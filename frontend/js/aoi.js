/**
 * GIS AI WorkTable — AOI 选择模块
 * 在聊天对话框里显示候选地点，用户点击选择
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  function init() {
    console.log('[GIS AOI] 模块初始化完成');
  }

  /**
   * 在聊天框里显示候选地点列表
   */
  function showSuggestions(suggestions) {
    if (!suggestions || suggestions.length === 0) return;

    var container = document.getElementById('chatMessages');
    if (!container) return;

    // 创建选择卡片消息
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;max-width:100%;margin:8px 0;';
    row.id = 'aoi-select-msg';

    // AI 头像
    var avatar = document.createElement('div');
    avatar.className = 'message-avatar message-avatar-ai';
    avatar.innerHTML = '<svg class="svg-icon-sm"><use href="assets/icons.svg#icon-ai"/></svg>';
    row.appendChild(avatar);

    // 气泡
    var bubble = document.createElement('div');
    bubble.className = 'message-bubble message-bubble-ai';
    bubble.style.cssText = 'max-width:100%;padding:12px 16px;';

    // 标题
    var title = document.createElement('div');
    title.style.cssText = 'font-size:13px;font-weight:600;color:#1a1a1a;margin-bottom:10px;';
    title.textContent = '已搜索到候选地点，请选择：';
    bubble.appendChild(title);

    // 候选列表
    suggestions.forEach(function(item, idx) {
      var el = document.createElement('div');
      el.style.cssText = 'padding:8px 10px;margin-bottom:4px;border:1px solid #e0e0e0;border-radius:4px;cursor:pointer;font-size:13px;transition:background 0.15s;';
      el.dataset.index = idx;

      var nameText = item.name || '';
      var addrText = item.address ? ' (' + item.address + ')' : '';

      el.innerHTML = '<span style="color:#333;">' + escapeHtml(nameText) + '</span>' +
        (addrText ? '<span style="color:#999;font-size:12px;margin-left:4px;">' + escapeHtml(addrText) + '</span>' : '');

      el.addEventListener('mouseenter', function() {
        this.style.background = '#f0f0f0';
      });
      el.addEventListener('mouseleave', function() {
        this.style.background = '';
      });
      el.addEventListener('click', function() {
        selectAndSend(item);
      });

      bubble.appendChild(el);
    });

    // 底部提示
    var hint = document.createElement('div');
    hint.style.cssText = 'font-size:11px;color:#aaa;margin-top:10px;';
    hint.textContent = '点击上方任意一项选择';
    bubble.appendChild(hint);

    row.appendChild(bubble);
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
  }

  function selectAndSend(item) {
    var name = item.name;
    var poiId = item.id || item.uid || '';
    var source = item.source || 'baidu';

    if (!poiId) return;

    // 移除选择消息（避免重复点击）
    var msgEl = document.getElementById('aoi-select-msg');
    if (msgEl) msgEl.remove();

    // 发送选择给 AI
    var message = '已选择AOI候选: ' + name + ' | ID: ' + poiId + ' | 来源: ' + source;
    GIS.chat.sendMessage(message).catch(function(err) {
      console.error('[GIS AOI] 发送失败:', err);
    });
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  GIS.aoi = {
    init: init,
    showSuggestions: showSuggestions,
  };

  // 向后兼容
  GIS.baiduAoi = GIS.aoi;
})();
