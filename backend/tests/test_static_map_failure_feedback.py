"""Static map validation and empty-input failures must not look successful."""

import pytest

from backend.services import history_service, tools


@pytest.mark.parametrize("layer_ids,layers,dpi,expected", [
    ("", {}, 150, "没有可绘制的图层"),
    ("missing", {}, 150, "指定图层不存在"),
    ("empty", {"empty": {"geojson": {"type": "FeatureCollection", "features": []}}}, 150,
     "没有可绘制的要素"),
    ("", {}, 0, "DPI 范围"),
])
def test_static_map_precondition_failures_are_recorded(monkeypatch, layer_ids, layers, dpi, expected):
    history = []
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    monkeypatch.setattr(tools, "_registered_layers", layers)

    result = next(tool for tool in tools.tools if tool.name == "generate_static_map").invoke({
        "layer_ids": layer_ids, "dpi": dpi,
    })

    assert expected in result
    assert tools._tool_result_failed("generate_static_map", result)
    assert history[-1][2] is False
