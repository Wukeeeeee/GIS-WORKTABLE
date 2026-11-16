"""Exercise operation-state recording around real local GIS tools, without a model or network."""
import pytest
import json
import uuid
from types import SimpleNamespace
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from backend.services import ai_service, history_service, storage_service, task_manager
from backend.services import tools as gis_tools
from backend.services.graph import _should_use_agent


@pytest.fixture
def local_gis_task(tmp_path, monkeypatch, isolated_tool_runtime):
    # Isolate both history persistence and its singleton cache without
    # clearing or replacing any history already held by the test process.
    monkeypatch.setattr(history_service, "_CUSTOM_PATH", [str(tmp_path / "history.json")])
    monkeypatch.setattr(history_service, "_ENTRIES", [])
    monkeypatch.setattr(history_service, "_NEXT_INDEX", [1])
    monkeypatch.setattr(history_service, "_LOADED", [False])
    monkeypatch.setattr(history_service, "_LOAD_ERROR", [None])
    monkeypatch.setattr(history_service, "_PERSIST_ERROR", [None])
    monkeypatch.setattr(ai_service, "_HISTORY_DIR", str(tmp_path / "ai-history"))
    monkeypatch.setattr(storage_service, "_CUSTOM_DB_PATH", [None])
    storage_service.set_db_path(str(tmp_path / "workspace.db"))
    task_id = task_manager.create_task("长沙边界缓冲与导出", "four-turn-session")
    gis_tools.reset_state(task_id=task_id)
    for run_id in ("run-four-turn-1", "run-four-turn-2", "run-four-turn-3"):
        storage_service.record_run_start(run_id, "four-turn-session", "长沙边界缓冲与导出", task_id)
    gis_tools.set_current_run("run-four-turn-1")
    source = {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"name": "长沙市"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [112.9, 28.1], [113.0, 28.1], [113.0, 28.2],
                [112.9, 28.2], [112.9, 28.1],
            ]]},
        }],
    }
    gis_tools._register_layer("长沙市", source)
    wrapped = {t.name: t for t in gis_tools.tools}
    yield task_id, wrapped, tmp_path


def test_gis_runtime_isolation_restores_existing_state(tmp_path, isolated_tool_runtime):
    from backend.services.tool_modules import runtime

    registry = runtime._registered_layers
    pending_layers = runtime._pending_layers
    pending_ops = runtime._pending_layer_ops
    previous_task_id = runtime.get_current_task_id()
    task_cache = task_manager._tasks
    active_sessions = task_manager._session_active
    previous_task_dir = task_manager._BASE_DIR
    sentinel = f"__gis_operation_context_fixture_{uuid.uuid4().hex}__"
    registry[sentinel] = {"sentinel": True}
    pending_layers.append({"name": sentinel})
    pending_ops.append({"action": sentinel})
    runtime.set_current_task(sentinel)
    task_cache[sentinel] = {"sentinel": True}
    active_sessions[sentinel] = sentinel

    patcher = pytest.MonkeyPatch()
    try:
        isolated_tool_runtime(patcher, tmp_path / "nested")
        gis_tools.reset_state()
        runtime._registered_layers[sentinel] = {"isolated": True}
        assert runtime._registered_layers is not registry
        assert runtime._pending_layers is not pending_layers
        assert runtime._pending_layer_ops is not pending_ops
        assert task_manager._tasks is not task_cache
        assert task_manager._session_active is not active_sessions
        task_manager._tasks[sentinel] = {"isolated": True}
        patcher.undo()
        assert runtime._registered_layers is registry
        assert registry[sentinel]["sentinel"] is True
        assert runtime._pending_layers is pending_layers
        assert pending_layers[-1]["name"] == sentinel
        assert runtime._pending_layer_ops is pending_ops
        assert pending_ops[-1]["action"] == sentinel
        assert runtime.get_current_task_id() == sentinel
        assert task_manager._tasks is task_cache
        assert task_cache[sentinel]["sentinel"] is True
        assert task_manager._session_active is active_sessions
        assert active_sessions[sentinel] == sentinel
        assert task_manager._BASE_DIR == previous_task_dir
    finally:
        patcher.undo()
        registry.pop(sentinel, None)
        pending_layers[:] = [item for item in pending_layers if item.get("name") != sentinel]
        pending_ops[:] = [item for item in pending_ops if item.get("action") != sentinel]
        runtime.set_current_task(previous_task_id)
        task_cache.pop(sentinel, None)
        active_sessions.pop(sentinel, None)

    assert runtime._registered_layers is registry
    assert registry.get(sentinel) is None
    assert runtime._pending_layers is pending_layers
    assert all(item.get("name") != sentinel for item in pending_layers)
    assert runtime._pending_layer_ops is pending_ops
    assert all(item.get("action") != sentinel for item in pending_ops)
    assert runtime.get_current_task_id() == previous_task_id
    assert task_manager._tasks is task_cache
    assert sentinel not in task_cache
    assert task_manager._session_active is active_sessions
    assert sentinel not in active_sessions
    assert task_manager._BASE_DIR == previous_task_dir


