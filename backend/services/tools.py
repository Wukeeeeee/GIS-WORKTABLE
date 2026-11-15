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
import copy
import math
import time
import glob
import datetime
import subprocess
import tempfile
import threading
import re
import hashlib
import ast
import shutil
import urllib.request
import urllib.parse
import uuid
import unicodedata
import types
from numbers import Real
from typing import Optional, Dict, Any, List, Literal

from langchain.tools import tool

# === P2-1: 简单内存缓存 ===
_tile_cache = {}
_geocode_cache = {}
_custom_proxy = None  # 用户在设置页面配置的代理地址，如 http://127.0.0.1:7897


def set_proxy_config(proxy_url: str = ""):
    """设置用户自定义代理地址。空字符串表示清除自定义代理，回退到系统代理检测。"""
    global _custom_proxy
    _custom_proxy = proxy_url.strip() if proxy_url else None
    return f"代理配置已更新: {_custom_proxy or '（使用系统代理自动检测）'}"


def get_proxy_config() -> str:
    """获取当前代理配置。"""
    return _custom_proxy or ""


def _get_effective_proxies() -> dict:
    """获取实际生效的代理配置：优先用户自定义，其次系统代理。"""
    if _custom_proxy:
        return {"http": _custom_proxy, "https": _custom_proxy}
    return urllib.request.getproxies()
_cache_hits = {"tile": 0, "geocode": 0}

# Task Manager 集成：持久化 Python 源代码 + Artifact 注册
from backend.services.task_manager import (
    save_code, register_artifact, log_execution,
    get_latest_code,
)

# DEM Provider（按需获取真实地表高程；不预下载全球 DEM）
from backend.services.data_providers.errors import DataProviderError
from backend.services.dem_providers import (
    DEMError,
    DEMTileDecodeError,
    dem_provider_by_id,
    list_dem_capabilities,
)


# ============================================================
# matplotlib_font 模块导入时执行一次全局初始化；沙箱代码复用同一配置片段。
# ============================================================
from backend.services.matplotlib_font import get_sandbox_setup_code


# ============================================================
# 模块化工具组件与 AST 安全校验引入
# (重构自 backend.services.tool_modules.common)
# ============================================================

from backend.services.tool_modules.common import (
    _ALLOWED_OPS,
    _ALLOWED_AST_NODES,
    ALLOWED_IMPORTS,
    BANNED_FUNCTIONS,
    BANNED_ATTR_CALLS,
    BANNED_MAGIC_ATTRS,
    BANNED_BUILTINS,
    _BANNED_BUILTINS,
    BANNED_SYSTEM_MODULES,
    _BANNED_IMPORTS,
    BANNED_FRAME_ATTRS,
    _validate_ast,
    _validate_field_calculation_ast,
    _normalize_geojson,
    _valid_registration_geometry,
    _extract_coords,
    _compute_bbox,
    _validate_wgs84_geojson,
    _make_fid,
    _normalize_fid,
    _normalize_layer_provenance,
    _sanitize_property_name,
    _parse_iso_datetime,
    _extract_geometry_type,
    _geometry_to_wkt,
    _wkt_to_geometry,
    _layer_property_examples,
    _safe_layer_export_stem,
)


# ============================================================
# 模块化运行时状态与图层管理引入
# (重构自 backend.services.tool_modules.runtime)
# ============================================================

from backend.services.tool_modules import runtime
from backend.services.tool_modules import io_export as _io_export
from backend.services.tool_modules.runtime import (
    _registered_layers,
    _pending_layers,
    _pending_layer_ops,
    _pending_images,
    _pending_qa_warnings,
    _state_lock,
    _shared_state_lock,
    _session_locks,
    _session_locks_guard,
    _temp_output_dir,
    _workspace_dir,
    _active_project_id,
    _clear_layers_flag,
    _pending_aoi_suggestions,
    _pending_heatmap,
    _current_amap_key,
    _search_call_count,
    _domain_fail,
    _DOMAIN_FAIL_LIMIT,
    _search_cache,
    _search_last_hit,
    _SEARCH_CACHE_TTL,
    _ENGINE_MIN_INTERVAL,
    _exec_call_count,
    _exec_log,
    _raster_output_scope,
    _current_task_id,
    _last_user_message,
    _current_run_id,
    _conversation_context,
    _INLINE_HTML_PREVIEW_LIMIT,
    set_current_task,
    get_current_task_id,
    set_current_run,
    get_current_run_id,
    set_last_user_message,
    get_last_user_message,
    set_conversation_context,
    get_conversation_context,
    set_active_project_id,
    get_active_project_id,
    init_temp_dir,
    get_temp_output_dir,
    peek_pending_images,
    _add_pending_item,
    get_pending_state,
    reset_state,
    session_lock_wait_seconds,
    acquire_session_lock,
    release_session_lock,
    acquire_shared_state_lock,
    release_shared_state_lock,
    _geo_qa,
    _unicode_layer_name_conflict,
    _disambiguate_layer_name,
    _push_layer,
    _unregister_layer,
    _register_layer,
    _update_registered_layer_data,
    _get_exact_registered_layer,
    _register_raster_layer,
    get_registered_layers_snapshot,
    reset_registered_layers,
    _layer_to_gdf,
    _gdf_to_layer,
)


# ============================================================
# Modular Domain Imports & Re-exports
# (Decomposed into backend.services.tool_modules: vector, network, raster, terrain)
# ============================================================

from backend.services.tool_modules import (
    vector as _vector_mod,
    network as _network_mod,
    raster as _raster_mod,
    terrain as _terrain_mod,
)

from backend.services.tool_modules.vector import (
    spatial_buffer,
    spatial_multi_ring_buffer,
    spatial_intersect,
    spatial_union,
    spatial_difference,
    spatial_clip,
    spatial_centroid,
    spatial_simplify,
    spatial_dissolve,
    spatial_select,
    spatial_sample,
    spatial_near,
    nearest_pair,
    spatial_cluster,
    spatial_voronoi,
    spatial_field_stats,
    spatial_join,
    layer_merge,
    layer_split,
    layer_add_geometry,
    spatial_select_by_attribute,
    topology_check,
    spatial_fix_geometry,
    spatial_check_duplicates,
    spatial_explode,
    geometry_convert,
    join_field,
    geometry_attributes,
    minimum_bounding_geometry,
    points_to_line,
    generate_points_along_lines,
    spatial_weights_matrix,
    spatial_regression,
    directional_distribution,
    central_tendency,
    create_fishnet,
    _to_local_metric_gdf,
    _spatial_feature_coordinates,
    _gdf_area_km2,
    _get_utm_crs,
    _local_utm_extent_error,
    _stats_metric_gdf,
    _stats_coords_weights,
    _geometric_median,
    _is_contiguous,
    _contiguity_pairs,
    _build_spatial_weights,
    _moran_from_weights,
    _stats_out_dir,
    _stats_safe_name,
    _stats_summary,
    _parse_numeric_condition,
)

from backend.services.tool_modules.network import (
    download_road_network,
    network_analysis,
    od_cost_matrix,
    metro_line,
    cost_distance,
    least_cost_path,
    _format_extent,
    _point_in_bbox,
    _find_layer_for_coord,
    _parse_coord,
    _cost_graph,
)

from backend.services.tool_modules.raster import (
    ndvi_analysis,
    raster_calculator,
    spatial_interpolate,
    clip_raster,
    calc_spectral_index,
    ndwi_analysis,
    ndbi_analysis,
    evi_analysis,
    ndmi_analysis,
    zonal_statistics,
    raster_resample,
    raster_reproject,
    raster_reclassify,
    raster_focal_stats,
    euclidean_distance,
    raster_extract_by_mask,
    feature_to_raster,
    raster_to_feature,
    load_cog,
    get_cog_info,
    _find_uploaded_tif,
    _raster_output_dir,
    _write_raster_output,
    _raster_preview_op,
    _raster_preview_context,
    _raster_out_profile,
    _parse_reclass_rules,
    _calc_spectral_index,
)

from backend.services.tool_modules.terrain import (
    dem_analysis,
    hydrology_analysis,
    view_3d_terrain,
    terrain_profile,
    extract_contours,
    get_elevation_data,
    surface_volumes,
    _elevation_unit_to_m,
    _fill_sinks,
    _parse_dem_bbox,
    _write_dem_geotiff,
    _write_dem_preview,
    _raster_pixel_area_m2,
)

def _engine_throttle(engine_name: str) -> None:
    """同引擎限速：间隔不足时 sleep 补齐，降低验证码/封禁概率。"""
    import time as _t
    last = _search_last_hit.get(engine_name, 0.0)
    wait = _ENGINE_MIN_INTERVAL - (_t.time() - last)
    if wait > 0:
        _t.sleep(wait)
    _search_last_hit[engine_name] = _t.time()


def record_tool_artifact(filename: str, filepath: str, artifact_type: str = "image", step: int = 0) -> Optional[dict]:
    """统一记录工具生成的产物到 TaskManager (任务台账) 与 StorageService (SQLite事实台账)。"""
    current_task_id = runtime.get_current_task_id() or _current_task_id
    current_run_id = runtime.get_current_run_id() or _current_run_id
    art = None
    if current_task_id:
        try:
            art = register_artifact(current_task_id, filename, filepath,
                                    artifact_type=artifact_type, created_by_step=step)
        except Exception as e:
            print(f"[Tools] register_artifact 出错: {e}", flush=True)
    if current_run_id:
        try:
            from backend.services import storage_service
            art_id = (art.get("artifact_id") if art else "") or uuid.uuid4().hex[:10]
            storage_service.register_run_artifact(
                current_run_id, art_id, filename, filepath, file_type=artifact_type
            )
        except Exception as e:
            print(f"[Tools] register_run_artifact 出错: {e}", flush=True)
    return art


# ============================================================
# 会话锁、状态重置与图层管理工具函数
# (重构自 backend.services.tool_modules.runtime)
# 支持短时间等待: GIS_SESSION_LOCK_WAIT, 核心分支调用 lock.acquire(timeout=timeout)
# ============================================================

# Note: The following symbols are imported above from backend.services.tool_modules.runtime:
#   _session_locks, _session_locks_guard, _shared_state_lock,
#   session_lock_wait_seconds, acquire_session_lock, release_session_lock,
#   acquire_shared_state_lock, release_shared_state_lock,
#   reset_state, init_temp_dir,
#   _push_layer, _geo_qa, _unregister_layer, _unicode_layer_name_conflict,
#   _disambiguate_layer_name, _register_layer, _update_registered_layer_data,
#   _get_exact_registered_layer, _register_raster_layer,
#   get_registered_layers_snapshot, reset_registered_layers, _add_pending_item



# ============================================================
# 工具: search_web — 必应搜索
# ============================================================

def _bing_rss_search(query: str, timeout: float = 12.0) -> str:
    """Bing RSS 免费出口：https://www.bing.com/search?q=...&format=rss
    返回干净的 XML（标题/链接/摘要），无反爬困扰、无需解析 HTML。"""
    import requests
    from xml.etree import ElementTree as ET
    url = "https://www.bing.com/search?q=" + requests.utils.quote(query) + "&format=rss&count=10"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return ""
        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        out = []
        for it in items[:10]:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = (it.findtext("description") or "").strip()
            if title or desc:
                out.append(f"- {title}\n  链接: {link}\n  摘要: {desc}")
        return "\n".join(out)
    except Exception:
        return ""


def _baidu_html_search(query: str, timeout: float = 12.0) -> str:
    """百度网页搜索兜底：解析结果页的标题/摘要（带 UA，失败返回空）。"""
    import requests
    from bs4 import BeautifulSoup
    url = "https://www.baidu.com/s?wd=" + requests.utils.quote(query) + "&rn=10"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200 or not resp.text:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        out = []
        for h3 in soup.select("h3.c-title-font, h3.t, div.result h3, div.c-container h3")[:10]:
            a = h3.find("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a.get("href", "")
            container = h3.find_parent(["div", "td"])
            desc = ""
            if container:
                for sel in (".c-abstract", ".c_span9", "[class*=content-right]", "[class*=abstract]"):
                    node = container.select_one(sel)
                    if node and node.get_text(strip=True):
                        desc = node.get_text(strip=True)
                        break
            if title:
                out.append(f"- {title}\n  链接: {link}\n  摘要: {desc}")
        return "\n".join(out)
    except Exception:
        return ""


def _sogou_html_search(query: str, timeout: float = 12.0) -> str:
    """搜狗网页搜索兜底 2。"""
    import requests
    from bs4 import BeautifulSoup
    url = "https://www.sogou.com/web?query=" + requests.utils.quote(query)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200 or not resp.text:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        out = []
        for vrwrap in soup.select("div.vrwrap, div.rb")[:10]:
            h3 = vrwrap.select_one("h3")
            if not h3:
                continue
            a = h3.find("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a.get("href", "")
            if link and not link.startswith("http"):
                link = "https://www.sogou.com" + link
            desc_node = vrwrap.select_one(".str-text-info, .space-txt, p.str_info")
            desc = desc_node.get_text(strip=True) if desc_node else ""
            if title:
                out.append(f"- {title}\n  链接: {link}\n  摘要: {desc}")
        return "\n".join(out)
    except Exception:
        return ""


def _ddg_html_search(query: str, timeout: float = 12.0) -> str:
    """DuckDuckGo HTML 版兜底 3（国际内容效果好，国内可能不可达）。"""
    import requests
    from bs4 import BeautifulSoup
    url = "https://html.duckduckgo.com/html/?q=" + requests.utils.quote(query)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200 or not resp.text:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        out = []
        for r in soup.select("div.result")[:10]:
            a = r.select_one("a.result__a")
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a.get("href", "")
            snip = r.select_one(".result__snippet")
            desc = snip.get_text(strip=True) if snip else ""
            if title:
                out.append(f"- {title}\n  链接: {link}\n  摘要: {desc}")
        return "\n".join(out)
    except Exception:
        return ""


def _query_tokens(query: str) -> list:
    """把查询拆成关键词 token（去空白/标点，保留 >=2 字符的段）。"""
    import re as _re2
    raw = _re2.split(r"[\s，。、,\.\?\?！!：:;\"'（）()　]+", query)
    toks = []
    for t in raw:
        t = t.strip()
        if len(t) >= 2:
            # 去掉常见后缀让匹配更宽容（"2024年""2024"，"GDP的""GDP"）
            t2 = t.rstrip("年的中之和与")
            if len(t2) >= 2:
                toks.append(t2)
            else:
                toks.append(t)
    return list(dict.fromkeys(toks))  # 去重保序


def _relevance_score(text: str, tokens: list) -> float:
    """结果文本中命中的查询关键词比例（0~1）。"""
    if not tokens:
        return 0.0
    low = text.lower()
    hit = sum(1 for t in tokens if t.lower() in low)
    return hit / len(tokens)


@tool
def search_web(query: str) -> str:
    """搜索网络信息，返回网页标题、链接/摘要。多引擎自动降级 + 相关性评分：
    百度  搜狗  Bing RSS  DuckDuckGo。结果须命中查询关键词一半以上才算数，
    否则继续尝试并最终返回最相关的一份。返回结构化摘要（非原始网页），token 省 90%。"""
    runtime._search_call_count += 1
    if runtime._search_call_count > 30:
        return "【已停止】已搜索太多次，请基于已有信息继续处理。"

    # 结果缓存：相同查询 10 分钟内直接返回（省时间也省引擎额度，降低验证码概率）
    import time as _time
    _cached = _search_cache.get(query)
    if _cached and (_time.time() - _cached[0]) < _SEARCH_CACHE_TTL:
        print(f"[GIS] search_web 命中缓存: {query[:40]}", flush=True)
        return _cached[1]

    engines = [
        ("百度", _baidu_html_search),
        ("搜狗", _sogou_html_search),
        ("Bing RSS", _bing_rss_search),
        ("DuckDuckGo", _ddg_html_search),
    ]
    tokens = _query_tokens(query)
    threshold = 0.5
    best_text, best_score, best_name = "", -1.0, ""
    for name, fn in engines:
        try:
            _engine_throttle(name)
            results = fn(query)
            if not results or len(results.strip()) < 40:
                continue
            score = _relevance_score(results, tokens)
            print(f"[GIS] search_web 引擎 {name} 相关性 {score:.2f} (query: {query[:40]})", flush=True)
            if score > best_score:
                best_text, best_score, best_name = results, score, name
            if score >= threshold:
                break  # 足够相关，立即采用
        except Exception as e:
            print(f"[GIS] search_web 引擎 {name} 异常: {str(e)[:100]}", flush=True)
            continue

    if best_text and best_score > 0.05:
        _final = f"[搜索结果 | {best_name} | 相关性 {best_score:.0%}]" + chr(10) + best_text
        _search_cache.clear()  # 只留最新一条，防内存膨胀
        _search_cache[query] = (_time.time(), _final)
        return _final

    # 所有引擎均无有效结果：不缓存失败，下次换关键词可立即重试
    return ("错误：搜索失败（所有引擎均无有效结果，可能网络受限或关键词过于冷门）。"
            "建议：1) 换个关键词 2) 若已有足够信息请直接分析，不要反复搜索。")


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


_JUNK_MARKERS = (
    "404 Not Found", "403 Forbidden", "Access Denied", "访问被拒绝",
    "页面不存在", "无法找到该页面", "系统发生错误", "Service Unavailable",
    "Just a moment...", "请开启 JavaScript", "安全验证", "human verification",
)


def _looks_like_junk(text: str) -> bool:
    """检测 404/403/反爬验证等无效页面，避免把错误页当正文喂给模型。"""
    if not text:
        return True
    head = text[:300].lower()
    if len(text.strip()) < 80:
        # 极短页面几乎必为错误页/空壳
        return True
    for m in _JUNK_MARKERS:
        if m.lower() in head:
            return True
    return False


def _normalize_web_url(url: str) -> str:
    """清理模型偶尔传入的 Markdown 链接，避免把整段链接语法交给抓取器。"""
    value = str(url or "").strip()
    match = re.fullmatch(r"\[([^\]]+)\]\((https?://.+)\)", value, re.IGNORECASE)
    if match:
        value = match.group(2).strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    return value


def _safe_url_label(url: str) -> str:
    """日志和错误反馈仅显示站点，不保留凭据、路径或查询参数。"""
    from urllib.parse import urlparse as _urlparse
    try:
        parsed = _urlparse(str(url or ""))
        host = parsed.hostname
        if not host or parsed.scheme.lower() not in {"http", "https"}:
            return "目标站点"
        return f"{parsed.scheme.lower()}://{host}"
    except Exception:
        return "目标站点"


def fetch_webpage_impl(url: str, max_length: int = 10000) -> str:
    """获取网页内容的实现（被 search_web 和 fetch_webpage 共用），带同域熔断。"""
    global _domain_fail
    url = _normalize_web_url(url)
    from urllib.parse import urlparse as _urlparse
    try:
        _host = (_urlparse(url).hostname or "").lower()
    except Exception:
        _host = ""
    if _host and _domain_fail.get(_host, 0) >= _DOMAIN_FAIL_LIMIT:
        print(f"[GIS] 熔断：{_host} 已连续失败 {_domain_fail[_host]} 次，本轮不再抓取", flush=True)
        return None

    _impl_result = _fetch_webpage_impl_inner(url, max_length)
    _ok = bool(_impl_result) and not _impl_result.startswith("错误")
    if _host:
        if _ok:
            _domain_fail[_host] = 0
        else:
            _domain_fail[_host] = _domain_fail.get(_host, 0) + 1
    return _impl_result


def _fetch_webpage_impl_inner(url: str, max_length: int = 10000) -> str:
    """获取网页内容的实现（被 search_web 和 fetch_webpage 共用）"""
    # 方案 A：Scrapling
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=20)
        if page.status != 200:
            print(f'[GIS] fetch_webpage HTTP {page.status}: {_safe_url_label(url)}', flush=True)
            return None
        html = str(page.html_content)
        if html and len(html) > 50:
            text = _html_to_markdown(html, url)
            text = text[:max_length]
            if text and not _looks_like_junk(text):
                return text
            if text:
                print(f'[GIS] fetch_webpage 页面疑似错误页/反爬页，已丢弃: {_safe_url_label(url)}', flush=True)
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
            return f"错误：网页抓取失败（目标站点未能加载：{_safe_url_label(url)}）"
        _text_out = stdout.strip()
        if not _text_out or _looks_like_junk(_text_out):
            print(f'[GIS] fetch_webpage(playwright) 内容疑似错误页，已丢弃: {_safe_url_label(url)}', flush=True)
            return None
        return _text_out or '抓取结果为空'
    except subprocess.TimeoutExpired:
        return "错误：抓取超时"
    except Exception as e:
        return f"错误：网页抓取失败（{type(e).__name__}）"
    # 注：方案 A/B 所有分支均已显式 return，无不可达代码


@tool
def fetch_webpage(url: str) -> str:
    """获取网页内容（Scrapling隐身引擎 + markdownify清洗，自动去广告/导航/侧栏，返回干净 Markdown，token 节省约80%）。国内网站直连，反爬增强"""
    runtime._search_call_count += 1
    if runtime._search_call_count > 30:
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
    url = _normalize_web_url(url)
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
        # 普通正文抓取可复用现有 Playwright 降级链路；CSS 子选择器仍需
        # Scrapling，不能在降级时悄悄返回整页并冒充选择器结果。
        if (selector or "body").strip().lower() not in {"body", "html"}:
            return "错误：Scrapling 未安装，降级抓取仅支持 selector='body'；请安装 scrapling[fetchers] 后重试该选择器"
        fallback = fetch_webpage_impl(url, max_length=8000)
        if fallback is None:
            return "错误：Scrapling 未安装，且备用网页抓取未能获取正文"
        if fallback.startswith("错误"):
            return fallback
        return "[备用抓取（Scrapling 不可用）]\n\n" + fallback
    except Exception as e:
        return f"错误：网页抓取失败（{_safe_url_label(url)}；{type(e).__name__}）"


# ============================================================
# 工具: search_platform — 平台搜索（B站等）
# ============================================================

@tool
def search_platform(platform: str, query: str) -> str:
    """搜索中国互联网平台的内容（B站/bilibili 等），零配置国内直连"""
    platform = platform.lower().strip()

    if platform in ('bilibili', 'b站'):
        try:
            import requests
            params = {
                'search_type': 'video',
                'keyword': query,
                'page': 1,
            }
            url = "https://api.bilibili.com/x/web-interface/search/all/v2"
            resp = requests.get(url, params=params, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.bilibili.com/',
            }, timeout=10)
            data = resp.json()
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

    # 安全：拒绝路径遍历，防止写出 output 目录
    safe_name = os.path.basename(filename)
    if safe_name != filename or filename.startswith('/') or '..' in filename:
        return f"错误：无效的文件名 '{filename}'（已拒绝路径遍历）"

    output_dir = _temp_output_dir
    os.makedirs(output_dir, exist_ok=True)
    output_name = filename
    if filename.endswith('.html'):
        ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        output_name = f"{ts}_{uuid.uuid4().hex}_{filename}"
    path = os.path.join(output_dir, output_name)
    resolved_output_dir = os.path.realpath(output_dir)
    resolved_path = os.path.realpath(path)
    try:
        inside_output = os.path.commonpath([resolved_output_dir, resolved_path]) == resolved_output_dir
    except ValueError:
        inside_output = False
    if os.path.islink(path) or not inside_output:
        return f"错误：文件名 '{filename}' 指向输出目录之外或符号链接（已拒绝）"
    path = resolved_path
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
        _add_pending_item(f"/output/{output_name}", path)

    return f"文件已保存：{path}"


# ============================================================
# 第一层：AST 静态代码校验
# ============================================================

# Note: ALLOWED_IMPORTS, BANNED_FUNCTIONS, BANNED_ATTR_CALLS, BANNED_MAGIC_ATTRS,
# BANNED_BUILTINS, BANNED_SYSTEM_MODULES, BANNED_FRAME_ATTRS are imported above
# from backend.services.tool_modules.common


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

def _rename_output_files(new_files: set, suffix: str, temp_dir: str) -> list:
    """为输出目录中新生成的文件加时间戳版本，避免文件名冲突，同时保留原文件名供直连访问。"""
    ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    renamed = []
    for fname in sorted(new_files):
        if not fname.lower().endswith(suffix):
            continue
        src = os.path.join(temp_dir, fname)
        dest = _unique_output_destination(temp_dir, f'{ts}_{fname}')
        dest_name = os.path.basename(dest)
        try:
            shutil.copy2(src, dest)
        except Exception:
            try:
                os.remove(dest)
            except OSError:
                pass
            continue
        _add_pending_item(f'/output/{dest_name}', dest)
        renamed.append(dest_name)
    return renamed


def _unique_output_destination(directory: str, filename: str) -> str:
    stem, extension = os.path.splitext(filename)
    candidate_name = filename
    while True:
        candidate = os.path.join(directory, candidate_name)
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            suffix = uuid.uuid4().hex[:12]
            candidate_name = f'{stem}_{suffix}{extension}'
            continue
        os.close(descriptor)
        return candidate


def _is_safe_exec_output_path(exec_root: str, path: str) -> bool:
    """Only collect regular paths that resolve inside the per-run directory."""
    try:
        if os.path.islink(path):
            return False
        root = os.path.realpath(exec_root)
        resolved = os.path.realpath(path)
        common = os.path.commonpath((root, resolved))
        return os.path.normcase(common) == os.path.normcase(root)
    except (OSError, ValueError):
        return False


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
# 工具: execute_python — 执行 GIS 代码（AST 限制 + 本地子进程）
# ============================================================

_EXEC_PYTHON_SENSITIVE_ENV_RE = re.compile(
    r"(?i)(?:^|_)(?:API[_-]?KEY|ACCESS[_-]?KEY|KEY|SECRET|TOKEN|PASSWORD|PASSWD|USERPWD|"
    r"CREDENTIALS?|AUTH|PRIVATE[_-]?KEY|DATABASE[_-]?(?:URL|URI)|DB[_-]?(?:URL|URI)|"
    r"CONNECTION[_-]?STRING|DSN)(?:_|$)"
)
_EXEC_PYTHON_PROXY_ENV_NAMES = {"http_proxy", "https_proxy", "all_proxy"}


