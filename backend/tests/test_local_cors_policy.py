import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.main import app


def _preflight(origin):
    return TestClient(app).options(
        "/api/tools/invoke",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_cors_allows_local_frontends_on_other_ports():
    response = _preflight("http://127.0.0.1:8003")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8003"


def test_cors_rejects_non_local_web_origins():
    for origin in ("https://attacker.example", "http://192.168.1.20:3000"):
        response = _preflight(origin)

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_cross_site_multipart_upload_is_rejected_before_processing(monkeypatch, headers):
    def unexpected_upload(_file):
        pytest.fail("cross-site upload must be blocked before processing")

    monkeypatch.setattr(main, "_process_uploaded_file", unexpected_upload)
    response = TestClient(app).post(
        "/api/upload",
        files={"file": ("attack.geojson", b"{}", "application/geo+json")},
        headers=headers,
    )

    assert response.status_code == 403


def test_loopback_frontend_can_still_post_mutations(monkeypatch):
    async def fake_upload(_file, request_id=None):
        return {"success": True}

    monkeypatch.setattr(main, "_process_uploaded_file", fake_upload)
    response = TestClient(app).post(
        "/api/upload",
        files={"file": ("valid.geojson", b"{}", "application/geo+json")},
        headers={"Origin": "http://localhost:8003", "Sec-Fetch-Site": "same-site"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_cross_site_project_open_is_rejected_before_activation(monkeypatch):
    from backend.services import project_service

    def unexpected_open(_project_id):
        pytest.fail("cross-site project opening must be blocked before activation")

    monkeypatch.setattr(project_service, "open_project", unexpected_open)
    response = TestClient(app).get(
        "/api/projects/attacker-chosen",
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
