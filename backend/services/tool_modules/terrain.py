# -*- coding: utf-8 -*-
"""
backend.services.tool_modules.terrain
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Layer 2 Terrain and Hydrological Analysis Tools.

This module provides 7 specialized tools for DEM surface analysis (slope, aspect, hillshade),
hydrology processing (flow direction, flow accumulation, stream network), 3D visualization,
elevation profiles, contour extraction, open DEM fetching, and cut/fill surface volumes.

Architectural rules:
- Strictly Layer 2: Depends only on Layer 1 (runtime), Layer 0 (common), peer Layer 2 (raster),
  and 3rd party GIS libraries.
- NEVER imports Layer 3 (backend.services.tools).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import sys
import time
import uuid
from typing import Any, Optional

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from langchain.tools import tool
from matplotlib.ticker import MaxNLocator
from PIL import Image
from pyproj import CRS as PyprojCRS
from pyproj import Transformer
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from skimage import measure

from backend.services.data_providers.errors import DataProviderError
from backend.services.dem_providers import (
    DEMError,
    dem_provider_by_id,
    list_dem_capabilities,
)
from backend.services.tool_modules.common import _safe_layer_export_stem
from backend.services.tool_modules.raster import (
    _find_uploaded_tif,
    _raster_out_profile,
    _raster_output_dir,
    _raster_preview_context,
    _raster_preview_op,
    _write_raster_output,
    record_tool_artifact,
)
from backend.services.tool_modules.runtime import (
    _pending_images,
    _pending_layer_ops,
    _push_layer,
    _register_layer,
    get_temp_output_dir,
    init_temp_dir,
)

__all__ = [
    # 7 Public Tools
    "dem_analysis",
    "hydrology_analysis",
    "view_3d_terrain",
    "terrain_profile",
    "extract_contours",
    "get_elevation_data",
    "surface_volumes",
    # Internal Helpers
    "_elevation_unit_to_m",
    "_fill_sinks",
    "_parse_dem_bbox",
    "_write_dem_geotiff",
    "_write_dem_preview",
    "_raster_pixel_area_m2",
]


# ============================================================
# Terrain Internal Helpers
# ============================================================


def _elevation_unit_to_m(value):
    if not isinstance(value, str) or not value.strip():
        return None
    unit = " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())
    factors = {
        "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
        "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01, "centimetre": 0.01, "centimetres": 0.01,
        "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001, "millimetre": 0.001, "millimetres": 0.001,
        "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0, "kilometre": 1000.0, "kilometres": 1000.0,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "international foot": 0.3048,
        "international feet": 0.3048,
        "us survey foot": 1200.0 / 3937.0, "us survey feet": 1200.0 / 3937.0,
        "us ft": 1200.0 / 3937.0, "ftus": 1200.0 / 3937.0,
    }
    return factors.get(unit)



def _fill_sinks(dem):
    """Priority-Flood 填洼，只抬升高程并为平地建立微小排水坡度。

    有效栅格外边界及 NoData 洞边缘作为局部出水边界；不把 NoData 像元纳入
    排水路径。返回 float64 数组，NoData 位置保持 NaN。
    """
    import numpy as np
    import heapq
    filled = dem.astype(np.float64).copy()
    ny, nx = filled.shape
    valid = np.isfinite(filled)
    visited = np.zeros((ny, nx), dtype=bool)
    frontier = []
    neighbors = ((-1, -1), (-1, 0), (-1, 1), (0, -1),
                 (0, 1), (1, -1), (1, 0), (1, 1))

    # Seed all valid cells on the raster edge and around NoData barriers.
    for row, col in np.argwhere(valid):
        row, col = int(row), int(col)
        boundary = row == 0 or row == ny - 1 or col == 0 or col == nx - 1
        if not boundary:
            boundary = any(not valid[row + dy, col + dx] for dy, dx in neighbors)
        if boundary:
            visited[row, col] = True
            heapq.heappush(frontier, (filled[row, col], row, col))

    while frontier:
        elevation, row, col = heapq.heappop(frontier)
        increment = max(1e-6, abs(elevation) * np.finfo(np.float64).eps)
        next_elevation = elevation + increment
        if next_elevation <= elevation:
            next_elevation = np.nextafter(elevation, np.inf)
        for dy, dx in neighbors:
            nr, nc = row + dy, col + dx
            if (nr < 0 or nr >= ny or nc < 0 or nc >= nx
                    or visited[nr, nc] or not valid[nr, nc]):
                continue
            visited[nr, nc] = True
            filled[nr, nc] = max(float(dem[nr, nc]), float(next_elevation))
            heapq.heappush(frontier, (filled[nr, nc], nr, nc))
    return filled



def _parse_dem_bbox(bbox):
    """统一 list / tuple / str → [minLng, minLat, maxLng, maxLat]（list of float）。"""
    if isinstance(bbox, (list, tuple)):
        if len(bbox) != 4:
            raise DataProviderError(f"bbox 必须 4 个数，收到 {bbox!r}")
        try:
            return [float(v) for v in bbox]
        except (TypeError, ValueError) as e:
            raise DataProviderError(f"bbox 含不可解析数值：{bbox!r}") from e
    if isinstance(bbox, str):
        s = bbox.strip()
        if not s:
            raise DataProviderError("bbox 字符串为空")
        if s.startswith("["):
            try:
                return _parse_dem_bbox(json.loads(s))
            except (ValueError, TypeError):
                pass
        for sep in (",", ";", " ", "\t"):
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) == 4:
                try:
                    return [float(p) for p in parts]
                except ValueError:
                    continue
        raise DataProviderError(
            f"bbox 字符串解析失败：{bbox!r}",
            hint="格式：'minLng,minLat,maxLng,maxLat'（如 '112.93,28.18,112.97,28.20'）"
                 " 或 [minLng, minLat, maxLng, maxLat]",
        )
    raise DataProviderError(f"bbox 类型不支持：{type(bbox).__name__}")



def _write_dem_geotiff(path: str, result) -> None:
    """把 DEMResult.data 写成单波段 float32 GeoTIFF（EPSG:4326，nodata=-9999）。

    下游工具（dem_analysis / extract_contours / terrain_profile）按 layer_name
    在 uploads 目录找 .tif 文件；nodata=-9999 与 SRTM 等 DEM 的事实标准一致。
    """
    import numpy as np
    import rasterio
    from rasterio.transform import Affine

    a, b, c, d, e, f = result.transform
    transform = Affine(a, b, c, d, e, f)
    arr = np.where(np.isfinite(result.data), result.data, -9999.0).astype(np.float32)

    with rasterio.open(
        path, "w", driver="GTiff",
        height=result.height, width=result.width,
        count=1, dtype="float32",
        crs="EPSG:4326", transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(arr, 1)
        dst.update_tags(
            provider=result.provider,
            source_url=result.source_url,
            min_elevation=f"{result.min_elevation:.3f}",
            max_elevation=f"{result.max_elevation:.3f}",
            resolution_deg=f"{result.resolution:.8f}",
        )



def _write_dem_preview(path: str, result) -> None:
    """渲染 DEM 地形预览 PNG（matplotlib terrain colormap，nodata→黑底）。"""
    import matplotlib
    import numpy as np
    from PIL import Image

    cmap = matplotlib.colormaps['terrain']
    arr = np.asarray(result.data, dtype=np.float64)
    valid = np.isfinite(arr)
    if not valid.any():
        rgb = np.zeros((max(1, result.height), max(1, result.width), 3), dtype=np.uint8)
    else:
        vmin = float(np.min(arr[valid]))
        vmax = float(np.max(arr[valid]))
        if np.isclose(vmin, vmax):
            vmax = vmin + 1.0
        norm = np.clip((arr - vmin) / (vmax - vmin), 0.0, 1.0)
        norm[~valid] = 0.0
        rgba = cmap(norm)
        rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
        rgb[~valid] = 0
    Image.fromarray(rgb).save(path)



def _raster_pixel_area_m2(src):
    """Return square metres per pixel (scalar projected area or row-wise geodesic area)."""
    transform = src.transform
    determinant = abs(float(transform.a) * float(transform.e) - float(transform.b) * float(transform.d))
    if not math.isfinite(determinant) or determinant <= 0:
        raise ValueError("无法从栅格变换计算有效像元面积")
    if src.crs is None:
        return determinant, ["源栅格缺少 CRS；面积按网格单位为米假设，填挖方结果需谨慎解释"]
    if src.crs.is_projected:
        try:
            unit_to_m = float(src.crs.linear_units_factor[1])
        except (TypeError, ValueError, IndexError, OverflowError) as exc:
            raise ValueError("无法识别投影坐标系的线性单位，不能计算平方米面积") from exc
        if not math.isfinite(unit_to_m) or unit_to_m <= 0:
            raise ValueError("投影坐标系的线性单位无效，不能计算平方米面积")
        return determinant * unit_to_m * unit_to_m, []
    if src.crs.is_geographic:
        if abs(float(transform.b)) > 1e-12 or abs(float(transform.d)) > 1e-12:
            raise ValueError("经纬度栅格含旋转/斜切变换；请先重投影后计算填挖方")
        from pyproj import CRS as PyprojCRS
        geod = PyprojCRS.from_wkt(src.crs.to_wkt()).get_geod()
        row_areas = []
        for row in range(src.height):
            left = float(transform.c)
            right = left + float(transform.a)
            top = float(transform.f) + float(transform.e) * row
            bottom = top + float(transform.e)
            area, _ = geod.polygon_area_perimeter(
                [left, right, right, left], [top, top, bottom, bottom]
            )
            area_per_pixel = abs(float(area))
            if not math.isfinite(area_per_pixel) or area_per_pixel <= 0:
                raise ValueError("无法计算经纬度栅格的椭球像元面积")
            row_areas.append(area_per_pixel)
        import numpy as np
        return np.asarray(row_areas, dtype="float64").reshape(src.height, 1), []
    raise ValueError("仅支持投影或地理坐标系的栅格面积计算")



# ============================================================
# 7 Terrain Domain Tools
# ============================================================


@tool
def dem_analysis(layer_name: str, analysis: str = "slope") -> str:
    """对 DEM 栅格图层进行地形分析并生成可视化图层。
    - layer_name: DEM 图层名（如已上传的 DEM 名称）。
    - analysis: 分析类型，'slope'(坡度,度0-90) / 'aspect'(坡向,度0-360) / 'hillshade'(山体阴影灰度图)。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的GeoTIFF文件，请先上传DEM"
        import rasterio
        from rasterio.warp import transform_bounds
        from pyproj import CRS as PyprojCRS
        import numpy as np
        from PIL import Image
        out_name = f"{layer_name}_{analysis}"
        with rasterio.open(tif_path) as src:
            dem = src.read(1, masked=True).astype(np.float64).filled(np.nan)
            dem[~np.isfinite(dem)] = np.nan
            transform = src.transform
            source_crs = src.crs
            source_width, source_height = src.width, src.height
            bounds = list(src.bounds)
            source_tags = {key.upper(): value for key, value in src.tags().items()}
            source_value_units = (
                (src.units[0] if src.units and src.units[0] else None)
                or source_tags.get("VALUE_UNITS")
                or source_tags.get("UNITTYPE")
            )
            source_label = source_tags.get("SOURCE_LABEL") or source_tags.get("SOURCE")
            source_quality_note = source_tags.get("QUALITY_NOTE")
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        elevation_unit_scale = _elevation_unit_to_m(source_value_units)
        if elevation_unit_scale is not None:
            dem *= elevation_unit_scale
        ny, nx = dem.shape
        if source_crs and source_crs.is_geographic:
            # Elevation values are linear while geographic raster pixels are angular.
            # Build the local east/north vectors for both affine pixel axes near
            # the raster centre, including rotated or sheared grids.
            geod = PyprojCRS.from_wkt(source_crs.to_wkt()).get_geod()
            center_x, center_y = transform * (source_width / 2, source_height / 2)
            azimuth_col, _, pixel_col_m = geod.inv(
                center_x, center_y,
                center_x + transform.a, center_y + transform.d,
            )
            azimuth_row, _, pixel_row_m = geod.inv(
                center_x, center_y,
                center_x + transform.b, center_y + transform.e,
            )
            x_col = pixel_col_m * math.sin(math.radians(azimuth_col))
            y_col = pixel_col_m * math.cos(math.radians(azimuth_col))
            x_row = pixel_row_m * math.sin(math.radians(azimuth_row))
            y_row = pixel_row_m * math.cos(math.radians(azimuth_row))
        elif source_crs and source_crs.is_projected:
            # Projected data may use feet (or another linear unit), while DEM
            # elevations are conventionally metres. Normalize the full affine
            # pixel basis to metres before converting grid derivatives to east/north.
            unit_to_m = float(src.crs.linear_units_factor[1])
            x_col, y_col = transform.a * unit_to_m, transform.d * unit_to_m
            x_row, y_row = transform.b * unit_to_m, transform.e * unit_to_m
        else:
            # Retain support for legacy unreferenced rasters whose cell units
            # cannot be inferred; uploaded GeoTIFFs are required to carry a CRS.
            x_col, y_col = transform.a, transform.d
            x_row, y_row = transform.b, transform.e
        pixel_basis = (x_col, y_col, x_row, y_row)
        determinant = x_col * y_row - x_row * y_col
        if (not all(math.isfinite(value) for value in pixel_basis)
                or not math.isfinite(determinant) or determinant == 0):
            return "DEM分析失败: 无法从栅格变换和坐标系确定有效像元基向量"
        # Horn's formula — 3x3 window
        dzdcol = np.full_like(dem, np.nan)
        dzdrow = np.full_like(dem, np.nan)
        # interior cells
        dzdcol[1:-1,1:-1] = (
            (dem[:-2,2:] + 2*dem[1:-1,2:] + dem[2:,2:]) -
            (dem[:-2,:-2] + 2*dem[1:-1,:-2] + dem[2:,:-2])
        ) / 8
        dzdrow[1:-1,1:-1] = (
            (dem[2:,:-2] + 2*dem[2:,1:-1] + dem[2:,2:]) -
            (dem[:-2,:-2] + 2*dem[:-2,1:-1] + dem[:-2,2:])
        ) / 8
        # Grid-axis derivatives are not east/north derivatives for rotated
        # rasters. Apply the inverse-transpose affine Jacobian to recover the
        # gradient in ground coordinates before calculating slope or aspect.
        dzdx = (y_row * dzdcol - y_col * dzdrow) / determinant
        dzdy = (-x_row * dzdcol + x_col * dzdrow) / determinant
        valid = np.isfinite(dzdx) & np.isfinite(dzdy) & np.isfinite(dem)
        if analysis == "slope":
            data = np.degrees(np.arctan(np.sqrt(dzdx**2 + dzdy**2)))
            data[~valid] = np.nan
            label = "坡度(Slope)"
            cmap = "slope"
        elif analysis == "aspect":
            # 坡向 = 最陡下坡方向的方位角（自正北顺时针）；dzdx、dzdy 已换算为东向和北向梯度。
            data = np.degrees(np.arctan2(-dzdx, -dzdy)) % 360
            data[~valid] = np.nan
            label = "坡向(Aspect)"
            cmap = "aspect"
        elif analysis == "hillshade":
            slope_rad = np.arctan(np.sqrt(dzdx**2 + dzdy**2))
            aspect_rad = np.arctan2(-dzdx, -dzdy)
            zenith = np.radians(45)
            azimuth = np.radians(315)
            data = (
                np.cos(zenith) * np.cos(slope_rad) +
                np.sin(zenith) * np.sin(slope_rad) * np.cos(azimuth - aspect_rad)
            )
            data = np.clip(data, 0, 1) * 255
            data[~valid] = np.nan
            label = "山体阴影(Hillshade)"
            cmap = "hillshade"
        else:
            return f"错误：不支持的analysis类型: {analysis}，可选: slope/aspect/hillshade"
        # 颜色映射
        if analysis == "hillshade":
            preview_band = np.where(valid, data, 0).astype(np.uint8)
            rgb = np.stack([preview_band]*3, axis=-1)
        else:
            import matplotlib
            if cmap == "slope":
                cmap_obj = matplotlib.colormaps['YlOrRd']
            else:
                cmap_obj = matplotlib.colormaps['hsv']
            vmin = np.nanmin(data)
            vmax = np.nanmax(data)
            norm_data = (data - vmin) / (vmax - vmin + 1e-10)
            norm_data = np.clip(norm_data, 0, 1)
            norm_data[~valid] = 0
            rgba = cmap_obj(norm_data)
            rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
            if np.any(~valid):
                rgb[~valid] = 0
        img = Image.fromarray(rgb)
        result_units = "°（角度）" if analysis in ("slope", "aspect") else "0–255（相对亮度）"
        raster_path = _write_raster_output(tif_path, out_name, data, metadata={
            "SOURCE_LAYER": layer_name,
            "SOURCE_LABEL": source_label or "GIS WorkTable 栅格分析",
            "SOURCE_VALUE_UNITS": source_value_units or "unknown",
            "SOURCE_URL": source_tags.get("SOURCE_URL"),
            "CITATION": source_tags.get("CITATION"),
            "SOURCE_QUALITY_NOTE": source_quality_note,
            "VERTICAL_DATUM": source_tags.get("VERTICAL_DATUM"),
            "PROCESSING": label,
            "VALUE_UNITS": result_units,
        })
        with rasterio.open(raster_path) as result_src:
            warnings = []
            if not source_value_units:
                warnings.append("源栅格未标注数值单位；地形计算按高程值为米解释，请核实原始数据")
            elif elevation_unit_scale is None:
                warnings.append("源栅格高程单位无法识别；地形计算按数值单位为米解释，请核实原始数据")
            if source_quality_note:
                warnings.append(source_quality_note)
            if source_crs and source_crs.is_geographic:
                warnings.append("经纬度栅格按中心处椭球像元距离换算水平间距；地形结果适用于当前小范围，大范围请使用合适的投影 CRS")
            note = _raster_preview_op(
                result_src, data, out_name, label, preview_image=img,
                source_layer=layer_name, value_units=result_units,
                source_label=source_label, quality_warnings=warnings,
            )
        return f"已生成{label} GeoTIFF：{os.path.basename(raster_path)}；{note}"
    except ImportError as e:
        return f"错误：DEM分析需要依赖库: {str(e)[:200]}，请安装: pip install matplotlib"
    except Exception as e:
        import traceback
        return f"DEM分析失败: {str(e)[:300]}"



