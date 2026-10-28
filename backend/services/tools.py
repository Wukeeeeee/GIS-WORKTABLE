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
# 表达式 AST 白名单校验（供字段计算与栅格计算器复用）
# ============================================================

_ALLOWED_OPS = {
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.And, ast.Or, ast.Not,
    ast.BitXor, ast.BitAnd, ast.BitOr,
}


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
        if node.attr.startswith('_'):
            raise ValueError(f"沙箱拦截：禁止访问以 _ 开头的属性「{node.attr}」")
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


def _validate_field_calculation_ast(node, column_names):
    """字段计算器仅允许字段、常量、运算和明确列出的标量函数。"""
    safe_functions = {"abs", "round", "int", "float", "str", "len", "min", "max", "sum", "pow", "bool"}
    if isinstance(node, ast.Expression):
        _validate_field_calculation_ast(node.body, column_names)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        _validate_field_calculation_ast(node.left, column_names)
        _validate_field_calculation_ast(node.right, column_names)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        _validate_field_calculation_ast(node.operand, column_names)
    elif isinstance(node, ast.BoolOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        for value in node.values:
            _validate_field_calculation_ast(value, column_names)
    elif isinstance(node, ast.Compare):
        _validate_field_calculation_ast(node.left, column_names)
        for comparator in node.comparators:
            _validate_field_calculation_ast(comparator, column_names)
        allowed_comparisons = {ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE}
        if any(type(op) not in allowed_comparisons for op in node.ops):
            raise ValueError("不支持的比较操作")
    elif isinstance(node, ast.IfExp):
        _validate_field_calculation_ast(node.test, column_names)
        _validate_field_calculation_ast(node.body, column_names)
        _validate_field_calculation_ast(node.orelse, column_names)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in safe_functions or node.keywords:
            raise ValueError("只支持 abs/round/int/float/str/len/min/max/sum/pow/bool 函数")
        for arg in node.args:
            _validate_field_calculation_ast(arg, column_names)
    elif isinstance(node, ast.Name):
        if node.id not in column_names and node.id not in safe_functions:
            raise ValueError(f"字段或函数「{node.id}」不在允许范围内")
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ValueError("不支持该常量类型")
    else:
        raise ValueError(f"字段计算不支持该语法: {type(node).__name__}")


# ============================================================
# 共享状态（每次请求开始时由 reset_state() 清空）
# ============================================================

_pending_layers: list = []          # 待推送到前端的 GeoJSON 图层
_pending_qa_warnings: list = []     # 地理质量自检警告（geo_qa，随图层通道收集）
_pending_images: list = []          # 待推送到前端的图片/HTML
_INLINE_HTML_PREVIEW_LIMIT = 2 * 1024 * 1024
_pending_aoi_suggestions: dict = {} # AOI 候选列表
_pending_heatmap: dict = {"latest": None}
_clear_layers_flag: bool = False
_pending_layer_ops: list = []
_current_amap_key: str = ""
_search_call_count: int = 0
_domain_fail: dict = {}          # 域名 -> 连续失败次数（熔断）
_DOMAIN_FAIL_LIMIT = 2           # 同域连续失败 N 次即熔断
_search_cache: dict = {}          # query -> (时间戳, 结果文本)
_search_last_hit: dict = {}       # 引擎名 -> 上次请求时间（限速防验证码）
_SEARCH_CACHE_TTL = 600.0         # 相同查询 10 分钟内直接用缓存
_ENGINE_MIN_INTERVAL = 1.5       # 同一引擎两次请求最小间隔（秒）


def _engine_throttle(engine_name: str) -> None:
    """同引擎限速：间隔不足时 sleep 补齐，降低验证码/封禁概率。"""
    import time as _t
    last = _search_last_hit.get(engine_name, 0.0)
    wait = _ENGINE_MIN_INTERVAL - (_t.time() - last)
    if wait > 0:
        _t.sleep(wait)
    _search_last_hit[engine_name] = _t.time()    # 搜索次数计数，每次请求重置
_exec_call_count: int = 0       # Python 执行次数计数，每次请求重置
_exec_log: list = []            # 执行日志：记录每次execute_python的用途和结果
_temp_output_dir: str = ""          # 在 reset_state 时设置
_workspace_dir: str = ""
_registered_layers: dict = {}       # 已注册的图层信息
_active_project_id = None
_current_task_id: str = ""          # 当前任务 ID（由 graph.py 设置）
_last_user_message: str = ""        # 本轮用户原始请求（由 graph.py 每轮设置，供选项类工具保存上下文）

# 这些列表会被主模块读取，所以要导出
# 线程锁，保证 get_pending_state 的"读取+清空"操作原子性
# RLock（可重入）：reset_registered_layers 持锁状态下会调用 _register_layer（内部再次抢锁），
# 用非重入 Lock 会同线程自死锁（2026-10-13 E2E 实测：加载工程即挂死整个后端）
_state_lock = threading.RLock()

def peek_pending_images():
    """非消费读取当前待推送图片（供历史记录捕获，不影响主链路消费）"""
    with _state_lock:
        return [{"url": im.get("url") or im.get("path") or "", "label": im.get("label") or ""}
                for im in list(_pending_images) if isinstance(im, dict)]


def get_pending_state():
    """获取当前所有待发送状态并消费（清空），防止跨请求污染和校验器重复收集"""
    global _clear_layers_flag
    with _state_lock:
        pending_layers = []
        for layer in _pending_layers:
            if not isinstance(layer, dict):
                pending_layers.append(layer)
                continue
            result_layer = dict(layer)
            registered_name = result_layer.get("name")
            registered = _registered_layers.get(registered_name) if isinstance(registered_name, str) else None
            if isinstance(registered, dict):
                result_layer["registry_name"] = registered_name
                token = registered.get("registration_token")
                if isinstance(token, str) and token:
                    result_layer["registration_token"] = token
            pending_layers.append(result_layer)
        result = {
            "layers": pending_layers,
            "images": list(_pending_images),
            "qa_warnings": list(_pending_qa_warnings),
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
        _pending_qa_warnings.clear()
        _clear_layers_flag = False
        _pending_heatmap["latest"] = None
        return result


_current_run_id: str = ""


def set_current_task(task_id: str):
    """设置当前任务 ID（由 graph.py 在每轮请求开始时调用）"""
    global _current_task_id
    _current_task_id = task_id or ""


def set_current_run(run_id: str):
    """设置当前单次执行 ID（由 graph.py 在每轮请求开始时调用）"""
    global _current_run_id
    _current_run_id = run_id or ""


def get_current_run_id() -> str:
    """获取当前单次执行 ID"""
    return _current_run_id


def set_last_user_message(msg: str):
    """记录本轮用户原始请求（由 graph.py 在每轮开始时调用）。
    供 ask_user_choice 等两阶段交互工具保存上下文，下一轮用户点击选项后
    可把原任务拼回消息，避免「用户选完选项、AI 丢失原任务地名」的幻觉。"""
    global _last_user_message
    _last_user_message = (msg or "")[:500]


_conversation_context: str = ""


def set_conversation_context(ctx: str):
    """记录多轮上下文文本摘要（由 graph.py 在每轮开始时调用）。
    供行政区划消歧、地理对象推断等工具在后续轮次中复用已确认的实体信息。"""
    global _conversation_context
    _conversation_context = (ctx or "")[:3000]


def get_conversation_context() -> str:
    """获取当前多轮上下文文本摘要"""
    return _conversation_context


def get_current_task_id() -> str:
    """获取当前任务 ID"""
    return _current_task_id


def record_tool_artifact(filename: str, filepath: str, artifact_type: str = "image", step: int = 0) -> Optional[dict]:
    """统一记录工具生成的产物到 TaskManager (任务台账) 与 StorageService (SQLite事实台账)。"""
    global _current_task_id, _current_run_id
    art = None
    if _current_task_id:
        try:
            art = register_artifact(_current_task_id, filename, filepath,
                                    artifact_type=artifact_type, created_by_step=step)
        except Exception as e:
            print(f"[Tools] register_artifact 出错: {e}", flush=True)
    if _current_run_id:
        try:
            from backend.services import storage_service
            art_id = (art.get("artifact_id") if art else "") or uuid.uuid4().hex[:10]
            storage_service.register_run_artifact(
                _current_run_id, art_id, filename, filepath, file_type=artifact_type
            )
        except Exception as e:
            print(f"[Tools] register_run_artifact 出错: {e}", flush=True)
    return art


# ---- 同 session 并发互斥：防止两条并发请求互相 reset/覆盖 pending 图层 ----
import threading as _threading_mod
_session_locks: dict = {}
_session_locks_guard = _threading_mod.Lock()
_shared_state_lock = _threading_mod.Lock()

def session_lock_wait_seconds() -> float:
    """同 session 新请求在被占用时最多等待多少秒。

    用户在上一条工具链还没收尾时又发一条（例如右键「问 AI」），旧逻辑会立刻
    返回「当前会话已有请求在处理中」，看起来像 AI 的正式回答。默认改为最多等
    20 秒，等上一条释放会话锁；可用环境变量 GIS_SESSION_LOCK_WAIT 调整，
    设为 0 恢复「不等待、立即忙」的旧行为。
    """
    raw = os.environ.get("GIS_SESSION_LOCK_WAIT", "20")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 20.0


def acquire_session_lock(session_id: str, timeout: Optional[float] = None) -> bool:
    """尝试占用会话锁。

    timeout=None 时使用 session_lock_wait_seconds()（默认 20s）；
    timeout<=0 表示非阻塞。成功 True；等待超时返回 False。
    """
    sid = session_id or "default"
    with _session_locks_guard:
        lock = _session_locks.get(sid)
        if lock is None:
            lock = _threading_mod.Lock()
            _session_locks[sid] = lock
    if timeout is None:
        timeout = session_lock_wait_seconds()
    if timeout and timeout > 0:
        return lock.acquire(timeout=timeout)
    return lock.acquire(blocking=False)

def release_session_lock(session_id: str):
    """释放会话锁（忽略未持有）。"""
    sid = session_id or "default"
    with _session_locks_guard:
        lock = _session_locks.get(sid)
    if lock is not None:
        try:
            lock.release()
        except RuntimeError:
            pass


def acquire_shared_state_lock(timeout: Optional[float] = None) -> bool:
    """Serialize top-level operations that use this module's process-wide state."""
    if timeout is None:
        timeout = session_lock_wait_seconds()
    if timeout and timeout > 0:
        return _shared_state_lock.acquire(timeout=timeout)
    return _shared_state_lock.acquire(blocking=False)


def release_shared_state_lock() -> None:
    try:
        _shared_state_lock.release()
    except RuntimeError:
        pass

def reset_state(amap_key: str = "", task_id: str = ""):
    """每次请求开始时调用，清空所有共享状态"""
    global _current_amap_key, _clear_layers_flag, _search_call_count, _exec_call_count, _exec_log, _current_task_id
    global _last_user_message, _conversation_context, _current_run_id
    # 保证输出目录在本轮任何工具用到之前就已就绪。
    # 此前只有 execute_python / _add_pending_item 等少数入口会初始化它，
    # 如果一轮里最先执行的工具是 spatial_interpolate 这类直接写 _temp_output_dir 的，
    # 目录还是空串 -> 产物落到 CWD/uploads，而 URL 指向 /output/...，前端拿到 404。
    init_temp_dir()
    with _state_lock:
        _pending_layers.clear()
        _pending_qa_warnings.clear()
        _pending_images.clear()
        _pending_aoi_suggestions.clear()
        _pending_heatmap["latest"] = None
        _clear_layers_flag = False
        _pending_layer_ops.clear()
        _current_amap_key = amap_key
        _search_call_count = 0
        _domain_fail.clear()
        _exec_call_count = 0
        _exec_log.clear()
        _current_task_id = task_id or ""
        # 会话级上下文同样要清：否则上一轮聊天留下的「用户原话/多轮上下文」会被
        # 手动工具调用（/api/tools/invoke、MCP）继承，导致实体消歧选错地名
        # （tools.py 内 _last_user_message / _conversation_context 参与城市候选判定）。
        # 聊天流程在 reset_state() 之后会由 graph.py 重新 set_*，所以清空是安全的。
        _last_user_message = ""
        _conversation_context = ""
        _current_run_id = ""


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


def _push_layer(name: str, geojson: dict, style: dict = None, provenance: dict = None):
    """将图层加入待发送列表（同名图层就地覆盖最新数据，防止单轮多次更新累加出重复图层）"""
    try:
        layer = {"geojson": geojson, "name": name}
        if style:
            layer["style"] = style
        safe_provenance = _normalize_layer_provenance(provenance)
        if safe_provenance:
            layer["provenance"] = safe_provenance
        with _state_lock:
            replaced = False
            for i, existing in enumerate(_pending_layers):
                if existing.get("name") == name:
                    _pending_layers[i] = layer
                    replaced = True
                    break
            if not replaced:
                _pending_layers.append(layer)
            else:
                _pending_qa_warnings[:] = [
                    item for item in _pending_qa_warnings
                    if not (isinstance(item, dict) and item.get("layer") == name)
                ]
            for w in _geo_qa(geojson):
                _pending_qa_warnings.append({"layer": name, "warning": w})
    except Exception:
        pass


def _geo_qa(geojson) -> list:
    """地理质量自检（延迟导入避免循环依赖；失败静默）"""
    try:
        from backend.services.geo_qa import qa_check
        return qa_check(geojson)
    except Exception:
        return []


def _unregister_layer(name: str, registration_token: str = None):
    """从注册表中移除图层"""
    with _state_lock:
        current = _registered_layers.get(name)
        if registration_token is not None and (not current or current.get("registration_token") != registration_token):
            return False
        return _registered_layers.pop(name, None) is not None


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


def _valid_registration_geometry(geometry: dict) -> bool:
    if not isinstance(geometry, dict):
        return False

    def valid_position(position):
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            return False
        for value in position:
            if not isinstance(value, Real) or isinstance(value, bool):
                return False
            try:
                if not math.isfinite(float(value)):
                    return False
            except (OverflowError, TypeError, ValueError):
                return False
        return True

    def valid_line(line, minimum=2):
        return (
            isinstance(line, (list, tuple)) and len(line) >= minimum
            and all(valid_position(p) for p in line)
        )

    def valid_ring(ring):
        return valid_line(ring, minimum=4) and tuple(ring[0]) == tuple(ring[-1])

    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Point":
        return valid_position(coordinates)
    if kind == "MultiPoint":
        return (
            isinstance(coordinates, (list, tuple)) and bool(coordinates)
            and all(valid_position(p) for p in coordinates)
        )
    if kind == "LineString":
        return valid_line(coordinates)
    if kind == "MultiLineString":
        return (
            isinstance(coordinates, (list, tuple)) and bool(coordinates)
            and all(valid_line(line) for line in coordinates)
        )
    if kind == "Polygon":
        return (
            isinstance(coordinates, (list, tuple)) and bool(coordinates)
            and all(valid_ring(ring) for ring in coordinates)
        )
    if kind == "MultiPolygon":
        return (isinstance(coordinates, (list, tuple)) and bool(coordinates)
                and all(isinstance(polygon, (list, tuple)) and bool(polygon)
                        and all(valid_ring(ring) for ring in polygon) for polygon in coordinates))
    if kind == "GeometryCollection":
        geometries = geometry.get("geometries")
        return isinstance(geometries, list) and all(_valid_registration_geometry(child) for child in geometries)
    return False


def _compute_bbox(geojson: dict) -> list:
    """计算 GeoJSON 的包围盒 [minLng, minLat, maxLng, maxLat]"""
    coords = []
    fc = _normalize_geojson(geojson)
    for f in fc.get("features", []):
        geom = f.get("geometry") or {}
        _extract_coords(geom, coords)
    if not coords:
        return [0, 0, 0, 0]
    # 防护：坐标可能为 None 或长度不足
    valid = [c for c in coords if c and len(c) >= 2]
    if not valid:
        return [0, 0, 0, 0]
    lngs = [c[0] for c in valid]
    lats = [c[1] for c in valid]
    return [min(lngs), min(lats), max(lngs), max(lats)]


def _validate_wgs84_geojson(geojson: dict) -> None:
    """Validate GeoJSON structure and coordinate bounds before accepting a vector layer."""
    try:
        feature_collection = _normalize_geojson(geojson)
        structurally_valid = (
            isinstance(feature_collection, dict)
            and isinstance(feature_collection.get("features"), list)
            and all(
                isinstance(feature, dict)
                and (feature.get("geometry") is None or _valid_registration_geometry(feature["geometry"]))
                for feature in feature_collection["features"]
            )
        )
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
        structurally_valid = False
    if not structurally_valid:
        raise ValueError("GeoJSON 几何结构无效：坐标需包含有效位置和有限数值")
    try:
        bounds = _compute_bbox(feature_collection)
        valid_bounds = (
            isinstance(bounds, (list, tuple)) and len(bounds) == 4
            and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(float(value)) for value in bounds)
            and -180 <= bounds[0] <= bounds[2] <= 180
            and -90 <= bounds[1] <= bounds[3] <= 90
        )
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
        valid_bounds = False
    if not valid_bounds:
        raise ValueError("矢量图层坐标超出 WGS-84 范围或格式无效")


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


def _make_fid(props: dict, idx: int) -> str:
    """稳定要素 ID：行政代码 > 数据源 ID > 名称 > 顺序兜底。"""
    if props.get("adcode") not in (None, ""):
        return f"p:{props['adcode']}"
    if props.get("id") not in (None, ""):
        return f"id:{props['id']}"
    if props.get("name"):
        return f"n:{props['name']}"
    return f"i:{idx}"


def _normalize_layer_provenance(provenance):
    """Keep only bounded, non-secret source facts suitable for project persistence."""
    if not isinstance(provenance, dict):
        return None
    allowed = ("provider", "provider_name", "kind", "kind_label", "file_format", "crs")
    result = {}
    for key in allowed:
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()[:200]
    crs_known = provenance.get("crs_known")
    if isinstance(crs_known, bool):
        result["crs_known"] = crs_known
    processing = provenance.get("processing")
    if isinstance(processing, dict) and processing.get("tool") == "spatial_buffer":
        source_layer = processing.get("source_layer")
        parameters = processing.get("parameters")
        if isinstance(source_layer, str) and source_layer.strip() and isinstance(parameters, dict):
            distance = parameters.get("distance")
            unit = parameters.get("unit")
            dissolve = parameters.get("dissolve")
            try:
                distance_value = float(distance) if isinstance(distance, (int, float)) and not isinstance(distance, bool) else None
            except (OverflowError, TypeError, ValueError):
                distance_value = None
            if (distance_value is not None and math.isfinite(distance_value) and distance_value > 0
                    and isinstance(unit, str) and unit in {"m", "km"} and isinstance(dissolve, bool)):
                result["processing"] = {
                    "tool": "spatial_buffer",
                    "source_layer": source_layer.strip()[:200],
                    "parameters": {"distance": distance_value, "unit": unit, "dissolve": dissolve},
                }
    elif isinstance(processing, dict) and processing.get("tool") == "spatial_clip":
        source_layer = processing.get("source_layer")
        clip_layer = processing.get("clip_layer")
        if (isinstance(source_layer, str) and source_layer.strip()
                and isinstance(clip_layer, str) and clip_layer.strip()):
            result["processing"] = {
                "tool": "spatial_clip",
                "source_layer": source_layer.strip()[:200],
                "clip_layer": clip_layer.strip()[:200],
            }
    elif isinstance(processing, dict) and processing.get("tool") == "spatial_union":
        source_layer = processing.get("source_layer")
        other_layer = processing.get("other_layer")
        if (isinstance(source_layer, str) and source_layer.strip()
                and isinstance(other_layer, str) and other_layer.strip()):
            result["processing"] = {
                "tool": "spatial_union",
                "source_layer": source_layer.strip()[:200],
                "other_layer": other_layer.strip()[:200],
            }
    elif isinstance(processing, dict) and processing.get("tool") == "spatial_intersect":
        source_layer = processing.get("source_layer")
        other_layer = processing.get("other_layer")
        if (isinstance(source_layer, str) and source_layer.strip()
                and isinstance(other_layer, str) and other_layer.strip()):
            result["processing"] = {
                "tool": "spatial_intersect",
                "source_layer": source_layer.strip()[:200],
                "other_layer": other_layer.strip()[:200],
            }
    elif isinstance(processing, dict) and processing.get("tool") == "spatial_difference":
        source_layer = processing.get("source_layer")
        other_layer = processing.get("other_layer")
        if (isinstance(source_layer, str) and source_layer.strip()
                and isinstance(other_layer, str) and other_layer.strip()):
            result["processing"] = {
                "tool": "spatial_difference",
                "source_layer": source_layer.strip()[:200],
                "other_layer": other_layer.strip()[:200],
            }
    source_url = provenance.get("source_url")
    if isinstance(source_url, str) and len(source_url) <= 1000:
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(source_url.strip())
            if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
                result["source_url"] = source_url.strip()
        except ValueError:
            pass
    return result or None


def _unicode_layer_name_conflict(name: str) -> str | None:
    """Return an existing visually equivalent Unicode name, if it is a different key."""
    normalized_name = unicodedata.normalize("NFC", name)
    return next((existing for existing in _registered_layers
                 if existing != name and unicodedata.normalize("NFC", existing) == normalized_name), None)


def _register_layer(name: str, geojson: dict, group_name: str = None, provenance: dict = None,
                    allow_unicode_alias: bool = False, unique_name: bool = False):
    """注册图层供 AI 后续查询。注册时为每个要素注入稳定 _fid（幂等），
    供前端 2D/3D 选中同步与下钻状态机使用。"""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("图层名称不能为空")
    if not isinstance(geojson, dict):
        raise ValueError("图层数据必须是 GeoJSON 对象")
    fc = _normalize_geojson(geojson)
    if not isinstance(fc, dict) or not isinstance(fc.get("features"), list):
        raise ValueError("GeoJSON 必须是 Feature、FeatureCollection 或 Geometry")

    features = fc["features"]
    types, used_fids = set(), set()
    for i, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError(f"第 {i + 1} 个要素格式无效")
        raw_geometry = feature.get("geometry")
        if raw_geometry is not None and not _valid_registration_geometry(raw_geometry):
            raise ValueError("GeoJSON 几何结构无效：坐标需包含有效位置和有限数值")
        geom = raw_geometry or {}
        if geom.get("type"):
            types.add(geom["type"])
        props = feature.get("properties")
        if not isinstance(props, dict):
            props = {}
            feature["properties"] = props
        fid = props.get("_fid")
        if fid in (None, "") or str(fid) in used_fids:
            fid = _make_fid(props, i)
            if str(fid) in used_fids:
                fid = f"i:{i}"
            suffix = 1
            while str(fid) in used_fids:
                fid = f"i:{i}:{suffix}"
                suffix += 1
            props["_fid"] = fid
        used_fids.add(str(fid))

    bbox = _compute_bbox(fc)
    with _state_lock:
        if unique_name and name in _registered_layers:
            stem, extension = os.path.splitext(name)
            suffix = 1
            while f"{stem}_{suffix}{extension}" in _registered_layers:
                suffix += 1
            name = f"{stem}_{suffix}{extension}"
        conflicting_name = _unicode_layer_name_conflict(name) if not allow_unicode_alias else None
        if conflicting_name:
            raise ValueError(f"图层名称与现有图层「{conflicting_name}」仅 Unicode 规范形式不同，为避免显示重复请先重命名")
        registration_token = uuid.uuid4().hex
        previous = _registered_layers.get(name) or {}
        safe_provenance = _normalize_layer_provenance(provenance)
        if (safe_provenance is None and previous.get("geojson") == fc
                and isinstance(previous.get("provenance"), dict)):
            safe_provenance = _normalize_layer_provenance(previous["provenance"])
        _registered_layers[name] = {
            "name": name,
            "layer_id": previous.get("layer_id") or uuid.uuid4().hex,
            "registration_token": registration_token,
            "group_name": (group_name.strip() if isinstance(group_name, str) else previous.get("group_name", "")),
            "feature_count": len(features),
            "geometry_types": list(types) if types else ["未知"],
            "geojson": fc,
            "bbox": bbox,
            **({"provenance": safe_provenance} if safe_provenance else {}),
        }
        return registration_token


def _update_registered_layer_data(name: str, geojson: dict):
    """Replace registered data through the same metadata/FID refresh path as registration."""
    _register_layer(name, geojson)


def _get_exact_registered_layer(name: str) -> tuple:
    """Mutating operations require the exact registered layer name to avoid editing a similarly named layer."""
    if isinstance(name, str) and name.strip() and name in _registered_layers:
        return name, _registered_layers[name], ""
    if not isinstance(name, str) or not name.strip():
        return "", None, "图层名不能为空；请先查看已注册图层并传入完整图层名；未执行修改"
    candidates = [key for key in _registered_layers if name in key]
    if candidates:
        if len(candidates) == 1:
            return "", None, f"请使用完整图层名「{candidates[0]}」，未执行修改"
        return "", None, f"「{name}」匹配多个图层：{', '.join(candidates)}，请指定完整图层名；未执行修改"
    return "", None, f"未找到完整图层名「{name}」，当前图层：{', '.join(_registered_layers.keys()) or '无'}；未执行修改"


def _layer_property_examples(geojson: dict, limit: int = 3) -> list:
    """抽取少量分散的非敏感属性样例，帮助模型理解图层内容。"""
    features = geojson.get("features", []) if isinstance(geojson, dict) else []
    if not features:
        return []
    if len(features) <= limit:
        indices = list(range(len(features)))
    else:
        indices = sorted({round(i * (len(features) - 1) / (limit - 1)) for i in range(limit)}) if limit > 1 else [0]
    examples = []
    for index in indices:
        props = features[index].get("properties") or {}
        example = {}
        for key, value in props.items():
            key_text = str(key)
            if key_text == "_fid" or any(term in key_text.casefold() for term in ("password", "secret", "token", "api_key", "phone", "email")):
                continue
            if isinstance(value, (str, int, float)) and str(value).strip():
                example[key_text] = str(value)[:72]
            if len(example) >= 5:
                break
        if example:
            examples.append(example)
    return examples


def _register_raster_layer(name: str, raster: dict, source_path: str = None,
                           allow_unicode_alias: bool = False):
    """Register a managed raster independently of its preview/map identifier."""
    import uuid
    if not isinstance(name, str) or not name.strip() or not isinstance(raster, dict):
        raise ValueError("栅格图层名称或资源无效")
    bounds = raster.get('bounds')
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
            or not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(value) for value in bounds)
            or not (-180 <= bounds[0] <= bounds[2] <= 180 and -90 <= bounds[1] <= bounds[3] <= 90)):
        raise ValueError("栅格范围必须是有效的 WGS-84 范围")
    if not source_path and any(raster.get(key) for key in ('source_asset', 'source_filename', 'source_url')):
        from backend.services.project_service import _raster_original_path
        source_path = _raster_original_path(raster)
        if not source_path:
            raise ValueError("栅格原始数据资源不存在")
    token = uuid.uuid4().hex
    with _state_lock:
        conflicting_name = _unicode_layer_name_conflict(name) if not allow_unicode_alias else None
        if conflicting_name:
            raise ValueError(f"图层名称与现有图层「{conflicting_name}」仅 Unicode 规范形式不同，为避免显示重复请先重命名")
        _registered_layers[name] = {'geojson': None, 'geometry_types': ['Raster'], 'feature_count': 0,
                                    'bbox': list(bounds), 'raster': dict(raster),
                                    'raster_source_path': source_path, 'registration_token': token}
    return token


def get_registered_layers_snapshot() -> list:
    """返回当前所有注册图层的快照，包括属性样例，供 AI 识别图层内容。"""
    result = []
    with _state_lock:
        snapshot = list(_registered_layers.items())
    for name, info in snapshot:
        geojson = info.get("geojson") or {}
        result.append({
            "filename": name,
            "group_name": info.get("group_name", ""),
            "geojson": geojson,
            "geometry_types": info.get("geometry_types", []),
            "feature_count": info.get("feature_count", 0),
            "bbox": info.get("bbox", []),
            "property_examples": _layer_property_examples(geojson),
            "source": "ai",
            **({"provenance": dict(info["provenance"])} if isinstance(info.get("provenance"), dict) else {}),
            **({"raster": dict(info["raster"])} if isinstance(info.get("raster"), dict) else {}),
        })
    return result


def reset_registered_layers(layers: list = None, tolerate_invalid: bool = False):
    """重置/替换当前注册的图层字典（切换工程或清空工程时调用，实现工程间严格图层隔离）"""
    global _active_project_id
    skipped = []
    with _state_lock:
        _active_project_id = None
        _registered_layers.clear()
        _pending_layers.clear()
        _pending_layer_ops.clear()
        if layers:
            for l in layers:
                if not isinstance(l, dict):
                    if tolerate_invalid:
                        skipped.append("图层")
                    continue
                name = l.get("name") or l.get("filename")
                geojson = l.get("geojson") or l.get("geojson_data")
                try:
                    if name and isinstance(l.get('raster'), dict):
                        _register_raster_layer(name, l['raster'], allow_unicode_alias=True)
                    elif name and geojson:
                        _register_layer(name, geojson, provenance=l.get("provenance"), allow_unicode_alias=True)
                except Exception:
                    if not tolerate_invalid:
                        raise
                    skipped.append(name if isinstance(name, str) and name else "图层")
    return skipped


def _add_pending_item(url: str, file_path: str = None):
    """添加到待发送的图片/HTML 列表"""
    init_temp_dir()
    if file_path and file_path.lower().endswith(".html"):
        try:
            with open(file_path, "rb") as _f:
                preview = _f.read(_INLINE_HTML_PREVIEW_LIMIT + 1)
            if len(preview) <= _INLINE_HTML_PREVIEW_LIMIT:
                _pending_images.append({
                    "url": url, "type": "html", "content": preview.decode("utf-8"),
                })
            else:
                _pending_images.append({"url": url, "type": "html"})
        except Exception:
            _pending_images.append({"url": url, "type": "html"})
    else:
        _pending_images.append({"url": url, "type": "png" if (url or "").lower().endswith(".png") else "image"})


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
    global _search_call_count
    _search_call_count += 1
    if _search_call_count > 30:
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
                return f"高德不可用（{amap_error}）；已尝试 OSM，但在「{fallback['area']}」未找到「{keywords}」POI。"
            source = "OpenStreetMap"
            layer_name = f"{keywords}_POI(OSM)"
        except Exception as error:
            return f"高德不可用（{amap_error or '无有效结果'}）；OSM 回退也失败：{str(error)[:250]}"

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
                in_msg = bool(_last_user_message and (city_short in _last_user_message or prov_short in _last_user_message or cand_label in _last_user_message))
                # 检查2：多轮上下文记录
                in_ctx = bool(_conversation_context and (city_short in _conversation_context or prov_short in _conversation_context or cand_label in _conversation_context))
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
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        import geopandas as gpd
        import pandas as pd
        import numpy as np
        import json

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层 {layer_name} 为空"

        safe_globals = {"__builtins__": {}}
        safe_locals = {
            "abs": abs, "round": round, "int": int, "float": float,
            "str": str, "len": len, "min": min, "max": max,
            "sum": sum, "pow": pow, "bool": bool,
        }
        try:
            _fc_tree = ast.parse(expression, mode="eval")
            _validate_field_calculation_ast(
                _fc_tree, set(gdf.columns) - {"geometry"}
            )
        except Exception as e:
            return f"表达式计算失败：{str(e)[:200]}"

        _fc_code = compile(_fc_tree, "<safe>", "eval")
        try:
            result = gdf.eval(expression, local_dict=safe_locals, global_dict=safe_globals)
            gdf[new_field] = result
        except Exception:
            try:
                result = gdf.apply(lambda row: eval(_fc_code, safe_globals, {**safe_locals, **row.to_dict()}), axis=1)
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
    global _clear_layers_flag
    count = len(_registered_layers)
    _registered_layers.clear()
    _pending_layers.clear()
    _clear_layers_flag = True
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
            _z = max(3, min(19, int(zoom)))
            _pending_layer_ops.append({"action": "center", "center": [lon, lat], "zoom": _z})
            return f"已定位到 ({lat:.4f}, {lon:.4f})，缩放级别 {_z}"
        except ValueError:
            return f"无法解析坐标：{center}，格式应为「经度,纬度」（如 121.4593,31.2513）"
    return "请提供 layer_name（图层名）或 center（「经度,纬度」）进行定位"


# ============================================================
# 工具: export_layer — 导出图层
# ============================================================

def _safe_layer_export_stem(layer_name: str) -> str:
    """把图层名转换为安全且可被聊天附件识别的有限长度文件名。"""
    stem = re.sub(r'[^A-Za-z0-9_\-\u4e00-\u9fa5.()（）]+', "_", str(layer_name)).strip(" ._")
    return (stem[:100] or "layer")


