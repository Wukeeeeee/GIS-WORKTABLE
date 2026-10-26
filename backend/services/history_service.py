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
_PER_TASK_KEEP = 20  # 截断时每任务至少保留的条数（防旧任务记录被整段清零）
_CUSTOM_PATH = [None]
_LOAD_ERROR = [None]
_PERSIST_ERROR = [None]


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
        _LOAD_ERROR[0] = None
        _PERSIST_ERROR[0] = None


def _load():
    if _LOADED[0]:
        return
    try:
        with open(_history_path(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("历史文件根节点必须是对象")
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("历史 entries 必须是列表")
        _ENTRIES.extend(entry for entry in entries if isinstance(entry, dict))
        next_index = data.get("next_index", 1)
        if isinstance(next_index, bool) or not isinstance(next_index, int) or next_index < 1:
            next_index = 1
        max_index = max(
            (entry.get("index", 0) for entry in _ENTRIES
             if isinstance(entry.get("index", 0), int) and not isinstance(entry.get("index", 0), bool)),
            default=0,
        )
        _NEXT_INDEX[0] = max(next_index, max_index + 1)
        _trim_entries()
    except FileNotFoundError:
        # A new history store is a normal first-run condition.
        pass
    except Exception:
        # Do not treat unreadable history as empty: the next record must not
        # overwrite a file that may still contain recoverable user history.
        _LOAD_ERROR[0] = "处理历史文件无法读取；为保留原文件，已暂停写入。"
    _LOADED[0] = True


def _persist(allow_unreadable_replace: bool = False) -> bool:
    if _LOAD_ERROR[0] and not allow_unreadable_replace:
        _PERSIST_ERROR[0] = _LOAD_ERROR[0]
        return False
    tmp_path = None
    try:
        path = _history_path()
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                {"next_index": _NEXT_INDEX[0], "entries": _ENTRIES},
                f, ensure_ascii=False, indent=2,
            )
        os.replace(tmp_path, path)
        _LOAD_ERROR[0] = None
        _PERSIST_ERROR[0] = None
        return True
    except Exception:
        _PERSIST_ERROR[0] = "处理历史未能写入磁盘；当前记录仅保留在本次运行内存中。"
        if allow_unreadable_replace and _LOAD_ERROR[0]:
            _PERSIST_ERROR[0] = "清空历史未能写入磁盘；原历史文件仍保留。"
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def get_storage_warning():
    """返回历史文件读写警告；正常时为 None。"""
    with _LOCK:
        _load()
        return _LOAD_ERROR[0] or _PERSIST_ERROR[0]


def _trim_entries():
    """总量最多 200 条，优先保留每任务最近 20 条，再按全局新近度补位。"""
    if len(_ENTRIES) <= _MAX_ENTRIES:
        return
    kept_per_task = {}
    selected = set()
    for index in range(len(_ENTRIES) - 1, -1, -1):
        entry = _ENTRIES[index]
        task_id = str(entry.get("task_id") or "_none_")
        kept = kept_per_task.get(task_id, 0)
        if kept >= _PER_TASK_KEEP:
            continue
        selected.add(index)
        kept_per_task[task_id] = kept + 1
        if len(selected) >= _MAX_ENTRIES:
            break
    for index in range(len(_ENTRIES) - 1, -1, -1):
        if len(selected) >= _MAX_ENTRIES:
            break
        selected.add(index)
    _ENTRIES[:] = [_ENTRIES[index] for index in sorted(selected)]


def record(tool_name: str, args: dict, ok: bool, layer_ids=None,
           task_id: str = "", error: str = "", duration_ms: int = 0,
           rerun_of: int = 0, images=None, file_artifacts=None) -> int:
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
            "images": list(images or []),
            "file_artifacts": list(file_artifacts or []),
        }
        _NEXT_INDEX[0] += 1
        _ENTRIES.append(entry)
        _trim_entries()
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


def get_entries_by_task(task_id: str, only_ok: bool = True) -> list:
    """按任务 ID 获取所有执行记录（按时间正序排列）"""
    with _LOCK:
        _load()
        res = []
        for e in _ENTRIES:
            if e.get("task_id") == task_id:
                if only_ok and not e.get("ok"):
                    continue
                res.append(dict(e))
        return res


def clear():
    """清空全部历史（含落盘文件）"""
    with _LOCK:
        _load()
        previous_entries = list(_ENTRIES)
        previous_next_index = _NEXT_INDEX[0]
        _ENTRIES.clear()
        _NEXT_INDEX[0] = 1
        _LOADED[0] = True
        if not _persist(allow_unreadable_replace=True):
            _ENTRIES[:] = previous_entries
            _NEXT_INDEX[0] = previous_next_index
            return False
        return True
