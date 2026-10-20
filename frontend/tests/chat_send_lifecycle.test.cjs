const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function createChatHarness(streamResponse) {
  const elements = new Map();
  const getElement = id => {
    if (!elements.has(id)) elements.set(id, {
      id, style: {}, dataset: {}, classList: { add() {}, remove() {}, toggle() {} },
      addEventListener() {}, appendChild() {}, remove() {}, focus() {},
      setAttribute() {}, querySelector() { return null; }, closest() { return null; },
    });
    return elements.get(id);
  };
  const tasks = [];
  let taskId = 0;
  const streamCalls = [];
  const api = {
    BASE_URL: 'http://127.0.0.1:8000',
    resolveProvider(id) { return { id, name: id, api_key: 'test-key' }; },
    getAmapKey() { return ''; },
  };
  const window = { GIS: {
    api,
    workspace: { toggleAI() {} },
    project: { getCurrentSessionId() { return 'session-a'; } },
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
    streamCalls.push(options.signal);
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
  return { window, tasks, streamCalls };
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
  const payload = 'data: ' + JSON.stringify({ type: 'done', response: '请求已完成', layers: [] });
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
  assert.equal(harness.window._aiRunning, false);
});
