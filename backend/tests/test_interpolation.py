# -*- coding: utf-8 -*-
"""空间插值（IDW / RBF）测试

插值最容易出的不是崩溃，而是"图出来了一切正常、但方向/取值是错的"。
这里用南低北高的非对称数据把方向钉死。
"""
import os
import sys
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from backend.services import tools as T
from backend.services.tools import (
    spatial_interpolate, _register_layer, _registered_layers, reset_state,
    _pending_layer_ops,
)
from backend.services import history_service


# 南（y=0.0）低值 -> 北（y=0.10）高值，南北非对称
_PROFILE_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"value": 0.0}, "geometry": {"type": "Point", "coordinates": [0.000, 0.00]}},
        {"type": "Feature", "properties": {"value": 10.0}, "geometry": {"type": "Point", "coordinates": [0.001, 0.02]}},
        {"type": "Feature", "properties": {"value": 50.0}, "geometry": {"type": "Point", "coordinates": [0.002, 0.05]}},
        {"type": "Feature", "properties": {"value": 90.0}, "geometry": {"type": "Point", "coordinates": [0.003, 0.08]}},
        {"type": "Feature", "properties": {"value": 100.0}, "geometry": {"type": "Point", "coordinates": [0.004, 0.10]}},
    ],
}


def _isolate_interpolation_state(monkeypatch, tmp_path):
    from backend.services.tool_modules import runtime

    output_dir = str(tmp_path / "tool-runtime")
    isolated_runtime = {
        "_registered_layers": {},
        "_pending_layers": [],
        "_pending_layer_ops": [],
        "_pending_images": [],
        "_pending_qa_warnings": [],
        "_pending_aoi_suggestions": {},
        "_pending_heatmap": {"latest": None},
        "_clear_layers_flag": False,
        "_current_amap_key": "",
        "_search_call_count": 0,
        "_domain_fail": {},
        "_search_cache": {},
        "_search_last_hit": {},
        "_exec_call_count": 0,
        "_exec_log": [],
        "_temp_output_dir": output_dir,
        "_workspace_dir": str(tmp_path / "workspace"),
        "_raster_output_scope": threading.local(),
        "_active_project_id": None,
        "_current_task_id": "",
        "_last_user_message": "",
        "_current_run_id": "",
        "_conversation_context": "",
        "_session_locks": {},
    }
    for path in (output_dir, os.path.join(output_dir, "output"), isolated_runtime["_workspace_dir"]):
        os.makedirs(path, exist_ok=True)
    with runtime._state_lock, runtime._session_locks_guard:
        for name, value in isolated_runtime.items():
            monkeypatch.setattr(T, name, value)
    monkeypatch.setattr(sys.modules[__name__], "_registered_layers", isolated_runtime["_registered_layers"])
    monkeypatch.setattr(sys.modules[__name__], "_pending_layer_ops", isolated_runtime["_pending_layer_ops"])
    history_state = {
        "_CUSTOM_PATH": [str(tmp_path / "tool_history.json")],
        "_ENTRIES": [],
        "_NEXT_INDEX": [1],
        "_LOADED": [False],
        "_LOAD_ERROR": [None],
        "_PERSIST_ERROR": [None],
    }
    for name, value in history_state.items():
        monkeypatch.setattr(history_service, name, value)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    _isolate_interpolation_state(monkeypatch, tmp_path)
    reset_state()
    yield
    reset_state()


def test_interpolation_fixture_restores_existing_runtime_and_history_state(tmp_path):
    from backend.services.tool_modules import runtime

    registry, pending_ops = runtime._registered_layers, runtime._pending_layer_ops
    entries, history_path = history_service._ENTRIES, history_service._CUSTOM_PATH
    registry["outside-sentinel"] = {"sentinel": True}
    pending_ops.append({"action": "outside-op-sentinel"})
    entries.append({"tool": "outside-history-sentinel"})
    history_path[0] = "outside-history-path.json"
    runtime.set_current_task("outside-task-context-sentinel")

    patcher = pytest.MonkeyPatch()
    try:
        _isolate_interpolation_state(patcher, tmp_path)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layer_ops is not pending_ops
        assert history_service._ENTRIES is not entries
        assert history_service._CUSTOM_PATH is not history_path
        assert T._registered_layers is runtime._registered_layers
        assert sys.modules[__name__]._registered_layers is runtime._registered_layers
        assert sys.modules[__name__]._pending_layer_ops is runtime._pending_layer_ops
    finally:
        patcher.undo()

    assert runtime._registered_layers is registry and "outside-sentinel" in registry
    assert runtime._pending_layer_ops is pending_ops and pending_ops[-1]["action"] == "outside-op-sentinel"
    assert history_service._ENTRIES is entries and entries[-1]["tool"] == "outside-history-sentinel"
    assert history_service._CUSTOM_PATH is history_path
    assert history_path[0] == "outside-history-path.json"
    assert runtime.get_current_task_id() == "outside-task-context-sentinel"


