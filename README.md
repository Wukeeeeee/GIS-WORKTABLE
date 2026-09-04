<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  <b>Web GIS 数据处理与可视化工作台</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Leaflet-199900?style=flat-square&logo=leaflet&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-2B6CB0?style=flat-square" />
  <img src="https://img.shields.io/badge/License-AGPL%20v3-1a1a2e?style=flat-square" />
  <img src="https://img.shields.io/badge/Tests-238%20passed-2ea44f?style=flat-square" />
</p>

---

基于 Web 的 GIS 数据处理与可视化工作台，内置 AI Agent（LangGraph ReAct），支持通过自然语言对话驱动地图操作、空间分析、栅格处理和第三方数据加载。

## 截图

暂无。

## 快速开始

**环境要求**: Python 3.10+, pip

```bash
# 克隆项目
git clone <repo-url>
cd Gis-WorkTable

# 安装后端依赖
cd backend
pip install -r requirements.txt

# 启动服务
cd ..
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

打开浏览器访问 `http://localhost:8000`。

首次使用需在右上角设置中配置 AI API Key（支持 GLM / DeepSeek / Agnes），配置后即可通过自然语言对话操作 GIS。

## 功能

### 数据加载

支持 GeoJSON、Shapefile（ZIP 压缩包）、GeoPackage、KML、KMZ、GPX、DXF、GeoTIFF、CSV（经纬度转点）格式上传。GeoTIFF 自动渲染为栅格底图叠加。

### 图层面板

浮动面板支持图层显隐、排序、分组、重命名、删除。右键菜单提供快捷操作。支持独立颜色、透明度、线宽设置，面要素可选斜线/网格/点阵填充样式。

### 符号化

分级设色（6 种色带可选）、唯一值渲染、属性标注（tooltip）、图例卡片。

### 属性表

弹出面板展示属性数据，支持排序筛选、CSV 导出、字段统计、按属性选择、字段计算、添加/删除字段、属性值编辑。

### 绘制与编辑

点/线/面/矩形/圆绘制，折点编辑，捕捉（自动吸附顶点和线段），撤销/重做（最大 50 步）。测距与测面积。

### 要素操作（自然语言可调用）

移动、旋转、缩放、缓冲区、分割、合并、删除要素。

### 空间分析

缓冲区（单环/多环）、相交、合并、裁剪、差异、质心、简化、融合（Dissolve）、空间连接、图层拆分/合并、空间选择、随机采样、邻近查找、DBSCAN 聚类、泰森多边形、字段统计、反向地理编码、批量地理编码。

### 网络分析

基于 OSMnx 的路网分析。面板支持最短路径（途经点 + 方向箭头）、服务区（多级断值）、最近设施（混合选点）。AI 可通过自然语言自动完成"下载路网 → 分析 → 加载结果"全流程。

### 栅格分析

| 类别 | 功能 |
|------|------|
| DEM 地形 | 坡度、坡向、山体阴影（Horn 公式，NumPy 实现，不依赖 GDAL） |
| 提取 | 等高线（scikit-image）、水文分析（D8 填洼 → 流向 → 汇流累积 → 河网） |
| 计算 | NDVI、栅格计算器（波段算术 + 数学函数） |
| 插值 | IDW（反距离加权）、RBF（径向基函数） |
| 裁剪 | 用矢量面裁剪栅格（rasterio.mask） |

### 制图导出

图例、比例尺、指北针。图片导出（PNG/JPEG）、PDF 出图（A4 横向）、Shapefile 导出（ZIP）、GeoPackage 导出、CSV 导出。

### 拓扑检查

面图层拓扑错误检测：自相交、无效几何、要素间重叠、缝隙。结果生成标注图层。

### 3D 地形

Three.js 嵌入 HTML，展示 DEM 三维地形，支持夸张系数调节。

### 时序动画

按时间字段逐帧播放图层要素变化。

### 图表联动

柱状图、饼图、折线图、散点图。选中要素高亮图表，点击图表聚焦要素。

### AI Agent 系统

- **80+ 工具**：通过 `@tool` 装饰器注册，覆盖空间分析、栅格处理、数据加载、网络分析、制图导出等全流程
- **Provider 列表化**：支持任意 OpenAI 兼容接口（内置 deepseek / 智谱GLM / agnes / OpenRouter GLM-5.2 / 自定义空模板），Key 只存浏览器 localStorage，加模型 = 设置里加一行
- **Reasoning 推理**：Provider 可开关 reasoning；开启时思考过程不进正文，完成后以可折叠「思考过程」块展示，并支持跨轮/工具循环续推回传
- **LangGraph ReAct Agent**：自动管理多轮工具调用循环，替代手写 if/elif 路由
- **技能路由系统**：按 Provider 开关可选，自动加载 `skills/` 目录下的技能文档辅助任务
- **SSE 流式响应**：前端实时展示工具调用进度
- **沙箱代码执行**：AST 白名单验证 + 安全 eval，支持数学表达式和受控 Python 执行

