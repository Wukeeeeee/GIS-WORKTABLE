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
    assert vector._registered_layers is runtime._registered_layers
    assert terrain._pending_layer_ops is runtime._pending_layer_ops
    assert vector._pending_layer_ops is runtime._pending_layer_ops


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


def test_measure_area_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.measure_area is vector.measure_area
    tool_names = [tool.name for tool in tools.tools]
    measure_area_index = tool_names.index("measure_area")
    assert tool_names[measure_area_index:measure_area_index + 2] == [
        "measure_area", "measure_distance",
    ]


def test_convert_coordinates_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.convert_coordinates is vector.convert_coordinates
    tool_names = [tool.name for tool in tools.tools]
    convert_index = tool_names.index("convert_coordinates")
    assert tool_names[convert_index - 1:convert_index + 2] == [
        "convert_crs", "convert_coordinates", "extract_contours",
    ]


def test_convert_crs_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.convert_crs is vector.convert_crs
    tool_names = [tool.name for tool in tools.tools]
    convert_index = tool_names.index("convert_crs")
    assert tool_names[convert_index:convert_index + 3] == [
        "convert_crs", "convert_coordinates", "extract_contours",
    ]


def test_add_length_field_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.add_length_field is vector.add_length_field
    tool_names = [tool.name for tool in tools.tools]
    field_index = tool_names.index("add_length_field")
    assert tool_names[field_index - 1:field_index + 3] == [
        "zonal_statistics", "add_length_field", "spatial_explode", "geometry_convert",
    ]


def test_edit_vertices_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.edit_vertices is vector.edit_vertices
    tool_names = [tool.name for tool in tools.tools]
    edit_index = tool_names.index("edit_vertices")
    assert tool_names[edit_index - 2:edit_index + 2] == [
        "scale_features", "draw_feature", "edit_vertices", "export_map",
    ]


def test_draw_feature_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.draw_feature is vector.draw_feature
    tool_names = [tool.name for tool in tools.tools]
    draw_index = tool_names.index("draw_feature")
    assert tool_names[draw_index - 1:draw_index + 2] == [
        "scale_features", "draw_feature", "edit_vertices",
    ]


def test_add_legend_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.add_legend is vector.add_legend
    tool_names = [tool.name for tool in tools.tools]
    legend_index = tool_names.index("add_legend")
    assert tool_names[legend_index - 1:legend_index + 2] == [
        "spatial_select_by_attribute", "add_legend", "update_attribute",
    ]


def test_add_labels_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.add_labels is vector.add_labels
    tool_names = [tool.name for tool in tools.tools]
    labels_index = tool_names.index("add_labels")
    assert tool_names[labels_index - 1:labels_index + 3] == [
        "layer_add_geometry", "add_labels", "spatial_graduated_colors",
        "spatial_unique_values",
    ]


def test_spatial_graduated_colors_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.spatial_graduated_colors is vector.spatial_graduated_colors
    tool_names = [tool.name for tool in tools.tools]
    colors_index = tool_names.index("spatial_graduated_colors")
    assert tool_names[colors_index - 1:colors_index + 3] == [
        "add_labels", "spatial_graduated_colors", "spatial_unique_values",
        "spatial_select_by_attribute",
    ]


def test_spatial_unique_values_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.spatial_unique_values is vector.spatial_unique_values
    tool_names = [tool.name for tool in tools.tools]
    unique_index = tool_names.index("spatial_unique_values")
    assert tool_names[unique_index - 1:unique_index + 3] == [
        "spatial_graduated_colors", "spatial_unique_values",
        "spatial_select_by_attribute", "add_legend",
    ]


def test_update_attribute_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.update_attribute is vector.update_attribute
    tool_names = [tool.name for tool in tools.tools]
    update_index = tool_names.index("update_attribute")
    assert tool_names[update_index - 1:update_index + 3] == [
        "add_legend", "update_attribute", "delete_features", "add_field",
    ]


def test_delete_features_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.delete_features is vector.delete_features
    tool_names = [tool.name for tool in tools.tools]
    delete_index = tool_names.index("delete_features")
    assert tool_names[delete_index - 1:delete_index + 2] == [
        "update_attribute", "delete_features", "add_field",
    ]


def test_add_field_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.add_field is vector.add_field
    tool_names = [tool.name for tool in tools.tools]
    add_index = tool_names.index("add_field")
    assert tool_names[add_index - 1:add_index + 2] == [
        "delete_features", "add_field", "delete_field",
    ]


def test_geojson_to_export_gdf_has_one_runtime_owner():
    from backend.services.tool_modules import io_export, runtime, vector

    assert io_export.geojson_to_export_gdf is runtime.geojson_to_export_gdf
    assert vector._geojson_to_export_gdf is runtime.geojson_to_export_gdf


def test_geojson_to_export_gdf_handles_empty_feature_collection():
    from backend.services.tool_modules.runtime import geojson_to_export_gdf

    gdf = geojson_to_export_gdf({"type": "FeatureCollection", "features": []})

    assert gdf.empty
    assert "geometry" in gdf.columns
    assert gdf.crs.to_epsg() == 4326


def test_delete_field_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.delete_field is vector.delete_field
    tool_names = [tool.name for tool in tools.tools]
    delete_index = tool_names.index("delete_field")
    assert tool_names[delete_index - 1:delete_index + 2] == [
        "add_field", "delete_field", "move_features",
    ]


def test_move_features_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.move_features is vector.move_features
    tool_names = [tool.name for tool in tools.tools]
    move_index = tool_names.index("move_features")
    assert tool_names[move_index - 1:move_index + 3] == [
        "delete_field", "move_features", "rotate_features", "scale_features",
    ]


def test_scale_features_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.scale_features is vector.scale_features
    tool_names = [tool.name for tool in tools.tools]
    scale_index = tool_names.index("scale_features")
    assert tool_names[scale_index - 1:scale_index + 2] == [
        "rotate_features", "scale_features", "draw_feature",
    ]


def test_facade_spatial_stats_limit_rebinds_to_vector(monkeypatch):
    from backend.services.tool_modules import vector

    monkeypatch.setattr(tools, "_MAX_DENSE_SPATIAL_STATS_FEATURES", 3)

    assert vector._MAX_DENSE_SPATIAL_STATS_FEATURES == 3
