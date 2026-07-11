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
  let _switchBtnRef = null;  // GLM→DeepSeek 切换按钮引用，执行完后恢复

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

    // 检查当前选中的模型是否已配置 API Key
    var selModel = document.getElementById('modelSelector');
    var curProvider = selModel ? selModel.value : 'deepseek';
    var hasKey = curProvider === 'glm' ? window.GIS.api.getGLMApiKey() : window.GIS.api.getApiKey();
    if (!hasKey) {
      if (window.GIS && window.GIS.app && window.GIS.app.toast) {
        var modelName = curProvider === 'glm' ? 'GLM-4.7-Flash' : 'DeepSeek V4 Flash';
        addMessage(modelName + ' 未配置 API Key，请点击齿轮按钮设置', 'system');
      }
      // 恢复输入框
      inputEl.placeholder = originalPlaceholder;
      inputEl.disabled = false;
      sendBtn.disabled = false;
      sendBtn.style.opacity = '1';
      var modelBar2 = document.querySelector('.chat-input-model-bar');
      if (modelBar2) modelBar2.classList.remove('is-disabled');
      return;
    }

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
    // 显示加载状态：输入框显示提示文字，禁用按钮和模型选择
    const originalPlaceholder = inputEl.placeholder;
    inputEl.placeholder = 'AI正在回复中...';
    inputEl.disabled = true;
    sendBtn.disabled = true;
    sendBtn.style.opacity = '0.5';
    // 禁用模型选择器（请求中不允许换模型）
    var modelBar = document.querySelector('.chat-input-model-bar');
    if (modelBar) modelBar.classList.add('is-disabled');

    // 获取当前模型显示名（从模型选择器取）
    var modelDisplayEl = document.getElementById('modelSelectValue');
    var modelDisplayName = modelDisplayEl ? modelDisplayEl.textContent : 'AI';

    // 添加"模型名 思考中..."占位气泡，让用户知道 AI 正在处理
    var loadingMsg = addMessage(modelDisplayName + ' 思考中...', 'ai', { noMarkdown: true });
    loadingMsg.id = 'ai-loading-msg';

    // 给气泡文本加流光 scan 动画
    var loadingContent = loadingMsg.querySelector('.message-bubble > div');
    if (loadingContent) loadingContent.classList.add('shimmer-loading-text');

    // 添加翻牌计时器（实时显示 AI 思考耗时），另起一行
    var timerEl = createFlipTimer();
    var timerWrapper = document.createElement('div');
    timerWrapper.style.cssText = 'margin-top:6px;';
    timerWrapper.appendChild(timerEl);
    var loadingBubble = loadingMsg.querySelector('.message-bubble');
    if (loadingBubble) loadingBubble.appendChild(timerWrapper);

    var startTime = Date.now();
    var timerInterval = setInterval(function() {
      var elapsed = Math.floor((Date.now() - startTime) / 1000);
      updateFlipTimer(timerEl, elapsed);
    }, 1000);
    updateFlipTimer(timerEl, 0);
    loadingMsg._timerInterval = timerInterval;

    try {
      // 读取当前选择的模型
      const modelSelector = document.getElementById('modelSelector');
      const provider = modelSelector ? modelSelector.value : 'deepseek';
      // 发送到后端 API，等待回复
      const result = await GIS.api.chat(text, 'default', provider);
      // 移除"思考中"占位气泡
      var loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        loadingEl.remove();
      }

      // 显示 AI 的文字回复
      var msgEl = addMessage(result.response, 'ai');

      // 如果有 AI 生成的图表图片，追加到最后一条回复下方
      if (result.images && result.images.length > 0) {
        // 如果上一步有返回 msgEl 就用它，否则新建容器
        var imgContainer = document.createElement('div');
        imgContainer.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;margin-left:32px;';
        // 通用下载函数（fetch + Blob，解决跨域下载问题）
        function downloadFile(url, filename) {
          fetch(url).then(function(res) { return res.blob(); }).then(function(blob) {
            var a = document.createElement('a');
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
          var imgUrl = typeof item === 'string' ? item : (item.url || '');
          var imgType = typeof item === 'string' ? (imgUrl.match(/\.html?$/i) ? 'html' : 'png') : (item.type || 'png');
          var htmlContent = typeof item === 'string' ? null : (item.content || null);
          var fileName = imgUrl.split('/').pop() || 'file';
          var baseUrl = (window.GIS && window.GIS.api && window.GIS.api.BASE_URL) || 'http://localhost:8000';
          var fullUrl = baseUrl + imgUrl;

          if (imgType === 'html') {
            var htmlWrap = document.createElement('div');
            htmlWrap.style.cssText = 'border:1px solid var(--ui-gray-200);border-radius:4px;overflow:hidden;width:100%;';
            var iframe = document.createElement('iframe');
            iframe.style.cssText = 'width:100%;height:420px;border:none;display:block;';
            iframe.title = '交互式地图';
            // 优先用 srcdoc（内联 HTML，不落磁盘），其次用 src
            if (htmlContent) {
              iframe.srcdoc = htmlContent;
            } else {
              iframe.src = fullUrl;
            }
            htmlWrap.appendChild(iframe);
            var toolBar = document.createElement('div');
            toolBar.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;border-top:1px solid var(--ui-gray-200);background:var(--surface-container-low);font-size:12px;';
            toolBar.innerHTML =
              '<span style="flex:1;color:var(--ui-gray-400);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + fileName + '</span>' +
              '<a href="' + fullUrl + '" target="_blank" style="padding:3px 8px;border:1px solid var(--ui-gray-200);border-radius:3px;text-decoration:none;color:var(--ui-gray-900);">新标签打开</a>';
            // 下载按钮（用 fetch+blob，不会跳转）
            var dlHtmlBtn = document.createElement('button');
            dlHtmlBtn.textContent = '下载';
            dlHtmlBtn.style.cssText = 'padding:3px 8px;background:var(--ui-gray-900);color:var(--ui-white);border:none;border-radius:3px;cursor:pointer;font-size:12px;';
            dlHtmlBtn.addEventListener('click', function() { downloadFile(fullUrl, fileName); });
            toolBar.appendChild(dlHtmlBtn);
            htmlWrap.appendChild(toolBar);
            imgContainer.appendChild(htmlWrap);
          } else {
            // 图片文件
            var wrapper = document.createElement('div');
            wrapper.style.cssText = 'position:relative;display:inline-block;';
            var img = document.createElement('img');
            img.src = fullUrl;
            img.style.cssText = 'max-width:100%;max-height:300px;border-radius:4px;border:1px solid var(--ui-gray-200);cursor:pointer;display:block;';
            img.title = '点击放大';
            img.addEventListener('click', function() { window.open(fullUrl); });
            wrapper.appendChild(img);
            // 下载按钮（右上角悬浮，用 fetch+blob）
            var dlImgBtn = document.createElement('button');
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
          var bubble = msgEl.querySelector('.message-bubble');
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
          var allLayers = window.GIS.layers.getLayers();
          allLayers.forEach(function(l) {
            if (l.layer_id) window.GIS.layers.removeLayer(l.layer_id);
          });
        }
        if (window.GIS && window.GIS.app && window.GIS.app.toast) {
          addMessage('已清空所有图层', 'system');
        }
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
            source: 'ai',
          });
        })(0);
      }
    } catch (err) {
      // 移除"思考中"占位气泡
      var loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        loadingEl.remove();
      }
      addMessage('请求失败: ' + err.message, 'system');
      if (window.GIS && window.GIS.app && window.GIS.app.toast) {
        addMessage('请求失败: ' + err.message, 'system');
      }
    } finally {
      // 恢复 GLM→DeepSeek 切换按钮（如果有）
      if (_switchBtnRef) {
        _switchBtnRef.disabled = false;
        _switchBtnRef.style.opacity = '1';
        _switchBtnRef.style.cursor = 'pointer';
        _switchBtnRef = null;
      }
      // 恢复输入状态
      inputEl.placeholder = originalPlaceholder;
      inputEl.disabled = false;
      sendBtn.disabled = false;
      sendBtn.style.opacity = '1';
      inputEl.focus();
      // 重新启用模型选择
      var modelBar = document.querySelector('.chat-input-model-bar');
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
      var isHidden = options && options.hidden;
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
      content.innerHTML = marked.parse(text, { breaks: true, gfm: true });
    } else {
      content.innerHTML = text;
    }
    bubble.appendChild(content);

    // 检测 AI 回复是否建议切换到 DeepSeek
    if (type === 'ai' && text.indexOf('→ 建议切换到 DeepSeek 执行') !== -1) {
      var switchBtn = document.createElement('button');
      switchBtn.textContent = '切换到 DeepSeek 执行';
      switchBtn.style.cssText = 'margin-top:10px;padding:6px 14px;font-size:12px;background:var(--ui-gray-900);color:var(--ui-white);border:none;border-radius:4px;cursor:pointer;display:block;transition:opacity 0.15s;';
      switchBtn.addEventListener('mouseenter', function() { this.style.opacity = '0.8'; });
      switchBtn.addEventListener('mouseleave', function() { this.style.opacity = '1'; });
      switchBtn.addEventListener('click', function() {
        // 检查 DeepSeek 是否已配置 API Key
        var dsKey = window.GIS.api.getApiKey();
        if (!dsKey) {
          switchBtn.disabled = false;
          switchBtn.style.opacity = '1';
          switchBtn.style.cursor = 'pointer';
          var tip = document.createElement('div');
          tip.style.cssText = 'margin-top:6px;padding:6px 10px;font-size:11px;color:#b71c1c;background:#ffebee;border-radius:4px;border:1px solid #ef9a9a;';
          tip.textContent = 'DeepSeek 未配置 API Key，请点击齿轮按钮设置';
          switchBtn.parentNode.insertBefore(tip, switchBtn.nextSibling);
          return;
        }
        // 保存引用，AI 执行完后恢复
        _switchBtnRef = switchBtn;
        // 立即禁用按钮（防重复点击）
        switchBtn.disabled = true;
        switchBtn.style.opacity = '0.35';
        switchBtn.style.cursor = 'default';
        // 切换到 DeepSeek 模型
        var sel = document.getElementById('modelSelector');
        var val = document.getElementById('modelSelectValue');
        if (sel) sel.value = 'deepseek';
        if (val) val.textContent = 'DeepSeek V4 Flash';
        if (window.GIS.api) window.GIS.api.setSelectedModel('deepseek');
        if (typeof updateModelStatusDot === 'function') updateModelStatusDot();
        // 提取规划内容，发给 DeepSeek 处理
        var workflow = text.replace('→ 建议切换到 DeepSeek 执行', '').trim();
        // 拼接执行指令
        var msg = '请按以下规划执行：\n' + workflow;
        // 通知用户
        var container = document.getElementById('chatMessages');
        var notice = document.createElement('div');
        notice.style.cssText = 'display:flex;justify-content:center;max-width:100%;';
        var noticeBubble = document.createElement('div');
        noticeBubble.style.cssText = 'font-size:11px;color:var(--ui-gray-400);background:var(--ui-gray-100);padding:3px 10px;border-radius:8px;text-align:center;margin:4px 0;';
        noticeBubble.textContent = '已切换到 DeepSeek，正在执行规划...';
        notice.appendChild(noticeBubble);
        container.appendChild(notice);
        container.scrollTop = container.scrollHeight;
        // 延迟一下等 UI 更新，然后把规划发给 DeepSeek
        setTimeout(function() {
          if (typeof sendMessage === 'function') {
            sendMessage(msg);
          } else if (window.GIS && window.GIS.chat && typeof window.GIS.chat.send === 'function') {
            window.GIS.chat.send(msg);
          }
        }, 500);
      });
      bubble.appendChild(switchBtn);
    }

    if (options.code) {
      const codeBlock = document.createElement('div');
      codeBlock.className = 'message-code-block';
      codeBlock.textContent = options.code;
      bubble.appendChild(codeBlock);
    }

    // AI 消息右下角复制按钮（跳过加载气泡）
    if (type === 'ai' && !options.noMarkdown) {
      var copyBtn = document.createElement('button');
      copyBtn.className = 'btn-copy-ai';
      copyBtn.title = '复制回复';
      copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      copyBtn.addEventListener('click', function() {
        // 取纯文本（跳过 markdown HTML 标签）
        var plainText = content.textContent || content.innerText || text;
        navigator.clipboard.writeText(plainText).then(function() {
          copyBtn.classList.add('copied');
          copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
          setTimeout(function() {
            copyBtn.classList.remove('copied');
            copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
          }, 2000);
        }).catch(function() {
          // fallback: 用 textarea 复制
          var ta = document.createElement('textarea');
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
