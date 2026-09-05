"""GIS WorkTable — 跨轮 pending task（待用户确认的待办动作）状态。

解决「多轮任务状态丢失」：上一轮 AI 说“数据已获取，回复‘继续’即可加载”，
下一轮用户只发“继续”时，必须由确定性逻辑识别并执行，而不是让 LLM 自由猜测。

当前只支持一种动作，schema 保持最小（后续加动作只需扩 action 分支）：

    {
      "action": "load_layer",      # 动作名（load_layer = 把挂起的图层加载到地图）
      "created_at": "ISO 时间",
      "summary": "给用户/AI 看的一句话",
      "layers": [{"name", "geojson"?, "source"?, "file"?}],   # 待显示数据
      "params": {...},             # 预留：dataset / 其它参数
    }

状态定位：
- 只挂最小会话级状态，复用现有「会话」概念（同对话历史 cache/history/ 目录），
  每个 session 一个 sidecar 文件，随 server 内存缓存，重启后仍可从磁盘恢复。
- 纯单会话模型下足够；不引入数据库。需要跨实例时替换 _path/_load/_save 即可。
"""

import os
import json
import threading
import datetime

# 与 ai_service 的对话历史同一目录（cache/history/）
_STORE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cache", "history"
)

_lock = threading.Lock()
_memory: dict = {}          # session_id -> action dict | None（未加载过则不在此）
_active_session = "default"  # 供无 session 上下文的 @tool 使用（本工具多数无会话参数）


def _sidecar_path(session_id: str) -> str:
    return os.path.join(_STORE_DIR, f"session_{session_id}_pending.json")


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# ============================================================
# 会话切换（给无 session 参数的 LangGraph @tool 用）
# ============================================================

def set_active_session(session_id: str):
    global _active_session
    _active_session = session_id or "default"


def get_active_session() -> str:
    return _active_session


# ============================================================
# CRUD（内存 + sidecar 磁盘持久化）
# ============================================================

def _load_locked(session_id: str):
    """惰性加载 sidecar；返回 dict|None。调用方需已持锁。"""
    if session_id in _memory:
        return _memory[session_id]
    path = _sidecar_path(session_id)
    data = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
    _memory[session_id] = data
    return data


def _save_locked(session_id: str):
    os.makedirs(_STORE_DIR, exist_ok=True)
    path = _sidecar_path(session_id)
    data = _memory.get(session_id)
    try:
        if data is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_pending_action(session_id: str = "default") -> dict | None:
    """返回当前待办动作（dict）或 None。"""
    with _lock:
        return _load_locked(session_id or "default")


def set_pending_action(session_id: str, action: dict) -> dict:
    """写入待办动作；若 action 无 created_at 自动补。返回 action。"""
    sid = session_id or "default"
    if not isinstance(action, dict):
        raise ValueError("pending action 必须是 dict")
    action.setdefault("created_at", _now())
    action["action"] = action.get("action", "load_layer")
    with _lock:
        _memory[sid] = action
        _save_locked(sid)
    return action


def clear_pending_action(session_id: str = "default"):
    """清除待办动作（用户“取消”/确认执行成功后 / 清空记忆时调用）。"""
    sid = session_id or "default"
    with _lock:
        _memory[sid] = None
        _save_locked(sid)


def pending_action_snapshot() -> dict:
    """供调试/日志：所有会话的 pending 摘要（不含 geojson 本体，太长）。"""
    out = {}
    for sid in list(_memory.keys()):
        act = _memory.get(sid)
        if not act:
            continue
        out[sid] = {
            "action": act.get("action"),
            "summary": act.get("summary", "")[:60],
            "layers": [l.get("name") for l in (act.get("layers") or [])],
            "created_at": act.get("created_at"),
        }
    return out


def describe_action(action: dict) -> dict | None:
    """给前端渲染「继续/取消」或「选项按钮」用的轻量描述（不含 geojson 本体）。"""
    if not isinstance(action, dict):
        return None
    result = {
        "action": action.get("action", ""),
        "summary": action.get("summary", "")[:200],
        "layer_names": [l.get("name") for l in (action.get("layers") or []) if l.get("name")],
    }
    # choose_option 动作：返回选项列表供前端渲染按钮组
    if action.get("action") == "choose_option":
        result["options"] = action.get("options", [])
        result["choice_key"] = action.get("choice_key", "")
        result["selected"] = action.get("selected")
    return result


# ============================================================
# 短指令识别（确定性，不让 LLM 猜）
# ============================================================