@tool
def export_layer(layer_name: str, format: str = "geojson") -> str:
    """导出指定矢量图层并提供下载链接。format 可选 geojson、shp、gpkg、csv、csv_xy；csv 只导出属性，csv_xy 导出属性及经纬度且仅支持 Point 要素。栅格图层当前不支持此导出工具。"""
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

    if isinstance(info.get("raster"), dict):
        return f"图层「{layer_name}」是栅格图层；当前 export_layer 仅支持矢量导出格式"
    geojson = info.get("geojson")
    if not isinstance(geojson, dict) or not isinstance(geojson.get("features"), list):
        return f"图层「{layer_name}」的矢量数据无效，无法导出"
    safe_name = _safe_layer_export_stem(layer_name)

    if format == "geojson":
        # 直接保存 GeoJSON
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        fname = f"{safe_name}_{ts}.geojson"
        init_temp_dir()
        path = os.path.join(_temp_output_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)
        # === 导出真实性验证 ===
        _verr = []
        _src_count = len(geojson.get("features", []))
        if not os.path.exists(path):
            _verr.append("文件未生成")
        elif os.path.getsize(path) < 20:
            _verr.append("文件过小")
        else:
            try:
                with open(path, "r", encoding="utf-8") as _f:
                    _gj = json.load(_f)
                if _gj.get("type") != "FeatureCollection":
                    _verr.append("非FeatureCollection")
                _feat_count = len(_gj.get("features", []))
                if _feat_count != _src_count:
                    _verr.append(f"Feature数不符({_feat_count}!={_src_count})")
                if _feat_count > 0 and not all(ft.get("geometry") for ft in _gj["features"]):
                    _verr.append("存在无geometry的Feature")
            except Exception as _ve:
                _verr.append(f"无法重新读取:{_ve}")
        if _verr:
            return "GeoJSON导出验证失败: " + "; ".join(_verr)
        record_tool_artifact(fname, path, artifact_type="geojson")
        return f"GeoJSON已生成：/output/{fname}（{_src_count}个Feature）\n如需要 Shapefile 格式，可再次调用 export_layer 并设 format='shp'"

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
            used_names = {
                str(col).casefold() for col in gdf.columns
                if col != "geometry" and len(str(col)) <= 10
            }
            for col in gdf.columns:
                if col != "geometry" and len(col) > 10:
                    new_name = col[:10]
                    suffix = 1
                    while new_name.casefold() in used_names or new_name.casefold() == "geometry":
                        suffix_text = str(suffix)
                        new_name = col[:10 - len(suffix_text)] + suffix_text
                        suffix += 1
                    rename_map[col] = new_name
                    used_names.add(new_name.casefold())
            if rename_map:
                gdf = gdf.rename(columns=rename_map)

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            fname = f"{safe_name}_{ts}.zip"

            tmp_dir = tempfile.mkdtemp(prefix="shp_export_")
            shp_base = os.path.join(tmp_dir, safe_name)
            gdf.to_file(shp_base + ".shp", driver="ESRI Shapefile", encoding="utf-8")

            init_temp_dir()
            zip_path = os.path.join(_temp_output_dir, fname)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fn in os.listdir(tmp_dir):
                    fp = os.path.join(tmp_dir, fn)
                    if os.path.isfile(fp):
                        zf.write(fp, fn)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            # === 导出真实性验证 ===
            _verr = []
            if not os.path.exists(zip_path):
                _verr.append("ZIP文件未生成")
            elif os.path.getsize(zip_path) < 100:
                _verr.append("ZIP文件过小")
            else:
                try:
                    with zipfile.ZipFile(zip_path, "r") as _zf:
                        _ns = _zf.namelist()
                        if not _ns:
                            _verr.append("ZIP内无文件")
                        for _e in [".shp", ".shx", ".dbf"]:
                            if not any(n.endswith(_e) for n in _ns):
                                _verr.append("ZIP缺少" + _e)
                        if gdf.crs and not any(n.endswith(".prj") for n in _ns):
                            _verr.append("ZIP缺少.prj")
                except Exception as _ve:
                    _verr.append("ZIP无法打开")
            if _verr:
                return "SHP导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, zip_path, artifact_type="file")
            return f"Shapefile已生成：/output/{fname}（含.shp/.shx/.dbf/.prj/.cpg，{len(gdf)}个要素）"
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
            fname = f"{safe_name}_{ts}.gpkg"

            init_temp_dir()
            path = os.path.join(_temp_output_dir, fname)
            gdf.to_file(path, layer=safe_name, driver="GPKG", encoding="utf-8")

            # === 导出真实性验证 ===
            _verr = []
            if not os.path.exists(path):
                _verr.append("文件未生成")
            elif os.path.getsize(path) < 100:
                _verr.append("文件过小")
            else:
                try:
                    _gdf2 = gpd.read_file(path, layer=safe_name)
                    if len(_gdf2) != len(gdf):
                        _verr.append(f"Feature数不符({len(_gdf2)}!={len(gdf)})")
                    if _gdf2.crs != gdf.crs:
                        _verr.append(f"CRS不符({_gdf2.crs}!={gdf.crs})")
                    if not _gdf2.geom_type.equals(gdf.geom_type):
                        _verr.append("geometry类型不一致")
                except Exception as _ve:
                    _verr.append(f"无法重新读取:{_ve}")
            if _verr:
                return "GPKG导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, path, artifact_type="file")
            return f"GeoPackage已生成：/output/{fname}（{len(gdf)}个Feature，CRS={gdf.crs}）"
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
            fname = f"{safe_name}_{ts}.csv"

            init_temp_dir()
            path = os.path.join(_temp_output_dir, fname)
            attr_df = gdf.drop(columns=["geometry"], errors="ignore")
            attr_df.to_csv(path, index=False, encoding="utf-8-sig")

            # === 导出真实性验证 ===
            _verr = []
            if not os.path.exists(path):
                _verr.append("文件未生成")
            elif os.path.getsize(path) < 10:
                _verr.append("文件过小")
            else:
                try:
                    _df2 = pd.read_csv(path, encoding="utf-8-sig")
                    if len(_df2) != len(attr_df):
                        _verr.append(f"行数不符({len(_df2)}!={len(attr_df)})")
                    if len(_df2.columns) != len(attr_df.columns):
                        _verr.append(f"列数不符({len(_df2.columns)}!={len(attr_df.columns)})")
                except Exception as _ve:
                    _verr.append(f"无法重新读取:{_ve}")
            if _verr:
                return "CSV导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, path, artifact_type="file")
            return (f"CSV属性表已生成：/output/{fname}"
                    f"（{len(attr_df.columns)}列, {len(attr_df)}行）"
                    f"\n如需含坐标的CSV，可用 format='csv_xy'")
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
            if not gdf.geometry.geom_type.eq("Point").all():
                return "CSV坐标导出仅支持 Point 点要素；线或面请使用 GeoJSON、Shapefile 或 GeoPackage 格式"

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            fname = f"{safe_name}_{ts}.csv"

            init_temp_dir()
            path = os.path.join(_temp_output_dir, fname)

            gdf["longitude"] = gdf.geometry.x
            gdf["latitude"] = gdf.geometry.y
            attr_df = gdf.drop(columns=["geometry"], errors="ignore")
            attr_df.to_csv(path, index=False, encoding="utf-8-sig")

            # === 导出真实性验证 ===
            _verr = []
            if not os.path.exists(path):
                _verr.append("文件未生成")
            elif os.path.getsize(path) < 10:
                _verr.append("文件过小")
            else:
                try:
                    _df2 = pd.read_csv(path, encoding="utf-8-sig")
                    if len(_df2) != len(attr_df):
                        _verr.append(f"行数不符({len(_df2)}!={len(attr_df)})")
                    if "longitude" not in _df2.columns:
                        _verr.append("缺少longitude列")
                    if "latitude" not in _df2.columns:
                        _verr.append("缺少latitude列")
                except Exception as _ve:
                    _verr.append(f"无法重新读取:{_ve}")
            if _verr:
                return "CSV导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, path, artifact_type="file")
            return (f"CSV（含坐标）已生成：/output/{fname}"
                    f"（{len(attr_df.columns)}列, {len(attr_df)}行，含longitude/latitude）")
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

        echarts_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{chart_title}</title>
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
  var chartType = '{chart_type}';
  var yAxisName = '{y_name_cfg}';

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
      text: '{chart_title}',
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
    if not isinstance(location_name, str) or not location_name.strip():
        return "路网下载失败：请提供城市名或经纬度范围"
    location_name = location_name.strip()
    if not isinstance(network_type, str) or network_type.strip().lower() not in {"drive", "walk", "bike", "all"}:
        return "路网下载失败：network_type 仅支持 drive、walk、bike、all"
    network_type = network_type.strip().lower()

    parts = [p.strip() for p in location_name.split(",")]
    bbox = None
    if len(parts) == 4:
        try:
            bbox = tuple(float(value) for value in parts)
        except (TypeError, ValueError, OverflowError):
            return "路网下载失败：BBox 必须按 min_lng,min_lat,max_lng,max_lat 提供数值坐标"
        import math
        min_lng, min_lat, max_lng, max_lat = bbox
        if not all(math.isfinite(value) for value in bbox):
            return "路网下载失败：BBox 坐标必须是有限数值"
        if not (-180 <= min_lng <= 180 and -180 <= max_lng <= 180
                and -90 <= min_lat <= 90 and -90 <= max_lat <= 90):
            return "路网下载失败：BBox 经度须在 -180 至 180、纬度须在 -90 至 90 范围内"
        if min_lng >= max_lng or min_lat >= max_lat:
            return "路网下载失败：BBox 最小经度/纬度必须小于最大经度/纬度"

    try:
        import osmnx as ox
    except ImportError:
        return "osmnx 未安装，请执行 pip install osmnx"

    try:
        import concurrent.futures

        ox.settings.log_console = False
        ox.settings.use_cache = True

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _fetch():
            if bbox is not None:
                min_lng, min_lat, max_lng, max_lat = bbox
                return ox.graph_from_bbox(north=max_lat, south=min_lat, east=max_lng, west=min_lng, network_type=network_type)
            else:
                return ox.graph_from_place(location_name, network_type=network_type)

        fut = executor.submit(_fetch)
        try:
            G = fut.result(timeout=120)
        except concurrent.futures.TimeoutError:
            # 显式 cancel + 关闭线程池，防止后台 osmnx 继续占用 socket
            fut.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            return (
                f"下载「{location_name}」路网超时（120秒），OSM 服务器无响应。\n\n"
                f"请尝试以下替代方案：\n"
                f"1. 前往 https://www.geofabrik.de 下载对应地区 .osm.pbf 文件（国内可访问）\n"
                f"2. 前往 https://extract.bbbike.org 用矩形框选区域导出 .osm（支持国内访问）\n"
                f"3. 将下载的文件上传到 GIS WorkTable，AI 会自动识别为路网图层\n"
                f"4. 上传后告诉我，我再调用 network_analysis 分析"
            )
        except Exception:
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True, cancel_futures=True)

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
        return f"下载路网失败: {str(e)[:300]}"


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
    """从路网图层执行网络分析（结果自动加载到地图）。
    - analysis_type: 'route'(最短路径,双向Dijkstra) / 'service_area'(服务区) / 'closest_facility'(最近设施)。
    - origin / destination / facility: 坐标，格式为 "经度,纬度"（WGS84）。地名需先经 amap_geocode 转坐标。
    - events: 分号分隔坐标点；breaks: 逗号分隔阻抗米数；n: 最近设施数(默认 3)。"""
    from backend.services.network_service import (
        shortest_route, service_area, closest_facilities,
    )

    # 收集分析所需的坐标，用于图层匹配
    need_coords = []
    event_coords = []
    try:
        if origin:
            need_coords.append(_parse_coord(origin))
        if destination:
            need_coords.append(_parse_coord(destination))
        if facility:
            need_coords.append(_parse_coord(facility))
        if analysis_type == "closest_facility" and events:
            event_coords = [_parse_coord(value.strip()) for value in events.split(";")]
            need_coords.extend(event_coords)
    except ValueError as e:
        return f"坐标参数错误: {e}"

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
            return (f"服务区分析完成：{area_str}；地图边界为近似范围"
                    "（可达路网节点凸包 + 0.001°缓冲，不是逐道路可达边界），已加载到地图")

        elif analysis_type == "closest_facility":
            if not origin:
                return "最近设施分析需要 origin（事件点）和已注册的设施图层"
            o = _parse_coord(origin)
            fac_list = event_coords
            if not fac_list:
                return "请通过 events 参数提供设施点坐标（分号分隔）"
            result = closest_facilities(geojson, o, fac_list, n)
            if "error" in result:
                skipped = result.get("unsnapped_facility_indices", [])
                unreachable = result.get("unreachable_facility_indices", [])
                details = []
                if skipped:
                    details.append("超出 500 m 吸附距离的设施序号（从 1 开始）：" + ", ".join(str(i + 1) for i in skipped))
                if unreachable:
                    details.append("路网不可达的设施序号（从 1 开始）：" + ", ".join(str(i + 1) for i in unreachable))
                suffix = "；" + "；".join(details) if details else ""
                return f"最近设施分析失败: {result['error']}{suffix}"
            _push_layer(f"最近设施_{layer_name}", {
                "type": "FeatureCollection",
                "features": result["paths"],
            })
            lines = [f"最近设施分析完成（前 {len(result['summary'])} 条）："]
            for s in result["summary"]:
                lines.append(f"  #{s['rank']} 设施{s['facility_idx']}：{s['distance_km']} km")
            skipped = result.get("unsnapped_facility_indices", [])
            unreachable = result.get("unreachable_facility_indices", [])
            if skipped:
                lines.append("未吸附设施序号（从 1 开始，未纳入结果）：" + ", ".join(str(i + 1) for i in skipped))
            if unreachable:
                lines.append("路网不可达设施序号（从 1 开始，未纳入结果）：" + ", ".join(str(i + 1) for i in unreachable))
            return "\n".join(lines)

        else:
            return f"不支持的分析类型：{analysis_type}，可选：route / service_area / closest_facility"

    except Exception as e:
        return f"网络分析失败: {str(e)[:300]}"


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
    if len(parts) != 2:
        raise ValueError(f"坐标格式错误，需要 '经度,纬度' 格式，收到: '{s}'")
    try:
        longitude, latitude = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        raise ValueError(f"坐标值非数字，收到: '{s}'")
    if (not math.isfinite(longitude) or not math.isfinite(latitude)
            or not -180 <= longitude <= 180 or not -90 <= latitude <= 90):
        raise ValueError(f"经纬度超出有效范围，收到: '{s}'")
    return longitude, latitude


def _get_utm_crs(lon: float, lat: float) -> str:
    """根据经纬度计算标准 UTM 投影坐标系，带号严格约束在 1~60 之间。"""
    utm_zone = int((lon + 180) / 6) + 1
    utm_zone = max(1, min(60, utm_zone))
    return f"EPSG:{32600 + utm_zone}" if lat >= 0 else f"EPSG:{32700 + utm_zone}"


def _local_utm_extent_error(bounds) -> str | None:
    if not all(math.isfinite(float(value)) for value in bounds):
        return "输入坐标包含非有限值，无法执行局部 UTM 分析"
    if bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90:
        return "输入坐标超出 WGS84 经纬度范围（经度 -180°–180°，纬度 -90°–90°）"
    if bounds[2] - bounds[0] > 180:
        return "输入范围跨越日期变更线，单一局部 UTM 投影不适用"
    if bounds[2] - bounds[0] > 6:
        return "输入范围超过 6° 经度，单一局部 UTM 投影不适用，请按区域分区处理"
    if bounds[1] < -80 or bounds[3] > 84:
        return "输入范围超出 UTM 投影适用纬度（80°S–84°N）"
    return None


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


def _to_local_metric_gdf(gdf):
    """把局部地理数据转到覆盖范围对应的 UTM 米制坐标系。"""
    extent_error = _local_utm_extent_error(gdf.total_bounds)
    if extent_error:
        raise ValueError(extent_error)
    crs = gdf.estimate_utm_crs()
    if crs is None:
        raise ValueError("无法为当前图层范围确定合适的米制投影")
    return gdf.to_crs(crs)


def _spatial_feature_coordinates(gdf):
    """为每个点要素返回一个坐标，避免 MultiPoint 顶点数与属性行数不一致。"""
    geometry = gdf.geometry
    if geometry.isna().any() or geometry.is_empty.any():
        raise ValueError("图层含空几何，请先清理")
    if not geometry.geom_type.isin(["Point", "MultiPoint"]).all():
        raise ValueError("该分析只支持点图层；线/面请先执行 spatial_centroid 取质心")
    if geometry.geom_type.eq("Point").all():
        return geometry.get_coordinates().values
    return geometry.centroid.get_coordinates().values


def _gdf_to_layer(gdf, name: str, style: dict = None, provenance: dict = None):
    """将 GeoDataFrame 转为 GeoJSON，推送到地图并注册"""
    import json
    geojson_data = json.loads(gdf.to_json())
    geojson_data["name"] = name
    # Registration validates and adds stable FIDs in place. Validate a copy first so
    # invalid output never enters the pending response, while the pushed GeoJSON
    # keeps its existing pre-registration shape.
    _register_layer(name, copy.deepcopy(geojson_data), provenance=provenance)
    _push_layer(name, geojson_data, style=style, provenance=provenance)


def _gdf_area_km2(gdf, unique=False):
    """计算 GeoDataFrame 的总面积（平方千米）。
    输入为 EPSG:4326 经纬度时，转到 EPSG:6933 全球等面积投影再求和，
    避免把经纬度 degree² 直接当平方米。unique=True 时统计去重覆盖面积，
    防止叠置产物的重叠记录重复计入覆盖比例。失败时返回 None。"""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            crs = getattr(gdf, "crs", None)
            if crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            ea = gdf.to_crs("EPSG:6933")
            if unique:
                merged = ea.geometry.union_all() if hasattr(ea.geometry, 'union_all') else ea.geometry.unary_union
                return float(merged.area) / 1e6
            return float(ea.geometry.area.sum()) / 1e6
    except Exception:
        return None


# ============================================================
# 工具: spatial_buffer — 缓冲区分析
# ============================================================

@tool
def spatial_buffer(layer_name: str, distance: float, unit: str = "m", dissolve: bool = False) -> str:
    """为矢量图层创建缓冲区并加载到地图（按范围中心选用局部 UTM 米制投影）。
    - layer_name: 图层名。
    - distance: 有限且大于零的缓冲距离，适用于局部范围分析。
    - unit: 'm'(米,默认) 或 'km'(千米)。
    - dissolve: 是否融合重叠缓冲区多边形（默认 False，保留各要素独立缓冲区）。"""
    try:
        from backend.services.tool_args_guard import validate_tool_args
        normalized, _ = validate_tool_args("spatial_buffer", {"unit": unit})
        unit = normalized["unit"]
        if unit not in ("m", "km"):
            return f"缓冲区分析失败: 不支持的距离单位「{unit}」，仅支持 m 或 km"
        distance_m = distance * 1000 if unit == "km" else distance
        if not math.isfinite(distance_m) or distance_m <= 0:
            return "缓冲区分析失败: 缓冲距离及换算后的米数必须为有限正数"
        import geopandas as gpd
        from backend.services.spatial_robust import repair_geometry, estimate_tier, robust_note
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        gdf, rstats = repair_geometry(gdf)
        if len(gdf) == 0:
            return f"缓冲区分析失败: 图层「{name}」没有有效几何"
        tier = estimate_tier(gdf)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
        # 用 bounds 中心确定 UTM 带号（避免在 geographic CRS 下计算 centroid 的 warning）
        _b = gdf.total_bounds
        extent_error = _local_utm_extent_error(_b)
        if extent_error:
            return f"缓冲区分析失败: {extent_error}"
        lon, lat = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2
        crs_utm = _get_utm_crs(lon, lat)
        gdf_utm = gdf.to_crs(crs_utm)
        _cstats = None
        if tier["tier"] == "chunked":
            _buf_parts = []
            _batch_count = min(16, len(gdf_utm))
            _batch_size = math.ceil(len(gdf_utm) / _batch_count)
            _okc = 0
            _attempted_batches = 0
            for _start in range(0, len(gdf_utm), _batch_size):
                _sub = gdf_utm.iloc[_start:_start + _batch_size]
                _attempted_batches += 1
                try:
                    _buffered = _sub.copy()
                    _buffered["geometry"] = _sub.geometry.buffer(distance_m)
                    _buf_parts.append(_buffered)
                    _okc += 1
                except Exception:
                    pass
            import pandas as _pd
            _cstats = {
                "cells": _attempted_batches,
                "ok_cells": _okc,
                "failed_cells": _attempted_batches - _okc,
            }
            if _buf_parts:
                gdf_utm = _pd.concat(_buf_parts, ignore_index=True)
                gdf_utm = gpd.GeoDataFrame(gdf_utm, geometry="geometry", crs=crs_utm)
            else:
                return f"缓冲区分析失败: 所有分批缓冲均失败（{_cstats['failed_cells']} 批）"
        else:
            gdf_utm["geometry"] = gdf_utm.geometry.buffer(distance_m)
        if dissolve:
            gdf_utm = gpd.GeoDataFrame({"geometry": [gdf_utm.union_all()]}, geometry="geometry", crs=crs_utm)
        gdf_wgs = gdf_utm.to_crs("EPSG:4326")
        result_name = f"{name}_缓冲区"
        provenance = {
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {
                "tool": "spatial_buffer",
                "source_layer": name,
                "parameters": {"distance": float(distance), "unit": unit, "dissolve": bool(dissolve)},
            },
        }
        _gdf_to_layer(gdf_wgs, result_name, style={
            "color": "#2563eb", "fillColor": "#60a5fa",
            "weight": 2, "opacity": 0.9, "fillOpacity": 0.06,
        }, provenance=provenance)
        _note = robust_note(rstats, tier, _cstats)
        return f"已为「{name}」创建{distance}{unit}缓冲区，{len(gdf_wgs)} 个要素，已加载到地图{_note}"
    except Exception as e:
        import traceback
        return f"缓冲区分析失败: {str(e)[:300]}\n{traceback.format_exc()[:200]}"


# ============================================================
# 工具: spatial_multi_ring_buffer — 多环缓冲区
# ============================================================

@tool
def spatial_multi_ring_buffer(layer_name: str, distances: str, unit: str = "m", dissolve: bool = False) -> str:
    """为指定图层创建多环缓冲区。distances 为逗号分隔的距离值（如"100,200,500"），每个距离生成一环。
    距离必须为有限正数，使用局部 UTM 米制投影。
    unit: m(米)/km(公里)；dissolve: 是否融合重叠缓冲区。所有环合并为单一图层。"""
    try:
        from backend.services.tool_args_guard import validate_tool_args
        normalized, _ = validate_tool_args("spatial_multi_ring_buffer", {"unit": unit})
        unit = normalized["unit"]
        if unit not in ("m", "km"):
            return f"多环缓冲区失败: 不支持的距离单位「{unit}」，仅支持 m 或 km"
        parts = distances.split(",")
        if len(parts) > 20:
            return f"多环缓冲区失败: 最多支持 20 个距离，当前 {len(parts)} 个"
        try:
            dist_list = [float(d.strip()) for d in parts]
        except ValueError:
            return '多环缓冲区失败: 每项距离必须为有限正数，如"100,200,500"'
        if any(not math.isfinite(d * 1000 if unit == "km" else d) or d <= 0 for d in dist_list):
            return "多环缓冲区失败: 每项距离及换算后的米数必须为有限正数"
        if len(set(dist_list)) != len(dist_list):
            return "多环缓冲区失败: 距离不能重复，否则会生成重复环带"

        import geopandas as gpd
        import pandas as pd
        import warnings

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name

        # 用 bounds 中心确定 UTM 带号（避免 geographic CRS 下计算 centroid 的 warning）
        _b = gdf.total_bounds
        extent_error = _local_utm_extent_error(_b)
        if extent_error:
            return f"多环缓冲区失败: {extent_error}"
        lon, lat = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2
        crs_utm = _get_utm_crs(lon, lat)
        gdf_utm = gdf.to_crs(crs_utm)

        distance_by_m = {d * 1000 if unit == "km" else d: d for d in dist_list}
        ring_geometry_by_m = {}
        previous_outer = None
        for distance_m in sorted(distance_by_m):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                buffered = gdf_utm.geometry.buffer(distance_m)
            if dissolve:
                outer = buffered.union_all()
                inner = previous_outer.union_all() if previous_outer is not None else None
                ring_geometry_by_m[distance_m] = outer.difference(inner) if inner is not None else outer
            else:
                ring_geometry_by_m[distance_m] = (
                    buffered.difference(previous_outer) if previous_outer is not None else buffered
                )
            previous_outer = buffered

        rings = []
        for i, d in enumerate(dist_list):
            distance_m = d * 1000 if unit == "km" else d
            geometry = ring_geometry_by_m[distance_m]
            if dissolve:
                ring = gpd.GeoDataFrame({"geometry": [geometry], "distance": d, "ring": i + 1},
                                        geometry="geometry", crs=crs_utm)
            else:
                ring = gpd.GeoDataFrame({"geometry": geometry, "distance": d, "ring": i + 1}, crs=crs_utm)
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

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

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
        from shapely import affinity
        import warnings

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            center = gdf.dissolve().centroid.iloc[0]

        gdf.geometry = gdf.geometry.rotate(angle, origin=(center.x, center.y), use_radians=False)

        geojson_data = gdf.__geo_interface__
        geojson_data["name"] = layer_name
        _update_registered_layer_data(layer_name, geojson_data)
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

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

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
            crs_utm = _get_utm_crs(lon, lat)
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
# 工具: spatial_intersect — 空间相交
# ============================================================

@tool
def spatial_intersect(layer_a: str, layer_b: str) -> str:
    """两矢量图层的空间叠置求交分析，提取共同重叠部分并合并双方属性，生成新图层上图。
    - layer_a / layer_b: 待求交的两图层名。"""
    try:
        import geopandas as gpd
        from backend.services.spatial_robust import repair_geometry, estimate_tier, chunked_overlay, robust_note
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        gdf_a, rsa = repair_geometry(gdf_a)
        gdf_b, rsb = repair_geometry(gdf_b)
        rstats = {"repaired": rsa["repaired"] + rsb["repaired"],
                   "dropped": rsa["dropped"] + rsb["dropped"]}
        if len(gdf_a) == 0 or len(gdf_b) == 0:
            return f"相交分析失败: 输入图层没有有效几何"
        tier = estimate_tier(gdf_a if len(gdf_a) >= len(gdf_b) else gdf_b)
        _cstats = None
        if tier["tier"] == "chunked":
            result, _cstats = chunked_overlay(
                gdf_a, gdf_b, lambda a, b: gpd.overlay(a, b, how="intersection", keep_geom_type=False)
            )
        else:
            result = gpd.overlay(gdf_a, gdf_b, how="intersection", keep_geom_type=False)
        if result.empty:
            return f"「{name_a}」和「{name_b}」没有重叠区域"
        result_name = f"{name_a}_∩_{name_b}"
        _gdf_to_layer(result, result_name, provenance={
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {"tool": "spatial_intersect", "source_layer": name_a, "other_layer": name_b},
        })
        # 按去重覆盖面积计算比例；叠置记录保留属性组合，不合并要素。
        has_polygonal_result = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        res_area = _gdf_area_km2(result, unique=True) if has_polygonal_result else None
        area_a = _gdf_area_km2(gdf_a, unique=True) if has_polygonal_result else None
        area_b = _gdf_area_km2(gdf_b, unique=True) if has_polygonal_result else None
        stat = [f"相交分析完成，结果图层「{result_name}」已加载到地图。",
                f"- 相交要素数：{len(result)}"]
        if res_area is not None:
            stat.append(f"- 相交覆盖面积（去除重叠）：{res_area:.4f} 平方千米")
            if area_a:
                stat[-1] += f"，占「{name_a}」的 {res_area/area_a*100:.2f}%"
            if area_b:
                stat.append(f"- 占「{name_b}」面积的 {res_area/area_b*100:.2f}%")
        stat.append(f"- 输入图层：{name_a}（{len(gdf_a)} 要素）、{name_b}（{len(gdf_b)} 要素）")
        stat.append(robust_note(rstats, tier, _cstats).strip("（）") or None)
        return "\n".join([s for s in stat if s])
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
        from backend.services.spatial_robust import repair_geometry, estimate_tier, robust_note
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        gdf_a, rsa = repair_geometry(gdf_a)
        gdf_b, rsb = repair_geometry(gdf_b)
        rstats = {"repaired": rsa["repaired"] + rsb["repaired"],
                   "dropped": rsa["dropped"] + rsb["dropped"]}
        if len(gdf_a) == 0 or len(gdf_b) == 0:
            return f"合并失败: 输入图层没有有效几何"
        tier = estimate_tier(gdf_a if len(gdf_a) >= len(gdf_b) else gdf_b)
        _cstats = None
        # union 的 B 独有区域依赖完整 A 图层；按 A 分批会重复生成不同范围的 B 差集。
        result = gpd.overlay(gdf_a, gdf_b, how="union", keep_geom_type=False)
        result_name = f"{name_a}__{name_b}"
        _gdf_to_layer(result, result_name, provenance={
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {"tool": "spatial_union", "source_layer": name_a, "other_layer": name_b},
        })
        _note = robust_note(rstats, tier, _cstats)
        return f"合并完成：{len(result)} 个要素，已加载到地图{_note}"
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
        from backend.services.spatial_robust import repair_geometry, estimate_tier, chunked_overlay, robust_note
        gdf_a, name_a = _layer_to_gdf(layer_a)
        if gdf_a is None: return name_a
        gdf_b, name_b = _layer_to_gdf(layer_b)
        if gdf_b is None: return name_b
        gdf_a, rsa = repair_geometry(gdf_a)
        gdf_b, rsb = repair_geometry(gdf_b)
        rstats = {"repaired": rsa["repaired"] + rsb["repaired"],
                   "dropped": rsa["dropped"] + rsb["dropped"]}
        if len(gdf_a) == 0 or len(gdf_b) == 0:
            return f"差异分析失败: 输入图层没有有效几何"
        tier = estimate_tier(gdf_a if len(gdf_a) >= len(gdf_b) else gdf_b)
        _cstats = None
        if tier["tier"] == "chunked":
            result, _cstats = chunked_overlay(gdf_a, gdf_b, lambda a, b: gpd.overlay(a, b, how="difference"))
        else:
            result = gpd.overlay(gdf_a, gdf_b, how="difference")
        if result.empty:
            return f"「{name_a}」完全被「{name_b}」覆盖，无剩余部分"
        result_name = f"{name_a}_减_{name_b}"
        _gdf_to_layer(result, result_name, provenance={
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {"tool": "spatial_difference", "source_layer": name_a, "other_layer": name_b},
        })
        has_polygonal_result = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        res_area = _gdf_area_km2(result) if has_polygonal_result else None
        area_a = _gdf_area_km2(gdf_a) if has_polygonal_result else None
        stat = [f"差异分析完成，结果图层「{result_name}」已加载到地图。",
                f"- 剩余要素数：{len(result)}"]
        if res_area is not None:
            line = f"- 剩余面积：{res_area:.4f} 平方千米"
            if area_a:
                line += f"（占「{name_a}」的 {res_area/area_a*100:.2f}%）"
            stat.append(line)
        stat.append(robust_note(rstats, tier, _cstats).strip("（）") or None)
        return "\n".join([s for s in stat if s])
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
        from backend.services.spatial_robust import repair_geometry, estimate_tier, chunked_overlay, robust_note
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        clip_gdf, clip_name = _layer_to_gdf(clip_layer)
        if clip_gdf is None: return clip_name
        gdf, rsa = repair_geometry(gdf)
        clip_gdf, rsb = repair_geometry(clip_gdf)
        rstats = {"repaired": rsa["repaired"] + rsb["repaired"],
                   "dropped": rsa["dropped"] + rsb["dropped"]}
        if len(gdf) == 0 or len(clip_gdf) == 0:
            return f"裁剪失败: 输入图层没有有效几何"
        tier = estimate_tier(gdf if len(gdf) >= len(clip_gdf) else clip_gdf)
        _cstats = None
        if tier["tier"] == "chunked":
            result, _cstats = chunked_overlay(gdf, clip_gdf, lambda a, b: gpd.clip(a, b))
        else:
            result = gpd.clip(gdf, clip_gdf)
        if result.empty:
            return f"裁剪后无剩余要素（「{name}」不在「{clip_name}」范围内）"
        result_name = f"{name}_裁剪"
        _gdf_to_layer(result, result_name, provenance={
            "provider": "gis_worktable",
            "kind": "analysis_result",
            "processing": {"tool": "spatial_clip", "source_layer": name, "clip_layer": clip_name},
        })
        has_polygonal_result = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        res_area = _gdf_area_km2(result) if has_polygonal_result else None
        src_area = _gdf_area_km2(gdf) if has_polygonal_result else None
        stat = [f"裁剪完成，结果图层「{result_name}」已加载到地图。",
                f"- 裁剪后要素数：{len(result)}"]
        if res_area is not None:
            line = f"- 裁剪后面积：{res_area:.4f} 平方千米"
            if src_area:
                line += f"（占原图层的 {res_area/src_area*100:.2f}%）"
            stat.append(line)
        stat.append(robust_note(rstats, tier, _cstats).strip("（）") or None)
        return "\n".join([s for s in stat if s])
    except Exception as e:
        return f"裁剪失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_centroid — 质心提取
# ============================================================

