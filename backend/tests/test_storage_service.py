# -*- coding: utf-8 -*-
"""测试 StorageService：数据库自愈、相对路径转换、产物登记与孤立隔离"""

import os
import tempfile
import pytest

# storage_service initializes its default database on import. Keep that import
# side effect out of the repository's persistent workspace even in this test.
_IMPORT_DB_DIR = tempfile.TemporaryDirectory(prefix="gis-storage-test-import-")
_PREVIOUS_DB_PATH_ENV = os.environ.get("GIS_WORKSPACE_DB_PATH")
os.environ["GIS_WORKSPACE_DB_PATH"] = os.path.join(_IMPORT_DB_DIR.name, "bootstrap.db")
try:
    from backend.services import storage_service as SS
finally:
    if _PREVIOUS_DB_PATH_ENV is None:
        os.environ.pop("GIS_WORKSPACE_DB_PATH", None)
    else:
        os.environ["GIS_WORKSPACE_DB_PATH"] = _PREVIOUS_DB_PATH_ENV


def _isolate_db_path(monkeypatch, test_db):
    monkeypatch.setattr(SS, "_CUSTOM_DB_PATH", [None])
    SS.set_db_path(test_db)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_workspace.db")
    _isolate_db_path(monkeypatch, test_db)
    yield test_db


def test_isolated_db_switch_restores_path_reference(temp_db):
    original_path_ref = SS._CUSTOM_DB_PATH
    original_path = original_path_ref[0]
    patcher = pytest.MonkeyPatch()
    nested_db = os.path.join(os.path.dirname(temp_db), "nested_workspace.db")
    try:
        _isolate_db_path(patcher, nested_db)
        assert SS.get_db_path() == nested_db
        assert SS._CUSTOM_DB_PATH is not original_path_ref
    finally:
        patcher.undo()

    assert SS._CUSTOM_DB_PATH is original_path_ref
    assert SS._CUSTOM_DB_PATH[0] == original_path
    assert SS.get_db_path() == temp_db


def test_db_init_and_stats():
    stats = SS.get_db_stats()
    assert stats["exists"] is True
    assert stats["runs_count"] == 0
    assert stats["artifacts_count"] == 0


def test_pytest_session_database_is_redirected_from_repository():
    configured_path = os.environ.get("GIS_WORKSPACE_DB_PATH")
    assert configured_path
    assert os.path.abspath(configured_path) != os.path.abspath(SS._DEFAULT_DB_PATH)


def test_path_normalization():
    root = SS.get_repo_root()
    test_abs = os.path.join(root, "temp_output", "buffer.geojson")
    rel = SS.to_relative_path(test_abs)
    assert rel == "temp_output/buffer.geojson"
    assert SS.to_absolute_path(rel) == os.path.normpath(test_abs)


def test_run_and_artifact_lifecycle(tmp_path):
    run_id = "run_test_001"
    assert SS.record_run_start(run_id, "session_1", "提取南京市边界", "task_1")

    # 创建物理文件
    f = tmp_path / "nanjing.geojson"
    f.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    assert SS.register_run_artifact(
        run_id=run_id,
        artifact_id="art_001",
        filename="nanjing.geojson",
        file_path=str(f),
        file_type="layer",
        qa_status="PASS",
        qa_details="几何检查通过"
    )

    artifacts = SS.get_run_artifacts(run_id)
    assert len(artifacts) == 1
    assert artifacts[0]["filename"] == "nanjing.geojson"
    assert artifacts[0]["exists"] is True
    assert artifacts[0]["qa_status"] == "PASS"

    # 完成 run
    assert SS.record_run_finish(run_id, "已为您提取南京市边界", "success", "PASS")
    stats = SS.get_db_stats()
    assert stats["runs_count"] == 1
    assert stats["artifacts_count"] == 1
    assert SS.record_run_finish("unknown_run", "无对应执行轮次", "success", "PASS") is False


def test_missing_or_empty_artifacts_cannot_be_marked_pass(tmp_path):
    run_id = "run_missing_artifact"
    assert SS.record_run_start(run_id, "session_1", "测试失败产物登记")

    missing = tmp_path / "missing.png"
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")

    # 登记动作本身成功，但事实台账必须明确记为失败，不能冒充已生成。
    assert SS.register_run_artifact(run_id, "art_missing", "missing.png", str(missing))
    assert SS.register_run_artifact(run_id, "art_empty", "empty.png", str(empty))
    artifacts = SS.get_run_artifacts(run_id)
    assert [a["qa_status"] for a in artifacts] == ["FAIL", "FAIL"]
    assert all(not a["exists"] for a in artifacts)
    assert all("不存在或为空" in a["qa_details"] for a in artifacts)


def test_run_isolation():
    # 验证 run_1 的产物不会漏给 run_2
    SS.record_run_start("run_1", "sess", "user 1")
    SS.register_run_artifact("run_1", "a1", "f1.png", "output/f1.png")
    assert SS.get_run_artifacts("run_1")[0]["qa_status"] == "FAIL"

    SS.record_run_start("run_2", "sess", "user 2")
    arts_2 = SS.get_run_artifacts("run_2")
    assert len(arts_2) == 0
