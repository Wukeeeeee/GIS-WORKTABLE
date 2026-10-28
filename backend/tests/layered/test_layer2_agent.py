# -*- coding: utf-8 -*-
"""Layer 2: Agent 测试 (Agent Tests)

测试目标：
1. 意图识别与工具选择：根据用户不同指令，选择正确的工具链；
2. 多轮对话上下文继承：第二轮短指令（如“需要专题图”）必须继承第一轮已确认的实体；
3. 杜绝过度追问：严禁向用户抛出方案 A/B 问卷，严禁索要本地 SHP；
4. 免责推诿拦截与强制执行：当模型输出未执行的制图代码或声称“无法直接出图”时，触发拦截重试；
5. 复用真实 LangGraph Agent 架构，不使用脱离生产代码的虚拟 Agent。

注：2026-10-12 与源码对齐——graph.py 纠错指令已抽为
_RECOVERY_PROMPT_CODE_DUMP / _RECOVERY_PROMPT_NO_ACTION 常量，检测函数签名为 (text, msgs)。
"""
import pytest
from unittest.mock import patch
from backend.services.tools import (
    set_conversation_context,
    datav_boundary,
    tools as all_tools
)
from backend.services.graph import (
    _is_unexecuted_code_or_disclaimer,
    _RECOVERY_PROMPT_CODE_DUMP,
)

pytestmark = [pytest.mark.agent, pytest.mark.fast]


def test_agent_disambiguation_inherits_previous_turn_context():
    """验证 Agent 在多轮对话中自动根据上下文消除重名歧义，不反复弹窗"""
    # 模拟历史对话中已经确认南京市鼓楼区（set_conversation_context 接收字符串摘要）
    set_conversation_context(
        "用户想查鼓楼区的GDP2025年；已查到官方数据：南京市鼓楼区 2025 年地区生产总值 2245.8 亿元。"
    )

    # 在第二轮中直接请求"鼓楼区"（不带城市前缀）
    with patch("backend.services.datav_service.fetch_boundary") as mock_get_bound:
        mock_get_bound.return_value = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[118.76, 32.03], [118.78, 32.03], [118.78, 32.05], [118.76, 32.05], [118.76, 32.03]]],
                },
                "properties": {"name": "鼓楼区"},
            }]
        }
        res = datav_boundary.invoke({"name": "鼓楼区"})

        # 断言：必须自动解析为南京市鼓楼区（adcode 320106），不应返回需要用户选择的歧义列表
        assert "南京市" in res or "320106" in res
        assert "多个名为" not in res
        assert "ask_user_choice" not in res


def test_agent_disclaimer_interception_generates_recovery_instruction():
    """验证 Agent 拦截到未执行免责声明时，存在强行执行工具调用的纠错指令"""
    disclaimer = "我没法在这边直接跑出图片文件给你，你复制到本地或 Jupyter 里直接出图。"
    is_bad = _is_unexecuted_code_or_disclaimer(disclaimer, [])
    assert is_bad is True

    # 纠错指令必须命令模型立即调用 execute_python 出图，禁止免责话术
    assert "execute_python" in _RECOVERY_PROMPT_CODE_DUMP
    assert "严禁" in _RECOVERY_PROMPT_CODE_DUMP
    assert "无法直接出图" in _RECOVERY_PROMPT_CODE_DUMP


def test_agent_avoids_asking_scheme_choices_on_short_command():
    """验证当用户输入'需要专题图'时，Agent 规则严格禁止提供方案A/B供用户手动选择"""
    from backend.services.ai_service import SYSTEM_PROMPT
    # 规则中明确要求行动优先，直接交付
    assert "手动打字回复特定格式" in SYSTEM_PROMPT
    assert "问卷式选项" in SYSTEM_PROMPT
