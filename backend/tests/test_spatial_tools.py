"""
空间分析工具测试
使用简单 GeoJSON 验证 buffer/intersect/union/clip/centroid/simplify/dissolve
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import shutil
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
spatial_graduated_colors = T.spatial_graduated_colors
spatial_unique_values = T.spatial_unique_values
add_labels = T.add_labels
spatial_select_by_attribute = T.spatial_select_by_attribute
add_legend = T.add_legend
update_attribute = T.update_attribute
delete_features = T.delete_features
add_field = T.add_field
delete_field = T.delete_field
spatial_multi_ring_buffer = T.spatial_multi_ring_buffer
move_features = T.move_features
rotate_features = T.rotate_features
scale_features = T.scale_features
draw_feature = T.draw_feature
edit_vertices = T.edit_vertices
export_map = T.export_map
export_pdf = T.export_pdf
redo_cmd = T.redo
undo_cmd = T.undo
enable_snapping = T.enable_snapping
dem_analysis = T.dem_analysis
extract_contours = T.extract_contours
ndvi_analysis = T.ndvi_analysis
raster_calculator = T.raster_calculator
spatial_interpolate = T.spatial_interpolate
topology_check = T.topology_check
hydrology_analysis = T.hydrology_analysis
create_workflow = T.create_workflow
view_3d_terrain = T.view_3d_terrain
animate_time = T.animate_time
link_chart_map = T.link_chart_map
terrain_profile = T.terrain_profile
convert_crs = T.convert_crs
convert_coordinates = T.convert_coordinates
clip_raster = T.clip_raster


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


class TestSpatialGraduatedColors:
    def test_graduated_numeric(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_graduated_colors.invoke({"layer_name": "multi", "field": "val", "n_classes": 3, "color_scheme": "reds"})
        assert "分级色彩" in r
        assert "val" in r
        assert len(T._pending_layer_ops) == 1
        op = T._pending_layer_ops[0]
        assert op["action"] == "symbology"
        assert op["symbology_type"] == "graduated"
        assert op["classes"] == 3
        assert op["scheme"] == "reds"

    def test_graduated_nonexistent_layer(self):
        r = spatial_graduated_colors.invoke({"layer_name": "nope", "field": "val"})
        assert "未找到图层" in r

    def test_graduated_nonexistent_field(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_graduated_colors.invoke({"layer_name": "multi", "field": "nonexist"})
        assert "没有字段" in r

    def test_graduated_string_field(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_graduated_colors.invoke({"layer_name": "multi", "field": "group"})
        assert "不是数值类型" in r

    def test_graduated_clamp_classes(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_graduated_colors.invoke({"layer_name": "multi", "field": "val", "n_classes": 99})
        assert "分级色彩" in r


class TestSpatialUniqueValues:
    def test_unique_string(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_unique_values.invoke({"layer_name": "multi", "field": "group", "color_scheme": "scheme"})
        assert "唯一值" in r
        assert "group" in r
        assert len(T._pending_layer_ops) == 1
        op = T._pending_layer_ops[0]
        assert op["action"] == "symbology"
        assert op["symbology_type"] == "unique"
        assert op["field"] == "group"

    def test_unique_nonexistent_layer(self):
        r = spatial_unique_values.invoke({"layer_name": "nope", "field": "group"})
        assert "未找到图层" in r

    def test_unique_nonexistent_field(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_unique_values.invoke({"layer_name": "multi", "field": "nonexist"})
        assert "没有字段" in r


class TestAddLabels:
    def test_labels_basic(self):
        _setup("multi", _MULTI_POLY)
        r = add_labels.invoke({"layer_name": "multi", "field": "group"})
        assert "标注" in r
        assert len(T._pending_layer_ops) == 1
        op = T._pending_layer_ops[0]
        assert op["action"] == "labels"
        assert op["field"] == "group"

    def test_labels_nonexistent_layer(self):
        r = add_labels.invoke({"layer_name": "nope", "field": "group"})
        assert "未找到图层" in r

    def test_labels_nonexistent_field(self):
        _setup("multi", _MULTI_POLY)
        r = add_labels.invoke({"layer_name": "multi", "field": "nonexist"})
        assert "没有字段" in r


_MULTI_SELECT = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"name": "A", "val": 10, "cat": "x"},
         "geometry": {"type":"Point", "coordinates":[0,0]}},
        {"type": "Feature", "properties": {"name": "B", "val": 20, "cat": "x"},
         "geometry": {"type":"Point", "coordinates":[1,1]}},
        {"type": "Feature", "properties": {"name": "C", "val": 30, "cat": "y"},
         "geometry": {"type":"Point", "coordinates":[2,2]}},
        {"type": "Feature", "properties": {"name": "D", "val": 40, "cat": "y"},
         "geometry": {"type":"Point", "coordinates":[3,3]}},
        {"type": "Feature", "properties": {"name": "E", "val": 50, "cat": "z"},
         "geometry": {"type":"Point", "coordinates":[4,4]}},
    ]
}

class TestSelectByAttribute:
    def test_eq_numeric(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": "=", "value": "20"})
        assert "选择了" in r
        assert "1/5" in r

    def test_gt_numeric(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": ">", "value": "30"})
        assert "选择了 2/5" in r

    def test_gte_numeric(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": ">=", "value": "30"})
        assert "选择了 3/5" in r

    def test_lt_numeric(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": "<", "value": "30"})
        assert "选择了 2/5" in r

    def test_lte_numeric(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": "<=", "value": "30"})
        assert "选择了 3/5" in r

    def test_neq_numeric(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": "!=", "value": "30"})
        assert "选择了 4/5" in r

    def test_eq_string(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "cat", "operator": "=", "value": "x"})
        assert "选择了 2/5" in r

    def test_neq_string(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "cat", "operator": "!=", "value": "x"})
        assert "选择了 3/5" in r

    def test_like(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "name", "operator": "like", "value": "A"})
        assert "选择了 1/5" in r

    def test_between(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": "between", "value": "15,45"})
        assert "选择了 3/5" in r

    def test_no_result(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": ">", "value": "999"})
        assert "没有满足条件" in r

    def test_nonexistent_layer(self):
        r = spatial_select_by_attribute.invoke({"layer_name": "nope", "field": "val", "operator": "=", "value": "1"})
        assert "未找到图层" in r

    def test_nonexistent_field(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "nonexist", "operator": "=", "value": "1"})
        assert "没有字段" in r

    def test_unsupported_operator(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "val", "operator": "xor", "value": "1"})
        assert "不支持的操作符" in r

    def test_string_on_gt(self):
        _setup("pts", _MULTI_SELECT)
        r = spatial_select_by_attribute.invoke({"layer_name": "pts", "field": "cat", "operator": ">", "value": "x"})
        assert "不是数值类型" in r


class TestAddLegend:
    def test_legend_basic(self):
        _setup("pts", _MULTI_SELECT)
        r = add_legend.invoke({"layer_name": "pts"})
        assert "图例" in r
        assert len(T._pending_layer_ops) == 1
        op = T._pending_layer_ops[0]
        assert op["action"] == "legend"
        assert op["name"] == "pts"

    def test_legend_nonexistent_layer(self):
        r = add_legend.invoke({"layer_name": "nope"})
        assert "未找到图层" in r


class TestUpdateAttribute:
    def test_update_all(self):
        _setup("pts", _MULTI_SELECT)
        r = update_attribute.invoke({"layer_name": "pts", "field": "val", "value": "99"})
        assert "已更新" in r
        assert "5/5" in r
        gj = _registered_layers["pts"]["geojson"]
        props = [f["properties"] for f in gj["features"]]
        assert all(p["val"] == 99 for p in props)

    def test_update_with_condition(self):
        _setup("pts", _MULTI_SELECT)
        r = update_attribute.invoke({"layer_name": "pts", "field": "val", "value": "99",
                                      "condition_field": "name", "condition_value": "C"})
        assert "已更新" in r
        assert "1/5" in r
        gj = _registered_layers["pts"]["geojson"]
        props = {f["properties"]["name"]: f["properties"]["val"] for f in gj["features"]}
        assert props["C"] == 99
        assert props["A"] == 10  # unchanged

    def test_update_string_field(self):
        _setup("pts", _MULTI_SELECT)
        r = update_attribute.invoke({"layer_name": "pts", "field": "name", "value": "X"})
        assert "已更新" in r
        gj = _registered_layers["pts"]["geojson"]
        names = [f["properties"]["name"] for f in gj["features"]]
        assert all(n == "X" for n in names)

    def test_nonexistent_layer(self):
        r = update_attribute.invoke({"layer_name": "nope", "field": "val", "value": "1"})
        assert "未找到图层" in r

    def test_nonexistent_field(self):
        _setup("pts", _MULTI_SELECT)
        r = update_attribute.invoke({"layer_name": "pts", "field": "nonexist", "value": "1"})
        assert "没有字段" in r

    def test_no_match_condition(self):
        _setup("pts", _MULTI_SELECT)
        r = update_attribute.invoke({"layer_name": "pts", "field": "val", "value": "99",
                                      "condition_field": "name", "condition_value": "ZZZ"})
        assert "没有要素满足条件" in r


class TestDeleteFeatures:
    def test_delete_with_condition(self):
        _setup("pts", _MULTI_SELECT)
        r = delete_features.invoke({"layer_name": "pts", "condition_field": "cat", "condition_value": "x"})
        assert "删除" in r
        assert "2/5" in r
        gj = _registered_layers["pts"]["geojson"]
        cats = [f["properties"]["cat"] for f in gj["features"]]
        assert "x" not in cats

    def test_delete_no_condition(self):
        _setup("pts", _MULTI_SELECT)
        r = delete_features.invoke({"layer_name": "pts"})
        assert "请指定删除条件" in r

    def test_delete_nonexistent_layer(self):
        r = delete_features.invoke({"layer_name": "nope", "condition_field": "cat", "condition_value": "x"})
        assert "未找到图层" in r

    def test_delete_no_match(self):
        _setup("pts", _MULTI_SELECT)
        r = delete_features.invoke({"layer_name": "pts", "condition_field": "cat", "condition_value": "nonexist"})
        assert "没有要素满足条件" in r

    def test_delete_single_feature(self):
        _setup("pts", _MULTI_SELECT)
        r = delete_features.invoke({"layer_name": "pts", "condition_field": "name", "condition_value": "A"})
        assert "删除" in r
        assert "1/5" in r
        gj = _registered_layers["pts"]["geojson"]
        names = [f["properties"]["name"] for f in gj["features"]]
        assert "A" not in names


class TestFieldManagement:
    def test_add_field_str(self):
        _setup("pts", _MULTI_SELECT)
        r = add_field.invoke({"layer_name": "pts", "field_name": "new_col", "field_type": "str"})
        assert "添加" in r
        gj = _registered_layers["pts"]["geojson"]
        assert "new_col" in gj["features"][0]["properties"]

    def test_add_field_int(self):
        _setup("pts", _MULTI_SELECT)
        r = add_field.invoke({"layer_name": "pts", "field_name": "count", "field_type": "int", "default_value": "0"})
        assert "添加" in r
        assert "int" in r or "字段" in r

    def test_add_field_duplicate(self):
        _setup("pts", _MULTI_SELECT)
        r = add_field.invoke({"layer_name": "pts", "field_name": "val", "field_type": "str"})
        assert "已存在" in r

    def test_delete_field(self):
        _setup("pts", _MULTI_SELECT)
        r = delete_field.invoke({"layer_name": "pts", "field_name": "val"})
        assert "删除" in r
        gj = _registered_layers["pts"]["geojson"]
        assert "val" not in gj["features"][0]["properties"]

    def test_delete_nonexistent_field(self):
        _setup("pts", _MULTI_SELECT)
        r = delete_field.invoke({"layer_name": "pts", "field_name": "nonexist"})
        assert "不存在" in r

    def test_delete_field_nonexistent_layer(self):
        r = delete_field.invoke({"layer_name": "nope", "field_name": "val"})
        assert "未找到图层" in r


_MULTI_RING = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"id": 1},
         "geometry": {"type":"Point", "coordinates":[116.4, 39.9]}},
    ]
}

class TestMultiRingBuffer:
    def test_multi_ring_basic(self):
        _setup("pt", _MULTI_RING)
        r = spatial_multi_ring_buffer.invoke({"layer_name": "pt", "distances": "100,200", "unit": "m"})
        assert "多环缓冲区" in r
        assert "2" in r

    def test_multi_ring_nonexistent(self):
        r = spatial_multi_ring_buffer.invoke({"layer_name": "nope", "distances": "100,200", "unit": "m"})
        assert "未找到图层" in r


class TestMoveFeatures:
    def test_move_basic_m(self):
        _setup("pts", _POINTS)
        r = move_features.invoke({"layer_name": "pts", "dx": 100, "dy": 100, "unit": "m"})
        assert "已移动" in r
        assert "pts" in r
        assert "3" in r

    def test_move_east_west(self):
        _setup("pts2", _POINTS)
        r = move_features.invoke({"layer_name": "pts2", "dx": -200, "dy": 0, "unit": "m"})
        assert "已移动" in r
        assert "西" in r

    def test_move_north_south(self):
        _setup("pts3", _POINTS)
        r = move_features.invoke({"layer_name": "pts3", "dx": 0, "dy": -200, "unit": "m"})
        assert "已移动" in r
        assert "南" in r

    def test_move_km(self):
        _setup("pts4", _POINTS)
        r = move_features.invoke({"layer_name": "pts4", "dx": 1, "dy": 0, "unit": "km"})
        assert "已移动" in r

    def test_move_nonexistent(self):
        r = move_features.invoke({"layer_name": "nope", "dx": 100, "dy": 0, "unit": "m"})
        assert "未找到图层" in r

    def test_move_zero_dxdy(self):
        _setup("pts5", _POINTS)
        r = move_features.invoke({"layer_name": "pts5", "dx": 0, "dy": 0, "unit": "m"})
        assert "不能同时为 0" in r

    def test_move_bad_unit(self):
        _setup("pts6", _POINTS)
        r = move_features.invoke({"layer_name": "pts6", "dx": 100, "dy": 0, "unit": "ft"})
        assert "不支持" in r or "ft" in r


class TestRotateFeatures:
    def test_rotate_basic(self):
        _setup("rpt", _POINTS)
        r = rotate_features.invoke({"layer_name": "rpt", "angle": 90})
        assert "已旋转" in r
        assert "rpt" in r
        assert "3" in r

    def test_rotate_clockwise(self):
        _setup("rpt2", _POINTS)
        r = rotate_features.invoke({"layer_name": "rpt2", "angle": -45})
        assert "顺时针" in r

    def test_rotate_counterclockwise(self):
        _setup("rpt3", _POINTS)
        r = rotate_features.invoke({"layer_name": "rpt3", "angle": 45})
        assert "逆时针" in r

    def test_rotate_no_angle(self):
        _setup("rpt4", _POINTS)
        r = rotate_features.invoke({"layer_name": "rpt4", "angle": 0})
        assert "已旋转" in r

    def test_rotate_nonexistent(self):
        r = rotate_features.invoke({"layer_name": "nope", "angle": 90})
        assert "未找到图层" in r


class TestScaleFeatures:
    def test_scale_enlarge(self):
        _setup("sc", _POINTS)
        r = scale_features.invoke({"layer_name": "sc", "x_factor": 2, "y_factor": 2})
        assert "已缩放" in r
        assert "sc" in r
        assert "3" in r

    def test_scale_shrink(self):
        _setup("sc2", _POINTS)
        r = scale_features.invoke({"layer_name": "sc2", "x_factor": 0.5, "y_factor": 0.5})
        assert "已缩放" in r

    def test_scale_invalid_factor(self):
        _setup("sc3", _POINTS)
        r = scale_features.invoke({"layer_name": "sc3", "x_factor": -1, "y_factor": 1})
        assert "大于 0" in r

    def test_scale_nonexistent(self):
        r = scale_features.invoke({"layer_name": "nope", "x_factor": 2, "y_factor": 2})
        assert "未找到图层" in r


class TestDrawFeature:
    def test_draw_point(self):
        r = draw_feature.invoke({"geometry_type": "Point", "coordinates": "116.4,39.9", "layer_name": "测试点"})
        assert "已创建" in r
        assert "Point" in r
        assert "测试点" in r
        assert "测试点" in _registered_layers

    def test_draw_linestring(self):
        r = draw_feature.invoke({"geometry_type": "LineString", "coordinates": "116.0,39.0;116.5,40.0;117.0,39.5", "layer_name": "测试线"})
        assert "已创建" in r
        assert "LineString" in r

    def test_draw_polygon(self):
        r = draw_feature.invoke({"geometry_type": "Polygon", "coordinates": "116.0,39.0;116.5,39.0;116.5,39.5;116.0,39.5;116.0,39.0", "layer_name": "测试面"})
        assert "已创建" in r
        assert "Polygon" in r

    def test_draw_invalid_type(self):
        r = draw_feature.invoke({"geometry_type": "MultiPoint", "coordinates": "116.0,39.0"})
        assert "不支持" in r

    def test_draw_bad_coords(self):
        r = draw_feature.invoke({"geometry_type": "Point", "coordinates": "abc,def"})
        assert "无法解析" in r

    def test_draw_auto_name(self):
        r = draw_feature.invoke({"geometry_type": "Point", "coordinates": "116.4,39.9"})
        assert "已创建" in r
        assert "绘制" in r

    def test_draw_rectangle(self):
        r = draw_feature.invoke({"geometry_type": "Rectangle", "coordinates": "116.0,39.0;116.5,39.5", "layer_name": "测试矩形"})
        assert "已创建" in r
        assert "Rectangle" in r
        assert "测试矩形" in r

    def test_draw_circle(self):
        r = draw_feature.invoke({"geometry_type": "Circle", "coordinates": "116.4,39.9;1000", "layer_name": "测试圆"})
        assert "已创建" in r
        assert "Circle" in r
        assert "测试圆" in r

    def test_draw_circle_bad_radius(self):
        r = draw_feature.invoke({"geometry_type": "Circle", "coordinates": "116.4,39.9;-100", "layer_name": "测试圆"})
        assert "大于 0" in r or r.startswith("已创建")

    def test_draw_rectangle_bad_coords(self):
        r = draw_feature.invoke({"geometry_type": "Rectangle", "coordinates": "116.0,39.0", "layer_name": "测试矩形"})
        assert "需要 2 个坐标" in r


class TestEditVertices:
    def setup_method(self):
        T.reset_state()
        _setup("test_polygon", _SQUARE_A)

    def test_edit_vertices_basic(self):
        r = edit_vertices.invoke({"layer_name": "test_polygon"})
        assert "已为" in r or "启用" in r

    def test_edit_vertices_nonexistent(self):
        r = edit_vertices.invoke({"layer_name": "不存在"})
        assert "不存在" in r or "没有" in r


class TestExportMap:
    def setup_method(self):
        T.reset_state()

    def test_export_png(self):
        r = export_map.invoke({"format": "png"})
        assert "已触发" in r or "导出" in r

    def test_export_jpg(self):
        r = export_map.invoke({"format": "jpg"})
        assert "已触发" in r or "导出" in r


class TestExportPdf:
    def setup_method(self):
        T.reset_state()

    def test_export_pdf_default(self):
        r = export_pdf.invoke({"title": "测试地图"})
        assert "已触发" in r or "PDF" in r

    def test_export_pdf_no_title(self):
        r = export_pdf.invoke({})
        assert "已触发" in r or "PDF" in r


class TestUndoRedo:
    def setup_method(self):
        T.reset_state()

    def test_undo(self):
        r = undo_cmd.invoke({})
        assert "撤销" in r

    def test_redo(self):
        r = redo_cmd.invoke({})
        assert "重做" in r


class TestSnapping:
    def setup_method(self):
        T.reset_state()

    def test_enable_snapping(self):
        r = enable_snapping.invoke({"enabled": True})
        assert "启用" in r

    def test_disable_snapping(self):
        r = enable_snapping.invoke({"enabled": False})
        assert "禁用" in r


class TestContour:
    def setup_method(self):
        T.reset_state()

    def _make_dem_tif(self, name, rows=50, cols=50, scale=1000):
        from rasterio.transform import from_bounds
        import numpy as np
        import tempfile, os, rasterio
        dem = np.random.rand(rows, cols).astype(np.float64) * scale
        transform = from_bounds(116, 39, 117, 40, cols, rows)
        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
        tmp.close()
        with rasterio.open(tmp.name, 'w', driver='GTiff', height=rows, width=cols,
                           count=1, dtype='float64', crs=None,
                           transform=transform) as dst:
            dst.write(dem, 1)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, f"{name}.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        return dest

    def test_contour_no_dem(self):
        r = extract_contours.invoke({"layer_name": "nonexistent"})
        assert "未找到" in r or "请先上传" in r

    def test_contour_auto_interval(self):
        dest = self._make_dem_tif("test_dem", 50, 50, 1000)
        r = extract_contours.invoke({"layer_name": "test_dem"})
        os.unlink(dest)
        assert "等高线" in r or "提取" in r

    def test_contour_explicit_interval(self):
        dest = self._make_dem_tif("test_contour", 30, 30, 500)
        r = extract_contours.invoke({"layer_name": "test_contour", "interval": 100})
        os.unlink(dest)
        assert "等高线" in r or "提取" in r


class TestNDVI:
    def setup_method(self):
        T.reset_state()

    def test_ndvi_no_file(self):
        r = ndvi_analysis.invoke({"layer_name": "nonexistent"})
        assert "未找到" in r or "请先上传" in r

    def test_ndvi_basic(self):
        from rasterio.transform import from_bounds
        import numpy as np
        import tempfile, os, rasterio
        rows, cols = 30, 30
        transform = from_bounds(116, 39, 117, 40, cols, rows)
        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
        tmp.close()
        with rasterio.open(tmp.name, 'w', driver='GTiff', height=rows, width=cols,
                           count=4, dtype='float64', crs=None,
                           transform=transform) as dst:
            band1 = np.ones((rows, cols), dtype=np.float64) * 0.1
            band4 = np.ones((rows, cols), dtype=np.float64) * 0.4
            dst.write(band1, 1)
            dst.write(np.zeros((rows, cols), dtype=np.float64), 2)
            dst.write(np.zeros((rows, cols), dtype=np.float64), 3)
            dst.write(band4, 4)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, "test_ndvi.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        r = ndvi_analysis.invoke({"layer_name": "test_ndvi"})
        os.unlink(dest)
        assert "NDVI" in r or "植被指数" in r

    def test_ndvi_too_few_bands(self):
        from rasterio.transform import from_bounds
        import numpy as np
        import tempfile, os, rasterio
        rows, cols = 10, 10
        transform = from_bounds(116, 39, 117, 40, cols, rows)
        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
        tmp.close()
        with rasterio.open(tmp.name, 'w', driver='GTiff', height=rows, width=cols,
                           count=1, dtype='float64', crs=None,
                           transform=transform) as dst:
            dst.write(np.ones((rows, cols), dtype=np.float64), 1)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, "test_ndvi2.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        r = ndvi_analysis.invoke({"layer_name": "test_ndvi2"})
        os.unlink(dest)
        assert "波段" in r or "失败" in r or "未找到" in r


class TestRasterCalculator:
    def setup_method(self):
        T.reset_state()

    def _make_band_tif(self, name, rows=20, cols=20):
        from rasterio.transform import from_bounds
        import numpy as np
        import tempfile, os, rasterio
        transform = from_bounds(116, 39, 117, 40, cols, rows)
        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
        tmp.close()
        with rasterio.open(tmp.name, 'w', driver='GTiff', height=rows, width=cols,
                           count=4, dtype='float64', crs=None,
                           transform=transform) as dst:
            dst.write(np.full((rows, cols), 0.2, dtype=np.float64), 1)
            dst.write(np.full((rows, cols), 0.5, dtype=np.float64), 2)
            dst.write(np.full((rows, cols), 0.3, dtype=np.float64), 3)
            dst.write(np.full((rows, cols), 0.8, dtype=np.float64), 4)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, f"{name}.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        return dest

    def test_calc_no_file(self):
        r = raster_calculator.invoke({"layer_name": "nope", "expression": "B1"})
        assert "未找到" in r or "请先上传" in r

    def test_calc_single_band(self):
        dest = self._make_band_tif("calc1")
        r = raster_calculator.invoke({"layer_name": "calc1", "expression": "B1*2"})
        os.unlink(dest)
        assert "栅格计算" in r or "执行" in r

    def test_calc_two_bands(self):
        dest = self._make_band_tif("calc2")
        r = raster_calculator.invoke({"layer_name": "calc2", "expression": "(B4-B3)/(B4+B3)"})
        os.unlink(dest)
        assert "栅格计算" in r or "执行" in r

    def test_calc_invalid_expr(self):
        dest = self._make_band_tif("calc3")
        r = raster_calculator.invoke({"layer_name": "calc3", "expression": "B1+unknown"})
        os.unlink(dest)
        assert "失败" in r or "错误" in r


class TestInterpolate:
    def setup_method(self):
        T.reset_state(), _register_layer("pts", _POINTS)

    def test_interpolate_basic(self):
        r = spatial_interpolate.invoke({"layer_name": "pts", "field": "id", "method": "idw"})
        assert "插值" in r or "生成" in r

    def test_interpolate_rbf(self):
        r = spatial_interpolate.invoke({"layer_name": "pts", "field": "id", "method": "rbf"})
        assert "插值" in r or "生成" in r

    def test_interpolate_bad_field(self):
        r = spatial_interpolate.invoke({"layer_name": "pts", "field": "nope", "method": "idw"})
        assert "没有字段" in r or "失败" in r

    def test_interpolate_nonexistent(self):
        r = spatial_interpolate.invoke({"layer_name": "nope", "field": "id", "method": "idw"})
        assert "未找到" in r or "没有" in r


class TestTopologyCheck:
    def setup_method(self):
        T.reset_state()

    def test_topo_nonexistent(self):
        r = topology_check.invoke({"layer_name": "nope"})
        assert "未找到" in r or "没有" in r

    def test_topo_valid_poly(self):
        fc = {"type":"FeatureCollection","features":[{
            "type":"Feature","properties":{"n":1},
            "geometry":{"type":"Polygon","coordinates":[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}
        }]}
        _register_layer("valid", fc)
        r = topology_check.invoke({"layer_name": "valid"})
        assert "未发现" in r or "无" in r

    def test_topo_invalid_geom(self):
        fc = {"type":"FeatureCollection","features":[{
            "type":"Feature","properties":{"n":1},
            "geometry":{"type":"Polygon","coordinates":[[[0,0],[2,0],[2,2],[0,2],[0,0],[1,1],[0,0]]]}
        }]}
        _register_layer("bad", fc)
        r = topology_check.invoke({"layer_name": "bad"})
        assert "发现" in r or "拓扑错误" in r or "无效" in r

    def test_topo_overlap(self):
        fc = {"type":"FeatureCollection","features":[
            {"type":"Feature","properties":{"n":1},
             "geometry":{"type":"Polygon","coordinates":[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}},
            {"type":"Feature","properties":{"n":2},
             "geometry":{"type":"Polygon","coordinates":[[[1,1],[3,1],[3,3],[1,3],[1,1]]]}}
        ]}
        _register_layer("overlap", fc)
        r = topology_check.invoke({"layer_name": "overlap"})
        assert "发现" in r or "重叠" in r or "拓扑错误" in r


class TestHydrology:
    def setup_method(self):
        T.reset_state()

    def _make_dem_tif(self, name, rows=30, cols=30):
        from rasterio.transform import from_bounds
        import numpy as np, tempfile, os, rasterio
        transform = from_bounds(116, 39, 117, 40, cols, rows)
        np.random.seed(42)
        dem = np.random.rand(rows, cols).astype(np.float64) * 500 + 100
        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
        tmp.close()
        with rasterio.open(tmp.name, 'w', driver='GTiff', height=rows, width=cols,
                           count=1, dtype='float64', crs=None,
                           transform=transform) as dst:
            dst.write(dem, 1)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, f"{name}.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        return dest

    def test_hydro_flowdir(self):
        dest = self._make_dem_tif("hydro_fd")
        r = hydrology_analysis.invoke({"layer_name": "hydro_fd", "analysis": "flowdir"})
        os.unlink(dest)
        assert "流向" in r or "水文" in r

    def test_hydro_flowacc(self):
        dest = self._make_dem_tif("hydro_fa")
        r = hydrology_analysis.invoke({"layer_name": "hydro_fa", "analysis": "flowacc"})
        os.unlink(dest)
        assert "汇流" in r or "水文" in r

    def test_hydro_streamnet(self):
        dest = self._make_dem_tif("hydro_sn")
        r = hydrology_analysis.invoke({"layer_name": "hydro_sn", "analysis": "streamnet", "threshold": 50})
        os.unlink(dest)
        assert "河网" in r or "Stream" in r or "水文" in r

    def test_hydro_nonexistent(self):
        r = hydrology_analysis.invoke({"layer_name": "nope", "analysis": "flowacc"})
        assert "未找到" in r or "请先上传" in r


class TestWorkflow:
    def setup_method(self):
        T.reset_state()

    def test_workflow_bad_json(self):
        r = create_workflow.invoke({"workflow_json": "not json"})
        assert "失败" in r or "错误" in r

    def test_workflow_empty(self):
        r = create_workflow.invoke({"workflow_json": "[]"})
        assert "非空" in r or "错误" in r

    def test_workflow_unknown_tool(self):
        wf = '[{"tool":"nope","params":{},"output":"x"}]'
        r = create_workflow.invoke({"workflow_json": wf})
        assert "未找到" in r or "错误" in r

    def test_workflow_simple(self):
        _register_layer("wf_pts", _POINTS)
        import json as _json
        wf = _json.dumps([{
            "tool": "spatial_buffer",
            "params": {"layer_name": "wf_pts", "distance": 1, "unit": "m", "dissolve": False},
            "output": "buf"
        }])
        r = create_workflow.invoke({"workflow_json": wf})
        assert "执行" in r or "完成" in r


class TestTimeAnimation:
    def setup_method(self):
        T.reset_state()

    def test_animate_time(self):
        _register_layer("anim_pts", _POINTS)
        r = animate_time.invoke({"layer_name": "anim_pts", "time_field": "id", "interval_ms": 300})
        assert "动画" in r or "启动" in r

    def test_animate_nonexistent(self):
        r = animate_time.invoke({"layer_name": "nope", "time_field": "id"})
        assert "未找到" in r or "没有" in r


class TestChartLink:
    def setup_method(self):
        T.reset_state()

    def test_chart_link(self):
        _register_layer("cl_pts", _POINTS)
        r = link_chart_map.invoke({"layer_name": "cl_pts", "chart_field": "id"})
        assert "图表联动" in r or "建立" in r

    def test_chart_link_nonexistent(self):
        r = link_chart_map.invoke({"layer_name": "nope", "chart_field": "id"})
        assert "未找到" in r or "没有" in r


class TestTerrain3D:
    def setup_method(self):
        T.reset_state()

    def _make_dem_tif(self, name, rows=30, cols=30):
        from rasterio.transform import from_bounds
        import numpy as np, tempfile, os, rasterio
        transform = from_bounds(116, 39, 117, 40, cols, rows)
        dem = np.random.rand(rows, cols).astype(np.float64) * 500 + 100
        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
        tmp.close()
        with rasterio.open(tmp.name, 'w', driver='GTiff', height=rows, width=cols,
                           count=1, dtype='float64', crs=None,
                           transform=transform) as dst:
            dst.write(dem, 1)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, f"{name}.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        return dest

    def test_3d_nonexistent(self):
        r = view_3d_terrain.invoke({"layer_name": "nope"})
        assert "未找到" in r or "请先上传" in r

    def test_3d_basic(self):
        dest = self._make_dem_tif("terr3d", 30, 30)
        r = view_3d_terrain.invoke({"layer_name": "terr3d", "exaggeration": 1.5})
        os.unlink(dest)
        assert "3D" in r or "地形" in r or "生成" in r


class TestTerrainProfile:
    def setup_method(self):
        T.reset_state()

    def _make_dem_tif(self, name, rows=50, cols=50):
        from rasterio.transform import from_bounds
        import numpy as np, tempfile, os, rasterio
        transform = from_bounds(116, 39, 117, 40, cols, rows)
        dem = np.random.rand(rows, cols).astype(np.float64) * 500 + 100
        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
        tmp.close()
        with rasterio.open(tmp.name, 'w', driver='GTiff', height=rows, width=cols,
                           count=1, dtype='float64', crs=None,
                           transform=transform) as dst:
            dst.write(dem, 1)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, f"{name}.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        return dest

    def test_profile_basic(self):
        dest = self._make_dem_tif("prof1", 50, 50)
        r = terrain_profile.invoke({"layer_name": "prof1", "line_coords": "[[116.2,39.2],[116.8,39.8]]"})
        os.unlink(dest)
        assert "剖面" in r or "高程" in r or "生成" in r

    def test_profile_nonexistent(self):
        r = terrain_profile.invoke({"layer_name": "nope", "line_coords": "[[116,39],[117,40]]"})
        assert "未找到" in r or "请先上传" in r


class TestConvertCRS:
    def setup_method(self):
        T.reset_state()

    def test_convert_crs_same(self):
        _register_layer("crs_pts", _POINTS)
        r = convert_crs.invoke({"layer_name": "crs_pts", "target_crs": "wgs84"})
        assert "已经是" in r or "已是" in r

    def test_convert_crs_mercator(self):
        _register_layer("crs_pts2", _POINTS)
        r = convert_crs.invoke({"layer_name": "crs_pts2", "target_crs": "web_mercator"})
        assert "转换" in r or "生成" in r

    def test_convert_crs_nonexistent(self):
        r = convert_crs.invoke({"layer_name": "nope"})
        assert "未找到" in r or "没有" in r

    def test_convert_coords_basic(self):
        r = convert_coordinates.invoke({"coords": "116.4,39.9", "source_crs": "wgs84", "target_crs": "web_mercator"})
        assert "→" in r

    def test_convert_coords_batch(self):
        r = convert_coordinates.invoke({"coords": "116,39;117,40", "source_crs": "wgs84", "target_crs": "web_mercator"})
        assert "→" in r

    def test_convert_coords_same_crs(self):
        r = convert_coordinates.invoke({"coords": "116.4,39.9", "source_crs": "wgs84", "target_crs": "wgs84"})
        assert "无需转换" in r


class TestClipRaster:
    def setup_method(self):
        T.reset_state()

    def _make_clip_tif(self, name, rows=20, cols=20):
        from rasterio.transform import from_bounds
        import numpy as np, tempfile, os, rasterio
        transform = from_bounds(116, 39, 117, 40, cols, rows)
        dem = np.random.rand(rows, cols).astype(np.float64) * 500 + 100
        tmp = tempfile.NamedTemporaryFile(suffix='.tif', delete=False)
        tmp.close()
        with rasterio.open(tmp.name, 'w', driver='GTiff', height=rows, width=cols,
                           count=1, dtype='float64', crs=None,
                           transform=transform) as dst:
            dst.write(dem, 1)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, f"{name}.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        return dest

    def test_clip_nonexistent_raster(self):
        r = clip_raster.invoke({"layer_name": "nope", "clip_layer_name": "clip"})
        assert "未找到" in r or "请先上传" in r

    def test_clip_nonexistent_clip_layer(self):
        self._make_clip_tif("clip_test1", 20, 20)
        r = clip_raster.invoke({"layer_name": "clip_test1", "clip_layer_name": "nope"})
        assert "未找到" in r or "没有" in r

    def test_clip_basic(self):
        dest = self._make_clip_tif("clip_test2", 20, 20)
        clip_geom = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[116.2,39.2],[116.8,39.2],[116.8,39.8],[116.2,39.8],[116.2,39.2]]]}
        }]}
        _register_layer("clip_poly", clip_geom)
        r = clip_raster.invoke({"layer_name": "clip_test2", "clip_layer_name": "clip_poly"})
        os.unlink(dest)
        assert "裁剪" in r

    def test_clip_no_overlap(self):
        dest = self._make_clip_tif("clip_test3", 20, 20)
        far_geom = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[10,10],[11,10],[11,11],[10,11],[10,10]]]}
        }]}
        _register_layer("far_poly", far_geom)
        r = clip_raster.invoke({"layer_name": "clip_test3", "clip_layer_name": "far_poly"})
        os.unlink(dest)
        assert "失败" in r or "无重叠" in r or "为空" in r
