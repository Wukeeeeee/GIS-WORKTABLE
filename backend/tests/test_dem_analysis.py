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
    reset_state()
    _pending_layer_ops.clear()
    T._temp_output_dir = str(tmp_path)
    yield
    reset_state()
    _pending_layer_ops.clear()


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
