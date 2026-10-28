import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.services import ai_service
from backend.services import graph


def test_cancelled_request_stays_cancelled_after_same_session_starts_next_request():
    session_id = "cancel-race-session"
    old_generation = ai_service.clear_session_cancel(session_id, "old-request")

    ai_service.request_cancel(session_id, "old-request")
    new_generation = ai_service.clear_session_cancel(session_id, "new-request")

    assert ai_service.is_session_cancelled(session_id, "old-request", old_generation)
    assert not ai_service.is_session_cancelled(session_id, "new-request", new_generation)


def test_late_cancel_only_marks_target_request_in_same_session():
    session_id = "late-cancel-race-session"
    old_generation = ai_service.clear_session_cancel(session_id, "old-request")
    new_generation = ai_service.clear_session_cancel(session_id, "new-request")

    ai_service.request_cancel(session_id, "old-request")

    assert ai_service.is_session_cancelled(session_id, "old-request", old_generation)
    assert not ai_service.is_session_cancelled(session_id, "new-request", new_generation)


def test_cancellation_cache_pressure_does_not_evict_an_active_request_signal():
    session_id = "cancel-cache-pressure-session"
    request_id = "active-protected-request"
    flood_prefix = "cancel-cache-pressure-flood-"
    generation = ai_service.clear_session_cancel(session_id, request_id)
    ai_service.register_cancel_request(session_id, request_id)
    try:
        ai_service.request_cancel(session_id, request_id)
        for index in range(ai_service._CANCELLED_SESSIONS_MAX):
            ai_service.request_cancel(session_id, flood_prefix + str(index))

        assert ai_service.is_session_cancelled(session_id, request_id, generation)
    finally:
        ai_service.finish_cancel_request(session_id, request_id)
        with ai_service._CANCEL_LOCK:
            for key in list(ai_service._cancelled_requests):
                if key == (session_id, request_id) or key[1].startswith(flood_prefix):
                    ai_service._cancelled_requests.pop(key, None)


def test_cancellation_cache_pressure_does_not_evict_an_active_legacy_session_signal():
    session_id = "legacy-cancel-cache-pressure-session"
    flood_prefix = "legacy-cancel-cache-pressure-flood-"
    ai_service.clear_session_cancel(session_id)
    ai_service.register_cancel_request(session_id)
    try:
        ai_service.request_cancel(session_id)
        for index in range(ai_service._CANCELLED_SESSIONS_MAX):
            ai_service.request_cancel(flood_prefix + str(index))

        assert ai_service.is_session_cancelled(session_id)
    finally:
        ai_service.finish_cancel_request(session_id)
        with ai_service._CANCEL_LOCK:
            ai_service._cancelled_sessions.pop(session_id, None)
            for key in list(ai_service._cancelled_sessions):
                if key.startswith(flood_prefix):
                    ai_service._cancelled_sessions.pop(key, None)


def test_session_generation_cache_pressure_preserves_active_legacy_global_cancel():
    session_id = "legacy-generation-cache-pressure-session"
    flood_prefix = "legacy-generation-cache-pressure-flood-"
    ai_service.clear_session_cancel(session_id)
    ai_service.register_cancel_request(session_id)
    try:
        for index in range(ai_service._CANCELLED_SESSIONS_MAX):
            ai_service.clear_session_cancel(flood_prefix + str(index))

        ai_service.request_cancel()

        assert ai_service.is_session_cancelled(session_id)
    finally:
        ai_service.finish_cancel_request(session_id)
        with ai_service._CANCEL_LOCK:
            ai_service._session_cancel_generation.pop(session_id, None)
            for key in list(ai_service._session_cancel_generation):
                if key.startswith(flood_prefix):
                    ai_service._session_cancel_generation.pop(key, None)


