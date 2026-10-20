// ============================================================
// geosource.js — GeoSource 全球 GIS 空间服务库（统一 SVG UI 与分页/代理模块）
// 检索 2,198+ 全球真实空间服务与 1,561+ 图层，支持多维过滤、分页浏览与一键上图
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

  async function browseArcgis(url, name) {
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
      '<label class="geosource-radio-label" title="自动分批抓取全量要素（如3,143个县全量），带实时进度与主键去重">' +
      '  <input type="radio" name="arcgisFetchMode" value="all" checked />' +
      '  <span>自动分批拉全（全量 3,000+ 县级，推荐）</span>' +
      '</label>' +
      '<label class="geosource-radio-label" title="仅快速获取前 1,000 条作为轻量预览">' +
      '  <input type="radio" name="arcgisFetchMode" value="preview" />' +
      '  <span>快速预览（前 1,000 条）</span>' +
      '</label>' +
      '<label class="geosource-radio-label" title="仅加载当前地图可视区域内的要素，极致省内存">' +
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
      var data = await fetchWithProxy(base + '?f=json');
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
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg> 返回上一级目录</span>', function() { browseArcgis(root, 'ArcGIS'); });
      }
      (data.folders || []).forEach(function(folder) {
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> ' + window.GIS.utils.escapeHtml(folder) + '</span><svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>', function() { browseArcgis(root + '/' + folder.split('/').map(encodeURIComponent).join('/'), folder); });
      });
      (data.services || []).forEach(function(service) {
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect><rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect><line x1="6" y1="6" x2="6.01" y2="6"></line><line x1="6" y1="18" x2="6.01" y2="18"></line></svg> ' + window.GIS.utils.escapeHtml(service.name) + ' · ' + window.GIS.utils.escapeHtml(service.type) + '</span><svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>', function() {
          browseArcgis(root + '/' + service.name.split('/').map(encodeURIComponent).join('/') + '/' + service.type, service.name);
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
            loadXyzLayer(base + '/tile/{z}/{y}/{x}', name);
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
          loadArcgisFeatures(base + '/' + layer.id, name + ' - ' + layer.name, panel, btn);
        });
      });
      if (data.type === 'Feature Layer' && /\/(FeatureServer|MapServer)\/\d+$/i.test(base)) {
        item('<span style="display:inline-flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg> 加载当前要素图层</span><span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:#166534;background:#dcfce7;border:1px solid #bbf7d0;padding:2px 8px;border-radius:4px;"><svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg> 加载图层</span>', function(btn) {
          loadArcgisFeatures(base, name, panel, btn);
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
      body.textContent = '读取服务失败：' + error.message;
      setArcgisProgress(panel, 'error', {
        title: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> 目录读取失败',
        desc: '无法连接到服务或服务拒绝访问：' + error.message
      });
    } finally {
      _arcgisBusy = false;
    }
  }

  async function loadArcgisFeatures(url, name, panel, clickedBtn) {
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
    if (fetchMode === 'bbox') {
      try {
        var bounds = window.GIS.map && window.GIS.map.getBounds && window.GIS.map.getBounds();
        if (bounds) {
          var west = bounds.getWest();
          var south = bounds.getSouth();
          var east = bounds.getEast();
          var north = bounds.getNorth();
          bboxParam = '&geometry=' + encodeURIComponent(west + ',' + south + ',' + east + ',' + north) +
                      '&geometryType=esriGeometryEnvelope&spatialRel=esriSpatialRelIntersects&inSR=4326';
        }
      } catch (e) {
        console.warn('[GeoSource] 获取地图视窗 BBOX 失败，使用全域查询', e);
      }
    }

    try {
      while (hasMore && currentBatch < maxBatches) {
        currentBatch++;
        var batchTitle = fetchMode === 'all'
          ? '正在拉取图层「' + name + '」（第 ' + currentBatch + ' 批）…'
          : '正在加载图层「' + name + '」…';
        var batchDesc = fetchMode === 'all'
          ? '正在通过代理请求要素（已获取 ' + allFeatures.length + ' 条）…'
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

        var data = await fetchWithProxy(queryUrl);
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
        note = '（已按当前地图可视范围精准过滤）';
      } else if (currentBatch > 1) {
        note = '（全量分批拉取完成，共 ' + currentBatch + ' 批，0 重复 0 缺失）';
      }

      setArcgisProgress(panel, 'success', {
        title: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg> 导入成功',
        desc: '已成功加载「' + name + '」共 ' + finalCount + ' 个要素至地图工作区！' + note
      });

    } catch (error) {
      setArcgisProgress(panel, 'error', {
        title: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> 导入失败',
        desc: '图层「' + name + '」加载失败：' + (error.message || '网络或格式错误') + '。可尝试选择其他模式或图层。',
        retryFn: function () {
          loadArcgisFeatures(url, name, panel, clickedBtn);
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

    // 异步加载全库统计信息
    loadStats();
  }

  function show(skipInitialSearch) {
    if (!_modal) _modal = document.getElementById('geosourceModal');
    if (!_modal) return;
    _modal.style.display = 'flex';
    var kwInput = document.getElementById('geosourceKeyword');
    if (kwInput) kwInput.focus();
    if (!skipInitialSearch && _lastResults.length === 0) {
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
      var totalSvc = (data.total_services || 11054).toLocaleString();
      var totalLyr = (data.total_layers || 18292).toLocaleString();

      var badge = document.getElementById('geosourceModalStatsBadge');
      if (badge) {
        badge.textContent = totalSvc + ' 服务 · ' + totalLyr + ' 图层';
      }
      var cardBadge = document.getElementById('geosourceServiceBadge');
      if (cardBadge) {
        cardBadge.textContent = totalSvc + ' 服务';
      }

      // 动态将真实覆盖的国家/地区注入国家筛选下拉列表
      if (data.top_countries && data.top_countries.length > 0) {
        var countrySelect = document.getElementById('geosourceCountry');
        if (countrySelect) {
          var currentVal = countrySelect.value;
          var html = '<option value="">全部国家/地区</option>';
          data.top_countries.forEach(function (c) {
            var name = c.country || '';
            if (!name) return;
            var cnt = typeof c.count === 'number' ? ' (' + c.count + ')' : '';
            html += '<option value="' + window.GIS.utils.escapeHtml(name) + '">' + window.GIS.utils.escapeHtml(name) + cnt + '</option>';
          });
          countrySelect.innerHTML = html;
          if (currentVal) countrySelect.value = currentVal;
        }
      }
    }).catch(function (e) {
      console.warn('[GeoSource] 加载统计概况失败', e);
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
      listEl.innerHTML = '<div style="text-align:center;padding:40px;color:var(--on-surface-variant,#444748);font-size:13px;">正在检索全球空间数据源...</div>';
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
        listEl.innerHTML = '<div style="text-align:center;padding:30px;color:var(--error,#ba1a1a);font-size:13px;">检索失败: ' + window.GIS.utils.escapeHtml(err.message || String(err)) + '</div>';
      }
    });
  }

  function renderResults(results) {
    var listEl = document.getElementById('geosourceResultsList');
    var countEl = document.getElementById('geosourceResultCount');
    if (countEl) {
      countEl.innerHTML = '找到 <strong>' + _totalCount + '</strong> 个空间服务（当前显示 ' + results.length + ' 条）';
    }
    if (!listEl) return;

    if (!results || results.length === 0) {
      listEl.innerHTML = '<div style="text-align:center;padding:50px;color:var(--outline,#747878);font-size:13px;">未找到匹配服务，请尝试更换关键词或清除筛选条件。</div>';
      return;
    }

    var html = '';
    results.forEach(function (s, index) {
      var proto = (s.protocol || '通用').trim();
      var capability = classifyService(s);
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
        html += '<span class="geosource-tag">' + UI_ICONS.pin + ' ' + window.GIS.utils.escapeHtml(s.country) + '</span>';
      }
      if (s.category) {
        html += '<span class="geosource-tag">' + UI_ICONS.tag + ' ' + window.GIS.utils.escapeHtml(s.category) + '</span>';
      }
      if (s.provider) {
        html += '<span class="geosource-tag">' + UI_ICONS.building + ' ' + window.GIS.utils.escapeHtml(s.provider) + '</span>';
      }
      if (s.need_no_key === '是') {
        html += '<span class="geosource-tag tag-success">' + UI_ICONS.check + ' 免Key</span>';
      }
      if (s.is_free === '是') {
        html += '<span class="geosource-tag tag-info">' + UI_ICONS.check + ' 免费</span>';
      }
      if (s.crs) {
        html += '<span class="geosource-tag">' + UI_ICONS.globe + ' ' + window.GIS.utils.escapeHtml(s.crs) + '</span>';
      }
      html += '  </div>';

      if (s.data_description) {
        html += '  <div class="geosource-card-desc" title="' + window.GIS.utils.escapeHtml(s.data_description) + '">' + window.GIS.utils.escapeHtml(s.data_description) + '</div>';
      }

      html += '  <div class="geosource-card-url-row">';
      html += '    <input type="text" readonly class="geosource-url-input" value="' + window.GIS.utils.escapeHtml(s.service_url || s.official_url || '') + '" />';
      html += '    <button class="geosource-copy-btn" onclick="window.GIS.geosource.copyUrl(\'' + encodeURIComponent(s.service_url || s.official_url || '') + '\', this)" title="复制 URL">';
      html += '      ' + UI_ICONS.copy + ' <span>复制</span>';
      html += '    </button>';
      html += '  </div>';

      html += '  <div class="geosource-card-actions">';
      html += '    <button class="geosource-action-btn" onclick="window.GIS.geosource.toggleDetails(\'' + window.GIS.utils.escapeHtml(s.service_id) + '\', this)">';
      html += '      ' + UI_ICONS.layers + ' <span>图层与详情</span>';
      html += '    </button>';
      if (canLoad && s.service_url) {
        html += '    <button class="geosource-action-btn btn-primary" onclick="window.GIS.geosource.loadService(' + index + ', this)">';
        html += '      ' + UI_ICONS.mapPlus + ' <span>' + (isRest ? '浏览并接入' : '加载图层') + '</span>';
        html += '    </button>';
      }
      if (s.official_url || s.docs_url) {
        html += '    <a class="geosource-action-btn" href="' + window.GIS.utils.escapeHtml(s.official_url || s.docs_url) + '" target="_blank" rel="noopener">';
        html += '      ' + UI_ICONS.externalLink + ' <span>官网/文档</span>';
        html += '    </a>';
      }
      html += '  </div>';

      html += '  <div class="geosource-detail-box" id="detail_' + window.GIS.utils.escapeHtml(s.service_id) + '" style="display:none;"></div>';
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
    html += '<button class="geosource-page-btn" onclick="window.GIS.geosource.goToPage(' + (_currentPage - 1) + ')" ' + (_currentPage <= 1 ? 'disabled' : '') + ' title="上一页">';
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
    html += '<button class="geosource-page-btn" onclick="window.GIS.geosource.goToPage(' + (_currentPage + 1) + ')" ' + (_currentPage >= _totalPages ? 'disabled' : '') + ' title="下一页">';
    html += UI_ICONS.chevronRight;
    html += '</button>';

    controlsEl.innerHTML = html;
  }

  function goToPage(page) {
    if (page < 1 || page > _totalPages || page === _currentPage) return;
    doSearch(page);
  }

  function copyUrl(encodedUrl, btn) {
    var url = decodeURIComponent(encodedUrl);
    if (!url) return;
    navigator.clipboard.writeText(url).then(function () {
      if (window.GIS.toast && typeof window.GIS.toast.success === 'function') {
        window.GIS.toast.success('服务 URL 已复制到剪贴板');
      }
      btn.classList.add('copied');
      var span = btn.querySelector('span');
      if (span) span.textContent = '已复制';
      setTimeout(function () {
        btn.classList.remove('copied');
        if (span) span.textContent = '复制';
      }, 1500);
    }).catch(function () {
      prompt('请按 Ctrl+C 复制服务端点 URL:', url);
    });
  }

  function toggleDetails(serviceId, btn) {
    var box = document.getElementById('detail_' + serviceId);
    if (!box) return;
    if (box.style.display === 'block') {
      box.style.display = 'none';
      btn.innerHTML = UI_ICONS.layers + ' <span>图层与详情</span>';
      return;
    }

    btn.innerHTML = UI_ICONS.layers + ' <span>加载中...</span>';
    window.GIS.api.geosourceDetail(serviceId).then(function (det) {
      btn.innerHTML = UI_ICONS.chevronUp + ' <span>收起详情</span>';
      box.style.display = 'block';

      var layers = det.layers || [];
      var dHtml = '<div class="geosource-detail-content">';
      dHtml += '<div style="font-size:11px;color:var(--on-surface-variant,#444748);margin-bottom:8px;line-height:1.5;">';
      dHtml += '<strong>数据协议:</strong> ' + window.GIS.utils.escapeHtml(det.protocol || '-') + ' &nbsp;|&nbsp; ';
      dHtml += '<strong>格式:</strong> ' + window.GIS.utils.escapeHtml(det.format || '-') + ' &nbsp;|&nbsp; ';
      dHtml += '<strong>更新频率:</strong> ' + window.GIS.utils.escapeHtml(det.update_frequency || '-') + ' &nbsp;|&nbsp; ';
      dHtml += '<strong>覆盖范围:</strong> ' + window.GIS.utils.escapeHtml(det.spatial_coverage || '-');
      dHtml += '</div>';

      if (layers.length > 0) {
        dHtml += '<div style="font-weight:600;font-size:12px;margin:8px 0 4px;color:var(--on-surface,#1c1b1b);">包含图层列表 (' + layers.length + ' 个):</div>';
        dHtml += '<div class="geosource-sublayer-list">';
        layers.forEach(function (l) {
          dHtml += '<div class="geosource-sublayer-item">';
          dHtml += '  <span class="geosource-sublayer-name">[' + l.layer_idx + '] ' + window.GIS.utils.escapeHtml(l.layer_name) + '</span>';
          if (/WMS/i.test(det.protocol || '')) {
            dHtml += '  <button class="geosource-sublayer-load-btn" onclick="window.GIS.geosource.loadWmsSublayer(\'' + encodeURIComponent(det.service_url) + '\', \'' + encodeURIComponent(l.layer_name) + '\', \'' + encodeURIComponent(det.service_name + ' - ' + l.layer_name) + '\')">' + UI_ICONS.mapPlus + ' 上图</button>';
          }
          dHtml += '</div>';
        });
        dHtml += '</div>';
      } else {
        dHtml += '<div style="font-size:11px;color:var(--outline,#747878);">该服务未列出单独命名的子图层，直接通过主服务 URL 访问。</div>';
      }
      dHtml += '</div>';
      box.innerHTML = dHtml;
    }).catch(function (e) {
      btn.innerHTML = UI_ICONS.layers + ' <span>图层与详情</span>';
      alert('获取详情失败: ' + e.message);
    });
  }

  function loadService(index, btnEl) {
    var s = typeof index === 'object' ? index : _lastResults[index];
    if (!s || !s.service_url) return;

    var name = s.service_name || s.service_id;
    var capability = classifyService(s);

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
      browseArcgis(s.service_url, name);
      return;
    }

    // 1. OGC WMS 服务
    if (capability.isWms) {
      window.GIS.api.geosourceDetail(s.service_id).then(function (det) {
        restoreBtn();
        var layerName = '';
        if (det.layers && det.layers.length > 0) {
          layerName = det.layers[0].layer_name;
        }
        loadWmsSublayer(encodeURIComponent(s.service_url), encodeURIComponent(layerName), encodeURIComponent(name));
      }).catch(function (err) {
        restoreBtn();
        loadWmsSublayer(encodeURIComponent(s.service_url), '', encodeURIComponent(name));
      });
      return;
    }

    // 2. XYZ 瓦片服务
    if (capability.isXyz) {
      restoreBtn();
      loadXyzLayer(s.service_url, name);
      return;
    }

    // 5. 默认尝试以 GeoJSON 格式加载（优先直连，CORS 失败自动回退代理）
    fetchWithProxy(s.service_url)
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
        fallbackNotifyUrl(s, name, err.message || '网络连接或 CORS 拦截失败');
      });
  }

  function fetchWithProxy(url) {
    return fetch(url, {signal: AbortSignal.timeout(15000)})
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .catch(function () {
        // 直连失败（如浏览器 CORS 拦截），自动通过后端代理重试
        var proxyUrl = (window.GIS.api.BASE_URL || '') + '/api/geosource/proxy?url=' + encodeURIComponent(url);
        return fetch(proxyUrl, {signal: AbortSignal.timeout(15000)}).then(function (res) {
          if (!res.ok) throw new Error('代理获取失败 (HTTP ' + res.status + ')');
          return res.json();
        });
      });
  }

  function _enforceMaxLayersRule(incomingName) {
    if (!window.GIS.layers || typeof window.GIS.layers.getLayers !== 'function') return;
    var list = window.GIS.layers.getLayers() || [];
    if (!list.length) return;

    // 1. 同名图层覆盖：如果已存在完全同名的图层，先替换掉该旧图层
    for (var i = list.length - 1; i >= 0; i--) {
      var existing = list[i];
      var exName = existing._rawName || existing.filename || existing.name || '';
      if (exName && exName === incomingName) {
        if (typeof window.GIS.layers.removeLayer === 'function') {
          window.GIS.layers.removeLayer(existing.layer_id, false, true);
        }
      }
    }

    // 重新获取列表
    list = window.GIS.layers.getLayers() || [];

    // 2. 全局最多 3 个图层严格上限（支持同时保留州级 + 县级等共 2~3 个图层；超过 3 个才触发淘汰）
    var MAX_LAYERS = 3;
    while (list.length >= MAX_LAYERS) {
      var oldest = list[0];
      var removedName = oldest._rawName || oldest.filename || oldest.name || '图层';
      if (typeof window.GIS.layers.removeLayer === 'function') {
        window.GIS.layers.removeLayer(oldest.layer_id, false, false);
      }
      if (window.GIS.toast && typeof window.GIS.toast.info === 'function') {
        window.GIS.toast.info('已达最多 3 个叠加图层上限，已自动替换最早图层「' + removedName + '」');
      }
      list = window.GIS.layers.getLayers() || [];
    }
  }

  function loadGeoJsonLayer(gj, name, crs) {
    _enforceMaxLayersRule(name);
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
  }

  function loadWmsSublayer(encUrl, encLayerName, encName, groupId) {
    var rawUrl = decodeURIComponent(encUrl);
    var layerName = decodeURIComponent(encLayerName);
    var name = decodeURIComponent(encName);

    // 清理 WMS URL 中的 GetCapabilities 参数，确保标准 WMS 瓦片请求正常拼接
    var cleanUrl = rawUrl.replace(/[\?&]request=getcapabilities.*$/i, '').replace(/[\?&]service=wms.*$/i, '');

    _enforceMaxLayersRule(name);

    if (window.GIS.map && typeof window.GIS.map.addWmsLayer === 'function') {
      window.GIS.map.addWmsLayer(cleanUrl, layerName, name);
      if (window.GIS.layers && typeof window.GIS.layers.addLayer === 'function') {
        window.GIS.layers.addLayer({
          layer_id: 'wms_' + Date.now(),
          filename: name,
          geometry_type: 'WMS',
          crs: 'EPSG:3857/4326',
          source: 'geosource',
          visible: true,
          groupId: groupId || null
        }, true);
      }
      notifySuccess(name);
    } else {
      alert('地图组件未初始化或不支持加载 WMS 图层');
    }
  }

  function loadXyzLayer(url, name) {
    _enforceMaxLayersRule(name);
    if (window.GIS.map && typeof window.GIS.map.addTileLayer === 'function') {
      window.GIS.map.addTileLayer(url, name);
      if (window.GIS.layers && typeof window.GIS.layers.addLayer === 'function') {
        window.GIS.layers.addLayer({
          layer_id: 'xyz_' + Date.now(),
          filename: name,
          geometry_type: 'XYZ瓦片',
          crs: 'WebMercator',
          source: 'geosource',
          visible: true
        }, true);
      }
      notifySuccess(name);
    } else {
      alert('地图组件未初始化或不支持加载瓦片图层');
    }
  }

  function fallbackNotifyUrl(serviceObj, name, reason) {
    var cleanName = (name || '').replace(/\*\*/g, '');
    if (window.GIS.toast && typeof window.GIS.toast.error === 'function') {
      window.GIS.toast.error('数据源接入失败，请在对话框查看排查指引');
    }
    var url = serviceObj.service_url || serviceObj.official_url || '';
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
    init: init,
    show: show,
    hide: hide,
    doSearch: doSearch,
    goToPage: goToPage,
    copyUrl: copyUrl,
    toggleDetails: toggleDetails,
    loadService: loadService,
    loadWmsSublayer: loadWmsSublayer,
    openWorldMap: openWorldMap,
    closeWorldMap: closeWorldMap,
    browseArcgis: browseArcgis
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
