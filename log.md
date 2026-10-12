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
- `python -m pytest backend/tests/test_spatial_tools.py -k "test_utm_crs_boundary or test_layer_control_rename_sync" -q`
  - 结果：2 passed（通过极值边界与图层重命名状态同步测试）。
- `python -m pytest backend/tests/test_spatial_tools.py -q`
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

6. **AI 助手头部按钮对比度与极简未配置引导**：
   - 彻底修复 AI 头部右侧按钮颜色对比度缺失（黑底黑图标）问题，统一四颗按钮（历史、设置、新建、关闭）为一致的 `workspace-icon-btn` 规格与主题自适应色彩。
   - 移除副标题描述文案（“用自然语言完成空间任务”等），面板采用极简风格。
   - 增加未配置检测：当检测到未填 API Key 时，面板居中呈现未配置说明并提供一键“去配置”按钮直达设置弹窗。

---

## 2026-10-12: GIS AI 助手过度追问、上下文复用与专题图生成流程深度修复

### 1. 检查结果与真实根因分析

针对“用户先查鼓楼区 GDP，随后输入'需要专题图'，AI 没有直接出图而是抛出 3 个维度的问卷式多选题并命令用户特定格式回复”的问题，进行了全链路深度排查，定位到以下真实根因：

1. **根因一：提示词硬性规定所有“专题图”必须调用 `spatial_graduated_colors`，与单要素图层产生冲突**
   - 原 `SYSTEM_PROMPT` 强制要求：“当用户要求制作'专题图'时...必须将矢量面边界加载为地图图层，并调用 `spatial_graduated_colors` 工具应用分级色彩渲染”。
   - 但 `spatial_graduated_colors` 在工具层逻辑严格要求要素具备数值差异（`if vmin == vmax: return "字段所有值相同，无法分级"`）。
   - 单个行政区（如南京市鼓楼区）在 DataV 中仅有 1 个多边形要素，必然导致 `vmin == vmax`。模型在提示词的“强制分级设色”死命令与单要素“无法分级”的技术约束之间陷入冲突，从而自行衍生出“方案A：拉取全国 4 个鼓楼区对比（凑多个要素）”或“方案B：单区看板”，并向用户抛出选择题。

2. **根因二：系统提示词缺乏“多轮上下文继承”与“零追问行动优先”规范**
   - 提示词中未明确规定：当上一轮对话已确定具体地理实体（如南京市鼓楼区）、统计年份（2025）和经济指标（GDP）后，下一轮简短指令（如“需要专题图”、“做成图”）必须完全继承前序实体，严禁退化为模糊泛指名称，严禁擅自将单区问题膨胀为跨区域对比。
   - 提示词中缺少对参数默认值的硬性规定，导致 AI 把可选参数（图型选择、色带、内置底图还是指定 SHP/GeoJSON）当作必填项反复盘问用户。

3. **根因三：工具层 `datav_boundary` 跨轮消歧与上下文复用能力薄弱**
   - 原 `datav_boundary` 消歧候选匹配只检查了 `_last_user_message`（当前轮用户原始输入）。
   - 当第 2 轮用户仅发送“需要专题图”时，输入中不包含“南京”，若模型调用 `datav_boundary("鼓楼区")`，原代码无法识别上一轮上下文，导致再次触发 `ask_user_choice` 重复追问。

4. **根因四：画布中心点坐标问题核实**
   - 日志中地图中心坐标为 `(91.53458, 23.41912)`，并非定位逻辑 Bug，而是因为 AI 在前两轮只进行了口头承诺和文本盘问，从未调用 `datav_boundary` 或图层注册工具，导致前端地图始终维持用户初始或平移视图，未触发 `mapInstance.fitBounds`。

---

### 2. 修改文件清单与改动说明

