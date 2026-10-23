import json

import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.services import graph
from backend.services.llm_config import LLMConfig


@pytest.fixture
def metered_usage(monkeypatch, tmp_path):
    from backend.services import token_usage_service
    monkeypatch.setattr(token_usage_service, "_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(token_usage_service, "_TOKEN_LOG_PATH", str(tmp_path / "tokens.jsonl"))
    return token_usage_service.extract_and_record_token_usage


def test_empty_stream_response_retries_original_request_with_tools(monkeypatch, metered_usage):
    recovery_calls = []
    bound_choices = []
    llm_configs = []

    class FakeLLM:
        def bind_tools(self, tools, **kwargs):
            bound_choices.append(kwargs.get("tool_choice"))
            return self

    class FakeAgent:
        def stream(self, payload, config=None, **kwargs):
            # 模拟思考模型只产出 reasoning，没有正文或结构化工具调用。
            yield {"messages": list(payload["messages"]) + [
                AIMessage(content="", additional_kwargs={"reasoning_content": "应该调用 get_registered_layers"},
                          usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11})
            ]}

        def invoke(self, payload, config=None):
            recovery_calls.append(payload["messages"][-1].content)
            call = AIMessage(content="", tool_calls=[{
                "name": "get_registered_layers", "args": {}, "id": "recovery-list-1", "type": "tool_call",
            }], usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})
            result = ToolMessage(
                content="当前图层：医院_POI(OSM)，共 12 个医院",
                name="get_registered_layers",
                tool_call_id="recovery-list-1",
            )
            answer = AIMessage(content="已读取医院图层信息。", usage_metadata={
                "input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
            })
            return {"messages": list(payload["messages"]) + [call, result, answer]}

    from backend.services import storage_service
    monkeypatch.setattr(graph, "build_llm", lambda cfg: (llm_configs.append(cfg) or FakeLLM()))
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, tools: FakeAgent())
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *args, **kwargs: "recovery-test")
    monkeypatch.setattr(storage_service, "record_run_start", lambda *args, **kwargs: True)
    monkeypatch.setattr(storage_service, "record_run_finish", lambda *args, **kwargs: True)
    monkeypatch.setattr(graph, "extract_and_record_token_usage", metered_usage)
    monkeypatch.setattr(graph._tools_mod, "acquire_session_lock", lambda *args, **kwargs: True)
    monkeypatch.setattr(graph._tools_mod, "release_session_lock", lambda *args, **kwargs: None)

    user_text = "计算已加载医院图层里距离最近的两家医院"
    events_raw = list(graph.run_agent_stream(
        [SystemMessage(content="test"), HumanMessage(content=user_text)],
        cfg=LLMConfig(api_key="mock", base_url="http://mock", model="mock", reasoning=True),
        original_message=user_text,
        session_id="empty-response-recovery-test",
    ))
    events = [json.loads(line[6:]) for line in events_raw if line.startswith("data: ")]
    starts = [event for event in events if event.get("type") == "tool_start"]
    ends = [event for event in events if event.get("type") == "tool_end"]
    done = next(event for event in events if event.get("type") == "done")

    assert recovery_calls and "结构化调用" in recovery_calls[0]
    assert bound_choices == [None, "required"]
    assert llm_configs[-1].reasoning is False
    assert starts[0]["tool_call_id"] == "recovery-list-1"
    assert ends[0]["tool_call_id"] == "recovery-list-1"
    assert starts[0]["step_id"] == ends[0]["step_id"]
    assert done["response"] == "已读取医院图层信息。"
    assert done["response"] != "(空响应)"
    assert done["token_usage"]["type"] == "api"
    assert done["token_usage"]["input_tokens"] == 22
    assert done["token_usage"]["output_tokens"] == 6