@tool
def spatial_centroid(layer_name: str) -> str:
    """在局部米制投影中提取线/面质心并还原原 CRS，返回点图层。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        if gdf.geometry.geom_type.eq("Point").all():
            centroids = gdf.copy()
        else:
            metric_gdf = _to_local_metric_gdf(gdf)
            centroids = metric_gdf.copy()
            centroids["geometry"] = metric_gdf.geometry.centroid
            centroids = centroids.to_crs(gdf.crs)
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
        if not math.isfinite(tolerance) or tolerance <= 0:
            return "简化失败: tolerance 必须为有限正数（单位：度）"
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
        if group_by and group_by not in gdf.columns:
            return f"融合失败: 图层「{name}」不存在字段「{group_by}」，未创建结果图层"
        if group_by:
            result = gdf.dissolve(by=group_by, aggfunc="first", dropna=False).reset_index()
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
        if isinstance(n, bool) or n < 0:
            return "采样失败: n 必须是非负整数"
        if not math.isfinite(frac) or frac < 0:
            return "采样失败: frac 必须是 0 到 1 之间的有限比例"
        if n > 0 and frac > 0:
            return "采样失败: n 和 frac 只能指定一个"
        if n > 0:
            n = min(n, len(gdf))
            sampled = gdf.sample(n=n)
        elif frac > 0:
            if frac > 1:
                return "采样失败: frac 必须不大于 1"
            sampled = gdf.sample(frac=frac)
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
    """查找 target_layer 中距离 layer_name 要素 distance 米以内的要素。
    使用两个图层范围共同估算的局部 UTM 投影；适用于局部区域，跨 UTM 带或跨日期变更线的数据应先分区。
    """
    try:
        import geopandas as gpd
        if isinstance(distance, bool):
            return "近邻查找失败: distance 必须是有限的非负米数"
        distance = float(distance)
        if not math.isfinite(distance) or distance < 0:
            return "近邻查找失败: distance 必须是有限的非负米数"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None: return name_t
        combined = gpd.GeoDataFrame(
            {"geometry": list(gdf.geometry) + list(gdf_t.geometry)},
            geometry="geometry",
            crs=gdf.crs,
        )
        metric_crs = combined.estimate_utm_crs()
        if metric_crs is None:
            return "近邻查找失败: 无法根据两个图层范围确定局部米制投影"
        gdf_u = gdf.to_crs(metric_crs)
        gdf_tu = gdf_t.to_crs(metric_crs)
        near_geometries = gdf_u.geometry if distance == 0 else gdf_u.geometry.buffer(distance)
        gdf_u_buf = gpd.GeoDataFrame(
            {"geometry": near_geometries}, geometry="geometry", crs=metric_crs,
        )
        hits = gpd.sjoin(gdf_tu, gdf_u_buf, how="inner", predicate="intersects")
        if hits.empty:
            return f"「{name_t}」中未找到距离「{name}」{distance}m 以内的要素"
        result = gdf_t.iloc[hits.index.unique()].copy()
        result_name = f"{name_t}_附近"
        _gdf_to_layer(result, result_name)
        return f"找到 {len(result)} 个距离{distance}m 以内的要素，已加载到地图"
    except Exception as e:
        return f"近邻查找失败: {str(e)[:300]}"


@tool
def nearest_pair(
    layer_name: str,
    target_layer: str = "",
    feature_filter: str = "",
    target_filter: str = "",
) -> str:
    """查找同一图层或两个不同图层之间距离最近的一对要素，可按属性关键词筛选。

    适用于“图层里最近的一对”“最近的两家医院”“最近的一家麦当劳和一家医院”等问题。
    target_layer 留空时在 layer_name 内比较；填写时在 layer_name 与 target_layer 之间比较。
    feature_filter 和 target_filter 分别用于在对应图层的要素属性中匹配关键词。
    对点要素计算点间距离；对面或线要素以代表点计算距离。距离使用局部 UTM 投影，单位为米。
    """
    try:
        from scipy.spatial import cKDTree

        source, source_name = _layer_to_gdf(layer_name)
        if source is None:
            return source_name
        same_layer = not target_layer
        if same_layer:
            target, target_name = source, source_name
            target_filter = target_filter or feature_filter
        else:
            target, target_name = _layer_to_gdf(target_layer)
            if target is None:
                return target_name
            same_layer = source_name == target_name and (not target_filter or target_filter == feature_filter)

        def select_features(gdf, keyword):
            valid = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
            if keyword and keyword.strip():
                needle = keyword.strip().casefold()
                matched = valid.apply(
                    lambda row: any(
                        needle in str(value).casefold()
                        for value in row.drop(labels="geometry", errors="ignore")
                        if value is not None
                    ),
                    axis=1,
                )
                valid = valid[matched]
            return valid

        left = select_features(source, feature_filter)
        right = select_features(target, target_filter)
        for gdf, name, keyword in ((left, source_name, feature_filter), (right, target_name, target_filter)):
            if gdf.empty:
                subject = f"属性包含「{keyword}」的" if keyword else ""
                return f"图层「{name}」中没有{subject}有效要素"
        insufficient = len(left) < 2 if same_layer else len(left) < 1 or len(right) < 1
        if insufficient:
            return "可比较的要素不足，无法计算最近距离"

        import geopandas as gpd
        combined = gpd.GeoDataFrame(
            {"geometry": list(left.geometry) + list(right.geometry)},
            geometry="geometry",
            crs=left.crs,
        )
        metric_crs = combined.estimate_utm_crs()
        if metric_crs is None:
            return "无法确定用于距离计算的局部投影坐标系"
        left_points = left.to_crs(metric_crs).geometry.representative_point()
        right_points = right.to_crs(metric_crs).geometry.representative_point()
        left_xy = [(point.x, point.y) for point in left_points]
        right_xy = [(point.x, point.y) for point in right_points]
        if same_layer:
            distances, indices = cKDTree(left_xy).query(left_xy, k=2)
            pairs = (
                (float(distance), i, int(j))
                for i, (distance, j) in enumerate(zip(distances[:, 1], indices[:, 1]))
                if i != int(j)
            )
        else:
            distances, indices = cKDTree(right_xy).query(left_xy, k=1)
            pairs = ((float(distance), i, int(j)) for i, (distance, j) in enumerate(zip(distances, indices)))
        distance_m, source_index, target_index = min(pairs, key=lambda item: item[0])

        left_rows = [row for _, row in left.iterrows()]
        right_rows = left_rows if same_layer else [row for _, row in right.iterrows()]
        name_fields = ("name", "医院名称", "poi_name", "NAME", "名称", "name:zh")

        def feature_name(row, index):
            for field in name_fields:
                value = row.get(field)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return f"要素 {index + 1}"

        names = (
            feature_name(left_rows[source_index], source_index),
            feature_name(right_rows[target_index], target_index),
        )
        distance_text = f"{distance_m:.1f} 米" if distance_m < 1000 else f"{distance_m / 1000:.3f} 千米"
        geometry_note = "点间距离" if all(g.geom_type == "Point" for g in list(left.geometry) + list(right.geometry)) else "要素代表点间距离"
        subject = f"（属性包含「{feature_filter}」）" if feature_filter else ""
        target_subject = f"（属性包含「{target_filter}」）" if target_filter and not same_layer else ""
        return (
            f"图层「{source_name}」{subject}与图层「{target_name}」{target_subject}距离最近的一对是："
            f"{names[0]} 和 {names[1]}；"
            f"{geometry_note}约 {distance_text}（{distance_m:.1f} 米）。"
        )
    except Exception as e:
        return f"最近要素对计算失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_cluster — 空间聚类
# ============================================================

@tool
def spatial_cluster(
    layer_name: str,
    eps: float = 0.01,
    min_samples: int = 3,
    distance_unit: str = "degrees",
) -> str:
    """用 DBSCAN 对点图层做空间聚类。

【参数选择】
- eps：邻域半径，默认按度数计算以兼容旧调用；请求固定地面距离时选择 m 或 km。
- distance_unit：degrees（默认，角度单位）、m 或 km。度数对应地理坐标平面距离，地面换算会随纬度变化。
- min_samples：一个簇最少要素数，通常 3-5。
- 结果添加 cluster 字段，-1 表示噪声点（不属于任何簇，是正常现象）。

【常见坑】
- eps 太小导致所有点都是噪声；请求固定地面距离时请使用 m/km，不要把 measure_distance 返回的米数直接填入默认度数参数。
- eps 太大把所有点聚成一个簇。
- 不适合密度差异极大的数据，可考虑 HDBSCAN（execute_python）。"""
    try:
        if (isinstance(eps, bool) or not isinstance(eps, (int, float))
                or not math.isfinite(eps) or eps <= 0):
            return "聚类失败: eps 必须为有限正数"
        if distance_unit not in ("degrees", "m", "km"):
            return "聚类失败: distance_unit 仅支持 degrees、m 或 km"
        if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1:
            return "聚类失败: min_samples 必须为正整数"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None: return name
        geometries = gdf.geometry
        if geometries.isna().any() or geometries.is_empty.any():
            return "聚类失败: 输入点图层包含空几何，请先清理"
        if not geometries.geom_type.eq("Point").all():
            return "聚类失败: 仅支持 Point 点图层"
        from sklearn.cluster import DBSCAN
        if distance_unit == "degrees":
            coords = geometries.get_coordinates().values
        else:
            extent_error = _local_utm_extent_error(gdf.total_bounds)
            if extent_error:
                return f"聚类失败: {extent_error}"
            coords = _to_local_metric_gdf(gdf).geometry.get_coordinates().values
        if len(coords) < min_samples:
            return f"要素数（{len(coords)}）少于最少点数（{min_samples}），无法聚类"
        eps_value = eps * 1000 if distance_unit == "km" else eps
        if not math.isfinite(eps_value):
            return "聚类失败: eps 换算后超出可计算范围"
        clustering = DBSCAN(eps=eps_value, min_samples=min_samples).fit(coords)
        gdf["cluster"] = clustering.labels_.tolist()
        n_clusters = len(set(clustering.labels_)) - (1 if -1 in clustering.labels_ else 0)
        noise = list(clustering.labels_).count(-1)
        result_name = f"{name}_聚类"
        _gdf_to_layer(gdf, result_name)
        return f"聚类完成：{n_clusters} 个簇，{noise} 个噪声点（eps={eps:g}{distance_unit}），已加载到地图（含 cluster 字段）"
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
        geometries = gdf.geometry
        if geometries.isna().any() or geometries.is_empty.any():
            return "泰森多边形失败: 输入点图层包含空几何，请先清理"
        if not geometries.geom_type.isin(["Point", "MultiPoint"]).all():
            return "泰森多边形失败: 仅支持 Point 或 MultiPoint 点图层"
        unique_sites = set()
        for geometry in geometries:
            site_geometries = [geometry] if geometry.geom_type == "Point" else geometry.geoms
            unique_sites.update((point.x, point.y) for point in site_geometries)
        if len(unique_sites) < 2:
            return "泰森多边形失败: 至少需要 2 个位置不同的点"
        from shapely.ops import voronoi_diagram
        metric_gdf = _to_local_metric_gdf(gdf)
        points = metric_gdf.geometry.union_all()
        polygons = voronoi_diagram(points)
        import geopandas as gpd
        result = gpd.GeoDataFrame(
            {"geometry": list(polygons.geoms)}, geometry="geometry", crs=metric_gdf.crs,
        ).to_crs("EPSG:4326")
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


# ============================================================
# 工具: spatial_join — 空间连接
# ============================================================

@tool
def spatial_join(target_layer: str, join_layer: str, how: str = "left", predicate: str = "intersects") -> str:
    """按空间拓扑关系将 join_layer 的属性连接到 target_layer。
    - target_layer / join_layer: 待连接的目标图层与数据源图层。
    - how: 'left'(保留所有目标要素，未匹配为 NaN) 或 'inner'(仅保留匹配成功的要素)。
    - predicate: 空间拓扑谓词，例如 'intersects'(默认相交) / 'within'(在内部) / 'contains'(包含) / 'touches'(边界接触)。"""
    if predicate == "nearest":
        return "空间连接失败：nearest 不是可用的拓扑谓词。如需查找两图层最近的一对要素，请使用 nearest_pair。"
    try:
        import geopandas as gpd
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None: return name_t
        gdf_j, name_j = _layer_to_gdf(join_layer)
        if gdf_j is None: return name_j
        for frame, side in ((gdf_t, "target"), (gdf_j, "join")):
            if "index_right" in frame.columns:
                column = f"index_right_{side}"
                suffix = 2
                while column in gdf_t.columns or column in gdf_j.columns:
                    column = f"index_right_{side}_{suffix}"
                    suffix += 1
                frame.rename(columns={"index_right": column}, inplace=True)
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
        with _state_lock:
            occupied_names = set(_registered_layers)
            occupied_names.update(
                item.get("name") for item in _pending_layers if isinstance(item.get("name"), str)
            )
            base_name = merged_name
            suffix = 1
            while merged_name in occupied_names:
                merged_name = f"{base_name}_{suffix}"
                suffix += 1
            _gdf_to_layer(result, merged_name)
        return f"合并完成：{len(result)} 个要素（{len(names)} 个图层），结果图层「{merged_name}」已加载到地图"
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
            groups = gdf.groupby(by_field, dropna=False)
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
        import math
        try:
            longitudes = gdf[lon_field].map(float)
            latitudes = gdf[lat_field].map(float)
        except (TypeError, ValueError, OverflowError):
            return "经纬度字段必须包含有效数值，且不能有空值或非数值"
        if not all(math.isfinite(value) for value in longitudes) or not all(math.isfinite(value) for value in latitudes):
            return "经纬度字段必须包含有限数值，且不能有空值或非数值"
        if ((longitudes < -180) | (longitudes > 180)).any() or ((latitudes < -90) | (latitudes > 90)).any():
            return "经纬度超出有效范围：经度 -180 至 180，纬度 -90 至 90"
        gdf["geometry"] = [Point(lon, lat) for lon, lat in zip(longitudes, latitudes)]
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
def spatial_graduated_colors(layer_name: str, field: str, n_classes: int = 5, color_scheme: str = "blues",
                            method: str = "equal_interval", fill_opacity: float = 0.35) -> str:
    """对图层应用分级色彩渲染（Choropleth），按数值字段将要素分为N个等级，每级用不同颜色显示。
    注意：要求图层包含至少2个要素且数值存在差异。如果是单要素图层（如单个行政区边界），无法分级，请使用 datav_boundary 默认边界在地图展示，并结合指标面板或图表交付。
    layer_name: 图层名；field: 数值字段名；n_classes: 分级数（2-20，默认5）；
    color_scheme: 色带 ylorrd(黄橙红/暖色)/blues(蓝)/reds(红)/greens(绿)/oranges(橙)/purples(紫)/ylgnbu(黄绿蓝)/spectral(光谱)；
    method: 分级方法 equal_interval(等间距，默认) 或 quantile(分位数)；fill_opacity: 面填充透明度（0-1，默认0.35）。"""
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
    """更新图层要素的属性值。不指定条件则更新所有要素；只改一条要素时优先用 condition_field="_fid" 和 get_layer_detail 返回的稳定 ID。
    支持数值和文本字段。更新后地图自动同步。
    layer_name: 必须为注册图层完整名称；field: 要更新的字段名；value: 新值（自动转换类型）；
    condition_field: 条件字段名（可选）；condition_value: 条件字段值（可选，仅更新匹配要素）。"""
    try:
        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        import geopandas as gpd
        import json

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field not in gdf.columns:
            return f"图层「{layer_name}」没有字段「{field}」，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"
        if field == "_fid":
            return "_fid 是要素稳定标识，不能修改"

        # 类型转换
        dtype_kind = gdf[field].dtype.kind
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

        # 筛选要更新的行
        if condition_field:
            if condition_field not in gdf.columns:
                return f"条件字段「{condition_field}」不存在"
            cond_kind = gdf[condition_field].dtype.kind
            try:
                if cond_kind in ('i', 'u', 'f'):
                    cond_value = float(condition_value)
                elif cond_kind == 'b':
                    normalized = str(condition_value).strip().casefold()
                    cond_value = normalized == "true" if normalized in ("true", "false") else condition_value
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

        import geopandas as gpd
        import json

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if condition_field not in gdf.columns:
            return f"条件字段「{condition_field}」不存在，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

        cond_kind = gdf[condition_field].dtype.kind
        try:
            if cond_kind in ('i', 'u', 'f'):
                cond_val = float(condition_value)
            elif cond_kind == 'b':
                normalized = str(condition_value).strip().casefold()
                cond_val = normalized == "true" if normalized in ("true", "false") else condition_value
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
        _update_registered_layer_data(layer_name, geojson_data)
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

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
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
        import geopandas as gpd
        import json

        layer_name, info, error = _get_exact_registered_layer(layer_name)
        if error:
            return error

        gdf = gpd.GeoDataFrame.from_features(info["geojson"]["features"], crs="EPSG:4326")
        if gdf.empty:
            return f"图层「{layer_name}」为空"

        if field_name not in gdf.columns:
            return f"字段「{field_name}」不存在，可用字段：{', '.join([c for c in gdf.columns if c != 'geometry'])}"

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
            mask = field_data.astype(str).str.contains(value, case=False, na=False, regex=False)
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


# ============================================================
# 工具: dem_analysis — 坡度/坡向/山体阴影
# ============================================================

def _elevation_unit_to_m(value):
    if not isinstance(value, str) or not value.strip():
        return None
    unit = " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())
    factors = {
        "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
        "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01, "centimetre": 0.01, "centimetres": 0.01,
        "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001, "millimetre": 0.001, "millimetres": 0.001,
        "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0, "kilometre": 1000.0, "kilometres": 1000.0,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "international foot": 0.3048,
        "international feet": 0.3048,
        "us survey foot": 1200.0 / 3937.0, "us survey feet": 1200.0 / 3937.0,
        "us ft": 1200.0 / 3937.0, "ftus": 1200.0 / 3937.0,
    }
    return factors.get(unit)

@tool
def dem_analysis(layer_name: str, analysis: str = "slope") -> str:
    """对 DEM 栅格图层进行地形分析并生成可视化图层。
    - layer_name: DEM 图层名（如已上传的 DEM 名称）。
    - analysis: 分析类型，'slope'(坡度,度0-90) / 'aspect'(坡向,度0-360) / 'hillshade'(山体阴影灰度图)。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件，请先上传DEM"
        import rasterio
        from rasterio.warp import transform_bounds
        from pyproj import CRS as PyprojCRS
        import numpy as np
        from PIL import Image
        out_name = f"{layer_name}_{analysis}"
        with rasterio.open(tif_path) as src:
            dem = src.read(1).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                dem[dem == nodata] = np.nan
            transform = src.transform
            source_crs = src.crs
            source_width, source_height = src.width, src.height
            bounds = list(src.bounds)
            source_tags = {key.upper(): value for key, value in src.tags().items()}
            source_value_units = (
                (src.units[0] if src.units and src.units[0] else None)
                or source_tags.get("VALUE_UNITS")
                or source_tags.get("UNITTYPE")
            )
            source_label = source_tags.get("SOURCE_LABEL") or source_tags.get("SOURCE")
            source_quality_note = source_tags.get("QUALITY_NOTE")
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        elevation_unit_scale = _elevation_unit_to_m(source_value_units)
        if elevation_unit_scale is not None:
            dem *= elevation_unit_scale
        ny, nx = dem.shape
        if source_crs and source_crs.is_geographic:
            # Elevation values are linear while geographic raster pixels are angular.
            # Build the local east/north vectors for both affine pixel axes near
            # the raster centre, including rotated or sheared grids.
            geod = PyprojCRS.from_wkt(source_crs.to_wkt()).get_geod()
            center_x, center_y = transform * (source_width / 2, source_height / 2)
            azimuth_col, _, pixel_col_m = geod.inv(
                center_x, center_y,
                center_x + transform.a, center_y + transform.d,
            )
            azimuth_row, _, pixel_row_m = geod.inv(
                center_x, center_y,
                center_x + transform.b, center_y + transform.e,
            )
            x_col = pixel_col_m * math.sin(math.radians(azimuth_col))
            y_col = pixel_col_m * math.cos(math.radians(azimuth_col))
            x_row = pixel_row_m * math.sin(math.radians(azimuth_row))
            y_row = pixel_row_m * math.cos(math.radians(azimuth_row))
        elif source_crs and source_crs.is_projected:
            # Projected data may use feet (or another linear unit), while DEM
            # elevations are conventionally metres. Normalize the full affine
            # pixel basis to metres before converting grid derivatives to east/north.
            unit_to_m = float(src.crs.linear_units_factor[1])
            x_col, y_col = transform.a * unit_to_m, transform.d * unit_to_m
            x_row, y_row = transform.b * unit_to_m, transform.e * unit_to_m
        else:
            # Retain support for legacy unreferenced rasters whose cell units
            # cannot be inferred; uploaded GeoTIFFs are required to carry a CRS.
            x_col, y_col = transform.a, transform.d
            x_row, y_row = transform.b, transform.e
        pixel_basis = (x_col, y_col, x_row, y_row)
        determinant = x_col * y_row - x_row * y_col
        if (not all(math.isfinite(value) for value in pixel_basis)
                or not math.isfinite(determinant) or determinant == 0):
            return "DEM分析失败: 无法从栅格变换和坐标系确定有效像元基向量"
        # Horn's formula — 3x3 window
        dzdcol = np.full_like(dem, np.nan)
        dzdrow = np.full_like(dem, np.nan)
        # interior cells
        dzdcol[1:-1,1:-1] = (
            (dem[:-2,2:] + 2*dem[1:-1,2:] + dem[2:,2:]) -
            (dem[:-2,:-2] + 2*dem[1:-1,:-2] + dem[2:,:-2])
        ) / 8
        dzdrow[1:-1,1:-1] = (
            (dem[2:,:-2] + 2*dem[2:,1:-1] + dem[2:,2:]) -
            (dem[:-2,:-2] + 2*dem[:-2,1:-1] + dem[:-2,2:])
        ) / 8
        # Grid-axis derivatives are not east/north derivatives for rotated
        # rasters. Apply the inverse-transpose affine Jacobian to recover the
        # gradient in ground coordinates before calculating slope or aspect.
        dzdx = (y_row * dzdcol - y_col * dzdrow) / determinant
        dzdy = (-x_row * dzdcol + x_col * dzdrow) / determinant
        valid = np.isfinite(dzdx) & np.isfinite(dzdy)
        if analysis == "slope":
            data = np.degrees(np.arctan(np.sqrt(dzdx**2 + dzdy**2)))
            data[~valid] = np.nan
            label = "坡度(Slope)"
            cmap = "slope"
        elif analysis == "aspect":
            # 坡向 = 最陡下坡方向的方位角（自正北顺时针）；dzdx、dzdy 已换算为东向和北向梯度。
            data = np.degrees(np.arctan2(-dzdx, -dzdy)) % 360
            data[~valid] = np.nan
            label = "坡向(Aspect)"
            cmap = "aspect"
        elif analysis == "hillshade":
            slope_rad = np.arctan(np.sqrt(dzdx**2 + dzdy**2))
            aspect_rad = np.arctan2(-dzdx, -dzdy)
            zenith = np.radians(45)
            azimuth = np.radians(315)
            data = (
                np.cos(zenith) * np.cos(slope_rad) +
                np.sin(zenith) * np.sin(slope_rad) * np.cos(azimuth - aspect_rad)
            )
            data = np.clip(data, 0, 1) * 255
            data[~valid] = np.nan
            label = "山体阴影(Hillshade)"
            cmap = "hillshade"
        else:
            return f"不支持的analysis类型: {analysis}，可选: slope/aspect/hillshade"
        # 颜色映射
        if analysis == "hillshade":
            preview_band = np.where(valid, data, 0).astype(np.uint8)
            rgb = np.stack([preview_band]*3, axis=-1)
        else:
            import matplotlib
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
        result_units = "°（角度）" if analysis in ("slope", "aspect") else "0–255（相对亮度）"
        raster_path = _write_raster_output(tif_path, out_name, data, metadata={
            "SOURCE_LAYER": layer_name,
            "SOURCE_LABEL": source_label or "GIS WorkTable 栅格分析",
            "SOURCE_VALUE_UNITS": source_value_units or "unknown",
            "SOURCE_URL": source_tags.get("SOURCE_URL"),
            "CITATION": source_tags.get("CITATION"),
            "SOURCE_QUALITY_NOTE": source_quality_note,
            "VERTICAL_DATUM": source_tags.get("VERTICAL_DATUM"),
            "PROCESSING": label,
            "VALUE_UNITS": result_units,
        })
        with rasterio.open(raster_path) as result_src:
            warnings = []
            if not source_value_units:
                warnings.append("源栅格未标注数值单位；地形计算按高程值为米解释，请核实原始数据")
            elif elevation_unit_scale is None:
                warnings.append("源栅格高程单位无法识别；地形计算按数值单位为米解释，请核实原始数据")
            if source_quality_note:
                warnings.append(source_quality_note)
            if source_crs and source_crs.is_geographic:
                warnings.append("经纬度栅格按中心处椭球像元距离换算水平间距；地形结果适用于当前小范围，大范围请使用合适的投影 CRS")
            note = _raster_preview_op(
                result_src, data, out_name, label, preview_image=img,
                source_layer=layer_name, value_units=result_units,
                source_label=source_label, quality_warnings=warnings,
            )
        return f"已生成{label} GeoTIFF：{os.path.basename(raster_path)}；{note}"
    except ImportError as e:
        return f"DEM分析需要依赖库: {str(e)[:200]}，请安装: pip install matplotlib"
    except Exception as e:
        import traceback
        return f"DEM分析失败: {str(e)[:300]}"


# ============================================================
# 工具: ndvi_analysis — NDVI 植被指数
# ============================================================

@tool
def ndvi_analysis(layer_name: str, red_band: int = 3, nir_band: int = 4) -> str:
    """计算归一化植被指数 NDVI = (NIR-Red)/(NIR+Red)。
    - layer_name: GeoTIFF 图层名。
    - red_band: 红光波段序号(从1开始，默认 3；Landsat 8/9为4，Sentinel-2为4)。
    - nir_band: 近红外波段序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。
    输出范围 [-1, 1] 的彩色渲染图层并上图。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
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
            source_tags = {key.upper(): value for key, value in src.tags().items()}
            source_label = source_tags.get("SOURCE_LABEL") or source_tags.get("SOURCE")
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != 'EPSG:4326':
                bounds = list(transform_bounds(src.crs, 'EPSG:4326', *bounds))
        ndvi = (nir - red) / (nir + red + 1e-10)
        ndvi = np.clip(ndvi, -1, 1)
        # 红绿渐变：NDVI=-1→红色，0→黄色，1→绿色
        import matplotlib
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
        out_name = f"{layer_name}_ndvi"
        raster_path = _write_raster_output(tif_path, out_name, ndvi, metadata={
            "SOURCE_LAYER": layer_name, "SOURCE_LABEL": source_label or "GIS WorkTable 栅格分析",
            "PROCESSING": "NDVI 归一化植被指数", "VALUE_UNITS": "无量纲（-1 至 1）",
        })
        with rasterio.open(raster_path) as result_src:
            _raster_preview_op(
                result_src, ndvi, out_name, "NDVI 归一化植被指数", preview_image=img,
                source_layer=layer_name, value_units="无量纲（-1 至 1）", source_label=source_label,
            )
        valid_count = np.sum(valid)
        mean_ndvi = float(np.nanmean(ndvi))
        return f"已生成NDVI栅格图层「{out_name}」，有效像元{valid_count}个，平均NDVI={mean_ndvi:.3f}"
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
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        with rasterio.open(tif_path) as src:
            pixel_count = int(src.width) * int(src.height)
            band_pixel_count = pixel_count * int(src.count)
            if pixel_count > 4_000_000 or band_pixel_count > 16_000_000:
                return (f"栅格计算失败: 当前影像为 {src.width}×{src.height} 像元、{src.count} 波段，"
                        "超过单次处理上限（400 万像元或 1600 万波段像元）；请先裁剪或重采样")
            bands = {}
            for i in range(1, src.count + 1):
                b = src.read(i).astype(np.float64)
                nodata = src.nodata
                if nodata is not None:
                    b[b == nodata] = np.nan
                bands[f"B{i}"] = b
            source_tags = {key.upper(): value for key, value in src.tags().items()}
            source_label = source_tags.get("SOURCE_LABEL") or source_tags.get("SOURCE")
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
        _rc_tree = ast.parse(expression, mode="eval")
        _validate_ast(_rc_tree.body)
        # NumPy may import warning handlers when floating-point errors occur; keep them
        # local to the expression and represent non-finite pixels as raster NoData below.
        with np.errstate(all="ignore"):
            result = eval(compile(_rc_tree, "<safe>", "eval"), {"__builtins__": {}}, safe_dict)
        if not isinstance(result, np.ndarray):
            return f"表达式结果不是栅格数据: {type(result)}"
        result = result.astype(np.float64, copy=True)
        result[~np.isfinite(result)] = np.nan
        if np.all(np.isnan(result)):
            return "计算结果全为NaN，请检查表达式或波段数据"
        vmin, vmax = np.nanmin(result), np.nanmax(result)
        if np.isclose(vmin, vmax):
            rgb = np.full((*result.shape, 3), 128, dtype=np.uint8)
        else:
            norm = (result - vmin) / (vmax - vmin + 1e-10)
            norm = np.clip(norm, 0, 1)
            import matplotlib
            cmap = matplotlib.colormaps['viridis']
            rgba = cmap(norm)
            rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
            nan_mask = np.isnan(result)
            if np.any(nan_mask):
                rgb[nan_mask] = 0
        img = Image.fromarray(rgb)
        out_name = f"{layer_name}_calc"
        raster_path = _write_raster_output(tif_path, out_name, result, metadata={
            "SOURCE_LAYER": layer_name, "SOURCE_LABEL": source_label or "GIS WorkTable 栅格分析",
            "PROCESSING": f"栅格计算: {expression}",
            "VALUE_UNITS": "未推导（取决于表达式与输入单位）",
        })
        with rasterio.open(raster_path) as result_src:
            _raster_preview_op(
                result_src, result, out_name, f"栅格计算: {expression}", preview_image=img,
                source_layer=layer_name, value_units="未推导（取决于表达式与输入单位）",
                source_label=source_label,
                quality_warnings=["栅格计算器不会自动推导表达式的物理单位"],
            )
        return f"已执行 '{expression}'，范围 [{vmin:.2f}, {vmax:.2f}]，结果栅格「{out_name}」已上图并可继续分析"
    except Exception as e:
        return f"栅格计算失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_interpolate — 空间插值（IDW / RBF）
# ============================================================

@tool
def spatial_interpolate(layer_name: str, field: str, method: str = "idw",
                        resolution: int = 200) -> str:
    """对点图层进行空间插值生成连续栅格曲面。

【方法选择】
- idw（反距离加权）：简单快速，精确通过采样点，适合点密集且分布均匀。
- rbf（径向基函数）：更平滑，可处理不规则分布，适合中等数据量。
- 需要估计误差时用克里金（execute_python + pykrige）。

