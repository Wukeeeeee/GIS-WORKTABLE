# -*- coding: utf-8 -*-
"""
backend.services.tool_modules.raster
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Layer 2 Raster and Remote Sensing Analysis Tools.

This module provides 20 specialized tools for raster manipulation, map algebra,
spectral indexing, surface interpolation, resampling, reclassification, and COG inspection.

Architectural rules:
- Strictly Layer 2: Depends only on Layer 1 (runtime), Layer 0 (common), and 3rd party GIS libraries.
- NEVER imports Layer 3 (backend.services.tools).
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.parse
import uuid
from typing import Any, Literal, Optional

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
from langchain.tools import tool
from PIL import Image

from backend.services.tool_modules.common import (
    _safe_layer_export_stem,
    _validate_ast,
)
from backend.services.tool_modules import runtime
from backend.services.tool_modules.runtime import (
    _disambiguate_layer_name,
    _gdf_to_layer,
    _layer_to_gdf,
    _pending_images,
    _pending_layer_ops,
    _pending_layers,
    _push_layer,
    _raster_output_scope,
    _register_layer,
    _register_raster_layer,
    _registered_layers,
    _state_lock,
    get_current_run_id,
    get_current_task_id,
    get_temp_output_dir,
    init_temp_dir,
)

__all__ = [
    # 20 Public Tools
    "ndvi_analysis",
    "raster_calculator",
    "spatial_interpolate",
    "clip_raster",
    "calc_spectral_index",
    "ndwi_analysis",
    "ndbi_analysis",
    "evi_analysis",
    "ndmi_analysis",
    "zonal_statistics",
    "raster_resample",
    "raster_reproject",
    "raster_reclassify",
    "raster_focal_stats",
    "euclidean_distance",
    "raster_extract_by_mask",
    "feature_to_raster",
    "raster_to_feature",
    "load_cog",
    "get_cog_info",
    # Shared / Internal Helpers
    "_find_uploaded_tif",
    "_raster_output_dir",
    "_write_raster_output",
    "_raster_preview_op",
    "_raster_preview_context",
    "_raster_out_profile",
    "_parse_reclass_rules",
    "_calc_spectral_index",
    "_get_utm_crs",
    "record_tool_artifact",
]


# ============================================================
# Shared / Internal Raster Helpers
# ============================================================

def record_tool_artifact(filename: str, filepath: str, artifact_type: str = "image", step: int = 0) -> Optional[dict]:
    """统一记录生成的产物到 TaskManager (工作台) 和 StorageService (SQLite持久化)。"""
    current_task_id = get_current_task_id()
    current_run_id = get_current_run_id()
    art = None
    if current_task_id:
        try:
            from backend.services.task_manager import register_artifact
            art = register_artifact(current_task_id, filename, filepath,
                                    artifact_type=artifact_type, created_by_step=step)
        except Exception as e:
            print(f"[Tools] register_artifact 失败: {e}", flush=True)
    if current_run_id:
        try:
            from backend.services import storage_service
            art_id = (art.get("artifact_id") if art else "") or uuid.uuid4().hex[:10]
            storage_service.register_run_artifact(
                current_run_id, art_id, filename, filepath, file_type=artifact_type
            )
        except Exception as e:
            print(f"[Tools] register_run_artifact 失败: {e}", flush=True)
    return art


def _get_utm_crs(lon: float, lat: float) -> str:
    """根据经纬度计算标准 UTM 投影坐标系，带号严格约束在 1~60 之间。"""
    utm_zone = int((lon + 180) / 6) + 1
    utm_zone = max(1, min(60, utm_zone))
    return f"EPSG:{32600 + utm_zone}" if lat >= 0 else f"EPSG:{32700 + utm_zone}"



def _raster_output_dir():
    init_temp_dir()
    temp_dir = get_temp_output_dir()
    path = os.path.join(temp_dir, 'uploads')
    scope = getattr(_raster_output_scope, "value", "")
    if scope:
        path = os.path.join(path, scope)
    os.makedirs(path, exist_ok=True)
    return path



def _find_uploaded_tif(layer_name: str):
    """Resolve the selected raster exactly; a substring may identify another dataset."""
    with _state_lock:
        info = _registered_layers.get(layer_name)
        if info and isinstance(info.get('raster'), dict):
            source = info.get('raster_source_path')
            return source if source and os.path.isfile(source) else None
        if runtime.get_active_project_id():
            return None
    init_temp_dir()
    temp_dir = get_temp_output_dir()
    upload_dirs = list(dict.fromkeys((
        _raster_output_dir(), os.path.join(temp_dir, 'uploads'),
    )))
    for upload_dir in upload_dirs:
        if os.path.isdir(upload_dir):
            for f in os.listdir(upload_dir):
                if f.lower().endswith(('.tif', '.tiff')):
                    base = os.path.splitext(f)[0]
                    if base == layer_name:
                        return os.path.join(upload_dir, f)
    return None



def _write_raster_output(source_path: str, out_name: str, data, metadata=None) -> str:
    """保存带源空间参考的单波段分析结果，作为后续栅格工具可读取的输入。"""
    import numpy as np
    import rasterio

    safe_name = os.path.basename(str(out_name)).strip()
    if not safe_name or safe_name in {'.', '..'}:
        raise ValueError("栅格结果名称无效")
    values = np.asarray(data, dtype="float32")
    if values.ndim == 2:
        values = values[None, :, :]
    if values.ndim != 3 or values.shape[0] < 1:
        raise ValueError("栅格结果必须是二维像元数组或波段数组")
    output_path = os.path.join(_raster_output_dir(), safe_name + ".tif")
    with rasterio.open(source_path) as src:
        profile = src.profile.copy()
        source_width, source_height = src.width, src.height
        profile.update(count=values.shape[0], width=values.shape[2], height=values.shape[1],
                       dtype="float32", nodata=float("nan"))
        if source_width != values.shape[2] or source_height != values.shape[1]:
            profile["transform"] = src.transform * src.transform.scale(
                src.width / values.shape[2], src.height / values.shape[1])
        if not profile.get("tiled"):
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(values)
        if metadata:
            dst.update_tags(**{str(key): str(value) for key, value in metadata.items() if value is not None})
    return output_path



def _raster_preview_op(src, data, out_name: str, label: str, preview_image=None,
                       source_layer=None, value_units=None, source_label=None,
                       source_reference=None, quality_warnings=None) -> str:
    """保存栅格预览、注册原始 GeoTIFF，并通过 dem_result 交付地图与图层面板。"""
    import numpy as np
    from PIL import Image
    import rasterio
    from affine import Affine
    from urllib.parse import quote
    from rasterio.enums import Resampling
    from rasterio.transform import array_bounds
    from rasterio.warp import calculate_default_transform, reproject
    values = np.asarray(data)
    band = (values if values.ndim == 2 else values[0]).astype("float64")
    valid = np.isfinite(band)
    if getattr(src, "nodata", None) is not None:
        valid &= band != src.nodata
    if valid.any():
        lo, hi = np.percentile(band[valid], 2), np.percentile(band[valid], 98)
        if hi <= lo:
            hi = lo + 1.0
        norm = np.clip((band - lo) / (hi - lo), 0, 1)
    else:
        norm = np.zeros_like(band)
    norm[~valid] = 0
    rgb = (np.dstack([norm] * 3) * 255).astype("uint8")
    img = preview_image if preview_image is not None else Image.fromarray(rgb)
    upload_dir = _raster_output_dir()
    try:
        input_tags = {key.upper(): value for key, value in src.tags().items()}
        input_units = src.units or ()
    except Exception:
        input_tags, input_units = {}, ()
    png_name = os.path.basename(str(out_name)) + ".png"
    png_path = os.path.join(upload_dir, png_name)
    raster_path = os.path.join(upload_dir, os.path.basename(str(out_name)) + ".tif")
    if not os.path.isfile(raster_path):
        raster_path = _write_raster_output(src.name, out_name, values)
    with rasterio.open(raster_path) as result_src:
        preview_rgba = np.dstack((np.asarray(img.convert("RGB")), valid.astype("uint8") * 255))
        transform = result_src.transform
        if result_src.crs and (
            not result_src.crs.is_geographic
            or abs(float(transform.b)) > 1e-12
            or abs(float(transform.d)) > 1e-12
            or result_src.crs.to_epsg() != 4326
        ):
            preview_transform, preview_width, preview_height = calculate_default_transform(
                result_src.crs, "EPSG:4326", result_src.width, result_src.height,
                *result_src.bounds,
            )
            max_preview_pixels = 4_000_000
            if preview_width * preview_height > max_preview_pixels:
                scale = (preview_width * preview_height / max_preview_pixels) ** 0.5
                target_width = max(1, int(preview_width / scale))
                target_height = max(1, int(preview_height / scale))
                preview_transform = preview_transform * Affine.scale(
                    preview_width / target_width, preview_height / target_height,
                )
                preview_width, preview_height = target_width, target_height
            warped_rgba = np.zeros((preview_height, preview_width, 4), dtype="uint8")
            for band_index in range(4):
                reproject(
                    source=preview_rgba[:, :, band_index],
                    destination=warped_rgba[:, :, band_index],
                    src_transform=transform, src_crs=result_src.crs,
                    dst_transform=preview_transform, dst_crs="EPSG:4326",
                    resampling=Resampling.nearest,
                )
            img = Image.fromarray(warped_rgba, mode="RGBA")
            bounds = list(array_bounds(preview_height, preview_width, preview_transform))
        elif result_src.crs:
            img = Image.fromarray(preview_rgba, mode="RGBA")
            bounds = [result_src.bounds.left, result_src.bounds.bottom,
                      result_src.bounds.right, result_src.bounds.top]
        else:
            img = Image.fromarray(preview_rgba, mode="RGBA")
            bounds = [result_src.bounds.left, result_src.bounds.bottom,
                      result_src.bounds.right, result_src.bounds.top]
        crs = result_src.crs.to_string() if result_src.crs else None
        width, height = result_src.width, result_src.height
        bands = result_src.count
        pixel_size = [
            math.hypot(float(result_src.transform.a), float(result_src.transform.d)),
            math.hypot(float(result_src.transform.b), float(result_src.transform.e)),
        ]
        source_tags = {key.upper(): value for key, value in result_src.tags().items()}
        result_units = (value_units or (result_src.units[0] if result_src.units and result_src.units[0] else None)
                        or source_tags.get("VALUE_UNITS")
                        or (input_units[0] if input_units and input_units[0] else None)
                        or input_tags.get("VALUE_UNITS"))
        pixel_units = result_src.crs.linear_units if result_src.crs and result_src.crs.is_projected else ("degree" if result_src.crs and result_src.crs.is_geographic else "unknown")
        warnings = list(quality_warnings or [])
        if result_src.crs is None:
            warnings.append("预览栅格缺少 CRS；未能进行地理配准转换")
        source_quality_note = (source_tags.get("QUALITY_NOTE") or source_tags.get("SOURCE_QUALITY_NOTE")
                               or input_tags.get("QUALITY_NOTE") or input_tags.get("SOURCE_QUALITY_NOTE"))
        if source_quality_note and source_quality_note not in warnings:
            warnings.append(source_quality_note)
        if not result_src.crs:
            warnings.append("结果栅格未包含 CRS")
        valid_ratio = float(np.count_nonzero(valid)) / float(valid.size) if valid.size else 0.0
        if valid_ratio < 0.9:
            warnings.append("有效像元比例低于 90%，请检查 NoData 或输入覆盖范围")
        resolved_source_layer = (source_layer or source_tags.get("SOURCE_LAYER")
                                 or input_tags.get("SOURCE_LAYER"))
        resolved_source_label = (source_label or source_tags.get("SOURCE_LABEL")
                                 or input_tags.get("SOURCE_LABEL") or input_tags.get("SOURCE")
                                 or "GIS WorkTable 栅格分析")
        resolved_source_reference = (source_reference or source_tags.get("SOURCE_URL")
                                     or source_tags.get("CITATION") or input_tags.get("SOURCE_URL")
                                     or input_tags.get("CITATION"))
        vertical_datum = source_tags.get("VERTICAL_DATUM") or input_tags.get("VERTICAL_DATUM")
        # Keep provenance on the analysis GeoTIFF itself so it survives project save/reopen
        # and can be consumed by a later raster operation, not only by this preview response.
        output_tags = {
            "SOURCE_LAYER": resolved_source_layer,
            "SOURCE_LABEL": resolved_source_label,
            "SOURCE_URL": resolved_source_reference,
            "SOURCE_VALUE_UNITS": (source_tags.get("SOURCE_VALUE_UNITS")
                                   or input_tags.get("SOURCE_VALUE_UNITS")
                                   or input_tags.get("VALUE_UNITS")
                                   or (input_units[0] if input_units else None)),
            "VALUE_UNITS": result_units,
            "VERTICAL_DATUM": vertical_datum,
            "PROCESSING": label,
            "QUALITY_NOTE": "; ".join(str(warning) for warning in warnings) or None,
        }
    with rasterio.open(raster_path, "r+") as output_src:
        output_src.update_tags(**{key: str(value) for key, value in output_tags.items() if value is not None})
    img.save(png_path)
    def _output_url(path):
        relative = os.path.relpath(path, get_temp_output_dir()).replace(os.sep, "/")
        return "/output/" + quote(relative, safe="/")

    preview_url = _output_url(png_path)
    source_url = _output_url(raster_path)
    layer_name = os.path.splitext(os.path.basename(raster_path))[0]
    raster_info = {
        "filename": png_name, "url": preview_url,
        "source_filename": os.path.basename(raster_path), "source_name": layer_name,
        "source_url": source_url, "bounds": [float(v) for v in bounds],
        "width": int(width), "height": int(height),
        "source_width": int(width), "source_height": int(height),
        "bands": int(bands), "crs": crs,
        "pixel_size": pixel_size,
        "pixel_units": pixel_units, "value_units": result_units,
        "source_layer": resolved_source_layer,
        "source_label": resolved_source_label,
        "source_reference": resolved_source_reference,
        "vertical_datum": vertical_datum,
        "processing": label, "valid_pixel_ratio": valid_ratio,
        "quality_warnings": warnings,
    }
    registration_token = _register_raster_layer(layer_name, raster_info, raster_path)
    _pending_layer_ops.append({
        "action": "dem_result", "name": png_name,
        "url": preview_url,
        "bounds": [float(v) for v in bounds],
        "label": label, "layer_name": layer_name, "raster": raster_info,
        "registration_token": registration_token, "crs": crs,
    })
    try:
        record_tool_artifact(png_name, png_path, artifact_type="image")
        record_tool_artifact(os.path.basename(raster_path), raster_path, artifact_type="raster")
    except Exception:
        pass
    return "预览已叠加到地图，并注册为可继续分析的栅格图层"



def _raster_preview_context(layer_name: str, *, value_units=None) -> dict:
    """Carry input layer provenance into derived raster metadata when a registry entry exists."""
    with _state_lock:
        info = _registered_layers.get(layer_name) or {}
        raster = info.get("raster") if isinstance(info, dict) else None
        raster = dict(raster) if isinstance(raster, dict) else {}
    return {
        "source_layer": layer_name,
        "value_units": value_units if value_units is not None else raster.get("value_units"),
        "source_label": raster.get("source_label"),
        "source_reference": raster.get("source_reference"),
        "quality_warnings": raster.get("quality_warnings"),
    }



def _raster_out_profile(src, nodata, count: int = 1) -> dict:
    """复制源栅格 profile 作为输出，清理与本机 GDAL 冲突的分块键，统一 float32"""
    profile = src.profile.copy()
    profile.update(count=count, dtype="float32", nodata=nodata)
    if not profile.get("tiled"):
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
    return profile



def _parse_reclass_rules(mapping: str):
    """解析重分类映射串 'a-b=v;c+=v'，返回 [(lo, hi, val), ...]（a-b 为左闭右开 [a,b)，c+ 表示 >=c）"""
    import math
    import re
    rules = []
    text = str(mapping or "").replace("\n", ";").replace("，", ";").replace(",", ";")
    for i, chunk in enumerate(text.split(";")):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            return []
        left, right = chunk.split("=", 1)
        left, right = left.strip(), right.strip()
        try:
            val = float(right)
        except ValueError:
            val = float(i + 1)
        m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*\+", left)
        if m:
            lo, hi = float(m.group(1)), math.inf
        else:
            m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*[-~]\s*(-?\d+(?:\.\d+)?)", left)
            if m:
                lo, hi = float(m.group(1)), float(m.group(2))
            else:
                m = re.fullmatch(r"(-?\d+(?:\.\d+)?)", left)
                if not m:
                    return []
                lo, hi = float(m.group(1)), float(m.group(1)) + 1e-9
        if not math.isfinite(lo) or (not math.isfinite(hi) and hi != math.inf):
            return []
        if hi < lo:
            lo, hi = hi, lo
        if hi <= lo:
            return []
        if not math.isfinite(val):
            return []
        rules.append((lo, hi, val))
    return rules



def _calc_spectral_index(layer_name: str, formula_name: str, calc_fn, cmap_name: str,
                         label: str, value_range=(-1.0, 1.0), band_map: dict = None) -> str:
    """通用遥感指数计算：读取 GeoTIFF → 计算指数 → 生成彩色 PNG → 推送到地图。
    calc_fn(bands_dict) -> np.ndarray，bands_dict 的键是波段名（red/green/blue/nir/swir）。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的 GeoTIFF 文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        with rasterio.open(tif_path) as src:
            if band_map is None:
                band_map = {"blue": 1, "green": 2, "red": 3, "nir": 4, "swir": 5}
            bands = {}
            for bname, bidx in band_map.items():
                if src.count >= bidx:
                    arr = src.read(bidx, masked=True).astype(np.float64).filled(np.nan)
                    arr[~np.isfinite(arr)] = np.nan
                    bands[bname] = arr
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != "EPSG:4326":
                bounds = list(transform_bounds(src.crs, "EPSG:4326", *bounds))
        if not bands:
            return "错误：GeoTIFF 无有效波段"
        idx = calc_fn(bands)
        idx = np.clip(idx, value_range[0], value_range[1])
        import matplotlib
        cmap = matplotlib.colormaps[cmap_name]
        valid = np.isfinite(idx)
        norm = (idx - value_range[0]) / (value_range[1] - value_range[0])
        norm = np.clip(norm, 0, 1)
        norm[~valid] = 0
        rgba = cmap(norm)
        rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
        if np.any(~valid):
            rgb[~valid] = 0
        img = Image.fromarray(rgb)
        out_name = f"{_safe_layer_export_stem(layer_name)}_{uuid.uuid4().hex}_{formula_name}.png"
        out_path = os.path.join(upload_dir, out_name)
        img.save(out_path)
        from urllib.parse import quote
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": out_name,
            "url": f"/output/uploads/{quote(out_name, safe='')}",
            "bounds": bounds,
            "label": label,
        })
        valid_count = int(np.sum(valid))
        mean_val = float(np.nanmean(idx)) if valid_count > 0 else 0.0
        return f"已生成{label}图层，有效像元{valid_count}个，平均值={mean_val:.3f}，范围[{value_range[0]}, {value_range[1]}]"
    except ImportError as e:
        return f"{formula_name}计算需要依赖库: {str(e)[:200]}"
    except Exception as e:
        return f"{formula_name}计算失败: {str(e)[:300]}"



