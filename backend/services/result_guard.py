"""GIS WorkTable — 结果真实性自检（Deterministic Result Guard）。

为什么要有这个模块
------------------
项目里反复出现过一类问题：Agent 在回复里声称「已生成 xxx.png」「图层已加载」，
但磁盘上根本没有这个文件、图片 URL 404、GeoJSON 为空。语言模型不知道自己有没有
真的产出东西，只看到工具返回的字符串就照着说，于是用户拿到的是一个"看起来成功"
的结果。

历史上用过一次 LLM 自校验（graph.py 里的 `_run_verifier`），但它有两个硬伤：
1. 每轮多一次 LLM 调用，延迟和成本都翻倍；
2. 兜底逻辑太多，绝大多数情况默认通过，实际抓不到问题。

这里改成**纯确定性校验**：不看模型说什么，直接对磁盘和内存状态做事实核对。
没有额外 API 调用，没有模型判断的不确定性，也不会自己"通过"自己。

校验内容
--------
1. 回复正文里提到的产物文件路径是否真实存在（支持 output/cache/uploads/reports/data 目录）
2. 待推送给前端的图片 URL 对应的文件是否真实存在
3. 待推送图层的 GeoJSON 是否缺失

只报告「确定出问题」的项；做不到确定结论的一律不报，避免噪音式误报。

对外只有两个入口：
    verify_result(...)  -> dict   # 返回校验详情
    build_guard_note(...) -> str  # 返回要追加到回复末尾的提示文本（无问题时为空串）
"""

import os
import re
import tempfile

# 本文件位于 backend/services/，项目根 = 上两级
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 工具实际会写入并被前端引用的目录。
# 「key -> 绝对路径」，key 同时用于匹配回复正文里的路径前缀。
_OUTPUT_DIRS = {
    "output": os.path.join(tempfile.gettempdir(), "gis_worktable_output"),
    "cache": os.path.join(_PROJECT_ROOT, "cache"),
    "uploads": os.path.join(_PROJECT_ROOT, "uploads"),
    "reports": os.path.join(_PROJECT_ROOT, "reports"),
    "data": os.path.join(_PROJECT_ROOT, "data"),
    "downloads": os.path.join(_PROJECT_ROOT, "data"),
}

# 只认这些后缀，避免把聊天正文里的普通单词当路径
_RECOGNIZED_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".html", ".htm",
    ".geojson", ".json", ".csv", ".zip", ".shp", ".gpkg", ".kml", ".kmz",
    ".gpx", ".dxf", ".tif", ".tiff", ".md", ".txt", ".pdf", ".xlsx", ".xls",
)

# 匹配正文里的路径：output/xxx.png、/cache/charts/xxx.png、uploads/a_b.shp
# 允许目录层级和中文文件名，不允许空格（路径含空格几乎必是被截断的自然语言）
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./\\])/?(?P<dir>" + "|".join(_OUTPUT_DIRS.keys()) + r")/"
    r"(?P<rest>[A-Za-z0-9_\-\u4e00-\u9fa5()（）.][A-Za-z0-9_\-\u4e00-\u9fa5()（）./]*?)"
    r"(?P<ext>" + "|".join(re.escape(e) for e in _RECOGNIZED_EXTS) + r")"
    r"(?![A-Za-z0-9_])"
)

_MAX_ISSUES = 5


def resolve_artifact_path(path: str):
    """把工具/回复里写的路径解析成本机绝对路径。

    支持 `output/x.png`、`/output/x.png`、`cache/charts/x.png` 三种写法。
    返回绝对路径；不在已知输出目录内则返回 None。
    """
    raw = (path or "").strip()
    if not raw or "://" in raw:
        return None
    normalized = raw.replace("\\", "/").lstrip("/")
    first = normalized.split("/", 1)[0]
    base = _OUTPUT_DIRS.get(first)
    if not base:
        return None
    rest = normalized[len(first):].lstrip("/")
    if not rest:
        return None
    return os.path.normpath(os.path.join(base, rest))


