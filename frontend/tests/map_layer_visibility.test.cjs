const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function createHarness() {
  const layers = new Map();
  const activeLayers = new Set();
  const fitBoundsCalls = [];
  let zoom = 8;
  const mapInstance = {
    getZoom() { return zoom; },
    hasLayer(layer) { return activeLayers.has(layer); },
    addLayer(layer) { activeLayers.add(layer); return this; },
    removeLayer(layer) { activeLayers.delete(layer); return this; },
    fitBounds(bounds, options) { fitBoundsCalls.push({ bounds, options }); },
  };
  const L = { geoJSON() { return {
    addTo(map) { map.addLayer(this); return this; },
    getBounds() { return {}; },
  }; } };
  const window = { GIS: {} };
  const document = { getElementById() { return null; } };
  const source = fs.readFileSync(path.resolve(__dirname, '../js/map.js'), 'utf8')
    .replace('GIS.map = {', [
      'GIS.__setMapInstanceForTest = function(value) { mapInstance = value; };',
      'GIS.__setTestLayer = function(name, layer) { layers[name] = layer; };',
      'GIS.map = {',
    ].join('\n'));
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String,
    Object, Array, JSON, Set, Map, URL, Blob, L, XMLSerializer: class {}, Image: class {} });
  vm.runInContext(source, context, { filename: 'map.js' });
  window.GIS.__setMapInstanceForTest(mapInstance);
  const layer = {};
  window.GIS.__setTestLayer('demo', layer);
  return { map: window.GIS.map, mapInstance, layer, fitBoundsCalls,
    setMapInstance: window.GIS.__setMapInstanceForTest, setZoom(value) { zoom = value; } };
}

test('toggleLayer keeps user visibility when scale visibility is recalculated', () => {
  const { map, mapInstance, layer } = createHarness();
  map.setLayerScaleRange('demo', 5, 10);
  assert.equal(mapInstance.hasLayer(layer), true);

  map.toggleLayer('demo');
  assert.equal(mapInstance.hasLayer(layer), false);

  map.setLayerScaleRange('demo', 5, 10);
  assert.equal(mapInstance.hasLayer(layer), false);
});

test('fitLayer reports whether valid rendered bounds were actually applied', () => {
  const { map, layer, fitBoundsCalls } = createHarness();
  assert.equal(map.fitLayer('missing'), false);
  assert.equal(map.fitLayer('demo'), false);
  layer.getBounds = () => ({ isValid: () => false });
  assert.equal(map.fitLayer('demo'), false);
  assert.equal(fitBoundsCalls.length, 0);
  layer.getBounds = () => ({ isValid: () => true });
  assert.equal(map.fitLayer('demo'), true);
  assert.equal(fitBoundsCalls.length, 1);
});

test('view operations report an uninitialized map instead of claiming success', () => {
  const { map, mapInstance, setMapInstance } = createHarness();
  mapInstance.setView = () => {};
  assert.equal(map.setView([0, 0], 0), true);
  setMapInstance(null);
  assert.equal(map.setView([0, 0], 0), false);
  assert.equal(map.fitLayer('demo'), false);
});

test('toggleLayer changes user visibility while the scale range currently hides the layer', () => {
  const { map, mapInstance, layer, setZoom } = createHarness();
  map.setLayerScaleRange('demo', 10, 12);
  assert.equal(mapInstance.hasLayer(layer), false);

  map.toggleLayer('demo');
  setZoom(10);
  map.setLayerScaleRange('demo', 10, 12);
  assert.equal(mapInstance.hasLayer(layer), false);
});

test('loadGeoJSON can render a newly shown layer without changing the current map extent', () => {
  const { map, fitBoundsCalls } = createHarness();
  const geojson = { type: 'FeatureCollection', features: [] };

  map.loadGeoJSON(geojson, 'show-without-fit', {}, { fitBounds: false });
  assert.equal(map.getLayer('show-without-fit') !== null, true);
  assert.equal(fitBoundsCalls.length, 0);

  map.loadGeoJSON(geojson, 'default-fit');
  assert.equal(fitBoundsCalls.length, 1, 'existing callers still fit the view by default');
});

test('applying thematic styles preserves user visibility and scale visibility', () => {
  const { map, mapInstance } = createHarness();
  const geojson = { type: 'FeatureCollection', features: [] };
  map.loadGeoJSON(geojson, 'thematic-layer');
  map.setLayerScaleRange('thematic-layer', 5, 10);
  map.setLayerVisible('thematic-layer', false);

  map.applySymbology('thematic-layer', geojson, {});

  assert.equal(mapInstance.hasLayer(map.getLayer('thematic-layer')), false,
    'replacing a hidden layer for thematic styling must not make it visible');

  map.loadGeoJSON(geojson, 'scale-hidden-layer');
  map.setLayerScaleRange('scale-hidden-layer', 10, 12);
  assert.equal(mapInstance.hasLayer(map.getLayer('scale-hidden-layer')), false);
  map.applySymbology('scale-hidden-layer', geojson, {});
  assert.equal(mapInstance.hasLayer(map.getLayer('scale-hidden-layer')), false,
    'replacement must be re-evaluated against the current zoom range');
});
