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
  const cancelCalls = [];
  const exportCalls = [];
  const workspaceResetCalls = [];
  const executionRows = [];
  const createdElements = [];
  const api = {
    BASE_URL: 'http://127.0.0.1:8000',
    resolveProvider(id) { return { id, name: id, api_key: 'test-key' }; },
    getAmapKey() { return ''; },
    getActiveProjectContext() { workspaceResetCalls.push(['read-context']); return Promise.resolve({active_project_id: 'project-a'}); },
    resetActiveProjectContext(id) { workspaceResetCalls.push(['reset-context', id]); return Promise.resolve({success: true}); },
    clearMemory() { return Promise.resolve({success: true}); },
  };
  let activeRegistryProjectId = 'project-a';
  const window = { GIS: {
    api,
    workspace: { toggleAI() {} },
    project: {
      getCurrentSessionId() { return 'session-a'; },
      getCurrentProjectId() { return 'project-a'; },
      getActiveRegistryProjectId() { return activeRegistryProjectId; },
      resetSession() { activeRegistryProjectId = null; return 'session-b'; },
    },
    map: {
      exportMap(format) { exportCalls.push({ action: 'png', format }); },
      exportPdf(title) { exportCalls.push({ action: 'pdf', title }); },
    },
    layers: { getLayers() { return []; }, clearAll() { workspaceResetCalls.push(['clear-ui']); } },
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
      insertBefore(child) { this.children.unshift(child); },
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
    if (url.includes('/api/cancel')) { cancelCalls.push(url); return Promise.resolve({ ok: true }); }
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
  return { window, context, tasks, streamCalls, cancelCalls, exportCalls, elements, getElement, executionRows, createdElements, workspaceResetCalls };
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

test('attached layer name, type, and count render as text instead of HTML', () => {
  const h = createChatHarness();
  h.window.GIS.chat.init();
  const name = '<img src=x onerror=alert(1)>';
  const type = '<svg onload=alert(2)>';
  const count = '<b>999</b>';
  h.window.GIS.chat.addMessage('analyze this', 'user', {
    attachLayer: { name, type, count },
  });

  const row = h.elements.get('chatMessages').children[0];
  const attachRow = row.children[1].children[1];
  assert.equal(attachRow.innerHTML, undefined);
  assert.equal(attachRow.children[1].textContent, name);
  assert.equal(attachRow.children[2].textContent, type + ' · ' + count + ' 要素');
});

test('starting a new chat resets backend GIS context before clearing the current workspace', async () => {
  const h = createChatHarness();
  await h.window.GIS.chat.clearSession();

  assert.deepEqual(h.workspaceResetCalls, [
    ['reset-context', 'project-a'],
    ['clear-ui'],
  ]);
  assert.equal(h.window.GIS.project.getActiveRegistryProjectId(), null);
});

test('starting a new chat reads the backend context after a frontend reload', async () => {
  const h = createChatHarness();
  h.window.GIS.project.getActiveRegistryProjectId = () => null;
  await h.window.GIS.chat.clearSession();

  assert.deepEqual(h.workspaceResetCalls, [
    ['read-context'],
    ['reset-context', 'project-a'],
    ['clear-ui'],
  ]);
});

test('a failed backend GIS context reset leaves the current workspace intact', async () => {
  const h = createChatHarness();
  h.window.GIS.api.resetActiveProjectContext = id => {
    h.workspaceResetCalls.push(['reset-context', id]);
    return Promise.reject(new Error('HTTP 409'));
  };
  const cleared = await h.window.GIS.chat.clearSession();

  assert.equal(cleared, false);
  assert.deepEqual(h.workspaceResetCalls, [['reset-context', 'project-a']]);
  assert.equal(h.window.GIS.project.getActiveRegistryProjectId(), 'project-a');
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
  assert.notEqual(harness.streamCalls[0].body.request_id, harness.streamCalls[1].body.request_id);
  assert.match(harness.cancelCalls[0], new RegExp('request_id=' + encodeURIComponent(harness.streamCalls[0].body.request_id)));
  assert.doesNotMatch(harness.cancelCalls[0], new RegExp('request_id=' + encodeURIComponent(harness.streamCalls[1].body.request_id)));
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

test('a late failure from a replaced chat request cannot reset the newer request UI', async () => {
  const harness = createChatHarness();
  harness.window.GIS.chat.init();
  let rejectFirstStream;
  let streamCount = 0;
  harness.context.fetch = (url, options) => {
    if (url.includes('/api/cancel')) return Promise.resolve({ ok: true });
    if (url.endsWith('/api/layers')) return Promise.resolve({ ok: true, json() { return Promise.resolve({ layers: [] }); } });
    if (url.endsWith('/api/chat/stream')) {
      streamCount += 1;
      if (streamCount === 1) return new Promise((_resolve, reject) => { rejectFirstStream = reject; });
      return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      }, { once: true }));
    }
    return Promise.resolve({ ok: true });
  };

  const first = harness.window.GIS.chat.send('第一条任务');
  await new Promise(resolve => setImmediate(resolve));
  const second = harness.window.GIS.chat.send('第二条任务');
  await new Promise(resolve => setImmediate(resolve));
  const input = harness.elements.get('chatInput');
  input.placeholder = '第二条任务正在运行';

  rejectFirstStream(new Error('late connection failure'));
  await first;

  assert.equal(input.placeholder, '第二条任务正在运行');
  assert.equal(harness.window._aiRunning, true);
  assert.equal(harness.elements.get('chatMessages').children.some(row => /late connection failure/.test(row._rawText || '')), false);
  harness.window._aiAbortController.abort('user-cancel');
  await second;
});

test('project switching cancellation aborts the active request and invalidates its generation', async () => {
  const harness = createChatHarness();
  const activeSend = harness.window.GIS.chat.send('切换工程前仍在运行的任务');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(harness.streamCalls.length, 1);
  const requestId = harness.streamCalls[0].body.request_id;
  const controller = harness.window._aiAbortController;

  const cancelled = harness.window.GIS.chat.cancelActiveRequest('切换工程，已取消当前任务');
  assert.equal(controller.signal.aborted, true);
  assert.equal(harness.window._aiRunning, false);
  assert.equal(harness.window._aiRequestId, null);
  assert.match(harness.cancelCalls[0], /session_id=session-a/);
  assert.match(harness.cancelCalls[0], new RegExp('request_id=' + encodeURIComponent(requestId)));
  assert.equal(harness.tasks[0].status, 'cancelled');
  assert.equal(await cancelled, true);
  await activeSend;
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

test('a protected response identifies its local GIS mode in the chat', async () => {
  const payload = 'data: ' + JSON.stringify({ type: 'done', response: '完成', layers: [], privacy_mode: true }) + '\n\n';
  let reads = 0;
  const bytes = new TextEncoder().encode(payload);
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } });
  h.window.GIS.chat.init();
  await h.window.GIS.chat.send('查看图层');
  const label = h.createdElements.find(element => element.className === 'chat-privacy-label');
  assert.ok(label);
  assert.equal(label.textContent, '敏感图层模式 · 本地 GIS 操作');
});

