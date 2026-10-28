"""Regression tests for project persistence and import validation."""

import gzip
import hashlib
import io
import json
import multiprocessing
import os
import stat
import zipfile

import pytest

from backend.services import project_service


_GEOJSON = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "A"},
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    }],
}


def _use_temp_project_store(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()


def test_failed_blob_write_does_not_poison_a_retry(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_service._ensure_dirs()
    real_gzip_open = gzip.open
    failed = False

    def fail_first_blob_write(path, mode="rb", *args, **kwargs):
        nonlocal failed
        if not failed and mode == "wt" and os.path.dirname(os.path.abspath(path)) == os.path.abspath(project_service._BLOB_DIR):
            failed = True
            with open(path, "wb") as partial:
                partial.write(b"partial gzip data")
            raise OSError("simulated interrupted blob write")
        return real_gzip_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(project_service.gzip, "open", fail_first_blob_write)
    with pytest.raises(OSError, match="interrupted blob write"):
        project_service._blob_put(_GEOJSON)

    monkeypatch.setattr(project_service.gzip, "open", real_gzip_open)
    expected_sha = hashlib.sha256(
        json.dumps(_GEOJSON, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:12]
    stale_path = project_service._blob_path(expected_sha)
    if not os.path.exists(stale_path):
        with open(stale_path, "wb") as stale:
            stale.write(b"left by a previously interrupted process")
    blob = project_service._blob_put(_GEOJSON)

    assert blob == expected_sha
    assert project_service._blob_get(blob) == _GEOJSON


def _import_project_in_subprocess(project_dir, archive_bytes, result_queue, started, completed):
    project_service._PROJECT_DIR = project_dir
    project_service._BLOB_DIR = os.path.join(project_dir, "blobs")
    project_service._INDEX_PATH = os.path.join(project_dir, "index.json")
    started.set()
    try:
        result_queue.put(("ok", project_service.import_project(archive_bytes)["id"]))
    except Exception as exc:
        result_queue.put(("error", repr(exc)))
    finally:
        completed.set()


def _project_delete_worker(project_dir, ready, command_queue, result_queue):
    project_service._PROJECT_DIR = project_dir
    project_service._BLOB_DIR = os.path.join(project_dir, "blobs")
    project_service._INDEX_PATH = os.path.join(project_dir, "index.json")
    project_service._rebuild_refcount()
    ready.set()
    project_id = command_queue.get(timeout=15)
    try:
        result_queue.put(("ok", project_service.delete_project(project_id)))
    except Exception as exc:
        result_queue.put(("error", repr(exc)))


@pytest.mark.parametrize("assignments,expected", [
    (None, {"kept", "deleted"}),
    ([], set()),
    ([{"names": ["kept"]}], {"kept"}),
    ([{"registry_name": "kept", "names": ["kept", "deleted"]}], {"kept"}),
])
def test_autosave_uses_the_explicit_frontend_layer_set(tmp_path, monkeypatch, assignments, expected):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {"scope": [{"role": "user", "content": "keep"}]})
    monkeypatch.setattr(tools, "_registered_layers", {
        name: {"geojson": _GEOJSON, "geometry_types": ["Point"]} for name in ("kept", "deleted")
    })
    saved = project_service.auto_save(session_id="scope", layer_assignments=assignments)
    result = project_service._load_project_data(saved["id"])
    assert {layer["name"] for layer in result["layers"]} == expected


def test_pending_tool_layers_include_the_registered_identity_for_manual_results(tmp_path, monkeypatch):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {
        "manual-tool-result": [{"role": "user", "content": "生成道路缓冲区"}],
    })
    monkeypatch.setattr(tools, "_registered_layers", {
        "roads_buffer": {"geojson": _GEOJSON, "geometry_types": ["Polygon"],
                         "registration_token": "registered-version"},
    })
    monkeypatch.setattr(tools, "_pending_layers", [{"name": "roads_buffer", "geojson": _GEOJSON}])

    pending = tools.get_pending_state()
    output = pending["layers"][0]
    assert output["registry_name"] == "roads_buffer"
    assert output["registration_token"] == "registered-version"

    saved = project_service.auto_save(
        session_id="manual-tool-result",
        layer_assignments=[{
            "registry_name": output["registry_name"], "registration_token": output["registration_token"],
            "name": "roads_buffer_1730000000000_0", "names": ["roads_buffer_1730000000000_0"],
        }],
    )
    assert [layer["name"] for layer in project_service.load_project(saved["id"])["layers"]] == ["roads_buffer"]


def test_manual_tool_api_returns_layer_registration_identity(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import main
    from backend.services import storage_service, task_manager, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])

    class ManualTool:
        name = "manual_identity_test"

        @staticmethod
        def invoke(_args):
            tools._push_layer("roads_buffer", _GEOJSON)
            tools._register_layer("roads_buffer", _GEOJSON)
            return "done"

    monkeypatch.setattr(tools, "tools", [ManualTool()])
    monkeypatch.setattr(tools, "_tool_result_failed", lambda *_args: False)
    monkeypatch.setattr(task_manager, "find_or_create_task", lambda *_args: "task-test")
    monkeypatch.setattr(storage_service, "record_run_start", lambda *_args: None)
    monkeypatch.setattr(storage_service, "record_run_finish", lambda *_args: None)

    with TestClient(main.app) as client:
        response = client.post("/api/tools/invoke", json={"name": "manual_identity_test", "arguments": {}})

    assert response.status_code == 200
    output = response.json()["layers"][0]
    assert output["registry_name"] == "roads_buffer"
    assert output["registration_token"]


def test_autosave_preserves_frontend_layer_order(tmp_path, monkeypatch):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {"order-session": [{"role": "user", "content": "图层顺序"}]})
    monkeypatch.setattr(tools, "_registered_layers", {
        name: {"geojson": _GEOJSON, "geometry_types": ["Point"]} for name in ("first", "second")
    })

    saved = project_service.auto_save(session_id="order-session", layer_assignments=[
        {"registry_name": "second", "names": ["second"], "name": "second", "order": 0},
        {"registry_name": "first", "names": ["first"], "name": "first", "order": 1},
    ])

    assert [layer["name"] for layer in project_service.load_project(saved["id"])["layers"]] == ["second", "first"]