def _proxy_environment_contains_credentials(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    try:
        parsed = urllib.parse.urlsplit(candidate if "://" in candidate else "//" + candidate)
        return parsed.username is not None or parsed.password is not None
    except ValueError:
        return "@" in candidate


def _execute_python_child_environment() -> dict:
    """Copy the runtime environment while filtering common credential names."""
    env = os.environ.copy()
    for name in tuple(env):
        lower_name = name.casefold()
        if (
            lower_name == "amap_key"
            or _EXEC_PYTHON_SENSITIVE_ENV_RE.search(name)
            or (lower_name in _EXEC_PYTHON_PROXY_ENV_NAMES and _proxy_environment_contains_credentials(env[name]))
        ):
            env.pop(name, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@tool
def execute_python(code: str) -> str:
    """执行自定义 Python GIS 分析与可视化代码（本地子进程）。
    运行前会检查部分导入、反射和路径模式，并设置 120 秒超时；这不是操作系统级安全沙箱，
    会按名称尽可能过滤常见凭据环境变量，并移除带认证信息的 HTTP(S) 代理环境变量；
    但不提供文件、网络或资源隔离。不要将其用于执行不可信用户代码。
    仅当需绘制多子图图表(matplotlib/pyecharts)、指标看板或无现有工具覆盖的高级矢量/栅格运算时使用。
    允许库：geopandas, shapely, numpy, pandas, matplotlib, pyecharts, rasterio, pyproj, osmnx, json, math, re, datetime, io, tempfile。
    导入 OSMnx 不会触发联网探测。AST 规则会拒绝 requests/urllib 等常见导入，但不构成网络隔离；
    边界和要素使用 fetch_osm_boundary_or_features 等现有 GIS 工具。
    输出规范：print(GeoJSON) 自动加载到地图（加 name 属性为图层名）；plt.savefig('chart_xxx.png') 自动注册图表。"""
    runtime._exec_call_count += 1

    # 记录执行日志（提取代码前50个字符作为摘要）
    code_summary = code.strip()[:50].replace('\n', ' ')
    _exec_log.append({
        "seq": runtime._exec_call_count,
        "code_summary": code_summary,
        "timestamp": datetime.datetime.now().strftime('%H:%M:%S'),
    })
    
    # 软警告：超过7次提醒但不阻断，超过20次才阻断
    if runtime._exec_call_count > 20:
        return f"【执行过热】本次请求已执行 {runtime._exec_call_count} 次 Python 代码（上限20次）。请基于已有结果继续，不要再执行了。"
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
        return ast_error + "\n请勿通过更换导入方式、反射或内省绕过沙箱；联网获取 GIS 数据请调用现有专用 GIS 工具。"

    # ================================================================
    # 第二层：每次执行创建专属临时目录
    # ================================================================
    exec_dir = tempfile.mkdtemp(prefix='gis_sandbox_')
    start_time = time.time()

    try:
        # 仅根据代码需要初始化绘图环境；导入 OSMnx 不触发网络探测。
        _code_tree = ast.parse(code)
        _imports = set()
        for _node in ast.walk(_code_tree):
            if isinstance(_node, ast.Import):
                _imports.update(_alias.name.split('.')[0] for _alias in _node.names)
            elif isinstance(_node, ast.ImportFrom) and _node.module:
                _imports.add(_node.module.split('.')[0])
        _plot_libs = {'matplotlib', 'plt', 'geopandas', 'gpd', 'seaborn', 'sns', 'cartopy', 'contextily'}
        _has_plot_import = bool(_imports.intersection({'matplotlib', 'geopandas', 'seaborn', 'cartopy', 'contextily', 'pandas'}))
        _has_plot_call = any(
            (isinstance(_node, ast.Name) and _node.id in {'plt', 'ax', 'fig', 'gpd'}) or
            (isinstance(_node, ast.Attribute) and _node.attr in {'plot', 'savefig', 'subplots', 'figure'})
            for _node in ast.walk(_code_tree)
        )
        _needs_plot = _has_plot_import or _has_plot_call or ('plot' in code) or ('savefig' in code)
        _setup_blocks = r"""
# matplotlib 中文字体配置（由公共模块动态生成，避免重复实现）
{font_setup_code}

# 创建 output/ 子目录，支持 plt.savefig('output/chart.png') 路径
import os as _os
_os.makedirs('output', exist_ok=True)
"""

        # P2: 动态注入公共模块生成的字体配置代码（替换占位符）
        _font_setup_code = ""
        if _needs_plot:
            _font_setup_code = get_sandbox_setup_code()
        _setup_blocks_filled = _setup_blocks.replace('{font_setup_code}', _font_setup_code)
        # Keep helper-only system modules out of the namespace seen by user code.
        _final_code = _setup_blocks_filled.rstrip() + '\n\ndel _os\n\n' + code

        temp_path = os.path.join(exec_dir, '_user_code_.py')
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(_final_code)

        # 记录执行前输出目录的快照
        try:
            before_files = set(os.listdir(_temp_output_dir))
        except Exception:
            before_files = set()

        # Filter common credentials by variable name as defense in depth. This
        # does not isolate files, network access, or secrets stored under other names.
        env = _execute_python_child_environment()

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
            for _sub in ('output', 'cache', os.path.join('cache', 'charts'), 'reports'):
                _sd = os.path.join(exec_dir, _sub)
                if os.path.isdir(_sd) and _is_safe_exec_output_path(exec_dir, _sd):
                    _dirs_to_scan.append(_sd)
            for _scan_dir in _dirs_to_scan:
                for fname in os.listdir(_scan_dir):
                    if fname == '_user_code_.py':
                        continue
                    fpath = os.path.join(_scan_dir, fname)
                    if os.path.isfile(fpath) and _is_safe_exec_output_path(exec_dir, fpath):
                        dest = _unique_output_destination(_temp_output_dir, fname)
                        try:
                            shutil.copy2(fpath, dest)
                        except Exception:
                            try:
                                os.remove(dest)
                            except OSError:
                                pass
                            continue
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

            for ext in ('.png', '.jpg', '.jpeg', '.webp', '.svg'):
                new_images.extend(_rename_output_files(new_files, ext, _temp_output_dir))
            _rename_output_files(new_files, '.html', _temp_output_dir)
            _cleanup_charts(_temp_output_dir)
        except Exception:
            pass

        if not output:
            # 即使无输出，如果有图片也要报告
            if new_images:
                # Task Manager + Storage Service: 注册图片 Artifact
                _registered_artifacts = []
                for img_name in new_images:
                    img_path = os.path.join(_temp_output_dir, img_name)
                    art = record_tool_artifact(img_name, img_path, artifact_type="image", step=_task_step or 0)
                    if art:
                        _registered_artifacts.append(art.get("artifact_id", ""))
                if _current_task_id:
                    try:
                        log_execution(_current_task_id, _task_step or 0, code, "",
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
        # Task Manager + Storage Service: 注册图片 Artifact + 记录执行
        _registered_artifacts = []
        for img_name in new_images:
            img_path = os.path.join(_temp_output_dir, img_name)
            art = record_tool_artifact(img_name, img_path, artifact_type="image", step=_task_step or 0)
            if art:
                _registered_artifacts.append(art.get("artifact_id", ""))
        if _current_task_id:
            try:
                log_execution(_current_task_id, _task_step or 0, code, "",
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

def _search_osm_poi_fallback(keywords: str, city: str = "", location: str = "", radius: int = 1000) -> dict:
    """Use public OSM/Overpass POIs when AMap is unavailable; bbox coordinates are WGS-84."""
    import re as _re
    from backend.services.data_providers import geocode as _geocode
    from backend.services.data_providers.osm_provider import OpenStreetMapProvider, _element_to_feature

    if location:
        parts = location.split(",")
        if len(parts) != 2:
            raise ValueError("位置坐标格式应为 经度,纬度")
        lon, lat = float(parts[0].strip()), float(parts[1].strip())
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("位置坐标超出经纬度范围")
        radius_m = max(100, min(int(radius or 1000), 50000))
        lat_delta = radius_m / 111320
        lon_delta = radius_m / max(111320 * abs(math.cos(math.radians(lat))), 1000)
        bbox = (lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta)
        area = f"{lat:.5f},{lon:.5f} ±{radius_m}m"
    elif city:
        bbox = _geocode.resolve_area_bbox(city)
        area = city
    else:
        raise ValueError("OSM 回退搜索需要城市名或中心坐标")

    text = str(keywords or "").strip()
    if not text:
        raise ValueError("缺少 POI 搜索关键词")
    normalized = text.lower()
    category_tags = {
        "hospital": ("amenity", "^(hospital|clinic|doctors)$"),
        "医院": ("amenity", "^(hospital|clinic|doctors)$"),
        "school": ("amenity", "^(school|university|college|kindergarten)$"),
        "学校": ("amenity", "^(school|university|college|kindergarten)$"),
        "餐厅": ("amenity", "^(restaurant|fast_food|cafe)$"),
        "restaurant": ("amenity", "^(restaurant|fast_food|cafe)$"),
        "pharmacy": ("amenity", "pharmacy"),
        "药店": ("amenity", "pharmacy"),
        "超市": ("shop", "^(supermarket|convenience)$"),
        "supermarket": ("shop", "^(supermarket|convenience)$"),
    }
    matched_tags = next((value for key, value in category_tags.items() if key in normalized), None)
    if matched_tags:
        tag, value = matched_tags
        selectors = [f'{obj}["{tag}"~"{value}"]' for obj in ("node", "way", "relation")]
        if text in ("医院", "hospital"):
            selectors += [f'{obj}["healthcare"~"^(hospital|clinic|doctor|doctors)$"]' for obj in ("node", "way", "relation")]
    else:
        regex = _re.escape(text).replace('"', '\\"')
        quoted = json.dumps(regex, ensure_ascii=False)
        selectors = [f'{obj}["name"~{quoted},i]' for obj in ("node", "way", "relation")]

    provider = OpenStreetMapProvider()
    query = provider._build_query(selectors, bbox, max_items=3000)
    response = provider._overpass(query)
    features = []
    for element in response.get("elements") or []:
        feature = _element_to_feature(element)
        if feature:
            feature["properties"]["source"] = "OpenStreetMap"
            features.append(feature)
    return {
        "geojson": {"type": "FeatureCollection", "name": f"{text}_POI_OSM", "features": features},
        "count": len(features),
        "area": area,
    }


@tool
def amap_poi_search(keywords: str, city: str = "", location: str = "", radius: int = 1000) -> str:
    """Search POIs with AMap when available, then automatically fall back to public OSM/Overpass.
    keywords: POI type/name; city: city or region; location: WGS-84 center as "lng,lat"; radius: meters."""
    if isinstance(radius, bool) or not isinstance(radius, int) or not 1 <= radius <= 50000:
        return "搜索半径必须是 1 到 50000 米之间的整数。"
    amap_error = ""
    amap_warnings = []
    result = None
    if _current_amap_key:
        from backend.services.amap_service import search_poi as _search_poi

        # AMap uses GCJ-02 for around queries; preserve the supplied WGS-84 point for OSM fallback.
        actual_location = location
        if location:
            try:
                parts = location.split(",")
                if len(parts) != 2:
                    raise ValueError("location 必须为经度,纬度")
                wgs_lng, wgs_lat = float(parts[0].strip()), float(parts[1].strip())
                if not (-180 <= wgs_lng <= 180 and -90 <= wgs_lat <= 90):
                    raise ValueError("location 超出经纬度范围")
                from backend.services.geo_coords import wgs84_to_gcj02
                gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
                actual_location = f"{gcj_lng},{gcj_lat}"
            except (ValueError, IndexError):
                return "中心点坐标无效，请使用 WGS-84 的「经度,纬度」格式。"
        result = _search_poi(
            keywords=keywords, city=city,
            location=actual_location if location else "",
            radius=radius, api_key=_current_amap_key,
        )
        amap_error = result.get("error", "")
        amap_warnings = result.get("warnings") or []
        if not amap_error and result.get("count", 0) > 0:
            geojson = result["geojson"]
            count = result["count"]
            source = result["source"]
            layer_name = f"{keywords}_POI(高德已转WGS84)"
        else:
            source = ""
            geojson = None
            count = 0
    else:
        amap_error = "高德 API Key 未配置"
        source = ""
        geojson = None
        count = 0

    if not source:
        try:
            fallback = _search_osm_poi_fallback(keywords, city, location, radius)
            geojson, count = fallback["geojson"], fallback["count"]
            if not count:
                return f"错误：高德不可用（{amap_error}）；已尝试 OSM，但在「{fallback['area']}」未找到「{keywords}」POI。"
            source = "OpenStreetMap"
            layer_name = f"{keywords}_POI(OSM)"
        except Exception as error:
            return f"错误：高德不可用（{amap_error or '无有效结果'}）；OSM 回退也失败：{str(error)[:250]}"

    _push_layer(layer_name, geojson, {"color": "#e74c3c", "fillColor": "#e74c3c"})
    _register_layer(layer_name, geojson)

    feat_count = len(geojson.get("features", []))
    if source == "OpenStreetMap":
        return f"高德不可用（{amap_error}）；已自动回退到 OpenStreetMap，找到 {count} 个「{keywords}」POI，已加载 {feat_count} 个要素。OSM 数据由社区维护，中国地区覆盖可能不完整。"
    source_desc = "关键字搜索" if source == "text" else "周边搜索"
    warning_text = ("；注意：" + "；".join(str(w) for w in amap_warnings)) if amap_warnings else ""
    return f"高德 {source_desc} 完成：找到 {count} 个「{keywords}」POI，原始坐标 GCJ-02 已转 WGS-84，已加载 {feat_count} 个点到地图（图层名已标注）{warning_text}"


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

    # P2-1: 地理编码缓存
    _cache_key = f"{address}|{city or ''}"
    if _cache_key in _geocode_cache:
        _cache_hits["geocode"] += 1
        return _geocode_cache[_cache_key]

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
        _result = f"「{address}」的坐标（WGS-84）：{wgs_lng:.6f},{wgs_lat:.6f}"
        _geocode_cache[_cache_key] = _result
        # 缓存上限
        if len(_geocode_cache) > 200:
            _keys = list(_geocode_cache.keys())[:100]
            for _k in _keys:
                del _geocode_cache[_k]
        return _result
    except Exception as exc:
        # requests 异常可能带上含 API Key 的完整 URL。
        return f"地理编码请求失败: {type(exc).__name__}"


# ============================================================
# 工具: cn_aoi_search / cn_aoi_extract（百度 AOI）
# ============================================================

@tool
def cn_aoi_search(query: str) -> str:
    """搜索地点轮廓，返回候选列表在聊天框显示。
    流程：用户说"提取轮廓"或"AOI"时先调本工具 → 在聊天框显示候选列表
    → **执行后立刻停止，不要继续提取**，等用户点击选择
    → 用户选择后会发来"已选择AOI候选: 名称 | ID: xxx"
    → 收到后用 cn_aoi_extract 提取
    提取失败的话如实告诉用户，**严禁自己估算或画边界**"""
    try:
        from backend.services.baidu_aoi_service import search_suggestions
        suggestions = search_suggestions(query)
        if not suggestions:
            return "搜索失败：未找到候选地点"
        tagged = [{"name": s["name"], "address": s.get("address", ""), "id": s["uid"], "source": "online"} for s in suggestions]
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
def cn_aoi_extract(uid: str, name: str) -> str:
    """根据用户选择的候选提取建筑轮廓边界，转WGS84加载到地图。
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

def _format_extent(bbox: list) -> str:
    """将 bbox 转为可读的描述文本（内部辅助函数，不暴露给 AI）"""
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


def _registered_layers_summary(keyword: str = "") -> str:
    """生成当前会话图层摘要，供多个工具入口共享。"""
    if not _registered_layers:
        return "当前地图没有已加载或注册的图层。"
    import re

    terms = [part.strip() for part in re.split(r"[,，、;；|]", keyword or "") if part.strip()]
    lines = [f"当前地图共注册了 {len(_registered_layers)} 个图层："]
    for name, info in _registered_layers.items():
        types = ", ".join(info.get("geometry_types", ["未知"]))
        ext = _format_extent(info.get("bbox", []))
        fc = info.get("feature_count", 0)
        fields = []
        geojson = info.get("geojson") or {}
        if isinstance(geojson, dict):
            features = geojson.get("features", [])
            if features:
                for f in features[:15]:
                    props = f.get("properties") or {}
                    for k in props.keys():
                        if k not in fields and k != "_fid":
                            fields.append(k)
        fields_desc = f"，属性字段: {', '.join(fields[:8])}" if fields else ""
        examples = _layer_property_examples(geojson)
        examples_desc = f"，属性样例: {examples}" if examples else ""
        group_name = info.get("group_name", "")
        group_desc = f"，所属分组:「{group_name}」" if group_name else "，所属分组:未分组"
        lines.append(f"  - 图层「{name}」: {fc} 个要素（东西），几何类型: {types}，范围: {ext}{group_desc}{fields_desc}{examples_desc}")
    if terms:
        lines.append("\n按属性内容检索结果：")
        for term in terms:
            needle = term.casefold()
            term_hits = []
            for name, info in _registered_layers.items():
                features = (info.get("geojson") or {}).get("features", [])
                matched = []
                for feature in features:
                    props = feature.get("properties") or {}
                    if any(needle in str(value).casefold() for value in props.values() if value is not None):
                        matched.append(props)
                if matched or needle in name.casefold():
                    examples = []
                    for props in matched[:3]:
                        label = next((str(props[key]) for key in ("name", "name:zh", "名称", "poi_name", "医院名称", "NAME") if props.get(key)), "")
                        examples.append(label or str({k: v for k, v in props.items() if k != "_fid"})[:100])
                    term_hits.append(f"图层「{name}」命中 {len(matched)} 个要素" + (f"，样例: {', '.join(examples)}" if examples else "（关键词匹配图层名）"))
            lines.append(f"  - 关键词「{term}」: " + ("；".join(term_hits) if term_hits else "没有匹配到图层或要素属性"))
    lines.append("\n如需查看指定图层的具体属性明细或前几条要素内容，可进一步调用 get_layer_detail(layer_name) 工具；如需对图层做缓冲区、叠加分析、裁剪等处理，可直接调用对应 GIS 工具。")
    return "\n".join(lines)


@tool
def get_registered_layers(keyword: str = "") -> str:
    """查看当前已注册图层；可附关键词在全部图层属性中查找对应要素。

    【适用场景】
    - 用户询问“现在有几个图层”、“图层有几个东西”、“有哪些图层”、“当前地图有什么数据”
    - 对图层进行进一步空间分析、筛选或处理前，先查看当前图层状态和要素数
    - 不确定某个对象（如麦当劳、医院）在哪个图层时，将对象名放入 keyword 搜索属性值

    keyword 可用逗号、顿号或分号分隔多个对象名称；留空时返回图层概览及属性样例。
    """
    return _registered_layers_summary(keyword)


@tool
def list_layers() -> str:
    """查看当前工作区/地图所有已注册图层及要素数量（有几个要素/东西）、几何类型、覆盖范围、属性字段等详细信息。
    当用户询问“现在图层有几个东西”、“有哪些图层”、“查看图层列表”时调用此工具。"""
    return _registered_layers_summary()


@tool
def get_layer_detail(layer_name: str) -> str:
    """查看指定图层的详细数据内容，包括属性字段和要素预览。
    
    【适用场景】
    - 需要了解图层有哪些属性字段时
    - 需要查看图层的具体数据内容时
    - 做统计、制图、分析前先了解数据结构
    
    【参数】
    - layer_name: 图层名称（可模糊匹配）
    
    【返回】
    - 图层名称、要素数、几何类型、覆盖范围
    - 属性字段列表
    - 前 3 个要素的稳定 ID（可用于精确修改/删除单条要素）及业务属性预览
    """
    if not layer_name or not layer_name.strip():
        return f"错误：layer_name 不能为空，当前图层：{', '.join(_registered_layers.keys()) or '无'}"
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
    features = geojson.get("features", [])
    # 提取属性字段
    fields = set()
    for f in features[:50]:
        props = f.get("properties", {}) or {}
        fields.update(key for key in props if key != "_fid")
    fields = sorted(fields)
    # 属性样本（前 3 个要素）
    samples = []
    for f in features[:3]:
        props = f.get("properties", {}) or {}
        visible_props = {key: value for key, value in props.items() if key != "_fid"}
        if visible_props:
            samples.append((f, visible_props))
    bbox = info.get("bbox", [])
    result = [
        f"图层：{info['name']}",
        f"所属分组：{info.get('group_name') or '未分组'}",
        f"要素数：{info['feature_count']}",
        f"几何类型：{', '.join(info['geometry_types'])}",
        f"覆盖范围：{_format_extent(bbox)}",
    ]
    if fields:
        result.append(f"属性字段（{len(fields)}个）：{', '.join(fields)}")
    if samples:
        result.append("属性样本（前3个要素）：")
        for i, (feature, s) in enumerate(samples, 1):
            fid = (feature.get("properties") or {}).get("_fid", "未知")
            result.append(f"  要素{i}（稳定 ID: {fid}）: {json.dumps(s, ensure_ascii=False)[:200]}")
    return "\n".join(result)


# ============================================================
# 工具: datav_boundary — 行政边界
# ============================================================

@tool
def datav_boundary(name: str) -> str:
    """从阿里云 DataV 获取中国省/市/区三级行政边界，自动转 WGS-84 加载到地图。国外边界请调用 fetch_osm_boundary_or_features。查不到时尝试上级行政区划。"""
    try:
        from backend.services.datav_service import fetch_boundary, get_ambiguous_candidates
        # 1. 检查是否属于全国多地重名区县（如鼓楼区、朝阳区、西湖区等）且用户未指明所属地级市
        candidates = get_ambiguous_candidates(name)
        if candidates and len(candidates) > 1:
            matched_candidate = None
            for cand in candidates:
                city_short = cand["city"].rstrip("市")
                prov_short = cand["province"].rstrip("省").rstrip("市").rstrip("自治区")
                cand_label = cand.get("label", "")
                # 检查1：当前用户请求
                last_msg = runtime.get_last_user_message() or _last_user_message
                in_msg = bool(last_msg and (city_short in last_msg or prov_short in last_msg or cand_label in last_msg))
                # 检查2：多轮上下文记录
                conv_ctx = runtime.get_conversation_context() or _conversation_context
                in_ctx = bool(conv_ctx and (city_short in conv_ctx or prov_short in conv_ctx or cand_label in conv_ctx))
                # 检查3：已加载/已注册图层名
                in_layers = any(city_short in lyr_name or cand_label in lyr_name for lyr_name in _registered_layers)
                if in_msg or in_ctx or in_layers:
                    matched_candidate = cand
                    break
            if matched_candidate:
                name = matched_candidate["label"]
            else:
                # 弹出选项供用户点击选择（与遥感数据源选择一致的交互体验）
                options = [
                    {
                        "label": cand["label"],
                        "value": cand["label"],
                        "desc": cand.get("desc", ""),
                        "configured": True,
                    }
                    for cand in candidates
                ]
                return ask_user_choice.invoke({
                    "prompt": f"全国有多处「{name}」，请选择您需要分析的具体城市：",
                    "options": options,
                    "choice_key": "region_disambiguation",
                })

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
# 工具: drill_down / drill_up — 行政区下钻导航
# ============================================================

_LEVEL_NAMES = {"country": "国家", "province": "省级", "city": "地级市",
                "county": "区县", "district": "各区", "street": "街道"}


@tool
def drill_down(region: str = "", adcode: str = "") -> str:
    """行政区下钻：加载指定行政区（省/市/区县，名称或 6 位 adcode）的下一级边界并推送到地图。
    例如用户说「下钻到湖南」→ drill_down(region="湖南省")；「看长沙的区县」→ drill_down(region="长沙市")。
    需要素含 adcode 属性；数据来自 DataV（自动 GCJ-02→WGS-84），覆盖国家/省/市/区县四级。"""
    try:
        from backend.services.datav_service import fetch_boundary, fetch_boundary_by_adcode, _find_adcode
        code = adcode.strip() if adcode else ""
        if not code:
            if not region.strip():
                return "失败：请提供 region（行政区名称）或 adcode（6 位数字）"
            code = region.strip() if region.strip().isdigit() else str(_find_adcode(region.strip()))
        if not code.isdigit() or len(code) != 6:
            return f"失败：未能解析出 6 位 adcode（输入：{region or adcode}）"
        data = fetch_boundary_by_adcode(code)
        if data is None and region.strip():
            data = fetch_boundary(region.strip())
        if data is None:
            return f"失败：DataV 未找到 adcode={code} 的下级边界"
        feats = data.get("features", [])
        if not feats:
            return f"失败：adcode={code} 无下级行政区（可能已是区县级）"
        p0 = feats[0].get("properties", {})
        level = p0.get("level", "district")
        parent = p0.get("parent")
        if isinstance(parent, dict):
            parent = parent.get("name") or parent.get("adcode") or ""
        region_arg = region.strip() if (region.strip() and not region.strip().isdigit()) else ""
        if parent and not str(parent).isdigit():
            child_name = parent          # DataV 返回了父级名
        elif region_arg:
            child_name = region_arg      # 用户输入的区域名（如"武汉市"）
        else:
            child_name = code            # 只有 adcode 时兜底
        layer_name = f"{child_name}_{_LEVEL_NAMES.get(level, level)}"
        _push_layer(layer_name, data, {"color": "#e74c3c", "fillColor": "#e74c3c", "fillOpacity": 0.25})
        _register_layer(layer_name, data)
        # 通知前端下钻状态机（面包屑/相机/图层显隐由前端统一处理）
        _pending_layer_ops.append({
            "action": "drill",
            "direction": "down",
            "adcode": code,
            "name": child_name,
            "level": level,
            "layer_name": layer_name,
        })
        names = [f.get("properties", {}).get("name", "?") for f in feats[:15]]
        preview = "、".join(n for n in names if n)
        more = f" 等 {len(feats)} 个" if len(feats) > 15 else ""
        return (f"已下钻到「{child_name}」的{_LEVEL_NAMES.get(level, level)}层级，"
                f"加载 {len(feats)} 个行政区：{preview}{more}。已加载到地图并推入下钻导航。")
    except Exception as e:
        return f"下钻失败：{str(e)[:200]}"


@tool
def drill_up() -> str:
    """行政区上钻（返回上一级）：撤销最近一次下钻，恢复父级行政区视图。对应前端面包屑「返回」。"""
    _pending_layer_ops.append({"action": "drill", "direction": "up"})
    return "已返回上一级行政区划。"


# ============================================================
# 工具: visualize_3d — 3D 地球数据驱动可视化
# ============================================================

@tool
def visualize_3d(layer_name: str, field: str, max_height: float = 50000, viz_type: str = "extrusion") -> str:
    """3D 可视化：在 3D 地球上把图层数据做数据驱动展示。viz_type="extrusion"（默认）按数值字段把
    面要素拉伸成柱体（如人口/GDP 立柱对比），max_height 为最大高度（米，默认 50000）。
    例：「在3D上把湖南省各市人口拉成柱子」→ visualize_3d(layer_name="湖南省_省级", field="人口", max_height=200000)。
    仅面图层支持拉伸；字段需为数值型。前端收到 spec 后按值归一化着色并拉伸。"""
    info = _registered_layers.get(layer_name)
    if not info:
        return f"图层 {layer_name} 未找到"
    viz_type = (viz_type or "extrusion").strip().lower()
    if viz_type != "extrusion":
        return f"失败：暂不支持的可视化类型「{viz_type}」（目前仅 extrusion 拉伸）"
    try:
        max_height = float(max_height)
    except (TypeError, ValueError):
        return f"失败：max_height 需为数值（输入：{max_height}）"
    if not (10 <= max_height <= 2000000):
        return f"失败：max_height 超出合理范围 10~2000000 米（输入：{max_height}）"

    features = (info.get("geojson") or {}).get("features", [])
    if not features:
        return f"图层 {layer_name} 无要素"
    has_poly = any(
        (f.get("geometry") or {}).get("type", "").find("Polygon") != -1
        for f in features
    )
    if not has_poly:
        return f"失败：extrusion 拉伸仅支持面（Polygon）图层，「{layer_name}」不含面要素"
    numeric = 0
    for f in features[:200]:
        try:
            float((f.get("properties") or {}).get(field))
            numeric += 1
        except (TypeError, ValueError):
            continue
    if numeric == 0:
        sample = [k for k in list((features[0].get("properties") or {}).keys()) if k != "_fid"][:10]
        return f"失败：字段「{field}」无数值数据。可用字段参考：{sample}"
    _pending_layer_ops.append({
        "action": "visualize",
        "name": layer_name,
        "viz": {"type": "extrusion", "field": field, "maxHeight": max_height},
    })
    return (f"已按「{field}」对图层「{layer_name}」应用 3D 拉伸（最大高度 {int(max_height)} 米），"
            f"切换到 3D 视图即可查看柱状对比。")


# ============================================================
# 工具: create_heatmap — 热力图
# ============================================================

@tool
def create_heatmap(layer_name: str, weight_field: str = "", radius: int = 20, gradient: str = "") -> str:
    """从点图层生成热力图。需先有点图层（含权重字段）。参数：weight_field（权重字段）、radius（1–100像素，默认20）、gradient（渐变色如"0.4=blue,1.0=red"）。"""
    info = _registered_layers.get(layer_name)
    if not info:
        return f"图层 {layer_name} 未找到"
    if isinstance(radius, bool) or not isinstance(radius, int) or not 1 <= radius <= 100:
        return "热力图半径范围为 1 到 100 像素"
    try:
        import geopandas as gpd
        import pandas as pd
        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层 {layer_name} 为空"
        pg = gdf[gdf.geometry.type.isin(["Point", "MultiPoint"])]
        if pg.empty:
            return "没有点要素，无法生成热力图"
        if weight_field and weight_field not in pg.columns:
            available_fields = [str(column) for column in pg.columns if column != "geometry"][:12]
            return f"权重字段「{weight_field}」不存在，可用字段：{available_fields or '无'}"
        pts = []
        skipped_weights = 0
        for _, r in pg.iterrows():
            g = r.geometry
            v = 1.0
            if weight_field:
                raw_weight = r[weight_field]
                try:
                    missing_weight = bool(pd.isna(raw_weight))
                except (TypeError, ValueError):
                    missing_weight = False
                if missing_weight:
                    skipped_weights += 1
                    continue
                try:
                    v = float(raw_weight)
                except (TypeError, ValueError, OverflowError):
                    return f"权重字段「{weight_field}」包含非数值内容，无法生成热力图"
                if not math.isfinite(v):
                    skipped_weights += 1
                    continue
            if g.geom_type == "MultiPoint":
                for p in g.geoms:
                    pts.append([p.y, p.x, v])
            else:
                pts.append([g.y, g.x, v])

        if not pts:
            return f"权重字段「{weight_field}」没有有限数值，无法生成热力图" if weight_field else "没有可用于生成热力图的点"

        grad = None
        if gradient:
            from matplotlib.colors import is_color_like

            grad = {}
            try:
                parts = gradient.split(",")
                for part in parts:
                    if "=" not in part:
                        return "热力图渐变格式无效，请使用 0.4=blue,1.0=red 格式"
                    key, color = part.split("=", 1)
                    stop = float(key.strip())
                    color = color.strip()
                    if (not math.isfinite(stop) or not 0 <= stop <= 1 or
                            not color or stop in grad or not is_color_like(color)):
                        return "热力图渐变参数无效：阈值须在 0 到 1 之间，颜色须为有效颜色"
                    grad[stop] = color
            except (TypeError, ValueError, OverflowError):
                return "热力图渐变格式无效，请使用 0.4=blue,1.0=red 格式"

        opts = {"radius": radius, "blur": max(10, radius - 5)}
        if grad:
            opts["gradient"] = grad
        _pending_heatmap["latest"] = {"points": pts, "name": f"{layer_name}_heat", "options": opts}
        skipped_note = f"，跳过 {skipped_weights} 个空或非有限权重" if skipped_weights else ""
        return f"热力图已生成：{len(pts)} 个点{skipped_note}"
    except Exception as e:
        return f"热力图生成失败: {str(e)}"


# ============================================================
# 工具: measure_area — 精确面积测量（自动选投影）
# ============================================================

@tool
def measure_area(layer_name: str) -> str:
    """测量指定图层面积：局部范围使用 UTM，大范围/跨带范围使用 WGS-84 椭球面积，支持多要素汇总。

【精度保障】
- 内部自动投影到 UTM 投影坐标系，WGS84 数据可直接使用。
- 返回平方公里（km2）、平方米（m2）、亩。

【常见坑】
- execute_python 中自定义面积计算必须先 to_crs 到投影坐标系，否则单位是平方度。
- 面图层有重叠时总面积重复计算，先用 topology_check 或 spatial_dissolve。
- 几何无效（自相交）会导致面积异常，先修复。"""
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
        # 用 bounds 中心确定 UTM 带号（避免在 geographic CRS 下计算 centroid 的 warning）
        _b = gdf.total_bounds
        lon, lat = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2

        min_zone = max(1, min(60, int(np.floor((_b[0] + 180) / 6)) + 1))
        max_zone = max(1, min(60, int(np.floor((_b[2] + 180) / 6)) + 1))
        use_geodesic_area = (
            (_b[2] - _b[0]) > 6.0 or (_b[3] - _b[1]) > 6.0
            or min_zone != max_zone or _b[1] < -80.0 or _b[3] > 84.0
        )
        cross_check = ""
        if use_geodesic_area:
            from pyproj import Geod
            geod = Geod(ellps="WGS84")

            def _geodesic_geometry_area(geometry):
                if geometry is None or geometry.is_empty:
                    return 0.0
                if geometry.geom_type == "Polygon":
                    def ring_area(ring):
                        coordinates = list(ring.coords)
                        return abs(geod.polygon_area_perimeter(
                            [point[0] for point in coordinates],
                            [point[1] for point in coordinates],
                        )[0])
                    return max(0.0, ring_area(geometry.exterior) - sum(
                        ring_area(ring) for ring in geometry.interiors
                    ))
                if geometry.geom_type in ("MultiPolygon", "GeometryCollection"):
                    return sum(_geodesic_geometry_area(part) for part in geometry.geoms)
                return 0.0

            area_m2 = sum(_geodesic_geometry_area(geometry) for geometry in gdf.geometry)
            area_method = "WGS-84 椭球大地面积（大范围/跨 UTM 带）"
        else:
            # UTM 带号：zone = floor((lon + 180) / 6) + 1，严格限制在 1~60
            utm_zone = int(np.floor((lon + 180) / 6)) + 1
            utm_zone = max(1, min(60, utm_zone))
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
            area_method = f"UTM {utm_zone}{hemi}（EPSG:{epsg_code}）"

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
        area_km2 = area_m2 / 1_000_000

        feat_count = len(gdf)
        geom_types = gdf.geometry.type.unique().tolist()

        result = (
            f"图层「{layer_name}」面积测量结果：\n"
            f"- 面积：{area_km2:.2f} 平方公里\n"
            f"- 面积方法：{area_method}"
        )
        if cross_check:
            result += f"\n- 交叉验证：{cross_check}"
        result += (
            f"\n- 几何类型：{', '.join(geom_types)}"
            f"\n- 要素数：{feat_count}"
            f"\n- 中心点：{lat:.4f}°, {lon:.4f}°"
            f"\n- 坐标系：WGS-84"
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
        lon1, lat1, lon2, lat2 = map(float, (lon1, lat1, lon2, lat2))
        if not all(math.isfinite(value) for value in (lon1, lat1, lon2, lat2)):
            return "输入坐标必须是有限数值，范围为经度 -180～180、纬度 -90～90"
        if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180
                and -90 <= lat1 <= 90 and -90 <= lat2 <= 90):
            return "输入坐标超出 WGS-84 范围：经度 -180～180、纬度 -90～90"
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
    """计算并添加新字段到指定图层。field_type 可选 str/int/float（及 string/text/integer/double/number 别名）。expression 写 Python 表达式（如"面积*0.0015"），直接引用字段名。支持 abs/round/int/float/str/len/min/max/sum/pow。自动更新地图。"""
    try:
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error
        if not isinstance(new_field, str) or not new_field.strip():
            return "字段计算失败：新字段名不能为空"
        if not isinstance(field_type, str):
            return f"字段计算失败：不支持字段类型「{field_type}」，请选择 str、int 或 float"
        field_type = field_type.lower().strip()
        if field_type in ("string", "text"):
            field_type = "str"
        elif field_type == "integer":
            field_type = "int"
        elif field_type in ("double", "number"):
            field_type = "float"
        if field_type not in ("str", "int", "float"):
            return f"字段计算失败：不支持字段类型「{field_type}」，请选择 str、int 或 float"
        if new_field == "_fid":
            return "字段计算失败：_fid 是要素稳定标识，不能覆盖"
        if new_field == "geometry":
            return "字段计算失败：geometry 是几何列，不能覆盖"

        import geopandas as gpd
        import pandas as pd
        import numpy as np
        import json

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层 {layer_name} 为空"
        if new_field in gdf.columns:
            return f"字段计算失败：字段「{new_field}」已存在，不能覆盖；请使用新的字段名"

        eval_gdf = gdf.copy(deep=True)
        for column in eval_gdf.columns:
            if column == "geometry":
                continue
            values = eval_gdf[column].tolist()
            eval_gdf[column] = pd.Series(
                [np.nan if pd.isna(value) else value for value in values],
                index=eval_gdf.index,
                dtype=object,
            )

        safe_globals = {"__builtins__": {}}
        safe_locals = {
            "abs": abs, "round": round, "int": int, "float": float,
            "str": str, "len": len, "min": min, "max": max,
            "sum": sum, "pow": pow, "bool": bool,
        }
        try:
            _fc_tree = ast.parse(expression, mode="eval")
            _validate_field_calculation_ast(
                _fc_tree, set(eval_gdf.columns) - {"geometry"}
            )
        except Exception as e:
            return f"表达式计算失败：{str(e)[:200]}"

        _fc_code = compile(_fc_tree, "<safe>", "eval")
        try:
            result = eval_gdf.eval(expression, local_dict=safe_locals, global_dict=safe_globals)
            gdf[new_field] = result
        except Exception:
            try:
                result = eval_gdf.apply(lambda row: eval(_fc_code, safe_globals, {**safe_locals, **row.to_dict()}), axis=1)
                gdf[new_field] = result
            except Exception as e2:
                return f"表达式计算失败：{str(e2)[:200]}"

        gdf[new_field] = pd.Series(
            [
                None if isinstance(value, (float, np.floating)) and not np.isfinite(value) else value
                for value in gdf[new_field].tolist()
            ],
            index=gdf.index,
            dtype=object,
        )

        if field_type in ("int", "float"):
            def convert_field_value(value):
                if value is None or pd.isna(value):
                    return None
                if isinstance(value, (float, np.floating)) and not np.isfinite(value):
                    return None
                if field_type == "int":
                    return int(value)
                # Keep Python integers exact; converting values above 2**53 to
                # float would silently corrupt GIS attributes during export.
                if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
                    return int(value)
                return float(value)

            try:
                gdf[new_field] = pd.Series(
                    [convert_field_value(value) for value in gdf[new_field].tolist()],
                    index=gdf.index,
                    dtype=object,
                )
            except (TypeError, ValueError, OverflowError) as conversion_error:
                return f"字段类型转换失败：无法将字段「{new_field}」转换为 {field_type}（{str(conversion_error)[:160]}）"
        elif field_type == "str":
            gdf[new_field] = gdf[new_field].map(lambda value: None if pd.isna(value) else str(value))

        # 将非有限结果编码为 GeoJSON null，保留原有缺失值；不能把无效计算改写成有效的 0。
        try:
            gdf[new_field] = gdf[new_field].replace([np.inf, -np.inf], np.nan)
        except Exception:
            pass

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name

        _update_registered_layer_data(layer_name, geojson_data)
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
    with runtime._state_lock:
        count = len(runtime._registered_layers)
        runtime._registered_layers.clear()
        runtime._pending_layers.clear()
        runtime._pending_layer_ops.clear()
        runtime._clear_layers_flag = True
    return f"已清空 {count} 个图层"


# ============================================================
# 工具: login_gscloud — 地理空间数据云自动登录状态
# ============================================================
# 当前无浏览器登录实现；明确告知 Agent 由用户手动登录和下载，避免模拟成功。

@tool
def login_gscloud() -> str:
    """说明当前版本不支持自动登录，引导用户手动获取数据。"""
    return json.dumps({
        "success": False,
        "reason": "当前版本不支持自动登录地理空间数据云，也不会验证已保存的账号密码。",
        "hint": (
            "请在浏览器中登录 https://www.gscloud.cn 手动检索并下载数据，"
            "再将下载文件上传到 GIS WorkTable。"
        ),
    }, ensure_ascii=False)


# ============================================================
# 工具: get_session_logs — 查询历史
# ============================================================

@tool
def get_session_logs(n: int = 20) -> str:
    """查看最近的问答日志，包含用户问题、AI回复、当时有哪些图层"""
    try:
        from backend.services.log_service import get_temp_log, get_perm_log
        from backend.services import pending_action
        records = get_temp_log(pending_action.get_active_session())
        perm = get_perm_log(5)
        if not records and not perm:
            return "暂无日志记录"
        lines = [f"== 当前会话（{len(records)} 次问答） =="]
        limit = max(1, min(100, int(n)))
        for i, r in enumerate(records[-limit:], 1):
            t = r.get("time", "")[:19].replace("T", " ") if r.get("time") else ""
            user_msg = r.get("user", "")[:80]
            ai_msg = r.get("ai", "")[:100]
            layers = r.get("layers", {})
            layer_info = ", ".join(layers.keys()) if layers else "无"
            lines.append(f"{i}. [{t}] 问：{user_msg}")
            lines.append(f"   答：{ai_msg}")
            lines.append(f"   图层：{layer_info}")

        if perm:
            lines.append(f"== 历史问题记录（{len(perm)} 条） ==")
            for r in perm:
                pt = r.get("time", "")[:19].replace("T", " ") if r.get("time") else ""
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
    """控制地图上的图层。action 参数：remove(删除) toggle(显隐) set_color(改色+color) set_style(设置完整样式+color+opacity+weight+fill_pattern) clear_symbology(清除分级/唯一值符号化和图例) rename(重命名+new_name) fit(缩放至图层)。opacity: 0~1，weight: 线宽像素数，fill_pattern: hatch/crosshatch/dots/grid/diagonal。"""
    if action in ("remove", "toggle", "set_color", "set_style", "clear_symbology", "fit", "rename"):
        resolved, _, error = _get_exact_registered_layer(name)
        if not resolved:
            return error.replace("未执行修改", "未执行操作")
        name = resolved
    if action == "remove":
        _pending_layer_ops.append({"action": "remove", "name": name})
        _unregister_layer(name)
        return f"已删除图层: {name}（当前剩余 {len(_registered_layers)} 个图层）"
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
    elif action == "clear_symbology":
        _pending_layer_ops.append({"action": "clear_symbology", "name": name})
        return f"已标记清除图层「{name}」的分级/唯一值符号化与对应图例"
    elif action == "rename":
        if not isinstance(new_name, str) or not new_name.strip():
            return "图层重命名失败: 新图层名不能为空；未重命名任何图层"
        new_name = new_name.strip()
        with _state_lock:
            if name not in _registered_layers:
                return f"图层重命名失败: 图层「{name}」已被移除，请刷新后重试"
            if new_name != name and new_name in _registered_layers:
                return f"图层重命名失败: 图层「{new_name}」已存在；未重命名任何图层"
            _registered_layers[new_name] = _registered_layers.pop(name)
            _registered_layers[new_name]["name"] = new_name
            # Invalidate session-scoped AI handles bound to the previous name.
            _registered_layers[new_name]["registration_token"] = uuid.uuid4().hex
            _pending_layer_ops.append({"action": "rename", "name": name, "new_name": new_name})
        return f"已重命名图层: {name} → {new_name}"
    elif action == "fit":
        _pending_layer_ops.append({"action": "fit", "name": name})
        return f"已标记缩放到图层: {name}"
    else:
        return f"未知操作: {action}，可选：remove / toggle / set_color / set_style / clear_symbology / rename / fit"


# ============================================================
# 工具: focus_map — 地图定位
# ============================================================

@tool
def focus_map(layer_name: str = "", center: str = "", zoom: int = 13) -> str:
    """将地图视野定位/飞到指定位置（用户说"定位一下""飞过去""看看在哪""跳转到"时调用）。
    两种模式二选一：
    1. layer_name: 定位到指定图层的范围（缩放至该图层），如 focus_map(layer_name="上海火车站")
    2. center: 定位到指定经纬度，格式"经度,纬度"，如 focus_map(center="121.4593,31.2513", zoom=15)
    不知道坐标时可先用 geocode 或 POI 搜索获取经纬度。"""
    if layer_name:
        if layer_name in _registered_layers:
            _pending_layer_ops.append({"action": "fit", "name": layer_name})
            return f"已定位到图层「{layer_name}」（缩放至其范围）"
        for _key in list(_registered_layers.keys()):
            if layer_name in _key or _key in layer_name:
                _pending_layer_ops.append({"action": "fit", "name": _key})
                return f"已定位到图层「{_key}」（缩放至其范围）"
        _names = "、".join(_registered_layers.keys()) or "无"
        return f"未找到图层「{layer_name}」，当前图层：{_names}。可改用 center 参数按坐标定位。"
    if center:
        try:
            parts = center.replace("，", ",").split(",")
            if len(parts) != 2:
                return f"center 格式应为「经度,纬度」，收到：{center}"
            lon, lat = float(parts[0].strip()), float(parts[1].strip())
            if (not math.isfinite(lon) or not math.isfinite(lat)
                    or not -180 <= lon <= 180 or not -90 <= lat <= 90):
                return "坐标范围无效：经度须在 -180 到 180 之间，纬度须在 -90 到 90 之间。"
            _z = max(3, min(19, int(zoom)))
            _pending_layer_ops.append({"action": "center", "center": [lon, lat], "zoom": _z})
            return f"已定位到 ({lat:.4f}, {lon:.4f})，缩放级别 {_z}"
        except ValueError:
            return f"无法解析坐标：{center}，格式应为「经度,纬度」（如 121.4593,31.2513）"
    return "请提供 layer_name（图层名）或 center（「经度,纬度」）进行定位"


# ============================================================
# 工具: export_layer — 导出图层
# ============================================================

# Note: _safe_layer_export_stem is imported above from backend.services.tool_modules.common


def _json_script_value(value) -> str:
    """Serialize JSON embedded in a script element without raw HTML delimiters."""
    return (json.dumps(value, ensure_ascii=False)
            .replace("&", r"\u0026")
            .replace("<", r"\u003c")
            .replace(">", r"\u003e")
            .replace("\u2028", r"\u2028")
            .replace("\u2029", r"\u2029"))


_geojson_to_export_gdf = _io_export.geojson_to_export_gdf


@tool
def export_layer(layer_name: str, format: str = "geojson") -> str:
    """导出指定矢量图层并提供下载链接。format 可选 geojson、shp、gpkg、csv、csv_xy；csv 只导出属性，csv_xy 导出属性及经纬度且仅支持 Point 要素。栅格图层当前不支持此导出工具。"""
    return _io_export.export_layer_impl(
        layer_name,
        format,
        registered_layers=_registered_layers,
        safe_layer_export_stem=_safe_layer_export_stem,
        output_dir_getter=get_temp_output_dir,
        record_tool_artifact=record_tool_artifact,
        geojson_to_export_gdf=_geojson_to_export_gdf,
    )

# ============================================================
# 工具: create_chart — 统计图表
# ============================================================

@tool
def create_chart(layer_name: str, chart_type: str = "bar", field: str = "",
                 x_field: str = "", y_field: str = "", title: str = "") -> str:
    """从图层属性数据生成 ECharts 统计图表。用户要看统计图表/分布时优先用本工具。
    chart_type 可选: bar(柱状图) pie(饼图) histogram(直方图) scatter(散点图) line(折线图)
    单字段统计传 field，双字段对比传 x_field+y_field。"""
    if chart_type not in {"bar", "pie", "histogram", "scatter", "line"}:
        return "图表生成失败：chart_type 仅支持 bar、pie、histogram、scatter、line"
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

        # 生成高质感自适应 ECharts HTML
        if chart_type == "histogram":
            f = field or prop_keys[0]
            counter = _value_counts(f)
            items = sorted([(k, v) for k, v in counter.items() if isinstance(k, (int, float))])
            if not items:
                items = list(counter.items())
            if not items:
                return f"字段「{f}」无有效数值数据"
            labels = [str(k) for k, _ in items]
            values = [v for _, v in items]
            series_cfg = json.dumps([{"type": "bar", "data": values, "name": f}], ensure_ascii=False)
            x_data_cfg = json.dumps(labels, ensure_ascii=False)
            y_name_cfg = "频数"

        elif chart_type == "pie":
            f = field or prop_keys[0]
            counter = _value_counts(f)
            items = list(counter.items())
            if not items:
                return f"字段「{f}」无有效数据"
            items = sorted(items, key=lambda x: x[1], reverse=True)[:20]
            pie_data = [{"name": str(k), "value": v} for k, v in items]
            series_cfg = json.dumps([{
                "type": "pie", "radius": ["35%", "65%"], "center": ["50%", "56%"],
                "data": pie_data,
                "label": {"fontSize": 11, "color": "auto"},
                "itemStyle": {"borderRadius": 5}
            }], ensure_ascii=False)
            x_data_cfg = "[]"
            y_name_cfg = ""

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
            series_cfg = json.dumps([{"type": "scatter", "data": scatter_data, "symbolSize": 8}], ensure_ascii=False)
            x_data_cfg = "[]"
            y_name_cfg = yf

        else:
            # bar / line：柱状图或折线图
            f = field or prop_keys[0]
            series_type = "line" if chart_type == "line" else "bar"
            if x_field and y_field:
                xf, yf = x_field, y_field
                bar_data = []
                bar_labels = []
                for p in props_list:
                    try:
                        bar_labels.append(str(p.get(xf, "")))
                        bar_data.append(float(p.get(yf, 0)))
                    except (ValueError, TypeError):
                        pass
                series_cfg = json.dumps([{"type": series_type, "data": bar_data, "name": yf}], ensure_ascii=False)
                x_data_cfg = json.dumps(bar_labels, ensure_ascii=False)
                y_name_cfg = yf
            else:
                counter = _value_counts(f)
                items = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:30]
                if not items:
                    return f"字段「{f}」无有效数据"
                labels = [str(k) for k, _ in items]
                values = [v for _, v in items]
                series_cfg = json.dumps([{"type": series_type, "data": values, "name": f}], ensure_ascii=False)
                x_data_cfg = json.dumps(labels, ensure_ascii=False)
                y_name_cfg = "数值"

        import html as html_module
        safe_title_html = html_module.escape(chart_title, quote=True)
        chart_title_js = _json_script_value(chart_title)
        chart_type_js = _json_script_value(chart_type)
        y_name_js = _json_script_value(y_name_cfg)
        series_cfg = _json_script_value(json.loads(series_cfg))
        x_data_cfg = _json_script_value(json.loads(x_data_cfg))

        echarts_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title_html}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    transition: background-color 0.2s, color 0.2s;
  }}
  #chart {{
    width: 100%;
    height: 100%;
  }}
  .chart-toolbar {{
    position: fixed;
    top: 10px;
    right: 14px;
    display: flex;
    gap: 6px;
    z-index: 100;
  }}
  .chart-toolbar button {{
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 500;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
  }}
</style>
</head>
<body>
<div class="chart-toolbar">
  <button id="btnSvg" onclick="downloadSVG()">导出 SVG</button>
  <button id="btnPng" onclick="downloadPNG()">导出 PNG</button>
</div>
<div id="chart"></div>
<script>
  // 主题自适应侦测（暗色 / 亮色）
  var isDark = true;
  try {{
    if (window.parent && window.parent.document && window.parent.document.documentElement) {{
      var pDoc = window.parent.document.documentElement;
      isDark = pDoc.classList.contains('theme-dark') || !pDoc.classList.contains('theme-light');
    }} else {{
      isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    }}
  }} catch(e) {{
    isDark = true;
  }}

  var colors = {{
    bg: isDark ? '#18181b' : '#ffffff',
    text: isDark ? '#f8fafc' : '#0f172a',
    subText: isDark ? '#94a3b8' : '#64748b',
    axisLine: isDark ? 'rgba(255, 255, 255, 0.18)' : 'rgba(0, 0, 0, 0.15)',
    splitLine: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.06)',
    btnBg: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.05)',
    btnBorder: isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(0, 0, 0, 0.12)',
    btnText: isDark ? '#cbd5e1' : '#475569',
    palette: ['#38bdf8', '#818cf8', '#34d399', '#fbbf24', '#f87171', '#c084fc', '#2dd4bf', '#fb923c']
  }};

  document.body.style.backgroundColor = colors.bg;
  document.body.style.color = colors.text;

  var btnSvg = document.getElementById('btnSvg');
  var btnPng = document.getElementById('btnPng');
  [btnSvg, btnPng].forEach(function(b) {{
    if (!b) return;
    b.style.backgroundColor = colors.btnBg;
    b.style.border = '1px solid ' + colors.btnBorder;
    b.style.color = colors.btnText;
  }});

  var chart = echarts.init(document.getElementById('chart'), null, {{ renderer: 'svg' }});
  var seriesRaw = {series_cfg};
  var xData = {x_data_cfg};
  var chartType = {chart_type_js};
  var yAxisName = {y_name_js};

  // 系列美化与渐变
  seriesRaw.forEach(function(s) {{
    if (s.type === 'bar') {{
      s.barWidth = '40%';
      s.itemStyle = {{
        borderRadius: [4, 4, 0, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          {{ offset: 0, color: '#38bdf8' }},
          {{ offset: 1, color: '#0284c7' }}
        ])
      }};
      s.emphasis = {{
        itemStyle: {{
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            {{ offset: 0, color: '#7dd3fc' }},
            {{ offset: 1, color: '#0369a1' }}
          ])
        }}
      }};
    }} else if (s.type === 'line') {{
      s.smooth = true;
      s.symbolSize = 6;
      s.lineStyle = {{ width: 2.5, color: '#38bdf8' }};
      s.itemStyle = {{ color: '#38bdf8' }};
      s.areaStyle = {{
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          {{ offset: 0, color: isDark ? 'rgba(56, 189, 248, 0.28)' : 'rgba(2, 132, 199, 0.2)' }},
          {{ offset: 1, color: isDark ? 'rgba(56, 189, 248, 0.02)' : 'rgba(2, 132, 199, 0.01)' }}
        ])
      }};
    }} else if (s.type === 'scatter') {{
      s.symbolSize = 8;
      s.itemStyle = {{
        color: '#38bdf8',
        borderColor: isDark ? '#18181b' : '#ffffff',
        borderWidth: 1.2
      }};
    }}
  }});

  var option = {{
    backgroundColor: 'transparent',
    color: colors.palette,
    title: {{
      text: {chart_title_js},
      left: 10,
      top: 8,
      textStyle: {{
        color: colors.text,
        fontSize: 14,
        fontWeight: 600
      }}
    }},
    tooltip: {{
      trigger: chartType === 'pie' ? 'item' : 'axis',
      backgroundColor: isDark ? 'rgba(24, 24, 27, 0.94)' : 'rgba(255, 255, 255, 0.96)',
      borderColor: colors.btnBorder,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: {{ color: colors.text, fontSize: 12 }},
      extraCssText: 'box-shadow: 0 8px 24px rgba(0,0,0,0.35); backdrop-filter: blur(8px); border-radius: 6px;',
      axisPointer: {{
        type: 'shadow',
        shadowStyle: {{ color: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.04)' }}
      }}
    }},
    grid: chartType === 'pie' ? undefined : {{
      left: 10,
      right: 14,
      top: 64,
      bottom: 16,
      containLabel: true
    }},
    xAxis: chartType === 'pie' ? undefined : {{
      type: chartType === 'scatter' ? 'value' : 'category',
      data: chartType === 'scatter' ? undefined : xData,
      axisLine: {{ lineStyle: {{ color: colors.axisLine }} }},
      axisTick: {{ alignWithLabel: true, lineStyle: {{ color: colors.axisLine }} }},
      axisLabel: {{
        color: colors.subText,
        fontSize: 11,
        rotate: 35,
        margin: 10
      }},
      splitLine: chartType === 'scatter' ? {{ lineStyle: {{ color: colors.splitLine, type: 'dashed' }} }} : undefined
    }},
    yAxis: chartType === 'pie' ? undefined : {{
      type: 'value',
      name: yAxisName,
      nameTextStyle: {{
        color: colors.subText,
        fontSize: 11,
        align: 'left',
        padding: [0, 0, 8, 0]
      }},
      axisLine: {{ show: false }},
      axisTick: {{ show: false }},
      axisLabel: {{ color: colors.subText, fontSize: 11 }},
      splitLine: {{
        lineStyle: {{
          color: colors.splitLine,
          type: 'dashed'
        }}
      }}
    }},
    series: seriesRaw
  }};

  chart.setOption(option);
  window.addEventListener('resize', function() {{ chart.resize(); }});

  function downloadSVG() {{
    var svg = document.querySelector('#chart svg');
    if (!svg) {{ alert('SVG not found'); return; }}
    var s = new XMLSerializer();
    var str = '<?xml version="1.0" encoding="utf-8"?>' + s.serializeToString(svg);
    var blob = new Blob([str], {{ type: 'image/svg+xml;charset=utf-8' }});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a'); a.href = url; a.download = 'chart.svg'; a.click();
    URL.revokeObjectURL(url);
  }}
  function downloadPNG() {{
    var url = chart.getDataURL({{ type: 'png', pixelRatio: 2, backgroundColor: colors.bg }});
    var a = document.createElement('a'); a.href = url; a.download = 'chart.png'; a.click();
  }}
</script>
</body>
</html>"""

        # 保存 HTML 并推送到前端
        init_temp_dir()
        fname = f"chart_{now_ts}_{uuid.uuid4().hex}.html"
        fpath = os.path.join(_temp_output_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(echarts_html)

        _add_pending_item(f"/output/{fname}", fpath)
        return f"图表已生成：{chart_title}（{chart_type}图），可在聊天中查看"

    except Exception as e:
        import traceback
        return f"图表生成失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# Re-exported from backend.services.tool_modules: download_road_network, network_analysis, spatial_buffer, spatial_multi_ring_buffer


# ============================================================
# 工具: move_features — 移动要素
# ============================================================

@tool
def move_features(layer_name: str, dx: float = 0, dy: float = 0, unit: str = "m") -> str:
    """移动指定图层的所有要素。dx 为东西方向位移（正=东/负=西），dy 为南北方向位移（正=北/负=南）。
    unit 可选 m(米) 或 km(公里)。自动 UTM 投影保证距离精确。"""
    try:
        import geopandas as gpd
        import math
        import warnings

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        try:
            dx, dy = float(dx), float(dy)
        except (TypeError, ValueError, OverflowError):
            return "移动要素失败：位移量必须是有限数值"
        if not math.isfinite(dx) or not math.isfinite(dy):
            return "移动要素失败：位移量必须是有限数值"

        if dx == 0 and dy == 0:
            return "位移量 dx 和 dy 不能同时为 0"

        requested_dx, requested_dy = dx, dy
        if unit == "km":
            dx *= 1000
            dy *= 1000
        elif unit != "m":
            return f"不支持的单位「{unit}」，请用 m 或 km"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
        # 用 bounds 中心确定 UTM 带号（避免 geographic CRS 下计算 centroid 的 warning）
        _b = gdf.total_bounds
        extent_error = _local_utm_extent_error(_b)
        if extent_error:
            return f"移动要素失败: {extent_error}；未修改图层"
        lon, lat = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2
        crs_utm = _get_utm_crs(lon, lat)

        gdf_utm = gdf.to_crs(crs_utm)
        gdf_utm.geometry = gdf_utm.geometry.translate(xoff=dx, yoff=dy)

        gdf_result = gdf_utm.to_crs("EPSG:4326")
        geojson_data = gdf_result.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        dir_x = "东" if dx > 0 else ("西" if dx < 0 else "")
        dir_y = "北" if dy > 0 else ("南" if dy < 0 else "")
        dir_str = (dir_y + dir_x) if (dx != 0 and dy != 0) else (dir_y or dir_x)
        unit_str = "km" if unit == "km" else "m"
        return (f"已移动图层「{layer_name}」{dir_str}方向 "
                f"（{requested_dx}{unit_str}, {requested_dy}{unit_str}），"
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
        import numpy as np
        import warnings

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        try:
            angle = float(angle)
        except (TypeError, ValueError, OverflowError):
            return "旋转要素失败：角度必须是有限数值"
        if not np.isfinite(angle):
            return "旋转要素失败：角度必须是有限数值"

        bounds = gdf.total_bounds
        extent_error = _local_utm_extent_error(bounds)
        if extent_error:
            return f"旋转要素失败: {extent_error}；未修改图层"
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        metric_crs = _get_utm_crs(lon, lat)
        gdf_metric = gdf.to_crs(metric_crs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            center = gdf_metric.dissolve().centroid.iloc[0]

        gdf_metric.geometry = gdf_metric.geometry.rotate(angle, origin=(center.x, center.y), use_radians=False)
        gdf_result = gdf_metric.to_crs("EPSG:4326")

        geojson_data = gdf_result.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        direction = "逆时针" if angle > 0 else "顺时针"
        return (f"已旋转图层「{layer_name}」{abs(angle)}°（{direction}），"
                f"{len(gdf_result)} 个要素，已同步地图")
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
        import math
        import warnings

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        try:
            x_factor, y_factor = float(x_factor), float(y_factor)
        except (TypeError, ValueError, OverflowError):
            return "缩放倍数必须是有限且大于 0 的数值"
        if not math.isfinite(x_factor) or not math.isfinite(y_factor) or x_factor <= 0 or y_factor <= 0:
            return "缩放倍数必须大于 0"

        bounds = gdf.total_bounds
        extent_error = _local_utm_extent_error(bounds)
        if extent_error:
            return f"缩放要素失败: {extent_error}；未修改图层"
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        gdf_metric = gdf.to_crs(_get_utm_crs(lon, lat))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            center = gdf_metric.dissolve().centroid.iloc[0]

        gdf_metric.geometry = gdf_metric.geometry.scale(
            xfact=x_factor, yfact=y_factor, origin=(center.x, center.y))
        gdf = gdf_metric.to_crs("EPSG:4326")

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
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
    """根据坐标创建点/线/面几何图层并加载到地图。
    - geometry_type: Point / LineString / Polygon / Rectangle / Circle。
    - coordinates: Point("lon,lat")；LineString("lon1,lat1;lon2,lat2;...")；Polygon("lon1,lat1;...;lon1,lat1"闭合)；
      Rectangle("lon1,lat1;lon2,lat2"对角线)；Circle("lon,lat;radius_m"圆心+半径米)。
    - layer_name: 自定义图层名（空则自动命名）。"""
    try:
        import geopandas as gpd
        from shapely.geometry import Point, LineString, Polygon
        import json, re, math

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
                x, y = float(xy[0]), float(xy[1])
                if not math.isfinite(x) or not math.isfinite(y):
                    return None
                if not (-180 <= x <= 180 and -90 <= y <= 90):
                    return None
                return (x, y)
            except (ValueError, TypeError, OverflowError):
                return None

        pts = [parse_xy(p) for p in parts]
        pts = [p for p in pts if p is not None]

        if gt == "Point":
            if not pts:
                return "无法解析坐标，请使用「lon,lat」格式（经度 -180~180，纬度 -90~90）"
            geom = Point(pts[0])
            node_count = 1
        elif gt == "LineString":
            if len(pts) < 2:
                return "无法解析坐标，LineString 至少需要 2 个有效点"
            geom = LineString(pts)
            node_count = len(pts)
        elif gt == "Polygon":
            if len(pts) < 3:
                return "无法解析坐标，Polygon 至少需要 3 个有效点"
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            geom = Polygon(pts)
            node_count = len(pts)
        elif gt == "Rectangle":
            if len(pts) != 2:
                return "Rectangle 需要 2 个有效坐标（对角线）：lon1,lat1;lon2,lat2"
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)
            if minx == maxx or miny == maxy:
                return "Rectangle 对角线两点不能在同一经度或同一纬度上"
            geom = Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)])
            node_count = 4
        else:  # Circle
            if len(pts) < 1 or len(parts) < 2:
                return "Circle 需要圆心坐标和半径：lon,lat;radius_m"
            try:
                radius = float(parts[1])
            except (ValueError, TypeError, OverflowError):
                return "Circle 半径必须是有限数值"
            if not math.isfinite(radius) or radius <= 0:
                return "Circle 半径必须大于 0"
            if radius > 50_000_000:
                return "Circle 半径超出合理地理范围"
            lon, lat = pts[0]
            if lat < -80 or lat > 84:
                return "Circle 圆心纬度必须在 UTM 投影适用范围（80°S 至 84°N）内"
            center_pt = Point(pts[0])
            crs_utm = _get_utm_crs(lon, lat)
            center_gdf = gpd.GeoDataFrame({"geometry": [center_pt]}, crs="EPSG:4326")
            center_utm = center_gdf.to_crs(crs_utm)
            circle_utm = center_utm.geometry.buffer(radius)
            circle_gdf = gpd.GeoDataFrame({"geometry": circle_utm}, crs=crs_utm).to_crs("EPSG:4326")
            geom = circle_gdf.geometry.iloc[0]
            node_count = len(geom.exterior.coords) if hasattr(geom, 'exterior') else 0

        base_name = layer_name.strip() or f"绘制_{gt}_{len(_registered_layers) + 1}"
        with _state_lock:
            name = _disambiguate_layer_name(base_name)
            gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")
            provenance = {"tool": "draw_feature", "geometry_type": gt}
            _gdf_to_layer(gdf, name, provenance=provenance)
        pts_str = f"，含 {node_count} 个节点" if node_count else ""
        return f"已创建{gt}图层「{name}」，含 1 个要素{pts_str}，已加载到地图"
    except Exception as e:
        return f"绘制失败: {str(e)[:300]}"


# Re-exported from backend.services.tool_modules.vector: spatial_intersect .. spatial_field_stats (14 tools)

# ============================================================
# 工具: reverse_geocode — 反向地理编码
# ============================================================

@tool
def reverse_geocode(lng: float, lat: float) -> str:
    """将 WGS-84 坐标转为地址描述（反向地理编码）。"""
    try:
        lng, lat = float(lng), float(lat)
    except (TypeError, ValueError, OverflowError):
        return "坐标无效：经度和纬度必须是 WGS-84 数值。"
    if (not math.isfinite(lng) or not math.isfinite(lat)
            or not -180 <= lng <= 180 or not -90 <= lat <= 90):
        return "坐标无效：经度须在 -180 到 180 之间，纬度须在 -90 到 90 之间。"
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
        # requests 异常可能包含完整查询 URL，其中带有 API Key。
        return f"反向地理编码失败: {type(e).__name__}"


# ============================================================
# 工具: batch_geocode — 批量地理编码
# ============================================================

@tool
def batch_geocode(addresses: str) -> str:
    """批量将地名转为 WGS-84 坐标。addresses 用逗号或分号分隔，单次最多 20 个。"""
    if not _current_amap_key:
        return "高德 API Key 未配置"
    import requests
    from backend.services.geo_coords import gcj02_to_wgs84
    import re
    sep = ";" if ";" in addresses else ","
    parts = [a.strip() for a in addresses.split(sep) if a.strip()]
    if not parts:
        return "请输入至少一个地址"
    if len(parts) > 20:
        return f"单次最多查询 20 个地址，当前有 {len(parts)} 个；请拆分后重试。"
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
            # requests 异常可能包含完整查询 URL，其中带有 API Key。
            results.append(f"  ❌ {addr}：请求失败（{type(e).__name__}）")
    return f"批量地理编码结果（{len(results)}/{len(parts)}）：\n" + "\n".join(results)


# Re-exported from backend.services.tool_modules.vector: spatial_join, layer_merge, layer_split, layer_add_geometry


# ============================================================
# 工具: add_labels — 属性标注
# ============================================================

@tool
def add_labels(layer_name: str, field: str, font_size: int = 12, color: str = "#333333") -> str:
    """对图层添加属性标注，每个要素上显示指定字段的文本标签，类似于 ArcGIS 的"标注要素"功能。
    layer_name: 图层名；field: 用于标注的字段名；font_size: 字体大小（6-72，默认12）；color: CSS 字体颜色（默认"#333333"）。"""
    try:
        import math
        try:
            requested_size = float(font_size)
        except (TypeError, ValueError, OverflowError):
            return "标注失败：font_size 必须是 6 到 72 之间的整数"
        if not math.isfinite(requested_size) or not requested_size.is_integer() or not 6 <= requested_size <= 72:
            return "标注失败：font_size 必须是 6 到 72 之间的整数"
        font_size = int(requested_size)
        if not isinstance(color, str) or not color.strip() or len(color) > 64:
            return "标注失败：color 必须是非空 CSS 颜色值"
        color = color.strip()
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"错误：图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

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
def spatial_graduated_colors(layer_name: str, field: str, n_classes: int = 5, color_scheme: str = "blues",
                            method: str = "equal_interval", fill_opacity: float = 0.35) -> str:
    """对图层应用分级色彩渲染（Choropleth），按数值字段将要素分为N个等级，每级用不同颜色显示。
    注意：要求图层包含至少2个要素且数值存在差异。如果是单要素图层（如单个行政区边界），无法分级，请使用 datav_boundary 默认边界在地图展示，并结合指标面板或图表交付。
    layer_name: 图层名；field: 数值字段名；n_classes: 分级数（2-20，默认5）；
    color_scheme: 色带 ylorrd(黄橙红/暖色)/blues(蓝)/reds(红)/greens(绿)/oranges(橙)/purples(紫)/ylgnbu(黄绿蓝)/spectral(光谱)；
    method: 分级方法 equal_interval(等间距，默认) 或 quantile(分位数)；fill_opacity: 面填充透明度（0-1，默认0.35）。"""
    try:
        import geopandas as gpd
        import numpy as np
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        if gdf[field].dtype.kind not in ('i', 'u', 'f'):
            return f"字段「{field}」不是数值类型（{gdf[field].dtype}），分级色彩仅支持数值字段"

        n_classes = max(2, min(20, n_classes if n_classes else 5))
        values = gdf[field].dropna()
        values = values[np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))]
        if values.empty:
            return f"字段「{field}」无有效数值"

        vmin, vmax = float(values.min()), float(values.max())
        if vmin == vmax:
            return f"字段「{field}」所有值相同（{vmin}）或仅有单个要素，无法进行分级设色。单行政区要素已在地图上展示，建议结合指标面板或统计图表交付专题成果。"

        method_names = {
            "equal_interval": "equal_interval", "equal interval": "equal_interval", "等间距": "equal_interval",
            "quantile": "quantile", "分位数": "quantile", "quantiles": "quantile",
        }
        method = method_names.get(str(method or "").strip().lower(), "")
        if not method:
            return "不支持该分级方法，可选：equal_interval（等间距）或 quantile（分位数）"
        n_classes = min(n_classes, int(values.nunique()))
        if n_classes < 2:
            return f"字段「{field}」的不同数值不足，无法分级设色"
        if method == "quantile":
            quantiles = values.quantile([i / n_classes for i in range(n_classes + 1)]).tolist()
            breaks = [float(v) for v in quantiles]
            # 重复值可能使部分等级边界相同；保留真实断点并减少重复等级。
            breaks = sorted(set(breaks))
            if len(breaks) < 3:
                return f"字段「{field}」的数值分布无法形成至少两个分位数等级"
            n_classes = len(breaks) - 1
        else:
            step = (vmax - vmin) / n_classes
            breaks = [vmin + i * step for i in range(n_classes + 1)]
        # Floating-point step accumulation can leave the final break a few
        # ulps below vmax, causing the browser to assign the maximum to no class.
        breaks[0], breaks[-1] = vmin, vmax
        try:
            fill_opacity = max(0.0, min(1.0, float(fill_opacity)))
        except (TypeError, ValueError):
            return "面填充透明度必须是 0 到 1 之间的数值"

        cs_norm = str(color_scheme or "").strip().lower()
        _scheme_map = {
            "ylorrd": "ylorrd", "yellow_orange_red": "ylorrd", "warm": "ylorrd",
            "黄橙红": "ylorrd", "黄到橙到红": "ylorrd", "黄红": "ylorrd", "暖色": "ylorrd",
            "blues": "blues", "蓝": "blues", "蓝色": "blues",
            "reds": "reds", "红": "reds", "红色": "reds",
            "greens": "greens", "绿": "greens", "绿色": "greens",
            "oranges": "oranges", "橙": "oranges", "橙色": "oranges",
            "purples": "purples", "紫": "purples", "紫色": "purples",
            "ylgnbu": "ylgnbu", "黄绿蓝": "ylgnbu",
            "spectral": "spectral", "彩虹": "spectral", "光谱": "spectral",
            "viridis": "viridis", "翠绿": "viridis",
            "scheme": "scheme"
        }
        color_scheme = _scheme_map.get(cs_norm, "blues")

        _pending_layer_ops.append({
            "action": "symbology",
            "name": name,
            "symbology_type": "graduated",
            "field": field,
            "classes": n_classes,
            "scheme": color_scheme,
            "method": method,
            "breaks": breaks,
            "fill_opacity": fill_opacity,
        })

        breaks_str = ", ".join(f"{b:.2f}" for b in breaks)
        method_label = "等间距" if method == "equal_interval" else "分位数"
        return (f"已对「{name}」应用分级色彩渲染，字段：{field}，{n_classes} 级，"
                f"方法：{method_label}，色带：{color_scheme}，填充透明度：{fill_opacity:.2f}，值域：{vmin:.2f} ~ {vmax:.2f}\n"
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
        import numpy as np
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        if field not in gdf.columns:
            return f"图层「{name}」没有字段「{field}」，可用字段：{', '.join(gdf.columns)}"

        unique_vals = []
        seen_values = set()
        for value in gdf[field].dropna().tolist():
            if isinstance(value, (bool, np.bool_)):
                key = ("boolean", bool(value))
            elif isinstance(value, (int, float, np.number)):
                key = ("number", value.item() if isinstance(value, np.generic) else value)
            else:
                key = (type(value).__name__, value)
            if key not in seen_values:
                seen_values.add(key)
                unique_vals.append(value)
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

        display_values = []
        display_counts = {}
        for value in unique_vals:
            if isinstance(value, (bool, np.bool_)):
                label, value_type = str(value).lower(), "boolean"
            elif isinstance(value, (int, float, np.number)):
                number = value.item() if isinstance(value, np.generic) else value
                label = str(int(number)) if isinstance(number, float) and number.is_integer() else str(number)
                value_type = "number"
            else:
                label, value_type = str(value), "string"
            display_values.append((label, value_type))
            display_counts[label] = display_counts.get(label, 0) + 1
        vals_str = ", ".join(
            f"{label} ({value_type})" if display_counts[label] > 1 else label
            for label, value_type in display_values[:20]
        )
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
    """更新图层要素的属性值。不指定条件则更新所有要素；只改一条要素时优先用 condition_field="_fid" 和 get_layer_detail 返回的稳定 ID。
    支持数值和文本字段。更新后地图自动同步。
    layer_name: 必须为注册图层完整名称；field: 要更新的字段名；value: 新值（自动转换类型）；
    condition_field: 条件字段名（可选）；condition_value: 条件字段值（可选，仅更新匹配要素）。"""
    try:
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        import copy
        import geopandas as gpd

        features = info["geojson"]["features"]
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field not in gdf.columns:
            return f"图层「{layer_name}」没有字段「{field}」，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"
        if field == "_fid":
            return "_fid 是要素稳定标识，不能修改"

        def property_kind(values, fallback):
            present = [item for item in values if item is not None]
            if not present:
                return fallback
            if all(isinstance(item, bool) for item in present):
                return "b"
            if all(isinstance(item, int) and not isinstance(item, bool) for item in present):
                return "i"
            if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in present):
                return "f"
            return "O"

        raw_field_values = [
            (feature.get("properties") or {}).get(field) for feature in features
        ]
        # Convert against source values so mixed nulls do not make large integer
        # properties appear to be floating point.
        dtype_kind = property_kind(raw_field_values, gdf[field].dtype.kind)
        try:
            if dtype_kind in ('i', 'u'):
                typed_value = int(value)
            elif dtype_kind == 'f':
                typed_value = float(value)
            elif dtype_kind == 'b':
                normalized = str(value).strip().casefold()
                if normalized not in ("true", "false"):
                    return f"字段「{field}」为布尔类型，请使用 true 或 false"
                typed_value = normalized == "true"
            else:
                typed_value = str(value)
        except ValueError:
            return f"字段「{field}」类型为 {gdf[field].dtype}，但值「{value}」无法转换"
        if dtype_kind == "f" and not math.isfinite(typed_value):
            return f"字段「{field}」只接受有限浮点数"

        # 筛选要更新的行
        if condition_field:
            if condition_field not in gdf.columns:
                return f"条件字段「{condition_field}」不存在"
            raw_condition_values = [
                (feature.get("properties") or {}).get(condition_field) for feature in features
            ]
            cond_kind = property_kind(raw_condition_values, gdf[condition_field].dtype.kind)
            try:
                if cond_kind in ('i', 'u', 'f'):
                    cond_value = _parse_numeric_condition(condition_value, cond_kind)
                elif cond_kind == 'b':
                    normalized = str(condition_value).strip().casefold()
                    cond_value = normalized == "true" if normalized in ("true", "false") else condition_value
                else:
                    cond_value = str(condition_value)
            except ValueError:
                cond_value = str(condition_value)

            matches_mask = [item == cond_value for item in raw_condition_values]
            match_count = sum(matches_mask)
            if match_count == 0:
                return f"没有要素满足条件（{condition_field} = {condition_value}）"
            target_indices = [index for index, matched in enumerate(matches_mask) if matched]
            affected_geojson = copy.deepcopy(info["geojson"])
            for index in target_indices:
                properties = affected_geojson["features"][index].get("properties")
                if not isinstance(properties, dict):
                    properties = {}
                    affected_geojson["features"][index]["properties"] = properties
                properties[field] = typed_value
            affected = match_count
        else:
            affected_geojson = copy.deepcopy(info["geojson"])
            for feature in affected_geojson["features"]:
                properties = feature.get("properties")
                if not isinstance(properties, dict):
                    properties = {}
                    feature["properties"] = properties
                properties[field] = typed_value
            affected = len(gdf)

        geojson_data = affected_geojson
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
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
    condition_value: 要匹配的字段值（可为空字符串，例如删除空值记录）；用 condition_field="_fid" 可精准删除单条要素。"""
    try:
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        if not condition_field:
            return "请指定删除条件（condition_field 和 condition_value），例如删除 name=xx 的所有要素"

        import copy
        import geopandas as gpd

        features = info["geojson"]["features"]
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if condition_field not in gdf.columns:
            return f"条件字段「{condition_field}」不存在，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

        raw_values = [
            (feature.get("properties") or {}).get(condition_field)
            for feature in features
        ]
        non_null_values = [value for value in raw_values if value is not None]
        if non_null_values and all(isinstance(value, bool) for value in non_null_values):
            cond_kind = "b"
        elif non_null_values and all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in non_null_values
        ):
            cond_kind = "i"
        elif non_null_values and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in non_null_values
        ):
            cond_kind = "f"
        else:
            cond_kind = "O"
        try:
            if cond_kind in ('i', 'u', 'f'):
                cond_val = _parse_numeric_condition(condition_value, cond_kind)
            elif cond_kind == 'b':
                normalized = str(condition_value).strip().casefold()
                cond_val = normalized == "true" if normalized in ("true", "false") else condition_value
            else:
                cond_val = str(condition_value)
        except ValueError:
            cond_val = str(condition_value)

        mask = [value == cond_val for value in raw_values]
        to_delete = sum(mask)
        if to_delete == 0:
            return f"没有要素满足条件（{condition_field} = {condition_value}）"

        remaining_indices = [index for index, matched in enumerate(mask) if not matched]
        if not remaining_indices:
            return f"条件（{condition_field} = {condition_value}）将删除全部 {to_delete} 个要素，操作已取消"

        geojson_data = copy.deepcopy(info["geojson"])
        geojson_data["features"] = [copy.deepcopy(features[index]) for index in remaining_indices]
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        return (f"已从图层「{layer_name}」删除 {to_delete}/{len(gdf)} 个要素"
                f"（条件：{condition_field} = {condition_value}），剩余 {len(remaining_indices)} 个，已同步地图")
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
        import pandas as pd

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if not isinstance(field_name, str) or not field_name.strip():
            return "字段名不能为空"
        field_name = field_name.strip()
        if field_name in ("geometry", "_fid"):
            return f"字段名「{field_name}」为保留字段，不能新增"
        if field_name in gdf.columns:
            return f"字段「{field_name}」已存在"

        field_type = field_type.lower().strip()
        if field_type not in ("str", "string", "text", "int", "integer", "float", "double", "number"):
            return f"不支持字段类型「{field_type}」，请选择 str、int 或 float"
        if field_type in ("string", "text"):
            field_type = "str"
        elif field_type in ("integer",):
            field_type = "int"
        elif field_type in ("double", "number"):
            field_type = "float"

        parsed_default = None
        if default_value != "":
            try:
                parsed_default = int(default_value) if field_type == "int" else float(default_value) if field_type == "float" else str(default_value)
            except (TypeError, ValueError):
                return f"默认值「{default_value}」无法转换为字段类型 {field_type}"
            if field_type == "float" and not math.isfinite(parsed_default):
                return "浮点字段默认值必须是有限数值"
        if field_type == "int":
            gdf[field_name] = parsed_default if parsed_default is not None else pd.Series([None] * len(gdf), dtype="object")
        elif field_type == "float":
            gdf[field_name] = parsed_default if parsed_default is not None else pd.Series([None] * len(gdf), dtype="object")
        else:
            gdf[field_name] = parsed_default if parsed_default is not None else None

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        return (f"已为图层「{layer_name}」添加字段「{field_name}」（类型：{field_type}"
                + (f"，默认值：{default_value}" if default_value != "" else "")
                + "），已同步地图")

    except Exception as e:
        return f"添加字段失败: {str(e)[:300]}"


@tool
def delete_field(layer_name: str, field_name: str) -> str:
    """删除图层的指定字段。字段删除后数据不可恢复。layer_name: 图层名；field_name: 要删除的字段名。"""
    try:
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = _geojson_to_export_gdf(info["geojson"])
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field_name not in gdf.columns:
            return f"错误：字段「{field_name}」不存在，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

        if field_name == "geometry":
            return "不能删除 geometry 字段"
        if field_name == "_fid":
            return "_fid 是要素稳定标识，不能删除"

        gdf = gdf.drop(columns=[field_name])

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
        _push_layer(layer_name, geojson_data)

        return f"已从图层「{layer_name}」删除字段「{field_name}」，已同步地图"

    except Exception as e:
        return f"删除字段失败: {str(e)[:300]}"


# Re-exported from backend.services.tool_modules.vector: spatial_select_by_attribute


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
    format = str(format or "png").strip().lower().lstrip(".")
    if format == "jpeg":
        format = "jpg"
    if format not in {"png", "jpg"}:
        return f"不支持的图片格式：{format}，仅支持 png/jpg"
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
def export_pdf(title: str = "地图导出", rotation_degrees: float = 0) -> str:
    """将当前地图导出为 PDF 文档（打印布局），包含地图、标题、比例尺、图例、经纬度和指北针。
    title: 文档标题（默认"地图导出"）。
    rotation_degrees: 地图顺时针旋转角度（度），北针随地图旋转；默认 0。"""
    try:
        _pending_layer_ops.append({
            "action": "export_pdf",
            "title": title,
            "rotation_degrees": rotation_degrees,
        })
        return f"已触发 PDF 出图，标题：{title}，旋转：{rotation_degrees}°"
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


# Re-exported from backend.services.tool_modules: dem_analysis, ndvi_analysis, raster_calculator, spatial_interpolate, hydrology_analysis


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
            return "工作流执行失败：workflow_json 必须是非空数组"
        outputs = {}
        results = []
        # 构建工具查找表
        tool_map = {}
        for t in tools:
            name = t.name if hasattr(t, 'name') else str(t)
            tool_map[name] = t
        for idx, step in enumerate(steps):
            step_num = idx + 1
            if not isinstance(step, dict):
                return f"工作流执行失败：第{step_num}步必须是对象"
            tool_name = step.get("tool", "")
            raw_params = step.get("params", {})
            if not isinstance(raw_params, dict):
                return f"工作流执行失败：第{step_num}步 params 必须是对象"
            output_name = step.get("output", f"step_{step_num}")
            if not isinstance(output_name, str) or not output_name.strip():
                return f"工作流执行失败：第{step_num}步 output 必须是非空字符串"
            if not isinstance(tool_name, str) or tool_name not in tool_map:
                return f"工作流执行失败：第{step_num}步未找到工具 '{tool_name}'"
            # 解析 $prev / $N 引用
            resolved_params = {}
            for k, v in raw_params.items():
                if isinstance(v, str) and v.startswith("$"):
                    ref = v[1:]
                    if ref == "prev":
                        if not outputs:
                            return f"工作流执行失败：第{step_num}步参数 {k} 引用了不存在的上一步输出"
                        prev_out = list(outputs.values())[-1]
                        resolved_params[k] = prev_out
                    elif ref.isdigit():
                        n = int(ref)
                        if n in outputs:
                            resolved_params[k] = outputs[n]
                        else:
                            return f"工作流执行失败：第{step_num}步参数 {k} 引用了不存在的第 {n} 步输出"
                    else:
                        return f"工作流执行失败：第{step_num}步参数 {k} 的输出引用格式无效：{v}"
                else:
                    resolved_params[k] = v
            try:
                tool_fn = tool_map[tool_name]
                step_result = tool_fn.invoke(resolved_params)
            except Exception as e:
                return f"工作流执行失败：第{step_num}步 '{tool_name}' 执行失败: {str(e)[:200]}"
            if _tool_result_failed(tool_name, step_result):
                return f"工作流执行失败：第{step_num}步 '{tool_name}' 执行失败: {str(step_result)[:200]}"
            step_output = output_name
            outputs[step_num] = step_output
            outputs[output_name] = step_output
            results.append(f"步骤{step_num}({tool_name}) → {output_name}: {str(step_result)[:100]}")
        return "工作流执行完成:\n" + "\n".join(results)
    except Exception as e:
        return f"工作流执行失败: {str(e)[:300]}"


# Re-exported from backend.services.tool_modules.terrain: view_3d_terrain


# ============================================================
# 工具: animate_time — 时序动画
# ============================================================

@tool
def animate_time(layer_name: str, time_field: str, interval_ms: int = 500) -> str:
    """对图层的时序字段进行动画播放。time_field为日期/数字字段，
    interval_ms为每帧间隔（毫秒，默认500）。前端会按时间顺序逐帧显示。"""
    try:
        import pandas as pd
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if time_field not in gdf.columns:
            return f"图层 '{name}' 没有字段 '{time_field}'"
        field_data = gdf[time_field]
        time_vals = list(field_data.dropna().unique())
        if len(time_vals) < 2:
            return f"字段 '{time_field}' 只有 {len(time_vals)} 个唯一值，至少需要2个"
        if field_data.dtype.kind in ("i", "u", "f"):
            time_vals = sorted(time_vals)
        else:
            try:
                parsed_times = pd.to_datetime(time_vals, utc=True, errors="raise")
            except (TypeError, ValueError, OverflowError):
                return f"字段 '{time_field}' 必须是数值或可解析的日期时间"
            time_vals = [value for _, value in sorted(zip(parsed_times, time_vals), key=lambda pair: pair[0])]
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


# Re-exported from backend.services.tool_modules: terrain_profile, topology_check, extract_contours


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
    """转换矢量图层的坐标参考系并生成新图层（原图层保留）。
    - layer_name: 待转换图层名。
    - target_crs: 目标坐标系，可选 'wgs84'(EPSG:4326)、'web_mercator'(EPSG:3857)、'utm_auto'(自动UTM投影带) 或 'EPSG:xxxx'。进行长度/面积精确度量前需转为投影坐标系。"""
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
        target_key = target_crs.strip().lower()
        target = epsg_map.get(target_key, target_crs.strip())
        if target_key in ("utm_auto", "utm"):
            extent_error = _local_utm_extent_error(gdf.total_bounds)
            if extent_error:
                return f"坐标系转换失败: {extent_error}"
            bounds = gdf.total_bounds
            center_lon = (bounds[0] + bounds[2]) / 2
            center_lat = (bounds[1] + bounds[3]) / 2
            target = _get_utm_crs(center_lon, center_lat)
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
        import math
        import pyproj

        def _resolve_crs(name: str) -> str:
            """CRS 别名 → EPSG；源 UTM 必须提供明确分带。"""
            n = str(name).lower().strip()
            m = {"wgs84": "EPSG:4326", "mercator": "EPSG:3857",
                 "web_mercator": "EPSG:3857", "gcj02": "EPSG:4326"}
            if n in m:
                return m[n]
            if n in ("utm_auto", "utm"):
                raise ValueError("源坐标为 UTM 时需指定 EPSG 分带（例如 EPSG:32719），不能使用 utm_auto")
            return str(name).strip()

        parts_raw = str(coords or "").replace("，", ",").replace("；", ";").split(";")
        parsed = []
        for part in parts_raw:
            xy = part.strip().split(",")
            if len(xy) != 2:
                raise ValueError("坐标格式错误，请输入 lng,lat 或 lng1,lat1;lng2,lat2")
            try:
                x, y = float(xy[0].strip()), float(xy[1].strip())
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("坐标格式错误，请输入有效数字坐标") from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("坐标必须是有限数值")
            parsed.append((x, y))

        p1 = _resolve_crs(source_crs)
        source_definition = pyproj.CRS.from_user_input(p1)
        if source_definition.is_geographic and any(
            not -180 <= x <= 180 or not -90 <= y <= 90 for x, y in parsed
        ):
            raise ValueError("源坐标超出有效经纬度范围（经度 -180°–180°，纬度 -90°–90°）")
        target_key = str(target_crs).lower().strip()
        if target_key in ("utm_auto", "utm"):
            to_wgs84 = pyproj.Transformer.from_crs(p1, "EPSG:4326", always_xy=True)
            geographic = [to_wgs84.transform(x, y, errcheck=True) for x, y in parsed]
            if any(not math.isfinite(lon) or not math.isfinite(lat)
                   or not -180 <= lon <= 180 or not -90 <= lat <= 90
                   for lon, lat in geographic):
                raise ValueError("坐标转换后超出 WGS84 经纬度有效范围")
            bounds = (
                min(point[0] for point in geographic), min(point[1] for point in geographic),
                max(point[0] for point in geographic), max(point[1] for point in geographic),
            )
            extent_error = _local_utm_extent_error(bounds)
            if extent_error:
                raise ValueError(extent_error)
            center_lon = (bounds[0] + bounds[2]) / 2
            center_lat = (bounds[1] + bounds[3]) / 2
            p2 = _get_utm_crs(center_lon, center_lat)
        else:
            p2 = _resolve_crs(target_crs)
        if p1 == p2:
            return f"源和目标CRS相同: {source_crs} = {target_crs}, 无需转换"
        transformer = pyproj.Transformer.from_crs(p1, p2, always_xy=True)
        target_is_geographic = pyproj.CRS.from_user_input(p2).is_geographic
        results = []
        for x, y in parsed:
            x2, y2 = transformer.transform(x, y, errcheck=True)
            if not math.isfinite(x2) or not math.isfinite(y2):
                raise ValueError("转换结果包含非有限坐标")
            if target_is_geographic and (not -180 <= x2 <= 180 or not -90 <= y2 <= 90):
                raise ValueError("目标经纬度超出有效范围")
            results.append(f"{x2:.6f},{y2:.6f}")
        return f"{source_crs}→{target_crs}: {'; '.join(results)}"
    except Exception as e:
        return f"坐标转换失败: {str(e)[:200]}"


# Re-exported from backend.services.tool_modules.raster: clip_raster


# ============================================================
# 工具: discover_gis_data / download_gis_data — GIS 开放数据发现与获取
# （数据 Provider 抽象见 backend/services/data_providers；此处只做调度）
# ============================================================

def _format_discover_hits(hits: list) -> str:
    """把发现结果格式化为 Markdown 表格，并展示用于一键下载的数据句柄 (Handle)。"""
    if not hits:
        return "（无命中）"
    lines = [
        "| 句柄 (Handle) | 数据源 | 类型 | 区域 | 格式 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for h in hits:
        status = "可获取"
        if not h.get("downloadable"):
            status = "需认证" + (f"：{str(h.get('note'))[:40]}" if h.get('note') else "")
        handle_code = f"`{h.get('handle', '-')}`"
        lines.append(
            f"| {handle_code} | {h.get('provider', '-')} | {h.get('kind_label', '-')} "
            f"| {h.get('area', '-')} | {h.get('file_format', '-')} | {status} |"
        )
    return "\n".join(lines)


@tool
def discover_gis_data(query: str = "", kind: str = "", area: str = "",
                      bbox: str = "", provider: str = "auto",
                      file_format: str = "", time_start: str = "",
                      time_end: str = "") -> str:
    """检索开放 GIS 数据源元信息（OSM/Copernicus/USGS/地理空间数据云，返回句柄不下载）。
    - kind: 数据类型（roads/buildings/pois/waterways/landuse/transport/imagery/dem）。
    - area: 城市/区域名（如'长沙市'）或 bbox='minLng,minLat,maxLng,maxLat'。
    - provider: osm/copernicus/usgs/gscloud，默认 auto。可自动获取的结果会返回 handle 供 download_gis_data 使用。"""
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
    first_handle = next((hit.get("handle") for hit in r["hits"] if hit.get("handle")), "")
    if first_handle:
        parts.append(
            f"\n下一步：确认后直接调用 **download_gis_data(handle='{first_handle}')** 即可一键获取并加载到地图（免重复传参）。"
        )
    elif r["hits"]:
        parts.append("\n以上结果仅提供数据源指引，当前没有可自动获取的候选。")
    return "\n".join(parts)


@tool
def download_gis_data(handle: str = "", query: str = "", kind: str = "", area: str = "",
                      bbox: str = "", provider: str = "", file_format: str = "",
                      time_start: str = "", time_end: str = "",
                      layer_name: str = "", max_items: int = 0) -> str:
    """从开放源下载 GIS 数据并自动加载到地图（OSM/Copernicus/USGS/GSCloud）。
    - handle: 前置 discover_gis_data 返回的句柄（优先传此参数，自动还原所有筛选）。
    - kind: roads/buildings/pois/waterways/landuse/transport 等；area: 城市名或 bbox。
    - file_format: geojson(默认)/gpkg/shp；使用 handle 时默认沿用发现结果格式。
    - layer_name: 自定义图层名称。"""
    from backend.services import data_discovery
    try:
        asset = data_discovery.download(
            handle=handle, query=query, kind=kind, area=area, bbox=bbox,
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
    meta = asset.get("metadata", {})
    if geojson is not None:
        layer = asset["layer_name"]
        provenance = _normalize_layer_provenance({
            "provider": asset.get("provider"),
            "provider_name": asset.get("provider_name"),
            "kind": asset.get("kind"),
            "kind_label": asset.get("kind_label"),
            "file_format": asset.get("file_format"),
            "crs": asset.get("crs"),
            "crs_known": asset.get("crs_known"),
            "source_url": meta.get("source_url") if isinstance(meta, dict) else None,
        })
        _push_layer(layer, geojson, provenance=provenance)
        _register_layer(layer, geojson, provenance=provenance)
        loaded = f"已加载到地图，图层名「{layer}」。"
    else:
        loaded = ""

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
def search_gis_services(query: str = "", country: str = "",
                        protocol: str = "", category: str = "",
                        limit: int = 10) -> str:
    """检索全球真实可用的 GIS 空间服务与公开端点（WMS/WFS/WMTS/XYZ/ArcGIS REST/STAC）。
    - query: 关键词（如 'DEM', '高程', 'satellite', '土地利用', '气象', '交通'）。
    - country: 地区筛选（如 '中国', '全球'）；protocol: 协议（WMS/WFS/XYZ/REST 等）。
    - category: 分类（高程/地形、交通、气象、土地利用等）；limit: 最大条数(默认 10，上限 30)。"""
    from backend.services import geosource_service as _gs
    res = _gs.search_services(
        keyword=query or None,
        country=country or None,
        protocol=protocol or None,
        category=category or None,
        limit=min(max(1, limit), 30),
    )
    results = res.get("results", [])
    if not results:
        return f"未找到匹配的 GIS 服务（query='{query}', country='{country}', protocol='{protocol}'）。可尝试更通用的关键词或减少过滤条件重试。"

    lines = [f"找到 {len(results)} 个匹配的全球 GIS 空间服务：\n"]
    for i, s in enumerate(results, 1):
        sid = s.get("service_id", "")
        name = s.get("service_name", "")
        proto = s.get("protocol", "未知")
        cntry = s.get("country", "")
        cat = s.get("category", "")
        free = "免费" if s.get("is_free") == "是" else "可能收费/受限"
        no_key = "免Key" if s.get("need_no_key") == "是" else "需Key"
        url = s.get("service_url", "")
        desc = (s.get("data_description") or "")[:80]
        lines.append(f"{i}. [{sid}] {name}")
        lines.append(f"   - 协议: {proto} | 地区: {cntry} | 分类: {cat} | {free} | {no_key}")
        if url:
            lines.append(f"   - 服务端点: {url}")
        if desc:
            lines.append(f"   - 说明: {desc}")
    lines.append("\n可使用 get_gis_service_detail(service_id='...') 查看具体图层清单与详细元数据。")
    return "\n".join(lines)


@tool
def get_gis_service_detail(service_id: str = "") -> str:
    """获取指定 GIS 空间服务的完整元数据与包含的子图层列表。
参数说明：
- service_id: 服务唯一标识符（如 'WMS-0001', 'DS-0001', 'AM-0001' 等）。
用法：在 search_gis_services 找到感兴趣的服务后，调用本工具查看该服务详细的图层名清单、投影坐标系(CRS)、访问限制与在线端点 URL。"""
    sid = (service_id or "").strip()
    if not sid:
        return "请提供要查询的 service_id（如 'WMS-0001'）。"
    from backend.services import geosource_service as _gs
    detail = _gs.get_service_detail(sid)
    if "error" in detail:
        return f"查询失败: {detail['error']}"

    name = detail.get("service_name", "")
    proto = detail.get("protocol", "")
    url = detail.get("service_url", "")
    off_url = detail.get("official_url", "")
    docs = detail.get("docs_url", "")
    desc = detail.get("data_description", "")
    crs = detail.get("crs", "")
    cov = detail.get("spatial_coverage", "")
    fmt = detail.get("format", "")
    layers = detail.get("layers", [])

    lines = [
        f"【GIS 服务详情】{name} (ID: {sid})",
        f"- 协议: {proto} | 格式: {fmt or '默认'} | 投影坐标系: {crs or '未指定'}",
        f"- 服务端点: {url or '无'}",
    ]
    if off_url:
        lines.append(f"- 官方网站: {off_url}")
    if docs:
        lines.append(f"- 接口文档: {docs}")
    if cov:
        lines.append(f"- 空间覆盖范围: {cov}")
    if desc:
        lines.append(f"- 数据描述: {desc}")
    if layers:
        lines.append(f"- 包含子图层（共 {len(layers)} 个）：")
        for lyr in layers[:15]:
            lines.append(f"    • [{lyr.get('layer_idx', '')}] {lyr.get('layer_name', '')}")
        if len(layers) > 15:
            lines.append(f"    ... 等共 {len(layers)} 个图层")
    else:
        lines.append("- 子图层: 暂无单独子图层记录，直接调用服务端点即可。")
    return "\n".join(lines)


@tool
def get_gis_services_stats() -> str:
    """获取本地内嵌的全球 GIS 服务知识库概况统计（总服务数、图层数、主要类别、协议与国家分布）。
用法：当用户询问知识库涵盖哪些服务、支持哪些国家/协议/分类时调用。"""
    from backend.services import geosource_service as _gs
    stats = _gs.list_categories_and_stats()
    top_cat = ", ".join(f"{c['category']}({c['count']})" for c in stats.get("top_categories", [])[:6])
    top_proto = ", ".join(f"{p['protocol']}({p['count']})" for p in stats.get("top_protocols", [])[:6])
    top_country = ", ".join(f"{k['country']}({k['count']})" for k in stats.get("top_countries", [])[:6])
    return (
        f"【全球 GIS 空间服务库统计（GeoSource 内嵌）】\n"
        f"- 空间服务总数: {stats.get('total_services', 0)} 个\n"
        f"- 包含图层总数: {stats.get('total_layers', 0)} 个\n"
        f"- 主流类别: {top_cat}\n"
        f"- 支持协议: {top_proto}\n"
        f"- 覆盖国家/地区: {top_country}"
    )


@tool
def hold_layer_for_confirm(name: str = "", geojson: str = "",
                           source: str = "", file_path: str = "",
                           summary: str = "") -> str:
    """将就绪图层数据挂起登记，等待用户在会话中确认后确定性加载到地图。
    - name: 图层名（必填；已注册图层可直接复用）。
    - geojson: 图层 GeoJSON 字符串（新数据必填，已注册图层可省）。
    - source / file_path / summary: 数据来源、文件路径及一句话说明。"""
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


# ============================================================
# 工具: spatial_moran — Moran's I 空间自相关（全局 + 局部 LISA）
# ============================================================

_MAX_DENSE_SPATIAL_STATS_FEATURES = 3000


@tool
def spatial_moran(layer_name: str, field: str, weight_type: str = "distance",
                  threshold: float = 0.01, k: int = 5, local: bool = True,
                  threshold_m: float = 0.0) -> str:
    """全局 Moran's I 空间自相关 + 局部 LISA 聚类分析（仅支持点/质心数值字段）。
    - layer_name: 图层名（点要素或质心）。
    - field: 待分析的数值型属性字段。
    - weight_type: 'distance'(默认距离阈值) 或 'knn'(K近邻)。
    - threshold: 兼容旧调用的距离阈值（度）；threshold_m: 米制距离阈值（优先使用本地 UTM 投影计算）。
    - k: 近邻数(默认 5)。
    - local: 是否生成局部 LISA 聚类图层（包含 HH/LL/HL/LH 字段，默认 True）。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        if not field:
            numeric_fields = gdf.select_dtypes(include=[np.number]).columns.tolist()
            if not numeric_fields:
                return "图层没有可用于空间自相关分析的数值字段"
            field = numeric_fields[0]
        if field not in gdf.columns:
            return f"字段「{field}」不存在，可用字段：{', '.join(gdf.select_dtypes(include=[np.number]).columns.tolist()) or '无'}"
        x = gdf[field].values.astype(float)
        if np.isnan(x).any() or np.isinf(x).any():
            return "字段含空值或无穷大，请先清洗数据"
        n = len(x)
        if n < 3:
            return f"要素数（{n}）太少，至少需要 3 个"
        if n > _MAX_DENSE_SPATIAL_STATS_FEATURES:
            return f"错误：空间自相关当前最多支持 {_MAX_DENSE_SPATIAL_STATS_FEATURES} 个要素；请先聚合或抽样，避免距离矩阵耗尽内存"
        if weight_type not in ("distance", "knn"):
            return "weight_type 仅支持 distance 或 knn"
        distance_threshold = threshold
        if weight_type == "knn":
            if isinstance(k, bool) or not isinstance(k, int) or k < 1:
                return "K 近邻数必须是正整数"
            coords = _spatial_feature_coordinates(_to_local_metric_gdf(gdf))
        elif threshold_m:
            if not math.isfinite(float(threshold_m)) or float(threshold_m) <= 0:
                return "米制距离阈值必须是大于 0 的有限数值"
            metric_gdf = _to_local_metric_gdf(gdf)
            coords = _spatial_feature_coordinates(metric_gdf)
            distance_threshold = float(threshold_m)
        else:
            if not math.isfinite(float(threshold)) or float(threshold) <= 0:
                return "距离阈值必须是大于 0 的有限数值"
            distance_threshold = float(threshold)
            coords = _spatial_feature_coordinates(gdf)
        # 构建空间权重矩阵
        if weight_type == "knn":
            from sklearn.neighbors import NearestNeighbors
            k_eff = min(k, n - 1)
            nn = NearestNeighbors(n_neighbors=k_eff + 1).fit(coords)
            _, idx = nn.kneighbors(coords)
            W = np.zeros((n, n))
            for i in range(n):
                # Coincident points can tie ahead of the query itself.
                # Remove the actual index instead of assuming it is first.
                neighbors = idx[i][idx[i] != i][:k_eff]
                W[i, neighbors] = 1.0
        else:
            from scipy.spatial.distance import cdist
            d = cdist(coords, coords)
            W = (d <= distance_threshold).astype(float)
            np.fill_diagonal(W, 0.0)
        W_sum = W.sum()
        if W_sum == 0:
            return "空间权重全为零：没有任何点对在阈值内，请调大 threshold 或改用 weight_type=knn"
        # 全局 Moran's I
        z = x - x.mean()
        zz = z @ z
        if zz == 0:
            return "字段方差为零（所有值相同），无法计算空间自相关"
        I = (n / W_sum) * (z @ W @ z) / zz
        # 随机化假设下的期望与方差（Cliff & Ord）
        E_I = -1.0 / (n - 1)
        S0 = W_sum
        S1 = 0.5 * ((W + W.T) ** 2).sum()
        S2 = ((W.sum(axis=1) + W.sum(axis=0)) ** 2).sum()
        denom = (n - 1) * (n - 2) * (n - 3) * S0 * S0

        # 峰度项 b2 必须用离差 z = x - mean(x)，不是原始 x。
        # 方差主项还有一个 n 因子。这两处写错会让方差变成负数，
        # 再被 max(var, 1e-12) 兜住 → z 值爆炸 → 任何数据都判成"显著"。
        m2 = (z ** 2).mean()
        var_I = None
        if denom > 0 and n > 3 and m2 > 0:
            b2 = (z ** 4).mean() / (m2 ** 2)
            k1 = n * (S1 * (n*n - 3*n + 3) - n*S2 + 3*S0*S0) / denom
            k2 = (S1 * (n*n - n) - 2*n*S2 + 6*S0*S0) / denom
            _v = k1 - k2 * b2 - E_I * E_I
            if _v > 0:
                var_I = _v

        from scipy.stats import norm
        if var_I is not None:
            z_score = (I - E_I) / np.sqrt(var_I)
            p_value = 2.0 * (1.0 - norm.cdf(abs(z_score)))
            method = "正态近似（随机化假设）"
        else:
            # 方差算不出来时不做"假装显著"的兜底：改用置换检验
            # 固定种子保证同一份数据每次结论一致
            _rng = np.random.default_rng(20240915)
            _perm = []
            for _ in range(199):
                _xp = _rng.permutation(x)
                _zp = _xp - _xp.mean()
                _zz = _zp @ _zp
                if _zz > 0:
                    _perm.append((n / S0) * (_zp @ W @ _zp) / _zz)
            _perm = np.array(_perm)
            if _perm.size == 0 or _perm.std() == 0:
                z_score = 0.0
                p_value = 1.0
            else:
                z_score = (I - _perm.mean()) / _perm.std()
                p_value = (1 + int((np.abs(_perm - _perm.mean()) >= abs(I - _perm.mean())).sum())) / (_perm.size + 1)
            method = "置换检验（199 次，样本量过小或权重结构不满足正态近似）"
        if z_score > 1.96:
            pattern = "显著正空间自相关（属性值聚集分布）"
        elif z_score < -1.96:
            pattern = "显著负空间自相关（属性值离散/竞争分布）"
        else:
            pattern = "空间随机分布（无显著自相关）"
        summary = (f"全局 Moran's I = {I:.4f}，z = {z_score:.2f}，p = {p_value:.4f}。{pattern}"
                   f"（显著性判定方式：{method}）")
        # 局部 LISA
        if local:
            local_I = np.array([(z[i] / m2) * (W[i] @ z) for i in range(n)])
            lag_z = W @ z
            cluster = []
            for i in range(n):
                if z[i] > 0 and lag_z[i] > 0:
                    cluster.append("HH")
                elif z[i] > 0 and lag_z[i] < 0:
                    cluster.append("HL")
                elif z[i] < 0 and lag_z[i] < 0:
                    cluster.append("LL")
                elif z[i] < 0 and lag_z[i] > 0:
                    cluster.append("LH")
                else:
                    cluster.append("NS")
            gdf["local_moran"] = np.round(local_I, 6)
            gdf["cluster_type"] = cluster
            base_result_name = f"{name}_MoranI"
            with _state_lock:
                result_name = _disambiguate_layer_name(base_result_name)
                _gdf_to_layer(gdf, result_name)
            hh = cluster.count("HH"); ll = cluster.count("LL")
            hl = cluster.count("HL"); lh = cluster.count("LH")
            return summary + f"\n局部 LISA 结果图层「{result_name}」已加载到地图：HH热点={hh}，LL冷点={ll}，HL异常={hl}，LH异常={lh}"
        return summary
    except Exception as e:
        return f"Moran's I 分析失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_hotspot — Getis-Ord Gi* 热点分析
# ============================================================

@tool
def spatial_hotspot(layer_name: str, field: str, threshold: float = 0.01,
                    threshold_m: float = 0.0) -> str:
    """Getis-Ord Gi* 热点分析，探测统计显著的高值聚集(热点)与低值聚集(冷点)。
    - layer_name: 图层名（点要素或质心）。
    - field: 待分析字段（必须为非负数值）。
    - threshold: 兼容旧调用的距离阈值（度）；threshold_m: 米制距离阈值（优先使用本地 UTM 投影计算）。
    生成含 gi_z、gi_p 及 hotspot_type('热点'/'冷点'/'不显著') 的新图层并上图。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        if not field:
            numeric_fields = gdf.select_dtypes(include=[np.number]).columns.tolist()
            if not numeric_fields:
                return "图层没有可用于热点分析的数值字段"
            field = numeric_fields[0]
        if field not in gdf.columns:
            return f"字段「{field}」不存在"
        x = gdf[field].values.astype(float)
        if not np.isfinite(x).all():
            return "字段含空值或无穷大，请先清洗"
        if (x < 0).any():
            return "Getis-Ord Gi* 要求字段非负，检测到负值"
        n = len(x)
        if n < 3:
            return f"要素数（{n}）太少"
        if n > _MAX_DENSE_SPATIAL_STATS_FEATURES:
            return f"错误：热点分析当前最多支持 {_MAX_DENSE_SPATIAL_STATS_FEATURES} 个要素；请先聚合或抽样，避免距离矩阵耗尽内存"
        distance_threshold = threshold
        if threshold_m:
            if not math.isfinite(float(threshold_m)) or float(threshold_m) <= 0:
                return "米制距离阈值必须是大于 0 的有限数值"
            metric_gdf = _to_local_metric_gdf(gdf)
            coords = _spatial_feature_coordinates(metric_gdf)
            distance_threshold = float(threshold_m)
        else:
            if not math.isfinite(float(threshold)) or float(threshold) <= 0:
                return "距离阈值必须是大于 0 的有限数值"
            distance_threshold = float(threshold)
            coords = _spatial_feature_coordinates(gdf)
        from scipy.spatial.distance import cdist
        d = cdist(coords, coords)
        W = (d <= distance_threshold).astype(float)  # 含自身（Gi* 定义）
        W_sum = W.sum()
        if W_sum == 0:
            return "权重全为零，请调大 threshold"
        xbar = x.mean()
        # Gi* 统计量
        num = W @ x - xbar * W.sum(axis=1)
        S = np.sqrt((x ** 2).mean() - xbar * xbar)
        if S == 0:
            return "字段标准差为零（所有值相同），无法计算 Gi*"
        wi_sum = W.sum(axis=1)
        wi2_sum = (W ** 2).sum(axis=1)
        denom = S * np.sqrt((n * wi2_sum - wi_sum * wi_sum) / (n - 1))
        denom = np.where(denom == 0, 1e-12, denom)
        gi_z = num / denom
        from scipy.stats import norm
        gi_p = 2.0 * (1.0 - norm.cdf(np.abs(gi_z)))
        htype = []
        for i in range(n):
            if gi_z[i] > 1.96 and gi_p[i] < 0.05:
                htype.append("热点")
            elif gi_z[i] < -1.96 and gi_p[i] < 0.05:
                htype.append("冷点")
            else:
                htype.append("不显著")
        gdf["gi_z"] = np.round(gi_z, 4)
        gdf["gi_p"] = np.round(gi_p, 6)
        gdf["hotspot_type"] = htype
        base_result_name = f"{name}_热点"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(gdf, result_name)
        hot = htype.count("热点"); cold = htype.count("冷点")
        return f"Getis-Ord Gi* 热点分析完成：热点={hot} 个，冷点={cold} 个，不显著={n-hot-cold} 个。结果图层「{result_name}」已加载到地图（含 gi_z / gi_p / hotspot_type 字段）"
    except Exception as e:
        return f"热点分析失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_kde — 核密度估计
# ============================================================

@tool
def spatial_kde(layer_name: str, bandwidth: float = 0.0, grid_size: int = 50,
                bandwidth_m: float = 0.0, metric_units: bool = False) -> str:
    """核密度估计（KDE），将点事件转化为连续密度面格网并上图。
    - layer_name: 必须是点图层（Point/MultiPoint，面/线需先调 spatial_centroid 取质心）。
    - bandwidth: 兼容旧调用的高斯核带宽（度）；bandwidth_m: 米制带宽（使用本地 UTM 投影计算）。
      metric_units=True 时始终使用米制坐标，带宽传 0 按 Scott 法则估算。
    - grid_size: 输出格网边长（默认 50，即 50x50 格点）。生成含 density 与 density_km2 字段的图层。"""
    try:
        if isinstance(grid_size, bool) or not isinstance(grid_size, int) or not 10 <= grid_size <= 200:
            return "grid_size 必须是 10 到 200 之间的整数"
        if not math.isfinite(float(bandwidth)) or float(bandwidth) < 0:
            return "带宽必须是有限的非负数"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        import geopandas as gpd
        from shapely.geometry import Point

        # 只接受点要素：对面/线直接取顶点会算成"顶点密度"，与用户意图不符
        _types = set(gdf.geometry.geom_type.dropna().unique())
        if not _types or not _types.issubset({"Point", "MultiPoint"}):
            return (f"KDE 需要点图层，而「{name}」是 {'/'.join(sorted(_types)) or '未知'}。"
                    f"请先对「{name}」执行 spatial_centroid 取质心，再对质心图层做核密度估计。")

        metric_mode = bool(metric_units or bandwidth_m)
        metric_gdf = None
        if metric_mode:
            if not math.isfinite(float(bandwidth_m)) or float(bandwidth_m) < 0:
                return "米制带宽必须是有限的非负数"
            metric_gdf = _to_local_metric_gdf(gdf)
            coords = metric_gdf.geometry.get_coordinates().values
        else:
            coords = gdf.geometry.get_coordinates().values
        n = len(coords)
        if n < 3:
            return f"点要素数（{n}）太少，KDE 至少需要 3 个点"

        # --- 带宽：真实高斯核标准差；米制模式在本地 UTM 坐标中计算 ---
        # 注意：scipy 的 gaussian_kde(bw_method=标量) 里这个标量是 Scott 因子的倍数、
        # 不是带宽本身，直接把 0.01 传进去得到的实际带宽只有约 0.0002 度（差 40 倍），
        # 密度面会退化成几个孤立点。这里自己算核，带宽单位就是度，语义与文档一致。
        std_x, std_y = coords[:, 0].std(), coords[:, 1].std()
        if metric_mode and bandwidth_m > 0:
            h = float(bandwidth_m)
            bw_desc = f"{h:.2f} 米（手动指定）"
        elif metric_mode:
            h = float(np.mean([std_x, std_y]) * (n ** (-1.0 / 6.0)))
            if h <= 0:
                h = 1000.0
            bw_desc = f"{h:.2f} 米（Scott 法则自动估算）"
        elif bandwidth and bandwidth > 0:
            h = float(bandwidth)
            bw_desc = f"{h:.5f} 度（手动指定）"
        else:
            h = float(np.mean([std_x, std_y]) * (n ** (-1.0 / 6.0)))  # Scott 法则（2D）
            if h <= 0:
                h = 0.01
            bw_desc = f"{h:.5f} 度（Scott 法则自动估算）"

        xmin, ymin, xmax, ymax = (metric_gdf if metric_mode else gdf).total_bounds
        pad_x = (xmax - xmin) * 0.1 if xmax > xmin else h
        pad_y = (ymax - ymin) * 0.1 if ymax > ymin else h
        xi = np.linspace(xmin - pad_x, xmax + pad_x, grid_size)
        yi = np.linspace(ymin - pad_y, ymax + pad_y, grid_size)
        gx, gy = np.meshgrid(xi, yi)

        # 密度 = Σ exp(-0.5·(d/h)²) / (n · 2π · h²)，各向同性，单位：点/平方度
        norm = 1.0 / (n * 2.0 * np.pi * h * h)
        density = np.zeros(gx.size, dtype=float)
        # Bound both axes: grid-only chunks still allocate grid_count * n
        # arrays, which can exhaust memory for large point uploads.
        for _start in range(0, gx.size, 512):
            _sl = slice(_start, _start + 512)
            for _point_start in range(0, n, 1024):
                _points = coords[_point_start:_point_start + 1024]
                dx = (gx.ravel()[_sl, None] - _points[None, :, 0]) / h
                dy = (gy.ravel()[_sl, None] - _points[None, :, 1]) / h
                density[_sl] += np.exp(-0.5 * (dx * dx + dy * dy)).sum(axis=1) * norm

        # 兼容旧度制输出；米制模式直接换算平方米与平方千米。
        if metric_mode:
            density_km2 = density * 1e6
        else:
            lat_mid = float(np.mean([ymin, ymax]))
            km2_per_deg2 = 110.574 * 111.320 * max(np.cos(np.radians(lat_mid)), 1e-6)
            density_km2 = density / km2_per_deg2

        dmax = float(density.max())
        keep = density >= dmax * 0.01 if dmax > 0 else np.ones(density.size, dtype=bool)
        pts = np.column_stack([gx.ravel()[keep], gy.ravel()[keep]])
        grid_gdf = gpd.GeoDataFrame(
            {
                "density": np.round(density[keep], 8),
                "density_km2": np.round(density_km2[keep], 6),
                "geometry": [Point(x, y) for x, y in pts],
            },
            crs=metric_gdf.crs if metric_mode else "EPSG:4326",
        )
        if metric_mode:
            grid_gdf = grid_gdf.to_crs("EPSG:4326")
        base_result_name = f"{name}_KDE"
        with _state_lock:
            result_name = _disambiguate_layer_name(base_result_name)
            _gdf_to_layer(grid_gdf, result_name)
        _cell = (xi[-1] - xi[0]) / max(grid_size - 1, 1)
        if metric_mode:
            bandwidth_text = f"{h / 1000:.2f} km"
            cell_text = f"{_cell / 1000:.3f} km"
            density_text = (
                f"{density[keep].min():.6f} ~ {dmax:.6f} 点/平方米"
                f"（{density_km2[keep].min():.6f} ~ {density_km2.max():.6f} 点/km²）"
            )
        else:
            bandwidth_text = f"{h * 110.574:.2f} km"
            cell_text = f"{_cell * 110.574:.3f} km"
            density_text = (
                f"{density[keep].min():.6f} ~ {dmax:.6f} 点/平方度"
                f"（约 {density_km2[keep].min():.6f} ~ {density_km2.max():.6f} 点/km²）"
            )
        return (
            f"核密度估计完成，结果图层「{result_name}」已加载到地图。\n"
            f"- 输入点：{n} 个\n"
            f"- 带宽：{bw_desc}（约 {bandwidth_text}）\n"
            f"- 网格：{grid_size}x{grid_size}，格边长约 {cell_text}\n"
            f"- 保留格点：{len(grid_gdf)} 个（已过滤密度低于峰值 1% 的格点）\n"
            f"- 密度范围：{density_text}"
        )
    except Exception as e:
        return f"KDE 分析失败: {str(e)[:300]}"




# Re-exported from backend.services.tool_modules.raster: ndwi_analysis, ndbi_analysis, evi_analysis, ndmi_analysis, calc_spectral_index


# ============================================================
# 工具: generate_analysis_report — GIS 分析报告生成
# ============================================================

@tool
def generate_analysis_report(layer_name: str, analysis_summary: str = "",
                             include_stats: bool = True, include_quality: bool = True) -> str:
    """为指定图层生成结构化 Markdown 分析报告并保存到输出目录。
    - layer_name: 图层名（自动提取要素量、几何类型与字段统计）。
    - analysis_summary: 分析目的与方法简述。
    - include_stats: 是否包含字段数值统计(默认 True)；include_quality: 是否包含几何质量自检(默认 True)。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        import datetime as _dt
        lines = []
        lines.append(f"# GIS 分析报告：{name}")
        lines.append("")
        lines.append(f"- 生成时间：{_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- 图层要素数：{len(gdf)}")
        lines.append(f"- 几何类型：{(gdf.geom_type.value_counts().to_dict() if hasattr(gdf.geom_type, 'value_counts') else str(set(gdf.geom_type)))}")
        lines.append(f"- 坐标系：{gdf.crs.to_string() if gdf.crs else '未知（默认 WGS84）'}")
        lines.append("")
        if analysis_summary.strip():
            lines.append("## 一、分析目的与方法")
            lines.append("")
            lines.append(analysis_summary.strip())
            lines.append("")
        if include_quality:
            lines.append("## 二、数据质量检查")
            lines.append("")
            try:
                from shapely.validation import make_valid
                valid_mask = gdf.geometry.is_valid
                n_invalid = int((~valid_mask).sum())
                # 重复要素（几何完全相同）
                geoms = gdf.geometry.to_wkb()
                n_dup = int(len(geoms) - len(set(geoms.tolist())))
                # 空几何
                n_empty = int(gdf.geometry.is_empty.sum())
                lines.append(f"- 几何有效：{n_invalid} 个无效" + ("（已建议修复，可运行 spatial_fix_geometry）" if n_invalid else "（全部有效）"))
                lines.append(f"- 重复要素：{n_dup} 个")
                lines.append(f"- 空几何：{n_empty} 个")
            except Exception as e:
                lines.append(f"- 质量检查异常：{str(e)[:100]}")
            lines.append("")
        if include_stats:
            lines.append("## 三、属性统计")
            lines.append("")
            num_cols = gdf.select_dtypes(include=[np.number]).columns.tolist()
            if num_cols:
                lines.append("| 字段 | 最小值 | 最大值 | 平均值 | 标准差 | 空值数 |")
                lines.append("|---|---|---|---|---|---|")
                for col in num_cols[:12]:
                    s = gdf[col]
                    try:
                        lines.append(f"| {col} | {float(s.min()):.4g} | {float(s.max()):.4g} | "
                                     f"{float(s.mean()):.4g} | {float(s.std()):.4g} | {int(s.isna().sum())} |")
                    except Exception:
                        continue
            else:
                lines.append("无数值字段。")
            lines.append("")
        lines.append("## 四、结论")
        lines.append("")
        lines.append("（由分析人员根据分析目标补充结论。）")
        lines.append("")
        report = "\n".join(lines)
        # 落盘
        try:
            import io as _io
            import datetime as _dt2
            safe_layer_name = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]', '_', name).strip(' .') or 'layer'
            fname = (f"{safe_layer_name}_分析报告_"
                     f"{_dt2.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}.md")
            out_path = os.path.join(_temp_output_dir, "reports", fname)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with _io.open(out_path, "w", encoding="utf-8") as f:
                f.write(report)
            record_tool_artifact(fname, out_path, artifact_type="document")
            _pending_images.append({
                "name": fname,
                "filename": fname,
                "path": out_path,
                "url": f"/output/reports/{fname}",
                "description": f"分析报告：{name}",
            })
            return f"分析报告已生成并保存：{out_path}\n\n" + report[:600] + ("\n...（报告其余部分已保存到文件）" if len(report) > 600 else "")
        except Exception as e:
            return f"报告生成成功但保存失败: {str(e)[:100]}\n\n" + report
    except Exception as e:
        return f"报告生成失败: {str(e)[:300]}"


