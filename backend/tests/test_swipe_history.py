# -*- coding: utf-8 -*-
"""阶段一工具测试：卷帘对比（create_swipe/close_swipe）+ 处理历史（list_history/rerun_history）

历史持久化文件通过 history_service.set_history_file 重定向到 tmp_path，
避免测试污染 cache/tool_history.json。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json

import pytest

from backend.services import tools as T
from backend.services.tools import (
    tools as TOOL_LIST,
    _register_layer,
    reset_state,
    get_pending_state,
)
from backend.services import history_service


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, request):
    """每个测试独立历史文件，测完恢复"""
    history_service.set_history_file(str(tmp_path / "tool_history.json"))
    yield
    history_service.set_history_file(None)


def _registry():
    """包装后的注册表（Agent 实际调用链路）：{name: tool}"""
    return {t.name: t for t in TOOL_LIST}


def _point_fc(lon, lat, name):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
         "properties": {"name": name}},
    ]}


# ============================================================
# 卷帘对比
# ============================================================

def test_create_swipe_pushes_layer_op():
    reset_state()
    _register_layer("图层A", _point_fc(116, 39, "a"))
    _register_layer("图层B", _point_fc(117, 40, "b"))
    r = _registry()["create_swipe"].invoke({"left_layer": "图层A", "right_layer": "图层B"})
    assert "卷帘" in r and "图层A" in r
    ops = get_pending_state()["layer_ops"]
    assert ops and ops[0]["action"] == "swipe"
    assert ops[0]["left"] == "图层A" and ops[0]["right"] == "图层B"
    assert ops[0]["orientation"] == "vertical"


def test_create_swipe_horizontal_orientation():
    reset_state()
    _register_layer("A", _point_fc(116, 39, "a"))
    _register_layer("B", _point_fc(117, 40, "b"))
    _registry()["create_swipe"].invoke(
        {"left_layer": "A", "right_layer": "B", "orientation": "horizontal"})
    ops = get_pending_state()["layer_ops"]
    assert ops[0]["orientation"] == "horizontal"


def test_create_swipe_chinese_orientation():
    """中文方向词：横向/上下 → horizontal，其余默认纵向"""
    reset_state()
    _register_layer("A", _point_fc(116, 39, "a"))
    _register_layer("B", _point_fc(117, 40, "b"))
    reg = _registry()
    reg["create_swipe"].invoke({"left_layer": "A", "right_layer": "B", "orientation": "横向"})
    assert get_pending_state()["layer_ops"][0]["orientation"] == "horizontal"
    reg["create_swipe"].invoke({"left_layer": "A", "right_layer": "B", "orientation": "上下"})
    assert get_pending_state()["layer_ops"][0]["orientation"] == "horizontal"
    reg["create_swipe"].invoke({"left_layer": "A", "right_layer": "B", "orientation": "竖直"})
    assert get_pending_state()["layer_ops"][0]["orientation"] == "vertical"


def test_create_swipe_missing_layer_returns_error_not_op():
    reset_state()
    _register_layer("A", _point_fc(116, 39, "a"))
    r = _registry()["create_swipe"].invoke({"left_layer": "A", "right_layer": "不存在"})
    assert "未找到" in r
    assert get_pending_state()["layer_ops"] == []


def test_create_swipe_same_layer_rejected():
    reset_state()
    _register_layer("A", _point_fc(116, 39, "a"))
    r = _registry()["create_swipe"].invoke({"left_layer": "A", "right_layer": "A"})
    assert "两个不同的图层" in r


def test_create_swipe_fuzzy_layer_match():
    reset_state()
    _register_layer("广州市_行政区划", _point_fc(113, 23, "gz"))
    _register_layer("佛山市_行政区划", _point_fc(113.1, 23.05, "fs"))
    r = _registry()["create_swipe"].invoke({"left_layer": "广州市", "right_layer": "佛山市"})
    assert "已开启" in r
    ops = get_pending_state()["layer_ops"]
    assert ops[0]["left"] == "广州市_行政区划"


def test_close_swipe_pushes_op():
    reset_state()
    r = _registry()["close_swipe"].invoke({})
    assert "已关闭" in r
    ops = get_pending_state()["layer_ops"]
    assert ops and ops[0]["action"] == "swipe_close"


# ============================================================
# 处理历史：记录 / list_history / rerun_history
# ============================================================

def test_tool_execution_recorded_via_registry():
    """经 tools 列表（Agent 链路）执行的工具自动写入历史"""
    reset_state()
    _registry()["focus_map"].invoke({"center": "116,39"})
    entries = history_service.list_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["tool"] == "focus_map"
    assert e["ok"] is True
    assert e["args"]["center"] == "116,39"
    assert e["time"]  # 有时间戳


def test_failed_execution_recorded_with_error():
    reset_state()
    r = _registry()["create_swipe"].invoke({"left_layer": "无此层1", "right_layer": "无此层2"})
    assert "未找到" in r  # 工具本身不抛异常，返回错误信息
    e = history_service.list_entries()[0]
    assert e["tool"] == "create_swipe" and e["ok"] is True  # 正常返回 = 成功


def test_invalid_args_recorded_gracefully():
    """参数错误不抛异常：包装层兜底返回错误文本，历史照常记录"""
    reset_state()
    reg = {t.name: t for t in TOOL_LIST}
    # focus_map 参数类型错误触发异常
    r = reg["focus_map"].invoke({"center": "不是坐标"})
    assert "格式" in r


def test_list_history_returns_entries():
    reset_state()
    reg = _registry()
    reg["focus_map"].invoke({"center": "116,39"})
    reg["close_swipe"].invoke({})
    r = reg["list_history"].invoke({"limit": 10})
    assert "close_swipe" in r and "focus_map" in r
    assert "#2" in r and "#1" in r  # 倒序编号


def test_history_persisted_to_disk(tmp_path):
    path = tmp_path / "tool_history.json"
    history_service.set_history_file(str(path))
    reset_state()
    _registry()["focus_map"].invoke({"center": "116,39"})
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["entries"] and data["entries"][0]["tool"] == "focus_map"


def test_rerun_history_reexecutes_with_original_args():
    reset_state()
    _register_layer("甲", _point_fc(116, 39, "a"))
    _register_layer("乙", _point_fc(117, 40, "b"))
    reg = _registry()
    reg["create_swipe"].invoke({"left_layer": "甲", "right_layer": "乙"})  # index 1
    get_pending_state()  # 消费第一次的 op
    r = reg["rerun_history"].invoke({"index": 1})
    assert "已重跑" in r and "成功" in r
    ops = get_pending_state()["layer_ops"]
    assert ops and ops[0]["action"] == "swipe" and ops[0]["left"] == "甲"
    # 重跑本身也入历史，且带 rerun_of 标记（重跑的 record 晚于其内层 record）
    entries = history_service.list_entries()
    rerun_entry = next(e for e in entries if e["tool"] == "rerun_history")
    inner = next(e for e in entries if e["tool"] == "create_swipe" and e["rerun_of"] == 1)
    assert rerun_entry["index"] > inner["index"]


def test_rerun_history_produces_new_layer_not_overwrite():
    """重跑产出图层的工具：新图层上图，被覆盖的同名注册图层以「_原」后缀保留"""
    reset_state()
    reg = _registry()
    # draw_feature 产出图层（纯几何，无网络依赖）
    reg["draw_feature"].invoke({
        "geometry_type": "Point", "coordinates": "116.4,39.9", "layer_name": "测试点",
    })
    get_pending_state()
    # 通过 list_history 拿到 draw_feature 的编号
    entries = history_service.list_entries()
    idx = next(e["index"] for e in entries if e["tool"] == "draw_feature")
    r = reg["rerun_history"].invoke({"index": idx})
    assert "已重跑" in r
    new_layers = get_pending_state()["layers"]
    assert len(new_layers) == 1  # 产物作为新图层推送
    # 原图层保留
    assert "测试点_原" in T._registered_layers


def test_rerun_history_missing_index():
    reset_state()
    r = _registry()["rerun_history"].invoke({"index": 99999})
    assert "未找到" in r


def test_rerun_history_never_reruns_itself():
    reset_state()
    _registry()["focus_map"].invoke({"center": "116,39"})  # index 1
    r = _registry()["rerun_history"].invoke({"index": 1})   # 重跑 focus_map（index 2, rerun_of 1）
    assert "已重跑" in r
    # 再试图重跑 rerun_history 自身的历史 → 拒绝
    entries = history_service.list_entries()
    rerun_idx = next(e["index"] for e in entries if e["tool"] == "rerun_history")
    r2 = _registry()["rerun_history"].invoke({"index": rerun_idx})
    assert "不支持重跑" in r2


def test_history_new_tools_registered():
    names = {t.name for t in TOOL_LIST}
    for n in ("create_swipe", "close_swipe", "list_history", "rerun_history"):
        assert n in names
