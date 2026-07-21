"""
GIS WorkTable — LangChain 工具集
所有工具函数使用 @tool 装饰器，供 LangGraph Agent 调用。

迁移说明:
  原 ai_service.py 中 15+ 个工具函数 + 手写 while/if 循环
  现统一为 LangChain Tool，由 LangGraph 自动管理调用流程

每个工具输出不超过 3000 字符（保留原业务逻辑不变）
"""

import os
import sys
import json
import math
import time
import glob
import datetime
import subprocess
import tempfile
import threading
import re
import hashlib
import random
import ast
import shutil
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from langchain.tools import tool


# ============================================================
# 共享状态（每次请求开始时由 reset_state() 清空）
# ============================================================

_pending_layers: list = []          # 待推送到前端的 GeoJSON 图层
_pending_images: list = []          # 待推送到前端的图片/HTML
_pending_aoi_suggestions: dict = {} # AOI 候选列表
_pending_heatmap: dict = {"latest": None}
_clear_layers_flag: bool = False
_pending_layer_ops: list = []
_current_amap_key: str = ""
_search_call_count: int = 0    # 搜索次数计数，每次请求重置
_exec_call_count: int = 0       # Python 执行次数计数，每次请求重置
_temp_output_dir: str = ""          # 在 reset_state 时设置
_workspace_dir: str = ""
_registered_layers: dict = {}       # 已注册的图层信息

# 这些列表会被主模块读取，所以要导出
# 线程锁，保证 get_pending_state 的"读取+清空"操作原子性
_state_lock = threading.Lock()

def get_pending_state():
    """获取当前所有待发送状态并消费（清空），防止跨请求污染和校验器重复收集"""
    global _clear_layers_flag
    with _state_lock:
        result = {
            "layers": list(_pending_layers),
            "images": list(_pending_images),
            "aoi_suggestions": _pending_aoi_suggestions.get("latest"),
            "heatmap": _pending_heatmap.get("latest"),
            "clear_layers": _clear_layers_flag,
            "registered_layers": dict(_registered_layers),
            "layer_ops": list(_pending_layer_ops),
        }
        # 消费：清空已收集的状态，避免：
        # 1. 校验器重新调用 agent 时重复累积
        # 2. 本请求残留状态污染下个请求
        _pending_layers.clear()
        _pending_images.clear()
        _pending_layer_ops.clear()
        _clear_layers_flag = False
        _pending_heatmap["latest"] = None
        return result


def reset_state(amap_key: str = ""):
    """每次请求开始时调用，清空所有共享状态"""
    global _current_amap_key, _clear_layers_flag, _search_call_count, _exec_call_count
    _pending_layers.clear()
    _pending_images.clear()
    _pending_aoi_suggestions.clear()
    _pending_heatmap["latest"] = None
    _clear_layers_flag = False
    _pending_layer_ops.clear()
    _current_amap_key = amap_key
    _search_call_count = 0
    _exec_call_count = 0


def init_temp_dir():
    """初始化临时目录（在模块加载时或首次调用时执行）"""
    global _temp_output_dir, _workspace_dir
    if not _temp_output_dir:
        _temp_output_dir = os.path.join(tempfile.gettempdir(), "gis_worktable_output")
        os.makedirs(_temp_output_dir, exist_ok=True)
        os.makedirs(os.path.join(_temp_output_dir, "output"), exist_ok=True)
    if not _workspace_dir:
        _workspace_dir = os.path.join(_temp_output_dir, "workspace")
        os.makedirs(_workspace_dir, exist_ok=True)


def _push_layer(name: str, geojson: dict, style: dict = None):
    """将图层加入待发送列表"""
    try:
        layer = {"geojson": geojson, "name": name}
        if style:
            layer["style"] = style
        _pending_layers.append(layer)
    except Exception:
        pass


def _unregister_layer(name: str):
    """从注册表中移除图层"""
    _registered_layers.pop(name, None)


def _normalize_geojson(geojson: dict) -> dict:
    """将任意 GeoJSON 归一化为 FeatureCollection"""
    t = geojson.get("type")
    if t == "FeatureCollection":
        return geojson
    if t == "Feature":
        return {"type": "FeatureCollection", "features": [geojson]}
    if t in ("Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"):
        return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geojson, "properties": {}}]}
    return geojson


def _compute_bbox(geojson: dict) -> list:
    """计算 GeoJSON 的包围盒 [minLng, minLat, maxLng, maxLat]"""
    coords = []
    fc = _normalize_geojson(geojson)
    for f in fc.get("features", []):
        geom = f.get("geometry") or {}
        _extract_coords(geom, coords)
    if not coords:
        return [0, 0, 0, 0]
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return [min(lngs), min(lats), max(lngs), max(lats)]


def _extract_coords(geom: dict, coords: list):
    t = geom.get("type")
    c = geom.get("coordinates")
    if not t:
        return
    if t == "Point":
        if c: coords.append(c)
    elif t in ("MultiPoint", "LineString"):
        if c: coords.extend(c)
    elif t in ("MultiLineString", "Polygon"):
        if c:
            for ring in c:
                coords.extend(ring)
    elif t == "MultiPolygon":
        if c:
            for poly in c:
                for ring in poly:
                    coords.extend(ring)
    elif t == "GeometryCollection":
        for g in geom.get("geometries", []):
            _extract_coords(g, coords)
    elif t == "Feature":
        _extract_coords(geom.get("geometry", {}), coords)
    elif t == "FeatureCollection":
        for f in geom.get("features", []):
            _extract_coords(f.get("geometry", {}), coords)


def _register_layer(name: str, geojson: dict):
    """注册图层供 AI 后续查询"""
    try:
        fc = _normalize_geojson(geojson)
        features = fc.get("features", [])
        types = set()
        for f in features:
            geom = f.get("geometry", {}) or {}
            if geom.get("type"):
                types.add(geom["type"])
        bbox = _compute_bbox(geojson)
        _registered_layers[name] = {
            "name": name,
            "feature_count": len(features),
            "geometry_types": list(types) if types else ["未知"],
            "geojson": geojson,
            "bbox": bbox,
        }
    except Exception:
        pass


def get_registered_layers_snapshot() -> list:
    """返回当前所有注册图层的快照 [{name, geojson, geometry_types, feature_count, color?, visible?}]"""
    result = []
    for name, info in list(_registered_layers.items()):
        result.append({
            "filename": name,
            "geojson": info.get("geojson"),
            "geometry_type": ", ".join(info.get("geometry_types", [])),
            "feature_count": info.get("feature_count", 0),
            "source": "ai",
        })
    return result


def _add_pending_item(url: str, file_path: str = None):
    """添加到待发送的图片/HTML 列表"""
    init_temp_dir()
    if file_path and file_path.lower().endswith(".html"):
        try:
            with open(file_path, "r", encoding="utf-8") as _f:
                _content = _f.read()
            _pending_images.append({"url": url, "type": "html", "content": _content})
            os.remove(file_path)
        except Exception:
            _pending_images.append({"url": url, "type": "html"})
    else:
        _pending_images.append({"url": url, "type": "png"})


# ============================================================
# 工具: search_web — 必应搜索
# ============================================================

@tool
def search_web(query: str) -> str:
    """搜索网络信息，返回网页标题/链接/摘要。用于搜索最新新闻、数据、资料。涉及国外内容用中英文搜。"""
    global _search_call_count
    _search_call_count += 1
    if _search_call_count > 30:
        return "【搜索过热】已搜索太多次，请基于已有信息继续处理。"

    # 搜 Bing
    content = ""
    try:
        url = f"https://cn.bing.com/search?q={query.replace(' ', '+')}"
        content = fetch_webpage_impl(url)
        if content.startswith("错误") or len(content) < 200:
            content = ""
    except Exception:
        content = ""

    # 也搜 Yandex，结果合并
    yandex_content = ""
    try:
        url = f"https://yandex.com/search/?text={query.replace(' ', '+')}"
        yandex_content = fetch_webpage_impl(url)
        if yandex_content.startswith("错误") or len(yandex_content) < 200:
            yandex_content = ""
    except Exception:
        pass

    # 合并两个结果
    if yandex_content:
        if content:
            content = content + "\n\n--- Yandex 搜索结果 ---\n" + yandex_content
        else:
            content = yandex_content

    if not content:
        return "错误：搜索失败（Bing 和 Yandex 均未返回有效结果）"

    if len(content) > 6000:
        content = content[:6000] + "\n\n...(内容过长，已截断)"
    return content


