"""Unsupported vector export formats must not be reported as successful calls."""

from backend.services import history_service, tools


def test_unsupported_export_format_is_reported_as_failure(monkeypatch, tmp_path):
    history = []
    geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": "a"},
        "geometry": {"type": "Point", "coordinates": [116, 39]},
    }]}
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    monkeypatch.setattr(tools, "_registered_layers", {"points": {"geojson": geojson}})
    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))

    result = next(tool for tool in tools.tools if tool.name == "export_layer").invoke({
        "layer_name": "points", "format": "not-a-format",
    })

    assert "不支持的格式" in result
    assert tools._tool_result_failed("export_layer", result)
    assert history[-1][2] is False
    assert list(tmp_path.iterdir()) == []
