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

test('shared layer state assigns and indexes feature IDs when GeoJSON properties are null', () => {
  const window = { GIS: { map: { loadGeoJSON() {} } } };
  const sourcePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), { window, Date, Math, Object, Array, String, Number }, { filename: sourcePath });
  const geojson = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: null, geometry: { type: 'Point', coordinates: [1, 2] } },
  ] };

  const layer = window.GIS.state.addLayer({ layer_id: 'null-properties', name: '空属性', geojson });

  assert.equal(geojson.features[0].properties._fid, 'i:0');
  assert.equal(layer.fidIndex['i:0'], 0);
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

test('shared layer state suffixes Unicode normalization aliases of existing names', () => {
  const window = { GIS: { map: { loadGeoJSON() {} } } };
  const sourcePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), { window, Date, Math, Object, Array, String, Number }, { filename: sourcePath });

  const composed = window.GIS.state.addLayer({
    name: 'é', geojson: { type: 'FeatureCollection', features: [] },
  });
  const decomposed = window.GIS.state.addLayer({
    name: 'e\u0301', geojson: { type: 'FeatureCollection', features: [] },
  });

  assert.equal(composed.name, 'é');
  assert.equal(decomposed.name, 'e\u0301_1');
});

test('layer selector labels disambiguate Unicode aliases without changing option values', () => {
  const window = { GIS: {} };
  const sourcePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, Date, Math, Object, Array, String, Number,
  }, { filename: sourcePath });

  const entries = window.GIS.state.layerOptionEntries(['é.geojson', 'e\u0301.geojson', 'roads.geojson']);

  assert.deepEqual(JSON.parse(JSON.stringify(entries)), [
    { value: 'é.geojson', label: 'é.geojson (1)', suffix: ' (1)' },
    { value: 'e\u0301.geojson', label: 'e\u0301.geojson (2)', suffix: ' (2)' },
    { value: 'roads.geojson', label: 'roads.geojson', suffix: '' },
  ]);
});

test('shared layer state forwards source provenance to the layer panel', () => {
  let panelLayer;
  const window = { GIS: {
    map: { loadGeoJSON() {} },
    layers: { addLayer(layer) { panelLayer = layer; } },
  } };
  const sourcePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, Date, Math, Object, Array, String, Number,
  }, { filename: sourcePath });
  const provenance = { provider_name: 'OpenStreetMap', crs: 'EPSG:4326' };

  const layer = window.GIS.state.addLayer({
    name: '下载道路', geojson: { type: 'FeatureCollection', features: [] }, provenance,
  });

  assert.equal(layer.provenance.provider_name, 'OpenStreetMap');
  assert.equal(panelLayer.provenance.crs, 'EPSG:4326');
});

test('shared layer state preserves backend registration identity and version token', () => {
  let panelLayer;
  const window = { GIS: {
    map: { loadGeoJSON() {} },
    layers: { addLayer(layer) { panelLayer = layer; } },
  } };
  const sourcePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, Date, Math, Object, Array, String, Number,
  }, { filename: sourcePath });

  const layer = window.GIS.state.addLayer({
    name: 'roads_buffer_1730000000000_0',
    registry_name: 'roads_buffer',
    registration_token: 'registered-version',
    geojson: { type: 'FeatureCollection', features: [] },
  });

  assert.equal(layer._registeredName, 'roads_buffer');
  assert.equal(layer._registrationTokens.roads_buffer, 'registered-version');
  assert.equal(panelLayer._registeredName, 'roads_buffer');
  assert.equal(panelLayer._registrationTokens.roads_buffer, 'registered-version');
});

test('a hidden state-only layer is rendered when it becomes visible without changing map extent', () => {
  const mapLayers = new Map();
  const loads = [];
  const map = {
    getLayer(name) { return mapLayers.get(name) || null; },
    loadGeoJSON(geojson, name, style, options) {
      loads.push({ name, style, options });
      mapLayers.set(name, { geojson, visible: true });
    },
    setLayerVisible(name, visible) {
      const layer = mapLayers.get(name);
      if (layer) layer.visible = visible;
    },
  };
  const window = { GIS: { map } };
  const sourcePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, Date, Math, Object, Array, String, Number,
  }, { filename: sourcePath });
  const geojson = { type: 'FeatureCollection', features: [] };
  const layer = window.GIS.state.addLayer({ layer_id: 'hidden-layer', name: '初始隐藏', geojson,
    style: { color: '#123456' }, visible: false });

  assert.equal(loads.length, 0, 'initially hidden layers need not affect the map view');
  window.GIS.state.setVisible(layer.layer_id, true);

  assert.equal(loads.length, 1);
  assert.equal(loads[0].name, '初始隐藏');
  assert.equal(loads[0].style.color, '#123456');
  assert.equal(loads[0].options.fitBounds, false);
  assert.equal(mapLayers.get('初始隐藏').visible, true);
});
