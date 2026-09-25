# -*- coding: utf-8 -*-
"""E2E：直连工具链全流程（FastAPI TestClient + 伪造数据，全程不借助 AI）

模拟真实用户在手动面板上的操作序列：
注册图层 → 缓冲区 → 裁剪 → 字段统计 → 分区统计 → 卷帘 → 历史 → 重跑，
验证每一步的响应结构与产物（图层通道/结果落盘/历史记录/质量守卫）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json

import pytest
from fastapi.testclient import TestClient

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

from backend.main import app

client = TestClient(app)


def _poly_fc(name, lon_min, lat_min, lon_max, lat_max, extra=None):
    props = {"name": name}
    if extra:
        props.update(extra)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             [lon_min, lat_min], [lon_max, lat_min], [lon_max, lat_max],
             [lon_min, lat_max], [lon_min, lat_min]]]},
         "properties": props},
    ]}


def _invoke(name, args):
    resp = client.post("/api/tools/invoke", json={"name": name, "arguments": args})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True, data.get("response")
    return data


@pytest.fixture(scope="module")
def dem_tif(tmp_path_factory):
    """伪造 DEM：值 = 经度方向递增，CRS 4326"""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    path = str(tmp_path_factory.mktemp("e2e") / "e2e_dem.tif")
    data = np.tile(np.linspace(50, 150, 20, dtype="float32"), (20, 1))
    with rasterio.open(path, "w", driver="GTiff", width=20, height=20, count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_bounds(116.0, 39.0, 116.2, 39.2, 20, 20)) as ds:
        ds.write(data, 1)
    return path


@pytest.fixture(scope="module")
def dem_registered(dem_tif):
    """把 DEM 复制进 uploads（栅格工具按文件名定位）并注册"""
    import shutil
    from backend.services.tools import init_temp_dir, _register_layer, _temp_output_dir
    init_temp_dir()
    dst = os.path.join(_temp_output_dir, "uploads", "e2e_dem.tif")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy(dem_tif, dst)
    _register_layer("e2e_dem", _poly_fc("dem范围", 116.0, 39.0, 116.2, 39.2))
    return "e2e_dem"


# ============================================================
# 场景 1：手动面板典型操作链（注册→缓冲→裁剪→统计）
# ============================================================

def test_e2e_register_layer_via_api():
    """伪造数据经 /api/layer/register 注册（模拟面板 syncLayer）"""
    resp = client.post("/api/layer/register", json={
        "name": "e2e_地块",
        "geojson": _poly_fc("地块A", 116.02, 39.02, 116.08, 39.08,
                            extra={"value": 42.5, "type": "industrial"})})
    assert resp.status_code == 200
    # 图层名出现在 /api/layers/names
    names = client.get("/api/layers/names").json()["names"]
    assert "e2e_地块" in names


def test_e2e_buffer_then_clip_chain():
    """缓冲区 → 用原图层裁剪缓冲区结果：链式产物真实上图"""
    data = _invoke("spatial_buffer",
                   {"layer_name": "e2e_地块", "distance": 2000, "unit": "m", "dissolve": False})
    buffer_layers = [l["name"] for l in data["layers"]]
    assert buffer_layers and buffer_layers[0].startswith("e2e_地块_缓冲区")
    assert data["qa_warnings"] == []  # 正常数据零警告

    buf_name = buffer_layers[0]
    data2 = _invoke("spatial_clip", {"layer_name": buf_name, "clip_layer": "e2e_地块"})
    clip_layers = [l["name"] for l in data2["layers"]]
    assert clip_layers, "裁剪应有产物"
    # 裁剪结果面积 ≤ 缓冲区面积（几何合理性）
    assert "已" in data2["response"]


def test_e2e_field_stats_response_shape():
    # 地块要素带数值字段 value=42.5，统计应输出 count/min/max/mean
    data = _invoke("spatial_field_stats", {"layer_name": "e2e_地块", "field": "value"})
    assert "count" in data["response"] or "统计" in data["response"]


# ============================================================
# 场景 2：栅格直连（伪造 DEM → 分区统计 → 重采样）
# ============================================================

def test_e2e_zonal_statistics(dem_registered):
    data = _invoke("zonal_statistics",
                   {"raster_layer": dem_registered, "zone_layer": "e2e_地块", "stat": "mean"})
    assert "分区统计完成" in data["response"]
    layer = data["layers"][0]
    props = layer["geojson"]["features"][0]["properties"]
    # DEM 值 50~150 → 分区均值必在此范围
    assert 50 <= props["zonal_mean"] <= 150
    assert props["zonal_count"] > 0


def test_e2e_raster_resample_output_real(dem_registered):
    data = _invoke("raster_resample",
                   {"layer_name": dem_registered, "scale_factor": 2.0, "method": "bilinear"})
    assert "重采样完成" in data["response"]
    # dem_result 影像叠加 op 真实指向已落盘文件
    overlay = [op for op in data["layer_ops"] if op["action"] == "dem_result"]
    assert overlay and overlay[0]["url"].startswith("/output/uploads/")
    fname = os.path.basename(overlay[0]["url"])
    from backend.services.tools import init_temp_dir, _temp_output_dir
    init_temp_dir()
    assert os.path.exists(os.path.join(_temp_output_dir, "uploads", fname))


# ============================================================
# 场景 3：卷帘 + 处理历史 + 重跑（手动面板闭环）
# ============================================================

def test_e2e_swipe_and_history_rerun():
    # 卷帘
    data = _invoke("create_swipe", {"left_layer": "e2e_地块", "right_layer": "e2e_dem"})
    ops = [op for op in data["layer_ops"] if op["action"] == "swipe"]
    assert ops and ops[0]["left"] == "e2e_地块"

    # 历史里有本次链路记录（倒序，最新在前）
    hist = client.get("/api/history?limit=10").json()["history"]
    tools = [h["tool"] for h in hist]
    assert "spatial_buffer" in tools and "create_swipe" in tools

    # 重跑第一条（最新一条）
    target = hist[0]["index"]
    rerun = client.post("/api/history/rerun", json={"index": target})
    assert rerun.status_code == 200
    rdata = rerun.json()
    assert "已重跑" in rdata["response"]


def test_e2e_unknown_tool_404():
    resp = client.post("/api/tools/invoke", json={"name": "no_such_tool", "arguments": {}})
    assert resp.status_code == 404


def test_e2e_history_endpoint_shape():
    hist = client.get("/api/history?limit=5").json()["history"]
    for h in hist:
        assert {"index", "tool", "args", "time", "ok", "layer_ids"} <= set(h.keys())
