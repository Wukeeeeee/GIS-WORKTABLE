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
  let serverGeneration = 0;
  let backendActiveProject = null;
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
    api: { loadProject(id) {
      const generation = ++serverGeneration;
      const req = deferred();
      requests.set(id, req);
      return req.promise.then(payload => {
        if (generation !== serverGeneration) throw new Error('superseded project load');
        backendActiveProject = id;
        return payload;
      });
    } },
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
  await new Promise(resolve => setImmediate(resolve));
  requests.get('latest-project').resolve({ id: 'latest-project', name: '最新工程', messages: [], layers: [], mapState: { lat: 40, lng: -74, zoom: 8 } });
  assert.equal(await latestLoad, true);
  requests.get('old-project').resolve({ id: 'old-project', name: '旧工程', messages: [], layers: [], mapState: { lat: 10, lng: 20, zoom: 4 } });
  assert.equal(await oldLoad, false);

  assert.equal(window.GIS.project.getCurrentProjectId(), 'latest-project');
  assert.equal(backendActiveProject, 'latest-project');
  assert.match(window.GIS.project.getCurrentSessionId(), /latest-project/);
  assert.equal(capsule.textContent, '最新工程');
  assert.equal(mapViews.length, 1);
  assert.equal(mapViews[0].center[0], 40);
  assert.equal(mapViews[0].center[1], -74);
  assert.equal(mapViews[0].zoom, 8);
  assert.ok(restoredMessages.some(message => message.includes('最新工程')));
  assert.equal(restoredMessages.some(message => message.includes('旧工程')), false);
});

