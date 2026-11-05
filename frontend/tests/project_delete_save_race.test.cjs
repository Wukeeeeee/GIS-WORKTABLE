const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test('deleting the current project waits for saves and invalidates queued autosaves', async () => {
  const saveRequest = deferred();
  const deleteRequest = deferred();
  const calls = [];
  let deleteClick;
  const item = {
    parentNode: null,
    addEventListener(type, handler) { if (type === 'click') deleteClick = handler; },
    getAttribute(name) { return name === 'data-id' ? 'project-1' : null; },
  };
  const list = { innerHTML: '', querySelectorAll() { return [item]; } };
  const capsule = { textContent: 'Current project' };
  const window = { GIS: {
    api: {
      listProjects() { return Promise.resolve({ projects: [
        { id: 'project-1', name: 'Current project', updatedAt: '2000-01-01', layerCount: 0, messageCount: 0 },
      ] }); },
      autoSaveProject() { calls.push('save'); return saveRequest.promise; },
      deleteProject(id) { calls.push(`delete:${id}`); return deleteRequest.promise; },
    },
    utils: { escapeHtml(value) { return String(value); } },
    layers: { getLayers() { return []; }, getGroupState() { return []; }, waitForRegistrySync() { return Promise.resolve([]); }, clearAll() {} },
    chat: { clear() {}, addMessage() {} },
    map: { resetView() {} },
  } };
  const document = {
    getElementById(id) {
      if (id === 'projectHistoryList') return list;
      if (id === 'workspaceCurrentProjectName') return capsule;
      if (id === 'chatMessages' || id === 'chatHistory') return { style: {} };
      return null;
    },
  };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
    confirm: () => true,
    console: { warn() {} },
  }, { filename: sourcePath });
  const project = window.GIS.project;
  project.setCurrentProjectId('project-1');

  const firstSave = project.autoSave();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['save']);

  project.showHistory();
  await new Promise(resolve => setImmediate(resolve));
  deleteClick({ target: { closest(selector) {
    return selector === '.history-action-btn' ? { getAttribute: () => 'delete' } : null;
  } } });
  const saveAfterDeleteRequest = project.autoSave();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['save'], 'delete must wait behind the already-running save');

  saveRequest.resolve({ id: 'project-1' });
  await firstSave;
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['save', 'delete:project-1']);

  deleteRequest.resolve({});
  await new Promise(resolve => setImmediate(resolve));
  await saveAfterDeleteRequest;
  assert.deepEqual(calls, ['save', 'delete:project-1']);
  assert.equal(project.getCurrentProjectId(), null);
});

test('deleting all projects waits for saves and clears the active project', async () => {
  const saveRequest = deferred();
  const deleteRequest = deferred();
  const calls = [];
  let clearClick;
  const clearButton = { addEventListener(type, handler) { if (type === 'click') clearClick = handler; } };
  const window = { GIS: {
    api: {
      listProjects() { return Promise.resolve({ projects: [] }); },
      autoSaveProject() { calls.push('save'); return saveRequest.promise; },
      deleteAllProjects() { calls.push('delete-all'); return deleteRequest.promise; },
    },
    layers: { getLayers() { return []; }, getGroupState() { return []; }, waitForRegistrySync() { return Promise.resolve([]); }, clearAll() {} },
    chat: { clear() {}, addMessage() {} },
    map: { resetView() {} },
  } };
  const document = {
    getElementById(id) {
      if (id === 'historyClearAllBtn') return clearButton;
      return null;
    },
  };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
    confirm: () => true,
    console: { warn() {} },
  }, { filename: sourcePath });
  const project = window.GIS.project;
  project.setCurrentProjectId('project-1');
  const firstSave = project.autoSave();
  await new Promise(resolve => setImmediate(resolve));
  project.init();
  clearClick();
  const saveAfterDeleteRequest = project.autoSave();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['save']);

  saveRequest.resolve({ id: 'project-1' });
  await firstSave;
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['save', 'delete-all']);
  deleteRequest.resolve({});
  await new Promise(resolve => setImmediate(resolve));
  await saveAfterDeleteRequest;
  assert.deepEqual(calls, ['save', 'delete-all']);
  assert.equal(project.getCurrentProjectId(), null);
});

