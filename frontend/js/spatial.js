window.GIS = window.GIS || {};

/**
 * spatial.js — 空间分析面板（手动直连版）
 * 所有操作经 POST /api/tools/invoke 直接调用后端 @tool 注册工具，
 * 不经 LLM：无 Key 可用、结果确定、自动进处理历史（可重跑）。
 */
(function() {
  'use strict';

  var GIS = window.GIS;
  var _active = false;
  var _initialized = false;
  var _panelLeft = NaN;
  var _panelTop = NaN;
  var PANEL_WIDTH = 380;
  var METERS_PER_DEGREE = 111320;

  var SEL = '<option value="">-- 请选择图层 --</option>';

  var PANEL_HTML =
    '<div class="spatial-panel" id="spatialPanel">' +

      '<div class="spatial-toolbar" id="spatialToolbar">' +
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v4"/><path d="M12 18v4"/><path d="M2 12h4"/><path d="M18 12h4"/></svg>' +
        '<span class="spatial-toolbar-title">空间分析（直连）</span>' +
        '<button class="spatial-toolbar-close" id="spatialClose">' +
          '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +

      '<div class="spatial-tabs" id="spatialTabs">' +
        '<button class="spatial-tab active" data-tab="buffer">缓冲区</button>' +
        '<button class="spatial-tab" data-tab="overlay">叠置</button>' +
        '<button class="spatial-tab" data-tab="clip">裁剪</button>' +
        '<button class="spatial-tab" data-tab="geom">几何工具</button>' +
        '<button class="spatial-tab" data-tab="select">选择</button>' +
        '<button class="spatial-tab" data-tab="stats">统计</button>' +
        '<button class="spatial-tab" data-tab="data">数据</button>' +
      '</div>' +

      '<div class="spatial-body" id="spatialBody">' +

        /* ===== 缓冲区（含多环） ===== */
        '<div class="spatial-tab-content active" id="tabBuffer">' +
          '<div class="spatial-field">' +
            '<label>图层</label>' +
            '<select id="bufferLayer">' + SEL + '</select>' +
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
            '<label>多环距离（可选，逗号分隔，如 100,300,500）</label>' +
            '<input type="text" id="bufferRings" class="spatial-input" placeholder="留空=单环缓冲">' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label class="spatial-checkbox-label">' +
              '<input type="checkbox" id="bufferDissolve"> 融合重叠区域' +
            '</label>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="buffer">运行缓冲区</button>' +
        '</div>' +

        /* ===== 叠置 ===== */
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
            '<select id="overlayLayerA">' + SEL + '</select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>图层 B</label>' +
            '<select id="overlayLayerB">' + SEL + '</select>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="overlay">运行叠置分析</button>' +
        '</div>' +

        /* ===== 裁剪 ===== */
        '<div class="spatial-tab-content" id="tabClip">' +
          '<div class="spatial-field">' +
            '<label>被裁剪图层</label>' +
            '<select id="clipLayer">' + SEL + '</select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>裁剪边界</label>' +
            '<select id="clipByLayer">' + SEL + '</select>' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="clip">运行裁剪</button>' +
        '</div>' +

        /* ===== 几何工具 ===== */
        '<div class="spatial-tab-content" id="tabGeom">' +
          '<div class="spatial-field">' +
            '<label>图层</label>' +
            '<select id="geomLayer">' + SEL + '</select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>操作</label>' +
            '<select id="geomOp">' +
              '<option value="centroid">提取质心</option>' +
              '<option value="simplify">简化几何</option>' +
              '<option value="dissolve">属性融合</option>' +
              '<option value="voronoi">泰森多边形</option>' +
              '<option value="cluster">空间聚类（DBSCAN）</option>' +
              '<option value="merge">与其它图层合并（行合并）</option>' +
              '<option value="fix_geometry">修复无效几何</option>' +
              '<option value="check_duplicates">检测重复要素</option>' +
              '<option value="explode">分解多部件要素</option>' +
              '<option value="to_lines">面→边界线</option>' +
              '<option value="bounding_box">提取外接矩形</option>' +
              '<option value="add_length">添加长度字段（km）</option>' +
            '</select>' +
          '</div>' +
          '<div class="spatial-field" id="geomSimplifyField" style="display:none">' +
            '<label>简化容差（度，0.001≈100m）</label>' +
            '<input type="number" id="geomSimplifyTolerance" class="spatial-input" value="0.001" min="0.0001" step="0.0001">' +
          '</div>' +
          '<div class="spatial-field" id="geomDissolveField" style="display:none">' +
            '<label>融合字段</label>' +
            '<select id="geomDissolveFieldSel"><option value="">-- 全部融合 --</option></select>' +
          '</div>' +
          '<div class="spatial-field" id="geomClusterField" style="display:none">' +
            '<label>DBSCAN 参数</label>' +
            '<div class="spatial-row">' +
              '<input type="number" id="geomClusterEps" class="spatial-input" value="0.01" step="0.005" title="邻域半径（度）">' +
              '<input type="number" id="geomClusterMin" class="spatial-input" value="3" min="1" step="1" title="最小点数">' +
            '</div>' +
          '</div>' +
          '<div class="spatial-field" id="geomMergeField" style="display:none">' +
            '<label>其它图层（逗号分隔）</label>' +
            '<input type="text" id="geomMergeOthers" class="spatial-input" placeholder="图层B,图层C">' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="geom">运行</button>' +
        '</div>' +

        /* ===== 选择 ===== */
        '<div class="spatial-tab-content" id="tabSelect">' +
          '<div class="spatial-field">' +
            '<label>选择方式</label>' +
            '<select id="selectMode">' +
              '<option value="location">按空间关系（相对另一图层）</option>' +
              '<option value="attribute">按属性条件</option>' +
              '<option value="near">近邻查询（距离内要素）</option>' +
              '<option value="sample">随机采样</option>' +
            '</select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>目标图层</label>' +
            '<select id="selectLayer">' + SEL + '</select>' +
          '</div>' +
          '<div class="spatial-field" id="selectLocField">' +
            '<label>参照图层（源）</label>' +
            '<select id="selectSourceLayer">' + SEL + '</select>' +
          '</div>' +
          '<div class="spatial-field" id="selectPredicateField">' +
            '<label>空间关系</label>' +
            '<select id="selectPredicate">' +
              '<option value="intersects">相交 intersects</option>' +
              '<option value="within">包含于 within</option>' +
              '<option value="contains">包含 contains</option>' +
            '</select>' +
          '</div>' +
          '<div class="spatial-field" id="selectNearField" style="display:none">' +
            '<label>距离（米）</label>' +
            '<input type="number" id="selectNearDist" class="spatial-input" value="1000" min="1" step="100">' +
          '</div>' +
          '<div class="spatial-field" id="selectAttrField" style="display:none">' +
            '<label>字段 / 操作符 / 值</label>' +
            '<div class="spatial-row">' +
              '<select id="selectAttrFieldSel"><option value="">-- 字段 --</option></select>' +
              '<select id="selectAttrOp" class="spatial-select-short">' +
                '<option value="=">=</option>' +
                '<option value="!=">!=</option>' +
                '<option value=">">&gt;</option>' +
                '<option value=">=">&gt;=</option>' +
                '<option value="<">&lt;</option>' +
                '<option value="<=">&lt;=</option>' +
                '<option value="contains">包含</option>' +
              '</select>' +
            '</div>' +
            '<input type="text" id="selectAttrValue" class="spatial-input" placeholder="属性值" style="margin-top:4px;">' +
          '</div>' +
          '<div class="spatial-field" id="selectSampleField" style="display:none">' +
            '<label>采样数量（或比例，如 0.2）</label>' +
            '<input type="text" id="selectSampleN" class="spatial-input" placeholder="100 或 0.2">' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="select">执行选择</button>' +
        '</div>' +

        /* ===== 统计 ===== */
        '<div class="spatial-tab-content" id="tabStats">' +
          '<div class="spatial-field">' +
            '<label>图层</label>' +
            '<select id="statsLayer">' + SEL + '</select>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>统计项</label>' +
            '<select id="statsOp">' +
              '<option value="field_stats">字段统计（count/min/max/均值…）</option>' +
              '<option value="measure_area">面积量测（UTM 精确）</option>' +
              '<option value="join">空间连接（把 B 的属性按位置连进来）</option>' +
              '<option value="zonal">分区统计（栅格×面）</option>' +
            '</select>' +
          '</div>' +
          '<div class="spatial-field" id="statsFieldSelWrap">' +
            '<label>数值字段</label>' +
            '<select id="statsFieldSel"><option value="">-- 自动选择 --</option></select>' +
          '</div>' +
          '<div class="spatial-field" id="statsJoinWrap" style="display:none">' +
            '<label>被连接图层（提供属性）</label>' +
            '<select id="statsJoinLayer">' + SEL + '</select>' +
          '</div>' +
          '<div class="spatial-field" id="statsZonalWrap" style="display:none">' +
            '<label>栅格图层名（上传的 GeoTIFF 文件名）</label>' +
            '<input type="text" id="statsZonalRaster" class="spatial-input" placeholder="如 dem">' +
          '</div>' +
          '<button class="spatial-run-btn" data-op="stats">运行统计</button>' +
        '</div>' +

        /* ===== 数据获取（确定性工具直连） ===== */
        '<div class="spatial-tab-content" id="tabData">' +
          '<div class="spatial-field">' +
            '<label>行政区边界（DataV，中国三级）</label>' +
            '<div class="spatial-row">' +
              '<input type="text" id="dataBoundaryPlace" class="spatial-input" placeholder="如：长沙市 / 430100">' +
              '<button class="spatial-run-btn spatial-run-btn-small" data-op="boundary">加载</button>' +
            '</div>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>POI 搜索（高德，需已配置 Key）</label>' +
            '<div class="spatial-row">' +
              '<input type="text" id="dataPoiKeywords" class="spatial-input" placeholder="关键词：餐厅/银行…">' +
              '<input type="text" id="dataPoiCity" class="spatial-input" placeholder="城市" style="max-width:80px;">' +
            '</div>' +
            '<button class="spatial-run-btn spatial-run-btn-small" data-op="poi" style="margin-top:4px;">搜索 POI</button>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>地震数据（USGS，免费）</label>' +
            '<div class="spatial-row">' +
              '<input type="number" id="dataQuakeMag" class="spatial-input" value="4.5" step="0.5" min="0" title="最小震级">' +
              '<button class="spatial-run-btn spatial-run-btn-small" data-op="quake">加载近30天地震</button>' +
            '</div>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>天气（Open-Meteo，当前地图中心）</label>' +
            '<button class="spatial-run-btn spatial-run-btn-small" data-op="weather">查询天气</button>' +
          '</div>' +
          '<div class="spatial-field">' +
            '<label>路网下载（OSM）</label>' +
            '<div class="spatial-row">' +
              '<input type="text" id="dataRoadCity" class="spatial-input" placeholder="城市/区域名">' +
              '<select id="dataRoadType" class="spatial-select-short">' +
                '<option value="drive">车行</option>' +
                '<option value="walk">步行</option>' +
                '<option value="bike">骑行</option>' +
              '</select>' +
            '</div>' +
            '<button class="spatial-run-btn spatial-run-btn-small" data-op="roads" style="margin-top:4px;">下载路网</button>' +
          '</div>' +
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

    // 几何工具：操作切换显隐参数行
    document.getElementById('geomOp').addEventListener('change', function() {
      var v = this.value;
      document.getElementById('geomSimplifyField').style.display = v === 'simplify' ? '' : 'none';
      document.getElementById('geomDissolveField').style.display = v === 'dissolve' ? '' : 'none';
      document.getElementById('geomClusterField').style.display = v === 'cluster' ? '' : 'none';
      document.getElementById('geomMergeField').style.display = v === 'merge' ? '' : 'none';
    });

    // 选择：方式切换显隐参数行
    document.getElementById('selectMode').addEventListener('change', function() {
      var v = this.value;
      document.getElementById('selectLocField').style.display = v === 'location' ? '' : 'none';
      document.getElementById('selectPredicateField').style.display = v === 'location' ? '' : 'none';
      document.getElementById('selectNearField').style.display = v === 'near' ? '' : 'none';
      document.getElementById('selectAttrField').style.display = v === 'attribute' ? '' : 'none';
      document.getElementById('selectSampleField').style.display = v === 'sample' ? '' : 'none';
      // 近邻的"目标图层"其实也是参照图层：near(layer, target) → layer 中距离 target 要素内的要素
      document.getElementById('selectSourceLayer').parentElement.style.display =
        (v === 'location' || v === 'near') ? '' : 'none';
    });

    document.getElementById('statsOp').addEventListener('change', function() {
      var v = this.value;
      document.getElementById('statsFieldSelWrap').style.display = v === 'join' ? 'none' : '';
      document.getElementById('statsJoinWrap').style.display = v === 'join' ? '' : 'none';
      document.getElementById('statsZonalWrap').style.display = v === 'zonal' ? '' : 'none';
    });

    // 图层变化 → 刷新字段下拉
    ['geomLayer', 'selectLayer', 'statsLayer'].forEach(function(id) {
      document.getElementById(id).addEventListener('change', _refreshFieldSelects);
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


  /** 聊天面板右边缘（实时计算：折叠/响应式时宽度会变，不能缓存） */
  function _chatRightEdge() {
    var chatPanel = document.querySelector('.chat-panel');
    if (!chatPanel) return 0;
    var r = chatPanel.getBoundingClientRect();
    return (r.width > 0 ? r.right : 0) + 4;
  }

  /** 把面板坐标夹紧在地图区域内：左不越聊天面板、右/下不出视口 */
  function _clampToMapArea(container, left, top) {
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


  function _switchTab(tab) {
    document.querySelectorAll('.spatial-tab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.spatial-tab-content').forEach(function(c) {
      c.classList.toggle('active', c.id === 'tab' + tab.charAt(0).toUpperCase() + tab.slice(1));
    });
    document.getElementById('spatialResult').style.display = 'none';
  }


  /** 图层下拉：后端注册名 ∪ 前端面板名（去重）。
   *  前端自建图层（绘制/演示）执行前由 syncLayer 自动补注册到后端。 */
  function _refreshLayers() {
    var feNames = _frontendLayerNames();
    fetch((GIS.api && GIS.api.BASE_URL || '') + '/api/layers/names')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var beNames = (data && data.names) || [];
        var seen = {};
        var merged = [];
        beNames.concat(feNames).forEach(function(n) {
          if (n && !seen[n]) { seen[n] = 1; merged.push(n); }
        });
        _fillLayerSelects(merged);
      })
      .catch(function() { _fillLayerSelects(feNames); });
  }

  function _frontendLayerNames() {
    if (GIS.layers && GIS.layers.getLayerNames) return GIS.layers.getLayerNames();
    var data = window._layerData || [];
    return data.map(function(l) { return l.name; });
  }

  var _LAYER_SELECTS = [
    'bufferLayer', 'overlayLayerA', 'overlayLayerB',
    'clipLayer', 'clipByLayer', 'geomLayer', 'selectLayer',
    'selectSourceLayer', 'statsLayer', 'statsJoinLayer'
  ];

  function _fillLayerSelects(names) {
    _LAYER_SELECTS.forEach(function(id) {
      var sel = document.getElementById(id);
      if (!sel) return;
      var current = sel.value;
      sel.innerHTML = SEL;
      names.forEach(function(n) {
        var opt = document.createElement('option');
        opt.value = n;
        opt.textContent = n;
        if (n === current) opt.selected = true;
        sel.appendChild(opt);
      });
    });
    _refreshFieldSelects();
  }

  /** 字段下拉：基于图层第一个要素的属性 */
  function _refreshFieldSelects() {
    var pairs = [
      ['geomLayer', 'geomDissolveFieldSel', false],
      ['selectLayer', 'selectAttrFieldSel', false],
      ['statsLayer', 'statsFieldSel', true]
    ];
    pairs.forEach(function(pair) {
      var layerSel = document.getElementById(pair[0]);
      var fieldSel = document.getElementById(pair[1]);
      if (!layerSel || !fieldSel) return;
      var layerName = layerSel.value;
      var current = fieldSel.value;
      fieldSel.innerHTML = pair[2] ? '<option value="">-- 自动选择 --</option>' : '<option value="">-- 选择字段 --</option>';
      if (!layerName || !GIS.layers || !GIS.layers.getLayerByName) return;
      var layer = GIS.layers.getLayerByName(layerName);
      var props = layer && layer.geojson && layer.geojson.features && layer.geojson.features[0]
        ? layer.geojson.features[0].properties : {};
      Object.keys(props).forEach(function(k) {
        if (k === '_fid') return;
        var opt = document.createElement('option');
        opt.value = k;
        opt.textContent = k;
        if (pair[2] && typeof props[k] !== 'number') return;  // 统计字段只要数值
        if (k === current) opt.selected = true;
        fieldSel.appendChild(opt);
      });
    });
  }


  function _val(id) { return document.getElementById(id).value; }
  function _requireLayer(id) {
    var v = _val(id);
    if (!v) { alert('请先选择图层'); throw new Error('no layer'); }
    return v;
  }

  /** 直连执行：先同步图层到后端注册表 → 调后端工具 → 结果上图 + 文本展示 */
  function _invoke(tool, args, btn) {
    var resultEl = document.getElementById('spatialResult');
    var resultBody = document.getElementById('spatialResultBody');
    var loader = document.getElementById('spatialLoader');
    loader.style.display = '';
    if (btn) { btn.disabled = true; }

    // 把参数里引用的图层先同步进后端注册表（绘制/手动图层只在前端存在）
    var layerNames = Object.keys(args || {})
      .filter(function(k) { return /layer/.test(k) && typeof args[k] === 'string'; })
      .map(function(k) { return args[k]; });
    layerNames = layerNames.concat(
      String(args.layer_names || '').split(',').map(function(s) { return s.trim(); }).filter(Boolean));
    var syncP = (GIS.api && GIS.api.syncLayer)
      ? Promise.all(layerNames.map(function(n) { return GIS.api.syncLayer(n); }))
      : Promise.resolve();

    var p = syncP.then(function() {
      if (!(GIS.api && GIS.api.invokeTool)) throw new Error('GIS.api.invokeTool 不可用');
      return GIS.api.invokeTool(tool, args);
    });

    p.then(function(result) {
      loader.style.display = 'none';
      if (btn) btn.disabled = false;
      // 图层/op/热力图/图片统一上图
      if (GIS.chat && GIS.chat.applyToolResult) GIS.chat.applyToolResult(result);
      // 文本结果展示在面板底部
      resultBody.textContent = result.response || '';
      resultEl.style.display = '';
    }).catch(function(err) {
      loader.style.display = 'none';
      if (btn) btn.disabled = false;
      resultBody.textContent = '执行失败: ' + err.message;
      resultEl.style.display = '';
    });
  }

  function _runOperation(op) {
    var btn = event && event.target ? event.target.closest('.spatial-run-btn') : null;

    if (op === 'buffer') {
      var layer = _requireLayer('bufferLayer');
      var rings = _val('bufferRings').trim();
      var args;
      if (rings) {
        args = { layer_name: layer, distances: rings, unit: _val('bufferUnit'), dissolve: document.getElementById('bufferDissolve').checked };
        return _invoke('spatial_multi_ring_buffer', args, btn);
      }
      args = { layer_name: layer, distance: parseFloat(_val('bufferDistance')) || 500, unit: _val('bufferUnit'), dissolve: document.getElementById('bufferDissolve').checked };
      return _invoke('spatial_buffer', args, btn);
    }

    if (op === 'overlay') {
      var opType = _val('overlayOp');
      var toolName = { intersect: 'spatial_intersect', union: 'spatial_union', difference: 'spatial_difference' }[opType];
      return _invoke(toolName, { layer_a: _requireLayer('overlayLayerA'), layer_b: _requireLayer('overlayLayerB') }, btn);
    }

    if (op === 'clip') {
      return _invoke('spatial_clip', { layer_name: _requireLayer('clipLayer'), clip_layer: _requireLayer('clipByLayer') }, btn);
    }

    if (op === 'geom') {
      var gLayer = _requireLayer('geomLayer');
      var gOp = _val('geomOp');
      if (gOp === 'centroid') return _invoke('spatial_centroid', { layer_name: gLayer }, btn);
      if (gOp === 'simplify') return _invoke('spatial_simplify', { layer_name: gLayer, tolerance: parseFloat(_val('geomSimplifyTolerance')) || 0.001 }, btn);
      if (gOp === 'dissolve') return _invoke('spatial_dissolve', { layer_name: gLayer, group_by: _val('geomDissolveFieldSel') || '' }, btn);
      if (gOp === 'voronoi') return _invoke('spatial_voronoi', { layer_name: gLayer }, btn);
      if (gOp === 'cluster') return _invoke('spatial_cluster', { layer_name: gLayer, eps: parseFloat(_val('geomClusterEps')) || 0.01, min_samples: parseInt(_val('geomClusterMin'), 10) || 3 }, btn);
      if (gOp === 'merge') {
        var others = _val('geomMergeOthers').trim();
        if (!others) { alert('请填写要合并的其它图层名'); return; }
        return _invoke('layer_merge', { layer_names: gLayer + ',' + others }, btn);
      }
      if (gOp === 'fix_geometry') return _invoke('spatial_fix_geometry', { layer_name: gLayer }, btn);
      if (gOp === 'check_duplicates') return _invoke('spatial_check_duplicates', { layer_name: gLayer }, btn);
      if (gOp === 'explode') return _invoke('spatial_explode', { layer_name: gLayer }, btn);
      if (gOp === 'to_lines') return _invoke('geometry_convert', { layer_name: gLayer, target_type: 'lines' }, btn);
      if (gOp === 'bounding_box') return _invoke('geometry_convert', { layer_name: gLayer, target_type: 'bounding_box' }, btn);
      if (gOp === 'add_length') return _invoke('add_length_field', { layer_name: gLayer }, btn);
      return;
    }

    if (op === 'select') {
      var mode = _val('selectMode');
      var sLayer = _requireLayer('selectLayer');
      if (mode === 'location') {
        return _invoke('spatial_select', { target_layer: sLayer, source_layer: _requireLayer('selectSourceLayer'), predicate: _val('selectPredicate') }, btn);
      }
      if (mode === 'attribute') {
        var field = _val('selectAttrFieldSel');
        var value = _val('selectAttrValue');
        if (!field || !value) { alert('请选择字段并填写值'); return; }
        return _invoke('spatial_select_by_attribute', { layer_name: sLayer, field: field, operator: _val('selectAttrOp'), value: value }, btn);
      }
      if (mode === 'near') {
        return _invoke('spatial_near', { layer_name: sLayer, target_layer: _requireLayer('selectSourceLayer'), distance: parseFloat(_val('selectNearDist')) || 1000 }, btn);
      }
      if (mode === 'sample') {
        var raw = _val('selectSampleN').trim();
        var args = { layer_name: sLayer };
        if (raw.indexOf('.') >= 0) args.frac = parseFloat(raw) || 0.1;
        else args.n = parseInt(raw, 10) || 50;
        return _invoke('spatial_sample', args, btn);
      }
      return;
    }

    if (op === 'stats') {
      var stLayer = _requireLayer('statsLayer');
      var stOp = _val('statsOp');
      if (stOp === 'field_stats') {
        return _invoke('spatial_field_stats', { layer_name: stLayer, field: _val('statsFieldSel') || '' }, btn);
      }
      if (stOp === 'measure_area') {
        return _invoke('measure_area', { layer_name: stLayer }, btn);
      }
      if (stOp === 'join') {
        return _invoke('spatial_join', { target_layer: stLayer, join_layer: _requireLayer('statsJoinLayer') }, btn);
      }
      if (stOp === 'zonal') {
        var raster = _val('statsZonalRaster').trim();
        if (!raster) { alert('请填写栅格图层名（上传的 GeoTIFF 文件名）'); return; }
        return _invoke('zonal_statistics', { raster_layer: raster, zone_layer: stLayer, stat: 'mean' }, btn);
      }
      return;
    }

    if (op === 'boundary') {
      var place = _val('dataBoundaryPlace').trim();
      if (!place) { alert('请输入行政区名称，如：长沙市'); return; }
      return _invoke('datav_boundary', { name: place }, btn);
    }

    if (op === 'poi') {
      var kw = _val('dataPoiKeywords').trim();
      if (!kw) { alert('请输入 POI 关键词'); return; }
      return _invoke('amap_poi_search', { keywords: kw, city: _val('dataPoiCity').trim() }, btn);
    }

    if (op === 'quake') {
      return _invoke('fetch_earthquake_data', { min_magnitude: parseFloat(_val('dataQuakeMag')) || 4.5, limit: 500 }, btn);
    }

    if (op === 'weather') {
      var c = GIS.map && GIS.map.getInstance ? GIS.map.getInstance().getCenter() : null;
      if (!c) { alert('地图未就绪'); return; }
      return _invoke('fetch_weather_data', { latitude: +c.lat.toFixed(4), longitude: +c.lng.toFixed(4), past_days: 7 }, btn);
    }

    if (op === 'roads') {
      var city = _val('dataRoadCity').trim();
      if (!city) { alert('请输入城市/区域名'); return; }
      return _invoke('download_road_network', { location_name: city, network_type: _val('dataRoadType') }, btn);
    }
  }


  /** 打开面板并定位到指定 tab（buffer/overlay/clip/geom/select/stats/data） */
  function openTab(tabId) {
    activate();
    if (tabId) _switchTab(tabId);
  }

  GIS.spatial = {
    init: init,
    activate: activate,
    deactivate: deactivate,
    toggle: toggle,
    refreshLayers: _refreshLayers,
    openTab: openTab,
  };

})();
