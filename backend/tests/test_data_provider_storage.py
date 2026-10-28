import os

import pytest

from backend.services.data_providers import storage
from backend.services.data_providers.errors import DownloadError


def _polygon(version: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"version": version},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            },
        }],
    }


def test_failed_shapefile_replacement_restores_previous_components(tmp_path, monkeypatch):
    output_dir = str(tmp_path / "data")
    path = storage.write_vector(
        _polygon("old"), out_format="shp", name="roads", dirpath=output_dir,
    )
    original_files = {
        name: (tmp_path / "data" / name).read_bytes()
        for name in os.listdir(output_dir)
        if name.startswith("roads.")
    }
    assert {"roads.shp", "roads.dbf", "roads.shx"}.issubset(original_files)

    real_replace = storage.os.replace
    staged_replacements = 0

    def fail_during_staged_install(source, destination):
        nonlocal staged_replacements
        if os.path.basename(os.path.dirname(source)).startswith(".vector-write-"):
            staged_replacements += 1
            if staged_replacements == 3:
                raise OSError("simulated component replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_during_staged_install)
    with pytest.raises(DownloadError, match="(?i)shapefile"):
        storage.write_vector(
            _polygon("new"), out_format="shp", name="roads", dirpath=output_dir,
        )

    current_files = {
        name: (tmp_path / "data" / name).read_bytes()
        for name in os.listdir(output_dir)
        if name.startswith("roads.")
    }
    assert current_files == original_files


def test_incomplete_catalog_backup_does_not_replace_original_on_abort(tmp_path, monkeypatch):
    data_file = tmp_path / "roads.geojson"
    metadata_file = tmp_path / "roads.metadata.json"
    catalog_file = tmp_path / "catalog.json"
    data_file.write_text('{"version": "old"}', encoding="utf-8")
    metadata_file.write_text('{"version": "old"}', encoding="utf-8")
    catalog_file.write_text('[{"version": "old"}]', encoding="utf-8")
    original_contents = {
        path.name: path.read_bytes() for path in (data_file, metadata_file, catalog_file)
    }

    def fail_after_partial_catalog_copy(_source, destination):
        with open(destination, "wb") as backup:
            backup.write(b"partial")
        raise OSError("simulated catalog backup failure")

    monkeypatch.setattr(storage.shutil, "copy2", fail_after_partial_catalog_copy)
    with pytest.raises(OSError, match="catalog backup failure"):
        with storage.vector_import_transaction(
            out_format="geojson", name="roads", dirpath=str(tmp_path),
        ):
            pytest.fail("the transaction must not start when catalog backup fails")

    assert {
        path.name: path.read_bytes() for path in (data_file, metadata_file, catalog_file)
    } == original_contents
    assert not list(tmp_path.glob(".vector-import-*"))
