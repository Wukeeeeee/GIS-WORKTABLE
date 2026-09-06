# -*- coding: utf-8 -*-
"""阶段 C：分析报告生成 + 数据质量检查工具测试"""
import pytest
from backend.services.tools import (
    generate_analysis_report, spatial_fix_geometry, spatial_check_duplicates,
    _register_layer, _registered_layers, _pending_images, reset_state,
)


# 含无效几何（自相交多边形）+ 重复要素的测试数据
_POLY = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"val": 1.5, "name": "A"},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}},
        {"type": "Feature", "properties": {"val": 2.5, "name": "B"},
         "geometry": {"type": "Polygon", "coordinates": [[[3, 0], [5, 0], [5, 2], [3, 2], [3, 0]]]}},
        # 重复要素（几何与 #1 相同）
        {"type": "Feature", "properties": {"val": 1.5, "name": "A_dup"},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}},
        # 自相交多边形（bowtie，无效几何）
        {"type": "Feature", "properties": {"val": 3.5, "name": "C"},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}},
    ],
}

_GOOD_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"v": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {"type": "Feature", "properties": {"v": 2}, "geometry": {"type": "Point", "coordinates": [1, 1]}},
        {"type": "Feature", "properties": {"v": 3}, "geometry": {"type": "Point", "coordinates": [2, 2]}},
    ],
}


@pytest.fixture(autouse=True)
def _clean():
    reset_state()
    _registered_layers.clear()
    _pending_images.clear()
    yield
    reset_state()
    _registered_layers.clear()
    _pending_images.clear()


def _setup(name, geojson):
    _register_layer(name, geojson)
    return name


# ============================================================
# generate_analysis_report — 分析报告
# ============================================================

class TestGenerateReport:
    def test_basic_report(self):
        _setup("poly", _POLY)
        r = generate_analysis_report.invoke({"layer_name": "poly", "analysis_summary": "测试多边形图层分析"})
        assert "分析报告" in r
        assert "测试多边形图层分析" in r
        assert "统计" in r







# ============================================================
# spatial_fix_geometry — 几何修复
# ============================================================

class TestFixGeometry:
    def test_fix_invalid_polygon(self):
        _setup("poly", _POLY)
        r = spatial_fix_geometry.invoke({"layer_name": "poly"})
        assert "修复完成" in r
        assert "已修复" in r
        # 结果图层存在
        result_names = [n for n in _registered_layers if "修复" in n]
        assert len(result_names) >= 1





# ============================================================
# spatial_check_duplicates — 重复检测
# ============================================================

class TestCheckDuplicates:
    def test_geometry_duplicates_found(self):
        _setup("poly", _POLY)
        r = spatial_check_duplicates.invoke({"layer_name": "poly"})
        assert "重复" in r
        result_names = [n for n in _registered_layers if "重复" in n]
        assert len(result_names) >= 1




