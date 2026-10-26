const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function createGeoSource(initialLayers) {
  const layers = initialLayers.map(layer => ({ ...layer }));
  const removed = [];
  const rendered = [];
  const notices = [];
  const window = { GIS: {
    api: { BASE_URL: '' },
    map: { addWmsLayer(url, layer, name) { rendered.push({ url, layer, name }); } },
    layers: {
      getLayers() { return layers; },
      removeLayer(id) {
        removed.push(id);
        const index = layers.findIndex(layer => layer.layer_id === id);
        if (index >= 0) layers.splice(index, 1);
      },
      addLayer(layer) { layers.push(layer); },
    },
    toast: {
      info(message) { notices.push({ type: 'info', message }); },
      warn(message) { notices.push({ type: 'warn', message }); },
      error(message) { notices.push({ type: 'error', message }); },
      success(message) { notices.push({ type: 'success', message }); },
    },
    chat: { addMessage() {} },
  }, addEventListener() {} };
  const document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/geosource.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, console, Promise, JSON, Array, String, Number, Object, Date,
    encodeURIComponent, decodeURIComponent, setTimeout, clearTimeout,
  }, { filename: sourcePath });
  return { geosource: window.GIS.geosource, layers, removed, rendered, notices };
}

function loadWms(geosource, name) {
  geosource.loadWmsSublayer(
    encodeURIComponent('https://maps.example.test/wms'),
    encodeURIComponent('roads'),
    encodeURIComponent(name),
  );
}

test('GeoSource capacity does not evict existing workspace layers', () => {
  const h = createGeoSource([
    { layer_id: 'analysis', filename: '分析结果', source: 'ai' },
    { layer_id: 'upload', filename: '本地上传', source: 'upload' },
    { layer_id: 'bookmark', filename: '工作区图层', source: 'manual' },
  ]);

  loadWms(h.geosource, '在线道路');

  assert.deepEqual(h.removed, []);
  assert.equal(h.rendered.length, 0);
  assert.equal(h.layers.length, 3);
  assert.equal(h.notices[0].type, 'warn');
  assert.match(h.notices[0].message, /先.*移除/);
});

test('GeoSource name collision does not replace a non-GeoSource layer', () => {
  const h = createGeoSource([
    { layer_id: 'analysis', filename: '道路', source: 'ai' },
    { layer_id: 'upload', filename: '本地上传', source: 'upload' },
  ]);

  loadWms(h.geosource, '道路');

  assert.deepEqual(h.removed, []);
  assert.equal(h.rendered.length, 0);
  assert.equal(h.layers[0].source, 'ai');
  assert.equal(h.notices[0].type, 'error');
});

test('reloading the same GeoSource layer replaces that layer without evicting peers', () => {
  const h = createGeoSource([
    { layer_id: 'old-road', filename: '在线道路', source: 'geosource' },
    { layer_id: 'analysis', filename: '分析结果', source: 'ai' },
  ]);

  loadWms(h.geosource, '在线道路');

  assert.deepEqual(h.removed, ['old-road']);
  assert.equal(h.rendered.length, 1);
  assert.equal(h.layers[0].source, 'ai');
  assert.equal(h.layers[1].source, 'geosource');
});
