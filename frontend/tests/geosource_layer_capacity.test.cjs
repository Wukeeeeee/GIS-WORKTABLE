const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function proxiedTarget(url) {
  const parsed = new URL(url, 'http://localhost');
  assert.equal(parsed.pathname, '/api/geosource/proxy');
  assert.equal(parsed.searchParams.get('_geosource_tile'), '1');
  return parsed.searchParams.get('url');
}

function proxiedAuthParameter(url) {
  return new URL(url, 'http://localhost').searchParams.get('_geosource_auth_parameter');
}

function createGeoSource(initialLayers, options = {}) {
  const layers = initialLayers.map(layer => ({ ...layer }));
  const removed = [];
  const rendered = [];
  const renderedTiles = [];
  const notices = [];
  const fetchCalls = [];
  const elements = {};
  function fakeTileLayer(collection, item) {
    const listeners = {};
    const layer = {
      on(type, callback) { listeners[type] = callback; return layer; },
      fire(type) { if (listeners[type]) listeners[type]({ type, target: layer }); },
    };
    collection.push({ ...item, layer });
    return layer;
  }
  const fetchImpl = options.fetch || ((url, init) => {
    fetchCalls.push({ url, init });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ type: 'FeatureCollection', features: [] }) });
  });
  function element(id) {
    const listeners = {};
    const value = {
      id, style: {}, dataset: {}, value: '', textContent: '', listeners,
      addEventListener(type, callback) { listeners[type] = callback; },
      focus() {},
      click() { if (listeners.click) listeners.click({ target: value }); },
    };
    elements[id] = value;
    return value;
  }
  if (options.withCredentialDialog) {
    element('geosourceModal');
    element('geosourceCredentialModal');
    element('geosourceCredentialTitle');
    element('geosourceCredentialParam');
    element('geosourceCredentialValue');
    element('geosourceCredentialCancelBtn');
    element('geosourceCredentialNoKeyBtn');
    element('geosourceCredentialSubmitBtn');
  }
  const window = { location: { href: 'http://localhost/' }, alert() {}, GIS: {
    api: { BASE_URL: '', geosourceDetail() {
      return options.geosourceDetail ? options.geosourceDetail() : Promise.resolve({ layers: [] });
    } },
    utils: { escapeHtml(value) { return String(value); } },
    map: {
      addWmsLayer(url, layer, name) { return fakeTileLayer(rendered, { url, sublayer: layer, name }); },
      addTileLayer(url, name) { return fakeTileLayer(renderedTiles, { url, name }); },
    },
    layers: {
      getLayers() { return layers; },
      removeLayer(id) {
        removed.push(id);
        const index = layers.findIndex(layer => layer.layer_id === id);
        if (index >= 0) layers.splice(index, 1);
      },
      addLayer(layer) { layers.push(layer); },
    },
    toast: {
      info(message) { notices.push({ type: 'info', message }); },
      warn(message) { notices.push({ type: 'warn', message }); },
      error(message) { notices.push({ type: 'error', message }); },
      success(message) { notices.push({ type: 'success', message }); },
    },
    chat: { addMessage() {} },
  }, addEventListener() {} };
  const document = {
    readyState: options.withCredentialDialog ? 'complete' : 'loading',
    addEventListener() {},
    querySelector() { return null; },
    getElementById(id) { return elements[id] || null; },
  };
  const sourcePath = path.resolve(__dirname, '../js/geosource.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, console, Promise, JSON, Array, String, Number, Object, Date,
    encodeURIComponent, decodeURIComponent, URL, fetch: fetchImpl,
    AbortSignal: { timeout(milliseconds) { return { milliseconds }; } }, setTimeout, clearTimeout,
  }, { filename: sourcePath });
  return { window, geosource: window.GIS.geosource, layers, removed, rendered, renderedTiles, notices, elements, fetchCalls };
}

function loadWms(geosource, name) {
  geosource.loadWmsSublayer(
    encodeURIComponent('https://maps.example.test/wms'),
    encodeURIComponent('roads'),
    encodeURIComponent(name),
  );
}

