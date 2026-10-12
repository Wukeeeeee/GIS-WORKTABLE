# -*- coding: utf-8 -*-
"""Layer 1: 单元测试 (Unit Tests)

测试目标：
1. Prompt 模板组装、核心准则约束（行动优先、单区规范、禁止过度追问、默认内置底图）；
2. 工具函数入参校验与上下文存取；
3. 未执行代码与“复制到本地/Jupyter”免责声明探测；
4. 结果质量守护（Result Guard）规则校验；
5. 纯逻辑测试，耗时极短（<1s），不依赖外部网络与大模型。
"""
import pytest
from backend.services.ai_service import SYSTEM_PROMPT, SYSTEM_PROMPT_GLM
from backend.services.tools import (
    set_conversation_context,
    get_conversation_context,
    _conversation_context,
    tools as all_tools
)
from backend.services.graph import _is_unexecuted_code_or_disclaimer
from backend.services.result_guard import sanitize_user_facing_response, guard_response_vs_tools

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_system_prompt_contains_core_thematic_rules():
    """验证系统提示词中包含核心交付红线，严禁过度追问与推诿"""
    for prompt in [SYSTEM_PROMPT, SYSTEM_PROMPT_GLM]:
        # 1. 严格上下文继承
        assert "多轮对话实体严格继承" in prompt
        # 2. 严禁过度追问与问卷
        assert "严禁过度追问与问卷式选择" in prompt
        # 3. 严禁要求用户手动打字回复特定格式
        assert "严禁要求用户回复特定格式" in prompt
        # 4. 严禁索要用户本地 shp
        assert "严禁要求用户提供本地" in prompt
        # 5. 单要素与多要素专题图明确分流
        assert "单区域" in prompt and "多区域" in prompt


def test_conversation_context_storage_and_retrieval():
    """验证工具层上下文存储与提取机制"""
    ctx = [
        {"role": "user", "content": "我想查一下鼓楼区的GDP2025年"},
        {"role": "assistant", "content": "南京市鼓楼区 2025 年地区生产总值 2245.8 亿元。"}
    ]
    set_conversation_context(ctx)
    retrieved = get_conversation_context()
    assert len(retrieved) == 2
    assert "鼓楼区" in retrieved[0]["content"]
    assert "南京市鼓楼区" in retrieved[1]["content"]


def test_unexecuted_code_detection():
    """验证未执行代码与'复制到本地/Jupyter'免责声明探测逻辑"""
    # 典型负面样本 1: 声明无法在此出图
    text_disclaimer_1 = "我没法在这边直接跑出图片文件给你，但代码是完整可运行的，你复制到本地或 Jupyter 里直接出图。"
    assert _is_unexecuted_code_or_disclaimer(text_disclaimer_1, False, 0) is True

    # 典型负面样本 2: 给出制图代码但未调用 execute_python
    text_code_block = "以下是绘制专题图的完整代码：\n```python\nimport matplotlib.pyplot as plt\nplt.figure()\nplt.savefig('output/test.png')\n```"
    assert _is_unexecuted_code_or_disclaimer(text_code_block, False, 0) is True

    # 典型负面样本 3: 给出裸 SVG XML
    text_svg = "你可以把以下代码保存为看板：\n```xml\n<svg width=\"800\" height=\"600\"><rect width=\"800\" height=\"600\" fill=\"#fff\"/></svg>\n```"
    assert _is_unexecuted_code_or_disclaimer(text_svg, False, 0) is True

    # 正常样本: 已经调用过工具并正常回复
    text_normal = "已成功获取南京市鼓楼区边界并生成 2025 年经济数据看板图：output/gulou_2025.png"
    assert _is_unexecuted_code_or_disclaimer(text_normal, True, 1) is False


def test_tool_registry_schemas_integrity():
    """验证已注册的生产工具清单及描述完整性"""
    tool_names = [t.name for t in all_tools]
    # 核心工具必须存在
    assert "datav_boundary" in tool_names
    assert "spatial_graduated_colors" in tool_names
    assert "execute_python" in tool_names
    assert "create_chart" in tool_names
    assert "spatial_buffer" in tool_names


def test_result_guard_sanitizer():
    """验证结果守护层对错误声明与幻觉信息的清洗处理"""
    raw_response = "任务完成。这里是分析结果。"
    sanitized = sanitize_user_facing_response(raw_response)
    assert sanitized == raw_response
