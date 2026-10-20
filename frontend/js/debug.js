window.GIS = window.GIS || {};
(function() {
  'use strict';

  var panel = null;
  var visible = false;
  var _refreshTimer = null;

  var PANEL_HTML = [
    '<div class="debug-panel" id="debugPanel" style="display:none;">',
    '  <div class="debug-panel-header" id="debugPanelHeader">',
    "    <span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:15px;height:15px;--ui-icon-image:url('/assets/ui-icons/icon-054c0c901442.png')\"></span>",
    '    <span>\u8c03\u8bd5\u9762\u677f</span>',
    '    <span class="debug-header-info" id="debugConnStatus">\u68c0\u67e5\u4e2d...</span>',
    '    <button class="debug-panel-close" id="debugPanelClose" title="\u5173\u95ed">',
    "      <span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-73fd2751026c.png')\"></span>",
    '    </button>',
    '  </div>',
    '  <div class="debug-panel-body custom-scrollbar">',
    '    <div class="debug-section">',
    "      <div class=\"debug-section-title\"><span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-6616d622fbcc.png')\"></span> 系统信息</div>",
    '      <div class="debug-row"><span class="debug-label">\u5f53\u524d\u6a21\u578b</span><span class="debug-value" id="debugModel"></span></div>',
    '      <div class="debug-row"><span class="debug-label">\u9ad8\u5fb7 Key</span><span class="debug-value" id="debugAmapKey"></span></div>',
    '      <div class="debug-row"><span class="debug-label">\u540e\u7aef\u72b6\u6001</span><span class="debug-value" id="debugBackendStatus"></span></div>',
    '    </div>',
    '    <div class="debug-section">',
    "      <div class=\"debug-section-title\"><span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-94d8a506cd23.png')\"></span> 图层</div>",
    '      <div class="debug-row"><span class="debug-label">\u5df2\u6ce8\u518c\u56fe\u5c42</span><span class="debug-value" id="debugLayerCount"></span></div>',
    '      <div class="debug-layer-list" id="debugLayerList"></div>',
    '    </div>',
    '    <div class="debug-section">',
    '      <div class="debug-section-title">\u4f1a\u8bdd</div>',
    '      <div class="debug-row"><span class="debug-label">\u65e5\u5fd7\u6761\u6570</span><span class="debug-value" id="debugSessionLogs"></span></div>',
    '    </div>',
    '    <div class="debug-section" id="debugApiTestSection">',
    "      <div class=\"debug-section-title\"><span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-afff92b26f09.png')\"></span> 接口测试</div>",
    '      <div class="debug-btn-row">',
    '        <button class="debug-btn debug-btn-sm" data-api="layers">GET /api/layers</button>',
    '        <button class="debug-btn debug-btn-sm" data-api="health">GET /api/health</button>',
    '        <button class="debug-btn debug-btn-sm" data-api="reset_state">POST /api/reset_state</button>',
    '      </div>',
    '      <div class="debug-api-result" id="debugApiResult"></div>',
    '    </div>',
    '    <div class="debug-section" id="debugLoadDataSection">',
    "      <div class=\"debug-section-title\"><span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-e17ca7aaa0a1.png')\"></span> 加载测试数据</div>",
    '      <div class="debug-btn-row">',
    '        <button class="debug-btn debug-btn-sm debug-load-sample" data-layer="polygons">\u52a0\u8f7d 2 \u4e2a\u77e9\u5f62</button>',
    '        <button class="debug-btn debug-btn-sm debug-load-sample" data-layer="points">\u52a0\u8f7d 5 \u4e2a\u968f\u673a\u70b9</button>',
    '        <button class="debug-btn debug-btn-sm debug-load-sample" data-layer="line2">\u52a0\u8f7d 1 \u6761\u7ebf</button>',
    '      </div>',
    '      <div class="debug-btn-row" style="margin-top:4px;">',
    '        <button class="debug-btn debug-btn-sm debug-load-sample" data-layer="buffer_test">\u52a0\u8f7d\u7f13\u51b2\u533a\u6d4b\u8bd5</button>',
    '        <button class="debug-btn debug-btn-sm debug-load-sample" data-layer="cluster_test">\u52a0\u8f7d\u805a\u7c7b\u6d4b\u8bd5</button>',
    '      </div>',
    '    </div>',
    '    <div class="debug-section">',
    "      <div class=\"debug-section-title\"><span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:12px;height:12px;--ui-icon-image:url('/assets/ui-icons/icon-5f880ef8e203.png')\"></span> 危险操作</div>",
    '      <button class="debug-btn debug-btn-danger" id="debugResetState">\u91cd\u7f6e\u540e\u7aef\u72b6\u6001</button>',
    '    </div>',
    '  </div>',
    '</div>'
  ].join('\n');

  var SAMPLE_DATA = {
    polygons: {
      type: "FeatureCollection",
      features: [
        {type:"Feature",properties:{name:"\u77e9\u5f62A",group:"X",val:10},geometry:{type:"Polygon",coordinates:[[[116.3,39.8],[116.5,39.8],[116.5,40.0],[116.3,40.0],[116.3,39.8]]]}},
        {type:"Feature",properties:{name:"\u77e9\u5f62B",group:"X",val:20},geometry:{type:"Polygon",coordinates:[[[116.4,39.85],[116.6,39.85],[116.6,40.05],[116.4,40.05],[116.4,39.85]]]}},
      ]
    },
    points: {
      type: "FeatureCollection",
      features: [
        {type:"Feature",properties:{id:1,type:"\u5b66\u6821"},geometry:{type:"Point",coordinates:[116.35,39.90]}},
        {type:"Feature",properties:{id:2,type:"\u533b\u9662"},geometry:{type:"Point",coordinates:[116.42,39.88]}},
        {type:"Feature",properties:{id:3,type:"\u5b66\u6821"},geometry:{type:"Point",coordinates:[116.48,39.95]}},
        {type:"Feature",properties:{id:4,type:"\u5546\u5e97"},geometry:{type:"Point",coordinates:[116.38,39.93]}},
        {type:"Feature",properties:{id:5,type:"\u533b\u9662"},geometry:{type:"Point",coordinates:[116.52,39.92]}},
      ]
    },
    line2: {
      type: "FeatureCollection",
      features: [
        {type:"Feature",properties:{name:"\u9053\u8def",length_km:5},geometry:{type:"LineString",coordinates:[[116.30,39.90],[116.40,39.95],[116.50,39.92],[116.60,39.98]]}},
      ]
    },
    buffer_test: {
      type: "FeatureCollection",
      features: [
        {type:"Feature",properties:{name:"\u6d4b\u8bd5\u70b9"},geometry:{type:"Point",coordinates:[116.4,39.9]}},
      ]
    },
    cluster_test: {
      type: "FeatureCollection",
      features: (function() {
        var f = [];
        for (var i = 0; i < 8; i++) f.push({type:"Feature",properties:{id:"c1_"+i},geometry:{type:"Point",coordinates:[116.40 + i*0.001, 39.90 + i*0.001]}});
        for (var i = 0; i < 6; i++) f.push({type:"Feature",properties:{id:"c2_"+i},geometry:{type:"Point",coordinates:[116.42 + i*0.001, 39.88 + i*0.001]}});
        for (var i = 0; i < 3; i++) f.push({type:"Feature",properties:{id:"noise_"+i},geometry:{type:"Point",coordinates:[116.50 + i*0.002, 39.95 + i*0.002]}});
        return f;
      })(),
    },
  };

  function getAmapKeyStatus() {
    var amapKey = localStorage.getItem('gis_amap_api_key') || '';
    return amapKey ? '\u2713 (' + amapKey.substring(0, 6) + '...)' : '\u2717 \u672a\u914d\u7f6e';
  }

  function getModel() {
    var sel = document.getElementById('modelSelector');
    if (!sel) return '\u672a\u77e5';
    var opt = sel.options[sel.selectedIndex];
    return opt ? opt.text : '\u672a\u77e5';
  }

  function escapeMarkup(value) {
    var text = String(value == null ? '' : value);
    if (GIS.utils && typeof GIS.utils.escapeHtml === 'function') return GIS.utils.escapeHtml(text);
    return text.replace(/[&<>"']/g, function(ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function refresh() {
    if (!panel || !visible) return;
    document.getElementById('debugModel').textContent = getModel();
    document.getElementById('debugAmapKey').textContent = getAmapKeyStatus();

    var api = GIS.api;
    if (!api) return;

    api.request('/api/layers').then(function(data) {
      var list = document.getElementById('debugLayerList');
      var layers = (data && data.layers) || [];
      document.getElementById('debugLayerCount').textContent = layers.length;
      if (layers.length === 0) {
        list.innerHTML = '<div class="debug-empty">\u6682\u65e0\u56fe\u5c42</div>';
        return;
      }
      var html = '';
      layers.forEach(function(l) {
        var name = l.name || l.filename || l.layer_id || '\u672a\u547d\u540d';
        var safeName = escapeMarkup(name);
        var gj = l.geojson;
        var fc = gj && gj.features ? gj.features.length : '?';
        var types = {};
        if (gj && gj.features) {
          gj.features.forEach(function(ft) {
            var t = ft.geometry && ft.geometry.type || '?';
            types[t] = (types[t] || 0) + 1;
          });
        }
        var typeStr = Object.keys(types).map(function(t) { return types[t] + ' ' + t; }).join(', ');
        html += '<div class="debug-layer-item">';
        html += '  <div class="debug-layer-info">';
        html += '    <div class="debug-layer-name" title="' + safeName + '">' + safeName + '</div>';
        html += '    <div class="debug-layer-meta">' + escapeMarkup(fc) + ' \u8981\u7d20' + (typeStr ? ' \u00b7 ' + escapeMarkup(typeStr) : '') + '</div>';
        html += '  </div>';
        html += '</div>';
      });
      list.innerHTML = html;
    }).catch(function() {
      document.getElementById('debugLayerCount').textContent = '\u83b7\u53d6\u5931\u8d25';
      document.getElementById('debugLayerList').innerHTML = '';
    });

    api.request('/api/session_logs').then(function(d) {
      var logs = d && d.logs ? d.logs : [];
      var el = document.getElementById('debugSessionLogs');
      if (el) el.textContent = logs.length + ' \u6761';
    }).catch(function() {});
  }

  function checkBackend() {
    var el = document.getElementById('debugBackendStatus');
    var connEl = document.getElementById('debugConnStatus');
    var api = GIS.api;
    if (!api) { el.textContent = '\u2717 \u65e0 API'; connEl.textContent = ''; return; }
    el.textContent = '\u68c0\u67e5\u4e2d...';
    connEl.textContent = '\u68c0\u67e5\u4e2d';
    api.healthCheck().then(function(d) {
      el.textContent = '\u2713 \u5728\u7ebf';
      connEl.textContent = '\u2713';
      connEl.className = 'debug-header-info debug-conn-ok';
    }).catch(function() {
      el.textContent = '\u2717 \u672a\u8fde\u63a5';
      connEl.textContent = '\u2717 \u65ad\u5f00';
      connEl.className = 'debug-header-info debug-conn-fail';
    });
  }

  function show() {
    if (!panel) return;
    visible = true;
    panel.style.display = '';
    if (GIS.workspace) {
      GIS.workspace.preparePanel('debugPanel', 'debugPanelHeader', 'debugPanelClose', '调试面板');
      GIS.workspace.expandPanel('debugPanel');
    }
    GIS.debugPanelVisible = true;
    positionPanel();
    checkBackend();
    refresh();
    if (!_refreshTimer) { _refreshTimer = setInterval(refresh, 5000); }
  }

  function hide() {
    if (!panel) return;
    visible = false;
    panel.style.display = 'none';
    GIS.debugPanelVisible = false;
    if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
  }

  function toggle() {
    if (visible) { hide(); } else { show(); }
  }

  function positionPanel() {
    if (!panel) return;
    if (GIS.workspace) {
      panel.style.position = 'fixed';
      GIS.workspace.centerPanel(panel, 380);
      var bounds = GIS.workspace.panelBounds(panel.offsetWidth || 380);
      panel.style.maxHeight = (bounds.bottom-bounds.top)+'px';
      return;
    }
    var mapArea = document.getElementById('mapArea');
    if (!mapArea) return;
    var mr = mapArea.getBoundingClientRect();
    var left = 4;
    var chatPanel = document.querySelector('.chat-panel');
    if (chatPanel) {
      left = chatPanel.offsetWidth + 4;
    }
    var top = 34;
    panel.style.left = left + 'px';
    panel.style.top = top + 'px';
    panel.style.maxHeight = (mr.height - top - 8) + 'px';
  }

  function loadSampleData(key) {
    var data = SAMPLE_DATA[key];
    if (!data || !data.features) return;
    var name = key + '.geojson';
    if (GIS.map && GIS.map.loadGeoJSON) {
      GIS.map.loadGeoJSON(data, name);
    }
    if (GIS.layers && GIS.layers.addLayer) {
      var typeMap = {};
      data.features.forEach(function(f) {
        var t = f.geometry && f.geometry.type;
        if (t) typeMap[t] = (typeMap[t] || 0) + 1;
      });
      GIS.layers.addLayer({
        layer_id: name + '_' + Date.now(),
        filename: name,
        geometry_type: Object.keys(typeMap).sort().join(', '),
        geojson: data,
        source: 'sample',
      }, false);
    }
    if (GIS.chat && GIS.chat.addMessage) {
      GIS.chat.addMessage('已加载测试数据「' + key + '」(' + data.features.length + ' 个要素)，可以在聊天中指挥 AI 分析了', 'system');
    }
    setTimeout(refresh, 300);
  }

  function callApi(endpoint) {
    var resultEl = document.getElementById('debugApiResult');
    var api = GIS.api;
    if (!api) { resultEl.textContent = '\u2717 \u65e0 API'; return; }
    resultEl.textContent = '\u8bf7\u6c42\u4e2d...';
    var p;
    if (endpoint === 'reset_state') {
      p = api.request('/api/reset_state', { method: 'POST' });
    } else {
      p = api.request('/api/' + endpoint);
    }
    p.then(function(d) {
      var txt = typeof d === 'string' ? d : JSON.stringify(d, null, 2);
      resultEl.textContent = txt.length > 300 ? txt.substring(0, 300) + '...' : txt;
      refresh();
    }).catch(function(e) {
      resultEl.textContent = '\u2717 ' + (e.message || e);
    });
  }

  function createPanel() {
    if (document.getElementById('debugPanel')) return;
    var wrapper = document.createElement('div');
    wrapper.innerHTML = PANEL_HTML;
    document.body.appendChild(wrapper.firstElementChild);
    panel = document.getElementById('debugPanel');

    document.getElementById('debugPanelClose').addEventListener('click', hide);

    document.getElementById('debugResetState').addEventListener('click', function() {
      var api = GIS.api;
      if (!api) return;
      api.request('/api/reset_state', { method: 'POST' }).then(function() {
        refresh();
      }).catch(function() {});
    });

    document.querySelectorAll('.debug-load-sample').forEach(function(btn) {
      btn.addEventListener('click', function() {
        loadSampleData(this.getAttribute('data-layer'));
      });
    });

    document.querySelectorAll('[data-api]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        callApi(this.getAttribute('data-api'));
      });
    });
  }

  GIS.debug = { show: show, hide: hide, toggle: toggle, refresh: refresh };

  document.addEventListener('DOMContentLoaded', function() {
    createPanel();

    var modelSel = document.getElementById('modelSelector');
    if (modelSel) modelSel.addEventListener('change', refresh);

    var oldResize = window.onresize;
    window.onresize = function() {
      if (oldResize) oldResize();
      if (visible) positionPanel();
    };
  });

})();
