/**
 * GIS AI WorkTable — API 接口层
 * 函数签名已预留，实现由你完成
 *
 * 使用: window.GIS.api.xxx()
 * BASE_URL: http://localhost:8000
 */


//创建一个空对象
window.GIS = window.GIS || {};
// 全局工具函数
window.GIS.utils = {
  escapeHtml: function(str) {
    if (typeof str !== 'string' && typeof str !== 'number') return '';
    var d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
};
window.GIS.api = (() => {
  const BASE_URL = (function() {
    try {
      // 优先使用 localStorage 覆盖（方便部署到其他域名时配置）
      var stored = localStorage.getItem('gis_api_base_url');
      if (stored) return stored;
    } catch(e) { /* localStorage 不可用（如 Safari 无痕模式） */ }
    return 'http://localhost:8000';
  })();

  // ===== API 密钥管理 (localStorage) =====
  // 密钥存在浏览器本地，每次发请求时带上，后端用完就丢不存盘
  const DS_STORAGE_KEY = 'gis_deepseek_api_key';
  const GLM_STORAGE_KEY = 'gis_glm_api_key';
  const AGNES_STORAGE_KEY = 'gis_agnes_api_key';
  const AMAP_STORAGE_KEY = 'gis_amap_api_key';
  const MODEL_STORAGE_KEY = 'gis_selected_model';
  const MODEL_STATUS_KEY = 'gis_model_status';

  function _lsGet(key) { try { return localStorage.getItem(key); } catch(e) { return null; } }
  function _lsSet(key, val) { try { localStorage.setItem(key, val); } catch(e) {} }
  function _lsRemove(key) { try { localStorage.removeItem(key); } catch(e) {} }

  /** 从 localStorage 读取保存的 DeepSeek 密钥 */
  function getApiKey() {
    return _lsGet(DS_STORAGE_KEY) || '';
  }

  /** 把 DeepSeek 密钥保存到 localStorage（关掉浏览器再打开还在） */
  function setApiKey(key) {
    if (key) { _lsSet(DS_STORAGE_KEY, key); } else { _lsRemove(DS_STORAGE_KEY); }
  }

  /** 从 localStorage 读取保存的 GLM 密钥 */
  function getGLMApiKey() {
    return _lsGet(GLM_STORAGE_KEY) || '';
  }

  /** 把 GLM 密钥保存到 localStorage */
  function setGLMApiKey(key) {
    if (key) { _lsSet(GLM_STORAGE_KEY, key); } else { _lsRemove(GLM_STORAGE_KEY); }
  }

  /** 从 localStorage 读取保存的 Agnes 密钥 */
  function getAgnesApiKey() {
    return _lsGet(AGNES_STORAGE_KEY) || '';
  }

  /** 把 Agnes 密钥保存到 localStorage */
  function setAgnesApiKey(key) {
    if (key) { _lsSet(AGNES_STORAGE_KEY, key); } else { _lsRemove(AGNES_STORAGE_KEY); }
  }

  /** 从 localStorage 读取保存的高德地图密钥 */
  function getAmapKey() {
    return _lsGet(AMAP_STORAGE_KEY) || '';
  }

  /** 把高德地图密钥保存到 localStorage */
  function setAmapKey(key) {
    if (key) { _lsSet(AMAP_STORAGE_KEY, key); } else { _lsRemove(AMAP_STORAGE_KEY); }
  }

  /** 获取保存的模型偏好 */
  function getSelectedModel() {
    return _lsGet(MODEL_STORAGE_KEY) || 'glm-routed';
  }

  /** 保存模型偏好 */
  function setSelectedModel(model) {
    _lsSet(MODEL_STORAGE_KEY, model);
  }

  // ===== 模型状态追踪 =====
  /** 获取指定模型的测速状态: 'untested' | 'online' | 'offline' */
  function getModelStatus(provider) {
    try {
      var stored = JSON.parse(_lsGet(MODEL_STATUS_KEY)) || {};
      return stored[provider] || 'untested';
    } catch (e) {
      return 'untested';
    }
  }

  /** 设置指定模型的测速状态 */
  function setModelStatus(provider, status) {
    try {
      var stored = JSON.parse(_lsGet(MODEL_STATUS_KEY)) || {};
      stored[provider] = status;
      _lsSet(MODEL_STATUS_KEY, JSON.stringify(stored));
    } catch (e) {}
  }

  /** 清除所有模型的测速状态 */
  function clearModelStatus() {
    _lsRemove(MODEL_STATUS_KEY);
  }

  async function request(endpoint, options = {}) {
    // 通用 fetch 请求（暂未使用）
    const url = `${BASE_URL}${endpoint}`;
    try {
      const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.warn(`[GIS API] 请求失败: ${endpoint}`, e);
      throw e;
    }
  }

  // ===== 文件上传 =====
  /** @param {File} file @param {AbortSignal} [signal] */
  async function upload(file, signal) {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${BASE_URL}/api/upload`, {
      method: 'POST',
      body: formData,
      signal: signal || null,
    });
    
    if (!res.ok) throw new Error(`Upload API error: ${res.status}`);
    const data = await res.json();
    return data;
  }

  // ===== 聊天 / AI =====
  /** @param {string} message @param {string} [sessionId='default'] @param {string} [provider='deepseek'] @param {string[]} [forceSkills=[]] */
  async function chat(message, sessionId = 'default', provider = 'glm', forceSkills = []) {
    // 根据 provider 选择对应的 API 密钥
    const apiKey = provider === 'agnes' ? getAgnesApiKey() : (provider === 'glm' || provider === 'glm-routed') ? getGLMApiKey() : getApiKey();
    const controller = new AbortController();
    const timeoutId = setTimeout(function() { controller.abort(); }, 600000);
    let res;
    try {
      res = await fetch(`${BASE_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          message,
          session_id: sessionId,
          api_key: apiKey || undefined,
          provider,
          force_skills: forceSkills,
          amap_key: getAmapKey() || undefined
        })
      });
    } finally {
      clearTimeout(timeoutId);
    }
    if (!res.ok) throw new Error(`Chat API error: ${res.status}`);
    const data = await res.json();
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

  /** 向后端发一个测试请求，验证 GLM 密钥能不能用 */
  async function testGLMApiKey(apiKey) {
    const res = await fetch(`${BASE_URL}/api/test-key-glm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (!res.ok) throw new Error(`测试连接失败: ${res.status}`);
    return res.json();
  }

  /** 向后端发一个测试请求，验证 Agnes 密钥能不能用 */
  async function testAgnesApiKey(apiKey) {
    const res = await fetch(`${BASE_URL}/api/test-key-agnes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (!res.ok) throw new Error(`测试连接失败: ${res.status}`);
    return res.json();
  }

  // ===== 图层管理 =====
  async function getLayers()        { /* TODO: GET /layers */ }
  async function getLayer(layerId)  { /* TODO: GET /layers/:id */ }
  async function deleteLayer(layerId) { /* TODO: DELETE /layers/:id */ }

  /** 检查图层元数据（前端可先算基础信息，后端补充 CRS 等） */
  async function inspectLayer(geojson, name) {
    const res = await fetch(`${BASE_URL}/api/layer/inspect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ geojson, name }),
    });
    if (!res.ok) throw new Error(`Inspect API error: ${res.status}`);
    return res.json();
  }

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
    healthCheck, testApiKey, testGLMApiKey, testAgnesApiKey,
    getApiKey, setApiKey, getGLMApiKey, setGLMApiKey,
    getAgnesApiKey, setAgnesApiKey,
    getAmapKey, setAmapKey,
    getSelectedModel, setSelectedModel,
    getModelStatus, setModelStatus, clearModelStatus,
    inspectLayer,
    BASE_URL, DS_STORAGE_KEY, GLM_STORAGE_KEY, AGNES_STORAGE_KEY, AMAP_STORAGE_KEY, MODEL_STORAGE_KEY, MODEL_STATUS_KEY,
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