# ============================================================
# 工具: fetch_webpage — 智能抓取网页
# ============================================================

def _html_to_markdown(html: str, url: str = "") -> str:
    """将 HTML 转为干净 Markdown，去除广告/导航噪音"""
    import re as _re

    text = _re.sub(r'<script[^>]*>.*?</script>', '', html, flags=_re.DOTALL)
    text = _re.sub(r'<style[^>]*>.*?</style>', '', text, flags=_re.DOTALL)
    text = _re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=_re.DOTALL)
    text = _re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=_re.DOTALL)
    text = _re.sub(r'<header[^>]*>.*?</header>', '', text, flags=_re.DOTALL)

    try:
        from markdownify import markdownify as _md
        text = _md(text, heading_style="ATX", strip=["img"])
    except ImportError:
        text = _re.sub(r'<[^>]+>', '', text)
        text = _re.sub(r'\s+', ' ', text)

    text = _re.sub(r'\n{4,}', '\n\n', text)
    text = _re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def fetch_webpage_impl(url: str, max_length: int = 10000) -> str:
    """获取网页内容的实现（被 search_web 和 fetch_webpage 共用）"""
    # 方案 A：Scrapling
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=20)
        if page.status == 200:
            html = str(page.html_content)
            if html and len(html) > 50:
                text = _html_to_markdown(html, url)
                text = text[:max_length]
                if text:
                    return text
    except ImportError:
        pass
    except Exception:
        pass

    # 方案 B：Playwright 子进程
    try:
        script = r'''import sys, asyncio
from playwright.async_api import async_playwright
async def fetch():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        page = await browser.new_page()
        await page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        await page.goto(sys.argv[1], timeout=15000, wait_until='domcontentloaded')
        await page.wait_for_timeout(1000)
        text = await page.evaluate('document.body.innerText') or ''
        await browser.close()
        return text
result = asyncio.run(fetch())
print(result[:int(sys.argv[2])])
'''
        my_env = {**os.environ.copy(), 'PYTHONIOENCODING': 'utf-8'}
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        result = subprocess.run(
            [sys.executable, '-c', script, url, str(max_length)],
            capture_output=True, timeout=30,
            env=my_env, startupinfo=startupinfo
        )
        stdout = result.stdout.decode('utf-8', errors='replace')
        if result.returncode != 0:
            return f"错误：{result.stderr.decode('utf-8', errors='replace')[:300]}"
        return stdout.strip() or "抓取结果为空"
    except subprocess.TimeoutExpired:
        return "错误：抓取超时"
    except Exception as e:
        return f"错误：[{type(e).__name__}] {str(e)[:200]}"

    # 所有抓取方案均失败
    return "错误：所有抓取方案均失败（网站可能被屏蔽或网络不可达）"


@tool
def fetch_webpage(url: str) -> str:
    """获取网页内容（Scrapling隐身引擎 + markdownify清洗，自动去广告/导航/侧栏，返回干净 Markdown，token 节省约80%）。国内网站直连，反爬增强"""
    global _search_call_count
    _search_call_count += 1
    if _search_call_count > 30:
        return "【已停止】已太多次获取网页，请基于已有信息继续处理。"

    result = fetch_webpage_impl(url)
    if result is None:
        return "错误：无法获取网页内容（所有抓取方案均失败，可能网站不可达或超时）"
    if result.startswith("错误"):
        return result
    return f"[Scrapling清洗] 以下为网页的干净内容（Markdown格式，已去除广告/导航）\n\n{result}"


# ============================================================
# 工具: scrape_page — Scrapling 隐身抓取
# ============================================================

@tool
def scrape_page(url: str, selector: str = "body") -> str:
    """使用 Scrapling 隐身引擎抓取网页（TLS指纹混淆+真实浏览器UA+Cloudflare绕过），适合反爬严格的网站。比 fetch_webpage 更快更反爬"""
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=20)
        if page.status != 200:
            return f"错误：HTTP {page.status}"
        elements = page.css(selector)
        if not elements:
            return f"未找到匹配「{selector}」的内容"
        text = str(elements[0].text) if hasattr(elements[0], 'text') else str(page.html_content)
        text = text.strip()
        if len(text) > 8000:
            text = text[:8000] + "\n\n...(内容过长，已截断)"
        return text
    except ImportError:
        return "错误：Scrapling 未安装，请执行 pip install scrapling[fetchers]"
    except Exception as e:
        return f"错误：[{type(e).__name__}] {str(e)[:200]}"


# ============================================================
# 工具: search_platform — 平台搜索（B站等）
# ============================================================

@tool
def search_platform(platform: str, query: str) -> str:
    """搜索中国互联网平台的内容（B站/bilibili 等），零配置国内直连"""
    platform = platform.lower().strip()

    if platform in ('bilibili', 'b站'):
        try:
            import urllib.request, urllib.parse
            params = urllib.parse.urlencode({
                'search_type': 'video',
                'keyword': query,
                'page': 1,
            })
            url = f"https://api.bilibili.com/x/web-interface/search/all/v2?{params}"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.bilibili.com/',
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if data.get('code') != 0:
                return f"B站搜索失败：{data.get('message', '未知错误')}"
            results = []
            for nav in data.get('data', {}).get('result', []):
                for item in nav.get('data', [])[:5]:
                    title = re.sub(r'<[^>]+>', '', item.get('title', ''))
                    author = item.get('author', '')
                    desc = item.get('desc', '')[:100]
                    play = item.get('play', 0)
                    results.append(f"  - {title}（作者:{author} 播放:{play}）\n    {desc}")
            if results:
                return f"B站搜索「{query}」结果（共{len(results)}条）：\n" + "\n".join(results[:15])
            else:
                return f"B站搜索「{query}」未找到相关视频"
        except Exception as e:
            return f"B站搜索出错：{str(e)[:200]}"
    else:
        return f"平台「{platform}」暂不支持。当前支持：bilibili（B站，零配置）"


# ============================================================
# 工具: save_file — 保存文件
# ============================================================

@tool
def save_file(filename: str, content: str) -> str:
    """把内容保存成文件（CSV/GeoJSON/TXT等）。文件名不加 output/ 前缀。优先UTF-8编码。GeoJSON自动加载到地图，HTML自动显示在前端。"""
    init_temp_dir()
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)

    output_dir = _temp_output_dir
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    # GeoJSON → 自动加载到地图
    if filename.endswith('.geojson'):
        try:
            geojson_data = json.loads(content)
            if geojson_data.get('type') in ('FeatureCollection', 'Feature'):
                name = filename.replace('.geojson', '')
                from backend.services.tools import _push_layer, _register_layer
                _push_layer(name, geojson_data)
                _register_layer(name, geojson_data)
        except Exception:
            pass

    # HTML → 自动显示在前端
    if filename.endswith('.html'):
        try:
            ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
            new_name = f"{ts}_{filename}"
            new_path = os.path.join(output_dir, new_name)
            os.rename(path, new_path)
            _add_pending_item(f"/output/{new_name}", new_path)
        except Exception:
            _add_pending_item(f"/output/{filename}")

    return f"文件已保存：{path}"


# ============================================================
# 第一层：AST 静态代码校验
# ============================================================

ALLOWED_IMPORTS = {
    'geopandas', 'shapely', 'numpy', 'pandas', 'matplotlib',
    'pyecharts', 'json', 'math', 're', 'datetime', 'io',
    'tempfile', 'requests', 'pyproj', 'rasterio',
}
BANNED_FUNCTIONS = {'eval', 'exec', '__import__', 'getattr', 'setattr', 'compile', 'vars', 'locals', 'globals', 'delattr', 'input', 'breakpoint'}
BANNED_ATTR_CALLS = {
    'system', 'popen', 'call', 'Popen', 'run', 'check_call', 'check_output',
    'startfile', 'spawnl', 'spawnle', 'spawnlp', 'spawnlpe',
    'spawnv', 'spawnve', 'spawnvp', 'spawnvpe', 'posix_spawn', 'posix_spawnp',
    'load_library',
}
BANNED_MAGIC_ATTRS = {'__dict__', '__globals__', '__builtins__', '__class__', '__bases__', '__subclasses__', '__mro__', '__getattribute__', '__self__', '__func__', '__code__', '__traceback__'}
BANNED_SYSTEM_MODULES = {'os', 'subprocess', 'shutil', 'sys', 'ctypes', 'ctypeslib', 'socket'}
# 帧/追踪属性——经典内省逃逸链的关键跳板
BANNED_FRAME_ATTRS = {'tb_frame', 'tb_next', 'f_back', 'f_globals', 'f_locals', 'f_builtins', 'f_code', 'f_trace'}


