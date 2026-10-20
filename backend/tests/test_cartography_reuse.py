"""Local regression coverage for thematic-map edits and reusable map state."""
import json
import uuid
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.services import history_service, storage_service, task_manager
from backend.services import tools as gis_tools


@pytest.fixture
def local_map(monkeypatch, tmp_path):
    monkeypatch.setattr(task_manager, "_BASE_DIR", str(tmp_path / "tasks"))
    task_manager._tasks.clear()
    task_manager._session_active.clear()
    history_service.set_history_file(str(tmp_path / "history.json"))
    old_db = storage_service.get_db_path()
    storage_service.set_db_path(str(tmp_path / "workspace.db"))
    task_id = task_manager.create_task("长沙人口分布图", "cartography-local-session")
    gis_tools.reset_state(task_id=task_id)
    gis_tools.set_current_run("cartography-run-1")
    features = []
    for i, population in enumerate((1, 2, 3, 4, 100)):
        x = 112.9 + i * 0.02
        features.append({
            "type": "Feature",
            "properties": {"name": f"长沙区{i + 1}", "population": population},
            "geometry": {"type": "Polygon", "coordinates": [[
                [x, 28.1], [x + 0.01, 28.1], [x + 0.01, 28.11],
                [x, 28.11], [x, 28.1],
            ]]},
        })
    gis_tools._register_layer("长沙人口测试图层", {"type": "FeatureCollection", "features": features})
    wrapped = {tool.name: tool for tool in gis_tools.tools}
    try:
        yield task_id, wrapped
    finally:
        gis_tools.reset_state()
        task_manager._tasks.clear()
        task_manager._session_active.clear()
        history_service.set_history_file(None)
        storage_service.set_db_path(old_db)


def test_classification_and_light_color_edits_reuse_the_same_layer(local_map):
    task_id, wrapped = local_map
    tool = wrapped["spatial_graduated_colors"]
    first = tool.invoke({"layer_name": "长沙人口测试图层", "field": "population"})
    assert "等间距" in first
    equal_op = gis_tools._pending_layer_ops[-1]
    assert equal_op["method"] == "equal_interval"
    assert equal_op["breaks"] == pytest.approx([1.0, 20.8, 40.6, 60.4, 80.2, 100.0])

    gis_tools.set_current_run("cartography-run-2")
    quantile = tool.invoke({
        "layer_name": "长沙人口测试图层", "field": "population",
        "method": "quantile", "fill_opacity": 0.2,
    })
    assert "分位数" in quantile
    quantile_op = gis_tools._pending_layer_ops[-1]
    assert quantile_op["method"] == "quantile"
    assert quantile_op["breaks"] == pytest.approx([1.0, 1.8, 2.6, 3.4, 23.2, 100.0])
    assert quantile_op["fill_opacity"] == 0.2

    state = task_manager.get_gis_context(task_id)
    assert len(state["recent_operations"]) == 2
    assert state["last_successful_operation"]["arguments"]["method"] == "quantile"
    assert state["last_successful_operation"]["input_layers"][0]["layer_id"]
    assert state["last_successful_output"]["name"] == "长沙人口测试图层"


def test_failed_map_edit_keeps_last_success_and_ambiguous_layer_is_rejected(local_map):
    task_id, wrapped = local_map
    tool = wrapped["spatial_graduated_colors"]
    tool.invoke({"layer_name": "长沙人口测试图层", "field": "population"})
    last_success = task_manager.get_gis_context(task_id)["last_successful_output"]

    failed = tool.invoke({"layer_name": "长沙人口测试图层", "field": "missing_population"})
    assert "没有字段" in failed
    state = task_manager.get_gis_context(task_id)
    assert state["current_operation"]["status"] == "failed"
    assert state["last_successful_output"] == last_success

    gis_tools.set_current_run("cartography-run-retry")
    retried = tool.invoke({"layer_name": "长沙人口测试图层", "field": "population", "method": "quantile"})
    assert "分位数" in retried
    state = task_manager.get_gis_context(task_id)
    assert state["current_operation"]["status"] == "success"
    assert state["last_successful_output"]["name"] == "长沙人口测试图层"

    gis_tools._register_layer("长沙人口测试图层_副本", gis_tools._registered_layers["长沙人口测试图层"]["geojson"])
    ambiguous = tool.invoke({"layer_name": "长沙人口测试", "field": "population"})
    assert "多个匹配" in ambiguous


def test_cartography_skill_is_added_for_brief_style_followups(monkeypatch):
    from backend.services import ai_service
    from backend.services.llm_config import LLMConfig

    monkeypatch.setattr(ai_service, "conversation_history", {})
    cfg = LLMConfig(api_key="local-test", base_url="http://model.invalid", model="controlled", router=False)
    for message in ("长沙人口分布图", "颜色浅一点", "换个分级方法", "只导出刚才这张图"):
        system, skill, _ = ai_service._build_system_content(cfg, message, session_id="cartography-prompt-test", force_skills=[])
        assert "地图制图规范" in system
        assert "spatial_graduated_colors" in skill
        assert "只改颜色、分级、标题或图例" in system

    from backend.services.graph import _should_use_agent
    for followup in ("换成分位数", "颜色浅一点", "只导出刚才这张图"):
        messages = [SimpleNamespace(content="system"), SimpleNamespace(content=followup)]
        assert _should_use_agent(messages, "cartography-prompt-test")


