"""Model provider keys must remain in browser storage, not persisted settings."""

import json
import threading

from fastapi.testclient import TestClient

from backend import main


def test_user_settings_post_strips_provider_keys(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))
    _use_temporary_credential_store(tmp_path, monkeypatch)

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
    _use_temporary_credential_store(tmp_path, monkeypatch)

    with TestClient(main.app) as client:
        fetched = client.get("/api/user-settings")

    assert fetched.status_code == 200
    assert fetched.json()["providers"] == [{"id": "custom", "model": "test"}]
    assert json.loads(settings_path.read_text(encoding="utf-8")) == fetched.json()


def _use_temporary_credential_store(tmp_path, monkeypatch):
    from backend.services import credential_store
    credential_dir = tmp_path / "credentials"
    monkeypatch.setattr(credential_store, "_CRED_DIR", str(credential_dir))
    monkeypatch.setattr(credential_store, "_KEY_FILE", str(credential_dir / ".key"))
    monkeypatch.setattr(credential_store, "_CRED_FILE", str(credential_dir / "credentials.enc"))
    return credential_store


def test_amap_key_is_encrypted_at_rest_and_remains_syncable(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))
    credential_store = _use_temporary_credential_store(tmp_path, monkeypatch)
    secret = "amap-secret-sentinel"

    with TestClient(main.app) as client:
        saved = client.post("/api/user-settings", json={"amap_key": secret})
        assert saved.json()["status"] == "ok"

        persisted = settings_path.read_text(encoding="utf-8")
        encrypted = (tmp_path / "credentials" / "credentials.enc").read_bytes()
        fetched = client.get("/api/user-settings").json()
        removed = client.post("/api/user-settings", json={"amap_key": ""})

    assert secret not in persisted
    assert '"amap_key"' not in persisted
    assert secret.encode("utf-8") not in encrypted
    assert fetched["amap_key"] == secret
    assert removed.json()["status"] == "ok"
    assert not credential_store.has_credential("amap")


def test_legacy_plaintext_amap_key_is_migrated_to_encrypted_storage(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    secret = "legacy-amap-secret-sentinel"
    settings_path.write_text(json.dumps({"amap_key": secret, "theme": "dark"}), encoding="utf-8")
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))
    _use_temporary_credential_store(tmp_path, monkeypatch)

    with TestClient(main.app) as client:
        fetched = client.get("/api/user-settings").json()

    persisted = settings_path.read_text(encoding="utf-8")
    encrypted = (tmp_path / "credentials" / "credentials.enc").read_bytes()
    assert fetched["amap_key"] == secret
    assert fetched["theme"] == "dark"
    assert secret not in persisted
    assert '"amap_key"' not in persisted
    assert secret.encode("utf-8") not in encrypted


def test_legacy_amap_key_migration_failure_is_reported_without_returning_settings(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    secret = "legacy-amap-secret-sentinel"
    settings_path.write_text(json.dumps({"amap_key": secret, "theme": "dark"}), encoding="utf-8")
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))
    monkeypatch.setattr(main, "_save_amap_key", lambda _key: False)

    with TestClient(main.app) as client:
        response = client.get("/api/user-settings")

    assert response.status_code == 500
    assert secret not in response.text
    assert "仍可能以明文保存" in response.json()["detail"]
    assert secret in settings_path.read_text(encoding="utf-8")


def test_legacy_amap_key_cleanup_failure_is_reported_after_encrypted_migration(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    secret = "legacy-amap-secret-sentinel"
    settings_path.write_text(json.dumps({"amap_key": secret, "theme": "dark"}), encoding="utf-8")
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))
    credential_store = _use_temporary_credential_store(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_save_user_settings", lambda _data: False)

    with TestClient(main.app) as client:
        response = client.get("/api/user-settings")

    assert response.status_code == 500
    assert secret not in response.text
    assert "仍可能有明文密钥" in response.json()["detail"]
    assert credential_store.get_credential("amap")["password"] == secret
    assert secret in settings_path.read_text(encoding="utf-8")


def test_deleting_legacy_amap_key_does_not_migrate_it_back(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    secret = "legacy-amap-secret-sentinel"
    settings_path.write_text(json.dumps({"amap_key": secret, "theme": "dark"}), encoding="utf-8")
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))
    credential_store = _use_temporary_credential_store(tmp_path, monkeypatch)

    with TestClient(main.app) as client:
        response = client.post("/api/user-settings", json={"amap_key": ""})

    persisted = settings_path.read_text(encoding="utf-8")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "amap_key" not in json.loads(persisted)
    assert secret not in persisted
    assert not credential_store.has_credential("amap")


def test_concurrent_legacy_migration_cannot_resurrect_deleted_amap_key(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    settings_path = tmp_path / "user_settings.json"
    secret = "legacy-amap-concurrency-sentinel"
    settings_path.write_text(json.dumps({"amap_key": secret, "theme": "dark"}), encoding="utf-8")
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))
    credential_store = _use_temporary_credential_store(tmp_path, monkeypatch)
    entered_migration = threading.Event()
    overlapping_migration = threading.Event()
    release_migration = threading.Event()
    original_save = main._save_amap_key

    def pause_first_migration(key):
        if key == secret:
            if not entered_migration.is_set():
                entered_migration.set()
                assert release_migration.wait(5)
            else:
                overlapping_migration.set()
        return original_save(key)

    monkeypatch.setattr(main, "_save_amap_key", pause_first_migration)
    with TestClient(main.app) as get_client, TestClient(main.app) as post_client, ThreadPoolExecutor(max_workers=2) as pool:
        get_request = pool.submit(get_client.get, "/api/user-settings")
        assert entered_migration.wait(5)
        delete_request = pool.submit(post_client.post, "/api/user-settings", json={"amap_key": ""})
        raced = overlapping_migration.wait(0.5)
        release_migration.set()
        deleted = delete_request.result(timeout=5)
        fetched = get_request.result(timeout=5)

    assert not raced
    assert deleted.json()["status"] == "ok"
    assert fetched.status_code == 200
    assert not credential_store.has_credential("amap")
    assert "amap_key" not in json.loads(settings_path.read_text(encoding="utf-8"))


def test_invalid_settings_file_is_not_silently_replaced_by_a_partial_update(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    original = '{"theme":"dark", this is invalid'
    settings_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))

    with TestClient(main.app) as client:
        response = client.post("/api/user-settings", json={"map_style": "satellite"})

    assert response.status_code == 500
    assert "为避免覆盖现有配置" in response.json()["detail"]
    assert settings_path.read_text(encoding="utf-8") == original


def test_user_settings_atomic_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    original = '{"theme": "dark"}'
    settings_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(main, "_USER_SETTINGS_PATH", str(settings_path))
    real_replace = main.os.replace

    def fail_settings_replace(source, destination):
        if str(destination) == str(settings_path):
            raise OSError("simulated replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(main.os, "replace", fail_settings_replace)

    assert main._save_user_settings({"theme": "light"}) is False
    assert settings_path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".user_settings_*.tmp"))
