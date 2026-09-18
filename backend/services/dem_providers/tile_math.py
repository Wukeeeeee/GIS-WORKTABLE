"""Web Mercator XYZ tile 数学（纯函数 + numpy）。

约定
----
- tile size = 256 px（AWS Terrain Tiles / OSM XYZ tile 的共同约定）
- world extent: lng ∈ [-180, 180]，lat ∈ [-85.05112877980659, +85.05112877980659]
  （Web Mercator 极区极限，超出无法用 Mercator 表示）
- 像素 (col, row) 中：col=0 是最西（左），row=0 是最北（上）。
  这与 numpy 数组 row=0 是最上一致；row 增大 → lat 减小 → 负的 pixel_height。
- affine transform 遵循 GDAL/rasterio 风格：
    X = a * col + b * row + c    (c = top_left_lng)
    Y = d * col + e * row + f    (f = top_left_lat, e < 0)
  即 `transform = (pixel_width, 0, top_left_lng, 0, -pixel_height, top_left_lat)`

所有函数都接受并返回 (lng, lat) WGS84 度；不涉及 CRS 转换（输入/输出都是 EPSG:4326）。

错误
----
- DEMAreaOutOfRangeError：bbox 超出 Web Mercator 覆盖
- DEMTooManyTilesError：tile 数量超过安全上限（防止误用下载成千 tile 卡死服务）
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Tuple

import numpy as np

from backend.services.dem_providers.errors import (
    DEMAreaOutOfRangeError,
    DEMTooManyTilesError,
)


# Web Mercator 极区极限（Web Mercator 在此纬度变成正无穷）
MERCATOR_MAX_LAT = 85.05112877980659
MERCATOR_MIN_LAT = -85.05112877980659
TILE_SIZE = 256

# 安全上限：单次下载的 tile 数量；超过即报错让用户缩小范围
DEFAULT_MAX_TILES = 512
# 默认 z 选择：bbox 较小（< 0.5°）→ 较细；bbox 较大 → 较粗（更少 tile）
DEFAULT_ZOOM = 12


# ============================================================
# 基本坐标变换（lng/lat ↔ world pixel ↔ tile index）
# ============================================================

def _clamp_lat(lat: float) -> float:
    return max(MERCATOR_MIN_LAT, min(MERCATOR_MAX_LAT, lat))


def _world_pixel_size(z: int) -> int:
    """z 级下整个世界地图的像素边长。"""
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
    try:
        min_lng, min_lat, max_lng, max_lat = (float(v) for v in bbox)
    except (TypeError, ValueError) as e:
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
    if min_lat < MERCATOR_MIN_LAT:
        min_lat = MERCATOR_MIN_LAT
    if max_lat > MERCATOR_MAX_LAT:
        max_lat = MERCATOR_MAX_LAT
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
    min_lng, min_lat, max_lng, max_lat = validate_bbox(bbox)
    n = 1 << z
    x_min, y_min = lnglat_to_tile_index(min_lng, max_lat, z)   # NW corner
    x_max, y_max = lnglat_to_tile_index(max_lng, min_lat, z)   # SE corner
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

def meters_per_pixel(lat: float, z: int) -> float:
    """Web Mercator 在指定纬度的地面分辨率（米/像素，赤道处最小、两极放大）。"""
    n = _world_pixel_size(z)
    return 156543.03392 * math.cos(math.radians(lat)) / n


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
    if target_resolution_deg <= 0:
        return DEFAULT_ZOOM
    for z in range(z_min, z_max + 1):
        if degrees_per_pixel(z) <= target_resolution_deg:
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
                # 防止 provider 返回意外形状；按左上对齐补/截
                tmp = np.full((TILE_SIZE, TILE_SIZE), np.nan, dtype=np.float64)
                h = min(TILE_SIZE, tile.shape[0])
                w = min(TILE_SIZE, tile.shape[1])
                tmp[:h, :w] = tile[:h, :w]
                tile = tmp
            row = (y - tile_y_min) * TILE_SIZE
            col = (x - tile_x_min) * TILE_SIZE
            mosaic[row:row + TILE_SIZE, col:col + TILE_SIZE] = tile
    return mosaic


def mosaic_transform(
    tile_x_min: int, tile_y_min: int, z: int,
) -> Tuple[float, float, float, float, float, float]:
    """mosaic 数组对应的 affine transform。

    mosaic 数组的 (col=0, row=0) 像素中心在世界像素坐标 (x0_px + 0.5, y0_px + 0.5)
    —— 但为简化与 rasterio 一致，使用 tile 的几何西北角作为 top_left：
        X = a * col + c
        Y = e * row + f    (e < 0)
    """
    x0_px, y0_px = tile_x_min * TILE_SIZE, tile_y_min * TILE_SIZE
    top_left_lng, top_left_lat = world_px_to_lnglat(x0_px, y0_px, z)
    pixel_width = degrees_per_pixel(z)
    pixel_height = -pixel_width  # 北向上：row 增大 → lat 减小
    a = pixel_width
    b = 0.0
    c = top_left_lng
    d = 0.0
    e = pixel_height
    f = top_left_lat
    return (a, b, c, d, e, f)


def clip_mosaic_to_bbox(
    data: np.ndarray, transform, target_bbox,
) -> Tuple[np.ndarray, tuple, tuple]:
    """把 mosaic 数组裁剪到 target_bbox（包含边界）。

    返回 (clipped_data, new_transform, new_bounds)。
    target_bbox = [minLng, minLat, maxLng, maxLat]。
    """
    a, b, c, d, e, f = transform
    min_lng, min_lat, max_lng, max_lat = validate_bbox(target_bbox)

    # 像素中心到 (lng, lat)：col → lng = a*col + c + a/2（用中心更稳）。
    # 但 GDAL/rasterio 默认 col=0 是左上角（非中心），保持一致。
    # row/col → (lng, lat)：col = (lng - c) / a；row = (lat - f) / e（e<0）
    col_min = max(0, int(math.floor((min_lng - c) / a)))
    col_max = min(data.shape[1] - 1, int(math.ceil((max_lng - c) / a)) - 1)
    # row：e < 0，所以 (lat - f) / e；min_lat → row_max，max_lat → row_min
    row_max = min(data.shape[0] - 1, int(math.floor((min_lat - f) / e)))
    row_min = max(0, int(math.ceil((max_lat - f) / e)))
    if col_min > col_max or row_min > row_max:
        # bbox 与 mosaic 无重叠（理论上前面已保证；保险起见返回 1x1 NaN）
        return np.full((1, 1), np.nan, dtype=np.float64), (a, b, c, d, e, f), (
            min_lng, min_lat, max_lng, max_lat,
        )

    clipped = data[row_min:row_max + 1, col_min:col_max + 1].copy()
    new_c = c + a * col_min
    new_f = f + e * row_min
    new_transform = (a, b, new_c, d, e, new_f)
    # 裁剪后真实 bounds（与切片起止一致）
    h, w = clipped.shape
    new_min_lng = new_c
    new_max_lng = new_c + a * w
    new_max_lat = new_f
    new_min_lat = new_f + e * h
    new_bounds = (new_min_lng, new_min_lat, new_max_lng, new_max_lat)
    return clipped, new_transform, new_bounds


def resample_to_resolution(
    data: np.ndarray, transform, target_bbox, target_resolution_deg: float,
) -> Tuple[np.ndarray, tuple, tuple]:
    """按目标分辨率（度/像素）重采样 data 到与 target_bbox 对齐的 grid。

    规则 grid 二线性插值：先把数据翻转成 lat 递增（南→北）以满足 np.interp 的单调
    递增要求；先沿列（lng）插值得到 (height, width_dst_col_temp)，再沿行（lat）插值
    得到 (height, width)。

    target_resolution_deg == 0 或 None 时只裁剪不重采样。
    """
    if not target_resolution_deg or target_resolution_deg <= 0:
        return clip_mosaic_to_bbox(data, transform, target_bbox)
    a, b, c, d, e, f = transform
    min_lng, min_lat, max_lng, max_lat = validate_bbox(target_bbox)

    width = max(1, int(math.ceil((max_lng - min_lng) / target_resolution_deg)))
    height = max(1, int(math.ceil((max_lat - min_lat) / target_resolution_deg)))

    # 源 grid：col=0..src_w-1 → lng=c+a*i；row=0..src_h-1 → lat=f+e*i（lat 递减）
    src_cols = c + a * np.arange(data.shape[1], dtype=np.float64)
    src_rows = f + e * np.arange(data.shape[0], dtype=np.float64)
    # 翻成 lat 递增（南→北）方便 np.interp
    data_south_up = data[::-1, :]
    rows_south_up = src_rows[::-1]

    # 目标 grid
    dst_cols = min_lng + target_resolution_deg * np.arange(width, dtype=np.float64)
    dst_rows = max_lat - target_resolution_deg * np.arange(height, dtype=np.float64)
    dst_rows_south_up = dst_rows[::-1]

    # 沿 col（lng）插值：对每一行（lat_south_up），在 src_cols 上插值到 dst_cols
    # 结果 shape = (src_rows, width)
    col_interp = np.empty((data_south_up.shape[0], width), dtype=np.float64)
    for r in range(data_south_up.shape[0]):
        col_interp[r, :] = np.interp(
            dst_cols, src_cols, data_south_up[r, :],
            left=np.nan, right=np.nan,
        )
    # 沿 row（lat）插值：对每一列（dst col），在 rows_south_up 上插值到 dst_rows_south_up
    # 结果 shape = (height, width)
    out = np.empty((height, width), dtype=np.float64)
    for c_idx in range(width):
        out[:, c_idx] = np.interp(
            dst_rows_south_up, rows_south_up, col_interp[:, c_idx],
            left=np.nan, right=np.nan,
        )

    new_transform = (
        target_resolution_deg, 0.0, float(min_lng),
        0.0, -target_resolution_deg, float(max_lat),
    )
    new_bounds = (
        float(min_lng), float(min_lat),
        float(min_lng + target_resolution_deg * width),
        float(max_lat - target_resolution_deg * height),
    )
    return out, new_transform, new_bounds