"""
百度地图 AOI 轮廓提取服务
直接从老代码移植过来的核心逻辑（已验证可跑）
"""

import json, os, hashlib, time
from typing import Optional
from playwright.sync_api import sync_playwright
import transbigdata
from shapely.geometry import Polygon
import geopandas as gpd

# ===== 缓存 =====
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "aoi")
def _cache_path(prefix, key):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    h = hashlib.md5(key.encode('utf-8')).hexdigest()[:16]
    return os.path.join(_CACHE_DIR, f"{prefix}_{h}.json")

def _read_cache(path):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
    except: pass
    return None

def _write_cache(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False)
    except: pass

# ===== 坐标解析 =====
def parse_geo_to_points(geo_str):
    parts = geo_str.split("|")
    if len(parts) < 3: raise ValueError("geo 格式异常")
    coords_str = parts[2]
    if coords_str.startswith("a"): coords_str = coords_str[1:]
    tokens = coords_str.split(",")
    points = []
    for i in range(0, len(tokens)-1, 2):
        try: points.append((float(tokens[i]), float(tokens[i+1])))
        except: pass
    return points

def bd09mc_to_wgs84(points):
    result = []
    for x, y in points:
        bd09_lon, bd09_lat = transbigdata.bd09mctobd09(x, y)
        gcj02_lon, gcj02_lat = transbigdata.bd09togcj02(bd09_lon, bd09_lat)
        wgs84_lon, wgs84_lat = transbigdata.gcj02towgs84(gcj02_lon, gcj02_lat)
        result.append((round(wgs84_lon,6), round(wgs84_lat,6)))
    return result

def points_to_geojson(points, name):
    if len(points) < 3: return None
    gdf = gpd.GeoDataFrame({"name":[name]}, geometry=[Polygon(points)], crs="EPSG:4326")
    return json.loads(gdf.to_json())

# ===== 响应解析 =====
def extract_suggestions_from_search(data):
    suggestions = []
    try:
        content = data.get("content", [])
        if isinstance(content, dict): content = [content]
        for item in content:
            if not isinstance(item, dict): continue
            name = item.get("name","") or item.get("std_tag","") or ""
            uid = item.get("uid","")
            addr = item.get("addr","") or item.get("address","") or ""
            if name: suggestions.append({"name":name,"address":addr,"uid":uid})
    except: pass
    return suggestions

def extract_geo_from_detail(data):
    try:
        content = data.get("content", {})
        if isinstance(content, list): content = content[0] if content else {}
        geo = content.get("ext",{}).get("detail_info",{}).get("guoke_geo",{}).get("geo","")
        return geo if geo else None
    except: return None

# ===== 浏览器（跟老代码完全一致）=====
def _launch_browser(p, headless=True):
    opts = dict(headless=headless, args=["--no-sandbox","--disable-setuid-sandbox","--disable-blink-features=AutomationControlled","--disable-dev-shm-usage","--disable-gpu","--disable-software-rasterizer"])
    try: return p.chromium.launch(channel="chrome", **opts)
    except: return p.chromium.launch(**opts)

def _create_context(browser):
    return browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width":1920,"height":1080}, locale="zh-CN")

def _add_script(page):
    page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false})")

# ===== 搜索 =====
def search_suggestions(query):
    if not query or not query.strip(): return []
    q = query.strip()

    # 缓存
    cp = _cache_path("bd_search", q)
    cached = _read_cache(cp)
    if cached: return cached

    result = _do_search(q)
    if result: _write_cache(cp, result)
    return result

def _do_search(query):
    result_suggestions = []
    try:
        with sync_playwright() as p:
            browser = _launch_browser(p)
            context = _create_context(browser)
            page = context.new_page()
            _add_script(page)

            search_data = []
            def on_resp(response):
                if "qt=s" in response.url and not search_data:
                    try:
                        data = response.json()
                        extracted = extract_suggestions_from_search(data)
                        if extracted: search_data.extend(extracted)
                    except: pass
            page.on("response", on_resp)

            page.goto("https://map.baidu.com/", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)

            sb = page.locator("#sole-input")
            sb.wait_for(state="visible", timeout=8000)
            sb.click(); page.wait_for_timeout(300)
            sb.fill(query); page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            page.wait_for_timeout(5000)

            # 兜底点击
            if not search_data:
                try:
                    link = page.locator("a").filter(has_text=query[:2]).first
                    link.wait_for(state="visible", timeout=3000)
                    link.click(); page.wait_for_timeout(3000)
                except: pass

            result_suggestions = search_data
            browser.close()
    except: pass

    seen = set()
    unique = []
    for s in result_suggestions:
        k = f"{s['name']}|{s['uid']}"
        if k not in seen and s['name']: seen.add(k); unique.append(s)
    return unique[:20]

# ===== 提取边界 =====
def extract_boundary(uid, place_name, headless=True):
    if not uid: return None

    cp = _cache_path("bd_extract", uid)
    cached = _read_cache(cp)
    if cached: return cached

    result_geo = None

    try:
        with sync_playwright() as p:
            browser = _launch_browser(p, headless=headless)
            context = _create_context(browser)
            page = context.new_page()
            _add_script(page)

            geo_result = [None]
            def on_resp(response):
                if geo_result[0]: return
                if "detailConInfo" in response.url:
                    try:
                        data = response.json()
                        geo = extract_geo_from_detail(data)
                        if geo: geo_result[0] = geo
                    except: pass
            page.on("response", on_resp)

            page.goto("https://map.baidu.com/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)

            # 搜索
            sb = page.locator("#sole-input")
            sb.wait_for(state="visible", timeout=8000)
            sb.click(); page.wait_for_timeout(300)
            sb.fill(place_name); page.wait_for_timeout(500)
            page.keyboard.press("Enter"); page.wait_for_timeout(4000)

            # context request
            api_url = f'https://map.baidu.com/?uid={uid}&ugc_type=3&ugc_ver=1&qt=detailConInfo&device_ratio=1&compat=1'
            if not geo_result[0]:
                for _ in range(2):
                    try:
                        resp = context.request.get(api_url, timeout=15000)
                        if resp.ok:
                            geo = extract_geo_from_detail(resp.json())
                            if geo: geo_result[0] = geo; break
                    except: page.wait_for_timeout(1000)

            # fetch 兜底
            if not geo_result[0]:
                for _ in range(3):
                    js = page.evaluate(f"fetch('{api_url}').then(r=>r.text()).catch(e=>'FETCH_ERROR')")
                    if not js.startswith('FETCH_ERROR'):
                        try:
                            geo = extract_geo_from_detail(json.loads(js))
                            if geo: geo_result[0] = geo; break
                        except: pass
                    page.wait_for_timeout(1500)

            # 点击结果触发
            if not geo_result[0]:
                try:
                    link = page.locator("a").filter(has_text=place_name[:2]).first
                    link.wait_for(state="visible", timeout=3000)
                    link.click(); page.wait_for_timeout(4000)
                    for _ in range(15):
                        if geo_result[0]: break
                        page.wait_for_timeout(500)
                except: pass

            result_geo = geo_result[0]
            browser.close()
    except: pass

    if not result_geo: return None

    try:
        points = parse_geo_to_points(result_geo)
        if len(points) < 3: return None
        wgs84 = bd09mc_to_wgs84(points)
        geojson = points_to_geojson(wgs84, place_name)
        if geojson: _write_cache(cp, geojson)
        return geojson
    except: return None
