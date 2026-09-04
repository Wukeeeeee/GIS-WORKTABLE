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
  <img src="https://img.shields.io/badge/Tests-340%20passed-2ea44f?style=flat-square" />
</p>

> 🚧 **项目持续开发中**，可能存在 Bug。功能与接口会随迭代调整。

---

基于 Web 的 GIS 数据处理与可视化工作台，内置 AI Agent（LangGraph ReAct），支持通过自然语言对话驱动地图操作、空间分析、栅格处理、网络分析和第三方数据加载。前端为原生 HTML/CSS/JS，后端为 FastAPI。

> ⚠️ **使用前必须在页面左下角 ⚙️ 齿轮按钮中配置 AI API Key**（浏览器会自动保存到 localStorage）。未配置 Key 前，AI 对话与联网功能不可用。

## 截图

暂无（项目中暂无真实截图资源）。

## 快速开始

**环境要求**: Python 3.10+, pip

### 方式一：AI 辅助部署（推荐）

复制下面这段指令发给任意 AI 编程助手即可完成克隆、装依赖、启动：

```
https://github.com/Wukeeeeee/GIS-WORKTABLE.git 请帮我在本地部署好这个项目
```

### 方式二：手动部署

```bash
# 克隆项目
git clone https://github.com/Wukeeeeee/GIS-WORKTABLE.git
cd Gis-WorkTable

# 安装后端依赖
cd backend
pip install -r requirements.txt

# 启动服务
cd ..
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

打开浏览器访问 `http://localhost:8000`。首次使用在左下角 ⚙️ 设置中配置 AI API Key 即可通过自然语言对话操作 GIS。

## 功能

### 核心功能（`/` 分隔）

```
数据加载 / 图层面板 / 符号化 / 属性表 / 绘制与编辑 / 要素操作 / 空间分析 / 网络分析 /
栅格分析 / 制图导出 / 拓扑检查 / 3D 地形 / 时序动画 / 图表联动 / AI Agent / 第三方数据 / 工程管理
```

### 数据加载

支持 GeoJSON、Shapefile（ZIP 压缩包）、GeoPackage、KML、KMZ、GPX、DXF、GeoTIFF、CSV（经纬度转点）格式上传。GeoTIFF 自动渲染为栅格底图叠加（`/api/upload`，见 `backend/main.py`）。

### 图层面板

浮动面板支持图层显隐、排序、分组、重命名、删除；右键菜单提供快捷操作；支持独立颜色、透明度、线宽设置，面要素可选斜线/网格/点阵填充样式。

### 符号化

分级设色、唯一值渲染、属性标注（tooltip）、图例卡片。

### 属性表

弹出面板展示属性数据，支持排序筛选、CSV 导出、字段统计、按属性选择、字段计算、添加/删除字段、属性值编辑。

### 绘制与编辑

点/线/面/矩形/圆绘制，折点编辑，捕捉（自动吸附顶点和线段），撤销/重做，测距与测面积。

### 要素操作（自然语言可调用）

移动、旋转、缩放、缓冲区、分割、合并、删除要素。

### 空间分析

缓冲区（单环/多环）、相交、合并、裁剪、差异、质心、简化、融合（Dissolve）、空间连接、图层拆分/合并、空间选择、随机采样、邻近查找、DBSCAN 聚类、泰森多边形、字段统计、反向地理编码、批量地理编码。

### 网络分析

基于 OSMnx 的路网分析。支持最短路径（途经点）、服务区（多级断值）、最近设施。AI 可通过自然语言自动完成「下载路网 → 分析 → 加载结果」全流程。

### 栅格分析

| 类别 | 功能 |
|------|------|
| DEM 地形 | 坡度、坡向、山体阴影（NumPy 实现） |
| 提取 | 等高线、水文分析（D8 填洼 → 流向 → 汇流累积 → 河网） |
| 计算 | NDVI、栅格计算器（波段算术 + 数学函数） |
| 插值 | IDW（反距离加权）、RBF（径向基函数） |
| 裁剪 | 用矢量面裁剪栅格（rasterio） |

### 制图导出

图例、比例尺、指北针、图片导出（PNG/JPEG）、PDF 出图、Shapefile 导出（ZIP）、GeoPackage / CSV 导出。

