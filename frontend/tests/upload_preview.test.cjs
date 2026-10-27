const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function makeElement() {
  const listeners = {};
  const buttons = {};
  return {
    listeners, buttons, children: [], style: {}, className: '', classList: { add() {}, remove() {} },
    addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
    appendChild(child) { child.parentNode = this; this.children.push(child); return child; },
    removeChild(child) { this.children = this.children.filter(item => item !== child); child.parentNode = null; return child; },
    querySelector(selector) {
      if (buttons[selector]) return buttons[selector];
      if (selector === 'div:last-child') return this.children[this.children.length - 1] || null;
      const className = selector[0] === '.' ? selector.slice(1) : '';
      const child = this.children.find(item => (item.className || '').split(/\s+/).includes(className));
      if (child) return child;
      if (className && String(this.innerHTML || '').includes(className)) return buttons[selector] = makeElement();
      for (const item of this.children) {
        const found = item.querySelector(selector);
        if (found) return found;
      }
      return null;
    },
    fire(name, event) { return Promise.all((listeners[name] || []).map(callback => callback(event))); },
    click() { return this.fire('click'); },
  };
}

function loadUploadModule(readFailure, uploadResponse, config = {}) {
  const overlays = [];
  const uploadCalls = [];
  const rasterOverlays = [];
  const rasterRemovals = [];
  const layerAdds = [];
  const layerRemovals = [];
  const vectorLoads = [];
  const vectorRemovals = [];
  const requests = [];
  const statusRequests = [];
  const reads = [];
  const warnings = [];
  const stateLayerIds = [];
  let stateLayer = null;
  const elements = new Map();
  elements.set('chatMessages', makeElement());
  const document = {
    body: makeElement(),
    createElement() {
      const element = makeElement();
      element.buttons['.preview-btn-confirm'] = makeElement();
      element.buttons['.preview-btn-cancel'] = makeElement();
      return element;
    },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement());
      return elements.get(id);
    },
  };
  document.body.appendChild = function(element) { element.parentNode = this; overlays.push(element); return element; };
  document.body.removeChild = function(element) { const index = overlays.indexOf(element); if (index >= 0) overlays.splice(index, 1); element.parentNode = null; };
  class FileReader {
    readAsText(file) {
      reads.push(file);
      if (readFailure) { this.error = new Error('read failed'); this.onerror(); return; }
      this.result = file.content;
      this.onload();
    }
  }
  class File {
    constructor(parts, name, options = {}) {
      this.name = name;
      this.content = parts.map(part => typeof part === 'string' ? part : part.content || '').join('');
      this.size = this.content.length;
      Object.assign(this, options);
    }
    slice(start, end) { return { content: this.content.slice(start, end) }; }
  }
  const window = { GIS: {
    utils: { escapeHtml: value => String(value) },
    api: {
      upload(file, signal, requestId) { uploadCalls.push(file.name); requests.push({ file, signal, requestId });
        return typeof uploadResponse === 'function' ? uploadResponse(file, signal, requestId)
          : Promise.resolve(uploadResponse || { error: 'test upload' }); },
      getUploadStatus(requestId) {
        statusRequests.push(requestId);
        return config.uploadStatus ? config.uploadStatus(requestId) : Promise.resolve({ status: 'unknown' });
      },
    },
    map: {
      addImageOverlay(...args) { rasterOverlays.push(args); },
      loadGeoJSON(...args) { vectorLoads.push(args); },
      removeLayer(name) { rasterRemovals.push(name); vectorRemovals.push(name); },
    },
    layers: {
      addLayer(...args) {
        if (config.failAfterStateBridge) {
          stateLayer = args[0];
          stateLayerIds.push(stateLayer.layer_id);
          throw new Error('layer panel unavailable after state insert');
        }
        layerAdds.push(args);
        if (config.failLayerAdd) throw new Error('layer panel unavailable');
        if (config.bridgeLayerAdd) {
          stateLayer = args[0];
          layerAdds[layerAdds.length - 1] = [{ ...args[0] }];
          return stateLayer;
        }
        return args[0];
      },
      getLayers() { return layerAdds.map(args => args[0]); },
      removeLayer(layerId) {
        layerRemovals.push(layerId);
        const index = layerAdds.findIndex(args => args[0].layer_id === layerId);
        if (index >= 0) layerAdds.splice(index, 1);
      },
    },
    state: {
      getLayer(layerId) { return stateLayer && stateLayer.layer_id === layerId ? stateLayer : null; },
      removeLayer(layerId) {
        if (!stateLayer || stateLayer.layer_id !== layerId) return;
        const mapName = stateLayer._rawName || stateLayer.filename || layerId;
        stateLayer = null;
        window.GIS.map.removeLayer(mapName);
      },
    },
    toast: { warn(message) { warnings.push(message); } },
  } };
  const context = { window, document, File, FileReader, console: { log() {}, warn() {} }, Promise, Map, Set, Array, Object, String, Number, Date, Math, RegExp,
    AbortController, requestAnimationFrame(callback) { callback(); }, setTimeout() { return 1; }, clearTimeout() {} };
  const sourcePath = path.resolve(__dirname, '../js/upload.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  window.GIS.upload.init();
  const input = elements.get('fileInput');
  return { window, upload: window.GIS.upload, overlays, uploadCalls, rasterOverlays, rasterRemovals, layerAdds, layerRemovals, vectorLoads, vectorRemovals, requests, statusRequests, reads, warnings, stateLayerIds,
    selectFiles(files) { input.files = files; return input.fire('change', { target: input }); },
    dropFiles(files) { return document.body.fire('drop', { preventDefault() {}, dataTransfer: { files } }); },
    chatMessages: elements.get('chatMessages') };
}