# Re-exported from backend.services.tool_modules.vector: spatial_fix_geometry, spatial_check_duplicates


# ============================================================
# 工具: ask_user_choice — 向用户弹出多选项确认（数据源/影像选择等）
# ============================================================

@tool
def ask_user_choice(prompt: str, options: list, choice_key: str = "") -> str:
    """向用户弹出一组选项按钮组，等待用户交互选择后自动继续执行。
    - prompt: 给用户的引导文案，说明选什么及决策原因。
    - options: 选项列表，每项为 dict({"label": "显示文字", "value": "值", "desc": "可选说明"}) 或 str，至少 2 项。
    - choice_key: 轮次标识（如 'data_source' / 'image_scene'），供下一轮识别上下文。"""
    try:
        if not options or len(options) < 2:
            return "错误：options 至少需要 2 个选项"
        # 规范化选项
        normalized = []
        for opt in options:
            if isinstance(opt, str):
                normalized.append({"label": opt, "value": opt})
            elif isinstance(opt, dict):
                normalized.append({
                    "label": opt.get("label", str(opt)),
                    "value": opt.get("value", opt.get("label", str(opt))),
                    "desc": opt.get("desc", ""),
                    "configured": opt.get("configured"),
                })
        # 数据源选择时，固定把 Esri 快速巡检插到最前面
        _is_data_source = (
            choice_key == "data_source"
            or any(kw in (prompt or "") for kw in ["数据源", "遥感影像", "数据来源", "下载数据", "卫星影像"])
        )
        if _is_data_source:
            _esri_opt = {
                "label": "Esri 快速巡检（无需下载，免费瓦片）",
                "value": "esri_quick_inspect",
                "desc": "直接使用 Esri 卫星瓦片做 RGB 启发式初筛，立即可用",
                "configured": True,
            }
            # 移除已有的 Esri 选项（避免重复）
            normalized = [o for o in normalized if "esri" not in o.get("value", "").lower()
                          and "esri" not in o.get("label", "").lower()]
            normalized.insert(0, _esri_opt)
        from backend.services import pending_action as _pa
        action = {
            "action": "choose_option",
            "summary": prompt[:200],
            "options": normalized,
            "choice_key": choice_key,
            "selected": None,
            "context": (runtime.get_last_user_message() or _last_user_message)[:300],
        }
        _pa.set_pending_action(_pa.get_active_session(), action)
        # [WAITING_USER_CHOICE] 标记：graph.py 检测到该标记后停止 agent 循环，
        # 防止 LLM 拿到"等待用户选择"文本后继续自作主张往下跑
        return f"[WAITING_USER_CHOICE] 已向用户弹出选项（{choice_key or '未标识'}），共 {len(normalized)} 个选项，等待用户选择。用户选择后会自动继续。"
    except Exception as e:
        return f"弹出选项失败: {str(e)[:200]}"



