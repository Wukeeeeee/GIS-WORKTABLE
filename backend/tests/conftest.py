# -*- coding: utf-8 -*-
"""pytest 全局配置：修复 PROJ_LIB / PROJ_DATA 环境冲突（PostGIS 旧 proj.db 覆盖 rasterio）"""
import os
import tempfile

_TEST_WORKSPACE_DB_DIR = None
_PREVIOUS_WORKSPACE_DB_PATH = None
_WORKSPACE_DB_ENV_ACTIVE = False

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)


def pytest_configure(config):
    """Redirect storage_service's import-time DB initialization before test collection."""
    global _TEST_WORKSPACE_DB_DIR, _PREVIOUS_WORKSPACE_DB_PATH, _WORKSPACE_DB_ENV_ACTIVE
    _TEST_WORKSPACE_DB_DIR = tempfile.TemporaryDirectory(prefix="gis-worktable-pytest-db-")
    _PREVIOUS_WORKSPACE_DB_PATH = os.environ.get("GIS_WORKSPACE_DB_PATH")
    os.environ["GIS_WORKSPACE_DB_PATH"] = os.path.join(
        _TEST_WORKSPACE_DB_DIR.name, "workspace.db"
    )
    _WORKSPACE_DB_ENV_ACTIVE = True


def pytest_unconfigure(config):
    """Restore the caller's database setting after the pytest session."""
    global _TEST_WORKSPACE_DB_DIR, _WORKSPACE_DB_ENV_ACTIVE
    if not _WORKSPACE_DB_ENV_ACTIVE:
        return
    if _PREVIOUS_WORKSPACE_DB_PATH is None:
        os.environ.pop("GIS_WORKSPACE_DB_PATH", None)
    else:
        os.environ["GIS_WORKSPACE_DB_PATH"] = _PREVIOUS_WORKSPACE_DB_PATH
    _TEST_WORKSPACE_DB_DIR.cleanup()
    _TEST_WORKSPACE_DB_DIR = None
    _WORKSPACE_DB_ENV_ACTIVE = False
