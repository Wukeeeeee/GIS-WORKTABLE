import io
import gzip
import hashlib
import json
import multiprocessing
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.services import ai_service, project_service, tools


def _save_project_pause_before_index(project_dir, project_id, ready):
    project_service._PROJECT_DIR = project_dir
    project_service._BLOB_DIR = os.path.join(project_dir, "blobs")
    project_service._INDEX_PATH = os.path.join(project_dir, "index.json")
    project_service._blob_refcount.clear()

    def pause_before_index(_index):
        ready.set()
        while True:
            time.sleep(0.05)

    project_service._save_index = pause_before_index
    project_service.save_project(
        project_id=project_id, name="工程文件已更新", session_id="crash-window", provider="test",
        map_state={}, messages=[], layers=[{"name": "更新图层", "geojson": {
            "type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {"version": "new"},
                "geometry": {"type": "Point", "coordinates": [114.0, 29.0]},
            }],
        }}],
    )


def _use_temp_projects(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()
    uploads = tmp_path / "runtime" / "uploads"
    uploads.mkdir(parents=True)
    source = uploads / "source.png"
    source.write_bytes(b"png-raster-asset")
    monkeypatch.setattr(ai_service, "_TEMP_OUTPUT_DIR", str(uploads.parent))
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(uploads.parent))
    monkeypatch.setattr(tools, "_temp_output_dir", str(uploads.parent))
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    return source


def test_raster_original_path_accepts_nested_rerun_asset_but_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_service, "_TEMP_OUTPUT_DIR", str(tmp_path))
    rerun_dir = tmp_path / "uploads" / "history-reruns" / "run-123"
    rerun_dir.mkdir(parents=True)
    source = rerun_dir / "slope.tif"
    source.write_bytes(b"raster-data")

    resolved = project_service._raster_original_path({
        "source_url": "/output/uploads/history-reruns/run-123/slope.tif",
    })
    escaped = project_service._raster_original_path({
        "source_url": "/output/uploads/history-reruns/../../secret.tif",
    })

    assert resolved == str(source.resolve())
    assert escaped is None


def test_failed_replacement_keeps_existing_project_geojson_intact(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    original_geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"id": "original"},
        "geometry": {"type": "Point", "coordinates": [113.0, 28.0]},
    }]}
    project = project_service.save_project(
        project_id=None, name="已有工程", session_id="save-failure", provider="test",
        map_state={}, messages=[], layers=[{
            "name": "原图层", "geometry_type": "Point", "geojson": original_geojson,
        }],
    )
    original_blob = project_service._load_project_data(project["id"])["layers"][0]["blob"]

    with pytest.raises(ValueError, match="资源不存在"):
        project_service.save_project(
            project_id=project["id"], name="已有工程", session_id="save-failure", provider="test",
            map_state={}, messages=[], layers=[
                {"name": "新图层", "geometry_type": "Point", "geojson": {
                    "type": "FeatureCollection", "features": []}},
                {"name": "新栅格", "geometry_type": "Raster", "raster": {
                    "filename": source.name, "url": "/output/uploads/source.png",
                    "bounds": [100.0, 30.0, 101.0, 31.0]}},
                {"name": "缺失栅格", "geometry_type": "Raster", "raster": {
                    "filename": "missing.png", "url": "/output/uploads/missing.png"}},
            ],
        )

    restored = project_service.load_project(project["id"])
    assert restored["layers"][0]["geojson"] == original_geojson
    assert project_service._blob_get(original_blob) == original_geojson
    assert project_service._blob_refcount == {original_blob: 1}
    assets_dir = tmp_path / "projects" / project["id"] / "assets"
    assert not assets_dir.exists() or list(assets_dir.iterdir()) == []


def test_project_save_rejects_vector_coordinates_outside_wgs84(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    invalid_geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Point", "coordinates": [0, 100]},
    }]}

    with pytest.raises(ValueError, match="WGS-84"):
        project_service.save_project(
            project_id=None, name="越界图层", session_id="invalid-coordinates", provider="test",
            map_state={}, messages=[], layers=[{"name": "越界", "geojson": invalid_geojson}],
        )

    assert project_service.list_projects() == []


def test_project_save_rejects_malformed_vector_positions(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    malformed_geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "LineString", "coordinates": [[1]]},
    }]}

    with pytest.raises(ValueError, match="WGS-84"):
        project_service.save_project(
            project_id=None, name="无效图形", session_id="invalid-geometry", provider="test",
            map_state={}, messages=[], layers=[{"name": "无效线", "geojson": malformed_geojson}],
        )

    assert project_service.list_projects() == []


def test_project_activation_skips_legacy_vector_coordinates_outside_wgs84(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    data = {"layers": [
        {"name": "坏坐标", "geojson": {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [0, 100]},
        }]}},
        {"name": "正常图层", "geojson": {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [120, 30]},
        }]}},
    ], "messages": []}

    result = project_service._activate_project_data("legacy", data, "legacy-session")

    assert result["registration_warnings"] == ["坏坐标"]
    assert list(tools._registered_layers) == ["正常图层"]


