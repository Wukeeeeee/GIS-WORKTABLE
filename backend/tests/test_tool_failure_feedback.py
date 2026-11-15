"""Returned GIS validation errors must reach API/history/workflow as failures."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import history_service, storage_service, task_manager, tools
from backend.services.workflow import WorkflowExecutor, new_node, new_workflow


@pytest.mark.parametrize("name,arguments", [
    ("layer_split", {"layer_name": "points", "by_field": "missing"}),
    ("layer_add_geometry", {"layer_name": "points", "lon_field": "x", "lat_field": "x"}),
    ("spatial_field_stats", {"layer_name": "points", "field": "category"}),
    ("geometry_attributes", {"layer_name": "points", "metrics": "unknown"}),
    ("spatial_cluster", {"layer_name": "points", "min_samples": 10}),
])
def test_vector_preconditions_are_failures(monkeypatch, name, arguments):
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    tools._register_layer("points", {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"x": 1, "category": "label"},
        "geometry": {"type": "Point", "coordinates": [116 + i * 0.001, 39]},
    } for i in range(2)]})
    tools.get_pending_state()
    result = tools._TOOL_REGISTRY[name].invoke(arguments)
    assert tools._tool_result_failed(name, result), result
    assert tools.get_pending_state()["layers"] == []


def test_valid_empty_selection_and_field_listing_are_not_failures(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    tools._register_layer("points", {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"category": "label"},
        "geometry": {"type": "Point", "coordinates": [116, 39]},
    }]})
    result = tools.spatial_select_by_attribute.invoke({
        "layer_name": "points", "field": "category", "operator": "=", "value": "absent",
    })
    assert not tools._tool_result_failed("spatial_select_by_attribute", result), result
    result = tools.spatial_field_stats.invoke({"layer_name": "points"})
    assert not tools._tool_result_failed("spatial_field_stats", result), result


@pytest.mark.parametrize("scenario", ["cost_crs", "cost_outside", "cost_nodata", "hydrology_crs", "reclass_nodata"])
def test_real_raster_preconditions_are_failures(monkeypatch, tmp_path, scenario):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))
    monkeypatch.setattr(tools, "_active_project_id", None)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    data = np.full((3, 3), -9999 if "nodata" in scenario else 1, dtype="float32")
    crs = None if scenario.endswith("crs") else "EPSG:4326"
    with rasterio.open(uploads / "cost.tif", "w", driver="GTiff", width=3, height=3,
                       count=1, dtype="float32", nodata=-9999, crs=crs,
                       transform=from_origin(0, 3, 1, 1)) as dst:
        dst.write(data, 1)
    coordinates = [10, 10] if scenario == "cost_outside" else [1.5, 1.5]
    tools._register_layer("source", {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Point", "coordinates": coordinates},
    }]})
    tools.get_pending_state()
    if scenario.startswith("cost"):
        name, arguments = "cost_distance", {"cost_layer": "cost", "source_layer": "source"}
    elif scenario == "hydrology_crs":
        name, arguments = "hydrology_analysis", {"layer_name": "cost"}
    else:
        name, arguments = "raster_reclassify", {"layer_name": "cost"}
    result = tools._TOOL_REGISTRY[name].invoke(arguments)
    assert tools._tool_result_failed(name, result), result
    assert tools.get_pending_state()["layers"] == []


@pytest.mark.parametrize("name,arguments", [
    ("spatial_centroid", {"layer_name": "missing vector"}),
    ("layer_control", {"action": "remove", "name": "missing vector"}),
    ("dem_analysis", {"layer_name": "missing raster"}),
    ("raster_resample", {"layer_name": "missing raster"}),
    ("cost_distance", {"cost_layer": "missing raster", "source_layer": "missing source"}),
    ("hydrology_analysis", {"layer_name": "missing raster", "analysis": "invalid"}),
    ("calc_spectral_index", {"layer_name": "missing raster", "index": "ndwi"}),
])
def test_validation_failure_reaches_all_consumers(monkeypatch, tmp_path, name, arguments):
    history = []
    finishes = []
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))
    monkeypatch.setattr(task_manager, "find_or_create_task", lambda *args: "")
    monkeypatch.setattr(storage_service, "record_run_start", lambda *args: True)
    monkeypatch.setattr(storage_service, "get_run_artifacts", lambda *args: [])
    monkeypatch.setattr(storage_service, "record_run_finish", lambda *args: finishes.append(args))
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))

    with TestClient(app) as client:
        response = client.post("/api/tools/invoke", json={"name": name, "arguments": arguments})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is False, result
    assert history[-1][2] is False
    assert finishes[-1][2] == "failed"

    workflow = new_workflow("failure feedback", nodes=[new_node("n1", "analysis", name)])
    executor = WorkflowExecutor({name: lambda: result["response"]})
    assert executor.execute(workflow)["status"] == "failed"
