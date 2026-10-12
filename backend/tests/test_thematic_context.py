# -*- coding: utf-8 -*-
"""
多轮上下文复用、零过度追问与专题图生成自动化测试套件
覆盖交付要求四大场景：
1. 先查询 GDP，后要求制作专题图的多轮上下文继承测试
2. 未指定图型与底图时，优先使用合理默认行为而非追问
3. 重名地区在无明确上下文时的消歧处理，且禁止无故强推 4 城市对比
4. 缺少数据或边界时的合理降级与真实提示（不得捏造）
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from backend.services import tools as _tools_mod
from backend.services.tools import (
    reset_state,
    datav_boundary,
    spatial_graduated_colors,
    _registered_layers,
    set_last_user_message,
    set_conversation_context,
)
from backend.services.ai_service import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_GLM,
    _check_topic_relevance,
)


@pytest.fixture(autouse=True)
def clean_tool_state():
    reset_state()
    _registered_layers.clear()
    set_last_user_message("")
    set_conversation_context("")
    yield
    reset_state()
    _registered_layers.clear()
    set_last_user_message("")
    set_conversation_context("")


# ============================================================
# 场景 1：“先查询 GDP，后要求制作专题图”的多轮继承测试
# ============================================================

def test_multi_turn_context_inheritance_in_boundary():
    """
    第一轮查询了南京市鼓楼区 GDP；
    第二轮用户仅说“需要专题图”，未重复城市名。
    验证：即使传入“鼓楼区”，工具层能根据上一轮上下文自动消歧为“江苏省南京市鼓楼区”，
    不再触发二次弹窗，并成功获取该区边界。
    """
    # 模拟第一轮对话产生的上下文
    context_round1 = (
        "用户：我想查一下鼓楼区的GDP2025年\n"
        "AI：南京市鼓楼区 2025 年地区生产总值 2245.8 亿元，同比增长 5.2%..."
    )
    set_conversation_context(context_round1)
    set_last_user_message("需要专题图")

    # 模拟 fetch_boundary 返回有效南京鼓楼区 GeoJSON
    mock_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "鼓楼区", "adcode": 320106},
            "geometry": {"type": "Polygon", "coordinates": [[[118.7, 32.0], [118.8, 32.0], [118.8, 32.1], [118.7, 32.0]]]},
        }]
    }

    with patch("backend.services.datav_service.fetch_boundary", return_value=mock_geojson) as mock_fetch:
        result = datav_boundary.invoke({"name": "鼓楼区"}) if hasattr(datav_boundary, "invoke") else datav_boundary("鼓楼区")

        # 必须自动解析为江苏省南京市鼓楼区，不得弹出选择题
        mock_fetch.assert_called_with("江苏省南京市鼓楼区")
        assert "南京市鼓楼区" in result or "鼓楼区" in result
        assert "ask_user_choice" not in result


def test_topic_relevance_preserves_short_thematic_command():
    """
    验证短期指令如“需要专题图”、“做成图”不会被 _check_topic_relevance 误判为新话题而清空历史。
    """
    history = [
        {"role": "user", "content": "我想查一下鼓楼区的GDP2025年"},
        {"role": "assistant", "content": "南京市鼓楼区 2025 年地区生产总值 2245.8 亿元，同比增长 5.2%...三次产业结构比例为 0 : 6.2 : 93.8。"},
    ]

    # 短指令保持上下文
    assert _check_topic_relevance("需要专题图", history) is True
    assert _check_topic_relevance("做成图", history) is True
    assert _check_topic_relevance("在地图上展示指标", history) is True


# ============================================================
# 场景 2：未指定图型时，优先使用合理默认行为而非追问
# ============================================================

def test_system_prompt_rules_forbid_interrogation():
    """
    验证系统提示词中明确包含：
    1. 行动优先、杜绝盘问准则
    2. 严禁向用户抛出问卷式选项与格式指令（如“你回一句'方案A+...'”）
    3. 底图默认内置行政边界，严禁询问是否有 SHP / GeoJSON
    4. 单区专题图默认指标看板/信息图，要素数不足时不执行分级设色且不追问
    """
    for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_GLM):
        # 必须包含行动优先与禁止格式命令
        assert "行动优先" in prompt or "默认直接执行" in prompt
        assert "方案A" in prompt  # 提示词中作为反面案例禁止
        assert "严禁" in prompt
        # 必须包含底图默认内置与单区专题图处理规范
        assert "datav_boundary" in prompt
        assert "单区" in prompt or "单行政区" in prompt or "单个行政区" in prompt


def test_spatial_graduated_colors_single_polygon_graceful_guidance():
    """
    单行政区（只有一个要素）无法分级设色。
    验证：spatial_graduated_colors 给出清晰的专业指引（单要素已展示，建议结合指标面板交付），
    而不是晦涩报错或诱导 AI 去硬凑其他要素。
    """
    single_feature_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "南京市鼓楼区", "GDP": 2245.8},
            "geometry": {"type": "Polygon", "coordinates": [[[118.7, 32.0], [118.8, 32.0], [118.8, 32.1], [118.7, 32.0]]]},
        }]
    }

    _registered_layers["南京市鼓楼区"] = {
        "geojson": single_feature_geojson,
        "name": "南京市鼓楼区",
    }

    result = spatial_graduated_colors.invoke({"layer_name": "南京市鼓楼区", "field": "GDP"}) if hasattr(spatial_graduated_colors, "invoke") else spatial_graduated_colors("南京市鼓楼区", "GDP")
    assert "无法进行分级设色" in result or "无法分级" in result
    assert "指标面板" in result or "图表" in result


# ============================================================
# 场景 3：重名地区在无明确上下文时的消歧处理与禁止加戏
# ============================================================

def test_ambiguous_district_first_turn_requires_choice():
    """
    当第一轮用户输入重名区县“鼓楼区”，且既无上级市、也无历史上下文时：
    必须调用 ask_user_choice 弹出交互选项，不得擅自猜测南京或其他城市。
    """
    from backend.services import pending_action as pa
    pa.clear_pending_action("test_ambig_turn1")
    pa.set_active_session("test_ambig_turn1")
    set_last_user_message("我想查一下鼓楼区的GDP2025年")
    set_conversation_context("")

    res = datav_boundary.invoke({"name": "鼓楼区"}) if hasattr(datav_boundary, "invoke") else datav_boundary("鼓楼区")
    assert "选项" in res or "选择" in res

    action = pa.get_pending_action("test_ambig_turn1")
    assert action is not None
    assert action["action"] == "choose_option"
    assert action["choice_key"] == "region_disambiguation"
    labels = [o["label"] for o in action["options"]]
    assert any("南京" in l for l in labels)
    assert any("福州" in l for l in labels)
    pa.clear_pending_action("test_ambig_turn1")


def test_unambiguous_when_city_specified_in_query():
    """
    用户在输入中明确指明了城市（如“南京鼓楼区”或“南京市鼓楼区”）：
    必须直接执行，严禁弹出选项，严禁主动扩展为全国4个鼓楼区对比。
    """
    set_last_user_message("我想查一下南京市鼓楼区的GDP2025年")

    mock_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "鼓楼区", "adcode": 320106},
            "geometry": {"type": "Polygon", "coordinates": [[[118.7, 32.0], [118.8, 32.0], [118.8, 32.1], [118.7, 32.0]]]},
        }]
    }

    with patch("backend.services.datav_service.fetch_boundary", return_value=mock_geojson) as mock_fetch, \
         patch("backend.services.tools.ask_user_choice") as mock_choice:
        result = datav_boundary.invoke({"name": "南京市鼓楼区"}) if hasattr(datav_boundary, "invoke") else datav_boundary("南京市鼓楼区")
        assert not mock_choice.called
        assert "南京市鼓楼区" in result or "鼓楼区" in result


# ============================================================
# 场景 4：缺少数据或边界时的合理降级与真实提示（不得捏造）
# ============================================================

def test_missing_boundary_returns_truthful_failure():
    """
    当 DataV 无法获取指定区域边界时：
    返回明确、真实的错误说明，不得捏造虚假边界。
    """
    set_last_user_message("获取不存在的区域边界")
    with patch("backend.services.datav_service.fetch_boundary", return_value=None):
        result = datav_boundary.invoke({"name": "不存在的虚拟未知区"}) if hasattr(datav_boundary, "invoke") else datav_boundary("不存在的虚拟未知区")
        assert "获取失败" in result
        assert "DataV 未找到" in result


def test_spatial_graduated_colors_missing_field_reports_available_fields():
    """
    当图层缺少指定字段时：
    返回明确提示并列出所有可用字段，方便 Agent 正确修正，不得胡乱上色。
    """
    multi_feature_geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "玄武区", "population": 50}, "geometry": {"type": "Point", "coordinates": [118.7, 32.0]}},
            {"type": "Feature", "properties": {"name": "秦淮区", "population": 70}, "geometry": {"type": "Point", "coordinates": [118.8, 32.0]}},
        ]
    }
    _registered_layers["南京测试图层"] = {
        "geojson": multi_feature_geojson,
        "name": "南京测试图层",
    }

    result = spatial_graduated_colors.invoke({"layer_name": "南京测试图层", "field": "non_existent_gdp"}) if hasattr(spatial_graduated_colors, "invoke") else spatial_graduated_colors("南京测试图层", "non_existent_gdp")
    assert "没有字段" in result
    assert "可用字段" in result
    assert "population" in result


# ============================================================
# 场景 5：识别并拦截未执行 Python 代码或“无法直接出图”推脱言论
# ============================================================

def test_detect_unexecuted_code_and_disclaimer():
    """
    当模型输出“我没法在这边直接跑出图片文件给你，你复制到本地运行”，
    或输出了带有 plt.savefig / fig.savefig 的代码块却未调用任何工具时，
    _is_unexecuted_code_or_disclaimer 必须准确识别，以便触发强制执行补偿。
    """
    from backend.services.graph import _is_unexecuted_code_or_disclaimer
    from langchain_core.messages import AIMessage, ToolMessage

    msgs_no_tools = [AIMessage(content="这是一条消息")]
    msgs_with_tools = [ToolMessage(content="ok", tool_call_id="call_1")]

    # 1. 典型推脱话术（即便无代码块）
    disclaimer_text1 = "我没法在这边直接跑出图片文件给你，但代码是完整可运行的，你复制到本地或 Jupyter 里直接出图。"
    assert _is_unexecuted_code_or_disclaimer(disclaimer_text1, msgs_no_tools) is True
    # 如果已经调用过工具，则不再误判
    assert _is_unexecuted_code_or_disclaimer(disclaimer_text1, msgs_with_tools) is False

    # 2. 输出了包含 plt.savefig 代码块但未调工具
    code_block_text = (
        "好的，这是为您编写的绘图代码：\n"
        "```python\n"
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots()\n"
        "fig.savefig('output/test.png')\n"
        "```\n"
    )
    assert _is_unexecuted_code_or_disclaimer(code_block_text, msgs_no_tools) is True

    # 3. 正常文本回复不会被误判
    normal_text = "南京市鼓楼区 2025 年地区生产总值为 2245.8 亿元，同比增长 5.2%。"
    assert _is_unexecuted_code_or_disclaimer(normal_text, msgs_no_tools) is False

