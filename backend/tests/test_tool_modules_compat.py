"""Compatibility checks for the tools facade and modular shared runtime."""

import os
import threading

from backend.services import tools
from backend.services.tool_modules import map_ops, runtime


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


def test_pytest_unconfigure_restores_caller_proj_environment(monkeypatch):
    import conftest

    monkeypatch.setattr(conftest, "_PREVIOUS_PROJ_ENV", {
        "PROJ_LIB": "caller-proj-lib",
        "PROJ_DATA": "caller-proj-data",
    })
    monkeypatch.setattr(conftest, "_ARROW_MODULE", None)
    monkeypatch.setattr(conftest, "_PREVIOUS_ARROW_THREAD_COUNTS", None)
    monkeypatch.setattr(conftest, "_WORKSPACE_DB_ENV_ACTIVE", False)
    monkeypatch.setenv("PROJ_LIB", "test-proj-lib")
    monkeypatch.setenv("PROJ_DATA", "test-proj-data")

    conftest.pytest_unconfigure(None)

    assert os.environ["PROJ_LIB"] == "caller-proj-lib"
    assert os.environ["PROJ_DATA"] == "caller-proj-data"


def test_pytest_unconfigure_keeps_proj_environment_unset_when_previously_absent(monkeypatch):
    import conftest

    monkeypatch.setattr(conftest, "_PREVIOUS_PROJ_ENV", {
        "PROJ_LIB": None,
        "PROJ_DATA": None,
    })
    monkeypatch.setattr(conftest, "_ARROW_MODULE", None)
    monkeypatch.setattr(conftest, "_PREVIOUS_ARROW_THREAD_COUNTS", None)
    monkeypatch.setattr(conftest, "_WORKSPACE_DB_ENV_ACTIVE", False)
    monkeypatch.setenv("PROJ_LIB", "test-proj-lib")
    monkeypatch.setenv("PROJ_DATA", "test-proj-data")

    conftest.pytest_unconfigure(None)

    assert "PROJ_LIB" not in os.environ
    assert "PROJ_DATA" not in os.environ


def test_pytest_unconfigure_restores_numeric_thread_limits(monkeypatch):
    import conftest

    previous = {
        "OPENBLAS_NUM_THREADS": "caller-openblas",
        "OMP_NUM_THREADS": "caller-openmp",
        "MKL_NUM_THREADS": None,
        "NUMEXPR_NUM_THREADS": "caller-numexpr",
        "VECLIB_MAXIMUM_THREADS": None,
    }
    monkeypatch.setattr(conftest, "_PREVIOUS_THREAD_LIMIT_ENV", previous)
    monkeypatch.setattr(conftest, "_ARROW_MODULE", None)
    monkeypatch.setattr(conftest, "_PREVIOUS_ARROW_THREAD_COUNTS", None)
    monkeypatch.setattr(conftest, "_WORKSPACE_DB_ENV_ACTIVE", False)
    for name in conftest._THREAD_LIMIT_ENV_KEYS:
        monkeypatch.setenv(name, "1")

    conftest.pytest_unconfigure(None)

    for name, value in previous.items():
        assert os.environ.get(name) == value


def test_pytest_unconfigure_restores_pyarrow_thread_counts(monkeypatch):
    import conftest

    class FakeArrow:
        def __init__(self):
            self.counts = []

        def set_cpu_count(self, count):
            self.counts.append(("cpu", count))

        def set_io_thread_count(self, count):
            self.counts.append(("io", count))

    arrow = FakeArrow()
    monkeypatch.setattr(conftest, "_ARROW_MODULE", arrow)
    monkeypatch.setattr(conftest, "_PREVIOUS_ARROW_THREAD_COUNTS", (6, 4))
    monkeypatch.setattr(conftest, "_WORKSPACE_DB_ENV_ACTIVE", False)

    conftest.pytest_unconfigure(None)

    assert arrow.counts == [("cpu", 6), ("io", 4)]


