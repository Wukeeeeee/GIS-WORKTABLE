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

  // 文件格式校验
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
    notify(`文件上传中: ${file.name}`, 'info');

    try {
      const result = await GIS.api.upload(file);

      // 后端返回了错误信息
      if (result.error) {
        return notify(`上传失败: ${result.error}`, 'error');
      }

      // ===== CSV 文件：保存后让 AI 处理 =====
      if (result.csv_info) {
        const info = result.csv_info;
        notify(`${info.filename} 已保存，共${info.rows}行，列名: ${info.columns.join(', ')}`, 'info');
        // 自动让 AI 读取并转换
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
        geojson: geojson,
      });

      // 通知 AI 文件路径（简洁的标记，不打扰用户）
      if (GIS.chat && GIS.chat.addMessage) {
        GIS.chat.addMessage(`[文件上传] ${result.name} → output/uploads/`, 'system');
      }

      notify(`上传成功: ${result.name}`, 'success');
    } catch (err) {
      notify(`上传失败: ${err.message}`, 'error');
    }
  }

  // 系统通知
  function notify(message, type = 'info') {
    if (GIS.chat && GIS.chat.addMessage) {
      GIS.chat.addMessage(message, 'system');
    }
  }

  // 打开文件选择对话框
  function openDialog() { if (fileInput) fileInput.click(); }

  GIS.upload = { init, openDialog, handleFiles, ALLOWED_EXTENSIONS };
})();
