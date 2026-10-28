# -*- coding: utf-8 -*-
"""dem_analysis（坡度/坡向/山体阴影）回归测试

最隐蔽的不是崩溃，而是"图出来了但坡向整体偏了 90 度"。
用中心凸起的锥形 DEM（几何上无歧义）：峰以北的点下坡方向必为北（坡向 0°），
东/南/西依次为 90/180/270°。山体阴影默认光源方位 315°（西北），故西北坡应最亮。

写 GeoTIFF 时不带 CRS，规避本机 PROJ proj.db 版本冲突（proj_create_from_database 报错）。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors

from backend.services import tools as T
from backend.services.tools import dem_analysis, reset_state, _pending_layer_ops


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


def _make_cone(tmp_path, name="cone", n=81):
    import rasterio
    from rasterio.transform import from_origin
    upd = os.path.join(str(tmp_path), "uploads")
    os.makedirs(upd, exist_ok=True)
    yy, xx = np.mgrid[0:n, 0:n]
    z = -((xx - n // 2) ** 2 + (yy - n // 2) ** 2).astype(np.float32)
    path = os.path.join(upd, f"{name}.tif")
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs=None,
                       transform=from_origin(113.0, 23.0, 0.0002, 0.0002)) as dst:
        dst.write(z, 1)
    return n


def _make_geographic_slope_plane(tmp_path, name="geographic_plane", n=81):
    """Create a WGS-84 raster plane with a known 10-degree ground slope."""
    import rasterio
    from rasterio.transform import from_origin
    from pyproj import CRS

    crs_wkt = (
        'GEOGCS["WGS 84",DATUM["World Geodetic System 1984",'
        'SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
    )
    transform = from_origin(-119.64, 37.75, 0.0001, 0.0001)
    center_x, center_y = transform * (n / 2, n / 2)
    geod = CRS.from_wkt(crs_wkt).get_geod()
    _, _, pixel_width_m = geod.inv(center_x, center_y, center_x + transform.a, center_y)
    pixel_rise_m = np.tan(np.radians(10)) * pixel_width_m
    data = np.broadcast_to(np.arange(n, dtype=np.float32)[None, :] * pixel_rise_m, (n, n)).copy()
    path = os.path.join(str(tmp_path), "uploads", f"{name}.tif")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs=crs_wkt, transform=transform) as dst:
        dst.write(data, 1)
    return path


def _hue(arr, y, x):
    rgb = arr[y, x, :3].astype(float) / 255.0
    return mcolors.rgb_to_hsv(rgb)[0] * 360.0


def _read_dem_png(tmp_path):
    ops = [o for o in _pending_layer_ops if o.get("action") == "dem_result"]
    assert ops, f"未产生 dem_result：{_pending_layer_ops}"
    rel = ops[0]["url"].replace("/output/", "")
    path = os.path.join(str(tmp_path), rel)
    assert os.path.isfile(path), f"叠加图未落盘：{path}"
    from PIL import Image
    return np.array(Image.open(path).convert("RGB"))


def _ang_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def test_aspect_cardinals(tmp_path):
    """峰四周的坡向应为 N=0 / E=90 / S=180 / W=270（容差 20°，足以抓住 90° 偏置）。"""
    n = _make_cone(tmp_path)
    r = dem_analysis.invoke({"layer_name": "cone", "analysis": "aspect"})
    assert "坡向" in r, r
    arr = _read_dem_png(tmp_path)
    c = n // 2
    off = 20
    expected = {"N": (c - off, c, 0.0), "E": (c, c + off, 90.0),
                "S": (c + off, c, 180.0), "W": (c, c - off, 270.0)}
    for name, (y, x, truth) in expected.items():
        a = _hue(arr, y, x)
        assert _ang_diff(a, truth) < 20.0, f"{name} 坡向={a:.1f}° 期望≈{truth:.0f}°"


def test_hillshade_nw_brightest(tmp_path):
    """光源方位 315°（西北）：西北坡应最亮，其余朝向明显偏暗。"""
    n = _make_cone(tmp_path)
    r = dem_analysis.invoke({"layer_name": "cone", "analysis": "hillshade"})
    assert "山体阴影" in r, r
    arr = _read_dem_png(tmp_path)
    c = n // 2
    off = 20
    bright = {
        "NW": float(arr[c - off, c - off].mean()),
        "NE": float(arr[c - off, c + off].mean()),
        "SE": float(arr[c + off, c + off].mean()),
        "SW": float(arr[c + off, c - off].mean()),
    }
    nw = bright["NW"]
    others = max(bright["NE"], bright["SE"], bright["SW"])
    assert nw > 0, "西北坡不应全黑"
    assert nw >= others, f"西北坡({nw})应最亮，但 max(其他)={others}"


def test_hillshade_preserves_nodata_for_raster_reuse_and_quality_metadata(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    n = 41
    yy, xx = np.mgrid[0:n, 0:n]
    dem = -((xx - n // 2) ** 2 + (yy - n // 2) ** 2).astype(np.float32)
    dem[12:28, 12:28] = -9999
    path = os.path.join(str(tmp_path), "uploads", "nodata_cone.tif")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs=None, nodata=-9999,
                       transform=from_origin(113.0, 23.0, 0.0002, 0.0002)) as dst:
        dst.write(dem, 1)

    result = dem_analysis.invoke({"layer_name": "nodata_cone", "analysis": "hillshade"})
    assert "山体阴影" in result, result
    op = next(op for op in _pending_layer_ops if op.get("action") == "dem_result")
    assert op["raster"]["valid_pixel_ratio"] < 0.9
    output_path = T._find_uploaded_tif(op["layer_name"])
    with rasterio.open(output_path) as result_raster:
        assert np.isnan(result_raster.read(1)[20, 20])

    follow_up = T.raster_calculator.invoke({"layer_name": op["layer_name"], "expression": "B1*2"})
    assert "可继续分析" in follow_up, follow_up
    derived_path = T._find_uploaded_tif(op["layer_name"] + "_calc")
    with rasterio.open(derived_path) as derived:
        assert np.isnan(derived.read(1)[20, 20])


def test_slope_nonzero_on_cone(tmp_path):
    """锥形 DEM 坡度应处处非零且有限（坡度公式与坡向符号无关，仍应正确）。"""
    n = _make_cone(tmp_path)
    r = dem_analysis.invoke({"layer_name": "cone", "analysis": "slope"})
    assert "坡度" in r, r
    arr = _read_dem_png(tmp_path)
    c = n // 2
    off = 20
    # YlOrRd 灰度近似：取红通道；锥面坡度应 > 0
    gray = arr[c, c + off, 0]
    assert gray > 1, "坡度图出现全零/异常"


def test_geographic_dem_slope_converts_degrees_to_ground_metres(tmp_path):
    """地理坐标栅格的度不能直接当米；已知 10° 平面应还原为约 10°。"""
    import rasterio
    _make_geographic_slope_plane(tmp_path)

    result = dem_analysis.invoke({"layer_name": "geographic_plane", "analysis": "slope"})

    assert "坡度" in result, result
    op = next(op for op in _pending_layer_ops if op.get("action") == "dem_result")
    assert op["raster"]["value_units"] == "°（角度）"
    assert op["raster"]["source_layer"] == "geographic_plane"
    assert any("源栅格未标注数值单位" in warning for warning in op["raster"]["quality_warnings"])
    assert any("经纬度栅格按中心处椭球像元距离" in warning for warning in op["raster"]["quality_warnings"])
    output_path = T._find_uploaded_tif(op["layer_name"])
    with rasterio.open(output_path) as slope:
        value = float(slope.read(1)[40, 40])
        assert slope.tags()["VALUE_UNITS"] == "°（角度）"
        assert slope.tags()["SOURCE_LAYER"] == "geographic_plane"
    assert value == pytest.approx(10.0, abs=0.15)


def test_projected_dem_slope_normalizes_feet_elevation_to_metres(tmp_path):
    """Equivalent elevations in feet and metres should produce the same ground slope."""
    import rasterio
    from rasterio.transform import from_origin

    n = 41
    horizontal_pixel_m = 30.0
    rise_m = np.arange(n, dtype=np.float32)[None, :] * horizontal_pixel_m * np.tan(np.radians(10))
    meters = np.broadcast_to(rise_m, (n, n)).copy()
    os.makedirs(os.path.join(str(tmp_path), "uploads"), exist_ok=True)
    for layer_name, values, units in (
        ("slope_meters", meters, "m"),
        ("slope_feet", meters / 0.3048, "ft"),
    ):
        path = os.path.join(str(tmp_path), "uploads", layer_name + ".tif")
        with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                           dtype="float32", crs="EPSG:32611", nodata=None,
                           transform=from_origin(500000, 4180000, horizontal_pixel_m, horizontal_pixel_m)) as dst:
            dst.write(values, 1)
            dst.update_tags(VALUE_UNITS=units)

    measured_slopes = []
    for layer_name in ("slope_meters", "slope_feet"):
        result = dem_analysis.invoke({"layer_name": layer_name, "analysis": "slope"})
        assert "坡度" in result, result
        op = next(op for op in reversed(_pending_layer_ops)
                  if op.get("action") == "dem_result" and op.get("raster", {}).get("source_layer") == layer_name)
        with rasterio.open(T._find_uploaded_tif(op["layer_name"])) as slope:
            measured_slopes.append(float(slope.read(1)[20, 20]))

    assert measured_slopes[0] == pytest.approx(10.0, abs=0.15)
    assert measured_slopes[1] == pytest.approx(measured_slopes[0], abs=0.15)


def test_projected_dem_slope_uses_rotated_affine_basis(tmp_path):
    """A known east-rising plane must retain its slope under affine rotation."""
    import rasterio
    from affine import Affine

    n = 41
    pixel = 30.0
    angle = np.radians(30.0)
    a = pixel * np.cos(angle)
    b = pixel * np.sin(angle)
    d = pixel * np.sin(angle)
    e = -pixel * np.cos(angle)
    center_easting, center_northing = 500_000.0, 4_180_000.0
    transform = Affine(
        a, b, center_easting - (a + b) * n / 2,
        d, e, center_northing - (d + e) * n / 2,
    )
    rows, cols = np.mgrid[0:n, 0:n]
    eastings = transform.c + a * (cols + 0.5) + b * (rows + 0.5)
    values = ((eastings - center_easting) * np.tan(np.radians(10))).astype(np.float32)
    path = os.path.join(str(tmp_path), "uploads", "rotated_plane.tif")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs="EPSG:32611", transform=transform) as dst:
        dst.write(values, 1)
        dst.update_tags(VALUE_UNITS="m")

    result = dem_analysis.invoke({"layer_name": "rotated_plane", "analysis": "slope"})

    assert "坡度" in result, result
    op = next(op for op in _pending_layer_ops if op.get("action") == "dem_result")
    assert op["raster"]["pixel_size"] == pytest.approx([pixel, pixel])
    with rasterio.open(T._find_uploaded_tif(op["layer_name"])) as slope:
        measured = float(slope.read(1)[n // 2, n // 2])
    assert measured == pytest.approx(10.0, abs=0.15)
    from PIL import Image
    with Image.open(os.path.join(str(tmp_path), "uploads", op["raster"]["filename"])) as preview:
        rgba = np.asarray(preview.convert("RGBA"))
    assert rgba[0, 0, 3] == 0, "rotated raster preview must leave outside-coverage pixels transparent"
    assert rgba[:, :, 3].max() == 255


def test_analysis_output_is_registered_as_reusable_geotiff(tmp_path):
    _make_cone(tmp_path)
    result = dem_analysis.invoke({"layer_name": "cone", "analysis": "slope"})
    assert "GeoTIFF" in result and "可继续分析" in result

    op = next(op for op in _pending_layer_ops if op.get("action") == "dem_result")
    layer_name = op["layer_name"]
    raster_path = T._find_uploaded_tif(layer_name)
    assert raster_path and os.path.isfile(raster_path)
    assert op["raster"]["source_filename"] == os.path.basename(raster_path)
    assert op["registration_token"] == T._registered_layers[layer_name]["registration_token"]
    import rasterio
    with rasterio.open(raster_path) as result_raster:
        values = result_raster.read(1)
        assert result_raster.width == 81 and result_raster.height == 81
        assert np.isfinite(values[40, 60])

    follow_up = T.raster_calculator.invoke({"layer_name": layer_name, "expression": "B1*2"})
    assert "结果栅格" in follow_up and "已上图" in follow_up
    assert os.path.isfile(os.path.join(str(tmp_path), "uploads", layer_name + "_calc.tif"))
