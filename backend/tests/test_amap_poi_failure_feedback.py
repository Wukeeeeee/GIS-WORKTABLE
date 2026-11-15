from backend.services import tools


def test_invalid_radius_is_classified_as_tool_failure():
    result = tools.amap_poi_search.invoke({"keywords": "医院", "radius": 0})

    assert result.startswith("搜索半径必须是")
    assert tools._tool_result_failed("amap_poi_search", result)


def test_osm_fallback_exception_is_classified_as_tool_failure(monkeypatch):
    monkeypatch.setattr(tools, "_current_amap_key", "")

    def fail_fallback(*_args):
        raise RuntimeError("service unavailable")

    monkeypatch.setattr(tools, "_search_osm_poi_fallback", fail_fallback)
    result = tools.amap_poi_search.invoke({"keywords": "医院", "city": "长沙"})

    assert "OSM 回退也失败：service unavailable" in result
    assert tools._tool_result_failed("amap_poi_search", result)


def test_successful_osm_fallback_is_not_classified_as_failure():
    result = "高德不可用（无 Key）；已自动回退到 OpenStreetMap，找到 1 个 POI"

    assert not tools._tool_result_failed("amap_poi_search", result)
