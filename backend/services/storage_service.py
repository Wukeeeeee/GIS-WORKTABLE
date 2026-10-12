# -*- coding: utf-8 -*-
"""GIS WorkTable — 本地 SQLite 事实台账服务 (Storage Service)

原则与设计：
1. 事实与执行台账统一落盘在本地 SQLite 数据库（默认 data/workspace.db）。
2. 所有产物路径统一存储为相对于工作区/仓库根目录的【相对路径】（跨机器迁移、换目录不失效）。
3. 严格关联 run_id，彻底隔离每轮独立执行的产物。
4. 提供数据库路径获取、自愈连接与备份能力。
"""

import os
import sqlite3
import threading
import datetime
from typing import Optional, List, Dict, Any

_LOCK = threading.RLock()
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DB_PATH = os.path.join(_REPO_ROOT, "data", "workspace.db")
_CUSTOM_DB_PATH = [None]


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def get_repo_root() -> str:
    """获取工作区/仓库根目录绝对路径"""
    return _REPO_ROOT


def get_db_path() -> str:
    """获取当前使用的 SQLite 数据库绝对路径"""
    if _CUSTOM_DB_PATH[0]:
        return _CUSTOM_DB_PATH[0]
    env_path = os.environ.get("GIS_WORKSPACE_DB_PATH", "").strip()
    if env_path:
        return os.path.abspath(env_path)
    return _DEFAULT_DB_PATH


def set_db_path(path: Optional[str]):
    """切换数据库文件路径（支持设置面板切换与测试隔离）"""
    with _LOCK:
        _CUSTOM_DB_PATH[0] = os.path.abspath(path) if path else None
    init_db()


def to_relative_path(path: str) -> str:
    """将物理路径转为统一以正斜杠分隔的相对于工作区根目录的相对路径"""
    if not path:
        return ""
    norm = os.path.normpath(path)
    root_norm = os.path.normpath(_REPO_ROOT)
    if norm.lower().startswith(root_norm.lower()):
        rel = os.path.relpath(norm, root_norm)
    else:
        rel = norm
    return rel.replace("\\", "/")


def to_absolute_path(rel_path: str) -> str:
    """将相对路径还原为当前系统的绝对路径"""
    if not rel_path:
        return ""
    if os.path.isabs(rel_path):
        return os.path.normpath(rel_path)
    return os.path.normpath(os.path.join(_REPO_ROOT, rel_path))


def get_connection() -> sqlite3.Connection:
    """获取 SQLite 连接并配置 row_factory"""
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # 开启 WAL 模式以提升并发读写性能
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    return conn


def init_db():
    """初始化数据库表结构（自愈建表）"""
    with _LOCK:
        conn = get_connection()
        try:
            cur = conn.cursor()
            # 1. 执行轮次表 (runs)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                task_id TEXT,
                session_id TEXT,
                user_message TEXT,
                ai_response TEXT,
                status TEXT DEFAULT 'pending',
                guard_status TEXT DEFAULT 'NOT_CHECKED',
                created_at TEXT,
                finished_at TEXT
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);")

            # 2. 产物明细表 (run_artifacts)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS run_artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                file_type TEXT DEFAULT 'file',
                file_size INTEGER DEFAULT 0,
                qa_status TEXT DEFAULT 'NOT_CHECKED',
                qa_details TEXT DEFAULT '',
                created_at TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_run ON run_artifacts(run_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_filename ON run_artifacts(filename);")

            conn.commit()
        finally:
            conn.close()


# 模块导入时自动确保库表就绪
init_db()


def record_run_start(run_id: str, session_id: str, user_message: str, task_id: str = "") -> bool:
    """记录一轮执行开始"""
    try:
        with _LOCK:
            conn = get_connection()
            try:
                conn.execute("""
                INSERT OR REPLACE INTO runs (run_id, task_id, session_id, user_message, status, created_at)
                VALUES (?, ?, ?, ?, 'running', ?)
                """, (run_id, task_id, session_id, user_message, _now()))
                conn.commit()
                return True
            finally:
                conn.close()
    except Exception as e:
        print(f"[StorageService] 记录 run_start 异常: {e}", flush=True)
        return False


def record_run_finish(run_id: str, ai_response: str, status: str = "success", guard_status: str = "PASS") -> bool:
    """记录一轮执行结束与核验汇总状态"""
    try:
        with _LOCK:
            conn = get_connection()
            try:
                conn.execute("""
                UPDATE runs
                SET ai_response = ?, status = ?, guard_status = ?, finished_at = ?
                WHERE run_id = ?
                """, (ai_response, status, guard_status, _now(), run_id))
                conn.commit()
                return True
            finally:
                conn.close()
    except Exception as e:
        print(f"[StorageService] 记录 run_finish 异常: {e}", flush=True)
        return False


def register_run_artifact(run_id: str, artifact_id: str, filename: str,
                          file_path: str, file_type: str = "file",
                          qa_status: str = "PASS", qa_details: str = "") -> bool:
    """向本轮执行登记一个确凿生成的物理产物（存相对路径）"""
    try:
        rel_path = to_relative_path(file_path)
        abs_path = to_absolute_path(rel_path)
        size = 0
        if os.path.exists(abs_path):
            try:
                size = os.path.getsize(abs_path)
            except OSError:
                size = 0

        with _LOCK:
            conn = get_connection()
            try:
                conn.execute("""
                INSERT OR REPLACE INTO run_artifacts (
                    artifact_id, run_id, filename, rel_path, file_type, file_size, qa_status, qa_details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (artifact_id, run_id, filename, rel_path, file_type, size, qa_status, qa_details, _now()))
                conn.commit()
                return True
            finally:
                conn.close()
    except Exception as e:
        print(f"[StorageService] 登记 artifact 异常: {e}", flush=True)
        return False


def get_run_artifacts(run_id: str) -> List[Dict[str, Any]]:
    """获取指定 run_id 下的所有产物（自动补全绝对路径与存在状态）"""
    try:
        with _LOCK:
            conn = get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                SELECT artifact_id, run_id, filename, rel_path, file_type, file_size, qa_status, qa_details, created_at
                FROM run_artifacts
                WHERE run_id = ?
                ORDER BY created_at ASC
                """, (run_id,))
                rows = cur.fetchall()
                results = []
                for r in rows:
                    item = dict(r)
                    abs_p = to_absolute_path(item["rel_path"])
                    item["abs_path"] = abs_p
                    item["exists"] = os.path.exists(abs_p) and (os.path.getsize(abs_p) > 0 if os.path.isfile(abs_p) else True)
                    results.append(item)
                return results
            finally:
                conn.close()
    except Exception as e:
        print(f"[StorageService] 查询 artifacts 异常: {e}", flush=True)
        return []


def get_db_stats() -> Dict[str, Any]:
    """获取当前数据库统计信息（用于设置面板展示）"""
    try:
        db_path = get_db_path()
        exists = os.path.exists(db_path)
        size_bytes = os.path.getsize(db_path) if exists else 0
        runs_count = 0
        artifacts_count = 0
        if exists:
            conn = get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM runs;")
                runs_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM run_artifacts;")
                artifacts_count = cur.fetchone()[0]
            finally:
                conn.close()
        return {
            "db_path": db_path,
            "exists": exists,
            "size_bytes": size_bytes,
            "runs_count": runs_count,
            "artifacts_count": artifacts_count,
        }
    except Exception as e:
        return {
            "db_path": get_db_path(),
            "exists": False,
            "error": str(e),
            "runs_count": 0,
            "artifacts_count": 0,
        }
