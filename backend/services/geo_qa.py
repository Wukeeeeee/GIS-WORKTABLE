# -*- coding: utf-8 -*-
"""地理数据质量自检（Geo QA）

在图层通道出口（_push_layer / _register_layer）对每个产出图层做轻量体检，
把可疑的地理错误变成显式警告，而不是静默输出错误数据：

- 坐标范围：bbox 超出 WGS-84 合法范围 → 疑似 CRS 未转换（如投影坐标/ GCJ-02 直出）
- 坐标顺序：颠倒导致经纬度越界时，通过范围检查提示
- 几何有效性：抽样 shapely is_valid，无效几何给出修复提示
- 空结果：FeatureCollection 零要素 → 提示分析可能无意义
- 自相交缓冲类异常：单要素坐标数异常（<最小顶点数）→ 提示

设计约束：绝不抛异常、绝不阻塞出图——警告只附加信息，不改变数据。
"""
import math
from numbers import Real

_WGS_RANGE = (-180.0, -90.0, 180.0, 90.0)
_MAX_SAMPLE = 200          # 有效性抽样的最大要素数


def _walk_coords(coords, out, limit):
    """递归收集坐标点到 out（列表复用，避免大图层深拷贝）"""
    if len(out) >= limit:
        return
    if not coords or not isinstance(coords, (list, tuple)):
        return
    if (len(coords) >= 2 and isinstance(coords[0], Real) and isinstance(coords[1], Real)
            and not isinstance(coords[0], bool) and not isinstance(coords[1], bool)):
        try:
            x, y = float(coords[0]), float(coords[1])
        except (OverflowError, TypeError, ValueError):
            return
        if math.isfinite(x) and math.isfinite(y):
            out.append((x, y))
        return
    for c in coords:
        if len(out) >= limit:
            break
        _walk_coords(c, out, limit)


def _walk_geometry(geom, out, limit):
    if len(out) >= limit:
        return
    if not isinstance(geom, dict):
        return
    if geom.get("type") == "GeometryCollection":
        children = geom.get("geometries", [])
        if isinstance(children, list):
            for child in children:
                if len(out) >= limit:
                    break
                _walk_geometry(child, out, limit)
    else:
        _walk_coords(geom.get("coordinates"), out, limit)


def _extract_points(geojson: dict, limit: int = 5000):
    """提取前 limit 个坐标点用于统计判断"""
    points = []
    if not isinstance(geojson, dict) or limit <= 0:
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
        _walk_geometry(g, points, limit)
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
                for x, y in pts)
            if out_of_range:
                # 注：不做"经纬度顺序颠倒"启发式判断——中国区域经度普遍 >90，
                # 该启发式会大面积误报；范围检查已能拦住颠倒后的越界数据。
                # 若数据天然跨越反经线（lon 跨越 180），越界可能误报，提示用户可忽略
                lng_span = max(lngs) - min(lngs)
                crossing_antimeridian = lng_span > 180.0
                msg = (
                    f"坐标超出 WGS-84 合法范围（样本经度 [{min(lngs):.2f}, {max(lngs):.2f}]、"
                    f"纬度 [{min(lats):.2f}, {max(lats):.2f}]）疑似 CRS 未转换为 4326 或经纬度顺序颠倒"
                )
                if crossing_antimeridian:
                    msg += "；若数据跨越反经线（太平洋区域），可忽略该警告"
                warnings.append(msg)

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
                        invalid += 1
                        checked += 1
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
            geom_type = geom.get("type")
            coords = geom.get("coordinates")
            if geom_type == "Polygon" and isinstance(coords, (list, tuple)):
                if not coords or not isinstance(coords[0], (list, tuple)) or len(coords[0]) < 4:
                    degenerate += 1
            elif geom_type == "MultiPolygon" and isinstance(coords, (list, tuple)):
                if any(
                    not polygon or not isinstance(polygon[0], (list, tuple)) or len(polygon[0]) < 4
                    for polygon in coords
                ):
                    degenerate += 1
        if degenerate:
            warnings.append(f"{degenerate} 个面要素坐标点数不足（退化多边形）——请检查数据源")
    except Exception as e:
        # 质量自检永不阻塞出图，但故障要可见（否则守卫本身坏了都不知道）
        print(f"[GeoQA] 质量自检异常（已跳过）: {e}", flush=True)
    return warnings
