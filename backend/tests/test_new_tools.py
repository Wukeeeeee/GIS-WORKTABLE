# -*- coding: utf-8 -*-
"""对标 GeoLibre 补齐的新工具测试：
zonal_statistics / add_length_field / spatial_explode / geometry_convert /
raster_resample / raster_reproject
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import numpy as np
import pytest

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

from backend.services import tools as T
from backend.services.tools import (
    tools as TOOL_LIST, _register_layer, reset_state, get_pending_state,
)


def _registry():
    return {t.name: t for t in TOOL_LIST}


@pytest.fixture(scope="module")
def dem_tif(tmp_path_factory):
    """10x10 DEM 栅格，范围 116.0-116.1 / 39.0-39.1，值 = 行号递增"""
    import rasterio
    from rasterio.transform import from_bounds
    path = str(tmp_path_factory.mktemp("raster") / "dem.tif")
    data = np.tile(np.linspace(100, 200, 10, dtype="float32"), (10, 1))
    with rasterio.open(path, "w", driver="GTiff", width=10, height=10, count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_bounds(116.0, 39.0, 116.1, 39.1, 10, 10)) as ds:
        ds.write(data, 1)
    return path


@pytest.fixture(scope="module")
def dem_tif_uploaded(dem_tif):
    """把 DEM 放到 uploads 目录（栅格工具按 uploads 文件名定位）"""
    import shutil, os
    T.init_temp_dir()  # 确保 _temp_output_dir 已初始化
    upload_dir = os.path.join(T._temp_output_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    dst = os.path.join(upload_dir, "dem.tif")
    shutil.copy(dem_tif, dst)
    return "dem"


@pytest.fixture(autouse=True)
def _clean_layers():
    reset_state()
    yield


def _reg(name, fc):
    _register_layer(name, fc)
    return name


def _poly_fc(lon_min, lat_min, lon_max, lat_max, name="zone"):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             [lon_min, lat_min], [lon_max, lat_min], [lon_max, lat_max],
             [lon_min, lat_max], [lon_min, lat_min]]]},
         "properties": {"name": name}},
    ]}


# ============================================================
# zonal_statistics 分区统计
# ============================================================

def test_zonal_statistics_basic(dem_tif_uploaded):
    reg = _registry()
    _reg("分区A", _poly_fc(116.02, 39.02, 116.06, 39.06, "低值区"))
    r = reg["zonal_statistics"].invoke(
        {"raster_layer": dem_tif_uploaded, "zone_layer": "分区A", "stat": "mean"})
    assert "分区统计完成" in r, r
    assert "分区A_分区统计" in T._registered_layers
    out = T._registered_layers["分区A_分区统计"]["geojson"]["features"][0]["properties"]
    assert out["zonal_count"] > 0
    # DEM 值 100~200 → 统计值应在此范围
    assert 100 <= out["zonal_mean"] <= 200
    # 全部四个统计量都写入
    assert all(out[k] is not None for k in ("zonal_sum", "zonal_min", "zonal_max"))


def test_zonal_statistics_zone_outside_raster(dem_tif_uploaded):
    """分区不在栅格范围内 → zonal_count=0，工具不崩且给出落区计数"""
    reg = _registry()
    _reg("远区", _poly_fc(120.0, 30.0, 120.1, 30.1, "远区"))
    r = reg["zonal_statistics"].invoke(
        {"raster_layer": dem_tif_uploaded, "zone_layer": "远区"})
    assert "0/1" in r
    out = T._registered_layers["远区_分区统计"]["geojson"]["features"][0]["properties"]
    assert out["zonal_count"] == 0


def test_zonal_statistics_missing_raster():
    r = _registry()["zonal_statistics"].invoke(
        {"raster_layer": "不存在的栅格", "zone_layer": "任意"})
    assert "未找到" in r


# ============================================================
# add_length_field 长度字段
# ============================================================

def test_add_length_field_lines():
    reg = _registry()
    line_fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "LineString", "coordinates": [[116.0, 39.5], [116.01, 39.5]]},
         "properties": {"name": "路段1"}},
    ]}
    _reg("线层", line_fc)
    r = reg["add_length_field"].invoke({"layer_name": "线层"})
    assert "已添加字段" in r and "length_km" in r
    out = T._registered_layers["线层_带长度"]["geojson"]["features"][0]["properties"]
    # 0.01 度 ≈ 0.855 km（北纬 39.5）
    assert 0.7 < out["length_km"] < 1.0


def test_add_length_field_missing_layer():
    r = _registry()["add_length_field"].invoke({"layer_name": "无此层"})
    assert "未找到" in r


# ============================================================
# spatial_explode 多部件分解
# ============================================================

def test_spatial_explode():
    reg = _registry()
    multi_fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "MultiPolygon", "coordinates": [
             [[[116.0, 39.5], [116.1, 39.5], [116.1, 39.6], [116.0, 39.6], [116.0, 39.5]]],
             [[[116.2, 39.5], [116.3, 39.5], [116.3, 39.6], [116.2, 39.6], [116.2, 39.5]]],
         ]},
         "properties": {"name": "双子"}},
    ]}
    _reg("多部件", multi_fc)
    r = reg["spatial_explode"].invoke({"layer_name": "多部件"})
    assert "1 → 2 个要素" in r
    feats = T._registered_layers["多部件_分解"]["geojson"]["features"]
    assert len(feats) == 2
    assert all(f["geometry"]["type"] == "Polygon" for f in feats)


# ============================================================
# geometry_convert 几何互转
# ============================================================

def test_geometry_convert_lines():
    reg = _registry()
    _reg("面层", _poly_fc(116.0, 39.0, 116.1, 39.1))
    r = reg["geometry_convert"].invoke({"layer_name": "面层", "target_type": "lines"})
    assert "转换完成" in r
    feats = T._registered_layers["面层_lines"]["geojson"]["features"]
    assert feats[0]["geometry"]["type"] == "LineString"


def test_geometry_convert_bounding_box():
    reg = _registry()
    _reg("散点", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [116.0, 39.0]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [117.0, 40.0]}, "properties": {}},
    ]})
    r = reg["geometry_convert"].invoke({"layer_name": "散点", "target_type": "bounding_box"})
    assert "转换完成" in r
    ring = T._registered_layers["散点_bounding_box"]["geojson"]["features"][0]["geometry"]["coordinates"][0]
    xs = [c[0] for c in ring]
    assert abs(min(xs) - 116.0) < 1e-6 and abs(max(xs) - 117.0) < 1e-6


def test_geometry_convert_convex_hull():
    reg = _registry()
    _reg("散点", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [116.0, 39.0]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [117.0, 39.0]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [116.5, 39.8]}, "properties": {}},
    ]})
    r = reg["geometry_convert"].invoke({"layer_name": "散点", "target_type": "convex_hull"})
    assert "转换完成" in r
    assert T._registered_layers["散点_convex_hull"]["geojson"]["features"][0]["geometry"]["type"] == "Polygon"


def test_geometry_convert_unknown_type():
    _reg("面层", _poly_fc(116.0, 39.0, 116.1, 39.1))
    r = _registry()["geometry_convert"].invoke({"layer_name": "面层", "target_type": "bad"})
    assert "未知 target_type" in r


# ============================================================
# raster_resample / raster_reproject
# ============================================================

def test_raster_resample(dem_tif_uploaded):
    import rasterio, os
    reg = _registry()
    r = reg["raster_resample"].invoke({"layer_name": dem_tif_uploaded, "scale_factor": 2.0})
    assert "重采样完成" in r and "5x5" in r
    upload_dir = os.path.join(T._temp_output_dir, "uploads")
    out_path = os.path.join(upload_dir, "dem_重采样.tif")
    assert os.path.exists(out_path)
    with rasterio.open(out_path) as ds:
        assert ds.width == 5 and ds.height == 5
    # dem_result 叠加 op 已推送
    ops = get_pending_state()["layer_ops"]
    assert any(op["action"] == "dem_result" and "重采样" in op["name"] for op in ops)


def test_raster_resample_missing():
    r = _registry()["raster_resample"].invoke({"layer_name": "无此栅格"})
    assert "未找到" in r


def test_raster_reproject(dem_tif_uploaded):
    """源已是 4326 → 转投影坐标系（UTM 50N）验证真正发生重投影"""
    import rasterio, os
    reg = _registry()
    r = reg["raster_reproject"].invoke(
        {"layer_name": dem_tif_uploaded, "target_crs": "EPSG:32650"})
    assert "重投影完成" in r
    upload_dir = os.path.join(T._temp_output_dir, "uploads")
    out_path = os.path.join(upload_dir, "dem_重投影.tif")
    assert os.path.exists(out_path)
    with rasterio.open(out_path) as ds:
        assert ds.crs.to_epsg() == 32650


# ============================================================
# 注册与守卫
# ============================================================

def test_new_tools_registered():
    names = {t.name for t in TOOL_LIST}
    for n in ("zonal_statistics", "add_length_field", "spatial_explode",
              "geometry_convert", "raster_resample", "raster_reproject"):
        assert n in names


def test_new_tool_outputs_pass_geo_qa():
    """新工具产出图层经过质量自检：正常数据零警告"""
    reset_state()
    _reg("面层", _poly_fc(116.0, 39.0, 116.1, 39.1))
    _registry()["geometry_convert"].invoke({"layer_name": "面层", "target_type": "lines"})
    st = get_pending_state()
    assert st["qa_warnings"] == []
    assert any(l["name"] == "面层_lines" for l in st["layers"])
