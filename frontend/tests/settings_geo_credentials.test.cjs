const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor() { this.listeners = {}; this.dataset = {}; this.style = {}; this.value = ''; this.classList = { add() {}, remove() {}, toggle() {} }; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  fire(name) { (this.listeners[name] || []).forEach(callback => callback.call(this, { target: this })); }
}

function createHarness(initialCredentials = {}, providers = [], initialStatuses = {}, amapSave = () => Promise.resolve(), isEnglish = false) {
  const saveButton = new Element();
  saveButton.dataset.cred = 'copernicus';
  const username = new Element();
  const password = new Element();
  const status = new Element();
  const message = new Element();
  const amapInput = new Element();
  const amapSaveButton = new Element();
  const amapStatus = new Element();
  const amapMessage = new Element();
  const queryElements = new Map([
    ['.geo-cred-user[data-cred="copernicus"]', username],
    ['.geo-cred-pass[data-cred="copernicus"]', password],
    ['.geo-cred-msg[data-cred="copernicus"]', message],
    ['[data-cred-status="copernicus"]', status],
  ]);
  const idElements = new Map([
    ['amapApiKeyInput', amapInput], ['saveAmapKeyBtn', amapSaveButton],
    ['amapKeyStatus', amapStatus], ['amapTestResult', amapMessage],
  ]);
  const requests = [];
  const providerStatuses = Object.assign({}, initialStatuses);
  const providerChecks = [];
  const amapSaveCalls = [];
  let credentials = structuredClone(initialCredentials);
  let amapKey = '';
  const document = {
    readyState: 'loading',
    documentElement: { classList: { toggle() {} }, style: { setProperty() {} } },
    getElementById(id) { return idElements.get(id) || null; },
    querySelector(selector) { return queryElements.get(selector) || null; },
    querySelectorAll(selector) { return selector === '.geo-cred-save' ? [saveButton] : []; },
    addEventListener() {},
  };
  const amapTranslations = {
    'settings.amap-saving': 'Encrypting and saving…',
    'settings.amap-saved': 'Saved to browser and encrypted credential store',
  };
  const window = { GIS: {
    i18n: { t(key, fallback) { return isEnglish ? (amapTranslations[key] || fallback) : fallback; }, isEnglish() { return isEnglish; } },
    api: {
    BASE_URL: '',
    getGeoCredentials() { return credentials; },
    setGeoCredentials(next) { credentials = next; },
    setGeoCredential(service, credential) { credentials[service] = credential; },
    getProviders() { return providers; },
    setModelStatus(id, status) { providerStatuses[id] = status; },
    getModelStatus(id) { return providerStatuses[id] || 'untested'; },
    testProvider(provider) { providerChecks.push(provider.id); return Promise.resolve({ success: true }); },
    getAmapKey() { return amapKey; },
    setAmapKey(key) { amapKey = key; amapSaveCalls.push(key); return amapSave(key); },
  } } };
  const fetch = (url, options) => new Promise(resolve => requests.push({ url, options, resolve }));
  const sourcePath = path.resolve(__dirname, '../js/settings.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, fetch, Promise, Array, Object, String, Number, Math, Date, Set, Map,
    JSON, encodeURIComponent, console: { warn() {}, log() {} }, setTimeout() { return 1; },
  }, { filename: sourcePath });
  window.GIS.settings.init();
  return {
    saveButton, username, password, status, message, requests, providerStatuses, providerChecks,
    amapInput, amapSaveButton, amapStatus, amapMessage, amapSaveCalls,
    get credentials() { return credentials; },
  };
}

async function settleRequest(request, response) {
  request.resolve(response);
  await new Promise(resolve => setImmediate(resolve));
}

test('clearing a credential removes the local value and calls backend delete', async () => {
  const h = createHarness({ copernicus: { type: 'account', username: 'old-user', password: 'old-secret' } });
  h.username.value = '';
  h.password.value = '';
  h.saveButton.fire('click');

  assert.equal(h.credentials.copernicus, undefined);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/geo-credentials/copernicus');
  assert.equal(h.requests[0].options.method, 'DELETE');
  await settleRequest(h.requests[0], { ok: true, status: 200, json: () => Promise.resolve({ status: 'ok', deleted: true }) });
  assert.equal(h.message.textContent, '已从本地与后端清除');
});

test('startup clears stale model badges without sending provider test requests', () => {
  const providers = [
    { id: 'provider-a', api_key: 'user-key-a' },
    { id: 'provider-b', api_key: 'user-key-b' },
  ];
  const h = createHarness({}, providers, { 'provider-a': 'online', 'provider-b': 'offline' });

  assert.deepEqual(h.providerStatuses, { 'provider-a': 'untested', 'provider-b': 'untested' });
  assert.deepEqual(h.providerChecks, []);
});

test('Amap key is saved only on button click and UI reports backend confirmation', async () => {
  const h = createHarness();
  h.amapInput.value = 'amap-test-key';
  h.amapInput.fire('change');
  assert.deepEqual(h.amapSaveCalls, []);

  h.amapSaveButton.fire('click');
  assert.equal(h.amapSaveButton.disabled, true);
  assert.equal(h.amapMessage.textContent, '正在加密保存…');
  assert.deepEqual(h.amapSaveCalls, ['amap-test-key']);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.amapStatus.textContent, '已配置');
  assert.equal(h.amapMessage.textContent, '已保存到浏览器与本机加密凭据库');
  assert.equal(h.amapSaveButton.disabled, false);
});

test('Amap encrypted-sync failure is not shown as a successful save', async () => {
  const h = createHarness({}, [], {}, () => Promise.reject(new Error('storage unavailable')));
  h.amapInput.value = 'amap-test-key';
  h.amapSaveButton.fire('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.amapMessage.textContent, '当前浏览器已保存，但后端加密同步失败：storage unavailable');
  assert.equal(h.amapSaveButton.disabled, false);
});

test('Amap save progress and confirmation use the active language', async () => {
  const h = createHarness({}, [], {}, () => Promise.resolve(), true);
  h.amapInput.value = 'amap-test-key';
  h.amapSaveButton.fire('click');
  assert.equal(h.amapMessage.textContent, 'Encrypting and saving…');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.amapMessage.textContent, 'Saved to browser and encrypted credential store');
});

test('partial account credentials are rejected without replacing saved credentials', () => {
  const h = createHarness({ copernicus: { type: 'account', username: 'old-user', password: 'old-secret' } });
  h.username.value = 'new-user';
  h.password.value = '';
  h.saveButton.fire('click');

  assert.equal(h.requests.length, 0);
  assert.equal(h.credentials.copernicus.password, 'old-secret');
  assert.match(h.message.textContent, /同时填写用户名和密码/);
});

test('backend save failure is not reported as encrypted-save success', async () => {
  const h = createHarness();
  h.username.value = 'new-user';
  h.password.value = 'new-secret';
  h.saveButton.fire('click');
  await settleRequest(h.requests[0], { ok: false, status: 503, json: () => Promise.resolve({ detail: 'unavailable' }) });

  assert.equal(h.credentials.copernicus.username, 'new-user');
  assert.equal(h.message.textContent, '本地已保存，后端加密保存失败');
  assert.notEqual(h.message.textContent, '已保存（后端加密存储）');
});
