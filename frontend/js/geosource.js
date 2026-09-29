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

  // ===== SVG 图标常量 =====
  var SVG_ICONS = {
    globe: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    pin: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
    tag: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>',
    building: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"/><line x1="9" y1="22" x2="9" y2="22.01"/><line x1="15" y1="22" x2="15" y2="22.01"/><line x1="9" y1="6" x2="9" y2="6.01"/><line x1="15" y1="6" x2="15" y2="6.01"/><line x1="9" y1="10" x2="9" y2="10.01"/><line x1="15" y1="10" x2="15" y2="10.01"/><line x1="9" y1="14" x2="9" y2="14.01"/><line x1="15" y1="14" x2="15" y2="14.01"/></svg>',
    layers: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
    mapPlus: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>',
    externalLink: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    copy: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    check: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    chevronUp: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>',
    chevronDown: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
    chevronLeft: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>',
    chevronRight: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>'
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
      var badge = document.getElementById('geosourceModalStatsBadge');
      if (badge && data) {
        badge.textContent = (data.total_services || 2198) + ' 服务 · ' + (data.total_layers || 1561) + ' 图层';
      }
      var cardBadge = document.getElementById('geosourceServiceBadge');
      if (cardBadge && data) {
        cardBadge.textContent = (data.total_services || 2198) + ' 服务';
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
        html += '<span class="geosource-tag">' + SVG_ICONS.pin + ' ' + window.GIS.utils.escapeHtml(s.country) + '</span>';
      }
      if (s.category) {
        html += '<span class="geosource-tag">' + SVG_ICONS.tag + ' ' + window.GIS.utils.escapeHtml(s.category) + '</span>';
      }
      if (s.provider) {
        html += '<span class="geosource-tag">' + SVG_ICONS.building + ' ' + window.GIS.utils.escapeHtml(s.provider) + '</span>';
      }
      if (s.need_no_key === '是') {
        html += '<span class="geosource-tag tag-success">' + SVG_ICONS.check + ' 免Key</span>';
      }
      if (s.is_free === '是') {
        html += '<span class="geosource-tag tag-info">' + SVG_ICONS.check + ' 免费</span>';
      }
      if (s.crs) {
        html += '<span class="geosource-tag">' + SVG_ICONS.globe + ' ' + window.GIS.utils.escapeHtml(s.crs) + '</span>';
      }
      html += '  </div>';

      if (s.data_description) {
        html += '  <div class="geosource-card-desc" title="' + window.GIS.utils.escapeHtml(s.data_description) + '">' + window.GIS.utils.escapeHtml(s.data_description) + '</div>';
      }

      html += '  <div class="geosource-card-url-row">';
      html += '    <input type="text" readonly class="geosource-url-input" value="' + window.GIS.utils.escapeHtml(s.service_url || s.official_url || '') + '" />';
      html += '    <button class="geosource-copy-btn" onclick="window.GIS.geosource.copyUrl(\'' + encodeURIComponent(s.service_url || s.official_url || '') + '\', this)" title="复制 URL">';
      html += '      ' + SVG_ICONS.copy + ' <span>复制</span>';
      html += '    </button>';
      html += '  </div>';

      html += '  <div class="geosource-card-actions">';
      html += '    <button class="geosource-action-btn" onclick="window.GIS.geosource.toggleDetails(\'' + window.GIS.utils.escapeHtml(s.service_id) + '\', this)">';
      html += '      ' + SVG_ICONS.layers + ' <span>图层与详情</span>';
      html += '    </button>';
      if (canLoad && s.service_url) {
        html += '    <button class="geosource-action-btn btn-primary" onclick="window.GIS.geosource.loadService(' + index + ')">';
        html += '      ' + SVG_ICONS.mapPlus + ' <span>一键上图</span>';
        html += '    </button>';
      }
      if (s.official_url || s.docs_url) {
        html += '    <a class="geosource-action-btn" href="' + window.GIS.utils.escapeHtml(s.official_url || s.docs_url) + '" target="_blank" rel="noopener">';
        html += '      ' + SVG_ICONS.externalLink + ' <span>官网/文档</span>';
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
    html += SVG_ICONS.chevronLeft;
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
    html += SVG_ICONS.chevronRight;
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
      btn.innerHTML = SVG_ICONS.layers + ' <span>图层与详情</span>';
      return;
    }

    btn.innerHTML = SVG_ICONS.layers + ' <span>加载中...</span>';
    window.GIS.api.geosourceDetail(serviceId).then(function (det) {
      btn.innerHTML = SVG_ICONS.chevronUp + ' <span>收起详情</span>';
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
            dHtml += '  <button class="geosource-sublayer-load-btn" onclick="window.GIS.geosource.loadWmsSublayer(\'' + encodeURIComponent(det.service_url) + '\', \'' + encodeURIComponent(l.layer_name) + '\', \'' + encodeURIComponent(det.service_name + ' - ' + l.layer_name) + '\')">' + SVG_ICONS.mapPlus + ' 上图</button>';
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
      btn.innerHTML = SVG_ICONS.layers + ' <span>图层与详情</span>';
      alert('获取详情失败: ' + e.message);
    });
  }

  function loadService(index) {
    var s = _lastResults[index];
    if (!s || !s.service_url) return;

    var name = s.service_name || s.service_id;
    var proto = s.protocol || '';

    // 1. OGC WMS 服务
    if (/WMS/i.test(proto)) {
      window.GIS.api.geosourceDetail(s.service_id).then(function (det) {
        var layerName = '';
        if (det.layers && det.layers.length > 0) {
          layerName = det.layers[0].layer_name;
        }
        loadWmsSublayer(encodeURIComponent(s.service_url), encodeURIComponent(layerName), encodeURIComponent(name));
      }).catch(function () {
        loadWmsSublayer(encodeURIComponent(s.service_url), '', encodeURIComponent(name));
      });
      return;
    }

    // 2. XYZ 瓦片服务
    if (/XYZ/i.test(proto) || /\{[xyz]\}/i.test(s.service_url)) {
      loadXyzLayer(s.service_url, name);
      return;
    }

    // 3. ArcGIS REST FeatureServer
    if (/FeatureServer/i.test(s.service_url)) {
      var queryUrl = s.service_url.replace(/\/+$/, '') + '/0/query?where=1%3D1&outFields=*&f=geojson&resultRecordCount=1000';
      fetchWithProxy(queryUrl)
        .then(function (gj) {
          if (gj && (gj.type === 'FeatureCollection' || gj.features)) {
            loadGeoJsonLayer(gj, name, s.crs);
          } else {
            fallbackNotifyUrl(s, name);
          }
        })
        .catch(function () {
          fallbackNotifyUrl(s, name);
        });
      return;
    }

    // 4. ArcGIS REST MapServer (尝试作为 WMS 或 瓦片图层加载)
    if (/MapServer/i.test(s.service_url)) {
      var tileUrl = s.service_url.replace(/\/+$/, '') + '/tile/{z}/{y}/{x}';
      loadXyzLayer(tileUrl, name);
      return;
    }

    // 5. 默认尝试以 GeoJSON 格式加载（优先直连，CORS 失败自动回退代理）
    fetchWithProxy(s.service_url)
      .then(function (gj) {
        if (gj && (gj.type === 'FeatureCollection' || gj.type === 'Feature' || gj.coordinates || gj.features)) {
          loadGeoJsonLayer(gj, name, s.crs);
        } else {
          fallbackNotifyUrl(s, name);
        }
      })
      .catch(function () {
        fallbackNotifyUrl(s, name);
      });
  }

  function fetchWithProxy(url) {
    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .catch(function () {
        // 直连失败（如浏览器 CORS 拦截），自动通过后端代理重试
        var proxyUrl = (window.GIS.api.BASE_URL || '') + '/api/geosource/proxy?url=' + encodeURIComponent(url);
        return fetch(proxyUrl).then(function (res) {
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
      }, true);
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

  function fallbackNotifyUrl(serviceObj, name) {
    var url = serviceObj.service_url || serviceObj.official_url || '';
    if (url) {
      navigator.clipboard.writeText(url).catch(function () {});
    }
    if (window.GIS.chat && typeof window.GIS.chat.addMessage === 'function') {
      var proto = serviceObj.protocol || 'REST';
      var msg = '**数据源接入指引** · ' + name + '\n\n' +
        '该服务为 **' + proto + '** 空间服务目录或 API 端点。已将服务端点 URL 复制到剪贴板，您可以在 QGIS / ArcGIS 中作为 ' + proto + ' 服务直接添加，或在 Python / GDAL 代码中读取：\n\n' +
        '`' + url + '`';
      window.GIS.chat.addMessage(msg, 'system');
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
    loadWmsSublayer: loadWmsSublayer
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
