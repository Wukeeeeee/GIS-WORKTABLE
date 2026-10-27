# WTB 模块地图与审查边界

检查日期：2026-10-27。此文档按当前入口和调用关系建立导航清单，帮助逐模块审查；“已有检查”表示仓库中存在对应测试或扫描记录，不代表整个模块已完整验收。逐项证据和结果以 [`module-scan-progress.md`](module-scan-progress.md) 为准。

## 当前真实结构

- Web 前端由 `frontend/index.html` 按顺序加载 `frontend/js/*.js`，不是单一 SPA bundle；地图、聊天、图层、工程和工具面板分别由多个脚本共享 `window.GIS` 状态。
- FastAPI 路由集中在 `backend/main.py`；当前仓库没有 `backend/routers/` 目录。该入口同时处理聊天/SSE、上传、图层、项目、数据获取、设置、日志与工具调用。此为已确认的结构事实，不单独视为缺陷。
- AI 工具执行链为 `main.py` → `services/ai_service.py` / `services/graph.py` → `services/tools.py` 与参数/结果保护模块；大量 GIS 工具集中在 `tools.py`。
- GIS 数据发现和外部服务由 `backend/services/` 下的服务与 provider 子包处理；本地与远端服务覆盖不同，fixture 测试不代表在线服务验收。
- 任务历史有前端 `task.js` 本地状态，也有后端 `task_manager.py` / `history_service.py` 能力；二者属于不同状态面，不能因名称相近而假定共用持久化。

## 模块清单