@pytest.fixture
def normal_agent_for_synthetic_workspace(monkeypatch):
    """These agent-routing checks target normal mode, not privacy-mode routing."""
    from backend.services import privacy_service

    monkeypatch.setattr(privacy_service, "session_protected", lambda session_id="default": False)


def test_local_buffer_parameter_edit_and_export_are_recorded(local_gis_task):
    task_id, wrapped, output = local_gis_task
    first = wrapped["spatial_buffer"].invoke({
        "layer_name": "长沙市", "distance": 500, "unit": "m", "dissolve": False,
    })
    assert "500.0m缓冲区" in first
    buffer_layer = next(layer for layer in gis_tools._pending_layers if layer["name"] == "长沙市_缓冲区")
    original_buffer = gis_tools._registered_layers["长沙市_缓冲区"]
    assert buffer_layer["style"]["fillOpacity"] <= 0.1
    assert buffer_layer["style"]["color"]
    state = task_manager.get_gis_context(task_id)
    assert state["last_successful_operation"]["arguments"]["distance"] == 500
    assert state["last_successful_operation"]["input_layers"][0]["name"] == "长沙市"
    assert state["last_successful_output"]["name"] == "长沙市_缓冲区"
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform
    project = Transformer.from_crs("EPSG:4326", "EPSG:32649", always_xy=True).transform
    area_500 = transform(project, shape(
        gis_tools._registered_layers["长沙市_缓冲区"]["geojson"]["features"][0]["geometry"]
    )).area

    # Re-running the same operation preserves the prior output and allocates a unique result name.
    gis_tools.set_current_run("run-four-turn-2")
    second = wrapped["spatial_buffer"].invoke({
        "layer_name": "长沙市", "distance": 1, "unit": "km", "dissolve": False,
    })
    assert "创建1.0km缓冲区" in second
    state = task_manager.get_gis_context(task_id)
    assert state["last_successful_operation"]["arguments"]["distance"] == 1
    assert state["last_successful_operation"]["arguments"]["unit"] == "km"
    assert state["last_successful_operation"]["input_layers"][0]["name"] == "长沙市"
    latest_buffer_name = state["last_successful_output"]["name"]
    assert latest_buffer_name.startswith("长沙市_缓冲区_")
    assert gis_tools._registered_layers["长沙市_缓冲区"] is original_buffer
    assert latest_buffer_name in gis_tools._registered_layers
    area_1000 = transform(project, shape(
        gis_tools._registered_layers[latest_buffer_name]["geojson"]["features"][0]["geometry"]
    )).area
    assert area_1000 > area_500

    gis_tools.set_current_run("run-four-turn-3")
    exported = wrapped["export_layer"].invoke({"layer_name": latest_buffer_name, "format": "geojson"})
    assert "GeoJSON已生成" in exported
    state = task_manager.get_gis_context(task_id)
    assert state["current_operation"]["tool"] == "export_layer"
    assert state["last_successful_output"]["filename"].startswith(latest_buffer_name + "_")
    assert (output / "output" / state["last_successful_output"]["filename"]).is_file()
    prompt = task_manager.build_task_context(task_id)
    assert "最近成功结果" in prompt
    assert "spatial_buffer" in prompt and "export_layer" in prompt


def test_failed_and_ambiguous_attempts_preserve_last_success(local_gis_task):
    task_id, wrapped, _ = local_gis_task
    wrapped["spatial_buffer"].invoke({
        "layer_name": "长沙市", "distance": 500, "unit": "m", "dissolve": False,
    })
    last_success = task_manager.get_gis_context(task_id)["last_successful_output"]

    gis_tools._register_layer("长沙县", {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [113.1, 28.2]},
        }],
    })
    ambiguous = wrapped["spatial_buffer"].invoke({
        "layer_name": "长沙", "distance": 1000, "unit": "m", "dissolve": False,
    })
    assert "找到多个匹配" in ambiguous
    failed = wrapped["spatial_buffer"].invoke({
        "layer_name": "不存在的图层", "distance": 1000, "unit": "m", "dissolve": False,
    })
    assert "缓冲区分析失败" in failed or "未找到" in failed
    state = task_manager.get_gis_context(task_id)
    assert state["current_operation"]["status"] == "failed"
    assert state["last_successful_output"] == last_success
    retry = wrapped["spatial_buffer"].invoke({
        "layer_name": "长沙市", "distance": 1000, "unit": "m", "dissolve": False,
    })
    assert "1000.0m缓冲区" in retry
    state = task_manager.get_gis_context(task_id)
    assert state["current_operation"]["status"] == "success"
    assert state["last_successful_operation"]["arguments"]["distance"] == 1000


