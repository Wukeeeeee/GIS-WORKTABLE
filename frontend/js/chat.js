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
      sendBtn.addEventListener('click', send);
    }

  }

  async function send() {
    const text = inputEl ? inputEl.value.trim() : '';
    if (!text) return;
    // 渲染用户消息添加到这个对话框
    addMessage(text, 'user');
    inputEl.value = '';

    // 显示加载状态：输入框显示提示文字，禁用按钮
    const originalPlaceholder = inputEl.placeholder;
    inputEl.placeholder = 'AI正在回复中...';
    inputEl.disabled = true;
    sendBtn.disabled = true;
    sendBtn.style.opacity = '0.5';

    try {
      // 发送到后端 API，等待回复
      const result = await GIS.api.chat(text);
      addMessage(result.response, 'ai');
    } catch (err) {
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

  GIS.chat = { init: init, send: send, addMessage: addMessage, clear: clear };
})();