@tool
def hydrology_analysis(layer_name: str, analysis: str = "flowacc",
                       threshold: int = 100) -> str:
    """对DEM栅格进行水文分析。analysis可选:
    flowdir(流向图), flowacc(汇流累积量), streamnet(河网提取)。
    threshold为河网提取的最小汇流累积量阈值。
    layer_name为上传DEM时创建的图层名。"""
    try:
        import numpy as np
        if analysis not in {"flowdir", "flowacc", "streamnet"}:
            return f"错误：不支持的analysis类型: {analysis}，可选: flowdir/flowacc/streamnet"
        if analysis == "streamnet" and (
            isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1
        ):
            return "河网提取失败: threshold 阈值必须是正整数"
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from PIL import Image
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return "错误：水文分析要求输入 GeoTIFF 带有有效 CRS；请先定义 CRS 后重新上传"
            src_crs = src.crs
            transform = src.transform
            dem = src.read(1, masked=True).astype(np.float64).filled(np.nan)
            dem[~np.isfinite(dem)] = np.nan
        ny, nx = dem.shape
        if not np.isfinite(dem).any():
            return "水文分析失败: DEM 没有有效高程像元"
        filled = _fill_sinks(dem)
        # D8 流向编码（1=E,2=NE,4=N,8=NW,16=W,32=SW,64=S,128=SE）
        # 使用简化编码: 0=E,1=NE,2=N,3=NW,4=W,5=SW,6=S,7=SE
        dx = [1, 1, 0, -1, -1, -1, 0, 1]
        dy = [0, -1, -1, -1, 0, 1, 1, 1]
        if src_crs.is_projected:
            unit_to_m = float(src_crs.linear_units_factor[1])
            step_distances = [
                math.hypot(transform.a * x + transform.b * y,
                           transform.d * x + transform.e * y) * unit_to_m
                for x, y in zip(dx, dy)
            ]
            geod = None
        elif src_crs.is_geographic:
            from pyproj import CRS as PyprojCRS
            geod = PyprojCRS.from_user_input(src_crs).get_geod()
            step_distances = None
            if transform.b == 0 and transform.d == 0:
                step_distances = np.empty((ny, 8), dtype=np.float64)
                for row in range(ny):
                    for k, (x, y) in enumerate(zip(dx, dy)):
                        x1, y1 = transform * (0.5, row + 0.5)
                        x2, y2 = transform * (0.5 + x, row + 0.5 + y)
                        step_distances[row, k] = geod.inv(x1, y1, x2, y2)[2]
        else:
            return f"错误：水文分析暂不支持此坐标参考系: {src_crs}"
        direction = np.full_like(dem, -1, dtype=np.int32)
        slope_pct = np.full_like(dem, np.nan)
        for i in range(1, ny-1):
            for j in range(1, nx-1):
                if np.isnan(filled[i, j]):
                    continue
                max_drop = 0
                best_dir = -1
                for k in range(8):
                    ni, nj = i + dy[k], j + dx[k]
                    if ni < 0 or ni >= ny or nj < 0 or nj >= nx:
                        continue
                    if np.isnan(filled[ni, nj]):
                        continue
                    if step_distances is not None:
                        dist = (step_distances[i, k]
                                if isinstance(step_distances, np.ndarray) else step_distances[k])
                    else:
                        x1, y1 = transform * (j + 0.5, i + 0.5)
                        x2, y2 = transform * (j + 0.5 + dx[k], i + 0.5 + dy[k])
                        dist = geod.inv(x1, y1, x2, y2)[2]
                    if not math.isfinite(dist) or dist <= 0:
                        continue
                    drop = (filled[i, j] - filled[ni, nj]) / dist
                    if drop > max_drop:
                        max_drop = drop
                        best_dir = k
                if best_dir >= 0:
                    direction[i, j] = best_dir
                    slope_pct[i, j] = max_drop
        # 汇流累积量（按高程排序从高到低累加）
        flowacc = np.zeros_like(dem, dtype=np.float64)
        valid_cells = np.isfinite(filled)
        if np.any(valid_cells):
            flowacc[valid_cells] = 1.0
            order = np.argsort(-filled.ravel())
            for idx in order:
                i, j = divmod(int(idx), nx)
                if not valid_cells[i, j] or direction[i, j] < 0:
                    continue
                k = direction[i, j]
                ni, nj = i + dy[k], j + dx[k]
                if 0 <= ni < ny and 0 <= nj < nx and valid_cells[ni, nj]:
                    flowacc[ni, nj] += flowacc[i, j]
        if analysis == "flowdir":
            # 流向可视化（按角度色环）
            # D8 codes describe raster-neighbor offsets; rotated grids do not
            # have E/N aligned with their column/row axes. Color each direction
            # using its local true-compass bearing near the raster centre.
            from pyproj import CRS as PyprojCRS, Transformer
            to_wgs84 = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
            geod_wgs84 = PyprojCRS.from_epsg(4326).get_geod()
            center_col, center_row = nx / 2, ny / 2
            center_x, center_y = transform * (center_col, center_row)
            center_lon, center_lat = to_wgs84.transform(center_x, center_y)
            angle_map = np.empty(8, dtype=np.float64)
            for k, (step_x, step_y) in enumerate(zip(dx, dy)):
                neighbor_x, neighbor_y = transform * (center_col + step_x, center_row + step_y)
                neighbor_lon, neighbor_lat = to_wgs84.transform(neighbor_x, neighbor_y)
                bearing = geod_wgs84.inv(center_lon, center_lat, neighbor_lon, neighbor_lat)[0]
                angle_map[k] = bearing % 360
            dir_deg = np.full_like(dem, np.nan, dtype=np.float64)
            for k in range(8):
                dir_deg[direction == k] = angle_map[k]
            import matplotlib
            cmap = matplotlib.colormaps['hsv']
            norm_data = np.full_like(dir_deg, np.nan)
            valid_dir = dir_deg >= 0
            if np.any(valid_dir):
                norm_data[valid_dir] = dir_deg[valid_dir] / 360.0
            norm_data = np.clip(np.nan_to_num(norm_data, 0), 0, 1)
            rgba = cmap(norm_data)
            rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
            rgb[~valid_cells] = 0
            label = "流向(Flow Direction)"
        elif analysis == "flowacc":
            # 汇流累积量（对数拉伸）
            log_fa = np.log1p(flowacc)
            vmin, vmax = 0, np.nanmax(log_fa)
            norm_data = log_fa / (vmax + 1e-10)
            norm_data = np.clip(norm_data, 0, 1)
            import matplotlib
            cmap = matplotlib.colormaps['Blues']
            rgba = cmap(norm_data)
            rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
            rgb[~valid_cells] = 0
            label = "汇流累积量(Flow Accumulation)"
        elif analysis == "streamnet":
            # 河网（蓝色线状）
            stream = np.zeros((ny, nx, 3), dtype=np.uint8)
            stream[~valid_cells] = [200, 200, 200]
            stream[valid_cells] = [255, 255, 255]
            stream_cells = (flowacc >= threshold) & valid_cells
            for i in range(1, ny-1):
                for j in range(1, nx-1):
                    if stream_cells[i, j]:
                        stream[i, j] = [0, 100, 255]
                        # 加粗河网
                        for di in (-1, 0, 1):
                            for dj in (-1, 0, 1):
                                ni, nj = i+di, j+dj
                                if 0 <= ni < ny and 0 <= nj < nx:
                                    stream[ni, nj] = [0, 100, 255]
            rgb = stream
            label = f"河网(Stream): threshold={threshold}"
        else:
            return f"错误：不支持的analysis类型: {analysis}，可选: flowdir/flowacc/streamnet"
        img = Image.fromarray(rgb)
        stem = _safe_layer_export_stem(layer_name)
        base_name = f"{stem}_{analysis}"
        out_name = base_name
        suffix = 2
        while (os.path.exists(os.path.join(upload_dir, out_name + ".tif"))
               or os.path.exists(os.path.join(upload_dir, out_name + ".png"))):
            out_name = f"{base_name}_{suffix}"
            suffix += 1
        if analysis == "flowdir":
            result_data = direction.astype(np.float32)
            result_data[direction < 0] = np.nan
            value_units = "D8 raster-neighbor code (0=col+, 1=col+row-, 2=row-, 3=col-row-, 4=col-, 5=col-row+, 6=row+, 7=col+row+)"
            quality_warnings = ["采用当前工具的简化 D8 邻域流向算法；结果未经外部水文基准验证"]
        elif analysis == "flowacc":
            result_data = flowacc.astype(np.float32)
            result_data[~valid_cells] = np.nan
            value_units = "upstream pixel count"
            quality_warnings = ["汇流累积量按像元计数，不代表流量或面积；结果未经外部水文基准验证"]
        else:
            result_data = stream_cells.astype(np.float32)
            result_data[~valid_cells] = np.nan
            value_units = "binary stream mask (0/1)"
            quality_warnings = ["河网由简化 D8 汇流像元阈值提取；结果未经外部水文基准验证"]
        raster_context = _raster_preview_context(layer_name, value_units=value_units)
        raster_context["quality_warnings"] = quality_warnings
        with rasterio.open(tif_path) as src:
            note = _raster_preview_op(
                src, result_data, out_name, label, preview_image=img,
                **raster_context,
            )
        return f"已生成水文分析图层 '{label}'；{note}"
    except Exception as e:
        return f"水文分析失败: {str(e)[:300]}"



