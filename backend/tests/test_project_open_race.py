import asyncio
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import main
from backend.services import project_service, tools


_GEOJSON = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "marker"},
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    }],
}


def test_stale_project_open_cannot_activate_after_newer_open(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])

    old = project_service.save_project(
        project_id=None, name="old", session_id="old", provider="test", map_state={},
        messages=[], layers=[{"name": "old-layer", "geojson": _GEOJSON}],
    )
    latest = project_service.save_project(
        project_id=None, name="latest", session_id="latest", provider="test", map_state={},
        messages=[], layers=[{"name": "latest-layer", "geojson": _GEOJSON}],
    )
    old_entered = threading.Event()
    release_old = threading.Event()
    real_open_project = project_service.open_project

    def delayed_open(project_id, should_activate=None):
        if project_id == old["id"]:
            old_entered.set()
            assert release_old.wait(5), "timed out waiting to release delayed old open"
        return real_open_project(project_id, should_activate)

    monkeypatch.setattr(project_service, "open_project", delayed_open)

    async def perform_opens():
        old_request = asyncio.create_task(main.load_project(old["id"]))
        assert await asyncio.to_thread(old_entered.wait, 5)
        latest_result = await main.load_project(latest["id"])
        release_old.set()
        with pytest.raises(HTTPException) as stale_result:
            await old_request
        return latest_result, stale_result.value

    try:
        latest_result, stale_error = asyncio.run(perform_opens())
    finally:
        release_old.set()

    assert latest_result["id"] == latest["id"]
    assert stale_error.status_code == 409
    assert tools._active_project_id == latest["id"]
    assert set(tools._registered_layers) == {"latest-layer"}


def test_newer_open_during_activation_rolls_back_superseded_registry_state(tmp_path, monkeypatch):
    from backend.services import ai_service

    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()
    saved = project_service.save_project(
        project_id=None, name="candidate", session_id="candidate-session", provider="test",
        map_state={}, messages=[{"role": "user", "content": "new project"}],
        layers=[{"name": "candidate-layer", "geojson": _GEOJSON}],
    )
    old_registry = {"previous-layer": {"geojson": _GEOJSON}}
    old_pending = [{"name": "pending"}]
    old_ops = [{"action": "pending"}]
    old_history = [{"role": "user", "content": "previous project"}]
    monkeypatch.setattr(tools, "_registered_layers", dict(old_registry))
    monkeypatch.setattr(tools, "_active_project_id", "previous-project")
    monkeypatch.setattr(tools, "_pending_layers", list(old_pending))
    monkeypatch.setattr(tools, "_pending_layer_ops", list(old_ops))
    monkeypatch.setattr(ai_service, "conversation_history", {"candidate-session": old_history})
    checks = iter((True, False))

    with pytest.raises(project_service.ProjectOpenSuperseded):
        project_service.open_project(saved["id"], lambda: next(checks))

    assert tools._registered_layers == old_registry
    assert tools._active_project_id == "previous-project"
    assert tools._pending_layers == old_pending
    assert tools._pending_layer_ops == old_ops
    assert ai_service.conversation_history["candidate-session"] == old_history


def test_cancelled_project_open_does_not_activate_in_background(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])

    saved = project_service.save_project(
        project_id=None, name="cancelled", session_id="cancelled-session", provider="test",
        map_state={}, messages=[], layers=[{"name": "cancelled-layer", "geojson": _GEOJSON}],
    )
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    real_open_project = project_service.open_project

    def delayed_open(project_id, should_activate=None):
        entered.set()
        try:
            assert release.wait(5), "timed out waiting to release cancelled project open"
            return real_open_project(project_id, should_activate)
        finally:
            finished.set()

    monkeypatch.setattr(project_service, "open_project", delayed_open)

    async def cancel_open():
        task = asyncio.create_task(main.load_project(saved["id"]))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(cancel_open())
        assert finished.wait(5)
    finally:
        release.set()

    assert tools._active_project_id is None
    assert tools._registered_layers == {}


