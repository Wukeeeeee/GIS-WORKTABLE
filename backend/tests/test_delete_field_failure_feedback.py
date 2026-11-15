from backend.services import tools


def test_delete_missing_field_is_classified_as_failure_without_mutation(monkeypatch):
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
    before = tools._registered_layers["roads"]["geojson"]

    result = tools.delete_field.invoke({"layer_name": "roads", "field_name": "missing"})

    assert result.startswith("错误：字段「missing」不存在")
    assert tools._tool_result_failed("delete_field", result)
    assert tools._registered_layers["roads"]["geojson"] == before
    assert tools._pending_layer_ops == []
