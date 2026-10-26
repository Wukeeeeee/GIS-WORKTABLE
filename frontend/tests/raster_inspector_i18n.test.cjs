const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadRasterInspector() {
  const listeners = {};
  const panel = { style: {} };
  const body = { innerHTML: '' };
  const title = { textContent: '' };
  const document = {
    getElementById(id) { return id === 'layerInspector' ? panel : id === 'inspectorBody' ? body : id === 'inspectorTitle' ? title : null; },
    addEventListener(event, callback) { (listeners[event] ||= []).push(callback); },
    dispatchEvent(event) { (listeners[event.type] || []).forEach(callback => callback(event)); },
    querySelectorAll() { return []; },
    documentElement: { lang: '' },
    readyState: 'complete',
  };
  const window = { GIS: {}, addEventListener() {} };
  const context = {
    window, GIS: window.GIS, document, navigator: { language: 'en-US' },
    localStorage: { getItem() { return 'en'; }, setItem() {} },
    CustomEvent: function(type, options) { return { type, ...options }; },
    console: { warn() {} }, Promise, Set, Math, Date, Array, Object, String, Number,
  };
  const i18nPath = path.resolve(__dirname, '../js/i18n.js');
  vm.runInNewContext(fs.readFileSync(i18nPath, 'utf8'), context, { filename: i18nPath });
  window.GIS.workspace = { preparePanel() {}, expandPanel() {}, centerPanel() {} };
  const sourcePath = path.resolve(__dirname, '../js/layers.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  const raster = {
    crs: 'EPSG:4326', bounds: [100, 20, 101, 21], pixel_size: [0.01, 0.01], pixel_units: 'degree',
    source_width: 100, source_height: 100, bands: 1, processing: '坡度(Slope)', value_units: '°（角度）',
    quality_warnings: ['有效像元比例低于 90%，请检查 NoData 或输入覆盖范围'],
  };
  window.GIS.layers.addLayer({ layer_id: 'raster-one', filename: 'Elevation', geometry_type: 'Raster', raster }, true);
  return {
    layers: window.GIS.layers, i18n: window.GIS.i18n, body, title, panel,
    setLanguage(value) { window.GIS.i18n.setLanguage(value ? 'en' : 'zh-CN'); },
  };
}

test('raster metadata inspector follows the selected UI language, including after a language switch', async () => {
  const h = loadRasterInspector();
  await h.layers.showLayerInspector('raster-one');

  assert.equal(h.title.textContent, 'Raster inspection');
  assert.match(h.body.innerHTML, /Source CRS/);
  assert.match(h.body.innerHTML, /Valid pixel ratio is below 90%/);
  assert.match(h.body.innerHTML, /EPSG:4326/);
  assert.match(h.body.innerHTML, />Slope<\/span>/);
  assert.match(h.body.innerHTML, />degree \(°\)<\/span>/);

  h.setLanguage(false);
  assert.equal(h.title.textContent, '栅格检查');
  assert.match(h.body.innerHTML, /源数据 CRS/);
  assert.match(h.body.innerHTML, /有效像元比例低于 90%/);
  assert.match(h.body.innerHTML, /坡度\(Slope\)/);
  assert.match(h.body.innerHTML, /°（角度）/);
});

test('layer context-menu labels follow the selected UI language', () => {
  const h = loadRasterInspector();
  assert.equal(h.i18n.t('layer.context.legend', '显示图例'), 'Show legend');
  assert.equal(h.i18n.t('layer.context.add-feature', '＋ 添加要素'), '＋ Add feature');

  h.setLanguage(false);
  assert.equal(h.i18n.t('layer.context.legend', '显示图例'), '显示图例');
  assert.equal(h.i18n.t('layer.context.add-feature', '＋ 添加要素'), '＋ 添加要素');
});
