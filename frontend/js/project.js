window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  let _currentProjectId = null;
  let _activeRegistryProjectId = null;
  let _currentSessionId = _createSessionId();
  let _loadGeneration = 0;
  let _saveQueue = Promise.resolve();
  const _pendingDeleteProjectIds = new Set();

  function _queueProjectSave(work) {
    var request = _saveQueue.then(work);
    _saveQueue = request.catch(function() {});
    return request;
  }

  function _registrySyncFailed(result) {
    if (Array.isArray(result)) return result.some(_registrySyncFailed);
    return result === false || !!(result && (result.success === false || result.ok === false));
  }

  function _escapeMarkup(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function(ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function _createSessionId() {
    return 'session_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 7);
  }

  function init() {
    _bindHistoryToggle();
    _bindHistoryClose();
    _bindClearAll();
    _checkRecentProjectBanner();
  }

  function _checkRecentProjectBanner() {
    var container = document.getElementById('chatMessages');
    if (!container) return;
    GIS.api.listProjects().then(function(data) {
      var projs = data && data.projects;
      if (!projs || projs.length === 0) return;
      if (container.querySelectorAll('.message').length > 0) return;

      var emptyEl = container.querySelector('.chat-messages-empty');
      if (!emptyEl) return;

      var latest = projs[0];
      var name = (typeof latest.name === 'string' ? latest.name : '未命名工程')
        .replace(/^\[用户引用了上一条回复.*?\]\s*/s, '').replace(/^\[附图层:.*?\]\s*/s, '').trim() || '未命名工程';
      if (name.length > 22) name = name.slice(0, 22) + '…';

      var banner = document.createElement('div');
      banner.className = 'recent-project-banner';
      banner.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px 18px;margin:24px auto;max-width:340px;border:1px dashed var(--outline-variant);border-radius:10px;background:var(--surface-container-low);cursor:pointer;transition:all 0.2s;text-align:center;box-sizing:border-box;user-select:none;';
      banner.innerHTML =
        '<div style="font-size:12px;color:var(--on-surface-variant);display:flex;align-items:center;justify-content:center;gap:6px;">' +
          "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:15px;height:15px;--ui-icon-image:url('/assets/ui-icons/icon-21db89b5c210.png')\"></span>" +
          '<span>上次工程: <strong>' + GIS.utils.escapeHtml(name) + '</strong></span>' +
        '</div>' +
        '<div style="font-size:11px;color:var(--accent,#6366f1);font-weight:600;">点击一键恢复继续工作 →</div>';
      banner.addEventListener('click', function() {
        _loadProject(latest.id);
      });
      banner.addEventListener('mouseenter', function() {
        banner.style.borderColor = 'var(--accent,#6366f1)';
        banner.style.transform = 'translateY(-1px)';
      });
      banner.addEventListener('mouseleave', function() {
        banner.style.borderColor = 'var(--outline-variant)';
        banner.style.transform = 'none';
      });

      emptyEl.innerHTML = '';
      emptyEl.appendChild(banner);
    }).catch(function() {});
  }

  function _getProvider() {
    const sel = document.getElementById('modelSelector');
    return sel ? sel.value : 'glm-routed';
  }

  function _getMapState() {
    if (GIS.map && typeof GIS.map.getState === 'function') {
      const s = GIS.map.getState();
      return { lng: s.center ? s.center.lng : 0, lat: s.center ? s.center.lat : 0, zoom: Number.isFinite(s.zoom) ? s.zoom : 10 };
    }
    return {};
  }

  function _readSavedMapView(mapState) {
    if (!mapState || typeof mapState !== 'object') return null;
    var center = mapState.center;
    var latValue = mapState.lat;
    var lngValue = mapState.lng;
    if (latValue === undefined || latValue === null) {
      latValue = Array.isArray(center) ? center[0] : center && center.lat;
    }
    if (lngValue === undefined || lngValue === null) {
      lngValue = Array.isArray(center) ? center[1] : center && center.lng;
    }
    if ((typeof latValue === 'string' && !latValue.trim()) || (typeof lngValue === 'string' && !lngValue.trim())) return null;
    var lat = Number(latValue);
    var lng = Number(lngValue);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
    var zoom = mapState.zoom === undefined || mapState.zoom === null ? 10 : Number(mapState.zoom);
    return { center: [lat, lng], zoom: Number.isFinite(zoom) ? zoom : 10 };
  }

  function _collectMessages() {
    const msgs = [];
    const container = document.getElementById('chatMessages');
    if (!container) return msgs;
    const rows = container.querySelectorAll('.message');
    rows.forEach(function(row) {
      if (row.classList.contains('message-system')) return;
      const isUser = row.classList.contains('message-user');
      const bubble = row.querySelector('.message-bubble');
      if (!bubble) return;
      if (row.id === 'ai-loading-msg') return;
      var content = row._rawText || bubble.innerText || bubble.textContent || '';
      content = content.replace(/^\d{2}:\d{2}:\d{2}\s*/, '');
      msgs.push({ role: isUser ? 'user' : 'assistant', content: content.trim() });
    });
    return msgs;
  }

  function _collectLayers() {
    if (GIS.layers && typeof GIS.layers.getLayers === 'function') {
      return GIS.layers.getLayers().map(function(layer) {
        var shared = GIS.state && typeof GIS.state.getLayer === 'function'
          ? GIS.state.getLayer(layer.layer_id) : null;
        var panelStyle = Object.assign({}, layer.color ? { color: layer.color } : {}, layer.style || {});
        var style = Object.assign({}, panelStyle);
        // Shared state replaces its style object when controls change it; the
        // panel may still reference the original object from layer creation.
        Object.assign(style, shared && shared.style || {});
        // Keep the layer-wide opacity multiplier separate from base symbol opacity.
        if (layer.opacity !== undefined) {
          if (panelStyle.opacity === undefined) delete style.opacity;
          else style.opacity = panelStyle.opacity;
        }
        var symbology = GIS.layers && typeof GIS.layers.getSymbologyState === 'function'
          ? GIS.layers.getSymbologyState(layer.layer_id) : null;
        return Object.assign({}, layer, { style: style, symbology: symbology });
      });
    }
    return [];
  }

  function _collectLayerAssignments() {
    return _collectLayers().map(function(layer, order) {
      return {
        layer_id: layer.layer_id || null,
        registry_name: layer._registeredName || layer._rawName || layer.filename || null,
        style: layer.style || (layer.color ? { color: layer.color } : null),
        opacity: layer.opacity,
        symbology: layer.symbology || null,
        names: [layer._registeredName, layer._rawName, layer.filename].filter(function(name, index, all) {
          return !!name && all.indexOf(name) === index;
        }),
        groupId: layer.groupId || null,
        visible: layer.visible !== false,
        name: layer.filename || layer.name || '图层',
        raster: layer.raster || null,
        labels: layer.labels || null,
        order: order,
      };
    });
  }

  function _renderHistoryList(projects) {
    const list = document.getElementById('projectHistoryList');
    if (!list) return;
    if (!projects || projects.length === 0) {
      list.innerHTML =
        "<div class=\"history-empty\"><span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:48px;height:48px;opacity:0.3;--ui-icon-image:url('/assets/ui-icons/icon-10c1d9af6139.png')\"></span><div class=\"history-empty-text\">暂无历史会话</div><div class=\"history-empty-hint\">开始新对话后自动保存</div></div>";
      return;
    }

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today.getTime() - 86400000);

    var todayItems = [], yesterdayItems = [], earlierItems = [];
    projects.forEach(function(p) {
      var d = new Date(p.updatedAt);
      if (d >= today) todayItems.push(p);
      else if (d >= yesterday) yesterdayItems.push(p);
      else earlierItems.push(p);
    });

    function renderGroup(title, items) {
      if (items.length === 0) return '';
      return '<div class="history-date-group">' +
        '<div class="history-date-label">' + title + '</div>' +
        items.map(function(p) {
          var preview = p.msgPreview ? GIS.utils.escapeHtml(p.msgPreview) : '空会话';
          var timeStr = _formatTime(p.updatedAt);
          var name = GIS.utils.escapeHtml(p.name || '未命名工程');
          return '<div class="history-item" data-id="' + _escapeMarkup(p.id) + '">' +
            '<div class="history-item-main" data-action="load">' +
              '<div class="history-item-name">' + name + '</div>' +
              '<div class="history-item-preview">' + preview + '</div>' +
              '<div class="history-item-meta">' +
                '<span>' + timeStr + '</span>' +
                '<span class="history-item-dot">·</span>' +
                '<span>' + (p.layerCount || 0) + ' 图层</span>' +
                '<span class="history-item-dot">·</span>' +
                '<span>' + (p.messageCount || 0) + ' 条消息</span>' +
              '</div>' +
            '</div>' +
            '<div class="history-item-actions">' +
              '<button class="history-action-btn" data-action="load" title="继续">' +
                "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-f91a12a9cc81.png')\"></span>" +
              '</button>' +
              '<button class="history-action-btn" data-action="rename" title="重命名">' +
                "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-3de3336f34e0.png')\"></span>" +
              '</button>' +
              '<button class="history-action-btn history-action-delete" data-action="delete" title="删除">' +
                "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-01e0637d9a44.png')\"></span>" +
              '</button>' +
              '<button class="history-action-btn" data-action="export" title="导出">' +
                "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-b070c6cd9465.png')\"></span>" +
              '</button>' +
            '</div>' +
          '</div>';
        }).join('') +
        '</div>';
    }

    list.innerHTML =
      renderGroup('今天', todayItems) +
      renderGroup('昨天', yesterdayItems) +
      renderGroup('更早', earlierItems);

    list.querySelectorAll('.history-item').forEach(function(item) {
      item.addEventListener('click', function(e) {
        var actionBtn = e.target.closest('.history-action-btn');
        if (actionBtn) {
          var action = actionBtn.getAttribute('data-action');
          var pid = item.getAttribute('data-id');
          if (action === 'load') _loadProject(pid);
          else if (action === 'rename') _promptRename(pid, item);
          else if (action === 'delete') _deleteProject(pid, item);
          else if (action === 'export') {
            _exportProject(pid).catch(function(err) {
              GIS.chat.addMessage('导出失败: ' + _escapeMarkup(err.message || err), 'system');
            });
          }
          return;
        }
        var main = e.target.closest('[data-action="load"]');
        if (main) _loadProject(item.getAttribute('data-id'));
      });
    });
  }

  function _formatTime(isoStr) {
    if (!isoStr) return '';
    var d = new Date(isoStr);
    var now = new Date();
    var diff = now - d;
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前';
    if (diff < 86400000) {
      return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
    }
    return (d.getMonth() + 1) + '/' + d.getDate();
  }

  function _loadProject(pid) {
    var cancelPromise = false;
    if (GIS.chat && typeof GIS.chat.cancelActiveRequest === 'function') {
      cancelPromise = GIS.chat.cancelActiveRequest('切换工程，已取消当前任务');
    }
    var loadGeneration = ++_loadGeneration;
    var loadRequest;
    if (cancelPromise && typeof cancelPromise.then === 'function') {
      loadRequest = Promise.resolve(cancelPromise).catch(function() { return false; }).then(function(cancelled) {
        if (cancelled === false) {
          if (GIS.chat && typeof GIS.chat.addMessage === 'function') {
            GIS.chat.addMessage('无法确认当前任务已停止，未切换工程。请稍后重试。', 'system');
          }
          return false;
        }
        if (loadGeneration !== _loadGeneration) return false;
        return GIS.api.loadProject(pid);
      });
    } else {
      loadRequest = loadGeneration === _loadGeneration
        ? GIS.api.loadProject(pid) : Promise.resolve(false);
    }
    return Promise.resolve(loadRequest).then(function(data) {
      if (loadGeneration !== _loadGeneration) return false;
      if (data === false) return false;
      if (!data || data.error) {
        GIS.chat.addMessage('加载工程失败', 'system');
        return false;
      }
      var projectName = typeof data.name === 'string' ? data.name : '未命名工程';
      var skippedProjectRecords = 0;
      var projectMessages = Array.isArray(data.messages) ? data.messages.filter(function(msg) {
        var valid = msg && typeof msg === 'object' && !Array.isArray(msg) &&
          (msg.role === 'user' || msg.role === 'assistant') && typeof msg.content === 'string';
        if (!valid) skippedProjectRecords++;
        return valid;
      }) : [];
      if (data.messages != null && !Array.isArray(data.messages)) skippedProjectRecords++;
      var projectLayers = Array.isArray(data.layers) ? data.layers.filter(function(layer) {
        var valid = layer && typeof layer === 'object' && !Array.isArray(layer);
        if (!valid) skippedProjectRecords++;
        return valid;
      }) : [];
      if (data.layers != null && !Array.isArray(data.layers)) skippedProjectRecords++;
      var projectLayerGroups = Array.isArray(data.layerGroups) ? data.layerGroups : [];
      if (data.layerGroups != null && !Array.isArray(data.layerGroups)) skippedProjectRecords++;
      _currentProjectId = data.id;
      _activeRegistryProjectId = data.id;
      _currentSessionId = data.sessionId || ('proj_' + data.id);
      var capsuleName = document.getElementById('workspaceCurrentProjectName');
      if (capsuleName) capsuleName.textContent = projectName || '未命名工程';
      // 先恢复聊天面板可见
      _hideHistory();
      // 先清理旧图层与地图要素，避免与旧工程叠加冲突
      if (GIS.state && typeof GIS.state.clearAll === 'function') {
        try { GIS.state.clearAll(); } catch(_) {}
      }
      if (GIS.layers && typeof GIS.layers.clearAll === 'function') {
        try { GIS.layers.clearAll(true); } catch(_) {}
      }
      if (GIS.map && typeof GIS.map.clearAll === 'function') {
        try { GIS.map.clearAll(); } catch(_) {}
      }
      if (GIS.layers && typeof GIS.layers.setGroupState === 'function') {
        GIS.layers.setGroupState(projectLayerGroups);
      }
      GIS.chat.clear();
      projectMessages.forEach(function(msg) {
        if (msg.role === 'user') GIS.chat.addMessage(_escapeMarkup(msg.content), 'user');
        else if (msg.role === 'assistant') GIS.chat.addMessage(msg.content, 'ai');
      });
      if (projectLayers.length > 0) {
        var restoredLayerIds = new Set();
        var restoreWarnings = [];
        var backendSkippedLayers = new Set(Array.isArray(data.registration_warnings)
          ? data.registration_warnings.filter(function(name) { return typeof name === 'string'; }) : []);
        projectLayers.forEach(function(layer, layerIndex) {
          try {
            var layerName = layer.name || '图层';
            if (backendSkippedLayers.has(layerName)) {
              restoreWarnings.push(layerName);
              return;
            }
            var layerColor = layer.color || '#1c1b1b';
            var isVis = layer.visible !== false;
            var mapLayerName = 'project_' + data.id + '_layer_' + layerIndex;
            var baseLayerId = typeof layer.layer_id === 'string' && layer.layer_id
              ? layer.layer_id : mapLayerName;
            var restoredLayerId = baseLayerId;
            var duplicateSuffix = 2;
            while (restoredLayerIds.has(restoredLayerId)) {
              restoredLayerId = baseLayerId + '_' + duplicateSuffix++;
            }
            restoredLayerIds.add(restoredLayerId);
            var serviceUrl = layer.url || layer.service_url || '';
            var proto = (layer.service_type || layer.protocol || layer.geometry_type || '').toLowerCase();

            if (layer.geojson && GIS.map && GIS.map.loadGeoJSON) {
              var restoredStyle = Object.assign({}, layer.style || {});
              var legacyOpacity = layer.opacity === undefined && restoredStyle.opacity !== undefined;
              var vectorOpacity = Number(layer.opacity !== undefined ? layer.opacity :
                (legacyOpacity ? restoredStyle.opacity : 1));
              if (legacyOpacity) delete restoredStyle.opacity;
              if (!Number.isFinite(vectorOpacity)) vectorOpacity = 1;
              try {
                var renderedVector = GIS.map.loadGeoJSON(layer.geojson, mapLayerName, restoredStyle);
                if (renderedVector === null) {
                  restoreWarnings.push(layerName);
                  return;
                }
              } catch(_) {
                restoreWarnings.push(layerName);
                return;
              }
              if (GIS.layers && GIS.layers.addLayer) {
                var restoredLayer = GIS.layers.addLayer({
                  layer_id: restoredLayerId,
                  filename: layerName,
                  _rawName: mapLayerName,
                  geojson: layer.geojson,
                  geometry_type: layer.geometry_type || 'Vector',
                  crs: layer.crs || 'WGS-84',
                  color: layerColor,
                  style: restoredStyle,
                  opacity: vectorOpacity,
                  visible: isVis,
                  source: layer.source || 'ai',
                  provenance: layer.provenance || null,
                  groupId: layer.groupId || null,
                });
                if (!isVis && GIS.map.setLayerVisible) {
                  GIS.map.setLayerVisible(mapLayerName, false);
                }
                if (layer.symbology && typeof GIS.layers.restoreSymbologyState === 'function') {
                  GIS.layers.restoreSymbologyState(
                    restoredLayer && restoredLayer.layer_id || layer.layer_id,
                    layer.symbology
                  );
                }
                if (layer.labels && typeof layer.labels.field === 'string' && layer.labels.field &&
                    layer.labels.field.length <= 256 && GIS.map.setLabels) {
                  var labelFontSize = Number(layer.labels.fontSize);
                  if (!Number.isFinite(labelFontSize) || labelFontSize < 6 || labelFontSize > 48) labelFontSize = 12;
                  var labelColor = typeof layer.labels.color === 'string' && /^#[0-9a-f]{6}$/i.test(layer.labels.color)
                    ? layer.labels.color : '#333333';
                  GIS.map.setLabels(mapLayerName, layer.labels.field, labelFontSize, labelColor);
                }
                if (GIS.map.setLayerOpacity) GIS.map.setLayerOpacity(mapLayerName, vectorOpacity);
                if (restoredLayer && GIS.state && GIS.state.setOpacity) {
                  GIS.state.setOpacity(restoredLayer.layer_id, vectorOpacity);
                }
              }
            } else if (layer.raster && layer.raster.url && Array.isArray(layer.raster.bounds) &&
                GIS.map && GIS.map.addImageOverlay) {
              var rasterOpacity = Number(layer.opacity !== undefined ? layer.opacity :
                (layer.style && layer.style.opacity !== undefined ? layer.style.opacity : 1));
              GIS.map.addImageOverlay(layer.raster.url, layer.raster.bounds, mapLayerName, layerName);
              if (!isVis && GIS.map.setLayerVisible) {
                GIS.map.setLayerVisible(mapLayerName, false);
              }
              if (Number.isFinite(rasterOpacity) && GIS.map.setLayerOpacity) {
                GIS.map.setLayerOpacity(mapLayerName, rasterOpacity);
              }
              if (GIS.layers && GIS.layers.addLayer) {
                var restoredRaster = {
                  layer_id: restoredLayerId,
                  filename: layerName,
                  _rawName: mapLayerName,
                  geometry_type: layer.geometry_type || 'Raster',
                  crs: layer.crs || 'WGS-84',
                  source: layer.source || 'upload',
                  style: layer.style || {},
                  opacity: Number.isFinite(rasterOpacity) ? rasterOpacity : 1,
                  raster: layer.raster,
                  _registeredName: layerName,
                  visible: isVis,
                  groupId: layer.groupId || null,
                };
                if (typeof layer.registration_token === 'string') {
                  restoredRaster._registrationTokens = Object.create(null);
                  restoredRaster._registrationTokens[layerName] = layer.registration_token;
                }
                GIS.layers.addLayer(restoredRaster, true);
              }
            } else if (serviceUrl && proto.indexOf('wms') >= 0 && GIS.geosource &&
                (GIS.geosource.loadSavedServiceLayer || GIS.geosource.loadWmsSublayer)) {
              if (GIS.geosource.loadSavedServiceLayer) {
                GIS.geosource.loadSavedServiceLayer(Object.assign({}, layer, { layer_id: restoredLayerId }));
              } else {
                GIS.geosource.loadWmsSublayer(
                  encodeURIComponent(serviceUrl), encodeURIComponent(layer.sublayer || ''),
                  encodeURIComponent(layerName), layer.groupId || null
                );
              }
            } else if (serviceUrl && (proto.indexOf('xyz') >= 0 || /\{[xyz]\}/i.test(serviceUrl)) && GIS.map && GIS.map.addTileLayer) {
              if (GIS.geosource && GIS.geosource.loadSavedServiceLayer) {
                GIS.geosource.loadSavedServiceLayer(Object.assign({}, layer, { layer_id: restoredLayerId }));
              } else {
                GIS.map.addTileLayer(serviceUrl, layerName);
                if (GIS.layers && GIS.layers.addLayer) {
                  GIS.layers.addLayer({
                    filename: layerName,
                    geometry_type: 'XYZ瓦片',
                    crs: 'WebMercator',
                    source: 'geosource',
                    url: serviceUrl,
                    service_type: 'XYZ',
                    visible: isVis,
                    groupId: layer.groupId || null
                  }, true);
                }
              }
            }
          } catch(_) {
            restoreWarnings.push(typeof layer.name === 'string' && layer.name ? layer.name : '图层');
          }
        });
        if (GIS.layers && typeof GIS.layers.syncLayerOrder === 'function') {
          GIS.layers.syncLayerOrder();
        }
        if (restoreWarnings.length) {
          var failedNames = restoreWarnings.slice(0, 3).map(_escapeMarkup).join('、');
          var extraCount = restoreWarnings.length - 3;
          var failedSummary = extraCount > 0 ? failedNames + '等 ' + extraCount + ' 个图层' : failedNames;
          GIS.chat.addMessage('工程已部分恢复：' + failedSummary + '未能显示，请检查数据后重试。', 'system');
        }
      }
      if (skippedProjectRecords) {
        GIS.chat.addMessage('工程中有 ' + skippedProjectRecords + ' 条格式异常的记录已跳过，其余内容已尽量恢复。', 'system');
      }
      if (Array.isArray(data.registration_warnings) && data.registration_warnings.length) {
        GIS.chat.addMessage('其中 ' + data.registration_warnings.length +
          ' 个图层未能注册到分析工具；请检查这些图层的数据后再对其执行分析。', 'system');
      }
      var savedMapView = _readSavedMapView(data.mapState);
      if (savedMapView && GIS.map && GIS.map.setView) {
        try { GIS.map.setView(savedMapView.center, savedMapView.zoom); } catch(_) {}
      }
      var displayProjName = projectName.replace(/^\[用户引用了上一条回复.*?\]\s*/s, '').replace(/^\[附图层:.*?\]\s*/s, '').trim();
      if (!displayProjName || displayProjName === '未命名工程') displayProjName = projectName || '未命名工程';
      if (displayProjName.length > 25) displayProjName = displayProjName.slice(0, 25) + '…';
      GIS.chat.addMessage('已恢复工程: ' + _escapeMarkup(displayProjName), 'system', { pill: true });
      if (GIS.workspace && GIS.workspace.renderRecentProjects) {
        try { GIS.workspace.renderRecentProjects(); } catch(_) {}
      }
      return true;
    }).catch(function(err) {
      if (loadGeneration !== _loadGeneration) return false;
      GIS.chat.addMessage('加载工程失败: ' + _escapeMarkup(err.message || err), 'system');
      return false;
    });
  }

  function _deleteProject(pid, itemEl) {
    if (_pendingDeleteProjectIds.has(pid)) return;
    _pendingDeleteProjectIds.add(pid);
    var cancelPromise = false;
    if (pid === _currentProjectId) {
      _loadGeneration += 1;
      if (GIS.chat && typeof GIS.chat.cancelActiveRequest === 'function') {
        cancelPromise = GIS.chat.cancelActiveRequest('删除当前工程，已取消正在运行的任务');
      }
    }
    _queueProjectSave(function() {
      var deleteRequest = function() { return GIS.api.deleteProject(pid); };
      if (cancelPromise && typeof cancelPromise.then === 'function') {
        return Promise.resolve(cancelPromise).catch(function() { return false; }).then(function(cancelled) {
          if (cancelled === false) throw new Error('无法确认当前任务已停止，未删除工程');
          return deleteRequest();
        });
      }
      return deleteRequest();
    }).then(function(result) {
      if (itemEl && itemEl.parentNode) itemEl.remove();
      _refreshList();
      if (result && result.warning && GIS.toast && typeof GIS.toast.warn === 'function') GIS.toast.warn(result.warning);
      // Serialize deletion with saves so an in-flight or queued autosave cannot recreate this project.
      if (pid === _currentProjectId) _clearCurrentProjectState();
      _pendingDeleteProjectIds.delete(pid);
      return result;
    }).catch(function(err) {
      _pendingDeleteProjectIds.delete(pid);
      GIS.chat.addMessage('删除失败: ' + _escapeMarkup(err.message || err), 'system');
    });
  }

  function _promptRename(pid, itemEl) {
    var currentName = '';
    var nameEl = itemEl ? itemEl.querySelector('.history-item-name') : null;
    if (nameEl) currentName = nameEl.textContent;
    function doRename(newName) {
      if (!newName || newName.trim() === '') return;
      GIS.api.renameProject(pid, newName.trim()).then(function(result) {
        if (nameEl) nameEl.textContent = newName.trim();
        if (_currentProjectId === pid) {
          var topCapsule = document.getElementById('workspaceCurrentProjectName');
          if (topCapsule) topCapsule.textContent = newName.trim();
        }
        if (result && result.warning && GIS.toast && typeof GIS.toast.warn === 'function') GIS.toast.warn(result.warning);
      }).catch(function(err) {
        GIS.chat.addMessage('重命名失败: ' + _escapeMarkup(err.message || err), 'system');
      });
    }
    if (window.GIS.workspace && typeof window.GIS.workspace.promptModal === 'function') {
      window.GIS.workspace.promptModal('重命名历史工程', '修改此工程记录的显示名称。', currentName, doRename);
    } else {
      var n = prompt('重命名工程：', currentName);
      if (n) doRename(n);
    }
  }

  function _exportProject(pid, customName) {
    return GIS.api.exportProject(pid).then(function(blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = (customName || ('project_' + pid)) + '.giswork';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
    });
  }

  function _refreshList() {
    GIS.api.listProjects().then(function(data) {
      _renderHistoryList(data && data.projects ? data.projects : []);
    }).catch(function() {});
  }

  function _clearCurrentProjectState() {
    if (GIS.chat && typeof GIS.chat.cancelActiveRequest === 'function') {
      GIS.chat.cancelActiveRequest('工程已关闭，已取消当前任务');
    }
    _loadGeneration += 1;
    _currentProjectId = null;
    _activeRegistryProjectId = null;
    _currentSessionId = _createSessionId();
    var currentNameEl = document.getElementById('workspaceCurrentProjectName');
    if (currentNameEl) currentNameEl.textContent = '未命名工程';
    if (GIS.layers && typeof GIS.layers.clearAll === 'function') GIS.layers.clearAll(true);
    GIS.chat.clear();
    if (GIS.map && typeof GIS.map.resetView === 'function') { try { GIS.map.resetView(); } catch(_) {} }
  }

  function _bindHistoryToggle() {
    var btn = document.getElementById('historyBtn');
    if (!btn) return;
    btn.addEventListener('click', function() {
      _showHistory();
    });
  }

  function _bindHistoryClose() {
    var btn = document.getElementById('historyCloseBtn');
    if (!btn) return;
    btn.addEventListener('click', _hideHistory);
  }

  function _showHistory() {
    var msgs = document.getElementById('chatMessages');
    var history = document.getElementById('chatHistory');
    if (msgs) msgs.style.display = 'none';
    if (history) history.style.display = 'flex';
    _refreshList();
  }

  function _hideHistory() {
    var msgs = document.getElementById('chatMessages');
    var history = document.getElementById('chatHistory');
    if (msgs) msgs.style.display = '';
    if (history) history.style.display = 'none';
  }

  function _bindClearAll() {
    var btn = document.getElementById('historyClearAllBtn');
    if (!btn) return;
    btn.addEventListener('click', function() {
      if (!confirm('确定删除全部历史会话？此操作不可恢复。')) return;
      _loadGeneration += 1;
      var cancelPromise = GIS.chat && typeof GIS.chat.cancelActiveRequest === 'function'
        ? GIS.chat.cancelActiveRequest('删除全部历史前已取消正在运行的任务') : false;
      _queueProjectSave(function() {
        var deleteRequest = function() { return GIS.api.deleteAllProjects(); };
        if (cancelPromise && typeof cancelPromise.then === 'function') {
          return Promise.resolve(cancelPromise).catch(function() { return false; }).then(function(cancelled) {
            if (cancelled === false) throw new Error('无法确认当前任务已停止，未删除历史工程');
            return deleteRequest();
          });
        }
        return deleteRequest();
      }).then(async function(result) {
          _refreshList();
          if (result && result.success === false) {
            var currentId = _currentProjectId;
            if (currentId) {
              try {
                var latest = await GIS.api.listProjects();
                if (latest && Array.isArray(latest.projects) && _currentProjectId === currentId && !latest.projects.some(function(project) { return project.id === currentId; })) {
                  _clearCurrentProjectState();
                }
              } catch (_) { /* Preserve the workspace when project existence cannot be verified. */ }
            }
            if (result.warning && GIS.toast && typeof GIS.toast.warn === 'function') {
              GIS.toast.warn(result.warning);
            } else {
              GIS.chat.addMessage(_escapeMarkup(result.warning || '部分工程未能删除，请稍后重试。'), 'system');
            }
            return result;
          }
          _clearCurrentProjectState();
          GIS.chat.addMessage('已删除全部历史会话', 'system');
          if (result && result.warning && GIS.toast && typeof GIS.toast.warn === 'function') GIS.toast.warn(result.warning);
          return result;
      }).catch(function(err) {
        GIS.chat.addMessage('删除失败: ' + _escapeMarkup(err.message || err), 'system');
      });
    });
  }

  GIS.project = {
    init: init,
    save: function(customName) {
      var sessionId = _currentSessionId;
      var generation = _loadGeneration;
      return _queueProjectSave(function() {
        if (_currentSessionId !== sessionId || _loadGeneration !== generation) throw new Error('工程已切换，已取消旧工程的保存');
        var projectId = _currentProjectId;
        var topNameEl = document.getElementById('workspaceCurrentProjectName');
        var projName = customName || (topNameEl ? topNameEl.textContent : '未命名工程');
        return GIS.api.saveProject({
          project_id: projectId,
          name: projName,
          session_id: sessionId,
          provider: _getProvider(),
          map_state: _getMapState(),
          messages: _collectMessages(),
          layers: _collectLayers(),
          layer_groups: GIS.layers && typeof GIS.layers.getGroupState === 'function'
            ? GIS.layers.getGroupState() : [],
        }).then(function(res) {
          if (res && res.id && _currentSessionId === sessionId && _loadGeneration === generation && _currentProjectId === projectId) {
            _currentProjectId = res.id;
          }
          return res;
        });
      });
    },
    autoSave: function() {
      var sessionId = _currentSessionId;
      var generation = _loadGeneration;
      return _queueProjectSave(async function() {
        if (_currentSessionId !== sessionId || _loadGeneration !== generation) return null;
        var currentLayers = _collectLayers();
        var layerSyncs = GIS.layers && typeof GIS.layers.waitForRegistrySync === 'function'
          ? GIS.layers.waitForRegistrySync()
          : Promise.all(currentLayers.filter(function(layer) {
            return layer.geojson && layer._registrationPromise;
          }).map(function(layer) { return Promise.resolve(layer._registrationPromise); }));
        var syncResults = await layerSyncs;
        if (_currentSessionId !== sessionId || _loadGeneration !== generation) return null;
        if (!Array.isArray(syncResults) || _registrySyncFailed(syncResults)) {
          throw new Error('图层数据尚未同步到后端，已跳过自动保存以避免保存旧数据');
        }
        var projectId = _currentProjectId;
        var layerGroups = GIS.layers && typeof GIS.layers.getGroupState === 'function'
          ? GIS.layers.getGroupState() : [];
        var res = await GIS.api.autoSaveProject(sessionId, projectId, layerGroups, _collectLayerAssignments());
        if (res && res.id && _currentSessionId === sessionId && _loadGeneration === generation && _currentProjectId === projectId) {
          _currentProjectId = res.id;
        }
        if (res && res.warning && GIS.toast && typeof GIS.toast.warn === 'function') GIS.toast.warn(res.warning);
        return res;
      }).catch(function(error) {
        console.warn('[GIS Project] 自动保存失败', error);
        if (error && GIS.toast && typeof GIS.toast.error === 'function') GIS.toast.error(error.message || '自动保存失败');
      });
    },
    exportCurrent: function(pid, customName) {
      return _exportProject(pid || _currentProjectId, customName);
    },
    showHistory: _showHistory,
    loadProject: _loadProject,
    getCurrentProjectId: function() { return _currentProjectId; },
    getActiveRegistryProjectId: function() { return _activeRegistryProjectId; },
    getLoadGeneration: function() { return _loadGeneration; },
    setCurrentProjectId: function(id) {
      _loadGeneration += 1;
      _currentProjectId = id;
      if (!id) _currentSessionId = _createSessionId();
    },
    getCurrentSessionId: function() { return _currentSessionId; },
    resetSession: function() {
      _loadGeneration += 1;
      _currentProjectId = null;
      _activeRegistryProjectId = null;
      _currentSessionId = _createSessionId();
      return _currentSessionId;
    },
  };
})();
