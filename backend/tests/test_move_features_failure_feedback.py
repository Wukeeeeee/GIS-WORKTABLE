import copy

import pytest

from backend.services import tools
from backend.services.tool_modules import runtime


def _isolate_move_features_runtime_state(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})
        monkeypatch.setattr(tools, "_pending_layers", [])
        monkeypatch.setattr(tools, "_pending_layer_ops", [])
        monkeypatch.setattr(tools, "_pending_qa_warnings", [])


@pytest.fixture(autouse=True)
def isolate_move_features_runtime_state_fixture(monkeypatch):
    _isolate_move_features_runtime_state(monkeypatch)
    yield
    with runtime._state_lock:
        runtime._registered_layers.clear()
        runtime._pending_layers.clear()
        runtime._pending_layer_ops.clear()
        runtime._pending_qa_warnings.clear()
        assert runtime._registered_layers == {}


def test_move_features_runtime_isolation_restores_existing_state():
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
        _isolate_move_features_runtime_state(patcher)
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


def _setup_layer():
    tools._register_layer(
        "point-layer",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "origin"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }],
        },
    )


def test_unsupported_move_unit_is_failure_without_mutating_layer():
    _setup_layer()
    before = tools._registered_layers["point-layer"]["geojson"]

    result = tools.move_features.invoke({
        "layer_name": "point-layer", "dx": 10, "dy": 0, "unit": "mile",
    })

    assert "不支持的单位" in result
    assert tools._tool_result_failed("move_features", result)
    assert tools._registered_layers["point-layer"]["geojson"] == before
    assert tools._pending_layers == []


def test_kilometer_conversion_overflow_is_rejected_without_mutation():
    _setup_layer()
    before = copy.deepcopy(tools._registered_layers["point-layer"]["geojson"])

    result = tools.move_features.invoke({
        "layer_name": "point-layer", "dx": 1e308, "dy": 0, "unit": "km",
    })

    assert result.startswith("移动要素失败：公里换算后位移超出有限数值范围")
    assert tools._tool_result_failed("move_features", result)
    assert tools._registered_layers["point-layer"]["geojson"] == before
    assert tools._pending_layers == []
