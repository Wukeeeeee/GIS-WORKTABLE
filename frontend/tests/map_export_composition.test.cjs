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
  const document = { getElementById() { return null; }, addEventListener() {} };
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

test('map image graticule labels longitude and latitude from the visible map bounds', () => {
  const lines = [], labels = [];
  const ctx = {
    save() {}, restore() {}, beginPath() {}, rect() {}, clip() {}, setLineDash() {}, stroke() {},
    moveTo(x, y) { lines.push([x, y]); }, lineTo(x, y) { lines.push([x, y]); },
    measureText(text) { return { width: text.length * 6 }; }, fillRect() {}, fillText(text) { labels.push(text); },
  };
  const window = { GIS: {} };
  const document = { addEventListener() {} };
  const source = fs.readFileSync(path.resolve(__dirname, '../js/map.js'), 'utf8')
    .replace('GIS.map = {', 'GIS.__setMapInstanceForTest = function(value) { mapInstance = value; };\n  GIS.__drawMapGraticuleForTest = _drawMapGraticule;\n  GIS.map = {');
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String,
    Object, Array, JSON, Set, Map, URL, Blob, Image: class {} });
  vm.runInContext(source, context, { filename: 'map.js' });
  window.GIS.__setMapInstanceForTest({ getBounds() {
    return { getNorth() { return 28.5; }, getSouth() { return 27.9; }, getEast() { return 113.3; }, getWest() { return 112.5; } };
  } });

  window.GIS.__drawMapGraticuleForTest(ctx, 800, 600);
  assert.ok(lines.length >= 12, 'both longitude and latitude grid lines should be drawn');
  assert.ok(labels.includes('112.800°E'));
  assert.ok(labels.includes('28.200°N'));
});

test('PNG export starts a composed image download and reports the filename without claiming it was saved', async () => {
  const rect = { left: 10, top: 20, width: 100, height: 80 };
  class FakeImage { constructor() { this.complete = true; this.naturalWidth = 256; } getBoundingClientRect() { return { left: 20, top: 30, width: 256, height: 256 }; } }
  const tileImage = new FakeImage();
  const mapEl = { clientWidth: 100, clientHeight: 80, getBoundingClientRect() { return rect; }, querySelectorAll(selector) {
    return selector.split(',').some(part => ['.leaflet-tile-loaded', '.leaflet-tile'].includes(part.trim())) ? [tileImage] : [];
  } };
  const drawnImages = [];
  const ctx = { scale() {}, fillRect() {}, drawImage(image) { drawnImages.push(image); }, save() {}, restore() {}, beginPath() {}, rect() {}, clip() {},
    strokeRect() {}, fillText() {} };
  const messages = [];
  const canvas = { width: 0, height: 0, getContext() { return ctx; }, toBlob(callback, mime, quality) {
    this.mime = mime;
    this.quality = quality;
    callback(new Blob(['composed-map'], { type: mime }));
  } };
  const link = { download: '', href: '', clicks: 0, click() { this.clicks++; this.wasAttached = !!this.parentNode; } };
  const body = { appendChild(node) { node.parentNode = this; }, removeChild(node) { node.parentNode = null; } };
  const revokedUrls = [];
  const timers = [];
  const urlApi = { createObjectURL(blob) { this.blob = blob; return 'blob:composed-map'; }, revokeObjectURL(url) { revokedUrls.push(url); } };
  const window = { GIS: { chat: { addMessage(message) { messages.push(message); } } } };
  const document = {
    body,
    addEventListener() {},
    getElementById(id) { return id === 'map' ? mapEl : null; },
    createElement(tag) { return tag === 'canvas' ? canvas : link; },
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../js/map.js'), 'utf8')
    .replace('GIS.map = {', 'GIS.__setMapInstanceForTest = function(value) { mapInstance = value; };\n  GIS.map = {');
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String,
    Object, Array, JSON, Set, Map, URL: urlApi, Blob, setTimeout(callback, delay) { timers.push({ callback, delay }); },
    HTMLImageElement: FakeImage, XMLSerializer: class {}, Image: class {} });
  vm.runInContext(source, context, { filename: 'map.js' });
  window.GIS.__setMapInstanceForTest({});

  const result = await window.GIS.map.exportMap('png');
  assert.equal(result.ok, true);
  assert.match(result.filename, /^map_export_\d+\.png$/);
  assert.equal(canvas.width, 200);
  assert.equal(canvas.height, 160);
  assert.equal(canvas.mime, 'image/png');
  assert.equal(canvas.quality, 0.92);
  assert.ok(drawnImages.includes(tileImage), 'loaded Leaflet tile images must be included in the exported map');
  assert.equal(urlApi.blob.type, 'image/png');
  assert.equal(link.href, 'blob:composed-map');
  assert.equal(link.download, result.filename);
  assert.equal(link.clicks, 1);
  assert.equal(link.wasAttached, true);
  assert.equal(link.parentNode, null);
  assert.equal(timers[0].delay, 1000);
  timers[0].callback();
  assert.deepEqual(revokedUrls, ['blob:composed-map']);
  assert.match(messages[0], /已发起当前地图下载/);
  assert.doesNotMatch(messages[0], /已生成当前地图下载/);
  assert.match(messages[0], new RegExp(result.filename));
});