def test_explicit_input_switch_and_session_context_isolation(local_gis_task):
    task_id, wrapped, _ = local_gis_task
    gis_tools._register_layer("岳麓区", {
        "type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [112.9, 28.2]},
        }],
    })
    wrapped["spatial_buffer"].invoke({
        "layer_name": "岳麓区", "distance": 250, "unit": "m", "dissolve": False,
    })
    state = task_manager.get_gis_context(task_id)
    assert state["last_successful_operation"]["input_layers"][0]["name"] == "岳麓区"

    other = task_manager.create_task("另一会话", "different-session")
    assert task_manager.get_gis_context(other) == {}
    assert task_manager.find_active_task_for_session("different-session") == other


def test_streaming_and_non_streaming_use_same_agent_router():
    from types import SimpleNamespace
    for message in ("加载长沙市边界", "给它做500米缓冲", "改成一公里", "只导出刚才的结果"):
        messages = [SimpleNamespace(content="system"), SimpleNamespace(content=message)]
        assert _should_use_agent(messages, "router-session")


@pytest.mark.parametrize("streaming", [False, True], ids=["invoke", "stream"])
def test_four_turn_controlled_agent_uses_real_local_tool_chain(
    local_gis_task, monkeypatch, normal_agent_for_synthetic_workspace, streaming,
):
    task_id, wrapped, _ = local_gis_task
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
            context = task_manager.get_gis_context(task_id)
            if "加载" in user:
                name, args = "datav_boundary", {"name": "长沙市"}
            elif "500" in user:
                name, args = "spatial_buffer", {
                    "layer_name": "长沙市", "distance": 500, "unit": "m", "dissolve": False,
                }
            elif "一公里" in user:
                prior = context["last_successful_operation"]
                name, args = "spatial_buffer", {
                    "layer_name": prior["input_layers"][0]["name"],
                    "distance": 1, "unit": "km", "dissolve": False,
                }
            else:
                prior = context["last_successful_output"]
                name, args = "export_layer", {"layer_name": prior["name"], "format": "geojson"}
            call_id = uuid.uuid4().hex[:8]
            call = AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": call_id, "type": "tool_call",
            }])
            tool_result = self.by_name[name].invoke(args)
            return messages + [call, ToolMessage(content=str(tool_result), name=name, tool_call_id=call_id),
                               AIMessage(content=f"已完成：{name}")]

        def invoke(self, payload, config=None):
            return {"messages": self._execute(payload)}

        def stream(self, payload, config=None, **kwargs):
            yield {"messages": self._execute(payload)}

    monkeypatch.setattr(graph, "build_llm", lambda cfg: FakeLLM())
    def load_local_boundary(name: str):
        gis_tools._register_layer(name, {
            "type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {"name": name},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [112.9, 28.1], [113.0, 28.1], [113.0, 28.2],
                    [112.9, 28.2], [112.9, 28.1],
                ]]},
            }],
        })
        return f"已从本地固定样例加载{name}边界"

    fixture_loader = gis_tools._recorded(StructuredTool.from_function(
        func=load_local_boundary, name="datav_boundary", description="Load fixed local boundary fixture",
    ))
    test_tools = [fixture_loader if tool.name == "datav_boundary" else tool for tool in graph.tools]
    monkeypatch.setattr(graph, "tools", test_tools)
    monkeypatch.setattr(graph, "create_react_agent", lambda llm, tools: ControlledAgent(tools))
    cfg = LLMConfig(api_key="mock", base_url="http://mock", model="mock")
    messages = [SystemMessage(content="test GIS task")]
    session = "four-turn-session"
    for user_text in ("加载长沙市边界", "给它做500米缓冲", "改成一公里", "只导出刚才的结果"):
        messages.append(HumanMessage(content=user_text))
        try:
            if streaming:
                events = [line for line in graph.run_agent_stream(
                    messages=messages, cfg=cfg, original_message=user_text, session_id=session,
                ) if line.startswith("data: ")]
                result = json.loads(events[-1][6:])
                assert result["type"] == "done"
                response = result
            else:
                response = graph.run_agent(
                    messages=messages, cfg=cfg, original_message=user_text, session_id=session,
                )
        finally:
            if not streaming:
                gis_tools.release_session_lock(session)
        messages.append(AIMessage(content=response["response"]))

    state = task_manager.get_gis_context(task_id)
    operations = state["recent_operations"]
    assert [op["tool"] for op in operations[-4:]] == [
        "datav_boundary", "spatial_buffer", "spatial_buffer", "export_layer",
    ]
    assert operations[-3]["arguments"]["distance"] == 500
    assert operations[-2]["arguments"]["distance"] == 1
    assert operations[-2]["arguments"]["unit"] == "km"
    assert operations[-2]["input_layers"][0]["name"] == "长沙市"
    assert state["recent_operations"][-1]["tool"] == "export_layer"
    assert state["recent_operations"][-1]["arguments"]["layer_name"] == operations[-2]["output_layers"][-1]["name"]
    assert state["last_successful_output"]["filename"].endswith(".geojson")
