"""Copernicus Data Space Provider。

真实产品（Sentinel 1/2/3、DEM 等）位于 Copernicus Data Space，需要 ESA
注册账号，通过 OAuth2 获取 token（不硬编码账号密码到项目）。目录搜索
（STAC）在带 token 时可用。

第一阶段策略：
  - 发现/搜索：配置了 COPERNICUS_API_TOKEN 才发起 STAC 检索，返回元信息；
  - 未配置 token：给出明确的认证指引（ProviderAuthError），不静默失败；
  - 下载：第一阶段不自动下载（需 OAuth + 预处理/波段组合链路），只返回元信息。

账号密码不进入代码/配置，仅通过环境变量传递 token。
"""

from __future__ import annotations

import os

from backend.services.data_providers import geocode, http
from backend.services.data_providers.base import DataProvider
from backend.services.data_providers.errors import (
    DataNotFoundError,
    DataProviderError,
    ProviderAuthError,
)
from backend.services.data_providers.models import (
    AuthLevel,
    DataHit,
    DataRequest,
    DataType,
    ProviderCapability,
    RASTER_KINDS,
)

STAC_SEARCH_URL = "https://catalogue.dataspace.copernicus.eu/stac/search"
DEFAULT_TOKEN_ENV = "COPERNICUS_API_TOKEN"

# 常用 Collection（kind → 首选集合）。Sentinel-2 L2A 是公开默认影像。
_KIND_COLLECTIONS = {
    "imagery": ["SENTINEL-2"],
    "landcover": [],
    "dem": [],
}


class CopernicusProvider(DataProvider):
    provider_id = "copernicus"
    name = "Copernicus Data Space"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self.provider_id,
            name=self.name,
            auth=AuthLevel.ACCOUNT,
            auth_note=(
                "Copernicus Data Space 下载需 ESA 注册账号的 OAuth token"
                f"（设置环境变量 {DEFAULT_TOKEN_ENV}，不要硬编码账号密码）。"
            ),
            homepage="https://dataspace.copernicus.eu",
            description="欧洲航天局开放数据：Sentinel 遥感影像、DEM、土地覆盖等（STAC 目录）。",
            raster_kinds=["imagery", "dem", "landcover"],
            raster_formats=("geotiff",),
            default_raster_format="geotiff",
            note="第一阶段仅发现/元信息；下载需 OAuth token，未启用自动影像获取。",
        )

    # ----- 搜索 -----
    def search(self, request: DataRequest) -> list:
        if request.kind not in RASTER_KINDS:
            raise DataProviderError(
                f"Copernicus 只支持栅格类型：{', '.join(RASTER_KINDS)}。",
                provider=self.provider_id,
            )
        token = os.environ.get(DEFAULT_TOKEN_ENV, "").strip()
        if not token:
            raise ProviderAuthError(
                "Copernicus Data Space 目录检索需要 ESA OAuth token。",
                provider=self.provider_id,
                hint=(
                    "在 https://dataspace.copernicus.eu 注册并创建 OAuth token，"
                    f"然后设置环境变量 {DEFAULT_TOKEN_ENV}=<token> 后重启。"
                    "账号密码不会写入项目。"
                ),
            )
        bbox = self._bbox(request)
        return self._search_stac(request, token, bbox)

    def download(self, request: DataRequest) -> dict:
        raise ProviderAuthError(
            "第一阶段未启用 Copernicus 遥感影像自动下载。",
            provider=self.provider_id,
            hint=(
                "配置 COPERNICUS_API_TOKEN 后可先用 discover 查看可用影像；"
                "正式下载涉及波段组合/云检测，属下一阶段。"
            ),
        )

    # ----- 内部 -----
    def _bbox(self, request: DataRequest):
        if request.bbox:
            return tuple(request.bbox)
        if not (request.area or "").strip():
            raise DataProviderError("缺少区域：请提供 area（地名）或 bbox。", provider=self.provider_id)
        return geocode.resolve_area_bbox(request.area)

    def _search_stac(self, request: DataRequest, token: str, bbox: tuple) -> list:
        min_lng, min_lat, max_lng, max_lat = bbox
        body = {
            "bbox": [min_lng, min_lat, max_lng, max_lat],
            "limit": min(request.max_items or 10, 50),
        }
        cols = _KIND_COLLECTIONS.get(request.kind) or []
        if cols:
            body["collections"] = cols
        ds = _datetime_range(request)
        if ds:
            body["datetime"] = ds

        headers = {"Authorization": f"Bearer {token}"}
        resp = http.post_json(
            STAC_SEARCH_URL, json_body=body, headers=headers, retries=1,
        )
        features = resp.get("features") or []
        if not features:
            raise DataNotFoundError(
                f"Copernicus 在 {request.area or geocode.bbox_to_text(bbox)} 范围内"
                f"未发现 {RASTER_KINDS.get(request.kind, request.kind)}数据。",
                provider=self.provider_id,
                hint="可放宽时间范围（Sentinel 时序较稀疏）。",
            )
        hits = []
        for f in features:
            props = f.get("properties") or {}
            dt = (props.get("datetime") or props.get("start_datetime") or "")[:10]
            gid = f.get("id", "")
            hits.append(DataHit(
                title=gid,
                provider=self.name,
                provider_id=self.provider_id,
                kind=request.kind,
                kind_label=RASTER_KINDS.get(request.kind, request.kind),
                data_type=DataType.RASTER,
                area=request.area or geocode.bbox_to_text(bbox),
                file_format="geotiff",
                crs="EPSG:4326（目录范围）",
                crs_known=True,
                auth=AuthLevel.ACCOUNT,
                downloadable=False,
                time_start=dt,
                time_end=dt,
                source_url=f.get("self") or STAC_SEARCH_URL,
                note="Sentinel 产品需 OAuth token 下载，第一阶段仅列出元信息。",
            ))
        return hits


def _datetime_range(request: DataRequest) -> str:
    """拼 STAC 需要的 ISO8601 区间（含 T）。"""
    s = (request.time_start or "").strip()
    e = (request.time_end or "").strip()
    if not s and not e:
        return ""

    def norm(t: str) -> str:
        if t == "..":
            return t
        t = t.replace(" ", "T")
        return t if "T" in t else f"{t}T00:00:00Z"

    s = norm(s) if s else ".."
    e = norm(e) if e else ".."
    return f"{s}/{e}"
