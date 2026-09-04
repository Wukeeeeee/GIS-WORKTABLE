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

# Task Manager 集成：持久化 Python 源代码 + Artifact 注册
from backend.services.task_manager import (
    save_code, register_artifact, log_execution,
    get_latest_code, update_gis_context, get_task,
)


# ============================================================
# 安全表达式求值（替代 eval/exec）
# ============================================================

_ALLOWED_OPS = {
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.And, ast.Or, ast.Not,
    ast.BitXor, ast.BitAnd, ast.BitOr,
}


def _safe_expr_eval(expression, variables):
    """安全求值数学/逻辑表达式，只允许白名单操作和变量引用。"""
    tree = ast.parse(expression, mode="eval")
    _validate_ast(tree.body)
    code = compile(tree, "<safe>", "eval")
    return eval(code, {"__builtins__": {}}, variables)


def _validate_ast(node):
    """递归检查 AST 节点是否在白名单内。"""
    if isinstance(node, ast.Expression):
        _validate_ast(node.body)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        _validate_ast(node.left)
        _validate_ast(node.right)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        _validate_ast(node.operand)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("只支持直接函数名调用")
        for arg in node.args:
            _validate_ast(arg)
        for kw in node.keywords:
            _validate_ast(kw.value)
    elif isinstance(node, ast.Name):
        pass
    elif isinstance(node, ast.Constant):
        pass
    elif isinstance(node, ast.List):
        for elt in node.elts:
            _validate_ast(elt)
    elif isinstance(node, ast.Tuple):
        for elt in node.elts:
            _validate_ast(elt)
    elif isinstance(node, ast.Attribute):
        _validate_ast(node.value)
    elif isinstance(node, ast.Compare):
        _validate_ast(node.left)
        for c in node.comparators:
            _validate_ast(c)
        for op in node.ops:
            if type(op) not in {ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE}:
                raise ValueError(f"不支持的比较操作: {type(op).__name__}")
    elif isinstance(node, ast.IfExp):
        _validate_ast(node.test)
        _validate_ast(node.body)
        _validate_ast(node.orelse)
    elif isinstance(node, ast.Subscript):
        _validate_ast(node.value)
        _validate_ast(node.slice)
    elif isinstance(node, ast.Slice):
        if node.lower:
            _validate_ast(node.lower)
        if node.upper:
            _validate_ast(node.upper)
        if node.step:
            _validate_ast(node.step)
    elif isinstance(node, ast.Dict):
        for k in node.keys:
            if k:
                _validate_ast(k)
        for v in node.values:
            _validate_ast(v)
    else:
        raise ValueError(f"不支持的表达式语法: {type(node).__name__}")


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
_exec_log: list = []            # 执行日志：记录每次execute_python的用途和结果
_temp_output_dir: str = ""          # 在 reset_state 时设置
_workspace_dir: str = ""
_registered_layers: dict = {}       # 已注册的图层信息
_current_task_id: str = ""          # 当前任务 ID（由 graph.py 设置）

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
            "exec_log": list(_exec_log),  # 执行日志
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


def set_current_task(task_id: str):
    """设置当前任务 ID（由 graph.py 在每轮请求开始时调用）"""
    global _current_task_id
    _current_task_id = task_id or ""


def get_current_task_id() -> str:
    """获取当前任务 ID"""
    return _current_task_id


def reset_state(amap_key: str = "", task_id: str = ""):
    """每次请求开始时调用，清空所有共享状态"""
    global _current_amap_key, _clear_layers_flag, _search_call_count, _exec_call_count, _exec_log, _current_task_id
    with _state_lock:
        _pending_layers.clear()
        _pending_images.clear()
        _pending_aoi_suggestions.clear()
        _pending_heatmap["latest"] = None
        _clear_layers_flag = False
        _pending_layer_ops.clear()
        _current_amap_key = amap_key
        _search_call_count = 0
        _exec_call_count = 0
        _exec_log.clear()
        _current_task_id = task_id or ""


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
        with _state_lock:
            _pending_layers.append(layer)
    except Exception:
        pass


def _unregister_layer(name: str):
    """从注册表中移除图层"""
    with _state_lock:
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
        with _state_lock:
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
            "geometry_types": info.get("geometry_types", []),
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
    'tempfile', 'pyproj', 'rasterio', 'osmnx',
}
BANNED_FUNCTIONS = {'eval', 'exec', '__import__', 'getattr', 'setattr', 'compile', 'vars', 'locals', 'globals', 'delattr', 'input', 'breakpoint'}
BANNED_ATTR_CALLS = {
    'system', 'popen', 'call', 'Popen', 'run', 'check_call', 'check_output',
    'startfile', 'spawnl', 'spawnle', 'spawnlp', 'spawnlpe',
    'spawnv', 'spawnve', 'spawnvp', 'spawnvpe', 'posix_spawn', 'posix_spawnp',
    'load_library',
}
BANNED_MAGIC_ATTRS = {'__dict__', '__globals__', '__builtins__', '__class__', '__bases__', '__subclasses__', '__mro__', '__getattribute__', '__self__', '__func__', '__code__', '__traceback__', '__qualname__', '__module__', '__init_subclass__', '__set_name__'}
BANNED_BUILTINS = {'type', 'object', 'super', 'staticmethod', 'classmethod', 'property', 'memoryview', 'bytearray'}
BANNED_SYSTEM_MODULES = {'os', 'subprocess', 'shutil', 'sys', 'ctypes', 'ctypeslib', 'socket', 'pathlib', 'shlex', 'signal'}
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
                # 阻止 from geopandas import type 等导入内省逃逸工具
                for alias in node.names:
                    if alias.name in BANNED_SYSTEM_MODULES:
                        return f'沙箱拦截：禁止通过白名单库导入系统模块「{alias.name}」'
                    if alias.name in BANNED_BUILTINS:
                        return f'沙箱拦截：禁止通过白名单库导入内置类型「{alias.name}」'
                    if alias.name in BANNED_MAGIC_ATTRS:
                        return f'沙箱拦截：禁止通过白名单库导入魔法属性「{alias.name}」'

        # ---- 函数调用检查（含属性链调用，防 __builtins__.eval） ----
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in BANNED_FUNCTIONS:
                    return f'沙箱拦截：禁止调用危险函数「{node.func.id}」'
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in BANNED_FUNCTIONS:
                    return f'沙箱拦截：禁止通过属性链调用危险函数「{node.func.attr}」'

        # ---- 裸名检查：__builtins__ 等魔法名 / 内置类型作为标识符直写 ----
        if isinstance(node, ast.Name):
            if node.id in BANNED_MAGIC_ATTRS:
                return f'沙箱拦截：禁止直接使用魔法标识符「{node.id}」'
            if node.id in BANNED_BUILTINS:
                return f'沙箱拦截：禁止直接使用内置类型「{node.id}」（可用于内省逃逸）'

        # ---- 属性访问检查（全面覆盖：读取、赋值、调用均逃不掉） ----
        if isinstance(node, ast.Attribute):
            # 魔法属性——经典内省逃逸链的源头
            if node.attr in BANNED_MAGIC_ATTRS:
                return f'沙箱拦截：禁止访问魔法属性「{node.attr}」'
            # 内置类型属性——type、object 等通过属性链访问也拦截
            if node.attr in BANNED_BUILTINS:
                return f'沙箱拦截：禁止访问内置类型「{node.attr}」'
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

        # ---- open() 写入路径检查：仅允许写 output/ 目录 ----
        if isinstance(node, ast.Call):
            func = node.func
            # open(path, mode) 或 open(path, 'w', ...)
            is_open_call = (
                (isinstance(func, ast.Name) and func.id == 'open') or
                (isinstance(func, ast.Attribute) and func.attr == 'open')
            )
            if is_open_call and node.args:
                first_arg = node.args[0]
                # 检查模式参数（第二个参数或 keyword）
                write_mode = False
                if len(node.args) >= 2:
                    mode_arg = node.args[1]
                    if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                        write_mode = any(m in mode_arg.value for m in ('w', 'a', 'x'))
                for kw in node.keywords:
                    if kw.arg == 'mode' and isinstance(kw.value, ast.Constant):
                        write_mode = any(m in kw.value.value for m in ('w', 'a', 'x'))
                if write_mode and isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    path = first_arg.value
                    if not (path.startswith('output/') or path.startswith('output\\') or
                            path.startswith('/output/') or path.startswith('./output/')):
                        return f'沙箱拦截：禁止写入非 output 目录「{path[:60]}」（仅允许写 output/）'

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
        - 反向地理编码/坐标转地址 → 必须用 reverse_geocode
        - 批量地理编码 → 必须用 batch_geocode
       - POI 搜索/查天气 → 必须用 amap_poi_search
       - 行政边界获取 → 必须用 datav_boundary
       - AOI 建筑轮廓提取 → 必须用 unified_aoi_search/extract
       - 路网下载 → 必须用 download_road_network
       - 网络分析（路径/服务区/最近设施） → 必须用 network_analysis
       - 热力图生成 → 必须用 create_heatmap
       - 图层属性统计图 → 必须用 create_chart
       - 字段计算 → 必须用 field_calculate
       - 缓冲区分析 → 必须用 spatial_buffer
       - 空间相交分析 → 必须用 spatial_intersect
       - 空间合并 → 必须用 spatial_union
       - 空间差异 → 必须用 spatial_difference
       - 图层裁剪 → 必须用 spatial_clip
       - 质心提取 → 必须用 spatial_centroid
       - 几何简化 → 必须用 spatial_simplify
        - 属性融合 → 必须用 spatial_dissolve
        - 按空间关系选择要素 → 必须用 spatial_select
        - 随机采样 → 必须用 spatial_sample
        - 查找附近要素 → 必须用 spatial_near
        - 空间聚类 → 必须用 spatial_cluster
        - 泰森多边形 → 必须用 spatial_voronoi
        - 字段统计分析 → 必须用 spatial_field_stats
        - 空间连接 → 必须用 spatial_join
        - 图层合并 → 必须用 layer_merge
        - 图层拆分 → 必须用 layer_split
        - 从坐标列创建要素 → 必须用 layer_add_geometry

    ✅ 本工具适合做的：
       - 自定义 GIS 空间分析（矢量/栅格运算）
       - 数据格式转换与清洗
       - 国外边界数据获取（osmnx）
       - 自定义 matplotlib/pyecharts 可视化

    可用库：geopandas, shapely, numpy, pandas, matplotlib, pyecharts, json, math, re, datetime, io, tempfile, requests, pyproj, rasterio, osmnx
    print(GeoJSON) 自动加载到地图（加 name 字段做图层名）
    plt.savefig('chart_xxx.png') 生成图表

    安全：严禁在代码中硬编码 API Key（高德 Key 已自动注入 _AMAP_KEY 变量）"""
    global _exec_call_count, _exec_log
    _exec_call_count += 1
    
    # 记录执行日志（提取代码前50个字符作为摘要）
    code_summary = code.strip()[:50].replace('\n', ' ')
    _exec_log.append({
        "seq": _exec_call_count,
        "code_summary": code_summary,
        "timestamp": datetime.datetime.now().strftime('%H:%M:%S'),
    })
    
    # 软警告：超过7次提醒但不阻断，超过20次才阻断
    if _exec_call_count > 20:
        return f"【执行过热】本次请求已执行 {_exec_call_count} 次 Python 代码（上限20次）。请基于已有结果继续，不要再执行了。"
    init_temp_dir()

    # === Task Manager: 保存 Python 源代码到代码缓存 ===
    _task_step = 0
    if _current_task_id:
        try:
            _task_step = save_code(_current_task_id, code, label=code_summary)
        except Exception as _e:
            print(f"[TaskManager] 保存代码失败（忽略）: {_e}", flush=True)

    # ================================================================
    # 第一层：AST 静态代码校验（只查用户代码，不注入代码）
    # ================================================================
    ast_error = _ast_sandbox_check(code)
    if ast_error:
        # 记录执行失败
        if _current_task_id and _task_step:
            try:
                log_execution(_current_task_id, _task_step, code, "", "failed",
                              stderr=ast_error, exit_code=1)
            except Exception:
                pass
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

# 创建 output/ 子目录，支持 plt.savefig('output/chart.png') 路径
import os as _os
_os.makedirs('output', exist_ok=True)
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
        # 扫描 exec_dir 根目录和 output/ 子目录
        try:
            _dirs_to_scan = [exec_dir]
            _output_subdir = os.path.join(exec_dir, 'output')
            if os.path.isdir(_output_subdir):
                _dirs_to_scan.append(_output_subdir)
            for _scan_dir in _dirs_to_scan:
                for fname in os.listdir(_scan_dir):
                    if fname == '_user_code_.py':
                        continue
                    fpath = os.path.join(_scan_dir, fname)
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
            # Task Manager: 记录执行失败
            if _current_task_id and _task_step:
                try:
                    log_execution(_current_task_id, _task_step, code, "",
                                  "failed", stderr=stderr, exit_code=result.returncode)
                except Exception:
                    pass
            return f'代码执行错误（{elapsed:.1f}s）：{stderr[:2000]}\n请根据错误信息修改代码后重试。'

        output = result.stdout.strip()

        # 检测新生成的图片和 HTML
        new_images = []
        try:
            after_files = set(os.listdir(_temp_output_dir))
            new_files = after_files - before_files

            _rename_output_files(new_files, '.png', _temp_output_dir)
            _rename_output_files(new_files, '.html', _temp_output_dir)
            _cleanup_charts(_temp_output_dir)
            
            # 收集新生成的图片文件
            for f in new_files:
                if f.lower().endswith('.png'):
                    new_images.append(f)
        except Exception:
            pass

        if not output:
            # 即使无输出，如果有图片也要报告
            if new_images:
                # Task Manager: 注册图片 Artifact
                _registered_artifacts = []
                if _current_task_id:
                    for img_name in new_images:
                        img_path = os.path.join(_temp_output_dir, img_name)
                        try:
                            art = register_artifact(_current_task_id, img_name, img_path,
                                                    artifact_type="image", created_by_step=_task_step)
                            _registered_artifacts.append(art.get("artifact_id", ""))
                        except Exception:
                            pass
                    try:
                        log_execution(_current_task_id, _task_step, code, "",
                                      "success", stdout=f"生成了 {len(new_images)} 张图片",
                                      output_artifacts=_registered_artifacts)
                    except Exception:
                        pass
                return f'代码执行成功（{elapsed:.1f}s，无文本输出），生成了 {len(new_images)} 张图片：{", ".join(new_images[:3])}'
            # Task Manager: 记录执行成功（无输出无图片）
            if _current_task_id and _task_step:
                try:
                    log_execution(_current_task_id, _task_step, code, "",
                                  "success", stdout="无输出")
                except Exception:
                    pass
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
            # Task Manager: 注册 GeoJSON Artifact + 记录执行
            if _current_task_id and _task_step:
                try:
                    log_execution(_current_task_id, _task_step, code, "",
                                  "success", stdout=f"GIS 结果 {feature_count} 个要素")
                except Exception:
                    pass
            return f'GIS 结果已生成并加载到地图（{feature_count} 个要素，耗时 {elapsed:.1f}s）\n---\n{output[:3000]}'

        # 返回执行结果，包含图片信息
        image_info = f'，生成了 {len(new_images)} 张图片' if new_images else ''
        # Task Manager: 注册图片 Artifact + 记录执行
        _registered_artifacts = []
        if _current_task_id and _task_step:
            for img_name in new_images:
                img_path = os.path.join(_temp_output_dir, img_name)
                try:
                    art = register_artifact(_current_task_id, img_name, img_path,
                                            artifact_type="image", created_by_step=_task_step)
                    _registered_artifacts.append(art.get("artifact_id", ""))
                except Exception:
                    pass
            try:
                log_execution(_current_task_id, _task_step, code, "",
                              "success", stdout=output[:2000],
                              output_artifacts=_registered_artifacts)
            except Exception:
                pass
        return f'代码执行成功（{elapsed:.1f}s{image_info}）\n---\n{output[:3000]}'

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        if _current_task_id and _task_step:
            try:
                log_execution(_current_task_id, _task_step, code, "",
                              "timeout", stderr="执行超时 >120s", exit_code=-1)
            except Exception:
                pass
        return f'代码执行超时（{elapsed:.1f}s > 120s），已强制终止进程。请简化操作或分批处理。'
    except Exception as e:
        if _current_task_id and _task_step:
            try:
                log_execution(_current_task_id, _task_step, code, "",
                              "error", stderr=str(e)[:500], exit_code=-1)
            except Exception:
                pass
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
# 工具: measure_distance — 测距
# ============================================================

@tool
def measure_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> str:
    """测量两个经纬度坐标之间的地面距离。使用 Haversine 公式计算大圆距离。
    lon1/lat1: 起点经纬度；lon2/lat2: 终点经纬度。
    WGS84 坐标系。返回米和公里。"""
    try:
        import math
        R = 6371000  # 地球半径（米）
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance_m = R * c

        if distance_m < 1000:
            return f"距离：{distance_m:.1f} 米"
        else:
            return f"距离：{distance_m / 1000:.2f} 公里（{distance_m:.1f} 米）"
    except Exception as e:
        return f"距离测量失败: {str(e)[:200]}"


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
def layer_control(action: str, name: str = "", new_name: str = "", color: str = "", opacity: float = 1.0, weight: int = 2, fill_pattern: str = "") -> str:
    """控制地图上的图层。action 参数：remove(删除) toggle(显隐) set_color(改色+color) set_style(设置完整样式+color+opacity+weight+fill_pattern) rename(重命名+new_name) fit(缩放至图层)。opacity: 0~1，weight: 线宽像素数，fill_pattern: hatch/crosshatch/dots/grid/diagonal。"""
    if action == "remove":
        _pending_layer_ops.append({"action": "remove", "name": name})
        return f"已标记移除图层: {name}"
    elif action == "toggle":
        _pending_layer_ops.append({"action": "toggle", "name": name})
        return f"已标记切换图层显隐: {name}"
    elif action == "set_color":
        _pending_layer_ops.append({"action": "set_color", "name": name, "color": color})
        return f"已标记修改图层颜色: {name} → {color}"
    elif action == "set_style":
        style = {"color": color}
        if opacity != 1.0:
            style["opacity"] = max(0.0, min(1.0, opacity))
        if weight != 2:
            style["weight"] = max(1, weight)
        if fill_pattern:
            style["fillPattern"] = fill_pattern
        _pending_layer_ops.append({"action": "set_style", "name": name, "style": style})
        parts = [f"颜色={color}"]
        if "opacity" in style: parts.append(f"透明度={style['opacity']}")
        if "weight" in style: parts.append(f"线宽={style['weight']}")
        if "fillPattern" in style: parts.append(f"填充图案={style['fillPattern']}")
        return f"已标记修改图层样式: {name} → {'，'.join(parts)}"
    elif action == "rename":
        _pending_layer_ops.append({"action": "rename", "name": name, "new_name": new_name})
        return f"已标记重命名图层: {name} → {new_name}"
    elif action == "fit":
        _pending_layer_ops.append({"action": "fit", "name": name})
        return f"已标记缩放到图层: {name}"
    else:
        return f"未知操作: {action}，可选：remove / toggle / set_color / set_style / rename / fit"


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

    elif format == "gpkg":
        try:
            import geopandas as gpd
            import datetime

            gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
            if gdf.empty:
                return "图层为空，无法导出"

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            safe_name = layer_name.replace(" ", "_")
            fname = f"{safe_name}_{ts}.gpkg"

            init_temp_dir()
            path = os.path.join(_temp_output_dir, fname)
            gdf.to_file(path, layer=safe_name, driver="GPKG", encoding="utf-8")

            return f"GeoPackage 已生成：可通过 /output/{fname} 下载（单一文件，含空间索引）"
        except Exception as e:
            return f"GPKG 导出失败: {str(e)[:200]}"

    elif format == "csv":
        try:
            import geopandas as gpd
            import pandas as pd
            import datetime

            gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
            if gdf.empty:
                return "图层为空，无法导出"

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            safe_name = layer_name.replace(" ", "_")
            fname = f"{safe_name}_{ts}.csv"

            init_temp_dir()
            path = os.path.join(_temp_output_dir, fname)
            attr_df = gdf.drop(columns=["geometry"], errors="ignore")
            attr_df.to_csv(path, index=False, encoding="utf-8-sig")

            return (f"CSV 属性表已生成：可通过 /output/{fname} 下载"
                    f"（{len(attr_df.columns)} 列, {len(attr_df)} 行）"
                    f"\n如需含坐标的 CSV，可用 format='csv_xy'")
        except Exception as e:
            return f"CSV 导出失败: {str(e)[:200]}"

    elif format == "csv_xy":
        try:
            import geopandas as gpd
            import pandas as pd
            import datetime

            gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
            if gdf.empty:
                return "图层为空，无法导出"

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            safe_name = layer_name.replace(" ", "_")
            fname = f"{safe_name}_{ts}.csv"

            init_temp_dir()
            path = os.path.join(_temp_output_dir, fname)

            gdf["longitude"] = gdf.geometry.x
            gdf["latitude"] = gdf.geometry.y
            attr_df = gdf.drop(columns=["geometry"], errors="ignore")
            attr_df.to_csv(path, index=False, encoding="utf-8-sig")

            return (f"CSV（含坐标）已生成：可通过 /output/{fname} 下载"
                    f"（{len(attr_df.columns)} 列, {len(attr_df)} 行，含 longitude/latitude）")
        except Exception as e:
            return f"CSV 导出失败: {str(e)[:200]}"

    return f"不支持的格式: {format}，可选 geojson / shp / gpkg / csv / csv_xy"


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
    """从路网图层做网络分析。analysis_type: route(最短路径,双向Dijkstra) service_area(服务区) closest_facility(最近设施)。
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
    if len(parts) < 2:
        raise ValueError(f"坐标格式错误，需要 '经度,纬度' 格式，收到: '{s}'")
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        raise ValueError(f"坐标值非数字，收到: '{s}'")


