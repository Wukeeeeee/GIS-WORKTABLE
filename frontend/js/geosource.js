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

  async function browseArcgis(url, name) {
    if (_arcgisBusy) return;
    _arcgisBusy = true;
    var panel = document.getElementById('arcgisBrowser');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'arcgisBrowser';
      panel.style.cssText = 'position:fixed;inset:8% 5%;z-index:21000;background:var(--surface-container-lowest,#fff);border:1px solid var(--outline-variant);padding:20px;display:flex;flex-direction:column;gap:12px;box-shadow:0 12px 48px #0003;';
      document.body.appendChild(panel);
    }
    panel.style.display = 'flex';
    panel.replaceChildren();
    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:12px;';
    var title = document.createElement('strong');
    title.textContent = name + ' · 选择服务或图层';
    var close = document.createElement('button');
    close.textContent = '关闭';
    close.className = 'geosource-action-btn';
    close.onclick = function() { panel.style.display = 'none'; };
    header.append(title, close);
    var body = document.createElement('div');
    body.style.cssText = 'min-height:0;overflow:auto;display:flex;flex-direction:column;gap:8px;';
    body.textContent = '正在读取服务目录…';
    var search = document.createElement('input');
    search.type = 'search';
    search.placeholder = '筛选当前目录中的服务或图层';
    search.style.cssText = 'padding:8px;border:1px solid var(--outline-variant);background:var(--surface-container-low);color:var(--on-surface);';
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
    var summary = document.createElement('div');
    summary.style.cssText = 'font-size:12px;color:var(--on-surface-variant);';
    summary.textContent = '目录内容以服务端返回为准。';
    panel.append(header, search, summary, body);
    try {
      var base = url.split('?')[0].replace(/\/+$/, '');
      var data = await fetchWithProxy(base + '?f=json');
      if (data.error) throw new Error(data.error.message || '服务拒绝访问');
      body.replaceChildren();
      function item(label, action) {
        var btn = document.createElement('button');
        btn.className = 'geosource-action-btn';
        btn.style.cssText = 'text-align:left;justify-content:space-between;flex-shrink:0;';
        btn.textContent = label;
        btn.onclick = action;
        body.appendChild(btn);
      }
      var root = base.replace(/(\/rest\/services)(?:\/.*)?$/i, '$1');
      if (base.toLowerCase() !== root.toLowerCase()) {
        item('← 返回服务目录', function() { browseArcgis(root, 'ArcGIS'); });
      }
      (data.folders || []).forEach(function(folder) {
        item(folder + ' →', function() { browseArcgis(root + '/' + folder.split('/').map(encodeURIComponent).join('/'), folder); });
      });
      (data.services || []).forEach(function(service) {
        item(service.name + ' · ' + service.type + ' →', function() {
          browseArcgis(root + '/' + service.name.split('/').map(encodeURIComponent).join('/') + '/' + service.type, service.name);
        });
      });
      if (data.tileInfo && /\/MapServer$/i.test(base)) {
        item('加载缓存地图', function() { loadXyzLayer(base + '/tile/{z}/{y}/{x}', name); panel.style.display = 'none'; });
      }
      (data.layers || []).forEach(function(layer) {
        if (layer.type === 'Group Layer') return;
        item('加载 ' + layer.name, function() { loadArcgisFeatures(base + '/' + layer.id, name + ' - ' + layer.name, panel); });
      });
      if (data.type === 'Feature Layer' && /\/(FeatureServer|MapServer)\/\d+$/i.test(base)) {
        item('加载当前图层', function() { loadArcgisFeatures(base, name, panel); });
      }
      if (!body.childElementCount) body.textContent = '服务未提供可直接加载的图层，可能需要认证或其他协议。';
    } catch (error) {
      body.textContent = '读取服务失败：' + error.message;
    } finally { _arcgisBusy = false; }
  }

  async function loadArcgisFeatures(url, name, panel) {
    if (_arcgisBusy) return;
    _arcgisBusy = true;
    try {
      var data = await fetchWithProxy(url + '/query?where=1%3D1&outFields=*&outSR=4326&f=geojson&resultRecordCount=1000');
      if (data.error) throw new Error(data.error.message || '查询失败');
      if (data.type !== 'FeatureCollection') throw new Error('该图层不支持 GeoJSON 查询');
      loadGeoJsonLayer(data, name, 'EPSG:4326');
      panel.style.display = 'none';
      if (data.exceededTransferLimit || data.features.length >= 1000) {
        window.GIS.chat.addMessage('当前加载的是最多 1000 个要素的预览，未保证获取完整数据集。', 'system');
      }
    } catch (error) {
      var message = document.createElement('p');
      message.textContent = '加载失败：' + error.message;
      panel.appendChild(message);
    } finally { _arcgisBusy = false; }
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

  function show() {
    if (!_modal) _modal = document.getElementById('geosourceModal');
    if (!_modal) return;
    _modal.style.display = 'flex';
    var kwInput = document.getElementById('geosourceKeyword');
    if (kwInput) kwInput.focus();
    if (_lastResults.length === 0) {
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
    if (_isLoading) return;
    _currentPage = typeof targetPage === 'number' ? targetPage : 1;

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
      page: _currentPage,
      page_size: _pageSize
    };

    _isLoading = true;

    window.GIS.api.geosourceSearch(params).then(function (res) {
      _isLoading = false;
      _lastResults = res.results || [];
      _totalCount = typeof res.total === 'number' ? res.total : _lastResults.length;
      _totalPages = typeof res.total_pages === 'number' ? res.total_pages : 1;
      _currentPage = typeof res.page === 'number' ? res.page : _currentPage;

      renderResults(_lastResults);
      renderPagination();
    }).catch(function (err) {
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
      var isWms = /WMS/i.test(proto);
      var isXyz = /XYZ/i.test(proto) || /\{[xyz]\}/i.test(s.service_url || '');
      var isRest = /REST/i.test(proto);
      var isStac = /STAC/i.test(proto);
      var isWmts = /WMTS/i.test(proto);

      var protoClass = 'badge-def';
      if (isWms) protoClass = 'badge-wms';
      else if (isXyz) protoClass = 'badge-xyz';
      else if (isRest) protoClass = 'badge-rest';
      else if (isStac) protoClass = 'badge-stac';

      var canLoad = isWms || isXyz || isRest || (s.format && /geojson|json/i.test(s.format));

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
        html += '      ' + UI_ICONS.mapPlus + ' <span>' + (/ArcGIS/i.test(s.protocol || '') ? '浏览并接入' : '加载图层') + '</span>';
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
    var proto = s.protocol || '';

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

    if (/ArcGIS/i.test(proto) || /\/(?:FeatureServer|MapServer)(?:\/|$)/i.test(s.service_url) || /\/rest\/services(?:\/|$)/i.test(s.service_url)) {
      restoreBtn();
      browseArcgis(s.service_url, name);
      return;
    }

    // 1. OGC WMS 服务
    if (/WMS/i.test(proto)) {
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
    if (/XYZ/i.test(proto) || /\{[xyz]\}/i.test(s.service_url)) {
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

  function loadGeoJsonLayer(gj, name, crs) {
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

  function loadWmsSublayer(encUrl, encLayerName, encName) {
    var rawUrl = decodeURIComponent(encUrl);
    var layerName = decodeURIComponent(encLayerName);
    var name = decodeURIComponent(encName);

    // 清理 WMS URL 中的 GetCapabilities 参数，确保标准 WMS 瓦片请求正常拼接
    var cleanUrl = rawUrl.replace(/[\?&]request=getcapabilities.*$/i, '').replace(/[\?&]service=wms.*$/i, '');

    if (window.GIS.map && typeof window.GIS.map.addWmsLayer === 'function') {
      window.GIS.map.addWmsLayer(cleanUrl, layerName, name);
      if (window.GIS.layers && typeof window.GIS.layers.addLayer === 'function') {
        window.GIS.layers.addLayer({
          layer_id: 'wms_' + Date.now(),
          filename: name,
          geometry_type: 'WMS',
          crs: 'EPSG:3857/4326',
          source: 'geosource',
          visible: true
        }, true);
      }
      notifySuccess(name);
    } else {
      alert('地图组件未初始化或不支持加载 WMS 图层');
    }
  }

  function loadXyzLayer(url, name) {
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
    var url = serviceObj.service_url || serviceObj.official_url || '';
    var reasonText = reason ? ('\n\n**具体原因**：' + reason) : '';
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      var proto = serviceObj.protocol || 'REST';
      var msg = '**数据源接入指引** · ' + name + reasonText + '\n\n' +
        '此端点尚不能直接作为地图图层自动渲染，可能需要子图层、认证或指定格式。请在数据源详情中查看服务说明：\n\n' +
        '`' + url + '`';
      window.GIS.chat.addMessage(msg, 'system');
    } else {
      alert('无法直接上图：' + (reason || '该端点不支持直接矢量渲染') + '\n\n' + url);
    }
  }

  function notifySuccess(name) {
    hide();
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      window.GIS.chat.addMessage('已将空间数据源图层 **' + name + '** 加载到地图工作区！', 'system');
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
