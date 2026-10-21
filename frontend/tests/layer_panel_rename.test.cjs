const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function makeElement() {
  const listeners = {};
  const children = [];
  return {
    dataset: {}, style: {}, classList: { add() {}, remove() {}, contains() { return false; } },
    listeners, children,
    addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
    appendChild(child) { children.push(child); child.parentNode = this; return child; },
    removeChild(child) { const index = children.indexOf(child); if (index >= 0) children.splice(index, 1); },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    setAttribute() {}, focus() {}, select() {},
    blur() { (listeners.blur || []).forEach(callback => callback()); },
    fire(name, event) { (listeners[name] || []).forEach(callback => callback(event)); },
    set textContent(value) { this._textContent = value; children.splice(0); },
    get textContent() { return this._textContent || ''; },
  };
}

function loadLayerPanel() {
  const tbody = makeElement();
  const nameElement = makeElement();
  nameElement.dataset.id = 'layer-1';
  const elements = {
    layerTbody: tbody,
    layersTable: makeElement(),
    layersEmpty: makeElement(),
  };
  const registered = [];
  const mapRenames = [];
  const stateRenames = [];
  const stateLayer = { fidIndex: {} };
  let failRegistration = false;
  const backend = {
    registerLayer(name) {
      if (failRegistration) return Promise.reject(new Error('offline'));
      registered.push(['register', name]); return Promise.resolve();
    },
    unregisterLayer(name) { registered.push(['unregister', name]); return Promise.resolve(); },
  };
  const map = {
    setLayerColor() {}, getLayer() { return null; },
    renameLayer(oldName, newName) { mapRenames.push([oldName, newName]); },
  };
  const state = { renameLayer(id, name) { stateRenames.push([id, name]); } };
  const document = {
    readyState: 'loading',
    body: { appendChild(element) { if (element.id) elements[element.id] = element; } },
    addEventListener() {},
    getElementById(id) { return elements[id] || null; },
    querySelector(selector) { return selector === '.layer-name[data-id="layer-1"]' ? nameElement : null; },
    createElement(tag) { return makeElement(tag); },
  };
  const window = { GIS: { map, state, api: backend } };
  const context = { window, document, console, Promise, Set, Map, Math, Date, Array, Object, String, Number, JSON };
  const sourcePath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  window.GIS.layers.init();
  window.GIS.layers.addLayer({
    layer_id: 'layer-1', filename: 'Original', geojson: { type: 'FeatureCollection', features: [] },
  });
  state.getLayer = id => id === 'layer-1' ? stateLayer : null;
  return { layers: window.GIS.layers, tbody, nameElement, registered, mapRenames, stateRenames, stateLayer,
    state, backend, failRegistration(value) { failRegistration = value; } };
}

test('attribute data synchronization updates shared identity index and backend registration', async () => {
  const harness = loadLayerPanel();
  const data = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { id: 'a', name: 'A' }, geometry: { type: 'Point', coordinates: [120, 30] } },
    { type: 'Feature', properties: { id: 'b', name: 'B' }, geometry: { type: 'Point', coordinates: [121, 31] } },
  ] };
  const synced = await harness.layers.syncLayerData('layer-1', data);
  assert.equal(synced, true);
  assert.deepEqual(data.features.map(feature => feature.properties._fid), ['id:a', 'id:b']);
  assert.equal(harness.stateLayer.geojson, data);
  assert.equal(harness.stateLayer.featureCount, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.stateLayer.bbox)), [120, 30, 121, 31]);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.stateLayer.fidIndex)), { 'id:a': 0, 'id:b': 1 });
  assert.deepEqual(JSON.parse(JSON.stringify(harness.registered)), [['register', 'Original'], ['register', 'Original']]);
});