test('JPEG aliases use matching image MIME and extension; unsupported formats are rejected', async () => {
  const rect = { left: 0, top: 0, width: 40, height: 30 };
  const mapEl = { clientWidth: 40, clientHeight: 30, getBoundingClientRect() { return rect; }, querySelectorAll() { return []; } };
  const ctx = { scale() {}, fillRect() {}, fillText() {} };
  const canvas = { getContext() { return ctx; }, toBlob(callback, mime) {
    this.mime = mime;
    callback(new Blob(['map'], { type: mime }));
  } };
  const link = { click() {}, download: '', href: '' };
  const body = { appendChild(node) { node.parentNode = this; }, removeChild(node) { node.parentNode = null; } };
  const messages = [];
  const URL = { createObjectURL(blob) { this.blob = blob; return 'blob:jpeg-map'; }, revokeObjectURL() {} };
  const window = { GIS: { chat: { addMessage(message) { messages.push(message); } } } };
  const document = {
    body,
    addEventListener() {},
    getElementById(id) { return id === 'map' ? mapEl : null; },
    createElement(tag) { return tag === 'canvas' ? canvas : link; },
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../js/map.js'), 'utf8')
    .replace('GIS.map = {', 'GIS.__setMapInstanceForTest = function(value) { mapInstance = value; };\n  GIS.map = {');
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String,
    Object, Array, JSON, Set, Map, URL, Blob, setTimeout() {}, HTMLImageElement: class {}, XMLSerializer: class {}, Image: class {} });
  vm.runInContext(source, context, { filename: 'map.js' });
  window.GIS.__setMapInstanceForTest({});

  const result = await window.GIS.map.exportMap('jpeg');
  assert.equal(result.ok, true);
  assert.match(result.filename, /\.jpg$/);
  assert.equal(canvas.mime, 'image/jpeg');
  assert.equal(URL.blob.type, 'image/jpeg');
  assert.equal(window.GIS.map.exportMap('webp').ok, false);
  assert.match(messages.at(-1), /仅支持 PNG\/JPG/);
});

