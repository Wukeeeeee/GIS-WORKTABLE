"""Upload handoff checks use real CSV/GeoTIFF files and controlled oversized reads."""
import asyncio
import json
import os
from io import BytesIO

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_bounds

from backend import main
from backend.services import tools


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, '_TEMP_OUTPUT_DIR', str(tmp_path))
    monkeypatch.setattr(tools, '_temp_output_dir', str(tmp_path))
    monkeypatch.setattr(tools, '_registered_layers', {})
    monkeypatch.setattr(tools, '_pending_layer_ops', [])
    with main._upload_request_lock:
        main._upload_request_active.clear()
        main._upload_request_cache.clear()
    return TestClient(main.app)


def test_csv_null_preview_and_same_name_inputs_are_preserved(client, tmp_path):
    first_bytes = b'lon,lat,note\n116.1,39.9,\n,40.0,x\n'
    one = client.post('/api/upload', files={'file': ('points.csv', first_bytes, 'text/csv')})
    two = client.post('/api/upload', files={'file': ('points.csv', b'lon,lat\n1,2', 'text/csv')})
    assert one.status_code == two.status_code == 200
    assert one.json()['csv_info']['preview'][0]['note'] is None
    assert one.json()['csv_info']['preview'][1]['lon'] is None
    assert one.json()['csv_info']['filename'] != two.json()['csv_info']['filename']
    assert (tmp_path / 'uploads' / 'points.csv').read_bytes() == first_bytes


def test_invalid_csv_does_not_leave_a_failed_upload(client, tmp_path):
    response = client.post('/api/upload', files={'file': ('invalid.csv', b'\xff', 'text/csv')})
    assert 'error' in response.json()
    assert not (tmp_path / 'uploads' / 'invalid.csv').exists()


def test_lost_vector_upload_response_can_be_recovered_without_duplicate_file_or_layer(client, tmp_path):
    content = json.dumps({'type': 'Feature', 'properties': {'value': 1},
                          'geometry': {'type': 'Point', 'coordinates': [-122.3, 47.6]}})
    request_id = 'recover-vector-123'
    first = client.post(f'/api/upload?request_id={request_id}', files={'file': ('points.geojson', content, 'application/geo+json')})
    assert first.status_code == 200
    original = first.json()

    retry = client.post(f'/api/upload?request_id={request_id}', files={'file': ('points.geojson', b'{"type":"FeatureCollection","features":[]}', 'application/geo+json')})
    assert retry.status_code == 200
    recovered = retry.json()
    assert recovered['name'] == original['name']
    assert recovered['registration_token'] == original['registration_token']
    assert recovered['geojson']['type'] == 'FeatureCollection'
    assert recovered['geojson']['features'][0]['geometry']['coordinates'] == [-122.3, 47.6]
    assert list((tmp_path / 'uploads').iterdir()) == [tmp_path / 'uploads' / 'points.geojson']
    assert list(tools._registered_layers) == ['points.geojson']

    status = client.get(f'/api/upload/status/{request_id}')
    assert status.json()['status'] == 'completed'
    assert status.json()['result']['registration_token'] == original['registration_token']
    assert client.get('/api/upload/status/unknown-request').json() == {'status': 'unknown'}


def test_lost_raster_upload_response_can_be_recovered_without_duplicate_assets(client, tmp_path):
    data = BytesIO()
    with rasterio.open(data, 'w', driver='GTiff', width=4, height=4, count=1,
                       dtype='uint8', crs='EPSG:4326', transform=from_bounds(10, 20, 11, 21, 4, 4)) as dataset:
        dataset.write(np.arange(1, 17, dtype=np.uint8).reshape(4, 4), 1)
    request_id = 'recover-raster-123'
    first = client.post(f'/api/upload?request_id={request_id}', files={'file': ('elevation.tif', data.getvalue(), 'image/tiff')})
    assert first.status_code == 200
    original = first.json()

    retry = client.post(f'/api/upload?request_id={request_id}', files={'file': ('elevation.tif', data.getvalue(), 'image/tiff')})
    assert retry.status_code == 200
    assert retry.json() == original
    assert list(tools._registered_layers) == ['elevation']
    assert {path.name for path in (tmp_path / 'uploads').iterdir()} == {'elevation.tif', 'elevation.png'}


def test_disk_full_during_upload_returns_actionable_error_and_removes_partial_file(client, tmp_path, monkeypatch):
    class DiskFullWriter:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.wrapped.close()

        def write(self, data):
            self.wrapped.write(data[:1])
            raise OSError(28, 'No space left on device')

    real_fdopen = os.fdopen
    monkeypatch.setattr(main.os, 'fdopen', lambda fd, mode: DiskFullWriter(real_fdopen(fd, mode)))

    response = client.post('/api/upload', files={'file': ('disk-full.csv', b'lon,lat\n1,2', 'text/csv')})

    assert response.status_code == 507
    assert '磁盘空间不足' in response.json()['detail']
    assert not (tmp_path / 'uploads' / 'disk-full.csv').exists()


