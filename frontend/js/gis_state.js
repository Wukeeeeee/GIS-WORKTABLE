/**
 * GIS AI WorkTable — 共享 GIS 状态中枢（P0）
 *
 * 唯一运行时数据源：图层 / 选中要素 / 下钻栈。
 * 2D(Leaflet)、3D(Cesium)、UI(面包屑/属性面板) 都只订阅本模块，
 * 事件回写也只写回本模块 —— 渲染器是状态的消费者，不是持有者。
 *
 * 设计约定（详见 docs/research_3d_globe_drilldown.md §5）：
 *  - 数据统一 WGS-84 GeoJSON（DataV 的 GCJ-02 由后端 datav_service 转好）
 *  - 要素身份 = layer_id + _fid（adcode/name 稳定值，兜底 index）
 *  - 同步的是 GIS 数据状态；相机/绘制会话等 Renderer 私有状态不同步
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  // ============================================================
  // 状态
  // ============================================================

  const layers = [];          // LayerRecord 有序数组（顺序即叠放，[0] 最上）
  let selection = null;       // { layerId, layerName, fid, idx, feature, props, source }
  const drill = {             // 下钻导航栈（2D/3D 共用）
    stack: [],                // [{ level, adcode, name, layerId }]
  };

  // 稳定 _fid：adcode > name > id > index 兜底
  function makeFid(props, idx) {
    props = props || {};
    if (props.adcode !== undefined && props.adcode !== null && props.adcode !== '') {
      return 'p:' + props.adcode;
    }
    if (props.name) return 'n:' + props.name;
    if (props.id !== undefined && props.id !== null) return 'id:' + props.id;
    return 'i:' + idx;
  }

  function findLayer(layerId) {
    for (var i = 0; i < layers.length; i++) {
      if (layers[i].layer_id === layerId) return layers[i];
    }
    return null;
  }

  function layerByName(name) {
    for (var i = 0; i < layers.length; i++) {
      if (layers[i].name === name || layers[i]._rawName === name) return layers[i];
    }
    return null;
  }

  // ============================================================
  // 极简发布订阅
  // ============================================================

  const listeners = {};       // { event: [cb] }
  function emit(event, payload) {
    (listeners[event] || []).forEach(function(cb) {
      try { cb(payload); } catch (e) { console.error('[GIS State] listener error:', event, e); }
    });
  }
  function on(event, cb) {
    (listeners[event] = listeners[event] || []).push(cb);
    return function unsubscribe() {
      var arr = listeners[event] || [];
      var i = arr.indexOf(cb);
      if (i >= 0) arr.splice(i, 1);
    };
  }

  // ============================================================
  // 图层动作（单一入口；内部调用现有渲染实现，P0 不改 map.js 内部）
  // ============================================================

  /**
   * 注册一个图层到状态，并驱动 2D 渲染（3D 渲染器自行订阅）。
   * record: { layer_id?, name, geojson, style?, source?, metadata?, visible? }
   * 重复 name 自动加后缀（与 chat.js 现有行为一致）。
   */
  function addLayer(record) {
    var name = record.name || '图层';
    var uniqueName = name;
    var suffix = 1;
    while (layerByName(uniqueName)) { uniqueName = name + '_' + (suffix++); }

    var geojson = record.geojson;
    var features = (geojson && geojson.type === 'FeatureCollection') ? (geojson.features || [])
      : geojson ? [geojson] : [];

    // 注入稳定 _fid（幂等：已有则不覆盖）
    features.forEach(function(f, idx) {
      if (f && f.properties && f.properties._fid === undefined) {
        f.properties._fid = makeFid(f.properties, idx);
      }
    });

    var bbox = computeBbox(features);
    var layerId = record.layer_id || ('state_' + Date.now().toString(36) + '_' +
      Math.floor(Math.random() * 1e6).toString(36));

    var rec = {
      layer_id: layerId,
      name: uniqueName,
      _rawName: uniqueName,          // map.js/layers.js 以此查找
      geojson: geojson,
      style: record.style || null,
      source: record.source || 'ai',
      crs: 'EPSG:4326',
      visible: record.visible !== false,
      bbox: bbox,
      featureCount: features.length,
      metadata: record.metadata || {},   // { level?, parentAdcode?, drillChildOf? }
      fidIndex: {},                      // fid -> featureIdx（Leaflet name:idx 兼容）
    };
    features.forEach(function(f, idx) {
      if (f && f.properties && f.properties._fid !== undefined) {
        rec.fidIndex[f.properties._fid] = idx;
      }
    });
    // 地图内名称（_mapName）：上传/绘制路径 2D 已按原名渲染，地图操作必须沿用原名
    var rawName = record._mapName || uniqueName;
    rec._rawName = rawName;

    layers.unshift(rec);   // 新图层放最上（与图层面板行为一致）

    // 驱动 2D 渲染（沿用现有实现，P0 不重写）
    // _skip2DRender：layers.addLayer 桥接来的图层，调用方已渲染过 2D，避免双重加载
    if (!record._skip2DRender && GIS.map && GIS.map.loadGeoJSON && rec.visible) {
      GIS.map.loadGeoJSON(geojson, rawName, rec.style || {});
    }
    if (GIS.layers && GIS.layers.addLayer) {
      GIS.layers.addLayer({
        layer_id: layerId,
        filename: uniqueName,
        geometry_type: detectGeomType(features),
        crs: 'WGS-84',
        geojson: geojson,
        color: record.color,
        visible: rec.visible,
        source: rec.source,
        _rawName: rawName,
        _panelSync: true,   // 防递归：面板 addLayer 见此标记走正常入库，不再桥接回 state
      }, true /* skipRegister：数据来自后端或本模块，无需前端再注册 */);
    }

    emit('layer-added', rec);
    return rec;
  }

  function removeLayer(layerId) {
    var rec = findLayer(layerId);
    if (!rec) return;
    layers.splice(layers.indexOf(rec), 1);
    if (GIS.map && GIS.map.removeLayer) GIS.map.removeLayer(rec._rawName);
    if (GIS.layers && GIS.layers.removeLayer) {
      var panel = null;
      (GIS.layers.getLayers ? GIS.layers.getLayers() : []).forEach(function(l) {
        if (l.layer_id === layerId) panel = l;
      });
      if (panel) GIS.layers.removeLayer(layerId, true);
    }
    if (selection && selection.layerId === layerId) clearSelection();
    emit('layer-removed', { layerId: layerId });
  }

  function setVisible(layerId, visible) {
    var rec = findLayer(layerId);
    if (!rec) return;
    rec.visible = !!visible;
    if (GIS.map && GIS.map.setLayerVisible) GIS.map.setLayerVisible(rec._rawName, rec.visible);
    emit('layer-visible', rec);
  }

  function setStyle(layerId, style) {
    var rec = findLayer(layerId);
    if (!rec) return;
    rec.style = Object.assign({}, rec.style || {}, style || {});
    if (GIS.map && GIS.map.setLayerStyle) GIS.map.setLayerStyle(rec._rawName, rec.style);
    emit('layer-style', rec);
  }

  /** 图层透明度（0-1）。2D 由调用方直接驱动 map.setLayerOpacity（避免整层重设样式），
   *  这里只更新记录并广播 3D */
  function setOpacity(layerId, opacity) {
    var rec = findLayer(layerId);
    if (!rec) return;
    rec.style = Object.assign({}, rec.style || {}, { opacity: Math.max(0, Math.min(1, +opacity || 0)) });
    emit('layer-style', rec);
  }

  /** 按要素设色（fid -> '#rrggbb'）：2D 符号化结果同步给 3D 渲染器；传 null 清除 */
  function setFeatureColors(layerId, colorByFid) {
    var rec = findLayer(layerId);
    if (!rec) return;
    rec.featureColors = colorByFid || null;
    emit('feature-style', rec);
  }

  /** 应用数据驱动可视化 spec（由 Agent 的 visualize op 或前端触发） */
  function applyVisualization(layerId, viz) {
    var rec = findLayer(layerId);
    if (!rec) return;
    rec.viz = viz;
    emit('viz', { layer: rec, viz: viz });
  }

  // ============================================================
  // 选中（2D ↔ 3D 同步的核心：两边都写这里，两边都听这里）
  // ============================================================

  /**
   * 选中一个要素。source: '2d' | '3d' | 'panel' | 'agent'
   * feature: GeoJSON Feature；props 会自动带上 _fid
   */
  function selectFeature(layerId, feature, source, idx) {
    var rec = findLayer(layerId);
    if (!rec && layerId) {
      // 兼容传图层名
      rec = layerByName(layerId);
    }
    if (!rec) return;
    var props = (feature && feature.properties) || {};
    var fid = props._fid || makeFid(props, idx || 0);
    if (idx === undefined && rec.fidIndex[fid] !== undefined) idx = rec.fidIndex[fid];

    selection = {
      layerId: rec.layer_id,
      layerName: rec.name,
      fid: fid,
      idx: idx,
      feature: feature || null,
      props: props,
      source: source || 'unknown',
      adcode: props.adcode !== undefined ? props.adcode : null,
      name: props.name || props.NAME || props.adcode || ('要素#' + ((idx || 0) + 1)),
      level: props.level || (rec.metadata && rec.metadata.level) || null,
    };
    emit('selection-changed', { selection: selection, source: source });
  }

  function clearSelection() {
    if (!selection) return;
    selection = null;
    emit('selection-changed', { selection: null });
  }

  // ============================================================
  // 下钻状态机（World→Country→Province→City→County；DataV 支持到 County）
  // ============================================================

  /** 加载某行政区的子级边界并下钻。adcode 必填；后端负责 GCJ-02→WGS84 与缓存 */
  function drillDown(adcode, name) {
    if (!adcode) return Promise.reject(new Error('该要素无 adcode，不支持下钻'));
    var url = (GIS.api && GIS.api.BASE_URL ? GIS.api.BASE_URL : '') +
      '/api/boundary?adcode=' + encodeURIComponent(adcode);
    return fetch(url)
      .then(function(r) { if (!r.ok) throw new Error('边界服务返回 ' + r.status); return r.json(); })
      .then(function(data) {
        // /api/boundary 返回 {geojson: FC} 包装；解包并兼容裸 FC
        var geojson = data && data.geojson ? data.geojson : data;
        if (!geojson || geojson.error || geojson.type !== 'FeatureCollection') {
          throw new Error((data && data.error) || '未取到边界数据');
        }
        var parentLevel = (selection && selection.level) || 'country';
        var rec = addLayer({
          name: (name || adcode) + '_下级',
          geojson: geojson,
          source: 'datav',
          metadata: {
            level: nextLevel(parentLevel),
            parentAdcode: adcode,
            parentName: name || '',
          },
        });
        // 记录式显隐：进入该级时被隐藏的父级图层，随栈保存，返回时恢复
        var hiddenLayerId = null;
        if (selection && selection.layerId && String(selection.adcode) === String(adcode)) {
          hiddenLayerId = selection.layerId;
        } else {
          var pl = layerOfAdcode(adcode);
          if (pl) hiddenLayerId = pl.layer_id;
        }
        if (hiddenLayerId) setVisible(hiddenLayerId, false);
        drill.stack.push({
          level: nextLevel(parentLevel), adcode: String(adcode),
          name: name || String(adcode), layerId: rec.layer_id,
          hiddenLayerId: hiddenLayerId,
        });
        // 相机飞到子级范围（2D/3D 各自订阅 view-changed）
        emit('view-changed', { bbox: rec.bbox, reason: 'drill-down' });
        emit('drill-changed', { stack: drill.stack.slice() });
        return rec;
      });
  }

  /** Agent drill_down 工具路径：图层由 result.layers 通道加载，这里同步导航栈。
   * op 先于图层到达（chat.js 先处理 layer_ops 后处理 layers），所以带重试。 */
  function drillSyncFromAgent(op) {
    var tries = 0;
    (function attempt() {
      var rec = layerByName(op.layer_name || '');
      if (!rec) {
        // 兼容前端唯一名后缀（图层名_时间戳_序号）：按前缀匹配后端图层名
        var want = op.layer_name || '';
        for (var i = 0; i < layers.length; i++) {
          if ((layers[i].name || '').indexOf(want) === 0 ||
              (layers[i]._rawName || '').indexOf(want) === 0) { rec = layers[i]; break; }
        }
      }
      if (!rec && tries++ < 10) { setTimeout(attempt, 300); return; }
      if (!rec) return;
      var hiddenLayerId = null;
      if (selection && selection.layerId && String(selection.adcode) === String(op.adcode)) {
        hiddenLayerId = selection.layerId;
      } else {
        var pl = layerOfAdcode(op.adcode);
        if (pl) hiddenLayerId = pl.layer_id;
      }
      if (hiddenLayerId) setVisible(hiddenLayerId, false);
      drill.stack.push({
        level: op.level || 'city', adcode: String(op.adcode),
        name: op.name || op.layer_name || '', layerId: rec.layer_id,
        hiddenLayerId: hiddenLayerId,
      });
      emit('view-changed', { bbox: rec.bbox, reason: 'drill-down' });
      emit('drill-changed', { stack: drill.stack.slice() });
    })();
  }

  /** 加载全国省级行政区作为下钻起点（栈底） */
  function initCountryLevel() {
    return drillDown(100000, '中国');
  }

  /** 返回第 depth 级（-1 = 一路返回全国之前；省略 = 返回上一级）。
   * 语义：栈项 E 表示「正在查看 E 的子级图层」；弹出 E = 删除 E 的子级图层、
   * 恢复进入 E 时被隐藏的图层（E.hiddenLayerId）。 */
  function drillUpTo(targetDepth) {
    if (drill.stack.length === 0) return;
    var depth = (targetDepth === undefined) ? drill.stack.length - 2 : targetDepth;
    while (drill.stack.length > depth + 1) {
      var popped = drill.stack.pop();
      removeLayer(popped.layerId);
      var restored = popped.hiddenLayerId ? findLayer(popped.hiddenLayerId) : null;
      if (restored) setVisible(restored.layer_id, true);
      var top = drill.stack[drill.stack.length - 1] || null;
      var viewRec = restored || (top ? findLayer(top.layerId) : null);
      emit('view-changed', {
        bbox: viewRec ? viewRec.bbox : null,
        reason: 'drill-up',
      });
    }
    emit('drill-changed', { stack: drill.stack.slice() });
  }

  function getDrillStack() { return drill.stack.slice(); }

  /** 找到「包含 adcode 为 X 的要素」的图层（扫描全部要素，不只第一个） */
  function layerOfAdcode(adcode) {
    for (var i = 0; i < layers.length; i++) {
      var feats = layers[i].geojson && layers[i].geojson.features;
      if (!feats) continue;
      for (var j = 0; j < feats.length; j++) {
        var p = feats[j] && feats[j].properties;
        if (p && String(p.adcode) === String(adcode)) return layers[i];
      }
    }
    return null;
  }

  function nextLevel(level) {
    return { world: 'country', country: 'province', province: 'city', city: 'county', county: 'street' }[level] || 'city';
  }

  // ============================================================
  // 工具函数
  // ============================================================

  function computeBbox(features) {
    var w = 180, s = 90, e = -180, n = -90, found = false;
    function walk(c) {
      if (!c || !c.length) return;
      if (typeof c[0] === 'number') {
        w = Math.min(w, c[0]); e = Math.max(e, c[0]);
        s = Math.min(s, c[1]); n = Math.max(n, c[1]);
        found = true;
      } else { c.forEach(walk); }
    }
    features.forEach(function(f) {
      if (f && f.geometry) walk(f.geometry.coordinates);
    });
    return found ? [w, s, e, n] : null;
  }

  function detectGeomType(features) {
    var types = {};
    features.forEach(function(f) {
      if (f && f.geometry && f.geometry.type) types[f.geometry.type] = 1;
    });
    return Object.keys(types).join(', ') || '未知';
  }

  // ============================================================
  // 导出
  // ============================================================

  GIS.state = {
    on: on,
    addLayer: addLayer,
    removeLayer: removeLayer,
    setVisible: setVisible,
    setStyle: setStyle,
    setOpacity: setOpacity,
    setFeatureColors: setFeatureColors,
    applyVisualization: applyVisualization,
    selectFeature: selectFeature,
    clearSelection: clearSelection,
    drillDown: drillDown,
    drillUpTo: drillUpTo,
    drillSyncFromAgent: drillSyncFromAgent,
    initCountryLevel: initCountryLevel,
    getDrillStack: getDrillStack,
    getLayers: function() { return layers.slice(); },
    getLayer: findLayer,
    getSelection: function() { return selection; },
  };
})();