# ============================================================
# 工具: fetch_weather_data — Open-Meteo 天气数据获取（免费无 Key）
# ============================================================

@tool
def fetch_weather_data(latitude: float, longitude: float,
                       past_days: int = 7, forecast_days: int = 0,
                       variables: str = "",
                       start_date: str = "", end_date: str = "",
                       location_name: str = "") -> str:
    """从 Open-Meteo 获取指定坐标(WGS84)的历史/预报天气并绘制趋势图（免费免Key）。
    - latitude / longitude: 坐标(WGS84经纬度)。地名需先经 amap_geocode 转坐标。
    - past_days: 过去天数(默认 7，上限 90)；forecast_days: 预报天数(默认 0，上限 16)。
    - variables: 逗号分隔指标，默认温度/降水/风速；start_date/end_date: 自定义日期范围(YYYY-MM-DD)。
    - location_name: 地名标注，用于图表标题与统计展示。"""
    try:
        import requests
        import datetime

        if not variables:
            variables = "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max"

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": variables,
            "timezone": "auto",
        }
        if start_date and end_date:
            params["start_date"] = start_date
            params["end_date"] = end_date
        else:
            params["past_days"] = min(max(past_days, 0), 90)
            params["forecast_days"] = min(max(forecast_days, 0), 16)

        resp = requests.get("https://api.open-meteo.com/v1/forecast",
                            params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        if not dates:
            return "未获取到天气数据，请检查坐标和时间范围。"

        var_list = [v.strip() for v in variables.split(",")]
        title = f"{location_name + ' ' if location_name else ''}天气趋势 ({dates[0]} ~ {dates[-1]})"

        # 生成图表
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np

            fig, ax1 = plt.subplots(figsize=(10, 5))
            x = range(len(dates))

            if "precipitation_sum" in var_list and "precipitation_sum" in daily:
                precip = daily["precipitation_sum"]
                ax1.bar(x, precip, alpha=0.3, color="#42a5f5", label="降水 (mm)")
                ax1.set_ylabel("降水 (mm)", color="#1976d2")
                ax1.tick_params(axis="y", labelcolor="#1976d2")

            ax2 = ax1.twinx()
            if "temperature_2m_max" in var_list and "temperature_2m_max" in daily:
                ax2.plot(x, daily["temperature_2m_max"], "r-o", markersize=3, label="最高温")
            if "temperature_2m_min" in var_list and "temperature_2m_min" in daily:
                ax2.plot(x, daily["temperature_2m_min"], "b--o", markersize=3, label="最低温")
            ax2.set_ylabel("温度 (°C)", color="#d32f2f")
            ax2.tick_params(axis="y", labelcolor="#d32f2f")

            ax1.set_xticks(x)
            ax1.set_xticklabels([d[5:] for d in dates], rotation=45, fontsize=8)
            ax1.set_title(title, fontsize=12)
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)
            plt.tight_layout()

            import os, uuid
            os.makedirs("cache/charts", exist_ok=True)
            fname = f"weather_{uuid.uuid4().hex[:8]}.png"
            fpath = os.path.join("cache/charts", fname)
            plt.savefig(fpath, dpi=120)
            plt.close()
            abs_fpath = os.path.abspath(fpath)
            record_tool_artifact(fname, abs_fpath, artifact_type="image")
            _pending_images.append({"name": fname, "path": abs_fpath, "url": f"/cache/charts/{fname}", "type": "png"})
        except Exception as e:
            pass

        # 统计摘要
        parts = [f"已获取 {len(dates)} 天天气数据（{dates[0]} ~ {dates[-1]}）。"]
        if "temperature_2m_max" in daily:
            vals = [v for v in daily["temperature_2m_max"] if v is not None]
            if vals:
                parts.append(f"最高温：平均 {np.mean(vals):.1f}°C，最高 {max(vals):.1f}°C，最低 {min(vals):.1f}°C")
        if "precipitation_sum" in daily:
            vals = [v for v in daily["precipitation_sum"] if v is not None]
            if vals:
                total = sum(vals)
                max_i = vals.index(max(vals))
                parts.append(f"总降水：{total:.1f}mm，最大日降水 {max(vals):.1f}mm（{dates[max_i]}）")
        if "windspeed_10m_max" in daily:
            vals = [v for v in daily["windspeed_10m_max"] if v is not None]
            if vals:
                parts.append(f"最大风速：{max(vals):.1f} km/h")
        parts.append("图表已生成，可继续进行空间叠加分析。")
        return "\n".join(parts)
    except Exception as e:
        return f"获取天气数据失败: {str(e)[:200]}（可能是网络问题，Open-Meteo 国内偶尔不稳定）"