def _run_interp(**kw):
    _register_layer("prof", _PROFILE_POINTS)
    r = spatial_interpolate.invoke({"layer_name": "prof", "field": "value", **kw})
    return r


def _overlay_path():
    """取本轮插值生成的 PNG 绝对路径"""
    ops = [o for o in _pending_layer_ops if o.get("action") == "dem_result"]
    assert ops, f"没有产生 dem_result 叠加操作，当前：{_pending_layer_ops}"
    op = ops[0]
    rel = op["url"].replace("/output/", "")
    path = os.path.join(T._temp_output_dir, rel)
    assert os.path.isfile(path), f"叠加图未落盘：{path}"
    return path, op


class TestInterpolateBasics:
    def test_idw_produces_overlay(self):
        r = _run_interp(method="idw", resolution=30)
        assert "IDW" in r
        _overlay_path()

    def test_rbf_produces_overlay(self):
        r = _run_interp(method="rbf", resolution=30)
        assert "RBF" in r
        _overlay_path()

    def test_unknown_method_rejected(self):
        r = _run_interp(method="kriging", resolution=30)
        assert "不支持" in r

    def test_non_point_layer_rejected(self):
        _register_layer("poly", {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "properties": {"value": 1},
                "geometry": {"type": "Polygon",
                             "coordinates": [[[0, 0], [0.02, 0], [0.02, 0.02], [0, 0.02], [0, 0]]]},
            }],
        })
        r = spatial_interpolate.invoke({"layer_name": "poly", "field": "value"})
        assert "点要素" in r

    def test_missing_field_rejected(self):
        _register_layer("prof", _PROFILE_POINTS)
        r = spatial_interpolate.invoke({"layer_name": "prof", "field": "不存在"})
        assert "没有字段" in r


class TestInterpolateOrientation:
    def test_output_image_is_north_up(self):
        """回归：meshgrid 曾按 y 递增生成，row 0 是南，
        PNG 交给 Leaflet 叠加后整张图南北翻转（高值区显示在地图下方）。"""
        from PIL import Image
        _run_interp(method="idw", resolution=50)
        path, op = _overlay_path()

        img = np.array(Image.open(path).convert("RGB"))
        h = img.shape[0]
        # viridis：低值深紫（G 通道远小于 B），高值亮黄（G 通道远大于 B）
        top_is_high = img[2, :, 1].mean() > img[2, :, 2].mean()
        bottom_is_low = img[h - 3, :, 1].mean() < img[h - 3, :, 2].mean()
        assert top_is_high and bottom_is_low, (
            "插值图应为北在上：数据北边是高值，图像顶部应偏黄、底部应偏紫")

    def test_bounds_match_north_south_order(self):
        """bounds 必须是 [west, south, east, north]"""
        _run_interp(method="idw", resolution=30)
        _, op = _overlay_path()
        b = op["bounds"]
        assert b[1] < b[3], f"bounds 南北顺序错误：{b}"
        assert b[0] < b[2], f"bounds 东西顺序错误：{b}"


class TestTempOutputDirLifecycle:
    def test_reset_state_initializes_output_dir(self, monkeypatch, tmp_path):
        """回归：_temp_output_dir 的注释写着"在 reset_state 时设置"，但代码没做。

        一旦一轮里最先执行的工具是直接写该目录的（如 spatial_interpolate），
        目录还是空串，产物会落到 CWD/uploads，而 URL 指向 /output/...，前端 404。
        """
        from backend.services.tool_modules import runtime

        monkeypatch.setattr(runtime.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(T, "_temp_output_dir", "")
        monkeypatch.setattr(T, "_workspace_dir", "")
        reset_state()
        assert T._temp_output_dir == str(tmp_path / "gis_worktable_output")
        assert os.path.isdir(T._temp_output_dir)

    def test_interpolate_works_without_prior_setup(self, monkeypatch, tmp_path):
        """把输出目录指向 tmp 后，产物必须落在那儿，而不是 CWD"""
        monkeypatch.setattr(T, "_temp_output_dir", str(tmp_path / "out"))
        _run_interp(method="idw", resolution=20)
        written = list((tmp_path / "out" / "uploads").glob("*.png"))
        assert written, "插值产物没有写到指定的输出目录"
