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

    tbody.innerHTML = layerData.map((layer, index) => `
      <tr draggable="true" data-index="${index}" data-id="${layer.layer_id || ''}">
        <td>
          <span class="drag-handle" draggable="true">
            <svg><use href="assets/icons.svg#icon-drag"/></svg>
          </span>
        </td>
        <td>
          <span class="layer-color-dot" style="background:${layer.color || '#1c1b1b'}" data-id="${layer.layer_id || ''}"></span>
          <span class="layer-name">${escapeHtml(layer.filename || '未命名')}</span>
        </td>
        <td><span class="layer-type">${escapeHtml(layer.geometry_type || '未知')}</span></td>
        <td>
          <div class="layer-actions">
            <button class="layer-action-btn" data-action="visibility" data-id="${layer.layer_id || ''}" title="显隐">
              ${layer.visible !== false ? '👁' : '🚫'}
            </button>
            <button class="layer-action-btn btn-danger" data-action="delete" data-id="${layer.layer_id || ''}" title="删除">
              <svg><use href="assets/icons.svg#icon-delete"/></svg>
            </button>
          </div>
        </td>
      </tr>
    `).join('');

    // 拖拽排序
    bindDragEvents();
    // 显隐/删除按钮事件
    bindActionEvents();
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
    // 更新列表数据，将指定的图层删除
    layerData = layerData.filter(l => l.layer_id !== layerId);
    renderList();
    if (GIS.map && GIS.map.clearLayers) {
      GIS.map.clearLayers(layerId);  // 同时从地图上移除
    }
  }

  // 切换图层显隐
  function toggleVisibility(layerId) {
    const layer = layerData.find(l => l.layer_id === layerId);
    if (layer) {
      layer.visible = !layer.visible;
      renderList();
      if (GIS.map && GIS.map.setLayerVisible) {
        GIS.map.setLayerVisible(layerId, layer.visible);
      }
    }
  }

  function bindDragEvents() {
    if (!tbody) return;
    let dragSrcIndex = null;

    tbody.querySelectorAll('tr[draggable]').forEach(tr => {
      tr.addEventListener('dragstart', (e) => {
        dragSrcIndex = parseInt(tr.dataset.index, 10);
        tr.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        if (!e.target.closest('.drag-handle')) e.preventDefault();
      });
      tr.addEventListener('dragend', () => {
        tr.classList.remove('dragging');
        tbody.querySelectorAll('tr').forEach(r => r.classList.remove('drag-over'));
      });
      tr.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        tr.classList.add('drag-over');
      });
      tr.addEventListener('dragleave', () => { tr.classList.remove('drag-over'); });
      tr.addEventListener('drop', (e) => {
        e.preventDefault();
        tr.classList.remove('drag-over');
        const target = parseInt(tr.dataset.index, 10);
        if (dragSrcIndex === null || dragSrcIndex === target) return;
        const [moved] = layerData.splice(dragSrcIndex, 1);
        layerData.splice(target, 0, moved);
        renderList();
        dragSrcIndex = null;
      });
    });
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
              GIS.map.setLayerColor(id, this.value);
            }
            // 改颜色后如果原来隐藏就继续保持隐藏
            if (!layer.visible && GIS.map && GIS.map.setLayerVisible) {
              GIS.map.setLayerVisible(id, false);
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
    });
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  GIS.layers = {
    init, renderList, addLayer, removeLayer, toggleVisibility,
    getLayers: () => [...layerData],
  };
})();