def test_project_import_rejects_blob_with_valid_digest_but_invalid_json(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="有效工程", session_id="invalid-blob", provider="test",
        map_state={}, messages=[], layers=[{"name": "有效图层", "geojson": {
            "type": "FeatureCollection", "features": [],
        }}],
    )
    exported = project_service.export_project(saved["id"])
    corrupt_raw = b'{"type": '
    corrupt_blob = hashlib.sha256(corrupt_raw).hexdigest()[:12]
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported), "r") as source, zipfile.ZipFile(archive_bytes, "w") as target:
        for name in source.namelist():
            if name == "project.json" or name.startswith("blobs/"):
                continue
            target.writestr(name, source.read(name))
        project = json.loads(source.read("project.json"))
        project["layers"][0]["blob"] = corrupt_blob
        target.writestr("project.json", json.dumps(project).encode("utf-8"))
        target.writestr(f"blobs/{corrupt_blob}.geojson.gz", gzip.compress(corrupt_raw))

    with pytest.raises(ValueError, match="无效矢量图层数据"):
        project_service.import_project(archive_bytes.getvalue())
    assert [project["id"] for project in project_service.list_projects()] == [saved["id"]]


def test_project_import_rejects_blob_with_invalid_geojson_structure(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    raw = json.dumps({"type": "FeatureCollection", "features": "not-a-list"}).encode("utf-8")
    blob = hashlib.sha256(raw).hexdigest()[:12]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"name": "坏矢量", "layers": [
            {"name": "坏图层", "blob": blob},
        ]}))
        zipped.writestr(f"blobs/{blob}.geojson.gz", gzip.compress(raw))

    with pytest.raises(ValueError, match="无效矢量图层数据"):
        project_service.import_project(archive.getvalue())
    assert project_service.list_projects() == []
    assert not list((tmp_path / "projects").glob("proj_*"))


def test_project_import_rejects_vector_layer_with_missing_blob(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="有效工程", session_id="missing-blob", provider="test",
        map_state={}, messages=[], layers=[{"name": "有效图层", "geojson": {
            "type": "FeatureCollection", "features": [],
        }}],
    )
    exported = project_service.export_project(saved["id"])
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported), "r") as source, zipfile.ZipFile(archive_bytes, "w") as target:
        for name in source.namelist():
            if name.startswith("blobs/"):
                continue
            if name == "project.json":
                project = json.loads(source.read(name))
                project["layers"][0]["blob"] = None
                target.writestr(name, json.dumps(project).encode("utf-8"))
            else:
                target.writestr(name, source.read(name))

    with pytest.raises(ValueError, match="缺少矢量图层数据"):
        project_service.import_project(archive_bytes.getvalue())
    assert [project["id"] for project in project_service.list_projects()] == [saved["id"]]


def test_project_save_rejects_layer_without_vector_raster_or_service_payload(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="缺少矢量、栅格或服务数据"):
        project_service.save_project(
            project_id=None, name="空图层工程", session_id="empty-layer", provider="test",
            map_state={}, messages=[], layers=[{"name": "空图层"}],
        )

    assert project_service.list_projects() == []


