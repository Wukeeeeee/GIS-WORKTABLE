"""Conditional layer deletion must not remove a newer registration with the same name."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

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


def test_http_registration_with_stale_token_cannot_overwrite_newer_layer(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    client = TestClient(main.app)
    first = client.post('/api/layer/register', json={"name": "same", "geojson": point(1)}).json()
    second = client.post('/api/layer/register', json={
        "name": "same", "geojson": point(2),
        "registration_token": first["registration_token"],
    }).json()
    assert second["success"] is True
    assert second["registration_token"] != first["registration_token"]

    stale = client.post('/api/layer/register', json={
        "name": "same", "geojson": point(3),
        "registration_token": first["registration_token"],
    }).json()

    assert stale["success"] is False
    assert stale["stale"] is True
    assert tools._registered_layers["same"]["registration_token"] == second["registration_token"]
    assert tools._registered_layers["same"]["geojson"]["features"][0]["properties"]["revision"] == 2


def test_http_raster_registration_with_stale_token_cannot_overwrite_newer_layer(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    client = TestClient(main.app)
    first = client.post('/api/layer/register', json={
        "name": "raster", "raster": {"bounds": [0, 0, 1, 1]},
    }).json()
    second = client.post('/api/layer/register', json={
        "name": "raster", "raster": {"bounds": [1, 1, 2, 2]},
        "registration_token": first["registration_token"],
    }).json()
    assert second["success"] is True
    assert second["registration_token"] != first["registration_token"]

    stale = client.post('/api/layer/register', json={
        "name": "raster", "raster": {"bounds": [2, 2, 3, 3]},
        "registration_token": first["registration_token"],
    }).json()

    assert stale["success"] is False
    assert stale["stale"] is True
    assert tools._registered_layers["raster"]["registration_token"] == second["registration_token"]
    assert tools._registered_layers["raster"]["raster"]["bounds"] == [1, 1, 2, 2]


def test_online_vector_load_returns_the_registration_token(monkeypatch):
    from backend.services import cloud_native

    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(
        cloud_native, "cloud_vector_to_geojson",
        lambda _source, _fmt, bbox=None: (point(7), {"source": "synthetic"}),
    )
    request = main.OnlineLoadRequest(
        source="https://unused.invalid/data.parquet", type="geoparquet",
    )

    result = asyncio.run(main.api_online_load(request))

    assert result["registration_token"] == tools._registered_layers["data"]["registration_token"]


def test_non_http_data_updates_also_invalidate_stale_registration_tokens(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    token = tools._register_layer('same', point(1))
    tools._update_registered_layer_data('same', point(2))
    assert tools._unregister_layer('same', token) is False
    assert tools._unregister_layer('same') is True


def test_raster_register_response_survives_unregister_during_worker_return(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    token = "raster-registration-token"
    registered = threading.Event()
    finish_worker = threading.Event()

    def delayed_register(name, raster, **kwargs):
        with tools._state_lock:
            tools._registered_layers[name] = {
                "registration_token": token,
                "sensitive": True,
            }
        registered.set()
        if not finish_worker.wait(timeout=3):
            raise TimeoutError("test did not release registration worker")
        return token

    monkeypatch.setattr(tools, "_register_raster_layer", delayed_register)
    register_request = main.RegisterLayerRequest(
        name="raster", raster={"bounds": [0, 0, 1, 1]},
    )
    unregister_request = main.UnregisterLayerRequest(
        name="raster", registration_token=token,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        register_future = executor.submit(
            lambda: asyncio.run(main.register_layer(register_request)),
        )
        try:
            assert registered.wait(timeout=2)
            unregister_future = executor.submit(
                lambda: asyncio.run(main.unregister_layer(unregister_request)),
            )
            assert unregister_future.result(timeout=2)["removed"] is True
            with tools._state_lock:
                tools._registered_layers["raster"] = {
                    "registration_token": "newer-token",
                    "sensitive": False,
                }
        finally:
            finish_worker.set()

        result = register_future.result(timeout=2)

    assert result["success"] is False
    assert result["stale"] is True
    assert result["registration_token"] == token
    assert result["sensitive"] is True


def test_invalid_autosave_state_returns_a_validation_error(monkeypatch):
    def reject(**kwargs):
        raise ValueError('图层尚未完成注册')

    monkeypatch.setattr(main.project_service, 'auto_save', reject)
    response = TestClient(main.app).post('/api/projects/auto-save', json={"layer_assignments": [{"names": ["missing"]}]})
    assert response.status_code == 400
    assert '尚未完成注册' in response.json()["detail"]
