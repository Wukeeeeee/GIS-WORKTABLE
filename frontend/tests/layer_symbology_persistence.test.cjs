const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const layerSource = fs.readFileSync(path.resolve(__dirname, '../js/layers.js'), 'utf8');

function createLayers(features, applied = []) {
  const window = { GIS: { map: {
    loadGeoJSON() {}, setLayerColor() {}, setLayerVisible() {},
    applySymbology(_name, _geojson, styles) { applied.push(JSON.parse(JSON.stringify(styles))); },
    clearAll() { return { ok: true, remaining: 0 }; },
    removeLayer() {},
  } } };
  const document = { getElementById() { return null; } };
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String, Object, Array, JSON, Set, Map });
  vm.runInContext(layerSource, context, { filename: 'layers.js' });
  window.GIS.layers.addLayer({
    layer_id: 'population-layer', filename: '长沙区县', geojson: { type: 'FeatureCollection', features },
  }, true);
  return { layers: window.GIS.layers, applied };
}

function feature(fid, value) {
  return { type: 'Feature', properties: { _fid: fid, population: value },
    geometry: { type: 'Polygon', coordinates: [] } };
}

test('graduated symbology restores exact breaks, per-feature styles and legend by stable feature ID', () => {
  const original = [feature('adcode:1', 12), feature('adcode:2', 28), feature('adcode:3', 19)];
  const first = createLayers(original);
  first.layers.applyGraduatedColors('长沙区县', 'population', 2, 'ylorrd', 'quantile', [10, 20, 30], 0.2);
  const saved = first.layers.getSymbologyState('population-layer');
  assert.equal(saved.type, 'graduated');
  assert.equal(saved.method, 'quantile');
  assert.deepEqual(Array.from(saved.breaks), [10, 20, 30]);
  assert.equal(saved.fillOpacity, 0.2);
  assert.equal(saved.legendData.items.length, 2);

  const reordered = [original[2], original[0], original[1]].map(item => JSON.parse(JSON.stringify(item)));
  const restored = createLayers(reordered);
  assert.equal(restored.layers.restoreSymbologyState('population-layer', saved), true);
  const restoredStyles = restored.applied[0];
  assert.equal(restoredStyles[0].color, saved.featureStyles['fid:adcode:3'].color);
  assert.equal(restoredStyles[1].color, saved.featureStyles['fid:adcode:1'].color);
  assert.equal(restoredStyles[2].color, saved.featureStyles['fid:adcode:2'].color);
  assert.equal(restoredStyles[0].fillOpacity, 0.2);
});

test('symbology is not applied to changed feature data with missing saved IDs', () => {
  const original = [feature('adcode:1', 12), feature('adcode:2', 28)];
  const first = createLayers(original);
  first.layers.applyGraduatedColors('长沙区县', 'population', 2, 'ylorrd', 'quantile', [10, 20, 30], 0.2);
  const saved = first.layers.getSymbologyState('population-layer');
  const changed = createLayers([feature('adcode:1', 12), feature('new:3', 28)]);
  assert.equal(changed.layers.restoreSymbologyState('population-layer', saved), false);
  assert.equal(changed.applied.length, 0);
});

test('a failed field change keeps the last successful thematic style and legend', () => {
  const source = createLayers([feature('adcode:1', 12), feature('adcode:2', 28)]);
  assert.equal(source.layers.applyGraduatedColors('长沙区县', 'population', 2, 'ylorrd', 'quantile', [10, 20, 30], 0.2), true);
  const before = source.layers.getSymbologyState('population-layer');

  assert.equal(source.layers.applyGraduatedColors('长沙区县', 'missing_field', 4, 'blues', 'equal_interval'), false);
  const after = source.layers.getSymbologyState('population-layer');
  assert.deepEqual(JSON.parse(JSON.stringify(after)), JSON.parse(JSON.stringify(before)));
  assert.equal(source.applied.length, 1, 'a failed attempt must not redraw the map');
});

test('unique-value categories named like object prototype properties retain their styles', () => {
  const features = ['__proto__', 'constructor'].map((value, index) => ({
    type: 'Feature', properties: { _fid: 'kind:' + index, kind: value },
    geometry: { type: 'Polygon', coordinates: [] },
  }));
  const source = createLayers(features);
  assert.equal(source.layers.applyUniqueValues('长沙区县', 'kind', 'scheme'), true);
  const saved = source.layers.getSymbologyState('population-layer');
  assert.deepEqual(saved.legendData.items.map(item => item.label), ['__proto__', 'constructor']);
  assert.ok(saved.featureStyles['fid:kind:0'].color);
  assert.ok(saved.featureStyles['fid:kind:1'].color);
});

test('duplicate feature IDs fall back to saved feature order for thematic style restoration', () => {
  const data = [feature('duplicate', 12), feature('duplicate', 28)];
  const source = createLayers(data);
  assert.equal(source.layers.applyGraduatedColors('长沙区县', 'population', 2, 'ylorrd', 'quantile'), true);
  const saved = source.layers.getSymbologyState('population-layer');
  assert.ok(saved);
  assert.ok(saved.featureStyles['index:0']);
  assert.ok(saved.featureStyles['index:1']);
  const restored = createLayers(data.map(item => JSON.parse(JSON.stringify(item))));
  assert.equal(restored.layers.restoreSymbologyState('population-layer', saved), true);
  assert.deepEqual(restored.applied[0], source.applied[0]);
});
