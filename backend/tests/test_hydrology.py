# -*- coding: utf-8 -*-
"""水文分析填洼（_fill_sinks）回归测试

原实现把 `filled[i,j] > min_nbr` 判定为"填洼"，实为 3x3 最小值滤波（形态学腐蚀），
会把 DEM 反复抹平到全局最低点。正确填洼只抬高洼地、绝不降低任何栅格值。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from backend.services import tools as T
from backend.services.tools import _fill_sinks, hydrology_analysis, reset_state, _pending_layer_ops


@pytest.fixture(autouse=True)
def _clean(tmp_path):
    reset_state()
    _pending_layer_ops.clear()
    T._temp_output_dir = str(tmp_path)
    yield
    reset_state()
    _pending_layer_ops.clear()


def _local_min_still_there(a):
    """返回仍为"严格局部最低"的内部单元数"""
    inner = a[1:-1, 1:-1]
    nb = np.stack([
        a[:-2, 1:-1], a[2:, 1:-1], a[1:-1, :-2], a[1:-1, 2:],
        a[:-2, :-2], a[:-2, 2:], a[2:, :-2], a[2:, 2:],
    ])
    return int((inner < nb.min(axis=0) - 1e-9).sum())


class TestFillSinks:
    def test_flat_unchanged(self):
        flat = np.full((7, 7), 10.0)
        out = _fill_sinks(flat)
        assert np.allclose(out, flat)

    def test_monotone_plane_unchanged(self):
        plane = np.tile(np.arange(8, 0, -1, dtype=float).reshape(-1, 1), (1, 6))
        out = _fill_sinks(plane)
        assert np.allclose(out, plane)

    def test_never_lowers_and_raises_pit(self):
        pit = np.full((9, 9), 10.0)
        pit[4, 4] = 0.0
        out = _fill_sinks(pit)
        # 只抬高不降低
        assert (out >= pit - 1e-9).all(), "填洼降低了栅格值"
        # 洼地被抬高
        assert out[4, 4] > 9.9
        # 无残留局部最低
        assert _local_min_still_there(out) == 0

    def test_tilted_with_pit_becomes_drainable(self):
        tilt = np.tile(np.arange(12, 0, -1, dtype=float).reshape(-1, 1), (1, 12))
        tilt[6, 6] = 3.0
        out = _fill_sinks(tilt)
        assert (out >= tilt - 1e-9).all()
        assert _local_min_still_there(out) == 0

    def test_nodata_preserved(self):
        dem = np.full((7, 7), 5.0)
        dem[3, 3] = np.nan
        out = _fill_sinks(dem)
        assert np.isnan(out[3, 3])


class TestHydrologyTool:
    def _make_dem(self, tmp_path, name="dem", n=24):
        import rasterio
        from rasterio.transform import from_origin
        upd = os.path.join(str(tmp_path), "uploads")
        os.makedirs(upd, exist_ok=True)
        # 南倾平面 + 一个内部洼地
        z = np.tile(np.arange(n, 0, -1, dtype=np.float32).reshape(-1, 1), (1, n)).astype(np.float32)
        z[n // 2, n // 2] = 1.0
        with rasterio.open(os.path.join(upd, f"{name}.tif"), "w", driver="GTiff",
                           height=n, width=n, count=1, dtype="float32", crs=None,
                           transform=from_origin(113.0, 23.0, 0.0002, 0.0002)) as dst:
            dst.write(z, 1)

    def test_flowacc_runs(self, tmp_path):
        self._make_dem(tmp_path)
        r = hydrology_analysis.invoke({"layer_name": "dem", "analysis": "flowacc"})
        assert "已生成" in r, r
        assert any(o.get("action") == "dem_result" for o in _pending_layer_ops)

    def test_flowdir_runs(self, tmp_path):
        self._make_dem(tmp_path)
        r = hydrology_analysis.invoke({"layer_name": "dem", "analysis": "flowdir"})
        assert "已生成" in r, r