# ============================================================
# 工具: fetch_earthquake_data — USGS 地震数据获取（免费无 Key）
# ============================================================

@tool
def fetch_earthquake_data(start_time: str = "", end_time: str = "",
                          min_magnitude: float = 2.5,
                          min_lat: float = -90, max_lat: float = 90,
                          min_lon: float = -180, max_lon: float = 180,
                          limit: int = 500) -> str:
    """从 USGS 获取地震数据并生成点图层推送到地图（免费免Key）。
    - start_time / end_time: 时间范围(YYYY-MM-DD，默认近 30 天)；min_magnitude: 最小震级(默认 2.5)。
    - min_lat/max_lat/min_lon/max_lon: 空间范围；limit: 最大条数(默认 500)。输出分级着色图层与震级分布直方图。"""
    try:
        import requests
        import datetime

        if not end_time:
            end_time = datetime.date.today().isoformat()
        if not start_time:
            start_time = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

        params = {
            "format": "geojson",
            "starttime": start_time,
            "endtime": end_time,
            "minmagnitude": min_magnitude,
            "minlatitude": min_lat,
            "maxlatitude": max_lat,
            "minlongitude": min_lon,
            "maxlongitude": max_lon,
            "limit": limit,
        }
        resp = requests.get("https://earthquake.usgs.gov/fdsnws/event/1/query",
                            params=params, timeout=25)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if not features:
            return f"未找到 {start_time} ~ {end_time} 期间震级 >= {min_magnitude} 的地震记录。"

        # 构建 GeoJSON
        geojson_features = []
        mags = []
        for f in features:
            props = f.get("properties", {})
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            mag = props.get("mag")
            if mag is not None:
                mags.append(mag)
            geojson_features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [coords[0], coords[1]]},
                "properties": {
                    "title": props.get("place", "未知位置"),
                    "magnitude": mag,
                    "depth_km": coords[2] if len(coords) > 2 else None,
                    "time": datetime.datetime.fromtimestamp(props.get("time", 0) / 1000).strftime("%Y-%m-%d %H:%M") if props.get("time") else "",
                    "url": props.get("url", ""),
                }
            })

        fc = {"type": "FeatureCollection", "features": geojson_features}
        layer_name = f"地震_{start_time}_{end_time}_M{min_magnitude}+"

        # 震级分级着色样式
        def mag_color(m):
            if m >= 7: return "#d32f2f"
            if m >= 6: return "#f57c00"
            if m >= 5: return "#fbc02d"
            if m >= 4: return "#7cb342"
            return "#42a5f5"

        style = {
            "circleRadius": 5,
            "circleColor": "#d32f2f",
            "circleOpacity": 0.8,
        }

        _register_layer(layer_name, fc)
        _push_layer(layer_name, fc, style=style)

        # 生成震级分布直方图
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np

            fig, ax = plt.subplots(figsize=(8, 4))
            bins = [2.5, 3, 4, 5, 6, 7, 8, 10]
            labels = ["2.5-3", "3-4", "4-5", "5-6", "6-7", "7-8", "8+"]
            counts, _ = np.histogram(mags, bins=bins)
            colors = ["#42a5f5", "#7cb342", "#fbc02d", "#f57c00", "#e64a19", "#d32f2f", "#b71c1c"]
            ax.bar(labels, counts, color=colors[:len(labels)])
            ax.set_title(f"震级分布（共 {len(mags)} 次地震）", fontsize=12)
            ax.set_ylabel("地震次数")
            ax.set_xlabel("震级")
            plt.tight_layout()
            import os, uuid
            os.makedirs("cache/charts", exist_ok=True)
            fname = f"quake_{uuid.uuid4().hex[:8]}.png"
            fpath = os.path.join("cache/charts", fname)
            plt.savefig(fpath, dpi=120)
            plt.close()
            abs_fpath = os.path.abspath(fpath)
            record_tool_artifact(fname, abs_fpath, artifact_type="image")
            _pending_images.append({"name": fname, "path": abs_fpath, "url": f"/cache/charts/{fname}", "type": "png"})
        except Exception:
            pass

        # 统计摘要
        strongest = max(features, key=lambda f: (f.get("properties", {}).get("mag") or 0))
        sp = strongest.get("properties", {})
        parts = [
            f"已获取 {len(geojson_features)} 次地震（{start_time} ~ {end_time}，震级 >= {min_magnitude}），已加载到地图。",
            f"最强地震：{sp.get('place', '未知')}，震级 {sp.get('mag')}，时间 {datetime.datetime.fromtimestamp(sp.get('time', 0)/1000).strftime('%Y-%m-%d %H:%M') if sp.get('time') else '未知'}",
        ]
        if mags:
            parts.append(f"震级范围：{min(mags):.1f} ~ {max(mags):.1f}，平均 {np.mean(mags):.1f}")
        parts.append("可继续进行热点分析（spatial_hotspot）、缓冲区分析（spatial_buffer）等空间操作。")
        return "\n".join(parts)
    except Exception as e:
        return f"获取地震数据失败: {str(e)[:200]}（USGS 国内访问不稳定，可能需要检查网络）"




