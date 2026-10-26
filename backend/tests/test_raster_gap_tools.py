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
from pydantic import ValidationError
from rasterio.transform import from_origin

from backend.services import tools as T
from backend.services.tools import (
    tools as TOOL_LIST, _register_layer, reset_state, _pending_layer_ops,
    raster_reclassify, raster_focal_stats, euclidean_distance,
    raster_extract_by_mask, raster_to_feature, surface_volumes,
    cost_distance, least_cost_path,
)

NEW_TOOLS = [
    raster_reclassify, raster_focal_stats, euclidean_distance,
    raster_extract_by_mask, surface_volumes,
]
NEW_TOOL_NAMES = [t.name for t in NEW_TOOLS]


@pytest.fixture(autouse=True)
def _clean(tmp_path):
    previous_output_dir = T._temp_output_dir
    reset_state()
    _pending_layer_ops.clear()
    T._temp_output_dir = str(tmp_path)
    yield
    reset_state()
    _pending_layer_ops.clear()
    T._temp_output_dir = previous_output_dir


def _make_tif(tmp_path, name, data, res=1.0, nodata=None, origin=(0.0, None), crs=None):
    """在 uploads 目录写一个单波段 GeoTIFF，返回图层名"""
    n_rows, n_cols = data.shape
    top = origin[1] if origin[1] is not None else float(n_rows)
    upd = os.path.join(str(tmp_path), "uploads")
    os.makedirs(upd, exist_ok=True)
    path = os.path.join(upd, f"{name}.tif")
    with rasterio.open(path, "w", driver="GTiff", height=n_rows, width=n_cols,
                       count=1, dtype="float32", crs=crs, nodata=nodata,
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


@pytest.mark.parametrize("method", ["equal_interval", "quantile"])
@pytest.mark.parametrize("classes", [1, 0, -2])
def test_reclassify_rejects_invalid_class_count(tmp_path, method, classes):
    name, _ = _make_tif(tmp_path, f"invalid_count_{method}", np.array([[1.0, 2.0, 3.0]]))

    result = raster_reclassify.invoke({
        "layer_name": name, "method": method, "classes": classes,
    })

    assert "分级数必须是大于等于 2 的有限整数" in result
    assert _pending_layer_ops == []
    assert not os.path.exists(os.path.join(str(tmp_path), "uploads", f"{name}_重分类.tif"))


@pytest.mark.parametrize("classes", [2.5, float("inf"), float("nan")])
def test_reclassify_schema_rejects_noninteger_class_count(tmp_path, classes):
    name, _ = _make_tif(tmp_path, "invalid_fractional_count", np.array([[1.0, 2.0, 3.0]]))

    with pytest.raises(ValidationError):
        raster_reclassify.invoke({
            "layer_name": name, "method": "quantile", "classes": classes,
        })

    assert _pending_layer_ops == []


@pytest.mark.parametrize("mapping", ["0-10=nan", "0-10=inf", "5-5=1"])
def test_reclassify_rejects_nonfinite_values_and_empty_ranges(tmp_path, mapping):
    name, _ = _make_tif(tmp_path, "invalid_mapping", np.array([[1.0, 6.0]]))

    result = raster_reclassify.invoke({"layer_name": name, "mapping": mapping})

    assert "mapping 为空或格式不正确" in result
    assert _pending_layer_ops == []
    assert not os.path.exists(os.path.join(str(tmp_path), "uploads", f"{name}_重分类.tif"))


def test_reclassify_rejects_unknown_method_instead_of_falling_back_to_mapping(tmp_path):
    name, _ = _make_tif(tmp_path, "invalid_method", np.array([[1.0, 2.0, 3.0]]))

    result = raster_reclassify.invoke({
        "layer_name": name, "method": "quantilee", "mapping": "0-10=1",
    })

    assert "method 必须是 mapping、equal_interval 或 quantile" in result
    assert _pending_layer_ops == []


def test_reclassify_preserves_nodata(tmp_path):
    data = np.array([[1.0, -9999.0, 30.0]], dtype="float32")
    name, _ = _make_tif(tmp_path, "rc_nd", data, nodata=-9999.0)
    r = raster_reclassify.invoke({"layer_name": name, "mapping": "0-10=1;10+=2"})
    assert "重分类完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "rc_nd_重分类.tif"))
    assert out[0, 0] == 1.0 and out[0, 2] == 2.0
    assert np.isclose(out[0, 1], -9999.0), out.tolist()


def test_reclassify_uses_registered_layer_name_for_project_asset(tmp_path):
    data = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype="float32")
    _, source_path = _make_tif(tmp_path, "project_asset_5fc9a1", data)
    display_name = "可读坡度结果"
    T._register_raster_layer(
        display_name,
        {"bounds": [0.0, 0.0, 3.0, 2.0], "crs": "EPSG:4326"},
        source_path,
    )

    result = raster_reclassify.invoke(
        {"layer_name": display_name, "method": "quantile", "classes": 3})

    expected_name = f"{display_name}_重分类"
    assert "重分类完成" in result, result
    assert os.path.isfile(os.path.join(str(tmp_path), "uploads", expected_name + ".tif"))
    assert _pending_layer_ops[-1]["layer_name"] == expected_name


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