def test_stream_lifecycle_protects_cancel_signal_until_its_lock_lease_finishes(monkeypatch):
    session_id = "cancel-stream-lifecycle-session"
    request_id = "active-stream-request"
    flood_prefix = "cancel-stream-lifecycle-flood-"

    def one_event(**_kwargs):
        yield "data: {\"type\":\"thinking\"}\n\n"

    monkeypatch.setattr(graph, "_run_agent_stream_impl", one_event)
    stream = graph.run_agent_stream(
        messages=[], cfg=None, session_id=session_id, request_id=request_id,
    )
    try:
        assert next(stream).startswith("data:")
        ai_service.request_cancel(session_id, request_id)
        for index in range(ai_service._CANCELLED_SESSIONS_MAX):
            ai_service.request_cancel(session_id, flood_prefix + str(index))

        assert ai_service.is_session_cancelled(session_id, request_id)
        assert (session_id, request_id) in ai_service._active_cancel_requests
    finally:
        stream.close()
        with ai_service._CANCEL_LOCK:
            assert (session_id, request_id) not in ai_service._active_cancel_requests
            for key in list(ai_service._cancelled_requests):
                if key == (session_id, request_id) or key[1].startswith(flood_prefix):
                    ai_service._cancelled_requests.pop(key, None)


def test_request_scoped_start_does_not_clear_legacy_request_cancel():
    session_id = "mixed-client-cancel-session"
    ai_service.clear_session_cancel(session_id)
    ai_service.request_cancel(session_id)
    new_generation = ai_service.clear_session_cancel(session_id, "new-request")

    assert ai_service.is_session_cancelled(session_id)
    assert not ai_service.is_session_cancelled(session_id, "new-request", new_generation)


def test_cancel_endpoint_accepts_request_scoped_cancel():
    session_id = "cancel-route-session"
    old_generation = ai_service.clear_session_cancel(session_id, "old-request")
    new_generation = ai_service.clear_session_cancel(session_id, "new-request")

    response = TestClient(main.app).post(
        "/api/cancel", params={"session_id": session_id, "request_id": "old-request"}
    )

    assert response.status_code == 200
    assert ai_service.is_session_cancelled(session_id, "old-request", old_generation)
    assert not ai_service.is_session_cancelled(session_id, "new-request", new_generation)


def test_request_scoped_cancel_without_session_does_not_become_global_cancel():
    generation = ai_service._global_cancel_generation

    response = TestClient(main.app).post("/api/cancel", params={"request_id": "orphan-request"})

    assert response.status_code == 400
    assert ai_service._global_cancel_generation == generation


