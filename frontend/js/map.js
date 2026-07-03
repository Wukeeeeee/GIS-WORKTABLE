/**
 * ============================================
 *  GIS AI WorkTable — 地图模块
 *  Leaflet 地图封装，预留图层加载接口
 * ============================================
 * 使用: window.GIS.map.init('map')
 * 依赖: Leaflet (jsDelivr CDN)
 *
 * 底图说明:
 * - bing_cn: Bing Maps 中国区（默认）
 * - bing_clean: Bing Maps 无文字版
 * - bing_aerial: Bing Maps 卫星图
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
  /** @type {object<string, object>} 存储 GeoJSON 原始数据 */
  const geoStore = {};

  /** @type {L.TileLayer} 底图 */
  let baseLayer = null;

  /**
   * 地图源配置
   * bing_cn — Bing Maps 中国区（默认，国内可访问，WGS84）
   * bing_clean — Bing Maps 无文字版
   * bing_aerial — Bing Maps 卫星图
   */
  const TILE_CONFIG = {
    // Bing Maps 中国区（速度快，国内可访问，WGS84）
    bing_cn: {
      url: 'https://t1.dynamic.tiles.ditu.live.com/comp/ch/{q}?mkt=zh-CN&ur=cn&it=G,RL&n=z&og=804&cstl=vbd',
      attribution: '&copy; Microsoft, 必应地图',
      subdomains: [],
      maxZoom: 19,
      isBing: true,
    },
    // Bing Maps 无文字版
    bing_clean: {
      url: 'https://t1.dynamic.tiles.ditu.live.com/comp/ch/{q}?mkt=zh-CN&ur=cn&it=G&n=z&og=804&cstl=vbd',
      attribution: '&copy; Microsoft, 必应地图',
      subdomains: [],
      maxZoom: 19,
      isBing: true,
    },
    // Bing Maps 卫星图
    bing_aerial: {
      url: 'https://t1.dynamic.tiles.ditu.live.com/comp/ch/{q}?mkt=zh-CN&ur=cn&it=A&n=z&og=804&cstl=vbd',
      attribution: '&copy; Microsoft, 必应地图',
      subdomains: [],
      maxZoom: 19,
      isBing: true,
    },
  };

  /**
   * 初始化地图
   * @param {string|HTMLElement} container - 地图容器 ID 或元素
   * @param {object} [options] - 地图选项
   * @param {number[]} [options.center=[35, 110]] - 初始中心点 [lat, lng]
   * @param {number} [options.zoom=4] - 初始缩放级别
   * @param {'bing_cn'|'bing_clean'|'bing_aerial'} [options.tileSource='bing_cn'] - 底图来源
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

    // 获取容器元素
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
  const SOURCE_LIST = ['bing_cn', 'bing_clean', 'bing_aerial'];

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
   * @param {'bing_cn'|'bing_clean'|'bing_aerial'} source
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
   *  Leaflet 自动识别点/线/面，不用手动判断
   *  @param {object} geojson - GeoJSON 数据
   *  @param {string} [name='layer'] - 图层名，用于索引和显隐/删除
   *  @param {object} [style] - 样式，如 { color, fillColor }
   */
  function loadGeoJSON(geojson, name = 'layer', style = {}) {
    if (!mapInstance || !geojson) return null;

    // 如果已存在同名图层，先移除旧的
    if (layers[name]) {
      mapInstance.removeLayer(layers[name]);
    }

    const defaultStyle = {
      color: '#1c1b1b',
      weight: 2,
      fillColor: '#1c1b1b',
      fillOpacity: 0.1,
    };

    // L.geoJSON 是 Leaflet 自带的，自动区分点线面
    const layer = L.geoJSON(geojson, {
      // 默认样式
      style: { ...defaultStyle, ...style },
      // 点要素用 circleMarker 显示
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

    layers[name] = layer;                    // 存图层引用（给显隐/删除用）
    geoStore[name] = { geojson, style };      // 存原始数据（给换颜色用）

    try {
      mapInstance.fitBounds(layer.getBounds(), { padding: [30, 30] });
    } catch (e) { /* 单点要素忽略 */ }

    return layer;
  }

  /**
   * 更新图层颜色
   *  调用 loadGeoJSON 用新颜色重新加载
   *  被 layers.js 的颜色选择器调用
   */
  function setLayerColor(name, color) {
    if (!geoStore[name]) return;
    const { geojson } = geoStore[name];
    loadGeoJSON(geojson, name, { color, fillColor: color });
  }

  /**
   * 显隐图层（不删除数据，只是隐藏/显示）
   *  被 layers.js 的 toggleVisibility 调用
   *  @param {string} name - 图层名
   *  @param {boolean} visible - true=显示, false=隐藏
   */
  function setLayerVisible(name, visible) {
    if (!layers[name]) return;
    if (visible) {
      mapInstance.addLayer(layers[name]);      // 加回地图
    } else {
      mapInstance.removeLayer(layers[name]);    // 从地图移除（数据还在）
    }
  }

  /**
   * 删除图层（从地图彻底移除）
   *  被 layers.js 的 removeLayer 调用
   *  @param {string} [name] - 图层名，不传则清除所有
   */
  function clearLayers(name) {
    if (!mapInstance) return;

    if (name && layers[name]) {
      mapInstance.removeLayer(layers[name]);
      delete layers[name];
      delete geoStore[name];                    // 一起清除存的数据
    } else {
      Object.keys(layers).forEach(k => {
        mapInstance.removeLayer(layers[k]);
        delete layers[k];
        delete geoStore[k];
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
      //小数点后4位
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
      //移除地图实例
      mapInstance.remove();
      mapInstance = null;
    }
    Object.keys(layers).forEach(k => delete layers[k]);
  }

  function getMap() {
    return mapInstance;
  }

  // ========== 公开接口 ==========
  GIS.map = {
    init,
    setTileSource,
    cycleTileSource,
    loadGeoJSON,
    setLayerColor,
    setLayerVisible,
    clearLayers,
    getLayerNames,
    setView,
    getState,
    getMap,
    destroy,
  };
})();
