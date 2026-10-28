/* Map-first workspace: stable data dock, shared menus and optional AI assistant. */
(function() {
  'use strict';
  const GIS = window.GIS = window.GIS || {};
  const _toolTasks = {};
  let sampleLoadSequence = 0;
  function tr(key, fallback) { return GIS.i18n ? GIS.i18n.t(key, fallback) : fallback; }
  function layerCount(count) { return GIS.i18n ? GIS.i18n.layerCount(count) : count + ' 个图层'; }
  const paths = {"home":"/assets/ui-icons/workspace-home.png","map":"/assets/ui-icons/workspace-map.png","folder":"/assets/ui-icons/workspace-folder.png","layers":"/assets/ui-icons/workspace-layers.png","tool":"/assets/ui-icons/workspace-tool.png","ai":"/assets/ui-icons/workspace-ai.png","globe":"/assets/ui-icons/workspace-globe.png","upload":"/assets/ui-icons/workspace-upload.png","history":"/assets/ui-icons/workspace-history.png","settings":"/assets/ui-icons/workspace-settings.png","close":"/assets/ui-icons/workspace-close.png","chevron":"/assets/ui-icons/workspace-chevron.png"};
  function escapeMarkup(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function(ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function icon(name) {
    return '<span class="ui-icon" aria-hidden="true" style="--ui-icon-image:url(' + (paths[name] || '') + ')"></span>';
  }
  function panelBounds(width) {
    const map = document.querySelector('.map-area');
    const r = map ? map.getBoundingClientRect() : {left:12, right:window.innerWidth-12};
    const top = document.querySelector('.workspace-topbar');
    const status = document.querySelector('.workspace-statusbar');
    let left = r.left + 12, right = r.right - 12;
    const assistant = document.querySelector('.chat-panel');
    if (assistant && !assistant.hidden) {
      const availableLeft = assistant.getBoundingClientRect().right + 12;
      if (right - availableLeft >= width) left = Math.max(left, availableLeft);
    }
    if (right - left < width) { left = 12; right = window.innerWidth - 12; }
    return {left:left, right:right, top:top ? top.getBoundingClientRect().bottom+12 : 12,
      bottom:status ? status.getBoundingClientRect().top-12 : window.innerHeight-12};
  }
  function clampPanel(container, left, top, fallbackWidth) {
    if (typeof container === 'string') container = document.getElementById(container);
    if (!container) return [left || 0, top || 0];
    const width = container.offsetWidth || Math.min(fallbackWidth || 380, window.innerWidth-24);
    const height = container.offsetHeight || 300;
    const bounds = panelBounds(width);
    return [Math.max(bounds.left, Math.min(bounds.right-width, left)),
      Math.max(bounds.top, Math.min(bounds.bottom-height, top))];
  }
  function centerPanel(container, fallbackWidth) {
    if (typeof container === 'string') container = document.getElementById(container);
    if (!container) return [0, 0];
    container.style.position = 'fixed';
    container.style.zIndex = '1200';
    const width = container.offsetWidth || Math.min(fallbackWidth || 380, window.innerWidth-24);
    const bounds = panelBounds(width);
    const pos = clampPanel(container, bounds.left+(bounds.right-bounds.left-width)/2, bounds.top+12, width);
    container.style.left = pos[0]+'px'; container.style.top = pos[1]+'px';
    container.style.transform = 'none';
    return pos;
  }
  function preparePanel(panelId, headerId, closeId, label) {
    const panel = document.getElementById(panelId);
    const header = document.getElementById(headerId);
    const close = document.getElementById(closeId);
    if (!panel || !header || !close) return;
    panel.classList.add('workspace-floating-panel');
    header.classList.add('workspace-panel-heading');
    close.title = '关闭' + label;
    close.setAttribute('aria-label', close.title);
    close.classList.add('workspace-panel-close', 'workspace-icon-btn');
    // 注入标准矢量关闭图标，确保无论在任何黑白模式下都清晰可见
    close.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

    makeResizable(panel, label);
    makeDraggable(panel, header);

    // Keep the panel heading fixed while its existing body collapses through a grid track.
    let panelContent = Array.from(panel.children).find(function(child) {
      return child.classList.contains('workspace-panel-content');
    });
    if (!panelContent) {
      panelContent = document.createElement('div');
      panelContent.className = 'workspace-panel-content';
      const inner = document.createElement('div');
      inner.className = 'workspace-panel-content-inner';
      const resizeHandle = Array.from(panel.children).find(function(child) {
        return child.classList.contains('workspace-window-resize');
      });
      Array.from(panel.children).forEach(function(child) {
        if (child !== header && child !== resizeHandle) inner.appendChild(child);
      });
      panelContent.appendChild(inner);
      panel.insertBefore(panelContent, resizeHandle || null);
    }
    panel.querySelectorAll('.spatial-field, .network-field').forEach(function(field) {
      const labelEl = field.querySelector('label');
      const input = field.querySelector('input[id], select[id], textarea[id]');
      if (labelEl && input && !labelEl.contains(input)) labelEl.htmlFor = input.id;
    });

    let actions = header.querySelector('.workspace-panel-actions');
    if (!actions) {
      actions = document.createElement('div');
      actions.className = 'workspace-panel-actions';
      header.appendChild(actions);
    }

    if (!actions.querySelector('.workspace-panel-fold')) {
      const fold = document.createElement('button');
      fold.className = 'workspace-panel-fold workspace-icon-btn';
      fold.type = 'button';
      fold.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"></line></svg>';
      function update(folded) {
        fold.title = (folded ? '展开' : '折叠') + label;
        fold.setAttribute('aria-label', fold.title);
        fold.setAttribute('aria-expanded', String(!folded));
        panelContent.inert = folded;
        panelContent.setAttribute('aria-hidden', String(folded));
      }
      update(false);
      fold.onclick = function() {
        const folded = panel.classList.toggle('workspace-panel-folded');
        update(folded);
        if (!folded) keepPanelsVisible();
      };
      actions.appendChild(fold);
    }

    if (!close._hasCloseHandler) {
      close._hasCloseHandler = true;
      close.addEventListener('click', function(e) {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        panel.style.setProperty('display', 'none', 'important');
        panel.classList.add('is-hidden');
        panel.setAttribute('hidden', '');
        if (panel.id === 'featurePanel' && window.GIS && window.GIS.state && typeof window.GIS.state.clearSelection === 'function') {
          window.GIS.state.clearSelection();
        }
      });
    }

    actions.appendChild(close);
  }
  function promptModal(title, desc, defaultValue, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'workspace-modal-overlay';
    overlay.innerHTML =
      '<div class="workspace-modal-dialog" role="dialog" aria-modal="true">' +
        '<div class="workspace-modal-title">' + escapeMarkup(title || '请输入') + '</div>' +
        (desc ? '<div class="workspace-modal-desc">' + escapeMarkup(desc) + '</div>' : '') +
        '<input type="text" class="workspace-modal-input" value="' + escapeMarkup(defaultValue || '') + '" />' +
        '<div class="workspace-modal-actions">' +
          '<button type="button" class="workspace-modal-btn cancel">取消</button>' +
          '<button type="button" class="workspace-modal-btn primary">确定</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);
    const input = overlay.querySelector('.workspace-modal-input');
    const cancelBtn = overlay.querySelector('.cancel');
    const okBtn = overlay.querySelector('.primary');
    input.focus();
    input.select();
    function close() { overlay.remove(); }
    cancelBtn.onclick = close;
    overlay.onclick = function(e) { if (e.target === overlay) close(); };
    function submit() {
      const val = input.value.trim();
      close();
      if (typeof onConfirm === 'function') onConfirm(val);
    }
    okBtn.onclick = submit;
    input.onkeydown = function(e) {
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
      if (e.key === 'Escape') { e.preventDefault(); close(); }
    };
  }
  function confirmModal(title, desc, onConfirm, isDanger) {
    const overlay = document.createElement('div');
    overlay.className = 'workspace-modal-overlay';
    overlay.innerHTML =
      '<div class="workspace-modal-dialog" role="dialog" aria-modal="true">' +
        '<div class="workspace-modal-title">' + escapeMarkup(title || '确认操作') + '</div>' +
        (desc ? '<div class="workspace-modal-desc">' + escapeMarkup(desc) + '</div>' : '') +
        '<div class="workspace-modal-actions">' +
          '<button type="button" class="workspace-modal-btn cancel">取消</button>' +
          '<button type="button" class="workspace-modal-btn ' + (isDanger ? 'danger' : 'primary') + '">确定</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);
    const cancelBtn = overlay.querySelector('.cancel');
    const okBtn = overlay.querySelector('.' + (isDanger ? 'danger' : 'primary'));
    function close() { overlay.remove(); }
    cancelBtn.onclick = close;
    overlay.onclick = function(e) { if (e.target === overlay) close(); };
    okBtn.onclick = function() {
      close();
      if (typeof onConfirm === 'function') onConfirm();
    };
  }
  function saveProjectModal(currentName, onSaveCloud, onExportLocal) {
    const overlay = document.createElement('div');
    overlay.className = 'workspace-modal-overlay';
    overlay.innerHTML =
      '<div class="workspace-modal-dialog" role="dialog" aria-modal="true">' +
        '<div class="workspace-modal-title">' + tr('project.save-title', '保存工程') + '</div>' +
        '<div class="workspace-modal-desc">' + tr('project.save-desc', '可将工程记录保存至本地工作台数据库，或直接打包导出为 .giswork 独立工程文件。') + '</div>' +
        '<label style="display:block;font-size:12px;color:var(--on-surface-variant);margin-bottom:6px;">' + tr('project.name', '工程名称') + '</label>' +
        '<input type="text" class="workspace-modal-input" id="saveProjNameInput" value="' + escapeMarkup(currentName || tr('project.not-named', '未命名工程')) + '" />' +
        '<div class="workspace-modal-actions">' +
          '<button type="button" class="workspace-modal-btn cancel">' + tr('common.cancel', '取消') + '</button>' +
          '<button type="button" class="workspace-modal-btn" id="saveProjExportBtn">' + tr('project.export-local', '导出本地文件') + '</button>' +
          '<button type="button" class="workspace-modal-btn primary" id="saveProjSaveBtn">' + tr('project.save-workspace', '保存到工作台') + '</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);
    const input = overlay.querySelector('#saveProjNameInput');
    const cancelBtn = overlay.querySelector('.cancel');
    const exportBtn = overlay.querySelector('#saveProjExportBtn');
    const saveBtn = overlay.querySelector('#saveProjSaveBtn');
    input.focus();
    input.select();
    function close() { overlay.remove(); }
    cancelBtn.onclick = close;
    overlay.onclick = function(e) { if (e.target === overlay) close(); };
    saveBtn.onclick = function() {
      const name = input.value.trim() || currentName || tr('project.not-named', '未命名工程');
      close();
      if (typeof onSaveCloud === 'function') onSaveCloud(name);
    };
    exportBtn.onclick = function() {
      const name = input.value.trim() || currentName || tr('project.not-named', '未命名工程');
      close();
      if (typeof onExportLocal === 'function') onExportLocal(name);
    };
    input.onkeydown = function(e) {
      if (e.key === 'Enter') { e.preventDefault(); saveBtn.click(); }
      if (e.key === 'Escape') { e.preventDefault(); close(); }
    };
  }
  function openSaveProject() {
    const nameEl = document.getElementById('workspaceCurrentProjectName');
    const untitled = tr('project.not-named', '未命名工程');
    const curName = (nameEl ? nameEl.textContent : untitled).trim() || untitled;
    saveProjectModal(curName, function(saveName) {
      if (!GIS.project || !GIS.project.save) return;
      GIS.project.save(saveName).then(function(res) {
        if (!res || !res.id) throw new Error('保存工程未返回工程编号');
        if (nameEl) nameEl.textContent = res.name || saveName;
        renderRecentProjects();
        if (res.warning && GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage(escapeMarkup(res.warning), 'system', { pill: true });
        if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;margin-right:4px;"><path d="M20 6L9 17l-5-5"/></svg> ' + tr('project.saved', '已保存工程「') + escapeMarkup(res.name || saveName) + (GIS.i18n && GIS.i18n.isEnglish() ? '' : '」'), 'system');
      }).catch(function(err) {
        if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;margin-right:4px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> ' + tr('project.save-failed', '保存工程失败: ') + escapeMarkup(err.message || err), 'system');
      });
    }, function(exportName) {
      if (!GIS.project || !GIS.project.save) return;
      var saved = false;
      GIS.project.save(exportName).then(function(res) {
        if (!res || !res.id) throw new Error('保存工程未返回工程编号');
        saved = true;
        if (nameEl) nameEl.textContent = res.name || exportName;
        renderRecentProjects();
        if (res.warning && GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage(escapeMarkup(res.warning), 'system', { pill: true });
        if (!GIS.project.exportCurrent) throw new Error('工程导出功能不可用');
        return GIS.project.exportCurrent(res.id, exportName);
      }).then(function() {
        if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;margin-right:4px;"><path d="M20 6L9 17l-5-5"/></svg> ' + tr('project.download-started', '已开始下载工程文件: ') + escapeMarkup(exportName) + '.giswork', 'system');
      }).catch(function(err) {
        var message = saved ? tr('project.saved-but-export-failed', '工程已保存，但导出文件失败: ') : tr('project.save-failed', '保存工程失败: ');
        if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;margin-right:4px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> ' + message + escapeMarkup(err.message || err), 'system');
      });
    });
  }
  function loadProjectModal() {
    const overlay = document.createElement('div');
    overlay.className = 'workspace-modal-overlay';
    overlay.innerHTML =
      '<div class="workspace-modal-dialog" role="dialog" aria-modal="true" style="max-width:520px;max-height:85vh;display:flex;flex-direction:column;">' +
        '<div class="workspace-modal-title">' + tr('project.load-title', '加载工程') + '</div>' +
        '<div class="workspace-modal-desc" style="margin-bottom:12px;">' + tr('project.load-desc', '从已保存的历史工程记录中选择恢复，或导入外部 .giswork 工程文件。') + '</div>' +
        '<div style="margin-bottom:12px;display:flex;gap:8px;">' +
          '<button type="button" class="workspace-modal-btn primary" id="loadProjImportBtn" style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;">' +
            '<span class="ui-icon" aria-hidden="true" style="width:14px;height:14px;--ui-icon-image:url(\'/assets/ui-icons/icon-e5befca1a25f.png\');"></span>' +
            '<span>' + tr('project.import-local', '导入本地 .giswork 工程文件') + '</span>' +
          '</button>' +
          '<input type="file" id="loadProjFileInput" accept=".giswork,.zip" style="display:none;" />' +
        '</div>' +
        '<div style="font-size:12px;font-weight:600;color:var(--on-surface-variant);margin-bottom:6px;">' + tr('project.saved-records', '已保存工程记录') + '</div>' +
        '<div id="loadProjListContainer" class="custom-scrollbar" style="flex:1;min-height:160px;max-height:300px;overflow-y:auto;border:1px solid var(--outline-variant);border-radius:8px;padding:6px;background:var(--surface-container-lowest);">' +
          '<div style="padding:20px;text-align:center;color:var(--on-surface-variant);font-size:12px;">' + tr('project.loading-list', '正在加载工程列表...') + '</div>' +
        '</div>' +
        '<div class="workspace-modal-actions" style="margin-top:16px;">' +
          '<button type="button" class="workspace-modal-btn cancel">' + tr('common.cancel', '取消') + '</button>' +
          '<button type="button" class="workspace-modal-btn" id="loadProjOpenSidebarBtn">' + tr('project.open-history', '打开侧边栏历史') + '</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    function close() { overlay.remove(); }
    overlay.querySelector('.cancel').onclick = close;
    overlay.onclick = function(e) { if (e.target === overlay) close(); };

    const openSidebarBtn = overlay.querySelector('#loadProjOpenSidebarBtn');
    if (openSidebarBtn) {
      openSidebarBtn.onclick = function() {
        close();
        if (typeof toggleAI === 'function') toggleAI(true);
        if (GIS.project && GIS.project.showHistory) GIS.project.showHistory();
      };
    }

    const importBtn = overlay.querySelector('#loadProjImportBtn');
    const fileInput = overlay.querySelector('#loadProjFileInput');
    if (importBtn && fileInput) {
      importBtn.onclick = function() { fileInput.click(); };
      fileInput.onchange = function() {
        const file = fileInput.files && fileInput.files[0];
        if (!file) return;
        // Allow selecting the same file again if this import fails.
        fileInput.value = '';
        importBtn.disabled = true;
        importBtn.textContent = '正在导入...';
        if (GIS.api && GIS.api.importProject) {
          GIS.api.importProject(file).then(function(res) {
            close();
            if (res && res.id && GIS.project && GIS.project.loadProject) {
              GIS.project.loadProject(res.id);
              if (res.warning) {
                if (GIS.toast && typeof GIS.toast.warn === 'function') GIS.toast.warn(res.warning);
                else if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage(escapeMarkup(res.warning), 'system');
              }
            } else if (res && res.name) {
              if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;margin-right:4px;"><path d="M20 6L9 17l-5-5"/></svg> 已导入工程「' + escapeMarkup(res.name) + '」', 'system');
              renderRecentProjects();
            }
          }).catch(function(err) {
            importBtn.disabled = false;
            importBtn.textContent = '导入本地 .giswork 工程文件';
            alert('导入工程失败: ' + (err.message || err));
          });
        } else {
          alert('导入工程接口未就绪');
        }
      };
    }

    const listContainer = overlay.querySelector('#loadProjListContainer');
    if (listContainer && GIS.api && GIS.api.listProjects) {
      GIS.api.listProjects().then(function(data) {
        const projects = (data && data.projects) || [];
        if (!projects.length) {
          listContainer.innerHTML = '<div style="padding:24px;text-align:center;color:var(--on-surface-variant);font-size:12px;">' + tr('project.no-saved', '暂无已保存的工程记录') + '</div>';
          return;
        }
        listContainer.innerHTML = '';
        projects.forEach(function(p) {
          const item = document.createElement('div');
          item.className = 'workspace-load-project-item';
          item.style.cssText = 'padding:10px 12px;border-radius:6px;margin-bottom:4px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;transition:background 0.15s;border:1px solid transparent;';
          const untitled = tr('project.not-named', '未命名工程');
          const name = (p.name || untitled).replace(/^\[用户引用了上一条回复.*?\]\s*/s, '').replace(/^\[附图层:.*?\]\s*/s, '').trim() || untitled;
          const dateLocale = GIS.i18n && GIS.i18n.isEnglish() ? 'en-US' : 'zh-CN';
          const dateStr = p.updated_at ? new Date(p.updated_at).toLocaleString(dateLocale, {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
          const metaStr = (p.layers_count !== undefined ? layerCount(p.layers_count) : '') + (dateStr ? ' · ' + dateStr : '');
          
          item.innerHTML =
            '<div style="overflow:hidden;padding-right:8px;">' +
              '<div style="font-size:13px;font-weight:600;color:var(--on-surface);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escapeMarkup(name) + '</div>' +
              '<div style="font-size:11px;color:var(--on-surface-variant);margin-top:2px;">' + escapeMarkup(metaStr) + '</div>' +
            '</div>' +
            '<button type="button" class="workspace-btn" style="flex-shrink:0;padding:4px 10px;font-size:11px;background:var(--surface-container-high);border-radius:4px;">' + tr('project.restore', '恢复') + '</button>';
          
          item.onmouseenter = function() { item.style.background = 'var(--surface-container-high)'; item.style.borderColor = 'var(--outline-variant)'; };
          item.onmouseleave = function() { item.style.background = ''; item.style.borderColor = 'transparent'; };
          item.onclick = function() {
            close();
            if (GIS.project && GIS.project.loadProject) {
              GIS.project.loadProject(p.id);
            }
          };
          listContainer.appendChild(item);
        });
      }).catch(function(err) {
        listContainer.innerHTML = '<div style="padding:24px;text-align:center;color:var(--error,#d32f2f);font-size:12px;">' + tr('project.load-failed', '加载失败: ') + escapeMarkup(err.message || err) + '</div>';
      });
    }
  }
  function openLoadProject() {
    loadProjectModal();
  }
  function makeResizable(panel, label) {
    if (panel.querySelector('.workspace-window-resize')) return;
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'workspace-window-resize';
    handle.title = '拖动右下角调整窗口大小；方向键调整，双击恢复默认';
    handle.setAttribute('aria-label', '调整'+label+'窗口大小');
    handle.setAttribute('aria-controls', panel.id);
    const defaultWidth = panel.style.width;
    const defaultHeight = panel.style.height;
    let drag = null;
    function resize(width, height) {
      const r = panel.getBoundingClientRect();
      const status = document.querySelector('.workspace-statusbar');
      const maxWidth = Math.max(200, window.innerWidth-r.left-12);
      const maxHeight = Math.max(140, (status ? status.getBoundingClientRect().top : window.innerHeight)-r.top-12);
      const isTool = panel.matches('.spatial-panel, .network-panel');
      const minW = isTool ? 320 : 260;
      const minH = isTool ? 260 : 160;
      panel.style.setProperty('width', Math.min(maxWidth, Math.max(minW, width)) + 'px', 'important');
      panel.style.setProperty('height', Math.min(maxHeight, Math.max(minH, height)) + 'px', 'important');
    }
    handle.addEventListener('pointerdown', function(e) {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      const r = panel.getBoundingClientRect();
      drag = {id:e.pointerId, x:e.clientX, y:e.clientY, width:r.width, height:r.height};
      handle.setPointerCapture(e.pointerId);
      document.documentElement.classList.add('workspace-window-resizing');
    });
    handle.addEventListener('pointermove', function(e) {
      if (drag && drag.id === e.pointerId) {
        // 向右下拖动 deltaX > 0, deltaY > 0，宽度与高度均增加
        resize(drag.width + (e.clientX - drag.x), drag.height + (e.clientY - drag.y));
      }
    });
    function finish(e) {
      if (!drag || drag.id !== e.pointerId) return;
      drag = null;
      document.documentElement.classList.remove('workspace-window-resizing');
    }
    handle.addEventListener('pointerup', finish);
    handle.addEventListener('pointercancel', finish);
    handle.addEventListener('lostpointercapture', finish);
    handle.addEventListener('keydown', function(e) {
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const r = panel.getBoundingClientRect();
      resize(r.width+(e.key === 'ArrowRight' ? 20 : e.key === 'ArrowLeft' ? -20 : 0),
        r.height+(e.key === 'ArrowDown' ? 20 : e.key === 'ArrowUp' ? -20 : 0));
    });
    handle.addEventListener('dblclick', function() { panel.style.width=defaultWidth; panel.style.height=defaultHeight; keepPanelsVisible(); });
    panel.appendChild(handle);
  }

  function makeDraggable(panel, handleEl) {
    if (!panel || !handleEl) return;
    if (handleEl._hasDragInit) return;
    handleEl._hasDragInit = true;
    handleEl.style.cursor = 'move';
    let drag = null;
    handleEl.addEventListener('pointerdown', function(e) {
      if (e.button !== 0) return;
      if (e.target.closest('button, input, select, textarea, a, .workspace-icon-btn, .workspace-panel-actions')) return;
      e.preventDefault();
      const r = panel.getBoundingClientRect();
      drag = {
        id: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        startLeft: r.left,
        startTop: r.top,
      };
      handleEl.setPointerCapture(e.pointerId);
      panel.classList.add('workspace-dragging');
    });
    handleEl.addEventListener('pointermove', function(e) {
      if (!drag || drag.id !== e.pointerId) return;
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;
      const pos = clampPanel(panel, drag.startLeft + dx, drag.startTop + dy, panel.offsetWidth);
      panel.style.setProperty('position', 'fixed', 'important');
      panel.style.setProperty('left', pos[0] + 'px', 'important');
      panel.style.setProperty('top', pos[1] + 'px', 'important');
      panel.style.setProperty('right', 'auto', 'important');
      panel.style.setProperty('bottom', 'auto', 'important');
      panel.style.setProperty('transform', 'none', 'important');
      panel.style.zIndex = '1200';
    });
    function end(e) {
      if (!drag || drag.id !== e.pointerId) return;
      drag = null;
      panel.classList.remove('workspace-dragging');
    }
    handleEl.addEventListener('pointerup', end);
    handleEl.addEventListener('pointercancel', end);
    handleEl.addEventListener('lostpointercapture', end);
  }
  function toolFeedback(panelId, result, error) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    panel.setAttribute('aria-busy', 'false');
    panel.querySelectorAll('.spatial-run-btn, .spatial-tab, input, select, textarea').forEach(function(btn) { btn.disabled=false; });
    const task = _toolTasks[panelId] || {};
    if (task.timer) { clearInterval(task.timer); task.timer = null; }
    const duration = task.startTime ? ((Date.now() - task.startTime) / 1000).toFixed(1) : null;
    let output = panel.querySelector('.workspace-tool-feedback');
    if (!output) {
      output = document.createElement('section');
      output.className = 'workspace-tool-feedback';
      output.setAttribute('role', 'status');
      output.setAttribute('aria-live', 'polite');
      panel.insertBefore(output, panel.querySelector('.workspace-window-resize'));
    }
    const english = !!(GIS.i18n && GIS.i18n.isEnglish());
    const rawMessage = error ? (error.message || String(error)) : String(result && result.response || '处理结束，未返回说明。');
    const statLabels = english
      ? {count:'Records', non_null:'Non-null', null:'Null', min:'Minimum', max:'Maximum', mean:'Mean', sum:'Sum', std:'Standard deviation'}
      : {count:'记录数', non_null:'有效值', null:'空值', min:'最小值', max:'最大值', mean:'平均值', sum:'总和', std:'标准差'};
    let message = rawMessage.replace(/^\s*[\p{S}\uFE0F]+\s*/u, '').replace(/^(\s*)(count|non_null|null|min|max|mean|sum|std):/gm,
      function(_, space, key) { return space+statLabels[key]+(english?':':'：'); });
    const parameterWarnings = result && Array.isArray(result.param_warnings)
      ? result.param_warnings.map(String).filter(Boolean)
      : [];
    if (parameterWarnings.length) {
      message += '\n\n' + (english ? 'Parameter notes: ' : '参数提示：') + parameterWarnings.join(english ? '; ' : '；');
    }
    if (english) {
      const bufferResult = message.match(/^已为「(.+?)」创建([\d.]+)m缓冲区，(\d+) 个要素，已加载到地图$/);
      if (bufferResult) message = tr('workspace.buffer-created', 'Created a {distance} m buffer around "{layer}" with {count} features. Added it to the map.')
        .replace('{layer}', GIS.i18n.layerLabel(bufferResult[1])).replace('{distance}', bufferResult[2]).replace('{count}', bufferResult[3]);
    }
    const failed = !!error || (result && result.ok === false) || /^(?:[^\n:：]{0,24}失败[:：]|未找到|工具执行失败|错误[:：])/.test(message.trim());
    const count = result && result.layers ? result.layers.length : 0;
    const durText = duration ? (english ? ' · ' + duration + 's' : '（耗时 ' + duration + 's）') : '';

    let html = '<strong>' + (failed ? (english ? 'Not completed' : '执行未完成') + durText : (count ? (english ? 'Completed · ' + count + ' layer(s) added' : '已完成 · 新增 ' + count + ' 个图层') + durText : (english ? 'Result returned' : '结果已返回') + durText)) + '</strong>';
    if (result && result.layers && result.layers.length) {
      html += '<div class="workspace-feedback-artifacts">' + (english ? 'Output layers: ' : '产物图层：') + result.layers.map(function(l) { var name = typeof l === 'string' ? l : (l.name || l.filename || '图层'); return '<span class="workspace-artifact-badge">' + escapeMarkup(GIS.i18n && GIS.i18n.layerLabel ? GIS.i18n.layerLabel(name) : name) + '</span>'; }).join(' ') + '</div>';
    }
    html += '<p>' + escapeMarkup(message) + '</p>';
    if (failed && task.btn && typeof task.btn.click === 'function') {
      html += '<div class="workspace-feedback-actions"><button type="button" class="workspace-retry-btn" data-action="retry">' + (english ? 'Retry this operation' : '重试此操作') + '</button></div>';
    }
    output.innerHTML = html;
    output.dataset.state = failed ? 'error' : 'complete';

    const retryBtn = output.querySelector('[data-action="retry"]');
    if (retryBtn) {
      retryBtn.onclick = function() {
        if (task.btn && !task.btn.disabled) {
          output.innerHTML = '<strong>准备重试…</strong><p>保留现有参数，重新提交执行</p>';
          task.btn.click();
        }
      };
    }
    const existing = panel.querySelector('.spatial-result');
    if (existing) existing.style.display='none';
    return !failed;
  }
  function toolPending(panelId, btn) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    const existingTask = _toolTasks[panelId];
    if (existingTask && existingTask.timer) clearInterval(existingTask.timer);

    const task = _toolTasks[panelId] = {
      startTime: Date.now(),
      btn: btn || panel.querySelector('.spatial-run-btn:not([disabled])') || (existingTask && existingTask.btn)
    };

    let output = panel.querySelector('.workspace-tool-feedback');
    if (!output) {
      output = document.createElement('section');
      output.className = 'workspace-tool-feedback';
      output.setAttribute('role', 'status');
      output.setAttribute('aria-live', 'polite');
      panel.insertBefore(output, panel.querySelector('.workspace-window-resize'));
    }
    output.dataset.state = 'pending';
    output.innerHTML = '<strong>正在处理… (0.0s)</strong>' +
      '<div class="workspace-feedback-steps"><span>1. 校验输入参数</span> → <span class="active">2. 执行空间计算</span> → <span>3. 渲染结果图层</span></div>' +
      '<p>正在进行空间运算，处理完成后结果和新增图层会自动上图展示。</p>' +
      '<div class="workspace-feedback-actions"><button type="button" class="workspace-cancel-btn" data-action="cancel">取消等待</button><span class="workspace-feedback-tip">后台可能继续完成计算</span></div>';

    const timeStrong = output.querySelector('strong');
    task.timer = setInterval(function() {
      const sec = ((Date.now() - task.startTime) / 1000).toFixed(1);
      if (timeStrong) timeStrong.textContent = '正在处理… (' + sec + 's)';
    }, 200);

    const cancelBtn = output.querySelector('[data-action="cancel"]');
    if (cancelBtn) {
      cancelBtn.onclick = function() {
        if (task.timer) clearInterval(task.timer);
        // This stops the UI wait only; the request has no cancellation signal and may still
        // complete. Keep run buttons locked so a late result cannot overwrite a newer task.
        panel.setAttribute('aria-busy', 'true');
        panel.querySelectorAll('.spatial-tab').forEach(function(b) { b.disabled=false; });
        output.dataset.state = 'cancelled';
        output.innerHTML = '<strong>已停止等待提示</strong><p>当前操作仍在后台执行，参数与运行按钮暂时锁定；任务返回后可继续修改。</p>';
      };
    }

    panel.setAttribute('aria-busy', 'true');
    panel.querySelectorAll('.spatial-run-btn, .spatial-tab, input, select, textarea').forEach(function(b) { b.disabled=true; });
  }
  function expandPanel(panelId) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    panel.classList.remove('workspace-panel-folded');
    // preparePanel's close handler also sets hidden / is-hidden / display:none!important on the
    // panel element. Clear that state on every open, otherwise the panel stays blank after
    // being closed with the X button and reopened.
    panel.classList.remove('is-hidden');
    panel.removeAttribute('hidden');
    if (panel.style.display === 'none') panel.style.removeProperty('display');
    const fold = panel.querySelector('.workspace-panel-fold');
    if (fold) {
      fold.title = fold.title.replace(/^展开/, '折叠');
      fold.setAttribute('aria-label', fold.title);
      fold.setAttribute('aria-expanded', 'true');
    }
  }
  function keepPanelsVisible() {
    document.querySelectorAll('#spatialPanelContainer, #networkPanelContainer, #spatialStatsPanelContainer, #rasterToolsPanelContainer, #analysisToolsPanelContainer, #debugPanel').forEach(function(container) {
      if (!container.getClientRects().length || !container.offsetHeight) return;
      const r = container.getBoundingClientRect();
      const pos = clampPanel(container, r.left, r.top, r.width);
      container.style.left = pos[0]+'px'; container.style.top = pos[1]+'px';
    });
  }
  let activeTab = 'browser';
  let dock, chat, body, layerPanel, divider;
  let dockWidth = 340;
  function widthLimits() {
    const available = body.clientWidth - 68;
    const max = Math.max(180, Math.min(600, available - (window.innerWidth > 700 ? 396 : 36)));
    return {min: Math.min(260, max), max: max};
  }
  function setDockWidth(width, persist) {
    const limits = widthLimits();
    dockWidth = Math.max(limits.min, Math.min(limits.max, width));
    body.style.setProperty('--workspace-dock-width', dockWidth + 'px');
    divider.setAttribute('aria-valuemin', String(limits.min));
    divider.setAttribute('aria-valuemax', String(limits.max));
    divider.setAttribute('aria-valuenow', String(Math.round(dockWidth)));
    if (persist) { try { localStorage.setItem('gis_workspace_dock_width', String(dockWidth)); } catch (_) {} }
    invalidate();
  }
  function initDivider() {
    divider = document.createElement('div');
    divider.className = 'workspace-divider';
    divider.tabIndex = 0;
    divider.setAttribute('role', 'separator');
    divider.setAttribute('aria-orientation', 'vertical');
    divider.setAttribute('aria-label', '调整侧面板宽度');
    divider.title = '拖动调整宽度，双击恢复默认；也可使用左右方向键';
    body.insertBefore(divider, body.querySelector('.main-content'));
    let drag = null;
    function finish(e) {
      if (!drag || e.pointerId !== drag.id) return;
      drag = null;
      body.classList.remove('workspace-resizing');
      setDockWidth(dockWidth, true);
    }
    divider.addEventListener('pointerdown', function(e) {
      if (e.button !== 0) return;
      e.preventDefault();
      drag = {id: e.pointerId, x: e.clientX, width: dockWidth};
      divider.setPointerCapture(e.pointerId);
      body.classList.add('workspace-resizing');
    });
    divider.addEventListener('pointermove', function(e) {
      if (drag && e.pointerId === drag.id) setDockWidth(drag.width + e.clientX - drag.x, false);
    });
    divider.addEventListener('pointerup', finish);
    divider.addEventListener('pointercancel', finish);
    divider.addEventListener('lostpointercapture', finish);
    divider.addEventListener('dblclick', function() { setDockWidth(340, true); });
    divider.addEventListener('keydown', function(e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' && e.key !== 'Home') return;
      e.preventDefault();
      setDockWidth(e.key === 'Home' ? 340 : dockWidth + (e.key === 'ArrowRight' ? 20 : -20), true);
    });
    let saved = 340;
    try { saved = Number(localStorage.getItem('gis_workspace_dock_width')) || 340; } catch (_) {}
    setDockWidth(saved, false);
  }
  function invalidate() {
    if (divider) divider.hidden = chat.hidden && dock.hidden;
    requestAnimationFrame(function() {
      keepPanelsVisible();
      if (GIS.map) GIS.map.invalidateSize();
      const viewer = GIS.renderers && GIS.renderers.getViewer();
      if (viewer) { viewer.resize(); viewer.scene.requestRender(); }
    });
  }
  function tabLabelKey(name) {
    return {home:'workspace.home',browser:'workspace.data',layers:'workspace.layers',tools:'workspace.tools'}[name] || 'workspace.home';
  }
  function tabLabelChinese(name) {
    return {home:'首页',browser:'数据',layers:'图层',tools:'处理工具'}[name] || '工作台';
  }
  function setTab(name) {
    toggleAI(false);
    if (name !== 'browser' && GIS.geosource) GIS.geosource.closeWorldMap();
    activeTab = name;
    dock.hidden = false;
    try {
      localStorage.setItem('gis_workspace_active_tab', name);
      localStorage.setItem('gis_workspace_dock_closed', 'false');
    } catch (_) {}
    document.querySelectorAll('[data-dock-tab]').forEach(function(btn) {
      const selected = btn.dataset.dockTab === name;
      btn.classList.toggle('active', selected);
      btn.setAttribute('aria-pressed', String(selected));
    });
    document.querySelectorAll('[data-dock-pane]').forEach(function(pane) { pane.hidden = pane.dataset.dockPane !== name; });
    document.getElementById('workspaceDockTitle').textContent = tr(tabLabelKey(name), tabLabelChinese(name));
    document.getElementById('workspaceDockClose').title = tr('workspace.close-panel','关闭面板') + ' · ' + tr(tabLabelKey(name), tabLabelChinese(name));
    document.getElementById('toggleLayerPanel').classList.toggle('active', name === 'layers');
    if (name === 'home') renderRecentProjects();
    invalidate();
  }
  function toggleLayers() {
    if (chat.hidden && !dock.hidden && activeTab === 'layers') closeDock();
    else setTab('layers');
  }
  function closeDock() {
    dock.hidden = true;
    try { localStorage.setItem('gis_workspace_dock_closed', 'true'); } catch (_) {}
    document.querySelectorAll('[data-dock-tab]').forEach(function(btn) {
      btn.classList.remove('active');
      btn.setAttribute('aria-pressed', 'false');
    });
    document.getElementById('toggleLayerPanel').classList.remove('active');
    invalidate();
  }
  function toggleAI(force) {
    const show = typeof force === 'boolean' ? force : chat.hidden;
    chat.hidden = !show;
    document.body.classList.toggle('workspace-ai-open', show);
    dock.inert = show;
    document.querySelectorAll('[data-dock-tab]').forEach(function(btn) {
      const selected = !show && !dock.hidden && btn.dataset.dockTab === activeTab;
      btn.classList.toggle('active', selected);
      btn.setAttribute('aria-pressed', String(selected));
    });
    document.querySelectorAll('[data-workspace-action="ai"]').forEach(function(btn) {
      btn.classList.toggle('active', show);
      btn.setAttribute('aria-pressed', String(show));
      btn.setAttribute('aria-expanded', String(show));
      btn.title = show ? '收起 AI 助手' : '展开 AI 助手';
    });
    invalidate();
  }
  function renderRecentProjects() {
    const container = document.getElementById('workspaceRecentProjectsList');
    if (!container || !(GIS.api && GIS.api.listProjects)) return;
    GIS.api.listProjects().then(function(res) {
      const list = (res && res.projects) ? res.projects.slice(0, 4) : [];
      if (!list.length) {
        container.innerHTML = '<div class="workspace-empty-recent">' + tr('project.no-recent', '暂无保存的工程记录。可以在此保存当前工作或点击下方样例快速体验。') + '</div>';
        return;
      }
      container.innerHTML = list.map(function(p) {
        const title = String(p.name || tr('project.not-named', '未命名工程'));
        const time = String(p.updatedAt || '').slice(0, 16).replace('T', ' ');
        const count = Number(p.layerCount || 0);
        const countLabel = Number.isSafeInteger(count) && count >= 0
          ? layerCount(count)
          : tr('workspace.unknown-layer-count', '图层数未知');
        return '<div class="workspace-recent-item">' +
          '<div class="workspace-recent-info">' +
            '<strong>' + escapeMarkup(title) + '</strong>' +
            '<small>' + escapeMarkup(countLabel) + ' · ' + escapeMarkup(time) + '</small>' +
          '</div>' +
          '<button type="button" class="workspace-recent-btn" data-project-id="' + escapeMarkup(p.id) + '">' + tr('project.open', '打开') + '</button>' +
        '</div>';
      }).join('');
      container.querySelectorAll('.workspace-recent-btn, .workspace-recent-item').forEach(function(el) {
        el.onclick = function(e) {
          e.stopPropagation();
          const pid = this.dataset.projectId || (this.querySelector('.workspace-recent-btn') && this.querySelector('.workspace-recent-btn').dataset.projectId);
          if (!pid) return;
          if (GIS.project && typeof GIS.project.loadProject === 'function') {
            GIS.project.loadProject(pid);
            if (typeof toggleAI === 'function') toggleAI(true);
          } else if (GIS.api && GIS.api.loadProject) {
            document.getElementById('historyBtn').click();
            setTimeout(function() {
              const item = document.querySelector('.history-item[data-id="' + pid + '"]');
              if (item) item.click();
            }, 100);
          }
        };
      });
    }).catch(function() {
      container.innerHTML = '<div class="workspace-empty-recent">加载最近工程失败</div>';
    });
  }
  function loadSample(sampleName) {
    const sampleFiles = {
      buffer: { path: '/samples/demo-polygons.json', name: '样例_多边形地块', hint: '多边形地块' },
      points: { path: '/samples/demo-points.json', name: '样例_POI实心点', hint: 'POI实心圆点' },
      network: { path: '/samples/demo-lines.json', name: '样例_道路路网', hint: '道路网络线' }
    };
    const info = sampleFiles[sampleName];
    if (!info) return;
    const feedback = document.getElementById('workspaceSampleStatus');
    if (feedback) feedback.textContent = '正在加载 ' + info.hint + '…';

    fetch(info.path)
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(gj) {
        if (GIS.map && GIS.map.loadGeoJSON) GIS.map.loadGeoJSON(gj, info.name);
        if (GIS.layers && GIS.layers.addLayer) {
          GIS.layers.addLayer({
            layer_id: 'sample_' + sampleName + '_' + Date.now() + '_' + (++sampleLoadSequence),
            filename: info.name,
            geometry_type: gj.type || 'Vector',
            crs: 'WGS-84',
            geojson: gj,
            source: 'upload',
            visible: true
          });
        }
        if (feedback) feedback.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;margin-right:4px;"><path d="M20 6L9 17l-5-5"/></svg> ' + tr('workspace.sample-loaded','已加载 ') + (GIS.i18n && GIS.i18n.layerLabel ? GIS.i18n.layerLabel(info.name) : info.name) + tr('workspace.sample-loaded-tail','，可前往图层面板或直接在地图查看');
        setTimeout(function() { if (feedback) feedback.textContent = ''; }, 4000);
      })
      .catch(function(err) {
        if (feedback) feedback.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;margin-right:4px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></svg> ' + tr('workspace.sample-failed','加载失败: ') + escapeMarkup(err.message || err);
      });
  }
  function button(action, label, glyph, detail) {
    const keys = {
      upload:['workspace.local-files','workspace.local-files-detail'], data:['workspace.catalog','workspace.catalog-detail'],
      connector:['workspace.connectors','workspace.connectors-detail'], projects:['workspace.projects','workspace.projects-detail'],
      spatial:['workspace.spatial-analysis','workspace.spatial-detail'], network:['workspace.network-analysis','workspace.network-detail'],
      statistics:['workspace.spatial-statistics','workspace.statistics-detail'], raster:['workspace.raster-processing','workspace.raster-detail'],
      history:['workspace.processing-history','workspace.history-detail']
    }[action] || [];
    return '<button class="workspace-entry" data-workspace-action="'+action+'">'+icon(glyph)+'<span><span'+(keys[0]?' data-i18n="'+keys[0]+'"':'')+'>'+label+'</span>'+(detail?'<small'+(keys[1]?' data-i18n="'+keys[1]+'"':'')+'>'+detail+'</small>':'')+'</span>'+icon('chevron')+'</button>';
  }
  function init() {
    body = document.querySelector('.app-body');
    chat = document.querySelector('.chat-panel');
    layerPanel = document.getElementById('mapLayerPanel');
    if (!body || !chat || !layerPanel) return;
    document.body.classList.add('workbench');
    document.documentElement.classList.add('gis-workspace');
    GIS.workspace = {toggleLayers:toggleLayers, toggleAI:toggleAI, closeDock:closeDock,
      panelBounds:panelBounds, clampPanel:clampPanel, centerPanel:centerPanel,
      preparePanel:preparePanel, expandPanel:expandPanel, toolFeedback:toolFeedback, toolPending:toolPending,
      promptModal:promptModal, confirmModal:confirmModal,
      openSaveProject:openSaveProject, openLoadProject:openLoadProject,
      renderRecentProjects:renderRecentProjects};
    const app = document.getElementById('app');
    const top = document.createElement('header');
    top.className = 'workspace-topbar';
    top.innerHTML = '<a class="workspace-brand" href="#" aria-label="GIS WorkTable 工作台" data-i18n-aria-label="header.workbench">'+icon('map')+'<span>GIS<span class="workspace-brand-light"> WorkTable</span></span></a>' +
      '<div class="workspace-top-project" id="workspaceTopProjectCapsule" title="点击重命名当前工程" data-i18n-title="project.rename-title">' +
        '<span class="workspace-project-pill-icon">' + icon('folder') + '</span>' +
        '<span class="workspace-project-pill-name" id="workspaceCurrentProjectName">' + tr('project.not-named', '未命名工程') + '</span>' +
      '</div>' +
      '<div class="workspace-top-actions"><button class="workspace-top-btn" data-workspace-action="new-project" title="新建工程（重置图层与会话）" data-i18n-title="workspace.new-title" aria-label="新建工程" data-i18n-aria-label="workspace.new-project">' + icon('upload') + '<span data-i18n="workspace.new">新建</span></button><button class="workspace-top-btn" data-workspace-action="save-project" title="保存工程" data-i18n-title="project.save-title" aria-label="保存工程" data-i18n-aria-label="project.save-title">' + icon('history') + '<span data-i18n="workspace.save">保存</span></button><button class="workspace-top-btn" data-workspace-action="settings" title="系统设置" data-i18n-title="workspace.settings" aria-label="系统设置" data-i18n-aria-label="workspace.settings">'+icon('settings')+'</button></div>';
    const originalLogo = chat.querySelector('.chat-header > .ui-logo');
    if (originalLogo) {
      const logo = originalLogo.cloneNode(true);
      logo.removeAttribute('style');
      logo.setAttribute('aria-hidden', 'true');
      top.querySelector('.workspace-brand').replaceChildren(logo);
    }
    const menu = document.getElementById('mapMenuBar');
    top.insertBefore(menu, top.querySelector('.workspace-top-project'));
    app.insertBefore(top, body);
    if (GIS.i18n) GIS.i18n.translate(top);
    top.querySelector('.workspace-brand').addEventListener('click', function(e) { e.preventDefault(); setTab('home'); });

    const capsule = top.querySelector('#workspaceTopProjectCapsule');
    if (capsule) {
      capsule.addEventListener('click', function() {
        const nameEl = document.getElementById('workspaceCurrentProjectName');
        const oldName = nameEl ? nameEl.textContent : '未命名工程';
        promptModal(tr('project.rename-heading', '重命名当前工程'), tr('project.rename-desc', '修改工程显示名称，并同步至最近记录。'), oldName, function(newName) {
          if (newName && newName.trim()) {
            const curId = GIS.project && GIS.project.getCurrentProjectId && GIS.project.getCurrentProjectId();
            if (curId && GIS.api && GIS.api.renameProject) {
              GIS.api.renameProject(curId, newName.trim()).then(function(result) {
                if (nameEl) nameEl.textContent = result && result.name || newName.trim();
                renderRecentProjects();
                if (result && result.warning && GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage(escapeMarkup(result.warning), 'system', { pill: true });
              }).catch(function(err) {
                if (nameEl) nameEl.textContent = oldName;
                if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('重命名失败: ' + escapeMarkup(err.message || err), 'system');
              });
            } else if (nameEl) {
              nameEl.textContent = newName.trim();
            }
          }
        });
      });
    }

    const rail = document.createElement('nav');
    rail.className = 'workspace-rail';
    rail.setAttribute('aria-label', tr('workspace.rail','工作区面板'));
    rail.innerHTML = ['home','browser','layers','tools'].map(function(name,i) {
      const key = ['workspace.home','workspace.data','workspace.layers','workspace.tools'][i];
      return '<button data-dock-tab="'+name+'" data-i18n-title="'+key+'" title="'+['首页','数据','图层管理','处理工具'][i]+'">'+icon(['home','folder','layers','tool'][i])+'<span data-i18n="'+key+'">'+['首页','数据','图层','处理'][i]+'</span></button>';
    }).join('')+'<button data-workspace-action="ai" aria-pressed="false" aria-expanded="false" data-i18n-title="workspace.open-ai" title="展开 AI 助手">'+icon('ai')+'<span data-i18n="workspace.ai">AI 助手</span></button><div class="workspace-rail-spacer"></div>';
    if (GIS.i18n) GIS.i18n.translate(rail);
    dock = document.createElement('aside');
    dock.className = 'workspace-dock';
    dock.innerHTML = '<div class="workspace-dock-header"><strong id="workspaceDockTitle">首页</strong><button id="workspaceDockClose" class="workspace-icon-btn" title="收起首页面板">'+icon('close')+'</button></div>' +
      '<section data-dock-pane="home" class="workspace-home">' +
        '<div class="workspace-first-task">' +
          '<strong data-i18n="workspace.public-data">公开数据获取</strong>' +
          '<p data-i18n="workspace.public-data-copy">粘贴 ArcGIS REST 地址，预览或下载图层。</p>' +
          '<div class="workspace-first-task-actions">' +
            '<button type="button" data-workspace-action="arcgis-own" data-i18n="workspace.enter-url">输入地址</button>' +
            '<button type="button" data-workspace-action="arcgis-sample" data-i18n="workspace.try-sample">试用样例</button>' +
          '</div>' +
          '<small class="workspace-first-task-sample-note" data-i18n="workspace.old-sample-note">样例人口数据较旧，仅用于演示。</small>' +
        '</div>' +
        '<div class="workspace-recent-header" style="margin-top:4px;">' +
          '<p class="workspace-section-label" style="margin:0;" data-i18n="workspace.recent-projects">最近工程</p>' +
          '<div style="display:flex;gap:6px;">' +
            '<button type="button" class="workspace-save-cur-btn" data-workspace-action="new-project" style="background:transparent;border:1px solid var(--outline-variant);color:var(--on-surface);">新建</button>' +
            '<button type="button" class="workspace-save-cur-btn" data-workspace-action="save-project" data-i18n="workspace.save-current">保存当前</button>' +
          '</div>' +
        '</div>' +
        '<div id="workspaceRecentProjectsList" class="workspace-recent-list"></div>' +
        '<p class="workspace-section-label" data-i18n="workspace.quick-start">快速体验</p>' +
        '<div class="workspace-sample-cards">' +
          '<div class="workspace-sample-card"><strong data-i18n="workspace.sample-polygons">多边形地块</strong><p data-i18n="workspace.sample-polygons-copy">加载地块示例，可用于查看图层样式和空间分析。</p><button type="button" class="workspace-sample-btn" data-action="load-sample" data-sample="buffer" data-i18n="workspace.load-sample">加载样例</button></div>' +
          '<div class="workspace-sample-card"><strong data-i18n="workspace.sample-points">POI 点</strong><p data-i18n="workspace.sample-points-copy">加载点位示例，查看点图层和属性。</p><button type="button" class="workspace-sample-btn" data-action="load-sample" data-sample="points" data-i18n="workspace.load-sample">加载样例</button></div>' +
          '<div class="workspace-sample-card"><strong data-i18n="workspace.sample-roads">道路路网</strong><p data-i18n="workspace.sample-roads-copy">加载道路示例，查看线图层样式。</p><button type="button" class="workspace-sample-btn" data-action="load-sample" data-sample="network" data-i18n="workspace.load-sample">加载样例</button></div>' +
        '</div>' +
        '<div id="workspaceSampleStatus" class="workspace-sample-status" role="status" aria-live="polite"></div>' +
      '</section>' +
      '<section data-dock-pane="browser" class="workspace-browser" hidden><p class="workspace-pane-intro" data-i18n="workspace.data-intro">从数据获取开始，在地图上检查分析结果。</p><button class="workspace-discovery" data-workspace-action="world"><span class="workspace-discovery-heading">'+icon('globe')+'<strong data-i18n="workspace.global-data">全球数据</strong></span><span class="workspace-discovery-detail" data-i18n="workspace.global-data-copy">按国家和地区探索数据源，选择服务接入工作台。</span><span class="workspace-discovery-link"><span data-i18n="workspace.open-data-map">打开数据地图</span> '+icon('chevron')+'</span></button><div class="workspace-search"><input id="workspaceDataSearch" type="search" placeholder="按关键词检索数据" aria-label="搜索空间数据源" data-i18n-placeholder="workspace.search-keywords" data-i18n-aria-label="workspace.search-data"><button data-workspace-action="search" title="检索数据" data-i18n-title="workspace.search">'+icon('chevron')+'</button></div><p class="workspace-section-label" data-i18n="workspace.connect-data">接入工作台</p>'+button('upload','导入本地文件','upload','GeoJSON、Shapefile、栅格等')+button('data','目录检索','layers','按主题、地区和协议筛选')+button('connector','数据源连接器','settings','配置账号或添加在线地址')+'<p class="workspace-section-label" data-i18n="workspace.continue">继续工作</p>'+button('projects','会话与项目','history','回到已有工作')+'</section><section data-dock-pane="layers" class="workspace-layers" hidden></section><section data-dock-pane="tools" class="workspace-tools" hidden><p class="workspace-pane-intro" data-i18n="workspace.tools-intro">选取工具，设置参数后执行。计算结果会回到地图和图层列表。</p>'+button('spatial','空间分析','layers','缓冲、裁剪、叠置')+button('network','网络分析','tool','路径、服务区、最近设施')+button('statistics','空间统计','tool','统计与空间分布')+button('raster','栅格处理','map','地形、波段与栅格计算')+button('history','处理历史','history','查看执行记录并重跑')+'</section>';
    if (GIS.i18n) GIS.i18n.translate(dock);
    layerPanel.classList.remove('collapsed');
    dock.querySelector('[data-dock-pane="layers"]').appendChild(layerPanel);
    body.insertBefore(dock, body.firstChild);
    body.insertBefore(rail, dock);
    body.insertBefore(chat, dock.nextSibling);
    document.addEventListener('gis:languagechange', function() {
      if (GIS.i18n) {
        GIS.i18n.translate(dock);
        GIS.i18n.translate(rail);
        rail.setAttribute('aria-label', tr('workspace.rail','工作区面板'));
        document.getElementById('workspaceDockTitle').textContent = tr(tabLabelKey(activeTab), tabLabelChinese(activeTab));
        document.getElementById('workspaceDockClose').title = tr('workspace.close-panel','关闭面板') + ' · ' + tr(tabLabelKey(activeTab), tabLabelChinese(activeTab));
        const chatInput = document.getElementById('chatInput');
        if (chatInput) chatInput.placeholder = tr('input.placeholder','描述你的空间任务，或输入 / 选择工具…');
        if (closeAI) closeAI.title = tr('workspace.close-ai','收起 AI 助手');
      }
    });
    initDivider();
    const mapTools = document.getElementById('mapZoomControls');
    if (mapTools) {
      mapTools.setAttribute('role', 'toolbar');
      mapTools.setAttribute('aria-label', '地图操作');
    }
    const oldLogo = chat.querySelector('.chat-header > .ui-logo');
    if (oldLogo) {
      const heading = document.createElement('div');
      heading.className = 'workspace-ai-heading';
      heading.innerHTML = icon('ai')+'<span data-i18n="workspace.ai">AI 助手</span>';
      oldLogo.replaceWith(heading);
    }
    const closeAI = document.createElement('button');
    closeAI.className = 'workspace-icon-btn';
    closeAI.title = tr('workspace.close-ai','收起 AI 助手');
    closeAI.innerHTML = icon('close');
    closeAI.onclick = function() {
      toggleAI(false);
      closeDock();
    };
    chat.querySelector('.chat-header > div:last-child').appendChild(closeAI);
    const input = document.getElementById('chatInput');
    input.placeholder = tr('input.placeholder','描述你的空间任务，或输入 / 选择工具…');
    const connector = document.getElementById('connectorPanel');
    if (connector) document.body.appendChild(connector);
    const status = document.createElement('div');
    status.className = 'workspace-statusbar';
    status.innerHTML = '<span class="workspace-status-dot"></span><span data-i18n="workspace.workbench">本地工作台</span><span class="workspace-status-hint" id="workspaceVersionHint" title="版本信息" data-i18n-title="workspace.version-info">Git …</span>';
    if (GIS.i18n) GIS.i18n.translate(status);
    const coords = document.getElementById('mapCoords');
    if (coords) {
      coords.textContent = GIS.map && GIS.map.formatWgs84Coordinates ? GIS.map.formatWgs84Coordinates(NaN, NaN) : 'WGS-84 · 经度 -- · 纬度 --';
      status.insertBefore(coords, status.querySelector('.workspace-status-hint'));
    }
    app.appendChild(status);
    // 异步拉取后端动态 Git 提交号与脏状态
    if (window.GIS.api && typeof window.GIS.api.getVersion === 'function') {
      window.GIS.api.getVersion().then(function(ver) {
        const hintEl = document.getElementById('workspaceVersionHint');
        if (hintEl && ver && ver.commit) {
          const commitText = ver.commit + (ver.dirty ? '*' : '');
          hintEl.textContent = 'Git ' + commitText;
          hintEl.title = 'Git Commit: ' + commitText + (ver.start_time ? '\n启动时间: ' + ver.start_time : '');
          if (ver.commit !== 'unknown') {
            hintEl.style.cursor = 'pointer';
            hintEl.onclick = function() {
              window.open('https://github.com/Wukeeeeee/GIS-WORKTABLE/commit/' + ver.commit, '_blank');
            };
          }
        }
      }).catch(function() {});
    }
    document.getElementById('workspaceDockClose').onclick = closeDock;
    document.getElementById('workspaceDataSearch').addEventListener('keydown', function(e) { if (e.key === 'Enter') run('search'); });
    document.addEventListener('click', function(e) {
      const sampleBtn = e.target.closest('[data-action="load-sample"]');
      if (sampleBtn) { loadSample(sampleBtn.dataset.sample); return; }
      const tab = e.target.closest('[data-dock-tab]');
      if (tab) { setTab(tab.dataset.dockTab); return; }
      const action = e.target.closest('[data-workspace-action]');
      if (action) run(action.dataset.workspaceAction);
    });

    let initialTab = 'home';
    let isClosed = false;
    try {
      const savedTab = localStorage.getItem('gis_workspace_active_tab');
      if (savedTab && ['home', 'browser', 'layers', 'tools'].indexOf(savedTab) >= 0) {
        initialTab = savedTab;
      }
      isClosed = localStorage.getItem('gis_workspace_dock_closed') === 'true';
    } catch (_) {}
    setTab(initialTab);
    if (isClosed) closeDock();

    toggleAI(false);
    window.addEventListener('resize', function() { setDockWidth(dockWidth, false); });
  }
  function run(action) {
    if (action === 'ai') {
      if (!chat.hidden) {
        toggleAI(false);
        closeDock();
      } else {
        closeDock();
        toggleAI(true);
      }
    }
    else if (action === 'save-project') {
      openSaveProject();
    }
    else if (action === 'new-project') {
      confirmModal('新建工程确认', '新建工程将清空当前所有图层与会话记录。请确认重要成果已保存，是否继续？', function() {
        var clearPromise = GIS.chat && typeof GIS.chat.clearSession === 'function'
          ? GIS.chat.clearSession()
          : Promise.resolve(false);
        Promise.resolve(clearPromise).then(function(cleared) {
          if (cleared === false) return;
          if (GIS.map && GIS.map.resetView) { try { GIS.map.resetView(); } catch(_) {} }
          if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('已开启新工程', 'system');
        }).catch(function(err) {
        if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('新建工程失败: ' + escapeMarkup(err.message || err), 'system');
        });
      }, true);
    }
    else if (action === 'data') GIS.geosource.show();
    else if (action === 'world') GIS.geosource.openWorldMap();
    else if (action === 'arcgis-own' || action === 'arcgis-sample') {
      var connector = GIS.connector;
      if (!connector || typeof connector.openArcgis !== 'function') return;
      connector.openArcgis(action === 'arcgis-sample' ? {
        url: 'https://sampleserver6.arcgisonline.com/arcgis/rest/services/Census/MapServer',
        layer_id: '2', mode: 'full', where: "STATE_NAME = 'Alabama'", bbox: ''
      } : { url: '', layer_id: '', mode: 'preview', where: '1=1', bbox: '', selectUrl: true });
    }
    else if (action === 'upload') document.getElementById('uploadTrigger').click();
    else if (action === 'settings' || action === 'connector') {
      document.getElementById(action === 'connector' ? 'connectorBtn' : 'settingsBtn').click();
    } else if (action === 'search') {
      document.getElementById('geosourceKeyword').value = document.getElementById('workspaceDataSearch').value;
      // This entry point starts its own search; avoid show()'s empty-state auto-search.
      GIS.geosource.show(true);
      GIS.geosource.doSearch(1);
    } else if (action === 'projects') { toggleAI(true); document.getElementById('historyBtn').click(); }
    else if (action === 'spatial') GIS.spatial.toggle();
    else if (action === 'network') GIS.network.toggle();
    else if (action === 'statistics') GIS.spatialStats.toggle();
    else if (action === 'raster') GIS.rasterTools.openWith('slope');
    else if (action === 'history') document.getElementById('toggleHistoryPanel').click();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
