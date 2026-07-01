/**
 * GIS AI WorkTable — 文件上传模块
 * 文件选择、格式校验、调用 API 上传
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;
  const ALLOWED_EXTENSIONS = ['.geojson', '.json', '.shp', '.gpkg', '.kml', '.csv'];

  let fileInput = null;

  function init() {
    fileInput = document.getElementById('fileInput');

    // 绑定所有上传触发按钮
    document.querySelectorAll('[id="uploadTrigger"], [id="uploadTriggerBtn"]').forEach(btn => {
      if (btn && fileInput) btn.addEventListener('click', () => fileInput.click());
    });

    if (fileInput) {
      fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleFiles(e.target.files);
        fileInput.value = '';
      });
    }

    // 拖拽上传
    document.body.addEventListener('dragover', (e) => { e.preventDefault(); });
    document.body.addEventListener('drop', (e) => {
      e.preventDefault();
      if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
    });
  }

  function handleFiles(files) {
    Array.from(files).forEach(file => {
      const ext = '.' + file.name.split('.').pop().toLowerCase();
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        return notify(`不支持 ${ext} 格式`, 'error');
      }
      if (file.size > 300 * 1024 * 1024) {
        return notify('文件超过 300MB 限制', 'error');
      }
      startUpload(file);
    });
  }

  async function startUpload(file) {
    // TODO: const result = await GIS.api.upload(file, onProgress)
    // GIS.layers.addLayer(result)
    // GIS.map.loadGeoJSON(result.geojson, result.layer_id)
    notify(`待接入后端后实现上传: ${file.name}`, 'info');
  }

  function notify(message, type = 'info') {
    if (GIS.chat && GIS.chat.addMessage) {
      const icon = type === 'success' ? '✅ ' : type === 'error' ? '❌ ' : 'ℹ️ ';
      GIS.chat.addMessage(icon + message, 'system');
    }
  }

  function openDialog() { if (fileInput) fileInput.click(); }

  GIS.upload = { init, openDialog, handleFiles, ALLOWED_EXTENSIONS };
})();
