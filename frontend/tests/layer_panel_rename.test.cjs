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
    click() { return this.fire('click'); },
    set textContent(value) { this._textContent = value; children.splice(0); },
    get textContent() { return this._textContent || ''; },
  };
}

function loadLayerPanel() {
  let projectId = 'project-a';
  const tbody = makeElement();
  const nameElement = makeElement();
  nameElement.dataset.id = 'layer-1';
  const elements = {
    layerTbody: tbody,
    layersTable: makeElement(),
    layersEmpty: makeElement(),
    layerInspector: makeElement(),
    inspectorBody: makeElement(),
    inspectorTitle: makeElement(),
    attrDataTable: makeElement(),
    attrFillValue: { value: '' },
  };
  const registered = [];
  const mapRenames = [];
  const mapLoads = [];
  const toastErrors = [];
  const toastWarnings = [];
  const stateRenames = [];
  const createdElements = [];
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
    removeLayer() {},
    loadGeoJSON(data) { mapLoads.push(data); },
    renameLayer(oldName, newName) { mapRenames.push([oldName, newName]); },
  };
  const state = { renameLayer(id, name) { stateRenames.push([id, name]); } };
  const document = {
    readyState: 'loading',
    body: { appendChild(element) { if (element.id) elements[element.id] = element; } },
    addEventListener() {},
    getElementById(id) { return elements[id] || null; },
    querySelector(selector) { return selector === '.layer-name[data-id="layer-1"]' ? nameElement : null; },
    querySelectorAll() { return []; },
    createElement(tag) { const element = makeElement(tag); createdElements.push(element); return element; },
  };
  const window = { GIS: { map, state, api: backend, project: {
    getCurrentProjectId() { return projectId; }, getActiveRegistryProjectId() { return projectId; },
  }, toast: {
    error(message) { toastErrors.push(message); },
    warn(message) { toastWarnings.push(message); },
    success() {},
  } } };
  const context = { window, document, console, Promise, Set, Map, Math, Date, Array, Object, String, Number, JSON,
    CSS: { escape(value) { return String(value).replace(/["\\]/g, '\\$&'); } } };
  const sourcePath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  window.GIS.layers.init();
  window.GIS.layers.addLayer({
    layer_id: 'layer-1', filename: 'Original', geojson: { type: 'FeatureCollection', features: [] },
  });
  state.getLayer = id => id === 'layer-1' ? stateLayer : null;
  return { window, layers: window.GIS.layers, tbody, nameElement, registered, mapRenames, stateRenames, stateLayer,
    state, backend, elements, mapLoads, toastErrors, toastWarnings, createdElements,
    setProjectId(id) { projectId = id; }, failRegistration(value) { failRegistration = value; } };
}

test('restored layer IDs, colors, and opacity cannot inject table markup', () => {
  const harness = loadLayerPanel();
  const importedId = 'imported-layer" onmouseover="alert(1)';
  harness.layers.addLayer({
    layer_id: importedId,
    filename: 'Imported layer',
    color: 'red" onmouseover="alert(2)',
    opacity: '1" onmouseover="alert(3)',
  }, true);

  const html = harness.tbody.innerHTML;
  assert.doesNotMatch(html, /data-id="imported-layer" onmouseover=/);
  assert.doesNotMatch(html, /style="background:red" onmouseover=/);
  assert.match(html, /data-id="imported-layer&quot; onmouseover=&quot;alert\(1\)"/);
  assert.match(html, /style="background:#e74c3c;opacity:1"/);
  assert.equal(harness.layers.getLayers()[1].color, '#e74c3c');
});

test('restored layer IDs cannot inject the attribute inspector toolbar', async () => {
  const harness = loadLayerPanel();
  harness.state.getLayer = null;
  const importedId = 'imported-layer" onmouseover="alert(1)';
  harness.layers.addLayer({
    layer_id: importedId,
    filename: 'Imported layer',
    geojson: { type: 'FeatureCollection', features: [
      { type: 'Feature', properties: { name: 'A' }, geometry: { type: 'Point', coordinates: [120, 30] } },
    ] },
  }, true);

  await harness.layers.showLayerInspector(importedId);
  const html = harness.elements.inspectorBody.innerHTML;
  assert.doesNotMatch(html, /data-layer="imported-layer" onmouseover=/);
  assert.match(html, /data-layer="imported-layer&quot; onmouseover=&quot;alert\(1\)"/);
});

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

test('point coordinate parser accepts zero and rejects incomplete, mixed, non-finite, and out-of-range input', () => {
  const { layers } = loadLayerPanel();
  assert.deepEqual(JSON.parse(JSON.stringify(layers.parseEditedPointCoordinates('0', '0'))), { coordinates: [0, 0] });
  for (const input of [
    ['', '30'], ['120', ''], ['west', '30'], ['120', 'north'],
    ['120abc', '30'], ['Infinity', '30'], ['120', '-Infinity'],
    ['181', '30'], ['-181', '30'], ['120', '90.1'], ['120', '-90.1'],
  ]) {
    assert.ok(layers.parseEditedPointCoordinates(...input).error, `expected rejection for ${input.join(',')}`);
  }
});

test('invalid coordinates report the row and leave every row property and geometry untouched', () => {
  const harness = loadLayerPanel();
  const geojson = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { name: 'first' }, geometry: { type: 'Point', coordinates: [120, 30] } },
    { type: 'Feature', properties: { name: 'second' }, geometry: { type: 'Point', coordinates: [121, 31] } },
  ] };
  harness.layers.getLayers()[0].geojson = geojson;
  const input = (field, value) => ({ dataset: { field }, value, readOnly: false });
  const row = (idx, name, lng, lat) => ({ dataset: { idx: String(idx) }, querySelectorAll() {
    return [input('_经度', lng), input('_纬度', lat), input('name', name)];
  } });
  harness.elements.attrDataTable.querySelectorAll = () => [row(0, 'changed first', '0', '0'), row(1, 'changed second', '120abc', '95')];

  harness.layers.saveAttrChanges('layer-1', ['name']);

  assert.equal(geojson.features[0].properties.name, 'first');
  assert.deepEqual(geojson.features[0].geometry.coordinates, [120, 30]);
  assert.equal(geojson.features[1].properties.name, 'second');
  assert.deepEqual(geojson.features[1].geometry.coordinates, [121, 31]);
  assert.deepEqual(harness.mapLoads, []);
  assert.match(harness.toastErrors[0], /第 2 行坐标无效：经度必须是有限数字/);
});

test('failed backend sync is reported as a failed layer sync', async () => {
  const harness = loadLayerPanel();
  harness.failRegistration(true);
  const result = await harness.layers.syncLayerData('layer-1', { type: 'FeatureCollection', features: [] });
  assert.equal(result, false);
});

test('same display names get distinct backend registration names instead of overwriting', async () => {
  const harness = loadLayerPanel();
  harness.state.getLayer = undefined;
  harness.layers.addLayer({ layer_id: 'layer-2', filename: 'Original',
    geojson: { type: 'FeatureCollection', features: [] } });
  assert.deepEqual(JSON.parse(JSON.stringify(harness.layers.getLayers().map(layer => layer.filename))), ['Original', 'Original(1)']);
  await harness.layers.waitForRegistrySync();
  assert.deepEqual(JSON.parse(JSON.stringify(harness.registered)), [
    ['register', 'Original'], ['register', 'Original(1)'],
  ]);
});

test('layer panel suffixes Unicode normalization aliases when shared state is unavailable', () => {
  const harness = loadLayerPanel();
  harness.state.getLayer = undefined;
  harness.layers.addLayer({ layer_id: 'composed-name', filename: 'é',
    geojson: { type: 'FeatureCollection', features: [] } }, true);
  harness.layers.addLayer({ layer_id: 'decomposed-name', filename: 'e\u0301',
    geojson: { type: 'FeatureCollection', features: [] } }, true);

  assert.deepEqual(
    JSON.parse(JSON.stringify(harness.layers.getLayers().map(layer => layer.filename))),
    ['Original', 'é', 'e\u0301(1)'],
  );
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

test('a user-initiated layer deletion saves the empty layer assignment after backend cleanup', async () => {
  const harness = loadLayerPanel();
  harness.window.GIS.state.getLayer = () => null;
  await harness.layers.waitForRegistrySync();
  let finishUnregister;
  harness.backend.unregisterLayer = () => new Promise(resolve => { finishUnregister = resolve; });
  let savePromise;
  let savedLayerCount;
  harness.window.GIS.project = { autoSave() {
    savePromise = harness.layers.waitForRegistrySync().then(() => {
      savedLayerCount = harness.layers.getLayers().length;
    });
    return savePromise;
  } };

  harness.layers.removeLayer('layer-1');

  await new Promise(resolve => setImmediate(resolve));
  assert.equal(typeof finishUnregister, 'function');
  assert.equal(savedLayerCount, undefined, 'project save must wait for the pending backend unregister');
  finishUnregister({ success: true });
  await savePromise;
  assert.equal(savedLayerCount, 0);
});

test('silent project cleanup does not schedule an intermediate autosave', () => {
  const harness = loadLayerPanel();
  harness.window.GIS.state.getLayer = () => null;
  let saves = 0;
  harness.window.GIS.project = { autoSave() { saves++; return Promise.resolve(); } };

  harness.layers.clearAll(true);

  assert.equal(saves, 0);
});

test('visibility and committed opacity changes are saved to the project', () => {
  const harness = loadLayerPanel();
  let saves = 0;
  harness.window.GIS.project = { autoSave() { saves++; return Promise.resolve(); } };
  harness.state.getLayer = () => null;

  harness.layers.toggleVisibility('layer-1');
  const slider = { dataset: { id: 'layer-1' }, value: '40', closest(selector) {
    return selector === '.layer-row-opacity' ? this : null;
  } };
  harness.tbody.fire('input', { target: slider });
  harness.tbody.fire('change', { target: slider });
  harness.layers.showAll();

  assert.equal(harness.layers.getLayers()[0].visible, true);
  assert.equal(harness.layers.getLayers()[0].opacity, 0.4);
  assert.equal(saves, 3, 'opacity is saved once on commit, not for every drag input');
});

test('dragging a layer to a new panel position schedules an autosave', () => {
  const harness = loadLayerPanel();
  harness.layers.addLayer({ layer_id: 'layer-2', filename: 'Second' }, true);
  let saves = 0;
  harness.window.GIS.project = { autoSave() { saves++; return Promise.resolve(); } };
  const row = index => ({
    dataset: { index: String(index), id: index === 0 ? 'layer-1' : 'layer-2' },
    classList: { add() {}, remove() {}, contains() { return false; } },
  });
  const source = row(0);
  const target = row(1);
  harness.tbody.fire('dragstart', {
    target: { closest(selector) { return selector === 'tr[draggable]' ? source : selector === '.drag-handle' ? {} : null; } },
    dataTransfer: { setData() {}, effectAllowed: '' },
  });
  harness.tbody.fire('drop', {
    preventDefault() {},
    target: { closest(selector) { return selector === 'tr[draggable]' ? target : null; } },
  });

  assert.deepEqual(Array.from(harness.layers.getLayers(), layer => layer.layer_id), ['layer-2', 'layer-1']);
  assert.equal(saves, 1);
});

test('choosing a layer color schedules an autosave after the picker commits', () => {
  const harness = loadLayerPanel();
  let saves = 0;
  harness.window.GIS.project = { autoSave() { saves++; return Promise.resolve(); } };
  const dot = { dataset: { id: 'layer-1', color: '#123456' } };
  harness.tbody.fire('click', { target: { closest(selector) { return selector === '.layer-color-dot' ? dot : null; } } });

  const colorInput = harness.createdElements.find(element => element.type === 'color');
  assert.ok(colorInput);
  colorInput.fire('change');
  assert.equal(saves, 1);
});

test('adding and clearing layer labels updates the saved layer assignment', () => {
  const harness = loadLayerPanel();
  let saves = 0;
  const labelCalls = [];
  harness.window.GIS.project = { autoSave() { saves++; return Promise.resolve(); } };
  harness.window.GIS.map.setLabels = (...args) => { labelCalls.push(['set', ...args]); return true; };
  harness.window.GIS.map.clearLabels = name => labelCalls.push(['clear', name]);

  assert.equal(harness.layers.addLabels('Original', 'district'), true);
  assert.deepEqual(Array.from(labelCalls[0]), ['set', 'Original', 'district', 12, '#333333']);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.layers.getLayers()[0].labels)), {
    field: 'district', fontSize: 12, color: '#333333',
  });
  harness.layers.clearLabels('Original');
  assert.equal(harness.layers.getLayers()[0].labels, undefined);
  assert.equal(saves, 2);
});

