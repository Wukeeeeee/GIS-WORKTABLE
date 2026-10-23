"""Regression tests for project persistence and import validation."""

import io
import json
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