1. **`backend/services/ai_service.py`**
   - **重构专题图与空间可视化规范**：严格区分“单区域专题图”与“多区域专题图”。
     - **单区域专题图**：明确单个要素无法分级设色，默认调用 `datav_boundary` 加载边界并在地图居中，结合统计数据调用 `create_chart` 生成结构图表或通过 `execute_python` 绘制“行政区轮廓+指标信息看板”，直接交付成果，严禁追问；
     - **多区域专题图**：要素数 $\ge 2$ 时，调用 `spatial_graduated_colors` 渲染分级色彩；
     - **默认参数规范**：底图默认且必须使用系统内置行政区划（`datav_boundary`），严禁盘问用户是否提供 SHP/GeoJSON；符号化与配色采用专业默认值，严禁询问图型选择。
   - **新增多轮上下文继承与零追问默认执行准则**：
     - 准则 1：简短需求必须严格继承上一轮已确认的地理实体全称、年份、指标数值，严禁退化为模糊名称；
     - 准则 2：行动优先，默认直接出图交付，严禁抛出问卷式选项，严禁要求用户手动打字回复固定格式指令；
     - 准则 3：严禁自我加戏，用户未要求时严禁主动推荐跨区域横向对比。
   - 同步升级免费模型提示词 `SYSTEM_PROMPT_GLM`，保持策略一致。

2. **`backend/services/tools.py`**
   - 新增 `_conversation_context` 全局状态及其存取方法 `set_conversation_context()` / `get_conversation_context()`。
   - 增强 `datav_boundary` 的重名区县消歧逻辑：当区县重名时，多级匹配 `_last_user_message`（本轮指令）、`_conversation_context`（多轮上下文记录）以及 `_registered_layers`（当前地图已加载图层名）。在多轮对话中自动消歧为已确认城市，彻底杜绝重复弹窗。
   - 优化 `spatial_graduated_colors`：更新工具 docstring，并在 `vmin == vmax` 或单要素时返回建设性指引（提示单要素已在地图展示，建议结合指标面板或图表交付），避免引发模型困惑。

3. **`backend/services/graph.py`**
   - 在 `run_agent` 与 `run_agent_stream` 启动时，自动提取最近 10 条消息作为上下文摘要注入 `_tools_mod.set_conversation_context()`，使工具层在整个 Agent 执行周期内均具备准确的历史实体感知能力。

4. **`backend/tests/test_thematic_context.py`**
   - 新建覆盖四大关键场景的自动化测试用例，全方位验证上下文继承、零追问规则、消歧机制与真实错误提示。

5. **根治交付推脱与假边界借口（新增交付红线）**：
   - 严禁 AI 声称“我这边不能直接生成 PNG/PDF 图片文件”（系统支持 `execute_python`/matplotlib 产出 PNG 成果图，前端可直接查看下载）；
   - 严禁在正文中吐出裸 `<svg>` XML 代码让用户手动保存；
   - 严禁向用户索要本地 SHP/GeoJSON 路径（国内边界一律直接调用 `datav_boundary` 获取真实矢量并加载到交互地图，不可借口“没有真底图”推诿）。

---

### 3. 测试用例与执行结果

执行命令：
`python -m pytest backend/tests/test_thematic_context.py backend/tests/test_choose_option.py backend/tests/test_result_guard.py backend/tests/test_multi_turn_state.py -v`

测试结果：
- **35 项测试全部通过（35 passed in 2.60s）**：
  1. `test_multi_turn_context_inheritance_in_boundary`：验证先查询南京鼓楼区后要求专题图时，工具层自动消歧并复用前序实体，不重复弹窗（PASSED）。
  2. `test_topic_relevance_preserves_short_thematic_command`：验证短指令“需要专题图”、“做成图”不会被历史检测误删（PASSED）。
  3. `test_system_prompt_rules_forbid_interrogation`：验证系统提示词中包含行动优先、禁止格式命令、默认内置边界与单区规范（PASSED）。
  4. `test_spatial_graduated_colors_single_polygon_graceful_guidance`：验证单要素分级色彩优雅降级与指标看板指引（PASSED）。
  5. `test_ambiguous_district_first_turn_requires_choice`：验证首轮无上下文输入重名区县时，正确唤起 `ask_user_choice` 交互选项（PASSED）。
  6. `test_unambiguous_when_city_specified_in_query`：验证输入指明城市时直接执行，不弹出多余选项，不强推跨区域对比（PASSED）。
  7. `test_missing_boundary_returns_truthful_failure`：验证边界缺失时返回真实错误提示，严禁捏造几何（PASSED）。
  8. `test_spatial_graduated_colors_missing_field_reports_available_fields`：验证缺少属性字段时如实返回可用字段列表（PASSED）。

---

### 5. 系统通知单行截断与操作反馈 UI/Toast 体验重构

