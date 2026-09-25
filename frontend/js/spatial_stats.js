// ============================================================
// spatial_stats.js — 空间统计快捷面板
// 顶栏「工具 → 空间统计」入口，组装自然语言发给 AI 执行
// 方法：Moran's I 全局/局部自相关、Getis-Ord Gi* 热点、KDE 核密度
// ============================================================
window.GIS = window.GIS || {};

(function () {
  'use strict';

  var GIS = window.GIS;
  var _active = false;
  var _initialized = false;

  var PANEL_HTML =
    '<div class="spatial-panel" id="spatialStatsPanel">' +
      '<div class="spatial-loader" id="ssLoader" style="display:none">' +
        '<div class="spatial-spinner"></div>' +
        '<span>计算中...</span>' +
      '</div>' +
      '<div class="spatial-toolbar" id="spatialStatsToolbar">' +
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-5"/></svg>' +
        '<span class="spatial-toolbar-title">空间统计</span>' +
        '<button class="spatial-toolbar-close" id="spatialStatsClose">' +
          '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +

      '<div class="spatial-tabs" id="spatialStatsTabs">' +
        '<button class="spatial-tab active" data-tab="moran">自相关</button>' +
        '<button class="spatial-tab" data-tab="hotspot">热点</button>' +
        '<button class="spatial-tab" data-tab="kde">密度</button>' +
      '</div>' +

      '<div class="spatial-body" id="spatialStatsBody">' +

        /* ===== Moran's I 自相关 ===== */
        '<div class="spatial-tab-content active" id="stabMoran">' +
          '<div class="spatial-field">' +
            '<label>图层</label>' +
            '<select id="ssMoranLayer"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>分析字段（数值）</label>' +
            '<select id="ssMoranField"><option value="">-- 自动选择第一个数值字段 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>空间权重</label>' +
            '<select id="ssMoranWeight">' +
              '<option value="distance">距离权重</option>' +
              '<option value="knn">K近邻权重</option>' +
            '</select>' +
          '</div>' +
          '<div class="spatial-field" id="ssMoranDistField">' +
            '<label>距离阈值（米）</label>' +
            '<input type="number" id="ssMoranDist" class="spatial-input" value="1000" min="1" step="100">' +
          '</div>' +
          '<div class="spatial-field" id="ssMoranKnnField" style="display:none;">' +
            '<label>K近邻数</label>' +
            '<input type="number" id="ssMoranK" class="spatial-input" value="5" min="1" max="50">' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label class="spatial-checkbox-label">' +
              '<input type="checkbox" id="ssMoranLocal" checked> 同时计算局部 LISA（HH/HL/LH/LL 聚类图）' +
            '</label>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="moran">运行 Moran\'s I 分析</button>' +
        '</div>' +

        /* ===== Getis-Ord Gi* 热点 ===== */
        '<div class="spatial-tab-content" id="stabHotspot">' +
          '<div class="spatial-field">' +
            '<label>图层</label>' +
            '<select id="ssHotspotLayer"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>分析字段（数值）</label>' +
            '<select id="ssHotspotField"><option value="">-- 自动选择第一个数值字段 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>距离阈值（米）</label>' +
            '<input type="number" id="ssHotspotDist" class="spatial-input" value="1000" min="1" step="100">' +
          '</div>' +

          '<button class="spatial-run-btn" data-op="hotspot">运行热点分析（Gi*）</button>' +
        '</div>' +

        /* ===== KDE 核密度 ===== */
        '<div class="spatial-tab-content" id="stabKde">' +
          '<div class="spatial-field">' +
            '<label>图层</label>' +
            '<select id="ssKdeLayer"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>带宽（米，自动换算为度；留空自动估算）</label>' +
            '<input type="number" id="ssKdeBandwidth" class="spatial-input" placeholder="自动" min="1" step="100">' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>网格分辨率</label>' +
            '<select id="ssKdeGrid">' +
              '<option value="80">精细（80×80，较慢）</option>' +
              '<option value="50" selected>标准（50×50）</option>' +
              '<option value="30">粗略（30×30，快）</option>' +
            '</select>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="kde">运行核密度估计</button>' +
        '</div>' +

      '</div>' +
    '</div>';

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

    document.getElementById('spatialStatsClose').addEventListener('click', deactivate);

    // 标签切换
    document.getElementById('spatialStatsTabs').addEventListener('click', function (e) {
      var btn = e.target.closest('.spatial-tab');
      if (!btn) return;
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
        _runOperation(this.dataset.op);
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

  function _centerPanel(container) {
    container.style.position = 'fixed';
    container.style.left = '50%';
    container.style.top = '50%';
    container.style.transform = 'translate(-50%, -50%)';
    container.style.zIndex = '1100';
  }

  function activate() {
    if (_active) return;
    init();
    var container = document.getElementById('spatialStatsPanelContainer');
    if (!container) return;
    container.style.display = '';
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
      sel.innerHTML = '<option value="">-- 请选择图层 --</option>';
      layers.forEach(function (l) {
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
    function update() {
      var name = layerSel.value;
      fieldSel.innerHTML = '<option value="">-- 自动选择第一个数值字段 --</option>';
      if (!name || !GIS.layers || !GIS.layers.getLayerByName) return;
      var layer = GIS.layers.getLayerByName(name);
      if (!layer || !layer.geojson || !layer.geojson.features) return;
      var props = layer.geojson.features[0] ? layer.geojson.features[0].properties : {};
      Object.keys(props).forEach(function (k) {
        if (typeof props[k] === 'number') {
          var opt = document.createElement('option');
          opt.value = k;
          opt.textContent = k;
          fieldSel.appendChild(opt);
        }
      });
    }
    layerSel.removeEventListener('change', update);
    layerSel.addEventListener('change', update);
    update();
  }

  /** 直连执行：调后端工具 → 结果上图 + 面板展示文本（不经 AI） */
  var METERS_PER_DEGREE = 111320;

  function _invoke(tool, args) {
    var loader = document.getElementById('ssLoader');
    if (loader) loader.style.display = '';
    var syncP = (GIS.api && GIS.api.syncLayer && args.layer_name)
      ? GIS.api.syncLayer(args.layer_name) : Promise.resolve();
    var p = syncP.then(function() {
      if (!(GIS.api && GIS.api.invokeTool)) throw new Error('GIS.api.invokeTool 不可用');
      return GIS.api.invokeTool(tool, args);
    });
    p.then(function(result) {
      if (loader) loader.style.display = 'none';
      if (GIS.chat && GIS.chat.applyToolResult) GIS.chat.applyToolResult(result);
      // 统计解读直接展示到聊天区（系统消息），图层已上图
      if (GIS.chat && GIS.chat.addMessage && result.response) {
        GIS.chat.addMessage('【' + tool + '】' + result.response, 'system');
      }
    }).catch(function(err) {
      if (loader) loader.style.display = 'none';
      alert('执行失败: ' + err.message);
    });
  }

  function _runOperation(op) {
    if (op === 'moran') {
      var layer = document.getElementById('ssMoranLayer').value;
      if (!layer) { alert('请选择图层'); return; }
      var field = document.getElementById('ssMoranField').value;
      var weight = document.getElementById('ssMoranWeight').value;
      var local = document.getElementById('ssMoranLocal').checked;
      var args = { layer_name: layer, field: field || '', weight_type: weight, local: local };
      if (weight === 'distance') {
        var dist = parseFloat(document.getElementById('ssMoranDist').value) || 1000;
        args.threshold = +(dist / METERS_PER_DEGREE).toFixed(6);  // 米 → 度
      } else {
        args.k = parseInt(document.getElementById('ssMoranK').value, 10) || 5;
      }
      deactivate();
      return _invoke('spatial_moran', args);
    }
    if (op === 'hotspot') {
      var layer2 = document.getElementById('ssHotspotLayer').value;
      if (!layer2) { alert('请选择图层'); return; }
      var field2 = document.getElementById('ssHotspotField').value;
      var dist2 = parseFloat(document.getElementById('ssHotspotDist').value) || 1000;
      deactivate();
      return _invoke('spatial_hotspot', {
        layer_name: layer2, field: field2 || '',
        threshold: +(dist2 / METERS_PER_DEGREE).toFixed(6),  // 米 → 度
      });
    }
    if (op === 'kde') {
      var layer3 = document.getElementById('ssKdeLayer').value;
      if (!layer3) { alert('请选择图层'); return; }
      var bw = parseFloat(document.getElementById('ssKdeBandwidth').value);
      var grid = parseInt(document.getElementById('ssKdeGrid').value, 10) || 50;
      var args3 = { layer_name: layer3, grid_size: grid };
      if (bw) args3.bandwidth = +(bw / METERS_PER_DEGREE).toFixed(6);  // 米 → 度
      deactivate();
      return _invoke('spatial_kde', args3);
    }
  }

  GIS.spatialStats = { init: init, activate: activate, deactivate: deactivate, toggle: toggle, refreshLayers: _refreshLayers };
})();
