"""
高德地图 AOI 轮廓提取服务
从高德地图（ditu.amap.com）搜索地点、获取建筑/地块轮廓，转换到 WGS84 坐标系

功能:
  - search_suggestions(query): 搜索高德地图，返回候选地点列表 [{name, address, id}]
  - extract_boundary(poi_id, place_name): 根据 POI ID 提取建筑轮廓，返回 GeoJSON

坐标系转换链: GCJ02 (高德火星) → WGS84（标准全球坐标）

反反爬措施:
  - 随机 User-Agent 池（10+ 真实浏览器 UA）
  - 随机视口尺寸
  - 随机操作延时（避免固定间隔被检测）
  - 多重浏览器指纹伪装
  - Cookie 预热（先浏览首页再搜索）
  - 请求重试 + 不同指纹兜底
"""

import json
import random
import time
import hashlib
import os
import concurrent.futures
from typing import Optional

from playwright.sync_api import sync_playwright
from shapely.geometry import Polygon
import geopandas as gpd

# ===== AOI 缓存（同个地点第二次秒出）=====
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "aoi")

def _ensure_cache_dir():
    os.makedirs(_CACHE_DIR, exist_ok=True)

def _hash_key(key: str) -> str:
    return hashlib.md5(key.encode('utf-8')).hexdigest()[:16]

def _write_cache(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


# ============================================================
# 反反爬：随机指纹池
# ============================================================

_USER_AGENTS = [
    # Chrome 120-131 Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720},
    {"width": 1920, "height": 1200},
    {"width": 1600, "height": 900},
]

_LOCALES = ["zh-CN", "zh", "zh-cn,zh;q=0.9"]

_PLATFORMS = ["Win32", "Win64"]


def _random_choice(pool):
    return pool[random.randint(0, len(pool) - 1)]


def _random_delay(min_s=0.8, max_s=3.0):
    """随机延时，避免固定间隔被检测"""
    time.sleep(random.uniform(min_s, max_s))


def _build_fingerprint():
    """生成随机浏览器指纹配置"""
    return {
        "user_agent": _random_choice(_USER_AGENTS),
        "viewport": _random_choice(_VIEWPORTS),
        "locale": _random_choice(_LOCALES),
        "platform": _random_choice(_PLATFORMS),
    }


# ============================================================
# 反反爬：浏览器初始化
# ============================================================

def _build_launch_opts(headless=True):
    return dict(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-webgl",
            "--disable-features=IsolateOrigins,site-per-process",
            "--headless=new",
        ],
    )


def _launch_browser(p, headless=True):
    """尝试用系统 Chrome，没有就 fallback 到自带的 Chromium"""
    opts = _build_launch_opts(headless=headless)
    try:
        return p.chromium.launch(channel="chrome", **opts)
    except Exception:
        return p.chromium.launch(**opts)


def _create_context(browser, fp=None):
    """创建带随机指纹的浏览器上下文"""
    if fp is None:
        fp = _build_fingerprint()
    return browser.new_context(
        user_agent=fp["user_agent"],
        viewport=fp["viewport"],
        locale=fp["locale"],
        timezone_id="Asia/Shanghai",
        # 额外指纹伪装
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cache-Control": "max-age=0",
        },
        permissions=["geolocation"],
        device_scale_factor=random.choice([1, 1.25, 1.5, 2]),
        has_touch=False,
        color_scheme="light",
    )


def _add_anti_detect_scripts(page):
    """注入多重反检测脚本"""
    page.add_init_script("""
        // 覆盖 webdriver 属性
        Object.defineProperty(navigator, 'webdriver', { get: () => false });

        // 覆盖 plugins 长度（反检测）
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5].map(() => ({ name: 'Chrome PDF Plugin' })),
        });

        // 覆盖 languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en'],
        });

        // 覆盖 chrome 对象
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {},
        };

        // 覆盖 permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (params) => (
            params.name === 'notifications'
                ? Promise.resolve({ state: 'denied' })
                : originalQuery(params)
        );
    """)


# ============================================================
# 坐标转换: GCJ-02 → WGS-84
# ============================================================

import math as _math

