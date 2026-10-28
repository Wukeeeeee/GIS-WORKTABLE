import threading

import pytest

from backend.services import tools
from backend.services import project_service


def _points():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"id": "a", "group": "", "value": 1},
             "geometry": {"type": "Point", "coordinates": [120.0, 30.0]}},
            {"type": "Feature", "properties": {"id": "b", "group": "x", "value": 2},
             "geometry": {"type": "Point", "coordinates": [121.0, 31.0]}},
        ],
    }


def setup_function():
    tools.reset_registered_layers([])
    tools.reset_state()


def teardown_function():
    tools.reset_registered_layers([])
    tools.reset_state()


def test_register_normalizes_feature_and_keeps_unique_stable_ids_on_replacement():
    geojson = _points()
    geojson["features"][0]["properties"]["_fid"] = "duplicate"
    geojson["features"][1]["properties"]["_fid"] = "duplicate"
    tools._register_layer("places", geojson)
    first = tools._registered_layers["places"]
    layer_id = first["layer_id"]
    fids = [feature["properties"]["_fid"] for feature in first["geojson"]["features"]]
    assert len(set(fids)) == 2
    assert fids == ["duplicate", "id:b"]

    tools._register_layer("places", _points())
    current = tools._registered_layers["places"]
    assert current["layer_id"] == layer_id
    assert current["feature_count"] == 2
    assert current["bbox"] == [120.0, 30.0, 121.0, 31.0]


def test_gdf_to_layer_does_not_push_result_when_registration_validation_fails():
    import geopandas as gpd
    from shapely.geometry import Point

    result = gpd.GeoDataFrame(
        {"value": [1]},
        geometry=[Point(float("inf"), 0)],
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="GeoJSON"):
        tools._gdf_to_layer(result, "invalid-result")

    assert tools.get_pending_state()["layers"] == []
    assert "invalid-result" not in tools._registered_layers


@pytest.mark.parametrize("bounds", ([True, 0, 1, 1], [0, False, 1, 1]))
def test_raster_registration_rejects_boolean_bounds(bounds):
    from fastapi.testclient import TestClient
    from backend.main import app

    response = TestClient(app).post("/api/layer/register", json={
        "name": "invalid-raster", "raster": {"bounds": bounds},
    })

    assert response.status_code == 400
    assert "WGS-84" in response.json()["detail"]
    assert "invalid-raster" not in tools._registered_layers


@pytest.mark.parametrize("coordinates", ([True, 30], ["foo", 30], [None, 30], [1]))
def test_vector_registration_rejects_malformed_coordinates(coordinates):
    from fastapi.testclient import TestClient
    from backend.main import app

    response = TestClient(app).post("/api/layer/register", json={
        "name": "invalid-vector",
        "geojson": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Point", "coordinates": coordinates},
            }],
        },
    })

    assert response.status_code == 400
    assert "坐标" in response.json()["detail"]
    assert "invalid-vector" not in tools._registered_layers


@pytest.mark.parametrize("geometry", ({}, "not-a-geometry"))
def test_vector_registration_rejects_malformed_geometry_objects(geometry):
    from fastapi.testclient import TestClient
    from backend.main import app

    response = TestClient(app).post("/api/layer/register", json={
        "name": "invalid-vector",
        "geojson": {"type": "Feature", "properties": {}, "geometry": geometry},
    })

    assert response.status_code == 400
    assert "几何结构无效" in response.json()["detail"]


def test_null_geometry_and_empty_collections_remain_registerable():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    null_geometry = client.post("/api/layer/register", json={
        "name": "null-geometry",
        "geojson": {"type": "Feature", "properties": {}, "geometry": None},
    })
    empty_collection = client.post("/api/layer/register", json={
        "name": "empty-collection", "geojson": {"type": "FeatureCollection", "features": []},
    })

    assert null_geometry.status_code == 200
    assert empty_collection.status_code == 200


def test_layer_registration_api_reports_invalid_geojson_as_client_error():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    valid = client.post("/api/layer/register", json={
        "name": "api-layer", "geojson": _points(), "group_name": "分析结果",
    })
    assert valid.status_code == 200
    assert tools._registered_layers["api-layer"]["feature_count"] == 2
    assert tools._registered_layers["api-layer"]["group_name"] == "分析结果"
    assert "所属分组:「分析结果」" in tools.get_registered_layers.invoke({})
    invalid = client.post("/api/layer/register", json={"name": "invalid-layer", "geojson": {"type": "Unknown"}})
    assert invalid.status_code == 400
    assert "invalid-layer" not in tools._registered_layers


