/**
 * GIS AI WorkTable — 地图模块
 * Leaflet 封装，只保留 Bing 卫星底图
 *
 * 底图: Bing 卫星（ditu.live.com 中国 CDN）
 * 数据存 WGS-84，底图也是 WGS-84，直接叠加
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  let mapInstance = null;
  const layers = {};
  const geoStore = {};
  let baseLayer = null;
  let _currentBaseMap = 'satellite'; // 'satellite' | 'light'
  let drawnItems = null;        // Leaflet.Draw 绘制的图形集合
  let _featureMap = {};         // { "layerName:idx": LeafletLayer } — 要素索引→Leaflet 图层
  let _highlightedFeature = null; // 当前高亮的 Leaflet 图层
  let _featureInfoActive = false; // 选择要素工具是否激活
  // 缓存 DOM 引用——避免每次 mousemove 都 querySelector
  var _coordsEl = null;
  var _zoomLabelEl = null;
  var _resizeObserver = null;
  var _deleteMode = false;

  var TILE_URL = 'https://t1.dynamic.tiles.ditu.live.com/comp/ch/{q}?mkt=zh-CN&ur=cn&it=A&n=z&og=804&cstl=vbd';

  /** 进入删除模式：点击已绘制的图形将其移除 */
  function _enterDeleteMode() {
    if (_deleteMode) return;
    _deleteMode = true;
    document.getElementById('map').style.cursor = 'crosshair';
    // 监听绘制图层上的点击
    if (drawnItems) {
      drawnItems.on('click', _onDeleteClick);
    }
  }

  /** 退出删除模式 */
  function _exitDeleteMode() {
    if (!_deleteMode) return;
    _deleteMode = false;
    document.getElementById('map').style.cursor = '';
    if (drawnItems) {
      drawnItems.off('click', _onDeleteClick);
    }
    // 不操作 active 类（由 toolbar click handler 管理）
  }

  function _setFeatureInfoActive(active) {
    _featureInfoActive = active;
    var mapEl = document.getElementById('map');
    if (active) {
      mapEl.style.cursor = 'crosshair';
      if (drawnItems) drawnItems.on('click', _onFeatureInfoClick);
    } else {
      mapEl.style.cursor = '';
      if (drawnItems) drawnItems.off('click', _onFeatureInfoClick);
    }
  }

  /** 点击删除回调 */
  function _onDeleteClick(e) {
    var layer = e.layer || e.target;
    if (!layer || !drawnItems || layer === drawnItems) return;
    // 从地图上的 FeatureGroup 移除
    drawnItems.removeLayer(layer);
    // 从 GIS 图层系统移除
    if (layer._name && window.GIS && window.GIS.layers && window.GIS.layers.removeLayer) {
      window.GIS.layers.removeLayer(layer._name);
    }
    // 如果删完了，自动退出删除模式
    if (drawnItems.getLayers().length === 0) {
      _exitDeleteMode();
    }
  }

  /** 选择要素工具：点击绘制要素弹出属性信息卡片 */
  function _onFeatureInfoClick(e) {
    var layer = e.layer || e.target;
    if (!layer || layer === drawnItems) return;

    clearHighlight();
    _highlightFeature(layer);

    var geomType = '未知';
    var coordsInfo = '';
    if (layer.getLatLng) {
      var ll = layer.getLatLng();
      coordsInfo = ll.lat.toFixed(5) + ', ' + ll.lng.toFixed(5);
      if (layer instanceof L.CircleMarker) {
        geomType = '点（圆）';
      } else if (layer instanceof L.Marker) {
        geomType = '点（标记）';
      } else {
        geomType = '点';
      }
    } else if (layer.getCenter) {
      try {
        var center = layer.getCenter();
        coordsInfo = center.lat.toFixed(5) + ', ' + center.lng.toFixed(5);
      } catch(_) {}
      if (layer instanceof L.Polygon || layer instanceof L.Rectangle) {
        geomType = '面';
      } else if (layer instanceof L.Polyline) {
        geomType = '线';
      }
    }

    var html = '<div class="feat-popup">';
    html += '<strong>' + escapeHtml(layer._name || ('绘制' + geomType)) + '</strong>';
    html += '<div class="feat-popup-row"><span>类型</span><span>' + geomType + '</span></div>';
    if (coordsInfo) html += '<div class="feat-popup-row"><span>坐标</span><span>' + escapeHtml(coordsInfo) + '</span></div>';
    html += '</div>';
    layer.bindPopup(html, { className: 'feat-popup-wrap', closeButton: true, maxWidth: 300, offset: L.point(0, -8) }).openPopup();
  }

  function init(container, options) {
    if (typeof L === 'undefined') { console.warn('[GIS Map] Leaflet 未加载'); return; }
    if (mapInstance) { console.warn('[GIS Map] 已初始化'); return; }

    options = options || {};
    var el = typeof container === 'string' ? document.getElementById(container) : container;
    if (!el) { console.warn('[GIS Map] 容器不存在:', container); return; }

    mapInstance = L.map(el, {
      center: options.center || [35, 110],
      zoom: options.zoom || 4,
      zoomControl: false,
      attributionControl: true,
    });

    // Bing 卫星底图
    _currentBaseMap = localStorage.getItem('gis_basemap') || 'satellite';
    baseLayer = _createBaseLayer(_currentBaseMap);
    baseLayer.addTo(mapInstance);
    // 初始化底图切换勾选
    var swCheck = document.querySelector('.map-menu-item-toggle[data-action="switch-basemap"] .toggle-check');
    if (swCheck) swCheck.classList.toggle('off', _currentBaseMap !== 'satellite');

    // 缓存 DOM 引用，避免每次 mousemove 都 querySelector
    _coordsEl = document.querySelector('.map-coords');
    _zoomLabelEl = document.querySelector('.map-zoom-label');

    mapInstance.on('mousemove', onMouseMove);
    mapInstance.on('zoomend', onZoomEnd);

    // 拖拽地图时自动隐藏十字准星（坐标不再对应）
    mapInstance.on('dragstart', function() {
      _hideCrosshair();
    });
    // 缩放时也隐藏
    mapInstance.on('zoomstart', function() {
      _hideCrosshair();
    });

    // 初始化右键菜单
    setTimeout(initContextMenu, 200);

    // 确保地图尺寸正确——多次尝试 + ResizeObserver
    function doInvalidate() { if (mapInstance) mapInstance.invalidateSize(); }
    [50, 200, 500, 1000].forEach(function(t) { setTimeout(doInvalidate, t); });

    // ResizeObserver：地图容器尺寸变化时自动重算
    if (typeof ResizeObserver !== 'undefined') {
      if (_resizeObserver) _resizeObserver.disconnect(); // 防止重复 init
      _resizeObserver = new ResizeObserver(function() { doInvalidate(); });
      _resizeObserver.observe(el); // 观察地图元素自身，而非父元素
      // 页面关闭时断开，防止内存泄漏
      window.addEventListener('beforeunload', function _cleanupRO() {
        if (_resizeObserver) { _resizeObserver.disconnect(); _resizeObserver = null; }
      });
    }

    // ---- 绘制工具（顶部工具栏 + Leaflet.Draw 引擎）----
    if (typeof L.Draw !== 'undefined') {
      drawnItems = new L.FeatureGroup();
      mapInstance.addLayer(drawnItems);

      // 绘制完成事件
      mapInstance.on(L.Draw.Event.CREATED, function(e) {
        var layer = e.layer;
        // 把 marker 换成 circleMarker（统一颜色系统）
        if (layer instanceof L.Marker && !(layer instanceof L.CircleMarker)) {
          var latlng = layer.getLatLng();
          var color = '#1c1b1b';
          layer = L.circleMarker(latlng, {
            radius: 6, fillColor: color, color: color,
            weight: 2, opacity: 1, fillOpacity: 0.6,
          });
        }
        drawnItems.addLayer(layer);
        var name = '绘制_' + Date.now().toString(36);
        layer._name = name;
        if (window.GIS && window.GIS.layers && window.GIS.layers.addLayer) {
          window.GIS.layers.addLayer({
            layer_id: name, name: name, filename: name, checked: true,
            geojson: layer.toGeoJSON(), source: '绘制'
          });
        }
        // 连续绘制：如果绘制按钮仍高亮，自动重新启用同款工具
        var activeBtn = document.querySelector('.map-draw-btn.active:not([data-tool="delete"])');
        if (activeBtn) {
          var tool = activeBtn.dataset.tool;
          var DrawClass = { polygon: L.Draw.Polygon, rectangle: L.Draw.Rectangle,
            circle: L.Draw.Circle, polyline: L.Draw.Polyline, marker: L.Draw.Marker }[tool];
          if (DrawClass) {
            // 等 Leaflet.Draw 内部清理完再重新启用
            setTimeout(function() {
              if (!mapInstance) return;
              if (!document.querySelector('.map-draw-btn.active[data-tool="' + tool + '"]')) return;
              mapInstance._drawHandler = new DrawClass(mapInstance);
              mapInstance._drawHandler.enable();
            }, 50);
          }
        }
      });

      // 编辑/删除事件
      mapInstance.on(L.Draw.Event.DELETED, function() {
        // 删除后清理已移除的图层
      });

      // 右侧面板绘制按钮
      var drawToolbar = document.getElementById('mapZoomControls');
      if (drawToolbar) {
        drawToolbar.addEventListener('click', function(e) {
          var btn = e.target.closest('.map-draw-btn');
          if (!btn) return;
          var tool = btn.dataset.tool;

          // 高亮当前按钮，取消其他按钮高亮
          document.querySelectorAll('.map-draw-btn').forEach(function(b) { b.classList.remove('active'); });
          btn.classList.add('active');

          // 切到其他工具时停用选择要素
          if (tool !== 'feature-info') _setFeatureInfoActive(false);

          // 停止之前的绘制模式
          if (mapInstance._drawHandler) { mapInstance._drawHandler.disable(); mapInstance._drawHandler = null; }

          if (tool === 'select') {
            // 选择工具：退出所有编辑/删除模式，恢复默认光标
            _exitDeleteMode();
            _setFeatureInfoActive(false);
            return;
          }

          if (tool === 'feature-info') {
            // 选择要素工具：激活后点击地图要素弹出属性信息
            _exitDeleteMode();
            _setFeatureInfoActive(true);
            return;
          }

          if (tool === 'delete') {
            // 切换删除模式：点击已绘制的图形将其移除
            if (_deleteMode) {
              _exitDeleteMode();
            } else {
              _enterDeleteMode();
            }
            return;
          }

          // 启用手动绘制工具
          var DrawClass = { polygon: L.Draw.Polygon, rectangle: L.Draw.Rectangle,
            circle: L.Draw.Circle, polyline: L.Draw.Polyline, marker: L.Draw.Marker }[tool];
          if (DrawClass) {
            mapInstance._drawHandler = new DrawClass(mapInstance);
            mapInstance._drawHandler.enable();
          }
        });

        // 点击地图关闭绘制模式
        mapInstance.on('click', function() {
          // 不要立即清除高亮，让用户看到当前工具
        });

        // 按 Esc 取消绘制 / 退出删除模式 / 清除高亮
        mapInstance.on('keydown', function(e) {
          if (e.originalEvent.key === 'Escape') {
            if (mapInstance._drawHandler) { mapInstance._drawHandler.disable(); mapInstance._drawHandler = null; }
            _exitDeleteMode();
            _setFeatureInfoActive(false);
            document.querySelectorAll('.map-draw-btn').forEach(function(b) { b.classList.remove('active'); });
            document.getElementById('map').style.cursor = '';
          }
        });
      }
      // 初始化顶部菜单栏
      _initMapMenu();
      _initShortcuts();
      _initManual();
    }
  }

  /** 创建底图图层 */
  function _createBaseLayer(type) {
    if (type === 'light') {
      return new L.TileLayer('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQABNjN9GQAAAAlwSFlzAAAWJQAAFiUBSVIk8AAAAA0lEQVQI12P4z8BQDwAEgAF/QualzQAAAABJRU5ErkJggg==', {
        attribution: '',
        maxZoom: 19,
        tileSize: 256,
        noWrap: true,
      });
    }
    // satellite (default)
    var layer = new L.TileLayer('', {
      attribution: '&copy; Microsoft, 必应地图',
      maxZoom: 19,
    });
    layer.getTileUrl = function(coords) {
      return TILE_URL.replace('{q}', toQuadkey(coords.x, coords.y, coords.z));
    };
    return layer;
  }

  /** 切换底图 'satellite' | 'light' */
  function switchBaseMap(type) {
    if (!mapInstance || type === _currentBaseMap) return;
    if (baseLayer) mapInstance.removeLayer(baseLayer);
    baseLayer = _createBaseLayer(type);
    baseLayer.addTo(mapInstance);
    _currentBaseMap = type;
    localStorage.setItem('gis_basemap', type);
    // 更新菜单项勾选
    var satCheck = document.querySelector('.map-menu-item-toggle[data-action="switch-basemap"] .toggle-check');
    if (satCheck) satCheck.classList.toggle('off', type !== 'satellite');
  }

  function toQuadkey(x, y, z) {
    if (z < 0 || z > 23 || x < 0 || y < 0) return '';
    var q = '';
    for (var i = z; i > 0; i--) {
      var d = 0; var m = 1 << (i - 1);
      if ((x & m) !== 0) d += 1; if ((y & m) !== 0) d += 2; q += d;
    }
    return q;
  }

  /** 加载 GeoJSON 到地图 */
  function loadGeoJSON(geojson, name, style) {
    if (!mapInstance || !geojson) return null;
    name = name || 'layer';
    style = style || {};

    if (layers[name]) mapInstance.removeLayer(layers[name]);

    var defaultStyle = { color: '#1c1b1b', weight: 2, fillColor: '#1c1b1b', fillOpacity: 0.1 };
    var mergedStyle = Object.assign({}, defaultStyle, style);

    // 调试：检查 GeoJSON 是否有效
    var featCount = geojson.type === 'FeatureCollection' ? (geojson.features || []).length : 1;
    var firstCoord = null;
    try {
      if (geojson.type === 'FeatureCollection' && geojson.features && geojson.features[0] && geojson.features[0].geometry) {
        firstCoord = JSON.stringify(geojson.features[0].geometry.coordinates);
      } else if (geojson.geometry) {
        firstCoord = JSON.stringify(geojson.geometry.coordinates);
      }
    } catch(e) {}
    console.log('[GIS Map] 加载图层:', name, '要素:', featCount, '首坐标:', firstCoord);

    // 要素映射：清除该图层旧的映射
    Object.keys(_featureMap).forEach(function(k) {
      if (k.startsWith(name + ':')) delete _featureMap[k];
    });

    var features = (geojson.type === 'FeatureCollection' ? geojson.features : [geojson]);

    var layer = L.geoJSON(geojson, {
      style: mergedStyle,
      pointToLayer: function(feature, latlng) {
        return L.circleMarker(latlng, {
          radius: 2.5, fillColor: mergedStyle.fillColor,
          color: mergedStyle.fillColor, weight: 0, opacity: 1, fillOpacity: 1,
        });
      },
      coordsToLatLng: function(coords) {
        var lng = coords[0], lat = coords[1];
        if (Math.abs(lat) > 90 && Math.abs(lng) <= 90) {
          return L.latLng(lng, lat);
        }
        return L.latLng(lat, lng);
      },
      onEachFeature: function(feature, leafletLayer) {
        var idx = features.indexOf(feature);
        if (idx === -1) return;
        var key = name + ':' + idx;
        _featureMap[key] = leafletLayer;

        leafletLayer.on('click', function(e) {
          // 选择要素工具未激活时不弹 popup（只保留高亮供检查器定位用）
          if (!_featureInfoActive) return;

          clearHighlight();
          _highlightFeature(leafletLayer);

          var props = feature.properties || {};
          var title = props.name || props.id || props.NAME || '要素 #' + (idx + 1);
          var html = '<div class="feat-popup">';
          html += '<strong>' + escapeHtml(String(title)) + '</strong>';
          var count = 0;
          for (var k in props) {
            if (count++ >= 5) break;
            var v = props[k];
            html += '<div class="feat-popup-row">';
            html += '<span>' + escapeHtml(k) + '</span>';
            html += '<span>' + (v === null || v === undefined ? '' : escapeHtml(String(v))) + '</span>';
            html += '</div>';
          }
          html += '<div class="feat-popup-footer">';
          html += '<span class="feat-popup-idx">#' + (idx + 1) + ' / ' + features.length + '</span>';
          html += '<span style="color:var(--ui-gray-300);font-size:10px;">' + escapeHtml(name) + '</span>';
          html += '</div></div>';
          leafletLayer.bindPopup(html, { className: 'feat-popup-wrap', closeButton: true, maxWidth: 300, offset: L.point(0, -8) }).openPopup();
        });
      },
    });
    layer.addTo(mapInstance);
    layers[name] = layer;
    geoStore[name] = { geojson: geojson, style: style };
    // 自动缩放到图层范围
    try {
      mapInstance.fitBounds(layer.getBounds(), { padding: [30, 30], maxZoom: 16 });
    } catch(e) {}
    return layer;
  }

  function removeLayer(name) {
    // 清理要素映射
    Object.keys(_featureMap).forEach(function(k) {
      if (k.startsWith(name + ':')) delete _featureMap[k];
    });
    if (layers[name]) { mapInstance.removeLayer(layers[name]); delete layers[name]; delete geoStore[name]; }
    if (drawnItems) {
      var toRemove = [];
      drawnItems.eachLayer(function(l) {
        if (l._name === name) toRemove.push(l);
      });
      toRemove.forEach(function(l) { drawnItems.removeLayer(l); });
    }
  }

  /** 切换图层显隐 */
  function setLayerVisible(name, visible) {
    if (!layers[name]) return;
    if (visible) {
      if (!mapInstance.hasLayer(layers[name])) mapInstance.addLayer(layers[name]);
    } else {
      if (mapInstance.hasLayer(layers[name])) mapInstance.removeLayer(layers[name]);
    }
  }

  /** 获取 Leaflet 图层对象 */
  function getLayer(name) {
    return layers[name] || null;
  }

  /** 修改图层颜色 */
  function setLayerColor(name, color) {
    var layer = layers[name];
    if (!layer && drawnItems) {
      drawnItems.eachLayer(function(l) {
        if (l._name === name) layer = l;
      });
      if (layer) layers[name] = layer; // 缓存到 layers 方便下次查找
    }
    if (!layer) return;
    if (typeof layer.setStyle === 'function') {
      layer.setStyle({ color: color, fillColor: color });
    }
    if (geoStore[name]) geoStore[name].style = { color: color, fillColor: color };
  }

  function toggleLayer(name) {
    if (!layers[name]) return;
    if (mapInstance.hasLayer(layers[name])) mapInstance.removeLayer(layers[name]);
    else mapInstance.addLayer(layers[name]);
  }

  function flyTo(center, zoom) {
    if (!mapInstance) return;
    mapInstance.flyTo(center, zoom || 14);
  }

  function fitLayer(name) {
    if (!mapInstance || !layers[name]) return;
    mapInstance.fitBounds(layers[name].getBounds());
  }

  /** 清除当前高亮 */
  function clearHighlight() {
    if (_highlightedFeature) {
      var orig = _highlightedFeature._origStyle;
      if (orig) {
        _highlightedFeature.setStyle({
          color: orig.color,
          weight: orig.weight,
          fillColor: orig.fillColor,
          fillOpacity: orig.fillOpacity,
        });
      }
      _highlightedFeature._origStyle = null;
      _highlightedFeature = null;
    }
  }

  /** 高亮指定 Leaflet 图层 */
  function _highlightFeature(leafletLayer) {
    _highlightedFeature = leafletLayer;
    _highlightedFeature._origStyle = {
      color: leafletLayer.options.color,
      weight: leafletLayer.options.weight,
      fillColor: leafletLayer.options.fillColor,
      fillOpacity: leafletLayer.options.fillOpacity,
    };
    leafletLayer.setStyle({
      color: '#e53935',
      weight: 4,
      fillColor: '#ef5350',
      fillOpacity: 0.3,
    });
    if (leafletLayer.bringToFront) leafletLayer.bringToFront();
  }

  /** 从属性表定位到要素 */
  function highlightLayerFeature(name, idx) {
    var key = name + ':' + idx;
    var leafletLayer = _featureMap[key];
    if (!leafletLayer) return false;
    clearHighlight();
    _highlightFeature(leafletLayer);
    if (leafletLayer.getBounds) {
      try { mapInstance.flyToBounds(leafletLayer.getBounds(), { padding: [30, 30], maxZoom: 16 }); } catch(e) {}
    } else if (leafletLayer.getLatLng) {
      mapInstance.flyTo(leafletLayer.getLatLng(), 16);
    }
    return true;
  }

  function onMouseMove(e) {
    if (_coordsEl) _coordsEl.textContent = 'WGS-84 | ' + e.latlng.lat.toFixed(5) + ', ' + e.latlng.lng.toFixed(5);
  }

  function onZoomEnd() {
    if (_zoomLabelEl) _zoomLabelEl.textContent = 'Z' + mapInstance.getZoom();
  }

  /** 加载热力图（leaflet.heat） */
  function loadHeatmap(points, name, options) {
    if (!mapInstance || !points || points.length === 0) return null;
    if (typeof L.heatLayer !== 'function') {
      console.warn('[GIS Map] leaflet.heat 插件未加载，无法显示热力图');
      return null;
    }
    name = name || 'heatmap';
    options = options || {};
    if (layers[name]) { mapInstance.removeLayer(layers[name]); delete layers[name]; delete geoStore[name]; }
    var maxIntensity = 0;
    points.forEach(function(p) { if (p[2] > maxIntensity) maxIntensity = p[2]; });

    // 根据当前缩放级别动态调整 radius，缩小过远时自动隐藏
    var curZoom = mapInstance.getZoom();
    var radius = options.radius || 20;
    var maxZoom = options.maxZoom || Math.min(curZoom + 4, 18);

    var heat = L.heatLayer(points, {
      radius: radius,
      blur: options.blur || Math.max(radius * 0.75, 10),
      maxZoom: maxZoom,
      minOpacity: options.minOpacity || 0.3,
      max: maxIntensity || 1,
      gradient: options.gradient || { 0.4: 'blue', 0.6: 'cyan', 0.7: 'lime', 0.8: 'yellow', 1.0: 'red' },
    });
    heat.addTo(mapInstance);
    layers[name] = heat;
    geoStore[name] = { type: 'heatmap', options: options };

    // 缩放过远时自动显隐，避免大范围渲染卡顿
    var _heatZoomHandler = function() {
      var z = mapInstance.getZoom();
      var minZoom = options.minZoom || 4;
      if (z < minZoom) {
        if (mapInstance.hasLayer(heat)) mapInstance.removeLayer(heat);
      } else {
        if (!mapInstance.hasLayer(heat)) mapInstance.addLayer(heat);
      }
    };
    mapInstance.on('zoomend', _heatZoomHandler);
    heat._zoomHandler = _heatZoomHandler;

    return heat;
  }

  function removeHeatmap(name) {
    if (layers[name]) {
      if (layers[name]._zoomHandler) mapInstance.off('zoomend', layers[name]._zoomHandler);
      mapInstance.removeLayer(layers[name]);
      delete layers[name];
      delete geoStore[name];
    }
  }

  // ---- 右键菜单 ----
  var _contextMenuEl = null;
  var _lastRightClickLatLng = null;

  function initContextMenu() {
      mapInstance.on('contextmenu', function(e) {
        // 归一化坐标到标准 -180~180 范围
        var lat = Math.min(90, Math.max(-90, e.latlng.lat));
        var lng = ((e.latlng.lng + 180) % 360 + 360) % 360 - 180;
        _lastRightClickLatLng = { lat: lat, lng: lng };
        e.originalEvent.preventDefault();
        _showContextMenu(e.originalEvent.clientX, e.originalEvent.clientY, _lastRightClickLatLng);
      });
      document.addEventListener('click', function(e) {
        if (!e.target.closest('.map-context-menu')) _hideContextMenu();
      });
      var menuEl = document.getElementById('mapContextMenu');
      if (menuEl) {
        menuEl.addEventListener('click', function(e) {
          e.stopPropagation();
          var item = e.target.closest('.context-menu-item');
          if (!item) return;
          var action = item.getAttribute('data-action');
          var latlng = _lastRightClickLatLng;
          // 只隐藏菜单，十字准星保留在地图上（发送后不消失）
          var el = document.getElementById('mapContextMenu');
          if (el) el.style.display = 'none';
          if (!latlng) return;
          _handleCtxAction(action, latlng);
        });
      }
  }

  function _showContextMenu(x, y, latlng) {
    var el = document.getElementById('mapContextMenu');
    if (!el) return;
    el.style.display = 'block';
    el.style.left = x + 'px';
    el.style.top = y + 'px';
    _showCrosshair(x, y, latlng);
  }

  function _hideContextMenu() {
    var el = document.getElementById('mapContextMenu');
    if (el) el.style.display = 'none';
    _hideCrosshair();
  }

  // ---- 十字准星：用 position:fixed 固定在点击的屏幕位置 ----
  // 注意：拖拽地图时准星不会跟踪地理坐标，所以拖拽开始时自动隐藏
  var _crosshairOverlay = null;

  function _showCrosshair(x, y, latlng) {
    _hideCrosshair();
    var lat = latlng.lat, lng = latlng.lng;

    // 获取地图容器边界，把辅助线限制在地图区域内
    var mapEl = document.getElementById('map');
    var mapRect = mapEl ? mapEl.getBoundingClientRect() : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
    var mLeft = mapRect.left, mTop = mapRect.top;
    var mRight = mLeft + mapRect.width, mBottom = mTop + mapRect.height;

    var container = document.createElement('div');
    container.id = 'crosshair-overlay';
    container.style.cssText = 'position:fixed;left:' + mLeft + 'px;top:' + mTop + 'px;width:' + mapRect.width + 'px;height:' + mapRect.height + 'px;pointer-events:none;z-index:9999;overflow:hidden;';

    // 竖线（只在地图区域内）
    var vLine = document.createElement('div');
    vLine.style.cssText = 'position:absolute;left:' + (x - mLeft) + 'px;top:0;width:1px;height:100%;background:#666;opacity:0.5;pointer-events:none;';
    // 横线（只在地图区域内）
    var hLine = document.createElement('div');
    hLine.style.cssText = 'position:absolute;left:0;top:' + (y - mTop) + 'px;width:100%;height:1px;background:#666;opacity:0.5;pointer-events:none;';
    // 中心圆点
    var dot = document.createElement('div');
    dot.style.cssText = 'position:absolute;left:' + (x - mLeft - 5) + 'px;top:' + (y - mTop - 5) + 'px;width:10px;height:10px;border-radius:50%;background:#fff;border:2px solid #333;box-sizing:border-box;pointer-events:none;';
    // 坐标标签
    var label = document.createElement('div');
    label.textContent = lat.toFixed(5) + ', ' + lng.toFixed(5);
    var labelStyle = 'position:absolute;font-size:11px;font-family:monospace;padding:2px 6px;border-radius:3px;white-space:nowrap;line-height:1.5;color:#fff;background:rgba(0,0,0,0.75);pointer-events:none;';
    var lx = x - mLeft + 10, ly = y - mTop - 22;
    if (ly < 0) ly = y - mTop + 10;
    if (lx + 120 > mapRect.width) lx = x - mLeft - 130;
    label.style.cssText = labelStyle + 'left:' + lx + 'px;top:' + ly + 'px;';

    container.appendChild(vLine);
    container.appendChild(hLine);
    container.appendChild(dot);
    container.appendChild(label);
    document.body.appendChild(container);
    _crosshairOverlay = container;
  }

  function _hideCrosshair() {
    if (_crosshairOverlay && _crosshairOverlay.parentNode) {
      _crosshairOverlay.parentNode.removeChild(_crosshairOverlay);
    }
    _crosshairOverlay = null;
  }

  function _handleCtxAction(action, latlng) {
    var lat = latlng.lat.toFixed(6);
    var lng = latlng.lng.toFixed(6);

    // 复制坐标：不受任何限制
    if (action === 'copy-coords') {
      var text = lat + ', ' + lng;
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(function() {
          if (window.GIS && window.GIS.chat && window.GIS.chat.addMessage)
            window.GIS.chat.addMessage('已复制坐标：' + text, 'system');
        });
      } else {
        var ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        if (window.GIS && window.GIS.chat && window.GIS.chat.addMessage)
          window.GIS.chat.addMessage('已复制坐标：' + text, 'system');
      }
      return;
    }

    // AI 相关功能 — 如果被卡死但无 loading 气泡则自动复位
    if (window._aiRunning) {
      // 强制恢复：超过 90 秒无 loading 气泡 → 复位；无 loading 气泡 → 复位
      if (!document.getElementById('ai-loading-msg')) {
        window._aiRunning = false;
        // 也移除 is-disabled 类，确保右键菜单可用
        document.querySelectorAll('.context-menu-item').forEach(function(el) {
          if (el.getAttribute('data-action') !== 'copy-coords') el.classList.remove('is-disabled');
        });
      } else {
        return; // AI 正在运行且有加载提示，不打断
      }
    }

    var msg = '', displayMsg = '';
    switch (action) {
      case 'send-location':
      case 'send-location-routed':
        displayMsg = lat + ', ' + lng + ' - 查询地理信息';
        msg = '纬度' + lat + '，经度' + lng + '。\n这是新的坐标，和之前的问题无关。\n请完成以下任务：\n1. 先 search_web 搜索这个位置属于哪个省/市/区/县\n2. 查询附近的地理特征（山脉、河流、湖泊、地形等）\n3. 查询该区域的气候类型、典型海拔、植被等地理信息\n4. 最后用 execute_python 在地图该位置加一个点标记，只加一个点，不要生成多个点位\n5. 回复时用表格形式（markdown 表格），格式如下：\n\n| 项目 | 内容 |\n|------|------|\n| 经度 | 具体数值 |\n| 纬度 | 具体数值 |\n| 所属省份 | XX省 |\n| 所属城市 | XX市 |\n| 所属区县 | XX区/县 |\n| 附近河流 | XXX |\n| 附近山脉 | XXX |\n| 地形特征 | XXX |\n| 气候类型 | XXX |\n| 典型海拔 | XXX米 |\n| 备注 | 其他补充信息 |\n\n尽量多提供该位置的地理相关信息，回复要详细。不要用aoi相关工具，不要提取边界轮廓。';
        break;
    }
    if (msg && window.GIS && window.GIS.chat && window.GIS.chat.send) {
      var selEl = document.getElementById('modelSelector');
      var curProvider = selEl ? selEl.value : 'glm-routed';

      // 检查 API Key
      var _api = window.GIS.api;
      var _key = curProvider === 'agnes' ? (_api ? _api.getAgnesApiKey() : '') : (curProvider === 'glm' || curProvider === 'glm-routed') ? (_api ? _api.getGLMApiKey() : '') : (_api ? _api.getApiKey() : '');
      if (!_key) {
        var _names = { 'deepseek-routed': 'DeepSeek V4 Flash+', 'glm-routed': 'GLM-4.7-Flash+', 'agnes': 'Agnes 2.0 Flash+' };
        if (window.GIS.chat.addMessage) window.GIS.chat.addMessage((_names[curProvider] || curProvider) + ' 未配置 API Key，请点击齿轮按钮配置', 'system');
        return;
      }

      var valEl = document.getElementById('modelSelectValue');
      var names = { 'deepseek-routed': 'DeepSeek V4 Flash+', 'glm-routed': 'GLM-4.7-Flash+', 'agnes': 'Agnes 2.0 Flash+' };
      if (valEl) valEl.textContent = names[curProvider] || curProvider;
      try {
        var _sendResult = window.GIS.chat.send(msg, { displayText: displayMsg || undefined, provider: curProvider });
        if (_sendResult && typeof _sendResult.catch === 'function') {
          _sendResult.catch(function(_err) {
            if (window.GIS.chat && window.GIS.chat.addMessage)
              window.GIS.chat.addMessage('DEM 发送失败: ' + (_err.message || _err), 'system');
          });
        }
      } catch(_e) {
        if (window.GIS.chat && window.GIS.chat.addMessage)
          window.GIS.chat.addMessage('DEM 触发异常: ' + (_e.message || _e), 'system');
      }
    }
  }

  /** 打开/关闭操作手册弹窗 */
  function _openManual() {
    var overlay = document.getElementById('manualOverlay');
    if (overlay) overlay.style.display = 'flex';
  }
  function _closeManual() {
    var overlay = document.getElementById('manualOverlay');
    if (overlay) overlay.style.display = 'none';
  }

  /** 初始化操作手册弹窗交互 */
  function _initManual() {
    var overlay = document.getElementById('manualOverlay');
    if (!overlay) return;
    // 关闭按钮
    var closeBtn = document.getElementById('manualClose');
    if (closeBtn) closeBtn.addEventListener('click', _closeManual);
    // 点击背景关闭
    overlay.addEventListener('click', function(e) { if (e.target === overlay) _closeManual(); });
    // 目录切换
    var nav = document.getElementById('manualNav');
    if (nav) {
      nav.addEventListener('click', function(e) {
        var item = e.target.closest('.manual-nav-item');
        if (!item) return;
        var section = item.getAttribute('data-section');
        if (!section) return;
        nav.querySelectorAll('.manual-nav-item').forEach(function(n) { n.classList.remove('active'); });
        item.classList.add('active');
        var content = document.getElementById('manualContent');
        if (content) {
          content.querySelectorAll('.manual-section').forEach(function(s) { s.style.display = 'none'; });
          var target = document.getElementById('section-' + section);
          if (target) target.style.display = '';
        }
      });
    }
  }

  /** 初始化顶部菜单栏交互 */
  function _initMapMenu() {
    var menuBar = document.getElementById('mapMenuBar');
    if (!menuBar) return;

    menuBar.addEventListener('click', function(e) {
      // 菜单项点击优先
      var item = e.target.closest('.map-menu-item');
      if (item) {
        var action = item.getAttribute('data-action');
        if (action) {
          _handleMenuAction(action);
          menuBar.querySelectorAll('.map-menu-trigger.open').forEach(function(t) { t.classList.remove('open'); });
          e.stopPropagation();
        }
        return;
      }
      // 菜单触发器（展开/收起下拉）
      var trigger = e.target.closest('.map-menu-trigger');
      if (trigger) {
        var isOpen = trigger.classList.contains('open');
        menuBar.querySelectorAll('.map-menu-trigger.open').forEach(function(t) { t.classList.remove('open'); });
        if (!isOpen) trigger.classList.add('open');
        e.stopPropagation();
      }
    });
    // 点击菜单外部关闭所有
    document.addEventListener('click', function() {
      menuBar.querySelectorAll('.map-menu-trigger.open').forEach(function(t) { t.classList.remove('open'); });
    });
  }

  /** 初始化快捷栏状态（从 localStorage 恢复） */
  function _initShortcuts() {
    var defaults = { 'draw': false, 'tools': true };
    ['draw', 'tools'].forEach(function(group) {
      var val = localStorage.getItem('gis_shortcut_' + group);
      if (val === null) val = defaults[group] ? '1' : '0';
      var show = val === '1';
      _applyShortcutGroup(group, show);
    });
  }

  /** 应用快捷栏组的显隐 */
  function _applyShortcutGroup(group, show) {
    document.querySelectorAll('[data-shortcut-group="' + group + '"]').forEach(function(el) {
      el.classList.toggle('shortcut-hidden', !show);
    });
    // 更新菜单项勾选图标
    var menuBtn = document.querySelector('.map-menu-item-shortcut[data-action="shortcut-' + group + '"] .shortcut-check');
    if (menuBtn) {
      if (show) {
        menuBtn.style.opacity = '1';
      } else {
        menuBtn.style.opacity = '0.25';
      }
    }
  }

  /** 切换快捷栏组 */
  function _toggleShortcutGroup(group) {
    var oldVal = localStorage.getItem('gis_shortcut_' + group);
    var show = oldVal !== '1';
    localStorage.setItem('gis_shortcut_' + group, show ? '1' : '0');
    _applyShortcutGroup(group, show);
  }

  /** 执行菜单项动作 */
  function _handleMenuAction(action) {
    switch (action) {
      case 'import':
        var uploadBtn = document.getElementById('uploadTrigger') || document.getElementById('uploadTriggerBtn');
        if (uploadBtn) uploadBtn.click();
        break;
      case 'export':
        if (window.downloadGeoJSON) window.downloadGeoJSON();
        break;
      case 'save-project':
        var saveBtn = document.querySelector('[data-action="save"]');
        if (saveBtn) { saveBtn.click(); } else {
          var projectSave = document.getElementById('projectSave');
          if (projectSave) projectSave.click();
        }
        break;
      case 'load-project':
        var historyBtn = document.getElementById('historyBtn');
        if (historyBtn) historyBtn.click();
        break;
      case 'shortcut-draw':
        _toggleShortcutGroup('draw');
        break;
      case 'shortcut-tools':
        _toggleShortcutGroup('tools');
        break;
      case 'tool-polygon':
      case 'tool-rectangle':
      case 'tool-circle':
      case 'tool-polyline':
      case 'tool-marker':
      case 'tool-feature-info':
      case 'tool-delete':
        var tool = action.replace('tool-', '');
        var btn = document.querySelector('.map-draw-btn[data-tool="' + tool + '"]');
        if (btn) {
          if (btn.classList.contains('shortcut-hidden')) {
            var group = btn.getAttribute('data-shortcut-group');
            if (group) { _applyShortcutGroup(group, true); localStorage.setItem('gis_shortcut_' + group, '1'); }
          }
          btn.click();
        }
        break;
      case 'toggle-layer-panel':
        var layerBtn = document.getElementById('toggleLayerPanel');
        if (layerBtn) layerBtn.click();
        break;
      case 'toggle-coords':
        var coordsEl = document.querySelector('.map-coords');
        if (coordsEl) {
          var nowHidden = coordsEl.style.display === 'none';
          coordsEl.style.display = nowHidden ? '' : 'none';
          var check = document.querySelector('.map-menu-item-toggle[data-action="toggle-coords"] .toggle-check');
          if (check) check.classList.toggle('off', !nowHidden);
        }
        break;
      case 'switch-basemap':
        var newType = _currentBaseMap === 'satellite' ? 'light' : 'satellite';
        switchBaseMap(newType);
        break;
      case 'toggle-attr-table':
        var attrBtn = document.getElementById('toggleAttrTable');
        if (attrBtn) { attrBtn.click(); }
        break;
      case 'manual':
        _openManual();
        break;
    }
  }

  /** 应用符号化样式（按要素索引的样式映射） */
  function applySymbology(name, geojson, styleMap) {
    if (!mapInstance || !layers[name]) return;

    // 重新加载 GeoJSON 并应用每要素样式
    var features = [];
    if (geojson.type === 'FeatureCollection') features = geojson.features || [];
    else if (geojson.type === 'Feature') features = [geojson];

    // 移除旧图层
    if (layers[name]) mapInstance.removeLayer(layers[name]);

    // 清除旧要素映射
    Object.keys(_featureMap).forEach(function(k) {
      if (k.startsWith(name + ':')) delete _featureMap[k];
    });

    var layer = L.geoJSON(geojson, {
      style: function(feature) {
        var idx = features.indexOf(feature);
        var custom = styleMap ? styleMap[idx] : null;
        if (custom) {
          return {
            color: custom.color || '#1c1b1b',
            weight: custom.weight !== undefined ? custom.weight : 2,
            fillColor: custom.fillColor || '#1c1b1b',
            fillOpacity: custom.fillOpacity !== undefined ? custom.fillOpacity : 0.1,
            radius: custom.radius !== undefined ? custom.radius : 2.5,
          };
        }
        return { color: '#1c1b1b', weight: 2, fillColor: '#1c1b1b', fillOpacity: 0.1, radius: 2.5 };
      },
      pointToLayer: function(feature, latlng) {
        var idx = features.indexOf(feature);
        var custom = styleMap ? styleMap[idx] : null;
        var r = (custom && custom.radius) ? custom.radius : 2.5;
        var c = (custom && custom.color) ? custom.color : '#1c1b1b';
        return L.circleMarker(latlng, {
          radius: r, fillColor: c, color: c, weight: custom && custom.weight !== undefined ? custom.weight : 0,
          opacity: 1, fillOpacity: custom && custom.fillOpacity !== undefined ? custom.fillOpacity : 1,
        });
      },
      coordsToLatLng: function(coords) {
        var lng = coords[0], lat = coords[1];
        if (Math.abs(lat) > 90 && Math.abs(lng) <= 90) return L.latLng(lng, lat);
        return L.latLng(lat, lng);
      },
      onEachFeature: function(feature, leafletLayer) {
        var idx = features.indexOf(feature);
        if (idx === -1) return;
        var key = name + ':' + idx;
        _featureMap[key] = leafletLayer;

        leafletLayer.on('click', function(e) {
          if (!_featureInfoActive) return;
          clearHighlight();
          _highlightFeature(leafletLayer);
          var props = feature.properties || {};
          var title = props.name || props.id || props.NAME || '要素 #' + (idx + 1);
          var html = '<div class="feat-popup">';
          html += '<strong>' + escapeHtml(String(title)) + '</strong>';
          var count = 0;
          for (var k in props) {
            if (count++ >= 5) break;
            var v = props[k];
            html += '<div class="feat-popup-row"><span>' + escapeHtml(k) + '</span><span>' + (v === null || v === undefined ? '' : escapeHtml(String(v))) + '</span></div>';
          }
          html += '<div class="feat-popup-footer">';
          html += '<span class="feat-popup-idx">#' + (idx + 1) + ' / ' + features.length + '</span>';
          html += '<span style="color:var(--ui-gray-300);font-size:10px;">' + escapeHtml(name) + '</span>';
          html += '</div></div>';
          leafletLayer.bindPopup(html, { className: 'feat-popup-wrap', closeButton: true, maxWidth: 300, offset: L.point(0, -8) }).openPopup();
        });
      },
    });
    layer.addTo(mapInstance);
    layers[name] = layer;
    geoStore[name] = { geojson: geojson, style: null };
    // 缩放到图层范围
    try { mapInstance.fitBounds(layer.getBounds(), { padding: [30, 30], maxZoom: 16 }); } catch(e) {}
  }

  GIS.map = {
    init: init,
    loadGeoJSON: loadGeoJSON,
    switchBaseMap: switchBaseMap,
    applySymbology: applySymbology,
    removeLayer: removeLayer,
    setLayerVisible: setLayerVisible,
    setLayerColor: setLayerColor,
    getLayer: getLayer,
    toggleLayer: toggleLayer,
    flyTo: flyTo,
    fitLayer: fitLayer,
    loadHeatmap: loadHeatmap,
    removeHeatmap: removeHeatmap,
    clearHighlight: clearHighlight,
    highlightLayerFeature: highlightLayerFeature,
    invalidateSize: function() { if (mapInstance) mapInstance.invalidateSize(); },
    getInstance: function() { return mapInstance; },
    // 以下为兼容旧内联脚本
    getState: function() {
      if (!mapInstance) return null;
      return { center: mapInstance.getCenter(), zoom: mapInstance.getZoom() };
    },
    setView: function(center, zoom) {
      if (!mapInstance) return;
      mapInstance.setView(center, zoom);
    },
    getMap: function() { return mapInstance; },
    _openManual: function() { _openManual(); },
  };
})();
