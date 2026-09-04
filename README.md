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
- **三模型支持**：GLM-4.7-Flash+（免费默认）、DeepSeek V4 Flash+、Agnes 2.0 Flash+
- **LangGraph ReAct Agent**：自动管理多轮工具调用循环，替代手写 if/elif 路由
- **GLM 路由系统**：自动加载 `skills/` 目录下的技能文档辅助任务
- **SSE 流式响应**：前端实时展示工具调用进度
- **沙箱代码执行**：AST 白名单验证 + 安全 eval，支持数学表达式和受控 Python 执行

### 第三方数据

- 高德地图：POI 搜索、地理编码
- DataV：行政区划边界
- 百度地图：AOI 建筑轮廓（Playwright 自动化提取）
- OSM：路网下载与分析
- 热力图

### 工程管理

自动保存、手动保存/加载、重命名、导出/导入工程。

## 技术栈

| 类别 | 技术 |
|------|------|
| 前端 | HTML + CSS + JavaScript（原生） |
| 地图渲染 | Leaflet + Leaflet.Draw |
| 后端 | FastAPI + Python |
| AI 框架 | LangGraph（ReAct Agent）+ LangChain Tools |
| LLM | GLM-4.7-Flash+ / DeepSeek V4 Flash+ / Agnes 2.0 Flash+ |
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
│       └── test_coverage_gap.py    # 覆盖率补充测试
│
├── skills/                      # AI 技能文档（12 个领域）
├── data/                        # 示例路网数据
├── output/                      # AI 生成的 GeoJSON 输出
└── test/                        # 测试数据与报告
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
| GET/POST | `/api/projects` | 工程列表/创建 |
| POST | `/api/projects/auto-save` | 自动保存 |
| GET | `/api/version` | 版本信息 |
| DELETE | `/api/chat/memory` | 清空对话历史 |

## 运行测试

```bash
python -m pytest backend/tests/ -v
```

当前 238 个测试全部通过。

## 已知限制

- `requirements.txt` 未完整列出所有运行时依赖（`rasterio`、`scipy`、`scikit-image`、`pyproj`、`langchain`、`langgraph`、`pyogrio`、`Pillow`、`networkx`、`requests`、`pyogrio` 等在代码中使用但未声明），安装后可能需要手动补装
- 无 Docker 配置，无 CI/CD 流水线
- API Key 通过前端设置弹窗管理，存储在本地 `apikey.txt`（已 gitignore）
- 前端为原生 HTML/CSS/JS，无构建工具和包管理
- 部分高级功能（时序动画、图表联动）的前端交互仍在迭代中

## 许可证

[AGPL v3](LICENSE) -- 可自由使用和修改，但分发时需提供源码。
