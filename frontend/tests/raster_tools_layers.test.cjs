const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function makeElement(isSelect = false) {
  const listeners = {};
  const element = {
    listeners, style: {}, dataset: {}, children: [], options: [], parentElement: null,
    addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
    appendChild(child) {
      this.children.push(child);
      if (isSelect) {
        this.options.push(child);
        if (child.selected) this.value = child.value;
      }
      child.parentElement = this;
      return child;
    },
    querySelector() { return makeElement(); },
    querySelectorAll() { return []; },
    set innerHTML(_value) { this.children = []; if (isSelect) { this.options = []; this.value = ''; } },
    get innerHTML() { return ''; },
  };
  return element;
}

function loadRasterTools(features, registeredNames) {
  const ids = [
    'rasterToolsPanelWrapper', 'rasterToolsPanelContainer', 'rasterToolsPanel', 'rasterToolsToolbar',
    'rasterToolsBody', 'rasterToolsClose', 'rtOp', 'rtLayer', 'rtLayerField', 'rtLayerLabel',
    'rtIntervalField', 'rtBandsField', 'rtExpressionField', 'rtFieldField', 'rtHydroField',
    'rtCoordsField', 'rtWeightField', 'rtLayerText', 'rtFieldSel', 'rtWeightSel', 'rtRun',
  ];
  const elements = new Map(ids.map(id => [id, makeElement(id === 'rtOp' || id === 'rtLayer' || id === 'rtFieldSel' || id === 'rtWeightSel')]));
  elements.get('rtOp').value = 'slope';
  elements.get('rtLayer').value = 'local-grid';
  const fieldLabel = makeElement();
  fieldLabel.textContent = '插值字段（数值）';
  elements.get('rtFieldSel').parentElement = { querySelector() { return fieldLabel; } };
  const workspace = { preparePanel() {}, expandPanel() {}, centerPanel() { return [0, 0]; } };
  const layer = { geojson: { type: 'FeatureCollection', features: features || [{ properties: { elevation: 123, category: 'hill' } }] } };
  const window = { GIS: {
    workspace,
    api: { BASE_URL: '' },
    state: {
      layerOptionEntries(names) {
        const counts = new Map(), seen = new Map();
        names.forEach(name => counts.set(name.normalize('NFC'), (counts.get(name.normalize('NFC')) || 0) + 1));
        return names.map(value => {
          const key = value.normalize('NFC');
          const occurrence = (seen.get(key) || 0) + 1;
          seen.set(key, occurrence);
          const suffix = counts.get(key) > 1 ? ` (${occurrence})` : '';
          return { value, suffix };
        });
      },
    },
    layers: {
      getLayerNames() { return ['local-grid']; },
      getLayerByName(name) { return name === 'local-grid' ? layer : null; },
    },
  }, innerWidth: 1200, innerHeight: 800 };
  const document = {
    documentElement: { appendChild() {} },
    getElementById(id) { return elements.get(id) || null; },
    createElement(tag) { return makeElement(tag === 'option'); },
    querySelector() { return null; },
    addEventListener() {}, removeEventListener() {},
  };
  const context = {
    window, document, fetch() {
      return registeredNames
        ? Promise.resolve({ json: () => Promise.resolve({ names: registeredNames }) })
        : Promise.reject(new Error('offline'));
    },
    console, Promise, Array, Object, String, Number, Math, Date, Set, Map, isFinite, parseFloat, parseInt,
  };
  const sourcePath = path.resolve(__dirname, '../js/raster_tools.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return { tools: window.GIS.rasterTools, elements, fieldLabel };
}

test('raster layer-name fallback keeps the selected layer and refreshes its numeric fields', async () => {
  const harness = loadRasterTools();
  harness.tools.openWith('interpolate');
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(harness.elements.get('rtLayer').value, 'local-grid');
  assert.ok(harness.elements.get('rtFieldSel').options.some(option => option.value === 'elevation'));
  assert.ok(!harness.elements.get('rtFieldSel').options.some(option => option.value === 'category'));
});

test('raster layer selector labels legacy Unicode aliases while preserving exact values', async () => {
  const harness = loadRasterTools(undefined, ['é.geojson', 'e\u0301.geojson']);
  harness.tools.openWith('slope');
  await new Promise(resolve => setImmediate(resolve));

  const aliases = harness.elements.get('rtLayer').options.filter(option => option.value.includes('geojson'));
  assert.deepEqual(aliases.map(option => [option.value, option.textContent]), [
    ['é.geojson', 'é.geojson (1)'],
    ['e\u0301.geojson', 'e\u0301.geojson (2)'],
  ]);
});

test('split fields include categorical properties from later features and retain selection', async () => {
  const harness = loadRasterTools([
    { properties: {} },
    { properties: { zone: 'north', population: 12 } },
    { properties: { zone: 'south', population: 18 } },
  ]);
  harness.tools.openWith('split');
  await new Promise(resolve => setImmediate(resolve));

  const fieldSelect = harness.elements.get('rtFieldSel');
  assert.ok(fieldSelect.options.some(option => option.value === 'zone'));
  assert.ok(fieldSelect.options.some(option => option.value === 'population'));
  fieldSelect.value = 'zone';
  harness.elements.get('rtLayer').listeners.change[0]();
  assert.equal(fieldSelect.value, 'zone');
  assert.equal(harness.fieldLabel.textContent, '拆分字段');
});

test('interpolation only offers numeric fields found anywhere in the feature collection', async () => {
  const harness = loadRasterTools([
    { properties: { category: 'hill' } },
    { properties: { elevation: 123 } },
  ]);
  harness.tools.openWith('interpolate');
  await new Promise(resolve => setImmediate(resolve));

  const fieldSelect = harness.elements.get('rtFieldSel');
  assert.ok(fieldSelect.options.some(option => option.value === 'elevation'));
  assert.ok(!fieldSelect.options.some(option => option.value === 'category'));
  assert.equal(harness.fieldLabel.textContent, '插值字段（数值）');
});
