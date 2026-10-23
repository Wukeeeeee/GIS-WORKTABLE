# -*- coding: utf-8 -*-
"""GIS URL 探测与数据抽取服务单元测试"""

import os
import io
import json
import zipfile
import tempfile
from unittest.mock import patch, MagicMock
import pytest
from backend.services import url_gis_service as ugs


@pytest.fixture
def mock_geojson_data():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.397, 39.908]},
                "properties": {"name": "天安门", "type": "A级景区", "city": "北京"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.405, 39.915]},
                "properties": {"name": "故宫", "type": "5A景区", "city": "北京"},
            },
        ],
    }


@pytest.fixture
def mock_arcgis_service_json():
    return {
        "currentVersion": 10.81,
        "mapName": "Beijing_POI",
        "description": "北京兴趣点与行政区划服务",
        "spatialReference": {"wkid": 4326, "latestWkid": 4326},
        "layers": [
            {"id": 0, "name": "景区点位", "parentLayerId": -1, "geometryType": "esriGeometryPoint"},
            {"id": 1, "name": "行政边界", "parentLayerId": -1, "geometryType": "esriGeometryPolygon"},
        ],
        "fullExtent": {"xmin": 115.4, "ymin": 39.4, "xmax": 117.5, "ymax": 41.0},
    }


@pytest.fixture
def mock_arcgis_layer_json():
    return {
        "id": 0,
        "name": "景区点位",
        "type": "Feature Layer",
        "geometryType": "esriGeometryPoint",
        "spatialReference": {"wkid": 4326, "latestWkid": 4326},
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "序号"},
            {"name": "NAME", "type": "esriFieldTypeString", "alias": "景点名称"},
            {"name": "LEVEL", "type": "esriFieldTypeString", "alias": "评级"},
        ],
        "extent": {"xmin": 116.0, "ymin": 39.5, "xmax": 116.8, "ymax": 40.2},
        "maxRecordCount": 2000,
    }


