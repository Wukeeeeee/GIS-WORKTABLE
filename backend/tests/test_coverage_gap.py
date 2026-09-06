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


