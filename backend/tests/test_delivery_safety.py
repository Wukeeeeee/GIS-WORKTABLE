"""Submission regressions: no unlocked startup or silent feature loss."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend import launcher
from backend.main import _export_shp_sync


def test_start_lock_timeout_never_spawns(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'probe', lambda port: None)
    ticks = iter([0, 16])
    monkeypatch.setattr(launcher.time, 'monotonic', lambda: next(ticks))
    spawn = Mock()
    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    with pytest.raises(RuntimeError, match='Startup lock is still held'):
        launcher.start_backend(8010)
    spawn.assert_not_called()


def test_mixed_geometry_export_rejects_feature_loss():
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / 'data/sample_delivery_test.geojson').read_text(encoding='utf-8'))
    result, error = _export_shp_sync(data, 'EPSG:4326', 'mixed')
    assert result is None
    assert '混合几何' in error


def test_shapefile_export_name_cannot_escape_temporary_directory():
    import zipfile

    data = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
        }],
    }
    result, error = _export_shp_sync(data, "EPSG:4326", "../../outside\\layer")
    assert error is None
    with zipfile.ZipFile(result) as archive:
        assert archive.testzip() is None
        assert archive.namelist()
        assert all("/" not in member and "\\" not in member for member in archive.namelist())
        assert all(member.startswith("_.._outside_layer.") for member in archive.namelist())


def test_shapefile_export_removes_temporary_directory_after_write_failure(tmp_path, monkeypatch):
    import geopandas as gpd
    import tempfile

    export_dir = tmp_path / "shp_export_test"
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_kwargs: (export_dir.mkdir(), str(export_dir))[1])
    monkeypatch.setattr(gpd.GeoDataFrame, "to_file", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write failed")))
    data = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
        }],
    }

    result, error = _export_shp_sync(data, "EPSG:4326", "roads")

    assert result is None
    assert "write failed" in error
    assert not export_dir.exists()
