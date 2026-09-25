# -*- coding: utf-8 -*-
"""地理数据质量自检（Geo QA）测试

地理工具最常见的静默错误：CRS 未转换、经纬度颠倒、无效几何、空结果。
qa_check 把它们变成显式警告；本文件验证守卫本身抓得住、也绝不误报正常数据。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

from backend.services import geo_qa
from backend.services.geo_qa import qa_check, bbox_in_range, haversine_m
from backend.services.tools import _push_layer, get_pending_state, reset_state


def _point(lon, lat):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {}}


def _fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


# ============================================================
# 正常数据绝不误报
# ============================================================

def test_clean_points_no_warnings():
    gj = _fc(_point(116.4, 39.9), _point(121.47, 31.23), _point(113.26, 23.13))
    assert qa_check(gj) == []


def test_west_china_no_false_positive():
    """新疆喀什（经度 <90）等正常中国数据不得触发任何警告"""
    gj = _fc(_point(75.99, 39.47), _point(87.62, 43.79))
    assert qa_check(gj) == []


def test_japan_us_no_warnings():
    """国外正常数据（含南半球负纬度）不误报"""
    gj = _fc(_point(139.69, 35.68), _point(-122.42, 37.77), _point(151.2, -33.87))
    assert qa_check(gj) == []


# ============================================================
# 各类地理错误必须抓得住
# ============================================================

def test_out_of_range_detected():
    """纬度 116 → 投影坐标/未转 4326/经纬颠倒类错误"""
    gj = _fc(_point(88.0, 116.4))
    ws = qa_check(gj)
    assert ws and "超出 WGS-84" in ws[0]


def test_swapped_coords_detected():
    """经纬度颠倒（lat 116 放进了纬度位）→ 范围越界被抓"""
    gj = _fc(_point(39.9, 116.4))  # 本应是 [116.4, 39.9]
    ws = qa_check(gj)
    assert ws and "超出 WGS-84" in ws[0]


def test_empty_result_detected():
    ws = qa_check(_fc())
    assert ws and "为空" in ws[0]


def test_invalid_geometry_detected():
    """自相交多边形（bowtie）→ 无效几何警告"""
    bowtie = {"type": "Feature",
              "geometry": {"type": "Polygon", "coordinates": [
                  [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]},
              "properties": {}}
    ws = qa_check(_fc(bowtie))
    assert any("无效几何" in w for w in ws)


def test_degenerate_polygon_detected():
    """面要素只有 2 个点 → 退化警告"""
    degen = {"type": "Feature",
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]},
             "properties": {}}
    ws = qa_check(_fc(degen))
    assert any("退化" in w for w in ws)


def test_invalid_geometry_hint_mentions_fix_tool():
    bowtie = {"type": "Feature",
              "geometry": {"type": "Polygon", "coordinates": [
                  [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]},
              "properties": {}}
    ws = qa_check(_fc(bowtie))
    assert any("spatial_fix_geometry" in w for w in ws)


# ============================================================
# 辅助函数
# ============================================================

def test_bbox_in_range():
    assert bbox_in_range(_fc(_point(116.4, 39.9))) is True
    assert bbox_in_range(_fc(_point(200, 39.9))) is False
    assert bbox_in_range({"type": "FeatureCollection", "features": []}) is True


def test_haversine_known_distance():
    # 北京天安门 → 上海人民广场 约 1067km（允许 ±10km）
    d = haversine_m(116.391, 39.907, 121.474, 31.230)
    assert abs(d - 1_067_000) < 10_000


# ============================================================
# 图层通道集成：警告随 pending 状态返回
# ============================================================

def test_push_layer_collects_qa_warnings():
    reset_state()
    _push_layer("坏层", _fc(_point(88.0, 116.4)))
    st = get_pending_state()
    assert st["qa_warnings"] and st["qa_warnings"][0]["layer"] == "坏层"


def test_push_layer_clean_no_warnings():
    reset_state()
    _push_layer("好层", _fc(_point(116.4, 39.9)))
    assert get_pending_state()["qa_warnings"] == []


def test_qa_never_raises():
    """质量自检永不阻塞出图：各种畸形输入都不抛异常"""
    assert qa_check(None) == []
    assert qa_check({}) == []
    # 无 features 键 = 空 FeatureCollection → 报"为空"是正确行为，不抛异常即可
    assert isinstance(qa_check({"type": "FeatureCollection"}), list)
    assert isinstance(qa_check({"type": "Feature", "geometry": None}), list)
    assert isinstance(qa_check({"type": "Feature", "geometry": {"type": "Point"}}), list)
