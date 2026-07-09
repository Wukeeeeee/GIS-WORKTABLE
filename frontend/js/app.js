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
  function toast(message, type = 'info') {
    // TODO: 实现 Toast 通知
    // - 创建 .toast 元素插入 .toast-container
    // - 3 秒后自动移除
    // - 根据 type 设置对应图标
    console.log(`[GIS Toast][${type}] ${message}`);
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
})();