# ============================================================
# 卫星影像 RGB 启发式巡检工具
# ============================================================

def _tile_to_quadkey(x, y, z):
    """Bing Maps 瓦片坐标转 quadkey"""
    q = ""
    for i in range(z, 0, -1):
        d = 0
        m = 1 << (i - 1)
        if x & m:
            d += 1
        if y & m:
            d += 2
        q += str(d)
    return q


def _fetch_satellite_imagery(west, south, east, north, zoom=16, max_tiles=49, source="auto"):
    """下载卫星影像瓦片并拼接为 PIL Image。
    source: auto（先 Esri 失败回退 Bing）/ esri / bing
    自动使用系统代理（urllib getproxies），兼容 HTTP_PROXY/HTTPS_PROXY 环境变量。
    返回 (image, metadata) 或抛出异常。"""
    import math
    import io as _io
    import urllib.request
    from PIL import Image

    ESRI_TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    BING_TILE = "https://t{s}.dynamic.tiles.ditu.live.com/comp/ch/{q}?mkt=zh-CN&ur=cn&it=A&n=z&og=804&cstl=vbd"
    AMAP_TILE = "https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}"

    # 显式构建支持代理的 opener（优先用户自定义代理，其次系统代理）
    _proxies = _get_effective_proxies()
    print(f"[GIS] 卫星瓦片代理设置: {_proxies}（自定义: {_custom_proxy or '未设置'}）", flush=True)
    _proxy_handler = urllib.request.ProxyHandler(_proxies)
    _opener = urllib.request.build_opener(_proxy_handler)

    def _lon2tile(lon, z):
        return (lon + 180.0) / 360.0 * (2 ** z)

    def _lat2tile(lat, z):
        lat = max(-85.05112878, min(85.05112878, lat))
        rad = math.radians(lat)
        return (1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * (2 ** z)

    def _download_tiles(tile_source):
        """下载指定源的瓦片并拼接，返回 (mosaic, z, x0, y0) 或抛出异常"""
        z = max(10, min(18, int(zoom)))
        while True:
            x0 = math.floor(_lon2tile(west, z))
            x1 = math.ceil(_lon2tile(east, z)) - 1
            y0 = math.floor(_lat2tile(north, z))
            y1 = math.ceil(_lat2tile(south, z)) - 1
            if (x1 - x0 + 1) * (y1 - y0 + 1) <= max_tiles or z <= 10:
                break
            z -= 1

        mosaic = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
        _sub = 0
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if tile_source == "esri":
                    url = ESRI_TILE.format(z=z, y=ty, x=tx % (2 ** z))
                elif tile_source == "amap":
                    url = AMAP_TILE.format(s=(_sub % 4) + 1, x=tx, y=ty, z=z)
                    _sub += 1
                else:  # bing
                    qk = _tile_to_quadkey(tx, ty, z)
                    url = BING_TILE.format(s=(_sub % 4) + 1, q=qk)
                    _sub += 1
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GIS-WORKTABLE/1.0",
                    "Referer": "https://www.bing.com/maps/" if tile_source == "bing" else "",
                })
                _tile_key = (tile_source, z, tx, ty)
                if _tile_key in _tile_cache:
                    tile = _tile_cache[_tile_key]
                    _cache_hits["tile"] += 1
                else:
                    with _opener.open(req, timeout=20) as resp:
                        tile = Image.open(_io.BytesIO(resp.read())).convert("RGB")
                    _tile_cache[_tile_key] = tile
                    # 缓存上限：超过 500 张时清空一半（防止内存膨胀）
                    if len(_tile_cache) > 500:
                        _keys = list(_tile_cache.keys())[:250]
                        for _k in _keys:
                            del _tile_cache[_k]
                mosaic.paste(tile, ((tx - x0) * 256, (ty - y0) * 256))
        return mosaic, z, x0, y0

    # 按 source 策略尝试下载
    errors = []
    sources_to_try = []
    if source == "auto":
        sources_to_try = ["esri", "bing", "amap"]
    else:
        sources_to_try = [source]

    mosaic = z = x0 = y0 = None
    used_source = None
    for src in sources_to_try:
        try:
            mosaic, z, x0, y0 = _download_tiles(src)
            used_source = src
            break
        except Exception as e:
            errors.append(f"{src}: {str(e)[:100]}")
            continue

    if mosaic is None:
        raise RuntimeError("所有卫星影像源均失败: " + "; ".join(errors))

    px0 = int(round((_lon2tile(west, z) - x0) * 256))
    py0 = int(round((_lat2tile(north, z) - y0) * 256))
    px1 = int(round((_lon2tile(east, z) - x0) * 256))
    py1 = int(round((_lat2tile(south, z) - y0) * 256))
    image = mosaic.crop((max(0, px0), max(0, py0), min(mosaic.width, px1), min(mosaic.height, py1)))

    pixel_w = (east - west) / image.width
    pixel_h = (north - south) / image.height
    transform = (west, pixel_w, 0, north, 0, -pixel_h)

    metadata = {
        "zoom": z,
        "tile_count": int((mosaic.width / 256) * (mosaic.height / 256)),
        "width": image.width,
        "height": image.height,
        "bbox": [west, south, east, north],
        "transform": transform,
        "crs": "EPSG:4326",
        "source": used_source,
    }
    return image, metadata


def _fetch_esri_imagery(west, south, east, north, zoom=16, max_tiles=49):
    """兼容旧调用：等价于 _fetch_satellite_imagery(source='auto')"""
    return _fetch_satellite_imagery(west, south, east, north, zoom=zoom, max_tiles=max_tiles, source="auto")


def _classify_rgb_heuristic(image, analysis_mask=None):
    """RGB 启发式分类算法。
    返回 (masks_dict, statistics_list, active_count)
    masks_dict: {category: numpy 2d bool array}
    """
    import numpy as np

    arr = np.array(image, dtype=np.int16)
    R, G, B = arr[..., 0], arr[..., 1], arr[..., 2]
    brightness = (R + G + B) / 3.0
    saturation = arr.max(axis=2) - arr.min(axis=2)
    grey = R * 0.299 + G * 0.587 + B * 0.114
    edge = np.zeros_like(grey)
    edge[:, 1:] += np.abs(grey[:, 1:] - grey[:, :-1])
    edge[1:, :] += np.abs(grey[1:, :] - grey[:-1, :])

    active = np.ones((image.height, image.width), dtype=bool) if analysis_mask is None else analysis_mask
    active_count = int(active.sum())

    masks = {}
    masks["vegetation"] = (G - R > 10) & (G - B > 5) & (G > 48)
    masks["water"] = (~masks["vegetation"]) & (B - R > 7) & (B - G > 2) & (brightness < 170)
    masks["bare_ground"] = (~masks["vegetation"]) & (~masks["water"]) & (R - B > 16) & (G - B > 7) & (brightness > 72) & (saturation > 18)
    masks["built_up"] = (~masks["vegetation"]) & (~masks["water"]) & (~masks["bare_ground"]) & (brightness > 58) & (brightness < 235) & ((saturation < 38) | (edge > 25))

    for k in masks:
        masks[k] = masks[k] & active

    statistics = []
    for cat, mask in masks.items():
        count = int(mask.sum())
        statistics.append({
            "category": cat,
            "pixel_count": count,
            "pixel_ratio": round(count / active_count, 4) if active_count > 0 else 0,
        })

    return masks, statistics, active_count


def _mask_to_geojson(mask, transform, category, min_pixels=20, max_features=300):
    """将二值 mask 矢量化为 GeoJSON FeatureCollection。
    先用连通域分析移除小于 min_pixels 的噪点，再用
    rasterio.features.shapes 做真正的轮廓提取，最多保留 max_features 个。"""
    import numpy as np
    import rasterio.features
    from rasterio.transform import Affine
    from scipy import ndimage as ndi

    if not mask.any():
        return {"type": "FeatureCollection", "features": []}

    # 连通域分析，移除小于 min_pixels 的碎小区域（噪点）
    labeled, n = ndi.label(mask.astype(np.uint8))
    if n > 0:
        sizes = np.bincount(labeled.ravel())
        keep_labels = [i for i in range(1, n + 1) if sizes[i] >= min_pixels]
        cleaned = np.isin(labeled, keep_labels)
    else:
        cleaned = mask

    if not cleaned.any():
        return {"type": "FeatureCollection", "features": []}

    # rasterio transform 格式 (c, a, b, f, d, e)
    cc, aa, bb, ff, dd, ee = transform
    aff = Affine(aa, bb, cc, dd, ee, ff)

    # 收集所有多边形及其像素面积，按面积降序，最多保留 max_features 个
    candidates = []
    for geom, val in rasterio.features.shapes(
        cleaned.astype(np.uint8),
        mask=cleaned,
        transform=aff,
    ):
        if val != 1:
            continue
        coords = geom.get("coordinates", [])
        if not coords:
            continue
        poly_coords = coords[0] if coords else []
        if len(poly_coords) < 4:
            continue
        # 用经纬度包围盒面积作为排序依据（近似大小）
        all_pts = []
        def _collect(coords_list):
            if coords_list and isinstance(coords_list[0], (int, float)):
                all_pts.append(coords_list[:2])
            else:
                for x in coords_list:
                    _collect(x)
        _collect(coords)
        if len(all_pts) < 3:
            continue
        lons = [p[0] for p in all_pts]
        lats = [p[1] for p in all_pts]
        bbox_area = (max(lons) - min(lons)) * (max(lats) - min(lats))
        candidates.append((bbox_area, geom))

    candidates.sort(key=lambda x: x[0], reverse=True)
    features = [{
        "type": "Feature",
        "properties": {"category": category},
        "geometry": geom,
    } for _, geom in candidates[:max_features]]

    return {"type": "FeatureCollection", "features": features}


def _calculate_geojson_area(geojson):
    """计算 GeoJSON 的面积（平方米），使用等面积投影。"""
    try:
        import geopandas as gpd
        from shapely.geometry import shape

        features = geojson.get("features", [])
        if not features:
            return 0.0

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        # 转换到等面积投影 EPSG:6933（全球等面积）
        gdf_ea = gdf.to_crs("EPSG:6933")
        return float(gdf_ea.geometry.area.sum())
    except Exception:
        return 0.0


def _rasterize_boundary(boundary_geojson, image, bbox):
    """将行政边界栅格化为与影像同尺寸的 bool mask。"""
    import numpy as np
    from PIL import Image, ImageDraw

    west, south, east, north = bbox
    mask_img = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask_img)

    feats = boundary_geojson.get("features", [])
    for f in feats:
        geom = f.get("geometry", {})
        gtype = geom.get("type")
        polys = []
        if gtype == "Polygon":
            polys = [geom["coordinates"]]
        elif gtype == "MultiPolygon":
            polys = geom["coordinates"]
        for poly in polys:
            for ring in poly:
                pts = []
                for p in ring:
                    if len(p) >= 2:
                        px = (p[0] - west) / (east - west) * image.width
                        py = (north - p[1]) / (north - south) * image.height
                        pts.append((px, py))
                if len(pts) >= 3:
                    draw.polygon(pts, fill=255)

    arr = np.array(mask_img)
    result = arr >= 128
    return result if result.any() else None


