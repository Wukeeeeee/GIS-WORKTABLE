/**
 * GIS AI WorkTable — 文件上传模块
 * 文件选择、格式校验、调用 API 上传
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;
  function tr(key, fallback) { return GIS.i18n ? GIS.i18n.t(key, fallback) : fallback; }
  const ALLOWED_EXTENSIONS = ['.geojson', '.json', '.gpkg', '.kml', '.kmz', '.gpx', '.dxf', '.zip', '.shp', '.csv', '.tif', '.tiff', '.pmtiles', '.parquet', '.geoparquet', '.fgb'];

  let fileInput = null;
  let initialized = false;
  let fileQueue = Promise.resolve();

  function init() {
    if (initialized) return;
    fileInput = document.getElementById('fileInput');
    if (!fileInput) {
      console.warn('[GIS Upload] 未找到 #fileInput 元素');
      return;
    }
    initialized = true;

    // 绑定上传按钮：直接用 getElementById
    var btn1 = document.getElementById('uploadTrigger');
    var btn2 = document.getElementById('uploadTriggerBtn');
    if (btn1) btn1.addEventListener('click', function() { fileInput.click(); });
    else console.warn('[GIS Upload] 未找到 #uploadTrigger');
    if (btn2) btn2.addEventListener('click', function() { fileInput.click(); });
    else console.warn('[GIS Upload] 未找到 #uploadTriggerBtn');

    fileInput.addEventListener('change', function(e) {
      var files = Array.from(e.target.files || []);
      fileInput.value = '';
      return handleFiles(files);
    });

    // 拖拽上传
    document.body.addEventListener('dragover', function(e) { e.preventDefault(); });
    document.body.addEventListener('drop', function(e) {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files) return handleFiles(e.dataTransfer.files);
    });

    console.log('[GIS Upload] 上传模块初始化完成');
  }

  // 内容嗅探：无扩展名时检测 KML / GPX / GeoJSON
  async function sniffFormat(file) {
    try {
      var header = await readFileHead(file, 512);
      if (header.includes('<kml') || header.includes('earth.google.com/kml'))
        return '.kml';
      if (header.includes('<gpx') || header.includes('topografix.com/GPX'))
        return '.gpx';
      if (header.trim().startsWith('{') && header.includes('"type"'))
        return '.geojson';
    } catch (_) {}
    return null;
  }

  function readFileHead(file, bytes) {
    return new Promise(function (resolve, reject) {
      var blob = file.slice(0, bytes);
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = reject;
      reader.onabort = reject;
      reader.readAsText(blob);
    });
  }

  function _parseCsvPreview(content) {
    var text = String(content || '').replace(/^\uFEFF/, '');
    var rows = [];
    var row = [];
    var field = '';
    var quoted = false;
    var rowStarted = false;
    for (var i = 0; i < text.length; i++) {
      var char = text[i];
      if (quoted) {
        rowStarted = true;
        if (char === '"' && text[i + 1] === '"') {
          field += '"';
          i++;
        } else if (char === '"') {
          quoted = false;
        } else {
          field += char;
        }
      } else if (char === '"' && field === '') {
        quoted = true;
        rowStarted = true;
      } else if (char === ',') {
        row.push(field);
        field = '';
        rowStarted = true;
      } else if (char === '\n' || char === '\r') {
        if (char === '\r' && text[i + 1] === '\n') i++;
        row.push(field);
        field = '';
        if (rowStarted) rows.push(row);
        if (rows.length >= 4) return rows;
        row = [];
        rowStarted = false;
      } else {
        field += char;
        rowStarted = true;
      }
    }
    row.push(field);
    if (rowStarted) rows.push(row);
    return rows;
  }

  // 文件格式校验
  function handleFiles(files) {
    var batch = Array.from(files || []);
    var pending = fileQueue.then(async function() {
    for (var file of batch) {
      try {
      if (file.size === 0) {
        showUploadToast('error', file.name + ': 文件为空，请选择包含数据的文件');
        continue;
      }
      var parts = file.name.split('.');
      var ext;
      if (parts.length > 1 && file.name.lastIndexOf('.') > 0 && parts[parts.length - 1]) {
        ext = '.' + parts.pop().toLowerCase();
      } else {
        // 无扩展名 → 嗅探内容
        var sniffed = await sniffFormat(file);
        if (!sniffed) {
          showUploadToast('error', file.name + ': 无法识别文件格式，请添加 .kml/.gpx/.geojson 等扩展名');
          continue;
        }
        ext = sniffed;
        file = new File([file], file.name.replace(/\.$/, '') + ext, { type: file.type, lastModified: file.lastModified });
      }
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        showUploadToast('error', file.name + ': 不支持 ' + ext + ' 格式');
        continue;
      }
      // Shapefile 是多个文件的组合（.shp/.dbf/.shx/.prj），请打包为 ZIP 上传
      if (ext === '.shp') {
        showUploadToast('error', file.name + ': Shapefile 需要配套文件（.shp/.dbf/.shx/.prj），请打包为 ZIP 后上传');
        continue;
      }
      var maxMB = ['.csv', '.geojson', '.json'].includes(ext) ? 64 : 300;
      if (file.size > maxMB * 1024 * 1024) {
        showUploadToast('error', file.name + ': 文件超过 ' + maxMB + 'MB 限制');
        continue;
      }
      // 数据预览：CSV/GeoJSON 上传前显示表头
      if (ext === '.csv' || ext === '.geojson' || ext === '.json') {
        var confirmed = await _showPreviewDialog(file, ext);
        if (!confirmed) continue;
      }
      await startUpload(file);
      } catch (error) {
        showUploadToast('error', file.name + ': ' + (error.message || '文件读取失败'));
      }
    }
    });
    fileQueue = pending.catch(function(error) { console.warn('[GIS Upload] 上传队列失败', error); });
    return pending;
  }


  /** 上传前预览 CSV/GeoJSON 文件头 */
  function _showPreviewDialog(file, ext) {
    return new Promise(function(resolve) {
      function render(html) {
        var overlay = document.createElement('div');
        overlay.className = 'preview-dialog-overlay';
        overlay.innerHTML = html;
        document.body.appendChild(overlay);
        var settled = false;
        function close(confirmed) {
          if (settled) return;
          settled = true;
          if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
          resolve(confirmed);
        }
        overlay.querySelector('.preview-btn-confirm')?.addEventListener('click', function() { close(true); });
        overlay.querySelector('.preview-btn-cancel')?.addEventListener('click', function() { close(false); });
        overlay.addEventListener('click', function(e) { if (e.target === overlay) close(false); });
      }
      var cancelLabel = tr('common.cancel', '取消');
      var confirmLabel = tr('upload.confirm', '确认上传');
      if (ext !== '.csv' && file.size > 2 * 1024 * 1024) {
        render('<div class="preview-dialog"><div class="preview-dialog-title">' + tr('upload.preview', '数据预览') + '</div>' +
          '<div class="preview-dialog-file">' + escapeHtml(file.name) + '</div>' +
          '<p>' + tr('upload.large-file-note', '文件较大，上传后由后台检查完整数据，当前不展开要素预览。') + '</p>' +
          '<div class="preview-dialog-actions"><button class="preview-btn preview-btn-cancel">' + cancelLabel + '</button>' +
          '<button class="preview-btn preview-btn-confirm">' + confirmLabel + '</button></div></div>');
        return;
      }
      var reader = new FileReader();
      reader.onload = function() {
        var content = reader.result;
        var html = '';
        if (ext === '.csv') {
          var csvRows = _parseCsvPreview(content);
          var cols = (csvRows[0] || ['无列名']).slice(0, 50).map(function(c) { return c.trim(); });
          var previewRows = csvRows.slice(1, 4);
          html = '<div class="preview-dialog">' +
            '<div class="preview-dialog-title">' + tr('upload.preview', '数据预览') + '</div>' +
            '<div class="preview-dialog-file">' + escapeHtml(file.name) + ' (' + (file.size / 1024).toFixed(1) + ' KB)</div>' +
            '<div class="preview-dialog-section"><div class="preview-dialog-label">' + tr('upload.preview-columns', '预览列名（最多 50 列）') + '</div>' +
            '<div class="preview-chips">' + cols.map(function(c) { return '<span class="preview-chip">' + escapeHtml(c) + '</span>'; }).join('') + '</div></div>' +
            '<div class="preview-dialog-section"><div class="preview-dialog-label">' + (GIS.i18n && GIS.i18n.isEnglish() ? tr('upload.preview-rows', '前 ') + Math.min(previewRows.length, 3) + tr('upload.rows', ' 行') : '前 ' + Math.min(previewRows.length, 3) + ' 行预览') + '</div>' +
            '<table class="preview-table"><thead><tr>' + cols.map(function(c) { return '<th>' + escapeHtml(c) + '</th>'; }).join('') + '</tr></thead>' +
            '<tbody>' + previewRows.map(function(row) {
              return '<tr>' + row.slice(0, 50).map(function(c) { return '<td>' + escapeHtml(c.trim().slice(0, 200)) + '</td>'; }).join('') + '</tr>';
            }).join('') + '</tbody></table></div>' +
            '<div class="preview-dialog-actions">' +
            '<button class="preview-btn preview-btn-cancel">' + cancelLabel + '</button>' +
            '<button class="preview-btn preview-btn-confirm">' + confirmLabel + '</button></div></div>';
        } else {
          // GeoJSON
          try {
            var gj = JSON.parse(content);
            var features = gj.features || (gj.type === 'Feature' ? [gj]
              : gj.type === 'GeometryCollection' ? (gj.geometries || []).map(function(geometry) { return {geometry: geometry}; })
              : gj.coordinates ? [{geometry: gj}] : []);
            var featCount = features.length;
            if (!Array.isArray(features)) throw new Error('要素列表无效');
            var types = Object.create(null);
            var fields = Object.create(null);
            features.slice(0, 10).forEach(function(f) {
              if (!f || typeof f !== 'object') return;
              if (f.geometry) types[f.geometry.type] = (types[f.geometry.type] || 0) + 1;
              if (f.properties) Object.keys(f.properties).forEach(function(k) { fields[k] = typeof f.properties[k]; });
            });
            var typeStr = Object.keys(types).join(', ') || '未知';
            var fieldKeys = Object.keys(fields);
            html = '<div class="preview-dialog">' +
              '<div class="preview-dialog-title">' + tr('upload.preview', '数据预览') + '</div>' +
              '<div class="preview-dialog-file">' + escapeHtml(file.name) + ' (' + (file.size / 1024).toFixed(1) + ' KB)</div>' +
              '<div class="preview-dialog-section"><div class="preview-dialog-label">' + tr('upload.feature-info', '要素信息') + '</div>' +
              '<div class="preview-info"><span>' + tr('upload.feature-count', '要素数: ') + '<strong>' + featCount + '</strong></span><span>' + tr('upload.geometry-type', '几何类型: ') + '<strong>' + escapeHtml(typeStr) + '</strong></span></div></div>' +
              (fieldKeys.length ? '<div class="preview-dialog-section"><div class="preview-dialog-label">' + tr('upload.fields', '字段 (') + fieldKeys.length + ')</div>' +
              '<div class="preview-chips">' + fieldKeys.map(function(k) { return '<span class="preview-chip">' + escapeHtml(k) + '</span>'; }).join('') + '</div></div>' : '') +
              '<div class="preview-dialog-actions">' +
              '<button class="preview-btn preview-btn-cancel">' + cancelLabel + '</button>' +
              '<button class="preview-btn preview-btn-confirm">' + confirmLabel + '</button></div></div>';
          } catch (e) {
            html = '<div class="preview-dialog"><div class="preview-dialog-title">' + tr('upload.parse-error-title', '无法解析') + '</div>' +
              '<p style="color:var(--ui-gray-500);font-size:13px;">' + tr('upload.geojson-parse-failed', 'GeoJSON 解析失败') + '</p>' +
              '<div class="preview-dialog-actions"><button class="preview-btn preview-btn-cancel">' + cancelLabel + '</button></div></div>';
          }
        }
        render(html);
      };
      reader.onerror = function() {
        showUploadToast('error', tr('upload.read-preview-failed', '无法读取文件预览，文件未上传：') + file.name);
        resolve(false);
      };
      reader.onabort = reader.onerror;
      // 只读取前 64KB 用于预览（CSV取前几行，GeoJSON 完全解析需要读全部但限制大小）
      var blob = (ext === '.csv') ? file.slice(0, 64 * 1024) : file;
      reader.readAsText(blob);
    });
  }

  async function startUpload(file, requestId, recoverExisting) {
    const uploadId = 'upload_' + (++_uploadIdCounter);
    requestId = requestId || _newUploadRequestId();
    var controller = new AbortController();
    _uploadAbortControllers.set(uploadId, controller);
    _uploadRequestIds.set(uploadId, requestId);
    showUploadToast('importing', file.name, uploadId);
    var signal = controller.signal;
    var uploadResult = null;
    var localMapName = null;
    var localLayerId = null;
    var handoffCommitted = false;

    try {
      var result = null;
      if (recoverExisting && GIS.api.getUploadStatus) {
        var prior = await _waitForUploadResult(requestId, signal, 10);
        if (prior && prior.status === 'completed' && prior.result) result = prior.result;
        else if (prior && prior.status === 'processing') {
          var processingError = new Error('上传仍在服务器处理中，请稍后检查状态');
          processingError.code = 'UPLOAD_PROCESSING';
          throw processingError;
        } else if (prior && prior.status === 'unknown') {
          var unknownReceiptError = new Error('服务器未找到可恢复的上传记录；请检查图层列表，确认未导入后再重新选择文件上传');
          unknownReceiptError.code = 'UPLOAD_RECOVERY_UNKNOWN';
          throw unknownReceiptError;
        } else if (prior && (prior.status === 'unsupported' || prior.status === 'unavailable')) {
          var recoveryUnavailable = new Error('当前服务无法安全核对上传状态，请先检查图层列表');
          recoveryUnavailable.code = 'UPLOAD_RECOVERY_UNAVAILABLE';
          throw recoveryUnavailable;
        }
      }
      if (!result) {
        var phaseWatch = _watchUploadPhase(requestId, signal, uploadId);
        try {
          result = await GIS.api.upload(file, signal, requestId);
        } catch (uploadError) {
          phaseWatch.stop();
          await phaseWatch.done;
          var uncertainUpload = uploadError.code === 'UPLOAD_NETWORK_ERROR' || uploadError.code === 'UPLOAD_TIMEOUT';
          if (!uncertainUpload || !GIS.api.getUploadStatus) throw uploadError;
          var recovered = await _waitForUploadResult(requestId, signal, 5);
          if (recovered && recovered.status === 'completed' && recovered.result) result = recovered.result;
          else {
            uploadError.uploadRequestId = requestId;
            uploadError.uploadStillProcessing = !!(recovered && recovered.status === 'processing');
            uploadError.uploadRecoveryUnavailable = !!(recovered && (recovered.status === 'unsupported' || recovered.status === 'unavailable'));
            throw uploadError;
          }
        } finally {
          phaseWatch.stop();
          await phaseWatch.done;
        }
      }
      if (signal.aborted) {
        if (result && result.name && result.registration_token && GIS.api.unregisterLayer) {
          try { await GIS.api.unregisterLayer(result.name, result.registration_token); }
          catch (error) { if (GIS.toast && GIS.toast.warn) GIS.toast.warn('导入已取消，后台图层清理失败，请稍后检查'); }
        }
        return;
      }
      uploadResult = result;
      if (!result || typeof result !== 'object') throw new Error('服务器未返回有效的上传结果');

      // 后端返回了错误信息
      if (result.error) {
        return showUploadToast('error', file.name + ': ' + result.error, uploadId);
      }

      // ===== CSV 文件：保存后让 AI 处理 =====
      if (result.csv_info) {
        const info = result.csv_info;
        showUploadToast('success', `${info.filename} 已保存`, uploadId);
        const msg = `读取文件 ${JSON.stringify(info.path || ('output/uploads/' + info.filename))}，识别坐标列，转成GeoJSON显示到地图`;
        if (GIS.chat && GIS.chat.sendMessage) {
          if (window._aiRunning) {
            var row = _uploadRows.get(uploadId);
            if (row) {
              clearTimeout(_uploadStatusTimers.get(uploadId));
              _uploadStatusTimers.delete(uploadId);
              var convert = document.createElement('button');
              convert.textContent = '识别坐标并上图';
              convert.className = 'upload-convert-btn';
              convert.addEventListener('click', async function() {
                if (window._aiRunning) {
                  if (GIS.toast && GIS.toast.warn) GIS.toast.warn('当前 AI 任务仍在运行，请完成后再处理 CSV');
                  return;
                }
                convert.disabled = true;
                try {
                  await GIS.chat.sendMessage(msg);
                  _scheduleUploadRowRemoval(uploadId, 3000);
                } catch (error) {
                  convert.disabled = false;
                  if (GIS.toast && GIS.toast.error) GIS.toast.error('CSV 已保存，转换请求失败：' + error.message);
                }
              });
              row.appendChild(convert);
            }
          } else {
            try { await GIS.chat.sendMessage(msg); }
            catch (error) { if (GIS.toast && GIS.toast.error) GIS.toast.error('CSV 已保存，转换请求失败：' + error.message); }
          }
        } else if (GIS.toast && GIS.toast.warn) GIS.toast.warn('CSV 已保存，AI 模块不可用，尚未转换为地图图层');
        return;
      }

      // ===== GeoTIFF 栅格文件 =====
      if (result.raster_info) {
        const info = result.raster_info;
        if (typeof info.url !== 'string' || !Array.isArray(info.bounds) || info.bounds.length !== 4
            || !info.bounds.every(Number.isFinite)) throw new Error('栅格预览缺少有效的地址或范围');
        showUploadToast('phase', tr('upload.phase-loading', '正在加载到地图'), uploadId);
        const layerId = 'raster_' + Date.now() + '_' + uploadId.slice(7);
        const name = result.name || file.name.replace(/\.(tif|tiff)$/i, '');
        localMapName = layerId;
        localLayerId = layerId;

        GIS.map.addImageOverlay(info.url, info.bounds, name, layerId);
        const rasterLayer = {
          layer_id: layerId,
          _rawName: layerId,
          filename: name,
          geometry_type: 'Raster',
          crs: info.crs || '未知（上传数据未提供 CRS）',
          source: 'upload',
          raster: info,
          _registeredName: result.name || name,
        };
        var addedRaster = GIS.layers.addLayer(rasterLayer, true);
        if (!addedRaster) throw new Error('图层面板未接收栅格上传结果');
        _rememberUploadRegistration(layerId, addedRaster._registeredName, result.registration_token, addedRaster);
        handoffCommitted = true;
        _scheduleProjectSave();

        showUploadToast('success', name, uploadId);
        return;
      }

      // ===== GeoJSON / SHP / GPKG / KML 等矢量文件上传 =====
      if (!result.geojson || typeof result.name !== 'string' || !result.name) throw new Error('上传结果缺少有效的矢量数据或图层名');
      showUploadToast('phase', tr('upload.phase-loading', '正在加载到地图'), uploadId);
      localMapName = result.name;
      localLayerId = 'vector_' + Date.now() + '_' + uploadId.slice(7);
      GIS.map.loadGeoJSON(result.geojson, result.name);

      const geojson = result.geojson;
      const type = geojson.type === 'FeatureCollection' && Array.isArray(geojson.features) && geojson.features.length > 0
        ? (geojson.features.find(function(feature) { return feature && feature.geometry; })?.geometry?.type || '未知')
        : (geojson.geometry?.type || '未知');
      const layer = {
        layer_id: localLayerId,
        filename: result.name,
        geometry_type: type,
        crs: 'WGS-84',
        geojson: geojson,
        source: 'upload',
        provenance: result.provenance || null,
        _registeredName: result.name,
      };
      // Attach the registration token only after the panel accepts the layer,
      // so a failed local handoff can roll back without scheduling a second unregister.
      var addedVector = GIS.layers.addLayer(layer, true);
      if (!addedVector) throw new Error('图层面板未接收矢量上传结果');
      _rememberUploadRegistration(localLayerId, result.name, result.registration_token, addedVector);
      handoffCommitted = true;
      _scheduleProjectSave();

      // 通知 AI 文件路径（隐藏消息，不显示在聊天框，但 AI 能读到）
      if (GIS.chat && GIS.chat.addMessage) {
        GIS.chat.addMessage(`[文件上传] ${result.name} → output/uploads/`, 'system', { hidden: true });
      }

      showUploadToast('success', result.name, uploadId);
    } catch (err) {
      if (err.name === 'AbortError' && !uploadResult) return; // 请求尚未返回时的用户取消
      if (uploadResult && !handoffCommitted) {
        var stateLayer = localLayerId && GIS.state && GIS.state.getLayer
          ? GIS.state.getLayer(localLayerId)
          : null;
        var stateCleaned = false;
        if (stateLayer && GIS.state.removeLayer) {
          try { GIS.state.removeLayer(localLayerId, true); stateCleaned = true; } catch (_) {}
        }
        var partialLayer = localLayerId && GIS.layers && GIS.layers.getLayers
          ? GIS.layers.getLayers().find(function(layer) { return layer.layer_id === localLayerId; })
          : null;
        if (!stateCleaned && partialLayer && GIS.layers.removeLayer) {
          try { GIS.layers.removeLayer(localLayerId, undefined, true); } catch (_) {}
        }
        if (!stateCleaned && localMapName && GIS.map && GIS.map.removeLayer) {
          try { GIS.map.removeLayer(localMapName); } catch (_) {}
        }
        if (uploadResult.registration_token && uploadResult.name && GIS.api.unregisterLayer) {
          try { await GIS.api.unregisterLayer(uploadResult.name, uploadResult.registration_token); }
          catch (cleanupError) {
            if (GIS.toast && GIS.toast.warn) GIS.toast.warn('上传结果未能加入工作区，后台临时图层清理失败，请稍后检查');
          }
        }
      }
      var errorMessage = err.code === 'UPLOAD_RECOVERY_UNAVAILABLE' || err.uploadRecoveryUnavailable
        ? tr('upload.recovery-unavailable', '无法安全核对上传状态。请先检查图层列表；当前服务不支持安全恢复，因此不会重传。')
        : (err.code === 'UPLOAD_RECOVERY_UNKNOWN'
          ? tr('upload.recovery-unknown', '服务器未找到可恢复的上传记录，无法确认文件是否已导入。请检查图层列表；确认没有后，再重新选择文件上传。')
        : (err.code === 'UPLOAD_TIMEOUT'
          ? tr('upload.timeout-unknown', '上传等待超时，服务器可能仍在处理。请检查图层列表，或稍后使用“检查并恢复”。')
        : (err.code === 'UPLOAD_NETWORK_ERROR'
          ? tr('upload.connection-unknown', '上传连接中断，服务器可能已收到文件。请先检查图层列表，再决定是否重试，避免重复导入。')
        : (err.code === 'UPLOAD_PROCESSING'
          ? tr('upload.still-processing', '服务器仍在处理此上传，请稍后再次检查。')
          : (err.message || '上传失败')))));
      showUploadToast('error', file.name + ': ' + errorMessage, uploadId);
      if (err.code === 'UPLOAD_PROCESSING'
          || ((err.code === 'UPLOAD_NETWORK_ERROR' || err.code === 'UPLOAD_TIMEOUT') && !err.uploadRecoveryUnavailable)) {
        _addUploadRecoveryAction(uploadId, file, requestId);
      }
    } finally {
      _uploadAbortControllers.delete(uploadId);
      _uploadRequestIds.delete(uploadId);
    }
  }

  function _newUploadRequestId() {
    var cryptoApi = window.crypto;
    if (cryptoApi && typeof cryptoApi.randomUUID === 'function') return cryptoApi.randomUUID();
    if (cryptoApi && typeof cryptoApi.getRandomValues === 'function') {
      var bytes = new Uint8Array(16);
      cryptoApi.getRandomValues(bytes);
      return Array.from(bytes, function(value) { return value.toString(16).padStart(2, '0'); }).join('');
    }
    return 'upload-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  }

  function _watchUploadCancellation(requestId, bubble, uploadId) {
    if (!GIS.api || typeof GIS.api.getUploadStatus !== 'function') return;
    var attempts = 0;
    function show(key, fallback) {
      bubble.innerHTML = '<span style="color:var(--on-surface-variant);font-size:11px;">' + tr(key, fallback) + '</span>';
    }
    function poll() {
      attempts += 1;
      GIS.api.getUploadStatus(requestId).then(async function(status) {
        if (status && status.status === 'cancelled') {
          show('upload.cancelled', '导入已取消');
          _scheduleUploadRowRemoval(uploadId, 3000);
          return;
        }
        if (status && status.status === 'completed' && status.result) {
          var result = status.result;
          if (result.name && result.registration_token && GIS.api.unregisterLayer) {
            try {
              await GIS.api.unregisterLayer(result.name, result.registration_token);
              show('upload.cancelled', '导入已取消');
              _scheduleUploadRowRemoval(uploadId, 3000);
              return;
            } catch (_) {}
          }
          show('upload.cancel-uncertain', '取消请求未能确认完成，请检查图层列表');
          _scheduleUploadRowRemoval(uploadId, 10 * 60 * 1000);
          return;
        }
        if (status && status.status === 'processing' && attempts < 120) {
          setTimeout(poll, 500);
          return;
        }
        show('upload.cancel-uncertain', '取消请求未能确认完成，请检查图层列表');
        _scheduleUploadRowRemoval(uploadId, 10 * 60 * 1000);
      }).catch(function() {
        show('upload.cancel-uncertain', '取消请求未能确认完成，请检查图层列表');
        _scheduleUploadRowRemoval(uploadId, 10 * 60 * 1000);
      });
    }
    poll();
  }

  async function _waitForUploadResult(requestId, signal, attempts) {
    for (var attempt = 0; attempt < attempts; attempt++) {
      if (signal && signal.aborted) return { status: 'unavailable' };
      try {
        var status = await GIS.api.getUploadStatus(requestId, signal);
        if (status && status.status === 'completed' && status.result) return status;
        if (status && status.status === 'unknown') return status;
        if (!status || status.status !== 'processing') return { status: 'unavailable' };
      } catch (error) {
        return { status: error && (error.status === 404 || error.status === 405) ? 'unsupported' : 'unavailable' };
      }
      if (attempt + 1 < attempts) await new Promise(function(resolve) { setTimeout(resolve, 300); });
    }
    return { status: 'processing' };
  }

  function _watchUploadPhase(requestId, signal, uploadId) {
    var active = true;
    var waitTimer = null;
    var wakeWait = null;
    var statusController = new AbortController();
    var abortStatus = function() { statusController.abort(); };
    if (signal) {
      if (signal.aborted) statusController.abort();
      else signal.addEventListener('abort', abortStatus, { once: true });
    }
    var done = (async function() {
      try {
        while (active && !(signal && signal.aborted) && GIS.api.getUploadStatus) {
          try {
            var status = await GIS.api.getUploadStatus(requestId, statusController.signal);
            if (active && status && status.status === 'processing') {
              if (status.phase === 'parsing') {
                showUploadToast('phase', tr('upload.phase-parsing', '正在检查并解析数据'), uploadId);
              } else if (status.phase === 'saving') {
                showUploadToast('phase', tr('upload.phase-saving', '服务器正在保存已接收的数据'), uploadId);
              }
            }
          } catch (_) {
            if (!active || (signal && signal.aborted)) return;
          }
          if (active && !(signal && signal.aborted)) await new Promise(function(resolve) {
            wakeWait = resolve;
            waitTimer = setTimeout(function() {
              waitTimer = null;
              wakeWait = null;
              resolve();
            }, 400);
          });
        }
      } finally {
        if (signal) signal.removeEventListener('abort', abortStatus);
      }
    })();
    return { stop: function() {
      active = false;
      statusController.abort();
      if (waitTimer) clearTimeout(waitTimer);
      waitTimer = null;
      if (wakeWait) wakeWait();
      wakeWait = null;
    }, done: done };
  }

  function _addUploadRecoveryAction(uploadId, file, requestId) {
    var row = _uploadRows.get(uploadId);
    if (!row) return;
    var timer = _uploadStatusTimers.get(uploadId);
    if (timer) clearTimeout(timer);
    _uploadStatusTimers.delete(uploadId);
    var bubble = row.querySelector('.system-pill');
    if (!bubble) return;
    var button = document.createElement('button');
    button.className = 'upload-recovery-btn';
    button.textContent = tr('upload.check-recover', '检查并恢复');
    button.style.cssText = 'margin-left:8px;padding:2px 8px;border:1px solid var(--outline-variant);border-radius:10px;background:var(--surface);color:var(--on-surface);cursor:pointer;font-size:11px;';
    button.addEventListener('click', function() {
      button.disabled = true;
      var statusTimer = _uploadStatusTimers.get(uploadId);
      if (statusTimer) clearTimeout(statusTimer);
      var parent = row.parentNode;
      if (parent) parent.removeChild(row);
      _uploadRows.delete(uploadId);
      _uploadStatusTimers.delete(uploadId);
      return startUpload(file, requestId, true);
    });
    bubble.appendChild(button);
    _scheduleUploadRowRemoval(uploadId, 10 * 60 * 1000);
  }

  // The vector upload path may return the shared GIS state record while deletion
  // later reads registration ownership from the separate layer-panel record.
  // Keep the server name and version token on both records so cleanup is safe.
  function _rememberUploadRegistration(layerId, registeredName, token, returnedLayer) {
    if (!registeredName || typeof token !== 'string' || !token) return;
    var records = [returnedLayer];
    if (GIS.layers && GIS.layers.getLayers) {
      var panelLayer = GIS.layers.getLayers().find(function(layer) { return layer.layer_id === layerId; });
      if (panelLayer) records.push(panelLayer);
    }
    if (GIS.state && GIS.state.getLayer) {
      var stateLayer = GIS.state.getLayer(layerId);
      if (stateLayer) records.push(stateLayer);
    }
    records.filter(Boolean).forEach(function(layer) {
      layer._registeredName = registeredName;
      if (!layer._registrationTokens) layer._registrationTokens = Object.create(null);
      layer._registrationTokens[registeredName] = token;
    });
  }

  function _scheduleProjectSave() {
    if (GIS.project && typeof GIS.project.autoSave === 'function') {
      Promise.resolve(GIS.project.autoSave()).catch(function(error) {
        console.warn('[GIS Upload] 图层上传后的工程自动保存失败', error);
      });
    }
  }

  // ---- 上传状态气泡（显示在 AI 对话区，无头像，像 AI 消息样式） ----

  var _uploadAbortControllers = new Map();
  var _uploadRequestIds = new Map();
  var _uploadRows = new Map();
  var _uploadStatusTimers = new Map();
  var _uploadIdCounter = 0;

  function showUploadToast(status, msg, uploadId) {
    uploadId = uploadId || ('notice_' + (++_uploadIdCounter));
    var container = document.getElementById('chatMessages');
    if (!container) return;

    if (status === 'importing') {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:center;width:100%;padding:4px 0;box-sizing:border-box;opacity:0;transition:opacity 0.2s;';

      var bubble = document.createElement('div');
      bubble.className = 'system-pill';
      bubble.style.cssText = 'display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--on-surface-variant);background:var(--surface-container-high);border:1px solid var(--outline-variant);border-radius:12px;padding:3px 12px;line-height:1.4;';
      bubble.innerHTML =
        "<span class=\"ui-icon upload-msg-icon\" aria-hidden=\"true\" style=\"flex-shrink:0;width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-12f8ae0661b2.png')\"></span><span class=\"upload-phase-label\" aria-live=\"polite\" style=\"font-weight:500;\">" + tr('upload.importing', '正在上传: ') + escapeHtml(msg || (GIS.i18n && GIS.i18n.isEnglish() ? 'file' : '文件')) + '</span>' +
        '<button class="upload-cancel-btn" style="margin-left:6px;font-size:10px;padding:1px 6px;border:1px solid var(--outline-variant);border-radius:3px;background:none;cursor:pointer;color:var(--on-surface-variant);white-space:nowrap;">' + tr('upload.cancel', '取消') + '</button>';
      row.appendChild(bubble);
      container.appendChild(row);
      requestAnimationFrame(function() { row.style.opacity = '1'; });
      container.scrollTop = container.scrollHeight;

      _uploadRows.set(uploadId, row);

      var iconEl = row.querySelector('.upload-msg-icon');
      if (iconEl) iconEl.style.animation = 'upload-bounce 0.6s ease-in-out infinite alternate';

      var cancelBtn = row.querySelector('.upload-cancel-btn');
      if (cancelBtn) {
        cancelBtn.addEventListener('click', async function() {
          var ctrl = _uploadAbortControllers.get(uploadId);
          if (!ctrl) return;
          var requestId = _uploadRequestIds.get(uploadId);
          cancelBtn.disabled = true;
          try {
            var cancelResult = null;
            if (requestId && GIS.api && typeof GIS.api.cancelUpload === 'function') {
              cancelResult = await GIS.api.cancelUpload(requestId);
            }
            ctrl.abort();
            if (!cancelResult) {
              bubble.innerHTML = '<span style="color:var(--on-surface-variant);font-size:11px;">' +
                tr('upload.cancel-uncertain', '已停止等待；服务器可能仍在处理，请检查图层列表') + '</span>';
              _scheduleUploadRowRemoval(uploadId, 10 * 60 * 1000);
              return;
            }
            if (cancelResult.status === 'cancelling') {
              bubble.innerHTML = '<span style="color:var(--on-surface-variant);font-size:11px;">' +
                tr('upload.cancelling', '正在取消并清理上传结果…') + '</span>';
              _watchUploadCancellation(requestId, bubble, uploadId);
              return;
            }
            if (cancelResult.status !== 'cancelled') throw new Error('服务器未确认取消');
          } catch (_) {
            ctrl.abort();
            bubble.innerHTML = '<span style="color:var(--on-surface-variant);font-size:11px;">' +
              tr('upload.cancel-uncertain', '已停止等待；服务器可能仍在处理，请检查图层列表') + '</span>';
            _scheduleUploadRowRemoval(uploadId, 10 * 60 * 1000);
            return;
          }
          bubble.innerHTML = '<span style="color:var(--on-surface-variant);font-size:11px;">' +
            escapeHtml(msg || (GIS.i18n && GIS.i18n.isEnglish() ? 'File' : '文件')) + ' ' + tr('upload.cancelled', '导入已取消') + '</span>';
          _scheduleUploadRowRemoval(uploadId, 3000);
        });
      }

    } else if (status === 'phase') {
      var phaseRow = _uploadRows.get(uploadId);
      var phaseLabel = phaseRow && phaseRow.querySelector('.upload-phase-label');
      if (phaseLabel) phaseLabel.textContent = msg;
    } else {
      var targetRow = _uploadRows.get(uploadId);
      if (!targetRow) {
        targetRow = document.createElement('div');
        targetRow.style.cssText = 'display:flex;justify-content:center;width:100%;padding:4px 0;box-sizing:border-box;opacity:0;transition:opacity 0.2s;';
        var bub = document.createElement('div');
        bub.className = 'system-pill';
        bub.style.cssText = 'display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--on-surface-variant);background:var(--surface-container-high);border:1px solid var(--outline-variant);border-radius:12px;padding:3px 12px;line-height:1.4;';
        targetRow.appendChild(bub);
        container.appendChild(targetRow);
        requestAnimationFrame(function() { targetRow.style.opacity = '1'; });
        container.scrollTop = container.scrollHeight;
        _uploadRows.set(uploadId, targetRow);
      }

      var contentDiv = targetRow.querySelector('.system-pill') || targetRow.querySelector('div:last-child');
      if (!contentDiv) return;

      if (status === 'success') {
        if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
          window.GIS.toast.success(tr('upload.success', '上传成功') + (msg ? ': ' + msg : ''));
        }
        contentDiv.innerHTML =
          "<span class=\"ui-icon\" aria-hidden=\"true\" style=\"flex-shrink:0;width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-ae6516c4f98b.png')\"></span><span style=\"color:#2e7d32;font-weight:500;\">" + tr('upload.success', '上传成功') + (msg ? ': ' + escapeHtml(msg) : '') + '</span>';
        _scheduleUploadRowRemoval(uploadId, 3000);
      } else if (status === 'error') {
        if (window.GIS.toast && typeof window.GIS.toast.error === 'function') {
          window.GIS.toast.error(tr('upload.failed', '上传失败') + (msg ? ': ' + msg : ''));
        }
        contentDiv.innerHTML =
          "<span class=\"ui-icon\" aria-hidden=\"true\" style=\"flex-shrink:0;width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-22ff8b401bb5.png')\"></span><span style=\"color:#d32f2f;font-weight:500;\">" + tr('upload.failed', '上传失败') + (msg ? ': ' + escapeHtml(msg) : '') + '</span>';
        _scheduleUploadRowRemoval(uploadId, 5000);
      }
    }
  }

  function _scheduleUploadRowRemoval(uploadId, delay) {
    var previousTimer = _uploadStatusTimers.get(uploadId);
    if (previousTimer) clearTimeout(previousTimer);
    var timer = setTimeout(function() {
      var row = _uploadRows.get(uploadId);
      if (row && row.parentNode) row.parentNode.removeChild(row);
      _uploadRows.delete(uploadId);
      _uploadStatusTimers.delete(uploadId);
    }, delay);
    _uploadStatusTimers.set(uploadId, timer);
  }

  function escapeHtml(str) {
    if (window.GIS.utils && typeof window.GIS.utils.escapeHtml === 'function') return window.GIS.utils.escapeHtml(str);
    return String(str == null ? '' : str).replace(/[&<>"']/g, function(char) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char];
    });
  }

  GIS.upload = { init };
})();
