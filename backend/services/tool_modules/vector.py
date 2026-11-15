# -*- coding: utf-8 -*-
"""
backend.services.tool_modules.vector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Vector GIS operations, spatial analysis routines, geometric algorithms,
and spatial statistics.

Strict architectural constraints:
- Depends ONLY on runtime.py, common.py, standard libraries, and GIS libraries.
- NEVER imports backend.services.tools or tools (zero circular imports).
"""

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
from shapely.geometry import Point, LineString, Polygon, box, mapping, shape
from shapely.ops import unary_union
from langchain.tools import tool

from backend.services.task_manager import register_artifact
from backend.services.tool_args_guard import validate_tool_args
from backend.services.tool_modules.runtime import (
    _registered_layers,
    _pending_layers,
    _pending_layer_ops,
    _state_lock,
    get_temp_output_dir,
    _layer_to_gdf,
    _gdf_to_layer,
    _push_layer,
    _get_exact_registered_layer,
    _update_registered_layer_data,
    geojson_to_export_gdf as _geojson_to_export_gdf,
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


def _get_utm_crs(lon: float, lat: float) -> str:
    """根据经纬度计算标准 UTM 投影坐标系，带号严格约束在 1~60 之间。"""
    utm_zone = int((lon + 180) / 6) + 1
    utm_zone = max(1, min(60, utm_zone))
    return f"EPSG:{32600 + utm_zone}" if lat >= 0 else f"EPSG:{32700 + utm_zone}"


def _local_utm_extent_error(bounds) -> str | None:
    if not all(math.isfinite(float(value)) for value in bounds):
        return "输入坐标包含非有限值，无法执行局部 UTM 分析"
    if bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90:
        return "输入坐标超出 WGS84 经纬度范围（经度 -180°–180°，纬度 -90°–90°）"
    if bounds[2] - bounds[0] > 180:
        return "输入范围跨越日期变更线，单一局部 UTM 投影不适用"
    if bounds[2] - bounds[0] > 6:
        return "输入范围超过 6° 经度，单一局部 UTM 投影不适用，请按区域分区处理"
    if bounds[1] < -80 or bounds[3] > 84:
        return "输入范围超出 UTM 投影适用纬度（80°S–84°N）"
    return None


def _to_local_metric_gdf(gdf):
    """把局部地理数据转到覆盖范围对应的 UTM 米制坐标系。"""
    extent_error = _local_utm_extent_error(gdf.total_bounds)
    if extent_error:
        raise ValueError(extent_error)
    crs = gdf.estimate_utm_crs()
    if crs is None:
        raise ValueError("无法为当前图层范围确定合适的米制投影")
    return gdf.to_crs(crs)


def _spatial_feature_coordinates(gdf):
    """为每个点要素返回一个坐标，避免 MultiPoint 顶点数与属性行数不一致。"""
    geometry = gdf.geometry
    if geometry.isna().any() or geometry.is_empty.any():
        raise ValueError("图层含空几何，请先清理")
    if not geometry.geom_type.isin(["Point", "MultiPoint"]).all():
        raise ValueError("该分析只支持点图层；线/面请先执行 spatial_centroid 取质心")
    if geometry.geom_type.eq("Point").all():
        return geometry.get_coordinates().values
    return geometry.centroid.get_coordinates().values


def _gdf_area_km2(gdf, unique=False):
    """计算 GeoDataFrame 的总面积（平方千米）。
    输入为 EPSG:4326 经纬度时，转到 EPSG:6933 全球等面积投影再求和，
    避免把经纬度 degree² 直接当平方米。unique=True 时统计去重覆盖面积，
    防止叠置产物的重叠记录重复计入覆盖比例。失败时返回 None。"""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            crs = getattr(gdf, "crs", None)
            if crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            ea = gdf.to_crs("EPSG:6933")
            if unique:
                merged = ea.geometry.union_all() if hasattr(ea.geometry, 'union_all') else ea.geometry.unary_union
                return float(merged.area) / 1e6
            return float(ea.geometry.area.sum()) / 1e6
    except Exception:
        return None


def _stats_metric_gdf(gdf):
    """把图层投影到本地 UTM 米制坐标系，用于距离/面积/协方差计算。"""
    b = gdf.total_bounds
    lon, lat = (float(b[0]) + float(b[2])) / 2.0, (float(b[1]) + float(b[3])) / 2.0
    crs = _get_utm_crs(lon, lat)
    return gdf.to_crs(crs), crs


def _stats_coords_weights(gdf_metric, weight_field: str = ""):
    """取要素代表点坐标 (N,2) 与可选权重 (N,)。非点要素取 representative_point（保证落在几何内部）。"""
    import numpy as np
    geom = gdf_metric.geometry
    try:
        pts = geom.representative_point()
    except Exception:
        pts = geom
    coords = np.array([[float(p.x), float(p.y)] for p in pts], dtype=float)
    weights = None
    if weight_field:
        if weight_field not in gdf_metric.columns:
            raise ValueError(f"权重字段「{weight_field}」不存在")
        weights = np.asarray(gdf_metric[weight_field].values, dtype=float)
        if not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() <= 0:
            raise ValueError(f"权重字段「{weight_field}」必须为有限非负数且总和大于 0")
    return coords, weights


def _geometric_median(coords, weights, tol: float = 1e-6, max_iter: int = 1000):
    """用修正 Weiszfeld 迭代求加权几何中位数，坐标单位与输入一致。"""
    import numpy as np

    points = np.asarray(coords, dtype=float)
    weight = np.ones(len(points), dtype=float) if weights is None else np.asarray(weights, dtype=float)
    estimate = np.average(points, axis=0, weights=weight)
    for _ in range(max_iter):
        delta = points - estimate
        distances = np.linalg.norm(delta, axis=1)
        coincident = distances <= 1e-9
        eta = float(weight[coincident].sum())
        other = ~coincident
        if not other.any():
            return estimate
        residual = (weight[other, None] * delta[other] / distances[other, None]).sum(axis=0)
        residual_norm = float(np.linalg.norm(residual))
        if residual_norm <= eta:
            return estimate
        scaled = weight[other] / distances[other]
        candidate = (scaled[:, None] * points[other]).sum(axis=0) / float(scaled.sum())
        ratio = min(1.0, eta / residual_norm) if eta else 0.0
        updated = (1.0 - ratio) * candidate + ratio * estimate
        if float(np.linalg.norm(updated - estimate)) <= tol:
            return updated
        estimate = updated
    return estimate


def _is_contiguous(g1, g2, method: str) -> bool:
    """面邻接判定：queen=共享边或顶点(touches)；rook=仅共享边(交集为线且长度>0)。"""
    if g1 is None or g2 is None:
        return False
    try:
        if not g1.touches(g2):
            return False
        if method == "rook":
            inter = g1.intersection(g2)
            return (not inter.is_empty) and float(inter.length) > 0.0
        return True
    except Exception:
        return False


def _contiguity_pairs(geoms, method: str):
    """用 STRtree 预筛候选对再精确判定；无 STRtree 时退化为 O(n^2)。"""
    n = len(geoms)
    pairs = []
    try:
        from shapely import STRtree
        tree = STRtree(geoms)
        for i in range(n):
            for j in tree.query(geoms[i]):
                j = int(j)
                if j <= i:
                    continue
                if _is_contiguous(geoms[i], geoms[j], method):
                    pairs.append((i, j))
    except Exception:
        for i in range(n):
            for j in range(i + 1, n):
                if _is_contiguous(geoms[i], geoms[j], method):
                    pairs.append((i, j))
    return pairs


def _build_spatial_weights(gdf, method: str = "queen", k: int = 8):
    """统一的邻接/权重构建入口（spatial_weights_matrix 与 spatial_regression 复用）。

    返回 (W csr 稀疏矩阵, neighbors 列表, backend 说明)。
    - queen / rook: 优先 libpysal（惰性导入，不在 requirements.txt），
      不可用时用 shapely touches/intersects 的纯 numpy/scipy 实现。
    - knn: cKDTree 质心近邻。
    """
    import numpy as np
    from scipy import sparse

    n = len(gdf)
    if n < 2:
        raise ValueError(f"要素数（{n}）太少，至少需要 2 个")
    method = str(method).lower().strip()
    neighbors = [[] for _ in range(n)]
    backend = "numpy/scipy"

    if method in ("queen", "rook"):
        libpysal_w = None
        try:
            from libpysal.weights import Queen, Rook
            libpysal_w = (Queen if method == "queen" else Rook).from_dataframe(gdf, use_index=False)
        except Exception:
            libpysal_w = None
        if libpysal_w is not None:
            try:
                for i in range(n):
                    neighbors[i] = sorted(int(j) for j in libpysal_w.neighbors.get(i, []) if int(j) != i)
                backend = "libpysal"
            except Exception:
                libpysal_w = None
        if libpysal_w is None:
            geoms = list(gdf.geometry)
            _types = {str(t) for t in gdf.geometry.geom_type.dropna().unique()}
            if not _types or not _types.issubset({"Polygon", "MultiPolygon"}):
                raise ValueError(
                    f"{method} 邻接需要面图层，而当前是 {'/'.join(sorted(_types)) or '未知'}；点图层请改用 method='knn'")
            for i, j in _contiguity_pairs(geoms, method):
                neighbors[i].append(j)
                neighbors[j].append(i)
            for i in range(n):
                neighbors[i] = sorted(neighbors[i])
    elif method == "knn":
        # cKDTree 用欧氏距离：绝不能直接吃经纬度（1 度经差  1 度纬差），
        # 先投影到本地 UTM 米制坐标再建树，这样 knn 才是真正的"最近邻"。
        gdf_metric, _ = _stats_metric_gdf(gdf)
        coords = np.array([[float(p.x), float(p.y)] for p in gdf_metric.geometry.representative_point()], dtype=float)
        from scipy.spatial import cKDTree
        k_eff = max(1, min(int(k), n - 1))
        tree = cKDTree(coords)
        _, idx = tree.query(coords, k=k_eff + 1)
        for i in range(n):
            neighbors[i] = sorted(int(j) for j in np.atleast_1d(idx[i])[1:] if int(j) != i)
    else:
        raise ValueError("method 仅支持 queen / rook / knn")

    rows, cols, data = [], [], []
    for i, nbrs in enumerate(neighbors):
        for j in nbrs:
            rows.append(i)
            cols.append(j)
            data.append(1.0)
    W = sparse.csr_matrix((data, (rows, cols)), shape=(n, n))
    return W, neighbors, backend


def _moran_from_weights(W, x):
    """给定权重矩阵与数值向量计算全局 Moran's I 及随机化假设下的 z/p（与 spatial_moran 同口径）。"""
    import numpy as np
    from scipy.stats import norm
    x = np.asarray(x, dtype=float)
    n = len(x)
    z = x - x.mean()
    zz = float(z @ z)
    S0 = float(W.sum())
    if n < 3 or zz <= 0 or S0 <= 0:
        return None
    I = (n / S0) * float(z @ (W @ z)) / zz
    E_I = -1.0 / (n - 1)
    z_score, p_value, method = 0.0, 1.0, "置换检验"
    denom = (n - 1) * (n - 2) * (n - 3) * S0 * S0
    if n > 3 and denom > 0:
        m2 = float((z ** 2).mean())
        if m2 > 0:
            S1 = 0.5 * float(((W + W.T) ** 2).sum())
            S2 = float(((W.sum(axis=1) + W.sum(axis=0)) ** 2).sum())
            b2 = float((z ** 4).mean()) / (m2 ** 2)
            k1 = n * (S1 * (n * n - 3 * n + 3) - n * S2 + 3 * S0 * S0) / denom
            k2 = (S1 * (n * n - n) - 2 * n * S2 + 6 * S0 * S0) / denom
            var_I = k1 - k2 * b2 - E_I * E_I
            if var_I > 0:
                z_score = (I - E_I) / np.sqrt(var_I)
                p_value = 2.0 * (1.0 - norm.cdf(abs(z_score)))
                method = "正态近似"
    if method != "正态近似":
        rng = np.random.default_rng(20240915)
        perm = []
        for _ in range(99):
            xp = rng.permutation(x)
            zp = xp - xp.mean()
            zzp = float(zp @ zp)
            if zzp > 0:
                perm.append((n / S0) * float(zp @ (W @ zp)) / zzp)
        perm = np.asarray(perm)
        if perm.size and perm.std() > 0:
            z_score = (I - perm.mean()) / perm.std()
            p_value = (1 + int((np.abs(perm - perm.mean()) >= abs(I - perm.mean())).sum())) / (perm.size + 1)
    return I, z_score, p_value, method


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


def _parse_numeric_condition(value, dtype_kind):
    text = str(value).strip()
    if dtype_kind in ("i", "u") and re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    return float(text)


@tool
def measure_area(layer_name: str) -> str:
    """测量指定图层面积：局部范围使用 UTM，大范围/跨带范围使用 WGS-84 椭球面积，支持多要素汇总。

【精度保障】
- 内部自动投影到 UTM 投影坐标系，WGS84 数据可直接使用。
- 返回平方公里（km2）、平方米（m2）、亩。

【常见坑】
- execute_python 中自定义面积计算必须先 to_crs 到投影坐标系，否则单位是平方度。
- 面图层有重叠时总面积重复计算，先用 topology_check 或 spatial_dissolve。
- 几何无效（自相交）会导致面积异常，先修复。"""
    try:
        info = _registered_layers.get(layer_name)
        if not info:
            matches = [n for n in _registered_layers.keys() if layer_name in n]
            if len(matches) == 1:
                info = _registered_layers[matches[0]]
                layer_name = matches[0]
            elif len(matches) > 1:
                return f"找到多个匹配：{', '.join(matches)}，请指定完整名称"
            else:
                return f"未找到图层「{layer_name}」，当前图层：{', '.join(_registered_layers.keys()) or '无'}"

        import geopandas as gpd
        import numpy as np

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层 {layer_name} 为空"

        # 计算几何中心，选择最佳 UTM 投影带
        # 用 bounds 中心确定 UTM 带号（避免在 geographic CRS 下计算 centroid 的 warning）
        _b = gdf.total_bounds
        lon, lat = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2

        min_zone = max(1, min(60, int(np.floor((_b[0] + 180) / 6)) + 1))
        max_zone = max(1, min(60, int(np.floor((_b[2] + 180) / 6)) + 1))
        use_geodesic_area = (
            (_b[2] - _b[0]) > 6.0 or (_b[3] - _b[1]) > 6.0
            or min_zone != max_zone or _b[1] < -80.0 or _b[3] > 84.0
        )
        cross_check = ""
        if use_geodesic_area:
            from pyproj import Geod
            geod = Geod(ellps="WGS84")

            def _geodesic_geometry_area(geometry):
                if geometry is None or geometry.is_empty:
                    return 0.0
                if geometry.geom_type == "Polygon":
                    def ring_area(ring):
                        coordinates = list(ring.coords)
                        return abs(geod.polygon_area_perimeter(
                            [point[0] for point in coordinates],
                            [point[1] for point in coordinates],
                        )[0])
                    return max(0.0, ring_area(geometry.exterior) - sum(
                        ring_area(ring) for ring in geometry.interiors
                    ))
                if geometry.geom_type in ("MultiPolygon", "GeometryCollection"):
                    return sum(_geodesic_geometry_area(part) for part in geometry.geoms)
                return 0.0

            area_m2 = sum(_geodesic_geometry_area(geometry) for geometry in gdf.geometry)
            area_method = "WGS-84 椭球大地面积（大范围/跨 UTM 带）"
        else:
            # UTM 带号：zone = floor((lon + 180) / 6) + 1，严格限制在 1~60
            utm_zone = int(np.floor((lon + 180) / 6)) + 1
            utm_zone = max(1, min(60, utm_zone))
            # 北/南半球 EPSG 编号
            if lat >= 0:
                epsg_code = 32600 + utm_zone  # 32601~32660
                hemi = "北"
            else:
                epsg_code = 32700 + utm_zone  # 32701~32760
                hemi = "南"

            # 投影到 UTM 并计算面积（平方米）
            gdf_proj = gdf.to_crs(f"EPSG:{epsg_code}")
            area_m2 = gdf_proj.geometry.area.sum()
            area_method = f"UTM {utm_zone}{hemi}（EPSG:{epsg_code}）"

            # 同时用 Albers Equal Area（Krasovsky 1940 Albers）做交叉验证，用于提醒
            try:
                # 自定义 Albers Equal Area 投影参数（适合中国中低纬度）
                albers_crs = (
                    f"+proj=aea +lat_1={max(lat - 2, 0)} +lat_2={min(lat + 2, 50)} "
                    f"+lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 "
                    "+ellps=WGS84 +datum=WGS84 +units=m +no_defs"
                )
                gdf_albers = gdf.to_crs(albers_crs)
                area_m2_albers = gdf_albers.geometry.area.sum()
                area_km2_albers = area_m2_albers / 1_000_000
                cross_check = f"（Albers 等面积交叉验证：{area_km2_albers:.2f} km²）"
            except Exception:
                cross_check = ""
        area_km2 = area_m2 / 1_000_000

        feat_count = len(gdf)
        geom_types = gdf.geometry.type.unique().tolist()

        result = (
            f"图层「{layer_name}」面积测量结果：\n"
            f"- 面积：{area_km2:.2f} 平方公里\n"
            f"- 面积方法：{area_method}"
        )
        if cross_check:
            result += f"\n- 交叉验证：{cross_check}"
        result += (
            f"\n- 几何类型：{', '.join(geom_types)}"
            f"\n- 要素数：{feat_count}"
            f"\n- 中心点：{lat:.4f}°, {lon:.4f}°"
            f"\n- 坐标系：WGS-84"
        )

        return result

    except Exception as e:
        import traceback
        return f"面积测量失败: {str(e)}\n{traceback.format_exc()}"



@tool
def measure_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> str:
    """测量两个经纬度坐标之间的地面距离。使用 Haversine 公式计算大圆距离。
    lon1/lat1: 起点经纬度；lon2/lat2: 终点经纬度。
    WGS84 坐标系。返回米和公里。"""
    try:
        import math
        lon1, lat1, lon2, lat2 = map(float, (lon1, lat1, lon2, lat2))
        if not all(math.isfinite(value) for value in (lon1, lat1, lon2, lat2)):
            return "输入坐标必须是有限数值，范围为经度 -180～180、纬度 -90～90"
        if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180
                and -90 <= lat1 <= 90 and -90 <= lat2 <= 90):
            return "输入坐标超出 WGS-84 范围：经度 -180～180、纬度 -90～90"
        R = 6371000  # 地球半径（米）
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance_m = R * c

        if distance_m < 1000:
            return f"距离：{distance_m:.1f} 米"
        else:
            return f"距离：{distance_m / 1000:.2f} 公里（{distance_m:.1f} 米）"
    except Exception as e:
        return f"距离测量失败: {str(e)[:200]}"


