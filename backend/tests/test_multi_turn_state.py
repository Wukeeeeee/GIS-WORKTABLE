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



