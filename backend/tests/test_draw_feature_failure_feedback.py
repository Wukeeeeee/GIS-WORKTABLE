import pytest

from backend.services import tools
from backend.services.tool_modules import runtime

pytestmark = pytest.mark.usefixtures("isolated_tool_runtime")


def _isolate_draw_runtime_state(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})
        monkeypatch.setattr(tools, "_pending_layers", [])
        monkeypatch.setattr(tools, "_pending_layer_ops", [])
        monkeypatch.setattr(tools, "_pending_qa_warnings", [])


def test_draw_runtime_isolation_restores_existing_state():
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
        _isolate_draw_runtime_state(patcher)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layers is not pending
        assert runtime._pending_layer_ops is not ops
        assert runtime._pending_qa_warnings is not warnings
        assert tools._registered_layers is runtime._registered_layers
        assert tools._pending_layers is runtime._pending_layers
    finally:
        patcher.undo()
    assert runtime._registered_layers is registry and "sentinel-layer" in registry
    assert runtime._pending_layers is pending and pending[0]["name"] == "sentinel-pending"
    assert runtime._pending_layer_ops is ops and ops[0]["action"] == "sentinel"
    assert runtime._pending_qa_warnings is warnings and warnings[0]["warning"] == "preserve"


@pytest.mark.parametrize(
    "arguments",
    [
        {"geometry_type": "Triangle", "coordinates": "0,0"},
        {"geometry_type": "Point", "coordinates": "NaN,0"},
        {"geometry_type": "Rectangle", "coordinates": "1,1;1,2"},
        {"geometry_type": "Circle", "coordinates": "0,0;0"},
    ],
)
def test_draw_feature_input_errors_are_classified_as_failures(arguments):
    result = tools.draw_feature.invoke(arguments)

    assert tools._tool_result_failed("draw_feature", result), result
    assert tools._pending_layers == []
    assert runtime._registered_layers == {}


def test_draw_feature_success_is_not_classified_as_failure():
    result = tools.draw_feature.invoke({
        "geometry_type": "Point", "coordinates": "0,0", "layer_name": "probe-point",
    })

    assert result.startswith("已创建Point图层")
    assert not tools._tool_result_failed("draw_feature", result)
    assert set(runtime._registered_layers) == {"probe-point"}
    assert [item["name"] for item in tools._pending_layers] == ["probe-point"]