def test_nonstream_chat_route_forwards_request_id_to_ai_service(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "resolve_llm_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(main, "model_endpoint_transport_error", lambda *_args: None)
    monkeypatch.setattr(main, "chat_with_ai", lambda **kwargs: captured.update(kwargs) or {"response": "ok"})

    response = TestClient(main.app).post("/api/chat", json={
        "message": "hello", "session_id": "nonstream-route-session",
        "request_id": "nonstream-route-request",
    })

    assert response.status_code == 200
    assert captured["request_id"] == "nonstream-route-request"


def test_stream_short_command_does_not_run_pending_action_while_session_is_busy(monkeypatch, tmp_path):
    import asyncio
    import json
    from backend.services import pending_action, tools

    session_id = "busy-pending-action-session"
    monkeypatch.setattr(pending_action, "_STORE_DIR", str(tmp_path))
    monkeypatch.setattr(main, "resolve_llm_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(main, "model_endpoint_transport_error", lambda *_args: None)
    monkeypatch.setattr(ai_service, "_get_or_create_history", lambda *_args: [])
    monkeypatch.setattr(ai_service, "commit_assistant_reply", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    monkeypatch.setattr(tools, "_pending_qa_warnings", [])
    pending_action._memory.pop(session_id, None)
    action = pending_action.build_load_layer_action(
        "pending-points",
        geojson={"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [10, 20]},
        }]},
    )
    pending_action.set_pending_action(session_id, action)
    assert tools.acquire_session_lock(session_id, timeout=0)
    assert tools.acquire_shared_state_lock(0)
    pending_after = None
    registered_after = None
    pending_layers_after = None
    try:
        async def issue_confirmation():
            response = await main.chat_stream(main.ChatRequest(
                message="继续", session_id=session_id, request_id="busy-confirm-request",
            ))
            return "".join([
                chunk.decode() if isinstance(chunk, bytes) else chunk
                async for chunk in response.body_iterator
            ])

        payload = asyncio.run(issue_confirmation())
        pending_after = pending_action.get_pending_action(session_id)
        registered_after = dict(tools._registered_layers)
        pending_layers_after = list(tools._pending_layers)
    finally:
        tools.release_shared_state_lock()
        tools.release_session_lock(session_id)
        pending_action.clear_pending_action(session_id)
        pending_action._memory.pop(session_id, None)

    events = [json.loads(line[6:]) for line in payload.splitlines() if line.startswith("data: ")]
    assert events and events[0].get("busy") is True
    assert pending_after and pending_after["layers"][0]["name"] == "pending-points"
    assert registered_after == {}
    assert pending_layers_after == []


def test_nonstream_short_command_does_not_run_pending_action_while_session_is_busy(monkeypatch, tmp_path):
    import asyncio
    from backend.services import pending_action, tools

    session_id = "busy-pending-action-nonstream-session"
    monkeypatch.setattr(pending_action, "_STORE_DIR", str(tmp_path))
    monkeypatch.setattr(main, "resolve_llm_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(main, "model_endpoint_transport_error", lambda *_args: None)
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    pending_action._memory.pop(session_id, None)
    action = pending_action.build_load_layer_action(
        "pending-points",
        geojson={"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [10, 20]},
        }]},
    )
    pending_action.set_pending_action(session_id, action)
    assert tools.acquire_session_lock(session_id, timeout=0)
    assert tools.acquire_shared_state_lock(0)
    try:
        result = asyncio.run(main.chat(main.ChatRequest(
            message="继续", session_id=session_id, request_id="busy-confirm-nonstream",
        )))
        pending_after = pending_action.get_pending_action(session_id)
        registered_after = dict(tools._registered_layers)
        pending_layers_after = list(tools._pending_layers)
    finally:
        tools.release_shared_state_lock()
        tools.release_session_lock(session_id)
        pending_action.clear_pending_action(session_id)
        pending_action._memory.pop(session_id, None)

    assert result.get("busy") is True
    assert pending_after and pending_after["layers"][0]["name"] == "pending-points"
    assert registered_after == {}
    assert pending_layers_after == []


def test_cancelled_nonstream_result_is_not_committed_as_an_assistant_reply(monkeypatch):
    from backend.services import pending_action

    monkeypatch.setattr(ai_service, "clean_old_cache", lambda *_args: None)
    monkeypatch.setattr(ai_service, "_try_handle_confirm_command", lambda *_args: None)
    monkeypatch.setattr(pending_action, "build_choice_backfill", lambda *_args: None)
    monkeypatch.setattr(pending_action, "clear_pending_action", lambda *_args: None)
    monkeypatch.setattr(ai_service, "_get_or_create_history", lambda *_args: [])
    monkeypatch.setattr(ai_service, "_build_system_content", lambda *_args: ("system", "", "test"))
    monkeypatch.setattr(ai_service, "_rebase_history_context", lambda _sid, history: history)
    monkeypatch.setattr(ai_service, "_build_langgraph_messages", lambda _system, history: history)
    monkeypatch.setattr(graph, "run_agent", lambda **_kwargs: {
        "response": "用户已取消", "execution_status": "cancelled",
    })
    monkeypatch.setattr(ai_service, "commit_assistant_reply", lambda *_args, **_kwargs: pytest.fail(
        "cancelled response must not be committed as an assistant turn"
    ))

    result = ai_service.chat_with_ai(
        message="hello", session_id="cancelled-history-session",
        cfg=SimpleNamespace(model="test"), request_id="cancelled-history-request",
    )

    assert result["execution_status"] == "cancelled"


