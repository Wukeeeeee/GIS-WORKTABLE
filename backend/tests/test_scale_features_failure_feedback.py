import copy
import warnings

import pytest

from backend.services import tools


def _setup_layer():
    tools.reset_state()
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


def test_empty_layer_scale_rejection_is_failure_without_mutation():
    tools.reset_state()
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
