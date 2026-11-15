# -*- coding: utf-8 -*-
"""
backend.services.tool_modules.network
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Network analysis, routing, OD cost matrix, transit lines, and least-cost path.

Strict architectural constraints:
- Depends on runtime.py, common.py, shared raster helpers, and GIS/network libraries.
- NEVER imports backend.services.tools or tools (zero circular imports).
"""

import concurrent.futures
import copy
import datetime
import json
import math
import os
import re
import sys
import time
import uuid
from numbers import Real
from typing import Any, Dict, List, Literal, Optional

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import Point, LineString, Polygon, box
from langchain.tools import tool

from backend.services.task_manager import register_artifact
from backend.services.tool_modules.raster import (
    _find_uploaded_tif,
    _raster_output_dir,
    _write_raster_output,
    _raster_preview_op,
)
from backend.services.tool_modules.runtime import (
    _registered_layers,
    _pending_layers,
    _pending_layer_ops,
    _state_lock,
    get_temp_output_dir,
    _layer_to_gdf,
    _gdf_to_layer,
    _push_layer,
    _register_layer,
    _disambiguate_layer_name,
    init_temp_dir,
    get_current_task_id,
    get_current_run_id,
)
from backend.services.tool_modules.common import (
    _compute_bbox,
    _make_fid,
    _safe_layer_export_stem,
)



def record_tool_artifact(filename: str, filepath: str, artifact_type: str = "image", step: int = 0) -> Optional[dict]:
    """统一记录工具生成的产物到 TaskManager (任务台账) 与 StorageService (SQLite事实台账)。"""
    current_task_id = get_current_task_id()
    current_run_id = get_current_run_id()
    art = None
    if current_task_id:
        try:
            art = register_artifact(current_task_id, filename, filepath,
                                    artifact_type=artifact_type, created_by_step=step)
        except Exception as e:
            print(f"[Tools] register_artifact 出错: {e}", flush=True)
    if current_run_id:
        try:
            from backend.services import storage_service
            art_id = (art.get("artifact_id") if art else "") or uuid.uuid4().hex[:10]
            storage_service.register_run_artifact(
                current_run_id, art_id, filename, filepath, file_type=artifact_type
            )
        except Exception as e:
            print(f"[Tools] register_run_artifact 出错: {e}", flush=True)
    return art


def _format_extent(bbox: list) -> str:
    """将 bbox 转为可读的描述文本（内部辅助函数，不暴露给 AI）"""
    if not bbox or bbox == [0, 0, 0, 0]:
        return "未知范围"
    lng = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    span_lng = bbox[2] - bbox[0]
    span_lat = bbox[3] - bbox[1]
    loc = f"中心: {lat:.3f}°N, {lng:.3f}°E"
    if span_lng < 0.1 and span_lat < 0.1:
        loc += "（小范围）"
    elif span_lng < 1 and span_lat < 1:
        loc += "（城区级）"
    else:
        loc += "（大区域）"
    return loc


def _point_in_bbox(lng: float, lat: float, bbox: list) -> bool:
    """判断坐标是否在 bbox [minLng, minLat, maxLng, maxLat] 内"""
    if not bbox or len(bbox) < 4:
        return False
    return bbox[0] <= lng <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _find_layer_for_coord(lng: float, lat: float) -> str:
    """在所有已注册图层中找到包含该坐标的图层名，返回第一个匹配"""
    for name, info in _registered_layers.items():
        bbox = info.get("bbox", [])
        if _point_in_bbox(lng, lat, bbox):
            return name
    return ""


def _parse_coord(s: str) -> tuple:
    """解析 "经度,纬度" 字符串"""
    parts = s.split(",")
    if len(parts) != 2:
        raise ValueError(f"坐标格式错误，需要 '经度,纬度' 格式，收到: '{s}'")
    try:
        longitude, latitude = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        raise ValueError(f"坐标值非数字，收到: '{s}'")
    if (not math.isfinite(longitude) or not math.isfinite(latitude)
            or not -180 <= longitude <= 180 or not -90 <= latitude <= 90):
        raise ValueError(f"经纬度超出有效范围，收到: '{s}'")
    return longitude, latitude


def _stats_out_dir(kind: str = "") -> str:
    """空间统计文件产物目录（<temp>/stats[/kind]），与图层通道无关。"""
    init_temp_dir()
    d = os.path.join(get_temp_output_dir(), "stats", kind) if kind else os.path.join(get_temp_output_dir(), "stats")
    os.makedirs(d, exist_ok=True)
    return d


