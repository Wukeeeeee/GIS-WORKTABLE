"""DEM Provider 抽象基类 + DEMResult 数据模型 + 注册表。

设计
----
- 子类只需实现 `fetch_tile(z, x, y, cache_dir) -> ndarray(256, 256)`，单位米。
  通用 fetch(bbox, resolution, cache_dir) 由基类实现：
    1) bbox → tile 范围（tile_math.bbox_to_tile_index_range）
    2) 逐 tile 调用 fetch_tile（缓存命中返回已下载 PNG，否则下载→缓存→解码）
    3) 拼接为 mosaic → 裁剪到 bbox → 按 target_resolution 重采样
    4) 构造 DEMResult（含 CRS/transform/bounds/nodata）
- DEMResult 同时携带 ndarray + GDAL 风格 affine + bounds + nodata，
  上层 GIS 工具（dem_analysis / extract_contours / terrain_profile）可直接接力。
- 注册表懒加载：默认注册 AWS Terrain Tiles Provider（公开免 Key）。
"""
from __future__ import annotations

import io
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.services.dem_providers import tile_math
from backend.services.dem_providers.errors import (
    DEMAreaOutOfRangeError,
    DEMError,
    DEMTileDecodeError,
    DEMTooManyTilesError,
)


# ============================================================
# Provider 能力描述（给前端/接口/Agent 路由用）
# ============================================================

@dataclass
class ProviderCapability:
    """某个 DEM Provider 的能力描述。"""
    provider_id: str
    name: str
    description: str
    auth: str                       # "public" / "api_key" / "account"
    auth_note: str = ""
    homepage: str = ""
    min_zoom: int = 0
    max_zoom: int = 14
    default_zoom: int = 12
    coverage: str = ""              # 覆盖范围描述
    resolution_note: str = ""       # 分辨率说明
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "provider": self.provider_id,
            "name": self.name,
            "description": self.description,
            "auth": self.auth,
            "auth_note": self.auth_note,
            "homepage": self.homepage,
            "min_zoom": self.min_zoom,
            "max_zoom": self.max_zoom,
            "default_zoom": self.default_zoom,
            "coverage": self.coverage,
            "resolution_note": self.resolution_note,
            "note": self.note,
        }


# ============================================================
# DEM 结果（核心数据契约）
# ============================================================

@dataclass
class DEMResult:
    """DEM 数据获取结果。

    Attributes:
        provider: 实际使用的 Provider id
        data: 高程 ndarray（H, W），单位米；NaN 表示 nodata
        crs: 坐标系字符串（默认 EPSG:4326）
        transform: GDAL 风格 affine (a, b, c, d, e, f)，a/e 是像素宽/高（度）
        bounds: (min_lng, min_lat, max_lng, max_lat)
        width: 像素宽
        height: 像素高
        resolution: 度/像素（与 |a| 相等）
        min_elevation / max_elevation: 米
        nodata: 数据中的 nodata 值（默认 NaN）
        tile_count: 涉及的 tile 总数
        tile_cache_hits / tile_cache_misses: 缓存命中/未命中计数
        source_url: 数据源 URL 模板（用于审计/cite）
        note: 附加说明（如「部分 tile 缺失」「超出 SRTM 覆盖」等）
    """
    provider: str
    data: np.ndarray
    crs: str = "EPSG:4326"
    transform: tuple = (1.0, 0.0, 0.0, 0.0, -1.0, 1.0)
    bounds: tuple = (0.0, 0.0, 0.0, 0.0)
    width: int = 0
    height: int = 0
    resolution: float = 0.0
    min_elevation: float = 0.0
    max_elevation: float = 0.0
    nodata: float = float("nan")
    tile_count: int = 0
    tile_cache_hits: int = 0
    tile_cache_misses: int = 0
    source_url: str = ""
    note: str = ""
    elevation_summary: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.width == 0 and self.data is not None:
            self.width = int(self.data.shape[1])
        if self.height == 0 and self.data is not None:
            self.height = int(self.data.shape[0])
        if not self.elevation_summary and self.data is not None:
            self.elevation_summary = compute_summary(self.data, self.nodata)

    def to_dict(self) -> dict:
        """返回 LLM 友好的 dict（data 仅摘要，不塞 ndarray 原文进 token）。"""
        return {
            "provider": self.provider,
            "crs": self.crs,
            "transform": list(self.transform),
            "bounds": list(self.bounds),
            "width": self.width,
            "height": self.height,
            "resolution": self.resolution,
            "min_elevation": self.min_elevation,
            "max_elevation": self.max_elevation,
            "nodata": self.nodata if (self.nodata == self.nodata) else None,  # NaN→None
            "tile_count": self.tile_count,
            "tile_cache_hits": self.tile_cache_hits,
            "tile_cache_misses": self.tile_cache_misses,
            "source_url": self.source_url,
            "note": self.note,
            "elevation_summary": self.elevation_summary,
            "data": self.elevation_summary,  # 兼容 user_query #5 要求的 data 字段
        }


