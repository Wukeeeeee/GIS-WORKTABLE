"""Contract checks for semantic task grouping in the streamed execution cards."""

from backend.services.graph import _stream_step_descriptor, _stream_tool_failure, _stream_tool_warning
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest


@pytest.mark.parametrize("message", [
    "数据抓取失败: 未能解析 URL 所属的 GIS 服务或数据类型",
    "SQL 查询未通过: duplicate column name: _fid",
    "地理编码失败：INVALID_USER_KEY",
    "执行异常：Provider returned HTTP 400",
    "[ERROR] Scrapling is not installed",
])
def test_tool_failure_recognizes_existing_failure_message_formats(message):
    failed, reason = _stream_tool_failure(message)
    assert failed is True
    assert reason == message[:240]


def test_tool_failure_does_not_flag_successful_result_that_mentions_failure():
    message = "搜索结果说明‘查询失败’的排查方法，网页正文已成功读取。"
    assert _stream_tool_failure(message) == (False, "")


def test_web_search_and_page_reads_share_target_step():
    search_key, search_label, kind = _stream_step_descriptor(
        "search_web", {"query": "current weather in New York"}, "查一下纽约天气"
    )
    page_key, page_label, page_kind = _stream_step_descriptor(
        "fetch_webpage", {"url": "https://weather.example.com/nyc"}, "查一下纽约天气",
        {"key": search_key, "label": search_label},
    )
    assert kind == page_kind == "web"
    assert page_key == search_key
    assert page_label == search_label
    weather_key, weather_label, _ = _stream_step_descriptor(
        "fetch_weather_data", {"latitude": 40.7, "longitude": -74.0}, "查一下纽约的天气",
        {"key": search_key, "label": search_label},
    )
    assert weather_key == search_key
    assert weather_label == search_label


def test_different_web_targets_get_distinct_steps():
    new_york = _stream_step_descriptor("search_web", {"query": "New York weather today"}, "天气")[0]
    london = _stream_step_descriptor("search_web", {"query": "London weather today"}, "天气")[0]
    assert new_york != london


def test_distinct_task_categories_and_location_objects_do_not_merge():
    focus_key, focus_label, _ = _stream_step_descriptor(
        "focus_map", {"layer_name": "美国"}, "帮我定位到美国"
    )
    weather_key, weather_label, _ = _stream_step_descriptor(
        "fetch_weather_data", {"latitude": 40.7, "longitude": -74.0},
        "帮我定位到美国，查一下纽约的天气",
    )
    assert focus_key != weather_key
    assert "美国" in focus_label
    assert "纽约" in weather_label


