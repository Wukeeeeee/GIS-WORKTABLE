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