test('GeoSource capacity does not evict existing workspace layers', () => {
  const h = createGeoSource([
    { layer_id: 'analysis', filename: '分析结果', source: 'ai' },
    { layer_id: 'upload', filename: '本地上传', source: 'upload' },
    { layer_id: 'bookmark', filename: '工作区图层', source: 'manual' },
  ]);

  loadWms(h.geosource, '在线道路');

  assert.deepEqual(h.removed, []);
  assert.equal(h.rendered.length, 0);
  assert.equal(h.layers.length, 3);
  assert.equal(h.notices[0].type, 'warn');
  assert.match(h.notices[0].message, /先.*移除/);
});

test('GeoSource result cards distinguish partially free services', async () => {
  const h = createGeoSource([]);
  h.window.GIS.i18n = { isEnglish: () => true };
  h.elements.geosourceResultsList = { innerHTML: '', scrollTop: 0 };
  h.elements.geosourceResultCount = { innerHTML: '' };
  h.elements.geosourcePageControls = { innerHTML: '' };
  h.window.GIS.api.geosourceSearch = () => Promise.resolve({
    total: 1,
    page: 1,
    total_pages: 1,
    results: [{
      service_id: 'AGOL-0051',
      service_name: 'Esri World Geocoding Demo',
      protocol: 'WMS',
      service_url: 'https://example.test/wms',
      free: '部分免费',
      is_free: '是',
    }],
  });

  h.geosource.doSearch(1);
  await new Promise(resolve => setImmediate(resolve));

  assert.match(h.elements.geosourceResultsList.innerHTML, /Partially free/);
  assert.doesNotMatch(h.elements.geosourceResultsList.innerHTML, /<span class="geosource-tag tag-info">[^<]*Free<\/span>/);
});

