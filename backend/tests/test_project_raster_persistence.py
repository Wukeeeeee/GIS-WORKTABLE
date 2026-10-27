import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.services import ai_service, project_service, tools


def _use_temp_projects(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    monkeypatch.setattr(project_service, "_PROJECT_DIR", str(root))
    monkeypatch.setattr(project_service, "_BLOB_DIR", str(root / "blobs"))
    monkeypatch.setattr(project_service, "_INDEX_PATH", str(root / "index.json"))
    project_service._blob_refcount.clear()
    uploads = tmp_path / "runtime" / "uploads"
    uploads.mkdir(parents=True)
    source = uploads / "source.png"
    source.write_bytes(b"png-raster-asset")
    monkeypatch.setattr(ai_service, "_TEMP_OUTPUT_DIR", str(uploads.parent))
    monkeypatch.setattr(main, "_TEMP_OUTPUT_DIR", str(uploads.parent))
    monkeypatch.setattr(tools, "_temp_output_dir", str(uploads.parent))
    monkeypatch.setattr(tools, "_active_project_id", None)
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    return source


def test_failed_replacement_keeps_existing_project_geojson_intact(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    original_geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"id": "original"},
        "geometry": {"type": "Point", "coordinates": [113.0, 28.0]},
    }]}
    project = project_service.save_project(
        project_id=None, name="已有工程", session_id="save-failure", provider="test",
        map_state={}, messages=[], layers=[{
            "name": "原图层", "geometry_type": "Point", "geojson": original_geojson,
        }],
    )
    original_blob = project_service._load_project_data(project["id"])["layers"][0]["blob"]

    with pytest.raises(ValueError, match="资源不存在"):
        project_service.save_project(
            project_id=project["id"], name="已有工程", session_id="save-failure", provider="test",
            map_state={}, messages=[], layers=[
                {"name": "新图层", "geometry_type": "Point", "geojson": {
                    "type": "FeatureCollection", "features": []}},
                {"name": "新栅格", "geometry_type": "Raster", "raster": {
                    "filename": source.name, "url": "/output/uploads/source.png",
                    "bounds": [100.0, 30.0, 101.0, 31.0]}},
                {"name": "缺失栅格", "geometry_type": "Raster", "raster": {
                    "filename": "missing.png", "url": "/output/uploads/missing.png"}},
            ],
        )

    restored = project_service.load_project(project["id"])
    assert restored["layers"][0]["geojson"] == original_geojson
    assert project_service._blob_get(original_blob) == original_geojson
    assert project_service._blob_refcount == {original_blob: 1}
    assets_dir = tmp_path / "projects" / project["id"] / "assets"
    assert not assets_dir.exists() or list(assets_dir.iterdir()) == []


