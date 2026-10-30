const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor(tagName = 'div') { this.tagName = tagName; this.listeners = {}; this.style = {}; this.value = ''; this.textContent = '加载'; this.disabled = false; this.children = []; this.className = ''; this.open = false; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  fire(name, event = {}) { (this.listeners[name] || []).forEach(callback => callback.call(this, event)); }
  click() { this.fire('click', { stopPropagation() {} }); }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  appendChild(child) { this.children.push(child); return child; }
  contains(target) { return target === this; }
}

function createHarness({ savedRecipe, baseUrl = '' } = {}) {
  const elements = new Map(['connectorBtn', 'connectorPanel', 'connectorClose', 'onlineLoadBtn', 'onlineUrl', 'onlineType', 'openOnlineDataBtn', 'settingsModal', 'arcgisLayerId', 'arcgisFetchMode', 'arcgisWhere', 'arcgisBbox', 'arcgisInspectBtn', 'arcgisCancelBtn', 'arcgisRerunBtn', 'arcgisFetchStatus', 'arcgisFetchResult']
    .map(id => [id, new Element()]));
  elements.get('arcgisFetchMode').value = 'preview';
  elements.get('arcgisWhere').value = '1=1';
  const requests = [];
  const layers = [];
  const alerts = [];
  const toasts = [];
  const overlays = [];
  const window = { GIS: {
    api: { BASE_URL: baseUrl },
    map: {
      loadGeoJSON() {},
      addImageOverlay(url, bounds, name, layerId) { overlays.push({ url, bounds, name, layerId }); },
    },
    layers: { addLayer(layer) { layers.push(layer); } },
    chat: { addMessage() {} },
    toast: { info(message) { toasts.push(message); } },
  } };
  const document = {
    readyState: 'loading',
    getElementById(id) { return elements.get(id) || null; },
    createElement(tagName) { return new Element(tagName); },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    addEventListener() {},
  };
  const fetch = (url, options) => new Promise(resolve => requests.push({ url, options, resolve }));
  const sourcePath = path.resolve(__dirname, '../js/connector.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, GIS: window.GIS, document, fetch, alert: message => alerts.push(message), console,
    localStorage: { getItem() { return savedRecipe ? JSON.stringify(savedRecipe) : null; }, setItem() {} },
    Promise, JSON, Array, String, Number, Object, Map, Set, Date, encodeURIComponent, setTimeout() { return 1; }, clearTimeout() {},
  }, { filename: sourcePath });
  window.GIS.connector.init();
  elements.get('onlineUrl').value = 'https://example.test/data.fgb';
  return { elements, requests, layers, alerts, toasts, overlays, panel: elements.get('connectorPanel'), connector: window.GIS.connector };
}

async function flushPromises() {
  await new Promise(resolve => setImmediate(resolve));
  await Promise.resolve();
}

test('rerun restores saved conditions and prevents duplicate starts before a job ID exists', async () => {
  const recipe = { url: 'https://example.test/FeatureServer/0', layer_id: '0', mode: 'full', where: "state = 'CA'", bbox: '-125,32,-114,42' };
  const h = createHarness({ savedRecipe: recipe });
  h.connector.openArcgis({ url: '', mode: 'preview', where: '1=1', bbox: '' });
  h.elements.get('arcgisRerunBtn').fire('click');
  assert.equal(h.elements.get('onlineUrl').value, recipe.url);
  assert.equal(h.elements.get('arcgisFetchMode').value, recipe.mode);
  assert.equal(h.elements.get('arcgisWhere').value, recipe.where);
  assert.equal(h.elements.get('arcgisBbox').value, recipe.bbox);
  assert.deepEqual(JSON.parse(h.requests[0].options.body), recipe);
  assert.equal(h.elements.get('arcgisRerunBtn').disabled, true);
  h.elements.get('arcgisRerunBtn').fire('click');
  assert.equal(h.requests.length, 1);
  h.requests[0].resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: 'provider unavailable' }) });
  await flushPromises();
  assert.match(h.elements.get('arcgisFetchStatus').textContent, /启动失败/);
  assert.equal(h.elements.get('onlineLoadBtn').disabled, false);
  assert.equal(h.elements.get('arcgisRerunBtn').disabled, false);
});