test('protected replies render restored names as text without loading model supplied images', async () => {
  const text = '![秘密设施](https://untrusted.example/image?name=秘密设施)';
  const payload = 'data: ' + JSON.stringify({ type: 'done', response: text, layers: [], privacy_mode: true }) + '\n\n';
  const bytes = new TextEncoder().encode(payload);
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } });
  h.window.GIS.chat.init();
  await h.window.GIS.chat.send('查看图层');
  const content = h.createdElements.find(element => element.textContent === text);
  assert.ok(content);
  assert.equal(content.innerHTML, undefined);
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

test('ordinary chat fallback keeps the same request ID and stop signal as the failed stream', async () => {
  const harness = createChatHarness({
    ok: false, status: 503, json: async () => ({ detail: 'stream unavailable' }),
  });
  let fallbackArgs;
  harness.window.GIS.api.chat = async (...args) => {
    fallbackArgs = args;
    return { response: 'fallback reply' };
  };

  await harness.window.GIS.chat.send('你好');

  assert.equal(fallbackArgs[5], harness.streamCalls[0].body.request_id);
  assert.equal(typeof fallbackArgs[5], 'string');
  assert.equal(fallbackArgs[6], harness.streamCalls[0].signal);
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

test('unavailable heatmap plugin does not register a phantom layer', async () => {
  const event = { type: 'done', response: '热力图已生成', layers: [], layer_ops: [], heatmap: {
    name: 'cities_heat', points: [[39, 116, 1]], options: { radius: 20 },
  } };
  const bytes = new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n');
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } });
  const addedLayers = [];
  h.window.GIS.map.loadHeatmap = () => null;
  h.window.GIS.layers.getLayers = () => addedLayers;
  h.window.GIS.layers.addLayer = layer => addedLayers.push(layer);
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('生成热力图');

  assert.deepEqual(addedLayers, []);
  assert.ok(h.getElement('chatMessages').children.some(row => /热力图.*无法显示/.test(row._rawText || '')));
});