def test_controlled_stream_events_correlate_parallel_calls_and_apply_map_delta(monkeypatch):
    from types import SimpleNamespace
    from backend.services import graph
    from backend.services.llm_config import LLMConfig

    # Keep the SSE contract test independent from the local encrypted task store.
    monkeypatch.setattr(graph.task_manager, "find_or_create_task", lambda *_args, **_kwargs: "sse-test-task")

    class FakeAgent:
        def stream(self, payload, config=None, **kwargs):
            base = list(payload["messages"])
            calls = [
                {"name": "search_web", "args": {"query": "New York weather"}, "id": "ny-1", "type": "tool_call"},
                {"name": "search_web", "args": {"query": "NYC current forecast"}, "id": "ny-2", "type": "tool_call"},
            ]
            ai = AIMessage(content="", tool_calls=calls)
            yield {"messages": base + [ai]}
            yield {"messages": base + [ai, ToolMessage(content="NY result one", name="search_web", tool_call_id="ny-1")]}
            yield {"messages": base + [ai, ToolMessage(content=json.dumps({"data": "x" * 1300, "partial": True}), name="search_web", tool_call_id="ny-2")]}
            web = AIMessage(content="", tool_calls=[{"name": "fetch_webpage", "args": {"url": "https://example.test/ny"}, "id": "read-1", "type": "tool_call"}])
            yield {"messages": base + [ai, ToolMessage(content="NY result two", name="search_web", tool_call_id="ny-2"), web]}
            yield {"messages": base + [ai, ToolMessage(content="NY result two", name="search_web", tool_call_id="ny-2"), web,
                                        ToolMessage(content="New York weather is clear", name="fetch_webpage", tool_call_id="read-1")]}
            focus = AIMessage(content="", tool_calls=[{"name": "focus_map", "args": {"center": "-98,39", "zoom": 4}, "id": "map-1", "type": "tool_call"}])
            yield {"messages": base + [focus]}
            tool = next(t for t in graph.tools if t.name == "focus_map")
            result = tool.invoke({"center": "-98,39", "zoom": 4})
            yield {"messages": base + [focus, ToolMessage(content=str(result), name="focus_map", tool_call_id="map-1")]}
            failed_call = AIMessage(content="", tool_calls=[{"name": "get_elevation_data", "args": {"latitude": 19.5, "longitude": 116.7}, "id": "elev-1", "type": "tool_call"}])
            yield {"messages": base + [focus, ToolMessage(content=str(result), name="focus_map", tool_call_id="map-1"), failed_call]}
            failed_result = '{"ok": false, "error": "未能从 Provider 获取任何 tile", "type": "DEMAreaOutOfRangeError"}'
            yield {"messages": base + [focus, ToolMessage(content=str(result), name="focus_map", tool_call_id="map-1"), failed_call,
                                        ToolMessage(content=failed_result, name="get_elevation_data", tool_call_id="elev-1")]}
            yield {"messages": base + [focus, ToolMessage(content=str(result), name="focus_map", tool_call_id="map-1"), failed_call,
                                        ToolMessage(content=failed_result, name="get_elevation_data", tool_call_id="elev-1"),
                                        AIMessage(content="已定位美国并查询纽约天气；高程获取失败。")]}
            text_failure = AIMessage(content="", tool_calls=[{"name": "fetch_gis_data_url", "args": {"url": "https://example.test/data"}, "id": "url-1", "type": "tool_call"}])
            yield {"messages": base + [text_failure]}
            text_failure_result = "数据抓取失败: URL 无法解析"
            yield {"messages": base + [text_failure, ToolMessage(content=text_failure_result, name="fetch_gis_data_url", tool_call_id="url-1")]}
            yield {"messages": base + [text_failure, ToolMessage(content=text_failure_result, name="fetch_gis_data_url", tool_call_id="url-1"),
                                        AIMessage(content="数据抓取失败，已保留已有图层。") ]}

    class FakeLLM:
        def invoke(self, *args, **kwargs):
            return SimpleNamespace(content="")

    monkeypatch.setattr(graph, "build_llm", lambda cfg: FakeLLM())
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, tools: FakeAgent())
    user_text = "帮我定位到美国，查一下纽约的天气"
    session = "controlled-step-sse"
    lines = list(graph.run_agent_stream(
        [SystemMessage(content="test"), HumanMessage(content=user_text)],
        cfg=LLMConfig(api_key="mock", base_url="http://mock", model="mock"),
        original_message=user_text, session_id=session,
    ))
    events = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
    starts = [event for event in events if event.get("type") == "tool_start"]
    ends = [event for event in events if event.get("type") == "tool_end"]
    assert [event["tool_call_id"] for event in starts[:2]] == ["ny-1", "ny-2"]
    assert starts[0]["step_id"] == starts[1]["step_id"]
    assert ends[0]["tool_call_id"] == "ny-1" and ends[1]["tool_call_id"] == "ny-2"
    assert ends[0]["step_id"] == starts[0]["step_id"]
    assert json.loads(starts[0]["input"]) == {"query": "New York weather"}
    assert ends[1]["has_warning"] is True
    with pytest.raises(ValueError):
        json.loads(ends[1]["output"])
    page_start = next(event for event in starts if event["tool_call_id"] == "read-1")
    assert page_start["step_id"] == starts[0]["step_id"]
    delta = next(event for event in events if event.get("type") == "layer_ops_delta")
    assert delta["step_id"] == next(event for event in starts if event["tool_call_id"] == "map-1")["step_id"]
    assert delta["layer_ops"][0]["action"] == "center"
    done = next(event for event in events if event.get("type") == "done")
    done_op = next(op for op in done["layer_ops"] if op["action"] == "center")
    assert done_op["_stream_id"] == delta["layer_ops"][0]["_stream_id"]
    assert done_op["_step_id"] == delta["step_id"]
    elevation_end = next(event for event in ends if event.get("tool_call_id") == "elev-1")
    assert elevation_end["status"] == "error" and elevation_end["is_error"] is True
    assert elevation_end["error_message"] == "未能从 Provider 获取任何 tile"
    url_end = next(event for event in ends if event.get("tool_call_id") == "url-1")
    assert url_end["status"] == "error" and url_end["is_error"] is True
    assert url_end["error_message"] == "数据抓取失败: URL 无法解析"


