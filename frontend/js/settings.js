/**
 * GIS AI WorkTable — 设置模块
 * 设置弹窗、密钥管理、模型选择器、主题/字号
 */
window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  function init() {
    bindSettingsModal();
    bindKeyManagement();
    bindModelPicker();
    initTheme();
    initFontSize();
    initModelSelector();
    autoDetectModelStatus();
    bindButtonFeedback();
  }

  // ============================================================
  // 设置弹窗
  // ============================================================

  function bindSettingsModal() {
    var modal = document.getElementById('settingsModal');
    var settingsBtn = document.getElementById('settingsBtn');
    var closeBtn = document.getElementById('modalCloseBtn');
    if (!modal || !settingsBtn) return;

    settingsBtn.addEventListener('click', function() {
      openModal();
    });
    if (closeBtn) {
      closeBtn.addEventListener('click', closeModal);
    }
    modal.addEventListener('click', function(e) {
      if (e.target === modal) closeModal();
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && modal.style.display === 'flex') closeModal();
    });

    // 侧边栏切换
    var sidenavItems = document.querySelectorAll('.modal-sidenav-item');
    var panels = {
      appearance: document.getElementById('panelAppearance'),
      'ai-api': document.getElementById('panelAiApi'),
      'geo-api': document.getElementById('panelGeoApi'),
      history: document.getElementById('panelHistory'),
      about: document.getElementById('panelAbout'),
    };
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

  function openModal() {
    var modal = document.getElementById('settingsModal');
    if (!modal) return;

    var sidenavItems = document.querySelectorAll('.modal-sidenav-item');
    var panels = {
      appearance: document.getElementById('panelAppearance'),
      'ai-api': document.getElementById('panelAiApi'),
      'geo-api': document.getElementById('panelGeoApi'),
      history: document.getElementById('panelHistory'),
      about: document.getElementById('panelAbout'),
    };

    sidenavItems.forEach(function(s) { s.classList.remove('active'); });
    var firstNav = document.querySelector('.modal-sidenav-item[data-panel="appearance"]');
    if (firstNav) firstNav.classList.add('active');
    Object.keys(panels).forEach(function(k) {
      if (panels[k]) panels[k].classList.toggle('active', k === 'appearance');
    });

    populateKeyInputs();
    modal.style.display = 'flex';

    // 检测浏览器自动填充
    setTimeout(function() {
      var inputs = [
        document.getElementById('apiKeyInput'),
        document.getElementById('glmApiKeyInput'),
        document.getElementById('amapApiKeyInput'),
        document.getElementById('agnesApiKeyInput'),
      ];
      var keyMap = [
        { input: 'apiKeyInput', get: 'getApiKey', set: 'setApiKey', status: 'deepseek' },
        { input: 'glmApiKeyInput', get: 'getGLMApiKey', set: 'setGLMApiKey', status: 'glm' },
        { input: 'amapApiKeyInput', get: 'getAmapKey', set: 'setAmapKey', status: null },
        { input: 'agnesApiKeyInput', get: 'getAgnesApiKey', set: 'setAgnesApiKey', status: 'agnes' },
      ];
      keyMap.forEach(function(km) {
        var el = document.getElementById(km.input);
        if (el && el.value.trim() && !GIS.api[km.get]()) {
          GIS.api[km.set](el.value.trim());
          if (km.status) {
            updateKeyStatus(km.status, el.value.trim());
          }
        }
      });
      updateModelWarning();
      updateModelStatusDot();
    }, 100);
  }

  function closeModal() {
    var modal = document.getElementById('settingsModal');
    if (modal) modal.style.display = 'none';
  }

  // ============================================================
  // 密钥管理
  // ============================================================

  function populateKeyInputs() {
    var maps = [
      { id: 'apiKeyInput', get: 'getApiKey', status: 'deepseek' },
      { id: 'glmApiKeyInput', get: 'getGLMApiKey', status: 'glm' },
      { id: 'amapApiKeyInput', get: 'getAmapKey', status: 'amap' },
      { id: 'agnesApiKeyInput', get: 'getAgnesApiKey', status: 'agnes' },
    ];
    maps.forEach(function(m) {
      var el = document.getElementById(m.id);
      var key = GIS.api[m.get]();
      if (el) el.value = key;
      updateKeyStatus(m.status, key);
    });

    // 清空测试结果
    ['testResult', 'glmTestResult', 'amapTestResult', 'agnesTestResult'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = '';
    });
  }

  function updateKeyStatus(provider, key) {
    var map = {
      deepseek: 'apiKeyStatus',
      glm: 'glmApiKeyStatus',
      amap: 'amapKeyStatus',
      agnes: 'agnesApiKeyStatus',
    };
    var el = document.getElementById(map[provider]);
    if (!el) return;
    el.textContent = key ? '已配置' : '未配置';
    el.className = 'model-config-badge' + (key ? ' configured' : '');
  }

  function toggleKeyVis(inputId, eyeId) {
    var input = document.getElementById(inputId);
    var eye = document.getElementById(eyeId);
    if (!input || !eye) return;
    if (input.type === 'password') {
      input.type = 'text';
      eye.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/>';
    } else {
      input.type = 'password';
      eye.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
    }
  }

  function saveKey(provider) {
    var map = {
      deepseek: { input: 'apiKeyInput', set: 'setApiKey', status: 'deepseek' },
      glm: { input: 'glmApiKeyInput', set: 'setGLMApiKey', status: 'glm' },
      agnes: { input: 'agnesApiKeyInput', set: 'setAgnesApiKey', status: 'agnes' },
      amap: { input: 'amapApiKeyInput', set: 'setAmapKey', status: 'amap' },
    };
    var cfg = map[provider];
    if (!cfg) return;
    var input = document.getElementById(cfg.input);
    if (!input) return;
    var key = input.value.trim();
    GIS.api[cfg.set](key);
    GIS.api.setModelStatus(cfg.status === 'amap' ? 'amap' : cfg.status, 'untested');
    updateKeyStatus(cfg.status, key);
    updateModelWarning();

    var btnMap = {
      deepseek: 'saveKeyBtn',
      glm: 'saveGlmKeyBtn',
      agnes: 'saveAgnesKeyBtn',
      amap: 'saveAmapKeyBtn',
    };
    var btn = document.getElementById(btnMap[provider]);
    if (btn) {
      var orig = btn.textContent;
      btn.textContent = '已保存 ✓';
      setTimeout(function() { btn.textContent = orig; }, 2000);
    }
  }

  async function testKey(provider) {
    var map = {
      deepseek: { input: 'apiKeyInput', test: 'testApiKey', result: 'testResult', btn: 'testKeyBtn', status: 'deepseek' },
      glm: { input: 'glmApiKeyInput', test: 'testGLMApiKey', result: 'glmTestResult', btn: 'testGlmKeyBtn', status: 'glm' },
      agnes: { input: 'agnesApiKeyInput', test: 'testAgnesApiKey', result: 'agnesTestResult', btn: 'testAgnesKeyBtn', status: 'agnes' },
    };
    var cfg = map[provider];
    if (!cfg) return;
    var input = document.getElementById(cfg.input);
    var resultEl = document.getElementById(cfg.result);
    var btn = document.getElementById(cfg.btn);
    if (!input || !resultEl || !btn) return;

    var key = input.value.trim();
    if (!key) {
      resultEl.textContent = '请先输入 API 密钥';
      resultEl.className = 'modal-test-result modal-test-error';
      return;
    }

    if (btn.dataset.testing === 'true') return;
    btn.dataset.testing = 'true';
    btn.textContent = '测速中...';
    btn.disabled = true;
    resultEl.innerHTML = '<span class="loading-spinner"></span> 正在连接...';
    resultEl.className = 'modal-test-result';

    try {
      var res = await GIS.api[cfg.test](key);
      resultEl.textContent = res.message;
      resultEl.className = 'modal-test-result ' + (res.success ? 'modal-test-success' : 'modal-test-error');
      GIS.api.setModelStatus(cfg.status, res.success ? 'online' : 'offline');
      if (document.getElementById('modelSelector') &&
          document.getElementById('modelSelector').value === provider) {
        updateModelStatusDot();
      }
    } catch (e) {
      GIS.api.setModelStatus(cfg.status, 'offline');
      if (document.getElementById('modelSelector') &&
          document.getElementById('modelSelector').value === provider) {
        updateModelStatusDot();
      }
      resultEl.textContent = '连接失败: ' + e.message;
      resultEl.className = 'modal-test-result modal-test-error';
    } finally {
      btn.dataset.testing = 'false';
      btn.textContent = '测速';
      btn.disabled = false;
    }
  }

  function bindKeyManagement() {
    // 显隐切换
    bindToggleVis('toggleKeyVis', 'apiKeyInput', 'eyeIcon');
    bindToggleVis('toggleGlmKeyVis', 'glmApiKeyInput', 'glmEyeIcon');
    bindToggleVis('toggleAgnesKeyVis', 'agnesApiKeyInput', 'agnesEyeIcon');
    bindToggleVis('toggleAmapKeyVis', 'amapApiKeyInput', 'amapEyeIcon');

    // 保存
    bindSave('saveKeyBtn', 'deepseek');
    bindSave('saveGlmKeyBtn', 'glm');
    bindSave('saveAgnesKeyBtn', 'agnes');
    bindSave('saveAmapKeyBtn', 'amap');

    // 测速
    bindTest('testKeyBtn', 'deepseek');
    bindTest('testGlmKeyBtn', 'glm');
    bindTest('testAgnesKeyBtn', 'agnes');
  }

  function bindToggleVis(btnId, inputId, eyeId) {
    var btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', function() {
      toggleKeyVis(inputId, eyeId);
    });
  }

  function bindSave(btnId, provider) {
    var btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', function() {
      saveKey(provider);
    });
  }

  function bindTest(btnId, provider) {
    var btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', function() {
      testKey(provider);
    });
  }

  // ============================================================
  // 模型选择器
  // ============================================================

  function bindModelPicker() {
    var picker = document.getElementById('modelPicker');
    var trigger = document.getElementById('modelSelectTrigger');
    var selector = document.getElementById('modelSelector');
    var valueEl = document.getElementById('modelSelectValue');
    if (!picker || !trigger || !selector || !valueEl) return;

    var options = picker.querySelectorAll('.model-picker-option');

    function updateSelection() {
      var cur = selector.value;
      options.forEach(function(opt) {
        opt.classList.toggle('is-selected', opt.dataset.value === cur);
      });
    }

    trigger.addEventListener('click', function(e) {
      updateSelection();
      picker.classList.toggle('is-open');
    });

    options.forEach(function(opt) {
      opt.addEventListener('click', function() {
        var val = this.dataset.value;
        if (val === selector.value) { picker.classList.remove('is-open'); return; }
        selector.value = val;
        var names = { 'deepseek-routed': 'DeepSeek V4 Flash+', 'glm-routed': 'GLM-4.7-Flash+', 'agnes': 'Agnes 2.0 Flash+' };
        valueEl.textContent = names[val] || val;
        GIS.api.setSelectedModel(val);
        updateModelStatusDot();
        picker.classList.remove('is-open');
      });
    });

    document.addEventListener('click', function(e) {
      if (picker.classList.contains('is-open') &&
          !picker.contains(e.target) &&
          !trigger.contains(e.target)) {
        picker.classList.remove('is-open');
      }
    });
  }

  function updateModelStatusDot() {
    var dot = document.getElementById('modelStatusDot');
    var selector = document.getElementById('modelSelector');
    if (!dot || !selector) return;
    var provider = selector.value;
    var statusProvider = provider === 'deepseek-routed' ? 'deepseek' : provider;
    var status = GIS.api.getModelStatus(statusProvider);
    dot.classList.remove('online', 'offline', 'checking');
    if (status === 'online') {
      dot.classList.add('online');
    } else {
      dot.classList.add('offline');
    }
    updateModelWarning();
  }

  function updateModelWarning() {
    var warn = document.getElementById('modelWarning');
    if (!warn) return;
    var dsKey = GIS.api.getApiKey();
    var glmKey = GIS.api.getGLMApiKey();
    var agnesKey = GIS.api.getAgnesApiKey();
    var dsStatus = GIS.api.getModelStatus('deepseek');
    var glmStatus = GIS.api.getModelStatus('glm');
    var agnesStatus = GIS.api.getModelStatus('agnes');
    var anyConfigured = dsKey || glmKey || agnesKey;
    var anyOnline = dsStatus === 'online' || glmStatus === 'online' || agnesStatus === 'online';
    if (!anyConfigured) {
      warn.style.display = 'block';
      warn.querySelector('span').textContent = '请配置 API Key（DeepSeek / GLM / Agnes 任一即可），点击齿轮按钮设置';
    } else if (!anyOnline && (dsStatus !== 'untested' || glmStatus !== 'untested' || agnesStatus !== 'untested')) {
      warn.style.display = 'block';
      warn.querySelector('span').textContent = '配置的 API Key 均连接失败，请检查密钥配置';
    } else {
      warn.style.display = 'none';
    }
  }

  function initModelSelector() {
    var selector = document.getElementById('modelSelector');
    var valueEl = document.getElementById('modelSelectValue');
    var picker = document.getElementById('modelPicker');
    if (!selector || !valueEl) return;
    var saved = GIS.api.getSelectedModel();
    selector.value = saved;
    var names = { 'deepseek-routed': 'DeepSeek V4 Flash+', 'glm-routed': 'GLM-4.7-Flash+', 'agnes': 'Agnes 2.0 Flash+' };
    valueEl.textContent = names[saved] || saved;
    if (picker) {
      picker.querySelectorAll('.model-picker-option').forEach(function(opt) {
        opt.classList.toggle('is-selected', opt.dataset.value === saved);
      });
    }
    updateModelStatusDot();
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
      btn.addEventListener('click', function() {
        applyTheme(this.dataset.theme);
      });
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
    slider.addEventListener('input', function() {
      applyFontScale(parseInt(this.value, 10));
    });
  }

  // ============================================================
  // 自动检测模型状态
  // ============================================================

  function autoDetectModelStatus() {
    if (!GIS.api) {
      setTimeout(autoDetectModelStatus, 1000);
      return;
    }
    var providers = ['deepseek', 'glm', 'agnes'];
    var keyMap = { deepseek: 'getApiKey', glm: 'getGLMApiKey', agnes: 'getAgnesApiKey' };
    var testMap = { deepseek: 'testApiKey', glm: 'testGLMApiKey', agnes: 'testAgnesApiKey' };
    var selector = document.getElementById('modelSelector');
    var dot = document.getElementById('modelStatusDot');

    providers.forEach(function(provider) {
      var key = GIS.api[keyMap[provider]]();
      if (!key) {
        GIS.api.setModelStatus(provider, 'offline');
        if (selector && selector.value === provider) updateModelStatusDot();
        return;
      }
      if (selector && selector.value === provider && dot) {
        dot.classList.remove('online', 'offline');
        dot.classList.add('checking');
      }
      GIS.api[testMap[provider]](key).then(function(result) {
        GIS.api.setModelStatus(provider, result.success ? 'online' : 'offline');
        if (selector && selector.value === provider) updateModelStatusDot();
      }).catch(function() {
        GIS.api.setModelStatus(provider, 'offline');
        if (selector && selector.value === provider) updateModelStatusDot();
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
  };
})();
