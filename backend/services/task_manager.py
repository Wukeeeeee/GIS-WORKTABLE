"""GIS WorkTable — Task Working Memory + Python Source Code Cache + Artifact Registry

解决核心问题：Agent 没有持久化工作上下文，第二轮不知道第一轮生成了什么代码。

架构：
- TaskManager：任务生命周期（create/update/archive/restore/delete）
- CodeCache：Python 源代码版本化保存（step_001.py → step_002.py → latest.py）
- ArtifactRegistry：生成文件追踪（PNG/GeoJSON/CSV 等）
- ExecutionLog：每次 execute_python 的完整记录
- WorkingMemory：任务工作上下文（GIS 数据引用、CRS、当前步骤等）

存储：
- 内存字典 + JSON sidecar 磁盘持久化（与 pending_action.py 同模式）
- 目录：cache/tasks/<task_id>/task.json, code/, artifacts.json, exec_log.json
"""

import os
import json
import uuid
import threading
import datetime
import shutil
from typing import Optional

# ============================================================
# 目录结构
# ============================================================

_BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cache", "tasks"
)

_lock = threading.Lock()

# 内存缓存：task_id -> TaskMemory
_tasks: dict = {}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _task_dir(task_id: str) -> str:
    return os.path.join(_BASE_DIR, task_id)


def _task_json_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "task.json")


def _code_dir(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "code")


def _artifacts_json_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "artifacts.json")


def _exec_log_json_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "exec_log.json")


# ============================================================
# 数据模型
# ============================================================

def _new_task(user_goal: str, session_id: str = "default") -> dict:
    task_id = uuid.uuid4().hex[:12]
    now = _now()
    return {
        "task_id": task_id,
        "user_goal": user_goal,
        "status": "active",
        "session_id": session_id,
        "current_step": 0,
        "latest_code_version": None,
        "gis_context": {},
        "created_at": now,
        "updated_at": now,
        "archived": False,
    }


def _new_artifact(task_id: str, filename: str, filepath: str,
                   mime_type: str, size: int, artifact_type: str,
                   created_by_step: int = 0, derived_from: str = None) -> dict:
    artifact_id = uuid.uuid4().hex[:10]
    return {
        "artifact_id": artifact_id,
        "task_id": task_id,
        "type": artifact_type,
        "filename": filename,
        "path": filepath,
        "mime_type": mime_type,
        "size": size,
        "status": "success" if (filepath and os.path.exists(filepath) and size > 0) else "pending",
        "created_by_step": created_by_step,
        "derived_from": derived_from,
        "created_at": _now(),
    }


def _new_exec_record(task_id: str, step_id: int, source_code: str,
                      source_file: str, status: str, stdout: str = "",
                      stderr: str = "", exit_code: int = 0,
                      input_artifacts: list = None,
                      output_artifacts: list = None) -> dict:
    return {
        "task_id": task_id,
        "step_id": step_id,
        "execution_id": uuid.uuid4().hex[:8],
        "source_code": source_code,
        "source_file": source_file,
        "status": status,
        "stdout": stdout[:5000],
        "stderr": stderr[:2000],
        "exit_code": exit_code,
        "input_artifacts": input_artifacts or [],
        "output_artifacts": output_artifacts or [],
        "created_at": _now(),
    }


# ============================================================
# 磁盘持久化
# ============================================================

