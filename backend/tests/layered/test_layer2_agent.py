# -*- coding: utf-8 -*-
"""Layer 2: Agent 测试 (Agent Tests)

测试目标：
1. 意图识别与工具选择：根据用户不同指令，选择正确的工具链；
2. 多轮对话上下文继承：第二轮短指令（如“需要专题图”）必须继承第一轮已确认的实体；
3. 杜绝过度追问：严禁向用户抛出方案 A/B 问卷，严禁索要本地 SHP；
4. 免责推诿拦截与强制执行：当模型输出未执行的制图代码或声称“无法直接出图”时，触发拦截重试；
5. 复用真实 LangGraph Agent 架构，不使用脱离生产代码的虚拟 Agent。
"""
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage
from backend.services.tools import (
    set_conversation_context,
    datav_boundary,
    _tools_mod,
    tools as all_tools
)
from backend.services.graph import _is_unexecuted_code_or_disclaimer, _format_agent_recovery_instruction

pytestmark = [pytest.mark.agent, pytest.mark.fast]


def test_agent_disambiguation_inherits_previous_turn_context():
    """验证 Agent 在多轮对话中自动根据上下文消除重名歧义，不反复弹窗"""
    # 模拟历史对话中已经确认南京市鼓楼区
    history_messages = [
        {"role": "user", "content": "我想查一下鼓楼区的GDP2025年"},
        {"role": "assistant", "content": "已查到官方数据：南京市鼓楼区 2025 年地区生产总值 2245.8 亿元。"}
    ]
    set_conversation_context(history_messages)

    # 在第二轮中直接请求"鼓楼区"（不带城市前缀）
    with patch("backend.services.datav_service.get_boundary_by_adcode") as mock_get_bound:
        mock_get_bound.return_value = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}, "properties": {"name": "鼓楼区"}}]
        }
        res = datav_boundary.invoke({"name": "鼓楼区"})

        # 断言：必须自动解析为南京市鼓楼区（adcode 320106），不应返回需要用户选择的歧义列表
        assert "南京市" in res or "320106" in res
        assert "多个名为" not in res
        assert "ask_user_choice" not in res


def test_agent_disclaimer_interception_generates_recovery_instruction():
    """验证 Agent 拦截到未执行免责声明时，生成强行执行工具调用的纠错指令"""
    disclaimer = "我没法在这边直接跑出图片文件给你，你复制到本地或 Jupyter 里直接出图。"
    is_bad = _is_unexecuted_code_or_disclaimer(disclaimer, has_tool_msgs=False, tool_call_count=0)
    assert is_bad is True

    instruction = _format_agent_recovery_instruction()
    # 纠错指令必须严厉命令模型立即调用 execute_python 出图
    assert "execute_python" in instruction
    assert "严禁" in instruction
    assert "禁止输出任何免责声明" in instruction


def test_agent_avoids_asking_scheme_choices_on_short_command():
    """验证当用户输入'需要专题图'时，Agent 规则严格禁止提供方案A/B供用户手动选择"""
    from backend.services.ai_service import SYSTEM_PROMPT
    # 规则中明确要求行动优先，直接交付
    assert "严禁要求用户手动打字回复固定格式指令" in SYSTEM_PROMPT
    assert "严禁主动要求用户选择方案" in SYSTEM_PROMPT
