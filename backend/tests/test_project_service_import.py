"""Subprocess-isolated regression test for project_service import safety.

Ensures importing backend.services.project_service does not access the encrypted
store or invoke read_bytes at import time when keyring may be unavailable.
"""

import json
import os
import subprocess
import sys
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_project_service_import_without_store_access(tmp_path):
    """Importing project_service must not call read_bytes or touch keyring/credentials."""
    worker_script = """
import sys
import json

calls = []

def stub_read_bytes(*args, **kwargs):
    calls.append({"args": [str(a) for a in args], "kwargs": {k: str(v) for k, v in kwargs.items()}})
    raise RuntimeError("SECURITY ERROR: read_bytes was called during import!")

# Inject stub into backend.services.local_encryption before importing project_service
import backend.services.local_encryption as local_encryption
local_encryption.read_bytes = stub_read_bytes

# Disable keyring access to assert system credentials are never accessed
def failing_keyring(*args, **kwargs):
    raise RuntimeError("SECURITY ERROR: Keyring accessed during import!")

local_encryption.secure_keyring = failing_keyring
local_encryption._master_key = failing_keyring

# Now import project_service
try:
    import backend.services.project_service as project_service
    status = {
        "success": True,
        "calls": calls,
        "refcount": project_service._blob_refcount,
    }
except Exception as exc:
    status = {
        "success": False,
        "error": f"{type(exc).__name__}: {exc}",
        "calls": calls,
    }

print("RESULT:" + json.dumps(status))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = REPO_ROOT
    temp_dir = str(tmp_path)
    env["TEMP"] = temp_dir
    env["TMP"] = temp_dir

    result = subprocess.run(
        [sys.executable, "-c", worker_script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"Subprocess failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    result_line = next((line for line in result.stdout.splitlines() if line.startswith("RESULT:")), None)
    assert result_line is not None, f"No RESULT line found in stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    payload = json.loads(result_line[len("RESULT:"):])
    assert payload["success"] is True, f"Import failed: {payload}"
    assert payload["calls"] == [], f"read_bytes stub was called: {payload['calls']}"
    assert payload["refcount"] == {}, "Expected _blob_refcount to start empty without import-time scanning"


def test_project_service_import_stub_traps_read_bytes(tmp_path):
    """Verify our test harness stub actively traps and fails if read_bytes is invoked."""
    worker_script = """
import sys
import json

def stub_read_bytes(*args, **kwargs):
    raise RuntimeError("SECURITY ERROR: read_bytes was called!")

import backend.services.local_encryption as local_encryption
local_encryption.read_bytes = stub_read_bytes

try:
    local_encryption.read_bytes("dummy_path", "test_context")
    status = {"trapped": False}
except RuntimeError as exc:
    status = {"trapped": True, "error": str(exc)}

print("RESULT:" + json.dumps(status))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = REPO_ROOT
    temp_dir = str(tmp_path)
    env["TEMP"] = temp_dir
    env["TMP"] = temp_dir

    result = subprocess.run(
        [sys.executable, "-c", worker_script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Subprocess failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    result_line = next((line for line in result.stdout.splitlines() if line.startswith("RESULT:")), None)
    assert result_line is not None
    payload = json.loads(result_line[len("RESULT:"):])
    assert payload["trapped"] is True


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__]))
