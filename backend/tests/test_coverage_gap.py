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

    def test_calc_int_type(self):
        _setup("poly2", _MULTI_POLY)
        r = field_calculate.invoke({"layer_name": "poly2", "expression": "val + 5", "new_field": "plus5", "field_type": "int"})
        assert "添加" in r
        gj = _registered_layers["poly2"]["geojson"]
        assert "plus5" in gj["features"][0]["properties"]

    def test_calc_nonexistent_layer(self):
        r = field_calculate.invoke({"layer_name": "nope", "expression": "val*2", "new_field": "x"})
        assert "未找到" in r

    def test_calc_bad_expression(self):
        _setup("poly3", _MULTI_POLY)
        r = field_calculate.invoke({"layer_name": "poly3", "expression": "undefined_field + 1", "new_field": "x"})
        assert "失败" in r or "错误" in r


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

    def test_set_style(self):
        _setup("lc2", _SQUARE)
        r = layer_control.invoke({"action": "set_style", "name": "lc2", "color": "#00ff00", "opacity": 0.7, "weight": 3})
        assert "修改图层样式" in r
        assert _pending_layer_ops[0]["action"] == "set_style"
        assert _pending_layer_ops[0]["style"]["opacity"] == 0.7
        assert _pending_layer_ops[0]["style"]["weight"] == 3

    def test_set_fill_pattern(self):
        _setup("lc3", _SQUARE)
        r = layer_control.invoke({"action": "set_style", "name": "lc3", "color": "#000", "fill_pattern": "hatch"})
        assert "填充图案" in r
        assert _pending_layer_ops[0]["style"]["fillPattern"] == "hatch"

    def test_toggle(self):
        _setup("lc4", _SQUARE)
        r = layer_control.invoke({"action": "toggle", "name": "lc4"})
        assert "切换图层显隐" in r

    def test_remove(self):
        _setup("lc5", _SQUARE)
        r = layer_control.invoke({"action": "remove", "name": "lc5"})
        assert "移除" in r

    def test_rename(self):
        _setup("lc6", _SQUARE)
        r = layer_control.invoke({"action": "rename", "name": "lc6", "new_name": "新名称"})
        assert "重命名" in r

    def test_fit(self):
        _setup("lc7", _SQUARE)
        r = layer_control.invoke({"action": "fit", "name": "lc7"})
        assert "缩放" in r

    def test_bad_action(self):
        r = layer_control.invoke({"action": "nonexist"})
        assert "未知" in r


# ============================================================
# measure_distance — 测距
# ============================================================

class TestMeasureDistance:
    def test_distance_known(self):
        r = measure_distance.invoke({"lon1": 116.4, "lat1": 39.9, "lon2": 116.5, "lat2": 39.9})
        assert "距离" in r
        assert "米" in r or "公里" in r

    def test_distance_same_point(self):
        r = measure_distance.invoke({"lon1": 116.4, "lat1": 39.9, "lon2": 116.4, "lat2": 39.9})
        assert "0" in r or "距离" in r

    def test_distance_short(self):
        r = measure_distance.invoke({"lon1": 0, "lat1": 0, "lon2": 0.001, "lat2": 0})
        assert "米" in r


# ============================================================
# measure_area — 面积测量
# ============================================================

class TestMeasureArea:
    def test_area_polygon(self):
        _setup("ma1", _SQUARE)
        r = measure_area.invoke({"layer_name": "ma1"})
        assert "面积" in r or "平方公里" in r

    def test_area_multi_poly(self):
        _setup("ma2", _MULTI_POLY)
        r = measure_area.invoke({"layer_name": "ma2"})
        assert "面积" in r

    def test_area_nonexistent(self):
        r = measure_area.invoke({"layer_name": "nope"})
        assert "未找到" in r

    def test_area_points(self):
        _setup("ma3", _POINTS)
        r = measure_area.invoke({"layer_name": "ma3"})
        assert "面积" in r or "要素数" in r