def test_failed_atomic_project_write_keeps_old_file_and_releases_new_blob(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    original_geojson = {"type": "FeatureCollection", "features": []}
    project = project_service.save_project(
        project_id=None, name="已有工程", session_id="write-failure", provider="test",
        map_state={}, messages=[], layers=[{"name": "原图层", "geojson": original_geojson}],
    )
    original_blob = project_service._load_project_data(project["id"])["layers"][0]["blob"]
    real_replace = os.replace

    def fail_project_replace(source, destination):
        if destination == project_service._project_path(project["id"]):
            raise OSError("simulated project write failure")
        real_replace(source, destination)

    monkeypatch.setattr(project_service.os, "replace", fail_project_replace)
    with pytest.raises(OSError, match="simulated project write failure"):
        project_service.save_project(
            project_id=project["id"], name="已有工程", session_id="write-failure", provider="test",
            map_state={}, messages=[], layers=[
                {"name": "新图层", "geojson": {
                    "type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                        "geometry": {"type": "Point", "coordinates": [114.0, 29.0]}}]}},
                {"name": "新栅格", "geometry_type": "Raster", "raster": {
                    "filename": source.name, "url": "/output/uploads/source.png",
                    "bounds": [100.0, 30.0, 101.0, 31.0]}},
            ],
        )

    assert project_service.load_project(project["id"])["layers"][0]["geojson"] == original_geojson
    assert project_service._blob_refcount == {original_blob: 1}
    assert not any(name.endswith(".tmp") for name in os.listdir(project_service._project_dir(project["id"])))
    assets_dir = tmp_path / "projects" / project["id"] / "assets"
    assert not assets_dir.exists() or list(assets_dir.iterdir()) == []


def test_project_index_write_failure_reports_saved_project_and_list_recovers(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    monkeypatch.setattr(project_service, "_MAX_PROJECTS", 1)
    first = project_service.save_project(
        project_id=None, name="旧工程", session_id="old-project", provider="test",
        map_state={}, messages=[], layers=[],
    )

    def fail_index_write(_index):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(project_service, "_save_index", fail_index_write)
    saved = project_service.save_project(
        project_id=None, name="索引异常工程", session_id="index-write-failure", provider="test",
        map_state={}, messages=[], layers=[],
    )

    assert saved["id"]
    assert "warning" in saved
    assert project_service._load_project_data(first["id"]) is None
    assert project_service._load_project_data(saved["id"])["name"] == "索引异常工程"
    assert [project["id"] for project in project_service.list_projects()] == [saved["id"]]


def test_process_termination_after_project_replace_rebuilds_index_on_restart(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="旧工程", session_id="crash-window", provider="test",
        map_state={}, messages=[], layers=[{"name": "旧图层", "geojson": {
            "type": "FeatureCollection", "features": [],
        }}],
    )
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    child = context.Process(
        target=_save_project_pause_before_index,
        args=(str(project_service._PROJECT_DIR), saved["id"], ready),
    )
    child.start()
    try:
        assert ready.wait(10), "child should reach the index write after replacing project.json"
        child.terminate()
        child.join(10)
        assert not child.is_alive(), "terminated saver should release its cross-process project lock"

        summaries = project_service.list_projects()
        recovered = project_service._load_project_data(saved["id"])
        assert next(item for item in summaries if item["id"] == saved["id"])["name"] == "工程文件已更新"
        feature = project_service._blob_get(recovered["layers"][0]["blob"])["features"][0]
        assert feature["properties"]["version"] == "new"
    finally:
        if child.is_alive():
            child.terminate()
            child.join(10)


def test_project_rename_survives_index_write_failure_and_list_recovers(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="旧名称", session_id="rename-index-failure", provider="test",
        map_state={}, messages=[], layers=[],
    )

    def fail_index_write(_index):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(project_service, "_save_index", fail_index_write)
    renamed = project_service.rename_project(saved["id"], "新名称")

    assert renamed["name"] == "新名称"
    assert "warning" in renamed
    assert project_service._load_project_data(saved["id"])["name"] == "新名称"
    assert project_service.list_projects()[0]["name"] == "新名称"


def test_project_delete_reports_success_and_rebuildable_index_warning(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="待删除工程", session_id="delete-index-failure", provider="test",
        map_state={}, messages=[], layers=[{
            "name": "点图层", "geojson": {"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Point", "coordinates": [114.0, 29.0]},
            }]},
        }],
    )

    def fail_index_write(_index):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(project_service, "_save_index", fail_index_write)
    with TestClient(main.app) as client:
        response = client.delete(f"/api/projects/{saved['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "warning" in payload
    assert not os.path.exists(project_service._project_dir(saved["id"]))
    assert project_service.list_projects() == []


def test_deleting_active_project_clears_backend_layer_registry(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="当前工程", session_id="active-delete", provider="test",
        map_state={}, messages=[], layers=[{
            "name": "当前图层", "geojson": {"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Point", "coordinates": [114.0, 29.0]},
            }]},
        }],
    )
    project_service.open_project(saved["id"])
    assert tools._active_project_id == saved["id"]
    assert "当前图层" in tools._registered_layers

    project_service.delete_project(saved["id"])

    assert tools._active_project_id is None
    assert tools._registered_layers == {}
    assert tools._pending_layers == []
    assert tools._pending_layer_ops == []


def test_delete_index_failure_keeps_blob_shared_with_remaining_project(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    shared_geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"id": "shared"},
        "geometry": {"type": "Point", "coordinates": [114.0, 29.0]},
    }]}
    layers = [{"name": "共享图层", "geojson": shared_geojson}]
    first = project_service.save_project(
        project_id=None, name="待删除工程", session_id="delete-shared-first", provider="test",
        map_state={}, messages=[], layers=layers,
    )
    second = project_service.save_project(
        project_id=None, name="保留工程", session_id="delete-shared-second", provider="test",
        map_state={}, messages=[], layers=layers,
    )
    blob = project_service._load_project_data(first["id"])["layers"][0]["blob"]
    assert project_service._load_project_data(second["id"])["layers"][0]["blob"] == blob

    def fail_index_write(_index):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(project_service, "_save_index", fail_index_write)
    result = project_service.delete_project(first["id"])

    assert result and "warning" in result
    assert not os.path.exists(project_service._project_dir(first["id"]))
    restored = project_service.load_project(second["id"])
    assert restored["layers"][0]["geojson"] == shared_geojson
    assert project_service._blob_refcount[blob] == 1
    assert [item["id"] for item in project_service.list_projects()] == [second["id"]]


@pytest.mark.parametrize("delete_all", [False, True], ids=["single-delete", "bulk-delete"])
def test_delete_handles_project_with_malformed_layer_entries(tmp_path, monkeypatch, delete_all):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = [project_service.save_project(
        project_id=None, name=f"工程 {index}", session_id=f"malformed-layer-{index}",
        provider="test", map_state={}, messages=[], layers=[],
    ) for index in range(2 if delete_all else 1)]

    damaged = project_service._load_project_data(saved[0]["id"])
    damaged["layers"] = [None]
    project_service._save_project_data(saved[0]["id"], damaged)

    if delete_all:
        project_service.delete_all_projects()
    else:
        project_service.delete_project(saved[0]["id"])

    assert all(not os.path.exists(project_service._project_dir(project["id"])) for project in saved)


