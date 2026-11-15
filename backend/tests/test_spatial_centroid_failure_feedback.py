"""Spatial centroid empty-result failures must not be recorded as successes."""

import geopandas as gpd

from backend.services import history_service, tools
from backend.services.tool_modules import vector


def test_layer_without_valid_geometries_is_reported_as_failure(monkeypatch):
    history = []
    frame = gpd.GeoDataFrame({"geometry": [None]}, geometry="geometry", crs="EPSG:3857")
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    monkeypatch.setattr(vector, "_layer_to_gdf", lambda _name: (frame, "empty-geometry"))
    monkeypatch.setattr(vector, "_to_local_metric_gdf", lambda _frame: frame)

    result = next(tool for tool in tools.tools if tool.name == "spatial_centroid").invoke({
        "layer_name": "empty-geometry",
    })

    assert "没有可用于质心计算的有效几何" in result
    assert tools._tool_result_failed("spatial_centroid", result)
    assert history[-1][2] is False
