"""
高德地图高程查询服务（DEM）
通过高德 Web API 获取海拔高程数据，自动 GCJ-02 → WGS-84 坐标转换
返回标准 GeoJSON 供前端加载

API 文档: https://lbs.amap.com/api/webservice/guide/api/elevation
"""

import json
import math
import requests
from typing import Optional
from backend.services.geo_coords import gcj02_to_wgs84, wgs84_to_gcj02

AMAP_BASE = "https://restapi.amap.com/v3"
_MAX_POINTS_PER_CALL = 20


def _parse_bbox(bbox_str: str) -> tuple:
    """解析 bbox 字符串 'minLng,minLat,maxLng,maxLat' → (minLng, minLat, maxLng, maxLat)"""
    parts = [float(x) for x in bbox_str.replace("，", ",").split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox 格式错误，需要 4 个数值: {bbox_str}")
    return tuple(parts)


def _build_grid(min_lng: float, min_lat: float, max_lng: float, max_lat: float, step: float) -> list:
    """在 bbox 内按步长生成网格点坐标列表 [(lng, lat), ...]"""
    points = []
    x = min_lng
    while x <= max_lng:
        y = min_lat
        while y <= max_lat:
            points.append((round(x, 6), round(y, 6)))
            y += step
        x += step
    return points


def query_elevation(points: list, api_key: str) -> Optional[list]:
    """
    调用高德高程 API 查询一组点的高程
    points: [(lng, lat), ...] 最多 20 个点
    返回: [{"lng": ..., "lat": ..., "elevation": ...}, ...] 或 None
    """
    if not api_key:
        return None
    if not points:
        return []

    locations = "|".join(f"{lng},{lat}" for lng, lat in points)
    try:
        resp = requests.get(
            f"{AMAP_BASE}/elevation",
            params={"key": api_key, "locations": locations},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") != "1":
            return None

        results = []
        for item in data.get("elevation", []):
            loc = item.get("location", "")
            elev = item.get("elevation")
            if loc and elev is not None:
                try:
                    lng_str, lat_str = loc.split(",")
                    gcj_lng, gcj_lat = float(lng_str), float(lat_str)
                    wgs_lng, wgs_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)
                    results.append({
                        "lng": round(wgs_lng, 6),
                        "lat": round(wgs_lat, 6),
                        "elevation": round(float(elev), 1),
                    })
                except (ValueError, IndexError):
                    continue
        return results
    except Exception:
        return None


def query_single_point(lng: float, lat: float, api_key: str) -> Optional[dict]:
    """查询单个点的高程（输入 WGS-84 坐标，自动转 GCJ-02 调用高德 API）"""
    # 先转 GCJ-02 再查高德
    gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
    results = query_elevation([(gcj_lng, gcj_lat)], api_key)
    if results:
        return results[0]
    return None


def query_bbox(bbox: str, step: float, api_key: str) -> dict:
    """
    查询 bbox 范围内所有网格点的高程，返回 GeoJSON FeatureCollection

    bbox: "minLng,minLat,maxLng,maxLat" (WGS-84 坐标系，会自动转为 GCJ-02 调用高德 API)
    step: 步长（度），如 0.001 ≈ 100m
    """
    try:
        min_lng, min_lat, max_lng, max_lat = _parse_bbox(bbox)
    except ValueError as e:
        return {"error": str(e)}

    if not api_key:
        return {"error": "高德 API Key 未配置"}

    if step <= 0:
        step = 0.001

    # 限制网格点数防止超时
    total_points_estimate = ((max_lng - min_lng) / step + 1) * ((max_lat - min_lat) / step + 1)
    if total_points_estimate > 4000:
        return {"error": f"网格点数过多（约 {int(total_points_estimate)} 个），请增大 step 或缩小范围"}

    # 生成 WGS-84 网格点，然后转 GCJ-02（高德 API 需要）
    grid_points = _build_grid(min_lng, min_lat, max_lng, max_lat, step)
    grid_points_gcj = [wgs84_to_gcj02(lng, lat) for lng, lat in grid_points]

    # 分批查询（每批最多 _MAX_POINTS_PER_CALL 个点）
    all_results = []
    for i in range(0, len(grid_points_gcj), _MAX_POINTS_PER_CALL):
        batch = grid_points_gcj[i:i + _MAX_POINTS_PER_CALL]
        batch_results = query_elevation(batch, api_key)
        if batch_results is None:
            return {"error": f"高德高程 API 查询失败（第 {i//_MAX_POINTS_PER_CALL + 1} 批）"}
        all_results.extend(batch_results)

    if not all_results:
        return {"geojson": _empty_geojson(), "count": 0, "stats": {}}

    # 构建 GeoJSON
    features = []
    elevations = []
    for r in all_results:
        elevations.append(r["elevation"])
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r["lng"], r["lat"]],
            },
            "properties": {
                "elevation": r["elevation"],
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "name": f"DEM_{min_lng:.2f}_{min_lat:.2f}",
        "features": features,
    }

    elev_min = min(elevations)
    elev_max = max(elevations)
    elev_avg = sum(elevations) / len(elevations)

    return {
        "geojson": geojson,
        "count": len(features),
        "stats": {
            "min": elev_min,
            "max": elev_max,
            "avg": round(elev_avg, 1),
            "count": len(elevations),
        },
    }


def _empty_geojson() -> dict:
    return {"type": "FeatureCollection", "name": "DEM_空", "features": []}