def _stats_safe_name(name: str) -> str:
    """文件名安全化：保留中英文与数字。"""
    return (re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(name)).strip("_") or "layer")[:60]


def _stats_summary(tool: str, payload: dict) -> str:
    """短机器可读摘要行（JSON），便于前端/测试稳定解析。"""
    try:
        return "STATS_SUMMARY: " + json.dumps({"tool": tool, **payload}, ensure_ascii=False, default=str)
    except Exception:
        return ""


def _cost_graph(cost_arr, transform=None, crs=None):
    """cost_distance / least_cost_path 共用的 8 邻域代价图。
    生产调用传入栅格仿射变换和 CRS，边权为平均代价 × 相邻像元中心的地面距离（米）。"""
    import numpy as np
    from scipy.sparse import csr_matrix
    if (transform is None) != (crs is None):
        raise ValueError("计算地面距离需要同时提供栅格 transform 和 CRS")
    geodesic = None
    unit_to_meters = None
    if transform is not None:
        from pyproj import CRS
        raster_crs = CRS.from_user_input(crs)
        if raster_crs.is_geographic:
            geodesic = raster_crs.get_geod()
        elif raster_crs.is_projected and raster_crs.axis_info:
            unit_to_meters = raster_crs.axis_info[0].unit_conversion_factor
            if not unit_to_meters or not math.isfinite(unit_to_meters):
                raise ValueError("栅格 CRS 的线性单位无法换算为米")
        else:
            raise ValueError("代价栅格 CRS 必须是地理或投影坐标系")
    h, w = cost_arr.shape
    valid = np.isfinite(cost_arr) & (cost_arr > 0)
    valid_count = int(valid.sum())
    if valid_count > 100_000:
        raise ValueError("有效代价像元超过单次处理上限（10 万）；请先裁剪或重采样栅格")
    idx = np.full((h, w), -1, dtype=np.int64)
    idx[valid] = np.arange(valid_count)
    rows_l, cols_l, vals = [], [], []
    nb = [(-1, 0), (1, 0), (0, -1), (0, 1),
          (-1, -1), (-1, 1), (1, -1), (1, 1)]
    ca = cost_arr
    for r in range(h):
        for c in range(w):
            if not valid[r, c]:
                continue
            u = idx[r, c]
            for dr, dc in nb:
                rr, cc = r + dr, c + dc
                if 0 <= rr < h and 0 <= cc < w and valid[rr, cc]:
                    if transform is None:
                        distance = math.hypot(dc, dr)
                    else:
                        x0, y0 = transform * (c + 0.5, r + 0.5)
                        x1, y1 = transform * (cc + 0.5, rr + 0.5)
                        if geodesic is not None:
                            distance = geodesic.inv(x0, y0, x1, y1)[2]
                        else:
                            distance = math.hypot(x1 - x0, y1 - y0) * unit_to_meters
                    rows_l.append(u); cols_l.append(idx[rr, cc])
                    vals.append((float(ca[r, c]) + float(ca[rr, cc])) * 0.5 * distance)
    n = valid_count
    g = csr_matrix((vals, (rows_l, cols_l)), shape=(n, n))
    return g, idx, valid


