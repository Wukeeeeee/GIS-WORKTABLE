const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function createHarness(initialStorage = {}, backendSettings = { providers: [] }, mutation, timers = { setTimeout, clearTimeout }) {
  const storage = new Map(Object.entries(initialStorage));
  const requests = [];
  const localStorage = {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); },
    removeItem(key) { storage.delete(key); },
  };
  const document = {
    body: { contains() { return true; }, appendChild() {} },
    createElement() { return { classList: { add() {}, remove() {} }, appendChild() {}, click() {} }; },
    querySelectorAll() { return []; },
  };
  const window = { GIS: {}, location: { origin: 'http://localhost:8000', protocol: 'http:' } };
  const fetch = (url, options = {}) => {
    requests.push({ url, options });
    if (!options.method && !url.includes('/api/projects/')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(structuredClone(backendSettings)) });
    }
    if (mutation) return mutation(url, options);
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'ok' }) });
  };
  const sourcePath = path.resolve(__dirname, '../js/api.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, GIS: window.GIS, document, localStorage, fetch, Promise, Array, Object, String,
    Number, Math, Date, JSON, Set, Map, Blob, FormData, URL, AbortController,
    setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout,
    requestAnimationFrame() {}, console: { warn() {}, log() {} },
  }, { filename: sourcePath });
  return { api: window.GIS.api, requests, storage, gis: window.GIS };
}

test('provider API keys stay in localStorage and are omitted from backend sync', async () => {
  const key = 'test-only-provider-key';
  const h = createHarness();
  const providers = [{ id: 'custom', name: 'Custom', base_url: 'https://example.invalid', model: 'test', api_key: key }];

  h.api.setProviders(providers);
  assert.equal(JSON.parse(h.storage.get('gis_llm_providers'))[0].api_key, key);
  assert.equal(h.requests.length, 1);
  assert.equal(JSON.parse(h.requests[0].options.body).providers[0].api_key, undefined);

  const local = createHarness({ gis_llm_providers: JSON.stringify(providers) }, {
    providers: [
      { id: 'custom', name: 'Custom', api_key: 'legacy-server-key' },
      { id: 'remote', name: 'Remote', api_key: 'legacy-server-key', model: 'remote-model' },
    ],
  });
  local.requests.length = 0;
  const result = await local.api.syncUserSettingsFromBackend();
  const savedProviders = JSON.parse(local.storage.get('gis_llm_providers'));
  assert.equal(savedProviders.find(provider => provider.id === 'custom').api_key, key);
  assert.equal(savedProviders.find(provider => provider.id === 'remote').api_key, undefined);
  assert.equal(result.data.providers.some(provider => Object.hasOwn(provider, 'api_key')), false);
  const syncRequest = local.requests.find(request => request.options.method === 'POST');
  assert.ok(syncRequest, 'local providers should still synchronize safe metadata');
  assert.equal(JSON.stringify(syncRequest.options.body).includes('legacy-server-key'), false);
  assert.equal(JSON.parse(syncRequest.options.body).providers[0].api_key, undefined);
});

test('project import and export errors retain backend validation details', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({
    ok: false,
    status: 400,
    json: async () => ({ detail: '工程文件中缺少矢量数据文件' }),
  }));
  await assert.rejects(h.api.importProject(new Blob(['invalid project'])), /导入工程失败: 工程文件中缺少矢量数据文件/);
  await assert.rejects(h.api.exportProject('missing'), /导出工程失败: 工程文件中缺少矢量数据文件/);
});

test('SHP export rejects a JSON error response instead of downloading it as a ZIP', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({
    ok: true,
    headers: { get: () => 'application/json' },
    json: async () => ({ error: '混合几何类型无法导出' }),
  }));
  const messages = [];
  h.gis.chat = { addMessage(message, type) { messages.push({ message, type }); } };
  h.gis.utils.escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);

  await h.api.exportShp({ type: 'FeatureCollection', features: [] }, 'mixed');

  assert.equal(h.requests[0].url, 'http://localhost:8000/api/layer/export-shp');
  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, 'system');
  assert.match(messages[0].message, /混合几何类型无法导出/);
  assert.doesNotMatch(messages[0].message, /<|>/);
});

test('registry API forwards the registration version and returns the next version', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({ ok: true, json: async () => ({ success: true, registration_token: 'next' }) }));
  const registered = await h.api.registerLayer('demo', { type: 'FeatureCollection', features: [] });
  assert.equal(registered.registration_token, 'next');
  await h.api.unregisterLayer('demo', 'next');
  const request = h.requests.find(item => item.url.endsWith('/unregister'));
  assert.equal(JSON.parse(request.options.body).registration_token, 'next');
  assert.ok(request.options.signal instanceof AbortSignal);
});