def _ast_sandbox_check(code: str) -> str | None:
    """AST 静态代码校验。返回 None 表示通过，返回字符串表示拦截原因。"""

    def _iter_attr_chain_names(node):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield from _iter_attr_chain_names(node.value)
            yield node.attr

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f'沙箱拦截：代码语法错误（{e}）'

    for node in ast.walk(tree):
        # ---- 导入检查 ----
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split('.')[0]
                if base not in ALLOWED_IMPORTS:
                    return f'沙箱拦截：禁止导入库「{alias.name}」（非白名单库）'

        if isinstance(node, ast.ImportFrom):
            if node.module:
                base = node.module.split('.')[0]
                if base not in ALLOWED_IMPORTS:
                    return f'沙箱拦截：禁止导入库「{node.module}」（非白名单库）'
                # 阻止 from numpy import os 等跨白名单导入系统模块
                for alias in node.names:
                    if alias.name in BANNED_SYSTEM_MODULES:
                        return f'沙箱拦截：禁止通过白名单库导入系统模块「{alias.name}」'

        # ---- 函数调用检查（含属性链调用，防 __builtins__.eval） ----
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in BANNED_FUNCTIONS:
                    return f'沙箱拦截：禁止调用危险函数「{node.func.id}」'
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in BANNED_FUNCTIONS:
                    return f'沙箱拦截：禁止通过属性链调用危险函数「{node.func.attr}」'

        # ---- 裸名检查：__builtins__ 等魔法名作为标识符直写 ----
        if isinstance(node, ast.Name):
            if node.id in BANNED_MAGIC_ATTRS:
                return f'沙箱拦截：禁止直接使用魔法标识符「{node.id}」'

        # ---- 属性访问检查（全面覆盖：读取、赋值、调用均逃不掉） ----
        if isinstance(node, ast.Attribute):
            # 魔法属性——经典内省逃逸链的源头
            if node.attr in BANNED_MAGIC_ATTRS:
                return f'沙箱拦截：禁止访问魔法属性「{node.attr}」'
            # 危险系统方法——即使 os 通过任何途径泄漏也拦到最后一步
            if node.attr in BANNED_ATTR_CALLS:
                return f'沙箱拦截：禁止访问危险系统方法「{node.attr}」'
            # 帧/追踪属性——异常对象 → tb_frame → f_globals 逃逸链
            if node.attr in BANNED_FRAME_ATTRS:
                return f'沙箱拦截：禁止访问帧/追踪属性「{node.attr}」'
            # 属性链递归检查：a.b.c.d 中只要有一个节点是系统模块名即拦截
            names = list(_iter_attr_chain_names(node))
            if len(names) >= 2:
                for n in names[1:]:
                    if n in BANNED_SYSTEM_MODULES:
                        return f'沙箱拦截：属性链中含禁止的系统模块名「{n}」'

        # ---- 字符串常量检查 ----
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if '../' in s or '..\\' in s:
                return '沙箱拦截：禁止路径遍历（../）'
            if s.startswith('/') or (len(s) > 1 and s[1] == ':'):
                return '沙箱拦截：禁止使用绝对路径'
            if s.lower().startswith('file://'):
                return '沙箱拦截：禁止通过 file:// 协议读取本地文件'

    return None


# ============================================================
# 辅助函数 —— 图片/HTML 重命名 & chart 清理
# ============================================================

def _rename_output_files(new_files: set, suffix: str, temp_dir: str):
    """为输出目录中新生成的文件加时间戳前缀，避免文件名冲突。"""
    ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    for fname in sorted(new_files):
        if not fname.lower().endswith(suffix):
            continue
        src = os.path.join(temp_dir, fname)
        dest_name = f'{ts}_{fname}'
        dest = os.path.join(temp_dir, dest_name)
        try:
            os.rename(src, dest)
        except Exception:
            shutil.copy2(src, dest)
            try:
                os.remove(src)
            except Exception:
                pass
        _add_pending_item(f'/output/{dest_name}', dest)


def _cleanup_charts(temp_dir: str, max_charts: int = 20):
    """按 mtime 清理旧 chart，保留最近 max_charts 张。"""
    charts = glob.glob(os.path.join(temp_dir, 'chart_*.png'))
    if len(charts) <= max_charts:
        return
    charts.sort(key=os.path.getmtime)
    for old in charts[:-max_charts]:
        try:
            os.remove(old)
        except Exception:
            pass


def _extract_geojson(name: str, data: dict):
    """推送并注册一个 GeoJSON 图层，返回要素数量。"""
    _push_layer(name, data)
    _register_layer(name, data)
    if data.get('type') == 'FeatureCollection':
        return len(data.get('features', []))
    return 1


# ============================================================
# 工具: execute_python — 执行 GIS 代码（三层轻量沙箱）
# ============================================================

