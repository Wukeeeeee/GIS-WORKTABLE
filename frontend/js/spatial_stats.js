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
          '<div class="spatial-field">' +
            '<label>显著性水平</label>' +
            '<select id="ssHotspotSig">' +
              '<option value="0.05">0.05（95%）</option>' +
              '<option value="0.01">0.01（99%）</option>' +
              '<option value="0.001">0.001（99.9%）</option>' +
            '</select>' +
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
            '<label>带宽（米，留空自动估算）</label>' +
            '<input type="number" id="ssKdeBandwidth" class="spatial-input" placeholder="自动" min="1" step="100">' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>网格分辨率</label>' +
            '<select id="ssKdeGrid">' +
              '<option value="50">50m（精细）</option>' +
              '<option value="100" selected>100m（标准）</option>' +
              '<option value="200">200m（粗略）</option>' +
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

  // 组装自然语言发给 AI
  function _runOperation(op) {
    var msg = '';
    if (op === 'moran') {
      var layer = document.getElementById('ssMoranLayer').value;
      if (!layer) { alert('请选择图层'); return; }
      var field = document.getElementById('ssMoranField').value;
      var weight = document.getElementById('ssMoranWeight').value;
      var local = document.getElementById('ssMoranLocal').checked;
      if (weight === 'distance') {
        var dist = document.getElementById('ssMoranDist').value;
        msg = '对图层「' + layer + '」做 Moran\'s I 全局空间自相关分析' +
              (field ? '，字段「' + field + '」' : '') +
              '，使用距离权重（阈值 ' + dist + ' 米）' +
              (local ? '，同时计算局部 LISA 并生成 HH/HL/LH/LL 聚类图层' : '') +
              '，结果加载到地图并给出统计解读';
      } else {
        var k = document.getElementById('ssMoranK').value;
        msg = '对图层「' + layer + '」做 Moran\'s I 全局空间自相关分析' +
              (field ? '，字段「' + field + '」' : '') +
              '，使用 K近邻权重（K=' + k + '）' +
              (local ? '，同时计算局部 LISA 并生成 HH/HL/LH/LL 聚类图层' : '') +
              '，结果加载到地图并给出统计解读';
      }
    } else if (op === 'hotspot') {
      var layer2 = document.getElementById('ssHotspotLayer').value;
      if (!layer2) { alert('请选择图层'); return; }
      var field2 = document.getElementById('ssHotspotField').value;
      var dist2 = document.getElementById('ssHotspotDist').value;
      var sig = document.getElementById('ssHotspotSig').value;
      msg = '对图层「' + layer2 + '」做 Getis-Ord Gi* 热点分析' +
            (field2 ? '，字段「' + field2 + '」' : '') +
            '，距离阈值 ' + dist2 + ' 米，显著性水平 ' + sig +
            '，生成热点（红色）/冷点（蓝色）图层并给出统计解读';
    } else if (op === 'kde') {
      var layer3 = document.getElementById('ssKdeLayer').value;
      if (!layer3) { alert('请选择图层'); return; }
      var bw = document.getElementById('ssKdeBandwidth').value;
      var grid = document.getElementById('ssKdeGrid').value;
      msg = '对图层「' + layer3 + '」做核密度估计（KDE）' +
            (bw ? '，带宽 ' + bw + ' 米' : '，带宽自动估算') +
            '，网格分辨率 ' + grid + ' 米，生成密度格网图层并加载到地图';
    }
    if (msg) {
      deactivate();
      if (GIS.chat && GIS.chat.send) {
        GIS.chat.send(msg);
      }
    }
  }

  GIS.spatialStats = { init: init, activate: activate, deactivate: deactivate, toggle: toggle, refreshLayers: _refreshLayers };
})();