### 第三方数据

- 高德地图：POI 搜索、地理编码
- DataV：行政区划边界
- 百度地图：AOI 建筑轮廓（Playwright 自动化提取）
- OSM：路网下载与分析
- 热力图

### 开放数据发现与获取（Data Discovery）

通过自然语言发现并获取公开 GIS 数据，走确定性 Provider 代码（LLM 只负责解析需求，不直接访问互联网）：

```
用户需求 → 数据类型/空间范围识别 → 选择 Provider → 搜索(元信息) → 下载 → GIS 文件(GeoJSON/GPKG/SHP)
       → 完整性 + CRS 校验 → metadata → 加载到地图
```

| Provider | 数据 | 认证 | 阶段 |
|----------|------|------|------|
| OpenStreetMap（Overpass 官方 API） | 道路 / 建筑 / POI / 水系 / 土地利用 / 交通 | 公开免认证 | ✅ 已可用（含下载） |
| Copernicus Data Space | Sentinel 遥感影像等 | ESA 账号（OAuth token） | 🔍 发现/元信息（下载待下阶段） |
| USGS | Landsat（landsatlook STAC） | 目录匿名可发现，下载需账号 | 🔍 发现/元信息（下载待下阶段） |
| 地理空间数据云 | DEM / Landsat / MODIS | 需注册登录 | 🔍 仅指引（不自动抓取） |

**认证分级**：公开免认证（OSM）/ 需 API Key（走环境变量，不写进项目）/ 需账号授权（提供指引，密码不硬编码）。

对话示例：`帮我找长沙市的道路数据` → 返回 `Provider/类型/格式/区域/来源/状态` → `获取数据` → 文件落盘 + metadata → `加载到地图`。

**API**：`GET /api/data/providers`、`POST /api/data/discover`、`POST /api/data/download`。

### 工程管理

自动保存、手动保存/加载、重命名、导出/导入工程。

## 技术栈

| 类别 | 技术 |
|------|------|
| 前端 | HTML + CSS + JavaScript（原生） |
| 地图渲染 | Leaflet + Leaflet.Draw |
| 后端 | FastAPI + Python |
| AI 框架 | LangGraph（ReAct Agent）+ LangChain Tools |
| LLM | 任意 OpenAI 兼容接口（GLM-4.7-Flash+ / DeepSeek V4 / GLM-5.2 via OpenRouter / 自定义） |
| GIS | GeoPandas + Shapely + PyProj + Rasterio |
| 栅格处理 | NumPy + scikit-image + Matplotlib |
| 网络分析 | OSMnx + NetworkX |
| 网页抓取 | Playwright + scrapling + markdownify |

## 项目结构