test('GeoSource cards extract a valid official URL before catalog notes', async () => {
  const h = createGeoSource([]);
  h.elements.geosourceResultsList = { innerHTML: '', scrollTop: 0 };
  h.elements.geosourceResultCount = { innerHTML: '' };
  h.elements.geosourcePageControls = { innerHTML: '' };
  h.window.GIS.api.geosourceSearch = () => Promise.resolve({
    total: 1,
    page: 1,
    total_pages: 1,
    results: [{
      service_id: 'DS-1123',
      service_name: 'Anhui public data portal',
      protocol: 'HTTP/REST',
      service_url: '',
      official_url: 'https://data.ah.gov.cn（待直接验证',
    }],
  });

  h.geosource.doSearch(1);
  await new Promise(resolve => setImmediate(resolve));

  assert.match(h.elements.geosourceResultsList.innerHTML, /href="https:\/\/data\.ah\.gov\.cn\//);
  assert.match(h.elements.geosourceResultsList.innerHTML, /value="https:\/\/data\.ah\.gov\.cn\//);
  assert.doesNotMatch(h.elements.geosourceResultsList.innerHTML, /%EF%BC%88%E5%BE%85%E7%9B%B4%E6%8E%A5%E9%AA%8C%E8%AF%81/);
});

test('GeoSource cards explain when the catalog has no valid URL', async () => {
  const h = createGeoSource([]);
  h.window.GIS.i18n = { isEnglish: () => true };
  h.elements.geosourceResultsList = { innerHTML: '', scrollTop: 0 };
  h.elements.geosourceResultCount = { innerHTML: '' };
  h.elements.geosourcePageControls = { innerHTML: '' };
  h.window.GIS.api.geosourceSearch = () => Promise.resolve({
    total: 1,
    page: 1,
    total_pages: 1,
    results: [{
      service_id: 'DS-1129',
      service_name: 'Hebei public data portal',
      protocol: 'HTTP download',
      service_url: '',
      official_url: '',
      docs_url: '',
    }],
  });

  h.geosource.doSearch(1);
  await new Promise(resolve => setImmediate(resolve));

  assert.match(h.elements.geosourceResultsList.innerHTML, /No valid URL is listed/);
  assert.doesNotMatch(h.elements.geosourceResultsList.innerHTML, /geosource-copy-btn/);
});

test('GeoSource name collision does not replace a non-GeoSource layer', () => {
  const h = createGeoSource([
    { layer_id: 'analysis', filename: '道路', source: 'ai' },
    { layer_id: 'upload', filename: '本地上传', source: 'upload' },
  ]);

  loadWms(h.geosource, '道路');

  assert.deepEqual(h.removed, []);
  assert.equal(h.rendered.length, 0);
  assert.equal(h.layers[0].source, 'ai');
  assert.equal(h.notices[0].type, 'error');
});

test('reloading the same GeoSource layer replaces that layer without evicting peers', () => {
  const h = createGeoSource([
    { layer_id: 'old-road', filename: '在线道路', source: 'geosource' },
    { layer_id: 'analysis', filename: '分析结果', source: 'ai' },
  ]);

  loadWms(h.geosource, '在线道路');

  assert.deepEqual(h.removed, ['old-road']);
  assert.equal(h.rendered.length, 1);
  assert.equal(h.layers[0].source, 'ai');
  assert.equal(h.layers[1].source, 'geosource');
});

test('WMS layer metadata persists a key-free service URL and reauthentication details', () => {
  const h = createGeoSource([]);
  const runtimeUrl = 'https://maps.example.test/wms?code=KEY_SENTINEL';
  const safeServiceUrl = 'https://maps.example.test/wms?version=1.3.0';
  h.geosource.loadWmsSublayer(
    encodeURIComponent(runtimeUrl), encodeURIComponent('roads'), encodeURIComponent('Roads'), null,
    { url: safeServiceUrl, credential: { parameter: 'code', key: 'KEY_SENTINEL' }, requires_auth: true }
  );

  assert.equal(proxiedTarget(h.rendered[0].url), runtimeUrl);
  assert.equal(proxiedAuthParameter(h.rendered[0].url), 'code');
  assert.equal(h.layers[0].url, safeServiceUrl);
  assert.equal(h.layers[0].service_type, 'WMS');
  assert.equal(h.layers[0].sublayer, 'roads');
  assert.equal(h.layers[0].requires_auth, true);
  assert.equal(h.layers[0].auth_parameter, 'code');
  assert.equal(JSON.stringify(h.layers[0]).includes('KEY_SENTINEL'), false);
});

test('XYZ layer metadata persists key-free endpoint and never stores the session key', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  const runtimeUrl = 'https://tiles.example.test/{z}/{x}/{y}';
  h.geosource.loadSavedServiceLayer({
    filename: 'Protected tiles',
    geometry_type: 'XYZ瓦片',
    service_type: 'XYZ',
    url: runtimeUrl,
    requires_auth: true,
    auth_parameter: 'code',
  });
  h.elements.geosourceCredentialValue.value = 'KEY_SENTINEL';
  h.elements.geosourceCredentialSubmitBtn.click();

  assert.equal(proxiedTarget(h.renderedTiles[0].url), runtimeUrl + '?code=KEY_SENTINEL');
  assert.equal(proxiedAuthParameter(h.renderedTiles[0].url), 'code');
  assert.equal(h.layers[0].url, 'https://tiles.example.test/{z}/{x}/{y}');
  assert.equal(h.layers[0].requires_auth, true);
  assert.equal(h.layers[0].auth_parameter, 'code');
  assert.equal(JSON.stringify(h.layers[0]).includes('KEY_SENTINEL'), false);
});

test('authenticated XYZ service preserves the inverted {-y} tile template', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  const template = 'https://tiles.example.test/{z}/{x}/{-y}';
  h.geosource.loadSavedServiceLayer({
    filename: 'Inverted tiles',
    geometry_type: 'XYZ瓦片',
    service_type: 'XYZ',
    url: template,
    requires_auth: true,
    auth_parameter: 'token',
  });
  h.elements.geosourceCredentialValue.value = 'KEY_SENTINEL';
  h.elements.geosourceCredentialSubmitBtn.click();

  assert.equal(proxiedTarget(h.renderedTiles[0].url), template + '?token=KEY_SENTINEL');
  assert.equal(h.layers[0].url, template);
  assert.equal(JSON.stringify(h.layers[0]).includes('KEY_SENTINEL'), false);
});