@tool
def execute_python(code: str) -> str:
    """【最后选择】执行自定义 Python GIS 代码（沙箱隔离）。仅当所有专用工具都不满足需求时才用本工具。

    ❌ 以下操作已有专用工具，禁止使用 execute_python：
       - 地理编码/地址转坐标 → 必须用 amap_geocode
       - POI 搜索/查天气 → 必须用 amap_poi_search
       - 行政边界获取 → 必须用 datav_boundary
       - AOI 建筑轮廓提取 → 必须用 unified_aoi_search/extract
       - 路网下载 → 必须用 download_road_network
       - 网络分析（路径/服务区/最近设施） → 必须用 network_analysis
       - 热力图生成 → 必须用 create_heatmap
       - 图层属性统计图 → 必须用 create_chart
       - 字段计算 → 必须用 field_calculate

    ✅ 本工具适合做的：
       - 自定义 GIS 空间分析（矢量/栅格运算）
       - 数据格式转换与清洗
       - 国外边界数据获取（osmnx）
       - 自定义 matplotlib/pyecharts 可视化

    可用库：geopandas, shapely, numpy, pandas, matplotlib, pyecharts, json, math, re, datetime, io, tempfile, requests, pyproj, rasterio, osmnx
    print(GeoJSON) 自动加载到地图（加 name 字段做图层名）
    plt.savefig('chart_xxx.png') 生成图表

    安全：严禁在代码中硬编码 API Key（高德 Key 已自动注入 _AMAP_KEY 变量）"""
    global _exec_call_count
    _exec_call_count += 1
    if _exec_call_count > 5:
        return f"【执行过热】本次请求已执行 {_exec_call_count} 次 Python 代码，请基于已有结果继续，不要再执行了。"
    init_temp_dir()

    # ================================================================
    # 第一层：AST 静态代码校验（只查用户代码，不注入代码）
    # ================================================================
    ast_error = _ast_sandbox_check(code)
    if ast_error:
        return ast_error

    # ================================================================
    # 第二层：每次执行创建专属临时目录
    # ================================================================
    exec_dir = tempfile.mkdtemp(prefix='gis_sandbox_')
    start_time = time.time()

    try:
        # 环境初始化：OSM 镜像（多镜像自动切换）+ matplotlib 中文字体
        _setup_blocks = r"""
try:
    import osmnx as _ox
    import urllib.request, json
    _OVERPass_MIRRORS = [
        'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
        'https://overpass.osm.ch/api/interpreter',
        'https://overpass-api.de/api/interpreter',
        'https://overpass.kumi.systems/api/interpreter',
        'https://overpass.openstreetmap.ie/api/interpreter',
    ]
    for _url in _OVERPass_MIRRORS:
        try:
            _test = urllib.request.urlopen(_url + '?data=[out:json];node(0,0,1,1);out;', timeout=5)
            if _test.status == 200:
                _ox.settings.overpass_url = _url
                break
        except Exception:
            continue
except Exception:
    pass

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as _fm
for _fp in [
    r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\NotoSansSC-VF.ttf', r'C:\Windows\Fonts\Deng.ttf',
    r'C:\Windows\Fonts\simsun.ttc',
]:
    try:
        _fm.fontManager.addfont(_fp)
        _prop = _fm.FontProperties(fname=_fp)
        plt.rcParams['font.sans-serif'] = [_prop.get_name()] + plt.rcParams.get('font.sans-serif', ['DejaVu Sans'])
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['axes.unicode_minus'] = False
        break
    except Exception:
        continue
plt.style.use("ggplot")
"""

        _amap_injection = f'_AMAP_KEY = {_current_amap_key!r}\n\n'
        _final_code = _amap_injection + _setup_blocks.rstrip() + '\n\n' + code

        temp_path = os.path.join(exec_dir, '_user_code_.py')
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(_final_code)

        # 记录执行前输出目录的快照
        try:
            before_files = set(os.listdir(_temp_output_dir))
        except Exception:
            before_files = set()

        env = os.environ.copy()
        env['AMAP_KEY'] = _current_amap_key
        env['PYTHONIOENCODING'] = 'utf-8'

        # ================================================================
        # 第三层：子进程执行 + 超时强杀
        # ================================================================
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True, timeout=120, encoding='utf-8', errors='replace',
            cwd=exec_dir,
            env=env,
        )

        elapsed = time.time() - start_time

        # 将临时目录中生成的文件复制到真实输出目录
        try:
            for fname in os.listdir(exec_dir):
                if fname == '_user_code_.py':
                    continue
                fpath = os.path.join(exec_dir, fname)
                if os.path.isfile(fpath):
                    dest = os.path.join(_temp_output_dir, fname)
                    if os.path.exists(dest):
                        ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                        name_part, ext = os.path.splitext(fname)
                        dest = os.path.join(_temp_output_dir, f'{name_part}_{ts}{ext}')
                    shutil.copy2(fpath, dest)
        except Exception:
            pass

        if result.returncode != 0:
            stderr = result.stderr.strip()
            return f'代码执行错误（{elapsed:.1f}s）：{stderr[:2000]}\n请根据错误信息修改代码后重试。'

        output = result.stdout.strip()

        # 检测新生成的图片和 HTML
        try:
            after_files = set(os.listdir(_temp_output_dir))
            new_files = after_files - before_files

            _rename_output_files(new_files, '.png', _temp_output_dir)
            _rename_output_files(new_files, '.html', _temp_output_dir)
            _cleanup_charts(_temp_output_dir)
        except Exception:
            pass

        if not output:
            return f'代码执行成功（{elapsed:.1f}s，无输出）'

        # 检测 GeoJSON（先逐行扫，再整体解析）
        geojson_found = False
        feature_count = 0
        output_lines = output.split('\n')
        for line in output_lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict) and data.get('type') in ('FeatureCollection', 'Feature'):
                    now_str = datetime.datetime.now().strftime('%H%M%S')
                    name = data.get('name', f'分析结果_{now_str}')
                    feature_count = _extract_geojson(name, data)
                    geojson_found = True
                    break
            except (json.JSONDecodeError, ValueError):
                continue

        if not geojson_found:
            try:
                data = json.loads(output)
                if isinstance(data, dict) and data.get('type') in ('FeatureCollection', 'Feature'):
                    now_str = datetime.datetime.now().strftime('%H%M%S')
                    name = data.get('name', f'分析结果_{now_str}')
                    feature_count = _extract_geojson(name, data)
                    geojson_found = True
            except (json.JSONDecodeError, ValueError):
                pass

        if geojson_found:
            return f'GIS 结果已生成并加载到地图（{feature_count} 个要素，耗时 {elapsed:.1f}s）\n---\n{output[:3000]}'

        return f'代码执行成功（{elapsed:.1f}s）\n---\n{output[:3000]}'

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return f'代码执行超时（{elapsed:.1f}s > 120s），已强制终止进程。请简化操作或分批处理。'
    except Exception as e:
        return f'执行异常：{str(e)[:500]}'
    finally:
        try:
            shutil.rmtree(exec_dir, ignore_errors=True)
        except Exception:
            pass


# ============================================================
# 工具: amap_poi_search — 高德 POI 搜索（独立工具）
# ============================================================

@tool
def amap_poi_search(keywords: str, city: str = "", location: str = "", radius: int = 1000) -> str:
    """高德地图 POI 搜索（餐厅/银行/超市等），自动转 WGS-84 加载到地图。
    keywords: 搜索关键词；city: 城市名（必填）；location: 中心点"经度,纬度"（周边搜索用）；radius: 搜索半径米（默认1000）。禁止用 execute_python 调高德API。"""
    if not _current_amap_key:
        return "高德 API Key 未配置，请在设置中配置高德地图密钥"

    from backend.services.amap_service import search_poi as _search_poi

    # 如果有 location，需要从 WGS-84 转到 GCJ-02 再搜索
    # （高德 API 需要 GCJ-02 坐标输入）
    actual_location = location
    if location:
        try:
            parts = location.split(",")
            wgs_lng, wgs_lat = float(parts[0].strip()), float(parts[1].strip())
            # 近似：WGS-84 → GCJ-02 的逆转换（直接用高德 API 接受 WGS-84 也可以，但结果偏差不大）
            # 高德周边搜索直接接受 WGS-84 也能工作
            actual_location = f"{wgs_lng},{wgs_lat}"
        except (ValueError, IndexError):
            pass

    result = _search_poi(
        keywords=keywords,
        city=city,
        location=actual_location if location else "",
        radius=radius,
        api_key=_current_amap_key
    )

    if result.get("error"):
        return f"POI 搜索失败：{result['error']}"

    geojson = result["geojson"]
    count = result["count"]
    source = result["source"]

    if count == 0:
        return f"未找到「{keywords}」相关 POI"

    # 自动推送到地图（名称标注"高德已转WGS84"，说明坐标已转换）
    layer_name = f"{keywords}_POI(高德已转WGS84)"
    _push_layer(layer_name, geojson, {"color": "#e74c3c", "fillColor": "#e74c3c"})
    _register_layer(layer_name, geojson)

    source_desc = "关键字搜索" if source == "text" else "周边搜索"
    feat_count = len(geojson.get("features", []))
    return f"高德 {source_desc} 完成：找到 {count} 个「{keywords}」POI，原始坐标 GCJ-02 已转 WGS-84，已加载 {feat_count} 个点到地图（图层名已标注）"


# ============================================================
# 工具: amap_geocode — 高德地理编码（地名 → 坐标）
# ============================================================

@tool
def amap_geocode(address: str, city: str = "") -> str:
    """高德地理编码：将地名转为 WGS-84 坐标"经度,纬度"字符串，供 network_analysis 等工具使用。
address: 地址/地名（如"广州塔""广州南站"）；city: 城市名（可选，如"广州"）。
重要：必须用本工具做地理编码，严禁用 execute_python 调高德 API。"""
    if not _current_amap_key:
        return "高德 API Key 未配置，请在设置中配置高德地图密钥"

    import requests
    try:
        params = {
            "key": _current_amap_key,
            "address": address,
            "output": "JSON",
        }
        if city:
            params["city"] = city

        resp = requests.get("https://restapi.amap.com/v3/geocode/geo", params=params, timeout=10)
        data = resp.json()

        if data.get("status") != "1":
            return f"地理编码失败：{data.get('info', '未知错误')}"

        geocodes = data.get("geocodes", [])
        if not geocodes:
            return f"未找到「{address}」的坐标"

        loc = geocodes[0].get("location", "")
        if not loc:
            return f"未找到「{address}」的坐标"

        lng, lat = loc.split(",")
        from backend.services.geo_coords import gcj02_to_wgs84
        wgs_lng, wgs_lat = gcj02_to_wgs84(float(lng), float(lat))
        return f"「{address}」的坐标（WGS-84）：{wgs_lng:.6f},{wgs_lat:.6f}"
    except Exception as e:
        return f"地理编码失败: {str(e)[:200]}"


# ============================================================
# 工具: unified_aoi_search / unified_aoi_extract（百度 AOI）
# ============================================================