```
Gis-WorkTable/
├── frontend/                    # 前端
│   ├── index.html               # 主页面（SPA，菜单栏 + 绘图工具栏 + 图层面板）
│   ├── css/style.css            # 样式表
│   ├── js/
│   │   ├── app.js               # 应用初始化
│   │   ├── chat.js              # AI 对话 + 斜杠命令面板
│   │   ├── map.js               # 地图控制 + 菜单栏交互
│   │   ├── layers.js            # 图层面板 + 符号化控制
│   │   ├── api.js               # API 通信层
│   │   ├── upload.js            # 文件上传处理
│   │   ├── settings.js          # 设置弹窗
│   │   ├── network.js           # 网络分析面板
│   │   ├── spatial.js           # 空间分析面板
│   │   ├── aoi.js               # AOI 交互
│   │   ├── debug.js             # 调试面板
│   │   ├── project.js           # 工程持久化
│   │   ├── task.js              # 任务管理
│   │   └── time.js              # 时序动画
│   ├── assets/                  # 图标和 Logo
│   └── samples/                 # 示例 GeoJSON 数据
│
├── backend/                     # 后端
│   ├── main.py                  # FastAPI 入口（路由、上传、工程管理）
│   ├── requirements.txt         # Python 依赖
│   ├── services/
│   │   ├── tools.py             # 核心工具集（80+ @tool 函数，~4900 行）
│   │   ├── data_discovery.py    # 开放数据发现入口（发现/下载/导入调度）
│   │   ├── data_providers/      # 数据 Provider 抽象与实现
│   │   │   ├── base.py          #   DataProvider ABC + 注册表 + 能力列表
│   │   │   ├── models.py        #   数据模型（DataRequest/DataHit/Asset）
│   │   │   ├── errors.py        #   明确错误类型（禁静默失败）
│   │   │   ├── http.py          #   统一 HTTP：超时/受限重试/大小上限
│   │   │   ├── storage.py       #   GIS 文件落盘 + CRS + metadata
│   │   │   ├── osm_provider.py  #   OpenStreetMap（Overpass 官方 API）
│   │   │   ├── copernicus_provider.py  # Copernicus Data Space
│   │   │   ├── usgs_provider.py        # USGS Landsat（STAC）
│   │   │   └── gscloud_provider.py     # 地理空间数据云（指引）
│   │   ├── graph.py             # LangGraph ReAct Agent 构建
│   │   ├── ai_service.py        # AI 服务层（LLM 调用、历史管理、技能路由）
│   │   ├── network_service.py   # 网络分析（OSMnx + NetworkX）
│   │   ├── amap_service.py      # 高德 POI / 地理编码
│   │   ├── baidu_aoi_service.py # 百度 AOI 建筑轮廓
│   │   ├── datav_service.py     # DataV 行政边界
│   │   ├── geo_coords.py        # 坐标工具函数
│   │   ├── layer_service.py     # 图层检查
│   │   ├── project_service.py   # 工程 CRUD
│   │   └── log_service.py       # 日志
│   └── tests/
│       ├── test_spatial_tools.py   # 空间分析工具测试
│       ├── test_network.py         # 网络分析测试
│       ├── test_coverage_gap.py    # 覆盖率补充测试
│       ├── test_llm_config.py      # LLM 配置测试
│       └── test_data_discovery.py  # 开放数据发现/获取测试
│
├── skills/                      # AI 技能文档（12 个领域）
├── data/                        # 示例路网数据
├── goal/                        # 项目目标与更新日志
├── study/                       # 学习笔记与示例代码
├── scripts/                     # 辅助脚本
├── docs/                        # 设计文档
├── test_data/                   # 测试数据（KML/GPX）
└── test/                        # 测试计划
```

## API

核心 API 端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 非流式 AI 对话 |
| POST | `/api/chat/stream` | SSE 流式 AI 对话 |
| POST | `/api/cancel` | 取消当前 AI 请求 |
| POST | `/api/upload` | 文件上传（GeoJSON/SHP/GPKG/KML/GPX/DXF/GeoTIFF/CSV） |
| GET | `/api/layers` | 获取已注册图层列表 |
| POST | `/api/layer/inspect` | 图层数据检查 |
| POST | `/api/layer/export-shp` | 导出 Shapefile |
| POST | `/api/network/snap` | 路网点吸附 |
| POST | `/api/network/solve` | 网络分析求解 |
| GET | `/api/boundary` | 获取行政边界 |
| GET | `/api/data/providers` | 列出开放数据源及其能力/认证 |
| POST | `/api/data/discover` | 数据发现（返回各源元信息） |
| POST | `/api/data/download` | 获取数据 → GIS 文件 → 注册图层 |
| GET/POST | `/api/projects` | 工程列表/创建 |
| POST | `/api/projects/auto-save` | 自动保存 |
| GET | `/api/version` | 版本信息 |
| DELETE | `/api/chat/memory` | 清空对话历史 |
| POST | `/api/test-key` | 通用测速（入参即 Provider 的 `llm_config`） |

## 运行测试

```bash
python -m pytest backend/tests/ -v
```

当前 291 个测试全部通过（原 263 + 开放数据发现/获取 28）。

## 已知限制

- `requirements.txt` 未完整列出所有运行时依赖（`rasterio`、`scipy`、`scikit-image`、`pyproj`、`langchain`、`langgraph`、`pyogrio`、`Pillow`、`networkx`、`requests` 等在代码中使用但未声明），安装后可能需要手动补装
- 无 Docker 配置，无 CI/CD 流水线
- API Key 由前端「AI 模型」设置面板的 Provider 列表管理，存浏览器 localStorage、随请求携带即用即弃；后端不再读 `apikey.txt` / `glm_apikey.txt` 兜底
- 前端为原生 HTML/CSS/JS，无构建工具和包管理
- 部分高级功能（时序动画、图表联动）的前端交互仍在迭代中
- 临时文件（`cache/`、`uploads/`、`logs/`、`output/`）在运行时自动生成，已通过 `.gitignore` 排除

## 许可证

[AGPL v3](LICENSE) -- 可自由使用和修改，但分发时需提供源码。