test('online load ignores Enter while the same load is already in flight', () => {
  const h = createHarness();
  h.elements.get('onlineLoadBtn').fire('click');
  h.elements.get('onlineUrl').fire('keydown', { key: 'Enter' });
  assert.equal(h.requests.length, 1);
  assert.equal(h.elements.get('onlineLoadBtn').disabled, true);
});

test('non-success HTTP response preserves the URL and reports load failure', async () => {
  const h = createHarness();
  h.elements.get('onlineLoadBtn').fire('click');
  h.requests[0].resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: 'provider unavailable' }) });
  await flushPromises();

  assert.equal(h.layers.length, 0);
  assert.equal(h.elements.get('onlineUrl').value, 'https://example.test/data.fgb');
  assert.match(h.alerts[0], /provider unavailable|503/);
  assert.equal(h.elements.get('onlineLoadBtn').disabled, false);
});

test('ArcGIS home shortcut opens the online panel and focuses the address field', () => {
  const h = createHarness();
  h.elements.get('settingsModal').style.display = 'block';

  h.connector.openArcgis({ url: '', layer_id: '', mode: 'preview', where: '1=1', bbox: '', selectUrl: true });

  assert.equal(h.elements.get('settingsModal').style.display, 'none');
  assert.equal(h.panel.style.display, 'block');
  assert.equal(h.elements.get('onlineType').value, 'arcgis-rest');
  assert.equal(h.elements.get('onlineLoadBtn').textContent, '获取');
  assert.equal(h.elements.get('onlineUrl').placeholder, '粘贴 ArcGIS REST FeatureServer / MapServer 地址');
  assert.equal(h.elements.get('onlineUrl').focused, true);
  assert.equal(h.elements.get('onlineUrl').selected, true);
});

test('ArcGIS sample shortcut pre-fills a replaceable, filtered full-fetch recipe', () => {
  const h = createHarness();
  h.connector.openArcgis({
    url: 'https://sampleserver6.arcgisonline.com/arcgis/rest/services/Census/MapServer',
    layer_id: '2', mode: 'full', where: "STATE_NAME = 'Alabama'", bbox: '',
  });

  assert.equal(h.elements.get('onlineUrl').value, 'https://sampleserver6.arcgisonline.com/arcgis/rest/services/Census/MapServer');
  assert.equal(h.elements.get('arcgisLayerId').value, '2');
  assert.equal(h.elements.get('arcgisFetchMode').value, 'full');
  assert.equal(h.elements.get('arcgisWhere').value, "STATE_NAME = 'Alabama'");
});

test('ArcGIS inspection summarizes decision-critical metadata and collapses fields', async () => {
  const h = createHarness();
  h.elements.get('onlineType').value = 'arcgis-rest';
  h.elements.get('onlineUrl').value = 'https://example.test/FeatureServer/2';
  h.elements.get('arcgisLayerId').value = '2';
  h.elements.get('arcgisInspectBtn').fire('click');
  h.requests[0].resolve({ ok: true, status: 200, json: () => Promise.resolve({
    layer_name: 'Detailed Counties', layer_id: 2, geometry_type: 'Polygon', crs: 'EPSG:4326',
    object_id_field: 'OBJECTID', max_record_count: 1000, supports_pagination: true,
    fields: [{ name: 'OBJECTID' }, { name: 'STATE_NAME' }, { name: 'POP2000' }],
  }) });
  await flushPromises();

  const status = h.elements.get('arcgisFetchStatus');
  assert.equal(status.style.display, '');
  assert.equal(status.children[0].textContent, '图层检查完成');
  assert.match(status.children[1].textContent, /Detailed Counties.*Polygon.*EPSG:4326/);
  assert.match(status.children[2].textContent, /OBJECTID.*1000.*分页：支持/);
  const fields = status.children[3];
  assert.equal(fields.tagName, 'details');
  assert.equal(fields.open, false);
  assert.equal(fields.children[0].textContent, '查看全部 3 个字段');
  assert.deepEqual(fields.children[1].children.map(field => field.textContent), ['OBJECTID', 'STATE_NAME', 'POP2000']);
  assert.match(status.children[4].textContent, /确认图层与筛选条件/);
  assert.equal(h.elements.get('arcgisInspectBtn').disabled, false);
});