test('map cleanup failure does not leave a deleted layer registered for AI tools', async () => {
  const harness = loadLayerPanel();
  harness.state.getLayer = undefined;
  harness.window.GIS.map.removeLayer = () => { throw new Error('map cleanup failed'); };

  harness.layers.removeLayer('layer-1');
  await harness.layers.waitForRegistrySync();

  assert.equal(harness.layers.getLayers().length, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.registered)), [
    ['register', 'Original'], ['unregister', 'Original'],
  ]);
  assert.ok(harness.toastWarnings.some(message => /地图显示清理失败/.test(message)));
});

test('double-click rename synchronizes panel, map, shared state, and backend registration', async () => {
  const harness = loadLayerPanel();
  let saves = 0;
  harness.window.GIS.project = { autoSave() { saves++; return Promise.resolve(); } };
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
  assert.equal(saves, 1, 'renaming a layer should persist its new project assignment');
});

test('Escape cancels a rename even if the editor later loses focus', async () => {
  const harness = loadLayerPanel();
  harness.tbody.fire('dblclick', { target: { closest: selector => selector === '.layer-name' ? harness.nameElement : null } });
  const input = harness.nameElement.children[0];
  input.value = 'Should not persist';
  input.fire('keydown', { key: 'Escape', preventDefault() {} });
  input.blur();
  await harness.layers.waitForRegistrySync();

  assert.equal(harness.layers.getLayers()[0].filename, 'Original');
  assert.deepEqual(harness.mapRenames, []);
  assert.deepEqual(harness.stateRenames, []);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.registered)), [['register', 'Original']]);
});

