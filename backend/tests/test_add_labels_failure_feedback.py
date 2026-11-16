import pytest

from backend.services import tools
from backend.services.tool_modules import runtime

pytestmark = pytest.mark.usefixtures("isolated_tool_runtime")


def _isolate_label_runtime_state(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})
        monkeypatch.setattr(tools, "_pending_layer_ops", [])


def test_label_runtime_isolation_restores_existing_state():
    registry, ops = runtime._registered_layers, runtime._pending_layer_ops
    registry["sentinel-layer"] = {"geojson": {"type": "FeatureCollection", "features": []}}
    ops.append({"action": "sentinel"})
    patcher = pytest.MonkeyPatch()
    try:
        _isolate_label_runtime_state(patcher)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layer_ops is not ops
        assert tools._registered_layers is runtime._registered_layers
        assert tools._pending_layer_ops is runtime._pending_layer_ops
    finally:
        patcher.undo()
    assert runtime._registered_layers is registry and "sentinel-layer" in registry
    assert runtime._pending_layer_ops is ops and ops[0]["action"] == "sentinel"


def test_missing_label_field_is_classified_as_tool_failure():
    tools._register_layer(
        "roads",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "main"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }],
        },
    )

    result = tools.add_labels.invoke({"layer_name": "roads", "field": "missing"})

    assert "没有字段「missing」" in result
    assert tools._tool_result_failed("add_labels", result)
    assert runtime._pending_layer_ops == []


def test_valid_label_field_is_not_classified_as_failure():
    tools._register_layer(
        "roads",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "main"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }],
        },
    )

    result = tools.add_labels.invoke({"layer_name": "roads", "field": "name"})

    assert "已为" in result
    assert not tools._tool_result_failed("add_labels", result)
    assert runtime._pending_layer_ops == [{
        "action": "labels", "name": "roads", "field": "name",
        "font_size": 12, "color": "#333333",
    }]
