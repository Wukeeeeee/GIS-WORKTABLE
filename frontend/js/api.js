/**
 * GIS AI WorkTable — API 接口层
 * 函数签名已预留，实现由你完成
 *
 * 使用: window.GIS.api.xxx()
 * BASE_URL: http://localhost:8000
 */


//创建一个空对象
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
// 发送消息到后端的聊天接口，并返回 AI 的回复
  async function chat(message, sessionId = 'default') {
const res=await fetch(`${BASE_URL}/api/chat`,{
  method:'POST',
  headers:{'Content-Type':'application/json'},
  //sessionId可以用来区分不同的聊天会话，方便后端管理
  body:JSON.stringify({message,session_id:sessionId})
})
if (!res.ok) throw new Error(`Chat API error: ${res.status}`);
const data=await res.json();
//返回ai的回复数据
return data;


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