@tool
def convert_crs(layer_name: str, target_crs: str = "wgs84") -> str:
    """转换矢量图层的坐标参考系并生成新图层（原图层保留）。
    - layer_name: 待转换图层名。
    - target_crs: 目标坐标系，可选 'wgs84'(EPSG:4326)、'web_mercator'(EPSG:3857)、'utm_auto'(自动UTM投影带) 或 'EPSG:xxxx'。进行长度/面积精确度量前需转为投影坐标系。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        epsg_map = {
            "wgs84": "EPSG:4326",
            "web_mercator": "EPSG:3857",
            "mercator": "EPSG:3857",
            "gcj02": "EPSG:4326",  # 本系统全面使用WGS84，GCJ02暂不做偏移转换
        }
        target_key = target_crs.strip().lower()
        target = epsg_map.get(target_key, target_crs.strip())
        if target_key not in ("utm_auto", "utm"):
            import pyproj
            target_definition = pyproj.CRS.from_user_input(target)
            if target_definition.to_epsg() == 3857 and target_definition.area_of_use:
                min_lon, min_lat, max_lon, max_lat = target_definition.area_of_use.bounds
                min_x, min_y, max_x, max_y = gdf.total_bounds
                if min_x < min_lon or min_y < min_lat or max_x > max_lon or max_y > max_lat:
                    return (
                        f"坐标系转换失败: 图层范围超出 {target} 适用范围 "
                        f"（经度 {min_lon}°–{max_lon}°，纬度 {min_lat}°–{max_lat}°），"
                        "未生成新图层"
                    )
        if target_key in ("utm_auto", "utm"):
            extent_error = _local_utm_extent_error(gdf.total_bounds)
            if extent_error:
                return f"坐标系转换失败: {extent_error}"
            bounds = gdf.total_bounds
            center_lon = (bounds[0] + bounds[2]) / 2
            center_lat = (bounds[1] + bounds[3]) / 2
            target = _get_utm_crs(center_lon, center_lat)
        if gdf.crs and gdf.crs.to_string() == target:
            return f"图层 '{name}' 已经是 {target_crs} 坐标系"
        if not gdf.crs and target == "EPSG:4326":
            return f"图层 '{name}' 已经是 WGS84 坐标系"
        gdf_proj = gdf.to_crs(target)
        if gdf_proj is None or gdf_proj.empty:
            return f"坐标系转换失败: {target}"
        out_name = f"{name}_{target_crs}"
        _gdf_to_layer(gdf_proj, out_name)
        return f"已将图层 '{name}' 转换为 {target_crs}({target})，生成新图层 '{out_name}'"
    except Exception as e:
        return f"坐标系转换失败: {str(e)[:200]}"



@tool
def convert_coordinates(coords: str, source_crs: str = "wgs84",
                         target_crs: str = "web_mercator") -> str:
    """转换单个坐标点在两个坐标参考系之间。
    coords格式: "lng,lat" 或 "lng1,lat1;lng2,lat2" 批处理。
    source_crs/target_crs支持: wgs84, web_mercator, utm_auto。
    返回转换后的坐标对。"""
    try:
        import math
        import pyproj

        def _resolve_crs(name: str) -> str:
            """CRS 别名 → EPSG；源 UTM 必须提供明确分带。"""
            n = str(name).lower().strip()
            m = {"wgs84": "EPSG:4326", "mercator": "EPSG:3857",
                 "web_mercator": "EPSG:3857", "gcj02": "EPSG:4326"}
            if n in m:
                return m[n]
            if n in ("utm_auto", "utm"):
                raise ValueError("源坐标为 UTM 时需指定 EPSG 分带（例如 EPSG:32719），不能使用 utm_auto")
            return str(name).strip()

        def _validate_web_mercator_area(points, input_crs: str, role: str) -> None:
            area = pyproj.CRS.from_epsg(3857).area_of_use
            west, south, east, north = area.bounds
            to_wgs84 = pyproj.Transformer.from_crs(input_crs, "EPSG:4326", always_xy=True)
            for x, y in points:
                lon, lat = to_wgs84.transform(x, y, errcheck=True)
                if (
                    not math.isfinite(lon) or not math.isfinite(lat)
                    or not west <= lon <= east or not south <= lat <= north
                ):
                    raise ValueError(
                        f"{role}超出 EPSG:3857 适用范围 "
                        f"（经度 {west}°–{east}°，纬度 {south}°–{north}°）"
                    )

        parts_raw = str(coords or "").replace("，", ",").replace("；", ";").split(";")
        parsed = []
        for part in parts_raw:
            xy = part.strip().split(",")
            if len(xy) != 2:
                raise ValueError("坐标格式错误，请输入 lng,lat 或 lng1,lat1;lng2,lat2")
            try:
                x, y = float(xy[0].strip()), float(xy[1].strip())
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("坐标格式错误，请输入有效数字坐标") from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("坐标必须是有限数值")
            parsed.append((x, y))

        p1 = _resolve_crs(source_crs)
        source_definition = pyproj.CRS.from_user_input(p1)
        if source_definition.to_epsg() == 3857:
            _validate_web_mercator_area(parsed, p1, "源坐标")
        if source_definition.is_geographic and any(
            not -180 <= x <= 180 or not -90 <= y <= 90 for x, y in parsed
        ):
            raise ValueError("源坐标超出有效经纬度范围（经度 -180°–180°，纬度 -90°–90°）")
        target_key = str(target_crs).lower().strip()
        if target_key in ("utm_auto", "utm"):
            to_wgs84 = pyproj.Transformer.from_crs(p1, "EPSG:4326", always_xy=True)
            geographic = [to_wgs84.transform(x, y, errcheck=True) for x, y in parsed]
            if any(not math.isfinite(lon) or not math.isfinite(lat)
                   or not -180 <= lon <= 180 or not -90 <= lat <= 90
                   for lon, lat in geographic):
                raise ValueError("坐标转换后超出 WGS84 经纬度有效范围")
            bounds = (
                min(point[0] for point in geographic), min(point[1] for point in geographic),
                max(point[0] for point in geographic), max(point[1] for point in geographic),
            )
            extent_error = _local_utm_extent_error(bounds)
            if extent_error:
                raise ValueError(extent_error)
            center_lon = (bounds[0] + bounds[2]) / 2
            center_lat = (bounds[1] + bounds[3]) / 2
            p2 = _get_utm_crs(center_lon, center_lat)
        else:
            p2 = _resolve_crs(target_crs)
        target_definition = pyproj.CRS.from_user_input(p2)
        if target_definition.to_epsg() == 3857 and source_definition.to_epsg() != 3857:
            _validate_web_mercator_area(parsed, p1, "目标范围")
        if p1 == p2:
            return f"源和目标CRS相同: {source_crs} = {target_crs}, 无需转换"
        transformer = pyproj.Transformer.from_crs(p1, p2, always_xy=True)
        target_is_geographic = pyproj.CRS.from_user_input(p2).is_geographic
        results = []
        for x, y in parsed:
            x2, y2 = transformer.transform(x, y, errcheck=True)
            if not math.isfinite(x2) or not math.isfinite(y2):
                raise ValueError("转换结果包含非有限坐标")
            if target_is_geographic and (not -180 <= x2 <= 180 or not -90 <= y2 <= 90):
                raise ValueError("目标经纬度超出有效范围")
            results.append(f"{x2:.6f},{y2:.6f}")
        return f"{source_crs}→{target_crs}: {'; '.join(results)}"
    except Exception as e:
        return f"坐标转换失败: {str(e)[:200]}"



@tool
def add_length_field(layer_name: str, field_name: str = "length_km") -> str:
    """为线/面图层添加长度字段：每个要素的几何长度（千米，UTM 精确投影计算），
    结果作为新图层上图。面积量测用 measure_area，本工具补逐要素长度统计。"""
    gdf, name = _layer_to_gdf(layer_name)
    if gdf is None:
        return name
    try:
        utm = gdf.estimate_utm_crs()
        if utm is None:
            return "无法估算 UTM 投影带（图层范围异常）"
        projected = gdf.to_crs(utm)
        lengths_km = projected.geometry.length / 1000.0
        out = gdf.copy()
        out[field_name] = [round(float(v), 4) for v in lengths_km]
        with _state_lock:
            out_name = _disambiguate_layer_name(f"{name}_带长度")
            _gdf_to_layer(out, out_name)
        return (f"已添加字段「{field_name}」（单位 km，UTM {utm.to_string()} 计算）："
                f"总长 {lengths_km.sum():.2f} km，最长 {lengths_km.max():.2f} km，"
                f"结果图层「{out_name}」已上图")
    except Exception as e:
        return f"添加长度字段失败: {str(e)[:300]}"



@tool
def add_labels(layer_name: str, field: str, font_size: int = 12, color: str = "#333333") -> str:
    """对图层添加属性标注，每个要素上显示指定字段的文本标签，类似于 ArcGIS 的"标注要素"功能。
    layer_name: 图层名；field: 用于标注的字段名；font_size: 字体大小（6-72，默认12）；color: CSS 字体颜色（默认"#333333"）。"""
    try:
        import math
        try:
            requested_size = float(font_size)
        except (TypeError, ValueError, OverflowError):
            return "标注失败：font_size 必须是 6 到 72 之间的整数"
        if not math.isfinite(requested_size) or not requested_size.is_integer() or not 6 <= requested_size <= 72:
            return "标注失败：font_size 必须是 6 到 72 之间的整数"
        font_size = int(requested_size)
        if not isinstance(color, str) or not color.strip() or len(color) > 64:
            return "标注失败：color 必须是非空 CSS 颜色值"
        color = color.strip()
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"错误：图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        _pending_layer_ops.append({
            "action": "labels",
            "name": name,
            "field": field,
            "font_size": font_size,
            "color": color,
        })

        feat_count = len(gdf)
        return (f"已为「{name}」添加标注，字段：{field}，{feat_count} 个要素已显示文字标签")
    except Exception as e:
        return f"标注失败: {str(e)[:200]}"



@tool
def add_legend(layer_name: str) -> str:
    """显示图层的图例。图例根据图层的符号化配置（分级色彩或唯一值渲染）自动生成。
    layer_name: 图层名。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        _pending_layer_ops.append({
            "action": "legend",
            "name": name,
        })

        return (f"已为「{name}」生成图例")
    except Exception as e:
        return f"图例生成失败: {str(e)[:200]}"



@tool
def draw_feature(geometry_type: str, coordinates: str, layer_name: str = "") -> str:
    """根据坐标创建点/线/面几何图层并加载到地图。
    - geometry_type: Point / LineString / Polygon / Rectangle / Circle。
    - coordinates: Point("lon,lat")；LineString("lon1,lat1;lon2,lat2;...")；Polygon("lon1,lat1;...;lon1,lat1"闭合)；
      Rectangle("lon1,lat1;lon2,lat2"对角线)；Circle("lon,lat;radius_m"圆心+半径米)。
    - layer_name: 自定义图层名（空则自动命名）。"""
    try:
        import geopandas as gpd
        from shapely.geometry import Point, LineString, Polygon
        import json, re, math

        gt = geometry_type.strip().lower()
        norm_map = {"point": "Point", "linestring": "LineString", "polygon": "Polygon",
                    "rectangle": "Rectangle", "circle": "Circle"}
        if gt in norm_map:
            gt = norm_map[gt]
        else:
            return f"不支持的几何类型：{geometry_type}，请用 Point / LineString / Polygon / Rectangle / Circle"

        # 解析坐标
        parts = [p.strip() for p in coordinates.replace("，", ",").replace("；", ";").split(";") if p.strip()]
        if not parts:
            return "未提供有效坐标"

        def parse_xy(s):
            s = s.replace("，", ",")
            xy = [x.strip() for x in s.split(",") if x.strip()]
            if len(xy) != 2:
                return None
            try:
                x, y = float(xy[0]), float(xy[1])
                if not math.isfinite(x) or not math.isfinite(y):
                    return None
                if not (-180 <= x <= 180 and -90 <= y <= 90):
                    return None
                return (x, y)
            except (ValueError, TypeError, OverflowError):
                return None

        pts = [parse_xy(p) for p in parts]
        pts = [p for p in pts if p is not None]

        if gt == "Point":
            if not pts:
                return "无法解析坐标，请使用「lon,lat」格式（经度 -180~180，纬度 -90~90）"
            geom = Point(pts[0])
            node_count = 1
        elif gt == "LineString":
            if len(pts) < 2:
                return "无法解析坐标，LineString 至少需要 2 个有效点"
            geom = LineString(pts)
            node_count = len(pts)
        elif gt == "Polygon":
            if len(pts) < 3:
                return "无法解析坐标，Polygon 至少需要 3 个有效点"
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            geom = Polygon(pts)
            node_count = len(pts)
        elif gt == "Rectangle":
            if len(pts) != 2:
                return "Rectangle 需要 2 个有效坐标（对角线）：lon1,lat1;lon2,lat2"
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)
            if minx == maxx or miny == maxy:
                return "Rectangle 对角线两点不能在同一经度或同一纬度上"
            geom = Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)])
            node_count = 4
        else:  # Circle
            if len(pts) < 1 or len(parts) < 2:
                return "Circle 需要圆心坐标和半径：lon,lat;radius_m"
            try:
                radius = float(parts[1])
            except (ValueError, TypeError, OverflowError):
                return "Circle 半径必须是有限数值"
            if not math.isfinite(radius) or radius <= 0:
                return "Circle 半径必须大于 0"
            if radius > 50_000_000:
                return "Circle 半径超出合理地理范围"
            lon, lat = pts[0]
            if lat < -80 or lat > 84:
                return "Circle 圆心纬度必须在 UTM 投影适用范围（80°S 至 84°N）内"
            center_pt = Point(pts[0])
            crs_utm = _get_utm_crs(lon, lat)
            center_gdf = gpd.GeoDataFrame({"geometry": [center_pt]}, crs="EPSG:4326")
            center_utm = center_gdf.to_crs(crs_utm)
            circle_utm = center_utm.geometry.buffer(radius)
            circle_gdf = gpd.GeoDataFrame({"geometry": circle_utm}, crs=crs_utm).to_crs("EPSG:4326")
            geom = circle_gdf.geometry.iloc[0]
            node_count = len(geom.exterior.coords) if hasattr(geom, 'exterior') else 0

        base_name = layer_name.strip() or f"绘制_{gt}_{len(_registered_layers) + 1}"
        with _state_lock:
            name = _disambiguate_layer_name(base_name)
            gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")
            provenance = {"tool": "draw_feature", "geometry_type": gt}
            _gdf_to_layer(gdf, name, provenance=provenance)
        pts_str = f"，含 {node_count} 个节点" if node_count else ""
        return f"已创建{gt}图层「{name}」，含 1 个要素{pts_str}，已加载到地图"
    except Exception as e:
        return f"绘制失败: {str(e)[:300]}"



