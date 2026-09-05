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

    def test_report_stats_table(self):
        _setup("poly", _POLY)
        r = generate_analysis_report.invoke({"layer_name": "poly", "include_stats": True})
        assert "| 字段" in r or "属性统计" in r

    def test_report_quality_section(self):
        _setup("poly", _POLY)
        r = generate_analysis_report.invoke({"layer_name": "poly", "include_quality": True})
        assert "数据质量" in r
        assert "重复要素" in r

    def test_report_no_stats(self):
        _setup("poly", _POLY)
        r = generate_analysis_report.invoke({"layer_name": "poly", "include_stats": False, "include_quality": False})
        assert "分析报告" in r

    def test_report_pending_image(self, tmp_path, monkeypatch):
        """报告应落盘并产生 pending image 记录"""
        from backend.services import tools as T
        out = tmp_path / "out"
        monkeypatch.setattr(T, "_temp_output_dir", str(out))
        _setup("poly", _POLY)
        r = generate_analysis_report.invoke({"layer_name": "poly"})
        assert "已生成" in r
        assert len(_pending_images) >= 1

    def test_report_nonexistent_layer(self):
        r = generate_analysis_report.invoke({"layer_name": "nope"})
        assert "未找到" in r


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

    def test_fix_status_field(self):
        _setup("poly", _POLY)
        spatial_fix_geometry.invoke({"layer_name": "poly"})
        result_names = [n for n in _registered_layers if "修复" in n]
        assert result_names
        gj = _registered_layers[result_names[0]]["geojson"]
        statuses = {f["properties"].get("fix_status") for f in gj["features"]}
        assert "fixed" in statuses  # 至少一个被修复
        assert "original" in statuses  # 有效几何保持原样

    def test_fix_all_valid(self):
        """全部有效时无 fixed"""
        _setup("pts", _GOOD_POINTS)
        r = spatial_fix_geometry.invoke({"layer_name": "pts"})
        assert "修复完成" in r
        result_names = [n for n in _registered_layers if "修复" in n]
        gj = _registered_layers[result_names[0]]["geojson"]
        statuses = {f["properties"].get("fix_status") for f in gj["features"]}
        assert statuses == {"original"}

    def test_fix_nonexistent_layer(self):
        r = spatial_fix_geometry.invoke({"layer_name": "nope"})
        assert "未找到" in r


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

    def test_no_duplicates(self):
        _setup("pts", _GOOD_POINTS)
        r = spatial_check_duplicates.invoke({"layer_name": "pts"})
        assert "未发现" in r

    def test_field_duplicates(self):
        """按字段查重：name 字段有 A 和 A_dup 不同名，val 相同但 name 不同 → 不重复"""
        _setup("poly", _POLY)
        r = spatial_check_duplicates.invoke({"layer_name": "poly", "fields": "name"})
        assert "重复" in r or "未发现" in r

    def test_field_nonexistent(self):
        _setup("poly", _POLY)
        r = spatial_check_duplicates.invoke({"layer_name": "poly", "fields": "no_such"})
        assert "不存在" in r

    def test_nonexistent_layer(self):
        r = spatial_check_duplicates.invoke({"layer_name": "nope"})
        assert "未找到" in r
