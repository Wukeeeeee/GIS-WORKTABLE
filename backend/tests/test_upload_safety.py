"""HTTP regressions for the user-controlled upload filename boundary."""

from pathlib import Path
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.services import tools


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


@pytest.mark.parametrize("client_filename", [
    "COM¹.geojson", "COM².geojson", "COM³.geojson",
    "LPT¹.geojson", "LPT².geojson", "LPT³.geojson",
])
def test_upload_rejects_superscript_windows_device_names_before_file_creation(
    tmp_path, monkeypatch, client_filename
):
    output_dir = tmp_path / "workspace-output"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(main, "_register_layer", lambda *_args, **_kwargs: pytest.fail("invalid filename must not register"))
    payload = b'{"type":"FeatureCollection","features":[]}'

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (client_filename, payload, "application/geo+json")},
        )

    assert response.status_code == 200
    assert response.json()["error"] == "无效的上传文件名"
    assert not (output_dir / "uploads").exists()


@pytest.mark.parametrize("emoji_count", [62, 125])
def test_upload_rejects_unicode_filename_exceeding_portable_path_component_limit(tmp_path, monkeypatch, emoji_count):
    output_dir = tmp_path / "workspace-output"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    filename = "😀" * emoji_count + ".geojson"
    assert len(filename) < 240

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (filename, b'{"type":"FeatureCollection","features":[]}', "application/geo+json")},
        )

    assert response.status_code == 200
    assert response.json()["error"] == "无效的上传文件名"
    assert not (output_dir / "uploads").exists()


def test_upload_avoids_unicode_normalization_alias_of_registered_layer(tmp_path, monkeypatch):
    output_dir = tmp_path / "workspace-output"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(tools, "_registered_layers", {})
    tools._register_layer("é.geojson", {"type": "FeatureCollection", "features": []})

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={
                "file": (
                    "e\u0301.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/geo+json",
                ),
            },
        )

    assert response.status_code == 200
    assert response.json()["name"] == "e\u0301_1.geojson"
    assert set(tools._registered_layers) == {"é.geojson", "e\u0301_1.geojson"}
    assert (output_dir / "uploads" / "e\u0301_1.geojson").is_file()


def test_oversized_upload_body_is_rejected_before_multipart_file_parsing(monkeypatch):
    middleware_config = next(
        item for item in main.app.user_middleware
        if item.cls is main.ProjectImportBodyLimitMiddleware
        and item.kwargs.get("path") == "/api/upload"
    )
    original_limit = middleware_config.kwargs["max_body_bytes"]
    original_stack = main.app.middleware_stack
    middleware_config.kwargs["max_body_bytes"] = 512
    main.app.middleware_stack = None

    async def upload_must_not_run(_file):
        raise AssertionError("oversized request must be rejected before upload parsing")

    monkeypatch.setattr(main, "_process_uploaded_file", upload_must_not_run)
    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/upload",
                files={"file": ("large.geojson", b"x" * 1024, "application/geo+json")},
            )
    finally:
        middleware_config.kwargs["max_body_bytes"] = original_limit
        main.app.middleware_stack = original_stack

    assert response.status_code == 413
    assert "上传请求体超出允许大小" in response.json()["detail"]


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


@pytest.mark.parametrize("missing", [".dbf", ".shx", ".prj"])
def test_shapefile_zip_reports_missing_required_components(tmp_path, monkeypatch, missing):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        for suffix in (".shp", ".dbf", ".shx", ".prj"):
            if suffix != missing:
                zf.writestr(f"nested/roads{suffix}", b"placeholder")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("missing-component.zip", archive.getvalue(), "application/zip")},
        )

    assert response.status_code == 200
    assert missing in response.json()["error"]
    assert not (upload_dir / "missing-component.zip").exists()


@pytest.mark.parametrize("duplicate_name", [
    "nested/roads.dbf", "NESTED/ROADS.DBF", r"nested\roads.dbf",
    "nested/roads.dbf.", "nested/roads.dbf ",
])
def test_shapefile_zip_rejects_duplicate_component_paths_before_extraction(tmp_path, monkeypatch, duplicate_name):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/roads.shp", b"shape")
        zf.writestr("nested/roads.dbf", b"first attributes")
        zf.writestr(duplicate_name, b"different attributes")
        zf.writestr("nested/roads.shx", b"index")
        zf.writestr("nested/roads.prj", b"projection")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("duplicate-component.zip", archive.getvalue(), "application/zip")},
        )

    assert response.status_code == 200
    assert "重复的文件路径" in response.json()["error"]
    assert not (upload_dir / "duplicate-component.zip").exists()


@pytest.mark.parametrize("reserved_member", ["nested/NUL.txt", "nested/COM¹.dbf"])
def test_shapefile_zip_rejects_windows_reserved_device_members(
    tmp_path, monkeypatch, reserved_member,
):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(main, "_register_layer", lambda *_args, **_kwargs: pytest.fail("invalid archive must not register"))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        for suffix in (".shp", ".dbf", ".shx", ".prj"):
            zipped.writestr(f"nested/roads{suffix}", b"placeholder")
        zipped.writestr(reserved_member, b"must not reach a device path")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("reserved-device.zip", archive.getvalue(), "application/zip")},
        )

    assert response.status_code == 200
    assert "保留设备名" in response.json()["error"]
    assert not (upload_dir / "reserved-device.zip").exists()
