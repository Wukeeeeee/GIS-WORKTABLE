"""
GIS WorkTable — 网络分析服务
networkx + shapely 驱动：路线、服务区、最近设施
"""

import networkx as nx
from shapely.geometry import Point, LineString, Polygon, shape
from shapely.ops import nearest_points, unary_union
import geopandas as gpd
import numpy as np
import json
import math
import hashlib


# ============================================================
# 图缓存（避免重复建图）
# ============================================================

_graph_cache = {}  # cache_key → (graph, geojson_hash)

def _get_cached_graph(geojson: dict) -> nx.DiGraph:
    """
    从缓存获取图，如果 GeoJSON 未变化则复用缓存的图。
    """
    geo_str = json.dumps(geojson, ensure_ascii=False, sort_keys=True)
    h = hashlib.md5(geo_str.encode('utf-8')).hexdigest()
    if h in _graph_cache:
        return _graph_cache[h][0]
    g = build_graph_from_geojson(geojson)
    # 只缓存到内存，限制最大缓存数
    if len(_graph_cache) > 20:
        # 清除最旧的缓存
        oldest = next(iter(_graph_cache))
        del _graph_cache[oldest]
    _graph_cache[h] = (g, h)
    return g

def clear_graph_cache():
    """清除图缓存（工程切换时调用）"""
    _graph_cache.clear()


# ============================================================
# 工具函数
# ============================================================

def _haversine(p1, p2):
    """两点距离（米）"""
    lat1, lon1 = math.radians(p1[1]), math.radians(p1[0])
    lat2, lon2 = math.radians(p2[1]), math.radians(p2[0])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def _parse_coord(s):
    """解析 'lng,lat' 字符串为 (lng, lat)"""
    parts = s.split(",")
    return float(parts[0].strip()), float(parts[1].strip())


# ============================================================
# 建图
# ============================================================

def build_graph_from_geojson(geojson: dict, weight_field: str = "") -> nx.DiGraph:
    """
    将路网 GeoJSON 转为 networkx 有向加权图。
    
    每条 LineString 要素拆为节点对，权重 = 距离（米）。
    如果指定 weight_field，读取字段值作为权重（如耗时、速度倒数）。
    """
    g = nx.DiGraph()
    features = geojson.get("features", [])
    if not features:
        return g

    for feat in features:
        geom = feat.get("geometry")
        if not geom or geom.get("type") not in ("LineString", "MultiLineString"):
            continue

        props = feat.get("properties", {}) or {}
        lines = []
        if geom["type"] == "MultiLineString":
            for coords in geom["coordinates"]:
                lines.append(LineString(coords))
        else:
            lines.append(LineString(geom["coordinates"]))

        for line in lines:
            coords = list(line.coords)
            for i in range(len(coords) - 1):
                p1, p2 = coords[i], coords[i+1]
                d = _haversine(p1, p2)
                w = float(props.get(weight_field, d)) if weight_field else d
                g.add_edge(p1, p2, weight=w, distance=d)
                g.add_edge(p2, p1, weight=w, distance=d)

    return g


def find_nearest_node(graph: nx.DiGraph, point: tuple, max_dist: float = 500) -> tuple:
    """
    找距离 point 最近的图节点。
    point: (lng, lat)
    返回: (lng, lat) 或 None
    """
    if not graph.nodes:
        return None
    nearest = None
    min_d = float("inf")
    for node in graph.nodes:
        d = _haversine(point, node)
        if d < min_d:
            min_d = d
            nearest = node
    if min_d > max_dist:
        return None
    return nearest


def snap_to_network(geojson: dict, point: tuple, max_dist: float = 500) -> dict:
    """
    将点吸附到最近的路网节点（使用图缓存）。

    Returns:
        {"snapped": [lng, lat] | None, "distance_m": float, "found": bool}
    """
    graph = _get_cached_graph(geojson)
    if not graph.nodes:
        return {"snapped": None, "distance_m": 0, "found": False, "error": "路网为空"}

    node = find_nearest_node(graph, point, max_dist)
    if node is None:
        nearest = None
        min_d = float("inf")
        for n in graph.nodes:
            d = _haversine(point, n)
            if d < min_d:
                min_d = d
                nearest = n
        return {"snapped": list(nearest), "distance_m": round(min_d, 1), "found": False}
    return {"snapped": list(node), "distance_m": round(_haversine(point, node), 1), "found": True}


