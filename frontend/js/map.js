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
  let mapInstance = null;
  const layers = {};
  const geoStore = {};
  let baseLayer = null;
  // 缓存 DOM 引用——避免每次 mousemove 都 querySelector
  var _coordsEl = null;
  var _zoomLabelEl = null;

  var TILE_URL = 'https://t1.dynamic.tiles.ditu.live.com/comp/ch/{q}?mkt=zh-CN&ur=cn&it=A&n=z&og=804&cstl=vbd';

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
    baseLayer = new L.TileLayer('', {
      attribution: '&copy; Microsoft, 必应地图',
      maxZoom: 19,
    });
    baseLayer.getTileUrl = function(coords) {
      return TILE_URL.replace('{q}', toQuadkey(coords.x, coords.y, coords.z));
    };
    baseLayer.addTo(mapInstance);

    // 缓存 DOM 引用，避免每次 mousemove 都 querySelector
    _coordsEl = document.querySelector('.map-coords');
    _zoomLabelEl = document.querySelector('.map-zoom-label');

    mapInstance.on('mousemove', onMouseMove);
    mapInstance.on('zoomend', onZoomEnd);

    // 初始化右键菜单
    setTimeout(initContextMenu, 200);
  }

  function toQuadkey(x, y, z) {
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

    var layer = L.geoJSON(geojson, {
      style: mergedStyle,
      pointToLayer: function(feature, latlng) {
        return L.circleMarker(latlng, {
          radius: 6, fillColor: mergedStyle.fillColor,
          color: mergedStyle.color, weight: 2, opacity: 1, fillOpacity: 0.6,
        });
      },
      coordsToLatLng: function(coords) {
        // GeoJSON 标准是 [lng, lat]，但有的数据是 [lat, lng]
        // 如果纬度值看起来像经度（超出合理纬度范围 -90~90），自动交换
        var lng = coords[0], lat = coords[1];
        if (Math.abs(lat) > 90 && Math.abs(lng) <= 90) {
          return L.latLng(lng, lat);
        }
        return L.latLng(lat, lng);
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
    if (layers[name]) { mapInstance.removeLayer(layers[name]); delete layers[name]; delete geoStore[name]; }
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
    if (!layers[name] || !geoStore[name]) return;
    // 重新用新颜色加载
    var geo = geoStore[name].geojson;
    removeLayer(name);
    loadGeoJSON(geo, name, { color: color, fillColor: color });
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
        _hideContextMenu();
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

  // ---- 十字准星：使用 position:fixed 固定在点击的屏幕位置，不跟踪地图移动 ----
  var _crosshairOverlay = null;

  function _showCrosshair(x, y, latlng) {
    _hideCrosshair();
    var lat = latlng.lat, lng = latlng.lng;

    var mapEl = document.getElementById('map');
    if (!mapEl) return;
    var rect = mapEl.getBoundingClientRect();

    // Container 固定在"地图区域"的视口位置上，overflow:hidden 裁剪掉超出地图的范围
    var container = document.createElement('div');
    container.id = 'crosshair-overlay';
    container.style.cssText = 'position:fixed;left:' + rect.left + 'px;top:' + rect.top + 'px;width:' + rect.width + 'px;height:' + rect.height + 'px;pointer-events:none;z-index:9999;overflow:hidden;';

    // 将视口坐标转成地图区域相对坐标
    var rx = x - rect.left;
    var ry = y - rect.top;

    // 竖线（被 overflow:hidden 裁剪，只在地图区域内显示）
    var vLine = document.createElement('div');
    vLine.style.cssText = 'position:absolute;left:' + rx + 'px;top:0;width:1px;height:100%;background:#666;opacity:0.5;';
    // 横线
    var hLine = document.createElement('div');
    hLine.style.cssText = 'position:absolute;left:0;top:' + ry + 'px;width:100%;height:1px;background:#666;opacity:0.5;';
    // 中心圆点
    var dot = document.createElement('div');
    dot.style.cssText = 'position:absolute;left:' + (rx - 5) + 'px;top:' + (ry - 5) + 'px;width:10px;height:10px;border-radius:50%;background:#fff;border:2px solid #333;box-sizing:border-box;';
    // 坐标标签
    var label = document.createElement('div');
    label.textContent = lat.toFixed(5) + ', ' + lng.toFixed(5);
    var labelStyle = 'position:absolute;font-size:11px;font-family:monospace;padding:2px 6px;border-radius:3px;white-space:nowrap;line-height:1.5;color:#fff;background:rgba(0,0,0,0.75);';
    if (ry > 40) {
      label.style.cssText = labelStyle + 'left:' + (rx + 10) + 'px;top:' + (ry - 22) + 'px;';
    } else {
      label.style.cssText = labelStyle + 'left:' + (rx + 10) + 'px;top:' + (ry + 10) + 'px;';
    }

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

    // AI 相关功能
    if (window._aiRunning) return;
    var hasKey = window.GIS && window.GIS.api && window.GIS.api.getApiKey();
    if (!hasKey) {
      if (window.GIS && window.GIS.chat && window.GIS.chat.addMessage)
        window.GIS.chat.addMessage('请先配置 DeepSeek API Key', 'system');
      return;
    }

    var msg = '', displayMsg = '';
    switch (action) {
      case 'send-location':
      case 'send-location-routed':
        displayMsg = lat + ', ' + lng + ' - 查询地理信息';
        msg = '纬度' + lat + '，经度' + lng + '。\n请完成以下任务：\n1. 先 search_web 搜索这个位置属于哪个省/市/区/县\n2. 查询附近的地理特征（山脉、河流、湖泊、地形等）\n3. 查询该区域的气候类型、典型海拔、植被等地理信息\n4. 最后用 execute_python 在地图该位置加一个点标记，只加一个点，不要生成多个点位\n5. 回复时用表格形式（markdown 表格），格式如下：\n\n| 项目 | 内容 |\n|------|------|\n| 经度 | 具体数值 |\n| 纬度 | 具体数值 |\n| 所属省份 | XX省 |\n| 所属城市 | XX市 |\n| 所属区县 | XX区/县 |\n| 附近河流 | XXX |\n| 附近山脉 | XXX |\n| 地形特征 | XXX |\n| 气候类型 | XXX |\n| 典型海拔 | XXX米 |\n| 备注 | 其他补充信息 |\n\n尽量多提供该位置的地理相关信息，回复要详细。不要用aoi相关工具，不要提取边界轮廓。';
        break;
      case 'get-dem':
        displayMsg = lat + ', ' + lng + ' - DEM';
        msg = '获取DEM数据：bbox=' + (lng - 0.075).toFixed(4) + ',' + (lat - 0.075).toFixed(4) + ',' + (lng + 0.075).toFixed(4) + ',' + (lat + 0.075).toFixed(4) + ' step=0.0001';
        break;
    }
    if (msg && window.GIS && window.GIS.chat && window.GIS.chat.send) {
      // 右键发送 → 使用当前选中的模型
      var selEl = document.getElementById('modelSelector');
      var curProvider = selEl ? selEl.value : 'deepseek-routed';
      var valEl = document.getElementById('modelSelectValue');
      var names = { 'deepseek-routed': 'DeepSeek V4 Flash+', 'glm-routed': 'GLM-4.7-Flash+' };
      if (valEl) valEl.textContent = names[curProvider] || curProvider;
      window.GIS.chat.send(msg, { displayText: displayMsg || undefined, provider: curProvider });
    }
  }

  GIS.map = {
    init: init,
    loadGeoJSON: loadGeoJSON,
    removeLayer: removeLayer,
    setLayerVisible: setLayerVisible,
    setLayerColor: setLayerColor,
    getLayer: getLayer,
    toggleLayer: toggleLayer,
    flyTo: flyTo,
    fitLayer: fitLayer,
    loadHeatmap: loadHeatmap,
    removeHeatmap: removeHeatmap,
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
  };
})();
