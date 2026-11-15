import pytest

from backend.services import tools


@pytest.mark.parametrize(
    ("layers", "layer_name", "expected"),
    [
        ({}, "missing", "未找到图层"),
        ({"empty": {"geojson": {"features": []}}}, "empty", "图层没有要素"),
        ({"no-properties": {"geojson": {"features": [{"properties": {}}]}}},
         "no-properties", "图层没有属性字段"),
    ],
)
def test_chart_precondition_errors_are_classified_as_failures(monkeypatch, layers, layer_name, expected):
    monkeypatch.setattr(tools, "_registered_layers", layers)

    result = tools.create_chart.invoke({"layer_name": layer_name})

    assert expected in result
    assert tools._tool_result_failed("create_chart", result)
