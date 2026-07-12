"""
GIS WorkTable — 双轨日志模块

临时日志（temple.jsonl）：每次会话的详细记录，新建会话时自动清空
永久日志（prominent.jsonl）：只记录有问题的结果，长期保存
"""
import json, os, datetime

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")

def _ensure_dirs():
    os.makedirs(_LOG_DIR, exist_ok=True)

def _temp_path(session_id: str = "default") -> str:
    _ensure_dirs()
    return os.path.join(_LOG_DIR, "temp.jsonl")

def _perm_path() -> str:
    _ensure_dirs()
    return os.path.join(_LOG_DIR, "permanent.jsonl")


# ===== 临时日志：详细记录每一步 =====

def log_turn(session_id: str, user_message: str, ai_reply: str,
             layers_snapshot: dict = None, geojson_data: dict = None,
             saved_files: list = None):
    """记录一次问答到临时日志"""
    record = {
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
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def clear_temp_log(session_id: str = "default"):
    """新建会话时清空临时日志"""
    path = _temp_path(session_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def get_temp_log(session_id: str = "default") -> list:
    """读取当前会话的临时日志"""
    path = _temp_path(session_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []


# ===== 永久日志：只记有问题的结果 =====

def _is_problematic(record: dict) -> bool:
    ai = record.get("ai", "")
    user = record.get("user", "")

    if "失败" in ai or "错误" in ai or "无法获取" in ai or "提取失败" in ai:
        return True
    if "加载到地图" in ai or "已加载" in ai or "显示在地图" in ai:
        layers = record.get("layers", {})
        geojson = record.get("generated_geojson")
        if not layers and not geojson:
            return True
        if layers:
            for name, info in layers.items():
                if info.get("feature_count", 0) == 0:
                    return True
    if user and ("没看到" in user or "没有显示" in user or "看不到" in user):
        return True
    if "AOI" in ai and ("失败" in ai or "未能" in ai):
        return True
    return False


def log_issue(record: dict):
    try:
        path = _perm_path()
        issue = {
            "time": record.get("time", ""),
            "user": record.get("user", "")[:200],
            "ai": record.get("ai", "")[:500],
            "layers": record.get("layers", {}),
            "geojson": record.get("generated_geojson"),
            "saved_files": record.get("saved_files"),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(issue, ensure_ascii=False) + "\n")
    except Exception:
        pass


def archive_temp_to_perm(session_id: str = "default"):
    records = get_temp_log(session_id)
    for record in records:
        if _is_problematic(record):
            log_issue(record)
    clear_temp_log(session_id)


def get_perm_log(n: int = 50) -> list:
    path = _perm_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        records = [json.loads(line) for line in lines if line.strip()]
        return records[-n:][::-1]
    except Exception:
        return []
