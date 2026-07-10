/**
 * ============================================
 *  GIS AI WorkTable — 聊天模块
 *  消息渲染、输入框绑定、发送逻辑
 * ============================================
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';
//将GIS命名空间赋值给常量GIS，相当于全局变量
  const GIS = window.GIS;

  /** @type {HTMLElement} */
  let messagesContainer = null;
  let inputEl = null;
  let sendBtn = null;

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
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          send();
        }
      });
    }

    if (sendBtn) {
      sendBtn.addEventListener('click', function() { send(); });
    }

  }

  async function send(text) {
    // 如果传了参数就用参数，否则从输入框读取
    if (text === undefined) {
      text = inputEl ? inputEl.value.trim() : '';
    }
    if (!text) return;
    // 渲染用户消息
    addMessage(text, 'user');
    // 只有从输入框发送时才清空输入框
    if (inputEl && arguments.length === 0) {
      inputEl.value = '';
    }
    var el = document.getElementsByClassName('chat-messages-empty')[0];
    if (el) {
      el.style.display = 'none';
    }
    // 显示加载状态：输入框显示提示文字，禁用按钮
    const originalPlaceholder = inputEl.placeholder;
    inputEl.placeholder = 'AI正在回复中...';
    inputEl.disabled = true;
    sendBtn.disabled = true;
    sendBtn.style.opacity = '0.5';

    // 添加一个"思考中"的占位气泡，让用户知道 AI 正在处理
    var loadingMsg = addMessage('思考中...', 'ai');
    loadingMsg.id = 'ai-loading-msg';

    // 添加翻牌计时器（实时显示 AI 思考耗时）
    var timerEl = createFlipTimer();
    var loadingBubble = loadingMsg.querySelector('.message-bubble');
    if (loadingBubble) loadingBubble.appendChild(timerEl);

    var startTime = Date.now();
    var timerInterval = setInterval(function() {
      var elapsed = Math.floor((Date.now() - startTime) / 1000);
      updateFlipTimer(timerEl, elapsed);
    }, 1000);
    updateFlipTimer(timerEl, 0);
    loadingMsg._timerInterval = timerInterval;

    try {
      // 发送到后端 API，等待回复
      const result = await GIS.api.chat(text);
      // 移除"思考中"占位气泡
      var loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        loadingEl.remove();
      }

      addMessage(result.response, 'ai');

      // 如果 AI 清空了图层，同步清空前端地图和面板
      if (result.clear_layers) {
        console.log('[GIS Chat] 收到清空图层指令');
        if (window.GIS.layers) {
          var allLayers = window.GIS.layers.getLayers();
          allLayers.forEach(function(l) {
            if (l.layer_id) window.GIS.layers.removeLayer(l.layer_id);
          });
        }
        // 清空处理结果面板
        var ftb = document.getElementById('filesTbody');
        var ft = document.getElementById('filesTable');
        var fe = document.getElementById('filesEmpty');
        if (ftb) ftb.innerHTML = '';
        if (ft) ft.style.display = 'none';
        if (fe) fe.style.display = 'flex';
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
            var layerId = 'ai_' + Date.now() + '_' + idx;
            var layerName = layer.name || '图层' + (idx + 1);
            var uniqueName = layerName + '_' + Date.now() + '_' + idx;
            var geojson = layer.geojson || layer;
            var geoType = geojson.type === 'FeatureCollection'
              ? ((geojson.features && geojson.features[0] && geojson.features[0].geometry && geojson.features[0].geometry.type) || '未知')
              : (geojson.geometry && geojson.geometry.type || '未知');

            GIS.map.loadGeoJSON(geojson, uniqueName);
            GIS.layers.addLayer({
              layer_id: layerId,
              filename: uniqueName,
              geometry_type: geoType,
              crs: 'WGS-84',
              geojson: geojson,
              visible: true,
            });

            // 添加到处理结果面板
            var filesTbody = document.getElementById('filesTbody');
            var filesTable = document.getElementById('filesTable');
            var filesEmpty = document.getElementById('filesEmpty');
            if (filesTbody && filesTable && filesEmpty) {
              filesEmpty.style.display = 'none';
              filesTable.style.display = '';
              var row = document.createElement('tr');
              row.draggable = false;
              row.innerHTML = [
                '<td></td>',
                '<td><span class="layer-name">', layerName, '.geojson</span></td>',
                '<td style="text-align:right;">',
                  '<button class="layer-action-btn" onclick="downloadGeoJSON(\'', layerId, '\')" title="下载">',
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">',
                      '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
                    '</svg>',
                  '</button>',
                '</td>',
              ].join('');
              filesTbody.appendChild(row);
            }
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

          var layerId = 'ai_' + Date.now();
          var uniqueName = result.layerName + '_' + Date.now();
          var geoType = result.geojson.type === 'FeatureCollection'
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
          });

          // 3. 添加到处理结果面板
          var filesTbody = document.getElementById('filesTbody');
          var filesTable = document.getElementById('filesTable');
          var filesEmpty = document.getElementById('filesEmpty');
          if (filesTbody && filesTable && filesEmpty) {
            filesEmpty.style.display = 'none';
            filesTable.style.display = '';
            var row = document.createElement('tr');
            row.draggable = false;
            row.innerHTML = [
              '<td></td>',
              '<td><span class="layer-name">', result.layerName, '.geojson</span></td>',
              '<td style="text-align:right;">',
                '<button class="layer-action-btn" onclick="downloadGeoJSON(\'', layerId, '\')" title="下载">',
                  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">',
                    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
                  '</svg>',
                '</button>',
              '</td>',
            ].join('');
            filesTbody.appendChild(row);
          }
        })(0); // 从第 0 次尝试开始
      }
    } catch (err) {
      // 移除"思考中"占位气泡
      var loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        loadingEl.remove();
      }
      addMessage('请求失败: ' + err.message, 'system');
    } finally {
      // 恢复输入状态
      inputEl.placeholder = originalPlaceholder;
      inputEl.disabled = false;
      sendBtn.disabled = false;
      sendBtn.style.opacity = '1';
      inputEl.focus();
    }
  }

  function addMessage(text, type, options) {
    if (!messagesContainer) return null;
    type = type || 'ai';
    options = options || {};

    // 系统消息：居中灰色小字条
    if (type === 'system') {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:center;max-width:100%;';
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
    content.innerHTML = text;
    bubble.appendChild(content);

    if (options.code) {
      const codeBlock = document.createElement('div');
      codeBlock.className = 'message-code-block';
      codeBlock.textContent = options.code;
      bubble.appendChild(codeBlock);
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
    var container = document.createElement('span');
    container.className = 'flip-timer';

    // 存储当前显示的 6 个数字值 [h1,h2,m1,m2,s1,s2]
    container._current = [0, 0, 0, 0, 0, 0];

    // 布局：HH : MM : SS
    var layout = [
      { type: 'digit' }, { type: 'digit' },
      { type: 'sep', char: ':' },
      { type: 'digit' }, { type: 'digit' },
      { type: 'sep', char: ':' },
      { type: 'digit' }, { type: 'digit' }
    ];

    container._digits = [];

    layout.forEach(function(item) {
      if (item.type === 'sep') {
        var sep = document.createElement('span');
        sep.className = 't-sep';
        sep.textContent = item.char;
        container.appendChild(sep);
      } else {
        var digitEl = document.createElement('span');
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
    var h = Math.floor(elapsed / 3600);
    var m = Math.floor((elapsed % 3600) / 60);
    var s = elapsed % 60;

    // 拆成 6 个单独的数字
    var timeDigits = [
      Math.floor(h / 10) % 10, h % 10,
      Math.floor(m / 10),      m % 10,
      Math.floor(s / 10),      s % 10
    ];

    var current = timerEl._current;
    var digits  = timerEl._digits;

    for (var i = 0; i < 6; i++) {
      if (current[i] !== timeDigits[i]) {
        // 方向规则：
        //   第 6 位（秒个位 i=5）是主动计时的 → 向上翻
        //   其余位都是因为进位才触发变化 → 向下翻
        var direction = (i === 5) ? 'up' : 'down';
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
    var main = digitEl.querySelector('.t-d-main');
    var oldVal = main.textContent;
    if (oldVal === String(newVal)) return;

    var ANIM_MS = 260;

    // 旧数字飞出
    var outEl = document.createElement('span');
    outEl.className = 't-d-float';
    outEl.textContent = oldVal;
    outEl.style.animation = (dir === 'up' ? 't-up-out' : 't-down-out') + ' ' + ANIM_MS + 'ms ease forwards';

    // 新数字飞入
    var inEl = document.createElement('span');
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