@tool
def edit_vertices(layer_name: str) -> str:
    """对图层要素启用折点拖拽编辑模式。用户可通过鼠标拖拽几何图形的顶点进行编辑。
    layer_name: 图层名。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        _pending_layer_ops.append({
            "action": "edit_vertices",
            "name": name,
        })

        feat_count = len(gdf)
        return (f"已为「{name}」启用折点编辑，{feat_count} 个要素进入编辑模式。拖拽顶点修改后保存即可。")
    except Exception as e:
        return f"启用折点编辑失败: {str(e)[:200]}"



# ============================================================
# 工具: spatial_graduated_colors — 分级色彩渲染
# ============================================================

@tool
def spatial_graduated_colors(layer_name: str, field: str, n_classes: int = 5, color_scheme: str = "blues",
                            method: str = "equal_interval", fill_opacity: float = 0.35) -> str:
    """对图层应用分级色彩渲染（Choropleth），按数值字段将要素分为N个等级，每级用不同颜色显示。
    注意：要求图层包含至少2个要素且数值存在差异。如果是单要素图层（如单个行政区边界），无法分级，请使用 datav_boundary 默认边界在地图展示，并结合指标面板或图表交付。
    layer_name: 图层名；field: 数值字段名；n_classes: 分级数（2-20，默认5）；
    color_scheme: 色带 ylorrd(黄橙红/暖色)/blues(蓝)/reds(红)/greens(绿)/oranges(橙)/purples(紫)/ylgnbu(黄绿蓝)/spectral(光谱)；
    method: 分级方法 equal_interval(等间距，默认) 或 quantile(分位数)；fill_opacity: 面填充透明度（0-1，默认0.35）。"""
    try:
        import geopandas as gpd
        import numpy as np
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        if gdf[field].dtype.kind not in ('i', 'u', 'f'):
            return f"字段「{field}」不是数值类型（{gdf[field].dtype}），分级色彩仅支持数值字段"

        n_classes = max(2, min(20, n_classes if n_classes else 5))
        values = gdf[field].dropna()
        values = values[np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))]
        if values.empty:
            return f"字段「{field}」无有效数值"

        vmin, vmax = float(values.min()), float(values.max())
        if vmin == vmax:
            return f"字段「{field}」所有值相同（{vmin}）或仅有单个要素，无法进行分级设色。单行政区要素已在地图上展示，建议结合指标面板或统计图表交付专题成果。"

        method_names = {
            "equal_interval": "equal_interval", "equal interval": "equal_interval", "等间距": "equal_interval",
            "quantile": "quantile", "分位数": "quantile", "quantiles": "quantile",
        }
        method = method_names.get(str(method or "").strip().lower(), "")
        if not method:
            return "不支持该分级方法，可选：equal_interval（等间距）或 quantile（分位数）"
        n_classes = min(n_classes, int(values.nunique()))
        if n_classes < 2:
            return f"字段「{field}」的不同数值不足，无法分级设色"
        if method == "quantile":
            quantiles = values.quantile([i / n_classes for i in range(n_classes + 1)]).tolist()
            breaks = [float(v) for v in quantiles]
            # 重复值可能使部分等级边界相同；保留真实断点并减少重复等级。
            breaks = sorted(set(breaks))
            if len(breaks) < 3:
                return f"字段「{field}」的数值分布无法形成至少两个分位数等级"
            n_classes = len(breaks) - 1
        else:
            step = (vmax - vmin) / n_classes
            breaks = [vmin + i * step for i in range(n_classes + 1)]
        # Floating-point step accumulation can leave the final break a few
        # ulps below vmax, causing the browser to assign the maximum to no class.
        breaks[0], breaks[-1] = vmin, vmax
        try:
            fill_opacity = max(0.0, min(1.0, float(fill_opacity)))
        except (TypeError, ValueError):
            return "面填充透明度必须是 0 到 1 之间的数值"

        cs_norm = str(color_scheme or "").strip().lower()
        _scheme_map = {
            "ylorrd": "ylorrd", "yellow_orange_red": "ylorrd", "warm": "ylorrd",
            "黄橙红": "ylorrd", "黄到橙到红": "ylorrd", "黄红": "ylorrd", "暖色": "ylorrd",
            "blues": "blues", "蓝": "blues", "蓝色": "blues",
            "reds": "reds", "红": "reds", "红色": "reds",
            "greens": "greens", "绿": "greens", "绿色": "greens",
            "oranges": "oranges", "橙": "oranges", "橙色": "oranges",
            "purples": "purples", "紫": "purples", "紫色": "purples",
            "ylgnbu": "ylgnbu", "黄绿蓝": "ylgnbu",
            "spectral": "spectral", "彩虹": "spectral", "光谱": "spectral",
            "viridis": "viridis", "翠绿": "viridis",
            "scheme": "scheme"
        }
        color_scheme = _scheme_map.get(cs_norm, "blues")

        _pending_layer_ops.append({
            "action": "symbology",
            "name": name,
            "symbology_type": "graduated",
            "field": field,
            "classes": n_classes,
            "scheme": color_scheme,
            "method": method,
            "breaks": breaks,
            "fill_opacity": fill_opacity,
        })

        breaks_str = ", ".join(f"{b:.2f}" for b in breaks)
        method_label = "等间距" if method == "equal_interval" else "分位数"
        return (f"已对「{name}」应用分级色彩渲染，字段：{field}，{n_classes} 级，"
                f"方法：{method_label}，色带：{color_scheme}，填充透明度：{fill_opacity:.2f}，值域：{vmin:.2f} ~ {vmax:.2f}\n"
                f"分界值：{breaks_str}")
    except Exception as e:
        import traceback
        return f"分级色彩渲染失败: {str(e)[:200]}"



@tool
def spatial_unique_values(layer_name: str, field: str, color_scheme: str = "scheme") -> str:
    """对图层应用唯一值渲染，按分类字段每个唯一值分配不同颜色。
    layer_name: 图层名；field: 分类字段（字符串或数值）；
    color_scheme: 色带 scheme(默认)/blues(蓝)/reds(红)/greens(绿)/purples(紫)/oranges(橙)。"""
    try:
        import numpy as np
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        unique_vals = []
        seen_values = set()
        for value in gdf[field].dropna().tolist():
            if isinstance(value, (bool, np.bool_)):
                key = ("boolean", bool(value))
            elif isinstance(value, (int, float, np.number)):
                key = ("number", value.item() if isinstance(value, np.generic) else value)
            else:
                key = (type(value).__name__, value)
            if key not in seen_values:
                seen_values.add(key)
                unique_vals.append(value)
        n_unique = len(unique_vals)
        if n_unique == 0:
            return f"字段「{field}」无有效值"

        if n_unique > 50:
            return (f"字段「{field}」有 {n_unique} 个唯一值（超出最大50），"
                    f"建议改用 spatial_graduated_colors 分级色彩或缩小范围后再试")

        color_scheme = color_scheme if color_scheme in ("scheme","blues","reds","greens","purples","oranges") else "scheme"

        _pending_layer_ops.append({
            "action": "symbology",
            "name": name,
            "symbology_type": "unique",
            "field": field,
            "scheme": color_scheme,
        })

        display_values = []
        display_counts = {}
        for value in unique_vals:
            if isinstance(value, (bool, np.bool_)):
                label, value_type = str(value).lower(), "boolean"
            elif isinstance(value, (int, float, np.number)):
                number = value.item() if isinstance(value, np.generic) else value
                label = str(int(number)) if isinstance(number, float) and number.is_integer() else str(number)
                value_type = "number"
            else:
                label, value_type = str(value), "string"
            display_values.append((label, value_type))
            display_counts[label] = display_counts.get(label, 0) + 1
        vals_str = ", ".join(
            f"{label} ({value_type})" if display_counts[label] > 1 else label
            for label, value_type in display_values[:20]
        )
        if n_unique > 20:
            vals_str += f" ... 等共 {n_unique} 个值"
        return (f"已对「{name}」应用唯一值渲染，字段：{field}，{n_unique} 个类别，"
                f"色带：{color_scheme}\n"
                f"值列表：{vals_str}")
    except Exception as e:
        return f"唯一值渲染失败: {str(e)[:200]}"



@tool
def spatial_buffer(layer_name: str, distance: float, unit: str = "m", dissolve: bool = False) -> str:
    """为矢量图层创建缓冲区并加载到地图（按范围中心选用局部 UTM 米制投影）。
    - layer_name: 图层名。
    - distance: 有限且大于零的缓冲距离，适用于局部范围分析。
    - unit: 'm'(米,默认) 或 'km'(千米)。
    - dissolve: 是否融合重叠缓冲区多边形（默认 False，保留各要素独立缓冲区）。"""
    try:
        from backend.services.tool_args_guard import validate_tool_args
        normalized, _ = validate_tool_args("spatial_buffer", {"unit": unit})
        unit = normalized["unit"]
        if unit not in ("m", "km"):
            return f"缓冲区分析失败: 不支持的距离单位「{unit}」，仅支持 m 或 km"
        distance_m = distance * 1000 if unit == "km" else distance
        if not math.isfinite(distance_m) or distance_m <= 0:
            return "缓冲区分析失败: 缓冲距离及换算后的米数必须为有限正数"
        import geopandas as gpd
        from backend.services.spatial_robust import repair_geometry, estimate_tier, robust_note
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        gdf, rstats = repair_geometry(gdf)
        if len(gdf) == 0:
            return f"缓冲区分析失败: 图层「{name}」没有有效几何"
        tier = estimate_tier(gdf)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
        # 用 bounds 中心确定 UTM 带号（避免在 geographic CRS 下计算 centroid 的 warning）
        _b = gdf.total_bounds
        extent_error = _local_utm_extent_error(_b)
        if extent_error:
            return f"缓冲区分析失败: {extent_error}"
        lon, lat = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2
        crs_utm = _get_utm_crs(lon, lat)
        gdf_utm = gdf.to_crs(crs_utm)
        _cstats = None
        if tier["tier"] == "chunked":
            _buf_parts = []
            _batch_count = min(16, len(gdf_utm))
            _batch_size = math.ceil(len(gdf_utm) / _batch_count)
            _okc = 0
            _attempted_batches = 0
            for _start in range(0, len(gdf_utm), _batch_size):
                _sub = gdf_utm.iloc[_start:_start + _batch_size]
                _attempted_batches += 1
                try:
                    _buffered = _sub.copy()
                    _buffered["geometry"] = _sub.geometry.buffer(distance_m)
                    _buf_parts.append(_buffered)
                    _okc += 1
                except Exception:
                    pass
            import pandas as _pd
            _cstats = {
                "cells": _attempted_batches,
                "ok_cells": _okc,
                "failed_cells": _attempted_batches - _okc,
            }
            if _buf_parts:
                gdf_utm = _pd.concat(_buf_parts, ignore_index=True)
                gdf_utm = gpd.GeoDataFrame(gdf_utm, geometry="geometry", crs=crs_utm)
            else:
                return f"缓冲区分析失败: 所有分批缓冲均失败（{_cstats['failed_cells']} 批）"
        else:
            gdf_utm["geometry"] = gdf_utm.geometry.buffer(distance_m)
        if dissolve:
            gdf_utm = gpd.GeoDataFrame({"geometry": [gdf_utm.union_all()]}, geometry="geometry", crs=crs_utm)
        gdf_wgs = gdf_utm.to_crs("EPSG:4326")
        base_result_name = f"{name}_缓冲区"
        provenance = {
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {
                "tool": "spatial_buffer",
                "source_layer": name,
                "parameters": {"distance": float(distance), "unit": unit, "dissolve": bool(dissolve)},
            },
        }
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(gdf_wgs, result_name, style={
                "color": "#2563eb", "fillColor": "#60a5fa",
                "weight": 2, "opacity": 0.9, "fillOpacity": 0.06,
            }, provenance=provenance)
        _note = robust_note(rstats, tier, _cstats)
        return f"已为「{name}」创建{distance}{unit}缓冲区，{len(gdf_wgs)} 个要素，图层「{result_name}」已加载到地图{_note}"
    except Exception as e:
        import traceback
        return f"缓冲区分析失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


@tool
def spatial_multi_ring_buffer(layer_name: str, distances: str, unit: str = "m", dissolve: bool = False) -> str:
    """为指定图层创建多环缓冲区。distances 为逗号分隔的距离值（如"100,200,500"），每个距离生成一环。
    距离必须为有限正数，使用局部 UTM 米制投影。
    unit: m(米)/km(公里)；dissolve: 是否融合重叠缓冲区。所有环合并为单一图层。"""
    try:
        from backend.services.tool_args_guard import validate_tool_args
        normalized, _ = validate_tool_args("spatial_multi_ring_buffer", {"unit": unit})
        unit = normalized["unit"]
        if unit not in ("m", "km"):
            return f"多环缓冲区失败: 不支持的距离单位「{unit}」，仅支持 m 或 km"
        parts = distances.split(",")
        if len(parts) > 20:
            return f"多环缓冲区失败: 最多支持 20 个距离，当前 {len(parts)} 个"
        try:
            dist_list = [float(d.strip()) for d in parts]
        except ValueError:
            return '多环缓冲区失败: 每项距离必须为有限正数，如"100,200,500"'
        if any(not math.isfinite(d * 1000 if unit == "km" else d) or d <= 0 for d in dist_list):
            return "多环缓冲区失败: 每项距离及换算后的米数必须为有限正数"
        if len(set(dist_list)) != len(dist_list):
            return "多环缓冲区失败: 距离不能重复，否则会生成重复环带"

        import geopandas as gpd
        import pandas as pd
        import warnings

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        # 用 bounds 中心确定 UTM 带号（避免 geographic CRS 下计算 centroid 的 warning）
        _b = gdf.total_bounds
        extent_error = _local_utm_extent_error(_b)
        if extent_error:
            return f"多环缓冲区失败: {extent_error}"
        lon, lat = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2
        crs_utm = _get_utm_crs(lon, lat)
        gdf_utm = gdf.to_crs(crs_utm)

        distance_by_m = {d * 1000 if unit == "km" else d: d for d in dist_list}
        ring_geometry_by_m = {}
        previous_outer = None
        for distance_m in sorted(distance_by_m):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                buffered = gdf_utm.geometry.buffer(distance_m)
            if dissolve:
                outer = buffered.union_all()
                inner = previous_outer.union_all() if previous_outer is not None else None
                ring_geometry_by_m[distance_m] = outer.difference(inner) if inner is not None else outer
            else:
                ring_geometry_by_m[distance_m] = (
                    buffered.difference(previous_outer) if previous_outer is not None else buffered
                )
            previous_outer = buffered

        rings = []
        for i, d in enumerate(dist_list):
            distance_m = d * 1000 if unit == "km" else d
            geometry = ring_geometry_by_m[distance_m]
            if dissolve:
                ring = gpd.GeoDataFrame({"geometry": [geometry], "distance": d, "ring": i + 1},
                                        geometry="geometry", crs=crs_utm)
            else:
                ring = gpd.GeoDataFrame({"geometry": geometry, "distance": d, "ring": i + 1}, crs=crs_utm)
            rings.append(ring)

        merged = pd.concat(rings, ignore_index=True)
        merged = merged.to_crs("EPSG:4326")

        dist_str = "、".join(str(d) for d in dist_list)
        base_result_name = f"{name}_多环{unit}"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(merged, result_name)

        return (f"已为「{name}」创建 {len(dist_list)} 个多环缓冲区：{dist_str} {unit}，"
                f"共 {len(merged)} 个要素，图层「{result_name}」已加载到地图")
    except Exception as e:
        import traceback
        return f"多环缓冲区失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


@tool
def spatial_intersect(layer_a: str, layer_b: str) -> str:
    """两矢量图层的空间叠置求交分析，提取共同重叠部分并合并双方属性，生成新图层上图。
    - layer_a / layer_b: 待求交的两图层名。"""
    try:
        import geopandas as gpd
        from backend.services.spatial_robust import repair_geometry, estimate_tier, chunked_overlay, robust_note
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        gdf_a, rsa = repair_geometry(gdf_a)
        gdf_b, rsb = repair_geometry(gdf_b)
        rstats = {"repaired": rsa["repaired"] + rsb["repaired"],
                   "dropped": rsa["dropped"] + rsb["dropped"]}
        if len(gdf_a) == 0 or len(gdf_b) == 0:
            return f"相交分析失败: 输入图层没有有效几何"
        tier = estimate_tier(gdf_a if len(gdf_a) >= len(gdf_b) else gdf_b)
        _cstats = None
        if tier["tier"] == "chunked":
            result, _cstats = chunked_overlay(
                gdf_a, gdf_b, lambda a, b: gpd.overlay(a, b, how="intersection", keep_geom_type=False)
            )
        else:
            result = gpd.overlay(gdf_a, gdf_b, how="intersection", keep_geom_type=False)
        if result.empty:
            return f"「{name_a}」和「{name_b}」没有重叠区域"
        result_name = f"{name_a}_∩_{name_b}"
        _gdf_to_layer(result, result_name, provenance={
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {"tool": "spatial_intersect", "source_layer": name_a, "other_layer": name_b},
        })
        # 按去重覆盖面积计算比例；叠置记录保留属性组合，不合并要素。
        has_polygonal_result = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        res_area = _gdf_area_km2(result, unique=True) if has_polygonal_result else None
        area_a = _gdf_area_km2(gdf_a, unique=True) if has_polygonal_result else None
        area_b = _gdf_area_km2(gdf_b, unique=True) if has_polygonal_result else None
        stat = [f"相交分析完成，结果图层「{result_name}」已加载到地图。",
                f"- 相交要素数：{len(result)}"]
        if res_area is not None:
            stat.append(f"- 相交覆盖面积（去除重叠）：{res_area:.4f} 平方千米")
            if area_a:
                stat[-1] += f"，占「{name_a}」的 {res_area/area_a*100:.2f}%"
            if area_b:
                stat.append(f"- 占「{name_b}」面积的 {res_area/area_b*100:.2f}%")
        stat.append(f"- 输入图层：{name_a}（{len(gdf_a)} 要素）、{name_b}（{len(gdf_b)} 要素）")
        stat.append(robust_note(rstats, tier, _cstats).strip("（）") or None)
        return "\n".join([s for s in stat if s])
    except Exception as e:
        return f"相交分析失败: {str(e)[:300]}"


@tool
def spatial_union(layer_a: str, layer_b: str) -> str:
    """合并两个图层的全部几何区域。"""
    try:
        import geopandas as gpd
        from backend.services.spatial_robust import repair_geometry, estimate_tier, robust_note
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        gdf_a, rsa = repair_geometry(gdf_a)
        gdf_b, rsb = repair_geometry(gdf_b)
        rstats = {"repaired": rsa["repaired"] + rsb["repaired"],
                   "dropped": rsa["dropped"] + rsb["dropped"]}
        if len(gdf_a) == 0 or len(gdf_b) == 0:
            return f"合并失败: 输入图层没有有效几何"
        tier = estimate_tier(gdf_a if len(gdf_a) >= len(gdf_b) else gdf_b)
        _cstats = None
        # union 的 B 独有区域依赖完整 A 图层；按 A 分批会重复生成不同范围的 B 差集。
        result = gpd.overlay(gdf_a, gdf_b, how="union", keep_geom_type=False)
        result_name = f"{name_a}__{name_b}"
        _gdf_to_layer(result, result_name, provenance={
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {"tool": "spatial_union", "source_layer": name_a, "other_layer": name_b},
        })
        _note = robust_note(rstats, tier, _cstats)
        return f"合并完成：{len(result)} 个要素，已加载到地图{_note}"
    except Exception as e:
        return f"合并失败: {str(e)[:300]}"


@tool
def spatial_difference(layer_a: str, layer_b: str) -> str:
    """用 layer_a 减去 layer_b，返回 layer_a 中不在 layer_b 内的部分。"""
    try:
        import geopandas as gpd
        from backend.services.spatial_robust import repair_geometry, estimate_tier, chunked_overlay, robust_note
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        gdf_a, rsa = repair_geometry(gdf_a)
        gdf_b, rsb = repair_geometry(gdf_b)
        rstats = {"repaired": rsa["repaired"] + rsb["repaired"],
                   "dropped": rsa["dropped"] + rsb["dropped"]}
        if len(gdf_a) == 0 or len(gdf_b) == 0:
            return f"差异分析失败: 输入图层没有有效几何"
        tier = estimate_tier(gdf_a if len(gdf_a) >= len(gdf_b) else gdf_b)
        _cstats = None
        if tier["tier"] == "chunked":
            result, _cstats = chunked_overlay(gdf_a, gdf_b, lambda a, b: gpd.overlay(a, b, how="difference"))
        else:
            result = gpd.overlay(gdf_a, gdf_b, how="difference")
        if result.empty:
            return f"「{name_a}」完全被「{name_b}」覆盖，无剩余部分"
        result_name = f"{name_a}_减_{name_b}"
        _gdf_to_layer(result, result_name, provenance={
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {"tool": "spatial_difference", "source_layer": name_a, "other_layer": name_b},
        })
        has_polygonal_result = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        res_area = _gdf_area_km2(result) if has_polygonal_result else None
        area_a = _gdf_area_km2(gdf_a) if has_polygonal_result else None
        stat = [f"差异分析完成，结果图层「{result_name}」已加载到地图。",
                f"- 剩余要素数：{len(result)}"]
        if res_area is not None:
            line = f"- 剩余面积：{res_area:.4f} 平方千米"
            if area_a:
                line += f"（占「{name_a}」的 {res_area/area_a*100:.2f}%）"
            stat.append(line)
        stat.append(robust_note(rstats, tier, _cstats).strip("（）") or None)
        return "\n".join([s for s in stat if s])
    except Exception as e:
        return f"差异分析失败: {str(e)[:300]}"


@tool
def spatial_clip(layer_name: str, clip_layer: str) -> str:
    """用 clip_layer 的边界裁剪 layer_name。"""
    try:
        import geopandas as gpd
        from backend.services.spatial_robust import repair_geometry, estimate_tier, chunked_overlay, robust_note
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        clip_gdf, clip_name = _layer_to_gdf(clip_layer)
        if clip_gdf is None: return clip_name
        gdf, rsa = repair_geometry(gdf)
        clip_gdf, rsb = repair_geometry(clip_gdf)
        rstats = {"repaired": rsa["repaired"] + rsb["repaired"],
                   "dropped": rsa["dropped"] + rsb["dropped"]}
        if len(gdf) == 0 or len(clip_gdf) == 0:
            return f"裁剪失败: 输入图层没有有效几何"
        tier = estimate_tier(gdf if len(gdf) >= len(clip_gdf) else clip_gdf)
        _cstats = None
        if tier["tier"] == "chunked":
            result, _cstats = chunked_overlay(gdf, clip_gdf, lambda a, b: gpd.clip(a, b))
        else:
            result = gpd.clip(gdf, clip_gdf)
        if result.empty:
            return f"裁剪后无剩余要素（「{name}」不在「{clip_name}」范围内）"
        base_result_name = f"{name}_裁剪"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(result, result_name, provenance={
                "provider": "gis_worktable",
                "kind": "analysis_result",
                "processing": {"tool": "spatial_clip", "source_layer": name, "clip_layer": clip_name},
            })
        has_polygonal_result = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        res_area = _gdf_area_km2(result) if has_polygonal_result else None
        src_area = _gdf_area_km2(gdf) if has_polygonal_result else None
        stat = [f"裁剪完成，结果图层「{result_name}」已加载到地图。",
                f"- 裁剪后要素数：{len(result)}"]
        if res_area is not None:
            line = f"- 裁剪后面积：{res_area:.4f} 平方千米"
            if src_area:
                line += f"（占原图层的 {res_area/src_area*100:.2f}%）"
            stat.append(line)
        stat.append(robust_note(rstats, tier, _cstats).strip("（）") or None)
        return "\n".join([s for s in stat if s])
    except Exception as e:
        return f"裁剪失败: {str(e)[:300]}"


@tool
def spatial_centroid(layer_name: str) -> str:
    """在局部米制投影中提取线/面质心并还原原 CRS，返回点图层。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        if gdf.geometry.geom_type.eq("Point").all():
            centroids = gdf.copy()
        else:
            metric_gdf = _to_local_metric_gdf(gdf)
            centroids = metric_gdf.copy()
            centroids["geometry"] = metric_gdf.geometry.centroid
            centroids = centroids.to_crs(gdf.crs)
        centroids = centroids[centroids.geometry.notna()]
        if centroids.empty:
            return f"错误：图层「{name}」没有可用于质心计算的有效几何"
        result_name = f"{name}_质心"
        _gdf_to_layer(centroids, result_name)
        return f"已提取 {len(centroids)} 个质心，已加载到地图"
    except Exception as e:
        return f"质心提取失败: {str(e)[:300]}"


@tool
def spatial_simplify(layer_name: str, tolerance: float = 0.001) -> str:
    """简化图层几何，减少顶点数。tolerance 为简化容差（单位：度），0.001 约等于 100m。"""
    try:
        if not math.isfinite(tolerance) or tolerance <= 0:
            return "简化失败: tolerance 必须为有限正数（单位：度）"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
        base_result_name = f"{name}_简化"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(gdf, result_name)
        return f"已简化「{name}」（容差 {tolerance}），{len(gdf)} 个要素，图层「{result_name}」已加载到地图"
    except Exception as e:
        return f"简化失败: {str(e)[:300]}"


@tool
def spatial_dissolve(layer_name: str, group_by: str = "") -> str:
    """按属性字段融合图层几何。相同字段值的要素合并为一个。不传 group_by 则融合全部要素。"""
    try:
        import geopandas as gpd
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        if group_by and group_by not in gdf.columns:
            return f"融合失败: 图层「{name}」不存在字段「{group_by}」，未创建结果图层"
        if group_by:
            result = gdf.dissolve(by=group_by, aggfunc="first", dropna=False).reset_index()
            result_name = f"{name}_按{group_by}融合"
        else:
            result = gpd.GeoDataFrame({"geometry": [gdf.union_all()]}, geometry="geometry", crs="EPSG:4326")
            result_name = f"{name}_融合"
        _gdf_to_layer(result, result_name)
        return f"融合完成：{len(result)} 个要素，已加载到地图"
    except Exception as e:
        return f"融合失败: {str(e)[:300]}"


@tool
def spatial_select(target_layer: str, source_layer: str, predicate: str = "intersects") -> str:
    """按空间关系选择要素。返回 target_layer 中与 source_layer 满足关系的要素。predicate: intersects / within / contains / touches / crosses / overlaps。"""
    try:
        import geopandas as gpd
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None: return name_t
        gdf_s, name_s = _layer_to_gdf(source_layer)
        if gdf_s is None: return name_s
        joined = gpd.sjoin(gdf_t, gdf_s, how="inner", predicate=predicate)
        # This is a selection, so return original target rows only. Filtering
        # the left index preserves all target attributes (including names that
        # happen to end in ``_right``) and avoids leaking source-only fields.
        result = gdf_t.loc[gdf_t.index.isin(joined.index)].copy()
        if result.empty:
            return f"没有要素满足「{predicate}」关系"
        base_result_name = f"{name_t}_选择"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(result, result_name)
        return f"按「{predicate}」选择了 {len(result)}/{len(gdf_t)} 个要素，图层「{result_name}」已加载到地图"
    except Exception as e:
        return f"空间选择失败: {str(e)[:300]}"


@tool
def spatial_sample(layer_name: str, n: int = 0, frac: float = 0) -> str:
    """从图层随机采样 n 个要素（或 frac 比例）。n 和 frac 至少指定一个。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0 or int(n) != n:
            return "采样失败: n 必须是非负整数"
        n = int(n)
        if isinstance(frac, bool) or not isinstance(frac, (int, float)) or not math.isfinite(frac) or frac < 0:
            return "采样失败: frac 必须是 0 到 1 之间的有限比例"
        frac = float(frac)
        if n > 0 and frac > 0:
            return "采样失败: n 和 frac 只能指定一个"
        if n > 0:
            n = min(n, len(gdf))
            sampled = gdf.sample(n=n)
        elif frac > 0:
            if frac > 1:
                return "采样失败: frac 必须不大于 1"
            sampled = gdf.sample(frac=frac)
        else:
            return "错误：请指定 n（数量）或 frac（比例）"
        if sampled.empty:
            return "采样结果为空"
        base_result_name = f"{name}_采样{n or frac}"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            provenance = {"tool": "spatial_sample", "source_layer": name, "n": n, "frac": frac}
            _gdf_to_layer(sampled, result_name, provenance=provenance)
        return f"已随机采样 {len(sampled)}/{len(gdf)} 个要素，图层「{result_name}」已加载到地图"
    except Exception as e:
        return f"采样失败: {str(e)[:300]}"


@tool
def spatial_near(layer_name: str, target_layer: str, distance: float = 1000) -> str:
    """查找 target_layer 中距离 layer_name 要素 distance 米以内的要素。
    使用两个图层范围共同估算的局部 UTM 投影；适用于局部区域，跨 UTM 带或跨日期变更线的数据应先分区。
    """
    try:
        import geopandas as gpd
        if isinstance(distance, bool):
            return "近邻查找失败: distance 必须是有限的非负米数"
        distance = float(distance)
        if not math.isfinite(distance) or distance < 0:
            return "近邻查找失败: distance 必须是有限的非负米数"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None: return name_t
        combined = gpd.GeoDataFrame(
            {"geometry": list(gdf.geometry) + list(gdf_t.geometry)},
            geometry="geometry",
            crs=gdf.crs,
        )
        extent_error = _local_utm_extent_error(combined.total_bounds)
        if extent_error:
            return f"近邻查找失败: {extent_error}"
        metric_crs = combined.estimate_utm_crs()
        if metric_crs is None:
            return "近邻查找失败: 无法根据两个图层范围确定局部米制投影"
        gdf_u = gdf.to_crs(metric_crs)
        gdf_tu = gdf_t.to_crs(metric_crs)
        near_geometries = gdf_u.geometry if distance == 0 else gdf_u.geometry.buffer(distance)
        gdf_u_buf = gpd.GeoDataFrame(
            {"geometry": near_geometries}, geometry="geometry", crs=metric_crs,
        )
        hits = gpd.sjoin(gdf_tu, gdf_u_buf, how="inner", predicate="intersects")
        if hits.empty:
            return f"「{name_t}」中未找到距离「{name}」{distance}m 以内的要素"
        result = gdf_t.iloc[hits.index.unique()].copy()
        base_result_name = f"{name_t}_附近"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(result, result_name)
        return f"找到 {len(result)} 个距离{distance}m 以内的要素，图层「{result_name}」已加载到地图"
    except Exception as e:
        return f"近邻查找失败: {str(e)[:300]}"


@tool
def nearest_pair(
    layer_name: str,
    target_layer: str = "",
    feature_filter: str = "",
    target_filter: str = "",
) -> str:
    """查找同一图层或两个不同图层之间距离最近的一对要素，可按属性关键词筛选。

    适用于“图层里最近的一对”“最近的两家医院”“最近的一家麦当劳和一家医院”等问题。
    target_layer 留空时在 layer_name 内比较；填写时在 layer_name 与 target_layer 之间比较。
    feature_filter 和 target_filter 分别用于在对应图层的要素属性中匹配关键词。
    对点要素计算点间距离；对面或线要素以代表点计算距离。距离使用局部 UTM 投影，单位为米。
    """
    try:
        from scipy.spatial import cKDTree

        source, source_name = _layer_to_gdf(layer_name)
        if source is None:
            return source_name
        same_layer = not target_layer
        if same_layer:
            target, target_name = source, source_name
            target_filter = target_filter or feature_filter
        else:
            target, target_name = _layer_to_gdf(target_layer)
            if target is None:
                return target_name
            same_layer = source_name == target_name and (not target_filter or target_filter == feature_filter)

        def select_features(gdf, keyword):
            valid = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
            if keyword and keyword.strip():
                needle = keyword.strip().casefold()
                matched = valid.apply(
                    lambda row: any(
                        needle in str(value).casefold()
                        for value in row.drop(labels="geometry", errors="ignore")
                        if value is not None
                    ),
                    axis=1,
                )
                valid = valid[matched]
            return valid

        left = select_features(source, feature_filter)
        right = select_features(target, target_filter)
        for gdf, name, keyword in ((left, source_name, feature_filter), (right, target_name, target_filter)):
            if gdf.empty:
                subject = f"属性包含「{keyword}」的" if keyword else ""
                return f"错误：图层「{name}」中没有{subject}有效要素"
        insufficient = len(left) < 2 if same_layer else len(left) < 1 or len(right) < 1
        if insufficient:
            return "错误：可比较的要素不足，无法计算最近距离"

        import geopandas as gpd
        combined = gpd.GeoDataFrame(
            {"geometry": list(left.geometry) + list(right.geometry)},
            geometry="geometry",
            crs=left.crs,
        )
        extent_error = _local_utm_extent_error(combined.total_bounds)
        if extent_error:
            return f"错误：无法计算最近距离: {extent_error}"
        metric_crs = combined.estimate_utm_crs()
        if metric_crs is None:
            return "错误：无法确定用于距离计算的局部投影坐标系"
        left_points = left.to_crs(metric_crs).geometry.representative_point()
        right_points = right.to_crs(metric_crs).geometry.representative_point()
        left_xy = [(point.x, point.y) for point in left_points]
        right_xy = [(point.x, point.y) for point in right_points]
        if same_layer:
            distances, indices = cKDTree(left_xy).query(left_xy, k=2)
            pairs = (
                (float(distance), i, int(j))
                for i, (distance, j) in enumerate(zip(distances[:, 1], indices[:, 1]))
                if i != int(j)
            )
        else:
            distances, indices = cKDTree(right_xy).query(left_xy, k=1)
            pairs = ((float(distance), i, int(j)) for i, (distance, j) in enumerate(zip(distances, indices)))
        distance_m, source_index, target_index = min(pairs, key=lambda item: item[0])

        left_rows = [row for _, row in left.iterrows()]
        right_rows = left_rows if same_layer else [row for _, row in right.iterrows()]
        name_fields = ("name", "医院名称", "poi_name", "NAME", "名称", "name:zh")

        def feature_name(row, index):
            for field in name_fields:
                value = row.get(field)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return f"要素 {index + 1}"

        names = (
            feature_name(left_rows[source_index], source_index),
            feature_name(right_rows[target_index], target_index),
        )
        distance_text = f"{distance_m:.1f} 米" if distance_m < 1000 else f"{distance_m / 1000:.3f} 千米"
        geometry_note = "点间距离" if all(g.geom_type == "Point" for g in list(left.geometry) + list(right.geometry)) else "要素代表点间距离"
        subject = f"（属性包含「{feature_filter}」）" if feature_filter else ""
        target_subject = f"（属性包含「{target_filter}」）" if target_filter and not same_layer else ""
        return (
            f"图层「{source_name}」{subject}与图层「{target_name}」{target_subject}距离最近的一对是："
            f"{names[0]} 和 {names[1]}；"
            f"{geometry_note}约 {distance_text}（{distance_m:.1f} 米）。"
        )
    except Exception as e:
        return f"最近要素对计算失败: {str(e)[:300]}"


@tool
def spatial_cluster(
    layer_name: str,
    eps: float = 0.01,
    min_samples: int = 3,
    distance_unit: str = "degrees",
) -> str:
    """用 DBSCAN 对点图层做空间聚类。

