"""Contract checks for semantic task grouping in the streamed execution cards."""

from backend.services.graph import _stream_step_descriptor, _stream_tool_failure
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
            yield {"messages": base + [ai, ToolMessage(content="NY result two", name="search_web", tool_call_id="ny-2")]}
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
    page_start = next(event for event in starts if event["tool_call_id"] == "read-1")
    assert page_start["step_id"] == starts[0]["step_id"]
    delta = next(event for event in events if event.get("type") == "layer_ops_delta")
    assert delta["step_id"] == next(event for event in starts if event["tool_call_id"] == "map-1")["step_id"]
    assert delta["layer_ops"][0]["action"] == "center"
    elevation_end = next(event for event in ends if event.get("tool_call_id") == "elev-1")
    assert elevation_end["status"] == "error" and elevation_end["is_error"] is True
    assert elevation_end["error_message"] == "未能从 Provider 获取任何 tile"
    url_end = next(event for event in ends if event.get("tool_call_id") == "url-1")
    assert url_end["status"] == "error" and url_end["is_error"] is True
    assert url_end["error_message"] == "数据抓取失败: URL 无法解析"
    assert any(event.get("type") == "done" for event in events)
