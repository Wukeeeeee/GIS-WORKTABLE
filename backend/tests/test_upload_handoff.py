"""Upload handoff checks use real CSV/GeoTIFF files and controlled oversized reads."""
import asyncio
import json
import os
import threading
from io import BytesIO

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_bounds

from backend import main
from backend.services import cloud_native, tools


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, '_TEMP_OUTPUT_DIR', str(tmp_path))
    monkeypatch.setattr(tools, '_temp_output_dir', str(tmp_path))
    monkeypatch.setattr(tools, '_registered_layers', {})
    monkeypatch.setattr(tools, '_pending_layer_ops', [])
    with main._upload_request_lock:
        main._upload_request_active.clear()
        main._upload_request_phases.clear()
        main._upload_request_cache.clear()
        main._upload_request_cancel_events.clear()
        main._upload_request_files.clear()
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


def test_concurrent_same_stem_vector_formats_do_not_replace_each_other(client, monkeypatch):
    import geopandas as gpd
    import pyogrio
    from types import SimpleNamespace
    from starlette.datastructures import UploadFile

    class FakeFrame:
        empty = False
        crs = SimpleNamespace(to_string=lambda: 'EPSG:4326')

        def __init__(self, source_id):
            self.__geo_interface__ = {
                'type': 'FeatureCollection',
                'features': [{'type': 'Feature', 'geometry': {
                    'type': 'Point', 'coordinates': [0, 0],
                }, 'properties': {'source_id': source_id}}],
            }

        def to_crs(self, _crs):
            return self

    monkeypatch.setattr(pyogrio, 'list_layers', lambda _path: [('layer', 'Point')])
    monkeypatch.setattr(
        gpd, 'read_file', lambda path, **_kwargs: FakeFrame(os.path.splitext(path)[1]),
    )

    original_register = main._register_uploaded_vector_async
    both_at_registration = asyncio.Event()
    arrivals = 0

    async def synchronize_before_registration(name, geojson, provenance=None):
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            both_at_registration.set()
        await asyncio.wait_for(both_at_registration.wait(), timeout=5)
        return await original_register(name, geojson, provenance)

    monkeypatch.setattr(main, '_register_uploaded_vector_async', synchronize_before_registration)

    async def upload_both():
        return await asyncio.gather(
            main._process_uploaded_file(UploadFile(file=BytesIO(b'gpkg'), filename='shared.gpkg')),
            main._process_uploaded_file(UploadFile(file=BytesIO(b'kml'), filename='shared.kml')),
        )

    results = asyncio.run(upload_both())
    assert all('geojson' in result for result in results), results
    layer_names = [result['name'] for result in results]
    assert len(set(layer_names)) == 2
    assert all(name in tools._registered_layers for name in layer_names)
    source_ids = {
        tools._registered_layers[name]['geojson']['features'][0]['properties']['source_id']
        for name in layer_names
    }
    assert source_ids == {'.gpkg', '.kml'}


def test_csv_upload_counts_rows_in_chunks_and_keeps_first_preview(client, monkeypatch):
    import pandas as pd

    original_read_csv = pd.read_csv
    chunk_sizes = []

    def track_chunk_size(*args, **kwargs):
        chunk_sizes.append(kwargs.get('chunksize'))
        return original_read_csv(*args, **kwargs)

    monkeypatch.setattr(pd, 'read_csv', track_chunk_size)
    rows = 10_005
    payload = 'id,value\n' + ''.join(f'{index},{index * 2}\n' for index in range(rows))
    response = client.post(
        '/api/upload', files={'file': ('many-rows.csv', payload.encode(), 'text/csv')},
    )

    assert response.status_code == 200
    info = response.json()['csv_info']
    assert info['rows'] == rows
    assert info['preview'] == [
        {'id': 0, 'value': 0}, {'id': 1, 'value': 2}, {'id': 2, 'value': 4},
    ]
    assert chunk_sizes == [10_000]


def test_csv_preview_applies_late_mixed_type_inference_across_chunks(client):
    payload = 'id,value\n' + ''.join(f'{index},{index * 2}\n' for index in range(10_000))
    payload += '10000,not-a-number\n'

    response = client.post(
        '/api/upload', files={'file': ('mixed.csv', payload.encode(), 'text/csv')},
    )

    assert response.status_code == 200
    info = response.json()['csv_info']
    assert info['rows'] == 10_001
    assert info['preview'] == [
        {'id': 0, 'value': '0'}, {'id': 1, 'value': '2'}, {'id': 2, 'value': '4'},
    ]