test('attribute table edits keep existing number and boolean property types', () => {
  const harness = loadLayerPanel();
  assert.equal(harness.layers.coerceAttributeValue(4, '12'), 12);
  assert.equal(typeof harness.layers.coerceAttributeValue(4, '12'), 'number');
  assert.equal(harness.layers.coerceAttributeValue(true, 'false'), false);
  assert.equal(harness.layers.coerceAttributeValue('0012', '0013'), '0013');
});

test('failed backend sync is reported as a failed layer sync', async () => {
  const harness = loadLayerPanel();
  harness.failRegistration(true);
  const result = await harness.layers.syncLayerData('layer-1', { type: 'FeatureCollection', features: [] });
  assert.equal(result, false);
});

test('same display names get distinct backend registration names instead of overwriting', () => {
  const harness = loadLayerPanel();
  harness.state.getLayer = undefined;
  harness.layers.addLayer({ layer_id: 'layer-2', filename: 'Original',
    geojson: { type: 'FeatureCollection', features: [] } });
  assert.deepEqual(JSON.parse(JSON.stringify(harness.layers.getLayers().map(layer => layer.filename))), ['Original', 'Original(1)']);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.registered)), [
    ['register', 'Original'], ['register', 'Original(1)'],
  ]);
});

test('AI layer operations do not resolve partial names to the first similar layer', () => {
  const harness = loadLayerPanel();
  harness.state.getLayer = undefined;
  harness.layers.addLayer({ layer_id: 'layer-2', filename: 'Original points',
    geojson: { type: 'FeatureCollection', features: [] } });

  assert.equal(harness.layers.clearSymbology('Original point'), false);
  assert.equal(harness.layers.clearSymbology('Original points'), true);
});

test('deleting a layer keeps its unregister request visible to project autosave', async () => {
  const harness = loadLayerPanel();
  harness.state.getLayer = undefined;
  let finishUnregister;
  harness.backend.unregisterLayer = name => {
    harness.registered.push(['unregister', name]);
    return new Promise(resolve => { finishUnregister = resolve; });
  };
  harness.layers.removeLayer('layer-1');
  let finished = false;
  const pending = harness.layers.waitForRegistrySync().then(results => { finished = true; return results; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(finished, false, 'autosave must wait until backend deletion completes');
  assert.equal(typeof finishUnregister, 'function');
  finishUnregister({ success: true });
  assert.deepEqual(JSON.parse(JSON.stringify(await pending)), [{ success: true }]);
  assert.equal(finished, true);
  assert.equal(harness.layers.getLayers().length, 0);
});

test('double-click rename synchronizes panel, map, shared state, and backend registration', async () => {
  const harness = loadLayerPanel();
  harness.tbody.fire('dblclick', { target: { closest: selector => selector === '.layer-name' ? harness.nameElement : null } });
  const input = harness.nameElement.children[0];
  assert.ok(input, 'double-click should open the shared rename editor');
  input.value = 'Renamed';
  input.fire('keydown', { key: 'Enter', preventDefault() {} });
  await new Promise(resolve => setImmediate(resolve));

  const layer = harness.layers.getLayers()[0];
  assert.equal(layer.filename, 'Renamed');
  assert.equal(layer._rawName, 'Renamed');
  assert.deepEqual(harness.mapRenames, [['Original', 'Renamed']]);
  assert.deepEqual(harness.stateRenames, [['layer-1', 'Renamed']]);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.registered)),
    [['register', 'Original'], ['register', 'Renamed'], ['unregister', 'Original']]);
});

test('Escape cancels a rename even if the editor later loses focus', () => {
  const harness = loadLayerPanel();
  harness.tbody.fire('dblclick', { target: { closest: selector => selector === '.layer-name' ? harness.nameElement : null } });
  const input = harness.nameElement.children[0];
  input.value = 'Should not persist';
  input.fire('keydown', { key: 'Escape', preventDefault() {} });
  input.blur();

  assert.equal(harness.layers.getLayers()[0].filename, 'Original');
  assert.deepEqual(harness.mapRenames, []);
  assert.deepEqual(harness.stateRenames, []);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.registered)), [['register', 'Original']]);
});
