const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function loadRendererWithPendingLayer(layerId = 'pending-layer') {
  let finishLoad;
  let loadCalls = 0;
  const dataSource = { entities: { values: [] } };
  const dataSources = {
    items: [],
    get length() { return this.items.length; },
    get(index) { return this.items[index]; },
    add(source) { this.items.push(source); return Promise.resolve(source); },
    remove(source) {
      const index = this.items.indexOf(source);
      if (index >= 0) this.items.splice(index, 1);
      return index >= 0;
    },
  };
  const viewer = {
    dataSources,
    scene: { globe: {}, canvas: {}, requestRender() {}, pick() { return null; } },
    camera: {}, resize() {}, entities: { add() {} },
  };
  const noop = () => {};
  const elements = {
    map: { style: {}, parentNode: null },
    mapZoomControls: { classList: { add: noop, remove: noop } },
    toggle3dBtn: { classList: { add: noop, remove: noop }, setAttribute: noop },
    drillBreadcrumb: {}, featurePanel: {}, mapCoords: {},
  };
  const document = {
    readyState: 'loading',
    body: { classList: { toggle: noop }, appendChild(element) { elements[element.id] = element; } },
    addEventListener: noop,
    getElementById(id) { return elements[id] || null; },
    createElement() { return { style: {}, classList: { add: noop, remove: noop }, setAttribute: noop, addEventListener: noop }; },
  };
  const state = {
    on: noop,
    getLayers() {
      return [{ layer_id: layerId, name: 'Pending', visible: true,
        geojson: { type: 'FeatureCollection', features: [] } }];
    },
    clearSelection: noop,
  };
  const color = { fromCssColorString() { return { withAlpha() { return this; }, clone() { return this; } }; }, WHITE: {} };
  const Cesium = {
    Viewer: function() { return viewer; },
    ImageryLayer: function(source) { return source; },
    UrlTemplateImageryProvider: function() {},
    ScreenSpaceEventHandler: function() { this.setInputAction = noop; },
    ScreenSpaceEventType: { LEFT_CLICK: 0, MOUSE_MOVE: 1 },
    Color: color,
    GeoJsonDataSource: { load() { loadCalls++; return new Promise(resolve => { finishLoad = () => resolve(dataSource); }); } },
    defined(value) { return !!value; },
  };
  const window = { GIS: { state }, Cesium };
  const context = { window, Cesium, document, console, setTimeout, Promise, Set, Map, Math, Number, Infinity };
  const sourcePath = path.resolve(__dirname, '../js/renderer_cesium.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return { renderer: window.GIS.renderers, dataSources, finishLoad: () => finishLoad,
    getLoadCalls: () => loadCalls, toggle3D: () => window.GIS.renderers.toggle3D() };
}

test('3D renderer loads layers whose stable IDs collide with Object prototype properties', async () => {
  const harness = loadRendererWithPendingLayer('constructor');
  await harness.toggle3D();

  assert.equal(harness.getLoadCalls(), 1);
  assert.equal(typeof harness.finishLoad(), 'function');
});

test('clear removes legacy Cesium data sources and prevents pending GeoJSON loads from returning', async () => {
  const harness = loadRendererWithPendingLayer();
  await harness.toggle3D();
  const resolvePending = harness.finishLoad();
  assert.equal(typeof resolvePending, 'function', '3D sync should be in flight');

  const legacyLayer = { _gisLayerId: 'legacy-layer' };
  const unrelatedDataSource = { name: 'non-GIS source' };
  harness.dataSources.add(legacyLayer);
  harness.dataSources.add(unrelatedDataSource);

  const result = harness.renderer.clearAllLayers();
  resolvePending();
  await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(harness.dataSources.items, [unrelatedDataSource]);
  assert.equal(result.ok, true);
  assert.equal(result.remaining, 0);
});

test('layer-panel clear delegates to both map and 3D renderer cleanup', () => {
  const calls = { map: 0, renderer: 0 };
  const window = { GIS: {
    map: {
      getLayer() { return null; },
      removeLayer() {},
      clearAll() { calls.map++; return { ok: true, remaining: 0, errors: [] }; },
    },
    renderers: {
      clearAllLayers() { calls.renderer++; return { ok: true, remaining: 0, errors: [] }; },
    },
  } };
  const document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
  const context = { window, document, console, Promise, Set, Math, Date, Array, Object, String, Number };
  const sourcePath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });

  window.GIS.layers.addLayer({ layer_id: 'panel-only', filename: 'Panel only', geometry_type: 'Point' });
  const result = window.GIS.layers.clearAll();

  assert.equal(result.ok, true);
  assert.equal(window.GIS.layers.getLayers().length, 0);
  assert.deepEqual(calls, { map: 1, renderer: 1 });
});