@tool
def view_3d_terrain(layer_name: str, exaggeration: float = 2.0) -> str:
    """从DEM生成3D地形交互视图。layer_name为DEM图层名。
    exaggeration为垂直夸大系数（默认2.0）。
    结果在聊天窗口展示 Three.js 3D 场景。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        with rasterio.open(tif_path) as src:
            dem = src.read(1, masked=True).astype(np.float64).filled(np.nan)
            dem[~np.isfinite(dem)] = np.nan
            transform = src.transform
            bounds_wgs84 = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds_wgs84 = list(transform_bounds(src.crs, 'EPSG:4326', *bounds_wgs84))
        ny, nx = dem.shape
        step = max(1, max(ny, nx) // 200)
        dem = dem[::step, ::step]
        ny, nx = dem.shape
        vmin = np.nanmin(dem)
        vrange = np.nanmax(dem) - vmin
        if vrange < 1:
            return "错误：DEM 高程无变化"
        rows, cols = ny, nx
        lng0 = bounds_wgs84[0]
        lat0 = bounds_wgs84[1]
        lng_step = (bounds_wgs84[2] - bounds_wgs84[0]) / (nx - 1) if nx > 1 else 1
        lat_step = (bounds_wgs84[3] - bounds_wgs84[1]) / (ny - 1) if ny > 1 else 1
        vert_lines = []
        for i in range(rows):
            for j in range(cols):
                z = dem[i, j]
                if np.isnan(z):
                    z = vmin
                x = j * lng_step
                y = (rows - 1 - i) * lat_step
                h = (z - vmin) / vrange * exaggeration
                vert_lines.append(f"{x:.6f} {y:.6f} {h:.6f}")
        tri_lines = []
        for i in range(rows - 1):
            for j in range(cols - 1):
                a = i * cols + j
                b = i * cols + j + 1
                c = (i + 1) * cols + j
                d = (i + 1) * cols + j + 1
                tri_lines.append(f"{a} {b} {c}")
                tri_lines.append(f"{b} {d} {c}")
        color_lines = []
        for i in range(rows):
            for j in range(cols):
                z = dem[i, j]
                if np.isnan(z):
                    z = vmin
                t = (z - vmin) / vrange
                r = 255 * (1 - t)
                g = 255 * (0.3 + 0.7 * t)
                b = 255 * t
                color_lines.append(f"{r/255:.3f} {g/255:.3f} {b/255:.3f}")
        ctr_lng = (bounds_wgs84[0] + bounds_wgs84[2]) / 2
        ctr_lat = (bounds_wgs84[1] + bounds_wgs84[3]) / 2
        size_x = bounds_wgs84[2] - bounds_wgs84[0]
        size_y = bounds_wgs84[3] - bounds_wgs84[1]
        max_dim = max(size_x, size_y, vrange * exaggeration / 1000)
        verts_str = ",".join(vert_lines)
        tris_str = ",".join(tri_lines)
        colors_str = ",".join(color_lines)
        legend_html = f"""
