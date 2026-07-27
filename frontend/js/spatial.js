window.GIS = window.GIS || {};

(function() {
  'use strict';

  var GIS = window.GIS;
  var _active = false;
  var _initialized = false;
  var _panelLeft = NaN;
  var _panelTop = NaN;
  var PANEL_WIDTH = 300;

  var PANEL_HTML =
    '<div class="spatial-panel" id="spatialPanel">' +

      '<div class="spatial-toolbar" id="spatialToolbar">' +
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v4"/><path d="M12 18v4"/><path d="M2 12h4"/><path d="M18 12h4"/></svg>' +
        '<span class="spatial-toolbar-title">空间分析</span>' +
        '<button class="spatial-toolbar-close" id="spatialClose">' +
          '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +

      '<div class="spatial-tabs" id="spatialTabs">' +
        '<button class="spatial-tab active" data-tab="buffer">缓冲区</button>' +
        '<button class="spatial-tab" data-tab="overlay">叠置</button>' +
        '<button class="spatial-tab" data-tab="clip">裁剪</button>' +
        '<button class="spatial-tab" data-tab="tools">工具</button>' +
      '</div>' +

      '<div class="spatial-body" id="spatialBody">' +

        /* ===== 缓冲区标签 ===== */
        '<div class="spatial-tab-content active" id="tabBuffer">' +
          '<div class="spatial-field">' +
            '<label>图层</label>' +
            '<select id="bufferLayer"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>距离</label>' +
            '<div class="spatial-row">' +
              '<input type="number" id="bufferDistance" class="spatial-input" value="500" min="0" step="10">' +
              '<select id="bufferUnit" class="spatial-select-short">' +
                '<option value="m">米</option>' +
                '<option value="km">公里</option>' +
              '</select>' +
            '</div>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label class="spatial-checkbox-label">' +
              '<input type="checkbox" id="bufferDissolve"> 融合重叠区域' +
            '</label>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="buffer">运行缓冲区</button>' +
        '</div>' +

        /* ===== 叠置标签 ===== */
        '<div class="spatial-tab-content" id="tabOverlay">' +
          '<div class="spatial-field">' +
            '<label>操作</label>' +
            '<select id="overlayOp">' +
              '<option value="intersect">相交（保留重叠）</option>' +
              '<option value="union">合并（保留全部）</option>' +
              '<option value="difference">差异（A 减 B）</option>' +
            '</select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>图层 A</label>' +
            '<select id="overlayLayerA"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>图层 B</label>' +
            '<select id="overlayLayerB"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="overlay">运行叠置分析</button>' +
        '</div>' +

        /* ===== 裁剪标签 ===== */
        '<div class="spatial-tab-content" id="tabClip">' +
          '<div class="spatial-field">' +
            '<label>被裁剪图层</label>' +
            '<select id="clipLayer"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>裁剪边界</label>' +
            '<select id="clipByLayer"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="clip">运行裁剪</button>' +
        '</div>' +

        /* ===== 工具标签 ===== */
        '<div class="spatial-tab-content" id="tabTools">' +
          '<div class="spatial-field">' +
            '<label>图层</label>' +
            '<select id="toolsLayer"><option value="">-- 请选择图层 --</option></select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>操作</label>' +
            '<select id="toolsOp">' +
              '<option value="centroid">提取质心</option>' +
              '<option value="simplify">简化几何</option>' +
              '<option value="dissolve">属性融合</option>' +
            '</select>' +
          '</div>' +
          '<div class="spatial-field" id="toolsSimplifyField" style="display:none">' +
            '<label>简化容差（度）</label>' +
            '<input type="number" id="toolsSimplifyTolerance" class="spatial-input" value="0.001" min="0.0001" step="0.0001">' +
          '</div>' +
          '<div class="spatial-field" id="toolsDissolveField" style="display:none">' +
            '<label>融合字段</label>' +
            '<select id="toolsDissolveField"><option value="">-- 全部融合 --</option></select>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="tools">运行</button>' +
        '</div>' +

      '</div>' +

      '<div class="spatial-result" id="spatialResult" style="display:none">' +
        '<div class="spatial-result-body" id="spatialResultBody"></div>' +
      '</div>' +

      '<div class="spatial-loader" id="spatialLoader" style="display:none">' +
        '<div class="spatial-spinner"></div>' +
        '<span>分析中...</span>' +
      '</div>' +
    '</div>';


  function init() {
    if (_initialized) return;

    var wrapper = document.getElementById('spatialPanelWrapper');
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.id = 'spatialPanelWrapper';
      document.documentElement.appendChild(wrapper);
    }
    var container = document.getElementById('spatialPanelContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'spatialPanelContainer';
      wrapper.appendChild(container);
    } else if (container.parentNode !== wrapper) {
      wrapper.appendChild(container);
    }
    container.innerHTML = PANEL_HTML;

    _centerPanel(container);
    _initDrag(container);

    document.getElementById('spatialClose').addEventListener('click', deactivate);

    document.getElementById('spatialTabs').addEventListener('click', function(e) {
      var btn = e.target.closest('.spatial-tab');
      if (!btn) return;
      _switchTab(btn.dataset.tab);
    });

    document.getElementById('toolsOp').addEventListener('change', function() {
      var val = this.value;
      document.getElementById('toolsSimplifyField').style.display = val === 'simplify' ? '' : 'none';
      document.getElementById('toolsDissolveField').style.display = val === 'dissolve' ? '' : 'none';
    });

    document.querySelectorAll('.spatial-run-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        _runOperation(this.dataset.op);
      });
    });

    _initialized = true;
  }


  function activate() {
    if (_active) return;
    init();
    var container = document.getElementById('spatialPanelContainer');
    if (!container) return;
    container.style.display = '';
    _refreshLayers();
    _centerPanel(container);
    _active = true;
  }


  function deactivate() {
    _active = false;
    var container = document.getElementById('spatialPanelContainer');
    if (container) container.style.display = 'none';
  }


  function toggle() {
    if (_active) { deactivate(); }
    else { activate(); }
  }


  function _centerPanel(container) {
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var chatPanel = document.querySelector('.chat-panel');
    var chatRight = chatPanel ? chatPanel.offsetWidth + 4 : 0;
    var mapAreaWidth = vw - chatRight;
    _panelLeft = Math.round(chatRight + (mapAreaWidth - PANEL_WIDTH) / 2);
    _panelTop = 80;
    container.style.left = _panelLeft + 'px';
    container.style.top = _panelTop + 'px';
    container.style.transform = 'none';
  }


  function _initDrag(container) {
    var header = document.getElementById('spatialToolbar');
    if (!header) return;
    var startX, startY, startLeft, startTop;

    function onStart(e) {
      if (e.target.closest('.spatial-toolbar-close')) return;
      var ev = e.touches ? e.touches[0] : e;
      startX = ev.clientX;
      startY = ev.clientY;
      startLeft = _panelLeft;
      startTop = _panelTop;
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
      var left = startLeft + dx;
      var top = startTop + dy;
      var vw = window.innerWidth;
      var vh = window.innerHeight;
      var chatPanel = document.querySelector('.chat-panel');
      var chatRight = chatPanel ? chatPanel.offsetWidth + 4 : 0;
      left = Math.max(chatRight, Math.min(vw - 10, left));
      top = Math.max(34, Math.min(vh - 10, top));
      container.style.left = left + 'px';
      container.style.top = top + 'px';
      _panelLeft = left;
      _panelTop = top;
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


  function _switchTab(tab) {
    document.querySelectorAll('.spatial-tab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.spatial-tab-content').forEach(function(c) {
      c.classList.toggle('active', c.id === 'tab' + tab.charAt(0).toUpperCase() + tab.slice(1));
    });
    document.getElementById('spatialResult').style.display = 'none';
  }


  function _refreshLayers() {
    var layerNames = [];
    if (GIS.layers && GIS.layers.getLayerNames) {
      layerNames = GIS.layers.getLayerNames();
    } else {
      var data = window._layerData || [];
      layerNames = data.map(function(l) { return l.name; });
    }

    var selects = [
      'bufferLayer', 'overlayLayerA', 'overlayLayerB',
      'clipLayer', 'clipByLayer', 'toolsLayer'
    ];

    selects.forEach(function(id) {
      var sel = document.getElementById(id);
      if (!sel) return;
      var current = sel.value;
      sel.innerHTML = '<option value="">-- 请选择图层 --</option>';
      layerNames.forEach(function(n) {
        var opt = document.createElement('option');
        opt.value = n;
        opt.textContent = n;
        if (n === current) opt.selected = true;
        sel.appendChild(opt);
      });
    });

    _refreshDissolveFields();
  }


  function _refreshDissolveFields() {
    var sel = document.getElementById('toolsLayer');
    var fieldSel = document.getElementById('toolsDissolveField');
    if (!sel || !fieldSel) return;
    var layerName = sel.value;
    fieldSel.innerHTML = '<option value="">-- 全部融合 --</option>';
    if (!layerName || !GIS.layers) return;
    var info = GIS.layers.getLayerInfo ? GIS.layers.getLayerInfo(layerName) : null;
    if (!info && window._layerData) {
      info = window._layerData.find(function(l) { return l.name === layerName; });
    }
    if (!info || !info.properties) return;
    Object.keys(info.properties).forEach(function(key) {
      if (key === 'geometry') return;
      var opt = document.createElement('option');
      opt.value = key;
      opt.textContent = key;
      fieldSel.appendChild(opt);
    });
  }


  function _runOperation(op) {
    var resultEl = document.getElementById('spatialResult');
    var resultBody = document.getElementById('spatialResultBody');
    var loader = document.getElementById('spatialLoader');
    resultEl.style.display = 'none';
    loader.style.display = '';

    var msg = '';
    var skill = 'geometry';

    if (op === 'buffer') {
      var layer = document.getElementById('bufferLayer').value;
      var dist = document.getElementById('bufferDistance').value;
      var unit = document.getElementById('bufferUnit').value;
      var dissolve = document.getElementById('bufferDissolve').checked;
      skill = 'geometry';
      msg = '对图层「' + layer + '」做 ' + dist + ' ' + unit + ' 的缓冲区分析' +
            (dissolve ? '，融合重叠区域' : '') + '，结果加载到地图上';
    } else if (op === 'overlay') {
      var opType = document.getElementById('overlayOp').value;
      var layerA = document.getElementById('overlayLayerA').value;
      var layerB = document.getElementById('overlayLayerB').value;
      var opLabel = { intersect: '空间相交', union: '空间合并', difference: '空间差异' };
      skill = 'geometry';
      msg = '对图层「' + layerA + '」和「' + layerB + '」做' + opLabel[opType] + '分析，结果加载到地图上';
    } else if (op === 'clip') {
      var clipLayer = document.getElementById('clipLayer').value;
      var clipBy = document.getElementById('clipByLayer').value;
      skill = 'geometry';
      msg = '用图层「' + clipBy + '」裁剪图层「' + clipLayer + '」，结果加载到地图上';
    } else if (op === 'tools') {
      var toolsLayer = document.getElementById('toolsLayer').value;
      var toolsOp = document.getElementById('toolsOp').value;
      skill = 'geometry';
      if (toolsOp === 'centroid') {
        msg = '提取图层「' + toolsLayer + '」的质心，结果加载到地图上';
      } else if (toolsOp === 'simplify') {
        var tol = document.getElementById('toolsSimplifyTolerance').value;
        msg = '简化图层「' + toolsLayer + '」的几何，容差设为 ' + tol + '，结果加载到地图上';
      } else if (toolsOp === 'dissolve') {
        var field = document.getElementById('toolsDissolveField').value;
        if (field) {
          msg = '按字段「' + field + '」融合图层「' + toolsLayer + '」，结果加载到地图上';
        } else {
          msg = '融合图层「' + toolsLayer + '」的全部要素，结果加载到地图上';
        }
      }
    }

    loader.style.display = 'none';
    if (!msg) { return; }

    if (GIS.chat && GIS.chat.send) {
      GIS.chat.send(msg);
      deactivate();
    }
  }


  GIS.spatial = {
    init: init,
    activate: activate,
    deactivate: deactivate,
    toggle: toggle,
  };

})();
