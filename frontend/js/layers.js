/**
 * GIS AI WorkTable — 图层管理模块
 * 图层列表渲染、拖拽排序、显隐控制、删除
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';
  
  const GIS = window.GIS;

  let tbody = null;
  let layersTable = null;
  let layersEmpty = null;
  let layerData = [];
  let _pendingRegistryOps = [];
  let groups = Object.create(null); // { groupId: {id, name, collapsed} }
  let _groupIdCounter = 0;
  let _handleSwipeAction = null;

  function _trackRegistryOperation(promise, description) {
    var tracked = Promise.resolve(promise).catch(function(error) {
      console.warn('[GIS Layers] ' + description + '失败', error);
      return false;
    });
    _pendingRegistryOps.push(tracked);
    tracked.then(function() {
      _pendingRegistryOps = _pendingRegistryOps.filter(function(item) { return item !== tracked; });
    });
    return tracked;
  }

  function _waitForRegistrySync() {
    var operations = _pendingRegistryOps.slice();
    layerData.forEach(function(layer) {
      if (layer._registrationPromise) operations.push(Promise.resolve(layer._registrationPromise));
    });
    return Promise.all(operations);
  }

  function init() {
    tbody = document.getElementById('layerTbody');
    layersTable = document.getElementById('layersTable');
    layersEmpty = document.getElementById('layersEmpty');
    renderList();
    bindActionEvents();
    bindDragEvents();
    bindContextMenu();
    bindGroupEvents();
  }


  //渲染表格（支持分组）
  //渲染表格（支持分组）
  function renderList(data) {
    if (data) layerData = data;
    if (!tbody) return;
    const count = document.getElementById('workspaceLayerCount');
    if (count) count.textContent = layerData.length + ' 个图层';

    const groupKeys = Object.keys(groups);
    if (layerData.length === 0 && groupKeys.length === 0) {
      tbody.innerHTML = '';
      if (layersEmpty) layersEmpty.style.display = 'flex';
      if (layersTable) layersTable.style.display = 'none';
      return;
    }
    if (layersEmpty) layersEmpty.style.display = 'none';
    if (layersTable) layersTable.style.display = '';

    var html = '';
    var groupMap = groups;

    // 先渲染各个分组
    groupKeys.forEach(function(gid) {
      var g = groupMap[gid];
      if (!g) return;
      var groupLayers = layerData.filter(function(l) { return l.groupId === gid; });
      var collapsed = !!g.collapsed;

      html += '<tr class="group-header" data-group="' + escapeHtml(gid) + '" style="display:flex;align-items:center;padding:6px 8px;margin-top:6px;border-radius:4px;background:var(--surface-container-low,#eae6e4);cursor:pointer;border-bottom:1px solid var(--outline-variant,#ddd);">' +
        '<td class="col-group-toggle" style="width:22px;display:flex;align-items:center;justify-content:center;padding:0;"><span class="group-toggle" data-group="' + escapeHtml(gid) + '" title="' + (collapsed ? '展开分组' : '折叠分组') + '" style="cursor:pointer;font-size:10px;">' + (collapsed ? '&#9654;' : '&#9660;') + '</span></td>' +
        '<td class="col-group-name" colspan="3" style="flex:1;min-width:0;display:flex;align-items:center;justify-content:space-between;padding:0;">' +
          '<div style="display:flex;align-items:center;gap:6px;min-width:0;overflow:hidden;">' +
            '<span style="display:inline-flex;align-items:center;flex-shrink:0;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span>' +
            '<span class="group-name-text" data-group="' + escapeHtml(gid) + '" title="点击重命名分组" style="font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer;">' + escapeHtml(g.name) + '</span>' +
            '<span class="group-count" style="font-size:11px;color:var(--on-surface-variant,#888);flex-shrink:0;">(' + groupLayers.length + ')</span>' +
          '</div>' +
          '<div class="group-actions" style="display:flex;align-items:center;gap:4px;flex-shrink:0;">' +
            '<button type="button" class="group-rename-btn" data-group="' + escapeHtml(gid) + '" title="重命名分组" style="background:transparent;border:none;cursor:pointer;font-size:12px;color:var(--on-surface-variant,#666);padding:2px 4px;border-radius:3px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg></button>' +
            '<button type="button" class="group-delete-btn" data-group="' + escapeHtml(gid) + '" title="删除分组（保留图层）" style="background:transparent;border:none;cursor:pointer;font-size:12px;color:var(--on-surface-variant,#666);padding:2px 4px;border-radius:3px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>' +
          '</div>' +
        '</td></tr>';

      if (!collapsed) {
        if (groupLayers.length === 0) {
          html += '<tr class="group-empty-placeholder" data-group="' + escapeHtml(gid) + '" style="display:flex;align-items:center;justify-content:center;padding:8px 10px;margin-block:2px 6px;border:1px dashed var(--outline-variant,#ddd);border-radius:4px;background:var(--surface-container-lowest,#faf8f7);">' +
            '<td colspan="4" style="font-size:11px;color:var(--on-surface-variant,#888);text-align:center;border:none;padding:0;"><span style="display:inline-flex;align-items:center;vertical-align:-2px;margin-right:4px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><polyline points="2 10 22 10"/></svg></span> 该分组暂无图层，可拖入或右键图层移动至此</td></tr>';
        } else {
          groupLayers.forEach(function(layer) {
            var originalIndex = layerData.indexOf(layer);
            html += _renderLayerRow(layer, originalIndex, '');
          });
        }
      }
    });

    // 渲染未分组图层
    var ungrouped = layerData.filter(function(l) { return !l.groupId || !groupMap[l.groupId]; });
    if (groupKeys.length > 0 && ungrouped.length > 0) {
      html += '<tr class="group-header group-header-ungrouped" style="display:flex;align-items:center;padding:4px 8px;margin-top:6px;border-radius:4px;background:var(--surface-container-lowest,#f5f2f0);border-bottom:1px dashed var(--outline-variant,#ddd);">' +
        '<td class="col-group-toggle" style="width:22px;"></td>' +
        '<td class="col-group-name" colspan="3" style="font-size:11px;color:var(--on-surface-variant,#888);font-weight:600;padding:0;">未分组图层 (' + ungrouped.length + ')</td></tr>';
    }
    ungrouped.forEach(function(layer) {
      var originalIndex = layerData.indexOf(layer);
      html += _renderLayerRow(layer, originalIndex, '');
    });

    tbody.innerHTML = html;
  }

  function _detectGeomType(geojson) {
    if (!geojson) return '未知';
    var features = [];
    if (geojson.type === 'FeatureCollection') features = geojson.features || [];
    else if (geojson.type === 'Feature') features = [geojson];
    else if (geojson.type) return geojson.type;
    if (features.length === 0) return '空要素';
    var types = {};
    features.forEach(function(f) {
      if (f && f.geometry && f.geometry.type) types[f.geometry.type] = (types[f.geometry.type] || 0) + 1;
    });
    var keys = Object.keys(types);
    if (keys.length === 0) return '无几何';
    if (keys.length === 1) return keys[0];
    return 'GeometryCollection';
  }

  function _renderLayerRow(layer, index, hiddenStyle) {
    var rawType = layer.geometry_type;
    if (!rawType || rawType === '未知' || rawType === '未知类型' || rawType === 'Vector') {
      rawType = _detectGeomType(layer.geojson);
      layer.geometry_type = rawType;
    }
    const features = layer.geojson && (layer.geojson.type === 'FeatureCollection' ? (layer.geojson.features || []).length : layer.geojson.type === 'Feature' ? 1 : null);
    
    // 细分友好展示文案：针对集合特性精细化
    var typeText = '要素';
    if (rawType === 'Point') {
      typeText = (features && features > 1) ? '点集合 (Point)' : '点 (Point)';
    } else if (rawType === 'MultiPoint') {
      typeText = '点集合 (MultiPoint)';
    } else if (rawType === 'LineString') {
      typeText = (features && features > 1) ? '线集合 (Line)' : '线 (LineString)';
    } else if (rawType === 'MultiLineString') {
      typeText = '线集合 (MultiLine)';
    } else if (rawType === 'Polygon') {
      typeText = (features && features > 1) ? '面集合 (Polygon)' : '面 (Polygon)';
    } else if (rawType === 'MultiPolygon') {
      typeText = '多面 (MultiPolygon)';
    } else if (rawType === 'GeometryCollection') {
      typeText = '几何集合 (点/线/面)';
    } else {
      const geometryNames = {Point:'点', MultiPoint:'点集合', LineString:'线', MultiLineString:'线集合', Polygon:'面', MultiPolygon:'多面', GeometryCollection:'几何集合'};
      typeText = String(rawType).split(',').map(t => geometryNames[t.trim()] || t.trim()).join(' / ');
    }

    const op = Math.round((layer.opacity !== undefined ? layer.opacity : 1) * 100);
    return '<tr class="' + (layer.visible === false ? 'layer-hidden' : '') + '" draggable="true" data-index="' + index + '" data-id="' + escapeHtml(layer.layer_id || '') + '"' +
      (layer.groupId ? ' data-group="' + escapeHtml(layer.groupId) + '"' : '') + hiddenStyle + '>' +
      "<td class=\"col-drag\"><span class=\"drag-handle\" draggable=\"true\"><span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-102a87898985.png')\"></span></span></td>" +
      '<td class="col-vis"><button class="layer-action-btn layer-vis-check" data-action="visibility" data-id="' + (layer.layer_id || '') + '" aria-pressed="' + String(layer.visible !== false) + '" aria-label="' + (layer.visible !== false ? '隐藏图层' : '显示图层') + '" title="' + (layer.visible !== false ? '隐藏图层' : '显示图层') + '">' +
      '<span class="ui-visibility-check' + (layer.visible !== false ? ' checked' : '') + '" aria-hidden="true"></span></button></td>' +
      '<td class="col-name">' +
        '<div class="layer-title-line">' +
          '<span class="layer-color-dot" style="background:' + (layer.color || '#1c1b1b') + ';opacity:' + (layer.opacity !== undefined ? layer.opacity : 1) + '" data-color="' + (layer.color || '#1c1b1b') + '" data-id="' + (layer.layer_id || '') + '" title="修改颜色 · 不透明度 ' + op + '%"></span>' +
          '<span class="layer-name" data-id="' + (layer.layer_id || '') + '" title="' + escapeHtml(layer.filename || '未命名') + ' · 双击重命名">' + escapeHtml(layer.filename || '未命名') + '</span>' +
        '</div>' +
        '<div class="layer-meta-line">' +
          '<span class="layer-type">' + escapeHtml(typeText) + '</span>' + (features !== null && features !== undefined ? '<span class="layer-feature-count">· ' + features + ' 个要素</span>' : '') +
        '</div>' +
        '<div class="layer-op-row" title="透明度：拖动调整">' +
          '<span class="layer-op-label">不透明度</span>' +
          '<input type="range" class="layer-row-opacity" min="0" max="100" value="' + op + '" data-id="' + (layer.layer_id || '') + '">' +
          '<span class="layer-op-val" id="opval_' + (layer.layer_id || '') + '">' + op + '%</span>' +
        '</div>' +
      '</td>' +
      '<td class="col-actions"><div class="layer-actions">' +
      '<button class="layer-action-btn" data-action="inspect" data-id="' + (layer.layer_id || '') + '" title="检查图层"><span class="ui-icon" aria-hidden="true" style=";width:14px;height:14px;--ui-icon-image:url(\'/assets/ui-icons/icon-658e8e14699f.png\')"></span></button>' +
      '<button class="layer-action-btn layer-more-btn" data-action="more" data-id="' + (layer.layer_id || '') + '" title="更多图层操作" aria-label="更多图层操作" aria-haspopup="menu">⋯</button>' +
      '</div></td></tr>';
  }

  /** 同步地图叠放顺序与列表一致：列表最上面 = 地图最前面 */
  function _syncLayerOrder() {
    if (!GIS.map || typeof GIS.map.getLayer !== 'function') return;
    // 从后往前 bringToFront，让 layerData[0]（列表最上面）最终在地图最前
    for (let i = layerData.length - 1; i >= 0; i--) {
      const layer = layerData[i];
      const leafletLayer = GIS.map.getLayer(layer._rawName || layer.layer_id);
      if (leafletLayer && typeof leafletLayer.bringToFront === 'function') {
        leafletLayer.bringToFront();
      }
    }
  }

  function _saveGroupingChanges() {
    if (GIS.project && typeof GIS.project.autoSave === 'function') {
      Promise.resolve(GIS.project.autoSave()).catch(function(error) {
        console.warn('[GIS Layers] 分组状态自动保存失败', error);
      });
    }
  }

  // 添加图层：加入列表 + 渲染
  function nextColor() {
    var colors = ['#1c1b1b','#e74c3c','#2ecc71','#3498db','#f39c12','#9b59b6','#1abc9c','#e67e22'];
    return colors[layerData.length % colors.length];
  }

  function _registerLayerForPanel(name, geojson) {
    if (!window.GIS.api || typeof window.GIS.api.registerLayer !== 'function') return Promise.resolve(false);
    var registration;
    try { registration = window.GIS.api.registerLayer(name, geojson); }
    catch (error) { registration = Promise.reject(error); }
    return Promise.resolve(registration).then(function(result) {
      return result !== false;
    }).catch(function(error) {
      console.warn('[GIS Layers] 后端图层注册/同步失败', name, error);
      if (window.GIS.toast && typeof window.GIS.toast.error === 'function') {
        window.GIS.toast.error('图层「' + name + '」未能同步到分析数据，请检查连接后重试');
      }
      return false;
    });
  }

  function _syncEditedLayerData(layerId, geojson) {
    var layer = layerData.find(function(item) { return item.layer_id === layerId; });
    if (!layer || !geojson) return Promise.resolve(false);
    layer.geojson = geojson;
    var features = geojson.type === 'FeatureCollection' ? (geojson.features || []) :
      geojson.type === 'Feature' ? [geojson] : [];
    var usedFids = Object.create(null);
    features.forEach(function(feature, index) {
      if (!feature) return;
      var props = feature.properties || (feature.properties = {});
      var fid = props._fid;
      if (fid === undefined || fid === null || fid === '' || usedFids[fid]) {
        fid = props.adcode !== undefined && props.adcode !== null && props.adcode !== '' ? 'p:' + props.adcode :
          props.id !== undefined && props.id !== null ? 'id:' + props.id :
          props.name ? 'n:' + props.name : 'i:' + index;
        var suffix = 1;
        var base = fid;
        while (usedFids[fid]) fid = base + ':' + suffix++;
        props._fid = fid;
      }
      usedFids[fid] = true;
    });
    var stateLayer = window.GIS.state && window.GIS.state.getLayer ? window.GIS.state.getLayer(layerId) : null;
    if (stateLayer) {
      stateLayer.geojson = geojson;
      stateLayer.featureCount = features.length;
      stateLayer.fidIndex = Object.create(null);
      var bounds = [180, 90, -180, -90];
      var hasCoordinates = false;
      function includeCoordinates(coords) {
        if (!Array.isArray(coords) || !coords.length) return;
        if (typeof coords[0] === 'number' && typeof coords[1] === 'number') {
          bounds[0] = Math.min(bounds[0], coords[0]); bounds[1] = Math.min(bounds[1], coords[1]);
          bounds[2] = Math.max(bounds[2], coords[0]); bounds[3] = Math.max(bounds[3], coords[1]);
          hasCoordinates = true;
        } else coords.forEach(includeCoordinates);
      }
      features.forEach(function(feature, index) {
        var fid = feature && feature.properties && feature.properties._fid;
        if (fid !== undefined && fid !== null) stateLayer.fidIndex[fid] = index;
        if (feature && feature.geometry) includeCoordinates(feature.geometry.coordinates);
      });
      stateLayer.bbox = hasCoordinates ? bounds : null;
    }
    var registeredName = layer._registeredName || layer._rawName || layer.filename || layer.layer_id;
    var promise = _registerLayerForPanel(registeredName, geojson);
    layer._registrationPromise = promise.then(function(ok) {
      if (ok) layer._registeredName = registeredName;
      return ok;
    });
    return layer._registrationPromise;
  }

  function addLayer(layer, skipRegister) {
    // —— 桥接：手动路径（上传/绘制/工程/网络等）的图层统一入共享状态 ——
    // state 会回调本函数（带 _panelSync）走下面的正常入库，并跳过 2D 重复渲染；
    // 这样显隐/透明度/3D 拉伸等手动控件对所有图层生效（2D/3D 同步）。
    if (window.GIS.state && layer.geojson && !layer._panelSync &&
        typeof window.GIS.state.getLayer === 'function') {
      var bridgeMapName = layer._rawName || layer.filename || layer.layer_id || '未命名';
      var bridged = window.GIS.state.addLayer({
        layer_id: layer.layer_id,
        name: layer.filename || bridgeMapName,
        _mapName: bridgeMapName,   // 2D 已按此名渲染，地图操作沿用
        geojson: layer.geojson,
        style: layer.style || { color: layer.color || nextColor() },
        color: layer.color || nextColor(),
        source: layer.source || 'upload',
        visible: layer.visible !== false,
        _panelSync: true,
        _skip2DRender: true,
      });
      // 保持原注册行为（AI 后端需按原名可查）
      if (!skipRegister && window.GIS.api && typeof window.GIS.api.registerLayer === 'function' && layer.geojson) {
        var registrationPromise = _registerLayerForPanel(bridgeMapName, layer.geojson);
        var panelRecord = layerData.find(function(item) { return item.layer_id === bridged.layer_id; });
        if (panelRecord) {
          panelRecord._registeredName = bridgeMapName;
          panelRecord._registrationPromise = registrationPromise;
        }
      }
      return bridged;
    }
    const colors = ['#1c1b1b','#e74c3c','#2ecc71','#3498db','#f39c12','#9b59b6','#1abc9c','#e67e22'];
    const color = layer.color || colors[layerData.length % colors.length];
    // 重名自动加 (1) (2)
    var name = layer.filename || '未命名';
    var _rawName = layer._rawName || layer.filename || layer.layer_id || '未命名'; // 保留原始名称用于地图模块查找（工程加载时传入带 _loaded 后缀的注册名）
    if (layerData.some(function(l) { return l.filename === name; })) {
      var suffix = 1;
      while (layerData.some(function(l) { return l.filename === name + '(' + suffix + ')'; })) { suffix++; }
      name = name + '(' + suffix + ')';
    }
    // 兜底生成 layer_id：工程恢复等场景可能不带 layer_id，缺失会导致删除按钮 data-id 为空而失效
    var _layerId = layer.layer_id || ('layer_' + Date.now().toString(36) + '_' + Math.floor(Math.random() * 1e6).toString(36));
    var isVisible = layer.visible !== false;
    layerData.push({ ...layer, layer_id: _layerId, filename: name, _rawName, visible: isVisible, color });
    if (!layer._panelSync && GIS.map && GIS.map.setLayerColor) GIS.map.setLayerColor(_rawName, color);
    if (!isVisible && GIS.map && GIS.map.setLayerVisible) GIS.map.setLayerVisible(_rawName, false);
    renderList();
    _syncLayerOrder();
    if (!skipRegister && window.GIS.api && typeof window.GIS.api.registerLayer === 'function' && layer.geojson) {
      var registeredLayer = layerData[layerData.length - 1];
      registeredLayer._registeredName = name;
      registeredLayer._registrationPromise = _registerLayerForPanel(name, layer.geojson);
    }
    return layerData[layerData.length - 1] || null;
  }

  // 删除图层：从列表移除 + 从地图清除
  function removeLayer(layerId, _fromState, silent) {
    // 在共享状态中的图层：走 state 统一删除（会回调本函数同步面板/地图/后端）
    if (!_fromState && window.GIS.state && typeof window.GIS.state.getLayer === 'function' &&
        window.GIS.state.getLayer(layerId)) {
      window.GIS.state.removeLayer(layerId);
      return;
    }
    const target = layerData.find(l => l.layer_id === layerId);
    const mapName = target ? (target._rawName || target.layer_id) : null;
    layerData = layerData.filter(l => l.layer_id !== layerId);
    renderList();
    // 图例归属图层被删除 → 图例一并撤下，防止孤儿图例残留
    if (_lastLegendData && _lastLegendData.layerId === layerId) {
      _hideFloatingLegend();
    }
    if (typeof _clearSymbology === 'function') {
      try { _clearSymbology(layerId); } catch(_) {}
    }
    if (mapName && GIS.map && GIS.map.removeLayer) {
      GIS.map.removeLayer(mapName);
    }
    if (target) {
      if (!silent && window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
        window.GIS.chat.addMessage('已删除图层: ' + (target.filename || '图层'), 'system');
      }
      if (window.GIS.api && typeof window.GIS.api.unregisterLayer === 'function') {
        var registeredName = target._registeredName || target.filename || target.layer_id || '';
        var unregisterPromise = Promise.resolve(target._registrationPromise).catch(function() {}).then(function() {
          return window.GIS.api.unregisterLayer(registeredName);
        });
        _trackRegistryOperation(unregisterPromise, '取消注册图层「' + registeredName + '」');
      }
    }
  }

  // 清空所有图层（新建会话/删除工程时调用）：逐个走 removeLayer 保证地图与后端同步清理，默认静默执行不向聊天区灌入冗余系统提示
  function clearAll(silent) {
    if (silent === undefined) silent = true;
    var panelLayers = layerData.slice();
    var errors = [];
    var stateOk = true;
    // 先清共享状态，避免状态中存在但未显示在图层面板的图层在地图清空后又被重新同步。
    if (window.GIS.state && typeof window.GIS.state.clearAll === 'function') {
      try {
        var stateResult = window.GIS.state.clearAll();
        if (stateResult) {
          if (stateResult.ok === false) stateOk = false;
          if (Array.isArray(stateResult.errors)) errors = errors.concat(stateResult.errors);
        }
      } catch(error) { errors.push(error); }
    }
    panelLayers.forEach(function(layer) {
      if (!layerData.some(function(current) { return current.layer_id === layer.layer_id; })) return;
      try { removeLayer(layer.layer_id, true, silent); }
      catch(error) { errors.push(error); }
    });
    layerData = [];
    groups = Object.create(null);
    _groupIdCounter = 0;
    try { renderList(); } catch(error) { errors.push(error); }
    try { _hideFloatingLegend(); } catch(error) { errors.push(error); }
    var mapResult = { ok: true, remaining: 0 };
    if (GIS.map && typeof GIS.map.clearAll === 'function') {
      try { mapResult = GIS.map.clearAll() || mapResult; }
      catch(error) { mapResult = { ok: false, remaining: 0, errors: [error] }; }
    }
    var rendererResult = { ok: true, remaining: 0, errors: [] };
    if (GIS.renderers && typeof GIS.renderers.clearAllLayers === 'function') {
      try { rendererResult = GIS.renderers.clearAllLayers() || rendererResult; }
      catch(error) { rendererResult = { ok: false, remaining: 0, errors: [error] }; }
    }
    var remainingState = window.GIS.state && typeof window.GIS.state.getLayers === 'function'
      ? window.GIS.state.getLayers().length : 0;
    var remainingMap = Number(mapResult.remaining) || 0;
    var remainingRenderer = Number(rendererResult.remaining) || 0;
    var mapErrors = Array.isArray(mapResult.errors) ? mapResult.errors : [];
    var rendererErrors = Array.isArray(rendererResult.errors) ? rendererResult.errors : [];
    errors = errors.concat(mapErrors, rendererErrors);
    return { ok: stateOk && mapResult.ok !== false && rendererResult.ok !== false && errors.length === 0 &&
        layerData.length === 0 && remainingState === 0 && remainingMap === 0 && remainingRenderer === 0,
      removedCount: panelLayers.length, remainingPanel: layerData.length, remainingState: remainingState,
      remainingMap: remainingMap, remainingRenderer: remainingRenderer, errors: errors };
  }

  // 批量切换图层显隐（全部显示 / 全部隐藏）
  function setAllVisibility(visible) {
    if (!layerData || layerData.length === 0) return;
    layerData.forEach(function(layer) {
      layer.visible = !!visible;
      if (window.GIS.state && typeof window.GIS.state.getLayer === 'function' &&
          window.GIS.state.getLayer(layer.layer_id)) {
        window.GIS.state.setVisible(layer.layer_id, layer.visible);
      } else if (GIS.map && GIS.map.setLayerVisible) {
        GIS.map.setLayerVisible(layer._rawName || layer.layer_id, layer.visible);
      }
    });
    renderList();
    if (visible) _syncLayerOrder();
  }

  function showAll() {
    setAllVisibility(true);
  }

  function hideAll() {
    setAllVisibility(false);
  }

  function _moveLayerAtDrop(srcIndex, targetIndex, position) {
    const moved = layerData[srcIndex];
    const targetLayer = layerData[targetIndex];
    if (!moved || !targetLayer) return false;

    layerData.splice(srcIndex, 1);
    let insertIndex = targetIndex;
    if (srcIndex < targetIndex) {
      insertIndex = position === 'before' ? targetIndex - 1 : targetIndex;
    } else {
      insertIndex = position === 'before' ? targetIndex : targetIndex + 1;
    }
    insertIndex = Math.max(0, Math.min(insertIndex, layerData.length));

    // Dropping on an ungrouped row must also remove the old group assignment.
    moved.groupId = targetLayer.groupId || null;
    layerData.splice(insertIndex, 0, moved);
    renderList();
    _syncLayerOrder();
    return true;
  }

  // 切换图层显隐
  function toggleVisibility(layerId) {
    const layer = layerData.find(l => l.layer_id === layerId);
    if (!layer) return;
    layer.visible = !layer.visible;
    renderList();
    // 在共享状态中的图层：写回 state，由 state 广播 3D（2D 渲染由 state 内部驱动）
    if (window.GIS.state && typeof window.GIS.state.getLayer === 'function' &&
        window.GIS.state.getLayer(layerId)) {
      window.GIS.state.setVisible(layerId, layer.visible);
    } else if (GIS.map && GIS.map.setLayerVisible) {
      GIS.map.setLayerVisible(layer._rawName || layer.layer_id, layer.visible);
    }
    // 显示图层后 Leaflet 会把它放到最上层，重新同步叠放顺序
    if (layer.visible) _syncLayerOrder();
  }

  // 下载图层（显示格式选择弹窗）
  function downloadLayer(layerId) {
    const layer = layerData.find(l => l.layer_id === layerId);
    if (!layer) return;
    var geojson = layer.geojson;
    if (!geojson && GIS.map && GIS.map.getGeoJSON) {
      geojson = GIS.map.getGeoJSON(layer._rawName || layer.layer_id);
    }
    if (!geojson) {
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') window.GIS.chat.addMessage('无数据可下载', 'system');
      return;
    }
    // 显示格式选择弹窗
    _showDownloadDialog(layer, geojson);
  }

  /** 下载格式选择弹窗 */
  function _showDownloadDialog(layer, geojson) {
    var overlay = document.createElement('div');
    overlay.className = 'download-dialog-overlay';
    overlay.innerHTML =
      '<div class="download-dialog">' +
        '<div class="download-dialog-title">导出图层</div>' +
        '<div class="download-dialog-subtitle">' + escapeHtml(layer.filename || '图层') + '</div>' +
        '<div class="download-dialog-options">' +
          '<label class="download-dialog-option selected" data-format="geojson">' +
            '<span class="download-dialog-radio"><span class="download-dialog-radio-dot"></span></span>' +
            '<span class="download-dialog-label"><strong>GeoJSON (.geojson)</strong><span class="download-dialog-desc">通用地理数据，QGIS / ArcGIS / WebGIS 均可直接打开</span></span>' +
          '</label>' +
          '<label class="download-dialog-option" data-format="shp">' +
            '<span class="download-dialog-radio"><span class="download-dialog-radio-dot"></span></span>' +
            '<span class="download-dialog-label"><strong>Shapefile (.shp / .zip)</strong><span class="download-dialog-desc">经典 GIS 工业格式，打包含 .shp .shx .dbf .prj，QGIS / ArcGIS 无缝兼容</span></span>' +
          '</label>' +
        '</div>' +
        '<div class="download-dialog-actions">' +
          '<button class="download-dialog-btn download-dialog-cancel">取消</button>' +
          '<button class="download-dialog-btn download-dialog-confirm">立即下载</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    var selectedFormat = 'geojson';
    var options = overlay.querySelectorAll('.download-dialog-option');
    options.forEach(function(opt) {
      opt.addEventListener('click', function() {
        options.forEach(function(o) { o.classList.remove('selected'); });
        opt.classList.add('selected');
        selectedFormat = opt.getAttribute('data-format');
      });
    });

    overlay.querySelector('.download-dialog-cancel').addEventListener('click', function() {
      document.body.removeChild(overlay);
    });
    overlay.querySelector('.download-dialog-confirm').addEventListener('click', function() {
      document.body.removeChild(overlay);
      if (selectedFormat === 'geojson') {
        _downloadGeoJSON(layer, geojson);
      } else if (selectedFormat === 'shp') {
        _downloadSHP(layer, geojson);
      }
    });
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) document.body.removeChild(overlay);
    });
  }

  /** 下载 GeoJSON */
  function _downloadGeoJSON(layer, geojson) {
    var blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/geo+json;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (layer.filename || '图层') + '.geojson';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /** 下载 SHP（调后端接口） */
  function _downloadSHP(layer, geojson) {
    if (!window.GIS.api || typeof window.GIS.api.exportShp !== 'function') {
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function')
        window.GIS.chat.addMessage('SHP 导出服务不可用', 'system');
      return;
    }
    window.GIS.api.exportShp(geojson, layer.filename || '图层');
  }

  function bindDragEvents() {
    if (!tbody) return;
    let dragSrcIndex = null;
    let dropPosition = null; // 'before' or 'after'
    let currentHoverTr = null;

    function cleanupDragStyles() {
      tbody.querySelectorAll('.group-drag-over').forEach(r => r.classList.remove('group-drag-over'));
      tbody.querySelectorAll('.drag-over, .drag-over-top, .drag-over-bottom').forEach(r => {
        r.classList.remove('drag-over', 'drag-over-top', 'drag-over-bottom');
      });
      const placeholder = tbody.querySelector('.layer-drop-placeholder');
      if (placeholder) placeholder.remove();
      currentHoverTr = null;
      dropPosition = null;
    }

    tbody.addEventListener('dragstart', (e) => {
      const tr = e.target.closest('tr[draggable]');
      if (!tr) return;
      if (!e.target.closest('.drag-handle')) { e.preventDefault(); return; }
      dragSrcIndex = parseInt(tr.dataset.index, 10);
      tr.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', tr.dataset.id || tr.dataset.index);
    });

    tbody.addEventListener('dragend', () => {
      dragSrcIndex = null;
      tbody.querySelectorAll('tr').forEach(r => r.classList.remove('dragging'));
      cleanupDragStyles();
    });

    tbody.addEventListener('dragover', (e) => {
      e.preventDefault();
      const groupTr = e.target.closest('tr.group-header:not(.group-header-ungrouped)');
      if (groupTr) {
        e.dataTransfer.dropEffect = 'move';
        tbody.querySelectorAll('.drag-over-top, .drag-over-bottom').forEach(r => r.classList.remove('drag-over-top', 'drag-over-bottom'));
        groupTr.classList.add('group-drag-over');
        return;
      }
      tbody.querySelectorAll('.group-drag-over').forEach(r => r.classList.remove('group-drag-over'));

      const tr = e.target.closest('tr[draggable]');
      if (!tr || tr.classList.contains('dragging')) return;
      e.dataTransfer.dropEffect = 'move';

      // 计算鼠标在目标行内的高度比例，决定插入上方还是下方
      const rect = tr.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      const isTop = e.clientY < midY;

      if (currentHoverTr !== tr || dropPosition !== (isTop ? 'before' : 'after')) {
        tbody.querySelectorAll('.drag-over-top, .drag-over-bottom').forEach(r => r.classList.remove('drag-over-top', 'drag-over-bottom'));
        currentHoverTr = tr;
        dropPosition = isTop ? 'before' : 'after';
        if (isTop) {
          tr.classList.add('drag-over-top');
        } else {
          tr.classList.add('drag-over-bottom');
        }
      }
    });

    tbody.addEventListener('dragleave', (e) => {
      const groupTr = e.target.closest('tr.group-header');
      if (groupTr && !groupTr.contains(e.relatedTarget)) {
        groupTr.classList.remove('group-drag-over');
      }
      const tr = e.target.closest('tr[draggable]');
      if (tr && !tr.contains(e.relatedTarget)) {
        tr.classList.remove('drag-over', 'drag-over-top', 'drag-over-bottom');
        if (currentHoverTr === tr) {
          currentHoverTr = null;
          dropPosition = null;
        }
      }
    });

    tbody.addEventListener('drop', (e) => {
      e.preventDefault();
      const groupTr = e.target.closest('tr.group-header:not(.group-header-ungrouped)');
      if (groupTr && dragSrcIndex !== null) {
        var gid = groupTr.dataset.group;
        var srcLayer = layerData[dragSrcIndex];
        if (srcLayer && gid) {
          moveLayerToGroup(srcLayer.layer_id, gid);
          if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
            window.GIS.toast.success('已将图层「' + (srcLayer.filename || '') + '」移入「' + (groups[gid] ? groups[gid].name : '') + '」');
          }
        }
        cleanupDragStyles();
        dragSrcIndex = null;
        return;
      }

      const tr = e.target.closest('tr[draggable]');
      if (!tr || dragSrcIndex === null) {
        cleanupDragStyles();
        dragSrcIndex = null;
        return;
      }

      const target = parseInt(tr.dataset.index, 10);
      const isInsertBefore = dropPosition === 'before';
      cleanupDragStyles();

      if (dragSrcIndex === target) {
        dragSrcIndex = null;
        return;
      }
      const sourceIndex = dragSrcIndex;
      dragSrcIndex = null;
      _moveLayerAtDrop(sourceIndex, target, isInsertBefore ? 'before' : 'after');
    });
  }

  /** 图层分组控制及头部批量操作 */
  function bindGroupEvents() {
    var showAllBtn = document.getElementById('showAllLayersBtn');
    if (showAllBtn) {
      showAllBtn.addEventListener('click', function() {
        showAll();
      });
    }
    var hideAllBtn = document.getElementById('hideAllLayersBtn');
    if (hideAllBtn) {
      hideAllBtn.addEventListener('click', function() {
        hideAll();
      });
    }
    var clearAllBtn = document.getElementById('clearAllLayersBtn');
    if (clearAllBtn) {
      clearAllBtn.addEventListener('click', function() {
        var count = (layerData || []).length;
        var doClear = function() {
          var result = clearAll();
          if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
            if (result.ok) {
              window.GIS.chat.addMessage(count
                ? '已清空全部 ' + count + ' 个图层'
                : '已清理地图上的残留图层', 'system', { pill: true });
            } else {
              var remaining = Math.max(result.remainingPanel, result.remainingState, result.remainingMap, result.remainingRenderer);
              var detail = remaining
                ? '仍有 ' + remaining + ' 个图层或地图覆盖层未清除。'
                : '地图清理未能确认完成，请重试并检查地图显示。';
              window.GIS.chat.addMessage('清理未完全成功：' + detail, 'system', { pill: true });
            }
          }
        };
        if (window.GIS.workspace && typeof window.GIS.workspace.confirmModal === 'function') {
          var message = count
            ? '确定要清空当前地图上的全部 ' + count + ' 个图层吗？此操作不可恢复。'
            : '图层列表为空。仍要清理地图上的残留图层吗？';
          window.GIS.workspace.confirmModal('清空图层确认', message, doClear, true);
        } else if (typeof showConfirm === 'function') {
          var fallbackMessage = count
            ? '确定要清空当前地图上的全部 ' + count + ' 个图层吗？此操作不可恢复。'
            : '图层列表为空。仍要清理地图上的残留图层吗？';
          showConfirm('清空图层确认', fallbackMessage, doClear);
        } else if (confirm('确定要清空全部 ' + count + ' 个图层吗？')) {
          doClear();
        }
      });
    }
    var newLayerBtn = document.getElementById('newLayerBtn');
    if (newLayerBtn) {
      newLayerBtn.addEventListener('click', function() {
        _showCreateLayerModal();
      });
    }
    var newBtn = document.getElementById('newGroupBtn');
    if (newBtn) {
      newBtn.addEventListener('click', function() {
        addGroup();
      });
    }
    if (!tbody) return;
    tbody.addEventListener('click', function(e) {
      var toggle = e.target.closest('.group-toggle');
      if (toggle) {
        var gid = toggle.dataset.group;
        if (groups[gid]) {
          groups[gid].collapsed = !groups[gid].collapsed;
          renderList();
        }
        return;
      }
      var delBtn = e.target.closest('.group-delete-btn');
      if (delBtn) {
        var gidDel = delBtn.dataset.group;
        if (gidDel && groups[gidDel]) {
          var gName = groups[gidDel].name;
          deleteGroup(gidDel);
          if (window.GIS.toast && typeof window.GIS.toast.info === 'function') {
            window.GIS.toast.info('已解散分组「' + gName + '」');
          }
        }
        return;
      }
      var renBtn = e.target.closest('.group-rename-btn');
      if (renBtn) {
        var gidRen = renBtn.dataset.group;
        if (gidRen && groups[gidRen]) {
          var row = renBtn.closest('.group-header');
          _triggerGroupRename(gidRen, row && row.querySelector('.group-name-text'));
        }
        return;
      }
      var nameEl = e.target.closest('.group-name-text');
      if (nameEl) {
        var gid2 = nameEl.dataset.group;
        if (!gid2 || !groups[gid2]) return;
        _triggerGroupRename(gid2, nameEl);
      }
    });
  }

  function _triggerGroupRename(groupId, nameEl) {
    var group = groups[groupId];
    if (!group || !nameEl || nameEl.querySelector('input')) return;
    var oldName = group.name;
    var cancelled = false;
    var input = document.createElement('input');
    input.type = 'text';
    input.value = oldName;
    input.className = 'layer-rename-input group-rename-input';
    input.setAttribute('aria-label', '重命名分组');
    input.style.cssText = 'width:100%;min-width:80px;box-sizing:border-box;border:1px solid var(--ui-gray-400);border-radius:2px;padding:1px 4px;font-size:inherit;font-family:inherit;background:var(--ui-white);color:var(--ui-gray-900);';
    nameEl.textContent = '';
    nameEl.appendChild(input);
    input.focus();
    input.select();

    function commit() {
      if (cancelled) return;
      var nextName = input.value.trim();
      if (!nextName || nextName === oldName) {
        nameEl.textContent = oldName;
        return;
      }
      var duplicate = Object.keys(groups).some(function(id) {
        return id !== groupId && groups[id].name.toLocaleLowerCase() === nextName.toLocaleLowerCase();
      });
      if (duplicate) {
        nameEl.textContent = oldName;
        if (GIS.toast && GIS.toast.warn) GIS.toast.warn('已有同名分组，请换一个名称');
        return;
      }
      group.name = nextName;
      renderList();
      _saveGroupingChanges();
    }

    input.addEventListener('blur', commit);
    input.addEventListener('keydown', function(event) {
      if (event.key === 'Enter') { event.preventDefault(); input.blur(); }
      if (event.key === 'Escape') {
        event.preventDefault();
        cancelled = true;
        nameEl.textContent = oldName;
      }
    });
  }

  /** 新建分组 */
  function addGroup(name) {
    var gid = 'group_' + (++_groupIdCounter);
    var groupName = name || '新分组 ' + _groupIdCounter;
    groups[gid] = {
      id: gid,
      name: groupName,
      collapsed: false,
    };
    renderList();
    _saveGroupingChanges();
    if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
      window.GIS.toast.success('已新建分组「' + groupName + '」');
    }
    return gid;
  }

  function getGroupState() {
    return Object.keys(groups).map(function(id) {
      return { id: id, name: groups[id].name, collapsed: !!groups[id].collapsed };
    });
  }

  function setGroupState(groupState) {
    groups = Object.create(null);
    _groupIdCounter = 0;
    (Array.isArray(groupState) ? groupState : []).forEach(function(group) {
      if (!group || typeof group.id !== 'string' || !group.id || typeof group.name !== 'string' || !group.name.trim()) return;
      groups[group.id] = { id: group.id, name: group.name.trim(), collapsed: !!group.collapsed };
      var match = group.id.match(/^group_(\d+)$/);
      if (match) _groupIdCounter = Math.max(_groupIdCounter, Number(match[1]));
    });
    renderList();
  }

  /** 将图层移入分组 */
  function moveLayerToGroup(layerId, groupId) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (layer) {
      layer.groupId = groupId;
      renderList();
      _syncLayerOrder();
      _saveGroupingChanges();
    }
  }

  /** 从分组中移除图层 */
  function removeLayerFromGroup(layerId) {
    moveLayerToGroup(layerId, null);
  }

  /** 删除分组 */
  function deleteGroup(groupId) {
    if (!groups[groupId]) return;
    layerData.forEach(function(l) {
      if (l.groupId === groupId) l.groupId = null;
    });
    delete groups[groupId];
    renderList();
    _saveGroupingChanges();
  }

  /** 弹窗选择/新建分组将图层移动至分组 */
  function _showMoveToGroupModal(layerId) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;
    var gKeys = Object.keys(groups);

    var overlay = document.createElement('div');
    overlay.className = 'workspace-modal-overlay';
    
    var optionsHtml = '';
    gKeys.forEach(function(gid) {
      var isCurrent = layer.groupId === gid;
      optionsHtml += '<label style="display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--outline-variant,#ddd);border-radius:6px;cursor:pointer;font-size:12px;background:var(--surface-container-low,#f5f2f0);margin-bottom:6px;">' +
        '<input type="radio" name="targetGroupOption" value="' + escapeHtml(gid) + '"' + (isCurrent ? ' checked' : '') + ' style="accent-color:var(--primary,#000);" />' +
        '<span><span style="display:inline-flex;align-items:center;vertical-align:-2px;margin-right:4px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span> <strong>' + escapeHtml(groups[gid].name) + '</strong>' + (isCurrent ? ' <em style="color:#888;font-size:11px;">(当前归属)</em>' : '') + '</span>' +
      '</label>';
    });

    optionsHtml += '<label style="display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--outline-variant,#ddd);border-radius:6px;cursor:pointer;font-size:12px;background:var(--surface-container-low,#f5f2f0);margin-bottom:6px;">' +
      '<input type="radio" name="targetGroupOption" value="__new__"' + (gKeys.length === 0 ? ' checked' : '') + ' style="accent-color:var(--primary,#000);" />' +
      '<span><span style="display:inline-flex;align-items:center;vertical-align:-2px;margin-right:6px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></span> <strong>新建分组并移入</strong></span>' +
    '</label>';

    overlay.innerHTML =
      '<div class="workspace-modal-dialog" role="dialog" aria-modal="true" style="max-width:380px;">' +
        '<div class="workspace-modal-title">移动图层至分组</div>' +
        '<div class="workspace-modal-desc">为「' + escapeHtml(layer.filename || '未命名') + '」选择归属分组：</div>' +
        '<div style="max-height:220px;overflow-y:auto;margin-bottom:12px;">' +
          optionsHtml +
        '</div>' +
        '<div id="newGroupNameWrapper" style="margin-bottom:12px;' + (gKeys.length > 0 ? 'display:none;' : '') + '">' +
          '<label style="display:block;font-size:11px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">新分组名称</label>' +
          '<input type="text" id="newGroupNameInput" class="workspace-modal-input" placeholder="输入新分组名称" value="新分组 ' + (_groupIdCounter + 1) + '" style="margin-bottom:0;" />' +
        '</div>' +
        '<div class="workspace-modal-actions">' +
          (layer.groupId ? '<button type="button" class="workspace-modal-btn" id="removeFromGroupBtn" style="margin-right:auto;color:#d9534f;border-color:rgba(217,83,79,0.4);">移出分组</button>' : '') +
          '<button type="button" class="workspace-modal-btn cancel" id="cancelMoveGroupBtn">取消</button>' +
          '<button type="button" class="workspace-modal-btn primary" id="confirmMoveGroupBtn">确定</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    function close() { overlay.remove(); }
    overlay.querySelector('#cancelMoveGroupBtn').onclick = close;
    overlay.onclick = function(e) { if (e.target === overlay) close(); };

    var newWrapper = overlay.querySelector('#newGroupNameWrapper');
    var newNameInput = overlay.querySelector('#newGroupNameInput');
    overlay.querySelectorAll('input[name="targetGroupOption"]').forEach(function(r) {
      r.addEventListener('change', function() {
        if (this.value === '__new__') {
          newWrapper.style.display = 'block';
          newNameInput.focus();
          newNameInput.select();
        } else {
          newWrapper.style.display = 'none';
        }
      });
    });

    var removeBtn = overlay.querySelector('#removeFromGroupBtn');
    if (removeBtn) {
      removeBtn.onclick = function() {
        moveLayerToGroup(layerId, null);
        close();
        if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
          window.GIS.toast.success('已移出分组');
        }
      };
    }

    overlay.querySelector('#confirmMoveGroupBtn').onclick = function() {
      var checked = overlay.querySelector('input[name="targetGroupOption"]:checked');
      if (!checked) { close(); return; }
      var val = checked.value;
      if (val === '__new__') {
        var gname = (newNameInput ? newNameInput.value.trim() : '') || ('新分组 ' + (_groupIdCounter + 1));
        var gid = addGroup(gname);
        moveLayerToGroup(layerId, gid);
        close();
      } else {
        moveLayerToGroup(layerId, val);
        close();
        if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
          window.GIS.toast.success('已移动至分组「' + (groups[val] ? groups[val].name : '') + '」');
        }
      }
    };
  }

  /** 获取 GeoJSON 的中心点坐标（取所有坐标平均） */
  function getGeoJSONCenter(geojson) {
    try {
      var coords = [];
      function extractCoords(geom) {
        if (!geom) return;
        if (geom.type === 'Point') coords.push(geom.coordinates);
        else if (geom.type === 'MultiPoint' || geom.type === 'LineString') coords.push.apply(coords, geom.coordinates);
        else if (geom.type === 'MultiLineString' || geom.type === 'Polygon') {
          geom.coordinates.forEach(function(ring) { coords.push.apply(coords, ring); });
        } else if (geom.type === 'MultiPolygon') {
          geom.coordinates.forEach(function(poly) {
            poly.forEach(function(ring) { coords.push.apply(coords, ring); });
          });
        }
      }
      if (geojson.type === 'Feature') extractCoords(geojson.geometry);
      else if (geojson.type === 'FeatureCollection') geojson.features.forEach(function(f) { extractCoords(f.geometry); });
      if (coords.length === 0) return null;
      var avgLng = coords.reduce(function(s, c) { return s + c[0]; }, 0) / coords.length;
      var avgLat = coords.reduce(function(s, c) { return s + c[1]; }, 0) / coords.length;
      return { lat: avgLat, lng: avgLng };
    } catch(e) { return null; }
  }

  /** 将图层暂存到输入框附件栏，让用户自己输入分析指令 */
  function analyzeLayer(layerId) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;
    var geojson = layer.geojson;
    if (!geojson && GIS.map && GIS.map.getGeoJSON) {
      geojson = GIS.map.getGeoJSON(layer._rawName || layer.layer_id);
    }
    if (!geojson) {
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
        window.GIS.chat.addMessage('该图层无可用数据', 'system');
      }
      return;
    }
    var center = getGeoJSONCenter(geojson);
    var coordsStr = center ? center.lat.toFixed(6) + ', ' + center.lng.toFixed(6) : null;

    // 要素数
    var featCount = 0;
    if (geojson.type === 'FeatureCollection') featCount = (geojson.features || []).length;
    else if (geojson.type === 'Feature') featCount = 1;

    if (window.GIS.chat && typeof window.GIS.chat.setPendingLayer === 'function') {
      window.GIS.chat.setPendingLayer({
        name: layer.filename || '未命名',
        type: layer.geometry_type || geojson.type || '未知',
        coords: coordsStr,
        count: featCount,
        geojson: geojson,
      });
    }
  }

  function bindActionEvents() {
    if (!tbody) return;
    //监听
    tbody.addEventListener('click', (e) => {
      // 颜色点点击 → 弹出颜色选择器（符号化启用时禁用）
      const dot = e.target.closest('.layer-color-dot');
      if (dot) {
        const id = dot.dataset.id;
        // 检查符号化是否启用
        if (_symbologyConfig[id] && _symbologyConfig[id].enabled) {
          return;
        }
        const input = document.createElement('input');
        input.type = 'color';
        input.value = dot.dataset.color || '#1c1b1b';
        input.addEventListener('input', function() {
          const layer = layerData.find(l => l.layer_id === id);
          if (layer) {
            layer.color = this.value;
            dot.style.background = this.value;
            dot.dataset.color = this.value;
            if (GIS.state && GIS.state.getLayer(id)) {
              GIS.state.setStyle(id, { color: this.value, fillColor: this.value });
            } else if (GIS.map && GIS.map.setLayerColor) {
              GIS.map.setLayerColor(layer._rawName || layer.layer_id, this.value);
            }
            if (!layer.visible && GIS.map && GIS.map.setLayerVisible) {
              GIS.map.setLayerVisible(layer._rawName || layer.layer_id, false);
            }
          }
        });
        input.click();
        return;
      }

      // 显隐/删除按钮点击 → 执行相应操作
      //向上找一个匹配的祖先元素
      const btn = e.target.closest('.layer-action-btn');
      if (!btn) return;
      const action = btn.dataset.action;
      // 获取图层 ID
      const id = btn.dataset.id;
      if (!id) return;
      if (action === 'visibility') toggleVisibility(id);
      if (action === 'delete') removeLayer(id);
      if (action === 'download') downloadLayer(id);
      if (action === 'analyze') analyzeLayer(id);
      if (action === 'inspect') showLayerInspector(id);
      if (action === 'swipe') handleSwipeAction(id, btn);
      if (action === 'more') {
        e.stopPropagation();
        const rect = btn.getBoundingClientRect();
        _showContextMenu(rect.left, rect.bottom + 4, id);
      }
    });

    // ============================================================
    // 卷帘对比（手动入口）：点第一个图层的「卷帘」按钮选中为 A（按钮高亮），
    // 再点另一个图层的「卷帘」按钮即开启 A|B 对比；再点 A 或点关闭按钮可关闭。
    // ============================================================
    var _swipeSelId = null;
    _handleSwipeAction = handleSwipeAction;

    function handleSwipeAction(id, btn) {
      // 3D 模式不支持
      if (GIS.renderers && GIS.renderers.is3D && GIS.renderers.is3D()) {
        alert('卷帘对比目前仅支持 2D 模式，请先切换回 2D 地图');
        return;
      }
      if (!GIS.map || typeof GIS.map.startSwipe !== 'function') return;
      // 已开启卷帘：再次点任意「卷帘」按钮 → 关闭
      if (_swipeSelId === null && document.querySelector('.swipe-divider')) {
        GIS.map.stopSwipe();
        _clearSwipeSelection();
        return;
      }
      if (_swipeSelId === null) {
        _swipeSelId = id;
        btn.classList.add('swipe-armed');
        btn.title = '已选中为卷帘 A 图层，再点另一图层的卷帘按钮开始对比';
        return;
      }
      if (_swipeSelId === id) {
        _clearSwipeSelection();
        return;
      }
      var a = layerData.find(function(l) { return l.layer_id === _swipeSelId; });
      var b = layerData.find(function(l) { return l.layer_id === id; });
      _clearSwipeSelection();
      if (!a || !b) return;
      var an = a._rawName || a.filename;
      var bn = b._rawName || b.filename;
      if (GIS.map.startSwipe(an, bn, 'vertical')) {
        renderList();
      }
    }

    function _clearSwipeSelection() {
      _swipeSelId = null;
      tbody.querySelectorAll('.layer-action-btn.swipe-armed').forEach(function(b) {
        b.classList.remove('swipe-armed');
        b.title = b.dataset.action === 'more' ? '更多图层操作' : '卷帘对比（先点一个图层，再点另一个）';
      });
    }

    // 透明度滑块输入联动
    tbody.addEventListener('input', function(e) {
      var slider = e.target.closest('.layer-row-opacity');
      if (!slider) return;
      var id = slider.dataset.id;
      if (!id) return;
      var layer = layerData.find(function(l) { return l.layer_id === id; });
      if (!layer) return;
      var o = parseInt(slider.value, 10) / 100;
      layer.opacity = o;
      var valEl = document.getElementById('opval_' + id);
      if (valEl) valEl.textContent = slider.value + '%';
      var rowEl = slider.closest('tr');
      if (rowEl) {
        var dotEl = rowEl.querySelector('.layer-color-dot');
        if (dotEl) {
          dotEl.style.opacity = String(o);
          dotEl.title = '修改颜色 · 不透明度 ' + slider.value + '%';
        }
      }
      if (GIS.map && GIS.map.setLayerOpacity) {
        GIS.map.setLayerOpacity(layer._rawName || layer.layer_id, o);
      }
      if (window.GIS.state && typeof window.GIS.state.setOpacity === 'function' &&
          window.GIS.state.getLayer(id)) {
        window.GIS.state.setOpacity(id, o);
      }

      // 如果检查器打开且正是当前图层，同步检查器里的滑块与数值
      var insp = document.getElementById('layerInspector');
      if (insp && insp.style.display !== 'none') {
        var inspOp = document.getElementById('layerOpacity');
        var inspVal = document.getElementById('layerOpacityVal');
        if (inspOp) inspOp.value = slider.value;
        if (inspVal) inspVal.textContent = slider.value + '%';
      }
    });

    // 双击图层名重命名
    tbody.addEventListener('dblclick', function(e) {
      var nameEl = e.target.closest('.layer-name');
      if (!nameEl) return;
      var id = nameEl.dataset.id;
      if (!id) return;
      _triggerRename(id);
    });
  }

  function escapeHtml(str) {
    return window.GIS.utils ? window.GIS.utils.escapeHtml(str) : ('' + (str || ''));
  }

  // ---- 几何坐标辅助函数 ----

  /** 递归统计几何图形的顶点数 */
  function _countCoords(c) {
    if (!c || !c.length) return 0;
    return typeof c[0] === 'number' ? 1 : c.reduce(function(s, v) { return s + _countCoords(v); }, 0);
  }

  /** 虚拟坐标列显示名映射 */
  var VIRTUAL_DISPLAY = {
    '_经度': '经度',
    '_纬度': '纬度',
    '_几何类型': '几何类型',
    '_顶点数': '顶点数'
  };
  var VIRTUAL_KEYS_ALL = ['_经度', '_纬度', '_几何类型', '_顶点数'];

  /** 判断图层是否为纯点图层 */
  function _isPointLayer(features) {
    return features.length > 0 && features.every(function(f) { return f.geometry && f.geometry.type === 'Point'; });
  }

  // ===== 图层检查器 =====

  /** 前端快速统计 GeoJSON 基础信息 */
  function _fastInspect(geojson) {
    var info = { featureCount: 0, geometryType: '', attrFields: {}, bbox: null, nullGeom: 0 };
    if (!geojson) return info;
    var features = [];
    if (geojson.type === 'FeatureCollection') features = geojson.features || [];
    else if (geojson.type === 'Feature') features = [geojson];
    else return info;

    info.featureCount = features.length;
    var types = new Set();
    var allLngs = [], allLats = [];

    features.forEach(function(f) {
      var geom = f.geometry;
      var props = f.properties || {};

      for (var k in props) {
        if (k === '_fid') continue; // Stable feature identity is internal, never an editable attribute.
        if (!info.attrFields[k]) info.attrFields[k] = typeof props[k];
      }

      if (!geom) { info.nullGeom++; return; }
      if (geom.type) types.add(geom.type);

      // 提取坐标
      function collect(c) {
        if (!c || !c.length) return;
        if (typeof c[0] === 'number') { allLngs.push(c[0]); allLats.push(c[1]); }
        else c.forEach(collect);
      }
      collect(geom.coordinates);
    });

    info.geometryType = types.size ? Array.from(types).join(', ') : '无几何';
    if (allLngs.length) {
      info.bbox = [
        Math.min.apply(null, allLngs),
        Math.min.apply(null, allLats),
        Math.max.apply(null, allLngs),
        Math.max.apply(null, allLats),
      ];
    }
    return info;
  }

  /** 打开图层检查器面板 */
  async function showLayerInspector(layerId, initialTab) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;

    var geojson = layer.geojson;
    if (!geojson && GIS.map && GIS.map.getGeoJSON) {
      geojson = GIS.map.getGeoJSON(layer._rawName || layer.layer_id);
    }
    if (!geojson) {
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
        window.GIS.chat.addMessage('图层「' + (layer.filename || '未命名') + '」无可用数据', 'system');
      }
      return;
    }

    var panel = document.getElementById('layerInspector');
    var body = document.getElementById('inspectorBody');
    var title = document.getElementById('inspectorTitle');
    if (!panel || !body) return;

    // 记录或继承当前激活的标签页，避免保存或添加数据时跳回基础信息
    var activeTabId = initialTab;
    if (!activeTabId) {
      var curActive = body.querySelector('.inspector-tab.active');
      if (curActive) {
        activeTabId = curActive.getAttribute('data-tab');
      }
    }
    if (!activeTabId) activeTabId = 'info';

    // 前端快速统计
    var local = _fastInspect(geojson);

    // 后端补充检查 CRS
    var remote = {};
    try {
      if (window.GIS.api && typeof window.GIS.api.inspectLayer === 'function') {
        remote = await window.GIS.api.inspectLayer(geojson, layer.filename || '');
      }
    } catch(e) {
      console.warn('[GIS Layers] 后端检测失败:', e);
    }

    // 组装检查结果
    var crsStr = remote.crs || '未知（仅前端检测）';
    var crsKnown = remote.crs_known !== false;
    var crsBadge = crsKnown
      ? '<span style="color:#2e7d32;font-weight:600;display:inline-flex;align-items:center;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg></span>'
      : '<span style="color:#d32f2f;font-weight:600;">?</span>';

    var attrHtml = '';
    var attrFields = Object.assign({}, local.attrFields || {});
    if (remote.attr_fields) {
      Object.keys(remote.attr_fields).forEach(function(k) {
        if (k === '_fid') return;
        if (!attrFields[k]) attrFields[k] = remote.attr_fields[k];
      });
    }
    var attrKeys = Object.keys(attrFields);
    if (attrKeys.length > 0) {
      attrHtml = '<table class="inspector-attr-table"><tr><th>字段</th><th>类型</th></tr>';
      attrKeys.forEach(function(k) {
        attrHtml += '<tr><td>' + escapeHtml(k) + '</td><td>' + escapeHtml(attrFields[k]) + '</td></tr>';
      });
      attrHtml += '</table>';
    } else {
      attrHtml = '<span style="color:var(--ui-gray-300);">无属性字段</span>';
    }

    var bbox = remote.bbox || local.bbox;
    var bboxStr = bbox
      ? bbox.map(function(v) { return v.toFixed(6); }).join(', ')
      : '无法计算';

    var invalidCount = remote.invalid_geom_count !== undefined ? remote.invalid_geom_count : '未检测';

    if (title) title.textContent = layer.filename || '图层检查';

    // 获取 features 列表用于属性数据表
    var features = [];
    if (geojson.type === 'FeatureCollection') features = geojson.features || [];
    else if (geojson.type === 'Feature') features = [geojson];

  // ---- 虚拟坐标列 ----
    var virtualKeys = [];
    if (features.length > 0) {
      if (_isPointLayer(features)) {
        virtualKeys.push('_经度');
        virtualKeys.push('_纬度');
      } else {
        virtualKeys.push('_几何类型');
        virtualKeys.push('_顶点数');
      }
    }
    var displayKeys = virtualKeys.concat(attrKeys);

    // 构建可编辑属性数据表
    var dataHtml = '';
    if (features.length > 0 && displayKeys.length > 0) {
      dataHtml += '<div class="attr-toolbar">' +
        '<span class="inspector-section-title" style="margin-bottom:0;border:none;">属性数据 (' + features.length + ' 条)</span>' +
        '<div class="attr-toolbar-btns">' +
          '<button class="attr-btn" data-action="save-attrs" data-layer="' + layerId + '" title="保存修改">' +
            "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-d6c0572e9989.png')\"></span>" +
            '保存' +
          '</button>' +
          '<button class="attr-btn" data-action="add-row" data-layer="' + layerId + '" title="添加行">' +
            "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-493d1c3ed7c4.png')\"></span>" +
            '+ 行' +
          '</button>' +
          '<button class="attr-btn" data-action="add-col" data-layer="' + layerId + '" title="添加字段 (加列)">' +
            '<svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>' +
            '+ 列' +
          '</button>' +
          '<button class="attr-btn" data-action="calc-field" data-layer="' + layerId + '" title="字段计算器 (类似ArcMap)">' +
            '<svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="4" y="2" width="16" height="20" rx="2"></rect><line x1="8" y1="6" x2="16" y2="6"></line><line x1="16" y1="14" x2="16" y2="14.01"></line><line x1="12" y1="14" x2="12" y2="14.01"></line><line x1="8" y1="14" x2="8" y2="14.01"></line><line x1="16" y1="18" x2="16" y2="18.01"></line><line x1="12" y1="18" x2="12" y2="18.01"></line><line x1="8" y1="18" x2="8" y2="18.01"></line></svg>' +
            '计算器' +
          '</button>' +
          '<button class="attr-btn" data-action="toggle-filter" data-layer="' + layerId + '" title="筛选">' +
            "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-9cd115a22f65.png')\"></span>" +
            '筛选' +
          '</button>' +
          '<button class="attr-btn" data-action="export-csv" data-layer="' + layerId + '" title="导出 CSV">' +
            "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-e41ef486154e.png')\"></span>" +
          '</button>' +
        '</div>' +
      '</div>' +
      '<div class="attr-fill-row">' +
        '<span class="attr-fill-label">空值填充</span>' +
        '<input class="attr-fill-input" id="attrFillValue" placeholder="输入默认值，保存时自动填入空单元格" />' +
      '</div>' +
      '<div class="attr-filter-bar" id="attrFilterBar" style="display:none;">' +
        '<select class="attr-filter-field" id="attrFilterField">' +
          attrKeys.map(function(k) { return '<option value="' + escapeHtml(k) + '">' + escapeHtml(k) + '</option>'; }).join('') +
        '</select>' +
        '<select class="attr-filter-op" id="attrFilterOp">' +
          '<option value="eq">=</option><option value="neq">≠</option><option value="gt">&gt;</option>' +
          '<option value="gte">≥</option><option value="lt">&lt;</option><option value="lte">≤</option>' +
          '<option value="contains">包含</option>' +
        '</select>' +
        '<input class="attr-filter-val" id="attrFilterVal" placeholder="值" />' +
        '<button class="attr-btn attr-btn-sm" id="attrFilterApply">筛选</button>' +
        '<button class="attr-btn attr-btn-sm" id="attrFilterClear">清除</button>' +
        '<button class="attr-btn attr-btn-primary attr-btn-sm" id="attrFilterExport">导出为新图层</button>' +
        '<span class="attr-filter-count" id="attrFilterCount"></span>' +
      '</div>' +
      '<div class="inspector-data-wrap"><table class="inspector-data-table" id="attrDataTable"><thead><tr><th>#</th>';
      displayKeys.forEach(function(k) {
        var isVirtual = VIRTUAL_KEYS_ALL.indexOf(k) !== -1;
        var headerLabel = escapeHtml(VIRTUAL_DISPLAY[k] || k);
        if (!isVirtual) {
          dataHtml += '<th><div style="display:flex;align-items:center;justify-content:space-between;gap:4px;"><span>' + headerLabel + '</span><button type="button" class="attr-del-col-btn" data-field="' + escapeHtml(k) + '" title="删除此字段">×</button></div></th>';
        } else {
          dataHtml += '<th>' + headerLabel + '</th>';
        }
      });
      dataHtml += '<th style="width:28px;" title="定位">◎</th><th style="width:32px;"></th></tr></thead><tbody>';
      features.forEach(function(f, i) {
        var props = f.properties || {};
        dataHtml += '<tr data-idx="' + i + '" data-fid="' + escapeHtml(props._fid || '') + '">';
        dataHtml += '<td class="data-idx">' + (i + 1) + '</td>';
        displayKeys.forEach(function(k) {
          var isVirtual = VIRTUAL_KEYS_ALL.indexOf(k) !== -1;
          var cellValue = '';
          if (isVirtual) {
            // 从 geometry 提取坐标/几何信息
            if (k === '_经度') cellValue = (f.geometry && f.geometry.coordinates) ? f.geometry.coordinates[0].toFixed(6) : '';
            else if (k === '_纬度') cellValue = (f.geometry && f.geometry.coordinates) ? f.geometry.coordinates[1].toFixed(6) : '';
            else if (k === '_几何类型') cellValue = f.geometry ? f.geometry.type : 'null';
            else if (k === '_顶点数') cellValue = f.geometry ? _countCoords(f.geometry.coordinates) : 0;
          } else {
            var v = props[k];
            cellValue = (v === null || v === undefined) ? '' : String(v);
          }
          var isPointCoord = isVirtual && (k === '_经度' || k === '_纬度') && (f.geometry && f.geometry.type === 'Point');
          var readonlyAttr = (isVirtual && !isPointCoord) ? ' readonly class="attr-cell attr-cell-readonly"' : ' class="attr-cell"';
          dataHtml += '<td><input' + readonlyAttr + ' data-field="' + escapeHtml(k) + '" value="' + escapeHtml(cellValue) + '" ' + (isPointCoord ? 'placeholder="如 112.9388"' : '') + ' /></td>';
        });
        dataHtml += '<td class="col-locate"><button class="attr-locate-btn" data-idx="' + i + '" title="在地图上定位此要素">◎</button></td>';
        dataHtml += '<td><button class="attr-del-btn" data-idx="' + i + '" title="删除此行">×</button></td>';
        dataHtml += '</tr>';
      });
      dataHtml += '</tbody></table></div>';
    } else if (features.length > 0) {
      dataHtml = '<div class="inspector-section"><div class="inspector-section-title">属性数据</div><span style="color:var(--ui-gray-300);font-size:var(--fs-12);">无属性字段</span></div>';
    }

    // 构建三个标签页
    var bboxLeft = bbox ? bbox[0].toFixed(4) : '—';
    var bboxBottom = bbox ? bbox[1].toFixed(4) : '—';
    var bboxRight = bbox ? bbox[2].toFixed(4) : '—';
    var bboxTop = bbox ? bbox[3].toFixed(4) : '—';
          var scaleRange = (window.GIS.map && window.GIS.map.getLayerScaleRange)
            ? window.GIS.map.getLayerScaleRange(layer._rawName || layer.layer_id)
            : { minZoom: layer.minZoom, maxZoom: layer.maxZoom };
          var curMinZ = (layer.minZoom !== undefined && layer.minZoom !== null) ? layer.minZoom : (scaleRange.minZoom || '');
          var curMaxZ = (layer.maxZoom !== undefined && layer.maxZoom !== null) ? layer.maxZoom : (scaleRange.maxZoom || '');

          var tabInfo =
      '<div class="inspector-tab-content" id="tabInfo" style="display:' + (activeTabId === 'info' ? 'block' : 'none') + ';">' +
        '<div class="info-panel">' +
          '<div class="info-group">' +
            '<div class="info-group-title">数据源</div>' +
            '<div class="info-row"><span class="info-label">名称</span><span class="info-val">' + escapeHtml(layer.filename || '未命名') + '</span></div>' +
            '<div class="info-row"><span class="info-label">来源</span><span class="info-val">' + escapeHtml(layer.source || '未知') + '</span></div>' +
            '<div class="info-row"><span class="info-label">几何类型</span><span class="info-val">' + escapeHtml(remote.geometry_type || local.geometryType) + '</span></div>' +
            '<div class="info-row"><span class="info-label">要素数</span><span class="info-val">' + (remote.feature_count ?? local.featureCount) + '</span></div>' +
          '</div>' +
          '<div class="info-group">' +
            '<div class="info-group-title">坐标系</div>' +
            '<div class="info-row"><span class="info-label">CRS</span><span class="info-val">' + crsBadge + ' ' + escapeHtml(crsStr) + '</span></div>' +
          '</div>' +
          '<div class="info-group">' +
            '<div class="info-group-title">显示与可见缩放范围 (ArcMap 风格)</div>' +
            '<div class="info-row" style="align-items:center;gap:8px;">' +
              '<span class="info-label" style="flex-shrink:0;">透明度</span>' +
              '<input type="range" id="layerOpacity" min="0" max="100" step="5" value="' + Math.round(((layer.opacity !== undefined ? layer.opacity : 1)) * 100) + '" style="flex:1;" />' +
              '<span class="info-val" id="layerOpacityVal">' + Math.round(((layer.opacity !== undefined ? layer.opacity : 1)) * 100) + '%</span>' +
            '</div>' +
            '<div class="info-row" style="align-items:center;gap:8px;padding-top:4px;">' +
              '<span class="info-label" style="flex-shrink:0;" title="小于此缩放级别时图层不显示（例如缩小到全国时隐藏详细点位）">最小缩放 (Out)</span>' +
              '<input type="number" id="layerMinZoom" min="1" max="22" placeholder="不限 (如 4)" value="' + curMinZ + '" style="width:70px;padding:3px 6px;border:1px solid var(--outline-variant);border-radius:4px;font-size:11px;" />' +
              '<button type="button" class="scale-range-cur-btn" id="setMinZoomCurBtn" style="font-size:10px;padding:2px 6px;border:1px solid var(--outline-variant);border-radius:3px;background:var(--surface-container-low);cursor:pointer;" title="使用地图当前缩放级别">当前级别</button>' +
              '<button type="button" class="scale-range-clear-btn" id="clearMinZoomBtn" style="font-size:10px;padding:2px 5px;border:none;background:transparent;color:var(--on-surface-variant);cursor:pointer;" title="清除最小缩放限制"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>' +
            '</div>' +
            '<div class="info-row" style="align-items:center;gap:8px;padding-top:4px;">' +
              '<span class="info-label" style="flex-shrink:0;" title="大于此缩放级别时图层不显示（例如放大到街道时隐藏大范围省界）">最大缩放 (In)</span>' +
              '<input type="number" id="layerMaxZoom" min="1" max="22" placeholder="不限 (如 16)" value="' + curMaxZ + '" style="width:70px;padding:3px 6px;border:1px solid var(--outline-variant);border-radius:4px;font-size:11px;" />' +
              '<button type="button" class="scale-range-cur-btn" id="setMaxZoomCurBtn" style="font-size:10px;padding:2px 6px;border:1px solid var(--outline-variant);border-radius:3px;background:var(--surface-container-low);cursor:pointer;" title="使用地图当前缩放级别">当前级别</button>' +
              '<button type="button" class="scale-range-clear-btn" id="clearMaxZoomBtn" style="font-size:10px;padding:2px 5px;border:none;background:transparent;color:var(--on-surface-variant);cursor:pointer;" title="清除最大缩放限制"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>' +
            '</div>' +
          '</div>' +
          '<div class="info-group">' +
            '<div class="info-group-title">范围</div>' +
            '<div class="info-row"><span class="info-label">左 (Xmin)</span><span class="info-val info-mono">' + bboxLeft + '</span></div>' +
            '<div class="info-row"><span class="info-label">右 (Xmax)</span><span class="info-val info-mono">' + bboxRight + '</span></div>' +
            '<div class="info-row"><span class="info-label">下 (Ymin)</span><span class="info-val info-mono">' + bboxBottom + '</span></div>' +
            '<div class="info-row"><span class="info-label">上 (Ymax)</span><span class="info-val info-mono">' + bboxTop + '</span></div>' +
          '</div>' +
          '<div class="info-group">' +
            '<div class="info-group-title">字段 (' + attrKeys.length + ')</div>' +
            attrHtml +
          '</div>' +
        '</div>' +
      '</div>';

    var tabs =
      '<div class="inspector-tabs">' +
        '<button class="inspector-tab' + (activeTabId === 'info' ? ' active' : '') + '" data-tab="info">基础信息</button>' +
        '<button class="inspector-tab' + (activeTabId === 'symb' ? ' active' : '') + '" data-tab="symb">符号系统</button>' +
        '<button class="inspector-tab' + (activeTabId === 'attr' ? ' active' : '') + '" data-tab="attr">属性表</button>' +
      '</div>';

    var tabAttr =
      '<div class="inspector-tab-content" id="tabAttr" style="display:' + (activeTabId === 'attr' ? 'block' : 'none') + ';">' +
        dataHtml +
      '</div>';

    // ===== 符号系统标签 =====
    var symbFields = Object.keys(attrFields);
    var sConfig = _symbologyConfig[layerId] || {};
    var sEnabled = sConfig.enabled || false;
    var sType = sConfig.type || 'unique';
    var sField = sConfig.field || symbFields[0] || '';
    var sClasses = sConfig.classes || 5;
    var sScheme = sConfig.colorScheme || 'scheme';

    // ===== 3D 拉伸可视化（手动，不依赖 Agent）=====
    var vizNumeric = attrKeys.filter(function(k) { return attrFields[k] === 'number'; });
    var hasPoly = features.some(function(f) { return f.geometry && f.geometry.type.indexOf('Polygon') !== -1; });
    var sViz = (_symbologyConfig[layerId] && _symbologyConfig[layerId].viz) || null;
    var tabViz3d = '';
    if (hasPoly) {
      tabViz3d =
        '<div style="border-top:1px solid var(--ui-gray-200);margin-top:10px;padding-top:10px;">' +
          '<div class="inspector-section-title" style="margin-bottom:6px;">3D 拉伸可视化</div>';
      if (vizNumeric.length) {
        tabViz3d +=
          '<div class="symb-row">' +
            '<label class="symb-label">高度字段</label>' +
            '<select class="symb-input symb-select" id="v3dField">' +
              '<option value="">（无）</option>' +
              vizNumeric.map(function(k) { return '<option value="' + escapeHtml(k) + '"' + (sViz && sViz.field === k ? ' selected' : '') + '>' + escapeHtml(k) + '</option>'; }).join('') +
            '</select>' +
          '</div>' +
          '<div class="symb-row" id="v3dHeightRow" style="' + (sViz ? '' : 'display:none;') + '">' +
            '<label class="symb-label">最大高度(m)</label>' +
            '<input type="number" class="symb-input symb-input-narrow" id="v3dMax" value="' + (sViz ? sViz.maxHeight : 50000) + '" min="50" step="100" />' +
          '</div>' +
          '<div class="symb-actions" style="margin-top:8px;">' +
            '<button class="symb-btn symb-btn-clear" id="v3dClearBtn">清除拉伸</button>' +
            '<div class="symb-actions-right">' +
              '<button class="symb-btn symb-btn-apply" id="v3dApplyBtn">应用到 3D</button>' +
            '</div>' +
          '</div>';
      } else {
        tabViz3d += '<span style="color:var(--ui-gray-300);font-size:var(--fs-12);">无数值字段可拉伸</span>';
      }
      tabViz3d += '</div>';
    }

    var tabSymb =
      '<div class="inspector-tab-content" id="tabSymb" style="display:none;">' +
        '<div class="symb-panel">' +
          '<div class="symb-enable-row">' +
            '<label class="symb-toggle">' +
              '<input type="checkbox" id="symbEnable"' + (sEnabled ? ' checked' : '') + ' />' +
              '<span class="symb-toggle-slider"></span>' +
              '<span class="symb-toggle-label">启用符号化</span>' +
            '</label>' +
          '</div>' +
          '<div class="symb-controls" id="symbControls"' + (sEnabled ? '' : ' style="opacity:0.4;pointer-events:none;"') + '>' +
            '<div class="symb-row">' +
              '<label class="symb-label">渲染方式</label>' +
              '<select class="symb-input symb-select" id="symbType">' +
                '<option value="unique"' + (sType === 'unique' ? ' selected' : '') + '>唯一值 (Unique Values)</option>' +
                '<option value="graduated"' + (sType === 'graduated' ? ' selected' : '') + '>分级色彩 (Graduated Colors)</option>' +
                '<option value="graduated-symbol"' + (sType === 'graduated-symbol' ? ' selected' : '') + '>分级符号 (Graduated Symbols)</option>' +
                '<option value="proportional"' + (sType === 'proportional' ? ' selected' : '') + '>比例符号 (Proportional Symbols)</option>' +
              '</select>' +
            '</div>' +
            '<div class="symb-row">' +
              '<label class="symb-label">字段</label>' +
              '<select class="symb-input symb-select" id="symbField">' +
                symbFields.map(function(k) { return '<option value="' + escapeHtml(k) + '"' + (sField === k ? ' selected' : '') + '>' + escapeHtml(k) + '</option>'; }).join('') +
              '</select>' +
            '</div>' +
            '<div class="symb-row symb-classes-row" id="sClassesRow"' + (sType === 'unique' || sType === 'proportional' ? ' style="display:none;"' : '') + '>' +
              '<label class="symb-label">分级数</label>' +
              '<input type="number" class="symb-input symb-input-narrow" id="sClassesNum" value="' + sClasses + '" min="2" max="20" />' +
            '</div>' +
            '<div class="symb-row symb-size-row" id="sSizeRow"' + (sType !== 'graduated-symbol' && sType !== 'proportional' ? ' style="display:none;"' : '') + '>' +
              '<label class="symb-label">符号大小</label>' +
              '<span class="symb-size-label">最小</span><input type="number" class="symb-input symb-input-narrow" id="sSizeMin" value="' + (sConfig.minSize || 3) + '" min="1" max="50" />' +
              '<span class="symb-size-label">最大</span><input type="number" class="symb-input symb-input-narrow" id="sSizeMax" value="' + (sConfig.maxSize || 20) + '" min="1" max="50" />' +
            '</div>' +
            '<div class="symb-row">' +
              '<label class="symb-label">色带</label>' +
              '<div class="symb-schemes">' +
                '<span class="symb-swatch" data-scheme="scheme" title="默认"><span style="background:#1c1b1b"></span><span style="background:#e74c3c"></span><span style="background:#2ecc71"></span><span style="background:#3498db"></span></span>' +
                '<span class="symb-swatch" data-scheme="blues" title="蓝色系"><span style="background:#c6dbef"></span><span style="background:#6baed6"></span><span style="background:#2171b5"></span><span style="background:#08306b"></span></span>' +
                '<span class="symb-swatch" data-scheme="reds" title="红色系"><span style="background:#fcbba1"></span><span style="background:#fb6a4a"></span><span style="background:#de2d26"></span><span style="background:#a50f15"></span></span>' +
                '<span class="symb-swatch" data-scheme="greens" title="绿色系"><span style="background:#c7e9c0"></span><span style="background:#74c476"></span><span style="background:#238b45"></span><span style="background:#00441b"></span></span>' +
                '<span class="symb-swatch" data-scheme="purples" title="紫色系"><span style="background:#dadaeb"></span><span style="background:#9e9ac8"></span><span style="background:#6a51a3"></span><span style="background:#3f007d"></span></span>' +
                '<span class="symb-swatch" data-scheme="oranges" title="橙色系"><span style="background:#fdd0a2"></span><span style="background:#fd8d3c"></span><span style="background:#d94801"></span><span style="background:#8c2d04"></span></span>' +
              '</div>' +
            '</div>' +
            '<div class="symb-classes-preview" id="sClassesPreview">' +
              '<div class="symb-preview-title">类别预览</div>' +
              '<div class="symb-preview-body" id="sPreviewBody">选择字段后自动预览</div>' +
            '</div>' +
            '<div class="symb-actions">' +
              '<button class="symb-btn symb-btn-clear" id="sClearBtn">清除符号化</button>' +
              '<div class="symb-actions-right">' +
                '<button class="symb-btn symb-btn-apply" id="sApplyBtn" disabled>应用</button>' +
              '</div>' +
            '</div>' +
          '</div>' +
          tabViz3d +
        '</div>' +
      '</div>';

    body.innerHTML = tabs + tabInfo + tabSymb + tabAttr;

    // ===== 标签页切换 =====
    body.querySelectorAll('.inspector-tab').forEach(function(tab) {
      tab.addEventListener('click', function() {
        body.querySelectorAll('.inspector-tab').forEach(function(t) { t.classList.remove('active'); });
        tab.classList.add('active');
        var id = tab.getAttribute('data-tab');
        document.getElementById('tabInfo').style.display = id === 'info' ? 'block' : 'none';
        document.getElementById('tabSymb').style.display = id === 'symb' ? 'block' : 'none';
        document.getElementById('tabAttr').style.display = id === 'attr' ? 'block' : 'none';
      });
    });

    // ===== 属性表事件 =====
    var attrSection = document.getElementById('tabAttr');
    if (attrSection) {
      attrSection.querySelector('[data-action="save-attrs"]')?.addEventListener('click', function() { saveAttrChanges(layerId, attrKeys); });
      attrSection.querySelector('[data-action="add-row"]')?.addEventListener('click', function() { addAttrRow(layerId, attrKeys); });
      attrSection.querySelector('[data-action="add-col"]')?.addEventListener('click', function() { _showAddColumnModal(layerId, attrKeys); });
      attrSection.querySelector('[data-action="calc-field"]')?.addEventListener('click', function() { _showFieldCalculatorModal(layerId, attrKeys); });
      attrSection.querySelector('[data-action="toggle-filter"]')?.addEventListener('click', function() { var bar = document.getElementById('attrFilterBar'); if (bar) bar.style.display = bar.style.display === 'none' ? 'flex' : 'none'; });
      attrSection.querySelector('[data-action="export-csv"]')?.addEventListener('click', function() { exportAttrCSV(layerId); });
      document.getElementById('attrFilterApply')?.addEventListener('click', function() { applyFilter(layerId); });
      document.getElementById('attrFilterClear')?.addEventListener('click', function() { clearFilter(layerId); });
      document.getElementById('attrFilterExport')?.addEventListener('click', function() { exportFilteredLayer(layerId); });
      attrSection.querySelector('.inspector-data-wrap')?.addEventListener('click', function(e) {
        var locateBtn = e.target.closest('.attr-locate-btn');
        if (locateBtn) {
          var idx = parseInt(locateBtn.dataset.idx, 10);
          var layerName = layer._rawName || layer.layer_id;
          if (window.GIS.map && window.GIS.map.highlightLayerFeature) window.GIS.map.highlightLayerFeature(layerName, idx);
          document.querySelectorAll('#attrDataTable tbody tr').forEach(function(tr) { tr.classList.toggle('feat-row-active', parseInt(tr.dataset.idx, 10) === idx); });
          return;
        }
        var delBtn = e.target.closest('.attr-del-btn');
        if (delBtn) {
          deleteAttrRow(layerId, parseInt(delBtn.dataset.idx, 10));
          return;
        }
        var delColBtn = e.target.closest('.attr-del-col-btn');
        if (delColBtn) {
          var colName = delColBtn.dataset.field;
          if (colName) deleteAttrColumn(layerId, colName);
        }
      });
    }

    // ===== 符号系统事件 =====
    _bindSymbEvents(layerId, features);

    // ===== 手动 3D 拉伸事件 =====
    _bindViz3dEvents(layerId);

    // ===== 透明度滑块（2D 直接驱动，3D 经 state 广播，同步图层卡片）=====
    var opSlider = document.getElementById('layerOpacity');
    if (opSlider) {
      opSlider.addEventListener('input', function() {
        var o = parseInt(opSlider.value, 10) / 100;
        var valEl = document.getElementById('layerOpacityVal');
        if (valEl) valEl.textContent = opSlider.value + '%';
        layer.opacity = o;

        // 同步列表左侧对应图层卡片的滑块与数值
        var cardSlider = tbody ? tbody.querySelector('.layer-row-opacity[data-id="' + layerId + '"]') : null;
        if (cardSlider) cardSlider.value = opSlider.value;
        var cardVal = document.getElementById('opval_' + layerId);
        if (cardVal) cardVal.textContent = opSlider.value + '%';

        if (GIS.map && GIS.map.setLayerOpacity) {
          GIS.map.setLayerOpacity(layer._rawName || layer.layer_id, o);
        }
        if (window.GIS.state && typeof window.GIS.state.setOpacity === 'function' &&
            window.GIS.state.getLayer(layerId)) {
          window.GIS.state.setOpacity(layerId, o);
        }
      });
    }

    // ===== 比例尺可见缩放范围（ArcMap 风格：最小与最大缩放级别）=====
    var minZInput = document.getElementById('layerMinZoom');
    var maxZInput = document.getElementById('layerMaxZoom');

    function applyScaleRange() {
      var minVal = (minZInput && minZInput.value !== '') ? parseInt(minZInput.value, 10) : null;
      var maxVal = (maxZInput && maxZInput.value !== '') ? parseInt(maxZInput.value, 10) : null;
      if (minVal !== null && isNaN(minVal)) minVal = null;
      if (maxVal !== null && isNaN(maxVal)) maxVal = null;

      layer.minZoom = minVal;
      layer.maxZoom = maxVal;

      if (window.GIS.map && typeof window.GIS.map.setLayerScaleRange === 'function') {
        window.GIS.map.setLayerScaleRange(layer._rawName || layer.layer_id, minVal, maxVal);
      }
    }

    if (minZInput) {
      minZInput.addEventListener('change', applyScaleRange);
      minZInput.addEventListener('input', applyScaleRange);
    }
    if (maxZInput) {
      maxZInput.addEventListener('change', applyScaleRange);
      maxZInput.addEventListener('input', applyScaleRange);
    }

    document.getElementById('setMinZoomCurBtn')?.addEventListener('click', function() {
      if (!window.GIS.map || !window.GIS.map.getInstance()) return;
      var curZ = window.GIS.map.getInstance().getZoom();
      if (minZInput) minZInput.value = curZ;
      applyScaleRange();
    });
    document.getElementById('clearMinZoomBtn')?.addEventListener('click', function() {
      if (minZInput) minZInput.value = '';
      applyScaleRange();
    });

    document.getElementById('setMaxZoomCurBtn')?.addEventListener('click', function() {
      if (!window.GIS.map || !window.GIS.map.getInstance()) return;
      var curZ = window.GIS.map.getInstance().getZoom();
      if (maxZInput) maxZInput.value = curZ;
      applyScaleRange();
    });
    document.getElementById('clearMaxZoomBtn')?.addEventListener('click', function() {
      if (maxZInput) maxZInput.value = '';
      applyScaleRange();
    });

    // 初始化列宽拖拽
    _enableColumnResize('attrDataTable');

    if (window.GIS.workspace && typeof window.GIS.workspace.preparePanel === 'function') {
      window.GIS.workspace.preparePanel('layerInspector', 'inspectorHeader', 'inspectorClose', '图层检查');
      window.GIS.workspace.expandPanel('layerInspector');
      if (!panel.style.left || panel.style.left === 'auto') {
        window.GIS.workspace.centerPanel('layerInspector');
      }
    }
    panel.style.display = 'flex';
  }

  // ---- 属性表列宽拖拽 ----

  function _enableColumnResize(tableId) {
    var table = document.getElementById(tableId);
    if (!table) return;
    var thead = table.querySelector('thead');
    if (!thead) return;
    var ths = thead.querySelectorAll('th');
    if (ths.length < 2) return;

    ths.forEach(function(th, colIdx) {
      // 跳过序号列和删除列
      if (colIdx === 0) return;
      if (colIdx === ths.length - 1) return;

      var resizer = document.createElement('div');
      resizer.className = 'col-resizer';
      resizer.style.cssText = 'position:absolute;right:0;top:0;bottom:0;width:4px;cursor:col-resize;z-index:1;';
      th.style.position = 'relative';
      th.appendChild(resizer);

      var startX = 0, startWidth = 0;
      resizer.addEventListener('mousedown', function(e) {
        e.preventDefault();
        startX = e.clientX;
        startWidth = th.offsetWidth;
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      });

      function onMove(e) {
        var diff = e.clientX - startX;
        var newWidth = Math.max(30, startWidth + diff);
        // 设置表头宽度
        th.style.width = newWidth + 'px';
        th.style.minWidth = newWidth + 'px';
        // 同步设置该列所有数据格
        table.querySelectorAll('tbody tr').forEach(function(tr) {
          var cell = tr.querySelectorAll('td, th')[colIdx];
          if (cell) {
            cell.style.width = newWidth + 'px';
            cell.style.minWidth = newWidth + 'px';
          }
        });
      }

      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    });
  }

  // ---- 图层符号化 ----

  /** 存储每层的符号化配置 */
  var _symbologyConfig = Object.create(null);

  /** 绑定符号化标签页内的事件 */
  function _bindSymbEvents(layerId, features) {
    var enableEl = document.getElementById('symbEnable');
    var controlsEl = document.getElementById('symbControls');
    var typeEl = document.getElementById('symbType');
    var fieldEl = document.getElementById('symbField');
    var classesEl = document.getElementById('sClassesNum');
    var classesRow = document.getElementById('sClassesRow');
    var sizeRow = document.getElementById('sSizeRow');
    var sizeMinEl = document.getElementById('sSizeMin');
    var sizeMaxEl = document.getElementById('sSizeMax');
    var previewBody = document.getElementById('sPreviewBody');
    var applyBtn = document.getElementById('sApplyBtn');
    var clearBtn = document.getElementById('sClearBtn');

    if (!enableEl || !controlsEl || !typeEl || !fieldEl) return;

    // 启用/禁用切换
    enableEl.addEventListener('change', function() {
      var enabled = enableEl.checked;
      controlsEl.style.opacity = enabled ? '1' : '0.4';
      controlsEl.style.pointerEvents = enabled ? 'auto' : 'none';
      if (!enabled) {
        _clearSymbology(layerId);
      } else {
        if (!_symbologyConfig[layerId]) _symbologyConfig[layerId] = {};
        _symbologyConfig[layerId].enabled = true;
        _updatePreview();
      }
    });

    // 类型切换
    function _onTypeChange() {
      var t = typeEl.value;
      if (classesRow) classesRow.style.display = (t === 'unique' || t === 'proportional') ? 'none' : '';
      if (sizeRow) sizeRow.style.display = (t === 'graduated-symbol' || t === 'proportional') ? '' : 'none';
      _updatePreview();
    }
    typeEl.addEventListener('change', _onTypeChange);
    fieldEl.addEventListener('change', _updatePreview);
    if (classesEl) classesEl.addEventListener('change', _updatePreview);
    if (sizeMinEl) sizeMinEl.addEventListener('change', _updatePreview);
    if (sizeMaxEl) sizeMaxEl.addEventListener('change', _updatePreview);

    // 色带选择
    var swatches = document.querySelectorAll('.symb-swatch');
    swatches.forEach(function(sw) {
      sw.addEventListener('click', function() {
        swatches.forEach(function(s) { s.classList.remove('selected'); });
        sw.classList.add('selected');
        _updatePreview();
      });
    });

    // 预览更新
    function _updatePreview() {
      if (!enableEl.checked) return;
      var type = typeEl.value;
      var field = fieldEl.value;
      var classes = parseInt(classesEl?.value, 10) || 5;
      var scheme = document.querySelector('.symb-swatch.selected')?.dataset?.scheme || 'scheme';
      var minSize = parseInt(sizeMinEl?.value, 10) || 3;
      var maxSize = parseInt(sizeMaxEl?.value, 10) || 20;

      if (!field || !features.length) {
        if (previewBody) previewBody.textContent = '请选择字段';
        if (applyBtn) applyBtn.disabled = true;
        return;
      }

      var values = [];
      features.forEach(function(f) {
        var v = f.properties ? f.properties[field] : undefined;
        if (v !== null && v !== undefined) values.push(v);
      });
      if (!values.length) {
        if (previewBody) previewBody.textContent = '字段无数据';
        if (applyBtn) applyBtn.disabled = true;
        return;
      }

      var uniqueVals = [];
      values.forEach(function(v) { if (uniqueVals.indexOf(v) === -1) uniqueVals.push(v); });
      var schemeColors = _getSchemeColors(scheme, type === 'unique' ? Math.min(uniqueVals.length, 10) : classes);

      var html = '';
      if (type === 'unique') {
        var displayVals = uniqueVals.slice(0, 10);
        displayVals.forEach(function(v, i) {
          var c = schemeColors[i % schemeColors.length];
          html += '<div class="symb-preview-item"><span class="symb-preview-swatch" style="background:' + c + '"></span><span class="symb-preview-val">' + escapeHtml(String(v)) + '</span></div>';
        });
        if (uniqueVals.length > 10) html += '<div class="symb-preview-more">… 还有 ' + (uniqueVals.length - 10) + ' 个值</div>';
      } else {
        var min = Infinity, max = -Infinity;
        values.forEach(function(v) { if (v < min) min = v; if (v > max) max = v; });
        var step = (max - min) / classes;
        for (var i = 0; i < classes; i++) {
          var lo = min + i * step;
          var hi = (i === classes - 1) ? max : min + (i + 1) * step;
          var c = schemeColors[i % schemeColors.length];
          html += '<div class="symb-preview-item"><span class="symb-preview-swatch" style="background:' + c + '"></span><span class="symb-preview-val">' + lo.toFixed(2) + ' — ' + hi.toFixed(2) + '</span></div>';
        }
      }
      if (previewBody) previewBody.innerHTML = html;
      if (applyBtn) applyBtn.disabled = false;
    }

    // 清除符号化
    clearBtn?.addEventListener('click', function() {
      _clearSymbology(layerId);
      if (enableEl) enableEl.checked = false;
      controlsEl.style.opacity = '0.4';
      controlsEl.style.pointerEvents = 'none';
      if (previewBody) previewBody.textContent = '符号化已清除';
      if (applyBtn) applyBtn.disabled = true;
    });

    // 应用
    applyBtn?.addEventListener('click', function() {
      var type = typeEl.value;
      var field = fieldEl.value;
      var classes = parseInt(classesEl?.value, 10) || 5;
      var scheme = document.querySelector('.symb-swatch.selected')?.dataset?.scheme || 'scheme';
      var minSize = parseInt(sizeMinEl?.value, 10) || 3;
      var maxSize = parseInt(sizeMaxEl?.value, 10) || 20;
      _applySymbology(layerId, type, field, classes, scheme, minSize, maxSize);
      // 符号化应用时同步 3D 拉伸（若已选高度字段）
      _applyViz3dFromUI(layerId);
    });

    // 初始预览
    if (enableEl.checked) _updatePreview();
  }

  /** 绑定 3D 拉伸可视化控件（手动路径，无需 Agent） */
  function _bindViz3dEvents(layerId) {
    var fieldEl = document.getElementById('v3dField');
    if (!fieldEl) return;
    var heightRow = document.getElementById('v3dHeightRow');
    var applyBtn = document.getElementById('v3dApplyBtn');
    var clearBtn = document.getElementById('v3dClearBtn');

    fieldEl.addEventListener('change', function() {
      if (heightRow) heightRow.style.display = fieldEl.value ? '' : 'none';
    });
    applyBtn?.addEventListener('click', function() { _applyViz3dFromUI(layerId); });
    clearBtn?.addEventListener('click', function() {
      fieldEl.value = '';
      if (heightRow) heightRow.style.display = 'none';
      if (_symbologyConfig[layerId]) delete _symbologyConfig[layerId].viz;
      if (window.GIS.state && window.GIS.state.getLayer(layerId)) {
        window.GIS.state.applyVisualization(layerId, null);
      }
    });
  }

  /** 从检查器 UI 读取 3D 拉伸参数并经共享状态应用（2D/3D 都能收到） */
  function _applyViz3dFromUI(layerId) {
    var fieldEl = document.getElementById('v3dField');
    if (!fieldEl) return;
    var field = fieldEl.value;
    var state = window.GIS.state;
    if (!state || typeof state.applyVisualization !== 'function' || !state.getLayer(layerId)) {
      if (field && window.GIS.chat && window.GIS.chat.addMessage) {
        window.GIS.chat.addMessage('该图层不在共享状态中，无法应用 3D 拉伸', 'system');
      }
      return;
    }
    if (!field) {
      state.applyVisualization(layerId, null);
      if (_symbologyConfig[layerId]) delete _symbologyConfig[layerId].viz;
      return;
    }
    var maxEl = document.getElementById('v3dMax');
    var maxH = parseInt(maxEl && maxEl.value, 10) || 50000;
    // 拉伸色带独立于 2D 符号化：选了顺序色带就用它，否则默认蓝色系
    var schemeName = document.querySelector('.symb-swatch.selected')?.dataset?.scheme || 'blues';
    if (schemeName === 'scheme') schemeName = 'blues';
    var ramp = _getSchemeColors(schemeName, 9);
    var viz = { type: 'extrusion', field: field, ramp: [ramp[0], ramp[ramp.length - 1]], maxHeight: maxH };
    state.applyVisualization(layerId, viz);
    if (!_symbologyConfig[layerId]) _symbologyConfig[layerId] = {};
    _symbologyConfig[layerId].viz = viz;
  }

  /** 唯一值渲染 */

  /** 应用符号化 */
  function _applySymbology(layerId, type, field, classes, colorScheme, minSize, maxSize) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;
    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;

    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];
    if (!features.length) return;

    var scheme = _getColorScheme(colorScheme, classes);

    var previousConfig = _symbologyConfig[layerId];
    _symbologyConfig[layerId] = { type: type, field: field, classes: classes, colorScheme: colorScheme, enabled: true, minSize: minSize || 3, maxSize: maxSize || 20 };
    var restorePreviousConfig = function() {
      if (previousConfig) _symbologyConfig[layerId] = previousConfig;
      else delete _symbologyConfig[layerId];
    };

    if (type === 'unique') {
      if (!_applyUniqueValues(layer, gj, features, field, scheme)) {
        restorePreviousConfig();
      }
    } else if (type === 'graduated') {
      if (!_applyGraduatedColors(layer, gj, features, field, classes, scheme)) {
        restorePreviousConfig();
      }
    } else if (type === 'graduated-symbol') {
      if (!_applyGraduatedSymbols(layer, gj, features, field, classes, scheme, minSize, maxSize)) {
        restorePreviousConfig();
      }
    } else if (type === 'proportional') {
      if (!_applyProportionalSymbols(layer, gj, features, field, minSize, maxSize)) {
        restorePreviousConfig();
      }
    }
  }

  /** 获取色带颜色数组 */
  function _getColorScheme(name, count) {
    name = (name || '').toLowerCase().trim();
    if (name === 'ylorrd' || name === 'yellow_orange_red' || name === 'warm' || name === '黄橙红' || name === '黄到橙到红' || name === '暖色' || name.indexOf('黄') >= 0) {
      name = 'ylorrd';
    } else if (name === 'ylgnbu' || name === '黄绿蓝') {
      name = 'ylgnbu';
    } else if (name === 'spectral' || name === '彩虹' || name === '光谱') {
      name = 'spectral';
    } else if (name === 'viridis' || name === '翠绿') {
      name = 'viridis';
    } else if (name === 'blue' || name === '蓝' || name === '蓝色') {
      name = 'blues';
    } else if (name === 'red' || name === '红' || name === '红色') {
      name = 'reds';
    } else if (name === 'green' || name === '绿' || name === '绿色') {
      name = 'greens';
    } else if (name === 'orange' || name === '橙' || name === '橙色') {
      name = 'oranges';
    } else if (name === 'purple' || name === '紫' || name === '紫色') {
      name = 'purples';
    }

    var palettes = {
      scheme: ['#1c1b1b','#e74c3c','#2ecc71','#3498db','#f39c12','#9b59b6','#1abc9c','#e67e22','#34495e','#16a085',
               '#c0392b','#27ae60','#2980b9','#8e44ad','#2c3e50','#d35400','#7f8c8d','#f1c40f','#00bcd4','#ff5722'],
      blues:   ['#f7fbff','#deebf7','#c6dbef','#9ecae1','#6baed6','#4292c6','#2171b5','#08519c','#08306b'],
      reds:    ['#fff5f0','#fee0d2','#fcbba1','#fc9272','#fb6a4a','#ef3b2c','#cb181d','#a50f15','#67000d'],
      greens:  ['#f7fcf5','#e5f5e0','#c7e9c0','#a1d99b','#74c476','#41ab5d','#238b45','#006d2c','#00441b'],
      purples: ['#fcfbfd','#efedf5','#dadaeb','#bcbddc','#9e9ac8','#807dba','#6a51a3','#54278f','#3f007d'],
      oranges: ['#fff5eb','#fee6ce','#fdd0a2','#fdae6b','#fd8d3c','#f16913','#d94801','#a63603','#7f2704'],
      ylorrd:  ['#ffffcc','#ffeda0','#fed976','#feb24c','#fd8d3c','#fc4e2a','#e31a1c','#bd0026','#800026'],
      ylgnbu:  ['#ffffd9','#edf8b1','#c7e9b4','#7fcdbb','#41b6c4','#1d91c0','#225ea8','#253494','#081d58'],
      viridis: ['#440154','#482777','#3f4a8a','#31688e','#26828e','#1f9e89','#35b779','#6ece58','#b5de2b','#fde725'],
      spectral:['#9e0142','#d53e4f','#f46d43','#fdae61','#fee08b','#ffffbf','#e6f598','#abdda4','#66c2a5','#3288bd','#5e4fa2'],
    };
    var colors = palettes[name] || palettes.scheme;
    if (!count || count <= 1) return [colors[colors.length - 1]];
    if (count === colors.length) return colors.slice();
    // 均匀跨度采样：确保第 1 阶取到最浅色，第 K 阶取到最深色，呈现最佳渐变对比度
    var result = [];
    for (var i = 0; i < count; i++) {
      var idx = Math.round(i * (colors.length - 1) / (count - 1));
      result.push(colors[idx]);
    }
    return result;
  }

  /** 按几何类型返回适当样式 */
  function _styleForGeom(feature, color, fillColor, extra) {
    var geomType = feature && feature.geometry ? feature.geometry.type : '';
    var isPoint = geomType === 'Point' || geomType === 'MultiPoint';
    var isLine = geomType === 'LineString' || geomType === 'MultiLineString';
    var s = { color: color, fillColor: fillColor || color };
    if (isPoint) {
      s.weight = 0; s.fillOpacity = 1;
    } else if (isLine) {
      s.weight = 2.5; s.fillOpacity = 0;
    } else {
      s.weight = 1; s.fillOpacity = 0.35;
    }
    if (extra) Object.assign(s, extra);
    return s;
  }

  function _numericFieldValue(feature, field) {
    if (!feature || !feature.properties) return NaN;
    var raw = feature.properties[field];
    if (typeof raw !== 'number' && typeof raw !== 'string') return NaN;
    if (typeof raw === 'string' && !raw.trim()) return NaN;
    var value = Number(raw);
    return Number.isFinite(value) ? value : NaN;
  }

  /** 获取色带颜色数组（别名，供预览用） */
  function _getSchemeColors(name, count) {
    return _getColorScheme(name, count);
  }

  /** 唯一值渲染 */
  function _applyUniqueValues(layer, gj, features, field, scheme) {
    var values = Object.create(null);
    features.forEach(function(f, idx) {
      var v = String(f.properties ? f.properties[field] ?? '' : '');
      if (!values[v]) values[v] = [];
      values[v].push(idx);
    });
    var keys = Object.keys(values);
    var colorMap = Object.create(null);
    keys.forEach(function(k, i) { colorMap[k] = scheme[i % scheme.length]; });

    var styleMap = {};
    features.forEach(function(f, idx) {
      var v = String(f.properties ? f.properties[field] ?? '' : '');
      styleMap[idx] = _styleForGeom(f, colorMap[v]);
    });

    if (!_applyStyleToMap(layer, gj, styleMap)) return false;
    _push3dFeatureColors(layer, features, styleMap);
    var defaultColor = scheme[keys.length % scheme.length] || '#1c1b1b';

    // 存储图例数据
    if (!_symbologyConfig[layer.layer_id]) _symbologyConfig[layer.layer_id] = {};
    _symbologyConfig[layer.layer_id].legendData = {
      type: 'unique',
      field: field,
      items: keys.map(function(k) { return { label: k, color: colorMap[k], count: values[k].length }; }),
    };
    _symbologyConfig[layer.layer_id].type = 'unique';
    _symbologyConfig[layer.layer_id].field = field;
    _symbologyConfig[layer.layer_id].enabled = true;

    // 符号化信息由 _showLegend 生成可视化图例卡片展示，无需向聊天区倾倒未格式化的十六进制色码
    return true;
  }

  /** 分级色彩渲染 */
  function _applyGraduatedColors(layer, gj, features, field, classes, scheme, method, suppliedBreaks, fillOpacity) {
    var noDataColor = '#9ca3af';
    var values = features.map(function(f, idx) {
      return { idx: idx, val: _numericFieldValue(f, field) };
    }).filter(function(v) { return !isNaN(v.val); });
    if (!values.length) {
      if (window.GIS.chat) window.GIS.chat.addMessage('字段「' + field + '」无有效数值', 'system');
      return false;
    }

    var sorted = values.map(function(v) { return v.val; }).sort(function(a, b) { return a - b; });
    var min = sorted[0], max = sorted[sorted.length - 1];
    var noDataCount = features.length - values.length;
    if (min === max) {
      // 所有值相同，用单一颜色
      var styleMap = {};
      features.forEach(function(f, idx) {
        styleMap[idx] = _styleForGeom(f, isNaN(_numericFieldValue(f, field)) ? noDataColor : scheme[0]);
      });
      if (!_applyStyleToMap(layer, gj, styleMap)) return false;
      _push3dFeatureColors(layer, features, styleMap);
      if (!_symbologyConfig[layer.layer_id]) _symbologyConfig[layer.layer_id] = {};
      _symbologyConfig[layer.layer_id].type = 'graduated';
      _symbologyConfig[layer.layer_id].field = field;
      _symbologyConfig[layer.layer_id].classes = 1;
      _symbologyConfig[layer.layer_id].method = method === 'quantile' ? 'quantile' : 'equal_interval';
      _symbologyConfig[layer.layer_id].breaks = [min, max];
      _symbologyConfig[layer.layer_id].fillOpacity = isFinite(Number(fillOpacity)) ? Math.max(0, Math.min(1, Number(fillOpacity))) : 0.35;
      _symbologyConfig[layer.layer_id].legendData = {
        type: 'graduated', field: field, method: _symbologyConfig[layer.layer_id].method,
        items: [{ label: min.toFixed(2) + ' - ' + max.toFixed(2), color: scheme[0] }].concat(
          noDataCount ? [{ label: '无数据', color: noDataColor, count: noDataCount }] : []),
      };
      return true;
    }

    method = method === 'quantile' ? 'quantile' : 'equal_interval';
    var breaks = Array.isArray(suppliedBreaks) ? suppliedBreaks.map(Number) : [];
    if (breaks.length < 3 || breaks.some(function(v, i) { return !isFinite(v) || (i > 0 && v <= breaks[i - 1]); })) {
      breaks = [];
      if (method === 'quantile') {
        for (var q = 0; q <= classes; q++) {
          var pos = (sorted.length - 1) * q / classes;
          var lower = Math.floor(pos), upper = Math.ceil(pos);
          breaks.push(sorted[lower] + (sorted[upper] - sorted[lower]) * (pos - lower));
        }
        breaks = breaks.filter(function(v, i) { return i === 0 || v > breaks[i - 1]; });
      } else {
        var step = (max - min) / classes;
        for (var i = 0; i <= classes; i++) breaks.push(min + step * i);
      }
    }
    classes = breaks.length - 1;
    fillOpacity = isFinite(Number(fillOpacity)) ? Math.max(0, Math.min(1, Number(fillOpacity))) : 0.35;

    var styleMap = {};
    features.forEach(function(f, idx) {
      var v = _numericFieldValue(f, field);
      if (isNaN(v)) {
        var noDataStyle = _styleForGeom(f, noDataColor);
        if (f.geometry && /Polygon/.test(f.geometry.type || '')) noDataStyle.fillOpacity = fillOpacity;
        styleMap[idx] = noDataStyle;
        return;
      }
      var classIdx = 0;
      for (var j = 0; j < breaks.length - 1; j++) {
        if (v >= breaks[j] && (v < breaks[j + 1] || (j === breaks.length - 2 && v <= breaks[j + 1]))) {
          classIdx = j; break;
        }
      }
      var color = scheme[Math.min(classIdx, scheme.length - 1)];
      var featureStyle = _styleForGeom(f, color);
      if (f.geometry && /Polygon/.test(f.geometry.type || '')) featureStyle.fillOpacity = fillOpacity;
      styleMap[idx] = featureStyle;
    });

    if (!_applyStyleToMap(layer, gj, styleMap)) return false;
    _push3dFeatureColors(layer, features, styleMap);

    // 存储图例数据
    if (!_symbologyConfig[layer.layer_id]) _symbologyConfig[layer.layer_id] = {};
    _symbologyConfig[layer.layer_id].legendData = {
      type: 'graduated',
      field: field,
      method: method,
      items: (function() {
        var arr = [];
        for (var j = 0; j < classes; j++) {
          arr.push({ label: breaks[j].toFixed(2) + ' - ' + breaks[j + 1].toFixed(2), color: scheme[Math.min(j, scheme.length - 1)] });
        }
        if (noDataCount) arr.push({ label: '无数据', color: noDataColor, count: noDataCount });
        return arr;
      })(),
    };
    _symbologyConfig[layer.layer_id].type = 'graduated';
    _symbologyConfig[layer.layer_id].field = field;
    _symbologyConfig[layer.layer_id].classes = classes;
    _symbologyConfig[layer.layer_id].method = method;
    _symbologyConfig[layer.layer_id].breaks = breaks.slice();
    _symbologyConfig[layer.layer_id].fillOpacity = fillOpacity;
    // 符号化信息由 _showLegend 生成可视化图例卡片展示，无需向聊天区倾倒未格式化的十六进制色码
    return true;
  }

  /** 分级符号渲染（点图层用不同半径，线图层用不同粗细） */
  function _applyGraduatedSymbols(layer, gj, features, field, classes, scheme, minSize, maxSize) {
    var isPoint = _isPointLayer(features);
    var noDataColor = '#9ca3af';
    var values = features.map(function(f, idx) {
      return { idx: idx, val: _numericFieldValue(f, field) };
    }).filter(function(v) { return Number.isFinite(v.val); });
    if (!values.length) {
      if (window.GIS.chat) window.GIS.chat.addMessage('字段「' + field + '」无有效数值', 'system');
      return false;
    }

    var sorted = values.map(function(v) { return v.val; }).sort(function(a, b) { return a - b; });
    var min = sorted[0], max = sorted[sorted.length - 1];
    var effectiveClasses = min === max ? 1 : Math.max(1, Math.floor(Number(classes) || 1));
    var step = (max - min) / effectiveClasses;
    var breaks = [];
    for (var i = 0; i <= effectiveClasses; i++) breaks.push(min + step * i);

    if (minSize === undefined) minSize = isPoint ? 3 : 1;
    if (maxSize === undefined) maxSize = isPoint ? 12 : 5;

    var styleMap = {};
    features.forEach(function(f, idx) {
      var v = _numericFieldValue(f, field);
      if (!Number.isFinite(v)) {
        if (isPoint) styleMap[idx] = { radius: minSize, color: noDataColor, weight: 1, fillOpacity: 1 };
        else styleMap[idx] = _styleForGeom(f, noDataColor, null, { weight: Math.round(minSize) });
        return;
      }
      var classIdx = 0;
      for (var j = 0; j < breaks.length - 1; j++) {
        if (v >= breaks[j] && (v < breaks[j + 1] || (j === breaks.length - 2 && v <= breaks[j + 1]))) {
          classIdx = j; break;
        }
      }
      var ratio = effectiveClasses > 1 ? classIdx / (effectiveClasses - 1) : 0;
      var size = minSize + ratio * (maxSize - minSize);
      var color = scheme[Math.min(classIdx, scheme.length - 1)];
      if (isPoint) {
        styleMap[idx] = { radius: Math.round(size), color: color, weight: 0, fillOpacity: 1 };
      } else {
        styleMap[idx] = _styleForGeom(f, color, null, { weight: Math.round(size) });
      }
    });

    if (!_applyStyleToMap(layer, gj, styleMap)) return false;
    _push3dFeatureColors(layer, features, styleMap);

    var symbolLegendItems = [];
    for (var legendIndex = 0; legendIndex < effectiveClasses; legendIndex++) {
      var legendRatio = effectiveClasses > 1 ? legendIndex / (effectiveClasses - 1) : 0;
      var legendSize = Math.round(minSize + legendRatio * (maxSize - minSize));
      var classCount = values.filter(function(item) {
        return item.val >= breaks[legendIndex] &&
          (item.val < breaks[legendIndex + 1] || (legendIndex === effectiveClasses - 1 && item.val <= breaks[legendIndex + 1]));
      }).length;
      symbolLegendItems.push({
        label: breaks[legendIndex].toFixed(2) + ' - ' + breaks[legendIndex + 1].toFixed(2) +
          ' · ' + (isPoint ? '半径 ' : '线宽 ') + legendSize + 'px',
        color: scheme[Math.min(legendIndex, scheme.length - 1)],
        size: legendSize,
        count: classCount,
      });
    }
    var missingCount = features.length - values.length;
    if (missingCount) {
      symbolLegendItems.push({
        label: '无数据 · ' + (isPoint ? '半径 ' : '线宽 ') + Math.round(minSize) + 'px',
        color: noDataColor, size: Math.round(minSize), count: missingCount,
      });
    }
    _symbologyConfig[layer.layer_id].legendData = {
      type: 'graduated-symbol', field: field, method: 'equal_interval', items: symbolLegendItems,
    };

    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      var info = '已应用分级符号: ' + field + '（' + effectiveClasses + ' 级，大小 ' + minSize + '-' + maxSize + '）';
      window.GIS.chat.addMessage(info, 'system');
    }
    return true;
  }

  /** 比例符号渲染（点半径与数值成比例） */
  function _applyProportionalSymbols(layer, gj, features, field, minSize, maxSize) {
    if (!_isPointLayer(features)) {
      if (window.GIS.chat) window.GIS.chat.addMessage('比例符号仅支持点图层', 'system');
      return false;
    }
    var values = features.map(function(f, idx) {
      return { idx: idx, val: _numericFieldValue(f, field) };
    }).filter(function(v) { return Number.isFinite(v.val) && v.val > 0; });
    if (!values.length) {
      if (window.GIS.chat) window.GIS.chat.addMessage('字段「' + field + '」无有效正值', 'system');
      return false;
    }

    var sorted = values.map(function(v) { return v.val; }).sort(function(a, b) { return a - b; });
    var min = sorted[0], max = sorted[sorted.length - 1];
    var styleMap = {};
    var minR = minSize || 3, maxR = maxSize || 20;
    features.forEach(function(f, idx) {
      var v = _numericFieldValue(f, field);
      if (!Number.isFinite(v) || v <= 0) {
        styleMap[idx] = { radius: minR, color: '#9ca3af', weight: 1, fillOpacity: 1 };
        return;
      }
      var ratio = max === min ? 0 : (v - min) / (max - min);
      var r = minR + ratio * (maxR - minR);
      styleMap[idx] = _styleForGeom(f, '#1c1b1b', null, { radius: Math.round(r) });
    });

    if (!_applyStyleToMap(layer, gj, styleMap)) return false;
    _push3dFeatureColors(layer, features, styleMap);

    var proportionalLegendItems = [{
      label: min.toFixed(2) + ' · 半径 ' + Math.round(minR) + 'px',
      color: '#1c1b1b', size: Math.round(minR),
    }];
    if (max !== min) {
      proportionalLegendItems.push({
        label: max.toFixed(2) + ' · 半径 ' + Math.round(maxR) + 'px',
        color: '#1c1b1b', size: Math.round(maxR),
      });
    }
    var invalidCount = features.length - values.length;
    if (invalidCount) {
      proportionalLegendItems.push({
        label: '无数据 · 半径 ' + Math.round(minR) + 'px',
        color: '#9ca3af', size: Math.round(minR), count: invalidCount,
      });
    }
    _symbologyConfig[layer.layer_id].legendData = {
      type: 'proportional', field: field, items: proportionalLegendItems,
    };

    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('已应用比例符号: ' + field + '（大小 ' + minR + '-' + maxR + 'px）', 'system');
    }
    return true;
  }

  /** 将样式映射应用到地图图层 */
  function _applyStyleToMap(layer, gj, styleMap) {
    var name = layer._rawName || layer.layer_id;
    if (!GIS.map || !GIS.map.applySymbology) return false;
    var config = _symbologyConfig[layer.layer_id] || (_symbologyConfig[layer.layer_id] = {});
    var features = gj && gj.type === 'FeatureCollection' ? (gj.features || [])
      : gj && gj.type === 'Feature' ? [gj] : [];
    var stylesByFid = Object.create(null);
    var fidCounts = Object.create(null);
    features.forEach(function(feature) {
      var fid = feature && feature.properties && feature.properties._fid;
      if (fid !== undefined && fid !== null && fid !== '') {
        var stableKey = 'fid:' + String(fid);
        fidCounts[stableKey] = (fidCounts[stableKey] || 0) + 1;
      }
    });
    features.forEach(function(feature, index) {
      var fid = feature && feature.properties && feature.properties._fid;
      var stableKey = fid !== undefined && fid !== null && fid !== '' ? 'fid:' + String(fid) : null;
      var key = stableKey && fidCounts[stableKey] === 1 ? stableKey : 'index:' + index;
      if (styleMap && styleMap[index]) stylesByFid[key] = Object.assign({}, styleMap[index]);
    });
    config.featureStyles = stylesByFid;
    config.featureCount = features.length;
    config.featureStyleCount = Object.keys(stylesByFid).length;
    config.enabled = true;
    GIS.map.applySymbology(name, gj, styleMap);
    return true;
  }

  function _cloneSerializable(value) {
    if (value === undefined) return undefined;
    try { return JSON.parse(JSON.stringify(value)); } catch (_) { return null; }
  }

  function _getSymbologyState(layerId) {
    var config = _symbologyConfig[layerId];
    if (!config || !config.enabled || config.featureStyleCount !== config.featureCount) return null;
    var state = _cloneSerializable(config);
    if (_lastLegendData && _lastLegendData.layerId === layerId) {
      var panel = document.getElementById('mapFloatingLegend');
      var pill = document.getElementById('mapLegendTogglePill');
      state.legendPresentation = panel && panel.style.display !== 'none' ? 'open'
        : pill && pill.style.display !== 'none' ? 'collapsed' : 'open';
    } else {
      state.legendPresentation = 'hidden';
    }
    return state;
  }

  function _getLegendData(layerId) {
    var config = _symbologyConfig[layerId];
    return config && config.enabled && config.legendData ? _cloneSerializable(config.legendData) : null;
  }

  function _restoreSymbologyState(layerId, snapshot) {
    if (!snapshot || typeof snapshot !== 'object' || !snapshot.enabled || !snapshot.featureStyles ||
        snapshot.featureStyleCount !== snapshot.featureCount) return false;
    var layer = layerData.find(function(item) { return item.layer_id === layerId; });
    var gj = layer && getLayerGeoJSON(layerId);
    if (!layer || !gj) return false;
    var features = gj.type === 'FeatureCollection' ? (gj.features || [])
      : gj.type === 'Feature' ? [gj] : [];
    if (!features.length || snapshot.featureCount !== features.length) return false;
    var fidCounts = Object.create(null);
    features.forEach(function(feature) {
      var fid = feature && feature.properties && feature.properties._fid;
      if (fid !== undefined && fid !== null && fid !== '') {
        var stableKey = 'fid:' + String(fid);
        fidCounts[stableKey] = (fidCounts[stableKey] || 0) + 1;
      }
    });
    var styleMap = {};
    var colorsByFid = Object.create(null);
    for (var i = 0; i < features.length; i++) {
      var fid = features[i] && features[i].properties && features[i].properties._fid;
      var stableKey = fid !== undefined && fid !== null && fid !== '' ? 'fid:' + String(fid) : null;
      var key = stableKey && fidCounts[stableKey] === 1 ? stableKey : 'index:' + i;
      var savedStyle = snapshot.featureStyles[key];
      if (!savedStyle) return false;
      styleMap[i] = Object.assign({}, savedStyle);
      if (stableKey && fidCounts[stableKey] === 1 && savedStyle.color) colorsByFid[fid] = savedStyle.color;
    }

    var previousConfig = _symbologyConfig[layerId];
    _symbologyConfig[layerId] = _cloneSerializable(snapshot);
    _symbologyConfig[layerId].enabled = true;
    try {
      if (!_applyStyleToMap(layer, gj, styleMap)) throw new Error('地图渲染器不可用');
    } catch (_) {
      if (previousConfig) _symbologyConfig[layerId] = previousConfig;
      else delete _symbologyConfig[layerId];
      return false;
    }
    if (window.GIS.state) {
      if (typeof window.GIS.state.setFeatureColors === 'function') {
        window.GIS.state.setFeatureColors(layerId, Object.keys(colorsByFid).length ? colorsByFid : null);
      }
      if (typeof window.GIS.state.applyVisualization === 'function') {
        window.GIS.state.applyVisualization(layerId, snapshot.viz || null);
      }
    }
    if (snapshot.legendData && snapshot.legendPresentation !== 'hidden') {
      _renderFloatingLegend(layer._rawName || layer.filename || layer.layer_id, snapshot.legendData, layerId);
      if (snapshot.legendPresentation === 'collapsed') {
        var panel = document.getElementById('mapFloatingLegend');
        var pill = document.getElementById('mapLegendTogglePill');
        if (panel) panel.style.display = 'none';
        if (pill) pill.style.display = 'inline-flex';
      }
    }
    return true;
  }

  /** 把符号化颜色结果按 _fid 推给共享状态（3D 渲染器按 fid 设色） */
  function _push3dFeatureColors(layer, features, styleMap) {
    if (!window.GIS.state || typeof window.GIS.state.setFeatureColors !== 'function') return;
    var colorByFid = {};
    var has = false;
    features.forEach(function(f, idx) {
      var st = styleMap[idx];
      if (!st || !st.color) return;
      var fid = f.properties && f.properties._fid;
      if (fid === undefined || fid === null) return;
      colorByFid[fid] = st.color;
      has = true;
    });
    if (has) window.GIS.state.setFeatureColors(layer.layer_id, colorByFid);
  }

  /** 清除符号化，恢复默认样式 */
  function _clearSymbology(layerId) {
    delete _symbologyConfig[layerId];
    // 清除当前图例的来源样式时，同时移除图例浮层和折叠按钮，避免显示过期分级。
    if (_lastLegendData && _lastLegendData.layerId === layerId) {
      _hideFloatingLegend();
    }
    // 同时清除 3D 拉伸与符号化颜色（同属该图层的可视化配置）
    if (window.GIS.state && typeof window.GIS.state.getLayer === 'function' &&
        window.GIS.state.getLayer(layerId)) {
      window.GIS.state.applyVisualization(layerId, null);
      window.GIS.state.setFeatureColors(layerId, null);
    }
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;
    var name = layer._rawName || layer.layer_id;
    var gj = getLayerGeoJSON(layerId);
    if (gj && GIS.map && GIS.map.loadGeoJSON) {
      GIS.map.loadGeoJSON(gj, name, { color: layer.color || '#1c1b1b' });
    }
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('已清除符号化，恢复默认样式', 'system');
    }
  }

  // ---- 属性表编辑函数 ----

  function getLayerGeoJSON(layerId) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return null;
    var gj = layer.geojson;
    if (!gj && GIS.map && GIS.map.getGeoJSON) {
      gj = GIS.map.getGeoJSON(layer._rawName || layer.layer_id);
    }
    return gj;
  }

  function _coerceAttributeValue(original, rawValue) {
    if (typeof original === 'number') {
      if (rawValue === '') return null;
      var numeric = Number(rawValue);
      return Number.isFinite(numeric) ? numeric : rawValue;
    }
    if (typeof original === 'boolean') {
      if (rawValue === '') return null;
      if (rawValue === true || rawValue === 'true') return true;
      if (rawValue === false || rawValue === 'false') return false;
    }
    return rawValue;
  }

  function _attributeTypeSample(features, field) {
    for (var index = 0; index < features.length; index++) {
      var value = features[index] && features[index].properties ? features[index].properties[field] : undefined;
      if (value !== undefined && value !== null) return value;
    }
    return undefined;
  }

  /** 保存属性修改：读取 input → 检查空行 → 更新 GeoJSON → 刷新地图 */
  function saveAttrChanges(layerId, attrKeys) {
    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;
    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];

    var table = document.getElementById('attrDataTable');
    if (!table) return;

    var fillVal = (document.getElementById('attrFillValue')?.value || '').trim();

    var rows = table.querySelectorAll('tbody tr');
    var emptyRowNums = [];

    rows.forEach(function(row) {
      var hasStableFid = !!row.dataset.fid;
      var idx = hasStableFid ? features.findIndex(function(feature) {
        return feature && feature.properties && String(feature.properties._fid) === row.dataset.fid;
      }) : -1;
      if (!hasStableFid) idx = parseInt(row.dataset.idx, 10); // Legacy rows without a stable ID.
      if (isNaN(idx) || idx >= features.length) return;
      var inputs = row.querySelectorAll('.attr-cell');
      var allEmpty = true;
      var newLng = null, newLat = null;
      inputs.forEach(function(inp) {
        var field = inp.dataset.field;
        var val = inp.value.trim();
        if (field === '_fid') return; // Identity is managed by the layer registry, never by table edits.
        if (field === '_经度') {
          var numLng = parseFloat(val);
          if (!isNaN(numLng)) newLng = numLng;
          return;
        }
        if (field === '_纬度') {
          var numLat = parseFloat(val);
          if (!isNaN(numLat)) newLat = numLat;
          return;
        }
        if (inp.readOnly) return; // 跳过只读几何列
        if (fillVal && val === '') val = fillVal;
        var properties = features[idx].properties || (features[idx].properties = {});
        var typeSample = properties[field];
        if (typeSample === undefined || typeSample === null) typeSample = _attributeTypeSample(features, field);
        properties[field] = _coerceAttributeValue(typeSample, val);
        if (val !== '') allEmpty = false;
      });
      // 更新单点几何坐标
      if (newLng !== null && newLat !== null) {
        if (!features[idx].geometry) {
          features[idx].geometry = { type: 'Point', coordinates: [newLng, newLat] };
        } else if (features[idx].geometry.type === 'Point') {
          features[idx].geometry.coordinates = [newLng, newLat];
        }
        allEmpty = false;
      }
      if (allEmpty) emptyRowNums.push(idx + 1);
    });

    // 弹窗警告空行
    if (emptyRowNums.length > 0) {
      showConfirm('空行警告',
        '第 ' + emptyRowNums.join(', ') + ' 行为完全空行（无任何数据），建议删除或填写数据。是否继续保存？',
        function() { doSave(); }
      );
    } else {
      doSave();
    }

    function doSave() {
      var layer = layerData.find(function(l) { return l.layer_id === layerId; });
      if (layer && GIS.map && GIS.map.loadGeoJSON) {
        GIS.map.loadGeoJSON(gj, layer._rawName || layer.layer_id, { color: layer.color });
        _syncLayerOrder();
      }
      _syncEditedLayerData(layerId, gj);
      if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
        window.GIS.toast.success('属性表修改已保存');
      }
      showLayerInspector(layerId, 'attr');
    }
  }

  /** 添加空行 */
  function addAttrRow(layerId, attrKeys) {
    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;
    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];

    var fillVal = (document.getElementById('attrFillValue')?.value || '').trim();
    var props = {};
    attrKeys.filter(function(key) { return key !== '_fid'; }).forEach(function(key) {
      var sample = _attributeTypeSample(features, key);
      props[key] = fillVal ? _coerceAttributeValue(sample, fillVal) :
        (typeof sample === 'number' || typeof sample === 'boolean' ? null : '');
    });

    var newFeat = { type: 'Feature', geometry: null, properties: props };

    // 新行默认取第一个要素的几何（让新行能显示在地图上）；若原图层为空点集，则默认当前地图中心
    if (features.length > 0 && features[0].geometry) {
      var src = features[0].geometry;
      if (src.type === 'Point') {
        newFeat.geometry = { type: 'Point', coordinates: [src.coordinates[0], src.coordinates[1]] };
      } else {
        newFeat.geometry = JSON.parse(JSON.stringify(src));
      }
    } else {
      var centerLng = 112.9388, centerLat = 28.2282; // 默认长沙/中心
      if (window.GIS && window.GIS.map && window.GIS.map.getMap) {
        try {
          var c = window.GIS.map.getMap().getCenter();
          centerLng = parseFloat(c.lng.toFixed(6));
          centerLat = parseFloat(c.lat.toFixed(6));
        } catch(_) {}
      }
      newFeat.geometry = { type: 'Point', coordinates: [centerLng, centerLat] };
    }

    features.push(newFeat);

    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (layer && GIS.map && GIS.map.loadGeoJSON) {
      GIS.map.loadGeoJSON(gj, layer._rawName || layer.layer_id, { color: layer.color });
      _syncLayerOrder();
    }
    _syncEditedLayerData(layerId, gj);
    if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
      window.GIS.toast.success('已添加新记录行');
    }
    showLayerInspector(layerId, 'attr');
  }

  /** 删除行 */
  function deleteAttrRow(layerId, idx) {
    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;
    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];

    if (idx < 0 || idx >= features.length) return;
    features.splice(idx, 1);

    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (layer && GIS.map && GIS.map.loadGeoJSON) {
      GIS.map.loadGeoJSON(gj, layer._rawName || layer.layer_id, { color: layer.color });
      _syncLayerOrder();
    }
    _syncEditedLayerData(layerId, gj);
    if (window.GIS.toast && typeof window.GIS.toast.info === 'function') {
      window.GIS.toast.info('已删除第 ' + (idx + 1) + ' 行');
    }
    showLayerInspector(layerId, 'attr');
  }

  /** 添加字段 (加列) */
  function _showAddColumnModal(layerId, attrKeys) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;

    var overlay = document.createElement('div');
    overlay.className = 'workspace-modal-overlay';
    overlay.innerHTML =
      '<div class="workspace-modal-dialog" role="dialog" aria-modal="true" style="max-width:380px;">' +
        '<div class="workspace-modal-title">添加字段 (加列)</div>' +
        '<div class="workspace-modal-desc">向图层「' + escapeHtml(layer.filename || '未命名') + '」属性表中新增字段列。</div>' +
        '<div style="margin-bottom:12px;">' +
          '<label style="display:block;font-size:11px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">字段名称</label>' +
          '<input type="text" id="newFieldNameInput" class="workspace-modal-input" placeholder="如 name, area, level..." value="field_' + (Date.now() % 1000) + '" style="margin-bottom:0;" />' +
        '</div>' +
        '<div style="margin-bottom:12px;">' +
          '<label style="display:block;font-size:11px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">字段类型</label>' +
          '<select id="newFieldTypeSelect" class="symb-input symb-select" style="width:100%;height:32px;">' +
            '<option value="string">文本 (String / Text)</option>' +
            '<option value="number">数值 (Double / Number)</option>' +
          '</select>' +
        '</div>' +
        '<div style="margin-bottom:16px;">' +
          '<label style="display:block;font-size:11px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">默认值 (可选)</label>' +
          '<input type="text" id="newFieldDefaultInput" class="workspace-modal-input" placeholder="所有记录初始默认值" value="" style="margin-bottom:0;" />' +
        '</div>' +
        '<div class="workspace-modal-actions">' +
          '<button type="button" class="workspace-modal-btn cancel" id="cancelAddColBtn">取消</button>' +
          '<button type="button" class="workspace-modal-btn primary" id="confirmAddColBtn">立即添加</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    function close() { overlay.remove(); }
    overlay.querySelector('#cancelAddColBtn').onclick = close;
    overlay.onclick = function(e) { if (e.target === overlay) close(); };

    var nameInput = overlay.querySelector('#newFieldNameInput');
    nameInput.focus();
    nameInput.select();

    overlay.querySelector('#confirmAddColBtn').onclick = function() {
      var fieldName = nameInput.value.trim();
      if (!fieldName) {
        alert('请输入字段名称');
        nameInput.focus();
        return;
      }

      var fieldType = overlay.querySelector('#newFieldTypeSelect').value;
      var defaultRaw = overlay.querySelector('#newFieldDefaultInput').value.trim();
      var defaultVal = '';
      if (defaultRaw !== '') {
        defaultVal = fieldType === 'number' ? (parseFloat(defaultRaw) || 0) : defaultRaw;
      }

      var gj = getLayerGeoJSON(layerId);
      if (!gj) { close(); return; }
      var features = gj.type === 'FeatureCollection' ? (gj.features || []) : [gj];

      features.forEach(function(f) {
        if (!f.properties) f.properties = {};
        f.properties[fieldName] = defaultVal;
      });

      close();

      var layerObj = layerData.find(function(l) { return l.layer_id === layerId; });
      if (layerObj && GIS.map && GIS.map.loadGeoJSON) {
        GIS.map.loadGeoJSON(gj, layerObj._rawName || layerObj.layer_id, { color: layerObj.color });
        _syncLayerOrder();
      }
      _syncEditedLayerData(layerId, gj);

      if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
        window.GIS.toast.success('已成功添加字段「' + fieldName + '」');
      }

      showLayerInspector(layerId, 'attr');
    };
  }

  /** 删除字段 (删列) */
  function deleteAttrColumn(layerId, fieldName) {
    if (fieldName === '_fid') {
      if (window.GIS.toast && typeof window.GIS.toast.error === 'function') window.GIS.toast.error('_fid 是要素稳定标识，不能删除');
      return;
    }
    if (!confirm('确定要从图层中删除字段「' + fieldName + '」及其所有要素数据吗？')) return;
    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;
    var features = gj.type === 'FeatureCollection' ? (gj.features || []) : [gj];
    features.forEach(function(f) {
      if (f.properties && fieldName in f.properties) {
        delete f.properties[fieldName];
      }
    });
    var layerObj = layerData.find(function(l) { return l.layer_id === layerId; });
    if (layerObj && GIS.map && GIS.map.loadGeoJSON) {
      GIS.map.loadGeoJSON(gj, layerObj._rawName || layerObj.layer_id, { color: layerObj.color });
      _syncLayerOrder();
    }
    _syncEditedLayerData(layerId, gj);
    if (window.GIS.toast && typeof window.GIS.toast.info === 'function') {
      window.GIS.toast.info('已删除字段「' + fieldName + '」');
    }
    showLayerInspector(layerId, 'attr');
  }

  /** 打开字段计算器模态框 (类似 ArcMap 字段计算器) */
  function _showFieldCalculatorModal(layerId, attrKeys) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;

    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;
    var features = gj.type === 'FeatureCollection' ? (gj.features || []) : [gj];

    var validFields = (attrKeys || []).filter(function(k) { return VIRTUAL_KEYS_ALL.indexOf(k) === -1; });
    if (validFields.length === 0) {
      alert('当前图层没有可计算的属性字段，请先点击「+ 列」添加字段。');
      return;
    }

    var overlay = document.createElement('div');
    overlay.className = 'workspace-modal-overlay';

    var fieldChipsHtml = validFields.map(function(f) {
      return '<button type="button" class="calc-chip" data-insert="[' + escapeHtml(f) + ']">' + escapeHtml(f) + '</button>';
    }).join(' ');

    if (_isPointLayer(features)) {
      fieldChipsHtml += ' <button type="button" class="calc-chip" data-insert="[_经度]" style="color:#2e7d32;font-weight:600;">_经度</button>';
      fieldChipsHtml += ' <button type="button" class="calc-chip" data-insert="[_纬度]" style="color:#2e7d32;font-weight:600;">_纬度</button>';
    }

    var targetOptionsHtml = validFields.map(function(f) {
      return '<option value="' + escapeHtml(f) + '">' + escapeHtml(f) + '</option>';
    }).join('');

    overlay.innerHTML =
      '<div class="workspace-modal-dialog" role="dialog" aria-modal="true" style="max-width:480px;">' +
        '<div class="workspace-modal-title">字段计算器 (Field Calculator)</div>' +
        '<div class="workspace-modal-desc">批量计算属性值，类似 ArcMap 字段计算器。支持数学公式与文本拼接。</div>' +
        '<div style="margin-bottom:12px;">' +
          '<label style="display:block;font-size:11px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">目标字段 (计算结果写入该字段)</label>' +
          '<select id="calcTargetFieldSelect" class="symb-input symb-select" style="width:100%;height:32px;">' +
            targetOptionsHtml +
          '</select>' +
        '</div>' +
        '<div style="margin-bottom:10px;">' +
          '<label style="display:block;font-size:11px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">点击插入字段</label>' +
          '<div style="display:flex;flex-wrap:wrap;gap:4px;padding:6px;border:1px solid var(--outline-variant,#ddd);border-radius:6px;background:var(--surface-container-low,#f7f5f4);max-height:80px;overflow-y:auto;">' +
            fieldChipsHtml +
          '</div>' +
        '</div>' +
        '<div style="margin-bottom:10px;">' +
          '<label style="display:block;font-size:11px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">快捷运算符与函数</label>' +
          '<div style="display:flex;gap:4px;flex-wrap:wrap;">' +
            '<button type="button" class="calc-op-btn" data-insert=" + ">+</button>' +
            '<button type="button" class="calc-op-btn" data-insert=" - ">-</button>' +
            '<button type="button" class="calc-op-btn" data-insert=" * ">*</button>' +
            '<button type="button" class="calc-op-btn" data-insert=" / ">/</button>' +
            '<button type="button" class="calc-op-btn" data-insert="&quot;&quot;">""</button>' +
            '<button type="button" class="calc-op-btn" data-insert="Math.round()">Math.round()</button>' +
            '<button type="button" class="calc-op-btn" data-insert="Math.abs()">Math.abs()</button>' +
          '</div>' +
        '</div>' +
        '<div style="margin-bottom:12px;">' +
          '<label style="display:block;font-size:11px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">表达式 (例如: [pop] * 1.05 或 [name] + "_区")</label>' +
          '<textarea id="calcExpressionTextarea" class="workspace-modal-input" rows="3" style="font-family:monospace;font-size:12px;margin-bottom:0;resize:vertical;" placeholder="输入表达式，如 [pop] * 2 或 [name] + &quot;区&quot;"></textarea>' +
        '</div>' +
        '<div class="workspace-modal-actions">' +
          '<button type="button" class="workspace-modal-btn cancel" id="cancelCalcBtn">取消</button>' +
          '<button type="button" class="workspace-modal-btn primary" id="confirmCalcBtn">执行计算</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    function close() { overlay.remove(); }
    overlay.querySelector('#cancelCalcBtn').onclick = close;
    overlay.onclick = function(e) { if (e.target === overlay) close(); };

    var exprArea = overlay.querySelector('#calcExpressionTextarea');
    exprArea.focus();

    function insertAtCursor(text) {
      var start = exprArea.selectionStart;
      var end = exprArea.selectionEnd;
      var val = exprArea.value;
      exprArea.value = val.substring(0, start) + text + val.substring(end);
      exprArea.selectionStart = exprArea.selectionEnd = start + text.length;
      exprArea.focus();
    }

    overlay.querySelectorAll('.calc-chip, .calc-op-btn').forEach(function(btn) {
      btn.onclick = function(e) {
        e.preventDefault();
        insertAtCursor(this.dataset.insert);
      };
    });

    overlay.querySelector('#confirmCalcBtn').onclick = function() {
      var targetField = overlay.querySelector('#calcTargetFieldSelect').value;
      var expr = exprArea.value.trim();
      if (!expr) {
        alert('请输入计算表达式');
        exprArea.focus();
        return;
      }
      close();
      _executeFieldCalculation(layerId, targetField, expr);
    };
  }

  /** 执行字段计算 */
  function _executeFieldCalculation(layerId, targetField, expr) {
    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;
    var features = gj.type === 'FeatureCollection' ? (gj.features || []) : [gj];
    if (features.length === 0) return;

    var successCount = 0;
    var errorCount = 0;

    features.forEach(function(f) {
      var props = f.properties || {};
      try {
        var evaluatedExpr = expr.replace(/\[!?([a-zA-Z0-9_\u4e00-\u9fa5]+)!?\]/g, function(match, fieldName) {
          if (fieldName === '_经度') {
            return (f.geometry && f.geometry.coordinates ? f.geometry.coordinates[0] : 0);
          }
          if (fieldName === '_纬度') {
            return (f.geometry && f.geometry.coordinates ? f.geometry.coordinates[1] : 0);
          }
          var v = props[fieldName];
          if (v === null || v === undefined) return 'null';
          if (typeof v === 'string') return JSON.stringify(v);
          return v;
        });

        var result = (new Function('Math', 'return (' + evaluatedExpr + ');'))(Math);
        if (result !== undefined) {
          props[targetField] = result;
          successCount++;
        }
      } catch(err) {
        errorCount++;
      }
    });

    var layerObj = layerData.find(function(l) { return l.layer_id === layerId; });
    if (layerObj && GIS.map && GIS.map.loadGeoJSON) {
      GIS.map.loadGeoJSON(gj, layerObj._rawName || layerObj.layer_id, { color: layerObj.color });
      _syncLayerOrder();
    }
    _syncEditedLayerData(layerId, gj);

    if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
      if (errorCount === 0) {
        window.GIS.toast.success('字段「' + targetField + '」计算完成 (' + successCount + ' 条记录)');
      } else {
        window.GIS.toast.info('计算完成：' + successCount + ' 条成功，' + errorCount + ' 条异常');
      }
    }

    showLayerInspector(layerId, 'attr');
  }

  // ---- 筛选函数 ----

  var _filteredIndicesMap = new Map();

  function applyFilter(layerId) {
    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;
    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];

    var field = document.getElementById('attrFilterField')?.value;
    var op = document.getElementById('attrFilterOp')?.value;
    var val = document.getElementById('attrFilterVal')?.value?.trim();
    if (!field || !op || val === undefined) return;

    var matched = [];
    features.forEach(function(f, i) {
      var pv = String(f.properties ? f.properties[field] ?? '' : '');
      var match = false;
      switch (op) {
        case 'eq': match = pv === val; break;
        case 'neq': match = pv !== val; break;
        case 'gt': match = Number(pv) > Number(val); break;
        case 'gte': match = Number(pv) >= Number(val); break;
        case 'lt': match = Number(pv) < Number(val); break;
        case 'lte': match = Number(pv) <= Number(val); break;
        case 'contains': match = pv.includes(val); break;
      }
      if (match) matched.push(i);
    });

    _filteredIndicesMap.set(layerId, matched);

    // 高亮表格行
    var table = document.getElementById('attrDataTable');
    if (table) {
      table.querySelectorAll('tbody tr').forEach(function(row) {
        var idx = parseInt(row.dataset.idx, 10);
        row.style.display = matched.includes(idx) ? '' : 'none';
      });
    }

    var countEl = document.getElementById('attrFilterCount');
    if (countEl) countEl.textContent = '匹配 ' + matched.length + ' / ' + features.length;
  }

  function clearFilter(layerId) {
    if (layerId) {
      _filteredIndicesMap.delete(layerId);
    } else {
      _filteredIndicesMap.clear();
    }
    var table = document.getElementById('attrDataTable');
    if (table) {
      table.querySelectorAll('tbody tr').forEach(function(row) {
        row.style.display = '';
      });
    }
    var countEl = document.getElementById('attrFilterCount');
    if (countEl) countEl.textContent = '';
  }

  /** 筛选结果导出为新图层 */
  function exportFilteredLayer(layerId) {
    var indices = _filteredIndicesMap.get(layerId);
    if (!indices || indices.length === 0) {
      if (window.GIS.chat) window.GIS.chat.addMessage('请先设置筛选条件', 'system');
      return;
    }
    var gj = getLayerGeoJSON(layerId);
    if (!gj) return;
    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];

    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    var name = (layer ? layer.filename || layer.layer_id : '图层') + '_筛选结果';

    var newFeatures = indices.map(function(i) { return features[i]; });
    var newGJ = { type: 'FeatureCollection', features: newFeatures };

    var color = layer ? layer.color : '#1c1b1b';
    var newLayerId = 'filter_' + Date.now();

    if (GIS.map && GIS.map.loadGeoJSON) {
      GIS.map.loadGeoJSON(newGJ, name, { color: color });
    }
    if (GIS.layers && GIS.layers.addLayer) {
      GIS.layers.addLayer({
        layer_id: newLayerId,
        filename: name,
        geometry_type: (newFeatures[0] && newFeatures[0].geometry && newFeatures[0].geometry.type) || '未知',
        crs: 'WGS-84',
        geojson: newGJ,
        visible: true,
        color: color,
        source: 'filter',
      });
    }
    if (window.GIS.chat) {
      window.GIS.chat.addMessage('已从筛选结果创建新图层「' + name + '」（' + newFeatures.length + ' 个要素）', 'system');
    }
    clearFilter(layerId);
    closeInspector();
  }

  /** 导出属性表为 CSV */
  function exportAttrCSV(layerId) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;
    var gj = layer.geojson;
    if (!gj && GIS.map && GIS.map.getGeoJSON) {
      gj = GIS.map.getGeoJSON(layer._rawName || layer.layer_id);
    }
    if (!gj) return;
    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];
    if (!features.length) return;

    var keys = Object.keys(features[0].properties || {});
    if (!keys.length) return;

    var csv = keys.join(',') + '\n';
    features.forEach(function(f) {
      csv += keys.map(function(k) {
        var v = f.properties ? f.properties[k] : null;
        var s = (v === null || v === undefined) ? '' : String(v);
        return (s.includes(',') || s.includes('"') || s.includes('\n'))
          ? '"' + s.replace(/"/g, '""') + '"'
          : s;
      }).join(',') + '\n';
    });

    var bom = '\ufeff';
    var blob = new Blob([bom + csv], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (layer.filename || '图层') + '_属性表.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /** 关闭图层检查器 */
  function closeInspector() {
    var panel = document.getElementById('layerInspector');
    if (panel) panel.style.display = 'none';
  }

  // ---- 通用确认弹窗 ----

  function showConfirm(title, message, onConfirm) {
    var overlay = document.getElementById('confirmOverlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'confirmOverlay';
      overlay.className = 'confirm-overlay';
      overlay.innerHTML =
        '<div class="confirm-dialog">' +
          '<div class="confirm-title" id="confirmTitle"></div>' +
          '<div class="confirm-msg" id="confirmMsg"></div>' +
          '<div class="confirm-actions">' +
            '<button class="confirm-btn confirm-cancel" id="confirmCancel">取消</button>' +
            '<button class="confirm-btn confirm-ok" id="confirmOk">确认</button>' +
          '</div>' +
        '</div>';
      document.body.appendChild(overlay);

      overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeConfirm();
      });
      document.getElementById('confirmCancel').addEventListener('click', closeConfirm);
    }

    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmMsg').textContent = message;
    overlay.style.display = 'flex';

    var okBtn = document.getElementById('confirmOk');
    var newBtn = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newBtn, okBtn);
    newBtn.addEventListener('click', function() {
      closeConfirm();
      if (typeof onConfirm === 'function') onConfirm();
    });

    function closeConfirm() {
      overlay.style.display = 'none';
    }
  }

  var _lastLegendData = null;

  /** 隐藏浮动图例并清空记忆（图层删除/清空时调用，防止孤儿图例残留） */
  function _hideFloatingLegend() {
    _lastLegendData = null;
    var panel = document.getElementById('mapFloatingLegend');
    var pill = document.getElementById('mapLegendTogglePill');
    if (panel) panel.style.display = 'none';
    if (pill) pill.style.display = 'none';
  }

  function _buildLegacySymbolLegend(type, field, features, config) {
    var values = features.map(function(feature) { return _numericFieldValue(feature, field); })
      .filter(function(value) { return Number.isFinite(value) && (type !== 'proportional' || value > 0); });
    if (!values.length) return null;
    var sorted = values.slice().sort(function(a, b) { return a - b; });
    var min = sorted[0], max = sorted[sorted.length - 1];

    if (type === 'graduated-symbol') {
      var isPoint = _isPointLayer(features);
      var classes = min === max ? 1 : Math.max(1, Math.floor(Number(config.classes) || 1));
      var minSize = Number(config.minSize) || (isPoint ? 3 : 1);
      var maxSize = Number(config.maxSize) || (isPoint ? 12 : 5);
      var scheme = _getColorScheme(config.colorScheme || 'blues', classes);
      var breaks = [];
      for (var i = 0; i <= classes; i++) breaks.push(min + (max - min) * i / classes);
      var items = [];
      for (var j = 0; j < classes; j++) {
        var ratio = classes > 1 ? j / (classes - 1) : 0;
        var size = Math.round(minSize + ratio * (maxSize - minSize));
        var count = values.filter(function(value) {
          return value >= breaks[j] && (value < breaks[j + 1] || (j === classes - 1 && value <= breaks[j + 1]));
        }).length;
        items.push({
          label: breaks[j].toFixed(2) + ' - ' + breaks[j + 1].toFixed(2) + ' · ' + (isPoint ? '半径 ' : '线宽 ') + size + 'px',
          color: scheme[Math.min(j, scheme.length - 1)], size: size, count: count,
        });
      }
      var missing = features.length - values.length;
      if (missing) items.push({
        label: '无数据 · ' + (isPoint ? '半径 ' : '线宽 ') + Math.round(minSize) + 'px',
        color: '#9ca3af', size: Math.round(minSize), count: missing,
      });
      return { type: type, field: field, method: 'equal_interval', items: items };
    }

    if (type === 'proportional') {
      var minRadius = Number(config.minSize) || 3;
      var maxRadius = Number(config.maxSize) || 20;
      var proportionalItems = [{
        label: min.toFixed(2) + ' · 半径 ' + Math.round(minRadius) + 'px', color: '#1c1b1b', size: Math.round(minRadius),
      }];
      if (max !== min) proportionalItems.push({
        label: max.toFixed(2) + ' · 半径 ' + Math.round(maxRadius) + 'px', color: '#1c1b1b', size: Math.round(maxRadius),
      });
      var invalid = features.length - values.length;
      if (invalid) proportionalItems.push({
        label: '无数据 · 半径 ' + Math.round(minRadius) + 'px', color: '#9ca3af', size: Math.round(minRadius), count: invalid,
      });
      return { type: type, field: field, items: proportionalItems };
    }
    return null;
  }

  /** 显示地图浮动图例 */
  function _renderFloatingLegend(layerName, data, layerId) {
    _lastLegendData = { layerName: layerName, data: data, layerId: layerId || null };
    var panel = document.getElementById('mapFloatingLegend');
    var pill = document.getElementById('mapLegendTogglePill');
    var pillText = document.getElementById('mapLegendToggleText');
    if (!panel) return;
    var titleEl = document.getElementById('mapLegendTitle');
    var fieldEl = document.getElementById('mapLegendField');
    var itemsEl = document.getElementById('mapLegendItems');
    var closeBtn = document.getElementById('mapLegendClose');

    if (titleEl) titleEl.textContent = '图例 — ' + layerName;
    var legendTypeLabel = data.type === 'graduated' ? '分级设色'
      : data.type === 'graduated-symbol' ? '分级符号'
      : data.type === 'proportional' ? '比例符号' : '唯一值';
    if (fieldEl) fieldEl.textContent = '字段：' + data.field + ' (' + legendTypeLabel + ')';
    if (pillText) pillText.textContent = '图例 — ' + layerName;
    if (itemsEl) {
      itemsEl.innerHTML = '';
      (data.items || []).forEach(function(item) {
        var row = document.createElement('div');
        row.className = 'map-legend-row';
        var swatch = document.createElement('span');
        swatch.className = 'map-legend-swatch';
        swatch.style.background = item.color;
        var label = document.createElement('span');
        label.className = 'map-legend-label';
        label.textContent = item.label + (item.count !== undefined ? ' (' + item.count + ')' : '');
        row.appendChild(swatch);
        row.appendChild(label);
        itemsEl.appendChild(row);
      });
    }
    panel.style.display = 'flex';
    if (pill) pill.style.display = 'none';

    if (closeBtn && !closeBtn._bound) {
      closeBtn._bound = true;
      closeBtn.addEventListener('click', function() {
        panel.style.display = 'none';
        if (pill) pill.style.display = 'inline-flex';
      });
    }

    if (pill && !pill._bound) {
      pill._bound = true;
      pill.addEventListener('click', function() {
        if (_lastLegendData) {
          _renderFloatingLegend(_lastLegendData.layerName, _lastLegendData.data, _lastLegendData.layerId);
        } else {
          panel.style.display = 'flex';
          pill.style.display = 'none';
        }
      });
    }
  }

  /** 显示图例 */
  function _showLegend(layerId, silent) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer && layerData.length > 0) layer = layerData[0];
    if (!layer) return;

    var config = _symbologyConfig[layer.layer_id];
    if (config && config.enabled && !config.legendData &&
        (config.type === 'graduated-symbol' || config.type === 'proportional')) {
      var symbolGeoJSON = getLayerGeoJSON(layer.layer_id);
      var symbolFeatures = symbolGeoJSON
        ? (symbolGeoJSON.type === 'FeatureCollection' ? (symbolGeoJSON.features || []) : [symbolGeoJSON]) : [];
      var restoredLegend = _buildLegacySymbolLegend(config.type, config.field, symbolFeatures, config);
      if (restoredLegend) config.legendData = restoredLegend;
    }
    if ((!config || !config.legendData) && (!config || !config.enabled)) {
      // 智能探测：若图层未设色但包含数值字段（如人口_万人、人口等），自动为其应用分级设色并生成图例
      var gj = getLayerGeoJSON(layer.layer_id);
      var features = gj ? (gj.type === 'FeatureCollection' ? (gj.features || []) : [gj]) : [];
      if (features.length && features[0].properties) {
        var props = features[0].properties;
        var numField = Object.keys(props).find(function(k) {
          return /(人口|pop|gdp|val|count|数量|数值)/i.test(k) && typeof props[k] === 'number';
        }) || Object.keys(props).find(function(k) {
          return typeof props[k] === 'number' && !/adcode|code|id|fid|index/i.test(k);
        });
        if (numField) {
          var colors = _getColorScheme('ylorrd', 5);
          if (!_symbologyConfig[layer.layer_id]) _symbologyConfig[layer.layer_id] = {};
          _symbologyConfig[layer.layer_id].enabled = true;
          _applyGraduatedColors(layer, gj, features, numField, 5, colors);
          config = _symbologyConfig[layer.layer_id];
        }
      }
    }

    if (!config || !config.legendData) {
      if (!silent && window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
        window.GIS.chat.addMessage('该图层未找到可分级的数值指标，请先为图层应用分级设色', 'system');
      }
      return;
    }
    var data = config.legendData;
    var layerName = layer ? (layer._rawName || layer.filename || layer.layer_id) : layerId;

    // 呈现在地图右下角浮动图例控件中
    _renderFloatingLegend(layerName, data, layer ? layer.layer_id : null);

    if (!silent && window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('已在地图右下角展示「' + escapeHtml(layerName) + '」图例', 'system');
    }
  }

  function _findLayerByNameOrFuzzy(name) {
    if (!name) return null;
    var requested = String(name).trim();
    if (!requested) return null;
    return layerData.find(function(l) {
      return [l._registeredName, l._rawName, l.filename, l.layer_id]
        .some(function(alias) { return alias != null && String(alias) === requested; });
    }) || null;
  }

  /** 按照AI layer_op 'symbology' 应用分级色彩 */
  function _applyGraduatedFromAI(name, field, classes, scheme, method, breaks, fillOpacity) {
    var layer = _findLayerByNameOrFuzzy(name);
    if (!layer) { if (window.GIS.chat) window.GIS.chat.addMessage('未找到图层「' + name + '」', 'system'); return; }
    var gj = getLayerGeoJSON(layer.layer_id);
    if (!gj) { if (window.GIS.chat) window.GIS.chat.addMessage('图层「' + name + '」无数据', 'system'); return; }
    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];
    if (!features.length) return;
    var colors = _getColorScheme(scheme || 'blues', classes || 5);
    var previousConfig = _symbologyConfig[layer.layer_id];
    _symbologyConfig[layer.layer_id] = Object.assign({}, previousConfig || {}, {
      type: 'graduated', field: field, classes: classes || 5, colorScheme: scheme || 'blues',
      method: method === 'quantile' ? 'quantile' : 'equal_interval', breaks: Array.isArray(breaks) ? breaks.slice() : null,
      fillOpacity: fillOpacity, enabled: true,
    });
    if (!_applyGraduatedColors(layer, gj, features, field, classes || 5, colors, method, breaks, fillOpacity)) {
      if (previousConfig) _symbologyConfig[layer.layer_id] = previousConfig;
      else delete _symbologyConfig[layer.layer_id];
      return false;
    }
    _showLegend(layer.layer_id);
    return true;
  }

  /** 按照AI layer_op 'symbology' 应用唯一值渲染 */
  function _applyUniqueFromAI(name, field, scheme) {
    var layer = _findLayerByNameOrFuzzy(name);
    if (!layer) { if (window.GIS.chat) window.GIS.chat.addMessage('未找到图层「' + name + '」', 'system'); return; }
    var gj = getLayerGeoJSON(layer.layer_id);
    if (!gj) { if (window.GIS.chat) window.GIS.chat.addMessage('图层「' + name + '」无数据', 'system'); return; }
    var features = [];
    if (gj.type === 'FeatureCollection') features = gj.features || [];
    else if (gj.type === 'Feature') features = [gj];
    if (!features.length) return;
    if (!features.some(function(feature) {
      return feature && feature.properties && Object.prototype.hasOwnProperty.call(feature.properties, field);
    })) {
      if (window.GIS.chat) window.GIS.chat.addMessage('字段「' + field + '」不存在，未修改图层样式', 'system');
      return false;
    }
    var uniq = features.map(function(f) { return f.properties ? f.properties[field] : null; }).filter(function(v, i, a) { return a.indexOf(v) === i; });
    var colors = _getColorScheme(scheme || 'scheme', Math.min(uniq.length, 10));
    var previousConfig = _symbologyConfig[layer.layer_id];
    _symbologyConfig[layer.layer_id] = Object.assign({}, previousConfig || {}, {
      type: 'unique', field: field, colorScheme: scheme || 'scheme', enabled: true,
    });
    if (!_applyUniqueValues(layer, gj, features, field, colors)) {
      if (previousConfig) _symbologyConfig[layer.layer_id] = previousConfig;
      else delete _symbologyConfig[layer.layer_id];
      return false;
    }
    _showLegend(layer.layer_id);
    return true;
  }

  GIS.layers = {
    init, renderList, addLayer, removeLayer, clearAll, toggleVisibility, showAll, hideAll, setAllVisibility, downloadLayer,
    getGroupState: getGroupState, setGroupState: setGroupState,
    analyzeLayer, showLayerInspector, closeInspector, exportAttrCSV,
    syncLayerOrder: _syncLayerOrder,
    syncLayerData: _syncEditedLayerData,
    coerceAttributeValue: _coerceAttributeValue,
    waitForRegistrySync: _waitForRegistrySync,
    getLayers: () => [...layerData],
    getSymbologyState: _getSymbologyState,
    getLegendData: _getLegendData,
    restoreSymbologyState: _restoreSymbologyState,
    nextColor: nextColor,
    /** 返回所有图层名称列表（供网络分析面板使用） */
    getLayerNames: function() {
      return layerData.map(function(l) { return l.filename; });
    },
    /** 按图层名称获取 GeoJSON（供网络分析面板使用） */
    getLayerGeoJSON: function(name) {
      var layer = layerData.find(function(l) { return l.filename === name; });
      if (!layer) return null;
      return layer.geojson || null;
    },
    /** 按图层名称获取完整图层对象（供空间统计面板使用） */
    getLayerByName: function(name) {
      return layerData.find(function(l) { return l.filename === name || l.layer_id === name; }) || null;
    },
    /** AI 自然语言调用：对图层应用分级色彩 */
    applyGraduatedColors: _applyGraduatedFromAI,
    /** AI 自然语言调用：对图层应用唯一值渲染 */
    applyUniqueValues: _applyUniqueFromAI,
    /** AI 自然语言调用：清除符号化并同步移除该图层的浮动图例 */
    clearSymbology: function(name) {
      var layer = _findLayerByNameOrFuzzy(name);
      if (!layer) {
        if (window.GIS.chat && window.GIS.chat.addMessage) {
          window.GIS.chat.addMessage('未找到图层「' + (name || '') + '」，无法清除符号化', 'system');
        }
        return false;
      }
      _clearSymbology(layer.layer_id);
      return true;
    },
    /** AI 自然语言调用：对图层添加属性标注 */
    addLabels: function(name, field) {
      var layer = _findLayerByNameOrFuzzy(name);
      if (!layer) { if (window.GIS.chat) window.GIS.chat.addMessage('未找到图层「' + name + '」', 'system'); return; }
      if (GIS.map && GIS.map.setLabels) GIS.map.setLabels(layer._rawName || layer.layer_id, field);
    },
    /** 清除图层标注 */
    clearLabels: function(name) {
      var layer = _findLayerByNameOrFuzzy(name);
      if (!layer) return;
      if (GIS.map && GIS.map.clearLabels) GIS.map.clearLabels(layer._rawName || name);
    },
    /** AI 自然语言调用：显示图例 */
    addLegend: function(name) {
      var layer = null;
      if (name) {
        layer = _findLayerByNameOrFuzzy(name);
      } else {
        layer = layerData.find(function(l) { return _symbologyConfig[l.layer_id] && _symbologyConfig[l.layer_id].legendData; }) || layerData[0];
      }
      if (!layer) {
        if (_lastLegendData) {
          _renderFloatingLegend(_lastLegendData.layerName, _lastLegendData.data, _lastLegendData.layerId);
        }
        return;
      }
      _showLegend(layer.layer_id, false);
    },
    /** AI 自然语言调用：显示指北针 */
    addNorthArrow: function() {
      if (window.GIS.map && window.GIS.map.showNorthArrow) {
        window.GIS.map.showNorthArrow();
        if (window.GIS.chat) window.GIS.chat.addMessage('指北针已显示在地图右上角', 'system');
      }
    },
    /** 折点编辑：进入顶点拖拽编辑模式 */
    editVertices: function(name) {
      var layer = _findLayerByNameOrFuzzy(name);
      if (!layer) { if (window.GIS.chat) window.GIS.chat.addMessage('未找到图层「' + name + '」', 'system'); return; }
      if (GIS.map && GIS.map.enterEditMode) {
        GIS.map.enterEditMode(layer._rawName || layer.filename || layer.layer_id);
      }
    },
    /** 保存折点编辑并退出编辑模式 */
    saveEditVertices: function(name) {
      if (GIS.map && GIS.map.exitEditMode) {
        // map.exitEditMode is the cancel method; save is handled internally
        GIS.chat.addMessage('请在编辑栏点击「保存」按钮完成编辑', 'system');
      }
    },
    startAddingToLayer: startAddingToLayer,
    showCreateLayerModal: _showCreateLayerModal,
  };


  // ===== 右键菜单 =====

  function bindContextMenu() {
    if (!tbody) return;
    var menu = document.getElementById('layerContextMenu');
    if (!menu) {
      menu = document.createElement('div');
      menu.id = 'layerContextMenu';
    menu.className = 'context-menu';
      menu.setAttribute('role', 'menu');
      document.body.appendChild(menu);
    }

    tbody.addEventListener('contextmenu', function(e) {
      var tr = e.target.closest('tr[draggable]');
      if (!tr) return;
      e.preventDefault();
      e.stopPropagation();
      var layerId = tr.dataset.id;
      if (!layerId) return;
      _showContextMenu(e.clientX, e.clientY, layerId);
    });

    document.addEventListener('click', _hideContextMenu);
    document.addEventListener('contextmenu', function(e) {
      if (!e.target.closest('.context-menu')) _hideContextMenu();
    });
  }

  function _showContextMenu(x, y, layerId) {
    _hideContextMenu();
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;

    var groupItemHtml = '';
    var groupKeys = Object.keys(groups);
    if (layer.groupId && groups[layer.groupId]) {
      groupItemHtml =
        '<div class="context-menu-item" data-action="remove-from-group" title="移出当前分组">移出分组 (' + escapeHtml(groups[layer.groupId].name) + ')</div>' +
        '<div class="context-menu-item" data-action="move-to-group" title="移动到其他分组">移动到分组…</div>';
    } else {
      groupItemHtml = '<div class="context-menu-item" data-action="move-to-group" title="移动到分组">移动到分组…</div>';
    }

    var legendItemHtml =
      '<div class="context-menu-item" data-action="legend" title="在地图右下角显示此图层的图例">' +
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;" aria-hidden="true"><rect x="3" y="3" width="7" height="9"></rect><rect x="14" y="3" width="7" height="5"></rect><rect x="14" y="12" width="7" height="9"></rect><rect x="3" y="16" width="7" height="5"></rect></svg>' +
      '显示图例</div>';

    var menu = document.getElementById('layerContextMenu');
    menu.innerHTML =
      legendItemHtml +
      '<div class="context-menu-item" data-action="inspect" title="查看要素信息和属性">检查</div>' +
      '<div class="context-menu-item" data-action="add-feature" title="向此图层连续添加要素（点/线）">＋ 添加要素</div>' +
      '<div class="context-menu-item" data-action="toggle">' + (layer.visible !== false ? '隐藏' : '显示') + '</div>' +
      '<div class="context-menu-divider"></div>' +
      groupItemHtml +
      '<div class="context-menu-divider"></div>' +
      '<div class="context-menu-item" data-action="color" title="更改图层颜色">更改颜色</div>' +
      '<div class="context-menu-item" data-action="fit" title="缩放至图层范围">缩放至</div>' +
      '<div class="context-menu-item" data-action="analyze">发送给 AI 分析</div>' +
      '<div class="context-menu-item" data-action="swipe">卷帘对比</div>' +
      '<div class="context-menu-divider"></div>' +
      '<div class="context-menu-item" data-action="rename" title="重命名图层">重命名</div>' +
      '<div class="context-menu-item" data-action="download" title="下载图层">下载</div>' +
      '<div class="context-menu-divider"></div>' +
      '<div class="context-menu-item context-menu-item-danger" data-action="delete" title="删除图层">删除</div>';

    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    menu.style.display = 'block';
    menu._layerId = layerId;
    const bounds = menu.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(x, window.innerWidth - bounds.width - 8)) + 'px';
    menu.style.top = Math.max(8, Math.min(y, window.innerHeight - bounds.height - 8)) + 'px';

    // 点击菜单项
    menu.querySelectorAll('.context-menu-item').forEach(function(item) {
      item.setAttribute('role', 'menuitem');
      item.tabIndex = 0;
      item.addEventListener('keydown', function(ev) {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); item.click(); }
        if (ev.key === 'Escape') _hideContextMenu();
      });
      item.addEventListener('click', function(ev) {
        ev.stopPropagation();
        var action = this.dataset.action;
        _hideContextMenu();
        _execContextAction(action, layerId);
      });
    });
    menu.querySelector('.context-menu-item').focus();
  }

  function _hideContextMenu() {
    var menu = document.getElementById('layerContextMenu');
    if (menu) {
      const restoreFocus = menu.contains(document.activeElement);
      menu.style.display = 'none';
      if (restoreFocus && menu._layerId) {
        const button = tbody.querySelector('.layer-more-btn[data-id="' + CSS.escape(menu._layerId) + '"]');
        if (button) button.focus();
      }
    }
  }

  function _execContextAction(action, layerId) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;

    switch (action) {
      case 'legend':
        _showLegend(layerId);
        break;
      case 'inspect':
        showLayerInspector(layerId);
        break;
      case 'toggle':
        toggleVisibility(layerId);
        break;
      case 'remove-from-group':
        moveLayerToGroup(layerId, null);
        if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
          window.GIS.toast.success('已将图层移出分组');
        }
        break;
      case 'move-to-group':
        _showMoveToGroupModal(layerId);
        break;
      case 'color':
        _triggerColorPicker(layerId);
        break;
      case 'fit':
        if (GIS.map && GIS.map.fitLayer) {
          GIS.map.fitLayer(layer._rawName || layer.layer_id);
        }
        break;
      case 'rename':
        _triggerRename(layerId);
        break;
      case 'download':
        downloadLayer(layerId);
        break;
      case 'analyze':
        if (GIS.workspace) GIS.workspace.toggleAI(true);
        analyzeLayer(layerId);
        break;
      case 'add-feature':
        startAddingToLayer(layerId);
        break;
      case 'swipe':
        if (_handleSwipeAction) _handleSwipeAction(layerId, tbody.querySelector('.layer-more-btn[data-id="' + CSS.escape(layerId) + '"]'));
        break;
      case 'delete':
        removeLayer(layerId);
        break;
    }
  }

  /** 向指定图层连续添加要素 */
  function startAddingToLayer(layerId) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;
    var rawType = layer.geometry_type || _detectGeomType(layer.geojson);
    var tool = 'marker';
    if (rawType.includes('Line')) tool = 'polyline';
    else if (rawType.includes('Polygon')) tool = 'polygon';

    if (window.GIS.map && typeof window.GIS.map.setTargetLayerForDrawing === 'function') {
      window.GIS.map.setTargetLayerForDrawing(layerId);
    }
    // 触发对应绘制按钮激活连续绘制
    var drawBtn = document.querySelector('.map-draw-btn[data-tool="' + tool + '"]');
    if (drawBtn) drawBtn.click();
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('已开启「' + (layer.filename || '图层') + '」的连续落点/绘制模式，在地图上点击即可添加要素', 'system', { pill: true });
    }
  }

  function _getDateSuffix() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return '' + d.getFullYear() + m + day;
  }

  /** 弹出新建点集/线集/几何集合图层模态框 */
  function _showCreateLayerModal() {
    var overlay = document.createElement('div');
    overlay.className = 'workspace-modal-overlay';
    overlay.innerHTML =
      '<div class="workspace-modal-dialog" role="dialog" aria-modal="true" style="max-width:440px;">' +
        '<div class="workspace-modal-title">新建要素集合图层</div>' +
        '<div class="workspace-modal-desc">创建一个空的几何集合图层，随后可直接在地图上连续打点、画线或在属性表中批量录入。</div>' +
        '<div style="margin-bottom:12px;">' +
          '<label style="display:block;font-size:12px;font-weight:600;margin-bottom:4px;color:var(--on-surface);">图层名称</label>' +
          '<input type="text" id="newLayerNameInput" class="workspace-modal-input" value="点集_' + _getDateSuffix() + '" style="margin-bottom:0;" />' +
        '</div>' +
        '<div style="margin-bottom:18px;">' +
          '<label style="display:block;font-size:12px;font-weight:600;margin-bottom:6px;color:var(--on-surface);">几何类型</label>' +
          '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">' +
            '<label style="display:flex;align-items:center;gap:6px;padding:8px 10px;border:1px solid var(--outline-variant);border-radius:6px;cursor:pointer;font-size:12px;background:var(--surface-container-low);">' +
              '<input type="radio" name="newLayerType" value="Point" checked style="accent-color:var(--primary,#000);" />' +
              '<span><strong>点集合</strong> (MultiPoint/Point)</span>' +
            '</label>' +
            '<label style="display:flex;align-items:center;gap:6px;padding:8px 10px;border:1px solid var(--outline-variant);border-radius:6px;cursor:pointer;font-size:12px;background:var(--surface-container-low);">' +
              '<input type="radio" name="newLayerType" value="LineString" style="accent-color:var(--primary,#000);" />' +
              '<span><strong>线集合</strong> (LineString)</span>' +
            '</label>' +
            '<label style="display:flex;align-items:center;gap:6px;padding:8px 10px;border:1px solid var(--outline-variant);border-radius:6px;cursor:pointer;font-size:12px;background:var(--surface-container-low);">' +
              '<input type="radio" name="newLayerType" value="Polygon" style="accent-color:var(--primary,#000);" />' +
              '<span><strong>面集合</strong> (Polygon)</span>' +
            '</label>' +
            '<label style="display:flex;align-items:center;gap:6px;padding:8px 10px;border:1px solid var(--outline-variant);border-radius:6px;cursor:pointer;font-size:12px;background:var(--surface-container-low);">' +
              '<input type="radio" name="newLayerType" value="GeometryCollection" style="accent-color:var(--primary,#000);" />' +
              '<span><strong>几何集合</strong> (点/线混合)</span>' +
            '</label>' +
          '</div>' +
        '</div>' +
        '<div class="workspace-modal-actions">' +
          '<button type="button" class="workspace-modal-btn cancel" id="cancelNewLayerBtn">取消</button>' +
          '<button type="button" class="workspace-modal-btn primary" id="confirmNewLayerBtn">立即创建</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    function close() { overlay.remove(); }
    overlay.querySelector('#cancelNewLayerBtn').onclick = close;
    overlay.onclick = function(e) { if (e.target === overlay) close(); };

    var nameInput = overlay.querySelector('#newLayerNameInput');
    nameInput.focus();
    nameInput.select();

    overlay.querySelectorAll('input[name="newLayerType"]').forEach(function(r) {
      r.addEventListener('change', function() {
        var base = this.value === 'Point' ? '点集' : (this.value === 'LineString' ? '线集' : (this.value === 'Polygon' ? '面集' : '复合几何集'));
        nameInput.value = base + '_' + _getDateSuffix();
      });
    });

    overlay.querySelector('#confirmNewLayerBtn').onclick = function() {
      var name = nameInput.value.trim() || '未命名集合';
      var checkedRadio = overlay.querySelector('input[name="newLayerType"]:checked');
      var geomType = checkedRadio ? checkedRadio.value : 'Point';
      close();

      var newGj = {
        type: 'FeatureCollection',
        features: []
      };

      var layerId = 'col_' + Date.now().toString(36);
      addLayer({
        layer_id: layerId,
        filename: name,
        _rawName: name,
        geometry_type: geomType,
        geojson: newGj,
        source: '手动创建',
        color: nextColor()
      });

      if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
        window.GIS.toast.success('已创建图层「' + name + '」');
      }

      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
        window.GIS.chat.addMessage('已创建图层「' + name + '」，已自动开启连续绘制模式，直接在地图上点击即可添加要素', 'system', { pill: true });
      }

      // 自动绑定并启动地图连续绘制
      startAddingToLayer(layerId);
    };
  }

  /** 触发颜色选择器（复用已有逻辑） */
  function _triggerColorPicker(layerId) {
    var dot = document.querySelector('.layer-color-dot[data-id="' + layerId + '"]');
    if (dot) {
      var input = document.createElement('input');
      input.type = 'color';
      input.value = dot.dataset.color || '#1c1b1b';
      input.addEventListener('input', function() {
        var l = layerData.find(function(x) { return x.layer_id === layerId; });
        if (l) {
          l.color = this.value;
          dot.style.background = this.value;
          dot.dataset.color = this.value;
          if (GIS.state && GIS.state.getLayer(layerId)) {
            GIS.state.setStyle(layerId, { color: this.value, fillColor: this.value });
          } else if (GIS.map && GIS.map.setLayerColor) {
            GIS.map.setLayerColor(l._rawName || l.layer_id, this.value);
          }
        }
      });
      input.click();
    }
  }

  /** 触发重命名（复用已有逻辑） */
  function _triggerRename(layerId) {
    var nameEl = document.querySelector('.layer-name[data-id="' + layerId + '"]');
    if (!nameEl) return;
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;
    var oldName = layer.filename || '未命名';
    var oldRegisteredName = layer._registeredName || oldName;
    var oldMapName = layer._rawName || oldName;
    var oldRegistrationPromise = layer._registrationPromise;
    var cancelled = false;
    var input = document.createElement('input');
    input.type = 'text';
    input.value = oldName;
    input.className = 'layer-rename-input';
    input.style.cssText = 'width:100%;box-sizing:border-box;border:1px solid var(--ui-gray-400);border-radius:2px;padding:1px 4px;font-size:inherit;font-family:inherit;background:var(--ui-white);color:var(--ui-gray-900);';
    nameEl.textContent = '';
    nameEl.appendChild(input);
    input.focus();
    input.select();
    function commit() {
      if (cancelled) return;
      var val = input.value.trim() || oldName;
      if (val === oldName) {
        nameEl.textContent = oldName;
        return;
      }
      var exists = layerData.some(function(l) { return l !== layer && l.filename === val; });
      if (exists) {
        var suffix = 1;
        while (layerData.some(function(l) { return l !== layer && l.filename === val + '(' + suffix + ')'; })) { suffix++; }
        val = val + '(' + suffix + ')';
      }
      layer.filename = val;
      layer._rawName = val;
      nameEl.textContent = val;
      if (window.GIS.state && window.GIS.state.renameLayer) {
        window.GIS.state.renameLayer(layerId, val);
      }
      if (window.GIS.map && window.GIS.map.renameLayer) {
        window.GIS.map.renameLayer(oldMapName, val);
      }
      if (window.GIS.api && window.GIS.api.registerLayer && layer.geojson) {
        var nextRegistrationPromise = Promise.resolve(oldRegistrationPromise).catch(function() {}).then(function() {
          return _registerLayerForPanel(val, layer.geojson);
        });
        layer._registrationPromise = nextRegistrationPromise.then(function(registered) {
          if (registered && window.GIS.api.unregisterLayer && oldRegisteredName !== val) {
            return window.GIS.api.unregisterLayer(oldRegisteredName);
          }
          return registered;
        });
        layer._registrationPromise.then(function(registered) {
          if (registered) layer._registeredName = val;
        }).catch(function(error) {
          console.warn('[GIS Layers] 重命名后的旧注册项清理失败', oldRegisteredName, error);
        });
      }
    }
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', function(ke) {
      if (ke.key === 'Enter') { ke.preventDefault(); input.blur(); }
      if (ke.key === 'Escape') {
        ke.preventDefault();
        cancelled = true;
        nameEl.textContent = oldName;
      }
    });
  }
})();