def test_autosave_preserves_order_when_assignment_only_has_registry_name(tmp_path, monkeypatch):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {"canonical-order": [{"role": "user", "content": "排序"}]})
    # Registry order deliberately conflicts with the requested panel order.
    monkeypatch.setattr(tools, "_registered_layers", {
        name: {"geojson": _GEOJSON, "geometry_types": ["Point"]} for name in ("first", "second")
    })

    saved = project_service.auto_save(session_id="canonical-order", layer_assignments=[
        {"registry_name": "second", "order": 0},
        {"registry_name": "first", "order": 1},
    ])

    assert [layer["name"] for layer in project_service.load_project(saved["id"])["layers"]] == ["second", "first"]


def test_autosave_applies_assignment_metadata_when_only_canonical_name_is_sent(tmp_path, monkeypatch):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {"canonical-only": [{"role": "user", "content": "分组"}]})
    monkeypatch.setattr(tools, "_registered_layers", {
        "districts": {"geojson": _GEOJSON, "geometry_types": ["Point"]}
    })
    style = {"color": "#223344", "fillOpacity": 0.25}
    saved = project_service.auto_save(session_id="canonical-only", layer_assignments=[{
        "registry_name": "districts", "name": "districts", "groupId": "admin", "visible": False,
        "layer_id": "layer-districts", "style": style, "order": 0,
    }])

    layer = project_service.load_project(saved["id"])["layers"][0]
    assert layer["groupId"] == "admin"
    assert layer["visible"] is False
    assert layer["layer_id"] == "layer-districts"
    assert layer["style"] == style


def test_autosave_persists_and_clears_layer_label_config(tmp_path, monkeypatch):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {"labels-session": [{"role": "user", "content": "标注"}]})
    monkeypatch.setattr(tools, "_registered_layers", {
        "districts": {"geojson": _GEOJSON, "geometry_types": ["Point"]}
    })
    labels = {"field": "name", "fontSize": 14, "color": "#223344"}
    saved = project_service.auto_save(session_id="labels-session", layer_assignments=[{
        "registry_name": "districts", "names": ["districts"], "name": "districts", "labels": labels,
    }])
    assert project_service.load_project(saved["id"])["layers"][0]["labels"] == labels

    project_service.auto_save(session_id="labels-session", project_id=saved["id"], layer_assignments=[{
        "registry_name": "districts", "names": ["districts"], "name": "districts", "labels": None,
    }])
    assert project_service.load_project(saved["id"])["layers"][0].get("labels") is None

    with pytest.raises(ValueError, match="标注配置无效"):
        project_service.auto_save(session_id="labels-session", project_id=saved["id"], layer_assignments=[{
            "registry_name": "districts", "names": ["districts"], "name": "districts",
            "labels": {"field": "name", "fontSize": 1000, "color": "red;display:none"},
        }])


def test_autosave_can_remove_all_layers_without_chat_history(tmp_path, monkeypatch):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    messages = [{"role": "user", "content": "saved history"}]
    saved = project_service.save_project(project_id=None, name="manual", session_id="manual", provider="test",
                                         map_state={}, messages=messages, layers=[{"name": "old", "geojson": _GEOJSON}])
    monkeypatch.setattr(ai_service, "conversation_history", {})
    monkeypatch.setattr(tools, "_registered_layers", {"old": {"geojson": _GEOJSON}})
    project_service.auto_save(session_id="manual", project_id=saved["id"], layer_assignments=[])
    result = project_service._load_project_data(saved["id"])
    assert result["layers"] == []
    assert result["messages"] == messages


def test_autosave_api_preserves_existing_layers_when_assignment_fields_are_omitted(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="兼容保存工程", session_id="legacy-autosave", provider="test",
        map_state={}, messages=[{"role": "user", "content": "已有内容"}],
        layers=[{"name": "existing", "geojson": _GEOJSON}],
        layer_groups=[{"id": "group-1", "name": "分组", "collapsed": True}],
    )
    monkeypatch.setattr(ai_service, "conversation_history", {})
    monkeypatch.setattr(tools, "_registered_layers", {})

    with TestClient(main.app) as client:
        response = client.post(
            "/api/projects/auto-save",
            params={"session_id": "legacy-autosave", "project_id": saved["id"]},
            json={},
        )

    assert response.status_code == 200
    restored = project_service.load_project(saved["id"])
    assert restored["layers"][0]["geojson"] == _GEOJSON
    assert restored["layerGroups"] == [{"id": "group-1", "name": "分组", "collapsed": True}]


def test_activate_project_skips_malformed_conversation_records(tmp_path, monkeypatch):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="损坏历史", session_id="damaged-history", provider="test",
        map_state={}, messages=[
            {"role": "user", "content": "保留的问题"}, None,
            {"role": "tool", "content": "不支持的角色"},
            {"role": "assistant", "content": 42},
            {"role": "assistant", "content": "保留的回答"},
        ], layers=[],
    )
    monkeypatch.setattr(ai_service, "conversation_history", {})
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    monkeypatch.setattr(tools, "reset_registered_layers", lambda _layers, **_kwargs: [])

    activated = project_service.activate_project(saved["id"], session_id="restored-session")

    assert activated["sessionId"] == "restored-session"
    assert ai_service.conversation_history["restored-session"] == [
        {"role": "user", "content": "保留的问题"},
        {"role": "assistant", "content": "保留的回答"},
    ]


def test_downloaded_layer_provenance_survives_autosave_and_restore(tmp_path, monkeypatch):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    provenance = {
        "provider": "osm", "provider_name": "OpenStreetMap",
        "kind": "roads", "kind_label": "道路", "file_format": "geojson",
        "crs": "EPSG:4326", "crs_known": True,
        "source_url": "https://www.openstreetmap.org",
        "processing": {
            "tool": "spatial_clip", "source_layer": "roads", "clip_layer": "study_area",
        },
    }
    monkeypatch.setattr(ai_service, "conversation_history", {"provenance": [{"role": "user", "content": "load roads"}]})
    monkeypatch.setattr(tools, "_registered_layers", {
        "长沙_roads": {"geojson": _GEOJSON, "geometry_types": ["LineString"], "provenance": provenance}
    })

    saved = project_service.auto_save(
        session_id="provenance", layer_assignments=[{"registry_name": "长沙_roads", "names": ["长沙_roads"]}]
    )
    loaded = project_service.load_project(saved["id"])
    assert loaded["layers"][0]["provenance"] == provenance
    exported = project_service.export_project(saved["id"])
    imported = project_service.import_project(exported)
    reimported = project_service.load_project(imported["id"])
    assert reimported["layers"][0]["provenance"] == provenance
    project_service.activate_project(saved["id"], session_id="provenance-restored")
    restored = tools.get_registered_layers_snapshot()
    assert restored[0]["provenance"] == provenance


