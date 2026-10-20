const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const elements = new Map();

class Element {
  constructor(id = '') {
    this.id = id;
    this.value = '';
    this.options = [];
    this.style = { removeProperty() {} };
    this.listeners = {};
    this.dataset = {};
    this.classList = { remove() {}, add() {}, toggle() {} };
  }
  set innerHTML(value) {
    this._innerHTML = value;
    this.options = [{ value: '', selected: true }];
    this.value = '';
    for (const [, id] of value.matchAll(/\bid="([^"]+)"/g)) {
      if (!elements.has(id)) elements.set(id, new Element(id));
    }
    if (value.includes('class="spatial-panel"')) {
      this.root = this;
      this.toolbar = new Element();
    }
  }
  get innerHTML() { return this._innerHTML || ''; }
  appendChild(child) {
    this.children ||= [];
    this.children.push(child);
    if (child.tagName === 'option') this.options.push(child);
    if (child.selected || (!this.value && child.value)) this.value = child.value;
  }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  getAttribute(name) { return name === 'data-at-suffix' ? this.suffix : null; }
  setAttribute(name, value) { if (name === 'data-at-suffix') this.suffix = value; }
  removeAttribute() {}
  querySelector(selector) {
    if (selector === '.spatial-panel') return this.root || null;
    if (selector === '.spatial-toolbar') return this.toolbar;
    if (selector === '.spatial-toolbar-title') return new Element();
    if (selector[0] === '#') return elements.get(selector.slice(1)) || null;
    return null;
  }
  closest() { return null; }
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, width: 0 }; }
}

test('analysis tool field selector includes properties present after the first feature', async () => {
  const document = {
    documentElement: new Element('html'),
    createElement(tag) { const el = new Element(); el.tagName = tag; return el; },
    getElementById(id) { return elements.get(id) || null; },
    querySelector() { return null; },
    addEventListener() {},
    removeEventListener() {},
  };
  const features = [
    { properties: { population: null, district: 'A' } },
    { properties: { population: 125, late_field: 'available later' } },
  ];
  const window = {
    innerWidth: 1280,
    innerHeight: 800,
    addEventListener() {},
    GIS: {
      api: { BASE_URL: '' },
      layers: {
        getLayerNames() { return ['Districts']; },
        getLayerByName(name) { return name === 'Districts' ? { geojson: { features } } : null; },
      },
    },
  };
  const fetch = () => Promise.resolve({ json: () => Promise.resolve({ names: [] }) });
  const sourcePath = path.resolve(__dirname, '../js/analysis_tools.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, fetch, Promise, Array, Object, String, Number, Math, Date, Set, Map,
    alert() {}, console,
  }, { filename: sourcePath });

  const panel = window.GIS.analysisTools.openWith('regression');
  const suffix = 'regression';
  const layerSelect = panel.root.querySelector('#atLayer-' + suffix);
  layerSelect.value = 'Districts';

  await new Promise(resolve => setImmediate(resolve));

  const fieldValues = panel.root.querySelector('#atField1-' + suffix).options.map(option => option.value);
  assert.ok(fieldValues.includes('population'));
  assert.ok(fieldValues.includes('late_field'));
  assert.equal(panel.root.querySelector('#atField1-' + suffix).value, 'population');
});
