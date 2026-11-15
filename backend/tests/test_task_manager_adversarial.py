"""Adversarial and stress test suite for Task Manager and /api/tasks/* endpoints.

Probe targets:
- Malicious path traversal variations (URL-encoded, double-encoded, null bytes,
  backslashes, mixed slashes, Windows device names, whitespace padding, unicode dots).
- Root directory access/deletion defense.
- Extreme boundary values for step parameter.
- Concurrency and race conditions.
- Zero unhandled 500 errors and directory integrity guarantee.
"""

import os
import shutil
import threading
import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import task_manager


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolate_task_storage(tmp_path, monkeypatch):
    """Keep every adversarial task-manager case away from real task data."""
    task_root = tmp_path / "tasks"
    task_root.mkdir()
    monkeypatch.setattr(task_manager, "_BASE_DIR", str(task_root))


def test_adversarial_path_traversal_service_layer():
    """Verify that service-layer methods strictly reject or safely handle traversal payloads."""
    # Payloads that must be rejected by is_valid_task_id
    invalid_payloads = [
        "",
        ".",
        "..",
        "...",
        "....",
        ".....",
        "/",
        "\\",
        "//",
        "\\\\",
        "..\\",
        "../",
        "..\\..",
        "../../",
        "%2e%2e",
        "%2e%2e%2f",
        "%2e%2e%5c",
        "bad%5csub",
        "bad/sub",
        "bad\\sub",
        "foo\0bar",
        "%00",
        "C:",
        "C:foo",
        "D:bar",
        " ",
        "   ",
        "\t",
        "\n",
        " foo",
        "foo ",
        "foo\t",
        "foo\n",
    ]

    for p in invalid_payloads:
        assert not task_manager.is_valid_task_id(p), f"Payload {repr(p)} should be invalid"
        assert task_manager.get_task(p) is None
        assert task_manager.delete_task(p) is False
        assert task_manager.archive_task(p) is False
        assert task_manager.restore_task(p) is False
        assert task_manager.save_code(p, "print(1)") == 0
        assert task_manager.get_latest_code(p) is None
        assert task_manager.get_code_versions(p) == []


def test_adversarial_path_traversal_api_layer(client):
    """Verify that all API routes reject traversal variations without returning 500."""
    # Group 1: Explicitly malformed task_ids -> must return HTTP 400
    explicit_invalid_ids = [
        "%2e%2e",
        "%2e",
        "%2e%2e%5c",
        "bad%5csub",
        "%00",
        "bad%00sub",
        "%20",
        "%20%20",
        "test%20",
        "%20test",
        "%09",
        "%0a",
        "%0d%0a",
        "C:",
        "C:foo",
        "D:",
    ]

    for bad_id in explicit_invalid_ids:
        r_get = client.get(f"/api/tasks/{bad_id}")
        assert r_get.status_code == 400, f"GET {repr(bad_id)} expected 400, got {r_get.status_code}"

        r_code = client.get(f"/api/tasks/{bad_id}/code")
        assert r_code.status_code == 400, f"GET code {repr(bad_id)} expected 400, got {r_code.status_code}"

        r_arch = client.post(f"/api/tasks/{bad_id}/archive")
        assert r_arch.status_code == 400, f"POST archive {repr(bad_id)} expected 400, got {r_arch.status_code}"

        r_rest = client.post(f"/api/tasks/{bad_id}/restore")
        assert r_rest.status_code == 400, f"POST restore {repr(bad_id)} expected 400, got {r_rest.status_code}"

        r_del = client.delete(f"/api/tasks/{bad_id}")
        assert r_del.status_code == 400, f"DELETE {repr(bad_id)} expected 400, got {r_del.status_code}"

    # Group 2: Boundary strings / Windows device names / unicode dots -> must safely return 404 (or 400), NEVER 500
    safe_edge_cases = [
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM9",
        "LPT1",
        "LPT9",
        "CON.txt",
        "NUL.json",
        "con",
        "nul",
        "CON:",
        "AUX:",
        "cache:tasks",
        "test:stream",
        "test::$DATA",
        "%252e%252e",
        "\uff0e\uff0e",
        "\u2025",
        "\u2026",
        "a" * 250,
        "a" * 500,
    ]

    for p in safe_edge_cases:
        r_get = client.get(f"/api/tasks/{p}")
        assert r_get.status_code in (400, 404), f"GET {repr(p)} returned {r_get.status_code}"

        r_code = client.get(f"/api/tasks/{p}/code")
        assert r_code.status_code in (400, 404), f"GET code {repr(p)} returned {r_code.status_code}"

        r_arch = client.post(f"/api/tasks/{p}/archive")
        assert r_arch.status_code in (400, 404), f"POST archive {repr(p)} returned {r_arch.status_code}"

        r_rest = client.post(f"/api/tasks/{p}/restore")
        assert r_rest.status_code in (400, 404), f"POST restore {repr(p)} returned {r_rest.status_code}"

        r_del = client.delete(f"/api/tasks/{p}")
        assert r_del.status_code in (400, 404), f"DELETE {repr(p)} returned {r_del.status_code}"


