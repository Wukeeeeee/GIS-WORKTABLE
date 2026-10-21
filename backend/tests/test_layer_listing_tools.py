"""Regression tests for the two public tools that list registered layers."""

from backend.services import tools as gis_tools


def test_layer_listing_structured_tools_share_plain_summary_helper(monkeypatch):
    monkeypatch.setattr(gis_tools, "_registered_layers", {
        "测试图层": {
            "geometry_types": ["Polygon"],
            "bbox": [100.0, 20.0, 101.0, 21.0],
            "feature_count": 1,
            "geojson": {"features": [{"properties": {"population": 42, "_fid": "p:1"}}]},
        },
    })
    monkeypatch.setattr(gis_tools, "get_current_run_id", lambda: "")
    monkeypatch.setattr(gis_tools, "get_current_task_id", lambda: None)
    monkeypatch.setattr(gis_tools, "peek_pending_images", lambda: [])
    monkeypatch.setattr(gis_tools._history_svc, "record", lambda *args, **kwargs: None)
    tools_by_name = {tool.name: tool for tool in gis_tools.tools}

    for name in ("list_layers", "get_registered_layers"):
        result = tools_by_name[name].invoke({})
        assert "当前地图共注册了 1 个图层" in result
        assert "测试图层" in result
        assert "population" in result
        assert "StructuredTool" not in result
        assert "工具执行失败" not in result


def test_registered_layer_search_finds_keywords_beyond_preview(monkeypatch):
    features = [
        {"properties": {"name": f"商铺{i}", "category": "餐饮"}, "geometry": None}
        for i in range(40)
    ]
    features[-1]["properties"]["name"] = "麦当劳西区店"
    monkeypatch.setattr(gis_tools, "_registered_layers", {
        "混合POI": {
            "geometry_types": ["Point"],
            "bbox": [100.0, 20.0, 101.0, 21.0],
            "feature_count": len(features),
            "geojson": {"features": features},
        },
    })
    monkeypatch.setattr(gis_tools, "get_current_run_id", lambda: "")
    monkeypatch.setattr(gis_tools, "get_current_task_id", lambda: None)
    monkeypatch.setattr(gis_tools, "peek_pending_images", lambda: [])
    monkeypatch.setattr(gis_tools._history_svc, "record", lambda *args, **kwargs: None)
    tool = next(tool for tool in gis_tools.tools if tool.name == "get_registered_layers")

    result = tool.invoke({"keyword": "麦当劳"})

    assert "关键词「麦当劳」" in result
    assert "混合POI」命中 1 个要素" in result
    assert "麦当劳西区店" in result
