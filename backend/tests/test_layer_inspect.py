"""Tests for layer inspection service."""

import json
import pytest
from backend.services.layer_service import inspect_geojson


class TestInspectGeoJSON:
    """Test the inspect_geojson function."""

    def test_empty_feature_collection(self):
        """Empty FeatureCollection should return zero counts."""
        result = inspect_geojson({"type": "FeatureCollection", "features": []})
        assert result["feature_count"] == 0
        assert result["geometry_type"] == "无几何"
        assert result["attr_fields"] == {}
        assert result["bbox"] is None
        assert result["null_geom_count"] == 0

    def test_single_point(self):
        """Single Point feature."""
        gj = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
                "properties": {"name": "北京", "population": 2154}
            }]
        }
        result = inspect_geojson(gj)
        assert result["feature_count"] == 1
        assert "Point" in result["geometry_type"]
        assert result["attr_fields"] == {"name": "str", "population": "int"}
        assert result["attr_count"] == 2
        assert result["bbox"] == [116.4, 39.9, 116.4, 39.9]
        assert result["null_geom_count"] == 0

    def test_null_geometry(self):
        """Feature with null geometry should be counted."""
        gj = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": None, "properties": {"id": 1}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"id": 2}},
            ]
        }
        result = inspect_geojson(gj)
        assert result["feature_count"] == 2
        assert result["null_geom_count"] == 1

    def test_polygon_bbox(self):
        """Polygon should produce correct bbox."""
        gj = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]
                },
                "properties": {}
            }]
        }
        result = inspect_geojson(gj)
        assert result["bbox"] == [0, 0, 10, 10]

    def test_multi_polygon(self):
        """MultiPolygon geometry type detection."""
        gj = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]
                },
                "properties": {}
            }]
        }
        result = inspect_geojson(gj)
        assert "MultiPolygon" in result["geometry_type"]

    def test_multiple_geometry_types(self):
        """Multiple geometry types in one collection."""
        gj = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}},
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {}},
            ]
        }
        result = inspect_geojson(gj)
        assert "Point" in result["geometry_type"]
        assert "LineString" in result["geometry_type"]

    def test_single_feature(self):
        """A single Feature (not FeatureCollection) should also work."""
        gj = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"a": 1}}
        result = inspect_geojson(gj)
        assert result["feature_count"] == 1
        assert result["geometry_type"] == "Point"

    def test_property_type_mixed(self):
        """Mixed property types should be noted."""
        gj = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"val": 1}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"val": "text"}},
            ]
        }
        result = inspect_geojson(gj)
        assert result["attr_fields"]["val"] == "mixed"

    def test_crs_detection_wgs84(self):
        """WGS-84 coordinates should be detected as known CRS."""
        gj = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
                "properties": {}
            }]
        }
        result = inspect_geojson(gj)
        assert result["crs_known"] is True
        assert "WGS-84" in result["crs"]

    def test_crs_unknown_if_out_of_range(self):
        """Coordinates outside WGS-84 range should be marked unknown."""
        gj = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [200, 500]},
                "properties": {}
            }]
        }
        result = inspect_geojson(gj)
        assert result["crs_known"] is False

    def test_invalid_geometry_detection(self):
        """Self-intersecting polygon should be detected as invalid."""
        gj = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [0, 1], [1, 1], [0, 0]]]
                },
                "properties": {}
            }]
        }
        result = inspect_geojson(gj)
        # Self-intersecting bowtie is invalid
        assert result["invalid_geom_count"] >= 1

    def test_not_a_geojson(self):
        """Arbitrary JSON should not crash."""
        result = inspect_geojson({"type": "NotGeoJSON", "data": []})
        assert "error" in result
