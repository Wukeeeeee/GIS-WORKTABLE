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

    mapInstance.on('mousemove', onMouseMove);
    mapInstance.on('zoomend', onZoomEnd);
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
    var el = document.querySelector('.map-coords');
    if (el) el.textContent = 'WGS-84 | ' + e.latlng.lat.toFixed(5) + ', ' + e.latlng.lng.toFixed(5);
  }

  function onZoomEnd() {
    var el = document.querySelector('.map-zoom-label');
    if (el) el.textContent = 'Z' + mapInstance.getZoom();
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
