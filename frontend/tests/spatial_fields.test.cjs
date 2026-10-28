const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class SelectElement {
  constructor(value) { this.options = []; this.value = value || ''; }
  set innerHTML(html) {
    this._innerHTML = html;
    this.options = [{ value: '', selected: true }];
    this.value = '';
  }
  get innerHTML() { return this._innerHTML || ''; }
  appendChild(option) {
    this.options.push(option);
    if (option.selected || (!this.value && option.value)) this.value = option.value;
  }
}

test('spatial statistics fields include numeric values appearing after null first features', async () => {
  const layerIds = [
    'bufferLayer', 'overlayLayerA', 'overlayLayerB', 'clipLayer', 'clipByLayer',
    'geomLayer', 'selectLayer', 'selectSourceLayer', 'statsLayer', 'statsJoinLayer',
  ];
  const elements = new Map(layerIds.map(id => [id, new SelectElement(id === 'geomLayer' || id === 'selectLayer' || id === 'statsLayer' ? 'Population' : '')]));
  elements.set('geomDissolveFieldSel', new SelectElement());
  elements.set('selectAttrFieldSel', new SelectElement());
  elements.set('statsFieldSel', new SelectElement('pop'));
  const document = {
    addEventListener() {},
    getElementById(id) { return elements.get(id) || null; },
    createElement() { return {}; },
  };
  const geojson = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { pop: null, district: 'A' }, geometry: null },
    { type: 'Feature', properties: JSON.parse('{"pop":125,"district":"B","constructor":8,"__proto__":9}'), geometry: null },
    { type: 'Feature', properties: { pop: 142 }, geometry: null },
  ] };
  const window = { GIS: {
    api: { BASE_URL: '' },
    layers: {
      getLayerNames() { return ['Population', 'constructor', '__proto__']; },
      getLayerByName(name) { return name === 'Population' ? { geojson } : null; },
    },
  } };
  const sourcePath = path.resolve(__dirname, '../js/spatial.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document,
    fetch() { return Promise.resolve({ json() { return Promise.resolve({ names: [] }); } }); },
    Promise, Array, Object, String, Number, Math, Date, Set, Map, console: { log() {}, warn() {} },
  }, { filename: sourcePath });

  window.GIS.spatial.refreshLayers();
  await new Promise(resolve => setImmediate(resolve));

  const statsOptions = elements.get('statsFieldSel').options.map(option => option.value);
  assert.ok(statsOptions.includes('pop'));
  assert.ok(statsOptions.includes('constructor'), 'valid numeric fields may shadow Object.prototype names');
  assert.ok(statsOptions.includes('__proto__'), 'own __proto__ data fields must remain selectable');
  assert.equal(elements.get('statsFieldSel').value, 'pop');
  assert.equal(statsOptions.includes('_fid'), false);
  assert.ok(elements.get('bufferLayer').options.some(option => option.value === 'constructor'));
  assert.ok(elements.get('bufferLayer').options.some(option => option.value === '__proto__'));
});

test('cluster panel rejects invalid parameters instead of silently substituting defaults', () => {
  const sourcePath = path.resolve(__dirname, '../js/spatial.js');
  const source = fs.readFileSync(sourcePath, 'utf8').replace(
    'GIS.spatial = {', 'GIS.spatial = { _runOperationForTest: _runOperation,',
  );
  let invokeCount = 0;
  const values = { geomLayer: 'Sites', geomOp: 'cluster', geomClusterMin: '3' };
  const document = { addEventListener() {}, getElementById(id) { return { value: values[id] }; } };
  const window = { GIS: { api: { invokeTool() { invokeCount += 1; } } } };
  vm.runInNewContext(source, { window, document, Promise, Array, Object, String, Number, Math, Date, Set, Map });

  for (const eps of ['0', '', 'NaN', 'Infinity', '-0.1']) {
    values.geomClusterEps = eps;
    assert.throws(() => window.GIS.spatial._runOperationForTest('geom', {}), /聚类半径必须为有限正数/);
  }
  for (const minSamples of ['0', '2.5', '']) {
    values.geomClusterEps = '0.01';
    values.geomClusterMin = minSamples;
    assert.throws(() => window.GIS.spatial._runOperationForTest('geom', {}), /最小点数必须为正整数/);
  }
  assert.equal(invokeCount, 0);
});

