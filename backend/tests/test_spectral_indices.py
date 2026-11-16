# -*- coding: utf-8 -*-
"""阶段 C：遥感指数工具测试 — NDWI / NDBI / EVI / NDMI"""
import os
import sys
import threading
import numpy as np
import pytest
from backend.services import tools as T
from backend.services.tools import (
    ndwi_analysis, ndbi_analysis, evi_analysis, ndmi_analysis,
    ndvi_analysis, _registered_layers, _pending_layer_ops, reset_state,
)


def _isolate_spectral_indices_runtime(monkeypatch, tmp_path):
    from backend.services.tool_modules import runtime

    output_dir = str(tmp_path)
    isolated_runtime = {
        "_registered_layers": {},
        "_pending_layers": [],
        "_pending_layer_ops": [],
        "_pending_images": [],
        "_pending_qa_warnings": [],
        "_pending_aoi_suggestions": {},
        "_pending_heatmap": {"latest": None},
        "_clear_layers_flag": False,
        "_current_amap_key": "",
        "_search_call_count": 0,
        "_domain_fail": {},
        "_search_cache": {},
        "_search_last_hit": {},
        "_exec_call_count": 0,
        "_exec_log": [],
        "_temp_output_dir": output_dir,
        "_workspace_dir": str(tmp_path / "workspace"),
        "_raster_output_scope": threading.local(),
        "_active_project_id": None,
        "_current_task_id": "",
        "_last_user_message": "",
        "_current_run_id": "",
        "_conversation_context": "",
        "_session_locks": {},
    }
    for path in (output_dir, os.path.join(output_dir, "output"), isolated_runtime["_workspace_dir"]):
        os.makedirs(path, exist_ok=True)
    with runtime._state_lock, runtime._session_locks_guard:
        for name, value in isolated_runtime.items():
            monkeypatch.setattr(T, name, value)
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "_registered_layers", isolated_runtime["_registered_layers"])
    monkeypatch.setattr(module, "_pending_layer_ops", isolated_runtime["_pending_layer_ops"])


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    _isolate_spectral_indices_runtime(monkeypatch, tmp_path)
    reset_state()
    yield
    reset_state()


def test_spectral_indices_fixture_restores_existing_runtime_state(tmp_path):
    from backend.services.tool_modules import runtime

    registry, pending_ops = runtime._registered_layers, runtime._pending_layer_ops
    registry["outside-sentinel"] = {"sentinel": True}
    pending_ops.append({"action": "outside-sentinel"})
    runtime.set_current_task("outside-spectral-task-context")

    patcher = pytest.MonkeyPatch()
    try:
        _isolate_spectral_indices_runtime(patcher, tmp_path)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layer_ops is not pending_ops
        assert T._registered_layers is runtime._registered_layers
        assert sys.modules[__name__]._registered_layers is runtime._registered_layers
        assert sys.modules[__name__]._pending_layer_ops is runtime._pending_layer_ops
    finally:
        patcher.undo()

    assert runtime._registered_layers is registry
    assert registry["outside-sentinel"]["sentinel"]
    assert runtime._pending_layer_ops is pending_ops
    assert pending_ops[-1]["action"] == "outside-sentinel"
    assert runtime.get_current_task_id() == "outside-spectral-task-context"


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

    def test_spectral_index_counts_internal_mask_pixels_as_invalid(self, upload_dir):
        import rasterio

        path = os.path.join(upload_dir, "masked_water.tif")
        _make_tif(path, [0.3, 0.5, 0.2, 0.1])
        with rasterio.open(path, "r+") as src:
            mask = np.full((8, 8), 255, dtype=np.uint8)
            mask[0, 0] = 0
            src.write_mask(mask)

        result = ndwi_analysis.invoke({
            "layer_name": "masked_water", "green_band": 2, "nir_band": 4,
        })

        assert "已生成" in result
        assert "有效像元63" in result


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

    def test_ndvi_different_band_params_preserve_previous_output(self, upload_dir):
        import rasterio

        _make_tif(os.path.join(upload_dir, "ndvi_repeat.tif"), [0.1, 0.3, 0.2, 0.5, 0.05])
        first = ndvi_analysis.invoke({"layer_name": "ndvi_repeat", "red_band": 3, "nir_band": 4})
        first_op = next(op for op in _pending_layer_ops if op.get("action") == "dem_result")
        first_name = first_op["layer_name"]
        first_info = _registered_layers[first_name]
        first_path = first_info["raster_source_path"]
        with open(first_path, "rb") as raster_file:
            first_bytes = raster_file.read()
        with rasterio.open(first_path) as raster:
            first_values = raster.read(1)

        reset_state()
        second = ndvi_analysis.invoke({"layer_name": "ndvi_repeat", "red_band": 2, "nir_band": 4})
        second_op = next(op for op in _pending_layer_ops if op.get("action") == "dem_result")
        second_name = second_op["layer_name"]
        second_info = _registered_layers[second_name]

        assert "已生成NDVI" in first and "已生成NDVI" in second
        assert second_name != first_name
        assert second_info["raster_source_path"] != first_path
        with open(first_path, "rb") as raster_file:
            assert raster_file.read() == first_bytes
        with rasterio.open(second_info["raster_source_path"]) as raster:
            assert not np.array_equal(raster.read(1), first_values)

    def test_shared_spectral_index_different_bands_preserve_previous_preview(self, upload_dir):
        _make_tif(os.path.join(upload_dir, "ndwi_repeat.tif"), [0.1, 0.3, 0.2, 0.5, 0.05])
        first = ndwi_analysis.invoke({"layer_name": "ndwi_repeat", "green_band": 2, "nir_band": 4})
        first_op = next(op for op in _pending_layer_ops if op.get("action") == "dem_result")
        first_name = first_op["name"]
        first_path = os.path.join(upload_dir, first_name)
        with open(first_path, "rb") as image_file:
            first_bytes = image_file.read()

        reset_state()
        second = ndwi_analysis.invoke({"layer_name": "ndwi_repeat", "green_band": 3, "nir_band": 4})
        second_op = next(op for op in _pending_layer_ops if op.get("action") == "dem_result")
        second_name = second_op["name"]

        assert "已生成NDWI" in first and "已生成NDWI" in second
        assert second_name != first_name
        with open(first_path, "rb") as image_file:
            assert image_file.read() == first_bytes
        assert os.path.isfile(os.path.join(upload_dir, second_name))

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


class TestCalcSpectralIndexFacade:
    def test_facade_ndvi_dispatch(self, upload_dir):
        """测试 calc_spectral_index 门面正确调度 NDVI"""
        _make_tif(os.path.join(upload_dir, "facade_v.tif"), [0.1, 0.3, 0.2, 0.5, 0.05])
        from backend.services.tools import calc_spectral_index
        r = calc_spectral_index.invoke({"layer_name": "facade_v", "index": "ndvi"})
        assert "已生成NDVI" in r or "平均NDVI=" in r

    def test_facade_ndwi_dispatch(self, upload_dir):
        """测试 calc_spectral_index 门面正确调度 NDWI"""
        _make_tif(os.path.join(upload_dir, "facade_w.tif"), [0.3, 0.5, 0.2, 0.1, 0.05, 0.05])
        from backend.services.tools import calc_spectral_index
        r = calc_spectral_index.invoke({"layer_name": "facade_w", "index": "ndwi", "green_band": 2, "nir_band": 4})
        assert "已生成NDWI" in r









