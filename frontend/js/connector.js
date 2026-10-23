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
  var _activeFetchJob = '';
  var _fetchPollTimer = null;
  var _lastArcgisRecipe = null;

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

    // 在线云原生数据加载（粘贴 URL）
    var loadBtn = document.getElementById('onlineLoadBtn');
    if (loadBtn) loadBtn.addEventListener('click', loadOnline);
    var typeSelect = document.getElementById('onlineType');
    if (typeSelect) typeSelect.addEventListener('change', syncOnlineType);
    var inspectBtn = document.getElementById('arcgisInspectBtn');
    if (inspectBtn) inspectBtn.addEventListener('click', inspectArcgis);
    var cancelBtn = document.getElementById('arcgisCancelBtn');
    if (cancelBtn) cancelBtn.addEventListener('click', cancelArcgisFetch);
    var rerunBtn = document.getElementById('arcgisRerunBtn');
    if (rerunBtn) rerunBtn.addEventListener('click', function () {
      if (_lastArcgisRecipe) {
        openArcgis(_lastArcgisRecipe);
        startArcgisFetch(_lastArcgisRecipe);
      }
    });
    try { _lastArcgisRecipe = JSON.parse(localStorage.getItem('gis_last_arcgis_fetch_recipe') || 'null'); } catch (e) {}
    syncOnlineType();
    var urlInput = document.getElementById('onlineUrl');
    if (urlInput) {
      urlInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') loadOnline();
      });
    }
    // 设置页「地理服务」里的快捷入口 → 打开浮层面板
    var openOnlineBtn = document.getElementById('openOnlineDataBtn');
    if (openOnlineBtn) {
      openOnlineBtn.addEventListener('click', function (event) {
        event.stopPropagation();
        hide();   // 先收起设置面板浮层下的面板
        var modal = document.getElementById('settingsModal');
        if (modal) modal.style.display = 'none';
        show();
      });
    }

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

  function show() {
    if (!_panel) return;
    render();
    _panel.style.display = 'block';
  }

  function openArcgis(options) {
    options = options || {};
    var openOnlineBtn = document.getElementById('openOnlineDataBtn');
    if (openOnlineBtn && typeof openOnlineBtn.click === 'function') openOnlineBtn.click();
    else show();

    var typeSelect = document.getElementById('onlineType');
    if (typeSelect) typeSelect.value = 'arcgis-rest';
    syncOnlineType();

    var fields = {
      url: 'onlineUrl', layer_id: 'arcgisLayerId', mode: 'arcgisFetchMode',
      where: 'arcgisWhere', bbox: 'arcgisBbox'
    };
    Object.keys(fields).forEach(function (key) {
      if (!Object.prototype.hasOwnProperty.call(options, key)) return;
      var field = document.getElementById(fields[key]);
      if (field) field.value = options[key];
    });

    var urlInput = document.getElementById('onlineUrl');
    if (urlInput && typeof urlInput.focus === 'function') urlInput.focus();
    if (options.selectUrl && urlInput && typeof urlInput.select === 'function') urlInput.select();
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

  // ===== 在线云原生数据加载（COG / PMTiles / GeoParquet / FlatGeobuf） =====
  function loadOnline() {
    var typeEl = document.getElementById('onlineType');
    var urlEl = document.getElementById('onlineUrl');
    var btn = document.getElementById('onlineLoadBtn');
    if (!urlEl || !btn || btn.disabled) return;
    var source = (urlEl.value || '').trim();
    if (!source) {
      alert('请先粘贴数据 URL 或本地路径');
      return;
    }
    var type = typeEl ? typeEl.value : 'auto';
    if (type === 'arcgis-rest') {
      startArcgisFetch(readArcgisRecipe());
      return;
    }
    btn.disabled = true;
    var oldText = btn.textContent;
    btn.textContent = '加载中...';
    fetch((window.GIS && GIS.api && GIS.api.BASE_URL ? GIS.api.BASE_URL : '') + '/api/online/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: source, type: type }),
    })
      .then(function (r) {
        return r.json().then(function (result) {
          if (!r.ok) {
            throw new Error((result && (result.detail || result.error || result.message)) || r.statusText || ('HTTP ' + r.status));
          }
          return result;
        });
      })
      .then(function (result) {
        btn.disabled = false;
        btn.textContent = oldText;
        if (result.error) {
          alert('加载失败: ' + result.error);
          return;
        }
        if (!result || (!result.raster_info && !result.geojson)) {
          alert('加载失败: 服务未返回可加载的图层数据');
          return;
        }
        applyOnlineResult(result);
        urlEl.value = '';
        hide();
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = oldText;
        alert('加载失败: ' + err.message);
      });
  }

  function syncOnlineType() {
    var typeEl = document.getElementById('onlineType');
    var isArcgis = !!typeEl && typeEl.value === 'arcgis-rest';
    document.querySelectorAll('.arcgis-fetch-only').forEach(function (el) {
      el.style.display = isArcgis ? '' : 'none';
    });
    var hint = document.querySelector('#connectorOnline > .connector-online-hint:not(.arcgis-fetch-only)');
    var urlInput = document.getElementById('onlineUrl');
    if (urlInput) urlInput.placeholder = isArcgis
      ? '粘贴 ArcGIS REST FeatureServer / MapServer 地址'
      : '粘贴数据 URL（http/https）或本地路径';
    if (hint) hint.textContent = isArcgis
      ? '预览最多 1,000 条，不核验完整性；完整获取仅核对对象 ID。范围格式：minx,miny,maxx,maxy（WGS84）。'
      : '支持 COG(.tif)、PMTiles(.pmtiles)、GeoParquet(.parquet)、FlatGeobuf(.fgb)，流式加载不整体下载';
    var load = document.getElementById('onlineLoadBtn');
    if (load && !load.disabled) load.textContent = isArcgis ? '获取' : '加载';
    var rerun = document.getElementById('arcgisRerunBtn');
    if (rerun) rerun.style.display = isArcgis && _lastArcgisRecipe ? '' : 'none';
  }

  function readArcgisRecipe() {
    return {
      url: (document.getElementById('onlineUrl').value || '').trim(),
      layer_id: (document.getElementById('arcgisLayerId').value || '').trim(),
      mode: document.getElementById('arcgisFetchMode').value || 'preview',
      where: (document.getElementById('arcgisWhere').value || '1=1').trim() || '1=1',
      bbox: (document.getElementById('arcgisBbox').value || '').trim(),
      limit: 1000,
      max_features: 100000,
      output_format: 'geojson'
    };
  }

  function apiUrl(path) {
    return (window.GIS && GIS.api && GIS.api.BASE_URL ? GIS.api.BASE_URL : '') + path;
  }

  function sanitizeArcgisUrl(value) {
    try {
      var parsed = new URL(value, window.location.href);
      ['token', 'key', 'password', 'secret', 'auth', 'credential', 'signature'].forEach(function (sensitive) {
        Array.from(parsed.searchParams.keys()).forEach(function (key) {
          if (key.toLowerCase().indexOf(sensitive) >= 0) parsed.searchParams.delete(key);
        });
      });
      return parsed.toString();
    } catch (e) { return value; }
  }

  function setArcgisStatus(message) {
    var status = document.getElementById('arcgisFetchStatus');
    if (status) { status.textContent = message || ''; status.style.display = message ? '' : 'none'; }
  }

  function appendArcgisText(parent, tagName, className, message) {
    var element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = message;
    parent.appendChild(element);
    return element;
  }

  function setArcgisInspection(info) {
    var status = document.getElementById('arcgisFetchStatus');
    if (!status) return;
    status.textContent = '';
    status.style.display = '';

    var layer = info.layer_name ? info : null;
    appendArcgisText(status, 'strong', 'arcgis-inspection-title', layer ? '图层检查完成' : '服务检查完成');

    if (layer) {
      appendArcgisText(status, 'div', 'arcgis-inspection-summary',
        (layer.layer_name || 'ArcGIS 图层') + ' · 图层 ID ' + (layer.layer_id === undefined ? '未知' : layer.layer_id) +
        ' · ' + (layer.geometry_type || '几何类型未知') + ' · ' + (layer.crs || 'CRS 未知'));
      appendArcgisText(status, 'div', 'arcgis-inspection-summary',
        '对象 ID：' + (layer.object_id_field || '未知') +
        ' · 单次返回上限：' + (layer.max_record_count || '未知') +
        ' · 分页：' + (layer.supports_pagination === true ? '支持' : layer.supports_pagination === false ? '不支持' : '未知'));

      var fields = Array.isArray(layer.fields) ? layer.fields : [];
      if (fields.length) {
        var details = document.createElement('details');
        details.className = 'arcgis-inspection-fields';
        var summary = document.createElement('summary');
        summary.textContent = '查看全部 ' + fields.length + ' 个字段';
        details.appendChild(summary);
        var list = document.createElement('ul');
        fields.forEach(function (field) {
          var name = field && typeof field === 'object' ? field.name : field;
          if (name !== undefined && name !== null && String(name)) appendArcgisText(list, 'li', '', String(name));
        });
        details.appendChild(list);
        status.appendChild(details);
      }
    } else {
      var layers = Array.isArray(info.layers) ? info.layers : [];
      appendArcgisText(status, 'div', 'arcgis-inspection-summary',
        '服务：' + (info.service_name || 'ArcGIS REST') + ' · CRS：' + (info.crs || '未知') +
        ' · 发现 ' + layers.length + ' 个图层');
      if (layers.length) {
        var layerDetails = document.createElement('details');
        layerDetails.className = 'arcgis-inspection-fields';
        var layerSummary = document.createElement('summary');
        layerSummary.textContent = '查看图层名称和 ID';
        layerDetails.appendChild(layerSummary);
        var layerList = document.createElement('ul');
        layers.forEach(function (item) {
          appendArcgisText(layerList, 'li', '', (item.name || '未命名图层') + '（ID ' + item.id + '）');
        });
        layerDetails.appendChild(layerList);
        status.appendChild(layerDetails);
      }
      appendArcgisText(status, 'div', 'arcgis-inspection-next', '填写图层 ID 后再次检查。');
    }

    if (layer) {
      appendArcgisText(status, 'div', 'arcgis-inspection-next',
        '确认图层与筛选条件后，点击“获取”。');
    }
  }

  function inspectArcgis() {
    var recipe = readArcgisRecipe();
    if (!recipe.url) { setArcgisStatus('请先输入 ArcGIS REST 图层或服务 URL。'); return; }
    var button = document.getElementById('arcgisInspectBtn');
    button.disabled = true;
    setArcgisStatus('正在读取服务与图层元数据…');
    fetch(apiUrl('/api/url-data/inspect'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: recipe.url, layer_id: recipe.layer_id }) })
      .then(readJsonResponse)
      .then(function (info) {
        var layer = info.layer_name ? info : null;
        setArcgisInspection(info);
        if (layer && layer.layer_id !== undefined) document.getElementById('arcgisLayerId').value = String(layer.layer_id);
      })
      .catch(function (error) { setArcgisStatus('检查失败：' + error.message); })
      .finally(function () { button.disabled = false; });
  }

  function readJsonResponse(response) {
    return response.json().then(function (data) {
      if (!response.ok) throw new Error((data && (data.detail || data.error)) || ('HTTP ' + response.status));
      return data;
    });
  }

  function startArcgisFetch(recipe) {
    if (!recipe || !recipe.url) { setArcgisStatus('请先输入 ArcGIS REST 图层或服务 URL。'); return; }
    var runButton = document.getElementById('onlineLoadBtn');
    if (_activeFetchJob || (runButton && runButton.disabled)) return;
    _lastArcgisRecipe = recipe;
    try { localStorage.setItem('gis_last_arcgis_fetch_recipe', JSON.stringify(Object.assign({}, recipe, { url: sanitizeArcgisUrl(recipe.url) }))); } catch (e) {}
    var cancelButton = document.getElementById('arcgisCancelBtn');
    var rerunButton = document.getElementById('arcgisRerunBtn');
    runButton.disabled = true;
    runButton.textContent = '启动中…';
    cancelButton.style.display = '';
    if (rerunButton) { rerunButton.style.display = ''; rerunButton.disabled = true; }
    var resultBox = document.getElementById('arcgisFetchResult');
    resultBox.textContent = '';
    resultBox.style.display = 'none';
    setArcgisStatus(recipe.mode === 'full' ? '正在检查服务并获取完整 ID 清单…' : '正在执行限量预览…');
    fetch(apiUrl('/api/url-data/jobs'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(recipe) })
      .then(readJsonResponse)
      .then(function (job) { _activeFetchJob = job.job_id; pollArcgisFetch(); })
      .catch(function (error) { finishArcgisFetch(); setArcgisStatus('启动失败：' + error.message); });
  }

  function pollArcgisFetch() {
    if (!_activeFetchJob) return;
    fetch(apiUrl('/api/url-data/jobs/' + encodeURIComponent(_activeFetchJob))).then(function (response) {
      if (response.status === 404) return { expired: true };
      return readJsonResponse(response);
    }).then(function (job) {
      if (job.expired) {
        setArcgisStatus('任务记录已过期，请重新获取。');
        finishArcgisFetch();
        return;
      }
      var progress = job.progress || {};
      if (job.status === 'cancelling') {
        setArcgisStatus('正在停止任务（当前网络请求结束后生效）…');
        _fetchPollTimer = setTimeout(pollArcgisFetch, 500);
        return;
      }
      if (job.status === 'running') {
        if (progress.total === null || progress.total === undefined) setArcgisStatus('正在检查 ArcGIS 服务能力…');
        else setArcgisStatus('已获取 ' + progress.completed + ' / ' + progress.total + ' 条' + (progress.batches ? '，第 ' + progress.batch + ' / ' + progress.batches + ' 批' : ''));
        _fetchPollTimer = setTimeout(pollArcgisFetch, 500);
        return;
      }
      if (job.status === 'failed' || job.status === 'cancelled' || job.status === 'unknown') {
        setArcgisStatus((job.status === 'cancelled' ? '任务已取消。' : job.status === 'unknown' ? '完整性未知，未生成可交付数据：' : '获取失败：') + (job.error || ''));
        finishArcgisFetch();
        return;
      }
      showArcgisFetchResult(job.result || {});
      finishArcgisFetch();
    }).catch(function (error) {
      setArcgisStatus('读取任务状态失败：' + error.message);
      _fetchPollTimer = setTimeout(pollArcgisFetch, 1500);
    });
  }

  function showArcgisFetchResult(result) {
    var state = result.completeness || 'unknown';
    var statusText = result.mode === 'preview'
      ? '预览已获取 ' + result.feature_count + ' 条；完整性未检查。'
      : state === 'complete' ? '完整性检查通过：' + result.feature_count + ' / ' + result.expected_count + ' 条对象 ID 一致。'
        : state === 'partial' ? '只获取到部分数据：' + result.feature_count + ' / ' + result.expected_count + ' 条。'
          : '已生成结果，但完整性无法确认：' + (result.completeness_reason || '未知原因');
    setArcgisStatus(statusText + (result.warnings && result.warnings.length ? ' ' + result.warnings.join('；') : ''));
    var box = document.getElementById('arcgisFetchResult');
    box.innerHTML = '';
    var files = [[result.data_url, '下载数据'], [result.report_url, '检查报告'], [result.manifest_url, '来源清单'], [result.recipe_url, '复跑配方']];
    files.forEach(function (file) {
      if (!file[0]) return;
      var link = document.createElement('a');
      link.href = apiUrl(file[0]) + '?download=1'; link.textContent = file[1]; link.download = file[0].split('/').pop();
      link.style.marginRight = '10px'; box.appendChild(link);
    });
    box.style.display = '';
    var applyResult = result.data_url
      ? fetch(apiUrl(result.data_url)).then(function (r) { if (!r.ok) throw new Error('读取数据文件失败'); return r.json(); }) : Promise.resolve(null);
    applyResult.then(function (geojson) {
      if (geojson) applyOnlineResult({ geojson: geojson, name: 'ArcGIS_' + (result.file_name || '下载结果'), message: statusText });
      else setArcgisStatus(statusText + ' 地图没有加载：结果文件不可读取。');
    }).catch(function (error) { setArcgisStatus(statusText + ' 地图加载失败：' + error.message); });
  }

  function finishArcgisFetch() {
    _activeFetchJob = '';
    if (_fetchPollTimer) clearTimeout(_fetchPollTimer);
    _fetchPollTimer = null;
    var runButton = document.getElementById('onlineLoadBtn');
    var cancelButton = document.getElementById('arcgisCancelBtn');
    var rerunButton = document.getElementById('arcgisRerunBtn');
    if (runButton) { runButton.disabled = false; runButton.textContent = '获取'; }
    if (cancelButton) cancelButton.style.display = 'none';
    if (rerunButton) rerunButton.disabled = false;
  }

  function cancelArcgisFetch() {
    if (!_activeFetchJob) return;
    fetch(apiUrl('/api/url-data/jobs/' + encodeURIComponent(_activeFetchJob)), { method: 'DELETE' })
      .then(readJsonResponse).then(function () { setArcgisStatus('正在停止任务（当前网络请求结束后生效）…'); })
      .catch(function (error) { setArcgisStatus('取消失败：' + error.message); });
  }

  function applyOnlineResult(result) {
    var name = result.name || result.message || '在线数据';
    if (result.raster_info) {
      var info = result.raster_info;
      var layerId = 'raster_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
      if (window.GIS.map && GIS.map.addImageOverlay) {
        GIS.map.addImageOverlay(info.url, info.bounds, name, layerId);
      }
      if (window.GIS.layers && GIS.layers.addLayer) {
        GIS.layers.addLayer({
          layer_id: layerId,
          _rawName: layerId,
          filename: name,
          geometry_type: 'Raster',
          crs: 'WGS-84',
          source: 'upload',
          raster: info,
        }, true);
      }
    } else if (result.geojson && window.GIS.map) {
      var gj = result.geojson;
      var gtype = gj.type === 'FeatureCollection' && gj.features && gj.features.length
        ? gj.features[0].geometry.type : (gj.geometry ? gj.geometry.type : '未知');
      if (typeof GIS.map.loadGeoJSON === 'function') GIS.map.loadGeoJSON(gj, result.name || name);
      if (window.GIS.layers && GIS.layers.addLayer) {
        GIS.layers.addLayer({
          layer_id: (result.name || name) + '_' + Date.now(),
          filename: result.name || name,
          geometry_type: gtype,
          crs: 'WGS-84',
          geojson: gj,
          source: 'upload',
        }, true);
      }
    }
    if (window.GIS.chat && GIS.chat.addMessage) {
      GIS.chat.addMessage('[在线数据] ' + (result.message || name), 'system', { hidden: true });
    }
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
  window.GIS.connector = { init: init, hide: hide, openArcgis: openArcgis };

  // DOM 就绪后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
