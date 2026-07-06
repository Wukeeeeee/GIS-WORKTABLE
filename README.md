<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE
</p>

> 更新时间：2026-07-06（新增 OSM 边界提取 + 必应搜索 + Playwright 浏览器抓取 + 自动加载到地图）

## 项目简介

GIS WorkTable 是一个基于 Web 的 GIS 数据处理可视化工作台，内置 AI 助手（DeepSeek Chat），支持自然语言交互。

## 设计演进

<p align="center">
  <img src="firstDesign.jpg" alt="设计稿" width="80%">
</p>

<p align="center">
  <img src="DESIGNMD.png" alt="色彩方案" width="80%"><br>
  <a href="DESIGN.md">色彩方案配置</a>
</p>

<p align="center">
  <img src="firstHtml.png" alt="实际界面" width="80%">
</p>

利用 Google Stitch 设计界面，已完成前端界面骨架搭建及 AI 对话接入。

### 已完成功能

- **AI 智能对话** — 左侧聊天面板接入 DeepSeek Chat，支持自然语言问答
- **AI 工具系统（Function Calling）** — AI 可以调用多个 Python 工具并自动规划多步操作：

  #### 搜索与抓取
  - `search_web` — 通过必应搜索网络信息（无需 API Key）
  - `fetch_webpage` — 基于 Playwright 的浏览器渲染抓取，支持 JS 动态页面
  - 多步循环：先搜索 → 再抓取具体页面 → 分析 → 保存结果

  #### GIS 数据获取
  - `get_boundary` — 从 OpenStreetMap 获取行政边界，自动转为 GeoJSON

  #### 文件操作
  - `save_file` — 保存 GeoJSON / CSV / TXT 等文件到服务器
  - GeoJSON 文件自动加载到地图和图层面板

- **地图自动加载** — AI 生成的 GeoJSON 数据自动显示在地图上，无需手动上传
- **图层管理** — 图层列表（颜色点改色、显隐控制、删除、拖拽排序）
- **处理结果面板** — AI 生成的文件列表，支持单个下载和全部下载
- **Leaflet 地图** — Bing Maps 中国区底图（三种样式：标准/无文字/卫星），WGS84
- **地图定位** — 浏览器定位 + 脉冲蓝点显示当前位置
- **底图切换** — 按钮循环切换不同底图
- **文件上传** — 上传 GeoJSON 文件显示到地图 + 自动加入图层列表
- **对话记忆** — AI 能记住上下文，支持多轮连续对话，支持清除记忆

### 界面预览

<p align="center">
  <img src="firstHtml.png" alt="实际界面" width="80%">
</p>

## 快速开始

### 前端

直接用浏览器打开 `frontend/index.html`（或使用 Live Server）。

### 后端

```bash
# 1. 配置 API Key
echo "your-deepseek-api-key" > apikey.txt

# 2. 安装依赖
cd backend
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器（用于网页抓取）
playwright install chromium

# 4. 启动服务
cd ..
python -m uvicorn backend.main:app --port 8000
```

> 前端默认连接 `http://localhost:8000`，确保后端先启动。
> 后端不要加 `--reload`，Playwright 在 Windows 热加载下存在兼容问题。

## 目录结构

```
Gis-WorkTable/
├── frontend/
│   ├── index.html          # 主页面
│   ├── css/style.css       # 全部样式
│   ├── js/
│   │   ├── api.js          # API 接口层（前后端通信）
│   │   ├── app.js          # 应用入口
│   │   ├── map.js          # 地图模块（Leaflet）
│   │   ├── chat.js         # 聊天界面模块
│   │   ├── layers.js       # 图层管理
│   │   ├── upload.js       # 文件上传
│   │   └── time.js         # 时间问候
│   └── assets/icons.svg    # SVG 图标 sprite
├── backend/
│   ├── main.py             # FastAPI 应用入口
│   ├── requirements.txt    # Python 依赖
│   └── services/
│       └── ai_service.py   # AI 对话服务 + Function Calling 工具系统
├── output/                 # AI 生成的文件（CSV/GeoJSON）
├── apikey.txt              # API Key（已加入 .gitignore）
├── DESIGN.md               # 色彩方案文档
└── README.md
```

## 技术栈

- **前端**：原生 HTML + CSS（无框架）
- **地图**：Leaflet 1.9.4 + Bing Maps 中国区底图
- **后端**：FastAPI（Python）
- **AI**：DeepSeek Chat API（OpenAI 兼容接口）
- **浏览器自动化**：Playwright（网页抓取、JS 渲染）
- **GIS 数据处理**：osmnx（OpenStreetMap 数据获取）
- **搜索引擎**：必应（无需 API Key）
- **图标**：纯内联 SVG symbol sprite

## 未来规划

- [ ] 更多 OSM 数据查询（道路、河流、建筑物等）
- [ ] 空间分析工具（缓冲区、叠加分析等）
- [ ] 坐标投影转换
- [ ] 属性表查看与编辑
- [ ] 多图层叠加分析
- [ ] 支持栅格数据与遥感影像

## 免责声明

本项目使用 Bing Maps 中国区（ditu.live.com）作为默认底图。地图数据由 Microsoft 必应地图提供，数据可能存在误差或不准确的情况，请使用者自行甄别。本项目中地图仅供学习参考，不构成任何专业的地理信息依据。
