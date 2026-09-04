"""地名 → 空间范围（EPSG:4326 bbox）。

使用 OpenStreetMap Nominatim 官方公开 API（稳定、非爬虫）。
按 Nominatim 使用规范携带可识别 User-Agent 并低频调用。

结果不命中、解析失败时抛明确错误，不静默返回空范围。
"""

from __future__ import annotations

from typing import Optional

from backend.services.data_providers.http import get_json, DEFAULT_TIMEOUT
from backend.services.data_providers.errors import DataNotFoundError, DataProviderError

# 仅官方 Nominatim 实例。可被测试覆盖替换。
NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_ENDPOINTS = [NOMINATIM_ENDPOINT]


def resolve_area_bbox(area: str) -> tuple:
    """把地名解析为 (min_lng, min_lat, max_lng, max_lat)（EPSG:4326）。

    失败抛 DataNotFoundError / DataProviderError。
    """
    if not area or not str(area).strip():
        raise DataProviderError("缺少空间范围：请提供城市/区域名，或直接给出经纬度范围 bbox。")

    params = {
        "q": str(area).strip(),
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 0,
        "polygon_geojson": 0,
    }
    headers = {"Accept": "application/json"}

    # 依次尝试镜像（低频，单次即可）
    for url in _NOMINATIM_ENDPOINTS:
        try:
            results = get_json(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        except Exception as e:
            raise DataProviderError(
                f"地名解析服务暂时不可用：{area}",
                provider="geocode",
                hint=str(e),
            ) from e
        if not isinstance(results, list) or not results:
            continue
        hit = results[0]
        bb = hit.get("boundingbox") or []
        if len(bb) >= 4:
            try:
                south, north, west, east = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
                return (min(west, east), min(south, north), max(west, east), max(south, north))
            except (ValueError, TypeError):
                pass
        # 退而求其次：用中心点做一个小范围
        lat, lon = hit.get("lat"), hit.get("lon")
        if lat and lon:
            try:
                lat, lon = float(lat), float(lon)
                d = 0.05  # 约 5km 缓冲
                return (lon - d, lat - d, lon + d, lat + d)
            except (ValueError, TypeError):
                pass

    raise DataNotFoundError(
        f"无法定位区域「{area}」，请确认地名拼写，或直接提供经纬度 bbox。",
        provider="geocode",
        hint="示例：bbox='112.9,28.1,113.1,28.3'（minLng,minLat,maxLng,maxLat）。",
    )


def bbox_to_text(bbox: tuple) -> str:
    """把 bbox 转成可读文本（用于显示与 Overpass 参数）。"""
    min_lng, min_lat, max_lng, max_lat = (round(float(v), 5) for v in bbox)
    return f"{min_lng},{min_lat},{max_lng},{max_lat}"


def bbox_to_overpass(bbox: tuple) -> str:
    """Overpass 需要的 (south,west,north,east) 顺序。"""
    min_lng, min_lat, max_lng, max_lat = bbox
    return f"{min_lat},{min_lng},{max_lat},{max_lng}"