【常见坑】
- 采样点应覆盖研究区，边界外是外推不可靠，用研究区边界裁剪。
- 点太少（<10）结果不可靠。
- resolution 是行列数，支持 2–1024；单次计算最多 5,000 万个网格-样本距离对。
- 单次范围最多覆盖 6° 经度且须在 UTM 纬度范围内；更大区域应分区处理。"""
    try:
        import numpy as np
        import pandas as pd
        max_resolution = 1024
        max_distance_pairs = 50_000_000
        distance_batch_pairs = 1_000_000
        max_rbf_points = 500
        if isinstance(resolution, bool) or not isinstance(resolution, int) or not 2 <= resolution <= max_resolution:
            return f"插值失败: resolution 必须是 2 到 {max_resolution} 之间的整数"
        if method not in {"idw", "rbf"}:
            return f"不支持的方法: {method}，可选 idw / rbf"
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        non_null_geometry = gdf.geometry[gdf.geometry.notna()]
        if non_null_geometry.empty:
            return f"图层 '{name}' 没有有效点几何，无法插值"
        unsupported = sorted(set(non_null_geometry.geom_type) - {"Point", "MultiPoint"})
        if unsupported:
            return f"图层 '{name}' 不含点要素，无法插值"
        if field not in gdf.columns:
            return f"图层 '{name}' 没有字段 '{field}'，可用字段: {', '.join(gdf.columns)}"
        pts = gdf[[field, gdf.geometry.name]].copy()
        pts = pts.to_crs("EPSG:4326")
        # Explode MultiPoint features and keep each observation paired with its value.
        pts = pts.explode(index_parts=False, ignore_index=True)
        numeric_values = pd.to_numeric(pts[field], errors="coerce").to_numpy(dtype=np.float64)
        point_mask = pts.geometry.notna().to_numpy() & (pts.geometry.geom_type == "Point").to_numpy()
        coords = np.asarray(
            [(geometry.x, geometry.y) if is_point and not geometry.is_empty else (np.nan, np.nan)
             for geometry, is_point in zip(pts.geometry, point_mask)],
            dtype=np.float64,
        )
        valid_mask = point_mask & np.isfinite(numeric_values) & np.isfinite(coords).all(axis=1)
        coords = coords[valid_mask]
        values = numeric_values[valid_mask]
        if len(coords) < 3:
            return "至少需要3个具有有效点几何和有限数值属性的采样点进行插值"
        if method == "rbf" and len(coords) > max_rbf_points:
            return f"插值失败: RBF 最多支持 {max_rbf_points} 个有效点，请先抽样或改用 IDW"
        distance_pairs = resolution * resolution * len(coords)
        if distance_pairs > max_distance_pairs:
            return (f"插值失败: 当前网格与样本组合需要 {distance_pairs:,} 次距离计算，"
                    f"超过单次上限 {max_distance_pairs:,}；请降低 resolution 或减少样本点")
        xs = coords[:, 0]
        ys = coords[:, 1]
        center_lon = float((xs.min() + xs.max()) / 2)
        center_lat = float((ys.min() + ys.max()) / 2)
        xmin, ymin, xmax, ymax = xs.min(), ys.min(), xs.max(), ys.max()
        pad_x = (xmax - xmin) * 0.05 or 0.01
        pad_y = (ymax - ymin) * 0.05 or 0.01
        if xmax - xmin + 2 * pad_x > 6:
            return "插值失败: 单次范围超过 6° 经度，请按局部区域分区后再插值"
        if ymin - pad_y < -80 or ymax + pad_y > 84:
            return "插值失败: 当前点范围超出 UTM 适用纬度，请先按区域分区处理"
        if xs.min() < -180 or xs.max() > 180 or ys.min() < -90 or ys.max() > 90:
            return "插值失败: 点坐标超出 EPSG:4326 经纬度范围，请检查输入 CRS"
        metric_crs = _get_utm_crs(center_lon, center_lat)
        from pyproj import Transformer
        to_metric = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True)
        metric_xs, metric_ys = to_metric.transform(xs, ys)
        # 生成规则网格
        # y 方向必须递减生成：栅格与影像的约定是 row 0 = 北（y 最大）。
        # 按 y 递增生成的话 row 0 是南，PNG 交给 Leaflet 叠加后整张图会南北翻转，
        # 高值区显示在地图下方。
        grid_x, grid_y = np.meshgrid(
            np.linspace(xmin - pad_x, xmax + pad_x, resolution),
            np.linspace(ymax + pad_y, ymin - pad_y, resolution)
        )
        grid_metric_x, grid_metric_y = to_metric.transform(grid_x, grid_y)
        if method == "idw":
            # 反距离加权
            from scipy.spatial.distance import cdist
            flat_grid = np.column_stack([grid_metric_x.ravel(), grid_metric_y.ravel()])
            pts_xy = np.column_stack([metric_xs, metric_ys])
            flat_values = np.empty(len(flat_grid), dtype=np.float64)
            rows_per_batch = max(1, distance_batch_pairs // len(pts_xy))
            for start in range(0, len(flat_grid), rows_per_batch):
                stop = min(start + rows_per_batch, len(flat_grid))
                dist = cdist(flat_grid[start:stop], pts_xy)
                np.maximum(dist, 1e-10, out=dist)
                weights = 1.0 / (dist * dist)
                flat_values[start:stop] = np.dot(weights, values) / weights.sum(axis=1)
            z = flat_values.reshape(grid_x.shape)
        elif method == "rbf":
            from scipy import interpolate
            rbf = interpolate.Rbf(metric_xs, metric_ys, values, function='multiquadric')
            flat_x = grid_metric_x.ravel()
            flat_y = grid_metric_y.ravel()
            flat_values = np.empty(len(flat_x), dtype=np.float64)
            rows_per_batch = max(1, distance_batch_pairs // len(coords))
            for start in range(0, len(flat_x), rows_per_batch):
                stop = min(start + rows_per_batch, len(flat_x))
                flat_values[start:stop] = rbf(flat_x[start:stop], flat_y[start:stop])
            z = flat_values.reshape(grid_x.shape)
        vmin, vmax = np.nanmin(z), np.nanmax(z)
        if np.isclose(vmin, vmax):
            return f"插值结果无变化（值={vmin:.2f}）"
        norm = (z - vmin) / (vmax - vmin + 1e-10)
        norm = np.clip(norm, 0, 1)
        import matplotlib
        cmap = matplotlib.colormaps['viridis']
        rgba = cmap(norm)
        rgb = (rgba[:,:,:3] * 255).astype(np.uint8)
        nan_mask = ~np.isfinite(z)
        if np.any(nan_mask):
            rgb[nan_mask] = 0
        from PIL import Image
        img = Image.fromarray(rgb)
        import rasterio
        from rasterio.transform import from_bounds
        transform = from_bounds(xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y, resolution, resolution)
        out_name = os.path.basename(f"{name}_{method}")
        raster_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        raster_values = np.where(np.isfinite(z), z, np.nan).astype("float32")
        with rasterio.open(
            raster_path, "w", driver="GTiff", width=resolution, height=resolution,
            count=1, dtype="float32", crs="EPSG:4326", transform=transform,
            nodata=float("nan"),
        ) as dst:
            dst.write(raster_values, 1)
            dst.set_band_description(1, f"{field} ({method.upper()} interpolation)")
        label = f"空间插值（{method.upper()}，字段 {field}）"
        with rasterio.open(raster_path) as result_src:
            _raster_preview_op(
                result_src, raster_values, out_name, label, preview_image=img,
                source_layer=name, source_label="空间插值",
                quality_warnings=["范围为样本点外接区域扩展 5%；区域外结果属于外推，解释时请谨慎"],
            )
        return (f"已生成并注册 {method.upper()} 插值栅格（{resolution}×{resolution}），"
                f"值范围 [{vmin:.2f}, {vmax:.2f}]；字段单位未提供")
    except Exception as e:
        import traceback
        return f"插值失败: {str(e)[:300]}"


# ============================================================
# 工具: hydrology_analysis — 水文分析
# ============================================================

def _fill_sinks(dem, max_iter: int = 500):
    """填洼：迭代抬升局部洼地，使每个单元都有下坡去处（水文分析前置步骤）。

    约定（与原实现的关键区别）：
    - 只抬高、绝不降低任何栅格值——原地不低于邻域的单元保持不变；
      原实现用 `filled[i,j] > min_nbr` 判定，会把高于邻域的单元降到最低邻域，
      等价于反复做 3x3 最小值滤波（形态学腐蚀），会把 DEM 整体抹平到全局最低点。
    - 边界与 nodata 不参与抬升：边界视为出水口，nodata 视为屏障。

    返回 float64 数组（nodata 位置保持 NaN）。
    """
    import numpy as np
    filled = dem.astype(np.float64).copy()
    ny, nx = filled.shape
    if ny < 3 or nx < 3:
        return filled
    EPS = 1e-6
    for _ in range(max_iter):
        prev = filled.copy()
        inner = filled[1:-1, 1:-1]
        neigh = np.stack([
            filled[:-2, 1:-1], filled[2:, 1:-1], filled[1:-1, :-2], filled[1:-1, 2:],
            filled[:-2, :-2], filled[:-2, 2:], filled[2:, :-2], filled[2:, 2:],
        ])
        neigh = np.where(np.isfinite(neigh), neigh, np.inf)
        min_nbr = neigh.min(axis=0)
        # 仅抬升"低于最低邻域"的洼地单元
        raise_mask = np.isfinite(inner) & np.isfinite(min_nbr) & (inner < min_nbr)
        filled[1:-1, 1:-1] = np.where(raise_mask, min_nbr + EPS, inner)
        if np.allclose(filled, prev, atol=1e-9, equal_nan=True):
            break
    return filled


@tool
def hydrology_analysis(layer_name: str, analysis: str = "flowacc",
                       threshold: int = 100) -> str:
    """对DEM栅格进行水文分析。analysis可选:
    flowdir(流向图), flowacc(汇流累积量), streamnet(河网提取)。
    threshold为河网提取的最小汇流累积量阈值。
    layer_name为上传DEM时创建的图层名。"""
    try:
        import numpy as np
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的GeoTIFF文件"
        import rasterio
        from PIL import Image
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return "水文分析要求输入 GeoTIFF 带有有效 CRS；请先定义 CRS 后重新上传"
            src_crs = src.crs
            transform = src.transform
            dem = src.read(1).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                dem[dem == nodata] = np.nan
        ny, nx = dem.shape
        filled = _fill_sinks(dem)
        # D8 流向编码（1=E,2=NE,4=N,8=NW,16=W,32=SW,64=S,128=SE）
        # 使用简化编码: 0=E,1=NE,2=N,3=NW,4=W,5=SW,6=S,7=SE
        dx = [1, 1, 0, -1, -1, -1, 0, 1]
        dy = [0, -1, -1, -1, 0, 1, 1, 1]
        if src_crs.is_projected:
            unit_to_m = float(src_crs.linear_units_factor[1])
            step_distances = [
                math.hypot(transform.a * x + transform.b * y,
                           transform.d * x + transform.e * y) * unit_to_m
                for x, y in zip(dx, dy)
            ]
            geod = None
        elif src_crs.is_geographic:
            from pyproj import CRS as PyprojCRS
            geod = PyprojCRS.from_user_input(src_crs).get_geod()
            step_distances = None
            if transform.b == 0 and transform.d == 0:
                step_distances = np.empty((ny, 8), dtype=np.float64)
                for row in range(ny):
                    for k, (x, y) in enumerate(zip(dx, dy)):
                        x1, y1 = transform * (0.5, row + 0.5)
                        x2, y2 = transform * (0.5 + x, row + 0.5 + y)
                        step_distances[row, k] = geod.inv(x1, y1, x2, y2)[2]
        else:
            return f"水文分析暂不支持此坐标参考系: {src_crs}"
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
                    if step_distances is not None:
                        dist = (step_distances[i, k]
                                if isinstance(step_distances, np.ndarray) else step_distances[k])
                    else:
                        x1, y1 = transform * (j + 0.5, i + 0.5)
                        x2, y2 = transform * (j + 0.5 + dx[k], i + 0.5 + dy[k])
                        dist = geod.inv(x1, y1, x2, y2)[2]
                    if not math.isfinite(dist) or dist <= 0:
                        continue
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
        if analysis == "flowdir":
            # 流向可视化（按角度色环）
            # D8 codes describe raster-neighbor offsets; rotated grids do not
            # have E/N aligned with their column/row axes. Color each direction
            # using its local true-compass bearing near the raster centre.
            from pyproj import CRS as PyprojCRS, Transformer
            to_wgs84 = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
            geod_wgs84 = PyprojCRS.from_epsg(4326).get_geod()
            center_col, center_row = nx / 2, ny / 2
            center_x, center_y = transform * (center_col, center_row)
            center_lon, center_lat = to_wgs84.transform(center_x, center_y)
            angle_map = np.empty(8, dtype=np.float64)
            for k, (step_x, step_y) in enumerate(zip(dx, dy)):
                neighbor_x, neighbor_y = transform * (center_col + step_x, center_row + step_y)
                neighbor_lon, neighbor_lat = to_wgs84.transform(neighbor_x, neighbor_y)
                bearing = geod_wgs84.inv(center_lon, center_lat, neighbor_lon, neighbor_lat)[0]
                angle_map[k] = bearing % 360
            dir_deg = np.full_like(dem, np.nan, dtype=np.float64)
            for k in range(8):
                dir_deg[direction == k] = angle_map[k]
            import matplotlib
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
            import matplotlib
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
        stem = _safe_layer_export_stem(layer_name)
        base_name = f"{stem}_{analysis}"
        out_name = base_name
        suffix = 2
        while (os.path.exists(os.path.join(upload_dir, out_name + ".tif"))
               or os.path.exists(os.path.join(upload_dir, out_name + ".png"))):
            out_name = f"{base_name}_{suffix}"
            suffix += 1
        if analysis == "flowdir":
            result_data = direction.astype(np.float32)
            result_data[direction < 0] = np.nan
            value_units = "D8 raster-neighbor code (0=col+, 1=col+row-, 2=row-, 3=col-row-, 4=col-, 5=col-row+, 6=row+, 7=col+row+)"
            quality_warnings = ["采用当前工具的简化 D8 邻域流向算法；结果未经外部水文基准验证"]
        elif analysis == "flowacc":
            result_data = flowacc.astype(np.float32)
            result_data[~valid_cells] = np.nan
            value_units = "upstream pixel count"
            quality_warnings = ["汇流累积量按像元计数，不代表流量或面积；结果未经外部水文基准验证"]
        else:
            result_data = stream_cells.astype(np.float32)
            result_data[~valid_cells] = np.nan
            value_units = "binary stream mask (0/1)"
            quality_warnings = ["河网由简化 D8 汇流像元阈值提取；结果未经外部水文基准验证"]
        raster_context = _raster_preview_context(layer_name, value_units=value_units)
        raster_context["quality_warnings"] = quality_warnings
        with rasterio.open(tif_path) as src:
            note = _raster_preview_op(
                src, result_data, out_name, label, preview_image=img,
                **raster_context,
            )
        return f"已生成水文分析图层 '{label}'；{note}"
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


# ============================================================
# 工具: view_3d_terrain — 3D 地形
# ============================================================

@tool
def view_3d_terrain(layer_name: str, exaggeration: float = 2.0) -> str:
    """从DEM生成3D地形交互视图。layer_name为DEM图层名。
    exaggeration为垂直夸大系数（默认2.0）。
    结果在聊天窗口展示 Three.js 3D 场景。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
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
        record_tool_artifact(fname, fpath, artifact_type="html")
        _pending_images.append({
            "name": fname,
            "path": fpath,
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
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
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
        record_tool_artifact(fname, fpath, artifact_type="image")
        _pending_images.append({
            "name": fname,
            "path": fpath,
            "type": "png",
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
    """对面要素图层执行几何拓扑检查并自动修复（仅支持面图层）。
    - layer_name: 待检查面图层名。自动用 make_valid 修复自相交与环方向，报告要素间重叠与缝隙。"""
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
                        except Exception:
                            pass
            try:
                all_valid = [g for _, g in polys]
                if len(all_valid) >= 2:
                    merged = unary_union(all_valid)
                    envelope = Polygon(merged.exterior)
                    gaps = envelope.difference(merged)
                    if gaps is not None and not gaps.is_empty:
                        # 面积计算：若为地理CRS，转换到EPSG:6933等面积投影
                        _src_crs = gdf.crs
                        _is_geographic = _src_crs is not None and _src_crs.is_geographic
                        def _gap_area(geom):
                            if _is_geographic:
                                from shapely.ops import transform
                                from pyproj import Transformer
                                _t = Transformer.from_crs(_src_crs, "EPSG:6933", always_xy=True)
                                return transform(_t.transform, geom).area
                            return geom.area
                        if gaps.geom_type == "GeometryCollection":
                            for g in gaps.geoms:
                                if not g.is_empty and g.geom_type in ("Polygon",) and g.area > 1e-10:
                                    rep = g.representative_point()
                                    issues.append({
                                        "type": "Feature",
                                        "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                                        "properties": {"type": "缝隙", "area_m2": round(_gap_area(g), 2)}
                                    })
                        elif gaps.geom_type == "Polygon" and gaps.area > 1e-10:
                            rep = gaps.representative_point()
                            issues.append({
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [rep.x, rep.y]},
                                "properties": {"type": "缝隙", "area_m2": round(_gap_area(gaps), 2)}
                            })
            except Exception:
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
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
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
        name = f"{layer_name}_contour"
        fc = {"type": "FeatureCollection", "features": features}
        # 必须走统一的推送/注册接口：_push_layer 生成 {"geojson":...} 供前端渲染，
        # _register_layer 写入 geojson/feature_count/geometry_types/bbox 供后续工具读取。
        # 原实现手写 {"type","name"} 既缺 geojson（前端不渲染），也导致 _layer_to_gdf 报"图层为空"。
        _push_layer(name, fc)
        _register_layer(name, fc)
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

        def _resolve_crs(name: str, first_lng=None) -> str:
            """CRS 别名 → EPSG；utm_auto 按第一个点经度落带"""
            n = str(name).lower().strip()
            m = {"wgs84": "EPSG:4326", "mercator": "EPSG:3857",
                 "web_mercator": "EPSG:3857", "gcj02": "EPSG:4326"}
            if n in m:
                return m[n]
            if n in ("utm_auto", "utm"):
                if first_lng is None:
                    raise ValueError("utm_auto 需要至少一个坐标来推算投影带")
                zone = int((first_lng + 180) / 6) + 1
                return f"EPSG:{32600 + zone}"   # 北半球 UTM
            return name

        parts_raw = coords.replace("，", ",").replace("；", ";").split(";")
        first_lng = None
        for part in parts_raw:
            xy = part.strip().split(",")
            if len(xy) == 2:
                try:
                    v0, v1 = float(xy[0]), float(xy[1])
                    if -180 <= v0 <= 180 and -90 <= v1 <= 90:
                        first_lng = v0
                        break
                except ValueError:
                    continue
        p1 = _resolve_crs(source_crs, first_lng)
        p2 = _resolve_crs(target_crs, first_lng)
        if p1 == p2:
            return f"源和目标CRS相同: {source_crs} = {target_crs}, 无需转换"
        transformer = pyproj.Transformer.from_crs(p1, p2, always_xy=True)
        results = []
        for part in parts_raw:
            xy = part.strip().split(",")
            if len(xy) != 2:
                continue
            try:
                lng, lat = float(xy[0].strip()), float(xy[1].strip())
                x2, y2 = transformer.transform(lng, lat)
                results.append(f"{x2:.6f},{y2:.6f}")
            except Exception:
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
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
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
                import matplotlib
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
            result_name = f"{name}_MoranI"
            _gdf_to_layer(gdf, result_name)
            hh = cluster.count("HH"); ll = cluster.count("LL")
            hl = cluster.count("HL"); lh = cluster.count("LH")
            return summary + f"\n局部 LISA 已加载到地图：HH热点={hh}，LL冷点={ll}，HL异常={hl}，LH异常={lh}"
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
        result_name = f"{name}_热点"
        _gdf_to_layer(gdf, result_name)
        hot = htype.count("热点"); cold = htype.count("冷点")
        return f"Getis-Ord Gi* 热点分析完成：热点={hot} 个，冷点={cold} 个，不显著={n-hot-cold} 个。已加载到地图（含 gi_z / gi_p / hotspot_type 字段）"
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
        result_name = f"{name}_KDE"
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




# ============================================================
# 工具: 遥感指数扩展 — NDWI / NDBI / EVI / NDMI
# ============================================================

def _calc_spectral_index(layer_name: str, formula_name: str, calc_fn, cmap_name: str,
                         label: str, value_range=(-1.0, 1.0), band_map: dict = None) -> str:
    """通用遥感指数计算：读取 GeoTIFF → 计算指数 → 生成彩色 PNG → 推送到地图。
    calc_fn(bands_dict) -> np.ndarray，bands_dict 的键是波段名（red/green/blue/nir/swir）。"""
    try:
        upload_dir = _raster_output_dir()
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到图层 '{layer_name}' 对应的 GeoTIFF 文件"
        import rasterio
        from rasterio.warp import transform_bounds
        import numpy as np
        from PIL import Image
        with rasterio.open(tif_path) as src:
            if band_map is None:
                band_map = {"blue": 1, "green": 2, "red": 3, "nir": 4, "swir": 5}
            bands = {}
            for bname, bidx in band_map.items():
                if src.count >= bidx:
                    arr = src.read(bidx).astype(np.float64)
                    if src.nodata is not None:
                        arr[arr == src.nodata] = np.nan
                    bands[bname] = arr
            bounds = list(src.bounds)
            if src.crs and src.crs.to_string() != "EPSG:4326":
                bounds = list(transform_bounds(src.crs, "EPSG:4326", *bounds))
        if not bands:
            return "GeoTIFF 无有效波段"
        idx = calc_fn(bands)
        idx = np.clip(idx, value_range[0], value_range[1])
        import matplotlib
        cmap = matplotlib.colormaps[cmap_name]
        valid = np.isfinite(idx)
        norm = (idx - value_range[0]) / (value_range[1] - value_range[0])
        norm = np.clip(norm, 0, 1)
        norm[~valid] = 0
        rgba = cmap(norm)
        rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
        if np.any(~valid):
            rgb[~valid] = 0
        img = Image.fromarray(rgb)
        out_name = f"{layer_name}_{formula_name}.png"
        out_path = os.path.join(upload_dir, out_name)
        img.save(out_path)
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": out_name,
            "url": f"/output/uploads/{out_name}",
            "bounds": bounds,
            "label": label,
        })
        valid_count = int(np.sum(valid))
        mean_val = float(np.nanmean(idx)) if valid_count > 0 else 0.0
        return f"已生成{label}图层，有效像元{valid_count}个，平均值={mean_val:.3f}，范围[{value_range[0]}, {value_range[1]}]"
    except ImportError as e:
        return f"{formula_name}计算需要依赖库: {str(e)[:200]}"
    except Exception as e:
        return f"{formula_name}计算失败: {str(e)[:300]}"


@tool
def ndwi_analysis(layer_name: str, green_band: int = 2, nir_band: int = 4) -> str:
    """计算归一化水体指数 NDWI = (Green - NIR) / (Green + NIR)。
    - layer_name: GeoTIFF 图层名。
    - green_band: 绿光波段序号(从1开始，默认 2；Landsat 8/9为3，Sentinel-2为3)。
    - nir_band: 近红外波段序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。"""
    def calc(bands):
        import numpy as np
        g = bands.get("green"); n = bands.get("nir")
        if g is None or n is None:
            raise ValueError("需要 Green 和 NIR 波段")
        return (g - n) / (g + n + 1e-10)
    return _calc_spectral_index(layer_name, "ndwi", calc, "Blues", "NDWI 归一化水体指数",
                                 band_map={"green": green_band, "nir": nir_band})


@tool
def ndbi_analysis(layer_name: str, swir_band: int = 5, nir_band: int = 4) -> str:
    """计算归一化建筑指数 NDBI = (SWIR - NIR) / (SWIR + NIR)。
    - layer_name: GeoTIFF 图层名。
    - swir_band: 短波红外序号(从1开始，默认 5；Landsat 8/9为6，Sentinel-2为11)。
    - nir_band: 近红外波段序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。"""
    def calc(bands):
        import numpy as np
        s = bands.get("swir"); n = bands.get("nir")
        if s is None or n is None:
            raise ValueError("需要 SWIR 和 NIR 波段")
        return (s - n) / (s + n + 1e-10)
    return _calc_spectral_index(layer_name, "ndbi", calc, "OrRd", "NDBI 归一化建筑指数",
                                 band_map={"swir": swir_band, "nir": nir_band})


@tool
def evi_analysis(layer_name: str, nir_band: int = 4, red_band: int = 3, blue_band: int = 1) -> str:
    """计算增强植被指数 EVI = 2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)。
    - layer_name: GeoTIFF 图层名。
    - nir_band: 近红外序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。
    - red_band: 红光波段序号(从1开始，默认 3；Landsat 8/9为4，Sentinel-2为4)。
    - blue_band: 蓝光波段序号(从1开始，默认 1；Landsat 8/9为2，Sentinel-2为2)。
    输出截断到 [-1, 1] 后渲染（超出极值的像元压平到边界），有效植被区通常为 0~1。"""
    def calc(bands):
        import numpy as np
        n = bands.get("nir"); r = bands.get("red"); b = bands.get("blue")
        if n is None or r is None or b is None:
            raise ValueError("需要 NIR、Red、Blue 三个波段")
        return 2.5 * (n - r) / (n + 6 * r - 7.5 * b + 1.0 + 1e-10)
    return _calc_spectral_index(layer_name, "evi", calc, "RdYlGn", "EVI 增强植被指数",
                                 band_map={"nir": nir_band, "red": red_band, "blue": blue_band})


@tool
def ndmi_analysis(layer_name: str, nir_band: int = 4, swir_band: int = 5) -> str:
    """计算归一化水分指数 NDMI = (NIR - SWIR) / (NIR + SWIR)。
    - layer_name: GeoTIFF 图层名。
    - nir_band: 近红外波段序号(从1开始，默认 4；Landsat 8/9为5，Sentinel-2为8)。
    - swir_band: 短波红外序号(从1开始，默认 5；Landsat 8/9为6，Sentinel-2为11)。"""
    def calc(bands):
        import numpy as np
        n = bands.get("nir"); s = bands.get("swir")
        if n is None or s is None:
            raise ValueError("需要 NIR 和 SWIR 波段")
        return (n - s) / (n + s + 1e-10)
    return _calc_spectral_index(layer_name, "ndmi", calc, "YlGnBu", "NDMI 归一化水分指数",
                                 band_map={"nir": nir_band, "swir": swir_band})


@tool
def calc_spectral_index(
    layer_name: str,
    index: Literal["ndvi", "ndwi", "ndbi", "evi", "ndmi"],
    red_band: int = 3,
    nir_band: int = 4,
    green_band: int = 2,
    swir_band: int = 5,
    blue_band: int = 1,
) -> str:
    """统一计算多光谱遥感指数（NDVI/NDWI/NDBI/EVI/NDMI）。
    - layer_name: 多光谱 GeoTIFF 图层名。
    - index: 必选指数类型，可选 'ndvi'(植被) / 'ndwi'(水体) / 'ndbi'(建筑) / 'evi'(增强植被) / 'ndmi'(地表水分)。
    - red_band / nir_band / green_band / swir_band / blue_band: 传感器对应波段序号（默认适配常规RGBN传感器；Landsat/Sentinel按需配置）。"""
    idx = (index or "ndvi").strip().lower()
    if idx == "ndvi":
        return ndvi_analysis.invoke({"layer_name": layer_name, "red_band": red_band, "nir_band": nir_band})
    elif idx == "ndwi":
        return ndwi_analysis.invoke({"layer_name": layer_name, "green_band": green_band, "nir_band": nir_band})
    elif idx == "ndbi":
        return ndbi_analysis.invoke({"layer_name": layer_name, "swir_band": swir_band, "nir_band": nir_band})
    elif idx == "evi":
        return evi_analysis.invoke({"layer_name": layer_name, "nir_band": nir_band, "red_band": red_band, "blue_band": blue_band})
    elif idx == "ndmi":
        return ndmi_analysis.invoke({"layer_name": layer_name, "nir_band": nir_band, "swir_band": swir_band})
    else:
        return f"不支持的遥感指数: {index}，支持: ndvi, ndwi, ndbi, evi, ndmi"



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
            fname = f"{name}_分析报告_{_dt2.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
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


# ============================================================
# 工具: spatial_fix_geometry — 几何有效性批量修复
# ============================================================

@tool
def spatial_fix_geometry(layer_name: str) -> str:
    """批量修复图层中的无效几何（自相交多边形、环断裂等），生成修复后的新图层。
    - layer_name: 待修复的矢量图层名。生成含 fix_status('fixed'/'original'/'failed') 字段的新图层上图。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        from shapely.validation import make_valid
        import numpy as np
        fixed = 0
        failed = 0
        statuses = []
        new_geoms = []
        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                statuses.append("original")
                new_geoms.append(geom)
                continue
            if geom.is_valid:
                statuses.append("original")
                new_geoms.append(geom)
                continue
            try:
                new = make_valid(geom)
                if new is not None and not new.is_empty:
                    statuses.append("fixed")
                    new_geoms.append(new)
                    fixed += 1
                else:
                    statuses.append("failed")
                    new_geoms.append(geom)
                    failed += 1
            except Exception:
                statuses.append("failed")
                new_geoms.append(geom)
                failed += 1
        import geopandas as gpd
        result = gdf.copy()
        result.geometry = new_geoms
        result["fix_status"] = statuses
        result_name = f"{name}_修复"
        _gdf_to_layer(result, result_name)
        total = len(gdf)
        return f"几何修复完成：{total} 个要素中，{fixed} 个已修复，{failed} 个修复失败（保留原几何），其余原本有效。已加载到地图（含 fix_status 字段）"
    except Exception as e:
        return f"几何修复失败: {str(e)[:300]}"


# ============================================================
# 工具: spatial_check_duplicates — 重复要素检测
# ============================================================

@tool
def spatial_check_duplicates(layer_name: str, fields: str = "") -> str:
    """检测图层中的重复要素。
    - layer_name: 图层名。
    - fields: 逗号分隔的属性字段列表（如 'id,name'）；若为空则直接按几何完全一致查重。返回重复统计并标图。"""
    try:
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        import numpy as np
        if fields.strip():
            cols = [x.strip() for x in fields.split(",") if x.strip()]
            miss = [c for c in cols if c not in gdf.columns]
            if miss:
                return f"字段不存在：{', '.join(miss)}，可用：{', '.join(gdf.columns.tolist())}"
            dup_mask = gdf.duplicated(subset=cols, keep=False)
            n_dup = int(dup_mask.sum())
            n_groups = len(gdf[dup_mask].groupby(cols))
            if n_dup == 0:
                return f"未发现重复要素（按字段 {', '.join(cols)} 检查，共 {len(gdf)} 个要素）"
            return f"发现重复要素：{n_dup} 个要素组成 {n_groups} 个重复组（按字段 {', '.join(cols)}）"
        # 几何重复
        wkb = gdf.geometry.to_wkb()
        import collections
        counter = collections.Counter(wkb.tolist())
        dup_wkbs = {k for k, v in counter.items() if v > 1}
        if not dup_wkbs:
            return f"未发现几何完全相同的重复要素（共 {len(gdf)} 个要素）"
        dup_idx = [i for i, w in enumerate(wkb.tolist()) if w in dup_wkbs]
        # 生成标记图层
        import geopandas as gpd
        result = gdf.iloc[dup_idx].copy()
        result["is_duplicate"] = True
        result_name = f"{name}_重复要素"
        _gdf_to_layer(result, result_name)
        n_groups = len(dup_wkbs)
        return f"发现 {len(dup_idx)} 个重复要素（{n_groups} 组几何完全相同），已加载到地图（图层「{result_name}」）"
    except Exception as e:
        return f"重复检测失败: {str(e)[:300]}"



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
            "context": _last_user_message[:300],
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
    show_north_arrow: 是否显示指北针；show_scale_bar: 是否显示比例尺；dpi: 输出分辨率。"""
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
            for lid in ids:
                if lid in _registered_layers:
                    layers_to_draw.append((lid, _registered_layers[lid]))
        else:
            for lid, ldata in _registered_layers.items():
                layers_to_draw.append((lid, ldata))

        if not layers_to_draw:
            return "没有可绘制的图层，请先加载或创建图层"

        fig, ax = plt.subplots(1, 1, figsize=(10, 8))
        colors = plt.cm.Set2.colors
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
            except Exception:
                continue

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
                xlim = ax.get_xlim()
                ylim = ax.get_ylim()
                sx = xlim[0] + (xlim[1] - xlim[0]) * 0.05
                sy = ylim[0] + (ylim[1] - ylim[0]) * 0.05
                width = (xlim[1] - xlim[0]) * 0.1
                ax.plot([sx, sx + width], [sy, sy], "k-", linewidth=3)
                ax.text(sx + width / 2, sy + (ylim[1] - ylim[0]) * 0.01,
                        f"{width * 111:.0f} km", ha="center", fontsize=9)
            except Exception:
                pass

        ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
        plt.tight_layout()

        out_dir = os.path.join(os.getcwd(), "cache", "charts")
        os.makedirs(out_dir, exist_ok=True)
        fname = f"{output_name}.png"
        out_path = os.path.join(out_dir, fname)
        fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        record_tool_artifact(fname, out_path, artifact_type="image")

        _pending_images.append({
            "name": fname,
            "path": out_path,
            "url": f"/cache/charts/{fname}",
            "type": "png",
        })

        return f"静态地图已生成：{out_path}（{dpi} DPI，含{len(layers_to_draw)}个图层）"
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
        tid = _current_task_id or ""
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
            layer_name = result_layer_name or f"SQL过滤结果_{len(derived_geojson['features'])}条"
            style = {
                "color": "#e11d48",
                "fillColor": "#fb7185",
                "fillOpacity": 0.4,
                "weight": 2
            }
            _push_layer(layer_name, derived_geojson, style=style)
            _register_layer(layer_name, derived_geojson)
            out_lines.append(f"\n✨ 已将包含空间几何的 {len(derived_geojson['features'])} 个要素自动加载为新图层「{layer_name}」！")

        return "\n".join(out_lines)
    except Exception as e:
        return f"SQL 查询执行异常: {str(e)[:200]}"


# ============================================================
# 工具: get_elevation_data — 按需获取真实地表高程 DEM
# ============================================================

@tool
def get_elevation_data(
    bbox,
    resolution: float = 0,
    provider: str = "aws_terrain",
    output_format: str = "geotiff",
) -> str:
    """获取指定地理范围的真实地表高程 DEM 数据（按需下载 + 本地 tile 缓存）。
    - bbox: 边界框 [minLng, minLat, maxLng, maxLat]（WGS84，如 [112.93, 28.18, 112.97, 28.20]）或逗号分隔字符串。
    - resolution: 目标分辨率（度/像素，默认 0 为自动）。
    - provider: 数据源，默认 'aws_terrain'（全球免费免 Key）。
    - output_format: 当前仅支持 'geotiff'（落盘供 dem_analysis 等工具继续处理）。
    返回包含 min/max_elevation、geotiff_path、preview_url 及可用图层名 layer_name 的 JSON。"""
    try:
        fmt = (output_format or "geotiff").lower().strip()
        if fmt != "geotiff":
            raise DataProviderError("DEM 获取当前仅支持 output_format='geotiff'。")
        bb = _parse_dem_bbox(bbox)
        prov = dem_provider_by_id(provider)
        if prov is None:
            caps = list_dem_capabilities()
            return json.dumps({
                "ok": False,
                "error": f"未知 DEM Provider：{provider}",
                "hint": "可用 Provider：" + ", ".join(c["name"] for c in caps),
                "available_providers": [c["provider"] for c in caps],
            }, ensure_ascii=False)

        result = prov.fetch(bb, target_resolution_deg=float(resolution or 0))

        # 落盘 GeoTIFF + 渲染预览 PNG（沿用 dem_analysis 的上传目录约定）
        layer_name = f"dem_{int(time.time() * 1000) % 10**9:09d}"
        upload_dir = os.path.join(_temp_output_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        geotiff_path = os.path.join(upload_dir, f"{layer_name}.tif")
        png_path = os.path.join(upload_dir, f"{layer_name}.png")
        _write_dem_geotiff(geotiff_path, result)
        _write_dem_preview(png_path, result)

        # 推 dem_result 给前端叠加（与 dem_analysis/ndvi_analysis/raster_calculator 同一通道）
        bounds_list = [float(v) for v in result.bounds]
        _pending_layer_ops.append({
            "action": "dem_result",
            "name": f"{layer_name}.png",
            "url": f"/output/uploads/{layer_name}.png",
            "bounds": bounds_list,
            "label": (
                f"DEM 真实高程（{result.min_elevation:.1f}–{result.max_elevation:.1f} m，"
                f"{prov.name}）"
            ),
        })

        out = result.to_dict()
        out.update({
            "ok": True,
            "geotiff_path": geotiff_path,
            "preview_url": f"/output/uploads/{layer_name}.png",
            "preview_name": f"{layer_name}.png",
            "layer_name": layer_name,
        })
        return json.dumps(out, ensure_ascii=False)

    except DEMError as e:
        return json.dumps({"ok": False, **e.to_dict()}, ensure_ascii=False)
    except DataProviderError as e:
        return json.dumps({"ok": False, **e.to_dict()}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "ok": False,
            "error": f"DEM 获取失败：{type(e).__name__}: {str(e)[:200]}",
        }, ensure_ascii=False)


def _parse_dem_bbox(bbox):
    """统一 list / tuple / str → [minLng, minLat, maxLng, maxLat]（list of float）。"""
    if isinstance(bbox, (list, tuple)):
        if len(bbox) != 4:
            raise DataProviderError(f"bbox 必须 4 个数，收到 {bbox!r}")
        try:
            return [float(v) for v in bbox]
        except (TypeError, ValueError) as e:
            raise DataProviderError(f"bbox 含不可解析数值：{bbox!r}") from e
    if isinstance(bbox, str):
        s = bbox.strip()
        if not s:
            raise DataProviderError("bbox 字符串为空")
        if s.startswith("["):
            try:
                return _parse_dem_bbox(json.loads(s))
            except (ValueError, TypeError):
                pass
        for sep in (",", ";", " ", "\t"):
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) == 4:
                try:
                    return [float(p) for p in parts]
                except ValueError:
                    continue
        raise DataProviderError(
            f"bbox 字符串解析失败：{bbox!r}",
            hint="格式：'minLng,minLat,maxLng,maxLat'（如 '112.93,28.18,112.97,28.20'）"
                 " 或 [minLng, minLat, maxLng, maxLat]",
        )
    raise DataProviderError(f"bbox 类型不支持：{type(bbox).__name__}")


