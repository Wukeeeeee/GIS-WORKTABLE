const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.className = '';
    this.style = {};
    this.disabled = false;
    this._classes = new Set();
    this.classList = {
      add: name => this._classes.add(name),
      remove: name => this._classes.delete(name),
      contains: name => this._classes.has(name),
      toggle: (name, force) => {
        if (force === undefined) force = !this._classes.has(name);
        force ? this._classes.add(name) : this._classes.delete(name);
      },
    };
  }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  get childNodes() { return this.children; }
  set innerHTML(value) { this._innerHTML = value; if (value === '') this.children = []; }
  get innerHTML() { return this._innerHTML || ''; }
}

function createHarness() {
  const ids = ['historyPanel', 'historyBody', 'toggleHistoryPanel', 'toolHistClearBtn', 'toolHistCloseBtn'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const requests = [];
  const messages = [];
  const addedLayers = [];
  const panelLayers = [];
  const syncs = [];
  const rendered = [];
  let autosaves = 0;
  let ready;
  const document = {
    readyState: 'loading',
    getElementById(id) { return elements[id] || null; },
    createElement() { return new Element(); },
    addEventListener(name, callback) { if (name === 'DOMContentLoaded') ready = callback; },
  };
  const window = { GIS: {
    api: { BASE_URL: '' },
    chat: { addMessage(message) { messages.push(message); } },
    state: { addLayer(layer) { addedLayers.push(layer); return layer; } },
    layers: {
      getLayers() { return panelLayers; },
      syncLayerData(id, geojson) { syncs.push([id, geojson]); return Promise.resolve(true); },
    },
    project: { autoSave() { autosaves++; return Promise.resolve(); } },
    map: { loadGeoJSON(...args) { rendered.push(args); } },
  } };
  const fetch = (url, options = {}) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
  const sourcePath = path.resolve(__dirname, '../js/history.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, fetch, Promise, JSON, Array, String, Date, Object, Number, Map, Set,
    navigator: {}, console,
  }, { filename: sourcePath });
  ready();
  return { window, history: window.GIS.history, elements, requests, messages, addedLayers, panelLayers, syncs, rendered,
    getAutoSaves() { return autosaves; } };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function historyResponse(entries) {
  return { ok: true, json: () => Promise.resolve({ history: entries }) };
}

test('late history refresh cannot repopulate the list after clearing it', async () => {
  const h = createHarness();
  h.elements.toggleHistoryPanel.listeners.click[0]();
  assert.equal(h.requests[0].url, '/api/history?limit=50');

  h.elements.toolHistClearBtn.listeners.click[0]();
  assert.equal(h.requests[1].options.method, 'DELETE');
  h.requests[1].resolve({ ok: true });
  await flushPromises();
  assert.match(h.elements.historyBody.children[0].textContent, /暂无记录/);

  h.requests[0].resolve(historyResponse([{ index: 7, tool: 'old result', ok: true, args: {}, time: '' }]));
  await flushPromises();
  assert.equal(h.elements.historyBody.children.length, 1);
  assert.match(h.elements.historyBody.children[0].textContent, /暂无记录/);
});

test('failed history deletion preserves visible records and reports the failure', async () => {
  const h = createHarness();
  h.elements.toggleHistoryPanel.listeners.click[0]();
  h.requests[0].resolve(historyResponse([{ index: 3, tool: 'buffer', ok: true, args: {}, time: '' }]));
  await flushPromises();
  assert.equal(h.elements.historyBody.children.length, 1);

  h.elements.toolHistClearBtn.listeners.click[0]();
  h.requests[1].resolve({ ok: false, status: 500 });
  await flushPromises();

  assert.equal(h.elements.historyBody.children.length, 1);
  assert.match(h.messages[0], /清空处理历史失败/);
});

test('history storage warnings are visible without hiding available records', async () => {
  const h = createHarness();
  h.elements.toggleHistoryPanel.listeners.click[0]();
  h.requests[0].resolve({
    ok: true,
    json: () => Promise.resolve({
      warning: '处理历史文件无法读取；为保留原文件，已暂停写入。',
      history: [{ index: 9, tool: 'buffer', ok: true, args: {}, time: '' }],
    }),
  });
  await flushPromises();

  assert.equal(h.elements.historyBody.children[0].className, 'toolhist-warning');
  assert.match(h.elements.historyBody.children[0].textContent, /已暂停写入/);
  assert.equal(h.elements.historyBody.children.length, 2);
});

test('history rerun keeps the backend layer identity and version token', async () => {
  const h = createHarness();
  h.elements.toggleHistoryPanel.listeners.click[0]();
  h.requests[0].resolve(historyResponse([{ index: 4, tool: 'buffer', ok: true, args: {}, time: '' }]));
  await flushPromises();

  const entry = h.elements.historyBody.children[0];
  const actions = entry.children.find(child => child.className === 'toolhist-item-actions');
  const rerunButton = actions.children.find(child => child.className === 'toolhist-rerun-btn');
  rerunButton.listeners.click[0]();
  assert.equal(h.requests[1].url, '/api/history/rerun');
  h.requests[1].resolve({ ok: true, json: () => Promise.resolve({
    ok: true,
    layers: [{ name: 'roads_buffer', registry_name: 'roads_buffer', registration_token: 'registered-version',
      geojson: { type: 'FeatureCollection', features: [] } }],
    layer_ops: [],
  }) });
  await flushPromises();

  assert.equal(h.addedLayers.length, 1);
  assert.equal(h.addedLayers[0].registry_name, 'roads_buffer');
  assert.equal(h.addedLayers[0].registration_token, 'registered-version');
  assert.equal(h.getAutoSaves(), 1);
});

test('history rerun updates an existing same-name layer instead of duplicating it', async () => {
  const h = createHarness();
  const existing = { layer_id: 'roads-id', filename: 'roads', _registeredName: 'roads', _rawName: 'roads-map',
    _registrationTokens: { roads: 'old-version' }, style: { color: '#123456' } };
  h.panelLayers.push(existing);
  h.elements.toggleHistoryPanel.listeners.click[0]();
  h.requests[0].resolve(historyResponse([{ index: 5, tool: 'buffer', ok: true, args: {}, time: '' }]));
  await flushPromises();

  const entry = h.elements.historyBody.children[0];
  const actions = entry.children.find(child => child.className === 'toolhist-item-actions');
  actions.children.find(child => child.className === 'toolhist-rerun-btn').listeners.click[0]();
  const geojson = { type: 'FeatureCollection', features: [] };
  h.requests[1].resolve({ ok: true, json: () => Promise.resolve({
    ok: true,
    layers: [{ name: 'roads', registry_name: 'roads', registration_token: 'new-version', geojson }],
    layer_ops: [],
  }) });
  await flushPromises();

  assert.equal(h.addedLayers.length, 0);
  assert.equal(h.panelLayers.length, 1);
  assert.deepEqual(h.syncs, [['roads-id', geojson]]);
  assert.equal(h.rendered[0][1], 'roads-map');
  assert.equal(h.rendered[0][2], existing.style);
  assert.equal(h.rendered[0][3].fitBounds, false);
  assert.equal(existing._registrationTokens.roads, 'new-version');
  assert.equal(h.getAutoSaves(), 1);
});

test('history rerun forwards raster preview operations through the shared tool-result handler', async () => {
  const h = createHarness();
  const applied = [];
  h.elements.toggleHistoryPanel.listeners.click[0]();
  h.requests[0].resolve(historyResponse([{ index: 8, tool: 'raster_reclassify', ok: true, args: {}, time: '' }]));
  await flushPromises();

  h.window.GIS.chat.applyToolResult = result => applied.push(result);
  const entry = h.elements.historyBody.children[0];
  const actions = entry.children.find(child => child.className === 'toolhist-item-actions');
  actions.children.find(child => child.className === 'toolhist-rerun-btn').listeners.click[0]();
  const oldOp = { action: 'dem_result', name: 'classes_原.png', layer_name: 'classes_原',
    url: '/output/uploads/classes_原.png', bounds: [100, 30, 101, 31], raster: { source_filename: 'classes_原.tif' } };
  const op = { action: 'dem_result', name: 'classes.png', layer_name: 'classes',
    url: '/output/uploads/classes.png', bounds: [100, 30, 101, 31], raster: { source_filename: 'classes.tif' } };
  h.requests[1].resolve({ ok: true, json: () => Promise.resolve({
    ok: true, response: '已重跑 #8 raster_reclassify → 成功', layers: [], layer_ops: [oldOp, op],
  }) });
  await flushPromises();

  assert.equal(applied.length, 2);
  assert.deepEqual(applied.map(result => result.layer_ops[0]), [oldOp, op]);
});
