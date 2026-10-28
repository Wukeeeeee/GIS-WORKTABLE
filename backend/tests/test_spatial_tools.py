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
raster_reclassify = T.raster_reclassify
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


def test_provenance_processing_drops_malformed_buffer_parameters_without_raising():
    provenance = T._normalize_layer_provenance({
        "processing": {"tool": "spatial_buffer", "source_layer": "roads",
                       "parameters": {"distance": 10 ** 1000, "unit": [], "dissolve": "yes"}},
    })
    assert provenance is None


class TestSpatialBuffer:
    @pytest.mark.parametrize("distance,unit", [
        (0, "m"), (-100, "m"), (float("nan"), "m"),
        (float("inf"), "m"), (1e308, "km"),
    ])
    def test_invalid_distance_preserves_existing_result(self, distance, unit):
        _setup("pts", _POINTS)
        _setup("pts_缓冲区", _SQUARE_A)
        before = _registered_layers["pts_缓冲区"]["geojson"]
        result = spatial_buffer.invoke({"layer_name": "pts", "distance": distance, "unit": unit})
        assert result.startswith("缓冲区分析失败:")
        assert "有限正数" in result
        assert _registered_layers["pts_缓冲区"]["geojson"] == before
        assert not _pending_layers

    @pytest.mark.parametrize("unit", ["feet", "ft", "光年", ""])
    def test_buffer_rejects_unsupported_units_without_creating_output(self, unit):
        _setup("pts", _POINTS)
        before = set(_registered_layers)
        result = spatial_buffer.invoke({"layer_name": "pts", "distance": 100, "unit": unit})
        assert result.startswith("缓冲区分析失败:")
        assert "仅支持 m 或 km" in result
        assert set(_registered_layers) == before
        assert len(_pending_layers) == 0

    def test_buffer_simple(self):
        _setup("square", _SQUARE_A)
        r = spatial_buffer.invoke({"layer_name": "square", "distance": 10, "unit": "m", "dissolve": False})
        assert "缓冲区" in r
        assert len(_pending_layers) == 1
        expected = {"tool": "spatial_buffer", "source_layer": "square",
                    "parameters": {"distance": 10.0, "unit": "m", "dissolve": False}}
        assert _pending_layers[0]["provenance"]["processing"] == expected
        assert _registered_layers["square_缓冲区"]["provenance"]["processing"] == expected

    def test_buffer_dissolve(self):
        _setup("pts", _POINTS)
        r = spatial_buffer.invoke({"layer_name": "pts", "distance": 100, "unit": "m", "dissolve": True})
        assert "缓冲区" in r

    @pytest.mark.parametrize("coordinates,expected", [
        ([[179.9, 10.0], [-179.9, 10.0]], "跨越日期变更线"),
        ([[0.0, 85.0]], "超出 UTM 投影适用纬度"),
        ([[-20.0, 0.0], [20.0, 0.0]], "超过 6° 经度"),
        ([[999.0, 30.0]], "超出 WGS84 经纬度范围"),
        ([[0.0, -91.0]], "超出 WGS84 经纬度范围"),
    ])
    def test_buffer_rejects_extents_outside_local_utm_domain(self, coordinates, expected):
        points = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": index},
             "geometry": {"type": "Point", "coordinates": coordinate}}
            for index, coordinate in enumerate(coordinates)
        ]}
        _setup("edge_points", points)
        _setup("edge_points_缓冲区", _SQUARE_A)
        previous = _registered_layers["edge_points_缓冲区"]["geojson"]

        result = spatial_buffer.invoke({"layer_name": "edge_points", "distance": 1000, "unit": "m"})

        assert result.startswith("缓冲区分析失败:")
        assert expected in result
        assert _registered_layers["edge_points_缓冲区"]["geojson"] == previous
        assert not _pending_layers




class TestSpatialIntersect:
    def test_polygon_intersection_with_line_keeps_line_result(self):
        polygon = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"zone": "A"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        }]}
        line = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"road": "R1"},
            "geometry": {"type": "LineString", "coordinates": [[-1, 1], [3, 1]]},
        }]}
        _setup("overlay_polygon", polygon)
        _setup("overlay_line", line)

        result = spatial_intersect.invoke({"layer_a": "overlay_polygon", "layer_b": "overlay_line"})

        assert "相交分析完成" in result, result
        assert "相交覆盖面积" not in result
        features = _registered_layers["overlay_polygon_∩_overlay_line"]["geojson"]["features"]
        assert len(features) == 1
        assert features[0]["geometry"]["type"] == "LineString"
        assert features[0]["properties"]["road"] == "R1"
    def test_overlapping_input_records_use_unique_coverage(self):
        """覆盖范围叠置自身：保留四条属性组合，覆盖占比仍为 100%。"""
        from pyproj import Transformer
        rectangles = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": i}, "geometry": {
                "type": "Polygon", "coordinates": [[[x, 0], [x + 2, 0],
                    [x + 2, 2], [x, 2], [x, 0]]]}}
            for i, x in enumerate([0, 1])
        ]}
        _setup("overlapping_A", rectangles)
        _setup("overlapping_B", rectangles)
        result = spatial_intersect.invoke({"layer_a": "overlapping_A", "layer_b": "overlapping_B"})
        assert len(_pending_layers[-1]["geojson"]["features"]) == 4
        assert _pending_layers[-1]["provenance"]["processing"] == {
            "tool": "spatial_intersect", "source_layer": "overlapping_A", "other_layer": "overlapping_B",
        }
        assert _registered_layers["overlapping_A_∩_overlapping_B"]["provenance"]["processing"] == {
            "tool": "spatial_intersect", "source_layer": "overlapping_A", "other_layer": "overlapping_B",
        }
        assert result.count("100.00%") == 2, result
        projection = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
        left, bottom = projection.transform(0, 0)
        right, top = projection.transform(3, 2)
        expected = (right - left) * (top - bottom) / 1e6
        assert f"{expected:.4f} 平方千米" in result

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
        assert not _pending_layers, "empty intersection should not register a result layer"


class TestSpatialUnion:
    def test_union(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)
        r = spatial_union.invoke({"layer_a": "A", "layer_b": "B"})
        assert "合并" in r
        assert len(_pending_layers) == 1
        expected = {"tool": "spatial_union", "source_layer": "A", "other_layer": "B"}
        assert _pending_layers[0]["provenance"]["processing"] == expected
        assert _registered_layers["A__B"]["provenance"]["processing"] == expected

    def test_union_retains_line_geometry_from_mixed_inputs(self):
        polygon = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"zone": "A"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
        }]}
        line = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"road": "R1"},
            "geometry": {"type": "LineString", "coordinates": [[-1, 1], [3, 1]]},
        }]}
        _setup("union_polygon", polygon)
        _setup("union_line", line)

        result = spatial_union.invoke({"layer_a": "union_polygon", "layer_b": "union_line"})

        assert "合并完成" in result, result
        features = _registered_layers["union_polygon__union_line"]["geojson"]["features"]
        assert any(feature["geometry"]["type"] == "LineString" for feature in features)
        assert any(feature["properties"].get("road") == "R1" for feature in features)


