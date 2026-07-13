"""
GIS WorkTable — 图层检测服务
提供图层元数据检查（CRS、属性、空几何、无效几何等）。
不依赖前端 AI，后端独立计算。
"""

import json
import math
from typing import Optional


def inspect_geojson(geojson: dict) -> dict:
    """检查 GeoJSON 图层的完整元数据。

    Args:
        geojson: GeoJSON FeatureCollection 或 Feature

    Returns:
        dict: {
            feature_count, geometry_type, attr_fields, attr_types,
            bbox, crs, crs_known, null_geom_count, invalid_geom_count
        }
    """
    features = []
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
    elif geojson.get("type") == "Feature":
        features = [geojson]
    else:
        return {"error": "不是有效的 GeoJSON (FeatureCollection 或 Feature)"}

    feat_count = len(features)
    geom_types = set()
    attr_fields = {}
    null_geom = 0
    invalid_geom = 0
    all_coords = []

    for f in features:
        geom = f.get("geometry")
        props = f.get("properties", {})

        # 统计字段类型
        for k, v in props.items():
            if k not in attr_fields:
                attr_fields[k] = type(v).__name__ if v is not None else "null"
            else:
                existing = attr_fields[k]
                current = type(v).__name__ if v is not None else "null"
                if existing != current:
                    attr_fields[k] = "mixed"

        # 几何类型
        if geom is None:
            null_geom += 1
            continue
        gtype = geom.get("type")
        if gtype:
            geom_types.add(gtype)
        else:
            null_geom += 1
            continue

        # 提取坐标用于 bbox
        extracted = _extract_coords(geom)
        all_coords.extend(extracted)

        # 检查无效几何
        try:
            from shapely.geometry import shape
            import shapely
            s = shape(geom)
            if not s.is_valid:
                invalid_geom += 1
        except Exception:
            invalid_geom += 1

    # bbox
    bbox = _calc_bbox(all_coords) if all_coords else None

    # CRS 检测
    crs_info = _detect_crs(geojson)

    return {
        "feature_count": feat_count,
        "geometry_type": ", ".join(sorted(geom_types)) if geom_types else "无几何",
        "attr_fields": dict(sorted(attr_fields.items())) if attr_fields else {},
        "attr_count": len(attr_fields),
        "bbox": bbox,
        "crs": crs_info.get("crs", "未知"),
        "crs_known": crs_info.get("known", False),
        "null_geom_count": null_geom,
        "invalid_geom_count": invalid_geom,
        "coord_sample": all_coords[:3] if all_coords else [],
    }


def _extract_coords(geom: dict) -> list:
    """递归提取几何中的所有坐标对"""
    coords = []
    gtype = geom.get("type")
    raw = geom.get("coordinates", [])

    if gtype == "Point":
        if len(raw) >= 2:
            coords.append(tuple(raw[:2]))
    elif gtype in ("MultiPoint", "LineString"):
        for c in raw:
            if len(c) >= 2:
                coords.append(tuple(c[:2]))
    elif gtype in ("MultiLineString", "Polygon"):
        for ring in raw:
            for c in ring:
                if len(c) >= 2:
                    coords.append(tuple(c[:2]))
    elif gtype == "MultiPolygon":
        for poly in raw:
            for ring in poly:
                for c in ring:
                    if len(c) >= 2:
                        coords.append(tuple(c[:2]))
    elif gtype == "GeometryCollection":
        gs = geom.get("geometries", [])
        for g in gs:
            coords.extend(_extract_coords(g))
    return coords


def _calc_bbox(coords: list) -> Optional[list]:
    """计算坐标边界框 [minLng, minLat, maxLng, maxLat]"""
    if not coords:
        return None
    lngs = [c[0] for c in coords if len(c) >= 2]
    lats = [c[1] for c in coords if len(c) >= 2]
    if not lngs or not lats:
        return None
    return [min(lngs), min(lats), max(lngs), max(lats)]


def _detect_crs(geojson: dict) -> dict:
    """检测 GeoJSON 的 CRS 信息"""
    # 检查 GeoJSON 标准 crs 字段
    crs = geojson.get("crs")
    if crs:
        props = crs.get("properties", {})
        name = props.get("name", "")
        if "4326" in name or "WGS" in name.upper() or "84" in name:
            return {"crs": "EPSG:4326 (WGS-84)", "known": True}
        if "3857" in name or "900913" in name:
            return {"crs": "EPSG:3857 (Web Mercator)", "known": True}
        if name:
            return {"crs": name, "known": True}

    # 检查坐标范围推断
    features = []
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
    elif geojson.get("type") == "Feature":
        features = [geojson]

    all_lngs = []
    all_lats = []
    for f in features:
        geom = f.get("geometry")
        if geom:
            coords = _extract_coords(geom)
            for c in coords:
                if len(c) >= 2:
                    all_lngs.append(c[0])
                    all_lats.append(c[1])

    if all_lngs and all_lats:
        min_lat = min(all_lats)
        max_lat = max(all_lats)
        min_lng = min(all_lngs)
        max_lng = max(all_lngs)

        # 纬度在 -90~90，经度在 -180~180 → WGS-84
        if -90 <= min_lat <= 90 and -90 <= max_lat <= 90 and -180 <= min_lng <= 180 and -180 <= max_lng <= 180:
            return {"crs": "EPSG:4326 (WGS-84)", "known": True}

    return {"crs": "未知（无法从数据推断）", "known": False}
