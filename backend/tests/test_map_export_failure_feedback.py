"""Invalid map export formats must be recorded as failed tool calls."""

from backend.services import history_service, tools


def test_unsupported_map_export_format_is_reported_as_failure(monkeypatch):
    history = []
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))

    result = next(tool for tool in tools.tools if tool.name == "export_map").invoke({
        "format": "webp",
    })

    assert "不支持的图片格式" in result
    assert tools._tool_result_failed("export_map", result)
    assert history[-1][2] is False