test('CSV upload preview preserves quoted commas, escaped quotes, and embedded newlines', async () => {
  const harness = loadUploadModule();
  const content = '\uFEFFname,note\r\n"New York, NY","line 1\r\nline 2"\r\n"said ""hi""",plain';
  const file = { name: 'places.csv', size: content.length, content, slice() { return { content }; } };
  const pending = harness.selectFiles([file]);
  await new Promise(resolve => setImmediate(resolve));

  const overlay = harness.overlays[0];
  assert.ok(overlay, 'CSV should open the pre-upload preview');
  assert.match(overlay.innerHTML, /<th>name<\/th><th>note<\/th>/);
  assert.match(overlay.innerHTML, /<td>New York, NY<\/td><td>line 1\r?\nline 2<\/td>/);
  assert.match(overlay.innerHTML, /<td>said "hi"<\/td><td>plain<\/td>/);
  overlay.querySelector('.preview-btn-cancel').fire('click');
  await pending;
  assert.equal(harness.overlays.length, 0);
});

test('CSV preview read failure stops instead of implicitly confirming upload', async () => {
  const harness = loadUploadModule(true);
  const file = { name: 'unreadable.csv', size: 10, content: '', slice() { return this; } };
  await harness.selectFiles([file]);

  assert.deepEqual(harness.uploadCalls, []);
  assert.match(harness.chatMessages.children[0].children[0].innerHTML, /无法读取文件预览，文件未上传/);
});

test('uploaded raster layers use a stable map identity for independent visibility controls', async () => {
  const harness = loadUploadModule(false, { name: 'elevation', registration_token: 'raster-version', raster_info: {
    url: '/output/uploads/elevation.png', bounds: [100, 30, 101, 31],
  } });
  await harness.selectFiles([{ name: 'elevation.tif', size: 10 }]);

  assert.equal(harness.rasterOverlays.length, 1);
  assert.equal(harness.layerAdds.length, 1);
  const [, , displayName, mapLayerId] = harness.rasterOverlays[0];
  const [layer] = harness.layerAdds[0];
  assert.equal(displayName, 'elevation');
  assert.match(mapLayerId, /^raster_\d+_[a-z0-9]+$/);
  assert.equal(harness.layerAdds[0][0]._registeredName, 'elevation');
  assert.equal(harness.layerAdds[0][0]._registrationTokens.elevation, 'raster-version');
  assert.equal(layer.layer_id, mapLayerId);
  assert.equal(layer._rawName, mapLayerId);
});

