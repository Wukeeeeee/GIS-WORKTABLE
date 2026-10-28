window.GIS = window.GIS || {};

/**
 * raster_tools.js — 栅格与工具直连面板
 * 顶部菜单「栅格」「工具」的落地点：坡度/坡向/山体阴影/等高线/NDVI/栅格计算器/
 * 空间插值/水文分析/拓扑检查/坐标转换——全部经 /api/tools/invoke 直连后端工具，
 * 不经 LLM。设计语言：直角、浅色、细边框。
 */
(function () {
  'use strict';

  var GIS = window.GIS;
  var _initialized = false;

  var OPS = [
    { id: 'slope', label: '坡度分析', tool: 'dem_analysis', args: { analysis: 'slope' }, layerHint: 'DEM 栅格' },
    { id: 'aspect', label: '坡向分析', tool: 'dem_analysis', args: { analysis: 'aspect' }, layerHint: 'DEM 栅格' },
    { id: 'hillshade', label: '山体阴影', tool: 'dem_analysis', args: { analysis: 'hillshade' }, layerHint: 'DEM 栅格' },
    { id: 'contour', label: '等高线', tool: 'extract_contours', args: {}, layerHint: 'DEM 栅格', extra: 'interval' },
    { id: 'ndvi', label: 'NDVI', tool: 'ndvi_analysis', args: {}, layerHint: '多光谱栅格', extra: 'bands' },
    { id: 'rastercalc', label: '栅格计算器', tool: 'raster_calculator', args: {}, layerHint: '栅格', extra: 'expression' },
    { id: 'interpolate', label: '空间插值', tool: 'spatial_interpolate', args: {}, layerHint: '点图层', extra: 'field' },
    { id: 'hydrology', label: '水文分析', tool: 'hydrology_analysis', args: {}, layerHint: 'DEM 栅格', extra: 'hydro' },
    { id: 'topology', label: '拓扑检查', tool: 'topology_check', args: {}, layerHint: '面图层' },
    { id: 'coord', label: '坐标转换', tool: 'convert_coordinates', args: {}, layerHint: null, extra: 'coords' },
    { id: 'heatmap', label: '热力图（点图层）', tool: 'create_heatmap', args: {}, layerHint: '点图层', extra: 'weight' },
    { id: 'split', label: '图层拆分（按字段）', tool: 'layer_split', args: {}, layerHint: '图层', extra: 'field' },
    { id: 'geocode', label: '坐标转地址', tool: 'reverse_geocode', args: {}, layerHint: null, extra: 'coords' },
  ];

  var PANEL_HTML =
    ("<div class=\"spatial-panel\" id=\"rasterToolsPanel\">"
      + "<div class=\"spatial-toolbar\" id=\"rasterToolsToolbar\">"
      + "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:18px;height:18px;--ui-icon-image:url('/assets/ui-icons/icon-9955681a84e8.png')\">"
      + "</span>"
      + "<span class=\"spatial-toolbar-title\">栅格与地理工具"
      + "</span>"
      + "<button class=\"spatial-toolbar-close\" id=\"rasterToolsClose\">"
      + "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:16px;height:16px;--ui-icon-image:url('/assets/ui-icons/icon-28a441e0afbc.png')\">"
      + "</span>"
      + "</button>"
      + "</div>"
      + "<div class=\"spatial-body\" id=\"rasterToolsBody\">"
      + "<div class=\"spatial-field\">"
      + "<label>功能"
      + "</label>"
      + "<select id=\"rtOp\">"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"rtLayerField\">"
      + "<label id=\"rtLayerLabel\">图层"
      + "</label>"
      + "<select id=\"rtLayer\">"
      + "<option value=\"\">-- 请选择图层 --"
      + "</option>"
      + "</select>"
      + "<input type=\"text\" id=\"rtLayerText\" class=\"spatial-input\" placeholder=\"或直接输入栅格文件名（如 dem）\" style=\"margin-top:4px;display:none;\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"rtIntervalField\" style=\"display:none\">"
      + "<label>等高距（米，0=自动）"
      + "</label>"
      + "<input type=\"number\" id=\"rtInterval\" class=\"spatial-input\" value=\"0\" min=\"0\" step=\"10\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"rtBandsField\" style=\"display:none\">"
      + "<label>红波段 / 近红外波段（1 起）"
      + "</label>"
      + "<div class=\"spatial-row\">"
      + "<input type=\"number\" id=\"rtRed\" class=\"spatial-input\" value=\"3\" min=\"1\" step=\"1\">"
      + "<input type=\"number\" id=\"rtNir\" class=\"spatial-input\" value=\"4\" min=\"1\" step=\"1\">"
      + "</div>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"rtExpressionField\" style=\"display:none\">"
      + "<label>表达式（如 B1*2-B2）"
      + "</label>"
      + "<input type=\"text\" id=\"rtExpression\" class=\"spatial-input\" placeholder=\"B1*2-B2\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"rtFieldField\" style=\"display:none\">"
      + "<label>插值字段（数值）"
      + "</label>"
      + "<select id=\"rtFieldSel\">"
      + "<option value=\"\">-- 选择字段 --"
      + "</option>"
      + "</select>"
      + "<div class=\"spatial-row\" style=\"margin-top:4px;\">"
      + "<select id=\"rtMethod\" class=\"spatial-select-short\">"
      + "<option value=\"idw\">IDW 反距离权重"
      + "</option>"
      + "<option value=\"kriging\">Kriging 克里金"
      + "</option>"
      + "</select>"
      + "</div>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"rtHydroField\" style=\"display:none\">"
      + "<label>分析类型"
      + "</label>"
      + "<select id=\"rtHydroOp\">"
      + "<option value=\"flowacc\">汇流累积量"
      + "</option>"
      + "<option value=\"watershed\">流域划分"
      + "</option>"
      + "<option value=\"stream\">河网提取"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"rtWeightField\" style=\"display:none\">"
      + "<label>权重字段（可选）"
      + "</label>"
      + "<select id=\"rtWeightSel\">"
      + "<option value=\"\">-- 无权重（按点密度） --"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"rtCoordsField\" style=\"display:none\">"
      + "<label>坐标（lng,lat，分号分隔可批量）"
      + "</label>"
      + "<input type=\"text\" id=\"rtCoords\" class=\"spatial-input\" placeholder=\"112.94,28.23\">"
      + "<div class=\"spatial-row\" style=\"margin-top:4px;\">"
      + "<select id=\"rtSrcCrs\" class=\"spatial-select-short\">"
      + "<option value=\"wgs84\">WGS84"
      + "</option>"
      + "<option value=\"gcj02\">GCJ02（高德/腾讯）"
      + "</option>"
      + "<option value=\"web_mercator\">Web Mercator"
      + "</option>"
      + "<option value=\"utm_auto\">UTM 自动"
      + "</option>"
      + "</select>"
      + "<span style=\"align-self:center;font-size:12px;color:var(--ui-gray-500);\">→"
      + "</span>"
      + "<select id=\"rtDstCrs\" class=\"spatial-select-short\">"
      + "<option value=\"web_mercator\">Web Mercator"
      + "</option>"
      + "<option value=\"wgs84\">WGS84"
      + "</option>"
      + "<option value=\"utm_auto\">UTM 自动"
      + "</option>"
      + "</select>"
      + "</div>"
      + "</div>"
      + "<button class=\"spatial-run-btn\" id=\"rtRun\">运行"
      + "</button>"
      + "<div class=\"spatial-result\" id=\"rtResult\" style=\"display:none\">"
      + "<div class=\"spatial-result-body\" id=\"rtResultBody\">"
      + "</div>"
      + "</div>"
      + "</div>"
      + "</div>");

  function _opById(id) {
    for (var i = 0; i < OPS.length; i++) if (OPS[i].id === id) return OPS[i];
    return null;
  }

  function init() {
    if (_initialized) return;
    var wrapper = document.getElementById('rasterToolsPanelWrapper');
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.id = 'rasterToolsPanelWrapper';
      document.documentElement.appendChild(wrapper);
    }
    var container = document.getElementById('rasterToolsPanelContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'rasterToolsPanelContainer';
      wrapper.appendChild(container);
    }
    container.innerHTML = PANEL_HTML;

    var opSel = document.getElementById('rtOp');
    OPS.forEach(function (op) {
      var opt = document.createElement('option');
      opt.value = op.id;
      opt.textContent = op.label;
      opSel.appendChild(opt);
    });

    document.getElementById('rasterToolsClose').addEventListener('click', deactivate);
    if (GIS.workspace) GIS.workspace.preparePanel('rasterToolsPanel', 'rasterToolsToolbar', 'rasterToolsClose', '栅格处理');
    opSel.addEventListener('change', function () { _applyOpVisibility(); _refreshLayers(); });
    document.getElementById('rtLayer').addEventListener('change', _refreshFieldSel);
    document.getElementById('rtRun').addEventListener('click', _run);

    _applyOpVisibility();
    _centerPanel(container);
    _initDrag(container);
    _initialized = true;
  }

  function activate() {
    init();
    var container = document.getElementById('rasterToolsPanelContainer');
    if (!container) return;
    container.style.display = '';
    if (GIS.workspace) GIS.workspace.expandPanel('rasterToolsPanel');
    _refreshLayers();
    _centerPanel(container);
  }

  function deactivate() {
    var container = document.getElementById('rasterToolsPanelContainer');
    if (container) container.style.display = 'none';
  }

  function openWith(opId) {
    activate();
    if (opId) {
      document.getElementById('rtOp').value = opId;
      _applyOpVisibility();
      _refreshLayers();
    }
  }

  function _applyOpVisibility() {
    var op = _opById(document.getElementById('rtOp').value);
    if (!op) return;
    var hasLayer = !!op.layerHint;
    document.getElementById('rtLayerField').style.display = hasLayer ? '' : 'none';
    document.getElementById('rtLayerLabel').textContent = op.layerHint || '';
    document.getElementById('rtIntervalField').style.display = op.extra === 'interval' ? '' : 'none';
    document.getElementById('rtBandsField').style.display = op.extra === 'bands' ? '' : 'none';
    document.getElementById('rtExpressionField').style.display = op.extra === 'expression' ? '' : 'none';
    document.getElementById('rtFieldField').style.display = op.extra === 'field' ? '' : 'none';
    document.getElementById('rtHydroField').style.display = op.extra === 'hydro' ? '' : 'none';
    document.getElementById('rtCoordsField').style.display = op.extra === 'coords' ? '' : 'none';
    document.getElementById('rtWeightField').style.display = op.extra === 'weight' ? '' : 'none';
    var isFieldOp = op.extra === 'field' || op.extra === 'split';
    document.getElementById('rtFieldField').style.display = isFieldOp ? '' : 'none';
    var fieldLabel = document.getElementById('rtFieldSel').parentElement.querySelector('label');
    if (fieldLabel) fieldLabel.textContent = op.id === 'split' ? '拆分字段' : '插值字段（数值）';
    // 栅格类工具按文件名找 uploads 里的 tif，选择器之外保留手输名
    var isRaster = ['slope', 'aspect', 'hillshade', 'contour', 'ndvi', 'rastercalc', 'hydrology'].indexOf(op.id) >= 0;
    document.getElementById('rtLayerText').style.display = isRaster ? '' : 'none';
  }

  /** 图层下拉：后端注册名 ∪ 前端面板名（直连执行前会自动补注册） */
  function _refreshLayers() {
    var feNames = (GIS.layers && GIS.layers.getLayerNames) ? GIS.layers.getLayerNames() : [];
    fetch((GIS.api && GIS.api.BASE_URL || '') + '/api/layers/names')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var seen = {}, merged = [];
        ((data && data.names) || []).concat(feNames).forEach(function (n) {
          if (n && !seen[n]) { seen[n] = 1; merged.push(n); }
        });
        var sel = document.getElementById('rtLayer');
        var cur = sel.value;
        sel.innerHTML = '<option value="">-- 请选择图层 --</option>';
        var entries = GIS.state && GIS.state.layerOptionEntries
          ? GIS.state.layerOptionEntries(merged)
          : merged.map(function(n) { return { value: n, suffix: '' }; });
        entries.forEach(function (entry) {
          var n = entry.value;
          var opt = document.createElement('option');
          opt.value = n;
          opt.textContent = n + (entry.suffix || '');
          if (n === cur) opt.selected = true;
          sel.appendChild(opt);
        });
        _refreshFieldSel();
      })
      .catch(function () {
        var sel = document.getElementById('rtLayer');
        var cur = sel.value;
        sel.innerHTML = '<option value="">-- 请选择图层 --</option>';
        var entries = GIS.state && GIS.state.layerOptionEntries
          ? GIS.state.layerOptionEntries(feNames)
          : feNames.map(function(n) { return { value: n, suffix: '' }; });
        entries.forEach(function (entry) {
          var n = entry.value;
          var opt = document.createElement('option');
          opt.value = n; opt.textContent = n + (entry.suffix || '');
          if (n === cur) opt.selected = true;
          sel.appendChild(opt);
        });
        _refreshFieldSel();
      });
  }

  function _refreshFieldSel() {
    var fieldSel = document.getElementById('rtFieldSel');
    var weightSel = document.getElementById('rtWeightSel');
    if (weightSel) {
      var wName = document.getElementById('rtLayer').value;
      var wCur = weightSel.value;
      weightSel.innerHTML = '<option value="">-- 无权重（按点密度） --</option>';
      if (wName && GIS.layers && GIS.layers.getLayerByName) {
        _getLayerFeatures(GIS.layers.getLayerByName(wName)).forEach(function (feature) {
          var wProps = feature && feature.properties || {};
          Object.keys(wProps).forEach(function (k) {
            if (k === '_fid' || typeof wProps[k] !== 'number' || !isFinite(wProps[k]) ||
                weightSel.options.some(function (option) { return option.value === k; })) return;
          var o = document.createElement('option');
          o.value = k; o.textContent = k;
          if (k === wCur) o.selected = true;
          weightSel.appendChild(o);
          });
        });
      }
      if (wCur && weightSel.options.some(function (option) { return option.value === wCur; })) weightSel.value = wCur;
    }
    if (!fieldSel) return;
    var layerName = document.getElementById('rtLayer').value;
    var currentField = fieldSel.value;
    fieldSel.innerHTML = '<option value="">-- 选择字段 --</option>';
    if (!layerName || !GIS.layers || !GIS.layers.getLayerByName) return;
    var layer = GIS.layers.getLayerByName(layerName);
    var op = _opById(document.getElementById('rtOp').value);
    var numericOnly = !!op && op.id === 'interpolate';
    var seenFields = {};
    _getLayerFeatures(layer).forEach(function (feature) {
      var props = feature && feature.properties || {};
      Object.keys(props).forEach(function (k) {
        if (k === '_fid' || seenFields[k] || (numericOnly && !(typeof props[k] === 'number' && isFinite(props[k])))) return;
        seenFields[k] = true;
        var opt = document.createElement('option');
        opt.value = k; opt.textContent = k;
        fieldSel.appendChild(opt);
      });
    });
    if (currentField && seenFields[currentField]) fieldSel.value = currentField;
  }

  function _getLayerFeatures(layer) {
    if (!layer || !layer.geojson) return [];
    if (layer.geojson.type === 'FeatureCollection') return layer.geojson.features || [];
    return layer.geojson.type === 'Feature' ? [layer.geojson] : [];
  }

  function _clampToMapArea(container, left, top) {
    if (GIS.workspace) return GIS.workspace.clampPanel(container, left, top, 380);
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var chatPanel = document.querySelector('.chat-panel');
    var minLeft = 4;
    if (chatPanel) {
      var r = chatPanel.getBoundingClientRect();
      minLeft = (r.width > 0 ? r.right : 0) + 4;
    }
    var w = container.offsetWidth || 380;
    var h = container.offsetHeight || 300;
    left = Math.max(minLeft, Math.min(vw - w - 10, left));
    top = Math.max(34, Math.min(vh - h - 10, top));
    return [left, top];
  }

  function _centerPanel(container) {
    if (GIS.workspace) {
      GIS.workspace.centerPanel(container, 380);
      return;
    }
    var vw = window.innerWidth;
    var chatPanel = document.querySelector('.chat-panel');
    var chatRight = 4;
    if (chatPanel) {
      var r = chatPanel.getBoundingClientRect();
      chatRight = (r.width > 0 ? r.right : 0) + 4;
    }
    var coords = _clampToMapArea(container, chatRight + (vw - chatRight - 380) / 2, 80);
    container.style.left = coords[0] + 'px';
    container.style.top = coords[1] + 'px';
    container.style.transform = 'none';
  }

  function _initDrag(container) {
    var header = document.getElementById('rasterToolsToolbar');
    if (!header) return;
    var startX, startY, startLeft, startTop;
    function onStart(e) {
      if (e.target.closest('button')) return;
      var ev = e.touches ? e.touches[0] : e;
      startX = ev.clientX; startY = ev.clientY;
      var currentRect = container.getBoundingClientRect();
      startLeft = currentRect.left; startTop = currentRect.top;
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onEnd);
    }
    function onMove(e) {
      var ev = e.touches ? e.touches[0] : e;
      var c = _clampToMapArea(container, startLeft + ev.clientX - startX, startTop + ev.clientY - startY);
      container.style.left = c[0] + 'px';
      container.style.top = c[1] + 'px';
    }
    function onEnd() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onEnd);
    }
    header.addEventListener('mousedown', onStart);
  }

  function _invoke(tool, args) {
    var projectGeneration = GIS.project && typeof GIS.project.getLoadGeneration === 'function'
      ? GIS.project.getLoadGeneration() : null;
    function projectChanged() {
      return projectGeneration !== null && GIS.project &&
        typeof GIS.project.getLoadGeneration === 'function' &&
        GIS.project.getLoadGeneration() !== projectGeneration;
    }
    var resultEl = document.getElementById('rtResult');
    var resultBody = document.getElementById('rtResultBody');
    resultEl.style.display = 'none';
    resultBody.textContent = '计算中...';
    resultEl.style.display = '';
    if (GIS.workspace) { GIS.workspace.toolPending('rasterToolsPanel'); resultEl.style.display='none'; }
    var layerNames = Object.keys(args || {})
      .filter(function (k) { return /layer/.test(k) && typeof args[k] === 'string'; })
      .map(function (k) { return args[k]; });
    var syncP = (GIS.api && GIS.api.syncLayer)
      ? Promise.all(layerNames.map(function (n) { return GIS.api.syncLayer(n); }))
      : Promise.resolve();
    syncP.then(function () {
      if (projectChanged()) throw new Error('工程已切换，旧工程工具结果未执行');
      if (!(GIS.api && GIS.api.invokeTool)) throw new Error('GIS.api.invokeTool 不可用');
      return GIS.api.invokeTool(tool, args);
    }).then(function (result) {
      if (projectChanged()) throw new Error('工程已切换，旧工程工具结果未应用');
      if (GIS.workspace && !GIS.workspace.toolFeedback('rasterToolsPanel', result)) return;
      if (GIS.chat && GIS.chat.applyToolResult) GIS.chat.applyToolResult(result);
      var parameterWarnings = Array.isArray(result.param_warnings) ? result.param_warnings.map(String).filter(Boolean) : [];
      resultBody.textContent = [result.response || '', parameterWarnings.length ? '参数提示：' + parameterWarnings.join('；') : ''].filter(Boolean).join('\n\n');
    }).catch(function (err) {
      if (GIS.workspace) GIS.workspace.toolFeedback('rasterToolsPanel', null, err);
      resultBody.textContent = '执行失败: ' + err.message;
    });
  }

  function _run() {
    var op = _opById(document.getElementById('rtOp').value);
    if (!op) return;
    if (op.id === 'coord') {
      var coords = document.getElementById('rtCoords').value.trim();
      if (!coords) { alert('请输入坐标'); return; }
      return _invoke(op.tool, {
        coords: coords,
        source_crs: document.getElementById('rtSrcCrs').value,
        target_crs: document.getElementById('rtDstCrs').value,
      });
    }
    if (op.id === 'geocode') {
      // 坐标转地址：reverse_geocode(lng, lat)，与坐标转换一样无需图层
      var graw = document.getElementById('rtCoords').value.trim();
      if (!graw) { alert('请输入坐标，格式：经度,纬度（如 112.94,28.23）'); return; }
      var parts = graw.split(/[,，;；\s]+/);
      var lng = parseFloat(parts[0]), lat = parseFloat(parts[1]);
      if (!isFinite(lng) || !isFinite(lat)) { alert('坐标格式不对，应为 经度,纬度（如 112.94,28.23）'); return; }
      return _invoke(op.tool, { lng: lng, lat: lat });
    }
    // 栅格类：选择器优先，手输名兜底
    var layerName = document.getElementById('rtLayer').value ||
      document.getElementById('rtLayerText').value.trim();
    if (!layerName) { alert('请选择图层或输入栅格文件名'); return; }
    var args = { layer_name: layerName };
    if (op.id === 'contour') args.interval = parseFloat(document.getElementById('rtInterval').value) || 0;
    if (op.id === 'ndvi') {
      args.red_band = parseInt(document.getElementById('rtRed').value, 10) || 3;
      args.nir_band = parseInt(document.getElementById('rtNir').value, 10) || 4;
    }
    if (op.id === 'rastercalc') {
      var expr = document.getElementById('rtExpression').value.trim();
      if (!expr) { alert('请输入表达式，如 B1*2-B2'); return; }
      args.expression = expr;
    }
    if (op.id === 'interpolate') {
      var field = document.getElementById('rtFieldSel').value;
      if (!field) { alert('请选择插值字段'); return; }
      args.field = field;
      args.method = document.getElementById('rtMethod').value;
    }
    if (op.id === 'hydrology') args.analysis = document.getElementById('rtHydroOp').value;
    if (op.id === 'heatmap') args.weight_field = document.getElementById('rtWeightSel').value || '';
    if (op.id === 'split') {
      var f = document.getElementById('rtFieldSel').value;
      if (!f) { alert('请选择拆分字段'); return; }
      args.by_field = f;
    }
    var finalArgs = {};
    Object.keys(op.args).forEach(function (k) { finalArgs[k] = op.args[k]; });
    Object.keys(args).forEach(function (k) { finalArgs[k] = args[k]; });
    return _invoke(op.tool, finalArgs);
  }

  GIS.rasterTools = { openWith: openWith };
})();
