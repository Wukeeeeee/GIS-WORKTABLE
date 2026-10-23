"""
GIS WorkTable — 双轨日志模块

临时日志（temp_<会话哈希>.jsonl）：每次会话的详细记录，新建会话时归档并清空
永久日志（permanent.jsonl）：只记录有问题的结果，长期保存
"""
import datetime
import hashlib
import json
import os
import tempfile
import threading
import uuid
from collections import deque

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
_LOG_LOCK = threading.RLock()

def _ensure_dirs():
    os.makedirs(_LOG_DIR, exist_ok=True)

def _temp_path(session_id: str = "default") -> str:
    sid_hash = hashlib.sha256(str(session_id or "default").encode("utf-8")).hexdigest()
    return os.path.join(_LOG_DIR, f"temp_{sid_hash}.jsonl")

def _perm_path() -> str:
    return os.path.join(_LOG_DIR, "permanent.jsonl")


def _iter_jsonl(path: str, *, strict: bool = False):
    try:
        # 按行解码，单行损坏时仍可保留后续有效记录。
        with open(path, "rb") as f:
            for raw_line in f:
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if isinstance(record, dict):
                        yield record
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return
    except OSError:
        if strict:
            raise


def _read_jsonl(path: str, *, strict: bool = False) -> list:
    return list(_iter_jsonl(path, strict=strict))


# ===== 临时日志：详细记录每一步 =====

def log_turn(session_id: str, user_message: str, ai_reply: str,
             layers_snapshot: dict = None, geojson_data: dict = None,
             saved_files: list = None):
    """记录一次问答到临时日志"""
    record = {
        "record_id": uuid.uuid4().hex,
        "session_id": str(session_id or "default"),
        "time": datetime.datetime.now().astimezone().isoformat(),
        "user": user_message[:2000],
        "ai": ai_reply[:3000],
    }
    if layers_snapshot:
        record["layers"] = {}
        for name, info in layers_snapshot.items():
            layer_info = {
                "feature_count": info.get("feature_count", 0),
                "geometry_types": info.get("geometry_types", []),
            }
            # 提取图层属性预览（第一个要素的属性样例 + 所有属性字段名）
            geojson = info.get("geojson")
            if geojson:
                features = geojson.get("features", [])
                if features:
                    props = features[0].get("properties", {}) or {}
                    layer_info["properties_sample"] = dict(list(props.items())[:8])
                    # 所有要素共有的属性字段
                    all_keys = set()
                    for f in features[:50]:
                        p = f.get("properties", {}) or {}
                        all_keys.update(p.keys())
                    if all_keys:
                        layer_info["property_fields"] = list(all_keys)[:15]
            record["layers"][name] = layer_info
    if geojson_data:
        record["generated_geojson"] = geojson_data
    if saved_files:
        record["saved_files"] = saved_files

    path = _temp_path(session_id)
    try:
        with _LOG_LOCK:
            _ensure_dirs()
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def clear_temp_log(session_id: str = "default"):
    """新建会话时清空临时日志"""
    try:
        with _LOG_LOCK:
            path = _temp_path(session_id)
            if os.path.exists(path):
                os.remove(path)
        return True
    except Exception:
        return False


def get_temp_log(session_id: str = "default") -> list:
    """读取当前会话的临时日志"""
    path = _temp_path(session_id)
    with _LOG_LOCK:
        return _read_jsonl(path)


# ===== 永久日志：只记有问题的结果 =====

def _is_problematic(record: dict) -> bool:
    ai = str(record.get("ai") or "")
    user = str(record.get("user") or "")

    if "失败" in ai or "错误" in ai or "无法获取" in ai or "提取失败" in ai:
        return True
    if "加载到地图" in ai or "已加载" in ai or "显示在地图" in ai:
        layers = record.get("layers", {})
        geojson = record.get("generated_geojson")
        if not layers and not geojson:
            return True
        if layers:
            if not isinstance(layers, dict):
                return True
            for name, info in layers.items():
                if not isinstance(info, dict) or info.get("feature_count", 0) == 0:
                    return True
    if user and ("没看到" in user or "没有显示" in user or "看不到" in user):
        return True
    if "AOI" in ai and ("失败" in ai or "未能" in ai):
        return True
    return False


def _write_issues_atomic(issues: list):
    """一次提交整批问题记录，失败时保留旧永久日志。调用方持有日志锁。"""
    _ensure_dirs()
    fd, temporary = tempfile.mkstemp(prefix=".log-archive-", suffix=".tmp", dir=_LOG_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for record in _iter_jsonl(_perm_path(), strict=True):
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            for issue in issues:
                f.write(json.dumps(issue, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, _perm_path())
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def archive_temp_to_perm(session_id: str = "default"):
    with _LOG_LOCK:
        try:
            records = _read_jsonl(_temp_path(session_id), strict=True)
            archived = {record.get("record_id") for record in _iter_jsonl(_perm_path(), strict=True)}
            issues = []
            for index, record in enumerate(records):
                if not _is_problematic(record):
                    continue
                # Legacy temporary records have no UUID; a stable session/position/content key
                # allows retry after a failed temporary-file deletion without duplicating them.
                record_id = record.get("record_id") or hashlib.sha256(json.dumps(
                    [str(session_id or "default"), index, record], sort_keys=True, ensure_ascii=False,
                ).encode("utf-8")).hexdigest()
                if record_id in archived:
                    continue
                issues.append({
                    "record_id": record_id, "session_id": str(session_id or "default"),
                    "time": record.get("time", ""),
                    "user": str(record.get("user") or "")[:200],
                    "ai": str(record.get("ai") or "")[:500],
                    "layers": record.get("layers", {}),
                    "geojson": record.get("generated_geojson"),
                    "saved_files": record.get("saved_files"),
                })
                archived.add(record_id)
            if issues:
                _write_issues_atomic(issues)
            return clear_temp_log(session_id)
        except (OSError, TypeError, ValueError):
            return False


def get_perm_log(n: int | None = 50) -> list:
    """读取最近 n 条问题记录，n=None 用于完整导出。"""
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n <= 0):
        return []
    with _LOG_LOCK:
        records = _iter_jsonl(_perm_path())
        return list(records if n is None else deque(records, maxlen=n))[::-1]


def get_log_stats(session_id: str = "default") -> dict:
    with _LOG_LOCK:
        return {
            "temp_count": sum(1 for _ in _iter_jsonl(_temp_path(session_id))),
            "perm_count": sum(1 for _ in _iter_jsonl(_perm_path())),
            "legacy_temp_count": sum(1 for _ in _iter_jsonl(os.path.join(_LOG_DIR, "temp.jsonl"))),
            "log_dir": os.path.abspath(_LOG_DIR),
        }


def get_log_snapshot(session_id: str = "default") -> dict:
    """读取同一归档时点的完整日志，避免导出时混入两个时点的数据。"""
    with _LOG_LOCK:
        return {
            "temp": get_temp_log(session_id), "permanent": get_perm_log(None),
            "legacy_temp": _read_jsonl(os.path.join(_LOG_DIR, "temp.jsonl")),
        }
