const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function createChatHarness(streamResponse, withExecutionCards = false, layerListResponse = { layers: [] }, markedMock) {
  const elements = new Map();
  const getElement = id => {
    if (!elements.has(id)) {
      const listeners = {};
      elements.set(id, {
        id, style: {}, dataset: {}, listeners, children: [], value: '', selectionStart: 0, selectionEnd: 0,
        classList: { add() {}, remove() {}, toggle() {} },
        addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
        dispatch(name, event) { (listeners[name] || []).forEach(callback => callback(event)); },
        appendChild(child) { this.children.push(child); }, remove() {}, focus() {},
        setAttribute() {}, querySelector() { return null; }, querySelectorAll() { return []; }, closest() { return null; },
      });
    }
    return elements.get(id);
  };
  const tasks = [];
  let taskId = 0;
  const streamCalls = [];
  const exportCalls = [];
  const executionRows = [];
  const createdElements = [];
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
    body: { appendChild() {}, removeChild() {} },
    documentElement: { classList: { contains() { return false; } } },
    createElement() { const element = {
      style: {}, dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, children: [],
      appendChild(child) { this.children.push(child); }, setAttribute() {}, remove() { this.removed = true; },
      click() { this.clicked = true; },
      insertAdjacentElement(position, element) { executionRows.push(element); },
      querySelector() { return null; }, querySelectorAll() { return []; }, addEventListener() {}, closest() { return null; },
    }; createdElements.push(element); return element; },
    getElementById: getElement,
    getElementsByClassName() { return []; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
  const fetch = (url, options) => {
    if (url.includes('/api/cancel')) return Promise.resolve({ ok: true });
    if (url.endsWith('/api/layers')) return Promise.resolve({ ok: true, json() { return Promise.resolve(layerListResponse); } });
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
  const context = vm.createContext({
    window, document, fetch, AbortController, TextDecoder, Promise, Map, Set, Array,
    Object, String, Number, Math, Date, JSON, RegExp, URL, console: { log() {}, warn() {}, error() {} },
    marked: markedMock,
    sessionStorage: { getItem() { return '0'; } },
    requestAnimationFrame(callback) { callback(); },
    setTimeout() { return 1; }, clearTimeout() {}, setInterval() { return 1; }, clearInterval() {},
  });
  if (withExecutionCards) vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../js/execution_cards.js'), 'utf8'), context);
  const chatSource = fs.readFileSync(sourcePath, 'utf8').replace(
    'GIS.chat = { init, send,',
    'GIS.chat = { _renderChatMarkdown: _renderChatMarkdown, _linkRenderer: _linkRenderer, _attachOutputButtons: _attachOutputButtons, _downloadFile: downloadFile, addMessage, init, send,',
  );
  vm.runInContext(chatSource, context, { filename: sourcePath });
  return { window, context, tasks, streamCalls, exportCalls, elements, getElement, executionRows, createdElements };
}

test('plain user chat messages render as text instead of executable HTML', () => {
  const h = createChatHarness();
  h.window.GIS.chat.init();
  const rawHtml = '<img src=x onerror=alert(1)>';
  h.window.GIS.chat.addMessage(rawHtml, 'user');

  const row = h.elements.get('chatMessages').children[0];
  const bubble = row.children[1];
  const content = bubble.children[0];
  assert.equal(content.textContent, rawHtml);
  assert.equal(content.innerHTML, undefined);
});

test('chat markdown escapes raw HTML and blocks executable link schemes', () => {
  class Renderer {}
  const parsed = [];
  const marked = {
    Renderer,
    parse(text, options) { parsed.push({ text, options }); return '<p>safe</p>'; },
    parseInline(text, options) { parsed.push({ text, options }); return '<span>safe</span>'; },
  };
  const h = createChatHarness(null, false, { layers: [] }, marked);
  const rawHtml = '<img src=x onerror=alert(1)>';
  h.window.GIS.chat._renderChatMarkdown(rawHtml, false);
  const renderer = parsed[0].options.renderer;

  assert.equal(renderer.html({ text: rawHtml }), '&lt;img src=x onerror=alert(1)&gt;');
  assert.equal(renderer.link({ href: 'javascript:alert(2)', text: 'run code' }), 'run code');
  assert.equal(renderer.link({ href: 'https://safe.test/" onclick="alert(3)', text: 'safe link' }),
    '<a href="https://safe.test/&quot; onclick=&quot;alert(3)" target="_blank" rel="noopener noreferrer" class="chat-markdown-link">safe link</a>');
  assert.match(renderer.link({ href: 'https://example.test/path', text: 'safe link' }),
    /href="https:\/\/example\.test\/path"/);
  assert.equal(renderer.image({ href: 'https://tracker.example/pixel.png', text: 'external image' }), 'external image');
  assert.match(renderer.image({ href: '/output/chart.png', text: 'local chart' }), /src="\/output\/chart\.png"/);
  assert.equal(parsed[0].options.renderer, h.window.GIS.chat._linkRenderer);
});

test('HTML artifact iframes run in an opaque sandboxed origin', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../js/chat.js'), 'utf8');

  assert.match(source, /iframe\.setAttribute\(['"]sandbox['"],\s*['"]allow-scripts['"]\)/);
});

test('chat file download checks HTTP failure responses instead of saving their bodies', async () => {
  const h = createChatHarness();
  const messages = [];
  h.window.GIS.chat.addMessage = (message, type) => messages.push({ message, type });
  h.context.fetch = async () => ({ ok: false, status: 404, blob: async () => ({}) });
  h.window.GIS.chat._downloadFile('/output/missing.geojson', 'missing.geojson');
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(h.createdElements.some(element => element.clicked), false);
  assert.equal(messages.length, 1);
  assert.match(messages[0].message, /下载失败.*404/);
  assert.equal(messages[0].type, 'system');
});

test('chat file download delays Blob URL revocation after starting the browser download', async () => {
  const h = createChatHarness();
  const revoked = [];
  const scheduled = [];
  h.context.URL = {
    createObjectURL() { return 'blob:chat-download'; },
    revokeObjectURL(url) { revoked.push(url); },
  };
  h.context.setTimeout = (callback, delay) => { scheduled.push({ callback, delay }); return 77; };
  h.context.fetch = async () => ({ ok: true, blob: async () => ({}) });
  h.window.GIS.chat._downloadFile('/output/result.csv', 'result.csv');
  await new Promise(resolve => setImmediate(resolve));

  const anchor = h.createdElements.find(element => element.href === 'blob:chat-download');
  assert.ok(anchor && anchor.clicked, 'the download link should be clicked');
  assert.deepEqual(revoked, [], 'the Blob URL should remain valid after the click');
  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].delay, 1000);

  scheduled[0].callback();
  assert.deepEqual(revoked, ['blob:chat-download']);
});

test('chat attachment cards recognize supported artifact file paths', () => {
  for (const extension of ['svg', 'webp', 'gif', 'pdf', 'xls', 'xlsx', 'md', 'txt']) {
    const h = createChatHarness();
    const filePath = '/output/chart.' + extension;
    const textNode = {
      textContent: filePath,
      querySelector() { return null; },
      contains() { return false; },
    };
    const children = [];
    const content = {
      _outputBtnsAttached: false,
      querySelectorAll(selector) {
        if (selector === '*' || selector === 'img') return [];
        return [textNode];
      },
      closest() { return null; },
      appendChild(child) { children.push(child); },
    };

    assert.equal(h.window.GIS.chat._attachOutputButtons(content), true, extension);
    assert.equal(children[0].className, 'chat-outputs-shelf');
    assert.ok(h.createdElements.some(element => element.className === 'chat-file-btn-secondary'), extension);
  }
});

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

test('streaming chat sends the provider key only inside llm_config', async () => {
  const payload = 'data: ' + JSON.stringify({ type: 'done', response: '完成', layers: [] }) + '\n\n';
  const bytes = new TextEncoder().encode(payload);
  let reads = 0;
  const harness = createChatHarness({
    ok: true,
    body: { getReader() { return { read() {
      return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
    } }; } },
  });

  await harness.window.GIS.chat.send('你好');

  const body = harness.streamCalls[0].body;
  assert.equal(body.llm_config.api_key, 'test-key');
  assert.equal(Object.hasOwn(body, 'api_key'), false);
});

test('streaming chat keeps the backend transport-security explanation', async () => {
  const detail = '公网模型地址必须使用 HTTPS';
  const harness = createChatHarness({
    ok: false, status: 400, json: async () => ({ detail }),
  });
  harness.window.GIS.api.chat = async () => { throw new Error(detail); };

  await harness.window.GIS.chat.send('你好');

  assert.match(harness.tasks[0].error, /公网模型地址必须使用 HTTPS/);
});

test('chat stops before calling the AI when a current layer cannot sync to backend analysis state', async () => {
  const harness = createChatHarness();
  harness.window.GIS.layers.getLayers = () => [{ layer_id: 'layer-1', filename: 'demo', geojson: { type: 'FeatureCollection', features: [] } }];
  harness.window.GIS.layers.syncToolLayer = async () => false;

  await harness.window.GIS.chat.send('分析 demo 图层');

  assert.equal(harness.streamCalls.length, 0, 'AI must not run with stale or missing backend layer data');
  assert.equal(harness.tasks[0].status, 'failed');
  assert.match(harness.tasks[0].error, /图层未能同步/);
  assert.equal(harness.window._aiRunning, false);
});

test('chat synchronizes vector and raster layers through the shared registry before starting the AI stream', async () => {
  const payload = 'data: ' + JSON.stringify({ type: 'done', response: '完成', layers: [] });
  const bytes = new TextEncoder().encode(payload);
  let reads = 0;
  const harness = createChatHarness({
    ok: true,
    body: { getReader() { return { read() { return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true }); } }; } },
  });
  const synced = [];
  harness.window.GIS.layers.getLayers = () => [
    { filename: 'vector-demo', geojson: { type: 'FeatureCollection', features: [] } },
    { filename: 'raster-demo', raster: { url: '/output/demo.tif' } },
  ];
  harness.window.GIS.layers.syncToolLayer = async name => { synced.push(name); return true; };

  await harness.window.GIS.chat.send('查看当前数据');

  assert.deepEqual(synced, ['vector-demo', 'raster-demo']);
  assert.equal(harness.streamCalls.length, 1);
});