def test_header_only_csv_preserves_columns_without_data_rows(client):
    response = client.post(
        '/api/upload', files={'file': ('schema-only.csv', b'longitude,latitude\n', 'text/csv')},
    )

    assert response.status_code == 200
    assert response.json()['csv_info'] == {
        'filename': 'schema-only.csv',
        'rows': 0,
        'columns': ['longitude', 'latitude'],
        'preview': [],
        'path': response.json()['csv_info']['path'],
    }


def test_csv_upload_counts_an_explicit_record_with_only_empty_fields(client):
    response = client.post(
        '/api/upload', files={'file': ('empty-record.csv', b'lon,lat\n,\n1,2\n', 'text/csv')},
    )

    assert response.status_code == 200
    info = response.json()['csv_info']
    assert info['rows'] == 2
    assert info['preview'] == [{'lon': None, 'lat': None}, {'lon': 1, 'lat': 2}]


def test_invalid_csv_does_not_leave_a_failed_upload(client, tmp_path):
    response = client.post('/api/upload', files={'file': ('invalid.csv', b'\xff', 'text/csv')})
    assert 'error' in response.json()
    assert not (tmp_path / 'uploads' / 'invalid.csv').exists()


def test_empty_upload_is_rejected_and_removed(client, tmp_path):
    response = client.post('/api/upload', files={'file': ('empty.geojson', b'', 'application/geo+json')})
    assert response.json() == {'error': '上传文件为空，请选择包含数据的文件'}
    assert not (tmp_path / 'uploads' / 'empty.geojson').exists()


def test_upload_status_reports_the_current_processing_phase():
    request_id = 'phase-inspection-123'
    with main._upload_request_lock:
        main._upload_request_active.add(request_id)
        main._upload_request_phases[request_id] = 'parsing'
    try:
        assert asyncio.run(main.upload_status(request_id)) == {'status': 'processing', 'phase': 'parsing'}
    finally:
        with main._upload_request_lock:
            main._upload_request_active.discard(request_id)
            main._upload_request_phases.pop(request_id, None)


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


def test_cancelling_active_upload_rolls_back_registered_layer_and_files(client, tmp_path, monkeypatch):
    from starlette.datastructures import UploadFile as StarletteUploadFile

    entered = threading.Event()
    release = threading.Event()
    geojson = {'type': 'FeatureCollection', 'features': []}
    saved_path = tmp_path / 'uploads' / 'cancelled.geojson'
    saved_path.parent.mkdir(parents=True, exist_ok=True)

    async def delayed_upload(_file, request_id=None):
        saved_path.write_text('{}', encoding='utf-8')
        main._track_upload_request_file(request_id, str(saved_path))
        token = tools._register_layer('cancelled.geojson', geojson)
        entered.set()
        await asyncio.to_thread(release.wait, 3)
        return {'name': 'cancelled.geojson', 'geojson': geojson, 'registration_token': token}

    monkeypatch.setattr(main, '_process_uploaded_file', delayed_upload)
    request_id = 'cancel-active-upload-123'

    async def run_cancel():
        upload_task = asyncio.create_task(main.upload(
            StarletteUploadFile(file=BytesIO(b'{}'), filename='cancelled.geojson'), request_id,
        ))
        assert await asyncio.to_thread(entered.wait, 3)
        cancel_result = await main.cancel_upload(request_id)
        release.set()
        upload_result = await upload_task
        return cancel_result, upload_result

    try:
        cancel_result, upload_result = asyncio.run(run_cancel())
    finally:
        release.set()

    assert cancel_result == {'status': 'cancelling'}
    assert upload_result == {'error': '上传已取消'}
    assert 'cancelled.geojson' not in tools._registered_layers
    assert not saved_path.exists()
    assert asyncio.run(main.upload_status(request_id)) == {'status': 'cancelled'}