test('clearing a state-backed layer empties shared state, panel, 2D map and 3D renderer', () => {
  const removedFromMap = [];
  const calls = { mapClear: 0, rendererClear: 0 };
  const window = { GIS: {
    map: {
      getLayer() { return null; },
      removeLayer(name) { removedFromMap.push(name); },
      clearAll() { calls.mapClear++; return { ok: true, remaining: 0, errors: [] }; },
    },
    renderers: {
      clearAllLayers() { calls.rendererClear++; return { ok: true, remaining: 0, errors: [] }; },
    },
  } };
  const document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
  const context = { window, document, console, Promise, Set, Map, Math, Date, Array, Object, String, Number };
  const statePath = path.resolve(__dirname, '../js/gis_state.js');
  const layersPath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(statePath, 'utf8'), context, { filename: statePath });
  window.GIS.state.addLayer({ layer_id: 'state-only-layer', name: 'State only' });
  vm.runInNewContext(fs.readFileSync(layersPath, 'utf8'), context, { filename: layersPath });
  window.GIS.state.removeLayer('state-only-layer');

  window.GIS.layers.addLayer({
    layer_id: 'state-backed-layer', filename: 'State backed', _rawName: 'map-state-backed',
    geojson: { type: 'FeatureCollection', features: [] }, geometry_type: 'Point',
  });
  assert.equal(window.GIS.state.getLayers().length, 1);
  assert.equal(window.GIS.layers.getLayers().length, 1);

  const result = window.GIS.layers.clearAll();

  assert.equal(result.ok, true);
  assert.equal(window.GIS.state.getLayers().length, 0);
  assert.equal(window.GIS.layers.getLayers().length, 0);
  assert.deepEqual(removedFromMap, ['State only', 'map-state-backed']);
  assert.deepEqual(calls, { mapClear: 1, rendererClear: 1 });
});