class TestSpatialDifference:
    def test_difference(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)
        r = spatial_difference.invoke({"layer_a": "A", "layer_b": "B"})
        assert "差异" in r
        assert len(_pending_layers) == 1
        expected = {"tool": "spatial_difference", "source_layer": "A", "other_layer": "B"}
        assert _pending_layers[0]["provenance"]["processing"] == expected
        assert _registered_layers["A_减_B"]["provenance"]["processing"] == expected

    def test_no_remaining_geometry_does_not_register_result(self):
        _setup("A", _SQUARE_A)
        _setup("same_as_A", _SQUARE_A)
        result = spatial_difference.invoke({"layer_a": "A", "layer_b": "same_as_A"})
        assert "完全被" in result
        assert not _pending_layers

    def test_difference_provenance_requires_both_input_layers(self):
        assert T._normalize_layer_provenance({
            "processing": {"tool": "spatial_difference", "source_layer": "A", "other_layer": ""},
        }) is None



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
        expected = {"tool": "spatial_clip", "source_layer": "A", "clip_layer": "clip"}
        assert _pending_layers[0]["provenance"]["processing"] == expected
        assert _registered_layers["A_裁剪"]["provenance"]["processing"] == expected

    def test_clip_provenance_requires_both_input_layers(self):
        assert T._normalize_layer_provenance({
            "processing": {"tool": "spatial_clip", "source_layer": "A", "clip_layer": ""},
        }) is None
        assert T._normalize_layer_provenance({
            "processing": {"tool": "spatial_union", "source_layer": "A", "other_layer": []},
        }) is None
        assert T._normalize_layer_provenance({
            "processing": {"tool": "spatial_intersect", "source_layer": "A", "other_layer": ""},
        }) is None



class TestSpatialCentroid:
    def test_polygon(self):
        _setup("square", _SQUARE_A)
        r = spatial_centroid.invoke({"layer_name": "square"})
        assert "质心" in r
        assert len(_pending_layers) == 1

    def test_polygon_centroid_uses_metric_projection(self):
        from shapely.geometry import Point

        polygon = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[
                [10, 60], [15, 60], [14, 65], [10, 65], [10, 60]
            ]]},
        }]}
        _setup("high_lat", polygon)
        gdf, _ = T._layer_to_gdf("high_lat")
        expected = (gdf.to_crs(gdf.estimate_utm_crs()).geometry.centroid
                    .to_crs("EPSG:4326").iloc[0])

        result = spatial_centroid.invoke({"layer_name": "high_lat"})
        assert "已提取 1 个质心" in result
        coords = _pending_layers[-1]["geojson"]["features"][0]["geometry"]["coordinates"]
        actual = Point(coords)
        assert actual.distance(expected) < 1e-6




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

    @pytest.mark.parametrize("tolerance", [0, -0.1, float("nan"), float("inf")])
    def test_invalid_tolerance_does_not_register_result(self, tolerance):
        _setup("complex", _SQUARE_A)
        before = set(_registered_layers)

        result = spatial_simplify.invoke({"layer_name": "complex", "tolerance": tolerance})

        assert result.startswith("简化失败:")
        assert "有限正数" in result
        assert set(_registered_layers) == before
        assert not _pending_layers



class TestSpatialDissolve:
    def test_dissolve_all(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_dissolve.invoke({"layer_name": "multi"})
        assert "融合" in r
        assert len(_pending_layers) == 1

    def test_grouped_dissolve_keeps_features_with_missing_group_value(self):
        features = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"zone": "north"},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}},
            {"type": "Feature", "properties": {},
             "geometry": {"type": "Polygon", "coordinates": [[[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]]}},
        ]}
        _setup("zoned", features)

        result = spatial_dissolve.invoke({"layer_name": "zoned", "group_by": "zone"})

        assert "2 个要素" in result
        output = _pending_layers[0]["geojson"]["features"]
        assert len(output) == 2
        assert {feature["properties"].get("zone") for feature in output} == {"north", None}

    def test_unknown_group_field_fails_without_dissolving_all(self):
        _setup("multi", _MULTI_POLY)
        before = set(_registered_layers)

        result = spatial_dissolve.invoke({"layer_name": "multi", "group_by": "missing_field"})

        assert result.startswith("融合失败:")
        assert "missing_field" in result
        assert set(_registered_layers) == before
        assert not _pending_layers




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

    def test_nearest_predicate_reports_supported_tool_without_creating_layer(self):
        _setup("target", _JOIN_TARGET)
        _setup("points", _JOIN_LAYER)

        result = spatial_join.invoke({
            "target_layer": "target", "join_layer": "points", "predicate": "nearest",
        })

        assert "nearest_pair" in result
        assert "空间连接失败" in result
        assert _pending_layers == []

    def test_join_preserves_existing_reserved_index_right_attribute(self):
        target = json.loads(json.dumps(_JOIN_TARGET))
        target["features"][0]["properties"]["index_right"] = "original-source-id"
        points = json.loads(json.dumps(_JOIN_LAYER))
        points["features"][0]["properties"]["index_right"] = "original-join-id"
        _setup("target_with_index_right", target)
        _setup("points_for_index_right", points)

        result = spatial_join.invoke({
            "target_layer": "target_with_index_right",
            "join_layer": "points_for_index_right",
            "how": "left",
            "predicate": "intersects",
        })

        assert "空间连接完成" in result, result
        properties = _registered_layers["target_with_index_right_连接points_for_index_right"]["geojson"]["features"][0]["properties"]
        assert properties["index_right_target"] == "original-source-id"
        assert properties["index_right_join"] == "original-join-id"



class TestLayerMerge:
    def test_merge_two(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)
        r = layer_merge.invoke({"layer_names": "A, B", "new_name": "merged"})
        assert "合并" in r
        assert len(_pending_layers) == 1

    def test_repeated_default_merge_keeps_distinct_results_registered(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)

        first = layer_merge.invoke({"layer_names": "A, B"})
        second = layer_merge.invoke({"layer_names": "A, B"})

        assert "A_B_合并" in first
        assert "A_B_合并_1" in second
        assert "A_B_合并" in _registered_layers
        assert "A_B_合并_1" in _registered_layers
        assert len(_registered_layers["A"]["geojson"]["features"]) == 1
        assert len(_registered_layers["B"]["geojson"]["features"]) == 1
        assert len(_pending_layers) == 2

    def test_explicit_output_name_collision_does_not_replace_an_input(self):
        _setup("A", _SQUARE_A)
        _setup("B", _SQUARE_B)

        result = layer_merge.invoke({"layer_names": "A, B", "new_name": "A"})

        assert "A_1" in result
        assert len(_registered_layers["A"]["geojson"]["features"]) == 1
        assert len(_registered_layers["A_1"]["geojson"]["features"]) == 2



class TestLayerSplit:
    def test_split_by_field(self):
        _setup("multi", _MULTI_POLY)
        r = layer_split.invoke({"layer_name": "multi", "by_field": "group"})
        assert "拆分" in r

    def test_split_by_field_keeps_features_with_missing_group_values(self):
        features = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"zone": "north"},
             "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {},
             "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]}
        _setup("zones", features)

        result = layer_split.invoke({"layer_name": "zones", "by_field": "zone"})

        assert "2 个子图层" in result
        outputs = [layer["geojson"]["features"] for layer in _pending_layers]
        assert sum(len(group) for group in outputs) == 2
        assert any(feature["properties"].get("zone") is None for group in outputs for feature in group)