def test_map_task_context_does_not_leak_to_another_session(local_map):
    task_id, wrapped = local_map
    wrapped["spatial_graduated_colors"].invoke({
        "layer_name": "长沙人口测试图层", "field": "population",
    })
    other = task_manager.create_task("另一项地图任务", "cartography-other-session")
    assert task_manager.get_gis_context(other) == {}
    other_context = task_manager.build_task_context(other)
    own_context = task_manager.build_task_context(task_id)
    assert "population" not in other_context
    assert "population" in own_context


@pytest.mark.parametrize("streaming", [False, True], ids=["invoke", "stream"])
def test_controlled_model_routes_style_followups_to_real_tool_chain(local_map, monkeypatch, streaming):
    task_id, wrapped = local_map
    from backend.services import graph
    from backend.services.llm_config import LLMConfig

    class FakeLLM:
        def invoke(self, *args, **kwargs):
            return SimpleNamespace(content="")

    class ControlledAgent:
        def __init__(self, tools):
            self.by_name = {tool.name: tool for tool in tools}

        def _execute(self, payload):
            messages = list(payload["messages"])
            user = next(m.content for m in reversed(messages) if isinstance(m, HumanMessage))
            previous = task_manager.get_gis_context(task_id).get("last_successful_operation") or {}
            method = "quantile" if "分位数" in user else (previous.get("arguments", {}).get("method") or "equal_interval")
            opacity = 0.2 if "浅" in user else 0.35
            args = {
                "layer_name": "长沙人口测试图层", "field": "population",
                "method": method, "fill_opacity": opacity,
            }
            call_id = uuid.uuid4().hex[:8]
            call = AIMessage(content="", tool_calls=[{
                "name": "spatial_graduated_colors", "args": args,
                "id": call_id, "type": "tool_call",
            }])
            result = self.by_name["spatial_graduated_colors"].invoke(args)
            return messages + [call, ToolMessage(
                content=str(result), name="spatial_graduated_colors", tool_call_id=call_id,
            ), AIMessage(content="已更新长沙人口分布图")]

        def invoke(self, payload, config=None):
            return {"messages": self._execute(payload)}

        def stream(self, payload, config=None, **kwargs):
            yield {"messages": self._execute(payload)}

    monkeypatch.setattr(graph, "build_llm", lambda cfg: FakeLLM())
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, tools: ControlledAgent(tools))
    cfg = LLMConfig(api_key="controlled", base_url="http://model.invalid", model="controlled")
    messages = [SystemMessage(content="controlled local map test")]
    session = "cartography-local-session"
    final_result = None
    for text in ("画长沙人口分布图", "换成分位数", "颜色浅一点"):
        messages.append(HumanMessage(content=text))
        try:
            if streaming:
                events = [line for line in graph.run_agent_stream(
                    messages=messages, cfg=cfg, original_message=text, session_id=session,
                ) if line.startswith("data: ")]
                response = json.loads(events[-1][6:])
                assert response["type"] == "done"
                final_result = response
                response = response["response"]
            else:
                final_result = graph.run_agent(
                    messages=messages, cfg=cfg, original_message=text, session_id=session,
                )
                response = final_result["response"]
        finally:
            if not streaming:
                gis_tools.release_session_lock(session)
        messages.append(AIMessage(content=response))

    state = task_manager.get_gis_context(task_id)
    assert [op["tool"] for op in state["recent_operations"][-3:]] == [
        "spatial_graduated_colors", "spatial_graduated_colors", "spatial_graduated_colors",
    ]
    assert state["recent_operations"][-2]["arguments"]["method"] == "quantile"
    assert state["recent_operations"][-1]["arguments"]["fill_opacity"] == 0.2
    assert state["last_successful_output"]["name"] == "长沙人口测试图层"
    assert state["recent_operations"][-1]["input_layers"][0]["layer_id"]
    assert final_result["layer_ops"], f"map operation missing from response: {final_result!r}"
    last_map_op = final_result["layer_ops"][-1]
    assert last_map_op["method"] == "quantile"
    assert last_map_op["fill_opacity"] == 0.2
    assert last_map_op["breaks"]


@pytest.mark.parametrize("method", ["equal_interval", "quantile"])
def test_classification_method_is_validated_in_tool_metadata(local_map, method):
    _, wrapped = local_map
    result = wrapped["spatial_graduated_colors"].invoke({
        "layer_name": "长沙人口测试图层", "field": "population", "method": method,
    })
    assert json.loads(json.dumps(gis_tools._pending_layer_ops[-1]["breaks"]))
    assert ("分位数" in result) if method == "quantile" else ("等间距" in result)
