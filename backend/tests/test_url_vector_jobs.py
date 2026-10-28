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


def test_url_vector_inspection_error_redacts_source_credentials(monkeypatch):
    from backend import main
    from backend.services import url_gis_service as ugs

    source = "https://user:PASS_SENTINEL@example.test/roads?token=TOKEN_SENTINEL"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: (_ for _ in ()).throw(
        RuntimeError(f"read failed for {source}")
    ))
    with TestClient(main.app) as client:
        response = client.post("/api/url-data/inspect", json={"url": source})

    assert response.status_code == 400
    assert "PASS_SENTINEL" not in response.text
    assert "TOKEN_SENTINEL" not in response.text
    assert "https://example.test/roads" in response.text


def test_url_vector_job_error_redacts_source_credentials(monkeypatch):
    import threading
    from backend import main
    from backend.services import url_gis_service as ugs

    source = "https://user:PASS_SENTINEL@example.test/roads?token=TOKEN_SENTINEL"
    monkeypatch.setattr(ugs, "fetch_gis_data_url", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError(f"download failed for {source}")
    ))
    job_id = "credential-redaction-test"
    main._url_fetch_jobs[job_id] = {"status": "running"}
    try:
        main._run_url_vector_fetch(
            job_id, main.UrlVectorFetchRequest(url=source), threading.Event()
        )
        error = main._url_fetch_jobs[job_id]["error"]
        assert "PASS_SENTINEL" not in error
        assert "TOKEN_SENTINEL" not in error
        assert "https://example.test/roads" in error
    finally:
        main._url_fetch_jobs.pop(job_id, None)


def test_url_vector_job_records_cooperative_cancellation(monkeypatch):
    import threading
    from backend import main
    from backend.services import url_gis_service as ugs

    job_id = "cooperative-cancel-test"
    cancel_event = threading.Event()
    main._url_fetch_jobs[job_id] = {"status": "running", "cancel_event": cancel_event}

    def cancel_during_fetch(*_args, **kwargs):
        cancel_event.set()
        assert kwargs["cancel_check"]()
        raise ugs.UrlGisError("获取已由用户取消")

    monkeypatch.setattr(ugs, "fetch_gis_data_url", cancel_during_fetch)
    try:
        main._run_url_vector_fetch(
            job_id, main.UrlVectorFetchRequest(url="https://example.test/FeatureServer/0"), cancel_event,
        )
        job = main._url_fetch_jobs[job_id]
        assert job["status"] == "cancelled"
        assert "result" not in job
    finally:
        main._url_fetch_jobs.pop(job_id, None)
