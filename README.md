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
左侧聊天面板接入 DeepSeek Chat，支持自然语言问答和 GIS 操作指令。每次问答自动记录到日志，方便复查。

### 🧰 AI 工具系统（Function Calling，共 15 个工具）

AI 可以通过以下工具自动完成 GIS 操作：

#### 🗺️ 行政区划边界（DataV）
- `datav_boundary` — 从阿里云 DataV 获取省/市/区三级边界，自动 GCJ-02→WGS-84 转换，国内直连
- 支持：广东省、广州市、天河区 三级

#### 🔍 搜索与抓取
- `search_web` — 通过必应搜索网络信息（无需 API Key）
- `fetch_webpage` — 基于 Playwright 的浏览器渲染抓取，支持 JS 动态页面

#### 🏗️ AOI 建筑轮廓查询（多数据源）
- `unified_aoi_search` — 同时查询百度+高德地图源，合并返回候选列表
- `unified_aoi_extract` — 根据用户选择的数据源提取对应轮廓
- 坐标自动统一转换到 WGS-84 坐标系
- 查询结果自动缓存，同个地点第二次查询秒出

#### 📂 文件操作
- `save_file` — 保存 GeoJSON / CSV / TXT 等文件到服务器

#### 💻 GIS 代码执行
- `execute_python` — 执行 GIS 代码（shapely / geopandas / pyproj），结果自动加载到地图
- 支持多行 JSON 解析（漂亮打印的 GeoJSON 也能识别）
- 自动注册到图层系统供后续查询

#### 📋 图层查询与管理
- `get_registered_layers` — 查看当前地图上所有图层（名称、要素数、几何类型）
- `get_layer_detail("图层名")` — 查看某个图层的详细 GeoJSON 数据预览
- `clear_layers` — 清空地图上所有图层，释放内存

#### 📜 日志查询
- `get_session_logs(n)` — 查看最近 n 次问答记录（含消息、回复、图层信息）

### 🗺️ 地图功能
- **Leaflet 地图** + 必应卫星底图（WGS-84，中国 CDN 直连）
- **坐标显示** — 左下角实时显示鼠标经纬度 + WGS-84 标识
- **地图定位** — 浏览器定位 + 脉冲蓝点
- **图层管理** — 显隐控制、删除、颜色自定义、拖拽排序、坐标系标签
- **翻牌计时器** — AI 思考时显示实时计时器（数字翻转动画效果）
- **多图层同时加载** — AI 一次生成多个图层时，逐个独立加载到图层面板

### 📁 文件上传
支持 GeoJSON / Shapefile (zip) / GPKG / KML / CSV 等格式，自动加载到地图和图层面板。

### 📊 双轨日志系统
- **temp.jsonl**（临时日志）— 每次问答详细记录：用户消息、AI回复、图层信息、属性预览、工作区文件快照。新建会话时自动清空
- **permanent.jsonl**（永久日志）— 只记录有问题的结果（AI报错、数据加载失败、提取失败），长期保存不删除

### 🔄 对话记忆持久化
- 对话历史保存到文件（cache/history/），后端重启不丢失
- 新建会话自动清除记忆 + 图层 + GeoJSON 缓存

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

# 3. 安装 Playwright 浏览器（用于 AOI 提取）
playwright install chromium

# 4. 启动服务
cd ..
python -m uvicorn backend.main:app --port 8000
```

> 前端默认连接 `http://localhost:8000`，确保后端先启动。
> 后端建议不加 `--reload`，Playwright 在 Windows 热加载下存在兼容问题。

## 技术栈

- **前端**：原生 HTML + CSS（无框架）
- **地图**：Leaflet 1.9.4 + Bing 卫星底图（ditu.live.com 中国 CDN）
- **后端**：FastAPI（Python）
- **AI**：DeepSeek Chat API（OpenAI 兼容接口）
- **行政区划数据**：阿里云 DataV（国内可访问，无需翻墙）
- **建筑轮廓数据**：百度地图 + 高德地图 双源查询
- **坐标转换**：多坐标系自动统一转 WGS-84
- **GIS 数据处理**：shapely + geopandas
- **搜索引擎**：必应（无需 API Key）

## 项目结构

```
├── frontend/          # 前端页面（HTML / CSS / JS）
│   ├── index.html     # 主页面
│   ├── css/style.css  # 样式
│   └── js/            # JS 模块
│       ├── api.js     # API 接口层
│       ├── map.js     # Leaflet 地图封装
│       ├── chat.js    # 聊天模块 + 翻牌计时器
│       ├── layers.js  # 图层管理面板
│       ├── upload.js  # 文件上传
│       └── aoi.js     # AOI 选择交互
├── backend/           # 后端服务
│   ├── main.py        # FastAPI 入口
│   └── services/
│       ├── ai_service.py    # AI 对话 + 工具系统（15个工具）
│       ├── datav_service.py # DataV 行政区划获取
│       ├── log_service.py   # 双轨日志（temp + permanent）
│       ├── gaode_aoi_service.py  # 高德地图 AOI 提取
│       └── baidu_aoi_service.py # 百度地图 AOI 提取
├── output/            # AI 生成的文件
├── cache/             # 缓存（AOI + 对话历史）
└── logs/              # 日志
    ├── temp.jsonl      # 临时日志（每次问答详细记录）
    └── permanent.jsonl # 永久日志（只记有问题的结果）
