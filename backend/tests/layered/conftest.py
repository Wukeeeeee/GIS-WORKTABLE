# -*- coding: utf-8 -*-
"""分层测试共享 Fixtures 与环境准备

确保测试复用生产代码运行环境，不割裂 AI Core 与 GIS 工具链。
"""
import os
import sys
import threading
import pytest
from fastapi.testclient import TestClient

# 修复 PROJ_LIB 冲突
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

# 确保项目根目录在 sys.path 中
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.main import app
from backend.services import task_manager, tools as _tools_module
from backend.services.tools import reset_state

@pytest.fixture(scope="session")
def client():
    """FastAPI 真实生产应用 TestClient"""
    return TestClient(app)

@pytest.fixture(autouse=True)
def clean_gis_state(monkeypatch, tmp_path):
    """每例在临时 runtime 状态中运行，避免 reset_state 清掉宿主进程状态。"""
    from backend.services.tool_modules import runtime

    test_output_dir = str(tmp_path / "tool-runtime")
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
        "_temp_output_dir": test_output_dir,
        "_workspace_dir": str(tmp_path / "workspace"),
        "_raster_output_scope": threading.local(),
        "_active_project_id": None,
        "_current_task_id": "",
        "_last_user_message": "",
        "_current_run_id": "",
        "_conversation_context": "",
        "_session_locks": {},
    }
    for path in (
        isolated_runtime["_temp_output_dir"],
        os.path.join(isolated_runtime["_temp_output_dir"], "output"),
        isolated_runtime["_workspace_dir"],
    ):
        os.makedirs(path, exist_ok=True)
    with runtime._state_lock, runtime._session_locks_guard:
        for name, value in isolated_runtime.items():
            monkeypatch.setattr(_tools_module, name, value)
    with task_manager._lock:
        monkeypatch.setattr(task_manager, "_BASE_DIR", str(tmp_path / "tasks"))
        monkeypatch.setattr(task_manager, "_tasks", {})
        monkeypatch.setattr(task_manager, "_session_active", {})
    reset_state()
    yield
    reset_state()

@pytest.fixture
def sample_polygon_geojson():
    """标准测试多边形 GeoJSON"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[118.75, 32.05], [118.79, 32.05], [118.79, 32.09], [118.75, 32.09], [118.75, 32.05]]]
                },
                "properties": {"name": "南京市鼓楼区", "gdp": 2245.8, "year": 2025}
            }
        ]
    }

@pytest.fixture
def sample_multi_polygon_geojson():
    """标准多要素测试 GeoJSON"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[118.75, 32.05], [118.79, 32.05], [118.79, 32.09], [118.75, 32.09], [118.75, 32.05]]]
                },
                "properties": {"name": "鼓楼区", "gdp": 2245.8}
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[118.80, 32.03], [118.85, 32.03], [118.85, 32.08], [118.80, 32.08], [118.80, 32.03]]]
                },
                "properties": {"name": "玄武区", "gdp": 1350.2}
            }
        ]
    }
