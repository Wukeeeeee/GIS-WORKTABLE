"""Manual ArcGIS URL acquisition API state and credential handling tests."""

from fastapi.testclient import TestClient


def test_delivery_downloads_are_attachments_while_map_reads_stay_inline(tmp_path, monkeypatch):
    from backend import main

    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    with TestClient(main.app) as client:
        for filename in ("delivery.geojson", "delivery.report.md", "delivery.manifest.json", "delivery.recipe.json"):
            (downloads / filename).write_text('{"test": true}', encoding="utf-8")
            url = f"/output/downloads/{filename}"
            inline = client.get(url)
            assert inline.status_code == 200
            assert "content-disposition" not in inline.headers
            attachment = client.get(url, params={"download": "1"})
            assert attachment.status_code == 200
            assert attachment.content == inline.content
            assert attachment.headers["content-disposition"] == f'attachment; filename="{filename}"'


def test_url_vector_job_start_poll_and_cancel(monkeypatch):
    from backend import main

    submitted = []
    monkeypatch.setattr(main._url_fetch_executor, "submit", lambda *args, **kwargs: submitted.append(args))
    with TestClient(main.app) as client:
        started = client.post("/api/url-data/jobs", json={
            "url": "https://example.test/FeatureServer/0", "mode": "full", "where": "1=1"
        })
        assert started.status_code == 200
        job_id = started.json()["job_id"]
        assert len(submitted) == 1
        status = client.get(f"/api/url-data/jobs/{job_id}")
        assert status.json()["status"] == "running"
        cancelled = client.delete(f"/api/url-data/jobs/{job_id}")
        assert cancelled.json()["status"] == "cancelling"
        assert main._url_fetch_jobs[job_id]["cancel_event"].is_set()
        main._url_fetch_jobs.pop(job_id, None)


def test_url_vector_inspection_sanitizes_query_credentials(monkeypatch):
    from backend import main
    from backend.services import url_gis_service as ugs

    seen = []
    def fake_inspect(url):
        seen.append(url)
        return {"ok": True, "url": url, "service_type": "ArcGIS_REST_Layer", "layer_name": "roads"}
    monkeypatch.setattr(ugs, "inspect_gis_url", fake_inspect)
    with TestClient(main.app) as client:
        response = client.post("/api/url-data/inspect", json={
            "url": "https://example.test/FeatureServer?token=private", "layer_id": "12"
        })
    assert response.status_code == 200
    assert seen == ["https://example.test/FeatureServer/12?token=private"]
    assert response.json()["url"] == "https://example.test/FeatureServer/12"
    assert "private" not in response.text
