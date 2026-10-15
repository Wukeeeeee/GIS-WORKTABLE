# -*- coding: utf-8 -*-
"""矢量/属性缺口工具回归测试：join_field / geometry_attributes /
minimum_bounding_geometry / points_to_line / generate_points_along_lines。

重点不是"返回了字符串"，而是数字对不对：
- join_field 是 1:1 时绝不能行倍增，且要报告匹配/未匹配键数；
- geometry_attributes 在 EPSG:4326 下必须投影后再算面积，否则单位是平方度；
- minimum_bounding_geometry 的圆半径必须按米（投影）而不是度；
- points_to_line 的顶点顺序必须遵守 order_field，点不足的分组要跳过；
- generate_points_along_lines 的 interval/unit 必须按米/千米换算，点数与已知线长一致。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import math

import geopandas as gpd
import pytest

from backend.services import tools as T
from backend.services.tools import (
    _register_layer,
    _registered_layers,
    reset_state,
    tools as TOOL_LIST,
)

NEW_TOOLS = [
    "join_field",
    "geometry_attributes",
    "minimum_bounding_geometry",
    "points_to_line",
    "generate_points_along_lines",
]

join_field = T.join_field
geometry_attributes = T.geometry_attributes
minimum_bounding_geometry = T.minimum_bounding_geometry
points_to_line = T.points_to_line
generate_points_along_lines = T.generate_points_along_lines


@pytest.fixture(autouse=True)
def cleanup():
    reset_state()
    yield
    reset_state()


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _pt(props, x, y):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": [x, y]}}


def _poly(props, coords):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [coords]}}


def _line(props, coords):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "LineString", "coordinates": coords}}


def _oracle_metric(fc):
    """测试侧独立把 GeoJSON 转成投影坐标，作为数值 oracle。"""
    gdf = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
    return gdf, gdf.to_crs(gdf.estimate_utm_crs())


# ============================================================
# join_field
# ============================================================

def test_join_field_left_no_row_multiplication_and_match_counts():
    """1:1 left join：行数不变，匹配 2 / 未匹配 1，数值正确带入。"""
    target = _fc([
        _pt({"key": 1, "name": "a"}, 113.0, 23.0),
        _pt({"key": 2, "name": "b"}, 113.1, 23.1),
        _pt({"key": 3, "name": "c"}, 113.2, 23.2),
    ])
    join = _fc([
        _pt({"jid": 1, "score": 10}, 0.0, 0.0),
        _pt({"jid": 2, "score": 20}, 1.0, 1.0),
    ])
    _register_layer("tgt", target)
    _register_layer("jn", join)

    r = join_field.invoke({
        "target_layer": "tgt", "join_layer": "jn",
        "target_field": "key", "join_field": "jid",
        "fields": "score", "how": "left",
    })
    assert "完成" in r and "匹配 2" in r and "未匹配 1" in r, r
    out, _ = T._layer_to_gdf("tgt_连接jn")
    assert out is not None
    assert len(out) == 3, f"1:1 left join 不应行倍增，实际 {len(out)} 行"
    scores = list(out.sort_values("key")["score"])
    assert scores[0] == pytest.approx(10.0)
    assert scores[1] == pytest.approx(20.0)
    assert math.isnan(scores[2]), f"未匹配键的行应为 NaN，实际 {scores}"


def test_join_field_inner_drops_unmatched():
    target = _fc([
        _pt({"key": 1, "name": "a"}, 113.0, 23.0),
        _pt({"key": 2, "name": "b"}, 113.1, 23.1),
        _pt({"key": 3, "name": "c"}, 113.2, 23.2),
    ])
    join = _fc([
        _pt({"jid": 1, "score": 10}, 0.0, 0.0),
        _pt({"jid": 2, "score": 20}, 1.0, 1.0),
    ])
    _register_layer("tgt", target)
    _register_layer("jn", join)
    r = join_field.invoke({
        "target_layer": "tgt", "join_layer": "jn",
        "target_field": "key", "join_field": "jid",
        "fields": "score", "how": "inner",
    })
    assert "匹配 2" in r, r
    out, _ = T._layer_to_gdf("tgt_连接jn")
    assert len(out) == 2, f"inner join 应只剩 2 行，实际 {len(out)}"


def test_join_field_collision_is_renamed_not_overwritten():
    """两边同名字段必须重命名，不能把目标层原字段覆盖掉。"""
    target = _fc([
        _pt({"key": 1, "name": "LEFT1"}, 113.0, 23.0),
        _pt({"key": 2, "name": "LEFT2"}, 113.1, 23.1),
    ])
    join = _fc([
        _pt({"jid": 1, "name": "RIGHT1"}, 0.0, 0.0),
        _pt({"jid": 2, "name": "RIGHT2"}, 1.0, 1.0),
    ])
    _register_layer("tgt_c", target)
    _register_layer("jn_c", join)
    r = join_field.invoke({
        "target_layer": "tgt_c", "join_layer": "jn_c",
        "target_field": "key", "join_field": "jid", "how": "left",
    })
    assert "重命名" in r, r
    out, _ = T._layer_to_gdf("tgt_c_连接jn_c")
    assert out is not None
    assert "name" in out.columns and "name_join" in out.columns, out.columns.tolist()
    assert list(out.sort_values("key")["name"]) == ["LEFT1", "LEFT2"]
    assert list(out.sort_values("key")["name_join"]) == ["RIGHT1", "RIGHT2"]


def test_join_field_missing_key_fails_clearly():
    target = _fc([_pt({"key": 1}, 113.0, 23.0)])
    join = _fc([_pt({"jid": 1, "score": 10}, 0.0, 0.0)])
    _register_layer("tgt_m", target)
    _register_layer("jn_m", join)
    r = join_field.invoke({
        "target_layer": "tgt_m", "join_layer": "jn_m",
        "target_field": "no_such", "join_field": "jid",
    })
    assert "失败" in r or "不存在" in r, r


# ============================================================
# geometry_attributes
# ============================================================

def test_geometry_attributes_area_uses_projected_crs():
    """0.01 x 0.01 方框在经纬度下面积是 1e-4 度，工具必须投影到 UTM 后算成 ~1.13e6 m。"""
    box = _fc([_poly({"n": "box"}, [
        [113.00, 23.00], [113.01, 23.00], [113.01, 23.01], [113.00, 23.01], [113.00, 23.00],
    ])])
    _register_layer("geom_box", box)

    r = geometry_attributes.invoke({
        "layer_name": "geom_box", "metrics": "area,length,perimeter,centroid,bbox",
    })
    assert "完成" in r and "投影" in r, r

    out, _ = T._layer_to_gdf("geom_box_几何属性")
    assert out is not None

    _g, proj = _oracle_metric(box)
    expected_area = float(proj.geometry.area.iloc[0])
    actual_area = float(out["area"].iloc[0])
    assert actual_area == pytest.approx(expected_area, rel=1e-6), (
        f"面积应等于独立投影计算值 {expected_area}，实际 {actual_area}（若是 1e-4 量级说明没投影）"
    )
    assert 1.0e6 < actual_area < 1.3e6, f"0.01 方框面积应约 1.13e6 m，实际 {actual_area}"

    assert float(out["length"].iloc[0]) == pytest.approx(float(proj.geometry.length.iloc[0]), rel=1e-6)
    assert float(out["perimeter"].iloc[0]) == pytest.approx(float(proj.geometry.length.iloc[0]), rel=1e-6)
    assert float(out["centroid_x"].iloc[0]) == pytest.approx(float(proj.geometry.centroid.x.iloc[0]), rel=1e-6)
    assert float(out["centroid_y"].iloc[0]) == pytest.approx(float(proj.geometry.centroid.y.iloc[0]), rel=1e-6)
    assert float(out["bbox_minx"].iloc[0]) == pytest.approx(float(proj.geometry.bounds.minx.iloc[0]), rel=1e-6)
    assert float(out["bbox_maxy"].iloc[0]) == pytest.approx(float(proj.geometry.bounds.maxy.iloc[0]), rel=1e-6)


def test_geometry_attributes_metrics_selection():
    """metrics 只请求 centroid 时，不应添加 area/length 字段。"""
    box = _fc([_poly({"n": "box"}, [
        [113.00, 23.00], [113.01, 23.00], [113.01, 23.01], [113.00, 23.01], [113.00, 23.00],
    ])])
    _register_layer("geom_box2", box)
    geometry_attributes.invoke({"layer_name": "geom_box2", "metrics": "centroid"})
    out, _ = T._layer_to_gdf("geom_box2_几何属性")
    assert "centroid_x" in out.columns and "centroid_y" in out.columns
    assert "area" not in out.columns and "length" not in out.columns


# ============================================================
# minimum_bounding_geometry
# ============================================================

def test_minimum_bounding_geometry_envelope_bounds_exact():
    pts = _fc([
        _pt({"g": "g1"}, 113.00, 23.00),
        _pt({"g": "g1"}, 113.02, 23.01),
        _pt({"g": "g2"}, 114.00, 24.00),
    ])
    _register_layer("pts_env", pts)
    r = minimum_bounding_geometry.invoke({
        "layer_name": "pts_env", "kind": "envelope", "group_field": "g",
    })
    assert "完成" in r, r
    out, _ = T._layer_to_gdf("pts_env_按g_包络")
    assert out is not None and len(out) == 2
    by_group = {row["g"]: row.geometry.bounds for _, row in out.iterrows()}
    assert by_group["g1"] == pytest.approx((113.0, 23.0, 113.02, 23.01), abs=1e-9)
    assert by_group["g2"] == pytest.approx((114.0, 24.0, 114.0, 24.0), abs=1e-9)


def test_minimum_bounding_geometry_circle_radius_in_metres():
    """圆半径必须按米并在返回串里说明投影；跨约 1.4 的点集半径应约 75 km 而不是约 1.4。"""
    pts = _fc([
        _pt({"g": "g1"}, 113.0, 23.0),
        _pt({"g": "g1"}, 113.02, 23.01),
        _pt({"g": "g2"}, 114.0, 24.0),
    ])
    _register_layer("pts_circ", pts)
    r = minimum_bounding_geometry.invoke({"layer_name": "pts_circ", "kind": "circle"})
    assert "完成" in r and "m" in r, r
    out, _ = T._layer_to_gdf("pts_circ_最小外接圆")
    assert out is not None and len(out) == 1
    radius_m = float(out["radius_m"].iloc[0])
    assert 10_000.0 < radius_m < 200_000.0, f"跨约 1.4 的点集半径应是百米公里级，实际 {radius_m}"
    assert float(out["radius_km"].iloc[0]) == pytest.approx(radius_m / 1000.0, rel=1e-9)

    # 独立 oracle：投影后用 shapely 最小外接圆再量半径
    _g, proj = _oracle_metric(pts)
    from shapely import minimum_bounding_circle
    circ = minimum_bounding_circle(proj.geometry.union_all())
    c = circ.centroid
    coords = list(circ.exterior.coords)[:-1]
    oracle_r = max(math.hypot(x - c.x, y - c.y) for x, y in coords)
    assert radius_m == pytest.approx(oracle_r, rel=1e-6), (radius_m, oracle_r)


def test_minimum_bounding_geometry_missing_group_field_fails():
    pts = _fc([_pt({"g": "g1"}, 113.0, 23.0)])
    _register_layer("pts_bad", pts)
    r = minimum_bounding_geometry.invoke({"layer_name": "pts_bad", "group_field": "nope"})
    assert "未找到" in r or "不存在" in r or "失败" in r, r


# ============================================================
# points_to_line
# ============================================================

def test_points_to_line_orders_by_order_field_and_skips_small_groups():
    pts = _fc([
        _pt({"g": "L1", "ord": 1}, 0.00, 0.0),
        _pt({"g": "L1", "ord": 3}, 0.02, 0.0),
        _pt({"g": "L1", "ord": 2}, 0.01, 0.0),
        _pt({"g": "L2", "ord": 1}, 1.00, 1.0),
    ])
    _register_layer("pp", pts)
    r = points_to_line.invoke({
        "layer_name": "pp", "group_field": "g", "order_field": "ord", "close_ring": False,
    })
    assert "完成" in r and "跳过 1" in r, r
    out, _ = T._layer_to_gdf("pp_点转线")
    assert out is not None and len(out) == 1
    row = out.iloc[0]
    assert row["g"] == "L1"
    coords = list(row.geometry.coords)
    assert len(coords) == 3, coords
    xs = [c[0] for c in coords]
    assert xs == pytest.approx([0.00, 0.01, 0.02]), f"应按 order_field 升序，实际 {coords}"
    assert coords[0] != coords[-1], "close_ring=False 不应闭合"


def test_points_to_line_close_ring():
    pts = _fc([
        _pt({"g": "L1", "ord": 1}, 0.00, 0.0),
        _pt({"g": "L1", "ord": 2}, 0.01, 0.0),
        _pt({"g": "L1", "ord": 3}, 0.01, 0.01),
    ])
    _register_layer("pp_ring", pts)
    r = points_to_line.invoke({
        "layer_name": "pp_ring", "group_field": "g", "order_field": "ord", "close_ring": True,
    })
    assert "完成" in r, r
    out, _ = T._layer_to_gdf("pp_ring_点转线")
    coords = list(out.iloc[0].geometry.coords)
    assert len(coords) == 4, coords
    assert coords[0] == pytest.approx(coords[-1]), "close_ring=True 首尾应重合"


# ============================================================
# generate_points_along_lines
# ============================================================

def test_generate_points_along_lines_count_matches_known_length():
    line = _fc([_line({"n": "l"}, [[113.00, 23.00], [113.01, 23.00]])])
    _register_layer("gen_ln", line)

    # 先独立算投影线长，再断言点数是 floor(L/interval)
    _g, proj = _oracle_metric(line)
    L = float(proj.geometry.length.iloc[0])
    expected_n = int(math.floor(L / 250.0))

    r = generate_points_along_lines.invoke({
        "layer_name": "gen_ln", "interval": 250, "unit": "m",
    })
    assert "完成" in r and f"{expected_n} 个点" in r, r
    out, _ = T._layer_to_gdf("gen_ln_沿线等距点")
    assert out is not None and len(out) == expected_n, (len(out), expected_n, L)
    dists = sorted(float(v) for v in out["dist_m"])
    assert dists == pytest.approx([250.0 * (i + 1) for i in range(expected_n)]), dists


def test_generate_points_along_lines_km_unit_equivalent():
    """0.25 km 与 250 m 必须生成完全相同的点数。"""
    line = _fc([_line({"n": "l"}, [[113.00, 23.00], [113.01, 23.00]])])
    _register_layer("gen_ln2", line)
    generate_points_along_lines.invoke({"layer_name": "gen_ln2", "interval": 250, "unit": "m"})
    out_m, _ = T._layer_to_gdf("gen_ln2_沿线等距点")
    n_m = len(out_m)

    generate_points_along_lines.invoke({"layer_name": "gen_ln2", "interval": 0.25, "unit": "km"})
    out_km, _ = T._layer_to_gdf("gen_ln2_沿线等距点")
    assert len(out_km) == n_m, (len(out_km), n_m)
    assert sorted(float(v) for v in out_km["dist_m"]) == pytest.approx(
        sorted(float(v) for v in out_m["dist_m"]))


def test_generate_points_short_line_yields_no_points():
    line = _fc([_line({"n": "short"}, [[113.000, 23.000], [113.0005, 23.000]])])
    _register_layer("gen_short", line)
    r = generate_points_along_lines.invoke({
        "layer_name": "gen_short", "interval": 100, "unit": "m",
    })
    assert "未生成点" in r, r


# ============================================================
# 注册与 docstring 守卫
# ============================================================

def test_new_tools_are_registered_with_docstrings():
    by_name = {t.name: t for t in TOOL_LIST}
    for name in NEW_TOOLS:
        assert name in by_name, f"{name} 未注册到 tools 列表"
        desc = (by_name[name].description or "").strip()
        assert desc, f"{name} 缺少 docstring"
        assert "target_layer" in desc or "layer_name" in desc, f"{name} docstring 未说明图层参数"


def test_new_tool_docstrings_list_every_parameter():
    expected_params = {
        "join_field": ["target_layer", "join_layer", "target_field", "join_field", "fields", "how"],
        "geometry_attributes": ["layer_name", "metrics"],
        "minimum_bounding_geometry": ["layer_name", "kind", "group_field"],
        "points_to_line": ["layer_name", "group_field", "order_field", "close_ring"],
        "generate_points_along_lines": ["layer_name", "interval", "unit"],
    }
    by_name = {t.name: (t.description or "") for t in TOOL_LIST}
    for name, params in expected_params.items():
        for p in params:
            assert p in by_name[name], f"{name} 的 docstring 缺少参数说明：{p}"


def test_registry_size_at_least_141():
    """131 原有 + 5 栅格 + 5 矢量 = 141，少一个就说明忘了注册。"""
    names = [t.name for t in TOOL_LIST]
    assert len(TOOL_LIST) >= 141, f"注册表只有 {len(TOOL_LIST)} 个工具，期望 >= 141"
    assert len(names) == len(set(names)), "注册表存在重复工具名"