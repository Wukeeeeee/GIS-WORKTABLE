"""OpenStreetMap Provider。

走 OpenStreetMap 官方公开基础设施，不用网页爬虫：
  - 地名→范围：Nominatim 官方 API（geocode.py）
  - 要素获取：Overpass API 官方镜像（out geom 输出内联几何，无需二次解析节点）

能力：
  - 道路 roads / 建筑 buildings / POI pois / 水系 waterways / 土地利用 landuse / 交通 transport
  - 矢量，默认 EPSG:4326，格式 geojson / gpkg / shp
  - 公开免认证（但 OSM 中国区覆盖不完整，城市可用、乡村偏少）

失败全部抛明确异常；镜像逐一尝试并带受限重试。
"""

from __future__ import annotations

import os
from typing import Optional

from backend.services.data_providers import http, geocode
from backend.services.data_providers.base import DataProvider
from backend.services.data_providers.errors import (
    DataNotFoundError,
    DataProviderError,
    DownloadTimeoutError,
    ProviderUnavailableError,
)
from backend.services.data_providers.models import (
    AuthLevel,
    DataHit,
    DataRequest,
    DataType,
    ProviderCapability,
    VECTOR_KINDS,
)

# Overpass 官方/社区公开镜像（https://wiki.openstreetmap.org/wiki/Overpass_API）
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]

# 每类要素的 Overpass 选择器
_SELECTORS = {
    "roads": ['way["highway"]'],
    "buildings": ['way["building"]', 'relation["building"]'],
    "pois": [
        'node[~"^(amenity|shop|tourism|leisure|office|craft|healthcare|emergency|club|man_made)$"~"."]',
        'way[~"^(amenity|shop|tourism|leisure|office|craft|healthcare|emergency|club|man_made)$"~"."]',
        'relation[~"^(amenity|shop|tourism|leisure|office|craft|healthcare|emergency|club|man_made)$"~"."]',
    ],
    "waterways": [
        'way["waterway"]',
        'way["natural"="water"]',
        'relation["waterway"]',
        'relation["natural"="water"]',
    ],
    "landuse": ['way["landuse"]', 'relation["landuse"]'],
    "transport": [
        'way["railway"]',
        'relation["railway"]',
        'way["public_transport"]',
        'relation["route"="bus"]',
    ],
}

# 线状类要素（闭合时仍是 LineString，如环岛/闭合道路）
_LINE_KINDS = {"roads", "transport"}

DEFAULT_MAX_ITEMS = 50000
# 每类要素的默认抓取上限（保护 Overpass 公共镜像，也便于稳定复现）
KIND_CAPS = {
    "roads": 60000,
    "buildings": 60000,
    "pois": 80000,
    "waterways": 40000,
    "landuse": 40000,
    "transport": 40000,
}
QUERY_TIMEOUT = 45
OVERPASS_RETRIES = 1  # 每个镜像最多重试 1 次