def test_stream_does_not_retry_whole_turn_after_tool_result_then_connection_error(monkeypatch):
    from types import SimpleNamespace
    from backend.services import graph
    from backend.services.llm_config import LLMConfig

    retry_calls = []

    class FakeAgent:
        def stream(self, payload, config=None, **kwargs):
            base = list(payload["messages"])
            call = {"name": "export_layer", "args": {"layer_name": "result"},
                    "id": "export-1", "type": "tool_call"}
            ai = AIMessage(content="", tool_calls=[call])
            yield {"messages": base + [ai]}
            yield {"messages": base + [ai, ToolMessage(
                content="GeoJSON已生成：/output/result.geojson",
                name="export_layer", tool_call_id="export-1",
            )]}
            raise ConnectionError("connection reset by peer")

    class FakeLLM:
        def invoke(self, *args, **kwargs):
            return SimpleNamespace(content="")

    def fake_retry(*args, **kwargs):
        retry_calls.append(True)
        return "ok", {"messages": [AIMessage(content="重试后的答复")]}

    monkeypatch.setattr(graph, "build_llm", lambda cfg: FakeLLM())
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, tools: FakeAgent())
    monkeypatch.setattr(graph, "_invoke_agent_with_budget", fake_retry)
    user_text = "导出 result 图层"
    events_raw = list(graph.run_agent_stream(
        [SystemMessage(content="test"), HumanMessage(content=user_text)],
        cfg=LLMConfig(api_key="mock", base_url="http://mock", model="mock"),
        original_message=user_text, session_id="stream-retry-after-tool-result",
    ))
    events = [json.loads(line[6:]) for line in events_raw if line.startswith("data: ")]

    assert retry_calls == []
    assert any(event.get("type") == "tool_end" and event.get("tool_call_id") == "export-1" for event in events)
    assert any(event.get("type") == "error" for event in events)
    assert any(event.get("type") == "done" for event in events)


def test_stream_provider_error_redacts_key_from_sse_and_console(monkeypatch, capsys):
    from backend.services import graph
    from backend.services.llm_config import LLMConfig

    key = "stream-provider-key-sentinel"

    class FakeAgent:
        def stream(self, payload, config=None, **kwargs):
            raise RuntimeError(
                f"provider echoed {key}; https://user:{key}@api.example.test/v1?api_key={key}"
            )

    class FakeLLM:
        def invoke(self, *args, **kwargs):
            return SimpleNamespace(content="")

    monkeypatch.setattr(graph, "build_llm", lambda cfg: FakeLLM())
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, tools: FakeAgent())
    user_text = "加载并导出分析结果"
    lines = list(graph.run_agent_stream(
        [SystemMessage(content="test"), HumanMessage(content=user_text)],
        cfg=LLMConfig(api_key=key, base_url="https://api.example.test/v1", model="mock"),
        original_message=user_text, session_id="stream-provider-error-redaction",
    ))
    captured = capsys.readouterr()
    events = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
    error = next(event for event in events if event.get("type") == "error")

    assert key not in error["message"]
    assert key not in captured.out
    assert key not in captured.err
    assert "provider echoed" in error["message"]


@pytest.mark.parametrize("content,expected", [
    ({"partial": True}, True), ({"warnings": ["skipped"]}, True),
    ({"qa_warnings": ["invalid"]}, True), ({"skipped_count": "2"}, True),
    ({"status": "partial"}, True), ({"ok": True, "warnings": []}, False),
    ({"skipped_count": "invalid"}, False), ("普通成功结果", False), ([], False),
])
def test_stream_preserves_explicit_partial_result_metadata(content, expected):
    assert _stream_tool_warning(content) is expected
    if isinstance(content, dict):
        assert _stream_tool_warning(json.dumps(content)) is expected