test('requesting a project switch cancels the active chat before loading its state', async () => {
  const pending = deferred();
  const events = [];
  const window = { GIS: {
    api: { loadProject() { events.push('load'); return pending.promise; } },
    chat: {
      cancelActiveRequest() { events.push('cancel'); },
      clear() {},
      addMessage() {},
    },
    map: { clearAll() {} },
    workspace: { renderRecentProjects() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  const loading = window.GIS.project.loadProject('next-project');
  assert.equal(events.join(','), 'cancel,load');
  pending.resolve({ id: 'next-project', name: '新工程', messages: [], layers: [], mapState: {} });
  assert.equal(await loading, true);
});

test('a newer project request supersedes an older load waiting for chat cancellation', async () => {
  const cancellation = deferred();
  const loads = [];
  let firstCancel = true;
  const window = { GIS: {
    api: { loadProject(id) {
      loads.push(id);
      return Promise.resolve({ id, name: id, messages: [], layers: [], mapState: {} });
    } },
    chat: {
      cancelActiveRequest() {
        if (firstCancel) {
          firstCancel = false;
          return cancellation.promise;
        }
        return Promise.resolve(true);
      },
      clear() {},
      addMessage() {},
    },
    map: { clearAll() {} },
    workspace: { renderRecentProjects() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  const oldLoad = window.GIS.project.loadProject('old-project');
  const latestLoad = window.GIS.project.loadProject('latest-project');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(loads.join(','), 'latest-project');
  assert.equal(await latestLoad, true);
  cancellation.resolve(true);
  assert.equal(await oldLoad, false);
  assert.equal(loads.join(','), 'latest-project');
});

test('a project is not opened when the active chat cancellation cannot be confirmed', async () => {
  let loadCalls = 0;
  const messages = [];
  const window = { GIS: {
    api: { loadProject() { loadCalls++; return Promise.resolve({ id: 'unsafe' }); } },
    chat: {
      cancelActiveRequest() { return Promise.resolve(false); },
      clear() {},
      addMessage(message) { messages.push(message); },
    },
    map: { clearAll() {} },
    workspace: { renderRecentProjects() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('unsafe'), false);
  assert.equal(loadCalls, 0);
  assert.equal(window.GIS.project.getCurrentProjectId(), null);
  assert.ok(messages.some(message => message.includes('未切换工程')));
  assert.equal(messages.length, 1);
});

test('deleting the current project waits for active chat cancellation', async () => {
  const cancellation = deferred();
  const events = [];
  const messages = [];
  let active = true;
  const window = { GIS: {
    api: {
      deleteProject() { events.push('delete'); return Promise.resolve({}); },
      listProjects() { return Promise.resolve({ projects: [] }); },
    },
    chat: {
      cancelActiveRequest() {
        if (!active) return false;
        active = false;
        events.push('cancel');
        return cancellation.promise;
      },
      clear() {},
      addMessage(message) { messages.push(message); },
    },
    map: { clearAll() {} },
    workspace: { renderRecentProjects() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  const source = fs.readFileSync(sourcePath, 'utf8').replace(
    'loadProject: _loadProject,', 'loadProject: _loadProject, _deleteProject: _deleteProject,',
  );
  vm.runInNewContext(source, {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  window.GIS.project.setCurrentProjectId('active-project');
  window.GIS.project._deleteProject('active-project', null);
  assert.equal(events.join(','), 'cancel');
  cancellation.resolve(true);
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(events.join(','), 'cancel,delete');
  assert.equal(window.GIS.project.getCurrentProjectId(), null);
  assert.equal(messages.length, 0);
});

test('current project deletion is blocked when active chat cancellation fails', async () => {
  let deleteCalls = 0;
  const messages = [];
  const window = { GIS: {
    api: { deleteProject() { deleteCalls++; return Promise.resolve({}); } },
    chat: {
      cancelActiveRequest() { return Promise.resolve(false); },
      clear() {},
      addMessage(message) { messages.push(message); },
    },
    map: { clearAll() {} },
    workspace: { renderRecentProjects() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  const source = fs.readFileSync(sourcePath, 'utf8').replace(
    'loadProject: _loadProject,', 'loadProject: _loadProject, _deleteProject: _deleteProject,',
  );
  vm.runInNewContext(source, {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  window.GIS.project.setCurrentProjectId('active-project');
  window.GIS.project._deleteProject('active-project', null);
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(deleteCalls, 0);
  assert.equal(window.GIS.project.getCurrentProjectId(), 'active-project');
  assert.ok(messages.some(message => message.includes('无法确认当前任务已停止')));
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

test('loading a project with a non-text name uses a safe display fallback', async () => {
  const capsule = { textContent: '' };
  const messages = [];
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve({ id: 'bad-name', name: { value: '工程名' }, messages: [], layers: [], mapState: {} }); } },
    chat: { clear() {}, addMessage(message, type) { messages.push({ message, type }); } },
    map: { clearAll() {} },
  } };
  const document = { getElementById(id) { return id === 'workspaceCurrentProjectName' ? capsule : null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('bad-name'), true);
  assert.equal(capsule.textContent, '未命名工程');
  assert.ok(messages.some(item => item.type === 'system' && item.message === '已恢复工程: 未命名工程'));
});

test('project restore skips malformed saved messages and layer rows while restoring valid data', async () => {
  const messages = [];
  const restoredLayers = [];
  const payload = {
    id: 'partially-damaged-project', name: '可恢复工程',
    messages: [null, { role: 'user', content: '保留的消息' }, { role: 'assistant', content: 42 }],
    layers: [null, { name: '可恢复图层', geojson: { type: 'FeatureCollection', features: [] } }],
    layerGroups: {}, mapState: {}, registration_warnings: ['坏图层'],
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage(message, type) { messages.push({ message, type }); } },
    map: { clearAll() {}, loadGeoJSON() { return {}; } },
    layers: { clearAll() {}, setGroupState(groups) { assert.equal(groups.length, 0); },
      addLayer(layer) { restoredLayers.push(layer); }, syncLayerOrder() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
  }, { filename: sourcePath });

  const restored = await window.GIS.project.loadProject(payload.id);
  assert.equal(restored, true, JSON.stringify(messages));
  assert.ok(messages.some(item => item.type === 'user' && item.message === '保留的消息'));
  assert.equal(restoredLayers.length, 1);
  assert.equal(restoredLayers[0].filename, '可恢复图层');
  assert.ok(messages.some(item => item.type === 'system' && item.message.includes('4 条格式异常')));
  assert.ok(messages.some(item => item.type === 'system' && item.message.includes('1 个图层未能注册到分析工具')));
});

test('project restore does not render vector layers rejected by backend registration', async () => {
  const restoredLayers = [];
  const renderedNames = [];
  const messages = [];
  const payload = {
    id: 'invalid-coordinate-project', name: '坐标异常工程', messages: [], mapState: {},
    registration_warnings: ['坏坐标'],
    layers: [
      { name: '坏坐标', geojson: { type: 'FeatureCollection', features: [
        { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [0, 100] } },
      ] } },
      { name: '正常图层', geojson: { type: 'FeatureCollection', features: [] } },
    ],
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage(message, type) { messages.push({ message, type }); } },
    map: { clearAll() {}, loadGeoJSON(_geojson, name) { renderedNames.push(name); return {}; } },
    layers: { clearAll() {}, setGroupState() {}, addLayer(layer) { restoredLayers.push(layer); }, syncLayerOrder() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject(payload.id), true);
  assert.deepEqual(renderedNames, ['project_invalid-coordinate-project_layer_1']);
  assert.deepEqual(restoredLayers.map(layer => layer.filename), ['正常图层']);
  assert.ok(messages.some(item => item.type === 'system' && item.message.includes('坏坐标')));
});

test('restoring legacy same-name layers without IDs delegates unique ID creation to the layer registry', async () => {
  const addedLayers = [];
  const opacities = [];
  const mapNames = [];
  const hiddenMapNames = [];
  const payload = {
    id: 'legacy-project', name: '旧工程', messages: [], mapState: {},
    layers: [
      { name: '行政区', geojson: { type: 'FeatureCollection', features: [] } },
      { name: '行政区', visible: false, geojson: { type: 'FeatureCollection', features: [] } },
    ],
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage() {} },
    map: { clearAll() {}, loadGeoJSON(_geojson, name) { mapNames.push(name); },
      setLayerVisible(name, visible) { if (!visible) hiddenMapNames.push(name); } },
    layers: {
      setGroupState() {}, clearAll() {}, syncLayerOrder() {},
      addLayer(layer) { addedLayers.push({ ...layer }); },
    },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('legacy-project'), true);
  assert.deepEqual(mapNames, ['project_legacy-project_layer_0', 'project_legacy-project_layer_1']);
  assert.deepEqual(addedLayers.map(layer => layer.layer_id), mapNames);
  assert.deepEqual(addedLayers.map(layer => layer._rawName), mapNames);
  assert.deepEqual(addedLayers.map(layer => layer.filename), ['行政区', '行政区']);
  assert.deepEqual(hiddenMapNames, [mapNames[1]], 'only the saved hidden layer should be hidden');
});

test('a vector layer that fails to render is not registered as restored and is reported', async () => {
  const addedLayers = [];
  const messages = [];
  const payload = {
    id: 'broken-render-project', name: '渲染失败工程', messages: [], mapState: {},
    layers: [{ name: '无法渲染的图层', geojson: { type: 'FeatureCollection', features: [] } }],
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage(message, type) { messages.push({ message, type }); } },
    map: { clearAll() {}, loadGeoJSON() { throw new Error('render failed'); } },
    layers: { clearAll() {}, addLayer(layer) { addedLayers.push(layer); }, syncLayerOrder() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('broken-render-project'), true);
  assert.equal(addedLayers.length, 0, 'a failed map layer must not appear in the layer registry');
  assert.ok(messages.some(item => item.message.includes('无法渲染的图层未能显示')));
  assert.ok(messages.some(item => item.message.includes('已恢复工程')));
});

test('a raster restore error does not stop later project layers from loading', async () => {
  const addedLayers = [];
  const messages = [];
  const payload = {
    id: 'raster-error-project', name: '栅格损坏工程', messages: [], mapState: {},
    layers: [
      { name: '损坏栅格', raster: { url: 'blob:broken', bounds: [[0, 0], [1, 1]] } },
      { name: '后续矢量', geojson: { type: 'FeatureCollection', features: [] } },
    ],
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage(message, type) { messages.push({ message, type }); } },
    map: { clearAll() {}, addImageOverlay() { throw new Error('invalid raster source'); }, loadGeoJSON() { return {}; } },
    layers: { clearAll() {}, setGroupState() {}, addLayer(layer) { addedLayers.push(layer); }, syncLayerOrder() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject(payload.id), true);
  assert.deepEqual(addedLayers.map(layer => layer.filename), ['后续矢量']);
  assert.ok(messages.some(item => item.type === 'system' && item.message.includes('损坏栅格未能显示')));
  assert.ok(messages.some(item => item.type === 'system' && item.message.includes('已恢复工程')));
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
    layer_id: 'layer-persisted', registry_name: 'registered', style: { color: '#336699', fillOpacity: 0.24 },
    names: ['registered', 'raw', 'display'],
    groupId: 'group_2', visible: false,
    symbology: null,
    name: 'display', raster: null, labels: null, order: 0,
  }]);
});

test('autosave waits for the latest layer registration and skips saving stale data on sync failure', async () => {
  let resolveSync;
  let saveCalls = 0;
  const layer = { layer_id: 'layer-1', filename: 'places', geojson: { type: 'FeatureCollection', features: [] },
    _registrationPromise: new Promise(resolve => { resolveSync = resolve; }) };
  const window = { GIS: {
    api: { autoSaveProject() { saveCalls++; return Promise.resolve({ id: 'saved' }); } },
    layers: { getLayers() { return [layer]; }, getGroupState() { return []; } },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, console,
  }, { filename: sourcePath });

  const pendingSave = window.GIS.project.autoSave();
  await Promise.resolve();
  assert.equal(saveCalls, 0, 'automatic persistence must wait until current feature data is registered');
  resolveSync(true);
  await pendingSave;
  assert.equal(saveCalls, 1);

  layer._registrationPromise = Promise.resolve(false);
  await window.GIS.project.autoSave();
  assert.equal(saveCalls, 1, 'failed registration must not persist the older backend copy');
});

test('project restore forwards saved layer style and provenance to the layer registry', async () => {
  const addedLayers = [];
  const opacities = [];
  const payload = {
    id: 'styled-project', name: '样式工程', messages: [], mapState: {},
    layers: [{ layer_id: 'styled-layer', name: '行政区', color: '#336699',
      provenance: { provider_name: 'OpenStreetMap', crs: 'EPSG:4326' },
      style: { color: '#336699', fillOpacity: 0.24, opacity: 0.6, weight: 3 },
      geojson: { type: 'FeatureCollection', features: [] } }],
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage() {} },
    map: { clearAll() {}, loadGeoJSON() {}, setLayerOpacity(...args) { opacities.push(args); } },
    layers: { setGroupState() {}, clearAll() {}, addLayer(layer) { addedLayers.push({ ...layer }); }, syncLayerOrder() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('styled-project'), true);
  assert.deepEqual({ ...addedLayers[0].style }, { color: '#336699', fillOpacity: 0.24, weight: 3 });
  assert.deepEqual({ ...addedLayers[0].provenance }, { provider_name: 'OpenStreetMap', crs: 'EPSG:4326' });
  assert.equal(addedLayers[0].opacity, 0.6);
  assert.deepEqual(opacities, [['project_styled-project_layer_0', 0.6]]);
});

test('project restore reapplies a saved vector label configuration', async () => {
  const labels = [];
  const payload = {
    id: 'labeled-project', name: '标注工程', messages: [], mapState: {},
    layers: [{ layer_id: 'labeled-layer', name: '行政区',
      labels: { field: 'district', fontSize: 14, color: '#223344' },
      geojson: { type: 'FeatureCollection', features: [] } }],
  };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage() {} },
    map: { clearAll() {}, loadGeoJSON() {}, setLabels(...args) { labels.push(args); return true; } },
    layers: { setGroupState() {}, clearAll() {}, addLayer() {}, syncLayerOrder() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('labeled-project'), true);
  assert.deepEqual(labels, [['project_labeled-project_layer_0', 'district', 14, '#223344']]);
});

test('project restore recreates saved raster overlays and their layer-panel visibility', async () => {
  const overlays = [];
  const opacities = [];
  const hiddenMapNames = [];
  const addedLayers = [];
  const raster = { url: '/api/projects/raster-project/assets/abc.png', project_id: 'raster-project',
    asset: 'abc.png', bounds: [100, 30, 101, 31], width: 512, height: 256 };
  const payload = { id: 'raster-project', name: '栅格工程', messages: [], mapState: {},
    layers: [{ layer_id: 'raster-layer', name: '高程', geometry_type: 'Raster', visible: false,
      style: { opacity: 0.4 }, raster, registration_token: 'restored-version' }] };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage() {} },
    map: { clearAll() {}, addImageOverlay(...args) { overlays.push(args); },
      setLayerVisible(...args) { if (args[1] === false) hiddenMapNames.push(args); },
      setLayerOpacity(...args) { opacities.push(args); } },
    layers: { setGroupState() {}, clearAll() {},
      addLayer(layer) { addedLayers.push({ ...layer }); }, syncLayerOrder() {} },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('raster-project'), true);
  const mapLayerName = 'project_raster-project_layer_0';
  assert.deepEqual(overlays[0], [raster.url, raster.bounds, mapLayerName, '高程']);
  assert.deepEqual(hiddenMapNames, [[mapLayerName, false]]);
  assert.deepEqual(opacities[0], [mapLayerName, 0.4]);
  assert.equal(addedLayers[0].filename, '高程');
  assert.equal(addedLayers[0].layer_id, 'raster-layer');
  assert.equal(addedLayers[0]._rawName, mapLayerName);
  assert.equal(addedLayers[0].visible, false);
  assert.equal(addedLayers[0].opacity, 0.4);
  assert.deepEqual({ ...addedLayers[0].raster }, raster);
  assert.equal(addedLayers[0]._registeredName, '高程');
  assert.equal(addedLayers[0]._registrationTokens['高程'], 'restored-version');
});

test('project restore routes saved WMS and XYZ sources through GeoSource reauthentication', async () => {
  const restoredSources = [];
  const payload = { id: 'service-project', name: '在线图层工程', messages: [], mapState: {}, layers: [
    { layer_id: 'duplicate-service-id', filename: '在线 WMS', geometry_type: 'WMS', service_type: 'WMS',
      url: 'https://maps.example.test/wms', sublayer: 'roads', requires_auth: true, auth_parameter: 'token' },
    { layer_id: 'duplicate-service-id', filename: 'XYZ 底图', geometry_type: 'XYZ瓦片', service_type: 'XYZ',
      url: 'https://tiles.example.test/{z}/{x}/{y}', requires_auth: false },
  ] };
  const window = { GIS: {
    api: { loadProject() { return Promise.resolve(payload); } },
    chat: { clear() {}, addMessage() {} },
    map: { clearAll() {}, addTileLayer() {} },
    layers: { setGroupState() {}, clearAll() {}, syncLayerOrder() {} },
    geosource: { loadSavedServiceLayer(layer) { restoredSources.push(layer); } },
  } };
  const document = { getElementById() { return null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
  }, { filename: sourcePath });

  assert.equal(await window.GIS.project.loadProject('service-project'), true);
  assert.equal(restoredSources.length, 2);
  assert.equal(restoredSources[0].requires_auth, true);
  assert.equal(restoredSources[0].auth_parameter, 'token');
  assert.equal(restoredSources[1].service_type, 'XYZ');
  assert.equal(restoredSources[0].layer_id, 'duplicate-service-id');
  assert.equal(restoredSources[1].layer_id, 'duplicate-service-id_2');
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
  const opacities = [];
  const window = { GIS: {
    api: {
      saveProject(data) { manual = data; return Promise.resolve({ id: 'saved' }); },
      autoSaveProject(_sid, _pid, _groups, assignments) {
        automatic = assignments; return Promise.resolve({ id: 'saved' });
      },
    },
    map: { loadGeoJSON() {}, setLayerStyle() {}, setLayerOpacity(...args) { opacities.push(args); }, getLayer() { return null; }, applySymbology() { return true; } },
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

  const expected = { color: '#336699', fillOpacity: 0.24, weight: 3 };
  assert.deepEqual({ ...manual.layers[0].style }, expected);
  assert.deepEqual({ ...automatic[0].style }, expected);
  assert.equal(manual.layers[0].opacity, 0);
  assert.equal(automatic[0].opacity, 0);
  assert.equal(manual.layers[0].symbology.method, 'quantile');
  assert.deepEqual(Array.from(manual.layers[0].symbology.breaks), [10, 20, 30]);
  assert.deepEqual(JSON.parse(JSON.stringify(automatic[0].symbology)), JSON.parse(JSON.stringify(manual.layers[0].symbology)));
  assert.equal(window.GIS.layers.getLayers()[0].style.color, '#111111', 'saving must not mutate the panel record');
});

test('project export keeps its object URL alive until the browser can start the download', async () => {
  const events = [];
  const timers = [];
  const anchor = {
    href: '',
    download: '',
    click() { events.push('click'); },
  };
  const document = {
    readyState: 'loading',
    addEventListener() {},
    createElement(tag) { assert.equal(tag, 'a'); return anchor; },
    body: {
      appendChild(element) { assert.equal(element, anchor); events.push('append'); },
      removeChild(element) { assert.equal(element, anchor); events.push('remove'); },
    },
  };
  const window = { GIS: { api: { exportProject() { return Promise.resolve({ type: 'application/zip' }); } } } };
  const URL = {
    createObjectURL(blob) { assert.equal(blob.type, 'application/zip'); return 'blob:project-export'; },
    revokeObjectURL(url) { events.push('revoke:' + url); },
  };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, URL, Promise, Date, Math, Number, String, Object, Array, JSON,
    setTimeout(callback, delay) { timers.push({ callback, delay }); },
  }, { filename: sourcePath });

  await window.GIS.project.exportCurrent('project-1', '样式工程');

  assert.equal(anchor.href, 'blob:project-export');
  assert.equal(anchor.download, '样式工程.giswork');
  assert.deepEqual(events, ['append', 'click', 'remove']);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 1000);
  timers[0].callback();
  assert.deepEqual(events, ['append', 'click', 'remove', 'revoke:blob:project-export']);
});
