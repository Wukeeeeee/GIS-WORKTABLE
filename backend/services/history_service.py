# -*- coding: utf-8 -*-
"""处理历史（Tool Execution History）

统一记录每次 Agent 工具执行的：工具名、参数、时间、产物图层 id、成败、耗时。
持久化到 cache/tool_history.json（跨进程/重启可查），供：
- @tool list_history / rerun_history（tools.py，Agent 聊天入口）
- GET/POST /api/history（main.py，前端「历史」面板入口）

记录由 tools.py 在 tools 列表出口处统一包装完成，各工具本体零侵入。
"""
import json
import os
import threading
import datetime

_LOCK = threading.Lock()
_ENTRIES = []                # [{index, tool, args, time, ok, layer_ids, task_id, error, duration_ms}]
_NEXT_INDEX = [1]
_LOADED = [False]
_MAX_ENTRIES = 200
_CUSTOM_PATH = [None]


def _history_path() -> str:
    """历史持久化文件路径：默认 <repo>/cache/tool_history.json，测试可覆盖"""
    if _CUSTOM_PATH[0]:
        return _CUSTOM_PATH[0]
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cache_dir = os.path.join(root, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "tool_history.json")


def set_history_file(path: str):
    """切换历史文件（测试隔离用）。切换后内存缓存清空，下次读取重新加载。"""
    with _LOCK:
        _CUSTOM_PATH[0] = path
        _ENTRIES.clear()
        _NEXT_INDEX[0] = 1
        _LOADED[0] = False


def _load():
    if _LOADED[0]:
        return
    try:
        with open(_history_path(), encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        _ENTRIES.extend(entries)
        _NEXT_INDEX[0] = max(data.get("next_index", 1), len(entries) + 1)
    except Exception:
        pass
    _LOADED[0] = True


def _persist():
    try:
        with open(_history_path(), "w", encoding="utf-8") as f:
            json.dump(
                {"next_index": _NEXT_INDEX[0], "entries": _ENTRIES[-_MAX_ENTRIES:]},
                f, ensure_ascii=False, indent=2,
            )
    except Exception:
        pass


def record(tool_name: str, args: dict, ok: bool, layer_ids=None,
           task_id: str = "", error: str = "", duration_ms: int = 0,
           rerun_of: int = 0) -> int:
    """记录一次工具执行，返回分配的历史编号 index。"""
    with _LOCK:
        _load()
        entry = {
            "index": _NEXT_INDEX[0],
            "tool": tool_name,
            "args": _safe_args(args),
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": bool(ok),
            "layer_ids": list(layer_ids or []),
            "task_id": task_id or "",
            "error": (error or "")[:300],
            "duration_ms": int(duration_ms or 0),
            "rerun_of": int(rerun_of or 0),
        }
        _NEXT_INDEX[0] += 1
        _ENTRIES.append(entry)
        if len(_ENTRIES) > _MAX_ENTRIES * 2:
            del _ENTRIES[:_MAX_ENTRIES]
        _persist()
        return entry["index"]


def _safe_args(args) -> dict:
    """参数要求可 JSON 序列化（落盘 + 前端复制 JSON）。不可序列化的值转字符串。"""
    safe = {}
    for k, v in (args or {}).items():
        try:
            json.dumps(v, ensure_ascii=False)
            safe[k] = v
        except Exception:
            safe[k] = str(v)[:200]
    return safe


def list_entries(limit: int = 20) -> list:
    """按时间倒序返回最近 limit 条记录（最新在前）"""
    with _LOCK:
        _load()
        if limit and limit > 0:
            return list(reversed(_ENTRIES))[:limit]
        return list(reversed(_ENTRIES))


def get_entry(index: int):
    """按编号取单条记录；不存在返回 None"""
    with _LOCK:
        _load()
        for e in _ENTRIES:
            if e.get("index") == index:
                return dict(e)
        return None


def clear():
    """清空全部历史（含落盘文件）"""
    with _LOCK:
        _ENTRIES.clear()
        _NEXT_INDEX[0] = 1
        _LOADED[0] = True
        _persist()
