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

_lock = threading.RLock()

# 内存缓存：task_id -> TaskMemory
_tasks: dict = {}

# 会话  活跃任务 索引（避免 find_active_task_for_session 每次都全目录扫描）
_session_active: dict = {}  # session_id -> task_id


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _task_dir(task_id: str) -> str:
    if not isinstance(task_id, str) or not task_id or task_id in {".", ".."}:
        raise ValueError("无效 task_id")
    if os.path.basename(task_id) != task_id or "/" in task_id or "\\" in task_id or "\0" in task_id:
        raise ValueError("无效 task_id")
    base = os.path.realpath(_BASE_DIR)
    task_dir = os.path.realpath(os.path.join(base, task_id))
    try:
        common = os.path.commonpath((base, task_dir))
    except ValueError as exc:
        raise ValueError("无效 task_id") from exc
    if os.path.normcase(common) != os.path.normcase(base):
        raise ValueError("无效 task_id")
    return task_dir


def _task_json_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "task.json")


def _code_dir(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "code")


def _artifacts_json_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "artifacts.json")


def _exec_log_json_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "exec_log.json")


def _file_size(path: str) -> int:
    """返回普通文件大小；文件失效或被并发删除时按 0 字节处理。"""
    if not path:
        return 0
    try:
        return os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        return 0


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
        "status": "success" if size > 0 else "pending",
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

def _write_json_atomic(path: str, value) -> None:
    from backend.services.local_encryption import write_bytes_atomic
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    write_bytes_atomic(path, payload, _storage_context(path))


def _write_text_atomic(path: str, value: str) -> None:
    from backend.services.local_encryption import write_bytes_atomic
    write_bytes_atomic(path, str(value).encode("utf-8"), _storage_context(path))


def _storage_context(path: str) -> str:
    relative = os.path.relpath(os.path.abspath(path), os.path.abspath(_BASE_DIR))
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        raise ValueError("任务加密文件路径越界")
    return "task-store:" + relative.replace(os.sep, "/")


def _read_text(path: str) -> str:
    from backend.services.local_encryption import read_bytes
    return read_bytes(path, _storage_context(path)).decode("utf-8")


def _save_task_to_disk(task: dict):
    tid = task["task_id"]
    _write_json_atomic(_task_json_path(tid), task)


def _load_task_from_disk(task_id: str) -> Optional[dict]:
    path = _task_json_path(task_id)
    if not os.path.exists(path):
        return None
    try:
        data = json.loads(_read_text(path))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_artifacts_to_disk(task_id: str, artifacts: list):
    _write_json_atomic(_artifacts_json_path(task_id), artifacts)


def _load_artifacts_from_disk(task_id: str) -> list:
    path = _artifacts_json_path(task_id)
    if not os.path.exists(path):
        return []
    try:
        data = json.loads(_read_text(path))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def _save_exec_log_to_disk(task_id: str, log: list):
    _write_json_atomic(_exec_log_json_path(task_id), log)


def _load_exec_log_from_disk(task_id: str) -> list:
    path = _exec_log_json_path(task_id)
    if not os.path.exists(path):
        return []
    try:
        data = json.loads(_read_text(path))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception:
        return []


# ============================================================
# TaskManager API
# ============================================================

def create_task(user_goal: str, session_id: str = "default") -> str:
    """创建新任务，返回 task_id"""
    sid = session_id or "default"
    with _lock:
        os.makedirs(_BASE_DIR, exist_ok=True)
        for _ in range(10_000):
            task = _new_task(user_goal, sid)
            tid = task["task_id"]
            task_dir = _task_dir(tid)
            if tid in _tasks:
                continue
            try:
                # Reserve the new ID before writing anything so a collision can
                # never replace or clean up an existing task directory.
                os.mkdir(task_dir)
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("无法分配唯一的任务 ID")

        try:
            _save_task_to_disk(task)
            # 创建代码目录
            os.makedirs(_code_dir(tid), exist_ok=True)
            # 初始化空列表
            _save_artifacts_to_disk(tid, [])
            _save_exec_log_to_disk(tid, [])
        except Exception:
            shutil.rmtree(task_dir, ignore_errors=True)
            raise

        _tasks[tid] = task
        _session_active[sid] = tid
    print(f"[TaskManager] 创建任务 {tid}: {user_goal[:60]}", flush=True)
    return tid


def get_task(task_id: str) -> Optional[dict]:
    """获取任务（内存优先，磁盘兜底），双检锁保证并发放大读盘后写回导致老数据覆盖新值"""
    if not isinstance(task_id, str) or not task_id:
        return None
    with _lock:
        if task_id in _tasks:
            return _tasks[task_id]
    # 磁盘加载（无锁 IO）
    try:
        loaded = _load_task_from_disk(task_id)
    except (TypeError, ValueError):
        return None
    if not loaded:
        return None
    with _lock:
        # 双检：回到锁里再查一次，避免并发期间再有新数据写入又被覆盖
        existing = _tasks.get(task_id)
        if existing:
            return existing
        # 删除任务也持有同一把锁；若磁盘读取期间任务已被删除，不要把旧快照复活到缓存。
        if not os.path.isfile(_task_json_path(task_id)):
            return None
        _tasks[task_id] = loaded
        return loaded