class TestLayerAddGeometry:
    def test_add_geometry_auto(self):
        _setup("coords", _WITH_COORDS)
        r = layer_add_geometry.invoke({"layer_name": "coords"})
        assert "创建" in r
        assert len(_pending_layers) == 1

    def test_accepts_inclusive_geographic_coordinate_boundaries(self):
        features = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"longitude": -180, "latitude": -90}, "geometry": None},
            {"type": "Feature", "properties": {"longitude": 180, "latitude": 90}, "geometry": None},
        ]}
        _setup("coords-boundary", features)

        result = layer_add_geometry.invoke({"layer_name": "coords-boundary"})

        assert "2 个点" in result
        points = _pending_layers[0]["geojson"]["features"]
        assert [feature["geometry"]["coordinates"] for feature in points] == [[-180.0, -90.0], [180.0, 90.0]]

    @pytest.mark.parametrize("longitude,latitude,expected", [
        (180.1, 0, "有效范围"), (0, 90.1, "有效范围"),
        (float("nan"), 0, "有限数值"), (None, 0, "有效数值"), ("invalid", 0, "有效数值"),
    ])
    def test_rejects_invalid_coordinates_without_registering_partial_layer(self, longitude, latitude, expected):
        features = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"longitude": longitude, "latitude": latitude},
             "geometry": None},
        ]}
        _setup("coords", features)
        registered_before = set(_registered_layers)

        result = layer_add_geometry.invoke({"layer_name": "coords"})

        assert expected in result
        assert _pending_layers == []
        assert set(_registered_layers) == registered_before



class TestReverseGeocode:
    def test_no_key(self):
        old = T._current_amap_key
        T._current_amap_key = ""
        r = reverse_geocode.invoke({"lng": 116.4, "lat": 39.9})
        T._current_amap_key = old
        assert "未配置" in r



class TestBatchGeocode:
    def test_no_key(self):
        old = T._current_amap_key
        T._current_amap_key = ""
        r = batch_geocode.invoke({"addresses": "北京"})
        T._current_amap_key = old
        assert "未配置" in r



class TestSpatialSelect:
    def test_select_intersects(self):
        _setup("target", _SQUARE_A)
        _setup("source", _SQUARE_B)
        r = spatial_select.invoke({"target_layer": "target", "source_layer": "source"})
        assert "选择" in r
        assert len(_pending_layers) == 1

    def test_select_preserves_distinct_duplicate_features(self):
        same_geometry = {"type": "Point", "coordinates": [0.5, 0.5]}
        targets = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "target-1", "properties": {}, "geometry": same_geometry},
            {"type": "Feature", "id": "target-2", "properties": {}, "geometry": same_geometry},
        ]}
        source = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}},
        ]}
        _setup("duplicate_targets", targets)
        _setup("covering_source", source)

        result = spatial_select.invoke({"target_layer": "duplicate_targets", "source_layer": "covering_source"})

        assert "2/2" in result
        output = _pending_layers[0]["geojson"]["features"]
        assert len(output) == 2




class TestSpatialSample:
    def test_sample_n(self):
        _setup("pts", _POINTS)
        r = spatial_sample.invoke({"layer_name": "pts", "n": 2})
        assert "采样" in r
        assert len(_pending_layers) == 1

    def test_sample_fraction(self):
        _setup("pts", _POINTS)

        result = spatial_sample.invoke({"layer_name": "pts", "frac": 0.5})

        assert "采样" in result
        assert 1 <= len(_pending_layers[0]["geojson"]["features"]) <= 3

    @pytest.mark.parametrize("args", [
        {"n": -1},
        {"frac": -0.1},
        {"frac": float("nan")},
        {"frac": float("inf")},
        {"frac": 1.1},
        {"n": 1, "frac": 0.5},
    ])
    def test_sample_rejects_invalid_or_ambiguous_parameters_without_registering(self, args):
        _setup("pts", _POINTS)

        result = spatial_sample.invoke({"layer_name": "pts", **args})

        assert "失败" in result
        assert _pending_layers == []



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

    def test_near_distance_uses_local_ground_meters_at_high_latitude(self):
        source = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "Point", "coordinates": [3.0, 60.0]}},
        ]}
        target = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "Point", "coordinates": [3.01, 60.0]}},
        ]}
        _setup("source", source)
        _setup("target", target)

        result = spatial_near.invoke({"layer_name": "source", "target_layer": "target", "distance": 600})

        assert "找到 1 个" in result
        assert len(_pending_layers) == 1

    @pytest.mark.parametrize("distance", [-1, float("nan"), float("inf"), float("-inf")])
    def test_near_rejects_negative_or_non_finite_distance(self, distance):
        _setup("source", _POINTS)
        _setup("target", _POINTS)

        result = spatial_near.invoke({"layer_name": "source", "target_layer": "target", "distance": distance})

        assert "有限的非负米数" in result
        assert _pending_layers == []

    def test_near_zero_distance_includes_intersecting_points(self):
        points = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "Point", "coordinates": [3.0, 60.0]}},
        ]}
        _setup("source", points)
        _setup("target", points)

        result = spatial_near.invoke({"layer_name": "source", "target_layer": "target", "distance": 0})

        assert "找到 1 个" in result
        assert len(_pending_layers) == 1



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

    def test_cluster_rejects_non_point_input_without_registering_a_result(self):
        _setup("areas", _SQUARE_A)

        result = spatial_cluster.invoke({"layer_name": "areas", "eps": 0.01, "min_samples": 2})

        assert "仅支持 Point 点图层" in result
        assert _pending_layers == []

    def test_metric_cluster_rejects_extents_outside_local_utm_domain(self):
        points = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": index},
             "geometry": {"type": "Point", "coordinates": coordinate}}
            for index, coordinate in enumerate([[-20.0, 0.0], [20.0, 0.0]])
        ]}
        _setup("wide_points", points)

        result = spatial_cluster.invoke({
            "layer_name": "wide_points", "eps": 100, "min_samples": 2, "distance_unit": "m",
        })

        assert "超过 6° 经度" in result
        assert _pending_layers == []

    @pytest.mark.parametrize("eps,min_samples", [
        (0, 2), (-0.1, 2), (float("nan"), 2), (float("inf"), 2), (0.01, 0),
    ])
    def test_cluster_rejects_invalid_parameters_without_registering_a_result(self, eps, min_samples):
        _setup("pts", _POINTS)

        result = spatial_cluster.invoke({"layer_name": "pts", "eps": eps, "min_samples": min_samples})

        assert result.startswith("聚类失败:")
        assert _pending_layers == []

    @pytest.mark.parametrize("eps,unit,labels", [
        (500, "m", [0, 0]), (100, "m", [-1, -1]),
        (0.5, "km", [0, 0]), (0.1, "km", [-1, -1]),
    ])
    def test_cluster_supports_ground_distance_units_at_high_latitude(self, eps, unit, labels):
        sites = [[0.0, 80.0], [0.02, 80.0]]
        points = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": index},
             "geometry": {"type": "Point", "coordinates": coordinate}}
            for index, coordinate in enumerate(sites)
        ]}
        _setup("high_latitude_sites", points)
        from pyproj import Geod
        ground_distance_m = abs(Geod(ellps="WGS84").inv(*sites[0], *sites[1])[2])
        assert 100 < ground_distance_m < 500

        result = spatial_cluster.invoke({
            "layer_name": "high_latitude_sites", "eps": eps,
            "min_samples": 2, "distance_unit": unit,
        })

        expected_clusters = 1 if labels[0] == 0 else 0
        expected_noise = 0 if expected_clusters else 2
        assert f"{expected_clusters} 个簇，{expected_noise} 个噪声点" in result
        assert f"eps={eps}{unit}" in result
        assert [feature["properties"]["cluster"]
                for feature in _pending_layers[-1]["geojson"]["features"]] == labels

    def test_cluster_rejects_unsupported_distance_unit_without_registering_result(self):
        _setup("pts", _POINTS)

        result = spatial_cluster.invoke({
            "layer_name": "pts", "eps": 500, "min_samples": 2, "distance_unit": "yards",
        })

        assert "仅支持 degrees、m 或 km" in result
        assert _pending_layers == []