test('raster analysis results enter the layer panel with project-ready source metadata', () => {
  const harness = createChatHarness();
  const op = { action: 'dem_result', name: 'terrain_slope.png', layer_name: 'terrain_slope',
    url: '/output/uploads/terrain_slope.png', bounds: [100, 30, 101, 31], crs: 'EPSG:4326',
    registration_token: 'raster-version', raster: {
      filename: 'terrain_slope.png', url: '/output/uploads/terrain_slope.png',
      source_filename: 'terrain_slope.tif', source_url: '/output/uploads/terrain_slope.tif',
      bounds: [100, 30, 101, 31], width: 64, height: 48,
    } };
  const overlays = [];
  const addedLayers = [];
  let autoSaves = 0;
  harness.window.GIS.map.addImageOverlay = (...args) => overlays.push(args);
  harness.window.GIS.layers.getLayers = () => addedLayers;
  harness.window.GIS.layers.addLayer = (layer, skipRegister) => {
    addedLayers.push(layer);
    assert.equal(skipRegister, true, 'the backend already registered this raster and token');
  };
  harness.window.GIS.project = { autoSave() { autoSaves++; } };

  harness.window.GIS.chat.applyToolResult({ layer_ops: [op] });

  assert.deepEqual(overlays, [[op.url, op.bounds, op.name, op.layer_name]]);
  assert.equal(addedLayers[0].filename, 'terrain_slope');
  assert.equal(addedLayers[0].raster.source_filename, 'terrain_slope.tif');
  assert.equal(addedLayers[0]._registrationTokens.terrain_slope, 'raster-version');
  assert.equal(autoSaves, 1);
});

