import os
import io
import urllib.parse

from fastapi.testclient import TestClient

from backend import main


def test_active_output_files_receive_an_opaque_origin_policy(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    client = TestClient(main.app)

    for filename, content_type in (
        ("chart.html", "text/html"),
        ("map.svg", "image/svg+xml"),
        ("document.xhtml", "application/xhtml+xml"),
    ):
        (output_dir / filename).write_text("<script>window.test = true</script>", encoding="utf-8")
        response = client.get(f"/output/{filename}")

        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
        assert response.headers["content-security-policy"] == "sandbox allow-scripts"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_output_file_route_rejects_resolved_symlink_escape(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    target = output_dir / "linked" / "secret.txt"
    outside = tmp_path / "outside-secret.txt"
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    realpath = os.path.realpath

    def resolve_with_escape(path):
        if os.fspath(path) == os.fspath(target):
            return os.fspath(outside)
        return realpath(path)

    monkeypatch.setattr(main.os.path, "realpath", resolve_with_escape)
    response = TestClient(main.app).get("/output/linked/secret.txt")

    assert response.status_code == 403


def test_export_download_names_cannot_inject_response_headers(monkeypatch):
    monkeypatch.setattr(main.project_service, "export_project", lambda _project_id: b"project")
    project_id = "bad\r\nX-Injected: yes"
    project_url = "/api/projects/" + urllib.parse.quote(project_id, safe="") + "/export"
    project_response = TestClient(main.app).get(project_url)

    monkeypatch.setattr(main, "_export_shp_sync", lambda *_args: (io.BytesIO(b"shapefile"), None))
    shp_response = TestClient(main.app).post("/api/layer/export-shp", json={
        "geojson": {"type": "FeatureCollection", "features": []},
        "name": "线路\"\r\nX-Injected: yes",
        "crs": "EPSG:4326",
    })

    for response in (project_response, shp_response):
        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert "\r" not in disposition and "\n" not in disposition
        assert "filename*=UTF-8''" in disposition
        assert "%0D%0A" in disposition
