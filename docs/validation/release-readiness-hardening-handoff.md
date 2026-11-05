# GIS WorkTable 发布候选版可靠性攻坚

> 状态：进行中。本文记录当前可验证进度，不表示发布候选版已完成。

## 发布审计清单（状态截至 2026-11-05）

| 阶段 | 状态 | 已有证据 | 仍需完成/未验证 |
| --- | --- | --- | --- |
| 1. 启动、首次使用与恢复 | **部分完成** | 干净 Python 3.13 环境安装与运行时自检；launcher start/check/stop；Electron 31.7.7 隔离窗口启动并连通本地后端；`desktop/tests/main.test.cjs` 主进程启停与恢复测试 29 项、`backend/tests/test_launcher.py` 启动器探活测试 38 项均通过。包含 Windows 单实例 IPC、进程树关闭和启动器退出码检查。 | 无 Python 干净机器冷启动、失败恢复及打包安装升级路径仍未完整验收；当前仓库没有声明的 Electron 打包脚本/配置。 |
| 2. 上传、图层、工程生命周期 | **部分完成** | 矢量上传/握手与取消回归；当前工作树隔离浏览器完成合成 GeoJSON 上传→图层面板确认→Shapefile ZIP 下载及五组件、属性、几何和 EPSG:4326 回读；`.giswork` 导入导出、栅格资产持久化和隔离 Electron 保存/重启/重开也有证据；COG alpha/nodata、分类调色板和 GeoJSON 超大整数往返有本地回归；工程容量满额时拒绝新建、保留旧工程且允许更新有定向回归；数据发现/矢量下载导入服务 24 项 mock 定向回归通过；URL GIS 请求的本地 mock 安全路径已复审。 | Electron UI 删除、打包版本往返及大型/外部真实用户数据仍未验收；未访问真实外部 GIS/COG 服务。 |
| 3. 分析正确性与结果管理 | **部分完成** | SQL、CRS/几何校验、空间工具和结果产物已有多组定向回归；网络路由/服务区/最近设施服务完成定向审计，17 项合成路网测试通过；文档记录过真实 DEM 分析和重分析。 | 全部 CRS/单位组合、真实栅格/矢量/道路边界、失败后资源清理与重复运行仍未逐类验收。 |
| 4. AI 工具与工作流 | **部分完成** | 只读 SQL、任务持久化失败、事件顺序、取消/重试边界有针对性测试。 | 未使用真实在线模型；外部 provider、长运行取消和远程执行仍有环境边界。 |
| 5. 浏览器/桌面交互 | **部分完成** | 当前源码隔离浏览器完成本地 GeoJSON 上传、图层核验、Shapefile 导出，并用隔离测试守卫实测历史工程单项删除 UI：无确认框且发出 DELETE（守卫返回 409、合成工程保留）；隔离 Electron 窗口完成多边形样例加载、保存、应用重启及重开恢复；主进程与 launcher 定向测试通过。 | 浏览器单项删除确认修复需等待授权；地图 PNG/PDF 导出 UI 因隔离环境未配置 AI 模型而未触发；Electron 工程删除/导出 UI、关键失败提示及安装包路径解析仍待检查；仓库当前未配置可复现的打包构建。 |
| 6. 发布就绪复核 | **未完成** | 本文持续记录真实命令、结果、修复与风险；关键定向批次已复验。 | 仍需结束审计清单、检查文档/剩余风险并完成最终实际 diff 复核；不得以定向测试通过代替完整发布候选验收。 |

## 本轮范围与工作区边界

- 项目：`E:\my_repo\Gis-WorkTable`
- 已保留开始时存在的未提交修改，未提交、推送或发布。
- 原有脏文件包括 `backend/services/tools.py`、`backend/services/workflow.py`、相关测试和 `docs/validation/module-scan-progress.md` 等。
- 经用户明确授权，GPT 仅在已修改的 `backend/services/sql_engine.py` 与 `backend/tests/test_sql_engine.py` 追加一项 SQL 越界整数修复和回归测试。其余既有改动未编辑。

## 阶段验证

| 阶段 | 检查 | 结果 | 边界 |
| --- | --- | --- | --- |
| 启动/桌面客户端 | `D:\python\python.exe -m pytest -q backend/tests/test_launcher.py -p no:cacheprovider --tb=short` | 38/38 通过 | 受控启动器与临时 Windows 子进程；未验收完整 Electron 窗口 |
| 桌面启动 | `node --test desktop/tests/main.test.cjs` | 29/29 通过 | 包含真实 Windows IPC 和进程树测试；不代表完整 GUI 验收 |
| 工程生命周期 | `D:\python\python.exe -m pytest -q backend/tests/test_project_service_import.py backend/tests/test_project_raster_persistence.py -p no:cacheprovider --tb=short` | 49/49 通过 | 全局 Python 环境；测试覆盖真实服务函数的工程/栅格持久化用例；另有隔离 Electron UI 保存→重启→重开实测（见下文） |
| `.giswork` 包往返与栅格完整性 | 同上；Gemini 最终运行与 GPT 独立复验 | Gemini 52/52（12.91s）；GPT 最终复验 52/52（10.68s） | 包含三项新增回归：篡改资产拒绝、矢量往返、带陈旧来源 URL 的 source_asset-only 导入/重载 |
| 前端工程/上传 | `node --test frontend/tests/project_save_sync.test.cjs frontend/tests/project_load_race.test.cjs frontend/tests/project_delete_save_race.test.cjs frontend/tests/project_delete_all_partial.test.cjs frontend/tests/upload_preview.test.cjs frontend/tests/api_upload_timeout.test.cjs` | 72/72 通过 | 自动化测试；未进行完整浏览器手工流程 |
| 后端上传 | `D:\python\python.exe -m pytest -q backend/tests/test_upload_raster.py backend/tests/test_upload_vector.py backend/tests/test_upload_safety.py backend/tests/test_upload_handoff.py -p no:cacheprovider --tb=short` | 84/84 通过 | 包含 GeoTIFF/矢量/ZIP 安全边界；5 条 GDAL、CRS 或重复 ZIP 名警告来自测试情形 |
| SQL/空间工具/工作流 | `D:\python\python.exe -m pytest -q backend/tests/test_materialize_workflow.py backend/tests/test_spatial_tools.py backend/tests/test_sql_engine.py backend/tests/test_stream_step_events.py backend/tests/test_workflow.py -p no:cacheprovider --tb=short` | 修复前 361 通过、4 失败；修复后 366/366 通过，1 条 Pandas 日期推断警告 | 本轮 targeted regression；未运行全量后台套件 |
| Diff 格式 | `git diff --check` | 通过 | Git 对若干既有 LF 文件提示未来可能转换为 CRLF；没有 whitespace error |

## 已复现并修复

### SQL 被无关图层中的 uint64 属性拖垮

- **复现：**运行空间工具测试后执行 SQL 工具测试时，空间工具测试留下含 `2**63 + 17` 的注册图层；`query_spatial_sql` 将全部已注册图层传给 `execute_layer_sql`。SQLite 绑定超出有符号 64 位范围的 Python 整数时抛出 `Python int too large to convert to SQLite INTEGER`，即使查询目标是另一个普通图层也失败。独立构造“普通目标图层 + 无关 uint64 图层”同样可复现。
- **影响：**一个未被查询的图层可以让 SQL 查询整体失败；同一套件单独运行时不失败，组合运行后暴露了该问题。
- **修复：**`backend/services/sql_engine.py` 对超出 SQLite int64 范围的整数按十进制字符串绑定，保留精确数字文本并避免整个查询中止；范围内整数保持原数值类型。
- **回归：**`backend/tests/test_sql_engine.py` 覆盖正、负越界整数与无关目标图层查询，并检查越界值以精确十进制文本读取。
- **限制：**越界整数在 SQL 结果中是文本；对这些极端值进行数值排序/聚合的语义仍需明确产品契约。没有发生精度舍入，但不能据此宣称任意精度 SQL 算术已支持。

### `.giswork` 栅格资产完整性与旧来源 URL 恢复

- **缺陷证据：**受管栅格以 `<sha256 前 20 位>.<扩展名>` 命名，但导入原先只检查 ZIP 成员路径和文件存在。新增回归在文件名不变时改写 TIFF 字节；修复前该包会通过结构/路径检查并被接纳，修复后导入因哈希不符而拒绝，且没有残留工程目录。
- **来源资源恢复：**旧式合法包可仅含 `source_asset`，并携带旧机器的 `project_id` 与 `/api/projects/<old-id>/assets/...`。`load_project` 原先只在预览 `asset` 存在时重写引用；新增回归验证仅含 `source_asset` 的包激活后返回当前项目 URL，并通过接口与下游栅格查找读取原始 TIFF。
- **额外往返覆盖：**矢量回归完整导出/导入多边形和点的几何、属性、地图状态、消息、样式与注册令牌。详细变更和兼容性记录见 [project-package-roundtrip-handoff.md](project-package-roundtrip-handoff.md)。
- **验证：**`backend/tests/test_project_service_import.py` 与 `backend/tests/test_project_raster_persistence.py` 共 52 项通过；Gemini 最终运行 12.91s，GPT 在最终 stale-URL 回归变更后独立复验 10.68s。
- **限制：**只有符合当前 20 位小写十六进制命名契约的资产按内容哈希校验；不符合该契约的旧资产仍执行路径与存在性校验，以保留旧包导入兼容性。

### DataV 行政区名称误映射到省级代码

- **复现：**修复前直接调用 `_find_adcode("吉林市")` 返回 `220000`（吉林省）；城市边界下钻因此可能取省级子项，而不是吉林市的区县。
- **修复：**`backend/services/datav_service.py` 保留精确省名优先，然后查城市/区县映射；只有精确映射和后缀变体都未命中时，未知行政区名称返回 `0`，不再按省名子串猜测。
- **回归：**新建 `backend/tests/test_datav_service.py`，mock 城市表为 `{"吉林市": 220200}`，检查吉林市返回地级市代码、吉林省仍返回省代码，且未知“市”名称不映射到吉林省。命令 `D:\python\python.exe -m pytest -q backend/tests/test_datav_service.py -p no:cacheprovider --tb=short`：2/2 通过；`git diff --check -- backend/services/datav_service.py` 通过。
- **归属与限制：**因 Gemini Antigravity 生成接口连续返回 EOF 且未产生项目文件改动，本修复由 GPT 实施。Gemini 随后在原协作会话独立审查，结论为未发现实质性问题，并报告 2/2 回归通过；GPT 已核对该审查回传。未调用 DataV 网络服务；该结果仅验证名称映射函数及 mock 回归，不等于真实边界获取流程已验证。

### 图层检查器漏报非数字 GeoJSON 坐标

