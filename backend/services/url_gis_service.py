# -*- coding: utf-8 -*-
"""GIS URL 智能探测、检索与数据抓取服务 (URL-Driven GIS Data Service)

支持多协议/多格式探测与数据抽取，解耦数据流与地图渲染（Data-First 原则）：
1. 格式/服务探测：ArcGIS REST (MapServer/FeatureServer)、OGC (WFS/WMS/WMTS)、GeoJSON、
   GeoParquet、FlatGeobuf、PMTiles、COG/GeoTIFF、Shapefile ZIP、CSV 坐标表、XYZ 瓦片
2. 数据按需抽取：支持 BBox 空间过滤、Where 属性过滤、字段选择、Limit 分页与采样
3. 标准化落地：自动探测 CRS 并转换为 WGS84 (EPSG:4326)，支持导出为 GeoJSON / GPKG / CSV，
   返回结构化元数据、字段列表、要素预览样本与本地物理文件路径。
"""

import os
import io
import re
import json
import time
import zipfile
import urllib.parse
from typing import Dict, Any, Optional, List, Tuple
import requests

from backend.services.cloud_native import get_effective_proxies, parse_bbox


class UrlGisError(Exception):
    """URL GIS 服务错误"""
    pass


def _get_request_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GIS-WorkTable/2.0",
        "Accept": "*/*",
    }


def _http_get(url: str, params: dict = None, timeout: int = 15) -> requests.Response:
    proxies = get_effective_proxies()
    headers = _get_request_headers()
    try:
        resp = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception as e:
        raise UrlGisError(f"HTTP 请求失败 ({url}): {str(e)}")


def _get_output_dir() -> str:
    """获取数据下载落盘目录"""
    from backend.services.tools import _temp_output_dir, init_temp_dir
    init_temp_dir()
    d = os.path.join(_temp_output_dir, "downloads")
    os.makedirs(d, exist_ok=True)
    return d


# ============================================================
# 1. 协议与类型嗅探 (Inspection)
# ============================================================

