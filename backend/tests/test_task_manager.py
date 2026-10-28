# -*- coding: utf-8 -*-
"""
Task Manager 测试（不打真实 LLM / 网络，全本地确定性验证）

对应需求：Task Working Memory + Python Source Code Cache + Artifact Registry + Task Archive

测试覆盖：
  测试 1  Python source code 保存
  测试 2  Task 可以恢复（从磁盘重新加载）
  测试 3  latest.py 可以恢复
  测试 4  Artifact 可以恢复
  测试 5  同一个 task_id 跨多轮
  测试 6  Context Builder 可以提供上一轮完整 Python source code
  测试 7  Sandbox failure 后 Task State 正确
  测试 8  Archive / Restore
  测试 9  不同 Task 之间 Context 不串
  测试 10 多轮 Python 修改（step_001 → step_002 → step_003）
"""
import os
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.services import task_manager
from backend.services.tools import (
    reset_state, set_current_task, get_current_task_id,
    save_code, get_latest_code, register_artifact, log_execution,
)


@pytest.fixture(autouse=True)
def isolated_task_dir(tmp_path, monkeypatch):
    """把 task_manager 的存储目录指到临时目录，避免污染仓库。"""
    test_dir = str(tmp_path / "tasks")
    monkeypatch.setattr(task_manager, "_BASE_DIR", test_dir)
    task_manager._tasks.clear()
    task_manager._session_active.clear()
    yield
    task_manager._tasks.clear()
    task_manager._session_active.clear()


# ============================================================
# 测试 1: Python source code 保存
# ============================================================

def test_code_save_and_retrieve():
    """保存 Python 源代码后可以正确读取"""
    tid = task_manager.create_task("生成广州地图", "test_session")
    code = "import matplotlib.pyplot as plt\nplt.plot([1,2,3])\nplt.savefig('test.png')"
    step = save_code(tid, code, label="绘制折线图")

    assert step == 1
    latest = get_latest_code(tid)
    assert latest == code
    versions = task_manager.get_code_versions(tid)
    assert len(versions) == 1
    assert versions[0]["step"] == 1


def test_failed_code_write_does_not_advance_the_task_step(tmp_path, monkeypatch):
    tid = task_manager.create_task("恢复代码写入", "code-write-failure")
    original_write = task_manager._write_text_atomic

    def fail_first_version(path, content):
        if path.endswith("step_001.py"):
            raise OSError("simulated version write failure")
        return original_write(path, content)

    monkeypatch.setattr(task_manager, "_write_text_atomic", fail_first_version)
    with pytest.raises(OSError, match="simulated version write failure"):
        task_manager.save_code(tid, "print('first')")

    assert task_manager.get_task(tid)["current_step"] == 0
    monkeypatch.setattr(task_manager, "_write_text_atomic", original_write)
    assert task_manager.save_code(tid, "print('retry')") == 1
    assert task_manager.get_code_version(tid, 1) == "print('retry')"


def test_failed_latest_write_does_not_expose_an_uncommitted_code_version(monkeypatch):
    tid = task_manager.create_task("回滚未完成的代码版本", "latest-write-failure")
    task_manager.save_code(tid, "print('committed')")
    original_write = task_manager._write_text_atomic

    def fail_latest(path, content):
        if path.endswith("latest.py"):
            raise OSError("simulated latest code write failure")
        return original_write(path, content)

    monkeypatch.setattr(task_manager, "_write_text_atomic", fail_latest)
    with pytest.raises(OSError, match="simulated latest code write failure"):
        task_manager.save_code(tid, "print('uncommitted')")

    assert [version["step"] for version in task_manager.get_code_versions(tid)] == [1]
    assert task_manager.get_code_version(tid, 1) == "print('committed')"
    assert task_manager.get_latest_code(tid) == "print('committed')"
    assert task_manager.get_task(tid)["current_step"] == 1


