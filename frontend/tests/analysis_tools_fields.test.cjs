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
      this.root = elements.get([...value.matchAll(/\bid="([^"]+)"/g)][0][1]);
      this.firstElementChild = this.root;
      this.toolbar = new Element();
      this.root.toolbar = this.toolbar;
    }
  }
  get innerHTML() { return this._innerHTML || ''; }
  appendChild(child) {
    this.children ||= [];
    this.children.push(child);
    if (child.tagName === 'option') this.options.push(child);
    if (child.selected) this.value = child.value;
  }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  fire(name) { return Promise.all((this.listeners[name] || []).map(callback => callback.call(this))); }
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

function loadAnalysis(fetchResponse, language = 'zh-CN') {
  elements.clear();
  const listeners = {};
  const document = {
    documentElement: new Element('html'),
    createElement(tag) { const el = new Element(); el.tagName = tag; return el; },
    getElementById(id) { return elements.get(id) || null; },
    querySelector() { return null; },
    addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
    removeEventListener() {},
  };
  const features = [
    { properties: { population: null, district: 'A' } },
    { properties: { population: 125, late_field: 'available later' } },
  ];
  const calls = [], feedback = [], alerts = [], preparedPanels = [];
  const layer = {geojson: {type: 'FeatureCollection', features}};
  const names = ['Districts'];
  const window = {
    innerWidth: 1280,
    innerHeight: 800,
    addEventListener() {},
    GIS: {
      i18n: { t(key, fallback) { return language === 'en' ? 'EN:' + key : fallback; } },
      api: { BASE_URL: '', syncLayer() { return Promise.resolve(); }, invokeTool(tool, args) { calls.push({tool, args}); return Promise.resolve({response: 'done'}); } },
      workspace: {preparePanel(...args) { preparedPanels.push(args); }, expandPanel() {}, centerPanel() {return [0, 0];}, clampPanel(_c, x, y) {return [x, y];}, toolPending() {}, toolFeedback(...args) {feedback.push(args); return !args[2];}},
      layers: {
        getLayerNames() { return names; },
        getLayerByName(name) { return name === 'Districts' ? layer : null; },
      },
    },
  };
  const fetch = fetchResponse || (() => Promise.resolve({ ok: true, json: () => Promise.resolve({ names: [] }) }));
  const sourcePath = path.resolve(__dirname, '../js/analysis_tools.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, fetch, Promise, Array, Object, String, Number, Math, Date, Set, Map,
    alert(message) { alerts.push(message); }, console,
  }, { filename: sourcePath });

  return {window, layer, names, calls, feedback, alerts, preparedPanels, setLanguage(next) {
    language = next;
    (listeners['gis:languagechange'] || []).forEach(callback => callback({detail: {language: next}}));
  }, launcherChildren() {
    const body = elements.get('analysisToolsBody');
    return body && body.children && body.children[0] ? body.children[0].children : [];
  }, open(op) {
    window.GIS._lastMenuOp = op; window.GIS.analysisTools.toggle();
    return elements.get('analysisToolsPanel-' + op);
  }};
}

test('analysis tool launcher localizes its title, groups, and all tool labels', () => {
  const h = loadAnalysis(undefined, 'en');
  h.window.GIS.analysisTools.toggle();

  const children = h.launcherChildren();
  const groups = children.filter(element => element.tagName === 'div');
  const tools = children.filter(element => element.className === 'at-tool-btn');
  assert.equal(groups.length, 4);
  assert.equal(tools.length, 20);
  assert.ok(groups.every(element => element.textContent.startsWith('EN:')));
  assert.ok(tools.every(element => element.textContent.startsWith('EN:')));
  assert.ok(h.preparedPanels.some(args => args[0] === 'analysisToolsPanel' && args[3] === 'EN:tool.analysis-tools'));
});