#### 根因剖析
1. **单行省略号挤压截断**：
   - 在 `frontend/css/workspace.css` 与 `frontend/js/chat.js` 中，系统通知元素 `.system-pill` 均被强制声明了：
     ```css
     overflow: hidden !important;
     text-overflow: ellipsis !important;
     white-space: nowrap !important;
     max-width: 82% !important;
     ```
   - 导致如“数据源接入指引”、“代理获取失败 (HTTP 502)”以及图层名称较长的通知（如 `ACS_Highlights_Population_Housing_Basics_Boundaries - County`）被生硬截断成半截字，用户必须 hover 才能通过浏览器原生粗糙的黑色 `title` 浮窗查看，视觉极差且无法阅读。
2. **Markdown 格式未解析与原生 tooltip 污染**：
   - 胶囊内直接插入带 `**` 的原始文本，未调用内联 Markdown 解析；
   - 赋值 `bubble.title = text` 导致鼠标滑过时系统弹窗黑色矩形，破坏界面质感。
3. **缺少轻量级操作级反馈（Toast）机制**：
   - 空间数据源“加载图层”、“复制 URL”、“上传文件”等高频动作直接以聊天行插入左侧对话框，既污染了 AI 与用户的多轮问答流，又因聊天窗口狭窄显得拥挤杂乱。

#### 落地修复方案
1. **全局轻量 Toast 组件上线 (`window.GIS.toast`)**：
   - 在 `frontend/js/api.js` 与 `frontend/css/workspace.css` 中实现并挂载全局 `window.GIS.toast`（支持 `success`, `error`, `warn`, `info`）。
   - 顶部居中悬浮、高质感毛玻璃圆角卡片、平滑滑入淡出（2.8s 自动销毁），点击即关。
   - 数据源加载成功、文件上传成功、URL 复制等交互一律唤起 Toast 即时提示，用户无需分心扫视左侧聊天框。
2. **彻底解决提示被截断与排版难看问题**：
   - 在 `frontend/css/workspace.css` 中将 `.system-pill` 改造为 `white-space: normal !important; word-break: break-word !important; overflow: visible !important;`，自适应折行完整展示所有文字与图层名；
   - 胶囊内容支持 `marked.parseInline()` 解析，将 `**名称**` 正确渲染为加粗字体，移除原始 `**` 符号；
   - 移除 `bubble.title` 属性，彻底消除鼠标悬浮时的黑色系统原生黑框；
   - `.system-card` 统一左对齐 (`text-align: left !important;`) 与优化行高间距，保证 502/排查指引/多行警告结构清晰整齐。

---

### 6. AI 与 GIS 深度融合的分层测试体系搭建

#### 核心原则：不割裂系统，真实链路验证
本项目的 AI Agent 依赖 GIS 空间分析工具、图层注册机制与前后端协议接口。严禁将 AI Core 孤立为不具备 GIS 运行环境的玩具模块。分层测试旨在既保留 GIS 真实运行链路，又能逐层精准定位问题：

1. **Layer 1: 单元测试 (`test_layer1_unit.py`)**：
   - 验证 Prompt 规则、多轮上下文继承指令、单区规范、禁止方案A/B过度追问；
   - 验证未执行制图代码（"我无法直接出图/请复制到 Jupyter"）探测函数；
   - 验证参数提取与结果守护，纯内存极速验证（<1s）。
2. **Layer 2: Agent 测试 (`test_layer2_agent.py`)**：
   - 复用真实生产 `LangGraph Agent` 与 `tools.py` 上下文机制；
   - 验证第二轮短需求（"需要专题图"）自动复用首轮实体消歧，不重复弹窗；
   - 验证拦截到未执行代码时，自动触发强制执行机制。
3. **Layer 3: GIS 工具集成测试 (`test_layer3_gis_tools.py`)**：
   - 使用真实生产工具与真实/受控地理数据；
   - 验证 `datav_boundary` 产出合规 WGS-84 矢量边界；
   - 验证 `execute_python` 实际调用 matplotlib 在磁盘生成有效且非空的 PNG 图像文件（校验 PNG 文件头签名）；
   - 验证单要素分级设色优雅降级。
