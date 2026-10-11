// AI 面板空状态与配置引导
function updateGreeting() {
  var el = document.getElementsByClassName('chat-messages-empty')[0];
  if (!el) return;

  var isConfigured = false;
  try {
    if (window.GIS && window.GIS.api && window.GIS.api.currentProvider) {
      var cur = window.GIS.api.currentProvider();
      isConfigured = cur && !!cur.api_key;
    }
  } catch (_) {}

  if (!isConfigured) {
    el.innerHTML = [
      '<div class="chat-empty-state">',
      '  <div class="chat-empty-title">尚未配置 AI 模型</div>',
      '  <div class="chat-empty-hint">请先配置 API Key 以启用智能对话与空间 Agent</div>',
      '  <button type="button" class="chat-empty-config-btn" id="emptyPanelConfigBtn">去配置</button>',
      '</div>'
    ].join('\n');
    var btn = document.getElementById('emptyPanelConfigBtn');
    if (btn) {
      btn.onclick = function() {
        var s = document.getElementById('settingsBtn');
        if (s) s.click();
      };
    }
  } else {
    el.innerHTML = [
      '<div class="chat-empty-state">',
      '  <div class="chat-empty-title" style="font-weight:500;color:var(--on-surface-variant);">输入任务指令，按 Enter 发送</div>',
      '</div>'
    ].join('\n');
  }
}

document.addEventListener('DOMContentLoaded', function() {
  setTimeout(updateGreeting, 50);
});
window.updateGreeting = updateGreeting;
