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
import hashlib
import uuid
import datetime
import ntpath
import shutil
import urllib.parse
from pathlib import PurePosixPath
from typing import Dict, Any, Optional
import requests

from backend.services.cloud_native import get_effective_proxies, parse_bbox
from backend.services.url_security import (
    PinnedAddressHTTPAdapter,
    is_public_http_target,
    redirect_origin_key,
    redirect_is_allowed,
    sanitize_error_text,
    sanitize_http_url,
    sensitive_query_parameter_names,
    strip_query_parameters,
)

_HTTP_RESPONSE_CAP_BYTES = 300 * 1024 * 1024
_ZIP_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_ZIP_MAX_MEMBERS = 10000


class UrlGisError(Exception):
    """URL GIS 服务错误"""
    pass


def _size_limit_message(resource: str, max_bytes: int) -> str:
    limit_mb = max(1, max_bytes // (1024 * 1024))
    return f"{resource}超过 {limit_mb} MB 限制"


def _get_request_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GIS-WorkTable/2.0",
        "Accept": "*/*",
    }


def _http_get(url: str, params: dict = None, timeout: int = 15) -> requests.Response:
    proxies = get_effective_proxies()
    headers = _get_request_headers()
    session = requests.Session()
    try:
        current_url = url
        credentials_stripped = False
        credential_parameters = sensitive_query_parameter_names(url)
        if params:
            credential_query = urllib.parse.urlencode(params, doseq=True)
            credential_parameters.update(sensitive_query_parameter_names("?" + credential_query))
        initial_classification = is_public_http_target(url)
        protect_public_target = initial_classification is not False
        if initial_classification is not True:
            proxies = {"http": None, "https": None}
        # Only a clearly private initial target may use the direct-private path.
        # Mixed or unresolved DNS answers must not select an arbitrary address.
        pinned_adapter = PinnedAddressHTTPAdapter(
            initial_classification is not False,
            initial_private_url=url if initial_classification is False else None,
        )
        session.mount("http://", pinned_adapter)
        session.mount("https://", pinned_adapter)
        for redirect_count in range(11):
            resp = session.get(
                current_url,
                params=params if redirect_count == 0 else None,
                headers=headers,
                proxies=proxies,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
            if resp.status_code not in {301, 302, 303, 307, 308}:
                try:
                    if credentials_stripped and resp.status_code in {401, 403}:
                        raise UrlGisError(
                            "远程 GIS 服务在跨主机跳转后要求认证；为避免向新主机泄露凭据，认证参数未转发。"
                            "请改用服务方提供的直连地址。"
                        )
                    resp.raise_for_status()
                    content_length = resp.headers.get("Content-Length")
                    if content_length:
                        try:
                            if int(content_length) > _HTTP_RESPONSE_CAP_BYTES:
                                raise UrlGisError(_size_limit_message("远程 GIS 响应", _HTTP_RESPONSE_CAP_BYTES))
                        except ValueError:
                            pass
                    chunks = []
                    total_bytes = 0
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > _HTTP_RESPONSE_CAP_BYTES:
                            raise UrlGisError(_size_limit_message("远程 GIS 响应", _HTTP_RESPONSE_CAP_BYTES))
                        chunks.append(chunk)
                    resp._content = b"".join(chunks)
                    resp._content_consumed = True
                except Exception:
                    resp.close()
                    raise
                resp.close()
                return resp
            location = resp.headers.get("Location")
            next_url = urllib.parse.urljoin(current_url, location or "")
            resp.close()
            if not location or not redirect_is_allowed(next_url, protect_public_target):
                raise UrlGisError("远程 GIS 服务跳转地址不符合安全策略")
            if (
                credential_parameters
                and redirect_origin_key(current_url) != redirect_origin_key(next_url)
            ):
                stripped_url = strip_query_parameters(next_url, credential_parameters)
                credentials_stripped = credentials_stripped or stripped_url != next_url
                next_url = stripped_url
            if redirect_count == 10:
                raise UrlGisError("远程 GIS 服务跳转次数过多")
            # Preserve the user's private-origin allowance for private hops,
            # but make the guard sticky after a public or ambiguous hop.
            if is_public_http_target(next_url) is not False:
                protect_public_target = True
            current_url = next_url
            pinned_adapter.require_public_target = protect_public_target
        raise UrlGisError("远程 GIS 服务跳转次数过多")
    except Exception as e:
        safe_url = _sanitize_source_url(url)
        detail = sanitize_error_text(e, url)
        raise UrlGisError(f"HTTP 请求失败 ({safe_url}): {detail}")
    finally:
        session.close()


def _get_output_dir() -> str:
    """获取数据下载落盘目录"""
    from backend.services import tools as _tools
    _tools.init_temp_dir()
    d = os.path.join(_tools._temp_output_dir, "downloads")
    os.makedirs(d, exist_ok=True)
    return d


def _is_safe_zip_member(name: str) -> bool:
    raw_name = str(name or "")
    normalized = raw_name.replace("\\", "/")
    path = PurePosixPath(normalized)
    drive, _ = ntpath.splitdrive(raw_name)
    return bool(normalized) and not drive and not path.is_absolute() and ".." not in path.parts


def _safe_extract_zip(archive: zipfile.ZipFile, destination: str) -> None:
    members = archive.infolist()
    if len(members) > _ZIP_MAX_MEMBERS:
        raise UrlGisError("ZIP 压缩包文件数量超过限制")
    if any(not _is_safe_zip_member(member.filename) for member in members):
        raise UrlGisError("ZIP 压缩包包含不安全的文件路径")
    if sum(member.file_size for member in members) > _ZIP_MAX_UNCOMPRESSED_BYTES:
        raise UrlGisError(_size_limit_message("ZIP 压缩包解压后", _ZIP_MAX_UNCOMPRESSED_BYTES))
    archive.extractall(destination)


def _find_shapefiles(root: str) -> list:
    """Find extracted shapefiles at any directory depth in stable order."""
    matches = []
    for current, dirs, files in os.walk(root):
        dirs.sort()
        matches.extend(os.path.join(current, name) for name in sorted(files)
                       if name.lower().endswith(".shp"))
    return matches


def _sanitize_inspection_result(result: dict) -> dict:
    """探测元数据可返回给模型/API；其中的源 URL 不得携带认证信息。"""
    def scrub(value, key=""):
        if isinstance(value, dict):
            return {k: scrub(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(item, key) for item in value]
        if isinstance(value, str) and "url" in key.lower():
            return _sanitize_source_url(value)
        return value

    return scrub(result)


# ============================================================
# 1. 协议与类型嗅探 (Inspection)
# ============================================================

def inspect_gis_url(url: str) -> Dict[str, Any]:
    """探测指定 URL 的 GIS 服务或数据类型，提取图层、坐标系、字段、范围与要素信息。"""
    u = str(url).strip()
    parsed_url = urllib.parse.urlsplit(u)
    if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.netloc:
        raise UrlGisError("URL 必须以 http:// 或 https:// 开头")

    lower_u = u.lower()
    path_lower = parsed_url.path.lower()

    # 1.1 云原生 / 特殊二进制文件扩展名快速分流
    if path_lower.endswith((".tif", ".tiff")):
        return _sanitize_inspection_result(_inspect_cog(u))
    if path_lower.endswith(".pmtiles"):
        return _sanitize_inspection_result(_inspect_pmtiles(u))
    if path_lower.endswith((".parquet", ".geoparquet")):
        return _sanitize_inspection_result(_inspect_geoparquet(u))
    if path_lower.endswith(".fgb"):
        return _sanitize_inspection_result(_inspect_flatgeobuf(u))
    if path_lower.endswith(".zip"):
        return _sanitize_inspection_result(_inspect_zip_shapefile(u))

    # 1.2 ArcGIS REST 探测 (MapServer / FeatureServer / Services Directory)
    if "/arcgis/rest/services" in lower_u or "/mapserver" in lower_u or "/featureserver" in lower_u or "rest/services" in lower_u:
        return _sanitize_inspection_result(_inspect_arcgis_rest(u))

    # 1.3 OGC 服务探测 (WFS / WMS / WMTS)
    if "service=wfs" in lower_u or "/wfs" in lower_u:
        return _sanitize_inspection_result(_inspect_ogc_wfs(u))
    if "service=wmts" in lower_u or "/wmts" in lower_u:
        return _sanitize_inspection_result(_inspect_ogc_wmts(u))
    if "service=wms" in lower_u or "/wms" in lower_u:
        return _sanitize_inspection_result(_inspect_ogc_wms(u))

    # 1.4 XYZ 瓦片模板探测
    if "{z}" in u and "{x}" in u and "{y}" in u:
        return _sanitize_inspection_result({
            "ok": True,
            "url": u,
            "service_type": "XYZ_Tile",
            "format": "Raster/Vector Tiles",
            "description": "XYZ / Slippy Map 瓦片服务模板",
            "tile_url_pattern": u,
        })

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
                    return _sanitize_inspection_result(_summarize_geojson(u, js))
                # 检查是否为 ArcGIS REST 根或图层
                if isinstance(js, dict) and ("layers" in js or "fields" in js or "spatialReference" in js or "currentVersion" in js):
                    return _sanitize_inspection_result(_parse_arcgis_json_metadata(u, js))
            except Exception:
                pass

        # 检查是否为 XML (OGC Capabilities)
        if "text/xml" in content_type or "application/xml" in content_type or b"<" in body_sample[:10]:
            text = resp.text
            if "WFS_Capabilities" in text or "wfs:WFS_Capabilities" in text:
                return _sanitize_inspection_result(_parse_wfs_capabilities_xml(u, text))
            if "WMS_Capabilities" in text or "WMT_MS_Capabilities" in text:
                return _sanitize_inspection_result(_parse_wms_capabilities_xml(u, text))
            if "Capabilities" in text and "wmts" in text.lower():
                return _sanitize_inspection_result(_parse_wmts_capabilities_xml(u, text))

        # 检查 CSV
        if "text/csv" in content_type or lower_u.endswith((".csv", ".tsv", ".txt")):
            return _sanitize_inspection_result(_inspect_csv_text(u, resp.text))

    except Exception as e:
        # Fallback: 尝试作为 ArcGIS REST 探测
        try:
            return _sanitize_inspection_result(_inspect_arcgis_rest(u))
        except Exception:
            raise UrlGisError(f"未能解析 URL 所属的 GIS 服务或数据类型: {e}")

    return _sanitize_inspection_result({
        "ok": True,
        "url": u,
        "service_type": "Unknown_Web_Resource",
        "content_type": content_type,
        "message": "未能识别为已知 GIS 服务协议，请检查 URL 是否正确或附带相应参数",
    })


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
    credential_names = sensitive_query_parameter_names(url)
    auth_params = {k: v for k, v in urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)
                   if k in credential_names}
    # 请求 json 元数据
    resp = _http_get(clean_url, params=dict(auth_params, f="pjson"), timeout=30)
    try:
        data = resp.json()
    except Exception:
        data = _http_get(clean_url, params=dict(auth_params, f="json"), timeout=30).json()

    return _parse_arcgis_json_metadata(url, data, base_url=clean_url)


def _arcgis_crs_label(spatial_reference: dict) -> str:
    sr = spatial_reference or {}
    wkid = sr.get("latestWkid") or sr.get("wkid")
    if not wkid:
        return "Unknown"
    return f"EPSG:{wkid}" if sr.get("latestWkid") else f"ArcGIS WKID:{wkid}"


def _parse_arcgis_json_metadata(url: str, data: dict, base_url: str = "") -> dict:
    """解析 ArcGIS REST 返回的 Services Catalog / Service / Layer JSON"""
    if not isinstance(data, dict):
        raise UrlGisError("ArcGIS 元数据响应结构无效：JSON 根节点必须是对象")
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
        sr = data.get("sourceSpatialReference") or data.get("spatialReference") or {}
        crs = _arcgis_crs_label(sr)
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
            "supports_pagination": (data.get("advancedQueryCapabilities") or {}).get("supportsPagination"),
        }

    # 是具体的 Layer 节点 (如 /MapServer/0 或 /FeatureServer/1)
    layer_name = data.get("name", "ArcGIS Layer")
    geom_type = data.get("geometryType", "").replace("esriGeometry", "")
    sr = data.get("sourceSpatialReference") or data.get("spatialReference") or {}
    crs = _arcgis_crs_label(sr)
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
        "object_id_field": data.get("objectIdField") or next(
            (f.get("name") for f in data.get("fields", []) if f.get("type") == "esriFieldTypeOID"), None
        ),
        "supports_pagination": (data.get("advancedQueryCapabilities") or {}).get("supportsPagination"),
        "supported_query_formats": data.get("supportedQueryFormats", ""),
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
    header = cn.pmtiles_header(url)
    summary = cn.pmtiles_header_summary(header)
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
        "bounds": summary["bounds_wgs84"],
        "center": summary["center"],
    }


