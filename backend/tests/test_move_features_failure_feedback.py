from backend.services import tools


def test_unsupported_move_unit_is_failure_without_mutating_layer(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
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
    before = tools._registered_layers["point-layer"]["geojson"]

    result = tools.move_features.invoke({
        "layer_name": "point-layer", "dx": 10, "dy": 0, "unit": "mile",
    })

    assert "不支持的单位" in result
    assert tools._tool_result_failed("move_features", result)
    assert tools._registered_layers["point-layer"]["geojson"] == before
    assert tools._pending_layers == []