【参数选择】
- eps：邻域半径，默认按度数计算以兼容旧调用；请求固定地面距离时选择 m 或 km。
- distance_unit：degrees（默认，角度单位）、m 或 km。度数对应地理坐标平面距离，地面换算会随纬度变化。
- min_samples：一个簇最少要素数，通常 3-5。
- 结果添加 cluster 字段，-1 表示噪声点（不属于任何簇，是正常现象）。

【常见坑】
- eps 太小导致所有点都是噪声；请求固定地面距离时请使用 m/km，不要把 measure_distance 返回的米数直接填入默认度数参数。
- eps 太大把所有点聚成一个簇。
- 不适合密度差异极大的数据，可考虑 HDBSCAN（execute_python）。"""
    try:
        if (isinstance(eps, bool) or not isinstance(eps, (int, float))
                or not math.isfinite(eps) or eps <= 0):
            return "聚类失败: eps 必须为有限正数"
        if distance_unit not in ("degrees", "m", "km"):
            return "聚类失败: distance_unit 仅支持 degrees、m 或 km"
        if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1:
            return "聚类失败: min_samples 必须为正整数"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        geometries = gdf.geometry
        if geometries.isna().any() or geometries.is_empty.any():
            return "聚类失败: 输入点图层包含空几何，请先清理"
        if not geometries.geom_type.eq("Point").all():
            return "聚类失败: 仅支持 Point 点图层"
        from sklearn.cluster import DBSCAN
        if distance_unit == "degrees":
            coords = geometries.get_coordinates().values
        else:
            extent_error = _local_utm_extent_error(gdf.total_bounds)
            if extent_error:
                return f"聚类失败: {extent_error}"
            coords = _to_local_metric_gdf(gdf).geometry.get_coordinates().values
        if len(coords) < min_samples:
            return f"错误：要素数（{len(coords)}）少于最少点数（{min_samples}），无法聚类"
        eps_value = eps * 1000 if distance_unit == "km" else eps
        if not math.isfinite(eps_value):
            return "聚类失败: eps 换算后超出可计算范围"
        clustering = DBSCAN(eps=eps_value, min_samples=min_samples).fit(coords)
        gdf["cluster"] = clustering.labels_.tolist()
        n_clusters = len(set(clustering.labels_)) - (1 if -1 in clustering.labels_ else 0)
        noise = list(clustering.labels_).count(-1)
        with _state_lock:
            result_name = _disambiguate_layer_name(f"{name}_聚类")
            _gdf_to_layer(gdf, result_name)
        return f"聚类完成：{n_clusters} 个簇，{noise} 个噪声点（eps={eps:g}{distance_unit}），图层「{result_name}」已加载到地图（含 cluster 字段）"
    except Exception as e:
        return f"聚类失败: {str(e)[:300]}"


@tool
def spatial_voronoi(layer_name: str) -> str:
    """根据点图层生成泰森多边形（Voronoi 图）。
    输出面由 Shapely 根据输入点自动扩展的外包络范围裁切，并不等于输入点凸包；
    如需限制到实际研究区，请再用研究区面执行空间相交或裁剪。
    """
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        geometries = gdf.geometry
        if geometries.isna().any() or geometries.is_empty.any():
            return "泰森多边形失败: 输入点图层包含空几何，请先清理"
        if not geometries.geom_type.isin(["Point", "MultiPoint"]).all():
            return "泰森多边形失败: 仅支持 Point 或 MultiPoint 点图层"
        unique_sites = set()
        for geometry in geometries:
            site_geometries = [geometry] if geometry.geom_type == "Point" else geometry.geoms
            unique_sites.update((point.x, point.y) for point in site_geometries)
        if len(unique_sites) < 2:
            return "泰森多边形失败: 至少需要 2 个位置不同的点"
        from shapely.ops import voronoi_diagram
        metric_gdf = _to_local_metric_gdf(gdf)
        points = metric_gdf.geometry.union_all()
        polygons = voronoi_diagram(points)
        import geopandas as gpd
        result = gpd.GeoDataFrame(
            {"geometry": list(polygons.geoms)}, geometry="geometry", crs=metric_gdf.crs,
        ).to_crs("EPSG:4326")
        if result.empty:
            return "错误：泰森多边形生成失败"
        result_name = f"{name}_泰森"
        _gdf_to_layer(result, result_name)
        return f"已生成 {len(result)} 个泰森多边形，已加载到地图"
    except Exception as e:
        return f"泰森多边形失败: {str(e)[:300]}"


@tool
def spatial_field_stats(layer_name: str, field: str = "") -> str:
    """统计图层数值字段的基本统计量（count / min / max / mean / sum / std / 空值数）。不指定 field 则列出所有可统计字段。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        import numpy as np
        numeric_cols = gdf.select_dtypes(include=[np.number]).columns.tolist()
        if not field:
            return f"「{name}」的数值字段：{', '.join(numeric_cols) if numeric_cols else '无'}"
        if field not in gdf.columns:
            return f"错误：「{name}」中无字段「{field}」，可用字段：{', '.join(gdf.columns)}"
        if field not in numeric_cols:
            return f"错误：字段「{field}」不是数值类型，类型：{gdf[field].dtype}"
        vals = gdf[field].dropna()
        from collections import OrderedDict
        stats = OrderedDict([
            ("count", len(gdf)),
            ("non_null", len(vals)),
            ("null", int(gdf[field].isna().sum())),
            ("min", float(vals.min())),
            ("max", float(vals.max())),
            ("mean", float(vals.mean())),
            ("sum", float(vals.sum())),
            ("std", float(vals.std()) if len(vals) > 1 else 0),
        ])
        lines = [f"📊 「{name}」.{field} 统计："]
        for k, v in stats.items():
            lines.append(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
        return "\n".join(lines)
    except Exception as e:
        return f"字段统计失败: {str(e)[:300]}"


@tool
def spatial_join(target_layer: str, join_layer: str, how: str = "left", predicate: str = "intersects") -> str:
    """按空间拓扑关系将 join_layer 的属性连接到 target_layer。
    - target_layer / join_layer: 待连接的目标图层与数据源图层。
    - how: 'left'(保留所有目标要素，未匹配为 NaN) 或 'inner'(仅保留匹配成功的要素)。
    - predicate: 空间拓扑谓词，例如 'intersects'(默认相交) / 'within'(在内部) / 'contains'(包含) / 'touches'(边界接触)。"""
    if predicate == "nearest":
        return "空间连接失败：nearest 不是可用的拓扑谓词。如需查找两图层最近的一对要素，请使用 nearest_pair。"
    if how not in ("left", "inner"):
        return "空间连接失败：how 仅支持 left（保留全部目标要素）或 inner（仅保留匹配要素）。"
    try:
        import geopandas as gpd
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None: return name_t
        gdf_j, name_j = _layer_to_gdf(join_layer)
        if gdf_j is None: return name_j
        for frame, side in ((gdf_t, "target"), (gdf_j, "join")):
            if "index_right" in frame.columns:
                column = f"index_right_{side}"
                suffix = 2
                while column in gdf_t.columns or column in gdf_j.columns:
                    column = f"index_right_{side}_{suffix}"
                    suffix += 1
                frame.rename(columns={"index_right": column}, inplace=True)
        result = gpd.sjoin(gdf_t, gdf_j, how=how, predicate=predicate)
        base_result_name = f"{name_t}_连接{name_j}"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(result, result_name)
        return f"空间连接完成：{len(result)} 个要素，图层「{result_name}」已加载到地图"
    except Exception as e:
        return f"空间连接失败: {str(e)[:300]}"


@tool
def layer_merge(layer_names: str, new_name: str = "") -> str:
    """合并多个图层为一个（行合并）。layer_names 用逗号分隔。"""
    try:
        import geopandas as gpd
        import pandas as pd
        names = [n.strip() for n in layer_names.split(",") if n.strip()]
        if len(names) < 2:
            return "错误：图层合并至少需要提供 2 个图层名（逗号分隔）"
        if len(names) != len(set(names)):
            duplicates = [n for n in names if names.count(n) > 1]
            return f"错误：图层合并列表中包含重复图层名「{duplicates[0]}」"

        gdfs = []
        resolved_names = []
        for n in names:
            gdf, resolved = _layer_to_gdf(n)
            if gdf is None: return resolved
            gdfs.append(gdf)
            resolved_names.append(resolved)

        target_crs = gdfs[0].crs or "EPSG:4326"
        unified_gdfs = []
        for g in gdfs:
            if g.crs and g.crs != target_crs:
                unified_gdfs.append(g.to_crs(target_crs))
            else:
                unified_gdfs.append(g)

        concatenated = pd.concat(unified_gdfs, ignore_index=True)
        result = gpd.GeoDataFrame(concatenated, crs=target_crs)
        base_name = new_name.strip() or f"{'_'.join(resolved_names)}_合并"
        with _state_lock:
            merged_name = _disambiguate_layer_name(base_name)
            provenance = {"tool": "layer_merge", "source_layers": resolved_names}
            _gdf_to_layer(result, merged_name, provenance=provenance)
        return f"合并完成：{len(result)} 个要素（{len(resolved_names)} 个图层），结果图层「{merged_name}」已加载到地图"
    except Exception as e:
        return f"图层合并失败: {str(e)[:300]}"


@tool
def layer_split(layer_name: str, by_field: str = "") -> str:
    """按属性字段拆分图层，每个唯一值生成一个子图层。不传 by_field 则每个要素单独成层（上限 50 层）。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        if gdf.empty:
            return f"错误：图层「{name}」为空，无法拆分"

        MAX_SPLIT_LAYERS = 50

        def register_part(group, base_name):
            with _state_lock:
                result_name = _disambiguate_layer_name(base_name)
                provenance = {"tool": "layer_split", "source_layer": name, "by_field": by_field}
                _gdf_to_layer(group, result_name, provenance=provenance)

        if by_field and by_field not in gdf.columns:
            return f"错误：图层「{name}」不存在字段「{by_field}」，可用字段：{', '.join(map(str, gdf.columns))}"
        if by_field:
            groups = list(gdf.groupby(by_field, dropna=False))
            if len(groups) > MAX_SPLIT_LAYERS:
                return f"错误：字段「{by_field}」包含 {len(groups)} 个唯一值，超出拆分上限（最多 {MAX_SPLIT_LAYERS} 个图层）；未执行拆分"
            count = 0
            for val, group in groups:
                val_str = "null" if val is None or (isinstance(val, float) and math.isnan(val)) else str(val)
                register_part(group, f"{name}_{val_str}")
                count += 1
            return f"按字段「{by_field}」拆分为 {count} 个子图层（共 {len(gdf)} 个要素），已加载到地图"
        else:
            if len(gdf) > MAX_SPLIT_LAYERS:
                return f"错误：图层「{name}」要素过多（{len(gdf)} 个），未指定字段拆分时最多支持 {MAX_SPLIT_LAYERS} 个要素单独成层；请指定 by_field 字段按类别拆分"
            for i in range(len(gdf)):
                sub = gdf.iloc[[i]].copy()
                register_part(sub, f"{name}_{i}")
            return f"已拆分为 {len(gdf)} 个独立要素图层，已加载到地图"
    except Exception as e:
        return f"图层拆分失败: {str(e)[:300]}"


@tool
def layer_add_geometry(layer_name: str, lon_field: str = "", lat_field: str = "") -> str:
    """根据图层中的经度/纬度字段创建点几何。自动识别常见列名（lng/lon/longitude/x, lat/latitude/y）。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        import geopandas as gpd
        from shapely.geometry import Point
        lon_candidates = ["lng", "lon", "longitude", "x", "经度", "经"]
        lat_candidates = ["lat", "latitude", "y", "纬度", "纬"]

        if lon_field and lon_field not in gdf.columns:
            return f"错误：图层「{name}」不存在经度列「{lon_field}」，可用列：{', '.join(map(str, gdf.columns))}"
        if lat_field and lat_field not in gdf.columns:
            return f"错误：图层「{name}」不存在纬度列「{lat_field}」，可用列：{', '.join(map(str, gdf.columns))}"

        if not lon_field:
            for c in lon_candidates:
                if c in gdf.columns:
                    lon_field = c
                    break
        if not lat_field:
            for c in lat_candidates:
                if c in gdf.columns:
                    lat_field = c
                    break
        if not lon_field or not lat_field:
            return f"错误：未找到经纬度列，可用列：{', '.join(map(str, gdf.columns))}"
        if lon_field == lat_field:
            return f"错误：经度字段与纬度字段不能相同（均为「{lon_field}」）"
        import math
        try:
            longitudes = gdf[lon_field].map(float)
            latitudes = gdf[lat_field].map(float)
        except (TypeError, ValueError, OverflowError):
            return "错误：经纬度字段必须包含有效数值，且不能有空值或非数值"
        if not all(math.isfinite(value) for value in longitudes) or not all(math.isfinite(value) for value in latitudes):
            return "错误：经纬度字段必须包含有限数值，且不能有空值或非数值"
        if ((longitudes < -180) | (longitudes > 180)).any() or ((latitudes < -90) | (latitudes > 90)).any():
            return "错误：经纬度超出有效范围：经度 -180 至 180，纬度 -90 至 90"
        gdf["geometry"] = [Point(lon, lat) for lon, lat in zip(longitudes, latitudes)]
        gdf = gdf.set_geometry("geometry", crs="EPSG:4326")
        with _state_lock:
            result_name = _disambiguate_layer_name(f"{name}_点")
            provenance = {"tool": "layer_add_geometry", "source_layer": name, "lon_field": lon_field, "lat_field": lat_field}
            _gdf_to_layer(gdf, result_name, provenance=provenance)
        return f"已从 {lon_field}/{lat_field} 创建 {len(gdf)} 个点，图层「{result_name}」已加载到地图"
    except Exception as e:
        return f"创建几何失败: {str(e)[:300]}"


@tool
def update_attribute(layer_name: str, field: str, value: str, condition_field: str = "", condition_value: str = "") -> str:
    """更新图层要素的属性值。不指定条件则更新所有要素；只改一条要素时优先用 condition_field="_fid" 和 get_layer_detail 返回的稳定 ID。
    支持数值和文本字段。更新后地图自动同步。
    layer_name: 必须为注册图层完整名称；field: 要更新的字段名；value: 新值（自动转换类型）；
    condition_field: 条件字段名（可选）；condition_value: 条件字段值（可选，仅更新匹配要素）。"""
    try:
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        import copy
        import geopandas as gpd

        features = info["geojson"]["features"]
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field not in gdf.columns:
            return f"图层「{layer_name}」没有字段「{field}」，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"
        if field == "_fid":
            return "_fid 是要素稳定标识，不能修改"

        def property_kind(values, fallback):
            present = [item for item in values if item is not None]
            if not present:
                return fallback
            if all(isinstance(item, bool) for item in present):
                return "b"
            if all(isinstance(item, int) and not isinstance(item, bool) for item in present):
                return "i"
            if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in present):
                return "f"
            return "O"

        raw_field_values = [
            (feature.get("properties") or {}).get(field) for feature in features
        ]
        # Convert against source values so mixed nulls do not make large integer
        # properties appear to be floating point.
        dtype_kind = property_kind(raw_field_values, gdf[field].dtype.kind)
        try:
            if dtype_kind in ('i', 'u'):
                typed_value = int(value)
            elif dtype_kind == 'f':
                typed_value = float(value)
            elif dtype_kind == 'b':
                normalized = str(value).strip().casefold()
                if normalized not in ("true", "false"):
                    return f"字段「{field}」为布尔类型，请使用 true 或 false"
                typed_value = normalized == "true"
            else:
                typed_value = str(value)
        except ValueError:
            return f"字段「{field}」类型为 {gdf[field].dtype}，但值「{value}」无法转换"
        if dtype_kind == "f" and not math.isfinite(typed_value):
            return f"字段「{field}」只接受有限浮点数"

        # 筛选要更新的行
        if condition_field:
            if condition_field not in gdf.columns:
                return f"条件字段「{condition_field}」不存在"
            raw_condition_values = [
                (feature.get("properties") or {}).get(condition_field) for feature in features
            ]
            cond_kind = property_kind(raw_condition_values, gdf[condition_field].dtype.kind)
            try:
                if cond_kind in ('i', 'u', 'f'):
                    cond_value = _parse_numeric_condition(condition_value, cond_kind)
                elif cond_kind == 'b':
                    normalized = str(condition_value).strip().casefold()
                    cond_value = normalized == "true" if normalized in ("true", "false") else condition_value
                else:
                    cond_value = str(condition_value)
            except ValueError:
                cond_value = str(condition_value)

            matches_mask = [item == cond_value for item in raw_condition_values]
            match_count = sum(matches_mask)
            if match_count == 0:
                return f"没有要素满足条件（{condition_field} = {condition_value}）"
            target_indices = [index for index, matched in enumerate(matches_mask) if matched]
            affected_geojson = copy.deepcopy(info["geojson"])
            for index in target_indices:
                properties = affected_geojson["features"][index].get("properties")
                if not isinstance(properties, dict):
                    properties = {}
                    affected_geojson["features"][index]["properties"] = properties
                properties[field] = typed_value
            affected = match_count
        else:
            affected_geojson = copy.deepcopy(info["geojson"])
            for feature in affected_geojson["features"]:
                properties = feature.get("properties")
                if not isinstance(properties, dict):
                    properties = {}
                    feature["properties"] = properties
                properties[field] = typed_value
            affected = len(gdf)

        geojson_data = affected_geojson
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        condition_str = f"（条件：{condition_field} = {condition_value}）" if condition_field else ""
        return (f"已更新图层「{layer_name}」字段「{field}」为 {value}，"
                f"影响 {affected}/{len(gdf)} 个要素{condition_str}，已同步地图")
    except Exception as e:
        return f"属性更新失败: {str(e)[:300]}"


@tool
def delete_features(layer_name: str, condition_field: str = "", condition_value: str = "") -> str:
    """按条件删除图层的要素。必须指定条件（例如删除某个字段等于某值的所有要素）。
    删除后地图自动同步。layer_name: 图层名；condition_field: 条件字段名（必填）；
    condition_value: 要匹配的字段值（可为空字符串，例如删除空值记录）；用 condition_field="_fid" 可精准删除单条要素。"""
    try:
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        if not condition_field:
            return "请指定删除条件（condition_field 和 condition_value），例如删除 name=xx 的所有要素"

        import copy
        import geopandas as gpd

        features = info["geojson"]["features"]
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if condition_field not in gdf.columns:
            return f"条件字段「{condition_field}」不存在，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

        raw_values = [
            (feature.get("properties") or {}).get(condition_field)
            for feature in features
        ]
        non_null_values = [value for value in raw_values if value is not None]
        if non_null_values and all(isinstance(value, bool) for value in non_null_values):
            cond_kind = "b"
        elif non_null_values and all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in non_null_values
        ):
            cond_kind = "i"
        elif non_null_values and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in non_null_values
        ):
            cond_kind = "f"
        else:
            cond_kind = "O"
        try:
            if cond_kind in ('i', 'u', 'f'):
                cond_val = _parse_numeric_condition(condition_value, cond_kind)
            elif cond_kind == 'b':
                normalized = str(condition_value).strip().casefold()
                cond_val = normalized == "true" if normalized in ("true", "false") else condition_value
            else:
                cond_val = str(condition_value)
        except ValueError:
            cond_val = str(condition_value)

        mask = [value == cond_val for value in raw_values]
        to_delete = sum(mask)
        if to_delete == 0:
            return f"没有要素满足条件（{condition_field} = {condition_value}）"

        remaining_indices = [index for index, matched in enumerate(mask) if not matched]
        if not remaining_indices:
            return f"条件（{condition_field} = {condition_value}）将删除全部 {to_delete} 个要素，操作已取消"

        geojson_data = copy.deepcopy(info["geojson"])
        geojson_data["features"] = [copy.deepcopy(features[index]) for index in remaining_indices]
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        return (f"已从图层「{layer_name}」删除 {to_delete}/{len(gdf)} 个要素"
                f"（条件：{condition_field} = {condition_value}），剩余 {len(remaining_indices)} 个，已同步地图")
    except Exception as e:
        return f"删除要素失败: {str(e)[:300]}"

