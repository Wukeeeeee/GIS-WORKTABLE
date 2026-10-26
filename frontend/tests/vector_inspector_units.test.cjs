const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadInspector(provenance = null) {
  const listeners = {};
  const panel = { style: {} };
  const body = { innerHTML: '', querySelector() { return null; }, querySelectorAll() { return []; } };
  const title = { textContent: '' };
  const document = {
    getElementById(id) { return id === 'layerInspector' ? panel : id === 'inspectorBody' ? body : id === 'inspectorTitle' ? title : null; },
    addEventListener(event, callback) { (listeners[event] ||= []).push(callback); },
    dispatchEvent(event) { (listeners[event.type] || []).forEach(callback => callback(event)); },
    querySelectorAll() { return []; },
    documentElement: { lang: '' },
    readyState: 'complete',
  };
  const window = {
    GIS: {
      api: { async inspectLayer() { return {
        crs: 'EPSG:32649', crs_known: true, coordinate_units: 'metre',
        geometry_type: 'Point', feature_count: 1, bbox: [100, 30, 100, 30],
        attr_fields: {}, invalid_geom_count: 0,
      }; } },
      workspace: { preparePanel() {}, expandPanel() {}, centerPanel() {} },
    },
    addEventListener() {},
  };
  const context = {
    window, GIS: window.GIS, document, navigator: { language: 'en-US' },
    localStorage: { getItem() { return 'en'; }, setItem() {} },
    CustomEvent: function(type, options) { return { type, ...options }; },
    console: { warn() {} }, Promise, Set, Math, Date, Array, Object, String, Number,
  };
  for (const file of ['i18n.js', 'layers.js']) {
    const sourcePath = path.resolve(__dirname, '../js/' + file);
    vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  }
  window.GIS.layers.addLayer({
    layer_id: 'vector-one', filename: 'Projected points', geometry_type: 'Point', source: 'upload',
    provenance,
    geojson: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [100, 30] } }] },
  }, true);
  return { layers: window.GIS.layers, body, setLanguage: language => window.GIS.i18n.setLanguage(language) };
}

test('vector inspector shows the coordinate unit returned for the layer CRS in both UI languages', async () => {
  const h = loadInspector();
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /Coordinate units/);
  assert.match(h.body.innerHTML, /metre \(m\)/);

  h.setLanguage('zh-CN');
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /坐标单位/);
  assert.match(h.body.innerHTML, /米 \(m\)/);
});

test('vector inspector shows downloaded source facts safely', async () => {
  const h = loadInspector({
    provider_name: '<img src=x onerror=alert(1)>', kind_label: '道路', file_format: 'geojson',
    crs: 'EPSG:3857', crs_known: true, source_url: 'https://www.openstreetmap.org',
  });
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(h.body.innerHTML, /<img src=x onerror=alert/);
  assert.match(h.body.innerHTML, /Data provenance/);
  assert.match(h.body.innerHTML, /Data provider/);
  assert.match(h.body.innerHTML, /EPSG:3857/);
  assert.match(h.body.innerHTML, /href="https:\/\/www\.openstreetmap\.org"/);
});

test('vector inspector does not create links for non-HTTPS provenance URLs', async () => {
  const h = loadInspector({ provider_name: 'Example', source_url: 'javascript:alert(1)' });
  await h.layers.showLayerInspector('vector-one');
  assert.doesNotMatch(h.body.innerHTML, /href="javascript:/);
});

test('local vector upload provenance labels follow the active UI language', async () => {
  const h = loadInspector({ provider: 'local_upload', kind: 'vector_upload', file_format: 'GeoPackage', crs: 'EPSG:3857', crs_known: true });
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /Data provider/);
  assert.match(h.body.innerHTML, /Local file/);
  assert.match(h.body.innerHTML, /Vector file upload/);
  assert.match(h.body.innerHTML, /GeoPackage/);

  h.setLanguage('zh-CN');
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /数据提供方/);
  assert.match(h.body.innerHTML, /本地文件/);
  assert.match(h.body.innerHTML, /矢量文件上传/);
});

