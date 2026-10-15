// Minimal DOM harness that smoke-tests frontend/js/analysis_tools.js.
// It boots the module in a Node VM, builds the "all tools" launcher and opens
// one per-tool window, then asserts both were created without throwing.
// Usage: node analysis_panel_dom_harness.js <path-to-analysis_tools.js>
const fs = require('fs');
const vm = require('vm');

const target = process.argv[2];
if (!target) { console.error('usage: node analysis_panel_dom_harness.js <file>'); process.exit(2); }

const ALL = [];

function makeStyle() {
  return {
    setProperty() {}, removeProperty() {}, getPropertyValue() { return ''; },
  };
}

function makeEl(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    style: makeStyle(),
    dataset: {},
    attributes: {},
    children: [],
    listeners: {},
    value: '',
    textContent: '',
    innerHTML: '',
    checked: false,
    selected: false,
    disabled: false,
    offsetWidth: 0,
    offsetHeight: 0,
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); },
      toggle(c, on) {
        if (on === undefined) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); }
        else if (on) { this._s.add(c); } else { this._s.delete(c); }
      },
    },
    _q: {},
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    insertBefore(c) { this.children.push(c); c.parentNode = this; return c; },
    removeChild(c) { return c; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    removeEventListener() {},
    dispatchEvent() { return true; },
    querySelector(sel) { return this._q[sel] || (this._q[sel] = makeEl('div')); },
    querySelectorAll() { return []; },
    closest() { return makeEl('div'); },
    getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k); },
    removeAttribute(k) { delete this.attributes[k]; },
    focus() {}, click() {}, select() {},
  };
  Object.defineProperty(el, 'firstElementChild', {
    get() { return this._first || (this._first = makeEl('div')); },
  });
  ALL.push(el);
  return el;
}

const byId = new Map();
function el(id) { if (!byId.has(id)) byId.set(id, makeEl('div')); return byId.get(id); }

const document = {
  documentElement: makeEl('html'),
  body: makeEl('body'),
  createElement: (t) => makeEl(t),
  createTextNode: (t) => ({ textContent: t }),
  getElementById: (id) => el(id),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
};

const sandbox = {
  console, document,
  Event: function (type) { this.type = type; },
  fetch: () => Promise.resolve({ json: () => Promise.resolve({ names: [] }) }),
  setTimeout, clearTimeout, Promise, Math, Date, JSON, Object, Array, String,
  Number, Boolean, RegExp, Error, isNaN, parseFloat, parseInt,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.innerWidth = 1400;
sandbox.innerHeight = 900;
sandbox.addEventListener = () => {};
sandbox.removeEventListener = () => {};
sandbox.GIS = {};

vm.createContext(sandbox);
try {
  vm.runInContext(fs.readFileSync(target, 'utf8'), sandbox, { filename: target });
} catch (e) {
  console.error('LOAD ERROR: ' + (e && e.message));
  process.exit(1);
}

const api = sandbox.GIS.analysisTools;
if (!api) { console.error('GIS.analysisTools missing'); process.exit(1); }
for (const fn of ['init', 'activate', 'deactivate', 'toggle', 'openWith']) {
  if (typeof api[fn] !== 'function') { console.error('missing API ' + fn); process.exit(1); }
}

try {
  api.init();
  api.activate();
  api.openWith('join');
} catch (e) {
  console.error('RUNTIME ERROR: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e));
  process.exit(1);
}

function fail(msg) { console.error('ASSERT FAILED: ' + msg); process.exit(1); }

const launcher = ALL.find((e) => e.id === 'analysisToolsPanelContainer');
if (!launcher) fail('launcher container #analysisToolsPanelContainer was not created');

const toolPanel = ALL.find((e) => e.getAttribute('data-at-suffix') === 'join');
if (!toolPanel) fail('per-tool window for op "join" was not created');

const launcherButtons = ALL.filter((e) => e.className === 'at-tool-btn');
if (launcherButtons.length !== 20) fail('launcher should list 20 tools, got ' + launcherButtons.length);

console.log('OK: launcher + per-tool window built without errors');