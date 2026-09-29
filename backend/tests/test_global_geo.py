# -*- coding: utf-8 -*-
"""全球开放地理数据、Wikidata 与 OSM 单元测试"""

import os
import json
from unittest.mock import patch, MagicMock
import pytest
from backend.services import global_geo_service as ggs


@pytest.fixture
def mock_wikidata_search_response():
    return {
        "search": [
            {
                "id": "Q1867",
                "label": "台北市",
                "description": "台湾的直辖市及主要都市",
                "concepturi": "http://www.wikidata.org/entity/Q1867",
            }
        ]
    }


@pytest.fixture
def mock_wikidata_entity_detail():
    return {
        "entities": {
            "Q1867": {
                "claims": {
                    "P625": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": {
                                        "latitude": 25.033,
                                        "longitude": 121.565,
                                    }
                                }
                            }
                        }
                    ]
                },
                "sitelinks": {
                    "zhwiki": {"title": "台北市"}
                },
            }
        }
    }


@pytest.fixture
def mock_nominatim_response():
    return [
        {
            "lat": "25.033",
            "lon": "121.565",
            "display_name": "台北市, 台湾",
            "boundingbox": ["24.96", "25.21", "121.45", "121.66"],
            "geojson": {
                "type": "Polygon",
                "coordinates": [[[121.45, 24.96], [121.66, 24.96], [121.66, 25.21], [121.45, 25.21], [121.45, 24.96]]],
            },
        }
    ]


def _make_mock_response(json_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json = MagicMock(return_value=json_data)
    mock.text = json.dumps(json_data)
    return mock


def test_search_wikidata_entities(mock_wikidata_search_response, mock_wikidata_entity_detail):
    def fake_http_get(url, params=None, timeout=10):
        if "Special:EntityData" in url:
            return _make_mock_response(mock_wikidata_entity_detail)
        elif "page/summary" in url:
            return _make_mock_response({"extract": "台北市是台湾的直辖市。"})
        return _make_mock_response(mock_wikidata_search_response)

    with patch("backend.services.global_geo_service._http_get", side_effect=fake_http_get):
        res = ggs.search_wikidata_entities("台北", lang="zh")
        assert len(res) == 1
        assert res[0]["qid"] == "Q1867"
        assert res[0]["name"] == "台北市"
        assert res[0]["coordinates"] == [121.565, 25.033]


def test_search_osm_nominatim(mock_nominatim_response):
    mock_resp = _make_mock_response(mock_nominatim_response)
    with patch("backend.services.global_geo_service._http_get", return_value=mock_resp):
        res = ggs.search_osm_nominatim("Taipei", fetch_polygon=True)
        assert len(res) == 1
        assert res[0]["coordinates"] == [121.565, 25.033]
        assert res[0]["has_polygon"] is True
        assert res[0]["geojson"]["type"] == "Polygon"


def test_query_osm_overpass():
    mock_elements = {
        "elements": [
            {"type": "node", "id": 101, "lat": 25.03, "lon": 121.56, "tags": {"name": "台北101", "amenity": "attraction"}},
            {"type": "node", "id": 102, "lat": 25.04, "lon": 121.57, "tags": {"name": "信义商圈", "amenity": "mall"}},
        ]
    }
    mock_resp = _make_mock_response(mock_elements)
    with patch("backend.services.global_geo_service._http_get", return_value=mock_resp):
        res = ggs.query_osm_overpass(query_type="amenity", bbox="121.4,24.9,121.6,25.1", limit=10)
        assert res["ok"] is True
        assert res["feature_count"] == 2
        assert res["geojson"]["type"] == "FeatureCollection"
