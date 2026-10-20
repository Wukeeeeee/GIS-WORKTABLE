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
