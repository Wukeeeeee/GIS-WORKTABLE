const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.className = '';
    this.style = {};
    this.disabled = false;
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
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  get childNodes() { return this.children; }
  set innerHTML(value) { this._innerHTML = value; if (value === '') this.children = []; }
  get innerHTML() { return this._innerHTML || ''; }
}

function createHarness() {
  const ids = ['historyPanel', 'historyBody', 'toggleHistoryPanel', 'toolHistClearBtn', 'toolHistCloseBtn'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const requests = [];
  const messages = [];
  let ready;
  const document = {
    readyState: 'loading',
    getElementById(id) { return elements[id] || null; },
    createElement() { return new Element(); },
    addEventListener(name, callback) { if (name === 'DOMContentLoaded') ready = callback; },
  };
  const window = { GIS: { api: { BASE_URL: '' }, chat: { addMessage(message) { messages.push(message); } } } };
  const fetch = (url, options = {}) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
  const sourcePath = path.resolve(__dirname, '../js/history.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, fetch, Promise, JSON, Array, String, Date, Object, Number, Map, Set,
    navigator: {}, console,
  }, { filename: sourcePath });
  ready();
  return { history: window.GIS.history, elements, requests, messages };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function historyResponse(entries) {
  return { ok: true, json: () => Promise.resolve({ history: entries }) };
}

test('late history refresh cannot repopulate the list after clearing it', async () => {
  const h = createHarness();
  h.elements.toggleHistoryPanel.listeners.click[0]();
  assert.equal(h.requests[0].url, '/api/history?limit=50');

  h.elements.toolHistClearBtn.listeners.click[0]();
  assert.equal(h.requests[1].options.method, 'DELETE');
  h.requests[1].resolve({ ok: true });
  await flushPromises();
  assert.match(h.elements.historyBody.innerHTML, /暂无记录/);

  h.requests[0].resolve(historyResponse([{ index: 7, tool: 'old result', ok: true, args: {}, time: '' }]));
  await flushPromises();
  assert.equal(h.elements.historyBody.children.length, 0);
  assert.match(h.elements.historyBody.innerHTML, /暂无记录/);
});

test('failed history deletion preserves visible records and reports the failure', async () => {
  const h = createHarness();
  h.elements.toggleHistoryPanel.listeners.click[0]();
  h.requests[0].resolve(historyResponse([{ index: 3, tool: 'buffer', ok: true, args: {}, time: '' }]));
  await flushPromises();
  assert.equal(h.elements.historyBody.children.length, 1);

  h.elements.toolHistClearBtn.listeners.click[0]();
  h.requests[1].resolve({ ok: false, status: 500 });
  await flushPromises();

  assert.equal(h.elements.historyBody.children.length, 1);
  assert.match(h.messages[0], /清空处理历史失败/);
});
