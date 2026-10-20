const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor(id) {
    this.id = id;
    this.style = {};
    this.dataset = {};
    this.options = [];
    this.listeners = {};
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  appendChild(child) { child.parentNode = this; return child; }
  querySelector() { return new Element('nested'); }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return { left: 0, top: 0 }; }
}

function createHarness(config = {}) {
  const elements = new Map();
  const mapContainer = { style: {} };
  const getElement = id => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const map = {
    on(type, handler) { if (type === 'click') this.clickHandler = handler; },
    off() {},
    getContainer() { return mapContainer; },
    removeLayer() {},
  };
  const roadData = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[-73, 40], [-72, 41]] } },
  ] };
  let finishSolve;
  const fetchCalls = [];
  const snapResolvers = [];
  const window = { innerWidth: 1200, innerHeight: 800, GIS: {
    api: { BASE_URL: '' },
    map: { getMap() { return map; } },
    layers: {
      getLayerNames() { return ['roads']; },
      getLayerGeoJSON(name) { return name === 'roads' ? roadData : null; },
    },
  } };
  const document = {
    documentElement: new Element('html'),
    body: new Element('body'),
    createElement(tag) { return new Element(tag); },
    getElementById: getElement,
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeEventListener() {},
  };
  getElement('networkLayerSelect').value = 'roads';
  getElement('networkLayerSelect').options = [{ value: '' }, { value: 'roads' }];
  const fetch = (url, options) => {
    fetchCalls.push({ url, options });
    if (url.endsWith('/snap') && config.deferSnap) {
      return new Promise(resolve => snapResolvers.push(resolve));
    }
    if (url.endsWith('/snap')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ snapped: [-73, 40], distance_m: 0 }) });
    return new Promise(resolve => { finishSolve = resolve; });
  };
  const L = {
    latLng(lat, lng) { return { lat, lng }; },
    circleMarker() { return { addTo() { return this; }, bindTooltip() { return this; } }; },
  };
  const sourcePath = path.resolve(__dirname, '../js/network.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, fetch, L, console: { log() {}, warn() {}, error() {} },
    Promise, Map, Set, Array, Object, String, Number, Math, Date, JSON,
    AbortController, setTimeout, clearTimeout,
  }, { filename: sourcePath });
  return { window, document, getElement, map, mapContainer, fetchCalls, snapResolvers, finishSolve: () => finishSolve };
}

async function setRoutePoints(harness) {
  harness.window.GIS.network.activate();
  harness.getElement('btnOrigin').onclick();
  harness.map.clickHandler({ latlng: { lng: -73, lat: 40 } });
  await new Promise(resolve => setImmediate(resolve));
  harness.getElement('btnDest').onclick();
  harness.map.clickHandler({ latlng: { lng: -72, lat: 41 } });
  await new Promise(resolve => setImmediate(resolve));
}

test('network solve results are ignored after the user switches analysis modes', async () => {
  const harness = createHarness();
  await setRoutePoints(harness);
  harness.getElement('networkSolveBtn').listeners.click();
  assert.equal(harness.fetchCalls.filter(call => call.url.endsWith('/solve')).length, 1);

  const serviceAreaTab = new Element('service-area-tab');
  serviceAreaTab.dataset.type = 'service_area';
  serviceAreaTab.closest = () => serviceAreaTab;
  harness.getElement('networkTabs').listeners.click({ target: serviceAreaTab });
  assert.equal(harness.getElement('networkSolveBtn').disabled, false);
  assert.equal(harness.getElement('networkLoader').style.display, 'none');

  harness.finishSolve()({
    ok: true,
    json: () => Promise.resolve({
      path: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[-73, 40], [-72, 41]] } },
      distance_km: 10,
    }),
  });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(harness.getElement('networkResult').style.display, 'none');
  assert.equal(harness.getElement('networkStatus').textContent, '');
});

test('network solve treats non-2xx JSON responses without an error field as failures', async () => {
  const harness = createHarness();
  await setRoutePoints(harness);
  harness.getElement('networkSolveBtn').listeners.click();

  harness.finishSolve()({ ok: false, status: 500, json: () => Promise.resolve({ detail: 'internal error' }) });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(harness.getElement('networkStatus').textContent, '求解失败: HTTP 500');
  assert.equal(harness.getElement('networkLoader').style.display, 'none');
  assert.equal(harness.getElement('networkSolveBtn').disabled, false);
});

test('late point snap cannot become an input for a newly selected network mode', async () => {
  const harness = createHarness({ deferSnap: true });
  harness.window.GIS.network.activate();
  harness.getElement('btnOrigin').onclick();
  harness.map.clickHandler({ latlng: { lng: -73, lat: 40 } });
  assert.equal(harness.snapResolvers.length, 1);

  const serviceAreaTab = new Element('service-area-tab');
  serviceAreaTab.dataset.type = 'service_area';
  serviceAreaTab.closest = () => serviceAreaTab;
  harness.getElement('networkTabs').listeners.click({ target: serviceAreaTab });
  harness.getElement('btnFacility').onclick();

  harness.snapResolvers[0]({
    ok: true,
    json: () => Promise.resolve({ snapped: [-73, 40], distance_m: 0 }),
  });
  await new Promise(resolve => setImmediate(resolve));

  assert.notEqual(harness.getElement('networkFacilityCoord').textContent, '-73.00000, 40.00000');
  assert.equal(harness.mapContainer.style.cursor, 'crosshair');
});
