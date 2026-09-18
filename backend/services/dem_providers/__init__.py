"""按需数字高程（DEM）数据获取与处理子包。

设计目标
--------
- 按需获取：不预下载全球 DEM，只在用户指定区域时下载所需 tile。
- Provider 抽象：以 Web Mercator XYZ tile 协议为公共接口，便于后续接入
  USGS 3DEP / OpenTopography / SRTM-via-CGIAR 等公开数据源。
- 缓存：tile 级本地缓存，原子写入（先 .tmp 再 rename），下载失败不破坏已有缓存。
- 统一返回：DEMResult 同时携带 ndarray + CRS + affine transform + bounds + nodata，
  上层 GIS 工具可直接接力（dem_analysis / extract_contours / terrain_profile）。

模块
----
- errors.py       错误类型（复用 data_providers/errors 体系，扩展 DEM 专属）
- tile_math.py    Web Mercator tile 数学（纯函数）
- cache.py        tile 级磁盘缓存
- base.py         DEMProvider ABC + DEMResult + 注册表
- aws_terrain.py  默认实现：AWS Terrain Tiles / Terrarium（SRTM 派生，免 Key）

不依赖 LLM / 前端 / LangGraph；确定性程序代码。
"""

from backend.services.dem_providers.base import (
    DEMProvider,
    DEMRegistry,
    DEMResult,
    ProviderCapability,
    get_dem_registry,
    list_dem_capabilities,
    dem_provider_by_id,
)
from backend.services.dem_providers.errors import (
    DEMError,
    DEMTileDecodeError,
    DEMAreaOutOfRangeError,
    DEMResolutionUnsupportedError,
    DEMTooManyTilesError,
)

__all__ = [
    # ABC / 数据模型 / 注册表
    "DEMProvider",
    "DEMRegistry",
    "DEMResult",
    "ProviderCapability",
    "get_dem_registry",
    "list_dem_capabilities",
    "dem_provider_by_id",
    # errors
    "DEMError",
    "DEMTileDecodeError",
    "DEMAreaOutOfRangeError",
    "DEMResolutionUnsupportedError",
    "DEMTooManyTilesError",
]