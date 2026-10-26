// ============================================================
// spatial_stats.js — 空间统计快捷面板
// 顶栏「工具 → 空间统计」入口，直接调用本地后端工具
// 方法：Moran's I 全局/局部自相关、Getis-Ord Gi* 热点、KDE 核密度
// ============================================================
window.GIS = window.GIS || {};

(function () {
  'use strict';

  var GIS = window.GIS;
  var _active = false;
  var _initialized = false;
  var PANEL_WIDTH = 380;
  var _panelLeft = NaN, _panelTop = NaN;

  var PANEL_HTML =
    ("<div class=\"spatial-panel\" id=\"spatialStatsPanel\">"
      + "<div class=\"spatial-loader\" id=\"ssLoader\" style=\"display:none\">"
      + "<div class=\"spatial-spinner\">"
      + "</div>"
      + "<span data-i18n=\"spatial-stats.loading\">计算中..."
      + "</span>"
      + "</div>"
      + "<div class=\"spatial-toolbar\" id=\"spatialStatsToolbar\">"
      + "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:18px;height:18px;--ui-icon-image:url('/assets/ui-icons/icon-b5c56f814b9e.png')\">"
      + "</span>"
      + "<span class=\"spatial-toolbar-title\" data-i18n=\"spatial-stats.title\">空间统计"
      + "</span>"
      + "<button class=\"spatial-toolbar-close\" id=\"spatialStatsClose\" data-i18n-title=\"spatial-stats.close\">"
      + "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:16px;height:16px;--ui-icon-image:url('/assets/ui-icons/icon-28a441e0afbc.png')\">"
      + "</span>"
      + "</button>"
      + "</div>"
      + "<div class=\"spatial-tabs\" id=\"spatialStatsTabs\">"
      + "<button class=\"spatial-tab active\" data-tab=\"moran\" data-i18n=\"spatial-stats.tab-moran\">自相关"
      + "</button>"
      + "<button class=\"spatial-tab\" data-tab=\"hotspot\" data-i18n=\"spatial-stats.tab-hotspot\">热点"
      + "</button>"
      + "<button class=\"spatial-tab\" data-tab=\"kde\" data-i18n=\"spatial-stats.tab-kde\">密度"
      + "</button>"
      + "</div>"
      + "<div class=\"spatial-body\" id=\"spatialStatsBody\">"
      + "<div class=\"spatial-tab-content active\" id=\"stabMoran\">"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.layer\">图层"
      + "</label>"
      + "<select id=\"ssMoranLayer\">"
      + "<option value=\"\" data-i18n=\"spatial-stats.choose-layer\">-- 请选择图层 --"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.field\">分析字段（数值）"
      + "</label>"
      + "<select id=\"ssMoranField\">"
      + "<option value=\"\" data-i18n=\"spatial-stats.choose-field\">-- 自动选择第一个数值字段 --"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.weights\">空间权重"
      + "</label>"
      + "<select id=\"ssMoranWeight\">"
      + "<option value=\"distance\" data-i18n=\"spatial-stats.distance-weights\">距离权重"
      + "</option>"
      + "<option value=\"knn\" data-i18n=\"spatial-stats.knn-weights\">K近邻权重"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"ssMoranDistField\">"
      + "<label data-i18n=\"spatial-stats.distance-threshold\">距离阈值（米）"
      + "</label>"
      + "<input type=\"number\" id=\"ssMoranDist\" class=\"spatial-input\" value=\"1000\" min=\"1\" step=\"100\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"ssMoranKnnField\" style=\"display:none;\">"
      + "<label data-i18n=\"spatial-stats.knn-count\">K近邻数"
      + "</label>"
      + "<input type=\"number\" id=\"ssMoranK\" class=\"spatial-input\" value=\"5\" min=\"1\" max=\"50\">"
      + "</div>"
      + "<div class=\"spatial-field\">"
      + "<label class=\"spatial-checkbox-label\">"
      + "<input type=\"checkbox\" id=\"ssMoranLocal\" checked> <span data-i18n=\"spatial-stats.local-lisa\">同时计算局部 LISA（HH/HL/LH/LL 聚类图）</span>"
      + "</label>"
      + "</div>"
      + "<button class=\"spatial-run-btn\" data-op=\"moran\" data-i18n=\"spatial-stats.run-moran\">运行 Moran's I 分析"
      + "</button>"
      + "</div>"
      + "<div class=\"spatial-tab-content\" id=\"stabHotspot\">"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.layer\">图层"
      + "</label>"
      + "<select id=\"ssHotspotLayer\">"
      + "<option value=\"\" data-i18n=\"spatial-stats.choose-layer\">-- 请选择图层 --"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.field\">分析字段（数值）"
      + "</label>"
      + "<select id=\"ssHotspotField\">"
      + "<option value=\"\" data-i18n=\"spatial-stats.choose-field\">-- 自动选择第一个数值字段 --"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.distance-threshold\">距离阈值（米）"
      + "</label>"
      + "<input type=\"number\" id=\"ssHotspotDist\" class=\"spatial-input\" value=\"1000\" min=\"1\" step=\"100\">"
      + "</div>"
      + "<button class=\"spatial-run-btn\" data-op=\"hotspot\" data-i18n=\"spatial-stats.run-hotspot\">运行热点分析（Gi*）"
      + "</button>"
      + "</div>"
      + "<div class=\"spatial-tab-content\" id=\"stabKde\">"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.layer\">图层"
      + "</label>"
      + "<select id=\"ssKdeLayer\">"
      + "<option value=\"\" data-i18n=\"spatial-stats.choose-layer\">-- 请选择图层 --"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.bandwidth\">带宽（米，自动换算为度；留空自动估算）"
      + "</label>"
      + "<input type=\"number\" id=\"ssKdeBandwidth\" class=\"spatial-input\" placeholder=\"自动\" data-i18n-placeholder=\"spatial-stats.automatic\" min=\"1\" step=\"100\">"
      + "</div>"
      + "<div class=\"spatial-field\">"
      + "<label data-i18n=\"spatial-stats.grid-resolution\">网格分辨率"
      + "</label>"
      + "<select id=\"ssKdeGrid\">"
      + "<option value=\"80\" data-i18n=\"spatial-stats.grid-fine\">精细（80×80，较慢）"
      + "</option>"
      + "<option value=\"50\" selected data-i18n=\"spatial-stats.grid-standard\">标准（50×50）"
      + "</option>"
      + "<option value=\"30\" data-i18n=\"spatial-stats.grid-coarse\">粗略（30×30，快）"
      + "</option>"
      + "</select>"
      + "</div>"
      + "<button class=\"spatial-run-btn\" data-op=\"kde\" data-i18n=\"spatial-stats.run-kde\">运行核密度估计"
      + "</button>"
      + "</div>"
      + "</div>"
      + "</div>");

  function tr(key, fallback) {
    return GIS.i18n ? GIS.i18n.t(key, fallback) : fallback;
  }

  function init() {
    if (_initialized) return;

    var wrapper = document.getElementById('spatialStatsPanelWrapper');
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.id = 'spatialStatsPanelWrapper';
      document.documentElement.appendChild(wrapper);
    }
    var container = document.getElementById('spatialStatsPanelContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'spatialStatsPanelContainer';
      wrapper.appendChild(container);
    }
    container.innerHTML = PANEL_HTML;
    _centerPanel(container);
    _initDrag(container);

    document.getElementById('spatialStatsClose').addEventListener('click', deactivate);
    if (GIS.workspace) GIS.workspace.preparePanel('spatialStatsPanel', 'spatialStatsToolbar', 'spatialStatsClose', '空间统计');
    if (GIS.i18n) GIS.i18n.translate(container);

    // 标签切换
    document.getElementById('spatialStatsTabs').addEventListener('click', function (e) {
      var btn = e.target.closest('.spatial-tab');
      if (!btn) return;
      _refreshLayers();
      _switchTab(btn.dataset.tab);
    });

    // 权重类型切换显示
    document.getElementById('ssMoranWeight').addEventListener('change', function () {
      var isDist = this.value === 'distance';
      document.getElementById('ssMoranDistField').style.display = isDist ? '' : 'none';
      document.getElementById('ssMoranKnnField').style.display = isDist ? 'none' : '';
    });

    // 运行按钮
    container.querySelectorAll('.spatial-run-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        return _runOperation(this.dataset.op, this);
      });
    });

    _initialized = true;
  }

  function _switchTab(tab) {
    var tabs = document.querySelectorAll('#spatialStatsTabs .spatial-tab');
    tabs.forEach(function (t) { t.classList.toggle('active', t.dataset.tab === tab); });
    var contents = document.querySelectorAll('#spatialStatsBody .spatial-tab-content');
    contents.forEach(function (c) { c.classList.toggle('active', c.id === 'stab' + tab.charAt(0).toUpperCase() + tab.slice(1)); });
  }

  function _chatRightEdge() {
    var chatPanel = document.querySelector('.chat-panel');
    if (!chatPanel) return 0;
    var r = chatPanel.getBoundingClientRect();
    return (r.width > 0 ? r.right : 0) + 4;
  }

  function _clampToMapArea(container, left, top) {
    if (GIS.workspace) return GIS.workspace.clampPanel(container, left, top, PANEL_WIDTH);
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var minLeft = _chatRightEdge();
    var w = container.offsetWidth || PANEL_WIDTH;
    var h = container.offsetHeight || 300;
    left = Math.max(minLeft, Math.min(vw - w - 10, left));
    top = Math.max(34, Math.min(vh - h - 10, top));
    return [left, top];
  }

  function _centerPanel(container) {
    container.style.position = 'fixed';
    container.style.zIndex = '1100';
    if (!isNaN(_panelLeft) && !isNaN(_panelTop)) {
      var clamped = _clampToMapArea(container, _panelLeft, _panelTop);
      _panelLeft = clamped[0]; _panelTop = clamped[1];
      container.style.left = _panelLeft + 'px';
      container.style.top = _panelTop + 'px';
      container.style.transform = 'none';
      return;
    }
    if (GIS.workspace) {
      var pos = GIS.workspace.centerPanel(container, PANEL_WIDTH);
      _panelLeft = pos[0]; _panelTop = pos[1];
      return;
    }
    var vw = window.innerWidth;
    var chatRight = _chatRightEdge();
    var mapAreaWidth = vw - chatRight;
    var coords = _clampToMapArea(container,
      Math.round(chatRight + (mapAreaWidth - PANEL_WIDTH) / 2), 80);
    _panelLeft = coords[0];
    _panelTop = coords[1];
    container.style.left = _panelLeft + 'px';
    container.style.top = _panelTop + 'px';
    container.style.transform = 'none';
  }

  function _initDrag(container) {
    var header = document.getElementById('spatialStatsToolbar');
    if (!header) return;
    var startX, startY, startLeft, startTop;

    function onStart(e) {
      if (e.target.closest('button')) return;
      var ev = e.touches ? e.touches[0] : e;
      startX = ev.clientX;
      startY = ev.clientY;
      var currentRect = container.getBoundingClientRect();
      startLeft = currentRect.left;
      startTop = currentRect.top;
      container.classList.add('dragging');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onEnd);
      document.addEventListener('touchmove', onMove, {passive: false});
      document.addEventListener('touchend', onEnd);
    }

    function onMove(e) {
      var ev = e.touches ? e.touches[0] : e;
      var dx = ev.clientX - startX;
      var dy = ev.clientY - startY;
      var clamped = _clampToMapArea(container, startLeft + dx, startTop + dy);
      container.style.left = clamped[0] + 'px';
      container.style.top = clamped[1] + 'px';
      _panelLeft = clamped[0];
      _panelTop = clamped[1];
    }

    function onEnd() {
      container.classList.remove('dragging');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onEnd);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onEnd);
    }

    header.addEventListener('mousedown', onStart);
    header.addEventListener('touchstart', onStart, {passive: true});
  }

  function activate() {
    if (_active) return;
    init();
    var container = document.getElementById('spatialStatsPanelContainer');
    if (!container) return;
    container.style.display = '';
    if (GIS.workspace) GIS.workspace.expandPanel('spatialStatsPanel');
    _centerPanel(container);
    _refreshLayers();
    _active = true;
  }

  function deactivate() {
    _active = false;
    var container = document.getElementById('spatialStatsPanelContainer');
    if (container) container.style.display = 'none';
  }

  function toggle() {
    if (_active) { deactivate(); } else { activate(); }
  }

  // 刷新所有图层下拉框
  function _refreshLayers() {
    var layers = (GIS.layers && GIS.layers.getLayers) ? GIS.layers.getLayers() : [];
    var selects = ['ssMoranLayer', 'ssHotspotLayer', 'ssKdeLayer'];
    selects.forEach(function (id) {
      var sel = document.getElementById(id);
      if (!sel) return;
      var cur = sel.value;
      sel.innerHTML = '<option value="" data-i18n="spatial-stats.choose-layer">-- 请选择图层 --</option>';
      if (GIS.i18n) GIS.i18n.translate(sel);
      layers.filter(function(l) { return l.geojson && !l.raster; }).forEach(function (l) {
        var opt = document.createElement('option');
        opt.value = l.filename || l.layer_id;
        opt.textContent = l.filename || l.layer_id;
        sel.appendChild(opt);
      });
      if (cur) sel.value = cur;
    });
    // 字段下拉（监听图层变化）
    _bindFieldRefresh('ssMoranLayer', 'ssMoranField');
    _bindFieldRefresh('ssHotspotLayer', 'ssHotspotField');
  }

  function _bindFieldRefresh(layerId, fieldId) {
    var layerSel = document.getElementById(layerId);
    var fieldSel = document.getElementById(fieldId);
    if (!layerSel || !fieldSel) return;
    if (layerSel._spatialStatsFieldRefreshHandler) {
      layerSel.removeEventListener('change', layerSel._spatialStatsFieldRefreshHandler);
    }
    function update() {
      var name = layerSel.value;
      var currentField = fieldSel.value;
      fieldSel.innerHTML = '<option value="" data-i18n="spatial-stats.choose-field">-- 自动选择第一个数值字段 --</option>';
      if (GIS.i18n) GIS.i18n.translate(fieldSel);
      if (!name || !GIS.layers || !GIS.layers.getLayerByName) return;
      var layer = GIS.layers.getLayerByName(name);
      if (!layer || !layer.geojson) return;
      var features = layer.geojson.type === 'Feature' ? [layer.geojson] : layer.geojson.features;
      if (!Array.isArray(features)) return;
      var numericFields = new Set();
      features.forEach(function (feature) {
        var props = feature && feature.properties || {};
        Object.keys(props).forEach(function (key) {
          if (typeof props[key] === 'number' && Number.isFinite(props[key])) numericFields.add(key);
        });
      });
      numericFields.forEach(function (k) {
        var opt = document.createElement('option');
        opt.value = k;
        opt.textContent = k;
        if (k === currentField) opt.selected = true;
        fieldSel.appendChild(opt);
      });
    }
    layerSel._spatialStatsFieldRefreshHandler = update;
    layerSel.addEventListener('change', update);
    update();
  }

  /** 直连执行：调后端工具 → 结果上图 + 面板展示文本（不经 AI） */
  function _invoke(tool, args, runButton) {
    var loader = document.getElementById('ssLoader');
    if (loader) loader.style.display = 'flex';
    if (GIS.workspace) GIS.workspace.toolPending('spatialStatsPanel', runButton);
    var syncP = (GIS.api && GIS.api.syncLayer && args.layer_name)
      ? GIS.api.syncLayer(args.layer_name) : Promise.resolve();
    var p = syncP.then(function() {
      if (!(GIS.api && GIS.api.invokeTool)) throw new Error(tr('spatial-stats.error.execute', '执行失败: ') + 'GIS.api.invokeTool 不可用');
      return GIS.api.invokeTool(tool, args);
    });
    return p.then(function(result) {
      if (loader) loader.style.display = 'none';
      if (GIS.workspace && !GIS.workspace.toolFeedback('spatialStatsPanel', result)) return;
      if (GIS.chat && GIS.chat.applyToolResult) GIS.chat.applyToolResult(result);
      // 统计解读直接展示到聊天区（系统消息），图层已上图
      if (GIS.chat && GIS.chat.addMessage && result.response) {
        GIS.chat.addMessage('【' + tool + '】' + result.response, 'system');
      }
    }).catch(function(err) {
      if (loader) loader.style.display = 'none';
      if (GIS.workspace) GIS.workspace.toolFeedback('spatialStatsPanel', null, err);
      else alert(tr('spatial-stats.error.execute', '执行失败: ') + err.message);
    });
  }

  function _runOperation(op, runButton) {
    if (op === 'moran') {
      var layer = document.getElementById('ssMoranLayer').value;
      if (!layer) { alert(tr('spatial-stats.error.select-layer', '请选择图层')); return; }
      var field = document.getElementById('ssMoranField').value;
      var weight = document.getElementById('ssMoranWeight').value;
      var local = document.getElementById('ssMoranLocal').checked;
      var args = { layer_name: layer, field: field || '', weight_type: weight, local: local };
      if (weight === 'distance') {
        var dist = Number(document.getElementById('ssMoranDist').value);
        if (!Number.isFinite(dist) || dist <= 0) { alert(tr('spatial-stats.error.distance-positive', '距离阈值必须是大于 0 的有限数值')); return; }
        args.threshold_m = dist;
      } else {
        var k = Number(document.getElementById('ssMoranK').value);
        if (!Number.isInteger(k) || k < 1 || k > 50) { alert(tr('spatial-stats.error.knn-range', 'K 近邻数必须是 1 到 50 之间的整数')); return; }
        args.k = k;
      }
      return _invoke('spatial_moran', args, runButton);
    }
    if (op === 'hotspot') {
      var layer2 = document.getElementById('ssHotspotLayer').value;
      if (!layer2) { alert(tr('spatial-stats.error.select-layer', '请选择图层')); return; }
      var field2 = document.getElementById('ssHotspotField').value;
      var dist2 = Number(document.getElementById('ssHotspotDist').value);
      if (!Number.isFinite(dist2) || dist2 <= 0) { alert(tr('spatial-stats.error.distance-positive', '距离阈值必须是大于 0 的有限数值')); return; }
      return _invoke('spatial_hotspot', {
        layer_name: layer2, field: field2 || '',
        threshold_m: dist2,
      }, runButton);
    }
    if (op === 'kde') {
      var layer3 = document.getElementById('ssKdeLayer').value;
      if (!layer3) { alert(tr('spatial-stats.error.select-layer', '请选择图层')); return; }
      var bwText = document.getElementById('ssKdeBandwidth').value.trim();
      var bw = bwText ? Number(bwText) : 0;
      if (bwText && (!Number.isFinite(bw) || bw <= 0)) { alert(tr('spatial-stats.error.bandwidth-positive', '带宽必须是大于 0 的有限数值，或留空自动估算')); return; }
      var grid = Number(document.getElementById('ssKdeGrid').value);
      if (!Number.isInteger(grid) || grid < 10 || grid > 200) { alert(tr('spatial-stats.error.grid-range', '网格分辨率必须是 10 到 200 之间的整数')); return; }
      var args3 = { layer_name: layer3, grid_size: grid, bandwidth_m: bw, metric_units: true };
      return _invoke('spatial_kde', args3, runButton);
    }
  }

  GIS.spatialStats = { toggle: toggle };
})();
