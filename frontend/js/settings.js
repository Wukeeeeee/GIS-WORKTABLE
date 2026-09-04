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

  // 复用已有 CSS 的模型选择器 check 图标
  const CHECK_SVG =
    '<svg class="model-picker-check" viewBox="0 0 16 16" width="16" height="16">' +
    '<circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.5"/>' +
    '<path d="M5 8l2 2 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
    '</svg>';

  function init() {
    // 各块互相隔离：任何一块报错都不影响顶栏模型名同步等其余功能
    try { bindSettingsModal(); } catch (e) { console.warn('[GIS settings] bindSettingsModal', e); }
    try { bindAmap(); } catch (e) { console.warn('[GIS settings] bindAmap', e); }
    try { initProviderPanel(); } catch (e) { console.warn('[GIS settings] provider panel', e); }
    try { initTheme(); } catch (e) {}
    try { initFontSize(); } catch (e) {}
    try { initModelSelector(); } catch (e) { console.warn('[GIS settings] model selector', e); }
    try { autoDetectModelStatus(); } catch (e) {}
    try { bindButtonFeedback(); } catch (e) {}
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
      history: document.getElementById('panelHistory'),
      about: document.getElementById('panelAbout'),
    };
  }

  function openModal() {
    var modal = document.getElementById('settingsModal');
    if (!modal) return;
    var sidenavItems = document.querySelectorAll('.modal-sidenav-item');
    var panels = _panels();
    sidenavItems.forEach(function(s) { s.classList.remove('active'); });
    var firstNav = document.querySelector('.modal-sidenav-item[data-panel="appearance"]');
    if (firstNav) firstNav.classList.add('active');
    Object.keys(panels).forEach(function(k) {
      if (panels[k]) panels[k].classList.toggle('active', k === 'appearance');
    });

    // 打开设置前把当前 Provider 列表渲染进面板
    renderProviderList();
    populateAmapInput();
    modal.style.display = 'flex';
    updateModelStatusDot();
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
      return { text: '已配置', cls: 'model-config-badge configured' };
    }
    return { text: '未配置', cls: 'model-config-badge' };
  }

  function renderProviderList() {
    var host = document.getElementById('providerList');
    if (!host) return;
    host.innerHTML = '';
    var providers = GIS.api.getProviders();
    if (!providers || !providers.length) return;

    var container = host;

    providers.forEach(function(p, idx) {
      var badge = providerStatusBadge(p);
      var card = document.createElement('div');
      card.className = 'model-config-card';
      card.dataset.providerId = p.id;
      card.style.borderLeft = '3px solid ' + (idx % 2 ? 'var(--ui-gray-300,#d0d5dd)' : 'var(--accent,#6366f1)');

      var header = document.createElement('div');
      header.className = 'model-config-header';
      var curTag = (p.id === GIS.api.getSelectedModel())
        ? '<span class="model-config-free" style="color:var(--accent,#6366f1);">● 当前使用</span>' : '';
      header.innerHTML =
        '<input type="text" class="modal-input prov-name" value="' + GIS.utils.escapeHtml(p.name || '') + '" style="flex:1;padding:6px 8px;" title="显示名称(顶栏/列表/任务卡都用它)" />' +
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
        _fieldRow('base_url', '接口地址', p.base_url, 'https://.../v1', 'text') +
        _fieldRow('model', '模型名', p.model, 'model-name', 'text') +
        _fieldRow('api_key', 'API Key', p.api_key, 'sk-...', 'password');
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

  function _fieldRow(field, label, value, placeholder, type) {
    var show = field === 'api_key';
    return '<div style="display:flex;gap:6px;align-items:center;">' +
      '<span style="width:64px;font-size:11px;color:var(--ui-gray-500,#888);flex:none;">' + label + '</span>' +
      '<div class="modal-input-wrapper" style="flex:1;">' +
      '<input type="' + (show ? 'password' : type) + '" class="modal-input" data-field="' + field + '" value="' +
      GIS.utils.escapeHtml(value || '') + '" placeholder="' + placeholder + '" autocomplete="off" />' +
      (show ? '<button class="modal-toggle-vis" type="button" title="显示/隐藏密钥">' +
        '<svg class="prov-eye" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>' +
        '</svg></button>' : '') +
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
    if (msgEl) { msgEl.innerHTML = '正在连接...'; msgEl.className = 'modal-test-result'; }

    try {
      var res = await GIS.api.testProvider(p);
      GIS.api.setModelStatus(p.id, res.success ? 'online' : 'offline');
      if (msgEl) {
        msgEl.textContent = res.message;
        msgEl.className = 'modal-test-result ' + (res.success ? 'modal-test-success' : 'modal-test-error');
      }
    } catch (e) {
      GIS.api.setModelStatus(p.id, 'offline');
      if (msgEl) {
        msgEl.textContent = '连接失败: ' + (e.message || e);
        msgEl.className = 'modal-test-result modal-test-error';
      }
    } finally {
      btn.dataset.testing = 'false';
      btn.disabled = false;
      btn.textContent = '测速';
      // 刷新徽章（不重建整个列表，避免打断编辑）
      var badge = card ? card.querySelector('.model-config-header .model-config-badge') : null;
      if (badge) {
        var st = providerStatusBadge(GIS.api.getProvider(id));
        badge.textContent = st.text;
        badge.className = st.cls;
      }
      updateModelStatusDot();
    }
  }

  // ============================================================
  // 高德地图 Key（仍单独存，放 #panelGeoApi）
  // ============================================================

  function bindAmap() {
    var input = document.getElementById('amapApiKeyInput');
    if (input) input.addEventListener('change', function() { GIS.api.setAmapKey(this.value.trim()); });
    var saveBtn = document.getElementById('saveAmapKeyBtn');
    if (saveBtn) {
      saveBtn.addEventListener('click', function() {
        var key = (document.getElementById('amapApiKeyInput') || {}).value || '';
        GIS.api.setAmapKey(key.trim());
        var msg = document.getElementById('amapTestResult');
        if (msg) { msg.textContent = '已保存 ✓'; msg.className = 'modal-test-result modal-test-success'; }
        setTimeout(function() { if (msg) { msg.textContent = ''; msg.className = 'modal-test-result'; } }, 2000);
        updateAmapStatus();
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
    el.textContent = has ? '已配置' : '未配置';
    el.className = 'model-config-badge' + (has ? ' configured' : '');
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
    dot.classList.remove('online', 'offline', 'checking');
    if (cur && cur.api_key && status === 'online') dot.classList.add('online');
    else dot.classList.add('offline');
    updateModelWarning();
  }

  function updateModelWarning() {
    var warn = document.getElementById('modelWarning');
    if (!warn) return;
    var providers = GIS.api.getProviders();
    var anyKey = providers.some(function(p) { return !!p.api_key; });
    var cur = GIS.api.currentProvider();
    if (!anyKey) {
      warn.style.display = 'block';
      warn.querySelector('span').textContent = '请配置 API Key（任选一个 Provider 填 Key），点击齿轮按钮设置';
    } else if (cur && !cur.api_key) {
      warn.style.display = 'block';
      warn.querySelector('span').textContent = '当前 Provider 未填 Key，请先在设置里配置';
    } else if (cur && cur.api_key && GIS.api.getModelStatus(cur.id) === 'offline') {
      warn.style.display = 'block';
      warn.querySelector('span').textContent = '当前 Provider 连接失败，请检查密钥 / 接口地址';
    } else {
      warn.style.display = 'none';
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

  // ============================================================
  // 自动检测已配置 Provider 的连通性（静默，不打断）
  // ============================================================

  function autoDetectModelStatus() {
    if (!GIS.api || !GIS.api.getProviders) {
      setTimeout(autoDetectModelStatus, 1000);
      return;
    }
    var providers = GIS.api.getProviders().filter(function(p) { return !!p.api_key; });
    var dot = document.getElementById('modelStatusDot');
    if (!providers.length) {
      if (dot) { dot.classList.remove('online', 'offline'); dot.classList.add('offline'); }
      return;
    }
    providers.forEach(function(p) {
      if (dot) { dot.classList.remove('online', 'offline'); dot.classList.add('checking'); }
      GIS.api.testProvider(p).then(function(res) {
        GIS.api.setModelStatus(p.id, res.success ? 'online' : 'offline');
        if (GIS.api.getSelectedModel() === p.id) updateModelStatusDot();
      }).catch(function() {
        GIS.api.setModelStatus(p.id, 'offline');
        if (GIS.api.getSelectedModel() === p.id) updateModelStatusDot();
      });
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
    closeModal,
    updateModelStatusDot,
    updateModelWarning,
    syncModelUI,
  };
})();
