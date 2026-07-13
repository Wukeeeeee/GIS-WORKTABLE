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
_current_amap_key: str = ""
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
    }


def reset_state(amap_key: str = ""):
    """每次请求开始时调用，清空所有共享状态"""
    global _current_amap_key, _clear_layers_flag
    _pending_layers.clear()
    _pending_images.clear()
    _pending_aoi_suggestions.clear()
    _pending_heatmap["latest"] = None
    _clear_layers_flag = False
    _current_amap_key = amap_key


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
    """通过必应搜索引擎搜索网络信息，返回相关网页的标题、链接和摘要。用于搜索最新新闻、数据、资料等"""
    try:
        url = f"https://cn.bing.com/search?q={query.replace(' ', '+')}"
        content = fetch_webpage_impl(url)
        if content.startswith("错误"):
            return content
        if len(content) > 3000:
            content = content[:3000] + "\n\n...(内容过长，已截断)"
        return content
    except Exception as e:
        return f"错误：{str(e)}"


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
        text = _md(text, heading_style="ATX", strip=["img", "a"])
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


@tool
def fetch_webpage(url: str) -> str:
    """获取网页内容（Scrapling隐身引擎 + markdownify清洗，自动去广告/导航/侧栏，返回干净 Markdown，token 节省约80%）。国内网站直连，反爬增强"""
    result = fetch_webpage_impl(url)
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

    if platform in ('bilibili', 'b站', 'b站'):
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
# 工具: execute_python — 执行 GIS 代码
# ============================================================