def _write_dem_geotiff(path: str, result) -> None:
    """把 DEMResult.data 写成单波段 float32 GeoTIFF（EPSG:4326，nodata=-9999）。

    下游工具（dem_analysis / extract_contours / terrain_profile）按 layer_name
    在 uploads 目录找 .tif 文件；nodata=-9999 与 SRTM 等 DEM 的事实标准一致。
    """
    import numpy as np
    import rasterio
    from rasterio.transform import Affine

    a, b, c, d, e, f = result.transform
    transform = Affine(a, b, c, d, e, f)
    arr = np.where(np.isfinite(result.data), result.data, -9999.0).astype(np.float32)

    with rasterio.open(
        path, "w", driver="GTiff",
        height=result.height, width=result.width,
        count=1, dtype="float32",
        crs="EPSG:4326", transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(arr, 1)
        dst.update_tags(
            provider=result.provider,
            source_url=result.source_url,
            min_elevation=f"{result.min_elevation:.3f}",
            max_elevation=f"{result.max_elevation:.3f}",
            resolution_deg=f"{result.resolution:.8f}",
        )


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

@tool
def load_cog(url: str, layer_name: str = "", max_size: int = 2048) -> str:
    """流式加载云优化 GeoTIFF（COG）/在线 GeoTIFF 并叠加到地图。
    走 rasterio /vsicurl/ 流式读取 + 降采样生成 PNG 预览叠加，不整体下载。
    url: http(s) 遥感影像地址；layer_name: 图层名（默认取文件名）；max_size: 预览最长边像素（默认 2048）。
    用户给了一个在线 .tif/.tiff 链接要求"加载/叠加到地图"时调用。"""
    from backend.services import cloud_native as cn
    from backend.services.url_security import sanitize_error_text, sanitize_http_url
    from PIL import Image as _PILImage
    init_temp_dir()
    try:
        result = cn.read_cog(url, max_size=max_size)
    except cn.CloudNativeError as e:
        return f"加载失败: {sanitize_error_text(e, url)}"
    except Exception as e:
        return f"加载异常: {sanitize_error_text(e, url)}"
    parsed_url = urllib.parse.urlsplit(str(url))
    source_path = parsed_url.path if parsed_url.scheme.lower() in {"http", "https"} else str(url)
    name = (layer_name or os.path.splitext(os.path.basename(source_path))[0]).strip() or "COG影像"
    upload_dir = os.path.join(_temp_output_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    png_name = f"cog_{safe}_{int(time.time())}_{uuid.uuid4().hex[:12]}.png"
    png_path = os.path.join(upload_dir, png_name)
    with open(png_path, "wb") as f:
        f.write(result["png_bytes"])
    bounds = result["bounds"]
    meta = result["meta"]
    preview_url = f"/output/uploads/{png_name}"
    preview_layer_name = f"{name}（COG 预览）"
    source_reference = (
        sanitize_http_url(url)
        if parsed_url.scheme.lower() in {"http", "https"}
        else os.path.basename(source_path)
    )
    raster_info = {
        "filename": png_name,
        "url": preview_url,
        "source_name": name,
        "source_reference": source_reference,
        "bounds": [float(v) for v in bounds],
        "width": int(meta["width"]),
        "height": int(meta["height"]),
        "preview_width": int(meta["resampled"][0]),
        "preview_height": int(meta["resampled"][1]),
        "bands": int(meta["count"]),
        "crs": meta["crs"],
        "preview_only": True,
        "processing": "云端 COG 影像预览",
    }
    # 影像叠加（dem_result 通道：前端 addImageOverlay）
    _pending_layer_ops.append({
        "action": "dem_result", "name": png_name,
        "url": preview_url,
        "bounds": [float(v) for v in bounds],
        "label": f"COG 影像: {name}",
        "layer_name": preview_layer_name,
        "raster": raster_info,
        "crs": meta["crs"],
    })
    # 注册范围框图层（供 AI 查询/缩放/卷帘，透明填充红框）
    minx, miny, maxx, maxy = bounds
    footprint = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]]},
        "properties": {"name": name, "source": "cog", "url": sanitize_http_url(url)[:500]},
    }]}
    _push_layer(name, footprint, {"color": "#e74c3c", "fillColor": "#e74c3c", "fillOpacity": 0.02, "weight": 1.5, "dashArray": "6 4"})
    _register_layer(name, footprint)
    return (
        f"已加载 COG 影像「{name}」并叠加到地图: {meta['width']}x{meta['height']} 像素, "
        f"{meta['count']} 波段, CRS {meta['crs']}, 范围 {meta['bounds_wgs84']}, "
        f"预览降采样至 {meta['resampled'][0]}x{meta['resampled'][1]}。"
        f"已注册同名范围框图层可供查询；当前仅保存地图预览，像元分析需提供原始栅格文件"
    )


@tool
def get_cog_info(url: str) -> str:
    """查询在线 COG/GeoTIFF 元信息：CRS、范围、尺寸、波段、数据类型、统计值（min/max/mean，采样）。
    只读元数据与降采样统计，不整体下载。用户问"这个 tif 是什么/什么坐标系/波段信息"时调用。"""
    from backend.services import cloud_native as cn
    from backend.services.url_security import sanitize_error_text, sanitize_http_url
    try:
        info = cn.cog_info(url)
    except cn.CloudNativeError as e:
        return f"查询失败: {sanitize_error_text(e, url)}"
    except Exception as e:
        return f"查询异常: {sanitize_error_text(e, url)}"
    lines = [
        f"== COG 元信息: {sanitize_http_url(url)[:120]} ==",
        f"CRS: {info['crs']}  范围(WGS84): {info['bounds_wgs84']}",
        f"尺寸: {info['width']} x {info['height']}  波段数: {info['count']}  类型: {', '.join(info['dtypes'])}",
        f"nodata: {info['nodata']}  瓦片化: {info['is_tiled']}  压缩: {info['compression']}",
    ]
    for s in info["stats_sampled"]:
        lines.append(f"  波段{s['band']}: min={s['min']} max={s['max']} mean={s['mean']}")
    return "\n".join(lines)


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

