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

  // ===== API 密钥管理 (localStorage) =====
  // 密钥存在浏览器本地，每次发请求时带上，后端用完就丢不存盘
  const STORAGE_KEY = 'gis_deepseek_api_key';

  /** 从 localStorage 读取保存的 DeepSeek 密钥 */
  function getApiKey() {
    return localStorage.getItem(STORAGE_KEY) || '';
  }

  /** 把 DeepSeek 密钥保存到 localStorage（关掉浏览器再打开还在） */
  function setApiKey(key) {
    if (key) {
      localStorage.setItem(STORAGE_KEY, key);
    } else {
      localStorage.removeItem(STORAGE_KEY);  // 传空字符串就当是清除
    }
  }

  async function request(endpoint, options = {}) {
    // TODO: 通用 fetch — 拼接 URL、headers、错误处理
  }

  // ===== 文件上传 =====
  /** @param {File} file @param {function} [onProgress] */
  async function upload(file, onProgress) {
    //上传文件使用 FormData 发送 POST 请求到 /api/upload
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${BASE_URL}/api/upload`, {
      method: 'POST',
      body: formData,
    });
    
    if (!res.ok) throw new Error(`Upload API error: ${res.status}`);
    const data = await res.json();
    return data;
  }

  // ===== 聊天 / AI =====
  /** @param {string} message @param {string} [sessionId='default'] */
// 发送消息到后端的聊天接口，并返回 AI 的回复
  async function chat(message, sessionId = 'default') {
    // 从浏览器 localStorage 取出用户保存的 API 密钥，一起发给后端
    const apiKey = getApiKey();
const res=await fetch(`${BASE_URL}/api/chat`,{
  method:'POST',
  headers:{'Content-Type':'application/json'},
  //sessionId可以用来区分不同的聊天会话，方便后端管理
  body:JSON.stringify({
    message,                    // 用户输入的文字
    session_id:sessionId,       // 会话ID（目前都用 default）
    api_key: apiKey || undefined  // 密钥：有就带上，没有就不传（后端会用 apikey.txt）
  })
})
if (!res.ok) throw new Error(`Chat API error: ${res.status}`);
const data=await res.json();
// { response: "AI 回复的文字" }
return data;


    // TODO: POST /chat  { message, session_id }
  }

  // ===== 测试 API 密钥 =====
  /** 向后端发一个测试请求，验证 DeepSeek 密钥能不能用 */
  async function testApiKey(apiKey) {
    const res = await fetch(`${BASE_URL}/api/test-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (!res.ok) throw new Error(`测试连接失败: ${res.status}`);
    // 返回 { success: true/false, message: "连接成功 ✓" / "密钥无效" }
    return res.json();
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

  // ===== 边界加载 =====
  /** 从OSM加载行政边界，返回GeoJSON */
  async function getBoundary(place) {
    const res = await fetch(`${BASE_URL}/api/boundary?place=${encodeURIComponent(place)}`);
    if (!res.ok) throw new Error(`获取边界失败: ${res.status}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    return data; // { geojson: ..., name: "..." }
  }

  // ===== 项目保存/加载 =====
  async function saveProject(data)  { /* TODO: POST /projects */ }
  async function loadProject(id)    { /* TODO: GET /projects/:id */ }
  async function listProjects()     { /* TODO: GET /projects */ }

  // ===== 清除记忆 =====
  async function clearMemory(sessionId = 'default') {
    const res = await fetch(`${BASE_URL}/api/chat/memory?session_id=${sessionId}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(`清除记忆失败: ${res.status}`);
    return res.json();
  }

  // ===== 系统 =====
  async function healthCheck()      { /* TODO: GET /health */ }

  /** 获取后端版本信息（Git 提交号 + 启动时间） */
  async function getVersion() {
    try {
      const res = await fetch(`${BASE_URL}/api/version`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  return {
    request, upload, chat, clearMemory,
    getLayers, getLayer, deleteLayer,
    downloadLayer, executeGISAction, getBoundary,
    saveProject, loadProject, listProjects,
    healthCheck, testApiKey, getApiKey, setApiKey, getVersion,
    BASE_URL,
  };
})();

// ===== 全局下载函数 =====
window.downloadGeoJSON = function(layerId) {
  const layers = GIS.layers.getLayers();
  const layer = layers.find(l => l.layer_id === layerId);
  if (!layer || !layer.geojson) return;
  //封装成blob对象
  const blob = new Blob([JSON.stringify(layer.geojson, null, 2)], { type: 'application/json' });
  //创建下载连接
  const url = URL.createObjectURL(blob);
  // 创建a标签
  const a = document.createElement('a');
  // 设置a标签的href属性为下载链接
  //必须要有一个<a>才能触发下载
  a.href = url;
  // 设置a标签的download属性为文件名
  a.download = (layer.filename || 'layer') + '.geojson';
  // 模拟点击a标签
  a.click();
  //释放URL对象
  URL.revokeObjectURL(url);
};

window.downloadAllFiles = function() {
  const rows = document.querySelectorAll('#filesTbody tr');
  rows.forEach(row => {
    const btn = row.querySelector('button');
    if (btn && btn.onclick) btn.onclick();
  });
};
