# -*- coding: utf-8 -*-
"""参数角色校验层测试（ESRI 式参数类型系统，最小可用版）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.tool_args_guard import validate_tool_args, PARAM_ROLES


def _mk_layer(name, props):
    from backend.services import tools as T
    feat = {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [[[113, 23], [113.01, 23], [113.01, 23.01], [113, 23.01], [113, 23]]]}}
    T._register_layer(name, {"type": "FeatureCollection", "features": [feat]})


def test_roles_cover_registered_tools():
    """登记的角色表里所有工具名必须真实存在（防拼写错）"""
    from backend.services.tools import tools
    names = {t.name for t in tools}
    bad = [tn for tn in PARAM_ROLES if tn not in names]
    assert not bad, "PARAM_ROLES 里有不存在的工具名: %s" % bad


def test_layer_missing_gives_suggestion(monkeypatch):
    """图层不存在 -> warning 里带可用图层列表

    提示只列前 8 个可用图层，若同批其他用例先注册了大量图层，本用例的 ga_ok 会被挤出列表
    （顺序相关假失败）。这里在用例内隔离图层注册表，保持断言强度同时消除顺序依赖。
    """
    from backend.services import tools as _T
    monkeypatch.setattr(_T, "_registered_layers", {}, raising=False)
    _mk_layer("ga_ok", {"id": 1})
    clean, w = validate_tool_args("spatial_intersect", {"layer_a": "ga_ok", "layer_b": "不存在的图层"})
    assert any("layer_b" in x and "不存在" in x for x in w), w
    assert any("ga_ok" in x for x in w), "应提示可用图层"


def test_layer_ambiguous_gives_candidates():
    _mk_layer("amb_alpha", {"id": 1})
    _mk_layer("amb_alpha2", {"id": 1})
    clean, w = validate_tool_args("spatial_intersect", {"layer_a": "amb_alpha", "layer_b": "amb_alpha"})
    assert not any("layer_a" in x for x in w), w  # 精确名不告警


def test_unit_autocorrect():
    """unit='KM' 自动纠正为 'km'，米别名纠正为 'm'"""
    clean, w = validate_tool_args("spatial_buffer", {"layer_name": "x", "distance": 5, "unit": "KM"})
    assert clean["unit"] == "km"
    clean2, w2 = validate_tool_args("spatial_buffer", {"layer_name": "x", "distance": 5, "unit": "米"})
    assert clean2["unit"] == "m"
    clean3, w3 = validate_tool_args("spatial_buffer", {"layer_name": "x", "distance": 5, "unit": "光年"})
    assert any("单位应为 m 或 km" in x for x in w3)


def test_odd_window_autocorrect():
    """偶数窗口自动 +1"""
    clean, w = validate_tool_args("raster_focal_stats", {"layer_name": "x", "size": 4})
    assert clean["size"] == 5
    assert any("奇数" in x for x in w)


def test_negative_distance_flagged():
    clean, w = validate_tool_args("spatial_buffer", {"layer_name": "x", "distance": -10})
    assert any("正数" in x for x in w)


def test_field_role_dynamic():
    """field_of 动态依赖：字段必须存在于指定图层的属性里"""
    from backend.services.tool_args_guard import _FIELD_ROLE
    # join_field 用 field_of 动态校验（演示扩展方式）：临时注册一个规则
    import backend.services.tool_args_guard as G
    _mk_layer("jf_t", {"key": "a", "val": 1})
    G.PARAM_ROLES.setdefault("join_field", {})["target_field"] = _FIELD_ROLE + "target_layer"
    try:
        clean, w = validate_tool_args("join_field",
            {"target_layer": "jf_t", "join_layer": "jf_t", "target_field": "不存在的字段", "join_field": "key"})
        assert any("target_field" in x and "不在图层字段中" in x for x in w), w
        assert any("key" in x for x in w if "target_field" in x), "应提示可用字段"
    finally:
        G.PARAM_ROLES["join_field"].pop("target_field", None)


def test_no_warning_for_valid_args():
    _mk_layer("ok_layer", {"id": 1})
    clean, w = validate_tool_args("spatial_buffer",
        {"layer_name": "ok_layer", "distance": 100, "unit": "m", "dissolve": False})
    assert w == [], w
    assert clean["distance"] == 100


def test_unknown_tool_is_noop():
    clean, w = validate_tool_args("不存在_的工具", {"a": 1})
    assert clean == {"a": 1} and w == []
