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

    // 6. 绑定全局快捷键 / 事件
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
        // TODO: 关闭弹窗/下拉菜单
      }
    });
  }

  /**
   * 显示 Toast 通知
   * @param {string} message - 提示内容
   * @param {'success'|'error'|'warning'|'info'} [type='info']
   */
  function toast(message, type) {
    if (!type) type = 'info';
    var container = document.getElementById('toastContainer');
    if (!container) {
      console.warn('[GIS Toast] #toastContainer 不存在');
      return;
    }

    // 用对象字面量替代 ES6 Map，每个类型对应 [图标路径, 颜色]
    var iconPaths = {
      success: { path: 'M9 12l2 2 4-4', color: '#2e7d32' },
      error:   { path: 'M15 9l-6 6m0-6l6 6', color: '#c62828' },
      warning: { path: 'M12 9v4m0 4h.01', color: '#e65100' },
      info:    { path: 'M12 16v-4m0-4h.01', color: '#444748' },
    };
    var cfg = iconPaths[type] || iconPaths.info;

    // 创建 toast 元素
    var el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML =
      '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="' + cfg.color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0;">' +
        '<circle cx="12" cy="12" r="10" stroke="' + cfg.color + '" fill="none"/>' +
        '<path d="' + cfg.path + '" stroke="' + cfg.color + '" fill="none"/>' +
      '</svg>' +
      '<span class="toast-message">' + message + '</span>' +
      '<button class="toast-close" title="关闭">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="#888" stroke-width="2" stroke-linecap="round" style="width:14px;height:14px;">' +
          '<path d="M6 6l12 12M6 18L18 6"/>' +
        '</svg>' +
      '</button>';

    // 点击关闭
    el.querySelector('.toast-close').addEventListener('click', function() {
      dismiss(el);
    });

    container.appendChild(el);

    // 3 秒后自动消失
    var timer = setTimeout(function() {
      dismiss(el);
    }, 3000);

    // 鼠标悬停时暂停计时
    el.addEventListener('mouseenter', function() {
      clearTimeout(timer);
    });
    el.addEventListener('mouseleave', function() {
      timer = setTimeout(function() {
        dismiss(el);
      }, 3000);
    });

    function dismiss(el) {
      if (el.classList.contains('toast-leaving')) return;
      el.classList.add('toast-leaving');
      setTimeout(function() {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 250);
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
    toast,
  };

  // 页面加载完成后弹一个测试 Toast，看系统是否正常工作
  if (document.readyState === 'complete') {
    setTimeout(function() { toast('GIS WorkTable 已就绪', 'info'); }, 500);
  } else {
    document.addEventListener('DOMContentLoaded', function() {
      setTimeout(function() { toast('GIS WorkTable 已就绪', 'info'); }, 500);
    });
  }
})();