def test_cancelling_upload_that_fails_during_processing_keeps_cancel_receipt(client, tmp_path, monkeypatch):
    from starlette.datastructures import UploadFile as StarletteUploadFile

    entered = threading.Event()
    release = threading.Event()
    request_id = 'cancel-upload-processing-error-123'
    partial_path = tmp_path / 'uploads' / 'cancel-processing-error.geojson'
    partial_path.parent.mkdir(parents=True, exist_ok=True)

    async def failing_upload(_file, request_id=None):
        partial_path.write_text('{', encoding='utf-8')
        main._track_upload_request_file(request_id, str(partial_path))
        entered.set()
        await asyncio.to_thread(release.wait, 3)
        raise ValueError('simulated parser failure after cancel')

    monkeypatch.setattr(main, '_process_uploaded_file', failing_upload)

    async def run_cancel():
        upload_task = asyncio.create_task(main.upload(
            StarletteUploadFile(file=BytesIO(b'bad'), filename='broken.geojson'), request_id,
        ))
        assert await asyncio.to_thread(entered.wait, 3)
        cancel_result = await main.cancel_upload(request_id)
        release.set()
        with pytest.raises(ValueError, match='simulated parser failure'):
            await upload_task
        return cancel_result

    try:
        cancel_result = asyncio.run(run_cancel())
    finally:
        release.set()

    assert cancel_result == {'status': 'cancelling'}
    assert asyncio.run(main.upload_status(request_id)) == {'status': 'cancelled'}
    assert not partial_path.exists()


def test_task_cancellation_during_vector_registration_does_not_leave_orphan_layer(client, tmp_path, monkeypatch):
    from starlette.datastructures import UploadFile as StarletteUploadFile

    entered = threading.Event()
    release = threading.Event()
    original_register = main._register_uploaded_vector

    def delayed_register(name, geojson, provenance=None):
        token = original_register(name, geojson, provenance)
        entered.set()
        release.wait(3)
        return token

    monkeypatch.setattr(main, '_register_uploaded_vector', delayed_register)
    payload = json.dumps({
        'type': 'Feature', 'properties': {'value': 1},
        'geometry': {'type': 'Point', 'coordinates': [-122.3, 47.6]},
    }).encode()
    request_id = 'cancel-during-registration-123'

    async def run_cancel():
        upload_task = asyncio.create_task(main.upload(
            StarletteUploadFile(file=BytesIO(payload), filename='orphan.geojson'), request_id,
        ))
        assert await asyncio.to_thread(entered.wait, 3)
        upload_task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await upload_task

    try:
        asyncio.run(run_cancel())
    finally:
        release.set()

    assert 'orphan.geojson' not in tools._registered_layers
    assert not (tmp_path / 'uploads' / 'orphan.geojson').exists()


def test_task_cancellation_during_raster_registration_does_not_leave_orphan_layer(client, tmp_path, monkeypatch):
    from starlette.datastructures import UploadFile as StarletteUploadFile

    entered = threading.Event()
    release = threading.Event()
    original_register = tools._register_raster_layer

    def delayed_register(name, raster, source_path=None):
        token = original_register(name, raster, source_path)
        entered.set()
        release.wait(3)
        return token

    monkeypatch.setattr(tools, '_register_raster_layer', delayed_register)
    data = BytesIO()
    with rasterio.open(data, 'w', driver='GTiff', width=4, height=4, count=1,
                       dtype='uint8', crs='EPSG:4326', transform=from_bounds(10, 20, 11, 21, 4, 4)) as dataset:
        dataset.write(np.arange(1, 17, dtype=np.uint8).reshape(4, 4), 1)
    request_id = 'cancel-raster-registration-123'

    async def run_cancel():
        upload_task = asyncio.create_task(main.upload(
            StarletteUploadFile(file=BytesIO(data.getvalue()), filename='orphan-raster.tif'), request_id,
        ))
        assert await asyncio.to_thread(entered.wait, 5)
        upload_task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await upload_task

    try:
        asyncio.run(run_cancel())
    finally:
        release.set()

    assert 'orphan-raster' not in tools._registered_layers
    assert not (tmp_path / 'uploads' / 'orphan-raster.tif').exists()
    assert not (tmp_path / 'uploads' / 'orphan-raster.png').exists()


def test_cancel_before_upload_route_starts_blocks_processing(client, monkeypatch):
    from starlette.datastructures import UploadFile as StarletteUploadFile

    async def unexpected_upload(_file, request_id=None):
        raise AssertionError('a cancelled request must not be processed')

    monkeypatch.setattr(main, '_process_uploaded_file', unexpected_upload)
    request_id = 'cancel-before-upload-123'
    assert asyncio.run(main.cancel_upload(request_id)) == {'status': 'cancelled'}

    result = asyncio.run(main.upload(
        StarletteUploadFile(file=BytesIO(b'{}'), filename='cancelled.geojson'), request_id,
    ))

    assert result == {'error': '上传已取消'}
    assert asyncio.run(main.upload_status(request_id)) == {'status': 'cancelled'}