def test_empty_nonstream_response_does_not_retry_with_tools_disabled(monkeypatch, metered_usage):
    recovery_calls = []
    agent_invocations = 0
    bound_choices = []
    llm_configs = []

    class FakeLLM:
        def bind_tools(self, tools, **kwargs):
            bound_choices.append(kwargs.get("tool_choice"))
            return self

    class FakeAgent:
        def invoke(self, payload, config=None):
            nonlocal agent_invocations
            agent_invocations += 1
            if agent_invocations == 1:
                return {"messages": list(payload["messages"]) + [
                    AIMessage(content="", additional_kwargs={"reasoning_content": "应该调用最近邻工具"},
                              usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11})
                ]}
            recovery_calls.append(payload["messages"][-1].content)
            call = AIMessage(content="", tool_calls=[{
                "name": "nearest_pair", "args": {"layer_name": "医院_POI(OSM)"},
                "id": "recovery-pair-1", "type": "tool_call",
            }], usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})
            result = ToolMessage(
                content="最近的一对约 120 米",
                name="nearest_pair",
                tool_call_id="recovery-pair-1",
            )
            answer = AIMessage(content="最近的两家医院相距约 120 米。", usage_metadata={
                "input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
            })
            return {"messages": list(payload["messages"]) + [call, result, answer]}

    from backend.services import storage_service
    monkeypatch.setattr(graph, "build_llm", lambda cfg: (llm_configs.append(cfg) or FakeLLM()))
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, tools: FakeAgent())
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *args, **kwargs: "recovery-test")
    monkeypatch.setattr(storage_service, "record_run_start", lambda *args, **kwargs: True)
    monkeypatch.setattr(storage_service, "record_run_finish", lambda *args, **kwargs: True)
    monkeypatch.setattr(graph, "extract_and_record_token_usage", metered_usage)
    monkeypatch.setattr(graph._tools_mod, "acquire_session_lock", lambda *args, **kwargs: True)
    monkeypatch.setattr(graph._tools_mod, "release_session_lock", lambda *args, **kwargs: None)

    user_text = "已加载医院 POI 图层，距离最近的 2 个医院是哪两个"
    result = graph.run_agent(
        [SystemMessage(content="test"), HumanMessage(content=user_text)],
        cfg=LLMConfig(api_key="mock", base_url="http://mock", model="mock", reasoning=True),
        original_message=user_text,
        session_id="empty-response-recovery-nonstream-test",
    )

    assert recovery_calls and "结构化调用" in recovery_calls[0]
    assert bound_choices == [None, "required"]
    assert llm_configs[-1].reasoning is False
    assert "不要调用工具" not in recovery_calls[0]
    assert result["response"] == "最近的两家医院相距约 120 米。"
    assert result["token_usage"]["type"] == "api"
    assert result["token_usage"]["input_tokens"] == 22
    assert result["token_usage"]["output_tokens"] == 6


