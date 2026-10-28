from io import BytesIO

import numpy as np
import rasterio
from rasterio.enums import ColorInterp
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
    assert "raster_info" in response.json(), response.json()
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


def test_rgba_geotiff_upload_reprojects_alpha_and_preserves_source(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    raster_bytes = BytesIO()
    transform = from_bounds(10, 55, 30, 75, 4, 4)
    with rasterio.open(
        raster_bytes, "w", driver="GTiff", width=4, height=4, count=4,
        dtype="uint8", crs="EPSG:4326", transform=transform,
    ) as dataset:
        dataset.write(np.full((4, 4), 160, dtype=np.uint8), 1)
        dataset.write(np.full((4, 4), 80, dtype=np.uint8), 2)
        dataset.write(np.full((4, 4), 40, dtype=np.uint8), 3)
        alpha = np.full((4, 4), 128, dtype=np.uint8)
        alpha[0, 0] = 0
        dataset.write(alpha, 4)
        dataset.colorinterp = (
            ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha,
        )
    source_bytes = raster_bytes.getvalue()

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("rgba-source.tif", source_bytes, "image/tiff")},
        )

    assert response.status_code == 200
    assert "raster_info" in response.json(), response.json()
    info = response.json()["raster_info"]
    assert (tmp_path / "uploads" / "rgba-source.tif").read_bytes() == source_bytes
    with Image.open(tmp_path / "uploads" / info["filename"]) as preview:
        alpha_preview = np.asarray(preview.getchannel("A"))
        assert np.any(alpha_preview > 0)
        assert np.any(alpha_preview < 255)


def test_rgba_geotiff_preview_keeps_nodata_pixels_transparent(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    raster_bytes = BytesIO()
    transform = from_bounds(0, 0, 4, 4, 4, 4)
    rgb = np.full((4, 4), 100, dtype=np.uint8)
    rgb[1, 1] = 0
    with rasterio.open(
        raster_bytes, "w", driver="GTiff", width=4, height=4, count=4,
        dtype="uint8", crs="EPSG:3857", transform=transform, nodata=0,
    ) as dataset:
        dataset.write(rgb, 1)
        dataset.write(rgb, 2)
        dataset.write(rgb, 3)
        dataset.write(np.full((4, 4), 255, dtype=np.uint8), 4)
        dataset.colorinterp = (
            ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha,
        )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("rgba-nodata.tif", raster_bytes.getvalue(), "image/tiff")},
        )

    assert response.status_code == 200, response.json()
    info = response.json()["raster_info"]
    with Image.open(tmp_path / "uploads" / info["filename"]) as preview:
        alpha_preview = np.asarray(preview.getchannel("A"))
    assert alpha_preview[1, 1] == 0


def test_geotiff_upload_uses_color_interpretation_when_alpha_is_first_band(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    transform = from_bounds(0, 0, 4, 4, 4, 4)
    rows, columns = np.indices((4, 4))
    red = (40 + columns * 40).astype(np.uint8)
    green = (30 + rows * 50).astype(np.uint8)
    blue = (20 + (rows + columns) * 20).astype(np.uint8)
    alpha = (80 + rows * 40).astype(np.uint8)

    def make_raster(bands, interpretations):
        raster_bytes = BytesIO()
        with rasterio.open(
            raster_bytes, "w", driver="GTiff", width=4, height=4, count=4,
            dtype="uint8", crs="EPSG:3857", transform=transform,
        ) as dataset:
            for band, values in enumerate(bands, start=1):
                dataset.write(values, band)
            dataset.colorinterp = interpretations
        return raster_bytes.getvalue()

    conventional = make_raster(
        (red, green, blue, alpha),
        (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha),
    )
    alpha_first = make_raster(
        (alpha, red, green, blue),
        (ColorInterp.alpha, ColorInterp.red, ColorInterp.green, ColorInterp.blue),
    )

    with TestClient(main.app) as client:
        conventional_response = client.post(
            "/api/upload",
            files={"file": ("conventional.tif", conventional, "image/tiff")},
        )
        alpha_first_response = client.post(
            "/api/upload",
            files={"file": ("alpha-first.tif", alpha_first, "image/tiff")},
        )

    assert conventional_response.status_code == 200, conventional_response.json()
    assert alpha_first_response.status_code == 200, alpha_first_response.json()
    conventional_info = conventional_response.json()["raster_info"]
    info = alpha_first_response.json()["raster_info"]
    with Image.open(tmp_path / "uploads" / conventional_info["filename"]) as reference:
        expected_rgb = np.asarray(reference.convert("RGB"))
    with Image.open(tmp_path / "uploads" / info["filename"]) as preview:
        np.testing.assert_array_equal(np.asarray(preview.convert("RGB")), expected_rgb)


def test_geotiff_upload_reports_rotated_pixel_axis_lengths(tmp_path, monkeypatch):
    from affine import Affine

    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    angle = np.radians(30)
    pixel = 30.0
    transform = Affine(
        pixel * np.cos(angle), pixel * np.sin(angle), 500_000,
        pixel * np.sin(angle), -pixel * np.cos(angle), 4_000_000,
    )
    raster_bytes = BytesIO()
    with rasterio.open(
        raster_bytes, "w", driver="GTiff", width=8, height=8, count=1,
        dtype="uint8", crs="EPSG:32611", transform=transform,
    ) as dataset:
        dataset.write(np.ones((8, 8), dtype=np.uint8), 1)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("rotated.tif", raster_bytes.getvalue(), "image/tiff")},
        )

    assert response.status_code == 200, response.json()
    assert np.allclose(response.json()["raster_info"]["pixel_size"], [30.0, 30.0])


def test_large_geotiff_uses_bounded_preview_and_preserves_full_resolution_source(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    raster_bytes = BytesIO()
    values = np.full((2000, 3000), 100, dtype=np.uint8)
    with rasterio.open(
        raster_bytes, "w", driver="GTiff", width=3000, height=2000, count=1,
        dtype="uint8", crs="EPSG:4326", transform=from_bounds(10, 20, 11, 21, 3000, 2000),
    ) as dataset:
        dataset.write(values, 1)
    source_bytes = raster_bytes.getvalue()

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("large-dem.tif", source_bytes, "image/tiff")},
        )

    assert response.status_code == 200
    assert "raster_info" in response.json(), response.json()
    raster_info = response.json()["raster_info"]
    assert raster_info["source_width"] == 3000
    assert raster_info["source_height"] == 2000
    assert raster_info["preview_downsampled"] is True
    assert raster_info["width"] * raster_info["height"] <= main._MAX_RASTER_PREVIEW_PIXELS
    assert any("后续栅格分析仍使用保留的原始 GeoTIFF" in warning for warning in raster_info["quality_warnings"])
    assert (tmp_path / "uploads" / "large-dem.tif").read_bytes() == source_bytes


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
