# -*- coding: utf-8 -*-
"""
多轮任务状态测试（不打真实 LLM / 网络，全本地确定性验证）

对应修复：跨轮 pending task 状态丢失。覆盖（按需求逐条）：
  测试 1  获取法国边界 → “继续”：执行上一轮挂起的 load_layer，把图层加载到地图
  测试 2  获取法国边界 → “取消”：清除 pending，不加载
  测试 3  没有 pending 时 “继续”：不会被确定性逻辑误执行，交回正常 AI
  测试 4  普通多轮“获取长沙道路”→“这个数据有多少条？”：历史不受影响
  测试 5  session 状态持久化语义：pending 随会话落盘（磁盘可恢复，不引数据库）
另附：短指令识别、显式 hold 工具写入、auto-promote（注册但未推送→挂起）。
"""
import json
import os
import sys
import threading

import pytest

from backend.services import pending_action, ai_service, tools
from backend.services.tool_modules import runtime
from backend.services.tools import (
    reset_state,
    _registered_layers,
    _pending_layers,
    _register_layer,
)

FRANCE_GJ = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[2.0, 42.0], [2.0, 50.0], [7.0, 50.0], [2.0, 42.0]]]},
        "properties": {"name": "France"},
    }],
}


def _isolate_multi_turn_state(monkeypatch, tmp_path):
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
        "_session_locks": {},
        "_raster_output_scope": threading.local(),
        "_temp_output_dir": str(tmp_path / "output"),
        "_workspace_dir": str(tmp_path / "workspace"),
    }
    mutable_names = {
        name for name in isolated_state
        if isinstance(getattr(runtime, name), (dict, list, threading.local))
    }
    original_values = {name: getattr(runtime, name) for name in mutable_names}
    aliases = []
    seen_modules = set()
    for module in tuple(sys.modules.values()):
        if module is None or id(module) in seen_modules or module in (runtime, tools):
            continue
        seen_modules.add(id(module))
        namespace = getattr(module, "__dict__", {})
        for name in mutable_names:
            if namespace.get(name) is original_values[name]:
                aliases.append((module, name, isolated_state[name]))

    with runtime._state_lock:
        for name, value in isolated_state.items():
            monkeypatch.setattr(tools, name, value)
        for module, name, value in aliases:
            monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(ai_service, "conversation_history", {})
    monkeypatch.setattr(pending_action, "_memory", {})
    monkeypatch.setattr(ai_service, "_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setattr(pending_action, "_STORE_DIR", str(tmp_path / "pending"))


@pytest.fixture(autouse=True)
def isolated_session_state(tmp_path, monkeypatch):
    """替换会话/runtime 状态，不清空进程共享历史或图层。"""
    active_session_token = pending_action._active_session.set("default")
    _isolate_multi_turn_state(monkeypatch, tmp_path)
    reset_state()
    try:
        yield
    finally:
        reset_state()
        pending_action._active_session.reset(active_session_token)


def test_multi_turn_fixture_restores_shared_history_and_runtime(tmp_path):
    outer_registry = runtime._registered_layers
    outer_pending = runtime._pending_layers
    outer_memory = pending_action._memory
    outer_history = ai_service.conversation_history
    outer_registry["outside-sentinel"] = {"sentinel": True}
    outer_pending.append({"name": "outside-sentinel"})
    outer_memory["outside-sentinel"] = {"action": "sentinel"}
    outer_history["outside-sentinel"] = [{"role": "user", "content": "sentinel"}]
    runtime.set_current_task("outside-multi-turn-task")
    previous_history_dir = ai_service._HISTORY_DIR
    previous_pending_dir = pending_action._STORE_DIR

    patcher = pytest.MonkeyPatch()
    try:
        _isolate_multi_turn_state(patcher, tmp_path / "nested-isolation")
        reset_state()
        _register_layer("nested-layer", FRANCE_GJ)
        pending_action._memory["nested"] = {"action": "nested"}
        ai_service.conversation_history["nested"] = [{"role": "user", "content": "nested"}]
        assert runtime._registered_layers is not outer_registry
        assert _registered_layers is runtime._registered_layers
        assert _pending_layers is runtime._pending_layers
        assert "nested-layer" in runtime._registered_layers
        assert pending_action._memory is not outer_memory
        assert ai_service.conversation_history is not outer_history
    finally:
        patcher.undo()

    assert runtime._registered_layers is outer_registry
    assert outer_registry["outside-sentinel"]["sentinel"]
    assert "nested-layer" not in outer_registry
    assert runtime._pending_layers is outer_pending
    assert outer_pending == [{"name": "outside-sentinel"}]
    assert pending_action._memory is outer_memory
    assert outer_memory["outside-sentinel"]["action"] == "sentinel"
    assert ai_service.conversation_history is outer_history
    assert outer_history["outside-sentinel"][0]["content"] == "sentinel"
    assert runtime.get_current_task_id() == "outside-multi-turn-task"
    assert ai_service._HISTORY_DIR == previous_history_dir
    assert pending_action._STORE_DIR == previous_pending_dir


def test_continue_command_loads_pending_layer_and_commits_history():
    session_id = "continue-pending-layer"
    action = pending_action.build_load_layer_action(
        "法国边界", geojson=FRANCE_GJ, summary="法国边界已就绪，等待确认。",
    )
    pending_action.set_pending_action(session_id, action)

    result = ai_service._try_handle_confirm_command(session_id, "继续")

    assert result is not None
    assert "已把图层「法国边界」加载到地图" in result["response"]
    assert [layer["name"] for layer in result["layers"]] == ["法国边界"]
    assert "法国边界" in runtime._registered_layers
    assert any(layer["name"] == "法国边界" for layer in runtime._pending_layers)
    assert pending_action.get_pending_action(session_id) is None
    assert not os.path.exists(pending_action._sidecar_path(session_id))

    history = ai_service.conversation_history[session_id]
    assert [entry["role"] for entry in history] == ["user", "assistant"]
    assert history[0]["content"] == "继续"
    assert "法国边界" in history[1]["content"]
    assert os.path.isfile(ai_service._history_path(session_id))
    assert ai_service._load_history(session_id) == history


def test_cancel_command_consumes_pending_without_loading_layer():
    session_id = "cancel-pending-layer"
    pending_action.set_pending_action(session_id, pending_action.build_load_layer_action(
        "法国边界", geojson=FRANCE_GJ, summary="法国边界已就绪。",
    ))

    result = ai_service._try_handle_confirm_command(session_id, "取消")

    assert result is not None
    assert "已取消" in result["response"]
    assert result["layers"] == []
    assert runtime._registered_layers == {}
    assert runtime._pending_layers == []
    assert pending_action.get_pending_action(session_id) is None
    assert [entry["role"] for entry in ai_service.conversation_history[session_id]] == [
        "user", "assistant",
    ]


def test_short_command_without_pending_action_falls_back_to_ai():
    session_id = "continue-without-pending"

    result = ai_service._try_handle_confirm_command(session_id, "继续")

    assert result is None
    assert session_id not in ai_service.conversation_history
    assert runtime._registered_layers == {}
    assert runtime._pending_layers == []


def test_pending_action_is_recovered_from_session_sidecar():
    session_id = "pending-action-recovery"
    pending = pending_action.build_load_layer_action(
        "法国边界", geojson=FRANCE_GJ, summary="等待确认加载法国边界。",
    )
    pending_action.set_pending_action(session_id, pending)
    sidecar = pending_action._sidecar_path(session_id)

    assert os.path.isfile(sidecar)
    pending_action._memory.pop(session_id)

    recovered = pending_action.get_pending_action(session_id)

    assert recovered["action"] == "load_layer"
    assert recovered["summary"] == "等待确认加载法国边界。"
    assert recovered["layers"][0]["name"] == "法国边界"
    assert recovered["layers"][0]["geojson"] == FRANCE_GJ


# ============================================================
# 短指令识别
# ============================================================

def test_short_command_classification():
    assert pending_action.classify_short_command("继续") == "continue"
    assert pending_action.classify_short_command("确认") == "continue"
    assert pending_action.classify_short_command("执行") == "continue"
    assert pending_action.classify_short_command("取消") == "cancel"
    assert pending_action.classify_short_command(" 继续。") == "continue"
    assert pending_action.classify_short_command("这个数据有多少条？") is None
    assert pending_action.classify_short_command("把长沙道路下载下来") is None


# ============================================================
# 测试 3：没有 pending 时，“继续”不会被确定性逻辑误执行
# ============================================================





# ============================================================
# 测试 1：获取法国边界 → “继续”执行 pending load_layer 并加载
# ============================================================





# ============================================================
# 测试 2：取消 → 清除 pending，不加载
# ============================================================



# ============================================================
# 测试 4：普通多轮对话历史不受影响
# ============================================================







# ============================================================
# 测试 5：pending 随会话持久化（磁盘可恢复），无需数据库
# ============================================================



# ============================================================
# producer：显式 hold 工具 + auto-promote（注册但未推送 → 挂起）
# ============================================================