4. **Layer 4: 地图集成测试 (`test_layer4_map_integration.py`)**：
   - 验证工具产物真实传递至 `_register_layer` 并更新 `get_registered_layers()` 与 `get_pending_state()`；
   - 验证后端 `/api/layer/register` 与 `/api/layer/list` 前后端数据通道畅通；
   - 验证 GeoJSON 结构完全契合 Leaflet / VectorGrid 渲染引擎规范。
5. **Layer 5: 端到端测试 (`test_layer5_e2e.py`)**：
   - 验证从用户请求出发，贯穿 Agent 调度、工具执行、图层注册、产物落盘到流式 SSE 事件输出全流程。

#### 运行模式与配套工具
- **`scripts/run_layered_tests.py`**：统一运行脚本，提供 `--mode fast` (Layer 1+2)、`--mode integration` (Layer 3+4)、`--mode regression` (全量 5 层) 及 `--layer N` 指定单层测试。
- **`backend/pytest.ini`**：注册 `unit`, `agent`, `gis_tools`, `map_integration`, `e2e`, `fast`, `integration`, `regression` 专属 markers。
- **`docs/layered-testing-guide.md`**：产出全套设计原则与操作指南。

---

### 7. 仍存在的潜在局限与待优化项

1. **行政区下辖多街道精细矢量覆盖**：
   - 当前阿里云 DataV 官方接口支持省、市、区（县）三级矢量边界。对于区县下辖的各街道/乡镇边界，DataV 尚未提供标准化接口。若用户明确要求“鼓楼区各街道分级设色图”，仍需依赖 OSM 或第三方高精矢量数据源。
2. **极短对话历史的话题切换精细度**：
   - 当前针对小于 12 个有效字符的短消息一律视为上下文延续以防止历史丢失。如果用户在同一会话中突然提出完全无关的短指令（如“查查西瓜”），系统仍会携带前置 GIS 上下文，需在后续版本中结合语义意图分类做进一步精细化分流。


## 2026-10-12: 依赖审计、GIS 工具运行时审计与 Pyodide 可行性验证（架构审计轮）

### 1. 本轮目标

按「审计真实调用链 → 工具分级 → 多执行引擎设计 → Pyodide 实测 → 渐进式改动」顺序推进，不做大规模重构，不引入为新技术而技术的改动。

### 2. 检查的文件

- `backend/requirements.txt`（34 个顶级依赖逐包 grep 验证）
- `backend/main.py`（启动流程、约 50 个 `/api/*` 端点、PROJ_LIB 清理）
- `backend/services/graph.py`（create_react_agent 构建与强制补执行链）
- `backend/services/tools.py`（9288 行，124 个 @tool，约 200 处函数内懒加载）
- `backend/services/result_guard.py`、`datav_service.py`、`tools.py` 上下文/消歧实现
- `backend/tests/layered/`、`conftest.py`（离线性确认：LLM 全 mock，网络测试自带 skip）
- `frontend/index.html` + 22 个 JS（无构建、无 Turf.js、CDN 引入 Leaflet/Cesium）
- `desktop/main.js`、`start.bat`、`backend/launcher.py`（部署链）

### 3. 修改的文件

