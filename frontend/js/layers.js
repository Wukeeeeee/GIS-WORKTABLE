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

  function renderList(data) {
    if (data) layerData = data;
    if (!tbody) return;

    if (layerData.length === 0) {
      tbody.innerHTML = '';
      if (layersEmpty) layersEmpty.style.display = 'flex';
      if (layersTable) layersTable.style.display = 'none';
      return;
    }
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
              <svg><use href="assets/icons.svg#icon-${layer.visible !== false ? 'visibility' : 'visibility-off'}"/></svg>
            </button>
            <button class="layer-action-btn btn-danger" data-action="delete" data-id="${layer.layer_id || ''}" title="删除">
              <svg><use href="assets/icons.svg#icon-delete"/></svg>
            </button>
          </div>
        </td>
      </tr>
    `).join('');

    bindDragEvents();
    bindActionEvents();
  }

  function addLayer(layer) {
    const colors = ['#1c1b1b','#e74c3c','#2ecc71','#3498db','#f39c12','#9b59b6','#1abc9c','#e67e22'];
    const color = layer.color || colors[layerData.length % colors.length];
    layerData.push({ ...layer, visible: true, color });
    renderList();
  }

  function removeLayer(layerId) {
    layerData = layerData.filter(l => l.layer_id !== layerId);
    renderList();
    // GIS.map.clearLayers(layerId);
  }

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
          }
        });
        input.click();
        return;
      }

      const btn = e.target.closest('.layer-action-btn');
      if (!btn) return;
      const action = btn.dataset.action;
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
