const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

class Element {
  constructor() { this.children = []; this.listeners = {}; this.dataset = {}; this.style = {}; this.attributes = {}; }
  appendChild(child) { child.parentNode = this; this.children.push(child); }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  fire(name) { (this.listeners[name] || []).forEach(callback => callback.call(this, { target: this })); }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  remove() { this.removed = true; }
}

function createHarness() {
  const chatMessages = new Element();
  const calls = [];
  const notices = [];
  let appliedResults = 0;
  const window = { GIS: {
    api: { invokeTool(name, args) { return new Promise((resolve, reject) => calls.push({ name, args, resolve, reject })); } },
    chat: {
      addMessage(message) { notices.push(message); },
      applyToolResult() { appliedResults++; },
    },
  } };
  const document = {
    getElementById(id) { return id === 'chatMessages' ? chatMessages : null; },
    createElement() { return new Element(); },
  };
  const sourcePath = path.resolve(__dirname, '../js/aoi.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Array, String, console: { error() {} },
  }, { filename: sourcePath });
  window.GIS.aoi.showSuggestions([{ id: 'candidate-1', name: '候选地点' }, { id: 'candidate-2', name: '另一个地点' }]);
  const row = chatMessages.children[0];
  const bubble = row.children[1];
  const choices = bubble.children.filter(child => child.dataset.index !== undefined);
  return { calls, notices, choices, hint: row._aoiHint, row, get appliedResults() { return appliedResults; } };
}

test('AOI keeps failed candidates retryable and prevents duplicate extraction while pending', async () => {
  const h = createHarness();
  h.choices[0].fire('click');
  h.choices[0].fire('click');
  h.choices[1].fire('click');
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].name, 'cn_aoi_extract');

  h.calls[0].resolve({ ok: true, response: '未能提取候选地点的AOI轮廓', layers: [] });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.row.removed, undefined);
  assert.match(h.hint.textContent, /可重试/);
  assert.equal(h.choices[0].style.pointerEvents, '');
  assert.equal(h.appliedResults, 0);

  h.choices[1].fire('click');
  assert.equal(h.calls.length, 2);
  h.calls[1].resolve({ ok: true, response: '成功提取另一个地点', layers: [{ name: '另一个地点', geojson: {} }] });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.row.removed, true);
  assert.equal(h.appliedResults, 1);
});