def test_layer_registration_api_rejects_wgs84_out_of_range_coordinates():
    from fastapi.testclient import TestClient
    from backend.main import app

    response = TestClient(app).post("/api/layer/register", json={
        "name": "out-of-range-layer",
        "geojson": {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [0, 100]},
        }]},
    })

    assert response.status_code == 400
    assert "WGS-84" in response.json()["detail"]
    assert "out-of-range-layer" not in tools._registered_layers


@pytest.mark.parametrize("second_payload", [
    {"geojson": _points()},
    {"raster": {"bounds": [0, 0, 1, 1]}},
])
def test_layer_registration_rejects_unicode_normalization_aliases(second_payload):
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    first = client.post("/api/layer/register", json={
        "name": "\u00e9.geojson", "geojson": _points(),
    })
    assert first.status_code == 200

    duplicate = client.post("/api/layer/register", json={
        "name": "e\u0301.geojson", **second_payload,
    })

    assert duplicate.status_code == 400
    assert "\u00e9.geojson" in duplicate.json()["detail"]
    assert list(tools._registered_layers) == ["\u00e9.geojson"]

    exact_replacement = client.post("/api/layer/register", json={
        "name": "\u00e9.geojson", "geojson": _points(),
    })
    assert exact_replacement.status_code == 200
    assert list(tools._registered_layers) == ["\u00e9.geojson"]


def test_project_restore_preserves_existing_unicode_alias_layer_names():
    legacy_layers = [
        {"name": "\u00e9.geojson", "geojson": _points()},
        {"name": "e\u0301.geojson", "geojson": _points()},
    ]

    skipped = tools.reset_registered_layers(legacy_layers)

    assert skipped == []
    assert list(tools._registered_layers) == ["\u00e9.geojson", "e\u0301.geojson"]


def test_unregister_legacy_unicode_alias_targets_exact_name_and_token():
    from fastapi.testclient import TestClient
    from backend.main import app

    composed = tools._register_layer("\u00e9.geojson", _points())
    decomposed = tools._register_layer(
        "e\u0301.geojson", _points(), allow_unicode_alias=True,
    )
    client = TestClient(app)

    removed_alias = client.post("/api/layer/unregister", json={
        "name": "e\u0301.geojson", "registration_token": decomposed,
    })
    stale_other = client.post("/api/layer/unregister", json={
        "name": "\u00e9.geojson", "registration_token": decomposed,
    })

    assert removed_alias.json()["removed"] is True
    assert stale_other.json()["removed"] is False
    assert stale_other.json()["stale"] is True
    assert list(tools._registered_layers) == ["\u00e9.geojson"]
    assert tools._registered_layers["\u00e9.geojson"]["registration_token"] == composed


def test_group_metadata_is_available_to_ai_and_can_be_cleared():
    tools._register_layer("grouped-places", _points(), group_name="重点区域")
    snapshot = tools.get_registered_layers_snapshot()
    assert snapshot[0]["group_name"] == "重点区域"
    assert "所属分组:「重点区域」" in tools.get_registered_layers.invoke({})

    tools._register_layer("grouped-places", _points())
    assert tools._registered_layers["grouped-places"]["group_name"] == "重点区域"

    tools._register_layer("grouped-places", _points(), group_name="")
    assert tools._registered_layers["grouped-places"]["group_name"] == ""


def test_attribute_mutations_refresh_registry_metadata_and_pending_map_data():
    tools._register_layer("places", _points())
    old_layer_id = tools._registered_layers["places"]["layer_id"]

    result = tools.update_attribute.invoke({
        "layer_name": "places", "field": "value", "value": "7",
        "condition_field": "group", "condition_value": "",
    })
    assert "1/2" in result
    current = tools._registered_layers["places"]
    assert [f["properties"]["value"] for f in current["geojson"]["features"]] == [7, 2]
    assert current["feature_count"] == 2
    assert current["layer_id"] == old_layer_id
    assert tools._pending_layers[-1]["geojson"] == current["geojson"]

    result = tools.delete_features.invoke({
        "layer_name": "places", "condition_field": "group", "condition_value": "x",
    })
    assert "1/2" in result
    current = tools._registered_layers["places"]
    assert current["feature_count"] == 1
    assert current["bbox"] == [120.0, 30.0, 120.0, 30.0]
    assert current["geojson"]["features"][0]["properties"]["_fid"]


