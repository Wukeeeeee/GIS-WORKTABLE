from backend.services import tools


def _setup_layer(features=None):
    tools.reset_state()
    tools._register_layer(
        "roads",
        {
            "type": "FeatureCollection",
            "features": features if features is not None else [{
                "type": "Feature",
                "properties": {"name": "main"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }],
        },
    )


def test_unsupported_field_type_is_failure_without_mutation():
    _setup_layer()
    before = tools._registered_layers["roads"]["geojson"]

    result = tools.add_field.invoke({
        "layer_name": "roads", "field_name": "score", "field_type": "date",
    })

    assert result.startswith("不支持字段类型")
    assert tools._tool_result_failed("add_field", result)
    assert tools._registered_layers["roads"]["geojson"] == before
    assert tools._pending_layers == []


def test_duplicate_field_name_is_failure_without_mutation():
    _setup_layer()
    before = tools._registered_layers["roads"]["geojson"]

    result = tools.add_field.invoke({
        "layer_name": "roads", "field_name": "name", "field_type": "str",
    })

    assert result == "字段「name」已存在"
    assert tools._tool_result_failed("add_field", result)
    assert tools._registered_layers["roads"]["geojson"] == before
    assert tools._pending_layers == []


def test_blank_field_name_is_failure_without_mutation():
    _setup_layer()
    before = tools._registered_layers["roads"]["geojson"]

    result = tools.add_field.invoke({
        "layer_name": "roads", "field_name": "   ", "field_type": "str",
    })

    assert result == "字段名不能为空"
    assert tools._tool_result_failed("add_field", result)
    assert tools._registered_layers["roads"]["geojson"] == before
    assert tools._pending_layers == []


def test_empty_layer_add_field_rejection_is_failure_without_mutation():
    _setup_layer(features=[])
    before = tools._registered_layers["roads"]["geojson"]

    result = tools.add_field.invoke({
        "layer_name": "roads", "field_name": "score", "field_type": "int",
    })

    assert result == "图层「roads」为空"
    assert tools._tool_result_failed("add_field", result)
    assert tools._registered_layers["roads"]["geojson"] == before
    assert tools._pending_layers == []


def test_valid_field_addition_is_not_classified_as_failure():
    _setup_layer()

    result = tools.add_field.invoke({
        "layer_name": "roads", "field_name": "score", "field_type": "int",
    })

    assert "添加字段「score」" in result
    assert not tools._tool_result_failed("add_field", result)