def _save_task_to_disk(task: dict):
    tid = task["task_id"]
    d = _task_dir(tid)
    os.makedirs(d, exist_ok=True)
    with open(_task_json_path(tid), "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)


def _load_task_from_disk(task_id: str) -> Optional[dict]:
    path = _task_json_path(task_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_artifacts_to_disk(task_id: str, artifacts: list):
    d = _task_dir(task_id)
    os.makedirs(d, exist_ok=True)
    with open(_artifacts_json_path(task_id), "w", encoding="utf-8") as f:
        json.dump(artifacts, f, ensure_ascii=False, indent=2)


def _load_artifacts_from_disk(task_id: str) -> list:
    path = _artifacts_json_path(task_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_exec_log_to_disk(task_id: str, log: list):
    d = _task_dir(task_id)
    os.makedirs(d, exist_ok=True)
    with open(_exec_log_json_path(task_id), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _load_exec_log_from_disk(task_id: str) -> list:
    path = _exec_log_json_path(task_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# ============================================================
# TaskManager API
# ============================================================

def create_task(user_goal: str, session_id: str = "default") -> str:
    """创建新任务，返回 task_id"""
    task = _new_task(user_goal, session_id)
    tid = task["task_id"]
    with _lock:
        _tasks[tid] = task
        _save_task_to_disk(task)
        # 创建代码目录
        os.makedirs(_code_dir(tid), exist_ok=True)
        # 初始化空列表
        _save_artifacts_to_disk(tid, [])
        _save_exec_log_to_disk(tid, [])
    print(f"[TaskManager] 创建任务 {tid}: {user_goal[:60]}", flush=True)
    return tid


def get_task(task_id: str) -> Optional[dict]:
    """获取任务（内存优先，磁盘兜底）"""
    with _lock:
        if task_id in _tasks:
            return _tasks[task_id]
    # 从磁盘加载
    task = _load_task_from_disk(task_id)
    if task:
        with _lock:
            _tasks[task_id] = task
    return task


def update_task(task_id: str, **kwargs) -> bool:
    """更新任务字段"""
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return False
        for k, v in kwargs.items():
            if k != "task_id":
                task[k] = v
        task["updated_at"] = _now()
        _save_task_to_disk(task)
    return True


def archive_task(task_id: str) -> bool:
    """归档任务"""
    return update_task(task_id, status="archived", archived=True)


def restore_task(task_id: str) -> bool:
    """恢复归档任务"""
    return update_task(task_id, status="active", archived=False)


def delete_task(task_id: str) -> bool:
    """删除任务及其所有文件"""
    with _lock:
        _tasks.pop(task_id, None)
    d = _task_dir(task_id)
    if os.path.exists(d):
        try:
            shutil.rmtree(d)
        except Exception:
            pass
    return True


def list_tasks(session_id: str = None, include_archived: bool = False) -> list:
    """列出任务（摘要）"""
    result = []
    # 从磁盘扫描
    if os.path.isdir(_BASE_DIR):
        for tid_dir in os.listdir(_BASE_DIR):
            task = get_task(tid_dir)
            if not task:
                continue
            if session_id and task.get("session_id") != session_id:
                continue
            if not include_archived and task.get("archived"):
                continue
            result.append({
                "task_id": task["task_id"],
                "user_goal": task["user_goal"][:100],
                "status": task["status"],
                "current_step": task["current_step"],
                "created_at": task["created_at"],
                "updated_at": task["updated_at"],
            })
    result.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return result


# ============================================================
# CodeCache API
# ============================================================

def save_code(task_id: str, source_code: str, label: str = None) -> int:
    """保存 Python 源代码到代码缓存，返回版本号（step_id）

    每次调用创建新版本：step_001.py, step_002.py, ... 并更新 latest.py
    """
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            # 尝试从磁盘加载
            task = _load_task_from_disk(task_id)
            if not task:
                return 0
            _tasks[task_id] = task

        step = task.get("current_step", 0) + 1
        task["current_step"] = step
        task["latest_code_version"] = step
        task["updated_at"] = _now()

        # 写入版本文件
        code_dir = _code_dir(task_id)
        os.makedirs(code_dir, exist_ok=True)
        version_file = os.path.join(code_dir, f"step_{step:03d}.py")
        with open(version_file, "w", encoding="utf-8") as f:
            f.write(source_code)

        # 更新 latest.py
        latest_file = os.path.join(code_dir, "latest.py")
        with open(latest_file, "w", encoding="utf-8") as f:
            f.write(source_code)

        # 如果有 label，保存到 metadata
        if label:
            meta_path = os.path.join(code_dir, "metadata.json")
            meta = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    pass
            meta[f"step_{step:03d}"] = {"label": label, "saved_at": _now()}
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

        _save_task_to_disk(task)
        print(f"[TaskManager] 保存代码 {task_id}/step_{step:03d}.py ({len(source_code)} bytes)", flush=True)
        return step


def get_latest_code(task_id: str) -> Optional[str]:
    """获取任务的最新 Python 源代码"""
    code_dir = _code_dir(task_id)
    latest = os.path.join(code_dir, "latest.py")
    if os.path.exists(latest):
        with open(latest, "r", encoding="utf-8") as f:
            return f.read()
    return None


def get_code_version(task_id: str, step: int) -> Optional[str]:
    """获取指定版本的 Python 源代码"""
    path = os.path.join(_code_dir(task_id), f"step_{step:03d}.py")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def get_code_versions(task_id: str) -> list:
    """列出所有代码版本"""
    code_dir = _code_dir(task_id)
    if not os.path.isdir(code_dir):
        return []
    versions = []
    for fname in sorted(os.listdir(code_dir)):
        if fname.startswith("step_") and fname.endswith(".py"):
            step = int(fname[5:8])
            fpath = os.path.join(code_dir, fname)
            size = os.path.getsize(fpath)
            versions.append({"step": step, "file": fname, "size": size})
    return versions


# ============================================================
# ArtifactRegistry API
# ============================================================

def register_artifact(task_id: str, filename: str, filepath: str,
                       mime_type: str = "", artifact_type: str = "file",
                       created_by_step: int = 0, derived_from: str = None) -> dict:
    """注册一个生成的 Artifact"""
    size = 0
    if filepath and os.path.exists(filepath):
        size = os.path.getsize(filepath)

    artifact = _new_artifact(
        task_id=task_id,
        filename=filename,
        filepath=filepath,
        mime_type=mime_type or _guess_mime(filename),
        size=size,
        artifact_type=artifact_type or _guess_type(filename),
        created_by_step=created_by_step,
        derived_from=derived_from,
    )

    # 验证：文件必须真实存在且 size > 0 才能标记 success
    if filepath and os.path.exists(filepath) and size > 0:
        artifact["status"] = "success"
    else:
        artifact["status"] = "failed"

    with _lock:
        artifacts = _load_artifacts_from_disk(task_id)
        artifacts.append(artifact)
        _save_artifacts_to_disk(task_id, artifacts)

    print(f"[TaskManager] 注册 Artifact {artifact['artifact_id']}: {filename} ({size} bytes, {artifact['status']})", flush=True)
    return artifact


def get_artifacts(task_id: str) -> list:
    """获取任务的所有 Artifact"""
    return _load_artifacts_from_disk(task_id)


def get_artifact(task_id: str, artifact_id: str) -> Optional[dict]:
    """获取指定 Artifact"""
    artifacts = _load_artifacts_from_disk(task_id)
    for a in artifacts:
        if a["artifact_id"] == artifact_id:
            return a
    return None


def verify_artifact(task_id: str, artifact_id: str) -> bool:
    """验证 Artifact 是否真实存在"""
    artifact = get_artifact(task_id, artifact_id)
    if not artifact:
        return False
    fp = artifact.get("path", "")
    return bool(fp and os.path.exists(fp) and os.path.getsize(fp) > 0)


def get_artifact_summary(task_id: str) -> str:
    """获取 Artifact 摘要（给 LLM 用）"""
    artifacts = get_artifacts(task_id)
    if not artifacts:
        return ""
    lines = ["### 已生成的文件"]
    for a in artifacts:
        status_icon = "✅" if a["status"] == "success" else "❌"
        lines.append(f"- {status_icon} {a['filename']} ({a['type']}, {a['size']} bytes, step_{a['created_by_step']:03d})")
    return "\n".join(lines)


# ============================================================
# ExecutionLog API
# ============================================================

def log_execution(task_id: str, step_id: int, source_code: str,
                   source_file: str, status: str, stdout: str = "",
                   stderr: str = "", exit_code: int = 0,
                   input_artifacts: list = None,
                   output_artifacts: list = None) -> dict:
    """记录一次 Python 执行"""
    record = _new_exec_record(
        task_id=task_id,
        step_id=step_id,
        source_code=source_code,
        source_file=source_file,
        status=status,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        input_artifacts=input_artifacts,
        output_artifacts=output_artifacts,
    )
    with _lock:
        log = _load_exec_log_from_disk(task_id)
        log.append(record)
        _save_exec_log_to_disk(task_id, log)
    return record


def get_exec_log(task_id: str) -> list:
    """获取任务的执行日志"""
    return _load_exec_log_from_disk(task_id)


def get_exec_log_summary(task_id: str) -> str:
    """获取执行日志摘要（给 LLM 用）"""
    log = get_exec_log(task_id)
    if not log:
        return ""
    lines = ["### 执行历史"]
    for rec in log:
        status_icon = "✅" if rec["status"] == "success" else "❌"
        code_preview = rec["source_code"][:80].replace("\n", " ") if rec.get("source_code") else ""
        lines.append(f"- Step {rec['step_id']:03d} {status_icon} ({rec['status']}): `{code_preview}...`")
    return "\n".join(lines)


# ============================================================
# WorkingMemory：GIS 上下文
# ============================================================

def update_gis_context(task_id: str, **kwargs):
    """更新任务的 GIS 上下文（CRS、数据路径、图层名等）"""
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return
        gis = task.get("gis_context", {})
        gis.update(kwargs)
        task["gis_context"] = gis
        task["updated_at"] = _now()
        _save_task_to_disk(task)


def get_gis_context(task_id: str) -> dict:
    """获取任务的 GIS 上下文"""
    task = get_task(task_id)
    return (task or {}).get("gis_context", {})


# ============================================================
# Context Builder：构建给 LLM 的任务上下文
# ============================================================

def build_task_context(task_id: str) -> str:
    """构建任务上下文字符串，注入到 LLM system prompt"""
    task = get_task(task_id)
    if not task:
        return ""

    parts = []

    # 任务基本信息
    parts.append(f"## 当前任务 (task_id: {task_id})")
    parts.append(f"目标: {task['user_goal']}")
    parts.append(f"状态: {task['status']}")
    parts.append(f"当前步骤: Step {task['current_step']:03d}")

    # 最新代码
    latest_code = get_latest_code(task_id)
    if latest_code:
        parts.append(f"\n### 上一轮执行的 Python 源代码 (step_{task['current_step']:03d}.py)")
        parts.append("```python")
        parts.append(latest_code)
        parts.append("```")
        parts.append("**重要：如果是修改/继续此任务，请基于以上代码修改，不要重新生成整个程序。**")

    # GIS 上下文
    gis = task.get("gis_context", {})
    if gis:
        parts.append("\n### GIS 数据上下文")
        for k, v in gis.items():
            parts.append(f"- {k}: {v}")

    # Artifact 摘要
    art_summary = get_artifact_summary(task_id)
    if art_summary:
        parts.append(f"\n{art_summary}")

    # 执行历史摘要
    exec_summary = get_exec_log_summary(task_id)
    if exec_summary:
        parts.append(f"\n{exec_summary}")

    return "\n".join(parts)


def find_active_task_for_session(session_id: str) -> Optional[str]:
    """查找会话的当前活跃任务"""
    if os.path.isdir(_BASE_DIR):
        for tid_dir in os.listdir(_BASE_DIR):
            task = get_task(tid_dir)
            if not task:
                continue
            if task.get("session_id") == session_id and task.get("status") == "active" and not task.get("archived"):
                return task["task_id"]
    return None


def find_or_create_task(session_id: str, user_message: str) -> str:
    """查找当前活跃任务或创建新任务

    策略：
    1. 如果有活跃任务 → 复用（多轮对话继续同一任务）
    2. 如果没有活跃任务 → 创建新任务
    """
    existing = find_active_task_for_session(session_id)
    if existing:
        return existing

    # 创建新任务
    return create_task(user_message, session_id)


# ============================================================
# 辅助函数
# ============================================================

def _guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".geojson": "application/geo+json",
        ".json": "application/json",
        ".csv": "text/csv",
        ".shp": "application/octet-stream",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".html": "text/html",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")


def _guess_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".gif": "image",
        ".svg": "image",
        ".geojson": "geojson",
        ".json": "geojson",
        ".csv": "csv",
        ".shp": "shapefile",
        ".tif": "raster",
        ".tiff": "raster",
        ".html": "html",
        ".pdf": "pdf",
    }.get(ext, "file")


def task_snapshot(task_id: str) -> dict:
    """任务快照（供调试/API）"""
    task = get_task(task_id)
    if not task:
        return {}
    return {
        "task_id": task["task_id"],
        "user_goal": task["user_goal"],
        "status": task["status"],
        "current_step": task["current_step"],
        "latest_code_version": task.get("latest_code_version"),
        "gis_context": task.get("gis_context", {}),
        "artifacts_count": len(get_artifacts(task_id)),
        "exec_log_count": len(get_exec_log(task_id)),
        "code_versions": len(get_code_versions(task_id)),
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }
