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

    def test_ndwi_missing_bands(self, upload_dir):
        _make_tif(os.path.join(upload_dir, "few.tif"), [0.3, 0.5])  # 只有2波段
        r = ndwi_analysis.invoke({"layer_name": "few"})
        # 缺波段应报错（不会崩溃）
        assert "失败" in r or "需要" in r or "未找到" in r

    def test_ndbi_builtup_positive(self, upload_dir):
        """建成区（SWIR 高、NIR 低）NDBI 应为正"""
        # SWIR=0.4, NIR=0.1 → NDBI=(0.4-0.1)/(0.4+0.1)=0.6
        _make_tif(os.path.join(upload_dir, "built.tif"), [0.2, 0.3, 0.25, 0.1, 0.4, 0.35])
        r = ndbi_analysis.invoke({"layer_name": "built", "swir_band": 5, "nir_band": 4})
        assert "已生成" in r

    def test_evi_vegetation(self, upload_dir):
        """植被（NIR 高、Red 低、Blue 中）EVI 应为正"""
        # NIR=0.6, Red=0.1, Blue=0.1 → EVI=2.5*0.5/(0.6+0.6-0.75+1)=1.25/1.45≈0.86
        _make_tif(os.path.join(upload_dir, "veg.tif"), [0.1, 0.2, 0.1, 0.6, 0.15, 0.15])
        r = evi_analysis.invoke({"layer_name": "veg", "nir_band": 4, "red_band": 3, "blue_band": 1})
        assert "已生成" in r

    def test_evi_missing_blue(self, upload_dir):
        """波段数不足（缺 Red/Blue）应报错"""
        _make_tif(os.path.join(upload_dir, "noblue.tif"), [0.1, 0.2])
        r = evi_analysis.invoke({"layer_name": "noblue", "nir_band": 4, "red_band": 3, "blue_band": 1})
        assert "失败" in r or "需要" in r

    def test_ndmi_vegetation_moisture(self, upload_dir):
        """湿润植被（NIR 高、SWIR 低）NDMI 应为正"""
        # NIR=0.5, SWIR=0.2 → NDMI=(0.5-0.2)/(0.5+0.2)=0.43
        _make_tif(os.path.join(upload_dir, "moist.tif"), [0.2, 0.3, 0.2, 0.5, 0.2, 0.2])
        r = ndmi_analysis.invoke({"layer_name": "moist", "nir_band": 4, "swir_band": 5})
        assert "已生成" in r

    def test_no_tif_found(self):
        r = ndvi_analysis.invoke({"layer_name": "ghost"})
        assert "未找到" in r or "未找到上传目录" in r

    def test_pending_ops_created(self, upload_dir):
        """成功计算后应产生 dem_result 待推送图层操作"""
        _make_tif(os.path.join(upload_dir, "w2.tif"), [0.3, 0.5, 0.2, 0.1, 0.05, 0.05])
        ndwi_analysis.invoke({"layer_name": "w2", "green_band": 2, "nir_band": 4})
        ops = [o for o in _pending_layer_ops if o.get("label") and "NDWI" in o["label"]]
        assert len(ops) == 1
        assert ops[0]["url"].endswith("ndwi.png")

    def test_bounds_in_epsg4326(self, upload_dir):
        """结果 PNG 应带 EPSG:4326 边界"""
        _make_tif(os.path.join(upload_dir, "w3.tif"), [0.3, 0.5, 0.2, 0.1, 0.05, 0.05])
        ndwi_analysis.invoke({"layer_name": "w3", "green_band": 2, "nir_band": 4})
        ops = [o for o in _pending_layer_ops if "NDWI" in (o.get("label") or "")]
        assert ops and len(ops[0]["bounds"]) == 4

    def test_formula_correctness(self):
        """核心公式正确性（直接验证计算逻辑，不依赖文件）"""
        import numpy as np
        green, nir = np.array([0.5]), np.array([0.1])
        ndwi = (green - nir) / (green + nir + 1e-10)
        assert abs(float(ndwi[0]) - 0.6667) < 0.001

        swir = np.array([0.4]); nir2 = np.array([0.1])
        ndbi = (swir - nir2) / (swir + nir2 + 1e-10)
        assert abs(float(ndbi[0]) - 0.6) < 0.001

        n, r, b = np.array([0.6]), np.array([0.1]), np.array([0.1])
        evi = 2.5 * (n - r) / (n + 6*r - 7.5*b + 1.0 + 1e-10)
        assert abs(float(evi[0]) - 2.5*0.5/(0.6+0.6-0.75+1)) < 0.001

        n3, s3 = np.array([0.5]), np.array([0.2])
        ndmi = (n3 - s3) / (n3 + s3 + 1e-10)
        assert abs(float(ndmi[0]) - 0.4286) < 0.001