def test_root_directory_protection_under_deletion_attack():
    """Verify that root cache/tasks directory cannot be deleted or compromised."""
    base_dir = task_manager._BASE_DIR
    assert os.path.isdir(base_dir), "Root tasks directory must exist"

    attack_payloads = [
        "",
        ".",
        "..",
        "...",
        "....",
        "/",
        "\\",
        "//",
        "\\\\",
        "cache/tasks",
        "cache\\tasks",
        base_dir,
        os.path.dirname(base_dir),
        "%2e%2e",
        "%252e%252e",
        "CON",
        "NUL",
        "C:",
        "test:stream",
    ]

    for bad_id in attack_payloads:
        deleted = task_manager.delete_task(bad_id)
        assert deleted is False, f"delete_task should return False for {repr(bad_id)}"
        assert os.path.isdir(base_dir), f"Base directory was deleted by {repr(bad_id)}"


def test_extreme_boundary_step_values(client):
    """Verify extreme boundary step parameter values at route and service level."""
    tid = task_manager.create_task("Boundary step test", "step_session")
    try:
        task_manager.save_code(tid, "print('step 1')", label="v1")

        # Non-positive integers -> 400
        for bad_step in [0, -1, -2, -99999999999999999999999999999999999999999999999999]:
            r = client.get(f"/api/tasks/{tid}/code?step={bad_step}")
            assert r.status_code == 400, f"step={bad_step} expected 400, got {r.status_code}"

        # Valid step -> 200
        r_valid = client.get(f"/api/tasks/{tid}/code?step=1")
        assert r_valid.status_code == 200
        assert r_valid.json()["step"] == 1

        # Non-existent valid positive steps -> 404
        for missing_step in [2, 100, 99999999999999999999999999999999999999999999999999]:
            r_miss = client.get(f"/api/tasks/{tid}/code?step={missing_step}")
            assert r_miss.status_code == 404, f"step={missing_step} expected 404, got {r_miss.status_code}"

        # Non-integer query strings -> 422
        for invalid_param in ["abc", "1.5", "", "NaN", "Infinity", "-Infinity"]:
            r_inv = client.get(f"/api/tasks/{tid}/code?step={invalid_param}")
            assert r_inv.status_code == 422, f"step={invalid_param} expected 422, got {r_inv.status_code}"

        # Service level checks
        assert task_manager.get_code_version(tid, 0) is None
        assert task_manager.get_code_version(tid, -1) is None
        assert task_manager.get_code_version(tid, 10**60) is None
        assert task_manager.get_code_version(tid, False) is None  # type: ignore
        assert task_manager.get_code_version(tid, True) is None   # type: ignore
        assert task_manager.get_code_version(tid, "1") is None    # type: ignore
    finally:
        task_manager.delete_task(tid)


def test_concurrency_and_race_conditions():
    """Verify concurrency safety under parallel version increments and mutations."""
    tid = task_manager.create_task("Concurrency test", "race_session")
    try:
        errors = []

        def worker_save(start_idx):
            for i in range(10):
                try:
                    res = task_manager.save_code(tid, f"x = {start_idx + i}", label=f"v_{start_idx + i}")
                    if res <= 0:
                        errors.append(f"save_code returned non-positive: {res}")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker_save, args=(i * 10,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent save: {errors}"

        # Check versions
        versions = task_manager.get_code_versions(tid)
        assert len(versions) == 30
        steps = [v["step"] for v in versions]
        assert steps == list(range(1, 31))
    finally:
        task_manager.delete_task(tid)


def test_concurrent_api_delete_race(client):
    """Concurrent task API reads/mutations may conflict, but must never produce HTTP 500."""
    tid = task_manager.create_task("Delete race test", "del_session")
    task_manager.save_code(tid, "print('race')", label="v1")

    observed_statuses = []

    def reader():
        for _ in range(40):
            r1 = client.get(f"/api/tasks/{tid}")
            r2 = client.get(f"/api/tasks/{tid}/code")
            observed_statuses.extend([r1.status_code, r2.status_code])
            time.sleep(0.001)

    def archiver():
        for _ in range(25):
            r = client.post(f"/api/tasks/{tid}/archive")
            observed_statuses.append(r.status_code)
            time.sleep(0.001)

    def deleter():
        time.sleep(0.01)
        r = client.delete(f"/api/tasks/{tid}")
        observed_statuses.append(r.status_code)

    threads = [
        threading.Thread(target=reader),
        threading.Thread(target=archiver),
        threading.Thread(target=deleter),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert 500 not in observed_statuses, f"500 observed in race: {observed_statuses}"
    for s in observed_statuses:
        assert s in (200, 404, 409), f"Unexpected status code {s} in delete race"


def test_disk_corruption_resilience(client, tmp_path, monkeypatch):
    """Verify resilience when encountering corrupt JSON or malformed folders on disk."""
    corrupt_id = "corrupt_fixture_task_999"
    corrupt_dir = os.path.join(task_manager._BASE_DIR, corrupt_id)
    os.makedirs(corrupt_dir, exist_ok=True)

    try:
        # Invalid JSON
        with open(os.path.join(corrupt_dir, "task.json"), "w", encoding="utf-8") as f:
            f.write("{broken json!!")

        r_list = client.get("/api/tasks")
        assert r_list.status_code == 200

        r_get = client.get(f"/api/tasks/{corrupt_id}")
        assert r_get.status_code == 404

        # Null fields in task.json
        with open(os.path.join(corrupt_dir, "task.json"), "w", encoding="utf-8") as f:
            f.write('{"task_id": "corrupt_fixture_task_999", "user_goal": null, "updated_at": null}')

        r_list2 = client.get("/api/tasks")
        assert r_list2.status_code == 200
    finally:
        shutil.rmtree(corrupt_dir, ignore_errors=True)
