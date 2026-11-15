"""Layer detail lookups with no unique result must be classified as failures."""

import pytest

from backend.services import history_service, tools


@pytest.mark.parametrize("layer_name,layers", [
    ("missing", {}),
    ("poi", {"poi_north": {}, "poi_south": {}}),
])
def test_missing_or_ambiguous_layer_detail_is_reported_as_failure(monkeypatch, layer_name, layers):
    history = []
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    monkeypatch.setattr(tools, "_registered_layers", layers)

    result = next(tool for tool in tools.tools if tool.name == "get_layer_detail").invoke({
        "layer_name": layer_name,
    })

    assert "未找到图层" in result or "找到多个匹配" in result
    assert tools._tool_result_failed("get_layer_detail", result)
    assert history[-1][2] is False
