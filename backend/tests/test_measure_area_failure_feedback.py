from backend.services import tools


def test_missing_layer_is_classified_as_measurement_failure(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})

    result = tools.measure_area.invoke({"layer_name": "missing"})

    assert result.startswith("未找到图层")
    assert tools._tool_result_failed("measure_area", result)


def test_ambiguous_layer_name_is_classified_as_measurement_failure(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {
        "roads_main": {}, "roads_local": {},
    })

    result = tools.measure_area.invoke({"layer_name": "roads"})

    assert result.startswith("找到多个匹配：")
    assert tools._tool_result_failed("measure_area", result)
