const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function createHarness(initialStorage = {}, backendSettings = { providers: [] }, mutation, timers = { setTimeout, clearTimeout }, storageFailure = {}) {
  const storage = new Map(Object.entries(initialStorage));
  const requests = [];
  const localStorage = {
    getItem(key) { if (storageFailure.read) throw new Error('storage unavailable'); return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { if (storageFailure.write) throw new Error('storage unavailable'); storage.set(key, String(value)); },
    removeItem(key) { if (storageFailure.remove) throw new Error('storage unavailable'); storage.delete(key); },
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

test('provider keys remain usable for this session when localStorage is unavailable', async () => {
  const cases = [
    { failure: { read: true, write: true }, storage: {} },
    {
      failure: { write: true },
      storage: {
        gis_selected_model: 'glm-routed',
        gis_llm_providers: JSON.stringify([{
          id: 'custom', name: 'Custom', base_url: 'https://example.invalid/v1', model: 'test-model', api_key: '',
        }]),
      },
    },
  ];
  for (const scenario of cases) {
    const h = createHarness(scenario.storage, { providers: [] }, undefined, undefined, scenario.failure);
    const provider = h.api.getProviders().find(item => item.id === 'custom');
    provider.base_url = 'https://example.invalid/v1';
    provider.model = 'test-model';
    provider.api_key = 'session-only-provider-key';

    h.api.upsertProvider(provider);
    assert.equal(h.api.areProviderSettingsPersistent(), false);
    assert.equal(h.api.getProvider('custom').api_key, provider.api_key);
    h.api.setSelectedModel('custom');
    assert.equal(h.api.getSelectedModel(), 'custom');
    await h.api.chat('test task');
    await h.api.testProvider(provider);

    const chatRequest = h.requests.find(request => request.url.endsWith('/api/chat'));
    assert.equal(JSON.parse(chatRequest.options.body).llm_config.api_key, provider.api_key);
    const testRequest = h.requests.find(request => request.url.endsWith('/api/test-key'));
    assert.equal(JSON.parse(testRequest.options.body).llm_config.api_key, provider.api_key);
    const settingsRequest = h.requests.find(request => request.url.endsWith('/api/user-settings'));
    assert.equal(JSON.stringify(settingsRequest.options.body).includes(provider.api_key), false);
  }
});

test('backend provider metadata stays selectable in memory when localStorage is unavailable', async () => {
  const remoteProvider = {
    id: 'remote-custom', name: 'Remote Custom',
    base_url: 'https://example.invalid/v1', model: 'remote-model',
  };
  const h = createHarness({}, {
    providers: [remoteProvider], selected_provider: remoteProvider.id,
  }, undefined, undefined, { read: true, write: true });

  await h.api.syncUserSettingsFromBackend();

  assert.equal(h.api.areProviderSettingsPersistent(), false);
  assert.equal(h.api.getProvider(remoteProvider.id).model, remoteProvider.model);
  assert.equal(h.api.getSelectedModel(), remoteProvider.id);
});

test('user model selection is not overwritten by a late backend settings sync', async () => {
  const remoteProvider = {
    id: 'remote-custom', name: 'Remote Custom',
    base_url: 'https://example.invalid/v1', model: 'remote-model',
  };
  const h = createHarness({}, {
    providers: [remoteProvider], selected_provider: remoteProvider.id,
  }, undefined, undefined, { read: true, write: true });

  h.api.setSelectedModel('custom');
  await h.api.syncUserSettingsFromBackend();

  assert.equal(h.api.getSelectedModel(), 'custom');
});

test('chat and connection test send a provider key only inside llm_config', async () => {
  const key = 'request-only-provider-key';
  const provider = {
    id: 'custom', name: 'Custom', base_url: 'https://example.invalid/v1',
    model: 'test-model', api_key: key,
  };
  const h = createHarness();

  await h.api.chat('hello', 'session', provider);
  await h.api.testProvider(provider);

  const chatBody = JSON.parse(h.requests[0].options.body);
  const testBody = JSON.parse(h.requests[1].options.body);
  assert.equal(chatBody.llm_config.api_key, key);
  assert.equal(Object.hasOwn(chatBody, 'api_key'), false);
  assert.equal(testBody.llm_config.api_key, key);
  assert.equal(Object.hasOwn(testBody, 'api_key'), false);
});

test('non-stream chat forwards its request ID and caller cancellation signal', async () => {
  let requestOptions;
  let finishFetch;
  const h = createHarness({}, {}, (_url, options) => {
    requestOptions = options;
    return new Promise(resolve => { finishFetch = resolve; });
  });
  const caller = new AbortController();
  const pending = h.api.chat('hello', 'session', null, [], 'full', 'request-123', caller.signal);
  await Promise.resolve();

  assert.equal(JSON.parse(requestOptions.body).request_id, 'request-123');
  assert.notEqual(requestOptions.signal, caller.signal);
  caller.abort('user-cancel');
  assert.equal(requestOptions.signal.aborted, true);
  finishFetch({ ok: true, json: async () => ({ response: 'cancelled' }) });
  assert.equal((await pending).response, 'cancelled');
});

test('non-stream chat shows a backend transport-security explanation', async () => {
  const detail = '公网或无法确认地址的模型服务必须使用 HTTPS';
  const h = createHarness({}, {}, () => Promise.resolve({
    ok: false, status: 400, json: async () => ({ detail }),
  }));

  await assert.rejects(h.api.chat('hello'), new RegExp(detail));
});

test('Amap key stays local and reports encrypted backend persistence success or failure', async () => {
  const key = 'test-only-amap-key';
  const saved = createHarness();
  await saved.api.setAmapKey(key);
  assert.equal(saved.api.getAmapKey(), key);
  assert.deepEqual(JSON.parse(saved.requests[0].options.body), { amap_key: key });

  const failed = createHarness({}, {}, () => Promise.resolve({
    ok: false, status: 500, json: async () => ({ status: 'error', detail: '检查磁盘空间后重试' }),
  }));
  await assert.rejects(failed.api.setAmapKey(key), /检查磁盘空间后重试/);
  assert.equal(failed.api.getAmapKey(), key, 'local key remains available in this browser');
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

test('registry updates forward the token for exact server-side property preservation', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({ ok: true, json: async () => ({ success: true, registration_token: 'next' }) }));
  await h.api.registerLayer('demo', { type: 'FeatureCollection', features: [] }, null, undefined, true, 'current');
  const payload = JSON.parse(h.requests[0].options.body);
  assert.equal(payload.registration_token, 'current');
});

test('registry API preserves the project context captured by the layer queue', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({
    ok: true, json: async () => ({ success: true, registration_token: 'context-token' }),
  }));
  h.gis.project = {
    getCurrentProjectId() { return 'project-b'; },
    getActiveRegistryProjectId() { return null; },
  };
  await h.api.registerLayer('old-result', { type: 'FeatureCollection', features: [] }, null, 'project-a');
  await h.api.registerLayer('new-session', { type: 'FeatureCollection', features: [] });
  await h.api.resetActiveProjectContext(null);

  const payloads = h.requests.filter(request => request.url.includes('/api/layer/register'))
    .map(request => JSON.parse(request.options.body));
  assert.deepEqual(payloads.map(payload => [payload.project_context, payload.expected_project_id]), [
    [true, 'project-a'], [true, null],
  ]);
  const reset = h.requests.find(request => request.url.endsWith('/api/projects/active/reset'));
  assert.deepEqual(JSON.parse(reset.options.body), { expected_project_id: null });
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

test('upload exposes a structured backend error for a rejected upload', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({
    ok: false, status: 507, json: async () => ({ detail: '服务器磁盘空间不足，上传未完成。请释放空间后重试。' }),
  }));
  await assert.rejects(h.api.upload(new Blob(['test file'])), error => {
    assert.equal(error.status, 507);
    assert.match(error.message, /磁盘空间不足/);
    return true;
  });
});

test('upload request IDs are reused in the URL and status lookup returns a committed result', async () => {
  const recoveredResult = { name: 'points.geojson', registration_token: 'version', geojson: { type: 'FeatureCollection', features: [] } };
  const h = createHarness({}, {}, url => Promise.resolve({
    ok: true,
    json: async () => url.includes('/api/upload/status/')
      ? { status: 'completed', result: recoveredResult }
      : recoveredResult,
  }));
  await h.api.upload(new Blob(['test file']), undefined, 'upload-request-123');
  assert.equal(h.requests[0].url, 'http://localhost:8000/api/upload?request_id=upload-request-123');
  const status = await h.api.getUploadStatus('upload-request-123');
  assert.equal(status.status, 'completed');
  assert.equal(status.result.registration_token, 'version');
  assert.equal(h.requests[1].options.method, 'GET');
});

test('upload reports a duplicate in-flight request as recoverable processing state', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({
    ok: false, status: 409, json: async () => ({ detail: '同一上传请求仍在处理中，请稍后检查上传状态' }),
  }));
  await assert.rejects(h.api.upload(new Blob(['test file']), undefined, 'upload-request-123'), error => {
    assert.equal(error.status, 409);
    assert.equal(error.code, 'UPLOAD_PROCESSING');
    assert.match(error.message, /处理中/);
    return true;
  });
});

test('upload status lookup preserves 404 when the running backend lacks recovery support', async () => {
  const h = createHarness({}, {}, () => Promise.resolve({
    ok: false, status: 404, json: async () => ({ detail: 'Not Found' }),
  }));
  await assert.rejects(h.api.getUploadStatus('upload-request-123'), error => {
    assert.equal(error.status, 404);
    return true;
  });
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
