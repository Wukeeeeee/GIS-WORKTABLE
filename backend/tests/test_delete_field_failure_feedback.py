import copy

import pytest

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
