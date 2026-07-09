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
    var loadingDots = document.createElement('span');
    loadingDots.className = 'loading-dots';
    loadingDots.innerHTML = '<span>.</span><span>.</span><span>.</span>';
    var loadingBubble = loadingMsg.querySelector('.message-bubble');
    if (loadingBubble) loadingBubble.appendChild(loadingDots);

    try {
      // 发送到后端 API，等待回复
      const result = await GIS.api.chat(text);
      // 移除"思考中"占位气泡
      var loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) loadingEl.remove();

      addMessage(result.response, 'ai');
      // 如果有待处理的 AOI 候选列表，显示在聊天框供点击选择
      if (result.pending_suggestions && result.pending_suggestions.length > 0) {
        setTimeout(() => {
          if (window.GIS.aoi && typeof window.GIS.aoi.showSuggestions === 'function') {
            window.GIS.aoi.showSuggestions(result.pending_suggestions);
          }
        }, 200);
      }
      // 如果 AI 生成了 GeoJSON 数据，自动加载到地图和图层
      if (result.geojson && result.layerName) {
        setTimeout(() => {
          const layerId = 'ai_' + Date.now();
          // 给图层名加时间戳避免重复（AI生成的结果每次都重新加）
          const uniqueName = result.layerName + '_' + Date.now();
          const geoType = result.geojson.type === 'FeatureCollection'
            ? (result.geojson.features[0]?.geometry?.type || '未知')
            : (result.geojson.geometry?.type || '未知');

          // 1. 加载到地图
          GIS.map.loadGeoJSON(result.geojson, uniqueName);

          // 2. 添加到图层面板（每次都加，不加去重）
          GIS.layers.addLayer({
            layer_id: layerId,
            filename: uniqueName,
            geometry_type: geoType,
            crs: 'WGS-84',
            geojson: result.geojson,
            visible: true,
          });

          // 3. 添加到处理结果面板
          const filesTbody = document.getElementById('filesTbody');
          const filesTable = document.getElementById('filesTable');
          const filesEmpty = document.getElementById('filesEmpty');
          if (filesTbody && filesTable && filesEmpty) {
            filesEmpty.style.display = 'none';
            filesTable.style.display = '';
            const row = document.createElement('tr');
            row.draggable = false;
            row.innerHTML = `
              <td></td>
              <td><span class="layer-name">${result.layerName}.geojson</span></td>
              <td style="text-align:right;">
                <button class="layer-action-btn" onclick="downloadGeoJSON('${layerId}')" title="下载">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
                  </svg>
                </button>
              </td>
            `;
            filesTbody.appendChild(row);
          }
        }, 100);
      }
    } catch (err) {
      // 移除"思考中"占位气泡
      var loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) loadingEl.remove();
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

  GIS.chat = { init, send, addMessage, clear, sendMessage: send };
})();