class OpenStreetMapProvider(DataProvider):
    provider_id = "osm"
    name = "OpenStreetMap"

    def __init__(self):
        self._area_bbox_cache = {}

    # ----- 能力 -----
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="osm",
            name="OpenStreetMap",
            auth=AuthLevel.PUBLIC,
            auth_note="公开免认证（需遵守 Overpass/Nominatim 使用规范）。",
            homepage="https://www.openstreetmap.org",
            description="全球开放矢量要素：道路、建筑、POI、水系、土地利用等（Overpass 官方 API）。",
            vector_kinds=list(VECTOR_KINDS.keys()),
            vector_formats=("geojson", "gpkg", "shp"),
            default_vector_format="geojson",
            crs_default="EPSG:4326",
            note="OSM 中国区数据不完整：城市可用，乡村/偏远地区要素偏少。",
        )

    # ----- 内部：空间范围 -----
    def _bbox(self, request: DataRequest) -> tuple:
        if request.bbox:
            return tuple(request.bbox)
        area = (request.area or "").strip()
        if not area:
            raise DataProviderError(
                "缺少空间范围：请提供城市/区域名（如 长沙市）或 bbox（minLng,minLat,maxLng,maxLat）。",
                provider=self.provider_id,
            )
        if area in self._area_bbox_cache:
            return self._area_bbox_cache[area]
        bb = geocode.resolve_area_bbox(area)
        self._area_bbox_cache[area] = bb
        return bb

    def _selectors(self, kind: str) -> list:
        if kind not in _SELECTORS:
            raise DataProviderError(
                f"OSM 暂不支持要素类型「{kind}」，可选：{', '.join(VECTOR_KINDS)}。",
                provider=self.provider_id,
            )
        return _SELECTORS[kind]

    def _endpoints(self) -> list:
        env = os.environ.get("GIS_OVERPASS_ENDPOINT", "").strip()
        return ([env] if env else []) + list(OVERPASS_ENDPOINTS)

    def _overpass(self, query: str) -> dict:
        """依次尝试 Overpass 镜像；全部失败抛明确异常。"""
        last = None
        for url in self._endpoints():
            try:
                return http.post_overpass(query, url, retries=OVERPASS_RETRIES)
            except DownloadTimeoutError as e:
                last = e
            except ProviderUnavailableError as e:
                last = e
        if isinstance(last, DownloadTimeoutError):
            raise DownloadTimeoutError(
                "所有 Overpass 镜像均请求超时。",
                provider=self.provider_id,
                hint="网络到 OSM Overpass 不稳定，请稍后重试。",
            ) from last
        raise ProviderUnavailableError(
            "所有 Overpass 镜像均不可用，无法获取 OSM 数据。",
            provider=self.provider_id,
            hint="可设置环境变量 GIS_OVERPASS_ENDPOINT 指定可用镜像。",
        ) from last

    def _build_query(self, selectors: list, bbox: tuple, *, count: bool = False,
                     max_items: int = 0) -> str:
        bb = geocode.bbox_to_overpass(bbox)  # south,west,north,east
        inner = "".join(f"{sel}({bb});" for sel in selectors)
        head = f"[out:json][timeout:{QUERY_TIMEOUT}];"
        if count:
            return f"{head}( {inner} );out count;"
        limit = f" {int(max_items)}" if max_items else ""
        return f"{head}( {inner} );out geom{limit};"

    # ----- 搜索（发现） -----
    def search(self, request: DataRequest) -> list:
        if request.kind not in _SELECTORS:
            raise DataProviderError(
                f"OSM 不支持该要素类型，可选：{', '.join(VECTOR_KINDS)}。", provider=self.provider_id)
        bbox = self._bbox(request)
        q = self._build_query(self._selectors(request.kind), bbox, count=True)
        try:
            resp = self._overpass(q)
        except (ProviderUnavailableError, DownloadTimeoutError) as e:
            raise e

        # out count 返回 elements:[{"type":"count","tags":{...}}]
        counts = {}
        for el in (resp.get("elements") or []):
            if el.get("type") == "count":
                counts = el.get("tags") or {}
        ways = int(counts.get("ways") or 0)
        nodes = int(counts.get("nodes") or 0)
        total = ways + nodes
        cap = KIND_CAPS.get(request.kind, DEFAULT_MAX_ITEMS)

        label = VECTOR_KINDS.get(request.kind, request.kind)
        area = request.area or geocode.bbox_to_text(bbox)
        hits = [
            DataHit(
                title=f"{area} - {label}（OSM）",
                provider=self.name,
                provider_id=self.provider_id,
                kind=request.kind,
                kind_label=label,
                data_type=DataType.VECTOR,
                area=area,
                file_format=request.file_format or "geojson",
                crs="EPSG:4326",
                crs_known=True,
                feature_count=total,
                auth=AuthLevel.PUBLIC,
                downloadable=True,
                source_url="https://www.openstreetmap.org",
                note=f"OSM 要素检索：ways≈{ways}, nodes≈{nodes}；单次获取上限 {cap} 条，超出会被截断。",
            )
        ]
        return hits

    # ----- 下载 -----
    def download(self, request: DataRequest) -> dict:
        if request.kind not in _SELECTORS:
            raise DataProviderError(
                f"OSM 不支持该要素类型，可选：{', '.join(VECTOR_KINDS)}。", provider=self.provider_id)
        bbox = self._bbox(request)
        max_items = request.max_items or KIND_CAPS.get(request.kind, DEFAULT_MAX_ITEMS)
        q = self._build_query(self._selectors(request.kind), bbox, max_items=max_items)
        resp = self._overpass(q)

        features = []
        skipped = 0
        for el in (resp.get("elements") or []):
            feat = _element_to_feature(el, force_line=request.kind in _LINE_KINDS)
            if feat is None:
                skipped += 1
                continue
            features.append(feat)

        if not features:
            # Overpass 有 remark 字段时说明服务端截断/异常
            remark = resp.get("remark")
            raise DataNotFoundError(
                f"未获取到「{request.area or geocode.bbox_to_text(bbox)}」的"
                f"{VECTOR_KINDS.get(request.kind, request.kind)}数据。"
                + (f"\nOverpass 提示：{remark}" if remark else ""),
                provider=self.provider_id,
                hint="该区域可能无此类要素，请扩大范围或核对要素类型。",
            )

        # 若因上限截断给出提示（放在 extra，由上层回显）
        truncated = skipped > 0 or resp.get("remark") or len(features) >= max_items
        return {
            "geojson": {"type": "FeatureCollection", "features": features},
            "crs": "EPSG:4326",
            "crs_known": True,
            "geometry_types": _distinct_geom(features),
            "truncated": bool(truncated),
            "skipped": skipped,
            "bbox": _features_bbox(features),
        }


