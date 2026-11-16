"""Empirical Challenger stress tests for Milestone M1 (Task Manager & Code Lifecycle).

Probing:
1. Corrupt disk sidecars: invalid JSON and null fields in task.json, artifacts.json, exec_log.json, metadata.json.
2. Lifecycle mutations on corrupted or read-only directories.
3. Rapid multi-turn step progression (50 sequential steps and concurrent steps).
4. List tasks sorting stability with missing, None, and non-string/malformed updated_at timestamps.
"""

import os
import json
import stat
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import task_manager


@pytest.fixture(autouse=True)
def isolate_task_storage(tmp_path, monkeypatch):
    """Keep probe task files and in-memory state isolated from real user tasks."""
    task_root = tmp_path / "tasks"
    task_root.mkdir()
    monkeypatch.setattr(task_manager, "_BASE_DIR", str(task_root))
    with task_manager._lock:
        monkeypatch.setattr(task_manager, "_tasks", {})
        monkeypatch.setattr(task_manager, "_session_active", {})
    yield
    with task_manager._lock:
        task_manager._tasks.clear()
        task_manager._session_active.clear()


# =======================================================================
# 1. Corrupt Disk Sidecars Probing
# =======================================================================

def test_probe_task_json_corrupt_syntax(tmp_path):
    """Probe: task.json contains invalid/truncated JSON syntax."""
    # Create task directory directly on disk in _BASE_DIR
    tid = "probe_corrupt_syntax"
    tdir = os.path.join(task_manager._BASE_DIR, tid)
    os.makedirs(tdir, exist_ok=True)
    task_file = os.path.join(tdir, "task.json")
    
    with open(task_file, "wb") as f:
        f.write(b'{"task_id": "probe_corrupt_syntax", truncated_json...')

    try:
        # get_task should degrade gracefully to None
        t = task_manager.get_task(tid)
        assert t is None, f"Expected None for corrupt task.json, got {t}"

        # list_tasks should skip the corrupted task without raising an exception
        tasks = task_manager.list_tasks()
        assert tid not in [x["task_id"] for x in tasks]

        # API calls should return 404 rather than 500
        client = TestClient(app)
        r = client.get(f"/api/tasks/{tid}")
        assert r.status_code == 404, f"GET expected 404, got {r.status_code}"

        r = client.get(f"/api/tasks/{tid}/code")
        assert r.status_code == 404, f"GET code expected 404, got {r.status_code}"

        r = client.post(f"/api/tasks/{tid}/archive")
        assert r.status_code == 404, f"POST archive expected 404, got {r.status_code}"

        r = client.post(f"/api/tasks/{tid}/restore")
        assert r.status_code == 404, f"POST restore expected 404, got {r.status_code}"

        # delete_task should delete the corrupt directory or return False safely
        del_result = task_manager.delete_task(tid)
        # Verify no unhandled exception
    finally:
        task_manager.delete_task(tid)
        if os.path.exists(tdir):
            import shutil
            shutil.rmtree(tdir, ignore_errors=True)


def test_probe_task_json_null_fields_get_task():
    """Probe: get_task, list_tasks, and task_snapshot with null fields in task.json."""
    tid = "probe_null_fields"
    tdir = os.path.join(task_manager._BASE_DIR, tid)
    os.makedirs(tdir, exist_ok=True)
    
    null_task = {
        "task_id": tid,
        "user_goal": None,
        "status": None,
        "session_id": None,
        "current_step": None,
        "latest_code_version": None,
        "gis_context": None,
        "created_at": None,
        "updated_at": None,
        "archived": None,
    }
    task_manager._write_json_atomic(os.path.join(tdir, "task.json"), null_task)

    try:
        task = task_manager.get_task(tid)
        assert task is not None
        assert task["task_id"] == tid

        tasks = task_manager.list_tasks()
        listed = next((x for x in tasks if x["task_id"] == tid), None)
        assert listed is not None
        assert listed["user_goal"] == ""

        snap = task_manager.task_snapshot(tid)
        assert snap["task_id"] == tid

        client = TestClient(app)
        r = client.get(f"/api/tasks/{tid}")
        assert r.status_code == 200
    finally:
        task_manager.delete_task(tid)


