# GIS AI WorkTable 前端重构设计文档

## 概述

将 `indexbygoogle.html` 的 Google Material Design 风格复刻到 `frontend/index.html`，使用纯内联 SVG 图标替代 Google Material Symbols，通过 jsDelivr 国内 CDN 加载 Leaflet，确保在国内无需 VPN 即可使用。

## 页面布局

```
┌──────────────────────────────────────────────────────┐
│  TopNavBar (标题 + 状态)                              │
├──────────────┬───────────────────────────────────────┤
│              │                                       │
│  左侧聊面板   │         中央地图 (Leaflet)             │
│  ──────────  │  ┌─────────────────────────────────┐  │
│  AI 消息     │  │   天地图/OSM 底图                │  │
│  用户消息    │  │    + 绘制的 GeoJSON 图层          │  │
│  代码块      │  │    + 缩放控件                     │  │
│              │  └─────────────────────────────────┘  │
│  输入框      │                                       │
│  [发送]      ├───────────────────────────────────────┤
│              │  底部面板 (图层列表 / 文件上传)         │
└──────────────┴───────────────────────────────────────┘
```

## 技术栈

| 组件 | 选择 | 国内访问 |
|------|------|---------|
| 样式 | 手写 CSS（不依赖 Tailwind） | ✅ 无外部依赖 |
| 图标 | 纯内联 SVG 图标集 | ✅ 零请求，本地可用 |
| 地图 | Leaflet 1.9.4 | ✅ 通过 `cdn.jsdelivr.net` 加载 |
| 底图 | 天地图 + OpenStreetMap 备选 | ✅ 天地图是国内服务 |
| 字体 | 系统字体栈 | ✅ 无需加载任何字体 |
| 后端 | FastAPI `localhost:8000` | ✅ 本地服务 |

## 模块结构

### `frontend/index.html`
主页面，加载所有 CSS 和 JS 模块，定义 DOM 骨架。

### `frontend/css/style.css`
所有自定义样式，包括布局、组件、动画、滚动条、地图网格背景等。

### `frontend/js/app.js`
应用入口，负责：
- 初始化所有模块
- 注册全局命名空间 `window.GIS`
- 启动地图
- 绑定全局事件

### `frontend/js/api.js`
API 接口层，封装所有 fetch 调用：
- `upload(file)` → POST `/upload`
- `chat(message)` → POST `/chat`
- `getLayers()` → GET `/layers`
- `deleteLayer(id)` → DELETE `/layers/{id}`
- `downloadLayer(id, format)` → GET `/download/{id}?format=geojson`
- `executeGISAction(action, params)` → POST `/execute`
- `saveProject(data)` / `loadProject(id)` → 项目保存/加载

所有函数返回 Promise，统一错误处理。

### `frontend/js/map.js`
地图模块，负责：
- 初始化 Leaflet 地图
- 设置天地图/OSM 底图
- 加载/清除 GeoJSON 图层
- 缩放至图层范围
- 获取当前视图状态（中心点、缩放级别、坐标显示）

### `frontend/js/chat.js`
聊天模块，负责：
- 渲染 AI/用户消息气泡（包括代码块）
- 输入框事件绑定（Enter 发送）
- 消息列表自动滚动
- 发送按钮状态管理

### `frontend/js/layers.js`
图层管理模块，负责：
- 渲染图层列表表格
- 拖拽排序（HTML5 Drag & Drop API）
- 图层显隐切换
- 删除图层
- 下载图层
- 高亮选中图层

### `frontend/js/upload.js`
文件上传模块，负责：
- 文件选择对话框
- 格式校验（geojson/shp/gpkg）
- 上传进度显示
- 上传结果反馈

## 图标方案

纯内联 SVG，在 `assets/icons.svg` 中定义 SVG symbol sprite，HTML 中用 `<svg><use href="#icon-name"/></svg>` 引用。

需要的图标：
- `smart_toy` / `auto_awesome` — AI 助手
- `person` — 用户头像
- `send` — 发送
- `attach_file` / `upload` — 上传
- `download` — 下载
- `delete` — 删除
- `visibility` / `visibility_off` — 图层显隐
- `drag_indicator` — 拖拽排序
- `add` / `remove` — 缩放
- `my_location` — 定位
- `filter_list` — 筛选
- `more_vert` — 更多操作
- `description` — 文件
- `schedule` — 等待中
- `check_circle` — 成功
- `error` — 错误

## 国内 CDN 策略

所有外部资源从 `cdn.jsdelivr.net` 加载：

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.min.css"/>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.min.js"></script>
```

天地图底图瓦片 URL（需要申请 token）：
```
https://t{s}.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=您的密钥
```

同时保留 OSM 底图作为备选。

## 错误处理

每个模块均实现错误边界：
- API 调用失败 → 显示中文错误提示
- 文件格式不支持 → 前端预校验 + 后端二次校验
- 地图加载失败 → 显示占位提示
- 空状态 → 明确的空状态提示文案

## 不包含的功能

- 地理编码搜索（用户明确不需要）
- 用户认证/登录
- 实时 WebSocket
- 栅格/遥感处理（后续版本）
