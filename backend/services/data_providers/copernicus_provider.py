"""Copernicus Data Space Provider。

真实产品（Sentinel 1/2/3、DEM 等）位于 Copernicus Data Space。STAC 目录搜索
公开可用；产品下载需要 ESA 账号的 OAuth2 token（不硬编码账号密码到项目）。

第一阶段策略：
  - 发现/搜索：使用公开 STAC 检索，返回元信息；
  - 下载：第一阶段不自动下载（需 OAuth + 预处理/波段组合链路）；

账号密码不进入代码/配置，仅通过环境变量传递 token。
"""

from __future__ import annotations

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

STAC_SEARCH_URL = "https://stac.dataspace.copernicus.eu/v1/search"
DEFAULT_TOKEN_ENV = "COPERNICUS_API_TOKEN"

# 常用 Collection（kind → 首选集合）。Sentinel-2 L2A 是公开默认影像。
_KIND_COLLECTIONS = {
    "imagery": ["sentinel-2-l2a"],
}


class CopernicusProvider(DataProvider):
    provider_id = "copernicus"
    name = "Copernicus Data Space"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self.provider_id,
            name=self.name,
            auth=AuthLevel.PUBLIC,
            auth_note=(
                "目录搜索公开；Copernicus Data Space 产品下载需 ESA 注册账号的 OAuth token"
                f"（设置环境变量 {DEFAULT_TOKEN_ENV}，不要硬编码账号密码）。"
            ),
            homepage="https://dataspace.copernicus.eu",
            description="欧洲航天局开放数据：Sentinel 遥感影像、DEM、土地覆盖等（STAC 目录）。",
            raster_kinds=["imagery"],
            raster_formats=("geotiff",),
            default_raster_format="geotiff",
            note="目录搜索公开；第一阶段仅发现/元信息，下载需 OAuth token，未启用自动影像获取。",
        )

    # ----- 搜索 -----
    def search(self, request: DataRequest) -> list:
        if request.kind not in _KIND_COLLECTIONS:
            raise DataProviderError(
                "Copernicus 当前只支持 Sentinel-2 影像目录检索，DEM 和土地覆盖检索尚未实现。",
                provider=self.provider_id,
            )
        bbox = self._bbox(request)
        return self._search_stac(request, bbox)

    def download(self, request: DataRequest) -> dict:
        if request.kind not in _KIND_COLLECTIONS:
            raise DataProviderError(
                "Copernicus 当前只支持 Sentinel-2 影像目录检索，DEM 和土地覆盖检索尚未实现。",
                provider=self.provider_id,
            )
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

    def _search_stac(self, request: DataRequest, bbox: tuple) -> list:
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

        resp = http.post_json(
            STAC_SEARCH_URL, json_body=body, retries=1,
        )
        if not isinstance(resp, dict) or not isinstance(resp.get("features"), list):
            raise DataProviderError(
                "Copernicus STAC 返回结构无效（缺少 features 列表）。",
                provider=self.provider_id,
            )
        features = resp["features"]
        if any(not isinstance(feature, dict) for feature in features):
            raise DataProviderError(
                "Copernicus STAC features 中包含无效条目。",
                provider=self.provider_id,
            )
        if not features:
            raise DataNotFoundError(
                f"Copernicus 在 {request.area or geocode.bbox_to_text(bbox)} 范围内"
                f"未发现 {RASTER_KINDS.get(request.kind, request.kind)}数据。",
                provider=self.provider_id,
                hint="可放宽时间范围（Sentinel 时序较稀疏）。",
            )
        hits = []
        for f in features:
            props = f.get("properties")
            props = props if isinstance(props, dict) else {}
            raw_datetime = props.get("datetime") or props.get("start_datetime") or ""
            dt = str(raw_datetime)[:10]
            gid = str(f.get("id") or "")
            links = f.get("links")
            source_url = next((link.get("href") for link in links or []
                               if isinstance(link, dict) and link.get("rel") == "self"
                               and isinstance(link.get("href"), str) and link["href"]), None)
            if not isinstance(source_url, str) or not source_url:
                source_url = STAC_SEARCH_URL
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
                source_url=source_url,
                note="Sentinel 产品需 OAuth token 下载，第一阶段仅列出元信息。",
            ))
        return hits


def _datetime_range(request: DataRequest) -> str:
    """拼 STAC 需要的 ISO8601 区间（含 T）。"""
    s = (request.time_start or "").strip()
    e = (request.time_end or "").strip()
    if not s and not e:
        return ""

    def norm(t: str, is_end: bool = False) -> str:
        if t == "..":
            return t
        t = t.replace(" ", "T")
        if "T" in t:
            return t
        return f"{t}T23:59:59Z" if is_end else f"{t}T00:00:00Z"

    s = norm(s) if s else ".."
    e = norm(e, is_end=True) if e else ".."
    return f"{s}/{e}"
