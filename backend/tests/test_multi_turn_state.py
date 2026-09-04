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

import pytest

from backend.services import pending_action, ai_service
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


@pytest.fixture(autouse=True)
def isolated_session_state(tmp_path, monkeypatch):
    """把会话历史 / pending 目录指到临时目录，避免污染仓库 cache/history。"""
    monkeypatch.setattr(ai_service, "_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setattr(pending_action, "_STORE_DIR", str(tmp_path / "pending"))
    pending_action._memory.clear()
    ai_service.conversation_history.clear()
    reset_state()
    _registered_layers.clear()
    yield
    _registered_layers.clear()
    _pending_layers.clear()
    pending_action._memory.clear()
    ai_service.conversation_history.clear()


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

def test_no_pending_continue_is_not_intercepted(isolated_session_state):
    sid = "mt_no_pending"
    assert pending_action.get_pending_action(sid) is None
    r = ai_service._try_handle_confirm_command(sid, "继续")
    assert r is None                      # 交回正常 AI 流程
    assert _pending_layers == []          # 没有错误执行任何图层加载


def test_non_short_message_with_pending_is_not_intercepted(isolated_session_state):
    """即使有 pending，非短指令（如追问）也应走正常 AI，不清除 pending。"""
    sid = "mt_question"
    _register_layer("France", FRANCE_GJ)
    pending_action.promote_registered_undisplayed(sid, set(), [])
    assert pending_action.get_pending_action(sid) is not None
    r = ai_service._try_handle_confirm_command(sid, "这个数据有多少条？")
    assert r is None
    assert pending_action.get_pending_action(sid) is not None  # 仍在，可继续“继续/取消”


# ============================================================
# 测试 1：获取法国边界 → “继续”执行 pending load_layer 并加载
# ============================================================

def test_continue_runs_pending_load_layer(isolated_session_state):
    sid = "mt_continue"
    # 第 1 轮：法国边界已注册但未推送到地图（数据就绪、待确认）
    _register_layer("France", FRANCE_GJ)
    promoted = pending_action.promote_registered_undisplayed(sid, set(), [])
    assert promoted is not None
    assert promoted["action"] == "load_layer"
    assert promoted["layers"][0]["name"] == "France"

    # 第 2 轮：用户只发“继续”
    r = ai_service._try_handle_confirm_command(sid, "继续")
    assert r is not None
    assert r["layers"] and r["layers"][0]["name"] == "France"
    # 已被消费：pending 清除；图层已 push（SSE done 会把 layers 送达前端）
    assert pending_action.get_pending_action(sid) is None
    assert any(l.get("name") == "France" for l in _pending_layers)
    # 本轮已写回历史（user“继续”+ assistant 结果）
    roles = [m["role"] for m in ai_service.conversation_history[sid]]
    assert roles == ["user", "assistant"]


def test_continue_also_accepts_confirm_and_execute(isolated_session_state):
    for word in ("确认", "执行"):
        sid = f"mt_word_{word}"
        _register_layer("France", FRANCE_GJ)
        pending_action.promote_registered_undisplayed(sid, set(), [])
        r = ai_service._try_handle_confirm_command(sid, word)
        assert r is not None and r.get("layers")
        assert pending_action.get_pending_action(sid) is None
        _registered_layers.clear()
        _pending_layers.clear()


# ============================================================
# 测试 2：取消 → 清除 pending，不加载
# ============================================================

def test_cancel_clears_pending(isolated_session_state):
    sid = "mt_cancel"
    _register_layer("France", FRANCE_GJ)
    pending_action.promote_registered_undisplayed(sid, set(), [])
    assert pending_action.get_pending_action(sid) is not None

    r = ai_service._try_handle_confirm_command(sid, "取消")
    assert r is not None
    assert not r.get("layers")                 # 没有加载到地图
    assert pending_action.get_pending_action(sid) is None
    assert _pending_layers == []


# ============================================================
# 测试 4：普通多轮对话历史不受影响
# ============================================================

def test_normal_multiturn_history_preserved(isolated_session_state):
    sid = "mt_road"
    ai_service._get_or_create_history(sid, "获取长沙道路")
    ai_service.commit_assistant_reply(sid, "已获取长沙道路数据，共 12345 条边，已加载到地图。")
    assert [m["role"] for m in ai_service.conversation_history[sid]] == ["user", "assistant"]

    # 用户追问（引用上一条结果）——历史不得被话题检测清空
    ai_service._get_or_create_history(sid, "这个数据有多少条？")
    ai_service.commit_assistant_reply(sid, "一共 12345 条。")
    roles = [m["role"] for m in ai_service.conversation_history[sid]]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_short_word_history_not_wiped(isolated_session_state):
    sid = "mt_short"
    ai_service._get_or_create_history(sid, "获取法国边界")
    ai_service.commit_assistant_reply(sid, "法国的边界数据已经获取成功，回复“继续”即可加载到地图。")
    ai_service._get_or_create_history(sid, "继续")
    roles = [m["role"] for m in ai_service.conversation_history[sid]]
    assert roles == ["user", "assistant", "user"]   # 上下文仍保留


def test_long_unrelated_new_topic_can_reset_history(isolated_session_state):
    """长度足够、且与近期对话零字面重叠的新请求才允许清历史（保守话题切换）。"""
    sid = "mt_switch"
    ai_service._get_or_create_history(sid, "获取法国边界")
    ai_service.commit_assistant_reply(sid, "法国的边界数据已经获取成功。")
    ai_service._get_or_create_history(sid, "请把北京市的全部湖泊绘成地图并导出")
    # 全新长主题 → 允许清空旧历史（只留本次 user）
    roles = [m["role"] for m in ai_service.conversation_history[sid]]
    assert roles == ["user"]


# ============================================================
# 测试 5：pending 随会话持久化（磁盘可恢复），无需数据库
# ============================================================

def test_pending_action_persists_across_restart(isolated_session_state):
    sid = "mt_persist"
    a = pending_action.build_load_layer_action(
        layer_name="France", geojson=FRANCE_GJ, source="geoBoundaries",
        dataset="France administrative boundary",
        summary="法国边界已就绪，等待确认。",
    )
    pending_action.set_pending_action(sid, a)
    # 模拟进程重启：清空内存后再取 → 从磁盘恢复
    pending_action._memory.clear()
    got = pending_action.get_pending_action(sid)
    assert got is not None
    assert got["action"] == "load_layer"
    assert got["layers"][0]["name"] == "France"
    assert got["params"].get("dataset") == "France administrative boundary"
    assert got.get("created_at")

    pending_action.clear_pending_action(sid)
    pending_action._memory.clear()
    assert pending_action.get_pending_action(sid) is None


# ============================================================
# producer：显式 hold 工具 + auto-promote（注册但未推送 → 挂起）
# ============================================================

def test_hold_layer_tool_sets_pending_for_active_session(isolated_session_state):
    from backend.services.tools import hold_layer_for_confirm
    pending_action.set_active_session("mt_hold")
    out = hold_layer_for_confirm.invoke({
        "name": "France",
        "geojson": json.dumps(FRANCE_GJ, ensure_ascii=False),
        "source": "geoBoundaries",
        "summary": "geoBoundaries 法国 ADM0 边界",
    })
    assert "继续" in out
    act = pending_action.get_pending_action("mt_hold")
    assert act is not None
    assert act["action"] == "load_layer"
    assert act["layers"][0]["name"] == "France"
    assert act["layers"][0]["source"] == "geoBoundaries"
    # 没有立刻推送到地图（等确认）
    assert not any(l.get("name") == "France" for l in _pending_layers)
    pending_action.clear_pending_action("mt_hold")


def test_auto_promote_skips_explicit_pending(isolated_session_state):
    """显式挂起（hold）后，auto-promote 不应覆盖同会话的既有 pending。"""
    sid = "mt_skip"
    from backend.services.tools import hold_layer_for_confirm
    pending_action.set_active_session(sid)
    hold_layer_for_confirm.invoke({"name": "France", "geojson": json.dumps(FRANCE_GJ)})
    explicit = pending_action.get_pending_action(sid)
    # 注册新图层触发 auto-promote
    _register_layer("Other", FRANCE_GJ)
    promoted = pending_action.promote_registered_undisplayed(sid, set(), [])
    assert promoted is None                      # 有显式 pending → 不覆盖
    got = pending_action.get_pending_action(sid)
    assert got["layers"][0]["name"] == explicit["layers"][0]["name"] == "France"
    pending_action.clear_pending_action(sid)
