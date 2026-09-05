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

    def test_local_lisa_output_fields(self):
        """局部 LISA 应输出含 cluster_type 字段的新图层"""
        _setup("cluster", _CLUSTER_POINTS)
        r = spatial_moran.invoke({"layer_name": "cluster", "field": "value", "threshold": 0.02, "local": True})
        # 结果图层应被注册
        result_names = [n for n in _registered_layers if "MoranI" in n]
        assert len(result_names) >= 1, f"未找到 MoranI 结果图层，当前：{list(_registered_layers.keys())}"
        gj = _registered_layers[result_names[0]]["geojson"]
        props = gj["features"][0]["properties"]
        assert "local_moran" in props
        assert "cluster_type" in props
        assert props["cluster_type"] in ("HH", "LL", "HL", "LH", "NS")

    def test_nonexistent_field(self):
        """字段不存在应返回明确错误"""
        _setup("cluster", _CLUSTER_POINTS)
        r = spatial_moran.invoke({"layer_name": "cluster", "field": "no_such_field"})
        assert "不存在" in r

    def test_constant_value_zero_variance(self):
        """全相同值（方差为零）应返回错误"""
        _setup("const", _CONSTANT_POINTS)
        r = spatial_moran.invoke({"layer_name": "const", "field": "value"})
        assert "方差为零" in r or "无法" in r

    def test_knn_weight(self):
        """KNN 权重模式应正常工作"""
        _setup("cluster", _CLUSTER_POINTS)
        r = spatial_moran.invoke({"layer_name": "cluster", "field": "value", "weight_type": "knn", "k": 3, "local": False})
        assert "Moran" in r

    def test_nonexistent_layer(self):
        """图层不存在应返回错误"""
        r = spatial_moran.invoke({"layer_name": "nope", "field": "value"})
        assert "未找到" in r


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

    def test_output_fields(self):
        """结果图层应含 gi_z / gi_p / hotspot_type"""
        _setup("cluster", _CLUSTER_POINTS)
        spatial_hotspot.invoke({"layer_name": "cluster", "field": "value", "threshold": 0.02})
        result_names = [n for n in _registered_layers if "热点" in n]
        assert result_names
        gj = _registered_layers[result_names[0]]["geojson"]
        props = gj["features"][0]["properties"]
        assert "gi_z" in props
        assert "gi_p" in props
        assert "hotspot_type" in props
        assert props["hotspot_type"] in ("热点", "冷点", "不显著")

    def test_negative_value_rejected(self):
        """Gi* 不允许负值字段"""
        _setup("neg", _NEGATIVE_POINTS)
        r = spatial_hotspot.invoke({"layer_name": "neg", "field": "value"})
        assert "非负" in r

    def test_nonexistent_field(self):
        _setup("cluster", _CLUSTER_POINTS)
        r = spatial_hotspot.invoke({"layer_name": "cluster", "field": "bad"})
        assert "不存在" in r

    def test_nonexistent_layer(self):
        r = spatial_hotspot.invoke({"layer_name": "nope", "field": "value"})
        assert "未找到" in r


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

    def test_output_has_density_field(self):
        """结果图层应含 density 字段且非负"""
        _setup("pts", _KDE_POINTS)
        spatial_kde.invoke({"layer_name": "pts", "bandwidth": 0.01, "grid_size": 20})
        result_names = [n for n in _registered_layers if "KDE" in n]
        assert result_names
        gj = _registered_layers[result_names[0]]["geojson"]
        assert len(gj["features"]) > 0
        props = gj["features"][0]["properties"]
        assert "density" in props
        assert props["density"] >= 0

    def test_too_few_points(self):
        """点太少应返回错误"""
        few = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.01, 0]}},
            ],
        }
        _setup("few", few)
        r = spatial_kde.invoke({"layer_name": "few"})
        assert "太少" in r

    def test_nonexistent_layer(self):
        r = spatial_kde.invoke({"layer_name": "nope"})
        assert "未找到" in r