def test_delete_all_finishes_before_reporting_rebuildable_index_warning(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = [project_service.save_project(
        project_id=None, name=f"工程 {index}", session_id=f"delete-all-{index}", provider="test",
        map_state={}, messages=[], layers=[],
    ) for index in range(2)]

    def fail_index_write(_index):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(project_service, "_save_index", fail_index_write)
    with TestClient(main.app) as client:
        response = client.delete("/api/projects")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "warning" in payload
    assert all(not os.path.exists(project_service._project_dir(project["id"])) for project in saved)
    assert project_service.list_projects() == []


def test_delete_all_reports_project_directory_removal_failure_and_preserves_blob(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": "still available"},
        "geometry": {"type": "Point", "coordinates": [114.0, 29.0]},
    }]}
    saved = project_service.save_project(
        project_id=None, name="索引外残留工程", session_id="orphan-delete-all", provider="test",
        map_state={}, messages=[], layers=[{"name": "点", "geojson": geojson}],
    )
    removable = project_service.save_project(
        project_id=None, name="仍应继续删除", session_id="delete-all-continues", provider="test",
        map_state={}, messages=[], layers=[],
    )
    orphan_dir = project_service._project_dir(saved["id"])
    blob = project_service._load_project_data(saved["id"])["layers"][0]["blob"]
    blob_path = project_service._blob_path(blob)
    original_rmtree = project_service.shutil.rmtree

    def fail_orphan_removal(path, *args, **kwargs):
        if os.path.normcase(os.path.normpath(path)) == os.path.normcase(os.path.normpath(orphan_dir)):
            raise OSError("simulated orphan directory removal failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(project_service.shutil, "rmtree", fail_orphan_removal)
    with TestClient(main.app) as client:
        response = client.delete("/api/projects")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert "未能删除" in payload["warning"]
    assert os.path.exists(project_service._project_path(saved["id"]))
    assert not os.path.exists(project_service._project_dir(removable["id"]))
    assert [project["id"] for project in project_service.list_projects()] == [saved["id"]]
    assert os.path.exists(blob_path)
    assert project_service.load_project(saved["id"])["layers"][0]["geojson"] == geojson


def test_project_delete_filesystem_failure_preserves_project_blobs(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": "protected"},
        "geometry": {"type": "Point", "coordinates": [114.0, 29.0]},
    }]}
    saved = project_service.save_project(
        project_id=None, name="删除失败应保留", session_id="delete-filesystem-failure", provider="test",
        map_state={}, messages=[], layers=[{"name": "点", "geojson": geojson}],
    )
    blob = project_service._load_project_data(saved["id"])["layers"][0]["blob"]
    blob_path = project_service._blob_path(blob)
    original_rmtree = project_service.shutil.rmtree

    def fail_project_removal(path, *args, **kwargs):
        if os.path.normpath(path) == os.path.normpath(project_service._project_dir(saved["id"])):
            raise OSError("simulated project directory removal failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(project_service.shutil, "rmtree", fail_project_removal)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.delete(f"/api/projects/{saved['id']}")

    assert response.status_code == 500
    assert os.path.exists(project_service._project_path(saved["id"]))
    assert os.path.exists(blob_path)
    assert project_service.load_project(saved["id"])["layers"][0]["geojson"] == geojson


def test_project_delete_reports_orphaned_blob_when_blob_file_is_locked(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="Blob 被占用", session_id="delete-blob-lock", provider="test",
        map_state={}, messages=[], layers=[{"name": "点", "geojson": {
            "type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Point", "coordinates": [114.0, 29.0]},
            }],
        }}],
    )
    blob = project_service._load_project_data(saved["id"])["layers"][0]["blob"]
    blob_path = project_service._blob_path(blob)
    original_remove = project_service.os.remove

    def fail_blob_removal(path, *args, **kwargs):
        if os.path.normcase(os.path.normpath(path)) == os.path.normcase(os.path.normpath(blob_path)):
            raise PermissionError("simulated locked blob")
        return original_remove(path, *args, **kwargs)

    monkeypatch.setattr(project_service.os, "remove", fail_blob_removal)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.delete(f"/api/projects/{saved['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "Blob" in payload["warning"]
    assert not os.path.exists(project_service._project_dir(saved["id"]))
    assert os.path.exists(blob_path)
    assert blob not in project_service._blob_refcount
    assert project_service.list_projects() == []


def test_raster_assets_survive_project_save_export_import_and_restore(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    raster = {
        "filename": source.name,
        "url": "/output/uploads/source.png",
        "bounds": [100.0, 30.0, 101.0, 31.0],
        "width": 2,
        "height": 3,
    }
    with TestClient(main.app) as client:
        save_response = client.post("/api/projects", json={
            "name": "栅格工程", "session_id": "raster-session", "provider": "test",
            "map_state": {}, "messages": [],
            "layers": [{"layer_id": "raster-layer", "filename": "坡度", "geometry_type": "Raster",
                        "visible": False, "style": {"opacity": 0.4}, "raster": raster}],
        })
        assert save_response.status_code == 200
        saved = save_response.json()
        load_response = client.get(f"/api/projects/{saved['id']}")
        assert load_response.status_code == 200
        loaded = load_response.json()
    saved_raster = loaded["layers"][0]["raster"]
    assert saved_raster["url"].startswith(f"/api/projects/{saved['id']}/assets/")
    assert loaded["layers"][0]["visible"] is False
    assert loaded["layers"][0]["style"]["opacity"] == 0.4
    with TestClient(main.app) as client:
        response = client.get(saved_raster["url"])
    assert response.status_code == 200
    assert response.content == source.read_bytes()

    archive = zipfile.ZipFile(io.BytesIO(project_service.export_project(saved["id"])))
    assert any(name.startswith("assets/") for name in archive.namelist())
    imported = project_service.import_project(project_service.export_project(saved["id"]))
    imported_layer = project_service.load_project(imported["id"])["layers"][0]
    assert imported_layer["raster"]["url"].startswith(f"/api/projects/{imported['id']}/assets/")
    assert imported_layer["raster"]["bounds"] == raster["bounds"]
    with TestClient(main.app) as client:
        imported_asset = client.get(imported_layer["raster"]["url"])
    assert imported_asset.status_code == 200
    assert imported_asset.content == source.read_bytes()


def test_project_asset_responses_sandbox_active_content(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    asset = Path(project_service._project_dir("test")) / "assets" / "untrusted.svg"
    asset.parent.mkdir(parents=True)
    asset.write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", encoding="utf-8")
    project_service._save_project_data("test", {
        "layers": [{"name": "untrusted", "raster": {"asset": "untrusted.svg"}}],
    })

    response = TestClient(main.app).get("/api/projects/test/assets/untrusted.svg")

    assert response.status_code == 200
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "<script>" in response.text


def test_preview_only_cog_raster_asset_survives_project_save_and_reload(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="远程 COG 预览", session_id="cog-preview-project", provider="test",
        map_state={}, messages=[], layers=[{
            "name": "影像预览", "geometry_type": "Raster", "raster": {
                "filename": "cog-preview.png", "url": "/output/uploads/source.png",
                "bounds": [100, 30, 101, 31], "width": 512, "height": 256,
                "preview_width": 128, "preview_height": 64, "bands": 4,
                "preview_only": True, "source_reference": "https://example.test/scene.tif",
            },
        }],
    )

    loaded = project_service.load_project(saved["id"])["layers"][0]["raster"]
    asset_path = project_service.get_project_raster_asset(saved["id"], loaded["asset"])

    assert loaded["preview_only"] is True
    assert loaded["preview_width"] == 128 and loaded["preview_height"] == 64
    assert loaded["source_reference"] == "https://example.test/scene.tif"
    assert Path(asset_path).read_bytes() == source.read_bytes()


def test_project_asset_route_honors_byte_ranges_without_gzip(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    asset = Path(project_service._project_dir("test")) / "assets" / "preview.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"0123456789" * 5000)
    project_service._save_project_data("test", {
        "layers": [{"name": "preview", "raster": {"asset": "preview.bin"}}],
    })

    response = TestClient(main.app).get(
        "/api/projects/test/assets/preview.bin",
        headers={"Range": "bytes=2-4", "Accept-Encoding": "gzip"},
    )

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2-4/50000"
    assert response.headers.get("content-encoding") is None
    assert response.content == b"234"


def test_project_asset_route_rejects_symlink_swap_before_deferred_file_open(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="资源竞态工程", session_id="asset-symlink-race", provider="test",
        map_state={}, messages=[], layers=[{"name": "影像", "geometry_type": "Raster", "raster": {
            "filename": source.name, "url": "/output/uploads/source.png", "bounds": [1, 2, 3, 4],
        }}],
    )
    raster = project_service._load_project_data(saved["id"])["layers"][0]["raster"]
    target = Path(project_service.get_project_raster_asset(saved["id"], raster["asset"]))
    outside = tmp_path / "outside-secret.png"
    outside.write_bytes(b"outside secret sentinel")
    original_lookup = project_service.get_project_raster_asset

    def swap_after_asset_lookup(project_id, filename):
        path = original_lookup(project_id, filename)
        if path and os.fspath(path) == os.fspath(target):
            target.unlink()
            try:
                target.symlink_to(outside)
            except OSError as exc:
                pytest.skip(f"local symlink creation unavailable: {exc}")
        return path

    monkeypatch.setattr(project_service, "get_project_raster_asset", swap_after_asset_lookup)
    response = TestClient(main.app).get(f"/api/projects/{saved['id']}/assets/{raster['asset']}")

    assert response.status_code == 403
    assert response.content != outside.read_bytes()


def test_project_asset_route_rejects_assets_directory_symlink_outside_project(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="资源目录链接工程", session_id="assets-directory-link", provider="test",
        map_state={}, messages=[], layers=[{"name": "影像", "geometry_type": "Raster", "raster": {
            "filename": source.name, "url": "/output/uploads/source.png", "bounds": [1, 2, 3, 4],
        }}],
    )
    raster = project_service._load_project_data(saved["id"])["layers"][0]["raster"]
    project_dir = Path(project_service._project_dir(saved["id"]))
    assets_dir = project_dir / "assets"
    assets_dir.rename(tmp_path / "original-assets")
    outside = tmp_path / "outside-assets"
    outside.mkdir()
    sentinel = outside / raster["asset"]
    sentinel.write_bytes(b"outside raster secret sentinel")
    try:
        assets_dir.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"local symlink creation unavailable: {exc}")

    response = TestClient(main.app).get(
        f"/api/projects/{saved['id']}/assets/{raster['asset']}"
    )

    assert response.status_code in {403, 404}
    assert response.content != sentinel.read_bytes()


def test_project_save_does_not_delete_files_through_assets_directory_symlink(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="资源清理链接工程", session_id="assets-cleanup-link", provider="test",
        map_state={}, messages=[], layers=[{"name": "影像", "geometry_type": "Raster", "raster": {
            "filename": source.name, "url": "/output/uploads/source.png", "bounds": [1, 2, 3, 4],
        }}],
    )
    project_dir = Path(project_service._project_dir(saved["id"]))
    assets_dir = project_dir / "assets"
    assets_dir.rename(tmp_path / "original-assets")
    outside = tmp_path / "outside-assets"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_bytes(b"keep unrelated external file")
    try:
        assets_dir.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"local symlink creation unavailable: {exc}")

    project_service.save_project(
        project_id=saved["id"], name="移除栅格", session_id="assets-cleanup-link", provider="test",
        map_state={}, messages=[], layers=[],
    )

    assert sentinel.read_bytes() == b"keep unrelated external file"


def test_interpolation_raster_survives_project_save_load_and_reanalysis(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    point_layer = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"value": 1}, "geometry": {"type": "Point", "coordinates": [116.0, 39.0]}},
        {"type": "Feature", "properties": {"value": 3}, "geometry": {"type": "Point", "coordinates": [116.1, 39.0]}},
        {"type": "Feature", "properties": {"value": 4}, "geometry": {"type": "Point", "coordinates": [116.0, 39.1]}},
    ]}
    tools._register_layer("插值输入点", point_layer)

    interpolation_result = tools.spatial_interpolate.invoke({
        "layer_name": "插值输入点", "field": "value", "resolution": 16,
    })

    assert "已生成" in interpolation_result
    output_op = next(op for op in tools._pending_layer_ops if op.get("raster"))
    output_name = output_op["layer_name"]
    project = project_service.save_project(
        project_id=None, name="插值结果往返", session_id="interpolation-roundtrip", provider="test",
        map_state={}, messages=[], layers=[{
            "filename": output_name, "name": output_name, "geometry_type": "Raster",
            "raster": output_op["raster"], "visible": True,
        }],
    )
    restored = project_service.load_project(project["id"])
    restored_layer = restored["layers"][0]
    restored_raster = restored_layer["raster"]
    assert restored_raster["crs"] == "EPSG:4326"
    assert restored_raster["value_units"] is None
    assert any("外推" in warning for warning in restored_raster["quality_warnings"])
    assert restored_raster["source_url"].startswith(f"/api/projects/{project['id']}/assets/")

    tools.reset_registered_layers(restored["layers"])
    followup_result = tools.raster_resample.invoke({
        "layer_name": restored_layer["name"], "scale_factor": 2, "method": "bilinear",
    })

    assert "重采样完成" in followup_result
    followup_ops = [op for op in tools._pending_layer_ops if op.get("action") == "dem_result"]
    assert followup_ops and followup_ops[0].get("raster")
    with TestClient(main.app) as client:
        saved_preview = client.get(restored_raster["url"])
        saved_source = client.get(restored_raster["source_url"])
    assert saved_preview.status_code == 200
    assert saved_source.status_code == 200
    assert saved_source.headers.get("content-type", "").startswith("image/tiff")