def test_project_export_deduplicates_shared_vector_blob_members(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="重复数据工程", session_id="duplicate-geojson", provider="test",
        map_state={}, messages=[], layers=[
            {"name": "points_a", "geojson": _GEOJSON},
            {"name": "points_b", "geojson": _GEOJSON},
        ],
    )

    exported = project_service.export_project(saved["id"])
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        blob_members = [name for name in archive.namelist() if name.startswith("blobs/")]
        assert len(blob_members) == 1

    imported = project_service.import_project(exported)
    restored = project_service.load_project(imported["id"])
    assert [layer["name"] for layer in restored["layers"]] == ["points_a", "points_b"]
    assert [layer["geojson"] for layer in restored["layers"]] == [_GEOJSON, _GEOJSON]


def test_open_project_registers_valid_layers_when_another_layer_is_invalid(tmp_path, monkeypatch):
    from backend.services import tools

    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="混合图层工程", session_id="mixed-layers", provider="test",
        map_state={}, messages=[], layers=[
            {"name": "坏图层", "geojson": {"type": "FeatureCollection", "features": [None]}},
            {"name": "好图层", "geojson": _GEOJSON},
        ],
    )
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    load_project = project_service.load_project
    load_calls = []

    def counted_load(pid):
        load_calls.append(pid)
        return load_project(pid)

    monkeypatch.setattr(project_service, "load_project", counted_load)

    opened = project_service.open_project(saved["id"])

    assert load_calls == [saved["id"]]
    assert [layer["name"] for layer in opened["layers"]] == ["坏图层", "好图层"]
    assert opened["registration_warnings"] == ["坏图层"]
    assert set(tools._registered_layers) == {"好图层"}


@pytest.mark.parametrize("assignment", [None, {}, {"names": "old"}, {"names": [None]},
                                        {"registry_name": 3}, {"registry_name": "missing"}])
def test_invalid_or_missing_layer_assignments_cannot_clear_saved_data(tmp_path, monkeypatch, assignment):
    from backend.services import ai_service, tools

    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(project_id=None, name="manual", session_id="manual", provider="test",
                                         map_state={}, messages=[], layers=[{"name": "old", "geojson": _GEOJSON}])
    monkeypatch.setattr(ai_service, "conversation_history", {})
    monkeypatch.setattr(tools, "_registered_layers", {"old": {"geojson": _GEOJSON}})
    with pytest.raises(ValueError):
        project_service.auto_save(session_id="manual", project_id=saved["id"], layer_assignments=[assignment])
    assert project_service._load_project_data(saved["id"])["layers"][0]["name"] == "old"


def test_project_round_trip_preserves_layer_groups(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)

    saved = project_service.save_project(
        project_id=None,
        name="分组工程",
        session_id="group-session",
        provider="test",
        map_state={},
        messages=[],
        layers=[{"filename": "区域A", "geojson": _GEOJSON, "groupId": "group_3"}],
        layer_groups=[{"id": "group_3", "name": "重点区域", "collapsed": True}],
    )

    loaded = project_service.load_project(saved["id"])
    assert loaded["layerGroups"] == [{"id": "group_3", "name": "重点区域", "collapsed": True}]
    assert loaded["layers"][0]["groupId"] == "group_3"
    assert loaded["layers"][0]["geojson"] == _GEOJSON


def test_project_round_trip_preserves_stable_layer_id(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)

    saved = project_service.save_project(
        project_id=None,
        name="稳定图层工程",
        session_id="stable-layer-session",
        provider="test",
        map_state={},
        messages=[],
        layers=[{"layer_id": "layer-stable-123", "filename": "区域A", "geojson": _GEOJSON,
                 "style": {"color": "#336699", "fillOpacity": 0.24, "weight": 3},
                 "symbology": {"type": "graduated", "field": "population", "method": "quantile",
                               "breaks": [10, 20, 30], "legendData": {"items": [{"label": "10-20"}]}}}],
    )

    loaded = project_service.load_project(saved["id"])
    assert loaded["layers"][0]["layer_id"] == "layer-stable-123"
    assert loaded["layers"][0]["style"] == {"color": "#336699", "fillOpacity": 0.24, "weight": 3}
    assert loaded["layers"][0]["symbology"] == {
        "type": "graduated", "field": "population", "method": "quantile",
        "breaks": [10, 20, 30], "legendData": {"items": [{"label": "10-20"}]},
    }

    imported = project_service.import_project(project_service.export_project(saved["id"]))
    imported_project = project_service.load_project(imported["id"])
    assert imported_project["layers"][0]["layer_id"] == "layer-stable-123"


