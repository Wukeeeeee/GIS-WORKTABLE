# -*- coding: utf-8 -*-
"""两阶段数据源选择（choose_option）测试"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import pending_action as pa
from backend.services import tools


def test_ask_user_choice_sets_pending():
    """ask_user_choice 工具应设置 choose_option pending"""
    pa.clear_pending_action("test_choice")
    pa.set_active_session("test_choice")
    result = tools.ask_user_choice.invoke({
        "prompt": "请选择数据源",
        "options": [
            {"label": "地理空间数据云", "configured": False},
            {"label": "Copernicus", "configured": True},
        ],
        "choice_key": "data_source",
    })
    action = pa.get_pending_action("test_choice")
    assert action is not None
    assert action["action"] == "choose_option"
    assert len(action["options"]) == 2
    assert action["choice_key"] == "data_source"
    assert action["options"][0]["label"] == "地理空间数据云"
    pa.clear_pending_action("test_choice")


def test_describe_action_returns_options():
    """describe_action 对 choose_option 应返回 options"""
    action = {
        "action": "choose_option",
        "summary": "请选择",
        "options": [{"label": "A"}, {"label": "B"}],
        "choice_key": "test",
    }
    desc = pa.describe_action(action)
    assert desc["action"] == "choose_option"
    assert len(desc["options"]) == 2
    assert desc["choice_key"] == "test"


def test_ask_user_choice_min_two_options():
    """少于 2 个选项应报错"""
    result = tools.ask_user_choice.invoke({
        "prompt": "test",
        "options": [{"label": "A"}],
    })
    assert "错误" in result or "至少" in result


def test_ask_user_choice_string_options():
    """字符串选项应自动规范化"""
    pa.clear_pending_action("test_choice2")
    pa.set_active_session("test_choice2")
    result = tools.ask_user_choice.invoke({
        "prompt": "test",
        "options": ["选项一", "选项二"],
    })
    action = pa.get_pending_action("test_choice2")
    assert action["options"][0]["label"] == "选项一"
    assert action["options"][0]["value"] == "选项一"
    pa.clear_pending_action("test_choice2")


def test_choose_option_persistence():
    """pending_action 应持久化到磁盘"""
    pa.clear_pending_action("test_persist")
    pa.set_active_session("test_persist")
    tools.ask_user_choice.invoke({
        "prompt": "test",
        "options": [{"label": "A"}, {"label": "B"}],
    })
    # 模拟重启：清内存
    pa._memory.pop("test_persist", None)
    action = pa.get_pending_action("test_persist")
    assert action is not None
    assert action["action"] == "choose_option"
    pa.clear_pending_action("test_persist")
    # 清理 sidecar
    sidecar = os.path.join(pa._STORE_DIR, "session_test_persist_pending.json")
    if os.path.exists(sidecar):
        os.remove(sidecar)
