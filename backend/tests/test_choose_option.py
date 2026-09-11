# -*- coding: utf-8 -*-
"""两阶段数据源选择（choose_option）测试"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import pending_action as pa
from backend.services import tools


def test_ask_user_choice_sets_pending():
    """ask_user_choice 工具应设置 choose_option pending；数据源选择会固定插入 Esri 快速巡检"""
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
    # 数据源选择会在最前面固定插入 Esri 快速巡检，共 3 个
    assert len(action["options"]) == 3
    assert action["choice_key"] == "data_source"
    assert action["options"][0]["value"] == "esri_quick_inspect"
    assert action["options"][0]["configured"] is True
    assert action["options"][1]["label"] == "地理空间数据云"
    pa.clear_pending_action("test_choice")


def test_context_is_saved_with_choice():
    """ask_user_choice 必须把本轮原始请求存进 pending，供下一轮回填"""
    pa.clear_pending_action("test_choice")
    pa.set_active_session("test_choice")
    tools.set_last_user_message("帮我下载上海市的 Sentinel-2 影像")
    tools.ask_user_choice.invoke({
        "prompt": "请选择数据源",
        "options": [
            {"label": "地理空间数据云", "configured": False},
            {"label": "Copernicus", "configured": True},
        ],
        "choice_key": "data_source",
    })
    action = pa.get_pending_action("test_choice")
    assert action["context"] == "帮我下载上海市的 Sentinel-2 影像"
    pa.clear_pending_action("test_choice")


def test_build_choice_backfill_prepends_original_task():
    """用户只回选项短标签时，原任务必须拼回去，否则模型会丢地名"""
    tools.set_last_user_message("巡检武汉市洪山区的卫星影像")
    pa.clear_pending_action("test_backfill")
    pa.set_active_session("test_backfill")
    tools.ask_user_choice.invoke({
        "prompt": "请选择数据源",
        "options": [
            {"label": "地理空间数据云", "configured": False},
            {"label": "Esri 快速巡检", "configured": True},
        ],
        "choice_key": "data_source",
    })
    try:
        msg = pa.build_choice_backfill("test_backfill", "Copernicus")
        assert msg is not None
        assert "巡检武汉市洪山区的卫星影像" in msg
        assert "Copernicus" in msg
        assert "不得更改或编造任务对象" in msg
    finally:
        pa.clear_pending_action("test_backfill")


def test_build_choice_backfill_returns_none_without_choice_pending():
    """没有任何选项挂起时不能凭空拼接上下文"""
    pa.clear_pending_action("test_backfill2")
    assert pa.build_choice_backfill("test_backfill2", "继续") is None


def test_build_choice_backfill_ignores_load_layer_action():
    """load_layer 是另一种 pending，不应触发选项回填"""
    pa.clear_pending_action("test_backfill3")
    pa.set_pending_action("test_backfill3", pa.build_load_layer_action("某图层"))
    try:
        assert pa.build_choice_backfill("test_backfill3", "继续") is None
    finally:
        pa.clear_pending_action("test_backfill3")


def test_build_choice_backfill_returns_none_when_context_empty():
    """pending 里没有上下文时保持原消息，不拼半截提示"""
    pa.clear_pending_action("test_backfill4")
    pa.set_pending_action("test_backfill4", {
        "action": "choose_option", "options": [], "choice_key": "k", "context": "",
    })
    try:
        assert pa.build_choice_backfill("test_backfill4", "某个选项") is None
    finally:
        pa.clear_pending_action("test_backfill4")