def test_cancel_after_server_completion_removes_result_before_client_handoff(client, tmp_path):
    content = json.dumps({'type': 'Feature', 'properties': {'value': 1},
                          'geometry': {'type': 'Point', 'coordinates': [-122.3, 47.6]}})
    request_id = 'cancel-after-upload-123'
    response = client.post(
        f'/api/upload?request_id={request_id}',
        files={'file': ('cancel-late.geojson', content, 'application/geo+json')},
    )
    assert response.status_code == 200
    result = response.json()
    assert result['name'] in tools._registered_layers

    cancelled = client.post(f'/api/upload/cancel/{request_id}')

    assert cancelled.status_code == 200
    assert cancelled.json() == {'status': 'cancelled'}
    assert result['name'] not in tools._registered_layers
    assert not (tmp_path / 'uploads' / 'cancel-late.geojson').exists()
    assert client.get(f'/api/upload/status/{request_id}').json() == {'status': 'cancelled'}


def test_evicted_upload_receipt_is_unknown_while_original_layer_remains(client, monkeypatch):
    monkeypatch.setattr(main, '_UPLOAD_REQUEST_CACHE_LIMIT', 1)
    content = json.dumps({'type': 'Feature', 'properties': {'value': 1},
                          'geometry': {'type': 'Point', 'coordinates': [-122.3, 47.6]}})
    request_id = 'evicted-receipt-123'
    first = client.post(
        f'/api/upload?request_id={request_id}',
        files={'file': ('points.geojson', content, 'application/geo+json')},
    )
    assert first.status_code == 200
    original_token = first.json()['registration_token']

    # A bounded receipt cache can evict a recent successful upload before its TTL.
    main._remember_upload_request('newer-receipt-456', {'csv_info': {'filename': 'other.csv'}})
    status = client.get(f'/api/upload/status/{request_id}')

    assert status.json() == {'status': 'unknown'}
    assert tools._registered_layers['points.geojson']['registration_token'] == original_token


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


def test_lost_raster_pmtiles_upload_response_does_not_create_duplicate_tiles(client, tmp_path, monkeypatch):
    def reject_vector(source):
        raise cloud_native.CloudNativeError('raster tile archive')

    monkeypatch.setattr(cloud_native, 'pmtiles_vector_to_geojson', reject_vector)
    monkeypatch.setattr(cloud_native, 'pmtiles_raster_tile_bounds',
                        lambda source: (b'png tile', [0, 0, 1, 1], 'png', {'tile_type': 'png'}))
    request_id = 'recover-raster-pmtiles-123'
    first = client.post(f'/api/upload?request_id={request_id}',
                        files={'file': ('basemap.pmtiles', b'pmtiles bytes', 'application/octet-stream')})
    assert first.status_code == 200
    original = first.json()

    status = client.get(f'/api/upload/status/{request_id}')
    assert status.json()['status'] == 'completed'
    retry = client.post(f'/api/upload?request_id={request_id}',
                        files={'file': ('basemap.pmtiles', b'different retry payload', 'application/octet-stream')})
    assert retry.status_code == 200
    assert retry.json() == original
    assert {path.name for path in (tmp_path / 'uploads').iterdir()} == {'basemap.pmtiles', 'pmtiles_basemap.png'}


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


def test_geotiff_rgba_upload_preserves_alpha_in_map_preview(client, tmp_path):
    from PIL import Image
    from rasterio.enums import ColorInterp

    data = BytesIO()
    with rasterio.open(data, 'w', driver='GTiff', width=2, height=1, count=4,
                       dtype='uint8', crs='EPSG:4326',
                       transform=from_bounds(10, 20, 12, 21, 2, 1)) as dataset:
        dataset.write(np.array([
            [[255, 255]], [[0, 0]], [[0, 0]], [[128, 0]],
        ], dtype=np.uint8))
        dataset.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)

    result = client.post(
        '/api/upload', files={'file': ('rgba.tif', data.getvalue(), 'image/tiff')},
    ).json()
    assert result['raster_info']['bands'] == 4
    preview = Image.open(tmp_path / 'uploads' / 'rgba.png').convert('RGBA')
    assert preview.getpixel((0, 0))[3] == pytest.approx(128, abs=2)
    assert preview.getpixel((1, 0))[3] == 0