# ============================================================
# 最短路径
# ============================================================

def _route_segment(graph, from_node, to_node):
    """计算单段路径，返回 (path_nodes, distance, steps) 或 None"""
    try:
        path_nodes = nx.astar_path(
            graph, from_node, to_node,
            heuristic=lambda a, b: _haversine(a, b),
            weight="weight"
        )
    except (nx.NetworkXNoPath, Exception):
        return None

    distance = 0.0
    steps = []
    for i in range(len(path_nodes) - 1):
        a, b = path_nodes[i], path_nodes[i+1]
        d = graph[a][b]["distance"]
        distance += d
        steps.append({"from": list(a), "to": list(b), "distance_m": round(d, 1)})
    return path_nodes, distance, steps


def shortest_route(
    geojson: dict,
    origin: tuple,
    dest: tuple,
    weight_field: str = "",
    waypoints: list = None,
) -> dict:
    """
    最短路径分析，支持途经点。

    Args:
        geojson: 路网数据
        origin: (lng, lat) 起点
        dest: (lng, lat) 终点
        waypoints: [(lng, lat), ...] 途经点列表（可选）

    Returns:
        {
            "path": GeoJSON LineString,
            "distance_m": float,
            "steps": [...],
            "segments": [...],
        }
    """
    graph = _get_cached_graph(geojson) if not weight_field else build_graph_from_geojson(geojson, weight_field)
    if not graph.nodes:
        return {"error": "路网为空，无法分析"}

    all_pts = [origin] + (waypoints or []) + [dest]
    all_nodes = []
    for pt in all_pts:
        node = find_nearest_node(graph, pt)
        if not node:
            return {"error": f"坐标 ({pt[0]:.4f}, {pt[1]:.4f}) 距路网超过阈值，请靠近道路设点"}
        all_nodes.append(node)

    segments_data = []
    total_distance = 0.0
    all_path_nodes = []
    for i in range(len(all_nodes) - 1):
        result = _route_segment(graph, all_nodes[i], all_nodes[i+1])
        if result is None:
            return {"error": f"第 {i+1} 段无法连通，路网可能不连续"}
        path_nodes, seg_dist, seg_steps = result
        if all_path_nodes and path_nodes:
            path_nodes = path_nodes[1:]
        all_path_nodes.extend(path_nodes)
        total_distance += seg_dist
        segments_data.append((seg_dist, seg_steps, path_nodes))

    segments = []
    steps = []
    for i, (seg_dist, seg_steps, path_nodes) in enumerate(segments_data):
        steps.extend(seg_steps)
        segments.append({
            "from": list(all_pts[i]),
            "to": list(all_pts[i+1]),
            "distance_m": round(seg_dist, 1),
            "distance_km": round(seg_dist / 1000, 2),
            "node_count": len(path_nodes) + (1 if i > 0 else 0),
        })

    line = LineString(all_path_nodes)
    path_geojson = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": list(line.coords),
        },
        "properties": {
            "distance_m": round(total_distance, 1),
            "distance_km": round(total_distance / 1000, 2),
            "segments": len(segments),
        },
    }

    return {
        "path": path_geojson,
        "distance_m": round(total_distance, 1),
        "distance_km": round(total_distance / 1000, 2),
        "steps": steps,
        "segments": segments,
        "node_count": len(all_path_nodes),
    }


# ============================================================
# 服务区
# ============================================================