def test_service_layer_round_trip_keeps_safe_endpoint_and_reauthentication_metadata(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    secrets = ("USER_SECRET", "PASSWORD_SECRET", "CUSTOM_CODE_SECRET", "API_KEY_SECRET")
    service_url = (
        "https://user:USER_SECRET@tiles.example.test/wms/{z}/{x}/{y}"
        "?version=1.3.0&code=CUSTOM_CODE_SECRET&api_key=API_KEY_SECRET#FRAGMENT_SECRET"
    )
    saved = project_service.save_project(
        project_id=None,
        name="外部服务工程",
        session_id="service-session",
        provider="test",
        map_state={},
        messages=[],
        layers=[{
            "layer_id": "service-layer-1",
            "filename": "需要重新授权的底图",
            "url": service_url,
            "service_type": "xyz",
            "requires_auth": True,
            "auth_parameter": "code",
            "geometry_type": "XYZ",
            "opacity": 0.6,
        }],
    )

    loaded = project_service.load_project(saved["id"])
    layer = loaded["layers"][0]
    assert layer["url"] == "https://tiles.example.test/wms/{z}/{x}/{y}?version=1.3.0"
    assert layer["service_type"] == "xyz"
    assert layer["requires_auth"] is True
    assert layer["auth_parameter"] == "code"
    assert layer["layer_id"] == "service-layer-1"
    assert layer["opacity"] == 0.6

    exported = project_service.export_project(saved["id"])
    imported = project_service.import_project(exported)
    imported_layer = project_service.load_project(imported["id"])["layers"][0]
    assert imported_layer["url"] == layer["url"]
    assert imported_layer["requires_auth"] is True
    assert imported_layer["auth_parameter"] == "code"
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        serialized_export = archive.read("project.json").decode("utf-8")
    for secret in (*secrets, "FRAGMENT_SECRET"):
        assert secret not in serialized_export


def test_legacy_service_credentials_are_redacted_on_load_and_export(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None,
        name="旧服务工程",
        session_id="legacy-service-session",
        provider="test",
        map_state={},
        messages=[],
        layers=[{"filename": "旧 XYZ", "url": "https://tiles.example.test/{z}/{x}/{y}",
                 "service_type": "XYZ", "geometry_type": "XYZ瓦片"}],
    )
    legacy = project_service._load_project_data(saved["id"])
    legacy["layers"][0]["url"] = (
        "https://user:LEGACY_PASSWORD@tiles.example.test/{z}/{x}/{y}"
        "?api_key=LEGACY_API_KEY&style=light#LEGACY_FRAGMENT"
    )
    project_service._save_project_data(saved["id"], legacy)

    loaded_layer = project_service.load_project(saved["id"])["layers"][0]
    assert loaded_layer["url"] == "https://tiles.example.test/{z}/{x}/{y}?style=light"
    assert loaded_layer["requires_auth"] is True
    assert loaded_layer["auth_parameter"] == "api_key"

    exported = project_service.export_project(saved["id"])
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        serialized = archive.read("project.json").decode("utf-8")
    assert "LEGACY_PASSWORD" not in serialized
    assert "LEGACY_API_KEY" not in serialized
    assert "LEGACY_FRAGMENT" not in serialized

    imported = project_service.import_project(exported)
    imported_layer = project_service.load_project(imported["id"])["layers"][0]
    assert imported_layer["requires_auth"] is True
    assert imported_layer["auth_parameter"] == "api_key"

    legacy_archive = io.BytesIO()
    with zipfile.ZipFile(legacy_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", json.dumps({
            "name": "外部旧工程",
            "messages": [],
            "layers": [{
                "name": "外部 XYZ",
                "url": "https://tiles.example.test/{z}/{x}/{y}?token=IMPORTED_TOKEN&style=dark",
                "service_type": "XYZ",
            }],
        }))
    imported_legacy = project_service.import_project(legacy_archive.getvalue())
    imported_legacy_layer = project_service.load_project(imported_legacy["id"])["layers"][0]
    assert imported_legacy_layer["url"] == "https://tiles.example.test/{z}/{x}/{y}?style=dark"
    assert imported_legacy_layer["requires_auth"] is True
    assert imported_legacy_layer["auth_parameter"] == "token"
    assert "IMPORTED_TOKEN" not in json.dumps(project_service._load_project_data(imported_legacy["id"]))


def test_export_refuses_to_silently_omit_a_missing_vector_blob(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None,
        name="缺失矢量数据工程",
        session_id="missing-vector-blob",
        provider="test",
        map_state={},
        messages=[],
        layers=[{"filename": "区域A", "geojson": _GEOJSON}],
    )
    blob = project_service._load_project_data(saved["id"])["layers"][0]["blob"]
    os.remove(project_service._blob_path(blob))

    with pytest.raises(ValueError, match="矢量.*缺失|缺失.*矢量"):
        project_service.export_project(saved["id"])


def test_export_refuses_to_include_vector_blob_with_mismatched_content(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None,
        name="矢量数据校验工程",
        session_id="mismatched-vector-blob",
        provider="test",
        map_state={},
        messages=[],
        layers=[{"filename": "区域A", "geojson": _GEOJSON}],
    )
    blob = project_service._load_project_data(saved["id"])["layers"][0]["blob"]
    with open(project_service._blob_path(blob), "wb") as corrupted:
        corrupted.write(gzip.compress(b'{"type":"FeatureCollection","features":[]}'))

    with pytest.raises(ValueError, match="校验失败"):
        project_service.export_project(saved["id"])


def test_export_refuses_to_include_invalid_vector_blob_identifier(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None,
        name="无效矢量标识工程",
        session_id="invalid-vector-blob",
        provider="test",
        map_state={},
        messages=[],
        layers=[{"filename": "区域A", "geojson": _GEOJSON}],
    )
    project = project_service._load_project_data(saved["id"])
    project["layers"][0]["blob"] = ""
    project_service._save_project_data(saved["id"], project)

    with pytest.raises(ValueError, match="无效矢量图层数据"):
        project_service.export_project(saved["id"])


def test_project_round_trip_preserves_layer_opacity_separately(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="透明度工程", session_id="opacity-round-trip", provider="test",
        map_state={}, messages=[], layers=[{
            "filename": "区域A", "geojson": _GEOJSON,
            "style": {"color": "#112233", "fillOpacity": 0.18}, "opacity": 0.6,
        }],
    )

    layer = project_service.load_project(saved["id"])["layers"][0]
    assert layer["style"] == {"color": "#112233", "fillOpacity": 0.18}
    assert layer["opacity"] == 0.6


