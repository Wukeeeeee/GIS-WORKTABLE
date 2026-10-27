window.GIS = window.GIS || {};

/**
 * analysis_tools.js  分析工具窗口
 * 顶部菜单「工具」里的 20 个分析工具各自打开独立窗口，只显示该工具需要的参数；
 * 「分析工具」条目打开全部工具选择器（启动台），点选后再打开对应工具的窗口。
 * 全部工具经 /api/tools/invoke 直连后端执行，不经 LLM。
 * 面板样式复用 spatial-* 公共类，不新增 CSS、不新增色值。
 */
(function () {
  'use strict';

  var GIS = window.GIS;
  var PANEL_WIDTH = 400;

  var OPS = [
    // 栅格分析
    { id: 'reclassify', group: '栅格分析', label: '栅格重分类', i18nKey: 'raster.reclassify', tool: 'raster_reclassify', args: {}, layerHint: '栅格图层', extra: 'reclassify' },
    { id: 'focal', group: '栅格分析', label: '邻域统计', i18nKey: 'raster.focal-statistics', tool: 'raster_focal_stats', args: {}, layerHint: '栅格图层', extra: 'focal' },
    { id: 'euclid', group: '栅格分析', label: '欧氏距离', i18nKey: 'raster.euclidean-distance', tool: 'euclidean_distance', args: {}, layerHint: '栅格图层', extra: 'sourceValue' },
    { id: 'mask', group: '栅格分析', label: '按掩膜提取', i18nKey: 'raster.mask-extraction', tool: 'raster_extract_by_mask', args: {}, layerHint: '栅格图层', layerHint2: '掩膜矢量', layers: ['raster_layer', 'zone_layer'], extra: 'inside' },
    { id: 'surface', group: '栅格分析', label: '表面体积', i18nKey: 'tool.surface-volumes', tool: 'surface_volumes', args: {}, layerHint: '变化前 DEM', layerHint2: '变化后 DEM', layers: ['before_layer', 'after_layer'], optionalLayers: ['after_layer'], extra: 'reference' },
    // 矢量与属性
    { id: 'join', group: '矢量与属性', label: '属性字段连接', i18nKey: 'tool.attribute-join', tool: 'join_field', args: {}, layerHint: '目标图层', layerHint2: '连接图层', layers: ['target_layer', 'join_layer'], extra: 'join' },
    { id: 'geomattrs', group: '矢量与属性', label: '几何属性', i18nKey: 'tool.geometry-attributes', tool: 'geometry_attributes', args: {}, layerHint: '矢量图层', extra: 'metrics' },
    { id: 'mingeom', group: '矢量与属性', label: '最小包络几何', i18nKey: 'tool.minimum-bounding-geometry', tool: 'minimum_bounding_geometry', args: {}, layerHint: '矢量图层', extra: 'minGeom' },
    { id: 'p2l', group: '矢量与属性', label: '点集转线', i18nKey: 'tool.points-to-line', tool: 'points_to_line', args: {}, layerHint: '点图层', extra: 'p2l' },
    { id: 'gpal', group: '矢量与属性', label: '沿线生成点', i18nKey: 'tool.points-along-lines', tool: 'generate_points_along_lines', args: {}, layerHint: '线图层', extra: 'gpal' },
    // 空间统计
    { id: 'weights', group: '空间统计', label: '空间权重矩阵', i18nKey: 'tool.spatial-weights', tool: 'spatial_weights_matrix', args: {}, layerHint: '矢量图层', extra: 'weights' },
    { id: 'regression', group: '空间统计', label: '空间回归', i18nKey: 'tool.spatial-regression', tool: 'spatial_regression', args: {}, layerHint: '矢量图层', extra: 'regression' },
    { id: 'directional', group: '空间统计', label: '方向分布', i18nKey: 'tool.standard-deviation-ellipse', tool: 'directional_distribution', args: {}, layerHint: '点图层', extra: 'directional' },
    { id: 'tendency', group: '空间统计', label: '中心趋势', i18nKey: 'tool.central-tendency', tool: 'central_tendency', args: {}, layerHint: '点图层', extra: 'tendency' },
    { id: 'od', group: '空间统计', label: 'OD 成本矩阵', i18nKey: 'tool.od-cost-matrix', tool: 'od_cost_matrix', args: {}, layerHint: '起点图层', layerHint2: '终点图层', layers: ['origins_layer', 'destinations_layer'], extra: 'od' },
    // 转换与代价距离
    { id: 'f2r', group: '转换与代价距离', label: '矢量转栅格', i18nKey: 'tool.vector-to-raster', tool: 'feature_to_raster', args: {}, layerHint: '矢量图层', extra: 'f2r' },
    { id: 'r2f', group: '转换与代价距离', label: '栅格转矢量', i18nKey: 'tool.raster-to-vector', tool: 'raster_to_feature', args: {}, layerHint: '栅格图层', extra: 'r2f' },
    { id: 'fishnet', group: '转换与代价距离', label: '渔网格网', i18nKey: 'tool.create-fishnet', tool: 'create_fishnet', args: {}, layerHint: '范围图层（可选）', layers: ['extent_layer'], optionalLayers: ['extent_layer'], extra: 'fishnet' },
    { id: 'costdist', group: '转换与代价距离', label: '代价距离', i18nKey: 'tool.cost-distance', tool: 'cost_distance', args: {}, layerHint: '代价栅格', layerHint2: '源图层', layers: ['cost_layer', 'source_layer'], extra: 'costDistance' },
    { id: 'leastcost', group: '转换与代价距离', label: '最小成本路径', i18nKey: 'tool.least-cost-path', tool: 'least_cost_path', args: {}, layerHint: '代价栅格', layerHint2: '源图层', layerHint3: '目标图层', layers: ['cost_layer', 'source_layer', 'destination_layer'], extra: 'leastCost' },
  ];

  var PANEL_HTML =
    ("<div class=\"spatial-panel\" id=\"analysisToolsPanel\">"
      + "<div class=\"spatial-toolbar\" id=\"analysisToolsToolbar\">"
      + "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:18px;height:18px;--ui-icon-image:url('/assets/ui-icons/icon-9955681a84e8.png')\">"
      + "</span>"
      + "<span class=\"spatial-toolbar-title\">分析工具"
      + "</span>"
      + "<button class=\"spatial-toolbar-close\" id=\"analysisToolsClose\">"
      + "<span class=\"ui-icon\" aria-hidden=\"true\" style=\";width:16px;height:16px;--ui-icon-image:url('/assets/ui-icons/icon-28a441e0afbc.png')\">"
      + "</span>"
      + "</button>"
      + "</div>"
      + "<div class=\"spatial-body\" id=\"analysisToolsBody\">"
      + "<div class=\"spatial-field\">"
      + "<label for=\"atOp\">功能</label>"
      + "<select id=\"atOp\"></select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atLayerField\">"
      + "<label id=\"atLayerLabel\" for=\"atLayer\">图层</label>"
      + "<select id=\"atLayer\"><option value=\"\">-- 请选择图层 --</option></select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atLayer2Field\" style=\"display:none\">"
      + "<label id=\"atLayer2Label\" for=\"atLayer2\">图层</label>"
      + "<select id=\"atLayer2\"><option value=\"\">-- 请选择图层 --</option></select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atLayer3Field\" style=\"display:none\">"
      + "<label id=\"atLayer3Label\" for=\"atLayer3\">图层</label>"
      + "<select id=\"atLayer3\"><option value=\"\">-- 请选择图层 --</option></select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atField1Field\" style=\"display:none\">"
      + "<label id=\"atField1Label\" for=\"atField1\">字段</label>"
      + "<select id=\"atField1\"><option value=\"\">-- 选择字段 --</option></select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atField2Field\" style=\"display:none\">"
      + "<label id=\"atField2Label\" for=\"atField2\">字段</label>"
      + "<select id=\"atField2\"><option value=\"\">-- 选择字段 --</option></select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atReclassMethodField\" style=\"display:none\">"
      + "<label for=\"atReclassMethod\">重分类方法</label>"
      + "<select id=\"atReclassMethod\">"
      + "<option value=\"mapping\">映射表</option>"
      + "<option value=\"equal_interval\">等间距</option>"
      + "<option value=\"quantile\">分位数</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atMappingField\" style=\"display:none\">"
      + "<label for=\"atMapping\">映射（0-10=1;10-50=2）</label>"
      + "<input type=\"text\" id=\"atMapping\" class=\"spatial-input\" placeholder=\"0-10=1;10-50=2;50+=3\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atClassesField\" style=\"display:none\">"
      + "<label for=\"atClasses\">类别数</label>"
      + "<input type=\"number\" id=\"atClasses\" class=\"spatial-input\" value=\"5\" min=\"2\" max=\"32\" step=\"1\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atFocalStatField\" style=\"display:none\">"
      + "<label for=\"atFocalStat\">统计量</label>"
      + "<select id=\"atFocalStat\">"
      + "<option value=\"mean\">均值</option>"
      + "<option value=\"median\">中位数</option>"
      + "<option value=\"min\">最小值</option>"
      + "<option value=\"max\">最大值</option>"
      + "<option value=\"std\">标准差</option>"
      + "<option value=\"range\">极差</option>"
      + "<option value=\"majority\">众数</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atFocalSizeField\" style=\"display:none\">"
      + "<label for=\"atFocalSize\">窗口大小（奇数）</label>"
      + "<input type=\"number\" id=\"atFocalSize\" class=\"spatial-input\" value=\"3\" min=\"3\" max=\"9\" step=\"2\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atSourceValueField\" style=\"display:none\">"
      + "<label for=\"atSourceValue\">源值（留空表示非零像元）</label>"
      + "<input type=\"number\" id=\"atSourceValue\" class=\"spatial-input\" step=\"any\" placeholder=\"可选\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atInsideField\" style=\"display:none\">"
      + "<label for=\"atInside\"><input type=\"checkbox\" id=\"atInside\" checked> 保留掩膜内区域</label>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atReferenceField\" style=\"display:none\">"
      + "<label for=\"atReference\">参考高程（留空表示前后 DEM 对比）</label>"
      + "<input type=\"number\" id=\"atReference\" class=\"spatial-input\" step=\"any\" placeholder=\"可选\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atJoinFieldsField\" style=\"display:none\">"
      + "<label for=\"atJoinFields\">携带字段（逗号分隔，留空为全部）</label>"
      + "<input type=\"text\" id=\"atJoinFields\" class=\"spatial-input\" placeholder=\"可选\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atHowField\" style=\"display:none\">"
      + "<label for=\"atHow\">连接方式</label>"
      + "<select id=\"atHow\">"
      + "<option value=\"left\">左连接</option>"
      + "<option value=\"inner\">内连接</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atMetricsField\" style=\"display:none\">"
      + "<label for=\"atMetrics\">指标（逗号分隔）</label>"
      + "<input type=\"text\" id=\"atMetrics\" class=\"spatial-input\" value=\"area,length,perimeter,centroid\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atKindField\" style=\"display:none\">"
      + "<label for=\"atKind\">几何类型</label>"
      + "<select id=\"atKind\">"
      + "<option value=\"envelope\">外包矩形</option>"
      + "<option value=\"convex_hull\">凸包</option>"
      + "<option value=\"circle\">最小外接圆</option>"
      + "<option value=\"oriented_bbox\">定向矩形</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atCloseRingField\" style=\"display:none\">"
      + "<label for=\"atCloseRing\"><input type=\"checkbox\" id=\"atCloseRing\"> 闭合线环</label>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atIntervalField\" style=\"display:none\">"
      + "<label for=\"atInterval\">间隔</label>"
      + "<input type=\"number\" id=\"atInterval\" class=\"spatial-input\" value=\"100\" min=\"0\" step=\"10\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atUnitField\" style=\"display:none\">"
      + "<label for=\"atUnit\">单位</label>"
      + "<select id=\"atUnit\">"
      + "<option value=\"m\">米</option>"
      + "<option value=\"km\">千米</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atWeightsMethodField\" style=\"display:none\">"
      + "<label for=\"atWeightsMethod\">权重方法</label>"
      + "<select id=\"atWeightsMethod\">"
      + "<option value=\"queen\">Queen 邻接</option>"
      + "<option value=\"rook\">Rook 邻接</option>"
      + "<option value=\"knn\">K 近邻</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atKField\" style=\"display:none\">"
      + "<label for=\"atK\">K 近邻数</label>"
      + "<input type=\"number\" id=\"atK\" class=\"spatial-input\" value=\"8\" min=\"1\" max=\"64\" step=\"1\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atIndependentsField\" style=\"display:none\">"
      + "<label for=\"atIndependents\">自变量字段（逗号分隔）</label>"
      + "<input type=\"text\" id=\"atIndependents\" class=\"spatial-input\" placeholder=\"x1,x2\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atNetworkSourceField\" style=\"display:none\">"
      + "<label for=\"atNetworkSource\">路网来源</label>"
      + "<select id=\"atNetworkSource\">"
      + "<option value=\"osm\">OSM 路网</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atCellSizeField\" style=\"display:none\">"
      + "<label for=\"atCellSize\">像元大小（0 为自动）</label>"
      + "<input type=\"number\" id=\"atCellSize\" class=\"spatial-input\" value=\"0\" min=\"0\" step=\"any\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atConnectivityField\" style=\"display:none\">"
      + "<label for=\"atConnectivity\">连通性</label>"
      + "<select id=\"atConnectivity\">"
      + "<option value=\"8\">8 邻域</option>"
      + "<option value=\"4\">4 邻域</option>"
      + "</select>"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atSimplifyField\" style=\"display:none\">"
      + "<label for=\"atSimplify\">简化容差（0 为不简化）</label>"
      + "<input type=\"number\" id=\"atSimplify\" class=\"spatial-input\" value=\"0\" min=\"0\" step=\"any\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atR2FFieldField\" style=\"display:none\">"
      + "<label for=\"atR2FField\">字段（可选）</label>"
      + "<input type=\"text\" id=\"atR2FField\" class=\"spatial-input\" placeholder=\"可选\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atRowsField\" style=\"display:none\">"
      + "<label for=\"atRows\">行数（0 为按像元大小）</label>"
      + "<input type=\"number\" id=\"atRows\" class=\"spatial-input\" value=\"0\" min=\"0\" step=\"1\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atColsField\" style=\"display:none\">"
      + "<label for=\"atCols\">列数（0 为按像元大小）</label>"
      + "<input type=\"number\" id=\"atCols\" class=\"spatial-input\" value=\"0\" min=\"0\" step=\"1\">"
      + "</div>"
      + "<div class=\"spatial-field\" id=\"atAllTouchedField\" style=\"display:none\">"
      + "<label for=\"atAllTouched\"><input type=\"checkbox\" id=\"atAllTouched\"> 包含所有接触像元</label>"
      + "</div>"
      + "<button class=\"spatial-run-btn\" id=\"atRun\" type=\"button\">运行</button>"
      + "</div>"
      + "</div>");

  function _opById(id) {
    for (var i = 0; i < OPS.length; i++) if (OPS[i].id === id) return OPS[i];
    return null;
  }

  function _opLayerArgs(op) {
    if (op.layers && op.layers.length) return op.layers;
    if (op.layerHint) return ['layer_name'];
    return [];
  }

  function _opLayerHint(op, i) {
    if (i === 0) return op.layerHint || '图层';
    if (i === 1) return op.layerHint2 || '图层';
    return op.layerHint3 || '图层';
  }

  function _show(id, on) {
    var el = _g(id);
    if (el) el.style.display = on ? '' : 'none';
  }

  function _setLabel(id, text) {
    var el = _g(id);
    if (el) el.textContent = text;
  }

  function _text(id) {
    var el = _g(id);
    return el ? String(el.value || '').trim() : '';
  }

  function _num(id, fallback) {
    var el = _g(id);
    var v = el ? parseFloat(el.value) : NaN;
    return isNaN(v) ? fallback : v;
  }

  function _int(id, fallback) {
    var el = _g(id);
    var v = el ? parseInt(el.value, 10) : NaN;
    return isNaN(v) ? fallback : v;
  }

  function _checked(id) {
    var el = _g(id);
    return !!(el && el.checked);
  }

  /** Scoped id lookup: resolves against the panel currently stored in _root. */
  function _g(id) {
    if (!_root) return document.getElementById(id);
    var suffix = _root.getAttribute('data-at-suffix');
    if (!suffix) return document.getElementById(id);
    return _root.querySelector('#' + id + '-' + suffix);
  }

  // =====================================================================
  // One independent window per analysis tool.
  // ---------------------------------------------------------------------
  // `analysisToolsPanel` keeps its fixed id and becomes the "all tools"
  // launcher (opened by the top-menu entry). Every tool gets its own panel
  // whose DOM ids are suffixed with the op id, so several tool windows can
  // be open at the same time without clashing.
  // =====================================================================
  var _root = null;      // panel element the field helpers operate on
  var _panels = {};      // opId -> { op, wrapper, container, root }
  var _launcher = null;
  var _keepBound = false;

  var _iconTags = PANEL_HTML.match(/--ui-icon-image:url\('([^']+)'\)/g) || [];
  function _iconUrl(tag, fallback) {
    var m = tag ? /url\('([^']+)'\)/.exec(tag) : null;
    return m ? m[1] : fallback;
  }
  var PANEL_ICON = _iconUrl(_iconTags[0], '');
  var CLOSE_ICON = _iconUrl(_iconTags[1] || _iconTags[0], PANEL_ICON);
  var PANEL_TITLE = (PANEL_HTML.match(/spatial-toolbar-title">([^<]*)</) || [])[1] || '';
  var GROUP_I18N_KEYS = {
    '栅格分析': 'analysis.group.raster',
    '矢量与属性': 'analysis.group.vector',
    '空间统计': 'analysis.group.statistics',
    '转换与代价距离': 'analysis.group.conversion',
  };

  function _translate(key, fallback) {
    return GIS.i18n && typeof GIS.i18n.t === 'function' ? GIS.i18n.t(key, fallback) : fallback;
  }

  function _refreshLauncherLabels() {
    if (!_launcher || !_launcher.grid) return;
    Array.prototype.forEach.call(_launcher.grid.children, function (element) {
      if (!element._i18nKey) return;
      element.textContent = _translate(element._i18nKey, element._i18nFallback);
      if (element._toolId) element.title = element.textContent + ' - ' + element._toolId;
    });
    if (_launcher.titleElement) _launcher.titleElement.textContent = _translate('tool.analysis-tools', PANEL_TITLE);
  }
  if (document.addEventListener) document.addEventListener('gis:languagechange', _refreshLauncherLabels);

  var GROUP_COLOR = {};
  var GROUP_ORDER = [];
  (function () {
    var palette = ['#2b6cb0', '#388e3c', '#7b1fa2', '#d97706'];
    OPS.forEach(function (op) {
      if (GROUP_ORDER.indexOf(op.group) < 0) GROUP_ORDER.push(op.group);
      if (!GROUP_COLOR[op.group]) {
        GROUP_COLOR[op.group] = palette[Object.keys(GROUP_COLOR).length % palette.length];
      }
    });
  })();

  /** Give every id / for attribute a private suffix so panels never clash. */
  function _suffixIds(html, suffix) {
    return html
      .replace(/\bid="([A-Za-z0-9_-]+)"/g, function (m, id) { return 'id="' + id + '-' + suffix + '"'; })
      .replace(/\bfor="([A-Za-z0-9_-]+)"/g, function (m, id) { return 'for="' + id + '-' + suffix + '"'; });
  }

  function _fillOpSelect(sel, op) {
    GROUP_ORDER.forEach(function (group) {
      var og = document.createElement('optgroup');
      og.label = group;
      OPS.forEach(function (o) {
        if (o.group !== group) return;
        var opt = document.createElement('option');
        opt.value = o.id;
        opt.textContent = o.label;
        og.appendChild(opt);
      });
      sel.appendChild(og);
    });
    sel.value = op.id;
  }

  function _bindResize() {
    if (_keepBound) return;
    _keepBound = true;
    window.addEventListener('resize', _keepVisible);
  }

  function _reveal(container, root, panelId) {
    container.style.display = '';
    if (GIS.workspace) {
      GIS.workspace.expandPanel(panelId);
      return;
    }
    root.classList.remove('is-hidden');
    root.removeAttribute('hidden');
    if (root.style.display === 'none') root.style.removeProperty('display');
  }

  function _buildToolPanel(op) {
    var suffix = op.id;
    var wrapper = document.createElement('div');
    wrapper.id = 'analysisToolWrapper-' + suffix;
    var container = document.createElement('div');
    container.id = 'analysisToolContainer-' + suffix;
    container.className = 'analysis-tool-container';
    container.style.display = 'none';
    container.innerHTML = _suffixIds(PANEL_HTML, suffix);
    wrapper.appendChild(container);
    document.documentElement.appendChild(wrapper);

    var root = container.querySelector('.spatial-panel') || container.firstElementChild;
    root.setAttribute('data-at-suffix', suffix);
    var titleEl = root.querySelector('.spatial-toolbar-title');
    if (titleEl) titleEl.textContent = op.label;

    // The tool picker stays in the DOM (the existing helpers read atOp) but
    // is never shown: this window serves exactly one tool.
    var opSel = container.querySelector('#atOp-' + suffix);
    if (opSel) {
      _fillOpSelect(opSel, op);
      var field = opSel.closest ? opSel.closest('.spatial-field') : null;
      if (field) field.style.display = 'none';
      opSel.addEventListener('change', function () { _applyOpVisibility(root); _refreshLayers(root); });
    }

    var closeBtn = container.querySelector('#analysisToolsClose-' + suffix);
    if (closeBtn) closeBtn.addEventListener('click', function () { container.style.display = 'none'; });

    ['atLayer-' + suffix, 'atLayer2-' + suffix].forEach(function (id) {
      var el = container.querySelector('#' + id);
      if (el) el.addEventListener('change', function () { _refreshFieldSel(root); });
    });
    ['atReclassMethod-' + suffix, 'atWeightsMethod-' + suffix].forEach(function (id) {
      var el = container.querySelector('#' + id);
      if (el) el.addEventListener('change', function () { _applyOpVisibility(root); });
    });
    var runBtn = container.querySelector('#atRun-' + suffix);
    if (runBtn) runBtn.addEventListener('click', function () { return _run(root); });

    if (GIS.workspace) {
      GIS.workspace.preparePanel(root.id, 'analysisToolsToolbar-' + suffix, 'analysisToolsClose-' + suffix, op.label);
    }
    _centerPanel(container);
    // Cascade tool windows so several open at once stay readable.
    var openCount = Object.keys(_panels).length;
    if (openCount > 0) {
      var offset = 22 * (openCount % 7);
      var pos = _clampToMapArea(container, (parseFloat(container.style.left) || 0) + offset,
        (parseFloat(container.style.top) || 0) + offset);
      container.style.left = pos[0] + 'px';
      container.style.top = pos[1] + 'px';
    }
    _initDrag(container);
    _bindResize();
    _applyOpVisibility(root);

    var rec = { op: op, wrapper: wrapper, container: container, root: root };
    _panels[op.id] = rec;
    return rec;
  }

  function _showTool(opId) {
    var op = _opById(opId);
    if (!op) return _showLauncher();
    var rec = _panels[op.id] || _buildToolPanel(op);
    _reveal(rec.container, rec.root, rec.root.id);
    _applyOpVisibility(rec.root);
    _refreshLayers(rec.root);
    return rec;
  }

  function _buildLauncher() {
    var wrapper = document.createElement('div');
    wrapper.id = 'analysisToolsPanelWrapper';
    var container = document.createElement('div');
    container.id = 'analysisToolsPanelContainer';
    container.style.display = 'none';
    wrapper.appendChild(container);
    document.documentElement.appendChild(wrapper);
    container.innerHTML =
      '<div class="spatial-panel" id="analysisToolsPanel">' +
        '<div class="spatial-toolbar" id="analysisToolsToolbar">' +
          '<span class="ui-icon" aria-hidden="true" style=";width:18px;height:18px;--ui-icon-image:url(\'' + PANEL_ICON + '\')"></span>' +
          '<span class="spatial-toolbar-title">' + _translate('tool.analysis-tools', PANEL_TITLE) + '</span>' +
          '<button class="spatial-toolbar-close" id="analysisToolsClose">' +
            '<span class="ui-icon" aria-hidden="true" style=";width:16px;height:16px;--ui-icon-image:url(\'' + CLOSE_ICON + '\')"></span>' +
          '</button>' +
        '</div>' +
        '<div class="spatial-body" id="analysisToolsBody"></div>' +
      '</div>';

    var root = container.firstElementChild;
    var body = container.querySelector('#analysisToolsBody');
    var grid = document.createElement('div');
    grid.className = 'at-tool-grid';
    grid.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;';
    GROUP_ORDER.forEach(function (group) {
      var head = document.createElement('div');
      head.style.cssText = 'flex:0 0 100%;margin:6px 0 2px;font-size:12px;color:var(--on-surface-variant,#5f5f5f);';
      head.textContent = _translate(GROUP_I18N_KEYS[group], group);
      head._i18nKey = GROUP_I18N_KEYS[group];
      head._i18nFallback = group;
      grid.appendChild(head);
      OPS.forEach(function (o) {
        if (o.group !== group) return;
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'at-tool-btn';
        var label = _translate(o.i18nKey, o.label);
        b.title = label + ' - ' + o.tool;
        b.textContent = label.replace(/\uFF08.*?\uFF09/g, '');
        b._i18nKey = o.i18nKey;
        b._i18nFallback = o.label.replace(/\uFF08.*?\uFF09/g, '');
        b._toolId = o.tool;
        b.style.cssText = 'font-size:12px;padding:4px 10px;border:1px solid var(--outline-variant,#e2e2e2);' +
          'border-radius:4px;background:var(--surface-container-low,#f7f7f7);color:var(--on-surface,#202020);cursor:pointer;line-height:1.4;';
        b.onclick = function () { _showTool(o.id); };
        grid.appendChild(b);
      });
    });
    if (body) body.appendChild(grid);

    var closeBtn = container.querySelector('#analysisToolsClose');
    if (closeBtn) closeBtn.addEventListener('click', function () { container.style.display = 'none'; });
    if (GIS.workspace) {
      GIS.workspace.preparePanel('analysisToolsPanel', 'analysisToolsToolbar', 'analysisToolsClose', _translate('tool.analysis-tools', PANEL_TITLE));
    }
    _centerPanel(container);
    _initDrag(container);
    _bindResize();
    _launcher = {
      wrapper: wrapper,
      container: container,
      root: root,
      grid: grid,
      titleElement: container.querySelector('.spatial-toolbar-title'),
    };
    _refreshLauncherLabels();
    return _launcher;
  }

  function _showLauncher() {
    if (!_launcher) _buildLauncher();
    _reveal(_launcher.container, _launcher.root, 'analysisToolsPanel');
    return _launcher;
  }

  function toggle() {
    var opId = window.GIS._lastMenuOp || '';
    window.GIS._lastMenuOp = '';
    if (opId && _opById(opId)) _showTool(opId);
    else _showLauncher();
  }

  function _applyOpVisibility(root) {
    _root = root;
    var op = _opById(_g('atOp').value);
    if (!op) return;
    var lArgs = _opLayerArgs(op);
    _show('atLayerField', lArgs.length >= 1);
    _show('atLayer2Field', lArgs.length >= 2);
    _show('atLayer3Field', lArgs.length >= 3);
    _setLabel('atLayerLabel', op.layerHint || '图层');
    _setLabel('atLayer2Label', op.layerHint2 || '图层');
    _setLabel('atLayer3Label', op.layerHint3 || '图层');

    var e = op.extra || '';
    var showField1 = ['join', 'minGeom', 'p2l', 'regression', 'directional', 'tendency', 'f2r'].indexOf(e) >= 0;
    var showField2 = ['join', 'p2l'].indexOf(e) >= 0;
    _show('atField1Field', showField1);
    _show('atField2Field', showField2);
    var label1 = '字段';
    if (e === 'join') label1 = '目标字段';
    else if (e === 'minGeom') label1 = '分组字段（可选）';
    else if (e === 'p2l') label1 = '分组字段';
    else if (e === 'regression') label1 = '因变量字段';
    else if (e === 'directional') label1 = '分组字段（可选）';
    else if (e === 'tendency') label1 = '权重字段（可选）';
    else if (e === 'f2r') label1 = '数值字段（可选）';
    _setLabel('atField1Label', label1);
    _setLabel('atField2Label', e === 'join' ? '连接字段' : (e === 'p2l' ? '排序字段（可选）' : '字段'));

    _show('atReclassMethodField', e === 'reclassify');
    _show('atMappingField', e === 'reclassify' && _g('atReclassMethod').value === 'mapping');
    _show('atClassesField', e === 'reclassify' && _g('atReclassMethod').value !== 'mapping');
    _show('atFocalStatField', e === 'focal');
    _show('atFocalSizeField', e === 'focal');
    _show('atSourceValueField', e === 'sourceValue');
    _show('atInsideField', e === 'inside');
    _show('atReferenceField', e === 'reference');
    _show('atJoinFieldsField', e === 'join');
    _show('atHowField', e === 'join');
    _show('atMetricsField', e === 'metrics');
    _show('atKindField', e === 'minGeom');
    _show('atCloseRingField', e === 'p2l');
    _show('atIntervalField', e === 'gpal');
    _show('atUnitField', e === 'gpal');
    _show('atWeightsMethodField', e === 'weights');
    _show('atKField', e === 'weights' && _g('atWeightsMethod').value === 'knn');
    _show('atIndependentsField', e === 'regression');
    _show('atNetworkSourceField', e === 'od');
    _show('atCellSizeField', e === 'f2r' || e === 'fishnet');
    _show('atConnectivityField', e === 'r2f');
    _show('atSimplifyField', e === 'r2f');
    _show('atR2FFieldField', e === 'r2f');
    _show('atRowsField', e === 'fishnet');
    _show('atColsField', e === 'fishnet');
    _show('atAllTouchedField', e === 'f2r');
    _refreshFieldSel(root);
  }

  /** 图层下拉：后端注册名 与 前端面板名 合并（直连前会自动补注册） */
  function _refreshLayers(root) {
    _root = root;
    var revision = root._layerRefreshRevision = (root._layerRefreshRevision || 0) + 1;
    function fill(backendNames) {
      if (revision !== root._layerRefreshRevision) return;
      var feNames = (GIS.layers && GIS.layers.getLayerNames) ? GIS.layers.getLayerNames() : [];
      var merged = Array.from(new Set(feNames.concat(backendNames).filter(function(name) { return typeof name === 'string' && name; })));
      _fillLayerSelect(root, 'atLayer', merged);
      _fillLayerSelect(root, 'atLayer2', merged);
      _fillLayerSelect(root, 'atLayer3', merged);
      _refreshFieldSel(root);
    }
    // Local layers remain usable while the backend is slow or unavailable.
    fill([]);
    return fetch((GIS.api && GIS.api.BASE_URL || '') + '/api/layers/names')
      .then(function (r) { if (!r.ok) throw new Error('图层列表读取失败'); return r.json(); })
      .then(function (data) { fill(data && Array.isArray(data.names) ? data.names : []); })
      .catch(function () { fill([]); });
  }

  function _fillLayerSelect(root, selId, names) {
    _root = root;
    var sel = _g(selId);
    if (!sel) return;
    var cur = sel.value;
    sel.innerHTML = '<option value="">-- 请选择图层 --</option>';
    names.forEach(function (n) {
      var opt = document.createElement('option');
      opt.value = n;
      opt.textContent = n;
      if (n === cur) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  function _refreshFieldSel(root) {
    _root = root;
    var op = _opById(_g('atOp').value);
    _fillFieldSel(root, 'atField1', _g('atLayer').value);
    if (op && op.extra === 'join') {
      _fillFieldSel(root, 'atField2', _g('atLayer2').value);
    } else {
      _fillFieldSel(root, 'atField2', _g('atLayer').value);
    }
  }

  function _fillFieldSel(root, selId, layerName) {
    _root = root;
    var sel = _g(selId);
    if (!sel) return;
    var cur = sel.value;
    sel.innerHTML = '<option value="">-- 选择字段 --</option>';
    if (!layerName || !GIS.layers || !GIS.layers.getLayerByName) return;
    var layer = GIS.layers.getLayerByName(layerName);
    var geojson = layer && layer.geojson;
    var features = geojson && geojson.type === 'Feature' ? [geojson]
      : geojson && Array.isArray(geojson.features) ? geojson.features : [];
    var fields = new Set();
    features.forEach(function (feature) {
      var props = feature && feature.properties;
      if (props && typeof props === 'object') {
        Object.keys(props).forEach(function (key) { fields.add(key); });
      }
    });
    fields.forEach(function (k) {
      if (!k || k === '_fid') return;
      var opt = document.createElement('option');
      opt.value = k;
      opt.textContent = k;
      if (k === cur) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  function _clampToMapArea(container, left, top) {
    if (GIS.workspace) return GIS.workspace.clampPanel(container, left, top, PANEL_WIDTH);
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var chatPanel = document.querySelector('.chat-panel');
    var minLeft = 4;
    if (chatPanel) {
      var r = chatPanel.getBoundingClientRect();
      minLeft = (r.width > 0 ? r.right : 0) + 4;
    }
    var w = container.offsetWidth || PANEL_WIDTH;
    var h = container.offsetHeight || 300;
    left = Math.max(minLeft, Math.min(vw - w - 10, left));
    top = Math.max(34, Math.min(vh - h - 10, top));
    return [left, top];
  }

  function _centerPanel(container) {
    if (GIS.workspace) {
      GIS.workspace.centerPanel(container, PANEL_WIDTH);
      return;
    }
    var vw = window.innerWidth;
    var chatPanel = document.querySelector('.chat-panel');
    var chatRight = 4;
    if (chatPanel) {
      var r = chatPanel.getBoundingClientRect();
      chatRight = (r.width > 0 ? r.right : 0) + 4;
    }
    var coords = _clampToMapArea(container, chatRight + (vw - chatRight - PANEL_WIDTH) / 2, 80);
    container.style.left = coords[0] + 'px';
    container.style.top = coords[1] + 'px';
    container.style.transform = 'none';
  }

  /** 面板保持在地图可见区域内（窗口缩放/侧栏宽度变化时）。 */
  function _keepVisible() {
    var list = [];
    Object.keys(_panels).forEach(function (id) { list.push(_panels[id].container); });
    if (_launcher) list.push(_launcher.container);
    list.forEach(function (container) {
      if (!container || container.style.display === 'none' || !container.offsetHeight) return;
      var r = container.getBoundingClientRect();
      var pos = _clampToMapArea(container, r.left, r.top);
      container.style.left = pos[0] + 'px';
      container.style.top = pos[1] + 'px';
    });
  }

  function _initDrag(container) {
    var header = container.querySelector('.spatial-toolbar');
    if (!header) return;
    var startX, startY, startLeft, startTop;
    function onStart(e) {
      if (e.target.closest('button')) return;
      var ev = e.touches ? e.touches[0] : e;
      startX = ev.clientX; startY = ev.clientY;
      var currentRect = container.getBoundingClientRect();
      startLeft = currentRect.left; startTop = currentRect.top;
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onEnd);
    }
    function onMove(e) {
      var ev = e.touches ? e.touches[0] : e;
      var c = _clampToMapArea(container, startLeft + ev.clientX - startX, startTop + ev.clientY - startY);
      container.style.left = c[0] + 'px';
      container.style.top = c[1] + 'px';
    }
    function onEnd() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onEnd);
    }
    header.addEventListener('mousedown', onStart);
  }

  /** 直连执行：同步图层 然后 调用后端工具，结果/错误都回到面板内 */
  function _invoke(root, tool, args) {
    _root = root;
    var panelId = root.id;
    var btn = _g('atRun');
    if (btn) btn.disabled = true;
    if (GIS.workspace) GIS.workspace.toolPending(panelId, btn);
    var layerNames = Object.keys(args || {})
      .filter(function (k) { return /layer/.test(k) && typeof args[k] === 'string' && args[k]; })
      .map(function (k) { return args[k]; });
    var syncP = (GIS.api && GIS.api.syncLayer)
      ? Promise.all(layerNames.map(function (n) { return GIS.api.syncLayer(n); }))
      : Promise.resolve();
    return syncP.then(function () {
      if (!(GIS.api && GIS.api.invokeTool)) throw new Error('GIS.api.invokeTool 不可用');
      return GIS.api.invokeTool(tool, args);
    }).then(function (result) {
      if (btn && !GIS.workspace) btn.disabled = false;
      if (GIS.workspace && !GIS.workspace.toolFeedback(panelId, result)) return;
      if (GIS.chat && GIS.chat.applyToolResult) GIS.chat.applyToolResult(result);
    }).catch(function (err) {
      if (btn && !GIS.workspace) btn.disabled = false;
      if (GIS.workspace) GIS.workspace.toolFeedback(panelId, null, err);
      else alert('执行失败: ' + err.message);
    });
  }

  function _run(root) {
    _root = root;
    var op = _opById(_g('atOp').value);
    if (!op) return;
    var args = {};
    Object.keys(op.args || {}).forEach(function (k) { args[k] = op.args[k]; });

    var lArgs = _opLayerArgs(op);
    var layerEls = ['atLayer', 'atLayer2', 'atLayer3'];
    for (var i = 0; i < lArgs.length; i++) {
      var val = _text(layerEls[i]);
      var optional = op.optionalLayers && op.optionalLayers.indexOf(lArgs[i]) >= 0;
      if (!val) {
        if (optional) continue;
        alert('请选择' + _opLayerHint(op, i));
        return;
      }
      args[lArgs[i]] = val;
    }

    var e = op.extra || '';
    if (e === 'reclassify') {
      var method = _g('atReclassMethod').value;
      args.method = method;
      if (method === 'mapping') {
        var mapping = _text('atMapping');
        if (!mapping) { alert('请输入重分类映射，如 0-10=1;10-50=2'); return; }
        args.mapping = mapping;
      } else {
        args.classes = Math.max(2, Math.round(_num('atClasses', 5)));
      }
    } else if (e === 'focal') {
      args.stat = _g('atFocalStat').value;
      args.size = Math.max(3, Math.round(_num('atFocalSize', 3)));
    } else if (e === 'sourceValue') {
      var sv = _text('atSourceValue');
      if (sv !== '') {
        args.source_value = Number(sv);
        if (!Number.isFinite(args.source_value)) { alert('源像元值必须是有限数值'); return; }
      }
    } else if (e === 'inside') {
      args.inside = _checked('atInside');
    } else if (e === 'reference') {
      var ref = _text('atReference');
      if (ref !== '') {
        var referenceValue = Number(ref);
        if (!Number.isFinite(referenceValue)) { alert('参考高程必须是有限数值'); return; }
        args.reference = referenceValue;
      }
      if (!args.after_layer && ref === '') {
        alert('请选择变化后 DEM，或输入参考高程');
        return;
      }
      if (!args.after_layer) args.after_layer = '';
    } else if (e === 'join') {
      var tf = _g('atField1').value;
      var jf = _g('atField2').value;
      if (!tf) { alert('请选择目标字段'); return; }
      if (!jf) { alert('请选择连接字段'); return; }
      args.target_field = tf;
      args.join_field = jf;
      var fields = _text('atJoinFields');
      if (fields) args.fields = fields;
      args.how = _g('atHow').value;
    } else if (e === 'metrics') {
      var metrics = _text('atMetrics');
      if (metrics) args.metrics = metrics;
    } else if (e === 'minGeom') {
      args.kind = _g('atKind').value;
      var mggf = _g('atField1').value;
      if (mggf) args.group_field = mggf;
    } else if (e === 'p2l') {
      var pgf = _g('atField1').value;
      if (!pgf) { alert('请选择分组字段'); return; }
      args.group_field = pgf;
      var of = _g('atField2').value;
      if (of) args.order_field = of;
      args.close_ring = _checked('atCloseRing');
    } else if (e === 'gpal') {
      args.interval = _num('atInterval', 100);
      args.unit = _g('atUnit').value;
    } else if (e === 'weights') {
      args.method = _g('atWeightsMethod').value;
      args.k = Math.max(1, Math.round(_num('atK', 8)));
    } else if (e === 'regression') {
      var dep = _g('atField1').value;
      var ind = _text('atIndependents');
      if (!dep) { alert('请选择因变量字段'); return; }
      if (!ind) { alert('请输入自变量字段，逗号分隔'); return; }
      args.dependent = dep;
      args.independents = ind;
    } else if (e === 'directional') {
      var dgf = _g('atField1').value;
      if (dgf) args.group_field = dgf;
    } else if (e === 'tendency') {
      var twf = _g('atField1').value;
      if (twf) args.weight_field = twf;
    } else if (e === 'od') {
      var ns = _g('atNetworkSource').value;
      if (ns) args.network_source = ns;
    } else if (e === 'f2r') {
      var vf = _g('atField1').value;
      if (vf) args.value_field = vf;
      args.cell_size = _num('atCellSize', 0);
      args.all_touched = _checked('atAllTouched');
    } else if (e === 'r2f') {
      args.connectivity = _int('atConnectivity', 8);
      args.simplify = _num('atSimplify', 0);
      var r2fField = _text('atR2FField');
      if (r2fField) args.field = r2fField;
    } else if (e === 'fishnet') {
      args.cell_size = _num('atCellSize', 0);
      args.rows = Math.round(_num('atRows', 0));
      args.cols = Math.round(_num('atCols', 0));
    }
    return _invoke(root, op.tool, args);
  }

  GIS.analysisTools = { toggle: toggle };
})();