test('authenticated WMS tile failures show one HTTPS and credential hint', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  const runtimeUrl = 'http://tiles.example.test/wms';
  h.geosource.loadWmsSublayer(
    encodeURIComponent(runtimeUrl + '?token=KEY_SENTINEL'), encodeURIComponent('roads'),
    encodeURIComponent('Protected roads'), null,
    { url: runtimeUrl, credential: { parameter: 'token', key: 'KEY_SENTINEL' }, requires_auth: true }
  );

  h.rendered[0].layer.fire('tileerror');
  h.rendered[0].layer.fire('tileerror');

  assert.equal(h.notices.filter(notice => notice.type === 'error').length, 1);
  assert.match(h.notices.at(-1).message, /公网服务，请改用 HTTPS/);
  assert.doesNotMatch(h.notices.at(-1).message, /KEY_SENTINEL/);
});

test('authenticated XYZ tile failures show one HTTPS and credential hint', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  const template = 'http://tiles.example.test/{z}/{x}/{y}.png';
  h.geosource.loadSavedServiceLayer({
    filename: 'Protected XYZ',
    geometry_type: 'XYZ瓦片',
    service_type: 'XYZ',
    url: template,
    requires_auth: true,
    auth_parameter: 'token',
  });
  h.elements.geosourceCredentialValue.value = 'KEY_SENTINEL';
  h.elements.geosourceCredentialSubmitBtn.click();

  h.renderedTiles[0].layer.fire('tileerror');
  h.renderedTiles[0].layer.fire('tileerror');

  assert.equal(h.notices.filter(notice => notice.type === 'error').length, 1);
  assert.match(h.notices.at(-1).message, /公网服务，请改用 HTTPS/);
  assert.doesNotMatch(h.notices.at(-1).message, /KEY_SENTINEL/);
});

test('project reauthentication prompts are queued and never persist entered keys', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  const firstUrl = 'https://tiles.example.test/a/{z}/{x}/{y}';
  const secondUrl = 'https://tiles.example.test/b/{z}/{x}/{y}';
  h.geosource.loadSavedServiceLayer({ filename: 'Tiles A', service_type: 'XYZ', url: firstUrl,
    requires_auth: true, auth_parameter: 'token' });
  h.geosource.loadSavedServiceLayer({ filename: 'Tiles B', service_type: 'XYZ', url: secondUrl,
    requires_auth: true, auth_parameter: 'token' });

  const modal = {
    title: h.elements.geosourceCredentialTitle,
    param: h.elements.geosourceCredentialParam,
    key: h.elements.geosourceCredentialValue,
    submit: h.elements.geosourceCredentialSubmitBtn,
  };
  assert.equal(modal.title.textContent, '接入服务：Tiles A');
  modal.param.value = 'token';
  modal.key.value = 'FIRST_KEY_SENTINEL';
  modal.submit.click();
  assert.equal(modal.title.textContent, '接入服务：Tiles B');
  modal.param.value = 'token';
  modal.key.value = 'SECOND_KEY_SENTINEL';
  modal.submit.click();

  assert.deepEqual(h.renderedTiles.map(item => proxiedTarget(item.url)), [
    firstUrl + '?token=FIRST_KEY_SENTINEL',
    secondUrl + '?token=SECOND_KEY_SENTINEL',
  ]);
  assert.equal(JSON.stringify(h.layers).includes('FIRST_KEY_SENTINEL'), false);
  assert.equal(JSON.stringify(h.layers).includes('SECOND_KEY_SENTINEL'), false);
});

