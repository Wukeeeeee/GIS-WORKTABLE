/**
 * GIS AI WorkTable — API 接口层
 * 函数签名已预留，实现由你完成
 *
 * 使用: window.GIS.api.xxx()
 * BASE_URL: http://localhost:8000
 */

window.GIS = window.GIS || {};
window.GIS.api = (() => {
  const BASE_URL = 'http://localhost:8000';

  async function request(endpoint, options = {}) {
    // TODO: 通用 fetch — 拼接 URL、headers、错误处理
  }

  // ===== 文件上传 =====
  /** @param {File} file @param {function} [onProgress] */
  async function upload(file, onProgress) {
    // TODO: POST /upload (multipart/form-data)
  }

  // ===== 聊天 / AI =====
  /** @param {string} message @param {string} [sessionId='default'] */
  async function chat(message, sessionId = 'default') {
    // TODO: POST /chat  { message, session_id }
  }

  // ===== 图层管理 =====
  async function getLayers()        { /* TODO: GET /layers */ }
  async function getLayer(layerId)  { /* TODO: GET /layers/:id */ }
  async function deleteLayer(layerId) { /* TODO: DELETE /layers/:id */ }

  // ===== 下载导出 =====
  /** @param {string} layerId @param {'geojson'|'shp'|'gpkg'} [format='geojson'] */
  async function downloadLayer(layerId, format = 'geojson') {
    // TODO: GET /download/:id?format=...
  }

  // ===== GIS 操作 =====
  /** @param {string} action @param {object} params */
  async function executeGISAction(action, params) {
    // TODO: POST /execute  { action, params }
  }

  // ===== 项目保存/加载 =====
  async function saveProject(data)  { /* TODO: POST /projects */ }
  async function loadProject(id)    { /* TODO: GET /projects/:id */ }
  async function listProjects()     { /* TODO: GET /projects */ }

  // ===== 系统 =====
  async function healthCheck()      { /* TODO: GET /health */ }

  return {
    request, upload, chat,
    getLayers, getLayer, deleteLayer,
    downloadLayer, executeGISAction,
    saveProject, loadProject, listProjects,
    healthCheck, BASE_URL,
  };
})();
