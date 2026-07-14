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
def get_pending_state():
    return {
        "layers": list(_pending_layers),
        "images": list(_pending_images),
        "aoi_suggestions": _pending_aoi_suggestions.get("latest"),
        "heatmap": _pending_heatmap.get("latest"),
        "clear_layers": _clear_layers_flag,
        "registered_layers": dict(_registered_layers),
        "layer_ops": list(_pending_layer_ops),
    }


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


def _register_layer(name: str, geojson: dict):
    """注册图层供 AI 后续查询"""
    try:
        features = geojson.get("features", [])
        types = set()
        for f in features:
            geom = f.get("geometry", {}) or {}
            if geom.get("type"):
                types.add(geom["type"])
        _registered_layers[name] = {
            "name": name,
            "feature_count": len(features),
            "geometry_types": list(types) if types else ["未知"],
            "geojson": geojson,
        }
    except Exception:
        pass


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
    """搜索网络信息，返回相关网页的标题、链接和摘要。用于搜索最新新闻、数据、资料等"""
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
    """把内容保存成文件，支持CSV、GeoJSON、TXT等格式。文件名不要加 output/ 前缀"""
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
    """执行Python GIS代码（沙箱隔离），返回执行结果及耗时。
    可用库：geopandas, shapely, numpy, pandas, matplotlib, pyecharts, json, math, re, datetime, io, tempfile, requests, pyproj, rasterio, osmnx
    要在地图上显示结果，print出GeoJSON字符串即可。
    要生成图表，用 plt.savefig('chart_xxx.png')（相对路径）。
    AMAP_KEY 通过 _AMAP_KEY 变量直接获取。"""
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
    """高德地图 POI 搜索。搜索兴趣点（餐厅、银行、超市等），自动转换坐标并加载到地图。
    keywords: 搜索关键词，如"麦当劳""肯德基"
    city: 城市名，如"广州"（可选，不填则全国搜索）
    location: 中心点坐标 "经度,纬度"（可选，传此参数则进行周边搜索）
    radius: 搜索半径（周边搜索时有效），单位米，默认1000"""
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
# 工具: unified_aoi_search / unified_aoi_extract（百度 AOI）
# ============================================================

@tool
def unified_aoi_search(query: str) -> str:
    """搜索地点轮廓，返回候选列表在聊天框显示"""
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
    """根据用户选择的候选提取建筑轮廓（百度数据源），转WGS84加载到地图"""
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
def get_registered_layers() -> str:
    """查看当前地图上所有已加载的图层列表，包括图层名、每个图层的要素数量和几何类型"""
    if not _registered_layers:
        return "当前没有已加载的图层"
    lines = [f"当前共 {len(_registered_layers)} 个图层："]
    for name, info in _registered_layers.items():
        types = ", ".join(info.get("geometry_types", ["未知"]))
        lines.append(f"  - {name}：{info['feature_count']} 个要素，类型：{types}")
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
    return (
        f"图层：{info['name']}\n"
        f"要素数：{info['feature_count']}\n"
        f"几何类型：{', '.join(info['geometry_types'])}\n"
        f"数据预览：\n{preview}"
    )


# ============================================================
# 工具: datav_boundary — 行政边界
# ============================================================

@tool
def datav_boundary(name: str) -> str:
    """从阿里云 DataV 获取省/市/区三级行政区划边界，自动转 WGS-84 并加载到地图。
    用于获取省份、城市、区县的行政边界，不要用百度/高德 AOI 工具获取行政边界"""
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
    """从点图层生成热力图。参数：图层名、权重字段（可选）、半径（像素，默认20）、渐变色"""
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
    """计算并添加新字段到指定图层。expression 是 Python 表达式，如"面积*0.0015"或"人口/面积"，引用现有字段名即可。支持四则运算、函数调用（abs, round, int, float, str, len 等）。执行后自动更新地图上的图层"""
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

        geojson_str = gdf.to_json()
        geojson_data = json.loads(geojson_str)
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
    """控制地图上的图层。action 为操作类型：
    - remove：删除指定图层（只需 name）
    - toggle：切换显隐（只需 name）
    - set_color：修改颜色（需 name + color，如 #ff0000）
    - rename：重命名（需 name + new_name）
    - fit：缩放到图层范围（只需 name）"""
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
]