def test_zero_default_is_kept_and_stable_fid_cannot_be_deleted():
    tools._register_layer("places", _points())
    result = tools.add_field.invoke({
        "layer_name": "places", "field_name": "rank", "field_type": "int", "default_value": "0",
    })
    assert "添加" in result
    assert [f["properties"]["rank"] for f in tools._registered_layers["places"]["geojson"]["features"]] == [0, 0]

    result = tools.delete_field.invoke({"layer_name": "places", "field_name": "_fid"})
    assert "不能删除" in result
    assert all("_fid" in f["properties"] for f in tools._registered_layers["places"]["geojson"]["features"])


def test_delete_features_accepts_explicit_empty_string_value():
    tools._register_layer("places", _points())
    result = tools.delete_features.invoke({
        "layer_name": "places", "condition_field": "group", "condition_value": "",
    })
    assert "1/2" in result
    assert [feature["properties"]["group"] for feature in tools._registered_layers["places"]["geojson"]["features"]] == ["x"]


def test_invalid_registration_is_reported_instead_of_silently_acknowledged():
    try:
        tools._register_layer("broken", {"type": "NotGeoJSON"})
    except ValueError as error:
        assert "GeoJSON" in str(error)
    else:
        raise AssertionError("invalid GeoJSON should be rejected")
    assert "broken" not in tools._registered_layers


def test_layer_management_never_removes_or_renames_ambiguous_or_empty_names():
    tools._register_layer("clinic east", _points())
    tools._register_layer("clinic west", _points())

    removed = tools.layer_control.invoke({"action": "remove", "name": "clinic"})
    renamed = tools.layer_control.invoke({"action": "rename", "name": "clinic", "new_name": "renamed"})
    empty = tools.layer_control.invoke({"action": "remove", "name": ""})

    assert "未执行操作" in removed
    assert "未执行操作" in renamed
    assert "未执行操作" in empty
    assert set(tools._registered_layers) == {"clinic east", "clinic west"}

    toggled = tools.layer_control.invoke({"action": "toggle", "name": "clinic east"})
    assert "显隐" in toggled
    assert "clinic east" in tools._registered_layers


def test_layer_management_exact_name_and_rename_collision_are_safe():
    tools._register_layer("clinic east", _points())
    tools._register_layer("clinic west", _points())
    original_id = tools._registered_layers["clinic east"]["layer_id"]

    conflict = tools.layer_control.invoke({
        "action": "rename", "name": "clinic east", "new_name": "clinic west",
    })
    assert "已存在" in conflict
    assert tools._tool_result_failed("layer_control", conflict)
    assert set(tools._registered_layers) == {"clinic east", "clinic west"}

    result = tools.layer_control.invoke({
        "action": "rename", "name": "clinic east", "new_name": "east branch",
    })
    assert "已重命名" in result
    assert tools._registered_layers["east branch"]["layer_id"] == original_id
    assert tools._registered_layers["east branch"]["name"] == "east branch"
    assert "clinic east" not in tools._registered_layers

    result = tools.layer_control.invoke({"action": "remove", "name": "east branch"})
    assert "已删除" in result
    assert set(tools._registered_layers) == {"clinic west"}


def test_attribute_mutation_requires_exact_layer_name_even_if_it_matches_a_feature_name():
    geojson = _points()
    geojson["features"][0]["properties"]["name"] = "hospital"
    tools._register_layer("hospital POI", geojson)

    result = tools.update_attribute.invoke({
        "layer_name": "hospital", "field": "value", "value": "99",
    })
    assert "完整图层名" in result and "未执行修改" in result
    values = [feature["properties"]["value"] for feature in tools._registered_layers["hospital POI"]["geojson"]["features"]]
    assert values == [1, 2]


def test_attribute_mutation_preserves_boolean_types_and_protects_fids():
    geojson = _points()
    for feature, active in zip(geojson["features"], (True, False)):
        feature["properties"]["active"] = active
    tools._register_layer("status layer", geojson)
    second_fid = tools._registered_layers["status layer"]["geojson"]["features"][1]["properties"]["_fid"]

    result = tools.update_attribute.invoke({
        "layer_name": "status layer", "field": "active", "value": "true",
        "condition_field": "_fid", "condition_value": second_fid,
    })
    assert "1/2" in result
    active_values = [feature["properties"]["active"] for feature in tools._registered_layers["status layer"]["geojson"]["features"]]
    assert active_values == [True, True]
    assert all(isinstance(value, bool) for value in active_values)

    result = tools.update_attribute.invoke({"layer_name": "status layer", "field": "_fid", "value": "changed"})
    assert "不能修改" in result
    assert tools.add_field.invoke({"layer_name": "status layer", "field_name": "_fid"}).find("保留字段") >= 0


def test_ai_layer_detail_does_not_expose_internal_feature_identity_as_a_field():
    tools._register_layer("places", _points())
    detail = tools.get_layer_detail.invoke({"layer_name": "places"})
    assert "_fid" not in detail.split("属性字段", 1)[-1]
    assert "稳定 ID: id:a" in detail


