"""Heatmap validation failures must be represented as tool failures."""

import pytest

from backend.services import history_service, tools


@pytest.mark.parametrize("layer_name,layers,arguments,expected", [
    ("missing", {}, {"radius": 20}, "未找到"),
    ("shapes", {"shapes": {"geojson": {"features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    }]}}}, {"radius": 20}, "没有点要素"),
    ("points", {"points": {"geojson": {"features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Point", "coordinates": [116, 39]},
    }]}}}, {"radius": 0}, "半径范围"),
])
def test_heatmap_validation_errors_are_recorded_as_failures(monkeypatch, layer_name, layers, arguments, expected):
    history = []
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    monkeypatch.setattr(tools, "_registered_layers", layers)

    result = next(tool for tool in tools.tools if tool.name == "create_heatmap").invoke({
        "layer_name": layer_name, **arguments,
    })

    assert expected in result
    assert tools._tool_result_failed("create_heatmap", result)
    assert history[-1][2] is False
