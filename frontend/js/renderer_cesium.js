/**
 * GIS AI WorkTable — Cesium 3D Globe 渲染适配器（P0）
 *
 * 职责（只做渲染，不做状态）：
 *  - 懒加载 CesiumJS（本地 vendor 优先，CDN 回退），零 Cesium Ion 依赖
 *  - 订阅 GIS.state：图层增删/显隐/可视化 → GeoJsonDataSource 同步
 *  - scene.pick 点击 → GIS.state.selectFeature(source:'3d')（反向同步 2D）
 *  - view-changed → camera.flyTo(Rectangle)
 *  - 2D/3D 互斥切换（同一地图区域，切换不销毁）
 *  - 面包屑 + 要素属性面板 UI（2D/3D 共用）
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  // ============================================================
  // Cesium 懒加载（本地 vendor → 国内 CDN → unpkg → 官方 CDN）
  // ============================================================

  const CESIUM_VERSION = '1.119';
  const CESIUM_SOURCES = [
    { base: 'vendor/cesium/', js: 'vendor/cesium/Cesium.js', css: 'vendor/cesium/Widgets/widgets.css' },
    { base: 'https://cdn.bootcdn.net/ajax/libs/cesium/' + CESIUM_VERSION + '/',
      js: 'https://cdn.bootcdn.net/ajax/libs/cesium/' + CESIUM_VERSION + '/Cesium.js',
      css: 'https://cdn.bootcdn.net/ajax/libs/cesium/' + CESIUM_VERSION + '/Widgets/widgets.css' },
    { base: 'https://unpkg.com/cesium@' + CESIUM_VERSION + '/Build/Cesium/',
      js: 'https://unpkg.com/cesium@' + CESIUM_VERSION + '/Build/Cesium/Cesium.js',
      css: 'https://unpkg.com/cesium@' + CESIUM_VERSION + '/Build/Cesium/Widgets/widgets.css' },
    { base: 'https://cesium.com/downloads/cesiumjs/releases/' + CESIUM_VERSION + '/Build/Cesium/',
      js: 'https://cesium.com/downloads/cesiumjs/releases/' + CESIUM_VERSION + '/Build/Cesium/Cesium.js',
      css: 'https://cesium.com/downloads/cesiumjs/releases/' + CESIUM_VERSION + '/Build/Cesium/Widgets/widgets.css' },
  ];

  function loadScript(url) {
    return new Promise(function(resolve, reject) {
      const s = document.createElement('script');
      s.src = url;
      s.onload = resolve;
      s.onerror = function() { reject(new Error('load fail: ' + url)); };
      document.head.appendChild(s);
    });
  }
  function loadCss(url) {
    if (document.querySelector('link[href="' + url + '"]')) return;
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = url;
    document.head.appendChild(l);
  }

  let cesiumReadyPromise = null;
  function ensureCesium() {
    if (window.Cesium) return Promise.resolve();
    if (cesiumReadyPromise) return cesiumReadyPromise;
    cesiumReadyPromise = (async function() {
      let lastErr = null;
      for (const src of CESIUM_SOURCES) {
        try {
          window.CESIUM_BASE_URL = src.base;
          loadCss(src.css);
          await loadScript(src.js);
          if (window.Cesium) return;
        } catch (e) { lastErr = e; }
      }
      throw lastErr || new Error('CesiumJS 所有源均加载失败');
    })();
    return cesiumReadyPromise;
  }

  // ============================================================
  // Viewer 初始化（零 Ion）
  // ============================================================

  let viewer = null;
  let container3d = null;
  const dsMap = {};          // layer_id -> GeoJsonDataSource
  let clickHandler = null;
  let basemap = 'satellite'; // 当前 3D 底图：satellite | street | dark

  const ESRI_IMAGERY = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  const ESRI_STREET = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}';

  /** 按需渲染：requestRenderMode 下实体属性/材质变更必须显式触发一帧 */
  function requestRender() {
    if (viewer && viewer.scene) viewer.scene.requestRender();
  }

  /** 飞到 bbox（drill/新图层/复位共用） */
  function flyToBbox(b, duration) {
    if (!viewer || !b) return;
    viewer.camera.flyTo({
      destination: Cesium.Rectangle.fromDegrees(
        Math.max(b[0], -179.9), Math.max(b[1], -89.9),
        Math.min(b[2], 179.9), Math.min(b[3], 89.9)),
      duration: duration || 1.5,
    });
  }

  function createViewer() {
    if (!container3d) return;
    viewer = new Cesium.Viewer(container3d, {
      baseLayer: new Cesium.ImageryLayer(new Cesium.UrlTemplateImageryProvider({
        url: ESRI_IMAGERY,
        credit: 'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics',
      })),
      // —— 零 Ion 依赖清单：以下默认值都指向 Ion，必须显式关掉 ——
      baseLayerPicker: false,
      geocoder: false,
      // terrainProvider 默认 EllipsoidTerrainProvider，无需设置
      homeButton: false, sceneModePicker: false, navigationHelpButton: false,
      animation: false, timeline: false, fullscreenButton: false,
      infoBox: false, selectionIndicator: false,
      // —— 流畅性：空闲时不渲染（省 GPU/电池），交互与飞行自动触发，实体变更走 requestRender ——
      requestRenderMode: true,
      maximumRenderTimeChange: Infinity,
    });
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#0b1020');

    // 点击选中 → 回写共享状态（3D → 2D 同步的入口）
    clickHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    clickHandler.setInputAction(function(movement) {
      const picked = viewer.scene.pick(movement.position);
      if (!Cesium.defined(picked) || !(picked.id instanceof Cesium.Entity)) {
        GIS.state.clearSelection();
        return;
      }
      const entity = picked.id;
      const props = entity.properties
        ? entity.properties.getValue(Cesium.JulianDate.now()) : {};
      const layerId = entity._gisLayerId;
      const fid = props._fid;
      const rec = GIS.state.getLayer(layerId);
      const idx = rec && rec.fidIndex[fid];
      // 重建一个轻量 Feature（几何不取，面板显示属性足够）
      GIS.state.selectFeature(layerId, {
        type: 'Feature', properties: props, geometry: null,
      }, '3d', idx);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
  }

  // ============================================================
  // 状态 → 3D 渲染同步
  // ============================================================

  function syncLayer(rec) {
    if (!viewer || !rec.geojson) return;
    const opScale = (rec.style && rec.style.opacity !== undefined) ? rec.style.opacity : 1;
    return Cesium.GeoJsonDataSource.load(rec.geojson, {
      stroke: Cesium.Color.fromCssColorString((rec.style && rec.style.color) || '#1c1b1b'),
      fill: Cesium.Color.fromCssColorString((rec.style && rec.style.fillColor) || (rec.style && rec.style.color) || '#1c1b1b')
        .withAlpha(((rec.style && rec.style.fillOpacity !== undefined) ? rec.style.fillOpacity : 0.35) * opScale),
      strokeWidth: (rec.style && rec.style.weight) || 2,
      clampToGround: false,
    }).then(function(ds) {
      ds.name = rec.name;
      ds.show = rec.visible !== false;
      ds._gisLayerId = rec.layer_id;
      ds.entities.values.forEach(function(e) {
        e._gisLayerId = rec.layer_id;
        // outline 在部分 GPU 上不可靠；面要素用填充色即可辨识
        if (e.polygon) e.polygon.outline = false;
        // 点要素按线宽放大像素点，默认过小不易点选
        if (e.point) e.point.pixelSize = ((rec.style && rec.style.weight) || 2) * 4;
      });
      viewer.dataSources.add(ds);
      dsMap[rec.layer_id] = ds;
      // 重放该图层已有的颜色/可视化配置（清除 viz 后的重载也走这里）
      if (rec.featureColors) applyFeatureColors(ds, rec);
      if (rec.viz) applyViz(ds, rec.viz, rec);
      requestRender();
    }).catch(function(e) {
      console.error('[GIS 3D] 图层加载失败:', rec.name, e);
    });
  }

  function desyncLayer(layerId) {
    const ds = dsMap[layerId];
    if (ds && viewer) { viewer.dataSources.remove(ds, true); requestRender(); }
    delete dsMap[layerId];
  }

  function applyViz(ds, viz, rec) {
    if (!viewer || !ds) return;
    if (!viz) return;
    const field = viz.field;
    let min = Infinity, max = -Infinity;
    ds.entities.values.forEach(function(e) {
      const v = e.properties && e.properties[field]
        ? e.properties[field].getValue(Cesium.JulianDate.now()) : null;
      if (typeof v === 'number' && isFinite(v)) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
    });
    if (!isFinite(min)) { console.warn('[GIS 3D] 字段无数值:', field); return; }
    const lo = Cesium.Color.fromCssColorString((viz.ramp && viz.ramp[0]) || '#c6dbef');
    const hi = Cesium.Color.fromCssColorString((viz.ramp && viz.ramp[1]) || '#08306b');
    const hMin = viz.minHeight || 0, hMax = viz.maxHeight || 150000;
    ds.entities.values.forEach(function(e) {
      const raw = e.properties && e.properties[field]
        ? e.properties[field].getValue(Cesium.JulianDate.now()) : null;
      if (typeof raw !== 'number' || !isFinite(raw)) return;
      const t = (max - min) ? (raw - min) / (max - min) : 0;
      const color = Cesium.Color.lerp(lo, hi, t, new Cesium.Color());
      if (e.polygon) {
        if (viz.type === 'extrusion') {
          e.polygon.extrudedHeight = hMin + t * (hMax - hMin);
          e.polygon.height = 0;
        }
        e.polygon.material = color.withAlpha(0.85);
      }
    });
    requestRender();
  }

  /** 3D 透明度同步：按基色缩放 alpha，反复调整不累积 */
  function applyOpacity(ds, opacity) {
    if (!viewer || !ds) return;
    ds.entities.values.forEach(function(e) {
      if (e.polygon && e.polygon.material && e.polygon.material.color) {
        const c = e._basePolyColor ||
          (e._basePolyColor = e.polygon.material.color.getValue(Cesium.JulianDate.now()).clone());
        e.polygon.material = new Cesium.ColorMaterialProperty(c.withAlpha(c.alpha * opacity));
      }
      if (e.polyline && e.polyline.material && e.polyline.material.color) {
        const c2 = e._baseLineColor ||
          (e._baseLineColor = e.polyline.material.color.getValue(Cesium.JulianDate.now()).clone());
        e.polyline.material = new Cesium.ColorMaterialProperty(c2.withAlpha(c2.alpha * opacity));
      }
      if (e.point && e.point.color) {
        const c3 = e._basePointColor ||
          (e._basePointColor = e.point.color.getValue(Cesium.JulianDate.now()).clone());
        e.point.color = c3.withAlpha(c3.alpha * opacity);
      }
    });
    requestRender();
  }

  /** 按要素设色（2D 符号化 → 3D 同步）：fid → 颜色 */
  function applyFeatureColors(ds, rec) {
    if (!viewer || !ds || !rec.featureColors) return;
    const now = Cesium.JulianDate.now();
    const opScale = (rec.style && rec.style.opacity !== undefined) ? rec.style.opacity : 1;
    ds.entities.values.forEach(function(e) {
      const fid = e.properties && e.properties._fid
        ? e.properties._fid.getValue(now) : null;
      const hex = fid ? rec.featureColors[fid] : null;
      if (!hex) return;
      const color = Cesium.Color.fromCssColorString(hex);
      if (e.polygon) e.polygon.material = color.withAlpha(0.85 * opScale);
      if (e.polyline) e.polyline.material = new Cesium.ColorMaterialProperty(color);
      if (e.point) e.point.color = color;
    });
    requestRender();
  }

  // ============================================================
  // 选中高亮（fid 匹配，与 2D 共用状态）
  // ============================================================

  let highlighted = null;
  function highlightEntity(ds, fid) {
    clearHighlight();
    if (!ds) return;
    const entities = ds.entities.values;
    for (let i = 0; i < entities.length; i++) {
      const e = entities[i];
      const p = e.properties && e.properties._fid
        ? e.properties._fid.getValue(Cesium.JulianDate.now()) : null;
      if (p === fid) {
        if (e.polygon) {
          e._origMaterial = e.polygon.material;
          e.polygon.material = Cesium.Color.RED.withAlpha(0.5);
        }
        if (e.polyline) {
          e._origLineMaterial = e.polyline.material;
          e.polyline.material = Cesium.Color.RED.withAlpha(1);
        }
        if (e.point) {
          e._origPointColor = e.point.color;
          e._origPointSize = e.point.pixelSize;
          e.point.color = Cesium.Color.RED;
          e.point.pixelSize = 12;
        }
        highlighted = e;
        viewer.selectedEntity = e;   // 触发 Cesium 内置定位/信息行为（infoBox 已关）
        requestRender();
        return;
      }
    }
  }
  function clearHighlight() {
    if (highlighted) {
      if (highlighted.polygon && highlighted._origMaterial) {
        highlighted.polygon.material = highlighted._origMaterial;
        highlighted._origMaterial = null;
      }
      if (highlighted.polyline && highlighted._origLineMaterial) {
        highlighted.polyline.material = highlighted._origLineMaterial;
        highlighted._origLineMaterial = null;
      }
      if (highlighted.point && highlighted._origPointColor) {
        highlighted.point.color = highlighted._origPointColor;
        highlighted.point.pixelSize = highlighted._origPointSize;
        highlighted._origPointColor = null;
        highlighted._origPointSize = null;
      }
    }
    if (viewer) viewer.selectedEntity = undefined;
    highlighted = null;
    requestRender();
  }

  // ============================================================
  // UI：2D/3D 切换按钮 + 面包屑 + 属性面板
  // ============================================================

  let mode = '2d';   // '2d' | '3d'

  function ensureUI() {
    // 3D 容器（与 #map 同级、同尺寸）
    if (!document.getElementById('map3d')) {
      const mapEl = document.getElementById('map');
      container3d = document.createElement('div');
      container3d.id = 'map3d';
      container3d.style.cssText =
        'position:absolute;inset:0;display:none;z-index:400;background:#0b1020;';
      if (mapEl && mapEl.parentNode) mapEl.parentNode.insertBefore(container3d, mapEl);
      else document.body.appendChild(container3d);
    }
    // 切换按钮 + 3D 专属按钮（挂在缩放/绘制快捷栏，与 2D 同一套样式）
    const toolbar = document.getElementById('mapZoomControls');
    if (toolbar && !document.getElementById('toggle3dBtn')) {
      const btn = document.createElement('button');
      btn.id = 'toggle3dBtn';
      btn.className = 'map-zoom-btn m3d-keep';
      btn.title = '切换 2D / 3D Globe';
      btn.innerHTML = '<span style="font-size:11px;font-weight:700;">3D</span>';
      btn.addEventListener('click', function() {
        toggle3D().catch(function(e) {
          if (GIS.chat && GIS.chat.addMessage) {
            GIS.chat.addMessage('3D 模式启动失败：' + (e.message || e), 'system');
          }
        });
      });
      toolbar.insertBefore(btn, toolbar.firstChild);

      // 3D 专属按钮组：仅 3D 模式显示（CSS 控制），复用 .map-zoom-btn 样式
      const frag = document.createDocumentFragment();
      const mkBtn = function(id, label, title, onclick) {
        const b = document.createElement('button');
        b.id = id;
        b.className = 'map-zoom-btn m3d-3dbtn m3d-keep';
        b.title = title;
        b.innerHTML = '<span style="font-size:11px;font-weight:600;">' + label + '</span>';
        b.addEventListener('click', onclick);
        return b;
      };
      frag.appendChild(mkBtn('m3dBmSat', '影像', 'Esri 影像底图', function() { setBasemap('satellite'); }));
      frag.appendChild(mkBtn('m3dBmStreet', '街道', 'Esri 街道底图', function() { setBasemap('street'); }));
      frag.appendChild(mkBtn('m3dBmDark', '深色', '深色球体（无底图）', function() { setBasemap('dark'); }));
      const divider = document.createElement('div');
      divider.className = 'map-ctrl-divider m3d-3dbtn m3d-keep';
      frag.appendChild(divider);
      frag.appendChild(mkBtn('m3dReset', '复位', '复位到当前下钻层级范围', function() { resetView(); }));
      toolbar.insertBefore(frag, btn.nextSibling);

      // 视图书签按钮（2D/3D 常驻，位于 3D/2D 切换之后）
      if (!document.getElementById('bmBtn')) {
        const bb = document.createElement('button');
        bb.id = 'bmBtn';
        bb.className = 'map-zoom-btn m3d-keep';
        bb.title = '视图书签（保存/回到常用视角）';
        bb.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
        bb.addEventListener('click', function(e) { e.stopPropagation(); toggleBmPanel(); });
        toolbar.insertBefore(bb, btn.nextSibling);
      }
    }
    // 面包屑
    if (!document.getElementById('drillBreadcrumb')) {
      const crumb = document.createElement('div');
      crumb.id = 'drillBreadcrumb';
      crumb.title = '行政区下钻导航：显示当前所在的层级，点击任意层级可跳回；下钻结束后可点击 ✕ 收起';
      crumb.style.cssText = 'position:absolute;top:46px;left:50%;transform:translateX(-50%);' +
        'z-index:500;display:none;align-items:center;gap:6px;padding:4px 10px;' +
        'background:rgba(15,18,25,0.82);border:1px solid rgba(255,255,255,0.12);' +
        'border-radius:0;font-size:12px;color:#e8e8e8;backdrop-filter:blur(6px);';
      const mapEl = document.getElementById('map');
      if (mapEl && mapEl.parentNode) mapEl.parentNode.insertBefore(crumb, mapEl);
    }
    // 属性面板
    if (!document.getElementById('featurePanel')) {
      const panel = document.createElement('div');
      panel.id = 'featurePanel';
      panel.style.cssText = 'position:absolute;top:52px;right:68px;z-index:500;display:none;' +
        'width:260px;max-height:55%;overflow:auto;padding:10px 12px;' +
        'background:rgba(15,18,25,0.88);border:1px solid rgba(255,255,255,0.12);' +
        'border-radius:0;color:#e8e8e8;font-size:12px;backdrop-filter:blur(6px);';
      const mapEl = document.getElementById('map');
      if (mapEl && mapEl.parentNode) mapEl.parentNode.insertBefore(panel, mapEl);
    }
  }

  function renderBreadcrumb() {
    const crumb = document.getElementById('drillBreadcrumb');
    if (!crumb) return;
    const stack = GIS.state.getDrillStack();
    if (!stack.length) {
      crumb.style.display = 'flex';
      crumb.innerHTML = '<span id="crumbInit" style="cursor:pointer;opacity:0.85;">🌐 加载全国省级行政区</span>';
      const initBtn = document.getElementById('crumbInit');
      if (initBtn) initBtn.addEventListener('click', function() {
        GIS.state.initCountryLevel().catch(function(e) {
          if (GIS.chat && GIS.chat.addMessage) {
            GIS.chat.addMessage('加载全国省界失败：' + (e.message || e), 'system');
          }
        });
      });
      return;
    }
    crumb.style.display = 'flex';
    let html = '<span style="opacity:0.55;font-size:11px;">下钻层级</span>' +
      '<span style="opacity:0.3;">|</span>' +
      '<span style="cursor:pointer;opacity:0.9;" data-depth="-1">🌐 全国</span>';
    stack.forEach(function(s, i) {
      html += '<span style="opacity:0.4;">›</span>' +
        '<span style="cursor:pointer;" data-depth="' + i + '">' + escapeHtml(s.name) + '</span>';
    });
    html += '<span id="crumbClose" title="收起导航条（不影响当前图层）" ' +
      'style="cursor:pointer;opacity:0.5;margin-left:4px;font-size:12px;">✕</span>';
    crumb.innerHTML = html;
    const closeBtn = document.getElementById('crumbClose');
    if (closeBtn) closeBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      crumb.style.display = 'none';
    });
    crumb.querySelectorAll('[data-depth]').forEach(function(el) {
      el.addEventListener('click', function() {
        const depth = parseInt(el.dataset.depth, 10);
        if (depth < 0) { GIS.state.drillUpTo(-1); }   // 清空栈
        else GIS.state.drillUpTo(depth);
      });
    });
  }

  function renderFeaturePanel() {
    const panel = document.getElementById('featurePanel');
    if (!panel) return;
    const sel = GIS.state.getSelection();
    if (!sel || !sel.props) { panel.style.display = 'none'; return; }
    let html = '<div style="font-weight:700;margin-bottom:6px;">' + escapeHtml(String(sel.name)) + '</div>';
    const keys = Object.keys(sel.props).filter(function(k) { return k !== '_fid'; }).slice(0, 12);
    if (keys.length) {
      html += '<table style="width:100%;border-collapse:collapse;">';
      keys.forEach(function(k) {
        const v = sel.props[k];
        html += '<tr><td style="opacity:0.6;padding:2px 4px;">' + escapeHtml(k) +
          '</td><td style="padding:2px 4px;text-align:right;">' +
          escapeHtml(v === null || v === undefined ? '' : String(v)) + '</td></tr>';
      });
      html += '</table>';
    }
    if (sel.adcode !== null && sel.adcode !== undefined) {
      html += '<button id="fpDrillBtn" style="margin-top:8px;width:100%;padding:5px 0;' +
        'background:#2563eb;color:#fff;border:none;border-radius:0;cursor:pointer;font-size:12px;">' +
        '下钻到下一级政区</button>';
    }
    panel.innerHTML = html;
    panel.style.display = 'block';
    const drillBtn = document.getElementById('fpDrillBtn');
    if (drillBtn) {
      drillBtn.addEventListener('click', function() {
        GIS.state.drillDown(sel.adcode, sel.name).catch(function(e) {
          if (GIS.chat && GIS.chat.addMessage) {
            GIS.chat.addMessage('下钻失败：' + (e.message || e), 'system');
          }
        });
      });
    }
  }

  function escapeHtml(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ============================================================
  // 3D 手动控制条：底图切换 + 复位视角（不依赖 Agent，GeoLibre 式常驻按钮）
  // ============================================================

  function setBasemap(key) {
    if (!viewer) return;
    basemap = key;
    viewer.imageryLayers.removeAll(true);
    if (key === 'satellite' || key === 'street') {
      viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
        url: key === 'street' ? ESRI_STREET : ESRI_IMAGERY,
        credit: 'Tiles © Esri',
      }));
    }
    // dark：无底图，显示球体基色
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#0b1020');
    const bmIds = { satellite: 'm3dBmSat', street: 'm3dBmStreet', dark: 'm3dBmDark' };
    Object.keys(bmIds).forEach(function(k) {
      const el = document.getElementById(bmIds[k]);
      if (el) el.classList.toggle('active', k === key);
    });
    requestRender();
  }

  function resetView() {
    if (!viewer) return;
    // 优先飞到当前下钻层级图层范围，否则回到全国视角
    let bbox = null;
    const stack = GIS.state.getDrillStack();
    for (let i = stack.length - 1; i >= 0 && !bbox; i--) {
      const rec = GIS.state.getLayer(stack[i].layerId);
      if (rec && rec.bbox) bbox = rec.bbox;
    }
    if (bbox) {
      flyToBbox(bbox, 1.2);
    } else {
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(105, 36, 14000000),
        duration: 1.2,
      });
    }
  }

  // ============================================================
  // 视图书签（2D/3D 共用，localStorage 持久化；跨模式自动切换后应用）
  // ============================================================

  const BM_KEY = 'gis_view_bookmarks';
  function loadBookmarks() {
    try { return JSON.parse(localStorage.getItem(BM_KEY)) || []; } catch (e) { return []; }
  }
  function saveBookmarks(list) {
    try { localStorage.setItem(BM_KEY, JSON.stringify(list)); } catch (e) {}
  }

  /** 捕获当前模式下的相机/视图状态 */
  function captureView() {
    if (mode === '3d' && viewer) {
      const cam = viewer.camera.positionCartographic;
      return {
        mode: '3d',
        lon: Cesium.Math.toDegrees(cam.longitude),
        lat: Cesium.Math.toDegrees(cam.latitude),
        height: cam.height,
        heading: Cesium.Math.toDegrees(viewer.camera.heading),
        pitch: Cesium.Math.toDegrees(viewer.camera.pitch),
        roll: Cesium.Math.toDegrees(viewer.camera.roll),
      };
    }
    const m = GIS.map && GIS.map.getInstance ? GIS.map.getInstance() : null;
    if (!m) return null;
    const c = m.getCenter();
    return { mode: '2d', lat: c.lat, lng: c.lng, zoom: m.getZoom() };
  }

  /** 应用书签；模式不匹配时先切换再应用 */
  function applyBookmark(bm) {
    const go = function() {
      if (bm.mode === '3d') {
        if (!viewer) return;
        viewer.camera.setView({
          destination: Cesium.Cartesian3.fromDegrees(bm.lon, bm.lat, Math.max(bm.height, 100)),
          orientation: {
            heading: Cesium.Math.toRadians(bm.heading || 0),
            pitch: Cesium.Math.toRadians(bm.pitch !== undefined ? bm.pitch : -90),
            roll: Cesium.Math.toRadians(bm.roll || 0),
          },
        });
        requestRender();
      } else if (GIS.map && GIS.map.getInstance) {
        const m = GIS.map.getInstance();
        if (m) m.setView([bm.lat, bm.lng], bm.zoom || 4);
      }
    };
    const need3d = bm.mode === '3d';
    if (need3d && mode !== '3d') {
      toggle3D().then(go).catch(function(e) {
        if (GIS.chat && GIS.chat.addMessage) GIS.chat.addMessage('切换 3D 失败：' + (e.message || e), 'system');
      });
    } else if (!need3d && mode !== '2d') {
      toggle3D().then(go);
    } else {
      go();
    }
  }

  function toggleBmPanel() {
    let panel = document.getElementById('bmPanel');
    if (!panel) panel = createBmPanel();
    const show = panel.style.display !== 'block';
    panel.style.display = show ? 'block' : 'none';
    if (show) renderBmList();
  }

  function createBmPanel() {
    const panel = document.createElement('div');
    panel.id = 'bmPanel';
    panel.style.cssText = 'position:absolute;top:46px;right:64px;z-index:520;display:none;width:200px;' +
      'background:var(--ui-white,#fff);border:1px solid var(--ui-gray-200,#ddd);border-radius:8px;' +
      'box-shadow:0 4px 16px rgba(0,0,0,0.15);padding:8px;font-size:12px;color:var(--ui-gray-900,#1c1b1b);';
    panel.innerHTML =
      '<div style="font-weight:700;margin-bottom:6px;">视图书签</div>' +
      '<div id="bmList" style="max-height:200px;overflow:auto;margin-bottom:6px;"></div>' +
      '<div style="display:flex;gap:4px;">' +
        '<input id="bmName" placeholder="书签名称" style="flex:1;min-width:0;padding:3px 6px;border:1px solid var(--ui-gray-200,#ddd);border-radius:4px;font-size:12px;background:#fff;color:inherit;" />' +
        '<button id="bmSave" style="padding:3px 8px;background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer;">保存</button>' +
      '</div>';
    const mapEl = document.getElementById('map');
    if (mapEl && mapEl.parentNode) mapEl.parentNode.insertBefore(panel, mapEl);
    document.getElementById('bmSave').addEventListener('click', function() {
      const input = document.getElementById('bmName');
      const name = (input.value || '').trim();
      if (!name) { input.focus(); return; }
      const bm = captureView();
      if (!bm) return;
      bm.name = name;
      const list = loadBookmarks();
      const i = list.findIndex(function(x) { return x.name === name; });
      if (i >= 0) list[i] = bm; else list.push(bm);
      saveBookmarks(list);
      input.value = '';
      renderBmList();
    });
    // 点击面板外部关闭
    setTimeout(function() {
      document.addEventListener('click', function onDocClick(e) {
        const p = document.getElementById('bmPanel');
        if (!p || p.style.display !== 'block') return;
        if (e.target.closest('#bmPanel') || e.target.closest('#bmBtn')) return;
        p.style.display = 'none';
      });
    }, 0);
    return panel;
  }

  function renderBmList() {
    const el = document.getElementById('bmList');
    if (!el) return;
    const list = loadBookmarks();
    if (!list.length) {
      el.innerHTML = '<div style="color:var(--ui-gray-400,#999);padding:4px 0;">暂无书签，移动到合适视角后保存</div>';
      return;
    }
    el.innerHTML = list.map(function(b, i) {
      return '<div class="bm-row" data-i="' + i + '" style="display:flex;align-items:center;gap:4px;padding:3px 4px;border-radius:4px;cursor:pointer;">' +
        '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(b.name) + '</span>' +
        '<span style="opacity:0.5;font-size:10px;">' + (b.mode === '3d' ? '3D' : '2D') + '</span>' +
        '<span class="bm-del" data-i="' + i + '" style="color:var(--ui-gray-400,#999);padding:0 3px;">×</span></div>';
    }).join('');
    el.querySelectorAll('.bm-row').forEach(function(row) {
      row.addEventListener('click', function(ev) {
        if (ev.target.classList.contains('bm-del')) {
          const l = loadBookmarks();
          l.splice(parseInt(ev.target.dataset.i, 10), 1);
          saveBookmarks(l);
          renderBmList();
          return;
        }
        const bm = loadBookmarks()[parseInt(row.dataset.i, 10)];
        if (bm) { applyBookmark(bm); const p = document.getElementById('bmPanel'); if (p) p.style.display = 'none'; }
      });
    });
  }

  // ============================================================
  // 2D/3D 切换（互斥挂载，不销毁）
  // ============================================================

  async function toggle3D() {
    ensureUI();
    if (mode === '2d') {
      // 卷帘对比仅 2D 支持：切 3D 前自动关闭，避免残留分割线与死 pane
      if (window.GIS && GIS.map && typeof GIS.map.stopSwipe === 'function' &&
          typeof GIS.map.isSwipeActive === 'function' && GIS.map.isSwipeActive()) {
        GIS.map.stopSwipe();
      }
      await ensureCesium();
      if (!viewer) createViewer();
      const mapEl = document.getElementById('map');
      if (mapEl) mapEl.style.display = 'none';
      container3d.style.display = 'block';
      mode = '3d';
      // 容器从 display:none 变为可见，Cesium 不会自动感知，必须显式重算画布尺寸
      if (viewer.resize) viewer.resize();
      // 控件栏：置顶于 3D 画布之上，隐藏 2D 专属按钮（CSS mode-3d 规则）
      const toolbar3d = document.getElementById('mapZoomControls');
      if (toolbar3d) {
        toolbar3d.classList.add('mode-3d');
        ['m3dBmSat', 'm3dBmStreet', 'm3dBmDark'].forEach(function(id) {
          const el = document.getElementById(id);
          if (el) el.classList.toggle('active',
            (id === 'm3dBmSat' && basemap === 'satellite') ||
            (id === 'm3dBmStreet' && basemap === 'street') ||
            (id === 'm3dBmDark' && basemap === 'dark'));
        });
      }
      // 把现有图层同步进 3D（只取含 GeoJSON 的）
      GIS.state.getLayers().forEach(function(rec) {
        if (!dsMap[rec.layer_id]) syncLayer(rec);
      });
      requestRender();
    } else {
      container3d.style.display = 'none';
      const toolbar2d = document.getElementById('mapZoomControls');
      if (toolbar2d) toolbar2d.classList.remove('mode-3d');
      const mapEl = document.getElementById('map');
      if (mapEl) { mapEl.style.display = ''; if (GIS.map && GIS.map.invalidateSize) GIS.map.invalidateSize(); }
      mode = '2d';
    }
    const btn = document.getElementById('toggle3dBtn');
    if (btn) btn.querySelector('span').textContent = mode === '2d' ? '3D' : '2D';
    // body 级 3D 标记：CSS 据此隐藏 2D 专属元素（如坐标显示）
    document.body.classList.toggle('gis-mode-3d', mode === '3d');
  }

  // ============================================================
  // 订阅共享状态
  // ============================================================

  function bindState() {
    GIS.state.on('layer-added', function(rec) {
      if (mode !== '3d') return;
      // 新图层装载后自动飞到其范围（与 2D loadGeoJSON 自动 fitBounds 行为对齐）
      Promise.resolve(syncLayer(rec)).then(function() {
        if (rec.visible !== false) flyToBbox(rec.bbox, 1.5);
      }).catch(function() {});
    });
    GIS.state.on('layer-removed', function(p) { desyncLayer(p.layerId); });
    GIS.state.on('layer-visible', function(rec) {
      const ds = dsMap[rec.layer_id];
      if (ds) { ds.show = rec.visible; requestRender(); }
    });
    GIS.state.on('layer-style', function(rec) {
      const ds = dsMap[rec.layer_id];
      if (ds && rec.style && rec.style.opacity !== undefined) {
        applyOpacity(ds, rec.style.opacity);
      }
    });
    GIS.state.on('feature-style', function(rec) {
      const ds = dsMap[rec.layer_id];
      if (!ds) return;
      if (!rec.featureColors) {
        // 清除符号化颜色：重载基础样式（重放 viz）
        desyncLayer(rec.layer_id);
        if (rec.geojson) syncLayer(rec);
        return;
      }
      applyFeatureColors(ds, rec);
    });
    GIS.state.on('viz', function(p) {
      const id = p.layer.layer_id;
      if (!p.viz) {
        // 清除可视化：重载基础样式
        desyncLayer(id);
        if (mode === '3d' && p.layer.geojson) syncLayer(p.layer);
        return;
      }
      applyViz(dsMap[id], p.viz, p.layer);
    });
    GIS.state.on('selection-changed', function(p) {
      renderFeaturePanel();
      if (mode !== '3d' || !viewer) return;
      const sel = p.selection;
      if (!sel) { clearHighlight(); return; }
      // 来自 3D 自身的点击无需再高亮（已由 pick 处理视觉）；来自 2D/面板/Agent 才同步
      if (sel.source !== '3d') highlightEntity(dsMap[sel.layerId], sel.fid);
    });
    GIS.state.on('view-changed', function(p) {
      if (mode !== '3d' || !p.bbox) return;
      flyToBbox(p.bbox, 1.5);
    });
    GIS.state.on('drill-changed', function() { renderBreadcrumb(); });
  }

  // ============================================================
  // 启动（等 DOM 与 Leaflet 就绪）
  // ============================================================

  function boot() {
    if (!GIS.state) { setTimeout(boot, 100); return; }
    ensureUI();
    bindState();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  GIS.renderers = {
    toggle3D: toggle3D,
    is3D: function() { return mode === '3d'; },
    getViewer: function() { return viewer; },
    flyToBbox: flyToBbox,
  };
})();
