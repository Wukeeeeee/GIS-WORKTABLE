import copy
import warnings

import pytest

from backend.services import tools
from backend.services.tool_modules import runtime


def _isolate_scale_runtime_state(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})
        monkeypatch.setattr(tools, "_pending_layers", [])
        monkeypatch.setattr(tools, "_pending_layer_ops", [])
        monkeypatch.setattr(tools, "_pending_qa_warnings", [])


@pytest.fixture(autouse=True)
def isolate_scale_runtime_state_fixture(monkeypatch):
    _isolate_scale_runtime_state(monkeypatch)
    yield
    with runtime._state_lock:
        runtime._registered_layers.clear()
        runtime._pending_layers.clear()
        runtime._pending_layer_ops.clear()
        runtime._pending_qa_warnings.clear()


def test_scale_runtime_isolation_restores_existing_state():
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
        _isolate_scale_runtime_state(patcher)
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
        "parcel",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "lot"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]]],
                },
            }],
        },
    )


@pytest.mark.parametrize("x_factor,y_factor", [
    (0, 1),
    (-1, 1),
    (float("nan"), 1),
    (1, float("inf")),
])
def test_invalid_scale_factors_are_failures_without_mutation(x_factor, y_factor):
    _setup_layer()
    before = copy.deepcopy(tools._registered_layers["parcel"]["geojson"])

    result = tools.scale_features.invoke({
        "layer_name": "parcel", "x_factor": x_factor, "y_factor": y_factor,
    })

    assert "缩放倍数" in result
    assert tools._tool_result_failed("scale_features", result)
    assert tools._registered_layers["parcel"]["geojson"] == before
    assert tools._pending_layers == []


def test_valid_scale_is_not_classified_as_failure():
    _setup_layer()

    result = tools.scale_features.invoke({
        "layer_name": "parcel", "x_factor": 2, "y_factor": 1,
    })

    assert "已缩放图层" in result
    assert not tools._tool_result_failed("scale_features", result)
    assert [layer["name"] for layer in runtime._pending_layers] == ["parcel"]


def test_empty_layer_scale_rejection_is_failure_without_mutation():
    tools._register_layer(
        "parcel",
        {"type": "FeatureCollection", "features": []},
    )
    before = copy.deepcopy(tools._registered_layers["parcel"]["geojson"])

    result = tools.scale_features.invoke({"layer_name": "parcel", "x_factor": 2, "y_factor": 2})

    assert "图层「parcel」为空" in result
    assert tools._tool_result_failed("scale_features", result)
    assert tools._registered_layers["parcel"]["geojson"] == before
    assert tools._pending_layers == []


def test_scale_factor_overflow_is_rejected_before_geometry_math():
    _setup_layer()
    before = copy.deepcopy(tools._registered_layers["parcel"]["geojson"])

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = tools.scale_features.invoke({
            "layer_name": "parcel", "x_factor": 1e308, "y_factor": 1,
        })

    assert "坐标溢出" in result
    assert not [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert tools._tool_result_failed("scale_features", result)
    assert tools._registered_layers["parcel"]["geojson"] == before
    assert tools._pending_layers == []