@tool
def download_road_network(location_name: str, network_type: str = "drive") -> str:
    """从 OpenStreetMap 下载指定城市/区域的路网数据并加载到地图，供 network_analysis 使用。
location_name: 城市名（如"北京市""广州市""上海浦东新区"），或"经度,纬度,经度,纬度"（bbox）。
network_type: drive(车行路) walk(步行) bike(骑行) all(全部)，默认 drive。"""
    if not isinstance(location_name, str) or not location_name.strip():
        return "路网下载失败：请提供城市名或经纬度范围"
    location_name = location_name.strip()
    if not isinstance(network_type, str) or network_type.strip().lower() not in {"drive", "walk", "bike", "all"}:
        return "路网下载失败：network_type 仅支持 drive、walk、bike、all"
    network_type = network_type.strip().lower()

    parts = [p.strip() for p in location_name.split(",")]
    bbox = None
    if len(parts) == 4:
        try:
            bbox = tuple(float(value) for value in parts)
        except (TypeError, ValueError, OverflowError):
            return "路网下载失败：BBox 必须按 min_lng,min_lat,max_lng,max_lat 提供数值坐标"
        import math
        min_lng, min_lat, max_lng, max_lat = bbox
        if not all(math.isfinite(value) for value in bbox):
            return "路网下载失败：BBox 坐标必须是有限数值"
        if not (-180 <= min_lng <= 180 and -180 <= max_lng <= 180
                and -90 <= min_lat <= 90 and -90 <= max_lat <= 90):
            return "路网下载失败：BBox 经度须在 -180 至 180、纬度须在 -90 至 90 范围内"
        if min_lng >= max_lng or min_lat >= max_lat:
            return "路网下载失败：BBox 最小经度/纬度必须小于最大经度/纬度"

    try:
        import osmnx as ox
    except ImportError:
        return "错误：osmnx 未安装，请执行 pip install osmnx"

    try:
        import concurrent.futures

        ox.settings.log_console = False
        ox.settings.use_cache = True

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _fetch():
            if bbox is not None:
                min_lng, min_lat, max_lng, max_lat = bbox
                return ox.graph_from_bbox(north=max_lat, south=min_lat, east=max_lng, west=min_lng, network_type=network_type)
            else:
                return ox.graph_from_place(location_name, network_type=network_type)

        fut = executor.submit(_fetch)
        try:
            G = fut.result(timeout=120)
        except concurrent.futures.TimeoutError:
            # 显式 cancel + 关闭线程池，防止后台 osmnx 继续占用 socket
            fut.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            return (
                f"错误：下载「{location_name}」路网超时（120秒），OSM 服务器无响应。\n\n"
                f"请尝试以下替代方案：\n"
                f"1. 前往 https://www.geofabrik.de 下载对应地区 .osm.pbf 文件（国内可访问）\n"
                f"2. 前往 https://extract.bbbike.org 用矩形框选区域导出 .osm（支持国内访问）\n"
                f"3. 将下载的文件上传到 GIS WorkTable，AI 会自动识别为路网图层\n"
                f"4. 上传后告诉我，我再调用 network_analysis 分析"
            )
        except Exception:
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True, cancel_futures=True)

        nodes, edges = ox.graph_to_gdfs(G)
        if edges.empty:
            return f"错误：未找到「{location_name}」的路网数据"

        geojson = edges.__geo_interface__
        layer_name = f"{location_name}_路网({network_type})"
        _push_layer(layer_name, geojson, {"color": "#555", "weight": 1.5})
        _register_layer(layer_name, geojson)

        node_count = len(nodes)
        edge_count = len(edges)
        bbox = _compute_bbox(geojson)
        extent = _format_extent(bbox)
        return (
            f"已从 OSM 下载「{location_name}」路网（{network_type}），"
            f"共 {node_count} 个节点、{edge_count} 条道路，{extent}。"
            f"图层名「{layer_name}」，已加载到地图。"
            f"接下来可以用 network_analysis 工具分析此路网。"
        )
    except Exception as e:
        return f"下载路网失败: {str(e)[:300]}"