def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * _math.sqrt(abs(lng))
    ret += (20.0 * _math.sin(6.0 * lng * _math.pi) + 20.0 * _math.sin(2.0 * lng * _math.pi)) * 2.0 / 3.0
    ret += (20.0 * _math.sin(lat * _math.pi) + 40.0 * _math.sin(lat / 3.0 * _math.pi)) * 2.0 / 3.0
    ret += (160.0 * _math.sin(lat / 12.0 * _math.pi) + 320.0 * _math.sin(lat * _math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * _math.sqrt(abs(lng))
    ret += (20.0 * _math.sin(6.0 * lng * _math.pi) + 20.0 * _math.sin(2.0 * lng * _math.pi)) * 2.0 / 3.0
    ret += (20.0 * _math.sin(lng * _math.pi) + 40.0 * _math.sin(lng / 3.0 * _math.pi)) * 2.0 / 3.0
    ret += (150.0 * _math.sin(lng / 12.0 * _math.pi) + 300.0 * _math.sin(lng / 30.0 * _math.pi)) * 2.0 / 3.0
    return ret


def _is_out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _gcj02_to_wgs84(lng: float, lat: float) -> tuple:
    """GCJ-02 → WGS-84，迭代法精度 0.1m"""
    if _is_out_of_china(lng, lat):
        return lng, lat
    a = 6378245.0
    ee = 0.00669342162296594323
    wgs_lng, wgs_lat = lng, lat
    for _ in range(5):
        dlat = _transform_lat(wgs_lng - 105.0, wgs_lat - 35.0)
        dlng = _transform_lng(wgs_lng - 105.0, wgs_lat - 35.0)
        radlat = wgs_lat / 180.0 * _math.pi
        magic = _math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = _math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * _math.pi)
        dlng = (dlng * 180.0) / (a / sqrtmagic * _math.cos(radlat) * _math.pi)
        wgs_lng -= dlng
        wgs_lat -= dlat
    return wgs_lng, wgs_lat


def _convert_boundary_points(points_str: str) -> list:
    """
    解析高德边界字符串为 WGS-84 坐标点列表

    高德边界格式: "lng1,lat1;lng2,lat2;...;lngN,latN"
    或者 MultiPolygon: "lng1,lat1;lng2,lat2||lng1,lat1;..."
    双竖线 || 分隔多个多边形
    """
    # 先按双竖线拆（MultiPolygon）
    parts = points_str.split("||")
    rings = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        tokens = part.split(";")
        points = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            parts_xy = token.split(",")
            if len(parts_xy) < 2:
                continue
            try:
                lng = float(parts_xy[0].strip())
                lat = float(parts_xy[1].strip())
                wgs_lng, wgs_lat = _gcj02_to_wgs84(lng, lat)
                points.append((round(wgs_lng, 6), round(wgs_lat, 6)))
            except (ValueError, IndexError):
                continue
        if len(points) >= 3:
            rings.append(points)
    return rings


def points_to_geojson(rings: list, name: str) -> Optional[dict]:
    """坐标点环列表 → GeoJSON FeatureCollection（自动判读 Polygon 或 MultiPolygon）"""
    if not rings:
        return None

    if len(rings) == 1:
        polygon = Polygon(rings[0])
    else:
        polygon = Polygon(rings[0], rings[1:] if len(rings) > 1 else None)

    gdf = gpd.GeoDataFrame(
        {"name": [name]},
        geometry=[polygon],
        crs="EPSG:4326",
    )
    return json.loads(gdf.to_json())


# ============================================================
# API 响应解析
# ============================================================

def extract_suggestions_from_search(data: dict) -> list:
    """从高德搜索 API 的 JSON 里提取候选地点列表"""
    suggestions = []
    try:
        # 高德不同的返回格式兼容
        poi_list = None

        # 格式1: data.poiList.pois
        if isinstance(data.get("data"), dict):
            if isinstance(data["data"].get("poiList"), dict):
                poi_list = data["data"]["poiList"].get("pois", [])
            # 格式2: data.pois 直接
            elif isinstance(data["data"].get("pois"), list):
                poi_list = data["data"]["pois"]

        # 格式3: data直接就是列表
        if poi_list is None and isinstance(data, list):
            poi_list = data

        # 格式4: results 字段
        if poi_list is None and isinstance(data.get("results"), list):
            poi_list = data["results"]

        # 格式5: data.result 对象里的 poiList
        if poi_list is None and isinstance(data.get("result"), dict):
            if isinstance(data["result"].get("poiList"), dict):
                poi_list = data["result"]["poiList"].get("pois", [])

        if poi_list is None:
            return suggestions

        # 确保是列表
        if isinstance(poi_list, dict):
            poi_list = [poi_list]

        for item in poi_list:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "") or item.get("poi_name", "") or ""
            poi_id = item.get("id", "") or item.get("poi_id", "") or ""
            addr = item.get("address", "") or item.get("addr", "") or ""
            if name:
                suggestions.append({
                    "name": name,
                    "address": addr,
                    "id": poi_id,
                })
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    return suggestions