<div style="position:absolute;bottom:10px;left:10px;color:#fff;font:12px sans-serif;background:rgba(0,0,0,.5);padding:4px 10px;border-radius:4px;pointer-events:none">{layer_name} | 3D Terrain | Drag to rotate | Scroll to zoom</div>"""
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>3D Terrain</title>
<style>body{{margin:0;overflow:hidden;background:#1a1a2e}}</style></head><body>
{legend_html}
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
var scene=new THREE.Scene();
var cam=new THREE.PerspectiveCamera(60,window.innerWidth/window.innerHeight,0.01,1000);
var renderer=new THREE.WebGLRenderer({{antialias:true}});
renderer.setSize(window.innerWidth,window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
renderer.shadowMap.enabled=true;
document.body.appendChild(renderer.domElement);
var geo=new THREE.BufferGeometry();
var vertices=new Float32Array([{verts_str}]);
var indices=new Uint16Array([{tris_str}]);
var colors=new Float32Array([{colors_str}]);
geo.setAttribute('position',new THREE.BufferAttribute(vertices,3));
geo.setAttribute('color',new THREE.BufferAttribute(colors,3));
geo.setIndex(new THREE.BufferAttribute(indices,1));
geo.computeVertexNormals();
var mat=new THREE.MeshPhongMaterial({{vertexColors:true,side:THREE.DoubleSide,shininess:30}});
var mesh=new THREE.Mesh(geo,mat);
mesh.castShadow=true;mesh.receiveShadow=true;
scene.add(mesh);
var centerX={ctr_lng:.4f},centerY={ctr_lat:.4f},sizeX={size_x:.4f},sizeY={size_y:.4f};
var maxDim=Math.max(sizeX,sizeY,{max_dim:.2f});
var dist=maxDim*3;
mesh.position.set(-centerX,-centerY,0);
cam.position.set(dist*.6,dist*.3,dist*.8);
cam.lookAt(0,0,0);
var ambient=new THREE.AmbientLight(0x404060);
scene.add(ambient);
var dir=new THREE.DirectionalLight(0xffffff,1);
dir.position.set(-50,100,50);
dir.castShadow=true;scene.add(dir);
var dir2=new THREE.DirectionalLight(0xffffff,0.3);
dir2.position.set(50,-50,30);
scene.add(dir2);
var controls=new THREE.OrbitControls(cam,renderer.domElement);
controls.target.set(0,0,0);controls.update();
var grid=new THREE.GridHelper(maxDim*2,20,0x88aaff,0x446688);
grid.position.y=-{max_dim:.2f}*0.5;
scene.add(grid);
window.addEventListener('resize',function(){{cam.aspect=window.innerWidth/window.innerHeight;cam.updateProjectionMatrix();renderer.setSize(window.innerWidth,window.innerHeight);}});
function animate(){{requestAnimationFrame(animate);controls.update();renderer.render(scene,cam);}}
animate();
</script></body></html>"""
        import hashlib
        fname = f"terrain_{layer_name}_{hashlib.md5(html.encode()[:100]).hexdigest()[:8]}.html"
        output_dir = os.path.join(get_temp_output_dir(), "output")
        os.makedirs(output_dir, exist_ok=True)
        fpath = os.path.join(output_dir, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(html)
        record_tool_artifact(fname, fpath, artifact_type="html")
        _pending_images.append({
            "name": fname,
            "path": fpath,
            "type": "html",
            "url": f"/output/{fname}"
        })
        return f"已生成3D地形视图，可在聊天窗口中查看"
    except Exception as e:
        return f"3D地形生成失败: {str(e)[:300]}"



@tool
def terrain_profile(layer_name: str, line_coords: str) -> str:
    """沿一条线从DEM提取高程并生成地形剖面图。
    layer_name为DEM图层名，line_coords为JSON数组 [[lng,lat],[lng,lat],...]。
    结果在聊天窗口显示高程剖面图表。"""
    try:
        import numpy as np
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        import json as _json
        coords = _json.loads(line_coords)
        if not isinstance(coords, list) or len(coords) < 2:
            return "错误：line_coords需为包含至少2个[lng,lat]的JSON数组"
        pts = np.array(coords)
        # 沿线段采样100个点
        total_len = 0
        segments = []
        for i in range(len(pts) - 1):
            dx = pts[i + 1][0] - pts[i][0]
            dy = pts[i + 1][1] - pts[i][1]
            seg_len = np.sqrt(dx ** 2 + dy ** 2)
            segments.append((seg_len, pts[i], pts[i + 1]))
            total_len += seg_len
        n_samples = 100
        sample_pts = []
        cum_dist = 0
        distances = [0]
        sample_pts.append(pts[0])
        for seg_len, p1, p2 in segments:
            n_seg = max(1, int(seg_len / total_len * n_samples))
            for j in range(1, n_seg + 1):
                t = j / n_seg
                x = p1[0] + (p2[0] - p1[0]) * t
                y = p1[1] + (p2[1] - p1[1]) * t
                sample_pts.append(np.array([x, y]))
                distances.append(cum_dist + seg_len * t)
            cum_dist += seg_len
        sample_pts = np.array(sample_pts)
        distances = np.array(distances)
        # 从DEM采样高程
        with rasterio.open(tif_path) as src:
            dem = src.read(1, masked=True).astype(np.float64).filled(np.nan)
            dem[~np.isfinite(dem)] = np.nan
            transform = src.transform
        elevations = []
        for pt in sample_pts:
            col, row = ~transform * (pt[0], pt[1])
            col, row = int(round(col)), int(round(row))
            if 0 <= row < dem.shape[0] and 0 <= col < dem.shape[1]:
                z = dem[row, col]
                elevations.append(z if np.isfinite(z) else np.nan)
            else:
                elevations.append(np.nan)
        elevations = np.array(elevations)
        valid = np.isfinite(elevations)
        if not np.any(valid):
            return "错误：所有采样点均落在DEM有效范围外"
        from matplotlib import pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 4), facecolor='white')
        ax.fill_between(distances, elevations, alpha=0.3, color='#8B4513')
        ax.plot(distances, elevations, color='#5C3317', linewidth=1.5)
        ax.fill_between(distances, elevations, elevations.min(), alpha=0.1, color='#8B4513')
        ax.set_xlabel('Distance (degree)', fontsize=10)
        ax.set_ylabel('Elevation', fontsize=10)
        ax.set_title(f'Terrain Profile — {layer_name}', fontsize=12)
        ax.grid(True, alpha=0.3)
        vmin, vmax = np.nanmin(elevations), np.nanmax(elevations)
        ax.set_ylim(vmin - (vmax - vmin) * 0.1, vmax + (vmax - vmin) * 0.1)
        from matplotlib.ticker import MaxNLocator
        ax.yaxis.set_major_locator(MaxNLocator(8))
        fig.tight_layout()
        import hashlib, io
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120)
        plt.close(fig)
        fname = f"profile_{layer_name}_{hashlib.md5(str(coords).encode()).hexdigest()[:8]}.png"
        output_dir = os.path.join(get_temp_output_dir(), "output")
        os.makedirs(output_dir, exist_ok=True)
        fpath = os.path.join(output_dir, fname)
        with open(fpath, 'wb') as f:
            f.write(buf.getvalue())
        record_tool_artifact(fname, fpath, artifact_type="image")
        _pending_images.append({
            "name": fname,
            "path": fpath,
            "type": "png",
            "url": f"/output/{fname}",
            "caption": f"{layer_name} 高程剖面 | 距离 {total_len:.4f}° | 高程 {vmin:.1f}–{vmax:.1f}"
        })
        return f"已生成地形剖面图，高程范围 {vmin:.1f}–{vmax:.1f}，距离 {total_len:.4f}°"
    except Exception as e:
        return f"地形剖面生成失败: {str(e)[:300]}"



