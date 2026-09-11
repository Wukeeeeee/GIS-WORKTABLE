# -*- coding: utf-8 -*-
"""focus_map（地图定位工具）测试

定位是纯"触发前端行为"的工具，最容易出的问题是：图层名对不上时静默失败、
坐标解析把中文逗号当成错误、zoom 越界导致 Leaflet 报白屏。这里逐条钉住。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.services import tools as T
from backend.services.tools import focus_map, _registered_layers, reset_state


_SQUARE = {"type": "FeatureCollection", "features": [{
    "type": "Feature",
    "geometry": {"type": "Polygon",
                 "coordinates": [[[113.0, 23.0], [113.5, 23.0], [113.5, 23.5], [113.0, 23.5], [113.0, 23.0]]]},
    "properties": {}}]}


def _setup(name="测试图层", geojson=None):
    reset_state()
    T._pending_layer_ops.clear()
    T._register_layer(name, geojson or _SQUARE)


class TestFocusMapByLayer:
    def setup_method(self):
        _setup()

    def test_focus_by_exact_layer_name(self):
        """按图层名定位：应下发 fit 操作且名字精确匹配"""
        r = focus_map.invoke({"layer_name": "测试图层"})
        assert "已定位到图层" in r
        ops = T._pending_layer_ops
        assert len(ops) == 1
        assert ops[0]["action"] == "fit"
        assert ops[0]["name"] == "测试图层"

    def test_focus_by_partial_layer_name(self):
        """图层名模糊匹配：AI 常给简称，应能匹配到完整注册名"""
        _setup("广州市天河区边界")
        r = focus_map.invoke({"layer_name": "天河区"})
        assert "已定位到图层" in r
        assert T._pending_layer_ops[0]["name"] == "广州市天河区边界"

    def test_focus_unknown_layer_reports_available(self):
        """图层不存在时必须明确失败并列出可用图层，不允许假装定位成功"""
        r = focus_map.invoke({"layer_name": "不存在的图层"})
        assert "未找到图层" in r
        assert "测试图层" in r          # 应提示当前可用图层
        assert T._pending_layer_ops == []  # 未找到时不下发任何地图操作


class TestFocusMapByCenter:
    def setup_method(self):
        _setup()

    def test_focus_by_center_lonlat(self):
        """按经纬度定位：下发 center 操作，注意 Leaflet 要 [lat, lng]"""
        r = focus_map.invoke({"center": "121.4593,31.2513", "zoom": 15})
        assert "已定位到" in r
        op = T._pending_layer_ops[0]
        assert op["action"] == "center"
        # 保持 (lon, lat) 顺序存储，由前端负责换成 [lat, lng]
        assert op["center"] == [121.4593, 31.2513]
        assert op["zoom"] == 15

    def test_focus_center_accepts_chinese_comma(self):
        """中文逗号要容错：这是国内 LLM 输出坐标的常见脏数据"""
        focus_map.invoke({"center": "121.4593，31.2513", "zoom": 14})
        assert T._pending_layer_ops[0]["center"] == [121.4593, 31.2513]

    def test_focus_center_zoom_clamped(self):
        """zoom 必须夹到 3-19，越界会让 Leaflet 直接白屏"""
        focus_map.invoke({"center": "116.4,39.9", "zoom": 25})
        assert T._pending_layer_ops[0]["zoom"] == 19
        T._pending_layer_ops.clear()
        focus_map.invoke({"center": "116.4,39.9", "zoom": 0})
        assert T._pending_layer_ops[0]["zoom"] == 3

    def test_focus_center_malformed(self):
        """坐标格式错误要明确报错，不能落到 [0,0] 或异常"""
        r = focus_map.invoke({"center": "abc"})
        assert "无法解析坐标" in r or "center 格式" in r
        assert T._pending_layer_ops == []

    def test_focus_center_three_components_rejected(self):
        r = focus_map.invoke({"center": "116.4,39.9,100"})
        assert "经度,纬度" in r
        assert T._pending_layer_ops == []


def test_focus_map_without_args_asks_for_input():
    """两个参数都不给时给出用法提示，而不是抛异常"""
    _setup()
    r = focus_map.invoke({})
    assert "layer_name" in r and "center" in r
    assert T._pending_layer_ops == []


def test_focus_map_is_registered_in_tool_list():
    """工具必须出现在 tools 列表里，否则 LLM 永远看不到它"""
    from backend.services.tools import tools
    assert focus_map in tools
