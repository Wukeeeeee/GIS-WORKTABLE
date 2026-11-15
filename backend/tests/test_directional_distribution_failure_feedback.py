"""Invalid deviation multipliers must be reported as failed tool executions."""

from backend.services import history_service, tools
from backend.services.tool_modules import vector


def test_invalid_std_deviation_is_reported_as_tool_failure(monkeypatch):
    history = []
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    monkeypatch.setattr(vector, "_layer_to_gdf", lambda _name: (object(), "points"))
    monkeypatch.setattr(vector, "_stats_metric_gdf", lambda frame: (frame, "EPSG:32650"))
    monkeypatch.setattr(vector, "_stats_coords_weights", lambda *_args: ([], []))

    result = next(tool for tool in tools.tools if tool.name == "directional_distribution").invoke({
        "layer_name": "points", "std_deviations": "not-a-number",
    })

    assert "解析失败" in result
    assert tools._tool_result_failed("directional_distribution", result)
    assert history[-1][2] is False
