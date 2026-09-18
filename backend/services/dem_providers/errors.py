"""DEM Provider 错误体系。

复用 backend.services.data_providers.errors 体系的 ProviderAuthError /
DownloadError / DownloadTimeoutError / DataValidationError / ProviderUnavailableError，
仅在 DEM 特有场景下扩展：
  - DEMAreaOutOfRangeError：请求范围超出 Provider 覆盖（如 Web Mercator 极区之外）
  - DEMResolutionUnsupportedError：要求的分辨率 Provider 不支持
  - DEMTooManyTilesError：请求范围过大（防止单次下载成千 tile）
  - DEMTileDecodeError：tile PNG 解码失败（编码格式与约定不符）

所有错误都给出可读中文 message + hint，禁止静默失败。
"""
from __future__ import annotations

from backend.services.data_providers.errors import (
    DataProviderError,
    DataValidationError,
    DownloadError,
    DownloadTimeoutError,
    ProviderAuthError,
    ProviderUnavailableError,
)


class DEMError(DataProviderError):
    """DEM 流程相关错误的基类（保留独立命名空间，便于上层针对性捕获）。"""


class DEMAreaOutOfRangeError(DEMError):
    """请求的地理范围不被 Provider 覆盖。

    例如：Web Mercator tile 体系在 lat = ±85.0511 之外无法表示。
    """


class DEMResolutionUnsupportedError(DEMError):
    """请求的目标分辨率 Provider 不支持（如越界 / Provider 没有该级别）。"""


class DEMTooManyTilesError(DEMError):
    """请求范围过大，单次将下载超过安全上限的 tile 数（防止误用卡死服务/磁盘）。

    建议缩小空间范围或提高目标分辨率（更粗粒度 = 更少 tile）。
    """


class DEMTileDecodeError(DataValidationError):
    """单 tile 解码失败：通常意味着 Provider 改变了返回格式，或文件损坏。

    hint 默认指向「Provider 升级 / 缓存损坏，请清理重试」。
    """


__all__ = [
    "DEMError",
    "DEMAreaOutOfRangeError",
    "DEMResolutionUnsupportedError",
    "DEMTooManyTilesError",
    "DEMTileDecodeError",
    # 复用 data_providers
    "DataProviderError",
    "DataValidationError",
    "DownloadError",
    "DownloadTimeoutError",
    "ProviderAuthError",
    "ProviderUnavailableError",
]