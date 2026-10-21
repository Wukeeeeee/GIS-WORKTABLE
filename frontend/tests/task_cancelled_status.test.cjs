const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

test('cancelled tasks are visibly distinct and can be rerun', () => {
  const taskList = { innerHTML: '', addEventListener() {} };
  const document = {
    getElementById(id) { return id === 'historyList' ? taskList : null; },
  };
  const storage = new Map();
  const localStorage = {
    getItem(key) { return storage.get(key) || null; },
    setItem(key, value) { storage.set(key, value); },
  };
  const window = { GIS: { api: { resolveProvider() { return null; } } } };
  const sourcePath = path.resolve(__dirname, '../js/task.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, localStorage, Date, Math, JSON, String, Number, Array, Object,
    console: { warn() {} },
  }, { filename: sourcePath });

  window.GIS.task.init();
  const task = window.GIS.task.createTask('测试任务', 'test', []);
  window.GIS.task.updateTask(task.id, { status: 'cancelled', error: '用户取消' });

  assert.match(taskList.innerHTML, /task-status-cancelled/);
  assert.match(taskList.innerHTML, /已取消/);
  assert.match(taskList.innerHTML, /task-rerun/);
});

test('task history persistence retains the newest 20 unsaved tasks', () => {
  const storage = new Map();
  const localStorage = {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); },
  };
  const window = { GIS: { api: { resolveProvider() { return null; } } } };
  const sourcePath = path.resolve(__dirname, '../js/task.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document: { getElementById() { return null; } }, localStorage,
    Date, Math, JSON, String, Number, Array, Object, console: { warn() {} },
  }, { filename: sourcePath });

  for (let index = 1; index <= 25; index++) {
    window.GIS.task.createTask('任务 ' + index, 'test', []);
  }

  const persisted = JSON.parse(storage.get('gis_task_history'));
  const goals = persisted.map(task => task.goal);
  assert.equal(persisted.length, 20);
  assert.ok(goals.includes('任务 25'), 'the latest task must be retained');
  assert.ok(goals.includes('任务 6'), 'the 20th latest task must be retained');
  assert.equal(goals.includes('任务 5'), false, 'older unsaved tasks should fall outside the retention window');
});

test('saved task cards can attach the backend task reference to the next chat message', () => {
  let clickHandler;
  const taskList = {
    innerHTML: '',
    addEventListener(name, handler) { if (name === 'click') clickHandler = handler; },
  };
  const storage = new Map();
  const localStorage = {
    getItem(key) { return storage.get(key) || null; },
    setItem(key, value) { storage.set(key, value); },
  };
  const references = [];
  const window = { GIS: {
    api: { resolveProvider() { return null; } },
    chat: { setTaskReference(id, label) { references.push([id, label]); } },
  } };
  const sourcePath = path.resolve(__dirname, '../js/task.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document: { getElementById(id) { return id === 'historyList' ? taskList : null; } },
    localStorage, Date, Math, JSON, String, Number, Array, Object, console: { warn() {} },
  }, { filename: sourcePath });

  window.GIS.task.init();
  const task = window.GIS.task.createTask('卫星底图专题图', 'test', []);
  window.GIS.task.updateTask(task.id, { status: 'success', backendTaskId: 'backend-task-7' });
  assert.match(taskList.innerHTML, /task-reference/);

  const referenceButton = {};
  clickHandler({ target: { closest(selector) {
    if (selector === '.task-card') return { dataset: { taskId: task.id } };
    if (selector === '.task-reference') return referenceButton;
    return null;
  } } });

  assert.deepEqual(references, [['backend-task-7', '卫星底图专题图']]);
});