def test_registered_layer_snapshot_is_atomic_with_registry_mutation(monkeypatch):
    iteration_started = threading.Event()
    release_iteration = threading.Event()
    writer_started = threading.Event()
    writer_finished = threading.Event()
    errors = []

    class PausingRegistry(dict):
        def items(self):
            iterator = iter(super().items())
            yield next(iterator)
            iteration_started.set()
            assert release_iteration.wait(2)
            yield from iterator

    monkeypatch.setattr(tools, "_registered_layers", PausingRegistry({
        "base": {"geojson": {"features": []}, "feature_count": 0, "geometry_types": [], "bbox": []}
    }))
    monkeypatch.setattr(tools, "_layer_property_examples", lambda _geojson: [])

    def take_snapshot():
        try:
            tools.get_registered_layers_snapshot()
        except Exception as exc:
            errors.append(exc)

    def mutate_registry():
        writer_started.set()
        with tools._state_lock:
            tools._registered_layers["concurrent"] = {
                "geojson": {"features": []}, "feature_count": 0, "geometry_types": [], "bbox": []
            }
        writer_finished.set()

    reader = threading.Thread(target=take_snapshot)
    reader.start()
    try:
        assert iteration_started.wait(1)
        writer = threading.Thread(target=mutate_registry)
        writer.start()
        assert writer_started.wait(1)
        writer_finished_while_snapshot_paused = writer_finished.wait(0.05)
    finally:
        release_iteration.set()
        reader.join(1)
        if "writer" in locals():
            writer.join(1)

    assert not writer_finished_while_snapshot_paused
    assert not errors
    assert writer_finished.is_set()


def test_register_edit_rename_save_reload_delete_round_trip(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()

    tools._register_layer("clinic POI", _points())
    first_fid = tools._registered_layers["clinic POI"]["geojson"]["features"][0]["properties"]["_fid"]
    update = tools.update_attribute.invoke({
        "layer_name": "clinic POI", "field": "value", "value": "9",
        "condition_field": "_fid", "condition_value": first_fid,
    })
    assert "1/2" in update
    assert [f["properties"]["value"] for f in tools._registered_layers["clinic POI"]["geojson"]["features"]] == [9, 2]

    tools.add_field.invoke({"layer_name": "clinic POI", "field_name": "rank", "field_type": "int", "default_value": "0"})
    tools.delete_field.invoke({"layer_name": "clinic POI", "field_name": "group"})
    renamed = tools.layer_control.invoke({"action": "rename", "name": "clinic POI", "new_name": "clinics"})
    assert "已重命名" in renamed

    def save_current(project_id):
        info = tools._registered_layers.get("clinics")
        layers = [] if not info else [{
            "layer_id": info["layer_id"], "filename": "clinics", "geojson": info["geojson"],
            "geometry_type": ", ".join(info["geometry_types"]),
        }]
        return project_service.save_project(
            project_id=project_id, name="layer lifecycle", session_id="layer-lifecycle",
            provider="test", map_state={}, messages=[{"role": "user", "content": "round trip"}],
            layers=layers,
        )

    saved = save_current(None)
    tools.reset_registered_layers([])
    activated = project_service.activate_project(saved["id"], "layer-lifecycle")
    assert activated["layerCount"] == 1
    restored = tools._registered_layers["clinics"]["geojson"]["features"]
    assert [f["properties"]["value"] for f in restored] == [9, 2]
    assert [f["properties"]["rank"] for f in restored] == [0, 0]
    assert all("group" not in f["properties"] for f in restored)
    assert [f["properties"]["_fid"] for f in restored][0] == first_fid

    remaining_fid = restored[1]["properties"]["_fid"]
    deleted = tools.delete_features.invoke({
        "layer_name": "clinics", "condition_field": "_fid", "condition_value": remaining_fid,
    })
    assert "1/2" in deleted
    saved = save_current(saved["id"])
    tools.reset_registered_layers([])
    project_service.activate_project(saved["id"], "layer-lifecycle")
    restored = tools._registered_layers["clinics"]["geojson"]["features"]
    assert len(restored) == 1 and restored[0]["properties"]["_fid"] == first_fid

    removed = tools.layer_control.invoke({"action": "remove", "name": "clinics"})
    assert "已删除" in removed
    save_current(saved["id"])
    tools.reset_registered_layers([])
    activated = project_service.activate_project(saved["id"], "layer-lifecycle")
    assert activated["layerCount"] == 0
    assert tools._registered_layers == {}
