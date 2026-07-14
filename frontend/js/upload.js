/**
 * GIS AI WorkTable — 文件上传模块
 * 文件选择、格式校验、调用 API 上传
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;
  const ALLOWED_EXTENSIONS = ['.geojson', '.json', '.gpkg', '.kml', '.kmz', '.gpx', '.dxf', '.zip', '.csv'];

  let fileInput = null;

  function init() {
    fileInput = document.getElementById('fileInput');
    if (!fileInput) {
      console.warn('[GIS Upload] 未找到 #fileInput 元素');
      return;
    }

    // 绑定上传按钮：直接用 getElementById
    var btn1 = document.getElementById('uploadTrigger');
    var btn2 = document.getElementById('uploadTriggerBtn');
    if (btn1) btn1.addEventListener('click', function() { fileInput.click(); });
    else console.warn('[GIS Upload] 未找到 #uploadTrigger');
    if (btn2) btn2.addEventListener('click', function() { fileInput.click(); });
    else console.warn('[GIS Upload] 未找到 #uploadTriggerBtn');

    fileInput.addEventListener('change', function(e) {
      if (e.target.files.length > 0) handleFiles(e.target.files);
      fileInput.value = '';
    });

    // 拖拽上传
    document.body.addEventListener('dragover', function(e) { e.preventDefault(); });
    document.body.addEventListener('drop', function(e) {
      e.preventDefault();
      if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
    });

    console.log('[GIS Upload] 上传模块初始化完成');
  }

  // 文件格式校验
  function handleFiles(files) {
    Array.from(files).forEach(file => {
      const ext = '.' + file.name.split('.').pop().toLowerCase();
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        return showUploadToast('error', `不支持 ${ext} 格式`);
      }
      if (file.size > 300 * 1024 * 1024) {
        return showUploadToast('error', '文件超过 300MB 限制');
      }
      startUpload(file);
    });
  }


  async function startUpload(file) {
    showUploadToast('importing', file.name);

    // 可取消：每个文件独立 AbortController，防止并发上传互相覆盖
    var controller = new AbortController();
    _uploadAbortControllers.set(file.name, controller);
    var signal = controller.signal;

    try {
      const result = await GIS.api.upload(file, signal);

      // 后端返回了错误信息
      if (result.error) {
        return showUploadToast('error', result.error);
      }

      // ===== CSV 文件：保存后让 AI 处理 =====
      if (result.csv_info) {
        const info = result.csv_info;
        showUploadToast('success', `${info.filename} 已保存`);
        setTimeout(() => {
          if (GIS.chat && GIS.chat.sendMessage) {
            const msg = `读取 output/${info.filename}，识别坐标列，转成GeoJSON显示到地图`;
            GIS.chat.sendMessage(msg);
          }
        }, 500);
        return;
      }

      // ===== GeoJSON / SHP / GPKG / KML 等矢量文件上传 =====
      GIS.map.loadGeoJSON(result.geojson, result.name);

      const geojson = result.geojson;
      const type = geojson.type === 'FeatureCollection' && geojson.features.length > 0
        ? (geojson.features[0].geometry?.type || '未知')
        : (geojson.geometry?.type || '未知');
      GIS.layers.addLayer({
        layer_id: result.name + '_' + Date.now(),
        filename: result.name,
        geometry_type: type,
        crs: 'WGS-84',
        geojson: geojson,
        source: 'upload',
      });

      // 通知 AI 文件路径（隐藏消息，不显示在聊天框，但 AI 能读到）
      if (GIS.chat && GIS.chat.addMessage) {
        GIS.chat.addMessage(`[文件上传] ${result.name} → output/uploads/`, 'system', { hidden: true });
      }

      showUploadToast('success', result.name);
    } catch (err) {
      if (err.name === 'AbortError') return; // 用户取消，不显示错误
      showUploadToast('error', err.message);
    } finally {
      _uploadAbortControllers.delete(file.name);
    }
  }

  // ---- 上传状态气泡（显示在 AI 对话区，无头像，像 AI 消息样式） ----

  var _uploadMsgEl = null;
  var _uploadStatusTimer = null;
  var _uploadAbortControllers = new Map();
  var _currentFileName = '';

  function showUploadToast(status, msg) {
    if (_uploadStatusTimer) { clearTimeout(_uploadStatusTimer); _uploadStatusTimer = null; }

    var container = document.getElementById('chatMessages');
    if (!container) return;

    if (status === 'importing') {
      _currentFileName = msg || '文件';
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:center;max-width:100%;opacity:0;transition:opacity 0.2s;';

      var bubble = document.createElement('div');
      bubble.style.cssText = 'font-size:12px;color:var(--ui-gray-900);background:var(--message-bg-ai, var(--surface-container-low));padding:8px 14px;border-radius:10px;text-align:left;max-width:90%;';
      bubble.innerHTML =
        '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
          '<svg class="upload-msg-svg" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;">' +
            '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>' +
            '<polyline points="17 8 12 3 7 8"/>' +
            '<line x1="12" y1="3" x2="12" y2="15"/>' +
          '</svg>' +
          '<span style="font-weight:500;">导入中: ' + escapeHtml(_currentFileName) + '</span>' +
          '<button class="upload-cancel-btn" id="uploadCancelBtn" style="margin-left:auto;font-size:11px;padding:2px 10px;border:1px solid var(--ui-gray-300);border-radius:4px;background:none;cursor:pointer;color:var(--ui-gray-600);white-space:nowrap;">取消导入</button>' +
        '</div>';
      row.appendChild(bubble);
      container.appendChild(row);
      requestAnimationFrame(function() { row.style.opacity = '1'; });
      container.scrollTop = container.scrollHeight;

      _uploadMsgEl = row;

      var svgEl = row.querySelector('.upload-msg-svg');
      if (svgEl) svgEl.style.animation = 'upload-bounce 0.6s ease-in-out infinite alternate';

      var cancelBtn = row.querySelector('#uploadCancelBtn');
      if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
          var ctrl = _uploadAbortControllers.get(_currentFileName);
          if (ctrl) ctrl.abort();
          _uploadAbortControllers.delete(_currentFileName);
          var bubbleDiv = cancelBtn.closest('div[style]');
          if (bubbleDiv) {
            bubbleDiv.innerHTML = '<span style="color:var(--ui-gray-400);font-size:12px;">导入已取消</span>';
          }
          _uploadMsgEl = null;
        });
      }

    } else {
      var targetRow = _uploadMsgEl;
      if (!targetRow) {
        targetRow = document.createElement('div');
        targetRow.style.cssText = 'display:flex;justify-content:center;max-width:100%;opacity:0;transition:opacity 0.2s;';
        var bub = document.createElement('div');
        bub.style.cssText = 'font-size:12px;color:var(--ui-gray-900);background:var(--message-bg-ai, var(--surface-container-low));padding:8px 14px;border-radius:10px;text-align:left;max-width:90%;';
        targetRow.appendChild(bub);
        container.appendChild(targetRow);
        requestAnimationFrame(function() { targetRow.style.opacity = '1'; });
        container.scrollTop = container.scrollHeight;
        _uploadMsgEl = targetRow;
      }

      var contentDiv = targetRow.querySelector('div:last-child');
      if (!contentDiv) return;

      if (status === 'success') {
        contentDiv.innerHTML =
          '<span style="display:inline-flex;align-items:center;gap:6px;">' +
            '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#2e7d32" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;">' +
              '<polyline points="4 12 9 17 20 6"/>' +
            '</svg>' +
            '<span style="color:#2e7d32;">上传成功' + (msg ? ': ' + escapeHtml(msg) : '') + '</span>' +
          '</span>';
        _uploadStatusTimer = setTimeout(function() {
          if (_uploadMsgEl) { _uploadMsgEl.remove(); _uploadMsgEl = null; }
        }, 3000);
      } else if (status === 'error') {
        contentDiv.innerHTML =
          '<span style="display:inline-flex;align-items:center;gap:6px;">' +
            '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#d32f2f" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;">' +
              '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>' +
            '</svg>' +
            '<span style="color:#d32f2f;">上传失败' + (msg ? ': ' + escapeHtml(msg) : '') + '</span>' +
          '</span>';
        _uploadStatusTimer = setTimeout(function() {
          if (_uploadMsgEl) { _uploadMsgEl.remove(); _uploadMsgEl = null; }
        }, 5000);
      }
    }
  }

  function escapeHtml(str) {
    return window.GIS.utils ? window.GIS.utils.escapeHtml(str) : ('' + (str || ''));
  }

  // 打开文件选择对话框
  function openDialog() { if (fileInput) fileInput.click(); }

  GIS.upload = { init, openDialog, handleFiles, ALLOWED_EXTENSIONS };
})();
