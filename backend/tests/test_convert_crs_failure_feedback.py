import copy

from backend.services import tools


def test_web_mercator_rejects_latitudes_outside_crs_area_without_mutation():
    tools.reset_state()
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
    tools.reset_state()
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
    y = tools._registered_layers["near_polar_EPSG:3857"]["geojson"]["features"][0]["geometry"]["coordinates"][1]
    assert 0 < y < 20_050_000
