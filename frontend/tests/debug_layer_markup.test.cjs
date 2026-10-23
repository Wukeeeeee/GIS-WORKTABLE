const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor(id = '') { this.id = id; this.style = {}; this.listeners = {}; this.className = ''; }
  set innerHTML(value) {
    this._innerHTML = value;
    for (const [, id] of value.matchAll(/\bid="([^"]+)"/g)) {
      if (!elements.has(id)) elements.set(id, new Element(id));
    }
  }
  get innerHTML() { return this._innerHTML || ''; }
  get firstElementChild() { return elements.get('debugPanel') || null; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  appendChild(child) { child.parentNode = this; }
  removeEventListener() {}
  fire(name) { return Promise.all((this.listeners[name] || []).map(callback => callback.call(this))); }
  getAttribute(name) { return name === 'data-layer' ? this.layer : null; }
}

let elements;

function loadDebug(options = {}) {
  elements = new Map();
  const documentListeners = {};
  const intervals = [], samples = [], added = [];
  const sampleButton = new Element(); sampleButton.layer = 'points';
  const document = {
    body: new Element('body'),
    createElement() { return new Element(); },
    getElementById(id) { return elements.get(id) || null; },
    querySelector() { return null; },
    querySelectorAll(selector) { return selector === '.debug-load-sample' ? [sampleButton] : []; },
    addEventListener(name, callback) { documentListeners[name] = callback; },
  };
  const unsafeName = 'roads"><img src=x onerror=alert(1)>';
  const unsafeType = 'Point</div><script>alert(2)</script>';
  const window = { GIS: { api: {
    request(endpoint) {
      if (endpoint === '/api/layers' && options.layers) return options.layers();
      if (endpoint === '/api/layers') return Promise.resolve({ layers: [{
        name: unsafeName,
        geojson: { features: [{ geometry: { type: unsafeType } }] },
      }] });
      return Promise.resolve({ logs: [] });
    },
    healthCheck() { return options.health ? options.health() : Promise.resolve({ status: 'ok' }); },
  }, map: {loadGeoJSON(data, name) { samples.push({data, name}); }}, layers: {addLayer(layer) {added.push(layer);}} } };
  const sourcePath = path.resolve(__dirname, '../js/debug.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, GIS: window.GIS, document, localStorage: { getItem() { return ''; } },
    Promise, Array, Object, String, Number, Math, Date, Set, Map,
    setTimeout() { return 1; }, setInterval(callback) { intervals.push(callback); return intervals.length; }, clearInterval() {}, console,
  }, { filename: sourcePath });

  documentListeners.DOMContentLoaded();
  return {window, intervals, sampleButton, samples, added, element(id) {return elements.get(id);}};
}

test('debug layer list escapes untrusted layer names and geometry types', async () => {
  const {window, element} = loadDebug();
  window.GIS.debug.toggle();
  await new Promise(resolve => setImmediate(resolve));

  const markup = element('debugLayerList').innerHTML;
  assert.ok(markup.includes('&lt;img'), markup);
  assert.ok(markup.includes('&lt;script&gt;'), markup);
  assert.equal(markup.includes('<img src=x'), false);
  assert.equal(markup.includes('<script>alert(2)</script>'), false);
  window.GIS.debug.toggle();
});

for (const response of [{ok: false, status: 503}, null, {}]) test(`debug reports an unsuccessful health result as offline: ${JSON.stringify(response)}`, async () => {
  const h = loadDebug({health: async () => response}); h.window.GIS.debug.toggle();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(h.element('debugBackendStatus').textContent, /未连接/);
  assert.match(h.element('debugConnStatus').className, /conn-fail/);
  h.window.GIS.debug.toggle();
});

test('debug refresh checks connectivity again instead of leaving an old online status', async () => {
  let online = true;
  const h = loadDebug({health: async () => online ? {status: 'ok'} : {ok: false}});
  h.window.GIS.debug.toggle(); await new Promise(resolve => setImmediate(resolve));
  assert.match(h.element('debugBackendStatus').textContent, /在线/);
  online = false; h.intervals[0](); await new Promise(resolve => setImmediate(resolve));
  assert.match(h.element('debugBackendStatus').textContent, /未连接/);
  h.window.GIS.debug.toggle();
});

test('old layer and health responses from before close cannot overwrite a reopened panel', async () => {
  const layers = [], health = [];
  const h = loadDebug({layers: () => new Promise(resolve => layers.push(resolve)), health: () => new Promise(resolve => health.push(resolve))});
  h.window.GIS.debug.toggle(); h.window.GIS.debug.toggle(); h.window.GIS.debug.toggle();
  layers[1]({layers: [{name: 'new', geojson: {type: 'Feature', geometry: {type: 'Point'}}}]});
  health[1]({status: 'ok'}); await new Promise(resolve => setImmediate(resolve));
  layers[0]({layers: []}); health[0]({ok: false}); await new Promise(resolve => setImmediate(resolve));
  assert.match(h.element('debugLayerList').innerHTML, /new/);
  assert.match(h.element('debugBackendStatus').textContent, /在线/);
  h.window.GIS.debug.toggle();
});

test('layer summaries tolerate null features and prototype-like geometry names', async () => {
  const h = loadDebug({layers: async () => ({layers: [null, {name: 'data', geojson: {features: [null, {geometry: {type: '__proto__'}}]}}]})});
  h.window.GIS.debug.toggle(); await new Promise(resolve => setImmediate(resolve));
  assert.match(h.element('debugLayerList').innerHTML, /1 __proto__/);
  assert.equal(h.element('debugLayerCount').textContent, 1);
  h.window.GIS.debug.toggle();
});

test('repeated sample loads keep independent map identities and data objects', async () => {
  const h = loadDebug();
  await h.sampleButton.fire('click'); await h.sampleButton.fire('click');
  assert.equal(h.samples.length, 2); assert.notEqual(h.samples[0].name, h.samples[1].name);
  assert.notEqual(h.samples[0].data, h.samples[1].data);
  assert.equal(h.added[0]._rawName, h.samples[0].name);
  assert.equal(h.added[1]._rawName, h.samples[1].name);
  assert.deepEqual(Object.keys(h.window.GIS.debug), ['toggle']);
});
