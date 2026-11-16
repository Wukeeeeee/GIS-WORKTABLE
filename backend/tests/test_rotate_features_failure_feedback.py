import copy
import pytest

from backend.services import tools
from backend.services.tool_modules import runtime


def _isolate_rotate_runtime_state(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})
        monkeypatch.setattr(tools, "_pending_layers", [])
        monkeypatch.setattr(tools, "_pending_layer_ops", [])
        monkeypatch.setattr(tools, "_pending_qa_warnings", [])


@pytest.fixture(autouse=True)
def isolate_rotate_runtime_state_fixture(monkeypatch):
    _isolate_rotate_runtime_state(monkeypatch)
    yield
    with runtime._state_lock:
        runtime._registered_layers.clear()
        runtime._pending_layers.clear()
        runtime._pending_layer_ops.clear()
        runtime._pending_qa_warnings.clear()


def test_rotate_runtime_isolation_restores_existing_state():
    registry, pending, ops, warnings = (
        runtime._registered_layers,
        runtime._pending_layers,
        runtime._pending_layer_ops,
        runtime._pending_qa_warnings,
    )
    registry["sentinel-layer"] = {"geojson": {"type": "FeatureCollection", "features": []}}
    pending.append({"name": "sentinel-pending"})
    ops.append({"action": "sentinel"})
    warnings.append({"layer": "sentinel-layer", "warning": "preserve"})
    patcher = pytest.MonkeyPatch()
    try:
        _isolate_rotate_runtime_state(patcher)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layers is not pending
        assert runtime._pending_layer_ops is not ops
        assert runtime._pending_qa_warnings is not warnings
        assert tools._registered_layers is runtime._registered_layers
    finally:
        patcher.undo()
    assert runtime._registered_layers is registry and "sentinel-layer" in registry
    assert runtime._pending_layers is pending and pending[0]["name"] == "sentinel-pending"
    assert runtime._pending_layer_ops is ops and ops[0]["action"] == "sentinel"
    assert runtime._pending_qa_warnings is warnings and warnings[0]["warning"] == "preserve"


def test_empty_layer_rotation_is_failure_without_mutation():
    tools._register_layer(
        "parcel",
        {"type": "FeatureCollection", "features": []},
    )
    before = copy.deepcopy(tools._registered_layers["parcel"]["geojson"])

    result = tools.rotate_features.invoke({"layer_name": "parcel", "angle": 90})

    assert "图层「parcel」为空" in result
    assert tools._tool_result_failed("rotate_features", result)
    assert tools._registered_layers["parcel"]["geojson"] == before
    assert tools._pending_layers == []


def test_zero_degree_rotation_is_a_successful_noop():
    tools._register_layer(
        "parcel",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]]],
                },
            }],
        },
    )
    before = copy.deepcopy(tools._registered_layers["parcel"]["geojson"])

    result = tools.rotate_features.invoke({"layer_name": "parcel", "angle": 0})

    assert "0°" in result
    assert "顺时针" not in result
    assert "逆时针" not in result
    assert not tools._tool_result_failed("rotate_features", result)
    assert tools._registered_layers["parcel"]["geojson"] == before
    assert tools._pending_layers == []
    assert tools._pending_layer_ops == []