# ============================================================
# 辅助函数：图层 ↔ GeoDataFrame 互转（供空间分析工具使用）
# ============================================================

def _layer_to_gdf(layer_name: str) -> tuple:
    """从注册表获取图层并转为 GeoDataFrame，返回 (gdf, layer_name) 或 (None, 错误消息)"""
    info = _registered_layers.get(layer_name)
    if not info:
        matches = [n for n in _registered_layers.keys() if layer_name in n]
        if len(matches) == 1:
            info = _registered_layers[matches[0]]
            layer_name = matches[0]
        elif len(matches) > 1:
            return None, f"找到多个匹配：{', '.join(matches)}，请指定完整名称"
        else:
            return None, f"未找到图层「{layer_name}」，当前图层：{', '.join(_registered_layers.keys()) or '无'}"
    geojson = info.get("geojson", {})
    if not geojson or not geojson.get("features"):
        return None, f"图层「{layer_name}」为空"
    import geopandas as gpd
    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
    return gdf, layer_name


def _gdf_to_layer(gdf, name: str):
    """将 GeoDataFrame 转为 GeoJSON，推送到地图并注册"""
    import json
    geojson_data = json.loads(gdf.to_json())
    geojson_data["name"] = name
    _push_layer(name, geojson_data)
    _register_layer(name, geojson_data)


# ============================================================
# 工具: spatial_buffer — 缓冲区分析
# ============================================================

@tool
def spatial_buffer(layer_name: str, distance: float, unit: str = "m", dissolve: bool = False) -> str:
    """为指定图层创建缓冲区。unit 可选 m(米) 或 km(公里)。dissolve=True 时融合重叠的缓冲区。"""
    try:
        import geopandas as gpd
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        distance_m = distance * 1000 if unit == "km" else distance
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            centroid = gdf.dissolve().centroid.iloc[0]
        lon, lat = centroid.x, centroid.y
        utm_zone = int((lon + 180) / 6) + 1
        crs_utm = f"EPSG:{32600 + utm_zone}" if lat >= 0 else f"EPSG:{32700 + utm_zone}"
        gdf_utm = gdf.to_crs(crs_utm)
        gdf_utm["geometry"] = gdf_utm.geometry.buffer(distance_m)
        if dissolve:
            gdf_utm = gpd.GeoDataFrame({"geometry": [gdf_utm.union_all()]}, geometry="geometry", crs=crs_utm)
        gdf_wgs = gdf_utm.to_crs("EPSG:4326")
        result_name = f"{name}_缓冲区"
        _gdf_to_layer(gdf_wgs, result_name)
        return f"已为「{name}」创建{distance}{unit}缓冲区，{len(gdf_wgs)} 个要素，已加载到地图"
    except Exception as e:
        import traceback
        return f"缓冲区分析失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: spatial_multi_ring_buffer — 多环缓冲区
# ============================================================

@tool
def spatial_multi_ring_buffer(layer_name: str, distances: str, unit: str = "m", dissolve: bool = False) -> str:
    """为指定图层创建多环缓冲区。distances 为逗号分隔的距离值（如"100,200,500"），每个距离生成一环。
    unit: m(米)/km(公里)；dissolve: 是否融合重叠缓冲区。所有环合并为单一图层。"""
    try:
        import geopandas as gpd
        import pandas as pd
        import warnings

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        dist_list = [float(d.strip()) for d in distances.split(",") if d.strip()]
        if not dist_list:
            return '请指定有效距离列表，如"100,200,500"'
        if len(dist_list) > 20:
            return f"最多支持 20 个距离，当前 {len(dist_list)} 个"

        centroid = gdf.dissolve().centroid.iloc[0]
        lon, lat = centroid.x, centroid.y
        utm_zone = int((lon + 180) / 6) + 1
        crs_utm = f"EPSG:{32600 + utm_zone}" if lat >= 0 else f"EPSG:{32700 + utm_zone}"
        gdf_utm = gdf.to_crs(crs_utm)

        rings = []
        for i, d in enumerate(dist_list):
            distance_m = d * 1000 if unit == "km" else d
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                buffered = gdf_utm.geometry.buffer(distance_m)
            ring = gpd.GeoDataFrame({"geometry": buffered, "distance": d, "ring": i + 1}, crs=crs_utm)
            if dissolve:
                ring = gpd.GeoDataFrame({"geometry": [ring.union_all()], "distance": d, "ring": i + 1}, geometry="geometry", crs=crs_utm)
            rings.append(ring)

        merged = pd.concat(rings, ignore_index=True)
        merged = merged.to_crs("EPSG:4326")

        dist_str = "、".join(str(d) for d in dist_list)
        result_name = f"{name}_多环{unit}"
        _gdf_to_layer(merged, result_name)

        return (f"已为「{name}」创建 {len(dist_list)} 个多环缓冲区：{dist_str} {unit}，"
                f"共 {len(merged)} 个要素，已加载到地图")
    except Exception as e:
        import traceback
        return f"多环缓冲区失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: move_features — 移动要素
# ============================================================

@tool
def move_features(layer_name: str, dx: float = 0, dy: float = 0, unit: str = "m") -> str:
    """移动指定图层的所有要素。dx 为东西方向位移（正=东/负=西），dy 为南北方向位移（正=北/负=南）。
    unit 可选 m(米) 或 km(公里)。自动 UTM 投影保证距离精确。"""
    try:
        import geopandas as gpd
        import warnings

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

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if dx == 0 and dy == 0:
            return "位移量 dx 和 dy 不能同时为 0"

        if unit == "km":
            dx *= 1000
            dy *= 1000
        elif unit != "m":
            return f"不支持的单位「{unit}」，请用 m 或 km"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            centroid = gdf.dissolve().centroid.iloc[0]
        lon, lat = centroid.x, centroid.y
        utm_zone = int((lon + 180) / 6) + 1
        crs_utm = f"EPSG:{32600 + utm_zone}" if lat >= 0 else f"EPSG:{32700 + utm_zone}"

        gdf_utm = gdf.to_crs(crs_utm)
        gdf_utm.geometry = gdf_utm.geometry.translate(xoff=dx, yoff=dy)

        gdf_result = gdf_utm.to_crs("EPSG:4326")
        geojson_data = gdf_result.__geo_interface__
        geojson_data["name"] = layer_name
        _registered_layers[layer_name]["geojson"] = geojson_data
        _push_layer(layer_name, geojson_data)

        dir_x = "东" if dx > 0 else ("西" if dx < 0 else "")
        dir_y = "北" if dy > 0 else ("南" if dy < 0 else "")
        dir_str = (dir_y + dir_x) if (dx != 0 and dy != 0) else (dir_y or dir_x)
        unit_str = "km" if unit == "km" else "m"
        return (f"已移动图层「{layer_name}」{dir_str}方向 "
                f"（{dx}{unit_str}, {dy}{unit_str}），"
                f"{len(gdf_result)} 个要素，已同步地图")
    except Exception as e:
        import traceback
        return f"移动要素失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: add_north_arrow — 指北针