test('cancelling single project deletion does not issue DELETE, cancel active task, or clear project', async () => {
  let deleteClick;
  let itemRemoved = false;
  const calls = [];
  const item = {
    parentNode: { removeChild() { itemRemoved = true; } },
    remove() { itemRemoved = true; },
    addEventListener(type, handler) { if (type === 'click') deleteClick = handler; },
    getAttribute(name) { return name === 'data-id' ? 'project-1' : null; },
  };
  const list = { innerHTML: '', querySelectorAll() { return [item]; } };
  let chatCancelCalled = false;
  const window = { GIS: {
    api: {
      listProjects() { return Promise.resolve({ projects: [
        { id: 'project-1', name: 'Current project', updatedAt: '2000-01-01', layerCount: 0, messageCount: 0 },
      ] }); },
      deleteProject(id) { calls.push(`delete:${id}`); return Promise.resolve({}); },
    },
    utils: { escapeHtml(value) { return String(value); } },
    layers: { getLayers() { return []; }, getGroupState() { return []; }, waitForRegistrySync() { return Promise.resolve([]); }, clearAll() {} },
    chat: {
      cancelActiveRequest() { chatCancelCalled = true; return Promise.resolve(true); },
      clear() {},
      addMessage() {},
    },
    map: { resetView() {} },
  } };
  const document = {
    getElementById(id) {
      if (id === 'projectHistoryList') return list;
      if (id === 'chatMessages' || id === 'chatHistory') return { style: {} };
      return null;
    },
  };
  let confirmPrompt = null;
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
    confirm: (msg) => { confirmPrompt = msg; return false; },
    console: { warn() {} },
  }, { filename: sourcePath });
  const project = window.GIS.project;
  project.setCurrentProjectId('project-1');

  project.showHistory();
  await new Promise(resolve => setImmediate(resolve));
  deleteClick({ target: { closest(selector) {
    return selector === '.history-action-btn' ? { getAttribute: () => 'delete' } : null;
  } } });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(confirmPrompt, '确定删除此工程？此操作不可恢复。');
  assert.equal(calls.length, 0, 'must not issue DELETE when confirmation cancelled');
  assert.equal(chatCancelCalled, false, 'must not cancel active chat request when confirmation cancelled');
  assert.equal(itemRemoved, false, 'must not remove list item when confirmation cancelled');
  assert.equal(project.getCurrentProjectId(), 'project-1', 'must not clear or modify current project id');
});

test('cancelling single project deletion via workspace.confirmModal leaves state intact', async () => {
  let deleteClick;
  let itemRemoved = false;
  const calls = [];
  const item = {
    parentNode: { removeChild() { itemRemoved = true; } },
    remove() { itemRemoved = true; },
    addEventListener(type, handler) { if (type === 'click') deleteClick = handler; },
    getAttribute(name) { return name === 'data-id' ? 'project-1' : null; },
  };
  const list = { innerHTML: '', querySelectorAll() { return [item]; } };
  let chatCancelCalled = false;
  let modalTitle = null;
  const window = { GIS: {
    workspace: {
      confirmModal(title, desc, onConfirm, isDanger) {
        modalTitle = title;
        // User dismisses modal without calling onConfirm
      },
    },
    api: {
      listProjects() { return Promise.resolve({ projects: [
        { id: 'project-1', name: 'Current project', updatedAt: '2000-01-01', layerCount: 0, messageCount: 0 },
      ] }); },
      deleteProject(id) { calls.push(`delete:${id}`); return Promise.resolve({}); },
    },
    utils: { escapeHtml(value) { return String(value); } },
    layers: { getLayers() { return []; }, getGroupState() { return []; }, waitForRegistrySync() { return Promise.resolve([]); }, clearAll() {} },
    chat: {
      cancelActiveRequest() { chatCancelCalled = true; return Promise.resolve(true); },
      clear() {},
      addMessage() {},
    },
    map: { resetView() {} },
  } };
  const document = {
    getElementById(id) {
      if (id === 'projectHistoryList') return list;
      if (id === 'chatMessages' || id === 'chatHistory') return { style: {} };
      return null;
    },
  };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
    confirm: () => true,
    console: { warn() {} },
  }, { filename: sourcePath });
  const project = window.GIS.project;
  project.setCurrentProjectId('project-1');

  project.showHistory();
  await new Promise(resolve => setImmediate(resolve));
  deleteClick({ target: { closest(selector) {
    return selector === '.history-action-btn' ? { getAttribute: () => 'delete' } : null;
  } } });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(modalTitle, '删除工程');
  assert.equal(calls.length, 0);
  assert.equal(chatCancelCalled, false);
  assert.equal(itemRemoved, false);
  assert.equal(project.getCurrentProjectId(), 'project-1');
});