def test_failed_atomic_project_write_keeps_old_file_and_releases_new_blob(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    original_geojson = {"type": "FeatureCollection", "features": []}
    project = project_service.save_project(
        project_id=None, name="已有工程", session_id="write-failure", provider="test",
        map_state={}, messages=[], layers=[{"name": "原图层", "geojson": original_geojson}],
    )
    original_blob = project_service._load_project_data(project["id"])["layers"][0]["blob"]
    real_replace = os.replace

    def fail_project_replace(source, destination):
        if destination == project_service._project_path(project["id"]):
            raise OSError("simulated project write failure")
        real_replace(source, destination)

    monkeypatch.setattr(project_service.os, "replace", fail_project_replace)
    with pytest.raises(OSError, match="simulated project write failure"):
        project_service.save_project(
            project_id=project["id"], name="已有工程", session_id="write-failure", provider="test",
            map_state={}, messages=[], layers=[
                {"name": "新图层", "geojson": {
                    "type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                        "geometry": {"type": "Point", "coordinates": [114.0, 29.0]}}]}},
                {"name": "新栅格", "geometry_type": "Raster", "raster": {
                    "filename": source.name, "url": "/output/uploads/source.png",
                    "bounds": [100.0, 30.0, 101.0, 31.0]}},
            ],
        )

    assert project_service.load_project(project["id"])["layers"][0]["geojson"] == original_geojson
    assert project_service._blob_refcount == {original_blob: 1}
    assert not any(name.endswith(".tmp") for name in os.listdir(project_service._project_dir(project["id"])))
    assets_dir = tmp_path / "projects" / project["id"] / "assets"
    assert not assets_dir.exists() or list(assets_dir.iterdir()) == []


def test_project_index_write_failure_reports_saved_project_and_list_recovers(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    monkeypatch.setattr(project_service, "_MAX_PROJECTS", 1)
    first = project_service.save_project(
        project_id=None, name="旧工程", session_id="old-project", provider="test",
        map_state={}, messages=[], layers=[],
    )

    def fail_index_write(_index):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(project_service, "_save_index", fail_index_write)
    saved = project_service.save_project(
        project_id=None, name="索引异常工程", session_id="index-write-failure", provider="test",
        map_state={}, messages=[], layers=[],
    )

    assert saved["id"]
    assert "warning" in saved
    assert project_service._load_project_data(first["id"]) is None
    assert project_service._load_project_data(saved["id"])["name"] == "索引异常工程"
    assert [project["id"] for project in project_service.list_projects()] == [saved["id"]]


def test_project_rename_survives_index_write_failure_and_list_recovers(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    saved = project_service.save_project(
        project_id=None, name="旧名称", session_id="rename-index-failure", provider="test",
        map_state={}, messages=[], layers=[],
    )

    def fail_index_write(_index):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(project_service, "_save_index", fail_index_write)
    renamed = project_service.rename_project(saved["id"], "新名称")

    assert renamed["name"] == "新名称"
    assert "warning" in renamed
    assert project_service._load_project_data(saved["id"])["name"] == "新名称"
    assert project_service.list_projects()[0]["name"] == "新名称"


def test_raster_assets_survive_project_save_export_import_and_restore(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    raster = {
        "filename": source.name,
        "url": "/output/uploads/source.png",
        "bounds": [100.0, 30.0, 101.0, 31.0],
        "width": 2,
        "height": 3,
    }
    with TestClient(main.app) as client:
        save_response = client.post("/api/projects", json={
            "name": "栅格工程", "session_id": "raster-session", "provider": "test",
            "map_state": {}, "messages": [],
            "layers": [{"layer_id": "raster-layer", "filename": "坡度", "geometry_type": "Raster",
                        "visible": False, "style": {"opacity": 0.4}, "raster": raster}],
        })
        assert save_response.status_code == 200
        saved = save_response.json()
        load_response = client.get(f"/api/projects/{saved['id']}")
        assert load_response.status_code == 200
        loaded = load_response.json()
    saved_raster = loaded["layers"][0]["raster"]
    assert saved_raster["url"].startswith(f"/api/projects/{saved['id']}/assets/")
    assert loaded["layers"][0]["visible"] is False
    assert loaded["layers"][0]["style"]["opacity"] == 0.4
    with TestClient(main.app) as client:
        response = client.get(saved_raster["url"])
    assert response.status_code == 200
    assert response.content == source.read_bytes()

    archive = zipfile.ZipFile(io.BytesIO(project_service.export_project(saved["id"])))
    assert any(name.startswith("assets/") for name in archive.namelist())
    imported = project_service.import_project(project_service.export_project(saved["id"]))
    imported_layer = project_service.load_project(imported["id"])["layers"][0]
    assert imported_layer["raster"]["url"].startswith(f"/api/projects/{imported['id']}/assets/")
    assert imported_layer["raster"]["bounds"] == raster["bounds"]
    with TestClient(main.app) as client:
        imported_asset = client.get(imported_layer["raster"]["url"])
    assert imported_asset.status_code == 200
    assert imported_asset.content == source.read_bytes()


def test_project_asset_responses_sandbox_active_content(tmp_path, monkeypatch):
    asset = tmp_path / "untrusted.svg"
    asset.write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", encoding="utf-8")
    monkeypatch.setattr(
        project_service,
        "get_project_raster_asset",
        lambda project_id, filename: str(asset) if (project_id, filename) == ("test", "untrusted.svg") else None,
    )

    response = TestClient(main.app).get("/api/projects/test/assets/untrusted.svg")

    assert response.status_code == 200
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "<script>" in response.text


def test_interpolation_raster_survives_project_save_load_and_reanalysis(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    point_layer = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"value": 1}, "geometry": {"type": "Point", "coordinates": [116.0, 39.0]}},
        {"type": "Feature", "properties": {"value": 3}, "geometry": {"type": "Point", "coordinates": [116.1, 39.0]}},
        {"type": "Feature", "properties": {"value": 4}, "geometry": {"type": "Point", "coordinates": [116.0, 39.1]}},
    ]}
    tools._register_layer("插值输入点", point_layer)

    interpolation_result = tools.spatial_interpolate.invoke({
        "layer_name": "插值输入点", "field": "value", "resolution": 16,
    })

    assert "已生成" in interpolation_result
    output_op = next(op for op in tools._pending_layer_ops if op.get("raster"))
    output_name = output_op["layer_name"]
    project = project_service.save_project(
        project_id=None, name="插值结果往返", session_id="interpolation-roundtrip", provider="test",
        map_state={}, messages=[], layers=[{
            "filename": output_name, "name": output_name, "geometry_type": "Raster",
            "raster": output_op["raster"], "visible": True,
        }],
    )
    restored = project_service.load_project(project["id"])
    restored_layer = restored["layers"][0]
    restored_raster = restored_layer["raster"]
    assert restored_raster["crs"] == "EPSG:4326"
    assert restored_raster["value_units"] is None
    assert any("外推" in warning for warning in restored_raster["quality_warnings"])
    assert restored_raster["source_url"].startswith(f"/api/projects/{project['id']}/assets/")

    tools.reset_registered_layers(restored["layers"])
    followup_result = tools.raster_resample.invoke({
        "layer_name": restored_layer["name"], "scale_factor": 2, "method": "bilinear",
    })

    assert "重采样完成" in followup_result
    followup_ops = [op for op in tools._pending_layer_ops if op.get("action") == "dem_result"]
    assert followup_ops and followup_ops[0].get("raster")
    with TestClient(main.app) as client:
        saved_preview = client.get(restored_raster["url"])
        saved_source = client.get(restored_raster["source_url"])
    assert saved_preview.status_code == 200
    assert saved_source.status_code == 200
    assert saved_source.headers.get("content-type", "").startswith("image/tiff")


def test_autosave_includes_uploaded_raster_layers(tmp_path, monkeypatch):
    source = _use_temp_projects(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_service, "conversation_history", {
        "auto-raster-session": [{"role": "user", "content": "保存栅格分析"}],
    })
    monkeypatch.setattr(tools, "_registered_layers", {})
    result = project_service.auto_save(
        session_id="auto-raster-session",
        provider="test",
        layer_assignments=[{
            "layer_id": "raster-auto",
            "name": "高程",
            "names": ["raster-auto", "高程"],
            "visible": True,
            "raster": {"filename": source.name, "url": "/output/uploads/source.png",
                       "bounds": [100.0, 30.0, 101.0, 31.0], "width": 2, "height": 3},
        }],
    )
    saved_layer = project_service.load_project(result["id"])["layers"][0]
    assert saved_layer["name"] == "高程"
    assert saved_layer["raster"]["asset"]


def _upload_real_raster(tmp_path, monkeypatch):
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    _use_temp_projects(tmp_path, monkeypatch)
    data = io.BytesIO()
    with rasterio.open(data, 'w', driver='GTiff', width=4, height=4, count=1, dtype='float32',
                       crs='EPSG:4326', transform=from_bounds(100, 30, 101, 31, 4, 4)) as dataset:
        dataset.write(np.arange(1, 17, dtype='float32').reshape(4, 4), 1)
    client = TestClient(main.app)
    result = client.post('/api/upload', files={'file': ('original#1.tif', data.getvalue(), 'image/tiff')}).json()
    assert result.get('registration_token'), result
    assert result['raster_info']['crs'] == 'EPSG:4326'
    assert result['raster_info']['source_width'] == 4
    assert result['raster_info']['pixel_units'] == 'degree'
    assert '单位未在文件元数据中标注' in result['raster_info']['quality_warnings'][0]
    saved = client.post('/api/projects', json={
        'name': '原始栅格工程', 'session_id': 'raw-session', 'provider': 'test', 'map_state': {}, 'messages': [],
        'layers': [{'filename': '自定义高程', 'raster': result['raster_info'], 'geometry_type': 'Raster'}],
    }).json()
    return client, result, saved, data.getvalue()


def test_original_raster_survives_import_without_runtime_or_original_project_files(tmp_path, monkeypatch):
    client, uploaded, saved, original = _upload_real_raster(tmp_path, monkeypatch)
    runtime = Path(tools._temp_output_dir) / 'uploads'
    (runtime / uploaded['raster_info']['source_filename']).unlink()
    (runtime / uploaded['raster_info']['filename']).unlink()
    exported = project_service.export_project(saved['id'])
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        raw_members = [name for name in archive.namelist() if name.endswith('.tif')]
        assert len(raw_members) == 1
        assert archive.read(raw_members[0]) == original
    imported = project_service.import_project(exported)
    project_service.delete_project(saved['id'])
    response = client.get('/api/projects/' + imported['id'])
    assert response.status_code == 200
    layer = response.json()['layers'][0]
    assert layer['geojson'] is None and layer['registration_token']
    restored_raster = layer['raster']
    assert restored_raster['crs'] == uploaded['raster_info']['crs']
    assert restored_raster['source_width'] == uploaded['raster_info']['source_width']
    assert restored_raster['source_height'] == uploaded['raster_info']['source_height']
    assert restored_raster['pixel_units'] == uploaded['raster_info']['pixel_units']
    assert restored_raster['quality_warnings'] == uploaded['raster_info']['quality_warnings']
    assert client.get(layer['raster']['source_url']).content == original
    located = tools._find_uploaded_tif('自定义高程')
    assert str(Path(project_service._project_dir(imported['id']))) in located
    result = tools.raster_calculator.invoke({'layer_name': '自定义高程', 'expression': 'B1*2'})
    assert '范围 [2.00, 32.00]' in result
    assert (runtime / '自定义高程_calc.png').exists()


def test_derived_dem_layer_survives_project_restore_and_can_be_reanalyzed(tmp_path, monkeypatch):
    client, uploaded, _, _ = _upload_real_raster(tmp_path, monkeypatch)
    result = tools.dem_analysis.invoke({'layer_name': uploaded['name'], 'analysis': 'slope'})
    assert 'GeoTIFF' in result and '可继续分析' in result
    op = next(op for op in tools._pending_layer_ops if op.get('action') == 'dem_result')
    layer_name = op['layer_name']
    # The authoritative source path comes from the backend registry, not the URL's display form.
    source_path = Path(tools._registered_layers[layer_name]['raster_source_path'])
    assert source_path.is_file()

    saved = client.post('/api/projects', json={
        'name': '派生地形工程', 'session_id': 'derived-session', 'provider': 'test',
        'map_state': {}, 'messages': [],
        'layers': [{'filename': layer_name, 'geometry_type': 'Raster', 'crs': op['crs'],
                    'source': 'ai', 'raster': op['raster']}],
    }).json()
    assert saved.get('id'), saved
    restored = client.get('/api/projects/' + saved['id'])
    assert restored.status_code == 200
    layer = restored.json()['layers'][0]
    assert layer['name'] == layer_name
    restored_raster = layer['raster']
    for key in ('crs', 'source_width', 'source_height', 'bands', 'pixel_size',
                'pixel_units', 'value_units', 'source_label', 'source_reference',
                'processing', 'valid_pixel_ratio', 'quality_warnings'):
        assert restored_raster.get(key) == op['raster'].get(key)
    assert layer['raster']['source_asset'].endswith('.tif')
    assert client.get(layer['raster']['url']).status_code == 200
    assert client.get(layer['raster']['source_url']).content == source_path.read_bytes()

    project_service.activate_project(saved['id'])
    restored_source = tools._find_uploaded_tif(layer_name)
    assert restored_source and str(Path(project_service._project_dir(saved['id']))) in restored_source
    follow_up = tools.raster_calculator.invoke({'layer_name': layer_name, 'expression': 'B1*2'})
    assert '结果栅格' in follow_up and '已上图' in follow_up


def test_raster_tool_outputs_do_not_modify_project_assets(tmp_path, monkeypatch):
    client, uploaded, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    client.get('/api/projects/' + saved['id'])
    assets = Path(project_service._project_dir(saved['id'])) / 'assets'
    before = {file.name: file.read_bytes() for file in assets.iterdir()}
    result = tools.raster_resample.invoke({'layer_name': '自定义高程', 'scale_factor': 2, 'method': 'nearest'})
    assert '重采样完成' in result
    assert {file.name: file.read_bytes() for file in assets.iterdir()} == before
    assert list((Path(tools._temp_output_dir) / 'uploads').glob('*_重采样.tif'))


def test_failed_raster_replacement_preserves_original_assets(tmp_path, monkeypatch):
    _, _, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    loaded = project_service.load_project(saved['id'])
    assets = Path(project_service._project_dir(saved['id'])) / 'assets'
    before = {file.name: file.read_bytes() for file in assets.iterdir()}
    broken = dict(loaded['layers'][0]['raster'], source_asset='missing.tif')
    with pytest.raises(ValueError, match='原始数据资源不存在'):
        project_service.save_project(saved['id'], '失败替换', 'raw-session', 'test', {}, [], [{'name': 'bad', 'raster': broken}])
    assert {file.name: file.read_bytes() for file in assets.iterdir()} == before
    assert project_service.load_project(saved['id'])['layers'][0]['name'] == '自定义高程'


def test_activation_warns_and_skips_raster_when_original_asset_is_missing(tmp_path, monkeypatch):
    _, _, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    loaded = project_service.load_project(saved['id'])
    raw = project_service._project_raster_path(saved['id'], loaded['layers'][0]['raster']['source_asset'])
    Path(raw).unlink()
    tools._active_project_id = 'previous-project'
    monkeypatch.setitem(ai_service.conversation_history, 'raw-session', [{'role': 'user', 'content': 'previous'}])
    activated = project_service.activate_project(saved['id'])
    assert activated['registration_warnings'] == ['自定义高程']
    assert '自定义高程' not in tools._registered_layers
    assert tools._active_project_id == saved['id']
    assert ai_service.conversation_history['raw-session'] == []


def test_renamed_raster_autosaves_once_and_keeps_raw_data(tmp_path, monkeypatch):
    client, _, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    loaded = client.get('/api/projects/' + saved['id']).json()
    raster = loaded['layers'][0]['raster']
    result = project_service.auto_save('raw-session', project_id=saved['id'], layer_assignments=[{
        'name': '重命名高程', 'registry_name': '自定义高程', 'names': ['自定义高程', '重命名高程'], 'raster': raster,
    }])
    layers = project_service.load_project(result['id'])['layers']
    assert len(layers) == 1 and layers[0]['name'] == '重命名高程'
    assert layers[0]['raster']['source_asset'] == raster['source_asset']
    assert layers[0]['geojson'] is None


def test_active_project_lookup_never_falls_back_to_another_runtime_raster(tmp_path, monkeypatch):
    client, uploaded, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    assert tools._find_uploaded_tif(uploaded['name'])
    client.get('/api/projects/' + saved['id'])
    assert tools._find_uploaded_tif(uploaded['name']) is None
    assert tools._find_uploaded_tif('自定义高程')


def test_legacy_lookup_does_not_match_only_a_substring(tmp_path, monkeypatch):
    _use_temp_projects(tmp_path, monkeypatch)
    path = Path(tools._temp_output_dir) / 'uploads' / 'dem_other.tif'
    path.write_bytes(b'not selected')
    assert tools._find_uploaded_tif('dem') is None
    assert tools._find_uploaded_tif('dem_other') == str(path)


def test_export_refuses_to_silently_omit_a_missing_original(tmp_path, monkeypatch):
    _, _, saved, _ = _upload_real_raster(tmp_path, monkeypatch)
    raster = project_service.load_project(saved['id'])['layers'][0]['raster']
    Path(project_service._project_raster_path(saved['id'], raster['source_asset'])).unlink()
    with pytest.raises(ValueError, match='缺失'):
        project_service.export_project(saved['id'])


@pytest.mark.parametrize('source_asset', ['../outside.tif', 'C:outside.tif', 'missing.tif'])
def test_import_rejects_unsafe_or_missing_original_assets(tmp_path, monkeypatch, source_asset):
    import json
    _use_temp_projects(tmp_path, monkeypatch)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('project.json', json.dumps({'layers': [{'name': 'bad', 'raster': {
            'asset': 'preview.png', 'source_asset': source_asset, 'bounds': [1, 2, 3, 4],
        }}]}))
        zipped.writestr('assets/preview.png', b'preview')
    with pytest.raises(ValueError, match='栅格资源'):
        project_service.import_project(archive.getvalue())
    assert project_service.list_projects() == []
    assert not list((tmp_path / 'projects').glob('proj_*'))
