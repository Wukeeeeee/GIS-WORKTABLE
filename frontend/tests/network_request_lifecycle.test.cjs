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
    fitBounds() {},
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
      addLayer() {},
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
    geoJSON() {
      const bounds = { isValid() { return true; }, pad() { return this; }, extend() { return this; } };
      return { addTo() { return this; }, getBounds() { return bounds; } };
    },
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

async function setClosestFacilityInputs(harness) {
  harness.window.GIS.network.activate();
  const closestTab = new Element('closest-facility-tab');
  closestTab.dataset.type = 'closest_facility';
  harness.getElement('networkTabs').listeners.click({ target: { closest: () => closestTab } });
  harness.getElement('btnEventOrigin').onclick();
  harness.map.clickHandler({ latlng: { lng: -73, lat: 40 } });
  await new Promise(resolve => setImmediate(resolve));
  harness.getElement('networkAddFacilityBtn').onclick();
  harness.map.clickHandler({ latlng: { lng: -72.99, lat: 40 } });
  harness.getElement('networkAddFacilityBtn').onclick();
  harness.map.clickHandler({ latlng: { lng: -72.98, lat: 40 } });
  harness.getElement('networkSolveBtn').listeners.click();
}

async function setServiceAreaInputs(harness) {
  harness.window.GIS.network.activate();
  const serviceAreaTab = new Element('service-area-tab');
  serviceAreaTab.dataset.type = 'service_area';
  harness.getElement('networkTabs').listeners.click({ target: { closest: () => serviceAreaTab } });
  harness.getElement('btnFacility').onclick();
  harness.map.clickHandler({ latlng: { lng: -73, lat: 40 } });
  await new Promise(resolve => setImmediate(resolve));
  harness.getElement('networkSolveBtn').listeners.click();
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

test('closest-facility results label facilities from one and explain omitted inputs', async () => {
  const harness = createHarness();
  await setClosestFacilityInputs(harness);
  harness.finishSolve()({
    ok: true,
    json: () => Promise.resolve({
      paths: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[-73, 40], [-72.99, 40]] } }],
      summary: [{ rank: 1, facility_idx: 0, distance_km: 0.8 }],
      unsnapped_facility_indices: [1],
      unreachable_facility_indices: [2],
    }),
  });
  await new Promise(resolve => setImmediate(resolve));

  const result = harness.getElement('networkResultBody').innerHTML;
  assert.match(result, /设施1:/);
  assert.doesNotMatch(result, /设施0:/);
  assert.match(result, /超出 500 m 吸附范围的设施序号（从 1 开始）：2/);
  assert.match(result, /与事件点路网不可达的设施序号（从 1 开始）：3/);
  assert.equal(harness.getElement('networkStatus').textContent, '最近设施分析完成（部分设施未纳入结果）');
});

test('closest-facility total failures retain backend snap and reachability diagnostics', async () => {
  const harness = createHarness();
  await setClosestFacilityInputs(harness);
  harness.finishSolve()({
    ok: true,
    json: () => Promise.resolve({
      error: '所有设施均无法连通',
      unsnapped_facility_indices: [0],
      unreachable_facility_indices: [1],
    }),
  });
  await new Promise(resolve => setImmediate(resolve));

  assert.match(harness.getElement('networkStatus').textContent, /所有设施均无法连通/);
  assert.match(harness.getElement('networkStatus').textContent, /吸附范围的设施序号（从 1 开始）：1/);
  assert.match(harness.getElement('networkStatus').textContent, /路网不可达的设施序号（从 1 开始）：2/);
});

test('service-area results disclose the convex-hull approximation', async () => {
  const harness = createHarness();
  await setServiceAreaInputs(harness);

  harness.finishSolve()({
    ok: true,
    json: () => Promise.resolve({
      polygons: { type: 'FeatureCollection', features: [
        { type: 'Feature', properties: { approximate: true, boundary_method: 'reachable_node_convex_hull' },
          geometry: { type: 'Polygon', coordinates: [[[-73, 40], [-72.99, 40], [-72.99, 40.01], [-73, 40]]] } },
      ] },
      areas: [{ break: 1000, area_km2: 0.2 }],
    }),
  });
  await new Promise(resolve => setImmediate(resolve));

  assert.match(harness.getElement('networkResultBody').innerHTML, /可达路网节点凸包估算/);
  assert.match(harness.getElement('networkResultBody').innerHTML, /不代表精确等时圈/);
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