def inspect_gis_url(url: str) -> Dict[str, Any]:
    """探测指定 URL 的 GIS 服务或数据类型，提取图层、坐标系、字段、范围与要素信息。"""
    u = str(url).strip()
    if not u.startswith(("http://", "https://")):
        raise UrlGisError("URL 必须以 http:// 或 https:// 开头")

    lower_u = u.lower()

    # 1.1 云原生 / 特殊二进制文件扩展名快速分流
    if lower_u.endswith((".tif", ".tiff")):
        return _inspect_cog(u)
    if lower_u.endswith(".pmtiles"):
        return _inspect_pmtiles(u)
    if lower_u.endswith((".parquet", ".geoparquet")):
        return _inspect_geoparquet(u)
    if lower_u.endswith(".fgb"):
        return _inspect_flatgeobuf(u)
    if lower_u.endswith(".zip"):
        return _inspect_zip_shapefile(u)

    # 1.2 ArcGIS REST 探测 (MapServer / FeatureServer / Services Directory)
    if "/arcgis/rest/services" in lower_u or "/mapserver" in lower_u or "/featureserver" in lower_u or "rest/services" in lower_u:
        return _inspect_arcgis_rest(u)

    # 1.3 OGC 服务探测 (WFS / WMS / WMTS)
    if "service=wfs" in lower_u or "/wfs" in lower_u:
        return _inspect_ogc_wfs(u)
    if "service=wmts" in lower_u or "/wmts" in lower_u:
        return _inspect_ogc_wmts(u)
    if "service=wms" in lower_u or "/wms" in lower_u:
        return _inspect_ogc_wms(u)

    # 1.4 XYZ 瓦片模板探测
    if "{z}" in u and "{x}" in u and "{y}" in u:
        return {
            "ok": True,
            "url": u,
            "service_type": "XYZ_Tile",
            "format": "Raster/Vector Tiles",
            "description": "XYZ / Slippy Map 瓦片服务模板",
            "tile_url_pattern": u,
        }

    # 1.5 通用 HTTP 请求探测 Content-Type 与响应内容
    try:
        resp = _http_get(u, timeout=10)
        content_type = resp.headers.get("Content-Type", "").lower()
        body_sample = resp.content[:2048]

        # 检查是否为 JSON / GeoJSON / ArcGIS REST
        if "application/json" in content_type or "geo+json" in content_type or body_sample.startswith(b"{") or body_sample.startswith(b"["):
            try:
                js = resp.json()
                # 检查是否为 GeoJSON
                if isinstance(js, dict) and js.get("type") in ("FeatureCollection", "Feature", "Point", "Polygon", "MultiPolygon", "LineString", "MultiLineString"):
                    return _summarize_geojson(u, js)
                # 检查是否为 ArcGIS REST 根或图层
                if isinstance(js, dict) and ("layers" in js or "fields" in js or "spatialReference" in js or "currentVersion" in js):
                    return _parse_arcgis_json_metadata(u, js)
            except Exception:
                pass

        # 检查是否为 XML (OGC Capabilities)
        if "text/xml" in content_type or "application/xml" in content_type or b"<" in body_sample[:10]:
            text = resp.text
            if "WFS_Capabilities" in text or "wfs:WFS_Capabilities" in text:
                return _parse_wfs_capabilities_xml(u, text)
            if "WMS_Capabilities" in text or "WMT_MS_Capabilities" in text:
                return _parse_wms_capabilities_xml(u, text)
            if "Capabilities" in text and "wmts" in text.lower():
                return _parse_wmts_capabilities_xml(u, text)

        # 检查 CSV
        if "text/csv" in content_type or lower_u.endswith((".csv", ".tsv", ".txt")):
            return _inspect_csv_text(u, resp.text)

    except Exception as e:
        # Fallback: 尝试作为 ArcGIS REST 探测
        try:
            return _inspect_arcgis_rest(u)
        except Exception:
            raise UrlGisError(f"未能解析 URL 所属的 GIS 服务或数据类型: {e}")

    return {
        "ok": True,
        "url": u,
        "service_type": "Unknown_Web_Resource",
        "content_type": content_type,
        "message": "未能识别为已知 GIS 服务协议，请检查 URL 是否正确或附带相应参数",
    }


# ============================================================
# 2. 细分格式元数据解析
# ============================================================

