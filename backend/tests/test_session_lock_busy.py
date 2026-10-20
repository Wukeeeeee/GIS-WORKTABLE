# -*- coding: utf-8 -*-
"""会话锁：上一条工具链还没收尾时，新请求应短暂等待而不是立刻回「会话忙」。

用户场景：右键「问 AI」时上一条请求仍在跑，旧逻辑会立刻返回
「当前会话已有请求在处理中，请等待上一条完成后再发送新消息。」，
前端把它当成 AI 的正式回答展示  看起来像工具跑完却答非所问。
"""
import os
import sys
import threading
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services import tools


def test_no_wait_mode_returns_busy_immediately(monkeypatch):
    monkeypatch.setenv("GIS_SESSION_LOCK_WAIT", "0")
    sid = "test-lock-nowait"
    assert tools.acquire_session_lock(sid) is True
    try:
        start = time.time()
        assert tools.acquire_session_lock(sid) is False
        assert time.time() - start < 1.0
    finally:
        tools.release_session_lock(sid)


def test_waits_until_previous_request_releases(monkeypatch):
    monkeypatch.setenv("GIS_SESSION_LOCK_WAIT", "5")
    sid = "test-lock-wait"
    assert tools.acquire_session_lock(sid) is True

    def release_later():
        time.sleep(0.4)
        tools.release_session_lock(sid)

    helper = threading.Thread(target=release_later)
    helper.start()
    start = time.time()
    got = tools.acquire_session_lock(sid)
    elapsed = time.time() - start
    helper.join()
    try:
        assert got is True, "锁释放后新请求应当拿到会话锁，而不是被判忙"
        assert elapsed >= 0.3, "应当真的等待了一段时间，而不是立刻返回"
    finally:
        tools.release_session_lock(sid)


def test_timeout_gives_up_and_returns_false(monkeypatch):
    monkeypatch.setenv("GIS_SESSION_LOCK_WAIT", "0.3")
    sid = "test-lock-timeout"
    assert tools.acquire_session_lock(sid) is True
    try:
        start = time.time()
        assert tools.acquire_session_lock(sid) is False
        assert time.time() - start >= 0.25
    finally:
        tools.release_session_lock(sid)


def test_run_agent_marks_busy_result(monkeypatch):
    monkeypatch.setenv("GIS_SESSION_LOCK_WAIT", "0")
    from backend.services import graph

    sid = "test-busy-run"
    assert tools.acquire_session_lock(sid) is True
    try:
        result = graph.run_agent(messages=[], cfg=None, session_id=sid)
        assert result.get("busy") is True, "忙时要带 busy 标记，前端才能不当成正文"
        assert "已有请求" in result.get("response", "")
    finally:
        tools.release_session_lock(sid)


def test_run_agent_stream_marks_busy_event(monkeypatch):
    monkeypatch.setenv("GIS_SESSION_LOCK_WAIT", "0")
    from backend.services import graph

    sid = "test-busy-stream"
    assert tools.acquire_session_lock(sid) is True
    try:
        lines = list(graph.run_agent_stream(messages=[], cfg=None, session_id=sid))
        assert lines, "忙时也应产出一条 done 事件"
        assert '"busy": true' in lines[0]
    finally:
        tools.release_session_lock(sid)


def test_run_agent_stream_releases_lock_when_initialization_fails(monkeypatch):
    from backend.services import graph

    sid = "test-stream-init-failure"

    def fail_build_llm(_cfg):
        raise RuntimeError("model initialization failed")

    monkeypatch.setattr(graph, "build_llm", fail_build_llm)
    stream = graph.run_agent_stream(messages=[], cfg=None, session_id=sid)
    with pytest.raises(RuntimeError, match="model initialization failed"):
        next(stream)

    assert tools.acquire_session_lock(sid) is True
    tools.release_session_lock(sid)


def test_run_agent_stream_releases_lock_when_consumer_disconnects(monkeypatch):
    from backend.services import graph

    sid = "test-stream-disconnect"

    def one_event(**_kwargs):
        yield "data: {\"type\":\"thinking\"}\n\n"

    monkeypatch.setattr(graph, "_run_agent_stream_impl", one_event)
    stream = graph.run_agent_stream(messages=[], cfg=None, session_id=sid)
    assert next(stream).startswith("data:")
    stream.close()

    assert tools.acquire_session_lock(sid) is True
    tools.release_session_lock(sid)


def test_contract_guards_across_backend_and_frontend():
    """一条链路的静态护栏：等待锁 -> busy 标记 -> 不写成历史 -> 前端不当事正文。"""
    import io
    import os

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    read = lambda rel: io.open(os.path.join(root, rel), encoding="utf-8").read()

    tools_src = read(os.path.join("backend", "services", "tools.py"))
    assert "GIS_SESSION_LOCK_WAIT" in tools_src, "会话锁需支持短暂等待（环境变量可调）"
    assert "lock.acquire(timeout=timeout)" in tools_src

    graph_src = read(os.path.join("backend", "services", "graph.py"))
    assert graph_src.count('"busy": True') == 2, "流式与非流式忙响应都要带 busy 标记"

    main_src = read(os.path.join("backend", "main.py"))
    assert 'not _evt.get("busy")' in main_src, "忙事件不能写入会话历史"
    assert 'output["busy"] = True' in main_src, "非流式入口要透传 busy 标记"

    ai_src = read(os.path.join("backend", "services", "ai_service.py"))
    assert 'if result.get("busy"):' in ai_src, "非流式忙响应不能写回会话历史"

    chat_src = read(os.path.join("frontend", "js", "chat.js"))
    assert "result.busy" in chat_src, "前端要识别忙标记，不能把提示语当成 AI 回答"
    assert "重试这条分析" in chat_src, "忙时要给出重试入口"