def test_autosave_includes_uploaded_raster_layers(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {
        "auto-raster-session": [{"role": "user", "content": "保存栅格分析"}],
    })
    monkeypatch.setattr(tools, "_registered_layers", {})
    result = project_service.auto_save(
        session_id="auto-raster-session",
        provider="test",
        layer_assignments=[{
            "layer_id": "raster-auto",
            "name": "高程",
            "names": ["raster-auto", "高程"],
            "visible": True,
            "raster": {"filename": source.name, "url": "/output/uploads/source.png",
                       "bounds": [100.0, 30.0, 101.0, 31.0], "width": 2, "height": 3},
        }],
    )
    saved_layer = project_service.load_project(result["id"])["layers"][0]
    assert saved_layer["name"] == "高程"
    assert saved_layer["raster"]["asset"]


def test_autosave_keeps_raster_when_only_registry_name_is_sent(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {
        "canonical-raster-session": [{"role": "user", "content": "保存栅格"}],
    })
    monkeypatch.setattr(tools, "_registered_layers", {})
    raster = {"filename": source.name, "url": "/output/uploads/source.png",
              "bounds": [100.0, 30.0, 101.0, 31.0], "width": 2, "height": 3}

    result = project_service.auto_save(
        session_id="canonical-raster-session",
        layer_assignments=[{"registry_name": "elevation", "raster": raster, "order": 0}],
    )

    saved_layers = project_service.load_project(result["id"])["layers"]
    assert len(saved_layers) == 1
    assert saved_layers[0]["name"] == "elevation"
    assert saved_layers[0]["raster"]["asset"]