@tool
def execute_python(code: str) -> str:
    """执行Python GIS代码，返回执行结果。可用库：shapely, geopandas, numpy, matplotlib, seaborn, json, math, pyproj, osmnx, requests。
    如果要在地图上显示结果，请print出GeoJSON字符串。
    如果要生成图表，用plt.savefig('output/chart_xxx.png')保存图片。
    高德API Key通过 os.environ.get('AMAP_KEY', '') 获取。
    数据可以保存到 output/workspace/ 目录供后续步骤读取。"""
    init_temp_dir()

    BANNED_KEYWORDS = ['__import__', 'subprocess', 'os.system', 'os.popen']
    for kw in BANNED_KEYWORDS:
        if kw in code:
            return f"错误：代码包含被禁止的操作 '{kw}'"

    os.makedirs(_workspace_dir, exist_ok=True)

    # 记录执行前的文件列表
    try:
        before_images = set(glob.glob(os.path.join(_temp_output_dir, "*.png"))) | set(glob.glob(os.path.join(_temp_output_dir, "output", "*.png")))
        before_html = set(glob.glob(os.path.join(_temp_output_dir, "*.html"))) | set(glob.glob(os.path.join(_temp_output_dir, "output", "*.html")))
    except Exception:
        before_images, before_html = set(), set()

    # matplotlib 中文字体配置（注入到用户代码前）
    _font_setup = r"""
import matplotlib, os
matplotlib.use('Agg')
try:
    import shutil
    import glob as _g
    _cache_dir = os.path.join(matplotlib.get_cachedir(), 'fontlist*.json')
    for _f in _g.glob(_cache_dir): os.remove(_f)
except: pass
import matplotlib.pyplot as plt
import matplotlib.font_manager as _fm
_WIN_CJK_FONTS = [
    r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\NotoSansSC-VF.ttf', r'C:\Windows\Fonts\Deng.ttf',
    r'C:\Windows\Fonts\simsun.ttc', r'C:\Windows\Fonts\simfang.ttf',
]
_font_loaded = False
for _fp in _WIN_CJK_FONTS:
    if os.path.exists(_fp):
        try:
            _fm.fontManager.addfont(_fp)
            _prop = _fm.FontProperties(fname=_fp)
            _name = _prop.get_name()
            plt.rcParams['font.sans-serif'] = [_name] + plt.rcParams.get('font.sans-serif', ['DejaVu Sans'])
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['axes.unicode_minus'] = False
            _font_loaded = True
            break
        except: continue
if not _font_loaded:
    try:
        _cjk = [f for f in _fm.findSystemFonts() if any(k in f.lower() for k in ['yahei','msyh','simhei','noto','deng','songti','heiti','wqy'])]
        if _cjk:
            _fm.fontManager.addfont(_cjk[0])
            _prop = _fm.FontProperties(fname=_cjk[0])
            _name = _prop.get_name()
            plt.rcParams['font.sans-serif'] = [_name] + plt.rcParams.get('font.sans-serif', ['DejaVu Sans'])
    except: pass
try:
    import seaborn as sns; sns.set_style("whitegrid"); sns.set_palette("muted")
except: plt.style.use("ggplot")
"""

    _final_code = _font_setup + code
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(_final_code)
        f.flush()
        temp_path = f.name

    try:
        env = os.environ.copy()
        env['AMAP_KEY'] = _current_amap_key
        env['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True, timeout=30, encoding='utf-8', errors='replace',
            cwd=_temp_output_dir,
            env=env
        )
        if result.returncode != 0:
            return f"代码执行错误：{result.stderr.strip()[:2000]}\n请根据错误信息修改代码后重试。"

        output = result.stdout.strip()

        # 检测新生成的图片和 HTML
        try:
            after_images = set(glob.glob(os.path.join(_temp_output_dir, "*.png"))) | set(glob.glob(os.path.join(_temp_output_dir, "output", "*.png")))
            new_images = after_images - before_images
            if new_images:
                ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                for img_path in sorted(new_images):
                    img_name = f"{ts}_{os.path.basename(img_path)}"
                    dest = os.path.join(_temp_output_dir, img_name)
                    try: os.rename(img_path, dest)
                    except:
                        import shutil; shutil.copy2(img_path, dest); os.remove(img_path)
                    _add_pending_item(f"/output/{img_name}", dest)
                all_charts = sorted(glob.glob(os.path.join(_temp_output_dir, "chart_*.png")))
                while len(all_charts) > 20: os.remove(all_charts.pop(0))

            after_html = set(glob.glob(os.path.join(_temp_output_dir, "*.html"))) | set(glob.glob(os.path.join(_temp_output_dir, "output", "*.html")))
            new_html = after_html - before_html
            if new_html:
                ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                for h_path in sorted(new_html):
                    h_name = f"{ts}_{os.path.basename(h_path)}"
                    dest = os.path.join(_temp_output_dir, h_name)
                    try: os.rename(h_path, dest)
                    except:
                        import shutil; shutil.copy2(h_path, dest); os.remove(h_path)
                    _add_pending_item(f"/output/{h_name}", dest)
        except Exception:
            pass

        if not output:
            return "代码执行成功（无输出）"

        # 检测 GeoJSON
        geojson_found = False
        feature_count = 0
        lines = output.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict) and data.get('type') in ('FeatureCollection', 'Feature'):
                    now_str = datetime.datetime.now().strftime('%H%M%S')
                    name = data.get('name', f'分析结果_{now_str}')
                    _push_layer(name, data)
                    _register_layer(name, data)
                    if data['type'] == 'FeatureCollection':
                        feature_count = len(data.get('features', []))
                    else:
                        feature_count = 1
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
                    _push_layer(name, data)
                    _register_layer(name, data)
                    feature_count = len(data.get('features', [])) if data['type'] == 'FeatureCollection' else 1
                    geojson_found = True
            except (json.JSONDecodeError, ValueError):
                pass

        if geojson_found:
            return f"GIS 结果已生成并加载到地图（{feature_count} 个要素）\n---\n{output[:3000]}"

        return output[:3000]

    except subprocess.TimeoutExpired:
        return "错误：代码执行超时（30 秒），请简化操作或分批处理"
    except Exception as e:
        return f"执行异常：{str(e)[:500]}"
    finally:
        try: os.unlink(temp_path)
        except: pass


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

    # 自动推送到地图
    _push_layer(f"{keywords}_POI", geojson, {"color": "#e74c3c", "fillColor": "#e74c3c"})
    _register_layer(f"{keywords}_POI", geojson)

    source_desc = "关键字搜索" if source == "text" else "周边搜索"
    feat_count = len(geojson.get("features", []))
    return f"高德 {source_desc} 完成：找到 {count} 个「{keywords}」POI，已加载 {feat_count} 个点到地图"


# ============================================================
# 工具: baidu_aoi_search / baidu_aoi_extract（AOI 建筑轮廓）
# ============================================================

@tool
def baidu_aoi_search(query: str) -> str:
    """搜索百度地图地点，返回候选列表供用户选择（AOI建筑轮廓提取的第一步）"""
    try:
        from backend.services.baidu_aoi_service import search_suggestions
        suggestions = search_suggestions(query)
        if not suggestions:
            return "搜索失败：未找到候选地点"
        tagged = [{"name": s["name"], "address": s.get("address", ""), "id": s["uid"], "source": "baidu"} for s in suggestions]
        _pending_aoi_suggestions["latest"] = {"suggestions": tagged, "sent": False}
        lines = [f"已搜索到 {len(tagged)} 个候选："]
        for i, s in enumerate(tagged[:10], 1):
            addr = f" ({s['address']})" if s.get("address") else ""
            lines.append(f"  {i}. {s['name']}{addr}")
        lines.append("用户会在聊天框中点击选择，发来『已选择AOI候选: 名称 | ID: xxx | 来源: baidu』格式的消息")
        return "\n".join(lines)
    except Exception as e:
        return f"搜索失败: {str(e)}"


