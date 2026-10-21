import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.services import tools as T
from backend.services.tools import _register_layer, reset_state


@pytest.fixture(autouse=True)
def cleanup_layers():
    reset_state()
    yield
    reset_state()


def _points():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "中心医院", "category": "医院"},
             "geometry": {"type": "Point", "coordinates": [120.0, 30.0]}},
            {"type": "Feature", "properties": {"name": "麦当劳湖滨店", "category": "麦当劳"},
             "geometry": {"type": "Point", "coordinates": [120.1, 30.1]}},
            {"type": "Feature", "properties": {"name": "麦当劳东站店", "category": "麦当劳"},
             "geometry": {"type": "Point", "coordinates": [120.1001, 30.1]}},
            {"type": "Feature", "properties": {"name": "麦当劳机场店", "category": "麦当劳"},
             "geometry": {"type": "Point", "coordinates": [120.2, 30.2]}},
        ],
    }


def test_nearest_pair_finds_global_pair_and_returns_names_and_distance():
    _register_layer("mixed_poi", _points())

    result = T.nearest_pair.invoke({"layer_name": "mixed_poi"})

    assert "麦当劳湖滨店" in result
    assert "麦当劳东站店" in result
    assert "米" in result


def test_nearest_pair_can_filter_features_before_comparing():
    _register_layer("mixed_poi", _points())

    result = T.nearest_pair.invoke({"layer_name": "mixed_poi", "feature_filter": "麦当劳"})

    assert "麦当劳湖滨店" in result
    assert "麦当劳东站店" in result
    assert "中心医院" not in result
    assert "属性包含「麦当劳」" in result


def test_nearest_pair_supports_two_registered_layers():
    _register_layer("餐饮POI", _points())
    _register_layer("医院_POI(OSM)", {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "湖滨医院"},
             "geometry": {"type": "Point", "coordinates": [120.10012, 30.1]}},
            {"type": "Feature", "properties": {"name": "远郊医院"},
             "geometry": {"type": "Point", "coordinates": [120.3, 30.3]}},
        ],
    })

    registered = T.get_registered_layers.invoke({})
    result = T.nearest_pair.invoke({
        "layer_name": "餐饮POI",
        "feature_filter": "麦当劳",
        "target_layer": "医院_POI(OSM)",
    })

    assert "餐饮POI" in registered and "医院_POI(OSM)" in registered
    assert "麦当劳东站店" in result
    assert "湖滨医院" in result
    assert "米" in result