test('a settled deletion failure stays visible and is retried before saving', async () => {
  const h = loadLayerPanel();
  h.state.getLayer = undefined;
  await h.layers.waitForRegistrySync();
  let ready = false;
  h.backend.unregisterLayer = () => ready ? Promise.resolve({ success: true }) : Promise.reject(new Error('offline'));
  h.layers.removeLayer('layer-1');
  await new Promise(resolve => setImmediate(resolve));
  assert.ok((await h.layers.waitForRegistrySync()).includes(false));
  assert.ok(h.toastErrors.some(message => /保存前将重试/.test(message)));
  ready = true;
  assert.ok((await h.layers.waitForRegistrySync()).every(value => value !== false));
  assert.equal((await h.layers.waitForRegistrySync()).length, 0);
});

test('a false deletion result cannot hide inside a successful batch array', async () => {
  const h = loadLayerPanel();
  h.state.getLayer = undefined;
  await h.layers.waitForRegistrySync();
  h.backend.unregisterLayer = () => Promise.resolve({ success: false });
  h.layers.removeLayer('layer-1');
  assert.ok((await h.layers.waitForRegistrySync()).includes(false));
});

test('failed feature registration can recover on a later synchronization wait', async () => {
  const h = loadLayerPanel();
  await h.layers.waitForRegistrySync();
  h.failRegistration(true);
  assert.equal(await h.layers.syncLayerData('layer-1', { type: 'FeatureCollection', features: [] }), false);
  h.failRegistration(false);
  assert.ok((await h.layers.waitForRegistrySync()).every(value => value !== false));
});