for (const method of ['registerLayer', 'unregisterLayer']) test(`${method} aborts a stalled request and releases its timer`, async () => {
  let clears = 0;
  const h = createHarness({}, {}, (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
  }), { setTimeout(fn) { queueMicrotask(fn); return 1; }, clearTimeout() { clears++; } });
  await assert.rejects(h.api[method]('demo', {}), /超时/);
  assert.equal(clears, 1);
});

for (const body of [null, { success: false }, { ok: true }]) test(`registry rejects an unconfirmed success response: ${JSON.stringify(body)}`, async () => {
  const h = createHarness({}, {}, () => Promise.resolve({ ok: true, json: async () => body }));
  await assert.rejects(h.api.unregisterLayer('demo'), /未确认/);
});

test('tool synchronization uses the tracked layer queue and propagates a failure', async () => {
  const h = createHarness(); const names = [];
  h.gis.layers = { syncToolLayer(name) { names.push(name); return Promise.resolve(false); } };
  await assert.rejects(h.api.syncLayer('display'), /同步失败/);
  assert.deepEqual(names, ['display']);
  assert.equal(h.requests.length, 0);
});

test('manual tool invocation preserves structured warnings without changing the response text', async () => {
  const warning = 'size: 窗口应为奇数（3/5/7），已自动调整为 5';
  const h = createHarness({}, {}, () => Promise.resolve({ ok: true, json: async () => ({
    ok: true, tool: 'raster_focal_stats', response: '分析完成', param_warnings: [warning],
  }) }));
  const result = await h.api.invokeTool('raster_focal_stats', { layer_name: 'dem', size: 4 });

  assert.deepEqual(Array.from(result.param_warnings), [warning]);
  assert.match(result.response, /分析完成/);
  assert.doesNotMatch(result.response, /参数提示：/);
  assert.equal(JSON.parse(h.requests[0].options.body).arguments.size, 4);
});

test('fallback synchronization keeps large data and stores the exact registered alias version', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({ok: true, json: async () => ({success: true, registration_token: 'fresh'})}));
  const layer = {filename: 'display', geojson: {type: 'FeatureCollection', features: Array(20001).fill({type: 'Feature', geometry: null, properties: {}})}};
  h.gis.layers = {getLayerByName() { return layer; }};
  await h.api.syncLayer('selected-id');
  const body = JSON.parse(h.requests[0].options.body);
  assert.equal(body.name, 'selected-id'); assert.equal(body.geojson.features.length, 20001);
  assert.equal(layer._registrationTokens['selected-id'], 'fresh');
});

test('fallback synchronization rejects a network failure instead of allowing stale analysis', async () => {
  const h = createHarness({}, {}, () => Promise.reject(new Error('offline')));
  h.gis.layers = { getLayerByName() { return {geojson: {type: 'FeatureCollection', features: []}}; } };
  await assert.rejects(h.api.syncLayer('display'), /offline/);
});

test('upload marks a lost connection as an unknown receipt state and preserves cancellation', async () => {
  const offline = createHarness({}, {}, () => Promise.reject(new TypeError('Failed to fetch')));
  const uploadError = await offline.api.upload(new Blob(['test file']), new AbortController().signal)
    .then(() => null, error => error);
  assert.equal(uploadError.code, 'UPLOAD_NETWORK_ERROR');
  assert.equal(offline.requests[0].url, 'http://localhost:8000/api/upload');
  assert.equal(offline.requests[0].options.method, 'POST');

  const cancelled = createHarness({}, {}, () => Promise.reject(Object.assign(new Error('cancelled'), { name: 'AbortError' })));
  await assert.rejects(cancelled.api.upload(new Blob(['test file'])), error => error.name === 'AbortError');
});

test('raster synchronization sends the managed source metadata and tracks its version', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({ok: true, json: async () => ({success: true, registration_token: 'raster-current'})}));
  const layer = {raster: {source_asset: 'original.tif', project_id: 'project', bounds: [1, 2, 3, 4]}};
  h.gis.layers = {getLayerByName() {return layer;}};
  await h.api.syncLayer('renamed raster');
  const body = JSON.parse(h.requests[0].options.body);
  assert.equal(body.name, 'renamed raster'); assert.deepEqual(body.raster, layer.raster);
  assert.equal(layer._registrationTokens['renamed raster'], 'raster-current');
});
