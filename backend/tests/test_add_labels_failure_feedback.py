from backend.services import tools


def test_missing_label_field_is_classified_as_tool_failure(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    tools._register_layer(
        "roads",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "main"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }],
        },
    )

    result = tools.add_labels.invoke({"layer_name": "roads", "field": "missing"})

    assert "没有字段「missing」" in result
    assert tools._tool_result_failed("add_labels", result)


def test_valid_label_field_is_not_classified_as_failure(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    tools._register_layer(
        "roads",
        {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "main"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }],
        },
    )

    result = tools.add_labels.invoke({"layer_name": "roads", "field": "name"})

    assert "已为" in result
    assert not tools._tool_result_failed("add_labels", result)