test('execution cards mark existing Chinese and English tool error strings as failures', () => {
  class Element {
    constructor(tag) {
      this.tagName = tag;
      this.children = [];
      this.dataset = {};
      this.className = '';
      this.classList = { add: name => { this.className += ' ' + name; } };
    }
    appendChild(child) { this.children.push(child); return child; }
    setAttribute() {}
  }
  const document = { createElement(tag) { return new Element(tag); } };
  const window = { GIS: {} };
  const context = { window, document, Map, Set, String, JSON, Math, RegExp };
  const sourcePath = path.resolve(__dirname, '../js/execution_cards.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  const container = new Element('div');
  const cards = window.GIS.executionCards.create(container);

  for (const [toolName, message] of [
    ['query_spatial_sql', 'SQL 查询未通过: duplicate column name: _fid'],
    ['fetch_gis_data_url', '数据抓取失败: URL 无法解析'],
    ['unknown_tool', '[ERROR] Provider unavailable'],
  ]) {
    cards.handle({ type: 'tool_start', step_id: toolName, step_label: '检查', name: toolName,
      tool_call_id: toolName, input: {} });
    cards.handle({ type: 'tool_end', step_id: toolName, name: toolName,
      tool_call_id: toolName, output: message });
  }
  cards.handle({ type: 'tool_start', step_id: 'success', step_label: '搜索网页', name: 'search_web',
    tool_call_id: 'success', input: { query: '查询失败的排查方法' } });
  cards.handle({ type: 'tool_end', step_id: 'success', name: 'search_web', tool_call_id: 'success',
    output: '搜索结果说明“查询失败”的排查方法，网页已成功读取。' });
  assert.equal(container.children[0].children.length, 4);
  for (const card of container.children[0].children) {
    const status = card.children[0].children[2].textContent;
    if (card.dataset.taskKind === 'search') assert.equal(status, '已完成');
    else {
      assert.match(card.className, /ai-step-failed/);
      assert.equal(status, '步骤失败');
    }
  }
});

test('layer-panel clear button waits for confirmation, then clears panel and map renderers', () => {
  const calls = { map: 0, renderer: 0, messages: [] };
  let confirmClear;
  class Button {
    addEventListener(type, handler) { this[type] = handler; }
  }
  const clearButton = new Button();
  const ids = { clearAllLayersBtn: clearButton };
  const document = { getElementById(id) { return ids[id] || null; } };
  const window = { GIS: {
    workspace: { confirmModal(title, message, callback) { confirmClear = callback; } },
    chat: { addMessage(message) { calls.messages.push(message); } },
    map: {
      getLayer() { return null; }, removeLayer() {},
      clearAll() { calls.map++; return { ok: true, remaining: 0, errors: [] }; },
    },
    renderers: { clearAllLayers() { calls.renderer++; return { ok: true, remaining: 0, errors: [] }; } },
  } };
  const context = { window, document, console, Promise, Set, Math, Date, Array, Object, String, Number };
  const sourcePath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  window.GIS.layers.init();
  window.GIS.layers.addLayer({ layer_id: 'panel-test', filename: 'Panel test', geometry_type: 'Point' });

  clearButton.click();
  assert.equal(window.GIS.layers.getLayers().length, 1, 'first click only opens confirmation');
  assert.equal(calls.map, 0);
  assert.equal(typeof confirmClear, 'function');
  confirmClear();

  assert.equal(window.GIS.layers.getLayers().length, 0);
  assert.deepEqual(calls, { map: 1, renderer: 1, messages: ['已清空全部 1 个图层'] });
});

test('layer-panel clear button reports cleanup errors instead of claiming success', () => {
  const messages = [];
  let confirmClear;
  class Button {
    addEventListener(type, handler) { this[type] = handler; }
  }
  const clearButton = new Button();
  const document = { getElementById(id) { return id === 'clearAllLayersBtn' ? clearButton : null; } };
  const window = { GIS: {
    workspace: { confirmModal(title, message, callback) { confirmClear = callback; } },
    chat: { addMessage(message) { messages.push(message); } },
    map: {
      getLayer() { return null; }, removeLayer() {},
      clearAll() { return { ok: true, remaining: 0, errors: [new Error('layer cleanup failed')] }; },
    },
    renderers: { clearAllLayers() { return { ok: true, remaining: 0, errors: [] }; } },
  } };
  const context = { window, document, console, Promise, Set, Math, Date, Array, Object, String, Number };
  const sourcePath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  window.GIS.layers.init();
  window.GIS.layers.addLayer({ layer_id: 'cleanup-error-layer', filename: 'Cleanup error', geometry_type: 'Point' });

  clearButton.click();
  confirmClear();

  assert.equal(window.GIS.layers.getLayers().length, 0);
  assert.equal(messages.length, 1);
  assert.match(messages[0], /^清理未完全成功：/);
});

test('layer panel preserves hidden visibility from imported and shared-state records', () => {
  const visibilityCalls = [];
  const hiddenMapLayers = [];
  let window;
  const hiddenStateLayer = { layer_id: 'state-hidden', visible: false };
  const state = {
    getLayer(id) { return id === hiddenStateLayer.layer_id ? hiddenStateLayer : null; },
    addLayer(record) {
      window.GIS.layers.addLayer({ ...record, layer_id: hiddenStateLayer.layer_id, _panelSync: true }, true);
      return hiddenStateLayer;
    },
    setVisible(id, visible) { visibilityCalls.push({ id, visible }); },
  };
  window = { GIS: {
    state,
    map: {
      setLayerColor() {}, getLayer() { return null; },
      setLayerVisible(name, visible) { if (!visible) hiddenMapLayers.push(name); },
    },
  } };
  const document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
  const context = { window, document, console, Promise, Set, Math, Date, Array, Object, String, Number };
  const sourcePath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });

  window.GIS.layers.addLayer({ layer_id: 'import-hidden', filename: 'Imported hidden', visible: false });
  window.GIS.layers.addLayer({ layer_id: 'state-hidden', filename: 'State hidden', geojson: {
    type: 'FeatureCollection', features: [],
  }, visible: false });

  const records = window.GIS.layers.getLayers();
  assert.equal(records.find(layer => layer.layer_id === 'import-hidden').visible, false);
  assert.equal(records.find(layer => layer.layer_id === 'state-hidden').visible, false);
  assert.deepEqual(hiddenMapLayers.sort(), ['Imported hidden', 'state-hidden']);
  window.GIS.layers.toggleVisibility('state-hidden');
  assert.deepEqual(visibilityCalls, [{ id: 'state-hidden', visible: true }]);
});
