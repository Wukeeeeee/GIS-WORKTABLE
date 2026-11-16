# -*- coding: utf-8 -*-
"""阶段 C：分析报告生成 + 数据质量检查工具测试"""
import os
import sys
import threading
import pytest
from pathlib import Path
from backend.services import tools as T
from backend.services import history_service
from backend.services.tools import (
    generate_analysis_report, spatial_fix_geometry, spatial_check_duplicates,
    _register_layer, _registered_layers, _pending_images, reset_state,
)


# 含无效几何（自相交多边形）+ 重复要素的测试数据
_POLY = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"val": 1.5, "name": "A"},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}},
        {"type": "Feature", "properties": {"val": 2.5, "name": "B"},
         "geometry": {"type": "Polygon", "coordinates": [[[3, 0], [5, 0], [5, 2], [3, 2], [3, 0]]]}},
        # 重复要素（几何与 #1 相同）
        {"type": "Feature", "properties": {"val": 1.5, "name": "A_dup"},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}},
        # 自相交多边形（bowtie，无效几何）
        {"type": "Feature", "properties": {"val": 3.5, "name": "C"},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}},
    ],
}

_GOOD_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"v": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {"type": "Feature", "properties": {"v": 2}, "geometry": {"type": "Point", "coordinates": [1, 1]}},
        {"type": "Feature", "properties": {"v": 3}, "geometry": {"type": "Point", "coordinates": [2, 2]}},
    ],
}


def _isolate_report_quality_state(monkeypatch, tmp_path):
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
    monkeypatch.setattr(sys.modules[__name__], "_pending_images", isolated_runtime["_pending_images"])
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
    _isolate_report_quality_state(monkeypatch, tmp_path)
    reset_state()
    yield
    reset_state()


def test_report_quality_fixture_restores_existing_runtime_and_history_state(tmp_path):
    from backend.services.tool_modules import runtime

    registry, pending_images = runtime._registered_layers, runtime._pending_images
    entries, history_path = history_service._ENTRIES, history_service._CUSTOM_PATH
    registry["outside-sentinel"] = {"sentinel": True}
    pending_images.append({"path": "outside-image-sentinel"})
    entries.append({"tool": "outside-history-sentinel"})
    history_path[0] = "outside-history-path.json"
    runtime.set_current_task("outside-report-task-context")

    patcher = pytest.MonkeyPatch()
    try:
        _isolate_report_quality_state(patcher, tmp_path)
        assert runtime._registered_layers is not registry
        assert runtime._pending_images is not pending_images
        assert history_service._ENTRIES is not entries
        assert history_service._CUSTOM_PATH is not history_path
        assert T._registered_layers is runtime._registered_layers
        assert sys.modules[__name__]._registered_layers is runtime._registered_layers
        assert sys.modules[__name__]._pending_images is runtime._pending_images
    finally:
        patcher.undo()

    assert runtime._registered_layers is registry and registry["outside-sentinel"]["sentinel"]
    assert runtime._pending_images is pending_images and pending_images[-1]["path"] == "outside-image-sentinel"
    assert history_service._ENTRIES is entries and entries[-1]["tool"] == "outside-history-sentinel"
    assert history_service._CUSTOM_PATH is history_path
    assert history_path[0] == "outside-history-path.json"
    assert runtime.get_current_task_id() == "outside-report-task-context"


def _setup(name, geojson):
    _register_layer(name, geojson)
    return name


# ============================================================
# generate_analysis_report — 分析报告
# ============================================================

class TestGenerateReport:
    def test_basic_report(self):
        _setup("poly", _POLY)
        r = generate_analysis_report.invoke({"layer_name": "poly", "analysis_summary": "测试多边形图层分析"})
        assert "分析报告" in r
        assert "测试多边形图层分析" in r
        assert "统计" in r

    def test_layer_name_cannot_escape_report_directory(self, tmp_path, monkeypatch):
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(T, "_temp_output_dir", str(output_dir))
        _setup("../../escaped", _GOOD_POINTS)

        result = generate_analysis_report.invoke({"layer_name": "../../escaped"})

        reported_path = result.splitlines()[0].removeprefix("分析报告已生成并保存：")
        assert Path(reported_path).resolve().is_relative_to(output_dir.resolve())







# ============================================================
# spatial_fix_geometry — 几何修复
# ============================================================

class TestFixGeometry:
    def test_fix_invalid_polygon(self):
        _setup("poly", _POLY)
        r = spatial_fix_geometry.invoke({"layer_name": "poly"})
        assert "修复完成" in r
        assert "已修复" in r
        # 结果图层存在
        result_names = [n for n in _registered_layers if "修复" in n]
        assert len(result_names) >= 1





# ============================================================
# spatial_check_duplicates — 重复检测
# ============================================================

class TestCheckDuplicates:
    def test_geometry_duplicates_found(self):
        _setup("poly", _POLY)
        r = spatial_check_duplicates.invoke({"layer_name": "poly"})
        assert "重复" in r
        result_names = [n for n in _registered_layers if "重复" in n]
        assert len(result_names) >= 1




