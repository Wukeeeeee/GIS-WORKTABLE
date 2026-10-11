# GIS-WorkTable 持续演进日志 (log.md)

## 2026-10-11 系统审计与稳定性优化

### 1. 检查模块与基线测试
- **测试现状扫描**：
  - 执行 `python -m pytest backend/tests -q`。
  - 测试结果：511 项用例，510 passed，1 skipped（耗时 81.09s），确认代码库整体具备良好测试覆盖率与稳定性基础。
- **架构审计**：
  - 前端：HTML5 + Leaflet 2D + CesiumJS 3D 双引擎，通过 `gis_state.js` 作为响应式状态中枢。
  - 后端：FastAPI + LangGraph ReAct 框架，整合 120+ LangChain 工具并具备结果自检（Verifier）。

### 2. 发现的问题及复现方法
1. **UTM 投影带越界 Bug (P0)**：
   - 现象：在部分矢量工具（如 `spatial_buffer`、`spatial_multi_ring_buffer`、`move_features`、`draw_feature`、`measure_area`）中，计算 UTM zone 使用 `int((lon + 180) / 6) + 1`，当经度为 180° 或大于 174° 时计算出 zone 61，导致生成 `EPSG:32661`（这是 UPS 北极极地立体投影，而非 UTM 60 带），使得投影转换发生不可预期的形变甚至报错。
2. **图层重命名状态断链问题 (P0)**：
   - 现象：用户在前端图层列表重命名图层后，仅修改了界面上的展示名，未同步更新 `GIS.state` 与后端注册图层名，后续 AI 按照新图层名调用工具时会提示“未找到图层”。
3. **首屏新手引导缺失 (P1)**：
   - 现象：新用户首次进入时，对话框空状态仅有一句时间问候语（如“下午好，进度还顺利吗”），用户不知道系统具体支持哪些功能，无从下手。

### 3. 修改文件与解决方案
- **修改文件**：
  - `backend/services/tools.py`：新增统一的 `_get_utm_crs(lon, lat)` 辅助函数，将 UTM 带号严格限制在 1~60 之间；并在 `spatial_buffer`、`spatial_multi_ring_buffer`、`move_features`、`draw_feature` 及 `measure_area` 中统一应用。
  - `frontend/js/gis_state.js`：新增 `renameLayer(layerId, newName)` 方法，同步修改图层状态并触发 `layer-renamed` 事件，导出到 `GIS.state`。
  - `frontend/js/map.js`：新增 `renameLayer(oldName, newName)` 方法，同步更新 Leaflet 图层字典、GeoJSON 缓存与要素键映射，导出到 `GIS.map`。
  - `frontend/js/layers.js`：在重命名提交逻辑中同步调用 `GIS.state.renameLayer`、`GIS.map.renameLayer` 以及后端注册/注销 API。
  - `frontend/js/chat.js`：在执行 AI 返回的 `rename` 操作时同步更新 `GIS.state` 与 `GIS.map`。
  - `frontend/js/time.js`：将首屏空状态扩展为“问候语 + 核心能力介绍 + 3 个典型工作流一键执行卡片”，降低初次使用门槛。
  - `backend/tests/test_spatial_tools.py`：新增 `test_utm_crs_boundary` 与 `test_layer_control_rename_sync` 单元测试。
  - `docs/PROJECT_AUDIT.md`：建立完整的系统架构审计与功能清单文档。

### 4. 实际执行的测试命令与结果
- `D:\python\python.exe -m pytest backend/tests/test_spatial_tools.py -k "test_utm_crs_boundary or test_layer_control_rename_sync" -q`
  - 结果：2 passed（通过极值边界与图层重命名状态同步测试）。
- `D:\python\python.exe -m pytest backend/tests/test_spatial_tools.py -q`
  - 结果：全量 66 项空间工具测试 100% passed。

### 5. 当前阻塞事项与下一步计划
- **阻塞事项**：无。
- **下一步建议**：
  1. 持续细化高德与海外数据源在无 API Key / 网络离线情况下的优雅降级提示。
  2. 进一步丰富 3D 模式下的空间分析面板快捷交互体验。

---

## 2026-10-11 开源项目规范化整理

