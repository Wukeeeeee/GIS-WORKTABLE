<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE — 地理空间分析工作台
</p>

> 更新时间：2026-07-10

## 项目简介

GIS WorkTable 是一个基于 Web 的 GIS 数据处理可视化工作台，内置 AI 助手（DeepSeek Chat），支持自然语言交互。你可以通过对话让 AI 帮你搜索地图数据、提取建筑轮廓、处理 GIS 数据并加载到地图上。

## 核心功能

### 🤖 AI 智能对话
左侧聊天面板接入 DeepSeek Chat，支持自然语言问答和 GIS 操作指令。

### 🧰 AI 工具系统（Function Calling）

AI 可以通过以下工具自动完成 GIS 操作：

#### 搜索与抓取
- `search_web` — 通过必应搜索网络信息（无需 API Key）
- `fetch_webpage` — 基于 Playwright 的浏览器渲染抓取，支持 JS 动态页面

#### AOI 建筑轮廓查询（多数据源）
- `unified_aoi_search` — 同时查询多个地图数据源，合并返回候选列表
- `unified_aoi_extract` — 根据用户选择的数据源提取对应轮廓
- 坐标自动统一转换到 WGS-84 坐标系
- 查询结果自动缓存，同个地点第二次查询秒出

#### 文件操作
- `save_file` — 保存 GeoJSON / CSV / TXT 等文件到服务器
- `execute_python` — 执行 GIS 代码（shapely / geopandas / pyproj），结果自动加载到地图

### 🗺️ 地图功能
- **Leaflet 地图** + 必应卫星底图（WGS-84，中国 CDN 直连）
- **坐标显示** — 左下角实时显示鼠标经纬度 + WGS-84 标识
- **地图定位** — 浏览器定位 + 脉冲蓝点
- **图层管理** — 显隐控制、删除、坐标系标签
- **处理结果面板** — AI 生成的文件列表，支持单个/批量下载

### 📁 文件上传
支持 GeoJSON / Shapefile (zip) / GPKG / KML / CSV 等格式，自动加载到地图和图层面板。

## 快速开始

### 前端

直接用浏览器打开 `frontend/index.html`（或使用 Live Server）。

### 后端

```bash
# 1. 配置 DeepSeek API Key
echo "your-deepseek-api-key" > apikey.txt

# 2. 安装依赖
cd backend
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器（用于网页抓取 + AOI 提取）
playwright install chromium

# 4. 启动服务
cd ..
python -m uvicorn backend.main:app --port 8000
```

> 前端默认连接 `http://localhost:8000`，确保后端先启动。
> 后端建议不加 `--reload`，Playwright 在 Windows 热加载下存在兼容问题。

## 目录结构

```
Gis-WorkTable/
├── frontend/
│   ├── index.html              # 主页面
│   ├── css/style.css           # 全部样式
│   ├── js/
│   │   ├── api.js              # API 接口层
│   │   ├── app.js              # 应用入口
│   │   ├── map.js              # 地图模块（Leaflet）
│   │   ├── chat.js             # 聊天界面模块
│   │   ├── layers.js           # 图层管理
│   │   ├── upload.js           # 文件上传
│   │   ├── aoi.js              # 🆕 AOI 候选选择（聊天框内嵌）
│   │   └── time.js             # 时间问候
│   └── assets/icons.svg        # SVG 图标 sprite
├── backend/
│   ├── main.py                 # FastAPI 应用入口 + 路由
│   ├── requirements.txt        # Python 依赖
│   └── services/
│       ├── ai_service.py       # AI 对话服务 + Function Calling 工具系统
│       ├── baidu_aoi_service.py # 🆕 百度地图 AOI 提取（Playwright）
│       └── gaode_aoi_service.py # 🆕 高德地图 AOI 提取（Playwright）
├── cache/aoi/                  # 🆕 AOI 结果缓存（自动生成）
├── output/                     # AI 生成的文件（CSV / GeoJSON）
├── apikey.txt                  # API Key（已加入 .gitignore）
└── README.md
```

## 技术栈

- **前端**：原生 HTML + CSS（无框架）
- **地图**：Leaflet 1.9.4 + Bing 卫星底图（ditu.live.com 中国 CDN）
- **后端**：FastAPI（Python）
- **AI**：DeepSeek Chat API（OpenAI 兼容接口）
- **地图数据源**：多源地图数据查询
- **坐标转换**：transbigdata（BD09 / GCJ-02 / WGS-84 互转）
- **GIS 数据处理**：shapely + geopandas
- **搜索引擎**：必应（无需 API Key）

## 未来规划

- [ ] 空间分析工具（缓冲区、叠加分析等）
- [ ] 属性表查看与编辑
- [ ] 多图层叠加分析
- [ ] 支持栅格数据与遥感影像
- [ ] 导出 AOI 结果为 Shapefile / GeoJSON

## 免责声明

本项目仅供学习参考。地图数据可能存在误差或不准确的情况，请使用者自行甄别。
