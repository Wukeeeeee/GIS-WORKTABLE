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
        output_path = T._find_uploaded_tif("zero_values_转栅格")
        assert output_path and os.path.isfile(output_path)
        with rasterio.open(output_path) as raster:
            data = raster.read(1)
            assert math.isnan(raster.nodata)
            assert data[0, 0] == 0
            assert math.isnan(data[0, 1])
            assert raster.crs.to_string() == "EPSG:4326"

        resampled = T.raster_resample.invoke({
            "layer_name": "zero_values_转栅格", "scale_factor": 0.5, "method": "nearest",
        })
        assert "重采样完成" in resampled
        resampled_path = T._find_uploaded_tif("zero_values_转栅格_重采样")
        with rasterio.open(resampled_path) as raster:
            data = raster.read(1)
            assert math.isnan(raster.nodata)
            assert (data == 0).any()
            assert np.isnan(data).any()

        reprojected = T.raster_reproject.invoke({
            "layer_name": "zero_values_转栅格", "target_crs": "EPSG:3857",
        })
        assert "重投影完成" in reprojected
        reprojected_path = T._find_uploaded_tif("zero_values_转栅格_重投影")
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
        output_path = T._find_uploaded_tif("single_point_转栅格")
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





# ============================================================
# create_heatmap — 热力图
# ============================================================

class TestCreateHeatmap:
    def test_heatmap_basic(self):
        _setup("hm1", _POINTS)
        r = create_heatmap.invoke({"layer_name": "hm1"})
        assert "热力图" in r or "生成" in r





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




# ============================================================
# create_chart — 统计图表
# ============================================================

class TestCreateChart:
    def test_chart_bar(self):
        _setup("ch1", _POINTS)
        r = create_chart.invoke({"layer_name": "ch1", "chart_type": "bar", "field": "val"})
        assert "图表" in r or "生成" in r


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