class TestSpatialVoronoi:
    def test_voronoi(self):
        _setup("pts", _POINTS)
        r = spatial_voronoi.invoke({"layer_name": "pts"})
        assert "泰森" in r or "生成" in r
        assert len(_pending_layers) == 1

    def test_voronoi_rejects_non_point_input_without_registering_a_result(self):
        _setup("areas", _SQUARE_A)

        result = spatial_voronoi.invoke({"layer_name": "areas"})

        assert "仅支持 Point 或 MultiPoint" in result
        assert _pending_layers == []

    @pytest.mark.parametrize("coordinates", [
        [[3.0, 60.0]],
        [[3.0, 60.0], [3.0, 60.0]],
    ])
    def test_voronoi_requires_two_distinct_point_locations(self, coordinates):
        points = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": index},
             "geometry": {"type": "Point", "coordinates": coordinate}}
            for index, coordinate in enumerate(coordinates)
        ]}
        _setup("sites", points)

        result = spatial_voronoi.invoke({"layer_name": "sites"})

        assert "至少需要 2 个位置不同的点" in result
        assert _pending_layers == []

    def test_voronoi_uses_local_metric_coordinates_for_high_latitude_sites(self):
        sites = [[0.0, 80.0], [1.0, 80.0], [1.0, 81.0]]
        points = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": index},
             "geometry": {"type": "Point", "coordinates": coordinate}}
            for index, coordinate in enumerate(sites)
        ]}
        _setup("polar_sites", points)

        result = spatial_voronoi.invoke({"layer_name": "polar_sites"})

        assert "已生成" in result
        from shapely.geometry import Point, shape
        cells = [shape(feature["geometry"]) for feature in _pending_layers[0]["geojson"]["features"]]
        site_zero_cell = next(cell for cell in cells if cell.covers(Point(*sites[0])))
        # In this high-latitude sample, degree-plane Voronoi incorrectly puts
        # this probe in site 0's region; local UTM ground distance makes site 2 nearer.
        assert not site_zero_cell.covers(Point(0.01, 80.52))



class TestSpatialFieldStats:
    def test_stats_exists(self):
        _setup("multi", _MULTI_POLY)
        r = spatial_field_stats.invoke({"layer_name": "multi", "field": "val"})
        assert "统计" in r




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




class TestAddLabels:
    def test_labels_basic(self):
        _setup("multi", _MULTI_POLY)
        r = add_labels.invoke({"layer_name": "multi", "field": "group"})
        assert "标注" in r
        assert len(T._pending_layer_ops) == 1
        op = T._pending_layer_ops[0]
        assert op["action"] == "labels"
        assert op["field"] == "group"




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

    def test_like_treats_regex_metacharacters_as_literal_text(self):
        features = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"label": "zone [A]"},
             "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {"label": "zone A"},
             "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]}
        _setup("labels", features)

        result = spatial_select_by_attribute.invoke({
            "layer_name": "labels", "field": "label", "operator": "like", "value": "[",
        })

        assert "选择了 1/2 个要素" in result
        assert len(_pending_layers[0]["geojson"]["features"]) == 1

    def test_like_does_not_match_null_values_after_string_conversion(self):
        features = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"label": None},
             "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {"label": "none"},
             "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]}
        _setup("nullable_labels", features)

        result = spatial_select_by_attribute.invoke({
            "layer_name": "nullable_labels", "field": "label", "operator": "like", "value": "none",
        })

        assert "选择了 1/2 个要素" in result
        assert len(_pending_layers[0]["geojson"]["features"]) == 1















class TestAddLegend:
    def test_legend_basic(self):
        _setup("pts", _MULTI_SELECT)
        r = add_legend.invoke({"layer_name": "pts"})
        assert "图例" in r
        assert len(T._pending_layer_ops) == 1
        op = T._pending_layer_ops[0]
        assert op["action"] == "legend"
        assert op["name"] == "pts"



class TestUpdateAttribute:
    def test_update_all(self):
        _setup("pts", _MULTI_SELECT)
        r = update_attribute.invoke({"layer_name": "pts", "field": "val", "value": "99"})
        assert "已更新" in r
        assert "5/5" in r
        gj = _registered_layers["pts"]["geojson"]
        props = [f["properties"] for f in gj["features"]]
        assert all(p["val"] == 99 for p in props)







class TestDeleteFeatures:
    def test_delete_with_condition(self):
        _setup("pts", _MULTI_SELECT)
        r = delete_features.invoke({"layer_name": "pts", "condition_field": "cat", "condition_value": "x"})
        assert "删除" in r
        assert "2/5" in r
        gj = _registered_layers["pts"]["geojson"]
        cats = [f["properties"]["cat"] for f in gj["features"]]
        assert "x" not in cats






class TestFieldManagement:
    def test_add_field_str(self):
        _setup("pts", _MULTI_SELECT)
        r = add_field.invoke({"layer_name": "pts", "field_name": "new_col", "field_type": "str"})
        assert "添加" in r
        gj = _registered_layers["pts"]["geojson"]
        assert "new_col" in gj["features"][0]["properties"]







_MULTI_RING = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"id": 1},
         "geometry": {"type":"Point", "coordinates":[116.4, 39.9]}},
    ]
}