test('PDF layout embeds the current thematic legend and restores the map legend visibility', async () => {
  const rect = { left: 10, top: 20, width: 100, height: 80 };
  const mapEl = { clientWidth: 100, clientHeight: 80, getBoundingClientRect() { return rect; }, querySelectorAll() { return []; } };
  const legendPanel = { style: { display: 'flex' }, querySelectorAll() { return []; } };
  const ctx = { scale() {}, fillRect() {}, drawImage() {}, save() {}, restore() {}, beginPath() {}, rect() {}, clip() {},
    strokeRect() {}, fillText() {} };
  let printedHtml = '';
  const pdfLegendData = { type: 'graduated', field: 'pop_wan', items: [
    { label: '64.20 - 83.60', color: '#fed976' }, { label: '83.60 - 152.70', color: '#bd0026' },
  ] };
  const printWindow = { document: { write(html) { printedHtml = html; }, close() {} }, close() {} };
  const window = { GIS: { layers: {
    getLayers() { return [{ layer_id: 'population', filename: '长沙区县人口', visible: true }]; },
    getLegendData() { return pdfLegendData; },
  }, chat: { addMessage() {} } }, getComputedStyle(node) {
    return { display: node.style && node.style.display || 'block', font: '', fontSize: '12px', color: '#333',
      getPropertyValue() { return ''; } };
  }, open() { return printWindow; } };
  const document = {
    addEventListener() {},
    getElementById(id) { return id === 'map' ? mapEl : id === 'mapFloatingLegend' ? legendPanel : null; },
    createElement(tag) { return tag === 'canvas' ? { getContext() { return ctx; }, toDataURL() { return 'data:image/png;base64,map'; } } : {}; },
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../js/map.js'), 'utf8')
    .replace('GIS.map = {', 'GIS.__setMapInstanceForTest = function(value) { mapInstance = value; };\n  GIS.map = {');
  const context = vm.createContext({ window, document, console, Promise, Date, Math, Number, String,
    Object, Array, JSON, Set, Map, URL: { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} },
    XMLSerializer: class { serializeToString() { return '<svg />'; } }, Blob, Image: class {} });
  vm.runInContext(source, context, { filename: 'map.js' });
  const bounds = { north: 28.5, south: 27.9, east: 113.3, west: 112.5 };
  window.GIS.__setMapInstanceForTest({
    getCenter() { return { lat: 28.2, lng: 112.9 }; }, getZoom() { return 8; },
    getBounds() { return { getNorth() { return bounds.north; }, getSouth() { return bounds.south; }, getEast() { return bounds.east; }, getWest() { return bounds.west; } }; },
  });

  const result = await window.GIS.map.exportPdf('长沙人口分布图', 30);
  assert.equal(result.ok, true);
  assert.match(printedHtml, /长沙人口分布图/);
  assert.match(printedHtml, /pop_wan/);
  assert.match(printedHtml, /64\.20 - 83\.60/);
  assert.match(printedHtml, /background:#fed976/);
  assert.match(printedHtml, /长沙区县人口/);
  assert.match(printedHtml, /112\.50000°E · 28\.50000°N/);
  assert.match(printedHtml, /113\.30000°E · 27\.90000°N/);
  assert.match(printedHtml, /class="graticule"[^>]*aria-hidden="true"/);
  assert.match(printedHtml, /@media print \{ body \{ padding: 0; \} \.map-container \{ display:flex; align-items:center; justify-content:center; \} \.map-artwork \{ position:relative; left:auto; top:auto; transform:rotate\(30\.00deg\); margin:auto; \} \}/,
    'the print page should keep the rotated map in normal flow so it fits on one page');
  assert.match(printedHtml, /112\.80000°E/);
  assert.match(printedHtml, /28\.20000°N/);
  const artwork = printedHtml.match(/<div class="map-artwork">([\s\S]*?)<\/div>/);
  assert.ok(artwork, 'rotated map artwork should be present');
  assert.doesNotMatch(artwork[1], /coordinate|grid-label/, 'coordinate text must remain upright outside the rotated artwork');
  assert.match(printedHtml, /class="coordinate" style="left:31\.59%;top:0\.00%">112\.50000°E · 28\.50000°N/,
    'the northwest coordinate should move to the rotated northwest map corner');
  assert.match(printedHtml, /图上北 · 顺时针旋转 30°/);
  assert.match(printedHtml, /rotate\(30\.00deg\)/);
  assert.match(printedHtml, /north-arrow[^}]*rotate\(30\.00deg\)/);
  assert.match(printedHtml, /旋转 30°/);
  assert.equal(legendPanel.style.display, 'flex');

  pdfLegendData.type = 'graduated-symbol';
  await window.GIS.map.exportPdf('分级符号图例测试', 0);
  assert.match(printedHtml, /@media print \{ body \{ padding: 0; \} \.map-container \{ display:flex; align-items:center; justify-content:center; \} \.map-artwork \{ position:relative; left:auto; top:auto; transform:none; margin:auto; \} \}/,
    'zero-degree exports should avoid a transform that fragments the print page');
  assert.match(printedHtml, /pop_wan · 分级符号/);
  pdfLegendData.type = 'proportional';
  await window.GIS.map.exportPdf('比例符号图例测试', 0);
  assert.match(printedHtml, /pop_wan · 比例符号/);

  bounds.south = 27.9995;
  await window.GIS.map.exportPdf('边界标签避让测试', 0);
  assert.match(printedHtml, /27\.99950°N/);
  assert.doesNotMatch(printedHtml, /class="grid-label latitude-label"[^>]*>28\.00000°N/,
    'a latitude tick label touching the southwest corner coordinate should be suppressed');
  assert.match(printedHtml, /<line x1="0" y1="[\d.]+" x2="1000" y2="[\d.]+"\/>/,
    'suppressing a colliding label should keep its graticule line');

  bounds.north = 30.26237;
  bounds.south = 30.23964;
  bounds.east = 120.16996;
  bounds.west = 120.13408;
  mapEl.clientWidth = 1226;
  mapEl.clientHeight = 900;
  rect.width = mapEl.clientWidth;
  rect.height = mapEl.clientHeight;
  await window.GIS.map.exportPdf('截图边界标签避让测试', 0);
  assert.doesNotMatch(printedHtml, /class="grid-label longitude-label"[^>]*>120\.14000°E/,
    'the northwest longitude tick should not overlap the corner coordinate');
  assert.doesNotMatch(printedHtml, /class="grid-label latitude-label"[^>]*>30\.24000°N/,
    'the southwest latitude tick should not overlap the corner coordinate');
  assert.match(printedHtml, /<line x1="[\d.]+" y1="0" x2="[\d.]+" y2="1000"\/>/,
    'suppressing colliding edge labels should keep longitude grid lines');

  bounds.north = 30.260197782180903;
  bounds.south = 30.241791820946666;
  bounds.east = 120.1644015312195;
  bounds.west = 120.13959646224977;
  await window.GIS.map.exportPdf('实际视口打印缩放避让测试', 0);
  assert.doesNotMatch(printedHtml, /class="grid-label longitude-label"[^>]*>120\.16000°E/,
    'the top-right grid label should be suppressed when it overlaps at actual print size');
});