| 模块 | 用户/API 入口与主要实现 | 关键状态/下游 | 已有检查证据 | 当前边界与风险 |
|---|---|---|---|---|
| Web 启动与工作区 | `frontend/index.html` → `js/app.js`, `js/workspace.js` | 活动面板、停靠状态、语言和会话上下文；下游各面板 | `workspace_dock_state.test.cjs` 等 | 多脚本共享全局状态；需要按功能链路而非单个脚本继续审查。 |
| 桌面端与本机 MCP | `desktop/main.js`, `backend/launcher.py`, `backend/mcp_server.py` | Web 服务进程、桌面窗口生命周期、MCP 工具暴露与本机配置 | `desktop/tests/main.test.cjs`, `backend/tests/test_launcher.py`, `test_mcp_server.py` | 启动/退出和 MCP 合约有自动化覆盖；本轮桌面主进程 29 项通过。完整 Electron 窗口、打包安装和跨机器配置尚未验收。 |
| 地图与图层注册 | `js/map.js`, `js/renderer_cesium.js`, `js/gis_state.js`, `js/layers.js`；`main.py` `/api/layer/*`, `/api/layers`；`services/layer_service.py` | 前后端图层名/版本、可见性、渲染器、工程恢复 | `layer_panel_rename.test.cjs`, `gis_state_fid_identity.test.cjs`, `map_layer_visibility.test.cjs`, `layer_symbology_persistence.test.cjs`, `renderer_cesium_clear.test.cjs`, `test_layer_service.py`, `test_layer4_map_integration.py` | 注册/删除/重命名队列及 2D 显隐有局部回归；3D 图层加载失败现有可见警告和定向测试。真实浏览器 2D/3D 异步渲染和真实并发仍未验收。 |
| 文件上传与图层交接 | `js/upload.js` → `main.py` `/api/upload` → `services/tools.py`/存储层 | 文件格式、CRS、预览、待发送图层、服务端注册 | `test_upload_vector.py`, `test_upload_raster.py`, `test_upload_handoff.py`, `test_upload_safety.py`, 前端 `upload_preview.test.cjs`, `api_provider_key_storage.test.cjs` | ZIP 多 Shapefile 歧义现已在解压前拒绝并测试；图层交接失败回滚、注册令牌同步及 ENOSPC 错误反馈有定向回归。隔离浏览器实测 GeoJSON/有效 CRS GeoTIFF 上传及后端成功后响应丢失的恢复；同一请求编号恢复后仅有一个可见图层和一个后端注册。原始 8000 故障仍未溯源，恢复缓存为进程内且有时限。 |
| AI 聊天与 Agent 流程 | `js/chat.js` → `/api/chat`, `/api/chat/stream`, `/api/cancel` → `ai_service.py`, `graph.py`；`execute_workflow` → `services/workflow.py` | 会话、工具步骤、重试/取消、SSE、图层操作、任务记录、多步 DAG 输出 | `test_stream_step_events.py`, `test_agent_retry_safety.py`, `test_workflow.py`, 前端聊天与执行卡测试 | Workflow 现把步骤执行中新注册的图层名暴露为上游输出；本轮新增 LangGraph custom stream 到现有 SSE 执行卡的步骤进度映射，后端集成及前端卡片回归通过。真实模型、真实浏览器内层 Workflow 进度、网络中断仍未验证。 |
| GIS 工具与参数/结果保护 | `main.py` `/api/tools/invoke`；`services/tools.py`, `tool_args_guard.py`, `result_guard.py`, `geo_qa.py` | 输入图层与版本、参数、几何/栅格结果、质量与来源元数据 | `test_spatial_tools.py`, `test_vector_gap_tools.py`, `test_raster_gap_tools.py`, `test_dem_analysis.py`, `test_spatial_stats.py` 等；扫描记录覆盖若干工具族 | `spatial_near` 使用局部 UTM 并校验距离；`spatial_voronoi` 验证点输入并使用局部 UTM；`spatial_cluster` 支持兼容旧调用的度数模式及局部 UTM 米/公里模式；`spatial_buffer` 拒绝跨日期变更线和 UTM 适用纬度外范围。`join_field` 对空连接键不匹配且避免行扩增；`spatial_sample` 现在拒绝负/非有限/超范围比例以及同时传入数量和比例。`hydrology_analysis` 按 CRS/仿射距离计算 D8 坡降并注册带来源、单位和质量提示的 GeoTIFF；真实地形水文准确性仍待外部基准验证。其他工具仍须逐项审查。 |
| 栅格运算与工程资源 | `js/raster_tools.js` → 栅格工具；服务端 `tools.py` 栅格函数及项目资源处理 | 原始 GeoTIFF、预览 PNG、CRS/像元单位、provenance、工程 assets | `test_dem_analysis.py`, `test_raster_provenance.py`, `test_project_raster_persistence.py`, `test_direct_invoke_e2e.py`；真实 SRTM-derived DEM 浏览器分析/保存/恢复记录 | 已在真实小范围 DEM 上完成坡度→5 类分位重分类→保存→刷新后手动重开，4 层、原始 TIFF/预览及来源/CRS/值单位/质量提示恢复；保存结果与五分位公式逐像元一致（3705 有效像元，各类 741），但未用外部地形基准或业务阈值验证适用性。重采样回归现通过 TestClient 请求实际预览 PNG 与原始 TIFF URL（均 HTTP 200）；先前磁盘路径断言错误地把百分号编码 URL 当成本地文件名，已修正测试，无生产代码改动。`spatial_interpolate` 现按局部 UTM 米制距离计算 IDW/RBF，过滤无效样本并支持 MultiPoint；结果注册 EPSG:4326 GeoTIFF，可再次重采样。合成数据服务测试验证插值→保存工程→重载→再分析；浏览器 UI 保存/重开尚未验收。工具限制扩展后经度范围≤6°、分辨率≤1024、距离计算≤5,000 万对并分块，RBF≤500点；这是未经硬件基准调优的初始阈值，小于6°但跨UTM分带仍需量化。`raster_calculator` 将非有限运算值写为 NaN/NoData 并在预览标为无效；读取前限制 400 万像元或 1600 万波段像元，表达式单位仍不可自动推导。该输入上限是原型保护阈值，尚未通过不同硬件的峰值内存基准调优。`raster_reclassify` 现在拒绝无效分级数、未知方法、非有限分类值和空区间；其他栅格工具、尺寸及 NoData 组合仍需针对性验证。 |
| 网络分析与地理服务 | `js/network.js` → `/api/network/*`、`services/network_service.py`、相关工具/外部 OSM 服务 | 路网、设施点、路径/OD/服务区结果 | `test_network.py`, `test_integration_e2e_v4.py` 等本地测试 | 有模拟上游和算法测试；真实 OSM/Overpass 限流、超时和大区域资源使用未全面验证。 |
| 数据发现与 GeoSource | `js/geosource.js`, `js/connector.js` → `/api/data/*`, `/api/geosource/*`, `/api/url-data/*` → discovery/provider/service | 搜索结果、下载文件、来源/CRS、异步作业、代理参数 | `test_data_discovery.py`, `test_data_provider_storage.py`, `test_geosource.py`, `test_geosource_proxy_redaction.py`, `test_url_gis.py` | GeoSource 代理及 URL GIS 手动跳转会在跨源时移除可识别的认证查询参数；ArcGIS token 单独作为请求参数的转发也覆盖了跳转用例。GeoSource、URL GIS 和共享云原生 HTTP 通道在公网/无法确认地址上不会通过 HTTP 明文发送可识别的 Key 或 URL 账号密码；明确内网 HTTP 仍可用但未加密。WMS/XYZ 手动 Key 仅随本次请求发送；认证查询参数识别与清理使用边界匹配，支持 `access_key` 且避免误删 `monkey` 等无关参数；GeoSource 含用户名/密码的源 URL 会在浏览器入口和后端代理入口拒绝，工程保存只保留无 Key 的服务地址和重新授权提示；认证 XYZ 的 `{-y}` 瓦片模板会在 URL 处理后保留。`GEOSOURCE_DB_PATH` 显式指向缺失文件时不再静默加载其他快照；搜索页码限制在实际页数内，避免超大页码溢出 SQLite 偏移量。目录卡片区分免费与部分免费，筛选文案明确包含部分免费服务；官方链接只使用备注前可解析的 HTTP(S) 地址，无有效地址时不显示空复制按钮并说明目录未提供地址。Shapefile 同名替换的进程内异常回滚已增加定向测试；真实 Provider、进程崩溃中断和多文件系统故障仍未验证。 |
| 项目保存、恢复与导出 | `js/project.js` → `/api/projects/*` → `services/project_service.py`；地图/聊天导出由对应 UI 与工具实现 | 项目快照、图层顺序/元数据、矢量 blob、栅格资源、导入包 | `test_project_raster_persistence.py`, `test_layer_group_persistence.py`, `project_load_race.test.cjs`, 地图导出组合测试；真实 DEM 工程往返浏览器记录 | 已发现并修复矢量 blob 缺失/内容不匹配时导出静默漏文件；工程导入在请求接收与解包阶段设限：包上限 1 GiB、解压上限 1 GiB、最多 10000 个条目；阈值未经设备基准，超限会拒绝导入。 |
| 任务/执行历史 | `js/task.js`, `js/history.js`；后端 `/api/tasks/*`, `/api/history/*` → `task_manager.py`, `history_service.py`，工具包装在 `tools.py` | 前端 localStorage 任务卡状态、后端跨轮任务上下文和工具执行历史 | `task_cancelled_status.test.cjs`, `chat_send_lifecycle.test.cjs`, `test_task_manager.py`, `test_swipe_history.py`, `test_direct_invoke_e2e.py`, `history_race.test.cjs` | 前后端任务状态用途不同；前端未终态重载后标记为待核对的中断。工具历史存储损坏时暂停覆盖并发出警告；清空仅在落盘成功时生效。`create_swipe` 的图层缺失/相同图层错误现计为执行失败；未验证真实模型的工具选择行为。 |
| 设置与凭据 | `js/settings.js`, `js/api.js` → `/api/user-settings`, `/api/geo-credentials/*`, `credential_store.py` | Provider 配置、服务凭据和浏览器本地设置 | `test_user_settings_provider_keys.py`, `settings_geo_credentials.test.cjs` 等 | 模型 Provider Key 仅保留在浏览器本地；高德 Key 通过本机加密凭据库支持跨浏览器同步。开机不再逐个 Provider 发送可能计费的连通测试，改由用户手动测速。自定义模型接入需用户从模型服务商控制台获取 Key；并非所有设置的真实供应商存储/连通均已验收。 |
| 本地 API 信任边界与代码执行 | `backend/main.py` CORS/危险路由、`launcher.py`, `desktop/main.js`；`execute_python` 在 `tools.py` | 项目/图层/任务数据、工具调用、上传、代码子进程 | `test_local_cors_policy.py`, `test_geosource_proxy_redaction.py`；`execute_python` 凭据测试、上传安全测试、`test_output_file_safety.py` | 全局 CORS 只允许 localhost/loopback 来源；浏览器 API 请求（包括读取和状态变更）会拒绝非本机 Origin 和标记为跨站的请求，包括 multipart 上传及会切换当前工程的 GET。Origin 与 Fetch Metadata 只约束浏览器来源，不认证无这些请求头的本机/MCP 客户端；启动器默认绑定 loopback，手动网络暴露仍不安全。`execute_python` 会按变量名过滤一部分常见凭据，并移除带认证的 HTTP(S) 代理变量；导入 OSMnx 不会自动探测 Overpass。它仍不是操作系统级沙箱，文件、网络和资源未隔离。`/output` 对 HTML/SVG 类活动内容使用不允许 same-origin 的 CSP sandbox，并对路径做 realpath 边界检查；相关回归测试不等于完整浏览器安全审计。 |
| 国际化 | `js/i18n.js` + `data-i18n` 与组件动态格式化 | 当前语言、字段/菜单/工具生成的动态文案 | raster inspector、tool menu、spatial stats 定向测试；本轮浏览器检查分析工具启动器及 AI Provider 卡片 | 已修复分析启动器标题、4 个分类及 20 个工具名的英语显示，并覆盖启动后切换语言；AI Provider 接入提示现提供中英文，工作台主工具菜单英语状态全部正确。分析工具参数窗口、其他动态 GIS 元数据和所有面板仍未证明完整本地化。 |