def extract_boundary_from_detail(data: dict) -> Optional[str]:
    """从高德详情 API 的 JSON 里抠出 boundary 轮廓字符串"""
    try:
        # 不同可能的嵌套路径
        boundary = None

        # 路径1: data.boundary
        if isinstance(data.get("data"), dict):
            boundary = data["data"].get("boundary")

        # 路径2: data.data.detailInfo.boundary
        if not boundary and isinstance(data.get("data"), dict):
            detail = data["data"].get("detailInfo") or data["data"].get("detail_info")
            if isinstance(detail, dict):
                boundary = detail.get("boundary") or detail.get("polygon") or detail.get("shape")

        # 路径3: data.boundary 直接在顶层
        if not boundary:
            boundary = data.get("boundary") or data.get("polygon")

        # 路径4: data.data.poi_info 里的 boundary
        if not boundary and isinstance(data.get("data"), dict):
            poi_info = data["data"].get("poiInfo") or data["data"].get("poi_info") or data["data"].get("poi")
            if isinstance(poi_info, dict):
                boundary = poi_info.get("boundary") or poi_info.get("polygon")

        if boundary and isinstance(boundary, str) and len(boundary) > 10:
            return boundary
        return None
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


# ============================================================
# Playwright 自动化: 搜索
# ============================================================

import os as _os
from contextlib import contextmanager


@contextmanager
def _no_proxy():
    """临时清除代理环境变量（含 Windows 大小写变体），执行完后恢复原样"""
    saved = {}
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        saved[key] = _os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, val in saved.items():
            if val is not None:
                _os.environ[key] = val


def _direct_search(query: str) -> list:
    """先用 requests 直接调高德搜索 API"""
    import requests as _req
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://ditu.amap.com/",
    }
    try:
        sess = _req.Session()
        sess.headers.update(headers)
        sess.get("https://ditu.amap.com/", timeout=8)
        # 高德搜索（urllib 编码 query 防止特殊字符破坏 URL）
        import urllib.parse as _urlparse
        url = f"https://www.amap.com/service/poi/search?keywords={_urlparse.quote(query)}&type=search&platform=0&s=show"
        resp = sess.get(url, timeout=10)
        if resp.status_code == 200:
            results = extract_suggestions_from_search(resp.json())
            if results: return results
    except Exception:
        pass
    return []


