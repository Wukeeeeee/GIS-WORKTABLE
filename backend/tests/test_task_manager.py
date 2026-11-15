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

@pytest.mark.parametrize("record_kind", ["artifact", "execution"])
def test_late_result_does_not_recreate_deleted_task(tmp_path, record_kind):
    tid = task_manager.create_task("deleted while running", "deletion-test")
    task_dir = task_manager._task_dir(tid)
    artifact = tmp_path / "late-result.txt"
    artifact.write_text("completed after deletion", encoding="utf-8")
    assert task_manager.delete_task(tid)
    if record_kind == "artifact":
        result = task_manager.register_artifact(tid, artifact.name, str(artifact))
    else:
        result = task_manager.log_execution(tid, 1, "print(1)", "", "success")
    assert result["status"] == "failed"
    assert result.get("error")
    assert not os.path.exists(task_dir)
    assert task_manager.get_task(tid) is None


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


def test_archive_and_restore_keep_task_state_and_active_index_in_order(monkeypatch):
    session_id = "archive-restore-race"
    task_id = task_manager.create_task("归档恢复竞态", session_id)
    archive_updated = threading.Event()
    restore_started = threading.Event()
    restore_update_entered = threading.Event()
    release_archive = threading.Event()
    original_update = task_manager.update_task

    def pause_between_archive_and_index_cleanup(candidate_id, **updates):
        if updates.get("status") == "active":
            restore_update_entered.set()
        result = original_update(candidate_id, **updates)
        if updates.get("status") == "archived":
            archive_updated.set()
            assert release_archive.wait(timeout=3)
        return result

    def restore():
        restore_started.set()
        return task_manager.restore_task(task_id)

    monkeypatch.setattr(task_manager, "update_task", pause_between_archive_and_index_cleanup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        archive_future = pool.submit(task_manager.archive_task, task_id)
        assert archive_updated.wait(timeout=3)
        restore_future = pool.submit(restore)
        assert restore_started.wait(timeout=3)
        restore_interleaved = restore_update_entered.wait(timeout=0.2)
        release_archive.set()
        assert archive_future.result(timeout=3)
        assert restore_future.result(timeout=3)

    assert not restore_interleaved
    assert task_manager.get_task(task_id)["status"] == "active"
    assert task_manager._session_active[session_id] == task_id


def test_explicit_cross_session_task_reference_survives_cache_restart():
    owner_session = "cross-session-owner"
    borrowing_session = "cross-session-borrower"
    task_id = task_manager.create_task("被引用的历史任务", owner_session)

    assert task_manager.find_or_create_task(
        borrowing_session, "继续引用任务", task_id=task_id,
    ) == task_id
    task_manager._tasks.clear()
    task_manager._session_active.clear()

    assert task_manager.find_active_task_for_session(borrowing_session) == task_id
    assert [task["task_id"] for task in task_manager.list_tasks(borrowing_session)] == [task_id]
    assert task_manager.find_active_task_for_session(owner_session) == task_id


def test_linked_task_lists_follow_archive_restore_for_owner_and_borrower():
    from fastapi.testclient import TestClient
    from backend.main import app

    owner_session = "lifecycle-list-owner"
    borrower_session = "lifecycle-list-borrower"
    task_id = task_manager.create_task("跨会话列表生命周期", owner_session)
    assert task_manager.find_or_create_task(
        borrower_session, "继续引用任务", task_id=task_id,
    ) == task_id
    client = TestClient(app)

    def api_task_ids(session_id):
        response = client.get("/api/tasks", params={"session_id": session_id})
        assert response.status_code == 200
        return {task["task_id"] for task in response.json()["tasks"]}

    for session_id in (owner_session, borrower_session):
        assert task_id in api_task_ids(session_id)
        assert [task["task_id"] for task in task_manager.list_tasks(session_id)] == [task_id]

    assert task_manager.archive_task(task_id)
    for session_id in (owner_session, borrower_session):
        assert task_id not in task_manager.list_tasks(session_id)
        assert [task["task_id"] for task in task_manager.list_tasks(
            session_id, include_archived=True,
        )] == [task_id]
        assert task_id in api_task_ids(session_id)

    assert task_manager.restore_task(task_id)
    assert task_manager._session_active[owner_session] == task_id
    assert borrower_session not in task_manager._session_active
    assert task_manager.find_active_task_for_session(borrower_session) == task_id
    for session_id in (owner_session, borrower_session):
        assert task_id in api_task_ids(session_id)
        assert [task["task_id"] for task in task_manager.list_tasks(session_id)] == [task_id]


@pytest.mark.parametrize(
    ("action", "initially_archived"),
    [("archive", False), ("restore", True), ("delete", False)],
)
def test_task_lifecycle_api_rejects_mutation_while_shared_workspace_is_busy(
    action, initially_archived,
):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.services import tools

    task_id = task_manager.create_task("共享工作区忙时的任务生命周期", "busy-lifecycle")
    if initially_archived:
        assert task_manager.archive_task(task_id)
    assert tools.acquire_shared_state_lock(timeout=0)
    try:
        client = TestClient(app)
        if action == "archive":
            response = client.post(f"/api/tasks/{task_id}/archive")
        elif action == "restore":
            response = client.post(f"/api/tasks/{task_id}/restore")
        else:
            response = client.delete(f"/api/tasks/{task_id}")
    finally:
        tools.release_shared_state_lock()

    assert response.status_code == 409
    task = task_manager.get_task(task_id)
    assert task is not None
    assert task.get("archived", False) is initially_archived


def test_cancelled_task_lifecycle_api_releases_lock_acquired_by_background_thread(monkeypatch):
    import asyncio
    from backend import main
    from backend.services import tools

    task_id = task_manager.create_task("取消期间延迟获取的锁", "cancel-lock-acquire")
    real_acquire = tools.acquire_shared_state_lock
    started = threading.Event()
    allow_acquire = threading.Event()
    acquired = threading.Event()

    def delayed_acquire(timeout):
        started.set()
        allow_acquire.wait(3)
        result = real_acquire(timeout)
        acquired.set()
        return result

    monkeypatch.setattr(tools, "acquire_shared_state_lock", delayed_acquire)

    async def cancel_archive_request():
        request_task = asyncio.create_task(main.archive_task(task_id))
        assert await asyncio.to_thread(started.wait, 3)
        request_task.cancel()
        await asyncio.sleep(0)
        allow_acquire.set()
        with pytest.raises(asyncio.CancelledError):
            await request_task
        assert await asyncio.to_thread(acquired.wait, 3)
        lock_was_available = real_acquire(0)
        tools.release_shared_state_lock()
        return lock_was_available

    assert asyncio.run(cancel_archive_request()) is True


def test_explicit_reference_restores_archived_task_for_continuation():
    owner_session = "archived-reference-owner"
    borrowing_session = "archived-reference-borrower"
    archived_id = task_manager.create_task("已归档的历史任务", owner_session)
    assert task_manager.archive_task(archived_id)
    current_id = task_manager.create_task("当前会话任务", borrowing_session)

    assert task_manager.find_or_create_task(
        borrowing_session, "继续已引用的归档任务", task_id=archived_id,
    ) == archived_id

    restored = task_manager.get_task(archived_id)
    assert restored["status"] == "active"
    assert restored["archived"] is False
    assert task_manager._session_active[owner_session] == archived_id
    assert task_manager._session_active[borrowing_session] == archived_id
    assert task_manager.find_active_task_for_session(borrowing_session) == archived_id
    assert current_id != archived_id


def test_legacy_task_without_linked_sessions_still_restores_from_disk():
    session_id = "legacy-linked-session"
    task_id = task_manager.create_task("旧版任务元数据", session_id)
    legacy_record = task_manager.get_task(task_id)
    legacy_record.pop("linked_sessions", None)
    task_manager._save_task_to_disk(legacy_record)
    task_manager._tasks.clear()
    task_manager._session_active.clear()

    assert task_manager.find_active_task_for_session(session_id) == task_id
    assert [task["task_id"] for task in task_manager.list_tasks(session_id)] == [task_id]


@pytest.mark.parametrize("archived", [False, True], ids=["active", "archived"])
def test_cross_session_reference_persistence_failure_does_not_publish_alias(monkeypatch, archived):
    task_id = task_manager.create_task("不能丢失引用失败", "cross-session-owner")
    if archived:
        assert task_manager.archive_task(task_id)

    def fail_save(_task):
        raise OSError("simulated task metadata write failure")

    monkeypatch.setattr(task_manager, "_save_task_to_disk", fail_save)
    with pytest.raises(OSError, match="无法持久化跨会话任务引用"):
        task_manager.find_or_create_task(
            "cross-session-borrower", "继续引用任务", task_id=task_id,
        )

    assert task_manager.get_task(task_id).get("linked_sessions") == []
    assert task_manager.get_task(task_id)["archived"] is archived
    assert task_manager.get_task(task_id)["status"] == ("archived" if archived else "active")
    assert "cross-session-borrower" not in task_manager._session_active


@pytest.mark.parametrize("race_action", ["delete", "create"])
def test_disk_scan_does_not_overwrite_concurrent_session_state(monkeypatch, race_action):
    session_id = "scan-delete-race"
    task_id = task_manager.create_task("磁盘回扫删除竞态", session_id)
    task_manager._session_active.pop(session_id, None)
    task_manager._tasks.pop(task_id, None)
    loaded = threading.Event()
    release = threading.Event()
    original_get_task = task_manager.get_task

    def pause_after_disk_load(candidate_id):
        task = original_get_task(candidate_id)
        if candidate_id == task_id:
            loaded.set()
            assert release.wait(timeout=3)
        return task

    monkeypatch.setattr(task_manager, "get_task", pause_after_disk_load)
    with ThreadPoolExecutor(max_workers=1) as pool:
        lookup = pool.submit(task_manager.find_active_task_for_session, session_id)
        assert loaded.wait(timeout=3)
        if race_action == "delete":
            assert task_manager.delete_task(task_id)
            expected = None
        else:
            expected = task_manager.create_task("并发创建的活跃任务", session_id)
        release.set()
        assert lookup.result(timeout=3) == expected

    if expected is None:
        assert session_id not in task_manager._session_active
    else:
        assert task_manager._session_active[session_id] == expected


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
    existing_json = task_manager._read_text(existing_path)
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
    assert task_manager._read_text(existing_path) == existing_json
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


def test_failed_gis_operation_persistence_keeps_memory_and_disk_unchanged(monkeypatch):
    tid = task_manager.create_task("写盘失败保留最近成功结果", "gis-state-write-failure")
    previous_output = {"name": "durable_buffer", "layer_id": "buffer-1"}
    assert task_manager.record_gis_operation(
        tid, "spatial_buffer", {"layer_name": "source", "distance": 100},
        output_layers=[previous_output], status="success", run_id="run-durable",
    )
    before_memory = json.loads(json.dumps(task_manager.get_task(tid), ensure_ascii=False))
    before_disk = task_manager._load_task_from_disk(tid)

    def fail_save(_candidate):
        raise OSError("simulated GIS context metadata write failure")

    monkeypatch.setattr(task_manager, "_save_task_to_disk", fail_save)
    with pytest.raises(OSError, match="GIS context metadata write failure"):
        task_manager.record_gis_operation(
            tid, "spatial_buffer", {"layer_name": "source", "distance": 500},
            output_layers=[{"name": "unpersisted_buffer", "layer_id": "buffer-2"}],
            status="success", run_id="run-unpersisted",
        )

    assert task_manager.get_task(tid) == before_memory
    assert task_manager._load_task_from_disk(tid) == before_disk
    context = task_manager.get_gis_context(tid)
    assert context["last_successful_output"] == previous_output
    assert context["current_operation"]["run_id"] == "run-durable"


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
# 测试 2: Task 持久化（磁盘恢复）与快照
# ============================================================

def test_task_disk_persistence_and_snapshot():
    """验证任务从磁盘重新加载及快照字段完整性"""
    tid = task_manager.create_task("磁盘恢复测试目标", "session-persist")
    task_manager.save_code(tid, "print('step 1')", label="初始化")

    # 清空内存缓存以强制磁盘回读
    task_manager._tasks.clear()

    task = task_manager.get_task(tid)
    assert task is not None
    assert task["user_goal"] == "磁盘恢复测试目标"
    assert task["current_step"] == 1

    snap = task_manager.task_snapshot(tid)
    assert snap["task_id"] == tid
    assert snap["user_goal"] == "磁盘恢复测试目标"
    assert snap["current_step"] == 1
    assert snap["code_versions"] == 1
    assert snap["artifacts_count"] == 0
    assert snap["exec_log_count"] == 0


# ============================================================
# 测试 3: latest.py 恢复与多版本管理
# ============================================================

def test_multistep_code_versions_and_latest_recovery():
    """验证多轮代码更新（step_001 → step_002 → step_003）及 latest.py 恢复"""
    tid = task_manager.create_task("多轮代码版本测试", "session-multistep")

    s1 = task_manager.save_code(tid, "print('v1')", label="版本1")
    s2 = task_manager.save_code(tid, "print('v2')", label="版本2")
    s3 = task_manager.save_code(tid, "print('v3')", label="版本3")

    assert s1 == 1 and s2 == 2 and s3 == 3
    assert task_manager.get_code_version(tid, 1) == "print('v1')"
    assert task_manager.get_code_version(tid, 2) == "print('v2')"
    assert task_manager.get_code_version(tid, 3) == "print('v3')"
    assert task_manager.get_latest_code(tid) == "print('v3')"

    versions = task_manager.get_code_versions(tid)
    assert len(versions) == 3
    assert [v["step"] for v in versions] == [1, 2, 3]


def test_get_code_version_edge_cases():
    """验证 get_code_version 边界异常输入（step <= 0, bool, 越界版本, 非法 task_id）"""
    tid = task_manager.create_task("版本边界测试", "session-step-bounds")
    task_manager.save_code(tid, "print('v1')")

    # 非法 step 输入安全返回 None
    assert task_manager.get_code_version(tid, 0) is None
    assert task_manager.get_code_version(tid, -1) is None
    assert task_manager.get_code_version(tid, True) is None
    assert task_manager.get_code_version(tid, 999) is None
    assert task_manager.get_code_version("..", 1) is None
    assert task_manager.get_latest_code("..") is None


# ============================================================
# 测试 4: Artifact 持久化与摘要
# ============================================================

def test_artifact_registration_and_persistence(tmp_path):
    """验证 Artifact 注册、大小检测、状态判定与磁盘恢复"""
    tid = task_manager.create_task("产物注册测试", "session-artifact")

    real_file = tmp_path / "result.png"
    real_file.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-data")

    art1 = task_manager.register_artifact(
        tid, filename="result.png", filepath=str(real_file),
        artifact_type="image", created_by_step=1,
    )
    assert art1["status"] == "success"
    assert art1["size"] > 0

    art2 = task_manager.register_artifact(
        tid, filename="missing.geojson", filepath=str(tmp_path / "missing.geojson"),
        artifact_type="geojson", created_by_step=1,
    )
    assert art2["status"] == "failed"
    assert art2["size"] == 0

    artifacts = task_manager.get_artifacts(tid)
    assert len(artifacts) == 2

    summary = task_manager.get_artifact_summary(tid)
    assert "result.png" in summary
    assert "missing.geojson" in summary


# ============================================================
# 测试 5: ExecutionLog 持久化与摘要
# ============================================================

def test_execution_log_lifecycle_and_summary():
    """验证执行日志记录、截断与摘要"""
    tid = task_manager.create_task("日志记录测试", "session-log")

    rec1 = task_manager.log_execution(
        task_id=tid, step_id=1, source_code="print('ok')",
        source_file="step_001.py", status="success", stdout="output lines",
    )
    assert rec1["status"] == "success"

    rec2 = task_manager.log_execution(
        task_id=tid, step_id=2, source_code="raise ValueError('fail')",
        source_file="step_002.py", status="failed", stderr="error trace", exit_code=1,
    )
    assert rec2["status"] == "failed"

    log = task_manager.get_exec_log(tid)
    assert len(log) == 2
    assert log[0]["step_id"] == 1
    assert log[1]["step_id"] == 2

    summary = task_manager.get_exec_log_summary(tid)
    assert "Step 001" in summary
    assert "Step 002" in summary


# ============================================================
# 测试 6: 服务层防御与容错能力 (Task 1.d & 1.e)
# ============================================================

def test_service_level_invalid_task_id_defensive():
    """验证服务层 save_code('..', ...), get_artifacts('..'), get_exec_log('..') 安全返回无未捕获异常 (1.d)"""
    bad_ids = ["..", ".", " ", "", "a/b", "a\\b", None]
    for bad_id in bad_ids:
        assert task_manager.save_code(bad_id, "print('fail')") == 0
        assert task_manager.get_artifacts(bad_id) == []
        assert task_manager.get_exec_log(bad_id) == []


def test_list_tasks_tolerates_none_fields(tmp_path):
    """验证 list_tasks 能够容忍 task.json 中 user_goal 或 updated_at 为 None (1.e)"""
    corrupt_dir = tmp_path / "tasks" / "task_with_nulls"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    (corrupt_dir / "task.json").write_text(
        json.dumps({
            "task_id": "task_with_nulls",
            "user_goal": None,
            "status": "active",
            "current_step": 0,
            "created_at": None,
            "updated_at": None,
            "session_id": "default",
        }),
        encoding="utf-8"
    )

    normal_id = task_manager.create_task("正常任务", "default")

    tasks = task_manager.list_tasks(include_archived=True)
    task_ids = [t["task_id"] for t in tasks]
    assert normal_id in task_ids
    assert "task_with_nulls" in task_ids
    null_task = next(t for t in tasks if t["task_id"] == "task_with_nulls")
    assert null_task["user_goal"] == ""


# ============================================================
# 测试 7: 任务删除与清理
# ============================================================

def test_delete_task_lifecycle():
    """验证 delete_task 清除磁盘、内存及活跃会话索引"""
    session_id = "session-del"
    tid = task_manager.create_task("待删除任务", session_id)
    assert task_manager.find_active_task_for_session(session_id) == tid

    assert task_manager.delete_task(tid) is True
    assert task_manager.get_task(tid) is None
    assert task_manager.find_active_task_for_session(session_id) is None

    assert task_manager.delete_task(tid) is False
    assert task_manager.delete_task("..") is False
    assert task_manager.delete_task("") is False


def test_delete_linked_task_clears_all_session_active_indexes():
    owner_session = "delete-linked-owner"
    borrowing_session = "delete-linked-borrower"
    task_id = task_manager.create_task("被跨会话引用后删除", owner_session)
    assert task_manager.find_or_create_task(
        borrowing_session, "引用该任务", task_id=task_id,
    ) == task_id
    assert task_manager._session_active[owner_session] == task_id
    assert task_manager._session_active[borrowing_session] == task_id

    assert task_manager.delete_task(task_id)

    assert task_id not in task_manager._session_active.values()
    assert task_manager.find_active_task_for_session(owner_session) is None
    assert task_manager.find_active_task_for_session(borrowing_session) is None


def test_failed_delete_keeps_linked_task_and_all_session_indexes(monkeypatch):
    owner_session = "delete-failure-owner"
    borrowing_session = "delete-failure-borrower"
    task_id = task_manager.create_task("删除失败需保留", owner_session)
    assert task_manager.find_or_create_task(
        borrowing_session, "引用该任务", task_id=task_id,
    ) == task_id
    task_path = task_manager._task_dir(task_id)
    before_task = dict(task_manager.get_task(task_id))
    before_indexes = dict(task_manager._session_active)

    def fail_rmtree(_path):
        raise OSError("simulated remove failure")

    monkeypatch.setattr(task_manager.shutil, "rmtree", fail_rmtree)
    assert task_manager.delete_task(task_id) is False

    assert os.path.isdir(task_path)
    assert task_manager.get_task(task_id) == before_task
    assert task_manager._session_active == before_indexes
    assert task_manager.find_active_task_for_session(owner_session) == task_id
    assert task_manager.find_active_task_for_session(borrowing_session) == task_id


# ============================================================
# API 集成测试: 路由契约与错误处理 (Task 1.a, 1.b, 1.c)
# ============================================================

def test_api_invalid_task_id_returns_400():
    """验证传入非法或路径穿越 task_id 时所有路由统一返回 HTTP 400 (1.a)"""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    invalid_ids = ["%2e%2e", "bad%5csub", "%20", " "]
    for bad_id in invalid_ids:
        r_get = client.get(f"/api/tasks/{bad_id}")
        assert r_get.status_code == 400, f"GET {bad_id} expected 400, got {r_get.status_code}"

        r_code = client.get(f"/api/tasks/{bad_id}/code")
        assert r_code.status_code == 400, f"GET code {bad_id} expected 400, got {r_code.status_code}"

        r_arch = client.post(f"/api/tasks/{bad_id}/archive")
        assert r_arch.status_code == 400, f"POST archive {bad_id} expected 400, got {r_arch.status_code}"

        r_rest = client.post(f"/api/tasks/{bad_id}/restore")
        assert r_rest.status_code == 400, f"POST restore {bad_id} expected 400, got {r_rest.status_code}"

        r_del = client.delete(f"/api/tasks/{bad_id}")
        assert r_del.status_code == 400, f"DELETE {bad_id} expected 400, got {r_del.status_code}"


def test_api_nonexistent_task_returns_404():
    """验证操作不存在的任务时统一返回 HTTP 404 而不是 HTTP 200 (1.b)"""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    non_existent = "nonexistent_task_999"

    assert client.get(f"/api/tasks/{non_existent}").status_code == 404
    assert client.get(f"/api/tasks/{non_existent}/code").status_code == 404
    assert client.post(f"/api/tasks/{non_existent}/archive").status_code == 404
    assert client.post(f"/api/tasks/{non_existent}/restore").status_code == 404
    assert client.delete(f"/api/tasks/{non_existent}").status_code == 404


def test_api_get_task_code_step_validation():
    """验证 get_task_code 的 step 参数校验 (step >= 1) (1.c)"""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    tid = task_manager.create_task("测试步骤参数校验", "test_step_session")
    task_manager.save_code(tid, "print('step 1')", label="v1")

    # step = 0 不能被当成 falsy 偷偷返回 latest，必须返回 400
    r_zero = client.get(f"/api/tasks/{tid}/code?step=0")
    assert r_zero.status_code == 400, f"step=0 expected 400, got {r_zero.status_code}"

    # step < 0 必须返回 400
    r_neg = client.get(f"/api/tasks/{tid}/code?step=-1")
    assert r_neg.status_code == 400, f"step=-1 expected 400, got {r_neg.status_code}"

    # 合法 step 获取指定版本
    r_valid = client.get(f"/api/tasks/{tid}/code?step=1")
    assert r_valid.status_code == 200
    assert r_valid.json()["code"] == "print('step 1')"
    assert r_valid.json()["step"] == 1

    # 合法但不存在的版本号返回 404
    r_missing_step = client.get(f"/api/tasks/{tid}/code?step=2")
    assert r_missing_step.status_code == 404

    # 不带 step 返回 latest
    r_latest = client.get(f"/api/tasks/{tid}/code")
    assert r_latest.status_code == 200
    assert r_latest.json()["code"] == "print('step 1')"
    assert r_latest.json()["step"] == "latest"


def test_api_task_lifecycle_happy_path():
    """验证任务创建后的正常生命周期 API 调用 (GET -> ARCHIVE -> RESTORE -> DELETE)"""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    tid = task_manager.create_task("完整生命周期", "lifecycle_session")
    task_manager.save_code(tid, "print('live')", label="v1")

    # 1. GET task
    r_get = client.get(f"/api/tasks/{tid}")
    assert r_get.status_code == 200
    assert r_get.json()["task_id"] == tid

    # 2. Archive
    r_arch = client.post(f"/api/tasks/{tid}/archive")
    assert r_arch.status_code == 200
    assert r_arch.json() == {"success": True}
    assert task_manager.get_task(tid)["archived"] is True

    # 3. Restore
    r_rest = client.post(f"/api/tasks/{tid}/restore")
    assert r_rest.status_code == 200
    assert r_rest.json() == {"success": True}
    assert task_manager.get_task(tid)["archived"] is False

    # 4. Delete
    r_del = client.delete(f"/api/tasks/{tid}")
    assert r_del.status_code == 200
    assert r_del.json() == {"success": True}

    # 5. Subsequent access returns 404
    assert client.get(f"/api/tasks/{tid}").status_code == 404
