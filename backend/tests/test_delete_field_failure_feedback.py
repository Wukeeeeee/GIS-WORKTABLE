import copy

import pytest

from backend.services import tools
from backend.services.tool_modules import runtime

pytestmark = pytest.mark.usefixtures("isolated_tool_runtime")


def _isolate_delete_field_runtime_state(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})
        monkeypatch.setattr(tools, "_pending_layers", [])
        monkeypatch.setattr(tools, "_pending_layer_ops", [])
        monkeypatch.setattr(tools, "_pending_qa_warnings", [])


def test_delete_field_runtime_isolation_restores_existing_state():
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
        _isolate_delete_field_runtime_state(patcher)
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


@pytest.mark.parametrize(
    ("field_name", "expected_fragments"),
    [
        ("missing", ("missing", "不存在")),
        ("geometry", ("不能删除 geometry 字段",)),
        ("_fid", ("_fid 是要素稳定标识，不能删除",)),
    ],
)
def test_delete_field_rejections_are_failures_without_mutation(field_name, expected_fragments):
    _setup_layer()
    before = copy.deepcopy(tools._registered_layers["roads"]["geojson"])

    result = tools.delete_field.invoke({"layer_name": "roads", "field_name": field_name})

    assert all(fragment in result for fragment in expected_fragments)
    assert tools._tool_result_failed("delete_field", result)
    assert tools._registered_layers["roads"]["geojson"] == before
    assert tools._pending_layers == []


def test_empty_layer_delete_field_rejection_is_failure_without_mutation():
    _setup_layer(features=[])
    before = copy.deepcopy(tools._registered_layers["roads"]["geojson"])

    result = tools.delete_field.invoke({"layer_name": "roads", "field_name": "name"})

    assert result.startswith("图层「roads」为空")
    assert tools._tool_result_failed("delete_field", result)
    assert tools._registered_layers["roads"]["geojson"] == before
    assert tools._pending_layers == []


def test_successful_field_deletion_is_not_classified_as_failure():
    _setup_layer()

    result = tools.delete_field.invoke({"layer_name": "roads", "field_name": "name"})

    assert "删除字段「name」" in result
    assert not tools._tool_result_failed("delete_field", result)
    assert [layer["name"] for layer in runtime._pending_layers] == ["roads"]