test('ArcGIS complete, partial, unknown, and failed results remain distinct', async () => {
  async function runJob(job) {
    const h = createHarness();
    h.elements.get('onlineType').value = 'arcgis-rest';
    h.elements.get('onlineUrl').value = 'https://example.test/FeatureServer/2';
    h.elements.get('onlineLoadBtn').fire('click');
    h.requests[0].resolve({ ok: true, status: 200, json: () => Promise.resolve({ job_id: 'job-1' }) });
    await flushPromises();
    h.requests[1].resolve({ ok: true, status: 200, json: () => Promise.resolve(job) });
    await flushPromises();
    if (job.result && job.result.data_url) {
      const dataRequest = h.requests[2];
      dataRequest.resolve({ ok: true, json: () => Promise.resolve({ type: 'FeatureCollection', features: [] }) });
      await flushPromises();
    }
    return h;
  }

  const complete = await runJob({ status: 'completed', result: {
    mode: 'full', completeness: 'complete', expected_count: 2, feature_count: 2,
    data_url: '/data', report_url: '/report', manifest_url: '/manifest', recipe_url: '/recipe',
    warnings: ['对象 ID 一致不代表属性值未变化'],
  } });
  assert.match(complete.elements.get('arcgisFetchStatus').textContent, /完整性检查通过：2 \/ 2/);
  assert.match(complete.elements.get('arcgisFetchStatus').textContent, /对象 ID 一致不代表属性值未变化/);
  assert.deepEqual(complete.elements.get('arcgisFetchResult').children.map(link => link.textContent), ['下载数据', '检查报告', '来源清单', '复跑配方']);
  assert.deepEqual(complete.elements.get('arcgisFetchResult').children.map(link => link.href), ['/data?download=1', '/report?download=1', '/manifest?download=1', '/recipe?download=1']);
  assert.equal(complete.layers.length, 1);

  const preview = await runJob({ status: 'completed', result: {
    mode: 'preview', completeness: 'not_checked', expected_count: 2, feature_count: 2, data_url: '/preview-data',
  } });
  assert.match(preview.elements.get('arcgisFetchStatus').textContent, /预览已获取 2 条；完整性未检查/);
  assert.doesNotMatch(preview.elements.get('arcgisFetchStatus').textContent, /完整性检查通过/);

  const partial = await runJob({ status: 'completed', result: {
    mode: 'full', completeness: 'partial', expected_count: 2, feature_count: 1, data_url: '/partial-data',
  } });
  assert.match(partial.elements.get('arcgisFetchStatus').textContent, /只获取到部分数据：1 \/ 2/);

  const unknown = await runJob({ status: 'completed', result: {
    mode: 'full', completeness: 'unknown', completeness_reason: '无法复查源 ID 清单', expected_count: 2,
    feature_count: 2, data_url: '/unknown-data',
  } });
  assert.match(unknown.elements.get('arcgisFetchStatus').textContent, /完整性无法确认：无法复查源 ID 清单/);

  const unavailable = await runJob({ status: 'unknown', error: '无法获得可靠 ID 清单' });
  assert.match(unavailable.elements.get('arcgisFetchStatus').textContent, /完整性未知，未生成可交付数据/);
  assert.equal(unavailable.elements.get('arcgisFetchResult').style.display, 'none');
  assert.equal(unavailable.layers.length, 0);

  const failed = await runJob({ status: 'failed', error: 'provider unavailable' });
  assert.match(failed.elements.get('arcgisFetchStatus').textContent, /获取失败：provider unavailable/);
  assert.equal(failed.elements.get('arcgisFetchResult').style.display, 'none');
});

