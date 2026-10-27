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

test('partially completed tasks are labeled distinctly and can be rerun', () => {
  const taskList = { innerHTML: '', addEventListener() {} };
  const document = { getElementById(id) { return id === 'historyList' ? taskList : null; } };
  const storage = new Map();
  const window = { GIS: { api: { resolveProvider() { return null; } } } };
  const sourcePath = path.resolve(__dirname, '../js/task.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, localStorage: { getItem(key) { return storage.get(key) || null; }, setItem(key, value) { storage.set(key, value); } },
    Date, Math, JSON, String, Number, Array, Object, console: { warn() {} },
  }, { filename: sourcePath });

  window.GIS.task.init();
  const task = window.GIS.task.createTask('缓冲分析', 'test', []);
  window.GIS.task.updateTask(task.id, { status: 'partial' });

  assert.match(taskList.innerHTML, /task-status-partial/);
  assert.match(taskList.innerHTML, /部分完成/);
  assert.match(taskList.innerHTML, /task-rerun/);
  assert.equal(JSON.parse(storage.get('gis_task_history'))[0].status, 'partial');
});

test('corrupted persisted task IDs and statuses cannot inject task card markup', () => {
  const taskList = { innerHTML: '', addEventListener() {} };
  const storage = new Map([['gis_task_history', JSON.stringify([{
    id: 'task-1" onmouseover="alert(1)',
    status: 'success" onmouseover="alert(2)',
    goal: '保留的任务', saved: true,
  }])]]);
  const window = { GIS: { api: { resolveProvider() { return null; } } } };
  const sourcePath = path.resolve(__dirname, '../js/task.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window,
    document: { getElementById(id) { return id === 'historyList' ? taskList : null; } },
    localStorage: { getItem(key) { return storage.get(key) || null; }, setItem(key, value) { storage.set(key, value); } },
    Date, Math, JSON, String, Number, Array, Object, console: { warn() {} },
  }, { filename: sourcePath });

  window.GIS.task.init();

  assert.match(taskList.innerHTML, /data-task-id="task-1&quot; onmouseover=&quot;alert\(1\)"/);
  assert.match(taskList.innerHTML, /task-status-unknown/);
  assert.match(taskList.innerHTML, /未知状态/);
  assert.doesNotMatch(taskList.innerHTML, /onmouseover="alert/);
});

test('stale in-progress tasks recover as interrupted and can be checked before rerun', () => {
  const staleTasks = [
    { id: '4', goal: '规划中的任务', provider: 'test', model: 'test', timestamp: 1, status: 'planning', resultLayers: [], saved: true },
    { id: '3', goal: '执行中的任务', provider: 'test', model: 'test', timestamp: 2, status: 'executing', resultLayers: [{ name: '可能已生成的图层' }], saved: false },
    { id: '2', goal: '已完成任务', provider: 'test', model: 'test', timestamp: 3, status: 'success', resultLayers: [], saved: false },
  ];
  const storage = new Map([['gis_task_history', JSON.stringify(staleTasks)]]);
  const taskList = { innerHTML: '', addEventListener() {} };
  const window = { GIS: { api: { resolveProvider() { return null; } } } };
  const sourcePath = path.resolve(__dirname, '../js/task.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document: { getElementById(id) { return id === 'historyList' ? taskList : null; } },
    localStorage: { getItem(key) { return storage.get(key) || null; }, setItem(key, value) { storage.set(key, value); } },
    Date, Math, JSON, String, Number, Array, Object, console: { warn() {} },
  }, { filename: sourcePath });

  window.GIS.task.init();

  const recovered = JSON.parse(storage.get('gis_task_history'));
  assert.equal(recovered[0].status, 'interrupted');
  assert.match(recovered[0].error, /先检查地图后再重试/);
  assert.ok(recovered[0].completedAt);
  assert.equal(recovered[1].status, 'interrupted');
  assert.equal(recovered[1].resultLayers[0].name, '可能已生成的图层');
  assert.equal(recovered[2].status, 'success', 'terminal task status must remain unchanged');
  assert.match(taskList.innerHTML, /执行中断，结果待核对/);
  assert.match(taskList.innerHTML, /task-status-interrupted/);
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