@pytest.mark.parametrize("size", [1, 9, -1])
def test_focal_rejects_unsupported_odd_window_without_clamping(tmp_path, size):
    name, _ = _make_tif(tmp_path, "fs_unsupported_size", np.ones((5, 5), dtype="float32"))

    result = raster_focal_stats.invoke({"layer_name": name, "stat": "mean", "size": size})

    assert "仅支持 3、5、7" in result
    assert _pending_layer_ops == []
    assert not os.path.exists(os.path.join(str(tmp_path), "uploads", f"{name}_焦点mean.tif"))


def test_focal_majority_returns_a_value_from_the_input_raster(tmp_path):
    data = np.full((3, 3), 1.0000001, dtype="float32")
    name, _ = _make_tif(tmp_path, "fs_majority_precision", data)

    result = raster_focal_stats.invoke({"layer_name": name, "stat": "majority", "size": 3})

    assert "焦点统计完成" in result, result
    out = _read_out(os.path.join(str(tmp_path), "uploads", f"{name}_焦点majority.tif"))
    assert out[1, 1] == data[1, 1]


def test_focal_nodata_uses_exact_sentinel_not_tolerance(tmp_path):
    nodata = -9999.0
    data = np.full((3, 3), nodata, dtype="float32")
    data[0, 0] = -9998.95  # Valid value, although np.isclose(..., -9999) is true.
    data[1, 1] = 0.0
    name, _ = _make_tif(tmp_path, "fs_near_nodata", data, nodata=nodata)

    result = raster_focal_stats.invoke({"layer_name": name, "stat": "mean", "size": 3})

    assert "焦点统计完成" in result, result
    out = _read_out(os.path.join(str(tmp_path), "uploads", f"{name}_焦点mean.tif"))
    assert np.isclose(out[1, 1], (-9998.95 + 0.0) / 2, atol=1e-3)
    assert _pending_layer_ops[-1]["raster"]["valid_pixel_ratio"] == pytest.approx(2 / 9)


def test_focal_output_uses_registered_layer_name_for_project_asset(tmp_path):
    data = np.arange(9, dtype="float32").reshape(3, 3)
    _, source_path = _make_tif(tmp_path, "project_asset_focal_hash", data)
    display_name = "可读高程图层"
    T._register_raster_layer(
        display_name,
        {"bounds": [0.0, 0.0, 3.0, 3.0], "crs": "EPSG:4326"},
        source_path,
    )

    result = raster_focal_stats.invoke({
        "layer_name": display_name, "stat": "mean", "size": 3,
    })

    expected_name = f"{display_name}_焦点mean"
    assert "焦点统计完成" in result, result
    assert os.path.isfile(os.path.join(str(tmp_path), "uploads", expected_name + ".tif"))
    assert _pending_layer_ops[-1]["layer_name"] == expected_name


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
    with rasterio.open(os.path.join(str(tmp_path), "uploads", "ed_grid_欧氏距离.tif")) as src:
        assert src.tags()["VALUE_UNITS"] == "栅格单位（CRS 未定义）"
        assert "缺少 CRS" in src.tags()["QUALITY_NOTE"]


