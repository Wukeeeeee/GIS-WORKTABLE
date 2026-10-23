# -*- coding: utf-8 -*-
"""空间分析健壮性层（方法论迁移，非代码复制）

背景：研究 ESRI ArcGIS 的 OverlayUtilities.py 后发现，他的健壮性来自工程纪律
而非更强的算法：
  1. 先检测/修复几何（RepairGeometry 等价）
  2. 先探测资源再选路径（CheckResources 等价）
  3. 切块→逐块→合并（CreatePartitionFeatureClass 等价）
  4. 降级而非失败
本模块用开源栈（geopandas/shapely/scipy）重写这份纪律，不依赖任何 ESRI 代码。
"""
from __future__ import annotations

import math

import geopandas as gpd


# 阈值：块段（坐标点数）或要素数超限时走分批路径
SEGMENT_THRESHOLD = 50_000
FEATURE_THRESHOLD = 20_000


def _geom_segments(geom) -> int:
    """估算单个几何的块段数（坐标点数）。点记 1，线/面记外环点数。"""
    if geom is None or geom.is_empty:
        return 0
    gt = geom.geom_type
    if gt == "Point":
        return 1
    if gt in ("LineString", "LinearRing"):
        return len(geom.coords)
    if gt == "Polygon":
        return len(geom.exterior.coords) + sum(len(r.coords) for r in geom.interiors)
    if gt.startswith("Multi") or gt == "GeometryCollection":
        return sum(_geom_segments(g) for g in geom.geoms)
    return 1


def repair_geometry(gdf: gpd.GeoDataFrame):
    """修复无效几何并丢弃空几何或无法修复的无效几何。

    返回 (new_gdf, stats)，stats = {"repaired": n, "dropped": n}。
    无效几何先试 geom.buffer(0)（shapely 经典自交修法），
    仍无效则丢弃；None/empty 直接丢弃。
    """
    if gdf is None or len(gdf) == 0:
        return gdf, {"repaired": 0, "dropped": 0}
    repaired = 0
    dropped = 0
    keep_positions = []
    new_geoms = []
    valid_mask = gdf.geometry.is_valid
    for idx, (geom, ok) in enumerate(zip(gdf.geometry, valid_mask)):
        if geom is None or geom.is_empty:
            dropped += 1
            continue
        if ok:
            keep_positions.append(idx)
            new_geoms.append(geom)
            continue
        try:
            fixed = geom.buffer(0)
        except Exception:
            fixed = None
        if fixed is not None and not fixed.is_empty and fixed.is_valid:
            repaired += 1
            keep_positions.append(idx)
            new_geoms.append(fixed)
        else:
            dropped += 1
    if not keep_positions:
        return gdf.iloc[0:0], {"repaired": repaired, "dropped": dropped}
    out = gdf.iloc[keep_positions].copy()
    out.geometry = new_geoms
    return out, {"repaired": repaired, "dropped": dropped}


def estimate_tier(gdf: gpd.GeoDataFrame) -> dict:
    """探测数据规模，决定走快路径还是分批路径。

    返回 {"features", "segments", "tier"}，tier 为 "fast" 或 "chunked"。
    """
    n = 0 if gdf is None else len(gdf)
    segs = 0
    if gdf is not None and n:
        segs = int(sum(_geom_segments(g) for g in gdf.geometry))
    tier = "chunked" if (segs > SEGMENT_THRESHOLD or n > FEATURE_THRESHOLD) else "fast"
    return {"features": n, "segments": segs, "tier": tier}


def chunked_overlay(gdf_a: gpd.GeoDataFrame, gdf_b: gpd.GeoDataFrame, op, chunk_cells: int = 4):
    """分批处理 gdf_a，每批都与完整 gdf_b 执行 op，最后合并结果。

    单批失败不弹全局；全部失败才 raise。
    返回 (result_gdf, stats)，stats = {"cells", "ok_cells", "failed_cells"}。
    cells 表示分批数。不要按空间网格筛整条几何：difference 等非对称操作会因此重复
    输出未扣除的完整要素。
    """
    if chunk_cells < 1:
        raise ValueError("chunk_cells 必须大于 0")
    if gdf_a is None or len(gdf_a) == 0:
        return gdf_a, {"cells": 0, "ok_cells": 0, "failed_cells": 0}
    batch_count = min(chunk_cells, len(gdf_a))
    batch_size = math.ceil(len(gdf_a) / batch_count)
    batch_count = math.ceil(len(gdf_a) / batch_size)
    parts = []
    ok_cells = 0
    failed_cells = 0
    for start in range(0, len(gdf_a), batch_size):
        sub_a = gdf_a.iloc[start:start + batch_size]
        try:
            res = op(sub_a, gdf_b)
            if res is not None and len(res):
                parts.append(res)
            ok_cells += 1
        except Exception:
            failed_cells += 1
    cells = batch_count
    if not parts and failed_cells:
        raise RuntimeError(f"分批处理未产生结果且有批次失败（{failed_cells}/{cells} 批失败）")
    if not parts:
        return gdf_a.iloc[0:0].copy(), {"cells": cells, "ok_cells": ok_cells, "failed_cells": failed_cells}
    merged = gpd.GeoDataFrame(
        __import__("pandas").concat(parts, ignore_index=True), crs=gdf_a.crs)
    return merged, {"cells": cells, "ok_cells": ok_cells, "failed_cells": failed_cells}


def robust_note(rstats: dict, tier: dict, chunk_stats: dict = None) -> str:
    """统一的附加说明文案（中文，放返回值末尾）。"""
    bits = []
    if rstats.get("repaired"):
        bits.append(f"已自动修复 {rstats['repaired']} 个无效几何")
    if rstats.get("dropped"):
        bits.append(f"丢弃 {rstats['dropped']} 个空或无法修复的无效几何")
    if chunk_stats is not None:
        bits.append(f"已启用分批处理（{tier['segments']} 块段，"
                    f"{chunk_stats['ok_cells']}/{chunk_stats['cells']} 批成功）")
        if chunk_stats["failed_cells"]:
            bits.append(f"{chunk_stats['failed_cells']} 批失败已跳过")
    elif tier.get("tier") == "chunked":
        bits.append(f"输入规模较大（{tier['segments']} 块段）")
    return ("（" + "；".join(bits) + "）") if bits else ""
