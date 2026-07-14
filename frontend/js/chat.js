/**
 * ============================================
 *  GIS AI WorkTable — 聊天模块
 *  消息渲染、输入框绑定、发送逻辑
 * ============================================
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

// 所有外部链接新标签打开
var _linkRenderer = new marked.Renderer();
_linkRenderer.link = function(token) {
  return '<a href="' + token.href + '" target="_blank" rel="noopener noreferrer">' + token.text + '</a>';
};

//将GIS命名空间赋值给常量GIS，相当于全局变量
  const GIS = window.GIS;

  /** @type {HTMLElement} */
  let messagesContainer = null;
  let inputEl = null;
  let sendBtn = null;

  // Chip 命令名 → 技能标签映射（用于 force_skills）
  const CHIP_TO_SKILL = {
    buffer: 'geometry', intersection: 'geometry', union: 'geometry',
    difference: 'geometry', centroid: 'geometry', simplify: 'geometry',
    make_valid: 'geometry',
    area: 'analysis', length: 'analysis',
    aoi: 'aoi',
    boundary: 'datav',
    heatmap: 'heatmap',
    plot: 'visualization',
    amap: 'amap'
  };
  // 每个命令的 SVG icon（14x14，currentColor）
  const SLASH_ICONS = {
    buffer: '<svg viewBox="0 0 14 14"><circle cx="7" cy="7" r="5.2" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="7" cy="7" r="2.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
    intersection: '<svg viewBox="0 0 14 14"><circle cx="5.2" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="8.8" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
    union: '<svg viewBox="0 0 14 14"><path d="M4 3v5a3 3 0 006 0V3" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M4 3h6" stroke="currentColor" stroke-width="1.3"/></svg>',
    difference: '<svg viewBox="0 0 14 14"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M7 2.5v9" stroke="currentColor" stroke-width="1.3"/></svg>',
    centroid: '<svg viewBox="0 0 14 14"><circle cx="7" cy="7" r="5.2" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="7" cy="7" r="1" fill="currentColor"/></svg>',
    simplify: '<svg viewBox="0 0 14 14"><polyline points="1,10 4,4 7,9 10,3 13,8" fill="none" stroke="currentColor" stroke-width="1.2"/><polyline points="1,11 13,11" fill="none" stroke="currentColor" stroke-width="1" opacity=".4"/></svg>',
    area: '<svg viewBox="0 0 14 14"><rect x="2" y="3" width="10" height="8" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M2 3L12 11" stroke="currentColor" stroke-width=".8" opacity=".3"/></svg>',
    length: '<svg viewBox="0 0 14 14"><line x1="2" y1="7" x2="12" y2="7" stroke="currentColor" stroke-width="1.3"/><polyline points="9,4 12,7 9,10" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>',
    make_valid: '<svg viewBox="0 0 14 14"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.2"/><polyline points="4.5,7 6.5,9 9.5,5.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
    aoi: '<svg viewBox="0 0 14 14"><path d="M2 12V3l5-2 5 2v9zm5-9v8M2 5h10M2 9h10" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>',
    boundary: '<svg viewBox="0 0 14 14"><polygon points="7,1 12,4 12,10 7,13 2,10 2,4" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="7" cy="7" r="1.5" fill="none" stroke="currentColor" stroke-width="1"/></svg>',
    heatmap: '<svg viewBox="0 0 14 14"><rect x="1" y="1" width="5" height="5" rx="1" fill="none" stroke="currentColor" stroke-width="1"/><rect x="8" y="1" width="5" height="5" rx="1" fill="none" stroke="currentColor" stroke-width="1"/><rect x="1" y="8" width="5" height="5" rx="1" fill="none" stroke="currentColor" stroke-width="1"/><rect x="8" y="8" width="5" height="5" rx="1" fill="none" stroke="currentColor" stroke-width="1"/><circle cx="3.5" cy="3.5" r="1.2" fill="currentColor" opacity=".6"/><circle cx="10.5" cy="3.5" r=".8" fill="currentColor" opacity=".4"/><circle cx="3.5" cy="10.5" r="1.5" fill="currentColor" opacity=".8"/></svg>',
    plot: '<svg viewBox="0 0 14 14"><rect x="2" y="8" width="2.5" height="4" rx=".5" fill="none" stroke="currentColor" stroke-width="1.2"/><rect x="5.5" y="4" width="2.5" height="8" rx=".5" fill="none" stroke="currentColor" stroke-width="1.2"/><rect x="9" y="6" width="2.5" height="6" rx=".5" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>',
    amap: '<svg viewBox="0 0 14 14"><path d="M7 1a5 5 0 00-5 5c0 3.5 5 7 5 7s5-3.5 5-7a5 5 0 00-5-5zm0 7a2 2 0 110-4 2 2 0 010 4z" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>',
  };

  const SLASH_COMMANDS = [
    { name: 'buffer', label: '缓冲区分析', desc: '为图层创建指定距离的缓冲区', prompt: '为当前选中的图层创建 {距离} 米的缓冲区，结果加载到地图上' },
    { name: 'intersection', label: '空间相交', desc: '两个图层的相交分析', prompt: '对 {图层A} 和 {图层B} 做空间相交分析，结果加载到地图上' },
    { name: 'union', label: '空间合并', desc: '合并两个图层的几何', prompt: '合并 {图层A} 和 {图层B}，结果加载到地图上' },
    { name: 'difference', label: '空间差异', desc: '一个图层减去另一个图层', prompt: '用 {图层A} 减去 {图层B}，结果加载到地图上' },
    { name: 'centroid', label: '提取质心', desc: '提取图层的中心点', prompt: '提取 {图层名} 的质心/中心点，结果加载到地图上' },
    { name: 'simplify', label: '简化几何', desc: '简化图层几何，减少顶点数', prompt: '简化 {图层名} 的几何，简化容差设为 {容差}，结果加载到地图上' },
    { name: 'area', label: '计算面积', desc: '计算图层各要素的面积', prompt: '计算 {图层名} 每个要素的面积，结果用表格显示' },
    { name: 'length', label: '计算长度', desc: '计算线图层的长度', prompt: '计算 {图层名} 每个要素的长度，结果用表格显示' },
    { name: 'make_valid', label: '修复几何', desc: '修复无效的几何图形', prompt: '修复 {图层名} 中无效的几何图形，将修复后的结果加载到地图上' },
    { name: 'aoi', label: 'AOI 边界', desc: '提取地点建筑轮廓', prompt: '搜索 {地点名称} 的 AOI 建筑轮廓并提取' },
    { name: 'boundary', label: '行政边界', desc: '获取行政区划边界', prompt: '获取 {省/市/区} 的行政边界并加载到地图' },
    { name: 'heatmap', label: '热力图', desc: '从点数据生成热力图', prompt: '为 {图层名} 生成热力图' },
    { name: 'plot', label: '统计图表', desc: '生成数据统计图表', prompt: '对 {图层名} 的 {字段} 生成统计图表' },
    { name: 'amap', label: '高德', desc: '搜索POI/查天气/地址转坐标', prompt: '搜索 {关键词} 的 POI 数据，每页25条最多200条，结果加载到地图' },
  ];

  let _slashFiltered = [];      // 当前过滤后的列表
  let _slashIndex = -1;         // 选中索引
  let _slashActive = false;     // 菜单是否打开
  // ---- Skill Chip 标签系统 ----
  let _skillChips = [];         // [{name, label, prompt}]

  /**
   * 初始化聊天模块
   * 绑定 DOM 元素和事件
   */
  function init() {
    messagesContainer = document.getElementById('chatMessages');
    inputEl = document.getElementById('chatInput');
    sendBtn = document.getElementById('sendBtn');

    if (!messagesContainer) {
      console.warn('[GIS Chat] #chatMessages 不存在');
    }

    if (inputEl) {
      inputEl.addEventListener('keydown', (e) => {
        // Backspace 删除最后一个 chip
        if (e.key === 'Backspace' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
          if (inputEl.selectionStart === 0 && inputEl.selectionEnd === 0 && _skillChips.length > 0) {
            e.preventDefault();
            _removeLastChip();
            return;
          }
        }
        // 斜杠菜单打开时，Enter 交给 _handleSlashKeydown 处理选择命令
        if (_slashActive) return;
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          send();
        }
      });
      // 斜杠命令：输入/弹出菜单，↑↓选择，Enter/Tab确认，Esc取消
      inputEl.addEventListener('keydown', _handleSlashKeydown);
      inputEl.addEventListener('input', _handleSlashInput);
      // 点击外部关闭菜单
      document.addEventListener('click', _handleSlashClickOutside);
    }

    if (sendBtn) {
      sendBtn.addEventListener('click', function() { send(); });
    }

    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) {
      stopBtn.addEventListener('click', function() {
        window._aiRunning = false;
        _resetUIAfterStop();
        fetch(window.GIS.api.BASE_URL + '/api/cancel', { method: 'POST' }).catch(function(){});
        const loadingEl = document.getElementById('ai-loading-msg');
        if (loadingEl) {
          if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
          if (loadingEl._phaseTimer) clearTimeout(loadingEl._phaseTimer);
          loadingEl.remove();
        }
        addMessage('操作已取消', 'system');
      });
    }
  }

  // ---- 斜杠命令处理 ----
  function _getSlashMenu() { return document.getElementById('slashMenu'); }
  function _getSlashBody() { return document.getElementById('slashMenuBody'); }

  function _handleSlashInput() {
    if (!inputEl) return;
    const val = inputEl.value;
    const cursor = inputEl.selectionStart;
    // 获取光标前的文本，检测是否以 / 开头且没有空格（表示正在输入命令名）
    const textBefore = val.substring(0, cursor);
    if (/^\/([a-zA-Z]*)$/.test(textBefore)) {
      const query = textBefore.substring(1).toLowerCase();
      _slashFiltered = SLASH_COMMANDS.filter(function(c) {
        return c.name.indexOf(query) === 0 || c.label.indexOf(query) === 0;
      });
      _slashIndex = -1;
      if (_slashFiltered.length > 0) {
        _renderSlashMenu();
        _showSlashMenu();
        _slashActive = true;
        return;
      }
    }
    _hideSlashMenu();
    _slashActive = false;
  }

  function _handleSlashKeydown(e) {
    if (!_slashActive) {
      // 按 / 时触发命令面板
      if (e.key === '/' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
        // 等 input 事件触发 _handleSlashInput
        return;
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        _slashIndex = Math.min(_slashIndex + 1, _slashFiltered.length - 1);
        _highlightSlash();
        break;
      case 'ArrowUp':
        e.preventDefault();
        _slashIndex = Math.max(_slashIndex - 1, 0);
        _highlightSlash();
        break;
      case 'Enter':
      case 'Tab':
        e.preventDefault();
        if (_slashIndex >= 0 && _slashFiltered[_slashIndex]) {
          _applySlashCommand(_slashFiltered[_slashIndex]);
        } else if (_slashFiltered[0]) {
          _applySlashCommand(_slashFiltered[0]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        _hideSlashMenu();
        _slashActive = false;
        break;
    }
  }

  function _handleSlashClickOutside(e) {
    const menu = _getSlashMenu();
    if (!menu) return;
    const wrapper = inputEl && inputEl.closest('.chat-input-wrapper');
    if (menu.style.display !== 'none' && !menu.contains(e.target) && wrapper && !wrapper.contains(e.target)) {
      _hideSlashMenu();
      _slashActive = false;
    }
  }

  function _renderSlashMenu() {
    const body = _getSlashBody();
    if (!body) return;
    body.innerHTML = _slashFiltered.map(function(c, i) {
      const iconSvg = SLASH_ICONS[c.name] || '';
      return '<div class="slash-item" data-index="' + i + '">' +
        '<div class="slash-item-left">' +
          '<span class="slash-item-icon">' + iconSvg + '</span>' +
          '<span class="slash-item-name">' + c.label + '</span>' +
          '<span class="slash-item-hint">/' + c.name + '</span>' +
        '</div>' +
        '<span class="slash-item-desc">' + c.desc + '</span>' +
      '</div>';
    }).join('');
    body.querySelectorAll('.slash-item').forEach(function(el) {
      el.addEventListener('click', function() {
        const idx = parseInt(this.dataset.index, 10);
        if (_slashFiltered[idx]) _applySlashCommand(_slashFiltered[idx]);
      });
    });
  }

  function _highlightSlash() {
    const body = _getSlashBody();
    if (!body) return;
    body.querySelectorAll('.slash-item').forEach(function(el, i) {
      el.classList.toggle('is-selected', i === _slashIndex);
    });
    const sel = body.querySelector('.slash-item.is-selected');
    if (sel) sel.scrollIntoView({ block: 'nearest' });
  }

  function _showSlashMenu() {
    const menu = _getSlashMenu();
    if (menu) menu.style.display = '';
  }

  function _hideSlashMenu() {
    const menu = _getSlashMenu();
    if (menu) menu.style.display = 'none';
  }

  function _applySlashCommand(cmd) {
    _hideSlashMenu();
    _slashActive = false;
    if (!inputEl) return;
    // 移除输入框中的 /命令名（只保留用户已输入的其他文字）
    inputEl.value = inputEl.value.replace(/^\/[a-zA-Z]*/, '');
    _addChip(cmd);
  }

  // ===== Skill Chip 管理 =====
  function _addChip(cmd) {
    // 不重复添加同名 chip
    if (_skillChips.some(function(c) { return c.name === cmd.name; })) return;
    _skillChips.push({name: cmd.name, label: cmd.label, prompt: cmd.prompt});
    _renderChips();
    if (inputEl) inputEl.focus();
  }

  function _removeChip(index) {
    if (index < 0 || index >= _skillChips.length) return;
    const chip = _skillChips[index];
    // 从 textarea 中移除这个 chip 对应的 prompt 文字
    if (inputEl) {
      const text = inputEl.value;
      const promptIndex = text.indexOf(chip.prompt);
      if (promptIndex >= 0) {
        let before = text.substring(0, promptIndex);
        const after = text.substring(promptIndex + chip.prompt.length);
        // 如果前面有换行符，去掉它
        if (before.endsWith('\n')) before = before.slice(0, -1);
        inputEl.value = before + after;
      }
    }
    _skillChips.splice(index, 1);
    _renderChips();
  }

  function _removeLastChip() {
    if (_skillChips.length === 0) return;
    _removeChip(_skillChips.length - 1);
    if (inputEl) inputEl.focus();
  }

  function _renderChips() {
    const container = document.getElementById('chipContainer');
    if (!container) return;
    container.innerHTML = '';
    if (_skillChips.length === 0) {
      container.style.display = 'none';
      let wrapper = container.closest('.chat-input-wrapper');
      if (wrapper) wrapper.classList.remove('has-chips');
      return;
    }
    container.style.display = 'flex';
    let wrapper = container.closest('.chat-input-wrapper');
    if (wrapper) wrapper.classList.add('has-chips');
    _skillChips.forEach(function(chip, i) {
      const el = document.createElement('span');
      el.className = 'skill-chip';
      el.innerHTML = '/<span class="chip-name">' + chip.name + '</span><span class="chip-close" data-i="' + i + '">✕</span>';
      el.querySelector('.chip-close').addEventListener('click', function(e) {
        e.stopPropagation();
        _removeChip(i);
        if (inputEl) inputEl.focus();
      });
      container.appendChild(el);
    });
  }

  function _resetUIAfterStop() {
    if (!inputEl) return;
    inputEl.placeholder = '输入指令或查询...';
    inputEl.disabled = false;
    if (sendBtn) { sendBtn.disabled = false; sendBtn.style.opacity = '1'; }
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) stopBtn.style.display = 'none';
    const modelBar = document.querySelector('.chat-input-model-bar');
    if (modelBar) modelBar.classList.remove('is-disabled');
    window._aiRunning = false;
    // 恢复右键菜单
    document.querySelectorAll('.context-menu-item').forEach(function(el) {
      if (el.getAttribute('data-action') !== 'copy-coords') el.classList.remove('is-disabled');
    });
  }

  async function send(text, displayOpt) {
    // 如果传了参数就用参数，否则从输入框读取
    if (text === undefined) {
      text = inputEl ? inputEl.value.trim() : '';
    }
    if (!text) return;
    // 防止快速双击/重复点击，避免创建重复计时器和加载气泡
    if (window._aiRunning) return;

    // 解析第二个参数：字符串=displayText，对象={displayText, badge, provider}
    const displayText = typeof displayOpt === 'string' ? displayOpt : (displayOpt ? displayOpt.displayText : null);
    const badge = displayOpt && displayOpt.badge ? displayOpt.badge : null;
    const providerOverride = displayOpt && displayOpt.provider ? displayOpt.provider : null;

    // 检查当前选中的模型是否已配置 API Key（优先用 providerOverride）
    const selModel = document.getElementById('modelSelector');
    const curProvider = providerOverride || (selModel ? selModel.value : 'deepseek');
    const hasKey = (curProvider === 'glm' || curProvider === 'glm-routed') ? window.GIS.api.getGLMApiKey() : window.GIS.api.getApiKey();
    if (!hasKey) {
        const modelName = (curProvider === 'glm-routed' || curProvider === 'glm') ? 'GLM-4.7-Flash+' : 'DeepSeek V4 Flash+';
        addMessage(modelName + ' 未配置 API Key，请点击齿轮按钮设置', 'system');
      // 恢复输入框（placeholder 还没被改过，不需要还原）
      inputEl.disabled = false;
      sendBtn.disabled = false;
      sendBtn.style.opacity = '1';
      const modelBar2 = document.querySelector('.chat-input-model-bar');
      if (modelBar2) modelBar2.classList.remove('is-disabled');
      return;
    }

    // 捕获当前 chips 显示在用户消息气泡中
    var chipsSnapshot = _skillChips.slice();
    // 渲染用户消息（如果传了 displayText 就显示它）
    var msgOpts = badge ? {badge: badge} : {};
    if (chipsSnapshot.length > 0) msgOpts.chips = chipsSnapshot;
    addMessage(displayText || text, 'user', msgOpts);
    // 只有从输入框发送时才清空输入框
    if (inputEl && arguments.length === 0) {
      inputEl.value = '';
    }
    const el = document.getElementsByClassName('chat-messages-empty')[0];
    if (el) {
      el.style.display = 'none';
    }
    // 显示加载状态：输入框显示提示文字，禁用按钮和模型选择
    inputEl.placeholder = 'AI正在回复中...';
    inputEl.disabled = true;
    sendBtn.disabled = true;
    sendBtn.style.opacity = '0.5';
    // 禁用模型选择器（请求中不允许换模型）
    const modelBar = document.querySelector('.chat-input-model-bar');
    if (modelBar) modelBar.classList.add('is-disabled');
    // 标记AI运行状态，显示停止按钮，禁用右键
    window._aiRunning = true;
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) stopBtn.style.display = '';
    document.querySelectorAll('.context-menu-item').forEach(function(el) {
      if (el.getAttribute('data-action') !== 'copy-coords') el.classList.add('is-disabled');
    });

    // 获取当前模型显示名（优先用 providerOverride）
    const modelDisplayEl = document.getElementById('modelSelectValue');
    let modelDisplayName = modelDisplayEl ? modelDisplayEl.textContent : 'AI';
    if (providerOverride === 'deepseek-routed') modelDisplayName = 'DeepSeek V4 Flash+'; else if (providerOverride === 'glm-routed') modelDisplayName = 'GLM-4.7-Flash+';
    else if (providerOverride === 'deepseek') modelDisplayName = 'DeepSeek V4 Flash';
    

    // 添加"模型名 思考中..."占位气泡，让用户知道 AI 正在处理
    const isRouted = (providerOverride === 'deepseek-routed' || providerOverride === 'glm-routed');
    const loadingMsg = addMessage(modelDisplayName + ' 思考中...', 'ai', { noMarkdown: true });
    loadingMsg.id = 'ai-loading-msg';

    // DS+ 模式：先显示 GLM 路由阶段，再切换到执行阶段
    if (isRouted) {
      const loadingContent = loadingMsg.querySelector('.message-bubble > div');
      if (loadingContent) {
        if (providerOverride === 'glm-routed') loadingContent.textContent = 'GLM-4.7-Flash+ 路由分析中...';
        else loadingContent.textContent = 'DeepSeek V4 Flash+ GLM 路由分析中...';
      }
    }

    // 给气泡文本加流光 scan 动画
    const loadingContent = loadingMsg.querySelector('.message-bubble > div');
    if (loadingContent) loadingContent.classList.add('shimmer-loading-text');

    // 添加翻牌计时器（实时显示 AI 思考耗时），另起一行
    const timerEl = createFlipTimer();
    const timerWrapper = document.createElement('div');
    timerWrapper.style.cssText = 'margin-top:6px;';
    timerWrapper.appendChild(timerEl);
    const loadingBubble = loadingMsg.querySelector('.message-bubble');
    if (loadingBubble) loadingBubble.appendChild(timerWrapper);

    const startTime = Date.now();
    // DS+ 模式：1.5 秒后从"GLM 路由中"切换到"执行中"
    let phaseTimer = null;
    if (isRouted) {
      phaseTimer = setTimeout(function() {
        const el = document.getElementById('ai-loading-msg');
        if (el) {
          const c = el.querySelector('.message-bubble > div');
          if (providerOverride === 'glm-routed') c.textContent = 'GLM-4.7-Flash+ 执行中...';
          else c.textContent = 'DeepSeek V4 Flash+ 执行中...';
        }
      }, 1500);
    }
    loadingMsg._phaseTimer = phaseTimer;
    const timerInterval = setInterval(function() {
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      updateFlipTimer(timerEl, elapsed);
    }, 1000);
    updateFlipTimer(timerEl, 0);
    loadingMsg._timerInterval = timerInterval;

    try {
      // 读取当前选择的模型（优先用 providerOverride）
      const modelSelector = document.getElementById('modelSelector');
      const rawProvider = providerOverride || (modelSelector ? modelSelector.value : 'deepseek'); const provider = rawProvider;
      const forceSkills = _skillChips.map(function(c) { return CHIP_TO_SKILL[c.name]; }).filter(Boolean);
      // 解析 displayOpt 中的任务信息
      var taskId = displayOpt && displayOpt._taskId ? displayOpt._taskId : null;
      var taskProvider = displayOpt && displayOpt.provider ? displayOpt.provider : curProvider;
      if (!taskId) {
        var inputLayers = (window.GIS.layers && typeof window.GIS.layers.getLayers === 'function')
          ? window.GIS.layers.getLayers() : [];
        var task = window.GIS.task && window.GIS.task.createTask(text, taskProvider, inputLayers);
        if (task) taskId = task.id;
      }
      // 更新任务状态为规划中
      if (taskId && window.GIS.task) {
        window.GIS.task.updateTask(taskId, { status: 'planning' });
      }

      const result = await GIS.api.chat(text, 'default', provider, forceSkills);
      // 发送后清除 chip 标签（已消费）
      _skillChips = [];
      _renderChips();
      // 移除"思考中"占位气泡
      const loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        if (loadingEl._phaseTimer) clearTimeout(loadingEl._phaseTimer);
        loadingEl.remove();
      }

      // 更新任务卡状态
      if (taskId && window.GIS.task) {
        var taskUpdate = { status: 'success' };
        // 收集结果图层信息
        var resultLayers = [];
        if (result.layers && result.layers.length > 0) {
          result.layers.forEach(function(l) {
            resultLayers.push({ name: l.name || '分析结果', geojson: l.geojson || l, layerId: 'task_result_' + Date.now() });
          });
        } else if (result.geojson && result.layerName) {
          resultLayers.push({ name: result.layerName, geojson: result.geojson, layerId: 'task_result_' + Date.now() });
        }
        taskUpdate.resultLayers = resultLayers;

        // 提取 AI 回复中的代码块作为执行代码
        var codeMatch = result.response && result.response.match(/```(?:python)?\s*([\s\S]*?)```/);
        if (codeMatch) {
          taskUpdate.code = codeMatch[1].trim();
        }
        // 提取前 300 字作为摘要
        var plainText = result.response ? result.response.replace(/<[^>]+>/g, '').replace(/```[\s\S]*?```/g, '') : '';
        taskUpdate.resultSummary = plainText.slice(0, 300) + (plainText.length > 300 ? '...' : '');
        taskUpdate.completedAt = Date.now();
        window.GIS.task.updateTask(taskId, taskUpdate);
      }

      // 显示 AI 的文字回复
      const msgEl = addMessage(result.response, 'ai');

      // 如果有 AI 生成的图表图片，追加到最后一条回复下方
      if (result.images && result.images.length > 0) {
        // 如果上一步有返回 msgEl 就用它，否则新建容器
        const imgContainer = document.createElement('div');
        imgContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;margin-left:32px;';
        // 通用下载函数（fetch + Blob，解决跨域下载问题）
        function downloadFile(url, filename) {
          fetch(url).then(function(res) { return res.blob(); }).then(function(blob) {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(a.href);
          }).catch(function(e) { console.warn('下载失败:', e); });
        }

        result.images.forEach(function(item) {
          // 兼容新旧格式：item 可能是字符串（旧）或对象（新）
          const imgUrl = typeof item === 'string' ? item : (item.url || '');
          const imgType = typeof item === 'string' ? (imgUrl.match(/\.html?$/i) ? 'html' : 'png') : (item.type || 'png');
          const htmlContent = typeof item === 'string' ? null : (item.content || null);
          const fileName = imgUrl.split('/').pop() || 'file';
          const baseUrl = (window.GIS && window.GIS.api && window.GIS.api.BASE_URL) || 'http://localhost:8000';
          const fullUrl = baseUrl + imgUrl;

          if (imgType === 'html') {
            const htmlWrap = document.createElement('div');
            htmlWrap.style.cssText = 'border:1px solid var(--ui-gray-200);border-radius:4px;overflow:hidden;width:100%;';
            const iframe = document.createElement('iframe');
            iframe.style.cssText = 'width:100%;height:420px;border:none;display:block;';
            iframe.title = '交互式地图';
            // 优先用 srcdoc（内联 HTML，不落磁盘），其次用 src
            if (htmlContent) {
              iframe.srcdoc = htmlContent;
            } else {
              iframe.src = fullUrl;
            }
            htmlWrap.appendChild(iframe);
            const toolBar = document.createElement('div');
            toolBar.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;border-top:1px solid var(--ui-gray-200);background:var(--surface-container-low);font-size:12px;';
            toolBar.innerHTML =
              '<span style="flex:1;color:var(--ui-gray-400);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + fileName + '</span>' +
              '<a href="' + fullUrl + '" target="_blank" style="padding:3px 8px;border:1px solid var(--ui-gray-200);border-radius:3px;text-decoration:none;color:var(--ui-gray-900);">新标签打开</a>';
            // 下载按钮（用 fetch+blob，不会跳转）
            const dlHtmlBtn = document.createElement('button');
            dlHtmlBtn.textContent = '下载';
            dlHtmlBtn.style.cssText = 'padding:3px 8px;background:var(--ui-gray-900);color:var(--ui-white);border:none;border-radius:3px;cursor:pointer;font-size:12px;';
            dlHtmlBtn.addEventListener('click', function() { downloadFile(fullUrl, fileName); });
            toolBar.appendChild(dlHtmlBtn);
            htmlWrap.appendChild(toolBar);
            imgContainer.appendChild(htmlWrap);
          } else {
            // 图片文件
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'position:relative;display:inline-block;';
            const img = document.createElement('img');
            img.src = fullUrl;
            img.style.cssText = 'max-width:100%;max-height:300px;border-radius:4px;border:1px solid var(--ui-gray-200);cursor:pointer;display:block;';
            img.title = '点击放大';
            img.addEventListener('click', function() { window.open(fullUrl); });
            wrapper.appendChild(img);
            // 下载按钮（右上角悬浮，用 fetch+blob）
            const dlImgBtn = document.createElement('button');
            dlImgBtn.title = '下载图片';
            dlImgBtn.innerHTML =
              '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>' +
              '</svg>';
            dlImgBtn.style.cssText = 'position:absolute;top:4px;right:4px;width:28px;height:28px;background:rgba(255,255,255,0.9);border:1px solid var(--ui-gray-200);border-radius:4px;display:flex;align-items:center;justify-content:center;color:var(--ui-gray-900);opacity:0;transition:opacity 0.15s;cursor:pointer;padding:0;';
            dlImgBtn.addEventListener('click', function(e) { e.stopPropagation(); downloadFile(fullUrl, fileName); });
            wrapper.addEventListener('mouseenter', function() { dlImgBtn.style.opacity = '1'; });
            wrapper.addEventListener('mouseleave', function() { dlImgBtn.style.opacity = '0'; });
            wrapper.appendChild(dlImgBtn);
            imgContainer.appendChild(wrapper);
          }
        });
        // 如果 msgEl 存在，追加到它的气泡里
        if (msgEl) {
          const bubble = msgEl.querySelector('.message-bubble');
          if (bubble) bubble.appendChild(imgContainer);
        } else {
          // 否则单独插到聊天容器
          document.getElementById('chatMessages').appendChild(imgContainer);
        }
      }

      // 如果 AI 清空了图层，同步清空前端地图和面板
      if (result.clear_layers) {
        console.log('[GIS Chat] 收到清空图层指令');
        if (window.GIS.layers) {
          const allLayers = window.GIS.layers.getLayers();
          allLayers.forEach(function(l) {
            if (l.layer_id) window.GIS.layers.removeLayer(l.layer_id);
          });
        }
        addMessage('已清空所有图层', 'system');
      }

      // 如果有待处理的 AOI 候选列表，显示在聊天框供点击选择
      if (result.pending_suggestions && result.pending_suggestions.length > 0) {
        setTimeout(() => {
          if (window.GIS.aoi && typeof window.GIS.aoi.showSuggestions === 'function') {
            window.GIS.aoi.showSuggestions(result.pending_suggestions);
          }
        }, 200);
      }

      // 如果 AI 生成了多个 GeoJSON 图层，逐个加载到地图
      if (result.layers && result.layers.length > 0) {
        console.log('[GIS Chat] 收到多个 GeoJSON 图层:', result.layers.length);

        (function loadMultiLayers(attempt) {
          if (!GIS.map || !GIS.map.loadGeoJSON || !GIS.layers || !GIS.layers.addLayer) {
            if (attempt < 10) {
              setTimeout(function() { loadMultiLayers(attempt + 1); }, 300);
              return;
            }
            console.warn('[GIS Chat] 地图模块未就绪，无法加载多个图层');
            return;
          }

          result.layers.forEach(function(layer, idx) {
            const layerId = 'ai_' + Date.now() + '_' + idx;
            const layerName = layer.name || '图层' + (idx + 1);
            const uniqueName = layerName + '_' + Date.now() + '_' + idx;
            const geojson = layer.geojson || layer;
            const geoType = geojson.type === 'FeatureCollection'
              ? ((geojson.features && geojson.features[0] && geojson.features[0].geometry && geojson.features[0].geometry.type) || '未知')
              : (geojson.geometry && geojson.geometry.type || '未知');

            GIS.map.loadGeoJSON(geojson, uniqueName, layer.style || {});
            GIS.layers.addLayer({
              layer_id: layerId,
              filename: uniqueName,
              geometry_type: geoType,
              crs: 'WGS-84',
              geojson: geojson,
              visible: true,
              source: 'ai',
            });
          });
        })(0);
      }

      // 如果 AI 生成了单个 GeoJSON 数据，自动加载到地图和图层（兼容旧格式）
      else if (result.geojson && result.layerName) {
        console.log('[GIS Chat] 收到 GeoJSON 图层:', result.layerName,
          '要素数:', result.geojson.type === 'FeatureCollection'
            ? (result.geojson.features || []).length : 1);

        // 等待地图和图层模块就绪（有时模块初始化有延迟）
        (function loadGeoJSONWithRetry(attempt) {
          if (!GIS.map || !GIS.map.loadGeoJSON || !GIS.layers || !GIS.layers.addLayer) {
            if (attempt < 10) {
              setTimeout(function() { loadGeoJSONWithRetry(attempt + 1); }, 300);
              return;
            }
            console.warn('[GIS Chat] 地图模块未就绪，无法加载图层:', result.layerName);
            return;
          }

          const layerId = 'ai_' + Date.now();
          const uniqueName = result.layerName + '_' + Date.now();
          const geoType = result.geojson.type === 'FeatureCollection'
            ? ((result.geojson.features && result.geojson.features[0] && result.geojson.features[0].geometry && result.geojson.features[0].geometry.type) || '未知')
            : (result.geojson.geometry && result.geojson.geometry.type || '未知');

          // 1. 加载到地图
          GIS.map.loadGeoJSON(result.geojson, uniqueName);

          // 2. 添加到图层面板
          GIS.layers.addLayer({
            layer_id: layerId,
            filename: uniqueName,
            geometry_type: geoType,
            crs: 'WGS-84',
            geojson: result.geojson,
            visible: true,
            source: 'ai',
          });
        })(0);
      }

      // 热力图数据
      if (result.heatmap && result.heatmap.points && result.heatmap.points.length > 0) {
        (function loadHeatmapWithRetry(attempt) {
          if (!GIS.map || !GIS.map.loadHeatmap) {
            if (attempt < 10) { setTimeout(function() { loadHeatmapWithRetry(attempt + 1); }, 300); return; }
            return;
          }
          const uniqueName = (result.heatmap.name || 'heatmap') + '_' + Date.now();
          GIS.map.loadHeatmap(result.heatmap.points, uniqueName, result.heatmap.options || {});
          if (window.GIS.layers && window.GIS.layers.addLayer) {
            GIS.layers.addLayer({
              layer_id: 'heat_' + Date.now(),
              filename: uniqueName,
              geometry_type: '热力',
              crs: 'WGS-84',
              geojson: null,
              visible: true,
              source: 'ai',
            });
          }
        })(0);
      }
    } catch (err) {
      // 移除"思考中"占位气泡
      const loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        if (loadingEl._phaseTimer) clearTimeout(loadingEl._phaseTimer);
        loadingEl.remove();
      }
      // 更新任务状态为失败
      if (taskId && window.GIS.task) {
        window.GIS.task.updateTask(taskId, { status: 'failed', error: err.message, completedAt: Date.now() });
      }
      // 恢复默认 placeholder（防止并发发送覆盖）
      inputEl.placeholder = '输入指令或查询...';
    } finally {
      _resetUIAfterStop();
      inputEl.placeholder = '输入指令或查询...';
      inputEl.focus();
      // 重新启用模型选择
      const modelBar = document.querySelector('.chat-input-model-bar');
      if (modelBar) modelBar.classList.remove('is-disabled');
    }
  }

  function addMessage(text, type, options) {
    if (!messagesContainer) return null;
    type = type || 'ai';
    options = options || {};

    // 系统消息：居中灰色小字条
    if (type === 'system') {
      const row = document.createElement('div');
      const isHidden = options && options.hidden;
      row.style.cssText = isHidden
        ? 'display:none;'
        : 'display:flex;justify-content:center;max-width:100%;';
      const bubble = document.createElement('div');
      bubble.style.cssText = 'font-size:12px;color:var(--ui-gray-400);background:var(--ui-gray-100);padding:4px 12px;border-radius:10px;text-align:center;';
      bubble.innerHTML = text;
      row.appendChild(bubble);
      messagesContainer.appendChild(row);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      return row;
    }

    const row = document.createElement('div');
    row.className = 'message' + (type === 'user' ? ' message-user' : '');
    row.style.opacity = '0';
    row.style.transition = 'opacity 0.2s';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar' + (type === 'user' ? ' message-avatar-user' : ' message-avatar-ai');
    avatar.innerHTML = type === 'user'
      ? '<svg class="svg-icon-sm"><use href="assets/icons.svg#icon-user"/></svg>'
      : '<svg class="svg-icon-sm"><use href="assets/icons.svg#icon-ai"/></svg>';
    row.appendChild(avatar);

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble' + (type === 'user' ? ' message-bubble-user' : ' message-bubble-ai');

    const content = document.createElement('div');
    // AI 消息渲染 Markdown（跳过加载气泡，避免 <p> 包裹破坏流光动画）
    if (type === 'ai' && !options.noMarkdown && typeof marked !== 'undefined') {
      content.innerHTML = marked.parse(text, { breaks: true, gfm: true, renderer: _linkRenderer });
    } else {
      content.innerHTML = text;
    }
    bubble.appendChild(content);

    // 用户消息：在气泡底部显示 skill chip 标签
    if (type === 'user' && options.chips && options.chips.length > 0) {
      var chipsRow = document.createElement('div');
      chipsRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;';
      options.chips.forEach(function(chip) {
        var chipEl = document.createElement('div');
        chipEl.style.cssText = 'display:inline-flex;align-items:center;padding:0 8px;height:22px;border-radius:11px;background:var(--primary-container,#1c1b1b);color:var(--on-primary,#fff);font-size:11px;font-weight:600;line-height:1;user-select:none;';
        chipEl.textContent = '/' + chip.name;
        chipsRow.appendChild(chipEl);
      });
      bubble.appendChild(chipsRow);
    }

    if (options.code) {
      const codeBlock = document.createElement('div');
      codeBlock.className = 'message-code-block';
      codeBlock.textContent = options.code;
      bubble.appendChild(codeBlock);
    }

    // AI 消息右下角复制按钮（跳过加载气泡）
    if (type === 'ai' && !options.noMarkdown) {
      const copyBtn = document.createElement('button');
      copyBtn.className = 'btn-copy-ai';
      copyBtn.title = '复制回复';
      copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      copyBtn.addEventListener('click', function() {
        // 取纯文本（跳过 markdown HTML 标签）
        const plainText = content.textContent || content.innerText || text;
        navigator.clipboard.writeText(plainText).then(function() {
          copyBtn.classList.add('copied');
          copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
          setTimeout(function() {
            copyBtn.classList.remove('copied');
            copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
          }, 2000);
        }).catch(function() {
          // fallback: 用 textarea 复制
          const ta = document.createElement('textarea');
          ta.value = plainText;
          ta.style.position = 'fixed'; ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand('copy'); copyBtn.classList.add('copied'); } catch(e) {}
          document.body.removeChild(ta);
        });
      });
      bubble.appendChild(copyBtn);
    }

    row.appendChild(bubble);
    messagesContainer.appendChild(row);

    requestAnimationFrame(function() { row.style.opacity = '1'; });
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return row;
  }

  function clear() {
    if (messagesContainer) messagesContainer.innerHTML = '';
  }

  // ──────────────────────────────────────────────
  //  翻牌计时器（AI 思考耗时）
  // ──────────────────────────────────────────────

  /**
   * 创建一个翻牌计时器 DOM
   * 格式：HH:MM:SS，每个数字都是独立的翻牌单元
   */
  function createFlipTimer() {
    const container = document.createElement('span');
    container.className = 'flip-timer';

    // 存储当前显示的 6 个数字值 [h1,h2,m1,m2,s1,s2]
    container._current = [0, 0, 0, 0, 0, 0];

    // 布局：HH : MM : SS
    const layout = [
      { type: 'digit' }, { type: 'digit' },
      { type: 'sep', char: ':' },
      { type: 'digit' }, { type: 'digit' },
      { type: 'sep', char: ':' },
      { type: 'digit' }, { type: 'digit' }
    ];

    container._digits = [];

    layout.forEach(function(item) {
      if (item.type === 'sep') {
        const sep = document.createElement('span');
        sep.className = 't-sep';
        sep.textContent = item.char;
        container.appendChild(sep);
      } else {
        const digitEl = document.createElement('span');
        digitEl.className = 't-digit';
        digitEl.innerHTML = '<span class="t-d-main">0</span>';
        container.appendChild(digitEl);
        container._digits.push(digitEl);
      }
    });

    return container;
  }

  /**
   * 更新计时器显示
   * @param {HTMLElement} timerEl - 计时器容器
   * @param {number} elapsed - 已过秒数
   */
  function updateFlipTimer(timerEl, elapsed) {
    const h = Math.floor(elapsed / 3600);
    const m = Math.floor((elapsed % 3600) / 60);
    const s = elapsed % 60;

    // 拆成 6 个单独的数字
    const timeDigits = [
      Math.floor(h / 10) % 10, h % 10,
      Math.floor(m / 10),      m % 10,
      Math.floor(s / 10),      s % 10
    ];

    const current = timerEl._current;
    const digits  = timerEl._digits;

    for (let i = 0; i < 6; i++) {
      if (current[i] !== timeDigits[i]) {
        // 方向规则：
        //   第 6 位（秒个位 i=5）是主动计时的 → 向上翻
        //   其余位都是因为进位才触发变化 → 向下翻
        const direction = (i === 5) ? 'up' : 'down';
        animateDigitFlip(digits[i], timeDigits[i], direction);
        current[i] = timeDigits[i];
      }
    }
  }

  /**
   * 单个数字翻牌动画
   * @param {HTMLElement} digitEl  - 数字容器 .t-digit
   * @param {number|string} newVal - 新数字
   * @param {string} dir           - "up" 向上 / "down" 向下
   */
  function animateDigitFlip(digitEl, newVal, dir) {
    const main = digitEl.querySelector('.t-d-main');
    const oldVal = main.textContent;
    if (oldVal === String(newVal)) return;

    const ANIM_MS = 260;

    // 旧数字飞出
    const outEl = document.createElement('span');
    outEl.className = 't-d-float';
    outEl.textContent = oldVal;
    outEl.style.animation = (dir === 'up' ? 't-up-out' : 't-down-out') + ' ' + ANIM_MS + 'ms ease forwards';

    // 新数字飞入
    const inEl = document.createElement('span');
    inEl.className = 't-d-float';
    inEl.textContent = newVal;
    inEl.style.animation = (dir === 'up' ? 't-up-in' : 't-down-in') + ' ' + ANIM_MS + 'ms ease forwards';

    // 动画期间隐藏主文字
    main.style.opacity = '0';

    digitEl.appendChild(outEl);
    digitEl.appendChild(inEl);

    // 动画结束后还原
    setTimeout(function() {
      main.textContent = newVal;
      main.style.opacity = '1';
      if (outEl.parentNode) outEl.remove();
      if (inEl.parentNode) inEl.remove();
    }, ANIM_MS + 40);
  }

  GIS.chat = { init, send, addMessage, clear, sendMessage: send };
})();