test('feature updates wait for prior registration so an old write cannot finish last', async () => {
  const h = loadLayerPanel();
  await h.layers.waitForRegistrySync();
  const sent = [];
  const complete = [];
  h.backend.registerLayer = (name, data) => {
    sent.push(data.revision);
    return new Promise(resolve => complete.push(resolve));
  };
  const one = h.layers.syncLayerData('layer-1', { type: 'FeatureCollection', features: [], revision: 1 });
  const two = h.layers.syncLayerData('layer-1', { type: 'FeatureCollection', features: [], revision: 2 });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(sent, [1]);
  complete[0]({ success: true });
  await one;
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(sent, [1, 2]);
  complete[1]({ success: true });
  assert.equal(await two, true);
});

test('a new same-name layer registers only after an in-flight old deletion finishes', async () => {
  const h = loadLayerPanel();
  h.state.getLayer = undefined;
  await h.layers.waitForRegistrySync();
  let complete;
  h.backend.unregisterLayer = () => new Promise(resolve => { complete = resolve; });
  h.layers.removeLayer('layer-1');
  await new Promise(resolve => setImmediate(resolve));
  const writes = [];
  h.backend.registerLayer = (name, data) => { writes.push(name); return Promise.resolve({ success: true }); };
  h.layers.addLayer({ layer_id: 'new-layer', filename: 'Original', geojson: { type: 'FeatureCollection', features: [] } });
  const synced = h.layers.waitForRegistrySync();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(writes, []);
  complete({ success: true });
  await synced;
  assert.deepEqual(writes, ['Original']);
});