栅格模块补充：`raster_reclassify` 现拒绝无效分级数、未知方法、非有限类别值和空区间；`raster_focal_stats` 现只接受 3/5/7 窗口，NoData 按哨兵值精确匹配，majority 输出保留输入像元值，并按注册图层名命名结果；`euclidean_distance` 精确匹配 NoData/source value，并按注册图层名命名默认结果；`raster_extract_by_mask` 使用显式掩膜与无冲突 NoData，并拒绝缺 CRS/转换失败。水文及栅格相关测试夹具恢复共享临时输出目录，避免组合运行时污染后续 API 产物路径。2026-10-26 浏览器验收已从恢复的 EPSG:4326 SRTM-derived DEM 再运行坡度分析，保存、刷新、从最近工程重开后确认 4 个栅格图层和结果元数据恢复；真实地形外部基准仍未验证。详见扫描进度中的 2026-10-26 记录。

## 审查状态解释

- **已验证的局部场景**：存在清晰输入、复现步骤和适用测试/浏览器证据；不自动代表整个模块完成。
- **本地自动化覆盖**：fixture、mock 或受控数据路径通过；不能替代真实模型、外部 Provider、浏览器网络故障或生产部署验证。
- **待运行确认**：记录了具体限制和需要的环境，不当作已发现缺陷，也不因为缺少环境而盲目改代码。

