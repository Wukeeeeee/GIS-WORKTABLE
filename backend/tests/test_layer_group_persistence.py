"""Regression tests for project persistence and import validation."""

import gzip
import io
import json
import os
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