def test_separate_archives_with_the_same_internal_shapefile_keep_distinct_layers(client, tmp_path):
    import zipfile
    import geopandas as gpd
    from shapely.geometry import Point
    source = tmp_path / 'data.shp'
    gpd.GeoDataFrame({'value': [1]}, geometry=[Point(10, 20)], crs='EPSG:4326').to_file(source)
    archive = BytesIO()
    with zipfile.ZipFile(archive, 'w') as zipped:
        for part in tmp_path.glob('data.*'):
            zipped.write(part, part.name)
    first = client.post('/api/upload', files={'file': ('first.zip', archive.getvalue(), 'application/zip')}).json()
    second = client.post('/api/upload', files={'file': ('second.zip', archive.getvalue(), 'application/zip')}).json()
    assert first['name'] != second['name']
    assert first['name'] in tools._registered_layers and second['name'] in tools._registered_layers


def test_geotiff_upload_keeps_source_and_can_feed_the_raster_calculator(client, tmp_path):
    data = BytesIO()
    with rasterio.open(data, 'w', driver='GTiff', width=4, height=4, count=1,
                       dtype='uint8', crs='EPSG:4326', transform=from_bounds(10, 20, 11, 21, 4, 4)) as dataset:
        dataset.write(np.arange(1, 17, dtype=np.uint8).reshape(4, 4), 1)
    response = client.post('/api/upload', files={'file': ('elevation#1.tif', data.getvalue(), 'image/tiff')})
    result = response.json()
    assert result['name'] == 'elevation#1'
    assert '%23' in result['raster_info']['url']
    source = tmp_path / 'uploads' / result['raster_info']['source_filename']
    assert source.read_bytes() == data.getvalue()
    calculated = tools.raster_calculator.invoke({'layer_name': result['name'], 'expression': 'B1*2'})
    assert '已执行' in calculated
    assert (tmp_path / 'uploads' / 'elevation#1_calc.png').exists()


def test_declared_projected_geojson_is_reprojected_before_registration(client):
    value = {'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:3857'}},
             'features': [{'type': 'Feature', 'properties': {},
                           'geometry': {'type': 'Point', 'coordinates': [1113194.9079327357, 0]}}]}
    response = client.post('/api/upload', files={'file': ('projected.geojson', json.dumps(value), 'application/json')})
    result = response.json()
    assert result['geojson']['features'][0]['geometry']['coordinates'][0] == pytest.approx(10)
    assert result['registration_token']
    assert result['provenance']['crs'] == 'EPSG:3857'
    assert result['provenance']['crs_known'] is True
    assert result['provenance']['provider'] == 'local_upload'
    assert not any(key in result['provenance'] for key in ('path', 'source_url', 'file_path'))
    assert tools._registered_layers['projected.geojson']['provenance'] == result['provenance']


def test_undeclared_projected_coordinates_are_not_silently_treated_as_degrees(client, tmp_path):
    value = {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Point', 'coordinates': [1000000, 2000000]}}
    result = client.post('/api/upload', files={'file': ('unknown.geojson', json.dumps(value), 'application/json')}).json()
    assert 'CRS' in result['error']
    assert not (tmp_path / 'uploads' / 'unknown.geojson').exists()


@pytest.mark.parametrize('filename', ['C:escaped.csv', 'NUL.csv', 'bad?.csv', 'x' * 241 + '.csv'])
def test_nonportable_file_names_are_rejected_before_any_file_read(tmp_path, monkeypatch, filename):
    monkeypatch.setattr(main, '_TEMP_OUTPUT_DIR', str(tmp_path))
    class Upload:
        def __init__(self): self.filename = filename
        async def read(self, size): raise AssertionError('must reject before reading')
    assert 'error' in asyncio.run(main.upload(Upload()))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('filename', ['large.csv', 'large.tif'])
def test_server_limits_remove_reserved_source_and_preview_files(tmp_path, monkeypatch, filename):
    monkeypatch.setattr(main, '_TEMP_OUTPUT_DIR', str(tmp_path))
    class Chunk(bytes):
        def __len__(self): return 301 * 1024 * 1024
    class Upload:
        def __init__(self): self.filename = filename
        async def read(self, size): return Chunk(b'x')
    result = asyncio.run(main.upload(Upload()))
    assert '限制' in result['error']
    assert list((tmp_path / 'uploads').iterdir()) == []


def test_zip_expansion_limit_is_checked_before_extraction(client, tmp_path, monkeypatch):
    import zipfile
    class Archive:
        def __init__(self, path): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def close(self): pass
        def namelist(self): return ['huge.shp']
        def infolist(self):
            info = zipfile.ZipInfo('huge.shp'); info.file_size = 513 * 1024 * 1024
            return [info]
        def extractall(self, path): raise AssertionError('must reject before extracting')
    monkeypatch.setattr(zipfile, 'ZipFile', Archive)
    result = client.post('/api/upload', files={'file': ('large.zip', b'x', 'application/zip')}).json()
    assert '解压内容超过' in result['error']
    assert list((tmp_path / 'uploads').iterdir()) == []


def test_csv_parsing_does_not_run_on_the_async_request_loop(tmp_path, monkeypatch):
    import pandas as pd
    monkeypatch.setattr(main, '_TEMP_OUTPUT_DIR', str(tmp_path))
    read_csv = pd.read_csv
    def checked_read(*args, **kwargs):
        with pytest.raises(RuntimeError, match='no running event loop'):
            asyncio.get_running_loop()
        return read_csv(*args, **kwargs)
    monkeypatch.setattr(pd, 'read_csv', checked_read)
    class Upload:
        filename = 'thread.csv'
        content = b'x,y\n1,2'
        async def read(self, size):
            result, self.content = self.content, b''
            return result
    assert asyncio.run(main.upload(Upload()))['csv_info']['rows'] == 1