test('same-tick name reuse cannot delete a replacement layer or deadlock registration', async () => {
  const h = loadLayerPanel();
  h.state.getLayer = undefined;
  h.layers.removeLayer('layer-1');
  h.layers.addLayer({ layer_id: 'replacement', filename: 'Original', geojson: { type: 'FeatureCollection', features: [] } });
  assert.ok((await h.layers.waitForRegistrySync()).every(value => value !== false));
  assert.equal(h.registered.filter(item => item[0] === 'unregister').length, 0);
  assert.equal(h.registered.filter(item => item[0] === 'register').length, 2);
});

test('old-name cleanup after a rename is tracked until it succeeds', async () => {
  const h = loadLayerPanel();
  await h.layers.waitForRegistrySync();
  let ready = false;
  h.backend.unregisterLayer = () => ready ? Promise.resolve({ success: true }) : Promise.reject(new Error('offline'));
  h.tbody.fire('dblclick', { target: { closest: selector => selector === '.layer-name' ? h.nameElement : null } });
  const input = h.nameElement.children[0];
  input.value = 'Renamed'; input.blur();
  assert.ok((await h.layers.waitForRegistrySync()).includes(false));
  assert.equal(h.layers.getLayers()[0]._registeredName, 'Renamed');
  ready = true;
  assert.ok((await h.layers.waitForRegistrySync()).every(value => value !== false));
});

test('a rename editor cannot register a layer after deletion', async () => {
  const h = loadLayerPanel();
  h.state.getLayer = undefined;
  await h.layers.waitForRegistrySync();
  h.tbody.fire('dblclick', { target: { closest: selector => selector === '.layer-name' ? h.nameElement : null } });
  const input = h.nameElement.children[0];
  h.layers.removeLayer('layer-1');
  input.value = 'Ghost'; input.blur();
  await h.layers.waitForRegistrySync();
  assert.equal(h.registered.some(item => item[0] === 'register' && item[1] === 'Ghost'), false);
});

test('repeated blur commits rename only once', async () => {
  const h = loadLayerPanel();
  await h.layers.waitForRegistrySync();
  h.tbody.fire('dblclick', { target: { closest: selector => selector === '.layer-name' ? h.nameElement : null } });
  const input = h.nameElement.children[0];
  input.value = 'Renamed'; input.blur(); input.blur();
  await h.layers.waitForRegistrySync();
  assert.equal(h.registered.filter(item => item[0] === 'register' && item[1] === 'Renamed').length, 1);
});

