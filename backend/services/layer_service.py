"""
GIS WorkTable — 图层检测服务
提供图层元数据检查（CRS、属性、空几何、无效几何等）。
不依赖前端 AI，后端独立计算。
"""

import math
import re
from numbers import Real
from typing import Optional


def inspect_geojson(geojson: dict) -> dict:
    """检查 GeoJSON 图层的完整元数据。

    Args:
        geojson: GeoJSON FeatureCollection 或 Feature

    Returns:
        dict: {
            feature_count, geometry_type, attr_fields, attr_types,
            bbox, crs, crs_known, coordinate_units, null_geom_count, invalid_geom_count
        }
    """
    if not isinstance(geojson, dict):
        return {"error": "不是有效的 GeoJSON 对象"}

    features = []
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
        if not isinstance(features, list) or any(not isinstance(f, dict) for f in features):
            return {"error": "FeatureCollection.features 必须是 Feature 对象列表"}
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
        if not isinstance(props, dict):
            props = {}

        # 统计字段类型
        for k, v in props.items():
            current = type(v).__name__ if v is not None else "null"
            if k not in attr_fields:
                attr_fields[k] = current
            else:
                existing = attr_fields[k]
                if existing == "null" and current != "null":
                    attr_fields[k] = current
                elif current != "null" and existing != current and existing != "mixed":
                    attr_fields[k] = "mixed"

        # 几何类型
        if geom is None:
            null_geom += 1
            continue
        if not isinstance(geom, dict):
            invalid_geom += 1
            continue
        gtype = geom.get("type")
        if not gtype:
            null_geom += 1
            continue
        if not isinstance(gtype, str):
            invalid_geom += 1
            continue
        geom_types.add(gtype)

        # 提取坐标用于 bbox
        extracted = _extract_coords(geom)
        all_coords.extend(extracted)

        # 检查无效几何
        try:
            from shapely.geometry import shape
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
        "coordinate_units": crs_info.get("coordinate_units"),
        "null_geom_count": null_geom,
        "invalid_geom_count": invalid_geom,
        "coord_sample": all_coords[:3] if all_coords else [],
    }


def _extract_coords(geom: dict) -> list:
    """递归提取几何中的所有坐标对"""
    coords = []
    if not isinstance(geom, dict):
        return coords
    gtype = geom.get("type")

    def walk(raw):
        if not isinstance(raw, (list, tuple)):
            return
        if (len(raw) >= 2 and isinstance(raw[0], Real) and isinstance(raw[1], Real)
                and not isinstance(raw[0], bool) and not isinstance(raw[1], bool)):
            try:
                x, y = float(raw[0]), float(raw[1])
            except (OverflowError, TypeError, ValueError):
                return
            if math.isfinite(x) and math.isfinite(y):
                coords.append((x, y))
            return
        for item in raw:
            walk(item)

    if gtype == "GeometryCollection":
        for child in geom.get("geometries", []) if isinstance(geom.get("geometries", []), list) else []:
            coords.extend(_extract_coords(child))
    else:
        walk(geom.get("coordinates", []))
    return coords


def _calc_bbox(coords: list) -> Optional[list]:
    """计算坐标边界框 [minLng, minLat, maxLng, maxLat]"""
    if not coords:
        return None
    lngs = [c[0] for c in coords if len(c) >= 2 and math.isfinite(c[0]) and math.isfinite(c[1])]
    lats = [c[1] for c in coords if len(c) >= 2 and math.isfinite(c[0]) and math.isfinite(c[1])]
    if not lngs or not lats:
        return None
    return [min(lngs), min(lats), max(lngs), max(lats)]


def _detect_crs(geojson: dict) -> dict:
    """检测 GeoJSON 的 CRS 信息"""
    # 检查 GeoJSON 标准 crs 字段
    crs = geojson.get("crs")
    if crs:
        props = crs.get("properties", {}) if isinstance(crs, dict) else {}
        name = props.get("name", "") if isinstance(props, dict) else ""
        if not isinstance(name, str):
            name = ""
        normalized = re.sub(r"[^A-Z0-9]", "", name.upper())
        if normalized in {"CRS84", "WGS84", "WGS1984"}:
            return {"crs": "EPSG:4326 (WGS-84)", "known": True, "coordinate_units": "degree"}
        if name:
            try:
                from pyproj import CRS
                parsed_crs = CRS.from_user_input(name)
            except Exception:
                # Preserve the supplied identifier for diagnosis, but don't
                # show an invalid/unrecognized CRS with the UI's green badge.
                return {"crs": name, "known": False, "coordinate_units": None}
            authority = parsed_crs.to_authority()
            axes = parsed_crs.axis_info
            coordinate_units = axes[0].unit_name if axes else None
            if authority in (("EPSG", "4326"), ("OGC", "CRS84")):
                return {"crs": "EPSG:4326 (WGS-84)", "known": True, "coordinate_units": coordinate_units or "degree"}
            if parsed_crs.to_epsg() in (3857, 900913):
                return {"crs": "EPSG:3857 (Web Mercator)", "known": True, "coordinate_units": coordinate_units}
            return {"crs": name, "known": True, "coordinate_units": coordinate_units}

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
            return {"crs": "EPSG:4326 (WGS-84)", "known": True, "coordinate_units": "degree"}

    return {"crs": "未知（无法从数据推断）", "known": False, "coordinate_units": None}
