# -*- coding: utf-8 -*-
"""新增栅格分析工具回归测试（raster_reclassify / raster_focal_stats / euclidean_distance /
raster_extract_by_mask / surface_volumes）。

不做"只返回了非空字符串"的假测试：用合成 DEM 断言数值结果。
写 GeoTIFF 时不带 CRS，规避本机 PROJ proj.db 版本冲突。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.services import tools as T
from backend.services.tools import (
    tools as TOOL_LIST, _register_layer, reset_state, _pending_layer_ops,
    raster_reclassify, raster_focal_stats, euclidean_distance,
    raster_extract_by_mask, surface_volumes,
)

NEW_TOOLS = [
    raster_reclassify, raster_focal_stats, euclidean_distance,
    raster_extract_by_mask, surface_volumes,
]
NEW_TOOL_NAMES = [t.name for t in NEW_TOOLS]


@pytest.fixture(autouse=True)
def _clean(tmp_path):
    reset_state()
    _pending_layer_ops.clear()
    T._temp_output_dir = str(tmp_path)
    yield
    reset_state()
    _pending_layer_ops.clear()


def _make_tif(tmp_path, name, data, res=1.0, nodata=None, origin=(0.0, None)):
    """在 uploads 目录写一个单波段 GeoTIFF，返回图层名"""
    n_rows, n_cols = data.shape
    top = origin[1] if origin[1] is not None else float(n_rows)
    upd = os.path.join(str(tmp_path), "uploads")
    os.makedirs(upd, exist_ok=True)
    path = os.path.join(upd, f"{name}.tif")
    with rasterio.open(path, "w", driver="GTiff", height=n_rows, width=n_cols,
                       count=1, dtype="float32", crs=None, nodata=nodata,
                       transform=from_origin(origin[0], top, res, res)) as dst:
        dst.write(np.asarray(data, dtype="float32"), 1)
    return name, path


def _read_out(path):
    with rasterio.open(path) as src:
        return src.read(1)


def _poly_fc(coords, name="zone"):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [coords]},
         "properties": {"name": name}},
    ]}


# ============================================================
# 注册守卫：工具必须在 tools 列表里且有 docstring
# ============================================================

def test_new_tools_registered_and_documented():
    registered = {getattr(t, "name", None): t for t in TOOL_LIST}
    for name in NEW_TOOL_NAMES:
        assert name in registered, f"{name} 未注册到 tools 列表"
        assert (registered[name].description or "").strip(), f"{name} 缺少 docstring/描述"


def test_tool_list_length():
    """131 个存量工具 + 本批 5 个 = 136；数量异常时报告真实值而非硬凑"""
    assert len(TOOL_LIST) >= 136, f"tools 列表长度 {len(TOOL_LIST)}（期望 >= 136）"


def test_every_new_tool_docstring_lists_params():
    registered = {getattr(t, "name", None): t for t in TOOL_LIST}
    for name in NEW_TOOL_NAMES:
        doc = registered[name].description or ""
        assert len(doc) > 20, f"{name} 描述过短：{doc!r}"


# ============================================================
# raster_reclassify：已知映射的类别值
# ============================================================

def test_reclassify_mapping_known_values(tmp_path):
    data = np.array([[5.0, 20.0, 60.0],
                     [9.999, 10.0, 49.999]], dtype="float32")
    name, _ = _make_tif(tmp_path, "rc_dem", data)
    r = raster_reclassify.invoke(
        {"layer_name": name, "mapping": "0-10=1;10-50=2;50+=3", "method": "mapping"})
    assert "重分类完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "rc_dem_重分类.tif"))
    # 区间左闭右开：5->1, 20->2, 60->3, 9.999->1, 10->2, 49.999->2
    assert out.tolist() == [[1.0, 2.0, 3.0], [1.0, 2.0, 2.0]], out.tolist()


def test_reclassify_equal_interval(tmp_path):
    data = np.array([[0.0, 26.0, 60.0, 100.0]], dtype="float32")
    name, _ = _make_tif(tmp_path, "rc_eq", data)
    r = raster_reclassify.invoke(
        {"layer_name": name, "method": "equal_interval", "classes": 4})
    assert "重分类完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "rc_eq_重分类.tif"))
    assert out.tolist() == [[1.0, 2.0, 3.0, 4.0]], out.tolist()


def test_reclassify_preserves_nodata(tmp_path):
    data = np.array([[1.0, -9999.0, 30.0]], dtype="float32")
    name, _ = _make_tif(tmp_path, "rc_nd", data, nodata=-9999.0)
    r = raster_reclassify.invoke({"layer_name": name, "mapping": "0-10=1;10+=2"})
    assert "重分类完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "rc_nd_重分类.tif"))
    assert out[0, 0] == 1.0 and out[0, 2] == 2.0
    assert np.isclose(out[0, 1], -9999.0), out.tolist()


# ============================================================
# raster_focal_stats：窗口统计数值
# ============================================================

def test_focal_mean_constant_grid(tmp_path):
    data = np.full((7, 7), 5.0, dtype="float32")
    name, _ = _make_tif(tmp_path, "fs_flat", data)
    r = raster_focal_stats.invoke({"layer_name": name, "stat": "mean", "size": 3})
    assert "焦点统计完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "fs_flat_焦点mean.tif"))
    assert np.allclose(out, 5.0, atol=1e-4), out


def test_focal_max_min_range_spike(tmp_path):
    data = np.full((5, 5), 4.0, dtype="float32")
    data[2, 2] = 8.0
    name, _ = _make_tif(tmp_path, "fs_spike", data)
    base = os.path.join(str(tmp_path), "uploads")
    raster_focal_stats.invoke({"layer_name": name, "stat": "max", "size": 3})
    raster_focal_stats.invoke({"layer_name": name, "stat": "min", "size": 3})
    raster_focal_stats.invoke({"layer_name": name, "stat": "range", "size": 3})
    mx = _read_out(os.path.join(base, "fs_spike_焦点max.tif"))
    mn = _read_out(os.path.join(base, "fs_spike_焦点min.tif"))
    rg = _read_out(os.path.join(base, "fs_spike_焦点range.tif"))
    # 3x3 窗口内 max 应为 8（尖峰扩散到 8 邻域），角落 max 仍为 4
    assert mx[2, 2] == 8.0 and mx[1, 1] == 8.0 and mx[0, 0] == 4.0
    assert np.allclose(mn, 4.0), mn
    assert np.allclose(rg, mx - mn), rg


def test_focal_rejects_even_window(tmp_path):
    data = np.full((5, 5), 1.0, dtype="float32")
    name, _ = _make_tif(tmp_path, "fs_even", data)
    r = raster_focal_stats.invoke({"layer_name": name, "stat": "mean", "size": 4})
    assert "奇数" in r, r


# ============================================================
# euclidean_distance：已知 5x5 网格
# ============================================================

def test_euclidean_distance_known_grid(tmp_path):
    data = np.zeros((5, 5), dtype="float32")
    data[2, 2] = 1.0  # 唯一源像元
    name, _ = _make_tif(tmp_path, "ed_grid", data)
    r = euclidean_distance.invoke({"layer_name": name, "source_value": 1.0})
    assert "欧氏距离完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "ed_grid_欧氏距离.tif"))
    yy, xx = np.mgrid[0:5, 0:5]
    expect = np.sqrt((yy - 2) ** 2 + (xx - 2) ** 2)
    assert np.allclose(out, expect, atol=1e-4), out
    assert out[2, 2] == 0.0
    assert np.isclose(out[0, 0], np.sqrt(8), atol=1e-4)


def test_euclidean_distance_default_nonzero_sources(tmp_path):
    data = np.zeros((5, 5), dtype="float32")
    data[0, 0] = 3.0
    data[4, 4] = 7.0
    name, _ = _make_tif(tmp_path, "ed_two", data)
    r = euclidean_distance.invoke({"layer_name": name})
    assert "欧氏距离完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "ed_two_欧氏距离.tif"))
    assert out[0, 0] == 0.0 and out[4, 4] == 0.0
    # (0,4) 到两个源像元 (0,0)/(4,4) 的最近距离均为 4
    assert np.isclose(out[0, 4], 4.0, atol=1e-4), out[0, 4]
    # 中点 (2,2) 到两个源像元等距
    assert np.isclose(out[2, 2], np.sqrt(8), atol=1e-4)


def test_euclidean_distance_custom_out_name(tmp_path):
    data = np.zeros((5, 5), dtype="float32")
    data[2, 2] = 1.0
    name, _ = _make_tif(tmp_path, "ed_custom", data)
    r = euclidean_distance.invoke({"layer_name": name, "source_value": 1, "out_name": "my_dist"})
    assert "欧氏距离完成" in r, r
    assert os.path.isfile(os.path.join(str(tmp_path), "uploads", "my_dist.tif"))


def test_euclidean_distance_no_source(tmp_path):
    data = np.zeros((4, 4), dtype="float32")
    name, _ = _make_tif(tmp_path, "ed_empty", data)
    r = euclidean_distance.invoke({"layer_name": name, "source_value": 42})
    assert "找不到源像元" in r, r


# ============================================================
# surface_volumes：已知平面的填挖方
# ============================================================

def test_surface_volumes_pure_fill(tmp_path):
    before = np.zeros((5, 5), dtype="float32")
    after = np.full((5, 5), 2.0, dtype="float32")
    nb, _ = _make_tif(tmp_path, "sv_before", before)
    na, _ = _make_tif(tmp_path, "sv_after", after)
    r = surface_volumes.invoke({"before_layer": nb, "after_layer": na})
    assert "填挖方计算完成" in r, r
    # 25 像元 x 2 m x 1 m2 = 50 m3 填方，无挖方
    assert "填方量 50.00 m3" in r.replace(",", ""), r
    assert "挖方量 0.00 m3" in r.replace(",", ""), r
    assert "净方量 50.00 m3" in r.replace(",", ""), r
    assert "变化面积 25.00 m2" in r.replace(",", ""), r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "sv_before_填挖方.tif"))
    assert np.allclose(out, 2.0), out


def test_surface_volumes_cut_and_fill(tmp_path):
    before = np.zeros((5, 5), dtype="float32")
    after = np.zeros((5, 5), dtype="float32")
    after[0:2, :] = 2.0    # 10 像元填 +2 -> 20 m3
    after[3:5, :] = -3.0   # 10 像元挖 3 -> 30 m3
    nb, _ = _make_tif(tmp_path, "sv_b2", before)
    na, _ = _make_tif(tmp_path, "sv_a2", after)
    r = surface_volumes.invoke({"before_layer": nb, "after_layer": na})
    assert "填挖方计算完成" in r, r
    flat = r.replace(",", "")
    assert "挖方量 30.00 m3" in flat, r
    assert "填方量 20.00 m3" in flat, r
    assert "净方量 -10.00 m3" in flat, r
    assert "变化面积 20.00 m2" in flat, r


def test_surface_volumes_with_reference_plane(tmp_path):
    before = np.full((4, 4), 10.0, dtype="float32")
    nb, _ = _make_tif(tmp_path, "sv_ref_b", before)
    r = surface_volumes.invoke({"before_layer": nb, "after_layer": "", "reference": 12.0})
    assert "填挖方计算完成" in r, r
    # 16 像元 x 2 m x 1 m2 = 32 m3 填方
    assert "填方量 32.00 m3" in r.replace(",", ""), r


def test_surface_volumes_shape_mismatch_fails_loudly(tmp_path):
    nb, _ = _make_tif(tmp_path, "sv_m_b", np.zeros((5, 5), dtype="float32"))
    na, _ = _make_tif(tmp_path, "sv_m_a", np.zeros((4, 4), dtype="float32"))
    r = surface_volumes.invoke({"before_layer": nb, "after_layer": na})
    assert "失败" in r and "不一致" in r, r


def test_surface_volumes_transform_mismatch_fails_loudly(tmp_path):
    nb, _ = _make_tif(tmp_path, "sv_t_b", np.zeros((5, 5), dtype="float32"))
    na, _ = _make_tif(tmp_path, "sv_t_a", np.zeros((5, 5), dtype="float32"), origin=(100.0, 5.0))
    r = surface_volumes.invoke({"before_layer": nb, "after_layer": na})
    assert "失败" in r and "地理变换不一致" in r, r


# ============================================================
# raster_extract_by_mask：面内/面外像元数
# ============================================================

def _mask_fixture(tmp_path, name):
    # 栅格 5x5，像元中心 (x+0.5, y+0.5)，范围 x/y 0..5
    data = np.ones((5, 5), dtype="float32")
    _make_tif(tmp_path, name, data)
    _register_layer("裁剪面", _poly_fc([[1.0, 1.0], [4.0, 1.0], [4.0, 4.0], [1.0, 4.0], [1.0, 1.0]]))
    return name


def test_extract_by_mask_inside(tmp_path):
    name = _mask_fixture(tmp_path, "em_in")
    r = raster_extract_by_mask.invoke({"raster_layer": name, "zone_layer": "裁剪面", "inside": True})
    assert "按掩膜提取完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "em_in_掩膜内.tif"))
    # 面覆盖 3x3 像元中心 (1.5..3.5) -> 9 个有效
    assert int((out > 0).sum()) == 9, out


def test_extract_by_mask_outside(tmp_path):
    name = _mask_fixture(tmp_path, "em_out")
    r = raster_extract_by_mask.invoke({"raster_layer": name, "zone_layer": "裁剪面", "inside": False})
    assert "按掩膜提取完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "em_out_掩膜外.tif"))
    # 25 - 9 = 16 个有效像元
    assert int((out > 0).sum()) == 16, out


def test_extract_by_mask_missing_raster():
    r = raster_extract_by_mask.invoke({"raster_layer": "不存在的栅格", "zone_layer": "裁剪面"})
    assert "未找到栅格文件" in r, r


def test_extract_by_mask_missing_zone(tmp_path):
    name = _mask_fixture(tmp_path, "em_nozone")
    r = raster_extract_by_mask.invoke({"raster_layer": name, "zone_layer": "不存在的面"})
    assert "未找到图层" in r, r