- **复现与依据：**旧 `inspect_geojson` 对 `Point([True, 30])` 与 `Point(["100", "30"])` 均返回 `invalid_geom_count=0`，且 `coord_sample=[]`。Shapely 会将布尔值和数字字符串强制转成坐标值；GeoJSON 位置规范要求由至少两个数字构成。相关规范见 [RFC 7946 §3.1、§3.1.1](https://www.rfc-editor.org/rfc/rfc7946.html#section-3.1)。
- **修复：**`backend/services/layer_service.py` 增加类型感知的坐标结构检查，再调用 Shapely 做拓扑检查；拒绝 bool、字符串、非有限数、少于两个分量及畸形嵌套。区分 Feature `geometry: null`（计入 null）和对象中缺失/空 `type`（计入 invalid）；保留根空坐标数组与空 GeometryCollection 的空几何语义。
- **回归：**`backend/tests/test_layer_service.py` 从 4 项扩至 12 项，覆盖点/线/面与 GeometryCollection 坐标、畸形嵌套、空几何与 Feature null geometry，并检查混合 FeatureCollection 的 bbox/CRS 仍稳定。Gemini 执行 12/12 通过；GPT 独立复验命令 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & '.venv\Scripts\python.exe' -m pytest -q backend/tests/test_layer_service.py -p no:cacheprovider --tb=short`：12/12 通过（0.29s）；`git diff --check -- backend/services/layer_service.py backend/tests/test_layer_service.py` 通过。
- **用户流影响与限制：**`/api/layer/inspect` 返回 `invalid_geom_count`，但目前 `frontend/js/layers.js` 中对应局部变量未渲染到面板；这是后端 API 的计数正确性修复，不宣称修复了前端可见提示。未进行真实浏览器检查。Gemini 交接见 [layer-service-inspection-handoff.md](layer-service-inspection-handoff.md)。

## 关键流程状态清单（2026-11-05）

| 流程 | 状态 | 当前证据 / 缺口 |
| --- | --- | --- |
| 启动器检查、启动/停止与错误恢复 | 部分通过 | GPT 在隔离干净 Python 3.13 环境运行 `scripts/check_runtime.py`（依赖就绪）、`uv pip check`（137 包兼容）及启动/环境测试 45/45；另由真实 `backend.launcher` 在 18765 端口启动、健康检查通过并成功停止，CUA 浏览器的工作台主页和最近工程列表正常显示。隔离 Electron 开发源码副本也完成保存后重启重开；完整打包 GUI 与脱离开发机的冷启动仍未验收。 |
| 矢量上传与检查器 | 浏览器流程已走通 | 使用 `D:\python\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` 启动本地服务，在真实内嵌浏览器导入仓库合成样例 `data/sample_delivery_test.geojson`：预览显示 3 要素、Polygon/LineString/Point 和 5 字段；上传后图层列表出现 3 要素，属性表读出属性和值，检查器显示 EPSG:4326、degree 和数据范围。另在隔离临时存储中上传合成 bowtie GeoJSON，真实浏览器显示无效几何数为 1 且呈警示样式。1440×900 下 `scrollWidth == clientWidth`（无整页水平溢出）；默认 319×704 内嵌视口下属性表使用内部横向滚动。 |
| 浏览器项目保存、重载、导出与导入 | 部分通过 | 工作区中保存的合成分析工程可在刷新后从最近项目显式恢复；含源 DEM 和坡度结果的 `.giswork` 导出包经 ZIP CRC 与 TIFF 校验，并在隔离的临时项目存储内由真实 UI 导入成功。前端生命周期定向回归 64/64 通过，另修复了跨工程迟到认证回调污染。当前用户工作区的 UI 导入请求因工程数达到 30 上限返回 HTTP 400；没有删除旧工程。 |
| 真实矢量分析、结果登记与工程恢复 | 已验证（合成样例） | 内嵌浏览器对合成 GeoJSON 执行 100 m 缓冲：界面报告 3 个结果要素；图层列表登记 3 个 Polygon；检查器显示 0 空几何、EPSG:4326、处理来源/输入图层/参数。保存后刷新，再从 Home 最近工程恢复，原始层和缓冲结果层均恢复，检查器保留处理记录。真实生产矢量数据未覆盖。 |
| 栅格上传、分析、导出/导入与结果再次使用 | 已验证（合成 DEM） | 浏览器上传 32×32、30 m、EPSG:32651 合成 DEM，执行坡度并登记第二个栅格结果；导出包含源/结果 TIFF，UI 在隔离项目存储导入后保留 2 层，再对导入的坡度结果运行一次坡度并成功登记第三层。分析值与已知平面理论坡度一致。真实外部 DEM、栅格边缘行为及 Electron 栅格流程仍未验收。 |
| AI 工具与工作流 | 自动化通过，真实模型未验 | 干净 Python 3.13 环境下 SQL、空间工具、DataV、工作流、工作流物化、流事件、取消、结果守卫和任务持久化等定向用例均通过；手动分析工具回归验证 `{ok:false}` 不再进入成功展示/结果应用，失败按钮状态可恢复；task 元数据写盘失败时内存不再误报成功；聊天完成后的迟到图层恢复不再写入已被替换的工作区。未调用真实模型，也未在浏览器发送 AI 请求或真实并发锁冲突。 |
| 远程数据、凭据与外部 GIS 服务 | 未验证 | 本轮 DataV 使用 mock；浏览器地图底图显示 Bing Maps，外部底图不构成分析数据或真实第三方服务验收。 |
| 最终发布候选审查 | 进行中 | 已复核当前工程包、DataV、图层检查器和分析工具失败反馈的实际 diff；其余全库未审计范围及环境限制尚未关闭。 |

- **UI 运行边界：**本轮只上传仓库合成 GeoJSON 和新生成的合成 DEM，未提供或上传用户个人文件，也未触发 AI 请求。此前 UI 轮次使用 PID 23424、18928、23316；本次矢量分析使用 PID 41084，隔离栅格导入服务 PID 38964；这些本地服务均已停止。页面使用 Bing 底图；DOM、包内容和计算值证明本地流程，不证明离线底图或第三方服务可靠性。
- **项目恢复行为：**浏览器页面重载后回到空白工程；从“打开工程”的已保存项目列表选择“恢复”后，合成工程及其 3 个要素恢复成功。故验证通过的是显式打开/恢复路径，不是刷新自动恢复。
- **分析结果恢复行为（本轮复验）：**`data/sample_delivery_test.geojson` 在隔离的空白浏览器工程中导入后，执行 100 m Buffer；UI 显示完成，结果层为 3 个 Polygon、0 空几何，检查器显示 EPSG:4326、输入层 `sample_delivery_test_2.geojson` 和 100 m 参数。保存为 `QA buffer analysis roundtrip 2026-11-05`，刷新后从 Home 最近项目打开，恢复 2 个图层；结果层检查器仍显示 Buffer processing provenance。该验证证明合成矢量分析输出可登记并经工作区保存/恢复继续使用，不证明栅格结果或 `.giswork` 中该分析结果的 UI 导入/导出。
- **导出文件：**本轮导出生成于 `C:\Users\13469\Downloads\QA synthetic save-reload 2026-….giswork`（文件名中省略号为界面显示的实际字符）。ZIP 包含 `project.json` 与一个 gzip GeoJSON 资产，CRC 检查无损坏；文件保留在下载目录，未清理。
- **本地状态保留：**UI 检查后观察到 `cache/projects/index.json` 和 `cache/projects/proj_3fddd0fe` 的时间戳为 02:32；运行前未记录这些对象的内容，因此无法确认应用自动写入的范围。没有读取其加密内容、清理或删除这些项目缓存；后续复验应继续保留。

## 环境与协作限制

- 早期验证时项目 `.venv` 的 Python 3.13 环境缺少 `keyring`，工程生命周期测试曾有 34 项因 `ModuleNotFoundError` 失败；`backend/requirements.txt` 已声明 `keyring>=25.0.0`。本轮后续已按下方“项目 `.venv` 声明依赖与定向测试”记录安装声明依赖并完成定向复验，因此这不是当前已知的依赖缺口。
- 早期通过 `uv pip install` 修复时 PyPI 网络连接被拒绝；随后改用全局 Python 的 pip 将声明依赖安装到项目 `.venv`，没有改 requirements 或锁文件。全局 Python 也曾用于工程测试，相关历史结果不代表当前 `.venv` 状态。
- Antigravity 直接桥接曾因 agent API 本机 RPC 端口拒绝连接而无法创建/发送任务；旧 worker 的 `ready` 只检查环境变量，曾错误报告就绪。2026-11-05 清理了已失去父进程的旧 bridge worker、重启当前 worker，并将 `C:\Users\13469\.gemini\config\sidecars\codex-client-bridge\worker.mjs` 的健康状态改为实际 TCP 探测。端到端验证 `new` 和同会话 `send` 均收到 Gemini 精确回复；状态显示 `agentApiReachable=true`。之后在原会话 `4af80f9e-87fb-4dd8-a6c0-9891858fd586` 恢复工程包子任务，Gemini 提交了代码与交接，GPT 审阅 diff 并独立复验 52 项针对性测试。
- 之前的 Gemini 会话连续出现生成接口 EOF；本轮新建同目标的短会话 `9a323fa6-d167-4012-9b78-666a9ed0e32f` 后成功完成 `layer_service` 实施、定向测试和交接。GPT 独立复核发现交接对空 `GeometryCollection` 的文字与代码不一致，已在同一 Gemini 会话修订；随后 GPT 复跑 12 项测试并通过。此次 Antigravity 界面未显示上下文用量仪表。
- Node 根目录模块解析未找到 `playwright`、`playwright-core` 或 `electron`。本地内嵌浏览器已完成矢量上传、属性检查、缓冲及坡度分析、保存/显式恢复、工程包导出；在隔离临时项目存储完成 `.giswork` UI 导入和结果再次分析。当前用户项目存储因达到 30 个工程上限而阻止导入。Electron 开发源码副本已实测工程保存后重启重开；打包 GUI、真实模型和外部 GIS 分析服务仍未验证。

## 后续工作

1. `.giswork` 工程包往返、DataV 查码和图层检查器三个子任务均有具体修复/测试记录；继续分析结果登记、真实分析往返与失败清理边界。
2. 审计未覆盖的上传后分析结果登记、工作流失败恢复及重试/取消路径，优先复现数据丢失、错误结果或误报成功。
3. 继续在可用本地环境验证栅格分析后保存/重载/导出的真实浏览器路径；把 UI 观察与自动化测试分开记录。`invalid_geom_count` 已通过真实本地浏览器和 VM 回归。
4. `.venv` 已补齐缺失的声明依赖；另在仓库外的隔离 Python 3.13 环境从 `backend/requirements.txt` 干净安装并通过 600 项关键定向回归。Electron 桌面打包、完整 GUI 和脱离开发机的冷启动仍需验收。
5. 完成剩余审计与 GPT 对 Gemini diff 的逐项复核后，再更新本文状态和最终未验证清单。

## 2026-11-05 追加验证

| 路径 | 命令 | 结果 | 边界 |
| --- | --- | --- | --- |
| 全量前端自动化 | `node --test --test-concurrency=4 --test-reporter=spec`（工作目录 `frontend/`） | 429/429 通过，0 失败 | 覆盖当前前端测试文件；不等于真实浏览器视觉验收 |
| 地图导出、图层样式与可见性 | `node --test frontend/tests/map_export_composition.test.cjs frontend/tests/map_layer_visibility.test.cjs frontend/tests/layer_symbology_persistence.test.cjs` | 52/52 通过 | 自动化交互契约；未替代完整浏览器/Electron 视觉验收 |
| 工程打开竞态 | `D:\python\python.exe -m pytest -q backend/tests/test_project_open_race.py -p no:cacheprovider --tb=short` | 7/7 通过 | 受控并发与项目状态测试 |
| GeoJSON 图层检查 | `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & '.venv\Scripts\python.exe' -m pytest -q backend/tests/test_layer_service.py -p no:cacheprovider --tb=short` | Gemini 12/12；GPT 独立复验 12/12（0.29s） | 服务函数与结构化 GeoJSON 用例；另用隔离临时项目及合成 bowtie 在真实本地浏览器验证 `invalid_geom_count=1` 警示显示。生产数据、大型图层仍未覆盖 |

以上测试后工作区其他原有脏文件仍保留；发布就绪状态仍为进行中。

### 2026-11-05 本轮 DEM 坡度与 `.giswork` UI 往返

- **合成输入：**`D:\python\python.exe` 的 rasterio 创建 32×32 float32 DEM，EPSG:32651，像元 30 m，值面为 `z = 100 + 0.5·x + 0.25·y`（输入高程按米构造），NoData=-9999。初次创建受进程 `PROJ_LIB` 指向旧 PostGIS PROJ 数据库影响而失败；仅对生成命令设置 rasterio 自带的 `proj_data`/`gdal_data` 后成功，未改系统变量或项目配置。
- **真实界面分析：**在本地 WorkTable 浏览器上传 DEM，运行 Slope。界面成功信息称生成 `gis-worktable-qa-dem-20261105_slope.tif` 并注册为可继续分析的栅格图层；层列表出现源/结果 2 个 Raster 层。检查器显示 EPSG:32651、30×30 m 像元、32×32 大小、坡度单位度、有效像元 87.89%。该小样例的边缘 NoData 比例触发质量提示，不作为应用缺陷。
- **像元数值复核：**输出坡度 TIFF 从实际 UI 导出的 `.giswork` 包读取，1024 像元中 900 个有效；有效值 min=max=mean=`1.067520260810852°`。理论值 `atan(sqrt((0.5/30)^2+(0.25/30)^2))` 转度约为 `1.06752°`，与输出一致。输入单位字段未声明；这是合成值的已知构造，不代表真实 DEM 单位识别。
- **包结构与完整性：**`C:\Users\13469\Downloads\Untitled project.giswork` 包含 `project.json`、源和坡度 TIFF 各一份及两张 PNG 预览；`ZipFile.testzip()` 返回 `None`。项目元数据保留 EPSG:32651、30 m 像元、源 TIFF 与坡度结果的处理来源。该本地测试文件保留，未清理。
- **用户存储导入阻挡：**在原工作区端点上传同一包，`POST /api/projects/import` 返回 `400`，具体为“工程数量已达到上限（最多 30 个）；请先删除不需要的工程后再导入”。在不删改既有工程的前提下，没有继续向该存储导入。
- **隔离 UI 导入与复用：**启动第二个本地 UI 服务，将 `project_service._PROJECT_DIR`、`_BLOB_DIR`、`_INDEX_PATH` 在该测试进程内指向新建的 `%TEMP%` 项目存储（临时 runner：`%TEMP%\gis-worktable-isolated-uvicorn.py`）。真实 UI 导入刚才导出的 `.giswork` 成功，源与坡度层恢复；坡度结果检查器仍显示源图层、EPSG:32651、32×32、30 m 和有效像元比例。对导入后的坡度层再次执行 Slope，第三个结果栅格成功注册，证明该包结果不止可查看，也可再次用于分析。isolated store 与导出包均为本轮测试产物。
- **边界：**这是合成 DEM 和本机后端的界面/数值集成验证；不是生产 DEM、真实外网数据或 Electron 验收。用户原缓存未清理，之前两个本地服务已停止后才结束本轮；新建的测试 workspace 记录保留以便追溯。

### 本轮浏览器分析结果往返

- **运行：**`D:\python\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`，PID 23316；本地内嵌浏览器导入仓库合成文件 `data/sample_delivery_test.geojson`，对其运行 100 m Buffer。
- **结果证据：**操作反馈“已为图层创建 100.0m 缓冲区，3 个要素”；Layers 面板新增 3 要素 Polygon 结果层；检查器显示空几何数 0、字段空值数均为 0、EPSG:4326、操作 Buffer、输入层名和 100 m 参数。
- **持久化复验：**保存到 workspace，浏览器 reload 后工程回到空白态；从 Home 的 Recent projects 显式 Open 后，工程恢复 2 个图层，结果层仍有 3 个要素，检查器保留处理来源。此次没有测试刷新自动恢复，也没有成功验证该含分析结果工程的 `.giswork` 导出。
- **边界：**数据为仓库合成 GeoJSON；这是本地界面与本地后端的集成验证，不是生产数据或 Electron GUI 验收。使用 Bing 底图不构成外部 GIS 分析服务验证。PID 23316 已在验证后停止；生成的 `QA buffer analysis roundtrip 2026-11-05` workspace 工程保留，未清理。截图仅在验证过程中查看，未另存为交付文件。

### 分析工具失败反馈与结果完整性（Gemini + GPT）

- **缺陷证据：**手动工具 API 在共享 GIS 锁被占用时会正常返回 HTTP 200 和 `{ok:false, busy:true, error:"当前 GIS 工作区正在处理另一项操作"}`，而不是抛 HTTP 异常。前端原来把所有 resolved JSON 都送去成功结果处理；workspace feedback 只读 `response`，busy 响应会显示通用空结果；没有 workspace 时则继续调用 `applyToolResult`，可能把失败响应当作成功结果应用。
- **修复范围：**Gemini 在确认干净归属后仅修改 `frontend/js/raster_tools.js`、`frontend/js/spatial.js` 及对应 `frontend/tests/raster_tools_layers.test.cjs`、`frontend/tests/spatial_fields.test.cjs`。两处执行器在应用结果前校验 `ok:false`/错误字段，统一转入错误反馈；恢复运行按钮并避免失败结果调用 `applyToolResult`。Raster 成功路径另刷新可选图层列表。
- **回归证据：**新增 workspace 与 standalone 模式下失败响应回归，以及 raster 成功后按钮复位/图层列表刷新的回归。Gemini 与 GPT 在最终 EOF 格式修正后均运行 `node --test frontend/tests/raster_tools_layers.test.cjs frontend/tests/spatial_fields.test.cjs`：14/14 通过；`git diff --check` 覆盖四个前端改动文件及本交接文档，通过。GPT 复核了四文件实际 diff，未发现实质性功能意见；格式意见已在同一 Gemini 会话修正并复验。
- **边界：**测试以与后端接口一致的 busy/failed JSON 构造响应；本轮没有在浏览器中人工制造真实共享锁争用。成功分析 UI 路径由上文实际 Buffer/Slope 检查另行覆盖，不等于该失败并发路径已真实 UI 复验。Gemini Antigravity 未显示上下文用量计。

### 前端项目恢复的迟到 GeoSource 认证回调（Gemini + GPT）

- **复现：**组合运行真实 `frontend/js/project.js` 与 `frontend/js/geosource.js`，先恢复含受保护 XYZ 在线图层的工程 A，等待 GeoSource 凭据弹窗；随后切换到空工程 B，再提交 A 的密钥。修复前，测试观察到旧服务层被加入 B 的地图和图层注册表。相关测试先在修复前失败，确认了跨工程污染。
- **影响：**旧工程的凭据输入可能在新工程加载后继续注册旧在线图层；其后保存新工程时可能把旧工程来源的服务图层一起持久化。
- **修复：**`frontend/js/project.js` 在恢复 WMS/XYZ 服务时传入基于 `_loadGeneration` 和当前项目 ID 的可选谓词；`frontend/js/geosource.js` 在立即连接及迟到的凭据回调处检查该谓词，不再连接过期恢复。`loadSavedServiceLayer(layer)` 原有单参数调用仍兼容。新增集成回归 `frontend/tests/project_load_race.test.cjs` 和 GeoSource 单元回归 `frontend/tests/geosource_layer_capacity.test.cjs`。GPT 审查实际 diff 后要求移除重复谓词入口；Gemini 在同一会话修订，最终只保留第二参数谓词。
- **验证：**GPT 独立运行 `node --test --test-reporter=spec frontend/tests/project_load_race.test.cjs frontend/tests/geosource_layer_capacity.test.cjs frontend/tests/project_save_sync.test.cjs frontend/tests/project_delete_save_race.test.cjs frontend/tests/project_delete_all_partial.test.cjs`：64/64 通过，退出码 0。`git diff --check -- frontend/js/project.js frontend/js/geosource.js frontend/tests/project_load_race.test.cjs frontend/tests/geosource_layer_capacity.test.cjs` 通过。Gemini 同一会话也完成了修复前失败、修复后通过的回归及这组相关测试。
- **限制：**这是本地 VM 集成测试中对真实前端模块和凭据回调的受控验证；未使用真实在线服务、真实凭据或 Electron 界面。项目 UI 全流程的已有验证边界见上文。
- **Antigravity 上下文用量：**未显示。

### AI 聊天完成后图层恢复期间的请求替换竞态（Gemini + GPT）

- **复现与影响：**第一条聊天流已返回 `done` 和针对缺失图层的 `layer_ops`，随后前端暂停在 `/api/layers` 的异步恢复请求；此时启动第二条请求。修复前受控 VM 集成回归观察到旧请求在恢复响应返回后仍把图层注册进 GIS 状态并可能应用旧操作、触发工程自动保存。另测第二条请求先完整结束、旧恢复请求随后返回，避免只覆盖新请求仍处于运行中的情形。
- **修复：**`frontend/js/chat.js` 为缺失图层恢复请求传递当前 AbortSignal，并在 `fetch`/JSON 恢复边界检查 `_sendGeneration`，旧请求失效后停止所有后续 GIS/UI/保存副作用。请求被新请求取代时使用独立的 `request-replaced` abort reason，确保即使新请求已完成，旧任务仍标记为“被替换”，不误报成用户主动取消。新增/扩展 `frontend/tests/chat_send_lifecycle.test.cjs` 覆盖替换时迟到响应、替换请求保持运行、替换请求先完成三种状态，并检查旧图层/设色/额外自动保存均不发生。
- **审查与验证：**修复前集成回归失败并观察到旧图层被加入；Gemini 与 GPT 后续运行 focused chat 生命周期测试均为 49/49 通过。GPT 独立命令：`node --test --test-reporter=spec frontend/tests/chat_send_lifecycle.test.cjs`，49/49 通过，退出码 0。Gemini 清理 EOF 空行后运行 `git diff --check -- frontend/js/chat.js frontend/tests/chat_send_lifecycle.test.cjs`，退出码 0；GPT 清理前检查发现该空行并已由 Gemini 在同一会话修正。
- **限制：**该验证是本地模拟 SSE、请求竞争与 `/api/layers` 延迟的前端 VM 回归；未调用真实模型、真实分析服务或 Electron。后端取消端点的 HTTP 200 表示取消信号已发送，不等于耗时工具已物理终止或回滚；已开始运行的同步工具会继续到函数返回。共享 GIS 状态锁由延迟释放租约持有，工程切换在锁释放前会被拒绝；这只能避免并发切换，不保证工具副作用回滚。后端边界审计记录于下节。
- **Antigravity 上下文用量：**未显示。

### 后端取消与运行中工具边界（Gemini + GPT）

- **代码路径审查：**Gemini 检查 `backend/services/ai_service.py`、`backend/services/graph.py`、`backend/main.py` 和 `backend/tests/test_ai_cancellation.py`，并只读追踪 `tools.py`、`project_service.py` 与 `frontend/js/chat.js` 的锁/响应契约。`POST /api/cancel` 写入请求取消标记后返回 HTTP 200；LangGraph 的同步工具线程不能被 Python 强制终止。`_DeferredLockLease` 将会话锁和共享 GIS 状态锁延迟到后台 worker 结束后释放，工程激活在共享锁不可用时返回冲突；取消流以 cancelled 结束，非流式路径返回 `execution_status=cancelled`，两条路径都不提交助手回复历史。
- **工具副作用边界：**取消守卫阻止取消后的新工具启动；它不会中断或回滚已开始的同步工具。`backend/services/tools.py::_recorded` 只在调用实际工具前检查取消。GPT 在仓库外隔离进程运行受控复现：工具开始后发出取消，再释放工具继续注册一个合成图层；工具仍返回完成，`_registered_layers` 和 `_pending_layers` 当时均含该图层。执行下一请求的 `reset_state()` 后，待推队列被清空，但注册表中的该图层仍存在。复现脚本和命令见下项。此脚本只验证包装器/图层状态，不模拟真实分析算法、磁盘产物、完整 HTTP/SSE 或 task manager 写入。
- **锁和状态残留复核（Gemini + GPT）：**取消事件可先返回；`_DeferredLockLease` 保持会话锁和共享 GIS 锁直到后台 worker 结束，因此期间新请求会收到 busy，不会并发进入 `reset_state()`。后台工具结束后下一次请求会清空 `_pending_layers`，所以“取消后待推图层必然泄漏并在下一轮渲染”的推测已被否定。`_registered_layers` 不由 `reset_state()` 清除；`_recorded` 会在真实工具调用完成后写工具历史，并对登记的 GIS 操作记录结果。因此已取消的请求仍可能留下后端注册图层、成功任务上下文或工具创建的文件；真实生产数据的这一完整时序未做端到端实测。
- **状态呈现边界：**`POST /api/cancel` 表示已提交取消请求；界面随后标为“用户已取消当前任务”，不说明已启动的工具仍可能完成，也不等于回滚。已运行工具期间 UI 与后端状态可能暂时分离；后端 busy 提示会阻止并发的新分析。
- **GPT 受控复现：**脚本 `E:\_codex-qa\gis-worktable-cancel-inflight-audit\repro_mid_tool_cancel.py`，命令 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\my_repo\Gis-WorkTable\.venv\Scripts\python.exe' 'E:\_codex-qa\gis-worktable-cancel-inflight-audit\repro_mid_tool_cancel.py'`。结果：工具完成后 `registered=true,pending=true`；下一次 `reset_state()` 后 `registered=true,pending=false`。这是组件级受控演示，不是产品 UI/E2E 测试。
- **审查结论与改动：**未发现此取消契约之外、可由本次授权文件修复的确定缺陷；Gemini 未修改代码。GPT 复核后要求 Gemini 修正“待推图层泄漏到下一轮渲染”的风险表述；Gemini 同会话确认该推测不成立，改为注册表/任务上下文可能留下的前后台状态差异。没有擅自改动现有用户脏文件 `backend/services/tools.py`、`backend/services/workflow.py` 或 `backend/services/sql_engine.py`。
- **验证：**Gemini 在同一 Antigravity 会话运行 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\my_repo\Gis-WorkTable\.venv\Scripts\python.exe' -m pytest backend/tests/test_ai_cancellation.py -v`，20/20 通过。GPT 独立复跑 ` $env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\my_repo\Gis-WorkTable\.venv\Scripts\python.exe' -m pytest backend/tests/test_ai_cancellation.py -q`，20/20 通过（2.38s，退出码 0）。指定后端文件工作区状态干净。 GPT 另定向复跑 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\my_repo\Gis-WorkTable\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_ai_cancellation.py::test_cancelled_agent_worker_does_not_start_a_late_tool backend/tests/test_ai_cancellation.py::test_cancelled_stream_worker_does_not_start_a_late_tool -p no:cacheprovider --tb=short`，2/2 通过（5.22s）；该用例验证的是取消后不启动迟到工具，并不覆盖已开始工具的中途取消副作用。Gemini 本轮独立复跑同两项 2/2、整组 20/20 通过，并运行 `node --test frontend/tests/chat_send_lifecycle.test.cjs`：49/49 通过（216ms）。
- **Antigravity 上下文用量：**未显示。

### 结果产物登记与跨运行隔离（Gemini + GPT）

- **代码审查：**`backend/services/result_guard.py` 在传入 `run_id` 时仅查询该 run 的登记表；缺失/空文件、未登记声称、路径不匹配和无有效 GeoJSON 的待返回图层会被标记。主 Agent 两条结束路径都把当前 `task_id`、`run_id` 和开始时间传给 guard。审查未复现跨 task/run 误认问题，生产代码没有修改。
- **回归补充：**原有测试覆盖了其他 task 的同名产物隔离和单个 run 的登记成功，但没有直接固定跨 run 场景。Gemini 在 `backend/tests/test_result_guard_v2.py` 新增 `test_other_run_artifact_not_confused`：仅 Run A 登记一个非空文件后，Run B 声称同路径，预期 `ok=False`、`registered=False`、`exists=True`、状态 `UNREGISTERED`。GPT 复核实际 diff，并要求修正一次新增的 EOF 空行；Gemini 在同一会话修订，最终 `git diff --check` 通过。
- **验证：**Gemini 和 GPT 均使用 `D:\python\python.exe` 从仓库根运行 `D:\python\python.exe -m pytest backend/tests/test_result_guard.py backend/tests/test_result_guard_v2.py`，最终分别 36/36 通过（Gemini 1.13s；GPT 独立复验 0.95s）。当时首次尝试使用项目 `.venv` 因缺少 `keyring` 失败；依赖已在后续环境修复中补齐，并另行以 `.venv` 复跑这两组测试 36/36 通过，详见下文。
- **边界：**这验证的是登记身份、路径、文件存在/非空和部分图层结构检查；不证明任意输出文件的内容语义正确，也不替代具体分析算法及真实数据验证。干净机器安装与发布打包仍待验收。
- **Antigravity 上下文用量：**未显示。

### 无效自交几何修复面积损失（Gemini + GPT）

- **复现：**用自交 bowtie Polygon `[(0,0),(2,2),(2,0),(0,2),(0,0)]` 对比修复方法：当前 `buffer(0)` 只保留一个叶片，面积为 1；Shapely `make_valid` 得到包含两个 Polygon 的 MultiPolygon，面积为 2。项目声明 Shapely `>=2.0.0`，因此修复 API 已在支持范围内。
- **修复：**`backend/services/spatial_robust.py` 先调用 `shapely.make_valid`，验证其结果非空且有效；不可用或失败时才回退到原 `buffer(0)`。有效的 GeometryCollection 作为完整几何保留，不静默丢弃低维分量。仅修改这一实现文件及 `backend/tests/test_spatial_robust.py`。
- **回归与审查：**测试现在检查 bowtie 两叶总面积为 2，并用带悬挂线的无效面检查修复后 Polygon 与 LineString 分量都还在。GPT 复核实际 diff 后要求补足 GeometryCollection 分量断言；Gemini 在同一会话修订。Gemini 与 GPT 最终均运行 `D:\python\python.exe -m pytest backend/tests/test_spatial_robust.py -q`，12/12 通过；GPT 用时 3.19s。`git diff --check -- backend/services/spatial_robust.py backend/tests/test_spatial_robust.py` 通过。
- **边界：**定向测试含合成几何和空间工具受控调用；未用真实生产数据复验修复后属性/拓扑。三个 GeoPandas `keep_geom_type=True` 警告来自 overlay 对不同维度接触结果的原生过滤，测试通过。多图层 CRS 处理由工具调用路径负责；本轮只读检查 `_layer_to_gdf` 将 GeoJSON 输入按 EPSG:4326 构造，未覆盖外部调用方直接用不同 CRS 调用 helper 的场景。`tools.py` 当前有用户修改，本轮未编辑。
- **Antigravity 上下文用量：**未显示。

### 运行记录与产物台账生命周期审计（Gemini + GPT）

- **范围与结论：**只读审计干净的 `backend/services/storage_service.py`、`backend/tests/test_storage_service.py`。检查 Run ID 复用清空旧产物并重置状态、产物覆盖登记、完成状态更新、缺失/空文件降级、路径规范化和 SQLite 事务/异常路径；未复现实质性缺陷，无代码改动。
- **验证：**测试使用 `tmp_path` 下独立 SQLite 数据库。Gemini 与 GPT 分别运行 `D:\python\python.exe -m pytest -q backend/tests/test_storage_service.py -p no:cacheprovider --tb=short` / `D:\python\python.exe -m pytest backend/tests/test_storage_service.py -q`，均 5/5 通过（Gemini 0.24s；GPT 0.25s）。目标源码和测试保持干净。
- **限制：**这是本地 SQLite 临时库的服务级审计；未制造真实磁盘写满、进程崩溃或多进程同时写入故障。
- **Antigravity 上下文用量：**未显示。

### 图层检查器显示无效几何数量（Gemini + GPT）

- **复现与影响：**`backend/services/layer_service.py` 已计算并返回 `invalid_geom_count`，`frontend/js/layers.js` 也把该值读入 `invalidCount`，但此前未将它加入检查器 HTML。用户只能看到空几何数量，无法从图层检查器判断服务器检测到的无效几何数量。
- **修复：**在图层数据体检中新增“无效几何数量”行；正数使用警示色，0 正常显示，字段缺失或为 null 时显示“未检测”。仅修改 `frontend/js/layers.js` 和 `frontend/tests/vector_inspector_units.test.cjs`，未改已有脏文件 `backend/services/layer_service.py`。
- **回归与审查：**VM harness 的远端检查响应支持可控无效几何数；新增断言覆盖正数警示、0 值和缺失字段回退。GPT 审核了实际 diff 并独立运行 `node --test --test-reporter=spec frontend/tests/vector_inspector_units.test.cjs`，19/19 通过；`git diff --check -- frontend/js/layers.js frontend/tests/vector_inspector_units.test.cjs` 通过。
- **真实浏览器验证：**首次检查时没有打开的 WorkTable 页面；随后在隔离临时工程存储和临时数据库下启动本地后端 `127.0.0.1:8765`，通过 CUA 浏览器上传合成 bowtie `invalid-bowtie.geojson`。工程只含该 1 个 Polygon；检查器实际显示 `空几何数量 0`、`无效几何数量 1` 且为警示色。测试服务在验证后停止；未使用或改动用户工程/数据库。
- **边界：**该真实浏览器结果只覆盖一个合成无效 Polygon 和本地后端，没有验证生产矢量、多图层并发或 Electron。VM 测试与浏览器观察分开记录；其他 UI 视觉和环境限制见阶段验证表。
- **Antigravity 上下文用量：**未显示。

### 项目 `.venv` 声明依赖与定向测试

- **发现与修复：**`.venv` 缺少 `backend/requirements.txt` 已声明的 `keyring>=25.0.0`，且环境自身没有 pip。最初代理不可用且本地 wheel 缓存无包；通过全局 Python pip 将官方 `keyring 25.7.0` 及其依赖安装到项目 `.venv`，未改 `requirements.txt` 或其他项目依赖声明。
- **环境检查：**`D:\python\python.exe -m pip --python E:\my_repo\Gis-WorkTable\.venv\Scripts\python.exe check` 返回 `No broken requirements found.`；用 `.venv` 的 `packaging.Requirement` 逐项检查 `backend/requirements.txt` 的直接依赖，结果 `All direct requirements satisfied`。
- **定向复验：**`.venv\Scripts\python.exe -m pytest backend/tests/test_ai_cancellation.py -q -p no:cacheprovider --tb=short`：20/20 通过（2.90s）；`.venv\Scripts\python.exe -m pytest backend/tests/test_result_guard.py backend/tests/test_result_guard_v2.py -q -p no:cacheprovider --tb=short`：36/36 通过（1.12s）。
- **边界：**这证明当前 `.venv` 满足声明依赖且这些定向测试通过，不等于在干净机器上完成全量安装/打包验收，也未运行全量后台测试套件。

### GIS task 操作记录持久化失败恢复（GPT + Gemini）

- **复现与影响：**在隔离临时目录创建 task 后，将 `_save_task_to_disk` 替换为抛出 `OSError`。旧实现先原地修改缓存中的 `gis_context`，再写盘；写盘失败后内存仍保留未持久化的 `last_successful_operation` 和输出图层。上游工具会记录并吞掉该记录异常，后续上下文因此可能把未保存操作当成成功状态。
- **修复：**仅修改 `backend/services/task_manager.py` 与 `backend/tests/test_task_manager.py`。先构造候选 task 并写盘，成功后才更新缓存；写盘失败仍向调用方抛出异常，但内存和磁盘快照都保留上一次成功状态。未编辑现有脏改动中的 `tools.py`、`workflow.py`、`sql_engine.py`。
- **回归与审查：**`D:\python\python.exe -m pytest -q backend/tests/test_task_manager.py -p no:cacheprovider --tb=short`：GPT 首次运行 13/13 通过；Gemini 在同一 Antigravity 会话独立复跑 13/13 通过。`git diff --check` 通过。GPT 检查实际 diff；Gemini 回审无实质问题，并确认本次审查未再遇到 EOF。
- **限制：**这是 task manager 本地文件写入失败的受控故障注入；没有制造真实磁盘满、进程崩溃或端到端工具调用故障。该修复不代表其余工作流恢复路径已全部审计。

### 启动与运行时恢复只读复审（Gemini + GPT）

- **范围与结论：**Gemini 只读检查 `backend/launcher.py`、对应启动器/运行时测试，以及直接使用的 `scripts/check_runtime.py`、`scripts/bootstrap_windows.ps1`、`start.bat` 和 `desktop/main.js`；未发现当前切片内可复现的高影响启动或恢复缺陷，也未改动代码。
- **Gemini 验证：**运行 `.venv\Scripts\pytest.exe backend/tests/test_launcher.py backend/tests/test_bootstrap_runtime.py -q --tb=short`，45/45 通过（0.29s）；运行时检查在项目 `.venv` 报 `Runtime dependencies are ready.`。全局 Python 的 uvicorn 0.51.0 不满足仓库声明的 `==0.31.1`，检查器按预期以退出码 1 拒绝该环境。
- **GPT 独立复验：**`$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & '.venv\Scripts\python.exe' -m pytest -q backend/tests/test_launcher.py backend/tests/test_bootstrap_runtime.py -p no:cacheprovider --tb=short`：45/45 通过（0.23s）。直接从项目 `.venv` 检查版本得到 uvicorn 0.31.1，满足 `backend/requirements.txt` 的精确约束。
- **边界：**自动化与依赖自检通过不代表完整 Electron 窗口或无 Python 的干净机器冷启动已验收；这两项仍待真实环境验证。Antigravity 未显示上下文用量仪表。

### 上传响应丢失恢复与幂等契约只读复审（Gemini + GPT）

- **范围与结论：**只读复审 `backend/main.py` 上传处理/状态缓存/取消回滚、`backend/tests/test_upload_handoff.py`、`frontend/js/api.js`、`frontend/js/upload.js` 及相关前端用例；Gemini 在六类请求 ID 重放、并发重复、取消竞态、状态暴露、回执淘汰/过期、服务重启后的恢复行为中未发现新的高影响缺陷，未改代码。
- **契约证据：**服务端成功回执当前仅保留在进程内存 15 分钟、最多 64 项；同 ID 命中回执时复用原结果，活动中的重复请求返回 409。前端恢复得到 `unknown` 时不会自动重传，而是提示用户先检查图层，再自行重新选择文件，避免服务重启或回执淘汰后因静默重传而重复导入。
- **Gemini 验证：**上传后端握手/幂等测试 42/42；API 超时测试 4/4；前端预览/恢复测试 26/26。Antigravity 未显示上下文用量。
- **GPT 独立复验：**`.venv\Scripts\python.exe -m pytest -q backend/tests/test_upload_handoff.py -p no:cacheprovider --tb=short`：42/42 通过（6.96s，4 条 Rasterio `PendingDeprecationWarning`）；`node --test --test-reporter=spec frontend/tests/upload_preview.test.cjs`：26/26；`node --test --test-reporter=spec frontend/tests/api_upload_timeout.test.cjs`：4/4；定向 `git diff --check` 通过。
- **界面边界：**本轮没有可用的 WorkTable 浏览器页或正在运行的本地服务，因此没有声称本轮完成新的浏览器上传验证；既有文件选择与响应丢失浏览器证据仍见早前模块扫描记录。多进程部署和回执跨重启持久化不在当前实现保证范围内。

### 隔离干净 Python 环境安装与关键回归

- **环境：**在 E 盘仓库外新建 `E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv`，基于 `D:\python\python.exe`（Python 3.13.0），将 uv 缓存也定向到该临时目录；从 `backend/requirements.txt` 解析并安装 137 个包。未改仓库依赖文件或现有 `.venv`。
- **安装与就绪：**`uv venv --python D:\python\python.exe E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv`；`uv pip install --python E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe -r backend/requirements.txt`：成功安装 137 包。`E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe scripts/check_runtime.py` 输出 `Runtime dependencies are ready.`；`uv pip check --python E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe` 检查 137 包并报告全部兼容。
- **定向验证：**均在 PowerShell 中设置 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'`，并用临时环境解释器执行：
  - `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_launcher.py backend/tests/test_bootstrap_runtime.py -p no:cacheprovider --tb=short`：45/45。
  - `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_layer_service.py backend/tests/test_spatial_robust.py backend/tests/test_upload_handoff.py backend/tests/test_project_service_import.py backend/tests/test_project_raster_persistence.py -p no:cacheprovider --tb=short`：118/118。
  - `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_ai_cancellation.py backend/tests/test_result_guard.py backend/tests/test_result_guard_v2.py backend/tests/test_task_manager.py -p no:cacheprovider --tb=short`：69/69。
  - `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_sql_engine.py backend/tests/test_spatial_tools.py backend/tests/test_datav_service.py backend/tests/test_workflow.py -p no:cacheprovider --tb=short`：339/339。
  - `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_materialize_workflow.py backend/tests/test_stream_step_events.py -p no:cacheprovider --tb=short`：29/29。
  合计 600/600，通过；118 项批次有 19 条警告；339 项空间工具批次有 1,693 条警告，主要包括 `backend/services/tools.py` 的 Rasterio/GDAL Affine `*` 运算弃用、Pandas `rename(inplace=...)` 警告，以及测试用例中的 Shapely/日期解析警告。没有运行完整后端套件。
- **边界：**证明当前 `backend/requirements.txt` 可在干净 Python 3.13 venv 安装，并覆盖上述关键后端回归；不证明前端依赖干净安装、Electron 构建/窗口、无 Python 机器冷启动或远程服务可用。警告涉及的 `tools.py` 是现存用户脏文件，本轮只记录未改。临时 venv 与缓存保留在 E 盘 QA 目录，不在项目仓库内。

### 干净依赖环境真实进程启动与浏览器联通

- **隔离配置：**使用上述临时 Python 3.13 解释器、独立端口 `18765`，并设置 `GIS_WORKSPACE_DB_PATH=E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\runtime.sqlite3`。真实进程启动时项目最近工程列表仍由现有只读缓存索引提供；本轮没有打开工程、上传数据、保存项目或调用 AI。
- **生命周期命令与结果：**
  - `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; $env:GIS_PORT='18765'; $env:GIS_WORKSPACE_DB_PATH='E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\runtime.sqlite3'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m backend.launcher start --port 18765`：启动成功。
  - `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; $env:GIS_PORT='18765'; $env:GIS_WORKSPACE_DB_PATH='E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\runtime.sqlite3'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m backend.launcher check --port 18765`：退出码 0。
  - `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; $env:GIS_PORT='18765'; $env:GIS_WORKSPACE_DB_PATH='E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\runtime.sqlite3'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m backend.launcher stop`：报告停止 PID 25040，退出码 0；随后检查 `127.0.0.1:18765` 监听数为 0。
- **真实浏览器观察：**CUA 在 `http://127.0.0.1:18765/` 载入标题 `GIS AI WorkTable`；首页、工作区面板、地图控件和最近工程列表均显示。只检查 UI，没有打开列表项目或执行会写入数据的操作。服务已停止。
- **边界：**这是隔离 Python 环境下的真实本地后端进程与浏览器主页联通验证，不是 Electron 窗口/桌面打包测试；未验证浏览器地图瓦片、真实在线模型、外部 GIS 服务或无 Python 新机器冷启动。

### 隔离 Electron 桌面流程：样例加载与工程保存

- **环境与隔离：**在仓库外的 `E:\_codex-qa\gis-worktable-desktop-smoke-18cbdc4049454989849e5c00f4513ec1` 运行当前源码副本；Electron 31.7.7、单独端口 `18766`、临时 `--user-data-dir`、临时 Python 3.13 venv。通过 hosts resolver 规则与本地代理拒绝外部网络；`APPDATA`、`LOCALAPPDATA`、临时目录、后端缓存和工程数据均指向隔离目录。已有用户 Electron profile 未用于此流程。
- **真实界面结果：**Electron 窗口加载本地 WorkTable；首页点击“多边形地块 / 加载样例”后界面显示加载成功。随后点击“保存工程 / 保存到工作台”，对话框关闭；`GET http://127.0.0.1:18766/api/projects` 返回工程 `3b7fa73a`，`layerCount: 1`。对应后端日志显示 `/samples/demo-polygons.json` 与 `/api/layer/register` 均 200。
- **失败原因澄清：**此前一次隔离尝试显式设置 `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`，保存按预期以 400 拒绝，错误为“没有可用的系统安全密钥库”；这证明 fail-closed 行为，不能作为产品保存缺陷。随后只在仓库外临时副本把测试密钥服务名改为唯一命名空间，使用 Windows 默认安全密钥库进行真实 UI 保存；没有读取现有产品密钥。独立后端调用也在该独立命名空间成功。
- **附带限制：**启动时 `/api/geosource/stats` 因隔离副本未包含 `data/gis_services.db` 返回 500；该数据库依赖功能未在此临时副本验证，不据此判断为产品缺陷。真实远程服务、在线模型、外部数据源仍未测试。
- **清理与改动范围：**结束隔离 Electron 进程后确认端口 `18766` 无监听；确认并删除仅为本轮测试生成的唯一 Windows 凭据项。没有修改仓库源码或现存用户脏文件；仅更新本交接文档。浏览器/Electron 窗口已实际操作验证，但不是发布构建包验收。
- **复核状态：**Gemini 先前按只读任务检查了保存流程；GPT 补做上述带隔离密钥库的端到端复验，并已请求 Gemini 基于新证据收口此前 400 判断。Gemini 最终只读回审确认该 400 来自测试环境故意禁用 keyring 的安全拒绝，未发现保存流程产品缺陷；它报告 `project.json`、压缩 GeoJSON blob 与 `GISWENC1` 加密索引已落盘。GPT 已独立确认 UI 保存后 `/api/projects` 返回 1 条记录及 1 图层，并检查交接中记录的隔离目录文件存在；Gemini 另跑的 `vector_inspector_units.test.cjs` 为 19/19，但该测试与工程保存无直接关系，不计作保存回归测试。Gemini 未编辑仓库文件，上下文仪表未显示。

### 工程保存、恢复与删除回归复验（GPT）

- **范围：**当前工作树中的前端工程保存队列/加载竞态/单项与批量删除，以及后端矢量/栅格资产持久化、导入和恢复。
- **前端命令：**`node --test --test-reporter=dot frontend/tests/project_save_sync.test.cjs frontend/tests/project_load_race.test.cjs frontend/tests/project_delete_save_race.test.cjs frontend/tests/project_delete_all_partial.test.cjs`。退出码 0；点式报告共 43 项通过，无失败。
- **后端命令：**`$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_project_raster_persistence.py backend/tests/test_project_service_import.py -p no:cacheprovider --tb=short`。`52 passed, 12 warnings in 13.11s`；警告均为现存 Rasterio/GDAL `Affine *` 矩阵运算弃用提示，出现在 `backend/services/tools.py` 和 `backend/main.py`，未在本轮修改。
- **工程打开竞态命令：**`$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_project_open_race.py -p no:cacheprovider --tb=short`：7/7 通过（3.52s）。
- **GPT 复核：**实际 diff 中 `project_service.py` 的导入校验新增 20 位内容寻址栅格哈希核验，并在 `load_project` 中重写 `asset` 与 `source_asset` URL；`project.js` 给受保护在线图层的延迟凭据回调增加项目代际判断。GPT 追踪 `geosource.js` 后确认当前 `loadSavedServiceLayer` 在凭据回调恢复时检查代际，WMS/XYZ 图层注册在该回调内同步发生；现有 `project_load_race.test.cjs` 对切换后迟到凭据进行了回归覆盖。未在此发现新的可复现缺陷。
- **边界：**自动化覆盖和下述隔离 Electron 的真实保存、重启、重开共同支持当前范围；本轮没有在界面上执行项目删除，没有用真实认证在线地图服务，也没有代表性真实用户栅格数据重跑。
- **重启重开补测（通过）：**首次启动尝试中 Electron 主进程写入测试启动器已关闭的 stdout pipe，触发 `EPIPE`，渲染窗口未进入可操作页面；这是 harness 输出管道配置问题，不是产品缺陷。调整为 Node detached launcher 并保留 stdout/stderr 文件句柄后，在隔离副本 `E:\_codex-qa\gis-worktable-release-roundtrip-20261105-1126` 用端口 `18768` 重新验证。命令为 `& '<clean-venv>\Scripts\python.exe' '<isolated-copy>\scripts\check_runtime.py'`（输出 `Runtime dependencies are ready.`），再由 `node '<isolated-copy>\runtime\launch-electron.js'` 启动 Electron 31.7.7。设置独立 `GISWTB_PROFILE=codex-release-roundtrip-20261105-1126`、独立 workspace DB、用户目录和缓存。UI 加载内置“多边形地块”样例，保存为 `Codex Release Restart Check 2026-11-05`；本地 `/api/projects` 返回工程 `0cd2ebe2`、`layerCount: 1`。正常关闭并重启同一应用后，首页最近工程列出该项目；打开后 toast 显示工程恢复，图层面板显示 `样例_多边形地块`、`Polygon`、`3 个要素`。后端恢复请求及图层重新登记均为 HTTP 200。再次正常关闭后，确认无隔离 Electron 进程且 `18768` 无监听；仅此轮创建的唯一 Windows 测试 key 已移除。修正后的日志未出现 `EPIPE`，仅有 Electron 开发模式 CSP 提示。
- **边界与未覆盖：**这是隔离开发源码副本上的真实 Electron UI 流程，不是 Windows 打包安装版本；没有验证 UI 删除、外部生产数据、真实在线 GIS 服务或干净机器首次安装。UI/API 的工程名及图层恢复是主要成功证据；加密的 `project.json` 无法直接当作普通 JSON 读取，不作为失败证据。隔离副本中 `local_encryption.py` 使用了唯一服务标签以避免复用用户密钥；测试结束后唯一测试 key 已清理。仓库源码及用户脏改动未改动。
- **Gemini 独立复核：**已分派同一 Antigravity 会话做当前跨层只读审查；最终交接待回传。Gemini 已返回只读复核，确认无其他可复现生命周期缺陷；但本节随后发现容量淘汰风险并已请 Gemini 再评估。

### 空间分析 CRS / 单位定向复核（GPT + Gemini，只读）

- **代码复核范围：**`backend/services/tools.py::measure_area` 的局部 UTM 与大范围 WGS-84 椭球面积分支；`spatial_buffer` 与多环缓冲的距离单位、UTM 范围拒绝和结果命名；对应边界和单位回归。只读工作区脏文件，没有编辑。
- **面积命令：**`$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_coverage_gap.py::TestMeasureArea -p no:cacheprovider --tb=short`：2/2 通过；其中大范围面与独立 `pyproj.Geod` 椭球面积期望值比对，误差容限 0.01 km²。
- **缓冲命令：**`$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_spatial_tools.py -k buffer -p no:cacheprovider --tb=short`：50/50 通过，221 项非 buffer 用例未运行。覆盖单位/数值校验、UTM 可用范围、输出重名保留和多环缓冲边界。
- **GPT 复核结论与限制：**所读分支按 WGS-84 注册坐标解释，跨 UTM 带/大范围使用椭球面积；局部缓冲超出 UTM 使用范围时明确拒绝，避免静默将度数当米。该结论限于所审函数及当前用例，不代表所有空间分析单位正确。GPT 未发现新可复现错误；跨日期变更线、多远隔区域混合图层及极区边界仍未由本次复验覆盖。
- **Gemini 只读复核：**检查 `backend/services/tools.py` 的距离/面积、缓冲、多环缓冲、质心、叠置、近邻、简化、聚类、Voronoi、插值、KDE 与几何字段等路径，以及 `backend/services/spatial_robust.py`；确认仓库没有改动或新增文件。报告在本轮审查范围内未列出可复现缺陷。它提出 `spatial_simplify` 可增加米制模式作为后续独立改进建议；这属于建议，未作为已证实缺陷或本轮修复。
- **Gemini 实际验证：**`D:\python\python.exe -m pytest -q backend/tests/test_spatial_robust.py -p no:cacheprovider --tb=short`：12 passed、3 条测试触发的类型过滤警告（3.46s）；`D:\python\python.exe -m pytest -q backend/tests/test_spatial_tools.py -k "TestSpatialBuffer or TestSpatialIntersect or TestSpatialCentroid or TestSpatialUnion or TestSpatialDifference or TestSpatialClip" -p no:cacheprovider --tb=short`：31 passed、240 deselected（2.51s）。GPT 独立运行结果见上两项及本节前述面积/缓冲测试。
- **Gemini 未覆盖项：**其余 240 项 `test_spatial_tools.py` 用例未运行；跨 180° 日期变更线真实数据的端到端浏览器渲染未视觉比对。本节所列测试不能代替完整空间分析或真实业务数据验收。Antigravity 上下文用量未显示。

### 工程数量上限的保存/导入差异（已按用户选择修复）

- **初始发现：**`backend/services/project_service.py::save_project` 在新保存使索引超过 `_MAX_PROJECTS`（30）时，按最早 `updatedAt` 删除旧工程及其独占资源，再返回保存成功；满额导入则拒绝并保留现有工程。GPT 和 Gemini 的只读复审都确认了静默数据丢失风险。用户选择“达到上限就拒绝新建并保留现有工程”，据此授权本次最小修改。
- **修复：**`save_project` 在项目锁内识别新建后、分配 ID 和处理图层数据前检查当前索引；满额时抛出与导入一致的容量错误。删除了静默 FIFO 修剪逻辑。达到上限时已有工程更新仍允许；新建（无 ID 或传入不存在 ID）、手动保存和自动保存创建路径都会受到同一规则约束。API 路由将 `ValueError` 返回 HTTP 400。
- **回归：**新增 `test_project_save_respects_project_count_limit_without_evicting_existing_data`：满额时尝试矢量和栅格新建，确认 ID 分配、矢量 blob、栅格存储、工程写入和删除均未调用；现有工程数据快照、blob refcount、目录和列表不变；随后更新现有工程成功。更新 `test_project_index_write_failure_reports_saved_project_and_list_recovers`，令测试容量为 2，保留其“索引写失败后从工程文件恢复列表”的原目的，不再依赖旧工程淘汰。导入满额保留行为继续由既有回归覆盖。
- **验证：**GPT 在干净 Python 3.13 环境执行 `backend/tests/test_layer_group_persistence.py backend/tests/test_project_raster_persistence.py -p no:cacheprovider --tb=short`：128 passed、13 条既有测试情形/弃用警告（17.24s）；此前另外独立执行三个容量/导入/索引恢复定向用例：3 passed。`py_compile` 对 `project_service.py` 与两个测试文件通过；针对这三个文件的 `git diff --check` 通过。Gemini 也分别执行两条容量拒绝/更新测试（2 passed）及相关索引恢复测试（1 passed）。
- **错误提示补齐：**Gemini 随后检查发现 `frontend/js/api.js` 的 `saveProject` 与 `autoSaveProject` 丢弃了 HTTP 错误 JSON 中的 `detail`。Gemini 将两处错误构造改为复用 `projectResponseError`，使现有错误展示流程可以显示后端容量恢复指引；响应无详情或 JSON 解析失败时保留状态码回退。新增 `frontend/tests/api_project_errors.test.cjs` 覆盖手动/自动保存的容量详情、回退和成功响应。GPT 检查实际 diff 后未发现需修订项，并在同一 Antigravity 会话请求最终闭环。
- **前端验证：**GPT 独立运行 `node --test frontend/tests/api_project_errors.test.cjs`：6 passed；`node --test frontend/tests/project_save_sync.test.cjs frontend/tests/project_load_race.test.cjs frontend/tests/project_delete_save_race.test.cjs`：38 passed、0 failed。`node --check` 对实现和新测试均通过，相关 `git diff --check` 通过。Gemini 同会话报告同一组新增测试 6 passed、相关工程回归 38 passed，并报告 Antigravity 上下文用量未显示。
- **未验证：**本轮未通过完整浏览器 UI 再现 30 个实际工程后的手动/自动保存提示；真实工作区的 30 项容量未被填满或修改，均在临时目录和 `_MAX_PROJECTS=1` 下模拟。容量后端行为和前端错误提取分别有回归覆盖，但没有执行真实 HTTP 400 到浏览器 toast 的端到端验证。

### 工程删除 UI 与文件保护复审（Gemini + GPT）

- **范围：**只读检查 `frontend/index.html`、`frontend/js/project.js` 单项/全部删除处理、`backend/main.py` 删除路由、`backend/services/project_service.py` 文件/Blob 清理与 refcount，以及删除/保存竞态和部分失败测试。相关源码和测试含用户已有修改，Gemini、GPT 均未编辑。
- **行为证据：**单项删除由历史列表垃圾桶按钮直接调用 `_deleteProject`，当前没有确认提示；删除当前工程时先使加载代际失效，等待运行任务取消确认，再串行化与保存队列，成功后刷新列表并清理当前工程状态。全部删除会先调用 `confirm()`，等待保存及任务取消；后端逐个删除，保留删除失败工程并重建索引/refcount，前端在部分失败时提示而不谎报全部成功。单项删除遇到工程目录 `rmtree` 失败会保留工程 JSON 和所引用 Blob 并返回 HTTP 500；前端 catch 后显示“删除失败”。现有回归明确断言该安全失败行为。
- **验证：**GPT 命令 `node --test --test-reporter=spec frontend/tests/project_delete_save_race.test.cjs frontend/tests/project_delete_all_partial.test.cjs`：7/7 通过。Gemini 在同一 Antigravity 会话用 `node --test frontend/tests/project_delete_save_race.test.cjs frontend/tests/project_delete_all_partial.test.cjs` 独立运行，7/7 通过（80.8ms）；Git 状态检查确认没有文件变更。
- **确认提示回归基线：**当前工作树再次运行 `node --test frontend/tests/project_delete_save_race.test.cjs`：2 passed；两个用例覆盖保存队列与竞态，但没有断言单项删除的确认/取消路径，故该测试集通过不能证明 UI 有删除确认。
- **后端独立复验：**`$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_project_raster_persistence.py -k delete -p no:cacheprovider --tb=short`：9 passed, 41 deselected（3.70s）；同解释器运行 `backend/tests/test_layer_group_persistence.py -k 'delete_project_removes_project_symlink or delete_all_removes_project_symlink'`：4 passed, 73 deselected（3.02s）。这些用例使用 pytest 临时目录，覆盖目录删除失败后的工程/Blob 保留、批量删除部分失败与重建，以及单项/批量删除项目目录符号链接时不触碰链接目标。
- **审查判断与复核：**单项永久删除缺少二次确认是可信的数据误删风险，且“全部删除”已经有确认机制作同产品内参照；Gemini 同会话复核认定这是高风险用户数据丢失缺陷。现有 `project_delete_save_race.test.cjs` 的单删测试没有注入/断言确认框；`project_delete_all_partial.test.cjs` 只覆盖全部删除确认。最小回归应断言用户取消单项确认时不发送 DELETE、不取消 AI 任务、不改变活动工程状态；确认后保留既有保存队列/竞态行为。此修复触及现存脏 `frontend/js/project.js` 与对应测试，GPT 已向用户申请仅此两处的编辑授权，尚待回复。
- **后端删除失败语义复核：**Gemini 更正了初次建议。工程目录无法 `rmtree` 时服务保留工程文件及引用 Blob，API 返回 500；现有 `test_project_delete_filesystem_failure_preserves_project_blobs` 明确断言此行为，前端 catch 后显示“删除失败”并保留当前 UI 状态。该单项删除语义是原子、fail-closed 行为，不应为结构化 warning 将其改成 200。仅当工程目录已成功删除而未引用 Blob 清理失败时，服务返回成功并附 warning。未发现应改动该后端行为的依据。
- **旧 Electron 测试环境限制：**此前隔离 Electron clone 的测试工程仍加密，但对应测试 key 已清理；该旧 clone 的工程列表 500 不视为产品缺陷，本次没有在其中点击删除。
- **隔离浏览器复现（GPT，2026-11-05）：**从当前工作树复制前端/后端到 `E:\_codex-qa\gis-delete-ui-smoke-20261106-verified`，只在该隔离服务进程内存使用随机 AES key，不访问 Windows 凭据库；建立一条合成工程，并用测试 ASGI 中间件只拦截该 clone 的单项 `DELETE /api/projects/{id}`，记录请求并返回 409，保护测试工程不被删除。真实浏览器打开“文件 → 加载工程 → 打开侧边栏历史”，点击合成工程的“删除”；`getJsDialog()` 返回 null（没有确认对话框），中间件日志记录 `DELETE /api/projects/c01042f5 intercepted; returned 409`，随后 GET `/api/projects` 确认该合成工程仍在列表中。该 UI 复现证实没有 guard 时按钮会直接发起删除请求；实际永久删除已由测试守卫阻止，未删除任何用户工程。
- **Gemini 同会话只读复核：**确认确认逻辑必须先于 `_pendingDeleteProjectIds`、当前任务取消、`_loadGeneration` 递增和保存队列入队。建议回归覆盖：取消确认时不发 DELETE、不取消任务、不改变活动工程/列表；确认后保留原保存队列和竞态保护；API 失败时 DOM/活动工程保留且 pending lock 可再次重试。GPT 复核未发现该建议与现有实现冲突。Gemini 未改动文件。
- **变更边界与待办：**源码及对应测试仍含用户已有改动，GPT/Gemini 均未编辑。已向用户提交最小修复授权请求；建议回归断言取消单项确认时不发 DELETE、不取消 AI 任务、不改变活动工程状态，确认后保留原保存队列/竞态保护。等待用户回复后再编辑 `frontend/js/project.js` 及相应测试。Antigravity 上下文仪表未显示。

### COG 预览 alpha / nodata 与位深修复（Gemini + GPT）

- **缺陷复现：**带 `nodata=99` 的 4 波段 RGBA GeoTIFF 中，像元 RGB=(200,200,200)、原始 alpha=0 时，Rasterio 因 nodata 发出 `NodataShadowWarning`，`dataset_mask()` 返回 alpha=255；旧预览把这个透明像元渲染为不透明。独立 16 位 TIFF 的原始 alpha `[0, 32768, 65535]` 经 Rasterio `dataset_mask()` 为 `[0, 127, 255]`；直接把原值截断到 8 位会错误地产生 `[0,255,255]`。
- **修复：**在干净文件 `backend/services/cloud_native.py` 改为直接读声明的 alpha 波段；对 uint16 用 `//257` 对齐 Rasterio/GDAL 的 8 位 mask 缩放；浮点 alpha 支持 `[0,1]` 和 `[0,255]` 表示。透明度再与每个显示色带的非有限值、nodata 及内部 TIFF mask 合并，掩膜无效像元的 alpha 归零。仅抑制由 nodata/alpha 组合触发的 `NodataShadowWarning`。
- **回归：**干净测试文件 `backend/tests/test_cloud_native.py` 新增两项：`test_read_cog_preview_preserves_alpha_when_nodata_is_declared` 覆盖 uint8 alpha=0、半透明、nodata 和不透明像元；`test_read_cog_preview_preserves_uint16_alpha_and_nodata` 覆盖 16 位 alpha 0/20000/32768/65535 的 `[0,77,127,255]` 输出，以及 nodata 和内部 mask 清零。
- **Gemini 验证：**`python -m pytest -q backend/tests/test_cloud_native.py -k "test_read_cog_preview_preserves"`：3 passed, 65 deselected（1.45s）；`python -m pytest -q backend/tests/test_cloud_native.py -k "not integration and not slow" -p no:cacheprovider --tb=short`：64 passed, 4 deselected（6.97s）；`py_compile` 和 `git diff --check` 均通过。Antigravity 上下文仪表未显示。
- **GPT 独立复核：**检查实际 diff，仅变更上述两个开始时干净的文件，未触及既有脏文件。使用隔离 Python 3.13 venv 和其 Rasterio `proj_data` 运行同一非集成命令：64 passed, 4 deselected，另有 9 条既有 Shapely `ops.transform` 弃用警告（7.84s）；`py_compile` 与 `git diff --check -- backend/services/cloud_native.py backend/tests/test_cloud_native.py` 通过。另以仓库外小型 RGBA TIFF 复现旧 alpha/nodata 结果并检查修复行为。第一次临时复现继承系统 `PROJ_LIB=D:\Postgresql\...`，与 venv 所需 PROJ 数据不兼容；明确使用 venv 自带路径后成功，不属于产品问题。
- **边界：**4 个远程集成测试未运行；未连接真实 COG 服务，也未验收调色板索引栅格转换为 RGB 的显示路径或大型影像性能。未声称云原生栅格模块整体审计完成。

### Shapefile 导出字段完整性与 CRS/PRJ 检查（Gemini + GPT）

- **缺陷证据：**通过实际 `_export_shp_sync` 导出并读取临时 ZIP，发现大于 `2^53-1` 的整数与空值或浮点数混列时会被提升为 `float64` 并静默丢失低位；字符串长度超过 DBF 254 字节时 GDAL 会警告并截断，但旧 API 仍返回成功。嵌套属性经 Python 对象表示写入也不能保证是可解析的 JSON。
- **修复：**`backend/main.py::_export_shp_sync` 现在拒绝会被空值/缺失/浮点混列转换的大整数列，允许全整数列保持精度；将 dict/list 属性序列化为紧凑 JSON；对转换后的字符串按 UTF-8 字节数执行 254 字节限制并给出明确错误；规范化 WGS84/CRS84 等别名并为缺失 CRS 回退 EPSG:4326。
- **回归与 CRS 检查：**`backend/tests/test_delivery_safety.py` 新增混空/混浮点正负大整数、纯整数字段无损回读、ASCII/多字节字符串边界、嵌套 dict/list JSON 与超限拒绝、EPSG:4326/WGS84/CRS84/3857 的 `.prj` 检查。只改动本项开始时干净的 `backend/main.py` 和 `backend/tests/test_delivery_safety.py`；`backend/tests/test_output_file_safety.py` 未改。
- **GPT 独立验证：**在隔离 Python 3.13 venv 中运行 `backend/tests/test_delivery_safety.py backend/tests/test_output_file_safety.py`：19 passed（3.80s）；对三个相关 Python 文件运行 `py_compile`，并对两个改动文件运行 `git diff --check`，均通过。Gemini 同组测试报告 19 passed（4.14s）。
- **限制：**未通过真实浏览器/Electron 导出弹窗或打包应用验证；未覆盖超大图层性能及其他桌面 GIS 对边缘 DBF 编码/数值宽度的兼容性。Shapefile 的 254 字节字段限制是格式边界，超长数据应改用 GeoJSON。Antigravity 未显示数值型上下文用量。

### 上传断连恢复、重试与取消状态审计（Gemini + GPT）

- **检查范围：**上传/状态/取消路由、请求收据与回滚辅助函数、前端超时/状态轮询/取消反馈，以及上传恢复和文件安全定向用例。Gemini 只读审计，没有修改文件。
- **通过项：**正常保留收据时，重复请求由请求缓存重放结果；活动重复请求得到 409；取消中的图层注册使用 token 回滚；失败路径最终清除活动标记。前端限制状态/取消超时和轮询次数；超时恢复不会自动重发。GPT 运行 `backend/tests/test_upload_handoff.py backend/tests/test_upload_safety.py -p no:cacheprovider --tb=short`：72 passed（8.07s）；`node --test frontend/tests/api_upload_timeout.test.cjs frontend/tests/upload_preview.test.cjs`：30 passed。Gemini 运行 `backend/tests/test_upload_vector.py backend/tests/test_upload_raster.py -p no:cacheprovider --tb=short`：12 passed（5.80s）。
- **已复现限制/缺陷：**回执是进程内缓存，最多 64 项且 TTL 为 15 分钟。GPT 在隔离临时目录内用 FastAPI `TestClient` 复现：成功上传后驱逐请求回执，状态为 `unknown`；随后对同一 request_id 调用取消，API 返回 `cancelled`，但已注册图层和源文件仍存在，状态查询也转为 `cancelled`。前端 [upload.js](../../frontend/js/upload.js) 将此响应显示为“导入已取消”，因此边缘情形下会错误确认取消。风险为低概率但可见的状态误报/遗留图层；超过缓存容量或等待超过 TTL 后可能触发。
- **修复：**GPT 在共享的 `backend/main.py` 上传状态/取消分支新增 `cancel_unconfirmed` 有界回执。无活动句柄且无结果回执时，服务端仍保留预取消标记以阻止迟到的同 ID 上传，但返回 `uncertain`；状态查询返回 `unknown`。确认回滚路径仍返回 `cancelled`。前端已有的非 `cancelled` 处理会提示取消未确认并要求检查图层。
- **回归：**`backend/tests/test_upload_handoff.py` 更新“上传路由启动前取消”契约，并新增“成功回执被淘汰后取消不误报、旧图层/源文件仍明确存在、同 ID 重试被阻止”的用例。GPT 独立运行 `backend/tests/test_upload_handoff.py backend/tests/test_upload_safety.py -p no:cacheprovider --tb=short`：73 passed（7.92s）；`node --test frontend/tests/api_upload_timeout.test.cjs frontend/tests/upload_preview.test.cjs`：30 passed；对 `backend/main.py` 与 `backend/tests/test_upload_handoff.py` 执行 `py_compile`，并执行 `git diff --check`，通过（Git 提示该测试文件下次触碰时会转换 LF/CRLF 行尾）。Gemini 对上传交接文件运行 43 passed，并独立运行原两组文件 19 passed；它也运行矢量/栅格上传专项 12 passed。
- **剩余边界：**收据被淘汰后仍无法自动定位并清理旧图层/源文件；现在会诚实报告不确定，用户需检查图层并按需手动清理。这里仍是进程内缓存契约，未覆盖服务重启后的恢复。测试为本地 API/前端自动化，没有真实网络断连、浏览器/Electron 交互或打包版本验证。Antigravity 未显示数值型上下文用量。

### 隔离浏览器 UI：本地 GeoJSON 上传与 Shapefile 下载往返（GPT）

- **隔离环境：**从当前工作树复制 `backend/`、`frontend/`、`desktop/`、`scripts/` 到仓库外 `E:\_codex-qa\gis-worktable-ui-smoke-20261105-0935`；排除 `.env`、缓存与依赖目录，未复制用户工程数据。复制已跟踪的静态 `data/gis_services.db`，使用临时 workspace DB、临时目录和 profile `release-ui-smoke-20261105-0935`，端口 `18772`。后端 `/api/health` 返回 `status=ok`，并确认 workspace 指向隔离副本。
- **真实界面流程：**在 Codex in-app browser 打开隔离 WorkTable；数据面板选择本地合成 `release-smoke.geojson`，预览显示 1 个 Polygon 要素及 `name`/`value` 字段，确认上传后图层面板显示 `release-smoke.geojson`、`面 (Polygon) · 1 个要素`。随后从图层菜单选择 Shapefile 下载。
- **导出实物复核：**浏览器实际下载 ZIP 后复制到隔离输出目录，读取并解压确认恰有 `.cpg/.dbf/.prj/.shp/.shx` 五个同名组件；GeoPandas 回读为 1 个 Polygon，`name=smoke polygon`、`value=7`、CRS `EPSG:4326`。归档保存在 `E:\_codex-qa\gis-worktable-ui-smoke-20261105-0935\outputs\release-smoke.geojson.zip`。从用户 Downloads 移除了本次生成的同名临时副本；验证服务已停止，端口无监听。
- **覆盖边界：**这是当前工作树代码的隔离浏览器 UI 验证，不是已打包 Electron 安装版；使用小型合成数据，不代表大型用户数据性能或远程数据源兼容性。早先隔离 Electron 工程保存、关闭、重启、重开证据见上文。

### COG 调色板索引 TIFF 颜色丢失（已修复并复验）

- **复现：**在仓库外临时目录创建 2×2 单波段 GeoTIFF，`ColorInterp.palette`，索引 `[1,2;3,0]` 分别映射红/绿/蓝/黑，`nodata=0`。Rasterio 确认输入为调色板，但当前 `backend/services/cloud_native.py::_read_cog_impl` 将索引当灰阶拉伸，输出 PNG 为 `mode=RGB`，像元为黑、灰、白、黑；原调色板颜色丢失，nodata 索引为不透明黑色。
- **既有基线：**`$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; $env:PROJ_LIB='E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Lib\site-packages\rasterio\proj_data'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_cloud_native.py -k 'cog_preview or read_cog_preview' -p no:cacheprovider --tb=short`：8 passed、60 deselected。现有 alpha/nodata 用例通过，但没有 palette 用例。
- **实现与审查：**为保留这两个已含既有改动的文件，先在确认与工作树基线一致的仓库外快照 `E:\_codex-qa\gis-worktable-ui-smoke-20261105-0935` 编写并验证最小补丁，再精确整合到当前工作树。补丁在 palette 索引波段上直接查色表 RGB，不做灰阶百分位拉伸；沿用 nodata、内部掩膜和非法索引遮罩生成透明度，并在存在独立 alpha 波段时与调色板 alpha 合成。新增 `test_cog_preview_renders_palette_indices_and_nodata_transparency`，断言红/绿/蓝精确像元值和 nodata alpha=0。Gemini 对隔离快照中的实际差异做只读审查并批准；指出大型调色板和同时带 palette/独立 alpha 的复合影像尚未单独造测。
- **复验：**主工作树执行 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; $env:PROJ_LIB='E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Lib\site-packages\rasterio\proj_data'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_cloud_native.py -k 'cog_preview or read_cog_preview' -p no:cacheprovider --tb=short`：9 passed、60 deselected。随后 `python -m py_compile backend/services/cloud_native.py backend/tests/test_cloud_native.py` 和 `git diff --check -- backend/services/cloud_native.py backend/tests/test_cloud_native.py` 均退出码 0。Gemini 在隔离快照独立复验同一焦点集：9 passed、60 deselected。
- **限制：**测试使用本地 2×2 合成 GeoTIFF；未覆盖超大调色板/数据的内存与性能，也未单独测试 palette 与独立 alpha 波段组合或真实远程 COG 服务。此项不代表完整栅格数据生命周期已经验收。

### Electron 主进程启停与恢复定向复验（GPT + Gemini）

- **GPT 实际检查：**确认当前 `desktop/main.js`、`desktop/tests/main.test.cjs`、`scripts/start-desktop.bat` 和 `scripts/stop.bat` 在本轮开始时无未提交改动；阅读后端进程启动/退出、健康检查身份、超时关闭、单实例 IPC、窗口关闭清理及两个批处理入口。
- **测试复验：**GPT 执行 `node --test desktop/tests/main.test.cjs`：29 passed、0 failed、0 skipped（含当前 Windows 环境下的真实 IPC 单实例与进程树关闭子测，以及批处理启动错误码测试）。Gemini 与 GPT 各自执行 `backend/tests/test_launcher.py`；Gemini 为 38 passed、GPT 使用干净 venv Python 3.13 复验为 38 passed。目标四文件在复验后仍保持 clean，本轮没有源码差异。
- **Gemini 审查结论：**没有在陈旧端口/IPC、健康身份匹配、子进程早退、启动超时清理、窗口关闭和 launcher 退出码路径复现关键缺陷；未改动源码。独立审查中尝试的额外命名管道脚本因命令转义失败，不能算作应用失败证据；实际 Windows named-pipe 子测已由上述 Node 测试通过。
- **打包状态检查：**`desktop/package.json` 目前只有 `start`、`start:dev`、`test` 脚本；`desktop` 下未发现 electron-builder、electron-forge 或 electron-packager 依赖/配置，也未找到打包脚本。因此本轮没有安装包可构建验证，不据此宣称已完成安装/升级验收。
- **覆盖限制：**测试包含 VM 模拟和有限 Windows 本机子测，不是打包安装版的冷启动/升级测试；未实测无 Python 干净机器和 Electron 二进制损坏情形。Antigravity 未显示数值型上下文用量。

### 地图图片与 PDF 导出审查（Gemini + GPT）

- **范围与结论：**Gemini 在同一 Antigravity 会话审查 clean 的 `frontend/js/map.js` 与 `frontend/tests/map_export_composition.test.cjs`，覆盖合成绘制顺序/视口、瓦片 CORS 与 Canvas 序列化错误、下载提示、PDF 打印窗口和图例恢复；未复现正确性缺陷，未改源码或测试。GPT 检查实际工作树差异确认这两个文件未修改。
- **Gemini 验证：**`node --test frontend/tests/map_export_composition.test.cjs`（5/5）及 `node --test frontend/tests/chat_send_lifecycle.test.cjs`（49/49）；另对 CORS `SecurityError`、打印弹窗被拦截及异常视口做独立 VM 注入检查。Gemini 报告 Antigravity 未显示上下文用量。
- **GPT 独立复验：**重新运行 `node --test frontend/tests/map_export_composition.test.cjs`：5 passed、0 failed；`git diff --check -- frontend/js/map.js frontend/tests/map_export_composition.test.cjs` 通过；两文件仍 clean。
- **界面边界：**隔离浏览器载入内置样例后，确认 File → Export 是 GeoJSON 导出入口；地图 PNG/PDF 由 AI 助手命令触发，而隔离 profile 显示尚未配置 AI 模型，因此没有真实点击/下载地图 PNG 或 PDF。该审查不能算作真实界面地图图片/PDF 导出验证。隔离服务已停止，端口 18775 无监听。
- **未覆盖：**物理打印机/各系统 PDF 打印驱动差异、超大要素画布内存压力，以及需要已配置模型的真实 UI 触发流程仍未验证。

### GeoJSON 超大整数注册恢复溢出（Gemini + GPT，已修复）

- **复现与影响：**`restore_registered_integer_properties` 为识别 JavaScript IEEE-754 舍入副本直接转换 `new_value` 和已注册 `old_value` 为 `float`。属性为 `10**400` 或 `-(10**400)` 时 Python 抛 `OverflowError: int too large to convert to float`；`/api/layer/register` 调用此恢复逻辑，而路由仅把 `ValueError` 转成 400，因此该输入可使恢复请求异常失败。GPT 在修改前用小型 Python 调用复现；原有精度测试为 4/4 通过，未覆盖浮点范围溢出。
- **修复：**Gemini 只修改 clean 文件 `backend/services/geojson_precision.py` 与 `backend/tests/test_geojson_precision.py`。新增 `_same_float_value`，当转换溢出时返回“不相等”，使数值编辑保持原样而不崩溃；十进制文本仍精确转回整数，并保留 JS 安全整数边界附近原有浮点舍入恢复。
- **回归：**新增两项测试，覆盖超大正整数的 int/float 编辑、精确文本编辑、负超大整数编辑，以及 `9007199254740992.0` 对已注册 `9007199254740993` 的正常恢复。
- **GPT 复核与复验：**检查实际 diff，确认仅两个授权文件改变且改动与复现范围一致。执行 `E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe -m pytest -q backend/tests/test_geojson_precision.py -p no:cacheprovider --tb=short`：6 passed；同一解释器对两个文件运行 `-m py_compile` 成功；`git diff --check -- backend/services/geojson_precision.py backend/tests/test_geojson_precision.py` 通过。Gemini 独立运行焦点测试也是 6 passed。
- **限制：**测试为本地函数/服务逻辑回归，没有通过真实浏览器或 HTTP 客户端构造带已注册令牌的 10^400 请求；因此没有把这一项描述为端到端 UI/API 验证。Antigravity 未显示数值型上下文用量。

### URL GIS 公网/私网重定向与 DNS 固定审查（Gemini + GPT，只读）

- **范围：**Gemini 复核 clean 的 `backend/services/url_security.py` 与 `backend/tests/test_url_gis.py`，沿 DNS 分类与固定连接地址、代理路由、HTTP 重定向、跨源凭据剥离和请求期限路径检查；没有修改源码或测试。GPT 检查工作树确认这两文件仍 clean。
- **Gemini 结论：**本地 mock 覆盖多 A/AAAA 混合公私网时 fail-closed、IPv4-mapped IPv6 私网地址、公网重绑定、私网源转公网后再反跳内网、跨源敏感查询参数移除、公网明文 HTTP 凭据拦截、HTTP CONNECT 代理目标固定、以及公网 SOCKS 代理不可固定时拒绝。未复现 SSRF、凭据泄露、超时/资源耗尽或假成功缺陷；没有提出代码修改。
- **验证：**Gemini 对 `backend/tests/test_url_gis.py` 运行 62 项：62 passed，1 条 Pandas `inplace` 弃用警告（`url_gis_service.py:941`）。GPT 独立运行 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_url_gis.py -k 'redirect or dns or proxy or credential or timeout or sanitize or public_to_private or private_to_public or mixed' -p no:cacheprovider --tb=short`：27 passed、35 deselected。
- **限制：**验证通过本地 mock/测试服务器，不是对真实公网 GIS/CDN 的联网验收；未验证非标准 SOCKS 实现及实际外部证书链。Antigravity 未显示数值型上下文用量。

### UTM 自动分带回归去除恒真断言（Gemini + GPT）

- **发现：**clean 的 `backend/tests/test_geo_coords.py::test_convert_coordinates_utm_auto` 原来尝试用 `source_crs="utm_auto"` 反查 EPSG:32650，但产品实现要求源 UTM 必须给出明确分带；其断言又以 `or True` 结束，因此无论结果如何都通过。`backend/services/tools.py` 含用户已有改动，仅只读检查，未编辑。
- **修复：**Gemini 只编辑 `backend/tests/test_geo_coords.py`：移除恒真表达式；分别将 112.94°E/28.23°N 自动带号输出与 EPSG:32649、116.4°E/39.9°N 输出与 EPSG:32650 的 pyproj 结果比较，误差容限 0.5 m；保留东坐标相对检查。
- **GPT 验证：**变更前 16/16 通过；改后在干净 Python 3.13 环境运行 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; $py='E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe'; & $py -m pytest -q backend/tests/test_geo_coords.py -p no:cacheprovider --tb=short`：16 passed。`py_compile backend/tests/test_geo_coords.py` 和对应 `git diff --check` 通过。Gemini 独立复跑也是 16 passed。
- **限制：**验证了该测试样例两处中国坐标的自动 UTM 分带；不代表全球所有经度/纬度、南半球、带界、跨带范围或其它投影均已穷尽验证。Antigravity 未显示数值型上下文用量。

### 网络分析服务定向审计（Gemini + GPT，只读）

- **范围与发现：**Gemini 在同一 Antigravity 会话检查 clean 文件 `backend/services/network_service.py` 与 `backend/tests/test_network.py`，并只读追踪现有 API/前端调用契约。范围包括 WGS-84 坐标与球面距离、路线方向/自定义代价启发式、服务区断值、最近设施可达分类、结果 GeoJSON 结构及图缓存边界。未发现新的可复现缺陷；两个目标文件未改动，既有用户修改保留。
- **GPT 复验：**干净 Python 3.13 环境运行 `backend/tests/test_network.py -p no:cacheprovider --tb=short`：17 passed（3.32s）。对服务和测试文件运行 `py_compile` 成功，`git diff --check -- backend/services/network_service.py backend/tests/test_network.py` 通过；目标文件状态仍 clean。Gemini 独立运行同一测试：17 passed（3.88s）。
- **限制：**测试使用合成路网；未调用 OSM/Overpass、真实城市路网或大型网络性能基准。服务区仍是可达节点凸包加经纬度缓冲的已披露近似，不是逐道路精确等时圈。Antigravity 上下文用量未显示。

### 数据发现与矢量下载导入定向审计（Gemini + GPT，只读）

- **范围与结论：**Gemini 在同一 Antigravity 会话检查 clean 的 `backend/services/data_discovery.py`、`backend/tests/test_data_discovery.py`，只读追踪 provider 和存储事务。检查请求/BBox/格式校验、provider 选择、发现句柄、矢量完整性和 CRS 验证、文件与目录元数据写入事务、失败回滚、重复写入保护及一期栅格拒绝提示；未发现需修改的可复现问题，也没有改文件。
- **验证：**GPT 独立运行 `$env:PYTHONPATH='E:\my_repo\Gis-WorkTable'; $env:PROJ_LIB='E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Lib\site-packages\rasterio\proj_data'; & 'E:\_codex-qa\gis-worktable-clean-193423f942a141788c9f7b977e59d4a9\.venv\Scripts\python.exe' -m pytest -q backend/tests/test_data_discovery.py -p no:cacheprovider --tb=short`：24 passed（2.64s）。Gemini 同会话执行相同测试：24 passed（2.41s）。`py_compile` 和目标文件 `git diff --check` 通过；目标服务与测试文件保持 clean。
- **限制：**搜索/下载路径使用 mock 与合成数据，未连接真实公网 Overpass/Nominatim、未执行真实远程下载或高并发/大范围拉取。栅格自动导入当前明确不支持，本轮没有将其计为已验收能力。Antigravity 上下文用量未显示。
- **补充 GPT 集成复验：**再与相邻存储事务测试联跑 `backend/tests/test_data_discovery.py backend/tests/test_data_provider_storage.py -p no:cacheprovider --tb=short`：26 passed（2.25s）。