def compute_summary(data: np.ndarray, nodata: float) -> dict:
    """统计高程数据：shape / min / max / mean / std / nodata_pct / valid_count。

    单一值（NaN）用 None 表示，便于 JSON 序列化。
    """
    arr = np.asarray(data, dtype=np.float64)
    total = int(arr.size)
    if nodata == nodata:  # not NaN
        valid = arr[arr != nodata]
    else:
        valid = arr[np.isfinite(arr)]
    invalid = total - int(valid.size)
    summary = {
        "shape": [int(arr.shape[0]), int(arr.shape[1])] if arr.ndim == 2 else list(arr.shape),
        "min": float(np.min(valid)) if valid.size else None,
        "max": float(np.max(valid)) if valid.size else None,
        "mean": float(np.mean(valid)) if valid.size else None,
        "std": float(np.std(valid)) if valid.size else None,
        "valid_count": int(valid.size),
        "invalid_count": invalid,
        "nodata_pct": float(invalid / total) if total else 0.0,
    }
    return summary


# ============================================================
# Provider 抽象基类
# ============================================================

class DEMProvider(ABC):
    """DEM Provider 抽象基类。

    子类必须：
      1) 设置 provider_id / name / description / min_zoom / max_zoom / default_zoom
      2) 实现 fetch_tile(z, x, y, cache_dir) -> ndarray(256, 256)，单位米；
         内部应处理缓存命中 / 下载 / 解码 / 异常映射。
      3) 可选覆盖 capability() 自定义字段。

    基类提供的通用 fetch(bbox, resolution, cache_dir)：
      调用顺序：bbox 校验 → tile 范围 → 逐 tile fetch_tile → 拼接 → 裁剪 → 可选重采样 → 构造 DEMResult。
    """

    provider_id: str = ""
    name: str = ""
    description: str = ""
    requires_key: bool = False
    auth_note: str = ""
    homepage: str = ""
    min_zoom: int = 0
    max_zoom: int = 14
    default_zoom: int = 12
    coverage: str = ""
    resolution_note: str = ""

    @abstractmethod
    def fetch_tile(self, z: int, x: int, y: int, cache_dir: str) -> np.ndarray:
        """取单个 256x256 tile 的高程数据（米）。

        返回 ndarray(TILE_SIZE, TILE_SIZE)，dtype=float。
        内部实现可调用 self._cache_or_download(z, x, y, cache_dir, _decode_fn)。
        """

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self.provider_id,
            name=self.name,
            description=self.description,
            auth="api_key" if self.requires_key else "public",
            auth_note=self.auth_note,
            homepage=self.homepage,
            min_zoom=self.min_zoom,
            max_zoom=self.max_zoom,
            default_zoom=self.default_zoom,
            coverage=self.coverage,
            resolution_note=self.resolution_note,
        )

    # ----- 通用 fetch：bbox + resolution → DEMResult -----

    def fetch(
        self,
        bbox,
        target_resolution_deg: float = 0.0,
        cache_dir: Optional[str] = None,
        max_tiles: int = tile_math.DEFAULT_MAX_TILES,
    ) -> DEMResult:
        """按 bbox 获取 DEM。返回 DEMResult（详见类 docstring）。

        target_resolution_deg = 0 表示按当前 zoom 级别的原生分辨率（不重采样）。
        cache_dir 为空时使用 backend.services.dem_providers.cache.default_cache_root()。
        """
        from backend.services.dem_providers import cache as cache_mod
        if not cache_dir:
            cache_dir = cache_mod.default_cache_root()

        bb = tile_math.validate_bbox(bbox)
        # 决定 zoom
        z = self._decide_zoom(target_resolution_deg)
        # bbox → tile 范围
        x_min, y_min, x_max, y_max = tile_math.bbox_to_tile_index_range(
            bb, z, max_tiles=max_tiles,
        )
        # 逐 tile 抓取
        tile_dict: Dict[Tuple[int, int], np.ndarray] = {}
        hits = misses = 0
        failed: List[Tuple[int, int, str]] = []
        for x, y in tile_math.iter_tile_indexes(x_min, y_min, x_max, y_max):
            try:
                tile, hit = self._fetch_tile_with_cache(z, x, y, cache_dir)
                tile_dict[(x, y)] = tile
                if hit:
                    hits += 1
                else:
                    misses += 1
            except DEMError:
                raise
            except Exception as e:
                # 单 tile 失败不能毁掉整次请求：跳过该 tile 但记录
                failed.append((x, y, str(e)[:200]))
        if not tile_dict:
            raise DEMAreaOutOfRangeError(
                "未能从 Provider 获取任何 tile（所有 tile 均下载失败或越界）。",
                hint="请检查网络后重试，或缩小空间范围。",
            )

        mosaic = tile_math.mosaic_tiles(tile_dict, z, x_min, y_min, x_max, y_max)
        transform = tile_math.mosaic_transform(x_min, y_min, z)

        # 裁剪到目标 bbox
        if target_resolution_deg and target_resolution_deg > 0:
            clipped, new_transform, new_bounds = tile_math.resample_to_resolution(
                mosaic, transform, bb, target_resolution_deg,
            )
        else:
            clipped, new_transform, new_bounds = tile_math.clip_mosaic_to_bbox(
                mosaic, transform, bb,
            )

        a = new_transform[0]
        resolution = abs(a) if a else tile_math.degrees_per_pixel(z)
        valid_mask = np.isfinite(clipped)
        if valid_mask.any():
            vmin = float(np.min(clipped[valid_mask]))
            vmax = float(np.max(clipped[valid_mask]))
        else:
            vmin = vmax = float("nan")

        notes = []
        if failed:
            notes.append(
                f"部分 tile 下载失败（{len(failed)}/{(x_max - x_min + 1) * (y_max - y_min + 1)} 个，"
                f"已作为 nodata 处理）：" + "；".join(f"({x},{y}):{err}" for x, y, err in failed[:5])
            )
        if bb[1] < -60.0 or bb[3] > 60.0:
            notes.append("范围涉及 SRTM 覆盖边缘或之外（lat > ±60），部分区域可能返回海洋/无效数据。")

        return DEMResult(
            provider=self.provider_id,
            data=clipped,
            crs="EPSG:4326",
            transform=new_transform,
            bounds=new_bounds,
            width=int(clipped.shape[1]),
            height=int(clipped.shape[0]),
            resolution=resolution,
            min_elevation=vmin,
            max_elevation=vmax,
            nodata=float("nan"),
            tile_count=int((x_max - x_min + 1) * (y_max - y_min + 1)),
            tile_cache_hits=hits,
            tile_cache_misses=misses,
            source_url=self.homepage,
            note=" ".join(notes) if notes else "",
        )

    # ----- 内部 helper -----

    def _decide_zoom(self, target_resolution_deg: float) -> int:
        """决定本次 fetch 使用的 zoom。

        优先级：target_resolution > 0 → 选最高满足条件的 zoom；
                否则用 self.default_zoom（夹到 [min_zoom, max_zoom]）。
        """
        if target_resolution_deg and target_resolution_deg > 0:
            z = tile_math.select_zoom(
                target_resolution_deg,
                z_min=self.min_zoom,
                z_max=self.max_zoom,
            )
        else:
            z = self.default_zoom
        return max(self.min_zoom, min(self.max_zoom, z))

    def _fetch_tile_with_cache(
        self, z: int, x: int, y: int, cache_dir: str,
    ) -> Tuple[np.ndarray, bool]:
        """调用 fetch_tile，记录是否走缓存。

        子类可重写此方法以提供「先 cache 命中后调用子类的 fetch_tile」的简化逻辑。
        默认实现：每次都调 fetch_tile，由子类在内部决定缓存命中（返回的 ndarray 与
        原始 PNG 字节可一致 / 可不同；这里只关心是否触网）。
        """
        # 默认无法区分 hit/miss；子类可重写
        tile = self.fetch_tile(z, x, y, cache_dir)
        return tile, False


