"""地名 → 空间范围（EPSG:4326 bbox）。

使用 OpenStreetMap Nominatim 官方公开 API（稳定、非爬虫）。
按 Nominatim 使用规范携带可识别 User-Agent 并低频调用。

结果不命中、解析失败时抛明确错误，不静默返回空范围。
"""

from __future__ import annotations

import math

from backend.services.data_providers.http import get_json, DEFAULT_TIMEOUT
from backend.services.data_providers.errors import DataNotFoundError, DataProviderError, DataValidationError

# 仅官方 Nominatim 实例。可被测试覆盖替换。
NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"


def _validated_bbox(bbox) -> tuple:
    try:
        if len(bbox) != 4:
            raise ValueError
        if any(isinstance(value, bool) for value in bbox):
            raise ValueError
        min_lng, min_lat, max_lng, max_lat = (float(value) for value in bbox)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("bbox 必须包含四个有效经纬度") from exc
    if (not all(map(math.isfinite, (min_lng, min_lat, max_lng, max_lat)))
            or not (-180 <= min_lng < max_lng <= 180)
            or not (-90 <= min_lat < max_lat <= 90)):
        raise ValueError("bbox 超出 WGS84 经纬度范围或坐标顺序无效")
    return min_lng, min_lat, max_lng, max_lat


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

    try:
        results = get_json(NOMINATIM_ENDPOINT, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
    except Exception as e:
        raise DataProviderError(
            f"地名解析服务暂时不可用：{area}",
            provider="geocode",
            hint=str(e),
        ) from e
    if not isinstance(results, list):
        raise DataValidationError(
            "地名解析服务返回了无效的数据结构。", provider="geocode")
    if not results:
        raise DataNotFoundError(
            f"无法定位区域「{area}」，请确认地名拼写，或直接提供经纬度 bbox。",
            provider="geocode",
            hint="示例：bbox='112.9,28.1,113.1,28.3'（minLng,minLat,maxLng,maxLat）。",
        )
    if not isinstance(results[0], dict):
        raise DataValidationError(
            "地名解析服务返回了无效的结果条目。", provider="geocode")

    hit = results[0]
    bb = hit.get("boundingbox")
    if isinstance(bb, (list, tuple)) and len(bb) >= 4:
        try:
            south, north, west, east = (float(value) for value in bb[:4])
            return _validated_bbox((min(west, east), min(south, north), max(west, east), max(south, north)))
        except (TypeError, ValueError, OverflowError):
            pass
    # 退而求其次：用中心点做一个小范围；0 经度/纬度也是合法中心点。
    lat, lon = hit.get("lat"), hit.get("lon")
    if lat is not None and lon is not None:
        try:
            lat, lon = float(lat), float(lon)
            if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                d = 0.05  # 约 5km 缓冲
                return _validated_bbox((max(-180, lon - d), max(-90, lat - d),
                                        min(180, lon + d), min(90, lat + d)))
        except (TypeError, ValueError, OverflowError):
            pass

    raise DataNotFoundError(
        f"无法定位区域「{area}」，请确认地名拼写，或直接提供经纬度 bbox。",
        provider="geocode",
        hint="示例：bbox='112.9,28.1,113.1,28.3'（minLng,minLat,maxLng,maxLat）。",
    )


def bbox_to_text(bbox: tuple) -> str:
    """把 bbox 转成可读文本（用于显示与 Overpass 参数）。"""
    min_lng, min_lat, max_lng, max_lat = (round(v, 5) for v in _validated_bbox(bbox))
    return f"{min_lng},{min_lat},{max_lng},{max_lat}"


def bbox_to_overpass(bbox: tuple) -> str:
    """Overpass 需要的 (south,west,north,east) 顺序。"""
    min_lng, min_lat, max_lng, max_lat = _validated_bbox(bbox)
    return f"{min_lat},{min_lng},{max_lat},{max_lng}"