@tool
def add_field(layer_name: str, field_name: str, field_type: str = "str", default_value: str = "") -> str:
    """为图层添加新字段。field_type 可选 str(文本) / int(整数) / float(小数)。
    default_value 可指定默认填充值。添加后地图自动同步。"""
    try:
        import pandas as pd

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if not isinstance(field_name, str) or not field_name.strip():
            return "字段名不能为空"
        field_name = field_name.strip()
        if field_name in ("geometry", "_fid"):
            return f"字段名「{field_name}」为保留字段，不能新增"
        if field_name in gdf.columns:
            return f"字段「{field_name}」已存在"

        field_type = field_type.lower().strip()
        if field_type not in ("str", "string", "text", "int", "integer", "float", "double", "number"):
            return f"不支持字段类型「{field_type}」，请选择 str、int 或 float"
        if field_type in ("string", "text"):
            field_type = "str"
        elif field_type in ("integer",):
            field_type = "int"
        elif field_type in ("double", "number"):
            field_type = "float"

        parsed_default = None
        if default_value != "":
            try:
                parsed_default = int(default_value) if field_type == "int" else float(default_value) if field_type == "float" else str(default_value)
            except (TypeError, ValueError):
                return f"默认值「{default_value}」无法转换为字段类型 {field_type}"
            if field_type == "float" and not math.isfinite(parsed_default):
                return "浮点字段默认值必须是有限数值"
        if field_type == "int":
            gdf[field_name] = parsed_default if parsed_default is not None else pd.Series([None] * len(gdf), dtype="object")
        elif field_type == "float":
            gdf[field_name] = parsed_default if parsed_default is not None else pd.Series([None] * len(gdf), dtype="object")
        else:
            gdf[field_name] = parsed_default if parsed_default is not None else None

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        return (f"已为图层「{layer_name}」添加字段「{field_name}」（类型：{field_type}"
                + (f"，默认值：{default_value}" if default_value != "" else "")
                + "），已同步地图")

    except Exception as e:
        return f"添加字段失败: {str(e)[:300]}"

@tool
def delete_field(layer_name: str, field_name: str) -> str:
    """删除图层的指定字段。字段删除后数据不可恢复。layer_name: 图层名；field_name: 要删除的字段名。"""
    try:
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field_name not in gdf.columns:
            return f"错误：字段「{field_name}」不存在，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

        if field_name == "geometry":
            return "不能删除 geometry 字段"
        if field_name == "_fid":
            return "_fid 是要素稳定标识，不能删除"

        gdf = gdf.drop(columns=[field_name])

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        return f"已从图层「{layer_name}」删除字段「{field_name}」，已同步地图"

    except Exception as e:
        return f"删除字段失败: {str(e)[:300]}"

@tool
def move_features(layer_name: str, dx: float = 0, dy: float = 0, unit: str = "m") -> str:
    """移动指定图层的所有要素。dx 为东西方向位移（正=东/负=西），dy 为南北方向位移（正=北/负=南）。
    unit 可选 m(米) 或 km(公里)。自动 UTM 投影保证距离精确。"""
    try:
        import geopandas as gpd
        import math
        import warnings

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        try:
            dx, dy = float(dx), float(dy)
        except (TypeError, ValueError, OverflowError):
            return "移动要素失败：位移量必须是有限数值"
        if not math.isfinite(dx) or not math.isfinite(dy):
            return "移动要素失败：位移量必须是有限数值"

        if dx == 0 and dy == 0:
            return "位移量 dx 和 dy 不能同时为 0"

        requested_dx, requested_dy = dx, dy
        if unit == "km":
            dx *= 1000
            dy *= 1000
            if not math.isfinite(dx) or not math.isfinite(dy):
                return "移动要素失败：公里换算后位移超出有限数值范围"
        elif unit != "m":
            return f"不支持的单位「{unit}」，请用 m 或 km"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
        # 用 bounds 中心确定 UTM 带号（避免 geographic CRS 下计算 centroid 的 warning）
        _b = gdf.total_bounds
        extent_error = _local_utm_extent_error(_b)
        if extent_error:
            return f"移动要素失败: {extent_error}；未修改图层"
        lon, lat = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2
        crs_utm = _get_utm_crs(lon, lat)

        gdf_utm = gdf.to_crs(crs_utm)
        gdf_utm.geometry = gdf_utm.geometry.translate(xoff=dx, yoff=dy)

        gdf_result = gdf_utm.to_crs("EPSG:4326")
        geojson_data = gdf_result.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        dir_x = "东" if dx > 0 else ("西" if dx < 0 else "")
        dir_y = "北" if dy > 0 else ("南" if dy < 0 else "")
        dir_str = (dir_y + dir_x) if (dx != 0 and dy != 0) else (dir_y or dir_x)
        unit_str = "km" if unit == "km" else "m"
        return (f"已移动图层「{layer_name}」{dir_str}方向 "
                f"（{requested_dx}{unit_str}, {requested_dy}{unit_str}），"
                f"{len(gdf_result)} 个要素，已同步地图")
    except Exception as e:
        import traceback
        return f"移动要素失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


@tool
def rotate_features(layer_name: str, angle: float = 90) -> str:
    """旋转指定图层的所有要素。angle 为旋转角度（度），正数=逆时针，负数=顺时针。旋转中心为图层所有要素的几何中心。"""
    try:
        import warnings

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        try:
            angle = float(angle)
        except (TypeError, ValueError, OverflowError):
            return "旋转要素失败：角度必须是有限数值"
        if not np.isfinite(angle):
            return "旋转要素失败：角度必须是有限数值"
        if angle == 0:
            return f"未旋转图层「{layer_name}」：角度为 0°，图层未修改"

        bounds = gdf.total_bounds
        extent_error = _local_utm_extent_error(bounds)
        if extent_error:
            return f"旋转要素失败: {extent_error}；未修改图层"
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        metric_crs = _get_utm_crs(lon, lat)
        gdf_metric = gdf.to_crs(metric_crs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            center = gdf_metric.dissolve().centroid.iloc[0]

        gdf_metric.geometry = gdf_metric.geometry.rotate(angle, origin=(center.x, center.y), use_radians=False)
        gdf_result = gdf_metric.to_crs("EPSG:4326")

        geojson_data = gdf_result.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        direction = "逆时针" if angle > 0 else "顺时针"
        return (f"已旋转图层「{layer_name}」{abs(angle)}°（{direction}），"
                f"{len(gdf_result)} 个要素，已同步地图")
    except Exception as e:
        import traceback
        return f"旋转要素失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


@tool
def scale_features(layer_name: str, x_factor: float = 1, y_factor: float = 1) -> str:
    """缩放指定图层的所有要素。x_factor 为 X 轴缩放倍数，y_factor 为 Y 轴缩放倍数。缩放中心为图层几何中心。大于 1 放大，小于 1 缩小。"""
    try:
        import geopandas as gpd
        import math
        import warnings

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        try:
            x_factor, y_factor = float(x_factor), float(y_factor)
        except (TypeError, ValueError, OverflowError):
            return "缩放倍数必须是有限且大于 0 的数值"
        if not math.isfinite(x_factor) or not math.isfinite(y_factor) or x_factor <= 0 or y_factor <= 0:
            return "缩放倍数必须大于 0"

        bounds = gdf.total_bounds
        extent_error = _local_utm_extent_error(bounds)
        if extent_error:
            return f"缩放要素失败: {extent_error}；未修改图层"
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        gdf_metric = gdf.to_crs(_get_utm_crs(lon, lat))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            center = gdf_metric.dissolve().centroid.iloc[0]

        bounds_metric = gdf_metric.total_bounds
        max_x = max(abs(bounds_metric[0]), abs(bounds_metric[2]), abs(center.x), 1.0)
        max_y = max(abs(bounds_metric[1]), abs(bounds_metric[3]), abs(center.y), 1.0)
        safe_x_factor = (sys.float_info.max / 2) / max_x
        safe_y_factor = (sys.float_info.max / 2) / max_y
        if x_factor > safe_x_factor or y_factor > safe_y_factor:
            return "缩放要素失败：比例因子会导致坐标溢出，未修改图层"
        gdf_metric.geometry = gdf_metric.geometry.scale(
            xfact=x_factor, yfact=y_factor, origin=(center.x, center.y))

        scaled_bounds = gdf_metric.total_bounds
        if not all(math.isfinite(float(value)) for value in scaled_bounds):
            return "缩放要素失败：缩放结果包含非有限坐标，未修改图层"
        gdf = gdf_metric.to_crs("EPSG:4326")


        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        return (f"已缩放图层「{layer_name}」（X: {x_factor}倍, Y: {y_factor}倍），"
                f"{len(gdf)} 个要素，已同步地图")
    except Exception as e:
        import traceback
        return f"缩放要素失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"












@tool
def spatial_select_by_attribute(layer_name: str, field: str, operator: str, value: str) -> str:
    """按属性条件选择要素。支持操作符：=(等于) / !=(不等于) / >(大于) / >=(大于等于) / <(小于) / <=(小于等于) / like(包含) / between(介于,值格式"min,max")。
    将匹配要素复制为新图层，不修改原始数据。layer_name: 图层名；field: 字段名；operator: 操作符；value: 比较值。"""
    try:
        import geopandas as gpd
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"错误：图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        ops = {
            "=": "eq", "eq": "eq",
            "!=": "ne", "neq": "ne",
            ">": "gt", "gt": "gt",
            ">=": "gte", "gte": "gte",
            "<": "lt", "lt": "lt",
            "<=": "lte", "lte": "lte",
            "like": "like",
            "between": "between",
        }
        op_norm = ops.get(operator.lower() if operator else "")
        if op_norm is None:
            return f"错误：不支持的操作符「{operator}」，支持：= != > >= < <= like between"

        field_data = gdf[field]
        is_numeric = field_data.dtype.kind in ('i', 'u', 'f')

        if op_norm == "like":
            mask = field_data.astype(str).str.contains(value, case=False, na=False, regex=False)
        elif op_norm == "between":
            parts = value.split(",")
            if len(parts) != 2:
                return "错误：between 格式为「min,max」，如「0,100」"
            try:
                vmin, vmax = (_parse_numeric_condition(part, field_data.dtype.kind) for part in parts)
            except ValueError:
                return f"错误：between 值必须为数字，当前：{value}"
            if not is_numeric:
                return f"错误：字段「{field}」不是数值类型，不支持 between"
            if any(isinstance(bound, float) and not math.isfinite(bound) for bound in (vmin, vmax)):
                return "错误：between 值必须是有限数字"
            if vmin > vmax:
                return "错误：between 下限不能大于上限"
            mask = (field_data >= vmin) & (field_data <= vmax)
        else:
            if is_numeric:
                try:
                    v = _parse_numeric_condition(value, field_data.dtype.kind)
                except ValueError:
                    return f"错误：字段「{field}」为数值类型，但条件值「{value}」无法转为数字"
                if isinstance(v, float) and not math.isfinite(v):
                    return f"错误：字段「{field}」的条件值必须为有限数字"
                if op_norm == "eq":
                    mask = field_data == v
                elif op_norm == "ne":
                    mask = field_data != v
                elif op_norm == "gt":
                    mask = field_data > v
                elif op_norm == "gte":
                    mask = field_data >= v
                elif op_norm == "lt":
                    mask = field_data < v
                elif op_norm == "lte":
                    mask = field_data <= v
                else:
                    return f"错误：不支持的数值操作符：{operator}"
            else:
                if op_norm in ("gt", "gte", "lt", "lte", "between"):
                    return f"错误：字段「{field}」不是数值类型，不支持「{operator}」操作"
                if op_norm == "eq":
                    mask = field_data == value
                elif op_norm == "ne":
                    mask = field_data != value
                else:
                    return f"错误：不支持的字符串操作符：{operator}"

        mask = mask.fillna(False) & field_data.notna()
        result = gdf[mask].copy()
        if result.empty:
            return f"没有满足条件（{field} {operator} {value}）的要素"

        result_name = f"{name}_按{field}{operator}{value}"
        _gdf_to_layer(result, result_name)
        return (f"按属性条件（{field} {operator} {value}）选择了 {len(result)}/{len(gdf)} 个要素，"
                f"已加载到地图：{result_name}")
    except Exception as e:
        import traceback
        return f"按属性选择失败: {str(e)[:300]}"


@tool
def topology_check(layer_name: str) -> str:
    """只读检查面图层的无效几何、要素间重叠与缝隙，并生成问题标记图层。
    不修改源图层；修复无效几何请调用 spatial_fix_geometry。
    - layer_name: 待检查的面图层名。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if not any(gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])):
            return f"图层 '{name}' 不含面要素，拓扑检查仅支持面图层"
        from shapely.validation import explain_validity
        from shapely.geometry import Polygon
        import shapely.wkt
        issues = []
        gdf_single = gdf.copy()
        if 'geometry' in gdf_single.columns:
            gdf_single = gdf_single.set_geometry('geometry')
        for idx, row in gdf_single.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                issues.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"type": "空几何", "fid": int(idx)}
                })
                continue
            if not geom.is_valid:
                reason = explain_validity(geom)
                rep = geom.representative_point()
                issues.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                    "properties": {"type": "无效几何", "detail": reason, "fid": int(idx)}
                })
        # 重叠和缝隙
        if len(gdf_single) >= 2:
            from shapely.ops import unary_union
            polys = [(i, g) for i, g in gdf_single.geometry.items()
                     if g is not None and not g.is_empty and g.geom_type in ("Polygon", "MultiPolygon")]
            for i, a in polys:
                for j, b in polys:
                    if j <= i:
                        continue
                    if a.intersects(b) and not a.touches(b):
                        try:
                            inter = a.intersection(b)
                            if inter is not None and not inter.is_empty and inter.area > 1e-10:
                                rep = inter.representative_point()
                                issues.append({
                                    "type": "Feature",
                                    "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                                    "properties": {"type": "重叠", "fid_pair": f"{i}-{j}"}
                                })
                        except Exception:
                            pass
            try:
                all_valid = [g for _, g in polys]
                if len(all_valid) >= 2:
                    merged = unary_union(all_valid)
                    envelope = Polygon(merged.exterior)
                    gaps = envelope.difference(merged)
                    if gaps is not None and not gaps.is_empty:
                        # 面积计算：若为地理CRS，转换到EPSG:6933等面积投影
                        _src_crs = gdf.crs
                        _is_geographic = _src_crs is not None and _src_crs.is_geographic
                        def _gap_area(geom):
                            if _is_geographic:
                                from shapely.ops import transform
                                from pyproj import Transformer
                                _t = Transformer.from_crs(_src_crs, "EPSG:6933", always_xy=True)
                                return transform(_t.transform, geom).area
                            return geom.area
                        if gaps.geom_type == "GeometryCollection":
                            for g in gaps.geoms:
                                if not g.is_empty and g.geom_type in ("Polygon",) and g.area > 1e-10:
                                    rep = g.representative_point()
                                    issues.append({
                                        "type": "Feature",
                                        "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                                        "properties": {"type": "缝隙", "area_m2": round(_gap_area(g), 2)}
                                    })
                        elif gaps.geom_type == "Polygon" and gaps.area > 1e-10:
                            rep = gaps.representative_point()
                            issues.append({
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                                "properties": {"type": "缝隙", "area_m2": round(_gap_area(gaps), 2)}
                            })
            except Exception:
                pass
        if not issues:
            return f"图层 '{name}' 未发现拓扑错误"
        fc = {"type": "FeatureCollection", "features": issues}
        with _state_lock:
            out_name = _disambiguate_layer_name(f"{name}_拓扑错误")
            _push_layer(out_name, fc)
            _register_layer(out_name, fc)
        return (f"拓扑检查完成，发现 {len(issues)} 个问题，已生成问题标记图层 '{out_name}'；"
                "源图层未修改。修复无效几何请使用 spatial_fix_geometry。")
    except Exception as e:
        return f"拓扑检查失败: {str(e)[:300]}"


@tool
def spatial_fix_geometry(layer_name: str) -> str:
    """批量修复图层中的无效几何（自相交多边形、环断裂等），生成修复后的新图层。
    - layer_name: 待修复的矢量图层名。生成含 fix_status('fixed'/'original'/'failed') 字段的新图层上图。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        from shapely.validation import make_valid
        import numpy as np
        fixed = 0
        failed = 0
        statuses = []
        new_geoms = []
        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                statuses.append("original")
                new_geoms.append(geom)
                continue
            if geom.is_valid:
                statuses.append("original")
                new_geoms.append(geom)
                continue
            try:
                new = make_valid(geom)
                if new is not None and not new.is_empty:
                    statuses.append("fixed")
                    new_geoms.append(new)
                    fixed += 1
                else:
                    statuses.append("failed")
                    new_geoms.append(geom)
                    failed += 1
            except Exception:
                statuses.append("failed")
                new_geoms.append(geom)
                failed += 1
        import geopandas as gpd
        result = gdf.copy()
        result.geometry = new_geoms
        result["fix_status"] = statuses
        result_name = f"{name}_修复"
        _gdf_to_layer(result, result_name)
        total = len(gdf)
        return f"几何修复完成：{total} 个要素中，{fixed} 个已修复，{failed} 个修复失败（保留原几何），其余原本有效。已加载到地图（含 fix_status 字段）"
    except Exception as e:
        return f"几何修复失败: {str(e)[:300]}"


