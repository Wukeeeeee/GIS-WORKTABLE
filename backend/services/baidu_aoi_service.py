"""
在线空间 AOI 轮廓边界提取服务
"""

import json
import os
import hashlib
import time
from typing import Optional, List, Dict, Any
from playwright.sync_api import sync_playwright
from shapely.geometry import Polygon
import geopandas as gpd

from backend.services.geo_coords import bd09mc_to_wgs84

# ===== 缓存 =====
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "aoi")


def _cache_path(prefix, key):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    h = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    return os.path.join(_CACHE_DIR, f"{prefix}_{h}.json")


def _read_cache(path):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _write_cache(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


# ===== 坐标解析 =====
def parse_geo_to_points(geo_str: str):
    if not geo_str or not isinstance(geo_str, str):
        return []
    import re
    parts = geo_str.split("|")
    target_str = parts[2] if len(parts) >= 3 else geo_str

    points = []
    rings = target_str.split(";")
    for ring in rings:
        ring = ring.strip()
        if not ring:
            continue
        if "-" in ring:
            ring = ring.split("-", 1)[1]
        elif ring and ring[0].isalpha():
            ring = ring[1:]

        tokens = re.findall(r"\d+(?:\.\d+)?", ring)
        for i in range(0, len(tokens) - 1, 2):
            try:
                points.append((float(tokens[i]), float(tokens[i + 1])))
            except Exception:
                continue
    return points


def points_to_geojson(points, name):
    if len(points) < 3:
        return None
    pts = list(points)
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    gdf = gpd.GeoDataFrame({"name": [name]}, geometry=[Polygon(pts)], crs="EPSG:4326")
    return json.loads(gdf.to_json())


# ===== 响应解析 =====
def extract_suggestions_from_search(data):
    suggestions = []
    try:
        content = data.get("content", [])
        if isinstance(content, dict):
            content = [content]
        for item in content:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "") or item.get("std_tag", "") or ""
            uid = item.get("uid", "")
            addr = item.get("addr", "") or item.get("address", "") or ""
            if name:
                suggestions.append({"name": name, "address": addr, "uid": uid})
    except Exception:
        pass
    return suggestions


def extract_geo_from_detail(data):
    if not isinstance(data, dict):
        return None

    # 常见层级路径
    try:
        content = data.get("content", {})
        if isinstance(content, list):
            content = content[0] if content else {}
        if isinstance(content, dict):
            ext = content.get("ext", {})
            if isinstance(ext, dict):
                dinfo = ext.get("detail_info", {})
                if isinstance(dinfo, dict):
                    ggeo = dinfo.get("guoke_geo", {})
                    if isinstance(ggeo, dict) and ggeo.get("geo"):
                        return str(ggeo["geo"])
                    if dinfo.get("geo"):
                        return str(dinfo["geo"])
            if content.get("geo"):
                return str(content["geo"])
    except Exception:
        pass

    # 递归深层匹配
    def _search(node):
        if isinstance(node, dict):
            if "geo" in node and isinstance(node["geo"], str) and "|" in node["geo"] and len(node["geo"]) > 20:
                return node["geo"]
            if "guoke_geo" in node and isinstance(node["guoke_geo"], dict):
                g = node["guoke_geo"].get("geo")
                if isinstance(g, str) and "|" in g:
                    return g
            for v in node.values():
                res = _search(v)
                if res:
                    return res
        elif isinstance(node, list):
            for item in node:
                res = _search(item)
                if res:
                    return res
        return None

    return _search(data)


# ===== 浏览器无头模式 =====
def _launch_browser(p, headless=True):
    opts = dict(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-software-rasterizer",
        ],
    )
    try:
        return p.chromium.launch(channel="chrome", **opts)
    except Exception:
        return p.chromium.launch(**opts)


def _create_context(browser):
    return browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )


def _add_script(page):
    page.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>false})"
    )


def fetch_fast_suggestions(query: str) -> List[Dict[str, Any]]:
    """快速从在线空间数据联想服务获取候选地点 (毫秒级响应)"""
    import requests
    import urllib.parse
    q = (query or "").strip()
    if not q:
        return []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://map.baidu.com/"
        }
        url = f"https://map.baidu.com/su?wd={urllib.parse.quote(q)}&cid=1&type=0"
        resp = requests.get(url, headers=headers, timeout=4)
        resp.encoding = "utf-8"
        text = resp.text.strip()
        if "(" in text and text.endswith(")"):
            text = text[text.find("(") + 1 : text.rfind(")")]
        data = json.loads(text)
        sugs = data.get("s", [])
        candidates = []
        for s in sugs:
            parts = s.split("$")
            if len(parts) >= 4:
                city = parts[0]
                district = parts[1]
                name = parts[3]
                addr = f"{city} {district}".strip()
                if name:
                    candidates.append({"name": name, "address": addr, "uid": ""})
        return candidates
    except Exception:
        return []


