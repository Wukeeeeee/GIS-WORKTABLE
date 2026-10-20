const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor() { this.listeners = {}; this.style = {}; this.value = ''; this.textContent = '加载'; this.disabled = false; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  fire(name, event = {}) { (this.listeners[name] || []).forEach(callback => callback.call(this, event)); }
  contains(target) { return target === this; }
}

function createHarness() {
  const elements = new Map(['connectorBtn', 'connectorPanel', 'connectorClose', 'onlineLoadBtn', 'onlineUrl', 'onlineType', 'openOnlineDataBtn']
    .map(id => [id, new Element()]));
  const requests = [];
  const layers = [];
  const alerts = [];
  const window = { GIS: {
    api: { BASE_URL: '' },
    map: { loadGeoJSON() {}, addImageOverlay() {} },
    layers: { addLayer(layer) { layers.push(layer); } },
    chat: { addMessage() {} },
  } };
  const document = {
    readyState: 'loading',
    getElementById(id) { return elements.get(id) || null; },
    addEventListener() {},
  };
  const fetch = (url, options) => new Promise(resolve => requests.push({ url, options, resolve }));
  const sourcePath = path.resolve(__dirname, '../js/connector.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, GIS: window.GIS, document, fetch, alert: message => alerts.push(message), console,
    Promise, JSON, Array, String, Number, Object, Map, Set, Date, encodeURIComponent, setTimeout() { return 1; }, clearTimeout() {},
  }, { filename: sourcePath });
  window.GIS.connector.init();
  elements.get('onlineUrl').value = 'https://example.test/data.fgb';
  return { elements, requests, layers, alerts, panel: elements.get('connectorPanel') };
}

async function flushPromises() {
  await new Promise(resolve => setImmediate(resolve));
  await Promise.resolve();
}

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
