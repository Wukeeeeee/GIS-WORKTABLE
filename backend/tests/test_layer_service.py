from backend.services.layer_service import inspect_geojson


def _point_with_crs(crs_name):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {},
        "crs": {"type": "name", "properties": {"name": crs_name}},
    }


def test_inspector_does_not_mark_an_invalid_explicit_crs_as_known():
    result = inspect_geojson(_point_with_crs("EPSG:999999"))

    assert result["crs"] == "EPSG:999999"
    assert result["crs_known"] is False
    assert result["coordinate_units"] is None


def test_inspector_preserves_valid_non_default_crs_identifiers():
    result = inspect_geojson(_point_with_crs("EPSG:32649"))

    assert result["crs"] == "EPSG:32649"
    assert result["crs_known"] is True
    assert result["coordinate_units"] == "metre"


def test_inspector_normalizes_recognized_geographic_and_web_mercator_crs():
    geographic = inspect_geojson(_point_with_crs("urn:ogc:def:crs:OGC:1.3:CRS84"))
    mercator = inspect_geojson(_point_with_crs("EPSG:3857"))

    assert geographic["crs"] == "EPSG:4326 (WGS-84)"
    assert geographic["crs_known"] is True
    assert geographic["coordinate_units"] == "degree"
    assert mercator["crs"] == "EPSG:3857 (Web Mercator)"
    assert mercator["crs_known"] is True
    assert mercator["coordinate_units"] == "metre"


def test_inferred_geojson_crs_reports_degrees_and_unknown_crs_reports_no_units():
    inferred = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [100, 30]},
        "properties": {},
    })
    unknown = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [250, 120]},
        "properties": {},
    })

    assert inferred["coordinate_units"] == "degree"
    assert unknown["crs_known"] is False
    assert unknown["coordinate_units"] is None
