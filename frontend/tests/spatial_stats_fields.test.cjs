const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function makeElement(isSelect = false) {
  const listeners = {};
  const options = [];
  const classes = new Set();
  return {
    listeners, options, dataset: {}, style: {}, children: [], parentElement: null,
    classList: {
      toggle(name, force) { force ? classes.add(name) : classes.delete(name); },
      add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
    },
    addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
    removeEventListener(name, callback) {
      listeners[name] = (listeners[name] || []).filter(item => item !== callback);
    },
    fire(name, event = {}) { return Promise.all((listeners[name] || []).slice().map(callback => callback.call(this, event))); },
    appendChild(child) {
      this.children.push(child);
      if (isSelect) {
        options.push(child);
        if (child.selected) this.value = child.value;
      }
      child.parentElement = this;
      return child;
    },
    set innerHTML(_value) { this.children = []; if (isSelect) { options.splice(0); this.value = ''; } },
    get innerHTML() { return ''; },
    querySelectorAll() { return []; },
    setAttribute() {},
  };
}

function loadSpatialStats() {
  const ids = [
    'spatialStatsPanelWrapper', 'spatialStatsPanelContainer', 'spatialStatsClose', 'spatialStatsPanel',
    'spatialStatsToolbar', 'spatialStatsTabs', 'spatialStatsBody', 'ssMoranWeight', 'ssMoranDistField',
    'ssMoranKnnField', 'ssMoranLayer', 'ssMoranField', 'ssHotspotLayer', 'ssHotspotField', 'ssKdeLayer',
    'ssHotspotDist', 'ssLoader', 'ssMoranDist', 'ssMoranK', 'ssMoranLocal', 'ssKdeBandwidth', 'ssKdeGrid',
  ];
  const selectIds = new Set(['ssMoranLayer', 'ssMoranField', 'ssHotspotLayer', 'ssHotspotField', 'ssKdeLayer']);
  const elements = new Map(ids.map(id => [id, makeElement(selectIds.has(id))]));
  for (const [id, value] of Object.entries({ ssMoranWeight: 'distance', ssMoranDist: '1000', ssMoranK: '5', ssHotspotDist: '1000', ssKdeBandwidth: '', ssKdeGrid: '50' })) elements.get(id).value = value;
  const layer = {
    filename: 'partitions',
    geojson: { type: 'FeatureCollection', features: [
      { properties: { population: null, category: 'A' } },
      { properties: { population: 240, category: 'B', density: 15.5 } },
    ] },
  };
  let layerLookupCount = 0;
  const tabs = ['moran', 'hotspot', 'kde'].map(name => {
    const tab = makeElement(); tab.dataset.tab = name; return tab;
  });
  const contents = ['Moran', 'Hotspot', 'Kde'].map(name => {
    const pane = makeElement(); pane.id = 'stab' + name; return pane;
  });
  const container = elements.get('spatialStatsPanelContainer');
  const runButtons = ['moran', 'hotspot', 'kde'].map(op => {
    const button = makeElement(); button.dataset.op = op; return button;
  });
  container.querySelectorAll = selector => selector === '.spatial-run-btn' ? runButtons : [];
  const wrapper = elements.get('spatialStatsPanelWrapper');
  wrapper.appendChild = child => { child.parentElement = wrapper; };
  const document = {
    documentElement: { appendChild() {} },
    getElementById(id) { return elements.get(id) || null; },
    createElement(tag) { return makeElement(tag === 'option'); },
    querySelectorAll(selector) {
      if (selector === '#spatialStatsTabs .spatial-tab') return tabs;
      if (selector === '#spatialStatsBody .spatial-tab-content') return contents;
      return [];
    },
    querySelector() { return null; },
  };
  const pendingButtons = [], calls = [], feedback = [], alerts = [], applied = [];
  const window = { GIS: {
    workspace: {
      preparePanel() {}, expandPanel() {}, centerPanel() { return [0, 0]; },
      clampPanel(_container, left, top) { return [left, top]; },
      toolPending(_panelId, button) { pendingButtons.push(button); },
      toolFeedback(...args) { feedback.push(args); return !args[2] && args[1]?.ok !== false; },
    },
    api: { syncLayer() { return Promise.resolve(); }, invokeTool(tool, args) { calls.push({tool, args}); return Promise.resolve({ response: 'done' }); } },
    chat: { applyToolResult(result) { applied.push(result); } },
    layers: {
      getLayers() { return [layer]; },
      getLayerByName(name) { layerLookupCount++; return name === 'partitions' ? layer : null; },
    },
  }, innerWidth: 1200, innerHeight: 900 };
  const context = { window, document, console, Set, Map, Math, Number, String, Array, Object, Promise, Date, parseFloat, parseInt, alert(message) { alerts.push(message); } };
  const sourcePath = path.resolve(__dirname, '../js/spatial_stats.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return {
    stats: window.GIS.spatialStats, elements, tabs, runButtons, pendingButtons, calls, feedback, alerts, applied, layer, api: window.GIS.api,
    switchTab(index) { return elements.get('spatialStatsTabs').fire('click', {target: {closest: () => tabs[index]}}); },
    get layerLookupCount() { return layerLookupCount; },
    resetLayerLookupCount() { layerLookupCount = 0; },
  };
}