@tool
def inspect_satellite_image(
    place_name: str = "",
    bbox: str = "",
    inspection_type: str = "all",
    zoom: int = 14,
) -> str:
    """卫星影像快速巡检（无需下载）。利用 Esri World Imagery 免费瓦片进行 RGB 启发式初筛水体/植被/裸地/建筑候选区并上图。
    - place_name: 明确地名（如'武汉市洪山区'，禁止编造），优先裁剪已注册行政边界。
    - bbox: 手动范围 'west,south,east,north'（WGS84），与 place_name 二选一。
    - inspection_type: 巡检类别，'all'(默认) 或 'water,vegetation,bare_ground,built_up' 组合。
    - zoom: 瓦片级别 10-18（默认 14）。生成影像巡检矢量图层及面积初筛统计。"""
    import numpy as np

    # --- 1. 解析研究范围 ---
    west = south = east = north = None
    boundary_geojson = None
    label = place_name or "自定义范围"

    if bbox:
        try:
            parts = [float(x) for x in bbox.split(",")]
            west, south, east, north = parts[:4]
        except Exception:
            return "错误：bbox 格式应为 west,south,east,north（WGS84 经纬度）"
    elif place_name:
        # 从已注册图层中查找行政边界
        boundary_info = _registered_layers.get(place_name)
        if boundary_info and boundary_info.get("geojson"):
            boundary_geojson = boundary_info["geojson"]
            coords = []
            for f in boundary_geojson.get("features", []):
                _extract_nested_coords(f.get("geometry", {}).get("coordinates"), coords)
            if coords:
                lons = [p[0] for p in coords]
                lats = [p[1] for p in coords]
                west, south, east, north = min(lons), min(lats), max(lons), max(lats)
        if west is None:
            # 尝试 DataV 行政边界 API
            try:
                import requests as _req
                import urllib.parse as _up
                _dv_url = "https://geo.datav.aliyun.com/areas_v3/bound/geojson?name=" + _up.quote(place_name)
                resp = _req.get(_dv_url, timeout=15)
                if resp.status_code == 200:
                    boundary_geojson = resp.json()
                    coords = []
                    for f in boundary_geojson.get("features", []):
                        _extract_nested_coords(f.get("geometry", {}).get("coordinates"), coords)
                    if coords:
                        lons = [p[0] for p in coords]
                        lats = [p[1] for p in coords]
                        west, south, east, north = min(lons), min(lats), max(lons), max(lats)
            except Exception:
                pass

    if west is None:
        return "错误：无法确定研究范围。请先加载行政边界图层（如通过 datav_boundary 获取），或直接提供 bbox 参数。"

    if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
        return f"错误：范围无效 [{west}, {south}, {east}, {north}]"

    # --- 2. 获取卫星影像 ---
    try:
        image, meta = _fetch_esri_imagery(west, south, east, north, zoom)
    except Exception as e:
        return f"错误：卫星影像获取失败 - {e}"

    if image.width < 10 or image.height < 10:
        return "错误：影像范围过小，请扩大范围或降低 zoom"

    # --- 3. 边界栅格化 ---
    analysis_mask = None
    if boundary_geojson:
        try:
            analysis_mask = _rasterize_boundary(boundary_geojson, image, [west, south, east, north])
        except Exception:
            analysis_mask = None

    # --- 4. RGB 启发式分类 ---
    all_masks, statistics, active_count = _classify_rgb_heuristic(image, analysis_mask)

    # 筛选用户指定的类别
    cats = ["water", "vegetation", "bare_ground", "built_up"]
    if inspection_type and inspection_type != "all":
        requested = [c.strip() for c in inspection_type.split(",") if c.strip() in cats]
        if requested:
            cats = requested

    # --- 5. 矢量化并计算面积 ---
    all_features = []
    cat_names = {"water": "水体", "vegetation": "植被", "bare_ground": "裸地", "built_up": "建筑/建成区"}
    cat_colors = {"water": "#38BDF8", "vegetation": "#22C55E", "built_up": "#A78BFA", "bare_ground": "#FB923C"}

    for cat in cats:
        mask = all_masks.get(cat)
        if mask is None or not mask.any():
            continue
        # 矢量化
        fc = _mask_to_geojson(mask, meta["transform"], cat)
        # 计算面积
        area_m2 = _calculate_geojson_area(fc)
        # 更新统计
        for s in statistics:
            if s["category"] == cat:
                s["area_m2"] = round(area_m2, 1)
                s["area_km2"] = round(area_m2 / 1e6, 4)
                s["feature_count"] = len(fc["features"])
        # 合并要素
        for feat in fc["features"]:
            feat["properties"]["category"] = cat
            all_features.append(feat)

    # --- 5.5 生成 overlay PNG（原始影像 + 半透明分类色块叠加，对齐 GeoHarness 效果）---
    _overlay_url = None
    try:
        import numpy as _np
        from PIL import Image as _PILImage
        import os as _os, uuid as _uuid
        _cat_rgb = {
            "water": (56, 189, 248),
            "vegetation": (34, 197, 94),
            "bare_ground": (251, 146, 60),
            "built_up": (167, 139, 250),
        }
        _overlay_arr = _np.zeros((image.height, image.width, 4), dtype=_np.uint8)
        for _cat in cats:
            _mask = all_masks.get(_cat)
            if _mask is None or not _mask.any():
                continue
            _rgb = _cat_rgb.get(_cat, (255, 255, 255))
            _overlay_arr[_mask, 0] = _rgb[0]
            _overlay_arr[_mask, 1] = _rgb[1]
            _overlay_arr[_mask, 2] = _rgb[2]
            _overlay_arr[_mask, 3] = 110  # 半透明
        _overlay_img = _PILImage.fromarray(_overlay_arr, "RGBA")
        _combined = _PILImage.alpha_composite(image.convert("RGBA"), _overlay_img).convert("RGB")

        # --- 图例 + 指北针（PIL 绘制，解决巡检图无图例/指北针问题）---
        try:
            from PIL import ImageDraw as _PIDraw, ImageFont as _PIFont
            _draw = _PIDraw.Draw(_combined, "RGBA")
            _w, _h = _combined.size

            # 中文字体（微软雅黑优先，fallback 到默认字体）
            _font_paths = [
                r"C:\Windows\Fonts\msyh.ttc",
                r"C:\Windows\Fonts\simhei.ttf",
                r"C:\Windows\Fonts\simsun.ttc",
                r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
            ]
            _font = None
            for _fp in _font_paths:
                if _os.path.exists(_fp):
                    try:
                        _font = _PIFont.truetype(_fp, 16)
                        break
                    except Exception:
                        continue
            if _font is None:
                _font = _PIFont.load_default()

            # 图例（右下角）：各类别色块 + 中文名 + 占比
            _legend_items = []
            for _s in statistics:
                if _s["category"] not in cats:
                    continue
                _ratio = _s.get("pixel_ratio", 0)
                _legend_items.append((_s["category"], _ratio))
            if _legend_items:
                _swatch = 22
                _row_h = 24
                _pad = 10
                _box_w = 230
                _box_h = _pad * 2 + len(_legend_items) * _row_h
                _bx0 = _w - _box_w - 14
                _by0 = _h - _box_h - 14
                _draw.rectangle([_bx0, _by0, _bx0 + _box_w, _by0 + _box_h],
                                fill=(255, 255, 255, 200), outline=(0, 0, 0, 80), width=1)
                _draw.text((_bx0 + _pad, _by0 + _pad - 4), "图例",
                           fill=(0, 0, 0, 255), font=_font)
                _y = _by0 + _pad + 14
                for _cat, _ratio in _legend_items:
                    _rgb = _cat_rgb.get(_cat, (128, 128, 128))
                    _draw.rectangle([_bx0 + _pad, _y, _bx0 + _pad + _swatch, _y + 14],
                                    fill=_rgb + (255,), outline=(0, 0, 0, 60))
                    _label = f"{cat_names.get(_cat, _cat)}  {_ratio:.1%}"
                    _draw.text((_bx0 + _pad + _swatch + 8, _y - 2), _label,
                               fill=(20, 20, 20, 255), font=_font)
                    _y += _row_h

            # 指北针（右上角）：N + 向上箭头
            _ax0, _ay0 = _w - 74, 14
            _draw.rectangle([_ax0, _ay0, _ax0 + 60, _ay0 + 72],
                            fill=(255, 255, 255, 200), outline=(0, 0, 0, 80), width=1)
            _cx, _cy = _ax0 + 30, _ay0 + 44
            _draw.polygon([(_cx, _cy - 24), (_cx - 10, _cy + 6), (_cx, _cy + 1), (_cx + 10, _cy + 6)],
                          fill=(220, 40, 40, 255), outline=(0, 0, 0, 120))
            _nfont = _PIFont.truetype(_font_paths[0], 14) if _os.path.exists(_font_paths[0]) else _PIFont.load_default()
            _draw.text((_cx - 7, _ay0 + 2), "N", fill=(220, 40, 40, 255), font=_nfont)
        except Exception as _e:
            print(f"[GIS] 巡检图图例/指北针绘制失败(不影响主流程): {_e}", flush=True)

        _os.makedirs("cache/charts", exist_ok=True)
        _fname = f"inspect_{_uuid.uuid4().hex[:8]}.png"
        _fpath = _os.path.join("cache/charts", _fname)
        _combined.save(_fpath, "PNG")
        _combined.close()
        _overlay_img.close()
        _overlay_url = f"/cache/charts/{_fname}"
        _abs_fpath = _os.path.abspath(_fpath)
        record_tool_artifact(_fname, _abs_fpath, artifact_type="image")
        _pending_images.append({"name": _fname, "path": _abs_fpath, "url": _overlay_url, "type": "png"})
    except Exception as _e:
        pass  # overlay 生成失败不影响主流程

    # --- 6. 注册结果图层 ---
    layer_name = f"影像巡检_{label}"
    result_geojson = {"type": "FeatureCollection", "features": all_features}

    if all_features:
        _register_layer(layer_name, result_geojson)
        _push_layer(layer_name, result_geojson, {
            "color": "#FF6B6B",
            "weight": 1,
            "fillOpacity": 0.5,
            "fillColor": "#FF6B6B",
        })

    # --- 7. 生成结果报告 ---
    total_classified = sum(s.get("pixel_count", 0) for s in statistics if s["category"] in cats)
    total_area = sum(s.get("area_m2", 0) for s in statistics if s["category"] in cats)

    lines = [
        f"## 卫星影像巡检结果（{label}）",
        "",
        "### 基本信息",
        f"- 影像来源：{'Esri World Imagery' if meta.get('source') == 'esri' else 'Bing 中国区卫星影像'}（缩放级别 z={meta['zoom']}）",
        f"- 研究范围：[{west:.4f}, {south:.4f}, {east:.4f}, {north:.4f}]",
        f"- 影像尺寸：{meta['width']} x {meta['height']} 像素",
        f"- 分析像素数：{active_count}",
        f"- 行政边界裁剪：{'是' if analysis_mask is not None else '否'}",
        f"- 坐标参考：EPSG:4326（WGS84）",
        f"- 面积计算：EPSG:6933 等面积投影",
        "",
        "### 分类统计（RGB 启发式初筛）",
        "",
        "| 类别 | 像素数 | 占比 | 要素数 | 面积(km2) |",
        "|------|--------|------|--------|-----------|",
    ]
    for s in statistics:
        if s["category"] not in cats:
            continue
        lines.append(
            f"| {cat_names.get(s['category'], s['category'])} "
            f"| {s.get('pixel_count', 0)} "
            f"| {s.get('pixel_ratio', 0):.1%} "
            f"| {s.get('feature_count', 0)} "
            f"| {s.get('area_km2', 0)} |"
        )

    lines.extend([
        "",
        f"- 已分类像素占比：{total_classified/active_count:.1%}" if active_count > 0 else "- 已分类像素占比：N/A",
        f"- 统计口径：各类占比 = 该类像素数 / 总分析像素数，各类独立计算；混合像元、阴影、未识别地物不计入任何类别，因此各类占比合计通常不足 100%",
        f"- 候选区域总面积：{total_area/1e6:.4f} km2",
        f"- 生成矢量要素：{len(all_features)} 个",
        f"- 结果图层：{layer_name}" if all_features else "- 结果图层：未生成（候选区域过少）",
        "",
        "### 局限性说明",
        "- 本结果为基于 RGB 颜色特征的启发式初筛，不等同于专业遥感分类",
        "- 面积为等面积投影下的估计值，非实测面积",
        "- 阴影、云、季节变化、影像时相会影响分类准确性",
        "- 结果需人工核验后才可用于正式分析",
        "- 影像来源为 Esri World Imagery 瓦片，不同区域影像时相可能不同",
    ])

    return "\n".join(lines)


def _extract_nested_coords(coords, result):
    """递归提取嵌套坐标数组中的点"""
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        result.append(coords[:2])
    else:
        for c in coords:
            _extract_nested_coords(c, result)

@tool
def generate_static_map(
    layer_ids: str = "",
    title: str = "GIS 分析结果图",
    output_name: str = "static_map",
    show_north_arrow: bool = True,
    show_scale_bar: bool = True,
    dpi: int = 150,
) -> str:
    """根据已注册的矢量图层生成独立静态研究区图（PNG），不包含交互地图的卫星底图。
    需要保留当前地图底图（包括卫星影像）导出图片时应调用 export_map；本工具用于独立矢量图。
    layer_ids: 要绘制的图层ID，逗号分隔（为空则绘制所有已注册图层）；
    title: 地图标题；output_name: 输出文件名；
    show_north_arrow: 是否显示指北针；show_scale_bar: 是否显示比例尺；dpi: 输出分辨率（30–600）。"""
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not 30 <= dpi <= 600:
        return "静态地图 DPI 范围为 30 到 600"
    try:
        import geopandas as gpd
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyArrowPatch
        import os

        layers_to_draw = []
        if layer_ids.strip():
            ids = [x.strip() for x in layer_ids.split(",") if x.strip()]
            missing_ids = [lid for lid in ids if lid not in _registered_layers]
            if missing_ids:
                return f"指定图层不存在：{', '.join(missing_ids)}"
            for lid in ids:
                layers_to_draw.append((lid, _registered_layers[lid]))
        else:
            for lid, ldata in _registered_layers.items():
                layers_to_draw.append((lid, ldata))

        if not layers_to_draw:
            return "没有可绘制的图层，请先加载或创建图层"

        fig, ax = plt.subplots(1, 1, figsize=(10, 8))
        colors = plt.cm.Set2.colors
        drawn_layer_count = 0
        for i, (lid, ldata) in enumerate(layers_to_draw):
            geojson = ldata.get("geojson") or ldata
            if not geojson:
                continue
            try:
                gdf = gpd.GeoDataFrame.from_features(geojson.get("features", []))
                if gdf.empty:
                    continue
                color = colors[i % len(colors)]
                gdf.plot(ax=ax, facecolor=color, edgecolor="black",
                         linewidth=0.5, alpha=0.7, label=lid)
                drawn_layer_count += 1
            except Exception:
                continue

        if drawn_layer_count == 0:
            plt.close(fig)
            return "没有可绘制的要素：所选图层为空或无法转换"

        ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
        ax.set_xlabel("经度")
        ax.set_ylabel("纬度")
        ax.grid(True, alpha=0.3, linestyle="--")

        if show_north_arrow:
            try:
                xlim = ax.get_xlim()
                ylim = ax.get_ylim()
                nx = xlim[0] + (xlim[1] - xlim[0]) * 0.95
                ny = ylim[0] + (ylim[1] - ylim[0]) * 0.95
                arrow = FancyArrowPatch((nx, ny - 0.02), (nx, ny + 0.02),
                                        arrowstyle="->", color="black",
                                        linewidth=2, mutation_scale=15)
                ax.add_patch(arrow)
                ax.text(nx, ny + 0.03, "N", ha="center", fontsize=12, fontweight="bold")
            except Exception:
                pass

        if show_scale_bar:
            try:
                from pyproj import Geod

                xlim = ax.get_xlim()
                ylim = ax.get_ylim()
                sx = xlim[0] + (xlim[1] - xlim[0]) * 0.05
                sy = ylim[0] + (ylim[1] - ylim[0]) * 0.05
                width = (xlim[1] - xlim[0]) * 0.1
                ground_distance_km = abs(Geod(ellps="WGS84").inv(sx, sy, sx + width, sy)[2]) / 1000
                if ground_distance_km >= 1:
                    scale_label = f"{ground_distance_km:.0f} km"
                else:
                    ground_distance_m = ground_distance_km * 1000
                    scale_label = f"{ground_distance_m:.0f} m" if ground_distance_m >= 10 else f"{ground_distance_m:.2g} m"
                ax.plot([sx, sx + width], [sy, sy], "k-", linewidth=3)
                ax.text(sx + width / 2, sy + (ylim[1] - ylim[0]) * 0.01,
                        scale_label, ha="center", fontsize=9)
            except Exception:
                pass

        ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
        plt.tight_layout()

        out_dir = os.path.join(os.getcwd(), "cache", "charts")
        os.makedirs(out_dir, exist_ok=True)
        safe_output_name = os.path.basename(str(output_name or "static_map").replace("\\", "/"))
        safe_output_name = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]', '_', safe_output_name).strip(' .') or 'static_map'
        fname = f"{safe_output_name}.png"
        out_path = os.path.join(out_dir, fname)
        suffix = 2
        while True:
            try:
                reservation_fd = os.open(out_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
                os.close(reservation_fd)
                break
            except FileExistsError:
                fname = f"{safe_output_name}_{suffix}.png"
                out_path = os.path.join(out_dir, fname)
                suffix += 1
        try:
            fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="white")
        except Exception:
            plt.close(fig)
            try:
                os.remove(out_path)
            except OSError:
                pass
            raise
        plt.close(fig)

        record_tool_artifact(fname, out_path, artifact_type="image")

        _pending_images.append({
            "name": fname,
            "path": out_path,
            "url": f"/cache/charts/{fname}",
            "type": "png",
        })

        return f"静态地图已生成：{out_path}（{dpi} DPI，含{drawn_layer_count}个图层）"
    except Exception as e:
        return f"静态地图生成失败: {str(e)[:200]}"


@tool
def execute_workflow(workflow_json: str) -> str:
    """执行多步骤、有依赖关系的 GIS 分析工作流。
    - workflow_json: JSON 格式定义，含 name、description 及 nodes 列表。
      每个节点包含 id、name、tool(工具名)、inputs(参数字典，支持 ${node_id.output_key} 引用上游) 与 depends_on。
      若节点运行时注册了一个 GIS 图层，后续节点可通过 ${node_id.layer_name} 引用；注册多个时输出 layer_names。"""
    try:
        import json
        from backend.services.workflow import (
            new_workflow, validate_workflow, WorkflowExecutor
        )

        wf_data = json.loads(workflow_json)

        # LangGraph custom stream events let the chat surface Workflow's real node
        # progress while direct tool-panel invocations remain usable without a stream.
        stream_writer = None
        try:
            from langgraph.config import get_stream_writer
            stream_writer = get_stream_writer()
        except Exception:
            pass
        workflow_invocation_id = uuid.uuid4().hex[:12]
        workflow_name = str(wf_data.get("name") or "未命名工作流")[:120]
        workflow_nodes = {
            str(node.get("id")): node
            for node in wf_data.get("nodes", [])
            if isinstance(node, dict) and node.get("id") is not None
        }

        def publish_workflow_event(event):
            if not callable(stream_writer) or not isinstance(event, dict):
                return
            detail = dict(event)
            node = workflow_nodes.get(str(detail.get("node_id")), {})
            detail.setdefault("tool", node.get("tool", ""))
            try:
                stream_writer({
                    "type": "workflow_progress",
                    "invocation_id": workflow_invocation_id,
                    "workflow_name": workflow_name,
                    "event": detail,
                })
            except Exception:
                # Progress delivery is best-effort; it must not change GIS execution.
                pass

        # 保留工具对象本身，让 WorkflowExecutor 通过 invoke 调用并走完整记录链路。
        tool_registry = {}
        for t in tools:
            try:
                tool_registry[t.name] = t
            except Exception:
                pass

        def layer_snapshot():
            with _state_lock:
                return {
                    name: info.get("registration_token")
                    for name, info in _registered_layers.items()
                }

        # 校验
        errors = validate_workflow(wf_data, list(tool_registry.keys()))
        if errors:
            for node in wf_data.get("nodes", []):
                if not isinstance(node, dict):
                    continue
                node_id = node.get("id")
                node_errors = [error for error in errors if node_id and f"节点 {node_id} " in error]
                if node_errors:
                    publish_workflow_event({
                        "type": "workflow_node_failed", "node_id": node_id,
                        "name": node.get("name", ""), "tool": node.get("tool", ""),
                        "error": "; ".join(node_errors)[:500],
                    })
                else:
                    publish_workflow_event({
                        "type": "workflow_node_skipped", "node_id": node_id,
                        "name": node.get("name", ""), "tool": node.get("tool", ""),
                        "error": "工作流结构校验未通过，节点未执行",
                    })
            return "Workflow 校验失败：\n" + "\n".join(f"- {e}" for e in errors)

        # 创建 Workflow 对象
        wf = new_workflow(
            name=wf_data.get("name", "未命名工作流"),
            description=wf_data.get("description", ""),
            nodes=wf_data.get("nodes", []),
        )

        # 执行
        executor = WorkflowExecutor(
            tool_registry=tool_registry,
            register_layer_fn=_register_layer,
            event_callback=publish_workflow_event,
            failure_detector=_tool_result_failed,
            layer_snapshot_fn=layer_snapshot,
        )
        result = executor.execute(wf)

        # 生成摘要
        lines = [f"工作流「{result['name']}」执行完成，状态: {result['status']}"]
        for node in result["nodes"]:
            status_icon = {"success": "✓", "failed": "✗", "skipped": "⊘", "running": "⟳", "pending": "○"}.get(node["status"], "?")
            dur = f" ({node['duration']}s)" if node.get("duration") else ""
            lines.append(f"  {status_icon} {node['name']} [{node['tool']}] - {node['status']}{dur}")
            if node.get("error"):
                lines.append(f"    错误: {node['error'][:100]}")

        return "\n".join(lines)

    except json.JSONDecodeError as e:
        return f"Workflow JSON 解析失败: {str(e)}"
    except Exception as e:
        return f"Workflow 执行失败: {str(e)[:200]}"


@tool
def materialize_workflow(workflow_name: str = "") -> str:
    """【执行实录沉淀】将当前任务（或最近一次分析会话）中真实成功跑通的工具链，自动提取并物化为可调参、可复现的 DAG 工作流文件。

    【适用场景】
    - 用户完成了一次复杂的多轮空间分析（如：查边界 → 做缓冲区 → 叠置分析 → 导出统计图表），希望将其实录固化为标准工作流资产；
    - 以后更换地点或参数时，可直接重用该 DAG。

    【参数】
    workflow_name: 可选，工作流名称。留空时自动根据当前任务命名。

    【返回】
    物化结果说明及工作流保存路径。
    """
    try:
        from backend.services.workflow import materialize_from_history, save_workflow
        tid = runtime.get_current_task_id() or _current_task_id or ""
        if not tid:
            return "当前会话暂无活跃的任务记录，请先执行至少一次 GIS 分析操作。"

        wf = materialize_from_history(tid, workflow_name=workflow_name)
        if not wf or not wf.get("nodes"):
            return f"任务 {tid} 中未找到成功的工具执行记录，无法物化工作流。"

        save_dir = os.path.join(_temp_output_dir, "workflows")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"{wf['id']}.giswork"
        filepath = os.path.join(save_dir, filename)

        if save_workflow(wf, filepath):
            node_summaries = [f"  {i+1}. {n['name']} (工具: {n['tool']})" for i, n in enumerate(wf["nodes"])]
            nodes_text = "\n".join(node_summaries)
            return (
                f"已成功从真实执行历史中物化 DAG 工作流！\n"
                f"工作流名称：{wf['name']}\n"
                f"包含节点（{len(wf['nodes'])}个）：\n{nodes_text}\n"
                f"保存路径：{filepath}\n"
                f"后续可通过 execute_workflow 工具或前端工作流面板直接复用/重算。"
            )
        else:
            return "工作流物化生成成功，但保存到磁盘时失败。"
    except Exception as e:
        return f"物化工作流失败: {str(e)[:200]}"


@tool
def query_spatial_sql(sql: str, result_layer_name: str = "") -> str:
    """使用标准 SQL (SELECT/WITH) 对当前已加载图层属性与要素进行极速只读查询与透视。
    表名为图层名。若包含几何或使用 SELECT *，自动将结果要素渲染为高亮新图层上图。
    - sql: 标准只读 SQL 语句。
    - result_layer_name: 可选，生成结果图层的自定义名称。
    - 查询执行上限 10 秒，结果上限 10 万行或 32 MB；超限会明确返回错误。"""
    try:
        from backend.services.sql_engine import execute_layer_sql
        res = execute_layer_sql(sql, _registered_layers, create_result_layer=True)
        if not res.get("ok"):
            return f"SQL 查询未通过: {res.get('error')}"

        out_lines = [f"**SQL 执行成功**（返回 {res['row_count']} 条记录）：\n"]
        out_lines.append(res.get("markdown_table", ""))

        # 若生成了衍生图层，自动推送到地图
        derived_geojson = res.get("derived_geojson")
        if derived_geojson and derived_geojson.get("features"):
            clean_result_name = result_layer_name.strip() if isinstance(result_layer_name, str) else ""
            base_layer_name = clean_result_name or f"SQL过滤结果_{len(derived_geojson['features'])}条"
            layer_name = _disambiguate_layer_name(base_layer_name)
            style = {
                "color": "#e11d48",
                "fillColor": "#fb7185",
                "fillOpacity": 0.4,
                "weight": 2
            }
            provenance = {"tool": "query_spatial_sql", "sql": sql}
            _push_layer(layer_name, derived_geojson, style=style, provenance=provenance)
            _register_layer(layer_name, derived_geojson, provenance=provenance)
            out_lines.append(f"\n✨ 已将包含空间几何的 {len(derived_geojson['features'])} 个要素自动加载为新图层「{layer_name}」！")

        return "\n".join(out_lines)
    except Exception as e:
        return f"SQL 查询执行异常: {str(e)[:200]}"


# Re-exported from backend.services.tool_modules.terrain: get_elevation_data


def _resolve_layer_name(name: str) -> str:
    """Resolve only exact registered names; partial names are unsafe for multi-layer operations."""
    if not isinstance(name, str) or not name.strip():
        return ""
    name = name.strip()
    return name if name in _registered_layers else ""


# ============================================================
# 工具: 云原生格式流式加载（COG / PMTiles / GeoParquet / FlatGeobuf）
# 实现细节在 cloud_native.py，此处只做 @tool 包装与上图通道
# ============================================================
# Re-exported from backend.services.tool_modules.raster: load_cog, get_cog_info


@tool
def load_pmtiles(source: str, layer_name: str = "", max_features: int = 5000) -> str:
    """流式加载 PMTiles（本地路径或 http(s) URL）并上图。
    矢量 PMTiles：解析 MVT 瓦片转为 GeoJSON 图层；栅格 PMTiles：取中心瓦片叠加。
    source: 本地 .pmtiles 路径或 URL；layer_name: 图层名；max_features: 最多解码要素数（默认 5000）。
    用户给了一个 .pmtiles 地址要求"加载到地图"时调用。"""
    from backend.services import cloud_native as cn
    from backend.services.url_security import sanitize_error_text
    init_temp_dir()
    src = str(source).strip()
    parsed_source = urllib.parse.urlsplit(src)
    display_source = parsed_source.path if parsed_source.scheme.lower() in {"http", "https"} else src
    name = (layer_name or os.path.splitext(os.path.basename(display_source))[0]).strip() or "PMTiles图层"
    try:
        header = cn.pmtiles_header(src)
        _tt = header.get("tile_type", 0)
        tile_type = int(_tt.value) if hasattr(_tt, "value") else int(_tt)
        if tile_type == 1:  # MVT 矢量
            geojson, info = cn.pmtiles_vector_to_geojson(src, max_features=max_features)
            _push_layer(name, geojson, {"color": "#2b6cb0", "weight": 1.5})
            _register_layer(name, geojson)
            return (
                f"已加载矢量 PMTiles「{name}」: {info['feature_count']} 个要素"
                f"（z={info['zoom_sampled']} 采样 {info['tiles_sampled']} 块瓦片），"
                f"图层: {', '.join(info['layers'])}，范围 {info['bounds_wgs84']}"
            )
        # 栅格 PMTiles：中心瓦片叠加
        tile_bytes, bounds, fmt, info = cn.pmtiles_raster_tile_bounds(src)
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|]', "_", name)
        tile_name = f"pmtiles_{safe}_{int(time.time())}.{fmt}"
        with open(os.path.join(upload_dir, tile_name), "wb") as f:
            f.write(tile_bytes)
        _pending_layer_ops.append({
            "action": "dem_result", "name": tile_name,
            "url": f"/output/uploads/{tile_name}",
            "bounds": [float(v) for v in bounds],
            "label": f"PMTiles 栅格瓦片: {name} (z={info['center'][2]})",
        })
        return (
            f"已加载栅格 PMTiles「{name}」中心瓦片并叠加（z={info['center'][2]}，"
            f"范围 {info['bounds_wgs84']}，max_zoom={info['max_zoom']}）。"
            "提示：栅格 PMTiles 全量浏览需前端瓦片渲染，此处先以采样瓦片预览"
        )
    except cn.CloudNativeError as e:
        return f"加载失败: {sanitize_error_text(e, src)}"
    except Exception as e:
        return f"加载异常: {sanitize_error_text(e, src)}"


def _load_cloud_vector_tool(source: str, fmt: str, layer_name: str, bbox: str, limit: int) -> str:
    """load_geoparquet / load_flatgeobuf 共用实现"""
    from backend.services import cloud_native as cn
    from backend.services.url_security import sanitize_error_text
    try:
        bbox_tuple = cn.parse_bbox(bbox)
    except cn.CloudNativeError as e:
        return f"参数错误: {e}"
    # cloud_vector_to_geojson 内部会先读 metadata 并做超限拒绝，
    # 这里不再单独预读，避免下载回退场景重复拉取同一文件
    try:
        geojson, meta2 = cn.cloud_vector_to_geojson(source, fmt, bbox=bbox_tuple, limit=limit)
    except cn.CloudNativeError as e:
        return sanitize_error_text(e, source)
    except Exception as e:
        return sanitize_error_text(e, source)
    parsed_source = urllib.parse.urlsplit(str(source))
    display_source = parsed_source.path if parsed_source.scheme.lower() in {"http", "https"} else str(source)
    name = (layer_name or os.path.splitext(os.path.basename(display_source))[0]).strip() or fmt
    _push_layer(name, geojson, {"color": "#388e3c", "weight": 1.5})
    _register_layer(name, geojson)
    crs_note = f"，几何已从 {meta2['crs']} 重投影到 WGS84" if meta2.get("geometry_reprojected") else ""
    extra = f"，bbox 过滤 {meta2['bbox_filtered']}" if meta2.get("bbox_filtered") else ""
    return (
        f"已加载 {fmt}「{name}」: 全库 {meta2['features']} 要素，本次载入 {meta2['loaded_features']} 个"
        f"{extra}，CRS {meta2['crs']}{crs_note}，"
        f"字段: {', '.join(meta2['fields'][:10]) or '无'}"
    )


@tool
def load_geoparquet(source: str, layer_name: str = "", bbox: str = "", limit: int = 0) -> str:
    """流式加载 GeoParquet（本地路径或 http(s) URL）并上图。
    大文件先读 metadata 提示要素数；超过上限时需用 bbox="minx,miny,maxx,maxy" 空间过滤或减小 limit。
    用户给了 .parquet/.geoparquet 地址要求"加载到地图"时调用。"""
    return _load_cloud_vector_tool(source, "GeoParquet", layer_name, bbox, int(limit))


@tool
def load_flatgeobuf(source: str, layer_name: str = "", bbox: str = "", limit: int = 0) -> str:
    """流式加载 FlatGeobuf（本地路径或 http(s) URL）并上图。
    大文件先读 metadata 提示要素数；超过上限时需用 bbox="minx,miny,maxx,maxy" 空间过滤或减小 limit。
    用户给了 .fgb 地址要求"加载到地图"时调用。"""
    return _load_cloud_vector_tool(source, "FlatGeobuf", layer_name, bbox, int(limit))


# ============================================================
# 工具: 分区统计 / 长度字段 / 多部件分解 / 几何互转 / 栅格重采样 / 栅格重投影
# （对标 GeoLibre 工具分类补齐：Raster zonal stats、Vector cleaning/conversion、Projection）
# ============================================================

# Re-exported from backend.services.tool_modules.raster: zonal_statistics


@tool
def add_length_field(layer_name: str, field_name: str = "length_km") -> str:
    """为线/面图层添加长度字段：每个要素的几何长度（千米，UTM 精确投影计算），
    结果作为新图层上图。面积量测用 measure_area，本工具补逐要素长度统计。"""
    gdf, name = _layer_to_gdf(layer_name)
    if gdf is None:
        return name
    try:
        utm = gdf.estimate_utm_crs()
        if utm is None:
            return "无法估算 UTM 投影带（图层范围异常）"
        projected = gdf.to_crs(utm)
        lengths_km = projected.geometry.length / 1000.0
        out = gdf.copy()
        out[field_name] = [round(float(v), 4) for v in lengths_km]
        with _state_lock:
            out_name = _disambiguate_layer_name(f"{name}_带长度")
            _gdf_to_layer(out, out_name)
        return (f"已添加字段「{field_name}」（单位 km，UTM {utm.to_string()} 计算）："
                f"总长 {lengths_km.sum():.2f} km，最长 {lengths_km.max():.2f} km，"
                f"结果图层「{out_name}」已上图")
    except Exception as e:
        return f"添加长度字段失败: {str(e)[:300]}"


# Re-exported from backend.services.tool_modules: spatial_explode, geometry_convert, raster_resample, raster_reproject


# ============================================================
# 工具: create_swipe / close_swipe — 卷帘对比
# ============================================================

@tool
def create_swipe(left_layer: str, right_layer: str, orientation: str = "vertical") -> str:
    """开启卷帘对比（Swipe）：将两个已有图层置为分割对比模式，前端出现可拖动分割线。
    left_layer 显示在分割线一侧，right_layer 显示在另一侧。
    orientation: vertical（竖直分割线，左=left_layer 右=right_layer，默认）或 horizontal（水平分割线，上=left_layer 下=right_layer）。
    用户说"卷帘对比/左右对比/滑动对比两个图层"时调用。"""
    lname = _resolve_layer_name(left_layer)
    rname = _resolve_layer_name(right_layer)
    if not lname:
        _names = "、".join(list(_registered_layers.keys())[:8]) or "无"
        return f"未找到图层「{left_layer}」，当前图层：{_names}"
    if not rname:
        _names = "、".join(list(_registered_layers.keys())[:8]) or "无"
        return f"未找到图层「{right_layer}」，当前图层：{_names}"
    if lname == rname:
        return "卷帘对比需要两个不同的图层"
    _o = str(orientation).strip().lower()
    orient = "horizontal" if (_o.startswith("h") or "横" in _o or "上下" in _o or "水平" in _o) else "vertical"
    _pending_layer_ops.append({
        "action": "swipe", "left": lname, "right": rname, "orientation": orient,
    })
    side = "上下" if orient == "horizontal" else "左右"
    return f"已开启卷帘对比（{side}分割）：{lname} | {rname}。拖动地图上的分割线查看，说\"关闭卷帘\"退出。"