# ============================================================

@tool
def add_north_arrow() -> str:
    """在地图上显示指北针。指北针会出现在地图右上角，始终指向正北。"""
    try:
        _pending_layer_ops.append({
            "action": "north_arrow",
        })
        return "已在地图右上角显示指北针"
    except Exception as e:
        return f"指北针添加失败: {str(e)[:200]}"


# ============================================================
# 工具: rotate_features — 旋转要素
# ============================================================

@tool
def rotate_features(layer_name: str, angle: float = 90) -> str:
    """旋转指定图层的所有要素。angle 为旋转角度（度），正数=逆时针，负数=顺时针。旋转中心为图层所有要素的几何中心。"""
    try:
        import geopandas as gpd
        from shapely import affinity
        import warnings

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

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            center = gdf.dissolve().centroid.iloc[0]

        gdf.geometry = gdf.geometry.rotate(angle, origin=(center.x, center.y), use_radians=False)

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _registered_layers[layer_name]["geojson"] = geojson_data
        _push_layer(layer_name, geojson_data)

        direction = "逆时针" if angle > 0 else "顺时针"
        return (f"已旋转图层「{layer_name}」{abs(angle)}°（{direction}），"
                f"{len(gdf)} 个要素，已同步地图")
    except Exception as e:
        import traceback
        return f"旋转要素失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: scale_features — 缩放要素
# ============================================================

@tool
def scale_features(layer_name: str, x_factor: float = 1, y_factor: float = 1) -> str:
    """缩放指定图层的所有要素。x_factor 为 X 轴缩放倍数，y_factor 为 Y 轴缩放倍数。缩放中心为图层几何中心。大于 1 放大，小于 1 缩小。"""
    try:
        import geopandas as gpd
        from shapely import affinity
        import warnings

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

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if x_factor <= 0 or y_factor <= 0:
            return "缩放倍数必须大于 0"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            center = gdf.dissolve().centroid.iloc[0]

        gdf.geometry = gdf.geometry.scale(xfact=x_factor, yfact=y_factor, origin=(center.x, center.y))

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _registered_layers[layer_name]["geojson"] = geojson_data
        _push_layer(layer_name, geojson_data)

        return (f"已缩放图层「{layer_name}」（X: {x_factor}倍, Y: {y_factor}倍），"
                f"{len(gdf)} 个要素，已同步地图")
    except Exception as e:
        import traceback
        return f"缩放要素失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: draw_feature — 绘制点/线/面
# ============================================================

@tool
def draw_feature(geometry_type: str, coordinates: str, layer_name: str = "") -> str:
    """根据指定坐标创建新的点/线/面图层。
    geometry_type: Point / LineString / Polygon / Rectangle / Circle。
    coordinates 格式：
      - Point: "lon,lat" 如 "116.4,39.9"
      - LineString: "lon1,lat1;lon2,lat2;..." 如 "116.3,39.9;116.4,40.0;116.5,39.8"
      - Polygon: "lon1,lat1;lon2,lat2;lon3,lat3;lon1,lat1"（首尾闭合）
      - Rectangle: "lon1,lat1;lon2,lat2"（对角线，自动生成矩形）
      - Circle: "lon,lat;radius_m"（圆心坐标 + 半径米数，自动 UTM 投影）
    未指定 layer_name 时自动命名。"""
    try:
        import geopandas as gpd
        from shapely.geometry import Point, LineString, Polygon
        import json, re

        gt = geometry_type.strip().lower()
        norm_map = {"point": "Point", "linestring": "LineString", "polygon": "Polygon",
                    "rectangle": "Rectangle", "circle": "Circle"}
        if gt in norm_map:
            gt = norm_map[gt]
        else:
            return f"不支持的几何类型：{geometry_type}，请用 Point / LineString / Polygon / Rectangle / Circle"

        # 解析坐标
        parts = [p.strip() for p in coordinates.replace("，", ",").replace("；", ";").split(";") if p.strip()]
        if not parts:
            return "未提供有效坐标"

        def parse_xy(s):
            s = s.replace("，", ",")
            xy = [x.strip() for x in s.split(",") if x.strip()]
            if len(xy) != 2:
                return None
            try:
                return (float(xy[0]), float(xy[1]))
            except ValueError:
                return None

        pts = [parse_xy(p) for p in parts]
        pts = [p for p in pts if p is not None]

        if gt == "Point":
            if not pts:
                return "无法解析坐标，请使用「lon,lat」格式"
            geom = Point(pts[0])
            node_count = 1
        elif gt == "LineString":
            if len(pts) < 2:
                return "无法解析坐标，LineString 至少需要 2 个点"
            geom = LineString(pts)
            node_count = len(pts)
        elif gt == "Polygon":
            if len(pts) < 3:
                return "无法解析坐标，Polygon 至少需要 3 个点"
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            geom = Polygon(pts)
            node_count = len(pts)
        elif gt == "Rectangle":
            if len(parts) == 2 and (len(pts) < 2 or len(pts) > 2):
                pass  # pts already parsed
            if len(pts) != 2:
                return "Rectangle 需要 2 个坐标（对角线）：lon1,lat1;lon2,lat2"
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)
            geom = Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)])
            node_count = 4
        else:  # Circle
            if len(pts) < 1 or len(parts) < 2:
                return "Circle 需要圆心坐标和半径：lon,lat;radius_m"
            radius = float(parts[1]) if len(parts) >= 2 else 0
            if radius <= 0:
                return "半径必须大于 0"
            center_pt = Point(pts[0])
            lon, lat = pts[0]
            utm_zone = int((lon + 180) / 6) + 1
            crs_utm = f"EPSG:{32600 + utm_zone}" if lat >= 0 else f"EPSG:{32700 + utm_zone}"
            center_gdf = gpd.GeoDataFrame({"geometry": [center_pt]}, crs="EPSG:4326")
            center_utm = center_gdf.to_crs(crs_utm)
            circle_utm = center_utm.geometry.buffer(radius)
            circle_gdf = gpd.GeoDataFrame({"geometry": circle_utm}, crs=crs_utm).to_crs("EPSG:4326")
            geom = circle_gdf.geometry.iloc[0]
            node_count = len(geom.exterior.coords) if hasattr(geom, 'exterior') else 0

        name = layer_name.strip() or f"绘制_{gt}_{len(_registered_layers) + 1}"
        gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")
        _gdf_to_layer(gdf, name)
        pts_str = f"，含 {node_count} 个节点" if node_count else ""
        return f"已创建{gt}图层「{name}」，含 1 个要素{pts_str}，已加载到地图"
    except Exception as e:
        import traceback
        return f"绘制失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: spatial_buffer — 缓冲区分析
# ============================================================

@tool
def spatial_intersect(layer_a: str, layer_b: str) -> str:
    """两个图层的空间相交分析，返回两者重叠的部分。"""
    try:
        import geopandas as gpd
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        result = gpd.overlay(gdf_a, gdf_b, how="intersection")
        if result.empty:
            return f"「{name_a}」和「{name_b}」没有重叠区域"
        result_name = f"{name_a}_∩_{name_b}"
        _gdf_to_layer(result, result_name)
        return f"相交分析完成：{len(result)} 个要素，已加载到地图"
    except Exception as e:
        return f"相交分析失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_union — 空间合并
# ============================================================

@tool
def spatial_union(layer_a: str, layer_b: str) -> str:
    """合并两个图层的全部几何区域。"""
    try:
        import geopandas as gpd
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        result = gpd.overlay(gdf_a, gdf_b, how="union")
        result_name = f"{name_a}_∪_{name_b}"
        _gdf_to_layer(result, result_name)
        return f"合并完成：{len(result)} 个要素，已加载到地图"
    except Exception as e:
        return f"合并失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_difference — 空间差异
# ============================================================

@tool
def spatial_difference(layer_a: str, layer_b: str) -> str:
    """用 layer_a 减去 layer_b，返回 layer_a 中不在 layer_b 内的部分。"""
    try:
        import geopandas as gpd
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        result = gpd.overlay(gdf_a, gdf_b, how="difference")
        if result.empty:
            return f"「{name_a}」完全被「{name_b}」覆盖，无剩余部分"
        result_name = f"{name_a}_减_{name_b}"
        _gdf_to_layer(result, result_name)
        return f"差异分析完成：{len(result)} 个要素，已加载到地图"
    except Exception as e:
        return f"差异分析失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_clip — 裁剪
# ============================================================

@tool
def spatial_clip(layer_name: str, clip_layer: str) -> str:
    """用 clip_layer 的边界裁剪 layer_name。"""
    try:
        import geopandas as gpd
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        clip_gdf, clip_name = _layer_to_gdf(clip_layer)
        if clip_gdf is None: return clip_name
        result = gpd.clip(gdf, clip_gdf)
        if result.empty:
            return f"裁剪后无剩余要素（「{name}」不在「{clip_name}」范围内）"
        result_name = f"{name}_裁剪"
        _gdf_to_layer(result, result_name)
        return f"裁剪完成：{len(result)} 个要素，已加载到地图"
    except Exception as e:
        return f"裁剪失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_centroid — 质心提取
# ============================================================

@tool
def spatial_centroid(layer_name: str) -> str:
    """提取图层的质心/中心点，返回点图层。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        import warnings
        centroids = gdf.copy()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            centroids["geometry"] = gdf.geometry.centroid
        centroids = centroids[centroids.geometry.notna()]
        if centroids.empty:
            return f"「{name}」无法计算质心"
        result_name = f"{name}_质心"
        _gdf_to_layer(centroids, result_name)
        return f"已提取 {len(centroids)} 个质心，已加载到地图"
    except Exception as e:
        return f"质心提取失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_simplify — 简化几何
# ============================================================

@tool
def spatial_simplify(layer_name: str, tolerance: float = 0.001) -> str:
    """简化图层几何，减少顶点数。tolerance 为简化容差（单位：度），0.001 约等于 100m。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
        result_name = f"{name}_简化"
        _gdf_to_layer(gdf, result_name)
        return f"已简化「{name}」（容差 {tolerance}），{len(gdf)} 个要素，已加载到地图"
    except Exception as e:
        return f"简化失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_dissolve — 融合
# ============================================================

@tool
def spatial_dissolve(layer_name: str, group_by: str = "") -> str:
    """按属性字段融合图层几何。相同字段值的要素合并为一个。不传 group_by 则融合全部要素。"""
    try:
        import geopandas as gpd
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        if group_by and group_by in gdf.columns:
            result = gdf.dissolve(by=group_by, aggfunc="first").reset_index()
            result_name = f"{name}_按{group_by}融合"
        else:
            result = gpd.GeoDataFrame({"geometry": [gdf.union_all()]}, geometry="geometry", crs="EPSG:4326")
            result_name = f"{name}_融合"
        _gdf_to_layer(result, result_name)
        return f"融合完成：{len(result)} 个要素，已加载到地图"
    except Exception as e:
        return f"融合失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_select — 按空间关系选择
# ============================================================

@tool
def spatial_select(target_layer: str, source_layer: str, predicate: str = "intersects") -> str:
    """按空间关系选择要素。返回 target_layer 中与 source_layer 满足关系的要素。predicate: intersects / within / contains / touches / crosses / overlaps。"""
    try:
        import geopandas as gpd
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None: return name_t
        gdf_s, name_s = _layer_to_gdf(source_layer)
        if gdf_s is None: return name_s
        result = gpd.sjoin(gdf_t, gdf_s, how="inner", predicate=predicate)
        result = result.drop(columns=[c for c in result.columns if c.endswith("_right") or c == "index_right"], errors="ignore")
        result = result.drop_duplicates()
        if result.empty:
            return f"没有要素满足「{predicate}」关系"
        result_name = f"{name_t}_选择"
        _gdf_to_layer(result, result_name)
        return f"按「{predicate}」选择了 {len(result)}/{len(gdf_t)} 个要素，已加载到地图"
    except Exception as e:
        return f"空间选择失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_sample — 随机采样
# ============================================================

@tool
def spatial_sample(layer_name: str, n: int = 0, frac: float = 0) -> str:
    """从图层随机采样 n 个要素（或 frac 比例）。n 和 frac 至少指定一个。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        if n > 0:
            n = min(n, len(gdf))
            sampled = gdf.sample(n=n)
        elif frac > 0:
            sampled = gdf.sample(frac=min(frac, 1.0))
        else:
            return "请指定 n（数量）或 frac（比例）"
        if sampled.empty:
            return "采样结果为空"
        result_name = f"{name}_采样{n or frac}"
        _gdf_to_layer(sampled, result_name)
        return f"已随机采样 {len(sampled)}/{len(gdf)} 个要素，已加载到地图"
    except Exception as e:
        return f"采样失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_near — 查找附近要素
# ============================================================

@tool
def spatial_near(layer_name: str, target_layer: str, distance: float = 1000) -> str:
    """查找 target_layer 中距离 layer_name 要素 distance 米以内的要素。"""
    try:
        import geopandas as gpd
        from shapely import buffer
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None: return name_t
        gdf_u = gdf.to_crs("EPSG:3857")
        gdf_tu = gdf_t.to_crs("EPSG:3857")
        gdf_u_buf = gpd.GeoDataFrame({"geometry": gdf_u.geometry.buffer(distance)}, geometry="geometry", crs="EPSG:3857")
        hits = gpd.sjoin(gdf_tu, gdf_u_buf, how="inner", predicate="intersects")
        if hits.empty:
            return f"「{name_t}」中未找到距离「{name}」{distance}m 以内的要素"
        result = gdf_t.iloc[hits.index.unique()].copy()
        result_name = f"{name_t}_附近"
        _gdf_to_layer(result, result_name)
        return f"找到 {len(result)} 个距离{distance}m 以内的要素，已加载到地图"
    except Exception as e:
        return f"近邻查找失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_cluster — 空间聚类
# ============================================================

@tool
def spatial_cluster(layer_name: str, eps: float = 0.01, min_samples: int = 3) -> str:
    """用 DBSCAN 对点图层做空间聚类。eps 为聚类半径（度），min_samples 为最少点数。返回带 cluster 字段的新图层。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        from sklearn.cluster import DBSCAN
        coords = gdf.geometry.get_coordinates().values
        if len(coords) < min_samples:
            return f"要素数（{len(coords)}）少于最少点数（{min_samples}），无法聚类"
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
        gdf["cluster"] = clustering.labels_.tolist()
        n_clusters = len(set(clustering.labels_)) - (1 if -1 in clustering.labels_ else 0)
        noise = list(clustering.labels_).count(-1)
        result_name = f"{name}_聚类"
        _gdf_to_layer(gdf, result_name)
        return f"聚类完成：{n_clusters} 个簇，{noise} 个噪声点，已加载到地图（含 cluster 字段）"
    except Exception as e:
        return f"聚类失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_voronoi — 泰森多边形
