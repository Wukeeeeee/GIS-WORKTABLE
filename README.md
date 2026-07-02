<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE
</p>

> 更新时间：2026-07-02

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
- **对话记忆** — AI 能记住上下文，支持多轮连续对话
- **GIS 问答** — 回答地理信息、地图、空间分析相关问题
- **Leaflet 地图** — Bing Maps 中国区底图（国内最快，WGS84），可选 Carto / OSM / 地形图 / 卫星图
- **图层管理** — 图层列表（拖拽排序、显隐、删除）
- **文件上传** — 上传交互与格式校验（`.geojson` / `.shp` / `.gpkg` 等）
- **处理结果展示** — 右侧结果面板

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

# 3. 启动服务
cd ..
python -m uvicorn backend.main:app --reload --port 8000
```

> 前端默认连接 `http://localhost:8000`，确保后端先启动。

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
│   │   └── upload.js       # 文件上传
│   └── assets/icons.svg    # SVG 图标 sprite
├── backend/
│   ├── main.py             # FastAPI 应用入口
│   ├── requirements.txt    # Python 依赖
│   └── services/
│       └── ai_service.py   # AI 对话服务（DeepSeek）
├── apikey.txt              # API Key（已加入 .gitignore）
├── DESIGN.md               # 色彩方案文档
└── README.md
```

## 技术栈

- **前端**：原生 HTML + CSS（无框架）
- **地图**：Leaflet 1.9.4 + Bing Maps 中国区底图（可选 Carto / OSM / 地形图 / 卫星图）
- **后端**：FastAPI（Python）
- **AI**：DeepSeek Chat API（OpenAI 兼容接口）
- **图标**：纯内联 SVG symbol sprite

## 未来规划

- [ ] AI 智能体（Function Calling）— AI 直接操作 GIS 数据
- [ ] 文件上传后端接入
- [ ] 多图层叠加分析
- [ ] 属性表查看与编辑
- [ ] 坐标系投影转换
- [ ] 结果导出（GeoJSON / Shapefile）
- [ ] 支持栅格数据与遥感影像

## 免责声明

本项目使用 OpenStreetMap 作为默认底图。OSM 数据由全球用户贡献，部分国家、地区边界及地理信息的表述可能与官方承认的边界存在不一致，请使用者自行甄别。如需更准确的国内地图数据，建议申请天地图 API 密钥并在 `map.js` 中切换底图源。