test('layer recovery requires an exact name and warns instead of attaching a similarly named layer', async () => {
  const geojson = { type: 'FeatureCollection', features: [] };
  const event = { type: 'done', response: '已处理图层', layers: [], layer_ops: [
    { action: 'set_color', name: 'roads', color: '#ff0000' },
  ] };
  const bytes = new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n');
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } }, false, { layers: [{ name: 'roads_buffer', geojson }] });
  const existingSimilarLayer = { filename: 'roads_buffer', _rawName: 'roads_buffer' };
  const panelLayers = [existingSimilarLayer];
  const colorChanges = [];
  h.window.GIS.layers.getLayers = () => panelLayers;
  h.window.GIS.layers.addLayer = layer => panelLayers.push(layer);
  h.window.GIS.layers.renderList = () => {};
  h.window.GIS.map.loadGeoJSON = () => {};
  h.window.GIS.map.setLayerColor = (...args) => colorChanges.push(args);
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('给 roads 图层改为红色');

  assert.equal(panelLayers.length, 1, 'a prefix match must not attach a second roads_buffer layer');
  assert.equal(panelLayers[0], existingSimilarLayer, 'the existing similarly named layer must remain untouched');
  assert.equal(colorChanges.length, 0, 'the operation must not be applied to the similarly named layer');
  assert.ok(h.createdElements.some(element => String(element._rawText || '').includes('roads') &&
    String(element._rawText || '').includes('可能未应用')));
});