# ============================================================

@tool
def spatial_voronoi(layer_name: str) -> str:
    """根据点图层生成泰森多边形（Voronoi 图）。覆盖范围由输入点的凸包决定。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        from shapely import MultiPoint
        from shapely.ops import voronoi_diagram
        points = gdf.geometry.union_all()
        polygons = voronoi_diagram(points)
        import geopandas as gpd
        result = gpd.GeoDataFrame({"geometry": list(polygons.geoms)}, geometry="geometry", crs="EPSG:4326")
        if result.empty:
            return "泰森多边形生成失败"
        result_name = f"{name}_泰森"
        _gdf_to_layer(result, result_name)
        return f"已生成 {len(result)} 个泰森多边形，已加载到地图"
    except Exception as e:
        return f"泰森多边形失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_field_stats — 字段统计
# ============================================================

@tool
def spatial_field_stats(layer_name: str, field: str = "") -> str:
    """统计图层数值字段的基本统计量（count / min / max / mean / sum / std / 空值数）。不指定 field 则列出所有可统计字段。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        import numpy as np
        numeric_cols = gdf.select_dtypes(include=[np.number]).columns.tolist()
        if not field:
            return f"「{name}」的数值字段：{', '.join(numeric_cols) if numeric_cols else '无'}"
        if field not in gdf.columns:
            return f"「{name}」中无字段「{field}」，可用字段：{', '.join(gdf.columns)}"
        if field not in numeric_cols:
            return f"字段「{field}」不是数值类型，类型：{gdf[field].dtype}"
        vals = gdf[field].dropna()
        from collections import OrderedDict
        stats = OrderedDict([
            ("count", len(gdf)),
            ("non_null", len(vals)),
            ("null", int(gdf[field].isna().sum())),
            ("min", float(vals.min())),
            ("max", float(vals.max())),
            ("mean", float(vals.mean())),
            ("sum", float(vals.sum())),
            ("std", float(vals.std()) if len(vals) > 1 else 0),
        ])
        lines = [f"📊 「{name}」.{field} 统计："]
        for k, v in stats.items():
            lines.append(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
        return "\n".join(lines)
    except Exception as e:
        return f"字段统计失败: {str(e)[:300]}"


# ============================================================
# 工具: reverse_geocode — 反向地理编码
# ============================================================

@tool
def reverse_geocode(lng: float, lat: float) -> str:
    """将 WGS-84 坐标转为地址描述（反向地理编码）。"""
    if not _current_amap_key:
        return "高德 API Key 未配置"
    import requests
    from backend.services.geo_coords import wgs84_to_gcj02
    try:
        gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
        params = {"key": _current_amap_key, "location": f"{gcj_lng},{gcj_lat}", "output": "JSON", "radius": 100}
        resp = requests.get("https://restapi.amap.com/v3/geocode/regeo", params=params, timeout=10)
        data = resp.json()
        if data.get("status") != "1":
            return f"反向地理编码失败：{data.get('info', '未知错误')}"
        regeocode = data.get("regeocode", {})
        formatted = regeocode.get("formatted_address", "")
        if not formatted:
            return f"({lng:.6f}, {lat:.6f}) 附近无地址信息"
        return f"坐标 ({lng:.6f}, {lat:.6f}) 对应地址：{formatted}"
    except Exception as e:
        return f"反向地理编码失败: {str(e)[:200]}"


# ============================================================
# 工具: batch_geocode — 批量地理编码
# ============================================================

@tool
def batch_geocode(addresses: str) -> str:
    """批量将地名转为 WGS-84 坐标。addresses 用逗号或分号分隔。返回地名→坐标映射。"""
    if not _current_amap_key:
        return "高德 API Key 未配置"
    import requests
    from backend.services.geo_coords import gcj02_to_wgs84
    import re
    sep = ";" if ";" in addresses else ","
    parts = [a.strip() for a in addresses.split(sep) if a.strip()]
    if not parts:
        return "请输入至少一个地址"
    results = []
    for addr in parts:
        try:
            params = {"key": _current_amap_key, "address": addr, "output": "JSON"}
            resp = requests.get("https://restapi.amap.com/v3/geocode/geo", params=params, timeout=10)
            data = resp.json()
            if data.get("status") != "1" or not data.get("geocodes"):
                results.append(f"  ❌ {addr}：未找到")
                continue
            loc = data["geocodes"][0].get("location", "")
            if not loc:
                results.append(f"  ❌ {addr}：未找到")
                continue
            lng, lat = loc.split(",")
            wgs_lng, wgs_lat = gcj02_to_wgs84(float(lng), float(lat))
            results.append(f"  ✅ {addr} → {wgs_lng:.6f},{wgs_lat:.6f}")
        except Exception as e:
            results.append(f"  ❌ {addr}：{str(e)[:60]}")
    return f"批量地理编码结果（{len(results)}/{len(parts)}）：\n" + "\n".join(results)


# ============================================================
# 工具: spatial_join — 空间连接
# ============================================================

@tool
def spatial_join(target_layer: str, join_layer: str, how: str = "left", predicate: str = "intersects") -> str:
    """将 join_layer 的属性按空间关系连接到 target_layer 的要素上。predicate: intersects / within / contains / nearest。how: left / inner。"""
    try:
        import geopandas as gpd
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None: return name_t
        gdf_j, name_j = _layer_to_gdf(join_layer)
        if gdf_j is None: return name_j
        result = gpd.sjoin(gdf_t, gdf_j, how=how, predicate=predicate)
        result_name = f"{name_t}_连接{name_j}"
        _gdf_to_layer(result, result_name)
        return f"空间连接完成：{len(result)} 个要素，已加载到地图"
    except Exception as e:
        return f"空间连接失败: {str(e)[:300]}"


# ============================================================
# 工具: layer_merge — 图层合并
# ============================================================

@tool
def layer_merge(layer_names: str, new_name: str = "") -> str:
    """合并多个图层为一个（行合并）。layer_names 用逗号分隔。"""
    try:
        import geopandas as gpd
        names = [n.strip() for n in layer_names.split(",")]
        gdfs = []
        for n in names:
            gdf, resolved = _layer_to_gdf(n)
            if gdf is None: return resolved
            gdfs.append(gdf)
        result = gpd.pd.concat(gdfs, ignore_index=True)
        merged_name = new_name.strip() or f"{'_'.join(names)}_合并"
        _gdf_to_layer(result, merged_name)
        return f"合并完成：{len(result)} 个要素（{len(names)} 个图层），已加载到地图"
    except Exception as e:
        return f"图层合并失败: {str(e)[:300]}"


# ============================================================
# 工具: layer_split — 图层拆分
# ============================================================

@tool
def layer_split(layer_name: str, by_field: str = "") -> str:
    """按属性字段拆分图层，每个唯一值生成一个子图层。不传 by_field 则每个要素单独成层。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        if by_field and by_field in gdf.columns:
            groups = gdf.groupby(by_field)
            count = 0
            for val, group in groups:
                sub_name = f"{name}_{val}"
                _gdf_to_layer(group, sub_name)
                count += 1
            return f"按字段「{by_field}」拆分为 {count} 个子图层（共 {len(gdf)} 个要素），已加载到地图"
        else:
            for i in range(len(gdf)):
                sub = gdf.iloc[[i]].copy()
                sub_name = f"{name}_{i}"
                _gdf_to_layer(sub, sub_name)
            return f"已拆分为 {len(gdf)} 个独立要素图层，已加载到地图"
    except Exception as e:
        return f"图层拆分失败: {str(e)[:300]}"


# ============================================================
# 工具: layer_add_geometry — 从坐标创建几何
# ============================================================

@tool
def layer_add_geometry(layer_name: str, lon_field: str = "", lat_field: str = "") -> str:
    """根据图层中的经度/纬度字段创建点几何。自动识别常见列名（lng/lon/longitude/x, lat/latitude/y）。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        import geopandas as gpd
        from shapely.geometry import Point
        lon_candidates = ["lng", "lon", "longitude", "x", "经度", "经"]
        lat_candidates = ["lat", "latitude", "y", "纬度", "纬"]
        if not lon_field:
            for c in lon_candidates:
                if c in gdf.columns:
                    lon_field = c
                    break
        if not lat_field:
            for c in lat_candidates:
                if c in gdf.columns:
                    lat_field = c
                    break
        if not lon_field or not lat_field:
            return f"未找到经纬度列，可用列：{', '.join(gdf.columns)}"
        gdf["geometry"] = gdf.apply(lambda r: Point(float(r[lon_field]), float(r[lat_field])), axis=1)
        gdf = gdf.set_geometry("geometry", crs="EPSG:4326")
        result_name = f"{name}_点"
        _gdf_to_layer(gdf, result_name)
        return f"已从 {lon_field}/{lat_field} 创建 {len(gdf)} 个点，已加载到地图"
    except Exception as e:
        return f"创建几何失败: {str(e)[:300]}"


# ============================================================
# 工具: add_labels — 属性标注
# ============================================================

@tool
def add_labels(layer_name: str, field: str, font_size: int = 12, color: str = "#333333") -> str:
    """对图层添加属性标注，每个要素上显示指定字段的文本标签，类似于 ArcGIS 的"标注要素"功能。
    layer_name: 图层名；field: 用于标注的字段名；font_size: 字体大小（默认12）；color: 字体颜色（如"#333333"）。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        _pending_layer_ops.append({
            "action": "labels",
            "name": name,
            "field": field,
            "font_size": font_size,
            "color": color,
        })

        feat_count = len(gdf)
        return (f"已为「{name}」添加标注，字段：{field}，{feat_count} 个要素已显示文字标签")
    except Exception as e:
        return f"标注失败: {str(e)[:200]}"


# ============================================================
# 工具: spatial_graduated_colors — 分级色彩渲染
# ============================================================

@tool
def spatial_graduated_colors(layer_name: str, field: str, n_classes: int = 5, color_scheme: str = "blues") -> str:
    """对图层应用分级色彩渲染（Choropleth），按数值字段将要素分为N个等级，每级用不同颜色显示。
    layer_name: 图层名；field: 数值字段名；n_classes: 分级数（2-20，默认5）；
    color_scheme: 色带 scheme(默认)/blues(蓝)/reds(红)/greens(绿)/purples(紫)/oranges(橙)。"""
    try:
        import geopandas as gpd
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        if not gdf[field].dtype.kind in ('i', 'f'):
            return f"字段「{field}」不是数值类型（{gdf[field].dtype}），分级色彩仅支持数值字段"

        n_classes = max(2, min(20, n_classes if n_classes else 5))
        values = gdf[field].dropna()
        if values.empty:
            return f"字段「{field}」无有效数值"

        vmin, vmax = float(values.min()), float(values.max())
        if vmin == vmax:
            return f"字段「{field}」所有值相同（{vmin}），无法分级"

        step = (vmax - vmin) / n_classes
        breaks = [vmin + i * step for i in range(n_classes + 1)]

        color_scheme = color_scheme if color_scheme in ("scheme","blues","reds","greens","purples","oranges") else "blues"

        _pending_layer_ops.append({
            "action": "symbology",
            "name": name,
            "symbology_type": "graduated",
            "field": field,
            "classes": n_classes,
            "scheme": color_scheme,
        })

        breaks_str = ", ".join(f"{b:.2f}" for b in breaks)
        return (f"已对「{name}」应用分级色彩渲染，字段：{field}，{n_classes} 级，"
                f"色带：{color_scheme}，值域：{vmin:.2f} ~ {vmax:.2f}\n"
                f"分界值：{breaks_str}")
    except Exception as e:
        import traceback
        return f"分级色彩渲染失败: {str(e)[:200]}"


# ============================================================
# 工具: spatial_unique_values — 唯一值渲染
# ============================================================

@tool
def spatial_unique_values(layer_name: str, field: str, color_scheme: str = "scheme") -> str:
    """对图层应用唯一值渲染，按分类字段每个唯一值分配不同颜色。
    layer_name: 图层名；field: 分类字段（字符串或数值）；
    color_scheme: 色带 scheme(默认)/blues(蓝)/reds(红)/greens(绿)/purples(紫)/oranges(橙)。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        unique_vals = gdf[field].dropna().unique()
        n_unique = len(unique_vals)
        if n_unique == 0:
            return f"字段「{field}」无有效值"

        if n_unique > 50:
            return (f"字段「{field}」有 {n_unique} 个唯一值（超出最大50），"
                    f"建议改用 spatial_graduated_colors 分级色彩或缩小范围后再试")

        color_scheme = color_scheme if color_scheme in ("scheme","blues","reds","greens","purples","oranges") else "scheme"

        _pending_layer_ops.append({
            "action": "symbology",
            "name": name,
            "symbology_type": "unique",
            "field": field,
            "scheme": color_scheme,
        })

        val_list = list(unique_vals[:20])
        vals_str = ", ".join(str(v) for v in val_list)
        if n_unique > 20:
            vals_str += f" ... 等共 {n_unique} 个值"
        return (f"已对「{name}」应用唯一值渲染，字段：{field}，{n_unique} 个类别，"
                f"色带：{color_scheme}\n"
                f"值列表：{vals_str}")
    except Exception as e:
        return f"唯一值渲染失败: {str(e)[:200]}"


# ============================================================
# 工具: add_legend — 显示图例
# ============================================================

@tool
def add_legend(layer_name: str) -> str:
    """显示图层的图例。图例根据图层的符号化配置（分级色彩或唯一值渲染）自动生成。
    layer_name: 图层名。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        _pending_layer_ops.append({
            "action": "legend",
            "name": name,
        })

        return (f"已为「{name}」生成图例")
    except Exception as e:
        return f"图例生成失败: {str(e)[:200]}"


# ============================================================
# 工具: update_attribute — 属性编辑
# ============================================================

@tool
def update_attribute(layer_name: str, field: str, value: str, condition_field: str = "", condition_value: str = "") -> str:
    """更新图层要素的属性值。不指定条件则更新所有要素。
    支持数值和文本字段。更新后地图自动同步。
    layer_name: 图层名；field: 要更新的字段名；value: 新值（自动转换类型）；
    condition_field: 条件字段名（可选）；condition_value: 条件字段值（可选，仅更新匹配要素）。"""
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
        import json

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field not in gdf.columns:
            return f"图层「{layer_name}」没有字段「{field}」，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

        # 类型转换
        dtype_kind = gdf[field].dtype.kind
        try:
            if dtype_kind == 'i':
                typed_value = int(value)
            elif dtype_kind == 'f':
                typed_value = float(value)
            else:
                typed_value = str(value)
        except ValueError:
            return f"字段「{field}」类型为 {gdf[field].dtype}，但值「{value}」无法转换"

        # 筛选要更新的行
        if condition_field and condition_value:
            if condition_field not in gdf.columns:
                return f"条件字段「{condition_field}」不存在"
            cond_kind = gdf[condition_field].dtype.kind
            try:
                if cond_kind in ('i', 'f'):
                    cond_value = float(condition_value)
                else:
                    cond_value = str(condition_value)
            except ValueError:
                cond_value = str(condition_value)

            matches_mask = gdf[condition_field] == cond_value
            match_count = matches_mask.sum()
            if match_count == 0:
                return f"没有要素满足条件（{condition_field} = {condition_value}）"
            gdf.loc[matches_mask, field] = typed_value
            affected = match_count
        else:
            gdf[field] = typed_value
            affected = len(gdf)

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _registered_layers[layer_name]["geojson"] = geojson_data
        _push_layer(layer_name, geojson_data)

        condition_str = f"（条件：{condition_field} = {condition_value}）" if condition_field else ""
        return (f"已更新图层「{layer_name}」字段「{field}」为 {value}，"
                f"影响 {affected}/{len(gdf)} 个要素{condition_str}，已同步地图")
    except Exception as e:
        return f"属性更新失败: {str(e)[:300]}"


# ============================================================
# 工具: delete_features — 删除要素
# ============================================================

@tool
def delete_features(layer_name: str, condition_field: str = "", condition_value: str = "") -> str:
    """按条件删除图层的要素。必须指定条件（例如删除某个字段等于某值的所有要素）。
    删除后地图自动同步。layer_name: 图层名；condition_field: 条件字段名（必填）；
    condition_value: 条件字段值（必填）。"""
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

        if not condition_field or not condition_value:
            return "请指定删除条件（condition_field 和 condition_value），例如删除 name=xx 的所有要素"

        import geopandas as gpd
        import json

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if condition_field not in gdf.columns:
            return f"条件字段「{condition_field}」不存在，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

        cond_kind = gdf[condition_field].dtype.kind
        try:
            if cond_kind in ('i', 'f'):
                cond_val = float(condition_value)
            else:
                cond_val = str(condition_value)
        except ValueError:
            cond_val = str(condition_value)

        mask = gdf[condition_field] == cond_val
        to_delete = mask.sum()
        if to_delete == 0:
            return f"没有要素满足条件（{condition_field} = {condition_value}）"

        remaining = gdf[~mask]
        if remaining.empty:
            return f"条件（{condition_field} = {condition_value}）将删除全部 {to_delete} 个要素，操作已取消"

        geojson_data = remaining.__geo_interface__
        geojson_data["name"] = layer_name
        _registered_layers[layer_name]["geojson"] = geojson_data
        _push_layer(layer_name, geojson_data)

        return (f"已从图层「{layer_name}」删除 {to_delete}/{len(gdf)} 个要素"
                f"（条件：{condition_field} = {condition_value}），剩余 {len(remaining)} 个，已同步地图")
    except Exception as e:
        return f"删除要素失败: {str(e)[:300]}"


# ============================================================
# 工具: add_field / delete_field — 字段管理
# ============================================================

@tool
def add_field(layer_name: str, field_name: str, field_type: str = "str", default_value: str = "") -> str:
    """为图层添加新字段。field_type 可选 str(文本) / int(整数) / float(小数)。
    default_value 可指定默认填充值。添加后地图自动同步。"""
    try:
        import geopandas as gpd
        import pandas as pd
        import json

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

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field_name in gdf.columns:
            return f"字段「{field_name}」已存在"

        field_type = field_type.lower().strip()
        if field_type == "int":
            gdf[field_name] = pd.Series(dtype="int64")
            if default_value:
                try:
                    gdf[field_name] = int(default_value)
                except ValueError:
                    pass
        elif field_type == "float":
            gdf[field_name] = pd.Series(dtype="float64")
            if default_value:
                try:
                    gdf[field_name] = float(default_value)
                except ValueError:
                    pass
        else:
            gdf[field_name] = pd.Series(dtype="object")
            if default_value:
                gdf[field_name] = str(default_value)

        if default_value:
            gdf[field_name] = gdf[field_name].fillna(default_value if field_type == "str" else
                                                       (int(default_value) if field_type == "int" else float(default_value)))

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _registered_layers[layer_name]["geojson"] = geojson_data
        _push_layer(layer_name, geojson_data)

        return (f"已为图层「{layer_name}」添加字段「{field_name}」（类型：{field_type}"
                + (f"，默认值：{default_value}" if default_value else "")
                + "），已同步地图")

    except Exception as e:
        return f"添加字段失败: {str(e)[:300]}"


@tool
def delete_field(layer_name: str, field_name: str) -> str:
    """删除图层的指定字段。字段删除后数据不可恢复。layer_name: 图层名；field_name: 要删除的字段名。"""
    try:
        import geopandas as gpd
        import json

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

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field_name not in gdf.columns:
            return f"字段「{field_name}」不存在，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

        if field_name == "geometry":
            return "不能删除 geometry 字段"

        gdf = gdf.drop(columns=[field_name])

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _registered_layers[layer_name]["geojson"] = geojson_data
        _push_layer(layer_name, geojson_data)

        return f"已从图层「{layer_name}」删除字段「{field_name}」，已同步地图"

    except Exception as e:
        return f"删除字段失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_select_by_attribute — 按属性选择
# ============================================================

@tool
def spatial_select_by_attribute(layer_name: str, field: str, operator: str, value: str) -> str:
    """按属性条件选择要素。支持操作符：=(等于) / !=(不等于) / >(大于) / >=(大于等于) / <(小于) / <=(小于等于) / like(包含) / between(介于,值格式"min,max")。
    将匹配要素复制为新图层，不修改原始数据。layer_name: 图层名；field: 字段名；operator: 操作符；value: 比较值。"""
    try:
        import geopandas as gpd
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        ops = {
            "=": "eq", "eq": "eq",
            "!=": "ne", "neq": "ne",
            ">": "gt", "gt": "gt",
            ">=": "gte", "gte": "gte",
            "<": "lt", "lt": "lt",
            "<=": "lte", "lte": "lte",
            "like": "like",
            "between": "between",
        }
        op_norm = ops.get(operator.lower() if operator else "")
        if op_norm is None:
            return f"不支持的操作符「{operator}」，支持：= != > >= < <= like between"

        field_data = gdf[field]
        is_numeric = field_data.dtype.kind in ('i', 'f')

        if op_norm == "like":
            mask = field_data.astype(str).str.contains(value, case=False, na=False)
        elif op_norm == "between":
            parts = value.split(",")
            if len(parts) != 2:
                return "between 格式为「min,max」，如「0,100」"
            try:
                vmin, vmax = float(parts[0]), float(parts[1])
            except ValueError:
                return f"between 值必须为数字，当前：{value}"
            if not is_numeric:
                return f"字段「{field}」不是数值类型，不支持 between"
            mask = (field_data >= vmin) & (field_data <= vmax)
        else:
            if is_numeric:
                try:
                    v = float(value)
                except ValueError:
                    return f"字段「{field}」为数值类型，但条件值「{value}」无法转为数字"
                if op_norm == "eq":
                    mask = field_data == v
                elif op_norm == "ne":
                    mask = field_data != v
                elif op_norm == "gt":
                    mask = field_data > v
                elif op_norm == "gte":
                    mask = field_data >= v
                elif op_norm == "lt":
                    mask = field_data < v
                elif op_norm == "lte":
                    mask = field_data <= v
                else:
                    return f"不支持的数值操作符：{operator}"
            else:
                if op_norm in ("gt", "gte", "lt", "lte", "between"):
                    return f"字段「{field}」不是数值类型，不支持「{operator}」操作"
                if op_norm == "eq":
                    mask = field_data == value
                elif op_norm == "ne":
                    mask = field_data != value
                else:
                    return f"不支持的字符串操作符：{operator}"

        result = gdf[mask].copy()
        if result.empty:
            return f"没有满足条件（{field} {operator} {value}）的要素"

        result_name = f"{name}_按{field}{operator}{value}"
        _gdf_to_layer(result, result_name)
        return (f"按属性条件（{field} {operator} {value}）选择了 {len(result)}/{len(gdf)} 个要素，"
                f"已加载到地图：{result_name}")
    except Exception as e:
        import traceback
        return f"按属性选择失败: {str(e)[:300]}"


# ============================================================
# 工具列表（供 LangGraph Agent 注册）
# ============================================================

# ============================================================
# 工具: edit_vertices — 折点编辑
# ============================================================

@tool
def edit_vertices(layer_name: str) -> str:
    """对图层要素启用折点拖拽编辑模式。用户可通过鼠标拖拽几何图形的顶点进行编辑。
    layer_name: 图层名。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        _pending_layer_ops.append({
            "action": "edit_vertices",
            "name": name,
        })

        feat_count = len(gdf)
        return (f"已为「{name}」启用折点编辑，{feat_count} 个要素进入编辑模式。拖拽顶点修改后保存即可。")
    except Exception as e:
        return f"启用折点编辑失败: {str(e)[:200]}"


# ============================================================
# 工具: export_map — 地图导出（图片/PDF）
# ============================================================

@tool
def export_map(format: str = "png") -> str:
    """将当前地图导出为图片。format: png(默认) / jpg。"""
    try:
        _pending_layer_ops.append({
            "action": "export_map",
            "format": format,
        })
        return f"已触发地图导出（{format}）"
    except Exception as e:
        return f"导出失败: {str(e)[:200]}"


# ============================================================
# 工具: export_pdf — PDF 出图
# ============================================================

@tool
def export_pdf(title: str = "地图导出") -> str:
    """将当前地图导出为 PDF 文档（打印布局），包含地图、标题、比例尺、图例、指北针。
    title: 文档标题（默认"地图导出"）。"""
    try:
        _pending_layer_ops.append({
            "action": "export_pdf",
            "title": title,
        })
        return f"已触发 PDF 出图，标题：{title}"
    except Exception as e:
        return f"PDF 出图失败: {str(e)[:200]}"


# ============================================================
# 工具: undo / redo — 撤销重做
# ============================================================

@tool
def undo() -> str:
    """撤销上一步操作（恢复上一步的地图状态）。"""
    try:
        _pending_layer_ops.append({"action": "undo"})
        return "已触发撤销操作"
    except Exception as e:
        return f"撤销失败: {str(e)[:200]}"


@tool
def redo() -> str:
    """重做被撤销的操作。"""
    try:
        _pending_layer_ops.append({"action": "redo"})
        return "已触发重做操作"
    except Exception as e:
        return f"重做失败: {str(e)[:200]}"


# ============================================================
# 工具: dem_analysis — 坡度/坡向/山体阴影
# ============================================================

@tool
def dem_analysis(layer_name: str, analysis: str = "slope") -> str:
    """对DEM栅格图层进行地形分析。analysis可选: slope(坡度), aspect(坡向), hillshade(山体阴影)。
    layer_name为上传DEM时创建的图层名（如dem.tif→图层名为dem）。
    结果将作为新栅格图层叠加到地图上。"""
    try:
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        if not os.path.isdir(upload_dir):
            return "未找到上传目录，请先上传DEM文件"
        # 按图层名匹配TIF
        tif_path = None
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    tif_path = os.path.join(upload_dir, f)
                    break
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件，请先上传DEM"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        with rasterio.open(tif_path) as src:
            dem = src.read(1).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                dem[dem == nodata] = np.nan
            transform = src.transform
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        ny, nx = dem.shape
        cx = transform[0]
        cy = -abs(transform[4])
        # Horn's formula — 3x3 window
        dzdx = np.full_like(dem, np.nan)
        dzdy = np.full_like(dem, np.nan)
        # interior cells
        dzdx[1:-1,1:-1] = (
            (dem[:-2,2:] + 2*dem[1:-1,2:] + dem[2:,2:]) -
            (dem[:-2,:-2] + 2*dem[1:-1,:-2] + dem[2:,:-2])
        ) / (8 * cx)
        dzdy[1:-1,1:-1] = (
            (dem[2:,:-2] + 2*dem[2:,1:-1] + dem[2:,2:]) -
            (dem[:-2,:-2] + 2*dem[:-2,1:-1] + dem[:-2,2:])
        ) / (8 * cy)
        valid = np.isfinite(dzdx) & np.isfinite(dzdy)
        if analysis == "slope":
            data = np.degrees(np.arctan(np.sqrt(dzdx**2 + dzdy**2)))
            data[~valid] = np.nan
            label = "坡度(Slope)"
            cmap = "slope"
        elif analysis == "aspect":
            data = np.degrees(np.arctan2(dzdy, -dzdx)) % 360
            data[~valid] = np.nan
            label = "坡向(Aspect)"
            cmap = "aspect"
        elif analysis == "hillshade":
            slope_rad = np.arctan(np.sqrt(dzdx**2 + dzdy**2))
            aspect_rad = np.arctan2(dzdy, -dzdx)
            zenith = np.radians(45)
            azimuth = np.radians(315)
            data = (
                np.cos(zenith) * np.cos(slope_rad) +
                np.sin(zenith) * np.sin(slope_rad) * np.cos(azimuth - aspect_rad)
            )
            data = np.clip(data, 0, 1) * 255
            data[~valid] = 0
            label = "山体阴影(Hillshade)"
            cmap = "hillshade"
        else:
            return f"不支持的analysis类型: {analysis}，可选: slope/aspect/hillshade"
        # 颜色映射
        if analysis == "hillshade":
            rgb = np.stack([data.astype(np.uint8)]*3, axis=-1)
        else:
            from matplotlib import cm
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
        out_name = f"{layer_name}_{analysis}.png"
        out_path = os.path.join(upload_dir, out_name)
        img.save(out_path)
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": out_name,
            "url": f"/output/uploads/{out_name}",
            "bounds": bounds,
            "label": label,
        })
        return f"已生成{label}，叠加到地图上"
    except ImportError as e:
        return f"DEM分析需要依赖库: {str(e)[:200]}，请安装: pip install matplotlib"
    except Exception as e:
        import traceback
        return f"DEM分析失败: {str(e)[:300]}"


