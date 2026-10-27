/**
 * GIS AI WorkTable — 设置模块（Provider 列表化版）
 * 设置弹窗、Provider 动态列表编辑器、模型选择器、主题/字号
 *
 * 唯一数据源：GIS.api.getProviders()（localStorage: gis_llm_providers）
 * 一个 Provider = 一份 LLMConfig，选中的 Provider 对象随每次请求作为 llm_config 发送。
 */
window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;
  var _providerStatusGeneration = Object.create(null);

  // 复用已有 CSS 的模型选择器 check 图标
  const CHECK_SVG =
    "<span class=\"ui-icon model-picker-check\" aria-hidden=\"true\" style=\";width:16px;height:16px;--ui-icon-image:url('/assets/ui-icons/icon-2317bb688770.png')\"></span>";

  function init() {
    // 各块互相隔离：任何一块报错都不影响顶栏模型名同步等其余功能
    try { resetProviderStatuses(); } catch (e) {}
    try { bindSettingsModal(); } catch (e) { console.warn('[GIS settings] bindSettingsModal', e); }
    try { bindAmap(); } catch (e) { console.warn('[GIS settings] bindAmap', e); }
    try { bindProxy(); } catch (e) { console.warn('[GIS settings] bindProxy', e); }
    try { bindGeoCredentials(); } catch (e) { console.warn('[GIS settings] geo credentials', e); }
    try { initProviderPanel(); } catch (e) { console.warn('[GIS settings] provider panel', e); }
    try { initTheme(); } catch (e) {}
    try { initFontSize(); } catch (e) {}
    try { initModelSelector(); } catch (e) { console.warn('[GIS settings] model selector', e); }
    try { bindButtonFeedback(); } catch (e) {}
    try {
      if (window.GIS.api && window.GIS.api.syncUserSettingsFromBackend) {
        window.GIS.api.syncUserSettingsFromBackend().then(function(res) {
          if (res && res.updated) {
            try { populateAmapInput(); } catch(_) {}
            try { renderProviderList(); } catch(_) {}
            try { syncModelUI(); } catch(_) {}
            try { updateModelStatusDot(); } catch(_) {}
          }
        });
      }
    } catch (e) { console.warn('[GIS settings] syncUserSettingsFromBackend', e); }
  }

  // ============================================================
  // 设置弹窗
  // ============================================================

  function bindSettingsModal() {
    var modal = document.getElementById('settingsModal');
    var settingsBtn = document.getElementById('settingsBtn');
    var closeBtn = document.getElementById('modalCloseBtn');
    if (!modal || !settingsBtn) return;

    settingsBtn.addEventListener('click', function() { openModal(); });
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', function(e) {
      if (e.target === modal) closeModal();
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && modal.style.display === 'flex') closeModal();
    });

    // 侧边栏切换
    var sidenavItems = document.querySelectorAll('.modal-sidenav-item');
    var panels = _panels();
    sidenavItems.forEach(function(item) {
      item.addEventListener('click', function() {
        var panel = this.dataset.panel;
        sidenavItems.forEach(function(s) { s.classList.remove('active'); });
        this.classList.add('active');
        Object.keys(panels).forEach(function(k) {
          if (panels[k]) panels[k].classList.toggle('active', k === panel);
        });
      });
    });
  }

  function _panels() {
    return {
      appearance: document.getElementById('panelAppearance'),
      'ai-api': document.getElementById('panelAiApi'),
      'geo-api': document.getElementById('panelGeoApi'),
      network: document.getElementById('panelNetwork'),
      history: document.getElementById('panelHistory'),
      logs: document.getElementById('panelLogs'),
      about: document.getElementById('panelAbout'),
    };
  }

  function openModal(initialPanel) {
    var modal = document.getElementById('settingsModal');
    if (!modal) return;
    var targetPanel = initialPanel || 'appearance';
    var sidenavItems = document.querySelectorAll('.modal-sidenav-item');
    var panels = _panels();
    sidenavItems.forEach(function(s) { s.classList.remove('active'); });
    var targetNav = document.querySelector('.modal-sidenav-item[data-panel="' + targetPanel + '"]');
    if (targetNav) {
      targetNav.classList.add('active');
    } else {
      var firstNav = document.querySelector('.modal-sidenav-item[data-panel="appearance"]');
      if (firstNav) firstNav.classList.add('active');
      targetPanel = 'appearance';
    }
    Object.keys(panels).forEach(function(k) {
      if (panels[k]) panels[k].classList.toggle('active', k === targetPanel);
    });

    // 打开设置前把当前 Provider 列表渲染进面板
    renderProviderList();
    populateAmapInput();
    populateGeoCredentials();
    refreshStorageStats();
    modal.style.display = 'flex';
    updateModelStatusDot();
  }

  function refreshStorageStats() {
    fetch('/api/storage/stats')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var pEl = document.getElementById('dbPathDisplay');
        var rEl = document.getElementById('dbRunsCount');
        var aEl = document.getElementById('dbArtsCount');
        var bEl = document.getElementById('dbStatusBadge');
        if (pEl) pEl.textContent = data.db_path || '未知';
        if (rEl) rEl.textContent = data.runs_count || 0;
        if (aEl) aEl.textContent = data.artifacts_count || 0;
        if (bEl) {
          if (data.exists) {
            bEl.textContent = '正常连接';
            bEl.style.background = '#e6f4ea';
            bEl.style.color = '#137333';
          } else {
            bEl.textContent = '库文件未就绪';
            bEl.style.background = '#fce8e6';
            bEl.style.color = '#c5221f';
          }
        }
      })
      .catch(function() {});
  }

  function closeModal() {
    var modal = document.getElementById('settingsModal');
    if (modal) modal.style.display = 'none';
  }

  // ============================================================
  // Provider 动态列表编辑器（AI 面板）
  // ============================================================

  function initProviderPanel() {
    var addBtn = document.getElementById('addProviderBtn');
    if (addBtn) {
      addBtn.addEventListener('click', function() {
        var item = GIS.api.addProvider({ name: '自定义（OpenAI 兼容）' });
        if (item) renderProviderList();
      });
    }
    renderProviderList();
  }

  function providerStatusBadge(p) {
    var status = GIS.api.getModelStatus(p.id);
    if (p.api_key) {
      if (status === 'online') return { text: '在线', cls: 'model-config-badge configured' };
      if (status === 'offline') return { text: '连接失败', cls: 'model-config-badge' };
      if (status === 'checking') return { text: '检测中', cls: 'model-config-badge' };
      return { text: '已配置', cls: 'model-config-badge configured' };
    }
    return { text: '未配置', cls: 'model-config-badge' };
  }

  function refreshProviderBadge(id) {
    var p = GIS.api.getProvider(id);
    if (!p) return;
    document.querySelectorAll('.model-config-card').forEach(function(card) {
      if (card.dataset.providerId !== id) return;
      var badge = card.querySelector('.model-config-header .model-config-badge');
      if (!badge) return;
      var status = providerStatusBadge(p);
      badge.textContent = status.text;
      badge.className = status.cls;
    });
  }

  function invalidateProviderStatus(id) {
    _providerStatusGeneration[id] = (_providerStatusGeneration[id] || 0) + 1;
    GIS.api.setModelStatus(id, 'untested');
    refreshProviderBadge(id);
    if (GIS.api.getSelectedModel() === id) updateModelStatusDot();
  }

  function beginProviderStatusCheck(id) {
    var generation = (_providerStatusGeneration[id] || 0) + 1;
    _providerStatusGeneration[id] = generation;
    GIS.api.setModelStatus(id, 'checking');
    refreshProviderBadge(id);
    if (GIS.api.getSelectedModel() === id) updateModelStatusDot();
    return generation;
  }

  function finishProviderStatusCheck(id, generation, status) {
    if (_providerStatusGeneration[id] !== generation) return false;
    GIS.api.setModelStatus(id, status);
    refreshProviderBadge(id);
    if (GIS.api.getSelectedModel() === id) updateModelStatusDot();
    return true;
  }

  function renderProviderList() {
    var host = document.getElementById('providerList');
    if (!host) return;
    host.innerHTML = '';
    var providers = GIS.api.getProviders();
    if (!providers || !providers.length) return;
    GIS.api.getSelectedModel();
    syncProviderStorageWarning(host);

    var container = host;

    providers.forEach(function(p, idx) {
      var badge = providerStatusBadge(p);
      var card = document.createElement('div');
      card.className = 'model-config-card';
      card.dataset.providerId = p.id;
      card.style.borderLeft = '3px solid ' + (idx % 2 ? 'var(--ui-gray-300,#d0d5dd)' : 'var(--accent,#6366f1)');

      var header = document.createElement('div');
      header.className = 'model-config-header';
      var nameInputId = 'gis-provider-' + idx + '-name';
      var curTag = (p.id === GIS.api.getSelectedModel())
        ? '<span class="model-config-free" style="color:var(--accent,#6366f1);">● 当前使用</span>' : '';
      header.innerHTML =
        '<input type="text" id="' + nameInputId + '" class="modal-input prov-name" value="' + GIS.utils.escapeHtml(p.name || '') + '" style="flex:1;padding:6px 8px;" aria-label="Provider 显示名称" title="显示名称(顶栏/列表/任务卡都用它)" />' +
        curTag +
        '<span class="' + badge.cls + '">' + badge.text + '</span>';
      // name 输入框失去焦点即改名（回车也触发）
      var nameInput = header.querySelector('.prov-name');
      nameInput.addEventListener('change', function() {
        updateField(p.id, 'name', this.value);
      });
      card.appendChild(header);

      // base_url / model / api_key
      var fieldBlock = document.createElement('div');
      fieldBlock.style.cssText = 'margin-top:8px;display:grid;gap:6px;';
      fieldBlock.innerHTML =
        _fieldRow('base_url', '接口地址', p.base_url, 'https://.../v1', 'text', 'gis-provider-' + idx + '-base-url') +
        _fieldRow('model', '模型名', p.model, 'model-name', 'text', 'gis-provider-' + idx + '-model') +
        _fieldRow('api_key', 'API Key', p.api_key, 'sk-...', 'password', 'gis-provider-' + idx + '-api-key');
      card.appendChild(fieldBlock);

      // 开关：glm 提示词 / 技能路由 / reasoning
      var toggles = document.createElement('div');
      toggles.style.cssText = 'margin-top:8px;display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--ui-gray-600,#555);';
      toggles.innerHTML =
        _toggleHtml('glm_prompt', p.glm_prompt, 'GLM 提示词') +
        _toggleHtml('router', p.router, '技能路由') +
        _toggleHtml('reasoning', p.reasoning, '推理 reasoning') +
        '<span style="align-self:center;display:inline-flex;align-items:center;gap:4px;">' +
        '温度 <input type="number" step="0.1" min="0" max="2" class="prov-num" data-field="temperature" value="' +
        (p.temperature === null || p.temperature === undefined ? '' : p.temperature) + '" style="width:52px;"/>' +
        '· max_tokens <input type="number" step="1" min="1" class="prov-num" data-field="max_tokens" value="' +
        (p.max_tokens === null || p.max_tokens === undefined ? '' : p.max_tokens) + '" style="width:64px;"/>' +
        '</span>';
      card.appendChild(toggles);

      // 测速 / 复制 / 删除
      var actions = document.createElement('div');
      actions.className = 'model-config-actions';
      var single = providers.length <= 1;
      actions.innerHTML =
        '<span class="modal-test-result prov-test-msg" style="margin-right:auto;width:auto;"></span>' +
        '<button class="modal-btn modal-btn-test prov-test" type="button">测速</button>' +
        '<button class="modal-btn modal-btn-test prov-dup" type="button" title="复制此 Provider">复制</button>' +
        (single ? '' : '<button class="modal-btn prov-del" type="button" style="color:#e53935;">删除</button>');
      actions.style.cssText = 'margin-top:8px;align-items:center;gap:6px;';
      card.appendChild(actions);

      // ---- 绑定 ----
      ['base_url', 'model', 'api_key'].forEach(function(f) {
        var el = fieldBlock.querySelector('[data-field="' + f + '"]');
        if (!el) return;
        el.addEventListener('input', function() {
          var v = f === 'api_key' ? this.value.trim() : this.value;
          updateField(p.id, f, v);
        });
      });
      // api_key 显隐切换
      fieldBlock.querySelectorAll('.modal-toggle-vis').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var wrap = this.closest('.modal-input-wrapper');
          var inp = wrap ? wrap.querySelector('input') : null;
          if (!inp) return;
          inp.type = inp.type === 'password' ? 'text' : 'password';
        });
      });
      toggles.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {
        cb.addEventListener('change', function() {
          updateField(p.id, cb.dataset.field, cb.checked);
        });
      });
      toggles.querySelectorAll('.prov-num').forEach(function(n) {
        n.addEventListener('change', function() {
          var val = n.value === '' ? null : Number(n.value);
          updateField(p.id, n.dataset.field, val);
        });
      });
      var testBtn = actions.querySelector('.prov-test');
      if (testBtn) testBtn.addEventListener('click', function() { testProviderRow(p.id, this); });
      var dupBtn = actions.querySelector('.prov-dup');
      if (dupBtn) dupBtn.addEventListener('click', function() {
        GIS.api.duplicateProvider(p.id);
        renderProviderList();
        updateModelStatusDot();
      });
      var delBtn = actions.querySelector('.prov-del');
      if (delBtn) delBtn.addEventListener('click', function() {
        if (window.confirm('删除 Provider「' + (p.name || p.id) + '」？')) {
          GIS.api.removeProvider(p.id);
          renderProviderList();
          syncModelUI();
        }
      });

      container.appendChild(card);
    });
  }

  function _fieldRow(field, label, value, placeholder, type, inputId) {
    var show = field === 'api_key';
    return '<div style="display:flex;gap:6px;align-items:center;">' +
      '<label for="' + inputId + '" style="width:64px;font-size:11px;color:var(--ui-gray-500,#888);flex:none;">' + label + '</label>' +
      '<div class="modal-input-wrapper" style="flex:1;">' +
      '<input id="' + inputId + '" type="' + (show ? 'password' : type) + '" class="modal-input" data-field="' + field + '" value="' +
      GIS.utils.escapeHtml(value || '') + '" placeholder="' + placeholder + '" autocomplete="off" />' +
      (show ? "<button class=\"modal-toggle-vis\" type=\"button\" title=\"显示/隐藏密钥\"><span class=\"ui-icon prov-eye\" aria-hidden=\"true\" style=\";width:18px;height:18px;--ui-icon-image:url('/assets/ui-icons/icon-6a87bac01dca.png')\"></span></button>" : '') +
      '</div></div>';
  }

  function _toggleHtml(field, checked, label) {
    return '<label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer;">' +
      '<input type="checkbox" data-field="' + field + '" ' + (checked ? 'checked' : '') + ' />' +
      '<span>' + label + '</span></label>';
  }

  /** 局部更新某个 Provider 的单个字段并落盘（不重建 DOM，保住焦点） */
  function updateField(id, field, value) {
    var p = GIS.api.getProvider(id);
    if (!p) return;
    if (field === 'temperature' || field === 'max_tokens') {
      // 空 → null（可选字段不发给后端）
      p[field] = (value === '' || value === null || value === undefined) ? null : Number(value);
    } else if (field === 'reasoning' || field === 'router' || field === 'glm_prompt') {
      p[field] = !!value;
    } else {
      p[field] = value;
    }
    GIS.api.upsertProvider(p);
    syncProviderStorageWarning(document.getElementById('providerList'));
    if (field === 'name') {
      if (GIS.api.getSelectedModel() === id) syncModelUI();
      return;
    }
    invalidateProviderStatus(id);
  }

  function syncProviderStorageWarning(host) {
    if (!host || !GIS.api.areProviderSettingsPersistent) return;
    var warning = host.querySelector('.provider-storage-warning');
    if (GIS.api.areProviderSettingsPersistent()) {
      if (warning) warning.remove();
      return;
    }
    if (warning) return;
    warning = document.createElement('div');
    warning.className = 'modal-note provider-storage-warning';
    warning.setAttribute('role', 'alert');
    warning.setAttribute('data-i18n', 'settings.provider-storage-warning');
    warning.setAttribute('data-i18n-zh', '此浏览器暂时无法保存模型设置；当前配置和 API Key 会在刷新或关闭页面后丢失。启用网站本地存储后才能保留。');
    warning.textContent = GIS.i18n && GIS.i18n.t
      ? GIS.i18n.t('settings.provider-storage-warning', warning.getAttribute('data-i18n-zh'))
      : warning.getAttribute('data-i18n-zh');
    host.insertBefore(warning, host.firstChild);
  }

  async function testProviderRow(id, btn) {
    var p = GIS.api.getProvider(id);
    var card = btn.closest('.model-config-card');
    var msgEl = card ? card.querySelector('.prov-test-msg') : null;
    if (!p) return;
    if (!p.api_key) {
      if (msgEl) {
        msgEl.textContent = '请先填 API Key';
        msgEl.className = 'modal-test-result modal-test-error';
      }
      return;
    }
    if (btn.dataset.testing === 'true') return;
    btn.dataset.testing = 'true';
    btn.disabled = true;
    btn.textContent = '测速中...';
    var checkGeneration = beginProviderStatusCheck(id);
    if (msgEl) { msgEl.innerHTML = '正在连接...'; msgEl.className = 'modal-test-result'; }

    try {
      var res = await GIS.api.testProvider(p);
      var isCurrentCheck = finishProviderStatusCheck(p.id, checkGeneration, res.success ? 'online' : 'offline');
      if (msgEl && isCurrentCheck) {
        msgEl.textContent = res.message;
        msgEl.className = 'modal-test-result ' + (res.success ? 'modal-test-success' : 'modal-test-error');
      }
    } catch (e) {
      var isCurrentCheck = finishProviderStatusCheck(p.id, checkGeneration, 'offline');
      if (msgEl && isCurrentCheck) {
        msgEl.textContent = '连接失败: ' + (e.message || e);
        msgEl.className = 'modal-test-result modal-test-error';
      }
    } finally {
      btn.dataset.testing = 'false';
      btn.disabled = false;
      btn.textContent = '测速';
      // 刷新徽章（不重建整个列表，避免打断编辑）
      refreshProviderBadge(id);
      updateModelStatusDot();
    }
  }

  // ============================================================
  // 高德地图 Key（仍单独存，放 #panelGeoApi）
  // ============================================================

  // ============================================================
  // 数据下载服务账号凭据（Copernicus / USGS / GSCloud）
  // ============================================================

  var GEO_SERVICES = ['copernicus', 'usgs', 'gscloud', 'nasa', 'opentopo', 'asf', 'tianditu', 'resdc', 'geoss', 'pie'];
  // key 型服务（单字段 API Key）；其余为 account 型（用户名+密码）
  var GEO_KEY_SERVICES = ['opentopo', 'tianditu'];

  function populateGeoCredentials() {
    var all = GIS.api.getGeoCredentials();
    GEO_SERVICES.forEach(function(svc) {
      var cred = all[svc] || {};
      var userEl = document.querySelector('.geo-cred-user[data-cred="' + svc + '"]');
      var passEl = document.querySelector('.geo-cred-pass[data-cred="' + svc + '"]');
      var keyEl = document.querySelector('.geo-cred-key[data-cred="' + svc + '"]');
      if (userEl) userEl.value = cred.username || '';
      if (passEl) passEl.value = cred.password || '';
      if (keyEl) keyEl.value = cred.api_key || '';
      updateGeoCredStatus(svc, cred);
    });
  }

  function updateGeoCredStatus(svc, cred) {
    var el = document.querySelector('[data-cred-status="' + svc + '"]');
    if (!el) return;
    var c = cred || {};
    var has = (c.type === 'key' || GEO_KEY_SERVICES.indexOf(svc) >= 0) ? !!c.api_key : !!(c.username && c.password);
    el.textContent = has ? (GIS.i18n && GIS.i18n.isEnglish() ? 'Configured' : '已配置') : (GIS.i18n && GIS.i18n.isEnglish() ? 'Not configured' : '未配置');
    el.className = 'model-config-badge' + (has ? ' configured' : '');
  }

  function bindGeoCredentials() {
    // 保存
    document.querySelectorAll('.geo-cred-save').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var svc = btn.dataset.cred;
        var isKey = GEO_KEY_SERVICES.indexOf(svc) >= 0;
        var userEl = document.querySelector('.geo-cred-user[data-cred="' + svc + '"]');
        var passEl = document.querySelector('.geo-cred-pass[data-cred="' + svc + '"]');
        var keyEl = document.querySelector('.geo-cred-key[data-cred="' + svc + '"]');
        var cred;
        if (isKey) {
          cred = { type: 'key', api_key: (keyEl ? keyEl.value : '').trim() };
        } else {
          cred = { type: 'account', username: (userEl ? userEl.value : '').trim(), password: passEl ? passEl.value : '' };
        }
        var msg = document.querySelector('.geo-cred-msg[data-cred="' + svc + '"]');
        var hasCredential = isKey ? !!cred.api_key : !!(cred.username && cred.password);
        if (!isKey && (!!cred.username !== !!cred.password)) {
          if (msg) {
            msg.textContent = GIS.i18n && GIS.i18n.isEnglish() ? 'Enter both username and password, or clear both to remove the credential.' : '请同时填写用户名和密码，或清空两项后删除';
            msg.className = 'modal-test-result modal-test-error';
          }
          return;
        }

        if (hasCredential) {
          GIS.api.setGeoCredential(svc, cred);
        } else {
          var allCredentials = GIS.api.getGeoCredentials();
          delete allCredentials[svc];
          GIS.api.setGeoCredentials(allCredentials);
        }
        updateGeoCredStatus(svc, hasCredential ? cred : {});
        btn.disabled = true;
        if (msg) {
          msg.textContent = hasCredential
            ? (GIS.i18n && GIS.i18n.isEnglish() ? 'Saving…' : '正在保存…')
            : (GIS.i18n && GIS.i18n.isEnglish() ? 'Removing…' : '正在删除…');
          msg.className = 'modal-test-result';
        }

        var endpoint = GIS.api.BASE_URL + '/api/geo-credentials' + (hasCredential ? '' : '/' + encodeURIComponent(svc));
        var request = hasCredential ? fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ service: svc, username: isKey ? 'api_key' : cred.username, password: isKey ? cred.api_key : cred.password }),
          }) : fetch(endpoint, { method: 'DELETE' });
        request.then(function(response) {
          return response.json().then(function(data) {
            if (!response.ok || !data || data.status !== 'ok') {
              throw new Error((data && data.message) || ('HTTP ' + response.status));
            }
            return data;
          });
        }).then(function() {
          if (msg) {
            msg.textContent = hasCredential
              ? (GIS.i18n && GIS.i18n.isEnglish() ? 'Saved (encrypted on the server)' : '已保存（后端加密存储）')
              : (GIS.i18n && GIS.i18n.isEnglish() ? 'Removed from local and server storage' : '已从本地与后端清除');
            msg.className = 'modal-test-result modal-test-success';
          }
        }).catch(function() {
          if (msg) {
            msg.textContent = hasCredential
              ? (GIS.i18n && GIS.i18n.isEnglish() ? 'Saved locally, but server-side encrypted storage failed.' : '本地已保存，后端加密保存失败')
              : (GIS.i18n && GIS.i18n.isEnglish() ? 'Removed locally, but server-side deletion failed. Please retry.' : '本地已清除，后端删除失败，请重试');
            msg.className = 'modal-test-result modal-test-error';
          }
        }).finally(function() {
          btn.disabled = false;
          setTimeout(function() {
            if (msg && !btn.disabled) { msg.textContent = ''; msg.className = 'modal-test-result'; }
          }, 3000);
        });
      });
    });
    // 密码显隐切换
    document.querySelectorAll('.geo-cred-eye').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var wrap = this.closest('.modal-input-wrapper');
        var inp = wrap ? wrap.querySelector('input') : null;
        if (inp) inp.type = inp.type === 'password' ? 'text' : 'password';
      });
    });
    populateGeoCredentials();
  }

  function bindAmap() {
    function amapText(key, fallback) {
      return GIS.i18n && GIS.i18n.t ? GIS.i18n.t(key, fallback) : fallback;
    }
    var input = document.getElementById('amapApiKeyInput');
    var saveBtn = document.getElementById('saveAmapKeyBtn');
    if (saveBtn) {
      saveBtn.addEventListener('click', function() {
        var key = (document.getElementById('amapApiKeyInput') || {}).value || '';
        var clearingKey = !key.trim();
        saveBtn.disabled = true;
        var msg = document.getElementById('amapTestResult');
        if (msg) {
          msg.textContent = clearingKey
            ? amapText('settings.amap-clearing', '正在清除密钥…')
            : amapText('settings.amap-saving', '正在加密保存…');
          msg.className = 'modal-test-result';
        }
        GIS.api.setAmapKey(key.trim()).then(function() {
          if (msg) {
            msg.textContent = clearingKey
              ? amapText('settings.amap-removed', '已从浏览器与本机凭据库删除')
              : amapText('settings.amap-saved', '已保存到浏览器与本机加密凭据库');
            msg.className = 'modal-test-result modal-test-success';
          }
          updateAmapStatus();
        }).catch(function(error) {
          if (msg) {
            var failureMessage = clearingKey
              ? amapText('settings.amap-remove-failed', '浏览器已清除，但后端凭据删除失败')
              : amapText('settings.amap-sync-failed', '当前浏览器已保存，但后端加密同步失败');
            var detail = error && error.message && error.message !== 'Failed to fetch'
              ? String(error.message).trim()
              : '';
            msg.textContent = detail ? failureMessage + '：' + detail : failureMessage;
            msg.className = 'modal-test-result modal-test-error';
          }
          updateAmapStatus();
        }).finally(function() {
          saveBtn.disabled = false;
          setTimeout(function() { if (msg) { msg.textContent = ''; msg.className = 'modal-test-result'; } }, 3000);
        });
      });
    }
    var toggleBtn = document.getElementById('toggleAmapKeyVis');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', function() {
        var inp = document.getElementById('amapApiKeyInput');
        if (!inp) return;
        var show = inp.type === 'password';
        inp.type = show ? 'text' : 'password';
        var eye = document.getElementById('amapEyeIcon');
        if (eye) {
          eye.innerHTML = show
            ? '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/>'
            : '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
        }
      });
    }
    updateAmapStatus();
  }

  function populateAmapInput() {
    var input = document.getElementById('amapApiKeyInput');
    if (input) input.value = GIS.api.getAmapKey() || '';
    updateAmapStatus();
  }

  function updateAmapStatus() {
    var el = document.getElementById('amapKeyStatus');
    if (!el) return;
    var has = !!GIS.api.getAmapKey();
    el.textContent = has ? (GIS.i18n && GIS.i18n.isEnglish() ? 'Configured' : '已配置') : (GIS.i18n && GIS.i18n.isEnglish() ? 'Not configured' : '未配置');
    el.className = 'model-config-badge' + (has ? ' configured' : '');
  }

  document.addEventListener('gis:languagechange', function() {
    var credentials = GIS.api && GIS.api.getGeoCredentials ? GIS.api.getGeoCredentials() : {};
    document.querySelectorAll('[data-cred-status]').forEach(function(el) {
      var service = el.getAttribute('data-cred-status');
      updateGeoCredStatus(service, credentials[service] || {});
    });
    updateAmapStatus();
  });

  // ============================================================
  // 网络代理配置
  // ============================================================
  function bindProxy() {
    var input = document.getElementById('proxyUrlInput');
    var saveBtn = document.getElementById('saveProxyBtn');
    var statusEl = document.getElementById('proxyStatus');
    var msgEl = document.getElementById('proxyMsg');
    if (!input || !saveBtn) return;

    // 加载已保存的代理配置
    var saved = localStorage.getItem('gis_proxy_url') || '';
    input.value = saved;
    if (statusEl) statusEl.textContent = saved ? '自定义' : '系统代理';
    // 页面加载时同步到后端
    fetch('/api/proxy-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proxy: saved })
    }).catch(function() {});

    saveBtn.addEventListener('click', function() {
      var proxy = input.value.trim();
      localStorage.setItem('gis_proxy_url', proxy);
      if (statusEl) statusEl.textContent = proxy ? '自定义' : '系统代理';
      // 同步到后端
      fetch('/api/proxy-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proxy: proxy })
      }).then(function(r) { return r.json(); }).then(function(data) {
        if (msgEl) {
          msgEl.textContent = proxy ? ('已保存: ' + proxy) : '已清除，使用系统代理';
          msgEl.style.color = 'var(--ui-success, #4caf50)';
        }
      }).catch(function() {
        if (msgEl) { msgEl.textContent = '保存失败（后端未启动？）'; msgEl.style.color = '#f44336'; }
      });
    });
  }

  // ============================================================
  // 模型选择器（从 Provider 列表动态渲染）
  // ============================================================

  function bindModelPicker() {
    var picker = document.getElementById('modelPicker');
    var trigger = document.getElementById('modelSelectTrigger');
    if (!picker || !trigger) return;

    trigger.addEventListener('click', function(e) {
      renderModelPickerOptions();
      picker.classList.toggle('is-open');
    });
    document.addEventListener('click', function(e) {
      if (picker.classList.contains('is-open') &&
          !picker.contains(e.target) &&
          !trigger.contains(e.target)) {
        picker.classList.remove('is-open');
      }
    });
  }

  function renderModelPickerOptions() {
    var picker = document.getElementById('modelPicker');
    if (!picker) return;
    var selector = document.getElementById('modelSelector');
    var cur = selector ? selector.value : GIS.api.getSelectedModel();
    picker.innerHTML = '';
    var providers = GIS.api.getProviders();
    providers.forEach(function(p, idx) {
      if (idx) {
        var div = document.createElement('div');
        div.className = 'model-picker-divider';
        picker.appendChild(div);
      }
      var opt = document.createElement('div');
      opt.className = 'model-picker-option' + (p.id === cur ? ' is-selected' : '');
      opt.dataset.value = p.id;
      var desc = (p.base_url || '?') + ' · ' + (p.model || '未填模型');
      opt.innerHTML =
        '<div class="model-picker-info">' +
        '<span class="model-picker-name">' + GIS.utils.escapeHtml(p.name || p.id) + '</span>' +
        '<span class="model-picker-desc">' + GIS.utils.escapeHtml(desc) + '</span>' +
        '</div>' +
        (p.api_key ? '' : '<span class="model-picker-free">未配 Key</span>') +
        CHECK_SVG;
      opt.addEventListener('click', function() {
        selectModel(p.id);
      });
      picker.appendChild(opt);
    });
  }

  function selectModel(id) {
    var selector = document.getElementById('modelSelector');
    var valueEl = document.getElementById('modelSelectValue');
    var picker = document.getElementById('modelPicker');
    if (!id) return;
    GIS.api.setSelectedModel(id);
    syncProviderStorageWarning(document.getElementById('providerList'));
    // 同步隐藏 select（map.js/task.js 等仍读它的 value）
    syncModelOptions(id);
    var p = GIS.api.getProvider(id);
    if (valueEl) valueEl.textContent = p ? p.name : id;
    if (picker) {
      picker.querySelectorAll('.model-picker-option').forEach(function(o) {
        o.classList.toggle('is-selected', o.dataset.value === id);
      });
      picker.classList.remove('is-open');
    }
    updateModelStatusDot();
  }

  /** 把隐藏 select 的 <option> 同步成 Provider 列表，并设 value */
  function syncModelOptions(selectedId) {
    var selector = document.getElementById('modelSelector');
    if (!selector) return;
    var providers = GIS.api.getProviders();
    var current = selectedId || selector.value || GIS.api.getSelectedModel();
    selector.innerHTML = '';
    providers.forEach(function(p) {
      var o = document.createElement('option');
      o.value = p.id;
      o.textContent = p.name || p.id;
      selector.appendChild(o);
    });
    if (getProviderById(providers, current)) selector.value = current;
  }

  function getProviderById(list, id) {
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  function initModelSelector() {
    bindModelPicker();
    var selector = document.getElementById('modelSelector');
    var valueEl = document.getElementById('modelSelectValue');
    if (!selector) return;
    syncModelOptions(GIS.api.getSelectedModel());
    var p = GIS.api.getProvider(GIS.api.getSelectedModel());
    if (valueEl) valueEl.textContent = p ? p.name : GIS.api.getSelectedModel();
    renderModelPickerOptions();
    updateModelStatusDot();
  }

  /** 增删 Provider 后同步顶栏选择 UI */
  function syncModelUI() {
    syncModelOptions(GIS.api.getSelectedModel());
    var p = GIS.api.getProvider(GIS.api.getSelectedModel());
    var valueEl = document.getElementById('modelSelectValue');
    if (valueEl) valueEl.textContent = p ? p.name : GIS.api.getSelectedModel();
    renderModelPickerOptions();
    updateModelStatusDot();
  }

  // ============================================================
  // 状态点 / 顶部警告
  // ============================================================

  function updateModelStatusDot() {
    var dot = document.getElementById('modelStatusDot');
    if (!dot) return;
    var cur = GIS.api.currentProvider();
    var status = cur ? GIS.api.getModelStatus(cur.id) : 'untested';
    dot.classList.remove('online', 'offline', 'checking', 'untested');
    if (!cur || !cur.api_key) {
      dot.classList.add('untested');
      dot.title = !cur ? '未选择模型' : (cur.name || 'AI 模型') + '：未配置 API Key';
    } else if (status === 'offline') {
      dot.classList.add('offline');
      dot.title = (cur.name || 'AI 模型') + '：连接离线';
    } else if (status === 'checking') {
      dot.classList.add('checking');
      dot.title = (cur.name || 'AI 模型') + '：检测中...';
    } else if (status === 'online') {
      dot.classList.add('online');
      dot.title = (cur.name || 'AI 模型') + '：就绪在线';
    } else {
      dot.classList.add('untested');
      dot.title = (cur.name || 'AI 模型') + '：尚未验证';
    }
    updateModelWarning();
    if (typeof updateGreeting === 'function') updateGreeting();
  }

  function updateModelWarning() {
    var warn = document.getElementById('modelWarning');
    if (!warn) return;
    var providers = GIS.api.getProviders();
    var anyKey = providers.some(function(p) { return !!p.api_key; });
    var cur = GIS.api.currentProvider();
    
    // 如果聊天区域当前处于初始空状态（即中央已渲染“尚未配置 AI 模型”空状态卡片），
    // 则不在底部重复展示黄色/红色警示条，避免视觉冗余与错位
    var emptyEl = document.querySelector('.chat-messages-empty');
    var isChatEmpty = emptyEl && emptyEl.style.display !== 'none' && (!document.querySelector('.message') || document.querySelectorAll('.message').length === 0);

    if (!anyKey) {
      if (isChatEmpty) {
        warn.style.display = 'none';
        warn.innerHTML = '';
      } else {
        warn.style.display = 'flex';
        warn.innerHTML = '<span>尚未配置 API Key</span> <button type="button" class="warn-config-link" style="background:none;border:0;color:inherit;text-decoration:underline;cursor:pointer;font-size:11px;padding:0 2px;">去配置</button>';
      }
    } else if (cur && !cur.api_key) {
      warn.style.display = 'flex';
      warn.innerHTML = '<span>当前模型未填 Key</span> <button type="button" class="warn-config-link" style="background:none;border:0;color:inherit;text-decoration:underline;cursor:pointer;font-size:11px;padding:0 2px;">去配置</button>';
    } else if (cur && cur.api_key && GIS.api.getModelStatus(cur.id) === 'offline') {
      warn.style.display = 'flex';
      warn.innerHTML = '<span>当前模型连接失败</span> <button type="button" class="warn-config-link" style="background:none;border:0;color:inherit;text-decoration:underline;cursor:pointer;font-size:11px;padding:0 2px;">检查设置</button>';
    } else {
      warn.style.display = 'none';
      warn.innerHTML = '';
    }
    var link = warn.querySelector('.warn-config-link');
    if (link) {
      link.onclick = function() {
        var s = document.getElementById('settingsBtn');
        if (s) s.click();
      };
    }
  }

  // ============================================================
  // 主题 / 字号
  // ============================================================

  function initTheme() {
    var themeBtns = document.querySelectorAll('.theme-btn');
    if (!themeBtns.length) return;

    function applyTheme(theme) {
      document.documentElement.classList.toggle('theme-dark', theme === 'dark');
      themeBtns.forEach(function(b) {
        b.classList.toggle('active', b.dataset.theme === theme);
      });
      try { localStorage.setItem('gis_theme', theme); } catch(e) {}
    }
    var savedTheme = localStorage.getItem('gis_theme');
    if (savedTheme) applyTheme(savedTheme);

    themeBtns.forEach(function(btn) {
      btn.addEventListener('click', function() { applyTheme(this.dataset.theme); });
    });
  }

  function initFontSize() {
    var slider = document.getElementById('fontSizeSlider');
    var valueEl = document.getElementById('fontSizeValue');
    if (!slider) return;

    function applyFontScale(val) {
      var scale = val / 14;
      document.documentElement.style.setProperty('--font-scale', scale);
      if (valueEl) valueEl.textContent = val + 'px';
      if (slider) slider.value = val;
      try { localStorage.setItem('gis_font_size', val); } catch(e) {}
    }
    var savedSize = localStorage.getItem('gis_font_size');
    if (savedSize) applyFontScale(parseInt(savedSize, 10));
    slider.addEventListener('input', function() { applyFontScale(parseInt(this.value, 10)); });
  }

  // 连通状态来自本次页面会话内的手动测速；重开页面后旧状态作废，不自动产生模型请求。
  function resetProviderStatuses() {
    if (!GIS.api || !GIS.api.getProviders || !GIS.api.setModelStatus) return;
    GIS.api.getProviders().forEach(function(provider) {
      GIS.api.setModelStatus(provider.id, 'untested');
    });
  }

  // ============================================================
  // 按钮按下反馈
  // ============================================================

  function bindButtonFeedback() {
    document.querySelectorAll('button, .icon-btn, .map-zoom-btn, .map-layer-btn, .layer-action-btn')
      .forEach(function(el) {
        el.addEventListener('mousedown', function() { this.style.opacity = '0.7'; });
        el.addEventListener('mouseup', function() { this.style.opacity = '1'; });
        el.addEventListener('mouseleave', function() { this.style.opacity = '1'; });
      });
  }

  // ========== 公开接口 ==========
  GIS.settings = {
    init,
    openModal,
  };
})();


  // ===== 日志导出面板 =====
  function _initLogsPanel() {
    var exportBtn = document.getElementById('logsExportBtn');
    var refreshBtn = document.getElementById('logsRefreshBtn');
    var clearBtn = document.getElementById('logsClearBtn');

    function logsUrl(path) {
      var sid = window.GIS.project && window.GIS.project.getCurrentSessionId
        ? window.GIS.project.getCurrentSessionId()
        : 'default';
      return path + '?session_id=' + encodeURIComponent(sid || 'default');
    }

    function refreshStats() {
      fetch(logsUrl('/api/logs/stats'))
        .then(function(r) { return r.json(); })
        .then(function(data) {
          var tempEl = document.getElementById('logsTempCount');
          var permEl = document.getElementById('logsPermCount');
          var pathEl = document.getElementById('logsPath');
          if (tempEl) tempEl.textContent = data.temp_count || 0;
          if (permEl) permEl.textContent = data.perm_count || 0;
          var legacyNote = document.getElementById('logsLegacyNote');
          if (legacyNote) {
            var legacyCount = Number(data.legacy_temp_count) || 0;
            legacyNote.hidden = legacyCount <= 0;
            legacyNote.textContent = legacyCount > 0
              ? '另有 ' + legacyCount + ' 条旧版共享会话记录，可通过导出查看。' : '';
          }
          if (pathEl) pathEl.textContent = data.log_dir || 'logs/';
        })
        .catch(function() {});
    }

    if (exportBtn) {
      exportBtn.addEventListener('click', function() {
        window.open(logsUrl('/api/logs/export'), '_blank');
      });
    }
    if (refreshBtn) {
      refreshBtn.addEventListener('click', refreshStats);
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', function() {
        if (!confirm('确定清除当前会话的所有日志吗？此操作不可恢复。')) return;
        fetch(logsUrl('/api/logs/clear'), { method: 'POST' })
          .then(function(r) { return r.json(); })
          .then(function() {
            refreshStats();
            alert('日志已清除');
          })
          .catch(function() { alert('清除失败'); });
      });
    }

    // 打开设置时自动刷新统计
    refreshStats();
  }

  // 页面加载完成后初始化日志面板
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _initLogsPanel);
  } else {
    _initLogsPanel();
  }
