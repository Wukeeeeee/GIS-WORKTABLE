const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function makeElement() {
  const listeners = {};
  const buttons = {};
  return {
    listeners, buttons, children: [], style: {}, className: '', classList: { add() {}, remove() {} },
    addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
    appendChild(child) { child.parentNode = this; this.children.push(child); return child; },
    removeChild(child) { this.children = this.children.filter(item => item !== child); child.parentNode = null; return child; },
    querySelector(selector) {
      if (buttons[selector]) return buttons[selector];
      if (selector === 'div:last-child') return this.children[this.children.length - 1] || null;
      const className = selector[0] === '.' ? selector.slice(1) : '';
      return this.children.find(child => (child.className || '').split(/\s+/).includes(className)) || null;
    },
    fire(name, event) { (listeners[name] || []).forEach(callback => callback(event)); },
  };
}

function loadUploadModule(readFailure) {
  const overlays = [];
  const uploadCalls = [];
  const elements = new Map();
  elements.set('chatMessages', makeElement());
  const document = {
    body: makeElement(),
    createElement() {
      const element = makeElement();
      element.buttons['.preview-btn-confirm'] = makeElement();
      element.buttons['.preview-btn-cancel'] = makeElement();
      return element;
    },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement());
      return id === 'chatMessages' ? elements.get(id) : null;
    },
  };
  document.body.appendChild = function(element) { element.parentNode = this; overlays.push(element); return element; };
  document.body.removeChild = function(element) { const index = overlays.indexOf(element); if (index >= 0) overlays.splice(index, 1); element.parentNode = null; };
  class FileReader {
    readAsText(file) {
      if (readFailure) { this.error = new Error('read failed'); this.onerror(); return; }
      this.result = file.content;
      this.onload();
    }
  }
  const window = { GIS: {
    utils: { escapeHtml: value => String(value) },
    api: { upload(file) { uploadCalls.push(file.name); return Promise.resolve({ error: 'test upload' }); } },
  } };
  const context = { window, document, FileReader, console, Promise, Map, Set, Array, Object, String, Number, Date, Math, RegExp,
    requestAnimationFrame(callback) { callback(); }, setTimeout() { return 1; }, clearTimeout() {} };
  const sourcePath = path.resolve(__dirname, '../js/upload.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return { upload: window.GIS.upload, overlays, uploadCalls, chatMessages: elements.get('chatMessages') };
}

test('CSV upload preview preserves quoted commas, escaped quotes, and embedded newlines', async () => {
  const harness = loadUploadModule();
  const content = '\uFEFFname,note\r\n"New York, NY","line 1\r\nline 2"\r\n"said ""hi""",plain';
  const file = { name: 'places.csv', size: content.length, content, slice() { return { content }; } };
  harness.upload.handleFiles([file]);

  const overlay = harness.overlays[0];
  assert.ok(overlay, 'CSV should open the pre-upload preview');
  assert.match(overlay.innerHTML, /<th>name<\/th><th>note<\/th>/);
  assert.match(overlay.innerHTML, /<td>New York, NY<\/td><td>line 1\r?\nline 2<\/td>/);
  assert.match(overlay.innerHTML, /<td>said "hi"<\/td><td>plain<\/td>/);
  overlay.querySelector('.preview-btn-cancel').fire('click');
  assert.equal(harness.overlays.length, 0);
});

test('CSV preview read failure stops instead of implicitly confirming upload', async () => {
  const harness = loadUploadModule(true);
  const file = { name: 'unreadable.csv', size: 10, content: '', slice() { return this; } };
  harness.upload.handleFiles([file]);
  await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(harness.uploadCalls, []);
  assert.match(harness.chatMessages.children[0].children[0].innerHTML, /无法读取文件预览，文件未上传/);
});
