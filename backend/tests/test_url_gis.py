# -*- coding: utf-8 -*-
"""GIS URL 探测与数据抽取服务单元测试"""

import os
import json
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
