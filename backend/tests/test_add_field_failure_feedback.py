import pytest

from backend.services import tools
from backend.services.tool_modules import runtime


def _isolate_add_field_runtime_state(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})
        monkeypatch.setattr(tools, "_pending_layers", [])
        monkeypatch.setattr(tools, "_pending_layer_ops", [])
        monkeypatch.setattr(tools, "_pending_qa_warnings", [])


@pytest.fixture(autouse=True)
def isolate_add_field_runtime_state_fixture(monkeypatch):
    _isolate_add_field_runtime_state(monkeypatch)
    yield
    with runtime._state_lock:
        runtime._registered_layers.clear()
        runtime._pending_layers.clear()
        runtime._pending_layer_ops.clear()
        runtime._pending_qa_warnings.clear()


def test_add_field_runtime_isolation_restores_existing_state():
    registry, pending, ops, warnings = (
        runtime._registered_layers,
        runtime._pending_layers,
        runtime._pending_layer_ops,
        runtime._pending_qa_warnings,
    )
    registry["sentinel-layer"] = {"geojson": {"type": "FeatureCollection", "features": []}}
    pending.append({"name": "sentinel-pending"})
    ops.append({"action": "sentinel"})
    warnings.append({"layer": "sentinel-layer", "warning": "preserve"})
    patcher = pytest.MonkeyPatch()
    try:
        _isolate_add_field_runtime_state(patcher)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layers is not pending
        assert runtime._pending_layer_ops is not ops
        assert runtime._pending_qa_warnings is not warnings
        assert tools._registered_layers is runtime._registered_layers
    finally:
        patcher.undo()
    assert runtime._registered_layers is registry and "sentinel-layer" in registry
    assert runtime._pending_layers is pending and pending[0]["name"] == "sentinel-pending"
    assert runtime._pending_layer_ops is ops and ops[0]["action"] == "sentinel"
    assert runtime._pending_qa_warnings is warnings and warnings[0]["warning"] == "preserve"


def _setup_layer(features=None):
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
    assert [layer["name"] for layer in runtime._pending_layers] == ["roads"]
