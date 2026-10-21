"""Model provider keys must remain in browser storage, not persisted settings."""

import json

from fastapi.testclient import TestClient

from backend import main


def test_user_settings_post_strips_provider_keys(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/user-settings",
            json={"providers": [{"id": "custom", "model": "test", "api_key": "test-only-key"}]},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        persisted = json.loads(settings_path.read_text(encoding="utf-8"))
        fetched = client.get("/api/user-settings").json()

    assert persisted["providers"] == [{"id": "custom", "model": "test"}]
    assert fetched["providers"] == persisted["providers"]


def test_legacy_provider_keys_are_removed_from_persisted_settings(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    settings_path.write_text(
        json.dumps({"providers": [{"id": "custom", "model": "test", "api_key": "legacy-test-key"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))

    with TestClient(main.app) as client:
        fetched = client.get("/api/user-settings")

    assert fetched.status_code == 200
    assert fetched.json()["providers"] == [{"id": "custom", "model": "test"}]
    assert json.loads(settings_path.read_text(encoding="utf-8")) == fetched.json()