### 拓扑检查

面图层拓扑错误检测：自相交、无效几何、要素间重叠、缝隙，结果生成标注图层。

### 3D 地形

Three.js 嵌入 HTML，展示 DEM 三维地形，支持夸张系数调节。

### 时序动画

按时间字段逐帧播放图层要素变化。

### 图表联动

柱状图、饼图、折线图、散点图；选中要素高亮图表，点击图表聚焦要素。

### AI Agent 系统

- **85 个工具**（`backend/services/tools.py`，约 5300 行）：经 `@tool` 装饰器注册，覆盖空间分析、栅格处理、数据加载、网络分析、制图导出等全流程
- **Provider 列表化**：后端不硬编码模型名，统一用一份 `LLMConfig`（`llm_config.py`），任意 OpenAI 兼容接口可用；Key 只存浏览器 localStorage，加模型 = 设置里加一行
- **Reasoning 推理**：Provider 可开关 reasoning；开启时思考过程不进正文，完成后以可折叠「思考过程」块展示，并支持跨轮/工具循环续推回传
- **LangGraph ReAct Agent**：自动管理多轮工具调用循环，替代手写 if/elif 路由
- **技能路由系统**：按 Provider 开关可选，自动加载 `skills/` 目录下的 12 个技能文档辅助任务
- **SSE 流式响应**：前端实时展示工具调用进度
- **沙箱代码执行**：AST 白名单验证，支持安全表达式求值（`_safe_expr_eval`）与受控 Python 执行（`execute_python`）

### Task Working Memory（任务工作记忆）

为跨轮对话保持任务状态而设计，`backend/services/task_manager.py` 实现，每个 Session 自动关联一个活跃 Task：

- **Task 生命周期**：create / update / archive / restore / delete
- **Python 源码缓存（Code Cache）**：每次 `execute_python` 自动保存 `step_XXX.py` + `latest.py`
- **Artifact Registry**：PNG / GeoJSON 等输出文件注册追踪（校验真实存在）
- **Execution Log**：每次执行记录 source / status / stdout / stderr / artifacts
- **Context Builder**：把最新代码 + Artifact + 执行历史自动注入 LLM System Prompt，让 Agent「记得」上一轮干了什么

### 第三方数据

- 高德地图：POI 搜索、地理编码
- DataV：行政区划边界
- 百度地图：AOI 建筑轮廓
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
| OpenStreetMap（Overpass 官方 API） | 道路 / 建筑 / POI / 水系 / 土地利用 / 交通 | 公开免认证 | ✅ 已实现（含下载） |
| Copernicus Data Space | Sentinel 遥感影像等 | ESA 账号（OAuth token） | 🔍 部分实现（发现/元信息，下载待下阶段） |
| USGS | Landsat（landsatlook STAC） | 目录匿名可发现，下载需账号 | 🔍 部分实现（发现/元信息，下载待下阶段） |
| 地理空间数据云 | DEM / Landsat / MODIS | 需注册登录 | 🔍 实验性（仅指引，不自动抓取） |

**认证分级**：公开免认证（OSM）/ 需 API Key（走环境变量）/ 需账号授权（提供指引，不硬编码密码）。

**API**：`GET /api/data/providers`、`POST /api/data/discover`、`POST /api/data/download`。

### 工程管理