@tool
def network_analysis(
    layer_name: str = "",
    analysis_type: str = "",
    origin: str = "",
    destination: str = "",
    facility: str = "",
    events: str = "",
    breaks: str = "",
    n: int = 3,
) -> str:
    """从路网图层执行网络分析（结果自动加载到地图）。
    - analysis_type: 'route'(最短路径,双向Dijkstra) / 'service_area'(服务区) / 'closest_facility'(最近设施)。
    - origin / destination / facility: 坐标，格式为 "经度,纬度"（WGS84）。地名需先经 amap_geocode 转坐标。
    - events: 分号分隔坐标点；breaks: 逗号分隔阻抗米数；n: 最近设施数(默认 3)。"""
    from backend.services.network_service import (
        shortest_route, service_area, closest_facilities,
    )

    # 收集分析所需的坐标，用于图层匹配
    need_coords = []
    event_coords = []
    try:
        if origin:
            need_coords.append(_parse_coord(origin))
        if destination:
            need_coords.append(_parse_coord(destination))
        if facility:
            need_coords.append(_parse_coord(facility))
        if analysis_type == "closest_facility" and events:
            event_coords = [_parse_coord(value.strip()) for value in events.split(";")]
            need_coords.extend(event_coords)
    except ValueError as e:
        return f"坐标参数错误: {e}"

    # 根据坐标自动匹配图层
    if not layer_name:
        for c in need_coords:
            matched = _find_layer_for_coord(c[0], c[1])
            if matched:
                layer_name = matched
                break
        if not layer_name:
            return "错误：请先通过 get_registered_layers 查看已加载的路网图层，再指定正确的 layer_name"

    info = _registered_layers.get(layer_name)
    if not info:
        matches = [n for n in _registered_layers.keys() if layer_name in n] if layer_name else []
        if len(matches) == 1:
            info = _registered_layers[matches[0]]
            layer_name = matches[0]
        elif len(matches) > 1:
            return f"错误：找到多个匹配：{', '.join(matches)}，请指定完整名称"
        elif not _registered_layers:
            return "错误：当前没有已加载的图层，请先上传路网数据"
        else:
            return f"错误：未找到图层「{layer_name}」，当前图层：{', '.join(_registered_layers.keys()) or '无'}"

    geojson = info.get("geojson", {})
    if not geojson:
        return f"错误：图层「{layer_name}」数据为空"

    # 校验坐标是否在图层范围内
    layer_bbox = info.get("bbox", [])
    for c in need_coords:
        if not _point_in_bbox(c[0], c[1], layer_bbox):
            alt = _find_layer_for_coord(c[0], c[1])
            if alt:
                return (f"错误：坐标 ({c[0]:.4f}, {c[1]:.4f}) 不在图层「{layer_name}」范围内，"
                        f"但匹配到图层「{alt}」。请将 layer_name 设为「{alt}」后重试")
            return (f"错误：坐标 ({c[0]:.4f}, {c[1]:.4f}) 不在图层「{layer_name}」范围内，"
                    f"当前图层的覆盖范围为 {_format_extent(layer_bbox)}。请确认使用的是正确的路网图层")

    try:
        if analysis_type == "route":
            if not origin or not destination:
                return "错误：路线分析需要 origin 和 destination 参数"
            o = _parse_coord(origin)
            d = _parse_coord(destination)
            result = shortest_route(geojson, o, d)
            if "error" in result:
                return f"路径分析失败: {result['error']}"
            _push_layer(f"路径_{layer_name}", {
                "type": "FeatureCollection",
                "features": [result["path"]],
            })
            return (
                f"路径分析完成：总距离 {result['distance_km']} km，"
                f"{result['node_count']} 个途经节点，已加载到地图"
            )

        elif analysis_type == "service_area":
            if not facility:
                return "错误：服务区分析需要 facility 参数"
            f = _parse_coord(facility)
            breaks_list = [int(b.strip()) for b in breaks.split(",")] if breaks else [1000, 3000, 5000]
            result = service_area(geojson, f, breaks_list)
            if "error" in result:
                return f"服务区分析失败: {result['error']}"
            _push_layer(f"服务区_{layer_name}", result["polygons"])
            area_str = "；".join(f"{a['break']}m:{a['area_km2']}km²" for a in result["areas"])
            return (f"服务区分析完成：{area_str}；地图边界为近似范围"
                    "（可达路网节点凸包 + 0.001°缓冲，不是逐道路可达边界），已加载到地图")

        elif analysis_type == "closest_facility":
            if not origin:
                return "错误：最近设施分析需要 origin（事件点）和已注册的设施图层"
            o = _parse_coord(origin)
            fac_list = event_coords
            if not fac_list:
                return "错误：请通过 events 参数提供设施点坐标（分号分隔）"
            result = closest_facilities(geojson, o, fac_list, n)
            if "error" in result:
                skipped = result.get("unsnapped_facility_indices", [])
                unreachable = result.get("unreachable_facility_indices", [])
                details = []
                if skipped:
                    details.append("超出 500 m 吸附距离的设施序号（从 1 开始）：" + ", ".join(str(i + 1) for i in skipped))
                if unreachable:
                    details.append("路网不可达的设施序号（从 1 开始）：" + ", ".join(str(i + 1) for i in unreachable))
                suffix = "；" + "；".join(details) if details else ""
                return f"最近设施分析失败: {result['error']}{suffix}"
            _push_layer(f"最近设施_{layer_name}", {
                "type": "FeatureCollection",
                "features": result["paths"],
            })
            lines = [f"最近设施分析完成（前 {len(result['summary'])} 条）："]
            for s in result["summary"]:
                lines.append(f"  #{s['rank']} 设施{s['facility_idx']}：{s['distance_km']} km")
            skipped = result.get("unsnapped_facility_indices", [])
            unreachable = result.get("unreachable_facility_indices", [])
            if skipped:
                lines.append("未吸附设施序号（从 1 开始，未纳入结果）：" + ", ".join(str(i + 1) for i in skipped))
            if unreachable:
                lines.append("路网不可达设施序号（从 1 开始，未纳入结果）：" + ", ".join(str(i + 1) for i in unreachable))
            return "\n".join(lines)

        else:
            return f"错误：不支持的分析类型：{analysis_type}，可选：route / service_area / closest_facility"

    except Exception as e:
        return f"网络分析失败: {str(e)[:300]}"


