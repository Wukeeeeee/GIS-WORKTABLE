const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function createHarness() {
  const elements = new Map();
  const getElementById = id => {
    if (!elements.has(id)) elements.set(id, { value: '', checked: false, style: {}, innerHTML: '', textContent: '' });
    return elements.get(id);
  };
  const requests = [];
  const window = {
    addEventListener() {},
    GIS: {
      api: {
        geosourceSearch(params) {
          return new Promise((resolve, reject) => requests.push({ params, resolve, reject }));
        },
      },
      utils: { escapeHtml: value => String(value) },
    },
  };
  const document = {
    readyState: 'loading',
    getElementById,
    addEventListener() {},
    querySelector() { return null; },
  };
  const sourcePath = path.resolve(__dirname, '../js/geosource.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, console: { warn() {} }, Promise, Set, Map, Math, Date, Array, Object, String, Number,
  }, { filename: sourcePath });
  return { window, requests };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

test('failed next-page search can be retried from the still displayed page', async () => {
  const { window, requests } = createHarness();

  window.GIS.geosource.doSearch(1);
  requests[0].resolve({ results: [], total: 30, total_pages: 3, page: 1 });
  await flushPromises();

  window.GIS.geosource.goToPage(2);
  assert.equal(requests.length, 2);
  requests[1].reject(new Error('temporary network failure'));
  await flushPromises();

  window.GIS.geosource.goToPage(2);
  assert.equal(requests.length, 3, 'page 2 should be requested again after the failed attempt');
  assert.equal(requests[2].params.page, 2);
});
