// ============================================================
// history.js — 处理历史面板
// 右侧浮层：按时间倒序展示每次工具执行（工具名/参数/时间/产物/成败），
// 每条支持「重跑」（原始参数重新调用，产物作为新图层上图）与「复制参数 JSON」。
// 后端：GET /api/history、POST /api/history/rerun（main.py）
// ============================================================
(function () {
  'use strict';

  var GIS = window.GIS = window.GIS || {};

  var _panel = null;
  var _body = null;
  var _entries = [];

  function init() {
    _panel = document.getElementById('historyPanel');
    _body = document.getElementById('historyBody');
    var toggleBtn = document.getElementById('toggleHistoryPanel');
    var clearBtn = document.getElementById('toolHistClearBtn');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', function () {
      if (!_panel) return;
      var willOpen = !_panel.classList.contains('open');
      _panel.classList.toggle('open', willOpen);
      toggleBtn.classList.toggle('active', willOpen);
      if (willOpen) refresh();
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        fetch(BASE() + '/api/history', { method: 'DELETE' })
          .then(function () { render([]); })
          .catch(function () {});
      });
    }
  }

  function BASE() {
    return (GIS.api && GIS.api.BASE_URL) || '';
  }

  function refresh() {
    if (!_body) return;
    fetch(BASE() + '/api/history?limit=50')
      .then(function (r) { return r.json(); })
      .then(function (data) { render(data.history || []); })
      .catch(function () {
        _body.innerHTML = '<div class="toolhist-empty">加载历史失败（后端未连接？）</div>';
      });
  }

  function render(entries) {
    _entries = entries;
    if (!_body) return;
    if (!entries.length) {
      _body.innerHTML = '<div class="toolhist-empty">暂无记录：执行任意工具后在此查看</div>';
      return;
    }
    _body.innerHTML = '';
    entries.forEach(function (e) {
      _body.appendChild(_renderItem(e));
    });
  }

  function _renderItem(e) {
    var div = document.createElement('div');
    div.className = 'toolhist-item' + (e.ok ? '' : ' is-error');

    var top = document.createElement('div');
    top.className = 'toolhist-item-top';
    var idx = document.createElement('span');
    idx.className = 'toolhist-time';
    idx.textContent = '#' + e.index;
    var name = document.createElement('span');
    name.className = 'toolhist-tool-name';
    name.textContent = e.tool || '';
    name.title = e.tool || '';
    top.appendChild(idx);
    top.appendChild(name);
    if (e.rerun_of) {
      var rr = document.createElement('span');
      rr.className = 'toolhist-badge rerun';
      rr.textContent = '重跑#' + e.rerun_of;
      top.appendChild(rr);
    }
    var badge = document.createElement('span');
    badge.className = 'toolhist-badge' + (e.ok ? '' : ' fail');
    badge.textContent = e.ok ? '成功' : '失败';
    top.appendChild(badge);
    var time = document.createElement('span');
    time.className = 'toolhist-time';
    time.textContent = (e.time || '').slice(5, 16);
    top.appendChild(time);
    div.appendChild(top);

    var args = document.createElement('div');
    args.className = 'toolhist-args';
    try {
      args.textContent = JSON.stringify(e.args || {}, null, 0);
    } catch (_) {
      args.textContent = '(参数不可序列化)';
    }
    div.appendChild(args);

    var layers = (e.layer_ids || []).join('、');
    if (layers) {
      var ly = document.createElement('div');
      ly.className = 'toolhist-layers';
      ly.textContent = '产物图层: ' + layers;
      ly.title = layers;
      div.appendChild(ly);
    }

    var actions = document.createElement('div');
    actions.className = 'toolhist-item-actions';
    var rerunBtn = document.createElement('button');
    rerunBtn.className = 'toolhist-rerun-btn';
    rerunBtn.textContent = '重跑';
    rerunBtn.addEventListener('click', function () { rerun(e.index, rerunBtn); });
    var copyBtn = document.createElement('button');
    copyBtn.className = 'toolhist-copy-btn';
    copyBtn.textContent = '复制参数';
    copyBtn.addEventListener('click', function () {
      copyText(JSON.stringify(e.args || {}, null, 2), copyBtn);
    });
    actions.appendChild(rerunBtn);
    actions.appendChild(copyBtn);
    div.appendChild(actions);
    return div;
  }

  function rerun(index, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '重跑中...'; }
    fetch(BASE() + '/api/history/rerun', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: index }),
    })
      .then(function (r) { return r.json(); })
      .then(function (result) {
        if (btn) { btn.disabled = false; btn.textContent = '重跑'; }
        applyRerunResult(result);
      })
      .catch(function (err) {
        if (btn) { btn.disabled = false; btn.textContent = '重跑'; }
        if (GIS.chat && GIS.chat.addMessage) {
          GIS.chat.addMessage('重跑失败: ' + err.message, 'system');
        }
      });
  }

  /** 应用重跑结果：图层经共享状态上图，图层操作逐条执行（与聊天侧同语言） */
  function applyRerunResult(result) {
    if (!result) return;
    if (result.clear_layers && GIS.layers) {
      (GIS.layers.getLayers() || []).forEach(function (l) {
        if (l.layer_id) GIS.layers.removeLayer(l.layer_id);
      });
    }
    (result.layers || []).forEach(function (layer, idx) {
      if (!window.GIS.state) return;
      window.GIS.state.addLayer({
        layer_id: 'rerun_' + Date.now() + '_' + idx,
        name: (layer.name || '图层') + '_' + Date.now() + '_' + idx,
        geojson: layer.geojson || layer,
        style: layer.style || null,
        source: 'ai',
      });
    });
    (result.layer_ops || []).forEach(function (op) {
      if (!GIS.map) return;
      switch (op.action) {
        case 'swipe':
          if (GIS.map.startSwipe) GIS.map.startSwipe(op.left, op.right, op.orientation);
          break;
        case 'swipe_close':
          if (GIS.map.stopSwipe) GIS.map.stopSwipe();
          break;
        case 'fit':
          if (GIS.map.fitLayer) GIS.map.fitLayer(op.name);
          break;
        case 'set_color':
          if (GIS.map.setLayerColor) GIS.map.setLayerColor(op.name, op.color);
          break;
        case 'set_style':
          if (GIS.map.setLayerStyle) GIS.map.setLayerStyle(op.name, op.style || {});
          break;
        case 'center':
          if (GIS.map.setView && op.center) GIS.map.setView([op.center[1], op.center[0]], op.zoom || 13);
          break;
      }
    });
    if (GIS.chat && GIS.chat.addMessage) {
      GIS.chat.addMessage(result.response || '重跑完成', 'system');
    }
    refresh();
  }

  function copyText(text, btn) {
    var done = function () {
      if (!btn) return;
      var old = btn.textContent;
      btn.textContent = '已复制';
      setTimeout(function () { btn.textContent = old; }, 1200);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () { _fallbackCopy(text, done); });
    } else {
      _fallbackCopy(text, done);
    }
  }

  function _fallbackCopy(text, done) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0;';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (_) {}
    document.body.removeChild(ta);
  }

  GIS.history = { init: init, refresh: refresh };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
