const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function createHarness() {
  const layers = new Map();
  const activeLayers = new Set();
  const fitBoundsCalls = [];
  const attributionValues = [];
  let zoom = 8;
  const mapInstance = {
    getZoom() { return zoom; },
    hasLayer(layer) { return activeLayers.has(layer); },
    addLayer(layer) { activeLayers.add(layer); return this; },
    removeLayer(layer) { activeLayers.delete(layer); return this; },
    eachLayer(callback) { renderedFeatures.forEach(callback); },
    fitBounds(bounds, options) { fitBoundsCalls.push({ bounds, options }); },
  };
  const renderedFeatures = [];
  const makeOverlay = (url, options = {}) => ({
    url,
    options,
    addTo(map) { map.addLayer(this); return this; },
  });
  const L = { geoJSON(geojson, options = {}) {
    const features = geojson.type === 'FeatureCollection' ? (geojson.features || []) : [geojson];
    features.forEach(feature => {
      const leafletLayer = {
        tooltip: null,
        feature,
        bindTooltip(text, config) { this.tooltip = { text, config }; },
        unbindTooltip() { this.tooltip = null; },
        on() {},
      };
      renderedFeatures.push(leafletLayer);
      if (options.onEachFeature) options.onEachFeature(feature, leafletLayer);
    });
    return {
    addTo(map) { map.addLayer(this); return this; },
    getBounds() { return {}; },
  }; }, CircleMarker: class {}, latLng(lat, lng) { return { lat, lng }; },
  latLngBounds(southWest, northEast) { return { southWest, northEast }; },
  imageOverlay(url, _bounds, options) { attributionValues.push(options.attribution); return makeOverlay(url, options); },
  tileLayer(url, options) { attributionValues.push(options.attribution); return makeOverlay(url, options); } };
  L.tileLayer.wms = function(url, options) {
    attributionValues.push(options.attribution);
    return makeOverlay(url, options);
  };
  const window = { GIS: {} };
  const document = { getElementById() { return null; }, addEventListener() {} };
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
  return { map: window.GIS.map, mapInstance, layer, fitBoundsCalls, activeLayers, renderedFeatures,
    attributionValues,
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

test('style mutations report failure when no rendered map layer can be updated', () => {
  const { map, layer } = createHarness();
  assert.equal(map.setLayerColor('missing', '#ff0000'), false);
  assert.equal(map.setLayerStyle('missing', { color: '#ff0000' }), false);
  assert.equal(map.setLayerColor('demo', '#ff0000'), false, 'a panel record without a style-capable map object is not success');
  assert.equal(map.setLayerStyle('demo', { color: '#ff0000' }), false);

  const calls = [];
  layer.setStyle = style => calls.push(style);
  assert.equal(map.setLayerColor('demo', '#ff0000'), true);
  assert.equal(map.setLayerStyle('demo', { weight: 4 }), true);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    { color: '#ff0000', fillColor: '#ff0000' },
    { weight: 4 },
  ]);
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

test('raster overlays replace a restored overlay by stable layer id after rerun', () => {
  const { map, activeLayers } = createHarness();
  const bounds = [0, 0, 1, 1];

  map.addImageOverlay('/old.png', bounds, 'project_layer_1', 'dem_slope');
  const restoredOverlay = [...activeLayers][0];
  map.addImageOverlay('/new.png', bounds, 'dem_slope.png', 'dem_slope');

  assert.equal(activeLayers.size, 1, 'rerunning a raster should not leave a duplicate map overlay');
  assert.equal(activeLayers.has(restoredOverlay), false);
  assert.equal(map.getLayer('dem_slope.png').url, '/new.png');
});

test('raster, XYZ, and WMS layer attributions escape provider-controlled names as text', () => {
  const { map, attributionValues } = createHarness();
  const unsafeName = '<img src=x onerror="alert(1)">';

  map.addImageOverlay('/preview.png', [0, 0, 1, 1], unsafeName, 'raster-id');
  map.addTileLayer('https://tiles.example/{z}/{x}/{y}.png', unsafeName);
  map.addWmsLayer('https://maps.example/wms', 'roads', unsafeName, {
    attribution: '<svg onload="alert(2)">',
  });

  assert.deepEqual(JSON.parse(JSON.stringify(attributionValues)), [
    '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;',
    '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;',
    '&lt;svg onload=&quot;alert(2)&quot;&gt;',
  ]);
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

test('applySymbology reports whether a rendered map layer accepted the style change', () => {
  const { map } = createHarness();
  const geojson = { type: 'FeatureCollection', features: [] };

  assert.equal(map.applySymbology('missing-layer', geojson, {}), false);
  map.loadGeoJSON(geojson, 'rendered-layer');
  assert.equal(map.applySymbology('rendered-layer', geojson, {}), true);
});

test('setLabels reports visible labels, preserves the previous config on an invalid field, and handles zero values', () => {
  const { map, renderedFeatures } = createHarness();
  map.loadGeoJSON({ type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { label: 0 }, geometry: { type: 'Point', coordinates: [0, 0] } },
    { type: 'Feature', properties: { label: null }, geometry: { type: 'Point', coordinates: [1, 1] } },
  ] }, 'labeled-layer');

  assert.equal(map.setLabels('labeled-layer', 'label'), true);
  assert.equal(renderedFeatures[0].tooltip.text, '0');
  assert.equal(renderedFeatures[1].tooltip, null);
  assert.equal(map.setLabels('labeled-layer', 'missing'), false);
  assert.equal(renderedFeatures[0].tooltip.text, '0', 'a failed field change must leave the prior label visible');
  assert.equal(map.setLabels('missing-layer', 'label'), false);
});

test('feature labels and chart-link tooltips render untrusted properties as text', () => {
  const { map, renderedFeatures } = createHarness();
  map.loadGeoJSON({ type: 'FeatureCollection', features: [
    { type: 'Feature', properties: {
      label: '<img src=x onerror=alert(1)>',
      chart: '<svg onload=alert(2)>',
    }, geometry: { type: 'Point', coordinates: [0, 0] } },
  ] }, 'untrusted-tooltip-layer');

  assert.equal(map.setLabels('untrusted-tooltip-layer', 'label'), true);
  assert.equal(renderedFeatures[0].tooltip.text, '&lt;img src=x onerror=alert(1)&gt;');
  map.enableChartLink('untrusted-tooltip-layer', 'chart');
  assert.equal(renderedFeatures[0].tooltip.text, '&lt;svg onload=alert(2)&gt;');
});
