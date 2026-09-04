"""USGS Provider（美国地质调查局）。

  - Landsat Collection 2 Level-1 目录（landsatlook STAC）可匿名浏览/检索，
    是稳定公开的 STAC 接口（2026-09 已实测可用）。
  - DEM（SRTM / 3DEP）与完整影像下载需 EarthExplorer 登录（账号/授权）。

第一阶段策略：
  - imagery：用公开 STAC 做发现，返回场景元信息（场景号/时间/范围）。
  - dem：返回明确指引（需 EarthExplorer 账号），不做网页爬取。
  - download：未启用自动下载，明确抛认证/指引错误。
账号密码不进入项目，下载阶段再读环境变量（USGS_*）。
"""

from __future__ import annotations

import datetime as _dt

from backend.services.data_providers import geocode, http
from backend.services.data_providers.base import DataProvider, guide_hit
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

LANDSAT_STAC_SEARCH = "https://landsatlook.usgs.gov/stac-server/search"
_LANDSAT_COLLECTION = "landsat-c2l1"


class USGSProvider(DataProvider):
    provider_id = "usgs"
    name = "USGS"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id=self.provider_id,
            name=self.name,
            auth=AuthLevel.ACCOUNT,
            auth_note=(
                "Landsat 目录可匿名检索；DEM/完整影像下载需 EarthExplorer"
                " 注册登录（USGS M2M 或网页）。账号密码不会写入项目。"
            ),
            homepage="https://www.usgs.gov",
            description="USGS 开放数据：Landsat 遥感影像（STAC 目录）、SRTM DEM 等。",
            raster_kinds=["imagery", "dem"],
            raster_formats=("geotiff",),
            default_raster_format="geotiff",
            note="第一阶段：imagery 目录发现可用；DEM/影像下载需 EarthExplorer 账号。",
        )

    def search(self, request: DataRequest) -> list:
        if request.kind not in RASTER_KINDS:
            raise DataProviderError(
                f"USGS 只支持栅格类型：imagery / dem。", provider=self.provider_id)
        bbox = self._bbox(request)
        if request.kind == "dem":
            return [guide_hit(
                provider_id=self.provider_id, provider_name=self.name,
                kind="dem", area=request.area or geocode.bbox_to_text(bbox),
                data_type=DataType.RASTER, file_format="geotiff",
                crs="EPSG:4326（SRTM）",
                auth=AuthLevel.ACCOUNT,
                source_url="https://earthexplorer.usgs.gov",
                note=("USGS DEM（SRTM/3DEP）需在 EarthExplorer 登录后选择范围下载，"
                      "本项目不自动抓取。请在网页下载后上传到 GIS WorkTable。"),
            )]
        # imagery：匿名 landsatlook STAC
        return self._search_landsat(request, bbox)

    def download(self, request: DataRequest) -> dict:
        raise ProviderAuthError(
            "第一阶段未启用 USGS 遥感影像自动下载。",
            provider=self.provider_id,
            hint="可用 discover 查看 Landsat 场景元信息；影像获取需 EarthExplorer 账号，属下一阶段。",
        )

    # ----- 内部 -----
    def _bbox(self, request: DataRequest):
        if request.bbox:
            return tuple(request.bbox)
        if not (request.area or "").strip():
            raise DataProviderError("缺少区域：请提供 area（地名）或 bbox。", provider=self.provider_id)
        return geocode.resolve_area_bbox(request.area)

    def _search_landsat(self, request: DataRequest, bbox: tuple) -> list:
        min_lng, min_lat, max_lng, max_lat = bbox
        dstr = _dt_range(request)
        body = {
            "collections": [_LANDSAT_COLLECTION],
            "bbox": [min_lng, min_lat, max_lng, max_lat],
            "datetime": dstr,
            "limit": min(request.max_items or 10, 50),
        }
        resp = http.post_json(LANDSAT_STAC_SEARCH, json_body=body, retries=1)
        features = resp.get("features") or []
        if not features:
            raise DataNotFoundError(
                f"Landsat 在 {request.area or geocode.bbox_to_text(bbox)} 范围内"
                f"{_window_text(dstr)}未发现 Level-1 场景。",
                provider=self.provider_id,
                hint="Landsat 重访周期约 8-16 天，请放宽时间范围。",
            )
        hits = []
        for f in features[: (request.max_items or 10)]:
            props = f.get("properties") or {}
            dt = (props.get("datetime") or "")[:10]
            hits.append(DataHit(
                title=f.get("id", "Landsat scene"),
                provider=self.name,
                provider_id=self.provider_id,
                kind=request.kind,
                kind_label=RASTER_KINDS.get(request.kind, request.kind),
                data_type=DataType.RASTER,
                area=request.area or geocode.bbox_to_text(bbox),
                file_format="geotiff",
                crs="EPSG:4326（目录范围）",
                crs_known=True,
                time_start=dt,
                time_end=dt,
                auth=AuthLevel.ACCOUNT,
                downloadable=False,
                source_url=LANDSAT_STAC_SEARCH,
                note="Landsat C2L1 场景元信息；影像下载需 EarthExplorer 登录。",
            ))
        return hits


def _dt_range(request: DataRequest) -> str:
    """返回 ISO8601 区间。未给时间则默认最近 180 天（约束检索量）。"""
    today = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    start = today - _dt.timedelta(days=180)
    s = (request.time_start or "").strip()
    e = (request.time_end or "").strip()

    def iso(t: str, default: _dt.datetime):
        if not t:
            return default.isoformat()
        t = t.replace(" ", "T")
        return t if "T" in t else f"{t}T00:00:00Z"

    return f"{iso(s, start)}/{iso(e, today)}"


def _window_text(dstr: str) -> str:
    if dstr.startswith(".."):
        return ""
    try:
        s, e = dstr.split("/")
        return f"（时间 {s[:10]} ~ {e[:10]}）"
    except ValueError:
        return ""