# ============================================================
# 注册表
# ============================================================

class DEMRegistry:
    """DEM Provider 注册表：集中管理 + 能力检测。"""

    def __init__(self):
        self._providers: Dict[str, DEMProvider] = {}
        self._installed = False

    def register(self, provider: DEMProvider) -> None:
        if not provider.provider_id:
            raise ValueError("DEMProvider 必须定义 provider_id")
        self._providers[provider.provider_id] = provider

    def _ensure_installed(self) -> None:
        if self._installed:
            return
        self._installed = True
        # 延迟 import，避免顶层加载 aws_terrain（其依赖 PIL/numpy/requests）
        from backend.services.dem_providers.aws_terrain import AWSTerrainProvider
        self.register(AWSTerrainProvider())

    def get(self, provider_id: str) -> DEMProvider:
        self._ensure_installed()
        pid = str(provider_id or "").strip().lower()
        if pid not in self._providers:
            raise KeyError(pid)
        return self._providers[pid]

    def all(self) -> List[DEMProvider]:
        self._ensure_installed()
        return list(self._providers.values())

    def capabilities(self) -> List[ProviderCapability]:
        return [p.capability() for p in self.all()]

    def capable_public(self) -> List[DEMProvider]:
        """公开免 Key 的 Provider（优先使用）。"""
        return [p for p in self.all() if not p.requires_key]


_registry = DEMRegistry()


def get_dem_registry() -> DEMRegistry:
    return _registry


def list_dem_capabilities() -> list:
    """所有已注册 Provider 的能力（dict 列表，供前端/接口展示）。"""
    return [c.to_dict() for c in _registry.capabilities()]


def dem_provider_by_id(provider_id: str) -> Optional[DEMProvider]:
    try:
        return _registry.get(provider_id)
    except KeyError:
        return None