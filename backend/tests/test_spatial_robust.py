# -*- coding: utf-8 -*-
"""空间健墺性层测试（方法论迁移，非代码复制）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest


# ------------------------------------------------------------
# repair_geometry
# ------------------------------------------------------------
def _gdf(geoms, crs="EPSG:4326"):
    import geopandas as gpd
    return gpd.GeoDataFrame({"id": list(range(len(geoms)))}, geometry=geoms, crs=crs)


def test_repair_bowtie_self_intersection():
    """自相交 bowtie 三角形：buffer(0) 后应变有效，且统计 repaired>=1"""
    from shapely.geometry import Polygon
    from backend.services.spatial_robust import repair_geometry
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])  # 自交
    assert not bowtie.is_valid
    gdf = _gdf([bowtie, Polygon([(5, 5), (6, 5), (6, 6), (5, 5)])])
    out, stats = repair_geometry(gdf)
    assert stats["repaired"] >= 1, stats
    assert out.geometry.is_valid.all(), "修复后仍有无效几何"
    assert len(out) == 2


def test_repair_drops_none_and_empty():
    """None / empty 几何被丢弃，dropped>=2"""
    from shapely.geometry import Polygon, Point
    from backend.services.spatial_robust import repair_geometry
    gdf = _gdf([None, Point(1, 1), Polygon()])
    out, stats = repair_geometry(gdf)
    assert stats["dropped"] >= 2, stats
    assert len(out) == 1


# ------------------------------------------------------------
# estimate_tier
# ------------------------------------------------------------
def test_tier_fast_for_small():
    """100 个小三角形 -> fast"""
    from shapely.geometry import Polygon
    from backend.services.spatial_robust import estimate_tier
    tris = [Polygon([(i * 0.01, 0), (i * 0.01 + 0.01, 0), (i * 0.01 + 0.005, 0.01)]) for i in range(100)]
    t = estimate_tier(_gdf(tris))
    assert t["features"] == 100
    assert t["tier"] == "fast", t


def test_tier_chunked_for_huge_segments():
    """单个 60000 块段的面 -> chunked"""
    from shapely.geometry import Polygon
    from backend.services.spatial_robust import estimate_tier
    ring = [(i * 0.0001, (i % 2) * 0.0001) for i in range(60_001)]
    big = Polygon(ring) if Polygon(ring).is_valid else Polygon([(0, 0), (0.0002, 0), (0.0002, 0.0002), (0, 0.0002)])
    t = estimate_tier(_gdf([big]))
    assert t["segments"] >= 4, t
    # 用一个真的大面（圆）验证
    from shapely.geometry import Point
    circle = Point(0, 0).buffer(0.1, quad_segs=13_000)
    t2 = estimate_tier(_gdf([circle]))
    assert t2["segments"] > 50_000, t2
    assert t2["tier"] == "chunked", t2


def test_tier_feature_threshold():
    """超过 20000 要素 -> chunked（块段很小）"""
    from shapely.geometry import Point
    from backend.services.spatial_robust import estimate_tier
    pts = [Point(i * 0.001, 0) for i in range(20_001)]
    t = estimate_tier(_gdf(pts))
    assert t["tier"] == "chunked", t


# ------------------------------------------------------------
# chunked_overlay
# ------------------------------------------------------------
def test_chunked_overlay_area_matches_ground_truth():
    """两个 10x10 网格，分批交集面积应等于 shapely 真值"""
    import geopandas as gpd
    from shapely.geometry import box
    from shapely.ops import unary_union
    from backend.services.spatial_robust import chunked_overlay

    cells = [box(c * 0.01, r * 0.01, (c + 1) * 0.01, (r + 1) * 0.01)
             for r in range(10) for c in range(10)]
    a = _gdf(cells)
    # b：左上角一块大面（覆盖 5x5 格）
    b_big = box(0, 0.05, 0.05, 0.1)
    b = _gdf([b_big])
    merged, stats = chunked_overlay(a, b, lambda x, y: gpd.overlay(x, y, how="intersection"))
    assert stats["cells"] == 4
    assert stats["ok_cells"] == stats["cells"]
    assert stats["failed_cells"] == 0
    import geopandas as _gpd
    _b_proj = _gpd.GeoDataFrame({"g": [b_big]}, geometry="g", crs=a.crs).to_crs(
        _gpd.GeoDataFrame({"g": [b_big]}, geometry="g", crs=a.crs).estimate_utm_crs())
    got = merged.to_crs(merged.estimate_utm_crs()).geometry.area.sum()
    expected = _b_proj.geometry.area.sum()
    assert abs(got - expected) / expected < 1e-6, (got, expected)
    # 去重：交集后不应有重复几何
    wkb = merged.geometry.apply(lambda g: g.wkb)
    assert not wkb.duplicated().any(), "分批后出现重复要素"


def test_chunked_overlay_all_fail_raises():
    """全部格失败应 raise，不静默返回空"""
    from backend.services.spatial_robust import chunked_overlay
    a = _gdf([__import__("shapely.geometry", fromlist=["box"]).box(0, 0, 0.1, 0.1)])
    b = _gdf([__import__("shapely.geometry", fromlist=["box"]).box(0, 0, 0.1, 0.1)])

    def boom(x, y):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        chunked_overlay(a, b, boom)


def test_chunked_difference_preserves_crossing_feature_once():
    """跨分区的完整要素不能重复输出或漏减另一图层。"""
    import geopandas as gpd
    from shapely.geometry import box
    from backend.services.spatial_robust import chunked_overlay

    outer, cut = box(0, 0, 4, 4), box(1, 1, 3, 3)
    result, _ = chunked_overlay(
        _gdf([outer]), _gdf([cut]),
        lambda a, b: gpd.overlay(a, b, how="difference"),
    )
    assert len(result) == 1
    assert result.geometry.iloc[0].equals(outer.difference(cut))


# ------------------------------------------------------------
# 工具接入验证
# ------------------------------------------------------------
def _mk_layer(name, feats):
    from backend.services import tools as T
    T._register_layer(name, {"type": "FeatureCollection", "features": feats})
    return name


def test_spatial_buffer_repairs_invalid_geometry():
    """含无效几何的图层，缓冲仍能成功，返回含“已自动修复”"""
    from shapely.geometry import Polygon
    from backend.services import tools as T
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    _mk_layer("rb_bad", [
        {"type": "Feature", "properties": {}, "geometry": bowtie.__geo_interface__},
        {"type": "Feature", "properties": {}, "geometry": Polygon([(5, 5), (6, 5), (6, 6), (5, 5)]).__geo_interface__},
    ])
    r = T.spatial_buffer.invoke({"layer_name": "rb_bad", "distance": 100, "unit": "m"})
    assert "缓冲区" in r, r
    assert "已自动修复" in r, r
    assert "失败" not in r.split("已自动修复")[0], r


def test_spatial_intersect_reports_repair():
    """相交工具同样修复并报告"""
    from shapely.geometry import Polygon
    from backend.services import tools as T
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    _mk_layer("ri_a", [{"type": "Feature", "properties": {}, "geometry": bowtie.__geo_interface__}])
    _mk_layer("ri_b", [{"type": "Feature", "properties": {}, "geometry": Polygon([(0, 0), (3, 0), (3, 3), (0, 3), (0, 0)]).__geo_interface__}])
    r = T.spatial_intersect.invoke({"layer_a": "ri_a", "layer_b": "ri_b"})
    assert "相交分析完成" in r, r
    assert "已自动修复" in r, r


def test_chunked_path_reports_batching():
    """大数据触发分批，返回含“分批”"""
    from shapely.geometry import Point
    from backend.services import tools as T
    circle = Point(116, 39).buffer(0.5, quad_segs=13_000)  # >50000 块段
    _mk_layer("rb_big", [{"type": "Feature", "properties": {}, "geometry": circle.__geo_interface__}])
    r = T.spatial_buffer.invoke({"layer_name": "rb_big", "distance": 1000, "unit": "m"})
    assert "分批" in r, r[:300]
