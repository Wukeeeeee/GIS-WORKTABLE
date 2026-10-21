const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function createHarness(initialStorage = {}, backendSettings = { providers: [] }) {
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
    if (!options.method) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(structuredClone(backendSettings)) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'ok' }) });
  };
  const sourcePath = path.resolve(__dirname, '../js/api.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, GIS: window.GIS, document, localStorage, fetch, Promise, Array, Object, String,
    Number, Math, Date, JSON, Set, Map, Blob, URL, AbortController, setTimeout, clearTimeout,
    requestAnimationFrame() {}, console: { warn() {}, log() {} },
  }, { filename: sourcePath });
  return { api: window.GIS.api, requests, storage };
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