@tool
def unified_aoi_search(query: str) -> str:
    """搜索地点轮廓，返回候选列表在聊天框显示。
    流程：用户说"提取轮廓"或"AOI"时先调本工具 → 在聊天框显示候选列表
    → **执行后立刻停止，不要继续提取**，等用户点击选择
    → 用户选择后会发来"已选择AOI候选: 名称 | ID: xxx | 来源: baidu"
    → 收到后用 unified_aoi_extract 提取
    提取失败的话如实告诉用户，**严禁自己估算或画边界**"""
    try:
        from backend.services.baidu_aoi_service import search_suggestions
        suggestions = search_suggestions(query)
        if not suggestions:
            return "搜索失败：未找到候选地点"
        tagged = [{"name": s["name"], "address": s.get("address", ""), "id": s["uid"], "source": "baidu"} for s in suggestions]
        _pending_aoi_suggestions["latest"] = {"suggestions": tagged, "sent": False}
        lines = [f"共 {len(tagged)} 个候选地点："]
        for i, s in enumerate(tagged[:15], 1):
            addr = f" ({s['address']})" if s.get("address") else ""
            lines.append(f"  {i}. {s['name']}{addr}")
        lines.append("候选已显示在聊天框，等待用户点击选择")
        return "\n".join(lines)
    except Exception as e:
        return f"搜索失败: {str(e)}"


@tool
def unified_aoi_extract(uid: str, name: str) -> str:
    """根据用户选择的候选提取建筑轮廓（百度数据源），转WGS84加载到地图。
    提取失败则如实告诉用户"暂时无法获取"。**严禁自己估算或画近似边界**"""
    try:
        from backend.services.baidu_aoi_service import extract_boundary
        geojson = extract_boundary(uid, name)
        if geojson:
            _push_layer(name, geojson)
            _register_layer(name, geojson)
            return f"成功提取 {name} 的AOI轮廓，已加载到地图"
        return f"未能提取 {name} 的AOI轮廓"
    except Exception as e:
        return f"提取失败: {str(e)}"


# ============================================================
# 工具: 图层查询
# ============================================================

@tool
def _format_extent(bbox: list) -> str:
    """将 bbox 转为可读的描述文本"""
    if not bbox or bbox == [0, 0, 0, 0]:
        return "未知范围"
    lng = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    span_lng = bbox[2] - bbox[0]
    span_lat = bbox[3] - bbox[1]
    loc = f"中心: {lat:.3f}°N, {lng:.3f}°E"
    if span_lng < 0.1 and span_lat < 0.1:
        loc += "（小范围）"
    elif span_lng < 1 and span_lat < 1:
        loc += "（城区级）"
    else:
        loc += "（大区域）"
    return loc


@tool
def get_registered_layers() -> str:
    """查看当前地图上所有已加载的图层列表，包括图层名、要素数量、几何类型、覆盖范围"""
    if not _registered_layers:
        return "当前没有已加载的图层"
    lines = [f"当前共 {len(_registered_layers)} 个图层："]
    for name, info in _registered_layers.items():
        types = ", ".join(info.get("geometry_types", ["未知"]))
        ext = _format_extent(info.get("bbox", []))
        lines.append(f"  - {name}：{info['feature_count']} 个要素，类型：{types}，{ext}")
    lines.append("\n如需查看某个图层的具体数据内容，可以使用 get_layer_detail 工具")
    return "\n".join(lines)


@tool
def get_layer_detail(layer_name: str) -> str:
    """查看指定图层的详细数据内容（GeoJSON 预览）"""
    info = _registered_layers.get(layer_name)
    if not info:
        matches = [n for n in _registered_layers.keys() if layer_name in n]
        if len(matches) == 1:
            info = _registered_layers[matches[0]]
        elif len(matches) > 1:
            return f"找到多个匹配：{', '.join(matches)}，请指定完整名称"
        else:
            return f"未找到图层「{layer_name}」，当前图层：{', '.join(_registered_layers.keys()) or '无'}"

    geojson = info.get("geojson", {})
    preview = json.dumps(geojson, ensure_ascii=False)[:2000]
    bbox = info.get("bbox", [])
    return (
        f"图层：{info['name']}\n"
        f"要素数：{info['feature_count']}\n"
        f"几何类型：{', '.join(info['geometry_types'])}\n"
        f"覆盖范围：{_format_extent(bbox)}\n"
        f"数据预览：\n{preview}"
    )


# ============================================================
# 工具: datav_boundary — 行政边界
# ============================================================

@tool
def datav_boundary(name: str) -> str:
    """从阿里云 DataV 获取中国省/市/区三级行政边界，自动转 WGS-84 加载到地图。国外边界用 execute_python 调 osmnx。查不到时尝试上级行政区划。"""
    try:
        from backend.services.datav_service import fetch_boundary
        data = fetch_boundary(name)
        if data is None:
            return f"获取失败：DataV 未找到«{name}»的数据，请检查名称是否正确"
        _push_layer(name, data)
        _register_layer(name, data)
        feat_info = f"（{len(data.get('features', []))} 个要素）" if data.get("features") else ""
        return f"成功获取 {name} 的边界数据{feat_info}，坐标系已转 WGS-84，已加载到地图"
    except Exception as e:
        return f"获取失败：{str(e)[:200]}"


# ============================================================
# 工具: create_heatmap — 热力图
# ============================================================

@tool
def create_heatmap(layer_name: str, weight_field: str = "", radius: int = 20, gradient: str = "") -> str:
    """从点图层生成热力图。需先有点图层（含权重字段）。参数：weight_field（权重字段）、radius（像素半径，默认20）、gradient（渐变色如"0.4=blue,1.0=red"）。"""
    info = _registered_layers.get(layer_name)
    if not info:
        return f"图层 {layer_name} 未找到"
    try:
        import geopandas as gpd
        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层 {layer_name} 为空"
        pg = gdf[gdf.geometry.type.isin(["Point", "MultiPoint"])]
        if pg.empty:
            return "没有点要素，无法生成热力图"
        pts = []
        for _, r in pg.iterrows():
            g = r.geometry
            v = float(r[weight_field]) if weight_field and weight_field in r else 1.0
            if g.geom_type == "MultiPoint":
                for p in g.geoms:
                    pts.append([p.y, p.x, v])
            else:
                pts.append([g.y, g.x, v])

        grad = None
        if gradient:
            try:
                parts = [p.strip() for p in gradient.split(",") if p.strip() and "=" in p]
                if parts:
                    grad = {}
                    for p in parts:
                        k, v2 = p.split("=", 1)
                        grad[float(k.strip())] = v2.strip()
            except Exception:
                pass

        opts = {"radius": radius, "blur": max(10, radius - 5)}
        if grad:
            opts["gradient"] = grad
        _pending_heatmap["latest"] = {"points": pts, "name": f"{layer_name}_heat", "options": opts}
        return f"热力图已生成：{len(pts)} 个点"
    except Exception as e:
        return f"热力图生成失败: {str(e)}"


# ============================================================
# 工具: measure_area — 精确面积测量（自动选投影）
# ============================================================

@tool
def measure_area(layer_name: str) -> str:
    """精确测量指定图层的面积（平方公里），自动选择最佳 UTM 投影带，支持多要素汇总"""
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
        centroid = gdf.dissolve().centroid.iloc[0]
        lon, lat = centroid.x, centroid.y

        # UTM 带号：zone = floor((lon + 180) / 6) + 1
        utm_zone = int(np.floor((lon + 180) / 6)) + 1
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
        area_km2 = area_m2 / 1_000_000

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

        feat_count = len(gdf)
        geom_types = gdf.geometry.type.unique().tolist()

        result = (
            f"图层「{layer_name}」面积测量结果：\n"
            f"- 面积：{area_km2:.2f} 平方公里\n"
            f"- 投影：UTM {utm_zone}{hemi}（EPSG:{epsg_code}）"
        )
        if cross_check:
            result += f"\n- 交叉验证：{cross_check}"
        result += (
            f"\n- 几何类型：{', '.join(geom_types)}"
            f"\n- 要素数：{feat_count}"
            f"\n- 中心点：{lat:.4f}°, {lon:.4f}°"
            f"\n- 坐标系：WGS-84 → 投影后计算"
        )

        return result

    except Exception as e:
        import traceback
        return f"面积测量失败: {str(e)}\n{traceback.format_exc()}"


# ============================================================
# 工具: field_calculate — 字段计算器
# ============================================================

