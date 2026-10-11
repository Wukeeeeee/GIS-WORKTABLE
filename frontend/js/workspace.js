/* Map-first workspace: stable data dock, shared menus and optional AI assistant. */
(function() {
  'use strict';
  const GIS = window.GIS = window.GIS || {};
  const paths = {"map":"/assets/ui-icons/workspace-map.png","folder":"/assets/ui-icons/workspace-folder.png","layers":"/assets/ui-icons/workspace-layers.png","tool":"/assets/ui-icons/workspace-tool.png","ai":"/assets/ui-icons/workspace-ai.png","globe":"/assets/ui-icons/workspace-globe.png","upload":"/assets/ui-icons/workspace-upload.png","history":"/assets/ui-icons/workspace-history.png","settings":"/assets/ui-icons/workspace-settings.png","close":"/assets/ui-icons/workspace-close.png","chevron":"/assets/ui-icons/workspace-chevron.png"};
  function icon(name) {
    return '<span class="ui-icon" aria-hidden="true" style="--ui-icon-image:url(' + paths[name] + ')"></span>';
  }
  function panelBounds(width) {
    const map = document.querySelector('.map-area');
    const r = map ? map.getBoundingClientRect() : {left:12, right:window.innerWidth-12};
    const top = document.querySelector('.workspace-topbar');
    const status = document.querySelector('.workspace-statusbar');
    let left = r.left + 12, right = r.right - 12;
    const assistant = document.querySelector('.chat-panel');
    if (assistant && !assistant.hidden) {
      const availableLeft = assistant.getBoundingClientRect().right + 12;
      if (right - availableLeft >= width) left = Math.max(left, availableLeft);
    }
    if (right - left < width) { left = 12; right = window.innerWidth - 12; }
    return {left:left, right:right, top:top ? top.getBoundingClientRect().bottom+12 : 12,
      bottom:status ? status.getBoundingClientRect().top-12 : window.innerHeight-12};
  }
  function clampPanel(container, left, top, fallbackWidth) {
    const width = container.offsetWidth || Math.min(fallbackWidth || 380, window.innerWidth-24);
    const height = container.offsetHeight || 300;
    const bounds = panelBounds(width);
    return [Math.max(bounds.left, Math.min(bounds.right-width, left)),
      Math.max(bounds.top, Math.min(bounds.bottom-height, top))];
  }
  function centerPanel(container, fallbackWidth) {
    container.style.position = 'fixed';
    container.style.zIndex = '1200';
    const width = container.offsetWidth || Math.min(fallbackWidth || 380, window.innerWidth-24);
    const bounds = panelBounds(width);
    const pos = clampPanel(container, bounds.left+(bounds.right-bounds.left-width)/2, bounds.top+12, width);
    container.style.left = pos[0]+'px'; container.style.top = pos[1]+'px';
    container.style.transform = 'none';
    return pos;
  }
  function preparePanel(panelId, headerId, closeId, label) {
    const panel = document.getElementById(panelId);
    const header = document.getElementById(headerId);
    const close = document.getElementById(closeId);
    if (!panel || !header || !close) return;
    panel.classList.add('workspace-floating-panel');
    header.classList.add('workspace-panel-heading');
    close.title = '关闭'+label;
    close.setAttribute('aria-label', close.title);
    makeResizable(panel, label);
    panel.querySelectorAll('.spatial-field').forEach(function(field) {
      const labelEl = field.querySelector('label');
      const input = field.querySelector('input[id], select[id], textarea[id]');
      if (labelEl && input && !labelEl.contains(input)) labelEl.htmlFor = input.id;
    });
    if (header.querySelector('.workspace-panel-fold')) return;
    const fold = document.createElement('button');
    fold.className = 'workspace-panel-fold workspace-icon-btn';
    fold.type = 'button';
    fold.innerHTML = "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-f7cda24f40e5.png')\"></span>";
    function update(folded) {
      fold.title = (folded ? '展开' : '折叠')+label;
      fold.setAttribute('aria-label', fold.title);
      fold.setAttribute('aria-expanded', String(!folded));
    }
    update(false);
    fold.onclick = function() {
      const folded = panel.classList.toggle('workspace-panel-folded');
      update(folded);
      if (!folded) keepPanelsVisible();
    };
    header.insertBefore(fold, close);
  }
  function makeResizable(panel, label) {
    if (panel.querySelector('.workspace-window-resize')) return;
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'workspace-window-resize';
    handle.title = '拖动右下角调整窗口大小；方向键调整，双击恢复默认';
    handle.setAttribute('aria-label', '调整'+label+'窗口大小');
    handle.setAttribute('aria-controls', panel.id);
    const defaultWidth = panel.style.width;
    const defaultHeight = panel.style.height;
    let drag = null;
    function resize(width, height) {
      const r = panel.getBoundingClientRect();
      const status = document.querySelector('.workspace-statusbar');
      const maxWidth = Math.max(160, window.innerWidth-r.left-12);
      const maxHeight = Math.max(120, (status ? status.getBoundingClientRect().top : window.innerHeight)-r.top-12);
      const isTool = panel.matches('.spatial-panel, .network-panel');
      panel.style.width = Math.min(maxWidth, Math.max(Math.min(isTool ? 320 : 220,maxWidth),width))+'px';
      panel.style.height = Math.min(maxHeight, Math.max(Math.min(isTool ? 320 : 160,maxHeight),height))+'px';
    }
    handle.addEventListener('pointerdown', function(e) {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      const r = panel.getBoundingClientRect();
      drag = {id:e.pointerId, x:e.clientX, y:e.clientY, width:r.width, height:r.height};
      handle.setPointerCapture(e.pointerId);
      document.documentElement.classList.add('workspace-window-resizing');
    });
    handle.addEventListener('pointermove', function(e) {
      if (drag && drag.id === e.pointerId) resize(drag.width+e.clientX-drag.x, drag.height+e.clientY-drag.y);
    });
    function finish(e) {
      if (!drag || drag.id !== e.pointerId) return;
      drag = null;
      document.documentElement.classList.remove('workspace-window-resizing');
    }
    handle.addEventListener('pointerup', finish);
    handle.addEventListener('pointercancel', finish);
    handle.addEventListener('lostpointercapture', finish);
    handle.addEventListener('keydown', function(e) {
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const r = panel.getBoundingClientRect();
      resize(r.width+(e.key === 'ArrowRight' ? 20 : e.key === 'ArrowLeft' ? -20 : 0),
        r.height+(e.key === 'ArrowDown' ? 20 : e.key === 'ArrowUp' ? -20 : 0));
    });
    handle.addEventListener('dblclick', function() { panel.style.width=defaultWidth; panel.style.height=defaultHeight; keepPanelsVisible(); });
    panel.appendChild(handle);
  }
  function toolFeedback(panelId, result, error) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    panel.setAttribute('aria-busy', 'false');
    panel.querySelectorAll('.spatial-run-btn, .spatial-tab').forEach(function(btn) { btn.disabled=false; });
    let output = panel.querySelector('.workspace-tool-feedback');
    if (!output) {
      output = document.createElement('section');
      output.className = 'workspace-tool-feedback';
      output.setAttribute('role', 'status');
      output.setAttribute('aria-live', 'polite');
      output.innerHTML = '<strong></strong><p></p>';
      panel.insertBefore(output, panel.querySelector('.workspace-window-resize'));
    }
    const rawMessage = error ? error.message || String(error) : String(result && result.response || '处理结束，未返回说明。');
    const statLabels = {count:'记录数', non_null:'有效值', null:'空值', min:'最小值', max:'最大值', mean:'平均值', sum:'总和', std:'标准差'};
    const message = rawMessage.replace(/^\s*📊\s*/u, '').replace(/^(\s*)(count|non_null|null|min|max|mean|sum|std):/gm,
      function(_, space, key) { return space+statLabels[key]+'：'; });
    const failed = !!error || (result && result.ok === false) || /^(?:[^\n:：]{0,24}失败[:：]|未找到|工具执行失败|错误[:：])/.test(message.trim());
    const count = result && result.layers ? result.layers.length : 0;
    output.querySelector('strong').textContent = failed ? '未完成' : count ? '已完成 · 新增 '+count+' 个图层' : '结果已返回';
    output.querySelector('p').textContent = message;
    output.dataset.state = failed ? 'error' : 'complete';
    const existing = panel.querySelector('.spatial-result');
    if (existing) existing.style.display='none';
    return !failed;
  }
  function toolPending(panelId) {
    toolFeedback(panelId, {response:'处理完成后，结果和新增图层会显示在这里。'});
    const panel = document.getElementById(panelId);
    panel.setAttribute('aria-busy', 'true');
    panel.querySelector('.workspace-tool-feedback strong').textContent='正在处理…';
    panel.querySelectorAll('.spatial-run-btn, .spatial-tab').forEach(function(btn) { btn.disabled=true; });
  }
  function expandPanel(panelId) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    panel.classList.remove('workspace-panel-folded');
    const fold = panel.querySelector('.workspace-panel-fold');
    if (fold) {
      fold.title = fold.title.replace(/^展开/, '折叠');
      fold.setAttribute('aria-label', fold.title);
      fold.setAttribute('aria-expanded', 'true');
    }
  }
  function keepPanelsVisible() {
    document.querySelectorAll('#spatialPanelContainer, #networkPanelContainer, #spatialStatsPanelContainer, #rasterToolsPanelContainer, #debugPanel').forEach(function(container) {
      if (!container.getClientRects().length || !container.offsetHeight) return;
      const r = container.getBoundingClientRect();
      const pos = clampPanel(container, r.left, r.top, r.width);
      container.style.left = pos[0]+'px'; container.style.top = pos[1]+'px';
    });
  }
  let activeTab = 'browser';
  let dock, chat, body, layerPanel, divider;
  let dockWidth = 340;
  function widthLimits() {
    const available = body.clientWidth - 68;
    const max = Math.max(180, Math.min(600, available - (window.innerWidth > 700 ? 396 : 36)));
    return {min: Math.min(260, max), max: max};
  }
  function setDockWidth(width, persist) {
    const limits = widthLimits();
    dockWidth = Math.max(limits.min, Math.min(limits.max, width));
    body.style.setProperty('--workspace-dock-width', dockWidth + 'px');
    divider.setAttribute('aria-valuemin', String(limits.min));
    divider.setAttribute('aria-valuemax', String(limits.max));
    divider.setAttribute('aria-valuenow', String(Math.round(dockWidth)));
    if (persist) { try { localStorage.setItem('gis_workspace_dock_width', String(dockWidth)); } catch (_) {} }
    invalidate();
  }
  function initDivider() {
    divider = document.createElement('div');
    divider.className = 'workspace-divider';
    divider.tabIndex = 0;
    divider.setAttribute('role', 'separator');
    divider.setAttribute('aria-orientation', 'vertical');
    divider.setAttribute('aria-label', '调整侧面板宽度');
    divider.title = '拖动调整宽度，双击恢复默认；也可使用左右方向键';
    body.insertBefore(divider, body.querySelector('.main-content'));
    let drag = null;
    function finish(e) {
      if (!drag || e.pointerId !== drag.id) return;
      drag = null;
      body.classList.remove('workspace-resizing');
      setDockWidth(dockWidth, true);
    }
    divider.addEventListener('pointerdown', function(e) {
      if (e.button !== 0) return;
      e.preventDefault();
      drag = {id: e.pointerId, x: e.clientX, width: dockWidth};
      divider.setPointerCapture(e.pointerId);
      body.classList.add('workspace-resizing');
    });
    divider.addEventListener('pointermove', function(e) {
      if (drag && e.pointerId === drag.id) setDockWidth(drag.width + e.clientX - drag.x, false);
    });
    divider.addEventListener('pointerup', finish);
    divider.addEventListener('pointercancel', finish);
    divider.addEventListener('lostpointercapture', finish);
    divider.addEventListener('dblclick', function() { setDockWidth(340, true); });
    divider.addEventListener('keydown', function(e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' && e.key !== 'Home') return;
      e.preventDefault();
      setDockWidth(e.key === 'Home' ? 340 : dockWidth + (e.key === 'ArrowRight' ? 20 : -20), true);
    });
    let saved = 340;
    try { saved = Number(localStorage.getItem('gis_workspace_dock_width')) || 340; } catch (_) {}
    setDockWidth(saved, false);
  }
  function invalidate() {
    if (divider) divider.hidden = chat.hidden && dock.hidden;
    requestAnimationFrame(function() {
      keepPanelsVisible();
      if (GIS.map) GIS.map.invalidateSize();
      const viewer = GIS.renderers && GIS.renderers.getViewer();
      if (viewer) { viewer.resize(); viewer.scene.requestRender(); }
    });
  }
  function setTab(name) {
    toggleAI(false);
    if (name !== 'browser' && GIS.geosource) GIS.geosource.closeWorldMap();
    activeTab = name;
    dock.hidden = false;
    document.querySelectorAll('[data-dock-tab]').forEach(function(btn) {
      const selected = btn.dataset.dockTab === name;
      btn.classList.toggle('active', selected);
      btn.setAttribute('aria-pressed', String(selected));
    });
    document.querySelectorAll('[data-dock-pane]').forEach(function(pane) { pane.hidden = pane.dataset.dockPane !== name; });
    document.getElementById('workspaceDockTitle').textContent = {browser:'数据',layers:'图层',tools:'处理工具'}[name];
    document.getElementById('workspaceDockClose').title = '收起' + {browser:'数据',layers:'图层',tools:'处理'}[name] + '面板';
    document.getElementById('toggleLayerPanel').classList.toggle('active', name === 'layers');
    invalidate();
  }
  function toggleLayers() {
    if (chat.hidden && !dock.hidden && activeTab === 'layers') closeDock();
    else setTab('layers');
  }
  function closeDock() {
    dock.hidden = true;
    document.querySelectorAll('[data-dock-tab]').forEach(function(btn) {
      btn.classList.remove('active');
      btn.setAttribute('aria-pressed', 'false');
    });
    document.getElementById('toggleLayerPanel').classList.remove('active');
    invalidate();
  }
  function toggleAI(force) {
    const show = typeof force === 'boolean' ? force : chat.hidden;
    chat.hidden = !show;
    document.body.classList.toggle('workspace-ai-open', show);
    dock.inert = show;
    document.querySelectorAll('[data-dock-tab]').forEach(function(btn) {
      const selected = !show && !dock.hidden && btn.dataset.dockTab === activeTab;
      btn.classList.toggle('active', selected);
      btn.setAttribute('aria-pressed', String(selected));
    });
    document.querySelectorAll('[data-workspace-action="ai"]').forEach(function(btn) {
      btn.classList.toggle('active', show);
      btn.setAttribute('aria-pressed', String(show));
      btn.setAttribute('aria-expanded', String(show));
      btn.title = show ? '收起 AI 助手' : '展开 AI 助手';
    });
    invalidate();
  }
  function button(action, label, glyph, detail) {
    return '<button class="workspace-entry" data-workspace-action="'+action+'">'+icon(glyph)+'<span>'+label+(detail?'<small>'+detail+'</small>':'')+'</span>'+icon('chevron')+'</button>';
  }
  function init() {
    body = document.querySelector('.app-body');
    chat = document.querySelector('.chat-panel');
    layerPanel = document.getElementById('mapLayerPanel');
    if (!body || !chat || !layerPanel) return;
    document.body.classList.add('workbench');
    document.documentElement.classList.add('gis-workspace');
    GIS.workspace = {toggleLayers:toggleLayers, setTab:setTab, toggleAI:toggleAI, closeDock:closeDock,
      panelBounds:panelBounds, clampPanel:clampPanel, centerPanel:centerPanel,
      preparePanel:preparePanel, expandPanel:expandPanel, toolFeedback:toolFeedback, toolPending:toolPending};
    const app = document.getElementById('app');
    const top = document.createElement('header');
    top.className = 'workspace-topbar';
    top.innerHTML = '<a class="workspace-brand" href="#" aria-label="GIS WorkTable 工作台">'+icon('map')+'<span>GIS<span class="workspace-brand-light"> WorkTable</span></span></a><div class="workspace-top-actions"><span class="workspace-project">空间工作台</span><button class="workspace-top-btn" data-workspace-action="data">'+icon('globe')+'<span>添加数据</span></button><button class="workspace-top-btn" data-workspace-action="settings" title="设置">'+icon('settings')+'</button></div>';
    const originalLogo = chat.querySelector('.chat-header > .ui-logo');
    if (originalLogo) {
      const logo = originalLogo.cloneNode(true);
      logo.removeAttribute('style');
      logo.setAttribute('aria-hidden', 'true');
      top.querySelector('.workspace-brand').replaceChildren(logo);
    }
    const menu = document.getElementById('mapMenuBar');
    top.insertBefore(menu, top.querySelector('.workspace-top-actions'));
    app.insertBefore(top, body);
    top.querySelector('.workspace-brand').addEventListener('click', function(e) { e.preventDefault(); setTab('browser'); });

    const rail = document.createElement('nav');
    rail.className = 'workspace-rail';
    rail.setAttribute('aria-label', '工作区面板');
    rail.innerHTML = ['browser','layers','tools'].map(function(name,i) {
      return '<button data-dock-tab="'+name+'" title="'+['数据','图层管理','处理工具'][i]+'">'+icon(['folder','layers','tool'][i])+'<span>'+['数据','图层','处理'][i]+'</span></button>';
    }).join('')+'<button data-workspace-action="ai" aria-pressed="false" aria-expanded="false" title="展开 AI 助手">'+icon('ai')+'<span>AI 助手</span></button><div class="workspace-rail-spacer"></div>';
    dock = document.createElement('aside');
    dock.className = 'workspace-dock';
    dock.innerHTML = '<div class="workspace-dock-header"><strong id="workspaceDockTitle">数据</strong><button id="workspaceDockClose" class="workspace-icon-btn" title="收起数据面板">'+icon('close')+'</button></div><section data-dock-pane="browser" class="workspace-browser"><p class="workspace-pane-intro">从数据获取开始，在地图上检查分析结果。</p><button class="workspace-discovery" data-workspace-action="world"><span class="workspace-discovery-heading">'+icon('globe')+'<strong>全球数据</strong></span><span class="workspace-discovery-detail">按国家和地区探索数据源，选择服务接入工作台。</span><span class="workspace-discovery-link">打开数据地图 '+icon('chevron')+'</span></button><div class="workspace-search"><input id="workspaceDataSearch" type="search" placeholder="按关键词检索数据" aria-label="搜索空间数据源"><button data-workspace-action="search" title="检索数据">'+icon('chevron')+'</button></div><p class="workspace-section-label">接入工作台</p>'+button('upload','导入本地文件','upload','GeoJSON、Shapefile、栅格等')+button('data','目录检索','layers','按主题、地区和协议筛选')+button('connector','数据源连接器','settings','配置账号或添加在线地址')+'<p class="workspace-section-label">继续工作</p>'+button('projects','会话与项目','history','回到已有工作')+'</section><section data-dock-pane="layers" class="workspace-layers" hidden></section><section data-dock-pane="tools" class="workspace-tools" hidden><p class="workspace-pane-intro">选取工具，设置参数后执行。计算结果会回到地图和图层列表。</p>'+button('spatial','空间分析','layers','缓冲、裁剪、叠置')+button('network','网络分析','tool','路径、服务区、最近设施')+button('statistics','空间统计','tool','统计与空间分布')+button('raster','栅格处理','map','地形、波段与栅格计算')+button('history','处理历史','history','查看执行记录并重跑')+'</section>';
    layerPanel.classList.remove('collapsed');
    dock.querySelector('[data-dock-pane="layers"]').appendChild(layerPanel);
    body.insertBefore(dock, body.firstChild);
    body.insertBefore(rail, dock);
    body.insertBefore(chat, dock.nextSibling);
    initDivider();
    const mapTools = document.getElementById('mapZoomControls');
    if (mapTools) {
      mapTools.setAttribute('role', 'toolbar');
      mapTools.setAttribute('aria-label', '地图操作');
    }
    const oldLogo = chat.querySelector('.chat-header > .ui-logo');
    if (oldLogo) {
      const heading = document.createElement('div');
      heading.className = 'workspace-ai-heading';
      heading.innerHTML = icon('ai')+'<span>AI 助手<small>用自然语言完成空间任务</small></span>';
      oldLogo.replaceWith(heading);
    }
    const closeAI = document.createElement('button');
    closeAI.className = 'workspace-icon-btn';
    closeAI.title = '收起 AI 助手';
    closeAI.innerHTML = icon('close');
    closeAI.onclick = function() { toggleAI(false); };
    chat.querySelector('.chat-header > div:last-child').appendChild(closeAI);
    const input = document.getElementById('chatInput');
    input.placeholder = '描述你的空间任务，或输入 / 选择工具…';
    const connector = document.getElementById('connectorPanel');
    if (connector) document.body.appendChild(connector);
    const status = document.createElement('div');
    status.className = 'workspace-statusbar';
    status.innerHTML = '<span class="workspace-status-dot"></span><span>本地工作台</span><span class="workspace-status-hint">2D / 3D 地图视图</span>';
    const coords = document.getElementById('mapCoords');
    if (coords) {
      coords.textContent = 'WGS-84 · 经度 -- · 纬度 --';
      status.insertBefore(coords, status.querySelector('.workspace-status-hint'));
    }
    app.appendChild(status);
    document.getElementById('workspaceDockClose').onclick = closeDock;
    document.getElementById('workspaceDataSearch').addEventListener('keydown', function(e) { if (e.key === 'Enter') run('search'); });
    document.addEventListener('click', function(e) {
      const tab = e.target.closest('[data-dock-tab]');
      if (tab) { setTab(tab.dataset.dockTab); return; }
      const action = e.target.closest('[data-workspace-action]');
      if (action) run(action.dataset.workspaceAction);
    });
    setTab('browser');
    toggleAI(false);
    window.addEventListener('resize', function() { setDockWidth(dockWidth, false); });
  }
  function run(action) {
    if (action === 'ai') toggleAI();
    else if (action === 'data') GIS.geosource.show();
    else if (action === 'world') GIS.geosource.openWorldMap();
    else if (action === 'upload') document.getElementById('uploadTrigger').click();
    else if (action === 'settings' || action === 'connector') {
      document.getElementById(action === 'connector' ? 'connectorBtn' : 'settingsBtn').click();
    } else if (action === 'search') {
      document.getElementById('geosourceKeyword').value = document.getElementById('workspaceDataSearch').value;
      GIS.geosource.doSearch(1);
      GIS.geosource.show();
    } else if (action === 'projects') { toggleAI(true); document.getElementById('historyBtn').click(); }
    else if (action === 'spatial') GIS.spatial.toggle();
    else if (action === 'network') GIS.network.toggle();
    else if (action === 'statistics') GIS.spatialStats.toggle();
    else if (action === 'raster') GIS.rasterTools.openWith('slope');
    else if (action === 'history') document.getElementById('toggleHistoryPanel').click();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
