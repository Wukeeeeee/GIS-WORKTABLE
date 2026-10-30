"""
补全测试：覆盖 tools.py 中未被 test_spatial_tools.py 测试的工具
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json, shutil, tempfile
import pytest

from backend.services import tools as T
from backend.services.tools import (
    _registered_layers, _pending_layers, _pending_layer_ops,
    _register_layer, reset_state, init_temp_dir,
)

# 导入未测试的工具
field_calculate = T.field_calculate
layer_control = T.layer_control
measure_distance = T.measure_distance
measure_area = T.measure_area
create_heatmap = T.create_heatmap
add_north_arrow = T.add_north_arrow
export_layer = T.export_layer
clear_layers = T.clear_layers
save_file = T.save_file
create_chart = T.create_chart
generate_static_map = T.generate_static_map
feature_to_raster = T.feature_to_raster
create_fishnet = T.create_fishnet


@pytest.fixture(autouse=True)
def cleanup():
    reset_state()
    init_temp_dir()
    yield
    reset_state()


_SQUARE = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "A", "val": 10, "cat": "x"},
        "geometry": {"type": "Polygon", "coordinates": [[[0,0],[2,0],[2,2],[0,2],[0,0]]]}
    }]
}

_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"id": 1, "val": 10.5, "label": "a"},
         "geometry": {"type": "Point", "coordinates": [116.4, 39.9]}},
        {"type": "Feature", "properties": {"id": 2, "val": 20.0, "label": "b"},
         "geometry": {"type": "Point", "coordinates": [116.5, 40.0]}},
        {"type": "Feature", "properties": {"id": 3, "val": 30.0, "label": "c"},
         "geometry": {"type": "Point", "coordinates": [116.45, 39.95]}},
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
        {"type": "Feature", "properties": {"group": "X", "val": 1, "area": 100},
         "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}},
        {"type": "Feature", "properties": {"group": "X", "val": 2, "area": 200},
         "geometry": {"type": "Polygon", "coordinates": [[[0.5,0.5],[1.5,0.5],[1.5,1.5],[0.5,1.5],[0.5,0.5]]]}},
        {"type": "Feature", "properties": {"group": "Y", "val": 3, "area": 300},
         "geometry": {"type": "Polygon", "coordinates": [[[2,0],[3,0],[3,1],[2,1],[2,0]]]}},
    ]
}

_TEMP_DIR = None


def _setup(name, geojson):
    _register_layer(name, geojson)
    return name


# ============================================================
# field_calculate — 字段计算
# ============================================================

class TestFieldCalculate:
    def test_calc_simple_expression(self):
        _setup("poly", _MULTI_POLY)
        r = field_calculate.invoke({"layer_name": "poly", "expression": "val * 2", "new_field": "double", "field_type": "float"})
        assert "添加" in r or "计算" in r
        gj = _registered_layers["poly"]["geojson"]
        props = [f["properties"] for f in gj["features"]]
        assert "double" in props[0]
        assert props[0]["double"] == 2  # val=1 → 2

    def test_calc_refuses_to_overwrite_existing_property_without_mutating_layer(self):
        import copy

        _setup("field_collision", {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"value": 3, "result": "keep-me"},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }]})
        before_layer = copy.deepcopy(_registered_layers["field_collision"])
        before_pending_layers = copy.deepcopy(_pending_layers)
        before_pending_ops = copy.deepcopy(_pending_layer_ops)

        result = field_calculate.invoke({
            "layer_name": "field_collision", "expression": "value * 2", "new_field": "result",
        })

        assert "result" in result and ("已存在" in result or "不能覆盖" in result)
        assert _registered_layers["field_collision"] == before_layer
        assert _pending_layers == before_pending_layers
        assert _pending_layer_ops == before_pending_ops

    def test_calc_preserves_large_integer_properties_when_other_features_are_null(self):
        exact_large_integer = 2**53 + 1
        _setup("field_large_integer_null", {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"value": exact_large_integer},
             "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {"value": None},
             "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]})

        result = field_calculate.invoke({
            "layer_name": "field_large_integer_null", "expression": "value", "new_field": "copy",
        })

        assert "已为图层" in result
        features = _registered_layers["field_large_integer_null"]["geojson"]["features"]
        assert features[0]["properties"]["value"] == exact_large_integer
        assert features[1]["properties"]["value"] is None
        assert features[0]["properties"]["copy"] == exact_large_integer

    def test_calc_rejects_unsupported_field_type_without_mutating_layer(self):
        import copy

        _setup("field_invalid_type", {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"value": 3},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }]})
        before_layer = copy.deepcopy(_registered_layers["field_invalid_type"])
        before_pending_layers = copy.deepcopy(_pending_layers)
        before_pending_ops = copy.deepcopy(_pending_layer_ops)

        result = field_calculate.invoke({
            "layer_name": "field_invalid_type", "expression": "value * 2",
            "new_field": "result", "field_type": "currency",
        })

        assert "currency" in result and ("不支持" in result or "仅支持" in result)
        assert _registered_layers["field_invalid_type"] == before_layer
        assert _pending_layers == before_pending_layers
        assert _pending_layer_ops == before_pending_ops

    @pytest.mark.parametrize(("field_type", "canonical_type"), [
        ("string", "str"), ("integer", "int"), ("number", "float"),
    ])
    def test_calc_normalizes_supported_field_type_aliases(self, field_type, canonical_type):
        layer_name = f"field_type_alias_{canonical_type}"
        _setup(layer_name, {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"value": 3},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }]})

        result = field_calculate.invoke({
            "layer_name": layer_name, "expression": "value", "new_field": "copy",
            "field_type": field_type,
        })

        assert f"（{canonical_type}，" in result

    def test_calc_rejects_unconvertible_integer_value_without_mutating_layer(self):
        import copy

        _setup("field_unconvertible_integer", {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"value": "not-a-number"},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }]})
        before_layer = copy.deepcopy(_registered_layers["field_unconvertible_integer"])
        before_pending_layers = copy.deepcopy(_pending_layers)
        before_pending_ops = copy.deepcopy(_pending_layer_ops)

        result = field_calculate.invoke({
            "layer_name": "field_unconvertible_integer", "expression": "value",
            "new_field": "as_int", "field_type": "int",
        })

        assert "字段类型转换失败" in result
        assert _registered_layers["field_unconvertible_integer"] == before_layer
        assert _pending_layers == before_pending_layers
        assert _pending_layer_ops == before_pending_ops

    def test_calc_converts_numeric_string_to_float(self):
        _setup("field_numeric_string", {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"value": "3.5"},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }]})

        result = field_calculate.invoke({
            "layer_name": "field_numeric_string", "expression": "value",
            "new_field": "as_float", "field_type": "float",
        })

        assert "已为图层" in result
        value = _registered_layers["field_numeric_string"]["geojson"]["features"][0]["properties"]["as_float"]
        assert value == pytest.approx(3.5)
        assert isinstance(value, float)

    def test_missing_input_values_stay_null_instead_of_becoming_zero(self):
        _setup("field_null_input", {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"value": 4},
             "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {"value": None},
             "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]})

        result = field_calculate.invoke({
            "layer_name": "field_null_input", "expression": "value * 2", "new_field": "double",
        })

        assert "已为图层" in result
        values = [feature["properties"]["double"] for feature in _registered_layers["field_null_input"]["geojson"]["features"]]
        assert values == [8, None]

    def test_string_output_preserves_missing_values(self):
        _setup("field_string_null", {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"value": 4},
             "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {"value": None},
             "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]})

        result = field_calculate.invoke({
            "layer_name": "field_string_null", "expression": "value", "new_field": "copy",
            "field_type": "str",
        })

        assert "已为图层" in result
        values = [feature["properties"]["copy"] for feature in _registered_layers["field_string_null"]["geojson"]["features"]]
        assert values == ["4", None]

    def test_cannot_overwrite_stable_feature_id(self):
        _setup("field_fid", _POINTS)
        before = [feature["properties"]["_fid"] for feature in _registered_layers["field_fid"]["geojson"]["features"]]

        result = field_calculate.invoke({
            "layer_name": "field_fid", "expression": "val", "new_field": "_fid",
        })

        after = [feature["properties"]["_fid"] for feature in _registered_layers["field_fid"]["geojson"]["features"]]
        assert "_fid" in result and "不能覆盖" in result
        assert after == before





# ============================================================
# layer_control — 图层控制（样式、显隐、重命名、移除等）
# ============================================================

class TestLayerControl:
    def test_set_color(self):
        _setup("lc1", _SQUARE)
        r = layer_control.invoke({"action": "set_color", "name": "lc1", "color": "#ff0000"})
        assert "修改图层颜色" in r
        assert len(_pending_layer_ops) == 1
        assert _pending_layer_ops[0]["action"] == "set_color"

    def test_clear_symbology(self):
        _setup("lc1", _SQUARE)
        r = layer_control.invoke({"action": "clear_symbology", "name": "lc1"})
        assert "清除" in r
        assert _pending_layer_ops == [{"action": "clear_symbology", "name": "lc1"}]









# ============================================================
# measure_distance — 测距
# ============================================================

class TestMeasureDistance:
    def test_distance_known(self):
        r = measure_distance.invoke({"lon1": 116.4, "lat1": 39.9, "lon2": 116.5, "lat2": 39.9})
        assert "距离" in r
        assert "米" in r or "公里" in r

    @pytest.mark.parametrize("coords", [
        (181, 0, 0, 0), (0, -91, 0, 0), (0, 0, 0, 91),
        (float("nan"), 0, 0, 0), (0, 0, float("inf"), 0),
    ])
    def test_rejects_coordinates_outside_wgs84_bounds(self, coords):
        result = measure_distance.invoke(dict(zip(("lon1", "lat1", "lon2", "lat2"), coords)))

        assert "坐标" in result and "范围" in result




# ============================================================
# measure_area — 面积测量
# ============================================================

class TestMeasureArea:
    def test_area_polygon(self):
        _setup("ma1", _SQUARE)
        r = measure_area.invoke({"layer_name": "ma1"})
        assert "面积" in r or "平方公里" in r

    def test_wide_extent_uses_ellipsoidal_area_instead_of_one_utm_zone(self):
        from pyproj import Geod

        coordinates = [[-20, 10], [20, 10], [20, 60], [-20, 60], [-20, 10]]
        geojson = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        }]}
        _setup("wide_area", geojson)

        result = measure_area.invoke({"layer_name": "wide_area"})

        expected_m2, _ = Geod(ellps="WGS84").polygon_area_perimeter(
            [point[0] for point in coordinates], [point[1] for point in coordinates],
        )
        expected_km2 = abs(expected_m2) / 1_000_000
        reported_km2 = float(result.split("- 面积：", 1)[1].split(" 平方公里", 1)[0])
        assert reported_km2 == pytest.approx(expected_km2, abs=0.01)
        assert "WGS-84 椭球大地面积" in result


class TestFeatureToRaster:
    def test_zero_attribute_values_remain_valid_and_output_is_reusable(self, tmp_path, monkeypatch):
        import math
        import numpy as np
        import rasterio

        monkeypatch.setattr(T, "_temp_output_dir", str(tmp_path))
        geojson = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"value": 0},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] }},
            {"type": "Feature", "properties": {"value": None},
             "geometry": {"type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]] }},
        ]}
        _setup("zero_values", geojson)

        result = feature_to_raster.invoke({
            "layer_name": "zero_values", "value_field": "value", "cell_size": 1,
        })

        assert "已烧录 1 个像元" in result
        rasterized_name = _pending_layer_ops[-1]["layer_name"]
        output_path = T._find_uploaded_tif(rasterized_name)
        assert output_path and os.path.isfile(output_path)
        with rasterio.open(output_path) as raster:
            data = raster.read(1)
            assert math.isnan(raster.nodata)
            assert data[0, 0] == 0
            assert math.isnan(data[0, 1])
            assert raster.crs.to_string() == "EPSG:4326"

        resampled = T.raster_resample.invoke({
            "layer_name": rasterized_name, "scale_factor": 0.5, "method": "nearest",
        })
        assert "重采样完成" in resampled
        resampled_path = T._find_uploaded_tif(_pending_layer_ops[-1]["layer_name"])
        with rasterio.open(resampled_path) as raster:
            data = raster.read(1)
            assert math.isnan(raster.nodata)
            assert (data == 0).any()
            assert np.isnan(data).any()

        reprojected = T.raster_reproject.invoke({
            "layer_name": rasterized_name, "target_crs": "EPSG:3857",
        })
        assert "重投影完成" in reprojected
        reprojected_path = T._find_uploaded_tif(_pending_layer_ops[-1]["layer_name"])
        with rasterio.open(reprojected_path) as raster:
            data = raster.read(1)
            assert math.isnan(raster.nodata)
            assert (data == 0).any()
            assert np.isnan(data).any()

    def test_non_numeric_value_field_returns_actionable_error(self):
        _setup("text_values", _SQUARE)

        result = feature_to_raster.invoke({
            "layer_name": "text_values", "value_field": "cat", "cell_size": 1,
        })

        assert "含非数值属性" in result

    def test_single_point_with_explicit_cell_size_gets_valid_pixel_grid(self, tmp_path, monkeypatch):
        import rasterio

        monkeypatch.setattr(T, "_temp_output_dir", str(tmp_path))
        _setup("single_point", {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
        }]})

        result = feature_to_raster.invoke({"layer_name": "single_point", "cell_size": 0.01})

        assert "矢量转栅格完成" in result, result
        output_path = T._find_uploaded_tif(_pending_layer_ops[-1]["layer_name"])
        with rasterio.open(output_path) as raster:
            assert raster.shape == (1, 1)
            assert raster.res == pytest.approx((0.01, 0.01))
            assert raster.transform * (0.5, 0.5) == pytest.approx((116.4, 39.9))
            assert raster.read(1)[0, 0] == 1

    def test_explicit_cell_size_cannot_allocate_unbounded_grid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(T, "_temp_output_dir", str(tmp_path))
        _setup("large_grid", _SQUARE)

        result = feature_to_raster.invoke({
            "layer_name": "large_grid", "cell_size": 0.0001,
        })

        assert "超过单次处理上限（400 万像元）" in result
        assert T._find_uploaded_tif("large_grid_转栅格") is None

    def test_negative_cell_size_is_rejected(self):
        _setup("bad_cell_size", _SQUARE)

        result = feature_to_raster.invoke({
            "layer_name": "bad_cell_size", "cell_size": -1,
        })

        assert "cell_size 必须是有限的非负数" in result


class TestCreateFishnet:
    def test_rejects_unbounded_grid_before_building_features(self):
        _setup("fishnet_extent", _SQUARE)

        result = create_fishnet.invoke({
            "extent_layer": "fishnet_extent", "rows": 101, "cols": 100,
        })

        assert "超过单次处理上限（10000 格）" in result
        assert "fishnet" not in T._registered_layers

    def test_rejects_negative_cell_size_even_if_rows_are_given(self):
        _setup("fishnet_bad_cell", _SQUARE)

        result = create_fishnet.invoke({
            "extent_layer": "fishnet_bad_cell", "cell_size": -1, "rows": 2, "cols": 2,
        })

        assert "cell_size 必须是有限的非负数" in result

    def test_reports_actual_cell_size_after_ceil(self):
        _setup("fishnet_small", _SQUARE)

        result = create_fishnet.invoke({
            "extent_layer": "fishnet_small", "cell_size": 0.6, "out_name": "fishnet_small_result",
        })

        assert "4 行 x 4 列 = 16 格" in result
        assert "格尺寸 0.5 x 0.5" in result

    def test_preserves_previous_result_when_output_name_repeats(self):
        _setup("fishnet_repeat_extent", _SQUARE)

        first = create_fishnet.invoke({
            "extent_layer": "fishnet_repeat_extent", "rows": 2, "cols": 2,
            "out_name": "fishnet_repeat",
        })
        second = create_fishnet.invoke({
            "extent_layer": "fishnet_repeat_extent", "rows": 4, "cols": 4,
            "out_name": "fishnet_repeat",
        })

        assert "图层「fishnet_repeat」已加载到地图" in first
        assert "图层「fishnet_repeat_1」已加载到地图" in second
        assert len(T._registered_layers["fishnet_repeat"]["geojson"]["features"]) == 4
        assert len(T._registered_layers["fishnet_repeat_1"]["geojson"]["features"]) == 16





# ============================================================
# create_heatmap — 热力图
# ============================================================

class TestCreateHeatmap:
    def test_heatmap_basic(self):
        _setup("hm1", _POINTS)
        r = create_heatmap.invoke({"layer_name": "hm1"})
        assert "热力图" in r or "生成" in r

    def test_requested_missing_weight_field_is_not_silently_ignored(self):
        _setup("hm_missing_weight", _POINTS)

        result = create_heatmap.invoke({
            "layer_name": "hm_missing_weight", "weight_field": "typo_weight",
        })

        assert "权重字段" in result and "不存在" in result
        assert T._pending_heatmap["latest"] is None





# ============================================================
# add_north_arrow — 指北针
# ============================================================

class TestAddNorthArrow:
    def test_north_arrow(self):
        r = add_north_arrow.invoke({})
        assert "指北针" in r
        assert len(_pending_layer_ops) == 1
        assert _pending_layer_ops[0]["action"] == "north_arrow"


# ============================================================
# export_layer — 图层导出（csv/csv_xy/gpkg 格式）
# ============================================================

class TestExportLayer:
    def test_csv_xy_export_does_not_overwrite_same_named_source_fields(self, tmp_path, monkeypatch):
        import csv
        import re

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))
        geojson = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {"longitude": "source lon", "latitude": "source lat"},
            "geometry": {"type": "Point", "coordinates": [113.5, 23.1]},
        }]}
        _setup("csv_xy_collision", geojson)

        result = export_layer.invoke({"layer_name": "csv_xy_collision", "format": "csv_xy"})
        filename = re.search(r"/output/([^\s]+\.csv)", result).group(1)
        with (output_dir / filename).open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))

        assert row["longitude"] == "source lon"
        assert row["latitude"] == "source lat"
        assert row["geometry_longitude"] == "113.5"
        assert row["geometry_latitude"] == "23.1"

    @pytest.mark.parametrize("export_format", ["csv", "csv_xy", "gpkg", "shp"])
    def test_export_preserves_unsafe_integer_when_other_rows_are_null(self, tmp_path, monkeypatch, export_format):
        import csv
        import re
        import geopandas as gpd
        import pandas as pd

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))
        geojson = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"code": 9007199254740993},
             "geometry": {"type": "Point", "coordinates": [0, 0]}},
            {"type": "Feature", "properties": {"code": None},
             "geometry": {"type": "Point", "coordinates": [1, 1]}},
        ]}
        _setup("large_integer_csv", geojson)

        result = export_layer.invoke({"layer_name": "large_integer_csv", "format": export_format})
        extension = "zip" if export_format == "shp" else ("gpkg" if export_format == "gpkg" else "csv")
        filename = re.search(rf"/output/([^\s]+\.{extension})", result).group(1)
        path = output_dir / filename
        if export_format in {"csv", "csv_xy"}:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                exported = list(csv.DictReader(stream))
            assert exported[0]["code"] == "9007199254740993"
            assert exported[1]["code"] == ""
        else:
            exported = gpd.read_file(f"zip://{path}" if export_format == "shp" else path)
            assert int(exported.iloc[0]["code"]) == 9007199254740993
            assert pd.isna(exported.iloc[1]["code"])

    def test_repeated_exports_with_same_second_do_not_overwrite_prior_download(self, tmp_path, monkeypatch):
        import datetime
        import re

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))
        fixed_time = T.datetime.datetime(2026, 10, 30, 12, 0, 0)

        class FixedDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_time

        monkeypatch.setattr(T.datetime, "datetime", FixedDatetime)
        _setup("same_second_export", _POINTS)

        first_result = export_layer.invoke({"layer_name": "same_second_export", "format": "geojson"})
        first_name = re.search(r"/output/([^\s]+\.geojson)", first_result).group(1)
        first_path = output_dir / first_name
        first_document = json.loads(first_path.read_text(encoding="utf-8"))

        replacement = json.loads(json.dumps(_POINTS))
        replacement["features"][0]["properties"]["id"] = 999
        T._registered_layers["same_second_export"]["geojson"] = replacement
        second_result = export_layer.invoke({"layer_name": "same_second_export", "format": "geojson"})
        second_name = re.search(r"/output/([^\s]+\.geojson)", second_result).group(1)

        assert second_name != first_name
        assert json.loads(first_path.read_text(encoding="utf-8")) == first_document

    def test_export_csv(self):
        _setup("ex1", _POINTS)
        r = export_layer.invoke({"layer_name": "ex1", "format": "csv"})
        assert "CSV" in r
        assert "已生成" in r

    def test_csv_xy_export_rejects_non_point_geometry_with_guidance(self):
        _setup("polygon_csv_xy", _SQUARE)

        result = export_layer.invoke({"layer_name": "polygon_csv_xy", "format": "csv_xy"})

        assert "仅支持 Point 点要素" in result

    @pytest.mark.parametrize("export_format", ["geojson", "shp", "gpkg", "csv", "csv_xy"])
    def test_vector_export_of_raster_layer_returns_clear_unsupported_message(self, export_format):
        T._register_raster_layer("dem_layer", {"bounds": [0, 0, 1, 1]})

        result = export_layer.invoke({"layer_name": "dem_layer", "format": export_format})

        assert "栅格图层" in result and "矢量导出" in result

    def test_shapefile_export_preserves_colliding_truncated_field_names(self):
        import re
        import zipfile
        import geopandas as gpd

        layer = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {"abcdefghijk": "long-name", "abcdefghij": "short-name"},
            "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
        }]}
        _setup("field_collision", layer)

        result = export_layer.invoke({"layer_name": "field_collision", "format": "shp"})
        match = re.search(r"/output/([^\s]+\.zip)", result)
        assert match, result
        archive_path = os.path.join(T._temp_output_dir, match.group(1))
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.testzip() is None
        exported = gpd.read_file(f"zip://{archive_path}")
        assert exported.iloc[0]["abcdefghij"] == "short-name"
        assert exported.iloc[0]["abcdefghi1"] == "long-name"

    def test_geojson_export_keeps_untrusted_layer_name_inside_output_dir(self, tmp_path, monkeypatch):
        import re
        from fastapi.testclient import TestClient
        from backend import main

        output_dir = tmp_path / "nested" / "output"
        output_dir.mkdir(parents=True)
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))
        _setup("../../outside & field", _POINTS)

        result = export_layer.invoke({"layer_name": "../../outside & field", "format": "geojson"})
        match = re.search(
            r"(?:/?)output/[A-Za-z0-9_\-\u4e00-\u9fa5.()（）]+?\.geojson", result
        )
        assert match, result
        assert "outside_field_" in match.group(0)
        filename = match.group(0).split("/output/", 1)[1]
        exported_path = (output_dir / filename).resolve()
        assert exported_path.is_relative_to(output_dir.resolve())
        assert exported_path.is_file()
        monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
        response = TestClient(main.app).get(f"/output/{filename}?download=true")
        assert response.status_code == 200
        assert response.content == exported_path.read_bytes()
        assert "attachment" in response.headers.get("content-disposition", "")

    @pytest.mark.parametrize("export_format", ["geojson", "shp", "gpkg", "csv", "csv_xy"])
    def test_exported_file_is_registered_for_result_guard(self, export_format, tmp_path, monkeypatch):
        import time
        import uuid
        from backend.services import result_guard, storage_service

        monkeypatch.setattr(T, "_temp_output_dir", str(tmp_path))
        monkeypatch.setitem(result_guard._OUTPUT_DIRS, "output", str(tmp_path))
        layer_name = f"export_guard_{export_format}"
        _setup(layer_name, _POINTS)
        run_id = f"run_export_{uuid.uuid4().hex}"
        assert storage_service.record_run_start(run_id, "test-session", f"export {export_format}")
        T.set_current_run(run_id)
        started_at = time.time()

        result = export_layer.invoke({"layer_name": layer_name, "format": export_format})
        check = result_guard.verify_result(result, run_id=run_id, run_start_time=started_at)

        assert check["ok"], check







# ============================================================
# save_file — 保存文件
# ============================================================

class TestSaveFile:
    def test_save_plain_text(self):
        r = save_file.invoke({"filename": "test.txt", "content": "Hello World"})
        assert "已保存" in r

    def test_rejects_output_symlink_that_targets_outside_directory(self, tmp_path, monkeypatch):
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("original", encoding="utf-8")
        link = output_dir / "alias.txt"
        try:
            link.symlink_to(outside_file)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))

        result = save_file.invoke({"filename": "alias.txt", "content": "overwritten"})

        assert "错误" in result
        assert outside_file.read_text(encoding="utf-8") == "original"

    def test_same_second_html_saves_keep_distinct_files(self, tmp_path, monkeypatch):
        import datetime

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))
        fixed_time = datetime.datetime(2026, 10, 30, 12, 0, 0)

        class FixedDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_time

        monkeypatch.setattr(T.datetime, "datetime", FixedDatetime)
        save_file.invoke({"filename": "report.html", "content": "first"})
        save_file.invoke({"filename": "report.html", "content": "second"})
        save_file.invoke({"filename": "report.html", "content": "third"})

        paths = list(output_dir.glob("*report.html"))
        assert len(paths) == 3
        assert {path.read_text(encoding="utf-8") for path in paths} == {"first", "second", "third"}
        assert len({item["url"] for item in T._pending_images}) == 3




# ============================================================
# create_chart — 统计图表
# ============================================================

class TestCreateChart:
    def test_chart_bar(self):
        _setup("ch1", _POINTS)
        r = create_chart.invoke({"layer_name": "ch1", "chart_type": "bar", "field": "val"})
        assert "图表" in r or "生成" in r

    def test_chart_outputs_created_in_same_second_keep_distinct_files(self, tmp_path, monkeypatch):
        import datetime

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))
        fixed_time = T.datetime.datetime(2026, 10, 30, 12, 0, 0)

        class FixedDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_time

        monkeypatch.setattr(T.datetime, "datetime", FixedDatetime)
        _setup("chart_same_second", _POINTS)

        create_chart.invoke({"layer_name": "chart_same_second", "title": "first chart"})
        first_path = next(output_dir.glob("chart_*.html"))
        first_content = first_path.read_text(encoding="utf-8")
        create_chart.invoke({"layer_name": "chart_same_second", "title": "second chart"})
        paths = list(output_dir.glob("chart_*.html"))

        assert len(paths) == 2
        assert first_path.read_text(encoding="utf-8") == first_content

    def test_untrusted_chart_title_and_category_cannot_break_out_of_script(self, tmp_path, monkeypatch):
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))
        payload = "</script><script>window.__chart_injected=true</script><script>"
        geojson = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"label": payload},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }]}
        _setup("chart_injection_layer", geojson)

        result = create_chart.invoke({
            "layer_name": "chart_injection_layer", "chart_type": "bar",
            "field": "label", "title": payload,
        })
        chart_path = next(output_dir.glob("chart_*.html"))
        html = chart_path.read_text(encoding="utf-8")

        assert payload not in html
        assert html.count("</script>") == 2
        assert "&lt;/script&gt;" in html
        assert r"\u003c/script\u003e" in html
        assert "图表已生成" in result


class TestGenerateStaticMap:
    def test_output_name_cannot_escape_chart_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _setup("static_map_path", _POINTS)

        result = generate_static_map.invoke({
            "layer_ids": "static_map_path", "output_name": "../../escaped",
        })

        assert "静态地图已生成" in result
        assert (tmp_path / "cache" / "charts" / "escaped.png").exists()
        assert not (tmp_path / "escaped.png").exists()

    def test_empty_layers_are_not_reported_as_successfully_drawn(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _setup("static_map_empty", {"type": "FeatureCollection", "features": []})

        result = generate_static_map.invoke({"layer_ids": "static_map_empty"})

        assert "没有可绘制的要素" in result
        assert not list((tmp_path / "cache" / "charts").glob("*.png"))

    def test_scale_bar_uses_ground_distance_at_layer_latitude(self, tmp_path, monkeypatch):
        import matplotlib.axes
        from pyproj import Geod

        monkeypatch.chdir(tmp_path)
        _setup("static_map_high_lat", {
            "type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 60]}},
                {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [10, 60]}},
            ],
        })
        observed = {}
        original_plot = matplotlib.axes.Axes.plot
        original_text = matplotlib.axes.Axes.text

        def capture_plot(ax, *args, **kwargs):
            if len(args) >= 2 and len(args[0]) == 2 and len(args[1]) == 2 and args[1][0] == args[1][1]:
                observed["line"] = (list(args[0]), list(args[1]))
            return original_plot(ax, *args, **kwargs)

        def capture_text(ax, x, y, text, *args, **kwargs):
            if isinstance(text, str) and text.endswith(" km"):
                observed["label_km"] = float(text.removesuffix(" km"))
            return original_text(ax, x, y, text, *args, **kwargs)

        monkeypatch.setattr(matplotlib.axes.Axes, "plot", capture_plot)
        monkeypatch.setattr(matplotlib.axes.Axes, "text", capture_text)

        result = generate_static_map.invoke({"layer_ids": "static_map_high_lat", "show_scale_bar": True})

        assert "静态地图已生成" in result
        x_values, y_values = observed["line"]
        expected_km = abs(Geod(ellps="WGS84").inv(x_values[0], y_values[0], x_values[1], y_values[1])[2]) / 1000
        assert observed["label_km"] == round(expected_km)


# ============================================================
# project_service — extract_clean_title
# ============================================================

class TestProjectService:
    def test_extract_clean_title_quoted(self):
        from backend.services.project_service import extract_clean_title
        raw = "[用户引用了上一条回复，请围绕其内容理解下面的问题]\n回复内容\n\n[当前问题]\n帮我把湖南各市GDP做成专题图"
        assert extract_clean_title(raw) == "帮我把湖南各市GDP做成专题图"

    def test_extract_clean_title_attached_layer(self):
        from backend.services.project_service import extract_clean_title
        raw = "[附图层: 广东省各市]\n类型: 面\n\nGeoJSON:\n```json\n{}\n```\n\n请分析广东省"
        assert extract_clean_title(raw) == "请分析广东省"

    def test_extract_clean_title_layer_only(self):
        from backend.services.project_service import extract_clean_title
        raw = "[附图层: 广东省各市]\n类型: 面\n\nGeoJSON:\n```json\n{}\n```"
        assert extract_clean_title(raw) == "广东省各市"

    def test_extract_clean_title_plain(self):
        from backend.services.project_service import extract_clean_title
        raw = "普通提问测试"
        assert extract_clean_title(raw) == "普通提问测试"

    def test_layer_reset_and_isolation(self):
        from backend.services.tools import _register_layer, _registered_layers, reset_registered_layers
        _register_layer("old_layer_1", _POINTS)
        _register_layer("old_layer_2", _SQUARE)
        assert "old_layer_1" in _registered_layers
        assert "old_layer_2" in _registered_layers

        # 重置并载入新工程专属图层
        reset_registered_layers([{"name": "new_proj_layer", "geojson": _POINTS}])
        assert "old_layer_1" not in _registered_layers
        assert "old_layer_2" not in _registered_layers
        assert "new_proj_layer" in _registered_layers