def _upload_real_raster(tmp_path, monkeypatch):
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    _use_temp_projects(tmp_path, monkeypatch)
    data = io.BytesIO()
    with rasterio.open(data, 'w', driver='GTiff', width=4, height=4, count=1, dtype='float32',
                       crs='EPSG:4326', transform=from_bounds(100, 30, 101, 31, 4, 4)) as dataset:
        dataset.write(np.arange(1, 17, dtype='float32').reshape(4, 4), 1)
    client = TestClient(main.app)
    result = client.post('/api/upload', files={'file': ('original#1.tif', data.getvalue(), 'image/tiff')}).json()
    assert result.get('registration_token'), result
    assert result['raster_info']['crs'] == 'EPSG:4326'
    assert result['raster_info']['source_width'] == 4
    assert result['raster_info']['pixel_units'] == 'degree'
    assert '单位未在文件元数据中标注' in result['raster_info']['quality_warnings'][0]
    saved = client.post('/api/projects', json={
        'name': '原始栅格工程', 'session_id': 'raw-session', 'provider': 'test', 'map_state': {}, 'messages': [],
        'layers': [{'filename': '自定义高程', 'raster': result['raster_info'], 'geometry_type': 'Raster'}],
    }).json()
    return client, result, saved, data.getvalue()


