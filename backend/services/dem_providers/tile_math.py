"""Web Mercator XYZ tile 数学与 DEM 网格重投影。

约定
----
- tile size = 256 px（AWS Terrain Tiles / OSM XYZ tile 的共同约定）
- world extent: lng ∈ [-180, 180]，lat ∈ [-85.05112877980659, +85.05112877980659]
  （Web Mercator 极区极限，超出无法用 Mercator 表示）
- 像素 (col, row) 中：col=0 是最西（左），row=0 是最北（上）。
  这与 numpy 数组 row=0 是最上一致；row 增大 → lat 减小 → 负的 pixel_height。
- mosaic 仿射变换遵循 GDAL/rasterio 风格并使用 EPSG:3857；裁剪/重采样输出 EPSG:4326。

错误
----
- DEMAreaOutOfRangeError：bbox 超出 Web Mercator 覆盖
- DEMTooManyTilesError：tile 数量超过安全上限（防止误用下载成千 tile 卡死服务）
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Iterable, Tuple

import numpy as np

from backend.services.dem_providers.errors import (
    DEMAreaOutOfRangeError,
    DEMResolutionUnsupportedError,
    DEMTileDecodeError,
    DEMTooManyTilesError,
)


# Web Mercator 极区极限（Web Mercator 在此纬度变成正无穷）
MERCATOR_MAX_LAT = 85.05112877980659
MERCATOR_MIN_LAT = -85.05112877980659
TILE_SIZE = 256

# 安全上限：单次下载的 tile 数量；超过即报错让用户缩小范围
DEFAULT_MAX_TILES = 512
DEFAULT_MAX_OUTPUT_PIXELS = 20_000_000
MAX_ZOOM = 30
# 默认 z 选择：bbox 较小（< 0.5°）→ 较细；bbox 较大 → 较粗（更少 tile）
DEFAULT_ZOOM = 12


# ============================================================
# 基本坐标变换（lng/lat ↔ world pixel ↔ tile index）
# ============================================================

def _clamp_lat(lat: float) -> float:
    return max(MERCATOR_MIN_LAT, min(MERCATOR_MAX_LAT, lat))


def _validate_zoom(z: int) -> int:
    if isinstance(z, bool) or not isinstance(z, int) or not 0 <= z <= MAX_ZOOM:
        raise ValueError(f"zoom 必须是 0 到 {MAX_ZOOM} 之间的整数。")
    return z


def _world_pixel_size(z: int) -> int:
    """z 级下整个世界地图的像素边长。"""
    z = _validate_zoom(z)
    return TILE_SIZE * (1 << z)


def lnglat_to_world_px(lng: float, lat: float, z: int) -> Tuple[float, float]:
    """(lng, lat) → (x_px, y_px)，亚像素精度（浮点）。"""
    lat_c = _clamp_lat(lat)
    n = _world_pixel_size(z)
    x = (lng + 180.0) / 360.0 * n
    lat_rad = math.radians(lat_c)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def world_px_to_lnglat(x_px: float, y_px: float, z: int) -> Tuple[float, float]:
    """(x_px, y_px) → (lng, lat)。"""
    n = _world_pixel_size(z)
    lng = x_px / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y_px / n))))
    return lng, lat


def lnglat_to_tile_index(lng: float, lat: float, z: int) -> Tuple[int, int]:
    """(lng, lat) → (tile_x, tile_y)，整数 tile 索引（floor 到 tile 西北角）。"""
    x_px, y_px = lnglat_to_world_px(lng, lat, z)
    return int(math.floor(x_px / TILE_SIZE)), int(math.floor(y_px / TILE_SIZE))


def tile_index_bounds_lnglat(tile_x: int, tile_y: int, z: int) -> Tuple[float, float, float, float]:
    """tile (z, x, y) → (min_lng, min_lat, max_lng, max_lat)。

    注意：tile 的东南角 (max_lng, max_lat) 是闭合到下一个 tile 的西北角减去 1 像素
    的中心点；但出于拼接方便，这里返回 tile 的几何边界（不含右下像素），
    即 x∈[tile_x*TILE_SIZE, (tile_x+1)*TILE_SIZE) 像素范围。
    """
    n = _world_pixel_size(z)
    x0_px = tile_x * TILE_SIZE
    y0_px = tile_y * TILE_SIZE
    x1_px = (tile_x + 1) * TILE_SIZE
    y1_px = (tile_y + 1) * TILE_SIZE
    min_lng, max_lat = world_px_to_lnglat(x0_px, y0_px, z)
    max_lng, min_lat = world_px_to_lnglat(x1_px, y1_px, z)
    return min_lng, min_lat, max_lng, max_lat


# ============================================================
# bbox 校验 / 规范化
# ============================================================

def validate_bbox(bbox) -> Tuple[float, float, float, float]:
    """校验并规范化 bbox = [minLng, minLat, maxLng, maxLat]（list/tuple 都可）。

    校验：
      - 4 个数，min<max，min≤180 且 max≥-180
      - 必须全部在 Web Mercator 极限内（lat ∈ [MERCATOR_MIN_LAT, MERCATOR_MAX_LAT]）
    """
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise DEMAreaOutOfRangeError(
            f"bbox 参数必须是 4 个数（minLng,minLat,maxLng,maxLat），收到 {bbox!r}",
        )
    if any(isinstance(value, bool) for value in bbox):
        raise DEMAreaOutOfRangeError("bbox 坐标必须是数值，不能使用布尔值。")
    try:
        min_lng, min_lat, max_lng, max_lat = (float(v) for v in bbox)
    except (TypeError, ValueError, OverflowError) as e:
        raise DEMAreaOutOfRangeError(f"bbox 含不可解析数值：{bbox!r}") from e
    if not (-180.0 <= min_lng < max_lng <= 180.0):
        raise DEMAreaOutOfRangeError(
            f"bbox 经度范围非法：minLng={min_lng}, maxLng={max_lng}",
            hint="经度需满足 -180 ≤ minLng < maxLng ≤ 180。",
        )
    if not (MERCATOR_MIN_LAT - 1e-9 <= min_lat < max_lat <= MERCATOR_MAX_LAT + 1e-9):
        raise DEMAreaOutOfRangeError(
            f"bbox 纬度范围非法：minLat={min_lat}, maxLat={max_lat}",
            hint=(f"Web Mercator 极限 lat ∈ [{MERCATOR_MIN_LAT:.4f}, "
                  f"{MERCATOR_MAX_LAT:.4f}]；超出此范围的极区无法用 XYZ tile 表示。"),
        )
    # 微小数值夹紧到合法区间（避免 85.0511 触发 off-by-1 失败）
    min_lat = _clamp_lat(min_lat)
    max_lat = _clamp_lat(max_lat)
    if min_lat >= max_lat:
        raise DEMAreaOutOfRangeError("bbox 在 Web Mercator 覆盖范围内没有有效纬度跨度。")
    return min_lng, min_lat, max_lng, max_lat


# ============================================================
# bbox → tile 列表
# ============================================================

def bbox_to_tile_index_range(
    bbox, z: int, *, max_tiles: int = DEFAULT_MAX_TILES,
) -> Tuple[int, int, int, int]:
    """bbox 在 z 级下覆盖的 tile 索引范围 (x_min, y_min, x_max, y_max)（含端点）。

    max_tiles：超过则抛 DEMTooManyTilesError（保护服务端）。
    """
    if isinstance(max_tiles, bool) or not isinstance(max_tiles, int) or max_tiles <= 0:
        raise DEMTooManyTilesError("max_tiles 必须是正整数。")
    z = _validate_zoom(z)
    min_lng, min_lat, max_lng, max_lat = validate_bbox(bbox)
    n = 1 << z
    x_min, y_min = lnglat_to_tile_index(min_lng, max_lat, z)   # NW corner
    # The east and south edges are exclusive for area coverage. If either edge
    # falls exactly on a tile boundary, the adjacent tile contributes no area.
    east_px, south_px = lnglat_to_world_px(max_lng, min_lat, z)
    x_max = int(math.floor(math.nextafter(east_px, -math.inf) / TILE_SIZE))
    y_max = int(math.floor(math.nextafter(south_px, -math.inf) / TILE_SIZE))
    # tile 索引必须在 [0, 2^z)
    x_min = max(0, min(x_min, n - 1))
    x_max = max(0, min(x_max, n - 1))
    y_min = max(0, min(y_min, n - 1))
    y_max = max(0, min(y_max, n - 1))
    nx = x_max - x_min + 1
    ny = y_max - y_min + 1
    total = nx * ny
    if total > max_tiles:
        raise DEMTooManyTilesError(
            f"请求范围在 z={z} 下需要 {total} 个 tile，超过单次上限 {max_tiles}。",
            hint="缩小空间范围、提高目标分辨率（更粗粒度）或降低 zoom 级别。",
        )
    return x_min, y_min, x_max, y_max


def iter_tile_indexes(x_min: int, y_min: int, x_max: int, y_max: int) -> Iterable[Tuple[int, int]]:
    """从 (x_min, y_min, x_max, y_max) 范围内 yield 所有 (x, y)，行优先（从北到南）。"""
    for y in range(y_min, y_max + 1):
        for x in range(x_min, x_max + 1):
            yield x, y


# ============================================================
# zoom 选择：根据 bbox 与目标分辨率挑 z
# ============================================================

def degrees_per_pixel(z: int) -> float:
    """每个像素多少度（沿赤道方向；非赤道会因 Mercator 拉伸有偏差，但本系统统一按
    赤道 360°/n_px 报告，因为 DEM 用经纬度 grid 表示，跨纬度仍按 256 px/° 切片。"""
    return 360.0 / _world_pixel_size(z)


def select_zoom(target_resolution_deg: float, *, z_min: int = 0, z_max: int = 14) -> int:
    """根据目标分辨率（度/像素）选 zoom。

    策略：选**最粗但仍满足 target** 的 z（避免下载过多 tile）。
    公式：degrees_per_pixel(z) = 360 / (256 * 2^z)，随 z 增大而减小（更细）。
    选最小 z 使 degrees_per_pixel(z) <= target_resolution_deg（保证下载的分辨率 ≥ target）。
    若 target_resolution_deg 比 degrees_per_pixel(z_max) 还细 → 强制返回 z_max。
    若 target_resolution_deg 比 degrees_per_pixel(z_min) 还粗 → 返回 z_min。
    """
    z_min = _validate_zoom(z_min)
    z_max = _validate_zoom(z_max)
    if z_min > z_max:
        raise ValueError("z_min 不能大于 z_max。")
    if isinstance(target_resolution_deg, bool) or not isinstance(target_resolution_deg, Real):
        raise ValueError("目标分辨率必须是有限数值。")
    try:
        target_resolution = float(target_resolution_deg)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("目标分辨率必须是有限数值。") from exc
    if not math.isfinite(target_resolution):
        raise ValueError("目标分辨率必须是有限数值。")
    if target_resolution <= 0:
        return max(z_min, min(DEFAULT_ZOOM, z_max))
    for z in range(z_min, z_max + 1):
        if degrees_per_pixel(z) <= target_resolution:
            return z
    return z_max


# ============================================================
# 拼接 / 裁剪 / 重采样
# ============================================================

def mosaic_tiles(
    tile_dict: dict,
    z: int,
    tile_x_min: int,
    tile_y_min: int,
    tile_x_max: int,
    tile_y_max: int,
) -> np.ndarray:
    """把 {(x, y): ndarray(TILE_SIZE, TILE_SIZE)} 拼成一张大 ndarray。

    输出形状：(tile_rows * TILE_SIZE, tile_cols * TILE_SIZE)。
    row 0 对应世界最北（即 tile_y = tile_y_min 的最上一行）。
    """
    n_rows = (tile_y_max - tile_y_min + 1) * TILE_SIZE
    n_cols = (tile_x_max - tile_x_min + 1) * TILE_SIZE
    mosaic = np.full((n_rows, n_cols), np.nan, dtype=np.float64)
    for y in range(tile_y_min, tile_y_max + 1):
        for x in range(tile_x_min, tile_x_max + 1):
            tile = tile_dict.get((x, y))
            if tile is None:
                continue
            tile = np.asarray(tile, dtype=np.float64)
            if tile.shape != (TILE_SIZE, TILE_SIZE):
                raise DEMTileDecodeError(
                    f"tile ({x}, {y}) 形状 {tile.shape}，期望 {(TILE_SIZE, TILE_SIZE)}。"
                )
            row = (y - tile_y_min) * TILE_SIZE
            col = (x - tile_x_min) * TILE_SIZE
            mosaic[row:row + TILE_SIZE, col:col + TILE_SIZE] = tile
    return mosaic


def mosaic_transform(
    tile_x_min: int, tile_y_min: int, z: int,
) -> Tuple[float, float, float, float, float, float]:
    """mosaic 数组的真实 EPSG:3857 affine transform。"""
    return mosaic_mercator_transform(tile_x_min, tile_y_min, z)


def mosaic_mercator_transform(
    tile_x_min: int, tile_y_min: int, z: int,
) -> Tuple[float, float, float, float, float, float]:
    """返回 XYZ 瓦片 mosaic 的真实 EPSG:3857 仿射变换。"""
    half_world = math.pi * 6378137.0
    pixel_size = (2.0 * half_world) / _world_pixel_size(z)
    left = -half_world + tile_x_min * TILE_SIZE * pixel_size
    top = half_world - tile_y_min * TILE_SIZE * pixel_size
    return (pixel_size, 0.0, left, 0.0, -pixel_size, top)


def _zoom_from_transform(transform) -> int:
    pixel_size = abs(float(transform[0]))
    if not math.isfinite(pixel_size) or pixel_size <= 0:
        raise DEMAreaOutOfRangeError("mosaic 仿射变换中的像素尺寸无效")
    world_pixels = (2.0 * math.pi * 6378137.0) / pixel_size
    return int(round(math.log2(world_pixels / TILE_SIZE)))


def reproject_mosaic_to_wgs84(
    data: np.ndarray,
    src_transform,
    target_bbox,
    target_resolution_deg: float = 0.0,
    *,
    z: int,
) -> Tuple[np.ndarray, tuple, tuple]:
    """把 EPSG:3857 XYZ mosaic 重投影并裁到 WGS84 bbox。"""
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject

    min_lng, min_lat, max_lng, max_lat = validate_bbox(target_bbox)
    if (isinstance(target_resolution_deg, bool)
            or not isinstance(target_resolution_deg, Real)
            or not math.isfinite(float(target_resolution_deg))
            or target_resolution_deg < 0):
        raise DEMResolutionUnsupportedError("目标分辨率必须是有限的非负度数")
    if not isinstance(data, np.ndarray) or data.ndim != 2 or not data.size:
        raise DEMTileDecodeError("DEM mosaic 必须是非空二维数组")
    if len(src_transform) != 6 or not all(math.isfinite(float(v)) for v in src_transform):
        raise DEMAreaOutOfRangeError("DEM mosaic 仿射变换无效")

    if target_resolution_deg > 0:
        desired_x = desired_y = float(target_resolution_deg)
    else:
        desired_x = degrees_per_pixel(z)
        center_lat = (min_lat + max_lat) / 2.0
        desired_y = desired_x * math.cos(math.radians(center_lat))
        desired_y = max(desired_y, desired_x * 0.01)

    width = max(1, int(math.ceil((max_lng - min_lng) / desired_x)))
    height = max(1, int(math.ceil((max_lat - min_lat) / desired_y)))
    if width * height > DEFAULT_MAX_OUTPUT_PIXELS:
        raise DEMTooManyTilesError(
            f"目标网格需要 {width * height:,} 个像素，超过单次上限 {DEFAULT_MAX_OUTPUT_PIXELS:,}。",
            hint="增大目标分辨率或缩小 bbox 后重试。",
        )
    xres = (max_lng - min_lng) / width
    yres = (max_lat - min_lat) / height
    dst_transform = Affine(xres, 0.0, min_lng, 0.0, -yres, max_lat)
    destination = np.full((height, width), np.nan, dtype=np.float32)

    reproject(
        source=np.asarray(data, dtype=np.float32),
        destination=destination,
        src_transform=Affine(*src_transform),
        src_crs="EPSG:3857",
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs="EPSG:4326",
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
        init_dest_nodata=True,
    )
    return destination, tuple(dst_transform)[:6], (min_lng, min_lat, max_lng, max_lat)


def clip_mosaic_to_bbox(
    data: np.ndarray, transform, target_bbox,
) -> Tuple[np.ndarray, tuple, tuple]:
    """重投影并裁剪 EPSG:3857 mosaic 到 WGS84 bbox。"""
    return reproject_mosaic_to_wgs84(
        data, transform, target_bbox, z=_zoom_from_transform(transform),
    )


def resample_to_resolution(
    data: np.ndarray, transform, target_bbox, target_resolution_deg: float,
) -> Tuple[np.ndarray, tuple, tuple]:
    """重投影 EPSG:3857 mosaic 到请求 bbox 的角度分辨率网格。"""
    return reproject_mosaic_to_wgs84(
        data, transform, target_bbox, target_resolution_deg,
        z=_zoom_from_transform(transform),
    )
