# -*- coding: utf-8 -*-
"""测试 StorageService：数据库自愈、相对路径转换、产物登记与孤立隔离"""

import os
import pytest
from backend.services import storage_service as SS


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    test_db = str(tmp_path / "test_workspace.db")
    SS.set_db_path(test_db)
    yield test_db
    SS.set_db_path(None)


def test_db_init_and_stats():
    stats = SS.get_db_stats()
    assert stats["exists"] is True
    assert stats["runs_count"] == 0
    assert stats["artifacts_count"] == 0


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


def test_run_isolation():
    # 验证 run_1 的产物不会漏给 run_2
    SS.record_run_start("run_1", "sess", "user 1")
    SS.register_run_artifact("run_1", "a1", "f1.png", "output/f1.png")

    SS.record_run_start("run_2", "sess", "user 2")
    arts_2 = SS.get_run_artifacts("run_2")
    assert len(arts_2) == 0
