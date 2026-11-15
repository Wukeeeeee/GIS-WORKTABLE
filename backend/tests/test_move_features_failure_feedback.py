import copy

from backend.services import tools


def _setup_layer():
    tools.reset_state()
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