# ============================================================
# Overpass element → GeoJSON Feature
# ============================================================

def _pts_to_coords(pts: list) -> list:
    out = []
    for p in pts or []:
        if isinstance(p, dict) and p.get("lat") is not None and p.get("lon") is not None:
            out.append([round(float(p["lon"]), 7), round(float(p["lat"]), 7)])
    return out


def _element_to_feature(el: dict, force_line: bool = False) -> Optional[dict]:
    etype = el.get("type")
    tags = el.get("tags") or {}
    props = dict(tags)
    props["@osm_id"] = el.get("id")
    props["@osm_type"] = etype

    if etype == "node":
        if el.get("lat") is None or el.get("lon") is None:
            return None
        geom = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
    elif etype in ("way", "relation"):
        coords = _pts_to_coords(el.get("geometry"))
        if len(coords) < 2:
            return None
        closed = len(coords) >= 4 and coords[0] == coords[-1]
        if closed and not force_line:
            geom = {"type": "Polygon", "coordinates": [coords]}
        else:
            geom = {"type": "LineString", "coordinates": coords}
    else:
        return None

    return {"type": "Feature", "geometry": geom, "properties": props}


def _distinct_geom(features: list) -> list:
    s = set()
    for f in features:
        g = (f.get("geometry") or {}).get("type")
        if g:
            s.add(g)
    return sorted(s)


def _features_bbox(features: list) -> Optional[list]:
    xs, ys = [], []
    for f in features:
        g = f.get("geometry")
        if not g:
            continue
        for c in _iter_xy(g):
            xs.append(c[0]); ys.append(c[1])
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _iter_xy(g: dict):
    t = g.get("type")
    c = g.get("coordinates") or []
    if t == "Point":
        yield c
    elif t in ("MultiPoint", "LineString"):
        for p in c:
            yield p
    elif t == "Polygon":
        for ring in c:
            for p in ring:
                yield p
    elif t in ("MultiLineString", "MultiPolygon"):
        # 简化：只处理一层（OSM out geom 产出的是 Point/LineString/Polygon）
        pass
    elif t == "GeometryCollection":
        for sub in g.get("geometries", []):
            for p in _iter_xy(sub):
                yield p
