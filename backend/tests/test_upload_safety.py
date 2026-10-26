"""HTTP regressions for the user-controlled upload filename boundary."""

from pathlib import Path
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import main


@pytest.mark.parametrize("client_filename", [r"..\..\escape.geojson", "../../escape.geojson"])
def test_upload_filename_cannot_escape_upload_directory(tmp_path, monkeypatch, client_filename):
    output_dir = tmp_path / "workspace-output"
    upload_dir = output_dir / "uploads"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(main, "_register_layer", lambda *_args, **_kwargs: {})
    payload = b'{"type":"FeatureCollection","features":[]}'

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (client_filename, payload, "application/geo+json")},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "escape.geojson"
    assert (upload_dir / "escape.geojson").read_bytes() == payload
    assert not (output_dir / "escape.geojson").exists()


@pytest.mark.parametrize(
    ("filename", "payload", "error"),
    [
        ("broken.geojson", b'{"type":', "GeoJSON 文件格式无效"),
        ("not-geojson.json", b'{"type":"NotGeoJSON"}', "文件不是有效的 GeoJSON 格式"),
    ],
)
def test_rejected_geojson_returns_error_and_removes_upload(tmp_path, monkeypatch, filename, payload, error):
    output_dir = tmp_path / "workspace-output"
    upload_dir = output_dir / "uploads"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(main, "_register_layer", lambda *_args, **_kwargs: {})

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (filename, payload, "application/geo+json")},
        )

    assert response.status_code == 200
    assert error in response.json()["error"]
    assert not (upload_dir / filename).exists()


@pytest.mark.parametrize("member", ["../escape.shp", r"..\escape.shp", "C:/escape.shp", "/escape.shp"])
def test_shapefile_zip_rejects_unsafe_member_paths_and_removes_upload(tmp_path, monkeypatch, member):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(member, b"not a shapefile")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("unsafe.zip", archive.getvalue(), "application/zip")},
        )

    assert response.status_code == 200
    assert "不安全的文件路径" in response.json()["error"]
    assert not (upload_dir / "unsafe.zip").exists()


def test_invalid_shapefile_zip_returns_error_and_removes_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("broken.zip", b"not a zip archive", "application/zip")},
        )

    assert response.status_code == 200
    assert "ZIP 文件损坏" in response.json()["error"]
    assert not (tmp_path / "uploads" / "broken.zip").exists()


def test_shapefile_zip_with_multiple_datasets_is_rejected_without_import(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    registered = []
    monkeypatch.setattr(main, "_register_layer", lambda *args, **kwargs: registered.append((args, kwargs)))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("first/first.shp", b"first")
        zf.writestr("second/second.shp", b"second")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("multiple-datasets.zip", archive.getvalue(), "application/zip")},
        )

    assert response.status_code == 200
    assert "多个 Shapefile" in response.json()["error"]
    assert registered == []
    assert not (upload_dir / "multiple-datasets.zip").exists()