def _summarize_geojson(url: str, geojson: dict) -> dict:
    """提取 GeoJSON 的要素计数、字段表、几何类型与 BBox"""
    features = []
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
    elif geojson.get("type") == "Feature":
        features = [geojson]
    else:
        features = [{"type": "Feature", "geometry": geojson, "properties": {}}]

    geom_types = set()
    fields = set()
    sample_records = []
    coords = []

    for i, f in enumerate(features):
        geom = f.get("geometry") or {}
        gtype = geom.get("type")
        if gtype:
            geom_types.add(gtype)
        props = f.get("properties") or {}
        fields.update(props.keys())
        if i < 5:
            sample_records.append(props)

        # 简易抽样算 bbox
        c = geom.get("coordinates")
        if c and len(coords) < 200:
            _flatten_coords(c, coords)

    bbox = None
    if coords:
        lons = [pt[0] for pt in coords if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        lats = [pt[1] for pt in coords if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        if lons and lats:
            bbox = [round(min(lons), 6), round(min(lats), 6), round(max(lons), 6), round(max(lats), 6)]

    return {
        "ok": True,
        "url": url,
        "service_type": "GeoJSON",
        "format": "Vector (GeoJSON)",
        "feature_count": len(features),
        "geometry_types": sorted(list(geom_types)),
        "crs": "EPSG:4326 (WGS84)",
        "bbox": bbox,
        "fields": sorted(list(fields)),
        "field_count": len(fields),
        "sample_records": sample_records,
        "is_direct_downloadable": True,
    }


def _flatten_coords(c, out):
    if isinstance(c, (list, tuple)):
        if len(c) >= 2 and isinstance(c[0], (int, float)) and isinstance(c[1], (int, float)):
            out.append(c)
        else:
            for item in c:
                _flatten_coords(item, out)


def _inspect_arcgis_rest(url: str) -> dict:
    """探测 ArcGIS MapServer / FeatureServer REST 接口"""
    clean_url = url.split("?")[0].rstrip("/")
    # 请求 json 元数据
    json_url = f"{clean_url}?f=pjson"
    resp = _http_get(json_url)
    try:
        data = resp.json()
    except Exception:
        data = _http_get(f"{clean_url}?f=json").json()

    return _parse_arcgis_json_metadata(url, data, base_url=clean_url)


def _parse_arcgis_json_metadata(url: str, data: dict, base_url: str = "") -> dict:
    """解析 ArcGIS REST 返回的 Services Catalog / Service / Layer JSON"""
    if "services" in data and isinstance(data["services"], list):
        # 是 ArcGIS REST 组织/服务目录根目录
        svc_list = []
        for s in data["services"]:
            s_name = s.get("name")
            s_type = s.get("type")
            s_url = s.get("url") or (f"{base_url}/{s_name}/{s_type}" if base_url else "")
            svc_list.append({"name": s_name, "type": s_type, "url": s_url})
        return {
            "ok": True,
            "url": url,
            "service_type": "ArcGIS_REST_Directory",
            "service_count": len(svc_list),
            "services": svc_list,
            "current_version": data.get("currentVersion"),
            "description": f"ArcGIS REST 服务目录根，共发布 {len(svc_list)} 个空间服务",
        }

    if "layers" in data and isinstance(data["layers"], list):
        # 是 MapServer / FeatureServer 服务根
        service_name = data.get("mapName") or data.get("serviceDescription") or "ArcGIS Service"
        sr = data.get("spatialReference", {})
        crs = f"EPSG:{sr.get('latestWkid') or sr.get('wkid') or 'Unknown'}"
        sub_layers = []
        for l in data["layers"]:
            sub_layers.append({
                "id": l.get("id"),
                "name": l.get("name"),
                "parent_layer_id": l.get("parentLayerId"),
                "geometry_type": l.get("geometryType", "").replace("esriGeometry", ""),
                "min_scale": l.get("minScale"),
                "max_scale": l.get("maxScale"),
            })
        full_extent = data.get("fullExtent") or data.get("initialExtent") or {}
        bbox = None
        if "xmin" in full_extent and "ymin" in full_extent:
            bbox = [full_extent.get("xmin"), full_extent.get("ymin"), full_extent.get("xmax"), full_extent.get("ymax")]

        return {
            "ok": True,
            "url": url,
            "service_type": "ArcGIS_REST_Service",
            "service_name": service_name,
            "crs": crs,
            "layer_count": len(sub_layers),
            "layers": sub_layers,
            "bbox": bbox,
            "capabilities": data.get("capabilities", ""),
            "description": data.get("description") or data.get("serviceDescription") or "",
            "supported_query_formats": data.get("supportedQueryFormats", "JSON, geoJSON"),
        }

    # 是具体的 Layer 节点 (如 /MapServer/0 或 /FeatureServer/1)
    layer_name = data.get("name", "ArcGIS Layer")
    geom_type = data.get("geometryType", "").replace("esriGeometry", "")
    sr = data.get("spatialReference", {})
    crs = f"EPSG:{sr.get('latestWkid') or sr.get('wkid') or 'Unknown'}"
    fields_info = []
    for f in data.get("fields", []):
        fields_info.append({
            "name": f.get("name"),
            "type": f.get("type", "").replace("esriFieldType", ""),
            "alias": f.get("alias") or f.get("name"),
        })

    ext = data.get("extent") or {}
    bbox = None
    if "xmin" in ext and "ymin" in ext:
        bbox = [ext.get("xmin"), ext.get("ymin"), ext.get("xmax"), ext.get("ymax")]

    return {
        "ok": True,
        "url": url,
        "service_type": "ArcGIS_REST_Layer",
        "layer_name": layer_name,
        "layer_id": data.get("id"),
        "geometry_type": geom_type,
        "crs": crs,
        "bbox": bbox,
        "max_record_count": data.get("maxRecordCount", 1000),
        "fields": fields_info,
        "field_count": len(fields_info),
        "capabilities": data.get("capabilities", ""),
        "description": data.get("description") or "",
    }


def _inspect_ogc_wfs(url: str) -> dict:
    """探测 OGC WFS 服务 GetCapabilities"""
    clean_url = url.split("?")[0]
    cap_url = f"{clean_url}?SERVICE=WFS&REQUEST=GetCapabilities&VERSION=2.0.0"
    try:
        resp = _http_get(cap_url)
        return _parse_wfs_capabilities_xml(url, resp.text)
    except Exception:
        # Fallback to WFS 1.1.0
        cap_url = f"{clean_url}?SERVICE=WFS&REQUEST=GetCapabilities&VERSION=1.1.0"
        resp = _http_get(cap_url)
        return _parse_wfs_capabilities_xml(url, resp.text)


def _parse_wfs_capabilities_xml(url: str, xml_text: str) -> dict:
    """解析 WFS Capabilities XML"""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        raise UrlGisError(f"WFS XML 解析失败: {e}")

    # 去除命名空间前缀遍历
    layers = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "FeatureType":
            name = ""
            title = ""
            crs = ""
            bbox = None
            for child in elem:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "Name":
                    name = (child.text or "").strip()
                elif ctag == "Title":
                    title = (child.text or "").strip()
                elif ctag in ("DefaultCRS", "DefaultSRS", "CRS", "SRS"):
                    if not crs:
                        crs = (child.text or "").strip()
                elif ctag in ("WGS84BoundingBox", "LowerCorner", "UpperCorner"):
                    # 尝试读取 corner
                    text = (child.text or "").strip()
                    if text:
                        parts = text.split()
                        if len(parts) >= 4:
                            try:
                                bbox = [float(p) for p in parts[:4]]
                            except Exception:
                                pass
            if name:
                layers.append({"name": name, "title": title or name, "default_crs": crs, "bbox": bbox})

    return {
        "ok": True,
        "url": url,
        "service_type": "OGC_WFS",
        "layer_count": len(layers),
        "layers": layers,
        "capabilities_sample": "WFS (Web Feature Service)",
    }


def _inspect_ogc_wms(url: str) -> dict:
    clean_url = url.split("?")[0]
    cap_url = f"{clean_url}?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0"
    resp = _http_get(cap_url)
    return _parse_wms_capabilities_xml(url, resp.text)


def _parse_wms_capabilities_xml(url: str, xml_text: str) -> dict:
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        raise UrlGisError(f"WMS XML 解析失败: {e}")

    layers = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "Layer":
            name = ""
            title = ""
            srs_list = []
            for child in elem:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "Name":
                    name = (child.text or "").strip()
                elif ctag == "Title":
                    title = (child.text or "").strip()
                elif ctag in ("CRS", "SRS"):
                    t = (child.text or "").strip()
                    if t and t not in srs_list and len(srs_list) < 5:
                        srs_list.append(t)
            if name:
                layers.append({"name": name, "title": title or name, "crs": srs_list})

    return {
        "ok": True,
        "url": url,
        "service_type": "OGC_WMS",
        "layer_count": len(layers),
        "layers": layers[:50],
        "description": "OGC Web Map Service (栅格地图渲染服务)",
    }


def _inspect_ogc_wmts(url: str) -> dict:
    clean_url = url.split("?")[0]
    cap_url = f"{clean_url}?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0"
    resp = _http_get(cap_url)
    return _parse_wmts_capabilities_xml(url, resp.text)


def _parse_wmts_capabilities_xml(url: str, xml_text: str) -> dict:
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        raise UrlGisError(f"WMTS XML 解析失败: {e}")

    layers = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "Layer":
            identifier = ""
            title = ""
            format_list = []
            for child in elem:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "Identifier":
                    identifier = (child.text or "").strip()
                elif ctag == "Title":
                    title = (child.text or "").strip()
                elif ctag == "Format":
                    f = (child.text or "").strip()
                    if f:
                        format_list.append(f)
            if identifier:
                layers.append({"identifier": identifier, "title": title or identifier, "formats": format_list})

    return {
        "ok": True,
        "url": url,
        "service_type": "OGC_WMTS",
        "layer_count": len(layers),
        "layers": layers,
        "description": "OGC Web Map Tile Service (切片地图服务)",
    }


def _inspect_cog(url: str) -> dict:
    from backend.services import cloud_native as cn
    info = cn.cog_info(url)
    return {
        "ok": True,
        "url": url,
        "service_type": "Cloud_Optimized_GeoTIFF",
        "crs": info.get("crs"),
        "bbox": info.get("bounds_wgs84"),
        "width": info.get("width"),
        "height": info.get("height"),
        "bands": info.get("count"),
        "dtypes": info.get("dtypes"),
        "nodata": info.get("nodata"),
        "is_tiled": info.get("is_tiled"),
        "compression": info.get("compression"),
        "stats_sampled": info.get("stats_sampled"),
    }


def _inspect_pmtiles(url: str) -> dict:
    from backend.services import cloud_native as cn
    reader, header = cn._pmtiles_open(url)
    _tt = header.get("tile_type", 0)
    tt_val = int(_tt.value) if hasattr(_tt, "value") else int(_tt)
    type_label = "Vector (MVT)" if tt_val == 1 else "Raster"
    return {
        "ok": True,
        "url": url,
        "service_type": "PMTiles",
        "tile_type": type_label,
        "min_zoom": header.get("min_zoom"),
        "max_zoom": header.get("max_zoom"),
        "bounds": [header.get("min_lon"), header.get("min_lat"), header.get("max_lon"), header.get("max_lat")],
        "center": [header.get("center_lon"), header.get("center_lat"), header.get("center_zoom")],
    }


def _inspect_geoparquet(url: str) -> dict:
    from backend.services import cloud_native as cn
    vsi = cn._as_vsi_path(url)
    meta = cn.read_vector_metadata_pyogrio(vsi)
    return {
        "ok": True,
        "url": url,
        "service_type": "GeoParquet",
        "feature_count": meta.get("features"),
        "geometry_types": [meta.get("geometry_type")],
        "crs": meta.get("crs"),
        "fields": meta.get("fields", []),
        "field_count": len(meta.get("fields", [])),
    }


def _inspect_flatgeobuf(url: str) -> dict:
    from backend.services import cloud_native as cn
    vsi = cn._as_vsi_path(url)
    meta = cn.read_vector_metadata_pyogrio(vsi)
    return {
        "ok": True,
        "url": url,
        "service_type": "FlatGeobuf",
        "feature_count": meta.get("features"),
        "geometry_types": [meta.get("geometry_type")],
        "crs": meta.get("crs"),
        "fields": meta.get("fields", []),
        "field_count": len(meta.get("fields", [])),
    }


def _inspect_zip_shapefile(url: str) -> dict:
    import geopandas as gpd
    import tempfile
    resp = _http_get(url)
    out_dir = tempfile.mkdtemp(prefix="shp_zip_")
    zip_path = os.path.join(out_dir, "data.zip")
    with open(zip_path, "wb") as f:
        f.write(resp.content)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(out_dir)

    shp_files = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.lower().endswith(".shp")]
    if not shp_files:
        raise UrlGisError("ZIP 压缩包内未找到 .shp 文件")

    gdf = gpd.read_file(shp_files[0])
    crs_str = str(gdf.crs) if gdf.crs else "Unknown"
    bounds = list(gdf.total_bounds) if not gdf.empty else None
    return {
        "ok": True,
        "url": url,
        "service_type": "Shapefile_ZIP",
        "shapefile_name": os.path.basename(shp_files[0]),
        "feature_count": len(gdf),
        "geometry_types": sorted(list(set(gdf.geometry.geom_type.dropna()))),
        "crs": crs_str,
        "bbox": bounds,
        "fields": [str(c) for c in gdf.columns if c != "geometry"],
        "sample_records": json.loads(gdf.drop(columns="geometry").head(5).to_json(orient="records")),
    }


def _inspect_csv_text(url: str, text: str) -> dict:
    import pandas as pd
    df = pd.read_csv(io.StringIO(text), nrows=100)
    cols = list(df.columns)
    lon_col = next((c for c in cols if c.lower() in ("lon", "lng", "longitude", "经度", "x")), None)
    lat_col = next((c for c in cols if c.lower() in ("lat", "latitude", "纬度", "y")), None)

    return {
        "ok": True,
        "url": url,
        "service_type": "CSV_Coordinates_Table",
        "row_count_sampled": len(df),
        "columns": cols,
        "detected_lon_col": lon_col,
        "detected_lat_col": lat_col,
        "has_spatial_coordinates": bool(lon_col and lat_col),
        "sample_records": df.head(5).to_dict(orient="records"),
    }


# ============================================================
# 3. 数据按需抽取与持久化 (Fetch & Extract)
# ============================================================

def fetch_gis_data_url(
    url: str,
    layer_id: str = "",
    bbox: str = "",
    where: str = "1=1",
    limit: int = 1000,
    output_format: str = "geojson",
    output_filename: str = "",
) -> Dict[str, Any]:
    """从 GIS URL 提取矢量数据、标准化坐标系为 WGS84 并保存到会话下载目录。
    支持 ArcGIS REST Query, OGC WFS GetFeature, GeoJSON URL, GeoParquet, FlatGeobuf, CSV。
    返回物理文件路径与结构化数据报告。
    """
    inspection = inspect_gis_url(url)
    stype = inspection.get("service_type", "")
    out_dir = _get_output_dir()
    timestamp = int(time.time())
    base_name = output_filename or f"fetched_{timestamp}"
    base_name = re.sub(r'[\\/:*?"<>|]', "_", base_name)

    import geopandas as gpd

    gdf: Optional[gpd.GeoDataFrame] = None

    # 3.1 ArcGIS REST Query 抓取
    if "ArcGIS_REST" in stype:
        gdf = _fetch_arcgis_features(url, layer_id=layer_id, bbox=bbox, where=where, limit=limit)

    # 3.2 OGC WFS 抓取
    elif stype == "OGC_WFS":
        gdf = _fetch_wfs_features(url, type_name=layer_id, bbox=bbox, limit=limit)

    # 3.3 直接 GeoJSON URL 抓取
    elif stype == "GeoJSON":
        resp = _http_get(url)
        gdf = gpd.read_file(io.BytesIO(resp.content))
        if bbox:
            bbox_tuple = parse_bbox(bbox)
            if bbox_tuple:
                gdf = gdf.cx[bbox_tuple[0]:bbox_tuple[2], bbox_tuple[1]:bbox_tuple[3]]
        if limit and len(gdf) > limit:
            gdf = gdf.iloc[:limit]

    # 3.4 GeoParquet / FlatGeobuf 流式读取
    elif stype in ("GeoParquet", "FlatGeobuf"):
        from backend.services import cloud_native as cn
        fmt = "GeoParquet" if stype == "GeoParquet" else "FlatGeobuf"
        bbox_tuple = parse_bbox(bbox) if bbox else None
        gj_dict, meta = cn.cloud_vector_to_geojson(url, fmt, bbox=bbox_tuple, limit=limit)
        gdf = gpd.GeoDataFrame.from_features(gj_dict["features"])
        gdf.set_crs(epsg=4326, inplace=True)

    # 3.5 CSV 坐标表抓取
    elif stype == "CSV_Coordinates_Table":
        resp = _http_get(url)
        import pandas as pd
        df = pd.read_csv(io.StringIO(resp.text))
        lon_col = inspection.get("detected_lon_col")
        lat_col = inspection.get("detected_lat_col")
        if not (lon_col and lat_col):
            raise UrlGisError("未能从 CSV 中自动识别经纬度列（如 lon/lat），无法转为空间要素")
        gdf = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
            crs="EPSG:4326"
        )
        if limit and len(gdf) > limit:
            gdf = gdf.iloc[:limit]

    # 3.6 Shapefile ZIP 抓取
    elif stype == "Shapefile_ZIP":
        resp = _http_get(url)
        import tempfile
        out_temp = tempfile.mkdtemp(prefix="shp_fetch_")
        zip_path = os.path.join(out_temp, "data.zip")
        with open(zip_path, "wb") as f:
            f.write(resp.content)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(out_temp)
        shp_files = [os.path.join(out_temp, f) for f in os.listdir(out_temp) if f.lower().endswith(".shp")]
        gdf = gpd.read_file(shp_files[0])
        if limit and len(gdf) > limit:
            gdf = gdf.iloc[:limit]

    else:
        raise UrlGisError(f"服务类型 {stype} 目前不支持直接矢量要素抓取。如果是栅格/瓦片，请使用专用流式加载工具")

    if gdf is None or gdf.empty:
        return {
            "ok": True,
            "source_url": url,
            "service_type": stype,
            "feature_count": 0,
            "message": "查询成功，但返回要素数量为 0",
        }

    # 坐标系标准化为 WGS84 (EPSG:4326)
    original_crs = str(gdf.crs) if gdf.crs else "Unknown"
    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # 落盘保存为文件
    fmt_lower = output_format.lower().strip()
    if fmt_lower in ("gpkg", "geopackage"):
        save_path = os.path.join(out_dir, f"{base_name}.gpkg")
        gdf.to_file(save_path, driver="GPKG")
        ext = "gpkg"
    elif fmt_lower == "csv":
        save_path = os.path.join(out_dir, f"{base_name}.csv")
        # 导出带 WKT 的 CSV
        df_export = gdf.copy()
        df_export["wkt_geometry"] = df_export.geometry.to_wkt()
        df_export.drop(columns=["geometry"], inplace=True)
        df_export.to_csv(save_path, index=False, encoding="utf-8-sig")
        ext = "csv"
    else:  # 默认 GeoJSON
        save_path = os.path.join(out_dir, f"{base_name}.geojson")
        gdf.to_file(save_path, driver="GeoJSON")
        ext = "geojson"

    file_size = os.path.getsize(save_path)
    bounds = list(gdf.total_bounds)
    geom_types = sorted(list(set(gdf.geometry.geom_type.dropna())))
    non_geom_cols = [str(c) for c in gdf.columns if c != "geometry"]

    sample_preview = json.loads(gdf.drop(columns="geometry").head(5).to_json(orient="records"))

    return {
        "ok": True,
        "source_url": url,
        "service_type": stype,
        "file_path": os.path.abspath(save_path),
        "file_name": os.path.basename(save_path),
        "file_format": ext,
        "file_size_bytes": file_size,
        "feature_count": len(gdf),
        "crs": "EPSG:4326",
        "original_crs": original_crs,
        "bbox": [round(v, 6) for v in bounds],
        "geometry_types": geom_types,
        "fields": non_geom_cols,
        "field_count": len(non_geom_cols),
        "sample_records": sample_preview,
        "geojson_data": json.loads(gdf.to_json()) if len(gdf) <= 200 else None,
    }


