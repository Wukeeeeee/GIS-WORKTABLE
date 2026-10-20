const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function element(rect, computed = {}) {
  return {
    style: {}, clientWidth: rect.width, clientHeight: rect.height,
    getBoundingClientRect() { return rect; },
    querySelectorAll() { return []; },
    cloneNode() {
      const clone = element(rect);
      clone.attributes = {};
      clone.setAttribute = (name, value) => { clone.attributes[name] = value; };
      clone.querySelectorAll = () => [clone.child];
      clone.child = element(rect);
      clone.child.setAttribute = (name, value) => { clone.child.attributes[name] = value; };
      clone.child.attributes = {};
      return clone;
    },
    computed,
  };
}

test('map export draws Leaflet SVG vector overlays before map labels and legend', async () => {
  const rect = { left: 15, top: 25, width: 50, height: 30 };
  const svg = element(rect, { fill: 'none', stroke: 'rgb(30, 60, 90)' });
  svg.tagName = 'svg';
  svg.querySelectorAll = selector => selector === '*' ? [element(rect, { fill: 'rgb(1, 2, 3)', 'stroke-width': '2px' })] : [];
  const canvas = element(rect);
  canvas.tagName = 'canvas';
  canvas.width = 50;
  canvas.height = 30;
  const mapRect = { left: 10, top: 20, width: 100, height: 80 };
  const mapEl = {
    getBoundingClientRect() { return mapRect; },
    querySelectorAll(selector) {
      if (selector === '.leaflet-pane svg, .leaflet-pane canvas') return [canvas, svg];
      return [];
    },
  };
  const drawCalls = [];
  const ctx = {
    fillRect() {}, drawImage(...args) { drawCalls.push(args); }, save() {}, restore() {},
    beginPath() {}, rect() {}, clip() {}, strokeRect() {}, fillText() {},
  };
  const serialized = [];
  class FakeImage { set src(_value) { queueMicrotask(() => this.onload()); } }
  const window = { GIS: {}, getComputedStyle(node) {
    return { display: 'block', font: '', fontSize: '12px', color: '#333',
      getPropertyValue(name) { return node.computed[name] || ''; } };
  } };
  const document = { getElementById() { return null; } };
  const URL = { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} };
  class XMLSerializer { serializeToString(node) { serialized.push(node); return '<svg />'; } }
  const source = fs.readFileSync(path.resolve(__dirname, '../js/map.js'), 'utf8')
    .replace('GIS.map = {', 'GIS.__drawMapCompositionForTest = _drawMapComposition;\n  GIS.map = {');
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String,
    Object, Array, JSON, Set, Map, URL, XMLSerializer, Blob, Image: FakeImage });
  vm.runInContext(source, context, { filename: 'map.js' });

  await window.GIS.__drawMapCompositionForTest(ctx, mapEl, 100, 80);
  assert.equal(drawCalls.length, 2, JSON.stringify(drawCalls.map(call => call[0] === canvas ? 'canvas' : 'svg')));
  assert.equal(drawCalls[0][0], canvas, 'Canvas output stays below the following SVG layer');
  assert.deepEqual(drawCalls[0].slice(1), [5, 5, 50, 30]);
  assert.deepEqual(drawCalls[1].slice(1), [5, 5, 50, 30]);
  assert.equal(serialized.length, 1);
  assert.equal(serialized[0].attributes.stroke, 'rgb(30, 60, 90)');
  assert.equal(serialized[0].child.attributes['stroke-width'], '2px');
});

test('PDF layout embeds the current thematic legend and restores the map legend visibility', async () => {
  const rect = { left: 10, top: 20, width: 100, height: 80 };
  const mapEl = { clientWidth: 100, clientHeight: 80, getBoundingClientRect() { return rect; }, querySelectorAll() { return []; } };
  const legendPanel = { style: { display: 'flex' }, querySelectorAll() { return []; } };
  const ctx = { scale() {}, fillRect() {}, drawImage() {}, save() {}, restore() {}, beginPath() {}, rect() {}, clip() {},
    strokeRect() {}, fillText() {} };
  let printedHtml = '';
  const printWindow = { document: { write(html) { printedHtml = html; }, close() {} }, close() {} };
  const window = { GIS: { layers: {
    getLayers() { return [{ layer_id: 'population', filename: '长沙区县人口', visible: true }]; },
    getLegendData() { return { type: 'graduated', field: 'pop_wan', items: [
      { label: '64.20 - 83.60', color: '#fed976' }, { label: '83.60 - 152.70', color: '#bd0026' },
    ] }; },
  }, chat: { addMessage() {} } }, getComputedStyle(node) {
    return { display: node.style && node.style.display || 'block', font: '', fontSize: '12px', color: '#333',
      getPropertyValue() { return ''; } };
  }, open() { return printWindow; } };
  const document = {
    getElementById(id) { return id === 'map' ? mapEl : id === 'mapFloatingLegend' ? legendPanel : null; },
    createElement(tag) { return tag === 'canvas' ? { getContext() { return ctx; }, toDataURL() { return 'data:image/png;base64,map'; } } : {}; },
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../js/map.js'), 'utf8')
    .replace('GIS.map = {', 'GIS.__setMapInstanceForTest = function(value) { mapInstance = value; };\n  GIS.map = {');
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String,
    Object, Array, JSON, Set, Map, URL: { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} },
    XMLSerializer: class { serializeToString() { return '<svg />'; } }, Blob, Image: class {} });
  vm.runInContext(source, context, { filename: 'map.js' });
  window.GIS.__setMapInstanceForTest({ getCenter() { return { lat: 28.2, lng: 112.9 }; }, getZoom() { return 8; } });

  const result = await window.GIS.map.exportPdf('长沙人口分布图');
  assert.equal(result.ok, true);
  assert.match(printedHtml, /长沙人口分布图/);
  assert.match(printedHtml, /pop_wan/);
  assert.match(printedHtml, /64\.20 - 83\.60/);
  assert.match(printedHtml, /background:#fed976/);
  assert.match(printedHtml, /长沙区县人口/);
  assert.equal(legendPanel.style.display, 'flex');
});
