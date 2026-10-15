/**
 * ============================================
 *  GIS AI WorkTable — 聊天模块
 *  消息渲染、输入框绑定、发送逻辑
 * ============================================
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

// 所有外部链接新标签打开
var _linkRenderer = null;
if (typeof marked !== 'undefined') {
  _linkRenderer = new marked.Renderer();
  _linkRenderer.link = function(token) {
    return '<a href="' + token.href + '" target="_blank" rel="noopener noreferrer" class="chat-markdown-link">' + token.text + '</a>';
  };
}

//将GIS命名空间赋值给常量GIS，相当于全局变量
  const GIS = window.GIS;

  /** @type {HTMLElement} */
  let messagesContainer = null;
  let followOutput = true;
  function _currentSessionIdSafe() {
  // 统一的会话 ID 解析（模块级，任何闭包可安全调用）
  try {
    return (window.GIS && window.GIS.project && window.GIS.project.getCurrentSessionId)
      ? (window.GIS.project.getCurrentSessionId() || 'default')
      : 'default';
  } catch (e) { return 'default'; }
}

function scrollMessages() {
    if (messagesContainer && followOutput) messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }
  let inputEl = null;
  let sendBtn = null;

  // Chip 命令名 → 技能标签映射（用于 force_skills）
  const CHIP_TO_SKILL = {
    buffer: 'geometry', intersection: 'geometry', union: 'geometry',
    difference: 'geometry', centroid: 'geometry', simplify: 'geometry',
    clip: 'geometry', dissolve: 'geometry',
    make_valid: 'geometry',
    area: 'analysis', length: 'analysis',
    aoi: 'aoi',
    boundary: 'datav',
    heatmap: 'heatmap',
    plot: 'visualization',
    amap: 'amap'
  };
  // 每个命令的 SVG icon（14x14，currentColor）
  const SLASH_ICONS = {
    geosource: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-c85a4814bdb4.png')\"></span>",
    buffer: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-8f5a4112e257.png')\"></span>",
    intersection: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-41795f2d789c.png')\"></span>",
    union: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-6b5b6eae0c0a.png')\"></span>",
    difference: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-9478f11a1237.png')\"></span>",
    centroid: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-284e841b1c7c.png')\"></span>",
    simplify: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-c18efbbf2ab6.png')\"></span>",
    area: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-a4e0e193fc8e.png')\"></span>",
    length: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-2b5ecc26521d.png')\"></span>",
    make_valid: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-13f024058ec9.png')\"></span>",
    aoi: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-09e5528af4cd.png')\"></span>",
    boundary: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-00fe3e193028.png')\"></span>",
    heatmap: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-95364f06eede.png')\"></span>",
    plot: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-051bf27e596b.png')\"></span>",
    amap: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-dc13a9e486f1.png')\"></span>",
    export: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-f1cd017de809.png')\"></span>",
    chart: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-0742652879d1.png')\"></span>",
    network: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-72a2f58db0ce.png')\"></span>",
    help: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-ef31a201422b.png')\"></span>",
    clip: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-00ece071fd14.png')\"></span>",
    dissolve: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-ed491c2db219.png')\"></span>",
    join: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-b8514e62df84.png')\"></span>",
    merge: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-6390b2c5ce5d.png')\"></span>",
    split: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-45665d1fa471.png')\"></span>",
    geocode: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-58451fcc0ae2.png')\"></span>",
    select: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-a519c972ec87.png')\"></span>",
    sample: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-5544ac241c3e.png')\"></span>",
    near: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-806a1de13166.png')\"></span>",
    cluster: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-34a533003eaf.png')\"></span>",
    voronoi: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-bfd3a4ec37dc.png')\"></span>",
    stats: "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-2a93cc365cca.png')\"></span>",
  };

  const SLASH_COMMANDS = [
    { name: 'help', label: '操作手册', desc: '打开系统操作手册', prompt: '' },
    { name: 'geosource', label: '全球数据源', desc: '全球 2198+ 空间服务与图层检索', prompt: '帮我检索全球 GIS 空间服务：', direct: function () { if (window.GIS.geosource) GIS.geosource.show(); } },
    { name: 'buffer', label: '缓冲区分析', desc: '为图层创建指定距离的缓冲区', prompt: '为图层 {图层名} 创建 {距离} 米的缓冲区，结果加载到地图上', direct: function () { GIS.spatial.openTab('buffer') },},
    { name: 'intersection', label: '空间相交', desc: '两个图层的相交分析', prompt: '对 {图层A} 和 {图层B} 做空间相交分析，结果加载到地图上', direct: function () { GIS.spatial.openTab('overlay') },},
    { name: 'union', label: '空间合并', desc: '合并两个图层的几何', prompt: '合并 {图层A} 和 {图层B}，结果加载到地图上', direct: function () { GIS.spatial.openTab('overlay') },},
    { name: 'difference', label: '空间差异', desc: '一个图层减去另一个图层', prompt: '用 {图层A} 减去 {图层B}，结果加载到地图上', direct: function () { GIS.spatial.openTab('overlay') },},
    { name: 'centroid', label: '提取质心', desc: '提取图层的中心点', prompt: '提取 {图层名} 的质心/中心点，结果加载到地图上', direct: function () { GIS.spatial.openTab('geom') },},
    { name: 'simplify', label: '简化几何', desc: '简化图层几何，减少顶点数', prompt: '简化 {图层名} 的几何，简化容差设为 {容差}，结果加载到地图上', direct: function () { GIS.spatial.openTab('geom') },},
    { name: 'clip', label: '图层裁剪', desc: '用一个图层裁剪另一个图层', prompt: '用 {裁剪图层} 裁剪 {被裁剪图层}，结果加载到地图上', direct: function () { GIS.spatial.openTab('clip') },},
    { name: 'dissolve', label: '属性融合', desc: '按属性字段融合图层几何', prompt: '按字段 {字段名} 融合图层 {图层名}，结果加载到地图上', direct: function () { GIS.spatial.openTab('geom') },},
    { name: 'join', label: '空间连接', desc: '按空间关系连接两个图层的属性', prompt: '将 {连接图层} 的属性按空间关系连接到 {目标图层} 上，结果加载到地图', direct: function () { GIS.spatial.openTab('stats') },},
    { name: 'merge', label: '图层合并', desc: '行级合并多个图层为一个', prompt: '合并图层 {图层A, 图层B}，结果加载到地图', direct: function () { GIS.spatial.openTab('geom') },},
    { name: 'split', label: '图层拆分', desc: '按属性字段拆分图层', prompt: '按字段 {字段名} 拆分图层 {图层名}', direct: function () { if (GIS.rasterTools && GIS.rasterTools.openWith) GIS.rasterTools.openWith('split'); } },
    { name: 'geocode', label: '反向地理编码', desc: '坐标转地址 / 地址批量转坐标', prompt: '将坐标 ({经度},{纬度}) 转为地址', direct: function () { if (GIS.rasterTools && GIS.rasterTools.openWith) GIS.rasterTools.openWith('geocode'); } },
    { name: 'select', label: '空间选择', desc: '按空间关系选择图层要素', prompt: '选择 {目标图层} 中与 {源图层} 相交的所有要素，结果加载到地图', direct: function () { GIS.spatial.openTab('select') },},
    { name: 'sample', label: '随机采样', desc: '从图层随机采样要素', prompt: '从 {图层名} 随机采样 {数量} 个要素，结果加载到地图', direct: function () { GIS.spatial.openTab('select') },},
    { name: 'near', label: '邻近查找', desc: '查找距离目标图层一定范围内的要素', prompt: '查找 {目标图层} 中距离 {源图层} {距离} 米以内的要素，结果加载到地图', direct: function () { GIS.spatial.openTab('select') },},
    { name: 'cluster', label: '空间聚类', desc: 'DBSCAN 点聚类分析', prompt: '对 {图层名} 做空间聚类，eps={半径} min_samples={最少点数}，结果加载到地图', direct: function () { GIS.spatial.openTab('geom') },},
    { name: 'voronoi', label: '泰森多边形', desc: '根据点图层生成 Voronoi 图', prompt: '为 {图层名} 生成泰森多边形，结果加载到地图', direct: function () { GIS.spatial.openTab('geom') },},
    { name: 'stats', label: '字段统计', desc: '统计图层数值字段', prompt: '统计 {图层名} 的 {字段名} 字段，给出 min/max/mean/sum/std', direct: function () { GIS.spatial.openTab('stats') },},
    { name: 'area', label: '计算面积', desc: '计算图层各要素的面积', prompt: '计算 {图层名} 每个要素的面积，结果用表格显示', direct: function () { GIS.spatial.openTab('stats') },},
    { name: 'length', label: '计算长度', desc: '计算线图层的长度', prompt: '计算 {图层名} 每个要素的长度，结果用表格显示', direct: function () { GIS.spatial.openTab('geom') },},
    { name: 'make_valid', label: '修复几何', desc: '修复无效的几何图形', prompt: '修复 {图层名} 中无效的几何图形，将修复后的结果加载到地图上', direct: function () { GIS.spatial.openTab('geom') },},
    { name: 'aoi', label: 'AOI 边界', desc: '提取地点建筑轮廓', prompt: '搜索 {地点名称} 的 AOI 建筑轮廓并提取' },
    { name: 'boundary', label: '行政边界', desc: '获取行政区划边界', prompt: '获取 {省/市/区} 的行政边界并加载到地图', direct: function () { GIS.spatial.openTab('data') },},
    { name: 'heatmap', label: '热力图', desc: '从点数据生成热力图', prompt: '为 {图层名} 生成热力图', direct: function () { if (GIS.rasterTools && GIS.rasterTools.openWith) GIS.rasterTools.openWith('heatmap'); } },
    { name: 'plot', label: '统计图表', desc: '生成数据统计图表', prompt: '对 {图层名} 的 {字段} 生成统计图表' },
    { name: 'export', label: '导出SHP', desc: '导出图层为Shapefile或GeoJSON', prompt: '将 {图层名} 导出为 {格式} 文件', direct: function () { var b = document.getElementById('toggleLayerPanel'); if (b) b.click(); } },
    { name: 'chart', label: '图表分析', desc: '图层属性统计图表（柱状/饼图/散点）', prompt: '对 {图层名} 的 {字段} 生成 {图表类型} 图' },
    { name: 'amap', label: '高德', desc: '搜索POI/查天气/地址转坐标', prompt: '搜索 {关键词} 的 POI 数据，每页25条最多200条，结果加载到地图', direct: function () { GIS.spatial.openTab('data') },},
    { name: 'network', label: '网络分析', desc: '最短路径/服务区/最近设施', prompt: '从 {起点} 到 {终点} 的最短路径，用广州路网分析', direct: function () { if (GIS.network && GIS.network.toggle) GIS.network.toggle(); } },
    { name: 'slope', label: '坡度分析', desc: '对 DEM 做坡度分析', prompt: '对 {图层名} 做坡度分析，结果叠加到地图上', direct: function () { GIS.rasterTools.openWith('slope') },},
    { name: 'aspect', label: '坡向分析', desc: '对 DEM 做坡向分析', prompt: '对 {图层名} 做坡向分析，结果叠加到地图上', direct: function () { GIS.rasterTools.openWith('aspect') },},
    { name: 'hillshade', label: '山体阴影', desc: '生成 DEM 山体阴影', prompt: '生成 {图层名} 的山体阴影，结果叠加到地图上', direct: function () { GIS.rasterTools.openWith('hillshade') },},
    { name: 'contour', label: '等高线', desc: '从 DEM 提取等高线', prompt: '从 {图层名} 提取等高线，等高距 {间隔} 米，结果加载到地图', direct: function () { GIS.rasterTools.openWith('contour') },},
    { name: 'ndvi', label: 'NDVI 计算', desc: '计算植被指数 NDVI', prompt: '计算 {图层名} 的 NDVI，结果叠加到地图', direct: function () { GIS.rasterTools.openWith('ndvi') },},
    { name: 'rastercalc', label: '栅格计算器', desc: '波段数学运算', prompt: '用表达式 {表达式} 对 {图层名} 做栅格计算，结果叠加到地图', direct: function () { GIS.rasterTools.openWith('rastercalc') },},
    { name: 'interpolate', label: '空间插值', desc: 'IDW / RBF 插值分析', prompt: '对 {图层名} 的 {字段} 做 {方法} 插值，结果叠加到地图', direct: function () { GIS.rasterTools.openWith('interpolate') },},
    { name: 'hydrology', label: '水文分析', desc: '流向/流量/河网提取', prompt: '对 {图层名} 做水文分析，提取河网，结果加载到地图', direct: function () { GIS.rasterTools.openWith('hydrology') },},
    { name: 'topology', label: '拓扑检查', desc: '检查重叠/缝隙/无效几何', prompt: '对 {图层名} 做拓扑检查，标记所有拓扑错误', direct: function () { GIS.rasterTools.openWith('topology') },},
    { name: 'coord-convert', label: '坐标转换', desc: '经纬度与投影坐标互转', prompt: '将坐标 {经度},{纬度} 转为 Web Mercator', direct: function () { GIS.rasterTools.openWith('coord') },},
    { name: 'edit-vertices', label: '折点编辑', desc: '编辑图层的折点', prompt: '编辑 {图层名} 的折点', direct: function () { var b = document.getElementById('toggleLayerPanel'); if (b) b.click(); } },
    { name: 'snapping', label: '捕捉开关', desc: '启用/关闭绘制捕捉', prompt: '启用绘制捕捉' },
    { name: 'legend', label: '添加图例', desc: '为分级/唯一值图层添加图例', prompt: '给 {图层名} 添加图例', direct: function () { var b = document.getElementById('toggleLayerPanel'); if (b) b.click(); } },
        { name: '3d', label: '3D 地球', desc: '2D 地图 / 3D 地球切换', prompt: '', direct: function () { if (window.GIS.renderers && GIS.renderers.toggle3D) GIS.renderers.toggle3D(); } },
{ name: 'north-arrow', label: '指北针', desc: '添加/移除指北针', prompt: '添加指北针', direct: function () { if (GIS.map && GIS.map.showNorthArrow) GIS.map.showNorthArrow(); },},
    { name: 'labels', label: '要素标注', desc: '给图层添加文字标注', prompt: '给 {图层名} 添加标注，显示 {字段} 内容', direct: function () { var b = document.getElementById('toggleLayerPanel'); if (b) b.click(); } },
    { name: 'export-map', label: '导出地图', desc: '导出当前地图为 PNG', prompt: '导出当前地图为 PNG', direct: function () { if (GIS.map && GIS.map.exportMap) GIS.map.exportMap('png'); } },
    { name: 'export-pdf', label: '导出 PDF', desc: '导出当前地图为 PDF', prompt: '导出当前地图为 PDF', direct: function () { if (GIS.map && GIS.map.exportPdf) GIS.map.exportPdf('地图导出'); } },
  ];

  let _slashFiltered = [];      // 当前过滤后的列表
  let _slashIndex = -1;         // 选中索引
  let _slashActive = false;     // 菜单是否打开
  // ---- Skill Chip 标签系统 ----
  let _skillChips = [];         // [{name, label, prompt}]
  // ---- 图层附件（分析按钮→暂存到输入框上方） ----
  let _pendingLayer = null;     // { name, type, coords, count, geojson, ... }
  let _quotedMessage = null;     // { text, time } 用户点击"引用"暂存的 AI 回复，随下一条消息发送

  /**
   * 初始化聊天模块
   * 绑定 DOM 元素和事件
   */
  function init() {
    messagesContainer = document.getElementById('chatMessages');
    if (messagesContainer) messagesContainer.addEventListener('scroll', function() {
      followOutput = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight < 72;
    }, { passive: true });
    inputEl = document.getElementById('chatInput');
    sendBtn = document.getElementById('sendBtn');

    if (!messagesContainer) {
      console.warn('[GIS Chat] #chatMessages 不存在');
    }

    if (inputEl) {
      inputEl.addEventListener('keydown', (e) => {
        // Backspace 删除最后一个 chip
        if (e.key === 'Backspace' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
          if (inputEl.selectionStart === 0 && inputEl.selectionEnd === 0 && _skillChips.length > 0) {
            e.preventDefault();
            _removeLastChip();
            return;
          }
        }
        // 斜杠菜单打开时，Enter 交给 _handleSlashKeydown 处理选择命令
        if (_slashActive) return;
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          send();
        }
      });
      // 斜杠命令：输入/弹出菜单，↑↓选择，Enter/Tab确认，Esc取消
      inputEl.addEventListener('keydown', _handleSlashKeydown);
      inputEl.addEventListener('input', _handleSlashInput);
      // 点击外部关闭菜单
      document.addEventListener('click', _handleSlashClickOutside);
    }

    if (sendBtn) {
      sendBtn.addEventListener('click', function() { send(); });
    }

    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) {
      stopBtn.disabled = true;
      stopBtn.classList.remove('is-running');
      stopBtn.title = '停止 (无运行中任务)';
      stopBtn.addEventListener('click', function() {
        if (!window._aiRunning || stopBtn.disabled) {
          return;
        }
        window._aiRunning = false;
        // 先发取消请求到后端（keepalive 确保页面卸载时也能发送），再中断 SSE 连接
        fetch(window.GIS.api.BASE_URL + '/api/cancel?session_id=' + encodeURIComponent(_currentSessionIdSafe()), { method: 'POST', keepalive: true }).catch(function(){});
        if (window._aiAbortController) window._aiAbortController.abort('user-cancel');
        _resetUIAfterStop();
        const loadingEl = document.getElementById('ai-loading-msg');
        if (loadingEl) {
          if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
          if (loadingEl._phaseTimer) clearTimeout(loadingEl._phaseTimer);
          loadingEl.remove();
        }
        addMessage('操作已取消', 'system');
        // 更新任务状态
        if (window.GIS.task && window._currentTaskId) {
          window.GIS.task.updateTask(window._currentTaskId, { status: 'failed', error: '用户取消', completedAt: Date.now() });
        }
      });
    }

    // 图层附件关闭按钮
    var attachClose = document.getElementById('attachLayerClose');
    if (attachClose) {
      attachClose.addEventListener('click', function() { _clearPendingLayer(); if (inputEl) inputEl.focus(); });
    }
    // 引用预览条取消按钮
    var quoteClose = document.getElementById('quoteAttachClose');
    if (quoteClose) {
      quoteClose.addEventListener('click', _hideQuoteBar);
    }
    // 确保启动时停止按钮与状态正确复位
    _resetUIAfterStop();
  }

  // 初始化 AI 运行状态
  window._aiRunning = false;

  // ---- 斜杠命令处理 ----
  function _getSlashMenu() { return document.getElementById('slashMenu'); }
  function _getSlashBody() { return document.getElementById('slashMenuBody'); }

  function _handleSlashInput() {
    if (!inputEl) return;
    const val = inputEl.value;
    const cursor = inputEl.selectionStart;
    // 获取光标前的文本，检测是否以 / 开头且没有空格（表示正在输入命令名）
    const textBefore = val.substring(0, cursor);
    if (/^\/([a-zA-Z]*)$/.test(textBefore)) {
      const query = textBefore.substring(1).toLowerCase();
      _slashFiltered = SLASH_COMMANDS.filter(function(c) {
        return c.name.indexOf(query) === 0 || c.label.indexOf(query) === 0;
      });
      _slashIndex = -1;
      if (_slashFiltered.length > 0) {
        _renderSlashMenu();
        _showSlashMenu();
        _slashActive = true;
        return;
      }
    }
    _hideSlashMenu();
    _slashActive = false;
  }

  function _handleSlashKeydown(e) {
    if (!_slashActive) {
      // 按 / 时触发命令面板
      if (e.key === '/' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
        // 等 input 事件触发 _handleSlashInput
        return;
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        _slashIndex = Math.min(_slashIndex + 1, _slashFiltered.length - 1);
        _highlightSlash();
        break;
      case 'ArrowUp':
        e.preventDefault();
        _slashIndex = Math.max(_slashIndex - 1, 0);
        _highlightSlash();
        break;
      case 'Enter':
      case 'Tab':
        e.preventDefault();
        if (_slashIndex >= 0 && _slashFiltered[_slashIndex]) {
          _applySlashCommand(_slashFiltered[_slashIndex]);
        } else if (_slashFiltered[0]) {
          _applySlashCommand(_slashFiltered[0]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        _hideSlashMenu();
        _slashActive = false;
        break;
    }
  }

  function _handleSlashClickOutside(e) {
    const menu = _getSlashMenu();
    if (!menu) return;
    const wrapper = inputEl && inputEl.closest('.chat-input-wrapper');
    if (menu.style.display !== 'none' && !menu.contains(e.target) && wrapper && !wrapper.contains(e.target)) {
      _hideSlashMenu();
      _slashActive = false;
    }
  }

  function _renderSlashMenu() {
    const body = _getSlashBody();
    if (!body) return;
    body.innerHTML = _slashFiltered.map(function(c, i) {
      const iconSvg = SLASH_ICONS[c.name] || '';
      return '<div class="slash-item" data-index="' + i + '">' +
        '<div class="slash-item-left">' +
          '<span class="slash-item-icon">' + iconSvg + '</span>' +
          '<span class="slash-item-name">' + c.label + '</span>' +
          '<span class="slash-item-hint">/' + c.name + '</span>' +
        '</div>' +
        '<span class="slash-item-desc">' + c.desc + '</span>' +
      '</div>';
    }).join('');
    body.querySelectorAll('.slash-item').forEach(function(el) {
      el.addEventListener('click', function() {
        const idx = parseInt(this.dataset.index, 10);
        if (_slashFiltered[idx]) _applySlashCommand(_slashFiltered[idx]);
      });
    });
  }

  function _highlightSlash() {
    const body = _getSlashBody();
    if (!body) return;
    body.querySelectorAll('.slash-item').forEach(function(el, i) {
      el.classList.toggle('is-selected', i === _slashIndex);
    });
    const sel = body.querySelector('.slash-item.is-selected');
    if (sel) sel.scrollIntoView({ block: 'nearest' });
  }

  function _showSlashMenu() {
    const menu = _getSlashMenu();
    if (menu) menu.style.display = '';
  }

  function _hideSlashMenu() {
    const menu = _getSlashMenu();
    if (menu) menu.style.display = 'none';
  }

  function _applySlashCommand(cmd) {
    _hideSlashMenu();
    _slashActive = false;
    if (!inputEl) return;
    // 移除输入框中的 /命令名（只保留用户已输入的其他文字）
    inputEl.value = inputEl.value.replace(/^\/[a-zA-Z]*/, '');
    // /help 直接打开操作手册，不添加 chip
    if (cmd.name === 'help') {
      if (window.GIS && window.GIS.map && window.GIS.map._openManual) {
        window.GIS.map._openManual();
      }
      return;
    }
    // 确定性命令 → 直连面板/工具（不经 AI）；无 direct 路由的才做 AI chip
    if (typeof cmd.direct === 'function') {
      try { cmd.direct(); } catch (e) { console.error('[slash] direct 执行失败', e); }
      return;
    }
    _addChip(cmd);
  }

  // ===== Skill Chip 管理 =====
  function _addChip(cmd) {
    // 不重复添加同名 chip
    if (_skillChips.some(function(c) { return c.name === cmd.name; })) return;
    _skillChips.push({name: cmd.name, label: cmd.label, prompt: cmd.prompt});
    _renderChips();
    if (inputEl) inputEl.focus();
  }

  function _removeChip(index) {
    if (index < 0 || index >= _skillChips.length) return;
    const chip = _skillChips[index];
    // 从 textarea 中移除这个 chip 对应的 prompt 文字
    if (inputEl) {
      const text = inputEl.value;
      const promptIndex = text.indexOf(chip.prompt);
      if (promptIndex >= 0) {
        let before = text.substring(0, promptIndex);
        const after = text.substring(promptIndex + chip.prompt.length);
        // 如果前面有换行符，去掉它
        if (before.endsWith('\n')) before = before.slice(0, -1);
        inputEl.value = before + after;
      }
    }
    _skillChips.splice(index, 1);
    _renderChips();
  }

  function _removeLastChip() {
    if (_skillChips.length === 0) return;
    _removeChip(_skillChips.length - 1);
    if (inputEl) inputEl.focus();
  }

  function _renderChips() {
    const container = document.getElementById('chipContainer');
    if (!container) return;
    container.innerHTML = '';
    if (_skillChips.length === 0) {
      container.style.display = 'none';
      let wrapper = container.closest('.chat-input-wrapper');
      if (wrapper) wrapper.classList.remove('has-chips');
      return;
    }
    container.style.display = 'flex';
    let wrapper = container.closest('.chat-input-wrapper');
    if (wrapper) wrapper.classList.add('has-chips');
    _skillChips.forEach(function(chip, i) {
      const el = document.createElement('span');
      el.className = 'skill-chip';
      el.innerHTML = '/<span class="chip-name">' + chip.name + '</span><span class="chip-close" data-i="' + i + '" role="button" tabindex="0" aria-label="移除技能标签" title="移除" style="display:inline-flex;align-items:center;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:0;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>';
      el.querySelector('.chip-close').addEventListener('click', function(e) {
        e.stopPropagation();
        _removeChip(i);
        if (inputEl) inputEl.focus();
      });
      container.appendChild(el);
    });
  }

  // ===== 图层附件管理 =====
  function _clearPendingLayer() {
    _pendingLayer = null;
    const bar = document.getElementById('layerAttachBar');
    if (bar) bar.style.display = 'none';
    if (inputEl) inputEl.placeholder = '输入指令或查询... 键入 / 打开命令面板';
  }

  /** 设置待发送的图层附件（在输入框上方显示） */
  function setPendingLayer(info) {
    if (GIS.workspace) GIS.workspace.toggleAI(true);
    _pendingLayer = info;
    const bar = document.getElementById('layerAttachBar');
    const nameEl = document.getElementById('attachLayerName');
    const metaEl = document.getElementById('attachLayerMeta');
    const badgeType = document.getElementById('attachBadgeType');
    const badgeCount = document.getElementById('attachBadgeCount');
    if (!bar || !nameEl) return;

    nameEl.textContent = info.name || '未命名图层';
    metaEl.textContent = info.coords
      ? 'WGS-84 · ' + info.coords
      : 'WGS-84';
    badgeType.textContent = info.type || '未知';
    badgeCount.textContent = (info.count !== undefined) ? info.count + ' 要素' : '';
    bar.style.display = 'flex';
    if (inputEl) { inputEl.placeholder = '输入你对 ' + (info.name || '图层') + ' 的分析指令...'; inputEl.focus(); }
  }

  // 显示引用预览条（被引用内容前 60 字符）
  function _showQuoteBar(fullText) {
    var bar = document.getElementById('quoteAttachBar');
    var textEl = document.getElementById('quoteAttachText');
    if (!bar || !textEl) return;
    var preview = fullText.replace(/\s+/g, ' ').trim();
    if (preview.length > 60) preview = preview.slice(0, 60) + '...';
    textEl.textContent = preview;
    bar.style.display = 'flex';
  }

  // 隐藏引用预览条并清除引用状态
  function _hideQuoteBar() {
    _quotedMessage = null;
    var bar = document.getElementById('quoteAttachBar');
    if (bar) bar.style.display = 'none';
  }

  function _resetUIAfterStop() {
    window._aiRunning = false;
    if (!inputEl) return;
    inputEl.placeholder = '输入指令或查询...';
    inputEl.disabled = false;
    if (sendBtn) { sendBtn.disabled = false; sendBtn.style.opacity = '1'; }
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) {
      stopBtn.disabled = true;
      stopBtn.classList.remove('is-running');
      stopBtn.title = '停止 (无运行中任务)';
    }
    const modelBar = document.querySelector('.chat-input-model-bar');
    if (modelBar) modelBar.classList.remove('is-disabled');
    // 恢复右键菜单
    document.querySelectorAll('.context-menu-item').forEach(function(el) {
      if (el.getAttribute('data-action') !== 'copy-coords') el.classList.remove('is-disabled');
    });
  }

  /**
   * 清空当前会话（UI + 图层 + 任务 + API）
   * 替代原来 inline script 里的重复实现
   */
  async function clearSession() {
    // 1. 中止 AI 请求
    if (window._aiRunning) {
      window._aiRunning = false;
      if (window._aiAbortController) {
        window._aiAbortController.abort();
        window._aiAbortController = null;
      }
      fetch(window.GIS.api.BASE_URL + '/api/cancel?session_id=' + encodeURIComponent(_currentSessionIdSafe()), { method: 'POST' }).catch(function(){});
      var loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        if (loadingEl._phaseTimer) clearTimeout(loadingEl._phaseTimer);
        loadingEl.remove();
      }
    }
    _resetUIAfterStop();

    // 2. 清除图层（静默清除，避免图层删除提示回灌进空会话）
    if (window.GIS.layers && typeof window.GIS.layers.clearAll === 'function') {
      window.GIS.layers.clearAll(true);
    } else if (window.GIS.layers) {
      var allLayers = window.GIS.layers.getLayers();
      allLayers.forEach(function(l) {
        if (l.layer_id) window.GIS.layers.removeLayer(l.layer_id, false, true);
      });
    }

    // 3. 清 UI
    if (messagesContainer) {
      messagesContainer.innerHTML = '<div class="chat-messages-empty"></div>';
      messagesContainer.style.display = '';
      if (typeof updateGreeting === 'function') updateGreeting();
    }
    var historyPanel = document.getElementById('chatHistory');
    if (historyPanel) historyPanel.style.display = 'none';

    // 清除引用预览条
    _hideQuoteBar();

    // 4. 清除未保存的任务
    if (window.GIS.task && typeof window.GIS.task.clearUnsaved === 'function') {
      window.GIS.task.clearUnsaved();
    }

    // 5. 更新问候语
    if (typeof updateGreeting === 'function') {
      updateGreeting();
    }

    // 6. 异步调 API（等待清除完成，避免用户发消息时看到旧历史）
    var oldSessionId = (window.GIS.project && window.GIS.project.getCurrentSessionId)
      ? window.GIS.project.getCurrentSessionId()
      : 'default';
    if (window.GIS.project) {
      window.GIS.project.save().catch(function() {});
      if (window.GIS.project.resetSession) {
        window.GIS.project.resetSession();
      } else {
        window.GIS.project.setCurrentProjectId(null);
      }
    }
    try {
      await window.GIS.api.clearMemory(oldSessionId);
    } catch (e) {
      console.warn('清除记忆失败:', e);
    }
  }

  async function send(text, displayOpt) {
    // 如果传了参数就用参数，否则从输入框读取
    if (text === undefined) {
      text = inputEl ? inputEl.value.trim() : '';
    }
    if (!text) return;
    if (GIS.workspace) GIS.workspace.toggleAI(true);
    followOutput = true;

    // 如果有正在跑的 AI 请求，先取消
    if (window._aiRunning) {
      if (window._aiAbortController) {
        window._aiAbortController.abort('user-cancel');
      }
      // 修复：此行位于 currentSessionId 声明之前（var 提升值 undefined），
      // 会向后端发 session_id=undefined。改为即时解析当前会话 ID。
      var _cancelSid = (window.GIS.project && window.GIS.project.getCurrentSessionId)
        ? window.GIS.project.getCurrentSessionId()
        : 'default';
      fetch(window.GIS.api.BASE_URL + '/api/cancel?session_id=' + encodeURIComponent(_cancelSid), { method: 'POST' }).catch(function(){});
      var oldLoading = document.getElementById('ai-loading-msg');
      if (oldLoading) {
        if (oldLoading._timerInterval) clearInterval(oldLoading._timerInterval);
        if (oldLoading._phaseTimer) clearTimeout(oldLoading._phaseTimer);
        oldLoading.remove();
      }
    }

    // 解析第二个参数：字符串=displayText，对象={displayText, badge, provider}
    const displayText = typeof displayOpt === 'string' ? displayOpt : (displayOpt ? displayOpt.displayText : null);
    const badge = displayOpt && displayOpt.badge ? displayOpt.badge : null;
    const providerOverride = displayOpt && displayOpt.provider ? displayOpt.provider : null;

    // 检查当前选中的模型是否已配置 API Key（优先用 providerOverride）
    const selModel = document.getElementById('modelSelector');
    const curProvider = providerOverride || (selModel ? selModel.value : 'glm-routed');
    const _prov = window.GIS.api.resolveProvider(curProvider);
    const hasKey = !!(_prov && _prov.api_key);
    if (!hasKey) {
        const modelName = _prov && _prov.name ? _prov.name : curProvider;
        addMessage(modelName + ' 未配置 API Key，请点击齿轮按钮设置', 'system');
      // 恢复输入框（placeholder 还没被改过，不需要还原）
      if (inputEl) inputEl.disabled = false;
      if (sendBtn) { sendBtn.disabled = false; sendBtn.style.opacity = '1'; }
      const modelBar2 = document.querySelector('.chat-input-model-bar');
      if (modelBar2) modelBar2.classList.remove('is-disabled');
      return;
    }

    // 捕获当前 chips、待发送的图层附件和被引用的回复
    var chipsSnapshot = _skillChips.slice();
    var layerSnapshot = _pendingLayer ? Object.assign({}, _pendingLayer) : null;
    var quotedSnapshot = _quotedMessage ? Object.assign({}, _quotedMessage) : null;
    // 渲染用户消息（如果传了 displayText 就显示它）
    var msgOpts = badge ? {badge: badge} : {};
    if (chipsSnapshot.length > 0) msgOpts.chips = chipsSnapshot;
    if (layerSnapshot) msgOpts.attachLayer = layerSnapshot;
    if (quotedSnapshot) msgOpts.quoted = quotedSnapshot;
    addMessage(displayText || text, 'user', msgOpts);
    // 清除图层附件条和引用
    _clearPendingLayer();
    _quotedMessage = null;
    _hideQuoteBar();
    // 只有从输入框发送时才清空输入框
    if (inputEl && arguments.length === 0) {
      inputEl.value = '';
    }
    const el = document.getElementsByClassName('chat-messages-empty')[0];
    if (el) {
      el.style.display = 'none';
    }
    // 显示加载状态：输入框显示提示文字，禁用按钮和模型选择
    if (inputEl) {
      inputEl.placeholder = 'AI正在回复中...';
      inputEl.disabled = true;
    }
    if (sendBtn) {
      sendBtn.disabled = true;
      sendBtn.style.opacity = '0.5';
    }
    // 禁用模型选择器（请求中不允许换模型）
    const modelBar = document.querySelector('.chat-input-model-bar');
    if (modelBar) modelBar.classList.add('is-disabled');
    // 标记AI运行状态，点亮停止按钮，禁用右键
    window._aiRunning = true;
    const stopBtn = document.getElementById('stopBtn');
    if (stopBtn) {
      stopBtn.disabled = false;
      stopBtn.classList.add('is-running');
      stopBtn.title = '停止当前任务';
    }
    document.querySelectorAll('.context-menu-item').forEach(function(el) {
      if (el.getAttribute('data-action') !== 'copy-coords') el.classList.add('is-disabled');
    });

    // 获取当前模型显示名（优先用 providerOverride → 取 Provider 列表的 name）
    const modelDisplayEl = document.getElementById('modelSelectValue');
    let modelDisplayName = modelDisplayEl ? modelDisplayEl.textContent : 'AI';
    if (providerOverride) {
      const _po = window.GIS.api.resolveProvider(providerOverride);
      if (_po && _po.name) modelDisplayName = _po.name;
    }
    

    // 添加"模型名 思考中..."占位气泡，让用户知道 AI 正在处理
    const isRouted = (providerOverride === 'deepseek-routed' || providerOverride === 'glm-routed' || providerOverride === 'agnes');
    const loadingMsg = addMessage(modelDisplayName + ' 思考中...', 'ai', { noMarkdown: true });
    if (loadingMsg) loadingMsg.id = 'ai-loading-msg';

    // 路由模式：先显示路由阶段，再切换到执行阶段
    if (isRouted && loadingMsg) {
      const loadingContent = loadingMsg.querySelector('.message-bubble > div');
      if (loadingContent) loadingContent.textContent = modelDisplayName + ' 路由分析中...';
    }

    // 给气泡文本加流光 scan 动画
    if (loadingMsg) {
      const loadingContent = loadingMsg.querySelector('.message-bubble > div');
      if (loadingContent) loadingContent.classList.add('shimmer-loading-text');
    }

    // 添加翻牌计时器（实时显示 AI 思考耗时），另起一行
    const timerEl = createFlipTimer();
    const timerWrapper = document.createElement('div');
    timerWrapper.style.cssText = 'margin-top:6px;';
    timerWrapper.appendChild(timerEl);
    const loadingBubble = loadingMsg ? loadingMsg.querySelector('.message-bubble') : null;
    if (loadingBubble) loadingBubble.appendChild(timerWrapper);


    const startTime = Date.now();
    // 路由模式：1.5 秒后从"路由中"切换到"执行中"
    let phaseTimer = null;
    if (isRouted) {
      phaseTimer = setTimeout(function() {
        const el = document.getElementById('ai-loading-msg');
        if (el) {
          const c = el.querySelector('.message-bubble > div');
          if (c) c.textContent = modelDisplayName + ' 执行中...';
        }
      }, 1500);
    }
    if (loadingMsg) loadingMsg._phaseTimer = phaseTimer;
    const timerInterval = setInterval(function() {
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      updateFlipTimer(timerEl, elapsed);
    }, 1000);
    updateFlipTimer(timerEl, 0);
    if (loadingMsg) loadingMsg._timerInterval = timerInterval;

    try {
      // 读取当前选择的模型（优先用 providerOverride）
      const modelSelector = document.getElementById('modelSelector');
      const rawProvider = providerOverride || (modelSelector ? modelSelector.value : 'glm-routed'); const provider = rawProvider;
      const sendProv = window.GIS.api.resolveProvider(provider); // 当前完整 Provider 条目 → llm_config
      const forceSkills = _skillChips.map(function(c) { return CHIP_TO_SKILL[c.name]; }).filter(Boolean);
      // 解析 displayOpt 中的任务信息
      var taskId = displayOpt && displayOpt._taskId ? displayOpt._taskId : null;
      var taskProvider = displayOpt && displayOpt.provider ? displayOpt.provider : curProvider;
      if (!taskId) {
        var inputLayers = (window.GIS.layers && typeof window.GIS.layers.getLayers === 'function')
          ? window.GIS.layers.getLayers() : [];
        var task = window.GIS.task && window.GIS.task.createTask(text, taskProvider, inputLayers);
        if (task) taskId = task.id;
      }
      // 更新任务状态为规划中
      if (taskId && window.GIS.task) {
        window.GIS.task.updateTask(taskId, { status: 'planning' });
        window._currentTaskId = taskId; // 存全局，供停止按钮用
      }

      // === 流式执行：通过 SSE 实时获取 Agent 进度 ===
      var result = null;
      var streamUrl = GIS.api.BASE_URL + '/api/chat/stream';
      window._aiAbortController = new AbortController();
      // 超时保护（双层）：
      // - 总时长上限 gis_timeout（默认 900s，0=不限时）
      // - 空闲看门狗：连续 90s 收不到任何 SSE 事件才判死；收到事件即重置  长任务只要在干活就不会被误杀
      var _timeoutSetting = parseInt(sessionStorage.getItem('gis_timeout'), 10);
      var _timeoutMs = _timeoutSetting > 0 ? _timeoutSetting * 1000 : (_timeoutSetting === 0 ? Infinity : 900000);
      var _idleLimitMs = 90000;
      var _streamTimeout = null;   // 总时长定时器
      var _idleTimeout = null;     // 空闲定时器（活动即重置）
      var _armIdleWatchdog = function() {
        if (_idleTimeout) clearTimeout(_idleTimeout);
        _idleTimeout = setTimeout(function() {
          if (window._aiAbortController && !window._aiAbortController.signal.aborted) {
            window._aiAbortController.abort('timeout');
            window._idleKilled = true;
            console.warn('[GIS Chat] SSE 流空闲超 ' + (_idleLimitMs/1000) + 's 无响应，判定卡死，已终止');
          }
        }, _idleLimitMs);
      };
      var _clearAllTimeouts = function() {
        // 修复：原代码此处误写为自我递归调用（立即栈溢出），且漏清 _streamTimeout
        if (_streamTimeout) { clearTimeout(_streamTimeout); _streamTimeout = null; }
        if (_idleTimeout) { clearTimeout(_idleTimeout); _idleTimeout = null; }
      };
      if (_timeoutMs < Infinity) {
        _streamTimeout = setTimeout(function() {
          if (window._aiAbortController && !window._aiAbortController.signal.aborted) {
            window._aiAbortController.abort('timeout');
            console.warn('[GIS Chat] SSE 流总时长超限（' + (_timeoutMs/1000) + 's），已强制终止');
          }
        }, _timeoutMs);
      }
      window._idleKilled = false;
      _armIdleWatchdog();
      try {
        // 发送前同步所有图层到后端（后端重启后内存中的注册信息会丢失，这里重新注册）
        try {
          const allLayers = (window.GIS.layers && typeof window.GIS.layers.getLayers === 'function')
            ? window.GIS.layers.getLayers() : [];
          const registerPromises = [];
          for (const lyr of allLayers) {
            const lname = lyr.filename || lyr.name || lyr.layer_id;
            if (lname && lyr.geojson) {
              registerPromises.push(
                fetch(window.GIS.api.BASE_URL + '/api/layer/register', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ name: lname, geojson: lyr.geojson }),
                }).catch(function() {})
              );
            }
          }
          if (registerPromises.length > 0) {
            await Promise.all(registerPromises);
          }
        } catch(e) { console.warn('图层同步失败:', e); }

        var currentSessionId = (window.GIS.project && window.GIS.project.getCurrentSessionId)
          ? window.GIS.project.getCurrentSessionId()
          : 'default';

        const streamRes = await fetch(streamUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: window._aiAbortController.signal,
          body: JSON.stringify({
            message: text,
            session_id: currentSessionId,
            mode: window.GIS.chat.getMode(),
            api_key: sendProv.api_key || undefined,
            provider: sendProv.id || provider,
            llm_config: sendProv,
            force_skills: forceSkills,
            amap_key: window.GIS.api.getAmapKey() || undefined,
            pending_layer: layerSnapshot ? {
              name: layerSnapshot.name,
              type: layerSnapshot.type,
              coords: layerSnapshot.coords,
              count: layerSnapshot.count,
              geojson: layerSnapshot.geojson,
            } : undefined,
            quoted: quotedSnapshot ? quotedSnapshot.text : undefined,
          }),
        });
        if (!streamRes.ok) throw new Error('Stream API error: ' + streamRes.status);

        // 实时进度：保留模型名 + 流光，下方累积工具步骤
        var stepLog = document.createElement('div');
        stepLog.className = 'step-log';
        stepLog.style.cssText = 'margin-top:4px;font-size:11px;line-height:1.7;';
        if (loadingBubble) loadingBubble.insertBefore(stepLog, loadingBubble.lastChild);

        var reader = streamRes.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        var lastStepEl = null;
        var _receivedDone = false;

        while (true) {
          var chunk = await reader.read();
          if (chunk.done) {
            // P0-3: SSE 连接中断但未收到 done 事件，不重复执行 Agent
            if (!_receivedDone && !window._aiAbortController.signal.aborted) {
              throw new Error('__SSE_INTERRUPTED__');
            }
            break;
          }
          buffer += decoder.decode(chunk.value, { stream: true });

          var lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (var _i = 0; _i < lines.length; _i++) {
            var line = lines[_i];
            if (!line.startsWith('data: ')) continue;
            _armIdleWatchdog(); // 收到任何 SSE 事件即证明 Agent 仍在干活，重置空闲看门狗
            var evt;
            try { evt = JSON.parse(line.slice(6)); } catch (parseErr) {
              console.warn('[GIS Chat] 流式数据解析失败，跳过:', line.slice(0, 80));
              continue;
            }
            // error/cancelled 必须在内层 try 之外处理，否则空 catch 会吞掉
            if (evt.type === 'error') {
              throw new Error(evt.message || 'Agent 执行失败');
            } else if (evt.type === 'cancelled') {
              throw new Error('__USER_CANCELLED__');
            }
            try {
              if (evt.type === 'tool_start') {
                var toolLabel = evt.name + (evt.input ? '(' + evt.input.slice(0, 60) + ')' : '');
                var stepEl = document.createElement('div');
                stepEl.className = 'step-item step-running';
                stepEl.innerHTML = "<span class=\"ui-icon\" aria-hidden=\"true\" style=\"vertical-align:-2px;margin-right:4px;;width:11px;height:11px;--ui-icon-image:url('/assets/ui-icons/icon-a53011a6a003.png')\"></span><strong>" + GIS.utils.escapeHtml(toolLabel) + '</strong>';
                stepLog.appendChild(stepEl);
                scrollMessages();
                lastStepEl = stepEl;
              } else if (evt.type === 'tool_end') {
                if (lastStepEl) {
                  lastStepEl.innerHTML = '<span style="color:var(--ui-gray-400);display:inline-flex;align-items:center;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg></span> <span style="color:var(--ui-gray-500);">' + GIS.utils.escapeHtml(evt.name) + ' 完成</span>';
                  lastStepEl.style.fontWeight = 'normal';
                  lastStepEl.style.color = 'var(--ui-gray-400)';
                }
              } else if (evt.type === 'verifying') {
                if (lastStepEl) {
                  lastStepEl.innerHTML = '<span style="color:var(--ui-gray-400);display:inline-flex;align-items:center;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg></span> <span style="color:var(--ui-gray-500);">' + GIS.utils.escapeHtml(evt.name) + ' 完成</span>';
                  lastStepEl.style.fontWeight = 'normal';
                  lastStepEl.style.color = 'var(--ui-gray-400)';
                }
                var verifyEl = document.createElement('div');
                verifyEl.className = 'step-item step-running';
                verifyEl.innerHTML = '<span style="color:#ff9800;display:inline-flex;align-items:center;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></span> <strong>校验结果...</strong>';
                stepLog.appendChild(verifyEl);
                lastStepEl = verifyEl;
                scrollMessages();
              } else if (evt.type === 'done') {
                _receivedDone = true;
                result = evt;
                _clearAllTimeouts();
                if (stepLog && stepLog.children.length > 1) {
                  stepLog.style.maxHeight = '44px';
                  stepLog.style.overflow = 'hidden';
                  stepLog.style.cursor = 'pointer';
                  stepLog.style.transition = 'max-height 0.25s';
                  stepLog.title = '点击展开执行步骤';
                  stepLog.addEventListener('click', function toggleLog() {
                    var isCollapsed = stepLog.style.maxHeight === '44px';
                    stepLog.style.maxHeight = isCollapsed ? stepLog.scrollHeight + 'px' : '44px';
                  });
                }
              }
            } catch (parseErr) {
              console.warn('[GIS Chat] SSE 事件处理异常:', parseErr);
            }
          }
        }
      } catch (streamErr) {
        // 清除超时计时器
        _clearAllTimeouts();
        // P0-3: 明确区分异常类型
        var _errMsg = streamErr.message || '';
        if (_errMsg === '__USER_CANCELLED__') {
          throw new Error('__USER_CANCELLED__');
        }
        if (_errMsg === '__SSE_INTERRUPTED__') {
          throw new Error('AI 连接中断，未收到完整结果。请检查网络后重试。');
        }
        if (streamErr.name === 'AbortError') {
          var _abortReason = window._aiAbortController ? window._aiAbortController.signal.reason : undefined;
          if (_abortReason === 'user-cancel') {
            throw new Error('__USER_CANCELLED__');
          }
          throw new Error('AI 请求' + (window._idleKilled ? '长时间无响应（90s 未收到任何进度）' : '总时长超限（' + (_timeoutMs === Infinity ? '不限时' : _timeoutMs/1000 + 's') + '）') + '，请简化操作或重试');
        }
        // 其他流式错误：降级到普通 API（仅当未收到任何有效结果时）
        if (!result) {
          console.warn('[GIS Chat] 流式接口失败，降级到普通 API:', streamErr);
          result = await GIS.api.chat(text, currentSessionId, sendProv, forceSkills, window.GIS.chat.getMode());
        }
      }

      // 发送后清除 chip 标签（已消费）
      _skillChips = [];
      _renderChips();
      // 移除"思考中"占位气泡
      const loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        if (loadingEl._phaseTimer) clearTimeout(loadingEl._phaseTimer);
        loadingEl.remove();
      }

      // 更新任务卡状态
      if (taskId && window.GIS.task) {
        window._currentTaskId = null;
        var taskUpdate = { status: 'success' };
        // 收集结果图层信息
        var resultLayers = [];
        if (result.layers && result.layers.length > 0) {
          result.layers.forEach(function(l) {
            resultLayers.push({ name: l.name || '分析结果', geojson: l.geojson || l, layerId: 'task_result_' + Date.now() });
          });
        } else if (result.geojson && result.layerName) {
          resultLayers.push({ name: result.layerName, geojson: result.geojson, layerId: 'task_result_' + Date.now() });
        }
        taskUpdate.resultLayers = resultLayers;

        // 提取 AI 回复中的代码块作为执行代码
        var codeMatch = result.response && result.response.match(/```(?:python)?\s*([\s\S]*?)```/);
        if (codeMatch) {
          taskUpdate.code = codeMatch[1].trim();
        }
        // 提取前 300 字作为摘要
        var plainText = result.response ? result.response.replace(/<[^>]+>/g, '').replace(/```[\s\S]*?```/g, '') : '';
        taskUpdate.resultSummary = plainText.slice(0, 300) + (plainText.length > 300 ? '...' : '');
        taskUpdate.completedAt = Date.now();
        window.GIS.task.updateTask(taskId, taskUpdate);
      }

      // 会话忙（上一条工具链还在收尾）：这不是 AI 的回答，别当正文渲染
      if (result && result.busy) {
        removePendingActionBars();
        if (taskId && window.GIS.task) {
          window._currentTaskId = null;
          window.GIS.task.updateTask(taskId, { status: 'failed', resultSummary: '会话忙，本条未执行' });
        }
        var _busyEl = addMessage('上一条 AI 请求还在收尾（工具链尚未结束），这条消息没有执行。', 'system');
        try {
          var _busyBar = document.createElement('div');
          _busyBar.className = 'pending-action-bar';
          _busyBar.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;align-items:center;';
          var _retryBtn = document.createElement('button');
          _retryBtn.type = 'button';
          _retryBtn.className = 'chat-file-btn-primary';
          _retryBtn.style.borderRadius = '14px';
          _retryBtn.textContent = '重试这条分析';
          _retryBtn.onclick = function () {
            _busyBar.remove();
            window.GIS.chat.sendMessage(text, displayText ? { displayText: displayText, provider: providerOverride } : undefined);
          };
          var _dismissBtn = document.createElement('button');
          _dismissBtn.type = 'button';
          _dismissBtn.textContent = '知道了';
          _dismissBtn.style.cssText = 'border:none;background:transparent;color:var(--ui-gray-400,#aaa);font-size:11px;cursor:pointer;padding:4px 8px;';
          _dismissBtn.onclick = function () { _busyBar.remove(); };
          _busyBar.appendChild(_retryBtn);
          _busyBar.appendChild(_dismissBtn);
          var _busyBubble = _busyEl ? (_busyEl.querySelector('.message-bubble') || _busyEl) : null;
          if (_busyBubble) _busyBubble.appendChild(_busyBar);
        } catch (_busyErr) { /* 按钮渲染失败不影响提示 */ }
        return;
      }

      // 显示 AI 的文字回复
      if (!result) {
        addMessage('AI 未返回有效响应', 'ai');
        return;
      }
      removePendingActionBars();   // 新一轮结果出来，清掉旧按钮
      const msgEl = addMessage(result.response || '(空响应)', 'ai', {
        mode: result.mode || 'full',
        tokenUsage: result.token_usage || null,
      });

      // 折叠「思考过程」块：reasoning 开启时后端在 done 事件带 reasoning（不进正文）
      if (result.reasoning && msgEl) {
        try {
          var bubbleEl = msgEl.querySelector('.message-bubble') || msgEl;
          var sumEl = document.createElement('summary');
          sumEl.textContent = '思考过程';
          sumEl.style.cssText = 'cursor:pointer;font-size:12px;color:var(--ui-gray-500,#888);user-select:none;';
          var bodyEl = document.createElement('div');
          bodyEl.style.cssText = 'white-space:pre-wrap;word-break:break-word;margin-top:6px;color:var(--ui-gray-600,#666);font-size:12px;line-height:1.6;';
          bodyEl.textContent = result.reasoning;
          var details = document.createElement('details');
          details.style.cssText = 'margin-bottom:8px;padding:6px 8px;border:1px solid var(--ui-gray-200,#e5e7eb);border-radius:6px;background:rgba(120,120,120,0.05);';
          details.appendChild(sumEl);
          details.appendChild(bodyEl);
          bubbleEl.insertBefore(details, bubbleEl.firstChild);
        } catch (e) { /* reasoning 展示失败不阻塞回复 */ }
      }

      // 有「待确认动作」（后端 confirm_pending）→ 渲染按钮
      if (result.confirm_pending && msgEl) {
        try {
          var cp = result.confirm_pending;
          var bubbleEl2 = msgEl.querySelector('.message-bubble') || msgEl;
          var bar = document.createElement('div');
          bar.className = 'pending-action-bar';
          bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;align-items:center;';

          if (cp.action === 'choose_option' && cp.options && cp.options.length > 0) {
            // 多选项确认：渲染选项按钮组
            var tip = document.createElement('span');
            tip.textContent = (cp.summary || '请选择').slice(0, 100);
            tip.style.cssText = 'font-size:12px;color:var(--ui-gray-600,#666);width:100%;margin-bottom:4px;font-weight:500;';
            bar.appendChild(tip);
            cp.options.forEach(function(opt) {
              var b = document.createElement('button');
              b.type = 'button';
              var isConfigured = opt.configured;
              var labelText = GIS.utils.escapeHtml(opt.label) + (opt.configured === true ? ' ' + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg>' : (opt.configured === false ? ' (未配置)' : ''));
              b.innerHTML = labelText;
              b.title = opt.desc || opt.label;
              b.style.cssText =
                'border-radius:14px;padding:6px 16px;font-size:12px;cursor:pointer;transition:all 0.15s;' +
                (isConfigured === true
                  ? (document.documentElement.classList.contains('theme-dark')
                      ? 'background:rgba(59,130,246,0.18);color:#93c5fd;border:1px solid rgba(59,130,246,0.38);'
                      : 'background:#e3f2fd;color:#1565c0;border:1px solid #90caf9;')
                  : isConfigured === false
                    ? (document.documentElement.classList.contains('theme-dark')
                        ? 'background:var(--surface-container-high);color:var(--on-surface-variant);border:1px dashed var(--outline-variant);'
                        : 'background:#fafafa;color:#999;border:1px dashed #ddd;')
                    : (document.documentElement.classList.contains('theme-dark')
                        ? 'background:var(--surface-container-high);color:var(--on-surface);border:1px solid var(--outline-variant);'
                        : 'background:#fff;color:#333;border:1px solid var(--ui-gray-300,#ddd);'));
              b.onmouseenter = function() { this.style.transform = 'translateY(-1px)'; this.style.boxShadow = '0 2px 6px rgba(0,0,0,0.1)'; };
              b.onmouseleave = function() { this.style.transform = ''; this.style.boxShadow = ''; };
              b.onclick = function() {
                bar.remove();
                // 发送选项 label，后端 choose_option 逻辑会记录选择并注入 AI 上下文
                window.GIS.chat.sendMessage(opt.label);
              };
              bar.appendChild(b);
            });
            // 取消按钮
            var cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.textContent = '取消';
            cancelBtn.style.cssText = 'border:none;background:transparent;color:var(--ui-gray-400,#aaa);font-size:11px;cursor:pointer;padding:4px 8px;';
            cancelBtn.onclick = function() { bar.remove(); };
            bar.appendChild(cancelBtn);
          } else {
            // 普通确认：继续/取消
            var tip2 = document.createElement('span');
            tip2.textContent = (cp.summary || '已就绪').slice(0, 80);
            tip2.style.cssText = 'font-size:11px;color:var(--ui-gray-500,#888);margin-right:2px;';
            bar.appendChild(tip2);
            var mkBtn = function(label, word, primary) {
              var b = document.createElement('button');
              b.type = 'button';
              b.innerHTML = label;
              b.className = primary ? 'chat-file-btn-primary' : 'chat-file-btn-secondary';
              b.style.borderRadius = '14px';
              b.style.padding = '5px 14px';
              b.style.fontSize = '12px';
              b.style.cursor = 'pointer';
              b.onclick = function() {
                bar.remove();
                window.GIS.chat.sendMessage(word);
              };
              return b;
            };
            bar.appendChild(mkBtn('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M20 6L9 17l-5-5"/></svg> 加载到地图', '继续', true));
            bar.appendChild(mkBtn('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> 取消', '取消', false));
          }
          bubbleEl2.appendChild(bar);
        } catch (e) { /* 按钮渲染失败不阻塞回复 */ }
      }

        // 如果有 AI 生成的图表图片，追加到最后一条回复下方
        // （下载工具函数 downloadFile 已提升到模块作用域，供图片按钮与文件路径按钮共用）
        if (result.images && result.images.length > 0) {
          const bubble = msgEl ? msgEl.querySelector('.message-bubble') : null;
          const imgContainer = document.createElement('div');
          let appendedCount = 0;

          result.images.forEach(function(item) {
            // 兼容新旧格式：item 可能是字符串（旧）或对象（新）
            let imgUrl = typeof item === 'string' ? item : (item.url || '');
            // 智能容错：如果 item 缺少 url，尝试从 item.path 或 item.name 自动推导可访问 URL
            if (!imgUrl && item && typeof item === 'object') {
              if (item.path) {
                const normPath = item.path.replace(/\\/g, '/');
                if (normPath.indexOf('cache/') >= 0) {
                  imgUrl = '/' + normPath.substring(normPath.indexOf('cache/'));
                } else if (normPath.indexOf('output/') >= 0) {
                  imgUrl = '/' + normPath.substring(normPath.indexOf('output/'));
                }
              } else if (item.name) {
                imgUrl = '/cache/charts/' + item.name;
              }
            }
            if (imgUrl && imgUrl.indexOf('/') !== 0 && !imgUrl.startsWith('http')) {
              imgUrl = '/' + imgUrl;
            }
            if (!imgUrl) {
              console.warn('[GIS Chat] 无法推导图片 URL，跳过渲染:', item);
              return;
            }

            const imgType = typeof item === 'string' ? (imgUrl.match(/\.html?$/i) ? 'html' : 'png') : (item.type || 'png');
            const htmlContent = typeof item === 'string' ? null : (item.content || null);
            const fileName = (item && item.name) || imgUrl.split('/').pop() || 'file';
            const baseUrl = (window.GIS && window.GIS.api && window.GIS.api.BASE_URL) || 'http://localhost:8000';
            const fullUrl = imgUrl.startsWith('http') ? imgUrl : (baseUrl + imgUrl);

            // 【防重机制】：如果气泡内已经存在该产物卡片或同名图片，不重复创建
            if (bubble) {
              const existingItems = bubble.querySelectorAll('.chat-file-output-card, img, a');
              let alreadyInBubble = false;
              const bareName = fileName.replace(/^\d{14}_/, '');
              existingItems.forEach(function(el) {
                const s = el.src || el.href || (el.querySelector && el.querySelector('img') ? el.querySelector('img').src : '') || '';
                const t = el.textContent || '';
                if (s && (s.indexOf(fileName) >= 0 || s.indexOf(encodeURIComponent(fileName)) >= 0 || (bareName && s.indexOf(bareName) >= 0))) {
                  alreadyInBubble = true;
                }
                if (t && (t.indexOf(fileName) >= 0 || (bareName && t.indexOf(bareName) >= 0))) {
                  alreadyInBubble = true;
                }
              });
              if (alreadyInBubble) {
                return;
              }
            }

            if (imgType === 'html') {
              const htmlWrap = document.createElement('div');
              htmlWrap.className = 'chat-file-output-card';
              htmlWrap.style.cssText = 'overflow:hidden;width:100%;';
              const iframe = document.createElement('iframe');
              iframe.style.cssText = 'width:100%;height:420px;border:none;display:block;';
              iframe.title = '交互式地图';
              // 优先用 srcdoc（内联 HTML，不落磁盘），其次用 src
              if (htmlContent) {
                iframe.srcdoc = htmlContent;
              } else {
                iframe.src = fullUrl;
              }
              htmlWrap.appendChild(iframe);

              const toolBar = document.createElement('div');
              toolBar.className = 'chat-file-card-bar';
              toolBar.style.borderTop = '1px solid var(--outline-variant)';

              const nameSpan = document.createElement('span');
              nameSpan.className = 'chat-file-card-name';
              nameSpan.textContent = fileName;

              const openLink = document.createElement('a');
              openLink.className = 'chat-file-btn-primary';
              openLink.href = fullUrl;
              openLink.target = '_blank';
              openLink.rel = 'noopener noreferrer';
              openLink.textContent = '新标签打开';

              const dlHtmlBtn = document.createElement('button');
              dlHtmlBtn.className = 'chat-file-btn-secondary';
              dlHtmlBtn.type = 'button';
              dlHtmlBtn.textContent = '下载';
              dlHtmlBtn.addEventListener('click', function() { downloadFile(fullUrl, fileName); });

              toolBar.appendChild(nameSpan);
              toolBar.appendChild(openLink);
              toolBar.appendChild(dlHtmlBtn);
              htmlWrap.appendChild(toolBar);
              imgContainer.appendChild(htmlWrap);
              appendedCount++;
            } else {
              // 图片文件：采用统一的 chat-file-output-card 风格
              const wrapper = document.createElement('div');
              wrapper.className = 'chat-file-output-card';
              wrapper.style.cssText = 'position:relative;display:block;width:100%;max-width:100%;box-sizing:border-box;margin-top:8px;overflow:hidden;';

              const img = document.createElement('img');
              // 关键：在设置 src 之前绑定 onerror，破图时直接从 DOM 移除整块 wrapper，杜绝浏览器自带破图方框
              img.onerror = function() {
                if (wrapper.parentNode) wrapper.parentNode.removeChild(wrapper);
              };
              img.src = fullUrl;
              img.alt = fileName;
              img.style.cssText = 'width:100%;max-width:100%;height:auto;max-height:520px;object-fit:contain;cursor:pointer;display:block;margin:0 auto;';
              img.title = '在新标签页查看高清原图';
              img.addEventListener('click', function() { window.open(fullUrl, '_blank'); });
              wrapper.appendChild(img);

              // 底部工具条，使用统一的高对比度按钮样式
              const bar = document.createElement('div');
              bar.className = 'chat-file-card-bar';
              bar.style.borderTop = '1px solid var(--outline-variant)';

              const nameSpan = document.createElement('span');
              nameSpan.className = 'chat-file-card-name';
              nameSpan.textContent = fileName;

              const openBtn = document.createElement('button');
              openBtn.className = 'chat-file-btn-primary';
              openBtn.type = 'button';
              openBtn.textContent = '查看大图';
              openBtn.addEventListener('click', function() { window.open(fullUrl, '_blank'); });

              const dlBtn = document.createElement('button');
              dlBtn.className = 'chat-file-btn-secondary';
              dlBtn.type = 'button';
              dlBtn.textContent = '下载';
              dlBtn.addEventListener('click', function() { downloadFile(fullUrl, fileName); });

              bar.appendChild(nameSpan);
              bar.appendChild(openBtn);
              bar.appendChild(dlBtn);
              wrapper.appendChild(bar);

              // 悬浮右上角快捷下载按钮
              const dlImgBtn = document.createElement('button');
              dlImgBtn.className = 'chat-img-floating-dl-btn';
              dlImgBtn.type = 'button';
              dlImgBtn.title = '下载图片';
              dlImgBtn.innerHTML =
                '<span class="ui-icon" aria-hidden="true" style="width:14px;height:14px;--ui-icon-image:url(\'/assets/ui-icons/icon-9a58c1268267.png\')"></span>';
              dlImgBtn.addEventListener('click', function(e) { e.stopPropagation(); downloadFile(fullUrl, fileName); });
              wrapper.addEventListener('mouseenter', function() { dlImgBtn.style.opacity = '1'; });
              wrapper.addEventListener('mouseleave', function() { dlImgBtn.style.opacity = '0'; });
              wrapper.appendChild(dlImgBtn);

              imgContainer.appendChild(wrapper);
              appendedCount++;
            }
          });

          // 如果成功追加了非重复产物，挂载到容器中
          if (appendedCount > 0) {
            if (bubble) {
              bubble.appendChild(imgContainer);
            } else {
              document.getElementById('chatMessages').appendChild(imgContainer);
            }
          }
        }

      // 如果 AI 清空了图层，同步清空前端地图和面板
      if (result.clear_layers) {
        console.log('[GIS Chat] 收到清空图层指令');
        if (window.GIS.layers) {
          const allLayers = window.GIS.layers.getLayers();
          allLayers.forEach(function(l) {
            if (l.layer_id) window.GIS.layers.removeLayer(l.layer_id);
          });
        }
        addMessage('已清空所有图层', 'system');
      }

      // 必须先加载新图层，再执行 layer_ops（分级设色/标注/图例等），避免找不到图层
      if (result.layers && result.layers.length > 0) {
        console.log('[GIS Chat] 收到多个 GeoJSON 图层:', result.layers.length);
        result.layers.forEach(function(layer, idx) {
          const layerId = layer.layer_id || ('ai_' + Date.now() + '_' + idx);
          const layerName = layer.name || ('图层' + (idx + 1));
          const geojson = layer.geojson || layer;
          if (window.GIS.state) {
            window.GIS.state.addLayer({
              layer_id: layerId,
              name: layerName,
              geojson: geojson,
              style: layer.style || null,
              source: 'ai',
            });
            return;
          }
          if (GIS.map && GIS.map.loadGeoJSON) {
            GIS.map.loadGeoJSON(geojson, layerName, layer.style || {});
          }
          if (GIS.layers && GIS.layers.addLayer) {
            GIS.layers.addLayer({
              layer_id: layerId,
              filename: layerName,
              _rawName: layerName,
              geometry_type: geojson.type === 'FeatureCollection'
                ? ((geojson.features && geojson.features[0] && geojson.features[0].geometry && geojson.features[0].geometry.type) || '未知')
                : (geojson.geometry && geojson.geometry.type || '未知'),
              crs: 'WGS-84',
              geojson: geojson,
              visible: true,
              source: 'ai',
            });
          }
        });
      } else if (result.geojson && result.layerName) {
        const layerId = 'ai_' + Date.now();
        const layerName = result.layerName;
        const geoType = result.geojson.type === 'FeatureCollection'
          ? ((result.geojson.features && result.geojson.features[0] && result.geojson.features[0].geometry && result.geojson.features[0].geometry.type) || '未知')
          : (result.geojson.geometry && result.geojson.geometry.type || '未知');
        if (window.GIS.state) {
          window.GIS.state.addLayer({
            layer_id: layerId,
            name: layerName,
            geojson: result.geojson,
            source: 'ai',
          });
        } else {
          if (GIS.map && GIS.map.loadGeoJSON) GIS.map.loadGeoJSON(result.geojson, layerName);
          if (GIS.layers && GIS.layers.addLayer) {
            GIS.layers.addLayer({
              layer_id: layerId,
              filename: layerName,
              _rawName: layerName,
              geometry_type: geoType,
              crs: 'WGS-84',
              geojson: result.geojson,
              visible: true,
              source: 'ai',
            });
          }
        }
      }

      // 【兜底】layer_ops 引用的图层若不在前端面板（后端已注册但本轮未随 done 推送），
      // 先从后端 /api/layers 拉取补挂再执行操作——修复「未找到图层」导致设色/图例全部落空
      if (result.layer_ops && result.layer_ops.length > 0) {
        var _opLayerNames = [];
        result.layer_ops.forEach(function(op) {
          if (op && op.name && _opLayerNames.indexOf(op.name) < 0) _opLayerNames.push(op.name);
        });
        var _panelNow = (window.GIS.layers && window.GIS.layers.getLayers) ? window.GIS.layers.getLayers() : [];
        var _missing = _opLayerNames.filter(function(nm) {
          return !_panelNow.some(function(l) {
            return l._rawName === nm || l.filename === nm || l.layer_id === nm
              || (l.filename && l.filename.indexOf(nm) === 0)
              || (l._rawName && l._rawName.indexOf(nm) === 0);
          });
        });
        if (_missing.length > 0) {
          try {
            var _lyrRes = await fetch(((window.GIS && window.GIS.api && window.GIS.api.BASE_URL) || '') + '/api/layers');
            var _lyrData = await _lyrRes.json();
            (_lyrData.layers || []).forEach(function(lyr) {
              if (!lyr || !lyr.geojson) return;
              var _hit = _missing.some(function(m) {
                return lyr.name === m || (lyr.name && (lyr.name.indexOf(m) === 0 || m.indexOf(lyr.name) === 0));
              });
              if (!_hit) return;
              if (window.GIS.state && window.GIS.state.addLayer) {
                window.GIS.state.addLayer({
                  name: lyr.name,
                  geojson: lyr.geojson,
                  style: lyr.style || null,
                  source: 'ai',
                });
              } else if (GIS.map && GIS.map.loadGeoJSON && GIS.layers && GIS.layers.addLayer) {
                GIS.map.loadGeoJSON(lyr.geojson, lyr.name, lyr.style || {});
                GIS.layers.addLayer({
                  filename: lyr.name, _rawName: lyr.name, geojson: lyr.geojson,
                  crs: 'WGS-84', visible: true, source: 'ai',
                });
              }
            });
            console.log('[GIS Chat] layer_ops 引用图层缺失，已从后端补挂:', _missing.join(', '));
          } catch (e) {
            console.warn('[GIS Chat] 补挂缺失图层失败:', e);
          }
        }
      }

      // 如果 AI 返回了图层操作指令（移除/显隐/改色/重命名/缩放/分级设色/图例），优化时序并逐个执行
      if (result.layer_ops && result.layer_ops.length > 0) {
        console.log('[GIS Chat] 收到图层操作指令:', result.layer_ops.length, '条');
        // 关键时序优化：symbology（分级渲染）必须优先于 legend（图例卡片）执行，确保图例计算已有数据
        var opOrder = { 'remove': 1, 'rename': 2, 'set_color': 3, 'set_style': 4, 'symbology': 5, 'legend': 6, 'labels': 7, 'fit': 8, 'center': 9, 'drill': 10 };
        var sortedOps = [...result.layer_ops].sort(function(a, b) {
          return (opOrder[a.action] || 99) - (opOrder[b.action] || 99);
        });
        // 若同一图层在同一批次中已经执行了 symbology（symbology 内部已包含图例卡片渲染），则跳过冗余的 legend 指令
        var symbologyApplied = new Set();
        sortedOps.forEach(function(op) {
          if (op.action === 'symbology' && op.name) symbologyApplied.add(op.name);
        });

        sortedOps.forEach(function(op) {
          if (op.action === 'legend' && op.name && symbologyApplied.has(op.name)) {
            return;
          }
          var allLayers = window.GIS.layers && window.GIS.layers.getLayers ? window.GIS.layers.getLayers() : [];
          var target = allLayers.find(function(l) {
            return l._rawName === op.name || l.filename === op.name || l.layer_id === op.name
              || (l.filename && l.filename.indexOf(op.name) === 0)
              || (l._rawName && l._rawName.indexOf(op.name) === 0);
          });
          switch (op.action) {
            case 'remove':
              if (target && window.GIS.layers) window.GIS.layers.removeLayer(target.layer_id);
              break;
            case 'toggle':
              if (target && window.GIS.layers) window.GIS.layers.toggleVisibility(target.layer_id);
              break;
            case 'set_color':
              if (target && window.GIS.layers) {
                target.color = op.color;
                window.GIS.layers.renderList();
                if (GIS.map && GIS.map.setLayerColor) {
                  GIS.map.setLayerColor(target._rawName || target.layer_id, op.color);
                }
              }
              break;
            case 'set_style':
              if (target && GIS.map && GIS.map.setLayerStyle) {
                GIS.map.setLayerStyle(target._rawName || target.layer_id, op.style || {});
              }
              break;
            case 'rename':
              if (target && window.GIS.layers) {
                var oldN = target.filename || target._rawName;
                target.filename = op.new_name;
                target._rawName = op.new_name;
                if (window.GIS.state && window.GIS.state.renameLayer) {
                  window.GIS.state.renameLayer(target.layer_id, op.new_name);
                }
                if (window.GIS.map && window.GIS.map.renameLayer) {
                  window.GIS.map.renameLayer(oldN, op.new_name);
                }
                window.GIS.layers.renderList();
              }
              break;
            case 'fit':
              if (window.GIS.renderers && window.GIS.renderers.is3D && window.GIS.renderers.is3D()) {
                // 3D：飞到图层 bbox（图层经共享状态查找）
                var fitRec = null;
                if (window.GIS.state) {
                  window.GIS.state.getLayers().forEach(function(l) {
                    if (l.name === op.name || l._rawName === op.name) fitRec = l;
                  });
                }
                if (fitRec && fitRec.bbox && window.GIS.renderers.flyToBbox) {
                  window.GIS.renderers.flyToBbox(fitRec.bbox, 1.5);
                }
              } else if (window.GIS.map && window.GIS.map.fitLayer) {
                window.GIS.map.fitLayer(op.name);
              }
              break;
            case 'center':
              if (op.center) {
                if (window.GIS.renderers && window.GIS.renderers.is3D && window.GIS.renderers.is3D()) {
                  // 3D：按 zoom 粗略换算相机高度后飞行
                  var v3d = window.GIS.renderers.getViewer && window.GIS.renderers.getViewer();
                  if (v3d && window.Cesium) {
                    var zoom3d = op.zoom || 13;
                    var height = Math.max(500, Math.pow(2, 22 - zoom3d) * 60);
                    v3d.camera.flyTo({
                      destination: window.Cesium.Cartesian3.fromDegrees(op.center[0], op.center[1], height),
                      duration: 1.5,
                    });
                  }
                } else if (window.GIS.map && window.GIS.map.setView) {
                  window.GIS.map.setView([op.center[1], op.center[0]], op.zoom || 13);
                }
              }
              break;
            case 'visualize':
              if (window.GIS.state && typeof window.GIS.state.applyVisualization === 'function' && op.viz) {
                var vizRec = null;
                window.GIS.state.getLayers().forEach(function(l) {
                  if (l.name === op.name || l._rawName === op.name) vizRec = l;
                });
                if (vizRec) {
                  window.GIS.state.applyVisualization(vizRec.layer_id, op.viz);
                } else if (window.GIS.chat && window.GIS.chat.addMessage) {
                  window.GIS.chat.addMessage('未找到图层「' + (op.name || '') + '」，无法应用可视化', 'system');
                }
              }
              break;
            case 'symbology':
              if (window.GIS.layers) {
                if (op.symbology_type === 'graduated') {
                  window.GIS.layers.applyGraduatedColors(op.name, op.field, op.classes, op.scheme);
                } else if (op.symbology_type === 'unique') {
                  window.GIS.layers.applyUniqueValues(op.name, op.field, op.scheme);
                }
              }
              break;
            case 'labels':
              if (window.GIS.layers) {
                window.GIS.layers.addLabels(op.name, op.field);
              }
              break;
            case 'legend':
              if (window.GIS.layers) {
                window.GIS.layers.addLegend(op.name);
              }
              break;
            case 'drill':
              // 行政区下钻/上钻：由共享状态机统一处理（面包屑/相机/图层显隐）
              if (window.GIS.state) {
                if (op.direction === 'up') {
                  window.GIS.state.drillUpTo();
                } else if (op.adcode) {
                  // 图层已由 result.layers 通道加载，这里只同步导航栈与视野
                  window.GIS.state.drillSyncFromAgent(op);
                }
              }
              break;
            case 'north_arrow':
              if (window.GIS.map && window.GIS.map.showNorthArrow) {
                window.GIS.map.showNorthArrow();
              }
              break;
            case 'edit_vertices':
              if (window.GIS.layers) window.GIS.layers.editVertices(op.name);
              if (window.GIS.chat) window.GIS.chat.addMessage('已进入折点编辑模式，拖拽顶点调整后点击「保存」完成编辑', 'system');
              break;
            case 'export_map':
              if (window.GIS.map && window.GIS.map.exportMap) {
                window.GIS.map.exportMap(op.format || 'png');
              }
              break;
            case 'export_pdf':
              if (window.GIS.map && window.GIS.map.exportPdf) {
                window.GIS.map.exportPdf(op.title || '地图导出');
              }
              break;
            case 'undo':
              if (window.GIS.map && window.GIS.map.undo) window.GIS.map.undo();
              break;
            case 'redo':
              if (window.GIS.map && window.GIS.map.redo) window.GIS.map.redo();
              break;
            case 'snapping':
              if (window.GIS.chat) {
                window.GIS.chat.addMessage('捕捉已' + (op.enabled ? '启用' : '禁用') + '（刷新页面生效）', 'system');
              }
              break;
            case 'dem_result':
              if (op.url && op.bounds) {
                window.GIS.map.addImageOverlay(op.url, op.bounds, op.name);
                if (window.GIS.chat) {
                  window.GIS.chat.addMessage('已添加地形分析图层: ' + (op.label || op.name), 'system');
                }
              }
              break;
            case 'time_animation':
              if (window.GIS.map && typeof window.GIS.map.startTimeAnimation === 'function') {
                window.GIS.map.startTimeAnimation(op.name, op.time_field, op.time_values, op.interval_ms);
                if (window.GIS.chat) {
                  window.GIS.chat.addMessage('已启动时序动画: ' + (op.name || ''), 'system');
                }
              }
              break;
            case 'chart_link':
              if (window.GIS.map && typeof window.GIS.map.enableChartLink === 'function') {
                window.GIS.map.enableChartLink(op.name, op.chart_field);
                if (window.GIS.chat) {
                  window.GIS.chat.addMessage('已建立图表联动: ' + (op.name || ''), 'system');
                }
              }
              break;
            case 'swipe':
              // 卷帘对比：2D 用独立 pane + clip-path 分割；3D 模式下提示切回 2D
              if (window.GIS.renderers && window.GIS.renderers.is3D && window.GIS.renderers.is3D()) {
                if (window.GIS.chat) {
                  window.GIS.chat.addMessage('卷帘对比目前仅支持 2D 模式，请先切换回 2D 地图', 'system');
                }
              } else if (window.GIS.map && typeof window.GIS.map.startSwipe === 'function') {
                window.GIS.map.startSwipe(op.left, op.right, op.orientation);
              }
              break;
            case 'swipe_close':
              if (window.GIS.map && typeof window.GIS.map.stopSwipe === 'function') {
                window.GIS.map.stopSwipe();
              }
              break;
          }
        });
      }

      // 如果有待处理的 AOI 候选列表，显示在聊天框供点击选择
      if (result.pending_suggestions && result.pending_suggestions.length > 0) {
        setTimeout(() => {
          if (window.GIS.aoi && typeof window.GIS.aoi.showSuggestions === 'function') {
            window.GIS.aoi.showSuggestions(result.pending_suggestions);
          }
        }, 200);
      }

      // === 结果真实性与 GIS 质量自检徽标（中文可信度徽标与折叠审计） ===
      if (msgEl && (result.result_check || (result.qa_warnings && result.qa_warnings.length > 0))) {
        try {
          var bubbleEl = msgEl.querySelector('.message-bubble') || msgEl;
          var rc = result.result_check || {};
          var qa = result.qa_warnings || [];
          var isOk = rc.ok !== false && qa.length === 0;
          var hasWarn = rc.ok !== false && qa.length > 0;
          var hasError = rc.ok === false;

          var badgeContainer = document.createElement('div');
          badgeContainer.className = 'result-audit-box';
          badgeContainer.style.cssText = 'margin-top:10px;padding-top:8px;border-top:1px dashed var(--ui-gray-200,#e5e7eb);font-size:12px;';

          var pill = document.createElement('div');
          pill.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:12px;cursor:pointer;user-select:none;font-weight:500;transition:all 0.15s;';

          var detailPanel = document.createElement('div');
          detailPanel.style.cssText = 'display:none;margin-top:8px;padding:8px 12px;border-radius:6px;font-size:11px;line-height:1.6;background:var(--ui-gray-50,#f9fafb);border:1px solid var(--ui-gray-200,#e5e7eb);color:var(--ui-gray-700,#374151);';

          // 精致轻量 SVG 图标
          var svgCheck = '<svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
          var svgWarn = '<svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>';
          var svgAlert = '<svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
          var svgChevron = '<svg width="10" height="10" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;transition:transform 0.2s;"><polyline points="6 9 12 15 18 9"></polyline></svg>';
          var svgDoc = '<svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>';

          if (hasError) {
            pill.style.background = '#fef2f2';
            pill.style.color = '#dc2626';
            pill.style.border = '1px solid #fecaca';
            pill.innerHTML = '<span>' + svgAlert + ' 产物核验异常</span> <span style="font-size:10px;color:#ef4444;display:inline-flex;align-items:center;gap:2px;">查看明细 ' + svgChevron + '</span>';
          } else if (hasWarn) {
            pill.style.background = '#fffbeb';
            pill.style.color = '#d97706';
            pill.style.border = '1px solid #fde68a';
            pill.innerHTML = '<span>' + svgWarn + ' 产物已落盘 · 存在几何提示</span> <span style="font-size:10px;color:#f59e0b;display:inline-flex;align-items:center;gap:2px;">查看明细 ' + svgChevron + '</span>';
          } else {
            pill.style.background = '#f0fdf4';
            pill.style.color = '#16a34a';
            pill.style.border = '1px solid #bbf7d0';
            pill.innerHTML = '<span>' + svgCheck + ' 真实性已核验 · 产物已落盘</span> <span style="font-size:10px;color:#22c55e;display:inline-flex;align-items:center;gap:2px;">审计 ' + svgChevron + '</span>';
          }

          var detailHtml = '<div style="font-weight:600;margin-bottom:6px;color:var(--ui-gray-900,#111827);display:flex;align-items:center;">' + svgDoc + ' 结果确定性核验报告</div>';
          if (rc.artifact_checks && rc.artifact_checks.length > 0) {
            detailHtml += '<div style="margin-bottom:4px;"><b>产物三方核实：</b><ul style="margin:2px 0 4px 16px;padding:0;">';
            rc.artifact_checks.forEach(function(c) {
              var stText = c.status === 'VERIFIED' ? '<span style="color:#16a34a;">已生成并落盘 (通过)</span>'
                         : c.status === 'MISSING' ? '<span style="color:#dc2626;">磁盘文件不存在 (缺失)</span>'
                         : c.status === 'UNREGISTERED' ? '<span style="color:#dc2626;">历史残留/未在本次执行登记</span>'
                         : c.status;
              detailHtml += '<li><code>' + (c.path || '') + '</code>: ' + stText + '</li>';
            });
            detailHtml += '</ul></div>';
          }

          if (rc.issues && rc.issues.length > 0) {
            detailHtml += '<div style="color:#dc2626;margin-bottom:4px;"><b>发现问题：</b><ul style="margin:2px 0 4px 16px;padding:0;">';
            rc.issues.forEach(function(iss) { detailHtml += '<li>' + iss + '</li>'; });
            detailHtml += '</ul></div>';
          }

          if (qa && qa.length > 0) {
            detailHtml += '<div style="color:#d97706;margin-bottom:4px;"><b>GIS 几何检查提示：</b><ul style="margin:2px 0 4px 16px;padding:0;">';
            qa.forEach(function(q) { detailHtml += '<li>图层「' + (q.layer || '') + '」: ' + (q.warning || '') + '</li>'; });
            detailHtml += '</ul></div>';
          }

          if (result.run_id) {
            detailHtml += '<div style="color:var(--ui-gray-400,#9ca3af);font-size:10px;margin-top:4px;">执行轮次 Run ID: <code>' + result.run_id + '</code> | 存储: 本地 SQLite</div>';
          }

          detailPanel.innerHTML = detailHtml;

          pill.onclick = function() {
            var isHidden = detailPanel.style.display === 'none';
            detailPanel.style.display = isHidden ? 'block' : 'none';
            var chev = pill.querySelector('svg:last-child');
            if (chev) {
              chev.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
            }
          };

          badgeContainer.appendChild(pill);
          badgeContainer.appendChild(detailPanel);
          bubbleEl.appendChild(badgeContainer);
        } catch (e) { console.warn('[GIS Chat] 渲染可信度徽标失败:', e); }
      }

      // 处理历史面板：打开状态下随每轮结果自动刷新（新工具执行记录到达）
      if (window.GIS.history && typeof window.GIS.history.refresh === 'function') {
        var _hp = document.getElementById('historyPanel');
        if (_hp && _hp.classList.contains('open')) {
          setTimeout(function() { window.GIS.history.refresh(); }, 1200);
        }
      }

      // 热力图数据
      if (result.heatmap && result.heatmap.points && result.heatmap.points.length > 0) {
        (function loadHeatmapWithRetry(attempt) {
          if (!GIS.map || !GIS.map.loadHeatmap) {
            if (attempt < 10) { setTimeout(function() { loadHeatmapWithRetry(attempt + 1); }, 300); return; }
            return;
          }
          const uniqueName = (result.heatmap.name || 'heatmap') + '_' + Date.now();
          GIS.map.loadHeatmap(result.heatmap.points, uniqueName, result.heatmap.options || {});
          if (window.GIS.layers && window.GIS.layers.addLayer) {
            GIS.layers.addLayer({
              layer_id: 'heat_' + Date.now(),
              filename: uniqueName,
              geometry_type: '热力',
              crs: 'WGS-84',
              geojson: null,
              visible: true,
              source: 'ai',
            });
          }
        })(0);
      }

      // 自动保存工程快照（异步，不阻塞）
      if (window.GIS.project && typeof window.GIS.project.autoSave === 'function') {
        window.GIS.project.autoSave();
      }
    } catch (err) {
      // 清除超时计时器
      _clearAllTimeouts();
      // 移除"思考中"占位气泡
      const loadingEl = document.getElementById('ai-loading-msg');
      if (loadingEl) {
        if (loadingEl._timerInterval) clearInterval(loadingEl._timerInterval);
        if (loadingEl._phaseTimer) clearTimeout(loadingEl._phaseTimer);
        loadingEl.remove();
      }
      // 用户主动取消：不显示"请求失败"，stopBtn 已提示"操作已取消"、任务状态已更新
      if (err && err.message === '__USER_CANCELLED__') {
        return;
      }
      // 更新任务状态为失败
      if (taskId && window.GIS.task) {
        window._currentTaskId = null;
        window.GIS.task.updateTask(taskId, { status: 'failed', error: err.message, completedAt: Date.now() });
      }
      // 显示错误消息
      var _errMsg = (err && err.message) ? err.message : String(err);
      if (_errMsg === 'Failed to fetch' || _errMsg.indexOf('ERR_CONNECTION') >= 0 || _errMsg.indexOf('NetworkError') >= 0) {
        addMessage('无法连接到后端服务，请确认后端已启动（默认地址 127.0.0.1:8000）。可在项目目录运行 start.bat 或 uvicorn backend.main:app --host 127.0.0.1 --port 8000', 'system');
      } else {
        addMessage('请求失败: ' + _errMsg, 'system');
      }
      // 恢复默认 placeholder（防止并发发送覆盖）
      if (inputEl) inputEl.placeholder = '输入指令或查询...';
    } finally {
      // 清除超时计时器
      _clearAllTimeouts();
      _resetUIAfterStop();
      if (inputEl) {
        inputEl.placeholder = '输入指令或查询...';
        inputEl.focus();
      }
      // 恢复模型选择器显示名：一律取 Provider 列表里的 name，避免硬编码映射对不上
      var selEl = document.getElementById('modelSelector');
      var valEl = document.getElementById('modelSelectValue');
      var _restoreProv = window.GIS.api && window.GIS.api.resolveProvider(selEl ? selEl.value : null);
      if (valEl && _restoreProv && _restoreProv.name) valEl.textContent = _restoreProv.name;
      const modelBar = document.querySelector('.chat-input-model-bar');
      if (modelBar) modelBar.classList.remove('is-disabled');
    }
  }

  function removePendingActionBars() {
    // 每次新的 AI 结果出来都清掉旧的「继续/取消」按钮，避免残留多个
    document.querySelectorAll('.pending-action-bar').forEach(function(el) {
      el.remove();
    });
  }

  /**
   * 通用下载函数（fetch + Blob，解决跨域下载问题）。
   * 定义在模块作用域：图片下载按钮与 AI 回复中的文件路径下载按钮共用。
   */
  function downloadFile(url, filename) {
    fetch(url).then(function(res) { return res.blob(); }).then(function(blob) {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    }).catch(function(e) { console.warn('下载失败:', e); });
  }

  /**
   * 在 AI 消息中识别输出文件路径（/output/xxx、cache/xxx 等），
   * 自动追加「打开 / 下载」按钮，方便用户直接跳转定位文件。
   */
  function _attachOutputButtons(contentEl) {
    if (!contentEl || contentEl._outputBtnsAttached) return false;
    contentEl._outputBtnsAttached = true;

    var baseUrl = (window.GIS && window.GIS.api && window.GIS.api.BASE_URL) || 'http://localhost:8000';
    var pathRe = /(?:\/?)(?:output|cache|uploads|downloads)\/[A-Za-z0-9_\-\u4e00-\u9fa5.\/()（）]+?\.(?:geojson|json|csv|shp|zip|png|jpe?g|html?|tiff?|kml|kmz|gpkg|gpx|dxf)/g;

    // 1. 查找是否存在「结果真实性自检」免责声明块，自检段落内的探针或不存在路径必须排除
    var guardNode = null;
    var allElements = contentEl.querySelectorAll('*');
    for (var g = 0; g < allElements.length; g++) {
      if ((allElements[g].textContent || '').indexOf('【结果真实性自检】') >= 0) {
        guardNode = allElements[g];
        break;
      }
    }

    var nodes = contentEl.querySelectorAll('p, li, div, code, pre, span, td');
    var seenPaths = new Set();
    var validCards = [];

    // 检查气泡中是否已经渲染了同名图片（比如 live stream 中由 result.images 渲染的 <img>）
    var parentBubble = contentEl.closest('.message-bubble') || contentEl;
    var existingImgs = parentBubble.querySelectorAll('img');
    var existingImgSrcs = new Set();
    existingImgs.forEach(function(img) {
      if (img.src) {
        var srcName = decodeURIComponent(img.src.split('/').pop());
        existingImgSrcs.add(srcName);
        existingImgSrcs.add(srcName.replace(/^\d{14}_/, ''));
      }
    });

    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      // 如果属于自检段落内部或其后代，直接跳过
      if (guardNode && (guardNode.contains(node) || node.contains(guardNode))) continue;
      // 避免父节点与子节点重复检查
      if (node.querySelector('p, li, pre')) continue;

      var text = node.textContent || '';
      // 如果包含否定语义，表示文件未生成或不存在，不生成打开/下载按钮
      if (/不存在|未生成|未通过|失败|probe|探针|404|请勿认为/.test(text)) continue;

      var matches = text.match(pathRe);
      if (!matches) continue;

      for (var mIdx = 0; mIdx < matches.length; mIdx++) {
        var filePath = matches[mIdx];
        if (filePath.indexOf('/') !== 0) filePath = '/' + filePath;
        var fileName = filePath.split('/').pop();
        if (seenPaths.has(filePath)) continue;
        seenPaths.add(filePath);

        // 如果文件名包含 probe、未生成等测试特征，过滤掉
        if (/probe|tiny_probe/i.test(fileName)) continue;

        var fullUrl = baseUrl + filePath;
        var isImg = /\.(png|jpe?g|webp|svg)$/i.test(fileName);
        var bareFileName = fileName.replace(/^\d{14}_/, '');
        var alreadyRendered = isImg && (existingImgSrcs.has(fileName) || existingImgSrcs.has(bareFileName));

        // 如果该图片已经在气泡里以大图形式呈现，不要再重复插入卡片
        if (alreadyRendered) continue;

        var card = document.createElement('div');
        card.className = 'chat-file-output-card';

        if (isImg) {
          var imgBox = document.createElement('div');
          imgBox.className = 'chat-file-card-img-box';
          var imgEl = document.createElement('img');
          // 关键：在设置 src 之前绑定 onerror，破图时彻底移除图片容器，不留破图方框
          imgEl.onerror = function() {
            imgEl.style.display = 'none';
            imgBox.style.display = 'none';
            if (imgBox.parentNode) {
              imgBox.parentNode.removeChild(imgBox);
            }
          };
          imgEl.src = fullUrl;
          imgEl.alt = fileName;
          imgEl.style.cssText = 'display:block;width:100%;max-width:100%;height:auto;max-height:480px;object-fit:contain;transition:transform 0.2s;';
          imgEl.title = '在新标签页查看高清原图';
          imgEl.addEventListener('mouseenter', function() { imgEl.style.transform = 'scale(1.01)'; });
          imgEl.addEventListener('mouseleave', function() { imgEl.style.transform = 'scale(1)'; });
          imgEl.addEventListener('click', (function(url) { return function() { window.open(url, '_blank'); }; })(fullUrl));
          imgBox.appendChild(imgEl);
          card.appendChild(imgBox);
        }

        var btnRow = document.createElement('div');
        btnRow.className = 'chat-file-card-bar';
        if (isImg && !alreadyRendered) {
          btnRow.style.borderTop = '1px solid var(--outline-variant)';
        }
        var nameSpan = document.createElement('span');
        nameSpan.className = 'chat-file-card-name';
        nameSpan.textContent = fileName;

        var openBtn = document.createElement('button');
        openBtn.className = 'chat-file-btn-primary';
        openBtn.type = 'button';
        openBtn.textContent = isImg ? '查看大图' : '打开';
        openBtn.addEventListener('click', (function(url) { return function() { window.open(url, '_blank'); }; })(fullUrl));

        var dlBtn = document.createElement('button');
        dlBtn.className = 'chat-file-btn-secondary';
        dlBtn.type = 'button';
        dlBtn.textContent = '下载';
        dlBtn.addEventListener('click', (function(url, name) { return function() { downloadFile(url, name); }; })(fullUrl, fileName));

        btnRow.appendChild(nameSpan);
        btnRow.appendChild(openBtn);
        btnRow.appendChild(dlBtn);
        card.appendChild(btnRow);

        validCards.push(card);
      }
    }

    if (validCards.length > 0) {
      // 统一收敛在消息末尾的附件货架中，避免插入到 <ul> / <li> 中断裂排版
      var shelf = document.createElement('div');
      shelf.className = 'chat-outputs-shelf';
      shelf.style.cssText = 'display:flex;flex-direction:column;gap:6px;margin-top:10px;padding-top:8px;border-top:1px dashed var(--outline-variant);';
      for (var c = 0; c < validCards.length; c++) {
        shelf.appendChild(validCards[c]);
      }
      contentEl.appendChild(shelf);
      return true;
    }
    return false;
  }

  function addMessage(text, type, options) {
    if (!messagesContainer) return null;
    type = type || 'ai';
    options = options || {};

    // 系统消息：支持 Markdown 渲染与优雅居中提示卡片/胶囊
    if (type === 'system') {
      const row = document.createElement('div');
      row._rawText = text;
      const isHidden = options && options.hidden;
      row.className = 'message message-system';
      row.style.cssText = isHidden
        ? 'display:none;'
        : 'display:flex;justify-content:center;align-items:center;width:100%;margin:4px 0;box-sizing:border-box;';
      const bubble = document.createElement('div');

      // 只要是显式 pill 选项、或单行超短状态通知（<50字且无换行无Markdown），采用居中胶囊展现；
      // 只要包含换行符（\n）、带有 markdown 标记、或字符数较长，自动作为系统卡片（换行、Markdown 解析、左对齐）展现，彻底解决被挤成单行截断的问题！
      const hasNewline = text.indexOf('\n') >= 0;
      const hasMarkdown = /[*`#\[\]\-_]/.test(text);
      const isStatusEvent = !options.card && (options.pill || (!hasNewline && !hasMarkdown && text.length < 50 && /^(已恢复工程|已保存|已清理|已重置|清空|加载工程|删除|保存|操作|未找到|捕捉|连接失败|请求失败)/.test(text)));
      const isRichCard = !isStatusEvent && (options.card || hasNewline || hasMarkdown || text.length > 50);

      if (isRichCard) {
        bubble.className = 'system-card';
        bubble.style.cssText = 'max-width:92%;font-size:12px;color:var(--on-surface-variant);background:var(--surface-container-low);border:1px solid var(--outline-variant);border-radius:8px;padding:10px 14px;line-height:1.6;word-break:break-word;text-align:left;white-space:normal;margin:4px auto;box-sizing:border-box;box-shadow:0 1px 3px rgba(0,0,0,0.05);';
        if (typeof marked !== 'undefined' && text.indexOf('<') === -1) {
          bubble.innerHTML = marked.parse(text, { breaks: true, gfm: true, renderer: _linkRenderer });
        } else {
          bubble.innerHTML = text.replace(/\n/g, '<br/>');
        }
      } else {
        bubble.className = 'system-pill';
        bubble.style.cssText = 'font-size:11.5px;color:var(--on-surface-variant);background:var(--surface-container-high);border:1px solid var(--outline-variant);border-radius:12px;padding:4px 14px;text-align:center;line-height:1.45;max-width:90%;white-space:normal;word-break:break-word;margin:0 auto;box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;';
        if (typeof marked !== 'undefined') {
          bubble.innerHTML = typeof marked.parseInline === 'function' ? marked.parseInline(text) : marked.parse(text);
        } else {
          bubble.innerHTML = text;
        }
      }
      row.appendChild(bubble);
      messagesContainer.appendChild(row);
      scrollMessages();
      return row;
    }

    const row = document.createElement('div');
    row._rawText = text;
    row.className = 'message' + (type === 'user' ? ' message-user' : '');
    row.style.opacity = '0';
    row.style.transition = 'opacity 0.2s';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar' + (type === 'user' ? ' message-avatar-user' : ' message-avatar-ai');
    avatar.innerHTML = type === 'user'
      ? "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-5df592d75d04.png')\"></span>"
      : "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:14px;height:14px;--ui-icon-image:url('/assets/ui-icons/icon-04301442a3cd.png')\"></span>";
    row.appendChild(avatar);

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble' + (type === 'user' ? ' message-bubble-user' : ' message-bubble-ai');

    const content = document.createElement('div');
    // AI 消息渲染 Markdown（跳过加载气泡，避免 <p> 包裹破坏流光动画）
    if (type === 'ai' && !options.noMarkdown && typeof marked !== 'undefined') {
      content.innerHTML = marked.parse(text, { breaks: true, gfm: true, renderer: _linkRenderer });
    } else {
      content.innerHTML = text;
    }
    // AI 消息：自动为输出文件路径添加「打开 / 下载」跳转按钮
    if (type === 'ai') _attachOutputButtons(content);
    bubble.appendChild(content);

    // 用户消息：在气泡底部显示 skill chip 标签
    if (type === 'user' && options.chips && options.chips.length > 0) {
      var chipsRow = document.createElement('div');
      chipsRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;';
      options.chips.forEach(function(chip) {
        var chipEl = document.createElement('div');
        chipEl.style.cssText = 'display:inline-flex;align-items:center;padding:0 8px;height:22px;border-radius:11px;background:var(--primary-container,#1c1b1b);color:var(--on-primary,#fff);font-size:11px;font-weight:600;line-height:1;user-select:none;';
        chipEl.textContent = '/' + chip.name;
        chipsRow.appendChild(chipEl);
      });
      bubble.appendChild(chipsRow);
    }

    // 用户消息：显示附带的图层信息
    if (type === 'user' && options.attachLayer) {
      var layerInfo = options.attachLayer;
      var attachRow = document.createElement('div');
      attachRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin-top:8px;padding:6px 10px;border:1px solid var(--ui-gray-200);border-radius:2px;background:var(--ui-gray-50,#f8f9fa);';
      attachRow.innerHTML =
        "<span class=\"ui-icon\" aria-hidden=\"true\" style=\"flex-shrink:0;;width:16px;height:16px;--ui-icon-image:url('/assets/ui-icons/icon-4575ae6edd83.png')\"></span><span style=\"font-size:12px;font-weight:600;color:var(--ui-gray-900);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;\">" + (layerInfo.name || '图层') + '</span>' +
        '<span style="font-size:11px;color:var(--ui-gray-300);margin-left:auto;">' + (layerInfo.type || '') + (layerInfo.count !== undefined ? ' · ' + layerInfo.count + ' 要素' : '') + '</span>';
      bubble.appendChild(attachRow);
    }

    // 用户消息：显示被引用的回复内容
    if (type === 'user' && options.quoted && options.quoted.text) {
      var quotedInfo = options.quoted;
      var quotedRow = document.createElement('div');
      quotedRow.style.cssText = 'margin-top:8px;padding:6px 10px;border-left:3px solid var(--ui-gray-300,#d0d5dd);background:var(--ui-gray-50,#f8f9fa);font-size:12px;color:var(--ui-gray-500,#777);white-space:pre-wrap;word-break:break-word;max-height:140px;overflow:hidden;';
      var quotedHead = document.createElement('div');
      quotedHead.textContent = '引用回复';
      quotedHead.style.cssText = 'font-size:11px;color:var(--ui-gray-400,#999);margin-bottom:4px;font-weight:600;';
      var quotedBody = document.createElement('div');
      quotedBody.textContent = quotedInfo.text;
      quotedRow.appendChild(quotedHead);
      quotedRow.appendChild(quotedBody);
      bubble.appendChild(quotedRow);
    }

    if (options.code) {
      const codeBlock = document.createElement('div');
      codeBlock.className = 'message-code-block';
      codeBlock.textContent = options.code;
      bubble.appendChild(codeBlock);
    }

    // AI 消息：展示 Token 计量角标（带 tooltip）
    if (type === 'ai' && !options.noMarkdown && options.tokenUsage) {
      const u = options.tokenUsage;
      const isEst = u.type === 'estimate';
      const badge = document.createElement('div');
      badge.className = 'token-usage-badge' + (isEst ? ' estimate' : '');
      const inStr = u.input_tokens >= 1000 ? (u.input_tokens / 1000).toFixed(1) + 'k' : u.input_tokens;
      const outStr = u.output_tokens >= 1000 ? (u.output_tokens / 1000).toFixed(1) + 'k' : u.output_tokens;
      badge.innerHTML = (isEst ? '≈' : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>') + ' ↑' + inStr + ' ↓' + outStr + ' tok';
      badge.title = (isEst ? '【估算 Token (字符÷3.0)】' : '【真实 API Token】') +
        '\n• 输入 (Prompt): ' + u.input_tokens + ' tok' +
        '\n• 输出 (Completion): ' + u.output_tokens + ' tok' +
        '\n• 绑定工具: ' + (u.tool_count || 0) + ' 个 (Schema ' + (u.schema_chars || 0) + ' 字符)' +
        '\n• 来源: ' + (isEst ? '模型未回传 usage，本地校准估算' : '接口官方回传 usage_metadata');
      bubble.appendChild(badge);
    }

    // AI 消息右下角引用按钮（复制按钮左侧，跳过加载气泡）
    if (type === 'ai' && !options.noMarkdown) {
      const quoteBtn = document.createElement('button');
      quoteBtn.className = 'btn-quote-ai';
      quoteBtn.title = '引用此回复';
      quoteBtn.innerHTML = "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:16px;height:16px;--ui-icon-image:url('/assets/ui-icons/icon-b335f3f42caa.png')\"></span>";
      quoteBtn.addEventListener('click', function() {
        const plainText = content.textContent || content.innerText || text;
        _quotedMessage = { text: plainText.slice(0, 3000), time: Date.now() };
        _showQuoteBar(plainText);
        if (inputEl) inputEl.focus();
      });
      bubble.appendChild(quoteBtn);

      // AI 消息右下角复制按钮（跳过加载气泡）
      const copyBtn = document.createElement('button');
      copyBtn.className = 'btn-copy-ai';
      copyBtn.title = '复制回复';
      copyBtn.innerHTML = "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:16px;height:16px;--ui-icon-image:url('/assets/ui-icons/icon-7f7694309e7d.png')\"></span>";
      copyBtn.addEventListener('click', function() {
        // 取纯文本（跳过 markdown HTML 标签）
        const plainText = content.textContent || content.innerText || text;
        navigator.clipboard.writeText(plainText).then(function() {
          copyBtn.classList.add('copied');
          copyBtn.innerHTML = "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-eba4e2d5125d.png')\"></span>";
          setTimeout(function() {
            copyBtn.classList.remove('copied');
            copyBtn.innerHTML = "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";--ui-icon-image:url('/assets/ui-icons/icon-7f7694309e7d.png')\"></span>";
          }, 2000);
        }).catch(function() {
          // fallback: 用 textarea 复制
          const ta = document.createElement('textarea');
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
    scrollMessages();
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
    const container = document.createElement('span');
    container.className = 'flip-timer';

    // 存储当前显示的 6 个数字值 [h1,h2,m1,m2,s1,s2]
    container._current = [0, 0, 0, 0, 0, 0];

    // 布局：HH : MM : SS
    const layout = [
      { type: 'digit' }, { type: 'digit' },
      { type: 'sep', char: ':' },
      { type: 'digit' }, { type: 'digit' },
      { type: 'sep', char: ':' },
      { type: 'digit' }, { type: 'digit' }
    ];

    container._digits = [];

    layout.forEach(function(item) {
      if (item.type === 'sep') {
        const sep = document.createElement('span');
        sep.className = 't-sep';
        sep.textContent = item.char;
        container.appendChild(sep);
      } else {
        const digitEl = document.createElement('span');
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
    const h = Math.floor(elapsed / 3600);
    const m = Math.floor((elapsed % 3600) / 60);
    const s = elapsed % 60;

    // 拆成 6 个单独的数字
    const timeDigits = [
      Math.floor(h / 10) % 10, h % 10,
      Math.floor(m / 10),      m % 10,
      Math.floor(s / 10),      s % 10
    ];

    const current = timerEl._current;
    const digits  = timerEl._digits;

    for (let i = 0; i < 6; i++) {
      if (current[i] !== timeDigits[i]) {
        // 方向规则：
        //   第 6 位（秒个位 i=5）是主动计时的 → 向上翻
        //   其余位都是因为进位才触发变化 → 向下翻
        const direction = (i === 5) ? 'up' : 'down';
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
    const main = digitEl.querySelector('.t-d-main');
    const oldVal = main.textContent;
    if (oldVal === String(newVal)) return;

    const ANIM_MS = 260;

    // 旧数字飞出
    const outEl = document.createElement('span');
    outEl.className = 't-d-float';
    outEl.textContent = oldVal;
    outEl.style.animation = (dir === 'up' ? 't-up-out' : 't-down-out') + ' ' + ANIM_MS + 'ms ease forwards';

    // 新数字飞入
    const inEl = document.createElement('span');
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

  /** 通过命令名触发斜杠命令（供菜单栏调用） */
  function triggerSlash(name) {
    var cmd = SLASH_COMMANDS.find(function(c) { return c.name === name; });
    if (cmd) _applySlashCommand(cmd);
  }

  // 模式已固定为完整模式，不再支持切换
  function getMode() { return 'full'; }
  function setMode(mode) { /* 已禁用模式切换 */ }

  /** 直连工具结果上图（手动面板通道）：与聊天返回同构，走共享状态与既有 op 逻辑 */
  function applyToolResult(result) {
    if (!result) return;
    if (result.clear_layers && GIS.layers) {
      (GIS.layers.getLayers() || []).forEach(function (l) {
        if (l.layer_id) GIS.layers.removeLayer(l.layer_id);
      });
    }
    (result.layers || []).forEach(function (layer, idx) {
      if (!window.GIS.state) return;
      const layerName = layer.name || ('图层' + (idx + 1));
      window.GIS.state.addLayer({
        layer_id: 'manual_' + Date.now() + '_' + idx,
        name: layerName + '_' + Date.now() + '_' + idx,
        geojson: layer.geojson || layer,
        style: layer.style || null,
        source: 'manual',
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
        case 'center':
          if (GIS.map.setView && op.center) GIS.map.setView([op.center[1], op.center[0]], op.zoom || 13);
          break;
        case 'set_color':
          if (GIS.map.setLayerColor) GIS.map.setLayerColor(op.name, op.color);
          break;
        case 'set_style':
          if (GIS.map.setLayerStyle) GIS.map.setLayerStyle(op.name, op.style || {});
          break;
        case 'toggle':
          if (GIS.layers && GIS.layers.toggleVisibility) {
            const t = (GIS.layers.getLayers() || []).find(l => l._rawName === op.name || l.filename === op.name);
            if (t) GIS.layers.toggleVisibility(t.layer_id);
          }
          break;
        case 'remove':
          if (GIS.layers) {
            const t2 = (GIS.layers.getLayers() || []).find(l => l._rawName === op.name || l.filename === op.name);
            if (t2) GIS.layers.removeLayer(t2.layer_id);
          }
          break;
        case 'north_arrow':
          if (GIS.map.showNorthArrow) GIS.map.showNorthArrow();
          break;
        case 'labels':
          if (GIS.layers && GIS.layers.addLabels) GIS.layers.addLabels(op.name, op.field);
          break;
        case 'legend':
          if (GIS.layers && GIS.layers.addLegend) GIS.layers.addLegend(op.name);
          break;
        case 'symbology':
          if (GIS.layers) {
            if (op.symbology_type === 'graduated') GIS.layers.applyGraduatedColors(op.name, op.field, op.classes, op.scheme);
            else if (op.symbology_type === 'unique') GIS.layers.applyUniqueValues(op.name, op.field, op.scheme);
          }
          break;
        case 'dem_result':
          if (op.url && op.bounds) GIS.map.addImageOverlay(op.url, op.bounds, op.name);
          break;
        case 'time_animation':
          if (GIS.map.startTimeAnimation) GIS.map.startTimeAnimation(op.name, op.time_field, op.time_values, op.interval_ms);
          break;
        case 'drill':
          // 行政区下钻/上钻：同步导航栈（面包屑/视野/父级图层显隐）
          if (window.GIS.state) {
            if (op.direction === 'up') window.GIS.state.drillUpTo();
            else if (op.adcode) window.GIS.state.drillSyncFromAgent(op);
          }
          break;
        case 'visualize':
          if (window.GIS.state && typeof window.GIS.state.applyVisualization === 'function' && op.viz) {
            const vizRec = (window.GIS.state.getLayers() || []).find(
              l => l.name === op.name || l._rawName === op.name);
            if (vizRec) window.GIS.state.applyVisualization(vizRec.layer_id, op.viz);
          }
          break;
      }
    });
    (result.images || []).forEach(function (item) {
      const url = typeof item === 'string' ? item : (item.url || '');
      if (!url) return;
      const fullUrl = url.startsWith('http') ? url : (window.GIS.api ? window.GIS.api.BASE_URL + url : url);
      if (window.GIS.chat && window.GIS.chat.addMessage) {
        window.GIS.chat.addMessage('产物文件：' + fullUrl, 'system');
      }
    });
    if (result.heatmap && result.heatmap.points && result.heatmap.points.length > 0 && GIS.map && GIS.map.loadHeatmap) {
      GIS.map.loadHeatmap(result.heatmap.points, result.heatmap.name || '热力图', result.heatmap.options || {});
    }
    // 地理质量自检警告：显式展示，不静默吞掉可疑数据
    (result.qa_warnings || []).forEach(function (w) {
      if (window.GIS.chat && window.GIS.chat.addMessage) {
        window.GIS.chat.addMessage('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> 质量提示[' + (w.layer || '') + ']: ' + w.warning, 'system');
      }
    });
    if (window.GIS.history && typeof window.GIS.history.refresh === 'function') {
      const hp = document.getElementById('historyPanel');
      if (hp && hp.classList.contains('open')) {
        setTimeout(function () { window.GIS.history.refresh(); }, 1000);
      }
    }
  }

  GIS.chat = { init, send, addMessage, clear, setPendingLayer, sendMessage: send, clearSession, _resetUIAfterStop, SLASH_COMMANDS, triggerSlash, getMode, setMode, applyToolResult };
})();