test('failed vector layer handoff removes the local map result and backend registration', async () => {
  const h = loadUploadModule(false, {
    name: 'points', geojson: { type: 'FeatureCollection', features: [] }, registration_token: 'vector-version',
  }, { failLayerAdd: true });
  const unregistered = [];
  h.window.GIS.api.unregisterLayer = (...args) => { unregistered.push(args); return Promise.resolve({ success: true }); };

  await h.selectFiles([{ name: 'points.gpkg', size: 10 }]);

  assert.equal(h.vectorLoads.length, 1);
  assert.deepEqual(h.vectorRemovals, ['points']);
  assert.equal(h.layerRemovals.length, 1);
  assert.deepEqual(unregistered, [['points', 'vector-version']]);
  assert.match(h.chatMessages.children[0].children[0].innerHTML, /上传失败/);
});

test('failed raster layer handoff removes the preview overlay and backend registration', async () => {
  const h = loadUploadModule(false, {
    name: 'elevation', registration_token: 'raster-version', raster_info: {
      url: '/output/uploads/elevation.png', bounds: [100, 30, 101, 31],
    },
  }, { failLayerAdd: true });
  const unregistered = [];
  h.window.GIS.api.unregisterLayer = (...args) => { unregistered.push(args); return Promise.resolve({ success: true }); };

  await h.selectFiles([{ name: 'elevation.tif', size: 10 }]);

  const mapLayerId = h.rasterOverlays[0][3];
  assert.deepEqual(h.rasterRemovals, [mapLayerId]);
  assert.deepEqual(h.layerRemovals, [mapLayerId]);
  assert.deepEqual(unregistered, [['elevation', 'raster-version']]);
  assert.match(h.chatMessages.children[0].children[0].innerHTML, /上传失败/);
});

test('failed vector panel bridge removes a state record created before the failure', async () => {
  const h = loadUploadModule(false, {
    name: 'points', geojson: { type: 'FeatureCollection', features: [] }, registration_token: 'vector-version',
  }, { failAfterStateBridge: true });
  const unregistered = [];
  h.window.GIS.api.unregisterLayer = (...args) => { unregistered.push(args); return Promise.resolve({ success: true }); };

  await h.selectFiles([{ name: 'points.gpkg', size: 10 }]);

  assert.equal(h.window.GIS.state.getLayer(h.stateLayerIds[0]), null);
  assert.deepEqual(h.vectorRemovals, ['points']);
  assert.deepEqual(unregistered, [['points', 'vector-version']]);
});

test('vector upload registration ownership is retained across the shared-state panel bridge', async () => {
  const h = loadUploadModule(false, {
    name: 'points', geojson: { type: 'FeatureCollection', features: [] }, registration_token: 'vector-version',
  }, { bridgeLayerAdd: true });

  await h.selectFiles([{ name: 'points.gpkg', size: 10 }]);

  const panelLayer = h.layerAdds[0][0];
  const stateLayer = h.window.GIS.state.getLayer(panelLayer.layer_id);
  assert.equal(panelLayer._registeredName, 'points');
  assert.equal(panelLayer._registrationTokens.points, 'vector-version');
  assert.equal(stateLayer._registeredName, 'points');
  assert.equal(stateLayer._registrationTokens.points, 'vector-version');
});

const tick = () => new Promise(resolve => setImmediate(resolve));
function csv(name = 'points.csv', content = 'lon,lat\n10,20') {
  return { name, size: content.length, content, slice(start, end) { return { content: content.slice(start, end) }; } };
}

test('initializing twice does not duplicate the actual file-selection handler', async () => {
  const h = loadUploadModule();
  h.upload.init();
  assert.equal(h.upload.handleFiles, undefined);
  await h.selectFiles([{ name: 'data.tif', size: 10 }]);
  assert.equal(h.uploadCalls.length, 1);
});

