"""Failure feedback must classify an OD request without an available road network."""

from backend.services import tools
from backend.services import history_service
from backend.services.tool_modules import network


def test_missing_road_network_is_reported_as_tool_failure(monkeypatch):
    history = []
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    for name, coordinates in (("origins", [116, 39]), ("destinations", [117, 40])):
        tools._register_layer(name, {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": coordinates},
        }]})
    tools.get_pending_state()
    monkeypatch.setattr(network, "_find_layer_for_coord", lambda *_args: None)

    result = next(tool for tool in tools.tools if tool.name == "od_cost_matrix").invoke({
        "origins_layer": "origins", "destinations_layer": "destinations",
    })

    assert "未找到可用的路网图层" in result
    assert tools._tool_result_failed("od_cost_matrix", result)
    assert history[-1][2] is False


def test_internal_od_error_is_reported_as_tool_failure(monkeypatch):
    history = []
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    monkeypatch.setattr(network, "_layer_to_gdf", lambda _name: (_ for _ in ()).throw(ValueError("test failure")))

    result = next(tool for tool in tools.tools if tool.name == "od_cost_matrix").invoke({
        "origins_layer": "origins", "destinations_layer": "destinations",
    })

    assert "计算失败" in result
    assert tools._tool_result_failed("od_cost_matrix", result)
    assert history[-1][2] is False