def test_euclidean_distance_geographic_crs_fails_with_reprojection_guidance(tmp_path):
    data = np.zeros((5, 5), dtype="float32")
    data[2, 2] = 1.0
    os.makedirs(os.path.join(str(tmp_path), "uploads"), exist_ok=True)
    path = os.path.join(str(tmp_path), "uploads", "ed_geographic.tif")
    with rasterio.open(path, "w", driver="GTiff", height=5, width=5, count=1,
                       dtype="float32", crs="EPSG:4326", transform=from_origin(112, 29, 0.01, 0.01)) as dst:
        dst.write(data, 1)
    result = euclidean_distance.invoke({"layer_name": "ed_geographic", "source_value": 1.0})
    assert "不能把角度当作地面距离" in result
    assert not os.path.exists(os.path.join(str(tmp_path), "uploads", "ed_geographic_欧氏距离.tif"))


def test_euclidean_distance_reports_projected_crs_units(tmp_path):
    data = np.zeros((5, 5), dtype="float32")
    data[2, 2] = 1.0
    os.makedirs(os.path.join(str(tmp_path), "uploads"), exist_ok=True)
    path = os.path.join(str(tmp_path), "uploads", "ed_projected.tif")
    with rasterio.open(path, "w", driver="GTiff", height=5, width=5, count=1,
                       dtype="float32", crs="EPSG:3857", transform=from_origin(0, 5, 2, 2)) as dst:
        dst.write(data, 1)
        dst.update_tags(VALUE_UNITS="m")
    result = euclidean_distance.invoke({"layer_name": "ed_projected", "source_value": 1.0})
    assert "最大距离 5.65685 metre" in result, result
    with rasterio.open(os.path.join(str(tmp_path), "uploads", "ed_projected_欧氏距离.tif")) as src:
        assert src.tags()["VALUE_UNITS"] == "metre"


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


def test_euclidean_distance_preserves_valid_pixels_near_nodata(tmp_path):
    nodata = -9999.0
    data = np.full((3, 3), nodata, dtype="float32")
    data[0, 0] = -9998.95
    data[1, 1] = 0.0
    name, _ = _make_tif(tmp_path, "ed_near_nodata", data, nodata=nodata)

    result = euclidean_distance.invoke({
        "layer_name": name, "source_value": -9998.95,
    })

    assert "欧氏距离完成" in result, result
    out = _read_out(os.path.join(str(tmp_path), "uploads", f"{name}_欧氏距离.tif"))
    assert out[0, 0] == 0.0
    assert out[1, 1] == pytest.approx(np.sqrt(2), abs=1e-4)
    assert np.isclose(out[2, 2], nodata)
    assert _pending_layer_ops[-1]["raster"]["valid_pixel_ratio"] == pytest.approx(2 / 9)


def test_euclidean_distance_source_value_does_not_use_magnitude_scaled_tolerance(tmp_path):
    data = np.array([[1_000_000.0, 1_000_005.0, 0.0]], dtype="float32")
    name, _ = _make_tif(tmp_path, "ed_large_source_value", data)

    result = euclidean_distance.invoke({
        "layer_name": name, "source_value": 1_000_000.0,
    })

    assert "源像元 1 个" in result, result
    out = _read_out(os.path.join(str(tmp_path), "uploads", f"{name}_欧氏距离.tif"))
    assert out[0, 0] == 0.0
    assert out[0, 1] == 1.0


