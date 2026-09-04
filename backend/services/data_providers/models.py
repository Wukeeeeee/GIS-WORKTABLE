"""统一数据模型与类型常量（不依赖任何第三方 GIS 库）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 认证分级：公开免认证 / 公开但需 API Key / 需要账号授权
# ============================================================
class AuthLevel:
    PUBLIC = "public"        # 公开、免认证即可访问/获取
    API_KEY = "api_key"      # 公开数据，但访问/下载需要 API Key
    ACCOUNT = "account"      # 需要用户账号/授权（登录），不硬编码账号密码


# ============================================================
# 数据类型
# ============================================================
class DataType:
    VECTOR = "vector"
    RASTER = "raster"


# 规范化要素类型（第一阶段）
#   矢量要素类型（与 OSM 映射）
VECTOR_KINDS = {
    "roads": "道路",
    "buildings": "建筑",
    "pois": "POI 兴趣点",
    "waterways": "水系",
    "landuse": "土地利用",
    "transport": "交通/铁路设施",
}
#   栅格要素类型（遥感/地形）
RASTER_KINDS = {
    "imagery": "遥感影像",
    "dem": "数字高程 DEM",
    "landcover": "土地利用/覆盖栅格",
}
ALL_KINDS = {**VECTOR_KINDS, **RASTER_KINDS}

# 矢量/栅格统一提示（给 LLM 的参数归一化）
_KIND_SYNONYMS = {
    "road": "roads", "roads": "roads", "道路": "roads", "路网": "roads", "公路": "roads",
    "道路数据": "roads", "路线": "roads", "街道": "roads", "highway": "roads",
    "building": "buildings", "buildings": "buildings", "建筑": "buildings",
    "建筑物": "buildings", "房屋": "buildings", "footprint": "buildings",
    "poi": "pois", "pois": "pois", "poi 兴趣点": "pois", "兴趣点": "pois",
    "餐饮": "pois", "饭店": "pois", "酒店": "pois", "商场": "pois", "银行": "pois",
    "加油站": "pois", "医院": "pois", "景点": "pois",
    "water": "waterways", "waterways": "waterways", "水系": "waterways",
    "河流": "waterways", "河": "waterways", "湖泊": "waterways", "水库": "waterways",
    "landuse": "landuse", "土地利用": "landuse", "land cover": "landuse",
    "用地": "landuse", "地类": "landuse",
    "transport": "transport", "铁路": "transport", "公交": "transport",
    "imagery": "imagery", "影像": "imagery", "遥感影像": "imagery",
    "卫星影像": "imagery", "哨兵": "imagery", "sentinel": "imagery",
    "landsat": "imagery", "dem": "dem", "高程": "dem", "地形": "dem",
    "数字高程": "dem", "dems": "dem",
    "landcover": "landcover", "栅格": "landcover", "土地覆盖": "landcover",
}

# 允许的下载格式（白名单，未知格式不允许落盘/加载）
VECTOR_FORMATS = ("geojson", "gpkg", "shp")
RASTER_FORMATS = ("geotiff",)
ALLOWED_FORMATS = VECTOR_FORMATS + RASTER_FORMATS
ALLOWED_FORMAT_EXTS = {
    "geojson": ".geojson",
    "gpkg": ".gpkg",
    "shp": ".shp",
    "geotiff": ".tif",
}


def normalize_kind(kind: str = "", query: str = "") -> str:
    """把用户表述（kind 参数 + 自由文本 query）归一化为规范化 kind。

    归一化失败返回 ""（表示"无法确定数据类型"，由上层引导用户补全）。
    """
    text = f"{kind or ''} {query or ''}"
    # 优先命中更长的同义词
    cands = sorted(_KIND_SYNONYMS.keys(), key=len, reverse=True)
    for c in cands:
        if c and c.lower() in text.lower():
            return _KIND_SYNONYMS[c]
    return ""


def normalize_format(fmt: str = "") -> str:
    """文件格式归一化（geojson/json/GeoJSON → geojson 等），未知返回 ''。"""
    f = (fmt or "").strip().lower().replace(".", "")
    return {
        "geojson": "geojson", "json": "geojson",
        "gpkg": "gpkg", "geopackage": "gpkg",
        "shp": "shp", "shapefile": "shp", "zip": "shp",
        "tif": "geotiff", "tiff": "geotiff", "geotiff": "geotiff", "栅格": "geotiff",
    }.get(f, "")


def parse_bbox(bbox: str = "") -> Optional[tuple]:
    """解析 'minLng,minLat,maxLng,maxLat' 字符串 → (minx, miny, maxx, maxy)。

    范围非法返回 None。
    """
    if not bbox:
        return None
    parts = [p.strip() for p in str(bbox).split(",")]
    if len(parts) != 4:
        return None
    try:
        min_lng, min_lat, max_lng, max_lat = (float(p) for p in parts)
    except (ValueError, TypeError):
        return None
    if not (-180 <= min_lng <= 180 and -180 <= max_lng <= 180):
        return None
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        return None
    if min_lng > max_lng or min_lat > max_lat:
        return None
    return (min_lng, min_lat, max_lng, max_lat)


def sanitize_name(name: str) -> str:
    """清理用于文件名/图层名的名称。"""
    name = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(name).strip())
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:80] or "data"


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ProviderCapability:
    """某个数据源的能力描述（用于能力检测与前端展示）。"""
    provider_id: str
    name: str                          # 显示名，如 OpenStreetMap
    auth: str                          # AuthLevel.PUBLIC / API_KEY / ACCOUNT
    auth_note: str = ""                # 认证说明
    homepage: str = ""
    description: str = ""
    vector_kinds: list = field(default_factory=list)   # 规范化 kind
    raster_kinds: list = field(default_factory=list)
    vector_formats: tuple = VECTOR_FORMATS
    raster_formats: tuple = RASTER_FORMATS
    default_vector_format: str = "geojson"
    default_raster_format: str = "geotiff"
    crs_default: str = "EPSG:4326"     # 该数据源矢量默认 CRS
    note: str = ""                     # 覆盖/完整性等提示

    def to_dict(self) -> dict:
        return {
            "provider": self.provider_id,
            "name": self.name,
            "auth": self.auth,
            "auth_note": self.auth_note,
            "homepage": self.homepage,
            "description": self.description,
            "vector_kinds": self.vector_kinds,
            "raster_kinds": self.raster_kinds,
            "vector_formats": list(self.vector_formats),
            "raster_formats": list(self.raster_formats),
            "default_vector_format": self.default_vector_format,
            "default_raster_format": self.default_raster_format,
            "crs_default": self.crs_default,
            "note": self.note,
        }


@dataclass
class DataRequest:
    """一次结构化数据需求（由 AI/上层把自然语言解析后的结果）。"""
    kind: str = ""                      # 规范化 kind：roads/buildings/pois/... imagery/dem/...
    area: str = ""                      # 区域名（如 长沙市）
    bbox: Optional[tuple] = None        # (minLng, minLat, maxLng, maxLat) EPSG:4326
    provider_id: str = ""               # 指定 Provider（空 = auto）
    query: str = ""                     # 原始自然语言（保留参考）
    time_start: str = ""                # 时间范围（遥感数据常用，如 '2024-01-01'）
    time_end: str = ""
    file_format: str = "geojson"        # geojson/gpkg/shp/geotiff
    max_items: int = 0                  # 0 = Provider 默认上限
    out_dir: Optional[str] = None       # 落盘目录（默认缓存目录，测试可用 tmp_path）


@dataclass
class DataHit:
    """搜索结果：某条可获取的数据（元信息，不含要素本身）。"""
    title: str
    provider: str
    provider_id: str
    kind: str
    data_type: str            # vector / raster
    kind_label: str = ""
    area: str = ""
    file_format: str = ""     # 建议获取格式
    crs: str = ""
    crs_known: bool = True
    size_bytes: Optional[int] = None
    feature_count: Optional[int] = None
    auth: str = AuthLevel.PUBLIC
    auth_note: str = ""
    downloadable: bool = True
    time_start: str = ""
    time_end: str = ""
    source_url: str = ""
    note: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "provider": self.provider,
            "provider_id": self.provider_id,
            "kind": self.kind,
            "kind_label": self.kind_label or ALL_KINDS.get(self.kind, self.kind),
            "data_type": self.data_type,
            "area": self.area,
            "file_format": self.file_format,
            "crs": self.crs,
            "crs_known": self.crs_known,
            "size_bytes": self.size_bytes,
            "feature_count": self.feature_count,
            "auth": self.auth,
            "auth_note": self.auth_note,
            "downloadable": self.downloadable,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "source_url": self.source_url,
            "note": self.note,
        }


@dataclass
class DownloadedAsset:
    """下载完成后的产物（已落盘 + 已校验 + metadata 已保存）。"""
    ok: bool = True
    provider: str = ""
    provider_name: str = ""
    kind: str = ""
    kind_label: str = ""
    data_type: str = ""
    layer_name: str = ""
    title: str = ""
    area: str = ""
    file_path: str = ""
    url: str = ""                       # 可通过前端 /output/... 下载的相对 URL
    file_format: str = ""
    crs: str = ""
    crs_known: bool = True
    size_bytes: int = 0
    feature_count: Optional[int] = None
    geometry_types: list = field(default_factory=list)
    bbox: Optional[list] = None
    geojson: Optional[dict] = None      # 矢量：直接可加载地图的 FeatureCollection
    metadata: dict = field(default_factory=dict)
    note: str = ""
    error: str = ""
    error_type: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "provider_name": self.provider_name,
            "kind": self.kind,
            "kind_label": self.kind_label,
            "data_type": self.data_type,
            "layer_name": self.layer_name,
            "title": self.title,
            "area": self.area,
            "file_path": self.file_path,
            "url": self.url,
            "file_format": self.file_format,
            "crs": self.crs,
            "crs_known": self.crs_known,
            "size_bytes": self.size_bytes,
            "feature_count": self.feature_count,
            "geometry_types": self.geometry_types,
            "bbox": self.bbox,
            "geojson": self.geojson,
            "metadata": self.metadata,
            "note": self.note,
            "error": self.error,
            "error_type": self.error_type,
        }
