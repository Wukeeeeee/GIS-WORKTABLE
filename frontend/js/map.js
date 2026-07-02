/**
 * ============================================
 *  GIS AI WorkTable — 地图模块
 *  Leaflet 地图封装，预留图层加载接口
 * ============================================
 * 使用: window.GIS.map.init('map')
 * 依赖: Leaflet (jsDelivr CDN)
 *
 * 底图说明:
 * - osm: OpenStreetMap（默认）
 * - arcgis: ArcGIS World Street Map
 * - tianditu: 天地图（需申请免费 token）
 * ============================================
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  /** @type {L.Map|null} */
  let mapInstance = null;

  /** @type {object<string, L.Layer>} 已加载的图层集合 */
  const layers = {};

  /** @type {L.TileLayer} 底图 */
  let baseLayer = null;

  /**
   * 地图源配置
   * osm  — OpenStreetMap（默认）
   * arcgis — ArcGIS 世界街道图（国内可访问）
   * tianditu — 天地图矢量，最快最稳，需免费申请 token
   *
   * 天地图 token 申请: https://console.tianditu.gov.cn/
   */
  const TILE_CONFIG = {
    // OpenStreetMap（默认）
    osm: {
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
      subdomains: 'abc',
      maxZoom: 19,
    },
    // ArcGIS 世界街道图（国内可访问，无需 token）
    arcgis: {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
      attribution: '&copy; Esri, HERE, Garmin, OpenStreetMap',
      subdomains: [],
      maxZoom: 18,
    },
    // 天地图（WMTS，需申请 token）
    tianditu: {
      url: 'https://t{s}.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=',
      attribution: '&copy; 天地图',
      subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'],
      maxZoom: 18,
      token: 'YOUR_TIANDITU_TOKEN', // 申请: https://console.tianditu.gov.cn/
    },
    // ArcGIS 卫星影像图
    satellite: {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      attribution: '&copy; Esri, Maxar, Earthstar, USDA',
      subdomains: [],
      maxZoom: 18,
    },
    // CartoDB 轻量街道图（WGS84，国内部分地区可访问）
    carto: {
      url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20,
    },
    // CartoDB 无文字版（纯地图，无标注）
    carto_clean: {
      url: 'https://{s}.basemaps.cartocdn.com/light_no_labels/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20,
    },
    // CartoDB 无文字深色版
    carto_dark: {
      url: 'https://{s}.basemaps.cartocdn.com/dark_no_labels/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20,
    },
    // Bing Maps 中国区（速度快，国内可访问，WGS84）
    bing_cn: {
      url: 'https://t1.dynamic.tiles.ditu.live.com/comp/ch/{q}?mkt=zh-CN&ur=cn&it=G,RL&n=z&og=804&cstl=vbd',
      attribution: '&copy; Microsoft, 必应地图',
      subdomains: [],
      maxZoom: 19,
      isBing: true, // 标记需要 quadkey 转换
    },
    // OpenTopoMap 全球地形图（WGS84，免费，无国界标注）
    terrain: {
      url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
      subdomains: 'abc',
      maxZoom: 17,
    },
    // Wikimedia 地图（OSM 数据，免费，国内部分地区可访问）
    wikimedia: {
      url: 'https://maps.wikimedia.org/osm-intl/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://wikimedia.org">Wikimedia</a>',
      subdomains: [],
      maxZoom: 19,
    },
    // ESRI 世界地形图（ArcGIS 服务，免费）
    esri_topo: {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
      attribution: '&copy; Esri, USGS, NOAA',
      subdomains: [],
      maxZoom: 18,
    },
  };

  /**
   * 初始化地图
   * @param {string|HTMLElement} container - 地图容器 ID 或元素
   * @param {object} [options] - 地图选项
   * @param {number[]} [options.center=[35, 110]] - 初始中心点 [lat, lng]
   * @param {number} [options.zoom=4] - 初始缩放级别
   * @param {'osm'|'arcgis'|'tianditu'|'satellite'|'carto'|'carto_clean'|'carto_dark'|'terrain'|'bing_cn'} [options.tileSource='osm'] - 底图来源
   */
  function init(container, options = {}) {
    if (typeof L === 'undefined') {
      console.warn('[GIS Map] Leaflet 未加载，地图不可用');
      return;
    }

    const {
      center = [35, 110],
      zoom = 4,
      tileSource = 'bing_cn',
    } = options;

    // 如果已初始化，跳过
    if (mapInstance) {
      console.warn('[GIS Map] 地图已初始化');
      return;
    }

    const el = typeof container === 'string'
      ? document.getElementById(container)
      : container;

    if (!el) {
      console.error(`[GIS Map] 容器 "${container}" 不存在`);
      return;
    }

    // 创建地图实例
    mapInstance = L.map(el, {
      center,
      zoom,
      zoomControl: false, // 使用自定义缩放控件
      attributionControl: true,
    });

    // 添加底图
    setTileSource(tileSource);

    // 鼠标移动时更新坐标显示
    mapInstance.on('mousemove', onMouseMove);

    // 地图交互事件
    mapInstance.on('zoomend', onZoomEnd);

    console.log(`[GIS Map] 地图初始化完成 (${center[0]}, ${center[1]}, zoom=${zoom})`);
  }

  let currentSource = 'osm';
  // 可供切换的底图列表
  const SOURCE_LIST = ['osm', 'carto', 'carto_clean', 'carto_dark', 'terrain', 'satellite', 'bing_cn'];

  /**
   * 将 z/x/y 转换为 Bing Maps quadkey
   */
  function toQuadkey(x, y, z) {
    var q = '';
    for (var i = z; i > 0; i--) {
      var d = 0;
      var m = 1 << (i - 1);
      if ((x & m) !== 0) d += 1;
      if ((y & m) !== 0) d += 2;
      q += d;
    }
    return q;
  }

  /**
   * 切换底图
   * @param {'osm'|'arcgis'|'tianditu'|'satellite'|'carto'|'carto_clean'|'carto_dark'|'terrain'|'wikimedia'|'esri_topo'} source
   */
  function setTileSource(source) {
    if (!mapInstance) return;

    // 移除旧底图
    if (baseLayer) {
      mapInstance.removeLayer(baseLayer);
    }

    const config = TILE_CONFIG[source];
    if (!config) {
      console.warn(`[GIS Map] 未知底图: ${source}，使用 osm`);
      return setTileSource('osm');
    }

    // 天地图需要替换 token
    let url = config.url;
    if (source === 'tianditu') {
      url = url.replace(/tk=$/, `tk=${config.token}`);
    }

    // Bing 瓦片要用 quadkey 转换
    if (config.isBing) {
      baseLayer = new L.TileLayer('', {
        attribution: config.attribution,
        maxZoom: config.maxZoom,
      });
      baseLayer.getTileUrl = function(coords) {
        return url.replace('{q}', toQuadkey(coords.x, coords.y, coords.z));
      };
      baseLayer.addTo(mapInstance);
    } else {
      baseLayer = L.tileLayer(url, {
        attribution: config.attribution,
        subdomains: config.subdomains.length > 0 ? config.subdomains : undefined,
        maxZoom: config.maxZoom,
      }).addTo(mapInstance);
    }

    // 瓦片加载失败时打印日志
    baseLayer.on('tileerror', function(e) {
      console.warn('[GIS Map] 瓦片加载失败:', e.tile.src);
    });

    currentSource = source;
  }

  /**
   * 切换到底图源（循环切换）
   */
  function cycleTileSource() {
    const idx = SOURCE_LIST.indexOf(currentSource);
    const next = SOURCE_LIST[(idx + 1) % SOURCE_LIST.length];
    setTileSource(next);
    console.log(`[GIS Map] 切换到底图: ${next}`);
    return next;
  }

  /**
   * 加载 GeoJSON 数据到地图
   * @param {object} geojson - GeoJSON FeatureCollection
   * @param {string} [name='layer'] - 图层名称（用于索引）
   * @param {object} [style] - 覆盖默认样式
   * @returns {L.GeoJSON|null} Leaflet GeoJSON 图层
   */
  function loadGeoJSON(geojson, name = 'layer', style = {}) {
    if (!mapInstance || !geojson) {
      console.warn('[GIS Map] 地图未初始化或无数据');
      return null;
    }

    // 清除同名旧图层
    if (layers[name]) {
      mapInstance.removeLayer(layers[name]);
    }

    const defaultStyle = {
      color: '#1c1b1b',
      weight: 2,
      fillColor: '#1c1b1b',
      fillOpacity: 0.1,
    };

    const layer = L.geoJSON(geojson, {
      style: { ...defaultStyle, ...style },
      pointToLayer: (feature, latlng) => {
        return L.circleMarker(latlng, {
          radius: 6,
          fillColor: style.fillColor || '#1c1b1b',
          color: '#ffffff',
          weight: 1,
          fillOpacity: 0.8,
        });
      },
    }).addTo(mapInstance);

    layers[name] = layer;

    // 自动缩放至图层范围
    try {
      mapInstance.fitBounds(layer.getBounds(), { padding: [30, 30] });
    } catch (e) {
      // 单点要素或异常范围时忽略
    }

    return layer;
  }

  /**
   * 清除所有或指定图层
   * @param {string} [name] - 不传则清除全部
   */
  function clearLayers(name) {
    if (!mapInstance) return;

    if (name && layers[name]) {
      mapInstance.removeLayer(layers[name]);
      delete layers[name];
    } else {
      Object.keys(layers).forEach(k => {
        mapInstance.removeLayer(layers[k]);
        delete layers[k];
      });
    }
  }

  /**
   * 获取所有已加载图层名称列表
   * @returns {string[]}
   */
  function getLayerNames() {
    return Object.keys(layers);
  }

  /**
   * 缩放到指定视图
   * @param {number[]} center - [lat, lng]
   * @param {number} zoom
   */
  function setView(center, zoom) {
    if (mapInstance) {
      mapInstance.setView(center, zoom);
    }
  }

  /**
   * 获取当前地图状态
   * @returns {{ center: number[], zoom: number, bounds: object }}
   */
  function getState() {
    if (!mapInstance) return null;
    const c = mapInstance.getCenter();
    return {
      center: [c.lat, c.lng],
      zoom: mapInstance.getZoom(),
      bounds: mapInstance.getBounds().toBBoxString(),
    };
  }

  /**
   * 鼠标移动 → 更新坐标显示
   * @param {L.LeafletMouseEvent} e
   */
  function onMouseMove(e) {
    const coordsEl = document.getElementById('mapCoords');
    if (coordsEl) {
      const lat = e.latlng.lat.toFixed(4);
      const lng = e.latlng.lng.toFixed(4);
      const zoom = mapInstance ? mapInstance.getZoom() : '-';
      coordsEl.textContent = `${lat}° N, ${lng}° E | 缩放 ${zoom}`;
    }
  }

  /**
   * 缩放变化 → 更新坐标显示中的 zoom
   */
  function onZoomEnd() {
    const coordsEl = document.getElementById('mapCoords');
    if (coordsEl && mapInstance) {
      const c = mapInstance.getCenter();
      const lat = c.lat.toFixed(4);
      const lng = c.lng.toFixed(4);
      coordsEl.textContent = `${lat}° N, ${lng}° E | 缩放 ${mapInstance.getZoom()}`;
    }
  }

  /**
   * 销毁地图（用于重新初始化）
   */
  function destroy() {
    if (mapInstance) {
      mapInstance.remove();
      mapInstance = null;
    }
    Object.keys(layers).forEach(k => delete layers[k]);
  }

  // ========== 公开接口 ==========
  GIS.map = {
    init,
    setTileSource,
    cycleTileSource,
    loadGeoJSON,
    clearLayers,
    getLayerNames,
    setView,
    getState,
    destroy,
  };
})();
