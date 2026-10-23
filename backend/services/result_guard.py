# -*- coding: utf-8 -*-
"""GIS WorkTable — 结果真实性自检（Deterministic Result Guard）。

为什么要有这个模块
------------------
项目里反复出现过一类问题：Agent 在回复里声称「已生成 xxx.png」「图层已加载」，
但磁盘上根本没有这个文件、图片 URL 404、GeoJSON 为空。语言模型不知道自己有没有
真的产出东西，只看到工具返回的字符串就照着说，于是用户拿到的是一个"看起来成功"
的结果。

历史上用过一次 LLM 自校验，但它有两个硬伤：
1. 每轮多一次 LLM 调用，延迟和成本都翻倍；
2. 兜底逻辑太多，绝大多数情况默认通过，实际抓不到问题。

这里改成**纯确定性校验**：不看模型说什么，直接对磁盘和内存状态做事实核对。
没有额外 API 调用，没有模型判断的不确定性，也不会自己"通过"自己。

三方一致性核对（v2 升级）
-------------------------
在原"文本声称 vs 磁盘"两核对的基础上，加入任务或当前运行的产物登记表。

    LLM Claim  ↔  Artifact Registry  ↔  Filesystem

- LLM Claim：从回复正文正则提取的产物路径
- Artifact Registry：task_manager 或 storage_service 登记的产物
- Filesystem：磁盘上文件是否存在、是否非空

每个声称的产物会得到一个状态：
    VERIFIED          声称 + 已登记 + 存在 + 非空 + 路径一致
    UNREGISTERED     声称 + 未登记（registry 无记录，但磁盘有文件）
    MISSING           声称 + 磁盘不存在（无论是否登记）
    EMPTY             声称 + 存在 + 0 字节
    CLAIM_MISMATCH    声称 + registry 有其他文件但不是这个（LLM 说的不是实际生成的）
    PATH_MISMATCH     声称 + registry 有记录但登记路径与解析路径不一致

对外入口：
    verify_result(...)   -> dict              # 返回校验详情（含三方核对）
    apply_guard(...)     -> (str, dict)       # 校验并按需在回复后追加提示
    build_guard_note(...) -> str              # 根据校验详情生成提示文本
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

# 三方核对的状态常量
ST_VERIFIED = "VERIFIED"
ST_UNREGISTERED = "UNREGISTERED"
ST_MISSING = "MISSING"
ST_EMPTY = "EMPTY"
ST_CLAIM_MISMATCH = "CLAIM_MISMATCH"
ST_PATH_MISMATCH = "PATH_MISMATCH"


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
    abs_path = os.path.normpath(os.path.join(base, rest))
    # 防越界：normpath 之后必须仍落在 base 之内；否则视为不在已知输出目录，不再继续解析
    _base_norm = os.path.normpath(base)
    if not (abs_path == _base_norm or abs_path.startswith(_base_norm + os.sep)):
        return None
    if os.path.exists(abs_path):
        return abs_path
    # 兼容自动重命名前缀：检查同目录下是否存在形如 {timestamp}_{basename} 的真实文件
    parent_dir = os.path.dirname(abs_path)
    base_name = os.path.basename(abs_path)
    if os.path.isdir(parent_dir):
        try:
            for fname in os.listdir(parent_dir):
                if fname.endswith("_" + base_name):
                    candidate = os.path.join(parent_dir, fname)
                    if os.path.isfile(candidate):
                        return candidate
        except OSError:
            pass
    return abs_path


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


def verify_result(final_text: str = "", pending: dict = None, task_id: str = None, run_id: str = None, run_start_time: float = None) -> dict:
    """对一轮 Agent 的产物做确定性事实核对。

    Args:
        final_text: Agent 最终回复正文
        pending: get_pending_state() 的结果（layers / images / ...）
        task_id: 当前任务 ID。传入后启用三方核对（Claim ↔ Registry ↔ Filesystem）；
                 不传则只做原"文本声称 vs 磁盘"两核对（向后兼容）。
        run_id: 当前执行轮次 ID。与 SQLite 事实台账核对。
        run_start_time: 本轮执行启动时间戳，用于自愈判定是否为本轮新产物。

    Returns:
        {
          "ok": bool,                 # 全部核对通过
          "checked_paths": [...],     # 正文里抽到并检查过的路径
          "missing_paths": [...],     # 正文声称但缺失或为空的路径
          "broken_images": [...],     # 待推送图片里文件缺失的 url
          "empty_layers": [...],      # GeoJSON 缺失的图层名
          "issues": [...],            # 面向用户的一句话问题描述
          "artifact_checks": [...],    # 三方核对：每个声称产物的状态明细（v2）
          "registry_count": int,      # registry 中登记的产物总数（v2）
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
        "artifact_checks": [],
        "registry_count": 0,
    }

    # 1) 正文声称的产物文件路径
    for rel in extract_output_paths(final_text):
        result["checked_paths"].append(rel)
        abs_path = resolve_artifact_path(rel)
        if not abs_path:
            result["missing_paths"].append(rel)
            result["issues"].append(
                f"回复中提到的产物 `{rel}` 路径无效或越出允许的输出目录，无法核验"
            )
            continue
        try:
            file_exists = os.path.isfile(abs_path)
            non_empty = file_exists and os.path.getsize(abs_path) > 0
        except OSError:
            file_exists = False
            non_empty = False
        if not file_exists:
            result["missing_paths"].append(rel)
            result["issues"].append(f"回复中提到的产物 `{rel}` 在磁盘上不存在（未真实生成）")
        elif not non_empty:
            # 保持 missing_paths 对零字节产物的既有兼容语义，但准确描述实际状态。
            result["missing_paths"].append(rel)
            result["issues"].append(f"回复中提到的产物 `{rel}` 文件存在但为 0 字节，等于未生成")

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

    # 4) 三方核对：Claim ↔ Registry ↔ Filesystem（v2）
    #    传入 task_id 或 run_id 时启用；否则保持原两核对行为（向后兼容）
    if task_id or run_id:
        checks, reg_count = _three_way_check(final_text, task_id=task_id, run_id=run_id, run_start_time=run_start_time)
        result["artifact_checks"] = checks
        result["registry_count"] = reg_count
        # 把非 VERIFIED 的三方问题补进 issues
        for c in checks:
            st = c.get("status")
            if st == ST_VERIFIED:
                continue
            rel = c.get("path", "")
            if st == ST_MISSING:
                # 已在第 1 步报过 missing_paths，不重复
                if rel not in result["missing_paths"]:
                    result["issues"].append(f"回复中提到的产物 `{rel}` 磁盘上不存在（registry 也无有效记录）")
            elif st == ST_EMPTY:
                empty_issue = f"回复中提到的产物 `{rel}` 文件存在但为 0 字节，等于未生成"
                if empty_issue not in result["issues"]:
                    result["issues"].append(empty_issue)
            elif st == ST_UNREGISTERED:
                result["issues"].append(f"回复声称的产物 `{rel}` 存在于磁盘，但未登记在本次执行记录中（可能为历史残留文件或未受控输出）")
            elif st == ST_CLAIM_MISMATCH:
                result["issues"].append(f"回复声称的产物 `{rel}` 与 registry 实际登记的产物不一致（LLM 可能张冠李戴）")
            elif st == ST_PATH_MISMATCH:
                result["issues"].append(f"产物 `{rel}` 在 registry 的登记路径与实际解析路径不一致")

    result["ok"] = not result["issues"]
    return result


