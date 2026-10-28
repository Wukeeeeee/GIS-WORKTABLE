// ============================================================
// geosource.js — GeoSource 全球 GIS 空间服务库（统一 SVG UI 与分页/代理模块）
// 根据当前 SQLite 快照检索空间服务与图层，支持多维过滤、分页浏览与手动接入
// ============================================================

(function () {
  'use strict';

  window.GIS = window.GIS || {};

  var _modal = null;
  var _stats = null;
  var _lastResults = [];
  var _currentPage = 1;
  var _pageSize = 20;
  var _totalCount = 0;
  var _totalPages = 1;
  var _isLoading = false;
  var _searchRequestId = 0;
  var _arcgisBusy = false;
  var _pendingCredentialCallback = null;
  var _credentialPromptQueue = [];

  function isEnglish() {
    return !!(window.GIS.i18n && window.GIS.i18n.isEnglish());
  }

  function uiText(english, chinese) {
    return isEnglish() ? english : chinese;
  }

  function closeCredentialDialog() {
    var overlay = document.getElementById('geosourceCredentialModal');
    var paramInput = document.getElementById('geosourceCredentialParam');
    var keyInput = document.getElementById('geosourceCredentialValue');
    if (overlay) overlay.style.display = 'none';
    if (paramInput) paramInput.value = '';
    if (keyInput) keyInput.value = '';
    _pendingCredentialCallback = null;
  }

  function notifyCredentialDialogUnavailable() {
    var message = uiText(
      'Credential entry is unavailable. Refresh the page and try connecting again.',
      '密钥输入框未加载，请刷新页面后重试接入。'
    );
    if (window.GIS.toast && typeof window.GIS.toast.error === 'function') window.GIS.toast.error(message);
    else if (typeof window.alert === 'function') window.alert(message);
  }

  function bindCredentialDialog() {
    var overlay = document.getElementById('geosourceCredentialModal');
    if (!overlay || overlay.dataset.bound === 'true') return;
    overlay.dataset.bound = 'true';

    var paramInput = document.getElementById('geosourceCredentialParam');
    var keyInput = document.getElementById('geosourceCredentialValue');
    var cancelBtn = document.getElementById('geosourceCredentialCancelBtn');
    var withoutKeyBtn = document.getElementById('geosourceCredentialNoKeyBtn');
    var submitBtn = document.getElementById('geosourceCredentialSubmitBtn');

    function finish(value) {
      var callback = _pendingCredentialCallback;
      closeCredentialDialog();
      var nextPrompt = _credentialPromptQueue.shift();
      if (nextPrompt) showCredentialPrompt(nextPrompt);
      if (callback) callback(value);
    }

    if (cancelBtn) cancelBtn.addEventListener('click', function () { finish(null); });
    if (withoutKeyBtn) withoutKeyBtn.addEventListener('click', function () { finish({ skipCredentialPrompt: true }); });
    if (submitBtn) submitBtn.addEventListener('click', function () {
      var parameter = (paramInput && paramInput.value || '').trim();
      var key = (keyInput && keyInput.value || '').trim();
      if (!/^[A-Za-z0-9_.-]{1,64}$/.test(parameter) || !key || key.length > 4096) {
        window.alert(uiText(
          'Enter the query parameter name and API key from the provider documentation.',
          '请按服务方文档填写参数名和 API Key。参数名仅支持字母、数字、下划线、点和连字符。'
        ));
        return;
      }
      finish({ parameter: parameter, key: key });
    });
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) finish(null);
    });
    overlay.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') finish(null);
      else if (event.key === 'Enter' && submitBtn) submitBtn.click();
    });
  }

  function showCredentialPrompt(prompt) {
    var overlay = document.getElementById('geosourceCredentialModal');
    if (!overlay) {
      notifyCredentialDialogUnavailable();
      return prompt.callback(null);
    }
    _pendingCredentialCallback = prompt.callback;
    overlay.style.display = 'flex';
    if (window.GIS.i18n && typeof window.GIS.i18n.translate === 'function') window.GIS.i18n.translate(overlay);
    var title = document.getElementById('geosourceCredentialTitle');
    if (title) title.textContent = uiText('API key for: ', '接入服务：') + (prompt.service.service_name || prompt.service.service_id || 'GeoSource');
    var paramInput = document.getElementById('geosourceCredentialParam');
    var keyInput = document.getElementById('geosourceCredentialValue');
    if (paramInput) paramInput.value = prompt.parameter || '';
    if (keyInput) keyInput.value = '';
    (prompt.parameter && keyInput ? keyInput : paramInput)?.focus();
  }

  function requestCredentialForService(service, callback) {
    var overlay = document.getElementById('geosourceCredentialModal');
    if (!overlay) {
      notifyCredentialDialogUnavailable();
      return callback(null);
    }
    var prompt = { service: service || {}, callback: callback, parameter: service && service.auth_parameter || '' };
    if (_pendingCredentialCallback) {
      _credentialPromptQueue.push(prompt);
      return;
    }
    showCredentialPrompt(prompt);
  }

  function withQueryCredential(urlValue, credential) {
    if (!credential || !credential.parameter || !credential.key) return urlValue;
    var url = new URL(urlValue, window.location.href);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error(uiText('Only HTTP and HTTPS services can use this credential option.', '仅支持通过 HTTP 或 HTTPS 接入此类凭据。'));
    url.searchParams.set(credential.parameter, credential.key);
    return url.href.replace(/%7B(-y|[xyz])%7D/ig, '{$1}');
  }

  function hasUrlUserInfo(urlValue) {
    try {
      var rawUrl = String(urlValue || '').trim();
      var url = new URL(rawUrl, window.location && window.location.href || 'http://localhost/');
      var authority = rawUrl.match(/^https?:\/\/([^/?#]*)/i);
      return url.username !== '' || url.password !== '' || !!(authority && authority[1].includes('@'));
    } catch (e) {
      return false;
    }
  }

  function notifyUnsupportedUrlCredentials() {
    window.alert(uiText(
      'This service URL contains a username or password. GeoSource supports query-parameter API keys only; remove the credentials from the URL and check the provider instructions.',
      '服务地址里包含用户名或密码。GeoSource 目前只支持 URL 参数形式的 API Key；请移除账号密码，并查看服务方提供的接入说明。'
    ));
  }

  function watchCredentialTileErrors(tileLayer, credential) {
    if (!credential || !credential.key || !tileLayer || typeof tileLayer.on !== 'function') return;
    var notified = false;
    tileLayer.on('tileerror', function () {
      if (notified) return;
      notified = true;
      if (window.GIS.toast && typeof window.GIS.toast.error === 'function') {
        window.GIS.toast.error(uiText(
          'The authenticated service tile could not be loaded. If this is a public service, use HTTPS; otherwise check the key parameter and service access.',
          '带密钥的服务瓦片加载失败。若这是公网服务，请改用 HTTPS；否则请检查 Key 参数和服务权限。'
        ));
      }
    });
  }

  function geosourceTileProxyUrl(targetUrl, authParameter) {
    var proxyBase = (window.GIS.api.BASE_URL || '') + '/api/geosource/proxy';
    var encodedTarget = encodeURIComponent(String(targetUrl || ''))
      .replace(/%7B(-y|[zxys])%7D/ig, '{$1}');
    var parameter = authParameter || inferAuthParameter(targetUrl);
    return proxyBase + '?_geosource_tile=1' +
      (parameter ? '&_geosource_auth_parameter=' + encodeURIComponent(parameter) : '') +
      '&url=' + encodedTarget;
  }

  function isCredentialParameterName(name) {
    return /(?:^|[^a-z0-9])(?:api[_-]?key|token|key|password|secret|auth|credential|signature)(?:$|[^a-z0-9])/i
      .test(String(name || ''));
  }

  function inferAuthParameter(urlValue) {
    try {
      var url = new URL(String(urlValue), window.location && window.location.href || 'http://localhost/');
      var keys = Array.from(url.searchParams.keys());
      return keys.find(isCredentialParameterName) || '';
    } catch (e) {
      return '';
    }
  }

  function serviceUrlForPersistence(urlValue, authParameter) {
    var safeUrl = sanitizeServiceUrl(urlValue);
    if (!authParameter) return safeUrl;
    try {
      var url = new URL(safeUrl, window.location && window.location.href || 'http://localhost/');
      url.searchParams.delete(authParameter);
      return url.href.replace(/%7B(-y|[xyz])%7D/ig, '{$1}');
    } catch (e) {
      return safeUrl;
    }
  }

  function serviceLayerMetadata(serviceUrl, serviceType, credential, requiresAuth, sublayer, authParameterOverride) {
    var authParameter = credential && credential.parameter || authParameterOverride || inferAuthParameter(serviceUrl);
    return {
      url: serviceUrlForPersistence(serviceUrl, authParameter),
      service_type: serviceType,
      requires_auth: !!requiresAuth || !!authParameter,
      auth_parameter: authParameter || '',
      sublayer: sublayer || '',
    };
  }

  function redactCredentialText(value, credential) {
    var message = String(value == null ? '' : value);
    if (credential && credential.key) message = message.split(credential.key).join('[redacted]');
    return message;
  }

  function countryLabel(value) {
    if (!isEnglish()) return value;
    var names = {
      '全球': 'Global', '中国': 'China', '美国': 'United States', '德国': 'Germany',
      '英国': 'United Kingdom', '法国': 'France', '加拿大': 'Canada', '澳大利亚': 'Australia',
      '日本': 'Japan', '土耳其': 'Turkey', '荷兰': 'Netherlands', '南非': 'South Africa',
      '欧盟': 'European Union', '西班牙': 'Spain', '意大利': 'Italy', '瑞士': 'Switzerland',
      '印度尼西亚': 'Indonesia', '挪威': 'Norway', '新西兰': 'New Zealand',
      '芬兰': 'Finland', '巴西': 'Brazil', '印度': 'India', '墨西哥': 'Mexico',
      '韩国': 'South Korea', '瑞典': 'Sweden', '丹麦': 'Denmark'
    };
    return names[value] || value;
  }

  function categoryLabel(value) {
    if (!isEnglish()) return value;
    var names = {
      '高程': 'Elevation', 'DEM': 'Elevation', '遥感': 'Remote sensing', '气象': 'Weather',
      '水利': 'Water', '土地利用': 'Land use', '交通': 'Transport',
      '水文': 'Hydrology', '人口': 'Population', '开放政府数据': 'Open government data',
      '商业供应商': 'Commercial vendor', '测绘': 'Surveying and mapping',
      '科研': 'Research', '大学科研': 'University research', '政府': 'Government',
      '经济': 'Economy', '金融': 'Finance', '公交': 'Public transit',
      '铁路': 'Rail', '社会': 'Society', '国际组织': 'International organization',
      '互联网公共数据': 'Public web data', '开源项目': 'Open-source project',
      '未知': 'Unspecified', '全球': 'Global'
    };
    return names[value] || value;
  }

  function frequencyLabel(value) {
    if (!isEnglish()) return value;
    var names = {
      '实时': 'Real time', '每日': 'Daily', '每周': 'Weekly', '每月': 'Monthly',
      '季度': 'Quarterly', '每年': 'Annual', '年度': 'Annual', '不定期': 'Irregular',
      '未知': 'Unknown'
    };
    return names[value] || value;
  }

  function openWorldMap() {
    if (window.innerWidth <= 700 && window.GIS.workspace) window.GIS.workspace.closeDock();
    var overlay = document.getElementById('worldMapOverlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'worldMapOverlay';
      overlay.innerHTML = '<iframe title="全球空间数据地图" src="geosource_map.html?embedded=1"></iframe>';
      (document.querySelector('.main-content') || document.body).appendChild(overlay);
    }
    overlay.style.display = 'block';
    var mapArea = document.getElementById('mapArea');
    if (mapArea) mapArea.inert = true;
    hide();
  }

  function closeWorldMap() {
    var overlay = document.getElementById('worldMapOverlay');
    if (overlay) overlay.style.display = 'none';
    var mapArea = document.getElementById('mapArea');
    if (mapArea) mapArea.inert = false;
  }

  window.addEventListener('message', function(event) {
    var overlay = document.getElementById('worldMapOverlay');
    var frame = overlay && overlay.querySelector('iframe');
    if (event.origin === window.location.origin && frame && event.source === frame.contentWindow
        && event.data && event.data.type === 'geosource-close') closeWorldMap();
    if (event.origin === window.location.origin && frame && event.source === frame.contentWindow
        && event.data && event.data.type === 'geosource-select') {
      var service = event.data.service;
      if (service && typeof service.url === 'string') {
        closeWorldMap();
        loadService({service_url: service.url, service_name: service.name, protocol: service.proto});
      }
    }
  });

  var _arcgisProgressTimer = null;
  var _arcgisCloseTimeout = null;

  function setArcgisProgress(panel, state, opts) {
    opts = opts || {};
    if (_arcgisProgressTimer) {
      clearInterval(_arcgisProgressTimer);
      _arcgisProgressTimer = null;
    }
    if (_arcgisCloseTimeout) {
      clearTimeout(_arcgisCloseTimeout);
      _arcgisCloseTimeout = null;
    }

    var container = panel.querySelector('.arcgis-progress-container');
    var bar = panel.querySelector('.arcgis-progress-bar');
    var badge = panel.querySelector('.arcgis-progress-icon-badge');
    var title = panel.querySelector('.arcgis-progress-title');
    var percent = panel.querySelector('.arcgis-progress-percent');
    var desc = panel.querySelector('.arcgis-progress-desc');
    var actions = panel.querySelector('.arcgis-progress-actions');
    if (!container || !bar) return;

    container.className = 'arcgis-progress-container is-' + state;
    bar.className = 'arcgis-progress-bar';
    badge.className = 'arcgis-progress-icon-badge ' + state;
    actions.replaceChildren();

    if (state === 'loading') {
      badge.innerHTML = '<svg class="arcgis-spin" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"></path></svg>';
      title.textContent = opts.title || '正在加载中…';
      title.style.color = '';
      desc.textContent = opts.desc || '正在请求数据，请稍候…';

      var currentPct = typeof opts.initialPct === 'number' ? opts.initialPct : 15;
      bar.style.width = currentPct + '%';
      percent.style.display = 'block';
      percent.textContent = currentPct + '%';

      var startTime = Date.now();
      _arcgisProgressTimer = setInterval(function () {
        if (currentPct < 88) {
          currentPct += Math.max(1, Math.floor(Math.random() * 7));
          if (currentPct > 88) currentPct = 88;
          bar.style.width = currentPct + '%';
          percent.textContent = currentPct + '%';
        }
        var elapsed = Math.round((Date.now() - startTime) / 1000);
        if (opts.showElapsed && elapsed >= 1) {
          desc.textContent = (opts.desc || '正在请求要素并转换为 GeoJSON') + '（已耗时 ' + elapsed + ' 秒）';
        }
      }, 300);

    } else if (state === 'success') {
      bar.classList.add('success');
      bar.style.width = '100%';
      percent.style.display = 'block';
      percent.textContent = '100%';
      badge.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';
      title.innerHTML = opts.title || '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg> 导入成功';
      title.style.color = '';
      desc.textContent = opts.desc || '已成功将图层要素加载并渲染至地图工作区！';

      var viewBtn = document.createElement('button');
      viewBtn.className = 'geosource-action-btn btn-primary';
      viewBtn.style.cssText = 'padding:4px 12px;font-size:11px;background:#16a34a;border-color:#16a34a;color:#fff;cursor:pointer;';
      viewBtn.textContent = '立即查看地图';
      viewBtn.onclick = function () {
        if (_arcgisCloseTimeout) clearTimeout(_arcgisCloseTimeout);
        panel.style.display = 'none';
      };
      actions.appendChild(viewBtn);

      _arcgisCloseTimeout = setTimeout(function () {
        if (panel.style.display !== 'none' && container.classList.contains('is-success')) {
          panel.style.display = 'none';
        }
      }, 2500);

    } else if (state === 'error') {
      bar.classList.add('error');
      bar.style.width = '100%';
      percent.style.display = 'block';
      percent.textContent = '失败';
      badge.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
      title.innerHTML = opts.title || '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> 导入失败';
      title.style.color = '';
      desc.textContent = opts.desc || '网络连接或服务解析错误，请查看提示。';

      if (typeof opts.retryFn === 'function') {
        var retryBtn = document.createElement('button');
        retryBtn.className = 'geosource-action-btn';
        retryBtn.style.cssText = 'padding:4px 12px;font-size:11px;cursor:pointer;';
        retryBtn.textContent = '重试';
        retryBtn.onclick = opts.retryFn;
        actions.appendChild(retryBtn);
      }

    } else {
      // idle 就绪状态
      bar.style.width = '0%';
      percent.style.display = 'none';
      badge.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
      title.textContent = opts.title || '准备就绪';
      title.style.color = '';
      desc.textContent = opts.desc || '请点击上方目录中的图层或服务进行导入';
    }
  }

  async function browseArcgis(url, name, credential, authRequired, authParameter) {
    if (_arcgisBusy) return;
    _arcgisBusy = true;
    var panel = document.getElementById('arcgisBrowser');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'arcgisBrowser';
      document.body.appendChild(panel);
    }
    panel.style.display = 'flex';
    panel.replaceChildren();

    var header = document.createElement('div');
    header.className = 'arcgis-browser-header';
    var title = document.createElement('strong');
    title.className = 'arcgis-browser-title';
    title.textContent = name + ' · 选择服务或图层';
    var close = document.createElement('button');
    close.className = 'geosource-action-btn';
    close.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg> <span>关闭</span>';
    close.onclick = function() {
      if (_arcgisProgressTimer) clearInterval(_arcgisProgressTimer);
      if (_arcgisCloseTimeout) clearTimeout(_arcgisCloseTimeout);
      panel.style.display = 'none';
    };
    header.append(title, close);

    var search = document.createElement('input');
    search.type = 'search';
    search.placeholder = '筛选当前目录中的服务或图层';
    search.style.cssText = 'padding:8px 12px;border:1px solid var(--outline-variant);border-radius:6px;background:var(--surface-container-low);color:var(--on-surface);font-size:12px;';
    search.oninput = function() {
      var keyword = search.value.trim().toLowerCase();
      var count = 0;
      body.querySelectorAll('button').forEach(function(btn) {
        var match = btn.textContent.toLowerCase().indexOf(keyword) >= 0;
        btn.style.display = match ? '' : 'none';
        if (match) count++;
      });
      summary.textContent = count ? '当前显示 ' + count + ' 项；目录内容以服务端返回为准。' : '当前目录没有匹配项，请尝试其他关键词。';
    };

    var modeRow = document.createElement('div');
    modeRow.className = 'arcgis-browser-mode-row';
    modeRow.innerHTML = 
      '<span style="font-size:12px;font-weight:600;color:var(--on-surface);">导入方式:</span>' +
      '<label class="geosource-radio-label" title="逐批请求，单次最多 12 批、12,000 条；超过上限会提示结果不完整">' +
      '  <input type="radio" name="arcgisFetchMode" value="all" checked />' +
      '  <span>分批拉取（上限 12,000 条）</span>' +
      '</label>' +
      '<label class="geosource-radio-label" title="仅快速获取前 1,000 条作为轻量预览">' +
      '  <input type="radio" name="arcgisFetchMode" value="preview" />' +
      '  <span>快速预览（前 1,000 条）</span>' +
      '</label>' +
      '<label class="geosource-radio-label" title="只请求当前地图视窗范围，单次最多 1,000 条">' +
      '  <input type="radio" name="arcgisFetchMode" value="bbox" />' +
      '  <span>当前视窗（BBOX过滤）</span>' +
      '</label>';

    var summary = document.createElement('div');
    summary.style.cssText = 'font-size:12px;color:var(--on-surface-variant);';
    summary.textContent = '目录内容以服务端返回为准。';

    var body = document.createElement('div');
    body.className = 'arcgis-browser-body';
    body.textContent = '正在读取服务目录…';

    // 底部进度条与状态卡片（响应用户点击加载时的进度条反馈、打勾成功、打叉失败）
    var progressContainer = document.createElement('div');
    progressContainer.className = 'arcgis-progress-container';
    progressContainer.innerHTML = 
      '<div class="arcgis-progress-track">' +
      '  <div class="arcgis-progress-bar"></div>' +
      '</div>' +
      '<div class="arcgis-progress-content">' +
      '  <div class="arcgis-progress-icon-badge"></div>' +
      '  <div class="arcgis-progress-texts">' +
      '    <div class="arcgis-progress-title-row">' +
      '      <span class="arcgis-progress-title">准备就绪</span>' +
      '      <span class="arcgis-progress-percent" style="display:none;">0%</span>' +
      '    </div>' +
      '    <div class="arcgis-progress-desc">正在连接服务目录…</div>' +
      '  </div>' +
      '  <div class="arcgis-progress-actions"></div>' +
      '</div>';

    panel.append(header, search, modeRow, summary, body, progressContainer);

    setArcgisProgress(panel, 'loading', {
      title: '正在读取服务目录…',
      desc: '正在连接远程 ArcGIS 服务并获取图层元数据',
      initialPct: 20
    });

    try {
      var base = url.split('?')[0].replace(/\/+$/, '');
      var data = await fetchWithProxy(withQueryCredential(base + '?f=json', credential),
        authParameter || (credential && credential.parameter));
      if (data.error) throw new Error(data.error.message || '服务拒绝访问');
      body.replaceChildren();

      function item(htmlContent, action) {
        var btn = document.createElement('button');
        btn.className = 'geosource-action-btn';
        btn.style.cssText = 'text-align:left;justify-content:space-between;flex-shrink:0;padding:8px 12px;border-radius:6px;';
        btn.innerHTML = htmlContent;
        btn.onclick = function () { action.call(btn, btn); };
        body.appendChild(btn);
        return btn;
      }

      var root = base.replace(/(\/rest\/services)(?:\/.*)?$/i, '$1');
      if (base.toLowerCase() !== root.toLowerCase()) {
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg> 返回上一级目录</span>', function() { browseArcgis(root, 'ArcGIS', credential, authRequired, authParameter); });
      }
      (data.folders || []).forEach(function(folder) {
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> ' + window.GIS.utils.escapeHtml(folder) + '</span><svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>', function() { browseArcgis(root + '/' + folder.split('/').map(encodeURIComponent).join('/'), folder, credential, authRequired, authParameter); });
      });
      (data.services || []).forEach(function(service) {
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect><rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect><line x1="6" y1="6" x2="6.01" y2="6"></line><line x1="6" y1="18" x2="6.01" y2="18"></line></svg> ' + window.GIS.utils.escapeHtml(service.name) + ' · ' + window.GIS.utils.escapeHtml(service.type) + '</span><svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>', function() {
          browseArcgis(root + '/' + service.name.split('/').map(encodeURIComponent).join('/') + '/' + service.type, service.name, credential, authRequired, authParameter);
        });
      });
      if (data.tileInfo && /\/MapServer$/i.test(base)) {
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg> 加载缓存瓦片地图</span><span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:#1565c0;background:#e3f2fd;border:1px solid #bbdefb;padding:2px 8px;border-radius:4px;"><svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg> 上图</span>', function(btn) {
          setArcgisProgress(panel, 'loading', {
            title: '正在加载瓦片服务…',
            desc: '正在接入 ArcGIS 缓存瓦片地图',
            initialPct: 50
          });
          try {
            loadXyzLayer(withQueryCredential(base + '/tile/{z}/{y}/{x}', credential), name,
              serviceLayerMetadata(base + '/tile/{z}/{y}/{x}', 'XYZ', credential, !!authRequired));
            setArcgisProgress(panel, 'success', {
              title: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg> 导入成功',
              desc: '已成功将「' + name + '」缓存瓦片地图图层添加到工作区！'
            });
          } catch (err) {
            setArcgisProgress(panel, 'error', {
              title: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> 导入失败',
              desc: err.message || '加载瓦片图层失败'
            });
          }
        });
      }
      (data.layers || []).forEach(function(layer) {
        if (layer.type === 'Group Layer') return;
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg> 加载 ' + window.GIS.utils.escapeHtml(layer.name) + '</span><span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:#166534;background:#dcfce7;border:1px solid #bbf7d0;padding:2px 8px;border-radius:4px;"><svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg> 加载图层</span>', function(btn) {
          loadArcgisFeatures(base + '/' + layer.id, name + ' - ' + layer.name, panel, btn, credential, authParameter);
        });
      });
      if (data.type === 'Feature Layer' && /\/(FeatureServer|MapServer)\/\d+$/i.test(base)) {
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg> 加载当前要素图层</span><span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:#166534;background:#dcfce7;border:1px solid #bbf7d0;padding:2px 8px;border-radius:4px;"><svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg> 加载图层</span>', function(btn) {
          loadArcgisFeatures(base, name, panel, btn, credential, authParameter);
        });
      }

      var totalItems = body.childElementCount;
      if (!totalItems) {
        body.textContent = '服务未提供可直接加载的图层，可能需要认证或其他协议。';
        setArcgisProgress(panel, 'idle', {
          title: '目录已读取（无直接可用图层）',
          desc: '该服务未包含开放的要素图层或需要特定授权。'
        });
      } else {
        setArcgisProgress(panel, 'idle', {
          title: '准备就绪（共 ' + totalItems + ' 项）',
          desc: '请点击上方「加载 ...」按钮导入目标图层到地图工作区'
        });
      }
    } catch (error) {
      var safeError = redactCredentialText(error.message, credential);
      body.textContent = '读取服务失败：' + safeError;
      setArcgisProgress(panel, 'error', {
        title: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> 目录读取失败',
        desc: '无法连接到服务或服务拒绝访问：' + safeError
      });
    } finally {
      _arcgisBusy = false;
    }
  }

  async function loadArcgisFeatures(url, name, panel, clickedBtn, credential, authParameter) {
    if (_arcgisBusy) return;
    _arcgisBusy = true;

    var origText = '';
    var bodyBtns = panel.querySelectorAll('.arcgis-browser-body button');
    bodyBtns.forEach(function (b) { b.disabled = true; });

    if (clickedBtn) {
      origText = clickedBtn.innerHTML;
      clickedBtn.classList.add('active-loading');
      clickedBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="arcgis-spin" style="vertical-align:-2px;"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> 正在请求数据…';
    }

    var selectedModeRadio = panel.querySelector('input[name="arcgisFetchMode"]:checked');
    var fetchMode = selectedModeRadio ? selectedModeRadio.value : 'all'; // 'all' | 'preview' | 'bbox'

    var pageSize = 1000;
    var allFeatures = [];
    var seenIds = new Set();
    var offset = 0;
    var maxBatches = fetchMode === 'all' ? 12 : 1; // 自动分批最多拉取 12,000 条（避免极端小区图层超负荷），preview 仅拉 1 批
    var currentBatch = 0;
    var hasMore = true;

    // 针对 BBOX 模式，获取当前地图视窗范围
    var bboxParam = '';
    var bboxError = '';
    if (fetchMode === 'bbox') {
      try {
        var bounds = window.GIS.map && window.GIS.map.getBounds && window.GIS.map.getBounds();
        if (!bounds) throw new Error(uiText('The current map extent is unavailable. Open the map and try again.', '当前地图视窗不可用，请打开地图后重试。'));
        var west = Number(bounds.getWest());
        var south = Number(bounds.getSouth());
        var east = Number(bounds.getEast());
        var north = Number(bounds.getNorth());
        if (![west, south, east, north].every(Number.isFinite)) {
          throw new Error(uiText('The current map extent is invalid; a safe filter could not be created.', '当前地图视窗范围无效，无法安全生成筛选范围。'));
        }
        west = Math.max(-180, west);
        east = Math.min(180, east);
        south = Math.max(-90, south);
        north = Math.min(90, north);
        if (west > east || south > north) {
          throw new Error(uiText('The current map extent cannot be represented as one geographic filter. Try preview mode or adjust the map.', '当前地图视窗无法表示为单个地理范围，请改用预览模式或调整地图范围。'));
        }
        bboxParam = '&geometry=' + encodeURIComponent(west + ',' + south + ',' + east + ',' + north) +
                    '&geometryType=esriGeometryEnvelope&spatialRel=esriSpatialRelIntersects&inSR=4326';
      } catch (e) {
        bboxError = e && e.message || uiText('The current map extent is unavailable.', '当前地图视窗不可用。');
      }
    }

    try {
      if (bboxError) throw new Error(bboxError);
      while (hasMore && currentBatch < maxBatches) {
        currentBatch++;
        var batchTitle = fetchMode === 'all'
          ? '正在拉取图层「' + name + '」（第 ' + currentBatch + ' 批）…'
          : '正在加载图层「' + name + '」…';
        var batchDesc = fetchMode === 'all'
          ? '正在通过本机代理请求要素（已获取 ' + allFeatures.length + ' 条）…'
          : (fetchMode === 'bbox' ? '正在按当前地图视窗 BBOX 范围检索要素…' : '正在请求前 1000 条要素预览…');

        var initialPct = fetchMode === 'all'
          ? Math.min(85, Math.round(15 + (currentBatch - 1) * 20))
          : 18;

        setArcgisProgress(panel, 'loading', {
          title: batchTitle,
          desc: batchDesc,
          showElapsed: true,
          initialPct: initialPct
        });

        var queryUrl = url + '/query?where=1%3D1&outFields=*&outSR=4326&f=geojson&resultRecordCount=' + pageSize +
                       '&resultOffset=' + offset + bboxParam;

        var data = await fetchWithProxy(withQueryCredential(queryUrl, credential),
          authParameter || (credential && credential.parameter));
        if (data.error) throw new Error(data.error.message || '服务端查询返回错误');
        if (data.type !== 'FeatureCollection') throw new Error('该图层不支持 GeoJSON 矢量查询接口');

        var batchFeatures = data.features || [];
        if (batchFeatures.length === 0) {
          hasMore = false;
          break;
        }

        // 精准去重校验并追加
        for (var i = 0; i < batchFeatures.length; i++) {
          var feat = batchFeatures[i];
          var fid = feat.id || (feat.properties && (feat.properties.OBJECTID || feat.properties.FID || feat.properties.GEOID || feat.properties.GlobalID)) || (offset + i);
          if (!seenIds.has(fid)) {
            seenIds.add(fid);
            allFeatures.push(feat);
          }
        }

        offset += batchFeatures.length;

        // 服务端明确标记仍有超限数据时，即使返回短页也要继续按 offset 拉取。
        // 只有明确未超限，或未提供该标记且短于请求页大小时，才能结束全量分页。
        if (fetchMode !== 'all' || data.exceededTransferLimit === false ||
            (data.exceededTransferLimit !== true && batchFeatures.length < pageSize)) {
          hasMore = false;
        }

        if (clickedBtn) {
          clickedBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="arcgis-spin" style="vertical-align:-2px;"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> 已获取 ' + allFeatures.length + ' 条…';
        }
      }

      if (allFeatures.length === 0) {
        throw new Error(fetchMode === 'bbox' ? '当前地图视窗范围内未检索到任何要素，请平移或缩放地图后重试。' : '未查询到任何要素数据。');
      }

      var fullGeoJson = {
        type: 'FeatureCollection',
        features: allFeatures
      };

      loadGeoJsonLayer(fullGeoJson, name, 'EPSG:4326');

      var finalCount = allFeatures.length;
      var note = '';
      if (hasMore && currentBatch >= maxBatches) {
        note = '（已达单次安全上限 ' + (maxBatches * pageSize) + ' 条熔断，如需更多区域建议使用视窗过滤）';
      } else if (fetchMode === 'preview') {
        note = '（快速预览模式）';
      } else if (fetchMode === 'bbox') {
        note = '（已按当前地图可视范围筛选，单次最多 1,000 条）';
      } else if (currentBatch > 1) {
        note = '（分页请求完成，共 ' + currentBatch + ' 批；已按要素标识去重）';
      }

      setArcgisProgress(panel, 'success', {
        title: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg> 导入成功',
        desc: '已成功加载「' + name + '」共 ' + finalCount + ' 个要素至地图工作区！' + note
      });

    } catch (error) {
      setArcgisProgress(panel, 'error', {
        title: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> 导入失败',
        desc: '图层「' + name + '」加载失败：' + redactCredentialText(error.message || '网络或格式错误', credential) + '。可尝试选择其他模式或图层。',
        retryFn: function () {
          loadArcgisFeatures(url, name, panel, clickedBtn, credential, authParameter);
        }
      });
    } finally {
      _arcgisBusy = false;
      bodyBtns.forEach(function (b) { b.disabled = false; });
      if (clickedBtn && origText) {
        clickedBtn.classList.remove('active-loading');
        clickedBtn.innerHTML = origText;
      }
    }
  }

  // ===== SVG 图标常量 =====
  var UI_ICONS = {
    globe: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-dc7b7fb13a72.png')\"></span>",
    pin: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-2200e2433552.png')\"></span>",
    tag: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-c7c80dddd98e.png')\"></span>",
    building: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-78222f4615be.png')\"></span>",
    layers: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-56f9f4052d45.png')\"></span>",
    mapPlus: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-13e0cc2979e5.png')\"></span>",
    externalLink: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-6949d84b62dc.png')\"></span>",
    copy: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-721a32062fe3.png')\"></span>",
    check: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-eba4e2d5125d.png')\"></span>",
    chevronUp: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-969cff716fd3.png')\"></span>",
    chevronDown: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-8eb9d6e19e3b.png')\"></span>",
    chevronLeft: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-557d5feaebcb.png')\"></span>",
    chevronRight: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:13px;height:13px;--ui-icon-image:url('/assets/ui-icons/icon-5d84c0df48b8.png')\"></span>"
  };

  function init() {
    _modal = document.getElementById('geosourceModal');
    if (!_modal) return;
    bindCredentialDialog();

    // 绑定关闭按钮与背景点击
    var closeBtn = document.getElementById('geosourceCloseBtn');
    if (closeBtn) closeBtn.addEventListener('click', hide);
    _modal.addEventListener('click', function (e) {
      if (e.target === _modal) hide();
    });

    // 绑定搜索按钮与回车触发
    var searchBtn = document.getElementById('geosourceSearchBtn');
    if (searchBtn) searchBtn.addEventListener('click', function () { doSearch(1); });

    var kwInput = document.getElementById('geosourceKeyword');
    var clearBtn = document.getElementById('geosourceSearchClear');
    if (kwInput) {
      kwInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') doSearch(1);
      });
      kwInput.addEventListener('input', function () {
        if (clearBtn) {
          clearBtn.style.display = kwInput.value.trim().length > 0 ? 'inline-flex' : 'none';
        }
      });
    }

    if (clearBtn && kwInput) {
      clearBtn.addEventListener('click', function () {
        kwInput.value = '';
        clearBtn.style.display = 'none';
        kwInput.focus();
        doSearch(1);
      });
    }

    // 快捷分类芯片点击
    var chipsContainer = document.getElementById('geosourceQuickChips');
    if (chipsContainer) {
      chipsContainer.addEventListener('click', function (e) {
        var chip = e.target.closest('.geosource-chip');
        if (!chip) return;
        chipsContainer.querySelectorAll('.geosource-chip').forEach(function (c) { c.classList.remove('active'); });
        chip.classList.add('active');

        var cat = chip.dataset.cat || '';
        var catSelect = document.getElementById('geosourceCategory');
        if (catSelect) {
          catSelect.value = cat;
        }
        doSearch(1);
      });
    }

    // 筛选下拉改变自动触发搜索
    ['geosourceProtocol', 'geosourceCountry', 'geosourceCategory', 'geosourceNoKeyOnly', 'geosourceFreeOnly'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) {
        el.addEventListener('change', function () {
          if (id === 'geosourceCategory' && chipsContainer) {
            var val = el.value;
            chipsContainer.querySelectorAll('.geosource-chip').forEach(function (c) {
              c.classList.toggle('active', (c.dataset.cat || '') === val);
            });
          }
          doSearch(1);
        });
      }
    });

    // 绑定外部打开入口
    var openBtn1 = document.getElementById('openGeoSourceModalBtn');
    if (openBtn1) openBtn1.addEventListener('click', show);

    var openBtn2 = document.getElementById('connectorOpenGeoSourceBtn');
    if (openBtn2) {
      openBtn2.addEventListener('click', function () {
        if (window.GIS.connector && typeof window.GIS.connector.hide === 'function') {
          window.GIS.connector.hide();
        }
        show();
      });
    }

    var triggerBtn = document.getElementById('geosourceTrigger');
    var worldLink = document.querySelector('a[href="geosource_map.html"]');
    if (worldLink) worldLink.addEventListener('click', function(e) { e.preventDefault(); openWorldMap(); });
    if (triggerBtn) {
      triggerBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        if (e.ctrlKey || e.metaKey) {
          openWorldMap();
        } else {
          show();
        }
      });
    }

    document.addEventListener('gis:languagechange', function() {
      loadStats();
      if (_lastResults.length) {
        renderResults(_lastResults);
        renderPagination();
      }
    });

    // 异步加载全库统计信息
    loadStats();
  }

  function show(skipInitialSearch) {
    if (!_modal) _modal = document.getElementById('geosourceModal');
    if (!_modal) return;
    _modal.style.display = 'flex';
    if (window.GIS.i18n && typeof window.GIS.i18n.translate === 'function') {
      window.GIS.i18n.translate(_modal);
    }
    loadStats();
    var kwInput = document.getElementById('geosourceKeyword');
    if (kwInput) kwInput.focus();
    if (_lastResults.length) {
      renderResults(_lastResults);
      renderPagination();
    } else if (!skipInitialSearch && _lastResults.length === 0) {
      doSearch(1);
    }
  }

  function hide() {
    if (_modal) _modal.style.display = 'none';
  }

  function loadStats() {
    if (!window.GIS.api || typeof window.GIS.api.geosourceStats !== 'function') return;
    window.GIS.api.geosourceStats().then(function (data) {
      _stats = data;
      var totalSvc = Number.isFinite(Number(data.total_services)) ? Number(data.total_services).toLocaleString() : '—';
      var totalLyr = Number.isFinite(Number(data.total_layers)) ? Number(data.total_layers).toLocaleString() : '—';

      var badge = document.getElementById('geosourceModalStatsBadge');
      if (badge) {
        badge.textContent = isEnglish()
          ? totalSvc + ' services · ' + totalLyr + ' layers'
          : totalSvc + ' 服务 · ' + totalLyr + ' 图层';
      }
      var cardBadge = document.getElementById('geosourceServiceBadge');
      if (cardBadge) {
        cardBadge.textContent = totalSvc + (isEnglish() ? ' services' : ' 服务');
      }

      var meta = document.getElementById('geosourceCatalogMeta');
      if (meta) {
        var snapshotDate = data.db_modified_at ? new Date(data.db_modified_at) : null;
        var snapshotText = snapshotDate && !Number.isNaN(snapshotDate.getTime())
          ? snapshotDate.toLocaleString()
          : uiText('date unavailable', '更新时间未知');
        var statusSummary = (data.catalog_status_counts || []).map(function (item) {
          var count = Number(item.count) || 0;
          return catalogStatusLabel(item.status) + ' ' + count.toLocaleString();
        }).join(' · ');
        if (!statusSummary) statusSummary = uiText('No catalog verification status recorded', '目录未记录验证状态');
        meta.innerHTML = uiText('Snapshot: ', '目录快照：')
          + window.GIS.utils.escapeHtml(data.db_name || uiText('unknown file', '未知文件'))
          + ' · ' + uiText('modified ', '文件更新时间 ')
          + window.GIS.utils.escapeHtml(snapshotText)
          + ' · ' + uiText('recorded status: ', '目录记录状态：')
          + window.GIS.utils.escapeHtml(statusSummary)
          + ' · ' + uiText('these are catalog records, not live checks.', '以上为目录记录，不是实时连通性检测。');
      }

      // 动态将真实覆盖的国家/地区注入国家筛选下拉列表
      if (data.top_countries && data.top_countries.length > 0) {
        var countrySelect = document.getElementById('geosourceCountry');
        if (countrySelect) {
          var currentVal = countrySelect.value;
          var html = '<option value="">' + uiText('All countries/regions', '全部国家/地区') + '</option>';
          data.top_countries.forEach(function (c) {
            var name = c.country || '';
            if (!name) return;
            var cnt = typeof c.count === 'number' ? ' (' + c.count + ')' : '';
            html += '<option value="' + window.GIS.utils.escapeHtml(name) + '">' + window.GIS.utils.escapeHtml(countryLabel(name)) + cnt + '</option>';
          });
          countrySelect.innerHTML = html;
          if (currentVal) countrySelect.value = currentVal;
        }
      }
    }).catch(function (e) {
      console.warn('[GeoSource] 加载统计概况失败', e);
      var badge = document.getElementById('geosourceModalStatsBadge');
      var cardBadge = document.getElementById('geosourceServiceBadge');
      var meta = document.getElementById('geosourceCatalogMeta');
      if (badge) badge.textContent = uiText('Catalog stats unavailable', '目录统计暂不可用');
      if (cardBadge) cardBadge.textContent = uiText('Stats unavailable', '统计不可用');
      if (meta) meta.textContent = uiText('Could not read the selected catalog snapshot.', '无法读取当前目录快照信息。');
    });
  }

  function doSearch(targetPage) {
    var requestId = ++_searchRequestId;
    var requestedPage = typeof targetPage === 'number' ? targetPage : 1;

    var kw = (document.getElementById('geosourceKeyword') || {}).value || '';
    var proto = (document.getElementById('geosourceProtocol') || {}).value || '';
    var country = (document.getElementById('geosourceCountry') || {}).value || '';
    var category = (document.getElementById('geosourceCategory') || {}).value || '';
    var noKey = (document.getElementById('geosourceNoKeyOnly') || {}).checked;
    var isFree = (document.getElementById('geosourceFreeOnly') || {}).checked;

    var listEl = document.getElementById('geosourceResultsList');
    if (listEl) {
      listEl.innerHTML = '<div style="text-align:center;padding:40px;color:var(--on-surface-variant,#444748);font-size:13px;">' + uiText('Searching the geospatial data catalog…', '正在检索全球空间数据源...') + '</div>';
    }

    var params = {
      keyword: kw.trim(),
      protocol: proto.trim(),
      country: country.trim(),
      category: category.trim(),
      need_no_key: noKey ? true : null,
      is_free: isFree ? true : null,
      page: requestedPage,
      page_size: _pageSize
    };

    _isLoading = true;

    window.GIS.api.geosourceSearch(params).then(function (res) {
      if (requestId !== _searchRequestId) return;
      _isLoading = false;
      _lastResults = res.results || [];
      _totalCount = typeof res.total === 'number' ? res.total : _lastResults.length;
      _totalPages = typeof res.total_pages === 'number' ? res.total_pages : 1;
      // Commit pagination only when the request succeeds. A failed page must
      // remain retryable from the last page actually displayed to the user.
      _currentPage = typeof res.page === 'number' ? res.page : requestedPage;

      renderResults(_lastResults);
      renderPagination();
    }).catch(function (err) {
      if (requestId !== _searchRequestId) return;
      _isLoading = false;
      if (listEl) {
        listEl.innerHTML = '<div style="text-align:center;padding:30px;color:var(--error,#ba1a1a);font-size:13px;">' + uiText('Search failed: ', '检索失败: ') + window.GIS.utils.escapeHtml(err.message || String(err)) + '</div>';
      }
    });
  }

  function renderResults(results) {
    var listEl = document.getElementById('geosourceResultsList');
    var countEl = document.getElementById('geosourceResultCount');
    if (countEl) {
      countEl.innerHTML = isEnglish()
        ? 'Found <strong>' + _totalCount + '</strong> services (showing ' + results.length + ')'
        : '找到 <strong>' + _totalCount + '</strong> 个空间服务（当前显示 ' + results.length + ' 条）';
    }
    if (!listEl) return;

    if (!results || results.length === 0) {
      listEl.innerHTML = '<div style="text-align:center;padding:50px;color:var(--outline,#747878);font-size:13px;">' + uiText('No matching services. Try another keyword or clear some filters.', '未找到匹配服务，请尝试更换关键词或清除筛选条件。') + '</div>';
      return;
    }

    var html = '';
    results.forEach(function (s, index) {
      var proto = (s.protocol || uiText('General', '通用')).trim();
      var capability = classifyService(s);
      var displayUrl = safeHttpUrl(s.service_url || s.official_url || '');
      var isWms = capability.isWms;
      var isXyz = capability.isXyz;
      var isRest = capability.isRest;
      var isStac = capability.isStac;

      var protoClass = 'badge-def';
      if (isWms) protoClass = 'badge-wms';
      else if (isXyz) protoClass = 'badge-xyz';
      else if (isRest) protoClass = 'badge-rest';
      else if (isStac) protoClass = 'badge-stac';

      var canLoad = capability.canLoad;

      html += '<div class="geosource-card" data-idx="' + index + '">';
      html += '  <div class="geosource-card-header">';
      html += '    <span class="geosource-proto-tag ' + protoClass + '">' + window.GIS.utils.escapeHtml(proto) + '</span>';
      html += '    <span class="geosource-card-title" title="' + window.GIS.utils.escapeHtml(s.service_name) + '">' + window.GIS.utils.escapeHtml(s.service_name) + '</span>';
      html += '    <span class="geosource-card-id">' + window.GIS.utils.escapeHtml(s.service_id) + '</span>';
      html += '  </div>';

      html += '  <div class="geosource-card-meta">';
      if (s.country) {
        html += '<span class="geosource-tag">' + UI_ICONS.pin + ' ' + window.GIS.utils.escapeHtml(countryLabel(s.country)) + '</span>';
      }
      if (s.category) {
        html += '<span class="geosource-tag">' + UI_ICONS.tag + ' ' + window.GIS.utils.escapeHtml(categoryLabel(s.category)) + '</span>';
      }
      if (s.provider) {
        html += '<span class="geosource-tag">' + UI_ICONS.building + ' ' + window.GIS.utils.escapeHtml(s.provider) + '</span>';
      }
      if (s.need_no_key === '是') {
        html += '<span class="geosource-tag tag-success" title="' + uiText('Catalog metadata only; this does not guarantee live access.', '仅为目录标注，不保证服务当前可访问。') + '">' + UI_ICONS.check + ' ' + uiText('Catalog says no key', '目录标注免密') + '</span>';
      } else if (s.need_no_key === '否') {
        html += '<span class="geosource-tag tag-info" title="' + uiText('Catalog metadata indicates authentication is required. Only provider-documented query-parameter API keys are supported here; header auth and OAuth are not supported.', '目录元数据标注需要认证。当前仅支持按服务方文档填写 URL 参数 API Key；暂不支持请求头认证或 OAuth。') + '">' + uiText('Catalog indicates auth required', '目录标注需认证') + '</span>';
      }
      if (s.status) {
        html += '<span class="geosource-tag" title="' + uiText('Recorded catalog status; not a live availability check.', '目录中记录的状态，不是实时可用性检测。') + '">' + window.GIS.utils.escapeHtml(catalogStatusLabel(s.status)) + '</span>';
      }
      if (s.free === '部分免费') {
        html += '<span class="geosource-tag tag-info">' + UI_ICONS.check + ' ' + uiText('Partially free', '部分免费') + '</span>';
      } else if (s.is_free === '是' || s.free === '是') {
        html += '<span class="geosource-tag tag-info">' + UI_ICONS.check + ' ' + uiText('Free', '免费') + '</span>';
      }
      if (s.crs) {
        html += '<span class="geosource-tag">' + UI_ICONS.globe + ' ' + window.GIS.utils.escapeHtml(s.crs) + '</span>';
      }
      html += '  </div>';

      if (s.data_description) {
        html += '  <div class="geosource-card-desc" title="' + window.GIS.utils.escapeHtml(s.data_description) + '">' + window.GIS.utils.escapeHtml(s.data_description) + '</div>';
      }

      html += '  <div class="geosource-card-url-row">';
      if (displayUrl) {
        html += '    <input type="text" readonly class="geosource-url-input" value="' + escapeAttribute(displayUrl) + '" />';
        html += '    <button class="geosource-copy-btn" onclick="window.GIS.geosource.copyUrl(' + inlineJsString(encodeURIComponent(displayUrl)) + ', this)" title="' + uiText('Copy URL', '复制 URL') + '">';
        html += '      ' + UI_ICONS.copy + ' <span>' + uiText('Copy', '复制') + '</span>';
        html += '    </button>';
      } else {
        html += '    <span class="geosource-url-missing">' + uiText('No valid URL is listed for this catalog entry.', '目录未提供有效地址，暂时无法复制或直接接入。') + '</span>';
      }
      html += '  </div>';

      html += '  <div class="geosource-card-actions">';
      html += '    <button class="geosource-action-btn" onclick="window.GIS.geosource.toggleDetails(' + index + ', this)">';
      html += '      ' + UI_ICONS.layers + ' <span>' + uiText('Layers and details', '图层与详情') + '</span>';
      html += '    </button>';
      if (canLoad && s.service_url) {
        var connectLabel = s.need_no_key === '否'
          ? uiText('Enter key and connect', '填写 Key 后接入')
          : (isRest ? uiText('Browse and connect', '浏览并接入') : uiText('Add layer', '加载图层'));
        html += '    <button class="geosource-action-btn btn-primary" onclick="window.GIS.geosource.loadService(' + index + ', this)">';
        html += '      ' + UI_ICONS.mapPlus + ' <span>' + connectLabel + '</span>';
        html += '    </button>';
      }
      var officialHref = safeHttpUrl(s.official_url || s.docs_url);
      if (officialHref) {
        html += '    <a class="geosource-action-btn" href="' + escapeAttribute(officialHref) + '" target="_blank" rel="noopener">';
        html += '      ' + UI_ICONS.externalLink + ' <span>' + uiText('Website / docs', '官网/文档') + '</span>';
        html += '    </a>';
      }
      html += '  </div>';

      html += '  <div class="geosource-detail-box" id="detail_' + index + '" style="display:none;"></div>';
      html += '</div>';
    });

    listEl.innerHTML = html;
    listEl.scrollTop = 0;
  }

  function classifyService(service) {
    var protocol = (service && service.protocol || '').trim();
    var url = (service && service.service_url) || '';
    var isWms = /WMS/i.test(protocol);
    var isXyz = /XYZ/i.test(protocol) || /\{[xyz]\}/i.test(url);
    var isRest = /ArcGIS/i.test(protocol) || /\/(?:FeatureServer|MapServer)(?:\/|$)/i.test(url) || /\/rest\/services(?:\/|$)/i.test(url);
    var isGeoJson = !!((service && service.format) && /geojson/i.test(service.format)) || /\.geojson(?:\?|$)/i.test(url);
    var isStac = /STAC/i.test(protocol);
    return {
      isWms: isWms,
      isXyz: isXyz,
      isRest: isRest,
      isGeoJson: isGeoJson,
      isStac: isStac,
      canLoad: isWms || isXyz || isRest || isGeoJson,
    };
  }

  function catalogStatusLabel(status) {
    var labels = {
      '已验证': uiText('Verified in catalog', '目录标记已验证'),
      '未验证': uiText('Unverified in catalog', '目录标记未验证'),
      '已停止': uiText('Listed as stopped', '目录标记已停止')
    };
    return labels[status] || (status ? String(status) : uiText('Status not recorded', '目录未记录状态'));
  }

  function escapeAttribute(value) {
    return window.GIS.utils.escapeHtml(String(value == null ? '' : value))
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function inlineJsString(value) {
    return escapeAttribute(JSON.stringify(String(value == null ? '' : value)));
  }

  function safeHttpUrl(value) {
    try {
      var raw = String(value || '').trim();
      var match = raw.match(/^(https?:\/\/[^\s（]+)/i);
      if (!match) return '';
      var url = new URL(match[1]);
      return url.protocol === 'http:' || url.protocol === 'https:' ? sanitizeServiceUrl(url.href) : '';
    } catch (e) {
      return '';
    }
  }

  function sanitizeServiceUrl(value) {
    try {
      var url = new URL(String(value), window.location.href);
      url.username = '';
      url.password = '';
      Array.from(url.searchParams.keys()).forEach(function (key) {
        if (isCredentialParameterName(key)) {
          url.searchParams.delete(key);
        }
      });
      url.hash = '';
      return url.href.replace(/%7B([xyz])%7D/ig, '{$1}');
    } catch (e) {
      return String(value || '').replace(/([?&](?:[^=]*?(?:token|key|password|secret|auth|credential|signature)[^=]*)=)[^&#]*/ig, '$1[redacted]');
    }
  }

  function renderPagination() {
    var totalEl = document.getElementById('geosourceTotalCount');
    var curEl = document.getElementById('geosourceCurrentPage');
    var totalPagesEl = document.getElementById('geosourceTotalPages');
    var controlsEl = document.getElementById('geosourcePageControls');

    if (totalEl) totalEl.textContent = _totalCount;
    if (curEl) curEl.textContent = _currentPage;
    if (totalPagesEl) totalPagesEl.textContent = _totalPages;

    if (!controlsEl) return;

    var html = '';

    // 上一页
    html += '<button class="geosource-page-btn" onclick="window.GIS.geosource.goToPage(' + (_currentPage - 1) + ')" ' + (_currentPage <= 1 ? 'disabled' : '') + ' title="' + uiText('Previous page', '上一页') + '">';
    html += UI_ICONS.chevronLeft;
    html += '</button>';

    // 页码算法（最多显示 5 个数字页码）
    var startPage = Math.max(1, _currentPage - 2);
    var endPage = Math.min(_totalPages, startPage + 4);
    if (endPage - startPage < 4) {
      startPage = Math.max(1, endPage - 4);
    }

    if (startPage > 1) {
      html += '<button class="geosource-page-btn" onclick="window.GIS.geosource.goToPage(1)">1</button>';
      if (startPage > 2) html += '<span style="padding:0 2px;color:var(--outline,#747878);">...</span>';
    }

    for (var p = startPage; p <= endPage; p++) {
      html += '<button class="geosource-page-btn ' + (p === _currentPage ? 'active' : '') + '" onclick="window.GIS.geosource.goToPage(' + p + ')">' + p + '</button>';
    }

    if (endPage < _totalPages) {
      if (endPage < _totalPages - 1) html += '<span style="padding:0 2px;color:var(--outline,#747878);">...</span>';
      html += '<button class="geosource-page-btn" onclick="window.GIS.geosource.goToPage(' + _totalPages + ')">' + _totalPages + '</button>';
    }

    // 下一页
    html += '<button class="geosource-page-btn" onclick="window.GIS.geosource.goToPage(' + (_currentPage + 1) + ')" ' + (_currentPage >= _totalPages ? 'disabled' : '') + ' title="' + uiText('Next page', '下一页') + '">';
    html += UI_ICONS.chevronRight;
    html += '</button>';

    controlsEl.innerHTML = html;
  }

  function goToPage(page) {
    if (page < 1 || page > _totalPages || page === _currentPage) return;
    doSearch(page);
  }

  function copyUrl(encodedUrl, btn) {
    var url = sanitizeServiceUrl(decodeURIComponent(encodedUrl));
    if (!url) return;
    navigator.clipboard.writeText(url).then(function () {
      if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
        window.GIS.toast.success(uiText('Service URL copied to clipboard', '服务 URL 已复制到剪贴板'));
      }
      btn.classList.add('copied');
      var span = btn.querySelector('span');
      if (span) span.textContent = uiText('Copied', '已复制');
      setTimeout(function () {
        btn.classList.remove('copied');
        if (span) span.textContent = uiText('Copy', '复制');
      }, 1500);
    }).catch(function () {
      prompt(uiText('Press Ctrl+C to copy the service endpoint URL:', '请按 Ctrl+C 复制服务端点 URL:'), url);
    });
  }

  function toggleDetails(index, btn) {
    var service = _lastResults[index];
    if (!service || service.service_id == null) return;
    var serviceId = service.service_id;
    var box = document.getElementById('detail_' + index);
    if (!box) return;
    if (box.style.display === 'block') {
      box.style.display = 'none';
      btn.innerHTML = UI_ICONS.layers + ' <span>' + uiText('Layers and details', '图层与详情') + '</span>';
      return;
    }

    btn.innerHTML = UI_ICONS.layers + ' <span>' + uiText('Loading…', '加载中...') + '</span>';
    window.GIS.api.geosourceDetail(serviceId).then(function (det) {
      btn.innerHTML = UI_ICONS.chevronUp + ' <span>' + uiText('Hide details', '收起详情') + '</span>';
      box.style.display = 'block';

      var layers = det.layers || [];
      var dHtml = '<div class="geosource-detail-content">';
      dHtml += '<div style="font-size:11px;color:var(--on-surface-variant,#444748);margin-bottom:8px;line-height:1.5;">';
      dHtml += '<strong>' + uiText('Protocol:', '数据协议:') + '</strong> ' + window.GIS.utils.escapeHtml(det.protocol || '-') + ' &nbsp;|&nbsp; ';
      dHtml += '<strong>' + uiText('Format:', '格式:') + '</strong> ' + window.GIS.utils.escapeHtml(det.format || '-') + ' &nbsp;|&nbsp; ';
      dHtml += '<strong>' + uiText('Update frequency:', '更新频率:') + '</strong> ' + window.GIS.utils.escapeHtml(frequencyLabel(det.update_frequency || '-')) + ' &nbsp;|&nbsp; ';
      dHtml += '<strong>' + uiText('Coverage:', '覆盖范围:') + '</strong> ' + window.GIS.utils.escapeHtml(countryLabel(det.spatial_coverage || '-'));
      dHtml += '</div>';

      if (layers.length > 0) {
        dHtml += '<div style="font-weight:600;font-size:12px;margin:8px 0 4px;color:var(--on-surface,#1c1b1b);">' + (isEnglish() ? 'Layers (' + layers.length + '):' : '包含图层列表 (' + layers.length + ' 个):') + '</div>';
        dHtml += '<div class="geosource-sublayer-list">';
        layers.forEach(function (l) {
          dHtml += '<div class="geosource-sublayer-item">';
          dHtml += '  <span class="geosource-sublayer-name">[' + window.GIS.utils.escapeHtml(String(l.layer_idx)) + '] ' + window.GIS.utils.escapeHtml(l.layer_name) + '</span>';
          if (/WMS/i.test(det.protocol || '')) {
            dHtml += '  <button class="geosource-sublayer-load-btn" onclick="window.GIS.geosource.loadWmsServiceSublayer(' + index + ', ' + inlineJsString(l.layer_name) + ', this)">' + UI_ICONS.mapPlus + ' ' + uiText('Add to map', '上图') + '</button>';
          }
          dHtml += '</div>';
        });
        dHtml += '</div>';
      } else {
        dHtml += '<div style="font-size:11px;color:var(--outline,#747878);">' + uiText('No separately named sublayers are listed. Access the service using its base URL.', '该服务未列出单独命名的子图层，直接通过主服务 URL 访问。') + '</div>';
      }
      dHtml += '</div>';
      box.innerHTML = dHtml;
    }).catch(function (e) {
      btn.innerHTML = UI_ICONS.layers + ' <span>' + uiText('Layers and details', '图层与详情') + '</span>';
      alert(uiText('Could not get service details: ', '获取详情失败: ') + e.message);
    });
  }

  function loadWmsServiceSublayer(index, layerName, btnEl) {
    var s = typeof index === 'object' ? index : _lastResults[index];
    if (!s || !s.service_url || !layerName) return false;
    loadService(index, btnEl, null, false, String(layerName));
    return true;
  }

  function loadService(index, btnEl, credential, skipCredentialPrompt, sublayerOverride) {
    var s = typeof index === 'object' ? index : _lastResults[index];
    if (!s || !s.service_url) return;
    if (hasUrlUserInfo(s.service_url)) {
      notifyUnsupportedUrlCredentials();
      return;
    }

    var name = s.service_name || s.service_id;
    var capability = classifyService(s);
    var catalogRequiresAuth = s.need_no_key === '否';
    var authParameter = inferAuthParameter(s.service_url) || s.auth_parameter || '';
    if ((catalogRequiresAuth || authParameter) && !credential && !skipCredentialPrompt) {
      var promptService = authParameter && !s.auth_parameter
        ? Object.assign({}, s, { auth_parameter: authParameter })
        : s;
      requestCredentialForService(promptService, function (choice) {
        if (!choice) return;
        if (choice.skipCredentialPrompt) loadService(index, btnEl, null, true, sublayerOverride);
        else loadService(index, btnEl, choice, true, sublayerOverride);
      });
      return;
    }

    var requestUrl = s.service_url;
    var authRequired = catalogRequiresAuth || !!credential || !!authParameter;
    try {
      if (credential) requestUrl = withQueryCredential(requestUrl, credential);
    } catch (err) {
      window.alert(err.message || String(err));
      return;
    }

    // 按钮反馈与防止重复点击
    var origText = '';
    if (btnEl && btnEl.querySelector) {
      var span = btnEl.querySelector('span');
      if (span) {
        origText = span.textContent;
        span.textContent = '正在连接与解析…';
      }
      btnEl.disabled = true;
    }
    function restoreBtn() {
      if (btnEl && btnEl.querySelector) {
        var span = btnEl.querySelector('span');
        if (span && origText) span.textContent = origText;
        btnEl.disabled = false;
      }
    }

    if (capability.isRest) {
      restoreBtn();
      browseArcgis(requestUrl, name, credential, authRequired, credential && credential.parameter || authParameter);
      return;
    }

    // 1. OGC WMS 服务
    if (capability.isWms) {
      window.GIS.api.geosourceDetail(s.service_id).then(function (det) {
        restoreBtn();
        var layerName = sublayerOverride || '';
        if (!layerName && det.layers && det.layers.length > 0) {
          layerName = det.layers[0].layer_name;
        }
        loadWmsSublayer(encodeURIComponent(requestUrl), encodeURIComponent(layerName), encodeURIComponent(layerName ? name + ' - ' + layerName : name), null,
          serviceLayerMetadata(s.service_url, 'WMS', credential, authRequired, layerName));
      }).catch(function (err) {
        restoreBtn();
        loadWmsSublayer(encodeURIComponent(requestUrl), encodeURIComponent(sublayerOverride || ''), encodeURIComponent(sublayerOverride ? name + ' - ' + sublayerOverride : name), null,
          serviceLayerMetadata(s.service_url, 'WMS', credential, authRequired, sublayerOverride || ''));
      });
      return;
    }

    // 2. XYZ 瓦片服务
    if (capability.isXyz) {
      restoreBtn();
      loadXyzLayer(requestUrl, name, serviceLayerMetadata(s.service_url, 'XYZ', credential, authRequired));
      return;
    }

    // 5. 默认尝试以 GeoJSON 格式加载，通过本机代理统一执行重定向安全策略
    fetchWithProxy(requestUrl, credential && credential.parameter || authParameter)
      .then(function (gj) {
        restoreBtn();
        if (gj && (gj.type === 'FeatureCollection' || gj.type === 'Feature' || gj.coordinates || gj.features)) {
          loadGeoJsonLayer(gj, name, s.crs);
        } else {
          fallbackNotifyUrl(s, name, '返回数据非有效 GeoJSON 矢量要素格式');
        }
      })
      .catch(function (err) {
        restoreBtn();
        fallbackNotifyUrl(s, name, redactCredentialText(err.message || '本机代理请求失败', credential));
      });
  }

  function fetchWithProxy(url, authParameter) {
    var proxyUrl = (window.GIS.api.BASE_URL || '') + '/api/geosource/proxy';
    var parameter = authParameter || inferAuthParameter(url);
    return fetch(proxyUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url, auth_parameter: parameter || '' }),
      signal: AbortSignal.timeout(15000)
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (payload) {
        if (!res.ok) {
          throw new Error(payload && (payload.detail || payload.message) || '代理获取失败 (HTTP ' + res.status + ')');
        }
        return payload;
      });
    });
  }

  function _enforceMaxLayersRule(incomingName) {
    if (!window.GIS.layers || typeof window.GIS.layers.getLayers !== 'function') return true;
    var list = window.GIS.layers.getLayers() || [];
    if (!list.length) return true;

    // 仅允许重新加载同名 GeoSource 图层；不能覆盖分析、上传或手动图层。
    for (var i = list.length - 1; i >= 0; i--) {
      var existing = list[i];
      var exName = existing._rawName || existing.filename || existing.name || '';
      if (exName && exName === incomingName) {
        if (existing.source !== 'geosource') {
          if (window.GIS.toast && typeof window.GIS.toast.error === 'function') {
            window.GIS.toast.error(uiText(
              'A layer with this name already exists. Rename it or remove it before loading this service.',
              '已有同名非 GeoSource 图层，请先重命名或手动移除后再加载。'
            ));
          }
          return false;
        }
        if (typeof window.GIS.layers.removeLayer === 'function') {
          window.GIS.layers.removeLayer(existing.layer_id, false, true);
        }
      }
    }

    // 保留现有三层上限，但达到上限时不自动淘汰用户已有图层。
    list = window.GIS.layers.getLayers() || [];
    var MAX_LAYERS = 3;
    if (list.length >= MAX_LAYERS) {
      if (window.GIS.toast && typeof window.GIS.toast.warn === 'function') {
        window.GIS.toast.warn(uiText(
          'The map overlay limit is 3 layers. Remove one manually before loading this service.',
          '地图叠加图层上限为 3 个，请先手动移除一个图层后再加载。'
        ));
      }
      return false;
    }
    return true;
  }

  function loadGeoJsonLayer(gj, name, crs) {
    if (!_enforceMaxLayersRule(name)) return false;
    if (window.GIS.map && typeof window.GIS.map.loadGeoJSON === 'function') {
      window.GIS.map.loadGeoJSON(gj, name);
    }
    if (window.GIS.layers && typeof window.GIS.layers.addLayer === 'function') {
      window.GIS.layers.addLayer({
        layer_id: 'gs_' + Date.now(),
        filename: name,
        geometry_type: gj.type || 'Vector',
        crs: crs || 'WGS-84',
        geojson: gj,
        source: 'geosource'
      }, false);
    }
    notifySuccess(name);
    return true;
  }

  function loadWmsSublayer(encUrl, encLayerName, encName, groupId, metadata) {
    metadata = metadata || {};
    var rawUrl = decodeURIComponent(encUrl);
    var layerName = decodeURIComponent(encLayerName);
    var name = decodeURIComponent(encName);

    // 清理 WMS URL 中的 GetCapabilities 参数，确保标准 WMS 瓦片请求正常拼接
    var cleanUrl = rawUrl.replace(/[\?&]request=getcapabilities.*$/i, '').replace(/[\?&]service=wms.*$/i, '');

    if (!_enforceMaxLayersRule(name)) return false;

    if (window.GIS.map && typeof window.GIS.map.addWmsLayer === 'function') {
      var wmsLayer = window.GIS.map.addWmsLayer(geosourceTileProxyUrl(cleanUrl,
        metadata.auth_parameter || (metadata.credential && metadata.credential.parameter)), layerName, name, { opacity: metadata.opacity });
      watchCredentialTileErrors(wmsLayer, metadata.credential);
      if (window.GIS.layers && typeof window.GIS.layers.addLayer === 'function') {
        window.GIS.layers.addLayer({
          layer_id: metadata.layer_id || ('wms_' + Date.now()),
          filename: name,
          geometry_type: 'WMS',
          crs: 'EPSG:3857/4326',
          source: 'geosource',
          visible: metadata.visible !== false,
          opacity: metadata.opacity === undefined ? 1 : metadata.opacity,
          groupId: groupId || metadata.groupId || null,
          ...serviceLayerMetadata(metadata.url || cleanUrl, 'WMS', metadata.credential,
            metadata.requires_auth, layerName, metadata.auth_parameter),
        }, true);
        if (metadata.visible === false && window.GIS.map.setLayerVisible) {
          window.GIS.map.setLayerVisible(name, false);
        }
      }
      notifySuccess(name);
      return true;
    } else {
      alert('地图组件未初始化或不支持加载 WMS 图层');
      return false;
    }
  }

  function loadXyzLayer(url, name, metadata) {
    metadata = metadata || {};
    if (!_enforceMaxLayersRule(name)) return false;
    if (window.GIS.map && typeof window.GIS.map.addTileLayer === 'function') {
      var tileLayer = window.GIS.map.addTileLayer(geosourceTileProxyUrl(url,
        metadata.auth_parameter || (metadata.credential && metadata.credential.parameter)), name, { opacity: metadata.opacity });
      watchCredentialTileErrors(tileLayer, metadata.credential);
      if (window.GIS.layers && typeof window.GIS.layers.addLayer === 'function') {
        window.GIS.layers.addLayer({
          layer_id: metadata.layer_id || ('xyz_' + Date.now()),
          filename: name,
          geometry_type: 'XYZ瓦片',
          crs: 'WebMercator',
          source: 'geosource',
          visible: metadata.visible !== false,
          opacity: metadata.opacity === undefined ? 1 : metadata.opacity,
          groupId: metadata.groupId || null,
          ...serviceLayerMetadata(metadata.url || url, 'XYZ', metadata.credential,
            metadata.requires_auth, '', metadata.auth_parameter),
        }, true);
        if (metadata.visible === false && window.GIS.map.setLayerVisible) {
          window.GIS.map.setLayerVisible(name, false);
        }
      }
      notifySuccess(name);
      return true;
    } else {
      alert('地图组件未初始化或不支持加载瓦片图层');
      return false;
    }
  }

  function loadSavedServiceLayer(layer) {
    var rawUrl = layer && (layer.url || layer.service_url);
    if (!rawUrl) return false;
    if (hasUrlUserInfo(rawUrl)) {
      notifyUnsupportedUrlCredentials();
      return false;
    }
    var serviceName = layer.filename || layer.name || rawUrl;
    var serviceType = (layer.service_type || layer.protocol || '').toLowerCase();
    var isWms = serviceType.indexOf('wms') >= 0 || String(layer.geometry_type || '').toLowerCase() === 'wms';
    var authParameter = layer.auth_parameter || inferAuthParameter(rawUrl);
    var url = serviceUrlForPersistence(rawUrl, authParameter);
    var requiresAuth = !!layer.requires_auth || !!authParameter;

    function connect(credential) {
      var runtimeUrl;
      try {
        runtimeUrl = credential ? withQueryCredential(url, credential) : url;
      } catch (error) {
        window.alert(error.message || String(error));
        return false;
      }
      var metadata = {
        url: url,
        credential: credential || null,
        requires_auth: requiresAuth,
        auth_parameter: authParameter,
        visible: layer.visible !== false,
        groupId: layer.groupId || null,
        layer_id: layer.layer_id || null,
        opacity: layer.opacity,
      };
      if (isWms) {
        return loadWmsSublayer(encodeURIComponent(runtimeUrl),
          encodeURIComponent(layer.sublayer || ''), encodeURIComponent(serviceName),
          layer.groupId || null, metadata);
      }
      return loadXyzLayer(runtimeUrl, serviceName, metadata);
    }

    if (!requiresAuth) return connect(null);
    requestCredentialForService({ service_name: serviceName, auth_parameter: authParameter }, function (choice) {
      if (!choice) return;
      connect(choice.skipCredentialPrompt ? null : choice);
    });
    return true;
  }

  function fallbackNotifyUrl(serviceObj, name, reason) {
    var cleanName = (name || '').replace(/\*\*/g, '');
    if (window.GIS.toast && typeof window.GIS.toast.error === 'function') {
      window.GIS.toast.error('数据源接入失败，请在对话框查看排查指引');
    }
    var url = sanitizeServiceUrl(serviceObj.service_url || serviceObj.official_url || '');
    var reasonText = reason ? ('\n\n**具体原因**：' + reason) : '';
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      var proto = serviceObj.protocol || 'REST';
      var msg = '**数据源接入指引** · ' + cleanName + reasonText + '\n\n' +
        '此端点尚不能直接作为地图图层自动渲染，可能需要子图层、认证或指定格式。请在数据源详情中查看服务说明：\n\n' +
        '`' + url + '`';
      window.GIS.chat.addMessage(msg, 'system', { card: true });
    } else {
      alert('无法直接上图：' + (reason || '该端点不支持直接矢量渲染') + '\n\n' + url);
    }
  }

  function notifySuccess(name) {
    hide();
    var cleanName = (name || '').replace(/\*\*/g, '');
    if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
      window.GIS.toast.success('已将空间数据源图层「' + cleanName + '」加载到地图工作区！');
    }
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('已将空间数据源图层 **' + cleanName + '** 加载到地图工作区！', 'system');
    }
  }

  window.GIS.geosource = {
    show: show,
    doSearch: doSearch,
    goToPage: goToPage,
    copyUrl: copyUrl,
    toggleDetails: toggleDetails,
    loadService: loadService,
    loadWmsServiceSublayer: loadWmsServiceSublayer,
    loadWmsSublayer: loadWmsSublayer,
    loadSavedServiceLayer: loadSavedServiceLayer,
    openWorldMap: openWorldMap,
    closeWorldMap: closeWorldMap
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
