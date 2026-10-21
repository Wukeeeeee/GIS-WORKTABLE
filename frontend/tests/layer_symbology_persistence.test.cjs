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
  const instrumentedSource = layerSource.replace('  GIS.layers = {',
    '  GIS.__applySymbologyForTest = _applySymbology;\n  GIS.layers = {');
  vm.runInContext(instrumentedSource, context, { filename: 'layers.js' });
  window.GIS.layers.addLayer({
    layer_id: 'population-layer', filename: '长沙区县', geojson: { type: 'FeatureCollection', features },
  }, true);
  return { layers: window.GIS.layers, applied, applySymbology: window.GIS.__applySymbologyForTest };
}

function feature(fid, value, geometryType = 'Polygon') {
  return { type: 'Feature', properties: { _fid: fid, population: value },
    geometry: { type: geometryType, coordinates: [] } };
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

test('graduated symbology gives null and non-numeric values a counted no-data style', () => {
  const source = createLayers([
    feature('adcode:1', 12), feature('adcode:2', 28),
    feature('adcode:3', null), feature('adcode:4', 'N/A'),
  ]);
  assert.equal(source.layers.applyGraduatedColors('长沙区县', 'population', 2, 'ylorrd', 'equal_interval'), true);

  const styles = source.applied[0];
  assert.notEqual(styles[2].color, styles[0].color);
  assert.equal(styles[2].color, '#9ca3af');
  assert.equal(styles[3].color, '#9ca3af');
  const legend = source.layers.getSymbologyState('population-layer').legendData.items;
  assert.deepEqual(JSON.parse(JSON.stringify(legend.at(-1))), { label: '无数据', color: '#9ca3af', count: 2 });
});

test('graduated symbology does not parse numeric prefixes from malformed text values', () => {
  const source = createLayers([
    feature('adcode:1', 10), feature('adcode:2', '15'), feature('adcode:3', '20 people'),
  ]);
  assert.equal(source.layers.applyGraduatedColors('长沙区县', 'population', 2, 'ylorrd', 'equal_interval'), true);

  const styles = source.applied[0];
  assert.notEqual(styles[1].color, '#9ca3af', 'numeric strings remain valid values');
  assert.equal(styles[2].color, '#9ca3af');
  const legend = source.layers.getSymbologyState('population-layer').legendData.items;
  assert.deepEqual(JSON.parse(JSON.stringify(legend.at(-1))), { label: '无数据', color: '#9ca3af', count: 1 });
});

test('graduated symbology keeps no-data separate when valid values are identical', () => {
  const source = createLayers([
    feature('adcode:1', 12), feature('adcode:2', 12), feature('adcode:3', null),
  ]);
  assert.equal(source.layers.applyGraduatedColors('长沙区县', 'population', 3, 'ylorrd', 'quantile'), true);

  const styles = source.applied[0];
  assert.notEqual(styles[2].color, styles[0].color);
  const legend = source.layers.getSymbologyState('population-layer').legendData.items;
  assert.deepEqual(JSON.parse(JSON.stringify(legend.at(-1))), { label: '无数据', color: '#9ca3af', count: 1 });
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

test('graduated symbols reject malformed numeric prefixes and style missing values as no-data', () => {
  const source = createLayers([
    feature('line:1', 10, 'LineString'), feature('line:2', 20, 'LineString'),
    feature('line:3', '20 people', 'LineString'), feature('line:4', null, 'LineString'),
  ]);
  source.applySymbology('population-layer', 'graduated-symbol', 'population', 2, 'blues', 3, 11);

  const styles = source.applied[0];
  assert.equal(styles[0].weight, 3);
  assert.equal(styles[1].weight, 11);
  assert.equal(styles[2].color, '#9ca3af');
  assert.equal(styles[3].color, '#9ca3af');
  assert.equal(styles[2].weight, 3);
  assert.equal(source.layers.getSymbologyState('population-layer').featureStyleCount, 4);
});

test('graduated symbols with equal values keep a single-class style', () => {
  const source = createLayers([
    feature('line:1', 7, 'LineString'), feature('line:2', 7, 'LineString'),
  ]);
  source.applySymbology('population-layer', 'graduated-symbol', 'population', 4, 'blues', 2, 14);

  assert.equal(source.applied[0][0].weight, 2);
  assert.equal(source.applied[0][1].weight, 2);
});

test('a failed graduated-symbol field change preserves the previous style state', () => {
  const source = createLayers([
    feature('line:1', 10, 'LineString'), feature('line:2', 20, 'LineString'),
  ]);
  source.applySymbology('population-layer', 'graduated-symbol', 'population', 2, 'blues', 3, 11);
  const before = source.layers.getSymbologyState('population-layer');

  source.applySymbology('population-layer', 'graduated-symbol', 'missing_field', 4, 'reds', 4, 16);

  assert.deepEqual(JSON.parse(JSON.stringify(source.layers.getSymbologyState('population-layer'))),
    JSON.parse(JSON.stringify(before)));
  assert.equal(source.applied.length, 1, 'invalid field must not redraw or clear the existing map style');
});

test('proportional symbols reject malformed prefixes and non-positive values', () => {
  const source = createLayers([
    feature('point:1', 10, 'Point'), feature('point:2', 20, 'Point'),
    feature('point:3', '20 people', 'Point'), feature('point:4', 0, 'Point'),
  ]);
  source.applySymbology('population-layer', 'proportional', 'population', 2, 'blues', 3, 11);

  const styles = source.applied[0];
  assert.equal(styles[0].radius, 3);
  assert.equal(styles[1].radius, 11);
  assert.equal(styles[2].color, '#9ca3af');
  assert.equal(styles[3].color, '#9ca3af');
  assert.equal(styles[2].radius, 3);
});

test('graduated-symbol legend is stored and opening it does not replace the applied style', () => {
  const source = createLayers([
    feature('line:1', 10, 'LineString'), feature('line:2', 20, 'LineString'),
    feature('line:3', null, 'LineString'),
  ]);
  source.applySymbology('population-layer', 'graduated-symbol', 'population', 2, 'blues', 3, 11);

  const before = source.layers.getSymbologyState('population-layer');
  assert.equal(before.legendData.type, 'graduated-symbol');
  assert.equal(before.legendData.items.length, 3);
  assert.match(before.legendData.items[0].label, /线宽 3px/);
  assert.deepEqual(JSON.parse(JSON.stringify(before.legendData.items.at(-1))), {
    label: '无数据 · 线宽 3px', color: '#9ca3af', size: 3, count: 1,
  });

  source.layers.addLegend('长沙区县');
  assert.equal(source.layers.getSymbologyState('population-layer').type, 'graduated-symbol');
  assert.equal(source.applied.length, 1, 'opening the legend must not reapply graduated colors');
});

test('proportional legend records min/max sizes and opening it preserves proportional styling', () => {
  const source = createLayers([
    feature('point:1', 10, 'Point'), feature('point:2', 20, 'Point'),
    feature('point:3', 0, 'Point'),
  ]);
  source.applySymbology('population-layer', 'proportional', 'population', 2, 'blues', 3, 11);

  const legend = source.layers.getSymbologyState('population-layer').legendData;
  assert.equal(legend.type, 'proportional');
  assert.equal(legend.items[0].size, 3);
  assert.equal(legend.items[1].size, 11);
  assert.equal(legend.items[2].count, 1);
  source.layers.addLegend('长沙区县');
  assert.equal(source.layers.getSymbologyState('population-layer').type, 'proportional');
  assert.equal(source.applied.length, 1);
});

test('legacy symbol styles rebuild their legend without changing restored feature styles', () => {
  const scenarios = [
    { type: 'graduated-symbol', features: [feature('line:1', 10, 'LineString'), feature('line:2', 20, 'LineString')],
      apply(source) { source.applySymbology('population-layer', this.type, 'population', 2, 'blues', 3, 11); } },
    { type: 'proportional', features: [feature('point:1', 10, 'Point'), feature('point:2', 20, 'Point')],
      apply(source) { source.applySymbology('population-layer', this.type, 'population', 2, 'blues', 3, 11); } },
  ];

  scenarios.forEach(function(scenario) {
    const original = createLayers(scenario.features);
    scenario.apply(original);
    const legacyState = original.layers.getSymbologyState('population-layer');
    delete legacyState.legendData;

    const restored = createLayers(scenario.features.map(item => JSON.parse(JSON.stringify(item))));
    assert.equal(restored.layers.restoreSymbologyState('population-layer', legacyState), true);
    const stylesBeforeLegend = JSON.parse(JSON.stringify(restored.applied[0]));
    restored.layers.addLegend('长沙区县');

    assert.equal(restored.layers.getSymbologyState('population-layer').legendData.type, scenario.type);
    assert.deepEqual(restored.applied[0], stylesBeforeLegend, 'legend recovery must not reapply a different style');
    assert.equal(restored.applied.length, 1);
  });
});