@tool
def spatial_check_duplicates(layer_name: str, fields: str = "") -> str:
    """检测图层中的重复要素。
    - layer_name: 图层名。
    - fields: 逗号分隔的属性字段列表（如 'id,name'）；若为空则直接按几何完全一致查重。返回重复统计并标图。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        if fields.strip():
            cols = [x.strip() for x in fields.split(",") if x.strip()]
            miss = [c for c in cols if c not in gdf.columns]
            if miss:
                return f"错误：字段不存在：{', '.join(miss)}，可用：{', '.join(gdf.columns.tolist())}"
            dup_mask = gdf.duplicated(subset=cols, keep=False)
            n_dup = int(dup_mask.sum())
            n_groups = len(gdf[dup_mask].groupby(cols))
            if n_dup == 0:
                return f"未发现重复要素（按字段 {', '.join(cols)} 检查，共 {len(gdf)} 个要素）"
            return f"发现重复要素：{n_dup} 个要素组成 {n_groups} 个重复组（按字段 {', '.join(cols)}）"
        # 几何重复
        wkb = gdf.geometry.to_wkb()
        import collections
        counter = collections.Counter(wkb.tolist())
        dup_wkbs = {k for k, v in counter.items() if v > 1}
        if not dup_wkbs:
            return f"未发现几何完全相同的重复要素（共 {len(gdf)} 个要素）"
        dup_idx = [i for i, w in enumerate(wkb.tolist()) if w in dup_wkbs]
        # 生成标记图层
        import geopandas as gpd
        result = gdf.iloc[dup_idx].copy()
        result["is_duplicate"] = True
        result_name = f"{name}_重复要素"
        _gdf_to_layer(result, result_name)
        n_groups = len(dup_wkbs)
        return f"发现 {len(dup_idx)} 个重复要素（{n_groups} 组几何完全相同），已加载到地图（图层「{result_name}」）"
    except Exception as e:
        return f"重复检测失败: {str(e)[:300]}"


@tool
def spatial_explode(layer_name: str) -> str:
    """分解多部件要素（Multi* → 单部件）：每个组成部分变成独立要素，
    属性保留，结果作为新图层上图。拓扑清洗/逐要素符号化前常用。"""
    gdf, name = _layer_to_gdf(layer_name)
    if gdf is None:
        return name
    try:
        out = gdf.explode(index_parts=False).reset_index(drop=True)
        with _state_lock:
            out_name = _disambiguate_layer_name(f"{name}_分解")
            _gdf_to_layer(out, out_name)
        return f"已分解多部件要素：{len(gdf)} → {len(out)} 个要素，结果图层「{out_name}」已上图"
    except Exception as e:
        return f"分解失败: {str(e)[:300]}"


@tool
def geometry_convert(layer_name: str, target_type: str = "lines") -> str:
    """几何类型互转/提取，结果作为新图层上图。target_type 可选：
    lines（面→边界线）、polygons（线→面，要求构成闭合环）、
    convex_hull（凸包）、bounding_box（最小外接矩形）。"""
    gdf, name = _layer_to_gdf(layer_name)
    if gdf is None:
        return name
    t = str(target_type).strip().lower()
    try:
        attribute_notice = ""
        import geopandas as gpd
        from shapely.geometry import LineString, Point, box as shp_box
        if t == "lines":
            if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
                return "面转边界线失败：输入图层包含空几何，请先清理"
            if not gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
                return "错误：面转边界线仅支持 Polygon/MultiPolygon 图层"
            out = gdf.copy()
            out["geometry"] = gdf.geometry.boundary
        elif t == "polygons":
            from shapely.ops import polygonize, unary_union
            polys = list(polygonize(unary_union(gdf.geometry.values)))
            if not polys:
                return "错误：线要素无法多边形化（未构成闭合环），请检查几何"
            out = gpd.GeoDataFrame(geometry=polys, crs=gdf.crs)
            attribute_notice = "；结果仅包含新几何，源线属性未继承"
        elif t == "convex_hull":
            union_geom = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.geometry.unary_union
            hull = union_geom.convex_hull
            out = gpd.GeoDataFrame(geometry=[hull], crs=gdf.crs)
            attribute_notice = "；结果仅包含聚合几何，源要素属性未继承"
        elif t == "bounding_box":
            minx, miny, maxx, maxy = gdf.total_bounds
            import math
            if not all(math.isfinite(float(value)) for value in (minx, miny, maxx, maxy)):
                return "外接矩形失败：输入图层没有有效几何"
            if minx == maxx and miny == maxy:
                extent = Point(minx, miny)
            elif minx == maxx or miny == maxy:
                extent = LineString([(minx, miny), (maxx, maxy)])
            else:
                extent = shp_box(minx, miny, maxx, maxy)
            out = gpd.GeoDataFrame(geometry=[extent], crs=gdf.crs)
            attribute_notice = "；结果仅包含外接范围几何，源要素属性未继承"
        else:
            return f"错误：未知 target_type: {target_type}，可选 lines/polygons/convex_hull/bounding_box"
        out_name = f"{name}_{t}"
        with _state_lock:
            occupied_names = set(_registered_layers)
            occupied_names.update(
                item.get("name") for item in _pending_layers if isinstance(item.get("name"), str)
            )
            base_name = out_name
            suffix = 1
            while out_name in occupied_names:
                out_name = f"{base_name}_{suffix}"
                suffix += 1
            _gdf_to_layer(out, out_name)
        return f"几何转换完成（{t}）：{len(out)} 个要素，结果图层「{out_name}」已上图{attribute_notice}"
    except Exception as e:
        return f"几何转换失败: {str(e)[:300]}"


@tool
def join_field(target_layer: str, join_layer: str, target_field: str, join_field: str, fields: str = "", how: str = "left") -> str:
    """按公共属性键连接图层（属性连接，不是空间连接）。
    - target_layer/join_layer: 目标图层与数据源图层名。
    - target_field/join_field: 两侧连接键字段名。
    - fields: 逗号分隔要带入的字段，留空=数据源除连接键外全部字段。
    - how: 'left'(保留全部目标要素,未匹配为 NaN,默认) 或 'inner'(仅匹配)。
    同名冲突字段重命名为「名字_join」；键唯一时 validate 防行倍增；结果作为新图层上图。"""
    try:
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None:
            return name_t
        gdf_j, name_j = _layer_to_gdf(join_layer)
        if gdf_j is None:
            return name_j

        how_key = str(how or "left").strip().lower()
        if how_key not in ("left", "inner"):
            return f"错误：how 只能为 'left' 或 'inner'，收到：{how}"

        if target_field not in gdf_t.columns:
            cols = ", ".join(c for c in gdf_t.columns if c != "geometry")
            return f"错误：目标图层「{name_t}」中不存在字段「{target_field}」，可用字段：{cols}"
        if join_field not in gdf_j.columns:
            cols = ", ".join(c for c in gdf_j.columns if c != "geometry")
            return f"错误：数据源图层「{name_j}」中不存在字段「{join_field}」，可用字段：{cols}"

        target_cols = [c for c in gdf_t.columns if c != "geometry"]
        join_cols = [c for c in gdf_j.columns if c != "geometry" and c != join_field]
        if str(fields or "").strip():
            wanted = [f.strip() for f in str(fields).split(",") if f.strip()]
            missing = [f for f in wanted if f not in join_cols]
            if missing:
                return f"错误：数据源图层「{name_j}」中不存在字段：{', '.join(missing)}，可用字段：{', '.join(join_cols)}"
            bring = wanted
        else:
            bring = list(join_cols)
        if not bring:
            return f"错误：数据源图层「{name_j}」除连接键外没有可带入的字段"

        collisions = [c for c in bring if c in target_cols]
        rename = {}
        used = set(target_cols) | set(bring)
        for c in collisions:
            new = f"{c}_join"
            i = 2
            while new in used:
                new = f"{c}_join{i}"
                i += 1
            rename[c] = new
            used.add(new)

        right_keys = gdf_j[join_field].dropna().unique()
        matched = int(gdf_t[target_field].isin(right_keys).sum())
        unmatched = int(len(gdf_t) - matched)
        # Null keys are not joinable values: ignore them both for cardinality
        # validation and on the right side, since pandas otherwise matches NaN
        # keys together and can multiply rows unexpectedly.
        target_keys = gdf_t[target_field].dropna()
        join_keys = gdf_j[join_field].dropna()
        duplicate_t = bool(target_keys.duplicated().any())
        duplicate_j = bool(join_keys.duplicated().any())
        if not duplicate_t and not duplicate_j:
            validate = "one_to_one"
        elif not duplicate_j:
            validate = "many_to_one"
        elif not duplicate_t:
            validate = "one_to_many"
        else:
            validate = "many_to_many"

        keep_cols = [join_field] + [c for c in bring if c != join_field]
        join_sub = gdf_j.loc[gdf_j[join_field].notna(), keep_cols].copy()
        if rename:
            join_sub = join_sub.rename(columns=rename)
        # Pandas treats null merge keys as equal to each other. Give every null
        # target key a unique temporary value so repeated nulls remain separate
        # unmatched rows while the cardinality validator still checks real keys.
        target_for_merge = gdf_t.reset_index(drop=True).copy()
        null_target_keys = target_for_merge[target_field].isna()
        null_marker = "__wtb_null_join_key__"
        while null_marker in target_for_merge.columns:
            null_marker += "_"
        target_for_merge[null_marker] = null_target_keys.to_numpy()
        target_for_merge[target_field] = target_for_merge[target_field].astype(object)
        target_for_merge.loc[null_target_keys, target_field] = [
            object() for _ in range(int(null_target_keys.sum()))
        ]
        join_sub[join_field] = join_sub[join_field].astype(object)
        result = target_for_merge.merge(join_sub, left_on=target_field, right_on=join_field,
                             how=how_key, validate=validate, suffixes=("", "_join"))
        result.loc[result[null_marker], target_field] = None
        result = result.drop(columns=[null_marker])
        if join_field != target_field and join_field in result.columns:
            result = result.drop(columns=[join_field])

        base_result_name = f"{name_t}_连接{name_j}"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(result, result_name)
        collision_note = ""
        if rename:
            collision_note = "；冲突字段已重命名：" + ", ".join(f"{k}->{v}" for k, v in rename.items())
        return (f"属性连接完成（{how_key}，validate={validate}）：目标 {len(gdf_t)} 个要素，"
                f"匹配 {matched}，未匹配 {unmatched}，结果 {len(result)} 个要素{collision_note}，"
                f"结果图层「{result_name}」已上图")
    except Exception as e:
        return f"属性连接失败: {str(e)[:300]}"


@tool
def geometry_attributes(layer_name: str, metrics: str = "area,length,perimeter,centroid") -> str:
    """为图层逐要素添加几何量测字段（几何不变，结果作为新图层上图）。
    - layer_name: 待计算矢量图层名。
    - metrics: 逗号分隔量测项，默认 'area,length,perimeter,centroid'。可选 area(投影面积 m2)、
      length(线/面长度 m)、perimeter(面周长 m)、centroid(展开 centroid_x/y)、bbox(展开
      bbox_minx/miny/maxx/maxy)，以及各 centroid_x、bbox_minx 单项。
    经纬度下面积/长度为度/度：自动估算 UTM 投影带后在投影坐标计算，返回串会说明所用投影；
    投影估算失败则直接报错。"""
    try:
        import geopandas as gpd
        import numpy as np

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"错误：图层「{name}」为空"

        raw = str(metrics or "").strip()
        if not raw:
            return "错误：metrics 不能为空，可选：area,length,perimeter,centroid,bbox"
        items = [m.strip().lower() for m in raw.split(",") if m.strip()]
        allowed = {"area", "length", "perimeter", "centroid", "centroid_x", "centroid_y",
                   "bbox", "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"}
        bad = [m for m in items if m not in allowed]
        if bad:
            return f"错误：不支持的 metrics 项：{', '.join(bad)}，可选：{', '.join(sorted(allowed))}"

        crs = gdf.crs
        is_geographic = bool(crs is not None and crs.is_geographic)
        if is_geographic:
            utm = gdf.estimate_utm_crs()
            if utm is None:
                return "错误：无法估算 UTM 投影带（图层范围异常），无法计算面积/长度"
            metric_gdf = gdf.to_crs(utm)
            crs_note = f"图层为地理坐标系（{crs.to_string()}），面积/长度/周长已在 UTM {utm.to_string()} 投影下计算"
        else:
            metric_gdf = gdf
            crs_note = f"按图层原投影 {crs.to_string() if crs is not None else '未定义'} 计算"

        out = gdf.copy()
        geom = metric_gdf.geometry
        want = set(items)
        added = []

        if "area" in want:
            out["area"] = geom.area.astype(float)
            added.append("area")
        if "length" in want:
            out["length"] = geom.length.astype(float)
            added.append("length")
        if "perimeter" in want:
            is_poly = geom.geom_type.isin(["Polygon", "MultiPolygon"])
            out["perimeter"] = geom.length.where(is_poly, np.nan).astype(float)
            added.append("perimeter")

        need_cx = "centroid" in want or "centroid_x" in want
        need_cy = "centroid" in want or "centroid_y" in want
        if need_cx or need_cy:
            cents = geom.centroid
            if need_cx:
                out["centroid_x"] = cents.x.astype(float)
                added.append("centroid_x")
            if need_cy:
                out["centroid_y"] = cents.y.astype(float)
                added.append("centroid_y")

        b = geom.bounds
        need_bbox = "bbox" in want
        for bn, col in zip(["bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"],
                           ["minx", "miny", "maxx", "maxy"]):
            if need_bbox or bn in want:
                out[bn] = b[col].astype(float)
                added.append(bn)

        base_out_name = f"{name}_几何属性"
        with _state_lock:
            out_name = _disambiguate_layer_name(base_out_name)
            _gdf_to_layer(out, out_name)
        return (f"几何属性计算完成（{crs_note}）：新增字段 {', '.join(added)}，"
                f"结果图层「{out_name}」已上图")
    except Exception as e:
        return f"几何属性计算失败: {str(e)[:300]}"


@tool
def minimum_bounding_geometry(layer_name: str, kind: str = "envelope", group_field: str = "") -> str:
    """计算图层（或分组后）的最小外包几何，结果作为新图层上图。
    - layer_name: 输入矢量图层名。
    - kind: 'envelope'(轴对齐包络,默认) / 'convex_hull'(凸包) / 'circle'(最小外接圆,
      输出 center_x/y、radius_m、radius_km) / 'oriented_bbox'(最小面积定向矩形,输出 length_m、width_m)。
    - group_field: 可选分组字段，留空=整层一个外包几何，给出时按该字段融合、每组一个几何；
      字段不存在时明确报错并列出可用字段。
    circle 半径与 oriented_bbox 边长在 UTM 投影下按米计算，结果几何转回原坐标系上图。"""
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"错误：图层「{name}」为空"

        kind_key = str(kind or "envelope").strip().lower()
        kind_map = {
            "envelope": "envelope", "bbox": "envelope", "extent": "envelope",
            "convex_hull": "convex_hull", "hull": "convex_hull", "convexhull": "convex_hull",
            "circle": "circle", "minimum_bounding_circle": "circle", "mbc": "circle",
            "oriented_bbox": "oriented_bbox", "oriented": "oriented_bbox",
            "rotated_bbox": "oriented_bbox", "obb": "oriented_bbox",
        }
        if kind_key not in kind_map:
            return f"错误：不支持的 kind：{kind}，可选 envelope/convex_hull/circle/oriented_bbox"
        kind_key = kind_map[kind_key]
        suffix_map = {"envelope": "_包络", "convex_hull": "_凸包",
                      "circle": "_最小外接圆", "oriented_bbox": "_定向外接矩形"}

        crs = gdf.crs
        is_geographic = bool(crs is not None and crs.is_geographic)
        need_proj = kind_key in ("circle", "oriented_bbox")
        if need_proj and is_geographic:
            utm = gdf.estimate_utm_crs()
            if utm is None:
                return "错误：无法估算 UTM 投影带（图层范围异常），无法计算圆/定向矩形"
            work = gdf.to_crs(utm)
        else:
            utm = None
            work = gdf

        def _one(geom):
            if kind_key == "envelope":
                return geom.envelope, {}
            if kind_key == "convex_hull":
                return geom.convex_hull, {}
            if kind_key == "oriented_bbox":
                rect = geom.minimum_rotated_rectangle
                if rect.is_empty:
                    return rect, {}
                coords = list(rect.exterior.coords)
                sides = [((coords[i + 1][0] - coords[i][0]) ** 2 +
                          (coords[i + 1][1] - coords[i][1]) ** 2) ** 0.5 for i in range(4)]
                return rect, {"length_m": float(max(sides)), "width_m": float(min(sides))}
            try:
                from shapely import minimum_bounding_circle
                circ = minimum_bounding_circle(geom)
                cx, cy = float(circ.centroid.x), float(circ.centroid.y)
                pts = list(circ.exterior.coords)[:-1]
                radius = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in pts) if pts else 0.0
            except Exception:
                hull = geom.convex_hull
                c = hull.centroid
                cx, cy = float(c.x), float(c.y)
                pts = list(hull.exterior.coords)[:-1] if hull.geom_type == "Polygon" else []
                radius = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in pts) if pts else 0.0
                circ = Point(cx, cy).buffer(radius, quad_segs=64)
            return circ, {"center_x": float(cx), "center_y": float(cy),
                          "radius_m": float(radius), "radius_km": float(radius) / 1000.0}

        if str(group_field or "").strip():
            gf = str(group_field).strip()
            if gf not in work.columns:
                cols = ", ".join(c for c in work.columns if c != "geometry")
                return f"错误：未找到分组字段「{gf}」，可用字段：{cols}"
            rows, geoms = [], []
            for key, sub in work.groupby(gf, dropna=False):
                merged = sub.geometry.union_all()
                geom, extra = _one(merged)
                row = {gf: key, "feature_count": int(len(sub))}
                row.update(extra)
                rows.append(row)
                geoms.append(geom)
            if not geoms:
                return f"错误：图层「{name}」没有可计算的分组"
            out = gpd.GeoDataFrame(rows, geometry=geoms, crs=work.crs)
            out_name = f"{name}_按{gf}{suffix_map[kind_key]}"
        else:
            merged = work.geometry.union_all()
            geom, extra = _one(merged)
            row = {"feature_count": int(len(work))}
            row.update(extra)
            out = gpd.GeoDataFrame([row], geometry=[geom], crs=work.crs)
            out_name = f"{name}{suffix_map[kind_key]}"

        if need_proj and is_geographic:
            out = out.to_crs(crs)
            note = f"（圆/定向边在 UTM {utm.to_string()} 下按米计算，几何已转回 {crs.to_string()}）"
        else:
            note = f"（按 {work.crs.to_string() if work.crs is not None else '未定义坐标系'} 计算）"
        with _state_lock:
            out_name = _disambiguate_layer_name(out_name)
            _gdf_to_layer(out, out_name)
        extra_txt = f"，半径 {float(out['radius_m'].iloc[0]):.3f} m" if (kind_key == "circle" and len(out)) else ""
        return f"最小外包几何完成（{kind_key}{extra_txt}）：{len(out)} 个要素，结果图层「{out_name}」已上图{note}"
    except Exception as e:
        return f"最小外包几何失败: {str(e)[:300]}"


@tool
def points_to_line(layer_name: str, group_field: str, order_field: str = "", close_ring: bool = False) -> str:
    """把点图层按分组字段连成线，结果作为新图层上图。
    - layer_name: 输入点图层名。
    - group_field: 分组字段名，同一取值连成一条线；不存在时明确报错并列出可用字段。
    - order_field: 可选排序字段，给出时组内按它升序连线，留空=原顺序。
    - close_ring: True 把首点追加到末尾闭合成环，False(默认)不闭合。
    少于 2 个有效点的分组会被跳过并报告；MultiPoint 会先拆成单点再连线。"""
    try:
        import geopandas as gpd
        from shapely.geometry import LineString

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"错误：图层「{name}」为空"

        gf = str(group_field or "").strip()
        if not gf:
            return "错误：group_field 不能为空"
        if gf not in gdf.columns:
            cols = ", ".join(c for c in gdf.columns if c != "geometry")
            return f"错误：未找到分组字段「{gf}」，可用字段：{cols}"
        of = str(order_field or "").strip()
        if of and of not in gdf.columns:
            cols = ", ".join(c for c in gdf.columns if c != "geometry")
            return f"错误：未找到排序字段「{of}」，可用字段：{cols}"

        work = gdf if not of else gdf.sort_values(of, kind="stable")
        grouped = {}
        for _, row in work.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            if geom.geom_type == "Point":
                pts = [geom]
            elif geom.geom_type == "MultiPoint":
                pts = list(geom.geoms)
            else:
                continue
            for pt in pts:
                grouped.setdefault(row[gf], []).append(pt)

        lines, attrs, skipped = [], [], 0
        for gval, pts in grouped.items():
            if len(pts) < 2:
                skipped += 1
                continue
            coords = [(float(p.x), float(p.y)) for p in pts]
            if bool(close_ring) and coords[0] != coords[-1]:
                coords = coords + [coords[0]]
            try:
                line = LineString(coords)
            except Exception:
                skipped += 1
                continue
            lines.append(line)
            attrs.append({gf: gval, "point_count": int(len(pts)), "closed": bool(close_ring)})

        if not lines:
            return f"错误：没有可连线的分组（共 {len(grouped)} 个分组，全部少于 2 个有效点），未生成图层"
        out = gpd.GeoDataFrame(attrs, geometry=lines, crs=gdf.crs)
        try:
            utm = out.estimate_utm_crs()
            if utm is not None:
                out["length_m"] = out.to_crs(utm).geometry.length.astype(float)
        except Exception:
            pass
        with _state_lock:
            out_name = _disambiguate_layer_name(f"{name}_点转线")
            _gdf_to_layer(out, out_name)
        return f"点转线完成：生成 {len(out)} 条线，跳过 {skipped} 个点不足 2 的分组，结果图层「{out_name}」已上图"
    except Exception as e:
        return f"点转线失败: {str(e)[:300]}"


@tool
def generate_points_along_lines(layer_name: str, interval: float = 100, unit: str = "m") -> str:
    """沿每条线按固定间隔生成点，结果作为新图层上图。
    - layer_name: 输入线图层名。
    - interval: 点间隔，正数，默认 100；单位由 unit 指定。
    - unit: 'm'(米,默认) 或 'km'(千米)。
    在距起点 interval、2*interval... 处取点（不含起点；整倍数时含终点）；短于一个间隔的线不产点。
    长度与间隔在 UTM 投影下按米计算，结果点转回原坐标系；返回总点数与覆盖线长。"""
    try:
        import geopandas as gpd
        import numpy as np

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"错误：图层「{name}」为空"
        try:
            iv = float(interval)
        except Exception:
            return f"错误：interval 必须是数字，收到：{interval}"
        if not np.isfinite(iv) or iv <= 0:
            return f"错误：interval 必须为正数，收到：{interval}"
        unit_key = str(unit or "m").strip().lower()
        if unit_key in ("m", "meter", "meters", "米"):
            iv_m = iv
            unit_note = f"{iv:g} m"
        elif unit_key in ("km", "kilometer", "kilometers", "千米", "公里"):
            iv_m = iv * 1000.0
            unit_note = f"{iv:g} km（{iv_m:g} m）"
        else:
            return f"错误：unit 只能为 'm' 或 'km'，收到：{unit}"

        work = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        work = work[work.geometry.geom_type.isin(["LineString", "MultiLineString"])]
        if work.empty:
            return f"错误：图层「{name}」中没有有效线要素"

        crs = gdf.crs
        is_geographic = bool(crs is not None and crs.is_geographic)
        if is_geographic:
            utm = gdf.estimate_utm_crs()
            if utm is None:
                return "错误：无法估算 UTM 投影带（图层范围异常），无法按米生成点"
            proj = work.to_crs(utm)
        else:
            utm = None
            proj = work
        proj = proj.explode(index_parts=False)

        total_pts, covered_m, total_len_m = 0, 0.0, 0.0
        pt_geoms, attrs = [], []
        for idx, row in proj.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty or geom.geom_type != "LineString":
                continue
            L = float(geom.length)
            total_len_m += L
            if L < iv_m:
                continue
            dists = np.arange(iv_m, L + 1e-9, iv_m)
            for d in dists:
                try:
                    pt = geom.interpolate(float(d))
                except Exception:
                    continue
                if pt is None or pt.is_empty:
                    continue
                pt_geoms.append(pt)
                attrs.append({"source_index": int(idx) if isinstance(idx, (int, np.integer)) else str(idx),
                              "dist_m": float(d), "line_length_m": L})
                total_pts += 1
            if len(dists):
                covered_m += float(min(float(dists[-1]), L))

        if not pt_geoms:
            return f"沿线生成等距点：线总长 {total_len_m:,.2f} m，均短于一个间隔（{unit_note}），未生成点"
        out = gpd.GeoDataFrame(attrs, geometry=pt_geoms, crs=proj.crs)
        if is_geographic:
            out = out.to_crs(crs)
        with _state_lock:
            out_name = _disambiguate_layer_name(f"{name}_沿线等距点")
            _gdf_to_layer(out, out_name)
        return (f"沿线生成等距点完成（间隔 {unit_note}）：共 {total_pts} 个点，"
                f"覆盖线长 {covered_m:,.2f} m（线总长 {total_len_m:,.2f} m），"
                f"结果图层「{out_name}」已上图")
    except Exception as e:
        return f"沿线生成等距点失败: {str(e)[:300]}"


@tool
def spatial_weights_matrix(layer_name: str, method: str = "queen", k: int = 8) -> str:
    """构建并持久化空间权重矩阵（邻接矩阵）文件产物，供用户独立查看或下载。
    - layer_name: 图层名；queen/rook 邻接需要面图层，点/线图层请改用 method='knn'。
    - method: 'queen'(共享边或顶点，默认) / 'rook'(仅共享边) / 'knn'(K 近邻)。
    - k: knn 的近邻数（默认 8，自动收敛到 N-1）；knn 在本地 UTM 米制投影坐标上计算，避免经纬度欧氏距离失真。
    产出：<临时输出目录>/stats/weights/<图层>_<method>.npz（scipy 稀疏矩阵）与同名 .json 邻居表，并返回要素数与平均邻居数。
    注意：本工具只产出磁盘文件而非地图图层。"""
    try:
        import numpy as np
        from scipy import sparse

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        W, neighbors, backend = _build_spatial_weights(gdf, method=method, k=k)
        n = len(gdf)
        counts = np.array([len(v) for v in neighbors], dtype=int)
        mean_nbrs = float(counts.mean()) if n else 0.0
        out_dir = _stats_out_dir("weights")
        stem = f"{_stats_safe_name(name)}_{str(method).lower()}"
        npz_path = os.path.join(out_dir, stem + ".npz")
        json_path = os.path.join(out_dir, stem + ".json")
        sparse.save_npz(npz_path, W)
        try:
            fids = gdf["_fid"].tolist() if "_fid" in gdf.columns else None
        except Exception:
            fids = None
        sidecar = {
            "layer": name, "method": str(method).lower(), "k": int(k),
            "n_features": n, "mean_neighbors": round(mean_nbrs, 4),
            "min_neighbors": int(counts.min()) if n else 0,
            "max_neighbors": int(counts.max()) if n else 0,
            "neighbor_counts": counts.tolist(),
            "neighbors": neighbors,
            "feature_ids": fids,
            "matrix_npz": npz_path,
            "backend": backend,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(sidecar, f, ensure_ascii=False, indent=2)
        record_tool_artifact(os.path.basename(npz_path), npz_path, artifact_type="file")
        record_tool_artifact(os.path.basename(json_path), json_path, artifact_type="file")
        summary = _stats_summary("spatial_weights_matrix", {
            "layer": name, "method": str(method).lower(), "n_features": n,
            "mean_neighbors": round(mean_nbrs, 4), "backend": backend,
            "matrix": npz_path, "sidecar": json_path,
        })
        return (
            f"空间权重矩阵已生成（{str(method).lower()}，实现路径：{backend}）。\n"
            f"- 图层：{name}，要素数：{n}\n"
            f"- 平均邻居数：{mean_nbrs:.3f}（最小 {int(counts.min()) if n else 0}，最大 {int(counts.max()) if n else 0}）\n"
            f"- 稀疏矩阵：{npz_path}\n"
            f"- 邻居表：{json_path}\n"
            f"（本工具产物为磁盘文件而非地图图层；Moran、热点和回归分析当前各自构建权重，不读取此文件）\n"
            f"{summary}"
        )
    except Exception as e:
        return f"空间权重矩阵构建失败: {str(e)[:300]}"


_MAX_DENSE_SPATIAL_STATS_FEATURES = 3000


@tool
def spatial_regression(layer_name: str, dependent: str, independents: str, model: str = "ols") -> str:
    """空间回归分析：OLS + 残差空间自相关（Moran's I），检验自变量对因变量的解释力。
    - layer_name: 图层名。
    - dependent: 因变量字段名（必须为数值型）。
    - independents: 自变量字段名，英文逗号分隔（必须全部为数值型）。
    - model: 'ols'(普通最小二乘，默认) / 'gwr'(地理加权回归，暂未支持，会明确返回不支持提示)。
    输出：系数、标准误、t 值、p 值、R、调整 R、AIC、Jarque-Bera 正态性 p 值，以及残差 Moran's I（默认 queen 权重）。
    注意：本工具只产出数值结果，不生成地图图层。"""
    try:
        import numpy as np
        import pandas as pd
        from scipy import stats

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        model = str(model).lower().strip()
        if model == "gwr":
            return ("错误：gwr（地理加权回归）暂未支持：当前仅提供 OLS 探索性回归（系数/显著性/残差自相关）。"
                    "请改用 model='ols'；空间权重矩阵文件不会启用 GWR 或被 OLS 自动读取。")
        if model != "ols":
            return f"错误：不支持的 model：{model}，可选 'ols'（默认）或 'gwr'（暂未支持）"
        num_cols = set(gdf.select_dtypes(include=[np.number]).columns.tolist())
        if dependent not in gdf.columns:
            return f"错误：因变量字段「{dependent}」不存在"
        if dependent not in num_cols:
            return f"错误：因变量「{dependent}」不是数值字段，空间回归要求数值型"
        indep_list = [s.strip() for s in str(independents).split(",") if s.strip()]
        if not indep_list:
            return "错误：自变量 independents 为空，请用逗号分隔数值字段名"
        for fld in indep_list:
            if fld not in gdf.columns:
                return f"错误：自变量字段「{fld}」不存在"
            if fld not in num_cols:
                return f"错误：自变量「{fld}」不是数值字段，空间回归要求数值型"
        data = gdf[[dependent] + indep_list].apply(pd.to_numeric, errors="coerce")
        data = data.replace([np.inf, -np.inf], np.nan).dropna()
        n = len(data)
        p = len(indep_list) + 1
        if n < p + 1:
            return f"错误：有效样本数（{n}）太少，OLS 至少需要 {p + 1} 个"
        X = np.column_stack([np.ones(n), data[indep_list].values.astype(float)])
        y = data[dependent].values.astype(float)
        beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
        if rank < p:
            return "错误：OLS 设计矩阵秩不足（自变量重复或完全共线），无法可靠估计系数和显著性；请移除重复/线性相关字段后重试"
        resid = y - X @ beta
        dof = n - p
        rss = float(resid @ resid)
        tss = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - rss / tss if tss > 0 else float("nan")
        adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof if tss > 0 else float("nan")
        sigma2 = rss / dof
        try:
            se = np.sqrt(np.maximum(np.diag(np.linalg.pinv(X.T @ X)) * sigma2, 0.0))
        except Exception:
            se = np.full(p, np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            tvals = beta / se
        pvals = 2.0 * (1.0 - stats.t.cdf(np.abs(tvals), df=dof))
        aic = n * np.log(rss / n) + 2 * p if rss > 0 else float("inf")
        jb_stat, jb_p = (float("nan"), float("nan"))
        if rss > 0 and n > 2:
            try:
                jb_stat, jb_p = stats.jarque_bera(resid)
            except Exception:
                pass
        names = ["const"] + indep_list
        lines = [f"空间回归（OLS）完成，图层「{name}」，有效样本 {n} 个："]
        lines.append("  变量        系数        标准误      t 值      p 值")
        for nm, b, s, t, pv in zip(names, beta, se, tvals, pvals):
            lines.append(f"  {nm:<10} {b:>10.4f} {s:>10.4f} {t:>9.3f} {pv:>9.4f}")
        lines.append(f"  R = {r2:.4f}，调整 R = {adj_r2:.4f}，AIC = {aic:.2f}")
        if jb_p == jb_p:
            lines.append(f"  Jarque-Bera 正态性检验：统计量 = {jb_stat:.4f}，p = {jb_p:.4f}"
                         + ("（p<0.05，残差偏离正态）" if jb_p < 0.05 else "（未拒绝正态）"))
        else:
            lines.append("  Jarque-Bera 正态性检验：样本不足，已跳过")
        moran_txt = "残差 Moran's I：样本不足，已跳过"
        try:
            if n >= 5:
                sub = gdf.loc[data.index]
                # 残差自相关：面图层优先 queen 邻接；点/线图层 queen 不适用，退回 knn
                try:
                    W, _, w_backend = _build_spatial_weights(sub, method="queen", k=8)
                except Exception:
                    W, _, w_backend = _build_spatial_weights(sub, method="knn", k=8)
                mi = _moran_from_weights(W, resid)
                if mi is not None:
                    I, z, pv2, mtd = mi
                    moran_txt = (f"残差 Moran's I = {I:.4f}，z = {z:.2f}，p = {pv2:.4f}"
                                 f"（{w_backend} queen 权重，{mtd}；"
                                 + ("残差仍存在显著空间自相关" if abs(z) > 1.96 else "残差无显著空间自相关") + "）")
        except Exception as _me:
            moran_txt = f"残差 Moran's I 计算跳过：{str(_me)[:120]}"
        lines.append("  " + moran_txt)
        summary = _stats_summary("spatial_regression", {
            "layer": name, "model": "ols", "n": n,
            "coefficients": {nm: round(float(b), 6) for nm, b in zip(names, beta)},
            "r2": None if r2 != r2 else round(float(r2), 6),
            "adj_r2": None if adj_r2 != adj_r2 else round(float(adj_r2), 6),
            "aic": round(float(aic), 4) if np.isfinite(aic) else None,
        })
        lines.append(summary)
        lines.append("（本工具只产出数值结果，不生成地图图层）")
        return "\n".join(lines)
    except Exception as e:
        return f"空间回归失败: {str(e)[:300]}"


@tool
def spatial_moran(layer_name: str, field: str, weight_type: str = "distance",
                  threshold: float = 0.01, k: int = 5, local: bool = True,
                  threshold_m: float = 0.0) -> str:
    """全局 Moran's I 空间自相关 + 局部 LISA 聚类分析（仅支持点/质心数值字段）。
    - layer_name: 图层名（点要素或质心）。
    - field: 待分析的数值型属性字段。
    - weight_type: 'distance'(默认距离阈值) 或 'knn'(K近邻)。
    - threshold: 兼容旧调用的距离阈值（度）；threshold_m: 米制距离阈值（优先使用本地 UTM 投影计算）。
    - k: 近邻数(默认 5)。
    - local: 是否生成局部 LISA 聚类图层（包含 HH/LL/HL/LH 字段，默认 True）。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        if not field:
            numeric_fields = gdf.select_dtypes(include=[np.number]).columns.tolist()
            if not numeric_fields:
                return "图层没有可用于空间自相关分析的数值字段"
            field = numeric_fields[0]
        if field not in gdf.columns:
            return f"字段「{field}」不存在，可用字段：{', '.join(gdf.select_dtypes(include=[np.number]).columns.tolist()) or '无'}"
        x = gdf[field].values.astype(float)
        if np.isnan(x).any() or np.isinf(x).any():
            return "字段含空值或无穷大，请先清洗数据"
        n = len(x)
        if n < 3:
            return f"要素数（{n}）太少，至少需要 3 个"
        if n > _MAX_DENSE_SPATIAL_STATS_FEATURES:
            return f"错误：空间自相关当前最多支持 {_MAX_DENSE_SPATIAL_STATS_FEATURES} 个要素；请先聚合或抽样，避免距离矩阵耗尽内存"
        if weight_type not in ("distance", "knn"):
            return "weight_type 仅支持 distance 或 knn"
        distance_threshold = threshold
        if weight_type == "knn":
            if isinstance(k, bool) or not isinstance(k, int) or k < 1:
                return "K 近邻数必须是正整数"
            coords = _spatial_feature_coordinates(_to_local_metric_gdf(gdf))
        elif threshold_m:
            if not math.isfinite(float(threshold_m)) or float(threshold_m) <= 0:
                return "米制距离阈值必须是大于 0 的有限数值"
            metric_gdf = _to_local_metric_gdf(gdf)
            coords = _spatial_feature_coordinates(metric_gdf)
            distance_threshold = float(threshold_m)
        else:
            if not math.isfinite(float(threshold)) or float(threshold) <= 0:
                return "距离阈值必须是大于 0 的有限数值"
            distance_threshold = float(threshold)
            coords = _spatial_feature_coordinates(gdf)
        # 构建空间权重矩阵
        if weight_type == "knn":
            from sklearn.neighbors import NearestNeighbors
            k_eff = min(k, n - 1)
            nn = NearestNeighbors(n_neighbors=k_eff + 1).fit(coords)
            _, idx = nn.kneighbors(coords)
            W = np.zeros((n, n))
            for i in range(n):
                # Coincident points can tie ahead of the query itself.
                # Remove the actual index instead of assuming it is first.
                neighbors = idx[i][idx[i] != i][:k_eff]
                W[i, neighbors] = 1.0
        else:
            from scipy.spatial.distance import cdist
            d = cdist(coords, coords)
            W = (d <= distance_threshold).astype(float)
            np.fill_diagonal(W, 0.0)
        W_sum = W.sum()
        if W_sum == 0:
            return "空间权重全为零：没有任何点对在阈值内，请调大 threshold 或改用 weight_type=knn"
        # 全局 Moran's I
        z = x - x.mean()
        zz = z @ z
        if zz == 0:
            return "字段方差为零（所有值相同），无法计算空间自相关"
        I = (n / W_sum) * (z @ W @ z) / zz
        # 随机化假设下的期望与方差（Cliff & Ord）
        E_I = -1.0 / (n - 1)
        S0 = W_sum
        S1 = 0.5 * ((W + W.T) ** 2).sum()
        S2 = ((W.sum(axis=1) + W.sum(axis=0)) ** 2).sum()
        denom = (n - 1) * (n - 2) * (n - 3) * S0 * S0

        # 峰度项 b2 必须用离差 z = x - mean(x)，不是原始 x。
        # 方差主项还有一个 n 因子。这两处写错会让方差变成负数，
        # 再被 max(var, 1e-12) 兜住 → z 值爆炸 → 任何数据都判成"显著"。
        m2 = (z ** 2).mean()
        var_I = None
        if denom > 0 and n > 3 and m2 > 0:
            b2 = (z ** 4).mean() / (m2 ** 2)
            k1 = n * (S1 * (n*n - 3*n + 3) - n*S2 + 3*S0*S0) / denom
            k2 = (S1 * (n*n - n) - 2*n*S2 + 6*S0*S0) / denom
            _v = k1 - k2 * b2 - E_I * E_I
            if _v > 0:
                var_I = _v

        from scipy.stats import norm
        if var_I is not None:
            z_score = (I - E_I) / np.sqrt(var_I)
            p_value = 2.0 * (1.0 - norm.cdf(abs(z_score)))
            method = "正态近似（随机化假设）"
        else:
            # 方差算不出来时不做"假装显著"的兜底：改用置换检验
            # 固定种子保证同一份数据每次结论一致
            _rng = np.random.default_rng(20240915)
            _perm = []
            for _ in range(199):
                _xp = _rng.permutation(x)
                _zp = _xp - _xp.mean()
                _zz = _zp @ _zp
                if _zz > 0:
                    _perm.append((n / S0) * (_zp @ W @ _zp) / _zz)
            _perm = np.array(_perm)
            if _perm.size == 0 or _perm.std() == 0:
                z_score = 0.0
                p_value = 1.0
            else:
                z_score = (I - _perm.mean()) / _perm.std()
                p_value = (1 + int((np.abs(_perm - _perm.mean()) >= abs(I - _perm.mean())).sum())) / (_perm.size + 1)
            method = "置换检验（199 次，样本量过小或权重结构不满足正态近似）"
        if z_score > 1.96:
            pattern = "显著正空间自相关（属性值聚集分布）"
        elif z_score < -1.96:
            pattern = "显著负空间自相关（属性值离散/竞争分布）"
        else:
            pattern = "空间随机分布（无显著自相关）"
        summary = (f"全局 Moran's I = {I:.4f}，z = {z_score:.2f}，p = {p_value:.4f}。{pattern}"
                   f"（显著性判定方式：{method}）")
        # 局部 LISA
        if local:
            local_I = np.array([(z[i] / m2) * (W[i] @ z) for i in range(n)])
            lag_z = W @ z
            cluster = []
            for i in range(n):
                if z[i] > 0 and lag_z[i] > 0:
                    cluster.append("HH")
                elif z[i] > 0 and lag_z[i] < 0:
                    cluster.append("HL")
                elif z[i] < 0 and lag_z[i] < 0:
                    cluster.append("LL")
                elif z[i] < 0 and lag_z[i] > 0:
                    cluster.append("LH")
                else:
                    cluster.append("NS")
            gdf["local_moran"] = np.round(local_I, 6)
            gdf["cluster_type"] = cluster
            base_result_name = f"{name}_MoranI"
            with _state_lock:
                result_name = _disambiguate_layer_name(base_result_name)
                _gdf_to_layer(gdf, result_name)
            hh = cluster.count("HH"); ll = cluster.count("LL")
            hl = cluster.count("HL"); lh = cluster.count("LH")
            return summary + f"\n局部 LISA 结果图层「{result_name}」已加载到地图：HH热点={hh}，LL冷点={ll}，HL异常={hl}，LH异常={lh}"
        return summary
    except Exception as e:
        return f"Moran's I 分析失败: {str(e)[:300]}"