本轮继续审查时应优先从核心用户任务链中选取未闭环的验证边界；若已记录为高风险但需架构决策的执行隔离问题，只做风险管理，不擅自改变权限或执行环境。

栅格工具补充：`raster_to_feature` 已拒绝无 CRS 栅格、按精确 NoData 哨兵保留邻近有效像元、拒绝非 4/8 连通度及负数/非有限简化容差；简化单位现说明为栅格 CRS 坐标单位。当前 `test_raster_gap_tools.py` 68 项通过。真实 DEM 的矢量化、地图复用和工程保存/恢复仍待浏览器验收。

`surface_volumes` 现对输入 NoData 精确匹配，并以 NaN 编码差值产品 NoData，避免把合法零高差误标为缺失；覆盖测试在最近组合回归中通过。真实地形适用性及项目往返浏览器验收仍需单独验证。

`feature_to_raster` 对零范围维度按显式像元尺寸居中扩展，以请求的坐标单位像元尺寸创建网格，并在栅格化前限制 400 万像元及拒绝无效 cell_size；其覆盖测试文件在最近组合回归中通过。阈值未经设备内存基准调优。

`create_fishnet` 现拒绝无效 cell_size、限制最多 10000 个网格面，并报告 ceil 划分后的实际格宽/高；`test_coverage_gap.py` 与栅格分析测试组合共 105 项通过，资源阈值尚未设备基准调优。

代价栅格模块：`cost_distance` / `least_cost_path` 现按栅格 CRS 对齐 WGS-84 图层、精确处理 NoData、拒绝错误吸附的边界外点，并设置图规模保护；cost-distance 输出文件名经过安全规范化。与覆盖测试组合 105 项通过；实际道路/阻力面语义、真实 GIS 基准和浏览器使用仍未验收。

矢量空间连接：`spatial_join` 现能保留输入中与 GeoPandas 内部 `index_right` 冲突的属性字段；新增回归同时覆盖目标与连接输入。该用例及栅格/覆盖组合共 280 项通过；大图层资源与真实属性表展示未验证。

矢量叠置：intersection/union 现保留混合几何交集/结果，线结果不再被错误报告为零面积。`test_spatial_tools.py` + `test_spatial_robust.py`：188 项通过；真实大图层及浏览器混合几何显示未验收。
