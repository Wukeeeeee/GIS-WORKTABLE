const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test('a late response from an older project load cannot replace the most recently requested project', async () => {
  const requests = new Map();
  const restoredMessages = [];
  const mapViews = [];
  const capsule = { textContent: '' };
  const chatMessages = { style: {} };
  const chatHistory = { style: {} };
  const document = {
    getElementById(id) {
      return ({
        workspaceCurrentProjectName: capsule,
        chatMessages,
        chatHistory,
      })[id] || null;
    },
  };
  const window = { GIS: {
    api: { loadProject(id) { const req = deferred(); requests.set(id, req); return req.promise; } },
    chat: {
      clear() { restoredMessages.length = 0; },
      addMessage(message) { restoredMessages.push(message); },
    },
    map: { clearAll() {}, setView(center, zoom) { mapViews.push({ center, zoom }); } },
    workspace: { renderRecentProjects() {} },
  } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  const oldLoad = window.GIS.project.loadProject('old-project');
  const latestLoad = window.GIS.project.loadProject('latest-project');
  requests.get('latest-project').resolve({ id: 'latest-project', name: '最新工程', messages: [], layers: [], mapState: { lat: 40, lng: -74, zoom: 8 } });
  assert.equal(await latestLoad, true);
  requests.get('old-project').resolve({ id: 'old-project', name: '旧工程', messages: [], layers: [], mapState: { lat: 10, lng: 20, zoom: 4 } });
  assert.equal(await oldLoad, false);

  assert.equal(window.GIS.project.getCurrentProjectId(), 'latest-project');
  assert.match(window.GIS.project.getCurrentSessionId(), /latest-project/);
  assert.equal(capsule.textContent, '最新工程');
  assert.equal(mapViews.length, 1);
  assert.equal(mapViews[0].center[0], 40);
  assert.equal(mapViews[0].center[1], -74);
  assert.equal(mapViews[0].zoom, 8);
  assert.ok(restoredMessages.some(message => message.includes('最新工程')));
  assert.equal(restoredMessages.some(message => message.includes('旧工程')), false);
});

test('loading a project renders project names and saved user messages as text', async () => {
  const messages = [];
  const capsule = { textContent: '' };
  const document = {
    getElementById(id) { return id === 'workspaceCurrentProjectName' ? capsule : null; },
  };
  const payload = {
    id: 'proj_safe',
    name: '<img src=x onerror=alert(1)>',
    messages: [{ role: 'user', content: '<svg onload=alert(2)>' }],
    layers: [],
    mapState: {},
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: {
      clear() {},
      addMessage(message, type) { messages.push({ message, type }); },
    },
    map: { clearAll() {} },
  } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('proj_safe'), true);
  assert.equal(capsule.textContent, payload.name, 'the project title remains literal text in the title capsule');
  assert.ok(messages.some(item => item.type === 'user' && item.message === '&lt;svg onload=alert(2)&gt;'));
  const restoredNotice = messages.find(item => item.type === 'system');
  assert.ok(restoredNotice.message.startsWith('已恢复工程: &lt;img src=x'), restoredNotice.message);
  assert.equal(restoredNotice.message.includes('<img'), false);
});

test('restoring legacy same-name layers without IDs delegates unique ID creation to the layer registry', async () => {
  const addedLayers = [];
  const payload = {
    id: 'legacy-project', name: '旧工程', messages: [], mapState: {},
    layers: [
      { name: '行政区', geojson: { type: 'FeatureCollection', features: [] } },
      { name: '行政区', geojson: { type: 'FeatureCollection', features: [] } },
    ],
  };
  class FixedDate extends Date { static now() { return 123456789; } }
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage() {} },
    map: { clearAll() {}, loadGeoJSON() {} },
    layers: {
      setGroupState() {}, clearAll() {}, syncLayerOrder() {},
      addLayer(layer) {
        const id = layer.layer_id || ('generated_' + (addedLayers.length + 1));
        addedLayers.push({ ...layer, layer_id: id });
      },
    },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date: FixedDate, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('legacy-project'), true);
  assert.deepEqual(addedLayers.map(layer => layer.layer_id), ['generated_1', 'generated_2']);
});