test('cluster panel forwards the selected distance unit to the existing tool', async () => {
  const sourcePath = path.resolve(__dirname, '../js/spatial.js');
  const source = fs.readFileSync(sourcePath, 'utf8').replace(
    'GIS.spatial = {', 'GIS.spatial = { _runOperationForTest: _runOperation,',
  );
  const values = {
    geomLayer: 'Sites', geomOp: 'cluster', geomClusterEps: '500',
    geomClusterMin: '2', geomClusterUnit: 'm',
  };
  let invoked;
  const document = {
    addEventListener() {},
    getElementById(id) {
      if (id === 'spatialResult' || id === 'spatialLoader') return { style: {} };
      if (id === 'spatialResultBody') return { textContent: '' };
      return { value: values[id] };
    },
    querySelectorAll() { return []; },
  };
  const window = { GIS: { api: { invokeTool(tool, args) { invoked = { tool, args }; return new Promise(() => {}); } } } };
  vm.runInNewContext(source, { window, document, Promise, Array, Object, String, Number, Math, Date, Set, Map });

  window.GIS.spatial._runOperationForTest('geom', {});
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(invoked.tool, 'spatial_cluster');
  assert.equal(invoked.args.eps, 500);
  assert.equal(invoked.args.distance_unit, 'm');
  assert.equal(invoked.args.min_samples, 2);
});

test('sample panel rejects invalid or empty input instead of substituting a count or fraction', () => {
  const sourcePath = path.resolve(__dirname, '../js/spatial.js');
  const source = fs.readFileSync(sourcePath, 'utf8').replace(
    'GIS.spatial = {', 'GIS.spatial = { _runOperationForTest: _runOperation,',
  );
  const values = { selectLayer: 'Sites', selectMode: 'sample', selectSampleN: '' };
  let invokeCount = 0;
  const document = { addEventListener() {}, getElementById(id) { return { value: values[id] }; } };
  const window = { GIS: { api: { invokeTool() { invokeCount += 1; } } } };
  vm.runInNewContext(source, { window, document, Promise, Array, Object, String, Number, Math, Date, Set, Map });

  for (const raw of ['', '0', '0.0', 'abc', '1.5', '-0.2']) {
    values.selectSampleN = raw;
    assert.throws(() => window.GIS.spatial._runOperationForTest('select', {}));
  }
  assert.equal(invokeCount, 0);
});

test('spatial layer selectors disambiguate legacy Unicode aliases and preserve exact values', () => {
  const select = new SelectElement('');
  const document = {
    addEventListener() {},
    getElementById(id) { return id === 'bufferLayer' ? select : null; },
    createElement() { return {}; },
    querySelectorAll() { return []; },
  };
  const window = { GIS: { map: { loadGeoJSON() {} } } };
  const context = { window, document, Promise, Array, Object, String, Number, Math, Date, Set, Map };
  const statePath = path.resolve(__dirname, '../js/gis_state.js');
  vm.runInNewContext(fs.readFileSync(statePath, 'utf8'), context, { filename: statePath });
  const spatialPath = path.resolve(__dirname, '../js/spatial.js');
  const spatialSource = fs.readFileSync(spatialPath, 'utf8').replace(
    'GIS.spatial = {', 'GIS.spatial = { _fillLayerSelectsForTest: _fillLayerSelects,',
  );
  vm.runInNewContext(spatialSource, context, { filename: spatialPath });

  window.GIS.spatial._fillLayerSelectsForTest(['é.geojson', 'e\u0301.geojson']);

  assert.deepEqual(select.options.map(option => [option.value, option.textContent]), [
    ['', undefined],
    ['é.geojson', 'é.geojson (1)'],
    ['e\u0301.geojson', 'e\u0301.geojson (2)'],
  ]);
});