def _inspect_geoparquet(url: str) -> dict:
    from backend.services import cloud_native as cn
    meta = cn.cloud_vector_metadata(url, "GeoParquet")
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
    meta = cn.cloud_vector_metadata(url, "FlatGeobuf")
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
    try:
        zip_path = os.path.join(out_dir, "data.zip")
        with open(zip_path, "wb") as f:
            f.write(resp.content)
        with zipfile.ZipFile(zip_path, "r") as z:
            _safe_extract_zip(z, out_dir)

        shp_files = _find_shapefiles(out_dir)
        if not shp_files:
            raise UrlGisError("ZIP 压缩包内未找到 .shp 文件")
        gdf = gpd.read_file(shp_files[0])
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
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
    mode: str = "preview",
    max_features: int = 100000,
    progress_callback=None,
    cancel_check=None,
) -> Dict[str, Any]:
    """从 GIS URL 提取矢量数据、标准化坐标系为 WGS84 并保存到会话下载目录。
    支持 ArcGIS REST Query, OGC WFS GetFeature, GeoJSON URL, GeoParquet, FlatGeobuf, CSV。
    返回物理文件路径与结构化数据报告。
    """
    mode = (mode or "preview").strip().lower()
    if mode not in {"preview", "full"}:
        raise UrlGisError("mode 只能是 preview 或 full")
    try:
        limit = int(limit)
    except (OverflowError, TypeError, ValueError) as exc:
        raise UrlGisError("limit 必须是正整数") from exc
    if limit <= 0:
        raise UrlGisError("limit 必须是正整数")
    if isinstance(max_features, bool) or not isinstance(max_features, int) or max_features <= 0:
        raise UrlGisError("max_features 必须是正整数")
    max_features = min(max_features, 1_000_000)
    output_format = str(output_format or "").strip().lower()
    if output_format == "geopackage":
        output_format = "gpkg"
    if output_format not in {"geojson", "gpkg", "csv"}:
        raise UrlGisError("output_format 仅支持 geojson、gpkg 或 csv")
    inspection = inspect_gis_url(url)
    stype = inspection.get("service_type", "")
    out_dir = _get_output_dir()
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base_name = output_filename or f"fetched_{timestamp}_{uuid.uuid4().hex[:6]}"
    base_name = re.sub(r'[\\/:*?"<>|]', "_", base_name)
    base_name = os.path.splitext(base_name)[0] or f"fetched_{timestamp}"
    while any(os.path.exists(os.path.join(out_dir, f"{base_name}.{suffix}"))
              for suffix in ("geojson", "gpkg", "csv", "recipe.json", "report.md", "manifest.json")):
        base_name = f"{base_name}_{uuid.uuid4().hex[:6]}"

    import geopandas as gpd

    gdf: Optional[gpd.GeoDataFrame] = None
    acquisition = {
        "mode": mode,
        "expected_count": None,
        "expected_count_known": False,
        "completeness": "not_checked" if mode == "preview" else "unknown",
        "completeness_reason": "限量预览不会检查源数据完整性" if mode == "preview" else "尚未完成完整性检查",
        "checks": [],
        "warnings": [],
    }

    # 3.1 ArcGIS REST Query 抓取
    if "ArcGIS_REST" in stype:
        gdf, acquisition = _fetch_arcgis_features(
            url, layer_id=layer_id, bbox=bbox, where=where,
            limit=limit, mode=mode, max_features=max_features,
            progress_callback=progress_callback, cancel_check=cancel_check,
        )
    elif mode == "full":
        raise UrlGisError("当前仅支持 ArcGIS REST 图层的全量获取；其他来源请使用限量预览")

    # 3.2 OGC WFS 抓取
    elif stype == "OGC_WFS":
        gdf = _fetch_wfs_features(url, type_name=layer_id, bbox=bbox, limit=limit)

    # 3.3 直接 GeoJSON URL 抓取
    elif stype == "GeoJSON":
        resp = _http_get(url)
        gdf = gpd.read_file(io.BytesIO(resp.content))
        if bbox:
            if gdf.crs is None:
                raise UrlGisError("GeoJSON 未提供坐标系，无法安全应用 WGS84 bbox 过滤")
            if gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
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
        try:
            zip_path = os.path.join(out_temp, "data.zip")
            with open(zip_path, "wb") as f:
                f.write(resp.content)
            with zipfile.ZipFile(zip_path, "r") as z:
                _safe_extract_zip(z, out_temp)
            shp_files = _find_shapefiles(out_temp)
            if not shp_files:
                raise UrlGisError("ZIP 压缩包内未找到 .shp 文件")
            gdf = gpd.read_file(shp_files[0])
        finally:
            shutil.rmtree(out_temp, ignore_errors=True)
        if limit and len(gdf) > limit:
            gdf = gdf.iloc[:limit]

    else:
        raise UrlGisError(f"服务类型 {stype} 目前不支持直接矢量要素抓取。如果是栅格/瓦片，请使用专用流式加载工具")

    if gdf is None:
        raise UrlGisError("数据源没有返回可读取的矢量要素")

    # ArcGIS 请求显式指定 outSR=4326；其他协议必须提供真实 CRS 才能转换。
    original_crs = acquisition.get("source_crs") or (str(gdf.crs) if gdf.crs else "Unknown")
    if gdf.crs is None:
        if "ArcGIS_REST" in stype:
            gdf.set_crs(epsg=4326, inplace=True)
            acquisition["checks"].append({"name": "output_crs", "status": "passed", "detail": "ArcGIS 查询显式请求 outSR=4326"})
        else:
            raise UrlGisError("数据源未提供可确认的坐标系，已停止导出以避免错误标注为 WGS84")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    if len(gdf) == 0:
        acquisition["checks"].append({"name": "empty_result", "status": "passed", "detail": "查询成功，匹配要素数为 0"})

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
    file_hash = hashlib.sha256()
    with open(save_path, "rb") as saved_file:
        for chunk in iter(lambda: saved_file.read(1024 * 1024), b""):
            file_hash.update(chunk)
    bounds = list(gdf.total_bounds) if len(gdf) else None
    geom_types = sorted(list(set(gdf.geometry.geom_type.dropna())))
    non_geom_cols = [str(c) for c in gdf.columns if c != "geometry"]

    sample_preview = json.loads(gdf.drop(columns="geometry").head(5).to_json(orient="records"))

    safe_source_url = _sanitize_source_url(url)
    recipe_path = os.path.join(out_dir, f"{base_name}.recipe.json")
    report_path = os.path.join(out_dir, f"{base_name}.report.md")
    manifest = {
        "schema_version": 1,
        "source_url": safe_source_url,
        "layer_id": str(acquisition.get("layer_id") or layer_id or inspection.get("layer_id") or ""),
        "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": mode,
        "query": {"bbox": bbox or "", "where": where or "1=1", "limit": limit if mode == "preview" else None},
        "feature_count": len(gdf),
        "expected_count": acquisition.get("expected_count"),
        "expected_count_known": acquisition.get("expected_count_known", False),
        "completeness": acquisition.get("completeness", "unknown"),
        "completeness_reason": acquisition.get("completeness_reason", ""),
        "checks": acquisition.get("checks", []),
        "warnings": acquisition.get("warnings", []),
        "crs": "EPSG:4326",
        "original_crs": original_crs,
        "output": {"filename": os.path.basename(save_path), "format": ext, "size_bytes": file_size, "sha256": file_hash.hexdigest()},
        "license": "unknown",
    }
    manifest_path = os.path.join(out_dir, f"{base_name}.manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)
    with open(recipe_path, "w", encoding="utf-8") as recipe_file:
        json.dump({"schema_version": 1, "source_url": safe_source_url, "layer_id": manifest["layer_id"], "bbox": bbox or "", "where": where or "1=1", "mode": mode, "limit": limit if mode == "preview" else None, "output_format": ext, "max_features": max_features}, recipe_file, ensure_ascii=False, indent=2)
    report_lines = [
        "# ArcGIS REST 数据获取报告", "", f"- 来源：{safe_source_url}",
        f"- 图层：{manifest['layer_id'] or '自动选择'}", f"- 获取时间：{manifest['retrieved_at']}",
        f"- 模式：{'完整获取' if mode == 'full' else '限量预览'}", f"- 实际要素数：{len(gdf)}",
        f"- 预期要素数：{manifest['expected_count'] if manifest['expected_count_known'] else '未知'}",
        f"- 完整性：{manifest['completeness']}（{manifest['completeness_reason']}）",
        f"- 坐标系：EPSG:4326（来源声明：{original_crs}）", f"- 文件 SHA-256：{file_hash.hexdigest()}",
        f"- 许可：未知；请在使用和再分发前核对源服务条款。", "",
        "## 检查范围", "",
        "哈希仅用于核对文件内容；数量一致不能证明属性正确；几何有效不能证明分析方法正确；抽样检查不代表全量内容均已验证。", "",
        "## 检查记录", "",
    ]
    report_lines.extend([f"- {c.get('name')}: {c.get('status')} — {c.get('detail', '')}" for c in manifest["checks"]] or ["- 未执行额外检查"])
    if manifest["warnings"]:
        report_lines.extend(["", "## 警告", ""] + [f"- {w}" for w in manifest["warnings"]])
    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write("\n".join(report_lines) + "\n")

    return {
        "ok": True,
        "source_url": safe_source_url,
        "service_type": stype,
        "file_path": os.path.abspath(save_path),
        "file_name": os.path.basename(save_path),
        "file_format": ext,
        "file_size_bytes": file_size,
        "sha256": file_hash.hexdigest(),
        "recipe_path": os.path.abspath(recipe_path),
        "report_path": os.path.abspath(report_path),
        "manifest_path": os.path.abspath(manifest_path),
        "mode": mode,
        "expected_count": acquisition.get("expected_count"),
        "expected_count_known": acquisition.get("expected_count_known", False),
        "completeness": acquisition.get("completeness", "unknown"),
        "completeness_reason": acquisition.get("completeness_reason", ""),
        "checks": acquisition.get("checks", []),
        "warnings": acquisition.get("warnings", []),
        "feature_count": len(gdf),
        "crs": "EPSG:4326",
        "original_crs": original_crs,
        "bbox": [round(v, 6) for v in bounds] if bounds else None,
        "geometry_types": geom_types,
        "fields": non_geom_cols,
        "field_count": len(non_geom_cols),
        "sample_records": sample_preview,
        "geojson_data": json.loads(gdf.to_json()) if len(gdf) <= 200 else None,
    }


def _sanitize_source_url(url: str) -> str:
    return sanitize_http_url(url)


def _fetch_arcgis_features(
    url: str, layer_id: str = "", bbox: str = "", where: str = "1=1", limit: int = 1000,
    mode: str = "preview", max_features: int = 100000, progress_callback=None, cancel_check=None,
):
    """获取 ArcGIS REST 图层；完整模式先取对象 ID 清单，再按服务上限分批并核对。"""
    import geopandas as gpd
    import pandas as pd
    clean_url = url.split("?")[0].rstrip("/")
    credential_names = sensitive_query_parameter_names(url)
    auth_params = {k: v for k, v in urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)
                   if k in credential_names}

    # 1. 若为服务目录根（/services），自动寻找第一个 FeatureServer
    if clean_url.endswith("/services"):
        try:
            cat = _http_get(clean_url, params=dict(auth_params, f="pjson"), timeout=30).json()
            svcs = cat.get("services", [])
            fs = next((s for s in svcs if s.get("type") == "FeatureServer"), None)
            if fs:
                clean_url = fs.get("url") or f"{clean_url}/{fs.get('name')}/FeatureServer"
        except Exception as exc:
            raise UrlGisError(f"无法解析 ArcGIS 服务目录：{exc}") from exc

    # 2. 自动嗅探图层 ID（避免盲目写死 0 导致失败）
    has_layer_path = bool(re.fullmatch(r"\d+", clean_url.rsplit("/", 1)[-1]))
    if not layer_id and not has_layer_path:
        try:
            fs_meta = _http_get(clean_url, params=dict(auth_params, f="pjson"), timeout=30).json()
            sub_layers = fs_meta.get("layers", [])
            if sub_layers and "id" in sub_layers[0]:
                layer_id = str(sub_layers[0]["id"])
            else:
                raise UrlGisError("服务根未提供可查询图层，请传入具体图层 URL 或 layer_id")
        except Exception as exc:
            raise UrlGisError(f"无法确定 ArcGIS 图层：{exc}") from exc
    elif not layer_id:
        layer_id = clean_url.rsplit("/", 1)[-1]

    if layer_id and not clean_url.endswith(f"/{layer_id}"):
        query_url = f"{clean_url}/{layer_id}/query"
    elif has_layer_path:
        query_url = f"{clean_url}/query"
    else:
        query_url = f"{clean_url}/0/query"

    layer_url = query_url[:-len("/query")]
    try:
        layer_meta = _http_get(layer_url, params=dict(auth_params, f="pjson"), timeout=30).json()
    except Exception as exc:
        raise UrlGisError(f"无法读取 ArcGIS 图层元数据：{exc}") from exc
    if not isinstance(layer_meta, dict):
        raise UrlGisError("ArcGIS 图层元数据结构无效：JSON 根节点必须是对象")
    if layer_meta.get("error"):
        raise UrlGisError(f"ArcGIS 图层元数据错误：{layer_meta['error'].get('message', '未知错误')}")
    oid_field = layer_meta.get("objectIdField") or next(
        (f.get("name") for f in layer_meta.get("fields", []) if f.get("type") == "esriFieldTypeOID"), None
    )
    source_sr = layer_meta.get("sourceSpatialReference") or layer_meta.get("spatialReference") or {}
    source_crs = _arcgis_crs_label(source_sr)
    if not oid_field and mode == "full":
        raise UrlGisError("完整性未知：图层元数据未提供对象 ID 字段，无法稳定排序并核对分页缺失和重复")

    params = {
        "where": where or "1=1",
        "outFields": "*",
        "f": "geojson",
        "resultRecordCount": min(max(int(limit or 1000), 1), max(int(layer_meta.get("maxRecordCount") or 1000), 1)),
        "returnGeometry": "true",
        "outSR": 4326,
    }
    if bbox:
        bbox_tuple = parse_bbox(bbox)
        if bbox_tuple:
            params["geometry"] = f"{bbox_tuple[0]},{bbox_tuple[1]},{bbox_tuple[2]},{bbox_tuple[3]}"
            params["geometryType"] = "esriGeometryEnvelope"
            params["spatialRel"] = "esriSpatialRelIntersects"
            params["inSR"] = 4326

    def query_json(query_params):
        query_params = dict(auth_params, **query_params)
        last_error = None
        for attempt in range(2):
            try:
                response = _http_get(query_url, params=query_params, timeout=30)
                break
            except UrlGisError as exc:
                last_error = exc
                if attempt == 0:
                    if cancel_check and cancel_check():
                        raise UrlGisError("获取已由用户取消")
                    time.sleep(0.2)
        else:
            raise UrlGisError(f"ArcGIS 请求重试耗尽：{last_error}") from last_error
        try:
            payload = response.json()
        except Exception as exc:
            raise UrlGisError(f"ArcGIS 查询返回无效 JSON：{exc}") from exc
        if not isinstance(payload, dict):
            raise UrlGisError("ArcGIS 查询响应结构无效：JSON 根节点必须是对象")
        if payload.get("error"):
            error = payload["error"]
            raise UrlGisError(f"ArcGIS 查询错误：{error.get('message', '未知错误')} {error.get('details', [])}")
        return payload

    def query_features(query_params):
        try:
            page = query_json(dict(query_params, f="geojson"))
            return page.get("features") or [], page
        except UrlGisError as geojson_error:
            error_text = str(geojson_error)
            if not any(marker in error_text for marker in (
                "ArcGIS 查询错误", "查询返回无效 JSON", "ArcGIS 查询响应结构无效",
            )):
                raise
            try:
                page = query_json(dict(query_params, f="json"))
            except UrlGisError:
                raise geojson_error
            converted = []
            try:
                for feature in page.get("features") or []:
                    converted.append({
                        "type": "Feature",
                        "geometry": _arcgis_json_geometry(feature.get("geometry")),
                        "properties": feature.get("attributes") or {},
                    })
            except Exception as exc:
                raise UrlGisError(f"ArcGIS JSON 几何转换失败：{exc}") from exc
            return converted, page

    if mode == "preview":
        features, page = query_features(params)
        gdf = _arcgis_features_to_gdf(features, layer_meta, gpd, pd)
        if len(gdf) > limit:
            gdf = gdf.iloc[:limit].copy()
        audit = {"mode": "preview", "expected_count": None, "expected_count_known": False,
                 "layer_id": str(layer_id),
                 "source_crs": source_crs,
                 "completeness": "not_checked", "completeness_reason": "限量预览不会检查源数据完整性",
                 "checks": [{"name": "preview_limit", "status": "not_checked", "detail": f"预览上限 {limit} 条"}], "warnings": []}
        return gdf, audit

    maximum = max(1, min(int(max_features or 100000), 1000000))
    id_params = dict(params, f="json", returnIdsOnly="true", returnGeometry="false")
    try:
        initial_count = int(query_json(dict(params, f="json", returnCountOnly="true", returnGeometry="false"))["count"])
    except Exception:
        initial_count = None
    try:
        id_result = query_json(id_params)
    except UrlGisError:
        id_result = {}
    ids = id_result.get("objectIds")
    # Some MapServer layers cap returnIdsOnly even when query pagination is available.
    # A stable ID list is not proof of completeness unless it agrees with returnCountOnly.
    if not isinstance(ids, list) or initial_count is None or len(ids) != initial_count:
        ids = None
    if not isinstance(ids, list):
        advanced = layer_meta.get("advancedQueryCapabilities") or {}
        if not advanced.get("supportsPagination") or advanced.get("supportsOrderBy") is False:
            raise UrlGisError("完整性未知：ArcGIS 未提供对象 ID 清单且不支持分页，无法安全核对完整结果")
        if initial_count is None:
            raise UrlGisError("完整性未知：ArcGIS 不提供可信总数，无法确定分页终点")
        expected_count = initial_count
        if expected_count > maximum:
            raise UrlGisError(f"匹配 {expected_count} 条，超过本次资源上限 {maximum}；请缩小范围或过滤条件后重试")
        service_limit = max(1, int(layer_meta.get("maxRecordCount") or 1000))
        page_size = min(service_limit, 500)
        paged_features = []
        seen_ids = set()
        offset = 0
        page_no = 0
        pagination_error = ""
        while offset < expected_count:
            if cancel_check and cancel_check():
                raise UrlGisError("获取已由用户取消")
            page_params = dict(params, f="geojson", resultOffset=offset, resultRecordCount=page_size,
                               orderByFields=f"{oid_field} ASC")
            page_features, page = query_features(page_params)
            if not page_features:
                pagination_error = "分页提前返回空页"
                break
            paged_features.extend(page_features)
            seen_ids.update(str((feature.get("properties") or {}).get(oid_field, "")) for feature in page_features)
            page_no += 1
            offset += len(page_features)
            if progress_callback:
                progress_callback({"phase": "fetching", "completed": min(offset, expected_count),
                                   "total": expected_count, "batch": page_no,
                                   "batches": max(1, (expected_count + page_size - 1) // page_size)})
            if offset < expected_count and not page.get("exceededTransferLimit"):
                pagination_error = "服务标记分页已结束，但返回数少于查询总数"
                break
            if offset > expected_count:
                pagination_error = "分页返回数超过查询总数"
                break
        try:
            after_count = query_json(dict(params, f="json", returnCountOnly="true", returnGeometry="false")).get("count")
        except Exception:
            after_count = None
        unique_ids = len(seen_ids - {""})
        verify_ids = set()
        verify_error = ""
        verify_offset = 0
        while verify_offset < expected_count:
            if cancel_check and cancel_check():
                raise UrlGisError("获取已由用户取消")
            verify_params = dict(params, f="json", outFields=oid_field, returnGeometry="false",
                                 resultOffset=verify_offset, resultRecordCount=page_size,
                                 orderByFields=f"{oid_field} ASC")
            try:
                verify_page = query_json(verify_params)
            except UrlGisError as exc:
                verify_error = str(exc)
                break
            verify_features = verify_page.get("features") or []
            if not verify_features:
                verify_error = "复核对象 ID 分页提前返回空页"
                break
            page_ids = [str((feature.get("attributes") or {}).get(oid_field, "")) for feature in verify_features]
            verify_ids.update(page_ids)
            verify_offset += len(verify_features)
            if verify_offset < expected_count and not verify_page.get("exceededTransferLimit"):
                verify_error = "复核分页标记已结束，但返回数少于查询总数"
                break
            if verify_offset > expected_count:
                verify_error = "复核分页返回数超过查询总数"
                break
        ids_stable = verify_ids == (seen_ids - {""}) and len(verify_ids) == expected_count
        complete = (not pagination_error and not verify_error and len(paged_features) == expected_count
                    and unique_ids == expected_count and ids_stable
                    and after_count is not None and int(after_count) == expected_count)
        audit = {"mode": "full", "expected_count": expected_count, "expected_count_known": True,
                 "layer_id": str(layer_id),
                 "source_crs": source_crs,
                 "completeness": "complete" if complete else "partial" if after_count is not None else "unknown",
                 "completeness_reason": "稳定排序分页条数、对象 ID 复核和前后总数一致" if complete else f"{pagination_error or verify_error or '分页条数、对象 ID 或前后源记录数不一致/无法复查'}；获取 {len(paged_features)}/{expected_count} 条",
                 "checks": [{"name": "stable_pagination", "status": "passed" if complete else "failed" if after_count is not None else "unknown",
                             "detail": f"获取 {len(paged_features)} 条，复核唯一 ID {len(verify_ids)} 个；查询总数 {expected_count}/{after_count}"}],
                 "warnings": ["偏移分页不是事务快照；源属性可能在获取期间变化"]}
        return _arcgis_features_to_gdf(paged_features, layer_meta, gpd, pd), audit
    if len(ids) > maximum:
        raise UrlGisError(f"匹配 {len(ids)} 条，超过本次资源上限 {maximum}；请缩小范围或过滤条件后重试")
    if len(set(map(str, ids))) != len(ids):
        raise UrlGisError("ArcGIS 对象 ID 清单含重复项，无法保证完整获取")
    expected_count = len(ids)
    if progress_callback:
        progress_callback({"phase": "fetching", "completed": 0, "total": expected_count, "batch": 0})
    service_limit = max(1, int(layer_meta.get("maxRecordCount") or 1000))
    batch_size = min(service_limit, 500)
    features = []
    received_ids = []
    fetch_error = ""
    total_batches = max(1, (expected_count + batch_size - 1) // batch_size)
    for batch_no, start in enumerate(range(0, expected_count, batch_size), start=1):
        if cancel_check and cancel_check():
            raise UrlGisError("获取已由用户取消")
        batch_ids = ids[start:start + batch_size]
        batch_params = dict(params, f="geojson", objectIds=",".join(map(str, batch_ids)))
        try:
            batch_features, payload = query_features(batch_params)
        except UrlGisError as exc:
            fetch_error = str(exc)
            break
        if payload.get("exceededTransferLimit"):
            fetch_error = "ArcGIS 返回 exceededTransferLimit=true"
            break
        features.extend(batch_features)
        received_ids.extend(str((feature.get("properties") or {}).get(oid_field, "")) for feature in batch_features)
        if progress_callback:
            progress_callback({"phase": "fetching", "completed": min(start + len(batch_ids), expected_count),
                               "total": expected_count, "batch": batch_no, "batches": total_batches})
    duplicates = len(received_ids) - len(set(received_ids))
    missing = sorted(set(map(str, ids)) - set(received_ids))
    checks = [{"name": "object_ids", "status": "passed", "detail": f"源清单 {expected_count} 个唯一 ID"}]
    if duplicates:
        checks.append({"name": "duplicate_ids", "status": "failed", "detail": f"收到 {duplicates} 个重复要素"})
    else:
        checks.append({"name": "duplicate_ids", "status": "passed", "detail": "未发现重复对象 ID"})
    if missing:
        checks.append({"name": "missing_ids", "status": "failed", "detail": f"缺失 {len(missing)} 个对象 ID"})
    else:
        checks.append({"name": "missing_ids", "status": "passed", "detail": "对象 ID 清单全部返回"})
    stable_ids = True
    after_ids = None
    try:
        after_ids = query_json(id_params).get("objectIds")
        stable_ids = isinstance(after_ids, list) and set(map(str, after_ids)) == set(map(str, ids))
    except Exception:
        stable_ids = False
    try:
        after_count = int(query_json(dict(params, f="json", returnCountOnly="true", returnGeometry="false"))["count"])
    except Exception:
        after_count = None
    count_stable = after_count == initial_count == expected_count
    checks.append({"name": "source_count", "status": "passed" if count_stable else "unknown" if after_count is None or initial_count is None else "failed",
                   "detail": f"获取前总数 {initial_count}，获取后总数 {after_count}，ID 清单 {expected_count}"})
    checks.append({"name": "source_ids_stable", "status": "passed" if stable_ids else "unknown" if after_ids is None else "failed",
                   "detail": "获取前后对象 ID 清单一致" if stable_ids else "获取期间对象 ID 清单变化或无法复查；属性值仍不是源数据快照"})
    complete = not duplicates and not missing and len(features) == expected_count and stable_ids and count_stable and not fetch_error
    completeness = "complete" if complete else "unknown" if (after_ids is None or after_count is None or initial_count is None) and not fetch_error else "partial"
    audit = {"mode": "full", "expected_count": expected_count, "expected_count_known": True,
             "layer_id": str(layer_id),
             "source_crs": source_crs,
             "completeness": completeness,
             "completeness_reason": "对象 ID 清单前后稳定且与返回结果逐项一致" if complete else f"预期 {expected_count} 条，实际 {len(features)} 条；发现重复 {duplicates} 条、缺失 {len(missing)} 条" if stable_ids else "源 ID 清单变化或无法复查，无法确认获取期间数据一致性",
             "checks": checks, "warnings": ["ID 清单稳定不代表属性值在获取期间未变化；ArcGIS REST 查询不是源数据快照"]}
    if fetch_error:
        audit["completeness_reason"] = f"获取中断：{fetch_error}；目前返回 {len(features)}/{expected_count} 条"
        audit["warnings"].append("部分已获取数据已保留为文件")
    if not complete:
        audit["warnings"].append("导出结果不完整；请查看报告并重试")
    gdf = _arcgis_features_to_gdf(features, layer_meta, gpd, pd)
    return gdf, audit


def _arcgis_features_to_gdf(features, layer_meta, gpd, pd):
    if features:
        return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    columns = [field.get("name") for field in layer_meta.get("fields", []) if field.get("name")]
    empty = pd.DataFrame({column: pd.Series(dtype="object") for column in columns})
    empty["geometry"] = gpd.GeoSeries([], crs="EPSG:4326")
    return gpd.GeoDataFrame(empty, geometry="geometry", crs="EPSG:4326")


def _arcgis_json_geometry(geometry):
    """Convert Esri JSON geometry to GeoJSON while retaining multipart rings and holes."""
    if not geometry:
        return None
    from shapely.geometry import Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon, box, mapping

    if "x" in geometry and "y" in geometry:
        coords = [geometry["x"], geometry["y"]]
        if geometry.get("z") is not None:
            coords.append(geometry["z"])
        return mapping(Point(coords))
    if "points" in geometry:
        return mapping(MultiPoint(geometry.get("points") or []))
    if "paths" in geometry:
        paths = geometry.get("paths") or []
        return mapping(LineString(paths[0])) if len(paths) == 1 else mapping(MultiLineString(paths))
    if "rings" in geometry:
        rings = geometry.get("rings") or []
        ring_polygons = [Polygon(ring) for ring in rings]
        order = sorted(range(len(rings)), key=lambda i: ring_polygons[i].area, reverse=True)
        parents = {}
        depths = {}
        for index in order:
            point = ring_polygons[index].representative_point()
            containers = [parent for parent in order if parent in depths
                          and ring_polygons[parent].area > ring_polygons[index].area
                          and ring_polygons[parent].contains(point)]
            parent = min(containers, key=lambda i: ring_polygons[i].area) if containers else None
            parents[index] = parent
            depths[index] = depths[parent] + 1 if parent is not None else 0
        polygons = []
        for index in order:
            if depths[index] % 2:
                continue
            holes = [rings[child] for child in order
                     if parents[child] == index and depths[child] == depths[index] + 1]
            polygons.append(Polygon(rings[index], holes))
        return mapping(polygons[0]) if len(polygons) == 1 else mapping(MultiPolygon(polygons))
    if all(key in geometry for key in ("xmin", "ymin", "xmax", "ymax")):
        return mapping(box(geometry["xmin"], geometry["ymin"], geometry["xmax"], geometry["ymax"]))
    if any(key in geometry for key in ("curvePaths", "curveRings")):
        raise UrlGisError("服务返回曲线几何；当前 GeoJSON 导出不能无损表达，已停止转换")
    raise UrlGisError("ArcGIS JSON 几何类型无法识别，未导出以避免静默丢失")


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
