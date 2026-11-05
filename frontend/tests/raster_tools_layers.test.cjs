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

function loadRasterTools(features, registeredNames, extras) {
  extras = extras || {};
  const ids = [
    'rasterToolsPanelWrapper', 'rasterToolsPanelContainer', 'rasterToolsPanel', 'rasterToolsToolbar',
    'rasterToolsBody', 'rasterToolsClose', 'rtOp', 'rtLayer', 'rtLayerField', 'rtLayerLabel',
    'rtIntervalField', 'rtBandsField', 'rtExpressionField', 'rtFieldField', 'rtHydroField',
    'rtCoordsField', 'rtWeightField', 'rtLayerText', 'rtFieldSel', 'rtWeightSel', 'rtRun',
    'rtInterval', 'rtResult', 'rtResultBody',
  ];
  const elements = new Map(ids.map(id => [id, makeElement(id === 'rtOp' || id === 'rtLayer' || id === 'rtFieldSel' || id === 'rtWeightSel')]));
  elements.get('rtOp').value = 'slope';
  elements.get('rtLayer').value = 'local-grid';
  elements.get('rtInterval').value = '10';
  const fieldLabel = makeElement();
  fieldLabel.textContent = '插值字段（数值）';
  elements.get('rtFieldSel').parentElement = { querySelector() { return fieldLabel; } };
  const workspace = extras.workspace !== undefined ? extras.workspace : {
    preparePanel() {}, expandPanel() {}, centerPanel() { return [0, 0]; },
    toolPending() {}, toolFeedback() { return true; },
  };
  const layer = { geojson: { type: 'FeatureCollection', features: features || [{ properties: { elevation: 123, category: 'hill' } }] } };
  const window = { GIS: {
    workspace,
    api: Object.assign({ BASE_URL: '' }, extras.api || {}),
    chat: extras.chat || undefined,
    project: extras.project || undefined,
    state: {
      layerOptionEntries(names) {
        const counts = new Map(), seen = new Map();
        names.forEach(name => counts.set(name.normalize('NFC'), (counts.get(name.normalize('NFC')) || 0) + 1));
        return names.map(value => {
          const key = value.normalize('NFC');
          const occurrence = (seen.get(key) || 0) + 1;
          seen.set(key, occurrence);
          const suffix = counts.get(key) > 1 ? ' (' + occurrence + ')' : '';
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
    window, document, fetch: extras.fetch || function(url) {
      return registeredNames
        ? Promise.resolve({ json: () => Promise.resolve({ names: registeredNames }) })
        : Promise.reject(new Error('offline'));
    },
    console, Promise, Array, Object, String, Number, Math, Date, Set, Map, isFinite, parseFloat, parseInt,
  };
  const sourcePath = path.resolve(__dirname, '../js/raster_tools.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return { tools: window.GIS.rasterTools, elements, fieldLabel, window };
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


test('raster tool execution failure reports error to feedback and avoids applying results', async () => {
  let feedbackCall = null;
  let applied = false;
  const harness = loadRasterTools(undefined, ['local-grid'], {
    workspace: {
      preparePanel() {}, expandPanel() {}, centerPanel() { return [0, 0]; },
      toolPending() {},
      toolFeedback(panel, res, err) { feedbackCall = { panel, res, err }; return false; },
    },
    api: {
      invokeTool() {
        return Promise.resolve({ ok: false, busy: true, error: '当前 GIS 正在处理另一项任务，请稍后重试' });
      },
    },
    chat: {
      applyToolResult() { applied = true; },
    },
  });
  harness.tools.openWith('slope');
  await new Promise(resolve => setImmediate(resolve));

  const runBtn = harness.elements.get('rtRun');
  runBtn.listeners.click[0]();
  assert.equal(runBtn.disabled, true, 'run button is locked during execution');

  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(runBtn.disabled, false, 'run button is unlocked after failure');
  assert.equal(applied, false, 'failed tool result is never applied');
  assert.ok(feedbackCall, 'toolFeedback was invoked');
  assert.equal(feedbackCall.panel, 'rasterToolsPanel');
  assert.equal(feedbackCall.res, null);
  assert.equal(feedbackCall.err.message, '当前 GIS 正在处理另一项任务，请稍后重试');
});

test('raster tool execution failure in non-workspace mode sets execution failure message', async () => {
  let applied = false;
  const harness = loadRasterTools(undefined, ['local-grid'], {
    workspace: null,
    api: {
      invokeTool() {
        return Promise.resolve({ ok: false, response: 'DEM 栅格无效' });
      },
    },
    chat: {
      applyToolResult() { applied = true; },
    },
  });
  harness.tools.openWith('slope');
  await new Promise(resolve => setImmediate(resolve));

  const runBtn = harness.elements.get('rtRun');
  runBtn.listeners.click[0]();

  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(applied, false, 'failed tool result is not applied');
  assert.equal(runBtn.disabled, false);
  assert.equal(harness.elements.get('rtResultBody').textContent, '执行失败: DEM 栅格无效');
  assert.equal(harness.elements.get('rtResult').style.display, '');
});

test('raster tool successful run refreshes layer list and re-enables run button', async () => {
  let layerFetchCount = 0;
  let applied = false;
  const harness = loadRasterTools(undefined, ['local-grid'], {
    fetch(url) {
      if (String(url).includes('/api/layers/names')) {
        layerFetchCount += 1;
        return Promise.resolve({ json: () => Promise.resolve({ names: ['local-grid', 'new_contour'] }) });
      }
      return Promise.reject(new Error('offline'));
    },
    api: {
      invokeTool() {
        return Promise.resolve({ ok: true, response: '已生成等高线', layers: ['new_contour'] });
      },
    },
    chat: {
      applyToolResult() { applied = true; },
    },
  });
  harness.tools.openWith('contour');
  await new Promise(resolve => setImmediate(resolve));
  const initialFetchCount = layerFetchCount;

  const runBtn = harness.elements.get('rtRun');
  runBtn.listeners.click[0]();

  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(applied, true, 'successful result was applied');
  assert.equal(runBtn.disabled, false);
  assert.ok(layerFetchCount > initialFetchCount, 'layers were refreshed after successful execution');
});
