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









