const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadInspector(provenance = null, customGeojson = null) {
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
    geojson: customGeojson || { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [100, 30] } }] },
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

test('layer data audit accurately computes feature count, null geometries, geometry types, and null field counts', async () => {
  const sampleGeojson = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [100, 30] },
        properties: { name: 'Alpha', count: 0, active: false, note: 'valid', _fid: 'fid-1' },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [101, 31] },
        properties: { name: null, count: 5, active: true, note: '', _fid: 'fid-2' },
      },
      {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
        properties: { name: undefined, count: 0, active: false, note: null, _fid: 'fid-3' },
      },
      {
        type: 'Feature',
        geometry: null, // 空几何 (null)
        properties: { count: 10, active: true, _fid: 'fid-4' }, // 缺失 name 与 note 字段
      },
      {
        type: 'Feature',
        geometry: { type: '' }, // 空几何 (缺少有效 type)
        properties: { name: '', count: 0, active: false, note: undefined, _fid: 'fid-5' },
      },
    ],
  };

  const h = loadInspector(null, sampleGeojson);
  await h.layers.showLayerInspector('vector-one');

  // 1. 标题与结构
  assert.match(h.body.innerHTML, /图层数据体检/);
  assert.match(h.body.innerHTML, /几何类型分布/);
  assert.match(h.body.innerHTML, /各字段空值数量/);

  // 2. 要素总数与空几何数量
  assert.match(h.body.innerHTML, /<span class="info-label">要素总数<\/span><span class="info-val">5<\/span>/);
  assert.match(h.body.innerHTML, /<span class="info-label">空几何数量<\/span><span class="info-val">2<\/span>/);

  // 3. 几何类型分布
  assert.match(h.body.innerHTML, /<span class="info-label">Point<\/span><span class="info-val">2<\/span>/);
  assert.match(h.body.innerHTML, /<span class="info-label">Polygon<\/span><span class="info-val">1<\/span>/);

  // 4. 字段空值计数：包含 null、undefined、空字符串、缺失字段 (各 4 次空值)
  assert.match(h.body.innerHTML, /<span class="info-label">name<\/span><span class="info-val">4<\/span>/);
  assert.match(h.body.innerHTML, /<span class="info-label">note<\/span><span class="info-val">4<\/span>/);

  // 5. 0 和 false 不为空值 (空值计数为 0)
  assert.match(h.body.innerHTML, /<span class="info-label">count<\/span><span class="info-val">0<\/span>/);
  assert.match(h.body.innerHTML, /<span class="info-label">active<\/span><span class="info-val">0<\/span>/);

  // 6. _fid 必须被排除，不应作为属性字段呈现
  assert.doesNotMatch(h.body.innerHTML, /<span class="info-label">_fid<\/span>/);
});

test('layer data audit safely escapes HTML special characters in attribute field names', async () => {
  const maliciousGeojson = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [100, 30] },
        properties: { '<img src=x onerror=alert(1)>': 'val1', normal: 'ok' },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [100, 30] },
        properties: { '<img src=x onerror=alert(1)>': null, normal: 'ok' },
      },
    ],
  };

  const h = loadInspector(null, maliciousGeojson);
  await h.layers.showLayerInspector('vector-one');

  // 安全转义验证
  assert.match(h.body.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(h.body.innerHTML, /<img src=x onerror=alert/);
  assert.match(h.body.innerHTML, /<span class="info-label">&lt;img src=x onerror=alert\(1\)&gt;<\/span><span class="info-val">1<\/span>/);
});

test('data audit CSV exports current layer statistics and escapes Unicode and CSV control characters', () => {
  const h = loadInspector();
  const current = {
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', geometry: { type: 'Point', coordinates: [1, 2] }, properties: { '名称,"字段"\n第二\r行': '中文,"值"\n第二行\r结束', count: 0, _fid: 'internal' } },
      { type: 'Feature', geometry: null, properties: { '名称,"字段"\n第二\r行': null, count: false } },
    ],
  };
  h.layers.syncLayerData('vector-one', current);
  const csv = h.layers.exportDataAuditCSV('vector-one');
  assert.match(csv, /图层数据体检,要素总数,2/);
  assert.match(csv, /图层数据体检,空几何数量,1/);
  assert.match(csv, /几何类型分布,Point,1/);
  assert.ok(csv.includes('各字段空值数量,"名称,""字段""\n第二\r行",1'));
  assert.match(csv, /各字段空值数量,count,0/);
  assert.doesNotMatch(csv, /internal/);
});