class TestMultiRingBuffer:
    @pytest.mark.parametrize("coordinates,expected", [
        ([[179.9, 10.0], [-179.9, 10.0]], "跨越日期变更线"),
        ([[0.0, 85.0]], "超出 UTM 投影适用纬度"),
        ([[-20.0, 0.0], [20.0, 0.0]], "超过 6° 经度"),
        ([[999.0, 30.0]], "超出 WGS84 经纬度范围"),
        ([[0.0, -91.0]], "超出 WGS84 经纬度范围"),
    ])
    def test_multi_ring_rejects_extents_outside_local_utm_domain(self, coordinates, expected):
        points = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": index},
             "geometry": {"type": "Point", "coordinates": coordinate}}
            for index, coordinate in enumerate(coordinates)
        ]}
        _setup("edge_points", points)
        _setup("edge_points_多环m", _SQUARE_A)
        previous = _registered_layers["edge_points_多环m"]["geojson"]

        result = spatial_multi_ring_buffer.invoke({
            "layer_name": "edge_points", "distances": "100,200", "unit": "m",
        })

        assert result.startswith("多环缓冲区失败:")
        assert expected in result
        assert _registered_layers["edge_points_多环m"]["geojson"] == previous
        assert not _pending_layers

    @pytest.mark.parametrize("unit", ["feet", "ft", "光年", ""])
    def test_unsupported_unit_creates_no_output(self, unit):
        _setup("pt", _MULTI_RING)
        before = set(_registered_layers)
        result = spatial_multi_ring_buffer.invoke({"layer_name": "pt", "distances": "100,200", "unit": unit})
        assert result.startswith("多环缓冲区失败:")
        assert "仅支持 m 或 km" in result
        assert set(_registered_layers) == before
        assert not _pending_layers

    @pytest.mark.parametrize("distances,unit", [
        ("0,100", "m"), ("-100,200", "m"), ("100,nan", "m"),
        ("100,inf", "m"), ("100,-inf", "m"), ("100,1e309", "m"),
        ("100,1e308", "km"), ("100,,200", "m"), ("100,", "m"),
        ("bad,200", "m"), ("", "m"),
    ])
    def test_invalid_distance_preserves_existing_result(self, distances, unit):
        _setup("pt", _MULTI_RING)
        result_name = f"pt_多环{unit}"
        _setup(result_name, _SQUARE_A)
        before = _registered_layers[result_name]["geojson"]
        result = spatial_multi_ring_buffer.invoke({"layer_name": "pt", "distances": distances, "unit": unit})
        assert result.startswith("多环缓冲区失败:")
        assert "有限正数" in result
        assert _registered_layers[result_name]["geojson"] == before
        assert not _pending_layers

    @pytest.mark.parametrize("unit", ["km", "KM", " kilometers "])
    @pytest.mark.parametrize("dissolve", [False, True])
    def test_kilometer_aliases_have_correct_ground_distance(self, unit, dissolve):
        # Check ellipsoidal ground distance, independently of the UTM buffer calculation.
        from pyproj import Geod
        _setup("pt", _MULTI_RING)
        result = spatial_multi_ring_buffer.invoke({
            "layer_name": "pt", "distances": "1,2", "unit": unit, "dissolve": dissolve,
        })
        assert result.startswith("已为")
        assert len(_pending_layers) == 1
        assert _pending_layers[0]["name"] == "pt_多环km"
        features = _pending_layers[0]["geojson"]["features"]
        assert len(features) == 2
        geod = Geod(ellps="WGS84")
        for feature, radius_m in zip(features, [1000, 2000]):
            assert feature["properties"]["distance"] == radius_m / 1000
            assert feature["geometry"]["type"] == "Polygon"
            for lon, lat in feature["geometry"]["coordinates"][0]:
                actual_m = geod.inv(116.4, 39.9, lon, lat)[2]
                assert actual_m == pytest.approx(radius_m, rel=0.001)

    def test_multi_ring_basic(self):
        _setup("pt", _MULTI_RING)
        r = spatial_multi_ring_buffer.invoke({"layer_name": "pt", "distances": "100,200", "unit": "m"})
        assert "多环缓冲区" in r
        assert "2" in r

    @pytest.mark.parametrize("dissolve", [False, True])
    def test_outer_ring_excludes_the_area_inside_the_previous_distance(self, dissolve):
        from shapely.geometry import Point, shape
        _setup("pt", _MULTI_RING)
        result = spatial_multi_ring_buffer.invoke({"layer_name": "pt", "distances": "100,200", "unit": "m", "dissolve": dissolve})
        assert result.startswith("已为")
        outer_ring = shape(_pending_layers[-1]["geojson"]["features"][1]["geometry"])
        center = Point(116.4, 39.9)
        assert not outer_ring.contains(center), "第二环应排除第一环覆盖的内区"

    def test_rings_keep_input_order_when_distances_are_descending(self):
        from shapely.geometry import Point, shape
        _setup("pt", _MULTI_RING)
        result = spatial_multi_ring_buffer.invoke({"layer_name": "pt", "distances": "200,100", "unit": "m"})
        assert result.startswith("已为")
        features = _pending_layers[-1]["geojson"]["features"]
        assert [feature["properties"]["distance"] for feature in features] == [200, 100]
        assert not shape(features[0]["geometry"]).contains(Point(116.4, 39.9))
        assert shape(features[1]["geometry"]).contains(Point(116.4, 39.9))

    def test_duplicate_ring_distances_are_rejected_without_replacing_output(self):
        _setup("pt", _MULTI_RING)
        _setup("pt_多环m", _SQUARE_A)
        previous = _registered_layers["pt_多环m"]["geojson"]
        result = spatial_multi_ring_buffer.invoke({"layer_name": "pt", "distances": "100,100", "unit": "m"})
        assert result == "多环缓冲区失败: 距离不能重复，否则会生成重复环带"
        assert _registered_layers["pt_多环m"]["geojson"] == previous



class TestMoveFeatures:
    @pytest.mark.parametrize("coordinates,expected", [
        ([[179.9, 10.0], [-179.9, 10.0]], "跨越日期变更线"),
        ([[0.0, 85.0]], "超出 UTM 投影适用纬度"),
        ([[-20.0, 0.0], [20.0, 0.0]], "超过 6° 经度"),
        ([[999.0, 30.0]], "超出 WGS84 经纬度范围"),
        ([[0.0, -91.0]], "超出 WGS84 经纬度范围"),
    ])
    def test_move_rejects_extents_outside_local_utm_domain_without_mutating(self, coordinates, expected):
        points = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": index},
             "geometry": {"type": "Point", "coordinates": coordinate}}
            for index, coordinate in enumerate(coordinates)
        ]}
        _setup("edge_points", points)
        before = json.loads(json.dumps(_registered_layers["edge_points"]["geojson"]))

        result = move_features.invoke({"layer_name": "edge_points", "dx": 100, "dy": 0, "unit": "m"})

        assert result.startswith("移动要素失败:")
        assert expected in result
        assert _registered_layers["edge_points"]["geojson"] == before
        assert not _pending_layers

    def test_move_basic_m(self):
        _setup("pts", _POINTS)
        r = move_features.invoke({"layer_name": "pts", "dx": 100, "dy": 100, "unit": "m"})
        assert "已移动" in r
        assert "pts" in r
        assert "3" in r

    def test_move_km_result_reports_requested_distance_not_internal_meters(self):
        _setup("km_point", {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
        }]})

        result = move_features.invoke({"layer_name": "km_point", "dx": 1, "dy": 0, "unit": "km"})
        coordinates = _registered_layers["km_point"]["geojson"]["features"][0]["geometry"]["coordinates"]
        from pyproj import Geod
        distance_m = Geod(ellps="WGS84").inv(116.4, 39.9, *coordinates)[2]

        assert "（1.0km, 0.0km）" in result
        assert "1000km" not in result
        assert distance_m == pytest.approx(1000, abs=1)