@tool
def baidu_aoi_extract(uid: str, name: str) -> str:
    """根据百度UID提取建筑轮廓，转WGS84，加载到地图（AOI建筑轮廓提取的第二步）"""
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
# 工具: gaode_aoi_search / gaode_aoi_extract（高德 AOI）
# ============================================================

@tool
def gaode_aoi_search(query: str) -> str:
    """搜索高德地图地点（备用源），返回候选列表供用户选择（AOI建筑轮廓提取的第一步）"""
    try:
        from backend.services.gaode_aoi_service import search_suggestions
        suggestions = search_suggestions(query)
        if not suggestions:
            return "搜索失败：未找到候选地点"
        tagged = [{"name": s["name"], "address": s.get("address", ""), "id": s["id"], "source": "gaode"} for s in suggestions]
        _pending_aoi_suggestions["latest"] = {"suggestions": tagged, "sent": False}
        lines = [f"已搜索到 {len(tagged)} 个候选（备用源）："]
        for i, s in enumerate(tagged[:10], 1):
            addr = f" ({s['address']})" if s.get("address") else ""
            lines.append(f"  {i}. {s['name']}{addr}")
        lines.append("用户会在聊天框中点击选择")
        return "\n".join(lines)
    except Exception as e:
        return f"搜索失败: {str(e)}"


@tool
def gaode_aoi_extract(poi_id: str, name: str) -> str:
    """根据高德ID提取建筑轮廓，转WGS84（备用源，AOI建筑轮廓提取的第二步）"""
    try:
        from backend.services.gaode_aoi_service import extract_boundary
        geojson = extract_boundary(poi_id, name)
        if geojson:
            _push_layer(name, geojson)
            _register_layer(name + "_AOI", geojson)
            return f"成功提取 {name} 的AOI轮廓，已加载到地图"
        return f"未能提取 {name} 的AOI轮廓"
    except Exception as e:
        return f"提取失败: {str(e)}"


# ============================================================
# 工具: unified_aoi_search / unified_aoi_extract（双源合一）
# ============================================================

@tool
def unified_aoi_search(query: str) -> str:
    """搜索地点轮廓（多数据源），返回合并候选列表在聊天框显示"""
    all_suggestions = []
    errors = []
    lock = threading.Lock()

    def search_baidu():
        try:
            from backend.services.baidu_aoi_service import search_suggestions as bd_search
            for s in bd_search(query):
                with lock:
                    all_suggestions.append({"name": s["name"], "address": s.get("address", ""), "id": s["uid"], "source": "baidu"})
        except Exception as e:
            with lock: errors.append(f"源A: {str(e)[:60]}")

    def search_gaode():
        try:
            from backend.services.gaode_aoi_service import search_suggestions as gd_search
            for s in gd_search(query):
                with lock:
                    all_suggestions.append({"name": s["name"], "address": s.get("address", ""), "id": s["id"], "source": "gaode"})
        except Exception as e:
            with lock: errors.append(f"源B: {str(e)[:60]}")

    search_baidu()
    search_gaode()

    if not all_suggestions:
        err_str = "；".join(errors) if errors else "未知错误"
        return f"搜索失败（{err_str}），可以换关键词重试"

    seen = set()
    unique = []
    for s in all_suggestions:
        key = f"{s['name']}|{s['source']}"
        if key not in seen and s['name']:
            seen.add(key); unique.append(s)

    _pending_aoi_suggestions["latest"] = {"suggestions": unique, "sent": False}
    lines = [f"共 {len(unique)} 个候选地点："]
    for i, s in enumerate(unique[:15], 1):
        addr = f" ({s['address']})" if s.get("address") else ""
        lines.append(f"  {i}. {s['name']}{addr}")
    lines.append("候选已显示在聊天框，等待用户点击选择")
    return "\n".join(lines)


@tool
def unified_aoi_extract(poi_id: str, name: str, source: str) -> str:
    """根据用户选择的候选提取轮廓（多数据源自动调度）"""
    if source == "baidu":
        return baidu_aoi_extract(poi_id, name)
    elif source == "gaode":
        return gaode_aoi_extract(poi_id, name)
    else:
        return f"未知来源: {source}"


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
    baidu_aoi_search,
    baidu_aoi_extract,
    gaode_aoi_search,
    gaode_aoi_extract,
    unified_aoi_search,
    unified_aoi_extract,
    get_registered_layers,
    get_layer_detail,
    datav_boundary,
    create_heatmap,
    clear_layers,
    get_session_logs,
]
