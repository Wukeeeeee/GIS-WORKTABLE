# -*- coding: utf-8 -*-
"""
backend.services.tool_modules.runtime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Layer 1 Runtime Layer State and GIS Layer Conversion Helpers.

This module serves as the authoritative Single Source of Truth for:
1. Shared runtime state:
   - Map layer registry (`_registered_layers`)
   - Pending frontend delivery queues (`_pending_layers`, `_pending_images`,
     `_pending_layer_ops`, `_pending_qa_warnings`, `_clear_layers_flag`, etc.)
   - State locks and concurrency controls (`_state_lock`, `_shared_state_lock`, `_session_locks`)
   - Output paths (`_temp_output_dir`, `_workspace_dir`)
2. Shared GIS layer conversion and registration helpers:
   - `_layer_to_gdf`: GeoDataFrame conversion from registered layers
   - `_gdf_to_layer`: Conversion and registration of GeoDataFrame to map layers
   - `_push_layer`: Enqueueing layers for frontend transmission
   - `_register_layer`: Validating, FID-injecting, and registering vector layers
   - `_register_raster_layer`: Validating and registering raster layers
   - `_unregister_layer`: Deregistering layers
   - `_disambiguate_layer_name`: Conflict-free layer name generation

Strict architectural constraints:
- Depends ONLY on `common.py`, standard libraries, and GIS libraries (geopandas, shapely).
- NEVER imports `backend.services.tools` or domain modules (zero circular imports).
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
import tempfile
import threading
import types
import unicodedata
import uuid
from typing import Any, Optional

import geopandas as gpd

from backend.services.tool_modules.common import (
    _compute_bbox,
    _layer_property_examples,
    _make_fid,
    _normalize_geojson,
    _normalize_layer_provenance,
    _valid_registration_geometry,
)

# ============================================================
# Shared Runtime State & Concurrency Controls
# ============================================================

_pending_layers: list = []          # 待推送到前端的 GeoJSON 图层
_pending_qa_warnings: list = []     # 质量自检警告（geo_qa 图层通过时收集）
_pending_images: list = []          # 待推送到前端的图片/HTML
_INLINE_HTML_PREVIEW_LIMIT = 2 * 1024 * 1024
_pending_aoi_suggestions: dict = {} # AOI 候选列表
_pending_heatmap: dict = {"latest": None}
_clear_layers_flag: bool = False
_pending_layer_ops: list = []
_current_amap_key: str = ""
_search_call_count: int = 0
_domain_fail: dict = {}             # 域名 -> 连续失败次数（熔断）
_DOMAIN_FAIL_LIMIT = 2              # 同域名连续失败 N 次即熔断
_search_cache: dict = {}            # query -> (时间戳, 文本)
_search_last_hit: dict = {}         # 引擎 -> 上次时间戳（限速防封）
_SEARCH_CACHE_TTL = 600.0           # 相同查询 10 分钟内复用
_ENGINE_MIN_INTERVAL = 1.5          # 同一引擎最小间隔（秒）

_exec_call_count: int = 0           # Python 执行次数（每轮重置）
_exec_log: list = []                # 执行日志记录，每轮 execute_python 用途及结果
_temp_output_dir: str = ""          # 由 reset_state 时初始化
_workspace_dir: str = ""
_raster_output_scope = threading.local()
_registered_layers: dict = {}       # 已注册图层元信息字典
_active_project_id = None
_current_task_id: str = ""          # 当前任务 ID（由 graph.py 设置）
_last_user_message: str = ""        # 用户原始消息（由 graph.py 每轮设置）
_current_run_id: str = ""           # 当前单次执行 ID
_conversation_context: str = ""     # 多轮上下文文本摘要

# 线程锁保证 get_pending_state 的"读取+清空"原子性
# RLock（可重入锁）：reset_registered_layers 持锁状态下调用 _register_layer 内部再次加锁不自锁
_state_lock = threading.RLock()

# 同 session 并发互斥：防止两条并发请求互相 reset/覆盖 pending 图层
_session_locks: dict = {}
_session_locks_guard = threading.Lock()
_shared_state_lock = threading.Lock()


def _sync_to_tools(var_name: str, val: Any) -> None:
    """直接同步运行时状态到 tools 模块字典，避免内部 LOAD_GLOBAL 读取到初始绑定。"""
    for mod_name in ("backend.services.tools", "tools"):
        tools_mod = sys.modules.get(mod_name)
        if tools_mod is not None:
            tools_mod.__dict__[var_name] = val


# ============================================================
# Temporary Directory Management
# ============================================================

def init_temp_dir() -> None:
    """初始化临时目录（在模块加载时或首次调用时执行）。"""
    global _temp_output_dir, _workspace_dir
    if not _temp_output_dir:
        _temp_output_dir = os.path.join(tempfile.gettempdir(), "gis_worktable_output")
        os.makedirs(_temp_output_dir, exist_ok=True)
        os.makedirs(os.path.join(_temp_output_dir, "output"), exist_ok=True)
    if not _workspace_dir:
        _workspace_dir = os.path.join(_temp_output_dir, "workspace")
        os.makedirs(_workspace_dir, exist_ok=True)
    _sync_to_tools("_temp_output_dir", _temp_output_dir)
    _sync_to_tools("_workspace_dir", _workspace_dir)


def get_temp_output_dir() -> str:
    """获取临时输出目录路径。"""
    init_temp_dir()
    return _temp_output_dir


# ============================================================
# Session & Shared Lock Helpers
# ============================================================

def session_lock_wait_seconds() -> float:
    """获取会话锁默认等待时长（秒）。"""
    raw = os.environ.get("GIS_SESSION_LOCK_WAIT", "20")
    try:
        val = float(raw)
        return max(0.0, val)
    except (ValueError, TypeError):
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
            lock = threading.Lock()
            _session_locks[sid] = lock
    if timeout is None:
        timeout = session_lock_wait_seconds()
    if timeout and timeout > 0:
        return lock.acquire(timeout=timeout)
    return lock.acquire(blocking=False)


def release_session_lock(session_id: str) -> None:
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
    """Release the coarse-grained process-wide state lock."""
    if _shared_state_lock.locked():
        try:
            _shared_state_lock.release()
        except RuntimeError:
            pass


# ============================================================
# Task & Conversation Context Accessors
# ============================================================

def set_current_task(task_id: str) -> None:
    """设置当前任务 ID（由 graph.py 在每轮请求开始时调用）。"""
    global _current_task_id
    _current_task_id = task_id or ""
    _sync_to_tools("_current_task_id", _current_task_id)


def get_current_task_id() -> str:
    """获取当前任务 ID。"""
    return _current_task_id


def set_current_run(run_id: str) -> None:
    """设置当前单次执行 ID（由 graph.py 在每轮请求开始时调用）。"""
    global _current_run_id
    _current_run_id = run_id or ""
    _sync_to_tools("_current_run_id", _current_run_id)


def get_current_run_id() -> str:
    """获取当前单次执行 ID。"""
    return _current_run_id


def set_last_user_message(msg: str) -> None:
    """记录本轮用户原始请求（由 graph.py 在每轮开始时调用）。"""
    global _last_user_message
    _last_user_message = (msg or "")[:500]
    _sync_to_tools("_last_user_message", _last_user_message)


def get_last_user_message() -> str:
    """获取当前轮用户原始请求。"""
    return _last_user_message


def set_conversation_context(ctx: str) -> None:
    """记录多轮上下文文本摘要（由 graph.py 在每轮开始时调用）。"""
    global _conversation_context
    _conversation_context = (ctx or "")[:3000]
    _sync_to_tools("_conversation_context", _conversation_context)


def get_conversation_context() -> str:
    """获取当前多轮上下文文本摘要。"""
    return _conversation_context


def set_active_project_id(pid: Any) -> None:
    """设置当前活动工程 ID。"""
    global _active_project_id
    _active_project_id = pid
    _sync_to_tools("_active_project_id", pid)


def get_active_project_id() -> Any:
    """获取当前活动工程 ID。"""
    return _active_project_id


# ============================================================
# Pending State & Quality Assurance
# ============================================================

def _geo_qa(geojson: Any) -> list:
    """地理质量自检（延迟导入避免循环依赖；失败静默）。"""
    try:
        from backend.services.geo_qa import qa_check
        return qa_check(geojson)
    except Exception:
        return []


def peek_pending_images() -> list:
    """只读读取当前轮图片/历史记录任务，不影响发送消费。"""
    with _state_lock:
        return [
            {"url": im.get("url") or im.get("path") or "", "label": im.get("label") or ""}
            for im in list(_pending_images)
            if isinstance(im, dict)
        ]


def _add_pending_item(url: str, file_path: str = None) -> None:
    """添加到待发送的图片/HTML 列表。"""
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
        _pending_images.append({
            "url": url,
            "type": "png" if (url or "").lower().endswith(".png") else "image",
        })


def get_pending_state() -> dict:
    """获取当前轮待发送状态（消费后清空，防止前端轮询重复叠加）。"""
    global _clear_layers_flag
    with _state_lock:
        pending_layers = []
        for layer in _pending_layers:
            if not isinstance(layer, dict):
                pending_layers.append(layer)
                continue
            result_layer = dict(layer)
            registered_name = result_layer.get("name")
            registered = (
                _registered_layers.get(registered_name)
                if isinstance(registered_name, str)
                else None
            )
            if isinstance(registered, dict):
                result_layer["registry_name"] = registered_name
                result_layer["sensitive"] = registered.get("sensitive") is True
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
            "exec_log": list(_exec_log),
        }
        _pending_layers.clear()
        _pending_images.clear()
        _pending_layer_ops.clear()
        _pending_qa_warnings.clear()
        _clear_layers_flag = False
        _pending_heatmap["latest"] = None
        return result


def reset_state(amap_key: str = "", task_id: str = "") -> None:
    """每次请求开始时调用，清空所有共享状态。"""
    global _current_amap_key, _clear_layers_flag, _search_call_count, _exec_call_count, _exec_log, _current_task_id
    global _last_user_message, _conversation_context, _current_run_id, _active_project_id
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
        _last_user_message = ""
        _conversation_context = ""
        _current_run_id = ""
        _active_project_id = None
        _sync_to_tools("_current_task_id", _current_task_id)
        _sync_to_tools("_last_user_message", "")
        _sync_to_tools("_conversation_context", "")
        _sync_to_tools("_current_run_id", "")
        _sync_to_tools("_active_project_id", None)
        _sync_to_tools("_current_amap_key", amap_key)
        _sync_to_tools("_clear_layers_flag", False)


# ============================================================
# Layer Registration & GIS Conversion Helpers
# ============================================================

def _unicode_layer_name_conflict(name: str) -> Optional[str]:
    """Return an existing visually equivalent Unicode name, if it is a different key."""
    normalized_name = unicodedata.normalize("NFC", name)
    return next(
        (
            existing
            for existing in _registered_layers
            if existing != name and unicodedata.normalize("NFC", existing) == normalized_name
        ),
        None,
    )


def _disambiguate_layer_name(base_name: str) -> str:
    """Return an unused registered or pending layer name, preserving its extension."""
    raw = base_name.strip() if isinstance(base_name, str) and base_name.strip() else "fishnet"

    def _taken(candidate: str) -> bool:
        return (
            candidate in _registered_layers
            or any(isinstance(item, dict) and item.get("name") == candidate for item in _pending_layers)
            or _unicode_layer_name_conflict(candidate) is not None
        )

    with _state_lock:
        if not _taken(raw):
            return raw
        stem, extension = os.path.splitext(raw)
        suffix = 1
        while _taken(f"{stem}_{suffix}{extension}"):
            suffix += 1
        return f"{stem}_{suffix}{extension}"


def _push_layer(name: str, geojson: dict, style: dict = None, provenance: dict = None) -> None:
    """将图层加入待发送列表（同名图层就地覆盖最新数据，防止单轮多次更新累加出重复图层）。"""
    try:
        layer = {"geojson": geojson, "name": name}
        if (_registered_layers.get(name) or {}).get("sensitive") is True:
            layer["sensitive"] = True
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
                    item
                    for item in _pending_qa_warnings
                    if not (isinstance(item, dict) and item.get("layer") == name)
                ]
            for w in _geo_qa(geojson):
                _pending_qa_warnings.append({"layer": name, "warning": w})
    except Exception:
        pass


def _unregister_layer(name: str, registration_token: str = None) -> bool:
    """从注册表中移除图层。"""
    with _state_lock:
        current = _registered_layers.get(name)
        if registration_token is not None and (
            not current or current.get("registration_token") != registration_token
        ):
            return False
        return _registered_layers.pop(name, None) is not None


def _register_layer(
    name: str,
    geojson: dict,
    group_name: str = None,
    provenance: dict = None,
    allow_unicode_alias: bool = False,
    unique_name: bool = False,
    sensitive: bool | None = None,
) -> str:
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
            raise ValueError(
                f"图层名称与现有图层「{conflicting_name}」仅 Unicode 规范形式不同，为避免显示重复请先重命名"
            )
        registration_token = uuid.uuid4().hex
        previous = _registered_layers.get(name) or {}
        is_sensitive = True
        safe_provenance = _normalize_layer_provenance(provenance)
        if (
            safe_provenance is None
            and previous.get("geojson") == fc
            and isinstance(previous.get("provenance"), dict)
        ):
            safe_provenance = _normalize_layer_provenance(previous["provenance"])
        _registered_layers[name] = {
            "name": name,
            "sensitive": bool(is_sensitive),
            "layer_id": previous.get("layer_id") or uuid.uuid4().hex,
            "registration_token": registration_token,
            "group_name": (
                group_name.strip()
                if isinstance(group_name, str)
                else previous.get("group_name", "")
            ),
            "feature_count": len(features),
            "geometry_types": list(types) if types else ["未知"],
            "geojson": fc,
            "bbox": bbox,
            **({"provenance": safe_provenance} if safe_provenance else {}),
        }
        return registration_token


def _update_registered_layer_data(name: str, geojson: dict) -> None:
    """Replace registered data through the same metadata/FID refresh path as registration."""
    _register_layer(name, geojson)


def _get_exact_registered_layer(name: str) -> tuple:
    """Mutating operations require the exact registered layer name to avoid editing a similarly named layer."""
    if isinstance(name, str) and name.strip() and name in _registered_layers:
        return name, _registered_layers[name], ""
    if not isinstance(name, str) or not name.strip():
        return "", None, "错误：图层名不能为空；请先查看已注册图层并传入完整图层名；未执行修改"
    candidates = [key for key in _registered_layers if name in key]
    if candidates:
        if len(candidates) == 1:
            return "", None, f"错误：请使用完整图层名「{candidates[0]}」，未执行修改"
        return "", None, f"错误：「{name}」匹配多个图层：{', '.join(candidates)}，请指定完整图层名；未执行修改"
    return (
        "",
        None,
        f"错误：未找到完整图层名「{name}」，当前图层：{', '.join(_registered_layers.keys()) or '无'}；未执行修改",
    )


def _register_raster_layer(
    name: str,
    raster: dict,
    source_path: str = None,
    allow_unicode_alias: bool = False,
    sensitive: bool | None = None,
) -> str:
    """Register a managed raster independently of its preview/map identifier."""
    if not isinstance(name, str) or not name.strip() or not isinstance(raster, dict):
        raise ValueError("栅格图层名称或资源无效")
    bounds = raster.get("bounds")
    if (
        not isinstance(bounds, (list, tuple))
        or len(bounds) != 4
        or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in bounds
        )
        or not (-180 <= bounds[0] <= bounds[2] <= 180 and -90 <= bounds[1] <= bounds[3] <= 90)
    ):
        raise ValueError("栅格范围必须是有效的 WGS-84 范围")
    if not source_path and any(
        raster.get(key) for key in ("source_asset", "source_filename", "source_url")
    ):
        from backend.services.project_service import _raster_original_path

        source_path = _raster_original_path(raster)
        if not source_path:
            raise ValueError("栅格原始数据资源不存在")
    token = uuid.uuid4().hex
    with _state_lock:
        conflicting_name = _unicode_layer_name_conflict(name) if not allow_unicode_alias else None
        if conflicting_name:
            raise ValueError(
                f"图层名称与现有图层「{conflicting_name}」仅 Unicode 规范形式不同，为避免显示重复请先重命名"
            )
        previous = _registered_layers.get(name) or {}
        is_sensitive = True
        _registered_layers[name] = {
            "geojson": None,
            "geometry_types": ["Raster"],
            "feature_count": 0,
            "sensitive": bool(is_sensitive),
            "layer_id": previous.get("layer_id") or uuid.uuid4().hex,
            "bbox": list(bounds),
            "raster": dict(raster),
            "raster_source_path": source_path,
            "registration_token": token,
        }
    return token


def get_registered_layers_snapshot() -> list:
    """返回当前所有注册图层的快照，包括属性样例，供 AI 识别图层内容。"""
    result = []
    with _state_lock:
        snapshot = list(_registered_layers.items())
    for name, info in snapshot:
        geojson = info.get("geojson") or {}
        result.append(
            {
                "filename": name,
                "sensitive": info.get("sensitive") is True,
                "group_name": info.get("group_name", ""),
                "geojson": geojson,
                "geometry_types": info.get("geometry_types", []),
                "feature_count": info.get("feature_count", 0),
                "bbox": info.get("bbox", []),
                "property_examples": _layer_property_examples(geojson),
                "source": "ai",
                **(
                    {"provenance": dict(info["provenance"])}
                    if isinstance(info.get("provenance"), dict)
                    else {}
                ),
                **(
                    {"raster": dict(info["raster"])}
                    if isinstance(info.get("raster"), dict)
                    else {}
                ),
            }
        )
    return result


def reset_registered_layers(layers: list = None, tolerate_invalid: bool = False):
    """重置/替换当前注册图层字典（切换会话或恢复工程时调用，实现工程级细粒度图层隔离）"""
    global _active_project_id
    skipped = []
    with _state_lock:
        _active_project_id = None
        _sync_to_tools("_active_project_id", None)
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
                        _register_raster_layer(name, l['raster'], allow_unicode_alias=True,
                                               sensitive=True)
                    elif name and geojson:
                        _register_layer(name, geojson, provenance=l.get("provenance"), allow_unicode_alias=True,
                                        sensitive=True)
                except Exception:
                    if not tolerate_invalid:
                        raise
                    skipped.append(name if isinstance(name, str) and name else "图层")
    return skipped



def geojson_to_export_gdf(geojson: dict, serialize_nested: bool = False):
    """Build a WGS-84 GeoDataFrame without pandas coercing mixed property values."""
    import geopandas as gpd
    import pandas as pd

    features = geojson["features"]
    if not features:
        return gpd.GeoDataFrame(
            {"geometry": gpd.GeoSeries([], crs="EPSG:4326")},
            crs="EPSG:4326",
        )
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    property_rows = [
        feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        for feature in features
    ]
    property_keys = list(dict.fromkeys(
        key for properties in property_rows for key in properties
        if key != "geometry"
    ))
    for key in property_keys:
        values = [properties.get(key) for properties in property_rows]
        if serialize_nested:
            values = [
                json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                if isinstance(value, (dict, list)) else value
                for value in values
            ]
        gdf[key] = pd.Series(
            values,
            index=gdf.index,
            dtype=object,
        )
    return gdf


def _layer_to_gdf(layer_name: str) -> tuple:
    """从注册表读取图层并转为 GeoDataFrame，返回 (gdf, layer_name) 或 (None, 错误信息)。"""
    info = _registered_layers.get(layer_name)
    if not info:
        matches = [n for n in _registered_layers.keys() if layer_name in n]
        if len(matches) == 1:
            info = _registered_layers[matches[0]]
            layer_name = matches[0]
        elif len(matches) > 1:
            return None, f"错误：找到多个匹配：{', '.join(matches)}，请指定完整名称"
        else:
            return None, f"错误：未找到图层「{layer_name}」，当前图层：{', '.join(_registered_layers.keys()) or '无'}"
    geojson = info.get("geojson", {})
    if not geojson or not geojson.get("features"):
        return None, f"错误：图层「{layer_name}」为空"
    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
    return gdf, layer_name


def _gdf_to_layer(gdf, name: str, style: dict = None, provenance: dict = None) -> None:
    """将 GeoDataFrame 转为 GeoJSON，推送到地图并注册。"""
    geojson_data = json.loads(gdf.to_json())
    geojson_data["name"] = name
    # Registration validates and adds stable FIDs in place. Validate a copy first so
    # invalid output never enters the pending response, while the pushed GeoJSON
    # keeps its existing pre-registration shape.
    _register_layer(name, copy.deepcopy(geojson_data), provenance=provenance)
    _push_layer(name, geojson_data, style=style, provenance=provenance)


# Initialize output directories on import
init_temp_dir()

# ============================================================
# Two-Way Module Proxy to Synchronize State with tools.py
# ============================================================

class _RuntimeModule(types.ModuleType):
    """Dynamic module proxy to synchronize rebound attributes back to tools facade if loaded."""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for mod_name in ("backend.services.tools", "tools"):
            tools_mod = sys.modules.get(mod_name)
            if tools_mod is not None:
                tools_mod.__dict__[name] = value


sys.modules[__name__].__class__ = _RuntimeModule

__all__ = [
    # State variables & locks
    "_registered_layers",
    "_pending_layers",
    "_pending_layer_ops",
    "_pending_images",
    "_pending_qa_warnings",
    "_state_lock",
    "_shared_state_lock",
    "_session_locks",
    "_session_locks_guard",
    "_temp_output_dir",
    "_workspace_dir",
    "_active_project_id",
    "_clear_layers_flag",
    "_pending_aoi_suggestions",
    "_pending_heatmap",
    "_current_amap_key",
    "_search_call_count",
    "_domain_fail",
    "_DOMAIN_FAIL_LIMIT",
    "_search_cache",
    "_search_last_hit",
    "_SEARCH_CACHE_TTL",
    "_ENGINE_MIN_INTERVAL",
    "_exec_call_count",
    "_exec_log",
    "_raster_output_scope",
    "_current_task_id",
    "_last_user_message",
    "_current_run_id",
    "_conversation_context",
    "_INLINE_HTML_PREVIEW_LIMIT",
    # Task context helpers
    "set_current_task",
    "get_current_task_id",
    "set_current_run",
    "get_current_run_id",
    "set_last_user_message",
    "get_last_user_message",
    "set_conversation_context",
    "get_conversation_context",
    "set_active_project_id",
    "get_active_project_id",
    # State inspection & reset helpers
    "init_temp_dir",
    "get_temp_output_dir",
    "peek_pending_images",
    "_add_pending_item",
    "get_pending_state",
    "reset_state",
    # Session locks
    "session_lock_wait_seconds",
    "acquire_session_lock",
    "release_session_lock",
    "acquire_shared_state_lock",
    "release_shared_state_lock",
    # Layer registration & conversion helpers
    "_geo_qa",
    "_unicode_layer_name_conflict",
    "_disambiguate_layer_name",
    "_push_layer",
    "_unregister_layer",
    "_register_layer",
    "_update_registered_layer_data",
    "_get_exact_registered_layer",
    "_register_raster_layer",
    "get_registered_layers_snapshot",
    "reset_registered_layers",
    "_layer_to_gdf",
    "_gdf_to_layer",
]