@tool
def field_calculate(layer_name: str, expression: str, new_field: str, field_type: str = "float") -> str:
    """计算并添加新字段到指定图层。expression 写 Python 表达式（如"面积*0.0015"），直接引用字段名。支持 abs/round/int/float/str/len/min/max/sum/pow。自动更新地图。"""
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
        import pandas as pd
        import numpy as np
        import json

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层 {layer_name} 为空"

        safe_globals = {"__builtins__": {}}
        safe_locals = {
            "gdf": gdf,
            "np": np,
            "pd": pd,
            "abs": abs, "round": round, "int": int, "float": float,
            "str": str, "len": len, "min": min, "max": max,
            "sum": sum, "pow": pow, "bool": bool,
        }
        # 把所有字段注入局部变量，方便直接引用
        for col in gdf.columns:
            if col != "geometry" and col not in safe_locals:
                pass  # 不用注入全部，通过 gdf.eval 访问
        try:
            result = gdf.eval(expression)
            gdf[new_field] = result
        except Exception:
            try:
                result = gdf.apply(lambda row: eval(expression, safe_globals, {**safe_locals, **row.to_dict()}), axis=1)
                gdf[new_field] = result
            except Exception as e2:
                return f"表达式计算失败：{str(e2)[:200]}"

        if field_type == "int":
            gdf[new_field] = gdf[new_field].astype(int, errors="ignore")
        elif field_type == "str":
            gdf[new_field] = gdf[new_field].astype(str)

        # 类型转换保底
        try:
            gdf[new_field] = gdf[new_field].replace([np.inf, -np.inf], np.nan).fillna(0)
        except Exception:
            pass

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name

        _registered_layers[layer_name]["geojson"] = geojson_data
        _push_layer(layer_name, geojson_data)

        non_null = gdf[new_field].notna().sum()
        return f"已为图层「{layer_name}」添加字段「{new_field}」（{field_type}，{non_null}/{len(gdf)} 个要素有值），已更新地图"
    except Exception as e:
        return f"字段计算失败：{str(e)[:200]}"


# ============================================================
# 工具: clear_layers — 清空地图
# ============================================================

@tool
def clear_layers() -> str:
    """清空地图上所有图层，释放内存和地图资源"""
    global _clear_layers_flag
    count = len(_registered_layers)
    _registered_layers.clear()
    _pending_layers.clear()
    _clear_layers_flag = True
    return f"已清空 {count} 个图层"


# ============================================================
# 工具: get_session_logs — 查询历史
# ============================================================

@tool
def get_session_logs(n: int = 20) -> str:
    """查看最近的问答日志，包含用户问题、AI回复、当时有哪些图层"""
    try:
        from backend.services.log_service import get_temp_log, get_perm_log
        records = get_temp_log()
        if not records:
            return "暂无临时日志记录"
        lines = [f"== 当前会话（{len(records)} 次问答） =="]
        for i, r in enumerate(records[-n:], 1):
            t = r.get("time", "")[-19:] if r.get("time") else ""
            user_msg = r.get("user", "")[:80]
            ai_msg = r.get("ai", "")[:100]
            layers = r.get("layers", {})
            layer_info = ", ".join(layers.keys()) if layers else "无"
            lines.append(f"{i}. [{t}] 问：{user_msg}")
            lines.append(f"   答：{ai_msg}")
            lines.append(f"   图层：{layer_info}")

        perm = get_perm_log(5)
        if perm:
            lines.append(f"== 历史问题记录（{len(perm)} 条） ==")
            for r in perm:
                pt = r.get("time", "")[-19:] if r.get("time") else ""
                pu = r.get("user", "")[:60]
                pa = r.get("ai", "")[:80]
                lines.append(f"  [{pt}] 问：{pu}")
                lines.append(f"    答：{pa}")
        return "\n".join(lines)
    except Exception as e:
        return f"读取日志失败：{str(e)[:100]}"


# ============================================================
# 工具: layer_control — 统一图层控制
# ============================================================

@tool
def layer_control(action: str, name: str = "", new_name: str = "", color: str = "") -> str:
    """控制地图上的图层。action 参数：remove(删除) toggle(显隐) set_color(改色+color) rename(重命名+new_name) fit(缩放至图层)。"""
    if action == "remove":
        _pending_layer_ops.append({"action": "remove", "name": name})
        return f"已标记移除图层: {name}"
    elif action == "toggle":
        _pending_layer_ops.append({"action": "toggle", "name": name})
        return f"已标记切换图层显隐: {name}"
    elif action == "set_color":
        _pending_layer_ops.append({"action": "set_color", "name": name, "color": color})
        return f"已标记修改图层颜色: {name} → {color}"
    elif action == "rename":
        _pending_layer_ops.append({"action": "rename", "name": name, "new_name": new_name})
        return f"已标记重命名图层: {name} → {new_name}"
    elif action == "fit":
        _pending_layer_ops.append({"action": "fit", "name": name})
        return f"已标记缩放到图层: {name}"
    else:
        return f"未知操作: {action}，可选：remove / toggle / set_color / rename / fit"


# ============================================================
# 工具: export_layer — 导出图层
# ============================================================

@tool
def export_layer(layer_name: str, format: str = "geojson") -> str:
    """导出指定图层为 GeoJSON 或 Shapefile 格式。format 可选 geojson 或 shp。导出结果提供下载链接给用户"""
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

    geojson = info.get("geojson", {})

    if format == "geojson":
        # 直接保存 GeoJSON
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        fname = f"{layer_name}_{ts}.geojson"
        init_temp_dir()
        path = os.path.join(_temp_output_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)
        return f"GeoJSON 已生成：可通过 /output/{fname} 下载\n如需要 Shapefile 格式，可再次调用 export_layer 并设 format='shp'"

    elif format == "shp":
        # 用 geopandas 转 Shapefile 并打包 zip
        try:
            import geopandas as gpd
            import tempfile, zipfile, shutil
            import datetime

            gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
            if gdf.empty:
                return "图层为空，无法导出"

            # 字段名截断
            rename_map = {}
            for col in gdf.columns:
                if col != "geometry" and len(col) > 10:
                    new_name = col[:10]
                    suffix = 1
                    while new_name in rename_map.values() or new_name == "geometry":
                        new_name = col[:8] + str(suffix)
                        suffix += 1
                    rename_map[col] = new_name
            if rename_map:
                gdf = gdf.rename(columns=rename_map)

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            safe_name = layer_name.replace(" ", "_")
            fname = f"{safe_name}_{ts}.zip"

            tmp_dir = tempfile.mkdtemp(prefix="shp_export_")
            shp_base = os.path.join(tmp_dir, safe_name)
            gdf.to_file(shp_base, driver="ESRI Shapefile", encoding="utf-8")

            init_temp_dir()
            zip_path = os.path.join(_temp_output_dir, fname)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fn in os.listdir(tmp_dir):
                    fp = os.path.join(tmp_dir, fn)
                    if os.path.isfile(fp):
                        zf.write(fp, fn)
            shutil.rmtree(tmp_dir, ignore_errors=True)

            return f"Shapefile 已生成：可通过 /output/{fname} 下载（包含 .shp .shx .dbf .prj .cpg）"
        except Exception as e:
            return f"SHP 导出失败: {str(e)[:200]}"

    return f"不支持的格式: {format}，可选 geojson 或 shp"


# ============================================================
# 工具: create_chart — 统计图表
# ============================================================

@tool
def create_chart(layer_name: str, chart_type: str = "bar", field: str = "",
                 x_field: str = "", y_field: str = "", title: str = "") -> str:
    """从图层属性数据生成 ECharts 统计图表。用户要看统计图表/分布时优先用本工具。
    chart_type 可选: bar(柱状图) pie(饼图) histogram(直方图) scatter(散点图) line(折线图)
    单字段统计传 field，双字段对比传 x_field+y_field。"""
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

    try:
        import numpy as np
        features = info["geojson"].get("features", [])
        if not features:
            return "图层没有要素"

        props_list = [f.get("properties", {}) for f in features]
        prop_keys = set()
        for p in props_list:
            prop_keys.update(p.keys())
        prop_keys = sorted(prop_keys)

        if not prop_keys:
            return "图层没有属性字段"

        chart_title = title or f"{layer_name} - {chart_type}图"
        now_ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        # 分类统计（唯一值计数）
        def _value_counts(key):
            from collections import Counter
            vals = []
            for p in props_list:
                v = p.get(key)
                if v is not None and v != "":
                    try:
                        vals.append(float(v))
                    except (ValueError, TypeError):
                        vals.append(str(v))
            return Counter(vals)

        # 生成 ECharts HTML
        echarts_html = ""
        if chart_type == "histogram":
            # 直方图：统计数值字段分布
            f = field or prop_keys[0]
            counter = _value_counts(f)
            items = sorted([(k, v) for k, v in counter.items() if isinstance(k, (int, float))])
            if not items:
                # 尝试作为分类数据
                items = list(counter.items())
            if not items:
                return f"字段「{f}」无有效数值数据"
            values = [v for _, v in items]
            labels = [str(k) for k, _ in items]
            echarts_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script></head><body><div id="chart" style="width:100%;height:400px;"></div><script>