def _three_way_check(final_text: str, task_id: str = None, run_id: str = None, run_start_time: float = None) -> tuple:
    """三方一致性核对：LLM Claim ↔ Artifact Registry ↔ Filesystem。

    返回 (checks, registry_count)：
      checks: list[dict]，每个声称产物的状态明细
      registry_count: registry 中登记的产物总数
    """
    registry = []
    # run_id 用于本轮核验时，不能拿任务历史里的旧产物证明本轮成功。
    if run_id:
        try:
            from backend.services import storage_service
            for art in storage_service.get_run_artifacts(run_id) or []:
                registry.append({
                    "artifact_id": art.get("artifact_id"),
                    "run_id": art.get("run_id", run_id),
                    "task_id": task_id,
                    "filename": art.get("filename"),
                    "path": art.get("rel_path"),
                    "status": "success" if art.get("exists") else "pending",
                })
        except Exception:
            pass
    elif task_id:
        try:
            from backend.services import task_manager
            registry.extend(task_manager.get_artifacts(task_id) or [])
        except Exception:
            pass

    claimed_paths = extract_output_paths(final_text)
    checks = []

    for rel in claimed_paths:
        resolved = resolve_artifact_path(rel)
        claim_basename = os.path.basename(resolved) if resolved else os.path.basename(rel)

        # Filesystem
        exists = False
        non_empty = False
        if resolved:
            try:
                exists = os.path.isfile(resolved)
                if exists:
                    non_empty = os.path.getsize(resolved) > 0
            except OSError:
                exists = False

        # Registry：按 basename 匹配（registry 登记的 filename 与声称的 basename）
        matched = None
        matched_score = -1
        registry_path_matches = False
        for art in registry:
            art_path = art.get("path") or art.get("rel_path") or ""
            art_basename = os.path.basename(art_path) if art_path else (art.get("filename") or "")
            if art_basename != claim_basename:
                continue
            # 同 basename 可能对应不同目录的历史产物。优先选路径一致项，
            # 再回退到没有可比路径的记录，最后才保留路径不一致项。
            if resolved and art_path:
                norm_art = os.path.normpath(art_path).replace("\\", "/")
                norm_res = os.path.normpath(resolved).replace("\\", "/")
                path_matches = (
                    norm_art == norm_res
                    or norm_res.endswith("/" + norm_art.lstrip("/"))
                    or norm_art.endswith("/" + norm_res.lstrip("/"))
                )
                score = 2 if path_matches else 0
            else:
                path_matches = True
                score = 1
            if score > matched_score:
                matched = art
                matched_score = score
                registry_path_matches = path_matches
            if matched_score == 2:
                break

        registered = matched is not None
        artifact_id = matched.get("artifact_id") if matched else None
        art_task_id = matched.get("task_id") if matched else None
        belongs_to_current_task = (art_task_id == task_id) if matched else (matched is not None)

        # 自愈与补录（收紧版）：
        #   只有当「storage_service.get_run_artifacts(run_id) 明确返回了与 claim_basename 同名记录」时才允许把
        #   历史磁盘文件当作本轮产物补录。仅凭 mtime 不能防误判复制/touch 会更新 mtime，导致旧文件冒认为新产物。
        if not registered and exists and non_empty and run_start_time and resolved:
            # 自愈条件（分层防误判）：
            #   a) 有 run_id：必须 storage_service 的 run registry 里确实登记过同名 artifact 才允许自愈
            #      （防止历史文件被 touch/复制后仅凭 mtime 冒认本轮产物）。
            #   b) 无 run_id（兼容 verify_result 直调场景）：退回 mtime-only 判定，
            #      run_start_time 窗口本身已限定「本轮开始时间之后修改过的文件」，误判面足够小。
            if run_id:
                run_artifact_matched = any(
                    os.path.basename(a.get("path") or a.get("rel_path") or a.get("filename") or "") == claim_basename
                    for a in registry
                    if a.get("artifact_id") and a.get("run_id") == run_id
                )
            else:
                run_artifact_matched = True
            if run_artifact_matched:
                try:
                    mtime = os.path.getmtime(resolved)
                except OSError:
                    mtime = None
                # mtime 允许向前后退 5 秒窗口容忍时钟/写文件延迟
                if mtime is not None and mtime >= (run_start_time - 5.0):
                    registered = True
                    registry_path_matches = True
                    belongs_to_current_task = True
                    if task_id:
                        try:
                            from backend.services import task_manager
                            art = task_manager.register_artifact(task_id, claim_basename, resolved, artifact_type="image")
                            if art:
                                artifact_id = art.get("artifact_id")
                        except Exception:
                            pass
                    if run_id:
                        try:
                            import uuid as _uuid
                            from backend.services import storage_service
                            art_id = artifact_id or _uuid.uuid4().hex[:10]
                            storage_service.register_run_artifact(run_id, art_id, claim_basename, resolved)
                        except Exception:
                            pass

        # 状态机
        if not registered:
            if not exists:
                status = ST_MISSING
            elif registry:
                # 当前任务/运行登记了其他产物，正文声称的文件却未登记，属于 claim 不一致。
                status = ST_CLAIM_MISMATCH
            else:
                # 磁盘有文件但 registry 无记录
                status = ST_UNREGISTERED
        else:
            # registered
            if not exists:
                status = ST_MISSING
            elif not non_empty:
                status = ST_EMPTY
            elif not registry_path_matches:
                status = ST_PATH_MISMATCH
            else:
                status = ST_VERIFIED

        checks.append({
            "path": rel,
            "claimed": True,
            "registered": registered,
            "artifact_id": artifact_id,
            "exists": exists,
            "non_empty": non_empty,
            "registry_path_matches": registry_path_matches,
            "belongs_to_current_task": belongs_to_current_task,
            "status": status,
        })

    return checks, len(registry)


def apply_guard(final_text: str, pending: dict = None, task_id: str = None, run_id: str = None, run_start_time: float = None, append_note: bool = False):
    """校验一轮结果。

    返回 `(最终文本, 校验详情)`。
    默认 append_note=False，仅进行内部校验与指标记录，不向用户端追加「结果真实性自检」免责说明，
    避免暴露内部断言信息与误导用户。需要时可传 append_note=True。
    task_id 或 run_id 传入时启用三方核对（Claim ↔ Registry ↔ Filesystem）。
    """
    final_text = final_text or ""
    check = verify_result(final_text, pending, task_id=task_id, run_id=run_id, run_start_time=run_start_time)
    if append_note:
        note = build_guard_note(check)
        if note:
            final_text = final_text + note
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
