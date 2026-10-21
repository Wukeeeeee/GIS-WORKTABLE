window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  let _currentProjectId = null;
  let _currentSessionId = _createSessionId();
  let _loadGeneration = 0;

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
      var name = (latest.name || '未命名工程').replace(/^\[用户引用了上一条回复.*?\]\s*/s, '').replace(/^\[附图层:.*?\]\s*/s, '').trim() || '未命名工程';
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
        var style = Object.assign({}, layer.color ? { color: layer.color } : {}, layer.style || {});
        if (layer.opacity !== undefined) style.opacity = layer.opacity;
        // Shared state replaces its style object when controls change it; the
        // panel may still reference the original object from layer creation.
        Object.assign(style, shared && shared.style || {});
        var symbology = GIS.layers && typeof GIS.layers.getSymbologyState === 'function'
          ? GIS.layers.getSymbologyState(layer.layer_id) : null;
        return Object.assign({}, layer, { style: style, symbology: symbology });
      });
    }
    return [];
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
    var loadGeneration = ++_loadGeneration;
    return GIS.api.loadProject(pid).then(function(data) {
      if (loadGeneration !== _loadGeneration) return false;
      if (!data || data.error) {
        GIS.chat.addMessage('加载工程失败', 'system');
        return false;
      }
      _currentProjectId = data.id;
      _currentSessionId = data.sessionId || ('proj_' + data.id);
      var capsuleName = document.getElementById('workspaceCurrentProjectName');
      if (capsuleName) capsuleName.textContent = data.name || '未命名工程';
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
        GIS.layers.setGroupState(data.layerGroups || []);
      }
      GIS.chat.clear();
      if (data.messages) {
        data.messages.forEach(function(msg) {
          if (msg.role === 'user') GIS.chat.addMessage(_escapeMarkup(msg.content), 'user');
          else if (msg.role === 'assistant') GIS.chat.addMessage(msg.content, 'ai');
        });
      }
      if (data.layers && data.layers.length > 0) {
        var restoredLayerIds = new Set();
        data.layers.forEach(function(layer, layerIndex) {
          var layerName = layer.name || '图层';
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
          var proto = (layer.service_type || layer.protocol || '').toLowerCase();

          if (layer.geojson && GIS.map && GIS.map.loadGeoJSON) {
            try { GIS.map.loadGeoJSON(layer.geojson, mapLayerName, layer.style || {}); } catch(_) {}
            if (GIS.layers && GIS.layers.addLayer) {
              var restoredLayer = GIS.layers.addLayer({
                layer_id: restoredLayerId,
                filename: layerName,
                _rawName: mapLayerName,
                geojson: layer.geojson,
                geometry_type: layer.geometry_type || 'Vector',
                crs: layer.crs || 'WGS-84',
                color: layerColor,
                style: layer.style || { color: layerColor },
                visible: isVis,
                source: layer.source || 'ai',
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
            }
          } else if (layer.raster && layer.raster.url && Array.isArray(layer.raster.bounds) &&
              GIS.map && GIS.map.addImageOverlay) {
            var rasterOpacity = Number(layer.opacity !== undefined ? layer.opacity :
              (layer.style && layer.style.opacity !== undefined ? layer.style.opacity : 1));
            GIS.map.addImageOverlay(layer.raster.url, layer.raster.bounds, mapLayerName, mapLayerName);
            if (!isVis && GIS.map.setLayerVisible) {
              GIS.map.setLayerVisible(mapLayerName, false);
            }
            if (Number.isFinite(rasterOpacity) && GIS.map.setLayerOpacity) {
              GIS.map.setLayerOpacity(mapLayerName, rasterOpacity);
            }
            if (GIS.layers && GIS.layers.addLayer) {
              GIS.layers.addLayer({
                layer_id: restoredLayerId,
                filename: layerName,
                _rawName: mapLayerName,
                geometry_type: layer.geometry_type || 'Raster',
                crs: layer.crs || 'WGS-84',
                source: layer.source || 'upload',
                style: layer.style || {},
                opacity: Number.isFinite(rasterOpacity) ? rasterOpacity : 1,
                raster: layer.raster,
                visible: isVis,
                groupId: layer.groupId || null,
              }, true);
            }
          } else if (serviceUrl && proto.indexOf('wms') >= 0 && GIS.geosource && GIS.geosource.loadWmsSublayer) {
            GIS.geosource.loadWmsSublayer(
              encodeURIComponent(serviceUrl), encodeURIComponent(layer.sublayer || ''),
              encodeURIComponent(layerName), layer.groupId || null
            );
          } else if (serviceUrl && (proto.indexOf('xyz') >= 0 || /\{[xyz]\}/i.test(serviceUrl)) && GIS.map && GIS.map.addTileLayer) {
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
        });
        if (GIS.layers && typeof GIS.layers.syncLayerOrder === 'function') {
          GIS.layers.syncLayerOrder();
        }
      }
      var savedMapView = _readSavedMapView(data.mapState);
      if (savedMapView && GIS.map && GIS.map.setView) {
        try { GIS.map.setView(savedMapView.center, savedMapView.zoom); } catch(_) {}
      }
      var displayProjName = (data.name || '').replace(/^\[用户引用了上一条回复.*?\]\s*/s, '').replace(/^\[附图层:.*?\]\s*/s, '').trim();
      if (!displayProjName || displayProjName === '未命名工程') displayProjName = data.name || '未命名工程';
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
    GIS.api.deleteProject(pid).then(function() {
      if (itemEl && itemEl.parentNode) itemEl.remove();
      _refreshList();
      // 若删除的是当前正在查看的工程，联动清空会话和图层，避免残留
      if (pid === _currentProjectId) {
        _currentProjectId = null;
        _currentSessionId = _createSessionId();
        var currentNameEl = document.getElementById('workspaceCurrentProjectName');
        if (currentNameEl) currentNameEl.textContent = '未命名工程';
        if (GIS.layers && typeof GIS.layers.clearAll === 'function') GIS.layers.clearAll(true);
        GIS.chat.clear();
        if (GIS.map && typeof GIS.map.resetView === 'function') { try { GIS.map.resetView(); } catch(_) {} }
      }
    }).catch(function(err) {
      GIS.chat.addMessage('删除失败: ' + _escapeMarkup(err.message || err), 'system');
    });
  }

  function _promptRename(pid, itemEl) {
    var currentName = '';
    var nameEl = itemEl ? itemEl.querySelector('.history-item-name') : null;
    if (nameEl) currentName = nameEl.textContent;
    function doRename(newName) {
      if (!newName || newName.trim() === '') return;
      GIS.api.renameProject(pid, newName.trim()).then(function() {
        if (nameEl) nameEl.textContent = newName.trim();
        if (_currentProjectId === pid) {
          var topCapsule = document.getElementById('workspaceCurrentProjectName');
          if (topCapsule) topCapsule.textContent = newName.trim();
        }
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
      GIS.api.deleteAllProjects().then(function() {
        _refreshList();
        GIS.chat.addMessage('已删除全部历史会话', 'system');
      }).catch(function(err) {
        GIS.chat.addMessage('删除失败: ' + _escapeMarkup(err.message || err), 'system');
      });
    });
  }

  GIS.project = {
    init: init,
    save: function(customName) {
      var topNameEl = document.getElementById('workspaceCurrentProjectName');
      var projName = customName || (topNameEl ? topNameEl.textContent : '未命名工程');
      return GIS.api.saveProject({
        project_id: _currentProjectId,
        name: projName,
        session_id: _currentSessionId,
        provider: _getProvider(),
        map_state: _getMapState(),
        messages: _collectMessages(),
        layers: _collectLayers(),
        layer_groups: GIS.layers && typeof GIS.layers.getGroupState === 'function'
          ? GIS.layers.getGroupState() : [],
      }).then(function(res) {
        if (res && res.id) _currentProjectId = res.id;
        return res;
      });
    },
    autoSave: function() {
      var currentLayers = _collectLayers();
      var layerAssignments = currentLayers.map(function(layer) {
        return {
          layer_id: layer.layer_id || null,
          style: layer.style || (layer.color ? { color: layer.color } : null),
          symbology: layer.symbology || null,
          names: [layer._registeredName, layer._rawName, layer.filename].filter(function(name, index, all) {
            return !!name && all.indexOf(name) === index;
          }),
          groupId: layer.groupId || null,
          visible: layer.visible !== false,
          name: layer.filename || layer.name || '图层',
          raster: layer.raster || null,
        };
      });
      var layerGroups = GIS.layers && typeof GIS.layers.getGroupState === 'function'
        ? GIS.layers.getGroupState() : [];
      var layerSyncs = GIS.layers && typeof GIS.layers.waitForRegistrySync === 'function'
        ? GIS.layers.waitForRegistrySync()
        : Promise.all(currentLayers.filter(function(layer) {
          return layer.geojson && layer._registrationPromise;
        }).map(function(layer) { return Promise.resolve(layer._registrationPromise); }));
      return Promise.resolve(layerSyncs).then(function(syncResults) {
        if (syncResults.some(function(result) { return result === false; })) {
          throw new Error('图层数据尚未同步到后端，已跳过自动保存以避免保存旧数据');
        }
        return GIS.api.autoSaveProject(_currentSessionId, _currentProjectId, layerGroups, layerAssignments);
      }).then(function(res) {
        if (res && res.id) _currentProjectId = res.id;
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
    hideHistory: _hideHistory,
    loadProject: _loadProject,
    getCurrentProjectId: function() { return _currentProjectId; },
    setCurrentProjectId: function(id) {
      _currentProjectId = id;
      if (!id) _currentSessionId = _createSessionId();
    },
    getCurrentSessionId: function() { return _currentSessionId; },
    setCurrentSessionId: function(sid) { _currentSessionId = sid; },
    resetSession: function() {
      _currentProjectId = null;
      _currentSessionId = _createSessionId();
      return _currentSessionId;
    },
  };
})();