def test_blocked_model_stream_observes_cancel_promptly_and_retains_shared_lock_until_worker_stops():
    started = threading.Event()
    release_model = threading.Event()
    worker_stopped = threading.Event()
    lock_released = threading.Event()
    cancelled = threading.Event()

    def blocked_stream():
        started.set()
        try:
            release_model.wait(2)
            yield "late model result"
        finally:
            worker_stopped.set()

    lease = graph._DeferredLockLease(lock_released.set)
    stream = graph._stream_with_deadline(
        blocked_stream(), time.monotonic() + 3, lease=lease,
        cancel_check=cancelled.is_set,
    )
    result = []
    observed = threading.Event()

    def consume_until_cancel():
        result.append(next(stream))
        observed.set()

    consumer = threading.Thread(target=consume_until_cancel)
    consumer.start()
    assert started.wait(1)

    started_cancel = time.monotonic()
    cancelled.set()
    assert observed.wait(0.5)
    assert result == [graph._STREAM_CANCELLED]
    consumer.join(1)
    assert time.monotonic() - started_cancel < 0.5
    stream.close()
    lease.finish()

    assert not lock_released.is_set(), "shared state must stay locked while the model worker is active"
    release_model.set()
    assert worker_stopped.wait(1)
    assert lock_released.wait(1)


def test_simple_chat_bypass_observes_cancel_and_retains_locks_until_model_stops(monkeypatch):
    session_id = "cancel-simple-bypass-session"
    request_id = "cancel-simple-bypass-request"
    started = threading.Event()
    release_model = threading.Event()
    invoke_finished = threading.Event()
    consumer_done = threading.Event()
    events = []
    finish_records = []
    leases = []
    real_stream_with_deadline = graph._stream_with_deadline

    def capture_lease(*args, **kwargs):
        leases.append(kwargs.get("lease"))
        return real_stream_with_deadline(*args, **kwargs)

    class BlockingLLM:
        def invoke(self, _messages):
            started.set()
            release_model.wait(2)
            invoke_finished.set()
            return SimpleNamespace(content="迟到的模型回复")

    monkeypatch.setattr(graph, "reset_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph, "_tools_for_request", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(graph._tools_mod, "set_last_user_message", lambda *_args: None)
    monkeypatch.setattr(graph._tools_mod, "set_conversation_context", lambda *_args: None)
    monkeypatch.setattr(graph.pending_action, "set_active_session", lambda *_args: None)
    monkeypatch.setattr(graph, "_should_use_agent", lambda *_args: False)
    monkeypatch.setattr(graph, "build_llm", lambda *_args: BlockingLLM())
    monkeypatch.setattr(graph, "_stream_with_deadline", capture_lease)
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *_args, **_kwargs: "task")
    monkeypatch.setattr(graph, "set_current_task", lambda *_args: None)
    monkeypatch.setattr(graph, "_record_run_finish", lambda *args, **_kwargs: finish_records.append(args))
    from backend.services import storage_service
    monkeypatch.setattr(storage_service, "record_run_start", lambda *_args, **_kwargs: None)

    def consume():
        events.extend(graph.run_agent_stream(
            messages=[SimpleNamespace(content="你好")], cfg=SimpleNamespace(model="test"),
            session_id=session_id, request_id=request_id,
        ))
        consumer_done.set()

    consumer = threading.Thread(target=consume)
    consumer.start()
    try:
        assert started.wait(1)
        ai_service.request_cancel(session_id, request_id)
        assert consumer_done.wait(0.5), "simple chat should report cancellation without waiting for model.invoke"
        assert len(events) == 1 and '"type": "cancelled"' in events[0]
        assert finish_records and finish_records[-1][2] == "cancelled"
        assert leases and leases[0] is not None
        assert leases[0]._workers == 1 and not leases[0]._released
        assert (session_id, request_id) in ai_service._active_cancel_requests
        probe_acquired = graph._tools_mod.acquire_session_lock(session_id, 0)
        if probe_acquired:
            graph._tools_mod.release_session_lock(session_id)
        assert not probe_acquired, "session lock must remain held by the active model worker"
    finally:
        release_model.set()
        consumer.join(2)
    assert invoke_finished.wait(1)
    assert (session_id, request_id) not in ai_service._active_cancel_requests
    assert graph._tools_mod.acquire_session_lock(session_id)
    graph._tools_mod.release_session_lock(session_id)


