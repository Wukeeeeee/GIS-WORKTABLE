from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import threading
import time

from backend.services import graph, tools
from backend.services.llm_config import LLMConfig


def _patch_agent_run(monkeypatch, agent):
    class FakeLLM:
        pass

    monkeypatch.setattr(graph, "build_llm", lambda cfg: FakeLLM())
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, available_tools: agent)
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *args, **kwargs: "retry-safety-test")
    monkeypatch.setattr(graph, "_record_run_finish", lambda *args, **kwargs: None)
    monkeypatch.setattr(graph, "extract_and_record_token_usage", lambda **kwargs: {"type": "test"})
    monkeypatch.setattr(graph.result_guard, "apply_guard", lambda text, *args, **kwargs: (text, {"ok": True}))
    monkeypatch.setattr(graph, "_auto_promote_pending", lambda *args, **kwargs: None)


def _run_agent(session_id):
    user_text = "加载并导出分析结果"
    return graph.run_agent(
        [SystemMessage(content="test"), HumanMessage(content=user_text)],
        cfg=LLMConfig(api_key="mock", base_url="http://mock", model="mock"),
        original_message=user_text,
        session_id=session_id,
    )


def test_nonstream_does_not_retry_after_tool_started_and_returns_partial_map_ops(monkeypatch):
    class FakeAgent:
        calls = 0

        def invoke(self, payload, config=None):
            self.calls += 1
            for callback in config.get("callbacks", []):
                callback.on_tool_start({"name": "export_layer"}, "{}")
            tools._pending_layer_ops.append({"action": "dem_result", "name": "partial.tif.png"})
            raise ConnectionError("connection reset by peer")

    agent = FakeAgent()
    _patch_agent_run(monkeypatch, agent)

    result = _run_agent("nonstream-tool-retry-safety")

    assert agent.calls == 1
    assert "未自动重跑" in result["response"]
    assert result["layer_ops"] == [{"action": "dem_result", "name": "partial.tif.png"}]


def test_nonstream_still_retries_transient_error_before_any_tool(monkeypatch):
    class FakeAgent:
        calls = 0

        def invoke(self, payload, config=None):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("connection reset by peer")
            return {"messages": list(payload["messages"]) + [AIMessage(content="恢复成功") ]}

    agent = FakeAgent()
    _patch_agent_run(monkeypatch, agent)

    result = _run_agent("nonstream-pre-tool-retry-safety")

    assert agent.calls == 2
    assert result["response"] == "恢复成功"


def test_nonstream_provider_error_redacts_key_and_url_credentials(monkeypatch, capsys):
    key = "provider-key-sentinel"

    class FakeAgent:
        def invoke(self, payload, config=None):
            raise RuntimeError(
                f"provider echoed {key}; https://user:{key}@api.example.test/v1?api_key={key}"
            )

    _patch_agent_run(monkeypatch, FakeAgent())
    user_text = "加载并导出分析结果"
    result = graph.run_agent(
        [SystemMessage(content="test"), HumanMessage(content=user_text)],
        cfg=LLMConfig(api_key=key, base_url="https://api.example.test/v1", model="mock"),
        original_message=user_text,
        session_id="provider-error-redaction",
    )
    captured = capsys.readouterr()

    assert key not in result["response"]
    assert key not in captured.out
    assert key not in captured.err
    assert "AI 服务调用失败" in result["response"]


def test_budget_timeout_reports_background_work_and_holds_workspace_locks(monkeypatch):
    started = threading.Event()
    allow_finish = threading.Event()
    side_effect_finished = threading.Event()

    class FakeAgent:
        def invoke(self, payload, config=None):
            started.set()
            allow_finish.wait(timeout=3)
            for callback in config.get("callbacks", []):
                callback.on_tool_start({"name": "export_layer"}, "{}")
            tools._pending_layer_ops.append({"action": "dem_result", "name": "late-result.png"})
            side_effect_finished.set()
            return {"messages": list(payload["messages"]) + [AIMessage(content="后台调用完成") ]}

    agent = FakeAgent()
    _patch_agent_run(monkeypatch, agent)
    monkeypatch.setattr(graph, "_GRAPH_TOTAL_TIMEOUT_S", 0.5)
    monkeypatch.setenv("GIS_SESSION_LOCK_WAIT", "0")
    session_id = "agent-timeout-background-work"
    try:
        result = _run_agent(session_id)

        assert started.is_set()
        assert result.get("execution_status") == "timeout"
        assert "后台调用仍可能继续" in result["response"]
        assert tools.acquire_session_lock(session_id) is False
        assert tools.acquire_shared_state_lock(0) is False
        assert not side_effect_finished.is_set()
    finally:
        allow_finish.set()

    assert side_effect_finished.wait(timeout=2)
    deadline = time.monotonic() + 2
    acquired = False
    while time.monotonic() < deadline and not acquired:
        acquired = tools.acquire_session_lock(session_id)
        if not acquired:
            time.sleep(0.01)
    assert acquired
    tools.release_session_lock(session_id)
    assert tools.acquire_shared_state_lock(0) is True
    tools.release_shared_state_lock()
    tools.reset_state()