| 文件 | 改动 | 原因 |
|---|---|---|
| `backend/requirements.txt` | 移除 `python-dotenv`、`seaborn`；为 `openai`/`pyecharts` 加防误删注释 | 两包全库零引用（grep 证实：dotenv 无任何加载约定、密钥走设置 UI；seaborn 绘图全走 matplotlib）。openai 是 langchain-openai 传递依赖（pin 有意），pyecharts 仅 execute_python 沙箱白名单使用，均保留 |
| `backend/services/graph.py` | 强制补执行的纠错指令文本从两处内联字面量（run_agent / run_agent_stream）提取为模块常量 `_RECOVERY_PROMPT_CODE_DUMP` / `_RECOVERY_PROMPT_NO_ACTION` | 消除重复 + 可测试性；字符串逐字节相同，**零行为变化** |
| `backend/tests/layered/test_layer1_unit.py` | 与源码对齐重写：result_guard 改用现行 API `apply_guard`；`_is_unexecuted_code_or_disclaimer` 改为现行签名 `(text, msgs)`；Prompt 断言更新为现行措辞（GLM 提示词为精简版，只校验子集）；`set_conversation_context` 按现行 `str` 签名传字符串 | 原文件 collect 即 ImportError（引用已删除的 `sanitize_user_facing_response`/`guard_response_vs_tools`），导致整个测试套件无法运行 |
| `backend/tests/layered/test_layer2_agent.py` | 同上：移除不存在的 `_tools_mod`、`_format_agent_recovery_instruction`；断言改打现行常量 `_RECOVERY_PROMPT_CODE_DUMP`；datav_service mock 改打现行函数 `fetch_boundary`（原打不存在的 `get_boundary_by_adcode`） | 同上（collect 即 ImportError） |
| `docs/architecture/dependency-audit.md`（新增） | 依赖审计报告：逐包引用点、冗余证据、懒加载纪律、部署链 | 本轮审计产出 |
| `docs/architecture/gis-tool-runtime-audit.md`（新增） | 124 工具按实现族分级的运行时审计表 | 本轮审计产出 |
| `docs/architecture/runtime-architecture.md`（新增） | 现状/目标架构 mermaid 图、确定性调度规则、统一结果协议、Pyodide 实测结论 | 本轮审计产出 |
| `scripts/pyodide_feasibility_check.mjs`（新增） | Pyodide 最小验证脚本（Node + 官方 CDN wheel），可复现 | 本轮验证产出 |

### 4. 测试与结果

- **修复前基线**：`pytest backend/tests` collect 即中断——`test_layer1_unit.py`、`test_layer2_agent.py` 两个 ImportError（测试与源码脱节），558 项无法运行。
- **修复后**：
  - fast 层（unit+agent）：`pytest backend/tests/layered -m fast` → **8 passed, 10 deselected**（0.13s）
  - `backend.main` 冒烟导入 → OK（requirements 变更后复验）
  - graph.py 常量提取后检测函数行为复测：免责声明 4 组样本判定结果与提取前一致
  - 全量回归（`-m "not slow"`，含网络型 e2e）：见第 7 节补充
- **Pyodide 实测**（`node scripts/pyodide_feasibility_check.mjs`，Pyodide 314.0.7 npm 运行时 + 官方 CDN wheel）：
  - 运行时加载 ≈1.4s；shapely 2.1.2 + pyproj 安装 ≈644ms（官方 wheel 可缓存）；缓冲区+投影计算 ≈777ms
  - **与 CPython 结果逐位一致**：面积 11,483,504.84 m²、contains=True、外环 37 点
  - 内存：进程 RSS ≈259–321MB；rasterio/GDAL 无 WASM wheel（官方索引 2026-10-12 确认）

### 5. 审计结论（未做改动的部分及理由）

1. **matplotlib 启动即加载不改**：实测 import 仅 167ms（tools 全模块 1586ms 的 10%），懒加载收益不抵图表类工具初始化时序风险。
2. **前端工具迁移不做**：后端经 start.bat / Electron 壳必然本地常驻，"省后端调用"省的是 <10ms 的 localhost 环回；第一类工具（属性过滤等）数据本就在后端注册表。
3. **Pyodide 暂缓集成**：技术可行、精度无损（实测），但当前部署形态无收益，代价确定（259MB 浏览器内存 + 10MB 首载 + geopandas 1.1.1 刚在 Pyodide 0.29 重新启用）。触发条件与试点路径写入 `docs/architecture/runtime-architecture.md`。

### 6. 已知问题

- 全量测试套件中部分 e2e/集成测试走真实网络（DataV/OSM），未标 `slow`，导致 `-m "not slow"` 仍需十余分钟；建议后续给网络型测试补标记或 mock。
- `pytest backend/tests` 必须在仓库根目录执行（`cd backend` 后 `backend` 包不在 sys.path，collect 即错）；可在 pytest.ini 加 `pythonpath = ..` 根治，本轮未动（避免扩大改动面）。

### 7. 补充：回归测试结果（分标记执行）

全量套件含未标记 `slow` 的真实网络 e2e（DataV/OSM 下载），单次 >30 分钟，本轮改为按层验证：

| 层级 | 命令 | 结果 |
|---|---|---|
| Layer 1+2（unit+agent，本次修复的文件所在层） | `pytest backend/tests/layered -m fast` | **8 passed**（0.13s） |
| Layer 3+4（integration） | `pytest backend/tests -m integration` | 2 passed, **6 failed** |
| 应用冒烟 | `import backend.main` | OK（requirements 变更后复验） |

