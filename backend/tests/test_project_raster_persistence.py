import io
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.services import ai_service, project_service, tools


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
    return source


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
