import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.services import credential_store

client = TestClient(main.app)


def test_delete_geo_credential_is_idempotent_when_already_absent(monkeypatch):
    monkeypatch.setattr(credential_store, "has_credential", lambda service: False)
    monkeypatch.setattr(credential_store, "delete_credential", lambda service: pytest.fail("must not delete absent credential"))

    response = client.delete("/api/geo-credentials/copernicus")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "deleted": False, "already_absent": True}


def test_delete_geo_credential_reports_storage_failure(monkeypatch):
    monkeypatch.setattr(credential_store, "has_credential", lambda service: True)
    monkeypatch.setattr(credential_store, "delete_credential", lambda service: False)

    response = client.delete("/api/geo-credentials/copernicus")

    assert response.status_code == 200
    assert response.json() == {"status": "error", "deleted": False}
