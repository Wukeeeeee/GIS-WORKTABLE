# -*- coding: utf-8 -*-
"""两阶段数据源选择（choose_option）测试"""
import os, sys, json
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import pending_action as pa
from backend.services import tools
from backend.services.tool_modules import runtime


def _isolate_tool_runtime(monkeypatch, tmp_path):
    isolated_state = {
        "_registered_layers": {},
        "_pending_layers": [],
        "_pending_layer_ops": [],
        "_pending_images": [],
        "_pending_qa_warnings": [],
        "_pending_aoi_suggestions": {},
        "_pending_heatmap": {"latest": None},
        "_domain_fail": {},
        "_search_cache": {},
        "_search_last_hit": {},
        "_exec_log": [],
        "_clear_layers_flag": False,
        "_current_amap_key": "",
        "_search_call_count": 0,
        "_exec_call_count": 0,
        "_current_task_id": "",
        "_last_user_message": "",
        "_current_run_id": "",
        "_conversation_context": "",
        "_active_project_id": None,
        "_temp_output_dir": str(tmp_path / "output"),
        "_workspace_dir": str(tmp_path / "workspace"),
    }
    with runtime._state_lock:
        for name, value in isolated_state.items():
            monkeypatch.setattr(tools, name, value)


@pytest.fixture(autouse=True)
def isolate_pending_action_state(tmp_path, monkeypatch):
    active_session_token = pa._active_session.set("default")
    monkeypatch.setattr(pa, "_STORE_DIR", str(tmp_path / "pending"))
    monkeypatch.setattr(pa, "_memory", {})
    _isolate_tool_runtime(monkeypatch, tmp_path)
    try:
        yield
    finally:
        pa._active_session.reset(active_session_token)


def test_tool_runtime_isolation_restores_preexisting_state(tmp_path):
    outer_registry = runtime._registered_layers
    outer_pending = runtime._pending_layers
    outer_ops = runtime._pending_layer_ops
    outer_registry["outside-sentinel"] = {"sentinel": True}
    outer_pending.append({"name": "outside-sentinel"})
    outer_ops.append({"action": "outside-sentinel"})
    runtime.set_current_task("outside-choice-task")
    previous_output_dir = runtime._temp_output_dir

    patcher = pytest.MonkeyPatch()
    try:
        _isolate_tool_runtime(patcher, tmp_path / "nested-isolation")
        tools.reset_registered_layers([])
        tools.reset_state()
        tools._register_layer("nested-layer", {
            "type": "FeatureCollection", "features": [],
        })
        assert runtime._registered_layers is not outer_registry
        assert "nested-layer" in runtime._registered_layers
        assert runtime._pending_layers is not outer_pending
        assert runtime._pending_layer_ops is not outer_ops
    finally:
        patcher.undo()

    assert runtime._registered_layers is outer_registry
    assert outer_registry["outside-sentinel"]["sentinel"]
    assert "nested-layer" not in outer_registry
    assert runtime._pending_layers is outer_pending
    assert outer_pending == [{"name": "outside-sentinel"}]
    assert runtime._pending_layer_ops is outer_ops
    assert outer_ops == [{"action": "outside-sentinel"}]
    assert runtime.get_current_task_id() == "outside-choice-task"
    assert runtime._temp_output_dir == previous_output_dir


def test_cancel_choice_is_handled_without_requesting_an_llm(monkeypatch):
    from unittest.mock import Mock
    from backend.services import ai_service

    action = {"action": "choose_option", "summary": "选择数据源", "options": [{"label": "方案 A"}]}
    monkeypatch.setattr(pa, "get_pending_action", lambda session_id: action)
    clear = Mock()
    select = Mock()
    commit = Mock()
    monkeypatch.setattr(pa, "clear_pending_action", clear)
    monkeypatch.setattr(pa, "set_pending_action", select)
    monkeypatch.setattr(ai_service, "_get_or_create_history", lambda *args: {})
    monkeypatch.setattr(ai_service, "commit_assistant_reply", commit)
    result = ai_service._try_handle_confirm_command("choice-test", "取消")
    assert result is not None and "已取消" in result["response"]
    assert result["layers"] == []
    clear.assert_called_once_with("choice-test")
    select.assert_not_called()
    commit.assert_called_once()


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


def test_datav_boundary_disambiguation():
    """datav_boundary 遇到多地重名区县（如鼓楼区）时应自动调用 ask_user_choice 并设置 pending"""
    registered_layers = tools.get_registered_layers_snapshot()
    tools.reset_registered_layers([])
    tools.reset_state()
    pa.clear_pending_action("test_disambig")
    pa.set_active_session("test_disambig")
    try:
        tools.set_last_user_message("帮我分析鼓楼区")
        res = tools.datav_boundary.invoke({"name": "鼓楼区"})
        assert "选项" in res or "选择" in res
        action = pa.get_pending_action("test_disambig")
        assert action is not None
        assert action["action"] == "choose_option"
        assert action["choice_key"] == "region_disambiguation"
        labels = [o["label"] for o in action["options"]]
        assert any("南京" in l for l in labels)
        assert any("福州" in l for l in labels)
    finally:
        pa.clear_pending_action("test_disambig")
        tools.reset_state()
        tools.reset_registered_layers(registered_layers)
