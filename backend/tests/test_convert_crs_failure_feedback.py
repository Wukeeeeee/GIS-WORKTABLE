import copy
import pytest

from backend.services import tools
from backend.services.tool_modules import runtime

pytestmark = pytest.mark.usefixtures("isolated_tool_runtime")


def _isolate_convert_crs_runtime_state(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})
        monkeypatch.setattr(tools, "_pending_layers", [])
        monkeypatch.setattr(tools, "_pending_layer_ops", [])
        monkeypatch.setattr(tools, "_pending_qa_warnings", [])


def test_convert_crs_runtime_isolation_restores_existing_state():
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
        _isolate_convert_crs_runtime_state(patcher)
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


def test_web_mercator_rejects_latitudes_outside_crs_area_without_mutation():
    tools._register_layer(
        "polar",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [0, 89]},
            }],
        },
    )
    before = copy.deepcopy(tools._registered_layers["polar"]["geojson"])

    result = tools.convert_crs.invoke({
        "layer_name": "polar", "target_crs": "web_mercator",
    })

    assert result.startswith("坐标系转换失败")
    assert "85.06" in result
    assert tools._tool_result_failed("convert_crs", result)
    assert tools._registered_layers["polar"]["geojson"] == before
    assert "polar_web_mercator" not in tools._registered_layers
    assert not any(
        layer.get("name") == "polar_web_mercator"
        for layer in tools._pending_layers
    )


def test_web_mercator_accepts_latitude_inside_crs_area():
    tools._register_layer(
        "near_polar",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [0, 85.05]},
            }],
        },
    )

    result = tools.convert_crs.invoke({
        "layer_name": "near_polar", "target_crs": "EPSG:3857",
    })

    assert "坐标系转换失败" not in result
    assert "near_polar_EPSG:3857" in tools._registered_layers
    assert [layer["name"] for layer in tools._pending_layers] == ["near_polar_EPSG:3857"]
    y = tools._registered_layers["near_polar_EPSG:3857"]["geojson"]["features"][0]["geometry"]["coordinates"][1]
    assert 0 < y < 20_050_000