# ============================================================
# 20 Raster Domain Tools
# ============================================================


@tool
def ndvi_analysis(layer_name: str, red_band: int = 3, nir_band: int = 4) -> str:
    """计算归一化植被指数 NDVI = (NIR-Red)/(NIR+Red)。
    - layer_name: GeoTIFF 图层名。
    - red_band: 红光波段序号(从1开始，默认 3；Landsat 8/9为4，Sentinel-2为4)。
    - nir_band: 近红外波段序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。
    输出范围 [-1, 1] 的彩色渲染图层并上图。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        with rasterio.open(tif_path) as src:
            if src.count < max(red_band, nir_band):
                return f"错误：文件只有{src.count}个波段，无法读取波段{max(red_band, nir_band)}"
            red = src.read(red_band, masked=True).astype(np.float64).filled(np.nan)
            nir = src.read(nir_band, masked=True).astype(np.float64).filled(np.nan)
            red[~np.isfinite(red)] = np.nan
            nir[~np.isfinite(nir)] = np.nan
            source_tags = {key.upper(): value for key, value in src.tags().items()}
            source_label = source_tags.get("SOURCE_LABEL") or source_tags.get("SOURCE")
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        ndvi = (nir - red) / (nir + red + 1e-10)
        ndvi = np.clip(ndvi, -1, 1)
        # 红绿渐变：NDVI=-1→红色，0→黄色，1→绿色
        import matplotlib
        cmap = matplotlib.colormaps['RdYlGn']
        valid = np.isfinite(ndvi)
        norm = (ndvi - (-1)) / (1 - (-1))  # -1~1 → 0~1
        norm = np.clip(norm, 0, 1)
        norm[~valid] = 0
        rgba = cmap(norm)
        rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
        if np.any(~valid):
            rgb[~valid] = 0
        img = Image.fromarray(rgb)
        out_name = f"{_safe_layer_export_stem(layer_name)}_{uuid.uuid4().hex}_ndvi"
        raster_path = _write_raster_output(tif_path, out_name, ndvi, metadata={
            "SOURCE_LAYER": layer_name, "SOURCE_LABEL": source_label or "GIS WorkTable 栅格分析",
            "PROCESSING": "NDVI 归一化植被指数", "VALUE_UNITS": "无量纲（-1 至 1）",
        })
        with rasterio.open(raster_path) as result_src:
            _raster_preview_op(
                result_src, ndvi, out_name, "NDVI 归一化植被指数", preview_image=img,
                source_layer=layer_name, value_units="无量纲（-1 至 1）", source_label=source_label,
            )
        valid_count = np.sum(valid)
        mean_ndvi = float(np.nanmean(ndvi))
        return f"已生成NDVI栅格图层「{out_name}」，有效像元{valid_count}个，平均NDVI={mean_ndvi:.3f}"
    except ImportError as e:
        return f"错误：NDVI计算需要依赖库: {str(e)[:200]}，请安装: pip install matplotlib"
    except Exception as e:
        import traceback
        return f"NDVI分析失败: {str(e)[:300]}"



@tool
def raster_calculator(layer_name: str, expression: str) -> str:
    """对多波段 GeoTIFF 执行逐像元数学表达式计算。
    layer_name 为上传的栅格图层名，expression 为表达式字符串。
    波段用 B1/B2/B3… 引用，支持 + - * / ** ( ) 和函数。
    示例: '(B4-B3)/(B4+B3)'、'B1*2.5'、'B2-B1'。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        with rasterio.open(tif_path) as src:
            pixel_count = int(src.width) * int(src.height)
            band_pixel_count = pixel_count * int(src.count)
            if pixel_count > 4_000_000 or band_pixel_count > 16_000_000:
                return (f"栅格计算失败: 当前影像为 {src.width}×{src.height} 像元、{src.count} 波段，"
                        "超过单次处理上限（400 万像元或 1600 万波段像元）；请先裁剪或重采样")
            bands = {}
            for i in range(1, src.count + 1):
                b = src.read(i, masked=True).astype(np.float64).filled(np.nan)
                b[~np.isfinite(b)] = np.nan
                bands[f"B{i}"] = b
            source_tags = {key.upper(): value for key, value in src.tags().items()}
            source_label = source_tags.get("SOURCE_LABEL") or source_tags.get("SOURCE")
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        safe_dict = {**bands}
        safe_dict.update({
            "sin": lambda x: np.sin(np.radians(x)),
            "cos": lambda x: np.cos(np.radians(x)),
            "sqrt": np.sqrt,
            "abs": np.abs,
            "log": np.log,
            "exp": np.exp,
            "min": np.minimum,
            "max": np.maximum,
            "power": np.power,
        })
        _rc_tree = ast.parse(expression, mode="eval")
        _validate_ast(_rc_tree.body)
        # NumPy may import warning handlers when floating-point errors occur; keep them
        # local to the expression and represent non-finite pixels as raster NoData below.
        with np.errstate(all="ignore"):
            result = eval(compile(_rc_tree, "<safe>", "eval"), {"__builtins__": {}}, safe_dict)
        if not isinstance(result, np.ndarray):
            return f"错误：表达式结果不是栅格数据: {type(result)}"
        result = result.astype(np.float64, copy=True)
        result[~np.isfinite(result)] = np.nan
        if np.all(np.isnan(result)):
            return "错误：计算结果全为NaN，请检查表达式或波段数据"
        vmin, vmax = np.nanmin(result), np.nanmax(result)
        if np.isclose(vmin, vmax):
            rgb = np.full((*result.shape, 3), 128, dtype=np.uint8)
        else:
            norm = (result - vmin) / (vmax - vmin + 1e-10)
            norm = np.clip(norm, 0, 1)
            import matplotlib
            cmap = matplotlib.colormaps['viridis']
            rgba = cmap(norm)
            rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
            nan_mask = np.isnan(result)
            if np.any(nan_mask):
                rgb[nan_mask] = 0
        img = Image.fromarray(rgb)
        out_name = f"{layer_name}_calc_{uuid.uuid4().hex}"
        raster_path = _write_raster_output(tif_path, out_name, result, metadata={
            "SOURCE_LAYER": layer_name, "SOURCE_LABEL": source_label or "GIS WorkTable 栅格分析",
            "PROCESSING": f"栅格计算: {expression}",
            "VALUE_UNITS": "未推导（取决于表达式与输入单位）",
        })
        with rasterio.open(raster_path) as result_src:
            _raster_preview_op(
                result_src, result, out_name, f"栅格计算: {expression}", preview_image=img,
                source_layer=layer_name, value_units="未推导（取决于表达式与输入单位）",
                source_label=source_label,
                quality_warnings=["栅格计算器不会自动推导表达式的物理单位"],
            )
        return f"已执行 '{expression}'，范围 [{vmin:.2f}, {vmax:.2f}]，结果栅格「{out_name}」已上图并可继续分析"
    except Exception as e:
        return f"栅格计算失败: {str(e)[:300]}"