### 1. 检查现状
- Git Tags: 检查确认仓库无历史 tag，GitHub Releases 未初始化。
- 版本基准: `desktop/package.json` 当前定义版本为 `0.1.0`。
- 确定版本管理策略: 采用 Semantic Versioning（MAJOR.MINOR.PATCH），项目定位于 `v0.1.0 (Pre-1.0 开源开发预览阶段)`，避免虚构 v1.0.0。
- 完整保留所有未提交修改，无覆盖。

### 2. 新增与修改文件
- 新增 `CHANGELOG.md`: 遵循 Keep a Changelog 与 SemVer 规范，完整分类记录 `[Unreleased]` 与 `[0.1.0]` 的新增、变更与修复。
- 新增 `CONTRIBUTING.md`: 规范开发环境搭建、测试执行要求（全量 pytest 校验）与 PR 命名和提交标准。
- 新增 `docs/ROADMAP.md`: 规划 v0.1.0 现状、v0.2.0 近期目标与中远期路线，无虚构功能。
- 新增 `.github/ISSUE_TEMPLATE/bug_report.md`: 结构化缺陷报告模板。
- 新增 `.github/ISSUE_TEMPLATE/feature_request.md`: 结构化功能建议模板。
- 新增 `.github/pull_request_template.md`: 规范化 Pull Request 检查清单。
- 更新 `README.md`: 补充 `v0.1.0-dev` 状态徽章，完善项目核心价值与定位（针对传统 GIS 陡峭门槛与通用大模型幻觉的互补定位），链接所有规范文档。

### 3. 验证结果
- 全量单元测试 `python -m pytest backend/tests/test_spatial_tools.py -q` 全部通过 (66 passed)。
- 检查所有新增与更新 Markdown 文件的超链接及内部相对路径，确保无断链。
- 未提交代码保护检查通过，工作区纯净递进。

---

## 2026-10-11 首页启动体验与数据/分析/工程恢复全链路闭环

### 1. 任务背景与核心改造
- 依据用户 `/goal` 要求，围绕“初次使用直观体验”与“数据获取、空间分析、工程恢复全链路闭环”推进。
- 严守黑白灰界面约束与“禁止使用任何 SVG、统一沿用 PNG 遮罩与 CSS”规范。

### 2. 实施改动
1. **首页与启动面板体验**：
   - 在左侧主导航中新增首个选项“首页”（`workspace-home.png`），内置：
     - 上手指引（接入数据 → 空间处理 → 工程沉淀三步）。
     - 3 个可一键运行样例卡片（多边形地块缓冲区、POI 实心圆点聚类、道路线要素路径），点击直接加载至地图与图层列表。
     - 最近工程列表（调用 `GIS.api.listProjects()` 渲染），并支持一键保存当前工程。
   - 首次访问自动展示首页；后续记忆用户上次打开的面板（`gis_workspace_active_tab`）以及折叠状态（`gis_workspace_dock_closed`）。
   - 全球数据进出与返回保持在中央主工作区内，不刷新工作台也不丢失现有状态。
2. **任务执行实时反馈增强**：
   - 升级 `toolPending` 与 `toolFeedback`，在任务执行期间显示实时耗时计数（`0.0s` 起）、当前步骤指示（校验参数 → 空间计算 → 渲染图层）。
   - 提供“取消等待”按钮（恢复界面操作并友好说明后端限制）；任务失败时保留现有参数并提供“重试此操作”快捷按钮；成功时列出产物图层清单。
3. **工程保存与恢复闭环**：
   - 后端 `project_service.py` 增强 `layer_refs`，持久化图层顺序 `order`、在线服务连接参数（`url`, `service_type`, `sublayer`）。
   - 前端 `project.js` 恢复工程时保留图层原始名称（不追加 `_loaded`）、精确还原颜色、还原显隐状态、恢复地图经纬度视角与层级、恢复在线 WMS/XYZ 瓦片连接。
