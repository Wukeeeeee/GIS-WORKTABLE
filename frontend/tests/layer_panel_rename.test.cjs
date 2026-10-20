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
  const backend = {
    registerLayer(name) { registered.push(['register', name]); return Promise.resolve(); },
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
  return { layers: window.GIS.layers, tbody, nameElement, registered, mapRenames, stateRenames };
}

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