def _make_mock_response(json_data=None, text_data=None, content_bytes=None, headers=None, status_code=200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = headers or {"Content-Type": "application/json"}
    if json_data is not None:
        mock_resp.json = MagicMock(return_value=json_data)
        mock_resp.content = json.dumps(json_data).encode("utf-8")
        mock_resp.text = json.dumps(json_data)
    elif text_data is not None:
        mock_resp.text = text_data
        mock_resp.content = text_data.encode("utf-8")
    elif content_bytes is not None:
        mock_resp.content = content_bytes
        mock_resp.text = content_bytes.decode("utf-8", errors="ignore")
    return mock_resp


def test_inspect_gis_url_geojson(mock_geojson_data):
    url = "https://example.com/beijing_poi.geojson"
    mock_resp = _make_mock_response(json_data=mock_geojson_data)
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.inspect_gis_url(url)
        assert res["ok"] is True
        assert res["service_type"] == "GeoJSON"
        assert res["feature_count"] == 2
        assert "Point" in res["geometry_types"]
        assert "name" in res["fields"]
        assert res["bbox"] is not None


def test_inspect_gis_url_arcgis_service(mock_arcgis_service_json):
    url = "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Beijing/MapServer"
    mock_resp = _make_mock_response(json_data=mock_arcgis_service_json)
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.inspect_gis_url(url)
        assert res["ok"] is True
        assert res["service_type"] == "ArcGIS_REST_Service"
        assert res["layer_count"] == 2
        assert len(res["layers"]) == 2
        assert res["layers"][0]["name"] == "景区点位"


def test_inspect_gis_url_arcgis_layer(mock_arcgis_layer_json):
    url = "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Beijing/MapServer/0"
    mock_resp = _make_mock_response(json_data=mock_arcgis_layer_json)
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.inspect_gis_url(url)
        assert res["ok"] is True
        assert res["service_type"] == "ArcGIS_REST_Layer"
        assert res["layer_name"] == "景区点位"
        assert res["field_count"] == 3
        assert "NAME" in [f["name"] for f in res["fields"]]


def test_inspect_gis_url_wfs_xml():
    url = "https://example.com/geoserver/wfs"
    wfs_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <wfs:WFS_Capabilities version="2.0.0" xmlns:wfs="http://www.opengis.net/wfs/2.0">
        <wfs:FeatureTypeList>
            <wfs:FeatureType>
                <wfs:Name>workspace:roads</wfs:Name>
                <wfs:Title>Urban Roads</wfs:Title>
                <wfs:DefaultCRS>urn:ogc:def:crs:EPSG::4326</wfs:DefaultCRS>
            </wfs:FeatureType>
        </wfs:FeatureTypeList>
    </wfs:WFS_Capabilities>"""
    mock_resp = _make_mock_response(text_data=wfs_xml, headers={"Content-Type": "text/xml"})
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.inspect_gis_url(url)
        assert res["ok"] is True
        assert res["service_type"] == "OGC_WFS"
        assert res["layer_count"] == 1
        assert res["layers"][0]["name"] == "workspace:roads"


def test_fetch_gis_data_url_geojson(mock_geojson_data, tmp_path, monkeypatch):
    url = "https://example.com/data.geojson"
    monkeypatch.setattr("backend.services.url_gis_service._get_output_dir", lambda: str(tmp_path))

    mock_resp = _make_mock_response(json_data=mock_geojson_data)
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.fetch_gis_data_url(url, output_format="geojson")

        assert res["ok"] is True
        assert res["feature_count"] == 2
        assert os.path.exists(res["file_path"])
        assert "name" in res["fields"]

        # 检查生成的文件
        with open(res["file_path"], "r", encoding="utf-8") as f:
            saved_gj = json.load(f)
            assert len(saved_gj["features"]) == 2


def test_get_output_dir_reads_temp_dir_after_initialization(tmp_path, monkeypatch):
    from backend.services import tools
    monkeypatch.setattr(tools, "_temp_output_dir", "")
    monkeypatch.setattr(tools, "init_temp_dir", lambda: setattr(tools, "_temp_output_dir", str(tmp_path)))
    result = ugs._get_output_dir()
    assert result == str(tmp_path / "downloads")
    assert os.path.isdir(result)


def test_fetch_gis_data_url_csv(tmp_path, monkeypatch):
    url = "https://example.com/points.csv"
    csv_text = "id,name,lng,lat,val\n1,站点A,120.1,30.2,99\n2,站点B,120.2,30.3,88\n"
    monkeypatch.setattr("backend.services.url_gis_service._get_output_dir", lambda: str(tmp_path))

    mock_resp = _make_mock_response(text_data=csv_text, headers={"Content-Type": "text/csv"})
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.fetch_gis_data_url(url, output_format="geojson")
        assert res["ok"] is True
        assert res["feature_count"] == 2
        assert res["crs"] == "EPSG:4326"
        assert os.path.exists(res["file_path"])


def test_arcgis_full_fetch_uses_object_id_batches_and_writes_delivery_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/arcgis/rest/services/roads/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {
        "service_type": "ArcGIS_REST_Layer", "layer_id": 0, "layer_name": "roads", "crs": "EPSG:4326"
    })
    metadata = {
        "objectIdField": "OBJECTID", "maxRecordCount": 2,
        "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
        "spatialReference": {"wkid": 4326},
    }
    calls = []
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        calls.append(dict(params))
        if "f=pjson" in _url or params.get("f") == "pjson":
            return _make_mock_response(json_data=metadata)
        if params.get("returnCountOnly"):
            return _make_mock_response(json_data={"count": 3})
        if params.get("returnIdsOnly"):
            return _make_mock_response(json_data={"objectIdFieldName": "OBJECTID", "objectIds": [1, 2, 3]})
        ids = [int(value) for value in params["objectIds"].split(",")]
        return _make_mock_response(json_data={
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [i, i]},
                          "properties": {"OBJECTID": i, "name": f"road-{i}"}} for i in ids],
        })
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url + "?token=secret", mode="full", output_format="gpkg")
    assert result["completeness"] == "complete"
    assert result["expected_count"] == result["feature_count"] == 3
    assert result["expected_count_known"] is True
    assert result["source_url"] == layer_url
    assert len([c for c in calls if c.get("objectIds")]) == 2
    assert os.path.exists(result["file_path"])
    manifest = json.loads(open(result["recipe_path"], encoding="utf-8").read())
    assert manifest["source_url"] == layer_url
    assert "secret" not in open(result["report_path"], encoding="utf-8").read()
    assert len(result["sha256"]) == 64


def test_arcgis_full_fetch_reports_missing_object_ids_as_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    def response_for(_url, params=None, **_kwargs):
        if "f=pjson" in _url or (params or {}).get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 100})
        if (params or {}).get("returnCountOnly"):
            return _make_mock_response(json_data={"count": 2})
        if (params or {}).get("returnIdsOnly"):
            return _make_mock_response(json_data={"objectIds": [1, 2]})
        return _make_mock_response(json_data={"features": [{"type": "Feature", "geometry": None,
                                                               "properties": {"OID": 1}}]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")
    assert result["completeness"] == "partial"
    assert result["feature_count"] == 1
    assert any(check["name"] == "missing_ids" and check["status"] == "failed" for check in result["checks"])


def test_arcgis_full_fetch_reports_duplicate_object_ids_as_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})

    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 100})
        if params.get("returnCountOnly"):
            return _make_mock_response(json_data={"count": 2})
        if params.get("returnIdsOnly"):
            return _make_mock_response(json_data={"objectIds": [1, 2]})
        return _make_mock_response(json_data={"features": [
            {"type": "Feature", "geometry": None, "properties": {"OID": 1}},
            {"type": "Feature", "geometry": None, "properties": {"OID": 1}},
            {"type": "Feature", "geometry": None, "properties": {"OID": 2}},
        ]})

    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")

    assert result["completeness"] == "partial"
    assert result["feature_count"] == 3
    assert any(check["name"] == "duplicate_ids" and check["status"] == "failed" for check in result["checks"])


def test_arcgis_empty_full_query_creates_a_valid_empty_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "fields": [{"name": "OID"}],
                                                  "sourceSpatialReference": {"wkid": 4326, "latestWkid": 4326}})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 0})
        if params.get("returnIdsOnly"): return _make_mock_response(json_data={"objectIds": []})
        return _make_mock_response(json_data={"features": []})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="full")
    assert result["feature_count"] == result["expected_count"] == 0
    assert result["completeness"] == "complete"
    assert result["bbox"] is None
    assert json.loads(open(result["file_path"], encoding="utf-8").read())["features"] == []


def test_arcgis_batch_failure_keeps_partial_file_after_bounded_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    failed_batch_calls = []
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 1})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 2})
        if params.get("returnIdsOnly"): return _make_mock_response(json_data={"objectIds": [1, 2]})
        if params.get("objectIds"):
            failed_batch_calls.append(params["objectIds"])
            raise ugs.UrlGisError("temporary network timeout")
        return _make_mock_response(json_data={"objectIds": [1, 2]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="full")
    assert result["completeness"] == "partial"
    assert result["feature_count"] == 0
    assert "重试耗尽" in result["completeness_reason"]
    assert len(failed_batch_calls) == 2
    assert os.path.exists(result["file_path"])


def test_arcgis_layer_crs_uses_source_spatial_reference_fallback():
    info = ugs._parse_arcgis_json_metadata("https://example.test/FeatureServer/0", {
        "name": "states", "geometryType": "esriGeometryPolygon", "spatialReference": None,
        "sourceSpatialReference": {"wkid": 4326, "latestWkid": 4326}, "fields": []
    })
    assert info["crs"] == "EPSG:4326"


def test_arcgis_preview_is_never_reported_as_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    def response_for(_url, params=None, **_kwargs):
        if "f=pjson" in _url or (params or {}).get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 100})
        return _make_mock_response(json_data={"features": [{"type": "Feature", "geometry": None,
                                                               "properties": {"OID": 1}}]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="preview", limit=1)
    assert result["completeness"] == "not_checked"
    assert result["expected_count_known"] is False


def test_arcgis_full_fetch_uses_stable_offset_pagination_when_ids_are_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    metadata = {"objectIdField": "OID", "maxRecordCount": 2,
                "advancedQueryCapabilities": {"supportsPagination": True}}
    def feature(i):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [i, i]},
                "properties": {"OID": i}}
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data=metadata)
        if params.get("returnIdsOnly"): return _make_mock_response(json_data={"objectIds": [1, 2]})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 3})
        offset = int(params["resultOffset"])
        if params.get("f") == "json":
            rows = [feature(1), feature(2)] if offset == 0 else [feature(3)]
            return _make_mock_response(json_data={"features": [{"attributes": row["properties"]} for row in rows],
                                                  "exceededTransferLimit": offset == 0})
        rows = [feature(1), feature(2)] if offset == 0 else [feature(3)]
        return _make_mock_response(json_data={"features": rows, "exceededTransferLimit": offset == 0})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")
    assert result["completeness"] == "complete"
    assert result["expected_count"] == result["feature_count"] == 3
    assert any(check["name"] == "stable_pagination" and check["status"] == "passed" for check in result["checks"])


def test_arcgis_full_fetch_returns_unknown_when_no_safe_pagination_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    with patch("backend.services.url_gis_service._http_get", return_value=_make_mock_response(json_data={"fields": []})):
        with pytest.raises(ugs.UrlGisError, match="完整性未知"):
            ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="full")


def test_arcgis_full_fetch_refuses_to_trust_ids_without_independent_count(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 10})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"error": {"message": "unsupported"}})
        return _make_mock_response(json_data={"objectIds": [1]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        with pytest.raises(ugs.UrlGisError, match="完整性未知"):
            ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="full")


def test_arcgis_full_fetch_marks_changed_source_ids_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    calls = {"ids": 0}
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 10})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 2})
        if params.get("returnIdsOnly"):
            calls["ids"] += 1
            return _make_mock_response(json_data={"objectIds": [1, 2] if calls["ids"] == 1 else [1, 3]})
        return _make_mock_response(json_data={"features": [
            {"type": "Feature", "geometry": None, "properties": {"OID": i}} for i in (1, 2)
        ]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")
    assert result["completeness"] == "partial"
    assert "期间" in result["completeness_reason"]


def test_arcgis_full_fetch_preserves_multipart_polygon_holes(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    geometry = {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]],
        [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]],
    ]}
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 10})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 1})
        if params.get("returnIdsOnly"): return _make_mock_response(json_data={"objectIds": [1]})
        return _make_mock_response(json_data={"features": [{"type": "Feature", "geometry": geometry, "properties": {"OID": 1}}]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")
    exported = json.loads(open(result["file_path"], encoding="utf-8").read())
    output_geometry = exported["features"][0]["geometry"]
    assert output_geometry["type"] == "MultiPolygon"
    assert len(output_geometry["coordinates"]) == 2
    assert len(output_geometry["coordinates"][0]) == 2


def test_arcgis_esrijson_polygon_conversion_preserves_parts_and_holes():
    from shapely.geometry import shape
    rings = [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]],
        [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]],
    ]
    result = shape(ugs._arcgis_json_geometry({"rings": rings}))
    assert result.geom_type == "MultiPolygon"
    assert len(result.geoms) == 2
    assert len(result.geoms[0].interiors) == 1


def test_arcgis_fetch_falls_back_to_esrijson_without_losing_geometry(tmp_path, monkeypatch):
    from shapely.geometry import shape
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    rings = [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]],
        [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]],
    ]
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "sourceSpatialReference": {"wkid": 4326, "latestWkid": 4326}})
        if params.get("f") == "geojson":
            return _make_mock_response(json_data={"error": {"message": "GeoJSON format unsupported"}})
        return _make_mock_response(json_data={"features": [{"geometry": {"rings": rings}, "attributes": {"OID": 1, "name": "area"}}]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="preview")
    exported = json.loads(open(result["file_path"], encoding="utf-8").read())
    geometry = shape(exported["features"][0]["geometry"])
    assert geometry.geom_type == "MultiPolygon"
    assert len(geometry.geoms[0].interiors) == 1


def test_fetch_geojson_rejects_unknown_crs_instead_of_guessing(tmp_path, monkeypatch):
    import geopandas as gpd
    from shapely.geometry import Point
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "GeoJSON"})
    response = _make_mock_response(content_bytes=b"unknown CRS fixture")
    unknown = gpd.GeoDataFrame({"geometry": [Point(1, 2)]}, geometry="geometry")
    with patch("backend.services.url_gis_service._http_get", return_value=response), \
            patch("geopandas.read_file", return_value=unknown):
        with pytest.raises(ugs.UrlGisError, match="未提供可确认的坐标系"):
            ugs.fetch_gis_data_url("https://example.test/data.geojson")


@pytest.mark.parametrize("member", ["../escape.shp", r"..\escape.shp", "C:/escape.shp", "/escape.shp"])
def test_inspect_remote_shapefile_zip_rejects_unsafe_member_paths(tmp_path, monkeypatch, member):
    extract_dir = tmp_path / "inspect-extract"
    extract_dir.mkdir()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("safe.shp", b"safe")
        archive.writestr(member, b"unsafe")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_kwargs: str(extract_dir))
    response = _make_mock_response(content_bytes=archive_bytes.getvalue())

    with patch("backend.services.url_gis_service._http_get", return_value=response):
        with pytest.raises(ugs.UrlGisError, match="不安全的文件路径"):
            ugs._inspect_zip_shapefile("https://example.com/data.zip")

    assert not (extract_dir / "safe.shp").exists()
    assert not (tmp_path / "escape.shp").exists()


def test_safe_extract_remote_shapefile_zip_accepts_relative_members(tmp_path):
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("roads.shp", b"safe shapefile data")

    with zipfile.ZipFile(io.BytesIO(archive_bytes.getvalue())) as archive:
        ugs._safe_extract_zip(archive, str(tmp_path))

    assert (tmp_path / "roads.shp").read_bytes() == b"safe shapefile data"


def test_fetch_remote_shapefile_zip_rejects_unsafe_member_paths(tmp_path, monkeypatch):
    extract_dir = tmp_path / "fetch-extract"
    extract_dir.mkdir()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("safe.shp", b"safe")
        archive.writestr("../escape.shp", b"unsafe")
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "Shapefile_ZIP"})
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path / "downloads"))
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_kwargs: str(extract_dir))
    response = _make_mock_response(content_bytes=archive_bytes.getvalue())

    with patch("backend.services.url_gis_service._http_get", return_value=response):
        with pytest.raises(ugs.UrlGisError, match="不安全的文件路径"):
            ugs.fetch_gis_data_url("https://example.com/data.zip")

    assert not (extract_dir / "safe.shp").exists()
    assert not (tmp_path / "escape.shp").exists()
