# -*- coding: utf-8 -*-
"""快速通道护栏：不走 Agent（因此没有任何工具）的「简单问题」捷径，
不能把模型「我来获取」这类空口承诺当成最终答复返回。

真实用例：用户问「我想看看广州地铁1号线的线路图」，因为文案命不中 GIS 关键词
（列表里只有"路线"没有"线路"），走了无工具的快速通道，模型回一句
「我来获取广州地铁1号线的线路和站点数据。」就成了最终输出，没有任何后续。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.graph import _looks_like_incomplete_promise

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRAPH = os.path.join(ROOT, "backend", "services", "graph.py")

REAL_CASE_MSG = "我想看看广州地铁1号线的线路图"
REAL_CASE_REPLY = "我来获取广州地铁1号线的线路和站点数据。"


def test_real_world_hollow_promise_is_detected():
    assert _looks_like_incomplete_promise(REAL_CASE_REPLY) is True


def test_normal_simple_reply_is_still_allowed():
    assert _looks_like_incomplete_promise("你好！我是 GIS 助手，可以帮你做空间分析。") is False
    assert _looks_like_incomplete_promise("广州地铁1号线全长约18.5公里，共16座车站。") is False


def test_transit_request_hits_agent_keywords():
    src = io.open(GRAPH, encoding="utf-8").read()
    gis = re.findall(r"'([^']+)'", re.search(r"_gis_kws = \[(.*?)\]", src, re.S).group(1))
    layer = re.findall(r"'([^']+)'", re.search(r"_layer_kws = \[(.*?)\]", src, re.S).group(1))
    hits = [k for k in (gis + layer) if k in REAL_CASE_MSG]
    assert hits, "地铁/线路类请求必须命中关键词，不能掉进无工具的快速通道"
    assert "地铁" in hits and "线路" in hits


def test_both_fast_paths_reject_hollow_promise():
    src = io.open(GRAPH, encoding="utf-8").read()
    assert src.count("_looks_like_incomplete_promise(_quick_text)") == 2, \
        "流式与非流式快速通道都要用空口承诺检测兜底"
    assert "改走 Agent 工具通道" in src

# --------------------------------------------------------------------------
# 快速通道行为：正常闲聊直接回；空口承诺必须改走 Agent；两条都要落台账
# --------------------------------------------------------------------------
class _Boom(Exception):
    """哨兵异常：用来证明代码真的走到了 Agent 分支。"""


class _FakeMsg(object):
    def __init__(self, content):
        self.content = content


class _FakeLLM(object):
    def __init__(self, reply):
        self.reply = reply

    def invoke(self, messages):
        return _FakeMsg(self.reply)


def _patch_stream_env(monkeypatch, reply):
    from backend.services import graph, storage_service, tools as _tools

    # 本测试直接驱动生成器（不经过 SSE 包装层的 finally），必须自己管好会话锁
    monkeypatch.setenv("GIS_SESSION_LOCK_WAIT", "0")
    monkeypatch.setattr(graph, "build_llm", lambda cfg: _FakeLLM(reply))
    monkeypatch.setattr(storage_service, "record_run_start", lambda *a, **k: True)
    finished = []
    monkeypatch.setattr(storage_service, "record_run_finish",
                        lambda *a, **k: (finished.append(a), True)[1])
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *a, **k: "test-task")
    return graph, _tools, finished


def _stream(graph, tools_mod, message, session_id):
    from langchain_core.messages import HumanMessage, SystemMessage

    msgs = [SystemMessage(content="system"), HumanMessage(content=message)]
    try:
        return list(graph.run_agent_stream(messages=msgs, cfg=None, session_id=session_id))
    finally:
        tools_mod.release_session_lock(session_id)


def test_hollow_promise_never_ends_on_the_fast_path(monkeypatch):
    """无工具的快速通道拿到「我来获取」时必须改走 Agent，而不是直接当答复。"""
    import pytest

    graph, tools_mod, _finished = _patch_stream_env(monkeypatch, "我来获取相关数据。")

    def _boom(*a, **k):
        raise _Boom()

    monkeypatch.setattr(graph, "create_react_agent", _boom)
    with pytest.raises(_Boom):
        _stream(graph, tools_mod, "帮我看看这个", "test-hollow-promise")


def test_normal_chat_reply_uses_fast_path_and_closes_ledger(monkeypatch):
    reply = "我是 GIS 助手，可以帮你做空间分析。"
    graph, tools_mod, finished = _patch_stream_env(monkeypatch, reply)
    lines = _stream(graph, tools_mod, "你是谁呀", "test-normal-chat")

    assert lines, "快速通道应当产出事件"
    assert '"type": "done"' in lines[-1], lines[-1][:200]
    assert "GIS 助手" in lines[-1]
    assert len(finished) == 1, "快速通道也必须把 run 标记完成，否则台账一直显示 running"
    run_id, text, status, guard = finished[0]
    assert text == reply and status == "success" and guard == "BYPASS"


def test_metro_request_routes_straight_to_agent(monkeypatch):
    """用户原始那句话现在必须直接进 Agent（带工具），不再走无工具快速通道。"""
    import pytest

    graph, tools_mod, _finished = _patch_stream_env(monkeypatch, REAL_CASE_REPLY)

    def _boom(*a, **k):
        raise _Boom()

    monkeypatch.setattr(graph, "create_react_agent", _boom)
    with pytest.raises(_Boom):
        _stream(graph, tools_mod, REAL_CASE_MSG, "test-metro-routing")