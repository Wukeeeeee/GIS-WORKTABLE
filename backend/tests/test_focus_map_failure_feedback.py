import pytest

from backend.services import tools


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"layer_name": "missing"}, "未找到图层"),
        ({"center": "1,2,3"}, "center 格式应为"),
        ({"center": "west,2"}, "无法解析坐标"),
        ({"center": "181,0"}, "坐标范围无效"),
        ({"center": "0,91"}, "坐标范围无效"),
        ({"center": "NaN,10"}, "坐标范围无效"),
        ({"center": "inf,0"}, "坐标范围无效"),
        ({}, "请提供 layer_name"),
    ],
)
def test_focus_map_invalid_requests_are_classified_as_failures(monkeypatch, arguments, expected):
    monkeypatch.setattr(tools, "_registered_layers", {})
    tools._pending_layer_ops.clear()

    result = tools.focus_map.invoke(arguments)

    assert expected in result
    assert tools._tool_result_failed("focus_map", result)
    assert tools._pending_layer_ops == []


def test_focus_map_valid_center_is_not_classified_as_failure(monkeypatch):
    tools._pending_layer_ops.clear()
    result = tools.focus_map.invoke({"center": "12.5,45.0", "zoom": 11})

    assert result.startswith("已定位到")
    assert not tools._tool_result_failed("focus_map", result)