test('data audit CSV export uses the requested layer current data', () => {
  const h = loadInspector();
  h.layers.addLayer({
    layer_id: 'vector-two', filename: 'Other', geometry_type: 'Point',
    geojson: { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: null, properties: { second: null } }] },
  }, true);
  const current = { type: 'FeatureCollection', features: [
    { type: 'Feature', geometry: { type: 'Polygon' }, properties: { fresh: null } },
    { type: 'Feature', geometry: { type: 'Polygon' }, properties: { fresh: 'ok' } },
  ] };
  h.layers.syncLayerData('vector-one', current);
  const csv = h.layers.exportDataAuditCSV('vector-one');
  assert.match(csv, /要素总数,2/);
  assert.match(csv, /几何类型分布,Polygon,2/);
  assert.match(csv, /各字段空值数量,fresh,1/);
  assert.doesNotMatch(csv, /Other|second|Point/);
});

test('data audit CSV escapes spreadsheet formula injection prefixes in field names', () => {
  const h = loadInspector();
  const current = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [0, 0] },
        properties: {
          '=1+1': 'val',
          '+cmd': 'val',
          '-formula': 'val',
          '@SUM(1,2)': 'val',
          '＝1+1': 'val',
          '＋cmd': 'val',
          '－formula': 'val',
          '＠SUM(1,2)': 'val',
          '\t=tab_danger': 'val',
          '  @space_danger': 'val',
          '\r-cr_danger': 'val',
        },
      },
    ],
  };
  h.layers.syncLayerData('vector-one', current);
  const csv = h.layers.exportDataAuditCSV('vector-one');

  // 证明危险前缀被中和，不得直接以公式触发字符导出
  assert.doesNotMatch(csv, /各字段空值数量,=1\+1/);
  assert.doesNotMatch(csv, /各字段空值数量,\+cmd/);
  assert.doesNotMatch(csv, /各字段空值数量,-formula/);
  assert.doesNotMatch(csv, /各字段空值数量,@SUM/);
  assert.doesNotMatch(csv, /各字段空值数量,"\t=tab_danger"/);

  // 验证遵循 OWASP 针对电子表格查看推荐的 Tab 前缀且强制双引号包裹策略
  assert.ok(csv.includes('各字段空值数量,"\t=1+1",0'), '等号前缀字段应包含前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t+cmd",0'), '加号前缀字段应包含前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t-formula",0'), '减号前缀字段应包含前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t@SUM(1,2)",0'), '艾特前缀字段应包含前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t＝1+1",0'), '全角等号前缀字段应包含前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t＋cmd",0'), '全角加号前缀字段应包含前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t－formula",0'), '全角减号前缀字段应包含前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t＠SUM(1,2)",0'), '全角艾特前缀字段应包含前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t\t=tab_danger",0'), '前导制表符绕过应被前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t  @space_danger",0'), '前导空格绕过应被前置 tab 且被双引号包裹');
  assert.ok(csv.includes('各字段空值数量,"\t\r-cr_danger",0'), '前导回车绕过应被前置 tab 且被双引号包裹');
});

test('attribute table CSV escapes formula prefixes in field names and values', () => {
  const h = loadInspector();
  const csv = h.layers.generateAttributeCSV([
    { properties: { '=1+1': '=HYPERLINK("https://example.invalid")', name: '中文,"值"\n第二行' } },
    { properties: { '=1+1': '\t@SUM(1,2)', name: null } },
  ], ['=1+1', 'name']);

  assert.ok(csv.startsWith('"\t=1+1",name\r\n'));
  assert.ok(csv.includes('"\t=HYPERLINK(""https://example.invalid"")","中文,""值""\n第二行"\r\n'));
  assert.ok(csv.includes('"\t\t@SUM(1,2)",\r\n'));
});

test('GeoJSON download restores transported unsafe integers as numeric literals', () => {
  const h = loadInspector();
  const geojson = JSON.parse('{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"large":"9007199254740993","nested":{"value":"9007199254740995"},"ordinaryNumericText":"123"},"geometry":{"type":"Point","coordinates":[120,30]},"_gisworktable_integer_paths":[["large"],["nested","value"]]}]}');
  const json = h.layers.stringifyGeoJSONLossless(geojson, 0);
  assert.match(json, /"large":9007199254740993/);
  assert.match(json, /"value":9007199254740995/);
  assert.match(json, /"ordinaryNumericText":"123"/);
  assert.doesNotMatch(json, /_gisworktable_integer_paths/);
});