class TestRotateFeatures:
    def test_rotate_basic(self):
        _setup("rpt", _POINTS)
        r = rotate_features.invoke({"layer_name": "rpt", "angle": 90})
        assert "已旋转" in r
        assert "rpt" in r
        assert "3" in r






class TestScaleFeatures:
    def test_scale_enlarge(self):
        _setup("sc", _POINTS)
        r = scale_features.invoke({"layer_name": "sc", "x_factor": 2, "y_factor": 2})
        assert "已缩放" in r
        assert "sc" in r
        assert "3" in r





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










class TestEditVertices:
    def setup_method(self):
        T.reset_state()
        _setup("test_polygon", _SQUARE_A)

    def test_edit_vertices_basic(self):
        r = edit_vertices.invoke({"layer_name": "test_polygon"})
        assert "已为" in r or "启用" in r



class TestExportMap:
    def setup_method(self):
        T.reset_state()

    def test_export_png(self):
        r = export_map.invoke({"format": "png"})
        assert "已触发" in r or "导出" in r
        assert T._pending_layer_ops[-1]["format"] == "png"

    def test_export_jpeg_alias_normalizes_to_jpg(self):
        export_map.invoke({"format": "jpeg"})
        assert T._pending_layer_ops[-1]["format"] == "jpg"

    def test_export_rejects_unsupported_format(self):
        r = export_map.invoke({"format": "webp"})
        assert "不支持" in r
        assert T._pending_layer_ops == []



class TestExportPdf:
    def setup_method(self):
        T.reset_state()

    def test_export_pdf_default(self):
        r = export_pdf.invoke({"title": "测试地图"})
        assert "已触发" in r or "PDF" in r
        assert T._pending_layer_ops[-1]["rotation_degrees"] == 0

    def test_export_pdf_rotation(self):
        export_pdf.invoke({"title": "旋转地图", "rotation_degrees": 30})
        op = T._pending_layer_ops[-1]
        assert op["title"] == "旋转地图"
        assert op["rotation_degrees"] == 30



class TestUndoRedo:
    def setup_method(self):
        T.reset_state()

    def test_undo(self):
        r = undo_cmd.invoke({})
        assert "撤销" in r



class TestSnapping:
    def setup_method(self):
        T.reset_state()

    def test_enable_snapping(self):
        r = enable_snapping.invoke({"enabled": True})
        assert "启用" in r



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

    def _make_ramp_tif(self, name, rows=40, cols=40, scale=10):
        """高程随行号(向南)递增的斜平面，用于验证像素→地理坐标的南北方向"""
        import numpy as np
        from rasterio.transform import from_bounds
        import rasterio
        dem = (np.arange(rows, dtype=np.float64).reshape(-1, 1) * np.ones((1, cols))) * scale
        transform = from_bounds(116, 39, 117, 40, cols, rows)  # north=40 在 row 0
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, f"{name}.tif")
        with rasterio.open(dest, 'w', driver='GTiff', height=rows, width=cols, count=1,
                           dtype='float64', crs=None, transform=transform) as dst:
            dst.write(dem, 1)
        return dest

    def test_contour_registers_usable_layer(self):
        """回归：等高线图层必须带 geojson 注册，否则前端不渲染、后续工具报"图层为空"。"""
        self._make_dem_tif("c1")
        r = extract_contours.invoke({"layer_name": "c1"})
        assert "等高线" in r, r
        info = T._registered_layers.get("c1_contour")
        assert info is not None and info.get("geojson", {}).get("features"), "注册表缺少 geojson"
        gdf, msg = T._layer_to_gdf("c1_contour")
        assert gdf is not None and len(gdf) > 0, f"后续工具无法读取等高线图层: {msg}"
        assert "geojson" in T._pending_layers[-1], "待推送图层缺 geojson（前端不会渲染）"

    def test_contour_orientation_north_up(self):
        """回归：高程随行号(向南)递增时，等高线纬度应随高程升高而降低（北在上）。"""
        import numpy as np
        self._make_ramp_tif("ramp")
        r = extract_contours.invoke({"layer_name": "ramp"})
        assert "等高线" in r, r
        feats = T._registered_layers["ramp_contour"]["geojson"]["features"]
        assert len(feats) >= 3
        elev, lat = [], []
        for f in feats:
            coords = f["geometry"]["coordinates"]
            elev.append(f["properties"]["elevation"])
            lat.append(sum(c[1] for c in coords) / len(coords))
        elev, lat = np.array(elev), np.array(lat)
        assert lat.min() > 38.9 and lat.max() < 40.1
        assert np.corrcoef(elev, lat)[0, 1] < 0, "南北方向映射反了（高程升高却纬度也升高）"

    def test_contour_coords_within_bounds(self):
        self._make_dem_tif("c2")
        extract_contours.invoke({"layer_name": "c2"})
        feats = T._registered_layers["c2_contour"]["geojson"]["features"]
        assert feats
        for f in feats:
            for x, y in f["geometry"]["coordinates"]:
                assert 115.9 < x < 117.1 and 38.9 < y < 40.1




class TestNDVI:
    def setup_method(self):
        T.reset_state()

    def test_ndvi_no_file(self):
        r = ndvi_analysis.invoke({"layer_name": "nonexistent"})
        assert "未找到" in r or "请先上传" in r




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

    def test_calc_marks_division_by_zero_pixels_as_nodata(self):
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        input_path = os.path.join(upload_dir, "calc_nonfinite.tif")
        band1 = np.arange(1, 401, dtype=np.float32).reshape(20, 20)
        band2 = np.full((20, 20), 2, dtype=np.float32)
        band2[0, 0] = 0
        with rasterio.open(input_path, "w", driver="GTiff", width=20, height=20, count=2,
                           dtype="float32", crs="EPSG:4326",
                           transform=from_bounds(116, 39, 117, 40, 20, 20)) as dst:
            dst.write(band1, 1)
            dst.write(band2, 2)

        result = raster_calculator.invoke({"layer_name": "calc_nonfinite", "expression": "B1/B2"})

        assert "结果栅格" in result
        op = next(op for op in T._pending_layer_ops if op.get("raster"))
        output_path = T._find_uploaded_tif(op["layer_name"])
        with rasterio.open(output_path) as dataset:
            values = dataset.read(1)
            assert np.isnan(values[0, 0])
            assert np.isfinite(values[1:, :]).all()
            assert np.isnan(dataset.nodata)
        from PIL import Image
        preview_path = os.path.join(upload_dir, op["raster"]["filename"])
        preview = np.asarray(Image.open(preview_path).convert("RGB"))
        assert np.array_equal(preview[0, 0], [0, 0, 0])

    @pytest.mark.parametrize("width,height,count", [(3000, 2000, 1), (2000, 1000, 9)])
    def test_calc_rejects_oversized_raster_before_reading_band_arrays(self, monkeypatch, width, height, count):
        import rasterio
        read_called = False

        class MetadataOnlyDataset:
            nodata = None

            def __init__(self):
                self.width, self.height, self.count = width, height, count

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args, **_kwargs):
                nonlocal read_called
                read_called = True
                raise AssertionError("oversized raster data should not be read")

            def tags(self):
                return {}

        monkeypatch.setattr(T, "_find_uploaded_tif", lambda _name: "metadata-only.tif")
        monkeypatch.setattr(rasterio, "open", lambda *_args, **_kwargs: MetadataOnlyDataset())

        result = raster_calculator.invoke({"layer_name": "large", "expression": "B1*2"})

        assert "超过单次处理上限" in result
        assert read_called is False
        assert T._pending_layer_ops == []