def test_pytest_configure_limits_pyarrow_thread_counts(monkeypatch):
    import sys
    import conftest

    class FakeArrow:
        def __init__(self):
            self.counts = {"cpu": 6, "io": 4}

        def cpu_count(self):
            return self.counts["cpu"]

        def io_thread_count(self):
            return self.counts["io"]

        def set_cpu_count(self, count):
            self.counts["cpu"] = count

        def set_io_thread_count(self, count):
            self.counts["io"] = count

    arrow = FakeArrow()
    monkeypatch.setitem(sys.modules, "pyarrow", arrow)
    monkeypatch.setattr(conftest, "_PREVIOUS_PROJ_ENV", {})
    monkeypatch.setattr(conftest, "_PREVIOUS_THREAD_LIMIT_ENV", {})

    conftest.pytest_configure(None)
    try:
        assert conftest._PREVIOUS_ARROW_THREAD_COUNTS == (6, 4)
        assert conftest._ARROW_MODULE is arrow
        assert arrow.counts == {"cpu": 1, "io": 1}
    finally:
        conftest.pytest_unconfigure(None)

    assert arrow.counts == {"cpu": 6, "io": 4}


def test_map_ops_uses_the_current_runtime_queue_object(monkeypatch):
    pending_ops = []
    monkeypatch.setattr(runtime, "_pending_layer_ops", pending_ops)

    result = map_ops._focus_map_impl(center="121.5,31.2", zoom=15)

    assert result == "已定位到 (31.2000, 121.5000)，缩放级别 15"
    assert pending_ops == [{"action": "center", "center": [121.5, 31.2], "zoom": 15}]


def test_layer_lookup_waits_for_registry_state_lock(monkeypatch):
    monkeypatch.setattr(runtime, "_registered_layers", {"roads": {"name": "roads"}})
    started = threading.Event()
    finished = threading.Event()
    result = []

    def lookup():
        started.set()
        result.append(runtime._get_exact_registered_layer("roads"))
        finished.set()

    worker = threading.Thread(target=lookup)
    with runtime._state_lock:
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.05)
    assert finished.wait(timeout=1)
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert result[0][0] == "roads"


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


def test_map_and_pdf_export_tools_delegate_to_io_export(monkeypatch):
    from backend.services.tool_modules import io_export, runtime

    pending_ops = []
    calls = []
    monkeypatch.setattr(tools, "_pending_layer_ops", pending_ops)

    def export_map_impl(format, *, pending_layer_ops):
        calls.append(("map", format, pending_layer_ops))
        return "map implementation delegated"

    def export_pdf_impl(title, rotation_degrees, *, pending_layer_ops):
        calls.append(("pdf", title, rotation_degrees, pending_layer_ops))
        return "pdf implementation delegated"

    monkeypatch.setattr(io_export, "export_map_impl", export_map_impl, raising=False)
    monkeypatch.setattr(io_export, "export_pdf_impl", export_pdf_impl, raising=False)

    assert tools.export_map.invoke({"format": "jpg"}) == "map implementation delegated"
    assert tools.export_pdf.invoke({"title": "验收", "rotation_degrees": 15}) == "pdf implementation delegated"
    assert tools.export_map.name == "export_map"
    assert tools.export_pdf.name == "export_pdf"
    assert runtime._pending_layer_ops is pending_ops
    assert calls == [
        ("map", "jpg", pending_ops),
        ("pdf", "验收", 15, pending_ops),
    ]


def test_layer_control_tool_delegates_to_map_ops(monkeypatch):
    pending_ops = []
    calls = []
    monkeypatch.setattr(tools, "_pending_layer_ops", pending_ops)

    def layer_control_impl(action, name, new_name, color, opacity, weight, fill_pattern):
        calls.append((action, name, new_name, color, opacity, weight, fill_pattern))
        return "map layer control delegated"

    monkeypatch.setattr(map_ops, "_layer_control_impl", layer_control_impl)

    assert tools.layer_control.invoke({
        "action": "toggle", "name": "roads", "color": "#123456",
    }) == "map layer control delegated"
    assert tools.layer_control.name == "layer_control"
    assert not hasattr(runtime, "_layer_control_impl")
    assert runtime._pending_layer_ops is pending_ops
    assert calls == [("toggle", "roads", "", "#123456", 1.0, 2, "")]