test('online load raster PMTiles retains preview_only, processing, and displays center-tile warning toast', async () => {
  const h = createHarness();
  h.elements.get('onlineUrl').value = 'https://example.test/elevation.pmtiles';
  h.elements.get('onlineLoadBtn').fire('click');

  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/online/load');

  h.requests[0].resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({
      name: 'Elevation_Center',
      raster_info: {
        url: '/output/uploads/pmtiles_tile.png',
        bounds: [100.1, 30.1, 100.2, 30.2],
        preview_only: true,
        preview_scope: 'pmtiles_center_tile',
        processing: '仅中心瓦片预览',
        crs: 'EPSG:3857',
      },
      message: '已加载栅格 PMTiles（中心单瓦片预览）: Elevation_Center',
      meta: {
        bounds_wgs84: [95.0, 25.0, 105.0, 35.0],
      },
    }),
  });
  await flushPromises();

  assert.equal(h.layers.length, 1);
  const layer = h.layers[0];
  assert.equal(layer.filename, 'Elevation_Center');
  assert.equal(layer.geometry_type, 'Raster');
  assert.equal(layer.crs, 'EPSG:3857');
  assert.equal(layer.preview_only, true);
  assert.equal(layer.processing, '仅中心瓦片预览');
  assert.equal(layer.raster.preview_only, true);
  assert.equal(layer.raster.preview_scope, 'pmtiles_center_tile');
  assert.equal(layer.raster.processing, '仅中心瓦片预览');
  assert.deepEqual(layer.raster.dataset_bounds, [95.0, 25.0, 105.0, 35.0]);
  assert.deepEqual(layer.raster.meta, { bounds_wgs84: [95.0, 25.0, 105.0, 35.0] });

  assert.deepEqual(h.toasts, ['仅中心瓦片预览']);
  assert.equal(h.elements.get('onlineLoadBtn').disabled, false);
  assert.equal(h.elements.get('onlineUrl').value, '');
});

test('online load prefixes relative raster_info.url with BASE_URL for overlay and layer record', async () => {
  const h = createHarness({ baseUrl: 'https://api.example.test' });
  h.elements.get('onlineUrl').value = 'https://example.test/remote-layer.tif';
  h.elements.get('onlineLoadBtn').fire('click');

  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, 'https://api.example.test/api/online/load');

  const bounds = [102.0, 24.0, 103.0, 25.0];
  h.requests[0].resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({
      name: 'Relative_Preview',
      raster_info: {
        url: '/output/uploads/preview.png',
        bounds: bounds,
      },
    }),
  });
  await flushPromises();

  assert.equal(h.overlays.length, 1);
  const overlay = h.overlays[0];
  assert.equal(overlay.url, 'https://api.example.test/output/uploads/preview.png');
  assert.deepEqual(overlay.bounds, bounds);
  assert.equal(overlay.name, 'Relative_Preview');

  assert.equal(h.layers.length, 1);
  assert.equal(h.layers[0].raster.url, 'https://api.example.test/output/uploads/preview.png');
  assert.equal(h.layers[0].raster.url, overlay.url);
  assert.deepEqual(h.layers[0].raster.bounds, bounds);
});

test('online load handles GeoJSON feature collection with null first geometry gracefully', async () => {
  const h = createHarness();
  h.elements.get('onlineUrl').value = 'https://example.test/parcels.parquet';
  h.elements.get('onlineLoadBtn').fire('click');

  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/online/load');

  h.requests[0].resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({
      name: 'Null_Geometry_Layer',
      geojson: {
        type: 'FeatureCollection',
        features: [
          { type: 'Feature', geometry: null, properties: { id: 1 } },
          { type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: { id: 2 } },
        ],
      },
    }),
  });
  await flushPromises();

  assert.equal(h.layers.length, 1);
  const layer = h.layers[0];
  assert.equal(layer.filename, 'Null_Geometry_Layer');
  assert.equal(layer.geometry_type, '未知');
  assert.equal(layer.source, 'upload');
  assert.equal(h.elements.get('onlineLoadBtn').disabled, false);
  assert.equal(h.elements.get('onlineUrl').value, '');
});
