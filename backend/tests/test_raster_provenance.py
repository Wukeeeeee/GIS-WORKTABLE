import numpy as np
import rasterio
from rasterio.transform import from_origin

from backend.services import tools


def test_resample_and_followup_dem_analysis_preserve_raster_provenance(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    source_path = upload_dir / "changsha_dem.tif"
    data = np.arange(49, dtype="float32").reshape(7, 7)
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=7,
        height=7,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(112.9, 28.22, 0.0002, 0.0002),
        nodata=-9999,
    ) as dataset:
        dataset.write(data, 1)
        dataset.update_tags(
            SOURCE_LABEL="AWS Terrain Tiles (SRTM-derived)",
            SOURCE_URL="https://registry.opendata.aws/terrain-tiles/",
            VALUE_UNITS="m",
            QUALITY_NOTE="source quality checked",
        )

    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    tools._register_raster_layer(
        "长沙 DEM",
        {
            "bounds": [112.9, 28.2186, 112.9014, 28.22],
            "crs": "EPSG:4326",
            "source_label": "AWS Terrain Tiles (SRTM-derived)",
            "source_reference": "https://registry.opendata.aws/terrain-tiles/",
            "value_units": "m",
            "quality_warnings": ["source quality checked"],
        },
        str(source_path),
    )

    resample_result = tools.raster_resample.func(
        layer_name="长沙 DEM", scale_factor=2, method="nearest"
    )
    assert "重采样完成" in resample_result
    resample_op = next(
        op for op in tools._pending_layer_ops if op.get("action") == "dem_result"
    )
    resampled = resample_op["raster"]
    assert resampled["source_layer"] == "长沙 DEM"
    assert resampled["source_label"] == "AWS Terrain Tiles (SRTM-derived)"
    assert resampled["source_reference"] == "https://registry.opendata.aws/terrain-tiles/"
    assert resampled["crs"] == "EPSG:4326"
    assert resampled["pixel_units"] == "degree"
    assert resampled["value_units"] == "m"
    assert "source quality checked" in resampled["quality_warnings"]

    resampled_path = upload_dir / resampled["source_filename"]
    with rasterio.open(resampled_path) as dataset:
        tags = dataset.tags()
    assert tags["SOURCE_LAYER"] == "长沙 DEM"
    assert tags["SOURCE_LABEL"] == "AWS Terrain Tiles (SRTM-derived)"
    assert tags["SOURCE_URL"] == "https://registry.opendata.aws/terrain-tiles/"
    assert tags["VALUE_UNITS"] == "m"

    derived_operations = [
        (tools.raster_reproject, {"layer_name": "长沙 DEM", "target_crs": "EPSG:4326"}, "m"),
        (tools.raster_reclassify, {"layer_name": "长沙 DEM", "mapping": "0-20=1;20+=2"}, "类别编码（无量纲）"),
        (tools.raster_focal_stats, {"layer_name": "长沙 DEM", "stat": "mean", "size": 3}, "m"),
    ]
    for raster_tool, args, expected_units in derived_operations:
        result = raster_tool.func(**args)
        assert "完成" in result
        operation = tools._pending_layer_ops[-1]
        derived = operation["raster"]
        assert derived["source_layer"] == "长沙 DEM"
        assert derived["source_label"] == "AWS Terrain Tiles (SRTM-derived)"
        assert derived["source_reference"] == "https://registry.opendata.aws/terrain-tiles/"
        assert derived["crs"] == "EPSG:4326"
        assert derived["value_units"] == expected_units

    followup_result = tools.dem_analysis.func(
        layer_name=resample_op["layer_name"], analysis="slope"
    )
    assert "坡度(Slope) GeoTIFF" in followup_result
    slope_op = [
        op for op in tools._pending_layer_ops
        if op.get("action") == "dem_result" and op["raster"].get("processing") == "坡度(Slope)"
    ][-1]
    slope_raster = slope_op["raster"]
    assert slope_raster["source_layer"] == resample_op["layer_name"]
    assert slope_raster["source_label"] == "AWS Terrain Tiles (SRTM-derived)"
    assert slope_raster["source_reference"] == "https://registry.opendata.aws/terrain-tiles/"
    assert slope_raster["value_units"] == "°（角度）"