test('extensionless dropped GeoJSON is uploaded with its detected extension and intact content', async () => {
  const content = '{"type":"FeatureCollection","features":[]}';
  const provenance = { provider: 'local_upload', kind: 'vector_upload', file_format: 'GeoJSON', crs: 'EPSG:4326', crs_known: true };
  const h = loadUploadModule(false, { name: 'points.geojson', geojson: JSON.parse(content), registration_token: 'version', provenance });
  const pending = h.dropFiles([csv('points', content)]);
  await tick();
  await h.overlays[0].querySelector('.preview-btn-confirm').fire('click');
  await pending;
  assert.equal(h.requests[0].file.name, 'points.geojson');
  assert.equal(h.requests[0].file.content, content);
  assert.equal(h.layerAdds[0][0]._registrationTokens['points.geojson'], 'version');
  assert.deepEqual(h.layerAdds[0][0].provenance, provenance);
});

test('a large GeoJSON gets a bounded preview without reading the whole browser file', async () => {
  const h = loadUploadModule();
  const pending = h.selectFiles([{ name: 'large.geojson', size: 3 * 1024 * 1024 }]);
  await tick();
  assert.equal(h.reads.length, 0);
  assert.match(h.overlays[0].innerHTML, /文件较大/);
  await h.overlays[0].querySelector('.preview-btn-cancel').fire('click');
  await pending;
  assert.equal(h.uploadCalls.length, 0);
});

test('multiple previews are presented sequentially rather than stacked', async () => {
  const h = loadUploadModule();
  const pending = h.selectFiles([csv('one.csv'), csv('two.csv')]);
  await tick();
  assert.equal(h.overlays.length, 1);
  assert.match(h.overlays[0].innerHTML, /one.csv/);
  await h.overlays[0].querySelector('.preview-btn-cancel').fire('click');
  await tick();
  assert.equal(h.overlays.length, 1);
  assert.match(h.overlays[0].innerHTML, /two.csv/);
  await h.overlays[0].querySelector('.preview-btn-cancel').fire('click');
  await pending;
});

test('canceling an upload prevents a late response from adding map layers', async () => {
  let complete;
  const h = loadUploadModule(false, () => new Promise(resolve => { complete = resolve; }));
  const cleaned = [];
  h.window.GIS.api.unregisterLayer = (...args) => { cleaned.push(args); return Promise.resolve({ success: true }); };
  const pending = h.selectFiles([{ name: 'points.gpkg', size: 10 }]);
  await tick();
  await h.chatMessages.children[0].querySelector('.upload-cancel-btn').fire('click');
  complete({ name: 'points', geojson: { type: 'FeatureCollection', features: [] }, registration_token: 'owned' });
  await pending;
  assert.equal(h.vectorLoads.length, 0);
  assert.equal(h.layerAdds.length, 0);
  assert.deepEqual(cleaned, [['points', 'owned']]);
});

test('CSV conversion uses the returned real path without interrupting an existing AI task', async () => {
  const h = loadUploadModule(false, { csv_info: { filename: 'points.csv', path: 'E:/data/uploads/points.csv' } });
  h.window._aiRunning = true;
  const sent = [];
  h.window.GIS.chat = { sendMessage(message) { sent.push(message); return Promise.resolve(); } };
  const pending = h.selectFiles([csv()]);
  await tick();
  await h.overlays[0].querySelector('.preview-btn-confirm').fire('click');
  await pending;
  assert.equal(sent.length, 0);
  const button = h.chatMessages.children[0].children.find(child => child.className === 'upload-convert-btn');
  await button.fire('click');
  assert.equal(sent.length, 0);
  h.window._aiRunning = false;
  await button.fire('click');
  assert.match(sent[0], /E:\/data\/uploads\/points.csv/);
});

test('wide CSV previews cap rendered columns and field text', async () => {
  const content = Array.from({ length: 80 }, (_, i) => 'column' + i).join(',') + '\n' + 'x'.repeat(1000);
  const h = loadUploadModule();
  const pending = h.selectFiles([csv('wide.csv', content)]);
  await tick();
  assert.equal((h.overlays[0].innerHTML.match(/<th>/g) || []).length, 50);
  assert.doesNotMatch(h.overlays[0].innerHTML, /x{201}/);
  await h.overlays[0].querySelector('.preview-btn-cancel').fire('click');
  await pending;
});

