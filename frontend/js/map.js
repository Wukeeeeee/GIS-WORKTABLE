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
var _labelConfigs = {};
var _patternsInited = false;  // SVG pattern defs 是否已注入
var _rasterLayers = {};       // { name: ImageOverlay }
var _northArrowControl = null;       // { name: {field, fontSize, color} } — 标注配置
var _undoStack = [];          // [{name, geojson}]
var _redoStack = [];
var _undoMax = 50;
var _undoSkip = false;
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
      preferCanvas: true,  // Canvas 渲染，大幅提升大数据性能
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

    // 比例尺控件
    L.control.scale({position: 'bottomleft', metric: true, imperial: false}).addTo(mapInstance);

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

    // 阻止浏览器默认右键菜单
    el.addEventListener('contextmenu', function(e) { e.preventDefault(); });
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
              mapInstance._drawHandler = new DrawClass(mapInstance, {
                snap: true, snapDistance: 15
              });
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

          if (tool === 'network-analysis') {
            if (GIS.network && GIS.network.toggle) GIS.network.toggle();
            return;
          }
          if (tool === 'spatial-analysis') {
            if (GIS.spatial && GIS.spatial.toggle) GIS.spatial.toggle();
            return;
          }
          if (tool === 'convert-crs') {
            if (window.GIS.chat) {
              window.GIS.chat.addMessage('坐标转换：发送"将[图层]转为Web Mercator" 或 "转换坐标 116.4,39.9 到web_mercator" 到聊天', 'system');
            }
            return;
          }
          if (tool === 'terrain-profile') {
            if (window.GIS.chat) {
              window.GIS.chat.addMessage('地形剖面：发送"查看[图层]的地形剖面" 或 "绘制断面并沿线提取高程" 到聊天', 'system');
            }
            return;
          }
          if (tool === 'debug-panel') {
            if (GIS.debug && GIS.debug.toggle) GIS.debug.toggle();
            return;
          }

          // 启用手动绘制工具（启用顶点捕捉）
          var snapOpts = { snap: true, snapDistance: 15 };
          var DrawClass = { polygon: L.Draw.Polygon, rectangle: L.Draw.Rectangle,
            circle: L.Draw.Circle, polyline: L.Draw.Polyline, marker: L.Draw.Marker }[tool];
          if (DrawClass) {
            mapInstance._drawHandler = new DrawClass(mapInstance, snapOpts);
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
    var isLarge = featCount > 5000;

    // 大数据使用 VectorGrid 瓦片渲染（Canvas + 按需加载，不生成 DOM 节点）
    var layer;
    if (isLarge && typeof L.vectorGrid !== 'undefined') {
      layer = L.vectorGrid.slicer(geojson, {
        rendererFactory: L.canvas.tile,
        vectorTileLayerStyles: {
          sliced: function(properties, zoom) {
            var w = zoom > 15 ? 3 : (zoom > 12 ? 2 : 1);
            return { color: mergedStyle.color, weight: w, opacity: 0.8 };
          },
        },
        maxZoom: 18,
        minZoom: 4,
        interactive: false,
      });
      console.log('[GIS Map] 大数据模式(VectorGrid):', name, featCount, '个要素');
    } else {
      layer = L.geoJSON(geojson, {
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
        onEachFeature: featCount > 5000 ? null : function(feature, leafletLayer) {
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
  }
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
    if (_rasterLayers[name]) {
      mapInstance.removeLayer(_rasterLayers[name]);
      delete _rasterLayers[name];
      delete layers[name];
      return;
    }
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

  /** 修改图层完整样式（颜色/透明度/线宽） */
  function setLayerStyle(name, style) {
    var layer = layers[name];
    if (!layer && drawnItems) {
      drawnItems.eachLayer(function(l) {
        if (l._name === name) layer = l;
      });
      if (layer) layers[name] = layer;
    }
    if (!layer) return;
    var opts = {};
    if (style.color) { opts.color = style.color; opts.fillColor = style.color; }
    if (style.opacity !== undefined) { opts.opacity = style.opacity; opts.fillOpacity = style.opacity; }
    if (style.weight !== undefined) { opts.weight = style.weight; }
    if (style.fillPattern) {
      opts.fillPattern = style.fillPattern;
    }
    if (typeof layer.setStyle === 'function') {
      layer.setStyle(opts);
    }
    if (geoStore[name]) geoStore[name].style = { ...(geoStore[name].style || {}), ...opts };
    // 对面要素应用填充图案（SVG 渲染器）
    if (opts.fillPattern && layer._path) {
      _ensureFillPatterns();
      var patternId = 'fp-' + opts.fillPattern;
      if (layer._path.setAttribute) {
        layer._path.setAttribute('fill', 'url(#' + patternId + ')');
        if (opts.fillColor) layer._path.setAttribute('fill-pattern-color', opts.fillColor);
      }
    }
  }

  /** 向地图 SVG 注入 fill pattern defs */
  function _ensureFillPatterns() {
    if (_patternsInited) return;
    var mapPanes = mapInstance && mapInstance.getPanes();
    var svgRoot = mapPanes && (mapPanes.overlayPane || mapPanes.mapPane);
    if (!svgRoot) return;
    var svg = svgRoot.querySelector('svg');
    if (!svg) return;
    var defs = svg.querySelector('defs');
    if (!defs) {
      defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      svg.insertBefore(defs, svg.firstChild);
    }
    var defsXml = [
      '<pattern id="fp-hatch" width="16" height="16" patternUnits="userSpaceOnUse"><path d="M0 0L16 16M8-4L20 4M-4 8L4 20" stroke="currentColor" stroke-width="1" fill="none"/></pattern>',
      '<pattern id="fp-crosshatch" width="16" height="16" patternUnits="userSpaceOnUse"><path d="M0 0L16 16M16 0L0 16" stroke="currentColor" stroke-width="1" fill="none"/></pattern>',
      '<pattern id="fp-dots" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="4" cy="4" r="2" fill="currentColor"/><circle cx="12" cy="12" r="2" fill="currentColor"/><circle cx="12" cy="4" r="2" fill="currentColor"/><circle cx="4" cy="12" r="2" fill="currentColor"/></pattern>',
      '<pattern id="fp-grid" width="16" height="16" patternUnits="userSpaceOnUse"><path d="M8 0L8 16M0 8L16 8" stroke="currentColor" stroke-width="0.5" fill="none"/></pattern>',
      '<pattern id="fp-diagonal" width="16" height="16" patternUnits="userSpaceOnUse"><path d="M0 16L16 0M-4 10L10-4M6 20L20 6" stroke="currentColor" stroke-width="1" fill="none"/></pattern>',
    ];
    var temp = document.createElement('div');
    temp.innerHTML = defsXml.join('');
    while (temp.firstChild) defs.appendChild(temp.firstChild);
    _patternsInited = true;
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
      case 'tool-network-analysis':
        if (GIS.network && GIS.network.toggle) GIS.network.toggle();
        break;
      case 'tool-spatial-analysis':
        if (GIS.spatial && GIS.spatial.toggle) GIS.spatial.toggle();
        break;
      case 'tool-debug-panel':
        if (GIS.debug && GIS.debug.toggle) GIS.debug.toggle();
        break;
      case 'toggle-attr-table':
        var attrBtn = document.getElementById('toggleAttrTable');
        if (attrBtn) { attrBtn.click(); }
        break;
      case 'manual':
        _openManual();
        break;
      // 新功能菜单项 — 转接到斜杠命令
      case 'tool-coord-convert':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('coord-convert');
        break;
      case 'tool-topology':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('topology');
        break;
      case 'tool-slope':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('slope');
        break;
      case 'tool-aspect':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('aspect');
        break;
      case 'tool-hillshade':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('hillshade');
        break;
      case 'tool-contour':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('contour');
        break;
      case 'tool-ndvi':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('ndvi');
        break;
      case 'tool-rastercalc':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('rastercalc');
        break;
      case 'tool-interpolate':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('interpolate');
        break;
      case 'tool-hydrology':
        if (GIS.chat && GIS.chat.triggerSlash) GIS.chat.triggerSlash('hydrology');
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
    // 重应用标注
    _applyLabelsForLayer(name);
  }

  /** 给指定图层绑定永久标注（Leaflet tooltip） */
  function _applyLabelsForLayer(name) {
    if (!_labelConfigs[name]) return;
    var cfg = _labelConfigs[name];
    if (!layers[name]) return;
    var gj = geoStore[name] && geoStore[name].geojson;
    if (!gj) return;
    var features = gj.type === 'FeatureCollection' ? gj.features : [gj];
    Object.keys(_featureMap).forEach(function(key) {
      if (!key.startsWith(name + ':')) return;
      var leaf = _featureMap[key];
      if (!leaf) return;
      var idx = parseInt(key.split(':')[1], 10);
      if (isNaN(idx) || idx >= features.length) return;
      var props = features[idx].properties || {};
      var txt = String(props[cfg.field] || '');
      if (!txt) return;
      leaf.bindTooltip(txt, {
        permanent: true, direction: 'center',
        className: 'layer-label',
        offset: [0, 0],
      });
    });
  }

  /** 对图层添加/更新标注 */
  function setLabels(name, field, fontSize, color) {
    _labelConfigs[name] = { field: field, fontSize: fontSize || 12, color: color || '#333333' };
    _applyLabelsForLayer(name);
  }

  /** 清除图层标注 */
  function clearLabels(name) {
    delete _labelConfigs[name];
    if (!layers[name]) return;
    Object.keys(_featureMap).forEach(function(key) {
      if (!key.startsWith(name + ':')) return;
      var leaf = _featureMap[key];
      if (leaf && leaf.unbindTooltip) leaf.unbindTooltip();
    });
  }

  function showNorthArrow() {
    hideNorthArrow();
    var NorthArrowControl = L.Control.extend({
      options: { position: 'topright' },
      onAdd: function() {
        var div = L.DomUtil.create('div', 'north-arrow-container');
        div.innerHTML = '<div style="background:rgba(255,255,255,0.9);border:1px solid #ccc;border-radius:4px;padding:6px;text-align:center;cursor:default;box-shadow:0 1px 5px rgba(0,0,0,0.2)">' +
          '<div style="font-size:18px;line-height:1;color:#c0392b">&#x2191;</div>' +
          '<div style="font-size:10px;color:#666;margin-top:2px">N</div>' +
          '</div>';
        L.DomEvent.disableClickPropagation(div);
        return div;
      }
    });
    _northArrowControl = new NorthArrowControl().addTo(mapInstance);
  }

  function hideNorthArrow() {
    if (_northArrowControl && mapInstance) {
      mapInstance.removeControl(_northArrowControl);
      _northArrowControl = null;
    }
  }

  /** 栅格图层（GeoTIFF 转换后的 PNG） */
  function addImageOverlay(url, bounds, name, layerId) {
    if (!mapInstance) return;
    var southWest = L.latLng(bounds[1], bounds[0]);
    var northEast = L.latLng(bounds[3], bounds[2]);
    var imageBounds = L.latLngBounds(southWest, northEast);
    var overlay = L.imageOverlay(url, imageBounds, {
      opacity: 1.0,
      attribution: name
    }).addTo(mapInstance);
    _rasterLayers[name] = overlay;
    _rasterLayers[layerId] = overlay;
    layers[name] = overlay;
    layers[layerId] = overlay;
    mapInstance.fitBounds(imageBounds);
  }

  function removeRasterLayer(name) {
    if (_rasterLayers[name]) {
      mapInstance.removeLayer(_rasterLayers[name]);
      delete _rasterLayers[name];
      delete layers[name];
    }
  }

  /** 折点编辑模式 */
  var _editModeName = null;

  function enterEditMode(name) {
    if (!mapInstance || !drawnItems) return;
    var gs = geoStore[name];
    if (!gs) return;
    _exitEditMode(); // 先退出已有编辑

    var geojson = gs.geojson;
    var features = geojson.type === 'FeatureCollection' ? (geojson.features || []) : [geojson];
    if (!features.length) return;

    // 隐藏原图层
    if (layers[name]) mapInstance.removeLayer(layers[name]);

    // 清空 drawnItems 并填入要素
    drawnItems.clearLayers();
    _editModeName = name;

    features.forEach(function(f, idx) {
      var leaf;
      var geom = f.geometry;
      if (!geom) return;
      switch (geom.type) {
        case 'Point':
          leaf = L.circleMarker([geom.coordinates[1], geom.coordinates[0]], { radius: 6, fillColor: '#e74c3c', color: '#e74c3c', weight: 2, fillOpacity: 0.6 });
          break;
        case 'LineString':
          leaf = L.polyline(geom.coordinates.map(function(c) { return [c[1], c[0]]; }), { color: '#e74c3c', weight: 3 });
          break;
        case 'Polygon':
          leaf = L.polygon(geom.coordinates[0].map(function(c) { return [c[1], c[0]]; }), { color: '#e74c3c', weight: 2, fillColor: '#e74c3c', fillOpacity: 0.1 });
          break;
        case 'MultiPoint':
          leaf = L.featureGroup(geom.coordinates.map(function(c) { return L.circleMarker([c[1], c[0]], { radius: 5 }); }));
          break;
        case 'MultiLineString':
          leaf = L.featureGroup(geom.coordinates.map(function(line) { return L.polyline(line.map(function(c) { return [c[1], c[0]]; })); }));
          break;
        case 'MultiPolygon':
          leaf = L.featureGroup(geom.coordinates.map(function(poly) { return L.polygon(poly[0].map(function(c) { return [c[1], c[0]]; })); }));
          break;
        default:
          return;
      }
      leaf._editIdx = idx;
      leaf._editName = name;
      leaf._editOrigProps = f.properties || {};
      drawnItems.addLayer(leaf);
    });

    // 启用编辑
    drawnItems.editing.enable();

    // 监听编辑事件
    mapInstance.on(L.Draw.Event.EDITSTOP, _onEditStop);

    // 添加保存/取消控制条
    _addEditControls(name);
  }

  function _addEditControls(name) {
    var existing = document.getElementById('edit-controls');
    if (existing) existing.remove();
    var div = L.DomUtil.create('div', 'edit-controls-bar', document.getElementById('map'));
    div.id = 'edit-controls';
    div.innerHTML =
      '<div style="background:rgba(255,255,255,0.95);border:1px solid #ddd;border-radius:8px;padding:8px 14px;display:flex;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(0,0,0,0.15);z-index:1000;font-size:13px;position:absolute;top:12px;left:50%;transform:translateX(-50%)">' +
      '<span style="color:#333;font-weight:500">折点编辑: ' + escapeHtml(name) + '</span>' +
      '<button id="edit-save-btn" style="background:#27ae60;color:#fff;border:none;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px">保存</button>' +
      '<button id="edit-cancel-btn" style="background:#bdc3c7;color:#333;border:none;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px">取消</button>' +
      '</div>';
    L.DomEvent.disableClickPropagation(div);
    document.getElementById('edit-save-btn').onclick = function() { _saveEdit(name); };
    document.getElementById('edit-cancel-btn').onclick = function() { _exitEditMode(); };
  }

  function _onEditStop() {
    // 编辑停止时不自动退出，等待用户点保存或取消
  }

  function _saveEdit(name) {
    if (!drawnItems || !_editModeName) return;
    var features = [];
    drawnItems.eachLayer(function(leaf) {
      var geom = null;
      if (leaf instanceof L.CircleMarker || leaf instanceof L.Marker) {
        var ll = leaf.getLatLng();
        geom = { type: 'Point', coordinates: [ll.lng, ll.lat] };
      } else if (leaf instanceof L.Polyline || leaf instanceof L.Polygon) {
        var latlngs = leaf.getLatLngs();
        if (leaf instanceof L.Polygon) {
          geom = { type: 'Polygon', coordinates: [latlngs[0].map(function(ll) { return [ll.lng, ll.lat]; })] };
        } else {
          geom = { type: 'LineString', coordinates: latlngs.map(function(ll) { return [ll.lng, ll.lat]; }) };
        }
      } else if (leaf instanceof L.FeatureGroup) {
        // Multi* types — skip reconstruction for now
        return;
      }
      if (geom) {
        features.push({ type: 'Feature', geometry: geom, properties: leaf._editOrigProps || {} });
      }
    });
    if (!features.length) { _exitEditMode(); return; }

    var updated = features.length === 1 ? features[0] : { type: 'FeatureCollection', features: features };
    geoStore[name] = { geojson: updated, style: geoStore[name] ? geoStore[name].style : {} };

    // 退出编辑模式并重新加载
    _exitEditMode();
    loadGeoJSON(updated, name, geoStore[name].style);
  }

  function _exitEditMode() {
    if (!drawnItems) return;
    drawnItems.editing.disable();
    drawnItems.clearLayers();
    mapInstance.off(L.Draw.Event.EDITSTOP, _onEditStop);
    _editModeName = null;
    var ctrl = document.getElementById('edit-controls');
    if (ctrl) ctrl.remove();
  }

  function exitEditMode() {
    _exitEditMode();
  }

  /** 导出地图为图片 */
  function exportMap(format) {
    if (!mapInstance) return;
    format = format || 'png';
    var mapEl = document.getElementById('map');
    if (!mapEl) return;
    var w = mapEl.clientWidth;
    var h = mapEl.clientHeight;
    if (!w || !h) return;

    var canvas = document.createElement('canvas');
    canvas.width = w * 2;
    canvas.height = h * 2;
    var ctx = canvas.getContext('2d');
    ctx.scale(2, 2);

    ctx.fillStyle = '#f8f8f8';
    ctx.fillRect(0, 0, w, h);

    try {
      var tiles = mapEl.querySelectorAll('.leaflet-tile-loaded img, .leaflet-tile img');
      tiles.forEach(function(img) {
        if (!img.complete || !img.naturalWidth) return;
        var left = parseInt(img.style.left) || 0;
        var top = parseInt(img.style.top) || 0;
        ctx.drawImage(img, left, top, img.naturalWidth, img.naturalHeight);
      });
    } catch(e) {}

    try {
      var renderer = mapInstance.getRenderer();
      if (renderer && renderer._container) {
        ctx.drawImage(renderer._container, 0, 0);
      }
    } catch(e) {}

    try {
      if (drawnItems) {
        drawnItems.eachLayer(function(l) {
          if (l._container && l._container instanceof HTMLCanvasElement) {
            ctx.drawImage(l._container, 0, 0);
          }
        });
      }
    } catch(e) {}

    ctx.fillStyle = 'rgba(0,0,0,0.45)';
    ctx.fillRect(0, h - 20, w, 20);
    ctx.fillStyle = '#fff';
    ctx.font = '11px sans-serif';
    ctx.fillText('GIS WorkTable · ' + new Date().toISOString().slice(0, 10), 8, h - 7);

    var mime = format === 'jpg' ? 'image/jpeg' : 'image/png';
    var dataUrl = canvas.toDataURL(mime, 0.92);
    var link = document.createElement('a');
    link.download = 'map_export_' + Date.now() + '.' + format;
    link.href = dataUrl;
    link.click();
  }

  /** 导出地图为 PDF（通过浏览器打印布局） */
  function exportPdf(title) {
    if (!mapInstance) return;
    title = title || '地图导出';
    var mapEl = document.getElementById('map');
    if (!mapEl) return;

    var mapData = _captureMapCanvas();
    if (!mapData) return;

    var now = new Date();
    var dateStr = now.toLocaleDateString('zh-CN');
    var center = mapInstance.getCenter();
    var zoom = mapInstance.getZoom();
    var layers = (window.GIS.layers && window.GIS.layers.getLayers) ? window.GIS.layers.getLayers() : [];

    var html = '<!DOCTYPE html><html><head><meta charset="utf-8">' +
      '<title>' + escapeHtml(title) + '</title>' +
      '<style>' +
      '@page { size: A4 landscape; margin: 20mm; }' +
      'body { font-family: "Microsoft YaHei", sans-serif; margin: 0; padding: 20px; color: #333; }' +
      '.header { text-align: center; margin-bottom: 16px; }' +
      '.header h1 { font-size: 22px; margin: 0 0 4px 0; font-weight: 600; }' +
      '.header .meta { font-size: 12px; color: #888; }' +
      '.map-container { border: 1px solid #ccc; page-break-inside: avoid; }' +
      '.map-container img { width: 100%; height: auto; display: block; }' +
      '.footer { display: flex; justify-content: space-between; margin-top: 14px; font-size: 11px; color: #666; }' +
      '.footer .legend { flex: 1; }' +
      '.footer .scale { text-align: right; }' +
      '.north-arrow { display: inline-block; font-size: 28px; color: #c0392b; margin-right: 12px; line-height: 1; }' +
      '@media print { body { padding: 0; } }' +
      '</style></head><body>' +
      '<div class="header"><h1>' + escapeHtml(title) + '</h1>' +
      '<div class="meta">' + dateStr + ' | 中心: ' + center.lat.toFixed(4) + ', ' + center.lng.toFixed(4) + ' | 缩放: ' + zoom + '</div></div>' +
      '<div class="map-container"><img src="' + mapData + '" alt="地图"></div>' +
      '<div class="footer"><div class="legend">' +
      (layers.length ? '<strong>图层:</strong> ' + layers.map(function(l) { return l.filename; }).join(' · ') : '') +
      '</div><div class="scale"><span class="north-arrow">&#x2191;</span> N</div></div>' +
      '<script>window.onload=function(){setTimeout(function(){window.print()},500)}<' + '/script>' +
      '</body></html>';

    var win = window.open('', '_blank', 'width=900,height=700');
    if (win) {
      win.document.write(html);
      win.document.close();
    }
  }

  /** 内部：捕获地图 Canvas 数据 */
  function _captureMapCanvas() {
    var mapEl = document.getElementById('map');
    if (!mapEl) return null;
    var w = mapEl.clientWidth, h = mapEl.clientHeight;
    if (!w || !h) return null;
    var canvas = document.createElement('canvas');
    canvas.width = w * 2;
    canvas.height = h * 2;
    var ctx = canvas.getContext('2d');
    ctx.scale(2, 2);
    ctx.fillStyle = '#f8f8f8';
    ctx.fillRect(0, 0, w, h);
    try {
      mapEl.querySelectorAll('.leaflet-tile-loaded img, .leaflet-tile img').forEach(function(img) {
        if (!img.complete || !img.naturalWidth) return;
        ctx.drawImage(img, parseInt(img.style.left) || 0, parseInt(img.style.top) || 0, img.naturalWidth, img.naturalHeight);
      });
    } catch(e) {}
    try {
      var renderer = mapInstance.getRenderer();
      if (renderer && renderer._container) ctx.drawImage(renderer._container, 0, 0);
    } catch(e) {}
    try {
      if (drawnItems) drawnItems.eachLayer(function(l) {
        if (l._container && l._container instanceof HTMLCanvasElement) ctx.drawImage(l._container, 0, 0);
      });
    } catch(e) {}
    return canvas.toDataURL('image/png', 0.95);
  }

  /** 快照当前所有地图状态到撤销栈 */
  function _snapshot() {
    var snap = {};
    Object.keys(geoStore).forEach(function(k) {
      snap[k] = JSON.parse(JSON.stringify(geoStore[k]));
    });
    return snap;
  }

  /** 保存快照（在修改前调用） */
  function _saveUndoSnap() {
    if (_undoSkip) return;
    _undoStack.push(_snapshot());
    if (_undoStack.length > _undoMax) _undoStack.shift();
    _redoStack = [];
  }

  /** 恢复到指定快照 */
  function _restoreSnap(snap) {
    Object.keys(geoStore).forEach(function(k) { delete geoStore[k]; });
    Object.keys(snap).forEach(function(k) { geoStore[k] = snap[k]; });
    _undoSkip = true;
    Object.keys(geoStore).forEach(function(k) {
      if (geoStore[k] && geoStore[k].geojson && layers[k]) {
        loadGeoJSON(geoStore[k].geojson, k, geoStore[k].style || {});
      }
    });
    _undoSkip = false;
  }

  /** 撤销 */
  function undo() {
    if (_undoStack.length === 0) return;
    var current = _snapshot();
    _redoStack.push(current);
    var snap = _undoStack.pop();
    _restoreSnap(snap);
    if (window.GIS.chat) window.GIS.chat.addMessage('已撤销上一步操作', 'system');
  }

  /** 重做 */
  function redo() {
    if (_redoStack.length === 0) return;
    var current = _snapshot();
    _undoStack.push(current);
    var snap = _redoStack.pop();
    _restoreSnap(snap);
    if (window.GIS.chat) window.GIS.chat.addMessage('已重做操作', 'system');
  }

  /** 修改 loadGeoJSON 以支持撤销快照（在加载前保存状态） */
  var _origLoadGeoJSON = loadGeoJSON;
  loadGeoJSON = function(geojson, name, style) {
    if (!_undoSkip && name && geoStore[name]) {
      _saveUndoSnap();
    }
    return _origLoadGeoJSON(geojson, name, style);
  };

  /** 键盘快捷键（CTRL+Z / CTRL+SHIFT+Z） */
  function _initKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
      if (!e.ctrlKey && !e.metaKey) return;
      if (e.shiftKey && (e.key === 'z' || e.key === 'Z')) {
        e.preventDefault();
        redo();
        return;
      }
      if (e.key === 'z' || e.key === 'Z') {
        e.preventDefault();
        undo();
      }
    });
  }

  // 在 init 中调用快捷键初始化
  var _origInit = init;
  init = function(container, options) {
    _origInit(container, options);
    _initKeyboardShortcuts();
  };

  GIS.map = {
    init: init,
    loadGeoJSON: loadGeoJSON,
    switchBaseMap: switchBaseMap,
    applySymbology: applySymbology,
    removeLayer: removeLayer,
    setLayerVisible: setLayerVisible,
    setLayerColor: setLayerColor,
    setLayerStyle: setLayerStyle,
    getLayer: getLayer,
    toggleLayer: toggleLayer,
    flyTo: flyTo,
    fitLayer: fitLayer,
    loadHeatmap: loadHeatmap,
    removeHeatmap: removeHeatmap,
    clearHighlight: clearHighlight,
    highlightLayerFeature: highlightLayerFeature,
    setLabels: setLabels,
    clearLabels: clearLabels,
    showNorthArrow: showNorthArrow,
    hideNorthArrow: hideNorthArrow,
    addImageOverlay: addImageOverlay,
    removeRasterLayer: removeRasterLayer,
    enterEditMode: enterEditMode,
    exitEditMode: exitEditMode,
    exportMap: exportMap,
    exportPdf: exportPdf,
    undo: undo,
    redo: redo,
    invalidateSize: function() { if (mapInstance) mapInstance.invalidateSize(); },
    getInstance: function() { return mapInstance; },
    startTimeAnimation: function(name, timeField, timeValues, intervalMs) {
      if (!mapInstance || !timeValues || timeValues.length < 2) return;
      var targetLayer = null;
      mapInstance.eachLayer(function(l) {
        if (l._name && String(l._name).indexOf(name) >= 0) targetLayer = l;
        if (l.name && String(l.name).indexOf(name) >= 0) targetLayer = l;
      });
      if (!targetLayer) {
        if (window.GIS.chat) { window.GIS.chat.addMessage('未找到图层: ' + name, 'system'); }
        return;
      }
      var idx = 0;
      if (window._timeAnimTimer) clearInterval(window._timeAnimTimer);
      window._timeAnimTimer = setInterval(function() {
        idx = (idx + 1) % timeValues.length;
        var val = timeValues[idx];
        targetLayer.eachLayer(function(f) {
          var fv = f.feature && f.feature.properties ? String(f.feature.properties[timeField] || '') : '';
          var match = fv === val;
          if (mapInstance.hasLayer(f)) {
            if (!match) mapInstance.removeLayer(f);
          } else {
            if (match) mapInstance.addLayer(f);
          }
        });
      }, intervalMs || 500);
      if (window.GIS.chat) {
        window.GIS.chat.addMessage('时序动画播放中，共' + timeValues.length + '帧', 'system');
      }
    },
    enableChartLink: function(name, chartField) {
      if (!mapInstance) return;
      mapInstance.eachLayer(function(l) {
        if (!l.feature || !l.feature.properties) return;
        var v = l.feature.properties[chartField];
        if (v !== undefined && v !== null) {
          l.bindTooltip(String(v), {permanent: false, direction: 'top'});
        }
      });
      if (window.GIS.chat) {
        window.GIS.chat.addMessage('图表联动已启用（字段: ' + chartField + '）', 'system');
      }
    },
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
