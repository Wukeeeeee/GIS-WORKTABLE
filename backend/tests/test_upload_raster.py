from io import BytesIO

import numpy as np
import rasterio
from fastapi.testclient import TestClient
from PIL import Image
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import calculate_default_transform, transform_bounds

from backend import main


def test_geotiff_upload_reprojects_pixels_and_extent_for_leaflet(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    raster_bytes = BytesIO()
    transform = from_bounds(10, 55, 30, 75, 4, 4)
    values = np.arange(1, 17, dtype=np.uint8).reshape((4, 4))
    values[0, 0] = 0
    with rasterio.open(
        raster_bytes, "w", driver="GTiff", width=4, height=4, count=3,
        dtype="uint8", crs="EPSG:4326", transform=transform, nodata=0,
    ) as dataset:
        for band in (1, 2, 3):
            dataset.write(values, band)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("projected-source.tif", raster_bytes.getvalue(), "image/tiff")},
        )

    assert response.status_code == 200
    raster_info = response.json()["raster_info"]
    output_path = tmp_path / "uploads" / raster_info["filename"]
    with Image.open(output_path) as image:
        assert image.mode == "RGBA"
        assert image.size == (raster_info["width"], raster_info["height"])
        assert image.size != (4, 4)
        assert np.any(np.asarray(image.getchannel("A")) == 0)

    destination_transform, width, height = calculate_default_transform(
        "EPSG:4326", "EPSG:3857", 4, 4, 10, 55, 30, 75,
    )
    expected_bounds = transform_bounds(
        "EPSG:3857", "EPSG:4326", *array_bounds(height, width, destination_transform),
    )
    assert raster_info["width"] == width
    assert raster_info["height"] == height
    assert np.allclose(raster_info["bounds"], expected_bounds)


def test_same_named_geotiff_uploads_keep_separate_png_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))

    def make_raster(values):
        data = BytesIO()
        with rasterio.open(
            data, "w", driver="GTiff", width=4, height=4, count=3,
            dtype="uint8", crs="EPSG:4326", transform=from_bounds(10, 55, 30, 75, 4, 4),
        ) as dataset:
            for band in (1, 2, 3):
                dataset.write(values, band)
        return data.getvalue()

    first_values = np.arange(1, 17, dtype=np.uint8).reshape((4, 4))
    second_values = np.flip(first_values, axis=1).copy()
    with TestClient(main.app) as client:
        first = client.post("/api/upload", files={
            "file": ("elevation.tif", make_raster(first_values), "image/tiff"),
        })
        first_info = first.json()["raster_info"]
        first_asset = tmp_path / "uploads" / first_info["filename"]
        original_first_asset = first_asset.read_bytes()
        second = client.post("/api/upload", files={
            "file": ("elevation.tif", make_raster(second_values), "image/tiff"),
        })

    assert first.status_code == second.status_code == 200
    second_info = second.json()["raster_info"]
    second_asset = tmp_path / "uploads" / second_info["filename"]
    assert first_info["filename"] == "elevation.png"
    assert second_info["filename"] == "elevation_1.png"
    assert first_info["url"] != second_info["url"]
    assert first_asset.read_bytes() == original_first_asset
    assert second_asset.read_bytes() != original_first_asset


def test_geotiff_without_crs_is_rejected_and_source_file_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    raster_bytes = BytesIO()
    values = np.arange(1, 17, dtype=np.uint8).reshape((4, 4))
    with rasterio.open(
        raster_bytes, "w", driver="GTiff", width=4, height=4, count=3,
        dtype="uint8", transform=from_bounds(10, 55, 30, 75, 4, 4),
    ) as dataset:
        for band in (1, 2, 3):
            dataset.write(values, band)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("unreferenced.tif", raster_bytes.getvalue(), "image/tiff")},
        )

    assert response.status_code == 200
    assert response.json()["error"] == "GeoTIFF 缺少坐标参考系，无法安全定位到地图；请先定义 CRS 后重新上传"
    assert not (tmp_path / "uploads" / "unreferenced.tif").exists()
    assert not (tmp_path / "uploads" / "unreferenced.png").exists()


def test_geotiff_processing_failure_removes_uploaded_source_and_partial_output(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    raster_bytes = BytesIO()
    values = np.arange(1, 17, dtype=np.uint8).reshape((4, 4))
    with rasterio.open(
        raster_bytes, "w", driver="GTiff", width=4, height=4, count=3,
        dtype="uint8", crs="EPSG:4326", transform=from_bounds(10, 55, 30, 75, 4, 4),
    ) as dataset:
        for band in (1, 2, 3):
            dataset.write(values, band)

    save_image = Image.Image.save

    def save_then_fail(image, path, *args, **kwargs):
        save_image(image, path, *args, **kwargs)
        raise RuntimeError("simulated raster processing failure")

    monkeypatch.setattr(Image.Image, "save", save_then_fail)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("processing-error.tif", raster_bytes.getvalue(), "image/tiff")},
        )

    assert response.status_code == 200
    assert "simulated raster processing failure" in response.json()["error"]
    assert not (tmp_path / "uploads" / "processing-error.tif").exists()
    assert not (tmp_path / "uploads" / "processing-error.png").exists()