def test_autosave_keeps_group_for_registered_existing_layer(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    initial = project_service.save_project(
        project_id=None,
        name="自动保存工程",
        session_id="auto-group-session",
        provider="test",
        map_state={},
        messages=[],
        layers=[{"filename": "区域A", "geojson": _GEOJSON, "groupId": "group_2",
                 "style": {"color": "#112233", "opacity": 0.75},
                 "symbology": {"type": "unique", "field": "kind", "featureStyles": {"fid:n:A": {"color": "#abcdef"}}}}],
        layer_groups=[{"id": "group_2", "name": "分析结果", "collapsed": False}],
    )

    from backend.services import ai_service, tools

    monkeypatch.setattr(ai_service, "conversation_history", {
        "auto-group-session": [{"role": "user", "content": "继续分析"}]
    })
    monkeypatch.setattr(tools, "_registered_layers", {
        "区域A": {"geojson": _GEOJSON, "geometry_types": ["Point"], "feature_count": 1}
    })

    project_service.auto_save(
        session_id="auto-group-session", provider="test", project_id=initial["id"]
    )

    loaded = project_service.load_project(initial["id"])
    assert loaded["layerGroups"] == [{"id": "group_2", "name": "分析结果", "collapsed": False}]
    assert loaded["layers"][0]["name"] == "区域A"
    assert loaded["layers"][0]["groupId"] == "group_2"
    assert loaded["layers"][0]["style"] == {"color": "#112233", "opacity": 0.75}
    assert loaded["layers"][0]["symbology"]["type"] == "unique"

    project_service.auto_save(
        session_id="auto-group-session",
        provider="test",
        project_id=initial["id"],
        layer_groups=[{"id": "group_7", "name": "新分组", "collapsed": True}],
        layer_assignments=[{"names": ["区域A"], "groupId": "group_7"}],
    )
    moved = project_service.load_project(initial["id"])
    assert moved["layerGroups"] == [{"id": "group_7", "name": "新分组", "collapsed": True}]
    assert moved["layers"][0]["groupId"] == "group_7"

    project_service.auto_save(
        session_id="auto-group-session",
        provider="test",
        project_id=initial["id"],
        layer_groups=[{"id": "group_7", "name": "新分组", "collapsed": True}],
        layer_assignments=[{"names": ["区域A"], "groupId": "group_7", "visible": False,
                            "layer_id": "layer-stable-autosave",
                            "style": {"color": "#993344", "opacity": 0.6, "fillOpacity": 0.18}}],
    )
    hidden = project_service.load_project(initial["id"])
    assert hidden["layers"][0]["visible"] is False
    assert hidden["layers"][0]["groupId"] == "group_7"
    assert hidden["layers"][0]["layer_id"] == "layer-stable-autosave"
    assert hidden["layers"][0]["style"] == {"color": "#993344", "opacity": 0.6, "fillOpacity": 0.18}
    assert hidden["layers"][0]["symbology"]["type"] == "unique", "older callers omitting symbology must preserve it"

    project_service.auto_save(
        session_id="auto-group-session",
        provider="test",
        project_id=initial["id"],
        layer_groups=[{"id": "group_7", "name": "新分组", "collapsed": True}],
        layer_assignments=[{"names": ["区域A"], "layer_id": "layer-stable-autosave", "symbology": None}],
    )
    cleared = project_service.load_project(initial["id"])
    assert cleared["layers"][0]["symbology"] is None, "an explicit null clears the saved thematic style"


def test_autosave_keeps_layer_opacity_separate_from_base_style(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    from backend.services import ai_service, tools
    monkeypatch.setattr(ai_service, "conversation_history", {
        "opacity-session": [{"role": "user", "content": "保存透明度"}]
    })
    monkeypatch.setattr(tools, "_registered_layers", {
        "区域A": {"geojson": _GEOJSON, "geometry_types": ["Point"], "feature_count": 1}
    })

    saved = project_service.auto_save(
        session_id="opacity-session", provider="test",
        layer_assignments=[{
            "names": ["区域A"], "style": {"color": "#112233", "fillOpacity": 0.18},
            "opacity": 0.6,
        }],
    )

    layer = project_service.load_project(saved["id"])["layers"][0]
    assert layer["style"] == {"color": "#112233", "fillOpacity": 0.18}
    assert layer["opacity"] == 0.6


@pytest.mark.parametrize("member_name", [
    "../pwned.txt",
    r"..\pwned.txt",
    "/tmp/pwned.txt",
    "C:/pwned.txt",
])
def test_project_import_rejects_unsafe_archive_paths_before_extract(
    tmp_path, monkeypatch, member_name
):
    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(project_service, "_generate_id", lambda: "import-test")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("project.json", json.dumps({"layers": [], "messages": []}))
        zf.writestr(member_name, b"outside project")

    with pytest.raises(ValueError, match="不安全路径"):
        project_service.import_project(archive.getvalue())

    project_root = tmp_path / "projects"
    assert not (project_root / "pwned.txt").exists()
    assert not (tmp_path / "tmp" / "pwned.txt").exists()
    assert not (project_root / "proj_import-test").exists()


def test_new_project_id_collision_does_not_replace_existing_project(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    generated_ids = iter(["collision-id", "collision-id", "fresh-id"])
    monkeypatch.setattr(project_service, "_generate_id", lambda: next(generated_ids))
    first = project_service.save_project(
        project_id=None, name="保留工程", session_id="first", provider="test",
        map_state={}, messages=[{"role": "user", "content": "keep"}], layers=[],
    )

    second = project_service.save_project(
        project_id=None, name="新工程", session_id="second", provider="test",
        map_state={}, messages=[], layers=[],
    )

    assert second["id"] == "fresh-id"
    assert project_service.load_project(first["id"])["name"] == "保留工程"
    assert project_service.load_project(second["id"])["name"] == "新工程"


def test_failed_import_id_collision_does_not_delete_existing_project(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    existing = project_service.save_project(
        project_id="collision-import", name="必须保留", session_id="existing",
        provider="test", map_state={}, messages=[], layers=[],
    )
    generated_ids = iter([existing["id"], "fresh-import"])
    monkeypatch.setattr(project_service, "_generate_id", lambda: next(generated_ids))

    with pytest.raises(ValueError, match="ZIP 包损坏"):
        project_service.import_project(b"not a zip archive")

    assert project_service.load_project(existing["id"])["name"] == "必须保留"


def test_project_import_rejects_symbolic_link_entries_before_extract(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(project_service, "_generate_id", lambda: "symlink-import")
    archive = io.BytesIO()
    link = zipfile.ZipInfo("assets/linked.tif")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"layers": [], "messages": []}))
        zipped.writestr(link, "../../outside.tif")

    with pytest.raises(ValueError, match="不安全路径"):
        project_service.import_project(archive.getvalue())

    assert not (tmp_path / "projects" / "proj_symlink-import").exists()
    assert not (tmp_path / "outside.tif").exists()


@pytest.mark.parametrize("duplicate_name", ["project.json", "PROJECT.JSON", "project.json.", "project.json "])
def test_project_import_rejects_duplicate_windows_path_aliases(tmp_path, monkeypatch, duplicate_name):
    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(project_service, "_generate_id", lambda: "duplicate-path-import")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"name": "first", "layers": [], "messages": []}))
        zipped.writestr(duplicate_name, json.dumps({"name": "second", "layers": [], "messages": []}))

    with pytest.raises(ValueError, match="重复的文件路径"):
        project_service.import_project(archive.getvalue())

    assert not (tmp_path / "projects" / "proj_duplicate-path-import").exists()