def test_original_raster_survives_import_without_runtime_or_original_project_files(tmp_path, monkeypatch):
    client, uploaded, saved, original = _upload_real_raster(tmp_path, monkeypatch)
    runtime = Path(tools._temp_output_dir) / 'uploads'
    (runtime / uploaded['raster_info']['source_filename']).unlink()
    (runtime / uploaded['raster_info']['filename']).unlink()
    exported = project_service.export_project(saved['id'])
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        raw_members = [name for name in archive.namelist() if name.endswith('.tif')]
        assert len(raw_members) == 1
        assert archive.read(raw_members[0]) == original
    imported = project_service.import_project(exported)
    project_service.delete_project(saved['id'])
    response = client.get('/api/projects/' + imported['id'])
    assert response.status_code == 200
    layer = response.json()['layers'][0]
    assert layer['geojson'] is None and layer['registration_token']
    restored_raster = layer['raster']
    assert restored_raster['crs'] == uploaded['raster_info']['crs']
    assert restored_raster['source_width'] == uploaded['raster_info']['source_width']
    assert restored_raster['source_height'] == uploaded['raster_info']['source_height']
    assert restored_raster['pixel_units'] == uploaded['raster_info']['pixel_units']
    assert restored_raster['quality_warnings'] == uploaded['raster_info']['quality_warnings']
    assert client.get(layer['raster']['source_url']).content == original
    located = tools._find_uploaded_tif('自定义高程')
    assert os.path.commonpath([located, project_service._decrypted_asset_root()]) == project_service._decrypted_asset_root()
    result = tools.raster_calculator.invoke({'layer_name': '自定义高程', 'expression': 'B1*2'})
    assert '范围 [2.00, 32.00]' in result
    calc_op = tools._pending_layer_ops[-1]
    assert (runtime / calc_op['raster']['filename']).exists()


def test_derived_dem_layer_survives_project_restore_and_can_be_reanalyzed(tmp_path, monkeypatch):
    client, uploaded, _, _ = _upload_real_raster(tmp_path, monkeypatch)
    result = tools.dem_analysis.invoke({'layer_name': uploaded['name'], 'analysis': 'slope'})
    assert 'GeoTIFF' in result and '可继续分析' in result
    op = next(op for op in tools._pending_layer_ops if op.get('action') == 'dem_result')
    layer_name = op['layer_name']
    # The authoritative source path comes from the backend registry, not the URL's display form.
    source_path = Path(tools._registered_layers[layer_name]['raster_source_path'])
    assert source_path.is_file()

    saved = client.post('/api/projects', json={
        'name': '派生地形工程', 'session_id': 'derived-session', 'provider': 'test',
        'map_state': {}, 'messages': [],
        'layers': [{'filename': layer_name, 'geometry_type': 'Raster', 'crs': op['crs'],
                    'source': 'ai', 'raster': op['raster']}],
    }).json()
    assert saved.get('id'), saved
    restored = client.get('/api/projects/' + saved['id'])
    assert restored.status_code == 200
    layer = restored.json()['layers'][0]
    assert layer['name'] == layer_name
    restored_raster = layer['raster']
    for key in ('crs', 'source_width', 'source_height', 'bands', 'pixel_size',
                'pixel_units', 'value_units', 'source_label', 'source_reference',
                'processing', 'valid_pixel_ratio', 'quality_warnings'):
        assert restored_raster.get(key) == op['raster'].get(key)
    assert layer['raster']['source_asset'].endswith('.tif')
    assert client.get(layer['raster']['url']).status_code == 200
    assert client.get(layer['raster']['source_url']).content == source_path.read_bytes()

    project_service.activate_project(saved['id'])
    restored_source = tools._find_uploaded_tif(layer_name)
    assert restored_source and os.path.commonpath([restored_source, project_service._decrypted_asset_root()]) == project_service._decrypted_asset_root()
    follow_up = tools.raster_calculator.invoke({'layer_name': layer_name, 'expression': 'B1*2'})
    assert '结果栅格' in follow_up and '已上图' in follow_up


def test_raster_tool_outputs_do_not_modify_project_assets(tmp_path, monkeypatch):
    client, uploaded, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    client.get('/api/projects/' + saved['id'])
    assets = Path(project_service._project_dir(saved['id'])) / 'assets'
    before = {file.name: file.read_bytes() for file in assets.iterdir()}
    result = tools.raster_resample.invoke({'layer_name': '自定义高程', 'scale_factor': 2, 'method': 'nearest'})
    assert '重采样完成' in result
    assert {file.name: file.read_bytes() for file in assets.iterdir()} == before
    assert list((Path(tools._temp_output_dir) / 'uploads').glob('*_重采样.tif'))


