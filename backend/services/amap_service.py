"""
高德地图 POI 搜索服务（独立工具）
通过高德 Web API 搜索 POI，自动转换坐标到 WGS-84，返回标准 GeoJSON

原方案：AI 在 execute_python 里手动调高德 API → 经常忘记转坐标/输出格式不对
本方案：后端直接调高德 Web API → 固定返回标准 GeoJSON → 自动推送到地图

API 文档: skills/amap.md
"""

import math
from typing import Optional, List

from backend.services.geo_coords import gcj02_to_wgs84


# ============================================================
# POI → GeoJSON 转换
# ============================================================

def _poi_to_feature(poi: dict) -> Optional[dict]:
    """单个 POI 条目 → GeoJSON Feature（坐标已转 WGS-84）"""
    if not isinstance(poi, dict):
        return None
    location = poi.get("location", "")
    if not isinstance(location, str) or not location:
        return None
    try:
        parts = location.split(",")
        if len(parts) != 2:
            return None
        lng_str, lat_str = parts
        gcj_lng, gcj_lat = float(lng_str), float(lat_str)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not math.isfinite(gcj_lng)
        or not math.isfinite(gcj_lat)
        or not -180 <= gcj_lng <= 180
        or not -90 <= gcj_lat <= 90
    ):
        return None

    wgs_lng, wgs_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [round(wgs_lng, 6), round(wgs_lat, 6)]
        },
        "properties": {
            "name": poi.get("name", ""),
            "address": poi.get("address", ""),
            "type": poi.get("type", ""),
            "typecode": poi.get("typecode", ""),
            "tel": poi.get("tel", ""),
            "distance": poi.get("distance", ""),
            "pname": poi.get("pname", ""),
            "cityname": poi.get("cityname", ""),
            "adname": poi.get("adname", ""),
            "id": poi.get("id", ""),
        }
    }


def pois_to_geojson(pois: list, name: str = "POI搜索结果") -> dict:
    """POI 列表 → GeoJSON FeatureCollection"""
    features = []
    for poi in pois:
        f = _poi_to_feature(poi)
        if f:
            features.append(f)

    return {
        "type": "FeatureCollection",
        "name": name,
        "features": features
    }


# ============================================================
# 高德 Web API 调用
# ============================================================

AMAP_BASE = "https://restapi.amap.com/v3"


def search_text(keywords: str, city: str = "", offset: int = 25, page: int = 1, api_key: str = "") -> dict:
    """
    关键字搜索 POI
    https://restapi.amap.com/v3/place/text
    """
    if not api_key:
        return {"error": "高德 API Key 未配置"}

    params = {
        "key": api_key,
        "keywords": keywords,
        "offset": offset,
        "page": page,
        "extensions": "base",
    }
    if city:
        params["city"] = city

    try:
        import requests
        resp = requests.get(f"{AMAP_BASE}/place/text", params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, dict):
            return {"error": "高德 API 返回结构无效"}
        if data.get("status") != "1":
            return {"error": f"高德 API 返回错误: {data.get('info', '未知错误')}"}
        return data
    except Exception as e:
        # requests 异常可能包含完整查询 URL，其中带有 API Key。
        return {"error": f"高德 API 请求失败: {type(e).__name__}"}


def search_around(location: str, keywords: str = "", radius: int = 1000,
                  offset: int = 25, page: int = 1, api_key: str = "") -> dict:
    """
    周边搜索 POI
    https://restapi.amap.com/v3/place/around
    location: "经度,纬度"（GCJ-02 经纬度，即高德坐标系）
    """
    if not api_key:
        return {"error": "高德 API Key 未配置"}

    params = {
        "key": api_key,
        "location": location,
        "radius": radius,
        "offset": offset,
        "page": page,
        "extensions": "base",
        "sortrule": "distance",
    }
    if keywords:
        params["keywords"] = keywords

    try:
        import requests
        resp = requests.get(f"{AMAP_BASE}/place/around", params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, dict):
            return {"error": "高德 API 返回结构无效"}
        if data.get("status") != "1":
            return {"error": f"高德 API 返回错误: {data.get('info', '未知错误')}"}
        return data
    except Exception as e:
        # requests 异常可能包含完整查询 URL，其中带有 API Key。
        return {"error": f"高德 API 请求失败: {type(e).__name__}"}


