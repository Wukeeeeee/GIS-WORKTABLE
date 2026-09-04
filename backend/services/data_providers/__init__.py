"""
GIS WorkTable — GIS 开放数据发现与获取（Data Discovery / Download / Import）

分层：
    data_discovery.py        数据发现入口（识别→选择 Provider→搜索→下载→导入）
    data_providers/
        base.py               DataProvider 抽象 + 注册表 + 能力列表
        models.py             统一数据模型与类型常量
        errors.py             明确错误类型（禁止静默失败）
        http.py               统一 HTTP（超时 / 重试次数限制 / 大小限制）
        geocode.py            地名 → 空间范围（EPSG:4326 bbox）
        storage.py            GIS 文件落盘 + 完整性校验 + CRS + metadata
        osm_provider.py       OpenStreetMap（Overpass 官方 API，公开免认证）
        copernicus_provider.py  Copernicus Data Space（catalog 发现，下载需账号）
        usgs_provider.py        USGS（Landsat/DEM 目录发现）
        gscloud_provider.py     地理空间数据云（需账号登录，仅指引）

本包不直接依赖 LLM / 前端，属于确定性程序代码。
"""
from backend.services.data_providers.base import (
    DataProvider,
    ProviderRegistry,
    get_registry,
    list_capabilities,
)
from backend.services.data_providers.errors import (
    DataProviderError,
    ProviderAuthError,
    DataNotFoundError,
    DownloadError,
    DownloadTimeoutError,
    DataValidationError,
    ProviderUnavailableError,
)
from backend.services.data_providers.models import (
    AuthLevel,
    DataType,
    VECTOR_KINDS,
    RASTER_KINDS,
    ALL_KINDS,
    DataRequest,
    DataHit,
    ProviderCapability,
)

__all__ = [
    "DataProvider",
    "ProviderRegistry",
    "get_registry",
    "list_capabilities",
    # errors
    "DataProviderError",
    "ProviderAuthError",
    "DataNotFoundError",
    "DownloadError",
    "DownloadTimeoutError",
    "DataValidationError",
    "ProviderUnavailableError",
    # models
    "AuthLevel",
    "DataType",
    "VECTOR_KINDS",
    "RASTER_KINDS",
    "ALL_KINDS",
    "DataRequest",
    "DataHit",
    "ProviderCapability",
]