@tool
def spatial_hotspot(layer_name: str, field: str, threshold: float = 0.01,
                    threshold_m: float = 0.0) -> str:
    """Getis-Ord Gi* 热点分析，探测统计显著的高值聚集(热点)与低值聚集(冷点)。
    - layer_name: 图层名（点要素或质心）。
    - field: 待分析字段（必须为非负数值）。
    - threshold: 兼容旧调用的距离阈值（度）；threshold_m: 米制距离阈值（优先使用本地 UTM 投影计算）。
    生成含 gi_z、gi_p 及 hotspot_type('热点'/'冷点'/'不显著') 的新图层并上图。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        if not field:
            numeric_fields = gdf.select_dtypes(include=[np.number]).columns.tolist()
            if not numeric_fields:
                return "图层没有可用于热点分析的数值字段"
            field = numeric_fields[0]
        if field not in gdf.columns:
            return f"字段「{field}」不存在"
        x = gdf[field].values.astype(float)
        if not np.isfinite(x).all():
            return "字段含空值或无穷大，请先清洗"
        if (x < 0).any():
            return "Getis-Ord Gi* 要求字段非负，检测到负值"
        n = len(x)
        if n < 3:
            return f"要素数（{n}）太少"
        if n > _MAX_DENSE_SPATIAL_STATS_FEATURES:
            return f"错误：热点分析当前最多支持 {_MAX_DENSE_SPATIAL_STATS_FEATURES} 个要素；请先聚合或抽样，避免距离矩阵耗尽内存"
        distance_threshold = threshold
        if threshold_m:
            if not math.isfinite(float(threshold_m)) or float(threshold_m) <= 0:
                return "米制距离阈值必须是大于 0 的有限数值"
            metric_gdf = _to_local_metric_gdf(gdf)
            coords = _spatial_feature_coordinates(metric_gdf)
            distance_threshold = float(threshold_m)
        else:
            if not math.isfinite(float(threshold)) or float(threshold) <= 0:
                return "距离阈值必须是大于 0 的有限数值"
            distance_threshold = float(threshold)
            coords = _spatial_feature_coordinates(gdf)
        from scipy.spatial.distance import cdist
        d = cdist(coords, coords)
        W = (d <= distance_threshold).astype(float)  # 含自身（Gi* 定义）
        W_sum = W.sum()
        if W_sum == 0:
            return "权重全为零，请调大 threshold"
        xbar = x.mean()
        # Gi* 统计量
        num = W @ x - xbar * W.sum(axis=1)
        S = np.sqrt((x ** 2).mean() - xbar * xbar)
        if S == 0:
            return "字段标准差为零（所有值相同），无法计算 Gi*"
        wi_sum = W.sum(axis=1)
        wi2_sum = (W ** 2).sum(axis=1)
        denom = S * np.sqrt((n * wi2_sum - wi_sum * wi_sum) / (n - 1))
        denom = np.where(denom == 0, 1e-12, denom)
        gi_z = num / denom
        from scipy.stats import norm
        gi_p = 2.0 * (1.0 - norm.cdf(np.abs(gi_z)))
        htype = []
        for i in range(n):
            if gi_z[i] > 1.96 and gi_p[i] < 0.05:
                htype.append("热点")
            elif gi_z[i] < -1.96 and gi_p[i] < 0.05:
                htype.append("冷点")
            else:
                htype.append("不显著")
        gdf["gi_z"] = np.round(gi_z, 4)
        gdf["gi_p"] = np.round(gi_p, 6)
        gdf["hotspot_type"] = htype
        base_result_name = f"{name}_热点"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(gdf, result_name)
        hot = htype.count("热点"); cold = htype.count("冷点")
        return f"Getis-Ord Gi* 热点分析完成：热点={hot} 个，冷点={cold} 个，不显著={n-hot-cold} 个。结果图层「{result_name}」已加载到地图（含 gi_z / gi_p / hotspot_type 字段）"
    except Exception as e:
        return f"热点分析失败: {str(e)[:300]}"

@tool
def directional_distribution(layer_name: str, group_field: str = "", weight_field: str = "",
                             std_deviations: str = "1_std,2_std") -> str:
    """方向分布（标准差椭圆）：按分组计算中心、长短轴标准差距离与方向角，并生成椭圆面图层供上图。
    - layer_name: 图层名（点要素，或可取质心的面/线）。
    - group_field: 可选分组字段（空=全部要素一组）。
    - weight_field: 可选权重字段（需为非负数值；空=等权）。
    - std_deviations: 要输出的标准差倍数，逗号分隔，如 '1_std,2_std'（也接受 2、1.5 等数字）。
    输出：每组中心 X/Y、方向角（自正北顺时针，度）、X/Y 轴标准差距离（米）；椭圆在 UTM 投影下计算后转回 WGS84 上图。
    """
    try:
        import numpy as np
        import geopandas as gpd
        from shapely.geometry import Polygon

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if group_field and group_field not in gdf.columns:
            return f"错误：分组字段「{group_field}」不存在"
        gdf_metric, crs_m = _stats_metric_gdf(gdf)
        coords, weights = _stats_coords_weights(gdf_metric, weight_field)
        mults = []
        raw = str(std_deviations if std_deviations is not None else "1_std,2_std")
        raw = raw.replace("_std", " ").replace("std", " ").replace("标准差", " ")
        for tok in raw.replace("，", ",").split(","):
            for sub in tok.split():
                try:
                    v = float(sub)
                    if v > 0:
                        mults.append(v)
                except ValueError:
                    if sub.strip():
                        return f"错误：std_deviations 解析失败：'{sub.strip()}'，示例 '1_std,2_std'"
        if not mults:
            mults = [1.0, 2.0]
        if group_field:
            if gdf_metric[group_field].isna().all():
                return f"错误：分组字段「{group_field}」全为空"
            groups = list(gdf_metric.groupby(group_field, dropna=True).groups.keys())
            if not groups:
                return f"错误：分组字段「{group_field}」没有有效分组"
        else:
            groups = [None]
        polys, attrs, lines, skipped = [], [], [], []
        for gval in groups:
            if gval is None:
                c, w, glabel = coords, weights, "全部要素"
            else:
                mask = (gdf_metric[group_field] == gval).values
                c = coords[mask]
                w = weights[mask] if weights is not None else None
                glabel = str(gval)
            n_g = len(c)
            if n_g < 2:
                skipped.append(f"组「{glabel}」要素数 {n_g} < 2")
                continue
            ww = np.ones(n_g, dtype=float) if w is None else np.asarray(w, dtype=float)
            if not np.isfinite(ww).all() or (ww < 0).any() or ww.sum() <= 0:
                return f"错误：组「{glabel}」权重无效：必须为有限非负数且总和大于 0"
            wsum = float(ww.sum())
            cx = float((ww * c[:, 0]).sum() / wsum)
            cy = float((ww * c[:, 1]).sum() / wsum)
            dx = c[:, 0] - cx
            dy = c[:, 1] - cy
            sxx = float((ww * dx * dx).sum() / wsum)
            syy = float((ww * dy * dy).sum() / wsum)
            sxy = float((ww * dx * dy).sum() / wsum)
            vals, vecs = np.linalg.eigh(np.array([[sxx, sxy], [sxy, syy]], dtype=float))
            order = np.argsort(vals)[::-1]
            vals = np.maximum(vals[order], 0.0)
            vecs = vecs[:, order]
            sdx = float(np.sqrt(vals[0]))
            sdy = float(np.sqrt(vals[1]))
            maj = vecs[:, 0]
            rot = float(np.degrees(np.arctan2(maj[0], maj[1]))) % 360.0
            lines.append(f"  组「{glabel}」：n={n_g}，中心=({cx:.2f}, {cy:.2f})，方向角={rot:.2f}，"
                         f"X轴标准差={sdx:.2f} m，Y轴标准差={sdy:.2f} m")
            ux, uy = float(maj[0]), float(maj[1])
            vx, vy = -uy, ux
            t = np.linspace(0.0, 2.0 * np.pi, 73)
            if sdx <= 0 or sdy <= 0:
                # 点共线/重合时某个轴标准差为 0，椭圆退化成线段，无法构成多边形
                skipped.append(f"组「{glabel}」点共线或重合（轴标准差 {sdx:.3f}/{sdy:.3f}）")
                continue
            for m in mults:
                a, b = sdx * m, sdy * m
                ex = cx + a * np.cos(t) * ux + b * np.sin(t) * vx
                ey = cy + a * np.cos(t) * uy + b * np.sin(t) * vy
                polys.append(Polygon(list(zip(ex.tolist(), ey.tolist()))))
                attrs.append({
                    "group": glabel, "std_dev": float(m), "center_x": round(cx, 3),
                    "center_y": round(cy, 3), "rotation_deg": round(rot, 3),
                    "x_std_distance": round(sdx, 3), "y_std_distance": round(sdy, 3),
                })
        if not polys:
            reason = "；".join(skipped) if skipped else "没有可用分组"
            return f"错误：标准差椭圆未生成：没有任何分组能构成有效椭圆（{reason}）"
        ell = gpd.GeoDataFrame(attrs, geometry=polys, crs=crs_m).to_crs("EPSG:4326")
        result_name = f"{name}_标准差椭圆"
        _gdf_to_layer(ell, result_name)
        summary = _stats_summary("directional_distribution", {
            "layer": name, "layer_out": result_name, "ellipses": len(ell), "std_deviations": mults,
            "skipped_groups": skipped,
        })
        skip_txt = ("\n- 已跳过分组：" + "；".join(skipped)) if skipped else ""
        return (f"方向分布（标准差椭圆）完成，结果图层「{result_name}」已加载到地图：\n"
                + "\n".join(lines) + f"\n- 椭圆要素数：{len(ell)}{skip_txt}\n{summary}")
    except Exception as e:
        return f"方向分布分析失败: {str(e)[:300]}"


@tool
def central_tendency(layer_name: str, weight_field: str = "") -> str:
    """中心趋势分析：平均中心、中位中心、中心要素、标准距离与平均最近邻比率。
    - layer_name: 图层名（点要素，或可取质心的面/线）。
    - weight_field: 可选权重字段（需为非负数值；空=等权）。
    输出：平均中心、中位中心、中心要素（到其他要素总距离最小者）、标准距离（米）、平均最近邻比率及其期望/观测/z/p 值。
    注意：本工具只产出数值结果，不生成地图图层。"""
    try:
        import numpy as np
        from scipy.spatial.distance import cdist
        from scipy.stats import norm

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        gdf_metric, crs_m = _stats_metric_gdf(gdf)
        coords, weights = _stats_coords_weights(gdf_metric, weight_field)
        n = len(coords)
        if n < 2:
            return f"错误：要素数（{n}）太少，中心趋势至少需要 2 个"
        ww = np.ones(n, dtype=float) if weights is None else np.asarray(weights, dtype=float)
        if not np.isfinite(ww).all() or (ww < 0).any() or ww.sum() <= 0:
            return "错误：权重字段必须为有限非负数且总和大于 0"
        wsum = float(ww.sum())
        mean_x = float((ww * coords[:, 0]).sum() / wsum)
        mean_y = float((ww * coords[:, 1]).sum() / wsum)
        median_x, median_y = _geometric_median(coords, ww)
        med_x, med_y = float(median_x), float(median_y)
        D = cdist(coords, coords)
        total_dist = D.sum(axis=1)
        center_idx = int(np.argmin(total_dist))
        sx = float(np.sqrt((ww * (coords[:, 0] - mean_x) ** 2).sum() / wsum))
        sy = float(np.sqrt((ww * (coords[:, 1] - mean_y) ** 2).sum() / wsum))
        std_dist = float(np.sqrt(sx ** 2 + sy ** 2))
        nearest = np.where(~np.eye(n, dtype=bool), D, np.inf).min(axis=1)
        obs_mean = float(nearest.mean())
        minx, miny, maxx, maxy = [float(v) for v in gdf_metric.total_bounds]
        b_w, b_h = (maxx - minx), (maxy - miny)
        area = b_w * b_h
        if area > 0:
            density = n / area
            exp_mean = 0.5 / np.sqrt(density)
            se_ann = 0.26136 / np.sqrt(n * density)
            ratio = obs_mean / exp_mean
            z_ann = (obs_mean - exp_mean) / se_ann
            p_ann = 2.0 * (1.0 - norm.cdf(abs(z_ann)))
            pattern = ("聚集分布（观测最近邻距离小于期望）" if ratio < 1 else
                       "离散分布（观测最近邻距离大于期望）" if ratio > 1 else "随机分布")
        else:
            exp_mean = se_ann = ratio = z_ann = p_ann = float("nan")
            pattern = "范围面积为 0，无法计算平均最近邻"
        try:
            center_fid = gdf["_fid"].iloc[center_idx] if "_fid" in gdf.columns else center_idx
        except Exception:
            center_fid = center_idx
        summary = _stats_summary("central_tendency", {
            "layer": name, "n": n, "crs": crs_m,
            "mean_center": [round(mean_x, 3), round(mean_y, 3)],
            "median_center": [round(med_x, 3), round(med_y, 3)],
            "standard_distance_m": round(std_dist, 3),
            "ann_observed_mean_m": round(obs_mean, 3),
            "ann_expected_mean_m": None if exp_mean != exp_mean else round(float(exp_mean), 3),
            "ann_se": None if se_ann != se_ann else round(float(se_ann), 4),
            "ann_z": None if z_ann != z_ann else round(float(z_ann), 4),
            "ann_p": None if p_ann != p_ann else round(float(p_ann), 6),
            "ann_ratio": None if ratio != ratio else round(float(ratio), 4),
        })
        return (
            f"中心趋势分析完成，图层「{name}」，要素数 {n}（投影：{crs_m}）：\n"
            f"- 平均中心：(X={mean_x:.2f}, Y={mean_y:.2f}) m\n"
            f"- 中位中心：(X={med_x:.2f}, Y={med_y:.2f}) m\n"
            f"- 中心要素：第 {center_idx + 1} 个要素（_fid={center_fid}），到其他要素总距离 {total_dist[center_idx]:.2f} m\n"
            f"- 标准距离：{std_dist:.2f} m（X 向 {sx:.2f} m，Y 向 {sy:.2f} m）\n"
            f"- 平均最近邻：观测均值 {obs_mean:.2f} m，期望均值 {exp_mean:.2f} m，"
            f"比率 ANN = {ratio:.4f}，z = {z_ann:.3f}，p = {p_ann:.4f}（{pattern}）\n"
            f"{summary}\n"
            f"（本工具只产出数值结果，不生成地图图层）"
        )
    except Exception as e:
        return f"中心趋势分析失败: {str(e)[:300]}"


@tool
def spatial_kde(layer_name: str, bandwidth: float = 0.0, grid_size: int = 50,
                bandwidth_m: float = 0.0, metric_units: bool = False) -> str:
    """核密度估计（KDE），将点事件转化为连续密度面格网并上图。
    - layer_name: 必须是点图层（Point/MultiPoint，面/线需先调 spatial_centroid 取质心）。
    - bandwidth: 兼容旧调用的高斯核带宽（度）；bandwidth_m: 米制带宽（使用本地 UTM 投影计算）。
      metric_units=True 时始终使用米制坐标，带宽传 0 按 Scott 法则估算。
    - grid_size: 输出格网边长（默认 50，即 50x50 格点）。生成含 density 与 density_km2 字段的图层。"""
    try:
        if isinstance(grid_size, bool) or not isinstance(grid_size, int) or not 10 <= grid_size <= 200:
            return "grid_size 必须是 10 到 200 之间的整数"
        if not math.isfinite(float(bandwidth)) or float(bandwidth) < 0:
            return "带宽必须是有限的非负数"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        import geopandas as gpd
        from shapely.geometry import Point

        # 只接受点要素：对面/线直接取顶点会算成"顶点密度"，与用户意图不符
        _types = set(gdf.geometry.geom_type.dropna().unique())
        if not _types or not _types.issubset({"Point", "MultiPoint"}):
            return (f"KDE 需要点图层，而「{name}」是 {'/'.join(sorted(_types)) or '未知'}。"
                    f"请先对「{name}」执行 spatial_centroid 取质心，再对质心图层做核密度估计。")

        metric_mode = bool(metric_units or bandwidth_m)
        metric_gdf = None
        if metric_mode:
            if not math.isfinite(float(bandwidth_m)) or float(bandwidth_m) < 0:
                return "米制带宽必须是有限的非负数"
            metric_gdf = _to_local_metric_gdf(gdf)
            coords = metric_gdf.geometry.get_coordinates().values
        else:
            coords = gdf.geometry.get_coordinates().values
        n = len(coords)
        if n < 3:
            return f"点要素数（{n}）太少，KDE 至少需要 3 个点"

        # --- 带宽：真实高斯核标准差；米制模式在本地 UTM 坐标中计算 ---
        # 注意：scipy 的 gaussian_kde(bw_method=标量) 里这个标量是 Scott 因子的倍数、
        # 不是带宽本身，直接把 0.01 传进去得到的实际带宽只有约 0.0002 度（差 40 倍），
        # 密度面会退化成几个孤立点。这里自己算核，带宽单位就是度，语义与文档一致。
        std_x, std_y = coords[:, 0].std(), coords[:, 1].std()
        if metric_mode and bandwidth_m > 0:
            h = float(bandwidth_m)
            bw_desc = f"{h:.2f} 米（手动指定）"
        elif metric_mode:
            h = float(np.mean([std_x, std_y]) * (n ** (-1.0 / 6.0)))
            if h <= 0:
                h = 1000.0
            bw_desc = f"{h:.2f} 米（Scott 法则自动估算）"
        elif bandwidth and bandwidth > 0:
            h = float(bandwidth)
            bw_desc = f"{h:.5f} 度（手动指定）"
        else:
            h = float(np.mean([std_x, std_y]) * (n ** (-1.0 / 6.0)))  # Scott 法则（2D）
            if h <= 0:
                h = 0.01
            bw_desc = f"{h:.5f} 度（Scott 法则自动估算）"

        xmin, ymin, xmax, ymax = (metric_gdf if metric_mode else gdf).total_bounds
        pad_x = (xmax - xmin) * 0.1 if xmax > xmin else h
        pad_y = (ymax - ymin) * 0.1 if ymax > ymin else h
        xi = np.linspace(xmin - pad_x, xmax + pad_x, grid_size)
        yi = np.linspace(ymin - pad_y, ymax + pad_y, grid_size)
        gx, gy = np.meshgrid(xi, yi)

        # 密度 = Σ exp(-0.5·(d/h)²) / (n · 2π · h²)，各向同性，单位：点/平方度
        norm = 1.0 / (n * 2.0 * np.pi * h * h)
        density = np.zeros(gx.size, dtype=float)
        # Bound both axes: grid-only chunks still allocate grid_count * n
        # arrays, which can exhaust memory for large point uploads.
        for _start in range(0, gx.size, 512):
            _sl = slice(_start, _start + 512)
            for _point_start in range(0, n, 1024):
                _points = coords[_point_start:_point_start + 1024]
                dx = (gx.ravel()[_sl, None] - _points[None, :, 0]) / h
                dy = (gy.ravel()[_sl, None] - _points[None, :, 1]) / h
                density[_sl] += np.exp(-0.5 * (dx * dx + dy * dy)).sum(axis=1) * norm

        # 兼容旧度制输出；米制模式直接换算平方米与平方千米。
        if metric_mode:
            density_km2 = density * 1e6
        else:
            lat_mid = float(np.mean([ymin, ymax]))
            km2_per_deg2 = 110.574 * 111.320 * max(np.cos(np.radians(lat_mid)), 1e-6)
            density_km2 = density / km2_per_deg2

        dmax = float(density.max())
        keep = density >= dmax * 0.01 if dmax > 0 else np.ones(density.size, dtype=bool)
        pts = np.column_stack([gx.ravel()[keep], gy.ravel()[keep]])
        grid_gdf = gpd.GeoDataFrame(
            {
                "density": np.round(density[keep], 8),
                "density_km2": np.round(density_km2[keep], 6),
                "geometry": [Point(x, y) for x, y in pts],
            },
            crs=metric_gdf.crs if metric_mode else "EPSG:4326",
        )
        if metric_mode:
            grid_gdf = grid_gdf.to_crs("EPSG:4326")
        base_result_name = f"{name}_KDE"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(grid_gdf, result_name)
        _cell = (xi[-1] - xi[0]) / max(grid_size - 1, 1)
        if metric_mode:
            bandwidth_text = f"{h / 1000:.2f} km"
            cell_text = f"{_cell / 1000:.3f} km"
            density_text = (
                f"{density[keep].min():.6f} ~ {dmax:.6f} 点/平方米"
                f"（{density_km2[keep].min():.6f} ~ {density_km2.max():.6f} 点/km²）"
            )
        else:
            bandwidth_text = f"{h * 110.574:.2f} km"
            cell_text = f"{_cell * 110.574:.3f} km"
            density_text = (
                f"{density[keep].min():.6f} ~ {dmax:.6f} 点/平方度"
                f"（约 {density_km2[keep].min():.6f} ~ {density_km2.max():.6f} 点/km²）"
            )
        return (
            f"核密度估计完成，结果图层「{result_name}」已加载到地图。\n"
            f"- 输入点：{n} 个\n"
            f"- 带宽：{bw_desc}（约 {bandwidth_text}）\n"
            f"- 网格：{grid_size}x{grid_size}，格边长约 {cell_text}\n"
            f"- 保留格点：{len(grid_gdf)} 个（已过滤密度低于峰值 1% 的格点）\n"
            f"- 密度范围：{density_text}"
        )
    except Exception as e:
        return f"KDE 分析失败: {str(e)[:300]}"

@tool
def create_fishnet(extent_layer: str = "", cell_size: float = 0.0, rows: int = 0, cols: int = 0, out_name: str = "fishnet") -> str:
    """创建矩形渔网采样格网（ArcGIS CreateFishnet 对应）。
    - extent_layer: 范围参照图层名；留空则用当前所有注册图层的联合范围。
    - cell_size: 每格边长（度）；与 rows/cols 二选一，同时给出时优先 cell_size。
    - rows / cols: 显式行列数（cell_size 为 0 时生效）。
    - out_name: 输出图层名。
    输出面格网图层，逐格带 row/col 属性。"""
    try:
        import numpy as np
        from shapely.geometry import box
        import geopandas as gpd
        try:
            requested_cell_size = float(cell_size)
        except (TypeError, ValueError, OverflowError):
            return "创建渔网失败：cell_size 必须是有限的非负数"
        if not np.isfinite(requested_cell_size) or requested_cell_size < 0:
            return "创建渔网失败：cell_size 必须是有限的非负数"
        if extent_layer:
            gdf_e, ename = _layer_to_gdf(extent_layer)
            if gdf_e is None:
                return ename
            minx, miny, maxx, maxy = gdf_e.total_bounds
        else:
            if not _registered_layers:
                return "错误：当前没有任何注册图层，请先加载图层或显式传 extent_layer"
            bs = [gpd.GeoDataFrame.from_features(v.get("geojson", {}).get("features", []), crs="EPSG:4326").total_bounds
                  for v in _registered_layers.values() if v.get("geojson", {}).get("features")]
            if not bs:
                return "错误：注册图层都没有要素，无法确定范围"
            minx = min(b[0] for b in bs); miny = min(b[1] for b in bs)
            maxx = max(b[2] for b in bs); maxy = max(b[3] for b in bs)
        if not np.isfinite([minx, miny, maxx, maxy]).all():
            return "创建渔网失败：范围包含非有限坐标"
        w = maxx - minx; h = maxy - miny
        if w <= 0 or h <= 0:
            return "错误：范围为空，无法创建格网"
        if requested_cell_size > 0:
            cs = requested_cell_size
            col_ratio, row_ratio = w / cs, h / cs
            if not np.isfinite([col_ratio, row_ratio]).all():
                return "创建渔网失败：目标格网超过单次处理上限（10000 格）"
            ncols = max(1, int(np.ceil(col_ratio)))
            nrows = max(1, int(np.ceil(row_ratio)))
        elif rows and cols and int(rows) > 0 and int(cols) > 0:
            nrows, ncols = int(rows), int(cols)
            cs = 0.0
        else:
            return "错误：请提供 cell_size，或同时提供 rows 与 cols"
        cell_count = nrows * ncols
        if cell_count > 10_000:
            return (f"创建渔网失败：请求 {nrows} 行 × {ncols} 列（{cell_count} 格），"
                    "超过单次处理上限（10000 格）；请增大 cell_size 或缩小范围")
        feats = []
        for r in range(nrows):
            for c in range(ncols):
                x0 = minx + c * (w / ncols); x1 = minx + (c + 1) * (w / ncols)
                y0 = miny + r * (h / nrows); y1 = miny + (r + 1) * (h / nrows)
                feats.append({"type": "Feature", "properties": {"row": r, "col": c},
                              "geometry": box(x0, y0, x1, y1).__geo_interface__})
        out = {"type": "FeatureCollection", "features": feats}
        with _state_lock:
            final_name = _disambiguate_layer_name(out_name)
            _push_layer(final_name, out, {"color": "#555", "weight": 1, "fillOpacity": 0.05})
            _register_layer(final_name, out)
        cs_txt = f"{w / ncols:.6g} x {h / nrows:.6g}"
        return (f"渔网创建完成：{nrows} 行 x {ncols} 列 = {nrows * ncols} 格，格尺寸 {cs_txt}，"
                f"范围 {w:.4g} x {h:.4g}。图层「{final_name}」已加载到地图")
    except Exception as e:
        return f"渔网创建失败: {str(e)[:300]}"


__all__ = [
    "measure_area",
    "measure_distance",
    "convert_crs",
    "convert_coordinates",
    "spatial_graduated_colors",
    "spatial_unique_values",
    "spatial_buffer",
    "spatial_multi_ring_buffer",
    "spatial_intersect",
    "spatial_union",
    "spatial_difference",
    "spatial_clip",
    "spatial_centroid",
    "spatial_simplify",
    "spatial_dissolve",
    "spatial_select",
    "spatial_sample",
    "spatial_near",
    "nearest_pair",
    "spatial_cluster",
    "spatial_voronoi",
    "spatial_field_stats",
    "spatial_join",
    "layer_merge",
    "layer_split",
    "layer_add_geometry",
    "update_attribute",
    "delete_features",
    "add_field",
    "delete_field",
    "move_features",
    "rotate_features",
    "scale_features",
    "spatial_select_by_attribute",
    "topology_check",
    "spatial_fix_geometry",
    "spatial_check_duplicates",
    "spatial_explode",
    "geometry_convert",
    "add_length_field",
    "edit_vertices",
    "draw_feature",
    "add_legend",
    "add_labels",
    "join_field",
    "geometry_attributes",
    "minimum_bounding_geometry",
    "points_to_line",
    "generate_points_along_lines",
    "spatial_weights_matrix",
    "spatial_regression",
    "spatial_moran",
    "spatial_hotspot",
    "spatial_kde",
    "directional_distribution",
    "central_tendency",
    "create_fishnet",
    "_to_local_metric_gdf",
    "_spatial_feature_coordinates",
    "_gdf_area_km2",
    "_get_utm_crs",
    "_local_utm_extent_error",
    "_stats_metric_gdf",
    "_stats_coords_weights",
    "_geometric_median",
    "_build_spatial_weights",
    "_moran_from_weights",
    "_stats_out_dir",
    "_stats_safe_name",
    "_stats_summary",
    "_parse_numeric_condition",
    "record_tool_artifact",
]