@pytest.mark.parametrize(('extension', 'driver'), [
    ('parquet', 'GeoParquet'), ('fgb', 'FlatGeobuf'),
])
def test_cloud_vector_upload_registers_layer_and_keeps_source(client, tmp_path, extension, driver):
    import geopandas as gpd
    from shapely.geometry import Point

    source = tmp_path / f'cloud-points.{extension}'
    frame = gpd.GeoDataFrame(
        {'name': ['first', 'second']},
        geometry=[Point(116.0, 39.0), Point(116.1, 39.1)], crs='EPSG:4326',
    )
    if extension == 'parquet':
        frame.to_parquet(source)
    else:
        frame.to_file(source, driver='FlatGeobuf')
    payload = source.read_bytes()

    response = client.post(
        '/api/upload', files={'file': (source.name, payload, 'application/octet-stream')},
    )

    assert response.status_code == 200
    result = response.json()
    assert result['name'] == source.stem
    assert result['registration_token']
    assert sorted(feature['properties']['name'] for feature in result['geojson']['features']) == [
        'first', 'second',
    ]
    assert result['provenance']['file_format'] == driver
    assert result['name'] in tools._registered_layers
    assert (tmp_path / 'uploads' / source.name).read_bytes() == payload


@pytest.mark.parametrize('extension', ['parquet', 'fgb'])
def test_invalid_cloud_vector_upload_removes_source_and_does_not_register(client, tmp_path, extension):
    filename = f'broken.{extension}'
    response = client.post(
        '/api/upload', files={'file': (filename, b'not a cloud vector file', 'application/octet-stream')},
    )

    assert response.status_code == 200
    assert 'error' in response.json()
    assert not (tmp_path / 'uploads' / filename).exists()
    assert not tools._registered_layers


def test_corrupt_parquet_page_upload_removes_source_and_does_not_register(client, tmp_path):
    import geopandas as gpd
    import pyarrow.parquet as pq
    from shapely.geometry import Point

    source = tmp_path / 'bad-page.parquet'
    gpd.GeoDataFrame(
        {'name': ['first', 'second']},
        geometry=[Point(116.0, 39.0), Point(116.1, 39.1)], crs='EPSG:4326',
    ).to_parquet(source)
    with pq.ParquetFile(source) as parquet:
        page_offset = parquet.metadata.row_group(0).column(0).data_page_offset
    corrupted = bytearray(source.read_bytes())
    corrupted[page_offset:page_offset + 4] = b'\xff\xff\xff\xff'

    response = client.post(
        '/api/upload', files={'file': ('bad-page.parquet', bytes(corrupted), 'application/octet-stream')},
    )

    assert response.status_code == 200 and 'error' in response.json()
    assert not (tmp_path / 'uploads' / 'bad-page.parquet').exists()
    assert not tools._registered_layers


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


def test_geojson_file_read_does_not_run_on_the_async_request_loop(tmp_path, monkeypatch):
    import builtins

    monkeypatch.setattr(main, '_TEMP_OUTPUT_DIR', str(tmp_path))
    monkeypatch.setattr(tools, '_temp_output_dir', str(tmp_path))
    monkeypatch.setattr(tools, '_registered_layers', {})
    monkeypatch.setattr(tools, '_pending_layer_ops', [])
    monkeypatch.setattr(main, '_register_uploaded_vector', lambda *_args, **_kwargs: 'test-token')
    target = os.path.normcase(os.path.abspath(tmp_path / 'uploads' / 'thread.geojson'))
    original_open = builtins.open

    def checked_open(path, mode='r', *args, **kwargs):
        if os.path.normcase(os.path.abspath(path)) == target and mode == 'rb':
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise AssertionError('GeoJSON file reads must not block the async request loop')
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', checked_open)

    class Upload:
        filename = 'thread.geojson'
        content = json.dumps({
            'type': 'FeatureCollection', 'features': [],
        }).encode('utf-8')

        async def read(self, size):
            result, self.content = self.content, b''
            return result

    assert asyncio.run(main.upload(Upload()))['registration_token'] == 'test-token'
