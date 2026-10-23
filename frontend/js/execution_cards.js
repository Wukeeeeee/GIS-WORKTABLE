/* Real-time task-step cards used by the chat SSE stream. */
window.GIS = window.GIS || {};
(function () {
  'use strict';

  function create(container) {
    if (!container) return null;
    var toolFailureText = /^(?:错误|失败|无法|未找到|请提供|\[[ \t]*(?:error|failed|failure|exception)[ \t]*\]|(?:error|failed|failure|exception)\b|[^\r\n。；;]{1,40}?(?:失败|错误|异常|未通过|未能|无法)(?=[:：,，\s]|$)|[^\r\n.!?]{1,48}\b(?:failed|failure|error|exception)(?:[:.,\s]|$))/i;
    var root = document.createElement('section');
    root.className = 'ai-execution-cards';
    root.hidden = true;
    root.setAttribute('aria-live', 'polite');
    root.setAttribute('aria-label', 'AI 执行步骤');
    var cards = new Map();
    var calls = new Map();
    var completedCalls = new Set();
    var callSequence = 0;
    var closed = false;
    var appliedOps = new Set();

    function text(tag, className, value) {
      var el = document.createElement(tag);
      if (className) el.className = className;
      el.textContent = value || '';
      return el;
    }
    var toolLabels = {
      focus_map: ['定位地图', 'location'], reverse_geocode: ['查询坐标位置', 'location'], amap_geocode: ['查询位置', 'location'],
      measure_distance: ['测量距离', 'distance'], fetch_weather_data: ['查询天气', 'weather'],
      get_elevation_data: ['获取高程数据', 'elevation'], search_web: ['搜索网页', 'search'],
      fetch_webpage: ['读取网页', 'web'], fetch_webpage_scrapling: ['读取网页', 'web'],
      fetch_gis_data_url: ['获取 GIS 数据', 'map'], execute_python: ['执行空间分析', 'code']
    };
    function parseArgs(input) {
      if (input && typeof input === 'object' && !Array.isArray(input)) return input;
      var raw = String(input || '');
      try {
        var parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
      } catch (_) { return {_raw: raw}; }
    }
    function taskDetails(name, input, fallback) {
      var info = toolLabels[name] || ['执行 GIS 任务', 'generic'];
      var cleanFallback = String(fallback || '').trim();
      var useFallback = false;
      if ((name === 'search_web' || name === 'fetch_webpage' || name === 'fetch_webpage_scrapling') &&
          cleanFallback.length <= 40 && /[\u3400-\u9fff]/.test(cleanFallback)) {
        info = [cleanFallback, cleanFallback.indexOf('天气') >= 0 ? 'weather' : (name === 'search_web' ? 'search' : 'web')];
        useFallback = true;
      } else if (name === 'focus_map' && /^定位/.test(cleanFallback) && cleanFallback.length <= 40) {
        info = [cleanFallback, 'location'];
        useFallback = true;
      }
      var args = parseArgs(input);
      var target = '';
      var location = args.location || args.city || args.address || args.layer_name || args.layer || args.name || args.url;
      if (location && typeof location === 'string') target = /^https?:\/\//i.test(location)
        ? location.replace(/^https?:\/\//i, '').split(/[/?#]/)[0] : location;
      var raw = String(args._raw || '');
      if (!target) {
        var lon = raw.match(/(?:经度|longitude|\blon\b|\blng\b)[^\d-]*(-?\d+(?:\.\d+)?)/i);
        var lat = raw.match(/(?:纬度|latitude|\blat\b)[^\d-]*(-?\d+(?:\.\d+)?)/i);
        if (lon && lat) target = lon[1] + ', ' + lat[1];
      }
      if (!target && (args.longitude != null || args.latitude != null || args.lng != null || args.lat != null)) {
        var x = args.longitude != null ? args.longitude : args.lng;
        var y = args.latitude != null ? args.latitude : args.lat;
        if (x != null && y != null) target = x + ', ' + y;
      }
      if (!target && args.center) target = String(args.center).replace(/\s+/g, '');
      if (!target && args.query) {
        var query = String(args.query).replace(/\s+/g, ' ').trim();
        if (query.length <= 32) target = query;
      }
      if (useFallback) target = '';
      if (!target && fallback && fallback.indexOf(' · ') >= 0) {
        var tail = fallback.slice(fallback.indexOf(' · ') + 3).trim();
        if (tail.length <= 32 && !/[，。；]/.test(tail)) target = tail;
      }
      return {title: info[0] + (target ? ' · ' + target.slice(0, 40) : ''), kind: info[1]};
    }
    function taskIconPath(kind) {
      return ({
        location: '<path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
        distance: '<path d="M4 18 18 4M8 4h10v10"/><path d="m5 9 3 3m1-7 3 3m1-7 3 3"/>',
        weather: '<circle cx="8" cy="8" r="3"/><path d="M8 2v1m0 10v1M2 8h1m10 0h1m-8-4-1-1m8 8-1-1"/><path d="M8 18h9a3 3 0 0 0 0-6 5 5 0 0 0-9-1 3.5 3.5 0 0 0 0 7Z"/>',
        elevation: '<path d="m3 19 6-10 4 6 3-4 5 8H3Z"/><path d="m8 11 1-2 2 3"/>',
        search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
        web: '<path d="M5 3h10l4 4v14H5z"/><path d="M14 3v5h5M8 12h8m-8 4h8"/>',
        map: '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15m6-12v15"/>',
        code: '<path d="m8 8-4 4 4 4m8-8 4 4-4 4m-3-11-2 14"/>',
        generic: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 1.5"/>'
      })[kind] || '<circle cx="12" cy="12" r="8"/>';
    }
    function icon(kind) {
      var span = document.createElement('span');
      span.className = 'ai-step-icon';
      span.setAttribute('aria-hidden', 'true');
      span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + taskIconPath(kind) + '</svg>';
      return span;
    }
    function statusIconPath(status) {
      return ({
        running: '<circle cx="12" cy="12" r="8" stroke-dasharray="34 16"/>',
        success: '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16.5 9"/>',
        failed: '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',
        waiting: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        warning: '<path d="M10.3 4.4 2.8 17.2A2 2 0 0 0 4.5 20h15a2 2 0 0 0 1.7-2.8L13.7 4.4a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 3h.01"/>',
        cancelled: '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',
        interrupted: '<path d="M12 3 2.8 19h18.4L12 3Z"/><path d="M12 9v4m0 3h.01"/>'
      })[status] || '<circle cx="12" cy="12" r="8"/>';
    }
    function setStatus(card, status, label) {
      card.status = status;
      card.row.className = 'ai-step-card ai-step-' + status;
      var labels = {running: '执行中', success: '已完成', failed: '执行失败', cancelled: '已取消', interrupted: '连接中断', waiting: '等待确认', warning: '部分完成 / 警告'};
      card.statusText.textContent = label || labels[status] || '执行中';
      card.statusIcon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + statusIconPath(status) + '</svg>';
      card.statusBadge.setAttribute('aria-label', card.statusText.textContent);
      card.progressTrack.hidden = status !== 'running';
    }
    function ensureCard(stepId, label, toolName, input) {
      var key = stepId || ('legacy-' + (cards.size + 1));
      var card = cards.get(key);
      if (card) return card;
      card = { id: key, status: 'running', inFlight: 0, counts: {search: 0, read: 0}, outputs: [], pendingMapOps: 0, warning: false };
      card.failedCalls = new Map();
      card.mapErrors = new Map();
      card.row = document.createElement('article');
      card.row.className = 'ai-step-card ai-step-running';
      var heading = document.createElement('div'); heading.className = 'ai-step-heading';
      var task = toolName ? taskDetails(toolName, input, label) : {title: label || '执行 GIS 任务', kind: 'generic'};
      card.icon = icon(task.kind); heading.appendChild(card.icon);
      card.row.dataset.taskKind = task.kind;
      card.title = text('strong', 'ai-step-title', task.title); heading.appendChild(card.title);
      card.statusBadge = document.createElement('span'); card.statusBadge.className = 'ai-step-status';
      card.statusIcon = document.createElement('span'); card.statusIcon.className = 'ai-step-status-icon'; card.statusIcon.setAttribute('aria-hidden', 'true'); card.statusBadge.appendChild(card.statusIcon);
      card.statusText = text('span', 'ai-step-status-text', '执行中'); card.statusBadge.appendChild(card.statusText); heading.appendChild(card.statusBadge);
      card.row.appendChild(heading);
      card.progress = text('div', 'ai-step-progress', '正在处理'); card.row.appendChild(card.progress);
      card.progressTrack = document.createElement('div'); card.progressTrack.className = 'ai-step-progress-track'; card.progressTrack.setAttribute('aria-hidden', 'true');
      card.progressIndicator = document.createElement('span'); card.progressIndicator.className = 'ai-step-progress-indicator'; card.progressTrack.appendChild(card.progressIndicator); card.row.appendChild(card.progressTrack);
      card.records = document.createElement('details'); card.records.className = 'ai-step-records';
      card.recordsSummary = text('summary', '', '工具记录'); card.records.appendChild(card.recordsSummary);
      card.recordList = document.createElement('ol'); card.recordList.className = 'ai-step-record-list'; card.records.appendChild(card.recordList);
      card.row.appendChild(card.records);
      root.appendChild(card.row);
      cards.set(key, card);
      return card;
    }
    function updateProgress(card) {
      var bits = [];
      if (card.counts.search) bits.push('已搜索' + card.counts.search + '次');
      if (card.counts.read) bits.push('已读取' + card.counts.read + '个网页');
      if (card.inFlight) bits.push('正在处理' + card.inFlight + '项');
      if (card.pendingMapOps) bits.push('正在应用地图操作');
      if (card.outputs.length) card.progress.textContent = card.outputs[card.outputs.length - 1];
      else card.progress.textContent = bits.join(' · ') || (card.status === 'running' ? '正在处理' : '');
      if (bits.length && card.outputs.length) card.progress.textContent += ' · ' + bits.join(' · ');
    }
    function brief(output) {
      var value = String(output == null ? '' : output).replace(/\s+/g, ' ').trim();
      return value.length > 180 ? value.slice(0, 177) + '…' : value;
    }
    function currentError(card) {
      var failure = card.failedCalls.values().next().value;
      card.error = failure ? failure.error : card.mapErrors.values().next().value || null;
      return card.error;
    }
    function settleCard(card) {
      var error = currentError(card);
      if (card.inFlight) setStatus(card, 'running', error ? '仍在处理（存在失败）' : null);
      else if (card.pendingMapOps) setStatus(card, 'running', '等待地图操作');
      else if (error) setStatus(card, 'failed', card.failedCalls.size ? '步骤失败' : '地图操作失败');
      else setStatus(card, card.warning ? 'warning' : 'success');
      updateProgress(card);
    }
    function addStart(evt) {
      var callId = evt.tool_call_id ? String(evt.tool_call_id) : 'legacy-call-' + (++callSequence);
      if (calls.has(callId) || completedCalls.has(callId)) return null;
      var card = ensureCard(evt.step_id, evt.step_label, evt.name, evt.input);
      var retryOf = null;
      if (card.inFlight === 0) card.failedCalls.forEach(function (failed, id) {
        if (failed.name === evt.name) retryOf = id;
      });
      var retrying = retryOf !== null;
      var row = document.createElement('li'); row.className = 'ai-tool-record';
      var head = text('strong', '', evt.name || '工具'); row.appendChild(head);
      var input = text('pre', 'ai-tool-args', typeof evt.input === 'string' ? evt.input : JSON.stringify(evt.input || {}, null, 2));
      row.appendChild(input); card.recordList.appendChild(row);
      calls.set(callId, {id: callId, card: card, row: row, name: evt.name || '工具', retryOf: retryOf});
      card.inFlight++;
      if (evt.name === 'search_web') card.counts.search++;
      if (evt.name === 'fetch_webpage' || evt.name === 'fetch_webpage_scrapling') card.counts.read++;
      setStatus(card, 'running', retrying ? '正在重试' : null); updateProgress(card);
      return card;
    }
    function addEnd(evt) {
      var callId = evt.tool_call_id ? String(evt.tool_call_id) : '';
      if (callId && completedCalls.has(callId)) return null;
      var call = callId ? calls.get(callId) : null;
      if (!call && !callId) {
        calls.forEach(function (candidate) {
          if (!call && candidate.name === evt.name && (!evt.step_id || candidate.card.id === evt.step_id)) call = candidate;
        });
      }
      if (!call) {
        // 兼容开始事件缺失的流，仍保留实际返回的结果及失败信息。
        var orphanId = callId || 'legacy-call-' + (++callSequence);
        addStart({tool_call_id: orphanId, step_id: evt.step_id, step_label: evt.step_label,
          name: evt.name, input: evt.input || '（未收到调用参数）'});
        call = calls.get(orphanId);
        if (!call) return null;
      }
      calls.delete(call.id);
      completedCalls.add(call.id);
      var card = call.card;
      card.inFlight = Math.max(0, card.inFlight - 1);
      var fullOutput = String(evt.output == null ? '' : evt.output).trim();
      var output = brief(fullOutput);
      var isError = evt.is_error === true || /^(error|failed|failure)$/i.test(evt.status || '') || toolFailureText.test(fullOutput);
      var isWarning = evt.status === 'partial' || evt.partial === true || evt.has_warning === true;
      var errorText = String(evt.error_message || '').trim();
      if (!isError && fullOutput) {
        try {
          var parsed = JSON.parse(fullOutput);
          isError = !!(parsed && typeof parsed === 'object' && (parsed.ok === false || parsed.success === false || parsed.is_error === true || /^(error|failed|failure)$/i.test(parsed.status || '')));
          isWarning = isWarning || !!(parsed && typeof parsed === 'object' && (parsed.partial === true || parsed.has_warning === true || parsed.status === 'partial' || (Array.isArray(parsed.warnings) && parsed.warnings.length > 0) || (Array.isArray(parsed.qa_warnings) && parsed.qa_warnings.length > 0) || Number(parsed.skipped_count || 0) > 0));
          if (isError) errorText = String(parsed.error || parsed.message || parsed.hint || '工具执行失败').trim();
        } catch (_) { /* Non-JSON results use the legacy status and prefix checks. */ }
      }
      var resultEl = text('div', 'ai-tool-result', fullOutput.slice(0, 1200) || (isError ? '工具执行失败' : '已返回结果'));
      call.row.appendChild(resultEl);
      if (isError) {
        call.row.classList.add('ai-tool-failed');
        call.error = errorText || output || '工具执行失败';
        card.failedCalls.set(call.id, call);
        card.outputs.push('失败：' + brief(call.error));
      } else {
        if (call.retryOf !== null) card.failedCalls.delete(call.retryOf);
        if (output) card.outputs.push(output);
        if (isWarning) {
          card.warning = true;
          card.outputs.push('部分完成或有警告');
        }
      }
      settleCard(card);
      return card;
    }
    function applyMapOps(evt) {
      if (!Array.isArray(evt.layer_ops) || !evt.layer_ops.length) return;
      var card = ensureCard(evt.step_id, evt.step_label);
      var ops = evt.layer_ops;
      ops.forEach(function (op) {
        if (!op || typeof op !== 'object') return;
        if (op._stream_id && appliedOps.has(op._stream_id)) return;
        var applied = false;
        var opKey = op._stream_id || op.action + ':' + (op.name || '');
        if (op.action === 'center' && Array.isArray(op.center) && op.center.length === 2
            && op.center.every(function (value) { return typeof value === 'number' && Number.isFinite(value); })
            && Math.abs(op.center[0]) <= 180 && Math.abs(op.center[1]) <= 90) {
          try {
            var zoom = op.zoom == null ? 13 : Number(op.zoom);
            if (!Number.isFinite(zoom)) throw new Error('地图缩放级别无效');
            if (window.GIS.renderers && window.GIS.renderers.is3D && window.GIS.renderers.is3D()) {
              var viewer = window.GIS.renderers.getViewer && window.GIS.renderers.getViewer();
              if (viewer && window.Cesium) {
                viewer.camera.flyTo({destination: window.Cesium.Cartesian3.fromDegrees(Number(op.center[0]), Number(op.center[1]), Math.max(500, Math.pow(2, 22 - zoom) * 60)), duration: 1.5});
                applied = true;
              }
            } else if (window.GIS.map && window.GIS.map.setView) {
              applied = window.GIS.map.setView([op.center[1], op.center[0]], zoom) === true;
            }
          } catch (e) { applied = false; }
        } else if (op.action === 'fit' && op.name) {
          try {
            if (window.GIS.renderers && window.GIS.renderers.is3D && window.GIS.renderers.is3D()) {
              var record = null;
              if (window.GIS.state && window.GIS.state.getLayers) window.GIS.state.getLayers().forEach(function (layer) { if (layer.name === op.name || layer._rawName === op.name) record = layer; });
              if (record && record.bbox && window.GIS.renderers.flyToBbox) applied = window.GIS.renderers.flyToBbox(record.bbox, 1.5) === true;
            } else {
              var layers = window.GIS.layers && window.GIS.layers.getLayers ? window.GIS.layers.getLayers() : [];
              var found = layers.some(function (layer) { return layer.name === op.name || layer._rawName === op.name || layer.filename === op.name || layer.layer_id === op.name; });
              if (found && window.GIS.map && window.GIS.map.fitLayer) applied = window.GIS.map.fitLayer(op.name) === true;
            }
          } catch (e) { applied = false; }
        }
        if (op._stream_id && applied) appliedOps.add(op._stream_id);
        if (applied) {
          card.pendingMapOps = Math.max(0, card.pendingMapOps - 1);
          card.mapErrors.delete(opKey);
        } else card.mapErrors.set(opKey, '地图操作未能应用：' + (op.name || op.action));
      });
      settleCard(card);
    }
    function handle(evt) {
      if (!evt || closed) return;
      if (evt.type === 'tool_start') {
        var c = addStart(evt);
        if (c && Number.isInteger(evt.map_ops_pending) && evt.map_ops_pending > 0) { c.pendingMapOps += evt.map_ops_pending; updateProgress(c); }
      } else if (evt.type === 'tool_end') addEnd(evt);
      else if (evt.type === 'layer_ops_delta') applyMapOps(evt);
      else if (evt.type === 'waiting_choice') {
        var card = ensureCard(evt.step_id, evt.step_label); setStatus(card, 'waiting', '等待选择');
      }
      root.hidden = cards.size === 0;
    }
    function finish(status, message) {
      closed = true;
      calls.clear();
      cards.forEach(function (card) {
        if (card.status !== 'running' && card.status !== 'waiting') return;
        if (card.status === 'waiting' && status === 'success') return;
        if (status === 'success') {
          if (currentError(card)) setStatus(card, 'failed');
          else if (card.inFlight) {
            setStatus(card, 'warning', '结果不完整');
            card.outputs.push('未收到全部工具结果');
          } else if (card.pendingMapOps) {
            setStatus(card, 'failed', '地图操作未完成');
            card.outputs.push('未确认地图操作已经应用');
          } else setStatus(card, card.warning ? 'warning' : 'success');
        }
        else if (status === 'cancelled') setStatus(card, 'cancelled');
        else if (status === 'interrupted') setStatus(card, 'interrupted');
        else if (status === 'waiting') setStatus(card, 'waiting');
        else setStatus(card, 'failed');
        card.inFlight = 0;
        card.pendingMapOps = 0;
        if (message && status !== 'success') card.outputs.push(message);
        updateProgress(card);
      });
    }
    function resolveWaiting(cancelled) {
      cards.forEach(function (card) {
        if (card.status !== 'waiting') return;
        setStatus(card, cancelled ? 'cancelled' : 'success', cancelled ? '已取消选择' : '已提交选择');
        updateProgress(card);
      });
    }
    container.appendChild(root);
    return {handle: handle, finish: finish, resolveWaiting: resolveWaiting,
      hasAppliedMapOp: function (id) { return !!id && appliedOps.has(id); }, element: root};
  }
  window.GIS.executionCards = {create: create};
})();