@pytest.mark.parametrize("member_name", [
    "assets/CON.txt", "assets/NUL", "assets/COM1.geojson.gz", "assets/LPT³.tif",
])
def test_project_import_rejects_windows_reserved_device_path_components(
    tmp_path, monkeypatch, member_name,
):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_id = "reserved-device-import"
    monkeypatch.setattr(project_service, "_generate_id", lambda: project_id)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"layers": [], "messages": []}))
        zipped.writestr(member_name, b"must not reach a device path")

    with pytest.raises(ValueError, match="保留设备名"):
        project_service.import_project(archive.getvalue())

    assert not (tmp_path / "projects" / f"proj_{project_id}").exists()


def test_project_import_replaces_non_string_name_with_safe_default(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({
            "name": {"unexpected": "object"}, "layers": [], "messages": [],
        }))

    imported = project_service.import_project(archive.getvalue())
    expected_name = f"导入工程 {imported['id'][:4]}"

    assert imported["name"] == expected_name
    assert project_service.load_project(imported["id"])["name"] == expected_name
    assert project_service._load_index()["projects"][imported["id"]]["name"] == expected_name


@pytest.mark.parametrize(
    "limit_name,archive_members,error_match",
    [
        ("_MAX_PROJECT_ARCHIVE_ENTRIES", [("project.json", b'{"layers":[],"messages":[]}'), ("extra", b"x")], "条目过多"),
        ("_MAX_PROJECT_ARCHIVE_EXPANDED_BYTES", [("project.json", b'{"layers":[],"messages":[]}'), ("assets/data.tif", b"x" * 40)], "解压后超过"),
    ],
)
def test_project_import_rejects_archive_limits_before_extract(
    tmp_path, monkeypatch, limit_name, archive_members, error_match
):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_id = "oversized-import"
    monkeypatch.setattr(project_service, "_generate_id", lambda: project_id)
    monkeypatch.setattr(project_service, limit_name, 1 if "ENTRIES" in limit_name else 64)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, content in archive_members:
            zipped.writestr(name, content)

    with pytest.raises(ValueError, match=error_match):
        project_service.import_project(archive.getvalue())

    assert not (tmp_path / "projects" / f"proj_{project_id}").exists()
    assert project_service._load_index()["projects"] == {}


def test_project_import_rejects_oversized_compressed_archive(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_id = "compressed-oversized-import"
    monkeypatch.setattr(project_service, "_generate_id", lambda: project_id)
    monkeypatch.setattr(project_service, "_MAX_PROJECT_ARCHIVE_COMPRESSED_BYTES", 1)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"layers": [], "messages": []}))

    with pytest.raises(ValueError, match="压缩包超过"):
        project_service.import_project(archive.getvalue())

    assert not (tmp_path / "projects" / f"proj_{project_id}").exists()
    assert project_service._load_index()["projects"] == {}


def test_project_import_respects_project_count_limit_without_evicting_existing_data(
    tmp_path, monkeypatch,
):
    _use_temp_project_store(tmp_path, monkeypatch)
    monkeypatch.setattr(project_service, "_MAX_PROJECTS", 1)
    existing = project_service.save_project(
        project_id=None, name="必须保留", session_id="existing", provider="test",
        map_state={}, messages=[], layers=[],
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"name": "导入工程", "layers": [], "messages": []}))

    with pytest.raises(ValueError, match="工程数量已达到上限"):
        project_service.import_project(archive.getvalue())

    assert project_service.load_project(existing["id"])["name"] == "必须保留"
    assert [project["id"] for project in project_service.list_projects()] == [existing["id"]]
    assert len(list((tmp_path / "projects").glob("proj_*"))) == 1


def test_project_import_accepts_seekable_upload_stream_without_copying_to_bytes(tmp_path, monkeypatch):
    import asyncio
    from fastapi import UploadFile
    from backend import main

    _use_temp_project_store(tmp_path, monkeypatch)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"layers": [], "messages": []}))

    upload = UploadFile(filename="project.giswork", file=io.BytesIO(archive.getvalue()))
    original_import = project_service.import_project
    imported_sources = []

    def track_source(source):
        imported_sources.append(source)
        return original_import(source)

    monkeypatch.setattr(project_service, "import_project", track_source)
    result = asyncio.run(main.import_project(upload))

    assert len(imported_sources) == 1
    assert hasattr(imported_sources[0], "read")
    assert result["id"]
    assert project_service.load_project(result["id"])["layers"] == []


def test_project_import_reports_success_when_index_write_fails(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main

    _use_temp_project_store(tmp_path, monkeypatch)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"name": "索引异常导入", "layers": [], "messages": []}))

    def fail_index_write(_index):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(project_service, "_save_index", fail_index_write)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/projects/import",
            files={"file": ("project.giswork", archive.getvalue(), "application/zip")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"]
    assert payload["name"] == "索引异常导入"
    assert "warning" in payload
    assert project_service.load_project(payload["id"])["name"] == "索引异常导入"
    assert [project["id"] for project in project_service.list_projects()] == [payload["id"]]


def test_project_import_body_limit_rejects_declared_oversize_before_parsing():
    import asyncio
    from backend.main import ProjectImportBodyLimitMiddleware

    app_called = False
    events = []

    async def downstream(scope, receive, send):
        nonlocal app_called
        app_called = True

    async def receive():
        raise AssertionError("oversized declared body should be rejected before reading")

    async def send(event):
        events.append(event)

    scope = {
        "type": "http", "method": "POST", "path": "/api/projects/import",
        "headers": [(b"content-length", b"6")],
    }
    middleware = ProjectImportBodyLimitMiddleware(downstream, max_body_bytes=5)
    asyncio.run(middleware(scope, receive, send))

    assert not app_called
    assert events[0]["status"] == 413
    assert "工程导入请求体超出允许大小" in events[1]["body"].decode("utf-8")


def test_project_import_body_limit_counts_chunked_requests():
    import asyncio
    from backend.main import ProjectImportBodyLimitMiddleware

    events = []
    chunks = iter([
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"56", "more_body": False},
    ])

    async def receive():
        return next(chunks)

    async def send(event):
        events.append(event)

    async def downstream(scope, limited_receive, send_response):
        while True:
            message = await limited_receive()
            if message["type"] == "http.request" and not message.get("more_body", False):
                break

    scope = {"type": "http", "method": "POST", "path": "/api/projects/import", "headers": []}
    middleware = ProjectImportBodyLimitMiddleware(downstream, max_body_bytes=5)
    asyncio.run(middleware(scope, receive, send))

    assert events[0]["status"] == 413
    assert "工程导入请求体超出允许大小" in events[1]["body"].decode("utf-8")


