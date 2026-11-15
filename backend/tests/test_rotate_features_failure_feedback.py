import copy

from backend.services import tools


def test_empty_layer_rotation_is_failure_without_mutation():
    tools.reset_state()
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
    tools.reset_state()
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
