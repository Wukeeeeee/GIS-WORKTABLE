from backend.services.geojson_precision import (
    protect_geojson_property_integers,
    restore_registered_integer_properties,
)
from backend.services import project_service, tools


def test_geojson_transport_encodes_unsafe_property_integers_but_not_coordinates():
    source = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [120, 30]},
            "properties": {"large": 9_007_199_254_740_993, "nested": {"large": -9_007_199_254_740_993}, "safe": 7},
        }],
    }

    result = protect_geojson_property_integers(source)

    assert result["features"][0]["properties"] == {
        "large": "9007199254740993",
        "nested": {"large": "-9007199254740993"},
        "safe": 7,
    }
    assert result["features"][0]["_gisworktable_integer_paths"] == [["large"], ["nested", "large"]]
    assert result["features"][0]["geometry"]["coordinates"] == [120, 30]
    assert source["features"][0]["properties"]["large"] == 9_007_199_254_740_993


def test_registered_integer_restore_preserves_rounded_copy_and_accepts_exact_text_edit():
    existing = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"_fid": "i:0", "large": 9_007_199_254_740_993}, "geometry": None,
    }]}
    incoming = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"_fid": "i:0", "large": 9_007_199_254_740_992}, "geometry": None,
    }]}

    restore_registered_integer_properties(existing, incoming)
    assert incoming["features"][0]["properties"]["large"] == 9_007_199_254_740_993

    incoming["features"][0]["properties"]["large"] = "9007199254740995"
    restore_registered_integer_properties(existing, incoming)
    assert incoming["features"][0]["properties"]["large"] == 9_007_199_254_740_995


def test_registered_integer_restore_uses_transport_metadata_for_nested_values():
    existing = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"nested": {"value": 9_007_199_254_740_993}}, "geometry": None,
    }]}
    incoming = protect_geojson_property_integers(existing)
    restore_registered_integer_properties(existing, incoming)
    assert incoming["features"][0]["properties"]["nested"]["value"] == 9_007_199_254_740_993
    assert "_gisworktable_integer_paths" not in incoming["features"][0]


def test_manual_project_save_uses_the_token_matched_registered_geojson(monkeypatch):
    exact = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"_fid": "i:0", "parcel_id": 9_007_199_254_740_993},
        "geometry": {"type": "Point", "coordinates": [120, 30]},
    }]}
    token = "active-registration-token"
    monkeypatch.setattr(tools, "_registered_layers", {"Parcels": {"geojson": exact, "registration_token": token}})
    saved = {}
    blobs = []
    monkeypatch.setattr(project_service, "_ensure_dirs", lambda: None)
    monkeypatch.setattr(project_service, "_load_index", lambda: {"projects": {}})
    monkeypatch.setattr(project_service, "_save_index", lambda index: None)
    monkeypatch.setattr(project_service, "_save_project_data", lambda pid, data: saved.update(data))
    monkeypatch.setattr(project_service, "_blob_put", lambda geojson: blobs.append(geojson) or "blob-test")
    monkeypatch.setattr(project_service, "_rebuild_refcount", lambda: None)
    monkeypatch.setattr(project_service, "_project_exists", lambda pid: False)

    rounded_transport_copy = protect_geojson_property_integers(exact)
    project_service.save_project(
        project_id=None,
        name="Big integer roundtrip",
        session_id="precision-test",
        provider="test",
        map_state={},
        messages=[],
        layers=[{
            "name": "Parcels",
            "filename": "Parcels",
            "_registeredName": "Parcels",
            "_registrationTokens": {"Parcels": token},
            "geojson": rounded_transport_copy,
        }],
    )

    assert blobs[0]["features"][0]["properties"]["parcel_id"] == 9_007_199_254_740_993
    assert saved["layers"][0]["blob"] == "blob-test"