def test_project_import_body_limit_is_wired_before_fastapi_upload_parsing(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main

    middleware_config = next(
        item for item in main.app.user_middleware
        if item.cls is main.ProjectImportBodyLimitMiddleware
        and item.kwargs.get("path", "/api/projects/import") == "/api/projects/import"
    )
    original_limit = middleware_config.kwargs["max_body_bytes"]
    original_stack = main.app.middleware_stack
    middleware_config.kwargs["max_body_bytes"] = 512
    main.app.middleware_stack = None

    def import_should_not_run(_file):
        raise AssertionError("oversized upload must be rejected before the route")

    monkeypatch.setattr(main.project_service, "import_project", import_should_not_run)
    try:
        response = TestClient(main.app).post(
            "/api/projects/import",
            files={"file": ("large.giswork", b"x" * 1024, "application/zip")},
        )
    finally:
        middleware_config.kwargs["max_body_bytes"] = original_limit
        main.app.middleware_stack = original_stack

    assert response.status_code == 413
    assert "工程导入请求体超出允许大小" in response.json()["detail"]


@pytest.mark.parametrize("blob_member", [
    None,
    b"not a gzip stream",
    gzip.compress(b'{"type":"FeatureCollection","features":[]}'),
], ids=["missing", "corrupt", "mismatched"])
def test_project_import_rejects_missing_or_corrupt_vector_blob_and_cleans_staging(
    tmp_path, monkeypatch, blob_member
):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_id = "bad-blob-import"
    monkeypatch.setattr(project_service, "_generate_id", lambda: project_id)
    blob = "0123456789ab"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({
            "layers": [{"name": "missing-vector", "blob": blob}], "messages": [],
        }))
        if blob_member is not None:
            zipped.writestr(f"blobs/{blob}.geojson.gz", blob_member)

    with pytest.raises(ValueError, match="矢量图层数据"):
        project_service.import_project(archive.getvalue())

    assert not (tmp_path / "projects" / f"proj_{project_id}").exists()
    assert project_service._load_index()["projects"] == {}


def test_project_import_bounds_nested_gzip_blob_expansion_and_cleans_staging(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_id = "gzip-bomb-import"
    monkeypatch.setattr(project_service, "_generate_id", lambda: project_id)
    monkeypatch.setattr(project_service, "_MAX_PROJECT_BLOB_EXPANDED_BYTES", 1024)
    raw_blob = b"A" * 4096
    blob = hashlib.sha256(raw_blob).hexdigest()[:12]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({
            "layers": [{"name": "points", "blob": blob}], "messages": [],
        }))
        zipped.writestr(f"blobs/{blob}.geojson.gz", gzip.compress(raw_blob))
    assert len(archive.getvalue()) < len(raw_blob)

    with pytest.raises(ValueError, match="矢量数据解压后超过"):
        project_service.import_project(archive.getvalue())

    assert not (tmp_path / "projects" / f"proj_{project_id}").exists()
    assert project_service._load_index()["projects"] == {}
    assert not (tmp_path / "projects" / "blobs" / f"{blob}.geojson.gz").exists()


def test_project_import_counts_referenced_compressed_blob_only_once(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_id = "shared-gzip-import"
    monkeypatch.setattr(project_service, "_generate_id", lambda: project_id)
    raw_blob = json.dumps(_GEOJSON, ensure_ascii=False, sort_keys=True).encode("utf-8")
    monkeypatch.setattr(project_service, "_MAX_PROJECT_BLOB_EXPANDED_BYTES", len(raw_blob))
    blob = hashlib.sha256(raw_blob).hexdigest()[:12]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({
            "layers": [
                {"name": "points-a", "blob": blob},
                {"name": "points-b", "blob": blob},
            ],
            "messages": [],
        }))
        zipped.writestr(f"blobs/{blob}.geojson.gz", gzip.compress(raw_blob))

    imported = project_service.import_project(archive.getvalue())

    assert imported["id"] == project_id
    assert [layer["geojson"] for layer in project_service.load_project(project_id)["layers"]] == [
        _GEOJSON, _GEOJSON,
    ]


def test_project_import_does_not_persist_unreferenced_archive_blobs(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"layers": [], "messages": []}))
        zipped.writestr("blobs/not-a-blob-id.geojson.gz", b"unreferenced archive data")

    imported = project_service.import_project(archive.getvalue())

    assert project_service.load_project(imported["id"])["layers"] == []
    assert not (tmp_path / "projects" / "blobs" / "not-a-blob-id.geojson.gz").exists()


@pytest.mark.parametrize("preexisting_blob", [False, True], ids=["new-blob", "shared-blob"])
def test_project_import_cleans_failed_staging_without_removing_existing_blobs(
    tmp_path, monkeypatch, preexisting_blob
):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_id = "write-failure-import"
    monkeypatch.setattr(project_service, "_generate_id", lambda: project_id)
    raw_geojson = json.dumps(_GEOJSON, ensure_ascii=False, sort_keys=True).encode("utf-8")
    blob = hashlib.sha256(raw_geojson).hexdigest()[:12]
    global_blob = tmp_path / "projects" / "blobs" / f"{blob}.geojson.gz"
    if preexisting_blob:
        global_blob.parent.mkdir(parents=True, exist_ok=True)
        global_blob.write_bytes(gzip.compress(raw_geojson))
        project_service._blob_refcount[blob] = 1
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({
            "layers": [{"name": "points", "blob": blob}], "messages": [],
        }))
        zipped.writestr(f"blobs/{blob}.geojson.gz", gzip.compress(raw_geojson))

    def fail_project_write(_pid, _data):
        raise OSError("simulated project file write failure")

    monkeypatch.setattr(project_service, "_save_project_data", fail_project_write)
    with pytest.raises(OSError, match="simulated project file write failure"):
        project_service.import_project(archive.getvalue())

    assert not (tmp_path / "projects" / f"proj_{project_id}").exists()
    assert global_blob.exists() is preexisting_blob
    assert project_service._load_index()["projects"] == {}