def test_project_activation_waits_for_inflight_direct_tool_state_mutation(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])

    source = project_service.save_project(
        project_id=None, name="source", session_id="source", provider="test", map_state={},
        messages=[], layers=[{"name": "source-layer", "geojson": _GEOJSON}],
    )
    target = project_service.save_project(
        project_id=None, name="target", session_id="target", provider="test", map_state={},
        messages=[], layers=[{"name": "target-layer", "geojson": _GEOJSON}],
    )
    project_service.open_project(source["id"])

    tool_entered = threading.Event()
    finish_tool = threading.Event()
    open_started = threading.Event()
    open_finished = threading.Event()
    failures = []

    def run_direct_tool_mutation():
        assert tools.acquire_shared_state_lock(timeout=0)
        try:
            tool_entered.set()
            assert finish_tool.wait(5), "timed out waiting to finish direct tool mutation"
            tools._register_layer("late-tool-result", _GEOJSON)
        except BaseException as exc:
            failures.append(exc)
        finally:
            tools.release_shared_state_lock()

    def open_target_project():
        open_started.set()
        try:
            project_service.open_project(target["id"])
        except BaseException as exc:
            failures.append(exc)
        finally:
            open_finished.set()

    tool_thread = threading.Thread(target=run_direct_tool_mutation)
    open_thread = threading.Thread(target=open_target_project)
    tool_thread.start()
    assert tool_entered.wait(5)
    open_thread.start()
    assert open_started.wait(5)
    assert not open_finished.wait(0.1), "project activation must wait for the in-flight shared GIS operation"

    finish_tool.set()
    tool_thread.join(5)
    open_thread.join(5)

    assert not tool_thread.is_alive()
    assert not open_thread.is_alive()
    assert failures == []
    assert tools._active_project_id == target["id"]
    assert set(tools._registered_layers) == {"target-layer"}


def test_layer_sync_from_previous_project_is_rejected_after_project_switch(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    old_project = project_service.save_project(
        project_id=None, name="old", session_id="old", provider="test", map_state={},
        messages=[], layers=[{"name": "old-layer", "geojson": _GEOJSON}],
    )
    new_project = project_service.save_project(
        project_id=None, name="new", session_id="new", provider="test", map_state={},
        messages=[], layers=[{"name": "new-layer", "geojson": _GEOJSON}],
    )
    project_service.open_project(new_project["id"])

    client = TestClient(main.app)
    current_response = client.post("/api/layer/register", json={
        "name": "current-layer-sync", "geojson": _GEOJSON,
        "project_context": True, "expected_project_id": new_project["id"],
    })
    assert current_response.status_code == 200
    new_session_response = client.post("/api/layer/register", json={
        "name": "new-session-layer", "geojson": _GEOJSON,
        "project_context": True, "expected_project_id": None,
    })
    assert new_session_response.status_code == 409

    response = client.post("/api/layer/register", json={
        "name": "late-old-layer", "geojson": _GEOJSON,
        "project_context": True, "expected_project_id": old_project["id"],
    })

    assert response.status_code == 409
    assert set(tools._registered_layers) == {"new-layer", "current-layer-sync"}


def test_layer_sync_allows_saved_unsaved_workspace_while_no_project_is_active(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    response = TestClient(main.app).post("/api/layer/register", json={
        "name": "new-session-layer", "geojson": _GEOJSON,
        "project_context": True, "expected_project_id": None,
    })

    assert response.status_code == 200
    assert set(tools._registered_layers) == {"new-session-layer"}


def test_deleting_previous_project_does_not_clear_new_session_registry(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    previous = project_service.save_project(
        project_id=None, name="previous", session_id="previous", provider="test", map_state={},
        messages=[], layers=[{"name": "previous-layer", "geojson": _GEOJSON}],
    )
    project_service.open_project(previous["id"])
    old_token = tools._registered_layers["previous-layer"]["registration_token"]
    client = TestClient(main.app)

    context = client.get("/api/projects/active/context")
    assert context.status_code == 200
    assert context.json()["active_project_id"] == previous["id"]
    stale_reset = client.post("/api/projects/active/reset", json={
        "expected_project_id": "another-project",
    })
    assert stale_reset.status_code == 409
    assert "previous-layer" in tools._registered_layers

    removed = client.post("/api/layer/unregister", json={
        "name": "previous-layer", "registration_token": old_token,
    })
    assert removed.status_code == 200
    reset = client.post("/api/projects/active/reset", json={
        "expected_project_id": previous["id"],
    })
    assert reset.status_code == 200
    assert client.get("/api/projects/active/context").json()["active_project_id"] is None
    added = client.post("/api/layer/register", json={
        "name": "new-session-layer", "geojson": _GEOJSON,
        "project_context": True, "expected_project_id": None,
    })
    assert added.status_code == 200
    assert tools._active_project_id is None

    project_service.delete_project(previous["id"])

    assert "new-session-layer" in tools._registered_layers