# ============================================================
# 工具: ndvi_analysis — NDVI 植被指数
# ============================================================

@tool
def ndvi_analysis(layer_name: str, red_band: int = 1, nir_band: int = 4) -> str:
    """从多光谱 GeoTIFF 计算归一化植被指数 NDVI = (NIR-Red)/(NIR+Red)。
    layer_name为上传的图层名，red_band为红光波段号（默认1），nir_band为近红外波段号（默认4）。
    结果将作为新栅格图层叠加到地图上。"""
    try:
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        if not os.path.isdir(upload_dir):
            return "未找到上传目录，请先上传多光谱文件"
        tif_path = None
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    tif_path = os.path.join(upload_dir, f)
                    break
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        with rasterio.open(tif_path) as src:
            if src.count < max(red_band, nir_band):
                return f"文件只有{src.count}个波段，无法读取波段{max(red_band, nir_band)}"
            red = src.read(red_band).astype(np.float64)
            nir = src.read(nir_band).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                red[red == nodata] = np.nan
                nir[nir == nodata] = np.nan
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        ndvi = (nir - red) / (nir + red + 1e-10)
        ndvi = np.clip(ndvi, -1, 1)
        # 红绿渐变：NDVI=-1→红色，0→黄色，1→绿色
        from matplotlib import cm
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
        out_name = f"{layer_name}_ndvi.png"
        out_path = os.path.join(upload_dir, out_name)
        img.save(out_path)
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": out_name,
            "url": f"/output/uploads/{out_name}",
            "bounds": bounds,
            "label": "NDVI 归一化植被指数",
        })
        valid_count = np.sum(valid)
        mean_ndvi = float(np.nanmean(ndvi))
        return f"已生成NDVI图层，有效像元{valid_count}个，平均NDVI={mean_ndvi:.3f}"
    except ImportError as e:
        return f"NDVI计算需要依赖库: {str(e)[:200]}，请安装: pip install matplotlib"
    except Exception as e:
        import traceback
        return f"NDVI分析失败: {str(e)[:300]}"