def service_area(
    geojson: dict,
    facility: tuple,
    breaks: list = None,
    weight_field: str = "",
) -> dict:
    """
    服务区分析：从设施点出发，沿路网扩散到指定断值距离。
    
    Returns:
        {
            "polygons": GeoJSON FeatureCollection,
            "areas": [{"break": float, "area_km2": float}, ...]
        }
    """
    if breaks is None:
        breaks = [1000, 3000, 5000]

    graph = _get_cached_graph(geojson) if not weight_field else build_graph_from_geojson(geojson, weight_field)
    if not graph.nodes:
        return {"error": "路网为空，无法分析"}

    facility_node = find_nearest_node(graph, facility)
    if not facility_node:
        return {"error": "设施点距路网超过阈值"}

    breaks_sorted = sorted(breaks)
    # 从设施点出发 BFS/双向 Dijkstra，累加距离
    distances = nx.single_source_dijkstra_path_length(graph, facility_node, weight="weight")
    
    # 按断值分组
    polygons = []
    area_infos = []
    prev_break = 0
    for brk in breaks_sorted:
        nodes_in_range = [n for n, d in distances.items() if d <= brk]
        if not nodes_in_range:
            continue
        points = [Point(n) for n in nodes_in_range]
        if len(points) < 3:
            continue
        # 用点集的凸包作为服务区边界
        hull = unary_union(points).convex_hull
        # 用缓冲区让边界平滑一些
        hull_buffered = hull.buffer(0.001)
        if hull_buffered.is_empty:
            continue
        try:
            geojson_geom = json.loads(json.dumps(hull_buffered.__geo_interface__))
        except Exception:
            continue

        # 计算面积（近似：用 WGS-84 球面面积）
        gdf = gpd.GeoDataFrame(geometry=[hull_buffered], crs="EPSG:4326")
        gdf_proj = gdf.to_crs(gdf.estimate_utm_crs())
        area_km2 = round(gdf_proj.geometry.area.iloc[0] / 1_000_000, 2)

        polygons.append({
            "type": "Feature",
            "geometry": geojson_geom,
            "properties": {
                "break_m": brk,
                "area_km2": area_km2,
                "from_m": prev_break,
                "to_m": brk,
            },
        })
        area_infos.append({"break": brk, "area_km2": area_km2})
        prev_break = brk

    if not polygons:
        return {"error": "服务区计算失败，范围太小或路网不连通"}

    return {
        "polygons": {
            "type": "FeatureCollection",
            "features": polygons,
        },
        "areas": area_infos,
    }


# ============================================================
# 最近设施
# ============================================================

def closest_facilities(
    geojson: dict,
    event: tuple,
    facilities: list,
    n: int = 3,
    weight_field: str = "",
) -> dict:
    """
    最近设施分析。
    
    Args:
        event: (lng, lat) 事件点
        facilities: [(lng, lat), ...] 设施点列表
        n: 返回最近的 N 个
    
    Returns:
        {
            "paths": [GeoJSON LineString, ...],
            "summary": [{"facility_idx": int, "distance_m": float, ...}, ...]
        }
    """
    graph = _get_cached_graph(geojson) if not weight_field else build_graph_from_geojson(geojson, weight_field)
    if not graph.nodes:
        return {"error": "路网为空，无法分析"}

    event_node = find_nearest_node(graph, event)
    if not event_node:
        return {"error": "事件点距路网超过阈值"}

    results = []
    for i, fac in enumerate(facilities):
        fac_node = find_nearest_node(graph, fac)
        if not fac_node:
            continue
        try:
            path_nodes = nx.astar_path(
                graph, fac_node, event_node,
                heuristic=lambda a, b: _haversine(a, b),
                weight="weight"
            )
            d = sum(graph[path_nodes[j]][path_nodes[j+1]]["distance"]
                    for j in range(len(path_nodes) - 1))
            line = LineString(path_nodes)
            results.append({
                "facility_idx": i,
                "facility_coord": fac,
                "distance_m": round(d, 1),
                "distance_km": round(d / 1000, 2),
                "path": {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": list(line.coords),
                    },
                    "properties": {
                        "facility_idx": i,
                        "distance_m": round(d, 1),
                    },
                },
            })
        except (nx.NetworkXNoPath, Exception):
            continue

    results.sort(key=lambda r: r["distance_m"])
    top = results[:n]

    if not top:
        return {"error": "所有设施均无法连通"}

    return {
        "paths": [r["path"] for r in top],
        "summary": [
            {
                "rank": idx + 1,
                "facility_idx": r["facility_idx"],
                "distance_m": r["distance_m"],
                "distance_km": r["distance_km"],
            }
            for idx, r in enumerate(top)
        ],
    }
