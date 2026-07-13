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
          <span class="layer-color-dot" style="background:${layer.color || '#1c1b1b'}" data-id="${layer.layer_id || ''}"></span>
          <span class="layer-source layer-source-${layer.source || 'upload'}">
            ${layer.source === 'ai'
              ? '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
              : '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>'}
          </span>
          <span class="layer-name">${escapeHtml(layer.filename || '未命名')}</span>
        </td>
        <td class="col-type"><span class="layer-type">${escapeHtml(layer.geometry_type || '未知')}</span></td>
        <td class="col-actions">
          <div class="layer-actions">
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

  // 添加图层：加入列表 + 渲染
  function addLayer(layer) {
    //随机取一个颜色
    const colors = ['#1c1b1b','#e74c3c','#2ecc71','#3498db','#f39c12','#9b59b6','#1abc9c','#e67e22'];
    // 保证不同的图层有不同的颜色
    const color = layer.color || colors[layerData.length % colors.length];
    //记录图层的颜色数据
    layerData.push({ ...layer, visible: true, color });
    // 渲染列表
    renderList();
  }

  // 删除图层：从列表移除 + 从地图清除
  function removeLayer(layerId) {
    // 先找到要删的图层，拿到它的名称（地图模块是按文件名存的）
    const target = layerData.find(l => l.layer_id === layerId);
    const mapName = target ? (target.filename || target.layer_id) : null;
    // 更新列表数据，将指定的图层删除
    layerData = layerData.filter(l => l.layer_id !== layerId);
    renderList();
    if (mapName && GIS.map && GIS.map.removeLayer) {
      GIS.map.removeLayer(mapName);  // 传正确的文件名，不是 layerId
    }
    // 删除提示
    if (target && window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('已删除图层: ' + (target.filename || '图层'), 'system');
    }
  }

  // 切换图层显隐
  function toggleVisibility(layerId) {
    const layer = layerData.find(l => l.layer_id === layerId);
    if (layer) {
      layer.visible = !layer.visible;
      renderList();
      if (GIS.map && GIS.map.setLayerVisible) {
        GIS.map.setLayerVisible(layer.filename || layer.layer_id, layer.visible);
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
      geojson = GIS.map.getGeoJSON(layer.filename || layer.layer_id);
    }
    if (!geojson) {
      if (typeof addMessage === 'function') addMessage('无数据可下载', 'system');
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
      // 更新地图图层的叠放顺序
      if (GIS.map && GIS.map.getLayer) {
        for (let i = layerData.length - 1; i >= 0; i--) {
          const layer = layerData[i];
          const leafletLayer = GIS.map.getLayer(layer.filename || layer.layer_id);
          if (leafletLayer) leafletLayer.bringToFront();
        }
      }
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

  /** 将图层发送给 AI 分析 */
  function analyzeLayer(layerId) {
    var layer = layerData.find(function(l) { return l.layer_id === layerId; });
    if (!layer) return;
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('正在准备图层数据发送给 AI...', 'system');
    }
    var geojson = layer.geojson;
    if (!geojson && GIS.map && GIS.map.getGeoJSON) {
      geojson = GIS.map.getGeoJSON(layer.filename || layer.layer_id);
    }
    if (!geojson) {
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
        window.GIS.chat.addMessage('该图层无可用数据', 'system');
      }
      return;
    }
    var center = getGeoJSONCenter(geojson);
    var coordsStr = center ? center.lat.toFixed(6) + ', ' + center.lng.toFixed(6) : '未知';
    var msg = '我会分析以下图层的地理信息并向地图添加结果标记。\n\n';
    msg += '**位置信息**\n';
    msg += '- 坐标: ' + coordsStr + '\n';
    msg += '- 图层名称: ' + (layer.filename || '未命名') + '\n';
    msg += '- 几何类型: ' + (layer.geometry_type || '未知') + '\n\n';
    msg += '请完成以下任务：\n';
    msg += '1. 先搜索确定这个位置属于哪个省/市/区/县\n';
    msg += '2. 查询附近的地理特征（山脉、河流、湖泊、地形等）\n';
    msg += '3. 查询该区域的气候类型、典型海拔、植被等地理信息\n';
    msg += '4. 最后用 execute_python 在地图上该位置加一个点标记，只加一个点\n';
    msg += '5. 用 markdown 表格回复\n\n';
    msg += '**GeoJSON 数据**\n```json\n' + JSON.stringify(geojson, null, 2) + '\n```';
    if (window.GIS.chat && typeof window.GIS.chat.send === 'function') {
      window.GIS.chat.send(msg, { displayText: '分析图层: ' + (layer.filename || '图层') });
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
        input.value = dot.style.backgroundColor || '#1c1b1b';
        input.addEventListener('input', function() {
          const layer = layerData.find(l => l.layer_id === id);
          if (layer) {
            layer.color = this.value;
            dot.style.background = this.value;
            if (GIS.map && GIS.map.setLayerColor) {
              GIS.map.setLayerColor(layer.filename || layer.layer_id, this.value);
            }
            // 改颜色后如果原来隐藏就继续保持隐藏
            if (!layer.visible && GIS.map && GIS.map.setLayerVisible) {
              GIS.map.setLayerVisible(layer.filename || layer.layer_id, false);
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
    });
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  GIS.layers = {
    init, renderList, addLayer, removeLayer, toggleVisibility, downloadLayer, analyzeLayer,
    getLayers: () => [...layerData],
  };
})();