def search_suggestions(query: str) -> list:
    """
    搜索高德地图（带缓存，同个关键词第二次秒出）
    """
    if not query or not query.strip():
        return []

    _ensure_cache_dir()
    q = query.strip()
    cache_key = _hash_key(q)
    cache_path = os.path.join(_CACHE_DIR, f"gd_search_{cache_key}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(_do_search_suggestions, q)
        try:
            results = future.result(timeout=8)
            if results: _write_cache(cache_path, results)
            return results
        except concurrent.futures.TimeoutError:
            print("[Gaode AOI] 搜索超时(20s)，返回空")
            return []
        except Exception:
            return []


def _do_search_suggestions(query: str) -> list:
    """先试直接 HTTP，失败才用 Playwright"""
    direct = _direct_search(query)
    if direct:
        return direct

    result_suggestions = []
    fp = _build_fingerprint()

    # 重试2次，每次换指纹
    for attempt in range(2):
        if attempt > 0:
            fp = _build_fingerprint()  # 换指纹
            _random_delay(1.0, 2.0)

        try:
            with _no_proxy(), sync_playwright() as p:
                browser = _launch_browser(p)
                context = _create_context(browser, fp)
                page = context.new_page()
                _add_anti_detect_scripts(page)

                # 拦截搜索 API 响应
                def on_response(response):
                    url = response.url
                    # 高德搜索 API 特征：含 /das/search 或 /service/poi/search 或 keywords 参数
                    if ("/das/search" in url or "/service/poi/search" in url or "/poi/" in url) and "json" in response.headers.get("content-type", ""):
                        try:
                            data = response.json()
                            extracted = extract_suggestions_from_search(data)
                            result_suggestions.extend(extracted)
                        except Exception:
                            pass

                page.on("response", on_response)

                # Cookie 预热：先打开首页
                page.goto("https://ditu.amap.com/", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(random.randint(1500, 3000))

                # 搜索
                search_box = page.locator("#search-input")  # 高德搜索框 ID
                try:
                    search_box.wait_for(state="visible", timeout=8000)
                except Exception:
                    # 备用选择器
                    search_box = page.locator("input.autoComplete-input")
                    try:
                        search_box.wait_for(state="visible", timeout=5000)
                    except Exception:
                        search_box = page.locator("input[placeholder*='搜索']")
                        search_box.wait_for(state="visible", timeout=5000)

                search_box.click()
                _random_delay(0.3, 0.8)
                search_box.fill(query)
                _random_delay(0.5, 1.0)
                page.keyboard.press("Enter")

                # 等待搜索结果（留足够时间让 API 返回）
                page.wait_for_timeout(random.randint(4000, 6000))

                browser.close()
                break  # 成功就跳出重试
        except Exception:
            if attempt == 1:
                pass  # 最后一次失败就算了
            continue

    # 去重
    seen = set()
    unique = []
    for s in result_suggestions:
        key = f"{s['name']}|{s.get('id', '')}"
        if key not in seen and s['name']:
            seen.add(key)
            unique.append(s)

    return unique[:20]


# ============================================================
# Playwright 自动化: 提取边界
# ============================================================

def _direct_extract(poi_id: str) -> Optional[str]:
    """先用 requests 直接调高德详情 API"""
    import requests as _req
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://ditu.amap.com/",
    }
    urls = [
        f"https://www.amap.com/service/poi/info?id={poi_id}&s=show&platform=0",
        f"https://ditu.amap.com/das/indoor/?id={poi_id}&type=poi",
    ]
    try:
        sess = _req.Session()
        sess.headers.update(headers)
        sess.get("https://ditu.amap.com/", timeout=8)
        for url in urls:
            try:
                resp = sess.get(url, timeout=10)
                if resp.status_code == 200:
                    boundary = extract_boundary_from_detail(resp.json())
                    if boundary: return boundary
            except Exception:
                continue
    except Exception:
        pass
    return None


def extract_boundary(poi_id: str, place_name: str, headless: bool = True) -> Optional[dict]:
    """
    提取高德建筑轮廓（先查缓存 → 直接HTTP → Playwright兜底）
    同个 POI 第二次秒出
    """
    if not poi_id: return None

    # 命中缓存 → 秒出
    _ensure_cache_dir()
    cache_path = os.path.join(_CACHE_DIR, f"gd_extract_{_hash_key(poi_id)}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    # 先试直接 HTTP
    boundary_string = _direct_extract(poi_id)

    # Playwright 兜底
    if not boundary_string:
        fp = _build_fingerprint()
        for attempt in range(2):
            if attempt > 0:
                fp = _build_fingerprint()
                _random_delay(1.0, 2.5)
            try:
                with _no_proxy(), sync_playwright() as p:
                    browser = _launch_browser(p, headless=headless)
                    context = _create_context(browser, fp)
                    page = context.new_page()
                    _add_anti_detect_scripts(page)
                    page.goto("https://ditu.amap.com/", wait_until="domcontentloaded", timeout=15000)
                    _random_delay(1.0, 2.0)
                    detail_urls = [
                        f"https://www.amap.com/service/poi/info?id={poi_id}&s=show&platform=0",
                        f"https://ditu.amap.com/das/indoor/?id={poi_id}&type=poi",
                    ]
                    for url in detail_urls:
                        try:
                            resp = context.request.get(url, timeout=10000)
                            if resp.ok:
                                b = extract_boundary_from_detail(resp.json())
                                if b: boundary_string = b; break
                        except: continue
                    if not boundary_string:
                        for url in detail_urls:
                            js = page.evaluate(f"fetch('{url}',{{credentials:'include'}}).then(r=>r.text()).catch(e=>'FETCH_ERROR:'+e.message)")
                            if not js.startswith('FETCH_ERROR'):
                                try:
                                    b = extract_boundary_from_detail(json.loads(js))
                                    if b: boundary_string = b; break
                                except: pass
                            _random_delay(1.0, 2.0)
                    browser.close()
                    if boundary_string: break
            except Exception:
                continue

    if not boundary_string: return None

    try:
        rings = _convert_boundary_points(boundary_string)
        if not rings: return None
        geojson = points_to_geojson(rings, place_name)
        if geojson: _write_cache(cache_path, geojson)
        return geojson
    except Exception:
        return None