@tool
def zonal_statistics(raster_layer: str, zone_layer: str, stat: str = "mean") -> str:
    """分区统计（Zonal Statistics）：用面图层对栅格分区，统计每个面内栅格值，
    结果作为新图层上图（分区面属性增加 zonal_mean/zonal_sum/zonal_min/zonal_max/count）。
    raster_layer: 栅格图层名（上传的GeoTIFF）；zone_layer: 矢量面图层；stat: 主统计量（mean/sum/min/max）。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask
        from rasterio.warp import transform_geom
        from shapely.geometry import mapping

        upload_dir = os.path.join(_temp_output_dir, "uploads")
        tif_path = _find_uploaded_tif(raster_layer)
        if tif_path is None:
            return f"未找到栅格文件「{raster_layer}」，请先上传 GeoTIFF"

        zones, zone_name = _layer_to_gdf(zone_layer)
        if zones is None:
            return zone_name
        with rasterio.open(tif_path) as src:
            if zones.crs is None or zones.crs.to_epsg() != 4326:
                zones = zones.to_crs(4326)
            feats = []
            for idx, row in zones.iterrows():
                geom4326 = row.geometry
                try:
                    geom_src = transform_geom("EPSG:4326", src.crs, mapping(geom4326))
                except Exception:
                    geom_src = mapping(geom4326)
                try:
                    out_img, _ = rio_mask(src, [geom_src], crop=True, filled=False)
                    arr = out_img[0]
                    nodata = src.nodata
                    mask = np.isfinite(arr) if arr.dtype.kind == 'f' else np.ones_like(arr, dtype=bool)
                    if nodata is not None:
                        mask &= ~np.isclose(arr, nodata)
                    vals = arr[mask].astype("float64")
                except Exception:
                    vals = np.array([])
                props = dict(row.drop(labels="geometry").items()) if hasattr(row, "drop") else {}
                props = {k: (v.item() if hasattr(v, "item") else v) for k, v in props.items()}
                if vals.size:
                    props["zonal_mean"] = round(float(vals.mean()), 4)
                    props["zonal_sum"] = round(float(vals.sum()), 4)
                    props["zonal_min"] = round(float(vals.min()), 4)
                    props["zonal_max"] = round(float(vals.max()), 4)
                    props["zonal_count"] = int(vals.size)
                else:
                    props["zonal_mean"] = None
                    props["zonal_sum"] = None
                    props["zonal_min"] = None
                    props["zonal_max"] = None
                    props["zonal_count"] = 0
                props["name"] = props.get("name") or f"{zone_name}_区{idx + 1}"
                feats.append({"type": "Feature", "geometry": mapping(geom4326), "properties": props})
        out_fc = {"type": "FeatureCollection", "features": feats}
        out_name = f"{zone_name}_分区统计"
        _push_layer(out_name, out_fc, {"color": "#7b1fa2", "weight": 2, "fillOpacity": 0.15})
        _register_layer(out_name, out_fc)
        ok_count = sum(1 for f in feats if f["properties"]["zonal_count"] > 0)
        key = {"mean": "zonal_mean", "sum": "zonal_sum", "min": "zonal_min", "max": "zonal_max"}.get(
            str(stat).lower(), "zonal_mean")
        preview = [f["properties"].get(key) for f in feats[:5]]
        return (f"分区统计完成（{stat}）：{ok_count}/{len(feats)} 个分区落在栅格范围内，"
                f"结果图层「{out_name}」已上图（含 zonal_mean/sum/min/max/count 字段）。"
                f"{key} 前5值: {preview}")
    except Exception as e:
        return f"分区统计失败: {str(e)[:300]}"


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
        out_name = f"{name}_带长度"
        _gdf_to_layer(out, out_name)
        return (f"已添加字段「{field_name}」（单位 km，UTM {utm.to_string()} 计算）："
                f"总长 {lengths_km.sum():.2f} km，最长 {lengths_km.max():.2f} km，"
                f"结果图层「{out_name}」已上图")
    except Exception as e:
        return f"添加长度字段失败: {str(e)[:300]}"


@tool
def spatial_explode(layer_name: str) -> str:
    """分解多部件要素（Multi* → 单部件）：每个组成部分变成独立要素，
    属性保留，结果作为新图层上图。拓扑清洗/逐要素符号化前常用。"""
    gdf, name = _layer_to_gdf(layer_name)
    if gdf is None:
        return name
    try:
        out = gdf.explode(index_parts=False).reset_index(drop=True)
        out_name = f"{name}_分解"
        _gdf_to_layer(out, out_name)
        return f"已分解多部件要素：{len(gdf)} → {len(out)} 个要素，结果图层「{out_name}」已上图"
    except Exception as e:
        return f"分解失败: {str(e)[:300]}"


@tool
def geometry_convert(layer_name: str, target_type: str = "lines") -> str:
    """几何类型互转/提取，结果作为新图层上图。target_type 可选：
    lines（面→边界线）、polygons（线→面，要求构成闭合环）、
    convex_hull（凸包）、bounding_box（最小外接矩形）。"""
    gdf, name = _layer_to_gdf(layer_name)
    if gdf is None:
        return name
    t = str(target_type).strip().lower()
    try:
        attribute_notice = ""
        import geopandas as gpd
        from shapely.geometry import LineString, Point, box as shp_box
        if t == "lines":
            if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
                return "面转边界线失败：输入图层包含空几何，请先清理"
            if not gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
                return "面转边界线仅支持 Polygon/MultiPolygon 图层"
            out = gdf.copy()
            out["geometry"] = gdf.geometry.boundary
        elif t == "polygons":
            from shapely.ops import polygonize, unary_union
            polys = list(polygonize(unary_union(gdf.geometry.values)))
            if not polys:
                return "线要素无法多边形化（未构成闭合环），请检查几何"
            out = gpd.GeoDataFrame(geometry=polys, crs=gdf.crs)
            attribute_notice = "；结果仅包含新几何，源线属性未继承"
        elif t == "convex_hull":
            union_geom = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.geometry.unary_union
            hull = union_geom.convex_hull
            out = gpd.GeoDataFrame(geometry=[hull], crs=gdf.crs)
            attribute_notice = "；结果仅包含聚合几何，源要素属性未继承"
        elif t == "bounding_box":
            minx, miny, maxx, maxy = gdf.total_bounds
            import math
            if not all(math.isfinite(float(value)) for value in (minx, miny, maxx, maxy)):
                return "外接矩形失败：输入图层没有有效几何"
            if minx == maxx and miny == maxy:
                extent = Point(minx, miny)
            elif minx == maxx or miny == maxy:
                extent = LineString([(minx, miny), (maxx, maxy)])
            else:
                extent = shp_box(minx, miny, maxx, maxy)
            out = gpd.GeoDataFrame(geometry=[extent], crs=gdf.crs)
            attribute_notice = "；结果仅包含外接范围几何，源要素属性未继承"
        else:
            return f"未知 target_type: {target_type}，可选 lines/polygons/convex_hull/bounding_box"
        out_name = f"{name}_{t}"
        with _state_lock:
            occupied_names = set(_registered_layers)
            occupied_names.update(
                item.get("name") for item in _pending_layers if isinstance(item.get("name"), str)
            )
            base_name = out_name
            suffix = 1
            while out_name in occupied_names:
                out_name = f"{base_name}_{suffix}"
                suffix += 1
            _gdf_to_layer(out, out_name)
        return f"几何转换完成（{t}）：{len(out)} 个要素，结果图层「{out_name}」已上图{attribute_notice}"
    except Exception as e:
        return f"几何转换失败: {str(e)[:300]}"


def _find_uploaded_tif(layer_name: str):
    """Resolve the selected raster exactly; a substring may identify another dataset."""
    with _state_lock:
        info = _registered_layers.get(layer_name)
        if info and isinstance(info.get('raster'), dict):
            source = info.get('raster_source_path')
            return source if source and os.path.isfile(source) else None
        if _active_project_id:
            return None
    upload_dir = _raster_output_dir()
    if os.path.isdir(upload_dir):
        for f in os.listdir(upload_dir):
            if f.lower().endswith(('.tif', '.tiff')):
                base = os.path.splitext(f)[0]
                if base == layer_name:
                    return os.path.join(upload_dir, f)
    return None


def _raster_output_dir():
    init_temp_dir()
    path = os.path.join(_temp_output_dir, 'uploads')
    os.makedirs(path, exist_ok=True)
    return path


def _write_raster_output(source_path: str, out_name: str, data, metadata=None) -> str:
    """保存带源空间参考的单波段分析结果，作为后续栅格工具可读取的输入。"""
    import numpy as np
    import rasterio

    safe_name = os.path.basename(str(out_name)).strip()
    if not safe_name or safe_name in {'.', '..'}:
        raise ValueError("栅格结果名称无效")
    values = np.asarray(data, dtype="float32")
    if values.ndim == 2:
        values = values[None, :, :]
    if values.ndim != 3 or values.shape[0] < 1:
        raise ValueError("栅格结果必须是二维像元数组或波段数组")
    output_path = os.path.join(_raster_output_dir(), safe_name + ".tif")
    with rasterio.open(source_path) as src:
        profile = src.profile.copy()
        source_width, source_height = src.width, src.height
        profile.update(count=values.shape[0], width=values.shape[2], height=values.shape[1],
                       dtype="float32", nodata=float("nan"))
        if source_width != values.shape[2] or source_height != values.shape[1]:
            profile["transform"] = src.transform * src.transform.scale(
                src.width / values.shape[2], src.height / values.shape[1])
        if not profile.get("tiled"):
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(values)
        if metadata:
            dst.update_tags(**{str(key): str(value) for key, value in metadata.items() if value is not None})
    return output_path


def _raster_preview_op(src, data, out_name: str, label: str, preview_image=None,
                       source_layer=None, value_units=None, source_label=None,
                       source_reference=None, quality_warnings=None) -> str:
    """保存栅格预览、注册原始 GeoTIFF，并通过 dem_result 交付地图与图层面板。"""
    import numpy as np
    from PIL import Image
    import rasterio
    from affine import Affine
    from urllib.parse import quote
    from rasterio.enums import Resampling
    from rasterio.transform import array_bounds
    from rasterio.warp import calculate_default_transform, reproject
    values = np.asarray(data)
    band = (values if values.ndim == 2 else values[0]).astype("float64")
    valid = np.isfinite(band)
    if getattr(src, "nodata", None) is not None:
        valid &= band != src.nodata
    if valid.any():
        lo, hi = np.percentile(band[valid], 2), np.percentile(band[valid], 98)
        if hi <= lo:
            hi = lo + 1.0
        norm = np.clip((band - lo) / (hi - lo), 0, 1)
    else:
        norm = np.zeros_like(band)
    norm[~valid] = 0
    rgb = (np.dstack([norm] * 3) * 255).astype("uint8")
    img = preview_image if preview_image is not None else Image.fromarray(rgb)
    upload_dir = _raster_output_dir()
    try:
        input_tags = {key.upper(): value for key, value in src.tags().items()}
        input_units = src.units or ()
    except Exception:
        input_tags, input_units = {}, ()
    png_name = os.path.basename(str(out_name)) + ".png"
    png_path = os.path.join(upload_dir, png_name)
    raster_path = os.path.join(upload_dir, os.path.basename(str(out_name)) + ".tif")
    if not os.path.isfile(raster_path):
        raster_path = _write_raster_output(src.name, out_name, values)
    with rasterio.open(raster_path) as result_src:
        preview_rgba = np.dstack((np.asarray(img.convert("RGB")), valid.astype("uint8") * 255))
        transform = result_src.transform
        if result_src.crs and (
            not result_src.crs.is_geographic
            or abs(float(transform.b)) > 1e-12
            or abs(float(transform.d)) > 1e-12
            or result_src.crs.to_epsg() != 4326
        ):
            preview_transform, preview_width, preview_height = calculate_default_transform(
                result_src.crs, "EPSG:4326", result_src.width, result_src.height,
                *result_src.bounds,
            )
            max_preview_pixels = 4_000_000
            if preview_width * preview_height > max_preview_pixels:
                scale = (preview_width * preview_height / max_preview_pixels) ** 0.5
                target_width = max(1, int(preview_width / scale))
                target_height = max(1, int(preview_height / scale))
                preview_transform = preview_transform * Affine.scale(
                    preview_width / target_width, preview_height / target_height,
                )
                preview_width, preview_height = target_width, target_height
            warped_rgba = np.zeros((preview_height, preview_width, 4), dtype="uint8")
            for band_index in range(4):
                reproject(
                    source=preview_rgba[:, :, band_index],
                    destination=warped_rgba[:, :, band_index],
                    src_transform=transform, src_crs=result_src.crs,
                    dst_transform=preview_transform, dst_crs="EPSG:4326",
                    resampling=Resampling.nearest,
                )
            img = Image.fromarray(warped_rgba, mode="RGBA")
            bounds = list(array_bounds(preview_height, preview_width, preview_transform))
        elif result_src.crs:
            img = Image.fromarray(preview_rgba, mode="RGBA")
            bounds = [result_src.bounds.left, result_src.bounds.bottom,
                      result_src.bounds.right, result_src.bounds.top]
        else:
            img = Image.fromarray(preview_rgba, mode="RGBA")
            bounds = [result_src.bounds.left, result_src.bounds.bottom,
                      result_src.bounds.right, result_src.bounds.top]
        crs = result_src.crs.to_string() if result_src.crs else None
        width, height = result_src.width, result_src.height
        bands = result_src.count
        pixel_size = [
            math.hypot(float(result_src.transform.a), float(result_src.transform.d)),
            math.hypot(float(result_src.transform.b), float(result_src.transform.e)),
        ]
        source_tags = {key.upper(): value for key, value in result_src.tags().items()}
        result_units = (value_units or (result_src.units[0] if result_src.units and result_src.units[0] else None)
                        or source_tags.get("VALUE_UNITS")
                        or (input_units[0] if input_units and input_units[0] else None)
                        or input_tags.get("VALUE_UNITS"))
        pixel_units = result_src.crs.linear_units if result_src.crs and result_src.crs.is_projected else ("degree" if result_src.crs and result_src.crs.is_geographic else "unknown")
        warnings = list(quality_warnings or [])
        if result_src.crs is None:
            warnings.append("预览栅格缺少 CRS；未能进行地理配准转换")
        source_quality_note = (source_tags.get("QUALITY_NOTE") or source_tags.get("SOURCE_QUALITY_NOTE")
                               or input_tags.get("QUALITY_NOTE") or input_tags.get("SOURCE_QUALITY_NOTE"))
        if source_quality_note and source_quality_note not in warnings:
            warnings.append(source_quality_note)
        if not result_src.crs:
            warnings.append("结果栅格未包含 CRS")
        valid_ratio = float(np.count_nonzero(valid)) / float(valid.size) if valid.size else 0.0
        if valid_ratio < 0.9:
            warnings.append("有效像元比例低于 90%，请检查 NoData 或输入覆盖范围")
        resolved_source_layer = (source_layer or source_tags.get("SOURCE_LAYER")
                                 or input_tags.get("SOURCE_LAYER"))
        resolved_source_label = (source_label or source_tags.get("SOURCE_LABEL")
                                 or input_tags.get("SOURCE_LABEL") or input_tags.get("SOURCE")
                                 or "GIS WorkTable 栅格分析")
        resolved_source_reference = (source_reference or source_tags.get("SOURCE_URL")
                                     or source_tags.get("CITATION") or input_tags.get("SOURCE_URL")
                                     or input_tags.get("CITATION"))
        vertical_datum = source_tags.get("VERTICAL_DATUM") or input_tags.get("VERTICAL_DATUM")
        # Keep provenance on the analysis GeoTIFF itself so it survives project save/reopen
        # and can be consumed by a later raster operation, not only by this preview response.
        output_tags = {
            "SOURCE_LAYER": resolved_source_layer,
            "SOURCE_LABEL": resolved_source_label,
            "SOURCE_URL": resolved_source_reference,
            "SOURCE_VALUE_UNITS": (source_tags.get("SOURCE_VALUE_UNITS")
                                   or input_tags.get("SOURCE_VALUE_UNITS")
                                   or input_tags.get("VALUE_UNITS")
                                   or (input_units[0] if input_units else None)),
            "VALUE_UNITS": result_units,
            "VERTICAL_DATUM": vertical_datum,
            "PROCESSING": label,
            "QUALITY_NOTE": "; ".join(str(warning) for warning in warnings) or None,
        }
    with rasterio.open(raster_path, "r+") as output_src:
        output_src.update_tags(**{key: str(value) for key, value in output_tags.items() if value is not None})
    img.save(png_path)
    preview_url = "/output/uploads/" + quote(png_name, safe="")
    source_url = "/output/uploads/" + quote(os.path.basename(raster_path), safe="")
    layer_name = os.path.splitext(os.path.basename(raster_path))[0]
    raster_info = {
        "filename": png_name, "url": preview_url,
        "source_filename": os.path.basename(raster_path), "source_name": layer_name,
        "source_url": source_url, "bounds": [float(v) for v in bounds],
        "width": int(width), "height": int(height),
        "source_width": int(width), "source_height": int(height),
        "bands": int(bands), "crs": crs,
        "pixel_size": pixel_size,
        "pixel_units": pixel_units, "value_units": result_units,
        "source_layer": resolved_source_layer,
        "source_label": resolved_source_label,
        "source_reference": resolved_source_reference,
        "vertical_datum": vertical_datum,
        "processing": label, "valid_pixel_ratio": valid_ratio,
        "quality_warnings": warnings,
    }
    registration_token = _register_raster_layer(layer_name, raster_info, raster_path)
    _pending_layer_ops.append({
        "action": "dem_result", "name": png_name,
        "url": preview_url,
        "bounds": [float(v) for v in bounds],
        "label": label, "layer_name": layer_name, "raster": raster_info,
        "registration_token": registration_token, "crs": crs,
    })
    try:
        record_tool_artifact(png_name, png_path, artifact_type="image")
        record_tool_artifact(os.path.basename(raster_path), raster_path, artifact_type="raster")
    except Exception:
        pass
    return "预览已叠加到地图，并注册为可继续分析的栅格图层"


def _raster_preview_context(layer_name: str, *, value_units=None) -> dict:
    """Carry input layer provenance into derived raster metadata when a registry entry exists."""
    with _state_lock:
        info = _registered_layers.get(layer_name) or {}
        raster = info.get("raster") if isinstance(info, dict) else None
        raster = dict(raster) if isinstance(raster, dict) else {}
    return {
        "source_layer": layer_name,
        "value_units": value_units if value_units is not None else raster.get("value_units"),
        "source_label": raster.get("source_label"),
        "source_reference": raster.get("source_reference"),
        "quality_warnings": raster.get("quality_warnings"),
    }


@tool
def raster_resample(layer_name: str, scale_factor: float = 2.0, method: str = "bilinear") -> str:
    """栅格重采样：按倍数缩放栅格分辨率（scale_factor>1 缩小/更粗，<1 放大/更细），
    method 可选 nearest / bilinear / cubic。结果 GeoTIFF 落盘并出预览叠加图层。"""
    try:
        import rasterio
        from rasterio.enums import Resampling

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        resampling = {"nearest": Resampling.nearest, "bilinear": Resampling.bilinear,
                      "cubic": Resampling.cubic}.get(str(method).lower(), Resampling.bilinear)
        out_name = f"{os.path.splitext(os.path.basename(tif_path))[0]}_重采样"
        out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        with rasterio.open(tif_path) as src:
            scale = max(0.05, min(32.0, float(scale_factor)))
            new_w = max(1, int(src.width / scale))
            new_h = max(1, int(src.height / scale))
            data = src.read(out_shape=(src.count, new_h, new_w), resampling=resampling)
            profile = src.profile.copy()
            profile.update(width=new_w, height=new_h,
                           transform=src.transform * src.transform.scale(
                               src.width / new_w, src.height / new_h))
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(data)
            note = _raster_preview_op(
                src, data, out_name, f"栅格重采样 x{scale} ({method})",
                **_raster_preview_context(layer_name),
            )
        return (f"重采样完成：{scale}x → {new_w}x{new_h} 像元，method={method}，"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"重采样失败: {str(e)[:300]}"


@tool
def raster_reproject(layer_name: str, target_crs: str = "EPSG:4326") -> str:
    """栅格重投影：把 GeoTIFF 转到目标坐标系（默认 EPSG:4326，供地图叠加），
    结果 GeoTIFF 落盘并出预览叠加图层。矢量重投影用 convert_crs。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject as rio_reproject

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        out_name = f"{os.path.splitext(os.path.basename(tif_path))[0]}_重投影"
        out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        with rasterio.open(tif_path) as src:
            transform, width, height = calculate_default_transform(
                src.crs, target_crs, src.width, src.height, *src.bounds)
            profile = src.profile.copy()
            profile.update(crs=target_crs, transform=transform, width=width, height=height)
            bands = []
            for i in range(1, src.count + 1):
                dst_arr = np.zeros((height, width), dtype=src.dtypes[i - 1])
                rio_reproject(
                    source=rasterio.band(src, i),
                    destination=dst_arr,
                    src_transform=src.transform, src_crs=src.crs,
                    dst_transform=transform, dst_crs=target_crs,
                    resampling=Resampling.bilinear)
                bands.append(dst_arr)
            stacked = np.stack(bands)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(stacked)
            with rasterio.open(out_path) as resrc:
                preview = resrc.read()
                note = _raster_preview_op(
                    resrc, preview, out_name, f"栅格重投影 → {target_crs}",
                    **_raster_preview_context(layer_name),
                )
        return (f"重投影完成：{src.crs} → {target_crs}，{width}x{height} 像元，"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"重投影失败: {str(e)[:300]}"


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
    try:
        out = tool_obj.invoke(entry.get("args") or {})
        ok = not _tool_result_failed(tool_name, out)
        err = "" if ok else str(out)[:200]
    except Exception as e:
        out = f"重跑失败: {str(e)[:200]}"
        ok, err = False, str(e)
    new_layers = [n for n in _registered_layers if n not in snapshot]
    restored = []
    for name, old in snapshot.items():
        if name in _registered_layers and _registered_layers[name] is not old:
            suffix_name = f"{name}_原"
            seq = 1
            while suffix_name in _registered_layers:
                seq += 1
                suffix_name = f"{name}_原{seq}"
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


def _write_dem_preview(path: str, result) -> None:
    """渲染 DEM 地形预览 PNG（matplotlib terrain colormap，nodata→黑底）。"""
    import matplotlib
    import numpy as np
    from PIL import Image

    cmap = matplotlib.colormaps['terrain']
    arr = np.asarray(result.data, dtype=np.float64)
    valid = np.isfinite(arr)
    if not valid.any():
        rgb = np.zeros((max(1, result.height), max(1, result.width), 3), dtype=np.uint8)
    else:
        vmin = float(np.min(arr[valid]))
        vmax = float(np.max(arr[valid]))
        if np.isclose(vmin, vmax):
            vmax = vmin + 1.0
        norm = np.clip((arr - vmin) / (vmax - vmin), 0.0, 1.0)
        norm[~valid] = 0.0
        rgba = cmap(norm)
        rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
        rgb[~valid] = 0
    Image.fromarray(rgb).save(path)


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


def _parse_reclass_rules(mapping: str):
    """解析重分类映射串 'a-b=v;c+=v'，返回 [(lo, hi, val), ...]（a-b 为左闭右开 [a,b)，c+ 表示 >=c）"""
    import math
    import re
    rules = []
    text = str(mapping or "").replace("\n", ";").replace("，", ";").replace(",", ";")
    for i, chunk in enumerate(text.split(";")):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            return []
        left, right = chunk.split("=", 1)
        left, right = left.strip(), right.strip()
        try:
            val = float(right)
        except ValueError:
            val = float(i + 1)
        m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*\+", left)
        if m:
            lo, hi = float(m.group(1)), math.inf
        else:
            m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*[-~]\s*(-?\d+(?:\.\d+)?)", left)
            if m:
                lo, hi = float(m.group(1)), float(m.group(2))
            else:
                m = re.fullmatch(r"(-?\d+(?:\.\d+)?)", left)
                if not m:
                    return []
                lo, hi = float(m.group(1)), float(m.group(1)) + 1e-9
        if not math.isfinite(lo) or (not math.isfinite(hi) and hi != math.inf):
            return []
        if hi < lo:
            lo, hi = hi, lo
        if hi <= lo:
            return []
        if not math.isfinite(val):
            return []
        rules.append((lo, hi, val))
    return rules


def _raster_out_profile(src, nodata, count: int = 1) -> dict:
    """复制源栅格 profile 作为输出，清理与本机 GDAL 冲突的分块键，统一 float32"""
    profile = src.profile.copy()
    profile.update(count=count, dtype="float32", nodata=nodata)
    if not profile.get("tiled"):
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
    return profile


@tool
def raster_reclassify(layer_name: str, mapping: str = "", method: str = "mapping", classes: int = 5) -> str:
    """栅格重分类：把连续栅格值按规则重新编码为类别值，结果 GeoTIFF 落在源文件旁并出预览图层。
    - layer_name: 栅格图层名（上传的 GeoTIFF 图层名）。
    - mapping: 区间映射串，分号分隔，形如 '0-10=1;10-50=2;50+=3'；'a-b' 表示 a<=v<b（左闭右开），
      'a+' 表示 v>=a；等号右边为类别值（非数字时按规则出现顺序编号 1,2,3...）。
    - method: 重分类方式，'mapping'(按 mapping 串，默认) / 'equal_interval'(等间距分级) / 'quantile'(分位数分级)。
    - classes: equal_interval / quantile 的分级数（整数>=2，默认 5）。
    输入 nodata 像元保持 nodata；未命中任何规则的像元也输出为 nodata。"""
    try:
        import numpy as np
        import rasterio

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        method_key = str(method or "mapping").strip().lower()
        supported_methods = {
            "mapping", "equal_interval", "equal", "interval",
            "quantile", "quantiles", "percentile",
        }
        if method_key not in supported_methods:
            return "重分类失败：method 必须是 mapping、equal_interval 或 quantile"
        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float64")
            nodata = src.nodata
            valid = np.isfinite(data)
            if nodata is not None:
                valid &= ~np.isclose(data, nodata)
            if not valid.any():
                return f"栅格「{layer_name}」没有有效像元，无法重分类"
            vals = data[valid]
            if method_key in ("equal_interval", "equal", "interval"):
                try:
                    class_count = float(classes)
                except (TypeError, ValueError):
                    class_count = float("nan")
                if not math.isfinite(class_count) or not class_count.is_integer() or class_count < 2:
                    return "重分类失败：分级数必须是大于等于 2 的有限整数"
                n_cls = int(class_count)
                lo_v, hi_v = float(np.min(vals)), float(np.max(vals))
                if hi_v <= lo_v:
                    codes = np.ones(data.shape, dtype="float64")
                    desc = f"equal_interval {n_cls} 级（值域退化为常数 {lo_v:.6g}）"
                else:
                    edges = np.linspace(lo_v, hi_v, n_cls + 1)
                    codes = (np.digitize(data, edges[1:-1], right=False) + 1).astype("float64")
                    desc = f"equal_interval {n_cls} 级 [{lo_v:.6g}, {hi_v:.6g}]"
            elif method_key in ("quantile", "quantiles", "percentile"):
                try:
                    class_count = float(classes)
                except (TypeError, ValueError):
                    class_count = float("nan")
                if not math.isfinite(class_count) or not class_count.is_integer() or class_count < 2:
                    return "重分类失败：分级数必须是大于等于 2 的有限整数"
                n_cls = int(class_count)
                edges = np.unique(np.quantile(vals, np.linspace(0.0, 1.0, n_cls + 1)))
                if edges.size < 2:
                    codes = np.ones(data.shape, dtype="float64")
                    desc = f"quantile 分级（值域退化，实际 1 级）"
                else:
                    codes = (np.digitize(data, edges[1:-1], right=False) + 1).astype("float64")
                    desc = f"quantile 分位分级（请求 {n_cls} 级，实际 {edges.size - 1} 级）"
            else:
                rules = _parse_reclass_rules(mapping)
                if not rules:
                    return "mapping 为空或格式不正确，示例：'0-10=1;10-50=2;50+=3'"
                conds = [(data >= lo) & (data < hi) & valid for lo, hi, _v in rules]
                choices = [v for _lo, _hi, v in rules]
                codes = np.select(conds, choices, default=np.nan).astype("float64")
                desc = f"mapping {len(rules)} 条规则"
            out = np.full(data.shape, np.nan, dtype="float64")
            out[valid] = np.asarray(codes, dtype="float64")[valid]
            out_nodata = nodata if nodata is not None else np.nan
            arr = np.where(np.isfinite(out), out, out_nodata)
            # The stored GeoTIFF may use a project asset hash as its filename;
            # keep the derived layer tied to the user-visible input layer name.
            out_name = f"{_safe_layer_export_stem(layer_name)}_重分类"
            out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
            with rasterio.open(out_path, "w", **_raster_out_profile(src, out_nodata)) as dst:
                dst.write(arr.astype("float32"), 1)
            note = _raster_preview_op(
                src, arr[None, :, :], out_name, f"栅格重分类（{desc}）",
                **_raster_preview_context(layer_name, value_units="类别编码（无量纲）"),
            )
            classified = out[valid]
            classified = classified[np.isfinite(classified)]
            uniq = np.unique(classified)
            hit = int(classified.size)
            miss = int(valid.sum() - hit)
        return (f"重分类完成（{desc}）：类别 {len(uniq)} 个，有效像元 {hit}/{int(valid.sum())}"
                f"（{miss} 个未命中任何规则），结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"栅格重分类失败: {str(e)[:300]}"


@tool
def raster_focal_stats(layer_name: str, stat: str = "mean", size: int = 3) -> str:
    """栅格焦点统计：按滑动窗口对每个像元做邻域统计，结果 GeoTIFF 落在源文件旁并出预览图层。
    - layer_name: 栅格图层名（上传的 GeoTIFF 图层名）。
    - stat: 统计量，'mean'(均值) / 'median'(中位数) / 'min'(最小值) / 'max'(最大值) /
      'std'(标准差) / 'range'(极差 max-min) / 'majority'(众数)。
    - size: 窗口边长（奇数，仅支持 3 / 5 / 7，默认 3）。
    统计自动忽略 nodata 与无效像元；输入 nodata 像元输出仍为 nodata。"""
    try:
        import numpy as np
        import rasterio

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        s = int(size)
        if s % 2 == 0:
            return f"窗口大小 size 必须为奇数（3/5/7），收到 {size}"
        if s not in (3, 5, 7):
            return f"窗口大小 size 仅支持 3、5、7，收到 {size}"
        key = str(stat or "mean").strip().lower()
        key = {"average": "mean", "avg": "mean", "mode": "majority", "max-min": "range",
               "maximum": "max", "minimum": "min"}.get(key, key)
        if key not in ("mean", "median", "min", "max", "std", "range", "majority"):
            return f"未知统计量 stat: {stat}，可选 mean/median/min/max/std/range/majority"
        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float64")
            nodata = src.nodata
            valid = np.isfinite(data)
            if nodata is not None:
                valid &= data != nodata
            if not valid.any():
                return f"栅格「{layer_name}」没有有效像元，无法做焦点统计"
            from scipy import ndimage
            filled = np.where(valid, data, np.nan)
            if key in ("min", "max", "range"):
                mn = ndimage.minimum_filter(np.where(valid, data, np.inf), size=s, mode="nearest")
                mx = ndimage.maximum_filter(np.where(valid, data, -np.inf), size=s, mode="nearest")
                res = {"min": mn, "max": mx, "range": mx - mn}[key]
            elif key == "majority":
                def _mode(v):
                    v = v[np.isfinite(v)]
                    if v.size == 0:
                        return np.nan
                    _rounded, inverse = np.unique(np.round(v, 6), return_inverse=True)
                    rounded_counts = np.bincount(inverse)
                    winning_group = int(np.argmax(rounded_counts))
                    original_values, original_counts = np.unique(
                        v[inverse == winning_group], return_counts=True,
                    )
                    return float(original_values[int(np.argmax(original_counts))])
                res = ndimage.generic_filter(filled, _mode, size=s, mode="nearest")
            else:
                f = np.where(valid, data, 0.0)
                w = valid.astype("float64")
                cnt = np.maximum(ndimage.uniform_filter(w, size=s, mode="nearest"), 1e-12)
                m1 = ndimage.uniform_filter(f, size=s, mode="nearest") / cnt
                if key == "mean":
                    res = m1
                elif key == "std":
                    m2 = ndimage.uniform_filter(f * f, size=s, mode="nearest") / cnt
                    res = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
                else:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        res = ndimage.generic_filter(filled, np.nanmedian, size=s, mode="nearest")
            res = np.where(valid, res, np.nan)
            fin = res[np.isfinite(res)]
            if fin.size == 0:
                return f"焦点统计失败: 窗口 {s}x{s} 内没有有效像元"
            out_nodata = nodata if nodata is not None else np.nan
            arr = np.where(np.isfinite(res), res, out_nodata)
            out_name = f"{_safe_layer_export_stem(layer_name)}_焦点{key}"
            out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
            with rasterio.open(out_path, "w", **_raster_out_profile(src, out_nodata)) as dst:
                dst.write(arr.astype("float32"), 1)
            note = _raster_preview_op(
                src, arr[None, :, :], out_name, f"焦点统计 {key} {s}x{s}",
                **_raster_preview_context(layer_name),
            )
            rmin, rmax = float(fin.min()), float(fin.max())
        return (f"焦点统计完成（{key}，窗口 {s}x{s}）：值域 [{rmin:.6g}, {rmax:.6g}]，"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"焦点统计失败: {str(e)[:300]}"


@tool
def euclidean_distance(layer_name: str, source_value: float = None, out_name: str = "") -> str:
    """欧氏距离分析：计算每个像元到最近源像元的平面距离（像元中心，单位与栅格坐标系一致），
    结果 GeoTIFF 落在源文件旁并出预览图层。
    - layer_name: 栅格图层名（上传的 GeoTIFF 图层名）。
    - source_value: 源像元取值，指定时把等于该值的像元视为源；缺省(None)时把非零且非 nodata 的像元视为源。
    - out_name: 输出文件名（可不带 .tif），留空时自动命名为 '<源文件名>_欧氏距离'。
    输入 nodata 像元输出仍为 nodata。"""
    try:
        import numpy as np
        import rasterio
        from scipy import ndimage

        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        suffix = str(out_name or "").strip() or f"{_safe_layer_export_stem(layer_name)}_欧氏距离"
        suffix = os.path.splitext(os.path.basename(suffix))[0]
        with rasterio.open(tif_path) as src:
            if src.crs and src.crs.is_geographic:
                return (f"欧氏距离失败: 输入坐标系 {src.crs.to_string()} 使用经纬度角度；"
                        "不能把角度当作地面距离，请先重投影到适用的投影坐标系")
            if src.crs and not src.crs.is_projected:
                return (f"欧氏距离失败: 暂不支持坐标系 {src.crs.to_string()}；"
                        "请先转换到投影坐标系")
            transform = src.transform
            col_vec = (float(transform.a), float(transform.d))
            row_vec = (float(transform.b), float(transform.e))
            dot = col_vec[0] * row_vec[0] + col_vec[1] * row_vec[1]
            if abs(dot) > 1e-10 * max(1.0, math.hypot(*col_vec) * math.hypot(*row_vec)):
                return "欧氏距离失败: 栅格像元存在斜切变换；请先重采样到正交网格"
            sampling = (math.hypot(*row_vec), math.hypot(*col_vec))
            if src.crs:
                distance_units = src.crs.linear_units or "投影坐标单位"
                distance_warnings = []
            else:
                distance_units = "栅格单位（CRS 未定义）"
                distance_warnings = ["源栅格缺少 CRS；欧氏距离按栅格坐标单位计算，地面距离含义未验证"]
            data = src.read(1).astype("float64")
            nodata = src.nodata
            valid = np.isfinite(data)
            if nodata is not None:
                valid &= data != nodata
            if source_value is None or str(source_value).strip() == "":
                source = valid & (data != 0)
                src_desc = "非零有效像元"
            else:
                sv = float(source_value)
                source_dtype = np.dtype(src.dtypes[0])
                if source_dtype.kind == "f":
                    # Match the value as it is representable in the source raster's
                    # floating dtype; np.isclose's relative tolerance can select
                    # distinct large-valued classes as the same source.
                    match_value = float(np.asarray(sv, dtype=source_dtype).item())
                else:
                    match_value = sv
                source = valid & (data == match_value)
                src_desc = f"值={sv:g}"
            n_src = int(source.sum())
            if n_src == 0:
                return f"栅格「{layer_name}」中找不到源像元（{src_desc}），无法计算欧氏距离"
            dist = ndimage.distance_transform_edt(~source, sampling=sampling).astype("float64")
            dist[~valid] = np.nan
            dmax = float(np.nanmax(dist))
            out_nodata = nodata if nodata is not None else np.nan
            arr = np.where(np.isfinite(dist), dist, out_nodata)
            out_path = os.path.join(_raster_output_dir(), suffix + ".tif")
            with rasterio.open(out_path, "w", **_raster_out_profile(src, out_nodata)) as dst:
                dst.write(arr.astype("float32"), 1)
            preview_context = _raster_preview_context(layer_name, value_units=distance_units)
            inherited_warnings = preview_context.get("quality_warnings") or []
            preview_context["quality_warnings"] = list(inherited_warnings) + [
                warning for warning in distance_warnings if warning not in inherited_warnings
            ]
            note = _raster_preview_op(
                src, arr[None, :, :], suffix, f"欧氏距离（源：{src_desc}）",
                **preview_context,
            )
        return (f"欧氏距离完成：源像元 {n_src} 个（{src_desc}），最大距离 {dmax:.6g}"
                f" {distance_units}（像元尺寸 {sampling[1]:g} x {sampling[0]:g} {distance_units}），"
                f"结果已保存 {suffix}.tif；{note}")
    except Exception as e:
        return f"欧氏距离分析失败: {str(e)[:300]}"


@tool
def raster_extract_by_mask(raster_layer: str, zone_layer: str, inside: bool = True) -> str:
    """按掩膜提取栅格：用矢量面图层裁剪栅格，保留面内（或面外）像元，
    结果 GeoTIFF 落在源文件旁并出预览图层。
    - raster_layer: 栅格图层名（上传的 GeoTIFF 图层名）。
    - zone_layer: 矢量面图层名（掩膜范围，支持 Polygon / MultiPolygon）。
    - inside: True(默认) 保留掩膜内像元；False 保留掩膜外像元。
    掩膜外的像元写为 nodata；结果保持源栅格的行列范围与地理变换不变。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask
        from rasterio.warp import transform_geom
        from shapely.geometry import mapping

        tif_path = _find_uploaded_tif(raster_layer)
        if tif_path is None:
            return f"未找到栅格文件「{raster_layer}」，请先上传 GeoTIFF"
        zones, zone_name = _layer_to_gdf(zone_layer)
        if zones is None:
            return zone_name
        if zones.crs is None:
            return f"掩膜图层「{zone_layer}」缺少 CRS，无法可靠转换坐标"
        if zones.crs.to_epsg() != 4326:
            zones = zones.to_crs(4326)
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return f"栅格「{raster_layer}」缺少 CRS，无法可靠对齐掩膜；请先定义 CRS 后重新上传"
            geoms = []
            for geom in zones.geometry:
                if geom is None or geom.is_empty:
                    continue
                geoms.append(transform_geom(zones.crs.to_string(), src.crs, mapping(geom)))
            if not geoms:
                return f"图层「{zone_layer}」没有可用的面几何，无法生成掩膜"
            out_nodata = src.nodata if src.nodata is not None else np.nan
            masked_arr, _out_transform = rio_mask(
                src, geoms, crop=False, filled=False, invert=not bool(inside),
            )
            arr = np.asarray(masked_arr.data, dtype="float32")
            arr[np.ma.getmaskarray(masked_arr)] = out_nodata
            band = arr[0]
            invalid = ~np.isfinite(band)
            if not np.isnan(out_nodata):
                invalid |= band == out_nodata
            keep = int((~invalid).sum())
            out_name = f"{_safe_layer_export_stem(raster_layer)}_掩膜{'内' if inside else '外'}"
            out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
            with rasterio.open(out_path, "w",
                               **_raster_out_profile(src, out_nodata, count=arr.shape[0])) as dst:
                dst.write(arr)
            note = _raster_preview_op(src, arr[0:1, :, :], out_name,
                                      f"按掩膜提取（{'保留面内' if inside else '保留面外'}）",
                                      **_raster_preview_context(raster_layer))
        return (f"按掩膜提取完成（{'保留面内' if inside else '保留面外'}）：有效像元 {keep}/{band.size}，"
                f"共 {arr.shape[0]} 个波段，结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"按掩膜提取失败: {str(e)[:300]}"


def _raster_pixel_area_m2(src):
    """Return square metres per pixel (scalar projected area or row-wise geodesic area)."""
    transform = src.transform
    determinant = abs(float(transform.a) * float(transform.e) - float(transform.b) * float(transform.d))
    if not math.isfinite(determinant) or determinant <= 0:
        raise ValueError("无法从栅格变换计算有效像元面积")
    if src.crs is None:
        return determinant, ["源栅格缺少 CRS；面积按网格单位为米假设，填挖方结果需谨慎解释"]
    if src.crs.is_projected:
        try:
            unit_to_m = float(src.crs.linear_units_factor[1])
        except (TypeError, ValueError, IndexError, OverflowError) as exc:
            raise ValueError("无法识别投影坐标系的线性单位，不能计算平方米面积") from exc
        if not math.isfinite(unit_to_m) or unit_to_m <= 0:
            raise ValueError("投影坐标系的线性单位无效，不能计算平方米面积")
        return determinant * unit_to_m * unit_to_m, []
    if src.crs.is_geographic:
        if abs(float(transform.b)) > 1e-12 or abs(float(transform.d)) > 1e-12:
            raise ValueError("经纬度栅格含旋转/斜切变换；请先重投影后计算填挖方")
        from pyproj import CRS as PyprojCRS
        geod = PyprojCRS.from_wkt(src.crs.to_wkt()).get_geod()
        row_areas = []
        for row in range(src.height):
            left = float(transform.c)
            right = left + float(transform.a)
            top = float(transform.f) + float(transform.e) * row
            bottom = top + float(transform.e)
            area, _ = geod.polygon_area_perimeter(
                [left, right, right, left], [top, top, bottom, bottom]
            )
            area_per_pixel = abs(float(area))
            if not math.isfinite(area_per_pixel) or area_per_pixel <= 0:
                raise ValueError("无法计算经纬度栅格的椭球像元面积")
            row_areas.append(area_per_pixel)
        import numpy as np
        return np.asarray(row_areas, dtype="float64").reshape(src.height, 1), []
    raise ValueError("仅支持投影或地理坐标系的栅格面积计算")


@tool
def surface_volumes(before_layer: str, after_layer: str, reference: float = -99999.0) -> str:
    """填挖方计算：比较两个共配准 DEM（或一个 DEM 与参考高程面），输出挖方/填方/净方量与变化面积。
    - before_layer: 施工前（现状）DEM 图层名（上传的 GeoTIFF 图层名）。
    - after_layer: 施工后（设计）DEM 图层名；当给出 reference 时该参数可留空字符串。
    - reference: 参考高程（米，浮点数）。给出时忽略 after_layer，用常数高程面作为设计面。
    要求两个 DEM 的行列数与地理变换完全一致，否则直接失败并提示；
    只有两个栅格都有效的像元参与计算。挖方=现状高于设计部分的体积，填方=设计高于现状部分的体积，
    净方量=填方-挖方（正数表示净填）。结果为 m3 / m2。"""
    try:
        import numpy as np
        import rasterio

        before_path = _find_uploaded_tif(before_layer)
        if before_path is None:
            return f"未找到栅格文件「{before_layer}」，请先上传 GeoTIFF"
        use_ref = reference is not None and float(reference) > -99998.0
        ref_val = float(reference) if use_ref else None
        after_path = None
        if not use_ref:
            after_path = _find_uploaded_tif(after_layer)
            if after_path is None:
                return f"未找到栅格文件「{after_layer}」，请先上传 GeoTIFF（或改用 reference 参考高程）"

        with rasterio.open(before_path) as src_b:
            before = src_b.read(1).astype("float64")
            vb = np.isfinite(before)
            if src_b.nodata is not None:
                vb &= before != src_b.nodata
            tr_b, crs_b = src_b.transform, src_b.crs
            hb, wb = src_b.height, src_b.width
            volume_warnings = []
            before_tags = {key.upper(): value for key, value in src_b.tags().items()}
            before_units = ((src_b.units[0] if src_b.units and src_b.units[0] else None)
                            or before_tags.get("VALUE_UNITS") or before_tags.get("UNITTYPE"))
            before_scale = _elevation_unit_to_m(before_units)
            if before_scale is None:
                volume_warnings.append(
                    f"源栅格「{before_layer}」未标注或无法识别高程单位；计算按米解释，请核实源数据"
                )
                before_scale = 1.0
            before *= before_scale
            if use_ref:
                after = np.full(before.shape, float(ref_val), dtype="float64")
                va = np.ones(before.shape, dtype=bool)
                after_desc = f"参考高程面 {ref_val:.6g} m"
            else:
                with rasterio.open(after_path) as src_a:
                    if (src_a.height, src_a.width) != (hb, wb):
                        return (f"填挖方失败: 两个 DEM 行列数不一致（{hb}x{wb} vs "
                                f"{src_a.height}x{src_a.width}），请先重采样或裁剪到同一网格")
                    if not np.allclose(np.asarray(tr_b, dtype="float64"),
                                       np.asarray(src_a.transform, dtype="float64"),
                                       rtol=1e-9, atol=1e-9):
                        return "填挖方失败: 两个 DEM 地理变换不一致（不是共配准栅格），请先重投影/重采样到同一网格"
                    if str(crs_b) != str(src_a.crs):
                        return f"填挖方失败: 两个 DEM 坐标系不一致（{crs_b} vs {src_a.crs}），请先统一坐标系"
                    after = src_a.read(1).astype("float64")
                    va = np.isfinite(after)
                    if src_a.nodata is not None:
                        va &= after != src_a.nodata
                    after_tags = {key.upper(): value for key, value in src_a.tags().items()}
                    after_units = ((src_a.units[0] if src_a.units and src_a.units[0] else None)
                                   or after_tags.get("VALUE_UNITS") or after_tags.get("UNITTYPE"))
                    after_scale = _elevation_unit_to_m(after_units)
                    if after_scale is None:
                        volume_warnings.append(
                            f"源栅格「{after_layer}」未标注或无法识别高程单位；计算按米解释，请核实源数据"
                        )
                        after_scale = 1.0
                    after *= after_scale
                after_desc = f"设计 DEM「{after_layer}」"

            valid = vb & va
            diff = after - before
            d = diff[valid]
            if d.size == 0:
                return "填挖方失败: 两个 DEM 没有共同有效像元（nodata 或范围不重叠）"
            pixel_area_m2, area_warnings = _raster_pixel_area_m2(src_b)
            volume_warnings.extend(area_warnings)
            cell_areas = np.asarray(pixel_area_m2, dtype="float64")
            if cell_areas.ndim == 0:
                area_weights = float(cell_areas)
                average_cell_area = float(cell_areas)
            else:
                area_weights = cell_areas
                average_cell_area = float(np.mean(cell_areas))
            diff_valid = np.where(valid, diff, 0.0)
            cut = float((np.clip(-diff_valid, 0.0, None) * area_weights).sum())
            fill = float((np.clip(diff_valid, 0.0, None) * area_weights).sum())
            net = fill - cut
            changed_mask = valid & (np.abs(diff) > 1e-9)
            changed_n = int(changed_mask.sum())
            changed_area = float((changed_mask * area_weights).sum())
            zmin, zmax = float(d.min()), float(d.max())
            diff_out = np.where(valid, diff, np.nan)
            # Difference values have different semantics from source elevations; a source
            # sentinel such as 0 can be a valid unchanged difference and must not mask it.
            out_nodata = np.nan
            arr = np.where(np.isfinite(diff_out), diff_out, out_nodata)
            out_name = f"{os.path.splitext(os.path.basename(before_path))[0]}_填挖方"
            out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
            with rasterio.open(out_path, "w", **_raster_out_profile(src_b, out_nodata)) as dst:
                dst.write(arr.astype("float32"), 1)
            source_layer_name = before_layer if use_ref else f"{before_layer} + {after_layer}"
            preview_context = _raster_preview_context(before_layer, value_units="m")
            preview_context["source_layer"] = source_layer_name
            inherited_warnings = preview_context.get("quality_warnings") or []
            preview_context["quality_warnings"] = list(inherited_warnings) + [
                warning for warning in volume_warnings if warning not in inherited_warnings
            ]
            note = _raster_preview_op(
                src_b, arr[None, :, :], out_name, "填挖方高程差", **preview_context
            )
        summary = (f"填挖方计算完成（现状={before_layer}，设计={after_desc}）：\n"
                   f"挖方量 {cut:,.2f} m3，填方量 {fill:,.2f} m3，净方量 {net:,.2f} m3（正数=净填）\n"
                   f"变化面积 {changed_area:,.2f} m2（{changed_n} 个像元，平均单像元面积 {average_cell_area:.6g} m2），"
                   f"高程差范围 [{zmin:.6g}, {zmax:.6g}] m\n")
        if volume_warnings:
            summary += "质量提示：" + "；".join(volume_warnings) + "\n"
        return summary + f"结果已保存 {out_name}.tif；{note}"
    except Exception as e:
        return f"填挖方失败: {str(e)[:300]}"


# ============================================================
# 工具: join_field  按属性字段连接（非空间连接）
# ============================================================

@tool
def join_field(target_layer: str, join_layer: str, target_field: str, join_field: str, fields: str = "", how: str = "left") -> str:
    """按公共属性键连接图层（属性连接，不是空间连接）。
    - target_layer/join_layer: 目标图层与数据源图层名。
    - target_field/join_field: 两侧连接键字段名。
    - fields: 逗号分隔要带入的字段，留空=数据源除连接键外全部字段。
    - how: 'left'(保留全部目标要素,未匹配为 NaN,默认) 或 'inner'(仅匹配)。
    同名冲突字段重命名为「名字_join」；键唯一时 validate 防行倍增；结果作为新图层上图。"""
    try:
        gdf_t, name_t = _layer_to_gdf(target_layer)
        if gdf_t is None:
            return name_t
        gdf_j, name_j = _layer_to_gdf(join_layer)
        if gdf_j is None:
            return name_j

        how_key = str(how or "left").strip().lower()
        if how_key not in ("left", "inner"):
            return f"how 只能为 'left' 或 'inner'，收到：{how}"

        if target_field not in gdf_t.columns:
            cols = ", ".join(c for c in gdf_t.columns if c != "geometry")
            return f"目标图层「{name_t}」中不存在字段「{target_field}」，可用字段：{cols}"
        if join_field not in gdf_j.columns:
            cols = ", ".join(c for c in gdf_j.columns if c != "geometry")
            return f"数据源图层「{name_j}」中不存在字段「{join_field}」，可用字段：{cols}"

        target_cols = [c for c in gdf_t.columns if c != "geometry"]
        join_cols = [c for c in gdf_j.columns if c != "geometry" and c != join_field]
        if str(fields or "").strip():
            wanted = [f.strip() for f in str(fields).split(",") if f.strip()]
            missing = [f for f in wanted if f not in join_cols]
            if missing:
                return f"数据源图层「{name_j}」中不存在字段：{', '.join(missing)}，可用字段：{', '.join(join_cols)}"
            bring = wanted
        else:
            bring = list(join_cols)
        if not bring:
            return f"数据源图层「{name_j}」除连接键外没有可带入的字段"

        collisions = [c for c in bring if c in target_cols]
        rename = {}
        used = set(target_cols) | set(bring)
        for c in collisions:
            new = f"{c}_join"
            i = 2
            while new in used:
                new = f"{c}_join{i}"
                i += 1
            rename[c] = new
            used.add(new)

        right_keys = gdf_j[join_field].dropna().unique()
        matched = int(gdf_t[target_field].isin(right_keys).sum())
        unmatched = int(len(gdf_t) - matched)
        # Null keys are not joinable values: ignore them both for cardinality
        # validation and on the right side, since pandas otherwise matches NaN
        # keys together and can multiply rows unexpectedly.
        target_keys = gdf_t[target_field].dropna()
        join_keys = gdf_j[join_field].dropna()
        duplicate_t = bool(target_keys.duplicated().any())
        duplicate_j = bool(join_keys.duplicated().any())
        if not duplicate_t and not duplicate_j:
            validate = "one_to_one"
        elif not duplicate_j:
            validate = "many_to_one"
        elif not duplicate_t:
            validate = "one_to_many"
        else:
            validate = "many_to_many"

        keep_cols = [join_field] + [c for c in bring if c != join_field]
        join_sub = gdf_j.loc[gdf_j[join_field].notna(), keep_cols].copy()
        if rename:
            join_sub = join_sub.rename(columns=rename)
        # Pandas treats null merge keys as equal to each other. Give every null
        # target key a unique temporary value so repeated nulls remain separate
        # unmatched rows while the cardinality validator still checks real keys.
        target_for_merge = gdf_t.reset_index(drop=True).copy()
        null_target_keys = target_for_merge[target_field].isna()
        null_marker = "__wtb_null_join_key__"
        while null_marker in target_for_merge.columns:
            null_marker += "_"
        target_for_merge[null_marker] = null_target_keys.to_numpy()
        target_for_merge[target_field] = target_for_merge[target_field].astype(object)
        target_for_merge.loc[null_target_keys, target_field] = [
            object() for _ in range(int(null_target_keys.sum()))
        ]
        join_sub[join_field] = join_sub[join_field].astype(object)
        result = target_for_merge.merge(join_sub, left_on=target_field, right_on=join_field,
                             how=how_key, validate=validate, suffixes=("", "_join"))
        result.loc[result[null_marker], target_field] = None
        result = result.drop(columns=[null_marker])
        if join_field != target_field and join_field in result.columns:
            result = result.drop(columns=[join_field])

        result_name = f"{name_t}_连接{name_j}"
        _gdf_to_layer(result, result_name)
        collision_note = ""
        if rename:
            collision_note = "；冲突字段已重命名：" + ", ".join(f"{k}->{v}" for k, v in rename.items())
        return (f"属性连接完成（{how_key}，validate={validate}）：目标 {len(gdf_t)} 个要素，"
                f"匹配 {matched}，未匹配 {unmatched}，结果 {len(result)} 个要素{collision_note}，"
                f"结果图层「{result_name}」已上图")
    except Exception as e:
        return f"属性连接失败: {str(e)[:300]}"


# ============================================================
# 工具: geometry_attributes  几何属性字段
# ============================================================

@tool
def geometry_attributes(layer_name: str, metrics: str = "area,length,perimeter,centroid") -> str:
    """为图层逐要素添加几何量测字段（几何不变，结果作为新图层上图）。
    - layer_name: 待计算矢量图层名。
    - metrics: 逗号分隔量测项，默认 'area,length,perimeter,centroid'。可选 area(投影面积 m2)、
      length(线/面长度 m)、perimeter(面周长 m)、centroid(展开 centroid_x/y)、bbox(展开
      bbox_minx/miny/maxx/maxy)，以及各 centroid_x、bbox_minx 单项。
    经纬度下面积/长度为度/度：自动估算 UTM 投影带后在投影坐标计算，返回串会说明所用投影；
    投影估算失败则直接报错。"""
    try:
        import geopandas as gpd
        import numpy as np

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"图层「{name}」为空"

        raw = str(metrics or "").strip()
        if not raw:
            return "metrics 不能为空，可选：area,length,perimeter,centroid,bbox"
        items = [m.strip().lower() for m in raw.split(",") if m.strip()]
        allowed = {"area", "length", "perimeter", "centroid", "centroid_x", "centroid_y",
                   "bbox", "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"}
        bad = [m for m in items if m not in allowed]
        if bad:
            return f"不支持的 metrics 项：{', '.join(bad)}，可选：{', '.join(sorted(allowed))}"

        crs = gdf.crs
        is_geographic = bool(crs is not None and crs.is_geographic)
        if is_geographic:
            utm = gdf.estimate_utm_crs()
            if utm is None:
                return "无法估算 UTM 投影带（图层范围异常），无法计算面积/长度"
            metric_gdf = gdf.to_crs(utm)
            crs_note = f"图层为地理坐标系（{crs.to_string()}），面积/长度/周长已在 UTM {utm.to_string()} 投影下计算"
        else:
            metric_gdf = gdf
            crs_note = f"按图层原投影 {crs.to_string() if crs is not None else '未定义'} 计算"

        out = gdf.copy()
        geom = metric_gdf.geometry
        want = set(items)
        added = []

        if "area" in want:
            out["area"] = geom.area.astype(float)
            added.append("area")
        if "length" in want:
            out["length"] = geom.length.astype(float)
            added.append("length")
        if "perimeter" in want:
            is_poly = geom.geom_type.isin(["Polygon", "MultiPolygon"])
            out["perimeter"] = geom.length.where(is_poly, np.nan).astype(float)
            added.append("perimeter")

        need_cx = "centroid" in want or "centroid_x" in want
        need_cy = "centroid" in want or "centroid_y" in want
        if need_cx or need_cy:
            cents = geom.centroid
            if need_cx:
                out["centroid_x"] = cents.x.astype(float)
                added.append("centroid_x")
            if need_cy:
                out["centroid_y"] = cents.y.astype(float)
                added.append("centroid_y")

        b = geom.bounds
        need_bbox = "bbox" in want
        for bn, col in zip(["bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"],
                           ["minx", "miny", "maxx", "maxy"]):
            if need_bbox or bn in want:
                out[bn] = b[col].astype(float)
                added.append(bn)

        out_name = f"{name}_几何属性"
        _gdf_to_layer(out, out_name)
        return (f"几何属性计算完成（{crs_note}）：新增字段 {', '.join(added)}，"
                f"结果图层「{out_name}」已上图")
    except Exception as e:
        return f"几何属性计算失败: {str(e)[:300]}"


# ============================================================
# 工具: minimum_bounding_geometry  最小外包几何
# ============================================================

@tool
def minimum_bounding_geometry(layer_name: str, kind: str = "envelope", group_field: str = "") -> str:
    """计算图层（或分组后）的最小外包几何，结果作为新图层上图。
    - layer_name: 输入矢量图层名。
    - kind: 'envelope'(轴对齐包络,默认) / 'convex_hull'(凸包) / 'circle'(最小外接圆,
      输出 center_x/y、radius_m、radius_km) / 'oriented_bbox'(最小面积定向矩形,输出 length_m、width_m)。
    - group_field: 可选分组字段，留空=整层一个外包几何，给出时按该字段融合、每组一个几何；
      字段不存在时明确报错并列出可用字段。
    circle 半径与 oriented_bbox 边长在 UTM 投影下按米计算，结果几何转回原坐标系上图。"""
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"图层「{name}」为空"

        kind_key = str(kind or "envelope").strip().lower()
        kind_map = {
            "envelope": "envelope", "bbox": "envelope", "extent": "envelope",
            "convex_hull": "convex_hull", "hull": "convex_hull", "convexhull": "convex_hull",
            "circle": "circle", "minimum_bounding_circle": "circle", "mbc": "circle",
            "oriented_bbox": "oriented_bbox", "oriented": "oriented_bbox",
            "rotated_bbox": "oriented_bbox", "obb": "oriented_bbox",
        }
        if kind_key not in kind_map:
            return f"不支持的 kind：{kind}，可选 envelope/convex_hull/circle/oriented_bbox"
        kind_key = kind_map[kind_key]
        suffix_map = {"envelope": "_包络", "convex_hull": "_凸包",
                      "circle": "_最小外接圆", "oriented_bbox": "_定向外接矩形"}

        crs = gdf.crs
        is_geographic = bool(crs is not None and crs.is_geographic)
        need_proj = kind_key in ("circle", "oriented_bbox")
        if need_proj and is_geographic:
            utm = gdf.estimate_utm_crs()
            if utm is None:
                return "无法估算 UTM 投影带（图层范围异常），无法计算圆/定向矩形"
            work = gdf.to_crs(utm)
        else:
            utm = None
            work = gdf

        def _one(geom):
            if kind_key == "envelope":
                return geom.envelope, {}
            if kind_key == "convex_hull":
                return geom.convex_hull, {}
            if kind_key == "oriented_bbox":
                rect = geom.minimum_rotated_rectangle
                if rect.is_empty:
                    return rect, {}
                coords = list(rect.exterior.coords)
                sides = [((coords[i + 1][0] - coords[i][0]) ** 2 +
                          (coords[i + 1][1] - coords[i][1]) ** 2) ** 0.5 for i in range(4)]
                return rect, {"length_m": float(max(sides)), "width_m": float(min(sides))}
            try:
                from shapely import minimum_bounding_circle
                circ = minimum_bounding_circle(geom)
                cx, cy = float(circ.centroid.x), float(circ.centroid.y)
                pts = list(circ.exterior.coords)[:-1]
                radius = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in pts) if pts else 0.0
            except Exception:
                hull = geom.convex_hull
                c = hull.centroid
                cx, cy = float(c.x), float(c.y)
                pts = list(hull.exterior.coords)[:-1] if hull.geom_type == "Polygon" else []
                radius = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in pts) if pts else 0.0
                circ = Point(cx, cy).buffer(radius, quad_segs=64)
            return circ, {"center_x": float(cx), "center_y": float(cy),
                          "radius_m": float(radius), "radius_km": float(radius) / 1000.0}

        if str(group_field or "").strip():
            gf = str(group_field).strip()
            if gf not in work.columns:
                cols = ", ".join(c for c in work.columns if c != "geometry")
                return f"未找到分组字段「{gf}」，可用字段：{cols}"
            rows, geoms = [], []
            for key, sub in work.groupby(gf, dropna=False):
                merged = sub.geometry.union_all()
                geom, extra = _one(merged)
                row = {gf: key, "feature_count": int(len(sub))}
                row.update(extra)
                rows.append(row)
                geoms.append(geom)
            if not geoms:
                return f"图层「{name}」没有可计算的分组"
            out = gpd.GeoDataFrame(rows, geometry=geoms, crs=work.crs)
            out_name = f"{name}_按{gf}{suffix_map[kind_key]}"
        else:
            merged = work.geometry.union_all()
            geom, extra = _one(merged)
            row = {"feature_count": int(len(work))}
            row.update(extra)
            out = gpd.GeoDataFrame([row], geometry=[geom], crs=work.crs)
            out_name = f"{name}{suffix_map[kind_key]}"

        if need_proj and is_geographic:
            out = out.to_crs(crs)
            note = f"（圆/定向边在 UTM {utm.to_string()} 下按米计算，几何已转回 {crs.to_string()}）"
        else:
            note = f"（按 {work.crs.to_string() if work.crs is not None else '未定义坐标系'} 计算）"
        _gdf_to_layer(out, out_name)
        extra_txt = f"，半径 {float(out['radius_m'].iloc[0]):.3f} m" if (kind_key == "circle" and len(out)) else ""
        return f"最小外包几何完成（{kind_key}{extra_txt}）：{len(out)} 个要素，结果图层「{out_name}」已上图{note}"
    except Exception as e:
        return f"最小外包几何失败: {str(e)[:300]}"


# ============================================================
# 工具: points_to_line  点按分组连线
# ============================================================

@tool
def points_to_line(layer_name: str, group_field: str, order_field: str = "", close_ring: bool = False) -> str:
    """把点图层按分组字段连成线，结果作为新图层上图。
    - layer_name: 输入点图层名。
    - group_field: 分组字段名，同一取值连成一条线；不存在时明确报错并列出可用字段。
    - order_field: 可选排序字段，给出时组内按它升序连线，留空=原顺序。
    - close_ring: True 把首点追加到末尾闭合成环，False(默认)不闭合。
    少于 2 个有效点的分组会被跳过并报告；MultiPoint 会先拆成单点再连线。"""
    try:
        import geopandas as gpd
        from shapely.geometry import LineString

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"图层「{name}」为空"

        gf = str(group_field or "").strip()
        if not gf:
            return "group_field 不能为空"
        if gf not in gdf.columns:
            cols = ", ".join(c for c in gdf.columns if c != "geometry")
            return f"未找到分组字段「{gf}」，可用字段：{cols}"
        of = str(order_field or "").strip()
        if of and of not in gdf.columns:
            cols = ", ".join(c for c in gdf.columns if c != "geometry")
            return f"未找到排序字段「{of}」，可用字段：{cols}"

        work = gdf if not of else gdf.sort_values(of, kind="stable")
        grouped = {}
        for _, row in work.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            if geom.geom_type == "Point":
                pts = [geom]
            elif geom.geom_type == "MultiPoint":
                pts = list(geom.geoms)
            else:
                continue
            for pt in pts:
                grouped.setdefault(row[gf], []).append(pt)

        lines, attrs, skipped = [], [], 0
        for gval, pts in grouped.items():
            if len(pts) < 2:
                skipped += 1
                continue
            coords = [(float(p.x), float(p.y)) for p in pts]
            if bool(close_ring) and coords[0] != coords[-1]:
                coords = coords + [coords[0]]
            try:
                line = LineString(coords)
            except Exception:
                skipped += 1
                continue
            lines.append(line)
            attrs.append({gf: gval, "point_count": int(len(pts)), "closed": bool(close_ring)})

        if not lines:
            return f"没有可连线的分组（共 {len(grouped)} 个分组，全部少于 2 个有效点），未生成图层"
        out = gpd.GeoDataFrame(attrs, geometry=lines, crs=gdf.crs)
        try:
            utm = out.estimate_utm_crs()
            if utm is not None:
                out["length_m"] = out.to_crs(utm).geometry.length.astype(float)
        except Exception:
            pass
        out_name = f"{name}_点转线"
        _gdf_to_layer(out, out_name)
        return f"点转线完成：生成 {len(out)} 条线，跳过 {skipped} 个点不足 2 的分组，结果图层「{out_name}」已上图"
    except Exception as e:
        return f"点转线失败: {str(e)[:300]}"


# ============================================================
# 工具: generate_points_along_lines  沿线等距生成点
# ============================================================

@tool
def generate_points_along_lines(layer_name: str, interval: float = 100, unit: str = "m") -> str:
    """沿每条线按固定间隔生成点，结果作为新图层上图。
    - layer_name: 输入线图层名。
    - interval: 点间隔，正数，默认 100；单位由 unit 指定。
    - unit: 'm'(米,默认) 或 'km'(千米)。
    在距起点 interval、2*interval... 处取点（不含起点；整倍数时含终点）；短于一个间隔的线不产点。
    长度与间隔在 UTM 投影下按米计算，结果点转回原坐标系；返回总点数与覆盖线长。"""
    try:
        import geopandas as gpd
        import numpy as np

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"图层「{name}」为空"
        try:
            iv = float(interval)
        except Exception:
            return f"interval 必须是数字，收到：{interval}"
        if not np.isfinite(iv) or iv <= 0:
            return f"interval 必须为正数，收到：{interval}"
        unit_key = str(unit or "m").strip().lower()
        if unit_key in ("m", "meter", "meters", "米"):
            iv_m = iv
            unit_note = f"{iv:g} m"
        elif unit_key in ("km", "kilometer", "kilometers", "千米", "公里"):
            iv_m = iv * 1000.0
            unit_note = f"{iv:g} km（{iv_m:g} m）"
        else:
            return f"unit 只能为 'm' 或 'km'，收到：{unit}"

        work = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        work = work[work.geometry.geom_type.isin(["LineString", "MultiLineString"])]
        if work.empty:
            return f"图层「{name}」中没有有效线要素"

        crs = gdf.crs
        is_geographic = bool(crs is not None and crs.is_geographic)
        if is_geographic:
            utm = gdf.estimate_utm_crs()
            if utm is None:
                return "无法估算 UTM 投影带（图层范围异常），无法按米生成点"
            proj = work.to_crs(utm)
        else:
            utm = None
            proj = work
        proj = proj.explode(index_parts=False)

        total_pts, covered_m, total_len_m = 0, 0.0, 0.0
        pt_geoms, attrs = [], []
        for idx, row in proj.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty or geom.geom_type != "LineString":
                continue
            L = float(geom.length)
            total_len_m += L
            if L < iv_m:
                continue
            dists = np.arange(iv_m, L + 1e-9, iv_m)
            for d in dists:
                try:
                    pt = geom.interpolate(float(d))
                except Exception:
                    continue
                if pt is None or pt.is_empty:
                    continue
                pt_geoms.append(pt)
                attrs.append({"source_index": int(idx) if isinstance(idx, (int, np.integer)) else str(idx),
                              "dist_m": float(d), "line_length_m": L})
                total_pts += 1
            if len(dists):
                covered_m += float(min(float(dists[-1]), L))

        if not pt_geoms:
            return f"沿线生成等距点：线总长 {total_len_m:,.2f} m，均短于一个间隔（{unit_note}），未生成点"
        out = gpd.GeoDataFrame(attrs, geometry=pt_geoms, crs=proj.crs)
        if is_geographic:
            out = out.to_crs(crs)
        out_name = f"{name}_沿线等距点"
        _gdf_to_layer(out, out_name)
        return (f"沿线生成等距点完成（间隔 {unit_note}）：共 {total_pts} 个点，"
                f"覆盖线长 {covered_m:,.2f} m（线总长 {total_len_m:,.2f} m），"
                f"结果图层「{out_name}」已上图")
    except Exception as e:
        return f"沿线生成等距点失败: {str(e)[:300]}"


# ============================================================
# 工具组: 空间统计扩展  权重矩阵 / 空间回归 / 标准差椭圆 / 中心趋势 / OD 成本矩阵
# ============================================================

def _stats_metric_gdf(gdf):
    """把图层投影到本地 UTM 米制坐标系，用于距离/面积/协方差计算。"""
    b = gdf.total_bounds
    lon, lat = (float(b[0]) + float(b[2])) / 2.0, (float(b[1]) + float(b[3])) / 2.0
    crs = _get_utm_crs(lon, lat)
    return gdf.to_crs(crs), crs


def _stats_coords_weights(gdf_metric, weight_field: str = ""):
    """取要素代表点坐标 (N,2) 与可选权重 (N,)。非点要素取 representative_point（保证落在几何内部）。"""
    import numpy as np
    geom = gdf_metric.geometry
    try:
        pts = geom.representative_point()
    except Exception:
        pts = geom
    coords = np.array([[float(p.x), float(p.y)] for p in pts], dtype=float)
    weights = None
    if weight_field:
        if weight_field not in gdf_metric.columns:
            raise ValueError(f"权重字段「{weight_field}」不存在")
        weights = np.asarray(gdf_metric[weight_field].values, dtype=float)
        if not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() <= 0:
            raise ValueError(f"权重字段「{weight_field}」必须为有限非负数且总和大于 0")
    return coords, weights


def _geometric_median(coords, weights, tol: float = 1e-6, max_iter: int = 1000):
    """用修正 Weiszfeld 迭代求加权几何中位数，坐标单位与输入一致。"""
    import numpy as np

    points = np.asarray(coords, dtype=float)
    weight = np.ones(len(points), dtype=float) if weights is None else np.asarray(weights, dtype=float)
    estimate = np.average(points, axis=0, weights=weight)
    for _ in range(max_iter):
        delta = points - estimate
        distances = np.linalg.norm(delta, axis=1)
        coincident = distances <= 1e-9
        eta = float(weight[coincident].sum())
        other = ~coincident
        if not other.any():
            return estimate
        residual = (weight[other, None] * delta[other] / distances[other, None]).sum(axis=0)
        residual_norm = float(np.linalg.norm(residual))
        if residual_norm <= eta:
            return estimate
        scaled = weight[other] / distances[other]
        candidate = (scaled[:, None] * points[other]).sum(axis=0) / float(scaled.sum())
        ratio = min(1.0, eta / residual_norm) if eta else 0.0
        updated = (1.0 - ratio) * candidate + ratio * estimate
        if float(np.linalg.norm(updated - estimate)) <= tol:
            return updated
        estimate = updated
    return estimate


def _is_contiguous(g1, g2, method: str) -> bool:
    """面邻接判定：queen=共享边或顶点(touches)；rook=仅共享边(交集为线且长度>0)。"""
    if g1 is None or g2 is None:
        return False
    try:
        if not g1.touches(g2):
            return False
        if method == "rook":
            inter = g1.intersection(g2)
            return (not inter.is_empty) and float(inter.length) > 0.0
        return True
    except Exception:
        return False


def _contiguity_pairs(geoms, method: str):
    """用 STRtree 预筛候选对再精确判定；无 STRtree 时退化为 O(n^2)。"""
    n = len(geoms)
    pairs = []
    try:
        from shapely import STRtree
        tree = STRtree(geoms)
        for i in range(n):
            for j in tree.query(geoms[i]):
                j = int(j)
                if j <= i:
                    continue
                if _is_contiguous(geoms[i], geoms[j], method):
                    pairs.append((i, j))
    except Exception:
        for i in range(n):
            for j in range(i + 1, n):
                if _is_contiguous(geoms[i], geoms[j], method):
                    pairs.append((i, j))
    return pairs


def _build_spatial_weights(gdf, method: str = "queen", k: int = 8):
    """统一的邻接/权重构建入口（spatial_weights_matrix 与 spatial_regression 复用）。

    返回 (W csr 稀疏矩阵, neighbors 列表, backend 说明)。
    - queen / rook: 优先 libpysal（惰性导入，不在 requirements.txt），
      不可用时用 shapely touches/intersects 的纯 numpy/scipy 实现。
    - knn: cKDTree 质心近邻。
    """
    import numpy as np
    from scipy import sparse

    n = len(gdf)
    if n < 2:
        raise ValueError(f"要素数（{n}）太少，至少需要 2 个")
    method = str(method).lower().strip()
    neighbors = [[] for _ in range(n)]
    backend = "numpy/scipy"

    if method in ("queen", "rook"):
        libpysal_w = None
        try:
            from libpysal.weights import Queen, Rook
            libpysal_w = (Queen if method == "queen" else Rook).from_dataframe(gdf, use_index=False)
        except Exception:
            libpysal_w = None
        if libpysal_w is not None:
            try:
                for i in range(n):
                    neighbors[i] = sorted(int(j) for j in libpysal_w.neighbors.get(i, []) if int(j) != i)
                backend = "libpysal"
            except Exception:
                libpysal_w = None
        if libpysal_w is None:
            geoms = list(gdf.geometry)
            _types = {str(t) for t in gdf.geometry.geom_type.dropna().unique()}
            if not _types or not _types.issubset({"Polygon", "MultiPolygon"}):
                raise ValueError(
                    f"{method} 邻接需要面图层，而当前是 {'/'.join(sorted(_types)) or '未知'}；点图层请改用 method='knn'")
            for i, j in _contiguity_pairs(geoms, method):
                neighbors[i].append(j)
                neighbors[j].append(i)
            for i in range(n):
                neighbors[i] = sorted(neighbors[i])
    elif method == "knn":
        # cKDTree 用欧氏距离：绝不能直接吃经纬度（1 度经差  1 度纬差），
        # 先投影到本地 UTM 米制坐标再建树，这样 knn 才是真正的"最近邻"。
        gdf_metric, _ = _stats_metric_gdf(gdf)
        coords = np.array([[float(p.x), float(p.y)] for p in gdf_metric.geometry.representative_point()], dtype=float)
        from scipy.spatial import cKDTree
        k_eff = max(1, min(int(k), n - 1))
        tree = cKDTree(coords)
        _, idx = tree.query(coords, k=k_eff + 1)
        for i in range(n):
            neighbors[i] = sorted(int(j) for j in np.atleast_1d(idx[i])[1:] if int(j) != i)
    else:
        raise ValueError("method 仅支持 queen / rook / knn")

    rows, cols, data = [], [], []
    for i, nbrs in enumerate(neighbors):
        for j in nbrs:
            rows.append(i)
            cols.append(j)
            data.append(1.0)
    W = sparse.csr_matrix((data, (rows, cols)), shape=(n, n))
    return W, neighbors, backend


def _moran_from_weights(W, x):
    """给定权重矩阵与数值向量计算全局 Moran's I 及随机化假设下的 z/p（与 spatial_moran 同口径）。"""
    import numpy as np
    from scipy.stats import norm
    x = np.asarray(x, dtype=float)
    n = len(x)
    z = x - x.mean()
    zz = float(z @ z)
    S0 = float(W.sum())
    if n < 3 or zz <= 0 or S0 <= 0:
        return None
    I = (n / S0) * float(z @ (W @ z)) / zz
    E_I = -1.0 / (n - 1)
    z_score, p_value, method = 0.0, 1.0, "置换检验"
    denom = (n - 1) * (n - 2) * (n - 3) * S0 * S0
    if n > 3 and denom > 0:
        m2 = float((z ** 2).mean())
        if m2 > 0:
            S1 = 0.5 * float(((W + W.T) ** 2).sum())
            S2 = float(((W.sum(axis=1) + W.sum(axis=0)) ** 2).sum())
            b2 = float((z ** 4).mean()) / (m2 ** 2)
            k1 = n * (S1 * (n * n - 3 * n + 3) - n * S2 + 3 * S0 * S0) / denom
            k2 = (S1 * (n * n - n) - 2 * n * S2 + 6 * S0 * S0) / denom
            var_I = k1 - k2 * b2 - E_I * E_I
            if var_I > 0:
                z_score = (I - E_I) / np.sqrt(var_I)
                p_value = 2.0 * (1.0 - norm.cdf(abs(z_score)))
                method = "正态近似"
    if method != "正态近似":
        rng = np.random.default_rng(20240915)
        perm = []
        for _ in range(99):
            xp = rng.permutation(x)
            zp = xp - xp.mean()
            zzp = float(zp @ zp)
            if zzp > 0:
                perm.append((n / S0) * float(zp @ (W @ zp)) / zzp)
        perm = np.asarray(perm)
        if perm.size and perm.std() > 0:
            z_score = (I - perm.mean()) / perm.std()
            p_value = (1 + int((np.abs(perm - perm.mean()) >= abs(I - perm.mean())).sum())) / (perm.size + 1)
    return I, z_score, p_value, method


def _stats_out_dir(kind: str = "") -> str:
    """空间统计文件产物目录（<temp>/stats[/kind]），与图层通道无关。"""
    init_temp_dir()
    d = os.path.join(_temp_output_dir, "stats", kind) if kind else os.path.join(_temp_output_dir, "stats")
    os.makedirs(d, exist_ok=True)
    return d


def _stats_safe_name(name: str) -> str:
    """文件名安全化：保留中英文与数字。"""
    return (re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(name)).strip("_") or "layer")[:60]


def _stats_summary(tool: str, payload: dict) -> str:
    """短机器可读摘要行（JSON），便于前端/测试稳定解析。"""
    try:
        return "STATS_SUMMARY: " + json.dumps({"tool": tool, **payload}, ensure_ascii=False, default=str)
    except Exception:
        return ""

@tool
def spatial_weights_matrix(layer_name: str, method: str = "queen", k: int = 8) -> str:
    """构建并持久化空间权重矩阵（邻接矩阵）文件产物，供用户独立查看或下载。
    - layer_name: 图层名；queen/rook 邻接需要面图层，点/线图层请改用 method='knn'。
    - method: 'queen'(共享边或顶点，默认) / 'rook'(仅共享边) / 'knn'(K 近邻)。
    - k: knn 的近邻数（默认 8，自动收敛到 N-1）；knn 在本地 UTM 米制投影坐标上计算，避免经纬度欧氏距离失真。
    产出：<临时输出目录>/stats/weights/<图层>_<method>.npz（scipy 稀疏矩阵）与同名 .json 邻居表，并返回要素数与平均邻居数。
    注意：本工具只产出磁盘文件而非地图图层。"""
    try:
        import numpy as np
        from scipy import sparse

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        W, neighbors, backend = _build_spatial_weights(gdf, method=method, k=k)
        n = len(gdf)
        counts = np.array([len(v) for v in neighbors], dtype=int)
        mean_nbrs = float(counts.mean()) if n else 0.0
        out_dir = _stats_out_dir("weights")
        stem = f"{_stats_safe_name(name)}_{str(method).lower()}"
        npz_path = os.path.join(out_dir, stem + ".npz")
        json_path = os.path.join(out_dir, stem + ".json")
        sparse.save_npz(npz_path, W)
        try:
            fids = gdf["_fid"].tolist() if "_fid" in gdf.columns else None
        except Exception:
            fids = None
        sidecar = {
            "layer": name, "method": str(method).lower(), "k": int(k),
            "n_features": n, "mean_neighbors": round(mean_nbrs, 4),
            "min_neighbors": int(counts.min()) if n else 0,
            "max_neighbors": int(counts.max()) if n else 0,
            "neighbor_counts": counts.tolist(),
            "neighbors": neighbors,
            "feature_ids": fids,
            "matrix_npz": npz_path,
            "backend": backend,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(sidecar, f, ensure_ascii=False, indent=2)
        record_tool_artifact(os.path.basename(npz_path), npz_path, artifact_type="file")
        record_tool_artifact(os.path.basename(json_path), json_path, artifact_type="file")
        summary = _stats_summary("spatial_weights_matrix", {
            "layer": name, "method": str(method).lower(), "n_features": n,
            "mean_neighbors": round(mean_nbrs, 4), "backend": backend,
            "matrix": npz_path, "sidecar": json_path,
        })
        return (
            f"空间权重矩阵已生成（{str(method).lower()}，实现路径：{backend}）。\n"
            f"- 图层：{name}，要素数：{n}\n"
            f"- 平均邻居数：{mean_nbrs:.3f}（最小 {int(counts.min()) if n else 0}，最大 {int(counts.max()) if n else 0}）\n"
            f"- 稀疏矩阵：{npz_path}\n"
            f"- 邻居表：{json_path}\n"
            f"（本工具产物为磁盘文件而非地图图层；Moran、热点和回归分析当前各自构建权重，不读取此文件）\n"
            f"{summary}"
        )
    except Exception as e:
        return f"空间权重矩阵构建失败: {str(e)[:300]}"


@tool
def spatial_regression(layer_name: str, dependent: str, independents: str, model: str = "ols") -> str:
    """空间回归分析：OLS + 残差空间自相关（Moran's I），检验自变量对因变量的解释力。
    - layer_name: 图层名。
    - dependent: 因变量字段名（必须为数值型）。
    - independents: 自变量字段名，英文逗号分隔（必须全部为数值型）。
    - model: 'ols'(普通最小二乘，默认) / 'gwr'(地理加权回归，暂未支持，会明确返回不支持提示)。
    输出：系数、标准误、t 值、p 值、R、调整 R、AIC、Jarque-Bera 正态性 p 值，以及残差 Moran's I（默认 queen 权重）。
    注意：本工具只产出数值结果，不生成地图图层。"""
    try:
        import numpy as np
        import pandas as pd
        from scipy import stats

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        model = str(model).lower().strip()
        if model == "gwr":
            return ("gwr（地理加权回归）暂未支持：当前仅提供 OLS 探索性回归（系数/显著性/残差自相关）。"
                    "请改用 model='ols'；空间权重矩阵文件不会启用 GWR 或被 OLS 自动读取。")
        if model != "ols":
            return f"不支持的 model：{model}，可选 'ols'（默认）或 'gwr'（暂未支持）"
        num_cols = set(gdf.select_dtypes(include=[np.number]).columns.tolist())
        if dependent not in gdf.columns:
            return f"因变量字段「{dependent}」不存在"
        if dependent not in num_cols:
            return f"因变量「{dependent}」不是数值字段，空间回归要求数值型"
        indep_list = [s.strip() for s in str(independents).split(",") if s.strip()]
        if not indep_list:
            return "自变量 independents 为空，请用逗号分隔数值字段名"
        for fld in indep_list:
            if fld not in gdf.columns:
                return f"自变量字段「{fld}」不存在"
            if fld not in num_cols:
                return f"自变量「{fld}」不是数值字段，空间回归要求数值型"
        data = gdf[[dependent] + indep_list].apply(pd.to_numeric, errors="coerce")
        data = data.replace([np.inf, -np.inf], np.nan).dropna()
        n = len(data)
        p = len(indep_list) + 1
        if n < p + 1:
            return f"有效样本数（{n}）太少，OLS 至少需要 {p + 1} 个"
        X = np.column_stack([np.ones(n), data[indep_list].values.astype(float)])
        y = data[dependent].values.astype(float)
        beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
        if rank < p:
            return "OLS 设计矩阵秩不足（自变量重复或完全共线），无法可靠估计系数和显著性；请移除重复/线性相关字段后重试"
        resid = y - X @ beta
        dof = n - p
        rss = float(resid @ resid)
        tss = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - rss / tss if tss > 0 else float("nan")
        adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof if tss > 0 else float("nan")
        sigma2 = rss / dof
        try:
            se = np.sqrt(np.maximum(np.diag(np.linalg.pinv(X.T @ X)) * sigma2, 0.0))
        except Exception:
            se = np.full(p, np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            tvals = beta / se
        pvals = 2.0 * (1.0 - stats.t.cdf(np.abs(tvals), df=dof))
        aic = n * np.log(rss / n) + 2 * p if rss > 0 else float("inf")
        jb_stat, jb_p = (float("nan"), float("nan"))
        if rss > 0 and n > 2:
            try:
                jb_stat, jb_p = stats.jarque_bera(resid)
            except Exception:
                pass
        names = ["const"] + indep_list
        lines = [f"空间回归（OLS）完成，图层「{name}」，有效样本 {n} 个："]
        lines.append("  变量        系数        标准误      t 值      p 值")
        for nm, b, s, t, pv in zip(names, beta, se, tvals, pvals):
            lines.append(f"  {nm:<10} {b:>10.4f} {s:>10.4f} {t:>9.3f} {pv:>9.4f}")
        lines.append(f"  R = {r2:.4f}，调整 R = {adj_r2:.4f}，AIC = {aic:.2f}")
        if jb_p == jb_p:
            lines.append(f"  Jarque-Bera 正态性检验：统计量 = {jb_stat:.4f}，p = {jb_p:.4f}"
                         + ("（p<0.05，残差偏离正态）" if jb_p < 0.05 else "（未拒绝正态）"))
        else:
            lines.append("  Jarque-Bera 正态性检验：样本不足，已跳过")
        moran_txt = "残差 Moran's I：样本不足，已跳过"
        try:
            if n >= 5:
                sub = gdf.loc[data.index]
                # 残差自相关：面图层优先 queen 邻接；点/线图层 queen 不适用，退回 knn
                try:
                    W, _, w_backend = _build_spatial_weights(sub, method="queen", k=8)
                except Exception:
                    W, _, w_backend = _build_spatial_weights(sub, method="knn", k=8)
                mi = _moran_from_weights(W, resid)
                if mi is not None:
                    I, z, pv2, mtd = mi
                    moran_txt = (f"残差 Moran's I = {I:.4f}，z = {z:.2f}，p = {pv2:.4f}"
                                 f"（{w_backend} queen 权重，{mtd}；"
                                 + ("残差仍存在显著空间自相关" if abs(z) > 1.96 else "残差无显著空间自相关") + "）")
        except Exception as _me:
            moran_txt = f"残差 Moran's I 计算跳过：{str(_me)[:120]}"
        lines.append("  " + moran_txt)
        summary = _stats_summary("spatial_regression", {
            "layer": name, "model": "ols", "n": n,
            "coefficients": {nm: round(float(b), 6) for nm, b in zip(names, beta)},
            "r2": None if r2 != r2 else round(float(r2), 6),
            "adj_r2": None if adj_r2 != adj_r2 else round(float(adj_r2), 6),
            "aic": round(float(aic), 4) if np.isfinite(aic) else None,
        })
        lines.append(summary)
        lines.append("（本工具只产出数值结果，不生成地图图层）")
        return "\n".join(lines)
    except Exception as e:
        return f"空间回归失败: {str(e)[:300]}"


@tool
def directional_distribution(layer_name: str, group_field: str = "", weight_field: str = "",
                             std_deviations: str = "1_std,2_std") -> str:
    """方向分布（标准差椭圆）：按分组计算中心、长短轴标准差距离与方向角，并生成椭圆面图层供上图。
    - layer_name: 图层名（点要素，或可取质心的面/线）。
    - group_field: 可选分组字段（空=全部要素一组）。
    - weight_field: 可选权重字段（需为非负数值；空=等权）。
    - std_deviations: 要输出的标准差倍数，逗号分隔，如 '1_std,2_std'（也接受 2、1.5 等数字）。
    输出：每组中心 X/Y、方向角（自正北顺时针，度）、X/Y 轴标准差距离（米）；椭圆在 UTM 投影下计算后转回 WGS84 上图。
    """
    try:
        import numpy as np
        import geopandas as gpd
        from shapely.geometry import Polygon

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if group_field and group_field not in gdf.columns:
            return f"分组字段「{group_field}」不存在"
        gdf_metric, crs_m = _stats_metric_gdf(gdf)
        coords, weights = _stats_coords_weights(gdf_metric, weight_field)
        mults = []
        raw = str(std_deviations if std_deviations is not None else "1_std,2_std")
        raw = raw.replace("_std", " ").replace("std", " ").replace("标准差", " ")
        for tok in raw.replace("，", ",").split(","):
            for sub in tok.split():
                try:
                    v = float(sub)
                    if v > 0:
                        mults.append(v)
                except ValueError:
                    if sub.strip():
                        return f"std_deviations 解析失败：'{sub.strip()}'，示例 '1_std,2_std'"
        if not mults:
            mults = [1.0, 2.0]
        if group_field:
            if gdf_metric[group_field].isna().all():
                return f"分组字段「{group_field}」全为空"
            groups = list(gdf_metric.groupby(group_field, dropna=True).groups.keys())
            if not groups:
                return f"分组字段「{group_field}」没有有效分组"
        else:
            groups = [None]
        polys, attrs, lines, skipped = [], [], [], []
        for gval in groups:
            if gval is None:
                c, w, glabel = coords, weights, "全部要素"
            else:
                mask = (gdf_metric[group_field] == gval).values
                c = coords[mask]
                w = weights[mask] if weights is not None else None
                glabel = str(gval)
            n_g = len(c)
            if n_g < 2:
                skipped.append(f"组「{glabel}」要素数 {n_g} < 2")
                continue
            ww = np.ones(n_g, dtype=float) if w is None else np.asarray(w, dtype=float)
            if not np.isfinite(ww).all() or (ww < 0).any() or ww.sum() <= 0:
                return f"组「{glabel}」权重无效：必须为有限非负数且总和大于 0"
            wsum = float(ww.sum())
            cx = float((ww * c[:, 0]).sum() / wsum)
            cy = float((ww * c[:, 1]).sum() / wsum)
            dx = c[:, 0] - cx
            dy = c[:, 1] - cy
            sxx = float((ww * dx * dx).sum() / wsum)
            syy = float((ww * dy * dy).sum() / wsum)
            sxy = float((ww * dx * dy).sum() / wsum)
            vals, vecs = np.linalg.eigh(np.array([[sxx, sxy], [sxy, syy]], dtype=float))
            order = np.argsort(vals)[::-1]
            vals = np.maximum(vals[order], 0.0)
            vecs = vecs[:, order]
            sdx = float(np.sqrt(vals[0]))
            sdy = float(np.sqrt(vals[1]))
            maj = vecs[:, 0]
            rot = float(np.degrees(np.arctan2(maj[0], maj[1]))) % 360.0
            lines.append(f"  组「{glabel}」：n={n_g}，中心=({cx:.2f}, {cy:.2f})，方向角={rot:.2f}，"
                         f"X轴标准差={sdx:.2f} m，Y轴标准差={sdy:.2f} m")
            ux, uy = float(maj[0]), float(maj[1])
            vx, vy = -uy, ux
            t = np.linspace(0.0, 2.0 * np.pi, 73)
            if sdx <= 0 or sdy <= 0:
                # 点共线/重合时某个轴标准差为 0，椭圆退化成线段，无法构成多边形
                skipped.append(f"组「{glabel}」点共线或重合（轴标准差 {sdx:.3f}/{sdy:.3f}）")
                continue
            for m in mults:
                a, b = sdx * m, sdy * m
                ex = cx + a * np.cos(t) * ux + b * np.sin(t) * vx
                ey = cy + a * np.cos(t) * uy + b * np.sin(t) * vy
                polys.append(Polygon(list(zip(ex.tolist(), ey.tolist()))))
                attrs.append({
                    "group": glabel, "std_dev": float(m), "center_x": round(cx, 3),
                    "center_y": round(cy, 3), "rotation_deg": round(rot, 3),
                    "x_std_distance": round(sdx, 3), "y_std_distance": round(sdy, 3),
                })
        if not polys:
            reason = "；".join(skipped) if skipped else "没有可用分组"
            return f"标准差椭圆未生成：没有任何分组能构成有效椭圆（{reason}）"
        ell = gpd.GeoDataFrame(attrs, geometry=polys, crs=crs_m).to_crs("EPSG:4326")
        result_name = f"{name}_标准差椭圆"
        _gdf_to_layer(ell, result_name)
        summary = _stats_summary("directional_distribution", {
            "layer": name, "layer_out": result_name, "ellipses": len(ell), "std_deviations": mults,
            "skipped_groups": skipped,
        })
        skip_txt = ("\n- 已跳过分组：" + "；".join(skipped)) if skipped else ""
        return (f"方向分布（标准差椭圆）完成，结果图层「{result_name}」已加载到地图：\n"
                + "\n".join(lines) + f"\n- 椭圆要素数：{len(ell)}{skip_txt}\n{summary}")
    except Exception as e:
        return f"方向分布分析失败: {str(e)[:300]}"


@tool
def central_tendency(layer_name: str, weight_field: str = "") -> str:
    """中心趋势分析：平均中心、中位中心、中心要素、标准距离与平均最近邻比率。
    - layer_name: 图层名（点要素，或可取质心的面/线）。
    - weight_field: 可选权重字段（需为非负数值；空=等权）。
    输出：平均中心、中位中心、中心要素（到其他要素总距离最小者）、标准距离（米）、平均最近邻比率及其期望/观测/z/p 值。
    注意：本工具只产出数值结果，不生成地图图层。"""
    try:
        import numpy as np
        from scipy.spatial.distance import cdist
        from scipy.stats import norm

        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        gdf_metric, crs_m = _stats_metric_gdf(gdf)
        coords, weights = _stats_coords_weights(gdf_metric, weight_field)
        n = len(coords)
        if n < 2:
            return f"要素数（{n}）太少，中心趋势至少需要 2 个"
        ww = np.ones(n, dtype=float) if weights is None else np.asarray(weights, dtype=float)
        if not np.isfinite(ww).all() or (ww < 0).any() or ww.sum() <= 0:
            return "权重字段必须为有限非负数且总和大于 0"
        wsum = float(ww.sum())
        mean_x = float((ww * coords[:, 0]).sum() / wsum)
        mean_y = float((ww * coords[:, 1]).sum() / wsum)
        median_x, median_y = _geometric_median(coords, ww)
        med_x, med_y = float(median_x), float(median_y)
        D = cdist(coords, coords)
        total_dist = D.sum(axis=1)
        center_idx = int(np.argmin(total_dist))
        sx = float(np.sqrt((ww * (coords[:, 0] - mean_x) ** 2).sum() / wsum))
        sy = float(np.sqrt((ww * (coords[:, 1] - mean_y) ** 2).sum() / wsum))
        std_dist = float(np.sqrt(sx ** 2 + sy ** 2))
        nearest = np.where(~np.eye(n, dtype=bool), D, np.inf).min(axis=1)
        obs_mean = float(nearest.mean())
        minx, miny, maxx, maxy = [float(v) for v in gdf_metric.total_bounds]
        b_w, b_h = (maxx - minx), (maxy - miny)
        area = b_w * b_h
        if area > 0:
            density = n / area
            exp_mean = 0.5 / np.sqrt(density)
            se_ann = 0.26136 / np.sqrt(n * density)
            ratio = obs_mean / exp_mean
            z_ann = (obs_mean - exp_mean) / se_ann
            p_ann = 2.0 * (1.0 - norm.cdf(abs(z_ann)))
            pattern = ("聚集分布（观测最近邻距离小于期望）" if ratio < 1 else
                       "离散分布（观测最近邻距离大于期望）" if ratio > 1 else "随机分布")
        else:
            exp_mean = se_ann = ratio = z_ann = p_ann = float("nan")
            pattern = "范围面积为 0，无法计算平均最近邻"
        try:
            center_fid = gdf["_fid"].iloc[center_idx] if "_fid" in gdf.columns else center_idx
        except Exception:
            center_fid = center_idx
        summary = _stats_summary("central_tendency", {
            "layer": name, "n": n, "crs": crs_m,
            "mean_center": [round(mean_x, 3), round(mean_y, 3)],
            "median_center": [round(med_x, 3), round(med_y, 3)],
            "standard_distance_m": round(std_dist, 3),
            "ann_observed_mean_m": round(obs_mean, 3),
            "ann_expected_mean_m": None if exp_mean != exp_mean else round(float(exp_mean), 3),
            "ann_se": None if se_ann != se_ann else round(float(se_ann), 4),
            "ann_z": None if z_ann != z_ann else round(float(z_ann), 4),
            "ann_p": None if p_ann != p_ann else round(float(p_ann), 6),
            "ann_ratio": None if ratio != ratio else round(float(ratio), 4),
        })
        return (
            f"中心趋势分析完成，图层「{name}」，要素数 {n}（投影：{crs_m}）：\n"
            f"- 平均中心：(X={mean_x:.2f}, Y={mean_y:.2f}) m\n"
            f"- 中位中心：(X={med_x:.2f}, Y={med_y:.2f}) m\n"
            f"- 中心要素：第 {center_idx + 1} 个要素（_fid={center_fid}），到其他要素总距离 {total_dist[center_idx]:.2f} m\n"
            f"- 标准距离：{std_dist:.2f} m（X 向 {sx:.2f} m，Y 向 {sy:.2f} m）\n"
            f"- 平均最近邻：观测均值 {obs_mean:.2f} m，期望均值 {exp_mean:.2f} m，"
            f"比率 ANN = {ratio:.4f}，z = {z_ann:.3f}，p = {p_ann:.4f}（{pattern}）\n"
            f"{summary}\n"
            f"（本工具只产出数值结果，不生成地图图层）"
        )
    except Exception as e:
        return f"中心趋势分析失败: {str(e)[:300]}"


@tool
def od_cost_matrix(origins_layer: str, destinations_layer: str, network_source: str = "osm") -> str:
    """多对多 OD 成本矩阵：起点/终点吸附到既有 OSM 路网节点后跑多源 Dijkstra，输出成本矩阵文件产物。
    - origins_layer: 起点图层名（点要素）。
    - destinations_layer: 终点图层名（点要素）。
    - network_source: 路网来源。'osm'（默认）= 复用已注册的路网图层（按起点坐标自动匹配）；
      也可直接填已注册路网图层名（如 download_road_network 生成的图层）。
    输出：<临时输出目录>/stats/od/<起点>_<终点>_od_matrix.csv 与同名 .json，并返回总/平均/最大出行成本（米）与不可达对数。
    注意：本工具只产出磁盘文件，不生成地图图层。
    """
    try:
        import numpy as np
        import csv as _csv
        import networkx as nx
        from backend.services import network_service as ns

        ogdf, oname = _layer_to_gdf(origins_layer)
        if ogdf is None:
            return oname
        dgdf, dname = _layer_to_gdf(destinations_layer)
        if dgdf is None:
            return dname
        o_pts = [(float(p.x), float(p.y)) for p in ogdf.geometry.representative_point()]
        d_pts = [(float(p.x), float(p.y)) for p in dgdf.geometry.representative_point()]
        if not o_pts or not d_pts:
            return "起点或终点图层为空"
        src = str(network_source or "osm").strip()
        info = None
        if src and src.lower() != "osm":
            info = _registered_layers.get(src)
            if info is None:
                cands = [n for n in _registered_layers if src in n]
                if len(cands) == 1:
                    src, info = cands[0], _registered_layers[cands[0]]
        if info is None:
            for (x, y) in o_pts:
                cand = _find_layer_for_coord(x, y)
                if cand and cand in _registered_layers:
                    info, src = _registered_layers[cand], cand
                    break
        if info is None and len(_registered_layers) == 1:
            src = next(iter(_registered_layers))
            info = _registered_layers[src]
        if info is None:
            return ("未找到可用的路网图层（network_source='osm' 需要先注册路网）：请先调用 download_road_network 下载路网，"
                    f"或把已注册路网图层名传给 network_source。当前图层：{', '.join(list(_registered_layers.keys())[:10]) or '无'}")
        geojson = info.get("geojson", {})
        if not geojson or not geojson.get("features"):
            return f"路网图层「{src}」为空"
        graph = ns._get_cached_graph(geojson)
        if not graph or not graph.nodes:
            return f"路网图层「{src}」未构建出有效图（需要 LineString/MultiLineString 路网要素）"

        def _snap_all(pts):
            nodes, missed = [], []
            for index, pt in enumerate(pts):
                s = ns.snap_to_network(geojson, pt, max_dist=5000)
                if s.get("found") and s.get("snapped"):
                    nodes.append(tuple(s["snapped"]))
                else:
                    nodes.append(None)
                    missed.append(index)
            return nodes, missed

        o_nodes, o_miss = _snap_all(o_pts)
        d_nodes, d_miss = _snap_all(d_pts)
        if not any(o_nodes) or not any(d_nodes):
            return "起点或终点全部无法吸附到路网节点（请检查路网覆盖范围是否包含起终点）"
        matrix = [[None] * len(d_pts) for _ in range(len(o_pts))]
        for i, onode in enumerate(o_nodes):
            if onode is None or onode not in graph:
                continue
            lengths = nx.single_source_dijkstra_path_length(graph, onode, weight="weight")
            for j, dnode in enumerate(d_nodes):
                if dnode is None:
                    continue
                cost = lengths.get(dnode)
                if cost is not None:
                    matrix[i][j] = round(float(cost), 3)
        flat = [v for row in matrix for v in row if v is not None]
        total = float(np.sum(flat)) if flat else 0.0
        mean_c = float(np.mean(flat)) if flat else 0.0
        max_c = float(np.max(flat)) if flat else 0.0
        unreachable = sum(
            1 for i, row in enumerate(matrix) for j, value in enumerate(row)
            if value is None and o_nodes[i] is not None and d_nodes[j] is not None
        )
        unsnapped_pairs = sum(
            1 for i, row in enumerate(matrix) for j in range(len(row))
            if o_nodes[i] is None or d_nodes[j] is None
        )
        out_dir = _stats_out_dir("od")
        stem = f"{_stats_safe_name(oname)}__{_stats_safe_name(dname)}_od_matrix"
        csv_path = os.path.join(out_dir, stem + ".csv")
        json_path = os.path.join(out_dir, stem + ".json")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["origin_index", "destination_index", "cost_m", "reachable"])
            for i, row in enumerate(matrix):
                for j, v in enumerate(row):
                    w.writerow([i, j, "" if v is None else v, 1 if v is not None else 0])
        payload = {
            "origins_layer": oname, "destinations_layer": dname, "network_layer": src,
            "n_origins": len(o_pts), "n_destinations": len(d_pts),
            "n_origins_snapped": sum(node is not None for node in o_nodes),
            "n_destinations_snapped": sum(node is not None for node in d_nodes),
            "unsnapped_origin_indices": o_miss,
            "unsnapped_destination_indices": d_miss,
            "unsnapped_pairs": unsnapped_pairs,
            "unreachable_pairs": unreachable, "cost_unit": "meter",
            "total_cost_m": round(total, 3), "mean_cost_m": round(mean_c, 3), "max_cost_m": round(max_c, 3),
            "matrix": matrix, "csv": csv_path,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        record_tool_artifact(os.path.basename(csv_path), csv_path, artifact_type="file")
        record_tool_artifact(os.path.basename(json_path), json_path, artifact_type="file")
        summary = _stats_summary("od_cost_matrix", {
            "origins": oname, "destinations": dname, "network_layer": src,
            "n_origins": len(o_pts), "n_destinations": len(d_pts),
            "n_origins_snapped": sum(node is not None for node in o_nodes),
            "n_destinations_snapped": sum(node is not None for node in d_nodes),
            "unsnapped_origin_indices": o_miss,
            "unsnapped_destination_indices": d_miss,
            "unsnapped_pairs": unsnapped_pairs,
            "total_cost_m": round(total, 3), "mean_cost_m": round(mean_c, 3), "max_cost_m": round(max_c, 3),
            "unreachable_pairs": unreachable, "csv": csv_path, "json": json_path,
        })
        miss_txt = ""
        if o_miss or d_miss:
            origin_indices = ", ".join(str(i + 1) for i in o_miss) or "无"
            destination_indices = ", ".join(str(i + 1) for i in d_miss) or "无"
            miss_txt = (f"\n- 未能吸附并保留为无成本单元：起点 {len(o_miss)} 个（输入序号 {origin_indices}）、"
                        f"终点 {len(d_miss)} 个（输入序号 {destination_indices}）")
        return (
            f"OD 成本矩阵完成（多源 Dijkstra，路网图层「{src}」）：\n"
            f"- 起点 {len(o_nodes)} 个，终点 {len(d_nodes)} 个，不可达 {unreachable} 对{miss_txt}\n"
            f"- 总出行成本 {total:.2f} m，平均 {mean_c:.2f} m，最大 {max_c:.2f} m\n"
            f"- 矩阵文件：{csv_path}\n"
            f"- JSON 文件：{json_path}\n"
            f"（本工具产物为磁盘文件而非地图图层）\n"
            f"{summary}"
        )
    except Exception as e:
        return f"OD 成本矩阵计算失败: {str(e)[:300]}"


# ============================================================
# 工具: feature_to_raster  矢量转栅格
# ============================================================
@tool
def feature_to_raster(layer_name: str, value_field: str = "", cell_size: float = 0.0, all_touched: bool = False) -> str:
    """矢量转栅格：把点/线/面要素按属性值烧录到栅格网格（ArcGIS FeatureToRaster 对应）。
    - layer_name: 矢量图层名（注册图层，EPSG:4326）。
    - value_field: 作为像元值的属性字段名；留空则全部烧录常量 1。
    - cell_size: 像元尺寸（度，与图层同单位）；0 = 自动取使长边约 256 像元的尺寸。
    - all_touched: true=像元被几何触碰即烧录；false（默认）=像元中心在几何内才烧录。
    结果 GeoTIFF 落盘并输出预览图层。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.features import rasterize
        from rasterio.transform import from_origin
        import types
        gdf, name = _layer_to_gdf(layer_name)
        if gdf is None:
            return name
        if gdf.empty:
            return f"图层「{name}」没有要素，无法转栅格"
        try:
            requested_cell_size = float(cell_size)
        except (TypeError, ValueError, OverflowError):
            return "矢量转栅格失败：cell_size 必须是有限的非负数"
        if not np.isfinite(requested_cell_size) or requested_cell_size < 0:
            return "矢量转栅格失败：cell_size 必须是有限的非负数"
        minx, miny, maxx, maxy = gdf.total_bounds
        if not np.isfinite([minx, miny, maxx, maxy]).all():
            return "矢量转栅格失败：图层范围包含非有限坐标"
        span_x, span_y = maxx - minx, maxy - miny
        if requested_cell_size > 0:
            cs = requested_cell_size
        else:
            cs = max(span_x, span_y) / 256.0
            if cs <= 0:
                return "图层范围为空，无法推导像元尺寸，请显式传 cell_size"
        if span_x <= 0:
            minx -= cs / 2
            maxx += cs / 2
            span_x = cs
        if span_y <= 0:
            miny -= cs / 2
            maxy += cs / 2
            span_y = cs
        width_ratio, height_ratio = span_x / cs, span_y / cs
        if not np.isfinite([width_ratio, height_ratio]).all():
            return "矢量转栅格失败：目标网格超过单次处理上限（400 万像元）；请增大 cell_size 或先裁剪图层范围"
        width = max(1, int(math.ceil(width_ratio)))
        height = max(1, int(math.ceil(height_ratio)))
        if width * height > 4_000_000:
            return (f"矢量转栅格失败：目标网格为 {width}×{height} 像元，超过单次处理上限（400 万像元）；"
                    "请增大 cell_size 或先裁剪图层范围")
        transform = from_origin(minx, maxy, cs, cs)
        nodata = 0
        if value_field:
            if value_field not in gdf.columns:
                return f"未找到字段「{value_field}」，可用字段：{', '.join(map(str, gdf.columns))}"
            shapes_iter = []
            for geom, val in zip(gdf.geometry, gdf[value_field]):
                if geom is None or geom.is_empty or val is None:
                    continue
                try:
                    numeric_value = float(val)
                except (TypeError, ValueError):
                    return f"字段「{value_field}」含非数值属性，矢量转栅格需要数值字段"
                if np.isnan(numeric_value):
                    continue
                if not np.isfinite(numeric_value):
                    return f"字段「{value_field}」含非有限数值，无法烧录到栅格"
                shapes_iter.append((geom, numeric_value))
            # NaN is a distinct background marker so valid zero and negative values survive.
            fill_value = np.nan
            nodata = np.nan
            dtype = "float64"
        else:
            shapes_iter = ((geom, 1) for geom in gdf.geometry if geom is not None)
            fill_value = 0
            dtype = "uint8"
        arr = rasterize(
            shapes_iter, out_shape=(height, width), transform=transform,
            fill=fill_value, all_touched=bool(all_touched), dtype=dtype,
        )
        out_name = f"{name}_转栅格"
        out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        profile = dict(driver="GTiff", height=height, width=width, count=1, dtype=arr.dtype.name,
                       crs="EPSG:4326", transform=transform, nodata=nodata)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(arr, 1)
        with rasterio.open(out_path) as _src_for_preview:
            note = _raster_preview_op(_src_for_preview, arr, out_name, f"矢量转栅格 {width}x{height}@{cs:.6g}")
        if value_field:
            burned_values = arr[np.isfinite(arr)]
            burned_count = int(burned_values.size)
            stat = (f"值域 {np.min(burned_values):.4g}~{np.max(burned_values):.4g}"
                    if burned_count else "无有效属性值")
        else:
            burned_count = int(np.count_nonzero(arr))
            stat = "常量 1"
        return (f"矢量转栅格完成：{width}x{height} 像元，像元尺寸 {cs:.6g}，已烧录 {burned_count} 个像元（{stat}）。"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"矢量转栅格失败: {str(e)[:300]}"


# ============================================================
# 工具: raster_to_feature  栅格转矢量
# ============================================================
@tool
def raster_to_feature(layer_name: str, connectivity: int = 8, simplify: float = 0.0) -> str:
    """栅格转矢量：把分类栅格按连续同值区域矢量化为面图层（ArcGIS RasterToPolygon 对应）。
    - layer_name: 上传的 GeoTIFF 栅格名。
    - connectivity: 4 或 8，同值像元连通判定。
    - simplify: 面简化容差，单位与栅格 CRS 的坐标单位一致；0 = 不简化。
    输出面图层（含 value 属性），面数与面积统计随结果返回。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.features import shapes as rio_shapes
        from shapely.geometry import shape as shp_shape
        import geopandas as gpd
        try:
            conn_value = float(connectivity)
        except (TypeError, ValueError, OverflowError):
            return "栅格转矢量失败：connectivity 仅支持 4 或 8"
        if not np.isfinite(conn_value) or conn_value not in (4, 8):
            return "栅格转矢量失败：connectivity 仅支持 4 或 8"
        try:
            simplify_value = float(simplify)
        except (TypeError, ValueError, OverflowError):
            return "栅格转矢量失败：simplify 必须是有限的非负数"
        if not np.isfinite(simplify_value) or simplify_value < 0:
            return "栅格转矢量失败：simplify 必须是有限的非负数"
        tif_path = _find_uploaded_tif(layer_name)
        if tif_path is None:
            return f"未找到栅格文件「{layer_name}」，请先上传 GeoTIFF"
        conn = int(conn_value)
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return "栅格转矢量失败：输入栅格缺少 CRS，无法可靠定位矢量结果；请先为栅格定义正确的坐标系"
            arr = src.read(1)
            mask = np.isfinite(arr) if arr.dtype.kind == "f" else np.ones_like(arr, dtype=bool)
            if src.nodata is not None:
                mask &= arr != src.nodata
            geoms = []
            vals = []
            for geom, val in rio_shapes(arr, mask=mask, transform=src.transform, connectivity=conn):
                if val == 0 or val is None:
                    continue
                geoms.append(shp_shape(geom))
                vals.append(val)
            if not geoms:
                return "栅格中没有可矢量化的有效像元（全为 nodata 或 0）"
            gdf = gpd.GeoDataFrame({"value": vals}, geometry=geoms, crs=src.crs)
        if simplify_value > 0:
            gdf["geometry"] = gdf.geometry.simplify(simplify_value, preserve_topology=True)
        out_name = f"{layer_name}_转矢量"
        _gdf_to_layer(gdf, out_name)
        utm = gdf.estimate_utm_crs()
        areas_km2 = gdf.to_crs(utm).geometry.area.sum() / 1e6 if utm is not None else float("nan")
        return (f"栅格转矢量完成：{len(gdf)} 个面（连通度 {conn}，值域 {min(vals)}~{max(vals)}），"
                f"总面积 {areas_km2:.3f} km²（UTM 投影计算）。图层「{out_name}」已加载到地图")
    except Exception as e:
        return f"栅格转矢量失败: {str(e)[:300]}"


# ============================================================
# 工具: create_fishnet  创建渔网格网
# ============================================================
@tool
def create_fishnet(extent_layer: str = "", cell_size: float = 0.0, rows: int = 0, cols: int = 0, out_name: str = "fishnet") -> str:
    """创建矩形渔网采样格网（ArcGIS CreateFishnet 对应）。
    - extent_layer: 范围参照图层名；留空则用当前所有注册图层的联合范围。
    - cell_size: 每格边长（度）；与 rows/cols 二选一，同时给出时优先 cell_size。
    - rows / cols: 显式行列数（cell_size 为 0 时生效）。
    - out_name: 输出图层名。
    输出面格网图层，逐格带 row/col 属性。"""
    try:
        import numpy as np
        from shapely.geometry import box
        import geopandas as gpd
        try:
            requested_cell_size = float(cell_size)
        except (TypeError, ValueError, OverflowError):
            return "创建渔网失败：cell_size 必须是有限的非负数"
        if not np.isfinite(requested_cell_size) or requested_cell_size < 0:
            return "创建渔网失败：cell_size 必须是有限的非负数"
        if extent_layer:
            gdf_e, ename = _layer_to_gdf(extent_layer)
            if gdf_e is None:
                return ename
            minx, miny, maxx, maxy = gdf_e.total_bounds
        else:
            if not _registered_layers:
                return "当前没有任何注册图层，请先加载图层或显式传 extent_layer"
            bs = [gpd.GeoDataFrame.from_features(v.get("geojson", {}).get("features", []), crs="EPSG:4326").total_bounds
                  for v in _registered_layers.values() if v.get("geojson", {}).get("features")]
            if not bs:
                return "注册图层都没有要素，无法确定范围"
            minx = min(b[0] for b in bs); miny = min(b[1] for b in bs)
            maxx = max(b[2] for b in bs); maxy = max(b[3] for b in bs)
        if not np.isfinite([minx, miny, maxx, maxy]).all():
            return "创建渔网失败：范围包含非有限坐标"
        w = maxx - minx; h = maxy - miny
        if w <= 0 or h <= 0:
            return "范围为空，无法创建格网"
        if requested_cell_size > 0:
            cs = requested_cell_size
            col_ratio, row_ratio = w / cs, h / cs
            if not np.isfinite([col_ratio, row_ratio]).all():
                return "创建渔网失败：目标格网超过单次处理上限（10000 格）"
            ncols = max(1, int(np.ceil(col_ratio)))
            nrows = max(1, int(np.ceil(row_ratio)))
        elif rows and cols and int(rows) > 0 and int(cols) > 0:
            nrows, ncols = int(rows), int(cols)
            cs = 0.0
        else:
            return "请提供 cell_size，或同时提供 rows 与 cols"
        cell_count = nrows * ncols
        if cell_count > 10_000:
            return (f"创建渔网失败：请求 {nrows} 行 × {ncols} 列（{cell_count} 格），"
                    "超过单次处理上限（10000 格）；请增大 cell_size 或缩小范围")
        feats = []
        for r in range(nrows):
            for c in range(ncols):
                x0 = minx + c * (w / ncols); x1 = minx + (c + 1) * (w / ncols)
                y0 = miny + r * (h / nrows); y1 = miny + (r + 1) * (h / nrows)
                feats.append({"type": "Feature", "properties": {"row": r, "col": c},
                              "geometry": box(x0, y0, x1, y1).__geo_interface__})
        out = {"type": "FeatureCollection", "features": feats}
        final_name = out_name or "fishnet"
        _push_layer(final_name, out, {"color": "#555", "weight": 1, "fillOpacity": 0.05})
        _register_layer(final_name, out)
        cs_txt = f"{w / ncols:.6g} x {h / nrows:.6g}"
        return (f"渔网创建完成：{nrows} 行 x {ncols} 列 = {nrows * ncols} 格，格尺寸 {cs_txt}，"
                f"范围 {w:.4g} x {h:.4g}。图层「{final_name}」已加载到地图")
    except Exception as e:
        return f"渔网创建失败: {str(e)[:300]}"


def _cost_graph(cost_arr):
    """cost_distance / least_cost_path 共用的 8 邻域代价图。返回 (csr_graph, node_index)。
    节点 = 有效像元；边权 = 平均代价  像元距离（4 邻 = 1，对角 = sqrt(2)）。"""
    import numpy as np
    from scipy.sparse import csr_matrix
    h, w = cost_arr.shape
    valid = np.isfinite(cost_arr) & (cost_arr > 0)
    valid_count = int(valid.sum())
    if valid_count > 100_000:
        raise ValueError("有效代价像元超过单次处理上限（10 万）；请先裁剪或重采样栅格")
    idx = np.full((h, w), -1, dtype=np.int64)
    idx[valid] = np.arange(valid_count)
    rows_l, cols_l, vals = [], [], []
    nb = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
          (-1, -1, 2 ** 0.5), (-1, 1, 2 ** 0.5), (1, -1, 2 ** 0.5), (1, 1, 2 ** 0.5)]
    ca = cost_arr
    for r in range(h):
        for c in range(w):
            if not valid[r, c]:
                continue
            u = idx[r, c]
            for dr, dc, dist in nb:
                rr, cc = r + dr, c + dc
                if 0 <= rr < h and 0 <= cc < w and valid[rr, cc]:
                    rows_l.append(u); cols_l.append(idx[rr, cc])
                    vals.append((float(ca[r, c]) + float(ca[rr, cc])) * 0.5 * dist)
    n = valid_count
    g = csr_matrix((vals, (rows_l, cols_l)), shape=(n, n))
    return g, idx, valid


# ============================================================
# 工具: cost_distance  代价距离面
# ============================================================
@tool
def cost_distance(cost_layer: str, source_layer: str, out_name: str = "") -> str:
    """代价距离面：基于代价栅格，计算每个像元到最近源的最小累积代价（8 邻域 Dijkstra，ArcGIS CostDistance 对应）。
    - cost_layer: 代价栅格（上传的 GeoTIFF，值>0，越大越难通行；nodata/非正值为不可通行）。
    - source_layer: 源要素图层（会烧录到代价栅格网格上作为源像元）。
    - out_name: 输出栅格名。
    输出累积代价 GeoTIFF + 预览图层，并报告可达/不可达像元数。"""
    try:
        import numpy as np
        import rasterio
        from scipy.sparse.csgraph import dijkstra
        from rasterio.features import rasterize as rio_rasterize
        tif_path = _find_uploaded_tif(cost_layer)
        if tif_path is None:
            return f"未找到代价栅格「{cost_layer}」，请先上传 GeoTIFF"
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return f"代价栅格「{cost_layer}」缺少 CRS，无法可靠对齐源图层"
            if src.width * src.height > 1_000_000:
                return "代价距离失败：栅格超过单次处理上限（100 万像元）；请先裁剪或重采样"
            cost = src.read(1).astype("float64")
            transform = src.transform
            crs = src.crs
            nodata = src.nodata
        valid0 = np.isfinite(cost)
        if nodata is not None:
            valid0 &= cost != nodata
        cost = np.where(valid0, cost, np.nan)
        gdf_s, sname = _layer_to_gdf(source_layer)
        if gdf_s is None:
            return sname
        gdf_s = gdf_s.to_crs(crs)
        h, w = cost.shape
        src_r = rio_rasterize(
            ((geom, 1) for geom in gdf_s.geometry if geom is not None),
            out_shape=(h, w), transform=transform, fill=0, dtype="uint8")
        src_nodes = np.argwhere(src_r == 1)
        if src_nodes.size == 0:
            return "源图层与代价栅格范围不相交，没有源像元"
        graph, idx, valid = _cost_graph(cost)
        flat_src = [idx[r, c] for r, c in src_nodes if idx[r, c] >= 0]
        if not flat_src:
            return "源图层落在代价栅格的 NoData 或非正值区域，没有可通行的源像元"
        dist = dijkstra(graph, directed=False, indices=flat_src, min_only=True)
        out = np.full(cost.shape, np.nan, dtype="float64")
        vm = valid & (idx >= 0)
        out[vm] = dist[idx[vm]]
        reachable = int(np.isfinite(out).sum())
        unreachable = int((valid & ~np.isfinite(out)).sum())
        out_name = _safe_layer_export_stem(out_name or f"{cost_layer}_代价距离")
        out_path = os.path.join(_raster_output_dir(), out_name + ".tif")
        profile = dict(driver="GTiff", height=h, width=w, count=1, dtype="float64", crs=crs, transform=transform, nodata=float("nan"))
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(out, 1)
        with rasterio.open(out_path) as _src_preview:
            note = _raster_preview_op(_src_preview, out, out_name, "代价距离面（累积代价）")
        fin = out[np.isfinite(out)]
        return (f"代价距离完成（8 邻域 Dijkstra）：可达 {reachable} 像元，不可达 {unreachable} 像元，"
                f"代价范围 {fin.min():.3f}~{fin.max():.3f}（单位=代价栅格值像元距离）。"
                f"结果已保存 {out_name}.tif；{note}")
    except Exception as e:
        return f"代价距离计算失败: {str(e)[:300]}"


# ============================================================
# 工具: least_cost_path  最小代价路径
# ============================================================
@tool
def least_cost_path(cost_layer: str, source_layer: str, destination_layer: str) -> str:
    """最小代价路径：在代价栅格上求源到目的地的最小累积代价路径（与 cost_distance 共用同一图与算法）。
    - cost_layer: 代价栅格（GeoTIFF）。
    - source_layer / destination_layer: 源/目的地点图层。
    输出路径线图层（含累积代价属性），并报告总代价与像素步数。"""
    try:
        import numpy as np
        import rasterio
        from scipy.sparse.csgraph import dijkstra
        from rasterio.features import rasterize as rio_rasterize
        from shapely.geometry import LineString, Point
        import geopandas as gpd
        tif_path = _find_uploaded_tif(cost_layer)
        if tif_path is None:
            return f"未找到代价栅格「{cost_layer}」，请先上传 GeoTIFF"
        with rasterio.open(tif_path) as src:
            if src.crs is None:
                return f"代价栅格「{cost_layer}」缺少 CRS，无法可靠对齐源/目的地图层"
            if src.width * src.height > 1_000_000:
                return "最小代价路径失败：栅格超过单次处理上限（100 万像元）；请先裁剪或重采样"
            cost = src.read(1).astype("float64")
            transform = src.transform
            crs = src.crs
            nodata = src.nodata
        valid0 = np.isfinite(cost)
        if nodata is not None:
            valid0 &= cost != nodata
        cost = np.where(valid0, cost, np.nan)
        h, w = cost.shape
        graph, idx, valid = _cost_graph(cost)
        gdf_s, sname = _layer_to_gdf(source_layer)
        if gdf_s is None: return sname
        gdf_d, dname = _layer_to_gdf(destination_layer)
        if gdf_d is None: return dname
        gdf_s = gdf_s.to_crs(crs)
        gdf_d = gdf_d.to_crs(crs)
        def snap(g):
            pts = g.geometry.centroid
            rows = []
            inv = ~transform
            for pt in pts:
                col, row = inv * (pt.x, pt.y)
                r, c = math.floor(row), math.floor(col)
                if 0 <= r < h and 0 <= c < w and idx[r, c] >= 0:
                    rows.append(idx[r, c])
            return rows
        s_nodes = snap(gdf_s); d_nodes = snap(gdf_d)
        if not s_nodes or not d_nodes:
            return f"源或目的地未能吸附到有效像元（源 {len(s_nodes)} 个，目的地 {len(d_nodes)} 个），请检查位置是否在栅格有效区内"
        if len(s_nodes) * int(valid.sum()) > 4_000_000:
            return "最小代价路径失败：源点数量与有效像元规模过大；请减少源点或裁剪/重采样栅格"
        dist_mat, preds = dijkstra(graph, directed=False, indices=s_nodes, return_predecessors=True)
        lines = []; costs = []
        for di, dn in enumerate(d_nodes):
            best_si = int(np.argmin(dist_mat[:, dn])) if np.isfinite(dist_mat[:, dn]).any() else -1
            if best_si < 0 or not np.isfinite(dist_mat[best_si, dn]):
                continue
            total = float(dist_mat[best_si, dn])
            path_nodes = [dn]
            cur = dn
            while cur != best_si and cur >= 0:
                cur = preds[best_si, cur]
                if cur < 0: break
                path_nodes.append(int(cur))
            
            coords_rc = []
            for n in path_nodes:
                r, c = divmod(int(n), w)
                coords_rc.append((r, c))
            xs = []; ys = []
            inv_t = ~transform
            for r, c in coords_rc:
                x, y = transform * (c + 0.5, r + 0.5)
                xs.append(x); ys.append(y)
            if len(xs) >= 2:
                lines.append(LineString(zip(xs, ys))); costs.append(total)
        if not lines:
            return "源与目的地之间不存在可达路径（被 nodata/非正值阻断）"
        gdf = gpd.GeoDataFrame({"total_cost": costs}, geometry=lines, crs=crs)
        out_name = f"{sname}_到_{dname}_代价路径"
        _gdf_to_layer(gdf, out_name)
        utm = gdf.estimate_utm_crs()
        len_km = gdf.to_crs(utm).geometry.length.sum() / 1000.0 if utm is not None else float("nan")
        return (f"最小代价路径完成（与 cost_distance 共用 8 邻域图）：{len(lines)} 条路径，"
                f"总代价 {min(costs):.3f}~{max(costs):.3f}，路径总长 {len_km:.2f} km（UTM 投影计算）。"
                f"图层「{out_name}」已加载到地图")
    except Exception as e:
        return f"最小代价路径计算失败: {str(e)[:300]}"




# ============================================================
# 工具: metro_line  地铁线路查询与上图（国内高德 / 国际 OSM 双源）
# ============================================================
@tool
def metro_line(city: str, line: str = "") -> str:
    """查询城市地铁线路并上图（站序连线 + 站点图层，官方配色）。
    - city: 城市名（如 长沙/北京/上海/广州/深圳 等国内城市；柏林/东京/纽约 等国际城市）。
    - line: 线路名或编号（如 '1号线' / '2'）；留空 = 展示全城线网。
    国内城市走高德地铁数据（GCJ-02 自动转 WGS-84），国际城市走 OSM Overpass（真实轨道折线，带官方色）。
    结果含站点数、起讫站、换乘站标记。"""
    try:
        from backend.services.metro_service import build_metro_layers, norm_city, CN_CITY_CODES
        cnorm = norm_city(city)
        layers, summary = build_metro_layers(cnorm, line or "")
        out_names = []
        for spec in layers:
            _push_layer(spec["name"], spec["geojson"], spec["style"])
            _register_layer(spec["name"], spec["geojson"])
            out_names.append(spec["name"])
        return (f"地铁线路查询完成：{summary}\n"
                f"- 已上图 {len(out_names)} 个图层：{', '.join(out_names)}\n"
                f"- 来源：{'高德地铁数据（坐标已转 WGS-84）' if cnorm in CN_CITY_CODES else 'OSM 开源数据'}")
    except Exception as e:
        return f"地铁查询失败: {str(e)[:300]}"

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
    "export_layer": ("工具执行失败:", "GeoJSON导出验证失败:", "找到多个匹配：", "未找到图层"),
    "datav_boundary": ("工具执行失败:", "找到多个匹配：", "未找到", "获取失败:", "查询失败:"),
    "create_swipe": ("未找到图层", "卷帘对比需要两个不同的图层"),
    "spatial_graduated_colors": ("分级色彩渲染失败:", "图层「", "不是数值类型", "无有效数值", "不支持该分级方法", "无法分级", "找到多个匹配"),
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