def update_task(task_id: str, **kwargs) -> bool:
    """更新任务字段；内存未命中时先从磁盘恢复任务。"""
    try:
        if not get_task(task_id):
            return False
    except (TypeError, ValueError):
        return False
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return False
        candidate = dict(task)
        for k, v in kwargs.items():
            if k != "task_id":
                candidate[k] = v
        candidate["updated_at"] = _now()
        try:
            _save_task_to_disk(candidate)
        except Exception as e:
            print(f"[TaskManager] 更新任务 {task_id} 失败: {e}", flush=True)
            return False
        task.update(candidate)
    return True


def archive_task(task_id: str) -> bool:
    """归档任务"""
    ok = update_task(task_id, status="archived", archived=True)
    if ok:
        with _lock:
            for sid, tid in list(_session_active.items()):
                if tid == task_id:
                    _session_active.pop(sid, None)
    return ok


def restore_task(task_id: str) -> bool:
    """恢复归档任务"""
    with _lock:
        if not update_task(task_id, status="active", archived=False):
            return False
        task = _tasks.get(task_id)
        if not task:
            return False
        sid = task.get("session_id") or "default"
        _session_active[sid] = task_id
        return True


def delete_task(task_id: str) -> bool:
    """删除任务及其所有文件（磁盘的 rmtree 和内存清索引要放同一把锁里，避免并发重建）"""
    with _lock:
        try:
            d = _task_dir(task_id)
        except ValueError:
            return False
        task = _tasks.get(task_id) or _load_task_from_disk(task_id)
        directory_exists = os.path.exists(d)
        if not task and not directory_exists:
            return False
        if directory_exists:
            try:
                shutil.rmtree(d)
            except OSError:
                return False
        _tasks.pop(task_id, None)
        if task:
            sid = task.get("session_id") or "default"
            if _session_active.get(sid) == task_id:
                _session_active.pop(sid, None)
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
        candidate = dict(task)
        candidate["current_step"] = step
        candidate["latest_code_version"] = step
        candidate["updated_at"] = _now()

        # 写入版本文件
        code_dir = _code_dir(task_id)
        os.makedirs(code_dir, exist_ok=True)
        version_file = os.path.join(code_dir, f"step_{step:03d}.py")
        latest_file = os.path.join(code_dir, "latest.py")
        latest_existed = os.path.isfile(latest_file)
        latest_before = None
        if latest_existed:
            latest_before = _read_text(latest_file)

        try:
            _write_text_atomic(version_file, source_code)
            _write_text_atomic(latest_file, source_code)

            # 如果有 label，保存到 metadata
            if label:
                meta_path = os.path.join(code_dir, "metadata.json")
                meta = {}
                if os.path.exists(meta_path):
                    try:
                        meta = json.loads(_read_text(meta_path))
                    except Exception:
                        pass
                meta[f"step_{step:03d}"] = {"label": label, "saved_at": _now()}
                _write_json_atomic(meta_path, meta)

            _save_task_to_disk(candidate)
        except Exception:
            # The version is not committed until task metadata is durable.
            try:
                if os.path.exists(version_file):
                    os.remove(version_file)
                if latest_existed:
                    current_latest = _read_text(latest_file)
                    if current_latest != latest_before:
                        _write_text_atomic(latest_file, latest_before)
                elif os.path.exists(latest_file):
                    os.remove(latest_file)
            except Exception:
                pass
            raise

        task.update(candidate)
        print(f"[TaskManager] 保存代码 {task_id}/step_{step:03d}.py ({len(source_code)} bytes)", flush=True)
        return step


def get_latest_code(task_id: str) -> Optional[str]:
    """获取任务的最新 Python 源代码"""
    try:
        code_dir = _code_dir(task_id)
    except ValueError:
        return None
    latest = os.path.join(code_dir, "latest.py")
    try:
        return _read_text(latest)
    except Exception:
        return None


def get_code_version(task_id: str, step: int) -> Optional[str]:
    """获取指定版本的 Python 源代码"""
    if isinstance(step, bool) or not isinstance(step, int) or step < 1:
        return None
    try:
        path = os.path.join(_code_dir(task_id), f"step_{step:03d}.py")
    except ValueError:
        return None
    try:
        return _read_text(path)
    except Exception:
        return None


def get_code_versions(task_id: str) -> list:
    """列出所有代码版本"""
    try:
        code_dir = _code_dir(task_id)
        filenames = os.listdir(code_dir)
    except (OSError, ValueError):
        return []
    versions = []
    for fname in sorted(filenames):
        if fname.startswith("step_") and fname.endswith(".py"):
            step_text = fname[len("step_"):-len(".py")]
            if not step_text.isdigit():
                continue
            step = int(step_text)
            fpath = os.path.join(code_dir, fname)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                continue
            versions.append({"step": step, "file": fname, "size": size})
    versions.sort(key=lambda version: version["step"])
    return versions