def test_focus_map_tool_delegates_to_map_ops(monkeypatch):
    pending_ops = []
    calls = []
    monkeypatch.setattr(tools, "_pending_layer_ops", pending_ops)

    def focus_map_impl(layer_name, center, zoom):
        calls.append((layer_name, center, zoom))
        return "map focus map delegated"

    monkeypatch.setattr(map_ops, "_focus_map_impl", focus_map_impl)

    assert tools.focus_map.invoke({"center": "121.5,31.2", "zoom": 15}) == "map focus map delegated"
    assert tools.focus_map.name == "focus_map"
    assert not hasattr(runtime, "_focus_map_impl")
    assert runtime._pending_layer_ops is pending_ops
    assert calls == [("", "121.5,31.2", 15)]


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


def test_rotate_features_is_owned_by_vector_and_reexported_by_facade():
    from backend.services.tool_modules import vector

    assert tools.rotate_features is vector.rotate_features
    tool_names = [tool.name for tool in tools.tools]
    rotate_index = tool_names.index("rotate_features")
    assert tool_names[rotate_index - 1:rotate_index + 2] == [
        "move_features", "rotate_features", "scale_features",
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


def test_create_workflow_implementation_is_injected_and_facade_order_is_stable():
    from backend.services.tool_modules import workflow_tools

    calls = []
    failures = []

    class StubTool:
        def __init__(self, name):
            self.name = name

        def invoke(self, arguments):
            calls.append((self.name, arguments))
            return self.name + "-done"

    result = workflow_tools.create_workflow_impl(
        '[{"tool":"first","params":{"input":"seed"},"output":"layer-a"},'
        '{"tool":"second","params":{"source":"$prev","prior":"$1"},"output":"layer-b"}]',
        tool_provider=lambda: [StubTool("first"), StubTool("second")],
        failure_classifier=lambda name, value: failures.append((name, value)) or False,
    )

    assert calls == [
        ("first", {"input": "seed"}),
        ("second", {"source": "layer-a", "prior": "layer-a"}),
    ]
    assert failures == [("first", "first-done"), ("second", "second-done")]
    assert result == (
        "工作流执行完成:\n"
        "步骤1(first) → layer-a: first-done\n"
        "步骤2(second) → layer-b: second-done"
    )

    assert tools.create_workflow.name == "create_workflow"
    assert tools._TOOL_REGISTRY["create_workflow"] is tools.create_workflow
    tool_names = [tool.name for tool in tools.tools]
    index = tool_names.index("create_workflow")
    assert tool_names.count("create_workflow") == 1
    assert tool_names[index - 1:index + 2] == [
        "hydrology_analysis", "create_workflow", "view_3d_terrain",
    ]


def test_create_workflow_facade_stops_on_registered_tool_failure(monkeypatch):
    class FailingTool:
        name = "spatial_buffer"

        def invoke(self, _arguments):
            return "工具执行失败: synthetic failure"

    monkeypatch.setattr(tools, "tools", [FailingTool()])
    result = tools.create_workflow.invoke(
        '{"not-a-list": true}'
    )
    assert "必须是非空数组" in result

    result = tools.create_workflow.invoke(
        '[{"tool":"spatial_buffer","params":{},"output":"buffer"}]'
    )
    assert result == "工作流执行失败：第1步 'spatial_buffer' 执行失败: 工具执行失败: synthetic failure"


def test_materialize_workflow_implementation_uses_injected_task_and_storage(tmp_path):
    from backend.services.tool_modules import workflow_tools

    materialized = []
    saved = []
    workflow = {
        "id": "workflow-probe",
        "name": "probe workflow",
        "nodes": [{"name": "buffer", "tool": "spatial_buffer"}],
    }

    def materialize(task_id, *, workflow_name):
        materialized.append((task_id, workflow_name))
        return workflow

    def save(candidate, filepath):
        saved.append((candidate, filepath))
        return True

    result = workflow_tools.materialize_workflow_impl(
        "custom name",
        task_id_provider=lambda: "task-probe",
        output_dir=str(tmp_path),
        materialize_from_history=materialize,
        save_workflow=save,
    )

    expected_path = str(tmp_path / "workflows" / "workflow-probe.giswork")
    assert materialized == [("task-probe", "custom name")]
    assert saved == [(workflow, expected_path)]
    assert "probe workflow" in result
    assert expected_path in result
