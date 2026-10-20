const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function createLayers() {
  const document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
  const window = { GIS: {} };
  const sourcePath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, console, Promise, Set, Math, Date, Array, Object, String, Number,
  }, { filename: sourcePath });
  return window.GIS.layers;
}

test('restores a saved group whose ID is the legacy __proto__ property name', () => {
  const layers = createLayers();
  layers.setGroupState([{ id: '__proto__', name: 'Imported group', collapsed: true }]);

  assert.deepEqual(layers.getGroupState().map(group => ({ ...group })), [
    { id: '__proto__', name: 'Imported group', collapsed: true },
  ]);
});
