const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function loadApi(fetchImpl, { sessionId = 'test-session', projectId = 'proj-123' } = {}) {
  const window = {
    location: { origin: 'http://127.0.0.1:8000', protocol: 'http:' },
    GIS: {
      project: {
        getCurrentSessionId: () => sessionId,
        getCurrentProjectId: () => projectId,
      },
    },
  };
  const context = {
    window,
    document: {
      createElement() {
        return { set textContent(value) { this.innerHTML = value; } };
      },
      body: { contains() { return false; } },
      querySelectorAll() { return []; },
    },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    FormData: class { append() {} },
    AbortController,
    DOMException,
    Promise,
    Map,
    Set,
    Array,
    Object,
    String,
    Number,
    JSON,
    Date,
    Math,
    encodeURIComponent,
    fetch: fetchImpl,
    setTimeout,
    clearTimeout,
    URL,
    Blob,
  };
  const sourcePath = path.resolve(__dirname, '../js/api.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return window.GIS.api;
}

test('saveProject preserves detail when backend returns HTTP 400 capacity error', async () => {
  const capacityMessage = '工程数量已达到上限（最多 30 个）；请先删除不需要的工程后再保存';
  let capturedRequest = null;
  const mockFetch = async (url, options) => {
    capturedRequest = { url, options };
    return {
      ok: false,
      status: 400,
      json: async () => ({ detail: capacityMessage }),
    };
  };

  const api = loadApi(mockFetch);
  const payload = { name: '新工程', layers: [], messages: [] };

  await assert.rejects(
    api.saveProject(payload),
    (err) => {
      assert.strictEqual(err.name, 'Error');
      assert.match(err.message, /保存工程失败: 工程数量已达到上限（最多 30 个）；请先删除不需要的工程后再保存/);
      assert.ok(err.message.includes(capacityMessage));
      return true;
    },
  );

  assert.ok(capturedRequest);
  assert.strictEqual(capturedRequest.url, 'http://127.0.0.1:8000/api/projects');
  assert.strictEqual(capturedRequest.options.method, 'POST');
  assert.strictEqual(capturedRequest.options.headers['Content-Type'], 'application/json');
  assert.deepStrictEqual(JSON.parse(capturedRequest.options.body), payload);
});

test('autoSaveProject preserves detail when backend returns HTTP 400 capacity error', async () => {
  const capacityMessage = '工程数量已达到上限（最多 30 个）；请先删除不需要的工程后再保存';
  let capturedRequest = null;
  const mockFetch = async (url, options) => {
    capturedRequest = { url, options };
    return {
      ok: false,
      status: 400,
      json: async () => ({ detail: capacityMessage }),
    };
  };

  const api = loadApi(mockFetch, { sessionId: 'auto-session', projectId: 'auto-pid' });
  const layerGroups = [{ name: 'Group1' }];
  const layerAssignments = [{ layer_id: 'l1', group_name: 'Group1' }];

  await assert.rejects(
    api.autoSaveProject(null, null, layerGroups, layerAssignments),
    (err) => {
      assert.strictEqual(err.name, 'Error');
      assert.match(err.message, /自动保存失败: 工程数量已达到上限（最多 30 个）；请先删除不需要的工程后再保存/);
      assert.ok(err.message.includes(capacityMessage));
      return true;
    },
  );

  assert.ok(capturedRequest);
  assert.ok(capturedRequest.url.includes('/api/projects/auto-save?session_id=auto-session&project_id=auto-pid'));
  assert.strictEqual(capturedRequest.options.method, 'POST');
  assert.deepStrictEqual(JSON.parse(capturedRequest.options.body), {
    layer_groups: layerGroups,
    layer_assignments: layerAssignments,
  });
});

test('saveProject falls back to HTTP status when response lacks detail', async () => {
  const mockFetch = async () => ({
    ok: false,
    status: 400,
    json: async () => ({}),
  });

  const api = loadApi(mockFetch);

  await assert.rejects(
    api.saveProject({ name: '测试' }),
    (err) => {
      assert.strictEqual(err.message, '保存工程失败: 400');
      return true;
    },
  );
});

test('saveProject falls back to HTTP status when response json parsing fails', async () => {
  const mockFetch = async () => ({
    ok: false,
    status: 500,
    json: async () => { throw new Error('Invalid JSON'); },
  });

  const api = loadApi(mockFetch);

  await assert.rejects(
    api.saveProject({ name: '测试' }),
    (err) => {
      assert.strictEqual(err.message, '保存工程失败: 500');
      return true;
    },
  );
});

test('autoSaveProject falls back to HTTP status when response lacks detail', async () => {
  const mockFetch = async () => ({
    ok: false,
    status: 400,
    json: async () => ({ detail: '' }),
  });

  const api = loadApi(mockFetch);

  await assert.rejects(
    api.autoSaveProject('s1', 'p1'),
    (err) => {
      assert.strictEqual(err.message, '自动保存失败: 400');
      return true;
    },
  );
});

test('saveProject and autoSaveProject return parsed json on success', async () => {
  const saveResult = { id: 'proj-new', name: '已保存' };
  const autoSaveResult = { id: 'proj-auto', note: '自动保存成功' };

  const mockFetch = async (url) => {
    if (url.includes('/auto-save')) {
      return { ok: true, status: 200, json: async () => autoSaveResult };
    }
    return { ok: true, status: 200, json: async () => saveResult };
  };

  const api = loadApi(mockFetch);

  const res1 = await api.saveProject({ name: '已保存' });
  assert.deepStrictEqual(res1, saveResult);

  const res2 = await api.autoSaveProject('s1', 'p1');
  assert.deepStrictEqual(res2, autoSaveResult);
});
