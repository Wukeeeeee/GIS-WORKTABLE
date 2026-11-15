import pytest

from backend.services import tools


@pytest.mark.parametrize(
    "arguments",
    [
        {"geometry_type": "Triangle", "coordinates": "0,0"},
        {"geometry_type": "Point", "coordinates": "NaN,0"},
        {"geometry_type": "Rectangle", "coordinates": "1,1;1,2"},
        {"geometry_type": "Circle", "coordinates": "0,0;0"},
    ],
)
def test_draw_feature_input_errors_are_classified_as_failures(arguments):
    tools.reset_state()
    result = tools.draw_feature.invoke(arguments)

    assert tools._tool_result_failed("draw_feature", result), result
    assert tools._pending_layers == []


def test_draw_feature_success_is_not_classified_as_failure():
    tools.reset_state()

    result = tools.draw_feature.invoke({
        "geometry_type": "Point", "coordinates": "0,0", "layer_name": "probe-point",
    })

    assert result.startswith("已创建Point图层")
    assert not tools._tool_result_failed("draw_feature", result)