@tool
def od_cost_matrix(origins_layer: str, destinations_layer: str, network_source: str = "osm") -> str:
    """多对多 OD 成本矩阵：起点/终点吸附到既有 OSM 路网节点后跑多源 Dijkstra，输出成本矩阵文件产物。
    - origins_layer: 起点图层名（点要素）。
    - destinations_layer: 终点图层名（点要素）。
    - network_source: 路网来源。'osm'（默认）= 复用已注册的路网图层（按起点坐标自动匹配）；
      也可直接填已注册路网图层名（如 download_road_network 生成的图层）。
    输出：<临时输出目录>/stats/od/<起点>_<终点>_od_matrix.csv 与同名 .json，并返回总/平均/最大出行成本（米）与不可达对数。
    注意：本工具只产出磁盘文件，不生成地图图层。
    """
    try:
        import numpy as np
        import csv as _csv
        import networkx as nx
        from backend.services import network_service as ns

        ogdf, oname = _layer_to_gdf(origins_layer)
        if ogdf is None:
            return oname
        dgdf, dname = _layer_to_gdf(destinations_layer)
        if dgdf is None:
            return dname
        o_pts = [(float(p.x), float(p.y)) for p in ogdf.geometry.representative_point()]
        d_pts = [(float(p.x), float(p.y)) for p in dgdf.geometry.representative_point()]
        if not o_pts or not d_pts:
            return "错误：起点或终点图层为空"
        src = str(network_source or "osm").strip()
        info = None
        if src and src.lower() != "osm":
            info = _registered_layers.get(src)
            if info is None:
                cands = [n for n in _registered_layers if src in n]
                if len(cands) == 1:
                    src, info = cands[0], _registered_layers[cands[0]]
        if info is None:
            for (x, y) in o_pts:
                cand = _find_layer_for_coord(x, y)
                if cand and cand in _registered_layers:
                    info, src = _registered_layers[cand], cand
                    break
        if info is None and len(_registered_layers) == 1:
            src = next(iter(_registered_layers))
            info = _registered_layers[src]
        if info is None:
            return ("错误：未找到可用的路网图层（network_source='osm' 需要先注册路网）：请先调用 download_road_network 下载路网，"
                    f"或把已注册路网图层名传给 network_source。当前图层：{', '.join(list(_registered_layers.keys())[:10]) or '无'}")
        geojson = info.get("geojson", {})
        if not geojson or not geojson.get("features"):
            return f"错误：路网图层「{src}」为空"
        graph = ns._get_cached_graph(geojson)
        if not graph or not graph.nodes:
            return f"错误：路网图层「{src}」未构建出有效图（需要 LineString/MultiLineString 路网要素）"

        def _snap_all(pts):
            nodes, missed = [], []
            for index, pt in enumerate(pts):
                s = ns.snap_to_network(geojson, pt, max_dist=5000)
                if s.get("found") and s.get("snapped"):
                    nodes.append(tuple(s["snapped"]))
                else:
                    nodes.append(None)
                    missed.append(index)
            return nodes, missed

        o_nodes, o_miss = _snap_all(o_pts)
        d_nodes, d_miss = _snap_all(d_pts)
        if not any(o_nodes) or not any(d_nodes):
            return "错误：起点或终点全部无法吸附到路网节点（请检查路网覆盖范围是否包含起终点）"
        matrix = [[None] * len(d_pts) for _ in range(len(o_pts))]
        for i, onode in enumerate(o_nodes):
            if onode is None or onode not in graph:
                continue
            lengths = nx.single_source_dijkstra_path_length(graph, onode, weight="weight")
            for j, dnode in enumerate(d_nodes):
                if dnode is None:
                    continue
                cost = lengths.get(dnode)
                if cost is not None:
                    matrix[i][j] = round(float(cost), 3)
        flat = [v for row in matrix for v in row if v is not None]
        total = float(np.sum(flat)) if flat else 0.0
        mean_c = float(np.mean(flat)) if flat else 0.0
        max_c = float(np.max(flat)) if flat else 0.0
        unreachable = sum(
            1 for i, row in enumerate(matrix) for j, value in enumerate(row)
            if value is None and o_nodes[i] is not None and d_nodes[j] is not None
        )
        unsnapped_pairs = sum(
            1 for i, row in enumerate(matrix) for j in range(len(row))
            if o_nodes[i] is None or d_nodes[j] is None
        )
        out_dir = _stats_out_dir("od")
        stem = f"{_stats_safe_name(oname)}__{_stats_safe_name(dname)}_od_matrix"
        csv_path = os.path.join(out_dir, stem + ".csv")
        json_path = os.path.join(out_dir, stem + ".json")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["origin_index", "destination_index", "cost_m", "reachable"])
            for i, row in enumerate(matrix):
                for j, v in enumerate(row):
                    w.writerow([i, j, "" if v is None else v, 1 if v is not None else 0])
        payload = {
            "origins_layer": oname, "destinations_layer": dname, "network_layer": src,
            "n_origins": len(o_pts), "n_destinations": len(d_pts),
            "n_origins_snapped": sum(node is not None for node in o_nodes),
            "n_destinations_snapped": sum(node is not None for node in d_nodes),
            "unsnapped_origin_indices": o_miss,
            "unsnapped_destination_indices": d_miss,
            "unsnapped_pairs": unsnapped_pairs,
            "unreachable_pairs": unreachable, "cost_unit": "meter",
            "total_cost_m": round(total, 3), "mean_cost_m": round(mean_c, 3), "max_cost_m": round(max_c, 3),
            "matrix": matrix, "csv": csv_path,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        record_tool_artifact(os.path.basename(csv_path), csv_path, artifact_type="file")
        record_tool_artifact(os.path.basename(json_path), json_path, artifact_type="file")
        summary = _stats_summary("od_cost_matrix", {
            "origins": oname, "destinations": dname, "network_layer": src,
            "n_origins": len(o_pts), "n_destinations": len(d_pts),
            "n_origins_snapped": sum(node is not None for node in o_nodes),
            "n_destinations_snapped": sum(node is not None for node in d_nodes),
            "unsnapped_origin_indices": o_miss,
            "unsnapped_destination_indices": d_miss,
            "unsnapped_pairs": unsnapped_pairs,
            "total_cost_m": round(total, 3), "mean_cost_m": round(mean_c, 3), "max_cost_m": round(max_c, 3),
            "unreachable_pairs": unreachable, "csv": csv_path, "json": json_path,
        })
        miss_txt = ""
        if o_miss or d_miss:
            origin_indices = ", ".join(str(i + 1) for i in o_miss) or "无"
            destination_indices = ", ".join(str(i + 1) for i in d_miss) or "无"
            miss_txt = (f"\n- 未能吸附并保留为无成本单元：起点 {len(o_miss)} 个（输入序号 {origin_indices}）、"
                        f"终点 {len(d_miss)} 个（输入序号 {destination_indices}）")
        return (
            f"OD 成本矩阵完成（多源 Dijkstra，路网图层「{src}」）：\n"
            f"- 起点 {len(o_nodes)} 个，终点 {len(d_nodes)} 个，不可达 {unreachable} 对{miss_txt}\n"
            f"- 总出行成本 {total:.2f} m，平均 {mean_c:.2f} m，最大 {max_c:.2f} m\n"
            f"- 矩阵文件：{csv_path}\n"
            f"- JSON 文件：{json_path}\n"
            f"（本工具产物为磁盘文件而非地图图层）\n"
            f"{summary}"
        )
    except Exception as e:
        return f"错误：OD 成本矩阵计算失败: {str(e)[:300]}"


@tool
def metro_line(city: str, line: str = "") -> str:
    """查询城市地铁线路并上图（站序连线 + 站点图层，官方配色）。
    - city: 城市名（如 长沙/北京/上海/广州/深圳 等国内城市；柏林/东京/纽约 等国际城市）。
    - line: 线路名或编号（如 '1号线' / '2'）；留空 = 展示全城线网。
    国内城市走高德地铁数据（GCJ-02 自动转 WGS-84），国际城市走 OSM Overpass（真实轨道折线，带官方色）。
    结果含站点数、起讫站、换乘站标记。"""
    try:
        from backend.services.metro_service import build_metro_layers, norm_city, CN_CITY_CODES
        cnorm = norm_city(city)
        layers, summary = build_metro_layers(cnorm, line or "")
        out_names = []
        for spec in layers:
            _push_layer(spec["name"], spec["geojson"], spec["style"])
            _register_layer(spec["name"], spec["geojson"])
            out_names.append(spec["name"])
        return (f"地铁线路查询完成：{summary}\n"
                f"- 已上图 {len(out_names)} 个图层：{', '.join(out_names)}\n"
                f"- 来源：{'高德地铁数据（坐标已转 WGS-84）' if cnorm in CN_CITY_CODES else 'OSM 开源数据'}")
    except Exception as e:
        return f"地铁查询失败: {str(e)[:300]}"


@tool
def cost_distance(cost_layer: str, source_layer: str, out_name: str = "") -> str:
    """代价距离面：基于代价栅格，计算每个像元到最近源的最小累积代价（8 邻域 Dijkstra，ArcGIS CostDistance 对应）。
    - cost_layer: 代价栅格（上传的 GeoTIFF，值>0，越大越难通行；nodata/非正值为不可通行）。
    - source_layer: 源要素图层（会烧录到代价栅格网格上作为源像元）。
    - out_name: 输出栅格名。
    输出累积代价 GeoTIFF + 预览图层，并报告可达/不可达像元数。代价按相邻像元中心的实际地面距离（米）累计。"""
    try:
        import numpy as np
        import rasterio
        from scipy.sparse.csgraph import dijkstra
        from rasterio.features import rasterize as rio_rasterize
        tif_path = _find_uploaded_tif(cost_layer)
        if tif_path is None:
            return f"错误：未找到代价栅格「{cost_layer}」，请先上传 GeoTIFF"
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return f"错误：代价栅格「{cost_layer}」缺少 CRS，无法可靠对齐源图层"
            if src.width * src.height > 1_000_000:
                return "代价距离失败：栅格超过单次处理上限（100 万像元）；请先裁剪或重采样"
            cost = src.read(1, masked=True).astype("float64").filled(np.nan)
            transform = src.transform
            crs = src.crs
            nodata = src.nodata
        valid0 = np.isfinite(cost)
        if nodata is not None:
            valid0 &= cost != nodata
        cost = np.where(valid0, cost, np.nan)
        gdf_s, sname = _layer_to_gdf(source_layer)
        if gdf_s is None:
            return sname
        gdf_s = gdf_s.to_crs(crs)
        h, w = cost.shape
        src_r = rio_rasterize(
            ((geom, 1) for geom in gdf_s.geometry if geom is not None),
            out_shape=(h, w), transform=transform, fill=0, dtype="uint8")
        src_nodes = np.argwhere(src_r == 1)
        if src_nodes.size == 0:
            return "错误：源图层与代价栅格范围不相交，没有源像元"
        graph, idx, valid = _cost_graph(cost, transform=transform, crs=crs)
        flat_src = [idx[r, c] for r, c in src_nodes if idx[r, c] >= 0]
        if not flat_src:
            return "错误：源图层落在代价栅格的 NoData 或非正值区域，没有可通行的源像元"
        dist = dijkstra(graph, directed=False, indices=flat_src, min_only=True)
        out = np.full(cost.shape, np.nan, dtype="float64")
        vm = valid & (idx >= 0)
        out[vm] = dist[idx[vm]]
        reachable = int(np.isfinite(out).sum())
        unreachable = int((valid & ~np.isfinite(out)).sum())
        out_name = _safe_layer_export_stem(out_name or f"{cost_layer}_代价距离")
        profile = dict(driver="GTiff", height=h, width=w, count=1, dtype="float64", crs=crs, transform=transform, nodata=float("nan"))
        out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(out, 1)
        with rasterio.open(out_path) as _src_preview:
            note = _raster_preview_op(_src_preview, out, out_name, "代价距离面（累积代价）")
        fin = out[np.isfinite(out)]
        return (f"代价距离完成（8 邻域 Dijkstra）：可达 {reachable} 像元，不可达 {unreachable} 像元，"
                f"代价范围 {fin.min():.3f}~{fin.max():.3f}（单位=代价栅格值·米）。"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"代价距离计算失败: {str(e)[:300]}"


@tool
def least_cost_path(cost_layer: str, source_layer: str, destination_layer: str) -> str:
    """最小代价路径：在代价栅格上求源到目的地的最小累积代价路径（与 cost_distance 共用同一图与算法）。
    - cost_layer: 代价栅格（GeoTIFF）。
    - source_layer / destination_layer: 源/目的地点图层。
    输出路径线图层（含累积代价属性），并报告总代价与路径长度。累计代价按实际地面距离（米）计算。"""
    try:
        import numpy as np
        import rasterio
        from scipy.sparse.csgraph import dijkstra
        from rasterio.features import rasterize as rio_rasterize
        from shapely.geometry import LineString, Point
        import geopandas as gpd
        tif_path = _find_uploaded_tif(cost_layer)
        if tif_path is None:
            return f"错误：未找到代价栅格「{cost_layer}」，请先上传 GeoTIFF"
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return f"错误：代价栅格「{cost_layer}」缺少 CRS，无法可靠对齐源/目的地图层"
            if src.width * src.height > 1_000_000:
                return "最小代价路径失败：栅格超过单次处理上限（100 万像元）；请先裁剪或重采样"
            cost = src.read(1, masked=True).astype("float64").filled(np.nan)
            transform = src.transform
            crs = src.crs
            nodata = src.nodata
        valid0 = np.isfinite(cost)
        if nodata is not None:
            valid0 &= cost != nodata
        cost = np.where(valid0, cost, np.nan)
        h, w = cost.shape
        graph, idx, valid = _cost_graph(cost, transform=transform, crs=crs)
        gdf_s, sname = _layer_to_gdf(source_layer)
        if gdf_s is None: return sname
        gdf_d, dname = _layer_to_gdf(destination_layer)
        if gdf_d is None: return dname
        gdf_s = gdf_s.to_crs(crs)
        gdf_d = gdf_d.to_crs(crs)
        def snap(g):
            pts = g.geometry.centroid
            rows = []
            inv = ~transform
            for pt in pts:
                col, row = inv * (pt.x, pt.y)
                r, c = math.floor(row), math.floor(col)
                if 0 <= r < h and 0 <= c < w and idx[r, c] >= 0:
                    rows.append(idx[r, c])
            return rows
        s_nodes = snap(gdf_s); d_nodes = snap(gdf_d)
        if not s_nodes or not d_nodes:
            return f"错误：源或目的地未能吸附到有效像元（源 {len(s_nodes)} 个，目的地 {len(d_nodes)} 个），请检查位置是否在栅格有效区内"
        if len(s_nodes) * int(valid.sum()) > 4_000_000:
            return "最小代价路径失败：源点数量与有效像元规模过大；请减少源点或裁剪/重采样栅格"
        dist_mat, preds = dijkstra(graph, directed=False, indices=s_nodes, return_predecessors=True)
        lines = []; costs = []
        for di, dn in enumerate(d_nodes):
            best_si = int(np.argmin(dist_mat[:, dn])) if np.isfinite(dist_mat[:, dn]).any() else -1
            if best_si < 0 or not np.isfinite(dist_mat[best_si, dn]):
                continue
            total = float(dist_mat[best_si, dn])
            path_nodes = [dn]
            cur = dn
            while cur != best_si and cur >= 0:
                cur = preds[best_si, cur]
                if cur < 0: break
                path_nodes.append(int(cur))
            
            coords_rc = []
            for n in path_nodes:
                r, c = divmod(int(n), w)
                coords_rc.append((r, c))
            xs = []; ys = []
            inv_t = ~transform
            for r, c in coords_rc:
                x, y = transform * (c + 0.5, r + 0.5)
                xs.append(x); ys.append(y)
            if len(xs) >= 2:
                lines.append(LineString(zip(xs, ys))); costs.append(total)
        if not lines:
            return "错误：源与目的地之间不存在可达路径（被 nodata/非正值阻断）"
        gdf = gpd.GeoDataFrame({"total_cost": costs}, geometry=lines, crs=crs)
        out_name = f"{sname}_到_{dname}_代价路径"
        _gdf_to_layer(gdf, out_name)
        from pyproj import CRS
        raster_crs = CRS.from_user_input(crs)
        if raster_crs.is_geographic:
            length_m = sum(raster_crs.get_geod().geometry_length(line) for line in lines)
            length_method = "椭球测地线"
        else:
            unit_to_meters = raster_crs.axis_info[0].unit_conversion_factor
            length_m = sum(line.length for line in lines) * unit_to_meters
            length_method = "栅格投影单位换算"
        len_km = length_m / 1000.0
        return (f"最小代价路径完成（与 cost_distance 共用 8 邻域图）：{len(lines)} 条路径，"
                f"总代价 {min(costs):.3f}~{max(costs):.3f}，路径总长 {len_km:.2f} km（{length_method}）。"
                f"图层「{out_name}」已加载到地图")
    except Exception as e:
        return f"最小代价路径计算失败: {str(e)[:300]}"


__all__ = [
    "download_road_network",
    "network_analysis",
    "od_cost_matrix",
    "metro_line",
    "cost_distance",
    "least_cost_path",
    "_format_extent",
    "_point_in_bbox",
    "_find_layer_for_coord",
    "_parse_coord",
    "_cost_graph",
    "_find_uploaded_tif",
    "_raster_output_dir",
    "_raster_preview_op",
    "record_tool_artifact",
]