test('spatial statistics lists numeric fields found after null first-feature values', () => {
  const harness = loadSpatialStats();
  harness.stats.toggle();
  const layerSelect = harness.elements.get('ssMoranLayer');
  layerSelect.value = 'partitions';
  layerSelect.fire('change');

  const fields = harness.elements.get('ssMoranField').options.map(option => option.value);
  assert.ok(fields.includes('population'));
  assert.ok(fields.includes('density'));
  assert.ok(!fields.includes('category'));
});

test('spatial statistics refresh preserves selected field and does not accumulate change handlers', () => {
  const harness = loadSpatialStats();
  harness.stats.toggle();
  const layerSelect = harness.elements.get('ssMoranLayer');
  const fieldSelect = harness.elements.get('ssMoranField');
  layerSelect.value = 'partitions';
  layerSelect.fire('change');
  fieldSelect.value = 'population';

  harness.resetLayerLookupCount();
  harness.stats.toggle(); harness.stats.toggle();
  harness.switchTab(1);
  assert.equal(fieldSelect.value, 'population');
  assert.equal(layerSelect.listeners.change.length, 1);

  harness.resetLayerLookupCount();
  layerSelect.fire('change');
  assert.equal(harness.layerLookupCount, 1);
});

test('spatial statistics retry context tracks the clicked operation button', async () => {
  const harness = loadSpatialStats();
  harness.stats.toggle();
  harness.elements.get('ssHotspotLayer').value = 'partitions';
  harness.runButtons[1].listeners.click[0].call(harness.runButtons[1]);
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(harness.pendingButtons[0], harness.runButtons[1]);
});

test('a failed layer synchronization stops statistics and releases the loading state', async () => {
  const h = loadSpatialStats(); h.stats.toggle();
  h.api.syncLayer = () => Promise.reject(new Error('offline'));
  h.elements.get('ssHotspotLayer').value = 'partitions';
  await h.runButtons[1].fire('click');
  assert.equal(h.calls.length, 0);
  assert.equal(h.feedback[0][2].message, 'offline');
  assert.equal(h.elements.get('ssLoader').style.display, 'none');
});

test('Moran and KDE forward metric parameters from the actual run buttons', async () => {
  const h = loadSpatialStats(); h.stats.toggle();
  h.elements.get('ssMoranLayer').value = 'partitions';
  h.elements.get('ssMoranField').value = 'population';
  await h.runButtons[0].fire('click');
  assert.equal(h.calls[0].tool, 'spatial_moran');
  assert.equal(h.calls[0].args.threshold_m, 1000);
  h.elements.get('ssKdeLayer').value = 'partitions';
  h.elements.get('ssKdeBandwidth').value = '250';
  await h.runButtons[2].fire('click');
  assert.equal(h.calls[1].tool, 'spatial_kde');
  assert.equal(h.calls[1].args.bandwidth_m, 250);
  assert.equal(h.calls[1].args.metric_units, true);
});

for (const value of ['2.5', '0', '-1', '51', 'NaN']) test(`KNN rejects invalid neighbor count ${value} before invoking`, async () => {
  const h = loadSpatialStats(); h.stats.toggle();
  h.elements.get('ssMoranLayer').value = 'partitions';
  h.elements.get('ssMoranWeight').value = 'knn';
  h.elements.get('ssMoranK').value = value;
  await h.runButtons[0].fire('click');
  assert.equal(h.calls.length, 0); assert.equal(h.alerts.length, 1);
});

test('a single Feature exposes finite numeric fields and tab changes refresh edited properties', async () => {
  const h = loadSpatialStats();
  h.layer.geojson = {type: 'Feature', properties: {count: 3, broken: Infinity, label: 'x'}};
  h.stats.toggle();
  h.elements.get('ssMoranLayer').value = 'partitions';
  await h.elements.get('ssMoranLayer').fire('change');
  assert.deepEqual(h.elements.get('ssMoranField').options.map(o => o.value), ['count']);
  h.layer.geojson.properties.newField = 2;
  await h.switchTab(1);
  assert.ok(h.elements.get('ssMoranField').options.some(o => o.value === 'newField'));
  assert.deepEqual(Object.keys(h.stats), ['toggle']);
});
