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

  // ============================================================
  // Provider 列表 —— 唯一数据源（旧的三把 key 只做一次性迁移）
  // ============================================================
  // 以前：gis_deepseek_api_key / gis_glm_api_key / gis_agnes_api_key 三把散 key
  // 现在：gis_llm_providers = ProviderItem[]
  //   ProviderItem: { id, name, base_url, model, api_key,
  //                   glm_prompt, router, reasoning, temperature?, max_tokens? }
  // Key 只存浏览器 localStorage，随每次请求经 llm_config 携带，后端即用即弃。
  const DS_STORAGE_KEY = 'gis_deepseek_api_key';      // 兼容/迁移用
  const GLM_STORAGE_KEY = 'gis_glm_api_key';
  const AGNES_STORAGE_KEY = 'gis_agnes_api_key';
  const AMAP_STORAGE_KEY = 'gis_amap_api_key';
  const GEO_CRED_STORAGE_KEY = 'gis_geo_credentials'; // { copernicus/usgs/gscloud: {username, password} }
  const MODEL_STORAGE_KEY = 'gis_selected_model';     // 历史 key，保留读写做兼容
  const MODEL_STATUS_KEY = 'gis_model_status';
  const PROVIDERS_STORAGE_KEY = 'gis_llm_providers';

  function _lsGet(key) { try { return localStorage.getItem(key); } catch(e) { return null; } }
  function _lsSet(key, val) { try { localStorage.setItem(key, val); } catch(e) {} }
  function _lsRemove(key) { try { localStorage.removeItem(key); } catch(e) {} }

  /** 默认 Provider 种子（首装 / 损坏时重建） */
  function _seedProviders() {
    return [
      { id: 'deepseek-routed', name: 'DeepSeek V4 Flash+',
        base_url: 'https://api.deepseek.com', model: 'deepseek-chat', api_key: '',
        glm_prompt: false, router: true, reasoning: false, temperature: 0.7, max_tokens: null },
      { id: 'glm-routed', name: 'GLM-4.7-Flash+',
        base_url: 'https://open.bigmodel.cn/api/paas/v4/', model: 'glm-4.7-flash', api_key: '',
        glm_prompt: true, router: true, reasoning: false, temperature: 0.7, max_tokens: null },
      { id: 'agnes', name: 'Agnes 2.0 Flash+',
        base_url: 'https://apihub.agnes-ai.com/v1', model: 'agnes-2.0-flash', api_key: '',
        glm_prompt: false, router: true, reasoning: false, temperature: 0.7, max_tokens: null },
      { id: 'openrouter', name: 'OpenRouter GLM-5.2 (free)',
        base_url: 'https://openrouter.ai/api/v1', model: 'z-ai/glm-5.2:free', api_key: '',
        glm_prompt: true, router: false, reasoning: false, temperature: 0.7, max_tokens: null },
      { id: 'custom', name: '自定义（OpenAI 兼容）',
        base_url: '', model: '', api_key: '',
        glm_prompt: false, router: false, reasoning: false, temperature: null, max_tokens: null },
    ];
  }

  /** 一次性迁移：把旧的三把 key 搬进种子 Provider，然后删旧 key */
  function _migrateLegacyKeys() {
    var moved = false;
    var legacyMap = {
      'deepseek-routed': _lsGet(DS_STORAGE_KEY),
      'glm-routed': _lsGet(GLM_STORAGE_KEY),
      'agnes': _lsGet(AGNES_STORAGE_KEY),
    };
    var list = _seedProviders();
    Object.keys(legacyMap).forEach(function(id) {
      var key = legacyMap[id];
      if (key) {
        var p = list.find(function(x) { return x.id === id; });
        if (p) { p.api_key = key; moved = true; }
      }
    });
    return { list: list, moved: moved };
  }

  function _saveProviders(list) {
    _lsSet(PROVIDERS_STORAGE_KEY, JSON.stringify(list));
  }

  /** 读取 Provider 列表（首次自动种子 + 迁移旧 key） */
  function getProviders() {
    var raw = _lsGet(PROVIDERS_STORAGE_KEY);
    if (!raw) {
      var migrated = _migrateLegacyKeys();
      _saveProviders(migrated.list);
      // 迁移完成即删旧 key（仅当本函数首次种出列表时删一次）
      if (raw === null) {
        _lsRemove(DS_STORAGE_KEY);
        _lsRemove(GLM_STORAGE_KEY);
        _lsRemove(AGNES_STORAGE_KEY);
      }
      return migrated.list;
    }
    try {
      var arr = JSON.parse(raw);
      if (Array.isArray(arr) && arr.length) {
        // 补缺省字段（老数据可能没有新开关）
        arr.forEach(function(p) {
          if (p.base_url === undefined) p.base_url = '';
          if (p.model === undefined) p.model = '';
          if (p.glm_prompt === undefined) p.glm_prompt = false;
          if (p.router === undefined) p.router = false;
          if (p.reasoning === undefined) p.reasoning = false;
        });
        return arr;
      }
    } catch (e) { /* 损坏则重建 */ }
    var seed = _seedProviders();
    _saveProviders(seed);
    return seed;
  }

  /** 整体保存 Provider 列表 */
  function setProviders(list) {
    if (!Array.isArray(list)) return;
    _saveProviders(list);
  }

  /** 按 id 找一个 Provider */
  function getProvider(id) {
    if (!id) return null;
    return getProviders().find(function(p) { return p.id === id; }) || null;
  }

  /** 新增 Provider，返回完整对象（带新 id） */
  function addProvider(item) {
    var p = Object.assign({}, {
      id: 'p' + Date.now().toString(36) + Math.floor(Math.random() * 1e6).toString(36),
      name: '新 Provider', base_url: '', model: '', api_key: '',
      glm_prompt: false, router: false, reasoning: false, temperature: null, max_tokens: null,
    }, item || {});
    var list = getProviders();
    list.push(p);
    setProviders(list);
    return p;
  }

  /** 整体更新某个 Provider（按 id 定位；找不到就追加） */
  function upsertProvider(item) {
    if (!item || !item.id) return null;
    var list = getProviders();
    var idx = list.findIndex(function(p) { return p.id === item.id; });
    if (idx >= 0) list[idx] = item; else list.push(item);
    setProviders(list);
    return item;
  }

  /** 删除 Provider */
  function removeProvider(id) {
    var list = getProviders();
    setProviders(list.filter(function(p) { return p.id !== id; }));
    // 若删的是当前选中项，回退到第一条
    if (_lsGet(MODEL_STORAGE_KEY) === id) setSelectedProvider(list.length ? list[0].id : 'glm-routed');
  }

  /** 复制一个 Provider（新 id） */
  function duplicateProvider(id) {
    var src = getProvider(id);
    if (!src) return null;
    var copy = JSON.parse(JSON.stringify(src));
    copy.id = 'p' + Date.now().toString(36) + Math.floor(Math.random() * 1e6).toString(36);
    copy.name = (src.name || 'Provider') + ' 副本';
    return addProvider(copy);
  }

  // ===== 兼容别名：老代码 getApiKey()/getGLMApiKey()/getAgnesApiKey() =====
  function _entryKey(id) { var p = getProvider(id); return p ? (p.api_key || '') : ''; }
  function _setEntryKey(id, key) {
    var list = getProviders();
    var p = list.find(function(x) { return x.id === id; });
    if (p) { p.api_key = key || ''; setProviders(list); }
  }
  function getApiKey()    { return _entryKey('deepseek-routed'); }
  function setApiKey(key) { _setEntryKey('deepseek-routed', key); }
  function getGLMApiKey() { return _entryKey('glm-routed'); }
  function setGLMApiKey(key) { _setEntryKey('glm-routed', key); }
  function getAgnesApiKey() { return _entryKey('agnes'); }
  function setAgnesApiKey(key) { _setEntryKey('agnes', key); }

  /** 从 localStorage 读取保存的高德地图密钥（保持独立，不并入 Provider 列表） */
  function getAmapKey() {
    return _lsGet(AMAP_STORAGE_KEY) || '';
  }
  function setAmapKey(key) {
    if (key) { _lsSet(AMAP_STORAGE_KEY, key); } else { _lsRemove(AMAP_STORAGE_KEY); }
  }

  /** 读取数据下载服务账号凭据（Copernicus / USGS / GSCloud），不存在返回空对象 */
  function getGeoCredentials() {
    try {
      var raw = _lsGet(GEO_CRED_STORAGE_KEY);
      if (!raw) return {};
      var obj = typeof raw === 'string' ? JSON.parse(raw) : raw;
      return (obj && typeof obj === 'object') ? obj : {};
    } catch (e) { return {}; }
  }
  /** 保存数据下载服务账号凭据 */
  function setGeoCredentials(creds) {
    _lsSet(GEO_CRED_STORAGE_KEY, JSON.stringify(creds || {}));
  }
  /** 更新单个服务凭据（保留其他服务）。cred 为对象：{type:'account',username,password} 或 {type:'key',api_key} */
  function setGeoCredential(service, cred) {
    var all = getGeoCredentials();
    all[service] = (cred && typeof cred === 'object') ? cred : {};
    setGeoCredentials(all);
    return all;
  }

  // ===== 当前选中 Provider =====
  /** 读取当前选中 Provider 的 id（默认 glm-routed） */
  function getSelectedModel() {
    var id = _lsGet(MODEL_STORAGE_KEY) || 'glm-routed';
    return getProvider(id) ? id : 'glm-routed';
  }

  /** 保存当前选中的 Provider id */
  function setSelectedModel(model) {
    if (model && getProvider(model)) _lsSet(MODEL_STORAGE_KEY, model);
  }
  function setSelectedProvider(id) { setSelectedModel(id); }

  /** 取当前选中的 Provider 对象（深拷贝，避免外部误改） */
  function currentProvider() {
    var p = getProvider(getSelectedModel());
    return p ? JSON.parse(JSON.stringify(p)) : null;
  }

  /**
   * 解析一个 Provider 参数（兼容旧调用）：
   *   - 对象（含 base_url）→ 直接用
   *   - 字符串 id / null → 从列表取，取不到回退当前选中
   * 找不到时给一份「legacy 默认」占位，保证老 provider 名字仍能发请求。
   */
  function resolveProvider(p) {
    if (p && typeof p === 'object' && p.base_url !== undefined) return JSON.parse(JSON.stringify(p));
    var id = (typeof p === 'string' && p) ? p : getSelectedModel();
    var found = getProvider(id);
    if (found) return JSON.parse(JSON.stringify(found));
    // 兜底：deepseek 形态，api_key 由老 key 别名给（尽力而为）
    return { id: id || 'deepseek', name: id || 'deepseek', base_url: 'https://api.deepseek.com',
             model: 'deepseek-chat', api_key: _entryKey('deepseek-routed'),
             glm_prompt: false, router: true, reasoning: false, temperature: 0.7, max_tokens: null };
  }

  // ===== 模型状态追踪（按 Provider id） =====
  function getModelStatus(provider) {
    try {
      var stored = JSON.parse(_lsGet(MODEL_STATUS_KEY)) || {};
      return stored[provider] || 'untested';
    } catch (e) {
      return 'untested';
    }
  }
  function setModelStatus(provider, status) {
    try {
      var stored = JSON.parse(_lsGet(MODEL_STATUS_KEY)) || {};
      stored[provider] = status;
      _lsSet(MODEL_STATUS_KEY, JSON.stringify(stored));
    } catch (e) {}
  }
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
  /**
   * 普通聊天请求。
   * @param {string} message
   * @param {string} [sessionId='default']
   * @param {ProviderItem|string} [provider] Provider 对象或 id；缺省用当前选中项
   * @param {string[]} [forceSkills=[]]
   */
  async function chat(message, sessionId = 'default', provider = null, forceSkills = []) {
    // 解析出完整 Provider 条目作为唯一配置来源
    const prov = resolveProvider(provider);
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
          provider: prov.id || 'deepseek',
          api_key: prov.api_key || undefined,   // 迁移兼容
          llm_config: prov,                      // 主数据源
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
  }

  // ===== 测试 LLM 连接（通用） =====
  /** 通用测速：入参即 Provider 条目（llm_config） */
  async function testProvider(prov) {
    const resolved = resolveProvider(prov);
    const res = await fetch(`${BASE_URL}/api/test-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        llm_config: resolved,
        provider: resolved.id || '',
        api_key: resolved.api_key || '',
      }),
    });
    if (!res.ok) throw new Error(`测试连接失败: ${res.status}`);
    // 返回 { success: true/false, message: "连接成功 ✓" / "密钥无效" }
    return res.json();
  }

  // ===== 兼容旧测速入口 =====
  /** 向后端发一个测试请求，验证 DeepSeek 密钥能不能用 */
  async function testApiKey(apiKey) {
    const res = await fetch(`${BASE_URL}/api/test-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'deepseek', api_key: apiKey }),
    });
    if (!res.ok) throw new Error(`测试连接失败: ${res.status}`);
    return res.json();
  }

  /** 向后端发一个测试请求，验证 GLM 密钥能不能用 */
  async function testGLMApiKey(apiKey) {
    const res = await fetch(`${BASE_URL}/api/test-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'glm', api_key: apiKey }),
    });
    if (!res.ok) throw new Error(`测试连接失败: ${res.status}`);
    return res.json();
  }

  /** 向后端发一个测试请求，验证 Agnes 密钥能不能用 */
  async function testAgnesApiKey(apiKey) {
    const res = await fetch(`${BASE_URL}/api/test-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'agnes', api_key: apiKey }),
    });
    if (!res.ok) throw new Error(`测试连接失败: ${res.status}`);
    return res.json();
  }

  // ===== 图层管理 =====
  async function getLayers()        { /* TODO: GET /layers */ }
  async function getLayer(layerId)  { /* TODO: GET /layers/:id */ }
  async function deleteLayer(layerId) { /* TODO: DELETE /layers/:id */ }

  /** 通知后端取消注册已删除的图层 */
  async function unregisterLayer(name) {
    try {
      await fetch(`${BASE_URL}/api/layer/unregister`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
    } catch (e) {
      console.warn('[GIS API] 取消注册图层失败', e);
    }
  }

  /** 通知后端注册新加载的图层（名字 + GeoJSON） */
  async function registerLayer(name, geojson) {
    try {
      await fetch(`${BASE_URL}/api/layer/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, geojson }),
      });
    } catch (e) {
      console.warn('[GIS API] 注册图层失败', e);
    }
  }

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
  async function saveProject(data) {
    const res = await fetch(`${BASE_URL}/api/projects`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(`保存工程失败: ${res.status}`);
    return res.json();
  }
  async function loadProject(id) {
    const res = await fetch(`${BASE_URL}/api/projects/${id}`);
    if (!res.ok) throw new Error(`加载工程失败: ${res.status}`);
    return res.json();
  }
  async function listProjects() {
    const res = await fetch(`${BASE_URL}/api/projects`);
    if (!res.ok) throw new Error(`获取工程列表失败: ${res.status}`);
    return res.json();
  }
  async function deleteProject(id) {
    const res = await fetch(`${BASE_URL}/api/projects/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`删除工程失败: ${res.status}`);
    return res.json();
  }
  async function renameProject(id, name) {
    const res = await fetch(`${BASE_URL}/api/projects/${id}/rename`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name}),
    });
    if (!res.ok) throw new Error(`重命名工程失败: ${res.status}`);
    return res.json();
  }
  async function exportProject(id) {
    const res = await fetch(`${BASE_URL}/api/projects/${id}/export`);
    if (!res.ok) throw new Error(`导出工程失败: ${res.status}`);
    return res.blob();
  }
  async function deleteAllProjects() {
    const res = await fetch(`${BASE_URL}/api/projects`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`删除全部工程失败: ${res.status}`);
    return res.json();
  }
  async function autoSaveProject() {
    const res = await fetch(`${BASE_URL}/api/projects/auto-save`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
    });
    if (!res.ok) throw new Error(`自动保存失败: ${res.status}`);
    return res.json();
  }

  // ===== 清除记忆 =====
  async function clearMemory(sessionId = 'default') {
    const res = await fetch(`${BASE_URL}/api/chat/memory?session_id=${sessionId}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(`清除记忆失败: ${res.status}`);
    return res.json();
  }

  // ===== 系统 =====
  async function healthCheck() {
    try {
      const res = await fetch(`${BASE_URL}/api/health`);
      if (!res.ok) return { ok: false, status: res.status };
      return await res.json();
    } catch (e) {
      return { ok: false, message: e.message };
    }
  }

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

  /** 导出图层为 SHP（调后端接口） */
  async function exportShp(geojson, name) {
    try {
      const res = await fetch(`${BASE_URL}/api/layer/export-shp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ geojson, name: name || '图层' }),
      });
      if (!res.ok) throw new Error(`SHP 导出失败: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = (name || '图层').replace(/[\/\\]/g, '_') + '.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function')
        window.GIS.chat.addMessage('SHP 导出失败: ' + (e.message || e), 'system');
    }
  }

  return {
    request, upload, chat, clearMemory, healthCheck,
    getLayers, getLayer, deleteLayer,
    downloadLayer, executeGISAction, getBoundary,
    saveProject, loadProject, listProjects,
    deleteProject, deleteAllProjects, renameProject, exportProject, autoSaveProject,
    healthCheck, testApiKey, testGLMApiKey, testAgnesApiKey, testProvider,
    getApiKey, setApiKey, getGLMApiKey, setGLMApiKey,
    getAgnesApiKey, setAgnesApiKey,
    getAmapKey, setAmapKey,
    getGeoCredentials, setGeoCredentials, setGeoCredential,
    getSelectedModel, setSelectedModel, setSelectedProvider,
    getProviders, setProviders, getProvider,
    addProvider, upsertProvider, removeProvider, duplicateProvider,
    currentProvider, resolveProvider,
    getModelStatus, setModelStatus, clearModelStatus,
    inspectLayer, unregisterLayer, registerLayer,
    exportShp,
    BASE_URL, PROVIDERS_STORAGE_KEY,
    DS_STORAGE_KEY, GLM_STORAGE_KEY, AGNES_STORAGE_KEY, AMAP_STORAGE_KEY, MODEL_STORAGE_KEY, MODEL_STATUS_KEY,
  };
})();

// ===== 全局下载函数 =====
window.downloadGeoJSON = function(layerId) {
  const layers = GIS.layers.getLayers();
  if (!layers || layers.length === 0) return;
  if (!layerId) layerId = layers[0].layer_id;
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