def test_workflow_progress_maps_node_completion_failure_and_skip():
    from backend.services.graph import _workflow_progress_tool_events

    active = {}
    common = {
        "type": "workflow_progress", "invocation_id": "wf-call-1",
        "workflow_name": "缓冲工作流",
    }
    started = _workflow_progress_tool_events({
        **common, "event": {"type": "workflow_node_started", "node_id": "buffer",
                            "name": "生成缓冲", "tool": "spatial_buffer"},
    }, active)
    completed = _workflow_progress_tool_events({
        **common, "event": {"type": "workflow_node_completed", "node_id": "buffer",
                            "name": "生成缓冲", "tool": "spatial_buffer"},
    }, active)
    assert started[0]["type"] == "tool_start"
    assert completed[0]["type"] == "tool_end"
    assert started[0]["tool_call_id"] == completed[0]["tool_call_id"]
    assert completed[0]["status"] == "success"

    failed = _workflow_progress_tool_events({
        **common, "event": {"type": "workflow_node_failed", "node_id": "centroid",
                            "name": "计算质心", "tool": "spatial_centroid", "error": "坏几何"},
    }, active)
    skipped = _workflow_progress_tool_events({
        **common, "event": {"type": "workflow_node_skipped", "node_id": "export",
                            "name": "导出结果", "tool": "export_layer", "error": "上游失败，跳过"},
    }, active)
    assert [event["type"] for event in failed] == ["tool_start", "tool_end"]
    assert failed[-1]["status"] == "error" and failed[-1]["error_message"] == "坏几何"
    assert [event["type"] for event in skipped] == ["tool_start", "tool_end"]
    assert skipped[-1]["status"] == "partial" and skipped[-1]["has_warning"] is True


def test_controlled_stream_forwards_langgraph_custom_workflow_events(monkeypatch):
    from types import SimpleNamespace
    from backend.services import graph
    from backend.services.llm_config import LLMConfig

    class FakeAgent:
        def stream(self, payload, config=None, **kwargs):
            assert kwargs.get("stream_mode") == ["values", "custom"]
            base = list(payload["messages"])
            call = {"name": "execute_workflow", "args": {"workflow_json": "{}"},
                    "id": "workflow-call-1", "type": "tool_call"}
            ai = AIMessage(content="", tool_calls=[call])
            yield {"messages": base + [ai]}
            custom = {"type": "workflow_progress", "invocation_id": "wf-call-1",
                      "workflow_name": "缓冲工作流"}
            yield ("custom", {**custom, "event": {
                "type": "workflow_node_started", "node_id": "buffer",
                "name": "生成缓冲", "tool": "spatial_buffer"}})
            yield ("custom", {**custom, "event": {
                "type": "workflow_node_completed", "node_id": "buffer",
                "name": "生成缓冲", "tool": "spatial_buffer"}})
            result = ToolMessage(content="工作流执行完成", name="execute_workflow", tool_call_id="workflow-call-1")
            yield {"messages": base + [ai, result]}
            yield {"messages": base + [ai, result, AIMessage(content="缓冲分析已完成。") ]}

    class FakeLLM:
        def invoke(self, *args, **kwargs):
            return SimpleNamespace(content="")

    monkeypatch.setattr(graph, "build_llm", lambda cfg: FakeLLM())
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, tools: FakeAgent())
    raw = list(graph.run_agent_stream(
        [SystemMessage(content="test"), HumanMessage(content="执行缓冲工作流")],
        cfg=LLMConfig(api_key="mock", base_url="http://mock", model="mock"),
        original_message="执行缓冲工作流", session_id="workflow-custom-progress",
    ))
    events = [json.loads(line[6:]) for line in raw if line.startswith("data: ")]
    node_start = next(event for event in events if event.get("name") == "spatial_buffer" and event["type"] == "tool_start")
    node_end = next(event for event in events if event.get("name") == "spatial_buffer" and event["type"] == "tool_end")
    assert node_start["tool_call_id"] == node_end["tool_call_id"]
    assert node_start["step_label"] == "缓冲工作流 · 生成缓冲"
    assert node_end["status"] == "success"
    assert any(event.get("type") == "done" for event in events)