test('confirming single project deletion via workspace.confirmModal schedules deletion and cleans up', async () => {
  let deleteClick;
  let itemRemoved = false;
  const calls = [];
  const item = {
    parentNode: { removeChild() { itemRemoved = true; } },
    remove() { itemRemoved = true; },
    addEventListener(type, handler) { if (type === 'click') deleteClick = handler; },
    getAttribute(name) { return name === 'data-id' ? 'project-1' : null; },
  };
  const list = { innerHTML: '', querySelectorAll() { return [item]; } };
  let chatCancelCalled = false;
  const window = { GIS: {
    workspace: {
      confirmModal(title, desc, onConfirm, isDanger) {
        assert.equal(isDanger, true);
        onConfirm();
      },
    },
    api: {
      listProjects() { return Promise.resolve({ projects: [
        { id: 'project-1', name: 'Current project', updatedAt: '2000-01-01', layerCount: 0, messageCount: 0 },
      ] }); },
      deleteProject(id) { calls.push(`delete:${id}`); return Promise.resolve({}); },
    },
    utils: { escapeHtml(value) { return String(value); } },
    layers: { getLayers() { return []; }, getGroupState() { return []; }, waitForRegistrySync() { return Promise.resolve([]); }, clearAll() {} },
    chat: {
      cancelActiveRequest() { chatCancelCalled = true; return Promise.resolve(true); },
      clear() {},
      addMessage() {},
    },
    map: { resetView() {} },
  } };
  const document = {
    getElementById(id) {
      if (id === 'projectHistoryList') return list;
      if (id === 'chatMessages' || id === 'chatHistory') return { style: {} };
      return null;
    },
  };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
    confirm: () => true,
    console: { warn() {} },
  }, { filename: sourcePath });
  const project = window.GIS.project;
  project.setCurrentProjectId('project-1');

  project.showHistory();
  await new Promise(resolve => setImmediate(resolve));
  deleteClick({ target: { closest(selector) {
    return selector === '.history-action-btn' ? { getAttribute: () => 'delete' } : null;
  } } });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(chatCancelCalled, true, 'must cancel active chat when confirmed');
  assert.deepEqual(calls, ['delete:project-1'], 'must issue DELETE after confirmation');
  assert.equal(itemRemoved, true, 'must remove list item after deletion succeeds');
  assert.equal(project.getCurrentProjectId(), null, 'must clear active project state');
});

test('absence of confirmation API fails closed and does not delete or alter state', async () => {
  let deleteClick;
  let itemRemoved = false;
  const calls = [];
  const messages = [];
  const item = {
    parentNode: { removeChild() { itemRemoved = true; } },
    remove() { itemRemoved = true; },
    addEventListener(type, handler) { if (type === 'click') deleteClick = handler; },
    getAttribute(name) { return name === 'data-id' ? 'project-1' : null; },
  };
  const list = { innerHTML: '', querySelectorAll() { return [item]; } };
  let chatCancelCalled = false;
  const window = { GIS: {
    api: {
      listProjects() { return Promise.resolve({ projects: [
        { id: 'project-1', name: 'Current project', updatedAt: '2000-01-01', layerCount: 0, messageCount: 0 },
      ] }); },
      deleteProject(id) { calls.push(`delete:${id}`); return Promise.resolve({}); },
    },
    utils: { escapeHtml(value) { return String(value); } },
    layers: { getLayers() { return []; }, getGroupState() { return []; }, waitForRegistrySync() { return Promise.resolve([]); }, clearAll() {} },
    chat: {
      cancelActiveRequest() { chatCancelCalled = true; return Promise.resolve(true); },
      clear() {},
      addMessage(msg, type) { messages.push({ msg, type }); },
    },
    map: { resetView() {} },
  } };
  const document = {
    getElementById(id) {
      if (id === 'projectHistoryList') return list;
      if (id === 'chatMessages' || id === 'chatHistory') return { style: {} };
      return null;
    },
  };
  const sourcePath = path.resolve(__dirname, '../js/project.js');
  // Neither window.GIS.workspace.confirmModal, window.confirm, nor global confirm is provided
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Promise, Date, Math, Number, String, Object, Array, JSON, Set,
    console: { warn() {} },
  }, { filename: sourcePath });
  const project = window.GIS.project;
  project.setCurrentProjectId('project-1');

  project.showHistory();
  await new Promise(resolve => setImmediate(resolve));
  deleteClick({ target: { closest(selector) {
    return selector === '.history-action-btn' ? { getAttribute: () => 'delete' } : null;
  } } });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(calls.length, 0, 'must not issue DELETE when no confirmation API exists');
  assert.equal(chatCancelCalled, false, 'must not cancel active chat');
  assert.equal(itemRemoved, false, 'must not remove item');
  assert.equal(project.getCurrentProjectId(), 'project-1', 'must preserve project ID');
  assert.ok(messages.some(m => m.msg.includes('无法调起删除确认对话框')), 'must notify user with actionable message');
});
