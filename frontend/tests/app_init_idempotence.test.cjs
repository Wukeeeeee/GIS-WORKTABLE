const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

test('app init does not initialize modules or bind global handlers twice', () => {
  const counts = { map: 0, chat: 0, layers: 0, upload: 0, aoi: 0, task: 0, project: 0, settings: 0 };
  const eventCounts = {};
  const documentListeners = {};
  let timerCount = 0;
  const document = {
    readyState: 'loading',
    addEventListener(name, callback) {
      eventCounts[name] = (eventCounts[name] || 0) + 1;
      documentListeners[name] = callback;
    },
    getElementById() { return null; },
    querySelector() { return null; },
    createElement() { return { style: {}, appendChild() {}, set textContent(value) { this._text = value; } }; },
  };
  const module = name => ({ init() { counts[name]++; } });
  const window = { GIS: {
    map: module('map'), chat: module('chat'), layers: module('layers'), upload: module('upload'),
    aoi: module('aoi'), task: module('task'), project: module('project'), settings: module('settings'),
  } };
  const sourcePath = path.resolve(__dirname, '../js/app.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, console: { log() {}, warn() {}, error() {} }, Date,
    setInterval() { timerCount++; return timerCount; }, clearInterval() {},
  }, { filename: sourcePath });

  window.GIS.app.init();
  assert.ok(Object.values(counts).every(count => count === 0));
  document.readyState = 'interactive';
  documentListeners.DOMContentLoaded();
  window.GIS.app.init();

  Object.values(counts).forEach(count => assert.equal(count, 1));
  assert.equal(eventCounts.DOMContentLoaded, 1);
  assert.equal(eventCounts.keydown, 1);
  assert.equal(timerCount, 1);
});
