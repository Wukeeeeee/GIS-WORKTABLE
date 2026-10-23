"""Conditional layer deletion must not remove a newer registration with the same name."""
from fastapi.testclient import TestClient

from backend import main
from backend.services import tools


def point(revision):
    return {"type": "FeatureCollection", "features": [{"type": "Feature",
        "properties": {"revision": revision}, "geometry": {"type": "Point", "coordinates": [0, 0]}}]}


def test_http_deletion_only_removes_the_version_it_registered(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    client = TestClient(main.app)
    old = client.post('/api/layer/register', json={"name": "same", "geojson": point(1)}).json()
    new = client.post('/api/layer/register', json={"name": "same", "geojson": point(2)}).json()
    assert old["registration_token"] != new["registration_token"]
    stale = client.post('/api/layer/unregister', json={"name": "same", "registration_token": old["registration_token"]})
    assert stale.status_code == 200 and stale.json()["removed"] is False
    assert stale.json()["stale"] is True
    assert tools._registered_layers["same"]["geojson"]["features"][0]["properties"]["revision"] == 2
    removed = client.post('/api/layer/unregister', json={"name": "same", "registration_token": new["registration_token"]})
    assert removed.json()["removed"] is True
    assert "same" not in tools._registered_layers


def test_non_http_data_updates_also_invalidate_stale_registration_tokens(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    token = tools._register_layer('same', point(1))
    tools._update_registered_layer_data('same', point(2))
    assert tools._unregister_layer('same', token) is False
    assert tools._unregister_layer('same') is True


def test_invalid_autosave_state_returns_a_validation_error(monkeypatch):
    def reject(**kwargs):
        raise ValueError('图层尚未完成注册')

    monkeypatch.setattr(main.project_service, 'auto_save', reject)
    response = TestClient(main.app).post('/api/projects/auto-save', json={"layer_assignments": [{"names": ["missing"]}]})
    assert response.status_code == 400
    assert '尚未完成注册' in response.json()["detail"]
