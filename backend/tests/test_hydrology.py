# -*- coding: utf-8 -*-
"""水文分析填洼（_fill_sinks）回归测试

原实现把 `filled[i,j] > min_nbr` 判定为"填洼"，实为 3x3 最小值滤波（形态学腐蚀），
会把 DEM 反复抹平到全局最低点。正确填洼只抬高洼地、绝不降低任何栅格值。
"""
import os
import sys
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from backend.services import tools as T
from backend.services.tools import _fill_sinks, hydrology_analysis, reset_state, _pending_layer_ops
from backend.services import history_service


def _isolate_hydrology_state(monkeypatch, tmp_path):
    from backend.services.tool_modules import runtime

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
        "_temp_output_dir": str(tmp_path),
        "_workspace_dir": str(tmp_path / "workspace"),
        "_raster_output_scope": threading.local(),
        "_active_project_id": None,
        "_current_task_id": "",
        "_last_user_message": "",
        "_current_run_id": "",
        "_conversation_context": "",
        "_session_locks": {},
    }
    for path in (tmp_path, tmp_path / "output", tmp_path / "workspace"):
        path.mkdir(parents=True, exist_ok=True)
    with runtime._state_lock, runtime._session_locks_guard:
        for name, value in isolated_runtime.items():
            monkeypatch.setattr(T, name, value)
    # This module imported the pending queue by value; keep its assertion on
    # the same isolated list used by runtime and the tools facade.
    monkeypatch.setattr(
        sys.modules[__name__], "_pending_layer_ops", isolated_runtime["_pending_layer_ops"]
    )
    history_state = {
        "_CUSTOM_PATH": [str(tmp_path / "tool_history.json")],
        "_ENTRIES": [],
        "_NEXT_INDEX": [1],
        "_LOADED": [False],
        "_LOAD_ERROR": [None],
        "_PERSIST_ERROR": [None],
    }
    for name, value in history_state.items():
        monkeypatch.setattr(history_service, name, value)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    _isolate_hydrology_state(monkeypatch, tmp_path)
    reset_state()
    yield
    reset_state()


def test_hydrology_fixture_restores_existing_runtime_and_history_state(tmp_path):
    from backend.services.tool_modules import runtime

    registry, pending = runtime._registered_layers, runtime._pending_layers
    pending_ops = runtime._pending_layer_ops
    history_entries, history_path = history_service._ENTRIES, history_service._CUSTOM_PATH
    registry["external-sentinel"] = {"sentinel": True}
    pending.append({"name": "external-pending-sentinel"})
    pending_ops.append({"action": "external-op-sentinel"})
    history_entries.append({"tool": "external-history-sentinel"})
    history_path[0] = "external-history-path.json"
    runtime.set_current_task("external-task-context-sentinel")

    patcher = pytest.MonkeyPatch()
    try:
        _isolate_hydrology_state(patcher, tmp_path)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layers is not pending
        assert runtime._pending_layer_ops is not pending_ops
        assert history_service._ENTRIES is not history_entries
        assert history_service._CUSTOM_PATH is not history_path
        assert T._pending_layer_ops is runtime._pending_layer_ops
        assert sys.modules[__name__]._pending_layer_ops is runtime._pending_layer_ops
    finally:
        patcher.undo()

    assert runtime._registered_layers is registry and "external-sentinel" in registry
    assert runtime._pending_layers is pending and pending[-1]["name"] == "external-pending-sentinel"
    assert runtime._pending_layer_ops is pending_ops and pending_ops[-1]["action"] == "external-op-sentinel"
    assert history_service._ENTRIES is history_entries
    assert history_entries[-1]["tool"] == "external-history-sentinel"
    assert history_service._CUSTOM_PATH is history_path
    assert history_path[0] == "external-history-path.json"
    assert runtime.get_current_task_id() == "external-task-context-sentinel"


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
                           height=n, width=n, count=1, dtype="float32", crs="EPSG:4326",
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

    def test_flowdir_preview_uses_compass_bearing_for_d8_codes(self, tmp_path):
        import rasterio
        from rasterio.transform import from_origin
        from PIL import Image

        n = 24
        # Elevation increases eastward, so the centre cell drains west (D8 code 4).
        dem = np.tile(np.arange(n, dtype=np.float32), (n, 1))
        upload_dir = os.path.join(str(tmp_path), "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        with rasterio.open(
            os.path.join(upload_dir, "east_rising.tif"), "w", driver="GTiff",
            height=n, width=n, count=1, dtype="float32", crs="EPSG:32611",
            transform=from_origin(500000, 4000000, 30, 30),
        ) as dst:
            dst.write(dem, 1)

        result = hydrology_analysis.invoke({"layer_name": "east_rising", "analysis": "flowdir"})
        assert "已生成" in result, result
        with rasterio.open(os.path.join(upload_dir, "east_rising_flowdir.tif")) as output:
            assert int(output.read(1)[n // 2, n // 2]) == 4
        preview = np.asarray(Image.open(os.path.join(upload_dir, "east_rising_flowdir.png")))
        import matplotlib
        expected = (np.asarray(matplotlib.colormaps["hsv"](270 / 360)[:3]) * 255).astype(np.uint8)
        assert np.array_equal(preview[n // 2, n // 2, :3], expected)

    def test_rotated_flowdir_preview_uses_ground_bearing(self, tmp_path):
        import rasterio
        from affine import Affine
        from PIL import Image
        from pyproj import CRS, Transformer

        n = 24
        angle = np.radians(30)
        pixel = 30.0
        transform = Affine(
            pixel * np.cos(angle), pixel * np.sin(angle), 500_000,
            pixel * np.sin(angle), -pixel * np.cos(angle), 4_000_000,
        )
        rows, cols = np.mgrid[0:n, 0:n]
        elevations = (transform.a * cols + transform.b * rows).astype(np.float32)
        upload_dir = os.path.join(str(tmp_path), "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        with rasterio.open(
            os.path.join(upload_dir, "rotated_east_rising.tif"), "w", driver="GTiff",
            height=n, width=n, count=1, dtype="float32", crs="EPSG:32611",
            transform=transform,
        ) as dst:
            dst.write(elevations, 1)

        result = hydrology_analysis.invoke({
            "layer_name": "rotated_east_rising", "analysis": "flowdir",
        })
        assert "已生成" in result, result
        with rasterio.open(os.path.join(upload_dir, "rotated_east_rising_flowdir.tif")) as output:
            direction_code = int(output.read(1)[n // 2, n // 2])
        preview = np.asarray(Image.open(os.path.join(upload_dir, "rotated_east_rising_flowdir.png")))
        to_wgs84 = Transformer.from_crs("EPSG:32611", "EPSG:4326", always_xy=True)
        geod = CRS.from_epsg(4326).get_geod()
        center = transform * (n / 2, n / 2)
        offset = (
            -transform.a - transform.b,
            -transform.d - transform.e,
        )
        start = to_wgs84.transform(*center)
        end = to_wgs84.transform(center[0] + offset[0], center[1] + offset[1])
        bearing = geod.inv(*start, *end)[0] % 360
        import matplotlib
        expected = (np.asarray(matplotlib.colormaps["hsv"](bearing / 360)[:3]) * 255).astype(np.uint8)
        assert direction_code == 3
        assert np.array_equal(preview[n // 2, n // 2, :3], expected)
