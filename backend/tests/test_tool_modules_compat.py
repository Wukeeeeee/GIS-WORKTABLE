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


def test_spatial_kde_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.spatial_kde is vector.spatial_kde
    tool_names = [tool.name for tool in tools.tools]
    assert tool_names.count("spatial_kde") == 1
    assert tool_names.index("spatial_hotspot") < tool_names.index("spatial_kde")
    assert tool_names.index("spatial_kde") < tool_names.index("calc_spectral_index")


def test_spatial_moran_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.spatial_moran is vector.spatial_moran
    tool_names = [tool.name for tool in tools.tools]
    moran_index = tool_names.index("spatial_moran")
    assert tool_names.count("spatial_moran") == 1
    assert tool_names[moran_index:moran_index + 3] == [
        "spatial_moran", "spatial_hotspot", "spatial_kde",
    ]


def test_spatial_hotspot_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.spatial_hotspot is vector.spatial_hotspot
    tool_names = [tool.name for tool in tools.tools]
    assert tool_names.count("spatial_hotspot") == 1
    assert tool_names[tool_names.index("spatial_moran") + 1] == "spatial_hotspot"


def test_measure_distance_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.measure_distance is vector.measure_distance
    tool_names = [tool.name for tool in tools.tools]
    measure_area_index = tool_names.index("measure_area")
    assert tool_names[measure_area_index:measure_area_index + 2] == [
        "measure_area", "measure_distance",
    ]


def test_facade_spatial_stats_limit_rebinds_to_vector(monkeypatch):
    from backend.services.tool_modules import vector

    monkeypatch.setattr(tools, "_MAX_DENSE_SPATIAL_STATS_FEATURES", 3)

    assert vector._MAX_DENSE_SPATIAL_STATS_FEATURES == 3
