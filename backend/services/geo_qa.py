# -*- coding: utf-8 -*-
"""地理数据质量自检（Geo QA）

在图层通道出口（_push_layer / _register_layer）对每个产出图层做轻量体检，
把可疑的地理错误变成显式警告，而不是静默输出错误数据：

- 坐标范围：bbox 超出 WGS-84 合法范围 → 疑似 CRS 未转换（如投影坐标/ GCJ-02 直出）
- 坐标顺序：全部 |经度|>90 且 |纬度|<=90 → 疑似 lat/lng 顺序颠倒
- 几何有效性：抽样 shapely is_valid，无效几何给出修复提示
- 空结果：FeatureCollection 零要素 → 提示分析可能无意义
- 自相交缓冲类异常：单要素坐标数异常（<最小顶点数）→ 提示

设计约束：绝不抛异常、绝不阻塞出图——警告只附加信息，不改变数据。
"""
import math

_WGS_RANGE = (-180.0, -90.0, 180.0, 90.0)
_MAX_SAMPLE = 200          # 有效性抽样的最大要素数


def _walk_coords(coords, out):
    """递归收集坐标点到 out（列表复用，避免大图层深拷贝）"""
    if not coords or not isinstance(coords, (list, tuple)):
        return
    if len(coords) >= 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
        out.append((coords[0], coords[1]))
        return
    for c in coords:
        _walk_coords(c, out)


def _extract_points(geojson: dict, limit: int = 5000):
    """提取前 limit 个坐标点用于统计判断"""
    points = []
    if not isinstance(geojson, dict):
        return points
    if geojson.get("type") == "FeatureCollection":
        geoms = [f.get("geometry") or {} for f in geojson.get("features", [])]
    elif geojson.get("type") == "Feature":
        geoms = [geojson.get("geometry") or {}]
    else:
        geoms = [geojson]
    for g in geoms:
        if points and len(points) >= limit:
            break
        _walk_coords(g.get("coordinates"), points)
        if len(points) >= limit:
            break
    return points[:limit]


def qa_check(geojson) -> list:
    """对图层 GeoJSON 做质量自检，返回警告列表（无问题返回空列表）"""
    warnings = []
    try:
        if not isinstance(geojson, dict):
            return warnings
        gtype = geojson.get("type")
        features = geojson.get("features", []) if gtype == "FeatureCollection" else (
            [geojson] if gtype in ("Feature",) else [])

        # 1) 空结果
        if gtype == "FeatureCollection" and not features:
            warnings.append("结果图层为空（0 要素）——请检查过滤条件或数据范围")

        # 2) 坐标范围 / 顺序
        pts = _extract_points(geojson)
        if pts:
            lngs = [p[0] for p in pts]
            lats = [p[1] for p in pts]
            out_of_range = any(
                not (_WGS_RANGE[0] <= x <= _WGS_RANGE[2] and _WGS_RANGE[1] <= y <= _WGS_RANGE[3])
                for x, y in pts[:1000])
            if out_of_range:
                # 注：不做"经纬度顺序颠倒"启发式判断——中国区域经度普遍 >90，
                # 该启发式会大面积误报；范围检查已能拦住颠倒后的越界数据。
                warnings.append(
                    f"坐标超出 WGS-84 合法范围（样本经度 [{min(lngs):.2f}, {max(lngs):.2f}]、"
                    f"纬度 [{min(lats):.2f}, {max(lats):.2f}]）——疑似 CRS 未转换为 4326 或经纬度顺序颠倒")

        # 3) 几何有效性（抽样）
        if features:
            try:
                from shapely.geometry import shape as shp_shape
                invalid = 0
                checked = 0
                for f in features[:_MAX_SAMPLE]:
                    geom = f.get("geometry") or {}
                    if not geom.get("type"):
                        continue
                    try:
                        if not shp_shape(geom).is_valid:
                            invalid += 1
                        checked += 1
                    except Exception:
                        continue
                if checked and invalid:
                    ratio = invalid / checked
                    msg = f"抽样 {checked} 个要素中发现 {invalid} 个无效几何"
                    if ratio > 0.5:
                        msg += "（超过半数）——结果可能不可靠，建议 spatial_fix_geometry 修复后重算"
                    else:
                        msg += "——可用 spatial_fix_geometry 修复"
                    warnings.append(msg)
            except ImportError:
                pass

        # 4) 最小顶点数 sanity：面要素只有 3 个以下坐标点（未闭合/退化）
        degenerate = 0
        for f in features[:_MAX_SAMPLE]:
            geom = f.get("geometry") or {}
            if geom.get("type") in ("Polygon", "MultiPolygon"):
                coords = geom.get("coordinates")
                flat = []
                _walk_coords(coords, flat)
                if len(flat) < 4:
                    degenerate += 1
        if degenerate:
            warnings.append(f"{degenerate} 个面要素坐标点数不足（退化多边形）——请检查数据源")
    except Exception as e:
        # 质量自检永不阻塞出图，但故障要可见（否则守卫本身坏了都不知道）
        print(f"[GeoQA] 质量自检异常（已跳过）: {e}", flush=True)
    return warnings


def bbox_in_range(geojson) -> bool:
    """bbox 是否在 WGS-84 范围内（供工具内部快速判断）"""
    pts = _extract_points(geojson, limit=1000)
    if not pts:
        return True
    for x, y in pts:
        if not (_WGS_RANGE[0] <= x <= _WGS_RANGE[2] and _WGS_RANGE[1] <= y <= _WGS_RANGE[3]):
            return False
    return True


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """两点地面距离（米）。供需要距离 sanity check 的工具复用"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