test('manual heatmap result reports when the renderer is unavailable', () => {
  const h = createChatHarness();
  h.window.GIS.map.loadHeatmap = () => null;
  h.window.GIS.chat.init();

  h.window.GIS.chat.applyToolResult({ heatmap: {
    name: 'cities_heat', points: [[39, 116, 1]], options: { radius: 20 },
  } });

  assert.ok(h.getElement('chatMessages').children.some(row => /热力图.*无法显示/.test(row._rawText || '')));
});

test('COG preview result is persisted as a preview layer and does not claim pixel analysis', async () => {
  const op = { action: 'dem_result', name: 'cog_scene.png', layer_name: 'scene（COG 预览）',
    url: '/output/uploads/cog_scene.png', bounds: [100, 30, 101, 31], crs: 'EPSG:4326',
    label: 'COG 影像: scene', raster: {
      filename: 'cog_scene.png', url: '/output/uploads/cog_scene.png',
      bounds: [100, 30, 101, 31], width: 1024, height: 512,
      preview_width: 256, preview_height: 128, bands: 4, preview_only: true,
    } };
  const event = { type: 'done', response: 'COG 已加载', layers: [], layer_ops: [op] };
  const bytes = new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n');
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } });
  const overlays = [];
  const addedLayers = [];
  let autoSaves = 0;
  h.window.GIS.map.addImageOverlay = (...args) => overlays.push(args);
  h.window.GIS.layers.getLayers = () => addedLayers;
  h.window.GIS.layers.addLayer = (layer, skipRegister) => {
    assert.equal(skipRegister, true);
    addedLayers.push(layer);
  };
  h.window.GIS.project = { autoSave() { autoSaves++; } };
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('加载 COG');

  assert.deepEqual(overlays, [[op.url, op.bounds, op.name, op.layer_name]]);
  assert.equal(addedLayers[0].raster.preview_only, true);
  assert.equal(autoSaves, 1);
  assert.ok(h.createdElements.some(element => String(element._rawText || '').includes('像元分析需提供原始栅格文件')));
});

test('manual tool results preserve the backend registration name and deletion token', () => {
  const h = createChatHarness();
  const added = [];
  h.window.GIS.state = { addLayer(layer) { added.push(layer); return layer; } };
  const geojson = { type: 'FeatureCollection', features: [] };

  h.window.GIS.chat.applyToolResult({ layers: [{
    name: 'roads_buffer', registry_name: 'roads_buffer', registration_token: 'registered-version', geojson,
  }] });

  assert.equal(added.length, 1);
  assert.equal(added[0].registry_name, 'roads_buffer');
  assert.equal(added[0].registration_token, 'registered-version');
  assert.equal(added[0].name.startsWith('roads_buffer_'), true);
});

