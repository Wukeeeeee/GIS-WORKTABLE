"""
空间分析工具测试
使用简单 GeoJSON 验证 buffer/intersect/union/clip/centroid/simplify/dissolve
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import pytest

from backend.services import tools as T
from backend.services.tools import (
    _registered_layers,
    _pending_layers,
    _register_layer,
    reset_state,
)

# StructuredTool 对象，需要用 .invoke({...}) 调用
spatial_buffer = T.spatial_buffer
spatial_intersect = T.spatial_intersect
spatial_union = T.spatial_union
spatial_difference = T.spatial_difference
spatial_clip = T.spatial_clip
spatial_centroid = T.spatial_centroid
spatial_simplify = T.spatial_simplify
spatial_dissolve = T.spatial_dissolve
spatial_join = T.spatial_join
reverse_geocode = T.reverse_geocode
batch_geocode = T.batch_geocode
spatial_select = T.spatial_select
spatial_sample = T.spatial_sample
spatial_near = T.spatial_near
spatial_cluster = T.spatial_cluster
spatial_voronoi = T.spatial_voronoi
spatial_field_stats = T.spatial_field_stats
layer_merge = T.layer_merge
layer_split = T.layer_split
layer_add_geometry = T.layer_add_geometry


@pytest.fixture(autouse=True)
def cleanup():
    reset_state()
    yield
    reset_state()


_SQUARE_A = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "A", "type": "test"},
        "geometry": {"type": "Polygon", "coordinates": [[[0,0],[2,0],[2,2],[0,2],[0,0]]]}
    }]
}

_SQUARE_B = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature", "properties": {"name": "B", "type": "test"},
        "geometry": {"type": "Polygon", "coordinates": [[[1,1],[3,1],[3,3],[1,3],[1,1]]]}
    }]
}

_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"id": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {"type": "Feature", "properties": {"id": 2}, "geometry": {"type": "Point", "coordinates": [1, 1]}},
        {"type": "Feature", "properties": {"id": 3}, "geometry": {"type": "Point", "coordinates": [2, 2]}},
    ]
}

_LINE = {
    "type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "LineString", "coordinates": [[0,0],[3,3]]}
    }]
}

_MULTI_POLY = {
    "type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"group": "X", "val": 1},
         "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}},
        {"type": "Feature", "properties": {"group": "X", "val": 2},
         "geometry": {"type": "Polygon", "coordinates": [[[0.5,0.5],[1.5,0.5],[1.5,1.5],[0.5,1.5],[0.5,0.5]]]}},
        {"type": "Feature", "properties": {"group": "Y", "val": 3},
         "geometry": {"type": "Polygon", "coordinates": [[[2,0],[3,0],[3,1],[2,1],[2,0]]]}},
    ]
}


def _setup(name, geojson):
    _register_layer(name, geojson)
    return name


class TestSpatialBuffer:
    def test_buffer_simple(self):
        _setup("square", _SQUARE_A)
        r = spatial_buffer.invoke({"layer_name": "square", "distance": 10, "unit": "m", "dissolve": False})
        assert "缓冲区" in r
        assert len(_pending_layers) == 1

    def test_buffer_dissolve(self):
        _setup("pts", _POINTS)
        r = spatial_buffer.invoke({"layer_name": "pts", "distance": 100, "unit": "m", "dissolve": True})
        assert "缓冲区" in r

    def test_buffer_km(self):
        _setup("square", _SQUARE_A)
        r = spatial_buffer.invoke({"layer_name": "square", "distance": 1, "unit": "km", "dissolve": False})
        assert "缓冲区" in r

    def test_buffer_nonexistent(self):
        r = spatial_buffer.invoke({"layer_name": "nope", "distance": 100})
        assert "未找到图层" in r


class TestSpatialIntersect:
    def test_overlapping(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)
        r = spatial_intersect.invoke({"layer_a": "A", "layer_b": "B"})
        assert "相交" in r
        assert len(_pending_layers) == 1

    def test_no_overlap(self):
        far = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[10,10],[12,10],[12,12],[10,12],[10,10]]]}
        }]}
        _setup("A", _SQUARE_A)
        _setup("far", far)
        r = spatial_intersect.invoke({"layer_a": "A", "layer_b": "far"})
        assert "没有重叠" in r


class TestSpatialUnion:
    def test_union(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)
        r = spatial_union.invoke({"layer_a": "A", "layer_b": "B"})
        assert "合并" in r
        assert len(_pending_layers) == 1


class TestSpatialDifference:
    def test_difference(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)
        r = spatial_difference.invoke({"layer_a": "A", "layer_b": "B"})
        assert "差异" in r
        assert len(_pending_layers) == 1

    def test_fully_covered(self):
        _setup("B", _SQUARE_B)
        big = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[0,0],[4,0],[4,4],[0,4],[0,0]]]}
        }]}
        _setup("big", big)
        r = spatial_difference.invoke({"layer_a": "B", "layer_b": "big"})
        assert "完全被" in r


class TestSpatialClip:
    def test_clip(self):
        _setup("A", _SQUARE_A)
        clip = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[0.5,0.5],[1.5,0.5],[1.5,1.5],[0.5,1.5],[0.5,0.5]]]}
        }]}
        _setup("clip", clip)
        r = spatial_clip.invoke({"layer_name": "A", "clip_layer": "clip"})
        assert "裁剪" in r
        assert len(_pending_layers) == 1

    def test_clip_no_overlap(self):
        _setup("A", _SQUARE_A)
        far = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[10,10],[11,10],[11,11],[10,11],[10,10]]]}
        }]}
        _setup("far", far)
        r = spatial_clip.invoke({"layer_name": "A", "clip_layer": "far"})
        assert "无剩余" in r


class TestSpatialCentroid:
    def test_polygon(self):
        _setup("square", _SQUARE_A)
        r = spatial_centroid.invoke({"layer_name": "square"})
        assert "质心" in r
        assert len(_pending_layers) == 1

    def test_points(self):
        _setup("pts", _POINTS)
        r = spatial_centroid.invoke({"layer_name": "pts"})
        assert "质心" in r

    def test_line(self):
        _setup("line", _LINE)
        r = spatial_centroid.invoke({"layer_name": "line"})
        assert "质心" in r


class TestSpatialSimplify:
    def test_simplify(self):
        geom = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[0,0],[0.5,0.01],[1,0],[1.5,0.01],[2,0],[2,1],[1.5,0.99],[1,1],[0.5,0.99],[0,1],[0,0]]]}
        }]}
        _setup("complex", geom)
        r = spatial_simplify.invoke({"layer_name": "complex", "tolerance": 0.1})
        assert "简化" in r
        assert len(_pending_layers) == 1

    def test_nonexistent(self):
        r = spatial_simplify.invoke({"layer_name": "nope"})
        assert "未找到图层" in r


class TestSpatialDissolve:
    def test_dissolve_all(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_dissolve.invoke({"layer_name": "multi"})
        assert "融合" in r
        assert len(_pending_layers) == 1

    def test_dissolve_by_field(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_dissolve.invoke({"layer_name": "multi", "group_by": "group"})
        assert "融合" in r
        assert len(_pending_layers) == 1

    def test_nonexistent(self):
        r = spatial_dissolve.invoke({"layer_name": "nope"})
        assert "未找到图层" in r


# ============================================================
# Phase 2 tests
# ============================================================

_JOIN_TARGET = {
    "type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": 1}, "geometry": {"type": "Polygon", "coordinates": [[[0,0],[2,0],[2,2],[0,2],[0,0]]]}},
    ]
}
_JOIN_LAYER = {
    "type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"label": "A"}, "geometry": {"type": "Point", "coordinates": [1, 1]}},
        {"type": "Feature", "properties": {"label": "B"}, "geometry": {"type": "Point", "coordinates": [5, 5]}},
    ]
}
_WITH_COORDS = {
    "type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "p1", "lng": 116.4, "lat": 39.9}, "geometry": None},
        {"type": "Feature", "properties": {"name": "p2", "lng": 116.5, "lat": 40.0}, "geometry": None},
    ]
}


class TestSpatialJoin:
    def test_join_intersects(self):
        _setup("target", _JOIN_TARGET)
        _setup("points", _JOIN_LAYER)
        r = spatial_join.invoke({"target_layer": "target", "join_layer": "points", "how": "left", "predicate": "intersects"})
        assert "连接" in r
        assert len(_pending_layers) == 1

    def test_join_nonexistent(self):
        _setup("target", _JOIN_TARGET)
        r = spatial_join.invoke({"target_layer": "target", "join_layer": "nope"})
        assert "未找到图层" in r


class TestLayerMerge:
    def test_merge_two(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)
        r = layer_merge.invoke({"layer_names": "A, B", "new_name": "merged"})
        assert "合并" in r
        assert len(_pending_layers) == 1

    def test_merge_nonexistent(self):
        _setup("A", _SQUARE_A)
        r = layer_merge.invoke({"layer_names": "A, nope"})
        assert "未找到图层" in r


class TestLayerSplit:
    def test_split_by_field(self):
        _setup("multi", _MULTI_POLY)
        r = layer_split.invoke({"layer_name": "multi", "by_field": "group"})
        assert "拆分" in r

    def test_split_individual(self):
        _setup("multi", _MULTI_POLY)
        r = layer_split.invoke({"layer_name": "multi"})
        assert "拆分" in r

    def test_split_nonexistent(self):
        r = layer_split.invoke({"layer_name": "nope"})
        assert "未找到图层" in r


class TestLayerAddGeometry:
    def test_add_geometry_auto(self):
        _setup("coords", _WITH_COORDS)
        r = layer_add_geometry.invoke({"layer_name": "coords"})
        assert "创建" in r
        assert len(_pending_layers) == 1

    def test_add_geometry_nonexistent(self):
        r = layer_add_geometry.invoke({"layer_name": "nope"})
        assert "未找到图层" in r


class TestReverseGeocode:
    def test_no_key(self):
        old = T._current_amap_key
        T._current_amap_key = ""
        r = reverse_geocode.invoke({"lng": 116.4, "lat": 39.9})
        T._current_amap_key = old
        assert "未配置" in r

    def test_invalid_coords(self):
        old = T._current_amap_key
        T._current_amap_key = "test_key"
        r = reverse_geocode.invoke({"lng": 999, "lat": 999})
        T._current_amap_key = old
        assert "失败" in r or "错误" in r


class TestBatchGeocode:
    def test_no_key(self):
        old = T._current_amap_key
        T._current_amap_key = ""
        r = batch_geocode.invoke({"addresses": "北京"})
        T._current_amap_key = old
        assert "未配置" in r

    def test_no_address(self):
        old = T._current_amap_key
        T._current_amap_key = "test_key"
        r = batch_geocode.invoke({"addresses": ""})
        T._current_amap_key = old
        assert "至少一个地址" in r


class TestSpatialSelect:
    def test_select_intersects(self):
        _setup("target", _SQUARE_A)
        _setup("source", _SQUARE_B)
        r = spatial_select.invoke({"target_layer": "target", "source_layer": "source"})
        assert "选择" in r
        assert len(_pending_layers) == 1

    def test_select_no_overlap(self):
        _setup("target", _SQUARE_A)
        far = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[10,10],[12,10],[12,12],[10,12],[10,10]]]}
        }]}
        _setup("far", far)
        r = spatial_select.invoke({"target_layer": "target", "source_layer": "far"})
        assert "没有要素" in r

    def test_select_nonexistent(self):
        _setup("target", _SQUARE_A)
        r = spatial_select.invoke({"target_layer": "target", "source_layer": "nope"})
        assert "未找到图层" in r


class TestSpatialSample:
    def test_sample_n(self):
        _setup("pts", _POINTS)
        r = spatial_sample.invoke({"layer_name": "pts", "n": 2})
        assert "采样" in r
        assert len(_pending_layers) == 1

    def test_sample_no_args(self):
        _setup("pts", _POINTS)
        r = spatial_sample.invoke({"layer_name": "pts"})
        assert "请指定" in r


class TestSpatialNear:
    def test_near(self):
        _setup("target", _SQUARE_A)
        pts = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.001, 0.001]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [10, 10]}},
        ]}
        _setup("pts", pts)
        r = spatial_near.invoke({"layer_name": "target", "target_layer": "pts", "distance": 1000})
        assert "找到" in r or "要素" in r

    def test_near_nonexistent(self):
        _setup("target", _SQUARE_A)
        r = spatial_near.invoke({"layer_name": "target", "target_layer": "nope"})
        assert "未找到图层" in r


class TestSpatialCluster:
    def test_cluster(self):
        pts = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.001, 0.001]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.002, 0.002]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]}
        _setup("pts", pts)
        r = spatial_cluster.invoke({"layer_name": "pts", "eps": 0.01, "min_samples": 2})
        assert "聚类" in r
        assert len(_pending_layers) == 1

    def test_cluster_too_few(self):
        _setup("pts", _POINTS)
        r = spatial_cluster.invoke({"layer_name": "pts", "eps": 0.01, "min_samples": 10})
        assert "少于" in r


class TestSpatialVoronoi:
    def test_voronoi(self):
        _setup("pts", _POINTS)
        r = spatial_voronoi.invoke({"layer_name": "pts"})
        assert "泰森" in r or "生成" in r
        assert len(_pending_layers) == 1

    def test_voronoi_nonexistent(self):
        r = spatial_voronoi.invoke({"layer_name": "nope"})
        assert "未找到图层" in r


class TestSpatialFieldStats:
    def test_stats_exists(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_field_stats.invoke({"layer_name": "multi", "field": "val"})
        assert "统计" in r

    def test_stats_no_field(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_field_stats.invoke({"layer_name": "multi"})
        assert "数值字段" in r

    def test_stats_nonexistent(self):
        r = spatial_field_stats.invoke({"layer_name": "nope"})
        assert "未找到图层" in r
