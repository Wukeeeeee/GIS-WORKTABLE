/**
 * ============================================
 *  GIS AI WorkTable — 应用入口
 *  负责初始化所有模块、注册全局命名空间
 * ============================================
 */

window.GIS = window.GIS || {};

(function() {
  'use strict';

  const GIS = window.GIS;

  /**
   * 初始化所有模块
   * DOMContentLoaded 后自动调用
   */
  function init() {
    console.log('[GIS] 应用初始化...');

    // 启动超时检测（10秒后检查关键模块是否就绪）
    var _startTime = Date.now();
    var _checkLoaded = setInterval(function() {
      if (Date.now() - _startTime > 10000) {
        clearInterval(_checkLoaded);
        var missing = [];
        if (!GIS.map || typeof GIS.map.init !== 'function') missing.push('地图');
        if (!GIS.chat || typeof GIS.chat.init !== 'function') missing.push('聊天');
        if (!GIS.layers || typeof GIS.layers.init !== 'function') missing.push('图层');
        if (missing.length) {
          var errMsg = '模块加载失败: ' + missing.join(', ') + '。请检查网络连接后刷新页面。';
          console.error('[GIS] ' + errMsg);
          var chatArea = document.querySelector('.chat-messages');
          if (chatArea) {
            var el = document.createElement('div');
            el.style.cssText = 'padding:20px;text-align:center;color:#c62828;font-size:14px;';
            el.textContent = errMsg;
            chatArea.appendChild(el);
          }
        }
      }
    }, 1000);

    // 1. 初始化地图
    if (GIS.map && typeof GIS.map.init === 'function') {
      GIS.map.init('map');
    } else {
      console.warn('[GIS] 地图模块未加载');
    }

    // 2. 初始化聊天
    if (GIS.chat && typeof GIS.chat.init === 'function') {
      GIS.chat.init();
    } else {
      console.warn('[GIS] 聊天模块未加载');
    }

    // 3. 初始化图层管理
    if (GIS.layers && typeof GIS.layers.init === 'function') {
      GIS.layers.init();
    } else {
      console.warn('[GIS] 图层模块未加载');
    }

    // 4. 初始化上传
    if (GIS.upload && typeof GIS.upload.init === 'function') {
      GIS.upload.init();
    } else {
      console.warn('[GIS] 上传模块未加载');
    }

    // 5. 初始化 AOI 提取（百度 + 高德双源）
    if (GIS.aoi && typeof GIS.aoi.init === 'function') {
      GIS.aoi.init();
    } else {
      console.warn('[GIS] AOI模块未加载');
    }

    // 6. 初始化任务模块
    if (GIS.task && typeof GIS.task.init === 'function') {
      GIS.task.init();
    } else {
      console.warn('[GIS] 任务模块未加载');
    }

    // 7. 绑定全局快捷键 / 事件
    bindGlobalEvents();

    console.log('[GIS] 应用初始化完成');
  }

  /**
   * 全局事件绑定
   */
  function bindGlobalEvents() {
    // ESC 关闭可能存在的弹出层
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        var settingsModal = document.getElementById('settingsModal');
        if (settingsModal && settingsModal.style.display === 'flex') {
          settingsModal.style.display = 'none';
        }
        var contextMenu = document.getElementById('mapContextMenu');
        if (contextMenu) contextMenu.style.display = 'none';
        var inspector = document.getElementById('layerInspector');
        if (inspector) inspector.style.display = 'none';
      }
    });

    // 浮动图层面板：折叠/展开
    var layerPanel = document.getElementById('mapLayerPanel');
    var toggleBtn = document.getElementById('toggleLayerPanel');
    if (layerPanel && toggleBtn) {
      toggleBtn.addEventListener('click', function() {
        layerPanel.classList.toggle('collapsed');
        toggleBtn.classList.toggle('active');
      });
    }

    // 图层检查器关闭按钮
    var inspectorClose = document.getElementById('inspectorClose');
    if (inspectorClose) {
      inspectorClose.addEventListener('click', function() {
        if (GIS.layers && typeof GIS.layers.closeInspector === 'function') {
          GIS.layers.closeInspector();
        }
      });
    }

    // 设置弹窗打开时，如果切换到历史记录面板则刷新列表
    var settingsBtn = document.getElementById('settingsBtn');
    if (settingsBtn) {
      settingsBtn.addEventListener('click', function() {
        if (window.GIS.task && typeof window.GIS.task.getTasks === 'function') {
          // re-render will happen via renderAll on next open
        }
      });
    }
  }

  // DOM 就绪后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ========== 公开接口 ==========
  GIS.app = {
    init,
  };
})();
