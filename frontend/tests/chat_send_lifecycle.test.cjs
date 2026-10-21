const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function createChatHarness(streamResponse) {
  const elements = new Map();
  const getElement = id => {
    if (!elements.has(id)) {
      const listeners = {};
      elements.set(id, {
        id, style: {}, dataset: {}, listeners, value: '', selectionStart: 0, selectionEnd: 0,
        classList: { add() {}, remove() {}, toggle() {} },
        addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
        dispatch(name, event) { (listeners[name] || []).forEach(callback => callback(event)); },
        appendChild() {}, remove() {}, focus() {},
        setAttribute() {}, querySelector() { return null; }, querySelectorAll() { return []; }, closest() { return null; },
      });
    }
    return elements.get(id);
  };
  const tasks = [];
  let taskId = 0;
  const streamCalls = [];
  const exportCalls = [];
  const api = {
    BASE_URL: 'http://127.0.0.1:8000',
    resolveProvider(id) { return { id, name: id, api_key: 'test-key' }; },
    getAmapKey() { return ''; },
  };
  const window = { GIS: {
    api,
    workspace: { toggleAI() {} },
    project: { getCurrentSessionId() { return 'session-a'; } },
    map: {
      exportMap(format) { exportCalls.push({ action: 'png', format }); },
      exportPdf(title) { exportCalls.push({ action: 'pdf', title }); },
    },
    layers: { getLayers() { return []; } },
    task: {
      createTask() { const task = { id: String(++taskId), status: 'pending' }; tasks.push(task); return task; },
      updateTask(id, updates) { Object.assign(tasks.find(task => task.id === id), updates); },
    },
  } };
  getElement('modelSelector').value = 'test-provider';
  getElement('modelSelectValue').textContent = 'test-provider';
  const document = {
    body: { appendChild() {} },
    createElement() { return {
      style: {}, classList: { add() {}, remove() {}, toggle() {} }, children: [],
      appendChild(child) { this.children.push(child); }, setAttribute() {}, remove() {},
    }; },
    getElementById: getElement,
    getElementsByClassName() { return []; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
  const fetch = (url, options) => {
    if (url.includes('/api/cancel')) return Promise.resolve({ ok: true });
    if (!url.endsWith('/api/chat/stream')) return Promise.resolve({ ok: true });
    streamCalls.push({ signal: options.signal, body: JSON.parse(options.body || '{}') });
    if (streamResponse) return Promise.resolve(streamResponse);
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      }, { once: true });
    });
  };
  const sourcePath = path.resolve(__dirname, '../js/chat.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, fetch, AbortController, TextDecoder, Promise, Map, Set, Array,
    Object, String, Number, Math, Date, JSON, RegExp, URL, console: { log() {}, warn() {}, error() {} },
    sessionStorage: { getItem() { return '0'; } },
    setTimeout() { return 1; }, clearTimeout() {}, setInterval() { return 1; }, clearInterval() {},
  }, { filename: sourcePath });
  return { window, tasks, streamCalls, exportCalls, elements, getElement };
}

test('replacing a chat request cancels its task without letting stale cleanup unlock the new request', async () => {
  const harness = createChatHarness();
  const first = harness.window.GIS.chat.send('第一条任务');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.streamCalls.length, 1);

  const second = harness.window.GIS.chat.send('第二条任务');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.streamCalls.length, 2);
  await first;

  assert.equal(harness.tasks[0].status, 'cancelled');
  assert.equal(harness.tasks[1].status, 'planning');
  assert.equal(harness.window._aiRunning, true);
  assert.equal(harness.window._aiAbortController.signal.aborted, false);

  harness.window._aiAbortController.abort('user-cancel');
  await second;
  assert.equal(harness.tasks[1].status, 'cancelled');
  assert.equal(harness.window._aiRunning, false);
});

test('chat stream accepts a final done event without a trailing newline', async () => {
  const payload = 'data: ' + JSON.stringify({ type: 'done', response: '请求已完成', layers: [], task_id: 'backend-task-1' });
  const bytes = new TextEncoder().encode(payload);
  let readCount = 0;
  const harness = createChatHarness({
    ok: true,
    body: { getReader() {
      return { read() {
        return Promise.resolve(readCount++ === 0
          ? { done: false, value: bytes }
          : { done: true });
      } };
    } },
  });

  await harness.window.GIS.chat.send('单轮测试');

  assert.equal(harness.tasks[0].status, 'success', JSON.stringify(harness.tasks[0]));
  assert.equal(harness.tasks[0].backendTaskId, 'backend-task-1');
  assert.equal(harness.window._aiRunning, false);

  harness.window.GIS.chat.setTaskReference('backend-task-1', '请求已完成');
  await harness.window.GIS.chat.send('把刚才的图改成蓝色');
  assert.equal(harness.streamCalls[1].body.task_id, 'backend-task-1');
  assert.match(harness.streamCalls[1].body.quoted, /backend-task-1|历史 GIS 任务/);
});

test('AI layer rename updates the panel registration identity used by later deletion', async () => {
  const payload = 'data: ' + JSON.stringify({ type: 'done', response: '已重命名', layers: [], layer_ops: [
    { action: 'rename', name: 'registered-name', new_name: 'renamed-name' },
  ] });
  const bytes = new TextEncoder().encode(payload);
  let readCount = 0;
  const harness = createChatHarness({
    ok: true,
    body: { getReader() { return { read() { return Promise.resolve(readCount++ === 0 ? { done: false, value: bytes } : { done: true }); } }; } },
  });
  const layer = { layer_id: 'layer-1', filename: 'registered-name', _rawName: 'registered-name', _registeredName: 'registered-name' };
  const renames = [];
  harness.window.GIS.layers.getLayers = () => [layer];
  harness.window.GIS.layers.renderList = () => {};
  harness.window.GIS.state = { renameLayer(id, name) { renames.push([id, name]); } };
  harness.window.GIS.map.renameLayer = (oldName, newName) => renames.push([oldName, newName]);

  await harness.window.GIS.chat.send('重命名这个图层');

  assert.equal(layer.filename, 'renamed-name');
  assert.equal(layer._rawName, 'renamed-name');
  assert.equal(layer._registeredName, 'renamed-name');
  assert.deepEqual(JSON.parse(JSON.stringify(renames)), [
    ['layer-1', 'renamed-name'], ['registered-name', 'renamed-name'],
  ]);
});

test('hyphenated map export slash commands remain selectable and route directly without AI', () => {
  const harness = createChatHarness();
  const slashMenu = harness.getElement('slashMenu');
  const slashBody = harness.getElement('slashMenuBody');
  harness.window.GIS.chat.init();
  const input = harness.elements.get('chatInput');

  function chooseCommand(name) {
    input.value = '/' + name;
    input.selectionStart = input.value.length;
    input.dispatch('input', {});
    assert.equal(slashMenu.style.display, '', '/' + name + ' should keep the command menu open');
    assert.match(slashBody.innerHTML, new RegExp('/' + name));
    const event = { key: 'Enter', preventDefault() { this.defaultPrevented = true; } };
    input.dispatch('keydown', event);
    assert.equal(event.defaultPrevented, true);
    assert.equal(input.value, '', 'selected slash command should be removed from the input');
  }

  chooseCommand('export-map');
  chooseCommand('export-pdf');

  assert.deepEqual(harness.exportCalls, [
    { action: 'png', format: 'png' },
    { action: 'pdf', title: '地图导出' },
  ]);
  assert.equal(harness.streamCalls.length, 0, 'direct export commands must not start an AI request');
});