test('manual vector tool results schedule a project autosave', () => {
  const h = createChatHarness();
  let autosaves = 0;
  h.window.GIS.state = { addLayer(layer) { return layer; } };
  h.window.GIS.project.autoSave = () => { autosaves++; return Promise.resolve(); };

  h.window.GIS.chat.applyToolResult({ layers: [{
    name: 'roads_buffer', registry_name: 'roads_buffer', registration_token: 'registered-version',
    geojson: { type: 'FeatureCollection', features: [] },
  }] });

  assert.equal(autosaves, 1);
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

test('successful manual style operations update shared and panel state for project persistence', () => {
  const event = { type: 'done', response: '已更新样式', layers: [], layer_ops: [
    { action: 'set_color', name: 'roads', color: '#ff0000' },
    { action: 'set_style', name: 'roads', style: { weight: 5, fillOpacity: 0.2 } },
  ] };
  const h = createChatHarness();
  const panelLayers = [];
  h.window.GIS.layers.getLayers = () => panelLayers;
  h.window.GIS.layers.addLayer = layer => panelLayers.push(layer);
  h.window.GIS.layers.renderList = () => {};
  h.window.GIS.map.loadGeoJSON = () => {};
  const styleCalls = [];
  h.window.GIS.map.setLayerColor = (...args) => { styleCalls.push(['color', ...args]); return true; };
  h.window.GIS.map.setLayerStyle = (...args) => { styleCalls.push(['style', ...args]); return true; };
  let saves = 0;
  h.window.GIS.project.autoSave = () => { saves++; };
  h.context.GIS = h.window.GIS;
  vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../js/gis_state.js'), 'utf8'), h.context);
  const shared = h.window.GIS.state.addLayer({ layer_id: 'roads-id', name: 'roads',
    geojson: { type: 'FeatureCollection', features: [] }, style: { color: '#000000', fillColor: '#000000' } });
  h.window.GIS.chat.applyToolResult({ layer_ops: event.layer_ops });

  assert.equal(panelLayers.length, 1);
  assert.equal(panelLayers[0].layer_id, 'roads-id');
  assert.equal(styleCalls.length, 2);
  assert.equal(shared.style.color, '#ff0000');
  assert.equal(shared.style.weight, 5);
  assert.equal(panelLayers[0].style.color, '#ff0000');
  assert.equal(panelLayers[0].style.fillOpacity, 0.2);
  assert.equal(saves, 1);
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

test('same-name spatial tool output replaces the visible layer instead of creating a suffixed duplicate', async () => {
  const updatedGeoJSON = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { value: 2 }, geometry: { type: 'Point', coordinates: [121, 31] } },
  ] };
  const event = { type: 'done', response: '已更新 roads', layers: [{ name: 'roads', geojson: updatedGeoJSON }] };
  const bytes = new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n');
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } });
  const existing = { layer_id: 'roads-id', filename: 'roads', _registeredName: 'roads',
    _rawName: 'roads-map-name', style: { color: '#123456' }, geojson: { type: 'FeatureCollection', features: [] } };
  const panelLayers = [existing];
  const rendered = [];
  const syncs = [];
  let added = 0;
  h.window.GIS.layers.getLayers = () => panelLayers;
  h.window.GIS.layers.syncToolLayer = async () => true;
  h.window.GIS.layers.addLayer = () => { added++; };
  h.window.GIS.layers.syncLayerData = (id, data) => { syncs.push([id, data]); existing.geojson = data; return Promise.resolve(true); };
  h.window.GIS.layers.renderList = () => {};
  h.window.GIS.state = { addLayer() { added++; } };
  h.window.GIS.map.loadGeoJSON = (...args) => rendered.push(args);
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('更新 roads');

  assert.equal(panelLayers.length, 1);
  assert.equal(added, 0);
  assert.equal(syncs.length, 1);
  assert.equal(syncs[0][0], 'roads-id');
  assert.equal(JSON.stringify(syncs[0][1]), JSON.stringify(updatedGeoJSON));
  assert.equal(JSON.stringify(rendered[0][0]), JSON.stringify(updatedGeoJSON));
  assert.equal(rendered[0][1], 'roads-map-name');
  assert.equal(rendered[0][2], existing.style);
  assert.equal(rendered[0][3].fitBounds, false);
});

