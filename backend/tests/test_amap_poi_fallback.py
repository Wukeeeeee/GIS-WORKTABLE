import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services import tools as T
from backend.services import amap_service
from backend.services.data_providers import osm_provider


@pytest.mark.parametrize(
    ("api_key", "amap_result"),
    [
        ("", None),
        ("invalid-key", {"error": "高德 API 返回错误: INVALID_USER_KEY"}),
    ],
)
def test_poi_search_falls_back_to_osm_when_amap_is_unavailable(
    monkeypatch, api_key, amap_result
):
    calls = {}

    class FakeOSMProvider:
        def _build_query(self, selectors, bbox, *, max_items=0):
            calls["selectors"] = selectors
            calls["bbox"] = bbox
            calls["max_items"] = max_items
            return "fake-overpass-query"

        def _overpass(self, query):
            assert query == "fake-overpass-query"
            return {
                "elements": [{
                    "type": "node",
                    "id": 42,
                    "lat": 28.19,
                    "lon": 112.98,
                    "tags": {"amenity": "hospital", "name": "Test Hospital"},
                }]
            }

    monkeypatch.setattr(osm_provider, "OpenStreetMapProvider", FakeOSMProvider)
    monkeypatch.setattr(T, "_current_amap_key", api_key)
    monkeypatch.setattr(T, "_pending_layers", [])
    monkeypatch.setattr(T, "_registered_layers", {})
    if amap_result is not None:
        monkeypatch.setattr(amap_service, "search_poi", lambda **_: amap_result)

    result = T.amap_poi_search.invoke({
        "keywords": "医院",
        "city": "长沙",
        "location": "112.98,28.19",
        "radius": 5000,
    })

    assert "自动回退到 OpenStreetMap" in result
    assert "已加载 1 个要素" in result
    assert any('"amenity"~"^(hospital|clinic|doctors)$"' in s for s in calls["selectors"])
    assert calls["bbox"][0] < 112.98 < calls["bbox"][2]
    assert calls["bbox"][1] < 28.19 < calls["bbox"][3]
    assert T._pending_layers[0]["name"] == "医院_POI(OSM)"
    feature = T._pending_layers[0]["geojson"]["features"][0]
    assert feature["properties"]["source"] == "OpenStreetMap"