test('GeoSource prompts for a manual key when the service URL identifies an auth parameter', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  const service = {
    service_id: 'protected-tiles',
    service_name: 'Protected tiles',
    protocol: 'XYZ',
    service_url: 'https://tiles.example.test/{z}/{x}/{y}?token=',
    need_no_key: '是',
  };

  h.geosource.loadService(service);

  assert.equal(h.elements.geosourceCredentialModal.style.display, 'flex');
  assert.equal(h.elements.geosourceCredentialParam.value, 'token');
  assert.equal(h.renderedTiles.length, 0);

  h.elements.geosourceCredentialValue.value = 'USER_KEY_SENTINEL';
  h.elements.geosourceCredentialSubmitBtn.click();

  assert.equal(proxiedTarget(h.renderedTiles[0].url), 'https://tiles.example.test/{z}/{x}/{y}?token=USER_KEY_SENTINEL');
  assert.equal(JSON.stringify(h.layers).includes('USER_KEY_SENTINEL'), false);
});

test('GeoSource WMS detail sublayers use the same credential prompt and retain the selected layer', async () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  const service = {
    service_id: 'protected-wms',
    service_name: 'Protected WMS',
    protocol: 'WMS',
    service_url: 'https://maps.example.test/wms',
    need_no_key: '否',
  };

  h.geosource.loadWmsServiceSublayer(service, 'private-roads', null);
  assert.equal(h.elements.geosourceCredentialModal.style.display, 'flex');
  assert.equal(h.rendered.length, 0);

  h.elements.geosourceCredentialParam.value = 'api_key';
  h.elements.geosourceCredentialValue.value = 'WMS_KEY_SENTINEL';
  h.elements.geosourceCredentialSubmitBtn.click();
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(h.fetchCalls.length, 0);
  assert.equal(h.rendered.length, 1);
  assert.equal(h.rendered[0].sublayer, 'private-roads');
  assert.equal(h.rendered[0].name, 'Protected WMS - private-roads');
  assert.equal(proxiedTarget(h.rendered[0].url), 'https://maps.example.test/wms?api_key=WMS_KEY_SENTINEL');
  assert.equal(h.layers[0].sublayer, 'private-roads');
  assert.equal(JSON.stringify(h.layers).includes('WMS_KEY_SENTINEL'), false);
});

test('GeoSource retains a selected WMS detail sublayer when service metadata lookup fails', async () => {
  const h = createGeoSource([], {
    withCredentialDialog: true,
    geosourceDetail() { return Promise.reject(new Error('offline')); },
  });
  const service = {
    service_id: 'protected-wms',
    service_name: 'Protected WMS',
    protocol: 'WMS',
    service_url: 'https://maps.example.test/wms',
    need_no_key: '否',
  };

  h.geosource.loadWmsServiceSublayer(service, 'private-roads', null);
  h.elements.geosourceCredentialParam.value = 'api_key';
  h.elements.geosourceCredentialValue.value = 'WMS_KEY_SENTINEL';
  h.elements.geosourceCredentialSubmitBtn.click();
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(h.rendered[0].sublayer, 'private-roads');
  assert.equal(h.layers[0].sublayer, 'private-roads');
  assert.equal(h.layers[0].url, 'https://maps.example.test/wms');
  assert.equal(JSON.stringify(h.layers).includes('WMS_KEY_SENTINEL'), false);
});

test('GeoSource recognizes access_key as credentials even when the catalog says no key is needed', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  const service = {
    service_id: 'protected-access-key-tiles',
    service_name: 'Access key tiles',
    protocol: 'XYZ',
    service_url: 'https://tiles.example.test/{z}/{x}/{y}?access_key=',
    need_no_key: '是',
  };

  h.geosource.loadService(service);

  assert.equal(h.elements.geosourceCredentialParam.value, 'access_key');
  assert.equal(h.renderedTiles.length, 0);
  h.elements.geosourceCredentialValue.value = 'ACCESS_KEY_SENTINEL';
  h.elements.geosourceCredentialSubmitBtn.click();

  assert.equal(proxiedTarget(h.renderedTiles[0].url),
    'https://tiles.example.test/{z}/{x}/{y}?access_key=ACCESS_KEY_SENTINEL');
  assert.equal(h.layers[0].url, 'https://tiles.example.test/{z}/{x}/{y}');
  assert.equal(h.layers[0].auth_parameter, 'access_key');
  assert.equal(JSON.stringify(h.layers[0]).includes('ACCESS_KEY_SENTINEL'), false);
});