var chart = echarts.init(document.getElementById('chart'), null, {{renderer:'svg'}});
chart.setOption({{
    title: {{text:'{chart_title}', left:'center', textStyle:{{fontSize:14}}}},
    tooltip: {{trigger:'axis'}},
    xAxis: {{type:'category', data:{json.dumps(labels)}, axisLabel:{{rotate:45,fontSize:11}}}},
    yAxis: {{type:'value'}},
    series: [{{type:'bar', data:{json.dumps(values)}, itemStyle:{{color:'#1c1b1b'}}}}]
}});
window.addEventListener('resize', function(){{chart.resize();}});
</script></body></html>"""

        elif chart_type == "pie":
            f = field or prop_keys[0]
            counter = _value_counts(f)
            items = list(counter.items())
            if not items:
                return f"字段「{f}」无有效数据"
            items = sorted(items, key=lambda x: x[1], reverse=True)[:20]
            pie_data = [{"name": str(k), "value": v} for k, v in items]
            echarts_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script></head><body><div id="chart" style="width:100%;height:400px;"></div><script>
var chart = echarts.init(document.getElementById('chart'), null, {{renderer:'svg'}});
chart.setOption({{
    title: {{text:'{chart_title}', left:'center', textStyle:{{fontSize:14}}}},
    tooltip: {{trigger:'item', formatter:'{{b}}: {{c}} ({{d}}%)'}},
    series: [{{type:'pie', radius:'60%', center:['50%','55%'],
        data:{json.dumps(pie_data, ensure_ascii=False)},
        label:{{fontSize:11}},
        itemStyle:{{borderRadius:4}}
    }}]
}});
window.addEventListener('resize', function(){{chart.resize();}});
</script></body></html>"""

        elif chart_type == "scatter":
            xf = x_field or prop_keys[0]
            yf = y_field or (prop_keys[1] if len(prop_keys) > 1 else prop_keys[0])
            scatter_data = []
            for p in props_list:
                try:
                    xv = float(p.get(xf, 0))
                    yv = float(p.get(yf, 0))
                    scatter_data.append([xv, yv])
                except (ValueError, TypeError):
                    pass
            if not scatter_data:
                return f"字段「{xf}」和「{yf}」无有效数值数据"
            echarts_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script></head><body><div id="chart" style="width:100%;height:400px;"></div><script>
var chart = echarts.init(document.getElementById('chart'), null, {{renderer:'svg'}});
chart.setOption({{
    title: {{text:'{chart_title}', left:'center', textStyle:{{fontSize:14}}}},
    tooltip: {{trigger:'item', formatter:'[{xf}]: {{c[0]}}<br/>[{yf}]: {{c[1]}}'}},
    xAxis: {{type:'value', name:'{xf}'}},
    yAxis: {{type:'value', name:'{yf}'}},
    series: [{{type:'scatter', data:{json.dumps(scatter_data)},
        symbolSize:8, itemStyle:{{color:'#1c1b1b',opacity:0.7}}}}]
}});
window.addEventListener('resize', function(){{chart.resize();}});
</script></body></html>"""

        else:
            # bar / line：默认柱状图或折线图
            f = field or prop_keys[0]
            if x_field and y_field:
                # 双字段
                xf, yf = x_field, y_field
                bar_data = []
                bar_labels = []
                for p in props_list:
                    try:
                        bar_labels.append(str(p.get(xf, "")))
                        bar_data.append(float(p.get(yf, 0)))
                    except (ValueError, TypeError):
                        pass
                series_type = "line" if chart_type == "line" else "bar"
                echarts_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script></head><body><div id="chart" style="width:100%;height:400px;"></div><script>
var chart = echarts.init(document.getElementById('chart'), null, {{renderer:'svg'}});
chart.setOption({{
    title: {{text:'{chart_title}', left:'center', textStyle:{{fontSize:14}}}},
    tooltip: {{trigger:'axis'}},
    xAxis: {{type:'category', data:{json.dumps(bar_labels)}, axisLabel:{{rotate:45,fontSize:11}}}},
    yAxis: {{type:'value', name:'{yf}'}},
    series: [{{type:'{series_type}', data:{json.dumps(bar_data)}, itemStyle:{{color:'#1c1b1b'}}}}]
}});
window.addEventListener('resize', function(){{chart.resize();}});
</script></body></html>"""
            else:
                # 单字段统计
                counter = _value_counts(f)
                items = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:30]
                if not items:
                    return f"字段「{f}」无有效数据"
                labels = [str(k) for k, _ in items]
                values = [v for _, v in items]
                series_type = "line" if chart_type == "line" else "bar"
                echarts_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script></head><body><div id="chart" style="width:100%;height:400px;"></div><script>
var chart = echarts.init(document.getElementById('chart'), null, {{renderer:'svg'}});
chart.setOption({{
    title: {{text:'{chart_title}', left:'center', textStyle:{{fontSize:14}}}},
    tooltip: {{trigger:'axis'}},
    xAxis: {{type:'category', data:{json.dumps(labels)}, axisLabel:{{rotate:45,fontSize:11}}}},
    yAxis: {{type:'value'}},
    series: [{{type:'{series_type}', data:{json.dumps(values)}, itemStyle:{{color:'#1c1b1b'}}}}]
}});
window.addEventListener('resize', function(){{chart.resize();}});
</script></body></html>"""

        if not echarts_html:
            return "图表生成失败"

        # 注入 SVG 导出按钮
        svg_export_script = """