# ===== 搜索建议 =====
def search_suggestions(query):
    if not query or not query.strip():
        return []
    q = query.strip()

    cp = _cache_path("aoi_search", q)
    cached = _read_cache(cp)
    if cached:
        return cached

    result = _do_search(q)
    if result:
        _write_cache(cp, result)
    return result


def _do_search(query):
    result_suggestions = []

    # 1. 优先调用快速联想服务 (解决别名/火车站/机场/学校等特殊地名)
    fast_sugs = fetch_fast_suggestions(query)
    if fast_sugs:
        result_suggestions.extend(fast_sugs)

    # 2. 调用浏览器深入拦截精确 UID
    try:
        with sync_playwright() as p:
            browser = _launch_browser(p)
            context = _create_context(browser)
            page = context.new_page()
            _add_script(page)

            search_data = []

            def on_resp(response):
                if ("qt=s" in response.url or "qt=con" in response.url) and not search_data:
                    try:
                        data = response.json()
                        extracted = extract_suggestions_from_search(data)
                        if extracted:
                            search_data.extend(extracted)
                    except Exception:
                        pass

            page.on("response", on_resp)
            page.goto("https://map.baidu.com/", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(800)

            sb = page.locator("#sole-input")
            sb.wait_for(state="visible", timeout=8000)
            sb.click()
            page.wait_for_timeout(150)
            sb.fill(query)
            page.wait_for_timeout(200)

            search_btn = page.locator("#search-button")
            if search_btn.is_visible():
                search_btn.click()
            else:
                page.keyboard.press("Enter")
            page.wait_for_timeout(3000)

            if search_data:
                result_suggestions.extend(search_data)

            browser.close()
    except Exception:
        pass

    seen = set()
    unique = []
    # 有 UID 的排在前面
    result_suggestions.sort(key=lambda x: (1 if x.get("uid") else 0), reverse=True)
    for s in result_suggestions:
        k = s["name"]
        if k not in seen and s["name"]:
            seen.add(k)
            unique.append(s)
    return unique[:20]


# ===== 提取边界 =====
def extract_boundary(uid, place_name, headless=True):
    if not uid:
        return None

    cp = _cache_path("aoi_extract", uid)
    cached = _read_cache(cp)
    if cached:
        return cached

    result_geo = None

    try:
        with sync_playwright() as p:
            browser = _launch_browser(p, headless=headless)
            context = _create_context(browser)
            page = context.new_page()
            _add_script(page)

            geo_result = [None]

            def on_resp(response):
                if geo_result[0]:
                    return
                if "detailConInfo" in response.url or "qt=ext" in response.url or "qt=inf" in response.url:
                    try:
                        data = response.json()
                        geo = extract_geo_from_detail(data)
                        if geo:
                            geo_result[0] = geo
                    except Exception:
                        pass

            page.on("response", on_resp)
            page.goto("https://map.baidu.com/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1000)

            # 搜索
            sb = page.locator("#sole-input")
            sb.wait_for(state="visible", timeout=8000)
            sb.click()
            page.wait_for_timeout(200)
            sb.fill(place_name)
            page.wait_for_timeout(300)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3500)

            api_url = f"https://map.baidu.com/?uid={uid}&ugc_type=3&ugc_ver=1&qt=detailConInfo&device_ratio=1&compat=1"

            # 方式 A: context request
            if not geo_result[0]:
                for _ in range(2):
                    try:
                        resp = context.request.get(api_url, timeout=12000)
                        if resp.ok:
                            geo = extract_geo_from_detail(resp.json())
                            if geo:
                                geo_result[0] = geo
                                break
                    except Exception:
                        page.wait_for_timeout(800)

            # 方式 B: fetch 兜底
            if not geo_result[0]:
                for _ in range(2):
                    js = page.evaluate(f"fetch('{api_url}').then(r=>r.text()).catch(e=>'FETCH_ERROR')")
                    if js and not js.startswith("FETCH_ERROR"):
                        try:
                            geo = extract_geo_from_detail(json.loads(js))
                            if geo:
                                geo_result[0] = geo
                                break
                        except Exception:
                            pass
                    page.wait_for_timeout(1000)

            # 方式 C: 点击结果触发
            if not geo_result[0]:
                try:
                    link = page.locator("a").filter(has_text=place_name[:2]).first
                    if link.is_visible():
                        link.click()
                        page.wait_for_timeout(3000)
                except Exception:
                    pass

            result_geo = geo_result[0]
            browser.close()
    except Exception:
        pass

    if not result_geo:
        return None

    try:
        points = parse_geo_to_points(result_geo)
        if len(points) < 3:
            return None
        wgs84 = bd09mc_to_wgs84(points)
        geojson = points_to_geojson(wgs84, place_name)
        if geojson:
            _write_cache(cp, geojson)
        return geojson
    except Exception:
        return None