def extract_output_paths(text: str) -> list:
    """从自然文本里抽出所有「看起来是本系统产物」的路径（去重保序）。"""
    if not text:
        return []
    found = []
    for m in _PATH_RE.finditer(text):
        item = f"{m.group('dir')}/{m.group('rest')}{m.group('ext')}"
        if item not in found:
            found.append(item)
    return found


def verify_result(final_text: str = "", pending: dict = None) -> dict:
    """对一轮 Agent 的产物做确定性事实核对。

    Args:
        final_text: Agent 最终回复正文
        pending: get_pending_state() 的结果（layers / images / ...）

    Returns:
        {
          "ok": bool,                 # 全部核对通过
          "checked_paths": [...],     # 正文里抽到并检查过的路径
          "missing_paths": [...],     # 正文声称但磁盘上不存在的路径
          "broken_images": [...],     # 待推送图片里文件缺失的 url
          "empty_layers": [...],      # GeoJSON 缺失的图层名
          "issues": [...],            # 面向用户的一句话问题描述
        }
    """
    pending = pending or {}
    result = {
        "ok": True,
        "checked_paths": [],
        "missing_paths": [],
        "broken_images": [],
        "empty_layers": [],
        "issues": [],
    }

    # 1) 正文声称的产物文件路径
    for rel in extract_output_paths(final_text):
        result["checked_paths"].append(rel)
        abs_path = resolve_artifact_path(rel)
        if not abs_path:
            continue
        try:
            exists = os.path.isfile(abs_path) and os.path.getsize(abs_path) > 0
        except OSError:
            exists = False
        if not exists:
            result["missing_paths"].append(rel)
            result["issues"].append(f"回复中提到的产物 `{rel}` 在磁盘上不存在（未真实生成）")

    # 2) 待推送图片：URL 必须对应真实文件（HTML 内联内容除外）
    for item in pending.get("images") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        if not url or "://" in url or not url.startswith("/"):
            continue
        # html 类型带内联 content 时文件已被读取并删除，不算缺失
        if item.get("type") == "html" and item.get("content"):
            continue
        abs_path = resolve_artifact_path(url)
        if not abs_path:
            continue
        try:
            exists = os.path.isfile(abs_path) and os.path.getsize(abs_path) > 0
        except OSError:
            exists = False
        if not exists:
            result["broken_images"].append(url)
            result["issues"].append(f"待推送的图片 `{url}` 对应文件不存在，前端会显示裂图")

    # 3) 待推送图层必须有真实 GeoJSON
    for layer in pending.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        if not layer.get("geojson"):
            name = layer.get("name") or "未命名图层"
            result["empty_layers"].append(name)
            result["issues"].append(f"图层「{name}」没有矢量数据，无法在地图上显示")

    result["ok"] = not result["issues"]
    return result


def apply_guard(final_text: str, pending: dict = None):
    """校验一轮结果，并把校验提示追加到回复末尾。

    返回 `(最终文本, 校验详情)`。通过校验时文本原样返回。
    graph.py 的流式与非流式入口统一走这里，保证两条路径行为一致。
    """
    check = verify_result(final_text, pending)
    note = build_guard_note(check)
    if note:
        final_text = (final_text or "") + note
    return final_text, check


def build_guard_note(check: dict) -> str:
    """校验未通过时，生成追加到 Agent 回复末尾的提示文本。无问题时返回空串。

    目的：不让「未通过校验」悄悄穿过系统。用户会看到明确的失败说明，
    而不是一个看起来成功的回复。
    """
    if not check or check.get("ok"):
        return ""
    issues = check.get("issues") or []
    shown = issues[:_MAX_ISSUES]
    lines = "\n".join(f"- {x}" for x in shown)
    # 超过展示上限时补一句，避免用户以为只错了这么点
    tail = ""
    if len(issues) > len(shown):
        tail = f"\n- （另有 {len(issues) - len(shown)} 项同类问题未列出）"
    return (
        "\n\n---\n"
        "【结果真实性自检】以下内容未通过磁盘/数据校验，请勿认为这些结果已经生成：\n"
        f"{lines}{tail}"
    )
