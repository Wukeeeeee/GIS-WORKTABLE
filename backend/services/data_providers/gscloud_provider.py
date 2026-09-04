"""地理空间数据云（www.gscloud.cn）Provider。

该平台（中国科学院计算机网络信息中心）需要注册账号 + 登录会话才能检索下载
DEM/Landsat/MODIS 等，且没有稳定公开的程序化检索 API；其网页检索也不适合
作为稳定方案爬取。因此本项目不自动获取，仅提供明确指引：
  - capability 描述（auth=account）；
  - search/download 返回引导结果，说明如何在 gscloud.cn 手动获取后上传，
    不静默失败、不做网页爬虫。
"""

from __future__ import annotations

from backend.services.data_providers.base import DataProvider, guide_hit
from backend.services.data_providers.errors import DataProviderError, ProviderAuthError
from backend.services.data_providers.models import (
    AuthLevel,
    DataRequest,
    DataType,
    ProviderCapability,
    RASTER_KINDS,
)

GSCLOUD_HOMEPAGE = "https://www.gscloud.cn"
_GUIDE = (
    "地理空间数据云（gscloud.cn）需注册账号登录后才能检索/下载 DEM、Landsat、MODIS 等数据，"
    "且没有稳定的公开程序化接口，本项目不自动抓取其网页。请按以下步骤手动获取：\n"
    "1. 在 https://www.gscloud.cn 注册并登录；\n"
    "2. 检索目标区域（DEM/Landsat/MODIS），选择并下载标准数据；\n"
    "3. 将下载的文件上传到 GIS WorkTable，会自动识别并加载为图层。"
)


class GSCloudProvider(DataProvider):
    provider_id = "gscloud"
    name = "地理空间数据云"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self.provider_id,
            name=self.name,
            auth=AuthLevel.ACCOUNT,
            auth_note="需要用户注册账号并登录（账号密码不进入项目）。",
            homepage=GSCLOUD_HOMEPAGE,
            description="中国科学院地理空间数据云：DEM、Landsat、MODIS 等公开地理/遥感数据。",
            raster_kinds=["dem", "imagery", "landcover"],
            raster_formats=("geotiff",),
            default_raster_format="geotiff",
            note="需账号登录、无稳定公开 API；本项目仅提供下载指引，不自动获取。",
        )

    def search(self, request: DataRequest) -> list:
        if request.kind not in RASTER_KINDS:
            raise DataProviderError(
                f"地理空间数据云只支持栅格类型：{', '.join(RASTER_KINDS)}。",
                provider=self.provider_id,
            )
        area = request.area or _bbox_text(request)
        return [guide_hit(
            provider_id=self.provider_id, provider_name=self.name,
            kind=request.kind, area=area, data_type=DataType.RASTER,
            file_format="geotiff", crs="待定（见平台产品说明）",
            auth=AuthLevel.ACCOUNT, source_url=GSCLOUD_HOMEPAGE,
            note=_GUIDE,
        )]

    def download(self, request: DataRequest) -> dict:
        raise ProviderAuthError(
            "地理空间数据云需要账号登录，本项目不自动获取其数据。",
            provider=self.provider_id,
            hint=_GUIDE,
        )


def _bbox_text(request: DataRequest) -> str:
    try:
        from backend.services.data_providers.geocode import bbox_to_text
        if request.bbox:
            return bbox_to_text(request.bbox)
    except Exception:
        pass
    return request.area or ""
