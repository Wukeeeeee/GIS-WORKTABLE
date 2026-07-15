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

  function init() {
    tbody = document.getElementById('layerTbody');
    layersTable = document.getElementById('layersTable');
    layersEmpty = document.getElementById('layersEmpty');
    renderList();
    bindActionEvents();  // 用事件委托监听按钮点击
    bindDragEvents();    // 用事件委托监听拖拽排序
  }


  //渲染表格
  function renderList(data) {
    if (data) layerData = data;
    if (!tbody) return;

    if (layerData.length === 0) {
      // 空列表
      tbody.innerHTML = '';
      if (layersEmpty) layersEmpty.style.display = 'flex';
      if (layersTable) layersTable.style.display = 'none';
      return;
    }
    // 非空列表
    if (layersEmpty) layersEmpty.style.display = 'none';
    if (layersTable) layersTable.style.display = '';

    // 渲染列表
    tbody.innerHTML = layerData.map((layer, index) => `
      <tr draggable="true" data-index="${index}" data-id="${layer.layer_id || ''}">
        <td class="col-drag">
          <span class="drag-handle" draggable="true">
            <svg><use href="assets/icons.svg#icon-drag"/></svg>
          </span>
        </td>
        <td class="col-vis">
          <button class="layer-action-btn layer-vis-check" data-action="visibility" data-id="${layer.layer_id || ''}" title="显隐">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              ${layer.visible !== false
                ? '<rect x="3" y="3" width="18" height="18" rx="3" fill="var(--ui-gray-900)" stroke="var(--ui-gray-900)"/><polyline points="7 12 10 15 17 8" stroke="#fff" stroke-width="2.5"/>'
                : '<rect x="3" y="3" width="18" height="18" rx="3" fill="none" stroke="var(--ui-gray-300)"/>'}
            </svg>
          </button>
        </td>
        <td class="col-name">
          <span class="layer-color-dot" style="background:${layer.color || '#1c1b1b'}" data-color="${layer.color || '#1c1b1b'}" data-id="${layer.layer_id || ''}"></span>
          <span class="layer-source layer-source-${layer.source || 'upload'}">
            ${layer.source === 'ai'
              ? '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="#8B5CF6" stroke-width="2.5" stroke-linecap="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
              : '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>'}
          </span>
          <span class="layer-name" data-id="${layer.layer_id || ''}" title="双击重命名">${escapeHtml(layer.filename || '未命名')}</span>
        </td>
        <td class="col-type"><span class="layer-type">${escapeHtml(layer.geometry_type || '未知')}</span></td>
        <td class="col-actions">
          <div class="layer-actions">
            <button class="layer-action-btn" data-action="inspect" data-id="${layer.layer_id || ''}" title="检查图层">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
              </svg>
            </button>
            <button class="layer-action-btn" data-action="analyze" data-id="${layer.layer_id || ''}" title="发送给AI分析">
              <svg><use href="assets/icons.svg#icon-ai-send"/></svg>
            </button>
            <button class="layer-action-btn" data-action="download" data-id="${layer.layer_id || ''}" title="下载">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </button>
            <button class="layer-action-btn btn-danger" data-action="delete" data-id="${layer.layer_id || ''}" title="删除">
              <svg><use href="assets/icons.svg#icon-delete"/></svg>
            </button>
          </div>
        </td>
      </tr>
    `).join('');
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

  // 添加图层：加入列表 + 渲染
  function addLayer(layer) {
    const colors = ['#1c1b1b','#e74c3c','#2ecc71','#3498db','#f39c12','#9b59b6','#1abc9c','#e67e22'];
    const color = layer.color || colors[layerData.length % colors.length];
    // 重名自动加 (1) (2)
    var name = layer.filename || '未命名';
    var _rawName = layer.filename || layer.layer_id || '未命名'; // 保留原始名称用于地图模块查找
    if (layerData.some(function(l) { return l.filename === name; })) {
      var suffix = 1;
      while (layerData.some(function(l) { return l.filename === name + '(' + suffix + ')'; })) { suffix++; }
      name = name + '(' + suffix + ')';
    }
    layerData.push({ ...layer, filename: name, _rawName, visible: true, color });
    renderList();
    _syncLayerOrder();
    if (window.GIS.api && typeof window.GIS.api.registerLayer === 'function' && layer.geojson) {
      window.GIS.api.registerLayer(name, layer.geojson);
    }
  }

  // 删除图层：从列表移除 + 从地图清除
  function removeLayer(layerId) {
    const target = layerData.find(l => l.layer_id === layerId);
    const mapName = target ? (target._rawName || target.layer_id) : null;
    layerData = layerData.filter(l => l.layer_id !== layerId);
    renderList();
    if (mapName && GIS.map && GIS.map.removeLayer) {
      GIS.map.removeLayer(mapName);
    }
    if (target) {
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
        window.GIS.chat.addMessage('已删除图层: ' + (target.filename || '图层'), 'system');
      }
      if (window.GIS.api && typeof window.GIS.api.unregisterLayer === 'function') {
        window.GIS.api.unregisterLayer(target.filename || target.layer_id || '');
      }
    }
  }

  // 切换图层显隐
  function toggleVisibility(layerId) {
    const layer = layerData.find(l => l.layer_id === layerId);
    if (layer) {
      layer.visible = !layer.visible;
      renderList();
      if (GIS.map && GIS.map.setLayerVisible) {
        GIS.map.setLayerVisible(layer._rawName || layer.layer_id, layer.visible);
        // 显示图层后 Leaflet 会把它放到最上层，重新同步叠放顺序
        if (layer.visible) _syncLayerOrder();
      }
    }
  }

  // 下载图层（导出 GeoJSON）
  function downloadLayer(layerId) {
    const layer = layerData.find(l => l.layer_id === layerId);
    if (!layer) return;
    var geojson = layer.geojson;
    // 如果没有独立 geojson，尝试从地图模块拿
    if (!geojson && GIS.map && GIS.map.getGeoJSON) {
      geojson = GIS.map.getGeoJSON(layer._rawName || layer.layer_id);
    }
    if (!geojson) {
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') window.GIS.chat.addMessage('无数据可下载', 'system');
      return;
    }
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

  function bindDragEvents() {
    if (!tbody) return;
    let dragSrcIndex = null;

    // 用事件委托，不怕 renderList 重绘丢失绑定
    tbody.addEventListener('dragstart', (e) => {
      const tr = e.target.closest('tr[draggable]');
      if (!tr) return;
      // 只能通过拖拽手柄拖动
      if (!e.target.closest('.drag-handle')) { e.preventDefault(); return; }
      dragSrcIndex = parseInt(tr.dataset.index, 10);
      tr.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', tr.dataset.index); // 浏览器要求必须setData
    });

    tbody.addEventListener('dragend', () => {
      dragSrcIndex = null;
      tbody.querySelectorAll('tr').forEach(r => r.classList.remove('dragging', 'drag-over'));
    });

    tbody.addEventListener('dragover', (e) => {
      e.preventDefault();
      const tr = e.target.closest('tr[draggable]');
      if (!tr) return;
      e.dataTransfer.dropEffect = 'move';
      tr.classList.add('drag-over');
    });

    tbody.addEventListener('dragleave', (e) => {
      const tr = e.target.closest('tr[draggable]');
      if (!tr) return;
      // 只有真正离开行时才移除样式（避免子元素冒泡干扰）
      if (!tr.contains(e.relatedTarget)) {
        tr.classList.remove('drag-over');
      }
    });

    tbody.addEventListener('drop', (e) => {
      e.preventDefault();
      const tr = e.target.closest('tr[draggable]');
      if (!tr) return;
      tr.classList.remove('drag-over');
      const target = parseInt(tr.dataset.index, 10);
      if (dragSrcIndex === null || dragSrcIndex === target) return;
      const [moved] = layerData.splice(dragSrcIndex, 1);
      layerData.splice(target, 0, moved);
      renderList();
      dragSrcIndex = null;
      // 同步地图叠放顺序
      _syncLayerOrder();
    });
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
      // 颜色点点击 → 弹出颜色选择器
      const dot = e.target.closest('.layer-color-dot');
      if (dot) {
        const id = dot.dataset.id;
        const input = document.createElement('input');
        input.type = 'color';
        input.value = dot.dataset.color || '#1c1b1b';
        input.addEventListener('input', function() {
          const layer = layerData.find(l => l.layer_id === id);
          if (layer) {
            layer.color = this.value;
            dot.style.background = this.value;
            dot.dataset.color = this.value;
            if (GIS.map && GIS.map.setLayerColor) {
              GIS.map.setLayerColor(layer._rawName || layer.layer_id, this.value);
            }
            // 改颜色后如果原来隐藏就继续保持隐藏
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
    });

    // 双击图层名重命名
    tbody.addEventListener('dblclick', function(e) {
      var nameEl = e.target.closest('.layer-name');
      if (!nameEl) return;
      var id = nameEl.dataset.id;
      if (!id) return;
      var layer = layerData.find(function(l) { return l.layer_id === id; });
      if (!layer) return;

      var oldName = layer.filename || '未命名';
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
        var val = input.value.trim() || oldName;
        // 检查重名
        var exists = layerData.some(function(l) { return l !== layer && l.filename === val; });
        if (exists) {
          var suffix = 1;
          while (layerData.some(function(l) { return l !== layer && l.filename === val + '(' + suffix + ')'; })) { suffix++; }
          val = val + '(' + suffix + ')';
        }
        layer.filename = val;
        nameEl.textContent = val;
        nameEl.title = '双击重命名';
      }

      input.addEventListener('blur', commit);
      input.addEventListener('keydown', function(ke) {
        if (ke.key === 'Enter') { ke.preventDefault(); input.blur(); }
        if (ke.key === 'Escape') { ke.preventDefault(); nameEl.textContent = oldName; }
      });
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
  async function showLayerInspector(layerId) {
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
      ? '<span style="color:#2e7d32;font-weight:600;">✓</span>'
      : '<span style="color:#d32f2f;font-weight:600;">?</span>';

    var attrHtml = '';
    var attrFields = remote.attr_fields || local.attrFields || {};
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

    var panel = document.getElementById('layerInspector');
    var body = document.getElementById('inspectorBody');
    var title = document.getElementById('inspectorTitle');
    if (!panel || !body) return;

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
            '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13 5v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1h7l2 2z"/><path d="M5 11h6"/><path d="M5 8h6"/><path d="M5 5h2"/></svg>' +
            '保存' +
          '</button>' +
          '<button class="attr-btn" data-action="add-row" data-layer="' + layerId + '" title="添加行">' +
            '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><line x1="8" y1="3" x2="8" y2="13"/><line x1="3" y1="8" x2="13" y2="8"/></svg>' +
            '行' +
          '</button>' +
          '<button class="attr-btn" data-action="toggle-filter" data-layer="' + layerId + '" title="筛选">' +
            '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 2h12l-5 6.5V14l-2-1V8.5L2 2z"/></svg>' +
            '筛选' +
          '</button>' +
          '<button class="attr-btn" data-action="export-csv" data-layer="' + layerId + '" title="导出 CSV">' +
            '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1v10"/><path d="M4 7l4 4 4-4"/><path d="M2 13h12"/></svg>' +
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
      displayKeys.forEach(function(k) { dataHtml += '<th>' + escapeHtml(VIRTUAL_DISPLAY[k] || k) + '</th>'; });
      dataHtml += '<th style="width:32px;"></th></tr></thead><tbody>';
      features.forEach(function(f, i) {
        var props = f.properties || {};
        dataHtml += '<tr data-idx="' + i + '">';
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
          var readonlyAttr = isVirtual ? ' readonly class="attr-cell attr-cell-readonly"' : ' class="attr-cell"';
          dataHtml += '<td><input' + readonlyAttr + ' data-field="' + escapeHtml(k) + '" value="' + escapeHtml(cellValue) + '" /></td>';
        });
        dataHtml += '<td><button class="attr-del-btn" data-idx="' + i + '" title="删除此行">×</button></td>';
        dataHtml += '</tr>';
      });
      dataHtml += '</tbody></table></div>';
    } else if (features.length > 0) {
      dataHtml = '<div class="inspector-section"><div class="inspector-section-title">属性数据</div><span style="color:var(--ui-gray-300);font-size:var(--fs-12);">无属性字段</span></div>';
    }

    body.innerHTML =
      '<div class="inspector-section">' +
        '<div class="inspector-row"><span class="inspector-label">要素数</span><span class="inspector-value">' + (remote.feature_count ?? local.featureCount) + '</span></div>' +
        '<div class="inspector-row"><span class="inspector-label">几何类型</span><span class="inspector-value">' + escapeHtml(remote.geometry_type || local.geometryType) + '</span></div>' +
        '<div class="inspector-row"><span class="inspector-label">来源</span><span class="inspector-value">' + escapeHtml(layer.source || '未知') + '</span></div>' +
        '<div class="inspector-row"><span class="inspector-label">CRS</span><span class="inspector-value">' + crsBadge + ' ' + escapeHtml(crsStr) + '</span></div>' +
        '<div class="inspector-row"><span class="inspector-label">边界 (minX, minY, maxX, maxY)</span><span class="inspector-value" style="font-family:var(--font-mono);font-size:var(--fs-11);">' + escapeHtml(bboxStr) + '</span></div>' +
        '<div class="inspector-row"><span class="inspector-label">空几何</span><span class="inspector-value">' + (remote.null_geom_count ?? local.nullGeom) + '</span></div>' +
        '<div class="inspector-row"><span class="inspector-label">无效几何</span><span class="inspector-value">' + invalidCount + '</span></div>' +
      '</div>' +
      '<div class="inspector-section">' +
        '<div class="inspector-section-title">属性字段 (' + attrKeys.length + ')</div>' +
        attrHtml +
      '</div>' +
      '<div class="inspector-section" id="attrSection">' +
        dataHtml +
      '</div>';

    // 绑定属性表事件
    var attrSection = document.getElementById('attrSection');
    if (attrSection) {
      // 保存
      attrSection.querySelector('[data-action="save-attrs"]')?.addEventListener('click', function() {
        saveAttrChanges(layerId, attrKeys);
      });
      // 添加行
      attrSection.querySelector('[data-action="add-row"]')?.addEventListener('click', function() {
        addAttrRow(layerId, attrKeys);
      });
      // 切换筛选栏
      attrSection.querySelector('[data-action="toggle-filter"]')?.addEventListener('click', function() {
        var bar = document.getElementById('attrFilterBar');
        if (bar) bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
      });
      // CSV 导出
      attrSection.querySelector('[data-action="export-csv"]')?.addEventListener('click', function() {
        exportAttrCSV(layerId);
      });
      // 筛选按钮
      document.getElementById('attrFilterApply')?.addEventListener('click', function() {
        applyFilter(layerId);
      });
      document.getElementById('attrFilterClear')?.addEventListener('click', function() {
        clearFilter(layerId);
      });
      document.getElementById('attrFilterExport')?.addEventListener('click', function() {
        exportFilteredLayer(layerId);
      });
      // 删除行（事件委托）
      attrSection.querySelector('.inspector-data-wrap')?.addEventListener('click', function(e) {
        var btn = e.target.closest('.attr-del-btn');
        if (btn) deleteAttrRow(layerId, parseInt(btn.dataset.idx, 10));
      });
    }

    // 初始化列宽拖拽
    _enableColumnResize('attrDataTable');

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
      var idx = parseInt(row.dataset.idx, 10);
      if (isNaN(idx) || idx >= features.length) return;
      var inputs = row.querySelectorAll('.attr-cell');
      var allEmpty = true;
      inputs.forEach(function(inp) {
        if (inp.readOnly) return; // 跳过只读列（坐标/几何信息）
        var field = inp.dataset.field;
        var val = inp.value;
        if (fillVal && val === '') val = fillVal;
        features[idx].properties[field] = val;
        if (val !== '') allEmpty = false;
      });
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
      showLayerInspector(layerId);
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
    attrKeys.forEach(function(k) { props[k] = fillVal; });

    var newFeat = { type: 'Feature', geometry: null, properties: props };

    // 新行默认取第一个要素的几何（让新行能显示在地图上）
    if (features.length > 0 && features[0].geometry) {
      var src = features[0].geometry;
      if (src.type === 'Point') {
        newFeat.geometry = { type: 'Point', coordinates: [src.coordinates[0], src.coordinates[1]] };
      } else {
        newFeat.geometry = JSON.parse(JSON.stringify(src));
      }
    }

    features.push(newFeat);

    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (layer && GIS.map && GIS.map.loadGeoJSON) {
      GIS.map.loadGeoJSON(gj, layer._rawName || layer.layer_id, { color: layer.color });
      _syncLayerOrder();
    }
    showLayerInspector(layerId);
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
    showLayerInspector(layerId);
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

  GIS.layers = {
    init, renderList, addLayer, removeLayer, toggleVisibility, downloadLayer,
    analyzeLayer, showLayerInspector, closeInspector, exportAttrCSV,
    syncLayerOrder: _syncLayerOrder,
    getLayers: () => [...layerData],
  };
})();