def test_euclidean_distance_uses_registered_layer_name_for_project_asset(tmp_path):
    data = np.zeros((5, 5), dtype="float32")
    data[2, 2] = 1.0
    _, source_path = _make_tif(tmp_path, "project_asset_distance_hash", data)
    display_name = "可读成本栅格"
    T._register_raster_layer(
        display_name,
        {"bounds": [0.0, 0.0, 5.0, 5.0], "crs": "EPSG:4326"},
        source_path,
    )

    result = euclidean_distance.invoke({
        "layer_name": display_name, "source_value": 1.0,
    })

    expected_name = f"{display_name}_欧氏距离"
    assert "欧氏距离完成" in result, result
    assert os.path.isfile(os.path.join(str(tmp_path), "uploads", expected_name + ".tif"))
    assert _pending_layer_ops[-1]["layer_name"] == expected_name


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
    assert "源栅格缺少 CRS" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "sv_before_填挖方.tif"))
    assert np.allclose(out, 2.0), out


def test_surface_volumes_preserves_valid_elevation_near_nodata(tmp_path):
    nodata = -9999.0
    before, before_path = _make_tif(
        tmp_path, "sv_near_nodata_before", np.zeros((5, 5), dtype="float32"), nodata=nodata
    )
    after, _ = _make_tif(
        tmp_path, "sv_near_nodata_after", np.full((5, 5), 2.0, dtype="float32"), nodata=nodata
    )
    with rasterio.open(before_path, "r+") as dataset:
        values = dataset.read(1)
        values[0, 0] = -9998.95
        dataset.write(values, 1)

    result = surface_volumes.invoke({"before_layer": before, "after_layer": after})

    flat = result.replace(",", "")
    assert "填方量 10048.95 m3" in flat, result
    assert "变化面积 25.00 m2" in flat, result
    diff = _read_out(os.path.join(str(tmp_path), "uploads", "sv_near_nodata_before_填挖方.tif"))
    assert diff[0, 0] == pytest.approx(10000.95, abs=1e-2)


def test_surface_volumes_output_uses_non_colliding_nodata(tmp_path):
    nodata = 0.0
    before_values = np.full((5, 5), 10.0, dtype="float32")
    after_values = before_values.copy()
    after_values[0, 0] = 12.0
    before, _ = _make_tif(tmp_path, "sv_zero_nodata_before", before_values, nodata=nodata)
    after, _ = _make_tif(tmp_path, "sv_zero_nodata_after", after_values, nodata=nodata)

    result = surface_volumes.invoke({"before_layer": before, "after_layer": after})

    assert "变化面积 1.00 m2" in result, result
    output_path = os.path.join(str(tmp_path), "uploads", "sv_zero_nodata_before_填挖方.tif")
    with rasterio.open(output_path) as output:
        assert np.isnan(output.nodata)
        assert int((output.read_masks(1) > 0).sum()) == 25
        diff = output.read(1)
    assert diff[0, 0] == pytest.approx(2.0)
    assert np.all(diff[1:, :] == 0)