test('a color operation that cannot reach the rendered layer leaves panel state unchanged and warns', async () => {
  const event = { type: 'done', response: '已设置颜色', layers: [], layer_ops: [
    { action: 'set_color', name: 'roads', color: '#ff0000' },
  ] };
  const bytes = new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n');
  let reads = 0;
  const h = createChatHarness({
    ok: true,
    body: { getReader() { return { read() {
      return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
    } }; } },
  });
  const target = { layer_id: 'roads-id', filename: 'roads', _rawName: 'roads', color: '#000000' };
  let renders = 0;
  h.window.GIS.layers.getLayers = () => [target];
  h.window.GIS.layers.renderList = () => { renders++; };
  h.window.GIS.map.setLayerColor = () => false;
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('把 roads 改成红色');

  assert.equal(target.color, '#000000');
  assert.equal(renders, 0);
  assert.ok(h.createdElements.some(element => String(element._rawText || '').includes('地图未能应用图层颜色')));
});

test('streamed fits retry after final layers load before execution cards finish', async () => {
  const op = { action: 'fit', name: 'demo', _stream_id: 'op-1', _step_id: 'map-step' };
  const geojson = { type: 'FeatureCollection', features: [] };
  const events = [
    { type: 'tool_start', name: 'focus_map', tool_call_id: 'map-1', step_id: 'map-step', map_ops_pending: 1 },
    { type: 'tool_end', name: 'focus_map', tool_call_id: 'map-1', step_id: 'map-step', output: '已请求定位' },
    { type: 'layer_ops_delta', step_id: 'map-step', layer_ops: [op] },
    { type: 'done', response: '已加载图层并定位', layers: [{ name: 'demo', geojson }], layer_ops: [op] },
  ];
  const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
  let readCount = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(readCount++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } }, true);
  const layers = [];
  let fits = 0;
  h.window.GIS.layers.getLayers = () => layers;
  h.window.GIS.state = { addLayer(layer) { layers.push(layer); }, getLayers: () => layers };
  h.window.GIS.map.fitLayer = name => { fits++; return layers.some(layer => layer.name === name); };
  h.window.GIS.chat.init();
  await h.window.GIS.chat.send('加载并定位 demo');
  const card = h.executionRows[0].children[0].children[0];
  assert.equal(fits, 1);
  assert.match(card.className, /ai-step-success/);
});

test('geospatial QA warnings escape layer names and messages before system HTML rendering', () => {
  const h = createChatHarness(null);
  const messages = [];
  h.window.GIS.chat.addMessage = (message, type) => messages.push({ message, type });
  h.window.GIS.chat.applyToolResult({ qa_warnings: [{
    layer: '<img src=x onerror=alert(1)>',
    warning: 'invalid geometry <svg onload=alert(2)> & check',
  }] });

  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, 'system');
  assert.ok(messages[0].message.includes('[&lt;img src=x onerror=alert(1)&gt;]'), messages[0].message);
  assert.ok(messages[0].message.includes('invalid geometry &lt;svg onload=alert(2)&gt; &amp; check'), messages[0].message);
  assert.doesNotMatch(messages[0].message, /<img\b|<svg onload=/i);
});

for (const cancel of [false, true]) test(`choice ${cancel ? 'cancellation' : 'submission'} reaches the backend and resolves its waiting card`, async () => {
  const events = [
    { type: 'tool_start', tool_call_id: 'choice', step_id: 'choice', name: 'ask_user_choice' },
    { type: 'tool_end', tool_call_id: 'choice', step_id: 'choice', name: 'ask_user_choice', output: '请选择' },
    { type: 'waiting_choice', step_id: 'choice' },
    { type: 'done', response: '请选择方案', layers: [],
      confirm_pending: { action: 'choose_option', options: [{ label: '方案 A' }] } },
  ];
  const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } }, true);
  h.window.GIS.utils = { escapeHtml: text => String(text) };
  h.window.GIS.chat.init();
  await h.window.GIS.chat.send('选择方案');
  const card = h.executionRows[0].children[0].children[0];
  assert.match(card.className, /ai-step-waiting/);
  const sent = [];
  h.window.GIS.chat.sendMessage = message => sent.push(message);
  const bar = h.createdElements.find(el => el.className === 'pending-action-bar');
  const button = cancel ? bar.children.find(el => el.textContent === '取消')
    : bar.children.find(el => el.tagName !== 'span' && typeof el.onclick === 'function' && el.textContent !== '取消');
  button.onclick();
  assert.deepEqual(sent, [cancel ? '取消' : '方案 A']);
  assert.equal(bar.removed, true);
  assert.match(card.className, cancel ? /ai-step-cancelled/ : /ai-step-success/);
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

