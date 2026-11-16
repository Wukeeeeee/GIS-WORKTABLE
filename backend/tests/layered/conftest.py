# -*- coding: utf-8 -*-
"""分层测试共享 Fixtures 与环境准备

确保测试复用生产代码运行环境，不割裂 AI Core 与 GIS 工具链。
"""
import os
import sys
import pytest
from fastapi.testclient import TestClient

# 确保项目根目录在 sys.path 中
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.main import app
from backend.services import task_manager, tools as _tools_module

@pytest.fixture(scope="session")
def client():
    """FastAPI 真实生产应用 TestClient"""
    return TestClient(app)

@pytest.fixture(autouse=True)
def clean_gis_state(monkeypatch, tmp_path, tool_runtime_isolator):
    """每例复用公共 runtime/task 隔离，并保留 layered 的工具输出目录约定。"""
    tool_runtime_isolator(monkeypatch, tmp_path / "runtime-state")
    test_output_dir = str(tmp_path / "tool-runtime")
    monkeypatch.setattr(_tools_module, "_temp_output_dir", test_output_dir)
    workspace_dir = str(tmp_path / "workspace")
    monkeypatch.setattr(_tools_module, "_workspace_dir", workspace_dir)
    with task_manager._lock:
        monkeypatch.setattr(task_manager, "_BASE_DIR", str(tmp_path / "tasks"))
    for path in (
        test_output_dir,
        os.path.join(test_output_dir, "output"),
        workspace_dir,
    ):
        os.makedirs(path, exist_ok=True)
    yield

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
