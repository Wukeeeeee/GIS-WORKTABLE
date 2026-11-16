import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.services import tools as T
from backend.services.tools import _register_layer, reset_state


def _isolate_nearest_pair_runtime(monkeypatch, tmp_path):
    from backend.services.tool_modules import runtime

    output_dir = str(tmp_path / "tool-runtime")
    isolated_runtime = {
        "_registered_layers": {},
        "_pending_layers": [],
        "_pending_layer_ops": [],
        "_pending_images": [],
        "_pending_qa_warnings": [],
        "_pending_aoi_suggestions": {},
        "_pending_heatmap": {"latest": None},
        "_clear_layers_flag": False,
        "_current_amap_key": "",
        "_search_call_count": 0,
        "_domain_fail": {},
        "_search_cache": {},
        "_search_last_hit": {},
        "_exec_call_count": 0,
        "_exec_log": [],
        "_temp_output_dir": output_dir,
        "_workspace_dir": str(tmp_path / "workspace"),
        "_raster_output_scope": threading.local(),
        "_active_project_id": None,
        "_current_task_id": "",
        "_last_user_message": "",
        "_current_run_id": "",
        "_conversation_context": "",
        "_session_locks": {},
    }
    for path in (output_dir, os.path.join(output_dir, "output"), isolated_runtime["_workspace_dir"]):
        os.makedirs(path, exist_ok=True)
    with runtime._state_lock, runtime._session_locks_guard:
        for name, value in isolated_runtime.items():
            monkeypatch.setattr(T, name, value)


@pytest.fixture(autouse=True)
def cleanup_layers(tmp_path, monkeypatch):
    _isolate_nearest_pair_runtime(monkeypatch, tmp_path)
    reset_state()
    yield
    reset_state()


def test_nearest_pair_fixture_restores_existing_runtime_state(tmp_path):
    from backend.services.tool_modules import runtime

    registry, pending_ops = runtime._registered_layers, runtime._pending_layer_ops
    registry["outside-sentinel"] = {"sentinel": True}
    pending_ops.append({"action": "outside-sentinel"})
    runtime.set_current_task("outside-nearest-pair-task-context")

    patcher = pytest.MonkeyPatch()
    try:
        _isolate_nearest_pair_runtime(patcher, tmp_path)
        assert runtime._registered_layers is not registry
        assert runtime._pending_layer_ops is not pending_ops
        assert T._registered_layers is runtime._registered_layers
    finally:
        patcher.undo()

    assert runtime._registered_layers is registry
    assert registry["outside-sentinel"]["sentinel"]
    assert runtime._pending_layer_ops is pending_ops
    assert pending_ops[-1]["action"] == "outside-sentinel"
    assert runtime.get_current_task_id() == "outside-nearest-pair-task-context"


def _points():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "中心医院", "category": "医院"},
             "geometry": {"type": "Point", "coordinates": [120.0, 30.0]}},
            {"type": "Feature", "properties": {"name": "麦当劳湖滨店", "category": "麦当劳"},
             "geometry": {"type": "Point", "coordinates": [120.1, 30.1]}},
            {"type": "Feature", "properties": {"name": "麦当劳东站店", "category": "麦当劳"},
             "geometry": {"type": "Point", "coordinates": [120.1001, 30.1]}},
            {"type": "Feature", "properties": {"name": "麦当劳机场店", "category": "麦当劳"},
             "geometry": {"type": "Point", "coordinates": [120.2, 30.2]}},
        ],
    }


def test_nearest_pair_finds_global_pair_and_returns_names_and_distance():
    _register_layer("mixed_poi", _points())

    result = T.nearest_pair.invoke({"layer_name": "mixed_poi"})

    assert "麦当劳湖滨店" in result
    assert "麦当劳东站店" in result
    assert "米" in result


def test_nearest_pair_can_filter_features_before_comparing():
    _register_layer("mixed_poi", _points())

    result = T.nearest_pair.invoke({"layer_name": "mixed_poi", "feature_filter": "麦当劳"})

    assert "麦当劳湖滨店" in result
    assert "麦当劳东站店" in result
    assert "中心医院" not in result
    assert "属性包含「麦当劳」" in result


def test_nearest_pair_supports_two_registered_layers():
    _register_layer("餐饮POI", _points())
    _register_layer("医院_POI(OSM)", {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "湖滨医院"},
             "geometry": {"type": "Point", "coordinates": [120.10012, 30.1]}},
            {"type": "Feature", "properties": {"name": "远郊医院"},
             "geometry": {"type": "Point", "coordinates": [120.3, 30.3]}},
        ],
    })

    registered = T.get_registered_layers.invoke({})
    result = T.nearest_pair.invoke({
        "layer_name": "餐饮POI",
        "feature_filter": "麦当劳",
        "target_layer": "医院_POI(OSM)",
    })

    assert "餐饮POI" in registered and "医院_POI(OSM)" in registered
    assert "麦当劳东站店" in result
    assert "湖滨医院" in result
    assert "米" in result


@pytest.mark.parametrize("coordinates, expected", [
    ([[179, 10], [-179, 10]], "跨越日期变更线"),
    ([[0, 10], [8, 10]], "超过 6° 经度"),
])
def test_nearest_pair_rejects_ranges_outside_one_local_utm(coordinates, expected):
    _register_layer("wide_poi", {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": str(index)},
             "geometry": {"type": "Point", "coordinates": point}}
            for index, point in enumerate(coordinates)
        ],
    })

    result = T.nearest_pair.invoke({"layer_name": "wide_poi"})

    assert expected in result
