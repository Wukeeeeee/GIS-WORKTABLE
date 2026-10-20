const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor() {
    this.style = {};
    this.listeners = {};
    this.attributes = {};
    this._classes = new Set();
    this.classList = {
      add: name => this._classes.add(name),
      remove: name => this._classes.delete(name),
      contains: name => this._classes.has(name),
      toggle: (name, force) => {
        if (force === undefined) force = !this._classes.has(name);
        force ? this._classes.add(name) : this._classes.delete(name);
      },
    };
  }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] || null; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 800, height: 600 }; }
}

function createHarness() {
  const elements = new Map();
  const getElement = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const mapElement = getElement('map');
  const drawButtons = ['polygon', 'delete', 'feature-info'].map(tool => {
    const button = new Element();
    button.dataset = { tool };
    return button;
  });
  const toolbar = getElement('mapZoomControls');
  const mapLayers = [];
  const map = {
    handlers: {},
    on(name, callback) { this.handlers[name] = callback; },
    off(name, callback) { if (this.handlers[name] === callback) delete this.handlers[name]; },
    addLayer(layer) { if (!mapLayers.includes(layer)) mapLayers.push(layer); return this; },
    removeLayer(layer) { const index = mapLayers.indexOf(layer); if (index >= 0) mapLayers.splice(index, 1); return this; },
    eachLayer(callback) { mapLayers.slice().forEach(callback); },
    hasLayer(layer) { return mapLayers.includes(layer); },
    getContainer() { return mapElement; },
    attributionControl: { setPrefix() {} },
    invalidateSize() {},
  };
  class FeatureGroup {
    constructor() { this.handlers = {}; this.layers = []; }
    on(name, callback) { this.handlers[name] = callback; }
    off(name, callback) { if (this.handlers[name] === callback) delete this.handlers[name]; }
    clearLayers() { this.layers = []; }
    eachLayer(callback) { this.layers.slice().forEach(callback); }
    getLayers() { return this.layers.slice(); }
    addLayer(layer) { this.layers.push(layer); }
  }
  const drawState = { enabled: 0, disabled: 0 };
  function DrawTool() {}
  DrawTool.prototype.enable = function() { drawState.enabled++; };
  DrawTool.prototype.disable = function() { drawState.disabled++; };
  class TileLayer { addTo(target) { target.addLayer(this); return this; } }
  class Canvas {}
  Canvas.extend = function() { return class extends Canvas {}; };
  const L = {
    Canvas, TileLayer, FeatureGroup,
    Draw: { Event: { CREATED: 'draw:created', DELETED: 'draw:deleted' }, Polygon: DrawTool,
      Rectangle: DrawTool, Circle: DrawTool, Polyline: DrawTool, Marker: DrawTool },
    map() { return map; },
    control: { scale() { return { addTo() {} }; } },
  };
  const document = {
    getElementById(id) { return elements.get(id) || null; },
    querySelectorAll(selector) { return selector === '.map-draw-btn' ? drawButtons : []; },
    querySelector(selector) {
      if (selector === '.map-draw-btn.active:not([data-tool="delete"])') return drawButtons.find(b => b.classList.contains('active')) || null;
      if (selector === '.map-coords' || selector === '.map-zoom-label') return new Element();
      return null;
    },
    addEventListener() {},
  };
  const localStorage = { getItem() { return 'light'; }, setItem() {} };
  const window = { GIS: {}, addEventListener() {} };
  const context = { window, document, localStorage, L, console, Promise, Set, Map, Math, Number, String,
    Array, Object, Date, JSON, setTimeout() { return 1; }, clearTimeout() {} };
  const sourcePath = path.resolve(__dirname, '../js/map.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  window.GIS.map.init(mapElement);
  const clickTool = button => toolbar.listeners.click[0]({ target: { closest(selector) { return selector === '.map-draw-btn' ? button : null; } } });
  return { mapApi: window.GIS.map, map, mapElement, toolbar, drawButtons, drawnItems: mapLayers.find(layer => layer instanceof FeatureGroup), drawState, clickTool };
}

test('clear map exits delete mode and cancels an active drawing handler', () => {
  const h = createHarness();
  h.clickTool(h.drawButtons[1]);
  assert.equal(h.mapElement.style.cursor, 'crosshair');

  h.mapApi.clearAll();
  assert.equal(h.mapElement.style.cursor, '');
  assert.equal(h.drawButtons[1].classList.contains('active'), false);
  assert.equal(h.drawnItems.handlers.click, undefined);

  h.clickTool(h.drawButtons[0]);
  assert.equal(h.drawState.enabled, 1);
  h.mapApi.clearAll();
  assert.equal(h.drawState.disabled, 1);
  assert.equal(h.drawButtons[0].classList.contains('active'), false);
});

test('clear map exits feature-info mode so the next drawn feature is not intercepted', () => {
  const h = createHarness();
  h.clickTool(h.drawButtons[2]);
  assert.equal(typeof h.drawnItems.handlers.click, 'function');
  assert.equal(h.mapElement.style.cursor, 'crosshair');

  h.mapApi.clearAll();

  assert.equal(h.drawnItems.handlers.click, undefined);
  assert.equal(h.mapElement.style.cursor, '');
  assert.equal(h.drawButtons[2].classList.contains('active'), false);
});