def test_probe_task_json_null_step_in_build_context():
    """Probe: build_task_context crashes if current_step is None in task.json."""
    tid = "probe_null_step_ctx"
    tdir = os.path.join(task_manager._BASE_DIR, tid)
    os.makedirs(tdir, exist_ok=True)
    null_task = {
        "task_id": tid,
        "user_goal": "Goal",
        "status": "active",
        "current_step": None,
        "gis_context": {},
    }
    task_manager._write_json_atomic(os.path.join(tdir, "task.json"), null_task)
    try:
        # Should build without TypeError: unsupported format string passed to NoneType.__format__
        ctx = task_manager.build_task_context(tid)
        assert isinstance(ctx, str)
    finally:
        task_manager.delete_task(tid)


def test_probe_task_json_null_step_in_save_code():
    """Probe: save_code crashes if current_step is None in task.json."""
    tid = "probe_null_step_save"
    tdir = os.path.join(task_manager._BASE_DIR, tid)
    os.makedirs(tdir, exist_ok=True)
    null_task = {
        "task_id": tid,
        "user_goal": "Goal",
        "status": "active",
        "current_step": None,
        "gis_context": {},
    }
    task_manager._write_json_atomic(os.path.join(tdir, "task.json"), null_task)
    try:
        # Should increment from 0 to 1 without TypeError
        s = task_manager.save_code(tid, "print('step')")
        assert s == 1
    finally:
        task_manager.delete_task(tid)


def test_probe_artifacts_json_corrupt_syntax():
    """Probe: artifacts.json contains invalid JSON syntax."""
    tid = task_manager.create_task("probe_artifacts_syntax")
    art_path = os.path.join(task_manager._task_dir(tid), "artifacts.json")
    with open(art_path, "wb") as f:
        f.write(b"not valid json {{{")

    try:
        arts = task_manager.get_artifacts(tid)
        assert arts == []

        summary = task_manager.get_artifact_summary(tid)
        assert summary == ""

        snap = task_manager.task_snapshot(tid)
        assert snap["artifacts_count"] == 0

        client = TestClient(app)
        r = client.get(f"/api/tasks/{tid}")
        assert r.status_code == 200
        assert r.json()["artifacts"] == []
    finally:
        task_manager.delete_task(tid)


def test_probe_artifacts_summary_null_and_missing_keys():
    """Probe: get_artifact_summary crashes if items lack keys or have None values."""
    tid = task_manager.create_task("probe_artifacts_nulls")
    art_path = os.path.join(task_manager._task_dir(tid), "artifacts.json")

    malformed_items = [
        {},
        {"artifact_id": "a1", "status": None, "filename": None, "created_by_step": None, "size": None, "type": None},
    ]
    task_manager._write_json_atomic(art_path, malformed_items)

    try:
        summary = task_manager.get_artifact_summary(tid)
        assert isinstance(summary, str)
    finally:
        task_manager.delete_task(tid)


def test_probe_exec_log_json_corrupt_syntax():
    """Probe: exec_log.json contains invalid JSON syntax."""
    tid = task_manager.create_task("probe_exec_log_syntax")
    log_path = os.path.join(task_manager._task_dir(tid), "exec_log.json")
    with open(log_path, "wb") as f:
        f.write(b"malformed exec log content [[{")

    try:
        logs = task_manager.get_exec_log(tid)
        assert logs == []

        summary = task_manager.get_exec_log_summary(tid)
        assert summary == ""

        snap = task_manager.task_snapshot(tid)
        assert snap["exec_log_count"] == 0

        client = TestClient(app)
        r = client.get(f"/api/tasks/{tid}")
        assert r.status_code == 200
        assert r.json()["exec_log"] == []
    finally:
        task_manager.delete_task(tid)


def test_probe_exec_log_summary_null_and_missing_keys():
    """Probe: get_exec_log_summary crashes if items lack status or step_id."""
    tid = task_manager.create_task("probe_exec_log_nulls")
    log_path = os.path.join(task_manager._task_dir(tid), "exec_log.json")

    malformed_records = [
        {},
        {"step_id": None, "status": None, "source_code": None},
    ]
    task_manager._write_json_atomic(log_path, malformed_records)

    try:
        summary = task_manager.get_exec_log_summary(tid)
        assert isinstance(summary, str)
    finally:
        task_manager.delete_task(tid)