test('analysis tool launcher follows language changes while it is open', () => {
  const h = loadAnalysis(undefined, 'en');
  h.window.GIS.analysisTools.toggle();
  h.setLanguage('zh-CN');
  assert.ok(h.launcherChildren().every(element => !element.textContent.startsWith('EN:')));
  h.setLanguage('en');
  assert.ok(h.launcherChildren().every(element => element.textContent.startsWith('EN:')));
});

test('analysis tool field selector includes properties present after the first feature', async () => {
  const h = loadAnalysis(); const root = h.open('regression');
  const suffix = 'regression';
  const layerSelect = root.querySelector('#atLayer-' + suffix);
  layerSelect.value = 'Districts';
  await layerSelect.fire('change');

  await new Promise(resolve => setImmediate(resolve));

  const fieldValues = root.querySelector('#atField1-' + suffix).options.map(option => option.value);
  assert.ok(fieldValues.includes('population'));
  assert.ok(fieldValues.includes('late_field'));
  assert.equal(root.querySelector('#atField1-' + suffix).value, '');
  root.querySelector('#atField1-' + suffix).value = 'population';
  h.open('regression');
  assert.equal(root.querySelector('#atField1-' + suffix).value, 'population');
  assert.deepEqual(Object.keys(h.window.GIS.analysisTools), ['toggle']);
});

test('local layer names including prototype keys are available before a slow response', () => {
  const h = loadAnalysis(() => new Promise(() => {}));
  h.names.push('__proto__', 'constructor');
  const root = h.open('regression');
  assert.deepEqual(root.querySelector('#atLayer-regression').options.map(o => o.value), ['', 'Districts', '__proto__', 'constructor']);
});

test('late layer-list responses cannot replace a newer refresh', async () => {
  const responses = [];
  const h = loadAnalysis(() => new Promise(resolve => responses.push(resolve)));
  const root = h.open('regression'); h.open('regression');
  responses[1]({ok: true, json: async () => ({names: ['new']})});
  await new Promise(resolve => setImmediate(resolve));
  responses[0]({ok: true, json: async () => ({names: ['old']})});
  await new Promise(resolve => setImmediate(resolve));
  const names = root.querySelector('#atLayer-regression').options.map(o => o.value);
  assert.ok(names.includes('new')); assert.ok(!names.includes('old'));
});

test('single Feature fields and actual run buttons send the selected regression parameters', async () => {
  const h = loadAnalysis();
  h.layer.geojson = {type: 'Feature', properties: {population: 1, income: 2, _fid: 'hidden'}};
  const root = h.open('regression');
  root.querySelector('#atLayer-regression').value = 'Districts';
  await root.querySelector('#atLayer-regression').fire('change');
  assert.deepEqual(root.querySelector('#atField1-regression').options.map(o => o.value), ['', 'population', 'income']);
  root.querySelector('#atField1-regression').value = 'population';
  root.querySelector('#atIndependents-regression').value = 'income';
  await root.querySelector('#atRun-regression').fire('click');
  assert.equal(h.calls[0].tool, 'spatial_regression');
  assert.equal(h.calls[0].args.dependent, 'population');
  assert.equal(h.calls[0].args.independents, 'income');
});

test('invalid raster source values stop before becoming JSON null', async () => {
  const h = loadAnalysis(); const root = h.open('euclid');
  root.querySelector('#atLayer-euclid').value = 'Districts';
  root.querySelector('#atSourceValue-euclid').value = 'invalid';
  await root.querySelector('#atRun-euclid').fire('click');
  assert.equal(h.calls.length, 0); assert.match(h.alerts[0], /有限数值/);
});

test('tool synchronization failure is returned to the owning panel without running analysis', async () => {
  const h = loadAnalysis(); const root = h.open('geomattrs');
  root.querySelector('#atLayer-geomattrs').value = 'Districts';
  h.window.GIS.api.syncLayer = () => Promise.reject(new Error('offline'));
  await root.querySelector('#atRun-geomattrs').fire('click');
  assert.equal(h.calls.length, 0);
  assert.equal(h.feedback[0][0], 'analysisToolsPanel-geomattrs');
  assert.equal(h.feedback[0][2].message, 'offline');
});
