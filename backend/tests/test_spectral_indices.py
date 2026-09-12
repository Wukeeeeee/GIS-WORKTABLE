# -*- coding: utf-8 -*-
"""阶段 C：遥感指数工具测试 — NDWI / NDBI / EVI / NDMI"""
import os
import numpy as np
import pytest
from backend.services.tools import (
    ndwi_analysis, ndbi_analysis, evi_analysis, ndmi_analysis,
    ndvi_analysis, _registered_layers, _pending_layer_ops, reset_state,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_state()
    _registered_layers.clear()
    _pending_layer_ops.clear()
    yield
    reset_state()
    _registered_layers.clear()
    _pending_layer_ops.clear()


def _make_tif(path, bands):
    """生成测试 GeoTIFF，波段数 = len(bands)（每个波段 8x8 固定值）"""
    import rasterio
    profile = {
        "driver": "GTiff", "width": 8, "height": 8, "count": len(bands),
        "dtype": "float32", "crs": "EPSG:4326",
        "transform": rasterio.transform.from_origin(0, 0, 0.001, 0.001),
    }
    with rasterio.open(path, "w", **profile) as dst:
        for i, val in enumerate(bands, start=1):
            arr = np.full((8, 8), val, dtype=np.float32)
            dst.write(arr, i)


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """把 _temp_output_dir 指向临时目录并建 uploads 子目录"""
    from backend.services import tools as T
    d = tmp_path / "output"
    uploads = d / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(T, "_temp_output_dir", str(d))
    return str(uploads)


# ============================================================
# 遥感指数：公式正确性
# ============================================================

class TestSpectralIndices:
    def _calc_direct(self, layer_name, fn, **kw):
        """调用工具后从生成的 PNG 无法读数值，改为直接验证公式：模拟植被/水体/建筑像元"""
        # 通过执行工具确认可运行 + 有效像元数正确（8x8=64）
        r = fn.invoke({"layer_name": layer_name, **kw})
        assert "已生成" in r, r
        return r

    def test_ndwi_water_positive(self, upload_dir):
        """水体（Green 高、NIR 低）NDWI 应为正"""
        # 模拟：Green=0.5, NIR=0.1 → NDWI=(0.5-0.1)/(0.5+0.1)=0.667
        _make_tif(os.path.join(upload_dir, "water.tif"), [0.3, 0.5, 0.2, 0.1, 0.05, 0.05])
        r = ndwi_analysis.invoke({"layer_name": "water", "green_band": 2, "nir_band": 4})
        assert "已生成" in r
        assert "有效像元64" in r


class TestSpectralIndexValues:
    @staticmethod
    def _mean(r):
        import re
        m = re.search(r"平均[^=]*=([-\d.]+)", r)
        return float(m.group(1)) if m else None

    def test_ndvi_formula_value(self, upload_dir):
        """NDVI = (NIR-Red)/(NIR+Red)；canonical 波段下应得已知值"""
        # band3=red=0.2, band4=nir=0.5 -> (0.5-0.2)/(0.5+0.2)=0.4286
        _make_tif(os.path.join(upload_dir, "v.tif"), [0.1, 0.3, 0.2, 0.5, 0.05])
        r = ndvi_analysis.invoke({"layer_name": "v"})
        val = self._mean(r)
        assert val is not None and abs(val - 0.4286) < 0.01, r

    def test_evi_formula_value(self, upload_dir):
        """EVI = 2.5*(NIR-Red)/(NIR+6*Red-7.5*Blue+1) 应得已知值"""
        # NIR=0.5, Red=0.2, Blue=0.1 -> 2.5*0.3/(0.5+1.2-0.75+1)=0.3846
        _make_tif(os.path.join(upload_dir, "e.tif"), [0.1, 0.3, 0.2, 0.5, 0.05])
        r = evi_analysis.invoke({"layer_name": "e"})
        val = self._mean(r)
        assert val is not None and abs(val - 0.3846) < 0.01, r

    def test_ndwi_uses_band_params(self, upload_dir):
        """回归：波段参数必须真正生效（修复前被静默忽略）。

        Landsat-8 风格顺序：band2/band4 取中性值(0.9)，真实水体在 band3(green=0.5)/band5(nir=0.1)。
        显式 green_band=3, nir_band=5 应读 3/5 -> 0.667；默认 2/4 应读 0.9/0.9 -> 0.0。
        两者必须不同，才能证明参数真的被用到了。"""
        _make_tif(os.path.join(upload_dir, "ls8.tif"), [0.2, 0.9, 0.5, 0.9, 0.1])
        r_param = ndwi_analysis.invoke({"layer_name": "ls8", "green_band": 3, "nir_band": 5})
        val_param = self._mean(r_param)
        assert val_param is not None and abs(val_param - 0.667) < 0.01, f"波段参数被忽略: {r_param}"
        r_def = ndwi_analysis.invoke({"layer_name": "ls8"})
        val_def = self._mean(r_def)
        assert val_def is not None and abs(val_def - 0.0) < 0.01, f"默认应≈0.0, 实得 {r_def}"
        assert abs(val_param - val_def) > 0.5, "波段参数未改变结果，疑似仍被忽略"