test('autosave sends stable layer IDs alongside names and display state', async () => {
  let capturedAssignments;
  const window = { GIS: {
    api: { autoSaveProject(_sessionId, _projectId, _groups, assignments) {
      capturedAssignments = assignments;
      return Promise.resolve({ id: 'saved-project' });
    } },
    layers: {
      getLayers() { return [{ layer_id: 'layer-persisted', _registeredName: 'registered',
        _rawName: 'raw', filename: 'display', groupId: 'group_2', visible: false,
        style: { color: '#336699', fillOpacity: 0.24 } }]; },
      getGroupState() { return [{ id: 'group_2', name: 'saved group', collapsed: true }]; },
    },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  await window.GIS.project.autoSave();
  assert.deepEqual(JSON.parse(JSON.stringify(capturedAssignments)), [{
    layer_id: 'layer-persisted', style: { color: '#336699', fillOpacity: 0.24 },
    names: ['registered', 'raw', 'display'],
    groupId: 'group_2', visible: false,
    symbology: null,
  }]);
});

test('project restore forwards saved layer style to the layer registry', async () => {
  const addedLayers = [];
  const payload = {
    id: 'styled-project', name: '样式工程', messages: [], mapState: {},
    layers: [{ layer_id: 'styled-layer', name: '行政区', color: '#336699',
      style: { color: '#336699', fillOpacity: 0.24, opacity: 0.6, weight: 3 },
      geojson: { type: 'FeatureCollection', features: [] } }],
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage() {} },
    map: { clearAll() {}, loadGeoJSON() {} },
    layers: { setGroupState() {}, clearAll() {}, addLayer(layer) { addedLayers.push({ ...layer }); }, syncLayerOrder() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('styled-project'), true);
  assert.deepEqual({ ...addedLayers[0].style }, payload.layers[0].style);
});

test('project restore reapplies saved thematic symbology after registering the layer', async () => {
  const calls = [];
  const snapshot = { enabled: true, type: 'graduated', field: 'population', method: 'quantile',
    classes: 2, breaks: [10, 20, 30], fillOpacity: 0.2,
    featureCount: 1, featureStyleCount: 1,
    featureStyles: { 'fid:adcode:1': { color: '#fed976', fillColor: '#fed976', fillOpacity: 0.2, weight: 1 } },
    legendData: { type: 'graduated', field: 'population', method: 'quantile',
      items: [{ label: '10.00 - 30.00', color: '#fed976' }] }, legendPresentation: 'open' };
  const payload = { id: 'thematic-project', name: '专题图工程', messages: [], mapState: {},
    layers: [{ layer_id: 'thematic-layer', name: '区县', geojson: { type: 'FeatureCollection', features: [] }, symbology: snapshot }] };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage() {} },
    map: { clearAll() {}, loadGeoJSON() {} },
    layers: {
      setGroupState() {}, clearAll() {}, syncLayerOrder() {},
      addLayer() {}, restoreSymbologyState(id, state) { calls.push({ id, state }); },
      getLayers() { return [{ layer_id: 'thematic-layer', filename: '区县' }]; },
    },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('thematic-project'), true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].id, 'thematic-layer');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].state)), snapshot);
});

test('manual and automatic saves capture style changes from the real shared state', async () => {
  let manual;
  let automatic;
  const window = { GIS: {
    api: {
      saveProject(data) { manual = data; return Promise.resolve({ id: 'saved' }); },
      autoSaveProject(_sid, _pid, _groups, assignments) {
        automatic = assignments; return Promise.resolve({ id: 'saved' });
      },
    },
    map: { loadGeoJSON() {}, setLayerStyle() {}, getLayer() { return null; }, applySymbology() {} },
  } };
  const document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String, Object, Array, JSON, Set, Map });
  for (const file of ['gis_state.js', 'layers.js', 'project.js']) {
    vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../js', file), 'utf8'), context);
  }
  window.GIS.state.addLayer({ layer_id: 'styled', name: '区域',
    geojson: { type: 'FeatureCollection', features: [
      { type: 'Feature', properties: { _fid: 'adcode:1', population: 12 }, geometry: { type: 'Polygon', coordinates: [] } },
      { type: 'Feature', properties: { _fid: 'adcode:2', population: 28 }, geometry: { type: 'Polygon', coordinates: [] } },
    ] }, style: { color: '#111111' } });
  window.GIS.state.setStyle('styled', { color: '#336699', fillOpacity: 0.24, weight: 3 });
  window.GIS.state.setOpacity('styled', 0);
  assert.equal(window.GIS.layers.applyGraduatedColors('区域', 'population', 2, 'ylorrd', 'quantile', [10, 20, 30], 0.2), true);
  await window.GIS.project.save('样式工程');
  await window.GIS.project.autoSave();

  const expected = { color: '#336699', fillOpacity: 0.24, weight: 3, opacity: 0 };
  assert.deepEqual({ ...manual.layers[0].style }, expected);
  assert.deepEqual({ ...automatic[0].style }, expected);
  assert.equal(manual.layers[0].symbology.method, 'quantile');
  assert.deepEqual(Array.from(manual.layers[0].symbology.breaks), [10, 20, 30]);
  assert.deepEqual(JSON.parse(JSON.stringify(automatic[0].symbology)), JSON.parse(JSON.stringify(manual.layers[0].symbology)));
  assert.equal(window.GIS.layers.getLayers()[0].style.color, '#111111', 'saving must not mutate the panel record');
});