# ============================================================
# create_heatmap — 热力图
# ============================================================

class TestCreateHeatmap:
    def test_heatmap_basic(self):
        _setup("hm1", _POINTS)
        r = create_heatmap.invoke({"layer_name": "hm1"})
        assert "热力图" in r or "生成" in r

    def test_heatmap_with_weight(self):
        _setup("hm2", _POINTS)
        r = create_heatmap.invoke({"layer_name": "hm2", "weight_field": "val", "radius": 30})
        assert "热力图" in r

    def test_heatmap_nonexistent(self):
        r = create_heatmap.invoke({"layer_name": "nope"})
        assert "未找到" in r

    def test_heatmap_no_points(self):
        _setup("hm3", _SQUARE)
        r = create_heatmap.invoke({"layer_name": "hm3"})
        assert "没有点要素" in r


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

    def test_export_csv_xy(self):
        _setup("ex2", _POINTS)
        r = export_layer.invoke({"layer_name": "ex2", "format": "csv_xy"})
        assert "CSV" in r
        assert "含坐标" in r

    def test_export_gpkg(self):
        _setup("ex3", _POINTS)
        r = export_layer.invoke({"layer_name": "ex3", "format": "gpkg"})
        assert "GeoPackage" in r

    def test_export_geojson(self):
        _setup("ex4", _POINTS)
        r = export_layer.invoke({"layer_name": "ex4", "format": "geojson"})
        assert "GeoJSON" in r

    def test_export_bad_format(self):
        _setup("ex5", _POINTS)
        r = export_layer.invoke({"layer_name": "ex5", "format": "xls"})
        assert "不支持的格式" in r

    def test_export_nonexistent(self):
        r = export_layer.invoke({"layer_name": "nope", "format": "csv"})
        assert "未找到" in r


# ============================================================
# clear_layers — 清空图层
# ============================================================

class TestClearLayers:
    def test_clear_with_layers(self):
        _setup("cl1", _POINTS)
        _setup("cl2", _SQUARE)
        r = clear_layers.invoke({})
        assert "清空" in r
        assert "2" in r
        assert len(_registered_layers) == 0

    def test_clear_empty(self):
        r = clear_layers.invoke({})
        assert "清空" in r or "0" in r


# ============================================================
# save_file — 保存文件
# ============================================================

class TestSaveFile:
    def test_save_plain_text(self):
        r = save_file.invoke({"filename": "test.txt", "content": "Hello World"})
        assert "已保存" in r

    def test_save_geojson(self):
        r = save_file.invoke({"filename": "test_out.geojson", "content": json.dumps(_POINTS, ensure_ascii=False)})
        assert "已保存" in r
        # GeoJSON 应自动注册
        assert "test_out" in _registered_layers

    def test_save_geojson_registered(self):
        # save_file 对 GeoJSON 会自动调用 _register_layer
        r = save_file.invoke({"filename": "auto_load.geojson", "content": json.dumps(_SQUARE, ensure_ascii=False)})
        assert "已保存" in r
        names = [n for n in _registered_layers.keys() if "auto_load" in n]
        assert len(names) > 0


# ============================================================
# create_chart — 统计图表
# ============================================================

class TestCreateChart:
    def test_chart_bar(self):
        _setup("ch1", _POINTS)
        r = create_chart.invoke({"layer_name": "ch1", "chart_type": "bar", "field": "val"})
        assert "图表" in r or "生成" in r

    def test_chart_pie(self):
        _setup("ch2", _POINTS)
        r = create_chart.invoke({"layer_name": "ch2", "chart_type": "pie", "field": "val"})
        assert "图表" in r

    def test_chart_nonexistent(self):
        r = create_chart.invoke({"layer_name": "nope"})
        assert "未找到" in r

    def test_chart_no_features(self):
        empty = {"type": "FeatureCollection", "features": []}
        _setup("empty", empty)
        r = create_chart.invoke({"layer_name": "empty"})
        assert "没有要素" in r or "空" in r