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



def test_shapefile_export_rejects_large_integer_mixed_with_null_or_float(tmp_path):
    import zipfile
    import geopandas as gpd

    # Large integer (> 2^53 - 1) mixed with None coercing to float64
    data_unsafe_null = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"identifier": 9007199254740993}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"identifier": None}},
        ],
    }
    result_null, error_null = _export_shp_sync(data_unsafe_null, "EPSG:4326", "unsafe_large_int_null")
    assert result_null is None
    assert "53 位精度限制" in error_null

    # Large integer (> 2^53 - 1) mixed with float coercing to float64
    data_unsafe_float = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"identifier": 9007199254740993}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"identifier": 1.5}},
        ],
    }
    result_float, error_float = _export_shp_sync(data_unsafe_float, "EPSG:4326", "unsafe_large_int_float")
    assert result_float is None
    assert "53 位精度限制" in error_float

    # Negative large integer (< -(2^53 - 1)) mixed with None
    data_unsafe_neg = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"identifier": -9007199254740993}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"identifier": None}},
        ],
    }
    result_neg, error_neg = _export_shp_sync(data_unsafe_neg, "EPSG:4326", "unsafe_large_int_neg")
    assert result_neg is None
    assert "53 位精度限制" in error_neg

    # Pure large integers without null or float must succeed and retain precision
    data_safe = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"identifier": 9007199254740993}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"identifier": 100}},
        ],
    }
    result_safe, error_safe = _export_shp_sync(data_safe, "EPSG:4326", "safe_large_int")
    assert error_safe is None
    extract_dir = tmp_path / "safe_int"
    extract_dir.mkdir()
    with zipfile.ZipFile(result_safe) as zf:
        zf.extractall(extract_dir)
    read_back = gpd.read_file(extract_dir / "safe_large_int.shp")
    assert int(read_back["identifier"].iloc[0]) == 9007199254740993
    assert int(read_back["identifier"].iloc[1]) == 100


def test_shapefile_export_rejects_string_exceeding_dbf_byte_limit(tmp_path):
    import zipfile
    import geopandas as gpd

    # 255-byte ASCII string exceeds 254 bytes
    data_ascii_over = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"desc": "x" * 255},
        }],
    }
    result, error = _export_shp_sync(data_ascii_over, "EPSG:4326", "ascii_over")
    assert result is None
    assert "254 字节" in error

    # 85-char Chinese string (255 UTF-8 bytes) exceeds 254 bytes
    data_utf8_over = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"name": "测" * 85},
        }],
    }
    result_cn, error_cn = _export_shp_sync(data_utf8_over, "EPSG:4326", "utf8_over")
    assert result_cn is None
    assert "254 字节" in error_cn

    # Exactly 254-byte ASCII string fits within DBF field limit
    data_exact = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"desc": "x" * 254},
        }],
    }
    result_exact, error_exact = _export_shp_sync(data_exact, "EPSG:4326", "exact_fit")
    assert error_exact is None
    extract_dir = tmp_path / "exact_fit"
    extract_dir.mkdir()
    with zipfile.ZipFile(result_exact) as zf:
        zf.extractall(extract_dir)
    read_back = gpd.read_file(extract_dir / "exact_fit.shp")
    assert len(read_back["desc"].iloc[0]) == 254


def test_shapefile_export_serializes_nested_dict_and_list_to_json(tmp_path):
    import json
    import zipfile
    import geopandas as gpd

    # Fitting nested structures serialize to compact JSON and roundtrip cleanly
    data_fitting = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {
                    "nested_dict": {"sensor": {"bands": [1, 2]}},
                    "nested_list": [1, 2, 3],
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1, 1]},
                "properties": {
                    "nested_dict": None,
                    "nested_list": None,
                },
            },
        ],
    }
    result, error = _export_shp_sync(data_fitting, "EPSG:4326", "nested_props")
    assert error is None
    extract_dir = tmp_path / "nested"
    extract_dir.mkdir()
    with zipfile.ZipFile(result) as zf:
        zf.extractall(extract_dir)
    read_back = gpd.read_file(extract_dir / "nested_props.shp")
    assert json.loads(read_back["nested_dic"].iloc[0]) == {"sensor": {"bands": [1, 2]}}
    assert json.loads(read_back["nested_lis"].iloc[0]) == [1, 2, 3]

    # Nested dict whose serialized JSON exceeds 254 bytes is rejected
    data_nested_over = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {
                "metadata": {"info": "long_description_" * 20},
            },
        }],
    }
    result_over, error_over = _export_shp_sync(data_nested_over, "EPSG:4326", "nested_over")
    assert result_over is None
    assert "254 字节" in error_over

    # Nested list whose serialized JSON exceeds 254 bytes is rejected
    data_list_over = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {
                "tags": ["tag_entry_" + str(i) for i in range(40)],
            },
        }],
    }
    result_list_over, error_list_over = _export_shp_sync(data_list_over, "EPSG:4326", "list_over")
    assert result_list_over is None
    assert "254 字节" in error_list_over


def test_shapefile_export_crs_prj_consistency():
    import zipfile

    data = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [116.0, 39.0]},
            "properties": {"name": "test"},
        }],
    }

    # EPSG:4326 / WGS84
    for crs_input in ("EPSG:4326", "WGS84"):
        res, err = _export_shp_sync(data, crs_input, "wgs_test")
        assert err is None
        with zipfile.ZipFile(res) as zf:
            assert "wgs_test.prj" in zf.namelist()
            prj_content = zf.read("wgs_test.prj").decode("utf-8", errors="ignore")
            assert "GCS_WGS_1984" in prj_content or "WGS 84" in prj_content

    # Default fallback when crs is empty string
    res_empty, err_empty = _export_shp_sync(data, "", "empty_crs_test")
    assert err_empty is None
    with zipfile.ZipFile(res_empty) as zf:
        assert "empty_crs_test.prj" in zf.namelist()
        prj_empty = zf.read("empty_crs_test.prj").decode("utf-8", errors="ignore")
        assert "GCS_WGS_1984" in prj_empty or "WGS 84" in prj_empty

    # Normalized from geojson crs properties (urn:ogc:def:crs:OGC:1.3:CRS84)
    data_crs84 = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [116.0, 39.0]},
            "properties": {"name": "test"},
        }],
    }
    res_crs84, err_crs84 = _export_shp_sync(data_crs84, None, "crs84_test")
    assert err_crs84 is None
    with zipfile.ZipFile(res_crs84) as zf:
        assert "crs84_test.prj" in zf.namelist()
        prj_crs84 = zf.read("crs84_test.prj").decode("utf-8", errors="ignore")
        assert "GCS_WGS_1984" in prj_crs84 or "WGS 84" in prj_crs84

    # EPSG:3857
    data_3857 = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12913265, 4721671]},
            "properties": {"name": "mercator"},
        }],
    }
    res_3857, err_3857 = _export_shp_sync(data_3857, "EPSG:3857", "mercator_test")
    assert err_3857 is None
    with zipfile.ZipFile(res_3857) as zf:
        assert "mercator_test.prj" in zf.namelist()
        prj_3857 = zf.read("mercator_test.prj").decode("utf-8", errors="ignore")
        assert "3857" in prj_3857 or "Mercator" in prj_3857