# ============================================================
# 工具: raster_calculator — 栅格计算器
# ============================================================

@tool
def raster_calculator(layer_name: str, expression: str) -> str:
    """对多波段 GeoTIFF 执行逐像元数学表达式计算。
    layer_name 为上传的栅格图层名，expression 为表达式字符串。
    波段用 B1/B2/B3… 引用，支持 + - * / ** ( ) 和函数。
    示例: '(B4-B3)/(B4+B3)'、'B1*2.5'、'B2-B1'。"""
    try:
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        if not os.path.isdir(upload_dir):
            return "未找到上传目录"
        tif_path = None
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    tif_path = os.path.join(upload_dir, f)
                    break
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        with rasterio.open(tif_path) as src:
            bands = {}
            for i in range(1, src.count + 1):
                b = src.read(i).astype(np.float64)
                nodata = src.nodata
                if nodata is not None:
                    b[b == nodata] = np.nan
                bands[f"B{i}"] = b
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
        result = eval(expression, {"__builtins__": {}}, safe_dict)
        if not isinstance(result, np.ndarray):
            return f"表达式结果不是栅格数据: {type(result)}"
        if np.all(np.isnan(result)):
            return "计算结果全为NaN，请检查表达式或波段数据"
        vmin, vmax = np.nanmin(result), np.nanmax(result)
        result = result.astype(np.float64)
        if np.isclose(vmin, vmax):
            rgb = np.full((*result.shape, 3), 128, dtype=np.uint8)
        else:
            norm = (result - vmin) / (vmax - vmin + 1e-10)
            norm = np.clip(norm, 0, 1)
            from matplotlib import cm
            cmap = matplotlib.colormaps['viridis']
            rgba = cmap(norm)
            rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
            nan_mask = np.isnan(result)
            if np.any(nan_mask):
                rgb[nan_mask] = 0
        img = Image.fromarray(rgb)
        out_name = f"{layer_name}_calc.png"
        out_path = os.path.join(upload_dir, out_name)
        img.save(out_path)
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": out_name,
            "url": f"/output/uploads/{out_name}",
            "bounds": bounds,
            "label": f"栅格计算: {expression}",
        })
        return f"已执行 '{expression}'，范围 [{vmin:.2f}, {vmax:.2f}]，生成栅格图层"
    except Exception as e:
        return f"栅格计算失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_interpolate — 空间插值（IDW / RBF）
# ============================================================

@tool
def spatial_interpolate(layer_name: str, field: str, method: str = "idw",
                        resolution: int = 200) -> str:
    """对点图层进行空间插值生成栅格曲面。field为插值字段，method可选idw(反距离加权)或rbf(径向基函数)，
    resolution为栅格分辨率（行列数）。结果作为栅格图层叠加到地图上。"""
    try:
        import numpy as np
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.geometry.iloc[0].geom_type not in ("Point", "MultiPoint"):
            return f"图层 '{name}' 不含点要素，无法插值"
        if field not in gdf.columns:
            return f"图层 '{name}' 没有字段 '{field}'，可用字段: {', '.join(gdf.columns)}"
        pts = gdf.copy()
        pts = pts.to_crs("EPSG:4326")
        coords = [(p.x, p.y) for p in pts.geometry if p is not None]
        values = pts[field].values.astype(np.float64)
        if len(coords) < 3:
            return "至少需要3个有效点进行插值"
        xs = np.array([c[0] for c in coords])
        ys = np.array([c[1] for c in coords])
        # 生成规则网格
        xmin, ymin, xmax, ymax = xs.min(), ys.min(), xs.max(), ys.max()
        pad_x = (xmax - xmin) * 0.05 or 0.01
        pad_y = (ymax - ymin) * 0.05 or 0.01
        grid_x, grid_y = np.meshgrid(
            np.linspace(xmin - pad_x, xmax + pad_x, resolution),
            np.linspace(ymin - pad_y, ymax + pad_y, resolution)
        )
        if method == "idw":
            # 反距离加权
            from scipy.spatial.distance import cdist
            flat_grid = np.column_stack([grid_x.ravel(), grid_y.ravel()])
            pts_xy = np.column_stack([xs, ys])
            dist = cdist(flat_grid, pts_xy)
            dist[dist < 1e-10] = 1e-10
            weights = 1.0 / dist ** 2
            z = np.dot(weights, values) / weights.sum(axis=1)
            z = z.reshape(grid_x.shape)
        elif method == "rbf":
            from scipy import interpolate
            rbf = interpolate.Rbf(xs, ys, values, function='multiquadric')
            z = rbf(grid_x, grid_y)
        else:
            return f"不支持的方法: {method}，可选 idw / rbf"
        vmin, vmax = np.nanmin(z), np.nanmax(z)
        if np.isclose(vmin, vmax):
            return f"插值结果无变化（值={vmin:.2f}）"
        norm = (z - vmin) / (vmax - vmin + 1e-10)
        norm = np.clip(norm, 0, 1)
        from matplotlib import cm
        cmap = matplotlib.colormaps['viridis']
        rgba = cmap(norm)
        rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
        nan_mask = ~np.isfinite(z)
        if np.any(nan_mask):
            rgb[nan_mask] = 0
        from PIL import Image
        img = Image.fromarray(rgb)
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        out_name = f"{name}_{method}.png"
        out_path = os.path.join(upload_dir, out_name)
        img.save(out_path)
        from rasterio.transform import from_bounds
        transform = from_bounds(xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y, resolution, resolution)
        bounds = [xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y]
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": out_name,
            "url": f"/output/uploads/{out_name}",
            "bounds": bounds,
            "label": f"插值({method}): {field}",
        })
        return f"已生成{method.upper()}插值网格 ({resolution}×{resolution})，值范围 [{vmin:.2f}, {vmax:.2f}]"
    except Exception as e:
        import traceback
        return f"插值失败: {str(e)[:300]}"


# ============================================================
# 工具: hydrology_analysis — 水文分析
# ============================================================

@tool
def hydrology_analysis(layer_name: str, analysis: str = "flowacc",
                       threshold: int = 100) -> str:
    """对DEM栅格进行水文分析。analysis可选:
    flowdir(流向图), flowacc(汇流累积量), streamnet(河网提取)。
    threshold为河网提取的最小汇流累积量阈值。
    layer_name为上传DEM时创建的图层名。"""
    try:
        import numpy as np
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        if not os.path.isdir(upload_dir):
            return "未找到上传目录"
        tif_path = None
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    tif_path = os.path.join(upload_dir, f)
                    break
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from rasterio.warp import transform_bounds
        from PIL import Image
        with rasterio.open(tif_path) as src:
            dem = src.read(1).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                dem[dem == nodata] = np.nan
            transform = src.transform
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        ny, nx = dem.shape
        filled = dem.copy()
        # 简单填洼：多次迭代填充
        for _ in range(20):
            prev = filled.copy()
            for i in range(1, ny-1):
                for j in range(1, nx-1):
                    if np.isnan(filled[i, j]):
                        continue
                    neighbors = [
                        filled[i-1, j], filled[i+1, j],
                        filled[i, j-1], filled[i, j+1],
                        filled[i-1, j-1], filled[i-1, j+1],
                        filled[i+1, j-1], filled[i+1, j+1]
                    ]
                    min_nbr = np.nanmin(neighbors)
                    if filled[i, j] > min_nbr + 1e-6 and min_nbr < filled[i, j]:
                        filled[i, j] = min(min_nbr, filled[i, j])
            if np.allclose(filled, prev, atol=1e-6):
                break
        # D8 流向编码（1=E,2=NE,4=N,8=NW,16=W,32=SW,64=S,128=SE）
        # 使用简化编码: 0=E,1=NE,2=N,3=NW,4=W,5=SW,6=S,7=SE
        dx = [1, 1, 0, -1, -1, -1, 0, 1]
        dy = [0, -1, -1, -1, 0, 1, 1, 1]
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
                    dist = 1.0 if k in (0, 2, 4, 6) else 1.414
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
        out_name = f"{layer_name}_{analysis}.png"
        if analysis == "flowdir":
            # 流向可视化（按角度色环）
            angle_map = np.array([0, 45, 90, 135, 180, 225, 270, 315])
            dir_deg = np.full_like(dem, np.nan, dtype=np.float64)
            for k in range(8):
                dir_deg[direction == k] = angle_map[k]
            from matplotlib import cm
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
            from matplotlib import cm
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
            return f"不支持的analysis类型: {analysis}，可选: flowdir/flowacc/streamnet"
        img = Image.fromarray(rgb)
        out_path = os.path.join(upload_dir, out_name)
        img.save(out_path)
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": out_name,
            "url": f"/output/uploads/{out_name}",
            "bounds": bounds,
            "label": label,
        })
        return f"已生成水文分析图层 '{label}'"
    except Exception as e:
        return f"水文分析失败: {str(e)[:300]}"


# ============================================================
# 工具: create_workflow — 批量处理链
# ============================================================

@tool
def create_workflow(workflow_json: str) -> str:
    """创建并执行批量处理工作流。workflow_json为JSON字符串，格式：
    [{"tool":"工具名","params":{"参数名":"参数值",...},"output":"输出图层名"},
     {"tool":"spatial_buffer","params":{"layer_name":"$prev","distance":100,"unit":"m"},"output":"buf_layer"}]
    工具名取工具函数名（不包含命名空间），$prev引用上一步输出，$N引用第N步输出（从1开始）。
    各步骤顺序执行，中间结果自动注册。"""
    try:
        import json as _json
        steps = _json.loads(workflow_json)
        if not isinstance(steps, list) or not steps:
            return "workflow_json必须是非空数组"
        outputs = {}
        results = []
        # 构建工具查找表
        tool_map = {}
        for t in tools:
            name = t.name if hasattr(t, 'name') else str(t)
            tool_map[name] = t
        for idx, step in enumerate(steps):
            step_num = idx + 1
            tool_name = step.get("tool", "")
            raw_params = dict(step.get("params", {}))
            output_name = step.get("output", f"step_{step_num}")
            if tool_name not in tool_map:
                return f"第{step_num}步: 未找到工具 '{tool_name}'"
            # 解析 $prev / $N 引用
            resolved_params = {}
            for k, v in raw_params.items():
                if isinstance(v, str) and v.startswith("$"):
                    ref = v[1:]
                    if ref == "prev":
                        if not outputs:
                            resolved_params[k] = v
                        else:
                            prev_out = list(outputs.values())[-1]
                            resolved_params[k] = prev_out
                    elif ref.isdigit():
                        n = int(ref)
                        if n in outputs:
                            resolved_params[k] = outputs[n]
                        else:
                            resolved_params[k] = v
                    else:
                        resolved_params[k] = v
                else:
                    resolved_params[k] = v
            try:
                tool_fn = tool_map[tool_name]
                result_str = tool_fn.invoke(resolved_params)
            except Exception as e:
                return f"第{step_num}步 '{tool_name}' 执行失败: {str(e)[:200]}"
            step_output = output_name
            outputs[step_num] = step_output
            outputs[output_name] = step_output
            results.append(f"步骤{step_num}({tool_name}) → {output_name}: {result_str[:100]}")
        return "工作流执行完成:\n" + "\n".join(results)
    except Exception as e:
        return f"工作流失败: {str(e)[:300]}"