test('buffer result processing details are shown safely in both UI languages', async () => {
  const h = loadInspector({
    provider: 'gis_worktable', kind: 'analysis_result',
    processing: { tool: 'spatial_buffer', source_layer: '<img src=x>', parameters: { distance: 500, unit: 'm', dissolve: true } },
  });
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /Processing record/);
  assert.match(h.body.innerHTML, /GIS WorkTable/);
  assert.match(h.body.innerHTML, /Spatial analysis result/);
  assert.match(h.body.innerHTML, /Buffer analysis/);
  assert.match(h.body.innerHTML, /500 m/);
  assert.match(h.body.innerHTML, /&lt;img src=x&gt;/);
  assert.doesNotMatch(h.body.innerHTML, /<img src=x>/);

  h.setLanguage('zh-CN');
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /处理记录/);
  assert.match(h.body.innerHTML, /空间分析结果/);
  assert.match(h.body.innerHTML, /缓冲区分析/);
  assert.match(h.body.innerHTML, /融合重叠区/);
});

test('clip result processing details show both input layers safely in both UI languages', async () => {
  const h = loadInspector({
    provider: 'gis_worktable', kind: 'analysis_result',
    processing: { tool: 'spatial_clip', source_layer: '<img src=x>', clip_layer: 'study & area' },
  });
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /Clip analysis/);
  assert.match(h.body.innerHTML, /Input layer/);
  assert.match(h.body.innerHTML, /Clip boundary layer/);
  assert.match(h.body.innerHTML, /study &amp; area/);
  assert.doesNotMatch(h.body.innerHTML, /<img src=x>/);

  h.setLanguage('zh-CN');
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /裁剪分析/);
  assert.match(h.body.innerHTML, /裁剪边界图层/);
});

test('union result processing details show both input layers safely in both UI languages', async () => {
  const h = loadInspector({
    provider: 'gis_worktable', kind: 'analysis_result',
    processing: { tool: 'spatial_union', source_layer: 'roads', other_layer: '<img src=x>' },
  });
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /Spatial union/);
  assert.match(h.body.innerHTML, /Other input layer/);
  assert.match(h.body.innerHTML, /&lt;img src=x&gt;/);
  assert.doesNotMatch(h.body.innerHTML, /<img src=x>/);

  h.setLanguage('zh-CN');
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /空间合并/);
  assert.match(h.body.innerHTML, /另一个输入图层/);
});

test('intersection result processing details show both input layers safely in both UI languages', async () => {
  const h = loadInspector({
    provider: 'gis_worktable', kind: 'analysis_result',
    processing: { tool: 'spatial_intersect', source_layer: 'parcels', other_layer: '<img src=x>' },
  });
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /Spatial intersection/);
  assert.match(h.body.innerHTML, /parcels/);
  assert.match(h.body.innerHTML, /&lt;img src=x&gt;/);
  assert.doesNotMatch(h.body.innerHTML, /<img src=x>/);

  h.setLanguage('zh-CN');
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /空间相交/);
  assert.match(h.body.innerHTML, /另一个输入图层/);
});

test('difference result processing details show both input layers safely in both UI languages', async () => {
  const h = loadInspector({
    provider: 'gis_worktable', kind: 'analysis_result',
    processing: { tool: 'spatial_difference', source_layer: 'parcels', other_layer: '<img src=x>' },
  });
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /Spatial difference/);
  assert.match(h.body.innerHTML, /parcels/);
  assert.match(h.body.innerHTML, /&lt;img src=x&gt;/);
  assert.doesNotMatch(h.body.innerHTML, /<img src=x>/);

  h.setLanguage('zh-CN');
  await h.layers.showLayerInspector('vector-one');
  assert.match(h.body.innerHTML, /空间差异/);
  assert.match(h.body.innerHTML, /另一个输入图层/);
});
