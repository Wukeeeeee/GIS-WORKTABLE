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


def test_inspect_geojson_rejects_boolean_coordinates():
    point_bool_x = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [True, 30]},
        "properties": {},
    })
    point_bool_y = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [100, False]},
        "properties": {},
    })
    linestring_bool = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[100, 30], [True, 31]]},
        "properties": {},
    })
    polygon_bool = inspect_geojson({
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[100, 30], [True, 30], [101, 31], [100, 30]]],
        },
        "properties": {},
    })

    assert point_bool_x["invalid_geom_count"] == 1
    assert point_bool_x["null_geom_count"] == 0
    assert point_bool_y["invalid_geom_count"] == 1
    assert point_bool_y["null_geom_count"] == 0
    assert linestring_bool["invalid_geom_count"] == 1
    assert linestring_bool["null_geom_count"] == 0
    assert polygon_bool["invalid_geom_count"] == 1
    assert polygon_bool["null_geom_count"] == 0


def test_inspect_geojson_rejects_string_and_nonnumeric_coordinates():
    point_str_both = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": ["100", "30"]},
        "properties": {},
    })
    point_str_y = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [100, "30"]},
        "properties": {},
    })
    point_nan = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float("nan"), 30]},
        "properties": {},
    })
    point_inf = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float("inf"), 30]},
        "properties": {},
    })
    point_single_ordinate = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [100]},
        "properties": {},
    })

    assert point_str_both["invalid_geom_count"] == 1
    assert point_str_both["null_geom_count"] == 0
    assert point_str_y["invalid_geom_count"] == 1
    assert point_nan["invalid_geom_count"] == 1
    assert point_inf["invalid_geom_count"] == 1
    assert point_single_ordinate["invalid_geom_count"] == 1


def test_inspect_geojson_rejects_malformed_nested_and_geometry_collection():
    geom_coords_null = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": None},
        "properties": {},
    })
    gc_geoms_null = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "GeometryCollection", "geometries": None},
        "properties": {},
    })
    gc_geoms_invalid_type = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "GeometryCollection", "geometries": "not-a-list"},
        "properties": {},
    })
    gc_mixed_child = inspect_geojson({
        "type": "Feature",
        "geometry": {
            "type": "GeometryCollection",
            "geometries": [
                {"type": "Point", "coordinates": [100, 30]},
                {"type": "Point", "coordinates": [True, 30]},
            ],
        },
        "properties": {},
    })
    nested_gc_malformed = inspect_geojson({
        "type": "Feature",
        "geometry": {
            "type": "GeometryCollection",
            "geometries": [
                {
                    "type": "GeometryCollection",
                    "geometries": [
                        {"type": "Point", "coordinates": ["100", "30"]},
                    ],
                }
            ],
        },
        "properties": {},
    })

    assert geom_coords_null["invalid_geom_count"] == 1
    assert gc_geoms_null["invalid_geom_count"] == 1
    assert gc_geoms_invalid_type["invalid_geom_count"] == 1
    assert gc_mixed_child["invalid_geom_count"] == 1
    assert nested_gc_malformed["invalid_geom_count"] == 1


def test_inspect_geojson_rejects_nested_empty_elements_in_non_empty_coordinates():
    polygon_nested_empty_ring = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[]]},
        "properties": {},
    })
    polygon_mixed_empty_ring = inspect_geojson({
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]], []],
        },
        "properties": {},
    })
    linestring_nested_empty_point = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[]]},
        "properties": {},
    })
    linestring_mixed_empty_point = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[100, 30], []]},
        "properties": {},
    })
    multipolygon_nested_empty = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": "MultiPolygon", "coordinates": [[[]]]},
        "properties": {},
    })

    assert polygon_nested_empty_ring["invalid_geom_count"] == 1
    assert polygon_mixed_empty_ring["invalid_geom_count"] == 1
    assert linestring_nested_empty_point["invalid_geom_count"] == 1
    assert linestring_mixed_empty_point["invalid_geom_count"] == 1
    assert multipolygon_nested_empty["invalid_geom_count"] == 1


def test_inspect_geojson_preserves_valid_and_empty_geometries_without_false_positives():
    valid_geoms = [
        {"type": "Point", "coordinates": [100, 30]},
        {"type": "Point", "coordinates": [100.5, 30.5, 15.0]},
        {"type": "LineString", "coordinates": [[100, 30], [101, 31]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
        {"type": "MultiPoint", "coordinates": [[100, 30], [101, 31]]},
        {"type": "MultiLineString", "coordinates": [[[100, 30], [101, 31]]]},
        {"type": "MultiPolygon", "coordinates": [[[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]]},
        {"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": [100, 30]}]},
        # Recognized empty geometries
        {"type": "Point", "coordinates": []},
        {"type": "LineString", "coordinates": []},
        {"type": "Polygon", "coordinates": []},
        {"type": "MultiPoint", "coordinates": []},
        {"type": "MultiLineString", "coordinates": []},
        {"type": "MultiPolygon", "coordinates": []},
        {"type": "GeometryCollection", "geometries": []},
        {"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": []}]},
    ]

    for g in valid_geoms:
        res = inspect_geojson({"type": "Feature", "geometry": g, "properties": {}})
        assert res["invalid_geom_count"] == 0, f"False positive invalid count for {g['type']}: {res}"
        assert res["null_geom_count"] == 0, f"False positive null count for {g['type']}: {res}"


def test_inspect_geojson_preserves_feature_null_geometry_as_null_count():
    feat_geom_none = inspect_geojson({
        "type": "Feature",
        "geometry": None,
        "properties": {},
    })

    assert feat_geom_none["null_geom_count"] == 1
    assert feat_geom_none["invalid_geom_count"] == 0


def test_inspect_geojson_counts_missing_or_empty_geometry_type_as_invalid():
    feat_geom_empty_type = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": ""},
        "properties": {},
    })
    feat_geom_missing_type = inspect_geojson({
        "type": "Feature",
        "geometry": {},
        "properties": {},
    })
    feat_geom_non_string_type = inspect_geojson({
        "type": "Feature",
        "geometry": {"type": 123},
        "properties": {},
    })

    assert feat_geom_empty_type["null_geom_count"] == 0
    assert feat_geom_empty_type["invalid_geom_count"] == 1
    assert feat_geom_missing_type["null_geom_count"] == 0
    assert feat_geom_missing_type["invalid_geom_count"] == 1
    assert feat_geom_non_string_type["null_geom_count"] == 0
    assert feat_geom_non_string_type["invalid_geom_count"] == 1


def test_inspect_geojson_feature_collection_mixed_summary():
    collection = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [100, 30]}, "properties": {"tag": "valid"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [True, 30]}, "properties": {"tag": "bool"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": ["100", "30"]}, "properties": {"tag": "str"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": []}, "properties": {"tag": "empty"}},
            {"type": "Feature", "geometry": None, "properties": {"tag": "null"}},
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[100, 30], [101, 31]]}, "properties": {"tag": "valid_line"}},
        ],
    }

    res = inspect_geojson(collection)
    assert res["feature_count"] == 6
    assert res["null_geom_count"] == 1
    assert res["invalid_geom_count"] == 2
    assert "Point" in res["geometry_type"]
    assert "LineString" in res["geometry_type"]
    assert res["bbox"] == [100.0, 30.0, 101.0, 31.0]
    assert res["crs"] == "EPSG:4326 (WGS-84)"
    assert res["crs_known"] is True