@tool
def spatial_interpolate(layer_name: str, field: str, method: str = "idw",
                        resolution: int = 200) -> str:
    """对点图层进行空间插值生成连续栅格曲面。

【方法选择】
- idw（反距离加权）：简单快速，精确通过采样点，适合点密集且分布均匀。
- rbf（径向基函数）：更平滑，可处理不规则分布，适合中等数据量。
- 需要估计误差时用克里金（execute_python + pykrige）。

【常见坑】
- 采样点应覆盖研究区，边界外是外推不可靠，用研究区边界裁剪。
- 点太少（<10）结果不可靠。
- resolution 是行列数，支持 2–1024；单次计算最多 5,000 万个网格-样本距离对。
- 单次范围最多覆盖 6° 经度且须在 UTM 纬度范围内；更大区域应分区处理。"""
    try:
        import numpy as np
        import pandas as pd
        max_resolution = 1024
        max_distance_pairs = 50_000_000
        distance_batch_pairs = 1_000_000
        max_rbf_points = 500
        if isinstance(resolution, bool) or not isinstance(resolution, int) or not 2 <= resolution <= max_resolution:
            return f"插值失败: resolution 必须是 2 到 {max_resolution} 之间的整数"
        if method not in {"idw", "rbf"}:
            return f"错误：不支持的方法: {method}，可选 idw / rbf"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        non_null_geometry = gdf.geometry[gdf.geometry.notna()]
        if non_null_geometry.empty:
            return f"错误：图层 '{name}' 没有有效点几何，无法插值"
        unsupported = sorted(set(non_null_geometry.geom_type) - {"Point", "MultiPoint"})
        if unsupported:
            return f"错误：图层 '{name}' 不含点要素，无法插值"
        if field not in gdf.columns:
            return f"错误：图层 '{name}' 没有字段 '{field}'，可用字段: {', '.join(gdf.columns)}"
        pts = gdf[[field, gdf.geometry.name]].copy()
        pts = pts.to_crs("EPSG:4326")
        # Explode MultiPoint features and keep each observation paired with its value.
        pts = pts.explode(index_parts=False, ignore_index=True)
        numeric_values = pd.to_numeric(pts[field], errors="coerce").to_numpy(dtype=np.float64)
        point_mask = pts.geometry.notna().to_numpy() & (pts.geometry.geom_type == "Point").to_numpy()
        coords = np.asarray(
            [(geometry.x, geometry.y) if is_point and not geometry.is_empty else (np.nan, np.nan)
             for geometry, is_point in zip(pts.geometry, point_mask)],
            dtype=np.float64,
        )
        valid_mask = point_mask & np.isfinite(numeric_values) & np.isfinite(coords).all(axis=1)
        coords = coords[valid_mask]
        values = numeric_values[valid_mask]
        if len(coords) < 3:
            return "错误：至少需要3个具有有效点几何和有限数值属性的采样点进行插值"
        if method == "rbf" and len(coords) > max_rbf_points:
            return f"插值失败: RBF 最多支持 {max_rbf_points} 个有效点，请先抽样或改用 IDW"
        distance_pairs = resolution * resolution * len(coords)
        if distance_pairs > max_distance_pairs:
            return (f"插值失败: 当前网格与样本组合需要 {distance_pairs:,} 次距离计算，"
                    f"超过单次上限 {max_distance_pairs:,}；请降低 resolution 或减少样本点")
        xs = coords[:, 0]
        ys = coords[:, 1]
        center_lon = float((xs.min() + xs.max()) / 2)
        center_lat = float((ys.min() + ys.max()) / 2)
        xmin, ymin, xmax, ymax = xs.min(), ys.min(), xs.max(), ys.max()
        pad_x = (xmax - xmin) * 0.05 or 0.01
        pad_y = (ymax - ymin) * 0.05 or 0.01
        if xmax - xmin + 2 * pad_x > 6:
            return "插值失败: 单次范围超过 6° 经度，请按局部区域分区后再插值"
        if ymin - pad_y < -80 or ymax + pad_y > 84:
            return "插值失败: 当前点范围超出 UTM 适用纬度，请先按区域分区处理"
        if xs.min() < -180 or xs.max() > 180 or ys.min() < -90 or ys.max() > 90:
            return "插值失败: 点坐标超出 EPSG:4326 经纬度范围，请检查输入 CRS"
        metric_crs = _get_utm_crs(center_lon, center_lat)
        from pyproj import Transformer
        to_metric = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True)
        metric_xs, metric_ys = to_metric.transform(xs, ys)
        # 生成规则网格
        # y 方向必须递减生成：栅格与影像的约定是 row 0 = 北（y 最大）。
        # 按 y 递增生成的话 row 0 是南，PNG 交给 Leaflet 叠加后整张图会南北翻转，
        # 高值区显示在地图下方。
        grid_x, grid_y = np.meshgrid(
            np.linspace(xmin - pad_x, xmax + pad_x, resolution),
            np.linspace(ymax + pad_y, ymin - pad_y, resolution)
        )
        grid_metric_x, grid_metric_y = to_metric.transform(grid_x, grid_y)
        if method == "idw":
            # 反距离加权
            from scipy.spatial.distance import cdist
            flat_grid = np.column_stack([grid_metric_x.ravel(), grid_metric_y.ravel()])
            pts_xy = np.column_stack([metric_xs, metric_ys])
            flat_values = np.empty(len(flat_grid), dtype=np.float64)
            rows_per_batch = max(1, distance_batch_pairs // len(pts_xy))
            for start in range(0, len(flat_grid), rows_per_batch):
                stop = min(start + rows_per_batch, len(flat_grid))
                dist = cdist(flat_grid[start:stop], pts_xy)
                np.maximum(dist, 1e-10, out=dist)
                weights = 1.0 / (dist * dist)
                flat_values[start:stop] = np.dot(weights, values) / weights.sum(axis=1)
            z = flat_values.reshape(grid_x.shape)
        elif method == "rbf":
            from scipy import interpolate
            rbf = interpolate.Rbf(metric_xs, metric_ys, values, function='multiquadric')
            flat_x = grid_metric_x.ravel()
            flat_y = grid_metric_y.ravel()
            flat_values = np.empty(len(flat_x), dtype=np.float64)
            rows_per_batch = max(1, distance_batch_pairs // len(coords))
            for start in range(0, len(flat_x), rows_per_batch):
                stop = min(start + rows_per_batch, len(flat_x))
                flat_values[start:stop] = rbf(flat_x[start:stop], flat_y[start:stop])
            z = flat_values.reshape(grid_x.shape)
        vmin, vmax = np.nanmin(z), np.nanmax(z)
        if np.isclose(vmin, vmax):
            return f"错误：插值结果无变化（值={vmin:.2f}）"
        norm = (z - vmin) / (vmax - vmin + 1e-10)
        norm = np.clip(norm, 0, 1)
        import matplotlib
        cmap = matplotlib.colormaps['viridis']
        rgba = cmap(norm)
        rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
        nan_mask = ~np.isfinite(z)
        if np.any(nan_mask):
            rgb[nan_mask] = 0
        from PIL import Image
        img = Image.fromarray(rgb)
        import rasterio
        from rasterio.transform import from_bounds
        transform = from_bounds(xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y, resolution, resolution)
        base_out_name = os.path.basename(f"{name}_{method}")
        # Use a per-run unique namespace before writing. Both output paths derive
        # from this name, so concurrent calls cannot share their TIFF or PNG.
        with _state_lock:
            out_name = _disambiguate_layer_name(f"{base_out_name}_{uuid.uuid4().hex}")
        raster_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        raster_values = np.where(np.isfinite(z), z, np.nan).astype("float32")
        with rasterio.open(
            raster_path, "w", driver="GTiff", width=resolution, height=resolution,
            count=1, dtype="float32", crs="EPSG:4326", transform=transform,
            nodata=float("nan"),
        ) as dst:
            dst.write(raster_values, 1)
            dst.set_band_description(1, f"{field} ({method.upper()} interpolation)")
        label = f"空间插值（{method.upper()}，字段 {field}）"
        with rasterio.open(raster_path) as result_src:
            _raster_preview_op(
                result_src, raster_values, out_name, label, preview_image=img,
                source_layer=name, source_label="空间插值",
                quality_warnings=["范围为样本点外接区域扩展 5%；区域外结果属于外推，解释时请谨慎"],
            )
        return (f"已生成并注册 {method.upper()} 插值栅格「{out_name}」（{resolution}×{resolution}），"
                f"值范围 [{vmin:.2f}, {vmax:.2f}]；字段单位未提供")
    except Exception as e:
        import traceback
        return f"插值失败: {str(e)[:300]}"



@tool
def clip_raster(layer_name: str, clip_layer_name: str, output_name: str = "") -> str:
    """用矢量面裁剪栅格图层，保留面内的栅格像元。
    layer_name: 栅格图层名（上传的GeoTIFF）；clip_layer_name: 矢量裁剪面图层名；
    output_name: 结果图层名（可选，默认自动生成）。
    结果作为新栅格图层叠加到地图。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的GeoTIFF文件，请先上传"

        import geopandas as gpd
        import rasterio
        from rasterio.mask import mask as rio_mask
        from rasterio.transform import array_bounds
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        from shapely.geometry import Polygon, MultiPolygon

        clip_info = _registered_layers.get(clip_layer_name)
        if not clip_info:
            matches = [n for n in _registered_layers.keys() if clip_layer_name in n]
            if len(matches) == 1:
                clip_info = _registered_layers[matches[0]]
                clip_layer_name = matches[0]
            elif len(matches) > 1:
                return f"错误：找到多个匹配：{', '.join(matches)}，请指定完整名称"
            else:
                return f"错误：未找到裁剪面图层 '{clip_layer_name}'"

        clip_gdf = gpd.GeoDataFrame.from_features(clip_info["geojson"]["features"], crs="EPSG:4326")
        if clip_gdf.empty:
            return f"错误：裁剪面图层 '{clip_layer_name}' 为空"

        # 合并所有面要素为一个几何体
        union_geom = clip_gdf.geometry.union_all()
        if union_geom.is_empty:
            return "错误：裁剪面几何为空"
        if union_geom.geom_type not in ("Polygon", "MultiPolygon"):
            return "错误：裁剪面必须是面要素"

        with rasterio.open(tif_path) as src:
            # 将裁剪面转为栅格 CRS
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                clip_gdf_proj = clip_gdf.to_crs(src.crs)
            else:
                clip_gdf_proj = clip_gdf

            # 提取裁剪面几何列表
            geoms = [g for g in clip_gdf_proj.geometry.values if not g.is_empty]

            try:
                out_image, out_transform = rio_mask(src, geoms, crop=True, filled=False)
            except Exception:
                return f"裁剪失败：裁剪面与栅格无重叠或几何无效"

            if out_image.shape[1] == 0 or out_image.shape[2] == 0:
                return "错误：裁剪结果为空：裁剪面与栅格无重叠区域"

            bounds = list(array_bounds(out_image.shape[1], out_image.shape[2], out_transform))
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))

            # 处理波段
            if out_image.shape[0] == 1:
                masked_band = np.ma.asarray(out_image[0])
                data = np.asarray(masked_band.data, dtype=np.float64)
                valid = ~np.ma.getmaskarray(masked_band) & np.isfinite(data)
                if not np.any(valid):
                    return "错误：裁剪结果为空"
                vmin, vmax = np.nanmin(data[valid]), np.nanmax(data[valid])
                import matplotlib
                cmap_obj = matplotlib.colormaps['viridis']
                if vmax > vmin:
                    norm_data = np.clip((data - vmin) / (vmax - vmin), 0, 1)
                else:
                    norm_data = np.full(data.shape, 0.5, dtype=np.float64)
                norm_data[~valid] = 0
                rgba = cmap_obj(norm_data)
                rgba[:, :, 3] = valid.astype(np.float64)
                rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
                alpha = (valid.astype(np.uint8) * 255)
            else:
                # 多波段：取前3波段合成RGB
                bands = []
                band_validity = []
                for i in range(min(3, out_image.shape[0])):
                    masked_band = np.ma.asarray(out_image[i])
                    b = np.asarray(masked_band.data, dtype=np.float64)
                    valid_band = ~np.ma.getmaskarray(masked_band) & np.isfinite(b)
                    band_validity.append(valid_band)
                    p2, p98 = np.percentile(b[valid_band], [2, 98]) if np.any(valid_band) else (0, 1)
                    if p98 > p2:
                        b = np.clip((b - p2) / (p98 - p2) * 255, 0, 255).astype(np.uint8)
                    else:
                        b = np.zeros_like(b, dtype=np.uint8)
                    b[~valid_band] = 0
                    bands.append(b)
                while len(bands) < 3:
                    bands.append(np.zeros_like(bands[0], dtype=np.uint8))
                rgb = np.stack(bands, axis=-1)
                alpha = (np.logical_and.reduce(band_validity).astype(np.uint8) * 255)

            rgba_image = np.dstack((rgb, alpha))
            img = Image.fromarray(rgba_image)
            with _state_lock:
                if output_name:
                    base_out_name = os.path.basename(str(output_name).replace("\\", "/"))
                    base_out_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', base_out_name).strip(' .')
                    if not base_out_name:
                        return "错误：输出图层名称无效"
                else:
                    base_out_name = (
                        f"{_safe_layer_export_stem(layer_name)}_{uuid.uuid4().hex}_clip_"
                        f"{_safe_layer_export_stem(clip_layer_name)}"
                    )
                out_name = base_out_name
                suffix = 1
                while os.path.exists(os.path.join(upload_dir, f"{out_name}.png")):
                    out_name = f"{base_out_name}_{suffix}"
                    suffix += 1
                out_path = os.path.join(upload_dir, f"{out_name}.png")
                img.save(out_path)

                from urllib.parse import quote
                preview_name = f"{out_name}.png"
                _pending_layer_ops.append({
                    "action": "dem_result",
                    "name": preview_name,
                    "url": f"/output/uploads/{quote(preview_name, safe='')}",
                    "bounds": bounds,
                    "label": f"栅格裁剪: {layer_name}",
                })

            feat_count = len(clip_gdf)
            return (f"已用 {clip_layer_name}（{feat_count} 个面）裁剪 {layer_name}"
                    f"，结果「{out_name}」已叠加到地图")

    except Exception as e:
        import traceback
        return f"栅格裁剪失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"



@tool
def ndwi_analysis(layer_name: str, green_band: int = 2, nir_band: int = 4) -> str:
    """计算归一化水体指数 NDWI = (Green - NIR) / (Green + NIR)。
    - layer_name: GeoTIFF 图层名。
    - green_band: 绿光波段序号(从1开始，默认 2；Landsat 8/9为3，Sentinel-2为3)。
    - nir_band: 近红外波段序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。"""
    def calc(bands):
        import numpy as np
        g = bands.get("green"); n = bands.get("nir")
        if g is None or n is None:
            raise ValueError("需要 Green 和 NIR 波段")
        return (g - n) / (g + n + 1e-10)
    return _calc_spectral_index(layer_name, "ndwi", calc, "Blues", "NDWI 归一化水体指数",
                                 band_map={"green": green_band, "nir": nir_band})



@tool
def ndbi_analysis(layer_name: str, swir_band: int = 5, nir_band: int = 4) -> str:
    """计算归一化建筑指数 NDBI = (SWIR - NIR) / (SWIR + NIR)。
    - layer_name: GeoTIFF 图层名。
    - swir_band: 短波红外序号(从1开始，默认 5；Landsat 8/9为6，Sentinel-2为11)。
    - nir_band: 近红外波段序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。"""
    def calc(bands):
        import numpy as np
        s = bands.get("swir"); n = bands.get("nir")
        if s is None or n is None:
            raise ValueError("需要 SWIR 和 NIR 波段")
        return (s - n) / (s + n + 1e-10)
    return _calc_spectral_index(layer_name, "ndbi", calc, "OrRd", "NDBI 归一化建筑指数",
                                 band_map={"swir": swir_band, "nir": nir_band})



@tool
def evi_analysis(layer_name: str, nir_band: int = 4, red_band: int = 3, blue_band: int = 1) -> str:
    """计算增强植被指数 EVI = 2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)。
    - layer_name: GeoTIFF 图层名。
    - nir_band: 近红外序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。
    - red_band: 红光波段序号(从1开始，默认 3；Landsat 8/9为4，Sentinel-2为4)。
    - blue_band: 蓝光波段序号(从1开始，默认 1；Landsat 8/9为2，Sentinel-2为2)。
    输出截断到 [-1, 1] 后渲染（超出极值的像元压平到边界），有效植被区通常为 0~1。"""
    def calc(bands):
        import numpy as np
        n = bands.get("nir"); r = bands.get("red"); b = bands.get("blue")
        if n is None or r is None or b is None:
            raise ValueError("需要 NIR、Red、Blue 三个波段")
        return 2.5 * (n - r) / (n + 6 * r - 7.5 * b + 1.0 + 1e-10)
    return _calc_spectral_index(layer_name, "evi", calc, "RdYlGn", "EVI 增强植被指数",
                                 band_map={"nir": nir_band, "red": red_band, "blue": blue_band})



@tool
def ndmi_analysis(layer_name: str, nir_band: int = 4, swir_band: int = 5) -> str:
    """计算归一化水分指数 NDMI = (NIR - SWIR) / (NIR + SWIR)。
    - layer_name: GeoTIFF 图层名。
    - nir_band: 近红外波段序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。
    - swir_band: 短波红外序号(从1开始，默认 5；Landsat 8/9为6，Sentinel-2为11)。"""
    def calc(bands):
        import numpy as np
        n = bands.get("nir"); s = bands.get("swir")
        if n is None or s is None:
            raise ValueError("需要 NIR 和 SWIR 波段")
        return (n - s) / (n + s + 1e-10)
    return _calc_spectral_index(layer_name, "ndmi", calc, "YlGnBu", "NDMI 归一化水分指数",
                                 band_map={"nir": nir_band, "swir": swir_band})



@tool
def calc_spectral_index(
    layer_name: str,
    index: Literal["ndvi", "ndwi", "ndbi", "evi", "ndmi"],
    red_band: int = 3,
    nir_band: int = 4,
    green_band: int = 2,
    swir_band: int = 5,
    blue_band: int = 1,
) -> str:
    """统一计算多光谱遥感指数（NDVI/NDWI/NDBI/EVI/NDMI）。
    - layer_name: 多光谱 GeoTIFF 图层名。
    - index: 必选指数类型，可选 'ndvi'(植被) / 'ndwi'(水体) / 'ndbi'(建筑) / 'evi'(增强植被) / 'ndmi'(地表水分)。
    - red_band / nir_band / green_band / swir_band / blue_band: 传感器对应波段序号（默认适配常规RGBN传感器；Landsat/Sentinel按需配置）。"""
    idx = (index or "ndvi").strip().lower()
    if idx == "ndvi":
        return ndvi_analysis.invoke({"layer_name": layer_name, "red_band": red_band, "nir_band": nir_band})
    elif idx == "ndwi":
        return ndwi_analysis.invoke({"layer_name": layer_name, "green_band": green_band, "nir_band": nir_band})
    elif idx == "ndbi":
        return ndbi_analysis.invoke({"layer_name": layer_name, "swir_band": swir_band, "nir_band": nir_band})
    elif idx == "evi":
        return evi_analysis.invoke({"layer_name": layer_name, "nir_band": nir_band, "red_band": red_band, "blue_band": blue_band})
    elif idx == "ndmi":
        return ndmi_analysis.invoke({"layer_name": layer_name, "nir_band": nir_band, "swir_band": swir_band})
    else:
        return f"错误：不支持的遥感指数: {index}，支持: ndvi, ndwi, ndbi, evi, ndmi"



@tool
def zonal_statistics(raster_layer: str, zone_layer: str, stat: str = "mean") -> str:
    """分区统计（Zonal Statistics）：用面图层对栅格分区，统计每个面内栅格值，
    结果作为新图层上图（分区面属性增加 zonal_mean/zonal_sum/zonal_min/zonal_max/count）。
    raster_layer: 栅格图层名（上传的GeoTIFF）；zone_layer: 矢量面图层；stat: 主统计量（mean/sum/min/max）。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask
        from rasterio.warp import transform_geom
        from shapely.geometry import mapping

        upload_dir = os.path.join(get_temp_output_dir(), "uploads")
        tif_path = _find_uploaded_tif(raster_layer)
        if tif_path is None:
            return f"错误：未找到栅格文件「{raster_layer}」，请先上传 GeoTIFF"

        zones, zone_name = _layer_to_gdf(zone_layer)
        if zones is None:
            return zone_name
        with rasterio.open(tif_path) as src:
            if zones.crs is None or zones.crs.to_epsg() != 4326:
                zones = zones.to_crs(4326)
            feats = []
            for idx, row in zones.iterrows():
                geom4326 = row.geometry
                try:
                    geom_src = transform_geom("EPSG:4326", src.crs, mapping(geom4326))
                except Exception:
                    geom_src = mapping(geom4326)
                try:
                    out_img, _ = rio_mask(src, [geom_src], crop=True, filled=False)
                    arr = out_img[0]
                    arr_data = np.ma.getdata(arr)
                    mask = ~np.ma.getmaskarray(arr) & np.isfinite(arr_data)
                    vals = arr_data[mask].astype("float64")
                except Exception:
                    vals = np.array([])
                props = dict(row.drop(labels="geometry").items()) if hasattr(row, "drop") else {}
                props = {k: (v.item() if hasattr(v, "item") else v) for k, v in props.items()}
                if vals.size:
                    props["zonal_mean"] = round(float(vals.mean()), 4)
                    props["zonal_sum"] = round(float(vals.sum()), 4)
                    props["zonal_min"] = round(float(vals.min()), 4)
                    props["zonal_max"] = round(float(vals.max()), 4)
                    props["zonal_count"] = int(vals.size)
                else:
                    props["zonal_mean"] = None
                    props["zonal_sum"] = None
                    props["zonal_min"] = None
                    props["zonal_max"] = None
                    props["zonal_count"] = 0
                props["name"] = props.get("name") or f"{zone_name}_区{idx + 1}"
                feats.append({"type": "Feature", "geometry": mapping(geom4326), "properties": props})
        out_fc = {"type": "FeatureCollection", "features": feats}
        base_out_name = f"{zone_name}_分区统计"
        with _state_lock:
            out_name = _disambiguate_layer_name(base_out_name)
            _push_layer(out_name, out_fc, {"color": "#7b1fa2", "weight": 2, "fillOpacity": 0.15})
            _register_layer(out_name, out_fc)
        ok_count = sum(1 for f in feats if f["properties"]["zonal_count"] > 0)
        key = {"mean": "zonal_mean", "sum": "zonal_sum", "min": "zonal_min", "max": "zonal_max"}.get(
            str(stat).lower(), "zonal_mean")
        preview = [f["properties"].get(key) for f in feats[:5]]
        return (f"分区统计完成（{stat}）：{ok_count}/{len(feats)} 个分区落在栅格范围内，"
                f"结果图层「{out_name}」已上图（含 zonal_mean/sum/min/max/count 字段）。"
                f"{key} 前5值: {preview}")
    except Exception as e:
        return f"分区统计失败: {str(e)[:300]}"



@tool
def raster_resample(layer_name: str, scale_factor: float = 2.0, method: str = "bilinear") -> str:
    """栅格重采样：按倍数缩放栅格分辨率（scale_factor>1 缩小/更粗，<1 放大/更细），
    method 可选 nearest / bilinear / cubic。结果 GeoTIFF 落盘并出预览叠加图层。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        resampling = {"nearest": Resampling.nearest, "bilinear": Resampling.bilinear,
                      "cubic": Resampling.cubic}.get(str(method).lower(), Resampling.bilinear)
        out_name = f"{os.path.splitext(os.path.basename(tif_path))[0]}_{uuid.uuid4().hex}_重采样"
        out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        with rasterio.open(tif_path) as src:
            scale = max(0.05, min(32.0, float(scale_factor)))
            new_w = max(1, int(src.width / scale))
            new_h = max(1, int(src.height / scale))
            data = src.read(masked=True, out_shape=(src.count, new_h, new_w), resampling=resampling)
            profile = src.profile.copy()
            profile.update(width=new_w, height=new_h,
                           transform=src.transform * src.transform.scale(
                               src.width / new_w, src.height / new_h))
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(data.filled(src.nodata if src.nodata is not None else 0))
                # GeoTIFF dataset masks are shared across bands; preserve every
                # invalid location so downstream tools do not treat it as data.
                dst.write_mask((~np.ma.getmaskarray(data).any(axis=0)).astype("uint8") * 255)
            note = _raster_preview_op(
                src, data.filled(np.nan), out_name, f"栅格重采样 x{scale} ({method})",
                **_raster_preview_context(layer_name),
            )
        return (f"重采样完成：{scale}x → {new_w}x{new_h} 像元，method={method}，"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"重采样失败: {str(e)[:300]}"



@tool
def raster_reproject(layer_name: str, target_crs: str = "EPSG:4326") -> str:
    """栅格重投影：把 GeoTIFF 转到目标坐标系（默认 EPSG:4326，供地图叠加），
    结果 GeoTIFF 落盘并出预览叠加图层。矢量重投影用 convert_crs。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject as rio_reproject

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        out_name = f"{os.path.splitext(os.path.basename(tif_path))[0]}_{uuid.uuid4().hex}_重投影"
        out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        with rasterio.open(tif_path) as src:
            transform, width, height = calculate_default_transform(
                src.crs, target_crs, src.width, src.height, *src.bounds)
            profile = src.profile.copy()
            profile.update(crs=target_crs, transform=transform, width=width, height=height,
                           dtype="float64", nodata=float("nan"))
            bands = []
            for i in range(1, src.count + 1):
                source = src.read(i, masked=True).astype("float64").filled(np.nan)
                source[~np.isfinite(source)] = np.nan
                dst_arr = np.full((height, width), np.nan, dtype="float64")
                rio_reproject(
                    source=source,
                    destination=dst_arr,
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=transform, dst_crs=target_crs,
                    src_nodata=np.nan, dst_nodata=np.nan,
                    resampling=Resampling.bilinear)
                bands.append(dst_arr)
            stacked = np.stack(bands)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(stacked)
            with rasterio.open(out_path) as resrc:
                preview = resrc.read()
                note = _raster_preview_op(
                    resrc, preview, out_name, f"栅格重投影 → {target_crs}",
                    **_raster_preview_context(layer_name),
                )
        return (f"重投影完成：{src.crs} → {target_crs}，{width}x{height} 像元，"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"重投影失败: {str(e)[:300]}"



@tool
def raster_reclassify(layer_name: str, mapping: str = "", method: str = "mapping", classes: int = 5) -> str:
    """栅格重分类：把连续栅格值按规则重新编码为类别值，结果 GeoTIFF 落在源文件旁并出预览图层。
    - layer_name: 栅格图层名（上传的 GeoTIFF 图层名）。
    - mapping: 区间映射串，分号分隔，形如 '0-10=1;10-50=2;50+=3'；'a-b' 表示 a<=v<b（左闭右开），
      'a+' 表示 v>=a；等号右边为类别值（非数字时按规则出现顺序编号 1,2,3...）。
    - method: 重分类方式，'mapping'(按 mapping 串，默认) / 'equal_interval'(等间距分级) / 'quantile'(分位数分级)。
    - classes: equal_interval / quantile 的分级数（整数>=2，默认 5）。
    输入 nodata 像元保持 nodata；未命中任何规则的像元也输出为 nodata。"""
    try:
        import numpy as np
        import rasterio

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        method_key = str(method or "mapping").strip().lower()
        supported_methods = {
            "mapping", "equal_interval", "equal", "interval",
            "quantile", "quantiles", "percentile",
        }
        if method_key not in supported_methods:
            return "重分类失败：method 必须是 mapping、equal_interval 或 quantile"
        with rasterio.open(tif_path) as src:
            data = src.read(1, masked=True).astype("float64").filled(np.nan)
            data[~np.isfinite(data)] = np.nan
            nodata = src.nodata
            valid = np.isfinite(data)
            if nodata is not None:
                # GeoTIFF NoData 是显式哨兵值；容差比较会吞掉其附近的合法数据。
                valid &= data != nodata
            if not valid.any():
                return f"错误：栅格「{layer_name}」没有有效像元，无法重分类"
            vals = data[valid]
            if method_key in ("equal_interval", "equal", "interval"):
                try:
                    class_count = float(classes)
                except (TypeError, ValueError):
                    class_count = float("nan")
                if not math.isfinite(class_count) or not class_count.is_integer() or class_count < 2:
                    return "重分类失败：分级数必须是大于等于 2 的有限整数"
                n_cls = int(class_count)
                lo_v, hi_v = float(np.min(vals)), float(np.max(vals))
                if hi_v <= lo_v:
                    codes = np.ones(data.shape, dtype="float64")
                    desc = f"equal_interval {n_cls} 级（值域退化为常数 {lo_v:.6g}）"
                else:
                    edges = np.linspace(lo_v, hi_v, n_cls + 1)
                    codes = (np.digitize(data, edges[1:-1], right=False) + 1).astype("float64")
                    desc = f"equal_interval {n_cls} 级 [{lo_v:.6g}, {hi_v:.6g}]"
            elif method_key in ("quantile", "quantiles", "percentile"):
                try:
                    class_count = float(classes)
                except (TypeError, ValueError):
                    class_count = float("nan")
                if not math.isfinite(class_count) or not class_count.is_integer() or class_count < 2:
                    return "重分类失败：分级数必须是大于等于 2 的有限整数"
                n_cls = int(class_count)
                edges = np.unique(np.quantile(vals, np.linspace(0.0, 1.0, n_cls + 1)))
                if edges.size < 2:
                    codes = np.ones(data.shape, dtype="float64")
                    desc = f"quantile 分级（值域退化，实际 1 级）"
                else:
                    codes = (np.digitize(data, edges[1:-1], right=False) + 1).astype("float64")
                    desc = f"quantile 分位分级（请求 {n_cls} 级，实际 {edges.size - 1} 级）"
            else:
                rules = _parse_reclass_rules(mapping)
                if not rules:
                    return "错误：mapping 为空或格式不正确，示例：'0-10=1;10-50=2;50+=3'"
                conds = [(data >= lo) & (data < hi) & valid for lo, hi, _v in rules]
                choices = [v for _lo, _hi, v in rules]
                codes = np.select(conds, choices, default=np.nan).astype("float64")
                desc = f"mapping {len(rules)} 条规则"
            out = np.full(data.shape, np.nan, dtype="float64")
            out[valid] = np.asarray(codes, dtype="float64")[valid]
            out_nodata = nodata if nodata is not None else np.nan
            arr = np.where(np.isfinite(out), out, out_nodata)
            # The stored GeoTIFF may use a project asset hash as its filename;
            # keep the derived layer tied to the user-visible input layer name.
            out_name = f"{_safe_layer_export_stem(layer_name)}_{uuid.uuid4().hex}_重分类"
            out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
            with rasterio.open(out_path, "w", **_raster_out_profile(src, out_nodata)) as dst:
                dst.write(arr.astype("float32"), 1)
            note = _raster_preview_op(
                src, arr[None, :, :], out_name, f"栅格重分类（{desc}）",
                **_raster_preview_context(layer_name, value_units="类别编码（无量纲）"),
            )
            classified = out[valid]
            classified = classified[np.isfinite(classified)]
            uniq = np.unique(classified)
            hit = int(classified.size)
            miss = int(valid.sum() - hit)
        return (f"重分类完成（{desc}）：类别 {len(uniq)} 个，有效像元 {hit}/{int(valid.sum())}"
                f"（{miss} 个未命中任何规则），结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"栅格重分类失败: {str(e)[:300]}"



@tool
def raster_focal_stats(layer_name: str, stat: str = "mean", size: int = 3) -> str:
    """栅格焦点统计：按滑动窗口对每个像元做邻域统计，结果 GeoTIFF 落在源文件旁并出预览图层。
    - layer_name: 栅格图层名（上传的 GeoTIFF 图层名）。
    - stat: 统计量，'mean'(均值) / 'median'(中位数) / 'min'(最小值) / 'max'(最大值) /
      'std'(标准差) / 'range'(极差 max-min) / 'majority'(众数)。
    - size: 窗口边长（奇数，仅支持 3 / 5 / 7，默认 3）。
    统计自动忽略 nodata 与无效像元；输入 nodata 像元输出仍为 nodata。"""
    try:
        import numpy as np
        import rasterio

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        s = int(size)
        if s % 2 == 0:
            return f"错误：窗口大小 size 必须为奇数（3/5/7），收到 {size}"
        if s not in (3, 5, 7):
            return f"错误：窗口大小 size 仅支持 3、5、7，收到 {size}"
        key = str(stat or "mean").strip().lower()
        key = {"average": "mean", "avg": "mean", "mode": "majority", "max-min": "range",
               "maximum": "max", "minimum": "min"}.get(key, key)
        if key not in ("mean", "median", "min", "max", "std", "range", "majority"):
            return f"错误：未知统计量 stat: {stat}，可选 mean/median/min/max/std/range/majority"
        with rasterio.open(tif_path) as src:
            data = src.read(1, masked=True).astype("float64").filled(np.nan)
            nodata = src.nodata
            valid = np.isfinite(data)
            if nodata is not None:
                valid &= data != nodata
            if not valid.any():
                return f"错误：栅格「{layer_name}」没有有效像元，无法做焦点统计"
            from scipy import ndimage
            filled = np.where(valid, data, np.nan)
            if key in ("min", "max", "range"):
                mn = ndimage.minimum_filter(np.where(valid, data, np.inf), size=s, mode="nearest")
                mx = ndimage.maximum_filter(np.where(valid, data, -np.inf), size=s, mode="nearest")
                res = {"min": mn, "max": mx, "range": mx - mn}[key]
            elif key == "majority":
                def _mode(v):
                    v = v[np.isfinite(v)]
                    if v.size == 0:
                        return np.nan
                    _rounded, inverse = np.unique(np.round(v, 6), return_inverse=True)
                    rounded_counts = np.bincount(inverse)
                    winning_group = int(np.argmax(rounded_counts))
                    original_values, original_counts = np.unique(
                        v[inverse == winning_group], return_counts=True,
                    )
                    return float(original_values[int(np.argmax(original_counts))])
                res = ndimage.generic_filter(filled, _mode, size=s, mode="nearest")
            else:
                f = np.where(valid, data, 0.0)
                w = valid.astype("float64")
                cnt = np.maximum(ndimage.uniform_filter(w, size=s, mode="nearest"), 1e-12)
                m1 = ndimage.uniform_filter(f, size=s, mode="nearest") / cnt
                if key == "mean":
                    res = m1
                elif key == "std":
                    m2 = ndimage.uniform_filter(f * f, size=s, mode="nearest") / cnt
                    res = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
                else:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        res = ndimage.generic_filter(filled, np.nanmedian, size=s, mode="nearest")
            res = np.where(valid, res, np.nan)
            fin = res[np.isfinite(res)]
            if fin.size == 0:
                return f"焦点统计失败: 窗口 {s}x{s} 内没有有效像元"
            out_nodata = nodata if nodata is not None else np.nan
            arr = np.where(np.isfinite(res), res, out_nodata)
            out_name = f"{_safe_layer_export_stem(layer_name)}_{uuid.uuid4().hex}_焦点{key}"
            out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
            with rasterio.open(out_path, "w", **_raster_out_profile(src, out_nodata)) as dst:
                dst.write(arr.astype("float32"), 1)
            note = _raster_preview_op(
                src, arr[None, :, :], out_name, f"焦点统计 {key} {s}x{s}",
                **_raster_preview_context(layer_name),
            )
            rmin, rmax = float(fin.min()), float(fin.max())
        return (f"焦点统计完成（{key}，窗口 {s}x{s}）：值域 [{rmin:.6g}, {rmax:.6g}]，"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"焦点统计失败: {str(e)[:300]}"



@tool
def euclidean_distance(layer_name: str, source_value: float = None, out_name: str = "") -> str:
    """欧氏距离分析：计算每个像元到最近源像元的平面距离（像元中心，单位与栅格坐标系一致），
    结果 GeoTIFF 落在源文件旁并出预览图层。
    - layer_name: 栅格图层名（上传的 GeoTIFF 图层名）。
    - source_value: 源像元取值，指定时把等于该值的像元视为源；缺省(None)时把非零且非 nodata 的像元视为源。
    - out_name: 输出文件名（可不带 .tif），留空时自动命名为 '<源文件名>_欧氏距离'。
    输入 nodata 像元输出仍为 nodata。"""
    try:
        import numpy as np
        import rasterio
        from scipy import ndimage

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        suffix = str(out_name or "").strip() or f"{_safe_layer_export_stem(layer_name)}_欧氏距离"
        suffix = os.path.splitext(os.path.basename(suffix))[0]
        with rasterio.open(tif_path) as src:
            if src.crs and src.crs.is_geographic:
                return (f"欧氏距离失败: 输入坐标系 {src.crs.to_string()} 使用经纬度角度；"
                        "不能把角度当作地面距离，请先重投影到适用的投影坐标系")
            if src.crs and not src.crs.is_projected:
                return (f"欧氏距离失败: 暂不支持坐标系 {src.crs.to_string()}；"
                        "请先转换到投影坐标系")
            transform = src.transform
            col_vec = (float(transform.a), float(transform.d))
            row_vec = (float(transform.b), float(transform.e))
            dot = col_vec[0] * row_vec[0] + col_vec[1] * row_vec[1]
            if abs(dot) > 1e-10 * max(1.0, math.hypot(*col_vec) * math.hypot(*row_vec)):
                return "欧氏距离失败: 栅格像元存在斜切变换；请先重采样到正交网格"
            sampling = (math.hypot(*row_vec), math.hypot(*col_vec))
            if src.crs:
                distance_units = src.crs.linear_units or "投影坐标单位"
                distance_warnings = []
            else:
                distance_units = "栅格单位（CRS 未定义）"
                distance_warnings = ["源栅格缺少 CRS；欧氏距离按栅格坐标单位计算，地面距离含义未验证"]
            data = src.read(1, masked=True).astype("float64").filled(np.nan)
            nodata = src.nodata
            valid = np.isfinite(data)
            if nodata is not None:
                valid &= data != nodata
            if source_value is None or str(source_value).strip() == "":
                source = valid & (data != 0)
                src_desc = "非零有效像元"
            else:
                sv = float(source_value)
                source_dtype = np.dtype(src.dtypes[0])
                if source_dtype.kind == "f":
                    # Match the value as it is representable in the source raster's
                    # floating dtype; np.isclose's relative tolerance can select
                    # distinct large-valued classes as the same source.
                    match_value = float(np.asarray(sv, dtype=source_dtype).item())
                else:
                    match_value = sv
                source = valid & (data == match_value)
                src_desc = f"值={sv:g}"
            n_src = int(source.sum())
            if n_src == 0:
                return f"错误：栅格「{layer_name}」中找不到源像元（{src_desc}），无法计算欧氏距离"
            dist = ndimage.distance_transform_edt(~source, sampling=sampling).astype("float64")
            dist[~valid] = np.nan
            dmax = float(np.nanmax(dist))
            out_nodata = nodata if nodata is not None else np.nan
            arr = np.where(np.isfinite(dist), dist, out_nodata)
            out_path = os.path.join(_raster_output_dir(), suffix + ".tif")
            with rasterio.open(out_path, "w", **_raster_out_profile(src, out_nodata)) as dst:
                dst.write(arr.astype("float32"), 1)
            preview_context = _raster_preview_context(layer_name, value_units=distance_units)
            inherited_warnings = preview_context.get("quality_warnings") or []
            preview_context["quality_warnings"] = list(inherited_warnings) + [
                warning for warning in distance_warnings if warning not in inherited_warnings
            ]
            note = _raster_preview_op(
                src, arr[None, :, :], suffix, f"欧氏距离（源：{src_desc}）",
                **preview_context,
            )
        return (f"欧氏距离完成：源像元 {n_src} 个（{src_desc}），最大距离 {dmax:.6g}"
                f" {distance_units}（像元尺寸 {sampling[1]:g} x {sampling[0]:g} {distance_units}），"
                f"结果已保存 {suffix}.tif；{note}")
    except Exception as e:
        return f"欧氏距离分析失败: {str(e)[:300]}"



@tool
def raster_extract_by_mask(raster_layer: str, zone_layer: str, inside: bool = True) -> str:
    """按掩膜提取栅格：用矢量面图层裁剪栅格，保留面内（或面外）像元，
    结果 GeoTIFF 落在源文件旁并出预览图层。
    - raster_layer: 栅格图层名（上传的 GeoTIFF 图层名）。
    - zone_layer: 矢量面图层名（掩膜范围，支持 Polygon / MultiPolygon）。
    - inside: True(默认) 保留掩膜内像元；False 保留掩膜外像元。
    掩膜外的像元写为 nodata；结果保持源栅格的行列范围与地理变换不变。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask
        from rasterio.warp import transform_geom
        from shapely.geometry import mapping

        tif_path = _find_uploaded_tif(raster_layer)
        if tif_path is None:
            return f"错误：未找到栅格文件「{raster_layer}」，请先上传 GeoTIFF"
        zones, zone_name = _layer_to_gdf(zone_layer)
        if zones is None:
            return zone_name
        if zones.crs is None:
            return f"错误：掩膜图层「{zone_layer}」缺少 CRS，无法可靠转换坐标"
        if zones.crs.to_epsg() != 4326:
            zones = zones.to_crs(4326)
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return f"错误：栅格「{raster_layer}」缺少 CRS，无法可靠对齐掩膜；请先定义 CRS 后重新上传"
            geoms = []
            for geom in zones.geometry:
                if geom is None or geom.is_empty:
                    continue
                geoms.append(transform_geom(zones.crs.to_string(), src.crs, mapping(geom)))
            if not geoms:
                return f"错误：图层「{zone_layer}」没有可用的面几何，无法生成掩膜"
            out_nodata = src.nodata if src.nodata is not None else np.nan
            masked_arr, _out_transform = rio_mask(
                src, geoms, crop=False, filled=False, invert=not bool(inside),
            )
            arr = np.asarray(masked_arr.data, dtype="float32")
            arr[np.ma.getmaskarray(masked_arr)] = out_nodata
            band = arr[0]
            invalid = ~np.isfinite(band)
            if not np.isnan(out_nodata):
                invalid |= band == out_nodata
            keep = int((~invalid).sum())
            out_name = f"{_safe_layer_export_stem(raster_layer)}_掩膜{'内' if inside else '外'}_{uuid.uuid4().hex[:8]}"
            out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
            with rasterio.open(out_path, "w",
                               **_raster_out_profile(src, out_nodata, count=arr.shape[0])) as dst:
                dst.write(arr)
            note = _raster_preview_op(src, arr[0:1, :, :], out_name,
                                      f"按掩膜提取（{'保留面内' if inside else '保留面外'}）",
                                      **_raster_preview_context(raster_layer))
        return (f"按掩膜提取完成（{'保留面内' if inside else '保留面外'}）：有效像元 {keep}/{band.size}，"
                f"共 {arr.shape[0]} 个波段，结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"按掩膜提取失败: {str(e)[:300]}"



@tool
def feature_to_raster(layer_name: str, value_field: str = "", cell_size: float = 0.0, all_touched: bool = False) -> str:
    """矢量转栅格：把点/线/面要素按属性值烧录到栅格网格（ArcGIS FeatureToRaster 对应）。
    - layer_name: 矢量图层名（注册图层，EPSG:4326）。
    - value_field: 作为像元值的属性字段名；留空则全部烧录常量 1。
    - cell_size: 像元尺寸（度，与图层同单位）；0 = 自动取使长边约 256 像元的尺寸。
    - all_touched: true=像元被几何触碰即烧录；false（默认）=像元中心在几何内才烧录。
    结果 GeoTIFF 落盘并输出预览图层。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.features import rasterize
        from rasterio.transform import from_origin
        import types
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"错误：图层「{name}」没有要素，无法转栅格"
        try:
            requested_cell_size = float(cell_size)
        except (TypeError, ValueError, OverflowError):
            return "矢量转栅格失败：cell_size 必须是有限的非负数"
        if not np.isfinite(requested_cell_size) or requested_cell_size < 0:
            return "矢量转栅格失败：cell_size 必须是有限的非负数"
        minx, miny, maxx, maxy = gdf.total_bounds
        if not np.isfinite([minx, miny, maxx, maxy]).all():
            return "矢量转栅格失败：图层范围包含非有限坐标"
        span_x, span_y = maxx - minx, maxy - miny
        if requested_cell_size > 0:
            cs = requested_cell_size
        else:
            cs = max(span_x, span_y) / 256.0
            if cs <= 0:
                return "错误：图层范围为空，无法推导像元尺寸，请显式传 cell_size"
        if span_x <= 0:
            minx -= cs / 2
            maxx += cs / 2
            span_x = cs
        if span_y <= 0:
            miny -= cs / 2
            maxy += cs / 2
            span_y = cs
        width_ratio, height_ratio = span_x / cs, span_y / cs
        if not np.isfinite([width_ratio, height_ratio]).all():
            return "矢量转栅格失败：目标网格超过单次处理上限（400 万像元）；请增大 cell_size 或先裁剪图层范围"
        width = max(1, int(math.ceil(width_ratio)))
        height = max(1, int(math.ceil(height_ratio)))
        if width * height > 4_000_000:
            return (f"矢量转栅格失败：目标网格为 {width}×{height} 像元，超过单次处理上限（400 万像元）；"
                    "请增大 cell_size 或先裁剪图层范围")
        transform = from_origin(minx, maxy, cs, cs)
        nodata = 0
        if value_field:
            if value_field not in gdf.columns:
                return f"错误：未找到字段「{value_field}」，可用字段：{', '.join(map(str, gdf.columns))}"
            shapes_iter = []
            for geom, val in zip(gdf.geometry, gdf[value_field]):
                if geom is None or geom.is_empty or val is None:
                    continue
                try:
                    numeric_value = float(val)
                except (TypeError, ValueError):
                    return f"错误：字段「{value_field}」含非数值属性，矢量转栅格需要数值字段"
                if np.isnan(numeric_value):
                    continue
                if not np.isfinite(numeric_value):
                    return f"错误：字段「{value_field}」含非有限数值，无法烧录到栅格"
                shapes_iter.append((geom, numeric_value))
            # NaN is a distinct background marker so valid zero and negative values survive.
            fill_value = np.nan
            nodata = np.nan
            dtype = "float64"
        else:
            shapes_iter = ((geom, 1) for geom in gdf.geometry if geom is not None)
            fill_value = 0
            dtype = "uint8"
        arr = rasterize(
            shapes_iter, out_shape=(height, width), transform=transform,
            fill=fill_value, all_touched=bool(all_touched), dtype=dtype,
        )
        out_name = f"{_safe_layer_export_stem(name)}_{uuid.uuid4().hex}_转栅格"
        out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        profile = dict(driver="GTiff", height=height, width=width, count=1, dtype=arr.dtype.name,
                       crs="EPSG:4326", transform=transform, nodata=nodata)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(arr, 1)
        with rasterio.open(out_path) as _src_for_preview:
            note = _raster_preview_op(_src_for_preview, arr, out_name, f"矢量转栅格 {width}x{height}@{cs:.6g}")
        if value_field:
            burned_values = arr[np.isfinite(arr)]
            burned_count = int(burned_values.size)
            stat = (f"值域 {np.min(burned_values):.4g}~{np.max(burned_values):.4g}"
                    if burned_count else "无有效属性值")
        else:
            burned_count = int(np.count_nonzero(arr))
            stat = "常量 1"
        return (f"矢量转栅格完成：{width}x{height} 像元，像元尺寸 {cs:.6g}，已烧录 {burned_count} 个像元（{stat}）。"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"矢量转栅格失败: {str(e)[:300]}"



@tool
def raster_to_feature(layer_name: str, connectivity: int = 8, simplify: float = 0.0) -> str:
    """栅格转矢量：把分类栅格按连续同值区域矢量化为面图层（ArcGIS RasterToPolygon 对应）。
    - layer_name: 上传的 GeoTIFF 栅格名。
    - connectivity: 4 或 8，同值像元连通判定。
    - simplify: 面简化容差，单位与栅格 CRS 的坐标单位一致；0 = 不简化。
    输出面图层（含 value 属性），面数与面积统计随结果返回。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.features import shapes as rio_shapes
        from shapely.geometry import shape as shp_shape
        import geopandas as gpd
        try:
            conn_value = float(connectivity)
        except (TypeError, ValueError, OverflowError):
            return "栅格转矢量失败：connectivity 仅支持 4 或 8"
        if not np.isfinite(conn_value) or conn_value not in (4, 8):
            return "栅格转矢量失败：connectivity 仅支持 4 或 8"
        try:
            simplify_value = float(simplify)
        except (TypeError, ValueError, OverflowError):
            return "栅格转矢量失败：simplify 必须是有限的非负数"
        if not np.isfinite(simplify_value) or simplify_value < 0:
            return "栅格转矢量失败：simplify 必须是有限的非负数"
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        conn = int(conn_value)
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return "栅格转矢量失败：输入栅格缺少 CRS，无法可靠定位矢量结果；请先为栅格定义正确的坐标系"
            band = src.read(1, masked=True)
            arr = np.asarray(band.data)
            mask = ~np.ma.getmaskarray(band)
            if arr.dtype.kind == "f":
                mask &= np.isfinite(arr)
            if src.nodata is not None:
                mask &= arr != src.nodata
            geoms = []
            vals = []
            for geom, val in rio_shapes(arr, mask=mask, transform=src.transform, connectivity=conn):
                if val == 0 or val is None:
                    continue
                geoms.append(shp_shape(geom))
                vals.append(val)
            if not geoms:
                return "错误：栅格中没有可矢量化的有效像元（全为 nodata 或 0）"
            gdf = gpd.GeoDataFrame({"value": vals}, geometry=geoms, crs=src.crs)
        if simplify_value > 0:
            gdf["geometry"] = gdf.geometry.simplify(simplify_value, preserve_topology=True)
        # Preserve prior parameterized results instead of replacing the same
        # registered layer when connectivity or simplify changes.
        out_name = f"{layer_name}_转矢量_{uuid.uuid4().hex[:8]}"
        _gdf_to_layer(gdf, out_name)
        utm = gdf.estimate_utm_crs()
        areas_km2 = gdf.to_crs(utm).geometry.area.sum() / 1e6 if utm is not None else float("nan")
        return (f"栅格转矢量完成：{len(gdf)} 个面（连通度 {conn}，值域 {min(vals)}~{max(vals)}），"
                f"总面积 {areas_km2:.3f} km²（UTM 投影计算）。图层「{out_name}」已加载到地图")
    except Exception as e:
        return f"栅格转矢量失败: {str(e)[:300]}"



@tool
def load_cog(url: str, layer_name: str = "", max_size: int = 2048) -> str:
    """流式加载云优化 GeoTIFF（COG）/在线 GeoTIFF 并叠加到地图。
    走 rasterio /vsicurl/ 流式读取 + 降采样生成 PNG 预览叠加，不整体下载。
    url: http(s) 遥感影像地址；layer_name: 图层名（默认取文件名）；max_size: 预览最长边像素（默认 2048）。
    用户给了一个在线 .tif/.tiff 链接要求"加载/叠加到地图"时调用。"""
    from backend.services import cloud_native as cn
    from backend.services.url_security import sanitize_error_text, sanitize_http_url
    from PIL import Image as _PILImage
    init_temp_dir()
    try:
        result = cn.read_cog(url, max_size=max_size)
    except cn.CloudNativeError as e:
        return f"加载失败: {sanitize_error_text(e, url)}"
    except Exception as e:
        return f"加载异常: {sanitize_error_text(e, url)}"
    parsed_url = urllib.parse.urlsplit(str(url))
    source_path = parsed_url.path if parsed_url.scheme.lower() in {"http", "https"} else str(url)
    name = (layer_name or os.path.splitext(os.path.basename(source_path))[0]).strip() or "COG影像"
    upload_dir = os.path.join(get_temp_output_dir(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    png_name = f"cog_{safe}_{int(time.time())}_{uuid.uuid4().hex[:12]}.png"
    png_path = os.path.join(upload_dir, png_name)
    with open(png_path, "wb") as f:
        f.write(result["png_bytes"])
    bounds = result["bounds"]
    meta = result["meta"]
    preview_url = f"/output/uploads/{png_name}"
    preview_layer_name = f"{name}（COG 预览）"
    source_reference = (
        sanitize_http_url(url)
        if parsed_url.scheme.lower() in {"http", "https"}
        else os.path.basename(source_path)
    )
    raster_info = {
        "filename": png_name,
        "url": preview_url,
        "source_name": name,
        "source_reference": source_reference,
        "bounds": [float(v) for v in bounds],
        "width": int(meta["width"]),
        "height": int(meta["height"]),
        "preview_width": int(meta["resampled"][0]),
        "preview_height": int(meta["resampled"][1]),
        "bands": int(meta["count"]),
        "crs": meta["crs"],
        "preview_only": True,
        "processing": "云端 COG 影像预览",
    }
    # 影像叠加（dem_result 通道：前端 addImageOverlay）
    _pending_layer_ops.append({
        "action": "dem_result", "name": png_name,
        "url": preview_url,
        "bounds": [float(v) for v in bounds],
        "label": f"COG 影像: {name}",
        "layer_name": preview_layer_name,
        "raster": raster_info,
        "crs": meta["crs"],
    })
    # 注册范围框图层（供 AI 查询/缩放/卷帘，透明填充红框）
    minx, miny, maxx, maxy = bounds
    footprint = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]]},
        "properties": {"name": name, "source": "cog", "url": sanitize_http_url(url)[:500]},
    }]}
    _push_layer(name, footprint, {"color": "#e74c3c", "fillColor": "#e74c3c", "fillOpacity": 0.02, "weight": 1.5, "dashArray": "6 4"})
    _register_layer(name, footprint)
    return (
        f"已加载 COG 影像「{name}」并叠加到地图: {meta['width']}x{meta['height']} 像素, "
        f"{meta['count']} 波段, CRS {meta['crs']}, 范围 {meta['bounds_wgs84']}, "
        f"预览降采样至 {meta['resampled'][0]}x{meta['resampled'][1]}。"
        f"已注册同名范围框图层可供查询；当前仅保存地图预览，像元分析需提供原始栅格文件"
    )



@tool
def get_cog_info(url: str) -> str:
    """查询在线 COG/GeoTIFF 元信息：CRS、范围、尺寸、波段、数据类型、统计值（min/max/mean，采样）。
    只读元数据与降采样统计，不整体下载。用户问"这个 tif 是什么/什么坐标系/波段信息"时调用。"""
    from backend.services import cloud_native as cn
    from backend.services.url_security import sanitize_error_text, sanitize_http_url
    try:
        info = cn.cog_info(url)
    except cn.CloudNativeError as e:
        return f"查询失败: {sanitize_error_text(e, url)}"
    except Exception as e:
        return f"查询异常: {sanitize_error_text(e, url)}"
    lines = [
        f"== COG 元信息: {sanitize_http_url(url)[:120]} ==",
        f"CRS: {info['crs']}  范围(WGS84): {info['bounds_wgs84']}",
        f"尺寸: {info['width']} x {info['height']}  波段数: {info['count']}  类型: {', '.join(info['dtypes'])}",
        f"nodata: {info['nodata']}  瓦片化: {info['is_tiled']}  压缩: {info['compression']}",
    ]
    for s in info["stats_sampled"]:
        lines.append(f"  波段{s['band']}: min={s['min']} max={s['max']} mean={s['mean']}")
    return "\n".join(lines)