class TestInterpolate:
    def setup_method(self):
        T.reset_state(), _register_layer("pts", _POINTS)

    def test_interpolate_basic(self):
        r = spatial_interpolate.invoke({"layer_name": "pts", "field": "id", "method": "idw"})
        assert "插值" in r or "生成" in r

    def test_interpolate_keeps_values_aligned_when_geometry_is_missing(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"v": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {"v": 2}, "geometry": None},
            {"type": "Feature", "properties": {"v": 3}, "geometry": {"type": "Point", "coordinates": [1, 0]}},
            {"type": "Feature", "properties": {"v": 4}, "geometry": {"type": "Point", "coordinates": [0, 1]}},
        ]}
        _register_layer("mixed_points", fc)

        result = spatial_interpolate.invoke({"layer_name": "mixed_points", "field": "v", "resolution": 16})

        assert "已生成" in result

    def test_interpolate_supports_declared_multipoint_input(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"v": 1}, "geometry": {"type": "MultiPoint", "coordinates": [[0, 0], [1, 0]]}},
            {"type": "Feature", "properties": {"v": 3}, "geometry": {"type": "Point", "coordinates": [0, 1]}},
            {"type": "Feature", "properties": {"v": 4}, "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]}
        _register_layer("multipoints", fc)

        result = spatial_interpolate.invoke({"layer_name": "multipoints", "field": "v", "resolution": 16})

        assert "已生成" in result

    def test_interpolate_uses_metric_distances_at_high_latitudes(self, monkeypatch):
        import numpy as np
        from scipy.spatial import distance
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"v": 1}, "geometry": {"type": "Point", "coordinates": [3.0, 60.0]}},
            {"type": "Feature", "properties": {"v": 3}, "geometry": {"type": "Point", "coordinates": [3.1, 60.0]}},
            {"type": "Feature", "properties": {"v": 4}, "geometry": {"type": "Point", "coordinates": [3.0, 60.1]}},
        ]}
        _register_layer("high_latitude", fc)
        original_cdist = distance.cdist
        captured = {}

        def capture_cdist(grid, points):
            captured["points"] = points.copy()
            return original_cdist(grid, points)

        monkeypatch.setattr(distance, "cdist", capture_cdist)
        result = spatial_interpolate.invoke({"layer_name": "high_latitude", "field": "v", "resolution": 8})

        assert "已生成" in result
        delta_m = np.linalg.norm(captured["points"][0] - captured["points"][1])
        assert 5_000 < delta_m < 6_000

    @pytest.mark.parametrize("resolution", [1, 1025])
    def test_interpolate_rejects_resolution_outside_supported_bounds(self, resolution):
        result = spatial_interpolate.invoke({
            "layer_name": "pts", "field": "id", "resolution": resolution,
        })

        assert "resolution" in result
        assert T._pending_layer_ops == []

    def test_interpolate_rejects_extent_wider_than_local_projection_limit(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"v": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {"v": 3}, "geometry": {"type": "Point", "coordinates": [4, 1]}},
            {"type": "Feature", "properties": {"v": 4}, "geometry": {"type": "Point", "coordinates": [8, 2]}},
        ]}
        _register_layer("wide_points", fc)

        result = spatial_interpolate.invoke({"layer_name": "wide_points", "field": "v", "resolution": 16})

        assert "超过 6° 经度" in result
        assert T._pending_layer_ops == []

    def test_interpolate_rejects_pairwise_work_above_budget_before_grid_allocation(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"v": i + 1},
             "geometry": {"type": "Point", "coordinates": [116 + i * 0.001, 39 + (i % 3) * 0.001]}}
            for i in range(50)
        ]}
        _register_layer("many_points", fc)

        result = spatial_interpolate.invoke({
            "layer_name": "many_points", "field": "v", "resolution": 1024,
        })

        assert "超过单次上限" in result
        assert T._pending_layer_ops == []

    def test_interpolate_batches_idw_distance_matrix(self, monkeypatch):
        from scipy.spatial import distance
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"v": i + 1},
             "geometry": {"type": "Point", "coordinates": [116 + (i % 10) * 0.001, 39 + (i // 10) * 0.001]}}
            for i in range(100)
        ]}
        _register_layer("batch_points", fc)
        original_cdist = distance.cdist
        pair_counts = []

        def capture_cdist(grid, points):
            pair_counts.append(len(grid) * len(points))
            return original_cdist(grid, points)

        monkeypatch.setattr(distance, "cdist", capture_cdist)
        result = spatial_interpolate.invoke({"layer_name": "batch_points", "field": "v", "resolution": 200})

        assert "已生成" in result
        assert len(pair_counts) > 1
        assert max(pair_counts) <= 1_000_000

    def test_interpolate_rbf_batches_grid_evaluation(self):
        result = spatial_interpolate.invoke({
            "layer_name": "pts", "field": "id", "method": "rbf", "resolution": 16,
        })

        assert "已生成" in result

    def test_interpolate_rejects_large_rbf_samples_before_fitting(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"v": i + 1},
             "geometry": {"type": "Point", "coordinates": [116 + (i % 25) * 0.001, 39 + (i // 25) * 0.001]}}
            for i in range(501)
        ]}
        _register_layer("rbf_many_points", fc)

        result = spatial_interpolate.invoke({
            "layer_name": "rbf_many_points", "field": "v", "method": "rbf", "resolution": 16,
        })

        assert "RBF 最多支持 500 个有效点" in result
        assert T._pending_layer_ops == []





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
                           count=1, dtype='float64', crs='EPSG:4326',
                           transform=transform) as dst:
            dst.write(dem, 1)
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, f"{name}.tif")
        shutil.copy(tmp.name, dest)
        os.unlink(tmp.name)
        return dest

    def test_hydro_flowdir(self):
        import uuid
        source_name = f"hydro_fd_{uuid.uuid4().hex[:8]}"
        dest = self._make_dem_tif(source_name)
        r = hydrology_analysis.invoke({"layer_name": source_name, "analysis": "flowdir"})
        assert "流向" in r and "可继续分析" in r
        flowdir_name = f"{source_name}_flowdir"
        assert flowdir_name in _registered_layers
        raster_info = _registered_layers[flowdir_name]["raster"]
        assert raster_info["source_layer"] == source_name
        assert "D8 raster-neighbor code" in raster_info["value_units"]
        assert raster_info["crs"] == "EPSG:4326"
        assert "未经外部水文基准验证" in " ".join(raster_info["quality_warnings"])
        assert len(T._pending_layer_ops) == 1
        assert T._pending_layer_ops[0]["raster"]["source_url"].endswith(flowdir_name + ".tif")

        import rasterio
        with rasterio.open(os.path.join(T._temp_output_dir, "uploads", flowdir_name + ".tif")) as result:
            assert result.crs.to_string() == "EPSG:4326"
            assert result.shape == (30, 30)
            assert result.nodata is not None
            assert "PROCESSING" in result.tags()

        follow_on = raster_reclassify.invoke({
            "layer_name": flowdir_name, "method": "quantile", "classes": 3,
        })
        assert isinstance(follow_on, str)
        assert f"{flowdir_name}_重分类" in _registered_layers

        for analysis in ("flowacc", "streamnet"):
            result = hydrology_analysis.invoke({
                "layer_name": source_name, "analysis": analysis,
            })
            assert "可继续分析" in result
            assert f"{source_name}_{analysis}" in _registered_layers
        os.unlink(dest)

    def test_hydro_flowdir_uses_geographic_ground_distance(self):
        import numpy as np
        import rasterio
        import uuid
        from rasterio.transform import from_bounds

        source_name = f"hydro_distance_case_{uuid.uuid4().hex[:8]}"
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, source_name + ".tif")
        dem = np.array([
            [100, 92, 100],
            [100, 100, 94],
            [100, 100, 100],
        ], dtype=np.float32)
        with rasterio.open(
            dest, "w", driver="GTiff", height=3, width=3, count=1,
            dtype="float32", crs="EPSG:4326",
            transform=from_bounds(0, 58, 3, 61, 3, 3),
        ) as src:
            src.write(dem, 1)

        result = hydrology_analysis.invoke({
            "layer_name": source_name, "analysis": "flowdir",
        })

        assert "已生成水文分析图层" in result
        with rasterio.open(os.path.join(upload_dir, source_name + "_flowdir.tif")) as output:
            # At 59.5°N, a one-degree east step is shorter than a one-degree north step.
            # The 6 m east drop is therefore steeper than the 8 m north drop.
            assert output.read(1)[1, 1] == 0  # D8 code 0 = east
        os.unlink(dest)

    def test_hydrology_rejects_raster_without_crs(self):
        import numpy as np
        import rasterio
        import uuid
        from rasterio.transform import from_bounds

        source_name = f"hydro_no_crs_{uuid.uuid4().hex[:8]}"
        upload_dir = os.path.join(T._temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, source_name + ".tif")
        with rasterio.open(
            dest, "w", driver="GTiff", height=3, width=3, count=1,
            dtype="float32", transform=from_bounds(0, 0, 3, 3, 3, 3),
        ) as src:
            src.write(np.arange(9, dtype=np.float32).reshape(3, 3), 1)

        result = hydrology_analysis.invoke({
            "layer_name": source_name, "analysis": "flowdir",
        })

        assert "要求输入 GeoTIFF 带有有效 CRS" in result
        assert T._pending_layer_ops == []
        assert f"{source_name}_flowdir" not in _registered_layers
        os.unlink(dest)





