# -*- coding: utf-8 -*-
"""visualize_3d 工具测试：spec 发射、图层/字段/类型/高度校验

3D 可视化链路：工具校验 → layer_ops visualize spec → 前端 applyVisualization。
工具端最容易错的是把非数值字段/非面图层静默发给前端，这里逐条钉住。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.services import tools as T
from backend.services.tools import _register_layer, visualize_3d


def _poly_fc(field="population"):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[[112.0, 27.0], [113.0, 27.0], [113.0, 28.0], [112.0, 28.0], [112.0, 27.0]]]},
         "properties": {"adcode": 430100, "name": "长沙市", field: 1000}},
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[[113.0, 26.0], [114.0, 26.0], [114.0, 27.0], [113.0, 27.0], [113.0, 26.0]]]},
         "properties": {"adcode": 430200, "name": "株洲市", field: 500}},
    ]}


def _isolate_visualize_3d_state(monkeypatch):
    from backend.services.tool_modules import runtime

    isolated = {
        "_registered_layers": {},
        "_pending_layer_ops": [],
    }
    with runtime._state_lock:
        for name, value in isolated.items():
            monkeypatch.setattr(T, name, value)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    _isolate_visualize_3d_state(monkeypatch)


def test_visualize_3d_fixture_restores_existing_runtime_state():
    from backend.services.tool_modules import runtime

    registry, pending_ops = runtime._registered_layers, runtime._pending_layer_ops
    registry["outside-sentinel"] = {"sentinel": True}
    pending_ops.append({"action": "outside-sentinel"})

    patcher = pytest.MonkeyPatch()
    try:
        _isolate_visualize_3d_state(patcher)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layer_ops is not pending_ops
        assert T._registered_layers is runtime._registered_layers
    finally:
        patcher.undo()

    assert runtime._registered_layers is registry
    assert registry["outside-sentinel"]["sentinel"]
    assert runtime._pending_layer_ops is pending_ops
    assert pending_ops[-1]["action"] == "outside-sentinel"


class TestVisualize3d:
    def test_emits_spec(self):
        _register_layer("湖南省_省级", _poly_fc())
        out = visualize_3d.invoke({"layer_name": "湖南省_省级", "field": "population", "max_height": 200000})
        assert "拉伸" in out
        ops = [o for o in T._pending_layer_ops if o["action"] == "visualize"]
        assert len(ops) == 1
        assert ops[0]["name"] == "湖南省_省级"
        assert ops[0]["viz"]["type"] == "extrusion"
        assert ops[0]["viz"]["field"] == "population"
        assert ops[0]["viz"]["maxHeight"] == 200000

    def test_layer_not_found(self):
        out = visualize_3d.invoke({"layer_name": "不存在", "field": "population"})
        assert "未找到" in out
        assert T._tool_result_failed("visualize_3d", out)
        assert all(o["action"] != "visualize" for o in T._pending_layer_ops)

    def test_empty_layer_is_classified_as_failure(self):
        _register_layer("empty", {"type": "FeatureCollection", "features": []})

        out = visualize_3d.invoke({"layer_name": "empty", "field": "population"})

        assert "无要素" in out
        assert T._tool_result_failed("visualize_3d", out)
        assert all(o["action"] != "visualize" for o in T._pending_layer_ops)

    def test_unsupported_type(self):
        _register_layer("L", _poly_fc())
        out = visualize_3d.invoke({"layer_name": "L", "field": "population", "viz_type": "choropleth"})
        assert "暂不支持" in out
        assert all(o["action"] != "visualize" for o in T._pending_layer_ops)

    def test_bad_height(self):
        _register_layer("L", _poly_fc())
        # 非数值会被 @tool 的 pydantic 参数校验拦下（ValueError），这里钉范围分支
        with pytest.raises(Exception):
            visualize_3d.invoke({"layer_name": "L", "field": "population", "max_height": "abc"})
        assert "失败" in visualize_3d.invoke({"layer_name": "L", "field": "population", "max_height": 1})
        assert all(o["action"] != "visualize" for o in T._pending_layer_ops)

    def test_non_poly_layer(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [112.0, 28.0]},
             "properties": {"population": 100}}]}
        _register_layer("点层", fc)
        out = visualize_3d.invoke({"layer_name": "点层", "field": "population"})
        assert "面" in out
        assert all(o["action"] != "visualize" for o in T._pending_layer_ops)

    def test_non_numeric_field(self):
        _register_layer("L", _poly_fc(field="category"))
        out = visualize_3d.invoke({"layer_name": "L", "field": "population"})
        assert "无数值" in out
        assert all(o["action"] != "visualize" for o in T._pending_layer_ops)

    def test_string_numeric_ok(self):
        fc = _poly_fc()
        fc["features"][0]["properties"]["population"] = "1000"  # 字符串数字也应通过
        _register_layer("L", fc)
        assert "拉伸" in visualize_3d.invoke({"layer_name": "L", "field": "population"})

    def test_tool_registered(self):
        from backend.services.tools import tools
        # tools 列表出口统一包了执行历史包装层，按 name 匹配而非对象同一性
        assert any(getattr(t, "name", "") == "visualize_3d" for t in tools)
