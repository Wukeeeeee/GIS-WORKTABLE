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

    var layer = L.geoJSON(geojson, {
      style: mergedStyle,
      pointToLayer: function(feature, latlng) {
        return L.circleMarker(latlng, {
          radius: 6, fillColor: mergedStyle.fillColor,
          color: mergedStyle.color, weight: 2, opacity: 1, fillOpacity: 0.6,
        });
      },
    });
    layer.addTo(mapInstance);
    layers[name] = layer;
    geoStore[name] = { geojson: geojson, style: style };
    return layer;
  }

  function removeLayer(name) {
    if (layers[name]) { mapInstance.removeLayer(layers[name]); delete layers[name]; delete geoStore[name]; }
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