def test_surface_volumes_geographic_dem_uses_square_metres(tmp_path, monkeypatch):
    from pyproj import Geod

    upload_dir = os.path.join(str(tmp_path), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    transform = from_origin(10.0, 60.0, 0.01, 0.01)
    geog_wkt = (
        'GEOGCS["WGS 84",DATUM["World Geodetic System 1984",'
        'SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],'
        'AUTHORITY["EPSG","4326"]]'
    )
    for name, values in (("sv_geo_before", np.zeros((5, 5))),
                         ("sv_geo_after", np.full((5, 5), 2.0))):
        with rasterio.open(
            os.path.join(upload_dir, name + ".tif"), "w", driver="GTiff",
            height=5, width=5, count=1, dtype="float32", crs=geog_wkt,
            transform=transform,
        ) as dataset:
            dataset.write(values.astype("float32"), 1)

    monkeypatch.setattr(T, "_raster_preview_op", lambda *args, **kwargs: "preview")
    result = surface_volumes.invoke({"before_layer": "sv_geo_before", "after_layer": "sv_geo_after"})

    geod = Geod(ellps="WGS84")
    total_area = 0.0
    for row in range(5):
        top = 60.0 - row * 0.01
        bottom = top - 0.01
        area, _ = geod.polygon_area_perimeter(
            [10.0, 10.01, 10.01, 10.0], [top, top, bottom, bottom]
        )
        total_area += abs(area) * 5
    expected_volume = total_area * 2.0
    flat_result = result.replace(",", "")
    assert f"填方量 {expected_volume:.2f} m3" in flat_result, result
    assert total_area > 1_000_000


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


def test_surface_volumes_normalizes_feet_elevation_to_metres(tmp_path):
    before, _ = _make_tif(tmp_path, "sv_ft_before", np.zeros((5, 5), dtype="float32"))
    after, after_path = _make_tif(
        tmp_path, "sv_ft_after", np.full((5, 5), 3.280839895, dtype="float32")
    )
    with rasterio.open(after_path, "r+") as dataset:
        dataset.update_tags(VALUE_UNITS="ft")

    result = surface_volumes.invoke({"before_layer": before, "after_layer": after})

    assert "填方量 25.00 m3" in result.replace(",", ""), result


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

def _mask_fixture(tmp_path, name, nodata=None):
    # 栅格 5x5，像元中心 (x+0.5, y+0.5)，范围 x/y 0..5
    data = np.ones((5, 5), dtype="float32")
    _make_tif(tmp_path, name, data, nodata=nodata, crs="EPSG:4326")
    _register_layer("裁剪面", _poly_fc([[1.0, 1.0], [4.0, 1.0], [4.0, 4.0], [1.0, 4.0], [1.0, 1.0]]))
    return name


def test_extract_by_mask_inside(tmp_path):
    name = _mask_fixture(tmp_path, "em_in")
    r = raster_extract_by_mask.invoke({"raster_layer": name, "zone_layer": "裁剪面", "inside": True})
    assert "按掩膜提取完成" in r, r
    out = _read_out(os.path.join(str(tmp_path), "uploads", "em_in_掩膜内.tif"))
    # 面覆盖 3x3 像元中心 (1.5..3.5) -> 9 个有效
    assert int((out > 0).sum()) == 9, out


def test_extract_by_mask_preserves_valid_nodata_sentinel_value(tmp_path):
    name = _mask_fixture(tmp_path, "em_valid_sentinel")
    path = os.path.join(str(tmp_path), "uploads", name + ".tif")
    with rasterio.open(path, "r+") as dataset:
        band = dataset.read(1)
        band[2, 2] = -9999.0
        dataset.write(band, 1)

    result = raster_extract_by_mask.invoke({
        "raster_layer": name, "zone_layer": "裁剪面", "inside": True,
    })

    assert "有效像元 9/25" in result, result
    out = _read_out(os.path.join(str(tmp_path), "uploads", "em_valid_sentinel_掩膜内.tif"))
    assert out[2, 2] == -9999.0
    with rasterio.open(os.path.join(str(tmp_path), "uploads", "em_valid_sentinel_掩膜内.tif")) as output:
        assert np.isnan(output.nodata)


def test_extract_by_mask_compares_declared_nodata_exactly(tmp_path):
    name = _mask_fixture(tmp_path, "em_near_nodata", nodata=-9999.0)
    path = os.path.join(str(tmp_path), "uploads", name + ".tif")
    with rasterio.open(path, "r+") as dataset:
        band = dataset.read(1)
        band[2, 2] = -9998.95
        dataset.write(band, 1)

    result = raster_extract_by_mask.invoke({
        "raster_layer": name, "zone_layer": "裁剪面", "inside": True,
    })

    assert "有效像元 9/25" in result, result
    out = _read_out(os.path.join(str(tmp_path), "uploads", "em_near_nodata_掩膜内.tif"))
    assert out[2, 2] == pytest.approx(-9998.95, abs=1e-3)
    assert _pending_layer_ops[-1]["raster"]["valid_pixel_ratio"] == pytest.approx(9 / 25)


def test_extract_by_mask_uses_registered_layer_name_for_project_asset(tmp_path):
    source_name = _mask_fixture(tmp_path, "project_asset_mask_hash")
    source_path = os.path.join(str(tmp_path), "uploads", source_name + ".tif")
    display_name = "可读分析栅格"
    T._register_raster_layer(
        display_name,
        {"bounds": [0.0, 0.0, 5.0, 5.0], "crs": "EPSG:4326"},
        source_path,
    )

    result = raster_extract_by_mask.invoke({
        "raster_layer": display_name, "zone_layer": "裁剪面", "inside": True,
    })

    expected_name = f"{display_name}_掩膜内"
    assert "按掩膜提取完成" in result, result
    assert os.path.isfile(os.path.join(str(tmp_path), "uploads", expected_name + ".tif"))
    assert _pending_layer_ops[-1]["layer_name"] == expected_name


def test_extract_by_mask_transforms_wgs84_zone_to_projected_raster_crs(tmp_path):
    data = np.ones((5, 5), dtype="float32")
    upload_dir = os.path.join(str(tmp_path), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, "em_projected.tif")
    with rasterio.open(
        path, "w", driver="GTiff", height=5, width=5, count=1,
        dtype="float32", crs="EPSG:3857", transform=from_origin(-2500, 2500, 1000, 1000),
    ) as dataset:
        dataset.write(data, 1)
    _register_layer("裁剪面", _poly_fc([
        [-0.01, -0.01], [0.01, -0.01], [0.01, 0.01], [-0.01, 0.01], [-0.01, -0.01],
    ]))

    result = raster_extract_by_mask.invoke({
        "raster_layer": "em_projected", "zone_layer": "裁剪面", "inside": True,
    })

    assert "有效像元 9/25" in result, result
    out_path = os.path.join(upload_dir, "em_projected_掩膜内.tif")
    assert int((_read_out(out_path) > 0).sum()) == 9
    with rasterio.open(out_path) as output:
        assert output.crs.to_string() == "EPSG:3857"


def test_raster_to_feature_requires_declared_crs(tmp_path):
    name, _ = _make_tif(tmp_path, "vectorize_no_crs", np.array([[1, 1]], dtype="float32"))

    result = raster_to_feature.invoke({"layer_name": name})

    assert "缺少 CRS" in result
    assert "vectorize_no_crs_转矢量" not in T._registered_layers


def test_raster_to_feature_preserves_valid_values_near_nodata(tmp_path, monkeypatch):
    import geopandas as gpd

    nodata = -9999.0
    name, _ = _make_tif(
        tmp_path,
        "vectorize_near_nodata",
        np.array([[-9998.95, nodata]], dtype="float32"),
        nodata=nodata,
        crs="EPSG:4326",
    )
    monkeypatch.setattr(gpd.GeoDataFrame, "estimate_utm_crs", lambda self: None)

    result = raster_to_feature.invoke({"layer_name": name})

    assert "栅格转矢量完成：1 个面" in result
    fc = T._registered_layers["vectorize_near_nodata_转矢量"]["geojson"]
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"]["value"] == pytest.approx(-9998.95)


@pytest.mark.parametrize("connectivity", [0, 6])
def test_raster_to_feature_rejects_invalid_connectivity(tmp_path, connectivity):
    name, _ = _make_tif(tmp_path, f"vectorize_bad_conn_{str(connectivity)}", np.array([[1]], dtype="float32"))

    result = raster_to_feature.invoke({"layer_name": name, "connectivity": connectivity})

    assert "connectivity 仅支持 4 或 8" in result


@pytest.mark.parametrize("simplify", [-1, float("inf"), float("nan")])
def test_raster_to_feature_rejects_invalid_simplify(tmp_path, simplify):
    name, _ = _make_tif(tmp_path, f"vectorize_bad_simplify_{str(simplify)}", np.array([[1]], dtype="float32"))

    result = raster_to_feature.invoke({"layer_name": name, "simplify": simplify})

    assert "simplify 必须是有限的非负数" in result


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


def test_extract_by_mask_rejects_raster_without_crs(tmp_path):
    name, _ = _make_tif(tmp_path, "em_no_crs", np.ones((5, 5), dtype="float32"))
    _register_layer("裁剪面", _poly_fc([
        [1.0, 1.0], [4.0, 1.0], [4.0, 4.0], [1.0, 4.0], [1.0, 1.0],
    ]))

    result = raster_extract_by_mask.invoke({
        "raster_layer": name, "zone_layer": "裁剪面", "inside": True,
    })

    assert "缺少 CRS，无法可靠对齐掩膜" in result
    assert _pending_layer_ops == []
    assert not os.path.exists(os.path.join(str(tmp_path), "uploads", f"{name}_掩膜内.tif"))


def _projected_cost_fixture(tmp_path, name, source_offset_x=0.0):
    from pyproj import Transformer

    forward = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    reverse = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    center_x, center_y = forward.transform(116.4, 39.9)
    upload_dir = os.path.join(str(tmp_path), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    cost = np.ones((3, 3), dtype="float32")
    cost[0, 0] = 9999.95
    path = os.path.join(upload_dir, f"{name}.tif")
    with rasterio.open(
        path, "w", driver="GTiff", height=3, width=3, count=1,
        dtype="float32", crs="EPSG:3857", nodata=10000.0,
        transform=from_origin(center_x - 1500, center_y + 1500, 1000, 1000),
    ) as dataset:
        dataset.write(cost, 1)
    source_lon, source_lat = reverse.transform(center_x + source_offset_x, center_y)
    dest_lon, dest_lat = reverse.transform(center_x + 1100, center_y)
    _register_layer("代价源", {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Point", "coordinates": [source_lon, source_lat]},
    }]})
    _register_layer("代价终点", {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Point", "coordinates": [dest_lon, dest_lat]},
    }]})
    return name


