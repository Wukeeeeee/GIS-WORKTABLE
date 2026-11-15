"""Compatibility checks for the tools facade and modular shared runtime."""

from backend.services import tools
from backend.services.tool_modules import runtime


def test_facade_reexports_authoritative_mutable_state(monkeypatch):
    replacement_layers = {"facade-layer": {"name": "facade-layer"}}
    replacement_pending = [{"op": "test"}]

    monkeypatch.setattr(tools, "_registered_layers", replacement_layers)
    monkeypatch.setattr(tools, "_pending_layer_ops", replacement_pending)

    assert runtime._registered_layers is replacement_layers
    assert runtime._pending_layer_ops is replacement_pending
    assert tools._registered_layers is runtime._registered_layers
    assert tools._pending_layer_ops is runtime._pending_layer_ops


def test_facade_forwards_runtime_output_directory(monkeypatch, tmp_path):
    output_dir = str(tmp_path / "facade-output")
    monkeypatch.setattr(tools, "_temp_output_dir", output_dir)

    assert runtime._temp_output_dir == output_dir
    assert tools._temp_output_dir == output_dir


def test_domain_modules_use_runtime_layer_registry():
    from backend.services.tool_modules import network, raster, terrain, vector

    assert network._registered_layers is runtime._registered_layers
    assert raster._registered_layers is runtime._registered_layers
    assert terrain._registered_layers is runtime._registered_layers
    assert vector._registered_layers is runtime._registered_layers
