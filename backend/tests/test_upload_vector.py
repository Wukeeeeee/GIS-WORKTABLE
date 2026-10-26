from fastapi.testclient import TestClient
import geopandas as gpd
import pytest
from shapely.geometry import Point
import zipfile

from backend import main


def test_projected_gpkg_upload_reprojects_features_to_wgs84(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    source_path = tmp_path / "projected.gpkg"
    gdf = gpd.GeoDataFrame(
        {"name": ["projected point"]},
        geometry=[Point(1_000_000, 6_000_000)],
        crs="EPSG:3857",
    )
    gdf.to_file(source_path, layer="points", driver="GPKG")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (source_path.name, source_path.read_bytes(), "application/geopackage+sqlite3")},
        )

    assert response.status_code == 200
    result = response.json()
    coordinates = result["geojson"]["features"][0]["geometry"]["coordinates"]
    assert coordinates[0] == pytest.approx(8.98315, abs=1e-4)
    assert coordinates[1] == pytest.approx(47.35370, abs=1e-4)
    assert result["provenance"]["provider"] == "local_upload"
    assert result["provenance"]["file_format"] == "GeoPackage"
    assert result["provenance"]["crs"] == "EPSG:3857"
    assert result["provenance"]["crs_known"] is True


def test_projected_shapefile_zip_upload_reprojects_features_to_wgs84(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    source_path = tmp_path / "projected.shp"
    gdf = gpd.GeoDataFrame(
        {"name": ["projected point"]},
        geometry=[Point(1_000_000, 6_000_000)],
        crs="EPSG:3857",
    )
    gdf.to_file(source_path, driver="ESRI Shapefile")
    archive_path = tmp_path / "projected.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for component in tmp_path.glob("projected.*"):
            if component.suffix.lower() in {".shp", ".dbf", ".shx", ".prj", ".cpg"}:
                archive.write(component, "projected.SHP" if component.suffix.lower() == ".shp" else component.name)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (archive_path.name, archive_path.read_bytes(), "application/zip")},
        )

    assert response.status_code == 200
    result = response.json()
    coordinates = result["geojson"]["features"][0]["geometry"]["coordinates"]
    assert coordinates[0] == pytest.approx(8.98315, abs=1e-4)
    assert coordinates[1] == pytest.approx(47.35370, abs=1e-4)
    assert result["provenance"]["file_format"] == "Shapefile ZIP"
    assert result["provenance"]["crs"] == "EPSG:3857"


def test_vector_upload_without_crs_returns_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(tmp_path))
    source_path = tmp_path / "unknown-crs.gpkg"
    gpd.GeoDataFrame(
        {"name": ["unknown point"]}, geometry=[Point(1_000_000, 6_000_000)],
    ).to_file(source_path, layer="points", driver="GPKG")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (source_path.name, source_path.read_bytes(), "application/geopackage+sqlite3")},
        )

    assert response.status_code == 200
    assert "缺少坐标参考系" in response.json()["error"]
