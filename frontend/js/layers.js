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
    bindActionEvents();
    bindDragEvents();
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
  function addLayer(layer, skipRegister) {
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
    if (!skipRegister && window.GIS.api && typeof window.GIS.api.registerLayer === 'function' && layer.geojson) {
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
            '<span class="download-dialog-radio"><svg viewBox="0 0 16 16" width="16" height="16"><circle cx="8" cy="8" r="5" fill="currentColor"/></svg></span>' +
            '<span class="download-dialog-label"><strong>GeoJSON</strong><span class="download-dialog-desc">标准地理数据格式，保留完整属性</span></span>' +
          '</label>' +
          '<label class="download-dialog-option" data-format="shp">' +
            '<span class="download-dialog-radio"></span>' +
            '<span class="download-dialog-label"><strong>Shapefile (.shp)</strong><span class="download-dialog-desc">兼容 ArcGIS/QGIS，含 .shp .shx .dbf .prj .cpg</span></span>' +
          '</label>' +
        '</div>' +
        '<div class="download-dialog-actions">' +
          '<button class="download-dialog-btn download-dialog-cancel">取消</button>' +
          '<button class="download-dialog-btn download-dialog-confirm">下载</button>' +
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
            if (GIS.map && GIS.map.setLayerColor) {
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
          '<button class="attr-btn" data-action="symbology" data-layer="' + layerId + '" title="符号化">' +
            '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="5" cy="5" r="2.5"/><circle cx="11" cy="5" r="3.5"/><circle cx="8" cy="11" r="2"/></svg>' +
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
      dataHtml += '<th style="width:28px;" title="定位">◎</th><th style="width:32px;"></th></tr></thead><tbody>';
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
    var tabInfo =
      '<div class="inspector-tab-content" id="tabInfo" style="display:block;">' +
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
        '<button class="inspector-tab active" data-tab="info">基础信息</button>' +
        '<button class="inspector-tab" data-tab="symb">符号系统</button>' +
        '<button class="inspector-tab" data-tab="attr">属性表</button>' +
      '</div>';

    var tabAttr =
      '<div class="inspector-tab-content" id="tabAttr" style="display:none;">' +
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
        if (delBtn) deleteAttrRow(layerId, parseInt(delBtn.dataset.idx, 10));
      });
    }

    // ===== 符号系统事件 =====
    _bindSymbEvents(layerId, features);

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

  // ---- 图层符号化 ----

  /** 存储每层的符号化配置 */
  var _symbologyConfig = {};

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
    });

    // 初始预览
    if (enableEl.checked) _updatePreview();
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

    _symbologyConfig[layerId] = { type: type, field: field, classes: classes, colorScheme: colorScheme, enabled: true, minSize: minSize || 3, maxSize: maxSize || 20 };

    if (type === 'unique') {
      _applyUniqueValues(layer, gj, features, field, scheme);
    } else if (type === 'graduated') {
      _applyGraduatedColors(layer, gj, features, field, classes, scheme);
    } else if (type === 'graduated-symbol') {
      _applyGraduatedSymbols(layer, gj, features, field, classes, scheme, minSize, maxSize);
    } else if (type === 'proportional') {
      _applyProportionalSymbols(layer, gj, features, field, minSize, maxSize);
    }
  }

  /** 获取色带颜色数组 */
  function _getColorScheme(name, count) {
    var palettes = {
      scheme: ['#1c1b1b','#e74c3c','#2ecc71','#3498db','#f39c12','#9b59b6','#1abc9c','#e67e22','#34495e','#16a085',
               '#c0392b','#27ae60','#2980b9','#8e44ad','#2c3e50','#d35400','#7f8c8d','#f1c40f','#00bcd4','#ff5722'],
      blues:   ['#f7fbff','#deebf7','#c6dbef','#9ecae1','#6baed6','#4292c6','#2171b5','#08519c','#08306b'],
      reds:    ['#fff5f0','#fee0d2','#fcbba1','#fc9272','#fb6a4a','#ef3b2c','#cb181d','#a50f15','#67000d'],
      greens:  ['#f7fcf5','#e5f5e0','#c7e9c0','#a1d99b','#74c476','#41ab5d','#238b45','#006d2c','#00441b'],
      purples: ['#fcfbfd','#efedf5','#dadaeb','#bcbddc','#9e9ac8','#807dba','#6a51a3','#54278f','#3f007d'],
      oranges: ['#fff5eb','#fee6ce','#fdd0a2','#fdae6b','#fd8d3c','#f16913','#d94801','#a63603','#7f2704'],
    };
    var colors = palettes[name] || palettes.scheme;
    if (count <= colors.length) return colors.slice(0, count);
    // 不够就重复
    var result = [];
    for (var i = 0; i < count; i++) result.push(colors[i % colors.length]);
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

  /** 获取色带颜色数组（别名，供预览用） */
  function _getSchemeColors(name, count) {
    return _getColorScheme(name, count);
  }

  /** 唯一值渲染 */
  function _applyUniqueValues(layer, gj, features, field, scheme) {
    var values = {};
    features.forEach(function(f, idx) {
      var v = String(f.properties ? f.properties[field] ?? '' : '');
      if (!values[v]) values[v] = [];
      values[v].push(idx);
    });
    var keys = Object.keys(values);
    var colorMap = {};
    keys.forEach(function(k, i) { colorMap[k] = scheme[i % scheme.length]; });

    var styleMap = {};
    features.forEach(function(f, idx) {
      var v = String(f.properties ? f.properties[field] ?? '' : '');
      styleMap[idx] = _styleForGeom(f, colorMap[v]);
    });

    _applyStyleToMap(layer, gj, styleMap);
    var defaultColor = scheme[keys.length % scheme.length] || '#1c1b1b';

    // 更新符号化信息
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      var info = '已应用唯一值符号化: ' + field + '（' + keys.length + ' 个类别）\n';
      keys.slice(0, 10).forEach(function(k) {
        info += '  ' + escapeHtml(k) + ' → ' + colorMap[k] + ' (' + values[k].length + ' 个)\n';
      });
      if (keys.length > 10) info += '  ... 还有 ' + (keys.length - 10) + ' 个类别';
      window.GIS.chat.addMessage(info, 'system');
    }
    layer.color = defaultColor;
  }

  /** 分级色彩渲染 */
  function _applyGraduatedColors(layer, gj, features, field, classes, scheme) {
    var values = features.map(function(f, idx) {
      return { idx: idx, val: parseFloat(f.properties ? f.properties[field] : 0) };
    }).filter(function(v) { return !isNaN(v.val); });
    if (!values.length) {
      if (window.GIS.chat) window.GIS.chat.addMessage('字段「' + field + '」无有效数值', 'system');
      return;
    }

    var sorted = values.map(function(v) { return v.val; }).sort(function(a, b) { return a - b; });
    var min = sorted[0], max = sorted[sorted.length - 1];
    if (min === max) {
      // 所有值相同，用单一颜色
      var styleMap = {};
      features.forEach(function(f, idx) { styleMap[idx] = _styleForGeom(f, scheme[0]); });
      _applyStyleToMap(layer, gj, styleMap);
      return;
    }

    var step = (max - min) / classes;
    var breaks = [];
    for (var i = 0; i <= classes; i++) breaks.push(min + step * i);

    var styleMap = {};
    features.forEach(function(f, idx) {
      var v = parseFloat(f.properties ? f.properties[field] : 0);
      if (isNaN(v)) v = min;
      var classIdx = 0;
      for (var j = 0; j < breaks.length - 1; j++) {
        if (v >= breaks[j] && (v < breaks[j + 1] || (j === breaks.length - 2 && v <= breaks[j + 1]))) {
          classIdx = j; break;
        }
      }
      var color = scheme[Math.min(classIdx, scheme.length - 1)];
      styleMap[idx] = _styleForGeom(f, color);
    });

    _applyStyleToMap(layer, gj, styleMap);
    layer.color = scheme[0];

    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      var info = '已应用分级色彩: ' + field + '（' + classes + ' 级）\n';
      for (var j = 0; j < classes && j < 10; j++) {
        info += '  ' + breaks[j].toFixed(2) + ' - ' + breaks[j + 1].toFixed(2) + ' → ' + scheme[Math.min(j, scheme.length - 1)] + '\n';
      }
      window.GIS.chat.addMessage(info, 'system');
    }
  }

  /** 分级符号渲染（点图层用不同半径，线图层用不同粗细） */
  function _applyGraduatedSymbols(layer, gj, features, field, classes, scheme, minSize, maxSize) {
    var isPoint = _isPointLayer(features);
    var values = features.map(function(f, idx) {
      return { idx: idx, val: parseFloat(f.properties ? f.properties[field] : 0) };
    }).filter(function(v) { return !isNaN(v.val); });
    if (!values.length) {
      if (window.GIS.chat) window.GIS.chat.addMessage('字段「' + field + '」无有效数值', 'system');
      return;
    }

    var sorted = values.map(function(v) { return v.val; }).sort(function(a, b) { return a - b; });
    var min = sorted[0], max = sorted[sorted.length - 1];
    if (min === max) {
      _applyStyleToMap(layer, gj, {});
      return;
    }

    var step = (max - min) / classes;
    var breaks = [];
    for (var i = 0; i <= classes; i++) breaks.push(min + step * i);

    if (minSize === undefined) minSize = isPoint ? 3 : 1;
    if (maxSize === undefined) maxSize = isPoint ? 12 : 5;

    var styleMap = {};
    features.forEach(function(f, idx) {
      var v = parseFloat(f.properties ? f.properties[field] : 0);
      if (isNaN(v)) v = min;
      var classIdx = 0;
      for (var j = 0; j < breaks.length - 1; j++) {
        if (v >= breaks[j] && (v < breaks[j + 1] || (j === breaks.length - 2 && v <= breaks[j + 1]))) {
          classIdx = j; break;
        }
      }
      var ratio = classIdx / (classes - 1);
      var size = minSize + ratio * (maxSize - minSize);
      var color = scheme[Math.min(classIdx, scheme.length - 1)];
      if (isPoint) {
        styleMap[idx] = { radius: Math.round(size), color: color, weight: 0, fillOpacity: 1 };
      } else {
        styleMap[idx] = _styleForGeom(f, color, null, { weight: Math.round(size) });
      }
    });

    _applyStyleToMap(layer, gj, styleMap);

    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      var info = '已应用分级符号: ' + field + '（' + classes + ' 级，大小 ' + minSize + '-' + maxSize + '）';
      window.GIS.chat.addMessage(info, 'system');
    }
  }

  /** 比例符号渲染（点半径与数值成比例） */
  function _applyProportionalSymbols(layer, gj, features, field, minSize, maxSize) {
    if (!_isPointLayer(features)) {
      if (window.GIS.chat) window.GIS.chat.addMessage('比例符号仅支持点图层', 'system');
      return;
    }
    var values = features.map(function(f, idx) {
      return { idx: idx, val: parseFloat(f.properties ? f.properties[field] : 0) };
    }).filter(function(v) { return !isNaN(v.val) && v.val > 0; });
    if (!values.length) {
      if (window.GIS.chat) window.GIS.chat.addMessage('字段「' + field + '」无有效正值', 'system');
      return;
    }

    var sorted = values.map(function(v) { return v.val; }).sort(function(a, b) { return a - b; });
    var min = sorted[0], max = sorted[sorted.length - 1];
    if (min === max) {
      _applyStyleToMap(layer, gj, {});
      return;
    }

    var styleMap = {};
    var minR = minSize || 3, maxR = maxSize || 20;
    features.forEach(function(f, idx) {
      var v = parseFloat(f.properties ? f.properties[field] : 0);
      if (isNaN(v) || v <= 0) v = min;
      var ratio = (v - min) / (max - min);
      var r = minR + ratio * (maxR - minR);
      styleMap[idx] = _styleForGeom(f, '#1c1b1b', null, { radius: Math.round(r) });
    });

    _applyStyleToMap(layer, gj, styleMap);

    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('已应用比例符号: ' + field + '（大小 ' + minR + '-' + maxR + 'px）', 'system');
    }
  }

  /** 将样式映射应用到地图图层 */
  function _applyStyleToMap(layer, gj, styleMap) {
    var name = layer._rawName || layer.layer_id;
    if (!GIS.map || !GIS.map.applySymbology) return;
    GIS.map.applySymbology(name, gj, styleMap);
  }

  /** 清除符号化，恢复默认样式 */
  function _clearSymbology(layerId) {
    delete _symbologyConfig[layerId];
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
  };
})();