test('GeoSource does not treat unrelated query names containing key as credentials', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  h.geosource.loadService({
    service_id: 'monkey-tiles',
    service_name: 'Monkey tiles',
    protocol: 'XYZ',
    service_url: 'https://tiles.example.test/{z}/{x}/{y}?monkey=species',
    need_no_key: '是',
  });

  assert.equal(h.renderedTiles.length, 1);
  assert.equal(h.elements.geosourceCredentialModal.style.display, undefined);
  assert.equal(h.layers[0].url, 'https://tiles.example.test/{z}/{x}/{y}?monkey=species');
});

test('GeoSource stops authenticated connections when the credential dialog is unavailable', () => {
  const h = createGeoSource([]);
  h.geosource.loadService({
    service_id: 'protected-tiles',
    service_name: 'Protected tiles',
    protocol: 'XYZ',
    service_url: 'https://tiles.example.test/{z}/{x}/{y}',
    need_no_key: '否',
  });

  assert.equal(h.renderedTiles.length, 0);
  assert.equal(h.layers.length, 0);
  assert.equal(h.notices.at(-1).type, 'error');
  assert.match(h.notices.at(-1).message, /密钥输入框未加载/);
});

test('GeoSource refuses embedded username and password instead of silently dropping them', () => {
  for (const url of [
    'https://user:password@tiles.example.test/{z}/{x}/{y}',
    'https://@tiles.example.test/{z}/{x}/{y}',
  ]) {
    const h = createGeoSource([], { withCredentialDialog: true });
    h.geosource.loadService({
      service_id: 'basic-auth-tiles',
      service_name: 'Account protected tiles',
      protocol: 'XYZ',
      service_url: url,
      need_no_key: '是',
    });

    assert.equal(h.renderedTiles.length, 0);
    assert.equal(h.layers.length, 0);
    assert.equal(h.elements.geosourceCredentialModal.style.display, undefined);
  }

  const restored = createGeoSource([], { withCredentialDialog: true });
  const didLoad = restored.geosource.loadSavedServiceLayer({
    filename: 'Legacy account tiles',
    service_type: 'XYZ',
    url: 'https://user:password@tiles.example.test/{z}/{x}/{y}',
  });
  assert.equal(didLoad, false);
  assert.equal(restored.renderedTiles.length, 0);
  assert.equal(restored.layers.length, 0);
});

test('GeoSource data requests proxy a one-session key without persisting it', () => {
  const h = createGeoSource([], { withCredentialDialog: true });
  h.geosource.loadService({
    service_id: 'protected-geojson',
    service_name: 'Protected GeoJSON',
    protocol: 'GeoJSON',
    format: 'GeoJSON',
    service_url: 'https://data.example.test/roads.geojson',
    need_no_key: '否',
  });

  h.elements.geosourceCredentialParam.value = 'api_key';
  h.elements.geosourceCredentialValue.value = 'USER_KEY_SENTINEL';
  h.elements.geosourceCredentialSubmitBtn.click();

  assert.equal(h.fetchCalls.length, 1);
  assert.equal(h.fetchCalls[0].url, '/api/geosource/proxy');
  assert.equal(h.fetchCalls[0].init.method, 'POST');
  assert.equal(JSON.parse(h.fetchCalls[0].init.body).url,
    'https://data.example.test/roads.geojson?api_key=USER_KEY_SENTINEL');
  assert.equal(JSON.parse(h.fetchCalls[0].init.body).auth_parameter, 'api_key');
  assert.equal(JSON.stringify(h.layers).includes('USER_KEY_SENTINEL'), false);
});