test('chat surfaces SSE recovery notes in the current language as safe system pills', async () => {
  const events = [
    { type: 'note', message: '服务端临时故障已自动重试成功。' },
    { type: 'note', message: '<img src=x onerror=alert(1)>' },
    { type: 'done', response: '已完成', layers: [] },
  ];
  const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } });
  const notes = [];
  h.window.GIS.i18n = { isEnglish() { return true; } };
  h.window.GIS.chat.addMessage = (message, type, options) => notes.push({ message, type, options });

  await h.window.GIS.chat.send('执行分析');

  assert.equal(notes.length, 2);
  assert.equal(notes[0].message, 'A temporary server issue was recovered by retrying.');
  assert.equal(notes[0].type, 'system');
  assert.equal(notes[0].options.pill, true);
  assert.equal(notes[1].message, '&lt;img src=x onerror=alert(1)&gt;');
});

test('agent timeout marks the task failed and execution cards interrupted', async () => {
  const events = [
    { type: 'tool_start', tool_call_id: 'slow-call', step_id: 'slow-step', name: 'execute_python' },
    { type: 'done', response: '等待时限已到；后台调用仍可能继续', layers: [], execution_status: 'timeout' },
  ];
  const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } }, true);
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('执行一个耗时分析');

  assert.equal(h.tasks[0].status, 'failed');
  assert.match(h.tasks[0].error, /后台调用可能仍在执行/);
  const card = h.executionRows[0].children[0].children[0];
  assert.match(card.className, /ai-step-interrupted/);
  assert.equal(h.window._aiRunning, false);
});

test('unresolved failed GIS steps mark the task as partially completed', async () => {
  const events = [
    { type: 'tool_start', tool_call_id: 'failed-call', step_id: 'failed-step', name: 'buffer' },
    { type: 'tool_end', tool_call_id: 'failed-call', step_id: 'failed-step', name: 'buffer',
      output: '{"success":false,"error":"无效距离"}', status: 'error', is_error: true, error_message: '无效距离' },
    { type: 'done', response: '缓冲分析未完成：距离无效。', layers: [], execution_status: 'success' },
  ];
  const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } }, true);
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('对图层做缓冲分析');

  assert.equal(h.tasks[0].status, 'partial');
  const card = h.executionRows[0].children[0].children[0];
  assert.match(card.className, /ai-step-failed/);
});

test('a streamed error after tool start is surfaced without falling back to a second AI request', async () => {
  const events = [
    { type: 'tool_start', tool_call_id: 'partial-call', step_id: 'partial-step', name: 'export_layer' },
    { type: 'error', message: '工具执行后模型连接中断' },
  ];
  const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
  let reads = 0;
  let fallbackCalls = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } }, true);
  h.window.GIS.api.chat = async () => { fallbackCalls++; return { response: '不应执行第二次请求' }; };
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('导出分析结果');

  assert.equal(fallbackCalls, 0);
  assert.equal(h.tasks[0].status, 'failed');
  const card = h.executionRows[0].children[0].children[0];
  assert.match(card.className, /ai-step-interrupted/);
  assert.equal(h.window._aiRunning, false);
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
  const layer = { layer_id: 'layer-1', filename: 'registered-name', _rawName: 'registered-name', _registeredName: 'registered-name',
    _registrationTokens: { 'registered-name': 'current-version' } };
  const renames = [];
  harness.window.GIS.layers.getLayers = () => [layer];
  harness.window.GIS.layers.renderList = () => {};
  harness.window.GIS.state = { renameLayer(id, name) { renames.push([id, name]); } };
  harness.window.GIS.map.renameLayer = (oldName, newName) => renames.push([oldName, newName]);

  await harness.window.GIS.chat.send('重命名这个图层');

  assert.equal(layer.filename, 'renamed-name');
  assert.equal(layer._rawName, 'renamed-name');
  assert.equal(layer._registeredName, 'renamed-name');
  assert.equal(layer._registrationTokens['renamed-name'], 'current-version');
  assert.equal(layer._registrationTokens['registered-name'], undefined);
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