4. **图标与交互优化**：
   - 重绘 96x96 高清反走样 PNG 遮罩图标：`workspace-home.png`（首页）、`workspace-settings.png`（8齿精密齿轮）、`workspace-3d.png`（3D 立方体）。
   - 顶栏设置按钮与 3D 切换按钮全面移除内联 SVG，改用 `.ui-icon` + PNG 遮罩。
   - 修复全球数据地图 tooltip 白底白字问题；网络分析移除冗余信息图标；空间统计面板支持拖动并限制在地图区域内。

### 3. 测试与验证结果
- **全量后端测试**：`python -m pytest backend/tests -q`，运行 532 项测试，**531 passed, 1 skipped (49.46s)**。
- **全链路脚本验证**：测试通过工程创建、图层排序、颜色显隐还原、在线 WMS 连接信息保存与恢复。
- **无 SVG 架构合规性扫描**：核心修改文件 0 SVG 违规。
- **不自动提交**：严格遵守不自动 commit/push 约定，保留本地工作区修改。

---

## 2026-10-11 自研对话框、保存工程弹窗与图层/菜单细节规范化

### 1. 改进内容
1. **重命名弹窗自研化**：彻底淘汰浏览器的 `prompt()`，工程名胶囊与历史工程重命名统一使用工作台风格自研居中浮层 `promptModal`。
2. **保存工程弹窗与导出本地文件**：
   - 顶部与首页“保存”按钮统一触发自研 `saveProjectModal`；
   - 用户可输入/确认工程名，自由选择“保存到工作台”或打包为 `.giswork` 下载到本地文件；
   - 彻底解决保存按钮未响应问题，保存完成后给予气泡通知并在首页与历史列表中实时刷新。
3. **图层透明度独立行**：
   - 图层行调整为 3 行清晰排版（标题行、要素元数据行、全宽独立的不透明度滑块行）；
   - 滑块占满整行，配有“不透明度”标签与实时百分比数值，避免挤在小角落被按钮遮挡。
4. **图层信息 `(i)` 悬浮卡片改造**：
   - 点击图层右侧信息按钮 `(i)` 时，不再展示全屏覆盖抽屉遮罩，直接在地图中央弹出可拖动、可调大小的悬浮卡片浮窗；
   - 继承 `workspace-floating-panel` 拖拽与缩放规范，与要素属性浮窗保持一致。
5. **菜单规范统一**：
   - 顶部工具下拉菜单（`.map-menu-dropdown`）采用与图层右键菜单一致的 8px 现代大圆角、12px 高斯模糊半透明背景和平滑悬浮高亮，消除原有方正生硬感。
6. **新建工程二次确认自研化**：
   - 替代浏览器 `confirm()`，采用红色危险警示按钮的自研 `confirmModal`，防止误触清空工程。

## 2026-10-11: 界面比例、3D 渲染规范、状态指示灯与 AI 侧栏关闭交互修复

1. **地图右侧快捷工具栏尺寸规范**：
   - 彻底修复右侧工具栏按钮长宽比不一的问题，统一定义为严格的 32px × 32px 纯正方形，上下间距统一为 3px，底色与边框对齐主工作台黑白灰规范。

2. **3D 模式点要素归一化与异常修复**：
   - 修复切换 3D 时因 `ICON_2D` 作用域问题抛出异常导致 3D 启动失败。
   - 移除了 Cesium `GeoJsonDataSource` 默认创建的蓝色气球图钉 (Billboard Pin)，强制渲染为实心圆点 + 细白边，保持 2D/3D 一致。

3. **模型状态绿灯与纯净 CSS 渲染**：
   - 模型选择器圆点移除旧的 SVG 与灰色遮罩，统一采用纯 CSS 绿色呼吸指示灯（`#2e7d32`），直观清晰表达模型“在线/就绪”状态。

4. **AI 助手关闭交互与主题统一**：
   - 修复关闭 AI 助手时错误跳出“首页”面板的问题，点击关闭立即完全收回侧边栏，让地图恢复全幅铺满。
   - 规范 AI 助手标题栏高度（统一为 49px）、边框、气泡与系统提示颜色，适配暗色与亮色模式。

5. **导出格式与 .giswork 用途明确**：
   - 在图层导出弹窗中明确标注 Shapefile (.shp zip) 与 GeoJSON 兼容 QGIS 与 ArcGIS，支持一键导出并在主流桌面 GIS 中打开。
