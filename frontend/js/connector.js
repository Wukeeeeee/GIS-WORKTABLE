// ============================================================
// connector.js — 连接器（数据源）快捷面板
// 输入框旁图标按钮 → 浮层显示所有外部数据源连接状态
// 配置编辑仍在「设置 → 连接器」中管理，此处仅状态总览 + 快捷入口
// ============================================================
(function () {
  'use strict';

  // 连接器元数据：名称、类型、说明
  var CONNECTOR_META = {
    amap:       { name: '高德地图',       type: 'key',     desc: 'POI搜索 / 天气 / 地理编码' },
    copernicus: { name: 'Copernicus',     type: 'account', desc: '哥白尼开放数据（Sentinel 系列）' },
    usgs:       { name: 'USGS',           type: 'account', desc: '美国地质调查局（Landsat / DEM）' },
    gscloud:    { name: '地理空间数据云', type: 'account', desc: '国内遥感数据平台' },
    nasa:       { name: 'NASA Earthdata', type: 'account', desc: 'NASA 地球科学数据' },
    opentopo:   { name: 'OpenTopography', type: 'key',     desc: '全球 DEM 高程数据' },
    asf:        { name: 'ASF',            type: 'account', desc: '阿拉斯加卫星设施（SAR 数据）' },
    tianditu:   { name: '天地图',         type: 'key',     desc: '国家地理信息公共服务平台' },
    resdc:      { name: '资源环境数据云', type: 'account', desc: '中科院资源环境科学数据中心' },
    geoss:      { name: 'China GEOSS',    type: 'account', desc: '中国地球观测组织' },
    pie:        { name: 'PIE-Engine',     type: 'account', desc: '航天宏图遥感云引擎' },
  };

  // 显示顺序
  var ORDER = ['amap', 'copernicus', 'usgs', 'gscloud', 'nasa', 'opentopo', 'asf', 'tianditu', 'resdc', 'geoss', 'pie'];

  var _panel = null;
  var _btn = null;

  function init() {
    _btn = document.getElementById('connectorBtn');
    _panel = document.getElementById('connectorPanel');
    if (!_btn || !_panel) return;

    _btn.addEventListener('click', function (e) {
      e.stopPropagation();
      // 直接打开设置面板并跳到连接器（地理服务）页签，不弹浮层
      openSettingsGeo();
    });

    var closeBtn = document.getElementById('connectorClose');
    if (closeBtn) closeBtn.addEventListener('click', hide);

    // 点击面板外部关闭
    document.addEventListener('click', function (e) {
      if (!_panel) return;
      if (_panel.style.display === 'none') return;
      if (_panel.contains(e.target)) return;
      if (_btn && _btn.contains(e.target)) return;
      hide();
    });

    // ESC 关闭
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') hide();
    });
  }

  function toggle() {
    if (!_panel) return;
    if (_panel.style.display === 'none' || !_panel.style.display) {
      show();
    } else {
      hide();
    }
  }

  function show() {
    if (!_panel) return;
    render();
    _panel.style.display = 'block';
  }

  function hide() {
    if (_panel) _panel.style.display = 'none';
  }

  // 判断连接器是否已配置
  function isConfigured(svc) {
    if (svc === 'amap') {
      var key = localStorage.getItem('gis_amap_api_key') || '';
      return key.trim().length > 0;
    }
    try {
      var all = JSON.parse(localStorage.getItem('gis_geo_credentials') || '{}');
      var cred = all[svc] || {};
      if (cred.api_key && cred.api_key.trim()) return true;
      if (cred.username && cred.username.trim()) return true;
    } catch (e) {}
    return false;
  }

  // 渲染连接器列表
  function render() {
    var list = document.getElementById('connectorList');
    if (!list) return;
    list.innerHTML = '';

    var configuredCount = 0;
    ORDER.forEach(function (svc) {
      var meta = CONNECTOR_META[svc];
      if (!meta) return;
      var configured = isConfigured(svc);
      if (configured) configuredCount++;

      var item = document.createElement('div');
      item.className = 'connector-item' + (configured ? ' is-configured' : '');

      var info = document.createElement('div');
      info.className = 'connector-info';
      var name = document.createElement('span');
      name.className = 'connector-name';
      name.textContent = meta.name;
      var status = document.createElement('span');
      status.className = 'connector-status ' + (configured ? 'configured' : 'unconfigured');
      status.textContent = configured ? '已配置' : '未配置';
      info.appendChild(name);
      info.appendChild(status);

      var desc = document.createElement('div');
      desc.className = 'connector-desc';
      desc.textContent = meta.desc + '（' + (meta.type === 'key' ? 'API Key' : '账号密码') + '）';

      var actions = document.createElement('div');
      actions.className = 'connector-actions';

      // 测试按钮（仅高德可直接测，其他显示提示）
      if (svc === 'amap' && configured) {
        var testBtn = document.createElement('button');
        testBtn.className = 'connector-test';
        testBtn.textContent = '测试';
        testBtn.addEventListener('click', function () { testAmap(testBtn); });
        actions.appendChild(testBtn);
      }

      var setupBtn = document.createElement('button');
      setupBtn.className = 'connector-setup';
      setupBtn.textContent = '设置';
      setupBtn.addEventListener('click', function () {
        hide();
        openSettingsGeo();
      });
      actions.appendChild(setupBtn);

      item.appendChild(info);
      item.appendChild(desc);
      item.appendChild(actions);
      list.appendChild(item);
    });

    // 头部统计
    var countEl = document.getElementById('connectorCount');
    if (countEl) {
      countEl.textContent = configuredCount + ' / ' + ORDER.length + ' 已配置';
    }
  }

  // 测试高德 Key（调用天气接口）
  function testAmap(btn) {
    var key = localStorage.getItem('gis_amap_api_key') || '';
    if (!key) {
      alert('高德 Key 未配置');
      return;
    }
    btn.textContent = '测试中...';
    btn.disabled = true;
    var url = 'https://restapi.amap.com/v3/weather/weatherInfo?city=110101&key=' + encodeURIComponent(key);
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        btn.disabled = false;
        if (data.status === '1') {
          btn.textContent = '正常';
          btn.classList.add('test-ok');
        } else {
          btn.textContent = '失败';
          btn.classList.add('test-fail');
        }
        setTimeout(function () {
          btn.textContent = '测试';
          btn.classList.remove('test-ok', 'test-fail');
        }, 2000);
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = '网络错误';
        setTimeout(function () { btn.textContent = '测试'; }, 2000);
      });
  }

  // 打开设置面板并切换到「连接器（地理服务）」页签
  function openSettingsGeo() {
    if (window.GIS && window.GIS.settings && typeof window.GIS.settings.openModal === 'function') {
      window.GIS.settings.openModal('geo-api');
    } else {
      // 兜底：手动打开并切换
      var modal = document.getElementById('settingsModal');
      if (!modal) return;
      var settingsBtn = document.getElementById('settingsBtn');
      if (settingsBtn) settingsBtn.click();
      setTimeout(function () {
        var navItems = document.querySelectorAll('.modal-sidenav-item');
        navItems.forEach(function (n) {
          n.classList.toggle('active', n.dataset.panel === 'geo-api');
        });
        var panels = document.querySelectorAll('.modal-panel');
        panels.forEach(function (p) { p.classList.remove('active'); });
        var geoPanel = document.getElementById('panelGeoApi');
        if (geoPanel) geoPanel.classList.add('active');
      }, 100);
    }
  }

  // 暴露到全局
  window.GIS = window.GIS || {};
  window.GIS.connector = { init: init, show: show, hide: hide, render: render };

  // DOM 就绪后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
