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
