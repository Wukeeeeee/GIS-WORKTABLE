"""AWS Terrain Tiles DEM Provider（默认实现，免 Key）。

数据源
------
- AWS Open Data Terrain Tiles：https://registry.opendata.aws/terrain-tiles/
- S3 endpoint：https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png
- 编码：Terrarium PNG，256×256 RGB
  解码公式：elevation_m = (R * 256 + G + B / 256) - 32768
- 来源：SRTM 等高程数据；上游使用 R=0 标记无数据，解码时置 NaN。
  其余 RGB 按 Terrarium 公式解码，保留零米及负高程。

覆盖
----
- 全球（Web Mercator 极限 lat ∈ ±85.0511）
- z ∈ [0, 14]（z=14 在赤道 ≈ 9.5 m/px；SRTM 实际分辨率 ≈ 30 m/px）
- 不需要 API Key，直接走 S3 公开 endpoint

合规
----
- 全部数据来自公开 AWS Open Data（非爬虫），与 Arnis 项目（OSM/terrarium 渲染）无任何代码复用
"""
from __future__ import annotations

import io
from typing import Tuple

import numpy as np

from backend.services.data_providers.http import get_bytes
from backend.services.dem_providers.base import DEMProvider
from backend.services.dem_providers.errors import DEMTileDecodeError


# Terrarium 解码常量
_TERRARIUM_OFFSET = 32768.0  # elevation = (R*256 + G + B/256) - 32768
_TILE_PNG_MAX_BYTES = 4 * 1024 * 1024  # 单 tile 上限，正常 < 50 KB


def _decode_terrarium_png(png_bytes: bytes) -> np.ndarray:
    """Terrarium PNG → ndarray(256, 256)，单位米，无数据 → NaN。

    公式：elev_m = R*256 + G + B/256 - 32768
    上游无数据标记：R = 0 → NaN。
    """
    from PIL import Image
    try:
        with Image.open(io.BytesIO(png_bytes)) as img:
            if img.size != (256, 256):
                raise DEMTileDecodeError(
                    f"AWS Terrain PNG 形状异常：{img.size}（期望 (256, 256)）",
                    hint="Provider 可能更新了 tile 大小，需适配。",
                )
            arr = np.asarray(img.convert("RGB"), dtype=np.float64)
    except DEMTileDecodeError:
        raise
    except Exception as e:
        raise DEMTileDecodeError(
            f"AWS Terrain PNG 解码失败：{type(e).__name__}: {str(e)[:120]}",
            hint="文件可能损坏，请清除缓存后重试。",
        ) from e
    R = arr[:, :, 0]
    G = arr[:, :, 1]
    B = arr[:, :, 2]
    elev = (R * 256.0 + G + B / 256.0) - _TERRARIUM_OFFSET
    elev = np.where(R == 0, np.nan, elev)
    return elev.astype(np.float64)


class AWSTerrainProvider(DEMProvider):
    """AWS Terrain Tiles（Terrarium 格式，SRTM 派生），公开免 Key。"""

    provider_id = "aws_terrain"
    name = "AWS Terrain Tiles"
    description = "AWS Open Data 全球高程瓦片（SRTM 1-arcsec 派生，Terrarium PNG 格式）"
    requires_key = False
    auth_note = "公开免 Key（AWS Open Data S3）"
    homepage = "https://registry.opendata.aws/terrain-tiles/"
    min_zoom = 0
    max_zoom = 14
    default_zoom = 12
    coverage = "全球（Web Mercator 极限 lat ≤ ±85.0511；SRTM 在 lat > ±60 数据稀疏）"
    resolution_note = (
        "z=12 默认 ≈ 78 m/px（赤道）；z=14 最细 ≈ 9.5 m/px（赤道）；"
        "SRTM 1-arcsec 实际 ≈ 30 m/px"
    )

    URL_TEMPLATE = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"

    # ----- Provider 抽象实现 -----

    def fetch_tile(self, z: int, x: int, y: int, cache_dir: str) -> np.ndarray:
        tile, _hit = self._load_or_download(z, x, y, cache_dir)
        return tile

    def _fetch_tile_with_cache(self, z: int, x: int, y: int, cache_dir: str) -> Tuple[np.ndarray, bool]:
        """重写以区分 hit/miss（基类默认实现无法区分）。"""
        return self._load_or_download(z, x, y, cache_dir)

    # ----- 内部 helper -----

    def _load_or_download(self, z: int, x: int, y: int, cache_dir: str) -> Tuple[np.ndarray, bool]:
        from backend.services.dem_providers import cache as cache_mod

        if any(isinstance(value, bool) or not isinstance(value, int) for value in (z, x, y)):
            raise ValueError("tile 的 z、x、y 必须是整数。")
        if not self.min_zoom <= z <= self.max_zoom:
            raise ValueError(f"tile zoom 必须在 {self.min_zoom} 到 {self.max_zoom} 之间。")
        tile_count = 1 << z
        if not (0 <= x < tile_count and 0 <= y < tile_count):
            raise ValueError(f"tile 坐标超出 z={z} 的范围：x、y 应在 [0, {tile_count})。")

        cached = cache_mod.load_cached_tile(cache_dir, self.provider_id, z, x, y)
        if cached is not None:
            try:
                return _decode_terrarium_png(cached), True
            except DEMTileDecodeError:
                # 当 miss 处理；下载成功后原子替换，避免误删并发写入的新版本。
                pass

        url = self.URL_TEMPLATE.format(z=z, x=x, y=y)
        png = get_bytes(url, timeout=20.0, max_bytes=_TILE_PNG_MAX_BYTES, retries=2)
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise DEMTileDecodeError(
                f"AWS Terrain 返回不是有效 PNG：{url[:80]}…",
                hint="Provider 升级或返回了非 PNG 内容，请重试。",
            )
        tile = _decode_terrarium_png(png)
        # 写缓存（失败不影响本次返回）
        cache_mod.save_tile_atomic(cache_dir, self.provider_id, z, x, y, png)
        return tile, False
