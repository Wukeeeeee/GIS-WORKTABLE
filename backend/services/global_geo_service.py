# -*- coding: utf-8 -*-
"""全球开放地理数据与维基实体检索服务 (Global Geospatial & Wikidata Service)

直连国际顶级开放地理基础设施（免 Key、全球覆盖、WGS-84 标准）：
1. Wikidata / Wikipedia Spatial API: 全球地理实体、山脉、水系、行政区、地标知识图谱与精确坐标
2. OpenStreetMap Nominatim: 全球地名正/反向编码与行政区划边界多边形（Polygon GeoJSON）秒级提取
3. OpenStreetMap Overpass API: 区域路网、建筑轮廓、水系与兴趣点矢量数据直接抽取
"""

import os
import json
import urllib.parse
from typing import Dict, Any, List, Optional
import requests

from backend.services.cloud_native import get_effective_proxies, parse_bbox


def _get_headers() -> dict:
    return {
        "User-Agent": "GIS-WorkTable/2.0 (Global Geospatial AI Platform; contact@gis-worktable.io)",
        "Accept": "application/json",
    }


def _http_get(url: str, params: dict = None, timeout: int = 10) -> requests.Response:
    proxies = get_effective_proxies()
    headers = _get_headers()
    return requests.get(url, params=params, headers=headers, proxies=proxies, timeout=timeout)


# ============================================================
# 1. Wikidata / Wikipedia 地理实体与知识图谱
# ============================================================

def search_wikidata_entities(query: str, lang: str = "zh", limit: int = 5) -> List[Dict[str, Any]]:
    """检索 Wikidata 地理实体，获取多语言名称、实体简介、坐标及维基百科摘要。"""
    q = str(query).strip()
    if not q:
        return []

    url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbsearchentities",
        "search": q,
        "language": lang,
        "format": "json",
        "limit": limit,
        "uselang": lang,
    }

    try:
        resp = _http_get(url, params=params)
        data = resp.json()
        search_results = data.get("search", [])
        if not search_results:
            # Fallback to English search
            if lang != "en":
                params["language"] = "en"
                params["uselang"] = "en"
                resp = _http_get(url, params=params)
                search_results = resp.json().get("search", [])
    except Exception as e:
        return [{"error": f"Wikidata 查询失败: {e}"}]

    entities = []
    for item in search_results[:limit]:
        qid = item.get("id")
        label = item.get("label") or q
        description = item.get("description", "")
        concept_uri = item.get("concepturi", f"https://www.wikidata.org/wiki/{qid}")

        # 获取实体坐标与维基详情
        coord, wiki_extract, wiki_url = _fetch_wikidata_entity_details(qid, lang)

        entities.append({
            "qid": qid,
            "name": label,
            "description": description,
            "coordinates": coord,  # [lng, lat]
            "wikipedia_summary": wiki_extract,
            "wikidata_url": concept_uri,
            "wikipedia_url": wiki_url,
        })

    return entities


def _fetch_wikidata_entity_details(qid: str, lang: str = "zh") -> tuple:
    """获取单个实体的 P625 坐标与关联 Wikipedia 条目摘要"""
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    coord = None
    wiki_title = None
    wiki_url = None
    wiki_extract = ""

    try:
        resp = _http_get(url, timeout=6)
        entities = resp.json().get("entities", {})
        entity = entities.get(qid, {})
        claims = entity.get("claims", {})

        # P625: Coordinate location
        p625 = claims.get("P625", [])
        if p625:
            val = p625[0].get("mainsnak", {}).get("datavalue", {}).get("value", {})
            lat = val.get("latitude")
            lng = val.get("longitude")
            if lat is not None and lng is not None:
                coord = [round(float(lng), 6), round(float(lat), 6)]

        # Sitelinks
        sitelinks = entity.get("sitelinks", {})
        site_key = f"{lang}wiki"
        if site_key not in sitelinks and "enwiki" in sitelinks:
            site_key = "enwiki"
            lang = "en"

        if site_key in sitelinks:
            wiki_title = sitelinks[site_key].get("title")
            wiki_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(wiki_title)}"
            # 抓取摘要
            wiki_extract = _fetch_wikipedia_summary(wiki_title, lang)

    except Exception:
        pass

    return coord, wiki_extract, wiki_url


def _fetch_wikipedia_summary(title: str, lang: str = "zh") -> str:
    """获取维基百科条目首段文本摘要"""
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
    try:
        resp = _http_get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("extract", "")
    except Exception:
        pass
    return ""


# ============================================================
# 2. OpenStreetMap Nominatim 全球正/反向编码与多边形边界
# ============================================================

