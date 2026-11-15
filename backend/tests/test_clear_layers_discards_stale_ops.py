"""Regression coverage for clearing queued map operations with the layer registry."""

from backend.services import tools
from backend.services.tool_modules import runtime


def test_clear_layers_discards_pending_operations_for_removed_layers(monkeypatch):
    monkeypatch.setattr(runtime, "_registered_layers", {"removed-layer": {}})
    monkeypatch.setattr(runtime, "_pending_layers", [{"name": "removed-layer"}])
    monkeypatch.setattr(runtime, "_pending_layer_ops", [{"action": "fit", "name": "removed-layer"}])
    monkeypatch.setattr(runtime, "_pending_images", [])
    monkeypatch.setattr(runtime, "_pending_qa_warnings", [])
    monkeypatch.setattr(runtime, "_pending_aoi_suggestions", {})
    monkeypatch.setattr(runtime, "_pending_heatmap", {"latest": None})
    monkeypatch.setattr(runtime, "_clear_layers_flag", False)

    tools.clear_layers.invoke({})

    pending = runtime.get_pending_state()
    assert pending["clear_layers"] is True
    assert pending["layers"] == []
    assert pending["layer_ops"] == []
