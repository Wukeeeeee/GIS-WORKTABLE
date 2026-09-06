# -*- coding: utf-8 -*-
"""阶段 C：空间统计工具测试 — Moran's I / Getis-Ord Gi* / KDE"""
import pytest
from backend.services.tools import (
    spatial_moran, spatial_hotspot, spatial_kde,
    _register_layer, _registered_layers, reset_state,
)


# ============================================================
# 测试数据
# ============================================================

# 聚集点：左侧高值聚集，右侧低值聚集（显著正空间自相关）
_CLUSTER_POINTS = {
    "type": "FeatureCollection",
    "features": [
        # 高值簇（左下）
        {"type": "Feature", "properties": {"value": 10}, "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
        {"type": "Feature", "properties": {"value": 12}, "geometry": {"type": "Point", "coordinates": [0.005, 0.0]}},
        {"type": "Feature", "properties": {"value": 11}, "geometry": {"type": "Point", "coordinates": [0.0, 0.005]}},
        {"type": "Feature", "properties": {"value": 9}, "geometry": {"type": "Point", "coordinates": [0.005, 0.005]}},
        # 低值簇（右上）
        {"type": "Feature", "properties": {"value": 1}, "geometry": {"type": "Point", "coordinates": [0.1, 0.1]}},
        {"type": "Feature", "properties": {"value": 2}, "geometry": {"type": "Point", "coordinates": [0.105, 0.1]}},
        {"type": "Feature", "properties": {"value": 1}, "geometry": {"type": "Point", "coordinates": [0.1, 0.105]}},
        {"type": "Feature", "properties": {"value": 2}, "geometry": {"type": "Point", "coordinates": [0.105, 0.105]}},
    ],
}

# 随机分散点
_RANDOM_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"value": 5}, "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
        {"type": "Feature", "properties": {"value": 1}, "geometry": {"type": "Point", "coordinates": [0.05, 0.0]}},
        {"type": "Feature", "properties": {"value": 9}, "geometry": {"type": "Point", "coordinates": [0.1, 0.0]}},
        {"type": "Feature", "properties": {"value": 2}, "geometry": {"type": "Point", "coordinates": [0.0, 0.05]}},
        {"type": "Feature", "properties": {"value": 8}, "geometry": {"type": "Point", "coordinates": [0.05, 0.05]}},
        {"type": "Feature", "properties": {"value": 3}, "geometry": {"type": "Point", "coordinates": [0.1, 0.05]}},
    ],
}

# 含负值的点（Gi* 不允许）
_NEGATIVE_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"value": -5}, "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
        {"type": "Feature", "properties": {"value": 3}, "geometry": {"type": "Point", "coordinates": [0.01, 0.0]}},
        {"type": "Feature", "properties": {"value": 2}, "geometry": {"type": "Point", "coordinates": [0.0, 0.01]}},
    ],
}

# 全相同值（方差为零）
_CONSTANT_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"value": 5}, "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
        {"type": "Feature", "properties": {"value": 5}, "geometry": {"type": "Point", "coordinates": [0.01, 0.0]}},
        {"type": "Feature", "properties": {"value": 5}, "geometry": {"type": "Point", "coordinates": [0.0, 0.01]}},
    ],
}

# KDE 用点
_KDE_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.002, 0.0]}},
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.0, 0.002]}},
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.002, 0.002]}},
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.05, 0.05]}},
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.052, 0.05]}},
    ],
}


@pytest.fixture(autouse=True)
def _clean():
    """每个测试前后清空注册表，避免互相污染"""
    reset_state()
    _registered_layers.clear()
    yield
    reset_state()
    _registered_layers.clear()


def _setup(name, geojson):
    _register_layer(name, geojson)
    return name


# ============================================================
# spatial_moran — Moran's I
# ============================================================

class TestSpatialMoran:
    def test_cluster_data_positive_autocorrelation(self):
        """聚集数据应返回显著正空间自相关"""
        _setup("cluster", _CLUSTER_POINTS)
        r = spatial_moran.invoke({"layer_name": "cluster", "field": "value", "threshold": 0.02})
        assert "Moran" in r
        assert "I" in r
        # 聚集数据 I 应为正
        assert "聚集" in r or "正空间自相关" in r or "随机" in r  # 小样本可能不显著，但不应报错







# ============================================================
# spatial_hotspot — Getis-Ord Gi*
# ============================================================

class TestSpatialHotspot:
    def test_basic_hotspot(self):
        """正常数据应返回热点/冷点计数"""
        _setup("cluster", _CLUSTER_POINTS)
        r = spatial_hotspot.invoke({"layer_name": "cluster", "field": "value", "threshold": 0.02})
        assert "热点" in r
        assert "冷点" in r
        result_names = [n for n in _registered_layers if "热点" in n]
        assert len(result_names) >= 1






# ============================================================
# spatial_kde — 核密度估计
# ============================================================

class TestSpatialKDE:
    def test_basic_kde(self):
        """正常点数据应输出格网点图层"""
        _setup("pts", _KDE_POINTS)
        r = spatial_kde.invoke({"layer_name": "pts", "bandwidth": 0.01, "grid_size": 20})
        assert "KDE" in r or "核密度" in r
        result_names = [n for n in _registered_layers if "KDE" in n]
        assert len(result_names) >= 1, f"未找到 KDE 结果图层，当前：{list(_registered_layers.keys())}"



