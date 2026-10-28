const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

test('partial project deletion refreshes the list and reports failure without claiming success', async () => {
  const events = [];
  const button = {
    addEventListener(name, callback) {
      if (name === 'click') this.onClick = callback;
    },
  };
  const window = { GIS: {
    api: {
      deleteAllProjects: async () => ({ success: false, warning: '有 1 个工程未能删除，请稍后重试。' }),
      listProjects: async () => { events.push('refresh'); return { projects: [] }; },
    },
    chat: { addMessage(message) { events.push(message); } },
    toast: { warn(message) { events.push(`warning:${message}`); } },
  } };
  const document = { getElementById(id) { return id === 'historyClearAllBtn' ? button : null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
    confirm: () => true,
  }, { filename: sourcePath });

  window.GIS.project.init();
  button.onClick();
  await new Promise(resolve => setImmediate(resolve));

  assert.ok(events.includes('warning:有 1 个工程未能删除，请稍后重试。'));
  assert.ok(events.includes('refresh'));
  assert.equal(events.includes('已删除全部历史会话'), false);
});

test('partial project deletion preserves the current workspace when the follow-up list request fails', async () => {
  const button = {
    addEventListener(name, callback) {
      if (name === 'click') this.onClick = callback;
    },
  };
  let clearCount = 0;
  const window = { GIS: {
    api: {
      deleteAllProjects: async () => ({ success: false, warning: '有 1 个工程未能删除，请稍后重试。' }),
      listProjects: async () => { throw new Error('temporary list failure'); },
    },
    layers: { clearAll() { clearCount++; } },
    chat: { cancelActiveRequest() { return false; }, clear() {} },
    map: { resetView() {} },
    toast: { warn() {} },
  } };
  const document = {
    getElementById(id) { return id === 'historyClearAllBtn' ? button : null; },
  };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
    confirm: () => true,
  }, { filename: sourcePath });

  window.GIS.project.setCurrentProjectId('still-on-disk');
  window.GIS.project.init();
  button.onClick();
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(window.GIS.project.getCurrentProjectId(), 'still-on-disk');
  assert.equal(clearCount, 0);
});

test('partial project deletion preserves the workspace when the refreshed list is malformed', async () => {
  const button = { addEventListener(name, callback) { if (name === 'click') this.onClick = callback; } };
  let clearCount = 0;
  const window = { GIS: {
    api: {
      deleteAllProjects: async () => ({ success: false, warning: '部分删除失败' }),
      listProjects: async () => ({ projects: null }),
    },
    layers: { clearAll() { clearCount++; } },
    chat: { cancelActiveRequest() { return false; }, clear() {} },
    map: { resetView() {} },
    toast: { warn() {} },
  } };
  const document = { getElementById(id) { return id === 'historyClearAllBtn' ? button : null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
    confirm: () => true,
  }, { filename: sourcePath });

  window.GIS.project.setCurrentProjectId('possibly-still-on-disk');
  window.GIS.project.init();
  button.onClick();
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(window.GIS.project.getCurrentProjectId(), 'possibly-still-on-disk');
  assert.equal(clearCount, 0);
});

test('deleting all projects waits for an active chat cancellation acknowledgement', async () => {
  let resolveCancellation;
  const cancellation = new Promise(resolve => { resolveCancellation = resolve; });
  const events = [];
  let active = true;
  const button = {
    addEventListener(name, callback) {
      if (name === 'click') this.onClick = callback;
    },
  };
  const window = { GIS: {
    api: {
      deleteAllProjects: async () => { events.push('delete'); return { success: true }; },
      listProjects: async () => ({ projects: [] }),
    },
    chat: {
      cancelActiveRequest() {
        if (!active) return false;
        active = false;
        events.push('cancel');
        return cancellation;
      },
      clear() {},
      addMessage(message) { events.push(message); },
    },
    toast: { warn() {} },
  } };
  const document = { getElementById(id) { return id === 'historyClearAllBtn' ? button : null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
    confirm: () => true,
  }, { filename: sourcePath });

  window.GIS.project.init();
  button.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(events.join(','), 'cancel');
  resolveCancellation(true);
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(events[0], 'cancel');
  assert.equal(events[1], 'delete');
  assert.ok(events.includes('已删除全部历史会话'));
});

test('deleting all projects is blocked when active chat cancellation fails', async () => {
  let deleteCalls = 0;
  const messages = [];
  const button = {
    addEventListener(name, callback) {
      if (name === 'click') this.onClick = callback;
    },
  };
  const window = { GIS: {
    api: { deleteAllProjects: async () => { deleteCalls++; return { success: true }; } },
    chat: {
      cancelActiveRequest() { return Promise.resolve(false); },
      addMessage(message) { messages.push(message); },
    },
  } };
  const document = { getElementById(id) { return id === 'historyClearAllBtn' ? button : null; } };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON,
    confirm: () => true,
  }, { filename: sourcePath });

  window.GIS.project.init();
  button.onClick();
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(deleteCalls, 0);
  assert.ok(messages.some(message => message.includes('未删除历史工程')));
});