def test_task_directory_rejects_a_resolved_symlink_escape(tmp_path, monkeypatch):
    base = tmp_path / "tasks"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    monkeypatch.setattr(task_manager, "_BASE_DIR", str(base))
    linked = base / "linked-task"
    realpath = os.path.realpath

    def resolve_with_escape(path):
        if os.fspath(path) == os.fspath(linked):
            return os.fspath(outside)
        return realpath(path)

    monkeypatch.setattr(task_manager.os.path, "realpath", resolve_with_escape)
    with pytest.raises(ValueError, match="无效 task_id"):
        task_manager._task_dir("linked-task")


def test_task_update_does_not_change_memory_when_persistence_fails(monkeypatch):
    tid = task_manager.create_task("归档状态保持一致", "task-update-failure")
    before = dict(task_manager.get_task(tid))

    def fail_save(_task):
        raise OSError("simulated task metadata write failure")

    monkeypatch.setattr(task_manager, "_save_task_to_disk", fail_save)
    assert task_manager.archive_task(tid) is False

    current = task_manager.get_task(tid)
    assert current["status"] == before["status"]
    assert current["archived"] == before["archived"]
    assert current["updated_at"] == before["updated_at"]
    assert task_manager.find_active_task_for_session("task-update-failure") == tid


def test_restoring_archived_task_makes_it_the_session_active_task():
    session_id = "restore-task-focus"
    archived = task_manager.create_task("归档任务", session_id)
    assert task_manager.archive_task(archived)
    current = task_manager.create_task("当前任务", session_id)
    assert task_manager.find_active_task_for_session(session_id) == current

    assert task_manager.restore_task(archived)

    assert task_manager.find_active_task_for_session(session_id) == archived


def test_failed_task_restore_keeps_the_existing_session_active_task(monkeypatch):
    session_id = "restore-task-write-failure"
    archived = task_manager.create_task("归档任务", session_id)
    assert task_manager.archive_task(archived)
    current = task_manager.create_task("当前任务", session_id)

    def fail_save(_task):
        raise OSError("simulated task metadata write failure")

    monkeypatch.setattr(task_manager, "_save_task_to_disk", fail_save)
    assert task_manager.restore_task(archived) is False

    assert task_manager.get_task(archived)["archived"] is True
    assert task_manager.find_active_task_for_session(session_id) == current


def test_failed_task_creation_does_not_publish_an_active_task(monkeypatch):
    session_id = "task-create-failure"
    task_id = "createfail001"
    monkeypatch.setattr(task_manager, "_new_task", lambda _goal, _session: {
        "task_id": task_id,
        "user_goal": "初始化失败任务",
        "status": "active",
        "session_id": session_id,
        "current_step": 0,
        "latest_code_version": None,
        "gis_context": {},
        "created_at": "now",
        "updated_at": "now",
        "archived": False,
    })

    def fail_initial_save(_task):
        raise OSError("simulated task metadata write failure")

    monkeypatch.setattr(task_manager, "_save_task_to_disk", fail_initial_save)
    with pytest.raises(OSError, match="metadata write failure"):
        task_manager.create_task("初始化失败任务", session_id)

    assert task_manager.get_task(task_id) is None
    assert task_manager.find_active_task_for_session(session_id) is None
    assert not os.path.exists(task_manager._task_dir(task_id))


def test_task_creation_retries_an_existing_id_without_touching_its_directory(monkeypatch):
    existing_id = task_manager.create_task("必须保留的任务", "existing-session")
    existing_path = task_manager._task_json_path(existing_id)
    with open(existing_path, "r", encoding="utf-8") as source:
        existing_json = source.read()
    generated_ids = iter([existing_id, "fresh-task-001"])

    def deterministic_task(goal, session_id):
        now = "now"
        return {
            "task_id": next(generated_ids),
            "user_goal": goal,
            "status": "active",
            "session_id": session_id,
            "current_step": 0,
            "latest_code_version": None,
            "gis_context": {},
            "created_at": now,
            "updated_at": now,
            "archived": False,
        }

    monkeypatch.setattr(task_manager, "_new_task", deterministic_task)
    fresh_id = task_manager.create_task("新任务", "new-session")

    assert fresh_id == "fresh-task-001"
    with open(existing_path, "r", encoding="utf-8") as source:
        assert source.read() == existing_json
    assert task_manager.get_task(existing_id)["user_goal"] == "必须保留的任务"