@tool
def close_swipe() -> str:
    """关闭卷帘对比模式，恢复所有图层完整显示。用户说"关闭卷帘/退出对比/恢复正常显示"时调用。"""
    _pending_layer_ops.append({"action": "swipe_close"})
    return "已关闭卷帘对比，恢复所有图层完整显示"


# ============================================================
# 工具: list_history / rerun_history — 处理历史与重跑
# ============================================================

@tool
def list_history(limit: int = 20) -> str:
    """查看处理历史：最近执行过的工具记录（工具名、参数、时间、产物图层、成败），按时间倒序。
    每条带历史编号 index，用户说"重跑第 N 条"时把该编号传给 rerun_history。"""
    from backend.services.history_service import list_entries
    entries = list_entries(limit)
    from backend.services.history_service import get_storage_warning
    warning = get_storage_warning()
    if warning:
        return warning + ("\n\n" if entries else "") + ("\n".join(
            f"#{e['index']} [{e['time']}] {e['tool']} → {'成功' if e.get('ok') else '失败'}"
            for e in entries
        ) if entries else "当前进程内没有可展示的历史记录。")
    if not entries:
        return "暂无处理历史。执行任意工具后即可在此查看。"
    lines = [f"== 处理历史（最近 {len(entries)} 条，倒序） =="]
    for e in entries:
        status = "成功" if e.get("ok") else f"失败({e.get('error', '')[:50]})"
        layers = ", ".join(e.get("layer_ids", [])) or "无图层产物"
        args_brief = json.dumps(e.get("args", {}), ensure_ascii=False)
        if len(args_brief) > 120:
            args_brief = args_brief[:120] + "..."
        rerun_tag = f" [重跑自 #{e['rerun_of']}]" if e.get("rerun_of") else ""
        lines.append(
            f"#{e['index']} [{e['time']}] {e['tool']}{rerun_tag} → {status}（{e.get('duration_ms', 0)}ms）\n"
            f"   参数: {args_brief}\n"
            f"   产物图层: {layers}"
        )
    return "\n".join(lines)


@tool
def rerun_history(index: int) -> str:
    """按历史编号重跑一次工具：用原始参数重新调用，产物作为新图层上图，不覆盖原图层。
    编号通过 list_history 查看。用户说"重跑/再来一次/重复上一步"时调用。"""
    from backend.services import history_service as _hs
    entry = _hs.get_entry(int(index))
    if not entry:
        return f"未找到编号 {index} 的历史记录，请先用 list_history 查看可用编号"
    tool_name = entry.get("tool", "")
    if tool_name in ("list_history", "rerun_history"):
        return "历史类工具本身不支持重跑"
    tool_obj = _TOOL_REGISTRY.get(tool_name)
    if tool_obj is None:
        return f"工具「{tool_name}」已不存在（可能已更名），无法重跑"
    # 防覆盖：重跑前快照注册表（浅引用，_register_layer 整体替换条目时即可识别），
    # 重跑后被同名覆盖的旧图层以「_原」后缀重新注册保留
    snapshot = dict(_registered_layers)
    _t0 = time.time()
    previous_raster_scope = getattr(_raster_output_scope, "value", None)
    _raster_output_scope.value = os.path.join("history-reruns", uuid.uuid4().hex)
    try:
        try:
            out = tool_obj.invoke(entry.get("args") or {})
            ok = not _tool_result_failed(tool_name, out)
            err = "" if ok else str(out)[:200]
        except Exception as e:
            out = f"重跑失败: {str(e)[:200]}"
            ok, err = False, str(e)
    finally:
        if previous_raster_scope is None:
            try:
                del _raster_output_scope.value
            except AttributeError:
                pass
        else:
            _raster_output_scope.value = previous_raster_scope
    new_layers = [n for n, info in _registered_layers.items()
                  if n not in snapshot or info is not snapshot[n]]
    restored = []
    for name, old in snapshot.items():
        if name in _registered_layers and _registered_layers[name] is not old:
            suffix_name = f"{name}_原"
            seq = 1
            while suffix_name in _registered_layers:
                seq += 1
                suffix_name = f"{name}_原{seq}"
            if isinstance(old.get("raster"), dict):
                old_raster = copy.deepcopy(old["raster"])
                token = _register_raster_layer(
                    suffix_name, old_raster, source_path=old.get("raster_source_path"),
                )
                preserved = _registered_layers[suffix_name]
                for key in ("group_name", "provenance", "style"):
                    if key in old:
                        preserved[key] = copy.deepcopy(old[key])
                restored_raster_op = {
                    "action": "dem_result",
                    "name": f"{suffix_name}.png",
                    "url": old_raster.get("url"),
                    "bounds": old_raster.get("bounds"),
                    "label": old_raster.get("processing") or "历史栅格结果",
                    "layer_name": suffix_name,
                    "raster": old_raster,
                    "registration_token": token,
                    "crs": old_raster.get("crs"),
                }
                # Replaying a raster operation fits the map to every image.
                # Restore the old layer before its replacement so the final
                # viewport remains focused on the newly generated result.
                insert_at = next((index for index, op in enumerate(_pending_layer_ops)
                                  if op.get("action") == "dem_result"
                                  and op.get("layer_name") == name), len(_pending_layer_ops))
                _pending_layer_ops.insert(insert_at, restored_raster_op)
            else:
                _register_layer(suffix_name, old.get("geojson", {}))
            restored.append(suffix_name)
    _hs.record(
        tool_name, entry.get("args") or {}, ok, new_layers,
        task_id=get_current_task_id(), error=err,
        duration_ms=int((time.time() - _t0) * 1000), rerun_of=int(index),
    )
    status = "成功" if ok else "失败"
    parts = [f"已重跑 #{index} {tool_name} → {status}"]
    if new_layers:
        parts.append(f"新图层: {'、'.join(new_layers)}（作为新图层上图）")
    if restored:
        parts.append(f"原图层已保留: {'、'.join(restored)}")
    if not ok:
        parts.append(str(out)[:200])
    return "；".join(parts)


# Re-exported from backend.services.tool_modules.terrain: _write_dem_preview


# ============================================================
# 工具: URL 空间数据智能探测、按需提取与分析 (URL-Driven GIS Data Tools)
# ============================================================

@tool
def inspect_gis_url(url: str) -> str:
    """智能探测指定 URL 的 GIS 服务或空间数据类型，提取图层列表、CRS 坐标系、字段元数据、要素量级与范围。
    支持 ArcGIS REST (MapServer/FeatureServer)、OGC (WFS/WMS/WMTS)、GeoJSON、GeoParquet、FlatGeobuf、PMTiles、COG、Shapefile ZIP、CSV。
    只读取并返回结构化元数据报告，不强制自动上图。用户提供在线 GIS 服务/数据链接或问"这个链接是什么数据"时调用。"""
    from backend.services import url_gis_service as ugs
    from backend.services.url_security import sanitize_error_text, sanitize_http_url
    try:
        info = ugs.inspect_gis_url(url)
    except ugs.UrlGisError as e:
        return f"探测失败: {sanitize_error_text(e, url)}"
    except Exception as e:
        return f"探测异常: {sanitize_error_text(e, url)[:300]}"

    stype = info.get("service_type", "未知")
    lines = [
        f"== GIS 资源探测报告: {sanitize_http_url(info.get('url', url))[:120]} ==",
        f"服务/数据类型: {stype}",
    ]
    if info.get("service_name"):
        lines.append(f"服务名称: {info['service_name']}")
    if info.get("crs"):
        lines.append(f"坐标系 (CRS): {info['crs']}")
    if info.get("bbox"):
        lines.append(f"空间范围 (BBox): {info['bbox']}")
    if info.get("feature_count") is not None:
        lines.append(f"要素总量: {info['feature_count']}")
    if info.get("layer_count") is not None:
        lines.append(f"包含图层数: {info['layer_count']}")
    if info.get("layers"):
        lines.append("子图层列表:")
        for l in info["layers"][:10]:
            lname = l.get("name") or l.get("title") or l.get("identifier") or str(l)
            lid = f" (ID: {l['id']})" if "id" in l else ""
            lines.append(f"  - {lname}{lid}")
        if len(info["layers"]) > 10:
            lines.append(f"  ... 剩余 {len(info['layers']) - 10} 个图层")
    if info.get("fields"):
        f_names = [f["name"] if isinstance(f, dict) else str(f) for f in info["fields"][:15]]
        lines.append(f"字段列表 ({info.get('field_count', len(f_names))} 个): {', '.join(f_names)}")
    if info.get("sample_records"):
        lines.append(f"数据样本 (前 {len(info['sample_records'])} 条): {json.dumps(info['sample_records'][:2], ensure_ascii=False)}")
    if info.get("description"):
        lines.append(f"描述: {info['description'][:200]}")

    return "\n".join(lines)


@tool
def fetch_gis_data_url(
    url: str,
    layer_id: str = "",
    bbox: str = "",
    where: str = "1=1",
    limit: int = 1000,
    output_format: str = "geojson",
    output_filename: str = "",
    auto_render: bool = False,
    mode: str = "preview",
    max_features: int = 100000,
) -> str:
    """从 GIS URL 获取矢量数据并落盘；ArcGIS REST 支持限量预览和对象 ID 校验的完整获取。
    - url: 在线服务或文件地址；layer_id: 子图层 ID/名称；bbox: 空间范围过滤 'minx,miny,maxx,maxy'。
    - where: 属性过滤条件；limit: 最大要素数(默认 1000)；output_format: geojson(默认)/gpkg/csv。
    - auto_render: 是否同时渲染上图(默认 False)；mode: preview(限量)/full(ArcGIS REST 完整获取)。
    - max_features: full 模式资源上限(默认 100000，最大 1000000)。"""
    from backend.services import url_gis_service as ugs
    from backend.services.url_security import sanitize_error_text
    try:
        res = ugs.fetch_gis_data_url(
            url=url,
            layer_id=layer_id,
            bbox=bbox,
            where=where,
            limit=limit,
            output_format=output_format,
            output_filename=output_filename,
            mode=mode,
            max_features=max_features,
        )
    except ugs.UrlGisError as e:
        return f"数据抓取失败: {sanitize_error_text(e, url)}"
    except Exception as e:
        return f"数据抓取异常: {sanitize_error_text(e, url)[:300]}"

    if not res.get("file_path"):
        return f"未抓取到有效要素: {res.get('message', '返回要素为 0')}"

    file_path = res["file_path"]
    count = res["feature_count"]
    fields = res.get("fields", [])
    crs = res.get("crs", "EPSG:4326")
    orig_crs = res.get("original_crs", "")
    crs_str = f"{crs} (原始 {orig_crs})" if orig_crs and orig_crs != crs else crs

    # 若指定 auto_render=True，则上图
    render_msg = ""
    if auto_render and res.get("file_format") == "geojson":
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                gj_content = json.load(f)
            layer_name = res.get("file_name", "URL_Data").replace(".geojson", "")
            _push_layer(layer_name, gj_content, {"color": "#1976d2", "weight": 1.5})
            _register_layer(layer_name, gj_content)
            render_msg = f"，已同步渲染到地图图层「{layer_name}」"
        except Exception as e:
            render_msg = f"（自动上图跳过: {e}）"

    return (
        f"数据提取成功！\n"
        f"- 来源类型: {res.get('service_type')}\n"
        f"- 要素数量: {count} 个\n"
        f"- 获取模式: {res.get('mode', 'preview')}；完整性: {res.get('completeness', 'unknown')}（{res.get('completeness_reason', '')}）\n"
        f"- 坐标系: {crs_str}\n"
        f"- 空间范围 (BBox): {res.get('bbox')}\n"
        f"- 包含字段 ({len(fields)} 个): {', '.join(fields[:10])}\n"
        f"- 本地保存路径: {file_path} ({round(res.get('file_size_bytes', 0) / 1024, 1)} KB){render_msg}\n"
        f"- 检查报告: {res.get('report_path', '')}\n"
        f"- 获取配方: {res.get('recipe_path', '')}\n"
        f"- SHA-256: {res.get('sha256', '')}\n"
        f"- 样例属性: {json.dumps(res.get('sample_records', [])[:2], ensure_ascii=False)}"
    )


# ============================================================
# 工具: 全球开放地理实体与 OSM 矢量抓取 (Global Geospatial Tools)
# ============================================================

@tool
def search_global_entities(query: str, lang: str = "zh") -> str:
    """全球开放地理实体与维基百科知识图谱检索（免 Key、全球覆盖）。
    检索全球任意国家、山川河流、地标名胜、岛屿、行政区划，提取 Wikidata 经纬度坐标、实体定义与维基百科简介。
    用户查询全球地理实体或问"XX 在哪里/XX 的百科信息"时调用。"""
    from backend.services import global_geo_service as ggs
    try:
        results = ggs.search_wikidata_entities(query, lang=lang, limit=5)
        if not results:
            return f"未能找到与「{query}」相关的全球地理实体"
        if "error" in results[0]:
            return f"检索失败: {results[0]['error']}"

        lines = [f"== 全球地理实体与百科知识: {query} =="]
        for idx, item in enumerate(results, 1):
            coords_str = f"{item['coordinates'][0]}, {item['coordinates'][1]}" if item.get("coordinates") else "无明确点位"
            lines.append(f"{idx}. {item['name']} ({item['qid']})")
            if item.get("description"):
                lines.append(f"   简介: {item['description']}")
            lines.append(f"   坐标: {coords_str}")
            if item.get("wikipedia_summary"):
                lines.append(f"   百科摘要: {item['wikipedia_summary'][:150]}...")
            if item.get("wikipedia_url"):
                lines.append(f"   条目链接: {item['wikipedia_url']}")
        return "\n".join(lines)
    except Exception as e:
        return f"查询异常: {str(e)[:250]}"


@tool
def fetch_osm_boundary_or_features(query: str, feature_type: str = "boundary", bbox: str = "", limit: int = 200, auto_render: bool = True) -> str:
    """全球开放街道地图（OSM）行政区划多边形边界与矢量要素极速抽取（免 Key）。
    query: 地名（如 'Taiwan', 'Tokyo', 'Paris'）；feature_type: boundary（行政边界）/ roads（道路网）/ buildings（建筑物）/ water（水系）；
    bbox: 可选空间范围；limit: 要素上限；auto_render: 是否自动上图（默认 True）。
    用户需要拉取全球任意区域边界或 OSM 矢量时调用。"""
    from backend.services import global_geo_service as ggs
    try:
        init_temp_dir()
        ft = str(feature_type).lower().strip()
        layer_name = f"OSM_{query}_{ft}"

        if ft in ("boundary", "border", "行政区", "边界"):
            items = ggs.search_osm_nominatim(query, fetch_polygon=True, limit=1)
            if not items or "error" in items[0]:
                return f"未找到「{query}」的 OSM 边界多边形"
            item = items[0]
            gj = item.get("geojson")
            if not gj:
                return f"「{query}」仅查到点位坐标 {item.get('coordinates')}，无面要素边界"

            fc = {"type": "FeatureCollection", "features": [{
                "type": "Feature",
                "geometry": gj,
                "properties": {"name": item.get("name"), "display_name": item.get("display_name"), "source": "OpenStreetMap"}
            }]}
            if auto_render:
                _push_layer(layer_name, fc, {"color": "#0284c7", "fillColor": "#0284c7", "fillOpacity": 0.1, "weight": 2})
                _register_layer(layer_name, fc)
            return f"成功获取「{item.get('name')}」OSM 行政区划边界！已生成图层「{layer_name}」，范围 BBox: {item.get('bbox')}"

        # Overpass 区域矢量提取
        if not bbox:
            # 先用 Nominatim 取该区域 bbox
            items = ggs.search_osm_nominatim(query, fetch_polygon=False, limit=1)
            if items and items[0].get("bbox"):
                b = items[0]["bbox"]
                bbox = f"{b[0]},{b[1]},{b[2]},{b[3]}"
            else:
                return f"需要提供 bbox 范围才能提取「{query}」的 {ft} 要素"

        res = ggs.query_osm_overpass(query_type=ft, bbox=bbox, limit=limit)
        fc = res.get("geojson", {})
        count = res.get("feature_count", 0)
        if count == 0:
            return f"在 {query} 范围内未检索到 {ft} 矢量要素"

        if auto_render:
            _push_layer(layer_name, fc, {"color": "#16a34a", "weight": 1.5})
            _register_layer(layer_name, fc)
        return f"成功提取 OSM {ft} 矢量要素共 {count} 个，已生成图层「{layer_name}」"
    except Exception as e:
        return f"OSM 抓取异常: {str(e)[:300]}"


# Re-exported from backend.services.tool_modules: raster_reclassify .. metro_line (21 tools)


tools = [
    search_web,
    fetch_webpage,
    scrape_page,
    search_platform,
    save_file,
    execute_python,
    amap_poi_search,
    amap_geocode,
    cn_aoi_search,
    cn_aoi_extract,
    get_registered_layers,
    list_layers,
    get_layer_detail,
    datav_boundary,
    drill_down,
    drill_up,
    visualize_3d,
    create_heatmap,
    field_calculate,
    measure_area,
    measure_distance,
    clear_layers,
    get_session_logs,
    login_gscloud,
    layer_control,
    focus_map,
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
    nearest_pair,
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
    spatial_moran,
    spatial_hotspot,
    spatial_kde,
    calc_spectral_index,
    ndwi_analysis,
    ndbi_analysis,
    evi_analysis,
    ndmi_analysis,
    generate_analysis_report,
    spatial_fix_geometry,
    spatial_check_duplicates,
    ask_user_choice,
    fetch_weather_data,
    fetch_earthquake_data,
    inspect_satellite_image,
    generate_static_map,
    execute_workflow,
    materialize_workflow,
    query_spatial_sql,
    get_elevation_data,
    create_swipe,
    close_swipe,
    list_history,
    rerun_history,
    load_cog,
    get_cog_info,
    load_pmtiles,
    load_geoparquet,
    load_flatgeobuf,
    zonal_statistics,
    add_length_field,
    spatial_explode,
    geometry_convert,
    raster_resample,
    raster_reproject,
    search_gis_services,
    get_gis_service_detail,
    get_gis_services_stats,
    inspect_gis_url,
    fetch_gis_data_url,
    search_global_entities,
    fetch_osm_boundary_or_features,
    raster_reclassify,
    raster_focal_stats,
    euclidean_distance,
    raster_extract_by_mask,
    surface_volumes,
    join_field,
    geometry_attributes,
    minimum_bounding_geometry,
    points_to_line,
    generate_points_along_lines,
    spatial_weights_matrix,
    spatial_regression,
    directional_distribution,
    central_tendency,
    od_cost_matrix,
    feature_to_raster,
    raster_to_feature,
    create_fishnet,
    cost_distance,
    least_cost_path,
    metro_line,
]

# ============================================================
# 工具执行历史：在 tools 列表出口统一包装记录（工具本体零侵入）
# Agent 链路经由此列表调用工具 → 每次执行自动记录到 history_service
# _TOOL_REGISTRY 保留未包装原件，rerun_history 用它按原始参数重跑
# ============================================================
from backend.services import history_service as _history_svc
from langchain_core.tools import StructuredTool as _StructuredTool

_TOOL_REGISTRY = {t.name: t for t in tools}

_TOOL_FAILURE_MARKERS = {
    "query_spatial_sql": ("SQL 查询未通过:", "SQL 查询执行异常:"),
    "spatial_buffer": ("工具执行失败:", "缓冲区分析失败:", "找到多个匹配：", "未找到图层"),
    "export_layer": ("工具执行失败:", "GeoJSON导出验证失败:", "找到多个匹配：", "未找到图层", "不支持的格式:"),
    "datav_boundary": ("工具执行失败:", "找到多个匹配：", "未找到", "获取失败:", "查询失败:"),
    "get_layer_detail": ("未找到图层", "找到多个匹配："),
    "create_heatmap": ("图层 ", "热力图半径范围为", "没有点要素", "权重字段「", "没有可用于生成热力图的点",
                        "热力图渐变格式无效", "热力图渐变参数无效", "热力图生成失败:"),
    "search_platform": ("平台「", "B站搜索出错："),
    "amap_poi_search": ("搜索半径必须是", "中心点坐标无效", "已尝试 OSM，但在", "OSM 回退也失败："),
    "amap_geocode": ("高德 API Key 未配置", "未找到「"),
    "scrape_page": ("未找到匹配",),
    "add_labels": ("标注失败:",),
    "add_field": (
        "图层「", "字段名不能为空", "字段名「", "不支持字段类型", "默认值「",
        "浮点字段默认值必须", "添加字段失败:",
    ),
    "measure_area": ("未找到图层", "找到多个匹配："),
    "create_chart": (
        "图表生成失败：", "未找到图层", "找到多个匹配：", "图层没有要素", "图层没有属性字段",
    ),
    "move_features": ("不支持的单位", "位移量 dx 和 dy 不能同时为 0"),
    "focus_map": (
        "未找到图层", "center 格式应为", "无法解析坐标：", "坐标范围无效", "请提供 layer_name",
    ),
    "visualize_3d": ("图层 ",),
    "measure_distance": ("输入坐标必须是有限数值", "输入坐标超出 WGS-84 范围"),
    "draw_feature": (
        "不支持的几何类型：", "未提供有效坐标", "无法解析坐标", "Rectangle 需要",
        "Rectangle 对角线两点不能", "Circle 需要", "Circle 半径必须", "Circle 半径超出",
        "Circle 圆心纬度必须",
    ),
    "execute_workflow": ("Workflow JSON 解析失败:", "Workflow 执行失败:"),
    "materialize_workflow": (
        "当前会话暂无活跃的任务记录",
        "未找到成功的工具执行记录",
        "工作流物化生成成功，但保存到磁盘时失败。",
        "物化工作流失败:",
    ),
    "generate_static_map": ("静态地图 DPI 范围为", "指定图层不存在：", "没有可绘制的图层", "没有可绘制的要素："),
    "export_map": ("不支持的图片格式：",),
    "export_pdf": ("PDF 出图失败:",),
    "create_swipe": ("未找到图层", "卷帘对比需要两个不同的图层"),
    "spatial_graduated_colors": ("分级色彩渲染失败:", "图层「", "不是数值类型", "无有效数值", "不支持该分级方法", "无法分级", "找到多个匹配"),
    "spatial_unique_values": ("唯一值渲染失败:", "未找到图层", "找到多个匹配", "图层「", "字段「"),
    "raster_focal_stats": ("未找到栅格文件", "窗口大小", "未知统计量", "没有有效像元"),
    "layer_control": ("未知操作:", "未找到图层"),
}


def _tool_result_failed(tool_name, result):
    """统一识别以普通返回值表达的工具失败。"""
    if isinstance(result, dict) and result.get("ok") is False:
        return True
    if not isinstance(result, str):
        return False
    text = result.strip()
    if re.match(r"^(?:失败|错误|异常)[:：]", text):
        return True
    if re.match(r"^[^\s:：]{1,30}(?:失败|错误|异常)[:：]", text):
        return True
    if text.startswith("{"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("ok") is False:
                return True
        except (TypeError, ValueError):
            pass
    generic_markers = ("工具执行失败:", "执行失败:", "查询失败:", "获取失败:")
    markers = generic_markers + _TOOL_FAILURE_MARKERS.get(tool_name, ())
    return any(text.startswith(marker) for marker in markers)


def _recorded(t):
    """包装一个工具：执行后把 名称/参数/成败/产物图层 写入处理历史"""
    def _run_and_record(**kwargs):
        from backend.services.ai_service import is_current_request_cancelled
        if is_current_request_cancelled():
            return "用户已取消，工具未执行。"
        _t0 = time.time()
        _before = dict(_registered_layers)
        _run_id = get_current_run_id()
        _files_before = set()
        if _run_id:
            try:
                from backend.services import storage_service as _ss
                _files_before = {a.get("artifact_id") for a in (_ss.get_run_artifacts(_run_id) or [])}
            except Exception:
                pass
        _style_action = t.name == "spatial_graduated_colors" or (
            t.name == "layer_control" and kwargs.get("action") in {"set_color", "set_style"}
        )
        _is_gis_op = t.name in {"spatial_buffer", "export_layer", "datav_boundary"} or _style_action
        try:
            out = t.invoke(kwargs)
            _err = ""
            _ok = not _tool_result_failed(t.name, out)
            if not _ok:
                _err = str(out)[:300]
        except Exception as e:
            out = f"工具执行失败: {str(e)[:300]}"
            _ok, _err = False, str(e)
        _changed_layers = [n for n, info in _registered_layers.items()
                           if n not in _before or info is not _before[n]]
        # 捕获图片与文件产物（此前历史记录只有图层，图片/文件全丢  用户翻历史找不到图）
        _imgs = peek_pending_images()
        _files = []
        try:
            if _run_id:
                from backend.services import storage_service as _ss
                for a in (_ss.get_run_artifacts(_run_id) or []):
                    if a.get("artifact_id") not in _files_before:
                        _files.append({"artifact_id": a.get("artifact_id") or "",
                                       "filename": a.get("filename") or a.get("name") or "",
                                       "path": a.get("rel_path") or a.get("filepath") or ""})
        except Exception:
            pass
        _task_id = get_current_task_id()
        if _task_id:
            try:
                from backend.services import task_manager as _tm
                _inputs = []
                for _key in ("layer_name", "clip_layer", "left_layer", "right_layer", "raster_layer"):
                    _name = kwargs.get(_key)
                    if _name:
                        _info = _registered_layers.get(_name) or {}
                        _inputs.append({"name": _name, "layer_id": _info.get("layer_id", "")})
                _outputs = [{"name": n, "layer_id": (_registered_layers.get(n) or {}).get("layer_id", "")}
                            for n in _changed_layers]
                if _style_action and _ok and not _outputs:
                    _style_layer = kwargs.get("layer_name") or kwargs.get("name") or ""
                    _style_info = _registered_layers.get(_style_layer) or {}
                    if _style_layer and _style_info:
                        _outputs = [{"name": _style_layer, "layer_id": _style_info.get("layer_id", "")}]
                _state_ok = _ok
                if t.name == "spatial_buffer":
                    _state_ok = _ok and bool(_outputs)
                    if _ok and not _state_ok:
                        _err = "缓冲区工具未登记新输出图层"
                elif t.name == "export_layer":
                    _state_ok = _ok and bool(_files)
                    if _ok and not _state_ok:
                        _err = "导出工具未登记本轮文件产物"
                elif _style_action:
                    _state_ok = _ok and bool(_outputs)
                    if _ok and not _state_ok:
                        _err = "样式工具未找到有效输入图层"
                if _is_gis_op:
                    _ok = _state_ok
                    _tm.record_gis_operation(
                        _task_id, t.name, kwargs, input_layers=_inputs,
                        output_layers=_outputs, output_artifacts=_files,
                        status="success" if _state_ok else "failed", run_id=_run_id,
                    )
            except Exception as _state_error:
                print(f"[Tools] GIS 任务状态记录失败: {_state_error}", flush=True)
        _history_svc.record(
            t.name, kwargs, _ok, _changed_layers,
            task_id=_task_id, error=_err,
            duration_ms=int((time.time() - _t0) * 1000),
            images=_imgs, file_artifacts=_files,
        )
        return out

    return _StructuredTool.from_function(
        func=_run_and_record,
        name=t.name,
        description=t.description,
        args_schema=t.args_schema,
    )


tools = [_recorded(t) for t in tools]


# ============================================================
# Dynamic Module Facade Proxy for Runtime Single Source of Truth
# ============================================================

class _ToolsFacadeModule(types.ModuleType):
    """Unified compatibility facade ensuring dynamic proxying to runtime module.

    Ensures that any external caller or test suite monkeypatching `tools.<state_var>`
    (e.g. `_registered_layers`, `_pending_layers`, `_temp_output_dir`, etc.)
    seamlessly updates `runtime.<state_var>` and maintains 100% two-way sync.
    """

    _PROXIED = {
        "_registered_layers",
        "_pending_layers",
        "_pending_layer_ops",
        "_pending_images",
        "_pending_qa_warnings",
        "_state_lock",
        "_shared_state_lock",
        "_session_locks",
        "_temp_output_dir",
        "_active_project_id",
        "_workspace_dir",
        "_clear_layers_flag",
        "_pending_aoi_suggestions",
        "_pending_heatmap",
        "_current_amap_key",
        "_search_call_count",
        "_domain_fail",
        "_exec_call_count",
        "_exec_log",
        "_raster_output_scope",
        "_current_task_id",
        "_last_user_message",
        "_current_run_id",
        "_conversation_context",
    }

    def __getattribute__(self, name):
        if name in _ToolsFacadeModule._PROXIED:
            runtime_mod = sys.modules.get("backend.services.tool_modules.runtime")
            if runtime_mod is not None and hasattr(runtime_mod, name):
                return getattr(runtime_mod, name)
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        for _m_name in (
            "backend.services.tool_modules.runtime",
            "backend.services.tool_modules.raster",
            "backend.services.tool_modules.terrain",
            "backend.services.tool_modules.vector",
            "backend.services.tool_modules.network",
        ):
            _mod = sys.modules.get(_m_name)
            if _mod is not None and (hasattr(_mod, name) or name in _ToolsFacadeModule._PROXIED):
                try:
                    setattr(_mod, name, value)
                except Exception:
                    pass
        super().__setattr__(name, value)

    def __getattr__(self, name):
        runtime_mod = sys.modules.get("backend.services.tool_modules.runtime")
        if runtime_mod is not None and hasattr(runtime_mod, name):
            return getattr(runtime_mod, name)
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


for _mod_name in ("backend.services.tools", "tools"):
    if _mod_name in sys.modules:
        sys.modules[_mod_name].__class__ = _ToolsFacadeModule
