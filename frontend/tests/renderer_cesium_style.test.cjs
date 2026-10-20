const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Color {
  constructor(red = 0, green = 0, blue = 0, alpha = 1) {
    this.red = red; this.green = green; this.blue = blue; this.alpha = alpha;
  }
  withAlpha(alpha) { return new Color(this.red, this.green, this.blue, alpha); }
  clone() { return new Color(this.red, this.green, this.blue, this.alpha); }
  getValue() { return this; }
  static fromCssColorString(value) {
    const hex = String(value || '#000000').replace('#', '');
    return new Color(
      parseInt(hex.slice(0, 2), 16) / 255,
      parseInt(hex.slice(2, 4), 16) / 255,
      parseInt(hex.slice(4, 6), 16) / 255,
      1,
    );
  }
}
Color.WHITE = new Color(1, 1, 1, 1);
Color.RED = new Color(1, 0, 0, 1);

function makeRendererHarness(options = {}) {
  const subscriptions = {};
  const sources = [];
  let releaseFirstLoad;
  const rec = {
    layer_id: 'styled-layer', name: 'Styled', visible: true, bbox: null,
    geojson: { type: 'FeatureCollection', features: [] },
    style: { color: '#ff0000', fillOpacity: 0.4, opacity: 0.5, weight: 2 },
  };
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
  const state = {
    on(event, callback) { subscriptions[event] = callback; },
    getLayers() { return [rec]; },
    clearSelection() {},
  };
  const elements = {
    map: { style: {}, parentNode: null },
    mapZoomControls: null,
    toggle3dBtn: null,
    mapCoords: {},
  };
  const noop = () => {};
  const document = {
    readyState: 'complete',
    body: {
      classList: { toggle: noop },
      appendChild(element) { if (element.id) elements[element.id] = element; },
    },
    addEventListener: noop,
    getElementById(id) { return elements[id] || null; },
    createElement() {
      return { id: '', style: {}, classList: { add: noop, remove: noop },
        setAttribute: noop, addEventListener: noop, appendChild: noop };
    },
  };
  const Cesium = {
    Viewer: function() { return viewer; },
    ImageryLayer: function(layer) { return layer; },
    UrlTemplateImageryProvider: function() {},
    ScreenSpaceEventHandler: function() { this.setInputAction = noop; },
    ScreenSpaceEventType: { LEFT_CLICK: 0, MOUSE_MOVE: 1 },
    Color,
    ColorMaterialProperty: function(color) { this.color = color; },
    PointGraphics: function(options) { Object.assign(this, options); },
    HeightReference: { CLAMP_TO_GROUND: 0 },
    LabelStyle: { FILL: 0 },
    Cartesian2: function(x, y) { this.x = x; this.y = y; },
    JulianDate: { now() { return 0; } },
    GeoJsonDataSource: {
      load(_geojson, style) {
        const entity = {
          polygon: { material: new Cesium.ColorMaterialProperty(style.fill) },
          polyline: { material: new Cesium.ColorMaterialProperty(style.stroke), width: style.strokeWidth },
          point: { color: style.stroke, pixelSize: 8 },
          properties: {},
        };
        const ds = { entities: { values: [entity] } };
        sources.push(ds);
        if (options.delayFirstLoad && sources.length === 1) {
          return new Promise(resolve => { releaseFirstLoad = () => resolve(ds); });
        }
        return Promise.resolve(ds);
      },
    },
    defined(value) { return !!value; },
  };
  const window = { GIS: { state }, Cesium };
  const context = { window, Cesium, document, console, setTimeout, Promise, Set, Map, Math, Number, Infinity };
  const sourcePath = path.resolve(__dirname, '../js/renderer_cesium.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return { renderer: window.GIS.renderers, subscriptions, sources, dataSources, rec,
    releaseFirstLoad: () => releaseFirstLoad && releaseFirstLoad() };
}

test('3D renderer applies updated layer color and opacity once from the shared style event', async () => {
  const harness = makeRendererHarness();
  await harness.renderer.toggle3D();
  await new Promise(resolve => setImmediate(resolve));

  let entity = harness.dataSources.items[0].entities.values[0];
  assert.ok(Math.abs(entity.polygon.material.color.alpha - 0.2) < 1e-9);
  assert.ok(Math.abs(entity.point.color.alpha - 0.5) < 1e-9);

  harness.rec.style = { color: '#0000ff', fillOpacity: 0.6, opacity: 0.5, weight: 4 };
  harness.subscriptions['layer-style'](harness.rec);
  await new Promise(resolve => setImmediate(resolve));

  entity = harness.dataSources.items[0].entities.values[0];
  assert.ok(entity.polygon.material.color.blue > 0.99);
  assert.ok(Math.abs(entity.polygon.material.color.alpha - 0.3) < 1e-9);
  assert.ok(entity.polyline.material.color.blue > 0.99);
  assert.equal(entity.polyline.width, 4);
  assert.ok(entity.point.color.blue > 0.99);

  harness.rec.style.opacity = 0.2;
  harness.subscriptions['layer-style'](harness.rec);
  entity = harness.dataSources.items[0].entities.values[0];
  assert.ok(Math.abs(entity.polygon.material.color.alpha - 0.12) < 1e-9);
  assert.ok(Math.abs(entity.point.color.alpha - 0.2) < 1e-9);
});

test('style changes during initial 3D load replace stale in-flight styling', async () => {
  const harness = makeRendererHarness({ delayFirstLoad: true });
  const toggle = harness.renderer.toggle3D();

  // toggle3D starts loading the original style but does not wait for GeoJSON parsing.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.sources.length, 1);
  harness.rec.style = { color: '#0000ff', fillOpacity: 0.6, opacity: 0.5, weight: 4 };
  harness.subscriptions['layer-style'](harness.rec);
  await new Promise(resolve => setImmediate(resolve));

  harness.releaseFirstLoad();
  await toggle;
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(harness.sources.length, 2);
  assert.equal(harness.dataSources.items.length, 1);
  const entity = harness.dataSources.items[0].entities.values[0];
  assert.ok(entity.polygon.material.color.blue > 0.99);
  assert.ok(Math.abs(entity.polygon.material.color.alpha - 0.3) < 1e-9);
  assert.equal(entity.polyline.width, 4);
});