def _fetch_arcgis_features(url: str, layer_id: str = "", bbox: str = "", where: str = "1=1", limit: int = 1000):
    """请求 ArcGIS REST Query 接口（支持自动探测图层 ID，如 id=10）"""
    import geopandas as gpd
    clean_url = url.split("?")[0].rstrip("/")

    # 1. 若为服务目录根（/services），自动寻找第一个 FeatureServer
    if clean_url.endswith("/services"):
        try:
            cat = _http_get(f"{clean_url}?f=pjson").json()
            svcs = cat.get("services", [])
            fs = next((s for s in svcs if s.get("type") == "FeatureServer"), None)
            if fs:
                clean_url = fs.get("url") or f"{clean_url}/{fs.get('name')}/FeatureServer"
        except Exception:
            pass

    # 2. 自动嗅探图层 ID（避免盲目写死 0 导致失败）
    if not layer_id and not any(clean_url.endswith(f"/{i}") for i in range(100)):
        try:
            fs_meta = _http_get(f"{clean_url}?f=pjson").json()
            sub_layers = fs_meta.get("layers", [])
            if sub_layers and "id" in sub_layers[0]:
                layer_id = str(sub_layers[0]["id"])
        except Exception:
            pass

    if layer_id and not clean_url.endswith(f"/{layer_id}"):
        query_url = f"{clean_url}/{layer_id}/query"
    elif any(clean_url.endswith(f"/{i}") for i in range(100)):
        query_url = f"{clean_url}/query"
    else:
        query_url = f"{clean_url}/0/query"

    params = {
        "where": where or "1=1",
        "outFields": "*",
        "f": "geojson",
        "resultRecordCount": limit or 1000,
        "outSR": 4326,
    }
    if bbox:
        bbox_tuple = parse_bbox(bbox)
        if bbox_tuple:
            params["geometry"] = f"{bbox_tuple[0]},{bbox_tuple[1]},{bbox_tuple[2]},{bbox_tuple[3]}"
            params["geometryType"] = "esriGeometryEnvelope"
            params["spatialRel"] = "esriSpatialRelIntersects"
            params["inSR"] = 4326

    resp = _http_get(query_url, params=params)
    try:
        gj = resp.json()
        if "features" in gj:
            return gpd.GeoDataFrame.from_features(gj["features"], crs="EPSG:4326")
    except Exception:
        pass

    # Fallback to f=json (ESRI Json)
    params["f"] = "json"
    resp2 = _http_get(query_url, params=params)
    data = resp2.json()
    if "features" in data and "fields" in data:
        # 转换 esri json
        from shapely.geometry import shape, Point, Polygon, LineString
        records = []
        for feat in data["features"]:
            geom = feat.get("geometry")
            props = feat.get("attributes", {})
            geom_obj = None
            if geom:
                if "x" in geom and "y" in geom:
                    geom_obj = Point(geom["x"], geom["y"])
                elif "rings" in geom:
                    geom_obj = Polygon(geom["rings"][0])
                elif "paths" in geom:
                    geom_obj = LineString(geom["paths"][0])
            if geom_obj:
                props["geometry"] = geom_obj
                records.append(props)
        if records:
            return gpd.GeoDataFrame(records, crs="EPSG:4326")

    raise UrlGisError("从 ArcGIS REST 获取要素失败或未返回有效要素数据")


def _fetch_wfs_features(url: str, type_name: str = "", bbox: str = "", limit: int = 1000):
    import geopandas as gpd
    clean_url = url.split("?")[0]
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "outputFormat": "application/json",
        "count": limit or 1000,
    }
    if type_name:
        params["typeNames"] = type_name
    if bbox:
        params["bbox"] = bbox

    resp = _http_get(clean_url, params=params)
    try:
        return gpd.read_file(io.BytesIO(resp.content))
    except Exception as e:
        # Fallback WFS 1.1.0
        params["VERSION"] = "1.1.0"
        params["maxFeatures"] = limit or 1000
        params.pop("count", None)
        resp2 = _http_get(clean_url, params=params)
        return gpd.read_file(io.BytesIO(resp2.content))
