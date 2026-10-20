const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

test('shared layer state gives duplicate feature IDs unique fallbacks and indexes them independently', () => {
  const window = { GIS: { map: { loadGeoJSON() {} } } };
  const sourcePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), { window, Date, Math, Object, Array, String, Number }, { filename: sourcePath });
  const geojson = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { _fid: 'duplicate', name: '区域', id: 11 }, geometry: null },
    { type: 'Feature', properties: { _fid: 'duplicate', name: '区域', id: 12 }, geometry: null },
  ] };

  const layer = window.GIS.state.addLayer({ layer_id: 'duplicate-fids', name: '重复ID数据', geojson });
  const ids = geojson.features.map(item => item.properties._fid);
  assert.equal(new Set(ids).size, 2);
  assert.deepEqual(ids, ['duplicate', 'id:12']);
  assert.equal(layer.fidIndex[ids[0]], 0);
  assert.equal(layer.fidIndex[ids[1]], 1);
});

test('data source IDs take precedence over repeated feature names', () => {
  const window = { GIS: { map: { loadGeoJSON() {} } } };
  const sourcePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), { window, Date, Math, Object, Array, String, Number }, { filename: sourcePath });
  const geojson = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { name: '同名区', id: 1 }, geometry: null },
    { type: 'Feature', properties: { name: '同名区', id: 2 }, geometry: null },
  ] };
  window.GIS.state.addLayer({ name: '同名数据', geojson });
  assert.deepEqual(geojson.features.map(item => item.properties._fid), ['id:1', 'id:2']);
});
