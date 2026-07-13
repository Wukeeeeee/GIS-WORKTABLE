/**
 * GIS AI WorkTable — 分析任务卡系统
 *
 * 功能:
 * 1. 将 AI 分析请求包装为任务卡（状态机：等待→规划中→执行中→成功/失败）
 * 2. 任务包含：目标、输入图层快照、AI 计划、执行代码、结果图层、统计摘要
 * 3. localStorage 持久化，支持重新运行
 * 4. 新建会话时保留主动保存的历史任务
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;
  const STORAGE_KEY = 'gis_task_history';
  const MAX_HISTORY = 50;

  let taskRecords = [];
  let _nextId = 1;

  // DOM 引用
  let taskListEl = null;
  let historyCountEl = null;

  // ===== 数据结构：TaskRecord =====
  // id, goal, provider, model, timestamp, completedAt,
  // status: pending|planning|executing|success|failed,
  // inputLayers: [{layerId, name, geometryType, featureCount}],
  // plan, code, resultSummary,
  // resultLayers: [{name, geojson, layerId}],
  // error, saved: bool

  function init() {
    taskListEl = document.getElementById('historyList');
    historyCountEl = document.getElementById('historyCount');
    loadFromStorage();
    renderAll();
    if (taskListEl) {
      taskListEl.addEventListener('click', handleTaskClick);
    }
    var clearBtn = document.getElementById('historyClearBtn');
    if (clearBtn) {
      clearBtn.addEventListener('click', function() {
        if (confirm('确定清除所有历史记录？已保存的任务将一并删除。')) {
          taskRecords = [];
          saveToStorage();
          renderAll();
        }
      });
    }
  }

  // ===== localStorage =====

  function saveToStorage() {
    try {
      var saved = taskRecords.filter(function(t) { return t.saved; });
      var recent = taskRecords.filter(function(t) { return !t.saved; }).slice(-20);
      var toStore = saved.concat(recent);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore));
    } catch(e) {
      console.warn('[GIS Task] 保存失败:', e);
    }
  }

  function loadFromStorage() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        taskRecords = JSON.parse(raw);
        taskRecords.forEach(function(t) {
          var nid = parseInt(t.id, 10);
          if (nid >= _nextId) _nextId = nid + 1;
        });
      }
    } catch(e) {
      console.warn('[GIS Task] 加载失败:', e);
      taskRecords = [];
    }
  }

  function clearUnsaved() {
    taskRecords = taskRecords.filter(function(t) { return t.saved; });
    saveToStorage();
    renderAll();
  }

  // ===== CRUD =====

  function createTask(goal, provider, inputLayers) {
    var modelNames = {
      'deepseek-routed': 'DeepSeek V4 Flash+',
      'glm-routed': 'GLM-4.7-Flash+',
    };
    var task = {
      id: String(_nextId++),
      goal: goal || '',
      provider: provider || 'deepseek-routed',
      model: modelNames[provider] || 'DeepSeek V4 Flash+',
      timestamp: Date.now(),
      completedAt: null,
      status: 'pending',
      inputLayers: (inputLayers || []).map(function(l) {
        return {
          layerId: l.layer_id || '',
          name: l.filename || l.name || '未命名',
          geometryType: l.geometry_type || '未知',
          featureCount: l.feature_count || 0,
        };
      }),
      plan: '',
      code: '',
      resultSummary: '',
      resultLayers: [],
      error: '',
      saved: false,
    };
    taskRecords.unshift(task);
    if (taskRecords.length > MAX_HISTORY) {
      taskRecords = taskRecords.slice(0, MAX_HISTORY);
    }
    saveToStorage();
    renderAll();
    return task;
  }

  function updateTask(taskId, updates) {
    var task = findTask(taskId);
    if (!task) return;
    Object.keys(updates).forEach(function(k) {
      task[k] = updates[k];
    });
    renderAll();
    if (updates.status || updates.saved !== undefined) {
      saveToStorage();
    }
  }

  function findTask(taskId) {
    for (var i = 0; i < taskRecords.length; i++) {
      if (taskRecords[i].id === taskId) return taskRecords[i];
    }
    return null;
  }

  function toggleSaved(taskId) {
    var task = findTask(taskId);
    if (!task) return;
    task.saved = !task.saved;
    saveToStorage();
    renderAll();
  }

  function deleteTask(taskId) {
    taskRecords = taskRecords.filter(function(t) { return t.id !== taskId; });
    saveToStorage();
    renderAll();
  }

  function rerunTask(taskId) {
    var original = findTask(taskId);
    if (!original) return;
    var newTask = createTask(original.goal, original.provider, original.inputLayers);
    if (GIS.chat && typeof GIS.chat.send === 'function') {
      GIS.chat.send(original.goal, {
        displayText: '[重新运行] ' + (original.goal.length > 50 ? original.goal.slice(0, 50) + '...' : original.goal),
        provider: original.provider,
        _taskId: newTask.id,
      });
    }
    return newTask;
  }

  // ===== 渲染 =====

  function renderAll() {
    if (!taskListEl) return;
    if (taskRecords.length === 0) {
      taskListEl.innerHTML = '<div class="task-empty">暂无分析任务</div>';
      if (historyCountEl) historyCountEl.textContent = '';
      return;
    }
    var html = '';
    taskRecords.forEach(function(t) {
      html += renderTaskCard(t);
    });
    taskListEl.innerHTML = html;
    if (historyCountEl) {
      var savedCount = taskRecords.filter(function(t) { return t.saved; }).length;
      historyCountEl.textContent = '共 ' + taskRecords.length + ' 条' + (savedCount ? '（已保存 ' + savedCount + ' 条）' : '');
    }
  }

  function renderTaskCard(t) {
    var statusLabel = {
      pending: '等待', planning: '规划中', executing: '执行中',
      success: '成功', failed: '失败',
    }[t.status] || t.status;

    var resultLayerHtml = '';
    if (t.resultLayers && t.resultLayers.length > 0) {
      resultLayerHtml = '<div class="task-result-layers">结果图层: ' +
        t.resultLayers.map(function(l) {
          return '<span class="task-layer-tag">' + escapeHtml(l.name || '未命名') + '</span>';
        }).join('') +
      '</div>';
    }

    var inputLayerHtml = '';
    if (t.inputLayers && t.inputLayers.length > 0) {
      inputLayerHtml = '<div class="task-input-layers">' +
        t.inputLayers.map(function(l) {
          return '<span class="task-layer-tag">' + escapeHtml(l.name) + '</span>';
        }).join('') +
      '</div>';
    }

    var codeHtml = t.code
      ? '<div class="task-code-wrapper"><button class="task-code-toggle" data-task-id="' + t.id + '">查看代码</button><pre class="task-code-block" style="display:none;">' + escapeHtml(t.code) + '</pre></div>'
      : '';

    var errorHtml = t.error
      ? '<div class="task-error">' + escapeHtml(t.error) + '</div>'
      : '';

    var canRerun = t.status === 'success' || t.status === 'failed';
    var isRunning = t.status === 'planning' || t.status === 'executing';

    return '<div class="task-card task-status-' + t.status + '" data-task-id="' + t.id + '">' +
      '<div class="task-card-header">' +
        '<div class="task-card-title-row">' +
          '<span class="task-status-badge task-badge-' + t.status + '">' + statusLabel + '</span>' +
          '<span class="task-goal-text">' + escapeHtml(truncate(t.goal, 80)) + '</span>' +
        '</div>' +
        '<div class="task-card-actions">' +
          '<button class="task-action-btn task-toggle-save" title="' + (t.saved ? '取消保存' : '保存任务') + '">' +
            (t.saved ? '★' : '☆') +
          '</button>' +
          (canRerun ? '<button class="task-action-btn task-rerun" title="重新运行">↻</button>' : '') +
          (isRunning ? '<span class="task-spinner"></span>' : '') +
          '<button class="task-action-btn task-delete" title="删除">✕</button>' +
        '</div>' +
      '</div>' +
      '<div class="task-card-body">' +
        '<div class="task-meta">' +
          '<span class="task-model">' + escapeHtml(t.model) + '</span>' +
          '<span class="task-time">' + formatTime(t.timestamp) + '</span>' +
        '</div>' +
        inputLayerHtml +
        (t.plan ? '<div class="task-plan">计划: ' + escapeHtml(truncate(t.plan, 200)) + '</div>' : '') +
        (t.resultSummary ? '<div class="task-summary">' + escapeHtml(truncate(t.resultSummary, 300)) + '</div>' : '') +
        resultLayerHtml +
        codeHtml +
        errorHtml +
      '</div>' +
    '</div>';
  }

  function handleTaskClick(e) {
    var card = e.target.closest('.task-card');
    if (!card) return;
    var taskId = card.dataset.taskId;

    var toggle = e.target.closest('.task-code-toggle');
    if (toggle) {
      var pre = toggle.nextElementSibling;
      if (pre) {
        var isHidden = pre.style.display === 'none';
        pre.style.display = isHidden ? 'block' : 'none';
        toggle.textContent = isHidden ? '收起代码' : '查看代码';
      }
      return;
    }

    if (e.target.closest('.task-toggle-save')) {
      toggleSaved(taskId);
      return;
    }
    if (e.target.closest('.task-delete')) {
      deleteTask(taskId);
      return;
    }
    if (e.target.closest('.task-rerun')) {
      rerunTask(taskId);
      return;
    }
  }

  // ===== 工具函数 =====

  function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function truncate(str, maxLen) {
    if (!str || str.length <= maxLen) return str || '';
    return str.slice(0, maxLen) + '...';
  }

  function formatTime(ts) {
    if (!ts) return '';
    var d = new Date(ts);
    var month = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    var hour = String(d.getHours()).padStart(2, '0');
    var min = String(d.getMinutes()).padStart(2, '0');
    return month + '-' + day + ' ' + hour + ':' + min;
  }

  // ===== 公开接口 =====

  GIS.task = {
    init: init,
    createTask: createTask,
    updateTask: updateTask,
    findTask: findTask,
    toggleSaved: toggleSaved,
    deleteTask: deleteTask,
    rerunTask: rerunTask,
    clearUnsaved: clearUnsaved,
    getTasks: function() { return [].concat(taskRecords); },
  };

})();