def test_project_import_repairs_a_corrupt_shared_blob_from_verified_archive(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    existing = project_service.save_project(
        project_id=None, name="已有工程", session_id="existing-blob", provider="test",
        map_state={}, messages=[], layers=[{"name": "points", "geojson": _GEOJSON}],
    )
    existing_blob = project_service._load_project_data(existing["id"])["layers"][0]["blob"]
    global_blob = tmp_path / "projects" / "blobs" / f"{existing_blob}.geojson.gz"
    global_blob.write_bytes(b"corrupt cache entry")

    imported_id = "repair-shared-blob"
    monkeypatch.setattr(project_service, "_generate_id", lambda: imported_id)
    raw_geojson = json.dumps(_GEOJSON, ensure_ascii=False, sort_keys=True).encode("utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({
            "layers": [{"name": "points", "blob": existing_blob}], "messages": [],
        }))
        zipped.writestr(f"blobs/{existing_blob}.geojson.gz", gzip.compress(raw_geojson))

    imported = project_service.import_project(archive.getvalue())

    assert imported["id"] == imported_id
    assert project_service.load_project(existing["id"])["layers"][0]["geojson"] == _GEOJSON
    assert project_service.load_project(imported_id)["layers"][0]["geojson"] == _GEOJSON


@pytest.mark.parametrize("target_directory", [False, True], ids=["file-link", "directory-link"])
def test_delete_all_removes_project_symlink_without_touching_its_target(
    tmp_path, monkeypatch, target_directory
):
    _use_temp_project_store(tmp_path, monkeypatch)
    project_root = tmp_path / "projects"
    project_root.mkdir(parents=True)
    outside = tmp_path / "outside-target"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep outside data", encoding="utf-8")
    target = outside if target_directory else sentinel
    link = project_root / "proj_outside"
    try:
        link.symlink_to(target, target_is_directory=target_directory)
    except OSError as exc:
        pytest.skip(f"local symlink creation unavailable: {exc}")

    result = project_service.delete_all_projects()

    assert not link.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "keep outside data"
    assert result.get("success", True) is True


@pytest.mark.parametrize("target_directory", [False, True], ids=["file-link", "directory-link"])
def test_delete_project_removes_project_symlink_without_touching_its_target(
    tmp_path, monkeypatch, target_directory
):
    from fastapi.testclient import TestClient
    from backend import main

    _use_temp_project_store(tmp_path, monkeypatch)
    project_root = tmp_path / "projects"
    project_root.mkdir(parents=True)
    outside = tmp_path / "outside-target"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep outside data", encoding="utf-8")
    target = outside if target_directory else sentinel
    link = project_root / "proj_outside"
    try:
        link.symlink_to(target, target_is_directory=target_directory)
    except OSError as exc:
        pytest.skip(f"local symlink creation unavailable: {exc}")

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.delete("/api/projects/outside")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert not link.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "keep outside data"


def test_failed_import_does_not_remove_blob_committed_by_another_process(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    import_id = "failing-import"
    monkeypatch.setattr(project_service, "_generate_id", lambda: import_id)
    raw_geojson = json.dumps(_GEOJSON, ensure_ascii=False, sort_keys=True).encode("utf-8")
    blob = hashlib.sha256(raw_geojson).hexdigest()[:12]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project.json", json.dumps({
            "layers": [{"name": "points", "blob": blob}], "messages": [],
        }))
        zipped.writestr(f"blobs/{blob}.geojson.gz", gzip.compress(raw_geojson))

    process_context = multiprocessing.get_context("spawn")
    result_queue = process_context.Queue()
    child_started = process_context.Event()
    child_completed = process_context.Event()
    child = None

    def fail_import_after_other_instance_starts(pid, data):
        nonlocal child
        if pid == import_id:
            child = process_context.Process(
                target=_import_project_in_subprocess,
                args=(str(project_service._PROJECT_DIR), archive.getvalue(), result_queue,
                      child_started, child_completed),
            )
            child.start()
            assert child_started.wait(timeout=10), "the second app instance should reach the import attempt"
            assert not child_completed.wait(timeout=0.25), "the second instance must wait for the shared-store lock"
            raise OSError("simulated import write failure while another instance waits")

    monkeypatch.setattr(project_service, "_save_project_data", fail_import_after_other_instance_starts)
    with pytest.raises(OSError, match="another instance waits"):
        project_service.import_project(archive.getvalue())
    assert child is not None
    child.join(timeout=15)
    assert not child.is_alive(), "the other app instance should finish after the failed import releases its lock"
    child_status, child_result = result_queue.get(timeout=2)
    assert child_status == "ok", child_result

    recovered = project_service.load_project(child_result)
    assert recovered["layers"][0]["geojson"] == _GEOJSON


def test_stale_process_blob_refcount_does_not_remove_other_projects_blob(tmp_path, monkeypatch):
    _use_temp_project_store(tmp_path, monkeypatch)
    process_context = multiprocessing.get_context("spawn")
    ready = process_context.Event()
    command_queue = process_context.Queue()
    result_queue = process_context.Queue()
    child = process_context.Process(
        target=_project_delete_worker,
        args=(str(project_service._PROJECT_DIR), ready, command_queue, result_queue),
    )
    child.start()
    assert ready.wait(timeout=10), "the second app instance should initialize with an empty store"

    def save_shared_project(name, session_id):
        return project_service.save_project(
            project_id=None, name=name, session_id=session_id, provider="test",
            map_state={}, messages=[], layers=[{"name": "points", "geojson": _GEOJSON}],
        )

    first = save_shared_project("first", "first-session")
    second = save_shared_project("second", "second-session")
    command_queue.put(first["id"])
    child.join(timeout=15)
    assert not child.is_alive(), "the other app instance should finish deleting the first project"
    child_status, child_result = result_queue.get(timeout=2)
    assert child_status == "ok", child_result

    recovered = project_service.load_project(second["id"])
    assert recovered["layers"][0]["geojson"] == _GEOJSON