# 只对“整条消息就是这个词/词组”的短指令生效；复合句一律交给正常 AI 流程。
_CONTINUE_WORDS = {
    "继续", "确认", "执行", "开始", "好的", "好", "可以", "嗯", "是", "对",
    "确定", "同意", "继续吧", "可以了", "加载", "ok", "okay", "yes", "go",
    "继续加载", "继续吧", "接着", "接着来",
}
_CANCEL_WORDS = {
    "取消", "算了", "不要", "不要了", "不用", "不用了", "停", "放弃",
    "算了不", "no", "cancel", "abort",
}
_STRIP_CHARS = " \t\r\n！!。.？?～~，,、:：;；\"'“”‘’（）()「」【】"


def normalize_short(message: str) -> str:
    s = (message or "").strip().strip(_STRIP_CHARS).lower()
    return s


def classify_short_command(message: str) -> str | None:
    """把短指令分类：'continue' / 'cancel' / None（不是短指令）。

    注意：是否真的触发 pending 由调用方再判断（有 pending 才拦截）。
    """
    s = normalize_short(message)
    if not s:
        return None
    if s in _CANCEL_WORDS and s not in _CONTINUE_WORDS:
        return "cancel"
    if s in _CONTINUE_WORDS:
        return "continue"
    return None


# ============================================================
# load_layer 动作构建 / 执行
# ============================================================

def build_load_layer_action(layer_name: str, geojson: dict = None,
                            source: str = "", file_path: str = "",
                            dataset: str = "", params: dict = None,
                            summary: str = "") -> dict:
    """构造一个 load_layer 待办动作。"""
    layer = {"name": layer_name}
    if geojson is not None:
        layer["geojson"] = geojson
    if source:
        layer["source"] = source
    if file_path:
        layer["file"] = file_path
    extra = dict(params or {})
    if dataset:
        extra["dataset"] = dataset
    action = {
        "action": "load_layer",
        "summary": summary or f"数据「{layer_name}」已就绪，等待确认后加载到地图。",
        "layers": [layer],
        "params": extra,
    }
    return action


def _registry():
    from backend.services import tools as _t
    return _t


def run_action(action: dict) -> dict | None:
    """确定性执行待办动作，返回兼容 chat result 的 dict；无法执行返回 None。

    支持动作：
    - load_layer：把 action.layers 里每个图层注册并推送到地图（register + push）。
    """
    act = (action or {}).get("action")
    if act == "load_layer":
        layers = action.get("layers") or []
        _tools = _registry()
        loaded = []
        for lyr in layers:
            name = lyr.get("name") or ""
            if not name:
                continue
            geojson = lyr.get("geojson")
            if geojson is None:
                info = _tools._registered_layers.get(name)
                geojson = (info or {}).get("geojson")
            if geojson is None:
                continue
            _tools._register_layer(name, geojson)
            layer_item = {"geojson": geojson, "name": name}
            if lyr.get("style"):
                layer_item["style"] = lyr["style"]
            _tools._push_layer(name, geojson, style=lyr.get("style"))
            loaded.append(layer_item)
        if loaded:
            names = "、".join(x["name"] for x in loaded)
            reply = f"已把图层「{names}」加载到地图。✅ 数据已就绪可直接使用，继续其它操作即可。"
        else:
            reply = ("抱歉，上一轮挂起的数据现在不可用了（可能已超时或被清理），"
                     "无法自动加载。请重新发起获取，我会直接完成。")
        return {
            "response": reply,
            "reasoning": None,
            "layers": loaded,
            "images": [],
            "heatmap": None,
            "clear_layers": False,
            "layer_ops": [],
            "pending_suggestions": None,
        }
    return None


def promote_registered_undisplayed(session_id: str, start_registered_names, pushed_layer_names) -> dict | None:
    """端末自动写入（producer #1）。

    Agent 本轮结束时，若存在「新注册但未推送到地图」的图层 → 说明数据已就绪、
    等待用户确认展示，自动记为 pending load_layer。用户回复“继续/确认”即加载。

    - start_registered_names: 本轮开始前已注册的图层名集合
    - pushed_layer_names: 本轮已推送到地图的图层名集合（已在 done 里展示的不再挂起）
    """
    sid = session_id or "default"
    with _lock:
        existing = _load_locked(sid)
    if existing:
        return None  # 已有人显式挂起（如 hold 工具），不覆盖

    _tools = _registry()
    now_names = set(_tools._registered_layers.keys())
    start_names = set(start_registered_names or ())
    pushed = set(pushed_layer_names or ())
    candidates = []
    for name in sorted(now_names - start_names):
        if name in pushed:
            continue
        info = _tools._registered_layers.get(name) or {}
        if info.get("geojson") is None:
            continue
        candidates.append({"name": name, "geojson": info["geojson"]})
    if not candidates:
        return None

    summary = (
        "已把下面图层准备好，等待你确认后加载到地图："
        + "、".join(c["name"] for c in candidates)
        + "（回复“继续/确认/执行”加载；回复“取消”放弃）"
    )
    action = {
        "action": "load_layer",
        "summary": summary,
        "layers": candidates,
        "params": {},
    }
    return set_pending_action(sid, action)