test('manual same-name tool output updates the existing panel layer instead of duplicating it', () => {
  const h = createChatHarness();
  const geojson = { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { value: 2 }, geometry: { type: 'Point', coordinates: [121, 31] } },
  ] };
  const existing = { layer_id: 'roads-id', filename: 'roads', _registeredName: 'roads', _rawName: 'roads-map',
    _registrationTokens: { roads: 'old-version' }, style: { color: '#123456' } };
  const panelLayers = [existing];
  const added = [];
  const syncs = [];
  const rendered = [];
  h.window.GIS.layers.getLayers = () => panelLayers;
  h.window.GIS.layers.syncLayerData = (id, data) => { syncs.push([id, data]); return Promise.resolve(true); };
  h.window.GIS.state = { addLayer(layer) { added.push(layer); } };
  h.window.GIS.map.loadGeoJSON = (...args) => rendered.push(args);

  h.window.GIS.chat.applyToolResult({ layers: [{
    name: 'roads', registry_name: 'roads', registration_token: 'new-version', geojson,
  }] });

  assert.equal(added.length, 0);
  assert.equal(panelLayers.length, 1);
  assert.deepEqual(syncs, [['roads-id', geojson]]);
  assert.equal(rendered[0][1], 'roads-map');
  assert.equal(rendered[0][2], existing.style);
  assert.equal(rendered[0][3].fitBounds, false);
  assert.equal(existing._registeredName, 'roads');
  assert.equal(existing._registrationTokens.roads, 'new-version');
});

test('new backend-registered vector results refresh the panel registration token through its sync queue', async () => {
  const geojson = { type: 'FeatureCollection', features: [] };
  const event = { type: 'done', response: '已生成 roads-buffer', layers: [{ name: 'roads-buffer', geojson }] };
  const bytes = new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n');
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } });
  let added = null;
  const syncs = [];
  h.window.GIS.state = { addLayer(record) { added = record; return { layer_id: record.layer_id }; } };
  h.window.GIS.layers.syncLayerData = (...args) => { syncs.push(args); return Promise.resolve(true); };
  h.window.GIS.layers.getLayers = () => [];
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('生成道路缓冲区');

  assert.equal(added.name, 'roads-buffer');
  assert.deepEqual(syncs, [[added.layer_id, geojson]]);
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

test('backend cancellation status is not shown as a successful task', async () => {
  const events = [
    { type: 'tool_start', tool_call_id: 'cancelled-call', step_id: 'cancelled-step', name: 'buffer' },
    { type: 'done', response: '用户已取消', layers: [], execution_status: 'cancelled' },
  ];
  const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
  let reads = 0;
  const h = createChatHarness({ ok: true, body: { getReader() { return { read() {
    return Promise.resolve(reads++ === 0 ? { done: false, value: bytes } : { done: true });
  } }; } } }, true);
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('取消缓冲分析');

  assert.equal(h.tasks[0].status, 'cancelled');
  const card = h.executionRows[0].children[0].children[0];
  assert.match(card.className, /ai-step-cancelled/);
});

test('non-stream cancellation response keeps the task cancelled after stream fallback', async () => {
  const h = createChatHarness({
    ok: false, status: 503,
    async json() { return { detail: 'stream unavailable' }; },
  }, true);
  h.window.GIS.api.chat = async () => ({
    response: '用户已取消', execution_status: 'cancelled', layers: [],
  });
  h.window.GIS.chat.init();

  await h.window.GIS.chat.send('执行分析');

  assert.equal(h.tasks[0].status, 'cancelled');
  assert.equal(h.tasks[0].error, '用户取消');
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
