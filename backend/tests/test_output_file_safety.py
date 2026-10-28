import os
import io
import urllib.parse

from fastapi.testclient import TestClient

from backend import main
from backend.services import tools


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


def test_output_file_route_rechecks_path_after_a_symlink_swap(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    target = output_dir / "report.txt"
    outside = tmp_path / "outside-secret.txt"
    target.write_text("safe", encoding="utf-8")
    outside.write_text("outside secret", encoding="utf-8")
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    original_response = main._output_file_response

    def swap_then_respond(path, download=False, request=None):
        if os.fspath(path) == os.fspath(target):
            target.unlink()
            os.symlink(outside, target)
        return original_response(path, download, request)

    monkeypatch.setattr(main, "_output_file_response", swap_then_respond)
    response = TestClient(main.app).get("/output/report.txt")

    assert response.status_code == 403
    assert response.text != "outside secret"


def test_output_file_route_keeps_single_and_multiple_byte_ranges(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "data.bin").write_bytes(b"0123456789")
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    client = TestClient(main.app)

    single = client.get("/output/data.bin", headers={"Range": "bytes=2-4"})
    multiple = client.get("/output/data.bin", headers={"Range": "bytes=0-1,8-9"})

    assert single.status_code == 206
    assert single.content == b"234"
    assert single.headers["content-range"] == "bytes 2-4/10"
    assert multiple.status_code == 206
    assert "multipart/byteranges" in multiple.headers["content-type"]
    assert b"Content-Range: bytes 0-1/10" in multiple.content
    assert b"Content-Range: bytes 8-9/10" in multiple.content
    assert b"01" in multiple.content and b"89" in multiple.content


def test_output_file_range_is_not_gzip_transformed(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "data.bin").write_bytes(b"0123456789" * 5000)
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))

    response = TestClient(main.app).get(
        "/output/data.bin",
        headers={"Range": "bytes=2-4", "Accept-Encoding": "gzip"},
    )

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2-4/50000"
    assert response.headers.get("content-encoding") is None
    assert response.content == b"234"


def test_output_file_route_coalesces_overlapping_byte_ranges(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "data.bin").write_bytes(b"0123456789")
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))

    response = TestClient(main.app).get(
        "/output/data.bin", headers={"Range": "bytes=0-9,0-9,2-7"}
    )

    assert response.status_code == 206
    assert response.content == b"0123456789"
    assert response.headers["content-range"] == "bytes 0-9/10"
    assert "multipart/byteranges" not in response.headers["content-type"]


def test_output_file_route_limits_byte_range_count(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "data.bin").write_bytes(b"0123456789")
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))
    range_items = ",".join("0-9" for _ in range(17))

    response = TestClient(main.app).get(
        "/output/data.bin", headers={"Range": f"bytes={range_items}"}
    )

    assert response.status_code == 400


def test_pending_html_artifact_remains_available_for_open_and_download(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    artifact = output_dir / "chart.html"
    content = "<html><body>chart artifact</body></html>"
    artifact.write_text(content, encoding="utf-8")
    monkeypatch.setattr(tools, "_temp_output_dir", str(output_dir))
    monkeypatch.setattr(tools, "_pending_images", [])
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))

    tools._add_pending_item("/output/chart.html", str(artifact))
    client = TestClient(main.app)
    opened = client.get("/output/chart.html")
    downloaded = client.get("/output/chart.html?download=true")

    assert tools._pending_images[0]["content"] == content
    assert opened.status_code == 200 and opened.text == content
    assert downloaded.status_code == 200 and downloaded.content == content.encode("utf-8")
    assert "attachment" in downloaded.headers["content-disposition"]


def test_large_pending_html_uses_file_url_instead_of_inline_copy(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    artifact = output_dir / "large-chart.html"
    content = b"<html>large chart</html>"
    artifact.write_bytes(content)
    monkeypatch.setattr(tools, "_temp_output_dir", str(output_dir))
    monkeypatch.setattr(tools, "_pending_images", [])
    monkeypatch.setattr(tools, "_INLINE_HTML_PREVIEW_LIMIT", 8)
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))

    tools._add_pending_item("/output/large-chart.html", str(artifact))
    response = TestClient(main.app).get("/output/large-chart.html")

    assert tools._pending_images == [{"url": "/output/large-chart.html", "type": "html"}]
    assert response.status_code == 200 and response.content == content


def test_output_file_route_rejects_range_integer_overflow(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "data.bin").write_bytes(b"0123456789")
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(output_dir))

    response = TestClient(main.app).get(
        "/output/data.bin", headers={"Range": "bytes=" + "9" * 5000 + "-"}
    )

    assert response.status_code == 400


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
