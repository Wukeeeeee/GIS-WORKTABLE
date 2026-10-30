/**
 * GIS AI WorkTable — API 接口层
 * 后端请求、模型配置与文件操作
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

// 全局 Toast 提示组件（轻量浮动在工作区顶部，带淡入淡出动画，支持 success/error/warn/info）
window.GIS.toast = (function() {
  var _container = null;
  function getContainer() {
    if (!_container || !document.body.contains(_container)) {
      _container = document.createElement('div');
      _container.className = 'gis-toast-container';
      document.body.appendChild(_container);
    }
    return _container;
  }

  var ICONS = {
    success: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg>',
    error: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    warn: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
  };

  function show(msg, type, duration) {
    if (!msg) return null;
    type = type || 'info';
    duration = typeof duration === 'number' ? duration : 2800;

    var container = getContainer();
    var item = document.createElement('div');
    item.className = 'gis-toast-item gis-toast-' + type;

    var iconSpan = document.createElement('span');
    iconSpan.className = 'gis-toast-icon';
    iconSpan.innerHTML = ICONS[type] || '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';

    var textSpan = document.createElement('span');
    textSpan.className = 'gis-toast-text';
    // 自动清洗可能夹杂的 Markdown 粗体标记
    textSpan.textContent = String(msg).replace(/\*\*/g, '');

    item.appendChild(iconSpan);
    item.appendChild(textSpan);
    container.appendChild(item);

    requestAnimationFrame(function() {
      item.classList.add('gis-toast-show');
    });

    var dismissTimer = setTimeout(dismiss, duration);

    function dismiss() {
      clearTimeout(dismissTimer);
      item.classList.remove('gis-toast-show');
      item.classList.add('gis-toast-hide');
      setTimeout(function() {
        if (item.parentNode) item.parentNode.removeChild(item);
      }, 260);
    }

    item.addEventListener('click', dismiss);
    return dismiss;
  }

  return {
    show: show,
    success: function(msg, dur) { return show(msg, 'success', dur); },
    error: function(msg, dur) { return show(msg, 'error', dur || 4000); },
    warn: function(msg, dur) { return show(msg, 'warn', dur || 3500); },
    info: function(msg, dur) { return show(msg, 'info', dur); }
  };
})();
window.GIS.api = (() => {
  const BASE_URL = (function() {
    try {
      // 优先使用 localStorage 覆盖（方便部署到其他域名时配置）
      var stored = localStorage.getItem('gis_api_base_url');
      if (stored) return stored;
    } catch(e) { /* localStorage 不可用（如 Safari 无痕模式） */ }
    if (typeof window !== 'undefined' && window.location && window.location.origin && window.location.protocol.startsWith('http')) {
      return window.location.origin;
    }
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
  var _providerMemoryCache = null;
  var _providerStoragePersistent = true;
  var _selectedProviderMemory = null;
  var _selectedProviderMemoryExplicit = false;
  var _selectedProviderPersistent = true;

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
    _providerMemoryCache = list;
    try {
      localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify(list));
      _providerStoragePersistent = true;
    } catch(e) {
      _providerStoragePersistent = false;
    }
    try {
      var backendProviders = list.map(function(provider) {
        var copy = Object.assign({}, provider);
        delete copy.api_key;
        return copy;
      });
      fetch(BASE_URL + '/api/user-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ providers: backendProviders }),
      }).catch(function() {});
    } catch(e) {}
  }

  /** 读取 Provider 列表（首次自动种子 + 迁移旧 key） */
  function getProviders() {
    var raw;
    try {
      raw = localStorage.getItem(PROVIDERS_STORAGE_KEY);
    } catch(e) {
      _providerStoragePersistent = false;
      if (_providerMemoryCache) return _providerMemoryCache;
      _providerMemoryCache = _seedProviders();
      return _providerMemoryCache;
    }
    if (!_providerStoragePersistent && _providerMemoryCache) {
      _saveProviders(_providerMemoryCache);
      return _providerMemoryCache;
    }
    _providerStoragePersistent = true;
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
        _providerMemoryCache = arr;
        return arr;
      }
    } catch (e) { /* 损坏则重建 */ }
    var seed = _seedProviders();
    _saveProviders(seed);
    return seed;
  }

  function areProviderSettingsPersistent() {
    return _providerStoragePersistent && _selectedProviderPersistent;
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
    if ((_lsGet(MODEL_STORAGE_KEY) || _selectedProviderMemory) === id) {
      setSelectedModel(list.length ? list[0].id : 'glm-routed');
    }
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

  // 旧 Provider 配置缺失时，从迁移前的存储键读取默认密钥。
  function _entryKey(id) { var p = getProvider(id); return p ? (p.api_key || '') : ''; }

  /** 从 localStorage 读取保存的高德地图密钥（保持独立，不并入 Provider 列表） */
  function getAmapKey() {
    return _lsGet(AMAP_STORAGE_KEY) || '';
  }
  function setAmapKey(key) {
    if (key) { _lsSet(AMAP_STORAGE_KEY, key); } else { _lsRemove(AMAP_STORAGE_KEY); }
    return fetch(BASE_URL + '/api/user-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amap_key: key || '' }),
      }).then(async function(response) {
        var data = await response.json().catch(function() { return null; });
        if (!response.ok || !data || data.status !== 'ok') {
          throw new Error((data && (data.detail || data.message)) || ('HTTP ' + response.status));
        }
        return data;
      });
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
    var storedId = null;
    try {
      storedId = localStorage.getItem(MODEL_STORAGE_KEY);
    } catch(e) {
      _selectedProviderPersistent = false;
    }
    if ((!_providerStoragePersistent || !_selectedProviderPersistent) && _selectedProviderMemory) {
      try {
        localStorage.setItem(MODEL_STORAGE_KEY, _selectedProviderMemory);
        _selectedProviderPersistent = true;
      } catch(e) {
        _selectedProviderPersistent = false;
      }
      return getProvider(_selectedProviderMemory) ? _selectedProviderMemory : 'glm-routed';
    }
    var id = storedId || _selectedProviderMemory || 'glm-routed';
    if (getProvider(id)) {
      _selectedProviderMemory = id;
      return id;
    }
    var fallback = getProvider(_selectedProviderMemory) ? _selectedProviderMemory : 'glm-routed';
    _selectedProviderMemory = fallback;
    return fallback;
  }

  /** 保存当前选中的 Provider id */
  function setSelectedModel(model) {
    if (model && getProvider(model)) {
      _selectedProviderMemory = model;
      _selectedProviderMemoryExplicit = true;
      try {
        localStorage.setItem(MODEL_STORAGE_KEY, model);
        _selectedProviderPersistent = true;
      } catch(e) {
        _selectedProviderPersistent = false;
      }
      try {
        fetch(BASE_URL + '/api/user-settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ selected_provider: model }),
        }).catch(function() {});
      } catch(e) {}
    }
  }
  /** 从后端同步并保活用户的 Provider/API Key 配置（跨浏览器、跨重启、跨域名） */
  async function syncUserSettingsFromBackend() {
    try {
      var res = await fetch(BASE_URL + '/api/user-settings');
      if (!res.ok) return null;
      var data = await res.json();
      if (!data || typeof data !== 'object') return null;
      if (Array.isArray(data.providers)) {
        data.providers = data.providers.filter(function(provider) {
          return provider && typeof provider === 'object' && !Array.isArray(provider);
        }).map(function(provider) {
          var safeProvider = Object.assign({}, provider);
          delete safeProvider.api_key;
          return safeProvider;
        });
      }

      var updated = false;

      // 1. 同步 Provider 元数据。模型 Key 仅保留在本浏览器 localStorage。
      if (Array.isArray(data.providers) && data.providers.length > 0) {
        var localList = getProviders();
        var hasLocalKeys = localList.some(function(p) { return !!p.api_key; });

        data.providers.forEach(function(bp) {
          var backendProvider = Object.assign({}, bp);
          delete backendProvider.api_key;
          var lp = localList.find(function(x) { return x.id === bp.id; });
          if (lp) {
            if (bp.base_url && !lp.base_url) { lp.base_url = bp.base_url; updated = true; }
            if (bp.model && !lp.model) { lp.model = bp.model; updated = true; }
          } else {
            localList.push(backendProvider);
            updated = true;
          }
        });
        if (hasLocalKeys) _saveProviders(localList);

        if (updated) {
          _providerMemoryCache = localList;
          try {
            localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify(localList));
            _providerStoragePersistent = true;
          } catch(e) {
            _providerStoragePersistent = false;
          }
        }
      } else {
        var curList = getProviders();
        if (curList.some(function(p) { return !!p.api_key; })) {
          _saveProviders(curList);
        }
      }

      // 2. 同步高德 Key
      if (data.amap_key) {
        var localAmap = _lsGet(AMAP_STORAGE_KEY);
        if (!localAmap) {
          _lsSet(AMAP_STORAGE_KEY, data.amap_key);
          updated = true;
        }
      } else {
        var curAmap = _lsGet(AMAP_STORAGE_KEY);
        if (curAmap) await setAmapKey(curAmap);
      }

      // 3. 同步选中模型
      if (data.selected_provider) {
        var localSel = _lsGet(MODEL_STORAGE_KEY);
        if (!localSel && !_selectedProviderMemoryExplicit && getProvider(data.selected_provider)) {
          _selectedProviderMemory = data.selected_provider;
          _selectedProviderMemoryExplicit = false;
          try {
            localStorage.setItem(MODEL_STORAGE_KEY, data.selected_provider);
            _selectedProviderPersistent = true;
          } catch(e) {
            _selectedProviderPersistent = false;
          }
          updated = true;
        }
      }

      return { updated: updated, data: data };
    } catch(e) {
      return null;
    }
  }

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
  async function request(endpoint, options = {}) {
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

  // ===== 工具直连执行（手动面板通道，不经 AI）=====
  /** 直接调用后端 @tool 注册工具。返回 {ok, tool, response, layers, layer_ops, images, heatmap} */
  async function invokeTool(name, args = {}, signal) {
    const res = await fetch(`${BASE_URL}/api/tools/invoke`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, arguments: args }),
      signal,
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }

  /** 直连工具执行前同步；失败必须阻止后续工具使用过时数据。 */
  async function syncLayer(name) {
    if (GIS.layers && GIS.layers.syncToolLayer) {
      if (await GIS.layers.syncToolLayer(name) === false) {
        throw new Error('图层「' + name + '」同步失败，请检查连接后重试');
      }
      return;
    }
    const layer = GIS.layers && GIS.layers.getLayerByName ? GIS.layers.getLayerByName(name) : null;
    if (!layer || (!layer.geojson && !layer.raster)) return;
    const result = await registerLayer(name, layer.geojson, layer.raster);
    if (result && typeof result.registration_token === 'string') {
      const tokens = layer._registrationTokens || (layer._registrationTokens = Object.create(null));
      tokens[name] = result.registration_token;
    }
  }

  // ===== 文件上传 =====
  /** @param {File} file @param {AbortSignal} [signal] @param {string} [requestId] */
  async function upload(file, signal, requestId) {
    const formData = new FormData();
    formData.append('file', file);

    const controller = new AbortController();
    const timeoutMs = 10 * 60 * 1000;
    let timedOut = false;
    const abortFromCaller = function() { controller.abort(); };
    if (signal) {
      if (signal.aborted) throw new DOMException('Upload cancelled', 'AbortError');
      signal.addEventListener('abort', abortFromCaller, { once: true });
    }
    const timeoutId = setTimeout(function() {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    try {
      const query = requestId ? `?request_id=${encodeURIComponent(requestId)}` : '';
      let res;
      try {
        res = await fetch(`${BASE_URL}/api/upload${query}`, {
          method: 'POST',
          body: formData,
          signal: controller.signal,
        });
        if (!res.ok) {
          let message = '';
          try {
            const body = await res.json();
            message = typeof body.detail === 'string' ? body.detail
              : (typeof body.error === 'string' ? body.error : '');
          } catch (_) {}
          const error = new Error(message || `Upload API error: ${res.status}`);
          error.status = res.status;
          if (res.status === 409) error.code = 'UPLOAD_PROCESSING';
          throw error;
        }
        return await res.json();
      } catch (error) {
        if (error && ((typeof error.code === 'string' && error.code) || Number.isFinite(error.status))) throw error;
        if (signal && signal.aborted) throw error;
          if (error && error.name === 'AbortError' && !timedOut) throw error;
        const uploadError = new Error(timedOut ? 'Upload timed out' : (error && error.message || 'Upload connection failed'));
        uploadError.code = timedOut ? 'UPLOAD_TIMEOUT' : 'UPLOAD_NETWORK_ERROR';
        throw uploadError;
      }
    } finally {
      clearTimeout(timeoutId);
      if (signal) signal.removeEventListener('abort', abortFromCaller);
    }
  }

  async function getUploadStatus(requestId, signal) {
    const controller = new AbortController();
    const timeoutMs = 5000;
    let timedOut = false;
    const abortFromCaller = function() { controller.abort(); };
    if (signal) {
      if (signal.aborted) throw new DOMException('Status check cancelled', 'AbortError');
      signal.addEventListener('abort', abortFromCaller, { once: true });
    }
    const timeoutId = setTimeout(function() {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    try {
      try {
        const res = await fetch(`${BASE_URL}/api/upload/status/${encodeURIComponent(requestId)}`, {
          method: 'GET',
          signal: controller.signal,
        });
        if (!res.ok) {
          let message = `HTTP ${res.status}`;
          try { message = (await res.json()).detail || message; } catch (_) {}
          const error = new Error(message);
          error.status = res.status;
          throw error;
        }
        return await res.json();
      } catch (error) {
        if (error && ((typeof error.code === 'string' && error.code) || Number.isFinite(error.status))) throw error;
        if (signal && signal.aborted) throw error;
        if (timedOut) {
          const timeoutError = new Error('Upload status check timed out');
          timeoutError.code = 'UPLOAD_STATUS_TIMEOUT';
          throw timeoutError;
        }
        throw error;
      }
    } finally {
      clearTimeout(timeoutId);
      if (signal) signal.removeEventListener('abort', abortFromCaller);
    }
  }

  async function cancelUpload(requestId) {
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = setTimeout(function() {
      timedOut = true;
      controller.abort();
    }, 5000);
    try {
      const res = await fetch(`${BASE_URL}/api/upload/cancel/${encodeURIComponent(requestId)}`, {
        method: 'POST',
        keepalive: true,
        signal: controller.signal,
      });
      if (!res.ok) {
        let message = `HTTP ${res.status}`;
        try { message = (await res.json()).detail || message; } catch (_) {}
        const error = new Error(message);
        error.status = res.status;
        throw error;
      }
      return await res.json();
    } catch (error) {
      if (timedOut) {
        const timeoutError = new Error('Upload cancellation request timed out');
        timeoutError.code = 'UPLOAD_CANCEL_TIMEOUT';
        throw timeoutError;
      }
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // ===== 聊天 / AI =====
  /**
   * 普通聊天请求。
   * @param {string} message
   * @param {string} [sessionId='default']
   * @param {ProviderItem|string} [provider] Provider 对象或 id；缺省用当前选中项
   * @param {string[]} [forceSkills=[]]
   */
  async function chat(message, sessionId = 'default', provider = null, forceSkills = [], mode = 'full', requestId = null, callerSignal = null, privacyMode = false) {
    // 解析出完整 Provider 条目作为唯一配置来源
    const prov = resolveProvider(provider);
    const controller = new AbortController();
    const timeoutId = setTimeout(function() { controller.abort(); }, 600000);
    const abortFromCaller = function() { controller.abort(callerSignal && callerSignal.reason); };
    if (callerSignal) {
      if (callerSignal.aborted) abortFromCaller();
      else callerSignal.addEventListener('abort', abortFromCaller, { once: true });
    }
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
          llm_config: prov,                     // 含 Key 的唯一配置来源
          request_id: requestId || undefined,
          force_skills: forceSkills,
          privacy_mode: privacyMode === true,
          amap_key: getAmapKey() || undefined,
          mode: mode
        })
      });
    } finally {
      clearTimeout(timeoutId);
      if (callerSignal) callerSignal.removeEventListener('abort', abortFromCaller);
    }
    if (!res.ok) {
      let detail = '';
      try { const body = await res.json(); detail = body.detail || body.message || ''; } catch (_) {}
      throw new Error(detail || `Chat API error: ${res.status}`);
    }
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
      }),
    });
    if (!res.ok) throw new Error(`测试连接失败: ${res.status}`);
    // 返回 { success: true/false, message: "连接成功" / "密钥无效" }
    return res.json();
  }

  async function _layerRegistryRequest(action, payload, timeout) {
    const controller = new AbortController();
    const timer = setTimeout(function() { controller.abort(); }, timeout);
    try {
      const res = await fetch(`${BASE_URL}/api/layer/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(`图层同步失败: ${detail}`);
      }
      const data = await res.json();
      if (!data || data.success !== true) throw new Error(data && data.message || '后台未确认图层同步成功');
      return data;
    } catch (error) {
      if (controller.signal.aborted) throw new Error('图层同步请求超时，请稍后重试');
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  /** 只取消本次持有的注册版本，保护后来重建的同名图层。 */
  async function unregisterLayer(name, registrationToken) {
    return _layerRegistryRequest('unregister', { name, registration_token: registrationToken }, 15000);
  }

  /** 通知后端注册新加载的图层（名字 + GeoJSON）。 */
  async function registerLayer(name, geojson, raster, expectedProjectId, sensitive, registrationToken) {
    const project = GIS.project;
    const payload = { name, geojson, raster };
    if (typeof sensitive === 'boolean') payload.sensitive = sensitive;
    if (typeof registrationToken === 'string' && registrationToken) payload.registration_token = registrationToken;
    if (arguments.length >= 4 && expectedProjectId !== undefined) {
      payload.project_context = true;
      payload.expected_project_id = expectedProjectId == null ? null : expectedProjectId;
    } else if (project && typeof project.getActiveRegistryProjectId === 'function') {
      payload.project_context = true;
      payload.expected_project_id = project.getActiveRegistryProjectId();
    } else if (project && typeof project.getCurrentProjectId === 'function') {
      payload.project_context = true;
      payload.expected_project_id = project.getCurrentProjectId();
    }
    return _layerRegistryRequest('register', payload, 60000);
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
  async function projectResponseError(res, action) {
    let detail = `${action}失败: ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === 'string' && body.detail.trim()) detail = `${action}失败: ${body.detail}`;
    } catch (_) {}
    return detail;
  }
  async function exportProject(id) {
    const res = await fetch(`${BASE_URL}/api/projects/${id}/export`);
    if (!res.ok) throw new Error(await projectResponseError(res, '导出工程'));
    return res.blob();
  }
  async function importProject(file) {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${BASE_URL}/api/projects/import`, {
      method: 'POST',
      body: fd,
    });
    if (!res.ok) throw new Error(await projectResponseError(res, '导入工程'));
    return res.json();
  }
  async function deleteAllProjects() {
    const res = await fetch(`${BASE_URL}/api/projects`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`删除全部工程失败: ${res.status}`);
    return res.json();
  }
  async function autoSaveProject(sessionId, projectId, layerGroups, layerAssignments) {
    const sid = sessionId || (window.GIS.project && window.GIS.project.getCurrentSessionId ? window.GIS.project.getCurrentSessionId() : 'default');
    const pid = projectId || (window.GIS.project && window.GIS.project.getCurrentProjectId ? window.GIS.project.getCurrentProjectId() : null);
    let url = `${BASE_URL}/api/projects/auto-save?session_id=${encodeURIComponent(sid)}`;
    if (pid) url += `&project_id=${encodeURIComponent(pid)}`;
    const res = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        layer_groups: layerGroups || [],
        layer_assignments: layerAssignments || [],
      }),
    });
    if (!res.ok) throw new Error(`自动保存失败: ${res.status}`);
    return res.json();
  }

  // ===== 清除记忆 =====
  async function clearMemory(sessionId) {
    const sid = sessionId || (window.GIS.project && window.GIS.project.getCurrentSessionId ? window.GIS.project.getCurrentSessionId() : 'default');
    const res = await fetch(`${BASE_URL}/api/chat/memory?session_id=${encodeURIComponent(sid)}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(`清除记忆失败: ${res.status}`);
    return res.json();
  }

  async function resetActiveProjectContext(expectedProjectId) {
    return request('/api/projects/active/reset', {
      method: 'POST',
      body: JSON.stringify({ expected_project_id: expectedProjectId == null ? null : expectedProjectId }),
    });
  }

  async function getActiveProjectContext() {
    return request('/api/projects/active/context');
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
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          detail = body.detail || body.error || detail;
        } catch (_) {}
        throw new Error(`SHP 导出失败: ${detail}`);
      }
      const contentType = res.headers && typeof res.headers.get === 'function'
        ? (res.headers.get('content-type') || '').toLowerCase() : '';
      if (contentType.indexOf('json') >= 0) {
        let detail = '服务器未返回 ZIP 文件';
        try {
          const body = await res.json();
          detail = body.error || body.detail || detail;
        } catch (_) {}
        throw new Error(`SHP 导出失败: ${detail}`);
      }
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
      if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
        var detail = String(e.message || e);
        var message = detail.indexOf('SHP 导出失败:') === 0 ? detail : 'SHP 导出失败: ' + detail;
        if (window.GIS.utils && typeof window.GIS.utils.escapeHtml === 'function') {
          message = window.GIS.utils.escapeHtml(message);
        } else {
          message = String(message).replace(/[&<>"']/g, function(char) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char];
          });
        }
        window.GIS.chat.addMessage(message, 'system');
      }
    }
  }

  // ===== GeoSource 全球空间数据源 =====
  async function geosourceStats() {
    return request('/api/geosource/stats');
  }

  async function geosourceSearch(params = {}) {
    return request('/api/geosource/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
  }

  async function geosourceDetail(serviceId) {
    return request(`/api/geosource/service/${encodeURIComponent(serviceId)}`);
  }

  return {
    request, upload, getUploadStatus, cancelUpload, chat, clearMemory, getActiveProjectContext,
    resetActiveProjectContext, healthCheck,
    saveProject, loadProject, listProjects,
    deleteProject, deleteAllProjects, renameProject, exportProject, importProject, autoSaveProject,
    testProvider,
    getAmapKey, setAmapKey,
    getGeoCredentials, setGeoCredentials, setGeoCredential,
    getSelectedModel, setSelectedModel,
    getProviders, setProviders, getProvider, areProviderSettingsPersistent,
    addProvider, upsertProvider, removeProvider, duplicateProvider,
    currentProvider, resolveProvider,
    getModelStatus, setModelStatus,
    inspectLayer, unregisterLayer, registerLayer, syncLayer,
    exportShp,
    invokeTool,
    geosourceStats, geosourceSearch, geosourceDetail,
    syncUserSettingsFromBackend,
    BASE_URL,
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
