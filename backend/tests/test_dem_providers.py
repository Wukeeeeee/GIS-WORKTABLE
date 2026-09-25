# -*- coding: utf-8 -*-
"""按需 DEM Provider 与 get_elevation_data 工具测试。

覆盖：
- tile_math 纯函数（bbox↔tile、zoom 选择、mosaic / clip / 重采样）
- cache 原子写与损坏恢复
- Terrarium 解码 round-trip + 海洋 NaN
- AWS Terrain Provider（mock HTTP）：fetch / 缓存命中 / 部分失败 / 越界
- get_elevation_data 工具：注册、bbox 解析、端到端（mock 网络）、产物落盘
- DEM Registry 默认 Provider
"""
import io
import json
import os
import sys
import tempfile
from unittest import mock

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services import tools as T
from backend.services.tools import (
    get_elevation_data,
    reset_state,
    _parse_dem_bbox,
    _pending_layer_ops,
)
from backend.services.dem_providers import (
    DEMError,
    DEMTileDecodeError,
    DEMAreaOutOfRangeError,
    DEMTooManyTilesError,
    DEMRegistry,
    dem_provider_by_id,
    list_dem_capabilities,
)
from backend.services.dem_providers.base import DEMProvider, DEMResult, compute_summary
from backend.services.dem_providers.tile_math import (
    bbox_to_tile_index_range,
    lnglat_to_tile_index,
    world_px_to_lnglat,
    lnglat_to_world_px,
    tile_index_bounds_lnglat,
    degrees_per_pixel,
    select_zoom,
    mosaic_tiles,
    mosaic_transform,
    clip_mosaic_to_bbox,
    resample_to_resolution,
    validate_bbox,
    DEFAULT_ZOOM,
    MERCATOR_MAX_LAT,
    TILE_SIZE,
)
from backend.services.dem_providers.cache import (
    save_tile_atomic,
    load_cached_tile,
    tile_path,
)
from backend.services.dem_providers.aws_terrain import (
    AWSTerrainProvider,
    _decode_terrarium_png,
    _OCEAN_RGB,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _clean_state(tmp_path, monkeypatch):
    """每个测试独立 tmp_path + uploads 目录，避免污染项目真实 cache/。"""
    reset_state()
    _pending_layer_ops.clear()
    T._temp_output_dir = str(tmp_path / "output")
    os.makedirs(T._temp_output_dir, exist_ok=True)
    os.makedirs(os.path.join(T._temp_output_dir, "uploads"), exist_ok=True)
    yield
    reset_state()
    _pending_layer_ops.clear()


def _encode_terrarium(elev: np.ndarray) -> bytes:
    """把高程数组编码为 Terrarium PNG（与 _decode_terrarium_png 互逆）。

    用 round 而非 floor 截断 G 通道，避免 ~1 m 精度损失（编码端按 G/256 反算时
    floor 会把 999.99 → 999）。
    """
    elev = np.asarray(elev, dtype=np.float64)
    val = elev + 32768.0
    R = np.clip(np.floor(val / 256.0), 0, 255).astype(np.uint8)
    # G：val 的小数部分 round 到最近整数（解码公式 R*256 + G + B/256 - 32768 = val）
    G_low = np.clip(np.round(val - R.astype(np.float64) * 256.0), 0, 255).astype(np.uint8)
    B = np.zeros_like(R, dtype=np.uint8)
    img = Image.fromarray(np.stack([R, G_low, B], axis=-1), mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _encode_rgb(R: int, G: int, B: int, h: int = 256, w: int = 256) -> bytes:
    arr = np.full((h, w, 3), [R, G, B], dtype=np.uint8)
    img = Image.fromarray(arr, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


# ============================================================
# 1. tile_math 纯函数
# ============================================================

class TestTileMath:

    def test_lnglat_to_tile_index_known(self):
        # 赤道本初子午线在 z=0 → tile (0,0)；z=1 → (1,1)
        x, y = lnglat_to_tile_index(0.0, 0.0, 0)
        assert (x, y) == (0, 0)
        x, y = lnglat_to_tile_index(0.0, 0.0, 1)
        assert (x, y) == (1, 1)

    def test_world_px_roundtrip(self):
        # (lng, lat) → world px → (lng, lat) 应回到原值
        for lng, lat in [(0.0, 0.0), (112.93, 28.18), (-73.97, 40.78), (121.5, -31.2)]:
            x, y = lnglat_to_world_px(lng, lat, 12)
            lng2, lat2 = world_px_to_lnglat(x, y, 12)
            assert abs(lng - lng2) < 1e-6, (lng, lng2)
            assert abs(lat - lat2) < 1e-6, (lat, lat2)

    def test_tile_index_bounds_returns_reasonable_lnglat(self):
        # tile (z=12, x=3332, y=1713) 覆盖岳麓山附近：bounds 包含 112.93, 28.18
        bx0, by0, bx1, by1 = tile_index_bounds_lnglat(3332, 1713, 12)
        # 岳麓山 (112.93, 28.18) 应落在此 tile 内（容许 ±1° 边界差）
        assert bx0 - 1.0 <= 112.93 <= bx1 + 1.0
        assert by0 - 1.0 <= 28.18 <= by1 + 1.0

    def test_bbox_to_tiles_yuelu_small(self):
        # 岳麓山 0.04° × 0.02° → z=12 应只有 1~2 个 tile
        bb = [112.93, 28.18, 112.97, 28.20]
        x_min, y_min, x_max, y_max = bbox_to_tile_index_range(bb, 12)
        n = (x_max - x_min + 1) * (y_max - y_min + 1)
        assert 1 <= n <= 4, f"unexpected tile count: {n}"

    def test_bbox_to_tiles_global(self):
        # 全球 bbox 在 z=2 应为 16 个 tile（4×4）
        bb = [-180, -MERCATOR_MAX_LAT + 0.01, 180, MERCATOR_MAX_LAT - 0.01]
        x_min, y_min, x_max, y_max = bbox_to_tile_index_range(bb, 2)
        assert (x_max - x_min + 1) == 4
        assert (y_max - y_min + 1) == 4

    def test_bbox_out_of_range_lat_raises(self):
        with pytest.raises(DEMAreaOutOfRangeError):
            bbox_to_tile_index_range([0, 86, 1, 87], 5)
        with pytest.raises(DEMAreaOutOfRangeError):
            bbox_to_tile_index_range([0, -90, 1, -85], 5)

    def test_bbox_invalid_order_raises(self):
        with pytest.raises(DEMAreaOutOfRangeError):
            bbox_to_tile_index_range([10, 0, 5, 5], 5)  # minLng > maxLng
        with pytest.raises(DEMAreaOutOfRangeError):
            bbox_to_tile_index_range([0, 5, 5, 0], 5)  # minLat > maxLat

    def test_bbox_too_many_tiles_raises(self):
        # z=14 全球 → 上千 tile
        bb = [-180, -MERCATOR_MAX_LAT + 0.01, 180, MERCATOR_MAX_LAT - 0.01]
        with pytest.raises(DEMTooManyTilesError):
            bbox_to_tile_index_range(bb, 14, max_tiles=10)

    def test_select_zoom_basic(self):
        # 0.01 deg/px → z=8 (0.00549 ≤ 0.01，z=9=0.00274 也满足但更细；选最粗)
        assert select_zoom(0.01, z_min=0, z_max=14) == 8
        # 0.001 deg/px → z=11 (0.00069 ≤ 0.001)
        assert select_zoom(0.001, z_min=0, z_max=14) == 11
        # 0.0001 deg/px → z=14 (0.000086 ≤ 0.0001)
        assert select_zoom(0.0001, z_min=0, z_max=14) == 14
        # 2.0 deg/px → z=0（z=0 = 1.40625 ≤ 2.0；z=1=0.703 也满足但更细，选最粗 z=0）
        assert select_zoom(2.0, z_min=0, z_max=14) == 0
        # 0 或负 → default
        assert select_zoom(0.0) == DEFAULT_ZOOM
        assert select_zoom(-1.0) == DEFAULT_ZOOM

    def test_select_zoom_clamps(self):
        # 极细 → 强制 max
        assert select_zoom(0.00001, z_min=0, z_max=14) == 14
        # 极粗 → 强制 min
        assert select_zoom(100.0, z_min=5, z_max=10) == 5

    def test_mosaic_and_clip_known(self):
        # 2x1 tile mosaic，每个 tile 是常数 50 m / 80 m
        x_min, y_min, x_max, y_max = 3332, 1713, 3333, 1713
        tile_dict = {
            (3332, 1713): np.full((TILE_SIZE, TILE_SIZE), 50.0),
            (3333, 1713): np.full((TILE_SIZE, TILE_SIZE), 80.0),
        }
        mosaic = mosaic_tiles(tile_dict, 12, x_min, y_min, x_max, y_max)
        assert mosaic.shape == (TILE_SIZE, 2 * TILE_SIZE)
        # mosaic 左半应 ≈ 50 m
        assert abs(np.mean(mosaic[:, :TILE_SIZE]) - 50.0) < 1e-6
        # 右半应 ≈ 80 m
        assert abs(np.mean(mosaic[:, TILE_SIZE:]) - 80.0) < 1e-6

        transform = mosaic_transform(x_min, y_min, 12)
        # 裁剪到岳麓山 bbox
        bb = [112.93, 28.18, 112.97, 28.20]
        clipped, new_t, new_b = clip_mosaic_to_bbox(mosaic, transform, bb)
        # clipped 应包含两个 tile 的拼接区域
        assert clipped.shape[0] > 0 and clipped.shape[1] > 0
        # bounds 应在请求范围内（容许 ~1 像素的 floor 误差 ≈ 1e-3°）
        pixel_w = degrees_per_pixel(12)
        assert new_b[0] >= bb[0] - pixel_w and new_b[2] <= bb[2] + pixel_w
        assert new_b[1] >= bb[1] - pixel_w and new_b[3] <= bb[3] + pixel_w

    def test_resample_doubles_grid(self):
        # 1 tile 256x256，bbox 是 tile 中心 0.01° × 0.01°
        elev = np.full((TILE_SIZE, TILE_SIZE), 100.0)
        tile_dict = {(3332, 1713): elev}
        x_min, y_min, x_max, y_max = 3332, 1713, 3332, 1713
        mosaic = mosaic_tiles(tile_dict, 12, x_min, y_min, x_max, y_max)
        transform = mosaic_transform(x_min, y_min, 12)
        # 0.01° 是 z=12 像素宽度的两倍左右 → 重采样后图像素更少
        bb = [112.94, 28.19, 112.96, 28.21]
        out, new_t, new_b = resample_to_resolution(mosaic, transform, bb, 0.01)
        # 输出 width ≈ (0.02 / 0.01) ≈ 2 个像素
        assert 1 <= out.shape[1] <= 5
        # 值应仍是 ~100 m
        valid = np.isfinite(out)
        if valid.any():
            assert abs(np.mean(out[valid]) - 100.0) < 1.0

    def test_validate_bbox_accepts_list_and_tuple(self):
        # list/tuple 都应通过
        v1 = validate_bbox([0, 0, 1, 1])
        v2 = validate_bbox((0, 0, 1, 1))
        assert v1 == v2


# ============================================================
# 2. tile cache
# ============================================================

class TestCache:

    def test_save_load_roundtrip(self, tmp_path):
        png = _encode_terrarium(np.full((TILE_SIZE, TILE_SIZE), 100.0))
        path = save_tile_atomic(str(tmp_path), "test_prov", 12, 100, 200, png)
        assert path is not None and os.path.isfile(path)
        loaded = load_cached_tile(str(tmp_path), "test_prov", 12, 100, 200)
        assert loaded == png

    def test_corrupted_cache_returns_none(self, tmp_path):
        # 写入非 PNG 数据
        save_tile_atomic(str(tmp_path), "test_prov", 12, 100, 200, b"NOT PNG")
        assert load_cached_tile(str(tmp_path), "test_prov", 12, 100, 200) is None

    def test_empty_cache_returns_none(self, tmp_path):
        assert load_cached_tile(str(tmp_path), "test_prov", 0, 0, 0) is None

    def test_oversized_cache_returns_none(self, tmp_path):
        path = save_tile_atomic(str(tmp_path), "test_prov", 12, 1, 1, b"x")
        # 不写入 → load_cached_tile 应返回 None
        assert load_cached_tile(str(tmp_path), "test_prov", 12, 1, 1) is None

    def test_atomic_write_preserves_old_on_failure(self, tmp_path):
        """写入新内容失败时，旧缓存不被破坏。"""
        png1 = _encode_terrarium(np.full((TILE_SIZE, TILE_SIZE), 50.0))
        save_tile_atomic(str(tmp_path), "test_prov", 12, 1, 1, png1)
        old = load_cached_tile(str(tmp_path), "test_prov", 12, 1, 1)
        assert old == png1
        # 模拟写入失败：mock 内置 open 抛错
        real_open = open

        def fail_open(path, *args, **kwargs):
            if str(path).endswith(".tmp.part"):
                raise OSError("disk full")
            return real_open(path, *args, **kwargs)

        png2 = _encode_terrarium(np.full((TILE_SIZE, TILE_SIZE), 99.0))
        with mock.patch("builtins.open", side_effect=fail_open):
            result = save_tile_atomic(str(tmp_path), "test_prov", 12, 1, 1, png2)
        assert result is None
        # 旧内容仍在
        cur = load_cached_tile(str(tmp_path), "test_prov", 12, 1, 1)
        assert cur == png1, "atomic write failure corrupted old cache"


# ============================================================
# 3. Terrarium 解码
# ============================================================

class TestTerrariumDecode:

    def test_decode_known_elevation(self):
        elev = np.full((TILE_SIZE, TILE_SIZE), 100.0)
        png = _encode_terrarium(elev)
        decoded = _decode_terrarium_png(png)
        assert decoded.shape == (TILE_SIZE, TILE_SIZE)
        # 100m 应精确还原
        assert abs(np.nanmax(decoded) - 100.0) < 0.01
        assert abs(np.nanmin(decoded) - 100.0) < 0.01

    def test_decode_varying_elevation(self):
        # 渐变：0 ~ 1000 m
        lin = np.linspace(0, 1000, TILE_SIZE * TILE_SIZE).reshape(TILE_SIZE, TILE_SIZE)
        png = _encode_terrarium(lin)
        decoded = _decode_terrarium_png(png)
        # Terrarium 24-bit 编码（G 通道 1 unit = 1m），round 后误差应 < 1 m
        diff = np.abs(decoded - lin)
        assert np.nanmax(diff) < 1.5, f"max diff = {np.nanmax(diff)}"

    def test_ocean_rgb_is_nan(self):
        png = _encode_rgb(*_OCEAN_RGB)
        decoded = _decode_terrarium_png(png)
        assert np.all(np.isnan(decoded))

    def test_decode_wrong_shape_raises(self):
        # 128×128 的 PNG（非 256×256）应抛 DEMTileDecodeError
        arr = np.full((128, 128, 3), 128, dtype=np.uint8)
        img = Image.fromarray(arr, mode='RGB')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        with pytest.raises(DEMTileDecodeError):
            _decode_terrarium_png(buf.getvalue())

    def test_decode_corrupt_png_raises(self):
        with pytest.raises(DEMTileDecodeError):
            _decode_terrarium_png(b"\x89PNG\r\n\x1a\ncorrupt")


# ============================================================
# 4. AWS Terrain Provider（mock HTTP）
# ============================================================

class TestAWSTerrainProvider:

    def test_capability_public(self):
        cap = AWSTerrainProvider().capability()
        assert cap.provider_id == "aws_terrain"
        assert cap.auth == "public"
        assert cap.max_zoom == 14
        # ProviderCapability 用 auth 字段标识认证要求
        assert cap.auth in ("public", "api_key", "account")

    def test_unknown_provider_returns_none(self):
        assert dem_provider_by_id("nonexistent") is None

    def test_capabilities_includes_aws_terrain(self):
        caps = list_dem_capabilities()
        assert any(c["provider"] == "aws_terrain" for c in caps)

    @mock.patch("backend.services.dem_providers.aws_terrain.get_bytes")
    def test_fetch_2x1_tiles(self, mock_get, tmp_path):
        # 2 个 tile，左 50m、右 80m
        png_left = _encode_terrarium(np.full((TILE_SIZE, TILE_SIZE), 50.0))
        png_right = _encode_terrarium(np.full((TILE_SIZE, TILE_SIZE), 80.0))

        # bbox 让 z=12 落 2x1 tile
        bb = [112.93, 28.18, 112.97, 28.20]
        x_min, y_min, x_max, y_max = bbox_to_tile_index_range(bb, 12)

        def fake_get(url, **kwargs):
            # URL 格式: .../{z}/{x}/{y}.png
            parts = url.rsplit("/", 3)
            z, x, y = int(parts[1]), int(parts[2].split(".")[0]), int(parts[3].split(".")[0])
            assert (x, y) == (x_min, y_min) or (x, y) == (x_min + 1, y_min), url
            return png_left if x == x_min else png_right

        mock_get.side_effect = fake_get

        prov = AWSTerrainProvider()
        result = prov.fetch(bb, cache_dir=str(tmp_path))

        assert isinstance(result, DEMResult)
        assert result.provider == "aws_terrain"
        assert result.crs == "EPSG:4326"
        assert result.width > 0 and result.height > 0
        assert result.resolution > 0
        assert result.tile_count == 2
        assert result.tile_cache_hits == 0
        assert result.tile_cache_misses == 2
        assert result.min_elevation == pytest.approx(50.0, abs=1e-3)
        assert result.max_elevation == pytest.approx(80.0, abs=1e-3)
        # bounds 应在请求范围内（容许 ~1 像素 floor 误差）
        pixel_w = degrees_per_pixel(12)
        assert result.bounds[0] >= bb[0] - pixel_w
        assert result.bounds[2] <= bb[2] + pixel_w
        assert result.bounds[1] >= bb[1] - pixel_w
        assert result.bounds[3] <= bb[3] + pixel_w

        # 缓存命中：第二次同 bbox 调用 → hits 增加
        mock_get.reset_mock()
        result2 = prov.fetch(bb, cache_dir=str(tmp_path))
        assert result2.tile_cache_hits == 2
        assert result2.tile_cache_misses == 0
        # 第二次没有触网
        assert mock_get.call_count == 0

    @mock.patch("backend.services.dem_providers.aws_terrain.get_bytes")
    def test_partial_failure_continues_with_nodata(self, mock_get, tmp_path):
        # 2 个 tile：第 1 个返回 200，第 2 个抛 ProviderUnavailableError
        png_ok = _encode_terrarium(np.full((TILE_SIZE, TILE_SIZE), 100.0))

        bb = [112.93, 28.18, 112.97, 28.20]
        x_min, y_min, x_max, y_max = bbox_to_tile_index_range(bb, 12)

        def fake_get(url, **kwargs):
            from backend.services.data_providers.errors import ProviderUnavailableError
            parts = url.rsplit("/", 3)
            x = int(parts[2].split(".")[0])
            if x == x_min:
                return png_ok
            raise ProviderUnavailableError(f"mock 502 for tile {x}")

        mock_get.side_effect = fake_get
        prov = AWSTerrainProvider()
        result = prov.fetch(bb, cache_dir=str(tmp_path))

        assert result is not None
        # 部分 tile 缺失：note 应说明
        assert "部分 tile 下载失败" in result.note or "tile 下载失败" in result.note

    @mock.patch("backend.services.dem_providers.aws_terrain.get_bytes")
    def test_all_tiles_fail_raises(self, mock_get, tmp_path):
        from backend.services.data_providers.errors import ProviderUnavailableError

        bb = [112.93, 28.18, 112.97, 28.20]

        mock_get.side_effect = ProviderUnavailableError("mock all fail")
        prov = AWSTerrainProvider()
        with pytest.raises(DEMError):
            prov.fetch(bb, cache_dir=str(tmp_path))

    def test_out_of_range_bbox_raises(self, tmp_path):
        prov = AWSTerrainProvider()
        with pytest.raises(DEMAreaOutOfRangeError):
            prov.fetch([0, 86, 1, 87], cache_dir=str(tmp_path))

    @mock.patch("backend.services.dem_providers.aws_terrain.get_bytes")
    def test_corrupted_tile_response(self, mock_get, tmp_path):
        # tile 返回非 PNG
        bb = [112.93, 28.18, 112.97, 28.20]
        mock_get.return_value = b"<html>503 Service Unavailable</html>"
        prov = AWSTerrainProvider()
        with pytest.raises(DEMError):
            prov.fetch(bb, cache_dir=str(tmp_path))

    def test_compute_summary(self):
        # 全部 nodata
        arr = np.full((3, 3), np.nan)
        s = compute_summary(arr, np.nan)
        assert s["valid_count"] == 0
        assert s["min"] is None
        # 全部 100
        arr = np.full((3, 3), 100.0)
        s = compute_summary(arr, -9999.0)
        assert s["min"] == 100.0
        assert s["max"] == 100.0
        assert s["valid_count"] == 9
        assert s["nodata_pct"] == 0.0


# ============================================================
# 5. get_elevation_data 工具
# ============================================================

class TestGetElevationDataTool:

    def test_tool_registered(self):
        from backend.services.tools import tools
        # tools 列表出口统一包了执行历史包装层，按 name 匹配而非对象同一性
        assert any(getattr(t, "name", "") == "get_elevation_data" for t in tools)

    def test_bbox_parser_list(self):
        bb = _parse_dem_bbox([112.93, 28.18, 112.97, 28.20])
        assert bb == [112.93, 28.18, 112.97, 28.20]

    def test_bbox_parser_tuple(self):
        bb = _parse_dem_bbox((112.93, 28.18, 112.97, 28.20))
        assert bb == [112.93, 28.18, 112.97, 28.20]

    def test_bbox_parser_str_comma(self):
        bb = _parse_dem_bbox("112.93,28.18,112.97,28.20")
        assert bb == [112.93, 28.18, 112.97, 28.20]

    def test_bbox_parser_str_json(self):
        bb = _parse_dem_bbox("[112.93, 28.18, 112.97, 28.20]")
        assert bb == [112.93, 28.18, 112.97, 28.20]

    def test_bbox_parser_invalid_str_raises(self):
        from backend.services.data_providers.errors import DataProviderError
        with pytest.raises(DataProviderError):
            _parse_dem_bbox("only three, parts, here")

    def test_bbox_parser_wrong_type_raises(self):
        from backend.services.data_providers.errors import DataProviderError
        with pytest.raises(DataProviderError):
            _parse_dem_bbox(12345)

    @mock.patch("backend.services.dem_providers.aws_terrain.get_bytes")
    def test_end_to_end_returns_dict_and_writes_files(self, mock_get, tmp_path):
        png = _encode_terrarium(np.full((TILE_SIZE, TILE_SIZE), 200.0))
        mock_get.return_value = png

        r = get_elevation_data.invoke({"bbox": [112.93, 28.18, 112.97, 28.20]})
        # 工具返回值是 JSON 字符串
        assert isinstance(r, str)
        out = json.loads(r)
        assert out["ok"] is True
        assert out["provider"] == "aws_terrain"
        assert out["crs"] == "EPSG:4326"
        assert out["width"] > 0
        assert out["height"] > 0
        assert out["resolution"] > 0
        assert out["tile_count"] >= 1
        assert "geotiff_path" in out
        assert "preview_url" in out
        assert "layer_name" in out
        # data 字段是 summary
        assert "shape" in out["data"]
        assert out["data"]["max"] is not None
        # 高程极值应 ≈ 200m（mock 数据）
        assert abs(out["min_elevation"] - 200.0) < 1.0
        assert abs(out["max_elevation"] - 200.0) < 1.0

        # geotiff 落盘
        assert os.path.isfile(out["geotiff_path"])
        # preview PNG 落盘
        png_path = os.path.join(T._temp_output_dir, "uploads", out["preview_name"])
        assert os.path.isfile(png_path)
        # _pending_layer_ops 推送 dem_result
        assert any(op.get("action") == "dem_result" for op in _pending_layer_ops)

    @mock.patch("backend.services.dem_providers.aws_terrain.get_bytes")
    def test_end_toend_str_bbox(self, mock_get, tmp_path):
        png = _encode_terrarium(np.full((TILE_SIZE, TILE_SIZE), 50.0))
        mock_get.return_value = png
        r = get_elevation_data.invoke({
            "bbox": "112.93, 28.18, 112.97, 28.20",
            "resolution": 0.01,
        })
        out = json.loads(r)
        assert out["ok"] is True

    def test_unknown_provider_returns_error(self):
        r = get_elevation_data.invoke({
            "bbox": [112.93, 28.18, 112.97, 28.20],
            "provider": "no_such_provider",
        })
        out = json.loads(r)
        assert out["ok"] is False
        assert "未知 DEM Provider" in out["error"]

    def test_invalid_bbox_returns_error(self):
        r = get_elevation_data.invoke({"bbox": "not a bbox"})
        out = json.loads(r)
        assert out["ok"] is False

    def test_out_of_range_bbox_returns_error(self):
        r = get_elevation_data.invoke({"bbox": [0, 86, 1, 87]})
        out = json.loads(r)
        assert out["ok"] is False
        assert "纬度范围非法" in out.get("error", "") or "DEMAreaOutOfRangeError" in out.get("type", "")


# ============================================================
# 6. Provider Registry
# ============================================================

class TestDEMRegistry:

    def test_default_registry_has_aws_terrain(self):
        reg = DEMRegistry()
        provs = reg.all()
        assert any(p.provider_id == "aws_terrain" for p in provs)

    def test_register_requires_provider_id(self):
        reg = DEMRegistry()
        # DEMProvider 是 ABC，需用最小子类才能实例化（只填 provider_id 仍抛 NotImplementedError）
        class _EmptyProvider(DEMProvider):
            provider_id = ""  # 故意为空
            name = "empty"
            def fetch_tile(self, z, x, y, cache_dir):
                raise NotImplementedError
        with pytest.raises(ValueError):
            reg.register(_EmptyProvider())