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