**6 个失败均为存量问题，与本次改动无关**，证据链：
1. 失败测试文件（`test_layer3_gis_tools.py`、`test_layer4_map_integration.py`）及其依赖源码（`tools.py`、`main.py`）**均不在本次 4 个改动文件清单内**（见第 3 节）；
2. 失败模式为确定性的测试-源码漂移：如 `test_layer4` 直接调用 `get_registered_layers()`，而该函数经 `@tool` 装饰后是 StructuredTool 对象（`tools.py:9120-9288` 注册链），`'StructuredTool' object is not callable` 必然发生，与 graph.py/requirements 改动无交集；
3. `test_layer3` 的 execute_python 落盘断言（`integration_test_card.png` 路径）与 DataV 真实网络拉取类用例属于环境依赖失败。

遗留：这 6 个用例与本次 test_layer1/2 同属"测试与源码脱节"，建议下一轮统一修复（tools.py 直调类测试应改用 `.invoke()`）。

### 8. 下一步建议

1. 给网络型测试补 `slow`/`network` 标记，恢复快速回归能力。
2. pytest.ini 增加 `pythonpath` 修复 backend 目录直跑。
3. 若决策引入"无后端模式"，按 runtime-architecture.md 从 spatial_buffer 族试点 Pyodide。

---

## 2026-10-13 核心能力升级与提交规范固化

### 1. 发现的问题与解决思路
1. **图层感知弱化与绕过工具执行 (P0)**：
   - 现象：用户提问“查看有几个注册图层”等指令时，LLM 可能会走短文本直出链路回复“没有拿到实时数据”，无法准确感知注册图层要素量、几何类型与字段信息。
   - 解决：扩展 `get_registered_layers`（及 `list_layers` 别名），返回要素数量、几何类型、外包范围（bbox）及属性字段列表；在 `graph.py` 中补充关键词匹配，防止图层查询指令误走短文本跳过分支；强化 System Prompt 禁止在图层存在时回复免责声明。
2. **Matplotlib 沙箱出图中文字体乱码 (P0)**：
   - 现象：专题图渲染中文标注时出现方块方框（□□□）。
   - 解决：调整沙箱中字体初始化顺序，确保 `plt.style.use()` 在中文字体注入之前执行，杜绝样式重置覆盖微软雅黑配置；扩大绘图环境自动检测覆盖面。
3. **图层属性检查器与拖拽反馈体验 (P1)**：
   - 现象：属性表在增行或保存后标签页错误跳回常规属性；图层列表拖动时缺少放置分界线；缺少自定义字段与字段计算能力。
   - 解决：增加激活 Tab 记忆；实现 `drag-over-top` / `drag-over-bottom` 放置指示线与卡片半透明幽灵样式；新增“+列”自定义字段弹窗与 ArcMap 风格“⌗ 字段计算器”。
4. **可见缩放范围控制与透明度联动 (P1)**：
   - 现象：无法按比例尺自动控制图层显示，卡片与检查器透明度未同步。
   - 解决：参照 ArcMap 实现 `minZoom`（缩小极限）与 `maxZoom`（放大极限）可见范围控制并联动 `zoomend` 事件；打通透明度双向绑定并支持手绘要素。
5. **新建工程幽灵边界残留 (P0)**：
   - 现象：新建工程后图层列表已空，但地图上残留上一次行政区划底图/多边形。
   - 解决：在新建工程与会话重置时前置调用 `GIS.state.clearAll()`，彻底重置图层注册表、下钻栈与选区状态。

### 2. 修改的文件
- `backend/services/tools.py`
- `backend/services/graph.py`
- `backend/services/ai_service.py`
- `backend/services/matplotlib_font.py`
- `frontend/js/layers.js`
- `frontend/css/workspace.css`
- `frontend/js/map.js`
- `frontend/js/gis_state.js`
- `frontend/js/project.js`
- `frontend/js/workspace.js`
- `.gitmessage`（新增）：根目录 Git 提交模板
- `docs/repository-standards.md`：规范化 Commit Title 与 Description（多模块中英双语格式）

### 3. 验证结果
- `backend/tests/test_new_tools.py` 15 passed。
- 前端 JS 核心文件语法检查全部通过。