test('format-specific file limits reject oversized input before preview or transfer', async () => {
  const h = loadUploadModule();
  await h.selectFiles([{ name: 'huge.csv', size: 65 * 1024 * 1024 }]);
  assert.equal(h.reads.length, 0);
  assert.equal(h.uploadCalls.length, 0);
});

test('an interrupted upload warns that the server may have received the file before retry', async () => {
  const h = loadUploadModule(false, () => Promise.reject(Object.assign(new Error('Failed to fetch'), { code: 'UPLOAD_NETWORK_ERROR' })));
  await h.selectFiles([{ name: 'elevation.tif', size: 10 }]);
  const message = h.chatMessages.children[0].children[0].innerHTML;
  assert.match(message, /服务器可能已收到文件/);
  assert.match(message, /检查图层列表/);
  assert.doesNotMatch(message, /Failed to fetch/);
});

test('a backend without status recovery support does not offer a potentially duplicating retry', async () => {
  const h = loadUploadModule(false,
    () => Promise.reject(Object.assign(new Error('Failed to fetch'), { code: 'UPLOAD_NETWORK_ERROR' })),
    { uploadStatus: () => Promise.reject(Object.assign(new Error('Not Found'), { status: 404 })) });
  await h.selectFiles([{ name: 'older-server.tif', size: 10 }]);
  const row = h.chatMessages.children[0];
  assert.match(row.children[0].innerHTML, /无法安全核对上传状态/);
  assert.equal(row.querySelector('.system-pill').children.length, 0);
  assert.equal(h.uploadCalls.length, 1);
});

test('a completed upload is recovered after a lost response without sending the file again', async () => {
  const geojson = { type: 'FeatureCollection', features: [{
    type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [-122.3, 47.6] },
  }] };
  const h = loadUploadModule(false,
    () => Promise.reject(Object.assign(new Error('Failed to fetch'), { code: 'UPLOAD_NETWORK_ERROR' })),
    { uploadStatus: () => Promise.resolve({ status: 'completed', result: {
      name: 'recovered.geojson', geojson, registration_token: 'recovered-version',
    } }) });
  const pending = h.selectFiles([csv('recovered.geojson', JSON.stringify(geojson))]);
  await tick();
  await h.overlays[0].querySelector('.preview-btn-confirm').fire('click');
  await pending;

  assert.equal(h.requests.length, 1);
  assert.equal(h.statusRequests.length, 1);
  assert.equal(h.requests[0].requestId.length > 0, true);
  assert.equal(h.layerAdds.length, 1);
  assert.equal(h.layerAdds[0][0].filename, 'recovered.geojson');
  assert.match(h.chatMessages.children[0].children[0].innerHTML, /上传成功/);
});

test('manual recovery retries the same upload request ID after checking an unknown receipt', async () => {
  const geojson = { type: 'FeatureCollection', features: [{
    type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [-122.3, 47.6] },
  }] };
  let uploadCount = 0;
  const h = loadUploadModule(false, () => {
    uploadCount += 1;
    if (uploadCount === 1) return Promise.reject(Object.assign(new Error('Failed to fetch'), { code: 'UPLOAD_NETWORK_ERROR' }));
    return Promise.resolve({ name: 'recovered.geojson', geojson, registration_token: 'recovered-version' });
  }, { uploadStatus: () => Promise.resolve({ status: 'unknown' }) });
  const pending = h.selectFiles([csv('recovered.geojson', JSON.stringify(geojson))]);
  await tick();
  await h.overlays[0].querySelector('.preview-btn-confirm').fire('click');
  await pending;
  const errorRow = h.chatMessages.children[0];
  const recoveryButton = errorRow.querySelector('.system-pill').children[0];
  assert.equal(recoveryButton.textContent, '检查并恢复');

  await recoveryButton.fire('click');
  assert.equal(h.requests.length, 2);
  assert.equal(h.requests[1].requestId, h.requests[0].requestId);
  assert.equal(h.layerAdds.length, 1);
});
