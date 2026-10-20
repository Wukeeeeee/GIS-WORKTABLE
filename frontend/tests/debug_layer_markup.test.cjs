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
}

let elements;

test('debug layer list escapes untrusted layer names and geometry types', async () => {
  elements = new Map();
  const documentListeners = {};
  const document = {
    body: new Element('body'),
    createElement() { return new Element(); },
    getElementById(id) { return elements.get(id) || null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener(name, callback) { documentListeners[name] = callback; },
  };
  const unsafeName = 'roads"><img src=x onerror=alert(1)>';
  const unsafeType = 'Point</div><script>alert(2)</script>';
  const window = { GIS: { api: {
    request(endpoint) {
      if (endpoint === '/api/layers') return Promise.resolve({ layers: [{
        name: unsafeName,
        geojson: { features: [{ geometry: { type: unsafeType } }] },
      }] });
      return Promise.resolve({ logs: [] });
    },
    healthCheck() { return Promise.resolve({ ok: true }); },
  } } };
  const sourcePath = path.resolve(__dirname, '../js/debug.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, GIS: window.GIS, document, localStorage: { getItem() { return ''; } },
    Promise, Array, Object, String, Number, Math, Date, Set, Map,
    setTimeout() { return 1; }, setInterval() { return 1; }, clearInterval() {}, console,
  }, { filename: sourcePath });

  documentListeners.DOMContentLoaded();
  window.GIS.debug.show();
  await new Promise(resolve => setImmediate(resolve));

  const markup = document.getElementById('debugLayerList').innerHTML;
  assert.ok(markup.includes('&lt;img'), markup);
  assert.ok(markup.includes('&lt;script&gt;'), markup);
  assert.equal(markup.includes('<img src=x'), false);
  assert.equal(markup.includes('<script>alert(2)</script>'), false);
  window.GIS.debug.hide();
});
