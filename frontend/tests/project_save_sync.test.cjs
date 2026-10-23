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

function setup(layers = [], wait = () => Promise.resolve([])) {
  const saves = [];
  const errors = [];
  const api = {
    autoSaveProject(session, id, groups, assignments) {
      saves.push({ session, id, groups, assignments });
      return Promise.resolve({ id: 'saved' });
    },
    saveProject(payload) { saves.push(payload); return Promise.resolve({ id: 'saved' }); },
  };
  const window = { GIS: { api, layers: {
    getLayers: () => layers, waitForRegistrySync: wait, getGroupState: () => [],
  }, toast: { error(message) { errors.push(message); } } } };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../js/project.js'), 'utf8'), {
    window, document: { getElementById: () => null }, Promise, Date, Math, Number, String, Object, Array, JSON,
    console: { warn() {} },
  });
  return { api, layers, saves, errors, project: window.GIS.project };
}

test('autosave collects names and groups after current registration finishes', async () => {
  const sync = deferred();
  const layer = { layer_id: 'layer', filename: 'Old', _rawName: 'Old', _registeredName: 'Old' };
  const h = setup([layer], () => sync.promise);
  const saving = h.project.autoSave();
  await new Promise(resolve => setImmediate(resolve));
  layer.filename = layer._rawName = layer._registeredName = 'New';
  layer.groupId = 'new-group';
  sync.resolve([true]);
  await saving;
  assert.deepEqual(Array.from(h.saves[0].assignments[0].names), ['New']);
  assert.equal(h.saves[0].assignments[0].registry_name, 'New');
  assert.equal(h.saves[0].assignments[0].groupId, 'new-group');
});

for (const results of [[[false]], [[{ success: false }]], [[{ ok: false }]], undefined]) {
  test(`autosave rejects failed or unknown synchronization results: ${JSON.stringify(results)}`, async () => {
    const h = setup([], () => Promise.resolve(results));
    await h.project.autoSave();
    assert.equal(h.saves.length, 0);
    assert.equal(h.errors.length, 1);
  });
}

test('overlapping autosaves are ordered and reuse the project created by the first save', async () => {
  const first = deferred();
  const h = setup();
  h.api.autoSaveProject = (session, id) => {
    h.saves.push({ session, id });
    return h.saves.length === 1 ? first.promise : Promise.resolve({ id: 'saved' });
  };
  const one = h.project.autoSave();
  const two = h.project.autoSave();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.saves.length, 1);
  first.resolve({ id: 'saved' });
  await Promise.all([one, two]);
  assert.deepEqual(h.saves.map(save => save.id), [null, 'saved']);
});

for (const manualFirst of [false, true]) test(`manual and automatic saves share one queue (${manualFirst ? 'manual' : 'auto'} first)`, async () => {
  const first = deferred();
  const h = setup();
  const order = [];
  function request(kind, id) {
    order.push({ kind, id });
    return order.length === 1 ? first.promise : Promise.resolve({ id: 'saved' });
  }
  h.api.autoSaveProject = (session, id) => request('auto', id);
  h.api.saveProject = payload => request('manual', payload.project_id);
  const one = manualFirst ? h.project.save('Named') : h.project.autoSave();
  const two = manualFirst ? h.project.autoSave() : h.project.save('Named');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(order.length, 1);
  first.resolve({ id: 'saved' });
  await Promise.all([one, two]);
  assert.deepEqual(order.map(item => item.kind), manualFirst ? ['manual', 'auto'] : ['auto', 'manual']);
  assert.equal(order[1].id, 'saved');
});

test('switching projects while synchronization waits cancels the stale autosave', async () => {
  const sync = deferred();
  const h = setup([], () => sync.promise);
  const saving = h.project.autoSave();
  await new Promise(resolve => setImmediate(resolve));
  h.project.setCurrentProjectId('other');
  sync.resolve([]);
  assert.equal(await saving, null);
  assert.equal(h.saves.length, 0);
  assert.equal(h.project.getCurrentProjectId(), 'other');
});

test('failed autosave does not poison the queue for a later full manual save', async () => {
  const h = setup([], () => Promise.resolve([false]));
  const one = h.project.autoSave();
  const two = h.project.save('Manual');
  await one;
  assert.equal((await two).id, 'saved');
  assert.equal(h.saves.length, 1);
  assert.equal(h.saves[0].name, 'Manual');
});