def test_gis_operation_context_preserves_latest_success_after_failure():
    tid = task_manager.create_task("长沙边界缓冲并导出", "gis-state-session")
    source = {"name": "长沙市", "layer_id": "source-1"}
    first = {"name": "长沙市_缓冲区", "layer_id": "buffer-500"}
    task_manager.record_gis_operation(
        tid, "spatial_buffer", {"layer_name": "长沙市", "distance": 500, "unit": "m"},
        input_layers=[source], output_layers=[first], status="success", run_id="run-1",
    )
    task_manager.record_gis_operation(
        tid, "spatial_buffer", {"layer_name": "缺失图层", "distance": 1000, "unit": "m"},
        input_layers=[{"name": "缺失图层", "layer_id": ""}], status="failed", run_id="run-2",
    )

    context = task_manager.get_gis_context(tid)
    assert context["current_operation"]["status"] == "failed"
    assert context["last_successful_operation"]["arguments"]["distance"] == 500
    assert context["last_successful_output"] == first
    prompt_context = task_manager.build_task_context(tid)
    assert '"layer_id": "source-1"' in prompt_context
    assert '"status": "failed"' in prompt_context
    assert "不要把分析输出当成原始输入" in prompt_context


def test_gis_operation_state_isolated_by_task_and_session():
    task_a = task_manager.create_task("任务 A", "session-A")
    task_b = task_manager.create_task("任务 B", "session-B")
    task_manager.record_gis_operation(
        task_a, "spatial_buffer", {"layer_name": "A", "distance": 500},
        output_layers=[{"name": "A_buffer", "layer_id": "a1"}], status="success",
    )
    assert task_manager.get_gis_context(task_b) == {}
    assert task_manager.find_active_task_for_session("session-A") == task_a
    assert task_manager.find_active_task_for_session("session-B") == task_b


def test_parallel_gis_operation_records_do_not_overwrite_each_other(monkeypatch):
    tid = task_manager.create_task("并行 GIS 操作", "parallel-session")
    original_get_task = task_manager.get_task
    loaded = threading.Barrier(2)

    def synchronized_snapshot(task_id):
        task = original_get_task(task_id)
        snapshot = json.loads(json.dumps(task)) if task else None
        loaded.wait(timeout=3)
        return snapshot

    monkeypatch.setattr(task_manager, "get_task", synchronized_snapshot)

    def record(name):
        return task_manager.record_gis_operation(
            tid, name, {"source": name},
            output_layers=[{"name": name + "_output", "layer_id": name}],
            status="success", run_id=name,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, ("parallel-A", "parallel-B")))

    assert results == [True, True]
    monkeypatch.setattr(task_manager, "get_task", original_get_task)
    context = task_manager.get_gis_context(tid)
    assert {op["tool"] for op in context["recent_operations"]} == {"parallel-A", "parallel-B"}
    assert context["last_successful_output"]["name"] in {"parallel-A_output", "parallel-B_output"}




# ============================================================
# 测试 2: Task 持久化（磁盘恢复）
# ============================================================



# ============================================================
# 测试 3: latest.py 恢复
# ============================================================



# ============================================================
# 测试 4: Artifact 持久化
# ============================================================





# ============================================================
# 测试 5: 同一个 task_id 跨多轮
# ============================================================



# ============================================================
# 测试 6: Context Builder 提供上一轮完整 Python source code
# ============================================================





# ============================================================
# 测试 7: Sandbox failure 后 Task State 正确
# ============================================================





# ============================================================
# 测试 8: Archive / Restore
# ============================================================



# ============================================================
# 测试 9: 不同 Task 之间 Context 不串
# ============================================================



# ============================================================
# 测试 10: 多轮 Python 修改（step_001 → step_002 → step_003）
# ============================================================



# ============================================================
# 测试: set_current_task / get_current_task_id
# ============================================================



# ============================================================
# 测试: find_or_create_task 策略
# ============================================================





# ============================================================
# 测试: delete_task
# ============================================================