@tool
def extract_contours(layer_name: str, interval: float = 0) -> str:
    """从DEM栅格图层提取等高线矢量。interval为等高距（米），0表示自动计算。
    layer_name为上传DEM时创建的图层名（如dem.tif→图层名为dem）。
    结果将作为新矢量图层加载到地图上。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"错误：未找到图层 '{layer_name}' 对应的GeoTIFF文件，请先上传DEM"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from skimage import measure
        with rasterio.open(tif_path) as src:
            dem = src.read(1, masked=True).astype(np.float64).filled(np.nan)
            dem[~np.isfinite(dem)] = np.nan
            transform = src.transform
            bounds = list(src.bounds)
            to_wgs84 = None
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                from pyproj import Transformer
                to_wgs84 = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        if not np.isfinite(dem).any():
            return "等高线提取失败: DEM 没有有效高程像元"
        ny, nx = dem.shape
        vmin, vmax = np.nanmin(dem), np.nanmax(dem)
        drange = vmax - vmin
        if interval <= 0:
            interval = max(round(drange / 15, -1), 1) if drange > 10 else drange / 15
        if not math.isfinite(interval) or interval <= 0 or not math.isfinite(drange) or drange <= 0:
            return "等高线提取失败: DEM 没有有效起伏，无法生成等高线"
        levels = np.arange(vmin, vmax + interval, interval)
        features = []
        for level in levels:
            for seg in measure.find_contours(dem, level, mask=np.isfinite(dem)):
                if len(seg) < 2:
                    continue
                coords = []
                for row, col in seg:
                    x = transform[2] + (col + 0.5) * transform[0] + (row + 0.5) * transform[1]
                    y = transform[5] + (col + 0.5) * transform[3] + (row + 0.5) * transform[4]
                    if to_wgs84 is not None:
                        x, y = to_wgs84.transform(x, y)
                    coords.append([round(x, 6), round(y, 6)])
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {"elevation": round(float(level), 1)}
                })
        name = f"{layer_name}_contour"
        fc = {"type": "FeatureCollection", "features": features}
        # 必须走统一的推送/注册接口：_push_layer 生成 {"geojson":...} 供前端渲染，
        # _register_layer 写入 geojson/feature_count/geometry_types/bbox 供后续工具读取。
        # 原实现手写 {"type","name"} 既缺 geojson（前端不渲染），也导致 _layer_to_gdf 报"图层为空"。
        _push_layer(name, fc)
        _register_layer(name, fc)
        return f"已提取 {len(features)} 条等高线（等高距 {interval:.1f}m），生成图层 '{name}'"
    except ImportError as e:
        return f"错误：等高线提取需要依赖库: {str(e)[:200]}，请安装: pip install scikit-image"
    except Exception as e:
        import traceback
        return f"等高线提取失败: {str(e)[:300]}"



@tool
def get_elevation_data(
    bbox,
    resolution: float = 0,
    provider: str = "aws_terrain",
    output_format: str = "geotiff",
) -> str:
    """获取指定地理范围的真实地表高程 DEM 数据（按需下载 + 本地 tile 缓存）。
    - bbox: 边界框 [minLng, minLat, maxLng, maxLat]（WGS84，如 [112.93, 28.18, 112.97, 28.20]）或逗号分隔字符串。
    - resolution: 目标分辨率（度/像素，默认 0 为自动）。
    - provider: 数据源，默认 'aws_terrain'（全球免费免 Key）。
    - output_format: 当前仅支持 'geotiff'（落盘供 dem_analysis 等工具继续处理）。
    返回包含 min/max_elevation、geotiff_path、preview_url 及可用图层名 layer_name 的 JSON。"""
    try:
        fmt = (output_format or "geotiff").lower().strip()
        if fmt != "geotiff":
            raise DataProviderError("DEM 获取当前仅支持 output_format='geotiff'。")
        bb = _parse_dem_bbox(bbox)
        prov = dem_provider_by_id(provider)
        if prov is None:
            caps = list_dem_capabilities()
            return json.dumps({
                "ok": False,
                "error": f"未知 DEM Provider：{provider}",
                "hint": "可用 Provider：" + ", ".join(c["name"] for c in caps),
                "available_providers": [c["provider"] for c in caps],
            }, ensure_ascii=False)

        result = prov.fetch(bb, target_resolution_deg=float(resolution or 0))

        # 落盘 GeoTIFF + 渲染预览 PNG（沿用 dem_analysis 的上传目录约定）
        layer_name = f"dem_{int(time.time() * 1000) % 10**9:09d}"
        upload_dir = os.path.join(get_temp_output_dir(), "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        geotiff_path = os.path.join(upload_dir, f"{layer_name}.tif")
        png_path = os.path.join(upload_dir, f"{layer_name}.png")
        _write_dem_geotiff(geotiff_path, result)
        _write_dem_preview(png_path, result)

        # 推 dem_result 给前端叠加（与 dem_analysis/ndvi_analysis/raster_calculator 同一通道）
        bounds_list = [float(v) for v in result.bounds]
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": f"{layer_name}.png",
            "url": f"/output/uploads/{layer_name}.png",
            "bounds": bounds_list,
            "label": (
                f"DEM 真实高程（{result.min_elevation:.1f}–{result.max_elevation:.1f} m，"
                f"{prov.name}）"
            ),
        })

        out = result.to_dict()
        out.update({
            "ok": True,
            "geotiff_path": geotiff_path,
            "preview_url": f"/output/uploads/{layer_name}.png",
            "preview_name": f"{layer_name}.png",
            "layer_name": layer_name,
        })
        return json.dumps(out, ensure_ascii=False)

    except DEMError as e:
        return json.dumps({"ok": False, **e.to_dict()}, ensure_ascii=False)
    except DataProviderError as e:
        return json.dumps({"ok": False, **e.to_dict()}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "ok": False,
            "error": f"DEM 获取失败：{type(e).__name__}: {str(e)[:200]}",
        }, ensure_ascii=False)



@tool
def surface_volumes(before_layer: str, after_layer: str, reference: float = -99999.0) -> str:
    """填挖方计算：比较两个共配准 DEM（或一个 DEM 与参考高程面），输出挖方/填方/净方量与变化面积。
    - before_layer: 施工前（现状）DEM 图层名（上传的 GeoTIFF 图层名）。
    - after_layer: 施工后（设计）DEM 图层名；当给出 reference 时该参数可留空字符串。
    - reference: 参考高程（米，浮点数）。给出时忽略 after_layer，用常数高程面作为设计面。
    要求两个 DEM 的行列数与地理变换完全一致，否则直接失败并提示；
    只有两个栅格都有效的像元参与计算。挖方=现状高于设计部分的体积，填方=设计高于现状部分的体积，
    净方量=填方-挖方（正数表示净填）。结果为 m3 / m2。"""
    try:
        import numpy as np
        import rasterio

        before_path = _find_uploaded_tif(before_layer)
        if before_path is None:
            return f"错误：未找到栅格文件「{before_layer}」，请先上传 GeoTIFF"
        use_ref = reference is not None and float(reference) > -99998.0
        ref_val = float(reference) if use_ref else None
        after_path = None
        if not use_ref:
            after_path = _find_uploaded_tif(after_layer)
            if after_path is None:
                return f"错误：未找到栅格文件「{after_layer}」，请先上传 GeoTIFF（或改用 reference 参考高程）"

        with rasterio.open(before_path) as src_b:
            before = src_b.read(1, masked=True).astype("float64").filled(np.nan)
            vb = np.isfinite(before)
            if src_b.nodata is not None:
                vb &= before != src_b.nodata
            tr_b, crs_b = src_b.transform, src_b.crs
            hb, wb = src_b.height, src_b.width
            volume_warnings = []
            before_tags = {key.upper(): value for key, value in src_b.tags().items()}
            before_units = ((src_b.units[0] if src_b.units and src_b.units[0] else None)
                            or before_tags.get("VALUE_UNITS") or before_tags.get("UNITTYPE"))
            before_scale = _elevation_unit_to_m(before_units)
            if before_scale is None:
                volume_warnings.append(
                    f"源栅格「{before_layer}」未标注或无法识别高程单位；计算按米解释，请核实源数据"
                )
                before_scale = 1.0
            before *= before_scale
            if use_ref:
                after = np.full(before.shape, float(ref_val), dtype="float64")
                va = np.ones(before.shape, dtype=bool)
                after_desc = f"参考高程面 {ref_val:.6g} m"
            else:
                with rasterio.open(after_path) as src_a:
                    if (src_a.height, src_a.width) != (hb, wb):
                        return (f"填挖方失败: 两个 DEM 行列数不一致（{hb}x{wb} vs "
                                f"{src_a.height}x{src_a.width}），请先重采样或裁剪到同一网格")
                    if not np.allclose(np.asarray(tr_b, dtype="float64"),
                                       np.asarray(src_a.transform, dtype="float64"),
                                       rtol=1e-9, atol=1e-9):
                        return "填挖方失败: 两个 DEM 地理变换不一致（不是共配准栅格），请先重投影/重采样到同一网格"
                    if str(crs_b) != str(src_a.crs):
                        return f"填挖方失败: 两个 DEM 坐标系不一致（{crs_b} vs {src_a.crs}），请先统一坐标系"
                    after = src_a.read(1, masked=True).astype("float64").filled(np.nan)
                    va = np.isfinite(after)
                    if src_a.nodata is not None:
                        va &= after != src_a.nodata
                    after_tags = {key.upper(): value for key, value in src_a.tags().items()}
                    after_units = ((src_a.units[0] if src_a.units and src_a.units[0] else None)
                                   or after_tags.get("VALUE_UNITS") or after_tags.get("UNITTYPE"))
                    after_scale = _elevation_unit_to_m(after_units)
                    if after_scale is None:
                        volume_warnings.append(
                            f"源栅格「{after_layer}」未标注或无法识别高程单位；计算按米解释，请核实源数据"
                        )
                        after_scale = 1.0
                    after *= after_scale
                after_desc = f"设计 DEM「{after_layer}」"

            valid = vb & va
            diff = after - before
            d = diff[valid]
            if d.size == 0:
                return "填挖方失败: 两个 DEM 没有共同有效像元（nodata 或范围不重叠）"
            pixel_area_m2, area_warnings = _raster_pixel_area_m2(src_b)
            volume_warnings.extend(area_warnings)
            cell_areas = np.asarray(pixel_area_m2, dtype="float64")
            if cell_areas.ndim == 0:
                area_weights = float(cell_areas)
                average_cell_area = float(cell_areas)
            else:
                area_weights = cell_areas
                average_cell_area = float(np.mean(cell_areas))
            diff_valid = np.where(valid, diff, 0.0)
            cut = float((np.clip(-diff_valid, 0.0, None) * area_weights).sum())
            fill = float((np.clip(diff_valid, 0.0, None) * area_weights).sum())
            net = fill - cut
            changed_mask = valid & (np.abs(diff) > 1e-9)
            changed_n = int(changed_mask.sum())
            changed_area = float((changed_mask * area_weights).sum())
            zmin, zmax = float(d.min()), float(d.max())
            diff_out = np.where(valid, diff, np.nan)
            # Difference values have different semantics from source elevations; a source
            # sentinel such as 0 can be a valid unchanged difference and must not mask it.
            out_nodata = np.nan
            arr = np.where(np.isfinite(diff_out), diff_out, out_nodata)
            out_name = (
                f"{_safe_layer_export_stem(before_layer)}_{uuid.uuid4().hex}_填挖方"
            )
            out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
            with rasterio.open(out_path, "w", **_raster_out_profile(src_b, out_nodata)) as dst:
                dst.write(arr.astype("float32"), 1)
            source_layer_name = before_layer if use_ref else f"{before_layer} + {after_layer}"
            preview_context = _raster_preview_context(before_layer, value_units="m")
            preview_context["source_layer"] = source_layer_name
            inherited_warnings = preview_context.get("quality_warnings") or []
            preview_context["quality_warnings"] = list(inherited_warnings) + [
                warning for warning in volume_warnings if warning not in inherited_warnings
            ]
            note = _raster_preview_op(
                src_b, arr[None, :, :], out_name, "填挖方高程差", **preview_context
            )
        summary = (f"填挖方计算完成（现状={before_layer}，设计={after_desc}）：\n"
                   f"挖方量 {cut:,.2f} m3，填方量 {fill:,.2f} m3，净方量 {net:,.2f} m3（正数=净填）\n"
                   f"变化面积 {changed_area:,.2f} m2（{changed_n} 个像元，平均单像元面积 {average_cell_area:.6g} m2），"
                   f"高程差范围 [{zmin:.6g}, {zmax:.6g}] m\n")
        if volume_warnings:
            summary += "质量提示：" + "；".join(volume_warnings) + "\n"
        return summary + f"结果已保存 {out_name}.tif；{note}"
    except Exception as e:
        return f"填挖方失败: {str(e)[:300]}"