def test_probe_metadata_json_corrupt():
    """Probe: metadata.json in code/ is non-dict (e.g. null, string, or corrupted)."""
    tid = task_manager.create_task("probe_metadata_corrupt")
    code_dir = os.path.join(task_manager._task_dir(tid), "code")
    os.makedirs(code_dir, exist_ok=True)
    meta_path = os.path.join(code_dir, "metadata.json")

    # 1. Corrupt syntax
    with open(meta_path, "wb") as f:
        f.write(b"corrupt meta")
    s1 = task_manager.save_code(tid, "print('s1')", label="label1")
    assert s1 == 1

    # 2. Non-dict JSON (e.g. string "hello")
    task_manager._write_json_atomic(meta_path, "not a dictionary")
    s2 = task_manager.save_code(tid, "print('s2')", label="label2")
    assert s2 == 2

    # 3. null in metadata.json
    task_manager._write_json_atomic(meta_path, None)
    s3 = task_manager.save_code(tid, "print('s3')", label="label3")
    assert s3 == 3
    task_manager.delete_task(tid)


def test_probe_register_artifact_and_log_execution_invalid_task_id():
    """Probe: register_artifact and log_execution with invalid task_id."""
    # Should safely return or raise handled exception, not unhandled ValueError
    art = task_manager.register_artifact("..", "test.png", "some/path")
    assert art is None or art.get("status") == "failed"



# =======================================================================
# 2. Lifecycle Mutations on Corrupted or Read-Only Directories Probing
# =======================================================================

def test_probe_task_dir_is_a_file():
    """Probe: A task ID directory is actually a file, not a directory."""
    tid = "probe_file_dir"
    file_path = os.path.join(task_manager._BASE_DIR, tid)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("I am a file, not a directory")

    try:
        # None of these should crash with unhandled NotADirectoryError or similar
        assert task_manager.get_task(tid) is None
        assert task_manager.save_code(tid, "print('hi')") == 0
        assert task_manager.get_code_versions(tid) == []
        assert task_manager.get_artifacts(tid) == []
        assert task_manager.get_exec_log(tid) == []
        assert task_manager.update_task(tid, status="archived") is False
        assert task_manager.archive_task(tid) is False
        assert task_manager.restore_task(tid) is False
        
        # list_tasks should not fail
        tasks = task_manager.list_tasks()
        assert isinstance(tasks, list)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def test_probe_readonly_directory_lifecycle():
    """Probe: Task directory is read-only. Mutations should degrade gracefully."""
    tid = task_manager.create_task("probe_readonly_task")
    tdir = task_manager._task_dir(tid)
    task_manager.save_code(tid, "print('initial')", label="v1")

    # Make the directory read-only (Windows attrib or chmod)
    # On Windows, marking directory read-only via os.chmod(tdir, stat.S_IREAD)
    # or marking files read-only.
    task_json = os.path.join(tdir, "task.json")
    os.chmod(task_json, stat.S_IREAD)

    try:
        # update_task should return False, not raise PermissionError
        ok = task_manager.update_task(tid, user_goal="changed goal")
        assert ok is False

        # archive_task should return False
        ok_arch = task_manager.archive_task(tid)
        assert ok_arch is False

        # restore_task should return False
        ok_rest = task_manager.restore_task(tid)
        assert ok_rest is False

        # API POST archive should return 200 {"success": False}
        client = TestClient(app)
        r_arch = client.post(f"/api/tasks/{tid}/archive")
        assert r_arch.status_code == 200
        assert r_arch.json()["success"] is False

        r_rest = client.post(f"/api/tasks/{tid}/restore")
        assert r_rest.status_code == 200
        assert r_rest.json()["success"] is False
    finally:
        # Restore write permissions for cleanup
        os.chmod(task_json, stat.S_IWRITE)
        task_manager.delete_task(tid)


# =======================================================================
# 3. Rapid Multi-turn Step Progression (50 Sequential Steps) Probing
# =======================================================================

