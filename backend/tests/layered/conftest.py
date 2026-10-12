# -*- coding: utf-8 -*-
"""分层测试共享 Fixtures 与环境准备

确保测试复用生产代码运行环境，不割裂 AI Core 与 GIS 工具链。
"""
import os
import sys
import json
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
from backend.services.tools import init_temp_dir, reset_state, _register_layer, get_registered_layers

@pytest.fixture(scope="session")
def client():
    """FastAPI 真实生产应用 TestClient"""
    return TestClient(app)

@pytest.fixture(autouse=True)
def clean_gis_state():
    """每个测试前后清理 GIS 临时状态，保证测试独立性"""
    init_temp_dir()
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