def test_cost_distance_transforms_wgs84_sources_and_preserves_near_nodata_cost(tmp_path):
    name = _projected_cost_fixture(tmp_path, "projected_cost_distance")

    result = cost_distance.invoke({"cost_layer": name, "source_layer": "代价源"})

    assert "可达 9 像元" in result, result
    output_path = T._find_uploaded_tif("projected_cost_distance_代价距离")
    assert output_path
    with rasterio.open(output_path) as output:
        assert np.isfinite(output.read(1)[0, 0])


def test_cost_distance_sanitizes_user_output_name(tmp_path):
    name = _projected_cost_fixture(tmp_path, "projected_cost_safe_output")

    result = cost_distance.invoke({
        "cost_layer": name, "source_layer": "代价源", "out_name": "../../outside",
    })

    assert "代价距离完成" in result, result
    output_path = T._find_uploaded_tif("outside")
    uploads_path = os.path.join(str(tmp_path), "uploads")
    assert output_path
    assert os.path.commonpath([os.path.abspath(output_path), os.path.abspath(uploads_path)]) == os.path.abspath(uploads_path)


def test_cost_graph_rejects_oversized_valid_surface():
    with pytest.raises(ValueError, match="超过单次处理上限（10 万）"):
        T._cost_graph(np.ones(100_001, dtype="float32").reshape(1, -1))


def test_least_cost_path_transforms_wgs84_points_to_projected_raster(tmp_path, monkeypatch):
    import geopandas as gpd

    _projected_cost_fixture(tmp_path, "projected_least_cost")
    monkeypatch.setattr(gpd.GeoDataFrame, "estimate_utm_crs", lambda self: None)

    result = least_cost_path.invoke({
        "cost_layer": "projected_least_cost",
        "source_layer": "代价源",
        "destination_layer": "代价终点",
    })

    assert "最小代价路径完成" in result and "1 条路径" in result, result
    assert "代价源_到_代价终点_代价路径" in T._registered_layers


def test_least_cost_path_does_not_snap_outside_point_toward_zero(tmp_path, monkeypatch):
    import geopandas as gpd

    _projected_cost_fixture(tmp_path, "projected_least_cost_outside", source_offset_x=-1501)
    monkeypatch.setattr(gpd.GeoDataFrame, "estimate_utm_crs", lambda self: None)

    result = least_cost_path.invoke({
        "cost_layer": "projected_least_cost_outside",
        "source_layer": "代价源",
        "destination_layer": "代价终点",
    })

    assert "源 0 个" in result and "未能吸附" in result, result
