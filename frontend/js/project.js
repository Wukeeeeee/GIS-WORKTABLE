window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  let _currentProjectId = null;

  function init() {
    _bindHistoryToggle();
    _bindHistoryClose();
    _bindClearAll();
  }

  function _getProvider() {
    const sel = document.getElementById('modelSelector');
    return sel ? sel.value : 'glm-routed';
  }

  function _getMapState() {
    if (GIS.map && typeof GIS.map.getState === 'function') {
      const s = GIS.map.getState();
      return { lng: s.center ? s.center.lng : 0, lat: s.center ? s.center.lat : 0, zoom: s.zoom || 10 };
    }
    return {};
  }

  function _collectMessages() {
    const msgs = [];
    const container = document.getElementById('chatMessages');
    if (!container) return msgs;
    const rows = container.querySelectorAll('.message');
    rows.forEach(function(row) {
      const isUser = row.classList.contains('message-user');
      const bubble = row.querySelector('.message-bubble');
      if (!bubble) return;
      if (row.id === 'ai-loading-msg') return;
      var content = bubble.innerText || bubble.textContent || '';
      content = content.replace(/^\d{2}:\d{2}:\d{2}\s*/, '');
      msgs.push({ role: isUser ? 'user' : 'assistant', content: content.trim() });
    });
    return msgs;
  }

  function _collectLayers() {
    if (GIS.layers && typeof GIS.layers.getLayers === 'function') {
      return GIS.layers.getLayers();
    }
    return [];
  }

  function _renderHistoryList(projects) {
    const list = document.getElementById('projectHistoryList');
    if (!list) return;
    if (!projects || projects.length === 0) {
      list.innerHTML =
        '<div class="history-empty">' +
          '<svg width="48" height="48" opacity="0.3"><use href="assets/icons.svg#icon-history"/></svg>' +
          '<div class="history-empty-text">暂无历史会话</div>' +
          '<div class="history-empty-hint">开始新对话后自动保存</div>' +
        '</div>';
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
          return '<div class="history-item" data-id="' + p.id + '">' +
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
                '<svg width="14" height="14"><use href="assets/icons.svg#icon-send"/></svg>' +
              '</button>' +
              '<button class="history-action-btn" data-action="rename" title="重命名">' +
                '<svg width="14" height="14"><use href="assets/icons.svg#icon-rename"/></svg>' +
              '</button>' +
              '<button class="history-action-btn history-action-delete" data-action="delete" title="删除">' +
                '<svg width="14" height="14"><use href="assets/icons.svg#icon-delete"/></svg>' +
              '</button>' +
              '<button class="history-action-btn" data-action="export" title="导出">' +
                '<svg width="14" height="14"><use href="assets/icons.svg#icon-download"/></svg>' +
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
          else if (action === 'export') _exportProject(pid);
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
    GIS.api.loadProject(pid).then(function(data) {
      if (!data || data.error) {
        GIS.chat.addMessage('加载工程失败', 'system');
        return;
      }
      _currentProjectId = data.id;
      // 先恢复聊天面板可见，再加载消息
      _hideHistory();
      GIS.chat.clear();
      if (data.messages) {
        data.messages.forEach(function(msg) {
          if (msg.role === 'user') GIS.chat.addMessage(msg.content, 'user');
          else if (msg.role === 'assistant') GIS.chat.addMessage(msg.content, 'ai');
        });
      }
      if (data.layers) {
        data.layers.forEach(function(layer) {
          if (layer.geojson && GIS.map && GIS.map.loadGeoJSON) {
            var uniqueName = (layer.name || 'layer') + '_loaded';
            try { GIS.map.loadGeoJSON(layer.geojson, uniqueName); } catch(_) {}
            if (GIS.layers && GIS.layers.addLayer) {
              GIS.layers.addLayer({
                filename: layer.name || '加载图层',
                geojson: layer.geojson,
                geometry_type: layer.geometry_type || '未知',
                crs: 'WGS-84',
                visible: true,
                source: layer.source || 'ai',
              });
            }
          }
        });
      }
      if (data.mapState && data.mapState.lng && GIS.map && GIS.map.setView) {
        try { GIS.map.setView([data.mapState.lat, data.mapState.lng], data.mapState.zoom || 10); } catch(_) {}
      }
      GIS.chat.addMessage('已恢复工程: ' + (data.name || ''), 'system');
    }).catch(function(err) {
      GIS.chat.addMessage('加载工程失败: ' + err.message, 'system');
    });
  }

  function _deleteProject(pid, itemEl) {
    if (!confirm('确定删除此工程？')) return;
    GIS.api.deleteProject(pid).then(function() {
      if (itemEl && itemEl.parentNode) itemEl.remove();
      _refreshList();
    }).catch(function(err) {
      GIS.chat.addMessage('删除失败: ' + err.message, 'system');
    });
  }

  function _promptRename(pid, itemEl) {
    var currentName = '';
    var nameEl = itemEl ? itemEl.querySelector('.history-item-name') : null;
    if (nameEl) currentName = nameEl.textContent;
    var newName = prompt('重命名工程：', currentName);
    if (!newName || newName.trim() === '') return;
    GIS.api.renameProject(pid, newName.trim()).then(function() {
      if (nameEl) nameEl.textContent = newName.trim();
    }).catch(function(err) {
      GIS.chat.addMessage('重命名失败: ' + err.message, 'system');
    });
  }

  function _exportProject(pid) {
    GIS.api.exportProject(pid).then(function(blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'project_' + pid + '.giswork';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }).catch(function(err) {
      GIS.chat.addMessage('导出失败: ' + err.message, 'system');
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
        GIS.chat.addMessage('删除失败: ' + err.message, 'system');
      });
    });
  }

  GIS.project = {
    init: init,
    save: function() {
      return GIS.api.saveProject({
        project_id: _currentProjectId,
        session_id: 'default',
        provider: _getProvider(),
        map_state: _getMapState(),
        messages: _collectMessages(),
        layers: _collectLayers(),
      }).then(function(res) {
        if (res && res.id) _currentProjectId = res.id;
        return res;
      }).catch(function() {});
    },
    autoSave: function() {
      return GIS.api.autoSaveProject().then(function(res) {
        if (res && res.id) _currentProjectId = res.id;
        return res;
      }).catch(function() {});
    },
    showHistory: _showHistory,
    hideHistory: _hideHistory,
    getCurrentProjectId: function() { return _currentProjectId; },
    setCurrentProjectId: function(id) { _currentProjectId = id; },
  };
})();