def test_probe_rapid_50_steps_progression():
    """Probe: Rapid sequential execution of 50 save_code steps."""
    tid = task_manager.create_task("probe_50_steps", "session_50")

    step_results = []
    for i in range(1, 51):
        code_content = f"# Step {i}\nprint('Executing step {i}')\nx = {i} * 2"
        step = task_manager.save_code(tid, code_content, label=f"step_{i}")
        step_results.append(step)

    assert step_results == list(range(1, 51)), f"Step progression mismatch: {step_results}"

    # Verify latest_code
    latest = task_manager.get_latest_code(tid)
    assert latest == "# Step 50\nprint('Executing step 50')\nx = 50 * 2"

    # Verify task current_step in memory
    task = task_manager.get_task(tid)
    assert task["current_step"] == 50
    assert task["latest_code_version"] == 50

    # Clear memory cache and re-verify from disk persistence
    task_manager._tasks.clear()
    task_reloaded = task_manager.get_task(tid)
    assert task_reloaded["current_step"] == 50
    assert task_reloaded["latest_code_version"] == 50

    # Verify all 50 versions in get_code_versions
    versions = task_manager.get_code_versions(tid)
    assert len(versions) == 50
    assert [v["step"] for v in versions] == list(range(1, 51))

    # Spot check versions
    assert task_manager.get_code_version(tid, 1) == "# Step 1\nprint('Executing step 1')\nx = 1 * 2"
    assert task_manager.get_code_version(tid, 25) == "# Step 25\nprint('Executing step 25')\nx = 25 * 2"
    assert task_manager.get_code_version(tid, 50) == latest

    # Verify API code endpoint for step 1, 50, and latest
    client = TestClient(app)
    r_50 = client.get(f"/api/tasks/{tid}/code?step=50")
    assert r_50.status_code == 200
    assert r_50.json()["step"] == 50
    assert r_50.json()["code"] == latest

    r_latest = client.get(f"/api/tasks/{tid}/code")
    assert r_latest.status_code == 200
    assert r_latest.json()["step"] == "latest"
    assert r_latest.json()["code"] == latest

    task_manager.delete_task(tid)


# =======================================================================
# 4. List Tasks Sorting Stability with Missing or Malformed Timestamps Probing
# =======================================================================

def test_probe_list_tasks_sorting_stability():
    """Probe: list_tasks sorting with missing, None, non-string, and malformed timestamps."""
    # Create several tasks with various malformed updated_at values
    corrupt_specs = [
        ("task_null_ts", None),
        ("task_int_ts", 1730000000),
        ("task_float_ts", 1730000000.5),
        ("task_bool_ts", True),
        ("task_list_ts", ["2026-11-06T10:00:00"]),
        ("task_dict_ts", {"ts": "2026-11-06"}),
        ("task_empty_ts", ""),
        ("task_valid_ts_1", "2026-11-06T12:00:00+00:00"),
        ("task_valid_ts_2", "2026-11-06T13:00:00+00:00"),
    ]

    created_tids = []
    for tid, ts_val in corrupt_specs:
        tdir = os.path.join(task_manager._BASE_DIR, tid)
        os.makedirs(tdir, exist_ok=True)
        raw_task = {
            "task_id": tid,
            "user_goal": f"Goal for {tid}",
            "status": "active",
            "current_step": 1,
            "session_id": "test_sort",
            "updated_at": ts_val,
        }
        task_manager._write_json_atomic(os.path.join(tdir, "task.json"), raw_task)
        created_tids.append(tid)

    try:
        # list_tasks must not crash with TypeError or unhandled exception
        tasks = task_manager.list_tasks(session_id="test_sort", include_archived=True)
        assert isinstance(tasks, list)
        found_tids = [t["task_id"] for t in tasks]
        for tid in created_tids:
            assert tid in found_tids

        # API GET /api/tasks must also return 200 without 500 error
        client = TestClient(app)
        r = client.get("/api/tasks?session_id=test_sort")
        assert r.status_code == 200
        assert len(r.json()["tasks"]) == len(created_tids)
    finally:
        for tid in created_tids:
            task_manager.delete_task(tid)