def test_required_tool_choice_failure_falls_back_to_non_reasoning_auto_tools(monkeypatch):
    created_agents = []

    class FakeLLM:
        tool_choice = None

        def bind_tools(self, tools, **kwargs):
            bound = FakeLLM()
            bound.tool_choice = kwargs.get("tool_choice")
            return bound

    class FakeAgent:
        def __init__(self, tool_choice):
            self.tool_choice = tool_choice

        def invoke(self, payload, config=None):
            if self.tool_choice == "required":
                raise RuntimeError("provider rejects required tool_choice")
            return {"messages": payload["messages"] + [AIMessage(content="fallback worked")]}

    def create_agent(llm, tools):
        if callable(llm):
            llm = llm({"messages": [HumanMessage(content="recovery")]}, None)
        agent = FakeAgent(getattr(llm, "tool_choice", None))
        created_agents.append(agent)
        return agent

    monkeypatch.setattr(graph, "build_llm", lambda cfg: FakeLLM())
    monkeypatch.setattr(graph, "create_react_agent", create_agent)
    original_agent = FakeAgent(None)
    result = graph._invoke_empty_response_recovery(
        original_agent,
        [HumanMessage(content="计算图层距离")],
        cfg=LLMConfig(api_key="mock", base_url="http://mock", model="mock", reasoning=True),
        available_tools=[object()],
    )

    assert [agent.tool_choice for agent in created_agents] == [None, "required"]
    assert result["messages"][-1].content == "fallback worked"


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("reject_required", [False, True])
def test_real_graph_recovers_screenshot_request_and_returns_line_layer(monkeypatch, streamed, reject_required):
    """真实 LangGraph/ToolNode + 模拟 HTTP 模型，覆盖空响应、恢复、工具、图层和收尾。"""
    import httpx
    from langchain_core.tools import tool
    from backend.services import storage_service
    from backend.services.llm_config import ReasoningChatOpenAI

    requests = []
    executions = []
    line = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {}, "geometry": {
            "type": "LineString", "coordinates": [[120.15, 30.25], [120.151, 30.25]],
        },
    }]}

    @tool
    def draw_connection() -> str:
        """Create a local test connection line and return it to the map."""
        executions.append(True)
        graph._tools_mod._push_layer("connection-regression", line)
        return "连接线已生成"

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body.get("tools"), "截图中的请求不能进入不绑定工具的快速通道"
        message = {"role": "assistant", "content": None}
        finish = "stop"
        if len(requests) == 1:
            message["reasoning_content"] = "需要先调用工具来生成连接线"
        elif body.get("tool_choice") == "required" and reject_required:
            return httpx.Response(400, json={"error": {
                "message": "required tool_choice is unsupported", "type": "invalid_request_error",
            }})
        elif any(msg["role"] == "tool" for msg in body["messages"]):
            assert body.get("tool_choice") != "required", "工具执行后必须恢复 auto，允许正常收尾"
            message["content"] = "已生成连接线。"
        else:
            message["tool_calls"] = [{
                "id": "connection-1", "type": "function",
                "function": {"name": "draw_connection", "arguments": "{}"},
            }]
            finish = "tool_calls"
        return httpx.Response(200, json={
            "id": "chat-test", "object": "chat.completion", "created": 1, "model": "mock",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        })

    cfg = LLMConfig(api_key="test-key", base_url="http://model.invalid/v1", model="mock", reasoning=True)
    monkeypatch.setattr(graph, "tools", [draw_connection])
    monkeypatch.setattr(graph, "GRAPH_TOKEN_BUDGET", 0)
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *a, **k: "connection-test")
    monkeypatch.setattr(storage_service, "record_run_start", lambda *a, **k: True)
    monkeypatch.setattr(storage_service, "record_run_finish", lambda *a, **k: True)
    monkeypatch.setattr(graph, "extract_and_record_token_usage", lambda **kwargs: {})
    monkeypatch.setattr(graph.pending_action, "get_pending_action", lambda sid: None)
    text = "将2个最近的医院之间连上线将2个将最近的医院跟麦当劳直接连上线"
    messages = [
        SystemMessage(content="Use the bound tool to create the requested connection."),
        HumanMessage(content="Earlier request"), AIMessage(content="Earlier completed result."),
        HumanMessage(content=text),
    ]
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        llm = ReasoningChatOpenAI(
            api_key="test-key", base_url=cfg.base_url, model="mock", http_client=client, max_retries=0,
        )
        monkeypatch.setattr(graph, "build_llm", lambda config: llm)
        if streamed:
            events = [json.loads(evt[6:]) for evt in graph.run_agent_stream(
                messages, cfg=cfg, original_message=text, session_id="connection-http-stream",
            ) if evt.startswith("data: ")]
            result = next(evt for evt in events if evt.get("type") == "done")
            assert any(evt.get("type") == "tool_start" for evt in events)
            assert any(evt.get("type") == "tool_end" for evt in events)
        else:
            try:
                result = graph.run_agent(messages, cfg=cfg, original_message=text, session_id="connection-http-sync")
            finally:
                # 正式非流式入口由 ai_service 的 finally 释放锁；这里直接驱动 graph。
                graph._tools_mod.release_session_lock("connection-http-sync")

    assert result["response"] == "已生成连接线。"
    assert executions == [True]
    assert any(layer["geojson"] == line for layer in result["layers"])
    assert requests[1]["tool_choice"] == "required"
    assert len(requests) == (4 if reject_required else 3)