class TestWorkflow:
    def setup_method(self):
        T.reset_state()

    def test_workflow_bad_json(self):
        r = create_workflow.invoke({"workflow_json": "not json"})
        assert "失败" in r or "错误" in r





class TestTimeAnimation:
    def setup_method(self):
        T.reset_state()

    def test_animate_time(self):
        _register_layer("anim_pts", _POINTS)
        r = animate_time.invoke({"layer_name": "anim_pts", "time_field": "id", "interval_ms": 300})
        assert "动画" in r or "启动" in r



class TestChartLink:
    def setup_method(self):
        T.reset_state()

    def test_chart_link(self):
        _register_layer("cl_pts", _POINTS)
        r = link_chart_map.invoke({"layer_name": "cl_pts", "chart_field": "id"})
        assert "图表联动" in r or "建立" in r



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





# ============================================================
# 沙箱安全测试（E1 加固验证）
# ============================================================

class TestSandboxSecurity:
    """验证 execute_python 沙箱的 AST 检查是否正确拦截内省逃逸"""

    def test_bans_type_direct(self):
        from backend.services.tools import _ast_sandbox_check
        r = _ast_sandbox_check("x = type(1)")
        assert r is not None and "内置类型" in r

    def test_bans_object_direct(self):
        from backend.services.tools import _ast_sandbox_check
        r = _ast_sandbox_check("x = object()")
        assert r is not None and "内置类型" in r

    def test_bans_super_direct(self):
        from backend.services.tools import _ast_sandbox_check
        r = _ast_sandbox_check("class A:\n  def f(self): return super()")
        assert r is not None and "内置类型" in r

    def test_rejects_network_imports_and_points_to_gis_tools(self):
        from backend.services.tools import _ast_sandbox_check
        from backend.services import tools as gis_tools
        assert "禁止导入库「requests」" in _ast_sandbox_check("import requests")
        assert "禁止导入库「urllib.request」" in _ast_sandbox_check("import urllib.request")
        result = gis_tools.execute_python.invoke({"code": "import requests"})
        assert "请勿通过更换导入方式" in result
        assert "专用 GIS 工具" in result














# ============================================================
# execute_python matplotlib PNG 生成测试
# ============================================================

class TestMatplotlibPNG:
    """验证 execute_python 能真正执行 matplotlib 并产出 PNG"""

    def setup_method(self):
        reset_state()
        T.init_temp_dir()

    def test_savefig_with_output_prefix(self):
        """系统提示词告诉 Agent 用 plt.savefig('output/chart.png')，必须能成功"""
        code = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots()\n"
            "ax.plot([1, 2, 3], [1, 4, 9])\n"
            "fig.savefig('output/chart.png', dpi=72)\n"
            "plt.close(fig)\n"
            "print('saved')\n"
        )
        result = T.execute_python.invoke({"code": code})
        assert "执行成功" in result or "图片" in result
        assert len(T._pending_images) > 0
        item = T._pending_images[-1]
        assert item["type"] == "png"
        url = item["url"]
        assert url.startswith("/output/")
        fname = url.split("/output/", 1)[1]
        fpath = os.path.join(T._temp_output_dir, fname)
        assert os.path.exists(fpath), f"PNG file not found: {fpath}"
        assert os.path.getsize(fpath) > 0


def test_utm_crs_boundary():
    """验证经度在 180°/-180° 极值边界时的 UTM 投影计算不会越界超 60 带"""
    crs_180_pos = T._get_utm_crs(180.0, 39.9)
    assert crs_180_pos == "EPSG:32660"
    crs_180_neg = T._get_utm_crs(-180.0, -39.9)
    assert crs_180_neg == "EPSG:32701"


def test_layer_control_rename_sync():
    """验证 layer_control rename 能正确同步更新后端注册图层名"""
    reset_state()
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
            "properties": {"name": "北京点"}
        }]
    }
    _register_layer("原测试图层", fc)
    assert "原测试图层" in _registered_layers

    res = T.layer_control.invoke({"action": "rename", "name": "原测试图层", "new_name": "新测试图层"})
    assert "已重命名图层" in res
    assert "新测试图层" in _registered_layers
    assert "原测试图层" not in _registered_layers



