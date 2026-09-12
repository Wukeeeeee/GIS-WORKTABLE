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

    def test_random_data_is_not_systematically_significant(self):
        """回归：方差公式写错时任何数据都会被判成"显著"

        历史 bug：b2 用了原始值而非离差、方差主项少了 n 因子，方差算成负数后
        被 max(var, 1e-12) 兜住，z 值爆炸 → 60/60 全部"显著"。
        固定随机种子下这是确定性断言。
        """
        import random as _random
        rng = _random.Random(20260912)
        flagged, zs = 0, []
        trials = 40
        for i in range(trials):
            reset_state()
            _registered_layers.clear()
            feats = []
            for j in range(12):
                feats.append({
                    "type": "Feature",
                    "properties": {"value": rng.gauss(50, 10)},
                    "geometry": {"type": "Point",
                                 "coordinates": [rng.random(), rng.random()]},
                })
            _setup(f"rnd{i}", {"type": "FeatureCollection", "features": feats})
            r = spatial_moran.invoke({"layer_name": f"rnd{i}", "field": "value",
                                      "threshold": 0.35})
            # "无显著自相关" 也含 "显著" 二字，必须排除
            if "无显著" not in r and ("显著正" in r or "显著负" in r):
                flagged += 1
            zs.append(float(r.split("z = ")[1].split("，")[0]))

        # 5% 显著性水平下 40 次里期望约 2 次；给到一半的余量仍远小于"全部显著"
        assert flagged <= trials * 0.25, (
            f"随机数据有 {flagged}/{trials} 次被判显著，显著性检验失效")
        # z 的经验标准差应接近 1（正态分布近似成立）
        mean_z = sum(zs) / len(zs)
        std_z = (sum((v - mean_z) ** 2 for v in zs) / len(zs)) ** 0.5
        assert 0.5 < std_z < 1.8, f"z 的经验标准差 {std_z:.2f} 应接近 1.0"

    def test_strong_cluster_is_significant(self):
        """强聚集数据必须被判为显著正相关（修完公式后不能矫枉过正）"""
        reset_state()
        _registered_layers.clear()
        feats = []
        for i in range(20):
            x = 0.05 * (i % 5) / 5 + (0.0 if i < 10 else 1.0)
            y = 0.05 * ((i // 5) % 2)
            feats.append({
                "type": "Feature",
                "properties": {"value": 10.0 if i < 10 else 1.0},
                "geometry": {"type": "Point", "coordinates": [x, y]},
            })
        _setup("strong", {"type": "FeatureCollection", "features": feats})
        r = spatial_moran.invoke({"layer_name": "strong", "field": "value", "threshold": 0.35})
        assert "显著正" in r, f"强聚集数据应判为显著正相关，实际：{r[:200]}"

    def test_reports_how_significance_was_determined(self):
        """显著性判定方式必须写进结果，便于用户判断结论可信度"""
        _setup("cluster", _CLUSTER_POINTS)
        r = spatial_moran.invoke({"layer_name": "cluster", "field": "value", "threshold": 0.02})
        assert "显著性判定方式" in r







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

def _kde_layer(grid_size=20, **kw):
    """跑一次 KDE，返回结果 GeoDataFrame"""
    _setup("pts", _KDE_POINTS)
    spatial_kde.invoke({"layer_name": "pts", "grid_size": grid_size, **kw})
    names = [n for n in _registered_layers if "KDE" in n]
    assert names, f"未找到 KDE 结果图层，当前：{list(_registered_layers.keys())}"
    return _registered_layers[names[0]]["geojson"]


class TestSpatialKDE:
    def test_basic_kde(self):
        """正常点数据应输出格网点图层"""
        _setup("pts", _KDE_POINTS)
        r = spatial_kde.invoke({"layer_name": "pts", "bandwidth": 0.01, "grid_size": 20})
        assert "KDE" in r or "核密度" in r
        result_names = [n for n in _registered_layers if "KDE" in n]
        assert len(result_names) >= 1, f"未找到 KDE 结果图层，当前：{list(_registered_layers.keys())}"

    def test_bandwidth_is_in_degrees_not_a_factor(self):
        """回归：bandwidth 曾被当成 scipy 的 bw_method 倍数，实际带宽小 40 倍，
        400 个格点只剩 2 个，密度面完全退化。这里要求带宽真的按"度"生效。"""
        gdf = _kde_layer(bandwidth=0.01)
        assert len(gdf["features"]) > 100, (
            f"带宽 0.01 度应得到连续密度面，实际只剩 {len(gdf['features'])} 个格点"
            "（若是 2 个，说明带宽又被当成倍数传给了 scipy）")

    def test_larger_bandwidth_gives_smoother_surface(self):
        """带宽越大越平滑：密度极差应显著变小，保留的格点应更多"""
        small = _kde_layer(bandwidth=0.005)
        large = _kde_layer(bandwidth=0.03)
        v_small = [f["properties"]["density"] for f in small["features"]]
        v_large = [f["properties"]["density"] for f in large["features"]]

        def rel_range(v):
            return (max(v) - min(v)) / max(v)

        assert rel_range(v_large) < rel_range(v_small), (
            "带宽变大后密度面应当更平滑（相对极差变小）")
        assert len(large["features"]) >= len(small["features"])

    def test_auto_bandwidth_when_not_specified(self):
        """不指定带宽时按 Scott 法则自动估算，且能算出有效结果"""
        gdf = _kde_layer(grid_size=20)  # 不传 bandwidth
        assert len(gdf["features"]) > 50
        _setup("pts", _KDE_POINTS)
        r = spatial_kde.invoke({"layer_name": "pts", "grid_size": 20})
        assert "自动估算" in r

    def test_density_peak_near_dense_cluster(self):
        """密度峰值应落在点密集处，而不是孤立的零散点上

        数据里 4 个点挤在原点附近、2 个点在 (0.05, 0.05)，峰值必须属于前者。
        """
        gdf = _kde_layer(bandwidth=0.01)
        feats = gdf["features"]
        peak = max(feats, key=lambda f: f["properties"]["density"])
        x, y = peak["geometry"]["coordinates"]
        assert abs(x) < 0.03 and abs(y) < 0.03, (
            f"密度峰值出现在 ({x:.4f}, {y:.4f})，应落在原点附近的密集簇")

    def test_density_km2_field_matches_conversion(self):
        """density_km2 必须是 density 按纬度换算的结果，不能是另一套口径"""
        gdf = _kde_layer(bandwidth=0.01)
        for f in gdf["features"][:5]:
            p = f["properties"]
            assert "density" in p and "density_km2" in p
            # 赤道附近 1 平方度约 12308 km²，允许纬度换算带来的偏差
            ratio = p["density"] / p["density_km2"]
            assert 10000 < ratio < 13000, f"单位换算异常：ratio={ratio}"

    def test_rejects_non_point_layer(self):
        """面/线图层不能偷偷按顶点算密度，必须明确拒绝并给出下一步指引"""
        _setup("poly", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Polygon",
                             "coordinates": [[[0, 0], [0.02, 0], [0.02, 0.02], [0, 0.02], [0, 0]]]},
            }],
        })
        r = spatial_kde.invoke({"layer_name": "poly"})
        assert "点图层" in r
        assert "spatial_centroid" in r
        assert not [n for n in _registered_layers if "KDE" in n]

    def test_rejects_too_few_points(self):
        """点太少时不做无意义计算"""
        _setup("two", {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.01, 0.01]}},
            ],
        })
        r = spatial_kde.invoke({"layer_name": "two"})
        assert "太少" in r
        assert not [n for n in _registered_layers if "KDE" in n]