自动保存、手动保存/加载、重命名、导出/导入工程（`.giswork` 压缩包）。

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│  前端（原生 HTML/CSS/JS，Leaflet 地图）                        │
│  上传 → 设置(Provider) → 对话(SSE) → 面板操作 → 工程管理         │
└───────────────▲───────────────────────────┬──────────────────┘
                │  /api/* (FastAPI)         │ 静态文件 /output
┌───────────────┴───────────────────────────▼──────────────────┐
│  后端 FastAPI（main.py）                                       │
│   └── ai_service.py      对话编排 / 历史 / 技能路由 / 上下文注入  │
│        └── graph.py      LangGraph ReAct Agent 循环            │
│             └── tools.py 85 个 @tool（图层/空间/栅格/网络/AOI…）  │
│                  └── execute_python（AST 沙箱）                 │
│   ├── task_manager.py   Task Working Memory（源码缓存/Artifact）│
│   ├── data_discovery.py + data_providers/  确定性数据发现/下载   │
│   ├── network_service.py  OSMnx 网络分析                        │
│   ├── amap / baidu / datav_service.py   第三方数据              │
│   ├── llm_config.py     统一 Provider 配置 + Reasoning          │
│   └── project_service.py 工程持久化                             │
└──────────────────────────────────────────────────────────────┘
```

### 核心工作流（一轮 AI 对话）

```
用户消息 + (附图层 GeoJSON) + llm_config + session_id + task_id
        │
        ▼
FastAPI /api/chat/stream（SSE）
        │
        ▼
ai_service：查/建会话历史 → 技能路由 → 构建 System Prompt
        │   （注入 Task 上下文：最新代码 + Artifact + 执行历史）
        ▼
graph.run_agent_stream：LangGraph ReAct 循环
        │   工具调用 → tools.py 处理 → 图层注册/文件落盘/Artifact 登记
        ▼
done 事件：回复写回历史 → 返回 layers / images / reasoning / task_id
        │
        ▼
前端渲染图层 + 折叠「思考过程」+ 保存工程
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 前端 | HTML + CSS + JavaScript（原生，无构建工具） |
| 前端设计 | Google Stitch 风格 · [`DESIGN.md`](DESIGN.md) |
| 地图渲染 | Leaflet + Leaflet.Draw |
| 后端 | FastAPI + Python |
| AI 框架 | LangGraph（ReAct Agent）+ LangChain Tools |
| LLM | 任意 OpenAI 兼容接口（内置 [DeepSeek 开放平台](https://platform.deepseek.com/)、[智谱开放平台](https://open.bigmodel.cn/) 默认项，可自定义） |
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
│   │   ├── settings.js          # 设置弹窗（Provider 配置）
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
│   ├── main.py                  # FastAPI 入口（路由、上传、工程、Task 管理）
│   ├── requirements.txt         # Python 依赖（已含 LangGraph 1.x + GIS 数据科学栈）
│   ├── services/
│   │   ├── tools.py             # 核心工具集（85 个 @tool 函数，~5300 行）
│   │   ├── graph.py             # LangGraph ReAct Agent 构建
│   │   ├── ai_service.py        # AI 服务层（对话、历史、技能路由、上下文注入）
│   │   ├── llm_config.py        # 统一 Provider 配置 + Reasoning 薄适配
│   │   ├── task_manager.py      # Task Working Memory（Task/源码缓存/Artifact）
│   │   ├── pending_action.py    # 确定性「继续/确认」短指令
│   │   ├── data_discovery.py    # 开放数据发现入口（发现/下载/导入调度）
│   │   ├── data_providers/      # 数据 Provider 抽象与实现
│   │   │   ├── base.py          #   DataProvider ABC + 注册表
│   │   │   ├── models.py        #   数据模型（DataRequest/DataHit/Asset）
│   │   │   ├── errors.py        #   明确错误类型（禁静默失败）
│   │   │   ├── http.py          #   统一 HTTP：超时/受限重试/大小上限
│   │   │   ├── storage.py       #   GIS 文件落盘 + CRS + metadata
│   │   │   ├── osm_provider.py  #   OpenStreetMap（Overpass 官方 API）
│   │   │   ├── copernicus_provider.py  # Copernicus Data Space
│   │   │   ├── usgs_provider.py        # USGS Landsat（STAC）
│   │   │   ├── gscloud_provider.py     # 地理空间数据云（指引）
│   │   │   └── geocode.py       #   地理编码
│   │   ├── network_service.py   # 网络分析（OSMnx + NetworkX）
│   │   ├── amap_service.py      # 高德 POI / 地理编码
│   │   ├── baidu_aoi_service.py # 百度 AOI 建筑轮廓
│   │   ├── datav_service.py     # DataV 行政边界
│   │   ├── geo_coords.py        # 坐标工具函数
│   │   ├── layer_service.py     # 图层检查
│   │   ├── project_service.py   # 工程 CRUD
│   │   └── log_service.py       # 日志
│   └── tests/                   # pytest 测试（7 个文件，340 例通过）
│       ├── test_spatial_tools.py      # 空间分析工具测试（192 例）
│       ├── test_coverage_gap.py       # 覆盖率补充测试
│       ├── test_data_discovery.py     # 开放数据发现/获取测试
│       ├── test_llm_config.py         # LLM 配置测试
│       ├── test_multi_turn_state.py   # 多轮状态测试
│       ├── test_network.py            # 网络分析测试
│       └── test_task_manager.py       # Task Manager 测试
│
├── skills/                      # AI 技能文档（12 个领域：analysis/geometry/amap/…）
├── data/                        # 示例路网数据
├── DESIGN.md                    # 设计系统文档
├── CLAUDE.md / WORKFLOW.md / CURRENT   # Claude Code 工作流
├── docs/                        # 设计文档
├── scripts/                     # 辅助脚本
└── test_data/                   # 测试数据（KML/GPX）
```

## API

核心 API 端点（均在 `backend/main.py`）：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 非流式 AI 对话 |
| POST | `/api/chat/stream` | SSE 流式 AI 对话 |
| POST | `/api/cancel` | 取消当前 AI 请求 |
| DELETE | `/api/chat/memory` | 清空对话历史 |
| POST | `/api/test-key` | 通用测速（入参即 Provider 的 `llm_config`） |
| POST | `/api/upload` | 文件上传（GeoJSON/SHP/GPKG/KML/GPX/DXF/GeoTIFF/CSV） |
| GET | `/api/layers` | 获取已注册图层列表 |
| POST | `/api/layer/inspect` | 图层数据检查 |
| POST | `/api/layer/register` / `/unregister` | 图层注册 / 取消注册 |
| POST | `/api/layer/export-shp` | 导出 Shapefile |
| POST | `/api/reset_state` | 重置后端状态 |
| GET/POST | `/api/session_logs` | 会话执行日志 |
| POST | `/api/network/snap` | 路网点吸附 |
| POST | `/api/network/solve` | 网络分析求解 |
| GET | `/api/boundary` | 获取行政边界 |
| GET | `/api/data/providers` | 列出开放数据源及其能力/认证 |
| POST | `/api/data/discover` | 数据发现（返回各源元信息） |
| POST | `/api/data/download` | 获取数据 → GIS 文件 → 注册图层 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}` | 任务详情（含源码/Artifact/执行日志） |
| GET | `/api/tasks/{id}/code` | 获取任务 Python 源码 |
| POST | `/api/tasks/{id}/archive` / `/restore` | 归档 / 恢复任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| GET/POST | `/api/projects` | 工程列表/创建 |
| GET/POST/DELETE | `/api/projects/{id}` | 工程读取/删除，含 `/rename` `/export` |
| POST | `/api/projects/auto-save` / `import` | 自动保存 / 导入工程 |
| GET | `/api/version` / `/api/health` | 版本 / 健康检查 |

## 运行测试

```bash
python -m pytest backend/tests/ -v
```

实测当前 **340 个测试全部通过**（`340 passed`）。

## 已知限制

- 无 Docker 配置，无 CI/CD 流水线
- API Key 由前端「AI 模型」设置面板的 Provider 列表管理，存浏览器 localStorage、随请求携带即用即弃；后端不再读 `apikey.txt` 兜底
- 前端为原生 HTML/CSS/JS，无构建工具和包管理，生产部署需依赖 FastAPI 静态托管
- 部分高级功能（时序动画、图表联动）的前端交互仍在迭代中
- 开放数据源的认证模型不同：OSM 免认证、Copernicus/USGS 需账号（当前仅发现/元信息阶段）、地理空间数据云仅指引
- 临时文件（`cache/`、`uploads/`、`logs/`、`output/`）在运行时自动生成，已通过 `.gitignore` 排除

## 后续可优化方向

- 将依赖从 `requirements.txt` 迁移到 `pyproject.toml`（LangGraph 已锁定在 1.x）
- 补充 Docker / docker-compose 与 CI 流水线
- 将 Copernicus、USGS 下载能力从「发现/元信息」推进到实际落盘
- 为前端引入构建工具与可复用组件，减少大文件 `app.js` / `chat.js` 的维护成本
- 消除其余 8 条非 Matplotlib 警告（geographic CRS 质心、pyproj numpy 标量转换）

## 许可证

[AGPL v3](LICENSE) — 可自由使用和修改，但分发时需提供源码。