def search_poi(keywords: str, city: str = "", location: str = "",
               radius: int = 1000, offset: int = 25, max_pages: int = 3,
               api_key: str = "") -> dict:
    """
    统一的 POI 搜索入口（自动选择搜索方式），返回 GeoJSON FeatureCollection

    参数:
        keywords: 搜索关键词，如"麦当劳"
        city: 城市名，如"广州"（可选，限定搜索范围）
        location: 中心点坐标 "lng,lat"（GCJ-02）（可选，周边搜索时使用）
        radius: 搜索半径，单位米，默认 1000
        offset: 每页条数，建议 25
        max_pages: 最大翻页数，最多 8 页（200 条）
        api_key: 高德 Web API Key

    返回:
        {
            "geojson": {...},         # GeoJSON FeatureCollection
            "count": 0,               # 总条数
            "source": "text|around",   # 搜索方式
            "error": "..."            # 错误信息（可选）
        }
    """
    if not api_key:
        return {"geojson": pois_to_geojson([], keywords), "count": 0, "error": "高德 API Key 未配置"}
    keywords = str(keywords or "").strip()
    if not keywords:
        return {"geojson": pois_to_geojson([], keywords), "count": 0, "error": "搜索关键词不能为空"}
    if isinstance(offset, bool) or not isinstance(offset, int) or offset <= 0:
        return {"geojson": pois_to_geojson([], keywords), "count": 0, "error": "offset 必须是正整数"}
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages <= 0:
        return {"geojson": pois_to_geojson([], keywords), "count": 0, "error": "max_pages 必须是正整数"}
    offset = min(offset, 25)
    page_limit = min(max_pages, 8)

    all_pois = []
    warnings = []
    source = "text"

    if location:
        # 周边搜索
        source = "around"
        for p in range(1, page_limit + 1):
            data = search_around(location, keywords, radius, offset, p, api_key)
            if "error" in data:
                if p == 1:
                    return {"geojson": pois_to_geojson([], keywords), "count": 0, "error": data["error"]}
                warnings.append(f"第 {p} 页周边搜索失败，结果仅包含前 {p - 1} 页。")
                break
            pois = data.get("pois", [])
            if not isinstance(pois, list) or any(not isinstance(poi, dict) for poi in pois):
                if p == 1:
                    return {"geojson": pois_to_geojson([], keywords), "count": 0,
                            "error": "高德 API 返回的 pois 列表结构无效"}
                warnings.append(f"第 {p} 页周边搜索返回无效数据，结果仅包含前 {p - 1} 页。")
                break
            if not pois:
                break
            all_pois.extend(pois)
            if len(pois) < offset:
                break
    else:
        # 关键字搜索
        for p in range(1, page_limit + 1):
            data = search_text(keywords, city, offset, p, api_key)
            if "error" in data:
                if p == 1:
                    return {"geojson": pois_to_geojson([], keywords), "count": 0, "error": data["error"]}
                warnings.append(f"第 {p} 页关键字搜索失败，结果仅包含前 {p - 1} 页。")
                break
            pois = data.get("pois", [])
            if not isinstance(pois, list) or any(not isinstance(poi, dict) for poi in pois):
                if p == 1:
                    return {"geojson": pois_to_geojson([], keywords), "count": 0,
                            "error": "高德 API 返回的 pois 列表结构无效"}
                warnings.append(f"第 {p} 页关键字搜索返回无效数据，结果仅包含前 {p - 1} 页。")
                break
            if not pois:
                break
            all_pois.extend(pois)
            if len(pois) < offset:
                break

    geojson = pois_to_geojson(all_pois, f"{keywords}_POI")
    return {
        "geojson": geojson,
        "count": len(geojson["features"]),
        "source": source,
        "warnings": warnings,
    }
