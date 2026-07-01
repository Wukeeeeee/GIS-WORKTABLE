# GIS AI WorkTable 前端重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 indexbygoogle.html 的 Google Material 风格复刻到 frontend/index.html，纯内联 SVG 图标，通过 jsDelivr 国内 CDN 加载 Leaflet，JS 文件预留 API 接口骨架

**架构:** 单页面应用，手写 CSS（无 Tailwind），纯内联 SVG 图标，Leaflet 地图通过 jsDelivr CDN 加载，后端 API 通过 fetch 调用 localhost:8000

**Tech Stack:** HTML5 + CSS3 + Leaflet 1.9.4 + Vanilla JS

## Global Constraints

- 所有外部 JS/CSS 必须从 `cdn.jsdelivr.net` 加载（国内可访问）
- 不使用 Google Fonts、Material Symbols、Tailwind 等被墙资源
- 图标全部使用内联 SVG
- 字体使用系统字体栈
- API 后端地址为 `http://localhost:8000`
- 所有 JS 文件通过 `window.GIS` 命名空间注册

---

### Task 1: 创建 SVG 图标 Sprite

**Files:**
- Create: `frontend/assets/icons.svg`

- [ ] **创建 SVG symbol sprite 文件**

包含所有图标的 `<symbol>` 定义：
- `icon-ai` (smart_toy-like) 
- `icon-user` (person)
- `icon-send` (send arrow)
- `icon-upload` (upload)
- `icon-download` (download)
- `icon-delete` (delete)
- `icon-visibility` (eye open)
- `icon-visibility-off` (eye closed)
- `icon-drag` (drag indicator/dots)
- `icon-zoom-in` / `icon-zoom-out`
- `icon-locate` (my_location)
- `icon-file` (description/document)
- `icon-clock` (schedule/waiting)
- `icon-check` (check_circle)
- `icon-error` (error)
- `icon-filter` (filter_list)
- `icon-more` (more_vert)

### Task 2: 创建主页面 HTML

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/css/style.css`

- [ ] **编写完整的 HTML 骨架**

按照 indexbygoogle.html 的布局结构，包含：
- TopNavBar（左侧标题 + 状态）
- 左侧聊天面板（消息区 + 输入区）
- 中央地图区域（Leaflet 容器 + 缩放控件覆盖）
- 底部面板（图层列表 + 文件上传）

- [ ] **通过 `<link>` 引入 Leaflet CSS（jsDelivr 国内 CDN）**
- [ ] **HTML 中引用所有 JS 模块（按依赖顺序：api → app → map → chat → layers → upload）**
- [ ] **SVG 图标通过 `<use href="assets/icons.svg#icon-name"/>` 引用**

### Task 3: 编写完整 CSS 样式

**Files:**
- Modify: `frontend/css/style.css`

- [ ] **布局系统** — Flexbox 布局：左侧 320px 聊面板 + 中央地图自适应 + 底部 240px 面板
- [ ] **配色系统** — 从 indexbygoogle.html 提取完整颜色变量（surface-container、on-surface、primary 等）
- [ ] **聊天气泡** — AI 气泡（左）和用户气泡（右），带三角形尾巴
- [ ] **自定义滚动条** — 4px 宽灰色滚动条
- [ ] **地图网格背景** — CSS linear-gradient 实现的 40x40 网格
- [ ] **图层表格样式** — 行悬停高亮，操作按钮悬停显示
- [ ] **缩放控件覆盖** — 右上角垂直排列的按钮组
- [ ] **坐标显示条** — 左下角半透明底图标签
- [ ] **按钮/交互微动效** — mousedown 透明度反馈
- [ ] **上传按钮** — 文件上传区域 UI
- [ ] **暗色模式准备** — 通过 `.dark` class 切换

### Task 4: 创建 JS 接口预留文件

**Files:**
- Create: `frontend/js/api.js` — API 接口层（预留）
- Create: `frontend/js/app.js` — 应用入口
- Create: `frontend/js/map.js` — 地图模块（骨架）
- Create: `frontend/js/chat.js` — 聊天模块（骨架）
- Create: `frontend/js/layers.js` — 图层管理（骨架）
- Create: `frontend/js/upload.js` — 文件上传（骨架）

- [ ] **`api.js`** — 定义 `window.GIS.api` 对象，包含所有 fetch 封装函数（函数体为 `// TODO: 实现` 注释）：

  ```js
  window.GIS = window.GIS || {};
  window.GIS.api = {
    async upload(file) { /* POST /upload */ },
    async chat(message) { /* POST /chat */ },
    async getLayers() { /* GET /layers */ },
    async deleteLayer(id) { /* DELETE /layers/:id */ },
    async downloadLayer(id, format) { /* GET /download/:id */ },
    async executeGISAction(action, params) { /* POST /execute */ },
  };
  ```

- [ ] **`app.js`** — 初始化命名空间，DOMContentLoaded 时调用各模块初始化
- [ ] **`map.js`** — `window.GIS.map` 对象，含 `init(containerId)`、`loadGeoJSON(data)`、`clearLayers()`、`fitBounds()` 方法骨架
- [ ] **`chat.js`** — `window.GIS.chat` 对象，含 `addMessage(text, type)`、`send()`、输入框绑定方法骨架
- [ ] **`layers.js`** — `window.GIS.layers` 对象，含 `renderList()`、`addLayer()`、`removeLayer()`、`toggleVisibility()`、拖拽排序方法骨架
- [ ] **`upload.js`** — `window.GIS.upload` 对象，含 `openDialog()`、`validateFile()`、`startUpload()` 方法骨架

### Task 5: 自检和验证

- [ ] 确认所有 CDN 链接使用 jsDelivr（非 unpkg/google）
- [ ] 确认所有图标使用 `<use href="assets/icons.svg#...">` 引用
- [ ] 确认 HTML 中没有被墙的外部资源
- [ ] 确认 CSS 颜色方案与 indexbygoogle.html 一致
- [ ] 确认页面布局：左侧聊面板 + 地图 + 底部面板