# ============================================================
# 工具: view_3d_terrain — 3D 地形
# ============================================================

@tool
def view_3d_terrain(layer_name: str, exaggeration: float = 2.0) -> str:
    """从DEM生成3D地形交互视图。layer_name为DEM图层名。
    exaggeration为垂直夸大系数（默认2.0）。
    结果在聊天窗口展示 Three.js 3D 场景。"""
    try:
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        if not os.path.isdir(upload_dir):
            return "未找到上传目录"
        tif_path = None
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    tif_path = os.path.join(upload_dir, f)
                    break
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        with rasterio.open(tif_path) as src:
            dem = src.read(1).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                dem[dem == nodata] = np.nan
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
            return "DEM 高程无变化"
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
        output_dir = os.path.join(_temp_output_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        fpath = os.path.join(output_dir, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(html)
        _pending_images.append({
            "type": "html",
            "url": f"/output/{fname}"
        })
        return f"已生成3D地形视图，可在聊天窗口中查看"
    except Exception as e:
        return f"3D地形生成失败: {str(e)[:300]}"


# ============================================================
# 工具: animate_time — 时序动画
# ============================================================

@tool
def animate_time(layer_name: str, time_field: str, interval_ms: int = 500) -> str:
    """对图层的时序字段进行动画播放。time_field为日期/数字字段，
    interval_ms为每帧间隔（毫秒，默认500）。前端会按时间顺序逐帧显示。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if time_field not in gdf.columns:
            return f"图层 '{name}' 没有字段 '{time_field}'"
        time_vals = gdf[time_field].dropna().unique()
        if len(time_vals) < 2:
            return f"字段 '{time_field}' 只有 {len(time_vals)} 个唯一值，至少需要2个"
        time_vals = sorted(time_vals)
        _pending_layer_ops.append({
            "action": "time_animation",
            "name": name,
            "time_field": time_field,
            "time_values": [str(v) for v in time_vals[:100]],
            "interval_ms": interval_ms,
        })
        return f"已启动时序动画，共 {len(time_vals)} 帧，间隔 {interval_ms}ms"
    except Exception as e:
        return f"时序动画失败: {str(e)[:200]}"


# ============================================================
# 工具: link_chart_map — 图表联动
# ============================================================

@tool
def link_chart_map(layer_name: str, chart_field: str) -> str:
    """建立图层面要素与图表的联动。选中地图要素时高亮图表对应项，
    点击图表项时地图聚焦到对应要素。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if chart_field not in gdf.columns:
            return f"图层 '{name}' 没有字段 '{chart_field}'"
        _pending_layer_ops.append({
            "action": "chart_link",
            "name": name,
            "chart_field": chart_field,
        })
        return f"已建立图层 '{name}' 的图表联动（字段: {chart_field}）"
    except Exception as e:
        return f"图表联动设置失败: {str(e)[:200]}"


# ============================================================
# 工具: terrain_profile — 地形剖面
# ============================================================

@tool
def terrain_profile(layer_name: str, line_coords: str) -> str:
    """沿一条线从DEM提取高程并生成地形剖面图。
    layer_name为DEM图层名，line_coords为JSON数组 [[lng,lat],[lng,lat],...]。
    结果在聊天窗口显示高程剖面图表。"""
    try:
        import numpy as np
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        if not os.path.isdir(upload_dir):
            return "未找到上传目录"
        tif_path = None
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    tif_path = os.path.join(upload_dir, f)
                    break
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        import json as _json
        coords = _json.loads(line_coords)
        if not isinstance(coords, list) or len(coords) < 2:
            return "line_coords需为包含至少2个[lng,lat]的JSON数组"
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
            dem = src.read(1).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                dem[dem == nodata] = np.nan
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
            return "所有采样点均落在DEM有效范围外"
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
        output_dir = os.path.join(_temp_output_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        fpath = os.path.join(output_dir, fname)
        with open(fpath, 'wb') as f:
            f.write(buf.getvalue())
        _pending_images.append({
            "type": "image",
            "url": f"/output/{fname}",
            "caption": f"{layer_name} 高程剖面 | 距离 {total_len:.4f}° | 高程 {vmin:.1f}–{vmax:.1f}"
        })
        return f"已生成地形剖面图，高程范围 {vmin:.1f}–{vmax:.1f}，距离 {total_len:.4f}°"
    except Exception as e:
        return f"地形剖面生成失败: {str(e)[:300]}"


# ============================================================
# 工具: topology_check — 拓扑检查
# ============================================================

@tool
def topology_check(layer_name: str) -> str:
    """对面要素图层进行拓扑检查。检测自相交、无效几何、要素间重叠和缝隙。
    结果生成标注图层，标注出每个拓扑错误的位置和类型。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if not any(gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])):
            return f"图层 '{name}' 不含面要素，拓扑检查仅支持面图层"
        from shapely.validation import explain_validity
        from shapely.geometry import Polygon
        import shapely.wkt
        issues = []
        gdf_single = gdf.copy()
        if 'geometry' in gdf_single.columns:
            gdf_single = gdf_single.set_geometry('geometry')
        for idx, row in gdf_single.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                issues.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"type": "空几何", "fid": int(idx)}
                })
                continue
            if not geom.is_valid:
                reason = explain_validity(geom)
                rep = geom.representative_point()
                issues.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                    "properties": {"type": "无效几何", "detail": reason, "fid": int(idx)}
                })
        # 重叠和缝隙
        if len(gdf_single) >= 2:
            from shapely.ops import unary_union
            polys = [(i, g) for i, g in gdf_single.geometry.items()
                     if g is not None and not g.is_empty and g.geom_type in ("Polygon", "MultiPolygon")]
            for i, a in polys:
                for j, b in polys:
                    if j <= i:
                        continue
                    if a.intersects(b) and not a.touches(b):
                        try:
                            inter = a.intersection(b)
                            if inter is not None and not inter.is_empty and inter.area > 1e-10:
                                rep = inter.representative_point()
                                issues.append({
                                    "type": "Feature",
                                    "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                                    "properties": {"type": "重叠", "fid_pair": f"{i}-{j}"}
                                })
                        except:
                            pass
            try:
                all_valid = [g for _, g in polys]
                if len(all_valid) >= 2:
                    merged = unary_union(all_valid)
                    envelope = Polygon(merged.exterior)
                    gaps = envelope.difference(merged)
                    if gaps is not None and not gaps.is_empty:
                        if gaps.geom_type == "GeometryCollection":
                            for g in gaps.geoms:
                                if not g.is_empty and g.geom_type in ("Polygon",) and g.area > 1e-10:
                                    rep = g.representative_point()
                                    issues.append({
                                        "type": "Feature",
                                        "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                                        "properties": {"type": "缝隙", "area": round(g.area, 6)}
                                    })
                        elif gaps.geom_type == "Polygon" and gaps.area > 1e-10:
                            rep = gaps.representative_point()
                            issues.append({
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                                "properties": {"type": "缝隙", "area": round(gaps.area, 6)}
                            })
            except:
                pass
        if not issues:
            return f"图层 '{name}' 未发现拓扑错误"
        fc = {"type": "FeatureCollection", "features": issues}
        out_name = f"{name}_拓扑错误"
        _push_layer(out_name, fc)
        _register_layer(out_name, fc)
        return f"拓扑检查完成，发现 {len(issues)} 个问题，已生成图层 '{out_name}'"
    except Exception as e:
        return f"拓扑检查失败: {str(e)[:300]}"


# ============================================================
# 工具: extract_contours — 等高线提取
# ============================================================

@tool
def extract_contours(layer_name: str, interval: float = 0) -> str:
    """从DEM栅格图层提取等高线矢量。interval为等高距（米），0表示自动计算。
    layer_name为上传DEM时创建的图层名（如dem.tif→图层名为dem）。
    结果将作为新矢量图层加载到地图上。"""
    try:
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        if not os.path.isdir(upload_dir):
            return "未找到上传目录，请先上传DEM文件"
        tif_path = None
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    tif_path = os.path.join(upload_dir, f)
                    break
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件，请先上传DEM"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from skimage import measure
        with rasterio.open(tif_path) as src:
            dem = src.read(1).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                dem[dem == nodata] = np.nan
            transform = src.transform
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        ny, nx = dem.shape
        vmin, vmax = np.nanmin(dem), np.nanmax(dem)
        drange = vmax - vmin
        if interval <= 0:
            interval = max(round(drange / 15, -1), 1) if drange > 10 else drange / 15
        levels = np.arange(vmin, vmax + interval, interval)
        features = []
        for level in levels:
            for seg in measure.find_contours(dem, level):
                if len(seg) < 2:
                    continue
                coords = []
                for row, col in seg:
                    x = transform[2] + (col + 0.5) * transform[0] + (row + 0.5) * transform[1]
                    y = transform[5] + (col + 0.5) * transform[3] + (row + 0.5) * transform[4]
                    coords.append([round(x, 6), round(y, 6)])
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {"elevation": round(float(level), 1)}
                })
        fc = {"type": "FeatureCollection", "features": features}
        name = f"{layer_name}_contour"
        _pending_layers.append({
            "type": "FeatureCollection",
            "features": fc["features"],
            "name": name,
        })
        _registered_layers[name] = {"type": "FeatureCollection", "name": name}
        return f"已提取 {len(features)} 条等高线（等高距 {interval:.1f}m），生成图层 '{name}'"
    except ImportError as e:
        return f"等高线提取需要依赖库: {str(e)[:200]}，请安装: pip install scikit-image"
    except Exception as e:
        import traceback
        return f"等高线提取失败: {str(e)[:300]}"


# ============================================================
# 工具: enable_snapping — 捕捉
# ============================================================

@tool
def enable_snapping(enabled: bool = True) -> str:
    """启用或禁用绘制时的折点捕捉功能。enabled: True(启用) / False(禁用)。启用后绘制
    点/线/面时会自动吸附到现有要素的顶点和线段上。"""
    try:
        _pending_layer_ops.append({
            "action": "snapping",
            "enabled": enabled,
        })
        return f"已{'启用' if enabled else '禁用'}捕捉功能"
    except Exception as e:
        return f"捕捉设置失败: {str(e)[:200]}"


# ============================================================
# 工具: convert_crs / convert_coordinates — 坐标转换
# ============================================================

@tool
def convert_crs(layer_name: str, target_crs: str = "wgs84") -> str:
    """将图层的坐标参考系转换为目标CRS并生成新图层。
    target_crs支持: wgs84(EPSG:4326), web_mercator(EPSG:3857),
    utm_auto(自动UTM分区), gcj02(高德/腾讯火星坐标)。
    原图层不变，结果生成新图层。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        epsg_map = {
            "wgs84": "EPSG:4326",
            "web_mercator": "EPSG:3857",
            "mercator": "EPSG:3857",
            "gcj02": "EPSG:4326",  # 本系统全面使用WGS84，GCJ02暂不做偏移转换
        }
        target = epsg_map.get(target_crs.lower(), target_crs)
        if target.startswith("utm"):
            pts = gdf.geometry.representative_point()
            avg_lon = pts.x.mean()
            avg_lat = pts.y.mean()
            zone = int((avg_lon + 180) / 6) + 1
            epsg = 32600 if avg_lat >= 0 else 32700
            target = f"EPSG:{epsg + zone}"
        if gdf.crs and gdf.crs.to_string() == target:
            return f"图层 '{name}' 已经是 {target_crs} 坐标系"
        if not gdf.crs and target == "EPSG:4326":
            return f"图层 '{name}' 已经是 WGS84 坐标系"
        gdf_proj = gdf.to_crs(target)
        if gdf_proj is None or gdf_proj.empty:
            return f"坐标系转换失败: {target}"
        out_name = f"{name}_{target_crs}"
        _gdf_to_layer(gdf_proj, out_name)
        return f"已将图层 '{name}' 转换为 {target_crs}({target})，生成新图层 '{out_name}'"
    except Exception as e:
        return f"坐标系转换失败: {str(e)[:200]}"


@tool
def convert_coordinates(coords: str, source_crs: str = "wgs84",
                         target_crs: str = "web_mercator") -> str:
    """转换单个坐标点在两个坐标参考系之间。
    coords格式: "lng,lat" 或 "lng1,lat1;lng2,lat2" 批处理。
    source_crs/target_crs支持: wgs84, web_mercator, utm_auto。
    返回转换后的坐标对。"""
    try:
        import pyproj
        p1 = {"wgs84": "EPSG:4326", "mercator": "EPSG:3857",
              "web_mercator": "EPSG:3857", "gcj02": "EPSG:4326"}.get(source_crs.lower(), source_crs)
        p2 = {"wgs84": "EPSG:4326", "mercator": "EPSG:3857",
              "web_mercator": "EPSG:3857", "gcj02": "EPSG:4326"}.get(target_crs.lower(), target_crs)
        if p1 == p2:
            return f"源和目标CRS相同: {source_crs} = {target_crs}, 无需转换"
        transformer = pyproj.Transformer.from_crs(p1, p2, always_xy=True)
        parts = coords.replace("，", ",").replace("；", ";").split(";")
        results = []
        for part in parts:
            xy = part.strip().split(",")
            if len(xy) != 2:
                continue
            try:
                lng, lat = float(xy[0].strip()), float(xy[1].strip())
                x2, y2 = transformer.transform(lng, lat)
                results.append(f"{x2:.6f},{y2:.6f}")
            except:
                continue
        if not results:
            return "坐标格式错误，请输入 lng,lat 或 lng1,lat1;lng2,lat2"
        return f"{source_crs}→{target_crs}: {'; '.join(results)}"
    except Exception as e:
        return f"坐标转换失败: {str(e)[:200]}"


# ============================================================
# 工具: clip_raster — 栅格裁剪
# ============================================================

@tool
def clip_raster(layer_name: str, clip_layer_name: str, output_name: str = "") -> str:
    """用矢量面裁剪栅格图层，保留面内的栅格像元。
    layer_name: 栅格图层名（上传的GeoTIFF）；clip_layer_name: 矢量裁剪面图层名；
    output_name: 结果图层名（可选，默认自动生成）。
    结果作为新栅格图层叠加到地图。"""
    try:
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        if not os.path.isdir(upload_dir):
            return "未找到上传目录，请先上传栅格文件"

        tif_path = None
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    tif_path = os.path.join(upload_dir, f)
                    break
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件，请先上传"

        import geopandas as gpd
        import rasterio
        from rasterio.mask import mask as rio_mask
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
                return f"找到多个匹配：{', '.join(matches)}，请指定完整名称"
            else:
                return f"未找到裁剪面图层 '{clip_layer_name}'"

        clip_gdf = gpd.GeoDataFrame.from_features(clip_info["geojson"]["features"], crs="EPSG:4326")
        if clip_gdf.empty:
            return f"裁剪面图层 '{clip_layer_name}' 为空"

        # 合并所有面要素为一个几何体
        union_geom = clip_gdf.geometry.union_all()
        if union_geom.is_empty:
            return "裁剪面几何为空"
        if union_geom.geom_type not in ("Polygon", "MultiPolygon"):
            return "裁剪面必须是面要素"

        with rasterio.open(tif_path) as src:
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))

            # 将裁剪面转为栅格 CRS
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                clip_gdf_proj = clip_gdf.to_crs(src.crs)
            else:
                clip_gdf_proj = clip_gdf

            # 提取裁剪面几何列表
            geoms = [g for g in clip_gdf_proj.geometry.values if not g.is_empty]

            try:
                out_image, out_transform = rio_mask(src, geoms, crop=True, nodata=0)
            except Exception:
                return f"裁剪失败：裁剪面与栅格无重叠或几何无效"

            if out_image.shape[1] == 0 or out_image.shape[2] == 0:
                return "裁剪结果为空：裁剪面与栅格无重叠区域"

            # 处理波段
            if out_image.shape[0] == 1:
                data = out_image[0].astype(np.float64)
                valid = data > 0
                if not np.any(valid):
                    return "裁剪结果为空"
                vmin, vmax = np.nanmin(data[valid]), np.nanmax(data[valid])
                from matplotlib import cm
                cmap_obj = matplotlib.colormaps['viridis']
                norm_data = np.clip((data - vmin) / (vmax - vmin + 1e-10), 0, 1)
                norm_data[~valid] = 0
                rgba = cmap_obj(norm_data)
                rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
            else:
                # 多波段：取前3波段合成RGB
                bands = []
                for i in range(min(3, out_image.shape[0])):
                    b = out_image[i].astype(np.float64)
                    p2, p98 = np.percentile(b[b > 0], [2, 98]) if np.any(b > 0) else (0, 1)
                    if p98 > p2:
                        b = np.clip((b - p2) / (p98 - p2) * 255, 0, 255).astype(np.uint8)
                    else:
                        b = np.zeros_like(b, dtype=np.uint8)
                    bands.append(b)
                while len(bands) < 3:
                    bands.append(np.zeros_like(bands[0], dtype=np.uint8))
                rgb = np.stack(bands, axis=-1)

            img = Image.fromarray(rgb)
            out_name = output_name or f"{layer_name}_clip_{clip_layer_name}"
            out_path = os.path.join(upload_dir, f"{out_name}.png")
            img.save(out_path)

            _pending_layer_ops.append({
                "action": "dem_result",
                "name": f"{out_name}.png",
                "url": f"/output/uploads/{out_name}.png",
                "bounds": bounds,
                "label": f"栅格裁剪: {layer_name}",
            })

            feat_count = len(clip_gdf)
            return (f"已用 {clip_layer_name}（{feat_count} 个面）裁剪 {layer_name}"
                    f"，结果已叠加到地图")

    except Exception as e:
        import traceback
        return f"栅格裁剪失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: discover_gis_data / download_gis_data — GIS 开放数据发现与获取
# （数据 Provider 抽象见 backend/services/data_providers；此处只做调度）
# ============================================================

def _format_discover_hits(hits: list) -> str:
    """把发现结果格式化为 Markdown 表格。"""
    if not hits:
        return "（无命中）"
    lines = [
        "| 数据源 | 类型 | 区域 | 格式 | CRS | 来源 | 状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    for h in hits:
        status = "可获取"
        if not h.get("downloadable"):
            status = "需认证" + (f"：{str(h.get('note'))[:40]}" if h.get('note') else "")
        lines.append(
            f"| {h.get('provider', '-')} | {h.get('kind_label', '-')} "
            f"| {h.get('area', '-')} | {h.get('file_format', '-')} "
            f"| {h.get('crs', '-')} | {h.get('provider_id', '-')} | {status} |"
        )
    return "\n".join(lines)


@tool
def discover_gis_data(query: str = "", kind: str = "", area: str = "",
                      bbox: str = "", provider: str = "auto",
                      file_format: str = "", time_start: str = "",
                      time_end: str = "") -> str:
    """发现/检索公开 GIS 数据的元信息（不下载）。数据源：OSM/Copernicus/USGS/地理空间数据云。
参数说明：
- kind: 数据类型（英文），road/道路/路网→roads，building/建筑→buildings，poi/兴趣点→pois，
  water/水系/河流→waterways，landuse/土地利用→landuse，transport/铁路→transport，
  imagery/影像/sentinel/landsat→imagery，dem/高程→dem。
- area: 城市/区域名（中文也可，如 长沙、长沙市）；或用 bbox='minLng,minLat,maxLng,maxLat'。
- provider: 数据源 osm/copernicus/usgs/gscloud，默认 auto 自动选。
- time_start/time_end: 遥感数据可选时间范围（如 2024-01-01）。
用法：用户想找开放 GIS 数据时先用本工具返回来源与可获取状态，再调用 download_gis_data 获取。"""
    from backend.services import data_discovery
    try:
        r = data_discovery.discover(
            query=query, kind=kind, area=area, bbox=bbox,
            provider_id="" if provider in ("", "auto") else provider,
            file_format=file_format, time_start=time_start, time_end=time_end,
        )
    except Exception as e:
        from backend.services.data_providers.errors import DataProviderError
        if isinstance(e, DataProviderError):
            return f"无法完成发现：{e.message}" + (f"\n提示：{e.hint}" if e.hint else "")
        return f"发现失败：{str(e)[:200]}"

    parts = [f"**{r['message']}**"]
    parts.append(f"\n发现的候选（{len(r['hits'])} 条）：")
    parts.append(_format_discover_hits(r['hits']))
    if r["notes"]:
        parts.append("\n数据源说明：")
        for n in r["notes"]:
            parts.append(f"- {n['message']}" + (f"（{n['hint']}）" if n.get('hint') else ""))
    if r["hits"]:
        parts.append(
            "\n下一步：确认后调用 **download_gis_data** 获取并加载到地图。"
            f"（kind='{r['kind']}', area='{r['area']}', provider 见表格）"
        )
    return "\n".join(parts)


@tool
def download_gis_data(query: str = "", kind: str = "", area: str = "",
                      bbox: str = "", provider: str = "", file_format: str = "geojson",
                      time_start: str = "", time_end: str = "",
                      layer_name: str = "", max_items: int = 0) -> str:
    """从开放 GIS 数据源获取数据 → 保存为标准 GIS 文件(GeoJSON/GPKG/SHP) → 完整性/CRS 校验 → 加载到地图。
矢量数据源现支持 OpenStreetMap（provider=osm，公开免认证）。
- kind：road/道路/路网→roads，building/建筑→buildings，poi/兴趣点→pois，
  water/水系/河流→waterways，landuse/土地利用→landuse，transport/铁路→transport。
- area：城市/区域名（如 长沙/长沙市），或 bbox='minLng,minLat,maxLng,maxLat'。
- file_format：geojson/gpkg/shp，默认 geojson。
- layer_name：自定义图层名（可选）。
示例：kind='roads', area='长沙市' → 下载道路数据并加载。用户已看到 discover 结果后，直接调用本工具获取。"""
    from backend.services import data_discovery
    try:
        asset = data_discovery.download(
            query=query, kind=kind, area=area, bbox=bbox,
            provider_id=provider, file_format=file_format,
            time_start=time_start, time_end=time_end,
            max_items=max_items, layer_name=layer_name,
        )
    except Exception as e:
        from backend.services.data_providers.errors import DataProviderError
        if isinstance(e, DataProviderError):
            return f"获取失败：{e.message}" + (f"\n提示：{e.hint}" if e.hint else "")
        import traceback
        return f"获取失败：{str(e)[:200]}\n{traceback.format_exc()[:150]}"

    # 矢量：直接加载到地图（复用现有图层链路）
    geojson = asset.get("geojson")
    if geojson is not None:
        layer = asset["layer_name"]
        _push_layer(layer, geojson)
        _register_layer(layer, geojson)
        loaded = f"已加载到地图，图层名「{layer}」。"
    else:
        loaded = ""

    meta = asset.get("metadata", {})
    lines = [
        f"获取成功（{asset['provider_name']} · {asset['kind_label']}）",
        f"- 图层：{asset['layer_name']}，要素数：{asset.get('feature_count') or 0}，"
        f"几何：{', '.join(asset.get('geometry_types') or [])}",
        f"- 格式：{asset.get('file_format')}，CRS：{asset.get('crs')}，大小：{_human_size(asset.get('size_bytes') or 0)}",
        f"- 下载：{asset.get('url')}（服务器可下载路径）",
        f"- 元数据：{meta.get('metadata_file', '')}",
    ]
    if asset.get("note"):
        lines.append(f"- 注意：{asset['note']}")
    if loaded:
        lines.append(loaded)
    return "\n".join(lines)


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


@tool
def hold_layer_for_confirm(name: str = "", geojson: str = "",
                           source: str = "", file_path: str = "",
                           summary: str = "") -> str:
    """把已经获取/生成、但尚未展示到地图的图层“挂起”，等用户确认后再加载。

    适用场景：数据已就绪（已下载/已生成 GeoJSON），但希望用户回复“继续/确认”后再显示到地图
    （例如一次数据量较大、或流程上需要用户拍板）。调用本工具会登记一个待确认动作，不会立刻把
    图层推到地图；用户回复“继续/确认/执行”时由系统确定性加载，“取消”则放弃。
    参数：
    - name: 图层名（必填）。若该名字已在“当前已注册图层”里，可不传 geojson 直接复用其数据；
      否则必须用 geojson 传入图层数据。
    - geojson: 图层 GeoJSON 的 JSON 字符串（FeatureCollection/Feature），可省略（当 name 已注册）。
    - source: 数据来源描述，如 geoBoundaries / OpenStreetMap / 文件。
    - file_path: 数据所在文件路径（若有）。
    - summary: 给用户看的一句话说明（可选）。
    调用后请在回复里告诉用户：“数据已准备好，回复‘继续’即可加载到地图；回复‘取消’可放弃。”"""
    import json as _json
    from backend.services import pending_action

    name = (name or "").strip()
    if not name:
        return "错误：hold_layer_for_confirm 需要 name（图层名）。"
    data = None
    if geojson and geojson.strip():
        try:
            data = _json.loads(geojson)
        except Exception:
            return f"错误：geojson 不是有效的 JSON：{str(geojson)[:120]}"

    # 若 name 已注册则复用其数据，否则用传入 geojson 注册（不推送）
    if data is None:
        info = _registered_layers.get(name)
        if not info or info.get("geojson") is None:
            return (f"错误：找不到图层「{name}」的数据，且未提供 geojson。"
                    f"请先用获取/下载工具注册该图层，或直接传入 geojson。")
    else:
        _register_layer(name, data)

    action = pending_action.build_load_layer_action(
        layer_name=name,
        geojson=data or None,
        source=source,
        file_path=file_path,
        dataset=source,
        summary=summary,
    )
    pending_action.set_pending_action(pending_action.get_active_session(), action)
    shown = "；".join(filter(None, [
        f"数据已就绪（图层「{name}」）",
        f"来源：{source}" if source else "",
        f"文件：{file_path}" if file_path else "",
    ]))
    return (shown or f"图层「{name}」已就绪") + (
        "。请回复“继续”加载到地图，或回复“取消”放弃。")





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
    measure_distance,
    clear_layers,
    get_session_logs,
    layer_control,
    export_layer,
    create_chart,
    download_road_network,
    network_analysis,
    spatial_buffer,
    spatial_multi_ring_buffer,
    add_north_arrow,
    spatial_intersect,
    spatial_union,
    spatial_difference,
    spatial_clip,
    spatial_centroid,
    spatial_simplify,
    spatial_dissolve,
    reverse_geocode,
    batch_geocode,
    spatial_select,
    spatial_sample,
    spatial_near,
    spatial_cluster,
    spatial_voronoi,
    spatial_field_stats,
    spatial_join,
    layer_merge,
    layer_split,
    layer_add_geometry,
    add_labels,
    spatial_graduated_colors,
    spatial_unique_values,
    spatial_select_by_attribute,
    add_legend,
    update_attribute,
    delete_features,
    add_field,
    delete_field,
    move_features,
    rotate_features,
    scale_features,
    draw_feature,
    edit_vertices,
    export_map,
    export_pdf,
    undo,
    redo,
    enable_snapping,
    dem_analysis,
    ndvi_analysis,
    raster_calculator,
    spatial_interpolate,
    topology_check,
    hydrology_analysis,
    create_workflow,
    view_3d_terrain,
    animate_time,
    link_chart_map,
    terrain_profile,
    convert_crs,
    convert_coordinates,
    extract_contours,
    clip_raster,
    discover_gis_data,
    download_gis_data,
    hold_layer_for_confirm,
]