<style>
.chart-toolbar{position:fixed;top:8px;right:8px;display:flex;gap:4px;z-index:100}
.chart-toolbar button{padding:4px 10px;font-size:12px;background:rgba(0,0,0,0.7);border:none;border-radius:4px;cursor:pointer;color:#fff}
.chart-toolbar button:hover{background:rgba(0,0,0,0.9)}
</style>
<div class="chart-toolbar">
<button onclick="downloadSVG()">导出 SVG</button>
</div>
<script>
function downloadSVG(){var svg=document.querySelector('#chart svg');if(!svg){alert('SVG not found');return}
var s=new XMLSerializer();var str='<?xml version="1.0" encoding="utf-8"?>'+s.serializeToString(svg)
var blob=new Blob([str],{type:'image/svg+xml;charset=utf-8'})
var url=URL.createObjectURL(blob);var a=document.createElement('a');a.href=url;a.download='chart.svg';a.click();URL.revokeObjectURL(url)}
</script>"""
        echarts_html = echarts_html.replace("</body></html>", svg_export_script + "</body></html>")

        # 保存 HTML 并推送到前端
        init_temp_dir()
        fname = f"chart_{now_ts}.html"
        fpath = os.path.join(_temp_output_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(echarts_html)

        _add_pending_item(f"/output/{fname}", fpath)
        return f"图表已生成：{chart_title}（{chart_type}图），可在聊天中查看"

    except Exception as e:
        import traceback
        return f"图表生成失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: download_road_network — 从 OSM 下载路网
# ============================================================

@tool
def download_road_network(location_name: str, network_type: str = "drive") -> str:
    """从 OpenStreetMap 下载指定城市/区域的路网数据并加载到地图，供 network_analysis 使用。
location_name: 城市名（如"北京市""广州市""上海浦东新区"），或"经度,纬度,经度,纬度"（bbox）。
network_type: drive(车行路) walk(步行) bike(骑行) all(全部)，默认 drive。"""
    try:
        import osmnx as ox
    except ImportError:
        return "osmnx 未安装，请执行 pip install osmnx"

    try:
        import concurrent.futures

        ox.settings.log_console = False
        ox.settings.use_cache = True

        parts = [p.strip() for p in location_name.split(",")]
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _fetch():
            if len(parts) == 4:
                min_lng, min_lat, max_lng, max_lat = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                return ox.graph_from_bbox(north=max_lat, south=min_lat, east=max_lng, west=min_lng, network_type=network_type)
            else:
                return ox.graph_from_place(location_name, network_type=network_type)

        fut = executor.submit(_fetch)
        try:
            G = fut.result(timeout=120)
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False)
            return (
                f"下载「{location_name}」路网超时（120秒），OSM 服务器无响应。\n\n"
                f"请尝试以下替代方案：\n"
                f"1. 前往 https://www.geofabrik.de 下载对应地区 .osm.pbf 文件（国内可访问）\n"
                f"2. 前往 https://extract.bbbike.org 用矩形框选区域导出 .osm（支持国内访问）\n"
                f"3. 将下载的文件上传到 GIS WorkTable，AI 会自动识别为路网图层\n"
                f"4. 上传后告诉我，我再调用 network_analysis 分析"
            )

        nodes, edges = ox.graph_to_gdfs(G)
        if edges.empty:
            return f"未找到「{location_name}」的路网数据"

        geojson = edges.__geo_interface__
        layer_name = f"{location_name}_路网({network_type})"
        _push_layer(layer_name, geojson, {"color": "#555", "weight": 1.5})
        _register_layer(layer_name, geojson)

        node_count = len(nodes)
        edge_count = len(edges)
        bbox = _compute_bbox(geojson)
        extent = _format_extent(bbox)
        return (
            f"已从 OSM 下载「{location_name}」路网（{network_type}），"
            f"共 {node_count} 个节点、{edge_count} 条道路，{extent}。"
            f"图层名「{layer_name}」，已加载到地图。"
            f"接下来可以用 network_analysis 工具分析此路网。"
        )
    except Exception as e:
        import traceback
        return f"下载路网失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: network_analysis — 网络分析
# ============================================================

@tool
def network_analysis(
    layer_name: str = "",
    analysis_type: str = "",
    origin: str = "",
    destination: str = "",
    facility: str = "",
    events: str = "",
    breaks: str = "",
    n: int = 3,
) -> str:
    """从路网图层做网络分析。analysis_type: route(最短路径) service_area(服务区) closest_facility(最近设施)。
origin/destination/facility 用"经度,纬度"传坐标。events 传分号分隔坐标，breaks 传逗号分隔米数。

完整工作流（按顺序）：
1. 用户给地名（如"北京西站到天安门最短路径"）→ 先调 amap_geocode 把地名转成坐标
2. 如果还没有路网图层 → 调 download_road_network 下载
3. 如果不确定用哪个路网 → 调 get_registered_layers 查看各图层覆盖范围
4. 用本工具（network_analysis）做分析
5. 分析结果已自动加载到地图（图层），无需额外操作

注意：坐标用"经度,纬度"格式（先经度后纬度）。
重要：必须用本工具做网络分析，严禁用 execute_python 调高德 API 做路径规划。"""
    from backend.services.network_service import (
        build_graph_from_geojson, shortest_route,
        service_area, closest_facilities,
    )

    # 收集分析所需的坐标，用于图层匹配
    need_coords = []
    if origin:
        need_coords.append(_parse_coord(origin))
    if destination:
        need_coords.append(_parse_coord(destination))
    if facility:
        need_coords.append(_parse_coord(facility))

    # 根据坐标自动匹配图层
    if not layer_name:
        for c in need_coords:
            matched = _find_layer_for_coord(c[0], c[1])
            if matched:
                layer_name = matched
                break
        if not layer_name:
            return "请先通过 get_registered_layers 查看已加载的路网图层，再指定正确的 layer_name"

    info = _registered_layers.get(layer_name)
    if not info:
        matches = [n for n in _registered_layers.keys() if layer_name in n] if layer_name else []
        if len(matches) == 1:
            info = _registered_layers[matches[0]]
            layer_name = matches[0]
        elif len(matches) > 1:
            return f"找到多个匹配：{', '.join(matches)}，请指定完整名称"
        elif not _registered_layers:
            return "当前没有已加载的图层，请先上传路网数据"
        else:
            return f"未找到图层「{layer_name}」，当前图层：{', '.join(_registered_layers.keys()) or '无'}"

    geojson = info.get("geojson", {})
    if not geojson:
        return f"图层「{layer_name}」数据为空"

    # 校验坐标是否在图层范围内
    layer_bbox = info.get("bbox", [])
    for c in need_coords:
        if not _point_in_bbox(c[0], c[1], layer_bbox):
            alt = _find_layer_for_coord(c[0], c[1])
            if alt:
                return (f"坐标 ({c[0]:.4f}, {c[1]:.4f}) 不在图层「{layer_name}」范围内，"
                        f"但匹配到图层「{alt}」。请将 layer_name 设为「{alt}」后重试")
            return (f"坐标 ({c[0]:.4f}, {c[1]:.4f}) 不在图层「{layer_name}」范围内，"
                    f"当前图层的覆盖范围为 {_format_extent(layer_bbox)}。请确认使用的是正确的路网图层")

    try:
        if analysis_type == "route":
            if not origin or not destination:
                return "路线分析需要 origin 和 destination 参数"
            o = _parse_coord(origin)
            d = _parse_coord(destination)
            result = shortest_route(geojson, o, d)
            if "error" in result:
                return f"路径分析失败: {result['error']}"
            _push_layer(f"路径_{layer_name}", {
                "type": "FeatureCollection",
                "features": [result["path"]],
            })
            return (
                f"路径分析完成：总距离 {result['distance_km']} km，"
                f"{result['node_count']} 个途经节点，已加载到地图"
            )

        elif analysis_type == "service_area":
            if not facility:
                return "服务区分析需要 facility 参数"
            f = _parse_coord(facility)
            breaks_list = [int(b.strip()) for b in breaks.split(",")] if breaks else [1000, 3000, 5000]
            result = service_area(geojson, f, breaks_list)
            if "error" in result:
                return f"服务区分析失败: {result['error']}"
            _push_layer(f"服务区_{layer_name}", result["polygons"])
            area_str = "；".join(f"{a['break']}m:{a['area_km2']}km²" for a in result["areas"])
            return f"服务区分析完成：{area_str}，已加载到地图"

        elif analysis_type == "closest_facility":
            if not origin:
                return "最近设施分析需要 origin（事件点）和已注册的设施图层"
            o = _parse_coord(origin)
            fac_list = [_parse_coord(e.strip()) for e in events.split(";")] if events else []
            if not fac_list:
                return "请通过 events 参数提供设施点坐标（分号分隔）"
            result = closest_facilities(geojson, o, fac_list, n)
            if "error" in result:
                return f"最近设施分析失败: {result['error']}"
            _push_layer(f"最近设施_{layer_name}", {
                "type": "FeatureCollection",
                "features": result["paths"],
            })
            lines = [f"最近设施分析完成（前 {len(result['summary'])} 条）："]
            for s in result["summary"]:
                lines.append(f"  #{s['rank']} 设施{s['facility_idx']}：{s['distance_km']} km")
            return "\n".join(lines)

        else:
            return f"不支持的分析类型：{analysis_type}，可选：route / service_area / closest_facility"

    except Exception as e:
        import traceback
        return f"网络分析异常: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


def _point_in_bbox(lng: float, lat: float, bbox: list) -> bool:
    """判断坐标是否在 bbox [minLng, minLat, maxLng, maxLat] 内"""
    if not bbox or len(bbox) < 4:
        return False
    return bbox[0] <= lng <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _find_layer_for_coord(lng: float, lat: float) -> str:
    """在所有已注册图层中找到包含该坐标的图层名，返回第一个匹配"""
    for name, info in _registered_layers.items():
        bbox = info.get("bbox", [])
        if _point_in_bbox(lng, lat, bbox):
            return name
    return ""


def _parse_coord(s: str) -> tuple:
    """解析 "经度,纬度" 字符串"""
    parts = s.split(",")
    return float(parts[0].strip()), float(parts[1].strip())


# ============================================================
# 工具列表（供 LangGraph Agent 注册）
# ============================================================

tools = [
    search_web,
    fetch_webpage,
    scrape_page,
    search_platform,
    save_file,
    execute_python,
    amap_poi_search,
    amap_geocode,
    unified_aoi_search,
    unified_aoi_extract,
    get_registered_layers,
    get_layer_detail,
    datav_boundary,
    create_heatmap,
    field_calculate,
    measure_area,
    clear_layers,
    get_session_logs,
    layer_control,
    export_layer,
    create_chart,
    download_road_network,
    network_analysis,
]