# ============================================================
# ArtifactRegistry API
# ============================================================

def register_artifact(task_id: str, filename: str, filepath: str,
                       mime_type: str = "", artifact_type: str = "",
                       created_by_step: int = 0, derived_from: str = None) -> dict:
    """注册一个生成的 Artifact"""
    size = _file_size(filepath)

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
    if size > 0:
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

def record_gis_operation(task_id: str, tool: str, arguments: dict,
                        input_layers: list = None, output_layers: list = None,
                        output_artifacts: list = None, status: str = "success",
                        run_id: str = "") -> bool:
    """Record a GIS tool attempt while preserving the latest successful result on failure."""
    task = get_task(task_id)
    if not task:
        return False
    operation = {
        "tool": tool,
        "arguments": dict(arguments or {}),
        "input_layers": list(input_layers or []),
        "output_layers": list(output_layers or []),
        "output_artifacts": list(output_artifacts or []),
        "status": status,
        "run_id": run_id or "",
        "recorded_at": _now(),
    }
    # Read/append/write must be one critical section. Otherwise parallel tools can
    # both copy the same old context and the last writer silently erases the other.
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return False
        gis = dict(task.get("gis_context") or {})
        recent = list(gis.get("recent_operations") or [])
        recent.append(operation)
        gis["recent_operations"] = recent[-20:]
        gis["current_operation"] = operation
        if status == "success":
            gis["last_successful_operation"] = operation
            outputs = operation["output_layers"] or operation["output_artifacts"]
            if outputs:
                gis["last_successful_output"] = outputs[-1]
        task["gis_context"] = gis
        task["updated_at"] = _now()
        _save_task_to_disk(task)
    return True


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
            if k in {"recent_operations", "current_operation", "last_successful_operation", "last_successful_output"}:
                continue
            parts.append(f"- {k}: {v}")

    current_op = gis.get("current_operation") or {}
    last_success = gis.get("last_successful_operation") or {}
    latest_output = gis.get("last_successful_output")
    if current_op or last_success or latest_output:
        parts.append("\n### GIS 最近执行状态（以工具记录为准）")
        if current_op:
            parts.append("- 最近尝试: " + json.dumps(current_op, ensure_ascii=False, sort_keys=True))
        if last_success:
            parts.append("- 最近成功操作: " + json.dumps(last_success, ensure_ascii=False, sort_keys=True))
        if latest_output:
            parts.append("- 最近成功结果: " + json.dumps(latest_output, ensure_ascii=False, sort_keys=True))
        recent = gis.get("recent_operations") or []
        if recent:
            parts.append("- 最近 GIS 操作记录: " + json.dumps(recent[-8:], ensure_ascii=False, sort_keys=True))
        parts.append(
            "以上记录中的工具参数和图层标识来自实际执行。用户要修改分析参数时，找到最近成功的同类分析，"
            "沿用其原始输入与参数，仅修改用户指定的值后重跑；不要把分析输出当成原始输入，除非用户明确要求继续处理输出。"
            "用户指向刚才结果或要求导出时，使用最近成功结果中的准确图层名/产物。最近尝试失败时保留并使用最近成功结果。"
            "对象有多个候选时先简短询问。"
        )

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
    """查找会话的当前活跃任务（优先走内存索引，索引不命中才回扫磁盘并回填索引）"""
    sid = session_id or "default"
    with _lock:
        tid = _session_active.get(sid)
        if tid:
            task = _tasks.get(tid)
            if task and task.get("status") == "active" and not task.get("archived"):
                return tid
            # 索引里的任务已被删除/归档，丢掉索引项
            _session_active.pop(sid, None)
    # 索引未命中  可能服务刚重启，磁盘扫一次回填
    if os.path.isdir(_BASE_DIR):
        for tid_dir in os.listdir(_BASE_DIR):
            task = get_task(tid_dir)
            if not task:
                continue
            if task.get("session_id") == sid and task.get("status") == "active" and not task.get("archived"):
                with _lock:
                    _session_active[sid] = task["task_id"]
                return task["task_id"]
    return None


def find_or_create_task(session_id: str, user_message: str, task_id: str = None) -> str:
    """查找当前活跃任务或创建新任务

    策略：
    1. 用户明确引用已有任务时，优先继续该任务
    2. 如果有活跃任务 → 复用（多轮对话继续同一任务）
    3. 如果没有活跃任务 → 创建新任务
    """
    sid = session_id or "default"
    # 查找与创建必须是一个原子操作，否则同一会话的并发首轮请求会各自
    # 观察到“无活跃任务”并创建多条任务，最后一条覆盖 session 索引。
    with _lock:
        if task_id:
            referenced = get_task(str(task_id))
            if referenced:
                _session_active[sid] = str(task_id)
                return str(task_id)
            # Explicit reference must never silently fall back to an unrelated active task.
            return create_task(user_message, sid)

        existing = find_active_task_for_session(sid)
        if existing:
            return existing

        return create_task(user_message, sid)


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
