# GIS-WorkTable 系统审计报告 (Project Audit Report)

> **2026-10-11 事实补充**：本文保留早前审计记录。本次仓库盘点未重跑此文所述测试；“充分验证”、纯本地离线及真实地形等表述不能替代对应环境的验收。当前随仓库提供的 SQLite 快照为 2,198 条服务、1,561 条图层记录，不是超万级；来源获取能力需区分下载、目录发现与人工指引。详见 [仓库盘点与方向评估](repository-audit.md)。

## 一、项目架构与技术选型审计

### 1. 整体架构
GIS-WorkTable 采用 **前后端分离 + Agent 工作流 + 2D/3D 双地图引擎** 架构：

- **前端架构**：
  - 核心页面：原生 HTML5 + 响应式 CSS（Material 3 中性设计风格，杜绝无意义渐变与过量毛玻璃）。
  - 地图引擎：
    - 2D: Leaflet 1.9.4（国内 CDN 加速，支持矢量图层、栅格图层、卷帘对比、测量与绘制）。
    - 3D: CesiumJS（零 Cesium Ion 依赖，支持全球地形、纯本地离线与按需渲染模式 `requestRenderMode: true`）。
  - 状态管理：`frontend/js/gis_state.js` 作为前端统一状态中心，管理图层、当前要素选中、行政区下钻栈（World → Province → City → County）、2D/3D 双向数据同步。
  - 交互模块：`chat.js`（对话流与 SSE 事件处理）、`layers.js`（图层列表与属性面板）、`map.js`（Leaflet 地图控制器）、`renderer_cesium.js`（3D 地球渲染器）、`spatial.js` / `raster_tools.js`（手动工具直接调用面板）。

- **后端架构**：
  - 框架：FastAPI + Uvicorn，开启 GZip 压缩与 CORS 支持。
  - 模型适配与调度：
    - `backend/services/llm_config.py`：多 Provider 动态切换（DeepSeek / GLM / Agnes / 自定义 OpenAI 兼容接口），支持客户端 API Key 与代理配置。
    - `backend/services/graph.py`：LangGraph ReAct Agent 工作流。自动编排大模型与工具执行，内置递归保护、网络重试及 Agent 2 结果真实性自检（Verifier）。
    - `backend/services/tools.py`：统一注册 120+ 个 LangChain `@tool` 工具，导出 StructuredTool 供 Agent 与 MCP Server 调度，具备工具执行历史自动记录功能（`history_service.py`）。
  - 核心空间计算库：GeoPandas、Shapely、PyProj、Rasterio、GDAL、Matplotlib、Scikit-learn、NetworkX。

---

## 二、真实功能分类清单

根据代码追踪与测试套件验证（510+ 项通过）：

### 1. 已实现且充分验证 (Verified & Stable)
- **行政区划获取与下钻导航**：`datav_boundary`、`drill_down`、`drill_up`（自动从阿里云 DataV 获取省市县三级边界并校正 GCJ-02 → WGS-84）。
- **矢量几何分析**：`spatial_buffer`、`spatial_multi_ring_buffer`、`spatial_intersect`、`spatial_union`、`spatial_difference`、`spatial_clip`、`spatial_centroid`、`spatial_simplify`、`spatial_dissolve`。
- **空间量测**：`measure_area`（自动选择最佳 UTM 带投影，带 Albers 交叉验证）、`measure_distance`。
- **3D 地球与数据驱动拉伸**：2D/3D 一键切换，`visualize_3d` 面图层高度挤出渲染。
- **手动直连面板与历史重跑**：`/api/tools/invoke`，不消耗 LLM token 即可调用所有核心空间工具，工具面板与处理历史一键复现。
- **GeoSource 全球数据超市与 MCP 互通**：本地 SQLite 索引 11,000+ 个空间服务与 18,000+ 图层，零拷贝热同步机制。

### 2. 已实现但依赖外部网络/API Key (Conditional)
- **高德地图服务**：`amap_poi_search`、`amap_geocode`（依赖有效的 AMAP Web Key）。
- **OSM 道路与要素提取**：`download_road_network`、`fetch_osm_boundary_or_features`（依赖 Overpass 镜像网络连通性）。
- **DEM 地表高程分析**：AWS/Terrain 瓦片服务在线获取（受海外网络影响）。

### 3. 部分实现或有待提升规范 (Partially Implemented / Need Standard)
- **图层重命名状态闭环**：历史代码中图层重命名只更新了图层面板属性，已在本次优化中补齐：前端 `GIS.state.renameLayer`、`GIS.map.renameLayer` 与后端注册表同步。
- **UTM 投影带极值约束**：全球经度边界点计算 UTM 带号偶发越界，已通过 `_get_utm_crs` 统一约束在 1~60。

---

## 三、问题优先级评估与改进

| 优先级 | 问题描述 | 影响范围 | 现状与改进措施 |
|---|---|---|---|
| **P0** | 经度极值（±180°）处 UTM 带号计算越界（如得到 EPSG:32661，UPS 极地投影而非 UTM 60 带） | 空间缓冲区、多环缓冲、要素位移等矢量工具 | **已修复**：建立 `_get_utm_crs` 规范函数，严格 clamp 在 [1, 60] 区间，通过回归测试。 |
| **P0** | 图层重命名后前后端状态不一致，导致后续 AI 工具按新名查询失败 | 图层生命周期、后续多轮分析 | **已修复**：前端 `layers.js`、`chat.js`、`map.js`、`gis_state.js` 统一增加 `renameLayer` 并在重命名后自动通知后端重新注册与解注册。 |
| **P1** | 新用户首屏空状态缺乏明确操作引导，仅显示时间问候语，系统能力不透明 | 用户首次使用上手成本 | **已修复**：在 `time.js` 空状态中嵌入任务导航引导框与 3 个典型核心工作流一键执行按钮。 |
| **P2** | 工具接口数量庞大（120+），部分工具依赖的投影转换存在重复实现片段 | 代码维护与后续扩展 | **已改善**：提取统一的 `_get_utm_crs` 规范，并在单元测试中建立极值防护基线。 |

---

## 四、核心代表性工作流验证结论

我们验证了最具代表性的基础工作流：
1. **边界数据获取**：`datav_boundary("北京市")` → 自动获取 16 个区县矢量要素，CRS 统一校正为 WGS-84，自动推送并注册图层。
2. **矢量空间分析**：`spatial_buffer("北京市", 5, "km")` → 自动根据边界经纬度计算 UTM 50N 投影带，执行真实多边形缓冲运算，生成 `北京市_缓冲区` 图层并加载。
3. **几何精确量测**：`measure_area("北京市")` → 投影到 UTM 50N 计算面积为 16395.82 km²，Albers 等面积交叉验证为 16407.34 km²，输出完整量测报告。

全链路前后端数据流、图层状态机与地图呈现保持一致，测试覆盖良好。
