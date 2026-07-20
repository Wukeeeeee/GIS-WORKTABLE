/**
 * GIS WorkTable — 网络分析模块
 * 路线（含途经点）/服务区/最近设施（多点添加）
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  var GIS = window.GIS;
  var _active = false;
  var _mode = 'route';
  var _inputMode = '';
  var _origin = null;
  var _destination = null;
  var _facility = null;
  var _waypoints = [];
  var _manualFacilities = [];
  var _eventMarkers = [];
  var _resultLayers = [];
  var _networkMarkers = [];
  var _arrowMarker = null;
  var _breaks = [1000, 3000, 5000];
  var _n = 3;
  var _panelLeft = NaN;
  var _panelTop = NaN;

  var BASE_URL = GIS.api ? GIS.api.BASE_URL || '' : '';
  var PANEL_WIDTH = 300;

  function _getMap() {
    return GIS.map && GIS.map.getMap ? GIS.map.getMap() : null;
  }

  var PANEL_HTML =
    '<div class="network-panel" id="networkPanel">' +

      /* ===== 顶部工具栏 ===== */
      '<div class="network-toolbar" id="networkToolbar">' +
        '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2"/><circle cx="18" cy="12" r="2"/><circle cx="10" cy="18" r="2"/><line x1="7.5" y1="7.5" x2="16.5" y2="11"/><line x1="11" y1="16.5" x2="17" y2="13"/></svg>' +
        '<span class="network-toolbar-title">网络分析</span>' +
        '<button class="network-toolbar-close" id="networkClose">' +
          '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</button>' +
      '</div>' +

      /* ===== 主体：左导航 + 右内容 ===== */
      '<div class="network-body">' +

        /* ===== 左侧导航栏 ===== */
        '<div class="network-sidenav" id="networkSidenav">' +
          '<button class="network-sidenav-item active" data-type="route">' +
            '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="12" x2="2" y2="12"/><polyline points="5 9 2 12 5 15"/><polyline points="19 9 22 12 19 15"/></svg>' +
            '<span>路线</span>' +
          '</button>' +
          '<button class="network-sidenav-item" data-type="service_area">' +
            '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="2"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="9"/></svg>' +
            '<span>服务区</span>' +
          '</button>' +
          '<button class="network-sidenav-item" data-type="closest_facility">' +
            '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3" fill="currentColor"/><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/></svg>' +
            '<span>最近设施</span>' +
          '</button>' +
        '</div>' +

        /* ===== 右侧内容区 ===== */
        '<div class="network-content" id="networkContent">' +

          '<div class="network-section-title">路网图层</div>' +
          '<div class="network-field">' +
            '<select id="networkLayerSelect"><option value="">-- 请选择路网图层 --</option></select>' +
          '</div>' +

          '<div class="network-section-title" style="margin-top:8px;">参数设置</div>' +
          '<div id="networkInputs"></div>' +

          '<div id="networkBreaksField" class="network-field" style="display:none">' +
            '<label>断值（米）<span class="network-help" title="从设施点出发沿路网可到达的距离范围">ⓘ</span></label>' +
            '<div class="network-breaks-row">' +
              '<input type="number" class="network-break-input" value="1000" min="100" step="100">' +
              '<input type="number" class="network-break-input" value="3000" min="100" step="100">' +
              '<input type="number" class="network-break-input" value="5000" min="100" step="100">' +
            '</div>' +
          '</div>' +

          '<div id="networkNField" class="network-field" style="display:none">' +
            '<label>返回条数</label>' +
            '<input type="number" class="network-n-input" value="3" min="1" max="20">' +
          '</div>' +

          '<button class="network-solve-btn" id="networkSolveBtn">' +
            '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>' +
            '<span>求解</span>' +
          '</button>' +

          '<div id="networkResult" class="network-result" style="display:none">' +
            '<div class="network-result-title">分析结果</div>' +
            '<div class="network-result-body" id="networkResultBody"></div>' +
            '<button class="network-export-btn" id="networkExportBtn">' +
              '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
              '<span>导出为图层</span>' +
            '</button>' +
          '</div>' +

          '<div class="network-loader" id="networkLoader">' +
            '<div class="network-spinner"></div>' +
            '<span>正在计算...</span>' +
          '</div>' +

        '</div>' + /* /networkContent */
      '</div>' + /* /network-body */

      /* ===== 底部状态栏 ===== */
      '<div class="network-status" id="networkStatus"></div>' +
    '</div>';


  var _initialized = false;

  // ===== 初始化（仅首次调用）=====
  function init() {
    if (_initialized) return;

    // 用 position:fixed wrapper 隔离 html/body overflow:hidden 的裁剪
    var wrapper = document.getElementById('networkPanelWrapper');
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.id = 'networkPanelWrapper';
      document.documentElement.appendChild(wrapper);
    }
    var container = document.getElementById('networkPanelContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'networkPanelContainer';
      wrapper.appendChild(container);
    } else if (container.parentNode !== wrapper) {
      wrapper.appendChild(container);
    }
    container.innerHTML = PANEL_HTML;

    _centerPanel(container);
    _initDrag(container);

    document.getElementById('networkClose').addEventListener('click', deactivate);

    document.getElementById('networkSidenav').addEventListener('click', function(e) {
      var btn = e.target.closest('.network-sidenav-item');
      if (!btn) return;
      _switchType(btn.dataset.type);
    });

    document.getElementById('networkLayerSelect').addEventListener('change', function() {
      _clearNetworkResult();
    });

    document.getElementById('networkSolveBtn').addEventListener('click', solve);
    document.getElementById('networkExportBtn').addEventListener('click', _exportResult);

    _initialized = true;
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


  // ===== 拖拽 =====
  function _initDrag(container) {
    var header = document.getElementById('networkToolbar');
    if (!header) return;
    var startX, startY, startLeft, startTop;

    function onStart(e) {
      if (e.target.closest('.network-toolbar-close')) return;
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
      // 左边界：AI 聊天面板右边缘 + 4px 间距，确保不进入聊天区
      var chatPanel = document.querySelector('.chat-panel');
      var chatRight = chatPanel ? chatPanel.offsetWidth + 4 : 0;
      // 右边界：保留 10px 在可见区域
      left = Math.max(chatRight, Math.min(vw - 10, left));
      // 顶部保留 4px 间距在菜单栏下方，底部保留 10px
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


  // ===== 模式切换 =====
  function _switchType(type) {
    _mode = type;
    _clearNetworkResult();
    _clearNetworkMarkers();
    _origin = null;
    _destination = null;
    _facility = null;
    _waypoints = [];
    _manualFacilities = [];

    document.querySelectorAll('.network-sidenav-item').forEach(function(b) {
      b.classList.toggle('active', b.dataset.type === type);
    });

    var inputs = document.getElementById('networkInputs');
    var breaksField = document.getElementById('networkBreaksField');
    var nField = document.getElementById('networkNField');

    // 设点按钮统一 SVG 图标
    var _pinIcon = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>';

    if (type === 'route') {
      inputs.innerHTML =
        '<div class="network-field">' +
          '<label>起点</label>' +
          '<div class="network-point-row">' +
            '<button class="network-set-btn" id="btnOrigin" data-target="origin">' + _pinIcon + '<span>点击设点</span></button>' +
            '<span class="network-coord" id="networkOriginCoord">未设置</span>' +
          '</div>' +
        '</div>' +
        '<div class="network-field">' +
          '<label>途经点 <span class="network-help" title="点击「添加途经点」后在地图上点击添加，可添加多个">ⓘ</span></label>' +
          '<div class="network-point-row">' +
            '<button class="network-set-btn" id="networkAddWaypointBtn">' +
              '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>' +
              '<span>添加途经点</span>' +
            '</button>' +
          '</div>' +
          '<div id="networkWaypointList"></div>' +
        '</div>' +
        '<div class="network-field">' +
          '<label>终点</label>' +
          '<div class="network-point-row">' +
            '<button class="network-set-btn" id="btnDest" data-target="destination">' + _pinIcon + '<span>点击设点</span></button>' +
            '<span class="network-coord" id="networkDestCoord">未设置</span>' +
          '</div>' +
        '</div>';
      breaksField.style.display = 'none';
      nField.style.display = 'none';
      // 直接绑定点击
      var o = document.getElementById('btnOrigin');
      if (o) o.onclick = function() { _startInputMode('origin'); };
      var d = document.getElementById('btnDest');
      if (d) d.onclick = function() { _startInputMode('destination'); };
      var w = document.getElementById('networkAddWaypointBtn');
      if (w) w.onclick = function() { _startInputMode('waypoint'); };
    } else if (type === 'service_area') {
      inputs.innerHTML =
        '<div class="network-field">' +
          '<label>设施点</label>' +
          '<div class="network-point-row">' +
            '<button class="network-set-btn" id="btnFacility" data-target="facility">' + _pinIcon + '<span>点击设点</span></button>' +
            '<span class="network-coord" id="networkFacilityCoord">未设置</span>' +
          '</div>' +
        '</div>';
      breaksField.style.display = 'block';
      nField.style.display = 'none';
      var f = document.getElementById('btnFacility');
      if (f) f.onclick = function() { _startInputMode('facility'); };
    } else if (type === 'closest_facility') {
      inputs.innerHTML =
        '<div class="network-field">' +
          '<label>事件点</label>' +
          '<div class="network-point-row">' +
            '<button class="network-set-btn" id="btnEventOrigin" data-target="origin">' + _pinIcon + '<span>点击设点</span></button>' +
            '<span class="network-coord" id="networkOriginCoord">未设置</span>' +
          '</div>' +
        '</div>' +
        '<div class="network-field">' +
          '<label>设施图层</label>' +
          '<select id="networkFacilityLayer"><option value="">-- 请选择（可选） --</option></select>' +
        '</div>' +
        '<div class="network-field">' +
          '<label>手动添加设施点 <span class="network-help" title="点击后在地图上点选添加设施点，可混用图层">ⓘ</span></label>' +
          '<div class="network-point-row">' +
            '<button class="network-set-btn" id="networkAddFacilityBtn">' +
              '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>' +
              '<span>添加设施点</span>' +
            '</button>' +
          '</div>' +
          '<div id="networkFacilityList"></div>' +
        '</div>';
      breaksField.style.display = 'none';
      nField.style.display = 'block';
      var eo = document.getElementById('btnEventOrigin');
      if (eo) eo.onclick = function() { _startInputMode('origin'); };
      var af = document.getElementById('networkAddFacilityBtn');
      if (af) af.onclick = function() { _startInputMode('manual_facility'); };
    }

    _setStatus('');
  }


  // ===== 输入模式 =====
  function _startInputMode(target) {
    var map = _getMap();
    console.log('[Network] _startInputMode, target:', target, 'map:', !!map);
    if (!map) { _setStatus('获取地图失败'); return; }

    _inputMode = target;
    _clearNetworkResult();

    var labels = {
      origin: '请在地图上点击设置起点',
      destination: '请在地图上点击设置终点',
      facility: '请在地图上点击设置设施点',
      waypoint: '请在地图上点击添加途经点',
      manual_facility: '请在地图上点击添加设施点',
    };
    _setStatus(labels[target] || '请在地图上点击');
    map.getContainer().style.cursor = 'crosshair';
  }


  // ===== 地图点击 + 吸附 =====
  function onMapClick(e) {
    console.log('[Network] onMapClick, active:', _active, 'inputMode:', _inputMode);
    if (!_active || !_inputMode) return;
    var latlng = e.latlng;
    var point = [latlng.lng, latlng.lat];
    var map = _getMap();

    if (_inputMode === 'waypoint') {
      _addWaypoint(point);
      _inputMode = '';
      if (map) map.getContainer().style.cursor = '';
      _setStatus('途经点已添加，可继续添加或设置终点');
      return;
    }

    if (_inputMode === 'manual_facility') {
      _addManualFacility(point);
      _inputMode = '';
      if (map) map.getContainer().style.cursor = '';
      _setStatus('设施点已添加，可继续添加或点击求解');
      return;
    }

    _doSnap(point, function(snapped, dist, errMsg) {
      console.log('[Network] snap callback, snapped:', !!snapped, 'dist:', dist, 'err:', errMsg);
      if (!snapped) {
        _inputMode = '';
        if (map) map.getContainer().style.cursor = '';
        _setStatus(errMsg || '该点距路网太远，请靠近道路点击');
        return;
      }
      var snapLatLng = L.latLng(snapped[1], snapped[0]);
      var coordStr = snapped[0].toFixed(5) + ', ' + snapped[1].toFixed(5);
      console.log('[Network] setting point, mode:', _inputMode, 'coord:', coordStr);

      if (_inputMode === 'origin') {
        _origin = snapped;
        var el = document.getElementById('networkOriginCoord');
        if (el) el.textContent = coordStr + (dist > 10 ? ' (~' + dist.toFixed(0) + 'm)' : '');
        _clearMarkersByType('origin');
        _addMarker(snapLatLng, '#e74c3c', '起');
      } else if (_inputMode === 'destination') {
        _destination = snapped;
        var el = document.getElementById('networkDestCoord');
        if (el) el.textContent = coordStr + (dist > 10 ? ' (~' + dist.toFixed(0) + 'm)' : '');
        _clearMarkersByType('dest');
        _addMarker(snapLatLng, '#2ecc71', '终');
      } else if (_inputMode === 'facility') {
        _facility = snapped;
        var el = document.getElementById('networkFacilityCoord');
        if (el) el.textContent = coordStr + (dist > 10 ? ' (~' + dist.toFixed(0) + 'm)' : '');
        _clearMarkersByType('facility');
        _addMarker(snapLatLng, '#3498db', '设');
      }

      _inputMode = '';
      if (map) map.getContainer().style.cursor = '';
      _setStatus('点已设置（已吸附到路网），点击"求解"开始分析');
    });
  }


  function _doSnap(point, callback) {
    var layerSelect = document.getElementById('networkLayerSelect');
    var layerName = layerSelect ? layerSelect.value : '';
    if (!layerName) {
      callback(point, 0);
      return;
    }
    var geojson = GIS.layers ? GIS.layers.getLayerGeoJSON(layerName) : null;
    if (!geojson) {
      callback(point, 0);
      return;
    }

    // 显示加载状态
    _setStatus('正在吸附到路网...');
    var map = _getMap();
    if (map) map.getContainer().style.cursor = 'wait';

    // 10 秒超时
    var controller = new AbortController();
    var timeoutId = setTimeout(function() {
      controller.abort();
      console.warn('[Network] snap 请求超时，使用原始坐标');
      if (map) map.getContainer().style.cursor = '';
      callback(point, 0);
    }, 10000);

    fetch(BASE_URL + '/api/network/snap', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({geojson: geojson, point: point}),
      signal: controller.signal,
    })
    .then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function(data) {
      clearTimeout(timeoutId);
      if (map) map.getContainer().style.cursor = '';
      console.log('[Network] snap 响应:', data.found ? '已吸附' : '未找到', '距离:', data.distance_m);
      if (data.snapped) {
        callback(data.snapped, data.distance_m);
      } else if (data.error) {
        callback(null, 0, data.error);
      } else {
        callback(null, 0, '无法将坐标吸附到路网');
      }
    })
    .catch(function(err) {
      clearTimeout(timeoutId);
      if (map) map.getContainer().style.cursor = '';
      if (err.name === 'AbortError') {
        // timeout 已经 callback 过了，不再重复
        return;
      }
      console.warn('[Network] snap 请求失败:', err.message);
      callback(point, 0);
    });
  }


  // ===== 途经点 =====
  function _addWaypoint(point) {
    _waypoints.push(point);
    _renderWaypointList();
    var map = _getMap();
    if (!map) return;
    var idx = _waypoints.length;
    var latlng = L.latLng(point[1], point[0]);
    _addMarker(latlng, '#f39c12', '' + idx);
  }


  function _removeWaypoint(idx) {
    _waypoints.splice(idx, 1);
    _renderWaypointList();
    _clearNetworkMarkers();
    _restoreMarkers();
  }


  function _renderWaypointList() {
    var list = document.getElementById('networkWaypointList');
    if (!list) return;
    list.innerHTML = _waypoints.map(function(wp, i) {
      return '<div class="network-waypoint-item">' +
        '<span class="network-wp-num">' + (i + 1) + '</span>' +
        '<span class="network-wp-coord">' + wp[0].toFixed(4) + ', ' + wp[1].toFixed(4) + '</span>' +
        '<button class="network-wp-del" data-idx="' + i + '">✕</button>' +
      '</div>';
    }).join('');
    list.querySelectorAll('.network-wp-del').forEach(function(btn) {
      btn.addEventListener('click', function() {
        _removeWaypoint(parseInt(this.dataset.idx));
      });
    });
  }


  // ===== 手动设施点 =====
  function _addManualFacility(point) {
    _manualFacilities.push(point);
    _renderFacilityList();
    var map = _getMap();
    if (!map) return;
    var idx = _manualFacilities.length;
    var latlng = L.latLng(point[1], point[0]);
    _addMarker(latlng, '#9b59b6', 'F' + idx);
  }


  function _removeManualFacility(idx) {
    _manualFacilities.splice(idx, 1);
    _renderFacilityList();
    _clearNetworkMarkers();
    _restoreMarkers();
  }


  function _renderFacilityList() {
    var list = document.getElementById('networkFacilityList');
    if (!list) return;
    list.innerHTML = _manualFacilities.map(function(f, i) {
      return '<div class="network-waypoint-item">' +
        '<span class="network-wp-num">F' + (i + 1) + '</span>' +
        '<span class="network-wp-coord">' + f[0].toFixed(4) + ', ' + f[1].toFixed(4) + '</span>' +
        '<button class="network-wp-del" data-idx="' + i + '">✕</button>' +
      '</div>';
    }).join('');
    list.querySelectorAll('.network-wp-del').forEach(function(btn) {
      btn.addEventListener('click', function() {
        _removeManualFacility(parseInt(this.dataset.idx));
      });
    });
  }


  function _restoreMarkers() {
    var map = _getMap();
    if (!map) return;
    if (_origin) _addMarker(L.latLng(_origin[1], _origin[0]), '#e74c3c', '起');
    if (_destination) _addMarker(L.latLng(_destination[1], _destination[0]), '#2ecc71', '终');
    if (_facility) _addMarker(L.latLng(_facility[1], _facility[0]), '#3498db', '设');
    _waypoints.forEach(function(wp, i) {
      _addMarker(L.latLng(wp[1], wp[0]), '#f39c12', '' + (i + 1));
    });
    _manualFacilities.forEach(function(f, i) {
      _addMarker(L.latLng(f[1], f[0]), '#9b59b6', 'F' + (i + 1));
    });
  }


  // ===== 标记管理 =====
  function _addMarker(latlng, color, label) {
    var map = _getMap();
    if (!map) return;
    var marker = L.circleMarker(latlng, {
      radius: 8, color: '#fff', weight: 2, fillColor: color, fillOpacity: 1,
    });
    marker._networkType = label;
    marker.bindTooltip(label, {permanent: true, direction: 'top', offset: [0, -10], className: 'network-marker-tooltip'});
    marker.addTo(map);
    _networkMarkers.push(marker);
  }


  function _clearMarkersByType(type) {
    var map = _getMap();
    var keep = [];
    var labels = {origin: '起', dest: '终', facility: '设'};
    var target = labels[type];
    _networkMarkers.forEach(function(m) {
      if (m._networkType === target) {
        if (map) map.removeLayer(m);
      } else {
        keep.push(m);
      }
    });
    _networkMarkers = keep;
  }


  function _clearNetworkMarkers() {
    var map = _getMap();
    _networkMarkers.forEach(function(m) { if (map) map.removeLayer(m); });
    _networkMarkers = [];
  }


  function _clearResultLayers() {
    var map = _getMap();
    _resultLayers.forEach(function(l) { if (map) map.removeLayer(l); });
    _resultLayers = [];
    if (_arrowMarker && map) { map.removeLayer(_arrowMarker); _arrowMarker = null; }
  }


  // ===== 求解 =====
  function solve() {
    var map = _getMap();
    if (!map) return;

    var layerSelect = document.getElementById('networkLayerSelect');
    var layerName = layerSelect ? layerSelect.value : '';
    if (!layerName) {
      _setStatus('请先选择路网图层');
      return;
    }

    var geojson = GIS.layers ? GIS.layers.getLayerGeoJSON(layerName) : null;
    if (!geojson) {
      _setStatus('路网图层数据不可用');
      return;
    }

    if (!_validateLayerType(geojson)) {
      _setStatus('所选图层不是路网数据（需要 LineString 线要素）');
      return;
    }

    var url = BASE_URL + '/api/network/solve';
    var body = {geojson: geojson, type: _mode};

    if (_mode === 'route') {
      if (!_origin) { _setStatus('请设置起点'); return; }
      if (!_destination) { _setStatus('请设置终点'); return; }
      body.origin = _origin;
      body.dest = _destination;
      if (_waypoints.length > 0) {
        body.waypoints = _waypoints;
      }
    } else if (_mode === 'service_area') {
      if (!_facility) { _setStatus('请设置设施点'); return; }
      body.facility = _facility;
      var inputs = document.querySelectorAll('.network-break-input');
      body.breaks = [];
      inputs.forEach(function(inp) {
        var v = parseFloat(inp.value);
        if (v > 0) body.breaks.push(v);
      });
      if (body.breaks.length === 0) body.breaks = [1000, 3000, 5000];
    } else if (_mode === 'closest_facility') {
      if (!_origin) { _setStatus('请设置事件点'); return; }
      body.origin = _origin;
      body.events = [];

      var facLayerSelect = document.getElementById('networkFacilityLayer');
      var facLayerName = facLayerSelect ? facLayerSelect.value : '';
      if (facLayerName) {
        var facGeoJSON = GIS.layers ? GIS.layers.getLayerGeoJSON(facLayerName) : null;
        if (facGeoJSON && facGeoJSON.features) {
          facGeoJSON.features.forEach(function(f) {
            var geom = f.geometry;
            if (!geom) return;
            if (geom.type === 'Point') {
              body.events.push(geom.coordinates);
            } else if (geom.type === 'MultiPoint') {
              geom.coordinates.forEach(function(c) { body.events.push(c); });
            } else {
              try {
                var centroid = L.geoJSON(f).getBounds().getCenter();
                body.events.push([centroid.lng, centroid.lat]);
              } catch(e) {}
            }
          });
        }
      }

      _manualFacilities.forEach(function(f) {
        body.events.push(f);
      });

      if (body.events.length === 0) {
        _setStatus('请通过设施图层或手动添加至少一个设施点');
        return;
      }

      var nInput = document.querySelector('.network-n-input');
      body.n = nInput ? parseInt(nInput.value) || 3 : 3;
    }

    _showLoader(true);
    _setStatus('正在求解...');
    document.getElementById('networkSolveBtn').disabled = true;

    fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
      _showLoader(false);
      document.getElementById('networkSolveBtn').disabled = false;
      if (data.error) {
        _setStatus('求解失败: ' + data.error);
        return;
      }
      _displayResult(data);
    })
    .catch(function(err) {
      _showLoader(false);
      document.getElementById('networkSolveBtn').disabled = false;
      _setStatus('请求失败: ' + err.message);
    });
  }


  function _validateLayerType(geojson) {
    if (!geojson || !geojson.features) return false;
    var hasLine = false;
    for (var i = 0; i < geojson.features.length; i++) {
      var t = geojson.features[i].geometry && geojson.features[i].geometry.type;
      if (t === 'LineString' || t === 'MultiLineString') {
        hasLine = true;
        break;
      }
    }
    return hasLine;
  }


  // ===== 结果展示 =====
  function _displayResult(data) {
    var map = _getMap();
    if (!map) return;

    _clearResultLayers();
    var resultDiv = document.getElementById('networkResult');
    var resultBody = document.getElementById('networkResultBody');
    resultDiv.style.display = 'block';

    if (_mode === 'route') {
      if (data.path) {
        var pathLayer = L.geoJSON(data.path, {
          style: {color: '#3498db', weight: 4, opacity: 0.9},
        }).addTo(map);
        _resultLayers.push(pathLayer);
        map.fitBounds(pathLayer.getBounds().pad(0.1));

        var coords = data.path.geometry.coordinates;
        if (coords && coords.length > 1) {
          var midIdx = Math.floor(coords.length / 2);
          var mid = coords[midIdx];
          _arrowMarker = L.marker([mid[1], mid[0]], {
            icon: L.divIcon({
              className: 'network-arrow-icon',
              html: '▶',
              iconSize: [16, 16],
              iconAnchor: [8, 8],
            })
          }).addTo(map);
        }
      }

      var html = '<div class="network-stat">总距离: <strong>' + (data.distance_km || 0) + '</strong> km</div>' +
        '<div class="network-stat">途经节点: <strong>' + (data.node_count || 0) + '</strong> 个</div>';

      if (data.segments && data.segments.length > 0) {
        html += '<div class="network-steps"><div class="network-step-title">分段明细</div>';
        data.segments.forEach(function(seg, i) {
          html += '<div class="network-step">' +
            '<span class="network-step-num">' + (i + 1) + '</span>' +
            '<span>' + seg.distance_km.toFixed(2) + ' km</span>' +
          '</div>';
        });
        html += '</div>';
      }

      if (data.steps && data.steps.length > 0) {
        html += '<div class="network-steps"><div class="network-step-title">路段明细</div>';
        var maxShow = Math.min(data.steps.length, 30);
        for (var i = 0; i < maxShow; i++) {
          html += '<div class="network-step"><span class="network-step-num">' + (i + 1) + '</span><span>' + data.steps[i].distance_m.toFixed(0) + 'm</span></div>';
        }
        if (data.steps.length > 30) {
          html += '<div class="network-step-more">...共 ' + data.steps.length + ' 段</div>';
        }
        html += '</div>';
      }

      resultBody.innerHTML = html;
      _setStatus('路径分析完成');

    } else if (_mode === 'service_area') {
      if (data.polygons && data.polygons.features) {
        var colors = ['#3498db', '#e67e22', '#2ecc71', '#e74c3c', '#9b59b6'];
        data.polygons.features.forEach(function(f, i) {
          var color = colors[i % colors.length];
          var layer = L.geoJSON(f, {style: {color: color, weight: 1, fillColor: color, fillOpacity: 0.15}}).addTo(map);
          _resultLayers.push(layer);
        });
        var allBounds = L.geoJSON(data.polygons).getBounds();
        if (allBounds.isValid()) map.fitBounds(allBounds.pad(0.1));
      }
      resultBody.innerHTML = (data.areas || []).map(function(a) {
        return '<div class="network-stat">' + a.break + 'm 服务区: <strong>' + a.area_km2 + '</strong> km²</div>';
      }).join('');
      _setStatus('服务区分析完成');

    } else if (_mode === 'closest_facility') {
      if (data.paths && data.paths.length > 0) {
        var colors = ['#e74c3c', '#e67e22', '#3498db', '#2ecc71', '#9b59b6'];
        var allBounds = null;
        data.paths.forEach(function(p, i) {
          var layer = L.geoJSON(p, {style: {color: colors[i % colors.length], weight: 3, opacity: 0.8, dashArray: '8,4'}}).addTo(map);
          _resultLayers.push(layer);
          var b = layer.getBounds();
          if (b.isValid()) {
            allBounds = allBounds ? allBounds.extend(b) : b;
          }
        });
        if (allBounds) map.fitBounds(allBounds.pad(0.1));
      }
      resultBody.innerHTML = (data.summary || []).map(function(s) {
        return '<div class="network-stat">#' + s.rank + ' 设施' + s.facility_idx + ': <strong>' + s.distance_km + '</strong> km</div>';
      }).join('');
      _setStatus('最近设施分析完成');
    }
  }


  function _exportResult() {
    if (_resultLayers.length === 0) {
      _setStatus('没有结果可导出');
      return;
    }
    var features = [];
    _resultLayers.forEach(function(layer) {
      if (layer.toGeoJSON) {
        var gj = layer.toGeoJSON();
        if (gj.type === 'Feature') features.push(gj);
        else if (gj.type === 'FeatureCollection') features = features.concat(gj.features);
      }
    });
    if (features.length === 0) return;
    var fc = {type: 'FeatureCollection', features: features};
    if (GIS.layers) {
      GIS.layers.addLayer({
        filename: '网络分析结果',
        geojson: fc,
        geometry_type: fc.features[0] && fc.features[0].geometry ? fc.features[0].geometry.type : '未知',
        source: 'network_analysis',
      });
    }
    _setStatus('已导出为图层');
  }


  // ===== Loader =====
  function _showLoader(show) {
    var el = document.getElementById('networkLoader');
    if (el) el.style.display = show ? 'flex' : 'none';
  }


  // ===== 状态 =====
  function _setStatus(msg) {
    var el = document.getElementById('networkStatus');
    if (el) el.textContent = msg;
  }


  function _clearNetworkResult() {
    _clearResultLayers();
    var resultDiv = document.getElementById('networkResult');
    if (resultDiv) resultDiv.style.display = 'none';
  }


  // ===== 图层列表刷新 =====
  function _updateLayerList() {
    var select = document.getElementById('networkLayerSelect');
    if (!select) return;
    var current = select.value;
    select.innerHTML = '<option value="">-- 请选择 --</option>';
    if (GIS.layers) {
      var names = GIS.layers.getLayerNames ? GIS.layers.getLayerNames() : [];
      names.forEach(function(n) {
        var opt = document.createElement('option');
        opt.value = n;
        opt.textContent = n;
        select.appendChild(opt);
      });
    }
    if (current && Array.from(select.options).some(function(o) { return o.value === current; })) {
      select.value = current;
    }

    var facSelect = document.getElementById('networkFacilityLayer');
    if (facSelect) {
      var facCurrent = facSelect.value;
      facSelect.innerHTML = '<option value="">-- 不选择（仅用手动设施点） --</option>';
      if (GIS.layers) {
        var names = GIS.layers.getLayerNames ? GIS.layers.getLayerNames() : [];
        names.forEach(function(n) {
          var opt = document.createElement('option');
          opt.value = n;
          opt.textContent = n;
          facSelect.appendChild(opt);
        });
      }
      if (facCurrent && Array.from(facSelect.options).some(function(o) { return o.value === facCurrent; })) {
        facSelect.value = facCurrent;
      }
    }
  }


  // ===== 激活/关闭 =====
  function activate() {
    if (_active) return;
    _active = true;
    init();
    var panel = document.getElementById('networkPanel');
    if (panel) panel.style.display = 'flex';
    _updateLayerList();
    _switchType('route');
    _setStatus('点击地图设置点，然后求解');
    var map = _getMap();
    console.log('[Network] activate, map:', !!map);
    if (map) map.on('click', onMapClick);
  }


  function deactivate() {
    if (!_active) return;
    _active = false;
    var map = _getMap();
    if (map) {
      map.off('click', onMapClick);
      map.getContainer().style.cursor = '';
    }
    var panel = document.getElementById('networkPanel');
    if (panel) panel.style.display = 'none';
    _clearNetworkMarkers();
    _clearResultLayers();
    _inputMode = '';
    _origin = null;
    _destination = null;
    _facility = null;
    _waypoints = [];
    _manualFacilities = [];
    // 不重置 _initialized，保留 DOM 结构与事件绑定
  }


  function toggle() {
    if (_active) { deactivate(); }
    else { activate(); }
  }


  function isActive() {
    return _active;
  }


  GIS.network = {
    init: init,
    activate: activate,
    deactivate: deactivate,
    toggle: toggle,
    isActive: isActive,
    onMapClick: onMapClick,
    updateLayerList: _updateLayerList,
  };
})();