def test_failed_raster_replacement_preserves_original_assets(tmp_path, monkeypatch):
    _, _, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    loaded = project_service.load_project(saved['id'])
    assets = Path(project_service._project_dir(saved['id'])) / 'assets'
    before = {file.name: file.read_bytes() for file in assets.iterdir()}
    broken = dict(loaded['layers'][0]['raster'], source_asset='missing.tif')
    with pytest.raises(ValueError, match='原始数据资源不存在'):
        project_service.save_project(saved['id'], '失败替换', 'raw-session', 'test', {}, [], [{'name': 'bad', 'raster': broken}])
    assert {file.name: file.read_bytes() for file in assets.iterdir()} == before
    assert project_service.load_project(saved['id'])['layers'][0]['name'] == '自定义高程'


def test_activation_warns_and_skips_raster_when_original_asset_is_missing(tmp_path, monkeypatch):
    _, _, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    loaded = project_service.load_project(saved['id'])
    raw = project_service._project_raster_path(saved['id'], loaded['layers'][0]['raster']['source_asset'])
    Path(raw).unlink()
    tools._active_project_id = 'previous-project'
    monkeypatch.setitem(ai_service.conversation_history, 'raw-session', [{'role': 'user', 'content': 'previous'}])
    activated = project_service.activate_project(saved['id'])
    assert activated['registration_warnings'] == ['自定义高程']
    assert '自定义高程' not in tools._registered_layers
    assert tools._active_project_id == saved['id']
    assert ai_service.conversation_history['raw-session'] == []


def test_renamed_raster_autosaves_once_and_keeps_raw_data(tmp_path, monkeypatch):
    client, _, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    loaded = client.get('/api/projects/' + saved['id']).json()
    raster = loaded['layers'][0]['raster']
    result = project_service.auto_save('raw-session', project_id=saved['id'], layer_assignments=[{
        'name': '重命名高程', 'registry_name': '自定义高程', 'names': ['自定义高程', '重命名高程'], 'raster': raster,
    }])
    layers = project_service.load_project(result['id'])['layers']
    assert len(layers) == 1 and layers[0]['name'] == '重命名高程'
    assert layers[0]['raster']['source_asset'] == raster['source_asset']
    assert layers[0]['geojson'] is None


def test_active_project_lookup_never_falls_back_to_another_runtime_raster(tmp_path, monkeypatch):
    client, uploaded, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    assert tools._find_uploaded_tif(uploaded['name'])
    client.get('/api/projects/' + saved['id'])
    assert tools._find_uploaded_tif(uploaded['name']) is None
    assert tools._find_uploaded_tif('自定义高程')


def test_legacy_lookup_does_not_match_only_a_substring(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    path = Path(tools._temp_output_dir) / 'uploads' / 'dem_other.tif'
    path.write_bytes(b'not selected')
    assert tools._find_uploaded_tif('dem') is None
    assert tools._find_uploaded_tif('dem_other') == str(path)


def test_export_refuses_to_silently_omit_a_missing_original(tmp_path, monkeypatch):
    _, _, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    raster = project_service.load_project(saved['id'])['layers'][0]['raster']
    Path(project_service._project_raster_path(saved['id'], raster['source_asset'])).unlink()
    with pytest.raises(ValueError, match='缺失'):
        project_service.export_project(saved['id'])


@pytest.mark.parametrize('source_asset', ['../outside.tif', 'C:outside.tif', 'missing.tif'])
def test_import_rejects_unsafe_or_missing_original_assets(tmp_path, monkeypatch, source_asset):
    import json
    _use_temp_projects(tmp_path, monkeypatch)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('project.json', json.dumps({'layers': [{'name': 'bad', 'raster': {
            'asset': 'preview.png', 'source_asset': source_asset, 'bounds': [1, 2, 3, 4],
        }}]}))
        zipped.writestr('assets/preview.png', b'preview')
    with pytest.raises(ValueError, match='栅格资源'):
        project_service.import_project(archive.getvalue())
    assert project_service.list_projects() == []
    assert not list((tmp_path / 'projects').glob('proj_*'))


@pytest.mark.parametrize('entries', [
    [('assets', b'file entry'), ('assets/preview.png', b'child entry')],
    [('assets/preview.png', b'child entry'), ('assets', b'file entry')],
])
def test_import_rejects_archive_file_directory_prefix_conflict(tmp_path, monkeypatch, entries):
    _use_temp_projects(tmp_path, monkeypatch)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as zipped:
        for name, content in entries:
            zipped.writestr(name, content)

    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.post('/api/projects/import', files={
        'file': ('conflicting.giswork', archive.getvalue(), 'application/zip'),
    })

    assert response.status_code == 400
    assert '路径冲突' in response.json()['detail']
    assert project_service.list_projects() == []
    assert not list((tmp_path / 'projects').glob('proj_*'))


def test_import_rejects_archive_unicode_normalization_path_aliases(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    archive = io.BytesIO()
    composed = "é.txt"
    decomposed = "e\u0301.txt"
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('project.json', '{"name":"Unicode aliases","layers":[]}')
        zipped.writestr('assets/' + composed, b'composed')
        zipped.writestr('assets/' + decomposed, b'decomposed')

    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.post('/api/projects/import', files={
        'file': ('unicode-aliases.giswork', archive.getvalue(), 'application/zip'),
    })

    assert response.status_code == 400
    assert '重复的文件路径' in response.json()['detail']
    assert project_service.list_projects() == []
    assert not list((tmp_path / 'projects').glob('proj_*'))
