# -*- coding: utf-8 -*-
"""pytest 全局配置：修复 PROJ_LIB / PROJ_DATA 环境冲突（PostGIS 旧 proj.db 覆盖 rasterio）"""
import os
import sys
import threading
import tempfile

_TEST_WORKSPACE_DB_DIR = None
_PREVIOUS_WORKSPACE_DB_PATH = None
_WORKSPACE_DB_ENV_ACTIVE = False
_ARROW_MODULE = None
_PREVIOUS_ARROW_THREAD_COUNTS = None
_PROJ_ENV_KEYS = ("PROJ_LIB", "PROJ_DATA")
_PREVIOUS_PROJ_ENV = {name: os.environ.get(name) for name in _PROJ_ENV_KEYS}
_THREAD_LIMIT_ENV_KEYS = (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
)
_PREVIOUS_THREAD_LIMIT_ENV = {
    name: os.environ.get(name) for name in _THREAD_LIMIT_ENV_KEYS
}
for _proj_env_name in _PROJ_ENV_KEYS:
    os.environ.pop(_proj_env_name, None)
for _thread_env_name in _THREAD_LIMIT_ENV_KEYS:
    os.environ[_thread_env_name] = "1"

import pytest


def _isolate_tool_runtime(monkeypatch, tmp_path):
    """Replace tool runtime, task-manager state, and loaded aliases for one test."""
    from backend.services import task_manager, tools
    from backend.services.tool_modules import runtime

    output_dir = str(tmp_path / "output")
    workspace_dir = str(tmp_path / "workspace")
    isolated_state = {
        "_registered_layers": {},
        "_pending_layers": [],
        "_pending_layer_ops": [],
        "_pending_images": [],
        "_pending_qa_warnings": [],
        "_pending_aoi_suggestions": {},
        "_pending_heatmap": {"latest": None},
        "_clear_layers_flag": False,
        "_current_amap_key": "",
        "_search_call_count": 0,
        "_domain_fail": {},
        "_search_cache": {},
        "_search_last_hit": {},
        "_exec_call_count": 0,
        "_exec_log": [],
        "_temp_output_dir": output_dir,
        "_workspace_dir": workspace_dir,
        "_raster_output_scope": threading.local(),
        "_active_project_id": None,
        "_current_task_id": "",
        "_last_user_message": "",
        "_current_run_id": "",
        "_conversation_context": "",
        "_session_locks": {},
    }
    mutable_names = {
        name for name in isolated_state
        if isinstance(getattr(runtime, name), (dict, list, threading.local))
    }
    original_values = {name: getattr(runtime, name) for name in mutable_names}
    aliases = []
    seen_modules = set()
    for module in tuple(sys.modules.values()):
        if module is None or id(module) in seen_modules or module in (runtime, tools):
            continue
        seen_modules.add(id(module))
        namespace = getattr(module, "__dict__", {})
        for name in mutable_names:
            if namespace.get(name) is original_values[name]:
                aliases.append((module, name, isolated_state[name]))

    for path in (tmp_path / "output", tmp_path / "workspace", tmp_path / "tasks"):
        path.mkdir(parents=True, exist_ok=True)
    with runtime._state_lock, runtime._session_locks_guard:
        for name, value in isolated_state.items():
            monkeypatch.setattr(tools, name, value)
        for module, name, value in aliases:
            monkeypatch.setattr(module, name, value)
    with task_manager._lock:
        monkeypatch.setattr(task_manager, "_BASE_DIR", str(tmp_path / "tasks"))
        monkeypatch.setattr(task_manager, "_tasks", {})
        monkeypatch.setattr(task_manager, "_session_active", {})


@pytest.fixture
def tool_runtime_isolator():
    """Expose the shared runtime isolator for suites with a custom output root."""
    return _isolate_tool_runtime


@pytest.fixture
def isolated_tool_runtime(monkeypatch, tmp_path, tool_runtime_isolator):
    tool_runtime_isolator(monkeypatch, tmp_path)
    return tool_runtime_isolator

def pytest_configure(config):
    """Redirect storage_service's import-time DB initialization before test collection."""
    global _TEST_WORKSPACE_DB_DIR, _PREVIOUS_WORKSPACE_DB_PATH, _WORKSPACE_DB_ENV_ACTIVE
    global _ARROW_MODULE, _PREVIOUS_ARROW_THREAD_COUNTS
    _TEST_WORKSPACE_DB_DIR = tempfile.TemporaryDirectory(prefix="gis-worktable-pytest-db-")
    _PREVIOUS_WORKSPACE_DB_PATH = os.environ.get("GIS_WORKSPACE_DB_PATH")
    os.environ["GIS_WORKSPACE_DB_PATH"] = os.path.join(
        _TEST_WORKSPACE_DB_DIR.name, "workspace.db"
    )
    _WORKSPACE_DB_ENV_ACTIVE = True
    try:
        import pyarrow
    except ImportError:
        _ARROW_MODULE = None
        _PREVIOUS_ARROW_THREAD_COUNTS = None
    else:
        if callable(getattr(pyarrow, "set_cpu_count", None)) and callable(
            getattr(pyarrow, "set_io_thread_count", None)
        ):
            _ARROW_MODULE = pyarrow
            _PREVIOUS_ARROW_THREAD_COUNTS = (pyarrow.cpu_count(), pyarrow.io_thread_count())
            pyarrow.set_cpu_count(1)
            pyarrow.set_io_thread_count(1)


def pytest_unconfigure(config):
    """Restore caller environment and clean the temporary workspace DB."""
    global _TEST_WORKSPACE_DB_DIR, _WORKSPACE_DB_ENV_ACTIVE
    if _WORKSPACE_DB_ENV_ACTIVE:
        if _PREVIOUS_WORKSPACE_DB_PATH is None:
            os.environ.pop("GIS_WORKSPACE_DB_PATH", None)
        else:
            os.environ["GIS_WORKSPACE_DB_PATH"] = _PREVIOUS_WORKSPACE_DB_PATH
        _TEST_WORKSPACE_DB_DIR.cleanup()
        _TEST_WORKSPACE_DB_DIR = None
        _WORKSPACE_DB_ENV_ACTIVE = False

    if _ARROW_MODULE is not None and _PREVIOUS_ARROW_THREAD_COUNTS is not None:
        _ARROW_MODULE.set_cpu_count(_PREVIOUS_ARROW_THREAD_COUNTS[0])
        _ARROW_MODULE.set_io_thread_count(_PREVIOUS_ARROW_THREAD_COUNTS[1])

    for previous_env in (_PREVIOUS_PROJ_ENV, _PREVIOUS_THREAD_LIMIT_ENV):
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