test('deletion waits for all owned names even when one request fails first', async () => {
  const h = loadLayerPanel();
  h.state.getLayer = undefined;
  await h.layers.waitForRegistrySync();
  h.layers.getLayers()[0]._registrationTokens = { Original: 'one', 'old-owned': 'two' };
  let complete;
  h.backend.unregisterLayer = name => name === 'Original'
    ? Promise.reject(new Error('offline')) : new Promise(resolve => { complete = resolve; });
  h.layers.removeLayer('layer-1');
  let finished = false;
  const pending = h.layers.waitForRegistrySync().then(results => { finished = true; return results; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(finished, false);
  complete({ success: true });
  assert.ok((await pending).includes(false));
});

test('deleting during initial registration preserves the returned version for conditional deletion', async () => {
  const h = loadLayerPanel();
  h.state.getLayer = undefined;
  h.backend.registerLayer = () => Promise.resolve({ success: true, registration_token: 'owned-version' });
  const deletions = [];
  h.backend.unregisterLayer = (name, token) => { deletions.push([name, token]); return Promise.resolve({ success: true }); };
  h.layers.removeLayer('layer-1');
  await h.layers.waitForRegistrySync();
  assert.deepEqual(deletions, [['Original', 'owned-version']]);
});

test('a protected newer registration is reported without retrying its deletion', async () => {
  const h = loadLayerPanel();
  h.state.getLayer = undefined;
  await h.layers.waitForRegistrySync();
  const warnings = [];
  h.window.GIS.toast.warn = message => warnings.push(message);
  let calls = 0;
  h.backend.unregisterLayer = () => { calls++; return Promise.resolve({ success: true, removed: false, stale: true }); };
  h.layers.removeLayer('layer-1');
  await h.layers.waitForRegistrySync();
  await h.layers.waitForRegistrySync();
  assert.equal(calls, 1);
  assert.match(warnings[0], /未删除新版本/);
});

test('tool aliases keep the canonical identity and are versioned during deletion', async () => {
  const h = loadLayerPanel(); h.state.getLayer = undefined;
  await h.layers.waitForRegistrySync();
  h.backend.registerLayer = name => Promise.resolve({success: true, registration_token: name + '-version'});
  const layer = h.layers.getLayers()[0]; layer._registeredName = 'canonical';
  layer._registrationTokens = {canonical: 'canonical-version'};
  assert.equal(await h.layers.syncToolLayer('Original'), true);
  assert.equal(layer._registeredName, 'canonical');
  assert.equal(layer._registrationTokens.Original, 'Original-version');
  const deletions = [];
  h.backend.unregisterLayer = (name, token) => { deletions.push([name, token]); return Promise.resolve({success: true}); };
  h.layers.removeLayer('layer-1'); await h.layers.waitForRegistrySync();
  assert.deepEqual(deletions.sort(), [['Original', 'Original-version'], ['canonical', 'canonical-version']]);
});

test('tool synchronization waits for an earlier edit and participates in the save barrier', async () => {
  const h = loadLayerPanel(); await h.layers.waitForRegistrySync();
  let finish; const calls = [];
  h.backend.registerLayer = (name, data) => { calls.push(data); return calls.length === 1 ? new Promise(resolve => {finish = resolve;}) : Promise.resolve({success: true}); };
  const data = {type: 'FeatureCollection', features: []};
  const edit = h.layers.syncLayerData('layer-1', data);
  const sync = h.layers.syncToolLayer('Original');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 1);
  let saved = false; const barrier = h.layers.waitForRegistrySync().then(() => {saved = true;});
  assert.equal(saved, false);
  finish({success: true}); await Promise.all([edit, sync, barrier]);
  assert.equal(calls.length, 2); assert.equal(calls[1], data); assert.equal(saved, true);
});

test('queued layer registration retains its original project context across a switch', async () => {
  const h = loadLayerPanel(); await h.layers.waitForRegistrySync();
  let finish;
  const registrations = [];
  h.backend.registerLayer = (name, data, _raster, projectId) => {
    registrations.push([name, data, projectId]);
    return registrations.length === 1
      ? new Promise(resolve => { finish = resolve; })
      : Promise.resolve({success: true});
  };
  const data = {type: 'FeatureCollection', features: []};
  const edit = h.layers.syncLayerData('layer-1', data);
  const sync = h.layers.syncToolLayer('Original');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(registrations.length, 1);
  h.setProjectId('project-b');
  finish({success: true});
  await Promise.all([edit, sync]);

  assert.equal(registrations.length, 2);
  assert.deepEqual(registrations.map(row => row[2]), ['project-a', 'project-a']);
});

test('raster tool synchronization uses the same tracked registration and versioned deletion queue', async () => {
  const h = loadLayerPanel(); h.state.getLayer = undefined;
  await h.layers.waitForRegistrySync();
  const layer = h.layers.getLayers()[0];
  layer.geojson = null; layer.raster = {source_asset: 'original.tif', project_id: 'project', bounds: [1, 2, 3, 4]};
  h.backend.registerLayer = (name, geojson, raster) => {
    assert.equal(geojson, null); assert.equal(raster, layer.raster);
    return Promise.resolve({success: true, registration_token: 'raster-current'});
  };
  assert.equal(await h.layers.syncToolLayer('Original'), true);
  const removed = [];
  h.backend.unregisterLayer = (name, token) => {removed.push([name, token]); return Promise.resolve({success: true});};
  h.layers.removeLayer('layer-1'); await h.layers.waitForRegistrySync();
  assert.deepEqual(removed, [['Original', 'raster-current']]);
});
