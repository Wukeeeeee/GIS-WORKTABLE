# -*- coding: utf-8 -*-
"""Layer 1: 单元测试 (Unit Tests)

测试目标：
1. Prompt 模板组装、核心准则约束（行动优先、单区规范、禁止过度追问、默认内置底图）；
2. 工具函数入参校验与上下文存取；
3. 未执行代码与"复制到本地/Jupyter"免责声明探测；
4. 结果质量守护（Result Guard）规则校验；
5. 纯逻辑测试，耗时极短（<1s），不依赖外部网络与大模型。

注：2026-10-12 与源码对齐——result_guard 当前 API 为 apply_guard/verify_result，
_is_unexecuted_code_or_disclaimer 签名为 (text, msgs)，Prompt 措辞同步更新。
"""
import pytest
from langchain_core.messages import ToolMessage
from backend.services.ai_service import SYSTEM_PROMPT, SYSTEM_PROMPT_GLM
from backend.services.tools import (
    set_conversation_context,
    get_conversation_context,
    tools as all_tools
)
from backend.services.graph import (
    _is_unexecuted_code_or_disclaimer,
    _RECOVERY_PROMPT_CODE_DUMP,
    _RECOVERY_PROMPT_NO_ACTION,
)
from backend.services.result_guard import apply_guard

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_system_prompt_contains_core_thematic_rules():
    """验证系统提示词中包含核心交付红线，严禁过度追问与推诿。

    注：GLM 专属提示词为精简版，仅校验通用红线子集。
    """
    # 主提示词：全部核心规则
    p = SYSTEM_PROMPT
    assert "严格继承前序实体" in p            # 1. 严格上下文继承
    assert "问卷式选项" in p                  # 2. 严禁过度追问与问卷
    assert "手动打字回复特定格式" in p        # 3. 严禁要求用户手动打字回复特定格式
    assert "索要本地" in p                    # 4. 严禁索要用户本地 shp
    assert "单区域" in p and "多区域" in p    # 5. 单要素与多要素专题图明确分流
    # GLM 提示词：通用红线子集
    g = SYSTEM_PROMPT_GLM
    assert "问卷式选项" in g
    assert "索要本地" in g


def test_conversation_context_storage_and_retrieval():
    """验证工具层上下文存储与提取机制（API 为字符串摘要）"""
    ctx = "用户想查鼓楼区的GDP2025年；回答：南京市鼓楼区 2025 年地区生产总值 2245.8 亿元。"
    set_conversation_context(ctx)
    retrieved = get_conversation_context()
    assert isinstance(retrieved, str)
    assert "鼓楼区" in retrieved
    assert "南京市鼓楼区" in retrieved


def test_unexecuted_code_detection():
    """验证未执行代码与'复制到本地/Jupyter'免责声明探测逻辑"""
    # 典型负面样本 1: 声明无法在此出图（无任何工具消息）
    text_disclaimer_1 = "我没法在这边直接跑出图片文件给你，但代码是完整可运行的，你复制到本地或 Jupyter 里直接出图。"
    assert _is_unexecuted_code_or_disclaimer(text_disclaimer_1, []) is True

    # 典型负面样本 2: 给出制图代码但未调用 execute_python
    text_code_block = (
        "以下是绘制专题图的完整代码：\n```python\n"
        "import matplotlib.pyplot as plt\nplt.figure()\nplt.savefig('output/test.png')\n```"
    )
    assert _is_unexecuted_code_or_disclaimer(text_code_block, []) is True

    # 典型负面样本 3: 让用户把代码存成本地运行
    text_dump = "平台不直接出图，请把下面代码存成 run.py 在本地执行。"
    assert _is_unexecuted_code_or_disclaimer(text_dump, []) is True

    # 正常样本: 已经调用过工具并正常回复（消息列表含 ToolMessage → 直接放行）
    text_normal = "已成功获取南京市鼓楼区边界并生成 2025 年经济数据看板图：output/gulou_2025.png"
    tool_msgs = [ToolMessage(content="ok", tool_call_id="call_1")]
    assert _is_unexecuted_code_or_disclaimer(text_normal, tool_msgs) is False

    # 纠错指令常量存在且包含关键约束（非流式/流式共用）
    assert "execute_python" in _RECOVERY_PROMPT_CODE_DUMP
    assert "严禁向用户声称" in _RECOVERY_PROMPT_CODE_DUMP
    assert "不要再只做口头承诺" in _RECOVERY_PROMPT_NO_ACTION


def test_tool_registry_schemas_integrity():
    """验证已注册的生产工具清单及描述完整性"""
    tool_names = [t.name for t in all_tools]
    # 核心工具必须存在
    assert "datav_boundary" in tool_names
    assert "spatial_graduated_colors" in tool_names
    assert "execute_python" in tool_names
    assert "create_chart" in tool_names
    assert "spatial_buffer" in tool_names


def test_result_guard_apply_guard_normal_text():
    """验证结果守护层对正常回复不误伤（apply_guard 当前 API）"""
    raw_response = "任务完成。这里是分析结果。"
    final_text, check = apply_guard(raw_response)
    assert isinstance(check, dict)
    assert "ok" in check
    assert check["ok"] is True
    assert final_text == raw_response