def test_nonstream_agent_request_observes_cancel_while_agent_invoke_is_blocked(monkeypatch):
    session_id = "cancel-nonstream-agent-session"
    request_id = "cancel-nonstream-agent-request"
    started = threading.Event()
    release_agent = threading.Event()
    invoke_finished = threading.Event()
    call_done = threading.Event()
    result = {}

    class BlockingAgent:
        def invoke(self, payload, _config):
            started.set()
            release_agent.wait(2)
            invoke_finished.set()
            from langchain_core.messages import AIMessage
            return {"messages": list(payload["messages"]) + [AIMessage(content="迟到的 Agent 回复")]}

    empty_pending = {"layers": [], "images": [], "layer_ops": [], "qa_warnings": [],
                     "heatmap": None, "clear_layers": False, "aoi_suggestions": {"suggestions": None}}
    monkeypatch.setattr(graph, "reset_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph._tools_mod, "set_last_user_message", lambda *_args: None)
    monkeypatch.setattr(graph._tools_mod, "set_conversation_context", lambda *_args: None)
    monkeypatch.setattr(graph._tools_mod, "set_current_run", lambda *_args: None)
    monkeypatch.setattr(graph.pending_action, "set_active_session", lambda *_args: None)
    monkeypatch.setattr(graph, "_should_use_agent", lambda *_args: True)
    monkeypatch.setattr(graph, "build_llm", lambda *_args: object())
    monkeypatch.setattr(graph, "create_react_agent", lambda *_args: BlockingAgent())
    monkeypatch.setattr(graph, "get_pending_state", lambda: dict(empty_pending))
    monkeypatch.setattr(graph, "extract_and_record_token_usage", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(graph, "_GRAPH_TOTAL_TIMEOUT_S", 5)
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *_args, **_kwargs: "task")
    monkeypatch.setattr(graph, "set_current_task", lambda *_args: None)
    monkeypatch.setattr(graph, "_record_run_finish", lambda *_args, **_kwargs: None)
    from backend.services import storage_service
    monkeypatch.setattr(storage_service, "record_run_start", lambda *_args, **_kwargs: None)

    def call_nonstream():
        result.update(graph.run_agent(
            messages=[SimpleNamespace(content="请分析这个图层")], cfg=SimpleNamespace(model="test"),
            session_id=session_id, request_id=request_id,
        ))
        call_done.set()

    caller = threading.Thread(target=call_nonstream)
    caller.start()
    try:
        assert started.wait(1)
        ai_service.request_cancel(session_id, request_id)
        assert call_done.wait(0.5), "Agent-mode chat should return cancellation without waiting for agent.invoke"
        assert result.get("execution_status") == "cancelled"
        assert result.get("response") == "用户已取消"
        assert (session_id, request_id) in ai_service._active_cancel_requests
        probe_acquired = graph._tools_mod.acquire_session_lock(session_id, 0)
        if probe_acquired:
            graph._tools_mod.release_session_lock(session_id)
        assert not probe_acquired, "Agent request must hold its session lock until the active worker stops"
    finally:
        release_agent.set()
        caller.join(2)
    assert invoke_finished.wait(1)
    assert (session_id, request_id) not in ai_service._active_cancel_requests
    assert graph._tools_mod.acquire_session_lock(session_id)
    graph._tools_mod.release_session_lock(session_id)


def test_cancelled_agent_worker_does_not_start_a_late_tool(monkeypatch):
    session_id = "cancel-late-tool-session"
    request_id = "cancel-late-tool-request"
    started = threading.Event()
    release_agent = threading.Event()
    invoke_finished = threading.Event()
    call_done = threading.Event()
    tool_calls = []
    result = {}

    from langchain_core.tools import StructuredTool
    probe_tool = graph._tools_mod._recorded(StructuredTool.from_function(
        func=lambda: tool_calls.append("ran") or "side effect complete",
        name="cancel_guard_probe", description="Cancellation guard test tool",
    ))

    class BlockingAgent:
        def invoke(self, payload, _config):
            started.set()
            release_agent.wait(2)
            probe_tool.invoke({})
            invoke_finished.set()
            from langchain_core.messages import AIMessage
            return {"messages": list(payload["messages"]) + [AIMessage(content="迟到回复")]}

    empty_pending = {"layers": [], "images": [], "layer_ops": [], "qa_warnings": [],
                     "heatmap": None, "clear_layers": False, "aoi_suggestions": {"suggestions": None}}
    monkeypatch.setattr(graph, "reset_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph._tools_mod, "set_last_user_message", lambda *_args: None)
    monkeypatch.setattr(graph._tools_mod, "set_conversation_context", lambda *_args: None)
    monkeypatch.setattr(graph._tools_mod, "set_current_run", lambda *_args: None)
    monkeypatch.setattr(graph.pending_action, "set_active_session", lambda *_args: None)
    monkeypatch.setattr(graph, "_should_use_agent", lambda *_args: True)
    monkeypatch.setattr(graph, "build_llm", lambda *_args: object())
    monkeypatch.setattr(graph, "create_react_agent", lambda *_args: BlockingAgent())
    monkeypatch.setattr(graph, "get_pending_state", lambda: dict(empty_pending))
    monkeypatch.setattr(graph, "_GRAPH_TOTAL_TIMEOUT_S", 5)
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *_args, **_kwargs: "task")
    monkeypatch.setattr(graph, "set_current_task", lambda *_args: None)
    monkeypatch.setattr(graph, "_record_run_finish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph, "extract_and_record_token_usage", lambda *_args, **_kwargs: {})
    from backend.services import storage_service
    monkeypatch.setattr(storage_service, "record_run_start", lambda *_args, **_kwargs: None)

    def call_nonstream():
        result.update(graph.run_agent(
            messages=[SimpleNamespace(content="请执行一个图层操作")], cfg=SimpleNamespace(model="test"),
            session_id=session_id, request_id=request_id,
        ))
        call_done.set()

    caller = threading.Thread(target=call_nonstream)
    caller.start()
    try:
        assert started.wait(1)
        ai_service.request_cancel(session_id, request_id)
        assert call_done.wait(0.5)
        assert result.get("execution_status") == "cancelled"
        assert not tool_calls
    finally:
        release_agent.set()
        caller.join(2)
    assert invoke_finished.wait(1)
    assert not tool_calls, "cancelled request must not start a new tool after the model call returns"


def test_cancelled_stream_worker_does_not_start_a_late_tool():
    from langchain_core.tools import StructuredTool

    session_id = "cancelled-stream-tool-session"
    request_id = "cancelled-stream-tool-request"
    token = ai_service.set_request_cancel_context(session_id, request_id)
    generation = ai_service.clear_session_cancel(session_id, request_id)
    started = threading.Event()
    release_stream = threading.Event()
    worker_finished = threading.Event()
    tool_calls = []
    probe_tool = graph._tools_mod._recorded(StructuredTool.from_function(
        func=lambda: tool_calls.append("ran") or "side effect complete",
        name="cancelled_stream_probe", description="Stream cancellation guard test tool",
    ))

    def blocking_stream():
        started.set()
        release_stream.wait(2)
        probe_tool.invoke({})
        worker_finished.set()
        yield "late stream item"

    def cancel_after_stream_starts():
        assert started.wait(1)
        ai_service.request_cancel(session_id, request_id)
        release_stream.set()

    cancel_thread = threading.Thread(target=cancel_after_stream_starts)
    cancel_thread.start()
    try:
        events = list(graph._stream_with_deadline(
            blocking_stream(), time.monotonic() + 3,
            cancel_check=lambda: ai_service.is_session_cancelled(
                session_id, request_id, generation,
            ),
        ))
    finally:
        release_stream.set()
        cancel_thread.join(2)
        ai_service.reset_request_cancel_context(token)

    assert events[-1] is graph._STREAM_CANCELLED
    assert worker_finished.wait(1)
    assert not tool_calls


def test_empty_response_recovery_observes_request_cancel_while_invoke_is_blocked():
    session_id = "cancel-recovery-session"
    request_id = "cancel-recovery-request"
    generation = ai_service.clear_session_cancel(session_id, request_id)
    started = threading.Event()
    release_agent = threading.Event()
    invoke_finished = threading.Event()
    call_done = threading.Event()
    result = {}

    class BlockingAgent:
        def invoke(self, _payload, _config):
            started.set()
            release_agent.wait(2)
            invoke_finished.set()
            return {"messages": []}

    def call_recovery():
        result["value"] = graph._invoke_empty_response_recovery(
            BlockingAgent(), [SimpleNamespace(content="原始请求")], recursion_limit=1,
            timeout_s=5,
            cancel_check=lambda: ai_service.is_session_cancelled(session_id, request_id, generation),
        )
        call_done.set()

    caller = threading.Thread(target=call_recovery)
    caller.start()
    try:
        assert started.wait(1)
        ai_service.request_cancel(session_id, request_id)
        assert call_done.wait(0.5), "empty-response recovery should stop waiting when its request is cancelled"
        assert result.get("value") is graph._STREAM_CANCELLED
    finally:
        release_agent.set()
        caller.join(2)
    assert invoke_finished.wait(1)


def test_nonstream_simple_chat_bypass_observes_request_cancel_while_model_is_blocked(monkeypatch):
    session_id = "cancel-nonstream-simple-session"
    request_id = "cancel-nonstream-simple-request"
    started = threading.Event()
    release_model = threading.Event()
    invoke_finished = threading.Event()
    call_done = threading.Event()
    result = {}

    class BlockingLLM:
        def invoke(self, _messages):
            started.set()
            release_model.wait(2)
            invoke_finished.set()
            return SimpleNamespace(content="迟到的普通接口回复")

    monkeypatch.setattr(graph, "reset_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph._tools_mod, "set_last_user_message", lambda *_args: None)
    monkeypatch.setattr(graph._tools_mod, "set_conversation_context", lambda *_args: None)
    monkeypatch.setattr(graph.pending_action, "set_active_session", lambda *_args: None)
    monkeypatch.setattr(graph, "_should_use_agent", lambda *_args: False)
    monkeypatch.setattr(graph, "build_llm", lambda *_args: BlockingLLM())
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *_args, **_kwargs: "task")
    monkeypatch.setattr(graph, "set_current_task", lambda *_args: None)
    monkeypatch.setattr(graph, "_record_run_finish", lambda *_args, **_kwargs: None)
    from backend.services import storage_service
    monkeypatch.setattr(storage_service, "record_run_start", lambda *_args, **_kwargs: None)

    def call_nonstream():
        result.update(graph.run_agent(
            messages=[SimpleNamespace(content="你好")], cfg=SimpleNamespace(model="test"),
            session_id=session_id, request_id=request_id,
        ))
        call_done.set()

    caller = threading.Thread(target=call_nonstream)
    caller.start()
    try:
        assert started.wait(1)
        ai_service.request_cancel(session_id, request_id)
        assert call_done.wait(0.5), "ordinary chat should return cancellation without waiting for model.invoke"
        assert result.get("execution_status") == "cancelled"
        assert result.get("response") == "用户已取消"
        assert (session_id, request_id) in ai_service._active_cancel_requests
        probe_acquired = graph._tools_mod.acquire_session_lock(session_id, 0)
        if probe_acquired:
            graph._tools_mod.release_session_lock(session_id)
        assert not probe_acquired, "ordinary chat must keep its session lock until the model worker stops"
    finally:
        release_model.set()
        caller.join(2)
    assert invoke_finished.wait(1)
    assert (session_id, request_id) not in ai_service._active_cancel_requests
    assert graph._tools_mod.acquire_session_lock(session_id, 0)
    graph._tools_mod.release_session_lock(session_id)
