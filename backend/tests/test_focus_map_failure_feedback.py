import pytest

from backend.services import tools
from backend.services.tool_modules import runtime


def _isolate_pending_layer_ops(monkeypatch):
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_pending_layer_ops", [])


@pytest.fixture(autouse=True)
def isolate_pending_layer_ops_fixture(monkeypatch):
    _isolate_pending_layer_ops(monkeypatch)
    yield
    with runtime._state_lock:
        runtime._pending_layer_ops.clear()


def test_pending_layer_ops_isolation_restores_existing_state():
    ops = runtime._pending_layer_ops
    ops.append({"action": "sentinel"})
    patcher = pytest.MonkeyPatch()
    try:
        _isolate_pending_layer_ops(patcher)
        assert tools._pending_layer_ops is runtime._pending_layer_ops
        assert runtime._pending_layer_ops is not ops
    finally:
        patcher.undo()
    assert runtime._pending_layer_ops is ops
    assert ops == [{"action": "sentinel"}]


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
    with runtime._state_lock:
        monkeypatch.setattr(tools, "_registered_layers", {})

    result = tools.focus_map.invoke(arguments)

    assert expected in result
    assert tools._tool_result_failed("focus_map", result)
    assert tools._pending_layer_ops == []


def test_focus_map_valid_center_is_not_classified_as_failure(monkeypatch):
    result = tools.focus_map.invoke({"center": "12.5,45.0", "zoom": 11})

    assert result.startswith("已定位到")
    assert not tools._tool_result_failed("focus_map", result)
    assert tools._pending_layer_ops == [{
        "action": "center", "center": [12.5, 45.0], "zoom": 11,
    }]
