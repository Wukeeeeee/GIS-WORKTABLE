const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function loadApi({ triggerTimeout = false, triggerStatusTimeout = false, fetchImpl = null } = {}) {
  const window = { location: { origin: 'http://127.0.0.1', protocol: 'http:' }, GIS: {} };
  const context = {
    window,
    document: { createElement() { return { set textContent(value) { this.innerHTML = value; } }; }, body: { contains() { return false; } } },
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
    fetch(url, options) {
      if (fetchImpl) return fetchImpl(url, options);
      return new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
      });
    },
    setTimeout(callback, delay) {
      if ((triggerTimeout && delay === 10 * 60 * 1000)
          || (triggerStatusTimeout && delay === 5000)) queueMicrotask(callback);
      return 1;
    },
    clearTimeout() {},
    URL,
    Blob,
  };
  const sourcePath = path.resolve(__dirname, '../js/api.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return window.GIS.api;
}

test('upload timeout aborts the request and reports a recoverable timeout', async () => {
  const api = loadApi({ triggerTimeout: true });

  await assert.rejects(
    api.upload({ name: 'large.geojson' }, new AbortController().signal, 'timeout-request-1'),
    error => error.code === 'UPLOAD_TIMEOUT',
  );
});

test('user cancellation remains distinct from an upload timeout', async () => {
  const api = loadApi();
  const caller = new AbortController();
  const pending = api.upload({ name: 'cancel.geojson' }, caller.signal, 'cancel-request-1');
  caller.abort();

  await assert.rejects(pending, error => error.name === 'AbortError' && typeof error.code !== 'string');
});

test('upload status checks have a bounded timeout during recovery', async () => {
  const api = loadApi({ triggerStatusTimeout: true });

  await assert.rejects(
    api.getUploadStatus('status-request-1', new AbortController().signal),
    error => error.code === 'UPLOAD_STATUS_TIMEOUT',
  );
});

test('upload cancellation notifies the server with a keepalive request', async () => {
  const calls = [];
  const api = loadApi({ fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ status: 'cancelling' }) };
  } });

  const result = await api.cancelUpload('cancel-request-1');

  assert.deepEqual(result, { status: 'cancelling' });
  assert.equal(calls[0].url, 'http://127.0.0.1/api/upload/cancel/cancel-request-1');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.keepalive, true);
});