def search_osm_nominatim(query: str, fetch_polygon: bool = True, limit: int = 3) -> List[Dict[str, Any]]:
    """通过 OSM Nominatim 检索全球地名，返回精准坐标、BBox 范围与完整行政区划边界多边形 (GeoJSON)"""
    q = str(query).strip()
    if not q:
        return []

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": q,
        "format": "json",
        "polygon_geojson": 1 if fetch_polygon else 0,
        "addressdetails": 1,
        "limit": limit,
    }

    try:
        resp = _http_get(url, params=params, timeout=8)
        items = resp.json()
    except Exception as e:
        return [{"error": f"OSM Nominatim 查询失败: {e}"}]

    results = []
    for item in items:
        lat = float(item.get("lat", 0))
        lng = float(item.get("lon", 0))
        bbox_raw = item.get("boundingbox", [])  # [minlat, maxlat, minlon, maxlon]
        bbox = None
        if len(bbox_raw) == 4:
            bbox = [float(bbox_raw[2]), float(bbox_raw[0]), float(bbox_raw[3]), float(bbox_raw[1])]  # [minx, miny, maxx, maxy]

        geojson = item.get("geojson")
        display_name = item.get("display_name", "")
        category = item.get("category") or item.get("class", "")
        osm_type = item.get("osm_type", "")
        place_rank = item.get("place_rank", 0)

        results.append({
            "name": display_name.split(",")[0],
            "display_name": display_name,
            "coordinates": [lng, lat],
            "bbox": bbox,
            "category": category,
            "osm_type": osm_type,
            "place_rank": place_rank,
            "has_polygon": bool(geojson and geojson.get("type") in ("Polygon", "MultiPolygon")),
            "geojson": geojson if fetch_polygon else None,
        })

    return results


# ============================================================
# 3. OpenStreetMap Overpass API 矢量要素提取
# ============================================================

def query_osm_overpass(query_type: str, bbox: str, limit: int = 300) -> Dict[str, Any]:
    """通过 Overpass API 按 BBox 空间范围抓取真实 OSM 矢量数据（道路网、建筑物、水系、绿地等）并转为 GeoJSON"""
    bbox_tuple = parse_bbox(bbox)
    if not bbox_tuple:
        raise ValueError("Overpass 查询必须提供有效的 bbox: 'minx,miny,maxx,maxy'")

    minx, miny, maxx, maxy = bbox_tuple
    # Overpass bbox 格式为 (minlat, minlon, maxlat, maxlon)
    op_bbox = f"{miny},{minx},{maxy},{maxx}"

    # 构建 Overpass QL
    qt = query_type.lower().strip()
    if qt in ("roads", "highway", "道路", "路网"):
        filter_clause = f'way["highway"]({op_bbox});'
    elif qt in ("buildings", "building", "建筑", "房屋"):
        filter_clause = f'way["building"]({op_bbox});'
    elif qt in ("water", "waterway", "水系", "河流"):
        filter_clause = f'way["natural"="water"]({op_bbox}); way["waterway"]({op_bbox});'
    elif qt in ("amenity", "poi", "设施", "兴趣点"):
        filter_clause = f'node["amenity"]({op_bbox});'
    else:
        filter_clause = f'way["highway"]({op_bbox}); way["building"]({op_bbox});'

    ql = f"""
    [out:json][timeout:15];
    (
      {filter_clause}
    );
    out body {limit};
    >;
    out skel qt;
    """

    url = "https://overpass-api.de/api/interpreter"
    resp = _http_get(url, params={"data": ql}, timeout=15)
    data = resp.json()
    elements = data.get("elements", [])

    # 将 Overpass 元素转为简易 GeoJSON
    nodes_map = {el["id"]: (el["lon"], el["lat"]) for el in elements if el.get("type") == "node"}
    features = []

    for el in elements:
        props = el.get("tags", {})
        if not props:
            continue
        props["osm_id"] = el.get("id")

        if el.get("type") == "node" and "lon" in el and "lat" in el:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                "properties": props,
            })
        elif el.get("type") == "way" and "nodes" in el:
            way_nodes = [nodes_map.get(nid) for nid in el["nodes"] if nid in nodes_map]
            if len(way_nodes) >= 2:
                # 闭合则作为 Polygon，否则 LineString
                is_closed = way_nodes[0] == way_nodes[-1] and len(way_nodes) >= 4 and ("building" in props or "natural" in props or "landuse" in props)
                gtype = "Polygon" if is_closed else "LineString"
                coords = [way_nodes] if is_closed else way_nodes
                features.append({
                    "type": "Feature",
                    "geometry": {"type": gtype, "coordinates": coords},
                    "properties": props,
                })

    geojson = {"type": "FeatureCollection", "features": features}

    return {
        "ok": True,
        "query_type": query_type,
        "bbox": [minx, miny, maxx, maxy],
        "feature_count": len(features),
        "geojson": geojson,
    }
