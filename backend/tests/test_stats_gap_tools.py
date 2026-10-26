# -*- coding: utf-8 -*-
"""空间统计扩展工具测试  权重矩阵 / 空间回归 / 标准差椭圆 / 中心趋势 / OD 成本矩阵

核心原则：断言"数对不对"，并让"经纬度当米用"这类 bug 无法蒙混过关：
  - 3x3 手搓面网格 queen 邻接必须给出角 3 / 边 5 / 中心 8；
  - 中心趋势的标准距离必须是米级合理值（若用度计算会得到 ~1e-4，直接失败）；
  - y = 2x + 1 的完美线性数据必须还原出系数 2 与 1、R  1；
  - knn 必须在投影坐标上做，否则极区样例会选错邻居。
"""

import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from backend.services import tools as T
from backend.services.tools import (
    tools as TOOL_LIST,
    _registered_layers,
    _register_layer,
    _layer_to_gdf,
    reset_state,
)

NEW_STATS_TOOLS = [
    "spatial_weights_matrix",
    "spatial_regression",
    "directional_distribution",
    "central_tendency",
    "od_cost_matrix",
]

HAVERSINE_R = 6371000.0


def _haversine(p1, p2):
    """独立实现的球面距离（米），用于校验 OD 成本。"""
    lon1, lat1 = math.radians(p1[0]), math.radians(p1[1])
    lon2, lat2 = math.radians(p2[0]), math.radians(p2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return HAVERSINE_R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@pytest.fixture(autouse=True)
def _clean():
    reset_state()
    _registered_layers.clear()
    yield
    reset_state()
    _registered_layers.clear()


def _setup(name, geojson):
    _register_layer(name, geojson)
    return name


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _pt(a, b, **props):
    """构造点要素：a=经度, b=纬度；props 为属性（可含 x/y 字段）。"""
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": [float(a), float(b)]}}


def _summary(text):
    """从返回文本里取 STATS_SUMMARY 的 JSON。"""
    assert "STATS_SUMMARY:" in text, f"缺少机器可读摘要行：{text[:400]}"
    return json.loads(text.split("STATS_SUMMARY:", 1)[1].split("\n", 1)[0])


# ============================================================
# 3x3 面网格（queen 黄金用例）
# ============================================================
def _grid_3x3():
    feats = []
    for r in range(3):
        for c in range(3):
            ring = [[c, r], [c + 1, r], [c + 1, r + 1], [c, r + 1], [c, r]]
            feats.append({
                "type": "Feature",
                "properties": {"cell_id": f"{c}_{r}", "value": float(c + r)},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
    return _fc(feats)


def _weights_result(text):
    payload = _summary(text)
    with open(payload["sidecar"], "r", encoding="utf-8") as fh:
        sidecar = json.load(fh)
    return payload, sidecar


# ============================================================
# 注册 / docstring
# ============================================================
class TestRegistration:
    def test_five_stats_tools_registered(self):
        names = {t.name for t in TOOL_LIST}
        missing = [n for n in NEW_STATS_TOOLS if n not in names]
        assert not missing, f"空间统计工具未注册到 tools 列表：{missing}"

    def test_registry_size_at_least_146(self):
        """131 既有 + 5 栅格 + 5 矢量 + 5 空间统计 = 146"""
        assert len(TOOL_LIST) >= 146, (
            f"注册表只有 {len(TOOL_LIST)} 个工具（<146），说明有 @tool 定义了但忘记注册")

    def test_no_duplicate_registration(self):
        names = [t.name for t in TOOL_LIST]
        dup = sorted({n for n in names if names.count(n) > 1})
        assert not dup, f"tools 列表存在重复项：{dup}"

    @pytest.mark.parametrize("tool_name", NEW_STATS_TOOLS)
    def test_docstring_present_and_lists_params(self, tool_name):
        t = next(x for x in TOOL_LIST if x.name == tool_name)
        doc = t.description or ""
        assert doc.strip(), f"{tool_name} 缺少 docstring"
        required = {
            "spatial_weights_matrix": ["layer_name", "method", "queen", "rook", "knn"],
            "spatial_regression": ["layer_name", "dependent", "independents", "ols", "gwr"],
            "directional_distribution": ["layer_name", "group_field", "weight_field", "std_deviations"],
            "central_tendency": ["layer_name", "weight_field"],
            "od_cost_matrix": ["origins_layer", "destinations_layer", "network_source"],
        }[tool_name]
        for token in required:
            assert token in doc, f"{tool_name} 的 docstring 缺少参数/取值说明：{token}"


# ============================================================
# spatial_weights_matrix
# ============================================================
class TestSpatialWeightsMatrix:
    def test_queen_counts_on_3x3_grid(self):
        """最强不变量：queen 邻接角 3 / 边 5 / 中心 8。"""
        _setup("grid", _grid_3x3())
        payload, sidecar = _weights_result(
            T.spatial_weights_matrix.invoke({"layer_name": "grid", "method": "queen"}))
        assert payload["n_features"] == 9
        counts = sorted(sidecar["neighbor_counts"])
        assert counts == [3, 3, 3, 3, 5, 5, 5, 5, 8], f"queen 邻居数错误：{counts}"
        assert abs(payload["mean_neighbors"] - 40 / 9.0) < 1e-3, payload

    def test_queen_interior_cell_has_all_eight_neighbours(self):
        """中心格 (1,1) 必须正好连到其余 8 格。"""
        _setup("grid", _grid_3x3())
        _, sidecar = _weights_result(
            T.spatial_weights_matrix.invoke({"layer_name": "grid", "method": "queen"}))
        ids = [f["properties"]["cell_id"] for f in _registered_layers["grid"]["geojson"]["features"]]
        center = ids.index("1_1")
        assert len(sidecar["neighbors"][center]) == 8
        assert set(sidecar["neighbors"][center]) == {i for i in range(9) if i != center}
        # 角格只连 3 个，且每个邻居都是边/角格
        corner = ids.index("0_0")
        assert sorted(sidecar["neighbors"][corner]) == sorted(
            [ids.index(v) for v in ("1_0", "0_1", "1_1")])

    def test_rook_counts_on_3x3_grid(self):
        """rook 只认共享边：角 2 / 边 3 / 中心 4。"""
        _setup("grid", _grid_3x3())
        _, sidecar = _weights_result(
            T.spatial_weights_matrix.invoke({"layer_name": "grid", "method": "rook"}))
        counts = sorted(sidecar["neighbor_counts"])
        assert counts == [2, 2, 2, 2, 3, 3, 3, 3, 4], f"rook 邻居数错误：{counts}"

    def test_knn_each_feature_has_k_neighbours(self):
        _setup("grid", _grid_3x3())
        _, sidecar = _weights_result(
            T.spatial_weights_matrix.invoke({"layer_name": "grid", "method": "knn", "k": 8}))
        assert sidecar["neighbor_counts"] == [8] * 9

    def test_knn_uses_projected_coordinates(self):
        """极区样例：按"度"算最近邻会选错，按投影米制才算对。

        A=(0.0, 83.9)，B=(0.001, 83.9) 投影后距 A 约 11.9 m；
        C=(0.0, 83.9005) 在度制上更近（0.0005 < 0.001），但投影米制约 55.8 m。
        k=1 时最近邻必须是 B。
        """
        feats = [_pt(0.0, 83.9, tag="A"), _pt(0.001, 83.9, tag="B"), _pt(0.0, 83.9005, tag="C")]
        _setup("polar", _fc(feats))
        _, sidecar = _weights_result(
            T.spatial_weights_matrix.invoke({"layer_name": "polar", "method": "knn", "k": 1}))
        assert sidecar["neighbors"][0] == [1], (
            f"knn 最近邻选成了 {sidecar['neighbors'][0]}（期望 [1]=B）很可能直接在经纬度上做了欧氏距离")

    def test_artifacts_on_disk_and_reopenable(self):
        from scipy import sparse as sp
        _setup("grid", _grid_3x3())
        payload, _ = _weights_result(
            T.spatial_weights_matrix.invoke({"layer_name": "grid", "method": "queen"}))
        assert os.path.exists(payload["matrix"]), payload["matrix"]
        assert os.path.exists(payload["sidecar"]), payload["sidecar"]
        W = sp.load_npz(payload["matrix"])
        assert W.shape == (9, 9)
        assert int(W.nnz) == 40, f"queen 总邻居数应为 4*3+4*5+8=40（对称邻接，每条边计两次），实际 {W.nnz}"
        assert not (W.diagonal() > 0).any(), "权重矩阵对角线必须为 0（不含自身）"
        assert (W.toarray() == W.toarray().T).all(), "邻接矩阵应当对称"

    def test_contiguity_rejects_point_layer(self):
        _setup("pts", _fc([_pt(0, 0), _pt(1, 0), _pt(1, 1)]))
        r = T.spatial_weights_matrix.invoke({"layer_name": "pts", "method": "queen"})
        assert "面图层" in r and "knn" in r

    def test_reports_backend_path(self):
        _setup("grid", _grid_3x3())
        r = T.spatial_weights_matrix.invoke({"layer_name": "grid"})
        assert ("libpysal" in r) or ("numpy/scipy" in r), r[:200]


# ============================================================
# central_tendency
# ============================================================
def _square_at(lon0, lat0, d=0.001):
    """0.001 度见方的小方块（约 111m x 102m @ lat23）。"""
    return _fc([_pt(lon0, lat0), _pt(lon0 + d, lat0),
                _pt(lon0, lat0 + d), _pt(lon0 + d, lat0 + d)])


class TestCentralTendency:
    def test_mean_center_matches_projected_midpoint(self):
        """对称方块：平均中心应等于方块中心（在投影坐标下独立复核）。"""
        lon0, lat0, d = 113.0, 23.0, 0.001
        _setup("sym", _square_at(lon0, lat0, d))
        r = T.central_tendency.invoke({"layer_name": "sym"})
        payload = _summary(r)
        assert payload["crs"].startswith("EPSG:"), payload
        gdf, _ = _layer_to_gdf("sym")
        proj = gdf.to_crs(payload["crs"])
        exp_x = float(np.mean([p.x for p in proj.geometry.representative_point()]))
        exp_y = float(np.mean([p.y for p in proj.geometry.representative_point()]))
        assert abs(payload["mean_center"][0] - exp_x) < 0.5, (payload["mean_center"], exp_x)
        assert abs(payload["mean_center"][1] - exp_y) < 0.5, (payload["mean_center"], exp_y)

    def test_standard_distance_is_metric_scale(self):
        """标准距离必须是米级  若误用度计算会得到 ~1e-4，本断言会失败。

        0.001 度见方（约 111m x 102m）的 4 角点，标准距离约 75 m。
        """
        _setup("sym", _square_at(113.0, 23.0, 0.001))
        payload = _summary(T.central_tendency.invoke({"layer_name": "sym"}))
        sd = payload["standard_distance_m"]
        assert 30.0 < sd < 200.0, (
            f"标准距离 {sd} 不在米级合理区间 [30,200]；若约 1e-4 说明误把经纬度当米")

    def test_ann_observed_distance_is_metric_scale(self):
        """平均最近邻的观测/期望距离都必须是米级。"""
        _setup("sym", _square_at(113.0, 23.0, 0.001))
        r = T.central_tendency.invoke({"layer_name": "sym"})
        payload = _summary(r)
        assert payload["ann_ratio"] is not None
        # 4 个角点，最近邻 = 边长约 102~111 m
        assert 50.0 < payload["ann_observed_mean_m"] < 200.0, payload

    def test_central_feature_is_middle_point(self):
        """4 角 + 1 中心点：中心点到其他点总距离最小，应被选为中心要素（第 5 个）。"""
        lon0, lat0, d = 113.0, 23.0, 0.001
        feats = [_pt(lon0, lat0), _pt(lon0 + d, lat0), _pt(lon0, lat0 + d),
                 _pt(lon0 + d, lat0 + d), _pt(lon0 + d / 2, lat0 + d / 2)]
        _setup("plus", _fc(feats))
        r = T.central_tendency.invoke({"layer_name": "plus"})
        assert "中心要素" in r
        assert "第 5 个要素" in r, r

    def test_median_center_symmetric(self):
        _setup("sym", _square_at(113.0, 23.0, 0.001))
        payload = _summary(T.central_tendency.invoke({"layer_name": "sym"}))
        # 中位中心与平均中心应对称重合（误差 < 2 m）
        assert abs(payload["median_center"][0] - payload["mean_center"][0]) < 1.0
        assert abs(payload["median_center"][1] - payload["mean_center"][1]) < 1.0

    def test_median_center_minimizes_total_distance(self):
        from scipy.optimize import minimize

        _setup("asym", _fc([_pt(113.0, 23.0), _pt(113.01, 23.0), _pt(113.0, 23.01)]))
        payload = _summary(T.central_tendency.invoke({"layer_name": "asym"}))
        gdf, _ = _layer_to_gdf("asym")
        points = np.array([[geom.x, geom.y] for geom in gdf.to_crs(payload["crs"]).geometry])
        result = np.asarray(payload["median_center"], dtype=float)
        axis_median = np.median(points, axis=0)
        objective = lambda center: np.linalg.norm(points - center, axis=1).sum()
        reference = minimize(objective, points.mean(axis=0), method="Nelder-Mead",
                             options={"xatol": 1e-7, "fatol": 1e-7})

        assert np.linalg.norm(result - axis_median) > 100.0
        assert objective(result) <= reference.fun + 1e-3


# ============================================================
# spatial_regression
# ============================================================
def _linear_layer(n=8):
    return _fc([_pt(float(i), 0.0, x=float(i), y=2.0 * i + 1.0) for i in range(n)])


class TestSpatialRegression:
    def test_perfect_linear_recovers_coefficients(self):
        _setup("lin", _linear_layer())
        r = T.spatial_regression.invoke(
            {"layer_name": "lin", "dependent": "y", "independents": "x"})
        payload = _summary(r)
        coef = payload["coefficients"]
        assert abs(coef["x"] - 2.0) < 1e-6, coef
        assert abs(coef["const"] - 1.0) < 1e-6, coef
        assert payload["r2"] is not None and abs(payload["r2"] - 1.0) < 1e-6, payload
        assert "OLS" in r

    def test_reports_standard_errors_and_aic(self):
        _setup("lin", _linear_layer())
        r = T.spatial_regression.invoke(
            {"layer_name": "lin", "dependent": "y", "independents": "x"})
        assert "标准误" in r and "AIC" in r and "调整 R" in r

    def test_rank_deficient_design_does_not_report_inference(self):
        features = [_pt(float(i), 0.0, x=float(i), x_copy=2.0 * i, y=3.0 * i + 1.0) for i in range(8)]
        _setup("collinear", _fc(features))
        result = T.spatial_regression.invoke(
            {"layer_name": "collinear", "dependent": "y", "independents": "x,x_copy"})
        assert "设计矩阵秩不足" in result, result
        assert "STATS_SUMMARY" not in result, "共线模型不能发布误导性的系数/显著性摘要"

    def test_missing_dependent_field_fails_clearly(self):
        _setup("lin", _linear_layer())
        r = T.spatial_regression.invoke(
            {"layer_name": "lin", "dependent": "nope", "independents": "x"})
        assert "不存在" in r

    def test_non_numeric_field_fails_clearly(self):
        feats = [_pt(float(i), 0.0, x=float(i), y=2.0 * i + 1.0, label="a") for i in range(6)]
        _setup("lin2", _fc(feats))
        r = T.spatial_regression.invoke(
            {"layer_name": "lin2", "dependent": "y", "independents": "label"})
        assert "数值" in r

    def test_gwr_is_not_faked(self):
        _setup("lin", _linear_layer())
        r = T.spatial_regression.invoke(
            {"layer_name": "lin", "dependent": "y", "independents": "x", "model": "gwr"})
        assert "暂未支持" in r
        assert "不会启用 GWR" in r
        assert "STATS_SUMMARY" not in r, "gwr 不应悄悄按 OLS 返回结果"


# ============================================================
# directional_distribution
# ============================================================
class TestDirectionalDistribution:
    def test_diagonal_ellipse_rotation_and_layer(self):
        """正对角线分布：方向角应为 45（自正北），并生成椭圆面图层。"""
        _setup("diag", _fc([_pt(0, 0), _pt(1, 1), _pt(2, 2), _pt(3, 3)]))
        r = T.directional_distribution.invoke(
            {"layer_name": "diag", "std_deviations": "1_std,2_std"})
        names = [n for n in _registered_layers if "标准差椭圆" in n]
        assert names, f"未生成椭圆图层：{list(_registered_layers.keys())}"
        geo = _registered_layers[names[0]]["geojson"]
        assert len(geo["features"]) == 2, "1_std,2_std 应生成 2 个椭圆"
        props = geo["features"][0]["properties"]
        rot = float(props["rotation_deg"]) % 180.0
        assert abs(rot - 45.0) < 1.5, f"方向角 {rot} 应接近 45（UMT 投影稍偏离正 45）：{props}"
        assert props["x_std_distance"] >= props["y_std_distance"] - 1e-9, props

    def test_axes_are_metric_scale(self):
        """椭圆轴长必须是米级（0.001 度见方 -> 轴长约 55/51 m），度制会得到 ~1e-4。"""
        _setup("sq", _square_at(113.0, 23.0, 0.002))
        r = T.directional_distribution.invoke({"layer_name": "sq"})
        assert "标准差椭圆" in r
        names = [n for n in _registered_layers if "标准差椭圆" in n]
        props = _registered_layers[names[0]]["geojson"]["features"][0]["properties"]
        assert 30.0 < float(props["x_std_distance"]) < 400.0, props
        assert 30.0 < float(props["y_std_distance"]) < 400.0, props

    def test_grouping_one_ellipse_per_group(self):
        # 每组 3 个非共线点（2 点组会退化成线段，本测试用退化组见下一个用例）
        pts = [_pt(0, 0, g="A"), _pt(1, 0, g="A"), _pt(0, 1, g="A"),
               _pt(5, 5, g="B"), _pt(6, 5, g="B"), _pt(5, 6, g="B")]
        _setup("grp", _fc(pts))
        T.directional_distribution.invoke({"layer_name": "grp", "group_field": "g"})
        names = [n for n in _registered_layers if "标准差椭圆" in n]
        assert names, "分组后应生成椭圆图层"
        geo = _registered_layers[names[0]]["geojson"]
        # 默认 std_deviations='1_std,2_std'：每组 2 个椭圆，共 2 组 -> 4 个面
        assert len(geo["features"]) == 4, f"实际 {len(geo['features'])} 个椭圆"
        groups = {f["properties"]["group"] for f in geo["features"]}
        assert groups == {"A", "B"}
        devs = {f["properties"]["std_dev"] for f in geo["features"]}
        assert devs == {1.0, 2.0}

    def test_degenerate_group_is_reported_not_silently_dropped(self):
        """2 点共线组做不出椭圆，必须明确报告跳过，而不是静默消失。"""
        pts = [_pt(0, 0, g="A"), _pt(1, 0, g="A"),            # 共线 -> 退化
               _pt(5, 5, g="B"), _pt(6, 5, g="B"), _pt(5, 6, g="B")]
        _setup("mix", _fc(pts))
        r = T.directional_distribution.invoke({"layer_name": "mix", "group_field": "g"})
        assert "跳过" in r and "A" in r, r
        names = [n for n in _registered_layers if "标准差椭圆" in n]
        assert names, "非退化组 B 仍应生成椭圆"
        groups = {f["properties"]["group"] for f in _registered_layers[names[0]]["geojson"]["features"]}
        assert groups == {"B"}

    def test_bad_std_deviations_string_fails(self):
        _setup("diag", _fc([_pt(0, 0), _pt(1, 1)]))
        r = T.directional_distribution.invoke(
            {"layer_name": "diag", "std_deviations": "abc"})
        assert "解析失败" in r


# ============================================================
# od_cost_matrix
# ============================================================
def _line_network():
    """一条 0.01 度长的水平路（两个线段），用于手工核对 OD 成本。"""
    return _fc([{
        "type": "Feature",
        "properties": {"highway": "residential"},
        "geometry": {"type": "LineString",
                     "coordinates": [[0.0, 0.0], [0.005, 0.0], [0.01, 0.0]]},
    }])


class TestOdCostMatrix:
    def test_cost_matches_haversine_and_artifacts(self):
        _setup("net", _line_network())
        _setup("orig", _fc([_pt(0.0, 0.0, name="o1")]))
        _setup("dest", _fc([_pt(0.01, 0.0, name="d1")]))
        r = T.od_cost_matrix.invoke(
            {"origins_layer": "orig", "destinations_layer": "dest", "network_source": "net"})
        payload = _summary(r)
        assert payload["n_origins"] == 1 and payload["n_destinations"] == 1
        expected = _haversine((0.0, 0.0), (0.01, 0.0))
        assert abs(payload["total_cost_m"] - expected) < max(5.0, expected * 0.02), (
            f"OD 成本 {payload['total_cost_m']} 与独立 haversine {expected:.2f} m 不符")
        assert "米" in r or "m" in r
        assert os.path.exists(payload["csv"]), payload["csv"]
        assert os.path.exists(payload["json"]), payload["json"]
        import csv as _csv
        with open(payload["csv"], encoding="utf-8") as fh:
            rows = list(_csv.reader(fh))
        assert rows[0] == ["origin_index", "destination_index", "cost_m", "reachable"]
        assert len(rows) == 2 and rows[1][3] == "1"

    def test_multi_od_matrix_shape(self):
        _setup("net", _line_network())
        _setup("orig", _fc([_pt(0.0, 0.0), _pt(0.005, 0.0)]))
        _setup("dest", _fc([_pt(0.005, 0.0), _pt(0.01, 0.0)]))
        payload = _summary(T.od_cost_matrix.invoke(
            {"origins_layer": "orig", "destinations_layer": "dest", "network_source": "net"}))
        assert payload["n_origins"] == 2 and payload["n_destinations"] == 2
        assert payload["unreachable_pairs"] == 0
        with open(payload["json"], encoding="utf-8") as fh:
            matrix = json.load(fh)["matrix"]
        assert len(matrix) == 2 and len(matrix[0]) == 2
        one_seg = _haversine((0.0, 0.0), (0.005, 0.0))   # 约 556 m
        tol = max(5.0, one_seg * 0.02)
        # o1(0.005,0) == d0(0.005,0)：同一吸附节点，成本 0
        assert abs(matrix[1][0]) < 1e-6, matrix
        # o0(0,0) -> d0(0.005,0)：一段约 556 m
        assert abs(matrix[0][0] - one_seg) < tol, matrix
        # o1(0.005,0) -> d1(0.01,0)：一段约 556 m
        assert abs(matrix[1][1] - one_seg) < tol, matrix
        # o0(0,0) -> d1(0.01,0)：两段约 1112 m
        assert abs(matrix[0][1] - 2 * one_seg) < 2 * tol, matrix

    def test_partial_snap_failures_preserve_original_matrix_indices(self):
        _setup("net", _line_network())
        _setup("orig", _fc([_pt(1.0, 1.0, name="outside"), _pt(0.005, 0.0, name="o1")]))
        _setup("dest", _fc([_pt(0.01, 0.0, name="d1"), _pt(1.0, 1.0, name="outside")]))

        payload = _summary(T.od_cost_matrix.invoke(
            {"origins_layer": "orig", "destinations_layer": "dest", "network_source": "net"}))

        with open(payload["json"], encoding="utf-8") as fh:
            result = json.load(fh)
        assert result["n_origins"] == 2 and result["n_destinations"] == 2
        assert result["unsnapped_origin_indices"] == [0]
        assert result["unsnapped_destination_indices"] == [1]
        assert result["matrix"][0] == [None, None]
        expected = _haversine((0.005, 0.0), (0.01, 0.0))
        assert abs(result["matrix"][1][0] - expected) < 5
        with open(payload["csv"], encoding="utf-8") as fh:
            rows = list(__import__("csv").reader(fh))
        assert [(row[0], row[1]) for row in rows[1:]] == [("0", "0"), ("0", "1"), ("1", "0"), ("1", "1")]

    def test_missing_network_fails_clearly(self):
        _setup("orig", _fc([_pt(0.0, 0.0)]))
        _setup("dest", _fc([_pt(0.01, 0.0)]))
        r = T.od_cost_matrix.invoke(
            {"origins_layer": "orig", "destinations_layer": "dest", "network_source": "nope"})
        assert "路网" in r


