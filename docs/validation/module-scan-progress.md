# 逐模块缺陷扫描进度

更新：2026-10-27。本记录覆盖近期扫描和待处理证据，不代表全库已完成，也不把受控测试当作真实服务或界面验收。

## 近期已修复

| 模块 | 主要修复 | 验证及边界 |
| --- | --- | --- |
| 地铁服务 | 高德颜色与换乘字段；OSM 类型编号冲突、方向覆盖、线路截断、批量获取和失败提示 | 与启动器、地理检查合计 115 项针对性测试通过；真实高德数据通过；Overpass 实测超时，国际在线链路未验收 |
| 后端启动器 | Windows 只读进程探活；启动锁异常；超时进程残留；停止失败的返回状态 | 39 项相关检查通过，包含真实临时子进程探活 |
| 桌面客户端 | 环境选择、启动失败及时反馈、日志句柄、退出时进程树清理、实例隔离、运行配置身份和页面失败反馈 | 29 项桌面检查通过，含真实 Windows IPC、临时进程树和启动脚本；完整 Electron 窗口未验收 |
| 执行卡片与流事件 | 并行失败和重试汇总、重复事件、旧调用编号、缺失/迟到事件、截断前保留警告；图层加载后重试地图操作；选择取消连接后端并结束等待状态；移除无消费方的重试计数 | 42 项相关前端检查通过；38 项相关后端检查通过；包含受控聊天流及确认/取消链路，无真实模型或完整浏览器验收 |
| 图层注册、删除与工程保存 | 同步失败可见且可重试；注册写入有序；删除等待全部请求；注册版本保护同名新图层；重命名清理纳入同步；同步后重新采集保存状态；手动/自动保存共用队列；后台只保存前端明确列出的图层；支持无对话工程更新并保留已有历史；移除无生产方的旧清理状态字段 | 65 项相关前端检查通过；68 项相关后端检查通过，含应用内 HTTP 版本删除和保存校验；完整浏览器验收未进行 |

版本删除参数为可选字段；没有提供版本的既有调用仍保留按名称删除的语义。

### 上传模块

- 保留原始 GeoTIFF，并返回实际预留名称，解决上传后能显示却无法继续栅格计算的问题；预览 URL 编码特殊字符。
- 各格式原子预留文件，避免同名 CSV 或矢量覆盖；ZIP 使用已预留的包名注册，避免不同包内的同名 SHP 覆盖；流式限制体积，失败清理源文件和预览；GeoJSON 声明 CRS 时转换，未声明且超出经纬度范围时拒绝。
- 预览与上传按队列处理；大 GeoJSON 不在浏览器整文件展开；补全无扩展名文件；取消后忽略迟到响应，并按注册版本清理已知旧结果。
- CSV 空值安全序列化，转换使用实际路径；AI 正忙时保留手动转换入口，避免打断当前任务。
- 删除测试对旧私有 `handleFiles` 的依赖，覆盖真实文件选择与拖放入口；保留当前公开的 `init` 接口。
- 解压前限制 ZIP 展开体积和成员数量；CSV、矢量转换与云原生读取移出请求事件循环，避免大文件处理卡住其他请求。
- 验证：11 项前端、30 项上传后台检查通过，包含真实 GeoTIFF 上传后栅格计算、真实 CSV 和投影坐标转换。完整浏览器及工程导出/重载后原始栅格衔接尚未验收。

### 空间统计与工具图层同步

- 测试改走当前 `toggle` 和真实按钮事件；重开及切换页签刷新字段，支持单个 Feature；K 近邻和网格输入不再静默截断或替换无效值。
- 工具图层同步接入已有注册队列，保留别名的注册版本与规范名称，删除及保存会等待同步；同步失败阻止计算；不再静默跳过超过两万个要素的数据。
- K 近邻明确排除当前要素，修复重复坐标时选中自身；核密度对格点和输入点同时分块，控制临时数组内存。Moran 与热点当前的稠密矩阵实现限制为 3000 个要素，超出明确提示先聚合或抽样。
- 验证：空间统计、API、图层队列及保存相关 55 项前端检查通过；17 项空间统计后台检查通过，含重复坐标近邻与分块密度一致性。

### 分析工具、调试面板与工作区入口

- 分析工具使用当前菜单入口；立即提供本地图层，避免旧请求覆盖新刷新；修复原型键名称去重、单个 Feature 字段，以及无效源像元值变成 JSON null。6 项前端检查、21 项工具注册与参数连接检查通过；后者为静态契约检查，不等于 20 个算法的真实计算验收。
- 调试面板正确识别失败健康响应，周期更新连接状态，忽略关闭前的迟到响应；容忍空要素，重复加载样例使用独立地图身份与数据对象。8 项前端检查通过。
- 工作区关闭状态恢复测试改为点击真实页签事件；没有恢复旧 `setTab` 导出。工作区相关 8 项检查通过。

### 远程 COG 读取补充修复

- 单独复现远程 COG 失败：Windows GDAL 打开远程影像时抛出 `UnicodeDecodeError`，原先只覆盖部分证书错误的下载回退没有触发。
- 回退判定补全该异常；继续使用现有 300MB 下载上限和临时文件所有权清理。4 项受控检查覆盖预览、元信息及后续解析失败后的清理；修复后真实远程 COG 加载用例通过。

### 原始栅格的工程保存、导出与恢复

- 工程同时保存预览和原始 GeoTIFF；打包包含两者，导入后重写资源地址；缺失原始资源时明确失败，不能静默导出不完整工程。既有只含预览的工程继续保留显示能力。
- 栅格登记接入图层注册版本、工具同步及删除队列，重载后按当前工程中的名称定位原始文件；禁止回退到其他工程遗留的同名临时数据。
- 合并 9 处重复 TIFF 查找，移除名称包含匹配；6 处结果输出改到运行目录，避免修改工程资产。
- 工程读取与激活在同一锁内完成；激活失败恢复旧注册表和待处理状态，保留原历史。自动保存重命名栅格不会生成重复图层。
- 验证：15 项专门的工程栅格检查、91 项相关后台回归、57 项相关前端回归通过。包含真实 TIFF 上传、删除运行时原件、导出导入、删除原工程、重载并实际执行波段计算，以及检查计算输出未修改工程资产；无完整浏览器验收。

## 当前全量前端回归

命令：在 `frontend/` 运行 `node --test --test-concurrency=4 --test-reporter=spec`。

结果：196 项，196 通过，0 失败。此结果覆盖现有前端检查，不代表全库或完整浏览器验收通过。

本轮后台本地回归：127 项通过，覆盖上传、云原生本地文件及回退、空间统计、分析工具契约、图层注册生命周期和工程图层分组。45 条警告：44 条来自经纬度点图层的质心调用，1 条来自刻意缺少 CRS 的上传夹具。4 项远程 `slow` 用例在本地回归中排除；其中远程 COG 已单独复现、修复并重跑通过，另 3 项远程用例尚未完成验收。语法检查及改动差异空白检查通过。

缺失导出须先核对真实调用链。若是过时测试，应改为覆盖当前入口；不为凑通过率恢复无生产调用的旧接口。

## 2026-10-24 提交前回归

- 后台：对本轮 27 个改动过的后台测试文件运行本地回归（`-m 'not slow' -k 'not remote'`），531 项通过、20 项排除、60 条警告；不是整个后台测试目录的全量结论。首次组合运行发现旧测试未清理工程上下文，补齐隔离后重跑通过。
- 前端：`node --test --test-concurrency=4 --test-reporter=spec`，196 项通过。
- 桌面：`node --test --test-reporter=spec tests/main.test.cjs`，29 项通过。
- 此外，前一轮真实远程 COG 用例已通过，高德地铁真实数据已检查；其余远程服务、完整 Electron 和浏览器界面仍按各模块边界记录。
- README 与更新日志记录本轮累计修复；自动化数量和边界保留在本文，不将当前通过率当作全库扫描完成证明。

### 2026-10-25 核心用户流程手工验收

本轮在本地浏览器实际操作，记录及复现步骤见 [核心流程验收记录](core-workflow-acceptance-2026-10-25.md)。内置 Polygon 样例加载、500 米缓冲、工程保存后刷新并重新打开，以及在线 COG 加载和预览资产恢复均通过。新增的空间工具参数保护也通过界面检查：零距离与格式错误的多环距离列表均被拒绝，未新增图层。

另运行三组定向后台检查：139 项通过、4 项 slow 远程测试排除、1 条警告。它是独立批次，不与 2026-10-24 的 531 项结果相加。COG 界面加载成功；单独重跑远程 COG slow 集成用例为 1 passed，但有 `PytestUnraisableExceptionWarning`：Windows 上 Rasterio `log_error` 回调将 GDAL 错误字节按 UTF-8 解码时触发 `UnicodeDecodeError`，现有下载回退仍完成读取。该非致命运行时警告尚未消除，详细记录见验收记录。完整本地文件选择上传、真实 DEM 经浏览器栅格工具生成并持久化结果、.giswork 导出/导入和完整 Electron 验收仍未覆盖。

## 下一轮重点

继续核查尚未完成的浏览器/真实服务边界和后端模块：小型 GeoJSON 文件选择、预览和上传已在当前 Codex 浏览器中成功一次，旧 `Failed to fetch` 根因仍未知；聊天导出附件的错误响应、Blob URL 生命周期和 SVG/WebP 路径识别已修复并有自动测试，但尚未用真实 AI 回复在浏览器中点击下载。另有远程数据 slow 用例未在本轮运行。真实 DEM 分析、重用、工程保存与重开已有浏览器记录和截图。全库逐模块扫描尚未完成。

## 2026-10-26 追加模块核查

- **AI 聊天与 SSE 生命周期：**追踪 `frontend/js/chat.js` 的图层同步、流式读取、断流与重试分支，以及 `backend/main.py` 的 `/api/chat/stream` 到 `graph.run_agent_stream`。确认同步失败会停止模型请求；工具开始后断流不会自动重放整轮；后端初始化异常会发出可读 SSE 错误。修复 `backend/tests/test_session_lock_busy.py` 中把 busy 标记数量写死为 2 的脆弱静态断言：当前会话锁与共享状态锁均有流式/非流式冲突分支，源码共 4 处标记，行为测试已分别覆盖流式和非流式忙响应。前端聊天生命周期 10 项通过，相关后端 38 项通过。未运行真实模型；本地浏览器地址拒绝连接，未作运行时验收。
- **工具菜单与英文本地化：**检查 `frontend/index.html` 菜单标签、`frontend/js/i18n.js` 词条和本地化护栏。截图中出现的菜单条目在当前静态 HTML 均有关联 key，英文词条齐全；相关静态测试 3 项通过，未确认当前源码有本地化缺陷。尝试打开本地页面时 `127.0.0.1:8000` 返回 `ERR_CONNECTION_REFUSED`，因此实际语言切换和浏览器渲染仍待运行时确认。
- **工程导入、导出与恢复：**追踪 `frontend/js/workspace.js` 的导入/导出入口、`backend/main.py` 的导入 API、`backend/services/project_service.py` 的 ZIP 校验/资产迁移/工程重建，以及 `frontend/js/project.js` 的恢复流程。确认导入 API 原先把整个上传包读成内存 `bytes`，服务又包一层 `BytesIO`；现已改为把 FastAPI 已暂存的文件流传给服务，保留原有 `bytes` 调用方式。新增上传流入口回归测试；工程持久化后台 37 项、前端加载/导出生命周期 10 项通过。当前仍没有 ZIP 条目数/解压总量限制，是否加入需先确定可接受的工程资产上限，避免拒绝本应用可生成的大型栅格工程；本地浏览器服务未运行，未做真实下载/导入界面验收。
- **工作区保护：**本次连续扫描保留开始前所有未提交内容；在已有改动的 `backend/main.py`、`backend/services/tools.py` 和进度文档上只改相关链路并追加记录；此前干净的 `backend/services/project_service.py`、`backend/tests/test_layer_group_persistence.py`、`backend/tests/test_integration_e2e_v4.py` 为本次目标新增修改。`backend/tests/test_execute_python_credentials.py` 是本轮新增回归测试；其他既有文件未回滚或整理。差异空白检查通过（Git 提示若干文件可能发生 LF/CRLF 转换）。
- **开放数据发现与获取：**追踪 `discover_gis_data` / `download_gis_data` 到 `data_discovery.discover/download`、OSM Provider、矢量校验/落盘、metadata 与地图图层注册。核实 OSM 截断、源端 remark、跳过几何都会进入结果说明或 metadata；候选 handle 有进程内上限，未发现本轮可复现的功能缺陷。发现/句柄/存储针对性测试 29 项通过，均为受控测试；真实 Overpass/Nominatim 未在本轮调用，故不声称在线服务通过。重复同名数据采用覆盖语义（现有 catalog 测试明确验证），若需保留历史版本属于后续产品决策。
- **网络分析与路径规划：**追踪 `network_analysis` 工具到 `network_service` 的建图、方向约束、路线/服务区/最近设施，并检查其结果图层出口。代码确认服务区边界用可达节点凸包加固定 `0.001°` 缓冲近似，旧工具回复没有说明这一限制；现已在成功回复中标出近似算法和边界含义，不改变计算结果。网络服务与工具链测试 31 项通过，使用合成路网，未用真实城市路网或在线路径服务验收。
- **`execute_python` 与工具 API 暴露：**复核 `execute_python` 到子进程的凭据传递、AST 检查、超时及输出回收。原实现将 `_current_amap_key` 注入脚本全局并写入子进程 `AMAP_KEY`；专用高德工具已有独立密钥路径，用户代码没有必要持有该凭据。已移除脚本注入，并确保子进程环境删除 `AMAP_KEY`；新增哨兵测试检查脚本和环境，不读取真实凭据。AST 安全测试 4 项、普通 Python 计算测试 2 项、工具 API 路由测试 4 项及凭据回归测试 1 项通过。残余风险：子进程仍继承其余父进程环境，白名单 GIS 库具文件/网络能力，不能视为安全沙箱。`/api/tools/invoke` 当前无认证依赖且 CORS 允许任意来源；桌面与内置启动器默认绑定 `127.0.0.1`。手动改为网络监听后的可达性/浏览器跨源风险未运行确认；未改权限、认证或执行隔离架构，公开部署不应按已加固处理。
- **`execute_python` 与工具 API 暴露：**复核 `execute_python` 到子进程的凭据传递、AST 检查、超时及输出回收。原实现将 `_current_amap_key` 注入脚本全局并写入子进程 `AMAP_KEY`；专用高德工具已有独立密钥路径，用户代码没有必要持有该凭据。已移除脚本注入，并确保子进程环境删除 `AMAP_KEY`；新增哨兵测试检查脚本和环境，不读取真实凭据。AST 安全测试 4 项及普通 Python 计算测试 2 项也通过。残余风险：子进程仍继承其余父进程环境，白名单 GIS 库具文件/网络能力，不能视为安全沙箱。`/api/tools/invoke` 当前无认证依赖且 CORS 允许任意来源；桌面与内置启动器默认绑定 `127.0.0.1`。手动改为网络监听后的可达性/浏览器跨源风险未运行确认；未改权限、认证或执行隔离架构，公开部署不应按已加固处理。
- **矢量叠置与融合工具：**沿 `spatial_intersect`、`spatial_union`、`spatial_difference`、`spatial_clip`、`spatial_simplify`、`spatial_dissolve` 和 `spatial_join` 检查图层读取、几何修复、叠置和结果注册。确认 `spatial_dissolve` 收到不存在的 `group_by` 字段时，原逻辑会静默对全部要素融合，容易把字段拼写错误当成成功分析；`spatial_simplify` 未检查容差，零/负值可报告成功但没有执行有效简化。现两者分别在字段缺失、容差非有限或非正时明确报错且不创建产物，补充无副作用回归测试。`backend/tests/test_spatial_tools.py` 新增用例后共 106 项通过；运行有 2 条环境警告（pytest 缓存目录权限、joblib 物理核心探测回退），未影响测试结果。测试使用受控 GeoJSON，不等同于真实数据/浏览器端验收。
- **栅格结果链路复核（代码与自动测试）：**追踪 `dem_analysis`、`_raster_preview_op`、`_register_raster_layer`、前端 `dem_result` 图层操作、图层检查面板和工程资源恢复。代码和测试覆盖栅格原始 GeoTIFF 注册、再次计算和项目恢复；`backend/tests/test_dem_analysis.py` 与 `backend/tests/test_project_raster_persistence.py` 合计 21 项通过，使用受控生成的带 CRS GeoTIFF，不能作为真实地形数据验收；`node --test frontend/tests/chat_send_lifecycle.test.cjs` 10 项通过，其中覆盖栅格结果进入图层面板及工程元数据。仓库没有可直接用于浏览器演练的真实 DEM 文件。尝试打开当前本地浏览器地址 `http://127.0.0.1:8000/` 返回 `ERR_CONNECTION_REFUSED`，因此本轮未完成浏览器链路，也未声称真实 DEM 端到端通过。需准备带有效 CRS 的真实 DEM 并启动本地 WTB 后继续验收。

### 2026-10-26 真实 DEM 浏览器链路续验

- 使用项目现有 AWS Terrain Tiles 下载链路准备长沙区域的一块 SRTM-derived DEM（EPSG:4326，59×67 像元，范围约 112.90–112.92°E、28.20–28.22°N，高程约 27.36–76.21 m；来源说明和引用链接进入图层元数据）。浏览器的本地文件上传仍返回 `Failed to fetch`，故输入 GeoTIFF 通过本地 API 上传；不能据此声称浏览器文件选择上传已通过。
- 在真实浏览器新页面恢复含 DEM 和坡度结果的工程。原始 DEM 和恢复后的坡度图均可在栅格工具输入列表中选择；浏览器内执行坡向分析后，图层面板从 2 张栅格增加到 3 张，地图叠加同步为 3 张。通过界面保存工程，再在另一新页面恢复，3 张栅格及其资产均可重新显示；项目 API 复核三张图层均保留 GeoTIFF 资产、CRS、像元大小/单位、结果数值单位、数据来源和处理元数据。恢复后再次从原始 DEM 执行坡度分析，仍为 3 个逻辑图层和 3 个地图影像，工具返回成功。
- 浏览器内逐一检查原始 DEM、坡度和坡向图层的栅格检查面板：来源链接/名称、处理步骤、EPSG:4326、WGS-84 范围、度制像元分辨率、栅格尺寸、波段、m 或 °（角度）值单位、有效像元比例及质量提示均可见。坡向检查最初发现质量提示误称“坡度水平距离”；提示已改为适用于地形导数的一般性说明，并增加地理坐标 DEM 自动测试。更新后的坡向结果已在浏览器重算、手动保存，并在新页面重新打开确认通用提示和其余元数据仍显示。
- 重开后的三图层和栅格检查面板截图：`docs/validation/raster-dem-save-reopen-2026-10-26.png`。
- **本轮复现并修复 P1 地图/图层不同步：**修复前，在工程恢复后重复执行同名坡度分析，面板保持 2 层但地图影像变为 3 张。工程恢复以工程临时地图名登记预览，`dem_result` 重算以输出 PNG 名登记，地图层去重只按显示名查找，未识别为同一栅格。现 `map.addImageOverlay` 也按稳定图层 ID 替换已有影像；恢复工程和 `dem_result` 均传入后端栅格名作为稳定 ID。新增地图替换回归测试，并更新聊天及工程恢复测试契约。
- 定向前端回归：`node --test tests/map_layer_visibility.test.cjs tests/project_save_sync.test.cjs tests/project_load_race.test.cjs tests/chat_send_lifecycle.test.cjs` 在 `frontend/` 执行，37 项通过。完整前端回归 203 项中 179 项通过、24 项失败；23 项失败是既有 i18n 事件监听接入后测试夹具没有提供 `document.addEventListener`（图层专题、地图导出、图层清理、空间字段等测试），另 1 项为 `workspace_dock_state.test.cjs` 对近期工程卡片的既有断言失败。该全量结果未全绿，本轮未扩大栅格修复范围去改其他模块夹具或工作区卡片逻辑。
- 真实浏览器流程未覆盖本地文件选择器上传：此前尝试显示 `Failed to fetch`，输入 GeoTIFF 改用本地 API 上传。当前只能确认浏览器上传链路有待调查，尚不能判断是产品缺陷还是浏览器/环境限制；上传模块是后续优先核查项。使用真实在线模型、第三方在线 GIS 分析服务也不属于本验收。当前本地验收服务为本轮启动，检查结束后已停止。

### 2026-10-26 文件上传链路核查

- 追踪 `#fileInput` / 拖放 → `frontend/js/upload.js::handleFiles/startUpload` → `frontend/js/api.js::upload` → `backend/main.py::/api/upload` → 格式解析/CRS 处理/栅格或矢量注册 → 前端地图与图层面板。前端对 CSV/GeoJSON 限制 64 MB、其他格式 300 MB；后端也执行相同格式级限制，GeoJSON 解析、CRS 转换、ZIP 解压成员/总量及文件名路径均有校验。现有后端上传用例覆盖 GeoTIFF、矢量、错误格式和安全边界。
- **已复现的用户提示问题：**此前本地浏览器上传显示原生 `Failed to fetch`，用户不知道服务端是否已收到文件。代码证实 API 将 fetch 网络拒绝原样传递、上传 UI 再展示原始异常；API 地址还允许从 `localStorage.gis_api_base_url` 覆盖。无法读取该浏览器上下文的设置，也没有浏览器上传的端到端复现，所以底层连接失败原因仍属**待运行确认**，不能断言是跨域、错误地址或 WTB 服务故障。
- 已对非取消的上传 fetch 拒绝标记 `UPLOAD_NETWORK_ERROR`，上传界面改为提示“服务端可能已收到文件”，引导先检查图层后再决定重试，避免盲目重复导入；英文界面增加对应文案。AbortError 仍保持取消语义，不显示网络错误。该改动改善失败可理解性和恢复决策，不修复也不宣称解决底层浏览器连接失败。
- 前端 API/上传/i18n 定向回归：`node --test tests/api_provider_key_storage.test.cjs tests/upload_preview.test.cjs tests/tool_menu_i18n.test.cjs tests/spatial_stats_i18n.test.cjs`，27 项通过；新增断言覆盖网络错误状态和取消保持。后端上传测试：`python -m pytest backend/tests/test_upload_raster.py backend/tests/test_upload_vector.py backend/tests/test_upload_safety.py backend/tests/test_upload_handoff.py -q`，31 项通过、2 条警告（刻意缺少 CRS 的夹具及 pytest 缓存目录权限）。
- 本轮未完成本地文件选择器的真实浏览器上传，也未核实 `gis_api_base_url` 实际值；后续若能获得稳定浏览器文件选择操作，应先用小型 GeoJSON 复现并查看实际请求目标和网络结果，再决定是否修复连接配置或 CORS 等根因。

### 2026-10-26 前端回归基线恢复

- 首轮全量前端回归的 23 项失败来自不完整的测试文档对象：`layers.js`、`map.js` 和 `spatial.js` 已监听 `gis:languagechange`，对应专题样式、地图导出、图层清理及空间字段测试夹具没有 `document.addEventListener`。仅补齐这些测试夹具，不改产品运行逻辑。
- 剩余近期工程卡片测试揭示真实边界问题：非法 `layerCount` 被转换为 `NaN` 并展示给用户。`frontend/js/workspace.js` 现在对非负安全整数才展示图层数，否则显示本地化的“图层数未知”；`workspace_dock_state.test.cjs` 覆盖异常计数且仍验证恶意工程名称、时间和 ID 不会作为 HTML 执行。
- 全量前端回归 `node --test --test-concurrency=4 --test-reporter=spec`：205 项通过、0 失败。工作区、地图、图层和空间统计测试的定向失败均已消除；之前 203 项/24 失败的结果为修复前记录。

### 2026-10-26 空间统计模块续查

- 复核空间统计的 OLS 与权重矩阵契约，并确认两项测试原断言已不符合当前工具语义：权重矩阵文件是独立查看/下载产物，不是 OLS 或 Moran 的前置输入；前端分析面板只公开 `GIS.analysisTools.toggle`。已更新 AI 指引与测试，使其描述现有真实契约。OLS 对完全共线自变量此前忽略 `lstsq` 返回秩，仍输出看似有效的显著性结果；现检测秩不足并返回可操作错误，不生成统计摘要。
- 新复现“中位中心”代码按 X/Y 分别取中位数，而非最小化到所有点的总距离。非对称点集因此可能把坐标轴中位数误标为 GIS 中位中心。现以修正 Weiszfeld 迭代计算几何中位数，并保留可选权重；新增与独立数值优化参考比较的回归测试。
- 沿统计工具输入提示继续检查其 `spatial_centroid` 前置操作。高纬非对称面样例复现：原工具直接在 EPSG:4326 的经纬度上计算 centroid，输出与局部 UTM 米制质心相差约 0.056 度（约数公里量级），会把后续 KDE/点统计的位置带偏。现对非 Point 几何先转局部 UTM 求质心再转回原 CRS；纯 Point 图层保留原坐标。新增高纬投影对照回归测试，修复前测试失败、修复后通过。
- 验证：`python -m pytest backend/tests/test_stats_gap_tools.py backend/tests/test_spatial_stats.py backend/tests/test_ai_wiring_new_tools.py backend/tests/test_analysis_panel_wiring.py -q --disable-warnings`，84 项通过、45 条已知警告；`git diff --check -- backend/services/tools.py backend/tests/test_stats_gap_tools.py` 通过（Git 提示 LF/CRLF 转换）。本轮测试使用合成点集，未进行真实空间统计数据或浏览器验收。
- 质心修复后交叉回归：`python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_stats_gap_tools.py backend/tests/test_spatial_stats.py -q --disable-warnings`，160 项通过、46 条已知警告；相关文件 `git diff --check` 通过。输入为合成 GeoJSON，不代表真实广域/跨日期变更几何验收。
- **导出链路已复现并修复 Shapefile 字段冲突：**当一个长字段截断后的前 10 字符与另一已有短字段相同（例如 `abcdefghijk` 与 `abcdefghij`），旧逻辑未把原短字段名纳入冲突集合，GeoPandas 因重复列名拒绝导出。现先保留已有合法短字段名，并为截断字段生成唯一、大小写不敏感的 10 字符名称。新增真实写出 ZIP、重读 Shapefile 并核对两列值的回归测试，修复前失败、修复后通过。SHP 数据为合成点，不代表所有 DBF 字段类型/编码组合均已覆盖。
- **导出路径边界和附件识别问题已复现并修复：**`/api/layer/register` 接受图层名，GeoJSON 导出原先直接把该名称拼入临时输出路径。测试用 `../../outside & field` 作为注册名，证实旧实现会将文件写到配置输出目录之外，且该文件名不符合聊天附件路径识别字符集。现在所有矢量格式都将图层名限制为有限长度、安全字符集（同时符合聊天附件识别规则）的文件名；注册名和地图显示名不变。新增测试检查路径仍在输出目录内、附件正则能识别文件名，并通过 FastAPI TestClient 请求 `/output/<文件>?download=true`，验证返回内容及 attachment 响应头。修复前路径测试失败，修复后通过；没有进行真实浏览器或网络监听验收。
- **产物核验器与导出登记已复现并修复：**实际生成并声称 SHP、GPKG、CSV、CSV-XY 文件后，`result_guard.verify_result(..., run_id=...)` 将其判为 `UNREGISTERED`；GeoJSON 原先已有登记。原因是另外四条成功导出分支没有调用 `record_tool_artifact`，导致流式 Agent 本轮账本无法证明文件归属。现在各格式仅在文件真实性校验通过后登记为本轮产物；新增五种导出格式的工具—SQLite 台账—核验器回归，修复前 4 种失败，修复后 5 种均通过。文件由真实导出代码生成，SQLite 中使用唯一测试 run id；不声称真实 AI 会话已完整浏览器验收。
- 导出、空间分析及产物台账交叉回归：`python -m pytest backend/tests/test_coverage_gap.py backend/tests/test_spatial_tools.py backend/tests/test_stats_gap_tools.py backend/tests/test_spatial_stats.py backend/tests/test_result_guard.py backend/tests/test_result_guard_v2.py backend/tests/test_storage_service.py -q --disable-warnings`，223 项通过、0 失败、2 条警告。SHP 实际 ZIP 重读、字段值检查，五种导出格式接入实际 SQLite 运行台账并通过结果核验，以及 GeoJSON HTTP 下载测试均通过。`git diff --check` 对本轮相关源文件、测试和进度文档通过；Git 仅提示相关文件可能发生 LF/CRLF 转换。
- 浏览器端验收限制：检查 `http://127.0.0.1:8000/` 返回连接拒绝；本轮只用 FastAPI TestClient 验证下载端点，未启动服务或声称 UI 下载按钮已在浏览器通过。
- 修复前的空间统计测试警告已追因：44 条是 `backend/services/tools.py` 对 geographic CRS 的 Point 几何调用 GeoPandas centroid，Point 的结果虽恒等仍产生提示；另 1 条是 pytest 缓存目录权限。Point 路径现已直接提取坐标，并由回归测试确认数值不变且无 geographic-CRS 警告。MultiPoint 在旧度制阈值下仍按坐标空间 centroid 代表点处理；米制/KNN 路径先投影，度制兼容参数仍代表度而非米。

### 2026-10-26 云原生栅格与台账续查

- 导出与产物核验器缺陷及修复详见上面的空间统计续查记录。五种矢量导出均接入本轮 SQLite 产物台账；新增五格式回归，实际写文件并由 `result_guard.verify_result` 核验。
- 复查 `backend/services/cloud_native.py` 的 `read_cog` / `cog_info`、向量源解析和远程临时文件生命周期：HTTP(S) 默认经 GDAL `/vsicurl/`，异常时 urllib 回退下载；回退检查声明长度和实际流长度，均限制 300 MiB，并通过已拥有临时文件集合在读取后清理。非 slow 云原生用例 `python -m pytest backend/tests/test_cloud_native.py -q -m 'not slow' --disable-warnings`：23 项通过、4 项 slow 外部服务用例未运行、1 条 pytest 缓存目录权限警告。当前未发现新的可复现功能缺陷。
- **风险推测（部署边界）：**云栅格/向量工具接受用户指定的 HTTP(S) 数据 URL，远程请求跟随标准 urllib/GDAL 网络行为；若把无认证工具 API 暴露给不可信网络用户，可能形成服务器侧请求风险。该能力本身服务于远程 GIS 数据获取，本轮不加 URL 白名单或扩大权限改造；部署应保持本机边界，公开服务需单独设计请求目标/重定向和网络隔离策略。没有做网络监听下的可达性或 SSRF 实测。
- 前端服务仍未通过浏览器手工验收；上一轮 Computer Use 无法高置信确定当前浏览器 URL 后终止，按工具要求未继续操作。真实远程 COG/PMTiles/FlatGeobuf/GeoParquet slow 用例和真实 AI 会话仍与本地自动化测试分开记录。
- 后续复核已将普通 Point 的警告根因确认：GeoPandas 对经纬度 Point 计算 centroid 虽数值恒等，仍发出 geographic CRS 警告。`_spatial_feature_coordinates` 现对纯 Point 图层直接取坐标；新增坐标保持与无 geographic-CRS 警告测试。空间统计定向组现为 54 项通过、仅 1 条 pytest 缓存目录权限警告。MultiPoint 仍按现有代表点规则处理；米制/KNN 路径先投影，旧兼容度阈值仍按度计算，不将其描述为米制距离。

### 2026-10-26 Cesium 3D 渲染器异步失败路径

- 检查 `frontend/js/renderer_cesium.js` 的 GeoJSON 异步加载、共享状态同步、清空/删除版本保护和新图层自动定位。最初怀疑加载期间切换可见性会写入旧状态；核对后发现共享状态原地更新同一图层记录，现有加载完成逻辑读取的是更新后的 `visible`，删除/清空也由版本号阻止旧请求回挂，因此不作为缺陷。
- **已复现并修复自动定位错误：**`syncLayer` 捕获 GeoJSON 加载异常后会以已处理的 Promise 完成，原 `layer-added` 回调仍无条件按 `bbox` 飞行，导致加载失败时相机跳向不存在的图层范围。现在仅当对应 Cesium data source 已挂载时自动定位。新增失败路径回归测试，断言无数据源新增且相机不移动。
- 验证：`node --test frontend/tests/renderer_cesium_clear.test.cjs frontend/tests/renderer_cesium_style.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/layers_group_state.test.cjs`，16 项通过。测试使用受控 Cesium/DOM 替身；本地服务未运行，未进行真实浏览器 3D 加载验收。模块逐项扫描仍在进行。

### 2026-10-26 DEM Hillshade NoData 传递

- 追踪 `dem_analysis` 的坡度/坡向/山体阴影数据计算、GeoTIFF 写入、PNG 预览、`dem_result` 注册与 `raster_calculator` 再分析。确认山体阴影分支把计算无效像元设为数值 0，而输出 GeoTIFF 的 NoData 标记为 NaN；后续质量统计以有限值判断有效像元，因此无法区分无效区与真实黑色像元，并会把 NoData 当成可继续分析的数据。
- **已复现并修复：**新增含 16×16 NoData 区块的合成 DEM。修复前结果元数据 `valid_pixel_ratio` 为 `1.0`，应低于 `0.9` 的质量告警阈值；输出栅格 NoData 区也被写成 0。现在分析输出保留 NaN，只有 PNG 预览将其渲染为黑色；质量统计能识别无效像元，栅格计算器后续 `B1*2` 也保留 NaN。
- 验证：`python -m pytest backend/tests/test_dem_analysis.py backend/tests/test_project_raster_persistence.py -q --disable-warnings --tb=short`，22 项通过、1 条环境警告。包含受控合成 DEM、真实 GeoTIFF 写读及本地工程持久化测试；不代表真实 DEM 浏览器工作流或真实 AI 会话验收。模块扫描继续。

### 2026-10-26 本轮开始时工作区快照

- 开始检查前的 `git status --short` 已有大量未提交内容；以下均作为既有工作保留。已修改：`CONTRIBUTING.md`、`README.md`、`backend/main.py`、`backend/services/ai_service.py`、`backend/services/project_service.py`、`backend/services/tool_args_guard.py`、`backend/services/tools.py`、`backend/tests/test_ai_wiring_new_tools.py`、`backend/tests/test_analysis_panel_wiring.py`、`backend/tests/test_coverage_gap.py`、`backend/tests/test_dem_analysis.py`、`backend/tests/test_integration_e2e_v4.py`、`backend/tests/test_layer_group_persistence.py`、`backend/tests/test_project_raster_persistence.py`、`backend/tests/test_session_lock_busy.py`、`backend/tests/test_spatial_stats.py`、`backend/tests/test_spatial_tools.py`、`backend/tests/test_stats_gap_tools.py`、`backend/tests/test_upload_raster.py`、`desktop/package-lock.json`、`desktop/package.json`、`docs/research_3d_globe_drilldown.md`、`docs/showcase.md`、`docs/validation/module-scan-progress.md`、`frontend/index.html`、`frontend/js/api.js`、`frontend/js/chat.js`、`frontend/js/connector.js`、`frontend/js/geosource.js`、`frontend/js/layers.js`、`frontend/js/map.js`、`frontend/js/project.js`、`frontend/js/renderer_cesium.js`、`frontend/js/settings.js`、`frontend/js/spatial.js`、`frontend/js/spatial_stats.js`、`frontend/js/upload.js`、`frontend/js/workspace.js`、`frontend/tests/api_provider_key_storage.test.cjs`、`frontend/tests/chat_send_lifecycle.test.cjs`、`frontend/tests/layer_symbology_persistence.test.cjs`、`frontend/tests/map_export_composition.test.cjs`、`frontend/tests/map_layer_visibility.test.cjs`、`frontend/tests/project_load_race.test.cjs`、`frontend/tests/renderer_cesium_clear.test.cjs`、`frontend/tests/spatial_fields.test.cjs`、`frontend/tests/upload_preview.test.cjs`、`frontend/tests/workspace_dock_state.test.cjs`。
- 开始时未跟踪：`CONTRIBUTING.en.md`、`README.en.md`、`backend/tests/test_execute_python_credentials.py`、`docs/competition/demo-runbook.en.md`、`docs/competition/demo-runbook.zh-CN.md`、`docs/competition/submission-brief.zh-CN.md`、`docs/validation/core-workflow-acceptance-2026-10-25.md`、`docs/validation/raster-dem-save-reopen-2026-10-26.png`、`frontend/js/i18n.js`、`frontend/samples/GIS-WorkTable-Competition-Demo.giswork`、`frontend/tests/spatial_stats_i18n.test.cjs`、`frontend/tests/tool_menu_i18n.test.cjs`、`frontend/ui-style-comparison.html`。
- 本轮改动触及开始时已修改的 `backend/services/tools.py`、`backend/tests/test_dem_analysis.py`、`frontend/js/renderer_cesium.js`、`frontend/tests/renderer_cesium_clear.test.cjs` 和进度文档；均在阅读现有差异后追加局部修复/测试/记录，未清理或覆盖其他既有改动。pytest 缓存目录访问被 Windows 拒绝，导致一条缓存警告；未影响测试执行。

### 2026-10-26 文件上传模块续查

- 追踪前端文件选择/拖拽、预览、`GIS.api.upload`、`POST /api/upload`、后端 CRS 检查与图层注册，再回到地图叠加和图层面板。确认网络异常会保留 `UPLOAD_NETWORK_ERROR` 语义，提示用户先检查图层再决定是否重传；后端超限、解析失败及转换失败分支会清理暂存资产。当前代码与现有回归未提供证据证明上次用户可见的连接中断是上传实现缺陷。
- 验证：`node --test frontend/tests/upload_preview.test.cjs frontend/tests/api_provider_key_storage.test.cjs`，24 项通过；`python -m pytest backend/tests/test_upload_raster.py -q -ra --tb=short`，5 项通过、1 条 pytest 缓存路径权限警告。当前 `127.0.0.1:8000` 无监听进程，无法复现实际浏览器到服务端的连接失败；该根因维持“待运行确认”，不归因于上传模块。
- 上传模块代码检查到此结束，后续可在服务端实际运行时补浏览器验收；本轮继续检查产物元数据的用户展示链路。

### 2026-10-26 栅格结果元数据展示

- 追踪后端上传/DEM/栅格计算结果中的 `raster_info` 到 `chat.applyRasterResult`、图层面板以及 `layers.js::showRasterLayerInspector`。确认项目 i18n 支持 `en`/`zh-CN`，英文界面图层和工具菜单会随切换更新，但新增栅格检查器的来源、CRS、像元单位、质量提示等字段固定为中文，且语言切换时不会重绘已经打开的检查器。
- **已修复并回归：**使用仓库真实 `i18n.js` 的前端测试先复现英文模式仍显示“栅格检查”；现将检查器标签、缺失值、来源链接和常见系统质量警告接入现有字典，并在打开检查器时响应语言切换。未知的供应方/文件自定义质量说明保留原文，不擅自机器翻译或改变数据内容。
- 验证：`node --test frontend/tests/raster_inspector_i18n.test.cjs frontend/tests/tool_menu_i18n.test.cjs frontend/tests/layers_group_state.test.cjs frontend/tests/raster_tools_layers.test.cjs frontend/tests/project_load_race.test.cjs`，17 项通过。使用 DOM 替身验证中英文打开与切换；没有进行浏览器视觉验收，产品自定义的来源标签/质量备注仍可能与界面语言不同。

### 2026-10-26 DEM 高程值单位归一化

- 检查 `dem_analysis` 的 CRS 水平像元距离与高程值求导链路。水平距离对投影坐标统一换算为米、对经纬度栅格按椭球局部像元距离估算，但高程栅格显式标注为英尺时原实现仍把数值直接当米，导致坡度和山体阴影数值偏差。
- **已复现并修复：**用同一 10° UTM 物理平面分别存为米与国际英尺。修复前米制结果约 `10.00°`，英尺数据得到 `30.05°`。现在常见长度单位（m/cm/mm/km、国际英尺、美国测量英尺）先换算为米再求导；显式但无法识别的单位增加质量提示，仍按米解释，不静默声称已转换。来源单位仍保存到结果 metadata。
- 验证：`python -m pytest backend/tests/test_dem_analysis.py backend/tests/test_project_raster_persistence.py -q -ra --tb=short -p no:cacheprovider`，23 项通过；同时 `node --test frontend/tests/raster_inspector_i18n.test.cjs frontend/tests/tool_menu_i18n.test.cjs frontend/tests/layers_group_state.test.cjs`，4 项通过。输入为合成 DEM/本地 GeoTIFF，不代表所有厂商的单位标签写法或真实 DEM 浏览器验收；本轮 pytest 禁用了缓存插件，未产生缓存权限警告。
- 本轮初始的定向工作区检查确认分支为 `main`，上传相关已修改文件为 `backend/main.py`、`backend/tests/test_upload_raster.py`、`frontend/js/api.js`、`frontend/js/upload.js`、`frontend/tests/upload_preview.test.cjs`；其他既有未提交/未跟踪文件见前一条完整快照。本轮在既有脏文件 `backend/services/tools.py`、`backend/tests/test_dem_analysis.py`、`frontend/js/layers.js`、进度文档上追加小范围改动，并编辑既有未跟踪的 `frontend/js/i18n.js`；新建 `frontend/tests/raster_inspector_i18n.test.cjs`。未清理其他改动。

### 2026-10-26 矢量多环缓冲几何语义

- 追踪 `spatial_multi_ring_buffer` 的距离参数解析、局部 UTM 缓冲、dissolve、结果 GeoJSON 注册和地图输出。工具说明为每个距离生成一环，但原实现对 100m、200m 分别输出完整缓冲面，第二面包含第一面的全部面积；作为多环分区叠加或面积汇总时会重复计量。
- **已复现并修复：**新增几何包含测试，修复前 200m 结果仍包含源点，证明它是完整面而非外环。现按递增半径用前一半径缓冲面作差形成环带；`dissolve=true` 对前后缓冲的整体并集作差，`false` 对各要素逐一作差；非递增输入仍保持用户传入的输出顺序。重复距离会生成相同边界，现明确拒绝并保留已有同名结果。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py -q -ra --tb=short -p no:cacheprovider`，111 项通过，1 条 joblib 无法读取物理核心数的环境警告；包含新增内环排除、dissolve 与无序半径测试。定向交叉组 `backend/tests/test_spatial_tools.py::TestMultiRingBuffer backend/tests/test_coverage_gap.py` 为 48 项通过。未进行真实城市数据/浏览器面积叠加验收。
- 本轮起始分支为 `main`。起始 `git status --short` 与前述完整快照中的修改集合一致，另包含上一轮新增的 `frontend/tests/raster_inspector_i18n.test.cjs`；与本修复相关的 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py` 在开始时均已修改，本轮在现有改动基础上局部扩展，没有重置或覆盖。Git 报告 pytest 缓存目录不可访问；本轮验证使用 `-p no:cacheprovider`，未写入该目录。

### 2026-10-26 矢量面积测量范围与投影选择

- 追踪 `measure_area` 从已注册 WGS-84 GeoJSON 到 UTM 面积汇总和 Albers 提示。对 40° 经度 × 50° 纬度的合成多边形量测，原实现仍用范围中心所在的单个 UTM 31N：结果 `18,883,921.51 km²`；独立 WGS-84 `Geod.polygon_area_perimeter` 参考为 `19,659,198.40 km²`，相差约 3.94%。原有 Albers “交叉验证”本身也未覆盖这种大范围边界误差。
- **已复现并修复：**图层范围超过 6°、跨 UTM 带或超 UTM 常规纬度时，现逐多边形及其洞用 WGS-84 椭球环面积求和，并在结果中明确显示面积算法；局部单带范围保留原 UTM 测量和 Albers 交叉提示。大范围测试现在按独立椭球面积参考断言到 0.01 km²。
- 验证：`python -m pytest backend/tests/test_coverage_gap.py backend/tests/test_spatial_tools.py -q -ra --tb=short -p no:cacheprovider`，134 项通过、1 条 joblib 无法读取物理核心数的环境警告。使用合成矩形，未测试超过半个地球面积的环/跨日期变更无效几何；这类输入仍需明确边界语义或专项验收。
- 本轮相关文件 `backend/services/tools.py`、`backend/tests/test_coverage_gap.py`、`backend/tests/test_spatial_tools.py` 与扫描台账在开始时均已修改；改动基于当前内容局部追加。未清理或覆盖其他未提交/未跟踪文件。

### 2026-10-26 矢量转栅格零值与结果文件

- 追踪 `feature_to_raster` 从注册矢量 GeoJSON、属性字段烧录、GeoTIFF 写盘，到 `_raster_preview_op` 注册栅格资源及 `_find_uploaded_tif` 后续读取。代码确认属性字段路径原先以 0 同时作为背景填充值和 GeoTIFF NoData；合法的 0 值会因此无法与背景区分，统计也只检查大于 0 的像元。输出路径直接拼接目录，单独调用时依赖 `uploads` 目录此前已存在。
- **已修复：**属性字段转换使用 NaN 作为背景和 NoData，合法零值及负值保留为有效像元；烧录统计改为有效像元计数及真实值域；非数值和无穷属性返回可理解错误，空属性跳过。输出目录改为经 `_raster_output_dir()` 创建。未提供字段时仍保留原来的常量 1 和 0 背景行为。
- 回归测试覆盖零值与背景区分、GeoTIFF CRS/NoData、文件由栅格查找器定位并可交给重采样和重投影工具、文本字段错误反馈。第一次测试发现 GeoPandas 将 GeoJSON `null` 变为 NaN；实现已按空值跳过。之后测试发现隔离输出目录未建 `uploads`，实现改为复用栅格目录管理函数。
- 验证：`python -m pytest backend/tests/test_coverage_gap.py backend/tests/test_spatial_tools.py backend/tests/test_dem_analysis.py backend/tests/test_project_raster_persistence.py -q -ra --tb=short -p no:cacheprovider`，159 项通过，1 条 joblib 无法检测物理核心数的环境警告。为合成 GeoJSON/GeoTIFF 自动化测试，未进行真实浏览器、真实工程 UI 或外部服务验收；其他下游栅格工具对 NaN NoData 的支持仍需结合具体工具覆盖。
- 相关 `backend/services/tools.py`、`backend/tests/test_coverage_gap.py` 和本台账在本轮开始前均为已有修改文件；本修复只在已有内容上局部扩展，没有清理其他工作区改动。

### 2026-10-26 栅格重投影 NoData 续验

- 沿 `raster_reproject` 追踪已注册栅格路径、Rasterio 的 `reproject` 调用、源 profile 继承和 `_raster_preview_op` 结果注册。以矢量转栅格输出的 EPSG:4326 合成数据（有效像元值为 0，背景为 NaN NoData）重投影到 EPSG:3857，自动化用例确认输出仍包含有效零值及 NaN 背景，且可由栅格查找器定位。
- 本场景未发现需要修复的问题，未修改 `raster_reproject`。检查仅覆盖单波段、小范围合成数据及 EPSG:3857，不代表多波段、其他投影、真实 DEM 浏览器显示或所有重采样方式都已验收。
- 此续验在已有修改的 `backend/tests/test_coverage_gap.py` 上追加断言，进度记录文件在开始时也已有未提交修改；未清理其他工作区改动。

### 2026-10-26 矢量导出图层类型校验

- 追踪 `export_layer` 从 AI 工具入口、注册图层查找、GeoJSON/Shapefile/GeoPackage/CSV 格式分支，到导出文件验证与 artifact 注册。已登记栅格具有 `raster` 元数据且 `geojson=None`；原 GeoJSON 分支在类型/内容校验前直接执行 `geojson.get(...)`，对栅格图层调用会抛出未处理的 `AttributeError`。Shapefile 等分支也没有统一的栅格类型反馈。
- **已复现并修复：**新增测试先复现 GeoJSON 导出调用异常。现对栅格图层在所有矢量导出格式前返回明确的“当前仅支持矢量导出”提示，并对缺少有效 FeatureCollection 的矢量注册数据返回数据无效提示；没有新增栅格导出格式。AI 工具描述现列出实现支持的五种格式，并说明 CSV 与仅支持 Point 的 CSV 坐标导出区别；非 Point 输入现在返回可操作的格式建议，不再暴露 GeoPandas 异常。
- 定向验证：`python -m pytest backend/tests/test_coverage_gap.py::TestExportLayer -q -ra --tb=short -p no:cacheprovider`，14 项通过，覆盖原有 GeoJSON、SHP、GPKG、CSV、CSV 坐标导出与 artifact 结果校验，以及栅格图层对五种矢量格式的提示和非点 CSV 坐标导出提示。
- `backend/services/tools.py`、`backend/tests/test_coverage_gap.py` 和本进度台账在本轮开始前均有未提交修改；在其现有内容上局部修改，无清理其他工作区改动。未做浏览器下载或大型真实工程验收。

### 2026-10-26 execute_python 执行边界只读审查

- 本轮开始分支为 `main`。相关的 `backend/services/tools.py`、`backend/services/ai_service.py`、`backend/tests/test_spatial_tools.py` 已有未提交改动，`backend/tests/test_execute_python_credentials.py` 已有未跟踪内容；全量工作区状态与前述扫描快照中的其他改动均保留。本轮只在既有改动上修正 AI 提示并为既有凭据回归文件追加断言。
- **代码确认的适用边界：**`execute_python` 经 AST 白名单后，在同一 OS 用户权限下启动 Python 子进程，`cwd` 指向临时目录、超时 120 秒，并传入 `os.environ.copy()`（仅移除 `AMAP_KEY`）；代码未创建 OS/容器隔离，也未设置内存配额。相对工作目录和 AST 检查不能证明对任意不可信代码的文件、凭据或资源隔离。
- **代码确认的网络行为：**当检测到用户代码导入 `osmnx`，生成的执行前置代码会依次对多个公共 Overpass 地址发起带超时的 GET 探测。AI 提示同时要求 execute_python 不联网，并在其他规则中允许 osmnx；因此当前“禁止联网”的表述不覆盖该自动探测及 osmnx 自身网络能力。未进行外网请求验证，也未尝试沙箱绕过。
- **部署边界：**`backend/main.py` 的 `/api/chat` 路由未声明认证依赖，CORS 允许任意源；桌面启动器和标准 launcher 当前绑定 `127.0.0.1`。据此只能确认默认桌面启动是本机服务，不能认定被改为 LAN/公网监听时安全；未在公开部署环境测试。
- **已修正的提示缺陷：**`SYSTEM_PROMPT` 原称高德凭据会自动注入 `_AMAP_KEY`，但子进程准备逻辑明确移除 `AMAP_KEY` 且没有注入该变量。现改为说明当前工具不注入 `_current_amap_key`，并要求使用专用 GIS 工具。该修正避免模型依赖不存在的变量，不改变执行权限。
- **验证：**`python -m pytest backend/tests/test_execute_python_credentials.py backend/tests/test_spatial_tools.py::TestSandboxSecurity -q -ra --tb=short -p no:cacheprovider`，6 项通过。凭据用例对 `subprocess.run` 做了替身，不执行真实用户代码；AST 用例覆盖被拒绝的导入和良性内省样本，不是沙箱安全认证。
- **未改动及限制：**没有修改 AST 白名单、子进程环境、文件/网络能力、权限或部署方式；这些变化会影响安全边界和现有能力，需单独安全设计。当前证据不足以宣称该实现可供不可信用户使用。

### 2026-10-26 流式 Agent 工具执行后的整轮重试

- 本轮开始分支为 `main`；全量 Git 状态与前述快照相同，`backend/services/graph.py`、`backend/tests/test_stream_step_events.py`、`backend/tests/test_simple_path_guard.py` 在本轮开始时为干净文件，其他未提交/未跟踪文件继续保留。
- 追踪 `/api/chat/stream` → `run_agent_stream` → `agent.stream` → SSE `tool_start`/`tool_end` → 前端执行卡片。流式循环将工具调用和结果写入 `msgs` 并向前端发出；但临时网络错误分支此前无条件从最初的 `messages` 调用整轮 Agent 重试。已通过受控 FakeAgent 复现：先产生 `export_layer` 工具结果，再抛 `ConnectionError`，旧逻辑仍调用 `_invoke_agent_with_budget` 重跑。
- **已复现并修复：**流式入口只有本轮尚无任何工具调用且无工具结果时，临时模型/网络异常才进行一次整轮自动重试；一旦出现工具调用或工具结果，不再重放，转为错误/中断反馈并保留已产生步骤。
- 同一缺陷也存在于非流式 `run_agent`：`agent.invoke` 异常时没有中间消息可检查，旧逻辑对网络错误一律重试。现通过 LangChain `on_tool_start` 回调跟踪工具是否启动，仅允许无工具启动记录的临时异常自动重试；若工具已启动，则停止重放、提示检查部分结果，并把本次待推送图层/地图操作随失败响应返回。
- 同一组检查中发现 `test_simple_path_guard.py` 的用例使用三参数调用 `_should_use_agent`，而当前函数定义和生产调用均为两参数；已将该测试改为匹配实际函数契约，未改变路由逻辑。
- 验证：`python -m pytest backend/tests/test_agent_retry_safety.py backend/tests/test_stream_step_events.py backend/tests/test_empty_response_recovery.py backend/tests/test_simple_path_guard.py backend/tests/test_session_lock_busy.py -q -ra --tb=short -p no:cacheprovider`，48 项通过、0 失败；12 条 `create_react_agent` 迁移弃用警告。新回归使用 FakeAgent/FakeLLM，不调用真实模型或外部服务；工具执行以受控回调和 ToolMessage 模拟，验证自动重试决策及部分地图操作返回，而非外部副作用。
- Agent 回调兼容及多轮 GIS 状态复用验证：`python -m pytest backend/tests/test_gis_operation_context.py backend/tests/test_cartography_reuse.py -q -ra --tb=short -p no:cacheprovider`，15 项通过。该次检查发现 `test_gis_operation_context.py` 的临时数据库夹具没有创建直接工具调用所需的 run 记录，导致 artifact 外键失败；已补齐三个测试 run 的记录后复跑通过。这是测试夹具修正，不是产品行为修复。
- 本轮编辑原本干净的 `backend/services/graph.py`、`backend/tests/test_stream_step_events.py`、`backend/tests/test_simple_path_guard.py`、`backend/tests/test_gis_operation_context.py`，并新建 `backend/tests/test_agent_retry_safety.py`；所有开始前已有的其他脏文件均未清理或覆盖。

### 2026-10-26 Agent 超时后后台调用仍运行

- 追踪非流式 `/api/chat` 到 `run_agent`、`_invoke_agent_with_budget` 的等待 future、延迟锁租约，再检查 `/api/chat/stream` 的 `done` 结果与前端任务卡。Python 线程池无法强制停止已运行的 Agent；超时响应返回后，后台调用可能继续产生工具副作用，会话和 GIS 共享状态锁保持占用直到 worker 完成。旧响应却称“已自动停止”，未返回执行状态，前端默认把任务标为成功。
- **已复现并修复：**新增受控 FakeAgent 回归测试，确认超时后后台调用可以继续完成，且两类锁在其完成前均不可获取。非流式超时现在返回 `execution_status=timeout` 和准确提示；流式完成结果同样附带执行状态和超时说明。`/api/chat` 与合成 SSE done 透传该状态；前端把任务标为失败、执行卡标为中断，并说明不要立即重复提交及先检查结果。
- 验证：`python -m pytest backend/tests/test_agent_retry_safety.py backend/tests/test_stream_step_events.py backend/tests/test_empty_response_recovery.py backend/tests/test_simple_path_guard.py backend/tests/test_session_lock_busy.py backend/tests/test_gis_operation_context.py backend/tests/test_cartography_reuse.py -q -ra --tb=short -p no:cacheprovider`，64 项通过，12 条 LangGraph `create_react_agent` 弃用警告；`node --test frontend/tests/chat_send_lifecycle.test.cjs`，11 项通过。调用为合成 Agent/模型；未验证真实模型长时间调用或浏览器中的后台线程行为。
- Python 后台线程无法被该超时机制强制终止，超时后最终结果也不会自动推送给已返回的请求；本轮修正的是状态如实表达与避免重复提交，不是引入线程取消或迟到结果交付机制。公开部署仍需独立的任务生命周期/隔离设计。
- 相关修改限于 `backend/services/graph.py`、`backend/main.py`、`backend/tests/test_agent_retry_safety.py`、`frontend/js/chat.js`、`frontend/tests/chat_send_lifecycle.test.cjs` 和本扫描台账；保留其余既有未提交修改。

### 2026-10-26 地理编码与 POI 坐标链路

- 先依据当前扫描台账和截图核对真实 DEM 浏览器验收现状：长沙 SRTM 派生 DEM 的来源、EPSG:4326、坡向/坡度分析、图层复用、保存及新页面恢复已有记录；截图显示 3 个栅格图层和检查面板元数据。本机当前没有 8000/8010 监听服务，仓库也无可直接复跑的 DEM 文件，因此不把这份既有验收当成本轮现场重跑。
- 追踪 AMap POI 文字/周边搜索、GCJ-02/WGS-84 转换、OSM 备用范围构造、正向/逆向/批量地理编码以及只读定位工具。代码显示 AMap POI service 的网络异常只返回异常类型，但 `reverse_geocode` 原先把 `str(e)` 返回 AI/用户，`batch_geocode` 也将异常文本写入逐条结果。HTTP 客户端异常可能包含带 query-string API Key 的完整 URL；使用仅用于测试的哨兵 Key 和模拟 `ConnectionError` 已复现两处都会回显该值。
- **代码确认并修复坐标边界：**`reverse_geocode` 原先没有验证经纬度有限性及 WGS-84 范围，非法数字仍会进入坐标转换和外部请求。现拒绝 NaN/无穷值及经度越过 ±180、纬度越过 ±90 的输入；新增参数化用例验证无请求副作用。
- **已修复凭据回显：**逆向地理编码改为只返回异常类型；批量地理编码对单条失败返回固定“请求失败（异常类型）”，不回显异常文本。哨兵 Key + 模拟 `ConnectionError` 回归覆盖两条路径。成功路径、坐标转换、AMap→OSM 回退逻辑未改，未调用真实 AMap/Overpass 服务，也未读取用户凭据。
- 验证：`python -m pytest backend/tests/test_geocoding_error_safety.py backend/tests/test_geo_coords.py backend/tests/test_amap_poi_fallback.py backend/tests/test_readonly_location_tools.py -q -ra --tb=short -p no:cacheprovider`，28 项通过。测试仅使用哨兵 Key 和模拟 HTTP 请求。
- 本轮开始时 `backend/services/tools.py` 与扫描台账均已有未提交改动；在 `tools.py` 原内容上只调整两个异常反馈分支。新增 `backend/tests/test_geocoding_error_safety.py`；其余原有脏文件和未跟踪文件均保留。真实服务限流、API Key 配置和具体地点精度不在本轮验证范围。

### 2026-10-26 外部网页抓取错误与 URL 隐私

- 追踪 `fetch_webpage` / `scrape_page` → Scrapling → Playwright 子进程的 URL 和失败信息流。用户可提供完整 URL；旧逻辑会在非 200/疑似错误页日志中记录完整 URL，Playwright 失败时将 stderr 末行作为工具错误返回。URL 中的认证信息、路径 token 或 query 参数因此可能进入应用日志或 AI/用户对话。
- **已复现并修复：**以模拟 Scrapling HTTP 503、Scrapling 异常文本和包含凭据/路径/query token 的 Playwright stderr 验证泄漏。现 `fetch_webpage` 与 `scrape_page` 错误最多显示 `scheme://hostname` 和异常类型；浏览器子进程失败返回“目标站点未能加载”的简短说明，不回显 stderr。代价是隐藏底层浏览器错误码，保留错误类别及站点，避免凭据与签名 URL 外流。
- **待专项安全设计的风险推测：**抓取入口没有在传输前限制 scheme 或本机/私网目标；Playwright 使用用户传入 URL，工具 API 路由未见认证依赖且 CORS 为 `*`。若本地服务被网页跨源访问或改为不可信网络可达，可能涉及 SSRF/本地资源访问风险。未实际访问本机文件、云元数据或内网地址，也未证明浏览器端利用链；未修改 URL 访问权限，因为限制网络目标会改变现有抓取能力，需先做部署边界和重定向/DNS 解析安全设计。
- 验证：`python -m pytest backend/tests/test_external_url_redaction.py backend/tests/test_scrape_page.py backend/tests/test_geocoding_error_safety.py backend/tests/test_geo_coords.py backend/tests/test_amap_poi_fallback.py backend/tests/test_readonly_location_tools.py -q -ra --tb=short -p no:cacheprovider`，35 项通过。均为自动化受控测试；未运行真实网页抓取、跨源浏览器请求或第三方 API。
- 本轮开始时 `backend/services/tools.py`、扫描台账和地理编码新测试已是既有改动；在 `tools.py` 上局部增加 URL 标识脱敏。更新此前干净的 `backend/tests/test_scrape_page.py` 断言，并新增 `backend/tests/test_external_url_redaction.py`。未改权限、服务监听或网络访问策略。

### 2026-10-26 矢量空间连接谓词契约

- 追踪 `/api/upload` 的矢量 CRS 规范化、`_layer_to_gdf` 的 GeoJSON 注册读取和 `spatial_join` 输出注册。GeoJSON CRS 声明由上传路径转至 EPSG:4326；其他已支持矢量格式在 GeoDataFrame 输出前同样转 EPSG:4326，工具读取也按此坐标约定赋 CRS。检查未发现常规注册图层之间存在不同 CRS 而需要 `spatial_join` 自动对齐的证据，不因 CRS 猜测增加无必要转换。
- **已复现的工具契约缺陷：**`spatial_join` 的描述把 `nearest` 写成拓扑谓词，但实际调用 `geopandas.sjoin(..., predicate="nearest")`。本机 GeoPandas 以 EPSG:4326 点层复现 `ValueError`：nearest 不在可用 predicate 集合中。失败被外层泛化为工具异常，AI/用户无法从工具说明理解原因。
- **已修复：**工具说明移除 `nearest` 谓词；若用户仍传入该值，返回明确失败原因和 `nearest_pair` 入口（其语义为两图层最近的一对要素，不等同于逐目标要素最近邻空间连接），不创建空/误导结果层。未新增算法或更改空间连接输出格式。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialJoin backend/tests/test_tool_docstring_guards.py -q -ra --tb=short -p no:cacheprovider`，15 项通过，含正常 `intersects` 结果及 nearest 明确拒绝/无产物测试。使用仓库合成 GeoJSON；未执行真实模型任务或浏览器分析。
- 本轮开始时 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py` 和扫描台账均已有未提交改动；在现有内容上做局部扩展。未清理其他修改。

### 2026-10-26 工程 ZIP 导入资源边界复核

- 重新检查 `/api/projects/import` → `project_service.import_project` → `_extract_project_archive`。API 将 FastAPI 已暂存的上传流直接交给服务，服务先对绝对路径、路径穿越和 ZIP 符号链接做校验，再解压至新建的工程目录，并在后续工程结构校验失败时清理目标目录。当前实现没有检查 ZIP 成员数量、单项解压大小或总解压字节数；导出路径会把工程引用的完整栅格资产写入 ZIP，因此没有证据支持一个不影响现有大型工程的任意固定限制。
- **代码确认的资源风险：**攻击者/误选的高压缩比归档或超大归档在导入时可能占用过多 CPU、内存或磁盘。风险范围取决于服务是否只供本机单用户使用及上传体积上限；本轮没有构造或解压资源耗尽样本，也没有证明默认桌面环境可由远程用户直接调用该路由。
- 未加 ZIP 大小限制：需要先定义可接受的最大工程/栅格资产体积及超过上限后的交互，否则可能拒绝本应用正常导出的较大栅格工程。该项记录为**待产品/部署边界决策**，不等于导入链路已有完整资源保护。
- 验证：`python -m pytest backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，21 项通过，覆盖路径拒绝、工程结构校验、现有持久化及上传流传递；没有覆盖压缩炸弹、文件数上限、上传总量限制或磁盘耗尽。
- 本轮开始时 `backend/main.py`、`backend/services/project_service.py`、相关集成测试和扫描台账均已有未提交修改；本轮只读检查，未改这些文件或执行归档解压写入。

### 2026-10-26 手动 GIS 工具参数修正提示

- 追踪手动分析面板 → `GIS.api.invokeTool` → `/api/tools/invoke` → `validate_tool_args` → 分析面板结果反馈。后端已对 `raster_focal_stats.size` 偶数做向上调整并返回 `param_warnings`；此前前端只返回响应对象，没有把警告并入现有面板读取的 `response`。
- **代码确认并由回归测试覆盖的可理解性缺陷：**输入窗口大小 4 时后端按 5 计算，但手动工具面板只展示分析响应，用户无法从当前结果说明参数已自动改变。此结论限于参数修正提示的前端展示，不表示栅格计算结果已用真实 DEM 验证。
- **已修复：**`invokeTool` 保留 `param_warnings` 结构化字段，不将警告拼入可能进入聊天 Markdown 的 `response`。工作区通用结果面板会单独附加警告并转义 HTML；空间/栅格工具的旧版结果区域使用 `textContent` 展示警告。没有更改服务端参数修正、工具入参或 GIS 计算。
- 验证：`node --check` 覆盖 `api.js`、`workspace.js`、`spatial.js`、`raster_tools.js`；`node --test frontend/tests/api_provider_key_storage.test.cjs frontend/tests/workspace_dock_state.test.cjs`，21 项通过，新增断言分别确认 API 保留结构化警告和结果文本不变、工作区结果面板可见展示警告且将恶意 HTML 当文本转义。`python -m pytest backend/tests/test_tool_args_guard.py -q -ra --tb=short -p no:cacheprovider`，9 项通过，覆盖窗口 4 → 5 的服务端契约。本轮未运行真实栅格分析、真实模型或浏览器验收。
- 本轮开始时 `frontend/js/api.js`、`frontend/js/workspace.js`、`frontend/js/spatial.js`、两个相关前端测试文件与扫描台账已有未提交改动；API 测试含之前的上传网络错误测试。本轮在现有内容上局部增加提示呈现和回归测试；`frontend/js/raster_tools.js` 开始时无未提交改动，本轮为兼容的旧版结果区域增加纯文本提示显示。未清理其他工作区改动。

### 2026-10-26 工具与栅格菜单本地化复核

- 按截图现象追踪静态工具菜单 `frontend/index.html` → `frontend/js/i18n.js`：截图中菜单出现中英混杂，但当前工作区静态工具及栅格菜单标签都含 `data-i18n`，对应英文词条存在，初始化会按 `gis_ui_language`/浏览器语言翻译；语言切换也会重译静态 DOM。
- **当前代码证据未确认截图对应版本存在同一缺陷：**仓库已有 `tool_menu_i18n.test.cjs` 检查两组菜单所有按钮标签均有有效英文键，测试通过。本检查无法证明用户截图的运行页面已加载当前工作区文件，也未在浏览器中核对其实际语言偏好/缓存状态，因此截图的混杂来源仍待运行确认；本轮未盲改菜单。
- 验证：`node --test frontend/tests/tool_menu_i18n.test.cjs`，2 项通过。属于静态映射自动化测试，未验证真实浏览器运行时或缓存更新。
- 本轮开始时 `frontend/index.html` 已有未提交修改，`frontend/js/i18n.js` 与菜单测试是未跟踪文件；均由此前工作区改动提供。本轮只读复核，没有改动这些文件。

### 2026-10-26 AI 对话 SSE 与执行卡片复核

- 追踪自然语言发送 → 聊天前置图层同步 → `POST /api/chat/stream` → `main.py::_persisted_stream` → `graph.py::_run_agent_stream_impl` → 前端 SSE 解析/执行卡片。代码会按工具调用发出 `tool_start`/`tool_end`，为相关调用分配步骤 ID；前端识别取消、错误、断流与完整 `done`，在工具可能已执行后不自动重跑整轮；服务端只在非 busy 的 done 到达时持久化 assistant 回复。
- **本轮未确认新的高优先级缺陷。**自动化测试覆盖工具失败状态/部分成功标记、多个工具调用事件，以及前端同步阻断、栅格/矢量同步、等待用户选择、取消、断流结尾和超时显示。此证据不能证明真实模型会正确规划多步任务，也不能证明真实浏览器/网络断流下没有状态偏差。
- 验证：`python -m pytest backend/tests/test_stream_step_events.py -q -ra --tb=short -p no:cacheprovider`，20 项通过；`node --test frontend/tests/chat_send_lifecycle.test.cjs`，11 项通过。均为受控自动化测试；未调用真实模型、真实第三方服务或浏览器长任务。
- 本轮只读复核 AI/SSE 路径，相关源文件与测试在本轮开始时已有未提交改动；未修改这些文件。

### 2026-10-26 execute_python 执行边界复核

- 追踪 `execute_python` → AST 过滤 → 每次执行创建临时工作目录 → `subprocess.run`，代码执行限制包括导入/属性检查、cwd 切换和 120 秒超时；已将 `AMAP_KEY` 从子进程环境移除，专用高德工具继续使用应用内凭据。
- **代码确认的边界风险：**子进程环境仍由 `os.environ.copy()` 继承（仅移除 `AMAP_KEY`）；白名单 GIS/数据库具备文件和网络相关能力，且当前为普通子进程而非 OS 级资源/文件/网络隔离。AST 检查、临时 cwd 和超时可降低部分误用风险，但不足以证明对不可信用户代码安全。`/api/tools/invoke` 路由未见认证依赖，CORS 配置允许任意来源；默认桌面启动器使用回环地址，但若另行网络暴露，信任边界会显著变化。未尝试读取文件、访问网络目标或利用逃逸。
- **处理决定：**本轮不改执行架构或过滤任意环境变量。可信本地单用户原型与公开/多用户服务的设计要求不同；需要先确定部署边界，再整体设计凭据最小化、文件边界、网络策略、资源限额和运行隔离。不得将当前 AST 测试描述为安全沙箱证明。
- 验证：`python -m pytest backend/tests/test_execute_python_credentials.py backend/tests/test_spatial_tools.py::TestSandboxSecurity -q -ra --tb=short -p no:cacheprovider`，6 项通过。覆盖 AMap 凭据不透传和若干 AST 拦截，不覆盖通用环境秘密、资源耗尽、文件访问或网络访问。
- 本轮开始时 `backend/services/tools.py` 和安全测试文件已是未提交/未跟踪改动；只读审查与运行受控测试，没有修改这些代码或执行用户代码攻击载荷。

### 2026-10-26 栅格产物闭环复核续验

- 本轮核对既有真实 DEM 浏览器验收记录和截图，并对照 DEM 分析、栅格图层检查器、工程恢复测试。此前记录包含长沙 SRTM 派生 DEM 的分析、产物复用、保存和新页面恢复；截图可见 3 个栅格图层及检查器。当前仓库没有可直接重跑的 DEM 文件，本机服务也不可用，故本轮不将历史浏览器验收冒充成重新执行。
- 当前记录同时区分了截图时间与后续代码状态：截图里的英文主菜单和中文栅格检查器是元数据 i18n 修复前的状态；现有测试覆盖英文打开及切换时检查器更新，但这轮没有浏览器视觉复验。
- 本轮自动化复验：`python -m pytest backend/tests/test_dem_analysis.py backend/tests/test_project_raster_persistence.py -q -ra --tb=short -p no:cacheprovider`，23 项通过；`node --test frontend/tests/raster_inspector_i18n.test.cjs frontend/tests/raster_tools_layers.test.cjs frontend/tests/project_load_race.test.cjs`，14 项通过。测试日志中一条“图层未同步则跳过自动保存”来自故意验证失败分支的测试，测试本身通过。
- 未发现需要在当前代码上追加修复的问题；当前证据支持已有栅格分析、图层重用、持久化和元数据路径，但不能替代本轮真实浏览器重跑或覆盖所有 DEM 来源与 CRS。

### 2026-10-26 矢量结果来源/CRS 与质量警告展示

- 追踪矢量工具 `_push_layer`/`_geo_qa` → graph/API `qa_warnings` → `chat.applyToolResult` → `chat.addMessage`。矢量检查器展示后端 CRS、范围、字段和粗粒度来源类别；质量检查警告在聊天区单独展示。相比栅格检查器，矢量图层没有统一的源数据链接/处理链/输出单位元数据；范围数值虽有 CRS 字段，但没有明确的坐标单位标签。各工具响应中部分有单位说明，但没有证据表明所有工具统一持久化结果来源和质量信息。此项是代码确认的产品一致性缺口，跨工具补齐需要单独设计产物元数据契约，本轮不批量改动几十个工具。
- **已复现渲染安全缺陷并修复：**`chat.applyToolResult` 曾将 `qa_warnings.layer` 和 `qa_warnings.warning` 原样插入带内联 SVG 的系统消息；`chat.addMessage` 对该类含 HTML 的系统内容使用 `innerHTML`。用户/工具提供的带标签文本可能进入 HTML 渲染。现只对动态警告字段做 HTML 转义，保留固定 SVG；新增前端回归测试验证图层名及警告里的 HTML 标签均先转义。该用例覆盖渲染输入，不声称完成浏览器攻击验证。
- 验证：`python -m pytest backend/tests/test_geo_qa.py -q -ra --tb=short -p no:cacheprovider`，15 项通过；`node --check frontend/js/chat.js` 通过；`node --test frontend/tests/chat_send_lifecycle.test.cjs`，12 项通过。没有运行浏览器手动验收。
- 本轮开始时 `frontend/js/chat.js`、`frontend/tests/chat_send_lifecycle.test.cjs` 与进度记录均已有未提交改动；在现有改动上局部转义动态值、追加回归测试和记录。矢量来源/单位统一契约暂列下一轮产品/架构审查项。

### 2026-10-26 矢量分析结果的来源与工程恢复续查

- 追踪代表性 `spatial_buffer` → `_gdf_to_layer` → `chat.applyToolResult` → `project_service.save_project` → `project.js` 恢复。缓冲先在局部 UTM 按用户距离单位计算，再转回 EPSG:4326；AI 回复说明距离和单位。新图层在前端标为粗粒度 `source: ai`，项目保存其 `source`、`crs` 和 GeoJSON，但没有结构化记录源图层、工具操作、参数单位等可随图层检查/恢复的 lineage 字段。栅格结果元数据已有更完整的结构化处理信息。
- **未发现当前缓冲几何/单位链需要改动的证据。**缺少的主要是跨工具一致的结果 provenance 契约；单独添加缓冲字段会造成能力不一致，完整补齐则会扩展工具输出与工程数据契约。本轮记录设计缺口，暂不改变持久化格式或扩大修改范围。
- 验证：`python -m pytest backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，21 项通过；`node --test frontend/tests/project_load_race.test.cjs`，10 项通过。覆盖矢量工程状态与恢复路径，不覆盖新增 lineage 元数据（当前不存在），也未进行浏览器重新验收。前端测试输出的一条自动保存跳过提示来自同步失败分支的预期用例，测试通过。
- 本轮开始时项目服务、聊天、图层/工程前端及进度记录均已有未提交修改；只读审查，无相关代码修改。

### 2026-10-26 `.giswork` 矢量 blob 完整性

- 追踪 `POST /api/projects/import` → ZIP 安全解压 → `project.json` 校验 → CAS blob 迁移 → `load_project`。导入原来只校验 blob ID 格式，没有确认归档中存在相应 `blobs/<id>.geojson.gz`，也不核对解压内容是否与 content-addressed ID 匹配；导入可成功进入工程索引，但 `load_project` 对缺失 blob 静默返回 `geojson: null`，或在读取损坏内容时报错。用户会得到一个名义成功、实际缺少矢量数据的工程。
- **代码确认并修复：**导入现在要求每个引用的 blob 文件存在，流式解压并核对内容 SHA-256 前 12 位与 blob ID 相符；缺失、无法解压或内容 ID 不匹配时，在写入全局 blob/工程索引前拒绝导入并清理暂存工程。未改变 `.giswork` 格式或用户现有工程。
- 验证：`python -m pytest backend/tests/test_layer_group_persistence.py backend/tests/test_project_raster_persistence.py -q -ra --tb=short -p no:cacheprovider`，40 项通过。新增回归覆盖缺失、损坏 gzip 和内容哈希不匹配；既有矢量往返与栅格资产保存/重开用例通过。未进行浏览器 `.giswork` 文件选择器手动验收。
- 本轮开始时 `backend/services/project_service.py`、`backend/tests/test_layer_group_persistence.py` 与进度文档均已有未提交改动；在现有改动上追加完整性校验、回归测试和记录，其他工作区改动保留。ZIP 总解压资源上限仍是此前记录的部署/产品决策风险，本修复不替代资源限额设计。

### 2026-10-26 `.giswork` 导入错误反馈

- 追踪加载工程弹窗的文件选择 → `GIS.api.importProject` → `POST /api/projects/import`。后端 `HTTPException` 会返回具体 `detail`，但 API 客户端原先只抛出状态码；用户遇到缺 blob、坏 gzip 等校验失败时看不到可操作原因。导入失败后文件输入仍保留原值，浏览器通常不会再次触发同一文件的 `change`，妨碍直接重试。
- **代码确认并修复：**导入与导出错误现在保留后端 detail 并标注操作；选择文件后立即清空 input 值，失败时可重新选择同一个文件。没有改变成功导入后的工程恢复逻辑。
- 验证：`node --test frontend/tests/api_provider_key_storage.test.cjs frontend/tests/project_load_race.test.cjs`，24 项通过；`node --check` 检查 `api.js`、`workspace.js` 通过，相关 `git diff --check` 通过。新增测试验证导入和导出都显示后端 detail。测试输出中的“同步失败、跳过自动保存”日志来自既有预期失败用例。
- 本轮确认本地 8000/8010 端口无监听；未进行真实浏览器文件导入、失败后重试或跨刷新恢复验收。下一步应在可运行服务和有效 `.giswork` 样本下完成浏览器闭环，并检查成功导入后恢复失败的提示位置与工程是否可从历史列表重新打开。

### 2026-10-26 上传与图层注册链路复核

- 追踪文件选择/预览/取消 → `GIS.api.upload` → `POST /api/upload` → 格式解析与坐标转换 → 后端图层注册 → 前端地图叠加及图层面板。代码显示栅格要求源 CRS 并保留源文件；SHP/GPKG 等格式要求 CRS 后转换到 EPSG:4326；上传取消的迟到响应会尝试撤销后端注册。
- **审查结论：**本次检查的失败、取消、重复初始化、CSV 预览和栅格身份分支没有发现新的可复现高优先级缺陷，不做代码改动。上传结果元数据对矢量主要保留归一化后的 WGS-84 标记，源数据 CRS/来源的统一展示仍属于已有的 provenance 待办，不在本次误报为上传错算。
- 验证：`node --test frontend/tests/upload_preview.test.cjs`，12 项通过；`python -m pytest backend/tests/test_upload_raster.py -q -ra --tb=short -p no:cacheprovider`，5 项通过。前端测试覆盖由 mock 上传返回值驱动，不代表真实浏览器或真实地理文件验收。

### 2026-10-26 图层注册队列与地图显隐复核

- 追踪面板新增/重命名/删除 → 版本化后端注册 → AI 调用前同步 → 工程保存屏障，并对照 2D 地图显隐与工程恢复。现有实现为同一图层串行注册、同名清理设屏障、注册令牌保护新版本、失败重试前阻止旧状态保存；地图单测也区分用户显隐和比例尺显隐。
- **审查结论：**本次查看的注册竞态、离线失败、删除屏障、栅格别名和地图显隐路径均有针对性回归用例；未发现新的可证实高优先级缺陷，不改代码。自动化测试不能证明浏览器运行状态及后端真实并发行为。
- 验证：`node --test frontend/tests/layer_panel_rename.test.cjs frontend/tests/map_layer_visibility.test.cjs frontend/tests/project_load_race.test.cjs`，42 项通过。输出中的 offline/未确认注册日志和“跳过旧状态自动保存”是测试特意触发的失败分支，测试通过。

### 2026-10-26 SHP 导出失败响应识别

- 追踪图层面板 SHP 导出 → `GIS.api.exportShp` → `POST /api/layer/export-shp`。`_export_shp_sync` 对混合几何等不支持情形会返回错误；路由将其序列化为 JSON `{error: ...}`，默认仍是 HTTP 200。前端原来只检查 HTTP 状态，随后把 JSON blob 下载并命名为 `.zip`，这会把失败伪装成成功交付。
- **代码确认并修复：**SHP 导出客户端现在检查非成功 HTTP 响应及 JSON 错误响应，提取服务端错误；报错文本转义后再交给系统消息渲染，避免动态详情作为 HTML 解析。未改后端端点或导出格式。
- 验证：`node --test frontend/tests/api_provider_key_storage.test.cjs`，15 项通过，新增用例模拟 HTTP 200 JSON 错误并确认不触发下载而显示后端原因；`python -m pytest backend/tests/test_delivery_safety.py -q -ra --tb=short -p no:cacheprovider`，2 项通过，覆盖混合几何导出函数返回失败；`node --test frontend/tests/map_export_composition.test.cjs`，5 项地图 PNG/JPG/PDF 组合导出测试通过；`node --check frontend/js/api.js` 及相关 `git diff --check` 通过。未在浏览器中下载真实 SHP 文件，也未端到端调用本地 HTTP 端点。

### 2026-10-26 矢量检查器 CRS 可信标记

- 追踪 `/api/layer/inspect` → `inspect_geojson` → `_detect_crs` → 矢量检查器 CRS 状态。**已复现：**显式无效标识 `EPSG:999999` 原先被原样展示且 `crs_known=True`，UI 因此显示绿色“已知”标记；同一标识无法被当前安装的 `pyproj.CRS` 解析。该误报会让用户误信后续对数据坐标系的判断。
- **代码确认并修复：**通过现有 `pyproj` 解析显式 CRS 标识，解析失败时保留原始名称供诊断、将 `crs_known` 设为 false；仍标准化 WGS-84、CRS84 与 Web Mercator，合法的其他 CRS 名称继续保留。未引入依赖（`backend/requirements.txt` 已列 `pyproj>=3.5.0`）。
- 验证：修复前调用 `inspect_geojson` 得到 `EPSG:999999 True`；`python -m pytest backend/tests/test_layer_service.py backend/tests/test_geo_qa.py -q -ra --tb=short -p no:cacheprovider`，18 项通过，新增无效 CRS、合法投影 CRS、CRS84 和 3857 用例。该检查在服务函数级别，不是浏览器验收；矢量范围坐标单位和完整处理来源仍未统一展示，继续列为产品元数据待办。

### 2026-10-26 矢量图层坐标单位展示

- 延续 CRS 检查器链路：后端 `inspect_geojson` 返回 CRS 和范围，前端 `showLayerInspector` 展示这些值。此前用户只能把 CRS 与 bbox 数字放在一起自行推断坐标单位；EPSG:4326 与英尺制投影等数据尤其容易被默认当成米。
- **代码确认并修复：**`inspect_geojson` 现在从已解析 CRS 的首个坐标轴取得单位；GeoJSON 范围推断为 WGS-84 时标注 degree；无效/未知 CRS 不虚构单位。矢量检查器增加“坐标单位”行，常见 degree/metre/foot 转为本地化标签，其他单位保留原 CRS 轴单位名。该信息按检查时数据计算，无需扩展工程存储格式。
- 验证：`python -m pytest backend/tests/test_layer_service.py backend/tests/test_geo_qa.py -q -ra --tb=short -p no:cacheprovider`，19 项通过，覆盖 EPSG:32649、4326/CRS84、3857、未知/无效 CRS；`node --test frontend/tests/vector_inspector_units.test.cjs frontend/tests/raster_inspector_i18n.test.cjs`，2 项通过，验证投影单位在中英文界面的展示。前端使用 mock inspect 响应，未在真实浏览器和运行服务中验收。

### 2026-10-26 网络分析计算链复核

- 追踪 `network_analysis`/`od_cost_matrix` → 网络图构建与缓存 → 路径、服务区、最近设施和输出图层/文件。路网成本以 GeoJSON 经纬度上的 haversine 距离为默认权重；单行方向通过 `oneway` 影响有向图；服务区用可达节点凸包和角度缓冲近似，工具返回文本明确披露并未声称是逐道路边界。坐标解析限制经纬度有效范围并提供超出图层范围提示。
- **审查结论：**本次核对的方向性、成本字段、最近节点/路线、服务区断值与失败路径未发现新的可证实高优先级缺陷，不改代码。服务区是已披露的近似产品能力；真实 OSM 下载及实际城市路网表现仍未验证。
- 验证：`python -m pytest backend/tests/test_network.py backend/tests/test_integration_e2e_v4.py -q -ra --tb=short -p no:cacheprovider`，31 项通过。均为本地合成路网/受控集成测试，不代表第三方 OSM 服务或真实城市数据验收。

### 2026-10-26 开放数据发现与下载链复核

- 追踪数据发现请求 → 参数规范化/bbox 校验 → Provider 搜索 → 句柄注册 → 下载 Provider → 矢量完整性/CRS 校验 → 文件与 metadata 落盘 → 注册到 AI/地图图层。现有测试对 Provider 网络出口使用 mock，并覆盖 OSM 数据转换、格式白名单、CRS 缺失、截断/跳过要素、来源 metadata 和失败提示。
- **审查结论：**本轮核对现有路径及句柄容量/锁保护，没有发现新的可复现高优先级问题，不修改代码。数据句柄存于进程级全局字典、无会话绑定和 TTL；对默认本地单用户工作台影响有限，但公开或多用户部署时可能暴露搜索条件并被跨会话复用，属于部署边界风险，不能以本地测试视为已解决。
- 验证：`python -m pytest backend/tests/test_data_discovery.py -q -ra --tb=short -p no:cacheprovider`，22 项通过。无真实外网、第三方下载或多用户隔离验收。

### 2026-10-26 开放数据来源随图层与工程保留

- 复核发现与既有来源元数据待办相符的具体断点：数据下载已生成 provider/CRS/格式等 metadata sidecar，聊天摘要也显示部分信息，但 `_register_layer`、前端图层状态和工程矢量保存契约原先没有传递这些字段；用户重开工程后无法从图层检查器确认下载来源。
- **代码确认并修复：**下载结果只将 provider、类型、格式、源 CRS、CRS 已知状态和经过限制的 HTTPS 来源主页传给矢量图层；不携带查询词、本机文件路径或下载 URL。来源信息进入图层检查器，并经工程保存、恢复和后端注册快照保留。仅对带这组元数据的下载图层显示来源详情，不声称它构成通用 GIS 处理 lineage。
- 前端检查器的 HTML 转义兜底原先在 `GIS.utils` 不可用时直接返回原文；新增来源字段测试复现该安全问题后，已修复兜底转义，并验证非 HTTPS URL 不生成链接。相关来源字段通过已有 i18n 字典为英文界面提供标签。
- 验证：`python -m pytest backend/tests/test_data_discovery.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，47 项通过；`node --test frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/vector_inspector_units.test.cjs frontend/tests/project_load_race.test.cjs frontend/tests/tool_menu_i18n.test.cjs`，19 项通过；另对本次来源随工程 ZIP 导出/导入的新增断言定向运行 2 项，通过。相关 JS `node --check` 与 Python `py_compile` 通过。测试覆盖 mock Provider、共享图层状态到面板、工程保存/恢复及 ZIP 往返和 DOM 替身；未用浏览器、真实外网或真实下载数据重跑。
- 本轮开始时 `backend/services/tools.py`、`backend/services/project_service.py`、`frontend/js/chat.js`、`frontend/js/layers.js`、`frontend/js/gis_state.js`、`frontend/js/project.js`、数据发现/工程保存测试和进度文档均已有工作区改动；`frontend/tests/gis_state_fid_identity.test.cjs` 本轮开始时干净，新增了状态到面板的来源传递测试。均在原仓库状态上局部修改，未清理其他改动。

### 2026-10-26 本地文件选择上传链路复核

- 追踪 `#fileInput` 的 `change` → `handleFiles` → 预览确认 → `GIS.api.upload` → `POST /api/upload`。文件选择与拖放共用同一处理队列；API 地址使用 `gis_api_base_url` 覆盖值，否则取当前页面 origin。网络异常会标记 `UPLOAD_NETWORK_ERROR`，取消仍保留 `AbortError` 语义；未发现选择入口和拖放入口分叉或吞掉失败的代码证据。
- **结论：**浏览器里的 `Failed to fetch` 根因仍待运行确认，不据此归咎于上传实现。本轮开始时 8000/8010 无监听；上一轮本地服务启动后因浏览器控制无法可靠识别当前 URL 而停止，未选择或上传任何本地文件；当前配置的 `gis_api_base_url` 也未检查。不能声称本地浏览器文件选择验收通过。
- 验证：`python -m pytest backend/tests/test_upload_raster.py backend/tests/test_upload_vector.py backend/tests/test_upload_safety.py backend/tests/test_upload_handoff.py -q -ra --tb=short -p no:cacheprovider`，31 项通过、1 条来自刻意缺少 CRS 测试夹具的预期 pyogrio 警告；`node --test frontend/tests/upload_preview.test.cjs frontend/tests/api_provider_key_storage.test.cjs`，27 项通过。覆盖 API/处理队列自动化，不覆盖真实浏览器文件选择器。
- 本轮开始时仓库存在大量既有未提交和未跟踪改动；只读检查上传实现、运行测试并追加此记录，没有修改上传代码或清理工作区。

### 2026-10-26 GeoSource 图层容量与服务代理复核

- 追踪 GeoSource 服务检索/详情 → `loadService`/WMS/XYZ/GeoJSON 加载 → 图层面板。**代码确认并修复 P1 图层状态风险：**`_enforceMaxLayersRule` 原来检查全局面板图层数量，达到三层后自动删除最早图层，可能删掉本地上传或 AI 分析结果；同名图层也会无条件删除并覆盖。现保留三层全局上限，满额时明确提示手动移除，不自动淘汰用户图层；仅同名 GeoSource 图层允许刷新，同名其他图层会阻止本次加载并提示处理冲突。
- 新增前端回归测试验证“3 个既有工作区图层时拒绝新增但不删除”“与非 GeoSource 同名时不覆盖”“同名 GeoSource 刷新可行”。该测试基于真实处理函数和替身地图/图层状态，不是浏览器验收。
- **风险推测（部署边界，未利用）：**`/api/geosource/proxy` 只检查 URL 的 `http(s)` scheme，服务端会跟随 urllib 默认重定向并无响应体大小上限；CORS 允许任意来源。桌面启动器和文档默认绑定 loopback，本地可信单用户与公开/多用户暴露的风险不同。本轮未尝试请求内网地址或大响应，也不改会影响合法 GIS 服务访问的网络策略；公开部署前需设计目标地址、重定向、响应大小和访问控制边界。
- 将原代理端点测试对无效 URL 允许 500 的宽松断言收紧为 400，匹配路由当前参数校验契约。
- 验证：`node --test frontend/tests/geosource_layer_capacity.test.cjs frontend/tests/geosource_pagination_retry.test.cjs frontend/tests/connector_online_load.test.cjs`，11 项通过；`python -m pytest backend/tests/test_geosource.py backend/tests/layered/test_layer4_map_integration.py -q -ra --tb=short -p no:cacheprovider`，12 项通过；`node --check frontend/js/geosource.js` 通过。未访问真实第三方服务，也未进行浏览器/公开网络验收。
- 本轮开始时 GeoSource 前端代码及进度文档已有工作区修改；新增容量测试，并修改原先干净的 `backend/tests/layered/test_layer4_map_integration.py` 以收紧参数错误断言。其他既有改动保留。

### 2026-10-26 GeoSource 代理错误详情脱敏

- 继续追踪 `/api/geosource/proxy` 的网络失败路径。**代码确认并修复信息泄露：**urllib 的异常文本包含原请求 URL；该 URL 可带用户名/密码、令牌查询参数及私有路径，而 API 原先将异常原文写入 `detail` 返回前端。现 HTTP 错误只返回状态码，网络错误使用固定提示，保留 HTTP 状态语义但不回显请求字符串。
- 新增回归用例通过替身 opener 注入带哨兵凭据/令牌/路径的 HTTP 与网络异常，验证 API 响应不包含这些字段；未访问网络目标或使用真实凭据。
- 验证：`python -m pytest backend/tests/test_geosource_proxy_redaction.py backend/tests/test_geosource.py backend/tests/layered/test_layer4_map_integration.py -q -ra --tb=short -p no:cacheprovider`，14 项通过；`python -m py_compile backend/main.py` 通过。未进行真实服务或浏览器验收。
- 代理仍允许用户指定任意 HTTP(S) 目标，且当前没有重定向策略或响应大小上限；这是另一项部署边界风险，本次只修错误回显，没有改变 URL 访问能力。

### 2026-10-26 工程恢复的矢量渲染失败反馈

- 追踪工程加载响应 → 前端清理旧状态 → 逐图层恢复地图与图层面板。**代码确认并修复状态不一致：**矢量 `loadGeoJSON` 抛异常时原逻辑吞掉异常，随后仍将同一数据注册进图层面板并最终提示工程已恢复；用户可能看到不可见的“幽灵图层”。现在地图渲染明确返回 `null` 或抛错时跳过该矢量图层注册，并在工程恢复消息旁列出最多三个未显示图层及额外数量。
- 验证：`node --test frontend/tests/project_load_race.test.cjs`，11 项通过；新增用例模拟矢量地图渲染抛错，确认失败图层不进入图层注册表且用户收到部分恢复提示。`node --check frontend/js/project.js`、`git diff --check -- frontend/js/project.js frontend/tests/project_load_race.test.cjs` 通过。此处是受控前端逻辑测试，未对浏览器、真实工程文件或 Leaflet 渲染器做验收。
- 本轮开始时 `frontend/js/project.js`、`frontend/tests/project_load_race.test.cjs` 和本进度文档均已有未提交改动；在阅读既有差异后做局部兼容修改，没有覆盖或清理其他脏文件。

### 2026-10-26 AI Agent 多步执行与整轮重试边界复核

- 追踪聊天调用 → `run_agent`/`run_agent_stream` → LangGraph Agent → 工具回调/结果 → pending 图层操作与 SSE done。检查非流式网络异常重试、流式异常重试、空响应恢复以及总时限超时路径。
- **审查结论：**当前实现已在非流式调用用工具启动回调、流式调用用工具调用/结果消息判断副作用；已开始工具后不从原始输入整轮重跑，并尽量保留部分图层操作。总时限超出时，Python 工作线程不能被强杀，代码保持会话/共享状态锁直到后台调用退出，并明确提示用户不要立即重复提交、先检查图层和输出。此为明确的运行时限制，不据此宣称调用已取消或后台工作必然完成；本轮未发现新的可证实高优先级缺陷，未修改 Agent 执行代码。
- 验证：`python -m pytest backend/tests/test_agent_retry_safety.py backend/tests/test_stream_step_events.py -q -ra --tb=short -p no:cacheprovider`，23 项通过；覆盖工具启动前后重试边界、部分图层操作保留、流式工具完成后断连不重放和超时期间锁保持。均为 mock/本地测试，不包含真实模型供应商、真实 GIS 外部写入或浏览器 SSE 验收。
- 本轮开始时 `backend/services/graph.py`、`backend/services/ai_service.py`、`backend/tests/test_stream_step_events.py` 已有未提交修改，`backend/tests/test_agent_retry_safety.py` 已是未跟踪文件；本轮只读检查这些代码并追加本进度记录，未改动 Agent 代码，也未清理工作区。

### 2026-10-26 前端 SSE 失败状态与防止重复请求复核

- 追踪前端请求 `/api/chat/stream` → SSE 解析 → execution cards/任务状态 → 断流回退。曾检查 `done.execution_status="error"` 是否被误显示为成功；对照当前后端发现所有设置 `error` 状态的分支都会先发 `type="error"` 事件，前端在读取 `done` 前抛出并进入失败处理，因此该候选问题在当前协议链路下不可达，撤销了未验证的状态映射改动，没有把它记作缺陷。
- **代码确认并加固回归覆盖：**SSE 已出现 `tool_start` 后遇到 `error` 时，前端把任务标为失败、步骤标为中断，并禁止回退到普通 `/api/chat` 再执行一次请求，避免重复 GIS 副作用。本轮新增用例覆盖这一契约，没有修改聊天运行逻辑。
- 验证：`node --test frontend/tests/chat_send_lifecycle.test.cjs frontend/tests/execution_cards.test.cjs`，33 项通过；`node --check frontend/js/chat.js` 和相关 `git diff --check` 通过。测试是本地前端逻辑测试，不代表真实 FastAPI SSE、浏览器网络中断或模型服务验收。
- 本轮开始时 `frontend/js/chat.js`、`frontend/tests/chat_send_lifecycle.test.cjs` 和进度文档已有未提交改动；最终仅在既有测试文件增加一项回归测试，并追加此记录，聊天源文件保留原状，其他工作区内容均未清理。

### 2026-10-26 AI 结果图层恢复与地图操作目标匹配

- 追踪 Agent 结果 `layers`/`layer_ops` → 前端面板查找 → `/api/layers` 后端注册快照补挂 → 地图操作执行。后端 `/api/layers` 按注册名返回图层；前端实际执行具名操作也按精确名称定位，但补挂时原先用前缀/子串匹配。**代码确认并修复 P1 状态错配：**操作目标 `roads` 在工作区/注册表不存在、只有 `roads_buffer` 时，模糊补挂可能把错误图层加入工作区，目标操作仍会因后续精确查找而落空；恢复失败原先只写控制台。
- 现补挂只恢复工具明确引用的目标类操作，工作区与后端注册表均按精确图层名匹配；HTTP 非成功也视为恢复失败。无法恢复时向用户显示经过 HTML 转义的提示，说明相关地图操作可能未应用。保留现有图层和操作行为，不改 API。
- 新增前端回归测试，构造已有 `roads_buffer` 图层、后端也只返回 `roads_buffer`，验证不会重复挂错图层、不会误对其改色，并能看到恢复提示。验证：`node --test frontend/tests/chat_send_lifecycle.test.cjs frontend/tests/execution_cards.test.cjs`，34 项通过；`node --check frontend/js/chat.js` 与针对文件的 `git diff --check` 通过。使用测试替身，不代表真实后端/浏览器验收。
- 本轮开始时 `frontend/js/chat.js`、`frontend/tests/chat_send_lifecycle.test.cjs` 和进度文档均已有未提交改动；阅读相关当前逻辑后局部改动既有源文件与测试文件，并追加本记录，未清理其他修改。

### 2026-10-26 AI 颜色/样式地图应用失败反馈

- 追踪 `layer_ops` 的 `set_color`/`set_style` → 地图渲染层查找 → 图层面板状态。**代码确认并修复 P1 状态不一致：**地图 setter 找不到可渲染图层时原先直接返回 `undefined`；聊天仍会把颜色写入图层面板，或静默跳过样式操作，用户可能看到工具文字成功但地图未变化。
- 地图颜色/样式 setter 现返回是否实际找到可更新的地图对象；AI 颜色操作仅在地图更新成功后更新面板色值，样式/颜色操作失败时显示提示。既有调用者不依赖返回值，API 参数和格式不变。
- 验证：`node --test frontend/tests/chat_send_lifecycle.test.cjs frontend/tests/execution_cards.test.cjs frontend/tests/map_layer_visibility.test.cjs`，43 项通过；新增覆盖 map setter 对缺失/不可样式图层返回失败、聊天不误更新面板并给出提示。`node --check` 检查 chat.js/map.js 通过，`git diff --check` 通过。受控前端测试，不代表真实 Leaflet 浏览器渲染验收。
- 本轮开始时 `frontend/js/chat.js`、`frontend/js/map.js`、对应两份前端测试和进度文档均已有未提交改动；在理解原实现后局部修改这些脏文件，未清理或覆盖其他工作区更改。

### 2026-10-26 专题符号化渲染结果确认

- 追踪 AI 的 `symbology` 图层操作 → `_applyGraduatedFromAI`/`_applyUniqueFromAI` → `_applyStyleToMap` → `GIS.map.applySymbology`。**代码确认并修复 P1 错报成功：**底图渲染方法在地图或目标图层不存在时原先提前 `return`（即 `undefined`），上层 `_applyStyleToMap` 无条件继续标记成功并保存要素符号状态；结果可能只在图层状态中存在、地图实际没有专题样式。空要素图层路径也会静默返回。
- 地图 `applySymbology` 现在对缺失 map/layer 返回 `false`、完成替换后返回 `true`；上层只在地图确认成功后记录成功样式元数据，渲染器不可用时向用户提示。AI 分级/唯一值符号化对空要素返回失败并解释原因，既有字段错误提示保留。
- 验证：`node --test frontend/tests/layer_symbology_persistence.test.cjs frontend/tests/map_layer_visibility.test.cjs frontend/tests/project_load_race.test.cjs`，36 项通过；新增覆盖 map 层是否实际接受样式、失败时不保存成功符号状态且显示提示。`node --check`（layers.js/map.js）和 `git diff --check` 通过。使用 mock 地图对象及本地测试，未作真实 Leaflet 浏览器渲染验收。
- 本轮开始时 `frontend/js/layers.js`、`frontend/js/map.js`、上述相关测试和进度文档均已有未提交改动；仅在这些脏文件中做局部兼容修改，保留其他工作区内容。

### 2026-10-26 标签与图例结果反馈复核

- 追踪 AI 图层操作 `addLabels`/`addLegend` → 图层注册表查找 → 地图 `setLabels`/浮动图例渲染。**代码确认并修复两类结果状态问题：**地图原先无论字段是否存在、是否绑定任何 tooltip，均保存标注配置且不返回状态；图层操作层也忽略地图结果，失败时不给用户反馈。现在地图只在至少一个非空字段值成功绑定后确认标注成功，缺字段/空字段/地图图层缺失返回失败；失败字段不覆盖上一次有效配置，数值 `0` 可作为有效标签，更新字段时空值要素会解除旧 tooltip。图层入口报告失败并提示核验字段。
- **代码确认并修复具名图例错配：**请求不存在图层时原先可能重显 `_lastLegendData`，造成用户要求的图层与地图显示图例不一致。具名查找失败现在明确提示且不绘制旧图例；内部 `_showLegend` 仅在未指定图层时才使用首个图层回退。图例没有可用 DOM 面板时不再记作已展示或发送成功消息。
- 验证：`node --test frontend/tests/map_layer_visibility.test.cjs frontend/tests/layer_symbology_persistence.test.cjs frontend/tests/project_load_race.test.cjs`，39 项通过（含新增标签渲染、失败配置保留、图例目标匹配与不重显旧图例测试）。`node --check` 检查 map/layers 和两份测试文件通过；`git diff --check` 通过，仅有工作区行尾规范提示。地图 Leaflet 由测试替身模拟，图例使用 DOM 替身；未做浏览器视觉或真实项目数据验收。
- 本轮开始时 `frontend/js/map.js`、`frontend/js/layers.js`、两份测试文件和本进度文档均已存在工作区修改；阅读相关实现后在既有脏文件上局部兼容修改，未清理或覆盖无关改动。

### 2026-10-26 本地矢量上传来源 CRS 交付

- 重新核对矢量元数据待办：上传入口会将带声明 CRS 的 GeoJSON、Shapefile ZIP、GeoPackage 等重投影为 EPSG:4326，但返回值和注册快照此前没有保留转换前 CRS；结果检查器只能显示当前标准化坐标系，用户无法从图层中辨认来源 CRS。本轮范围限定于本地矢量文件上传，不扩展为所有分析工具的通用 lineage 契约。
- **代码确认并修复：**`/api/upload` 对 GeoJSON、Shapefile ZIP、GeoPackage/KML/KMZ/GPX/DXF、PMTiles 矢量、GeoParquet 和 FlatGeobuf 生成受限 provenance（来源类别、文件格式、转换前 CRS/可信标记）；GeoJSON 未声明 CRS 时依照 RFC 7946 标为 EPSG:4326。没有保存本机路径或来源 URL。后端注册快照和上传响应共用该元数据，前端传入现有图层状态/工程持久化链；检查器按当前中英文界面显示“本地文件/矢量文件上传”。
- 验证：`python -m pytest backend/tests/test_upload_vector.py backend/tests/test_upload_handoff.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，42 项通过、1 条来自故意缺失 CRS 的 Shapefile 测试夹具警告；新增断言核对 EPSG:3857 原始 CRS、格式、可信标记和不含路径/URL。`node --test frontend/tests/upload_preview.test.cjs frontend/tests/vector_inspector_units.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/project_load_race.test.cjs`，31 项通过，覆盖上传响应传递、检查器中英文文案和已有工程状态元数据路径。`py_compile`、相关 `node --check`、`git diff --check` 通过。没有重跑浏览器或真实用户文件；原有真实 DEM 浏览器闭环记录见本文件第 94 节，但当前服务未运行。
- 仍未解决：AI 生成的矢量分析结果尚无跨工具统一的来源图层、工具/参数、距离单位等 lineage 元数据；本轮只补本地上传入口，避免扩展或改变项目数据契约。`/api/upload` 与所改前端/测试及进度文档在本轮开始时均已有工作区修改或未跟踪；在当前内容上局部修改，未覆盖、清理或提交其他更改。

### 2026-10-26 缓冲结果处理来源展示

- 追踪 `spatial_buffer` → `_layer_to_gdf` → 修复几何/距离单位归一 → 局部 UTM 缓冲 → EPSG:4326 输出 → `_gdf_to_layer` → 待发送层和 Agent 注册表。计算使用米制投影，结果转回 EPSG:4326；现有工具回复说明输入图层、用户距离和单位，但图层检查器/工程只保留粗粒度 `source=ai`，用户重开后无法从结果图层确认输入来源和参数。
- **代码确认并修复 P2 结果可解释性缺口：**`_gdf_to_layer` 增加可选 provenance 参数，原有调用保持默认行为；缓冲工具提供经白名单校验的处理记录（工具、源图层、距离、m/km、是否融合），同时传入前端待推层和 Agent 注册快照。已有工程字段可直接保留该可选对象，不新增顶层工程格式。图层检查器展示中英文“处理记录”，对图层名做 HTML 转义；无效或超大参数不会被持久化。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialBuffer backend/tests/test_spatial_tools.py::test_provenance_processing_drops_malformed_buffer_parameters_without_raising backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，37 项通过；覆盖缓冲产物和注册快照携带处理记录、畸形参数被丢弃、既有工程 provenance 往返保留。`node --test frontend/tests/vector_inspector_units.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/project_load_race.test.cjs`，20 项通过，检查器中英文显示、HTML 转义和工程恢复状态通路。`py_compile`、相关 `node --check`、`git diff --check` 通过。无浏览器视觉验收、真实 AI 模型调用或真实用户工程验收。
- 范围限制：只记录 `spatial_buffer`，没有声称其他空间分析工具已统一提供 lineage；地理质量警告继续沿既有聊天 `qa_warnings` 通道展示，不复制进该处理记录。所有本轮触及的工具代码、前端/测试和进度文档在开始时均已处于既有脏状态或未跟踪状态；基于原内容局部修改，没有清理或提交。

### 2026-10-26 矢量裁剪结果输入来源展示

- 追踪 `spatial_clip(layer_name, clip_layer)` → 注册表读取（GeoJSON 按工作区约定作为 EPSG:4326）→ 双输入几何修复 → GeoPandas `clip`/分块 overlay → `_gdf_to_layer` → 待发送层及 Agent 注册表。**未发现新的计算正确性缺陷**：空输入、无交集、几何修复、分块处理均有明确分支；分析结果返回要素数/面积和质量处理摘要。此前裁剪产物没有持久化被裁剪图层和边界图层，用户只能从聊天历史推测结果来源。
- **代码确认并修复 P2 可解释性缺口：**裁剪结果现在复用 provenance 记录两个输入图层名；白名单归一化只接收 `spatial_clip` 两个非空字符串并限制长度。现有工程 provenance 字段保存/恢复该记录，图层检查器中英文显示“输入图层”和“裁剪边界图层”，并转义动态名称。没有改动裁剪算法、工具参数或工程顶层格式。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialClip backend/tests/test_spatial_tools.py::test_provenance_processing_drops_malformed_buffer_parameters_without_raising backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，28 项通过；含产物、待发送层/注册快照处理记录，缺失边界输入被丢弃以及工程 provenance 往返。`node --test frontend/tests/vector_inspector_units.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/project_load_race.test.cjs`，21 项通过，覆盖处理中英文显示、HTML 转义、共享图层状态与工程恢复。`py_compile`、相关 `node --check` 和 `git diff --check` 通过。无真实浏览器或真实 AI 模型验收。
- 本轮开始时工具源文件、空间分析与工程测试、前端图层代码、i18n 及检查器测试、进度文档均已是工作区修改或未跟踪状态；本轮基于现有内容局部增加裁剪处理记录与测试，无清理、覆盖或提交。

### 2026-10-26 矢量 Union 结果输入来源展示

- 追踪 `spatial_union(layer_a, layer_b)` → 两个注册图层读取与几何修复 → GeoPandas `overlay(how="union")` → `_gdf_to_layer` → 待发送层和 Agent 注册表。输入不存在/无有效几何会提前返回；叠置异常返回失败说明，失败分支未注册产物。本轮未发现新的可证实几何或异常状态缺陷。此前成功产物仅以组合图层名表达结果，没有记录输入图层的独立关系。
- **代码确认并修复 P2 来源可追溯缺口：**union 产物增加规范化的两个输入图层名，后端 provenance 白名单只接受非空、限长的字符串；现有工程持久化保留记录。图层检查器以中英文显示操作和两个输入名，并转义动态内容。没有改变叠置计算、输出名称或项目顶层 schema。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialUnion backend/tests/test_spatial_tools.py::TestSpatialClip backend/tests/test_spatial_tools.py::test_provenance_processing_drops_malformed_buffer_parameters_without_raising backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，29 项通过；`node --test frontend/tests/vector_inspector_units.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/project_load_race.test.cjs`，22 项通过。覆盖实际 union 产物元数据、畸形/缺失双输入拒绝、检查器双语和转义、工程 provenance 往返。Python/JavaScript 语法及 `git diff --check` 通过；没有浏览器、真实模型或真实项目演练。
- 本轮开始时 backend 工具/测试、前端图层代码、i18n/检查器测试和进度文档均已有工作区修改或未跟踪状态；局部修改原有脏文件，未清理、覆盖或提交其他改动。

### 2026-10-26 矢量 Intersection 结果输入来源展示

- 追踪 `spatial_intersect(layer_a, layer_b)` → 双图层注册表读取/几何修复 → GeoPandas `overlay(intersection)` 或分块 overlay → 空结果判断 → `_gdf_to_layer` → 待发送层/注册表。空交集返回明确提示且在当前实现中先于结果注册；现补回归断言锁定这一失败契约。成功响应包含相交要素数、去重覆盖面积/占比及几何修复摘要。本轮未发现新的计算或错误反馈缺陷。
- **代码确认并修复 P2 结果来源缺口：**交集结果现在保存两张输入图层名；provenance 归一化限制为 `spatial_intersect` 的两个非空、限长字符串。图层检查器按中英文展示操作和输入图层名，并对动态值 HTML 转义。既有工程 provenance 保存/恢复字段承载记录，无新增项目顶层格式或计算变化。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialIntersect backend/tests/test_spatial_tools.py::TestSpatialUnion backend/tests/test_spatial_tools.py::TestSpatialClip backend/tests/test_spatial_tools.py::test_provenance_processing_drops_malformed_buffer_parameters_without_raising backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，32 项通过；含相交覆盖面积、多输入 provenance、无重叠不注册图层、畸形输入记录拒绝及工程 metadata 往返。`node --test frontend/tests/vector_inspector_units.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/project_load_race.test.cjs`，23 项通过；覆盖中英文操作说明、HTML 转义和工程图层状态通路。语法检查及 `git diff --check` 通过。无真实浏览器、AI 模型或用户工程验收。
- 本轮开始时工具代码、空间/工程测试、前端图层代码、i18n、检查器测试和进度文档均处于既有修改或未跟踪状态；在原有工作区内容上局部修改，没有清理、覆盖或提交。

### 2026-10-26 矢量 Difference 结果输入来源展示

- 追踪 `spatial_difference(layer_a, layer_b)` → 双图层注册表读取/几何修复 → GeoPandas `overlay(difference)` 或分块 overlay → 空结果判断 → `_gdf_to_layer` → 待发送层/注册表。代码路径显示空结果在图层注册前返回“完全被覆盖”，新增回归覆盖该行为；当前测试样本未发现差异计算/错误状态缺陷。
- **代码确认并修复 P2 来源可追溯缺口：**此前差异结果已进入图层，但没有记录两个输入图层，与相交/联合结果的交付信息不一致。现在结果及注册快照携带受限的 `spatial_difference` 双输入记录；现有图层检查器以中英文展示操作和另一输入图层名，动态名称经过 HTML 转义。未改变算法、工具参数或工程顶层格式。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，141 项通过、1 条环境 CPU 核数探测警告；包含差异结果来源、空差异不注册、provenance 校验及工程 metadata 往返。`node --test frontend/tests/vector_inspector_units.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/project_load_race.test.cjs`，24 项通过；覆盖检查器双语、动态值转义和工程恢复通路。`py_compile`、相关 `node --check`、`git diff --check` 通过。没有真实浏览器、AI 模型或真实用户工程验收。
- 本轮开始时 backend 工具/空间与工程测试、前端图层代码/i18n/检查器测试及进度文档均已有工作区修改或未跟踪状态；在现有内容上局部修改，未清理或提交其他改动。

### 2026-10-26 属性分组融合空值要素丢失

- 追踪 `spatial_dissolve(layer_name, group_by)` → `_layer_to_gdf` → `GeoDataFrame.dissolve` → `_gdf_to_layer`。**已复现 P1 数据完整性缺陷：**有分组字段空值的要素被 GeoPandas 默认 `dropna=True` 排除，工具仍返回成功。新增包含一条 `zone=north` 与一条缺少 `zone` 的面要素用例，修复前结果要素数为 1，输入的空值分组要素静默丢失。
- **最小修复：**分组 dissolve 显式传入 `dropna=False`，将空值作为一组保留；不改工具接口、聚合逻辑或输出格式。验证结果同时检查两组均存在且缺失分组字段仍为 null。
- 验证：修复前新增回归测试失败（1 个要素而非 2），确认了实际缺陷；修复后 `python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，142 项通过、1 条 Joblib CPU 核数探测环境警告。`py_compile` 与 `git diff --check` 通过。没有真实浏览器或大规模数据性能验证；`dropna=False` 依赖项目声明的 `geopandas>=1.0.0`，当前环境为 1.1.3。
- `backend/services/tools.py`、`backend/tests/test_spatial_tools.py` 和进度文档在本轮开始前均已被修改；基于现有内容增加局部修复/回归记录，未覆盖或清理其他改动。

### 2026-10-26 按空间关系选择复核

- 追踪 `spatial_select` → 两个图层 `_layer_to_gdf` → GeoPandas `sjoin` → 删除右侧属性/索引 → 去重 → `_gdf_to_layer`。当前测试样本与额外构造的“两个相同点要素命中同一面”用例均保留 2/2 个目标要素；该场景未证实 `drop_duplicates()` 会丢失目标记录，因此没有据此改生产逻辑。
- 新增一个重复几何选择回归用例，锁定测试数据中两个目标要素都出现在结果中。尝试断言输入 GeoJSON 的字符串 feature ID 会原样保留时测试显示输出 ID 为 `0`/`1`；本轮不把它归因于选择去重逻辑或扩展为所有矢量工具的 ID 契约，需在图层注册/GeoDataFrame 转换模块另行追踪后再判断。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialSelect -q -ra --tb=short -p no:cacheprovider`，2 项通过。仅为模块局部确定性用例，不代表所有 predicate、几何类型、数据规模或真实工程均已验证。
- 测试文件及进度文档在本轮开始前已存在未提交修改；仅追加用例与记录，未清理或覆盖其他改动。

### 2026-10-26 空间连接模块复核

- 追踪 `spatial_join` → 两个输入图层读取 → `geopandas.sjoin(how, predicate)` → 结果图层注册。`nearest` 被明确拒绝并指引 `nearest_pair`；其余无效参数由 GeoPandas 异常分支转成“空间连接失败”，未看到异常分支会注册半成品。现有测试覆盖相交连接与 nearest 拒绝路径。
- 本轮未确认新的缺陷，因此没有改生产逻辑。当前测试仍不足以证明所有空间 predicate、左右/内连接语义、字段重名和一对多匹配组合均正确；这些属于后续边界验证，不将未运行场景写成已通过。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialJoin -q -ra --tb=short -p no:cacheprovider`，2 项通过。未使用浏览器或外部数据。

### 2026-10-26 本地文件上传浏览器复验

- 重新启动本地 FastAPI（`127.0.0.1:8000`），通过 Codex 内置浏览器走 `Layers → Upload → 文件选择 → 预览 → Upload`。选择仓库 fixture `frontend/samples/demo-polygons.json`；预览显示 3 个 Polygon 要素及 `name`、`group`、`score` 字段。确认上传后，图层面板实际显示 `demo-polygons_2.json`、3 features，页面提示 `Upload complete`。
- **结论：**此次浏览器运行未复现历史 `Failed to fetch`，也未发现本次小型 GeoJSON 上传故障；此前失败原因仍不明，不能据单次成功推断所有端口配置、用户网络、文件格式或大型文件均可靠。此次使用的是仓库样例，不是用户私人文件；未保存工程或覆盖既有工程。
- 浏览器实际流程证明了当前本地工作台环境下的文件选择、预览和小型 GeoJSON 上传。不是 Shapefile/GeoPackage/栅格格式或大文件的兼容性验收，也未复跑真实 DEM；本轮结束后已停止本轮启动的本地服务。

### 2026-10-26 属性选择 like 字面匹配

 - 追踪 `spatial_select_by_attribute` 的 `like` 分支。**已复现 P2 查询正确性缺陷：**产品文案定义为不区分大小写的“包含”，实现却使用 Pandas 默认 `regex=True`；输入单独的 `[` 会返回正则解析错误，而不是查找字面字符。修复前回归测试失败，错误为 `Invalid regular expression: missing ]`。
 - **最小修复：**`str.contains(..., regex=False)` 明确按字面子串匹配，不改参数、查询字段和结果图层格式。另加空字段值近似用例，验证转字符串不会把缺失值误匹配成字面 `"none"`；该用例在当前 GeoPandas/Pandas 环境下通过，没有证实额外缺陷。
 - 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSelectByAttribute -q -ra --tb=short -p no:cacheprovider`，4 项通过（含数字比较、字面正则元字符、空字段值检查）；收尾回归 `python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，145 项通过，1 条 Joblib 无法探测物理 CPU 数量的环境警告。此前修复 regex 前，字面 `[` 用例复现为正则解析错误。
- 追踪 `spatial_select_by_attribute` 的 `like` 分支。**已复现 P2 查询正确性缺陷：**产品文案定义为不区分大小写的“包含”，实现却使用 Pandas 默认 `regex=True`；输入单独的 `[` 会返回正则解析错误，而不是查找字面字符。修复前回归测试失败，错误为 `Invalid regular expression: missing ]`。
- **最小修复：**`str.contains(..., regex=False)` 明确按字面子串匹配，不改参数、查询字段和结果图层格式。另加空字段值近似用例，验证转字符串不会把缺失值误匹配成字面 `"none"`；该用例在当前 GeoPandas/Pandas 环境下通过，没有证实额外缺陷。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSelectByAttribute -q -ra --tb=short -p no:cacheprovider`，4 项通过（含数字比较、字面正则元字符、空字段值检查）；收尾回归 `python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，145 项通过，1 条 Joblib 无法探测物理 CPU 数量的环境警告。此前修复 regex 前，字面 `[` 用例复现为正则解析错误。

### 2026-10-26 AI 输出附件识别与下载反馈

- 追踪 `export_layer` 结果路径 → `chat.addMessage` → `_attachOutputButtons` → `downloadFile` → `/output/{filename}`。服务端路径路由有目录边界检查并支持下载响应；聊天下载函数此前不检查 HTTP 状态，404 错误体会被当作文件保存，而且点击后立即撤销 Blob URL。另查明工具侧会产生/处理 SVG、WebP 图像产物，但聊天路径正则未列入这两种扩展名。
- **复现并最小修复：**新增测试在修复前分别复现“HTTP 404 被当作下载”与“Blob URL 没有延后撤销”两项行为；SVG/WebP 附件识别测试也在修复前失败。现在失败响应会在聊天中提示下载失败，不生成错误文件；下载后 1 秒撤销 Blob URL，与工程导出已有做法一致；附件识别正则补入 SVG/WebP。未改变后端导出格式或 HTTP API。
- 验证：`node --test frontend/tests/chat_send_lifecycle.test.cjs frontend/tests/project_load_race.test.cjs frontend/tests/execution_cards.test.cjs`，49 项通过；`node --check`（chat.js 与相关测试）和 `git diff --check` 通过。测试为本地 JS 行为替身；没有真实模型生成的聊天附件或浏览器点击下载验收。

- **后续复核：**将聊天路径识别与后端产物类型交叉检查，测试先复现 GIF 路径未生成附件卡片；同时发现 PDF、XLS/XLSX、MD、TXT 也缺少路径识别。现已补齐这些扩展名，并将 GIF 归入图片预览。回归测试覆盖 SVG/WebP/GIF/PDF/XLS/XLSX/MD/TXT 八种附件路径；聊天相关三组测试共 49 项通过，`node --check` 和目标文件 `git diff --check` 通过。仍未在浏览器里点击真实聊天生成的这些文件验证下载或预览。


### 2026-10-26 空间连接多匹配与字段冲突复核

- 补充检查 `_layer_to_gdf` → `geopandas.sjoin` → `_gdf_to_layer` 的边界：受控左连接样本包含 2 个重叠字段（`id`、`name`）、同一目标命中 2 个连接要素，以及 1 个未命中目标。运行结果为 3 行；GeoPandas 以 `_left`/`_right` 保留同名属性，一对多匹配产生两行，未命中目标保留且右侧属性为空。
- 结合已有 `intersects` 和 `nearest` 拒绝测试，本轮未确认空间连接功能缺陷；没有改生产代码。此结论限于本地小型 EPSG:4326 几何样本，不覆盖全部 predicate、how、CRS 组合或大型数据性能。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialJoin -q -ra --tb=short -p no:cacheprovider`，2 项通过；边界样本以直接调用工具的本地受控脚本检查，没有替代回归测试或真实用户工程验收。


### 2026-10-26 图层合并输出名称冲突

- 追踪前端空间面板/AI 工具 → `layer_merge` → `_layer_to_gdf` → GeoPandas 行拼接 → `_gdf_to_layer` → 待发送层及后端注册表。**已复现 P1 状态/数据覆盖缺陷：**连续合并相同输入会重复使用默认结果名并覆盖后端注册表的前次结果；显式将输出名设为输入图层 `A` 时，合并输出会替换 Agent 注册表中的 `A`，用户当前界面仍可能保留原 `A`。前端共享图层状态遇同名会加后缀，这加剧了后端名称与前端层记录不一致的风险。
- 修复前新增两个回归测试均失败：重复调用没有登记第二个独立结果；`new_name=A` 后注册表 `A` 的要素数从 1 变成合并后的 2。
- **最小修复：**合并结果名与已注册或待发送图层冲突时自动选取 `_1`、`_2` 等可用后缀，避免覆盖输入或历史结果；工具回复现在包含实际结果图层名。没有更改合并算法、输入数据或工程格式。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，147 项通过；包含修复前两项失败及修复后通过。`python -m py_compile backend/services/tools.py` 和目标文件 `git diff --check` 通过。测试为本地受控 GeoJSON；未完成 AI 真实模型多步任务或浏览器连续合并验收。1 条 Joblib CPU 核数探测警告来自当前 Windows 测试环境，不影响通过结果。


### 2026-10-26 按字段拆分保留空值组

- 追踪 `layer_split` → `_layer_to_gdf` → `GeoDataFrame.groupby(by_field)` → 每组 `_gdf_to_layer`。**已复现 P1 要素静默丢失：**按字段分组使用 Pandas 默认 `dropna=True`，带空分组值的输入要素不会进入任何输出子图层；消息仍报告原输入总要素数，容易让用户误以为拆分完整。
- 修复前新增两要素用例失败：字段 `zone` 一条为 `north`、另一条缺失时，工具仅生成 1 个子图层，未保留缺失值要素。
- **最小修复：**分组拆分显式使用 `dropna=False`，空值作为一个独立子图层保留；不改工具参数、几何或属性内容。
- 验证：`python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，148 项通过；修复前空值回归失败，修复后通过。`python -m py_compile backend/services/tools.py` 与目标文件 `git diff --check` 通过。使用本地受控 GeoJSON，没有真实浏览器或大规模数据性能验收；1 条 Joblib CPU 核数探测警告是当前 Windows 测试环境信息。


### 2026-10-26 属性坐标转点有效性校验

- 追踪 `layer_add_geometry` → 字段自动识别/选择 → 数值转换 → EPSG:4326 点构造 → `_gdf_to_layer` 注册与地图返回。**已复现 P1 空间数据正确性问题：**经度 180.1 或纬度 90.1 均被接受，工具返回成功并登记为 EPSG:4326 点；这会生成超出经纬度有效范围的坐标，后续空间分析和地图定位不可靠。
- 同时检查空值、非数值和 NaN 输入。此前函数在转换时会抛出底层异常或让非有限坐标继续进入几何；错误未统一说明。
- **最小修复：**先将两字段解析为数值，再拒绝空值、非数值、非有限值及经纬度越界数据；通过校验后才创建几何和注册结果，错误文案指明字段数值或有效范围。接受边界值 -180/180 经度、-90/90 纬度。
- 回归覆盖越界经度、越界纬度、NaN、空值、非数值、合法边界点，并断言失败时不增加待发送或注册图层。验证：`python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，154 项通过；`python -m py_compile backend/services/tools.py` 和目标文件 `git diff --check` 通过。此前测试一次初跑发现测试进程的注册表会跨用例保留旧图层；测试已改为比较调用前后的注册表快照，不把旧状态误判成本次部分注册。使用本地受控 GeoJSON，未进行浏览器或真实用户数据验收；1 条 Joblib CPU 核数探测警告不影响通过。


### 2026-10-26 面边界线几何转换输入类型校验

- 追踪前端几何转换面板「面→边界线」→ `geometry_convert(target_type="lines")` → GeoPandas geometry boundary → `_gdf_to_layer`。**已复现 P1 类型错误：**线输入会对线取边界，生成 MultiPoint 端点，却报告边界线转换成功；空几何也未在工具入口说明。界面和工具契约都把该操作定义为面转边界线。
- 修复前新增 LineString 反例测试失败：工具成功登记 `line_layer_lines`，输出不是边界线。
- **最小修复：**`lines` 仅接受 Polygon/MultiPolygon，遇到空/空值几何或其他几何类型时返回可理解错误，并在输出注册前终止；没有改变多边形边界算法。
- 验证：`python -m pytest backend/tests/test_new_tools.py -k geometry_convert -q -ra --tb=short -p no:cacheprovider`，6 项通过、11 项未选；覆盖面边界线、非面输入拒绝、空几何拒绝、外接矩形、凸包和未知类型。`test_new_tool_outputs_pass_geo_qa` 另 1 项通过；`py_compile` 与目标文件 `git diff --check` 通过。未做浏览器/真实 AI 模型验收。

- **完整文件回归补充：**`python -m pytest backend/tests/test_new_tools.py -q -ra --tb=short -p no:cacheprovider`，17 项通过（含上述几何转换测试及该文件其余新工具契约）。

- **几何转换续查：**复现重复执行相同几何转换时，后端继续覆盖固定输出名，而前端共享图层状态会对同名结果加后缀。现为 `geometry_convert` 输出选择不与注册表/待发送结果冲突的后缀名，响应返回实际名称；新增回归确认连续转换分别登记 `repeat_polygon_lines` 与 `_1`。适配 GeoQA 测试以接受实际后缀；原因是测试环境的已注册图层跨用例保留，这不是生产行为回归。
- 验证更新：`python -m pytest backend/tests/test_new_tools.py -q -ra --tb=short -p no:cacheprovider`，18 项通过；`python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_layer_group_persistence.py -q -ra --tb=short -p no:cacheprovider`，154 项通过、1 条环境 CPU 探测警告。工具语法与目标文件 `git diff --check` 通过。真实浏览器和 AI 模型多步结果同步仍未验收。


### 2026-10-26 几何转换退化范围与属性提示

- 续查 `geometry_convert` 的 `polygons`、`convex_hull` 与 `bounding_box` 分支。受控闭合环运行确认 `polygonize` 产生新面但不继承源线 `zone` 属性；多条线可共同构面时属性映射无通用且无歧义的规则，本轮不伪造属性对应关系。现在工具回复明确提示：线转面输出不继承源线属性；凸包与外接范围的聚合输出同样说明源要素属性未继承。
- **已复现 P1 无效外接几何：**单点、垂直共线点、水平共线点都曾生成零面积 Polygon（单点样本坐标环四点全重合）。现按范围退化维度返回 Point、LineString 或普通 Polygon；无有效几何/非有限范围不生成结果并返回错误。
- 新增回归：单点范围→Point、垂直/水平范围→LineString、无有效几何拒绝、线转面属性未继承提示；与既有普通 bbox、凸包、面边界、输入类型和重复输出名测试共同验证。
- 验证：`python -m pytest backend/tests/test_new_tools.py -q -ra --tb=short -p no:cacheprovider`，23 项通过；`python -m py_compile backend/services/tools.py` 和目标文件 `git diff --check` 通过。使用受控 GeoJSON；没有浏览器或真实 AI 多步验收。凸包面对空值/混合无效几何的行为尚未单独覆盖。


### 2026-10-26 网络分析设施遗漏与 OD 索引对齐

- 追踪 `network_analysis` → 坐标解析/图层 bbox 校验 → `network_service.closest_facilities`/`service_area`，以及 `od_cost_matrix` → 点代表位置 → 路网吸附 → Dijkstra → CSV/JSON 文件产物。
- **已复现 P1 最近设施部分结果遗漏：**路网以外或有向路网不可达的设施会被服务层跳过；工具只返回成功设施，没有说明跳过项。现在服务结果返回未吸附和不可达的输入序号，工具以 1 开始的输入序号报告未纳入结果的设施。
- **已复现 P2 坐标错误反馈及 traceback 暴露：**`events` 坐标未进入统一解析/bbox 校验，非法值进入异常分支并向工具调用方返回完整 traceback。现在最近设施事件坐标在开始计算前统一校验并参与图层范围检查；异常回复保留截断错误摘要，不再附带堆栈。修复前两个工具级回归均失败。
- **已复现 P1 OD 矩阵位置错配：**OD 的吸附函数在吸附失败时仍提供“最近节点坐标”供诊断，但会同时返回 `found=false`；原调用只检查坐标非空，导致远距离点被误当作已吸附。进一步地，已吸附子集压缩矩阵行列，CSV 索引不能追溯原始图层要素。现在按 `found` 判定，将未吸附位置保留为 null 成本单元，矩阵维度与输入点顺序一致；JSON 摘要保存原始计数、已吸附计数和零基未吸附索引，工具文本显示一基输入序号。
- 验证：`python -m pytest backend/tests/test_network.py -q -ra --tb=short -p no:cacheprovider`，14 项通过；`python -m pytest backend/tests/test_stats_gap_tools.py::TestOdCostMatrix -q -ra --tb=short -p no:cacheprovider`，4 项通过；`python -m pytest backend/tests/test_integration_e2e_v4.py::TestNetworkAnalysisE2E -q -ra --tb=short -p no:cacheprovider`，6 项通过。另有 `py_compile` 和目标文件 `git diff --check` 通过。所有路网均为受控本地 GeoJSON；未调用 OSM、外部服务或真实模型，未做浏览器验收。服务区边界仍是代码明确说明的节点凸包加经纬度缓冲近似，不代表逐道路可达区。


### 2026-10-26 OSM 路网下载输入校验与失败反馈

- 追踪 `download_road_network` → OSMnx 地名/BBox 路网请求 → `graph_to_gdfs` → GeoJSON 边集 → `_push_layer` / `_register_layer` → `network_analysis`。
- **已复现 P2 请求前校验缺口：**四段 BBox 输入此前没有检查数值是否有限、经纬度边界或最小/最大顺序；任意 `network_type` 也会发给 OSMnx。假 OSMnx 记录器确认三个无效样本都触发了外部请求函数。现在仅接受文档列出的 `drive/walk/bike/all`，并在请求前校验 BBox 值、范围和顺序。
- **已复现 P2 错误细节暴露：**OSMnx 失败会返回 traceback（含本地源文件路径）。现在向工具调用方返回截断错误摘要，不附堆栈；成功和非超时失败路径会关闭线程池。原有 120 秒超时仍使用非等待式 shutdown，因为 Python Future 不能强制停止已经运行中的 OSMnx 网络调用；其超时后后台请求是否继续由运行时/上游请求控制，尚未真实网络验证。
- 新增完全本地的模拟测试，覆盖无效 BBox/类型在请求前拒绝、上游异常不返回 traceback，以及模拟成功结果登记为图层并可继续执行路线分析。验证：`python -m pytest backend/tests/test_integration_e2e_v4.py -q -ra --tb=short -p no:cacheprovider`，24 项通过；`python -m pytest backend/tests/test_network.py -q -ra --tb=short -p no:cacheprovider`，14 项通过；OD 子集 4 项通过。`python -m py_compile backend/services/tools.py` 和目标文件 `git diff --check` 通过。没有调用真实 OSM/Overpass 或浏览器；真实数据覆盖、上游限流/超时和大区域内存使用尚未验证。


### 2026-10-26 批量地理编码请求数量上限

- 追踪 `batch_geocode` 工具输入 → 地址分隔 → 高德地理编码逐地址串行请求 → WGS-84 转换 → 汇总回复。**代码确认 P2 请求资源边界缺口：**工具对输入地址数量没有上限，每个非空地址都会额外发起一次最长 10 秒的外部请求；在单工具调用中可形成任意多次串行请求，延长任务并放大第三方服务负载。
- **最小修复：**单次最多接受 20 个地址；超限在任何网络请求前整体拒绝，并提示拆分重试。不改变合法批次逐项返回成功/失败的行为，也未引入新依赖。
- 新增超限回归测试并确认请求函数零调用。验证：`python -m pytest backend/tests/test_geocoding_error_safety.py backend/tests/test_amap_poi_fallback.py -q -ra --tb=short -p no:cacheprovider`，11 项通过；`python -m py_compile backend/services/tools.py` 通过。使用 mock，没有调用真实高德 API；20 个地址的真实服务耗时和高德限流策略未验证。


### 2026-10-26 开放数据发现、下载与矢量导入链路复核

- 复核入口与交接：`discover_gis_data`/`download_gis_data` → `data_discovery.resolve_request/discover/download` → Provider → `storage.validate_vector/write_vector/build_metadata` → 待发送图层与后端注册表；另核对 `/api/data/download` 的服务层注册。
- 本次查看的代码路径中，输入 bbox/格式/要素数量校验、Provider 搜索结构校验、非可下载栅格的明确限制、矢量空结果/未知 CRS/无效几何拒绝、写入后回读校验、元数据来源/CRS 保存和矢量待发送 provenance 均有实现。没有确认新的数据发现或导入缺陷，因此本模块本次未改生产代码；这是已查看代码和本地用例范围内的结论，不代表真实外部 Provider 已验证。
- 验证：`python -m pytest backend/tests/test_data_discovery.py -q -ra --tb=short -p no:cacheprovider`，22 项通过。测试使用 mock/fixture，未访问真实 OSM、USGS、Copernicus 服务；没有浏览器验收。存储文件名重复时的覆盖策略、Shapefile 多文件替换在文件系统异常下的恢复尚未做故障注入验证，暂列待验证项。


### 2026-10-26 execute_python 执行边界复核（风险记录，未改架构）

- 追踪 `execute_python` → `_ast_sandbox_check` → 临时脚本生成 → `subprocess.run(cwd=exec_dir, env=env, timeout=120)` → 输出文件与 GeoJSON 登记。**代码确认的边界：**这属于同一操作系统用户下的子进程和 AST 过滤，不是 OS 级文件、网络或资源隔离；代码将父进程环境复制给子进程，只移除 `AMAP_KEY`。因此其他环境凭据仍会被传递。另用非执行 AST 探针确认，动态拼接相对路径的 `open(...)` 通过静态检查，而字面 `../` 路径会被拒绝；本次没有执行文件读取或尝试逃逸。
- 影响取决于部署边界：本地单用户原型中由已登录用户提交的代码与公开服务中不可信用户提交的代码不是同一风险模型；若对不可信用户开放，现有实现不能据此宣称安全沙箱。符合本轮“只做证据充分、边界明确的审查”要求，未扩权限、未更改执行隔离架构，也未增加用于模拟真实隔离的测试。
- 针对已有凭据脱敏回归和 AST 过滤用例验证：`python -m pytest backend/tests/test_execute_python_credentials.py backend/tests/test_spatial_tools.py::TestSandboxSecurity -q -ra --tb=short -p no:cacheprovider`，6 项通过。该结果只证明现有测试范围，不证明不可信代码执行安全；公开部署前仍需独立安全设计与隔离方案评审。


### 2026-10-26 派生栅格来源与值单位连续性

- 使用已有长沙 SRTM-derived GeoTIFF（EPSG:4326、59×67、像元值单位 m、来源 AWS Terrain Tiles）复现：复制到本次独立临时目录后调用 `raster_resample`，修复前工具成功，但结果 raster metadata 的 `source_layer/source_reference/value_units` 均为空、`source_label` 退回泛化值且质量提示未继承。结果 GeoTIFF 无 `VALUE_UNITS` 标签，后续 `dem_analysis` 不能可靠判断高程单位。这是已复现的 P2 结果可解释性缺口，并可能影响非米制输入的后续坡度计算。
- **最小修复：**统一 `_raster_preview_op` 从输入数据集/注册图层继承来源标签、来源引用、像元值单位和质量提示，并把处理步骤及继承的元数据写回派生 GeoTIFF；重采样、重投影、重分类、焦点统计和按掩膜提取显式传递输入图层上下文。重分类输出声明“类别编码（无量纲）”，而不冒用原高程单位。未更改栅格算法或 CRS/文件格式。
- 新增 `backend/tests/test_raster_provenance.py`，覆盖带 CRS/来源/单位/质量信息的输入经过重采样、重投影、重分类、焦点统计后元数据展示及 GeoTIFF 标签，并从重采样结果继续运行坡度分析。
- 验证：`python -m pytest backend/tests/test_raster_provenance.py backend/tests/test_dem_analysis.py backend/tests/test_project_raster_persistence.py -q -ra --tb=short -p no:cacheprovider`，24 项通过；`python -m pytest backend/tests/test_raster_gap_tools.py backend/tests/test_new_tools.py -k raster -q -ra --tb=short -p no:cacheprovider`，27 项通过（18 项未选）；前端图层/工程/地图定向测试 39 项通过，栅格检查面板本地化测试 1 项通过。`py_compile` 与目标文件 `git diff --check` 通过。另在隔离临时目录用上述真实 SRTM-derived 文件跑通“重采样 → 坡度再分析”，核对输出保留来源链接、输入层、EPSG:4326、degree 像元单位、m/角度值单位和质量提示；没有本轮重启服务或重做浏览器保存/重开流程。仓库已有完整浏览器往返截图记录，但它早于本次元数据改动，不能代替本轮浏览器复验。

- **同模块继续发现并复现 P1 填挖方单位错误：**对 EPSG:4326 的 0.01° 像元 DEM，旧实现直接用 `transform.a * transform.e` 当 m²；在 60° 纬度、25 个像元、2 m 高差的受控用例中，结果约 0.01 m³，而椭球面积预期约 31,107,358.51 m³。旧实现也未按 DEM 高程单位把英尺值换算为米，却固定标注 m³/m²。
- **修复：**投影 CRS 面积按线性单位转换为平方米；北向上的地理 CRS 按每行使用椭球多边形面积计算像元面积，避免高纬度把度平方当平方米；旋转/斜切经纬度栅格明确拒绝，缺失 CRS 保留兼容计算但明确提示单位假设。已识别的高程单位按米换算；未知单位按米假设并给出质量提示。结果 GeoTIFF 记录 m 值单位及输入来源上下文。
- 新增回归覆盖地理坐标 DEM 面积、英尺高程换算，并加强无 CRS 输入的单位假设提示。`python -m pytest backend/tests/test_raster_gap_tools.py -q -ra --tb=short -p no:cacheprovider`，24 项通过。隔离临时目录内用真实长沙 SRTM-derived DEM 与其 +2 m 派生副本再验：3,953 个有效像元，独立椭球面积期望体积 8,703,629.12 m³，工具输出 8,703,629.10 m³，差 0.0246 m³（输出值以 float32 存储）。没有修改原始 DEM 或持久用户工程；未运行浏览器界面。

- **欧氏距离单位复核：**确认结果预览原先会继承输入高程的 `VALUE_UNITS`（例如 m），尽管运算结果是坐标平面距离；EPSG:4326 输入会把角度作为平面距离并可能误导用户理解成地面距离。
- **修复：**经纬度输入现在明确提示先重投影；投影 CRS 使用其线性单位作为结果值单位；缺少 CRS 时保留现有网格计算兼容性，但结果标为“栅格单位（CRS 未定义）”并附质量提示。采样间距根据栅格变换两个轴向向量计算；斜切网格明确拒绝，避免当作正交网格误算。
- 新增回归覆盖无 CRS 质量提示、EPSG:4326 失败指引和 EPSG:3857 距离单位/值。栅格工具、来源连续性、DEM 分析及工程持久化定向套件共 50 项通过；`py_compile` 和目标文件 `git diff --check` 通过。未进行浏览器复验；经纬度用户如需距离分析需先重投影，属于当前算法适用条件。

- **真实浏览器工程往返复验：**在单独新标签页导入临时目录内已有的 AWS Terrain Tiles SRTM-derived DEM（59×67，EPSG:4326，像元值单位 m，约 112.90–112.92°E、28.20–28.22°N），检查器展示来源链接、CRS、分辨率和质量提示；从栅格菜单执行坡度与坡向，图层面板出现两个可见栅格结果。保存为 `WTB DEM roundtrip verification 2026-10-26`，新建空会话后从工程列表恢复；恢复后 3 个栅格层都在面板，坡度层检查器仍保留来源、输入层、处理步骤、EPSG:4326、角度值单位、有效像元比例和地理栅格适用范围提示。浏览器错误日志为空。
- 验收只改动独立浏览器测试会话并新增上述本地验收工程；原先用户打开的浏览器标签及其 1 个图层未改动。该项目是本轮新增的本地验收工件，暂予保留以供复查；没有执行 AI 模型或外部数据服务验证。界面真实交互覆盖“导入 → 检查元数据 → 两次分析 → 图层面板 → 保存 → 新建会话 → 恢复”。

### 2026-10-26 栅格检查器元数据本地化

- **已复现 P2 混合语言：**真实浏览器工程恢复后，界面语言为 English，但栅格检查器的处理值仍显示 `坡度(Slope)`、像元值单位仍显示 `°（角度）`；其余字段、来源、CRS 和质量提示已经按 English 显示。原因是界面只翻译字段标签，直接渲染了后端保存的中文处理/单位元数据。
- **最小修复：**工程和 GeoTIFF 内的元数据继续保留原始值；仅在检查器展示时将已知坡度、坡向、山体阴影处理标签及常见角度/亮度/无量纲单位映射到英文，未知值保持原文。中文界面仍显示原始中文值，避免破坏旧工程和元数据兼容。
- 回归修改 `frontend/tests/raster_inspector_i18n.test.cjs` 验证 English、切回简体中文后标签与单位都正确；真实浏览器在刷新并恢复同一个保存工程后再次确认 `Slope`、`degree (°)`，来源、CRS、值域质量提示仍存在。`node --test tests/raster_inspector_i18n.test.cjs` 1 项通过；`node --test tests/vector_inspector_units.test.cjs` 9 项通过；`node --check` 与目标文件 `git diff --check` 通过。未覆盖尚未映射的动态处理描述；它们仍以原始值呈现，不声称所有元数据文字已完成全量翻译。
- 同模块继续复现用户截图对应的图层快捷菜单混合语言：English 界面下“显示图例、检查、移动到分组、发送给 AI 分析”等项仍为中文。为菜单的固定动作与说明补齐 i18n key，动态分组名和图层可见状态继续按原逻辑显示；不触碰菜单动作本身。浏览器刷新已保存工程后验证菜单全部为英文；新增测试检查 English 与简体中文词条回退。`node --test tests/raster_inspector_i18n.test.cjs` 更新后 2 项通过；`node --test tests/tool_menu_i18n.test.cjs` 3 项通过。
- **语言切换状态回归：**复现切换 English → 简体中文后列表仍显示 3 个图层，但计数回到静态初始值“0 个图层”。根因是 workspace 的整面板静态重译覆盖动态 `workspaceLayerCount`，而图层列表由 `renderList` 按当前语言负责格式化。移除该动态计数元素上的静态 `data-i18n`，保留图层渲染器的语言更新。新增回归断言动态计数不参与静态文案重置，且 `renderList` 继续从实际 `layerData.length` 生成计数。真实浏览器中从同一保存工程逐次切换 English ↔ 简体中文，计数分别显示 3 LAYERS / 3 个图层，DOM 行数保持 3；最后恢复 English 设置。

### 2026-10-26 SSE 自动恢复提示可见性

- 追踪 `run_agent_stream` → SSE `note` → `frontend/js/chat.js` `_processSseLine`。后端在临时服务故障重试成功和空响应恢复前分别发送固定 `note` 消息（`backend/services/graph.py` 约 1550、1603 行）；前端此前只处理工具步骤与 `done`，因此自动重试期间的解释事件被静默丢弃。这是代码确认的 P2 可理解性缺口，不影响最终 `done` 正文或工具执行本身。
- 前端现将非空 `note` 显示为系统提示胶囊；为两条已知后端提示提供 English 文案，并对提示文本做 HTML 转义和长度限制。未改变 SSE 协议、重试策略或 GIS 工具行为。未知 note 在 English 界面仍显示原文，未声称动态后端消息全部本地化。
- 新增 `frontend/tests/chat_send_lifecycle.test.cjs` 用例，注入模拟 SSE note/done，验证英文提示、系统胶囊类型和恶意 HTML 字符串安全转义。`node --test frontend/tests/chat_send_lifecycle.test.cjs`：19 项通过；相邻执行卡回归 `node --test frontend/tests/execution_cards.test.cjs`：20 项通过；`node --check frontend/js/chat.js` 与目标文件 `git diff --check` 通过。相邻复核发现：图级工具失败会保留在执行步骤卡中；当前“整轮 task status”在收到最终 done 且非 timeout 时仍记为 success，而现有代码/文案没有定义可恢复失败步骤是否应使整轮失败，因此暂不改状态语义，列为产品定义观察项。传输/Agent 异常路径先发 error 再收尾，当前协议下不会把该分支的 error done 误标成功。自动化用例不是浏览器或真实模型供应商验收。
- 本次开始时 `main` 工作区已有大量未提交和未跟踪内容；`frontend/js/chat.js`、测试文件及本进度文档均已有改动。本次仅在这三个既有脏文件做局部兼容修改，没有清理或重置其他改动；未提交或推送。

### 2026-10-26 执行步骤失败与任务历史状态一致性

- 追踪 `chat.send` 创建任务 → SSE `tool_end` → `execution_cards.finish` → `task.js` 历史卡片。**已复现 P2 状态误导：**发送 `tool_end(status=error,is_error=true)` 后收到合法 `done(execution_status=success)`，步骤卡正确显示失败，但历史任务状态仍是绿色“成功”。当前模型可继续回答或重试，因此不能简单把任何失败步骤都升级为整轮失败；但未恢复错误也不应在历史中显示成功。
- **最小修复：**`execution_cards.finish('success')` 返回是否仍有失败/警告步骤；聊天完成时据此将整轮状态更新为 `partial`。任务历史新增“部分完成”状态、橙色样式并允许重跑。执行卡内成功重试会清除对应未解决失败，整轮仍显示成功；超时和传输失败沿用原失败/中断路径。未改后端 SSE 协议或持久化结构，旧任务状态不受影响。
- 新增回归覆盖“失败步骤 + done(success) → partial”、失败恢复后的汇总仍为完整成功，以及部分完成任务的历史标签、重跑入口和本地存储。修复前回归测试按预期失败：实际 `success`、期望 `partial`；修复后 `node --test frontend/tests/chat_send_lifecycle.test.cjs` 20 项、`node --test frontend/tests/execution_cards.test.cjs` 20 项、`node --test frontend/tests/task_cancelled_status.test.cjs` 4 项全部通过。`node --check`（chat、execution_cards、task）及目标文件 `git diff --check` 通过。当前浏览器标签停留在已有的 DEM 工程，没有可安全复用的“部分完成”示例任务；为避免触发真实模型请求或改写验收工程，本轮未做该状态的真实浏览器视觉验收。
- 本次开始时聊天代码、聊天测试和本进度文档已存在未提交改动；新增/修改了 `frontend/js/execution_cards.js`、`frontend/js/task.js`、`frontend/css/style.css` 和两项执行/任务状态测试（这些文件在本次开始快照中未显示为脏）。其他原有脏文件均未触碰或清理；未提交或推送。

### 2026-10-26 真实模块地图

- 根据当前 `frontend/index.html` script 顺序、实际 JS/service 文件、`backend/main.py` 路由及现有测试目录，新增 [`module-inventory.md`](module-inventory.md) 作为逐模块导航。确认 FastAPI 入口目前集中在 `backend/main.py`，仓库不存在 `backend/routers/`；前端由多个脚本共享 `window.GIS` 状态；本地任务历史与后端任务/运行记录是不同状态面。
- 清单按工作区、地图/图层、上传、AI/SSE、矢量/栅格工具、网络、数据发现、项目导出、任务历史、安全设置和 i18n 汇总入口、关键状态、已有测试及验证边界。它是导航和覆盖记录，不代表每个模块均已完整审查；模块结论仍以本台账中的证据为准。
- 本轮开始前工作区已含大量修改；新增清单文件并追加此索引，没有覆盖、清理或格式化其他文件。未运行代码测试，因为该项只补充审查索引，不改运行代码。

### 2026-10-26 本地 API CORS 与写操作信任边界（待安全设计）

- **代码确认的策略：**`backend/main.py` 使用 `allow_origins=["*"]`、`allow_methods=["*"]`、`allow_headers=["*"]`；项目列举/保存/删除、全量项目删除、`/api/reset_state`、图层操作和 `/api/tools/invoke` 路由未看到应用层认证/Origin 校验。`backend/launcher.py` 与 `desktop/main.js` 当前启动均绑定 `127.0.0.1`，限制普通远端直连，但并不等价于浏览器来源校验。
- **无破坏性验证：**本地 FastAPI `TestClient` 对 `/api/projects` 发起来自 `https://audit.invalid`、预检 `DELETE`/`content-type` 的 OPTIONS 请求得到 200，响应含 `Access-Control-Allow-Origin: *`、DELETE 方法和 content-type 允许头。继续直接检查危险操作端点：对 `/api/tools/invoke` 发起来自 `https://example.com`、预检 `POST`/`content-type` 的 OPTIONS 请求同样得到 200 和通配来源/方法/请求头；只发送预检，没有调用工具或触碰图层状态。没有调用 DELETE，也没有读取或输出任何本地工程数据。
- **风险定级：**若不可信网页所在浏览器允许访问该 loopback 服务，通配 CORS 与无鉴权写/删/工具端点可能让网页读取或影响本机 WTB 数据；属于潜在高严重度安全问题，但当前只确认 CORS 策略，未在真实浏览器验证 Private Network Access/本地网络权限实际是否阻止攻击链，故不能宣称已复现可利用漏洞。默认 loopback 绑定也不应被描述为服务认证。
- **本轮不改安全边界：**允许的来源需结合 WTB 本地服务、桌面模式、外部部署/静态托管等使用方式定方案；贸然限制 CORS 可能破坏桌面跨端口连接，单加 Origin 白名单也不是完整 CSRF/session 设计。按目标要求暂不修改权限或安全架构，保留为高优先级安全设计项；后续可独立完成不涉及权限变更的模块审查。具体模块结构见 [`module-inventory.md`](module-inventory.md)。

### 2026-10-26 `.giswork` 工程导入归档资源边界

- 追踪 `/api/projects/import` → Starlette `UploadFile` spooled stream → `project_service.import_project` → `_extract_project_archive` → `project.json`/blob/栅格资源验证和工程索引提交。已有路径遍历、符号链接、非法 blob 和缺失栅格资产校验，且解压失败会清理新建 staging 工程目录。
- **代码确认的资源边界缺口（条件性风险）：**归档在 `extractall` 前没有最大成员数、累计解压大小或压缩比限制；接口也没有看到显式上传请求体大小限制。超大/高压缩归档可能消耗本机临时磁盘、项目盘或长时间 CPU。影响依赖用户导入归档及其大小；本轮没有制造或执行压缩炸弹，也未尝试耗尽磁盘，故不是已复现故障。
- 已有安全用例定向运行：`python -m pytest backend/tests/test_layer_group_persistence.py -k project_import_rejects_unsafe_archive_paths_before_extract -q -ra --tb=short -p no:cacheprovider`，4 项通过；`python -m pytest backend/tests/test_project_raster_persistence.py -k import_rejects_unsafe_or_missing_original_assets -q -ra --tb=short -p no:cacheprovider`，3 项通过。它们覆盖路径/资产校验，不覆盖资源上限。
- **本轮未加任意大小上限：**工程包可包含多个栅格源资产，而当前产品没有声明 `.giswork` 最大上传/解压尺寸；复制其他 ZIP 上传的 512 MiB 上限可能拒绝当前允许组合出的合法工程。需先确定工程容量策略和错误呈现，再设计压缩流限制；这不阻止继续其他模块审查。未改项目服务或文件系统数据。

### 2026-10-26 `.giswork` 矢量 blob 导出完整性

- 追踪 `/api/projects/{project_id}/export` → `project_service.export_project` 与 `import_project`。导入已校验矢量 blob 存在且解压内容 SHA-256 前缀匹配，但导出遇到无效 blob 标识会 `continue`，缺少对应文件也会静默跳过，仍返回 ZIP。
- **已复现 P1 交付缺陷：**在隔离临时工程存储中保存含矢量层的工程，删除其 blob 后调用导出，旧实现返回 ZIP 而不报错；该包缺少工程声明的数据，无法通过现有导入校验。没有触碰真实项目存储。
- **最小修复：**`export_project` 对无效标识、缺失矢量文件、无法解压/读取以及内容摘要不匹配均抛出明确 `ValueError`，仅在完整性校验通过后将 blob 写入归档。FastAPI 导出路由已有 `ValueError` → HTTP 400 的处理。新增回归覆盖缺失文件、空标识及有效 gzip 但内容摘要不匹配三种情况。
- **验证：**缺失文件回归在修复前按预期失败（旧实现未抛异常）；修复后 `python -m pytest backend/tests/test_layer_group_persistence.py backend/tests/test_project_raster_persistence.py -q -ra --tb=short -p no:cacheprovider`，44 项通过，覆盖工程往返及栅格持久化相邻路径。`py_compile` 与目标文件 `git diff --check` 通过。尚未单独发起 HTTP 导出请求；错误映射由当前路由代码确认。未进行浏览器复验。
- 本轮开始时 `project_service.py`、两个测试文件及本台账、模块清单均已有未提交改动；在这些脏文件中仅作局部兼容修改/追加记录，没有重置或清理改动，未提交或推送。

### 2026-10-26 数据下载落盘的 Shapefile 同名覆盖恢复

- 从 `data_discovery.download` → `_import_vector` → `data_providers.storage.write_vector` 追踪文件落盘和回读校验。GeoJSON/GPKG 使用单文件 `os.replace`；Shapefile 需要替换多个 sidecar 文件。原实现先校验 staging 成果，但正式目录按文件逐个 `os.replace`，中途异常没有回滚。
- **已复现 P1 数据完整性问题：**临时目录先写入一份 Shapefile，再故障注入让第二个 sidecar 替换成功、第三个替换抛错；旧实现退出后 `.dbf` 已包含新属性值而其他组件仍是旧版，证明同名数据文件会混合。只使用 pytest 临时目录，未改用户数据。
- **最小修复：**提交多文件前把已有同名 Shapefile 组件复制到同目录临时备份；替换失败时恢复原组件并移除本次新增组件。恢复本身若失败，则保留恢复副本并给出明确错误。成功路径继续逐文件替换，并沿用原有旧 sidecar 清理逻辑；未改变文件格式或下载命名策略。
- 新增 `test_data_provider_storage.py` 故障注入测试，逐字节比较失败前后所有同名组件。修复前测试失败并显示 `.dbf` 从 `old` 变为 `new`；修复后 `python -m pytest backend/tests/test_data_provider_storage.py backend/tests/test_data_discovery.py -q -ra --tb=short -p no:cacheprovider`，23 项通过。未连接真实 Provider；未模拟进程崩溃、磁盘耗尽或回滚期间硬件/文件系统持续故障。
- 本轮开始时 `backend/services/data_providers/storage.py`、新测试文件和本进度文档未显示为脏；对 `module-inventory.md` 的已有改动追加了状态更新。此前本轮已修改的工程服务和持久化测试均为开始前已有未提交文件。未清理其他改动，未提交或推送。

### 2026-10-26 矢量上传 ZIP 多 Shapefile 歧义

- 追踪前端 `upload.js` → `GIS.api.upload` → FastAPI `/api/upload` 的 ZIP 分支 → 解压到临时目录 → GeoPandas 读取 → 图层注册。现有逻辑只取 `shp_files[0]`，没有处理同一个 ZIP 含多个 `.shp` 的情况。
- **已复现 P2 不完整交付：**构造包含 `first/first.shp` 与 `second/second.shp` 的安全 ZIP，通过真实本地 FastAPI `TestClient` 上传。旧逻辑尝试读取第一个无效样例并返回通用读取错误；确认它在发现多个数据集时不会说明仅支持单个数据集，且会静默忽略其他 `.shp` 入口。样例没有注册任何图层或写入正式数据。
- **最小修复：**解压前若归档包含多个 `.shp`，删除临时上传并返回“请拆分后分别上传”的明确提示；单 Shapefile ZIP 流程不变。新增 HTTP 回归检查错误、无图层注册和上传临时文件清理。
- 修复前回归按预期失败：旧逻辑返回 GeoPandas 读取首个 `.shp` 的通用错误；修复后 `python -m pytest backend/tests/test_upload_safety.py backend/tests/test_upload_vector.py backend/tests/test_upload_raster.py backend/tests/test_upload_handoff.py -q -ra --tb=short -p no:cacheprovider`，32 项通过，1 条预期的缺 CRS GeoPackage 写入警告。测试覆盖本地 API 和受控文件；未使用真实用户文件或浏览器上传。
- 本轮开始时 `backend/main.py` 与 `module-inventory.md`、进度台账已有未提交改动；只在脏的 `main.py` 上传分支增加明确拒绝条件，在脏清单/台账追加记录；新增测试改动开始前干净的 `test_upload_safety.py`。其余既有改动均未清理，未提交或推送。

### 2026-10-26 地图与图层注册状态复验

- 复核 `gis_state.addLayer/removeLayer/setVisible` → `layers.js` 面板桥接/版本注册队列 → `GIS.api.registerLayer/unregisterLayer` → FastAPI 注册令牌，以及 3D Cesium 按共享状态增删、显隐和样式同步。已有记录已经覆盖注册队列竞态和工程恢复失败提示，本次不重复修改这些逻辑。
- **已复现 P2 反馈缺口：**Cesium GeoJSON 加载 Promise 拒绝时，`syncLayer` 只写控制台错误；即使数据源未加入 3D 地图，图层面板仍保持可见，用户没有提示。现有受控测试已能触发失败，但原断言只验证相机不飞到不可用范围；新增断言修复前显示警告次数为 0。
- **最小修复：**加载失败且仍对应当前图层版本时，若用户仍处于 3D 模式，给出带图层名和检查方向的 warning；2D 模式的迟到失败不弹提示。英文界面文案放入现有 i18n 字典，中文使用本地 fallback；没有改变 2D 数据或 Cesium 渲染策略。
- 验证：地图/图层逻辑 `node --test frontend/tests/layer_panel_rename.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/map_layer_visibility.test.cjs frontend/tests/layer_symbology_persistence.test.cjs`，57 项通过；FastAPI 图层检查/注册集成 `python -m pytest backend/tests/test_layer_service.py backend/tests/layered/test_layer4_map_integration.py -q -ra --tb=short -p no:cacheprovider`，8 项通过。3D 清理、失败提示（含切回 2D 后不弹过期警告）及英文词条 `node --test frontend/tests/renderer_cesium_clear.test.cjs frontend/tests/tool_menu_i18n.test.cjs`，15 项通过；`node --check`（`renderer_cesium.js`、`i18n.js`）和目标 `git diff --check` 通过。这里是受控异步拒绝用例，不是浏览器/真实 Cesium 运行验收；真实浏览器渲染和后端并发仍未验证。
- 本轮开始前 `renderer_cesium.js`、`renderer_cesium_clear.test.cjs`、`i18n.js`、`tool_menu_i18n.test.cjs`、图层状态文件与审查文档均已修改或未跟踪；本次只对这些相关文件做局部变更，未清理工作区其他内容。

### 2026-10-26 `spatial_near` 距离单位与阈值有效性

- 追踪 `/api/tools/invoke`/Agent 工具 → `spatial_near` → `_layer_to_gdf`（按 WGS-84 读取）→ 投影 → source 几何缓冲 → target 空间连接 → `_gdf_to_layer`。原实现把 EPSG:3857 的坐标单位直接当作地面米数，且该工具不在参数角色校验表内，内部也未检查负数/非有限距离。
- **已复现 P1 空间筛选错误：**受控 WGS-84 点位 `(3.0, 60.0)` 与 `(3.01, 60.0)` 的 WGS84 椭球测地距离为 558 m；同一对点在 Web Mercator 中坐标差为 1113.19 m。用 600 m 查询时，旧实现漏掉了实际位于阈值内的目标。复现和数值核对都只使用测试坐标，无外部或用户数据。
- **最小修复：**两个输入图层合并后估算同一个局部 UTM 投影，再以该投影米制几何做 buffer/intersects；有限非负阈值才执行，零距离使用原几何相交以正确包含重叠点。其他工具、结果结构与注册流程不变。工具说明明确当前方法适用于局部范围，不把 UTM 外推为全球测距保证。
- 修复前高纬回归按预期失败（目标被漏掉）；修复后 `TestSpatialNear` 7 项通过。全文件 `python -m pytest backend/tests/test_spatial_tools.py -q -ra --tb=short -p no:cacheprovider`，135 项通过、1 条 joblib 物理核心探测警告（回退逻辑正常）；`py_compile` 和目标 `git diff --check` 通过。没有进行真实第三方数据、浏览器或大范围跨 UTM 区域验收。
- 本轮开始时 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py`、模块清单和台账已有未提交改动；仅在这些相关脏文件中局部修改/追加记录，其他改动均保留，未提交或推送。

### 2026-10-26 `spatial_voronoi` 输入契约与高纬度距离

- 追踪工具注册的 `spatial_voronoi` → `_layer_to_gdf`（GeoJSON 按 EPSG:4326 构造）→ Shapely Voronoi → `_gdf_to_layer`（地图图层注册）。原实现对任意几何直接求 union；面要素会按边界顶点生成泰森区并报告成功。它还直接在经纬度度数平面计算，距离判定在高纬地区会明显失真。
- **已复现：**面图层调用会生成结果，违反“根据点图层”的输入契约。另一个受控高纬样例使用站点 `(0,80)、(1,80)、(1,81)`；探针 `(0.01,80.52)` 在经纬度平面被错误归入第一个站点区域，而按局部 UTM 地面距离不应归入该站点。此为合成坐标测试，不是实际业务数据验收。
- **最小修复：**仅接受 Point/MultiPoint，拒绝空几何，并要求至少两个位置不同的站点；使用已有 `_to_local_metric_gdf` 将点转入范围对应的 UTM 后计算 Voronoi，再把多边形转回 EPSG:4326 注册到地图。未更改结果图层交付结构。
- **验证：**修复前高纬回归失败；修复后 `python -m pytest backend/tests/test_spatial_tools.py::TestSpatialVoronoi -q -ra --tb=short -p no:cacheprovider`，5 项通过；完整空间工具文件 `python -m pytest backend/tests/test_spatial_tools.py -q -ra --tb=short -p no:cacheprovider`，139 项通过，1 条 joblib 在 Windows 环境无法探测物理 CPU 数的警告，测试回退到逻辑核心。`python -m py_compile backend/services/tools.py` 与目标 `git diff --check` 通过。
- 限制：仅覆盖局部范围可由 UTM 表达的点集；跨日期变更线、跨多个 UTM 带、大范围/全球数据未验证。没有真实浏览器、外部服务或真实用户数据验收。
- 本轮开始时工具实现、空间工具测试及验证文档已有未提交改动；本次在相关文件中做局部修改，没有清理或覆盖其他既有工作，未提交或推送。

### 2026-10-26 `spatial_cluster` 输入与参数边界

- 追踪 `spatial_cluster` → `_layer_to_gdf` → Shapely 几何坐标 → scikit-learn DBSCAN → 标签写回原要素 → `_gdf_to_layer`。工具说明要求点图层，但旧实现将几何所有坐标直接传给 DBSCAN，再把得到的标签写回要素行。
- **已复现 P2 错误反馈：**单个面要素含 5 个坐标，DBSCAN 返回 5 个标签，写回 1 行 GeoDataFrame 时失败并显示内部长度不匹配错误；用户难以判断该工具只接受点数据。此前缺少对 NaN/无穷/非正 eps 以及非正/非整数 min_samples 的前置校验。
- **最小修复：**只接受非空 Point 要素；执行聚类前验证 eps 是有限正数、min_samples 是正整数；无效输入返回明确提示，不注册结果图层。保留现有 eps 度数单位及输出结构，没有改动聚类算法参数语义。
- **验证：**新增非点输入及 5 组无效参数回归；目标 `TestSpatialCluster` 7 项通过。完整 `python -m pytest backend/tests/test_spatial_tools.py -q -ra --tb=short -p no:cacheprovider`，145 项通过，1 条 joblib 在 Windows 无法识别物理核心数的警告，已回退到逻辑核心。`py_compile` 和目标 `git diff --check` 通过。面输入回归修复前失败，错误为标签数与要素数不一致。
- **剩余风险：**eps 仍按经纬度度数计算，文档也明确其近似换算；同一 eps 对不同纬度代表不同地面距离。此处保持 API 语义兼容，后续需先决定是否增加显式距离单位/米制参数，再设计兼容方案；本轮没有声称其适合高纬度距离聚类。未做真实数据或浏览器验收。
- 本轮开始时 `tools.py`、`test_spatial_tools.py`、模块清单和台账已有未提交改动；仅在相关脏文件中追加定向实现、测试和记录，保留其他所有工作，未提交或推送。

### 2026-10-26 `spatial_buffer` 局部 UTM 适用范围

- 追踪 `spatial_buffer` → 参数单位校验 → 几何修复/规模分层 → bounds 中心选择单一 UTM 带 → 缓冲 → 转回 EPSG:4326 → 图层注册。既有实现明确只适用于局部范围，但没有拒绝日期变更线跨越或 UTM 覆盖纬度外的输入。
- **已复现错误结果路径：**分别用经度 `179.9°/-179.9°` 两个点和纬度 `85°N` 的单点调用 1000 米缓冲；旧代码两者都生成并注册结果，而 bounds 中心经度把跨日期变更线范围定位到格林尼治附近的 UTM 带，85°N 也落在标准 UTM 北界 84°之外。仅使用合成坐标，不代表真实用户数据。
- **最小修复：**缓冲前检查经度 bounds；范围跨度超过 180°时明确拒绝单一局部 UTM 处理。输入 bounds 超出 80°S–84°N 标准 UTM 纬度覆盖时也停止并说明限制。常规局部范围原流程不变，没有改动公共工具参数。
- 修复前新增回归均失败且显示旧实现已创建图层；修复后 `TestSpatialBuffer` 13 项通过。完整 `python -m pytest backend/tests/test_spatial_tools.py -q -ra --tb=short -p no:cacheprovider`，147 项通过，1 条 joblib 无法探测 Windows 物理核心数警告并回退逻辑核心。`python -m py_compile backend/services/tools.py` 与目标 `git diff --check` 通过。
- 限制：这只拒绝明显不适用的日期变更线/极区输入，没有定义任意大范围或跨 UTM 带缓冲的精度承诺；该工具仍是局部分析能力。未用真实地理数据、真实地图浏览器或外部服务验收。
- 本轮开始前工具实现、测试和审查文档均已有未提交改动；只在对应脏文件内做局部兼容修改，未清理、提交或推送其他工作。

### 2026-10-26 聚类面板参数静默回退

- 追踪几何工具面板 `spatial.js` 的 `geomClusterEps` / `geomClusterMin` → `_runOperation` → `/api/tools/invoke`。原面板用 `parseFloat(value) || 0.01` 和 `parseInt(value) || 3`，会把 0 和空值静默替换成默认值；用户无法确认提交值是否与界面输入一致。后端已经会拒绝 eps≤0 和 min_samples<1，但 UI 在它到达后端前已改变参数。
- **代码确认并通过定向用例复现：**面板表达式对 `0`、空字符串触发默认值；原本没有针对该路径的前端回归。该风险来自直接 JavaScript 表达式及回归测试，不是浏览器手动验收。
- **最小修复：**聚类参数显式转为 Number，校验 eps 有限且大于零、最小点数为正整数；无效输入抛出可读错误并阻止 `_invoke`。无 workspace 容器时将同步校验错误写入既有空间分析结果区域，避免异常被吞掉；不改变 eps 的度数单位和后端参数格式。
- **验证：**新增 `spatial_fields.test.cjs` 回归，覆盖 eps 的 0/空/NaN/Infinity/负数和 min_samples 的 0/小数/空值，确认均不调用后端；`node --test frontend/tests/spatial_fields.test.cjs frontend/tests/tool_menu_i18n.test.cjs frontend/tests/spatial_stats_i18n.test.cjs`，7 项通过。`node --check frontend/js/spatial.js` 和目标 `git diff --check` 通过。未做浏览器手动输入验收。
- **剩余限制：**聚类 eps 仍为度数，不能等价表达用户任意纬度下的固定米制距离；更改成米制需做兼容性设计，不在此处暗改现有工具语义。
- 本轮开始时 `spatial.js`、`spatial_fields.test.cjs` 和进度文档已有未提交内容；只在这些相关脏文件增加局部校验、反馈和测试，未清理或覆盖其他改动。

### 2026-10-26 `spatial_cluster` 米制半径与单位衔接

- 继续追踪 `spatial_cluster` 的 LangChain 工具 schema、工具说明、Agent 推荐和 `spatial.js` 手动面板。确认工具默认 `eps` 为度数，`measure_distance` 则返回米/公里；旧说明同时建议先用 `measure_distance` 查看点间距，却未说明单位转换，AI 有把米值直接作为度数半径传入的风险。空间面板也没有单位选择。
- **代码已确认的语义不一致：**点集在高纬使用度数距离时，东西方向的地面长度随纬度缩短；旧参数不能代表固定地面距离。旧行为虽对显式度数调用有效，但无法忠实表达“500 米内聚类”这类自然语言需求。
- **最小兼容改进：**给工具增加可选 `distance_unit`（`degrees`/`m`/`km`），默认仍为 `degrees`，旧调用结果语义保持不变；m/km 模式使用现有局部 UTM 辅助逻辑，跨日期变更线或 UTM 纬度范围外明确停止。手动面板增加单位选择并透传给已有工具，增加英文单位本地化；工具说明澄清不能把测距返回的米数填入默认度数参数。没有增加依赖或新工具。
- **验证：**新增 80°N 两点样例，并用 pyproj WGS84 Geod 确认两点地面距离位于 100–500m 之间；在局部 UTM 中，500m/0.5km 阈值将两点聚为一簇，100m/0.1km 则均判为噪声。这验证参数按米制距离计算，而不是把阈值当度数。旧默认度数测试继续通过；非法单位拒绝且不注册结果。`python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_tool_args_guard.py backend/tests/test_ai_wiring_new_tools.py backend/tests/test_tool_docstring_guards.py -q -ra --tb=short -p no:cacheprovider`，187 项通过，1 条 joblib Windows 物理核心探测警告并回退逻辑核心。首次运行发现 `test_ai_wiring_new_tools.py` 把提示中的 `_current_amap_key` 凭据变量误判为工具名；将其加入非工具标识符排除后该提示词检查通过。前端 `node --test frontend/tests/spatial_fields.test.cjs frontend/tests/tool_menu_i18n.test.cjs frontend/tests/spatial_stats_i18n.test.cjs`，8 项通过；参数校验、单位透传、`py_compile`、`node --check` 和目标 `git diff --check` 通过。
- **限制：**m/km 模式仅对局部 UTM 适用范围有验证；大范围、跨带精度与真实地图浏览器输入尚未验收。旧 degree 模式仍保留，调用方应明确理解角度单位。
- 本轮开始前后端空间工具、参数保护、空间工具测试、`spatial.js`、i18n、前端测试和审查台账已有未提交改动；仅在相关脏文件中局部修改，其他工作均保留，未提交或推送。

### 2026-10-26 `execute_workflow` GIS 图层产物衔接

- 追踪 AI 工具 `execute_workflow` → `WorkflowExecutor` 的 `StructuredTool.invoke` → 矢量 GIS 工具向 `_registered_layers` 注册结果 → 后续节点模板变量解析。手工构造真实工具链“`spatial_buffer` → `spatial_centroid`”，第一步提示缓冲完成并注册 `workflow_chain_source_缓冲区`，但它只向 Workflow 返回文本；第二步引用 `${buffer.layer_name}` 后失败，错误为“上游节点 buffer 未产生输出 layer_name”。此前 Workflow 单测只用返回结构化 dict 的 mock，未覆盖 GIS 工具的注册副作用。
- **已复现 P1 核心任务断链：**上游 GIS 操作实际创建的结果图层，不能自动作为下游工具输入。图层本身在注册表中，但 DAG 的数据依赖解析只读取工具返回值。
- **最小修复：**`WorkflowExecutor` 接收可选图层注册快照回调；每个节点执行前后比较注册表名称及 registration token，将唯一新建/更新图层暴露为 `layer_name`，多个变更暴露为 `layer_names`。`execute_workflow` 连接该回调，并在工具描述中说明变量引用方式；非 GIS / 结构化返回工具保持既有行为。同时修正 Workflow 在整体 schema 校验失败时仍把具体无效节点留作 `pending` 的状态：定位到节点的错误标为 failed，其余未执行节点标为 skipped。
- **验证：**修复前上述真实 `spatial_buffer`→`${buffer.layer_name}`→`spatial_centroid` 小型调用在质心节点失败；修复后新增集成回归验证工具注册的图层可传给后续工具、质心图层存在。`python -m pytest backend/tests/test_workflow.py -q -ra --tb=short -p no:cacheprovider`，25 项通过；该套件首次运行发现原有“工具不存在”用例与 executor 校验返回节点状态不一致，修复后恢复通过。测试使用本机工具注册表和合成 WGS‑84 点数据，没有真实模型或外部服务。
- **限制：**图层快照按节点前后 registration token 识别结果；只有一个产物时可以无歧义引用 `layer_name`，多个产物需用 `layer_names` 并由工作流显式选择。未在浏览器确认 Agent 内层 workflow 的步骤进度卡呈现；`execute_workflow` 仍以单个 Agent 工具调用返回摘要。
- 本轮开始时工作区已有大量既有未提交改动；`workflow.py`、`test_workflow.py` 和对应台账仅作本项相关修改，未清理或重置其他文件，也未提交或推送。

### 2026-10-26 真实 DEM 二次分析与工程恢复

- 从当前浏览器验收工程 `WTB DEM roundtrip verification…`（本地工程 ID `f7842aa2`）继续。图层源元数据记录为 AWS Terrain Tiles（SRTM-derived），输入栅格 EPSG:4326、59×67 像元、范围 112.90000–112.92000°E / 28.20000–28.22000°N，值单位 m；垂直基准未提供。此为本地已保存真实数据的验收，不代表本轮重新访问或独立验证数据提供方。
- 浏览器中选择既有坡度图层，运行 5 类分位数重分类；响应为 5 类、3705/3705 有效输入像元，产生新的 Raster 图层。将新图层改为可读名称并保存到验收工程。刷新后页面启动为空工程；从首页最近工程手动打开，图层面板恢复 4 个图层。栅格检查器显示新图层来源于坡度结果、处理方式为 5 类分位重分类、CRS 为 EPSG:4326、像元单位为 degree、值单位为无量纲类别编码、有效像元率 93.73%，并恢复小范围适用提示。
- 通过本地工程 API 验证保存快照包含原始 DEM、坡度、坡向、重分类结果；四层均记录原始 GeoTIFF 与预览 PNG 资产，重分类层预览/原始资产分别返回 HTTP 200（PNG/TIFF）。刷新后的真实浏览器 UI 显示并可检查第四层，证明本工程的手动重开及栅格恢复链路。随后从已保存 TIFF 在内存中读取坡度和重分类数组，按五分位公式独立重算并逐像元比对：两者均 3705 个有效像元，结果精确匹配，类别 1–5 各 741 像元。此验证确认实现与分位算法一致，不构成外部地形基准或业务阈值合理性的验证；验证脚本收到一个非致命 NumPy 2.5 deprecation warning。
- **浏览器复现 P2 结果可读性问题：**重分类输出文件名此前取 `_find_uploaded_tif` 实际路径的 basename；工程资产用内容哈希命名时，检查器的 Source file 显示哈希而非用户图层名（本次可见 `4972df12f32ebb1ad32a_重分类.tif`）。
- **最小修复：**`raster_reclassify` 改用注册图层名生成安全结果名，复用 `_safe_layer_export_stem`；新回归构造“可读图层名映射到哈希命名 TIFF”的已恢复工程情形，断言输出图层名使用可读名。当前真实浏览器工程的这一份文件是在修复前生成，后在 UI 中将图层标题改为可读名；未额外再跑一次分类，以免往验收工程加入重复结果。新命名由自动化回归验证，真实页面重跑尚未验证。
- **验证：**`python -m pytest -p no:cacheprovider -q --tb=short backend/tests/test_raster_gap_tools.py backend/tests/test_project_raster_persistence.py backend/tests/test_raster_provenance.py`：44 passed；`python -m py_compile backend/services/tools.py`、目标文件 `git diff --check` 通过。浏览器验收使用本地 FastAPI 和本地保存的 SRTM-derived DEM；无真实模型调用、无第三方数据重新请求。
- 本轮开始时 `backend/services/tools.py`、栅格测试、验证台账已存在未提交或未跟踪改动；只在相关脏文件追加结果命名修复、回归和验收记录。验收工程 `f7842aa2` 新增一个坡度重分类结果并已保存；原始 DEM、坡度和坡向未删除或覆盖。没有提交或推送。

### 2026-10-26 Workflow 内部节点进度接入聊天执行卡

- **现状证据：**`WorkflowExecutor` 原已产生节点 started/completed/failed/skipped 回调，但 `execute_workflow` 未连接该回调；Agent 侧只消费 LangGraph `values` 流，因此用户只看到一个 `execute_workflow` 工具调用及最终摘要，无法在执行期间辨认内部节点进度。
- **最小修复：**在 LangGraph 工具执行上下文中通过 `get_stream_writer()` 发布带 invocation/workflow 上下文的 custom 事件；图状态流同时消费 `values` 与 `custom`，把工作流节点事件映射到现有 `tool_start/tool_end` SSE 协议和执行卡。非图调用及 custom 事件写入失败仍不阻断工作流执行；失败节点呈错误状态，依赖跳过节点呈部分完成警告，并规整文案避免前端失败词匹配误判。
- **验证：**`backend/tests/test_workflow.py` 用真实 LangGraph `StateGraph` 执行实际 `execute_workflow` 工具，验证节点成功进度及结构校验失败/依赖跳过事件；`backend/tests/test_stream_step_events.py` 验证 custom 流事件映射和既有 Agent SSE 收尾；`frontend/tests/execution_cards.test.cjs` 验证成功、失败、跳过卡片状态。后端定向套件 48 passed；前端 `execution_cards` 与 `chat_send_lifecycle` 41 passed；`py_compile`、`node --check frontend/js/chat.js`、目标文件 `git diff --check` 通过。
- **限制：**未在真实模型及浏览器中运行含 Workflow 的 Agent 任务；因此已验证的是 LangGraph custom stream → Agent SSE 转换 → 执行卡协议及卡片状态映射，不声称完成真实浏览器视觉验收。没有改变 `execute_python` 安全边界，也未扩大工具权限。
- 本轮继续在开始前已有的大量未提交工作区上进行，仅更新相关 Workflow/Agent 实现、测试及扫描记录；没有清理其他改动，没有提交或推送。

### 2026-10-26 任务历史重载后的未完成状态恢复

- **证据与影响：**`task.js::createTask` 和 `updateTask(status)` 会把任务卡写入 localStorage；`loadFromStorage` 原样恢复 `pending/planning/executing`。页面重载结束了前端 SSE 消费后，旧卡仍显示规划中/执行中和 spinner，且这些状态没有重跑入口。此为代码确认，改动前由新增恢复回归构造旧版存储状态覆盖。
- **最小修复：**启动恢复时将残留的未终态标为 `interrupted`，写入“页面重新加载时任务仍在执行；结果可能已部分产生，请先检查地图后再重试。”，设置完成时间并持久化；保留结果图层/摘要等已存字段。历史卡片显示“执行中断，结果待核对”，提供已有的手动重跑操作；新增浅色/深色主题提示样式。没有自动重跑或认定后端操作已停止。
- **验证：**新增测试从 localStorage 恢复 planning、executing 和 success 三类记录，验证前两者转为可重跑的 interrupted、保留潜在产物并持久化，而终态 success 不变。`node --test frontend/tests/task_cancelled_status.test.cjs frontend/tests/chat_send_lifecycle.test.cjs frontend/tests/execution_cards.test.cjs`：46 passed；`node --check frontend/js/task.js` 和目标文件 `git diff --check` 通过。未做浏览器视觉检查或模拟真实网络断开后的后端继续执行行为。
- 前端任务历史脚本、样式和其测试文件在本轮开始前均已是工作区修改；在现有改动上作局部兼容修复。总进度文档及未跟踪的模块清单也属于开始前已有改动；本轮仅追加本项记录，未清理或覆盖其他内容，未提交或推送。

### 2026-10-26 后端任务上下文复用语义核对

- **追踪链路：**前端以当前项目 session_id 调用 `/api/chat/stream`，仅在用户明确引用历史任务时提交 task_id；`graph.run_agent`/`run_agent_stream` 调用 `task_manager.find_or_create_task`，随后绑定到工具上下文。后端任务 `active` 用于同一 GIS 会话跨轮复用工作记忆；前端 localStorage 卡片则按每次聊天请求记录 success/partial/failed/cancelled/interrupted。两者并非同一生命周期。
- **结论：**核对到的“后端 task 长期 active”符合其当前活跃会话上下文用途，代码有明确复用策略；没有证据证明应在每轮普通回复后终结该上下文。主动修改状态转换可能破坏跨轮 GIS 追问，因此本项不改后端状态模型。引用不存在任务时创建独立任务并在上下文中提示引用不可用的边界已有 `test_cartography_reuse.py` 覆盖。
- **验证：**`python -m pytest -p no:cacheprovider -q --tb=short backend/tests/test_task_manager.py backend/tests/test_cartography_reuse.py`：13 passed。该套件是本地确定性测试，不涉及真实 LLM 或服务部署。
- **限制/观察：**前后端状态仍分属不同存储，不能把后端 `active` 展示成某条前端聊天任务的进行中状态；当前 UI 没有显示后端任务生命周期的证据。本次按现状记录，不扩展管理界面。相关任务服务、前端实现和测试在本轮开始前均已有工作区修改；无额外代码改动，没有提交或推送。

### 2026-10-26 工具历史存储异常保护

- **复现问题：**用临时文件写入非完整 JSON，`history_service.list_entries()` 将它当作空历史；随后 `record()` 会把该文件替换成只含新记录的有效 JSON，原始文件字节变化，潜在可恢复的历史被覆盖。历史清空路径也忽略 `_persist()` 是否成功，API 原先始终返回成功，面板会清空显示但磁盘记录可能仍在。
- **最小修复：**文件读取异常（正常的首次运行 FileNotFound 除外）会记录存储警告并暂停普通写入；新执行记录仍保留在当前进程内存中，GIS 工具执行不被历史存储故障阻断，`GET /api/history` 和历史面板展示警告。显式清空允许替换不可读文件，但仅在原子落盘成功时提交清空；失败则恢复内存记录并由 API 返回 HTTP 500，原文件保留。
- **验证：**新增损坏文件逐字节保留、显式清空成功、模拟原子替换失败保留磁盘及内存历史测试；新增 API 警告/清空失败响应和前端警告显示测试。`pytest backend/tests/test_swipe_history.py -k 'corrupt_history or failed_history_clear'`：2 passed；`pytest backend/tests/test_direct_invoke_e2e.py -k corrupt_history_warning_and_failed_clear_response`：1 passed；`node --test frontend/tests/history_race.test.cjs`：3 passed；`py_compile`、`node --check frontend/js/history.js`、目标文件 `git diff --check` 通过。
- **未解决的扩展回归信号：**曾一并运行 `test_swipe_history.py` 与 `test_direct_invoke_e2e.py`，28 passed、2 failed：`test_create_swipe_fuzzy_layer_match` 返回值与断言不符（终端中文显示乱码，根因未定）；`test_e2e_raster_resample_output_real` 期望的 URL 编码 PNG 路径不存在。它们不是本轮历史存储保护的新增测试，未在本模块内盲改；前者留作图层匹配模块检查，后者提示下一轮应查栅格输出交付链。
- **限制：**本轮使用临时损坏/写失败注入和本地 TestClient，不代表真实磁盘损坏恢复或生产部署验证。`history_service.py` 与两个后端测试文件、`history.js`、`history_race.test.cjs` 在本轮开始前无工作区修改；`backend/main.py`、`backend/services/tools.py`、`frontend/css/style.css`、两份验证文档已有改动，本轮在其基础上做了局部兼容修改。未清理、提交或推送其他改动。

### 2026-10-26 栅格重采样产物 HTTP 交付断言校正

- **信号复核：**此前扩展回归的 `test_e2e_raster_resample_output_real` 以 `os.path.exists()` 检查 URL basename。栅格工具对中文预览/源文件名使用百分号编码的 HTTP URL，而磁盘使用 Unicode 文件名，因此旧断言检查了不存在的 `%E9...png` 磁盘路径。
- **验证与处理：**将断言改为 TestClient 实际 GET `dem_result.url` 与 `raster.source_url`，分别检查 HTTP 200 和 `image/png` / `image/tiff` 内容类型。`python -m pytest -p no:cacheprovider -q --tb=short backend/tests/test_direct_invoke_e2e.py`：11 passed；`py_compile` 和目标文件 `git diff --check` 通过。未改栅格生产代码；这属于修正测试对 URL 与文件系统路径概念的混用，不是栅格算法正确性或浏览器渲染验收。
- **边界：**使用本地 FastAPI TestClient 与合成 EPSG:4326 DEM，未调用真实模型、第三方数据服务或浏览器。该测试文件在本轮开始前已有未提交改动，本轮在既有测试上替换了错误断言并加严为 HTTP 交付验证；其他工作区改动未清理、未提交、未推送。

### 2026-10-26 卷帘图层精确匹配与执行历史状态

- **证据区分：**`_resolve_layer_name` 明确只接受已注册的完整图层名称；此前 `test_create_swipe_fuzzy_layer_match` 期待唯一前缀自动匹配，和实际策略不一致。用 `PYTHONUTF8=1` 单独复现后，工具返回了“未找到图层「广州市」，当前图层：广州市_行政区划、佛山市_行政区划”，不是终端乱码；这是过期测试预期，不证明当前精确匹配策略有缺陷。短名失败时不产生 layer op，并返回真实候选名，继续保留以避免多图层误选。
- **已复现缺陷：**`create_swipe` 的缺图层和同图层错误以普通文本返回；`_tool_result_failed` 没有该工具的失败标记，故 `_recorded` 把失败历史写成 `ok=true`。用户查看或重跑历史时会看到错误的成功状态。
- **最小修复：**为 `create_swipe` 增加“未找到图层”和“需要两个不同的图层”失败标记；更新测试验证精确名限制、失败时无卷帘操作，并验证两类错误都记录为失败及错误原因。没有放宽模糊匹配，也没有改变 API。
- **验证：**`python -m pytest -p no:cacheprovider -q --tb=short backend/tests/test_swipe_history.py backend/tests/test_direct_invoke_e2e.py`：31 passed；`py_compile` 与目标文件 `git diff --check` 通过。均为本地自动化，不涉及真实模型或浏览器。
- `backend/services/tools.py` 与 `backend/tests/test_swipe_history.py` 在本轮开始时已有未提交改动；本项在其上做局部修改。未清理、提交或推送其他改动。

### 2026-10-26 属性连接空键与重复键处理

- **调用链：**分析面板 `analysis_tools.js` / Agent 注册工具 → `join_field` → `_layer_to_gdf` → 连接字段、行基数检测 → Pandas merge → `_gdf_to_layer`。此前测试覆盖左右连接、未匹配键、字段冲突，但没有缺失键或重复连接键路径。
- **已复现问题：**新增本地 GeoJSON 用例，左表 2 条空键、右表 3 条空键。旧代码将重复关系格式化成 `many:many`，当前 Pandas 不接受该标签，工具直接返回 merge 错误；将标签改成合法值后，Pandas 校验仍会把左侧重复空键判为非法 1:1 关系，属性连接仍无法成功。该情形应是 2 个未匹配目标行，而不是整个任务失败或被空键彼此配对。
- **最小修复：**基数验证标签改为 Pandas 支持的 `one_to_one` / `many_to_one` / `one_to_many` / `many_to_many`；统计基数时忽略空键，连接前从右侧排除空键，并将左侧每个空键临时设为唯一哨兵以绕过 Pandas 的 null-equals-null 行为，结果写回前恢复为空值。重复的非空键仍按真实一对多/多对多语义连接。
- **验证：**新增空键回归覆盖“0 匹配、2 未匹配、结果行数不增长、关联值均为空”；新增一对多重复非空键回归覆盖 Pandas 校验和预期结果行。`python -m pytest -p no:cacheprovider -q --tb=short backend/tests/test_vector_gap_tools.py`：19 passed；`py_compile` 与目标文件 `git diff --check` 通过。使用本地合成 GeoJSON，无真实用户表格或浏览器/模型验收。
- `backend/services/tools.py` 在本轮开始前已有未提交修改；`backend/tests/test_vector_gap_tools.py` 本轮开始前是干净文件，本轮新增回归。扫描文档本身已有改动；其他工作区状态均保留，无提交或推送。

### 2026-10-26 `spatial_sample` 输入契约

- **调用链：**空间分析面板 `frontend/js/spatial.js` 的选择/采样分支 → `/api/tools/invoke` → `services/tools.py::spatial_sample` → `_layer_to_gdf` / `_gdf_to_layer`。面板提示支持“数量或比例”，后端工具 schema 也同时暴露 `n` 与 `frac`。
- **已确认缺陷：**前端使用 `parseInt/parseFloat(...) || 默认值`，空值、非法文本或 0 会静默替换为 50 个或 0.1 比例；小数比例 1.5 被后端 `min(frac, 1.0)` 静默改成 1，导致采样整层。后端同时接受 `n` 和 `frac` 时优先取 `n`，没有提示参数冲突。以上来自代码路径，原交互不依赖外部服务；新增回归覆盖了修复行为。
- **最小修复：**面板要求输入正整数数量或 (0, 1] 比例，不再静默默认；后端拒绝负数量、负/非有限/大于 1 的比例以及同时提供有效数量和比例的调用。未更改合法随机采样算法；数量超过图层大小仍保持现有“最多采全层”行为。
- **验证：**`python -m pytest -p no:cacheprovider -q --tb=short backend/tests/test_spatial_tools.py -k SpatialSample`：8 passed；`node --test frontend/tests/spatial_fields.test.cjs`：4 passed；`python -m py_compile backend/services/tools.py`、`node --check frontend/js/spatial.js` 与目标文件 `git diff --check` 通过。使用本地合成点图层，没有浏览器真实点击、Agent/模型调用或外部数据验收。
- 本轮开始时 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py`、`frontend/js/spatial.js`、`frontend/tests/spatial_fields.test.cjs`、模块清单和进度台账均已有未提交改动；本项仅在相关文件上作定向修改，其他改动保留，未提交或推送。

### 2026-10-26 空间插值输入对齐与距离单位

- **调用链：**`spatial_interpolate` → `_layer_to_gdf` → 几何/属性样本准备 → IDW/RBF 网格计算 → PNG `dem_result` 地图叠加。此前没有找到该工具的独立验收记录。
- **修复前复现：**在三条有效 Point 和一条空几何记录上，坐标长度为 3、字段值长度为 4，工具以 NumPy shape mismatch 失败；在声明支持的 MultiPoint 输入上，以 `'MultiPoint' object has no attribute 'x'` 失败。原算法还直接以 EPSG:4326 经纬度作 IDW/RBF 平面距离，纬度 60° 经度 0.1° 的水平间距会被当作 0.1 个坐标单位，而非约 5.6 km 地面距离。
- **最小修复：**字段值转为数值，按有效点几何和有限数值共同筛选，先 explode MultiPoint 以保持各点与属性值一一对应；少于 3 个有效观测时给出明确提示。IDW/RBF 网格和观测点均通过中心位置对应的局部 UTM 投影计算距离，同时保留原有经纬度网格范围供地图叠加使用；UTM 适用纬度外明确拒绝。
- **验证：**两个新增几何回归在修复前分别按预期失败（向量形状不一致、MultiPoint 无 x 属性）；修复后完整 `backend/tests/test_spatial_tools.py`：162 passed，另有一条 joblib 物理核心探测警告（回退到逻辑核心）。高纬度测试通过拦截 IDW 输入坐标并验证 0.1° 经度差对应 5,000–6,000 米投影距离。`node --test frontend/tests/spatial_fields.test.cjs`：4 passed；`py_compile` 与目标文件 `git diff --check` 通过。测试使用合成点数据，不涉及浏览器、真实模型或外部数据。
- **剩余边界：**点范围跨越多个 UTM 带、跨日期变更线或覆盖超大区域时，单一局部 UTM 不适用，当前工具没有范围宽度阈值；插值产物仍保存/展示为 PNG 叠加，而非可作为后续栅格计算输入的原始数值栅格。两项作为栅格交付与空间适用范围待审项，不宣称本模块所有场景已闭环。
- `backend/services/tools.py` 和 `backend/tests/test_spatial_tools.py` 在本轮开始前已有未提交修改；本项在相关脏文件内作局部变更，保留其他改动，未提交或推送。

### 2026-10-26 空间插值栅格产物交付

- **调用链复核：**聊天和工具面板共用 `dem_result`；前端 `applyRasterResult` 只有在操作含 `raster` 元数据时才会创建栅格图层，否则仅加地图图片叠加。此前 `spatial_interpolate` 只写 PNG 并发送 bounds，因而没有图层面板注册、原始数值像元、后续栅格工具输入或项目栅格资产链路。对用户而言，插值看似成功，但无法像其他栅格分析产物一样检查和继续工作。
- **最小修复：**沿用既有 `_raster_preview_op`，将插值数组保存为 EPSG:4326 单波段 Float32 GeoTIFF（北向上 transform），由既有 helper 生成预览、注册原始 TIFF、返回 `dem_result` 栅格元数据和项目资产所需 URLs。继承原始点图层名；字段单位未知时不伪造单位，并将“样本外接范围外推需谨慎”作为质量提示持久化。复用现有栅格工具和工程保存机制，无新增依赖或新格式。
- **验证：**新 HTTP 级回归修复前失败（`dem_result` 缺少 `raster`）；修复后 `backend/tests/test_direct_invoke_e2e.py`：12 passed。插值用例请求预览 PNG 和 TIFF URL，读取返回 TIFF 验证 CRS、16×16 像元、值范围、像元单位及外推提示，并将该输出作为 `raster_resample` 输入再次成功分析。`backend/tests/test_project_raster_persistence.py`：16 passed，验证既有通用栅格项目保存/导入/恢复路径；该套件没有专门保存本插值输出。`py_compile` 与目标文件 `git diff --check` 通过。未在浏览器内执行插值产物保存/重开验收，也未调用真实模型或外部数据。
- **剩余边界：**单一 UTM 距离方案对跨多个 UTM 带、跨日期变更线或大范围样本不适用；当前尚无经验证的范围阈值。空间插值的分辨率与点数组合也尚未建立资源上限。插值导出栅格 CRS 为 EPSG:4326，像元空间单位为 degree；属性值单位保持未知。
- 本轮开始时 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py`、`backend/tests/test_direct_invoke_e2e.py` 及两份扫描文档已有未提交改动；只在相关文件上做局部修改，保留其他脏工作区内容，未提交或推送。

### 2026-10-26 插值栅格工程保存、重载与再分析

- **目标链路：**在 `spatial_interpolate` 已返回带 TIFF 来源 URL 的栅格图层后，验证项目服务能否把真实插值 GeoTIFF 和预览一同纳入工程资产，加载工程后重新注册 TIFF，并把恢复结果交给后续栅格工具。
- **验证：**新增 `test_interpolation_raster_survives_project_save_load_and_reanalysis`，使用合成点图层生成 16×16 插值栅格，通过 `project_service.save_project` 保存、`load_project` 恢复，再以恢复层调用 `raster_resample`。测试确认 CRS、未知值单位、外推质量提示在工程元数据中保留；项目预览 URL 与原始 TIFF URL 均 HTTP 200，重载后的 TIFF 可再次分析。`backend/tests/test_project_raster_persistence.py`：17 passed；`backend/tests/test_direct_invoke_e2e.py`：12 passed；`py_compile` 和目标文件 `git diff --check` 通过。
- **验证边界：**这证明本地后端项目服务及资源恢复路径，不是浏览器工程列表打开/图层面板显示的完整 UI 验收；未调用真实模型或外部数据。栅格的 CRS 是 EPSG:4326（像元空间单位 degree），点字段没有单位元数据时保持 unknown。
- 本轮开始时 `backend/tests/test_project_raster_persistence.py` 与模块台账已有未提交改动；测试仅追加独立场景，文档追加本项结论，其他既有改动均保留，未提交或推送。

### 2026-10-26 插值空间范围与计算资源边界

- **代码证据：**`spatial_interpolate` 原先无 `resolution` 上限，先分配二维网格，再一次性构造大小为 `resolution² × 有效样本数` 的 IDW 距离矩阵；RBF 同样对全部网格批量求值，且拟合矩阵随样本数平方增长。用户或模型传入极大值可能导致请求长时间占用或进程内存耗尽。单一局部 UTM 用于超大经度范围也不能可靠代表局部距离；日期变更线数据以普通 GeoJSON 经度最小/最大值处理会形成近全球包络。
- **最小保护：**限制 resolution 在 2–1024，限制单次网格-样本距离计算总量为 5,000 万对，RBF 有效样本上限 500；IDW 与 RBF 网格计算按最多约 100 万对分批，避免一次性保留整个计算矩阵。检查扩展后的经度包络超过 6° 时要求分区，并拒绝超出 UTM 适用纬度的输入。6° 采用一个 UTM 分带的宽度作为初始边界；目前不是硬件性能基准。
- **验证：**新增回归覆盖分辨率边界、宽范围拒绝、超预算提前拒绝、IDW 最大批量、RBF 求值和大样本 RBF 拒绝。当前完整 `backend/tests/test_spatial_tools.py`：169 passed，1 条 joblib 物理核心探测警告并回退逻辑核心；`backend/tests/test_direct_invoke_e2e.py`：12 passed；`backend/tests/test_project_raster_persistence.py`：17 passed。语法检查与目标文件 `git diff --check` 通过。
- **剩余风险：**6° 内但跨 UTM 分带的范围仍可运行，误差没有通过高精度基准量化；50,000,000 距离对、1024 分辨率、500 个 RBF 点是保守初始限值，尚无多硬件性能/峰值内存基准。真实浏览器插值图层保存/恢复仍未验收，测试都使用本地合成数据，无模型、第三方服务或外部数据调用。
- 本轮开始时 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py`、`backend/tests/test_project_raster_persistence.py` 及两份扫描文档均已有未提交改动；只在相关脏文件内作定向修改/追加，未清理、提交或推送其他工作。

### 2026-10-26 栅格计算器非有限像元处理

- **调用链：**`raster_calculator` → `_find_uploaded_tif` → 按波段读取数组 → AST 白名单校验与无内建函数 eval → GeoTIFF 及 PNG 预览 → `_raster_preview_op` 注册和项目资源交付。
- **已复现缺陷：**用含零除数的两波段 GeoTIFF 执行 `B1/B2`，原行为在 NumPy 浮点警告路径触发空内建环境的 `KeyError('__import__')`，将常见栅格除零错误呈现成不相关的内部错误。浮点溢出/无效运算也可能生成 Inf；原代码只把 NaN 当预览无效像元，且未在源 GeoTIFF 中将 Inf 转成 NoData，造成地图外观与后续计算值语义不一致。
- **最小修复：**仅在受限表达式计算时使用 `np.errstate(all="ignore")`，不启用 Python 内建函数；将结果复制为浮点数组并把 NaN、正负 Inf 统一规范为 NaN。原有全 NaN 检查随后给出明确无产物提示；部分无效时 GeoTIFF 写入 NaN NoData，预览将无效像元渲染为黑色，质量比率继续由通用栅格 helper 计算。
- **验证：**新增含 1 个零除像元的 20×20 两波段 TIFF 回归。修复前测试失败并复现 `KeyError('__import__')`；修复后确认计算成功、该像元在 TIFF 中为 NaN、有效像元保持有限数值且 NoData 为 NaN，PNG 对应像元为黑色。当前完整 `backend/tests/test_spatial_tools.py`：170 passed（1 条 joblib 物理核心检测警告，回退逻辑核心）；`backend/tests/test_direct_invoke_e2e.py`：12 passed；`backend/tests/test_project_raster_persistence.py`：17 passed。语法检查与目标文件 `git diff --check` 通过。
- **剩余边界：**测试验证了局部运算与已有注册/持久化邻接路径，未用大尺寸真实栅格、浏览器、真实模型或外部数据验收。全波段读取仍是整幅数组处理，大文件内存边界需单独审查；表达式输出的物理值单位依赖输入字段和表达式，仍明确标作未推导。
- 本轮开始时 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py` 与模块文档已有未提交改动；本项仅作关联位置定向修改/追加，没有清理、提交或推送其他工作区改动。

### 2026-10-26 栅格计算器整幅输入内存边界

- **代码证据：**`/api/upload` 允许 GeoTIFF 最大 300 MiB；`raster_calculator` 在每次调用中对所有波段直接 `read(i).astype(float64)`，之后还有表达式结果、归一化、RGBA/RGB 预览及 GeoTIFF 写出数组。此前未见像元数或波段像元数限制。压缩 TIFF 文件大小不能反映解压后的数组内存，用户上传可被接受的高维/多波段文件时，执行可能消耗远超压缩文件大小的内存。
- **最小保护：**读取任何波段前检查 `width × height ≤ 4,000,000` 且 `width × height × band_count ≤ 16,000,000`，超限时返回包含影像尺寸、波段数及裁剪/重采样建议的错误。没有改变已有上传上限、表达式 API 或其它栅格工具；此为当前整幅内存算法的原型保护阈值，不声称是实测硬件最优值。
- **验证：**新增元数据代理测试分别覆盖总像元和波段像元预算；代理的 `read()` 若被调用会立即失败，因此验证了拒绝发生在波段数组读取前。`backend/tests/test_spatial_tools.py`：172 passed（1 条 joblib 核心数检测警告，回退逻辑核心）；`backend/tests/test_direct_invoke_e2e.py`：12 passed；`backend/tests/test_project_raster_persistence.py`：17 passed。语法检查及目标文件 `git diff --check` 通过。边界测试是代理数据；正常结果流程由真实小型 GeoTIFF HTTP E2E 覆盖，不等于大栅格性能实测。
- **剩余边界：**具体阈值未在不同内存设备基准测试；4 百万像元输入仍有预览和多波段处理的峰值开销。超限情况下目前要求用户先裁剪或重采样，尚未实现窗口化计算。真实大栅格、浏览器提示和真实模型选择该错误恢复方案均未验证。
- 本轮开始时 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py`、模块清单和扫描台账已有未提交改动；仅在相关脏文件上局部修复和追加记录，其他改动保留，未提交或推送。

### 2026-10-26 水文分析距离与栅格结果交付

- **已确认问题：**`hydrology_analysis` 的 D8 坡降比较此前将水平、垂直和对角邻居距离固定按 1/1.414 像元计，未读取栅格仿射变换或 CRS。经纬度 DEM 在不同纬度下东西向地面距离不同，因此可选错最陡流向。另一个交付断点是工具只发 PNG 叠加事件，没有注册原始分析栅格；结果不能进入现有栅格图层面板、工程保存/恢复和后续栅格工具链。
- **最小修复：**投影 CRS 按仿射像元向量与 CRS 线性单位换算距离；地理 CRS 用 CRS 对应椭球的 geodesic 距离（北向栅格按行预计算，旋转栅格按像元计算）；无 CRS 或不支持的 CRS 明确失败。流向、汇流累积和河网输出统一复用 `_raster_preview_op`，保存带 CRS、NoData、处理说明、来源/值单位和质量提示的 GeoTIFF，并注册地图预览及可继续使用的 Raster 图层。重复输出采用新名称，避免覆盖已有 TIFF/PNG。
- **验证：**新增 3×3 EPSG:4326 合成 DEM 测试：59.5°N 下比较 6 高程单位/向东与 8/向北，验证按地面距离后中心像元选择向东；另验证无 CRS 输入拒绝、流向输出的 GeoTIFF CRS/NoData/处理标签、来源与单位元数据、进入图层注册、可被栅格重分类工具继续使用，以及 flowacc/streamnet 也会注册栅格。`backend/tests/test_spatial_tools.py`：174 passed（1 条 joblib 物理核心探测警告并回退）；`backend/tests/test_project_raster_persistence.py backend/tests/test_raster_provenance.py`：18 passed；`py_compile` 与目标文件 `git diff --check` 通过。
- **未验证边界：**仅使用合成小栅格和本地自动化；未用真实 DEM/外部水文基准比较 sink filling、流向或河网准确性，未进行水文分析的浏览器保存并重开验收，也未调用真实模型。当前迭代 sink-filling 与 D8 算法仍属简化实现；质量提示对此作了明确限定。此前工作区中的 `backend/services/tools.py`、`backend/tests/test_spatial_tools.py`、扫描台账和模块清单均已有修改；本轮只在这些脏文件的相关位置追加，不清理、提交或推送其他改动。

### 2026-10-26 栅格重分类参数边界

- **代码确认的问题：**`raster_reclassify` 的说明要求 `classes` 至少为 2，但等间距/分位方法使用 `max(2, int(classes))`，会把 1、0、负数静默变成 2 级并返回成功。`method` 未知时会落入 mapping 分支；当调用方同时传入 mapping，方法拼写错误会静默执行另一种分析。映射解析允许 `nan`/`inf` 类别值和空区间，结果可能无有效分类像元但仍返回完成。
- **最小修复：**只接受列明的 method（保留原有别名）；等间距和分位方法要求有限、整数且 ≥2 的 classes；mapping 输出值要求有限，区间需有效非空。无效参数在写出或注册结果前返回错误，不改有效分类公式、既有调用格式或重分类产物命名。
- **验证：**新增整数下界、Pydantic 对非整数/非有限数的 schema 拒绝、未知方法、不有限映射值和空区间回归。`backend/tests/test_raster_gap_tools.py`：40 passed；`backend/tests/test_project_raster_persistence.py backend/tests/test_raster_provenance.py`：18 passed；`py_compile` 与相关文件 `git diff --check` 通过。测试为本地合成栅格；既有浏览器五分位重分类与工程恢复记录仍是独立的先前验收证据，不将本轮边界测试称为浏览器复验。
- **剩余边界：**未在本轮重复真实 DEM 浏览器保存/重开；也未重新做外部地形业务阈值验证。本轮开始时 `tools.py`、栅格测试及验证文档已有修改；仅在关联位置局部调整，没有清理、提交或推送其他改动。

### 2026-10-26 焦点统计 NoData 与窗口参数

- **已复现问题：**`raster_focal_stats` 将像元与 GeoTIFF 的 NoData 哨兵用 `np.isclose` 比较。输入 NoData=-9999 且合法值为 -9998.95 时，该合法像元被当作缺失，焦点均值从“使用两个有效像元”变为仅使用中心值；共享 `_raster_preview_op` 也会将接近哨兵的有效结果从有效像元统计中剔除。另有代码证据：窗口 1、9、负奇数会静默夹到 3 或 7；恢复工程图层的源 TIFF 若以内容哈希命名，焦点结果会沿用哈希文件名。
- **最小修复：**焦点统计与共享预览 helper 对 NoData 改为与明确哨兵值精确比较；窗口只接受 3/5/7，不再静默夹值（偶数仍由已有工具参数守卫向上调整并产生提示）；majority 仍按 6 位小数聚合近似类别，但输出该组中实际存在的代表值，不再输出舍入后可能不存在的像元值；结果名改用注册图层显示名。
- **验证：**回归覆盖 NoData=-9999 时保留 -9998.95 并正确报告 2/9 有效像元、majority 输出精确保留常量源值、窗口 1/9/-1 拒绝且不产出结果、哈希路径映射到可读图层名的注册情形，以及既有窗口和统计检查。`backend/tests/test_raster_gap_tools.py`：46 passed；`backend/tests/test_project_raster_persistence.py backend/tests/test_raster_provenance.py`：18 passed；`py_compile` 和相关 `git diff --check` 通过。
- **剩余边界：**NoData 修复触及所有栅格预览统计路径，但本轮回归集中在焦点统计及既有栅格来源/持久化用例；未逐一对每个栅格工具做近似 NoData 哨兵组合测试。未在本轮运行浏览器或真实 DEM 焦点分析。工作区开始时相关工具、测试和扫描文档均已有未提交改动；本轮仅在这些文件相关位置修改，没有清理、提交或推送其他改动。
- **测试隔离问题及处理：**扩展联测先发现 `test_dem_analysis.py`、`test_dem_providers.py`、`test_hydrology.py`、`test_raster_gap_tools.py` 会改写共享 `T._temp_output_dir` 却不恢复，导致后续 Direct Invoke 的静态产物请求 404；单独复跑 Direct Invoke 用例通过，确认是测试顺序污染而非栅格 helper 的 HTTP 回归。四个模块的 autouse fixture 现恢复原目录；`test_hydrology.py` 的工具输入同步改用有效 EPSG:4326 CRS，以符合工具目前明确要求。组合运行这 8 个栅格/持久化/工具参数测试文件：159 passed。此为自动化集成证据，不是浏览器或真实服务验收。

### 2026-10-26 欧氏距离源像元与栅格结果命名

- **代码确认的问题：**`euclidean_distance` 对 NoData 使用 `np.isclose`，会将 -9999 附近合法像元 -9998.95 排除，甚至拒绝把它识别为用户指定源；源值选择也使用默认相对容差，例如 float32 像元 1,000,005 在指定源值 1,000,000 时会被当作同一源像元，影响最近源距离。恢复工程中 TIFF 路径若为内容哈希，默认产物名原先也沿用哈希基名，不利于图层面板、导出和继续分析时识别结果。新增的数值回归场景覆盖这些触发条件并验证修复结果。
- **最小修复：**NoData 按 GeoTIFF 指定哨兵精确比较；浮点输入的 source_value 先转换到栅格存储类型，再做精确值匹配，整数输入保留直接数值比较；默认结果名使用注册图层名，显式 `out_name` 仍按原行为优先。CRS/单位、斜切网格拒绝和 EDT 算法均未改变。
- **验证：**新增测试覆盖近似 NoData 有效像元可作为源并保留 2/9 有效比例；1,000,000 与 1,000,005 只选中前者；哈希路径注册图层按显示名生成并注册输出。栅格与相邻工程组合套件：`test_dem_analysis.py`, `test_dem_providers.py`, `test_hydrology.py`, `test_raster_gap_tools.py`, `test_direct_invoke_e2e.py`, `test_project_raster_persistence.py`, `test_raster_provenance.py`, `test_tool_args_guard.py` 合计 162 passed。`py_compile` 与目标文件 `git diff --check` 通过。
- **未验证边界：**本轮未重跑浏览器或真实 DEM 距离分析；投影距离仍是投影平面距离，不等价于所有投影下的地面距离；经纬度 CRS 继续明确拒绝，需用户先重投影。工作区中的工具、栅格测试和扫描文档起初已有改动；没有清理、提交或推送。

### 2026-10-26 栅格掩膜提取 CRS 与 NoData

- **代码确认的问题：**源栅格未声明 NoData 时，工具固定用 `-9999` 同时编码掩膜外区域；如果有效输入像元刚好为 -9999，输出无法再区分该有效值和被掩膜像元。对已声明 NoData 的近似合法值又用 `np.isclose` 判断，可能被计为缺失。几何转换异常会被吞掉并回退到原坐标；源栅格缺 CRS 时这可能将 WGS-84 面坐标直接应用到未知坐标网格。默认结果名也从源 TIFF basename 生成，工程资产哈希路径会泄漏到结果名。
- **最小修复：**使用 `rasterio.mask` 的 masked-array 结果显式保留像元掩膜；输入无 NoData 时输出 NaN 哨兵，避免与合法数值冲突；有效像元统计按 NaN/精确哨兵判断；对缺失 CRS 与失败的坐标转换明确失败，不再把原几何静默套用；默认结果名使用已注册图层名称。掩膜仍在原始行列范围输出，未改变像元中心/all-touched 规则。
- **验证：**新增用例验证无 NoData 输入中的合法 -9999 被保留且输出 NoData 为 NaN；已声明 NoData=-9999 时合法 -9998.95 保留并计入有效像元；WGS-84 掩膜正确转换到 EPSG:3857 栅格并保留其 CRS；注册图层结果名称可读；无 CRS 输入拒绝且不产物。8 个栅格、持久化、来源和参数测试文件组合：167 passed；`py_compile` 与相关 `git diff --check` 通过。均为本地合成数据/自动化测试，不代表浏览器或真实 DEM 验收。
- **剩余边界：**未在浏览器或真实工程中复跑掩膜分析及保存恢复；输入矢量图层当前由 `_layer_to_gdf` 按 GeoJSON 规则解释为 EPSG:4326，未覆盖其他矢量上传/注册格式。工作区中的相关工具、测试和文档在本轮开始前均已有改动；本轮只改相关位置，没有清理、提交或推送。

### 2026-10-26 栅格转矢量 CRS、NoData 与参数校验

- **已确认问题：**`raster_to_feature` 原先在源 GeoTIFF 缺 CRS 时伪装指定 EPSG:4326，导致矢量化结果坐标含义被错误确定；用 `np.isclose` 排除 NoData 会把 -9999 附近的合法值（如 -9998.95）当作缺失；非法连通度（如 6）被静默改成 8 邻域，结果与用户请求不一致。简化参数原说明固定为“度”，但实际 Shapely 容差使用输入栅格 CRS 的坐标单位，投影栅格上文案会误导。
- **最小修复：**缺少 CRS 时停止矢量化并给出定义坐标系提示；NoData 使用精确哨兵比较；连通度只接受 4/8，非法值明确报错；简化容差要求有限且非负，说明改为“与栅格 CRS 坐标单位一致”；结果面积单位修正为 km²。
- **验证：**新增合成 GeoTIFF 测试覆盖无 CRS 拒绝且不注册产物、合法近 NoData 值仍保留为面、非法连通度 0/6 和非法简化 -1/NaN/Inf 拒绝。`backend/tests/test_raster_gap_tools.py`：61 passed；`py_compile backend/services/tools.py` 和针对本次文件的 `git diff --check` 通过。pytest 有一条缓存目录权限警告，不影响测试结果。
- **未验证边界：**没有用真实带 CRS 的 DEM、浏览器或已保存工程执行“转矢量→图层面板→再次分析→保存→重开”；本轮未评估超大栅格多边形数量的内存峰值、不同投影下简化效果或外部 DEM 业务正确性。测试使用本地合成栅格，不代表真实数据验收。工作区中工具、栅格测试和扫描记录均在本轮开始前已有修改；本次只在相关文件定向追加，没有清理、提交或推送。

### 2026-10-26 填挖方 NoData 与差值产物

- **已复现问题：**`surface_volumes` 对输入 NoData 使用 `np.isclose`，把 -9999 邻近合法高程 -9998.95 排除，受控 5×5 用例中因此少算 10,000.95 m³ 填方且少计一个像元。差值栅格沿用输入高程 NoData 哨兵；当输入 NoData=0 时，未变化像元的合法差值 0 会在输出 TIFF 被标为 NoData，地图/下游栅格工具读不到完整的变化面。
- **最小修复：**输入 NoData 按精确哨兵比较；差值产品使用 NaN NoData，与输入 DEM 的 NoData 编码解耦，保留合法零高差像元。
- **验证：**新增测试验证近 NoData 高程参与正确填挖计算、输出差值为 10000.95 m³等价像元差，以及源 NoData=0 时差值输出仍保留 25 个有效像元和 24 个合法零差值。`backend/tests/test_raster_gap_tools.py`：63 passed；`py_compile backend/services/tools.py` 与相关 `git diff --check` 通过。pytest 报缓存目录权限警告，不影响结果。
- **未验证边界：**局部合成栅格测试没有覆盖真实工程 DEM、数据垂直基准/测量误差、工程保存后浏览器恢复或大栅格内存表现；高程单位未知时现有实现仍按米解释并给出质量警告，不构成自动单位识别保证。工作区相关文件在本轮开始前已有改动；本次仅在其关联函数、测试和进度文档处定向修改/追加，没有清理、提交或推送。

### 2026-10-26 矢量转栅格像元网格边界

- **已确认问题：**`feature_to_raster` 对单点图层使用自动像元尺寸时无范围可推导；显式像元尺寸虽能绕过报错，但原 `from_bounds` 会产生 0 宽/高地理变换，结果不能形成有效点像元。任意小的正 `cell_size` 还可构造极大 `width × height` 并在 `rasterize` 分配数组前耗尽进程内存；负像元尺寸原先被当作自动模式静默忽略。原 `from_bounds` 以取整宽高重新拉伸输入边界，实际像元尺寸可能与回复声明的 cell_size 不符。
- **最小修复：**要求 `cell_size` 有限且非负；当某一维范围为零时围绕几何中心扩展半个像元，使用明确像元尺寸构造 Affine 网格并向上取整覆盖输入范围；栅格化前限制单次输出不超过 400 万像元，超限提示增大像元或裁剪范围。
- **验证：**新增单点图层测试验证显式 cell_size 产生 1×1 非零分辨率栅格且点落在像元中心；另测试极小像元请求在栅格化前拒绝、负尺寸拒绝。`backend/tests/test_coverage_gap.py`：34 passed。与栅格分析回归组合运行 `test_raster_gap_tools.py test_coverage_gap.py`：97 passed；`py_compile` 与相关 `git diff --check` 通过。pytest 有一条缓存目录权限警告，不影响测试结果。
- **未验证边界：**当前阈值沿用栅格计算器的 400 万像元保护值，未进行不同设备的内存基准；本地测试未验证大型/复杂几何烧录性能、浏览器显示、真实 GIS 对齐工作流或带 CRS 原始上传数据。相关工具与测试文件在本轮开始前已有修改；本次仅定向修改，无文件清理、提交或推送。

### 2026-10-26 创建渔网参数与规模上限

- **代码确认问题：**`create_fishnet` 将给定 cell_size 用 ceil 转为行列数后按范围均分网格，因此真实格尺寸可能小于请求值；成功信息却回报请求 cell_size。rows/cols 或小 cell_size 可让代码构造无上限的 Shapely 面要素列表，任务可拖垮单用户服务进程。负/非有限 cell_size 在同时传行列数时还可能被静默忽略。
- **最小修复：**cell_size 必须有限且非负；网格要素构造前限制最多 10000 格，并提示增大 cell_size 或缩小范围；回复改为展示 ceil 后真实的横纵格宽。此上限是原型资源保护值，未做设备基准。
- **验证：**新增测试验证 10000 格以上请求在产物注册前拒绝、负尺寸不会被 rows/cols 掩盖、2×2 范围与 cell_size=0.6 时创建 4×4 格并报告实际 0.5×0.5 格宽。`backend/tests/test_coverage_gap.py`：37 passed；与 `test_raster_gap_tools.py` 组合回归：100 passed；`py_compile` 和相关 `git diff --check` 通过。pytest 有一条缓存目录权限警告，不影响结果。
- **未验证边界：**没有浏览器 UI、真实业务范围或高要素渔网性能测试；10000 格阈值需在目标设备实测后再评估。文件在本轮开始前已有工作区修改；本次只定向修改工具与测试，并更新审查记录。

### 2026-10-26 栅格代价距离与最小成本路径 CRS/规模

- **已复现问题：**`_layer_to_gdf` 返回 EPSG:4326，但 `cost_distance` 直接把源几何烧录到栅格变换上，`least_cost_path` 也直接用经纬度吸附栅格像元；在北京附近 EPSG:3857 合成栅格上，正确源点坐标与投影网格不在同一数值空间。路径吸附用 `int()` 对负分数向零截断，导致栅格左/上边界外的点可能错误吸到第 0 行/列。两函数将近似 NoData 值误删；代价距离自定义输出名原样拼接文件路径。稀疏图和多源 predecessor 矩阵也没有像元规模保护。
- **最小修复：**要求代价栅格 CRS 已定义，并把源/目的图层转到栅格 CRS 再栅格化/吸附；吸附索引改用 floor；NoData 精确匹配；cost-distance 输出名经既有安全文件名 helper 规范化，并由栅格输出目录 helper 建目录；栅格总像元限制 100 万、有效代价节点限制 10 万、最小路径源数×节点矩阵限制 400 万项，超限明确建议裁剪/重采样/减少源点。
- **验证：**EPSG:3857 合成栅格与 WGS-84 源/终点测试验证代价面可达 9/9、路径可达且注册图层正确；NoData=10000 时合法值 9999.95 保持可达；边界外源点不再被吸附；输出名 `../../outside` 被限制在 uploads 目录；新增图规模保护测试。`test_raster_gap_tools.py` 与 `test_coverage_gap.py` 组合：105 passed；`py_compile` 与相关 `git diff --check` 通过。
- **未验证边界：**测试为小型合成 EPSG:3857 表面，没有真实阻力面基准、浏览器交互或跨投影生产数据。算法按 D8 邻域像素距离加权，结果量纲是“代价值×像元距离”，并非自动折算的地面距离；10 万节点/100 万栅格/400 万 predecessor 项阈值未经不同设备内存和运行时基准调优。测试输出的路径长度因隔离用例禁用 UTM 估算而显示 NaN，不以该字段声称单位长度验收通过。工作区对应工具、测试和台账原本已有修改；本轮定向更改这些相关脏文件，没有清理、提交或推送。

### 2026-10-26 空间连接保留输入属性字段

- **已复现问题：**`spatial_join` 直接调用 `geopandas.sjoin`。当任意输入属性字段已命名为内部索引列 `index_right` 时，连接稳定失败并返回 `'index_right' cannot be a column name in the frames being joined`，导致常见字段名数据无法完成核心连接任务。
- **最小修复：**执行 sjoin 前，仅当输入含冲突字段时，将目标和连接图层各自的 `index_right` 属性列改名为无冲突的 `index_right_target` / `index_right_join`（若名字也被占用则追加编号），保留原属性值，并让 GeoPandas 在输出中继续生成内部 `index_right` 结果列。
- **验证：**新回归同时让双方输入都带原 `index_right` 属性；修复前失败，修复后验证连接成功且两边原值分别保存在重命名字段中。`test_spatial_tools.py`、`test_raster_gap_tools.py`、`test_coverage_gap.py` 组合：280 passed；`py_compile` 与相关 `git diff --check` 通过。pytest 仅有 joblib 核心数检测回退和缓存目录权限两条警告。
- **未验证边界：**本地 GeoJSON/小型几何测试未覆盖大图层 sjoin 内存、复杂字段编码、浏览器属性表展示或真实业务数据。工作区相关服务、测试和进度文档在本轮开始前已有修改；本轮只在相应函数与测试处局部改动，保留其他变更且未提交/推送。

### 2026-10-26 混合几何类型矢量叠置

- **已复现问题：**`spatial_intersect` / `spatial_union` 调用 `geopandas.overlay` 时使用默认 `keep_geom_type=True`。用面与穿越该面的线相交，GeoPandas 明确警告丢弃 1 个异类型几何，工具随后误报“没有重叠区域”；面与线 union 也可能丢弃线部分。此行为会静默丢失合法交集/并集结果。
- **最小修复：**相交（快路径与分批路径）和并集显式用 `keep_geom_type=False` 保留跨几何维度结果；相交、差异和裁剪仅在结果全为面要素时计算/展示面积百分比，避免线结果被错误描述为 0 平方千米。
- **验证：**新增面×线测试验证 intersection 输出 LineString 并保留双方属性，union 输出保留线属性；修复前 intersection 回归失败并捕获 GeoPandas 的异类型丢弃警告，修复后通过。`test_spatial_tools.py` + `test_spatial_robust.py`：188 passed。警告含 joblib 物理核心检测回退、测试里既有直接调用默认 overlay 的异类型过滤提示（3 条）及 pytest cache 权限提示；无失败。
- **本模块观察：**`spatial_robust.chunked_overlay` 的已有测试验证全量对照面积、无重复几何、difference 跨批只处理一次，以及所有批次失败时显式 raise；对部分批次失败，工具回复会报告跳过数量，不会伪称全部成功。本轮未更改这部分行为。
- **未验证边界：**合成小型 GeoJSON 测试未验证多种几何类型组合的真实业务语义、浏览器混合几何渲染、大规模 overlay 内存或外部数据。工作区相关源文件/测试/扫描记录在本轮开始前已有修改；只在当前相关处局部更改，没有清理、提交或推送。

### 2026-10-26 最近设施部分结果诊断展示

- **代码确认问题：**网络求解服务已返回未吸附与路网不可达设施的序号，但 `network.js` 的结果面板只显示成功路径；部分成功时用户看不到被省略的设施，全部失败时也只显示笼统错误而丢失诊断。成功摘要将后端 0 起始 `facility_idx` 原样显示为“设施0”，与同一界面从 1 起始的诊断序号不一致。
- **最小修复：**前端把成功摘要转成从 1 起始的人类序号；部分成功时在结果区说明未纳入结果的设施序号，全部失败时将吸附/连通诊断追加到错误状态。没有改动求解算法或后端 API。
- **验证：**`node --test frontend/tests/network_request_lifecycle.test.cjs`：5 passed；`python -m pytest -p no:cacheprovider -q --tb=short backend/tests/test_network.py`：14 passed。回归覆盖部分结果、全部失败诊断和序号映射。
- **未验证边界：**此次没有浏览器人工验收，也未访问真实道路或外部路网服务；自动化验证通过前后端受控数据确认服务到 UI 的字段呈现。`frontend/js/network.js` 与 `docs/validation/module-scan-progress.md` 在本轮开始前已有工作区修改，本轮只在最近设施结果展示及台账末尾局部编辑；`frontend/tests/network_request_lifecycle.test.cjs` 为本轮新增用例。未清理、提交或推送。

### 2026-10-26 工程 ZIP 导入容量边界

- **已确认风险：**`main.py` 将上传工程流交给 `project_service.import_project`；工程服务先做路径穿越校验，但随后对 `ZipInfo` 列表无数量/解压字节限制地 `extractall`。压缩包大小同样没有在解包前限制。构造的高压缩比或海量条目工程可能占满临时/工程磁盘空间或消耗过多解包资源；这是代码路径确认的资源耗尽风险，未在真实磁盘上执行破坏性压测。
- **最小修复：**工程导入在 ASGI 请求接收阶段限制请求体为 1 GiB 工程包加 1 MiB multipart 开销，先检查 `Content-Length`，并对无长度/分块请求按实际接收字节计数；之后工程服务再次限制 ZIP 压缩包不超过 1 GiB、最多 10000 个条目、声明的累计解压数据不超过 1 GiB。超限请求返回 413；解包超限沿用既有清理路径移除本次暂存工程，并由 API 返回 400。不改 `.giswork` 格式，也不动工程导出内容。
- **容量取舍：**这是单机原型的初始保护阈值，留出多栅格工程空间；尚未按目标设备磁盘、解包耗时或真实大工程样本进行基准，超过 1 GiB 的合法工程会被拒绝，后续应依据真实样本再调整。
- **验证：**新增回归把限额压低，确认请求声明超限和无 `Content-Length` 的分块超限均在上传解析前返回 413；并确认超 ZIP 条目、解压数据与压缩包在工程导入时被拒绝且不留下工程目录/索引记录。`python -m pytest -p no:cacheprovider -q --tb=short backend/tests/test_layer_group_persistence.py backend/tests/test_project_raster_persistence.py`：51 passed；`python -m py_compile backend/main.py backend/services/project_service.py` 与目标文件 `git diff --check` 通过。正常工程/栅格资产导入、保存测试在此批次通过。
- **未验证边界：**未对真实大型 `.giswork`、压缩炸弹高 CPU、接近 1 GiB 的请求耗时/磁盘峰值或低磁盘空间恢复进行压力/浏览器验收。请求可在限制内占用最多约 1 GiB 临时上传空间及解包空间；该上限是原型保护，不构成公开部署的资源隔离保证。`main.py`、`project_service.py`、`test_layer_group_persistence.py` 和两份验证文档在本轮开始前已是脏/未跟踪工作；本次仅在工程导入边界、对应回归及同一模块文档处局部更改，保留其他现有改动，没有清理、提交或推送。

### 上传完成交接与注册生命周期（2026-10-26）

- **代码确认：**上传 API 成功注册图层后，前端还要把预览/数据交给地图和图层面板。地图加载或图层面板入库失败时，旧逻辑没有回滚已插入的本地预览或后台注册；重试可能遗留重复或孤立图层。
- **代码确认：**矢量上传通过 `layers.addLayer` 桥接到共享 `GIS.state`；删除时面板记录负责按 `_registrationTokens` 注销后台注册。上传令牌此前只赋给桥接返回的状态记录，面板记录没有令牌，可能导致删除无法按上传版本注销。
- **本轮修改：**在地图/面板交接未完成时清理部分本地图层并用服务端返回的注册令牌注销后台图层；成功后把注册名和版本令牌同步到状态记录与面板记录。保留当前上传、取消及既有注册机制，没有改动GIS分析逻辑。
- **验证：**`node --test frontend/tests/upload_preview.test.cjs`：16 passed；前端全量 `node --test frontend/tests/*.test.cjs`：257 passed。后端全量 `python -m pytest -p no:cacheprovider -q --tb=short backend/tests` 最终复跑：1432 passed、1 skipped、18 warnings；其中有 Rasterio Windows 日志回调 `UnicodeDecodeError` 非致命警告，测试进程仍返回成功。`node --check frontend/js/upload.js`、涉及 Python 测试的 `py_compile` 与目标文件 `git diff --check` 通过。
- **浏览器验收：**使用已保存的“小范围 DEM 往返验收”工程。数据源为 AWS Terrain Tiles（SRTM-derived），原始 DEM 为 EPSG:4326、59×67 像元，检查可见高程单位 m 和来源/质量提示；已有坡度、坡向和五级分位重分类图层。刷新后从“最近工程”重新打开，确认 4 个栅格图层恢复；再从恢复的原始 DEM 运行坡度分析，结果回到图层列表并显示 EPSG:4326、degree 值单位、93.73% 有效像元和经纬度栅格的距离换算提示；再次保存、刷新和重开后仍恢复 4 图层及坡度图层元数据。浏览器当前项目为本地验收工程，没有改动原有业务工程。
- **未验证边界：**没有用外部高程基准或业务阈值验证地形算法适用性；本次只覆盖小范围样例。没有重新验证真实模型、在线数据服务失败恢复、3D 浏览器渲染和公开部署安全边界。仓库中大量文件在本轮开始前已是未提交/未跟踪状态；本轮保留这些状态，没有清理、提交或推送。

### 2026-10-26 初始分支回归复核与 Python 执行边界（后续回归见文末）

- 当前工作区基线：`main` 与 `origin/main` 同步；未跟踪文件 `frontend/ui-style-comparison.html` 保留未改动。
- 全量前端回归：在 `frontend/` 执行 `node --test --test-concurrency=4 --test-reporter=spec`，257 passed、0 failed、0 skipped。
- 全量后端回归：在仓库根目录执行 `python -m pytest backend/tests -q --disable-warnings --tb=short -p no:cacheprovider`，将 pytest 与系统临时目录隔离到 E 盘后，1,428 passed、5 skipped、0 failed、17 warnings。最初未隔离临时目录的全量运行出现两个失败；检查时 C 盘仅剩约 5 MB，FlatGeobuf 错误明确为 `No space left on device`。其中大 GeoTIFF 上传用例随后在 E 盘临时目录单项重跑通过；因此不把第一次结果记作产品缺陷。远程数据测试受网络/资源条件影响，按测试输出跳过或失败时以最终隔离目录全量结果为准。
- `execute_python` 复核确认只使用 AST 代码规则、本地子进程和 120 秒执行超时；子进程仍可继承除已剔除 `AMAP_KEY` 外的父环境变量，白名单地理库可能触达文件和网络，且没有操作系统级 CPU/内存隔离。内置启动器绑定 `127.0.0.1`，但工具 API 无认证、CORS 允许任意来源；不应把当前实现用于公开或多租户部署。
- 已修正文案：工具描述与 AI 提示不再把本地子进程称为安全沙箱，也不再声称 `requests/urllib` 导入限制等同网络隔离；新增回归守卫防止该安全边界被文案误报。未改 Python 执行权限、隔离架构、认证或 CORS。
- 回归：`python -m pytest backend/tests/test_execute_python_credentials.py -q --disable-warnings --tb=short -p no:cacheprovider` 定向用例通过；README 中英文已同步更新执行边界、DEM 验收范围和本次自动化结果。
- 未验证边界：未尝试沙箱逃逸、资源耗尽或网络监听的破坏性实验；真实模型、公开部署和浏览器本地文件选择上传仍未验收。

### 2026-10-26 上传磁盘写入失败反馈

- **入口与证据：**`frontend/js/upload.js` → `GIS.api.upload` → FastAPI `/api/upload` 的流式文件写入。写入异常原先会删除部分上传文件后重新抛出，接口返回通用 500；前端对非 2xx 响应只显示 `Upload API error: <status>`，无法向用户展示后端校验详情。磁盘写满的真实错误曾阻塞测试临时目录，但未对上传端点进行真实满盘操作。
- **最小修复：**上传写入期间识别 POSIX `ENOSPC` 与 Windows `winerror=112`，清理部分文件并返回 HTTP 507 与可操作的中文提示。前端读取非 2xx JSON 的 `detail`/`error`，保留旧的状态码兜底和网络中断未知收件状态。
- **回归验证：**新增故障注入在文件写入一个字节后抛出 `ENOSPC`，断言 HTTP 507、提示内容和残片清理。`python -B -m pytest backend/tests/test_upload_handoff.py -q -ra --tb=short -p no:cacheprovider --basetemp=<workspace temp>`：15 passed；`node --test frontend/tests/api_provider_key_storage.test.cjs`：16 passed；`git diff --check` 通过。
- **边界：**仅使用临时测试目录模拟磁盘满，没有真实耗尽磁盘；Windows 错误码分支未独立注入验证。浏览器本地文件选择上传的 `Failed to fetch` 根因仍未确定，本次改动不解释或解决该网络错误。

### 2026-10-26 浏览器本地文件上传隔离复测

- **验证环境：**在 `127.0.0.1:8002` 启动独立测试服务，上传输出和系统临时目录均指向 E 盘 Goal 临时目录；测试包装拦截 Provider 设置写入、工程列表读取和模型测速。未向现有 `127.0.0.1:8000` 服务发送上传请求，也未保存测试工程。
- **浏览器实测：**从图层面板打开文件选择器，选择小型 GeoJSON，在预览中确认后上传；服务日志记录 `POST /api/upload` 返回 200，图层面板显示 1 个 Point 要素。另在全新隔离页选择有效 CRS（EPSG:4326）的 4×4 GeoTIFF；上传返回 200，PNG 预览请求返回 200，图层面板显示 Raster，地图 attribution 显示该栅格图层。
- **结论边界：**这证明当前工作区代码在隔离浏览器、E 盘临时空间和对应测试服务下可完成矢量与栅格上传、注册及地图交接；没有复现原 8000 页面上的 `Failed to fetch`，因此其根因仍未知。原页面的 `gis_api_base_url` 是否匹配、原请求是否到达服务、CORS/网络中断以及低 C 盘空间是否相关均未确认。当前环境 C 盘剩余空间过低，本轮常规测试命令无法启动；不据此宣称上传全量回归通过。

### 2026-10-26 隔离浏览器无效 TIFF 失败路径

- **操作与响应：**在隔离工作台 `http://127.0.0.1:8003/?app=3` 通过图层面板文件选择器上传 13 字节无效 TIFF。服务日志确认 `POST /api/upload` 返回 HTTP 200；前端显示后端给出的 GeoTIFF 格式解析错误，而非成功状态或 `Failed to fetch`。
- **清理与界面：**上传前后图层数均为 2；隔离输出目录中对应 TIFF 和预览 PNG 均不存在。该结果验证了无效栅格的错误交付与后端清理，不代表原 `8000` 页面失败的根因。
- **回归：**`python -m pytest -q backend/tests/test_upload_handoff.py`：15 passed；`node --test frontend/tests/api_provider_key_storage.test.cjs frontend/tests/upload_preview.test.cjs`：32 passed。pytest 因工作区 `.pytest_cache` 权限受限有一条缓存警告，不影响退出码和断言结果。
- **全量复核：**前端 `node --test frontend/tests/*.test.cjs`：261 passed；后端 `python -m pytest -p no:cacheprovider --basetemp=<隔离 E 盘目录> -q --disable-warnings --tb=short backend/tests`：1,434 passed、1 skipped、0 failed、18 warnings。
- **边界：**当前浏览器没有控制台 warning/error；原始失败时的请求、响应和服务端访问记录不可用。没有向 8000 上传；未模拟系统级断网、长时间超时或真实磁盘耗尽。`Failed to fetch` 原事件仍待原始请求证据确认。

### 2026-10-26 上传响应丢失与同请求恢复

- **已复现问题：**隔离代理把浏览器的 GeoJSON multipart 请求转发到 8003，收到后端 HTTP 200 后重置浏览器连接。后端日志确认上传成功；上传文件及图层注册已提交，但前端第一版只显示“服务器可能已收到”，图层面板仍为 0 层。此为受控响应丢失复现，证明该网络故障模式可产生 `Failed to fetch` 和后台孤立注册；不证明它就是原 8000 事件。
- **修复：**前端为每次上传生成随机请求编号。遇到网络中断时先查询 `/api/upload/status/{request_id}`；若后端已完成，取回同一注册版本并继续地图/图层交接。错误仍未知时保留“检查并恢复”按钮，用户可用同一请求编号恢复或重试。后端对成功结果做 15 分钟、最多 64 项的进程内缓存；重复或并发请求不会再次保存同一上传，处理中返回 409。恢复结果从当前注册图层重建，不重复缓存 GeoJSON 内容。
- **浏览器验收：**在隔离 WTB 页面选择 155 字节临时 GeoJSON；代理故意丢弃首次响应。浏览器随后查询状态，成功恢复 `lost-response-20261026.geojson`，图层面板显示 1 个 Point 要素；后端状态查询返回 HTTP 200，注册名只有一项，隔离上传目录只有一份文件。无请求发送到 8000。
- **定向回归：**新增后端向量/栅格重复请求测试，验证相同请求编号返回原注册、不重复创建文件；前端覆盖状态恢复、不确定收件后的同编号重试及 HTTP 409 处理中状态。定向测试：后端 17 passed；前端 36 passed。
- **全量回归：**前端 `node --test frontend/tests/*.test.cjs`：267 passed、0 failed；后端 `python -B -m pytest -p no:cacheprovider --basetemp=<隔离 E 盘目录> -q --disable-warnings --tb=short backend/tests`：1,432 passed、5 skipped、0 failed、17 warnings，用时 101.44 秒。前端全量回归在补充旧后端兼容保护后重新运行。
- **限制：**恢复记录仅在当前后端进程内保留 15 分钟，服务重启或缓存淘汰后不能恢复旧响应；该路径不自动盲目重传。原始 8000 页面当时的请求体、服务器访问记录和网络条件仍不可取得，因此原 incident 的具体起因未确定。
- **运行中服务兼容性：**只读检查发现当前 `127.0.0.1:8000` 对 `/api/upload/status/probe-only` 返回 404，而隔离更新服务 `127.0.0.1:8003` 返回 200，确认 8000 仍运行未包含恢复接口的旧后端。前端现遇到 404/405 或状态查询不可用时不会显示可能造成重复上传的重试按钮；需更新并重启 8000 服务后才能使用自动恢复。当前 IAB profile 的同源存储探针只记录到“无自定义 API 地址”，不读取或输出设置值/API Key；探针页面已删除。该兼容性检查没有上传文件或保存项目到 8000。

### 2026-10-26 本轮代码修改后的全量回归

- 前端：在 `frontend/` 执行 `node --test --test-concurrency=4 --test-reporter=tap`，261 passed、0 failed、0 skipped。该结果在分析启动器翻译修改后重跑。
- 后端：在仓库根目录执行 `python -B -m pytest backend/tests -q -ra --disable-warnings --tb=short -p no:cacheprovider --basetemp=<E 盘工作区临时目录>`，1430 passed、5 skipped、0 failed、17 warnings，运行 116.43 秒。4 个云原生远程读取用例因网络/远程服务条件跳过，另 1 个知识库用例因测试夹具章节结构条件跳过；未将其计为通过。
- 测试临时目录放在工作区 E 盘新建路径中，测试完成后仅删除本轮创建的临时目录；没有清理缓存、用户工程或未知文件。`git diff --check` 通过。
- 这是当前工作区自动化回归，不覆盖真实模型、在线 Provider、完整浏览器/桌面流程，也不代表空间算法已经过外部基准验证。

### 2026-10-26 分析工具启动器中英文混杂

- **复现与根因：**在本地浏览器 `http://127.0.0.1:8000/` 的英语界面打开“工具 → 分析工具”，启动器标题、4 个分类和 20 个工具按钮仍以中文常量渲染；调用 `analysis_tools.js` 的 `OPS` 及 `_buildLauncher()` 可确认该动态面板没有读取 `GIS.i18n`。用户截图中的主工具下拉菜单在本轮新开浏览器页复查时已全部显示英文，因此未把静态菜单截图误判为同一故障。
- **最小修复：**为 20 个启动项复用现有英文工具翻译键，补充一个缺少的 “Surface volumes” 翻译和 4 个分类键；标题也使用现有 “Analysis tools” 翻译。启动器监听语言变化事件，面板已打开时分类、名称和提示也随语言切换刷新。未改动独立工具参数表单与整体菜单视觉。
- **验证：**浏览器当前运行版本英语界面展示 “Analysis tools”、4 个英语分类和全部 20 个英语工具名；Node 定向检查 `analysis_tools_fields.test.cjs` 与 `tool_menu_i18n.test.cjs`：13 passed，覆盖英语渲染、打开后中英切换及翻译键完整性。
- **边界：**没有在浏览器里切换语言，以免改变用户同源 localStorage；语言切换由单元测试覆盖。独立工具参数表单中的动态说明仍含中文，未纳入本次修复。

### 2026-10-26 桌面主进程定向复核

- 在 `desktop/` 执行 `node --test --test-reporter=tap tests/main.test.cjs`：29 passed、0 failed、0 skipped。
- 这是桌面主进程测试，不是启动完整 Electron 窗口、构建安装包或在干净机器上验收；本轮未修改桌面端代码。

### 2026-10-26 栅格图层元数据面板回归覆盖补充

- **现有浏览器证据：**本文件“真实 DEM 二次分析与工程恢复”记录了 SRTM-derived DEM 分析、保存/重开、再次分析，以及图层检查器展示来源、CRS、单位、有效像元比例和质量提示。该浏览器流程是已有记录，本轮没有重复操作浏览器或修改验收工程。
- **本轮代码核对：**`layers.js` 的栅格检查器已统一显示来源标签、源文件、输入图层、HTTP(S) 来源说明链接、CRS、分辨率、像元值单位、垂直基准、有效像元比例和质量提示；`_raster_preview_op` 将主要字段写入 GeoTIFF 标签与图层元数据。工程恢复对元数据的保留由 `test_project_raster_persistence.py` 覆盖。
- **最小改动：**增强 `frontend/tests/raster_inspector_i18n.test.cjs`，为来源标签/文件/输入图层/链接、垂直基准和有效像元比例补充英中界面断言；没有改变用户可见行为。
- **验证：**`node --test frontend/tests/raster_inspector_i18n.test.cjs frontend/tests/chat_send_lifecycle.test.cjs`：22 passed；`python -B -m pytest -p no:cacheprovider -q --tb=short --basetemp=<E 盘隔离目录> backend/tests/test_project_raster_persistence.py backend/tests/test_raster_provenance.py backend/tests/test_dem_analysis.py`：25 passed；目标文件 `git diff --check` 通过。
- **边界：**本轮没有重新访问 AWS Terrain Tiles，也没有重复浏览器保存/重开；元数据面板测试确认的是现有字段渲染，不独立验证来源声明或数据的地理/垂直基准真实性。

### 2026-10-26 WTB 页面内隔离上传复验

- **隔离方式：**用当前前端打开 `http://127.0.0.1:8003/?app=3` 的 WTB 页面；根路径 `/` 会返回版本状态 JSON，不是工作台入口。后端上传输出、系统临时目录、工程索引/Blob 与 Provider 设置路径均定向到 `.goal-upload-investigation-20261026`。Provider 设置、代理设置和 API Key 测速请求由隔离包装拦截；未向 8000 发送文件，也未保存用户工程。
- **浏览器上传结果：**通过 WTB 数据页/图层页的本地文件入口选择临时 `points.geojson` 与 4×4、EPSG:4326 GeoTIFF。图层面板出现 `points_1.geojson`（Point、1 个要素）及 `dem_valid_epsg4326_1`（Raster）；隔离后端记录上传 HTTP 200，栅格 PNG 预览与原始 TIFF 的 HTTP GET 均为 200。
- **原服务只读连通检查：**从独立浏览器页跨源 GET `http://127.0.0.1:8000/api/version` 返回 200。随后从隔离页面向 8000 `/api/upload` 发出不含文件的空 multipart POST，浏览器可读取后端结构化 422（缺少必填 `file`）；此请求不包含文件，未产生上传产物。该证据排除本轮 IAB 环境到 8000 的普遍连通失败及该路由上的通用 CORS POST 拦截。
- **同源 API 地址只读检查：**使用临时静态页在 8000 origin 读取 `localStorage.gis_api_base_url` 的状态，但不输出原值；当前 IAB profile 显示 storage 可读、override 不存在，因此前端回退到页面 origin `127.0.0.1:8000`。探针不加载 WTB 启动代码，随后已删除；没有触发 Provider 设置写入，也没有访问密钥字段。
- **结论边界：**原 8000 页面上的文件请求仍未复现。上面的无文件 POST 不验证真实 multipart 文件体；`gis_api_base_url` 只代表探测时当前 IAB profile 的状态，不证明故障发生时的页面状态；原文件的大小/内容、磁盘状态或请求取消情况仍未知。当前线程没有附加 8000 应用终端，仓库内也未找到其访问日志，无法回溯原请求是否到达服务端。原失败根因继续未定；没有因此修改生产上传代码。

### 2026-10-27 GeoSource 代理跨站读取、响应体和重定向限制

- **修复：**`/api/geosource/proxy` 拒绝非 loopback 浏览器 Origin，也拒绝通过自定义域名重绑到本机的请求；localhost/127.0.0.1 不同端口的本地前端和无 Origin 的本地客户端仍可使用。全局 CORS 也限制为 loopback 来源。上游响应增加 64 MiB 上限。前端代理改用 POST JSON，避免 URL 出现在本地 API 查询串；Uvicorn 访问日志对兼容旧 GET 的查询部分脱敏。公网目标的重定向会逐跳解析 DNS，拒绝指向私网、回环或无法确认的地址；用户直接指定私网服务仍可使用。
- **验证：**`test_geosource_proxy_redaction.py`、`test_geosource.py`、`test_layer4_map_integration.py` 和 `test_local_cors_policy.py` 共 28 项通过；`backend/main.py` 和定向测试文件编译通过；`geosource.js` 语法检查及 `git diff --check` 通过。DNS 与重定向测试均使用替身，没有访问真实网络目标。
- **边界与后续：**私网/公网分类依赖代理进程本机的 DNS 解析结果，检查与后续连接之间仍存在 DNS 变化窗口；远端 HTTP 代理与本机 DNS 视图不一致时，公网重定向可能被保守拒绝。其他 API 仍无应用层鉴权，服务仍应限于本机可信单用户。

### 2026-10-27 用户提供 GIS URL 的重定向边界

- **发现并修复：**GeoSource 以外的 URL 探测/抓取同样接收用户 URL。`url_gis_service._http_get` 与云原生文件下载/PMTiles Range 原来使用默认自动跳转，公网地址可跳向本机或私网。新增共享 HTTP(S) 重定向策略：用户直接指定私网地址仍可访问；从公网地址发起的请求只可跳往解析为全局可路由地址的 HTTP(S) 目标，私网、回环、含 userinfo、未知 DNS 和非 HTTP(S) 跳转会拦截。应用到 URL GIS 请求和 urllib 下载/Range 通道。
- **验证：**URL GIS、GeoSource 代理/服务、图层集成、本地 CORS 和云原生格式合计 78 项本地/受控测试通过；8 个公网集成测试被单独排除。包含公网测试的合并运行中，82 项通过、3 项按条件跳过，FlatGeobuf 公网测试 1 项因 TLS EOF 失败；该不稳定用例未计为通过。pytest 临时目录放到工作区后，GeoSource 测试通过。新增跳转测试替身 DNS 和响应，没有连接真实网络目标。
- **边界：**GDAL/rasterio/pyogrio 直接 `/vsicurl/` 流读取由原生网络驱动处理跳转，本次未证明该路径遵守此策略；需要单独确认 GDAL 可配置限制，或在访问前改为受控 HTTP 通道。DNS 解析和连接之间的变化窗口也仍存在。

### 2026-10-27 在线 GIS 凭据错误与来源脱敏

- **发现并修复：**在线 COG/PMTiles/GeoParquet/FlatGeobuf 的底层错误可能回显含 token 或 userinfo 的源 URL，再被 API、异步任务、Agent 工具或 MCP 原样返回；`load_cog` 还曾把带凭据的完整 URL 写入范围框图层属性，`get_cog_info` 会在报告标题展示原 URL。现在统一清理嵌入错误文本中的 HTTP(S) 凭据、敏感查询值和片段；应用到主要工具、MCP、URL 检查 API 与异步抓取错误。COG 来源元数据和信息标题使用脱敏 URL；自动生成图层名从 URL 路径取值，不包含查询参数。
- **验证：**URL GIS/云原生格式的 58 项本地测试通过；覆盖 userinfo、token 查询参数、图层存储来源、工具错误、API 错误和异步任务错误。`sanitize_http_url` 对本地 Windows 路径的保持行为也有测试。没有访问外部服务。
- **GDAL 跳转限制调查：**GDAL 当前配置文档记录了重定向时 Authorization 头的转发策略，以及 S3 已签名跳转优化开关；未找到可按 DNS/IP 限制一般 HTTP 重定向目标的配置项，故 `/vsicurl/` 路径仍属于未解决边界。参考 [GDAL 网络配置选项](https://gdal.org/en/stable/user/configoptions.html)。

### 2026-10-27 自定义模型启动时自动测速

- **发现并修复：**设置模块启动时对所有含 Key 的 Provider 静默调用 `/api/test-key`；后端每次会向模型发送 `hi` 并请求 1 个输出 token，可能产生用户未预期的调用/费用，而且供应商临时不可达会把持久状态标成离线。现在启动只把上次在线/离线标记重置为“未验证”，不触发模型请求；连通性由用户在对应 Provider 行点击“测速”触发。设置说明补充了自备 Key、接口地址/模型名要求和测速可能计费的提示。
- **验证：**`settings_geo_credentials.test.cjs` 与 `api_provider_key_storage.test.cjs` 共 23 项通过；新增回归断言：即使配置多个带 Key 的 Provider，初始化也清除陈旧状态且不调用 `testProvider`。未调用真实供应商，也未使用用户密钥。

### 2026-10-27 高德 Key 后端明文持久化

- **发现并修复：**模型 Provider Key 已从 `user_settings.json` 排除，但高德 Web Key 仍被 `/api/user-settings` 写入该 JSON 文件明文。现在高德 Key 使用现有 Fernet 凭据库保存；设置文件不再接收或持久化该字段，读取设置时仍从加密存储返回以维持跨浏览器同步。旧版设置文件中的明文高德 Key 会在读取时迁移到加密存储并从 JSON 清除。界面只在后端确认保存/删除后显示成功，后端失败时明确提示 Key 仅在当前浏览器可用；移除了输入失焦和点击保存时重复提交的行为。
- **验证：**后端设置/加密凭据与执行凭据测试共 7 项通过，验证密钥不出现在设置 JSON/加密文件明文、旧数据迁移、读取同步和删除；前端设置与 Provider/API Key 测试 27 项通过，覆盖只在点击后提交、后端确认后提示成功、加密同步失败提示及中英文提示；GeoSource 代理安全测试 14 项通过。代理边界按用户选择：直接访问用户指定的内网服务允许，公网服务重定向到内网时拦截。使用临时凭据目录与哨兵值，没有读取或改写真实用户凭据。

### 2026-10-27 云原生 GDAL 重定向保护

- **发现并修复：**COG、GeoParquet 和 FlatGeobuf 原由 GDAL/libcurl 直接访问远程 URL，GDAL 文档没有提供按 IP 限制一般 HTTP 重定向的选项。现在 GDAL 通过一次性 loopback Range 中继读取；中继对每个上游 HEAD/Range 请求使用共享重定向策略，用户直接指定的内网地址仍允许，公网重定向到内网、回环或无法确认的目标会拒绝。保留按需读取；单次中继响应限制为 64 MiB，GDAL 打开失败时仍可经受控 urllib 通道回退下载。
- **验证：**云原生、GeoSource 代理、URL GIS 与 URL 作业共 81 项本地/受控测试通过，4 项 slow 外部服务用例排除。新增用例验证 loopback Range 转发、公网跳私网拒绝，以及 COG/FlatGeobuf 调用受保护源上下文。Rasterio/pyogrio 实际通过本机 TCP 中继的端到端用例在当前运行环境卡在 `rasterio.open`，未计为通过；需在正常桌面网络环境补验。
- **边界：**DNS 检查与上游实际连接之间仍存在解析变化窗口；真实 GDAL/pyogrio 网络读取也尚未在本机完成端到端验收。参考 [GDAL 虚拟文件系统文档](https://gdal.org/en/stable/user/virtual_file_systems.html)。

### 2026-10-27 GeoSource 统计缓存失效

- **发现并修复：**统计响应为避免暴露本机数据库完整路径，改为返回 `db_name`；缓存命中仍从响应对象读取 `db_path`，导致每次访问统计接口都重跑多组聚合查询。现在把数据库路径身份保存在内部缓存状态中，不放入 API 响应。
- **验证：**新增回归用例确认同一数据库和修改时间只查询一次、修改时间变化会重新统计、响应不含 `db_path`；定向用例通过。

### 2026-10-27 GeoSource 服务图层重新授权与工程往返

- **发现并修复：**WMS/XYZ/ArcGIS 服务图层保存工程时，前端和后端的字段白名单会丢失服务地址、服务类型及重新授权信息，导致重新打开工程无法恢复。现在保存去除 URL 用户信息、Key 类查询参数、自定义授权参数和片段后的服务地址，保留授权参数名与“需要重新授权”状态；恢复工程时按图层逐个提示用户重新输入凭据，凭据只用于当前请求，不进入图层元数据。保留服务图层 ID、透明度、可见性和分组；恢复时若旧工程有重复 ID，也会给服务图层分配唯一 ID。读取旧工程、导出旧工程及导入外部旧工程时也会清理历史凭据，并从可识别的 Key 参数恢复重新授权提示。
- **验证：**后端工程持久化/导入测试 36 项通过；前端 GeoSource、工程恢复和设置凭据测试 25 项通过；前端语法检查、后端编译和本次修改的 `git diff --check` 通过。新增用例覆盖含 URL 用户名密码、内置 API Key、自定义 `code` 参数和片段的 XYZ 地址，以及含旧 token 的旧工程读取/导出和外部旧工程导入，验证工程归档与落盘数据中没有哨兵凭据。
- **限制：**只验证本地工程保存/导出/导入与模拟凭据提示；没有调用真实 WMS/XYZ 上游，也没有在桌面地图界面验证第三方服务的兼容性。

### 2026-10-27 混合 DNS 答案下的公网跳转策略

- **发现并修复：**共享 URL 安全策略原把“解析结果全部为公网”之外的情况都归为内网；若同一主机名同时返回公网和私网地址，公网来源的跳转保护会被关闭。现在分类区分全公网、全非公网及混合/未知；只有全非公网仍按用户直接指定内网源处理，混合或未知来源开启公网跳转保护，跳转目标也必须明确解析为全公网。
- **后续加固：**URL GIS 的直连 Requests 与共享 urllib opener（GeoSource 代理、云原生 GDAL 中继和下载回退使用）现在会在连接前重新解析并复核目标，把复核通过的 IP 固定到实际套接字连接；HTTPS 保留原域名的证书与 SNI 校验。公网或未知来源若在检查后解析到内网会拒绝；用户直接指定的私网源仍允许首次连接。
- **代理行为：**私网、混合和无法确认的初始 URL 绕过全局/系统代理并走本地固定 IP 路径；明确公网目标可继续走 HTTP/HTTPS 代理，但 HTTP 代理请求会把已检查 IP 放在目标 URL 中并保留原 Host，HTTPS CONNECT 固定到已检查 IP，同时保留原域名的 SNI 与证书校验。Requests 对受保护目标选择 SOCKS 代理时会拒绝请求，因为无法固定远端 DNS。
- **验证：**`test_url_gis.py` 全部 48 项通过；本机代理用例分别验证 Requests/urllib 的 HTTP 转发目标是已检查 IP 且 Host 仍为原域名，以及 HTTPS CONNECT 目标为已检查 IP、TLS ClientHello 的 SNI 仍为原域名；另有用例验证 DNS 改为内网时拒绝、直连路径固定地址和非公网初始 URL 绕过代理。GeoSource 代理测试 14 项全通过；`test_cloud_native.py -m 'not slow'` 29 项通过、4 项 slow 用例按标记排除。所有网络边界使用本机 HTTP 代理、服务或 DNS 替身，没有访问真实公网或内网服务。
- **剩余边界：**只用本机 HTTP 代理验证了转发与 TLS ClientHello；没有对真实用户代理、HTTPS 代理服务器或代理端自定义重写行为做验收。由用户配置的代理若刻意忽略 IP 字面地址并按 Host 重新解析，客户端无法约束其内部实现。

### 2026-10-27 URL GIS 响应与 Shapefile ZIP 资源上限

- **发现并修复：**URL GIS 原先用 Requests 将远端完整响应不设上限读入内存；Shapefile ZIP 则先完整下载，再不检查展开体积与成员数量就解压。现在响应以流式方式读取并限制在 300 MB；ZIP 路径与成员数检查之后，还限制解压总量为 512 MB、最多 10,000 个成员，超限不会执行解压。
- **验证：**`test_url_gis.py` 全部 39 项通过，包含已知 Content-Length 超限、分块读取中途超限、关闭流后响应仍可供 JSON/内容读取、ZIP 展开体积超限和成员数超限；Python 编译与目标差异检查通过。响应限制测试使用小型伪响应，没有申请或下载大文件。
- **边界：**300 MB 响应被保存在内存供现有 GeoJSON/CSV/ZIP 解析流程使用；较大的合法数据源会明确失败，用户需要缩小数据范围或改用云原生流式读取。

### 2026-10-27 ArcGIS 当前视窗导入的范围校验

- **发现并修复：**ArcGIS“当前视窗”模式在地图尚未就绪或读取范围失败时，会移除 BBOX 条件继续发起全域查询，成功提示仍声称已精准过滤。现在只有成功取得且可表示为 EPSG:4326 范围的地图视窗时才发请求；范围缺失、非数值或无效时明确报错，不降级到全域查询。还移除了分页成功提示中的“0 缺失”断言，因为客户端无法证明远端分页没有遗漏。
- **验证：**`node --check frontend/js/geosource.js`、`node --test frontend/tests/geosource_layer_capacity.test.cjs`（6 项）与目标 `git diff --check` 通过。
- **边界：**现有 GeoSource 前端测试没有模拟 ArcGIS 目录交互与地图范围缺失的完整界面流程，因此本轮不声称该交互已被自动回归测试覆盖。

### 2026-10-27 GeoSource 导入模式与境外边界指引

- **发现并修复：**ArcGIS 目录把最多 12 批（12,000 条）的导入称为“全量”，并把单批最多 1,000 条的视窗导入宣传为无上限的精准过滤；现在在选项上提前显示各自上限，成功提示也明确视窗模式单次上限。帮助页仍指示用户用 `execute_python + osmnx` 获取境外边界，与当前专用 GIS 工具调用规范及代码执行边界冲突；已改为引导使用专用 GIS 工具，并说明 Python 执行不用于联网取数。
- **验证：**`node --check frontend/js/geosource.js`、现有 GeoSource 层容量/凭据回归 6 项通过；`git diff --check` 通过。直接的 ArcGIS 目录交互未被该测试文件覆盖。

### 2026-10-27 用户设置迁移失败与损坏文件保护

- **发现并修复：**旧版设置中的高德 Key 加密失败或清理明文 JSON 失败时，读取接口原先静默返回脱敏数据；磁盘上的明文可能仍在，用户看不到迁移失败。现在迁移和清理失败都会返回可操作的错误，明确提醒旧文件可能仍含明文。另发现损坏或非对象格式的设置文件会被当作空配置，后续增量保存可能覆盖原文件；现在读写均失败关闭，避免静默重置配置。调整 Key 删除顺序，避免从旧明文配置迁移时把刚删除的 Key 再次写回加密库。设置写入改为同目录临时文件、刷盘后原子替换，并串行化增量更新，避免中断留下半份 JSON 或并发更新互相覆盖。前端现在会显示后端给出的可操作失败原因。
- **验证：**`test_user_settings_provider_keys.py` 9 项通过，覆盖加密迁移失败、敏感字段清理失败、损坏 JSON 不被覆盖、删除旧版明文 Key 后两处均清空，以及原子替换失败时保留旧文件并清理临时文件；`api_provider_key_storage.test.cjs` 与 `settings_geo_credentials.test.cjs` 共 27 项通过，确认同步失败时 UI 展示返回原因；后端编译及目标 `git diff --check` 通过。失败场景使用临时文件与哨兵密钥。
- **边界：**迁移失败时旧文件可能继续保留明文，接口会明确失败而不返回配置；用户需恢复磁盘空间/文件权限后重试，或手动清除旧密钥。

### 2026-10-27 GeoSource 手动密钥参数识别

- **发现并修复：**GeoSource 服务 URL 若已包含 `token`、`api_key` 等认证参数，但目录元数据把服务标为免密，接入流程此前不会弹出手动输入密钥的窗口。现在从 URL 识别出认证参数时也会提示用户并预填参数名；认证输入框缺失时显示错误并停止请求。GeoSource 的 ArcGIS/GeoJSON 请求和 WMS/XYZ 瓦片现都经同源后端代理，WMS 动态参数会转发到目标服务，XYZ 坐标模板继续由 Leaflet 展开。用户输入的 Key 随本次代理请求发给服务方，不交给 AI、不写入工程；代理 GET 日志会隐藏目标 URL。
- **安全边界：**代理继续允许用户直接访问内网源，拦截公网源跳到内网或回环地址；瓦片响应上限 16 MiB，并设为不缓存；常规 GeoSource 获取上限 64 MiB。
- **验证：**`node --check frontend/js/geosource.js` 与 `node --test frontend/tests/geosource_layer_capacity.test.cjs`（8 项）通过；`test_geosource_proxy_redaction.py` 15 项通过，覆盖瓦片二进制响应、WMS 参数转发、目标 URL 日志脱敏和公网跳内网拦截。
- **边界：**尚未用真实第三方 GeoSource 服务完成浏览器端渲染验收；响应类型、参数转发和重定向边界由本地替身测试覆盖。

### 2026-10-27 远程 COG 请求超时边界

- **发现并修复：**受保护的 GDAL COG Range 中继和下载回退原先每次 urllib 请求允许等待 60 秒；GDAL HTTP 请求没有应用级连接、慢速传输或重试限制，外部代理/服务无响应时一次 COG 操作可能长时间挂起。现在远程 COG 的 GDAL 请求限制为 20 秒、连接 5 秒、不重试、低于 1 B/s 持续 20 秒即停止；中继和下载回退的 socket 超时也限制为 20 秒。中继校验保留随机资源路径，允许查询串及单个尾斜杠；客户端提前断开后发送错误响应时会安静关闭连接。远程配置作用域会在读取结束后恢复。
- **验证：**`test_cloud_native.py -m 'not slow'`：35 项通过、4 项网络慢测排除；覆盖中继路径变体、客户端断开、单请求超时、GDAL 配置作用域和 502 提示。远程 COG 集成测试有一次在 7.35 秒内返回 HTTP 502，另有两次在约 170 秒后通过；成功运行期间仍记录到一次路径不匹配 404。
- **剩余问题：**脱敏探针确认当前配置有 HTTP 代理，上游曾返回 `502 Bad Gateway`，且错误正文包含 CONNECT 标记；响应没有 `Via`、`Server` 或代理认证头，仍无法确认是代理还是源站导致。远程读取时间有明显波动；路径不匹配 404 仍未定位具体请求形式，自动化本地替身已覆盖查询串和单个尾斜杠。保留用户代理和跳转安全边界。

### 2026-10-27 私网源跨公网重定向链边界

- **发现并修复：**用户明确选择私网服务时，首个私网跳转可以访问其他私网；但若该链先跳到公网或 DNS 分类不明确的主机，再跳回私网，原策略会一直按初始私网来源放行。现在共享 urllib 重定向处理器与 URL GIS 手动重定向都会在链路到达公网或模糊分类主机后启用持续保护，后续目标必须明确为公网；GeoSource、云原生 urllib 读取和 URL GIS 因此一致拦截回跳。
- **验证：**`test_geosource_proxy_redaction.py` 与 `test_url_gis.py` 共 66 项通过；新增覆盖私网→公网→私网、私网→混合 DNS→私网链路，保留私网→私网允许及公网→私网拒绝。`git diff --check` 通过。测试使用 DNS/HTTP 替身，未连接真实公网或内网服务。
- **边界：**没有在用户真实内网或公网代理环境中验收跳转行为；其分类依赖请求时 DNS 结果，混合/未知目标按受保护目标失败关闭。

### 2026-10-27 自定义模型异常中的密钥脱敏

- **发现并修复：**连接测速会过滤原始错误，但聊天的 Agent 失败路径曾把 Provider 异常原文写入聊天错误响应及控制台；异常若回显用户 Key 或携带认证查询串，可能把凭据再次暴露。现在非流式/流式错误、重试和收尾日志都会先去掉当前 Provider Key，并清理 URL 用户信息、敏感查询参数和片段；异常 traceback 只保留调用栈帧，不打印异常文本。
- **验证：**`test_agent_retry_safety.py`、`test_stream_step_events.py`、`test_ai_key_error_redaction.py` 共 29 项通过。非流式和流式哨兵 Key 用例均确认用户响应/SSE、stdout/stderr 都不含 Key；测速用例继续验证异常正文不回传给客户端。`git diff --check` 通过。
- **边界：**没有调用真实模型 Provider；脱敏针对配置中的完整 API Key、常见 URL 认证字段与片段，不能替代对第三方错误响应内容的全面语义脱敏。

### 2026-10-27 流式聊天 Provider Key 重复传输

- **发现并修复：**普通 API 封装和测速已改为只在 `llm_config.api_key` 携带 Provider Key，但实际聊天由 `chat.js` 直接创建 SSE 请求，仍额外发送顶层兼容字段 `api_key`。现在流式聊天也只发送一份 Key；后端仍保留旧客户端的兼容解析。
- **验证：**`chat_send_lifecycle.test.cjs` 与 `api_provider_key_storage.test.cjs` 共 42 项通过；新增实际 SSE 请求体断言确认顶层没有 `api_key`，而 `llm_config.api_key` 保留自备密钥。`node --check frontend/js/chat.js` 与目标 `git diff --check` 通过。
- **边界：**验证使用测试用 Key 和模拟 SSE，不连接真实模型服务；浏览器完整接入流程仍未验收。

### 2026-10-27 自定义模型地址的明文传输保护

- **发现并修复：**用户自填公开 HTTP 模型地址时，聊天内容和 API Key 会经未加密 HTTP 发往模型服务。现在聊天、流式聊天和测速在发起 Provider 请求前都拒绝公网或无法确认的 HTTP 地址，提示改用 HTTPS；本机或 DNS 明确解析为私网的 HTTP 模型仍可使用。前端聊天会展示后端给出的具体策略原因。
- **验证：**`test_model_endpoint_transport.py` 5 项通过，覆盖公网/未知 HTTP 拒绝、HTTPS 和明确私网 HTTP 放行，以及两个聊天入口和测速入口均在 Provider 调用前阻断；相关前端 API 与聊天生命周期测试 44 项通过，确认策略提示能到达用户。模型设置说明已接入中英文词条；`tool_menu_i18n.test.cjs` 与 `raster_inspector_i18n.test.cjs` 共 8 项通过。JS 语法检查和目标 `git diff --check` 通过；未连接真实 Provider。
- **边界：**内网 HTTP 明文只适用于用户选择并解析为非公网的模型地址；公网 HTTPS 端点的证书校验仍由 HTTP 客户端执行。无法解析或混合 DNS 的 HTTP 主机按公网保护策略拒绝。

### 2026-10-27 网络代理范围与私网模型提示

- **发现并修复：**网络设置此前把代理描述为主要用于影像下载，未说明自定义代理也会承接模型 Provider、GeoSource、在线 GIS 与影像等后端请求；模型配置说明也未提示私网 HTTP 明文风险。现在中英文设置说明列出代理范围、私网模型地址也会经过自定义代理、私网模型直连的配置方式，以及代理可读取经其转发的未加密请求和 API Key。README 同步说明模型 Key 经用户所选 WorkTable 后端及自定义代理的传递边界。
- **验证：**`node --check frontend/js/i18n.js`、`node --test frontend/tests/tool_menu_i18n.test.cjs frontend/tests/raster_inspector_i18n.test.cjs`（9 项）和目标 `git diff --check` 通过。未修改代理运行逻辑。
- **边界：**仅完成词条/页面引用的自动检查，未进行完整浏览器视觉验收；自定义代理对私网模型请求的行为是现有逻辑，本轮只补充告知。

### 2026-10-27 混合公网/内网 DNS 目标失败关闭

- **发现并修复：**用户指定的 HTTP(S) 主机若同时解析到公网和内网地址，会被分类为未知；共享 urllib 安全 opener 与 URL GIS 的连接适配器此前仍可能从该解析结果中选一个地址直连。明确私网域名在预检查后若 DNS 改为公网，也可能在真实连接时转向公网。若请求携带 GeoSource 查询参数凭据，目标变化可能把请求或凭据发到意外主机。现在混合/未知首跳在连接前失败关闭；明确私网首跳在连接时仍须解析为私网。公网首跳在连接时仍须明确解析为公网。明确私网服务及其私网跳转继续允许，访问链经过公网/未知主机后仍持续禁止回跳私网。
- **验证：**新增 URL GIS 与共享 urllib opener 的混合 DNS、私网转公网 DNS 变化连接前拒绝用例；`python -m pytest -q backend/tests/test_url_gis.py backend/tests/test_geosource_proxy_redaction.py backend/tests/test_cloud_native.py -m "not slow"`：105 项通过、4 项慢测排除。覆盖 GeoSource 重定向、代理转发、DNS 固定及云原生读取；测试使用本地替身，没有连接真实公网或内网。
- **边界：**用户手动选择且 DNS 明确为私网的服务仍可直连；DNS 无法解析或同一主机解析结果混合时请求失败，用户需修复 DNS/服务地址后重试。测试有一条 pytest 缓存目录权限警告，不影响用例结果。

### 2026-10-27 模型 Provider 表单可访问名称

- **发现并修复：**自助模型接入表单的接口地址、模型名与 API Key 仅用相邻 `<span>` 显示，未与输入控件关联；Provider 显示名称输入框也没有可访问名称。现在三个字段使用显式 `<label for>` 关联唯一输入 ID，Provider 名称输入框增加 `aria-label`，让辅助技术能准确报出控件用途。
- **验证：**`node --check frontend/js/settings.js` 与 `node --test frontend/tests/tool_menu_i18n.test.cjs frontend/tests/settings_geo_credentials.test.cjs`（15 项）通过；新增源码级检查确保字段标签关联结构不会被移除。
- **边界：**尚未用实际屏幕阅读器或浏览器可访问性树验收，只能确认生成表单的源码结构和相关前端回归。

### 2026-10-27 Provider 本地存储失败时的会话内接入

- **发现并修复：**Provider 本地存储读/写失败时，列表读取曾静默回退默认列表，刚输入的模型 Key 可能立即消失；即使字段保留，选中 Provider 仍只读写浏览器存储，聊天会回退到默认模型；后端同步来的 Provider 元数据也未进入会话缓存。本页内的模型选择还可能被延迟返回的后端旧选择覆盖。现在 Provider 配置和选中项都能在当前页面会话内使用；同步来的无密钥 Provider 元数据也保存在内存缓存；用户本页主动选择优先于迟到的同步结果。存储恢复时会尝试重新持久化；设置页初次打开及保存状态变化时都会即时显示提醒，存储恢复后撤下提醒，并说明刷新/关闭页面会丢失配置。后端仍只接收不含 API Key 的 Provider 元数据。
- **验证：**新增读写均失败、存在旧列表但写入失败两种场景，确认用户配置的 Key 能在当前会话中完成测速和聊天请求；另验证后端同步来的 Provider 元数据可在本地存储不可用时选中，以及延迟同步不会覆盖本页主动选择。请求外的后端设置同步均不含哨兵 Key。`node --check frontend/js/api.js`、`node --check frontend/js/settings.js` 与 `node --test frontend/tests/api_provider_key_storage.test.cjs frontend/tests/tool_menu_i18n.test.cjs frontend/tests/settings_geo_credentials.test.cjs`（41 项）通过。
- **边界：**内存降级不跨页面刷新/关闭保留；提示显示由源码级测试覆盖，尚未做真实浏览器存储配额/隐私模式与页面提示联动验收。

### 2026-10-27 GeoSource 带 Key 请求的跨域重定向

- **发现并修复：**GeoSource 代理会阻止公网服务跳入私网，但带查询参数 Key 的请求若被服务重定向到另一公网主机，旧逻辑仍会照目标 URL 转发，可能把 Key 一并送给新主机。前端现把用户指定的认证参数名随 WMS/XYZ 瓦片、ArcGIS 与普通代理请求传递；GeoSource 代理在跨主机、端口或协议跳转时移除该认证参数及原 URL 中可识别的敏感参数，同源跳转仍保留 Key，其他查询参数和新主机自己的签名参数保留。若新主机因缺少认证参数返回 401/403，提示用户改用服务方原始直连地址。
- **验证：**新增同源保留、跨源移除自定义 `code` Key、GeoSource 请求参数传递及跨源认证失败提示用例。`test_geosource_proxy_redaction.py`、`test_url_gis.py`、`test_cloud_native.py -m "not slow"` 共 108 项通过、4 项慢测排除；`geosource_layer_capacity.test.cjs` 9 项通过；目标 `git diff --check` 通过。测试使用本地替身。
- **边界：**需要把同一 Key 转发到 CDN/另一主机的服务会失败，这是“密钥只发给原服务”的安全策略；应直接配置服务方提供的 CDN URL 或无认证目标。真实浏览器验收未完成：当前 Windows Computer Use 无法确认已有 Edge 页面的 URL，按工具要求停止了 UI 操作；后端本地服务已停止。

### 2026-10-27 AI Provider 接入提示与本地界面核查

- **发现并修复：**模型设置卡片上方原提示仍是静态中文“支持任意 OpenAI 兼容接口”，既不会随语言切换，也没有说明 API Key、接口地址和模型名应从服务商获取。现在将其替换为卡片前的简短操作指引，并加入英文翻译；密钥传输和存储逻辑未改变。
- **验证：**在本机浏览器打开工作台与 AI 模型设置，确认 Provider 卡片和字段正常渲染，并在更新后看到新的中文指引显示在卡片上方。`tool_menu_i18n.test.cjs` 11 项通过，`node --check frontend/js/i18n.js` 与目标 `git diff --check` 通过。
- **边界：**自动化检查确认中英文文案映射及 HTML 标记，未在真实界面切换到英文；未输入密钥或测速，因此未连接真实 Provider。验证用本机服务已停止。

### 2026-10-27 URL GIS 跨源跳转中的认证参数

- **发现并修复：**URL GIS 通过 `requests` 手动处理重定向，但跨主机跳转时会保留目标 `Location` 里的 `api_key`、`token` 等认证参数；ArcGIS 元数据请求把认证参数单独放在 `params` 中，同样可能被跳转响应带到新主机。共享敏感参数名识别函数还把 `key + "="` 与要求至少有一个值的正则匹配，导致自动识别始终返回空集；URL GIS 的凭据提取则用宽泛的子串规则，和跳转保护及错误脱敏对 `key` 的识别不一致。现在三处共用边界化的参数名规则；URL GIS 在跨源跳转时移除来自源 URL 或本次请求参数中的已识别凭据，同源跳转继续保留；若新主机返回 401/403，会说明凭据未转发并建议使用服务方直连地址。
- **验证：**新增用例覆盖 `api_key` URL、单独传入的 ArcGIS `token` 参数、同源凭据保留、参数名识别及剥离凭据后的 403 提示。`test_url_gis.py`、`test_geosource_proxy_redaction.py` 与 `test_cloud_native.py -m "not slow"` 合计 **113 项通过**，4 项慢测排除；两个 URL 安全模块 Python 编译通过，目标差异检查通过。所有网络请求都由本地替身模拟。
- **边界：**仅处理可识别的查询参数认证名称；真实 ArcGIS/第三方跳转链未连接验证，未知厂商的自定义认证参数需显式适配。慢测未运行。

### 2026-10-27 GeoSource 代理拦截无 Origin 的跨站请求

- **发现并修复：**GeoSource 代理原先只在请求带 `Origin` 时校验浏览器来源。跨站图片/瓦片类 GET 请求可能不带 `Origin`，绕过这项检查并借本机代理访问用户可达的服务。现在代理在处理目标 URL 前拒绝浏览器 `Sec-Fetch-Site: cross-site` 请求，包括没有 `Origin` 的情况；正常同站瓦片请求继续可用。
- **验证：**新增无 `Origin`、带跨站 Fetch Metadata 的拒绝用例，并确认拒绝发生在出站代理查找前。`test_geosource_proxy_redaction.py` 与 `test_local_cors_policy.py` 共 **23 项通过**；pytest 缓存目录有一条权限警告，不影响结果。
- **边界：**Fetch Metadata 是现代浏览器提供的请求来源信号，不是客户端身份认证；不带 Origin 且不提供该信号的非浏览器客户端仍可访问本机 API。真实浏览器跨站嵌入尚未做端到端验证。

### 2026-10-27 GeoSource 显式数据库路径缺失时停止回退

- **发现并修复：**设置 `GEOSOURCE_DB_PATH` 后，如果文件不存在，目录服务过去会静默选择默认快照或同级 GeoSource 快照；用户可能因此看到另一份数据，且误以为配置生效。现在显式配置始终优先，文件缺失由数据库连接给出包含所选路径的明确错误；未设置变量时原有快照发现顺序不变。
- **验证：**新增回归用例：指定不存在的临时数据库时，路径解析保留该选择，连接抛出明确的 `FileNotFoundError`，不回退读取其他快照。后续目录检索边界检查新增超大页码用例；`backend/tests/test_geosource.py` 共 **11 项通过**，覆盖路径选择、数据库读取、检索、分页与 API 端点。
- **边界：**本次只验证路径选择和缺失文件反馈；有效自定义数据库的 schema 兼容性仍取决于其包含预期的 `master` 与 `layers` 表。

### 2026-10-27 GeoSource 搜索页码限制

- **发现并修复：**目录检索原先将用户传入的页码直接换算为 SQLite `OFFSET`。极大的页码会超出 SQLite 整数绑定范围并使搜索接口失败；页码超过结果末页时，前端也会收到一个不存在的当前页。现在先根据总页数限制当前页，再计算查询偏移量；超出范围时返回最后一页。
- **验证：**新增 `page=10**100` 回归用例，确认搜索返回最后一页且有结果；`backend/tests/test_geosource.py` 共 **11 项通过**。pytest 缓存目录权限警告不影响结果。
- **边界：**页数在总数查询后确定；底层数据库若并发变化，计数与列表查询之间仍可能出现短暂不一致，但不会再由用户输入导致整数偏移量溢出。

### 2026-10-27 GeoSource 免费状态展示

- **发现并修复：**实际快照中有 7 条服务的 `free` 字段为“部分免费”，`is_free` 字段却为“是”。目录搜索此前不返回 `free`，卡片据此把这些项目标成“免费”。现在 API 返回详细收费说明，卡片优先标注“部分免费”；筛选文案也明确覆盖免费或部分免费服务。
- **验证：**后端回归检查确认 Esri World Geocoding Demo 同时保留这两个原始字段；`backend/tests/test_geosource.py` **12 项通过**。新增前端渲染用例验证卡片显示 “Partially free”；`frontend/tests/geosource_layer_capacity.test.cjs` **10 项通过**，GeoSource 与 i18n 脚本语法检查通过。
- **边界：**筛选仍依照快照的 `is_free` 标记，因此部分免费记录会出现在“免费或部分免费”筛选结果里；目录信息不代表实时价格或服务可用性。

### 2026-10-27 GeoSource 官方链接尾注

- **发现并修复：**快照里有 9 条 `official_url` 把括号备注直接拼在域名后（例如“待直接验证”），浏览器会把备注编码为 URL 路径，导致卡片链接和复制地址都指向错误位置。现在卡片只展示和链接首个备注前、可解析的绝对 HTTP(S) 地址；空值或说明文本不再被转成 localhost 地址。
- **验证：**新增前端渲染用例，以安徽省开放数据记录为例，确认链接与复制地址都只取 `https://data.ah.gov.cn/`，不包含 URL 编码后的备注；`frontend/tests/geosource_layer_capacity.test.cjs` **11 项通过**，`node --check frontend/js/geosource.js` 通过。
- **边界：**只修正界面中这类可解析 URL 的展示，不验证目标站点当前可访问，也不自动改写或清洗数据库快照中的原始记录。

### 2026-10-27 GeoSource 缺少有效地址的卡片提示

- **发现并修复：**仓库快照中有 2 条公共数据目录记录的 `service_url`、`official_url` 和 `docs_url` 均为空；此前卡片仍显示空 URL 输入框和复制按钮，点击没有可复制内容。现在无有效 HTTP(S) 地址时显示明确提示，并隐藏空输入框和复制按钮。
- **验证：**新增 DS-1129 的卡片渲染用例，确认显示缺失地址说明且不渲染复制按钮；`frontend/tests/geosource_layer_capacity.test.cjs` **12 项通过**，`node --check frontend/js/geosource.js` 通过。
- **边界：**该提示不补造官网或服务地址；目录维护者补齐来源后，用户仍需自行确认服务是否可用。

### 2026-10-27 execute_python 子进程环境凭据过滤

- **发现并修复：**`execute_python` 子进程此前复制全部父进程环境，只移除 `AMAP_KEY`，其他常见模型、云服务或数据库凭据可能被本地执行代码读取。现在按环境变量名过滤包含 key、secret、token、password、credential、auth、private key、数据库 URL/URI、连接串或 DSN 等常见标记的变量，并移除含用户名/密码的 HTTP(S) 代理环境变量；未认证代理与一般运行时环境保留。
- **验证：**凭据回归测试用合成值覆盖 `AMAP_KEY`（小写名称）、`OPENAI_API_KEY`、`AWS_SECRET_ACCESS_KEY`、`GOOGLE_APPLICATION_CREDENTIALS`、`DATABASE_URL`、Azure 存储 Key/连接串、`GDAL_HTTP_USERPWD` 和含 userinfo 的 `HTTPS_PROXY`；确认敏感变量未传入、无认证 `HTTP_PROXY` 和一般运行时变量保留。`test_execute_python_credentials.py` 与 AST 安全用例共 **7 项通过**。
- **边界：**这是按名称进行的尽力过滤，不是秘密扫描；自定义命名、文件读取、网络访问和 CPU/内存仍未隔离，不能把该子进程视为安全沙箱。未运行真实用户代码。

### 2026-10-27 生成 HTML/SVG 产物隔离与输出路径

- **发现并修复：**聊天把本机 `/output` 的 HTML 作为同源页面显示，也提供新标签打开；其中脚本可能继承工作台源的权限。现在 HTML/HTM/XHTML、SVG 与 XML/XSL 类输出由响应头 `Content-Security-Policy: sandbox allow-scripts` 限制为不含 `allow-same-origin` 的独立源，交互脚本仍可运行；聊天内 iframe 也单独启用 `sandbox="allow-scripts"`。同时 `/output` 原路径检查只做字符串规范化，符号链接可能指向输出根目录外；现在直达与时间戳回退匹配都在 realpath 后复核边界。
- **验证：**后端测试确认 HTML、SVG、XHTML 响应包含隔离 CSP 与 `nosniff`，并通过模拟 realpath 将目标指向根目录外来验证 403；`test_output_file_safety.py` **2 项通过**。前端聊天生命周期测试 **23 项通过**，包含 iframe sandbox 守卫；`node --check frontend/js/chat.js` 通过。
- **边界：**路径越界测试模拟解析结果，没有创建真实 Windows 符号链接。浏览器 CSP/下载按钮未做真实桌面端验收；`allow-scripts` 保留交互图表脚本，但不授予其同源访问权。此修复不构成 Python 执行隔离。

### 2026-10-27 本机 API 跨站浏览器请求

- **发现并修复：**全局 CORS 会阻止外站读取 API 响应，但不会阻止浏览器向本机发送请求；`/api/upload` 支持 multipart/form-data，可能被恶意网页用作跨站上传。进一步核对发现 `/api/projects/{id}` 虽是 GET，也会打开工程并切换当前图层。现在所有 `/api/` 浏览器请求都在路由执行前验证来源：拒绝非 loopback Origin 和跨站 Fetch Metadata，接受 localhost/127.0.0.1/::1 前端，也允许不带浏览器来源头的 MCP/本机客户端。
- **验证：**带外站 Origin 或仅带 cross-site Fetch Metadata 的 multipart 上传、跨站打开工程请求均在处理前返回 403；loopback 前端的 multipart 上传仍可达处理器。`test_local_cors_policy.py`、`test_upload_safety.py` 与 `test_output_file_safety.py` 当前共 **18 项通过**；`backend/main.py` 编译通过，目标差异检查通过。上传处理使用替身，没有写入真实上传数据。
- **边界：**无 Origin 且不提供 Fetch Metadata 的非浏览器客户端仍可访问，来源头不是身份认证；实际客户端认证及网络暴露保护仍需独立设计。浏览器端到端行为尚未验证。

### 2026-10-27 GeoSource 认证 XYZ 的反向行号模板

- **发现并修复：**手动输入 Key 后，GeoSource 会通过 `URL` 对象添加认证参数；该处理会把 XYZ 瓦片模板中的花括号编码。`{z}/{x}/{y}` 有恢复逻辑，但常见的 `{-y}` 反向行号模板没有恢复，导致已接入的 XYZ 瓦片请求无法按预期展开。现在添加 Key 和清理保存地址时都保留 `{-y}` 模板。
- **验证：**新增已保存服务重新授权用例，确认代理目标保留 `{-y}` 并附加本次 Key、工程图层地址仍无 Key。`geosource_layer_capacity.test.cjs` **13 项通过**，`node --check frontend/js/geosource.js` 与目标差异检查通过。
- **边界：**使用前端模拟地图/请求验证模板和凭据流转，未连接真实 XYZ 服务或进行浏览器地图渲染验收。

### 2026-10-27 GeoSource 公网 HTTP 凭据传输

- **发现并修复：**本机代理虽能安全转发用户手动输入的 Key，但公网 `http://` 目标会以明文传输 URL 查询参数。现在只要目标 URL 含已识别或用户指定的非空 Key 参数，公网或 DNS 无法确认的 HTTP 请求都会在出站连接前拒绝并提示改用 HTTPS；明确解析为内网的 HTTP 服务仍可使用。连接时还会重新检查这一条件，避免初次检查与实际连接之间 DNS 分类变化后把 Key 发往公网 HTTP。无 Key 的公开 HTTP 服务策略不变。
- **验证：**新增公网/未知 HTTP 凭据拒绝、明确内网 HTTP 保留、实际共享 opener 连接前拦截以及代理选项传递用例。`test_geosource_proxy_redaction.py` **25 项通过**；Python 编译与目标差异检查通过。界面中英文说明同步提示公网 HTTPS 与内网 HTTP 的差别。
- **边界：**DNS 使用受控替身；没有向真实地图服务发送 Key。内网 HTTP 内容仍未加密，只适用于用户明确选择并信任的本机/内网环境。

### 2026-10-27 GeoSource 自助接入认证参数识别

- **发现并修复：**前端提示认证参数的规则不一致：URL 清理把任何包含 `key` 的名字都当成密钥，可能删除合法参数 `monkey`；但提示规则又漏掉 `access_key`，与后端的认证参数识别不一致。目录若将含 `access_key=` 的服务误标为免密，用户此前不会被提示补 Key，保存后仍会丢掉凭据字段。现在前端提示与 URL 清理共用边界化的参数名判断，识别 `access_key`，且不会把 `monkey` 等无关名称当成凭据。
- **验证：**新增目录免密标记下的 `access_key` 手动接入/无 Key 持久化用例，以及 `monkey` 参数保持不变用例。`geosource_layer_capacity.test.cjs` **15 项通过**；`node --check frontend/js/geosource.js` 与目标差异检查通过。
- **边界：**敏感参数判断按名称启发式匹配；厂商的自定义认证参数仍需用户手动指定，未连接真实 Provider。

### 2026-10-27 GeoSource 源地址内嵌账号密码

- **发现并修复：**服务目录/导入工程提供的 `https://user:password@host/...` URL 会被 urllib 作为 Basic Auth 凭据发送，但 GeoSource 的接入说明只支持查询参数 API Key；前端清理服务元数据时也可能悄悄移除账号密码而继续显示连接成功。现在前端在新接入和恢复旧图层前明确拒绝这类 URL，后端代理也在联网前拒绝并说明当前不支持账号密码认证；普通错误脱敏用例改为单独验证查询参数 Key，避免把被拒绝的地址当作可请求目标。
- **验证：**后端用例覆盖用户名密码不同组合的出站前拒绝和不回显凭据，`test_geosource_proxy_redaction.py` **28 项通过**；前端用例确认不添加图层、不发请求，`geosource_layer_capacity.test.cjs` **16 项通过**。相关 Python 编译、JavaScript 语法与目标差异检查通过。
- **边界：**不支持嵌在 URL 里的 Basic Auth；如服务仅支持账号密码或请求头/OAuth，需要另行设计认证方式，不能用本次查询参数 Key 窗口替代。

### 2026-10-27 URL GIS 与云原生数据源的公网明文凭据

- **发现并修复：**GeoSource 已限制带 Key 的公网 HTTP，但同一共享重定向 opener 也服务于云原生 COG/PMTiles/矢量回退下载，URL GIS 则用 `PinnedAddressHTTPAdapter`。此前这些通道仍可能向公网 HTTP 发送 `token`/`api_key` 查询参数，或由 URL userinfo 生成明文 Basic Auth。现在两种 HTTP 连接实现都在最终 DNS/IP 复核时阻止公网或无法确认目标上的已识别查询凭据和 URL userinfo；明确内网直连仍可用。HTTPS 公开服务照常通过 TLS 连接。
- **验证：**`test_geosource_proxy_redaction.py` 覆盖共享 opener 的明文查询 Key/userinfo 拒绝和 GeoSource 的带 Key/账号密码入口；`test_url_gis.py` 覆盖 Requests 适配器在连接前阻止公网 HTTP API Key，同时保留既有 DNS 重绑定拒绝行为。两模块共 **89 项通过**；相关 Python 编译和目标差异检查通过，测试使用 DNS 替身且未访问真实公网。
- **边界：**“已识别凭据”按常见认证参数名匹配；未识别的厂商自定义参数需显式加入识别规则。明确内网 HTTP 仍为明文，公网 HTTP 不带识别凭据时策略不变。

### 2026-10-27 云原生数据源跨主机跳转凭据

- **发现并修复：**云原生 COG/PMTiles/GeoParquet/FlatGeobuf 的 Range 中继和下载回退使用共享重定向 opener，但此前只有 GeoSource 调用显式启用跨源认证参数清除。公网源重定向到 CDN 时，如果 `Location` 再次包含原 `token`/`api_key`，Key 可能被带到新主机。现在共享 opener 默认会识别初始 URL 中常见的敏感参数，并在跨主机、端口或协议跳转时移除；同源跳转保留，CDN 新签名和其他普通参数保留。GeoSource 可继续额外提供厂商自定义的参数名。
- **验证：**新增默认 opener 行为用例，确认同源保留、跨源剥离、普通格式参数保留并记录凭据已剥离；GeoSource 代理、URL GIS 和云原生非慢测共 **125 项通过**，4 项慢测排除。测试使用 DNS/服务替身，无真实网络请求。
- **边界：**自动发现仅覆盖常见认证参数名；自定义厂商参数需 GeoSource 显式传入。跨主机且需要把原 Key 传给 CDN 的服务会收到未认证响应，应改用服务方直连地址或其 CDN URL。

### 2026-10-27 云原生跨源认证失败提示

- **发现并修复：**共享重定向策略会在跨源时剥离 Key，但云原生 Range 中继可能只把上游 401/403 转成普通读取失败；下载回退和 PMTiles 也只返回 HTTP 错误，用户难以判断是 Key 被保护性剥离。现在只有“已剥离凭据且上游返回 401/403”时才提示改用服务方直连地址；其他 HTTP 错误继续按普通状态码处理，错误文案不带原 URL 或 Key。
- **验证：**新增下载回退与 PMTiles 认证失败提示用例；`test_cloud_native.py -m "not slow"` **37 项通过**、4 项慢测排除；Python 编译与目标差异检查通过。使用假 opener 和哨兵 Key，不连接真实服务。
- **边界：**Range 中继向 GDAL 返回 502 和安全提示正文；Rasterio/GDAL 在不同环境中如何呈现该响应仍需真实桌面端验收。

### 2026-10-27 OSMnx 导入触发的隐藏网络探测

- **发现并修复：**`execute_python` 只要检测到用户代码导入 OSMnx，就会在用户代码前注入 `requests.get`，依次探测最多五个 Overpass 镜像，每个最多等待 5 秒；即使代码只处理本地数据也会访问外网，且这段请求由注入代码绕过了用户代码的导入白名单。现在删除自动镜像探测，导入 OSMnx 不产生额外网络请求；获取在线 GIS 边界和要素继续走专用工具。
- **验证：**新增模拟子进程用例，让代码只导入 OSMnx 并检查生成脚本不含 Overpass 镜像或 `requests.get` 探测。`test_execute_python_credentials.py` 与 AST 安全用例共 **8 项通过**；没有运行 OSMnx 或发起真实网络请求。
- **边界：**`execute_python` 仍不是网络沙箱；用户代码通过允许库触发的主动网络请求仍可能发生。没有改变公开部署的执行隔离边界。

### 2026-10-27 GeoSource 带 Key 瓦片失败提示

- **发现并修复：**带 Key 的 WMS/XYZ 图层添加后，如果代理瓦片请求被安全策略拒绝或服务端拒绝，原先只显示“添加成功”，地图可能空白。现在首次瓦片失败时会给出一次提示：公网服务请使用 HTTPS，否则检查 Key 参数名和服务权限；提示不包含 Key，也不会反复刷屏。
- **验证：**`frontend/tests/geosource_layer_capacity.test.cjs` **18 项通过**；WMS、XYZ 分别验证重复 `tileerror` 只提示一次且哨兵 Key 不出现在提示中。前端脚本语法检查及目标差异空白检查通过。
- **边界：**图层创建成功仍不代表服务瓦片可用；提示需要 Leaflet 触发 `tileerror`，且仅对通过 GeoSource 凭据对话框录入 Key 的图层生效。

### 2026-10-27 GeoSource 上游文档响应隔离

- **发现并修复：**GeoSource 代理会把服务方的 `Content-Type` 用于本机同源响应，因此直接打开代理地址时，恶意上游的 HTML/SVG 可能被浏览器当作工作台页面。现在所有代理响应都带 CSP sandbox 与 `default-src 'none'`，将文档内容限制在隔离环境；瓦片和数据请求仍保留上游 MIME 类型与响应字节。
- **验证：**新增模拟上游 HTML 响应的回归用例，并复跑代理安全测试文件，**32 项通过**；Python 编译和目标差异空白检查通过。测试使用假上游，不连接真实服务。
- **边界：**浏览器实际如何呈现特定 GIS 客户端所需的 SVG/XML 瓦片仍需桌面端验收；CSP sandbox 只针对代理响应被当作文档打开的情形提供隔离。

### 2026-10-27 工程栅格资源响应隔离

- **发现并修复：**工程导入验证栅格资源路径及文件存在性，但资产路由按扩展名返回响应，不能假定导入文件内容可信。现在资产响应统一带 `nosniff` 和 CSP sandbox，降低伪装成栅格的 HTML/SVG 在同源打开时执行脚本的风险。
- **验证：**新增 SVG 资产响应头用例；`test_project_raster_persistence.py` **18 项通过**，覆盖既有资产保存/导入/恢复；Python 编译及目标差异空白检查通过。测试使用本地临时文件。
- **边界：**该响应策略隔离浏览器文档打开行为，不验证 GDAL 对用户导入栅格文件的解析安全性。

### 2026-10-27 下载响应文件名与工程 ZIP 链路

- **发现并修复：**Shapefile 导出把图层名直接拼入 `Content-Disposition`，工程导出则使用路径参数生成下载名；控制字符可破坏响应头，中文文件名也缺少可靠编码。现在两条路由统一生成净化的 ASCII 兼容名与 UTF-8 `filename*`。新增换行、引号和中文名称回归，`test_output_file_safety.py` **3 项通过**。
- **验证补充：**工程 ZIP 解压器在写盘前会检查归档路径、目标根目录边界和符号链接；原用例未直接覆盖符号链接。新增符号链接条目用例确认拒绝后不留工程目录；`test_layer_group_persistence.py` **37 项通过**。
- **边界：**ZIP 路径检查覆盖已测试的穿越、绝对路径和符号链接情形；超大包限制仍按独立压缩/展开大小与条目数门槛执行。

### 2026-10-27 Python 执行前缀与输出回收边界

- **发现并修复：**`execute_python` 的 AST 检查拒绝用户直接导入 `os`，但注入前缀为了创建输出目录把模块留在全局变量 `_os` 中，用户代码可以借该别名调用系统接口。现在前置目录初始化后立即删除 `_os`，新增真实子进程回归确认用户代码只能得到 `NameError`。输出回收也会跳过符号链接及解析到本次执行目录之外的路径，避免自动复制链接目标到工作台输出目录。
- **验证：**`test_execute_python_credentials.py` **6 项通过**，覆盖别名不可用、链接输出不被回收、环境凭据过滤和 OSMnx 不触发隐藏探测；Python 编译与目标差异空白检查通过。
- **边界：**这是对脚本前缀和自动输出回收的收紧；用户代码仍运行于本机子进程，仍不是文件、网络或资源隔离的操作系统级沙箱。

### 2026-10-27 Python 输出文件名冲突

- **发现并修复：**Python 执行器在输出目录已有同名文件时只追加到秒的时间戳；同一秒再次生成同名图表或执行重命名时会覆盖旧结果。现在输出复制和图表重命名都通过唯一候选名避开已有文件（包括悬空链接路径）。
- **验证：**固定系统时间并预置同名目标，新增回归确认连续两次重命名都生成独立文件，旧目标字节保持不变；`test_execute_python_credentials.py` **7 项通过**，Python 编译及目标差异空白检查通过。
- **边界：**候选路径使用文件系统独占创建，遇到已存在文件或链接时改用随机 UUID 后缀；写入失败会清理占位目标。

### 2026-10-27 导出文件名响应头安全

- **发现并修复：**Shapefile 导出把图层名直接拼入 `Content-Disposition`，工程导出则使用路径参数生成下载名；控制字符可破坏响应头，中文文件名也缺少可靠编码。现在两条路由统一生成净化的 ASCII 兼容名与 UTF-8 `filename*`，控制字符只会编码进下载名，不会进入原始头部。
- **验证：**新增恶意换行、引号与中文名称回归用例；`test_output_file_safety.py` **3 项通过**，覆盖工程与 Shapefile 导出；Python 编译及目标差异空白检查通过。
- **边界：**该修复约束下载响应头，不限制用户在文件内部使用的工程名或图层名。

### 2026-10-27 工程恢复内容与聊天图层展示

- **发现并修复：**导入工程会恢复历史 AI 消息和图层样式；此前 AI Markdown 允许原始 HTML、危险链接和外部图片自动加载，图层面板也把恢复的图层 ID、颜色和透明度直接放进 HTML。现在 AI 消息通过受限 Markdown 渲染器，原始 HTML 显示为文本，只允许安全链接，图片仅允许相对路径；图层 ID 和颜色先转义/校验，透明度限制在 0–1。历史用户消息仍作为转义后的文本恢复。
- **验证：**聊天渲染、图层面板及工程恢复三个前端测试文件共 **62 项通过**；`chat.js`、`layers.js` 语法检查和目标差异空白检查通过。用例覆盖原始 HTML、可执行链接、外部追踪图片、相对图片，以及伪造图层 ID/颜色/透明度。
- **边界：**相对图片仍可访问应用同源资源；当前验证覆盖单元测试路径，没有替代真实桌面浏览器中的工程恢复验收。

### 2026-10-27 工程恢复图层 ID 的检查器复核

- **发现并修复：**继续沿工程恢复的图层 ID 检查后发现，列表已转义的 ID 在打开属性检查器时又被原样写入工具栏按钮属性，可重新构造 HTML 属性注入。现在检查器按钮也转义 ID；重命名、改色和透明度同步的属性选择器先按 CSS 规则转义 ID。
- **验证：**新增恶意恢复 ID 打开属性检查器的回归用例；聊天、图层面板、工程恢复三个前端测试文件共 **63 项通过**。
- **边界：**测试覆盖检查器 HTML 的生成和选择器调用；桌面端交互仍需通过真实工程手动验收。

### 2026-10-27 GeoSource WMS 详情接入认证

- **发现并修复：**搜索卡片的 WMS 接入会在目录标注需认证或 URL 暴露凭据参数时要求用户输入 Key；展开详情后的子图层“上图”按钮此前绕过该流程，直接创建无凭据的瓦片图层。现在详情按钮复用同一认证流程并保留用户选定的子图层；服务详情查询失败时也保留选择，并只在本次请求中使用 Key。
- **验证：**新增认证 WMS 子图层成功接入和详情查询失败降级两项回归；`geosource_layer_capacity.test.cjs` **20 项通过**，覆盖 Key 不写入图层工程元数据。
- **边界：**测试使用本地模拟服务；真实供应商 WMS 对具体 Key 参数与子图层的兼容性仍需用户接入时验证。

### 2026-10-27 地图要素标签与图表提示文本

- **发现并修复：**上传或远程 GeoJSON 属性可以配置为地图标签；Leaflet 会把字符串工具提示按 HTML 解析。此前普通字段标签和图表联动提示直接传入属性值，可能把恶意数据解释成页面标记。现在两条路径都先转义为文本。
- **验证：**新增包含 `<img onerror>` 与 `<svg onload>` 的要素属性回归用例，确认两个工具提示均输出转义文本；`map_layer_visibility.test.cjs` **11 项通过**。
- **边界：**覆盖 Leaflet 2D 标签与图表联动工具提示；3D 属性面板已单独确认使用 HTML 转义，本次未改动其渲染方式。

### 2026-10-27 工程恢复损坏记录容错

- **发现并修复：**工程恢复会先清理当前工作区，再直接遍历保存的消息和图层；若旧工程或导入工程含空记录、错误类型的消息/集合，恢复可能中断并留下不完整状态。现在恢复前筛掉无效消息与图层记录，对错误格式的图层分组使用空列表，并汇总提示跳过数量，让剩余有效内容继续恢复。
- **验证：**新增混合正常与损坏记录的回归用例，确认有效消息、图层仍恢复，异常消息、空图层和错误分组不会中断流程；`project_load_race.test.cjs` **13 项通过**。
- **边界：**容错处理覆盖消息、图层记录和分组集合的顶层形状；单条图层记录内部嵌套资源的完整性仍由各恢复路径处理。

### 2026-10-27 GeoSource 密钥转发与跳转边界复核

- **复核结果：**当前代理仅接受 HTTP(S) 地址；公网或无法确认地址使用 HTTP 并带查询参数密钥时拒绝；跨来源跳转会剥离认证参数，公网服务跳转内网或解析结果不明确时拦截；明确输入的内网地址仍可直连。手动 Key 通过本机代理随请求发送，图层元数据只保留服务 URL 和参数名，不保留 Key。该规则与用户已选边界一致，本轮未改动代理行为。
- **验证：**`test_geosource_proxy_redaction.py` 与 `test_external_url_redaction.py` 共 **35 项通过**，覆盖密钥剥离、公网跳入内网拦截、显式内网地址及日志脱敏。
- **边界：**自动化用例使用解析与代理模拟；没有替代真实服务商端点的联网接入验证。

### 2026-10-27 单图层恢复失败隔离

- **发现并修复：**上一轮已处理坏记录集合和矢量渲染异常；继续检查单条记录内部资源时发现，栅格叠加或图层注册等恢复步骤若抛错，仍会中断整个工程恢复。现在每条图层独立捕获恢复错误并加入现有失败汇总，后续图层继续加载。
- **验证：**新增栅格恢复抛错后验证后续矢量图层仍显示、工程恢复仍完成且提示损坏图层；`project_load_race.test.cjs` **14 项通过**，目标差异空白检查通过。
- **边界：**此处理隔离单图层同步恢复异常；GeoSource 的网络瓦片加载仍是异步过程，会沿用其自身错误提示。

### 2026-10-27 上传请求体预解析限额

- **发现并修复：**`/api/upload` 虽然在保存文件时限制单文件大小，但该检查发生在 Starlette 解析 multipart 并将上传内容暂存之后，超大请求仍可能先占满临时磁盘。现在在 multipart 解析前限制上传请求体为 301 MiB（300 MiB 文件上限加 1 MiB 表单开销）；超限声明长度会立即返回 413，分块请求也会在累计超限时拒绝。原有工程导入限额保持独立。
- **验证：**新增真实 ASGI 路由回归，确认超限上传在处理函数前返回 413；`test_upload_safety.py`、`test_upload_handoff.py`、`test_upload_vector.py`、`test_upload_raster.py` 共 **36 项通过**；工程导入请求体限制相关回归 **4 项通过**。
- **边界：**上传主体以单文件 300 MiB 上限设计；multipart 额外允许 1 MiB 元数据空间。当前限制覆盖 HTTP 请求体，反向代理或服务器级限制仍可作为部署侧额外保护。

### 2026-10-27 工程名称类型异常恢复

- **发现并修复：**导入器校验了图层和消息集合，但没有校验工程名称类型；JSON 对象等非文本名称可进入索引，并让前端最近工程横幅或恢复完成提示在 `.replace()` 处报错。导入时现在为非字符串名称写入可读默认名；前端加载旧数据时也使用安全默认标题，避免清空工作区后因标题类型异常中断。
- **验证：**新增后端导入/工程索引名称回归和前端非文本工程名恢复回归；`project_load_race.test.cjs` **15 项通过**，`test_layer_group_persistence.py -k project_import` **16 项通过**。
- **边界：**仅把无效名称替换为默认显示名；其他工程内容保持不变。

### 2026-10-27 工程激活的历史消息过滤

- **发现并修复：**前端恢复会跳过空消息、未知角色和非文本内容，但后端打开工程时此前仍把完整历史列表放入 AI 会话；单条损坏记录可能污染后续模型请求。现在后端激活工程时只加载 `user`/`assistant` 且内容为文本的记录；工程原始历史仍保留给前端显示恢复提示。
- **验证：**新增含空记录、未知角色和错误内容类型的工程激活回归，确认有效问答保留、异常记录不会进入活动会话；`test_layer_group_persistence.py` **39 项通过**。
- **边界：**这只净化激活后的运行时会话，不会改写磁盘上的历史记录；前端仍负责提示并跳过无效记录。

### 2026-10-27 工程激活的单图层注册隔离

- **发现并修复：**前端可以跳过恢复失败的图层，但 `/api/projects/{id}` 打开工程时会先在后端注册全部图层；单条无效 GeoJSON 或栅格资源会触发整体回滚，前端因此拿不到工程数据，无法恢复其余有效内容。现在工程激活逐条隔离注册错误、保留其余有效图层，并将失败图层名随打开响应返回；前端汇总提示这些图层无法供分析工具使用。其他调用默认仍保持严格错误行为。
- **验证：**新增服务端混合有效/无效图层打开回归，确认有效图层被注册且坏图层列入警告；前端回归确认显示服务端注册失败汇总。`test_layer_group_persistence.py` **40 项通过**，`project_load_race.test.cjs` **15 项通过**。
- **边界：**失败图层的原始工程数据仍保留，前端会独立尝试显示；自动提示说明其后端分析注册失败，没有删除或改写图层内容。

### 2026-10-27 图层删除与地图清理故障隔离

- **发现并修复：**删除图层时，前端先从列表移除，再调用地图引擎清理；若地图清理同步抛错，原流程会提前退出，后端注销根本不会排队，已删除图层仍可能被 AI 工具查询。现在地图清理失败会记录并提示用户检查残留显示，同时继续执行带版本令牌的后端注销。
- **验证：**新增地图 `removeLayer` 抛错回归，确认图层从列表删除、后台 unregister 仍执行、用户收到地图残留提示；`layer_panel_rename.test.cjs` **28 项通过**。
- **边界：**地图引擎拒绝清理时，残留图像可能仍显示到刷新或重新清理；后端分析注册会按原队列注销，测试覆盖该分支。

### 2026-10-27 任务历史卡片动态字段转义

- **发现并修复：**分析任务历史从 `localStorage` 恢复；渲染时此前把 `status` 拼入 CSS 类和文本、把 `id` 拼入多个属性，格式损坏或手工编辑的持久记录可注入卡片标记。另外通用 HTML 转义工具未加载时的备用路径会原样返回文本。现在只使用已知状态类和固定状态文案，未知状态显示“未知状态”，任务 ID 转义后再写入属性，且提供独立的 HTML 转义备用实现。
- **验证：**新增恶意持久化 ID/状态回归，确认不生成事件属性并使用固定未知状态展示；`task_cancelled_status.test.cjs` **6 项通过**。
- **边界：**修复覆盖任务卡片当前动态字段；不把 `localStorage` 视作可信数据源，也不清理或迁移已有任务记录。

### 2026-10-27 Leaflet 图层归属文本转义

- **发现并修复：**栅格、XYZ 和 WMS 图层把用户/服务提供的图层名或归属说明传给 Leaflet attribution；该控件会按 HTML 内容处理字符串，异常工程名或目录服务元数据可能注入标记。现在三条入口统一将归属文本转义后传入 Leaflet，保留可读文字、不把输入解释为 HTML。
- **验证：**新增 `<img onerror>` 与 `<svg onload>` 归属回归，覆盖栅格、XYZ、WMS 三种图层；`map_layer_visibility.test.cjs` **12 项通过**。
- **边界：**提供者原本包含的 HTML 链接会作为文本显示；归属说明仍可阅读，链接不再可点击。

### 2026-10-27 GeoSource 密钥请求跨主机跳转

- **发现并修复：**GeoSource 代理原先在带密钥请求跨主机跳转时删除密钥后继续请求；用户难以判断跳转目标是否可信。现在检测到带认证参数的跨主机跳转就停止请求，并返回不含密钥的说明；无密钥请求仍按现有公开/内网地址规则处理。
- **验证：**新增重定向处理器回归，确认认证跨主机跳转被拒绝、密钥不会进入错误文本；GeoSource 代理测试 **33 项通过**。
- **边界：**服务商若依赖带密钥跨主机跳转至 CDN，当前会失败；请使用其提供的原始直连服务地址。用户明确输入的内网服务仍可直接访问。

### 2026-10-27 聊天纯文本消息渲染

- **发现并修复：**聊天气泡把用户消息和“无 Markdown”状态文本直接写入 `innerHTML`。粘贴或恢复的 HTML 内容可能被浏览器当作标记执行。现在这类消息通过纯文本节点显示，AI Markdown 消息仍走受控渲染器。
- **验证：**新增恶意 HTML 用户消息回归，确认原文可见但不会写入 `innerHTML`；`chat_send_lifecycle.test.cjs` **25 项通过**。
- **边界：**Markdown 内容仍依赖聊天模块的链接/HTML 渲染器；本次只修正纯文本分支。

### 2026-10-27 网络服务区近似边界说明

- **发现并修复：**服务区实现使用“可达节点凸包 + 固定角度缓冲”，会填平道路空缺，可能把实际无法沿路到达的区域纳入多边形；此前面板和首次使用说明未揭示这一近似。现在结果面板和帮助文案明确标注估算边界，输出图层属性记录 `approximate` 与 `boundary_method`，功能说明也同步校准。
- **验证：**服务区后端测试确认输出方法元数据；前端回归确认结果卡显示“可能包含实际不可达区域，不代表精确等时圈”。`test_network.py` **14 项通过**，`network_request_lifecycle.test.cjs` **6 项通过**。
- **边界：**本次使结果更诚实可辨，但没有把凸包估算改造成精确等时圈；固定角度缓冲随纬度变化，真实道路覆盖范围仍需更准确的网络面构造与外部基准验证。

### 2026-10-27 GeoSource 只读 SQL 资源限制

- **发现并修复：**GeoSource 目录 SQL 虽然使用只读连接并只返回 100 行，但查询执行没有时限；带排序的递归 CTE 可迫使 SQLite 先计算大量结果，长期占用后台线程。现在限制语句长度为 10,000 字符，并通过 SQLite 进度回调在 5 秒后中断查询，返回可读的超时提示。
- **验证：**新增长递归查询超时和超长语句拒绝回归；`test_geosource.py` **14 项通过**。
- **边界：**执行时限是本机目录查询的保护上限；超出时用户需要缩小查询范围。只读连接和现有 SELECT/WITH 限制仍保留。

### 2026-10-27 工程正文与列表索引写入失败隔离

- **发现并修复：**工程正文原子写入后，如果最近工程索引写入失败，保存接口原先仍报失败；用户重试新工程时可能产生重复记录。现在正文作为权威数据保存成功后返回成功和索引警告，工程列表会检测正文与索引摘要不一致并从工程文件重建；自动保存与手动保存都会显示警告。容量修剪在最终索引写入前不再逐个写索引。
- **验证：**模拟索引写入失败并将容量设为 1，确认旧工程按容量修剪、新工程正文保留、保存返回 ID/警告且工程列表从磁盘重建。工程栅格/分组测试 **60 项通过**；前端保存同步/工作区测试 **34 项通过**，包含容量淘汰及索引写入故障覆盖。
- **边界：**若磁盘持续不可写，工程正文可保存但索引文件不能修复；本机列表在读取时会从正文重建，UI 会明确提示索引问题。损坏的工程正文仍保留其索引摘要供用户识别。

### 2026-10-28 本地文件 Range 与 gzip 响应一致性

- **发现并修复：**本地文件响应先按原文件字节生成 `206 Content-Range`，随后 gzip 中间件又压缩分段响应，导致 Content-Range 描述的字节与实际返回表示不一致。项目资产路由还对完整文件声明支持 Range，却没有把请求传入响应函数，始终返回 `200`。现在任意带 Range 的 HTTP 请求绕过 gzip 转换，项目资产路由也完整处理 Range/If-Range 请求。
- **验证：**两个新增回归在修改前分别复现为“Range 响应带 gzip”及“项目资产返回 200”；修复后 `backend/tests/test_output_file_safety.py` 与 `backend/tests/test_project_raster_persistence.py` 共 **49 项通过**，`git diff --check` 通过。
- **边界：**测试使用 FastAPI TestClient 与本地文件；没有替代浏览器缓存/媒体组件或真实桌面端完整打开工程验收。Range 请求均跳过 gzip，包括其他路由带 Range 头的请求，以保持范围语义一致。

### 2026-10-28 AI 旧式会话取消信号缓存淘汰

- **发现并修复：**旧式客户端只传 `session_id` 时，取消标记和全局取消代次保存在有上限的缓存中，但运行中的会话没有登记为活动项。只要随后有足够多不同会话的取消/启动记录，就会淘汰长任务的信号，任务可能继续运行。现在请求生命周期登记活动会话（兼容请求 ID 与旧式会话 ID），缓存优先淘汰非活动项；容量因活动项暂时超过上限时，会在任务结束后修剪回限额。
- **验证：**新增缓存压力回归，1000 个其他会话记录不再清掉活动旧式会话取消标记或其全局取消代次；`backend/tests/test_ai_cancellation.py` **18 项通过**，目标差异空白检查通过。
- **边界：**压力场景通过服务层内存状态确定性模拟；没有对超过 1000 个真实并发 GIS 请求做负载演练。当前共享 GIS 工作区锁限制了真实同时运行任务数。

### 2026-10-28 COG 预览 alpha 通道与颜色波段顺序

- **发现并修复：**COG 预览把前 3 个波段固定当作 RGB，忽略 alpha 并依赖固定波段顺序。4 波段透明影像会把透明区域渲染为不透明；alpha 放在首波段时还会把透明度当红色。现在根据 GeoTIFF 颜色解释选择 RGB，并将数据集 alpha 写入 PNG，nodata 仍按透明像素处理。
- **验证：**新增本地 GeoTIFF 回归覆盖标准 RGBA 的全透明、半透明、全不透明像素，以及 alpha-first 排列；新增用例修改前分别复现 RGB 输出和红通道错误。`backend/tests/test_cloud_native.py -m 'not slow'` **57 项通过**，4 项公开 URL 集成测试未运行；差异空白检查通过。
- **边界：**验证使用本地合成 GeoTIFF，没有使用外部 COG 或真实桌面地图验收；PNG 预览继续沿用现有的每通道百分位拉伸策略。

### 2026-10-28 COG 预览文件名秒级碰撞

- **发现并修复：**加载同名图层时预览文件名只含秒级时间戳；同一秒内重复或并行加载会覆写先前 PNG，已排队的图层操作随后会取到后一张影像。现在预览名增加随机唯一后缀，保留原来的可读前缀和时间信息。
- **验证：**固定时间并让模拟读取依次返回两份不同内容，修改前两次调用生成完全相同的 URL 且第一份内容被覆盖；修复后两个预览路径不同、文件内容均保留。`backend/tests/test_cloud_native.py -m 'not slow'` **58 项通过**，4 项联网慢测未运行；目标差异空白检查通过。
- **边界：**重现使用本地工具调用与模拟影像内容；未做多个真实模型会话的并发压力验证。

### 2026-10-28 COG 预览未进入工程保存链路

- **发现并修复：**COG 加载只把 PNG URL 作为临时地图操作返回，没有提供 raster 图层元数据；前端项目快照只收集图层面板记录，因此保存后重开会丢掉影像预览，而留下的范围框容易被误认为完整数据。现在 COG 操作携带明确的 preview-only 图层记录，前端纳入图层面板和自动保存；工程存储保留预览标记并复制 PNG；聊天提示说明像元分析仍需原始栅格文件。
- **验证：**修改前回归分别复现“COG 操作无 raster 元数据”和“工程保存丢弃 preview_only 标记”；修复后云原生/工程栅格两个后端测试文件共 **97 项通过**，4 项联网慢测未运行；聊天、工程恢复与地图可见性前端测试共 **73 项通过**；目标差异空白检查通过。
- **边界：**存储和恢复使用本地 COG 夹具/本地项目目录，前端使用模拟浏览器 DOM；没有真实远程 COG 或桌面浏览器验收。原始远程影像本身不下载到项目，仅保存其地图预览和脱敏来源引用。

### 2026-10-28 聊天栅格结果重复触发工程自动保存

- **发现并修复：**一条聊天栅格结果先由 `applyRasterResult` 保存，聊天结束处理又无条件保存一次；前端 harness 稳定记录到同一结果触发 2 次自动保存。现在聊天操作批次将栅格变更合并到该批次的结束保存；手动工具结果仍在批次完成时保存一次。
- **验证：**聊天回归修改前观察到 2 次自动保存，修复后精确断言为 1 次；聊天、工程恢复和地图图层测试共 **73 项通过**。工程保存队列保持串行语义。
- **边界：**重复请求以模拟 DOM/网络回调计数确认；未量测真实大工程请求耗时。本次证明减少一次前端 API 自动保存调用，不改变后端保存数据格式。

### 2026-10-28 普通 GeoTIFF 上传忽略 RGB 波段解释

- **发现并修复：**普通 GeoTIFF 上传预览固定读取波段 1/2/3，未按文件的颜色解释读取 RGB；alpha-first 或自定义波段顺序会生成错色预览。现在 RGB 标签齐全时按 red/green/blue 标签选波段，未标记或灰度数据继续使用原回退逻辑；alpha 通道仍单独用于透明度。
- **验证：**新回归先用相同 RGB 数据生成 conventional 与 alpha-first 两个本地 GeoTIFF，修复前预览 RGB 有 **38/48** 个通道值不一致；修复后 `backend/tests/test_upload_raster.py` 与 `backend/tests/test_upload_safety.py` 共 **38 项通过**。2 条 zipfile 重名警告来自刻意构造的重复 ZIP 成员安全用例；目标差异空白检查通过。
- **边界：**验证使用本地合成 GeoTIFF 和 API 测试客户端，没有使用外部数据或真实桌面地图验收。

### 2026-10-28 同名跨格式矢量并发上传覆盖图层

- **发现并修复：**两个不同扩展名但同一名称主体的矢量文件并发上传时，各自只原子预留了不同文件名；它们读取图层注册快照时都看不到对方，注册阶段因此覆盖同名图层。现在矢量注册在共享图层锁内检测占名并分配 `_1` 等后缀，响应返回实际登记名；注册仍保留可按 token 回滚的取消语义。
- **验证：**新增并发回归用屏障确保两种格式都在同名未登记状态下抵达注册点；修改前两响应都叫 `shared`，注册表只保留一份数据；修复后返回两个名称且两份各自的数据均保留。上传交接、栅格、安全和图层注册生命周期测试共 **102 项通过**；2 条重复 ZIP 成员警告来自安全用例的刻意输入。
- **边界：**并发时序及两种格式的读取器由测试桩控制，上传处理和注册逻辑为真实代码；没有用真实 GPKG/KML 文件或浏览器验收这一并发场景。

### 2026-10-28 工程 ZIP 解压大小元数据低报（已排除）

- **候选与复核：**怀疑攻击者伪造 ZIP 中央目录的解压大小，绕过工程导入的展开体积上限。构造 20,000 字节压缩成员并把声明大小改为 1 字节；`_extract_project_archive` 随后由 ZIP CRC 校验拒绝，目标文件实际写入 **0 字节**，未观察到体积限制绕过。
- **处理：**未改代码；这是用本地损坏 ZIP 做的定向边界复核，不是完整恶意归档压力测试。

### 2026-10-28 本地文件服务与网络请求边界复核

- **复核范围：**本地输出文件的 Range、压缩、符号链接与整型边界；GeoSource/URL 请求的重定向、DNS 固定、凭据脱敏和私网访问策略；工程单删索引失败及共享 Blob 保留。
- **结果与验证：**未发现新的可复现缺陷。`test_output_file_safety.py`、`test_url_gis.py`、`test_geosource_proxy_redaction.py` 共 **115 项通过**；工程删除/索引失败用例 **11 项通过**；上传 UI 与请求超时恢复 Node 用例 **28 项通过**；矢量上传和云原生解析用例 **61 项通过**，另有 4 项联网慢测按 `not slow` 标记未运行。
- **环境限制：**真实浏览器验收未完成：Playwright 缺少可用安装，安装时系统 C 盘返回 ENOSPC；桌面控制服务在枚举窗口前退出。未清理磁盘或用户文件。测试桩和 API 客户端结果不等于真实浏览器验收。

### 2026-10-28 AI 确认短指令绕过会话与共享状态锁

- **严重度：P2。发现并修复：**流式和非流式聊天在 Agent 会话锁/共享 GIS 状态锁之外处理“继续/取消”及待办清理；同会话已有任务运行时，第二条“继续”仍能注册并推送待办图层、消费确认状态，可能与进行中的地图操作竞态。现在待办短指令、选择状态和清理都在两把锁下处理；任一锁忙则返回 `busy`，不改待办或图层。合成 SSE 结果也透传 `busy` 字段。
- **复现与验证：**测试先持有两把锁、设置待加载点图层，再调用流式“继续”；修改前实际发生注册、推送并清除待办。修复后流式及非流式回归均确认返回忙状态、待办保留且注册表/待推送队列不变。AI 取消、流式初始化、选项回填与多轮状态共 **33 项通过**。
- **边界：**并发时序由本地测试控制，GIS 注册逻辑为真实代码；没有真实浏览器并发点击验收，桌面浏览器控制仍受上一轮记录的环境限制。

### 2026-10-28 归档任务恢复后会话索引未切换

- **严重度：P2。发现并修复：**同一会话归档任务 A、创建任务 B、再恢复 A 后，恢复接口返回成功但会话活跃索引仍指向 B，后续多轮 AI 请求可能继续使用 B 的上下文。恢复任务现在在任务持久化成功后、同一把锁内切换会话索引。
- **复现与验证：**修改前新增回归用例稳定失败，`find_active_task_for_session` 返回 B 而非刚恢复的 A。另覆盖恢复写盘失败时保留 B 和 A 的归档状态。任务管理、任务上下文复用、GIS 操作上下文测试共 **27 项通过**。
- **边界：**使用本地 pytest 和隔离临时任务目录；未进行真实浏览器点击验收。

### 2026-10-28 工程删除索引故障复核（未发现新问题）

- **复核范围：**单工程删除后的索引恢复、共享 Blob 引用、删除活动工程时清理图层注册状态，以及异常图层条目；同时复核工程导入时索引写入失败的成功/警告契约。
- **结果与验证：**未发现新的可复现缺陷。上述工程删除、共享资源和导入索引故障用例共 **6 项通过**；验证基于本地 pytest 与隔离工程目录。

### 2026-10-28 被替换的聊天请求迟到失败修改新请求界面

- **严重度：P2。发现并修复：**新请求替换旧请求后，旧请求若迟到返回非取消错误，旧 catch 分支会向当前聊天区显示过期错误并重置共享输入框占位文字。现在旧代次只结束自己的任务/执行卡，不再更改新请求界面。
- **复现与验证：**用流式请求延迟返回失败构造旧请求在新请求启动后的时序；修改前输入框由新请求状态被改回默认文字，修改后保留新请求状态且不显示旧错误。聊天发送、取消、请求生命周期和任务状态共 **52 项通过**。
- **边界：**使用 Node 本地 DOM/网络桩模拟请求时序；未进行真实浏览器验收。

### 2026-10-28 重跑任务遇到缺失 API Key 后停留在等待

- **严重度：P2。发现并修复：**任务历史的重跑逻辑先创建新任务记录，再调用聊天；当原模型 Key 已失效时，聊天在创建执行上下文前提前返回，新记录一直保持 `pending`。现在这个早期校验失败会将重跑记录终结为 `failed` 并保存 Key 缺失原因，仍可再次重跑。
- **复现与验证：**在同一个 Node VM 中加载真实 `task.js` 与 `chat.js`，让 provider 解析返回未配置；修改前重跑记录为 `pending`，修改后为带错误原因的 `failed`。聊天生命周期、任务历史与执行卡测试共 **68 项通过**。
- **边界：**使用本地 DOM 和 provider 桩，覆盖真实前端函数调用链；没有真实浏览器或真实模型服务验收。

### 2026-10-28 前端工程加载与删除保存竞态复核（未发现新问题）

- **复核范围：**旧加载响应淘汰、切换前聊天取消、取消失败时阻止切换、当前工程删除等待保存、批量删除及图层/栅格恢复。
- **结果与验证：**未发现新的可复现缺陷。`project_load_race.test.cjs` 与 `project_delete_save_race.test.cjs` 共 **23 项通过**；其中自动保存因图层注册同步失败而跳过的预期错误日志不是测试失败。
- **边界：**使用 Node DOM/网络桩模拟异步顺序；没有真实浏览器验收。

### 2026-10-28 RGBA GeoTIFF 的 NoData 像元被 Alpha 重新变为不透明

- **严重度：P2。发现并修复：**上传预览先按 RGB 有效掩膜生成透明 NoData 像元，随后把独立 Alpha 波段直接覆盖到透明度通道；当 Alpha 在 RGB NoData 处仍为 255 时，空值像元会作为不透明色块显示。现在输出 Alpha 与重投影后的有效像元掩膜相乘。
- **复现与验证：**本地构造带 RGBA 颜色解释、RGB 单像元为 NoData、Alpha 全不透明的 4×4 GeoTIFF。修改前 PNG 对应透明度为 **255**，修改后为 **0**。`test_upload_raster.py` 与上传安全用例共 **39 项通过**；前端上传预览/交接用例 **24 项通过**。
- **边界：**像元及坐标转换使用本地合成 TIFF 和 FastAPI 测试客户端；前端用 Node harness；无真实浏览器或大尺寸远程栅格验收。合成 NoData+Alpha 样本产生两条 Rasterio `NodataShadowWarning`，不影响断言结果。

### 2026-10-28 CSV 预览过滤显式的全空字段记录

- **严重度：P3。发现并修复：**对 `lon,lat\n,\n1,2` 这类合法 CSV，后端按两行数据读取并在首条记录给出两个空值；前端预览此前用“至少一个非空字段”过滤行，导致用户看不到第一条显式空记录，预览与实际 CSV 行数不一致。现在仅跳过真正没有内容的物理空白行，保留逗号/引号等显式记录。
- **复现与验证：**前端回归修改前只显示 `1,2`；后端 API 同一输入确认 `rows=2`、首条记录为两个 `null`。修复后上传预览与交接测试 **25 项通过**，后端上传交接/CSV 解析测试 **39 项通过**。
- **边界：**使用 Node DOM harness 和 FastAPI 本地测试客户端；未做真实浏览器验收。另复核只有 CSV 表头而无数据行时列名仍能保留，未发现该候选缺陷。

### 2026-10-28 空间结果注册失败仍被推送到前端

- **严重度：P2。发现并修复：**`_gdf_to_layer` 原先先将结果放入待返回图层，再由注册流程校验 GeoJSON。若结果含无穷坐标等注册拒绝的数据，工具虽然报错，待返回列表仍包含该图层；直连工具接口仍会返回待处理图层，前端 `applyToolResult` 会照常上图。现在先用副本完成注册校验和登记，再将原始结果推送，保持既有待推送数据形态；校验失败时不会产生待返回图层或注册记录。
- **复现与验证：**本地 GeoDataFrame 含 `Point(inf, 0)`，修复前 `_gdf_to_layer` 抛出 GeoJSON 校验异常但待返回列表仍有 `invalid-result`；新增回归先稳定失败。修复后图层注册生命周期与空间工具测试共 **220 项通过**。
- **边界：**使用本地合成 GeoDataFrame 和 Node 代码路径检查；未以真实桌面浏览器制造数值异常或验收地图显示。测试使用仓库内隔离 pytest 临时目录，保留未清理。

### 2026-10-28 同名待返回图层替换后保留旧 QA 警告

- **严重度：P3。发现并修复：**`_push_layer` 遇到同名输出会用最新图层替换旧图层，但会继续累加旧版几何质量警告。修改/重跑同名图层后，用户看到的是最新数据，却可能仍收到旧坐标越界或几何问题提示。现在替换图层时同步移除该图层名的旧警告，再依据最新 GeoJSON 重新计算。
- **复现与验证：**依次推送同名图层（先使用越界点 `[88, 116.4]`，再用合法 WGS-84 点 `[116.4, 39.9]`），修改前返回层已是新坐标但警告仍指向旧越界坐标；新增回归先稳定失败。修复后图层注册生命周期、空间工具与 Geo QA 测试共 **236 项通过**。
- **边界：**通过本地 GeoJSON 与 Geo QA 实际函数验证；没有真实浏览器弹出警告的视觉验收。

### 2026-10-28 null 属性的 GeoJSON 要素未获得前端 FID

- **严重度：P2。发现并修复：**合法 GeoJSON Feature 可将 `properties` 设为 `null`。共享前端图层状态只给已有属性对象注入 `_fid`，导致此类要素没有稳定身份，也未进入 `fidIndex`，影响选择、表格和专题/3D 要素映射。现在遇到空值、非对象或数组属性时先归一化为空对象，再统一生成 FID；与后端注册的属性归一化保持一致。
- **复现与验证：**新增 Node VM 回归，修复前加入 `properties: null` 的点要素时报 `TypeError`，无法创建/断言 FID；修复后 `gis_state_fid_identity`、图层重命名/同步和工程加载竞态测试共 **64 项通过**。
- **边界：**Node VM 覆盖真实 `gis_state.js` 状态函数与图层状态桩；没有在真实浏览器中点选该要素或检查 3D 渲染。

### 2026-10-28 工程保存与恢复未拦截无效矢量坐标

- **严重度：P2。发现并修复：**工程保存路径只做 Blob 序列化，前端 `/api/layer/register` 也只检查坐标有限性，不验证矢量结构和 WGS-84 范围；`[0, 100]` 可被直接注册、保存并在打开时正常登记。地图的坐标回调会尝试交换这类经纬度，可能把坏坐标显示为另一个有效位置。现在共享验证器校验 GeoJSON 几何结构和有限 WGS-84 包围盒，应用于图层注册和工程保存；恢复旧工程时跳过无效矢量层并返回注册警告，前端按警告跳过地图绘制，保留其余正常图层。
- **复现与验证：**本地临时工程 `save_project` → `open_project` 修改前接受纬度 100、无警告地登记 `[0,100]`；直接图层注册拒绝越界、保存拒绝越界和短坐标位置、旧工程跳过均有回归。图层注册生命周期与工程栅格持久化共 **71 项通过**，工程加载竞态/恢复前端测试 **22 项通过**。
- **边界：**后端验证为本地临时工程服务层，前端为 Node VM 模拟；真实浏览器渲染未验收。导入旧 `.giswork` 时仍保留其 Blob，打开时会警告并跳过问题图层，不会自动改写用户数据。

### 2026-10-28 工程归档导入未解析验证 Blob JSON

- **严重度：P2。发现并修复：**归档导入验证 Blob 的 gzip、展开大小与 SHA 摘要，但不解析内容；携带有效摘要和有效 gzip、内容却为截断 JSON 的 `.giswork` 会被成功导入，直到加载工程读取 Blob 才失败，导致整个工程无法正常打开。现在在 Blob 迁移前解析 UTF-8 JSON 并要求根节点为对象，损坏归档按无效矢量数据拒绝且清理 staging 工程。
- **复现与验证：**以有效导出工程为底稿，替换为 gzip 正常、摘要与 project.json 匹配但内容为截断 JSON 的 Blob；新增回归在修复前确认 `import_project` 未报错，修复后因无效矢量数据拒绝。`test_project_raster_persistence.py` **43 项通过**。
- **边界：**使用本地临时工程 ZIP，覆盖损坏 JSON 与摘要校验契约；未对接真实浏览器文件选择或超大 1 GB Blob 导入的内存峰值做压力测试。

### 2026-10-28 工程矢量记录缺少 Blob 时被静默导入

- **严重度：P2。发现并修复：**归档结构校验允许普通矢量图层的 `blob` 为空；导入成功后，工程打开得到 `geojson: null`，该层没有恢复分支且不会产生注册警告。现在工程导入要求每条记录至少有矢量 Blob、栅格数据或服务 URL；工程保存也拒绝缺少这三类来源的图层，避免生成无法恢复的导出包。已有栅格与有效服务图层仍可正常保存/导入。
- **复现与验证：**从有效导出包移除矢量 Blob 并将 `project.json` 的引用设空，修改前导入成功；修复后导入拒绝且工程列表无新增记录。另测保存无数据图层被拒绝、已有 raster/WMS/XYZ 持久化回归保持通过。`test_project_raster_persistence.py` **45 项通过**。
- **边界：**使用本地临时目录和构造 ZIP；没有对真实浏览器的工程导入流程做验收。旧的、已存在的缺 Blob 工程不会被自动改写。

### 2026-10-28 上传解析与服务图层恢复复核

- **复核范围：**GeoJSON/Shapefile/栅格上传注册、取消与回滚；WMS/XYZ 图层密钥脱敏、工程恢复认证提示与服务容量限制。
- **结果与验证：**未发现新的可复现缺陷。上传交接、栅格预览与上传安全测试共 **78 项通过**；GeoSource 容量/凭据恢复和工程服务恢复前端测试共 **42 项通过**。GeoTIFF NoData+Alpha 样本产生 2 条 Rasterio 预期警告；安全测试故意构造重复 ZIP 成员产生 2 条 Python zipfile 警告。
- **边界：**后端使用本地样例/API 测试客户端，前端使用 Node harness；未连接真实 WMS/XYZ 服务或做浏览器交互验收。

### 2026-10-28 AI 流式取消、上传恢复与工程批量删除复核

- **复核范围：**SSE 外层生成器关闭到 AI 请求取消/底层生成器清理；上传超时、状态恢复、用户取消及图层交接；工程批量删除部分失败、共享 Blob 和自动保存竞态。
- **结果：**未发现新的可复现缺陷。直接关闭聊天 SSE body iterator 的本地路由复现中，取消信号到达请求处理且底层生成器 `finally` 执行；上传后端交接/安全测试 **69 项通过**、前端上传恢复/交接测试 **29 项通过**；工程删除后端定向测试 **9 项通过**、前端部分失败/保存竞态测试 **5 项通过**。
- **环境与边界：**AI 取消测试首次使用系统临时目录时，2 个需要 `tmp_path` 的用例受 `C:\Users\13469\AppData\Local\Temp\pytest-of-13469` 权限拒绝影响；改用仓库内新建隔离 basetemp 后同批 **28 项通过**。SSE 断连使用 ASGI response body iterator 本地关闭，不等同真实浏览器/网络断连验收；未运行完整浏览器、Electron 或外部服务验收。重复 ZIP 成员用例产生的 2 条警告为预期输入。

### 2026-10-28 批量删除部分失败后列表不可用会清空当前工作区

- **严重度：P2。发现并修复：**批量删除返回部分失败后，前端会重新请求工程列表以确认当前工程是否仍存在；列表请求失败或响应结构无效时，旧逻辑把“无法确认”当成“已删除”，清空当前图层、聊天和工程身份。现在只有有效列表明确不含当前工程时才清空，无法核验时保留工作区并继续显示部分失败提示。
- **复现与验证：**新增 Node VM 回归分别令二次列表请求拒绝、返回 `projects: null`；两用例修改前均观察到当前工程 ID 被清空，修复后保留当前工程且不清理图层。工程删除部分失败与保存竞态用例共 **7 项通过**；目标 `git diff --check` 通过。
- **边界：**前端状态用 Node VM 验证，未以浏览器实际触发文件系统部分删除或网络断开。

### 2026-10-28 隔离浏览器工程保存与恢复验收

- **验证流程：**启动本地浏览器与 FastAPI；服务端工程目录、Blob 目录和上传/输出目录均定向到 `backend/tests/.browser-acceptance-20261028/`。在实际工作台界面创建点要素图层并放置 1 个点，保存为 `qa-isolated-20261028`；刷新页面后经“文件 → 加载工程 → 恢复”打开。恢复后界面显示同名工程、`qa-probe-20261028` 图层及 **1 个 Point 要素**，隔离服务 `/api/projects` 也返回该工程和 `layerCount: 1`。
- **结果与清理：**此代表性真实浏览器流程的保存、刷新、恢复成功；临时本地服务已停止。隔离工程文件保留在专用测试目录中，以便审阅，不触碰正式 `cache/projects` 数据。
- **边界：**验收覆盖手动画点矢量工程；未覆盖真实文件选择上传、栅格、AI 模型或外部 WMS 服务。浏览器打开期间底图由页面当前配置显示，本轮未把底图服务质量作为验收结论。

### 2026-10-28 矢量上传格式与压缩包边界定向复核

- **复核范围：**裸 Shapefile 前端拦截与 ZIP 后端格式校验；GeoJSON CRS/无效 JSON；CSV 显式空记录；GeoParquet/FlatGeobuf 解析失败清理；上传请求体和 ZIP 展开大小/路径边界。
- **结果与验证：**未发现新的可复现问题；源码确认单独 `.shp` 会在上传前提示打包，后端上传请求体限制在 multipart 解析前生效，ZIP 会检查成员路径冲突及解压体积。`test_upload_handoff.py` 与 `test_upload_safety.py` 按格式/边界关键词筛选 **49 项通过、20 项未选**；2 条重复 ZIP 成员警告来自有意构造的安全输入。
- **边界：**解析验证以真实本地格式样例和 FastAPI 测试客户端为主；本轮没有对 300 MiB 上传极限或 512 MiB ZIP 解压上限做磁盘压力测试，也未做真实文件选择浏览器上传。

### 2026-10-28 删除已有图层后遗留绘制容器中的要素

- **严重度：P2。发现并修复：**在已有图层上绘制时，FeatureGroup 中的 Leaflet 绘制副本未设置所属图层的地图身份。删除图层会移除渲染集合，但绘制副本因没有匹配 `_name` 而留在地图上，造成图层列表为空、地图仍显示旧要素的错误结果。现在把绘制对象标记为目标图层的 `_rawName`/`layer_id`，删除时随图层一起清理。
- **复现与验证：**新增 Node VM 回归，执行“绘制到已有图层 → 删除其地图图层”后断言 FeatureGroup 为空；移除修复行时稳定失败并残留 1 个对象，恢复后通过。绘制清空、地图显隐和图层注册/重命名测试共 **58 项通过**，目标差异检查通过。隔离浏览器实际创建图层、放置一点并删除后，界面显示 0 个图层、地图未见孤立要素。
- **边界：**浏览器数据与本地服务使用 `backend/tests/.browser-acceptance-layer-delete-20261028/` 隔离，服务已停止；未测试批量几何类型与真实 Leaflet.Draw 编辑工具的完整交互。

### 2026-10-28 栅格结果上图与工程恢复交接复核

- **复核范围：**AI 栅格结果重跑时的 Leaflet overlay 替换、按稳定图层 ID 删除与别名清理、栅格/矢量同名切换，以及工程保存和恢复时的栅格元数据、可见性与恢复失败隔离。
- **结果与验证：**未发现新的可复现缺陷。`node --test frontend/tests/map_layer_visibility.test.cjs frontend/tests/raster_tools_layers.test.cjs frontend/tests/project_load_race.test.cjs frontend/tests/project_save_sync.test.cjs` 共 **56 项通过**。当前实现重跑时先按稳定 layer ID 移除旧 overlay，删除会清除其显示名与 ID 别名；恢复失败只报告该栅格并继续恢复后续图层。
- **边界：**本轮为 Node DOM/Leaflet/API 桩测试与源码调用链复核，没有在真实浏览器中运行栅格分析或连接真实云端 COG 服务；现有工程保存/恢复浏览器验收只覆盖手绘矢量图层。

### 2026-10-28 工具面板运行期间切换工程的共享 GIS 状态竞态

- **严重度：P2。发现并修复：**手动分析面板调用 `/api/tools/invoke` 时持有共享 GIS 操作锁，但打开工程只锁工程文件与图层注册字典，没有等待这项操作。若工具尚未登记结果时切换工程，项目 B 会先被激活，工具 A 随后可能把结果写入 B 的注册表。工程激活现在与共享 GIS 操作串行；等候后会重新核对打开请求代次，过期请求不会覆盖更新工程。锁等待超时会返回 409，不会强行激活。
- **补充修复：**图层同步现在携带排队时捕获的工程 ID；后端在共享 GIS 锁内核对当前已激活工程，过期工程的迟到注册会以 409 拒绝。空工程上下文仍可注册，以支持新建且尚未从服务器激活的会话。三个手动工具面板在同步前与结果返回后检查工程代次，阻止旧工程结果上图。
- **复现与验证：**线程回归先稳定复现打开工程越过正在进行的工具事务；修复后工程等待工具事务完成，最终只登记目标工程图层。另一个 API 回归在项目 B 已激活后提交项目 A 的迟到图层注册，修改前返回 200，修复后返回 409；B 的正常注册以及空工程上下文注册仍返回成功。工程打开竞态、直连工具和工程栅格测试共 **63 项通过**。前端覆盖 API 注册、图层注册队列、三个手动工具面板、工程加载/保存和聊天交接测试共 **170 项通过**；目标 Python 编译和差异检查通过。
- **边界：**服务端使用线程和 FastAPI 本地测试客户端，前端使用延迟 Promise/DOM 桩；没有浏览器中并发切换工程的验收。若客户端没有工程上下文或当前后端尚无活动工程，旧来源注册仍可能无法由工程 ID 判断；清空工作区到下一工程打开之间的状态隔离继续作为后续检查项。

### 2026-10-28 新会话图层注册被旧工程删除清空

- **严重度：P2。发现并修复：**从已打开工程切到新会话时，前端清空了当前图层，但后端活动工程 ID 和图层注册表仍属于旧工程。新会话登记的图层因此仍挂在旧工程上下文；随后删除旧工程会把新会话的图层注册一并清空。现在新会话清空前先在共享 GIS 锁内重置后端活动上下文；重置失败则保留界面和当前工作区。前端登记请求携带排队时捕获的活动工程 ID，后端严格核对上下文，避免过期注册落入其他工程。
- **复现与验证：**新增回归先复现“打开旧工程 → 清空旧图层 → 登记新会话图层 → 删除旧工程”会丢失新图层；修复后图层保留。项目打开竞态、直连工具与工程栅格测试共 **64 项通过**；前端 API、注册队列、工程加载/保存和聊天交接等定向回归共 **173 项通过**。Python 编译及差异空白检查通过。
- **边界：**服务端使用线程和 FastAPI 测试客户端，前端使用 DOM/异步桩；本次未在真实浏览器并行执行新会话切换与工程删除。整个工作区包含此前未提交改动，本条记录和本轮修改尚未提交。

### 2026-10-28 重跑保存的工作流沿用上次节点输出

- **严重度：P2。发现并修复：**保存过的工作流包含上次运行的节点 `outputs`。重跑时旧执行器把本次输出合并到旧字典；若本次没有生成同名字段，下游仍能读取旧 `layer_name` 等值，且整条工作流会显示成功。现每次运行前清空节点运行结果与错误，并只保留本次工具返回及本次运行检测到的图层输出。
- **复现与验证：**用带有历史 `layer_name` 的来源节点重跑，而本次工具只返回 `fresh_value`；修改前下游收到了历史图层名且工作流显示成功，修复后该引用明确失败且旧图层名不再出现在本次输出。工作流、历史物化、流事件及 Agent 定向回归共 **55 项通过**；`test_data_discovery.py` 与存储测试共 **26 项通过**。之前全量后端批次收集 1,778 项，在约 3% 进度处长时间等待本地测试服务后被中断，未作为全量通过结论。
- **补充测试修正：**全量批次中发现 Layer 2 的测试伪造了空坐标 Polygon，却断言边界获取成功。将样例改为闭合有效坐标环后，该测试文件 **3 项通过**；这是测试夹具修正，不是产品缺陷。
- **边界：**缺陷通过真实 `WorkflowExecutor` 本地执行路径确定性复现，工具函数使用桩；没有通过真实 AI 模型重跑磁盘工作流，也没有全量后端回归结论。

### 2026-10-29 新会话隔离真实浏览器复核

- **流程与结果：**在隔离项目目录及隔离服务端口中，通过浏览器打开旧工程，点击顶部“新建工程”并在确认框点“确定”；等待前后端工程身份均为空后，使用页面中的 `GIS.api.registerLayer` 注册新会话图层，再删除旧工程。注册接口返回 200，删除返回 200，删除后 `/api/layers` 仍含 `confirmed-ui-new-session-layer`，活动工程 ID 为 null。
- **排除的误报：**先前一次浏览器探测只触发了确认弹窗，没有确认，因此没有执行 `clearSession`；该结果不作为复现证据。
- **边界：**真实浏览器执行了界面按钮、确认框、前端 API 和隔离后端调用；外网 Leaflet CDN 在当前环境不可达，为继续测试会话链路，仅对 `GIS.map.getState` 提供默认中心/缩放桩，地图未渲染，不能视为完整地图端到端验收。隔离服务随后停止；截图保存在 `backend/tests/.browser-acceptance-new-session-20261028/confirmed-new-project-flow.png`。

### 2026-10-30 矢量检查器数据体检 CSV 与公式注入

- **复核范围：**`frontend/js/layers.js` 图层检查器数据体检、当前图层数据读取与 CSV 导出；`frontend/tests/vector_inspector_units.test.cjs` 对应回归。
- **确认并修复：**GeoJSON 字段名会作为 CSV 单元格内容。原实现仅做 RFC 4180 转义，`=1+1` 等用户导入字段会被原样输出，可被电子表格当作公式。先加测试确认原始公式单元格；现针对 ASCII 与全角 `= + - @` 前缀，以及前导空白、TAB、CR、LF 触发符，在值前加 TAB 并强制 CSV 双引号。修复后新断言通过。单引号策略不保证 Excel 保存/重开后仍安全，不能描述为普遍强制文本。
- **验证：**GPT 独立运行 `node --test frontend/tests/vector_inspector_units.test.cjs`，**14/14 通过**；`git diff --check` 通过。仅两个目标文件有未提交修改；未提交/推送。
- **边界：**按 OWASP CSV Injection 建议处理；TAB 会成为字段实际内容，可能影响之后的程序化导入。未运行真实 Excel/LibreOffice/Numbers，不能声称这些软件端到端已验收，也没有普遍适用于所有电子表格的无损方案。
- **交接阻塞：**本次 sidecar 对话实际挂在 `codex-client-bridge` 项目，元数据 `workspaces: []`；Antigravity 侧栏该项目显示“没有对话”。Gemini 后台有执行记录，但这不等于用户可在 GIS WorkTable 项目侧栏看到。下一批前需切回正确且可见的 GIS WorkTable Antigravity 对话入口。GIS 工具其余函数族、真实外部服务及完整桌面端验收仍按既有清单继续。
### 2026-10-30 Antigravity 会话路由与客户端启动复核

- **确认的路由：**历史中用于 GIS 扫描的 Antigravity 会话 `273d6ff5-9e4e-4038-920e-d6e78e0bbcd2` 元数据绑定项目 `Gis-WorkTable` 与 workspace `E:\my_repo\Gis-WorkTable`；可见项目与 bridge 项目区分明确。已将完整重启交接发送到这条正确会话，记录中出现重启说明与 Gemini 对现有清单/提交的读取动作。
- **当前阻塞：**后续对正确会话发送状态催办时，sidecar 返回 `spawnSync ...\resources\bin\language_server.exe ENOENT`。Antigravity 进程不在运行；已安装目录中的 `Antigravity.exe` 存在，但 UI 启动两次均超时且未出现窗口。已确认 `resources\bin` 中无 `language_server.exe`。没有进一步重试、没有改客户端文件或设置，也没有因此产生新的代码改动。
- **下一步：**等待 Antigravity/sidecar 客户端恢复后，从上述绑定 workspace 的可见会话继续，并先核对工作区再检查清单下一模块。当前 CSV 改动与进度记录均保留；不提交、不推送。
- **工具分支检查进展：**覆盖缺口中的 `spatial_graduated_colors` 已继续追踪：`backend/services/tools.py` 生成的 `breaks` 经 `chat.js` 传给 `layers.js` 分类并生成图例；本轮发现并修复了浮点末端断点问题，详见下方记录。GIS 工具仍有其他函数未逐项审查。
- **协作状态：**本轮新任务下发因 Antigravity sidecar 获取模型时连接拒绝而未创建；当前代码由 GPT 实施并记录，仍待 Antigravity 独立复核。

### 2026-10-30 分级设色单一数值的填充透明度

- **复现与修复：**沿 `spatial_graduated_colors` → `_pending_layer_ops` → `chat.js` → `applyGraduatedColors` 检查参数链路。当前要素均为同一有效值时，前端进入单色分支；该分支保存了 `fillOpacity`，却没有将其应用到面要素样式，地图仍使用 `_styleForGeom` 默认的 `0.35`。新增回归用例请求 `0.12`，修复前稳定得到 `0.35`；现统一先规范化透明度，并在单色分支为面要素设置该值。
- **验证：**`node --test frontend/tests/layer_symbology_persistence.test.cjs`，22/22 通过；`git diff --check` 通过。
- **边界与进度：**覆盖受控地图替身及前端样式状态；未在真实浏览器测量 Leaflet/3D 实际像素透明效果。GIS 工具模块仍有大量函数未逐项审查，本记录只标记分级设色此分支已修复，不代表工具模块完成。
- **工作区保护：**本轮开始时保留 `CHANGELOG.md`、`backend/requirements.txt`、`docs/validation/module-scan-progress.md`、`frontend/js/layers.js`、`frontend/tests/vector_inspector_units.test.cjs` 的既有修改；本项新增修改仅限本记录、符号化函数及其专项测试。未提交/推送。

### 2026-10-30 唯一值渲染的 null/缺失值处理

- **复现与修复：**后端 `spatial_unique_values` 使用 `dropna()`，不把 null 或缺失字段计入普通类别；前端原实现将两者映射为空字符串并分配类别颜色。新增前端回归后，修复前 null 要素颜色为色带色（`#c0392b`），而非无数据灰色。现将 null/缺失值样式设为灰色 `#9ca3af`，图例单独显示“无数据”及计数；真实空字符串仍保留为普通类别。
- **验证：**`node --test frontend/tests/layer_symbology_persistence.test.cjs`，23/23 通过；`git diff --check` 通过。测试覆盖 null、缺失字段、原型同名类别和相关符号化持久化回归。
- **边界与进度：**使用前端地图替身验证样式和图例数据，未做真实浏览器渲染。本次仅完成唯一值渲染对 null/缺失值这一分支；混合类型同文本值、超大类别图层和真实地图效果仍未覆盖。GIS 工具模块继续逐项审查。

### 2026-10-30 唯一值渲染的混合属性类型

- **复现与修复：**以 GeoJSON 数值 `1` 和文本 `"1"` 为例，确认 `GeoDataFrame.from_features(...)[field].unique()` 保留 `[1, '1']` 两类；原前端按 `String(value)` 建键，导致两类共享一个样式并只显示一个图例项。现以值类型加显示文本建立类别键；仅当显示文本冲突时，在图例标签补充 `(number)` / `(string)` 类型提示。
- **验证：**新增同文本异类型类别测试，修复前稳定出现相同颜色、合并图例；`node --test frontend/tests/layer_symbology_persistence.test.cjs` 24/24 通过；Python GeoPandas 探针确认后端保留类型差异；`git diff --check` 通过。
- **边界与进度：**测试使用前端地图替身；未在真实浏览器及实际导入的混合类型文件上验收。当前仅覆盖简单标量类型，不代表任意嵌套 JSON 属性可作为唯一值字段。GIS 工具模块继续逐项审查。

### 2026-10-30 手动唯一值渲染错误被标记为成功

- **复现与修复：**沿 `/api/tools/invoke` → `spatial_unique_values` → `_tool_result_failed` → API 与历史结果状态检查。对已注册图层请求不存在的字段时，工具明确返回错误，但失败检测器只对前缀做匹配，且该工具此前没有专用前缀集合，导致 API 返回 `ok: true`。新增端到端回归在修复前复现；现在识别唯一值工具以“图层「”或“字段「”开头的参数/数据错误，以及未找到图层、歧义和渲染失败前缀。
- **验证：**`python -m pytest backend/tests/test_direct_invoke_e2e.py::test_e2e_unique_values_missing_field_is_reported_as_failure -q --disable-warnings --tb=short` 修复前失败、修复后通过。`git diff --check` 通过。
- **边界与进度：**端到端测试覆盖 FastAPI TestClient、实际注册图层和实际工具调用；没有检查所有工具的失败文案与检测器映射。手动工具 API/参数保护仍需继续审查，GIS 工具模块未完成。

### 2026-10-30 焦点统计窗口自动校正超出支持范围

- **复现与修复：**追踪 `/api/tools/invoke` 参数守卫到 `raster_focal_stats`。工具只接受 3/5/7，但原 `odd_int` 守卫把 8 改成 9 并显示“已自动调整”，工具随后仍拒绝该值。现改用专用窗口规则：2/4/6 可调整为下一个受支持奇数；其他范围外整数不伪称校正，明确提示支持范围。工具拒绝时原本也缺少失败标记，已补充窗口错误前缀。
- **验证：**新增守卫单元测试与真实 TestClient/临时 GeoTIFF 端到端用例；`python -m pytest backend/tests/test_tool_args_guard.py backend/tests/test_direct_invoke_e2e.py::test_e2e_focal_stats_unsupported_window_is_not_claimed_as_corrected -q --disable-warnings --tb=short`，11/11 通过。`git diff --check` 通过。
- **边界与进度：**覆盖指定整数边界、上传栅格定位、参数提示和失败响应；未穷举浮点、字符串、布尔输入与全部栅格工具参数。手动工具 API/参数保护继续审查。

### 2026-10-30 栅格重分类误判近似 NoData 值

- **复现与修复：**合成 float32 GeoTIFF 声明 NoData 为 `-9999`，并包含有效值 `-9999.05`。原 `np.isclose(data, nodata)` 默认相对容差把该合法值与哨兵一并屏蔽，输出栅格丢失该像元。改为对 GeoTIFF 明确 NoData 值精确比较；NaN 仍由 `np.isfinite` 排除。
- **验证：**新回归修复前失败（有效像元输出 `-9999`），修复后 `python -m pytest backend/tests/test_raster_gap_tools.py -q --disable-warnings --tb=short`，69/69 通过；`git diff --check` 通过。
- **边界与进度：**验证范围为 `raster_reclassify` 与其定向栅格测试。代码中 zonal statistics 与 cloud-native 读取还存在容差式 NoData 检查，语义及其相关测试尚待分别审查；不能据此标记整个栅格模块完成。

### 2026-10-30 COG 与分区统计误屏蔽近似 NoData 的合法像元

- **复现与修复：**为 COG 元信息和预览、zonal statistics 分别构造声明 `-9999` 为 NoData、同时包含合法 `-9999.05` 的 float32 栅格。COG 元信息原最小值错误为 `0`；分区统计漏掉合法值；COG RGB 预览会把该像元整个屏蔽。COG 读取现精确匹配明确哨兵值；zonal statistics 使用 `rasterio.mask(..., filled=False)` 返回的显式掩码，并结合有限值筛选，避免 NoData 与近似有效值混淆。
- **验证：**新增 COG 统计、COG 预览和分区统计回归；含现有本地读写/alpha/色彩解释用例的定向测试 9/9 通过；`backend/tests/test_new_tools.py` 全文件 24/24 通过。`python -m pytest backend/tests/test_cloud_native.py backend/tests/test_new_tools.py -k "not test_integration" -q --disable-warnings --tb=short`，84/84 通过（4 个远程 slow 集成用例排除）。`git diff --check` 通过。
- **未完成验证：**此前尝试组合运行 87 项时，长时间无输出且一个测试报告失败，随后中断；没有最终 traceback，不能将其归因于本次改动。4 个公开 URL slow 集成仍未完成验收，整个云原生模块在线路径仍未全量验证。
- **审查进度：**本次处理了扫描记录里 zonal statistics 与 cloud-native 读取剩余的 NoData 容差比较；后续仍须复核其他栅格工具、云原生服务边界以及真实服务/浏览器差异，栅格模块未标记完成。

### 2026-10-30 工程归档导入接受无效 GeoJSON Blob

- **复现与修复：**构造哈希正确、JSON 可解析但 `features` 为字符串的归档 Blob。原导入只要求 Blob 根节点是对象，因此错误工程被登记成功，直到恢复阶段才会跳过/报错。现导入时先规范化并检查 FeatureCollection、features 列表及几何结构；非空要素继续校验坐标范围，空 FeatureCollection 保持兼容。新增回归修复前确认未抛错，修复后拒绝坏归档并清理暂存工程。
- **验证：**新用例与“有效 JSON 但语法损坏”已有用例通过，2/2。`test_project_raster_persistence.py` 整体 41/46；另外 5 项失败涉及测试直接读取加密工程 JSON、期待解密栅格仍位于工程目录、以及 Windows symlink 替换响应状态，和本次 GeoJSON 校验改动无关。单独重跑加密栅格导入用例仍失败（解密资产位于私有临时目录而非工程目录），记录为需独立核查的测试/路径契约，不据此归因为本次修复。
- **审查进度：**工程 ZIP 路径冲突、Blob 哈希/JSON、缺失矢量数据与本次 GeoJSON 结构有定向覆盖；项目 messages/map_state 的导入结构、复杂旧格式兼容和真实浏览器导入恢复仍未全面审查。当前进度账本和此前工作区修改均保留；未提交/推送。

### 2026-10-30 工程持久化回归与打开并发复核

- **本轮范围：**工程加密 JSON/Blob、栅格资产导入和 HTTP 资产读取、单项/批量删除异常输入、项目打开代次和共享 GIS 状态锁。沿 `/api/projects/{id}` → `project_service.open_project` → `load_project`/`_activate_project_data` 检查请求取消、被更新请求取代和共享状态锁等待后的重检。
- **测试夹具校正：**4 项旧测试仍按加密迁移前的明文工程 JSON及“解密资源位于工程目录”假设读写，导致失败；另一个竞态测试替换了现已不直接服务的加密原件路径。调整为经项目服务读写加密 JSON、断言资源位于应用私有解密目录，并替换实际返回给文件响应的资源路径。调整后测试仍保留原有删除韧性、资源隔离和符号链接竞态断言。
- **验证：**`python -m pytest backend/tests/test_project_raster_persistence.py -q --disable-warnings --tb=short`，46/46 通过；`python -m pytest backend/tests/test_project_open_race.py -q --disable-warnings --tb=short`，7/7 通过；`git diff --check` 通过。
- **状态与边界：**工程归档矢量 Blob 结构、资源路径和打开请求并发关键路径已审并有针对性回归；messages/map_state 的旧版结构兼容、真实浏览器导入后交互恢复及多进程同时打开/删除尚未审完。本轮仅校正过时测试契约，不改生产代码的资产存储位置或竞态防护策略。工程持久化模块仍为“审查中”，不能标记整个模块完成。

### 2026-10-30 工程归档导入与浏览器恢复复查

- **审查范围与结论：**重新核对 `.giswork` 的压缩/解压限额、ZIP 路径和别名拒绝、工程 JSON 与 GeoJSON Blob 校验、矢量/栅格资源落盘、Blob 迁移失败回滚、前端消息/图层/分组/地图视图恢复，以及项目切换与删除时的取消/自动保存队列。本轮没有确认新的产品缺陷；地图视图对无效经纬度/缩放安全忽略，孤立图层分组 ID 按未分组显示。
- **测试契约校正：**组合测试首次运行 77/80；3 个失败均来自当前实现契约更新后的旧夹具：Blob 现经加密暂存和原子替换，坏 GeoJSON 不能再通过 `save_project` 构造，导出校验错误对外统一包装。更新测试为在当前写入点注入失败、直接构造历史损坏 Blob 状态，以及断言公开错误信息；没有改动生产代码。
- **验证：**`python -m pytest backend/tests/test_layer_group_persistence.py backend/tests/test_project_open_race.py -q --disable-warnings --tb=short -p no:cacheprovider`，80/80 通过；工程前端恢复/保存/删除竞态测试 42/42 通过；`git diff --check` 通过。
- **状态与边界：**归档核心校验、资源迁移/失败清理以及浏览器工程恢复/竞态主要路径已有针对性验证；旧式复杂消息与 map_state 兼容矩阵、真实浏览器导入后交互、多进程同时删除/打开尚未完整覆盖。工程持久化模块保持“审查中”。

### 2026-10-30 旧式上传任务取消遗留文件

- **复现与修复：**直接调用仍受支持的 `/api/upload` 且不带 `request_id`，在 GeoJSON 已写入磁盘、后台读取尚未结束时取消请求。修复前测试稳定发现 `uploads/cancel-without-id.geojson` 被遗留。现在为旧式请求分配内部追踪编号并 shield 后台处理；取消时等待工作线程到达终态，再按该请求追踪到的文件和注册令牌回滚；成功时只移除追踪记录并保留上传数据。
- **验证：**新增取消竞态回归；`python -m pytest backend/tests/test_upload_handoff.py::test_task_cancellation_without_request_id_removes_saved_upload backend/tests/test_upload_vector.py backend/tests/test_upload_raster.py backend/tests/test_upload_handoff.py backend/tests/test_upload_safety.py -q --disable-warnings --tb=short`，82/82 通过（5 warnings）。
- **模块进度：**上传解析、请求编号恢复/取消、图层注册回滚和 ZIP 安全已有 82 项组合回归；未覆盖 Electron/浏览器真实断网中断、跨进程请求恢复，以及全部文件格式的超大文件内存曲线。上传模块仍需继续审查客户端进度/UI 状态和 CRS/格式边界。

### 2026-10-30 上传前端恢复状态机复核

- **审查范围与状态：**追踪 `upload.js` → `api.js` 的请求编号、状态轮询、超时恢复、取消确认、结果回收及图层/面板桥接失败清理；配合上面的 82 项后端上传回归和本次前端状态机测试。该模块主要本地流程标记为“已修复并验证”。
- **验证与结果：**`node --test frontend/tests/upload_preview.test.cjs`，25/25 通过，覆盖重复确认防重传、未知回执不自动重传、成功结果恢复、上传取消后的迟到响应抑制和前后端交接回滚；该范围未发现新的已证实缺陷。
- **未覆盖：**真实浏览器断网/页面关闭、反向代理中断后的长时间轮询，以及多进程部署时进程内上传回执共享；这些需要不同运行环境或跨进程设计验证，不能由当前测试替代。

### 2026-10-30 设置与凭据迁移竞态

- **复现与修复：**并发执行旧版 `user_settings.json` 中明文高德 Key 的 GET 迁移与 POST 删除。测试暂停 GET 在写入加密凭据前，允许删除请求执行，再恢复 GET；修复前删除后凭据仍存在，确认旧值被迁移逻辑复活。现 `_load_user_settings` 用与 POST 相同的可重入锁包住读取、旧 Key 迁移和明文清理的完整事务，避免迁移与更新交错。
- **测试隔离：**发现 `test_credential_security.py` 直接使用仓库默认凭据文件和系统密钥库，且忽略保存失败状态；改为每个测试用例使用临时凭据目录及临时 Fernet 实例，避免读取或改动开发者凭据。
- **验证：**`python -m pytest backend/tests/test_credential_security.py backend/tests/test_geo_credential_delete.py backend/tests/test_user_settings_provider_keys.py -q --disable-warnings --tb=short`，16/16 通过；前端 `node --test frontend/tests/settings_geo_credentials.test.cjs`，7/7 通过。
- **状态与边界：**设置增量保存、Provider Key 脱敏、高德 Key 明文迁移/失败、加密保存、删除竞态和地理凭据删除 API 的主要本地路径已审并验证，模块标记为“已修复并验证”。系统密钥库在不同 Windows 账户/机器上的可用性及应用升级迁移尚未实测；本次凭据测试不再依赖或触碰真实系统密钥库。

### 2026-10-30 数据发现与 GeoSource 本地链路复核

- **审查范围与状态：**追踪 GeoSource 目录搜索/详情/认证、共享 HTTP 安全重定向、ArcGIS URL 检查与异步获取、进度/取消/结果/历史记录，以及 WMS/XYZ/在线图层进入工作区的前端交接。主要本地路径标记为“已审查（未发现新确认缺陷）”。
- **验证：**`python -m pytest backend/tests/test_url_gis.py backend/tests/test_geosource_proxy_redaction.py backend/tests/test_geosource.py backend/tests/test_data_discovery.py backend/tests/test_data_provider_storage.py -q --disable-warnings --tb=short`，147/147 通过；`node --test frontend/tests/geosource_pagination_retry.test.cjs frontend/tests/geosource_layer_capacity.test.cjs frontend/tests/connector_online_load.test.cjs`，28/28 通过。
- **未覆盖：**没有对真实第三方 ArcGIS、WMS/XYZ、GeoSource 目录运行凭据或下载请求；在线服务行为、提供方数据准确性和真实网络中断仍需真实目标/网络条件才能验收。相关风险不作为已确认缺陷。

### 2026-10-30 任务与执行历史状态复核

- **审查范围与状态：**检查 task_manager 创建/加密落盘/缓存恢复/归档/恢复/删除，GIS 执行上下文与失败记录；检查 history 服务持久化错误、清空/重跑，以及前端取消态、重载后的中断恢复和迟到请求处理。主要本地生命周期标记为“已审查（未发现新的已证实产品缺陷）”。
- **测试夹具校正：**任务创建 ID 冲突用例仍把 `task.json` 当明文读取，而任务元数据现已加密。改为通过服务的 `_read_text` 读取后比较原字节对应的明文快照，仍验证冲突 ID 的已有目录没有被覆盖。
- **验证：**`python -m pytest backend/tests/test_task_manager.py backend/tests/test_swipe_history.py backend/tests/test_direct_invoke_e2e.py -q --disable-warnings --tb=short`，46/46 通过；`node --test frontend/tests/task_cancelled_status.test.cjs frontend/tests/history_race.test.cjs frontend/tests/chat_send_lifecycle.test.cjs`，59/59 通过。
- **未覆盖：**真实模型选择/重试行为、浏览器 localStorage 配额耗尽、进程崩溃时任务/历史双写一致性尚未进行端到端或故障注入验证；不将这些边界描述为已证实缺陷。

### 2026-10-30 本机 API 与输出文件安全边界复核

- **审查范围与状态：**复核 CORS 与 Fetch Metadata 中间件对跨站 multipart 和工程切换请求的限制、`/output` realpath/文件描述符与 Range 响应，以及 execute_python 子进程环境中常见凭据过滤。覆盖范围标记为“已审查（未发现新确认缺陷）”。
- **测试适配：**无请求编号上传现会给内部处理函数传递内部追踪编号；更新 CORS 测试中的处理函数替身，保持端到端路由用例与生产函数签名一致。
- **验证：**`python -m pytest backend/tests/test_local_cors_policy.py backend/tests/test_output_file_safety.py backend/tests/test_execute_python_credentials.py -q --disable-warnings --tb=short`，24/24 通过。
- **边界：**Origin/Fetch Metadata 不认证本机原生客户端；execute_python 不是操作系统沙箱；未进行独立浏览器渗透测试或任意代码文件/网络/资源隔离。此处记录是实现范围边界，不是已确认缺陷。

### 2026-10-30 启动器、桌面主进程与 MCP 生命周期复核

- **审查范围与状态：**复核 launcher 进程启动/探活/超时清理/停止结果，Electron 环境选择、重复启动实例锁、窗口载入失败与关闭子进程树，以及 MCP stdio 协议、工具反射和路径约束。当前自动化覆盖范围标记为“已审查（未发现新确认缺陷）”。
- **验证：**`python -m pytest backend/tests/test_launcher.py backend/tests/test_mcp_server.py -q --disable-warnings --tb=short`，49/49 通过；`node --test desktop/tests/main.test.cjs`，29/29 通过，包括 Windows 实例 IPC/父子进程关闭用例。
- **未覆盖：**未构建和安装发行包，未在干净 Windows 账户上验证依赖安装、Electron 完整 GUI/WebView 和 MCP 外部宿主互操作；测试不能替代这些部署环境检查。

### 2026-10-30 地图与图层共享状态复核

- **审查范围与状态：**检查共享图层身份/FID、注册令牌、图层重命名与属性更新、2D 显隐与清理、样式持久化，以及 Cesium 初始加载、状态变化中的样式更新、失败警告与清除时未完成加载的取消。该覆盖范围未发现新确认缺陷，地图与图层模块仍保留真实浏览器并发渲染盲区。
- **验证：**8 个定向前端测试文件 `node --test ...`，106/106 通过；`python -m pytest backend/tests/test_layer_service.py backend/tests/layered/test_layer4_map_integration.py -q --disable-warnings --tb=short`，8/8 通过。首次命令误写集成测试目录，未执行测试；按实际路径补跑成功。
- **未覆盖：**真实 Leaflet/Cesium 浏览器渲染、WebGL 资源压力、快速连续工程切换下的物理设备帧时序未在本轮验证；现有替身测试只证明状态和异步回调契约。

### 2026-10-30 AI 对话、Agent 流式事件与 Workflow 状态复核

- **审查范围与状态：**复核新旧流式入口与普通聊天回退的请求身份/取消信号，Agent 重试安全，Workflow DAG 节点开始/成功/失败/跳过事件，以及前端执行卡与后端工具结果对齐。当前模拟与本地集成路径标记为“已审查（未发现新确认缺陷）”。
- **验证：**`python -m pytest backend/tests/test_stream_step_events.py backend/tests/test_agent_retry_safety.py backend/tests/test_workflow.py backend/tests/test_materialize_workflow.py -q --disable-warnings --tb=short`，56/56 通过；前端 chat lifecycle、workflow 执行卡用例，62/62 通过。
- **未覆盖：**真实模型服务的工具选择、provider SSE 断流/重连、真实浏览器和真实地图联动未覆盖；当前结论只限本地模拟和集成路径。

### 2026-10-30 属性选择忽略 uint64 并丢失大整数精度

- **复现与修复：**以真实注册 GeoJSON 的 `2^63+17` 和 `2^63+18` 两个整数构造 GeoPandas 图层。原 `spatial_select_by_attribute` 只把 `i/f` dtype 视为数值，`uint64` 列的 `>` 和 `between` 会错误报“不支持”；即使纳入数值，原先把阈值转 `float` 也会让相邻大整数精度合并。现把 `u` dtype 纳入数值，并对整数文本精确解析为 Python `int`，仅小数/科学计数输入沿浮点路径处理。
- **验证：**新增用例修复前失败、修复后 `>` 与闭区间 `between` 均只选择预期要素；`python -m pytest backend/tests/test_spatial_tools.py::TestSelectByAttribute -q --disable-warnings --tb=short`，5/5；全文件 `python -m pytest backend/tests/test_spatial_tools.py -q --disable-warnings --tb=short`，193/193 通过。
- **审查进度：**GIS 工具模块仍有多种工具未逐项复核；本项只标记属性选择数值 dtype 这一分支已修复，不代表 GIS 工具模块完成。

### 2026-10-30 大整数属性条件的更新/删除误匹配及 uint64 分级设色

- **复现与修复：**继续沿整数属性在工具链中的调用检查，发现 `update_attribute` 和 `delete_features` 都把整数筛选条件转成 float。用 `2^63+17` 与相邻的 `+1` 两条记录复现：原更新误影响 2/2 条，删除则因误判会删除全部记录而拒绝。现与属性选择共用精确整数字符串解析器；小数/科学计数输入仍按浮点解析。另验证分级设色将合法 `uint64` 字段拒绝为文本，现允许无符号整数列。
- **验证：**更新、删除、`>`/`between` 属性选择及 `uint64` 分级设色专项 11/11；`python -m pytest backend/tests/test_spatial_tools.py -q --disable-warnings --tb=short`，196/196 通过。
- **审查进度：**整数属性条件和分级数值类型这些相关分支已修复；GIS 工具其余未审查函数族及更广的 GeoParquet/nullable dtype 边界仍待逐项检查。

### 2026-10-30 Web 工作区启动与停靠状态复核

- **审查范围与状态：**检查 app DOM-ready 初始化幂等性、停靠标签/关闭/宽度持久化、工作区工具取消后的锁状态、数据搜索跳转、样例加载身份和最近工程卡片不可信文本渲染。当前本地模拟路径标记为“已审查（未发现新确认缺陷）”。
- **验证：**`node --test frontend/tests/workspace_dock_state.test.cjs frontend/tests/app_init_idempotence.test.cjs`，9/9 通过。
- **未覆盖：**未覆盖真实浏览器小窗口布局、localStorage 被禁用或配额耗尽的 UI 反馈、移动触屏指针拖动和 Electron WebView 的真实重载时序。

### 2026-10-30 网络分析坐标未校验 WGS-84 范围

- **复现与修复：**`/api/network/solve` 和网络服务没有 CRS 入参，实际将所有坐标当作 EPSG:4326；提交 `[181,0]` 到 `[182,0]` 的路网/起点时，原实现仍返回合法路线和距离。现网络建图验证每个路网顶点，`find_nearest_node` 验证路线/设施/吸附点；拒绝非有限坐标及超出经纬度范围的坐标，并由 API 以错误对象返回，不产生路径结果。
- **验证：**新增越界路网、越界路线点和实际 API 回归；`python -m pytest backend/tests/test_network.py -q --disable-warnings --tb=short`，17/17；`node --test frontend/tests/network_request_lifecycle.test.cjs`，6/6。
- **模块进度：**本地路由、单行方向、最近设施/吸附错误和服务区近似边界已有定向回归，标记为“已修复并验证”。真实 OSM 路网、超大图性能和复杂多部件路网仍需真实数据/基准，未作结论。

### 2026-10-30 Shapefile 导出文件名、字段名和临时资源

- **复现与修复：**导出函数把请求中的图层名直接连接到临时目录；含 `../` 或反斜线的名称可改变输出路径。现清理跨平台路径分隔符、控制字符和 Windows 非法字符，并对空名/尾随点空格兜底，内部文件和下载使用同名。写出/打包异常原会遗留临时目录，现由 `finally` 清理。进一步用现有字段冲突回归场景真实写出，发现长字段截断名与原有短字段撞名，GeoPandas 报重复列名导致整包失败；现先预留既有短字段名，并按 DBF 大小写不敏感规则选唯一的截断名。
- **验证：**隔离执行生产导出函数：恶意名称 ZIP 5 个成员均为单层路径；写出失败后临时目录移除；字段冲突 ZIP 回读保留短字段 `abcdefghij=short-value` 和长字段 `abcdefghi1=long-value`。`py_compile`、`git diff --check` 通过。正式 pytest 收集仍因 `.venv` 缺少 `keyring`、导入时项目索引重建失败而受阻；未读写真实凭据或项目索引。
- **模块进度：**文件名、DBF 字段冲突与临时资源问题已在真实 GeoPandas 导出函数上复现并修复；API 层测试、CRS 声明一致性、其它字段类型及大图层行为仍待继续审查。

### 2026-10-30 空间连接接受未声明的 right 模式

- **复现与修复：**`spatial_join` 文档只承诺 left（保留目标图层）和 inner，但直接把调用者传入的 `how` 交给 GeoPandas；其 `right` 合法，会改为保留 join 图层记录及几何，结果层却仍按 target→join 命名。现对 `how` 显式限制为文档支持的 left/inner，并在非法值时不注册产物。
- **验证：**`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialJoin -q`，4/4 通过；新增 right 拒绝且不产生图层的回归。
- **模块进度：**空间连接 left/inner 结果、冲突索引列和错误模式已覆盖；GIS 工具其他函数族仍在逐项审查。

### 2026-10-30 图层拆分字段拼错时静默切换模式

- **复现与修复：**`layer_split` 对非空 `by_field` 仅在字段存在时才按字段拆分；字段拼错会进入 `else` 分支，静默按每个要素各建一个图层并报告成功。现在非空但不存在的字段返回可用字段提示，不创建结果；省略字段仍保留按要素拆分的设计。
- **验证：**`python -m pytest backend/tests/test_spatial_tools.py::TestLayerSplit backend/tests/test_spatial_tools.py::TestSpatialJoin -q`，7/7 通过。
- **模块进度：**空间连接 left/inner、空间索引属性和错误模式，以及按字段拆分与拼写错误边界已覆盖；GIS 工具其他函数族仍在逐项审查。

### 2026-10-30 图层拆分同名结果覆盖数据

- **复现与修复：**属性分组值 `1`（数字）和 `"1"`（文本）在 Pandas 中是两个不同组，但原实现都用字符串拼接生成同一个结果名；第二组覆盖第一组，且可能覆盖同名的用户已有图层。回归测试修复前失败，只有一个结果层且值为文本组。现注册每个拆分结果时，在状态锁内同时检查已注册层和待发送层，并分配可用唯一名称。
- **验证：**`python -m pytest backend/tests/test_spatial_tools.py::TestLayerSplit -q`，4/4；随后 `python -m pytest backend/tests/test_spatial_tools.py -q`，199/199 通过（包含空间连接和拆分全部用例）。回归包含异型分组名碰撞并确认既有图层数据不变。
- **模块进度：**按字段拆分的缺字段反馈、null 分组、同名结果碰撞及既有图层保护已覆盖；GIS 工具其他函数族仍在逐项审查。

### 2026-10-30 自动 UTM 转换接受不适合单带的范围

- **复现与修复：**`convert_crs(target_crs="utm_auto")` 原先对每个图层求代表点经度算术平均并直接计算 UTM EPSG。跨日期变更线的 `179°E/-179°W` 两点会被平均到 0°附近，跨度超过一带的数据也会被强行投到单一 UTM CRS，仍返回成功但坐标失真。现在先复用局部 UTM 范围校验，拒绝跨日期变更线、经度跨度超过 6°、超 WGS84/UTM 纬度范围等情况，再由范围中心和 `_get_utm_crs` 统一选择 EPSG，避免经度 180° 得到非法 61 带。
- **验证：**`python -m pytest backend/tests/test_spatial_tools.py::TestConvertCRS -q`，4/4；完整 `python -m pytest backend/tests/test_spatial_tools.py -q`，201/201 通过。回归覆盖日期变更线两侧和 8°跨度输入，不会生成结果层。
- **模块进度：**CRS 常见别名、WGS84/3857 转换、自动 UTM 范围错误和原图层保留已检查；GIS 工具其他分析函数族及更广 CRS 源数据契约仍在审查中。

### 2026-10-30 单点/批量坐标转换 UTM 半球与输入漏项

- **复现与修复：**`convert_coordinates` 的 `utm_auto` 总生成北半球 EPSG:326xx；南纬 33° 实际输出北向坐标为负且相差 10,000 km。它还从输入坐标原始 x 值推分带，导致 Web Mercator 米制坐标无法转 UTM；批处理会跳过坏点后仍报告部分成功；同 CRS 快速返回会放过纬度 91°。现先将任意源 CRS 坐标转换到 WGS84 后确定 UTM 带和南北半球，对不适合单一 UTM 带的批量范围报错，使用 EPSG:327xx 覆盖南半球；严格解析全部输入点、拒绝非有限/越界 WGS84 点，禁止猜测源 `utm_auto` 分带，并要求转换结果有限且经纬度目标范围有效。
- **验证：**修复前新增南半球、Web Mercator→UTM 和坏点批次三个用例均失败；修复后坐标转换专项 7/7，通过完整 `python -m pytest backend/tests/test_spatial_tools.py -q`，205/205。`py_compile` 和 `git diff --check` 通过。
- **模块进度：**`convert_crs` 图层转换与 `convert_coordinates` 单点/批量路径的 CRS 别名、半球、边界和错误输出已复核；输入 CRS 范围、跨分带边界和其他 GIS 工具族仍需继续审查。

### 2026-10-30 近邻分析在大范围使用单一 UTM 距离

- **复现与修复：**`spatial_near` 把源/目标联合范围交给 `estimate_utm_crs()` 后直接按米缓冲，但不像缓冲、聚类和新修复的 CRS 转换那样检查局部 UTM 适用范围。两点位于日期变更线两侧时，旧实现仍按一个投影返回“找到”要素；跨 8° 范围时也会正常回答“未找到”，没有说明测距超出局部投影适用范围。现估算 CRS 前用 `_local_utm_extent_error` 校验联合 bounds，错误时不计算也不创建结果层。原近邻成功测试含 0° 到 10° 的不适用范围，现将远点调整到 2.001°，使其符合本工具文档的局部分析范围并继续测试真实成功路径。
- **验证：**修复前新增的日期变更线与 8°范围测试均未得到预期拒绝；修复后 `python -m pytest backend/tests/test_spatial_tools.py::TestSpatialNear -q`，9/9 通过，覆盖拒绝、无结果副作用、局部命中和无效距离。随后完整 `python -m pytest backend/tests/test_spatial_tools.py -q`，207/207 通过。
- **模块进度：**近邻距离单位、局部投影域和筛选结果创建已覆盖；GIS 工具剩余函数族继续审查。

### 2026-10-30 最近要素对分析的局部投影边界

- **审查范围与修复：**沿最近要素对算法检查同层/跨层筛选、代表点、局部 UTM 距离和结果文本。发现 `nearest_pair` 与 `spatial_near` 一样会对任意范围直接 `estimate_utm_crs()`，全球/跨带输入仍给出米制“最近”结果。现也对筛选后的联合范围使用局部 UTM 校验，超界时停止给出误导性距离。
- **验证：**新增最近要素对在日期变更线两侧和跨 8° 范围的错误路径；`python -m pytest backend/tests/test_nearest_pair.py backend/tests/test_spatial_tools.py::TestSpatialNear -q`，14/14 通过，含局部同层、跨层、属性过滤和近邻命中。
- **模块进度：**近邻筛选、代表点距离、局部范围错误与近邻结果生成有测试覆盖；大型/全球距离需支持测地线计算时应另行设计，当前工具明确按局部 UTM 工作。

### 2026-10-30 泰森多边形范围说明与实现不一致

- **审查范围与发现：**对照 `spatial_voronoi` docstring 的“输入点凸包范围”和 Shapely 实际生成结果。用三角形顶点（凸包面积 2）复现，默认 Voronoi cells union 面积为 36、边界扩至 (-2,-2,4,4)，明显不是凸包。现有算法使用 Shapely 的自动外包络裁切，不传入凸包/研究区；这属于会影响用户对输出面边界理解的文档错误，已更正文档并提示需用研究区图层再裁剪。
- **验证：**运行时范围复现如上；`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialVoronoi -q`，5/5 通过，另 `py_compile` 与 `git diff --check` 通过。计算算法保持现有输出，研究区裁剪是独立后续空间操作。
- **模块进度：**点几何类型、重复站点、米制投影和自动裁切范围说明已核对；若产品要采用凸包/行政区等确定边界，需要新增明确的 extent 输入设计。

### 2026-10-30 空间插值数据对齐与栅格输出复核

- **审查范围与状态：**追踪点/多点展开、值字段与每个点位置配对、有效观测筛选、局部 UTM 单位、IDW/RBF 栅格朝北行序、GeoTIFF transform/NoData、预览图和 raster layer op 注册；结合非对称南北值、MultiPoint、极区/广域、批次内存预算和无效字段测试复核。当前涵盖的本地合成数据路径未发现新确认缺陷。
- **验证：**`python -m pytest backend/tests/test_interpolation.py -q`，9/9；IDW/RBF 数据和 CRS 边界用例随 `test_spatial_tools.py` 全量 207 项通过。随后合并复验 `python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_nearest_pair.py backend/tests/test_interpolation.py -q`，221/221 通过；`py_compile`、`git diff --check` 通过。
- **未覆盖：**没有真实业务采样点/已知地面基准面来验证统计精度；真实 GIS 客户端读取导出 GeoTIFF 和远程瓦片缓存未在本项验收。
- **模块进度：**只标记插值这一分支已审；GIS 工具模块其他函数族仍在审查。

### 2026-10-30 水文分析 NoData 掩膜与河网阈值

- **复现与修复：**逐像元追踪 GeoTIFF→填洼→D8→汇流累积→河网阈值和栅格注册。先发现 `src.read(1)` 忽略 GeoTIFF 内部 mask、`streamnet` 的 0/负阈值把所有有效像元判为河网、全 NoData 栅格生成空白成功结果；现用 masked read 并将非有限值统一为 NoData，拒绝全无效输入，analysis 提前校验，阈值须为正整数。进一步构造平底盆地（边缘高程 100、内部 10）与零高程平地，旧迭代填洼中心仍为 10、平地所有单元都没有低邻居；现以 Priority-Flood 抬升至最近有效外边界/NoData 洞边界溢流高程，并在平地引入至少 `1e-6` 的微小坡度以形成可计算的 D8 排水路径。
- **验证：**上述 mask、阈值、全 NoData 和两种填洼回归修复前失败，修复后水文专项 `TestHydrology` 9/9 通过。与 GIS 工具、近邻及插值集合并复验 `python -m pytest backend/tests/test_spatial_tools.py backend/tests/test_nearest_pair.py backend/tests/test_interpolation.py -q`，227/227；语法和 diff 检查通过。
- **模块进度：**水文输入掩膜、无效输入、Priority-Flood 填洼/平地排水和流程栅格注册分支已修复验证；真实 DEM 水文基准、复杂 NoData 隔断区域、Priority-Flood 大栅格性能未验证。

### 2026-10-30 栅格计算器忽略内部有效数据掩膜

- **审查范围与复现：**追踪 GeoTIFF 多波段读取、表达式白名单求值、NaN 传播、结果 GeoTIFF 写出和 preview/layer-op 注册。创建无 nodata 元数据、但内部 mask 屏蔽左上像元的两波段 TIFF，执行 `B1+B2`；修复前左上屏蔽像元仍输出 0.75，说明 `src.read(i)` 没使用 mask。
- **修复与验证：**逐波段改用 `read(masked=True)`，并将 masked 与所有非有限值统一转成 NaN，使表达式和结果写出保持 NoData。`python -m pytest backend/tests/test_spatial_tools.py::TestRasterCalculator -q`，5/5 通过，包含 mask、除零像元、超大尺寸提前拒绝。随后 GIS 工具、近邻、水文和插值集合并回归 228/228；语法及 diff 检查通过。
- **模块进度：**表达式白名单、NoData 传播、输出 CRS/栅格元数据、资源上限已在合成 TIFF 路径检查；多波段分别有效掩膜、实际云优化栅格/远程存储行为仍待审。

### 2026-10-30 栅格分析工具内部掩膜一致性

- **审查范围与修复：**沿 GeoTIFF 读取点继续检查 DEM 分析、NDVI/光谱指数、等值线、重分类、焦点统计、欧氏距离、代价距离/路径、填挖方、栅格转矢量、地形剖面和重采样/重投影。多个工具此前只按 NoData 哨兵值过滤，忽略 TIFF 内部有效数据 mask；现改为 masked read 或显式使用掩膜，避免掩膜区参与统计、路径/源像元和矢量化。重采样输出保留有效数据 mask，重投影将掩膜区设为 NaN NoData。另发现投影 CRS 等值线直接将投影坐标写入 GeoJSON，现转换至 WGS84。
- **验证：**新增焦点均值、重采样、重投影内部 mask 回归；合并运行 `python -m pytest -q backend/tests/test_raster_gap_tools.py backend/tests/test_spectral_indices.py backend/tests/test_dem_analysis.py backend/tests/test_spatial_tools.py::TestNDVI backend/tests/test_spatial_tools.py::TestContour backend/tests/test_new_tools.py`，121/121 通过。
- **模块进度：**本轮覆盖的消费者路径经定向测试；仍需继续检查栅格预览和其他读取分支的 mask 传播，不能视为栅格模块审查完成。

### 2026-10-30 COG 预览和统计内部掩膜

- **复现与修复：**检查远程/本地 COG 降采样预览与波段统计，发现两处直接 `read(out_shape=...)` 只按 nodata 元数据筛选，忽略内部 TIFF mask。现将每个显示波段的 `read_masks` 合并进预览无效区，并让 COG 抽样统计使用 masked read。
- **验证：**新增内部 mask 极值统计和预览像元回归；`python -m pytest -q backend/tests/test_cloud_native.py -k 'not integration'`，62/62 通过、4 项集成用例未运行。全文件运行在末尾集成测试处等待超过 45 秒后手动中断，因此不报告全文件通过。

### 2026-10-30 栅格计算器逐波段 PAM NoData 掩膜

- **复核结论：**使用两波段 GeoTIFF 和 `.aux.xml` PAM sidecar，分别给 band 1/2 声明 NoData `-9999`/`-8888`。Rasterio 打开后两波段掩膜在对角像元上相反；生产 `raster_calculator` 的 `B1`、`B2` 各自仅屏蔽对应无效像元，`B1+B2` 在任一输入无效时传播 NaN，其余像元仍正确相加。未发现生产代码缺陷。
- **回归与验证：**新增 `TestRasterCalculator.test_calc_propagates_independent_per_band_pam_nodata_masks`，输入、PAM sidecar、GeoTIFF/PNG 结果均位于 pytest `tmp_path`；未改生产代码。`python -m pytest backend/tests/test_spatial_tools.py::TestRasterCalculator -q --disable-warnings --tb=short -p no:cacheprovider`，6/6 通过。`git diff --check -- backend/tests/test_spatial_tools.py` 通过。
- **协作与边界：**GPT 独立复核最终实际差异。Antigravity 客户端该项运行在返回交接前因执行错误终止，且没有本轮文件写入；因此此回归由 GPT 接手完成，不将其计为 Antigravity 贡献。当前证据只覆盖 PAM per-band NoData 与小型真实 TIFF，未覆盖不同 GDAL 驱动/sidecar 变体或大型影像性能；栅格其他模块仍继续审查。

### 2026-10-30 字段计算静默覆盖已有属性

- **复现与影响：**`field_calculate` 的契约是添加新字段，但执行 `gdf[new_field] = result` 会覆盖同名现有属性。临时注册 GeoJSON 中 `result="keep-me"`，请求 `value * 2` 写入 `result`，旧行为返回成功并将值改成 `6`，造成无提示数据丢失。
- **修复与回归：**计算前检查目标字段是否已在 GeoDataFrame 列中；重名时返回明确错误，且不改注册数据或待推送图层/操作。新增冲突测试比较调用前后注册图层与推送状态。修复前新测试失败并实际复现覆盖。
- **验证：**`python -m pytest backend/tests/test_coverage_gap.py::TestFieldCalculate -q --disable-warnings --tb=short -p no:cacheprovider`，5/5 通过；`python -m py_compile backend/services/tools.py backend/tests/test_coverage_gap.py` 与 `git diff --check -- backend/services/tools.py backend/tests/test_coverage_gap.py` 通过。
- **协作与边界：**Antigravity 新任务在执行前因客户端错误终止，无本轮文件写入；GPT 接手实现并独立验证。现有新字段、null/字符串转换和 `_fid` 保护回归通过；测试只使用临时注册图层，未验证超大属性表性能。GIS 工具模块仍继续逐项审查。

### 2026-10-30 字段计算混合 null 使大整数精度丢失

- **复现与影响：**`field_calculate` 原以 `GeoDataFrame.from_features` 构造属性表；同列含 `9007199254740993` 与 `null` 时 pandas 推断为 `float64`，一次计算新字段会把原属性改成 `9007199254740992.0`，并让新字段也基于舍入值，造成静默数据损坏。新增真实注册 GeoJSON 回归修复前失败并复现该精度丢失。
- **修复：**使用已有 `_geojson_to_export_gdf` 按 object dtype 保留原属性；表达式在独立副本上处理 null 为 NaN，同时维持 object dtype，使缺失值按既有规则传播，源属性与可精确计算的大整数不受联动转换影响。字符串化整数保留其整数文本（`4`），不再受偶发的 float 推断影响。
- **验证：**`python -m pytest backend/tests/test_coverage_gap.py::TestFieldCalculate -q --disable-warnings --tb=short -p no:cacheprovider`，6/6 通过；包含已有字段名拒绝、混合 null 的大整数原值与新计算值、null/字符串行为和 `_fid` 保护。`python -m py_compile backend/services/tools.py backend/tests/test_coverage_gap.py` 与 `git diff --check -- backend/services/tools.py backend/tests/test_coverage_gap.py` 通过。
- **边界与协作：**输入为本地小型合成 GeoJSON，未测复杂 AST 函数与大表性能。Antigravity 本轮前置任务继续因客户端执行错误终止；代码由 GPT 在确认可复现后完成并验证。GIS 工具族继续审查。

### 2026-10-30 字段计算接受未支持的 field_type

- **复现与影响：**工具只对 `int`/`str` 做特殊处理，其余文本都沿默认分支执行。`field_type="currency"` 原会成功计算并把 `currency` 写入成功提示，实际结果仍为原数值类型，使请求的类型与提示不可信。
- **修复与回归：**仅接受 `str/int/float` 与 `add_field` 已支持的 `string/text/integer/double/number` 别名，统一转为规范名；其他值在读取/写回之前拒绝。新增未知类型失败且注册图层/待推送状态不变的回归，以及三个别名规范化测试。
- **验证：**未知类型测试修复前失败、返回成功；修复后 `python -m pytest backend/tests/test_coverage_gap.py::TestFieldCalculate -q --disable-warnings --tb=short -p no:cacheprovider`，10/10 通过。源文件语法与 diff 检查随后复核。
- **边界与协作：**只覆盖类型名校验/别名，不重新定义整数转换、非整数截断或缺失值类型推断语义；这些转换规则仍待审。Antigravity 近几轮任务都在执行前客户端终止，本项由 GPT 实现并独立验证。字段计算之外的工具族继续审查。
- **模块进度：**COG 本地读取、预览与抽样统计路径已覆盖；远程真实 COG、COG 内部 mask 与 Alpha 组合仍需单独验证。
- **合并复验：**栅格工具、COG（排除需外部网络的集成用例）和新增工具集合并运行 183/183 通过；`py_compile` 与 `git diff --check` 通过。

### 2026-10-30 空间随机采样参数契约抽查

- **审查范围与结论：**检查 `spatial_sample` 的数量/比例分支、互斥条件、上限和空样本反馈，并沿 StructuredTool 参数 schema 到 `/api/tools/invoke` 的异常回包路径核对小数/非有限的 `n`。Pydantic 工具 schema 会在函数执行前拒绝小数和 NaN/Inf，直连 API 捕获执行异常并记录失败；未发现新确认缺陷。
- **验证：**`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialSample -q`，8/8 通过，覆盖数量、比例、非法值及冲突参数。
- **模块进度：**此记录只覆盖随机采样参数和返回分支，不代表 GIS 工具模块完成。

### 2026-10-30 前端共享图层状态与后端注册生命周期

- **审查范围与结论：**追踪 `gis_state.addLayer/removeLayer/clearAll` 与 `layers.js` 面板桥接、重复名称处理、图层重命名/删除、注册版本 token、失败重试屏障，以及 Cesium 异步加载/删除版本隔离和工程保存读取共享样式。检查删除时 map 清理异常、后端取消注册等待保存、注册失败、项目切换时排队注册上下文等关键失败路径；本轮检查路径没有发现新的已证实缺陷。
- **验证：**`node --test frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/project_load_race.test.cjs frontend/tests/layer_panel_rename.test.cjs`，67/67 通过，覆盖状态唯一 ID、共享同步、重命名/重复名、注册失败与重试、工程切换/恢复及删除。
- **模块进度：**共享矢量图层身份和注册/删除/保存屏障主路径已审查；真实浏览器下 2D/3D 同时运行时的渲染一致性仍需浏览器级验证。下一步检查 AI 工具结果到图层操作的 SSE 生命周期和异步排序。

### 2026-10-30 AI/手动样式操作未同步工程状态

- **复现与修复：**沿 `chat.js` `set_color`/`set_style` 图层操作到 `gis_state`、面板数据和 `project._collectLayers` 追踪。此前地图样式成功变更后仅更新地图（设色还更新面板 `color` 字段），共享状态 `style` 仍保留旧值；工程保存时共享样式覆盖面板样式，重载会恢复旧颜色/符号。手动工具通道也缺少样式变更后的自动保存。现成功应用后同步面板与共享样式并发出状态事件；手动通道将样式变化纳入自动保存条件。
- **验证：**新增手动 `set_color` + `set_style` 回归，断言共享状态、面板状态和自动保存；先运行新增测试确认修复前在共享颜色断言失败，再验证修复通过。`node --test frontend/tests/chat_send_lifecycle.test.cjs frontend/tests/gis_state_fid_identity.test.cjs frontend/tests/project_load_race.test.cjs`，72/72 通过。
- **模块进度：**确认并修复 AI/手动成功样式操作的数据同步与保存路径；继续核对了 SSE 的增量地图操作与最终 `done` 操作身份，后端以相同 `_stream_id`/`_step_id` 重复携带，前端按应用结果去重/重试。错误后局部结果处理仍在检查。
- **验证补充：**新增并通过最终 `done` 与 `layer_ops_delta` 操作 ID 一致断言，单测 1/1。完整 `test_stream_step_events.py` 有 4 项因本地 `.venv` 缺 `keyring`、加密任务存储初始化失败；目标 SSE 用例通过测试内 task-store 隔离后通过。前端图层状态、工程恢复与聊天生命周期集合并 72/72；两个修改 JS 文件 `node --check` 和 `git diff --check` 通过。

### 2026-10-30 手动工具直连 API 契约与入口

- **审查范围与结论：**检查 `/api/tools/invoke` 工具注册表解析、对象参数校验、参数守卫、共享工作区非阻塞锁、执行/失败结果结构、待推送图层产物消费和 `finally` 释放锁；追踪前端 `invokeTool`、工具面板禁用/反馈和项目切换 generation 检查。代码路径上失败/忙碌使用 `ok:false` 并由面板展示为未完成，未确认新产品缺陷。
- **验证阻塞：**目标 E2E 文件无法收集：当前 `.venv` 缺少 `keyring`，导入 `backend.main` 时加密的工程索引初始化失败；没有改动密钥后端或读取用户加密数据来绕过。直接 E2E 用例因此未运行。仅从源码和既有调用测试得出结论，不能标为完整已审查。
- **模块进度：**入口主路径静态检查中；仍需在可用的隔离密钥测试环境验证忙碌锁、失败结果、待处理产物、历史记录及工程切换交互。该环境限制不阻塞其他模块继续审查。

### 2026-10-30 2D/3D 图层渲染同步路径

- **审查范围与结论：**追踪共享可见性/样式事件到 Leaflet 和 Cesium、Cesium GeoJSON 异步载入与版本失效、删除/清空期间迟到载入、失败后的相机飞行、样式更新重载，以及同名 raster/vector 替换和比例尺显隐。本轮覆盖的关键状态路径未发现新的已证实缺陷。
- **验证：**`node --test frontend/tests/renderer_cesium_style.test.cjs frontend/tests/renderer_cesium_clear.test.cjs frontend/tests/map_layer_visibility.test.cjs`，30/30 通过。
- **模块进度：**渲染状态与异步清理关键分支已由测试覆盖；真实浏览器 Cesium/WebGL、多种数据几何的视觉正确性和 GPU 设备差异仍未验证。

### 2026-10-30 工程保存/自动保存路径继续检查

- **审查范围与结论：**静态追踪前端串行保存队列、session/project generation 失效、自动保存前图层注册屏障、图层 assignment 对后端 registry/blob/raster 资产合并、保存前图层一致性校验及删除旧 Blob 的先后。当前阅读范围未确认新缺陷；前几轮已修过的 archive GeoJSON、加密 raster 资产和 open generation 竞态按现有记录保留，不重复实现。
- **验证边界：**未运行工程 E2E；当前 `.venv` 缺 `keyring`，导入 `backend.main`/`project_service` 时现存加密工程索引读取失败。此处只有源码追踪，模块仍为审查中；后续转向无需该本机加密状态的模块。

### 2026-10-30 Electron 客户端与启动器

- **审查范围与结论：**追踪桌面端 Python 解释器探测、端口校验/服务身份复用、同实例 IPC、启动等待与意外退出、只终止本客户端进程、窗口关闭清理；同时查看 Windows 启动器 bootstrap 锁、运行时依赖修复、launcher 端口选择与服务探测。该路径本轮未发现新的已证实缺陷。
- **验证：**`npm test`（`desktop/`），29/29；`python -m pytest -q backend/tests/test_launcher.py`，38/38。
- **模块进度：**桌面进程所有权与命令行 launcher 关键错误/竞争分支已审；真实用户环境首次安装网络、Windows Defender/权限策略和发布安装包升级路径仍未实机验证。

### 2026-10-30 模型 Provider Key 与凭据调用链复核

- **审查范围与结论：**追踪 Provider Key 从设置表单与浏览器存储，到聊天/测速请求、LLMConfig、模型客户端及后端设置同步；检查 HTML 属性转义、设置接口脱敏、连通性错误归一和凭据加密读写。未发现新的可复现缺陷。Provider Key 会按设计发送给用户配置的模型服务，使用远程 WorkTable 后端时也会发送给该后端；界面已有相应说明。
- **验证：**`python -m pytest backend/tests/test_credential_security.py backend/tests/test_user_settings_provider_keys.py -q --disable-warnings --tb=short`，14/14；`node --test frontend/tests/api_provider_key_storage.test.cjs frontend/tests/settings_geo_credentials.test.cjs`，34/34。
- **模块进度：**本地存储/同步与主要错误反馈路径已复核；未对真实模型服务发请求。系统密钥库跨 Windows 账户与升级迁移的边界沿用既有记录，尚未实测。

### 2026-10-30 属性表 CSV 公式注入与转义复核

- **发现并修复：**属性表“导出 CSV”原先只在值含逗号、双引号或 LF 时加引号，字段名完全不转义，也未中和以 `= + - @`、全角变体或控制字符开头的字段和值。将恶意属性表交给 Excel 等电子表格软件打开时，内容可能作为公式执行。现复用已有 CSV 公式前缀防护，对表头和值统一转义并采用 CRLF 行分隔；导出函数返回实际 CSV 文本便于回归验证。
- **验证：**新增 Unicode、逗号、双引号、嵌入换行、公式字段名/值及前导 Tab 回归；`node --test frontend/tests/vector_inspector_units.test.cjs frontend/tests/layer_panel_rename.test.cjs`，52/52；`node --check frontend/js/layers.js` 与 `git diff --check` 通过。测试输出中的离线注册/地图清理日志来自已有故障注入用例，断言均通过。
- **模块进度：**属性表 CSV 注入与格式转义已覆盖；编辑数值精度、CSV 导入类型推断和真实 Excel 兼容性作为下一轮检查点。

### 2026-10-30 属性表空行确认取消仍提交编辑

- **发现并修复：**属性表保存时，先把暂存值写入原 GeoJSON，再弹出“完全空行”确认框。点击取消会关闭提示但无法回滚对象，未确认的字段/坐标修改仍留在共享内存中，之后任意保存可能将其持久化。现在验证所有行后只保留暂存变更；用户确认后才写入 GeoJSON、刷新地图并同步工程。
- **复现与验证：**新增确认框交互回归：保存一行全空编辑触发警告，取消后断言属性原值不变且地图未刷新。`node --test frontend/tests/layer_panel_rename.test.cjs frontend/tests/vector_inspector_units.test.cjs`，53/53 通过；`node --check frontend/js/layers.js` 与 `git diff --check` 通过。
- **模块进度：**属性表 CSV 导出注入与空行确认事务已修复；编辑数值精度、CSV 导入类型推断和真实 Excel 兼容性仍待继续审查。

### 2026-10-30 CSV 上传预览与后端首屏类型推断抽查

- **审查范围与结论：**检查浏览器端 BOM、逗号/双引号/嵌入换行、显式空记录、HTML 转义、取消/读取失败流程，以及后端分块计行、跨块混合类型回退和 CSV 原文件保留。预览仅作展示；最终 AI 转换仍读取服务器保存的原 CSV。此路径未发现新的可复现缺陷。
- **验证：**`node --test frontend/tests/upload_preview.test.cjs`，25/25 通过。后端已有 CSV 跨块类型与行数回归记录，本轮未重跑会导入 `backend.main` 的测试。
- **后续发现：**该 JSON 精度边界在下一模块追踪到 AI 图层注册与工程保存后，确认并修复；见下方“GeoJSON unsafe integer 跨 API 精度丢失”。

### 2026-10-30 GeoJSON unsafe integer 跨 API 精度丢失

- **发现并修复：**证实 SSE `done.layers`、非流式聊天、矢量上传和工程恢复把 Python 任意精度整数输出为 JSON number，浏览器解析超过 `2^53-1` 后会静默舍入。聊天收到新图层还会把舍入副本再次注册，属性表编辑和手动保存工程也会把错误值持久化。现在出站 GeoJSON 属性将不安全整数编码为十进制文本并带 Feature 级字段路径标记；属性编辑注册请求携带版本令牌，后端对未改变的 IEEE-754 舍入副本恢复原值，对前端传回的精确十进制文本按原整数类型恢复；打开工程时传递注册令牌，手动保存优先取令牌匹配的后端图层；GeoJSON 下载按标记把文本还原成未舍入的数字字面量。
- **测试：**新增 `test_geojson_precision.py`，覆盖正/负大整数、嵌套属性、坐标不变、舍入副本恢复、精确编辑文本恢复和令牌匹配的手动工程保存；4/4。前端 `vector_inspector_units`、`layer_panel_rename`、`api_provider_key_storage` 共 83/83，覆盖大整数传输回读/GeoJSON 导出、注册令牌透传和编辑路径。`node --check`（layers/api/project）、`py_compile`（precision/project_service/main）及 `git diff --check` 通过。
- **验证边界：**没有运行真实 FastAPI/工程保存 E2E：当前仓库 Python 环境里 `backend.main` 导入会触发本机加密工程索引/密钥库路径，继续沿用隔离要求，不用实际用户密钥库绕过。已做后端 helper 单测与路由/服务静态追踪；需要隔离 keyring、临时项目索引的 API 集成回归仍应补跑。真实浏览器属性表、模型输出及 GIS 客户端读取也未实机验证。
- **模块进度：**主要 AI/上传/工程往返链路已修复并由单元/前端契约测试覆盖；后端 API 组合验证未完成，模块状态为“修复中，等待隔离 API 集成验证”。

### 2026-10-30 聊天附加图层卡片与产物渲染复核

- **审查范围与结论：**追踪用户消息中的附加图层名/类型/要素数到聊天 DOM；复核 AI Markdown 链接/图片策略、AI HTML/SVG 产物 iframe 沙箱、下载状态码与对象 URL 生命周期。发现并修复附加图层卡片的 DOM 注入：名称、类型和计数原先直接拼入 `innerHTML`，上传文件名可注入标记；现改为创建节点并用 `textContent` 写入。AI HTML 产物仍置于仅 `allow-scripts` 的 opaque-origin iframe；该路径未发现新问题。
- **复现与验证：**新增恶意图层名、类型、计数字段回归；修改前测试失败并显示原始 `<img>/<svg>/<b>` 标记被写入 `innerHTML`，修改后全部作为文字展示。`node --test frontend/tests/chat_send_lifecycle.test.cjs`，43/43 通过；`node --check frontend/js/chat.js` 与 `git diff --check` 通过。
- **模块进度：**聊天消息、附件卡片、产物卡片和 HTML iframe 关键显示路径已检查；真实浏览器 CSP 行为与第三方产物内容未实机验证。

### 2026-10-30 Workflow DAG 重跑状态复核

- **发现并修复：**工作流首次运行失败时会设置顶层 `error`；执行器重跑虽清空节点输出和节点错误，但未清空顶层错误。若后续重跑成功，结果会同时显示 `status=success` 和上次的失败说明。现每次有效执行在进入 `running` 前清除旧顶层错误。
- **复现与验证：**新增同一个工作流第一次抛错、第二次成功的回归；修复前测试失败，成功结果保留“1 个节点失败”，修复后 `error` 为 `None`。Workflow 和历史物化测试共 30/30 通过；`git diff --check` 通过。
- **审查范围与限制：**覆盖 schema 校验、循环检测、拓扑执行、上游失败跳过、模板解析、结果图层副作用与历史物化既有用例；未做超大 DAG 性能压测、真实 GIS 服务或浏览器执行卡端到端检查。工作流执行器模块继续扫描。

### 2026-10-30 路网分析服务复查

- **审查范围与结论：**追踪 GeoJSON 路网到有向图、单行方向、最近节点吸附、最短路、服务区与最近设施结果；复核 WGS-84 校验、零长度路径表达、不可达/未吸附分类、图缓存键和自定义权重启发式。未发现新的可复现产品缺陷。服务区仍是可达节点凸包估算，已由既有代码、属性及 UI 文案明确披露，不能视为精确等时圈。
- **验证：**`python -m pytest backend/tests/test_network.py -q --disable-warnings --tb=short -p no:cacheprovider`，17/17 通过。组合执行 `test_network.py` 与 `test_integration_e2e_v4.py` 时网络测试通过；后者两项凭据存储测试因当前环境凭据后端不可用而失败，与路网代码无调用关系，不计入网络模块结论。网络请求 UI 生命周期测试已有记录，本轮未重跑。
- **边界与进度：**没有真实道路数据对照、超大路网性能基准或真实地图端到端验收；这些限制不作为已确认缺陷。网络分析本地计算路径已审，外部 API/真实地图集成仍需后续模块批次覆盖。

### 2026-10-30 上传取消确认延迟时仍继续传输

- **复现与修复：**上传 UI 的取消按钮先等待 `/api/upload/cancel/{request_id}` 返回再中止上传请求；后端取消确认请求可能等待至 5 秒超时，期间浏览器仍继续发送大文件。新增延迟取消确认回归，修复前确认信号未中止；现在点击后立即 abort 文件传输，同时异步等待服务端状态/回滚确认，再按现有逻辑提示成功或不确定状态。
- **验证：**`node --test frontend/tests/upload_preview.test.cjs`，26/26 通过，包含取消后迟到响应清理；`node --check frontend/js/upload.js` 与目标 `git diff --check` 通过。
- **模块进度：**确认取消响应慢时的客户端传输缺陷已修复。上传 CRS/各格式实际转换契约、Electron 断网和大文件性能仍待继续审查；没有把现有 Node 仿真结果扩大成浏览器端到端结论。

### 2026-10-30 上传矢量 CRS 转换契约复查

- **审查范围与结论：**沿上传格式分支复核 GeoJSON（RFC 7946 默认 CRS 与旧式声明 CRS 转换）、Shapefile ZIP、GPKG/KML/KMZ/GPX/DXF 到 EPSG:4326 的转换、注册范围校验、source CRS provenance，以及前端图层 CRS 标签。浏览器 `crs: WGS-84` 对应的是服务端重投影后的实际坐标；来源 CRS 独立保存在 provenance。本轮未发现新的可复现数据错误。现有专项已覆盖 EPSG:3857 GeoPackage/Shapefile 重投影及缺失 CRS 拒绝。
- **验证与边界：**参考既有上传专项 `test_upload_vector.py`、上传 CRS provenance 验证记录；本轮没有重新导入 `backend.main` 执行可能触及本机加密项目索引/密钥库的 API 测试。旧式 GeoJSON CRS 变体矩阵、真实外部坐标文件与浏览器地图显示仍需单独验收；上传模块仍在审查中。

### 2026-10-30 同秒矢量导出覆盖前一个下载文件

- **复现与修复：**导出 GeoJSON、SHP、GPKG、CSV、CSV+坐标统一使用清理图层名和秒级时间戳；同一图层同一秒内再次导出会复用目标路径，覆盖先前已经返回给聊天/工具调用的下载文件。固定时钟回归先确认两次 GeoJSON 文件名和路径相同、第二份内容替换第一份；现五种格式均在时间戳后追加 UUID，保留独立下载文件。
- **验证：**`python -m pytest backend/tests/test_coverage_gap.py::TestExportLayer -q --disable-warnings --tb=short -p no:cacheprovider`，15/15 通过，覆盖固定时间重复导出、实际 SHP 写出/回读、各格式栅格拒绝和产物登记。
- **模块进度：**导出命名/路径、字段截断、CRS 输出（GeoJSON 注册坐标和 GPKG/SHP 4326 声明）以及 CSV 属性/点坐标边界已有定向检查；超大图层内存/耗时、完整业务字段类型回读和真实浏览器下载仍未验收。

### 2026-10-30 矢量文件导出将空值大整数舍入

- **复现与修复：**注册含 `9007199254740993` 与 `null` 的两条点要素。`GeoDataFrame.from_features` 将混合 int/null 属性推断为 `float64`，实际 CSV 输出 `9007199254740992.0`，SHP/GPKG 也在文件写出前已丢失原精度。新增导出 GeoDataFrame 构造器：几何仍由 GeoPandas 建立，但每个属性列按原始 GeoJSON 值以 object dtype 回填，避免 NumPy/Pandas 浮点化。
- **验证：**修复前 CSV 回归失败，明确读到舍入值；修复后 CSV、CSV+坐标、SHP、GPKG 均从实际落盘文件验证原整数精确保留、空值仍为空。`python -m pytest backend/tests/test_coverage_gap.py::TestExportLayer -q --disable-warnings --tb=short -p no:cacheprovider`，19/19；`py_compile` 和 `git diff --check` 通过。
- **模块进度：**已覆盖重复导出文件名碰撞、大整数属性及空值、SHP 字段截断冲突、格式 CRS/结构回读和结果产物登记。其它日期/时间、嵌套属性、超大图层性能与真实 GIS 软件兼容仍待继续审查。

### 2026-10-30 CSV+坐标导出覆盖同名属性字段

- **复现与修复：**点图层原始属性包含 `longitude`、`latitude` 时，`csv_xy` 直接给 GeoDataFrame 写同名几何坐标列，导致两项原属性不可恢复。新增实际 CSV 回读回归，修复前确认源属性被替换成坐标；现在有冲突时保留原字段，并选择 `geometry_longitude` / `geometry_latitude` 作为坐标字段，候选名也冲突时继续加序号。成功提示显示最终坐标列名。
- **验证：**`python -m pytest backend/tests/test_coverage_gap.py::TestExportLayer -q --disable-warnings --tb=short -p no:cacheprovider`，20/20 通过，包含源字段冲突、大整数精度、同秒文件名、SHP/GPKG 写出及产物台账；`py_compile`、`git diff --check` 通过。
- **模块进度：**本轮三项已确认导出缺陷（同秒覆盖、大整数舍入、CSV+坐标字段覆盖）均修复并验证；其他复杂属性与超大数据量仍需继续审查。

### 2026-10-30 工具产物下载路由复查

- **审查范围与结论：**复核 `/output/{filename:path}` 的规范化路径、符号链接目标约束、文件打开后 inode 重检、Content-Disposition、主动内容 CSP、单/多段 Range 解析和文件描述符关闭。本轮未发现新的可复现路由缺陷。
- **测试夹具校正：**安全测试要求响应文件名必须保留 `%0D%0A` 编码，但当前框架会先移除控制字符；两种行为都可安全，测试的真实不变量是无原始 CR/LF 且不能注入独立响应头。已将断言改为检查 `x-injected` 响应头不存在，不再要求某一种安全编码实现。
- **验证：**`python -m pytest backend/tests/test_output_file_safety.py -q --disable-warnings --tb=short -p no:cacheprovider`，11/11 通过；包含文件范围请求、符号链接替换和危险下载名。目标 `git diff --check` 通过。
- **边界与进度：**本地 TestClient 覆盖路径安全和 HTTP 响应；真实代理/浏览器 Range 请求、并发大量下载及输出目录在多进程部署时的权限隔离未实测。导出与输出下载模块仍在审查中。

### 2026-10-30 统计图表 HTML 内联脚本注入

- **复现与修复：**`create_chart` 将用户指定标题、字段分类值和轴名称拼入 HTML/内联 JavaScript；构造 `</script><script>window.__chart_injected=true</script><script>` 后，生成的聊天 HTML 图表中原样出现了可打断脚本元素的序列。聊天图表 iframe 允许脚本运行，因此可执行。现标题按 HTML 文本转义；图表配置、标题及轴名称作为 JSON 字面量序列化并转义 `<`、`>`、`&` 与 JS 行分隔符；图表类型先限制为文档支持的枚举。
- **复查发现：**固定时间连续生成两张图表可复现同秒文件名碰撞，第二次写入覆盖第一次下载文件。文件名增加 UUID 后缀。
- **验证：**新增生成真实 HTML 文件的恶意标题和分类值回归，以及固定时钟的同秒双产物回归；两项均能在修复前复现。修复后 `python -m pytest backend/tests/test_coverage_gap.py::TestCreateChart -q --disable-warnings --tb=short -p no:cacheprovider`，3/3 通过；`py_compile` 与 `git diff --check` 通过。
- **模块进度：**图表的标题、分类数据、轴名称、类型关键输入和同秒重复生成路径已覆盖；真实浏览器中第三方 ECharts CDN 与 CSP 组合未实机验证。

### 2026-10-30 save_file 符号链接越界写入

- **复现与修复：**`save_file` 的 basename/`..` 检查不能阻止输出目录内预置的符号链接。构造 `output/alias.txt → ../outside.txt` 后调用工具，会跟随链接并覆盖输出目录外目标。现写入前解析输出目录与目标路径，拒绝符号链接和规范化后越界的路径。
- **验证：**新增目录外目标保持原文的符号链接回归，修复前失败、修复后通过；`python -m pytest backend/tests/test_coverage_gap.py::TestSaveFile -q --disable-warnings --tb=short -p no:cacheprovider`，2/2 通过；`py_compile`、`git diff --check` 通过。
- **边界与进度：**覆盖静态符号链接与路径规范化；未模拟本机并发进程在路径检查和打开之间替换目录项的竞态。`save_file` 的 HTML 重名/登记路径继续审查。
- **后续发现：**同一秒连续三次保存同名 HTML 时，首份按时间戳改名，后续请求回退到原始文件名；第三次会覆盖第二份内容，已登记 URL 也不再对应稳定内容。现 HTML 在写入前分配带 UUID 的最终文件名，并以该文件登记预览。
- **验证：**新增固定时钟下连续三次写同名 HTML 的回归，修复前两条文件路径承载不了三份独立内容，修复后每份文件和预览 URL 均唯一。`python -m pytest backend/tests/test_coverage_gap.py::TestSaveFile -q --disable-warnings --tb=short -p no:cacheprovider`，3/3 通过；`py_compile`、`git diff --check` 通过。
- **模块进度：**`save_file` 的普通文本、静态符号链接路径和同秒 HTML 内容/预览登记已验证；并发竞态及真实浏览器内 HTML 预览仍未实测。

### 2026-10-30 GIS 分析报告文件名路径穿越

- **复现与修复：**`generate_analysis_report` 把注册图层名拼入 `output/reports` 路径。注册 `../../escaped` 图层后，报告文件实际写到 `output` 外。现落盘文件名过滤 Windows/POSIX 路径及非法字符、清除首尾点空格，并加入 UUID；报告正文仍保留原图层名。
- **验证：**新增临时输出目录回归，修复前解析出的报告路径位于 output 外，修复后落在 output 内；`python -m pytest backend/tests/test_report_quality.py::TestGenerateReport -q --disable-warnings --tb=short -p no:cacheprovider`，2/2 通过；`py_compile`、`git diff --check` 通过。
- **边界与进度：**路径验证覆盖图层名越界和同秒重名避免覆盖；报告 Markdown 在前端的实际呈现及复杂 Unicode 名称的兼容性未实测。其它报告统计和质量检查边界仍待审查。

### 2026-10-30 前端地图图片/PDF 导出路径复核

- **审查范围：**从 Agent `export_map`/`export_pdf` 操作进入 `chat.js`，追踪到 `map.js` 导出实现；检查格式归一、Canvas 合成/下载、打印弹窗失败路径、旋转角归一、PDF 标题转义、图层/专题图例嵌入及打印完成前恢复原地图图例显示。
- **结论：**本轮未发现可复现产品缺陷。前端导出回归覆盖 SVG/Canvas 叠放、经纬网、PNG/JPEG MIME/扩展名、下载状态反馈、PDF 图例、旋转布局和失败时的图例恢复相关分支。
- **验证：**`node --test frontend/tests/map_export_composition.test.cjs`，5/5 通过。
- **边界与进度：**测试基于 Node VM DOM/Canvas 模拟；未在真实浏览器验证不同地图底图 CORS、打印机/浏览器分页差异和大尺寸 Canvas 上限。模块暂记“审查中”，后续需真实浏览器导出验收或发现可测的离线问题。

### 2026-10-30 静态地图文件名路径穿越

- **复现与修复：**`generate_static_map` 将 `output_name` 原样拼入 `cache/charts`。在隔离工作目录传入 `../../escaped`，实际写出到 charts 目录之外；现在去除路径前缀并过滤非法文件名字符。另发现仅空图层时也会保存空白 PNG 并以“含 1 个图层”报告成功；现在统计成功绘制数，无有效图层则关闭图并返回明确错误。比例尺原先直接用经度跨度乘 111 km；在纬度 60°、经度跨度 1.1° 的实图中标 122 km，而 WGS84 地面距离为 66.8 km。现按比例尺所在纬度通过 WGS84 椭球测距。
- **验证：**路径越界、空图层和高纬比例尺三条回归均先复现旧行为、修复后通过；`python -m pytest backend/tests/test_coverage_gap.py::TestGenerateStaticMap -q --disable-warnings --tb=short -p no:cacheprovider`，3/3 通过；`py_compile`、`git diff --check` 通过。
- **边界与进度：**路径穿越、空/不可转换数据、成功计数和高纬度量值已覆盖；相同 `output_name` 的覆盖语义、比例尺在其他投影/跨日期变更线数据及大图层性能仍待继续审查。

### 2026-10-30 AI 图层操作与 SSE 重放复核

- **审查范围：**追踪 `run_agent_stream` → `tool_start/tool_end/layer_ops_delta/done`，核对同一会话及全局 GIS 工作区锁、`focus_map` 操作 ID 分配、增量应用失败重试、最终 `done.layer_ops` 重放去重及已结束卡片忽略迟到事件。
- **结论：**本轮路径未发现新的可复现缺陷。流式 Agent 获得 session lock 和 shared-state lock 后才重置/访问全局工具状态；焦点操作增量带 `_stream_id`，前端仅在确认应用后记为已应用，最终结果会跳过已应用项；未成功操作保留错误供最终重放重试。
- **验证：**`node --test frontend/tests/execution_cards.test.cjs frontend/tests/chat_send_lifecycle.test.cjs`，64/64 通过；`python -m pytest backend/tests/test_stream_step_events.py -q --disable-warnings --tb=short -p no:cacheprovider`，23/23 通过。
- **边界与进度：**后端使用模拟图事件、前端使用 Node VM；未通过真实模型与浏览器网络故障注入验证 SSE 断连/重连和多个会话的端到端竞争，AI/SSE 模块仍需剩余入口及运行时检查。

### 2026-10-30 鱼网格网与热力图工具复核

- **审查范围：**追踪 `create_fishnet` 的 extent_layer/联合范围、经纬度单位、cell_size 向上取整、rows/cols 分支、10,000 格上限和图层注册；追踪 `create_heatmap` 的点/MultiPoint 展开、权重提取、渐变选项及前端 `loadHeatmap` 对 max intensity/半径的消费。
- **复现与修复：**`create_heatmap(weight_field="typo_weight")` 在字段缺失时原先回退成每点权重 1，仍返回成功并发布热力图。新增缺失字段检查，返回可用字段名且不改变待发送热力图状态。
- **验证：**回归修复前失败，修复后 `python -m pytest backend/tests/test_coverage_gap.py::TestCreateFishnet backend/tests/test_coverage_gap.py::TestCreateHeatmap -q --disable-warnings --tb=short -p no:cacheprovider`，5/5 通过；覆盖鱼网格数量上限、负 cell_size、向上取整尺寸、基本热力图和缺失权重字段。`py_compile`、`git diff --check` 通过。
- **模块状态与边界：**这两个工具的主要生成/失败路径已做定向复核；鱼网格单元仍以度为单位（接口文档已声明），热力图非数值/空权重、极端半径、跨日期变更线范围及大点集性能尚未覆盖，GIS 工具模块继续审查。

### 2026-10-30 字段计算缺失值被改写为零

- **审查范围：**追踪字段名/表达式 AST 白名单、GeoPandas `eval` 与逐行安全 eval 回退、类型转换、非有限数值清理、GeoJSON 写回注册表与地图推送；同时复核 `measure_area` 的局部 UTM 与大范围 WGS-84 椭球分支及既有跨带基准测试。
- **复现与修复：**输入字段为 `null` 时表达式结果原为 NaN，函数统一 `.fillna(0)` 后把缺失值写成 0；`field_type="str"` 还会把缺失值变成字符串 `"nan"`。已移除零填充，将 ±Inf 归一为 null，并让字符串转换显式保留缺失值。另确认字段计算器原可将计算结果写入内部 `_fid`，成功更新后会改变稳定要素标识；现在拒绝覆盖 `_fid` 和 `geometry`。
- **验证：**新增 numeric/string 输出的 null 保留与 `_fid` 拒绝回归；修复前数值字段得到 `[8.0, 0.0]`，且 `_fid` 请求返回成功，修复后保留 null 并拒绝覆盖。`python -m pytest backend/tests/test_coverage_gap.py::TestFieldCalculate -q --disable-warnings --tb=short -p no:cacheprovider`，4/4 通过；并与 `TestMeasureArea` 合并的既有运行 5/5 通过；`py_compile`、`git diff --check` 通过。面积专项既有测试覆盖局部和大范围大地面积。
- **模块状态与边界：**字段表达式常见算术、AST 限制、null/Inf 输出、身份列保护已检查；输出字段名覆盖现有属性、非法 field_type、数值溢出类型及跨日期变更线面积仍待审查。空间分析工具族继续检查中。

### 2026-10-30 测距工具接受越界/非有限坐标

- **审查范围：**复核 `measure_distance` 的工具参数 schema、Haversine 运算和用户可见的米/公里结果；与邻近路网工具已实施的经纬度边界校验对照。
- **复现与修复：**经度 181°、纬度 91°、NaN 或 Infinity 原先都会进入 Haversine 公式并返回一个看似正常的距离。现先转数值并拒绝非有限坐标或超出 WGS-84 经度 [-180,180]/纬度 [-90,90] 的输入。
- **验证：**非法范围/非有限值 5 个回归在修复前均失败并返回数字距离，修复后转为明确输入错误；原已知距离样例继续通过。`python -m pytest backend/tests/test_coverage_gap.py::TestMeasureDistance -q --disable-warnings --tb=short -p no:cacheprovider`，6/6 通过。
- **边界与进度：**Haversine 仍按工具说明使用平均地球半径；本轮修复的是无效坐标被当作有效测距输入，不将其扩大声称为椭球精密测距。空间工具输入校验仍在逐项审查。

### 2026-10-30 热力图插件不可用时登记空图层

- **审查范围：**追踪后端 `create_heatmap` → `result.heatmap` → 聊天 SSE 与手动工具结果 → `map.loadHeatmap` → 图层面板；检查 `leaflet.heat` CDN 未加载时前端返回和 UI 结果。
- **复现与修复：**热力图插件不可用时 `loadHeatmap` 返回 `null`。SSE 路径原先仍无条件把 `geojson:null` 的热力图记录加入图层面板，造成不可见的假图层；手动路径无任何失败提示。两个入口现确认返回的 Leaflet 图层对象后才登记/视为成功，插件或地图未就绪时显示错误提示。
- **验证：**新增 SSE 回归修复前失败并观察到 phantom layer；另测手动工具结果入口。`node --test frontend/tests/chat_send_lifecycle.test.cjs`，45/45 通过；`node --check frontend/js/chat.js` 与 `git diff --check` 通过。
- **边界与进度：**通过模拟 `loadHeatmap` 返回 null 覆盖插件缺失状态，未在真实离线浏览器/外部 CDN 故障环境验证插件加载和成功渲染；热力图参数范围与大点集性能仍待检查。

### 2026-10-30 多环缓冲排序与环带语义复核

- **审查范围：**重新追踪 `spatial_multi_ring_buffer` 的距离单位规范化、正数/有限性/重复值/最多 20 个距离校验、局部 UTM 缓冲、按距离升序差集，以及输出按输入顺序还原、dissolve 和属性注册。
- **结论：**当前实现按升序构造互斥环带，最后按用户输入顺序输出；既有回归覆盖递减距离顺序、内区差集、dissolve 与否、单位别名/椭球距离、无效范围和重复距离不覆盖现有输出。本轮未发现新的可复现缺陷。
- **验证：**`python -m pytest backend/tests/test_spatial_tools.py::TestMultiRingBuffer -q --disable-warnings --tb=short -p no:cacheprovider`，31/31 通过。
- **边界与进度：**测试使用局部合成 WGS-84 几何；真实 GIS 软件拓扑兼容、大量源要素性能和无效源几何的处理仍未验收。多环缓冲主路径和关键参数失败路径已审，邻近 `move_features` 及其他空间变换工具继续检查。

### 2026-10-30 要素旋转误用经纬度平面

- **审查范围：**追踪 `rotate_features` 的角度参数、旋转中心计算、GeoJSON 修改和注册表/地图同步。
- **复现与修复：**原实现直接对 EPSG:4326 坐标调用 Shapely 旋转。在纬度 80°、南北约 22 km 的长条面上旋转 90°，结果重新投影后东西宽度仅约 4.2 km，实际没有按地面尺度完成方向旋转。现先检查局部 UTM 适用范围，在 UTM 米制坐标中求合并几何中心并旋转，再转回 EPSG:4326；非法/非有限角度及超出局部投影范围时不改原图层。
- **验证：**新增 80°N WGS-84 对照回归，修复前旋转后宽度未达到原地面南北长度，修复后宽度超过 15 km、南北高度小于 3 km。`python -m pytest backend/tests/test_spatial_tools.py::TestRotateFeatures -q --disable-warnings --tb=short -p no:cacheprovider`，2/2 通过；`py_compile`、`git diff --check` 通过。
- **边界与进度：**旋转仅支持局部 UTM 适用数据，跨日期变更线/超宽范围明确拒绝；真实浏览器地图回显及曲线/无效几何的视觉拓扑仍未验收。

### 2026-10-30 Agent 工具产物登记与核验链复查

- **审查范围与结论：**追踪工具写出文件 → `record_tool_artifact` → SQLite `run_artifacts` → `result_guard.verify_result` 的 run/task 归属、basename/路径匹配、缺失/空文件判定及历史残留隔离；未发现新的可复现生产缺陷。
- **测试夹具问题：**`test_result_guard_v2.py` 的 run-id 用例原先直接使用默认 workspace SQLite 数据库并留下运行记录。增加模块级隔离 fixture，将其改写到 pytest 临时数据库，防止回归套件污染用户的持久化产物台账。
- **验证：**`python -m pytest backend/tests/test_result_guard.py backend/tests/test_result_guard_v2.py backend/tests/test_storage_service.py -q --disable-warnings --tb=short -p no:cacheprovider`，40/40 通过；临时数据库由测试 fixture 隔离。
- **边界与进度：**没有并发多进程 SQLite 压力测试或完整真实 Agent/模型会话；结论限定在本地台账与核验代码路径。工具产物模块仍有更多文件生成器和真实前端附件下载需继续审查。
### 2026-10-30 要素缩放误用经纬度平面

- **审查范围：**检查 `scale_features` 的倍数校验、缩放中心、坐标单位及注册表/地图同步。
- **复现与修复：**原实现直接在 EPSG:4326 的度坐标上缩放。在 78°–82°N 的矩形中仅将 Y 倍数设为 2，重新投影后 X 向地面宽度从约 26.9 km 增至约 49.9 km，两个轴相互串扰。现使用局部 UTM 米制坐标求合并中心并缩放，再转回 WGS-84；跨日期变更线、过宽或超出 UTM 纬度范围时拒绝修改图层。
- **验证：**新增高纬度地面宽度回归，修复前失败、修复后通过。`python -m pytest backend/tests/test_spatial_tools.py::TestScaleFeatures -q --disable-warnings --tb=short -p no:cacheprovider`，2/2 通过。
- **边界与进度：**只覆盖局部 UTM 适用范围；未在真实浏览器验证地图回显，也未做无效/复杂几何的拓扑验收。缩放工具主路径与高纬度轴向语义已审。

### 2026-10-30 要素移动接受非有限位移

- **审查范围：**复核 `move_features` 位移参数转换、单位换算、局部 UTM 投影与图层写回。
- **复现与修复：**`dx=NaN` 或 `dy=Infinity` 原会经过投影平移，后续才因 GeoJSON 坐标无效报错；错误发生在更新路径内，未能提供明确输入反馈。现先转换并检查两个位移均为有限数值，再执行零位移与单位逻辑；非法值在触碰图层前拒绝。
- **验证：**新增 NaN/±Infinity 参数回归，修复前 3 项均失败、修复后通过；`TestMoveFeatures`、`TestScaleFeatures`、`TestRotateFeatures` 合计 14/14 通过。`py_compile` 与 `git diff --check` 通过。
- **边界与进度：**局部 UTM 范围限制和单位语义已有邻近测试；未测极端但有限的超大位移对投影有效范围的影响，地图真实回显未验收。

### 2026-10-30 缓冲与空间变换参数边界复核

- **审查范围与结论：**复核 `spatial_buffer` 的 m/km 单位规范化、NaN/Infinity/溢出距离拒绝、旧输出保护、局部 UTM 范围限制及 dissolve 参数路径；未发现新的可复现缺陷。非数值文本在工具 schema 层即被拒绝，不进入空间工具实现。
- **验证：**缓冲、移动、缩放、旋转相关回归合计 30/30 通过。
- **边界与进度：**仅针对合成局部几何及参数边界；超大有效几何的性能、真实 GIS 渲染与拓扑兼容未验收。缓冲参数和相邻要素编辑核心路径本轮已复核。

### 2026-10-30 GeoTIFF 上传预览与旧式 GeoJSON CRS 复核

- **审查范围与状态：**追踪 `/api/upload` 的 GeoTIFF 源文件保留、波段/alpha/NoData 预览生成、Warp 到 Web Mercator、预览尺寸限制、图层注册和异常清理；并核对旧式 GeoJSON `crs` 声明通过 GeoPandas 转为 WGS-84 后再登记。当前覆盖的主要数据路径与关键错误清理路径未发现新的已证实缺陷，记为**已审查（当前覆盖范围）**。
- **验证：**`python -m pytest backend/tests/test_upload_raster.py backend/tests/test_upload_handoff.py::test_declared_projected_geojson_is_reprojected_before_registration -q --disable-warnings --tb=short -p no:cacheprovider`，10/10 通过（2 warnings）。测试含 alpha 顺序/透明度、NoData、旋转像元轴、百万级预览限额、同名 TIFF 资产、缺 CRS 拒绝、处理失败清理及 EPSG:3857 GeoJSON 重投影。
- **边界：**未实测浏览器端瓦片叠加与真实大型外部 TIFF；旧式 CRS 格式只覆盖 EPSG 命名声明，其他历史 URN/URL 写法尚无完整兼容矩阵。上传模块其他 CSV/矢量/云原生与浏览器队列路径继续按台账其他条目处理。

### 2026-10-30 代价栅格忽略真实像元距离

- **审查范围：**追踪 `_cost_graph` 到 `cost_distance` 和 `least_cost_path`，检查 NoData/非正值节点过滤、8 邻域边权、源/终点坐标投影和 Dijkstra 输出。
- **复现与修复：**旧图权重固定按横纵 1、对角 √2 计算，没使用栅格仿射变换或 CRS。100 m × 1000 m 的 EPSG:3857 栅格中，竖向边本应是横向边的 10 倍，旧算法却视为等长；经纬度栅格的距离随纬度变化也被忽略。现由仿射变换计算相邻像元中心坐标，投影 CRS 按其单位换算为米，地理 CRS 使用 CRS 椭球测地线距离；两个工具都用同一物理距离权重，输出说明更新为“代价值·米”。
- **验证：**新增矩形像元测试，覆盖 100/1000 米横纵边、真实对角长度和 EPSG:4326 高纬行的测地线距离。修复前新测试因 `_cost_graph` 不接收变换/CRS 而失败，修复后通过。定向运行 `python -m pytest backend/tests/test_raster_gap_tools.py::test_cost_graph_uses_georeferenced_cell_distance_for_rectangular_pixels backend/tests/test_raster_gap_tools.py::test_cost_graph_rejects_oversized_valid_surface backend/tests/test_raster_gap_tools.py::test_cost_distance_transforms_wgs84_sources_and_preserves_near_nodata_cost backend/tests/test_raster_gap_tools.py::test_least_cost_path_transforms_wgs84_points_to_projected_raster backend/tests/test_raster_gap_tools.py::test_least_cost_path_does_not_snap_outside_point_toward_zero -q --disable-warnings --tb=short -p no:cacheprovider`，5/5 通过。
- **边界与进度：**未做大型栅格性能基准或不同投影/椭球的完整矩阵；图规模仍受现有 10 万有效像元上限约束。代价距离和最小代价路径的栅格几何权重主路径已修复并验证。

- **追加复现与修复：**`least_cost_path` 原依赖 `estimate_utm_crs()` 计算路径长度；估算为 None 时仍报成功并显示 `nan km`。现投影栅格按 CRS 线性单位换算，地理栅格按椭球测地线计算。
- **追加验证：**既有路径回归模拟 UTM 估算 None 并断言路径总长 1.00 km；修复前断言失败，修复后通过。完整 `test_raster_gap_tools.py` 为 72/72 通过。

### 2026-10-30 处理历史重跑破坏栅格图层

- **审查范围：**追踪历史面板/API → `rerun_history` → 工具调用、输出文件、注册表快照恢复、前端 `dem_result` 图层操作与工程栅格源文件解析。
- **复现与修复：**重跑同名栅格分析时，固定 `_raster_output_dir` 会先覆盖旧 TIFF/PNG；之后历史恢复代码把旧图层的 `geojson=None` 交给矢量注册器，导致重跑报错，旧栅格也无法保留。现重跑期间使用唯一隔离的上传子目录，生成新栅格不触碰旧文件；恢复旧 Raster 时按原 raster metadata 与 source path 重新注册，并追加带 `_原` 名称的 `dem_result` 操作。预览/源 URL 支持该子目录，工程栅格资源解析仅允许安全的 uploads 子路径并仍拒绝 `..` 越界。
- **追加缺陷与修复：**`map.addImageOverlay` 对每个 `dem_result` 都会 `fitBounds`。若按新结果→旧图层顺序处理，最终视图可能跳回旧范围；现在把旧图层操作插到同名新结果之前，使新结果最后应用。
- **验证：**新增同名 TIFF 写入与 Raster 替换回归，核对旧文件字节、元数据、源路径及新旧两个栅格操作顺序；另测嵌套源 URL 可解析且路径穿越被拒。后端历史/工程测试 68/68、手动 API 流程 15/15 通过；`node --test frontend/tests/history_race.test.cjs`，6/6 通过，包含旧/新 Raster 操作顺序转发。
- **边界与进度：**API、静态文件获取及前端处理器转发已验证；未在真实浏览器检查图层面板视觉顺序。历史矢量重跑回归同批通过。历史重跑的 Raster 保留、视图操作顺序和工程路径衔接已修复并验证。

### 2026-10-30 Agent 非流式重试、空响应恢复与取消复核

- **审查范围与状态：**追踪 `run_agent` → `_invoke_agent_with_budget` / `_invoke_empty_response_recovery` → ReAct/ToolNode → 部分地图状态返回；核对工具开始前瞬时错误最多重试一次、工具已开始后不重放整轮、reasoning 空响应关闭推理并只在首步强制工具、provider 拒绝 `tool_choice=required` 后回退、取消检查和总时限锁租约。
- **结论：**在受控 LangGraph/ToolNode 与模拟 HTTP 模型覆盖的路径中，没有发现新的已证实缺陷。取消或超时不会误报普通成功；工具执行后连接中断保留部分图层操作且不重放，避免副作用重复。
- **验证：**`python -m pytest backend/tests/test_agent_retry_safety.py backend/tests/test_empty_response_recovery.py backend/tests/test_stream_step_events.py backend/tests/test_ai_cancellation.py::test_empty_response_recovery_observes_request_cancel_while_invoke_is_blocked -q --disable-warnings --tb=short -p no:cacheprovider`，35/35 通过（12 warnings）。包含 provider 拒绝 required 选择、完整真实 LangGraph 加模拟 HTTP 模型（流式/非流式）、工具已启动与未启动重试差异及阻塞恢复期间取消。
- **边界与进度：**未连接真实第三方模型或对服务商的工具调用策略做在线验证；阻塞调用超时后底层线程会继续运行，已有锁租约保护并通过本地并发测试验证。当前 Agent 重试/空响应恢复关键本地分支已审，真实服务商兼容仍需对应网络/模型条件。

### 2026-10-30 云原生矢量 bbox 与限量读取复核

- **审查范围与结论：**复核 GeoParquet/FlatGeobuf 的 WGS84 bbox 解析、源 CRS 外接框转换、精确相交过滤、分批/限量读取和未知 CRS 拒绝。当前本地用例已覆盖投影外接框误报不消耗要素限额、GeoParquet 无 covering-bbox 元数据回退、FlatGeobuf 分批过滤与 CRS 声明；本轮没有确认新的可复现缺陷。
- **验证：**`python -m pytest backend/tests/test_cloud_native.py -q --disable-warnings --tb=short -p no:cacheprovider -k 'not integration'`，62/62 通过。首次不排除集成用例的运行到远程测试阶段未及时结束，已中断；四个远程 COG/PMTiles/GeoParquet/FlatGeobuf 集成用例因此未纳入本轮结论。
- **边界与进度：**云端网络服务、远端格式变体与大规模数据性能未验证；bbox 接口当前限定常规 `minx < maxx` 的 WGS84 矩形，不支持跨日期变更线的反经线范围。后续可继续复核 COG/PMTiles 服务响应、认证与瓦片边界行为。

### 2026-10-30 手动云原生栅格预览文件名冲突

- **审查范围：**追踪 `/api/online/load` 的 COG/PMTiles 栅格读取、预览文件写入和返回 URL；与工具 Agent 的 COG 唯一文件名修复及上传重试回执比较。
- **复现与修复：**手动在线加载用图层名加秒级时间生成 COG/PMTiles 预览名。同名数据在同一秒内连续加载会返回相同 URL，第二次写入覆盖第一次图层引用的影像。新增 API 回归先复现同路径覆盖；现为两条预览路径追加 UUID 后缀，确保并发/快速重复加载文件互不覆盖。
- **追加发现与修复：**PMTiles Raster 接口只读取中心的一块瓦片，原成功消息容易让人理解为完整栅格已加载；前端原本未保存预览标记且成功消息隐藏。后端现为 COG/PMTiles Raster 响应添加 `preview_only`、`preview_scope`、`processing`，PMTiles 返回消息明确中心单瓦片范围；Antigravity 按 GPT 指令在图层记录保留元数据、对中心瓦片弹出可见提示，并将相对预览 URL 解析到 API 主机。
- **追加复核：**Antigravity 增加 GeoJSON 首要素 `geometry: null` 的安全处理；GPT 核实 GeoParquet/FlatGeobuf GeoJSON 序列化可产生 null geometry，并要求增加回归用例。
- **验证：**重名/预览范围 API 回归修复前分别因路径相同、`preview_only` 缺失而失败，后端修复后通过；`python -m py_compile backend/main.py` 通过。后端 `backend/tests/test_upload_handoff.py` 全文件 41/41 通过；云原生本地用例 `backend/tests/test_cloud_native.py -k 'not test_integration'` 62/62 通过（4 个远程集成用例排除）。GPT 独立重跑前端 `node --test frontend/tests/connector_online_load.test.cjs`，10/10 通过；两个 `node --check` 和相关 `git diff --check` 通过。
- **边界与进度：**已验证手动 API 响应和预览文件、Connector 图层元数据/提示/跨源 URL、null geometry 错误路径；没有连接真实远程 COG/PMTiles 服务，也未在真实浏览器检查并发叠加、跨源图片 CORS 和 toast 视觉呈现。云原生本地入口和本地格式处理继续审查中。

### 2026-10-30 字段计算类型转换静默失效

- **审查范围：**检查 `field_calculate` 对声明类型 `str/int/float` 的新字段转换、null 保留及写回时序。
- **复现与修复：**`int` 转换使用 `astype(errors="ignore")`，`"not-a-number"` 会原样留下却报告成功；`float` 未转换数值字符串。现对新字段逐值转换，转换失败在图层注册/地图推送前返回明确错误；null 保留，字符串转换保留既有行为。原生大整数保留为精确整数，避免转 float 后损失超过 JavaScript 安全整数范围的精度；转换结果以 object dtype 写回，避免 Pandas 对整数与 null 混合列再次强制转 float。
- **验证：**`TestFieldCalculate` 12/12 通过，覆盖非法 int 不变更图层、数字字符串转 float、null、字段冲突、别名及 `2**53+1` 精度；`python -m py_compile backend/services/tools.py backend/tests/test_coverage_gap.py` 与相关 `git diff --check` 通过。
- **边界与进度：**Antigravity 完成了只读契约复核和聚焦回归交接，确认当前修复符合边界；代码由 GPT 实施，非 Antigravity 编码贡献。验证限定字段计算目标路径，其他 GIS 工具模块继续扫描。

### 2026-10-30 工程 ZIP 导入受 NTFS 8.3 短名覆盖

- **审查范围：**检查 `_extract_project_archive` 的路径遍历、Windows 规范化、成员冲突、符号链接和解压限额，并沿 `import_project` 确认解包目录是待导入工程的暂存目录。
- **复现：**在本机 NTFS 临时目录依次写入 `project.json` 与其 8.3 短名别名 `projec~1.jso`，后一次写入会覆盖前一个文件；同样的两个 ZIP 成员经当前 `_extract_project_archive` 解包后仅剩 `project.json`，内容变为 `OVERWRITTEN`。现有 NFC/casefold 路径树没有检测这类文件系统别名。
- **修复：**解包前先验证所有成员；随后逐成员创建目录，并用 `open(..., "xb")` 独占创建文件，拒绝由 Windows 8.3 别名解析到已写文件的路径。捕获文件已存在并返回重复路径错误；`import_project` 的异常清理负责删除未完成的暂存目录。
- **验证：**新增 Windows 8.3 能力检测回归，覆盖 `project.json` / `projec~1.jso` 冲突并断言原内容不变。为避开服务模块导入时扫描默认工程目录，GPT 从源文件 AST 隔离加载目标函数，仅在临时目录复验：短名归档被拒且原文件保留，合法 `data~1.tif` 与普通嵌套目录归档可正常解包。`py_compile` 与相关 `git diff --check` 通过；未运行会先导入服务模块的 pytest 文件。
- **协作与边界：**缺陷由 GPT 从复现结果筛选并实施；Antigravity 最终交接确认其未写代码，提供 NTFS 短名复现、独占创建验证及对 GPT `_extract_project_archive` 实际差异的只读认可。其报告记录的隔离路径穿越测试 4/4 通过，并指出直接调用提取函数若中途失败会留下部分临时文件；当前生产调用仅由 `import_project` 包裹且负责 staging 清理。其早先直接复现命令曾在建立临时提取目录前导入 `project_service`，触发模块级默认索引扫描；命令未输出项目内容，是否曾写索引无独立证据。该项限定于本机 NTFS 与目标解包函数。

### 2026-10-30 工程服务导入触发默认加密索引访问

- **发现与影响链：**`backend.main` 顶层导入 `project_service`，后者原先在文件尾立即调用 `_rebuild_refcount()`，继而读取默认加密工程索引。若已有工程而系统密钥库暂时不可用或密钥失效，读取异常会在 FastAPI 模块加载时冒出，可能连不依赖工程存储的 API 也无法启动。
- **修复：**移除文件尾导入期 `_rebuild_refcount()`，更新缓存注释。工程操作路径中的显式重建调用仍保留；`_blob_remove` 在缓存无有效引用计数时会回退到磁盘引用检查。
- **验证：**新增 subprocess 隔离回归，在导入服务前将 `local_encryption.read_bytes`、keyring 与 `_master_key` 替换成失败哨兵；导入成功且哨兵未触发。GPT 独立运行 `python -m pytest backend/tests/test_project_service_import.py -q --disable-warnings --tb=short -p no:cacheprovider`，2/2 通过；随后运行旧进程缓存 Blob 删除回退与单个坏矢量图层隔离两个针对性用例，2/2 通过；`py_compile` 与相关差异空白检查通过。
- **协作与边界：**本项由 Antigravity 实施，GPT 审查并运行聚焦回归。测试证明模块导入不读加密索引/凭据，不证明 keyring 不可用时工程 API 的操作行为或多进程引用计数一致性；这些仍需单独覆盖。工程持久化模块继续审查中。


### 2026-10-30 工程打开时单个损坏矢量 Blob 中断全工程恢复

- **复现与影响：**在临时工程库中创建包含两个独立矢量图层的工程，只对第一个加密 Blob 的末尾字节翻转。修复前 `_blob_get()` 的认证/解压异常从 `load_project()` 冒泡，`open_project()` 整体失败，正常的第二个图层也无法恢复。
- **修复：**打开时把可确认的单个 Blob 文件/数据损坏降级为缺失图层数据，在 `registration_warnings` 中列出图层并继续恢复其余有效图层。若系统密钥库不可用仍原样失败；认证标签失败只有在当前工程 JSON 已成功以加密格式解密时才按该 Blob 损坏处理，旧式明文工程无法证明密钥正确时仍抛出认证异常。
- **验证：**新增临时存储回归覆盖真实加密 Blob 位翻转、另一个有效图层继续注册、密钥库不可用传播，以及旧式明文工程的认证异常传播；相关四项测试 4/4 通过。`py_compile` 与相关 `git diff --check` 通过。
- **协作与边界：**本项由 GPT 在 Antigravity 本机 RPC 持续拒绝连接期间实施；已尝试通过原会话索取交接，但消息未能送达。验证限定单进程本机加密库和工程打开路径，未覆盖真实磁盘介质故障或完整工程恢复 UI；工程持久化模块仍继续审查。


### 2026-10-30 分级设色最大值因浮点断点舍入被分到首级

- **复现与影响：**构造三要素值 `-54247.55574590947`、中点与 `91558.13856151933`，等间距 2 级。修复前后端最后断点计算为 `91558.13856151931`，比真实最大值低约 `1.46e-11`。前端按 `[break[j], break[j+1])` 分类且无匹配时默认 `classIdx=0`，最大值没有命中任何等级而被错误渲染为首级颜色。
- **修复：**后端在生成等间距或分位数断点后，明确将首尾断点设为实际 `vmin` / `vmax`。前端分类也对断点范围外的值做首尾级夹取，避免浮点边界微差或历史断点造成未匹配值落入首级。
- **验证：**新增后端精确断点回归与前端略高于末断点的分类回归。`python -m pytest backend/tests/test_spatial_tools.py::TestSpatialGraduatedColors -q --disable-warnings --tb=short -p no:cacheprovider`，3/3 通过；完整 `node --test frontend/tests/layer_symbology_persistence.test.cjs`，25/25 通过；相关 `py_compile`、`node --check` 与 `git diff --check` 通过。
- **协作与边界：**Antigravity 侧车取模型时 RPC 返回连接拒绝，未创建新任务，因此本项由 GPT 复现、编码和验证，尚未由 Antigravity 独立复核。未在真实浏览器测量颜色渲染；分级设色之外的工具族仍待逐项审查。


### 2026-10-30 栅格裁剪预览错位、丢弃零值与输出路径穿越

- **复现 1：裁剪预览错位。**在临时目录创建 2×2 栅格（范围 `[0,0,2,2]`），用右半面裁剪。工具产出 1×2 PNG，却把原始全幅 bounds `[0,0,2,2]` 放进地图操作；正确范围应为 `[1,0,2,2]`，因此裁剪结果会被拉伸到整个源栅格。
- **复现 2：有效零值被误判为空。**无 NoData、四个像元都有效且全为 0 的栅格完整落在裁剪面内，修复前 `data > 0` 将四个有效像元全部滤掉，工具返回“裁剪结果为空”，没有地图操作。
- **复现 3：输出名可穿越目录。**将 `output_name` 设为 `..\escaped`，修复前 `clip_raster` 成功把 `escaped.png` 写到 `uploads` 父目录，而不是上传输出目录。
- **修复：**bounds 现从裁剪后的 `out_transform` 和像素尺寸计算，并在必要时转换到 WGS84；裁剪读取使用 `filled=False`，有效值依据 Rasterio 掩码和有限数检查，零值/负值保留，面外与 NoData 像元在 RGBA 预览中透明；常量单波段使用可见中点色。用户输出名先取文件名并清理 Windows/Unix 不安全字符，拒绝清理后为空的名称。
- **验证：**新增 4 个临时数据回归，覆盖全零有效栅格、半幅裁剪 bounds、含洞面外像元透明、路径穿越输出名；`python -m pytest backend/tests/test_spatial_tools.py::TestClipRaster -q --disable-warnings --tb=short -p no:cacheprovider`，5/5 通过。`py_compile` 与相关 `git diff --check` 通过。
- **协作与边界：**向 workspace 绑定的 Antigravity 会话下发了限定任务，但本机 sidecar RPC 仍返回 connection refused，任务未创建；本批由 GPT 复现、修改与验证，待 Antigravity 恢复后独立复核。所有复现文件都在临时目录；未访问 `cache/projects`、真实凭据或云服务。裁剪预览已修，栅格工具其余函数与真实浏览器渲染仍继续检查。


### 2026-10-30 重采样和重投影结果文件被后续调用覆盖

- **审查范围：**检查 `raster_resample` / `raster_reproject` 输出落盘、预览注册和工程栅格资产调用路径；检索并更新依赖确定性文件名的回归用例。
- **复现与影响：**在合成 8×8 栅格上先以 2 倍、再以 4 倍重采样，两个 `dem_result` 操作都指向 `dem_重采样.tif`；第二次写入后，第一次操作引用的 TIFF 也读出 2×2 像元，而非原来的 4×4。重投影也按源文件名固定写入 `_重投影.tif`，连续使用不同目标 CRS 会覆盖此前投影结果，旧预览 URL/图层记录因此指向后来内容。
- **修复：**每次重采样和重投影都在输出基名加入独立 UUID 后缀；预览和图层注册沿用该唯一 TIFF 名。相关测试改为从返回的 `dem_result` 读取实际产物名，增加连续不同参数调用后文件路径不同、原结果尺寸/CRS未改变的回归。
- **验证：**`backend/tests/test_new_tools.py -k 'raster_resample or raster_reproject'`，5/5 通过；`backend/tests/test_project_raster_persistence.py::test_raster_tool_outputs_do_not_modify_project_assets`，1/1 通过；相关 `py_compile` 与 `git diff --check` 通过。
- **协作与边界：**向 Antigravity 下发只读栅格工具审查，但侧车会话创建 RPC 返回 connection refused，未创建会话；缺陷由 GPT 复现、修复并验证。范围限于栅格重采样/重投影本地 TIFF 路径；未验证并发极端文件系统故障或真实浏览器图层呈现。栅格工具族仍继续扫描。


### 2026-10-30 栅格掩膜提取重复调用覆盖先前结果

- **审查范围：**检查 `raster_extract_by_mask` 的掩膜像元计算、输出 TIFF/预览命名与注册引用，并追踪项目内依赖文件名的测试。
- **复现与影响：**对同一 5×5 栅格先用 3×3 掩膜提取 9 个有效像元，再把同名面图层缩小为 1×1 像元并再次提取。修复前两次都写到 `<源名>_掩膜内.tif`，第二次会改写第一次结果文件，旧图层引用所见内容由 9 像元变为 1 像元。
- **修复：**每次掩膜提取输出名追加 UUID 后缀；新增连续两种掩膜的回归断言两条路径不同，旧结果仍为 9 个像元、新结果为 1 个像元。既有掩膜工具测试改为从最新 `dem_result` 读取实际 TIFF 名。
- **验证：**`backend/tests/test_raster_gap_tools.py -k 'extract_by_mask'`，GPT 本地 9/9 通过；Antigravity 会话运行整文件 73/73，并报告 AI wiring 与分析面板 wiring 测试 31/31 通过。GPT 后续加强“无 CRS 不写产物”的断言为 UUID 文件名 glob，单测 1/1 通过，相关 `py_compile` 与 `git diff --check` 通过。
- **协作与边界：**Antigravity 只读审查会话已成功创建，ID `5d8fdbd4-c69f-41ac-88aa-de9eddd81d75`；最终交接确认它检查了目标实际 diff、输出 TIFF/PNG 路径、图层名及工程持久化引用，未发现功能残留问题，并指出 CRS 缺失用例应匹配 UUID 文件名。缺陷由 GPT 复现、修改并做本地验证，审查未改仓库。仅验证合成栅格和面，真实浏览器呈现及异常文件系统行为未覆盖。它另一次 `test_project_raster_persistence.py` 收集因 `ModuleNotFoundError: No module named 'backend'` 失败，该结果不计作代码失败或测试通过。


### 2026-10-30 栅格重分类与焦点统计重复结果互相覆盖

- **审查范围：**延续栅格派生文件生命周期审查，核对 `raster_reclassify` 和 `raster_focal_stats` 输出文件、预览 URL、图层注册及已有固定文件名测试。
- **复现与影响：**重分类将 1/2/3 三个值先按规则全编码为 1，再按另一规则全编码为 2；两次 `dem_result` 都引用同一 `<源名>_重分类.tif`，第二次调用后第一次结果也变成 2。焦点均值对中心值为 8 的 7×7 合成栅格先跑 3×3 再跑 5×5，两次都引用 `<源名>_焦点mean.tif`，旧结果中心值从 `8/9` 被覆盖为 `8/25`。
- **修复：**两工具每次输出基名追加独立 UUID 后缀；测试从工具产生的 raster 元数据读取文件名。新增重复重分类和不同窗口焦点均值回归，明确断言旧 TIFF 数值仍保持原结果。
- **验证：**完整 `backend/tests/test_raster_gap_tools.py`，75/75 通过（包含既有 73 项和本批 2 项新增回归）；`py_compile` 与相关 `git diff --check` 通过。
- **协作与边界：**代码由 GPT 实施。Antigravity 的只读掩膜审查会话未给出最终交接；本轮请求其停止无关环境排查的 RPC 再次 connection refused，因此没有收到对本次重分类/焦点改动的实现或审查贡献。验证使用合成栅格，未做浏览器界面视觉检查。


### 2026-10-30 栅格计算器重复表达式覆盖既有结果

- **审查范围：**检查 `raster_calculator` 从表达式求值到 GeoTIFF/PNG 落盘、预览 URL 和 `dem_result` 注册的文件生命周期；检索依赖固定 `_calc` 文件名的回归测试。
- **复现与影响：**对合成 `[1, 2, 3]` 波段先计算 `B1*2`，再计算 `B1*3`。两个结果都写入 `grid_calc.tif`，第二次调用后第一次图层引用也读出 `[3, 6, 9]`，原 `[2, 4, 6]` 结果丢失；固定 PNG 预览也会被更新。
- **修复：**计算器每次生成的输出基名追加独立 UUID 后缀，GeoTIFF 和 PNG URL/文件名一并唯一；依赖测试改为通过最新 `dem_result` 的 raster 元数据取文件名。增加两种表达式重复计算回归，分别核对两份 TIFF 数值。
- **验证：**`test_dem_analysis.py` 10/10、`test_spatial_tools.py -k 'calc_'` 6/6、上传交接用例 1/1、工程栅格持久化用例 1/1 通过。代码与相关测试 `py_compile`、`git diff --check` 通过。
- **协作与边界：**代码由 GPT 实施；Antigravity 最近消息的 RPC 仍 connection refused，未收到此项编码或复审贡献。复现为本地合成栅格，未覆盖真实浏览器叠加及并发磁盘故障。


### 2026-10-30 NDVI 波段选择变化覆盖先前计算结果

- **审查范围：**从重分类/焦点统计/栅格计算器文件生命周期检查延伸到遥感指数 `ndvi_analysis`，追踪波段参数、TIFF/PNG 产物与注册图层引用。
- **复现与影响：**同一 4 波段合成影像用红光 band 3/NIR band 4 得到 NDVI `0.4286`，随后改用 band 2/NIR band 4 得到 `0.25`。两次原先都写入 `<图层>_ndvi.tif`，第二次改写了第一次图层引用和预览 URL 的结果。
- **修复：**NDVI 每次生成的基名追加 UUID 后缀，TIFF 与 PNG URL/文件名均随同唯一；新增回归分别打开两份结果，断言其数值各自匹配对应波段公式。
- **验证：**`backend/tests/test_spectral_indices.py`，8/8 通过；相关 `py_compile` 与 `git diff --check` 通过。
- **协作与边界：**代码由 GPT 实施。Antigravity 已完成上一项掩膜提取修复的只读独立审查，确认 TIFF/PNG、图层名和持久化引用一致且未见功能残留；本轮请求其继续审查当前多工具 UUID 改动时 RPC 拒绝连接，故 NDVI 及本轮其他 UUID 改动尚无独立复审。验证使用合成波段数据，未做真实浏览器呈现测试。


### 2026-10-30 矢量转栅格改变字段后覆盖先前像元结果

- **审查范围：**检查 `feature_to_raster` 的字段选择、网格参数、GeoTIFF/PNG 输出和 `dem_result` 注册名，并沿新栅格图层的重采样/重投影下游调用检查名字依赖。
- **复现与影响：**对同一 2×2 面依次烧录属性 `first=3` 与 `second=7`，此前两次都写入 `<图层>_转栅格.tif`；第二次后第一张栅格引用也变为全 7，首个字段结果丢失。参数 `cell_size`、`all_touched` 变化也会落到同一产物名。
- **修复：**每次矢量转栅格的输出基名追加独立 UUID，使 GeoTIFF、PNG URL、注册图层名各自唯一；相关测试从最新 `dem_result` 获取动态注册名，并让下游重采样/重投影按该注册名继续处理。新增重复字段栅格化回归，验证两条 TIFF/PNG 文件名均不同，且两次像元值分别保留 3 和 7。
- **验证：**`backend/tests/test_coverage_gap.py::TestFeatureToRaster`，6/6 通过；相关 `py_compile` 与 `git diff --check` 通过。
- **协作与边界：**已向 Antigravity 分配限定编码任务，但侧车 RPC 返回 connection refused，未创建会话；本批由 GPT 复现、实现及验证。使用临时合成面数据，尚未做真实浏览器或工程恢复下的页面验证。栅格转矢量的参数化输出生命周期仍需继续审查。


### 2026-10-30 鱼网重名覆盖及分级设色非有限值

- **鱼网复现与修复：**同一默认/指定输出名创建两次鱼网，第二次覆盖注册表中的首个结果。名称分配现检查已注册和待提交图层，并在锁内完成名称选择与注册；发生冲突时追加序号并保留扩展名。回归断言 4 格和 16 格结果分别保留。`TestCreateFishnet` 4/4 通过，相关 `git diff --check` 通过。
- **分级设色复现与修复：**值 `[1, 2, +Infinity, -Infinity]` 曾生成范围 `1 ~ inf` 和断点 `[1, inf, inf]`；该图层操作经 SSE 默认 JSON 序列化会产生非标准 `Infinity`，前端 `JSON.parse` 会跳过该事件。后端现只用有限值计算范围/断点；全非有限值返回无有效数值且不排入操作。新增正负无穷、全非有限值及严格 JSON 序列化回归。
- **验证：**`backend/tests/test_spatial_tools.py`，231/231 通过；`TestSpatialGraduatedColors` 6/6 通过；`git diff --check` 通过。
- **协作与边界：**Gemini 在真实工作树添加了分级设色回归测试；其本机测试命令遇到工作目录解析问题，未完成验证。有限值过滤由 GPT 实施并审查；鱼网主逻辑由 GPT 整合自 Gemini 隔离副本的设计。未提交或推送，用户原有工作树更改均保留。继续审查其他模块，长期 Goal 未完成。


### 2026-10-30 重复缓冲输出覆盖先前结果

- **复现与影响：**同一点图层先后执行 100 米与 1000 米缓冲，两次都注册为 `<图层>_缓冲区`；第二次覆盖第一份 GeoJSON，无法再引用第一结果。
- **修复：**Gemini 在 `spatial_buffer` 中复用图层名消歧函数，并在 `_state_lock` 内完成选择名称、注册和推送；响应显示实际图层名。新增重复距离回归，验证两个不同注册名及两份不同 GeoJSON 同时保留。
- **验证：**`backend/tests/test_spatial_tools.py -k TestSpatialBuffer`，17/17 通过；相关 `git diff --check` 通过。
- **协作与边界：**Gemini 修改了生产函数；因其在停止点交接了测试用例，Codex 补写并审查回归测试、独立运行验证。未提交或推送；缓冲范围/失败路径仍由既有测试覆盖。


### 2026-10-30 重复多环缓冲输出覆盖先前结果

- **复现与影响：**同一点图层先后以 `100,200` 与 `500,1000` 米创建多环缓冲，两次都注册为 `<图层>_多环m`；第二次替换第一份 GeoJSON。
- **修复：**Gemini 在 `spatial_multi_ring_buffer` 中复用名称消歧逻辑，并在 `_state_lock` 内完成名称选择、注册和推送；成功消息返回实际图层名。新增回归验证两份不同几何分别保留。现有公里单位测试改为容许持久注册表产生的数字后缀。
- **验证：**`TestMultiRingBuffer`，32/32 通过；完整 `backend/tests/test_spatial_tools.py`，233/233 通过；相关 `git diff --check` 通过。
- **协作与边界：**Gemini 修改生产函数；Codex 补回归测试、处理旧测试对固定名称的假设并独立验证。未提交或推送，长程 Goal 继续审查其他工具。


### 2026-10-30 不同简化容差覆盖先前结果

- **复现与影响：**同一锯齿多边形分别用 `0.001` 与 `0.2` 容差运行简化，两个成果都注册为 `<图层>_简化`，第二次替换第一份几何。
- **修复：**`spatial_simplify` 现在使用名称消歧，并在 `_state_lock` 内完成名称选择与注册；成功消息返回实际图层名。回归测试用唯一源图层验证两种容差的输出名称不同、首个 GeoJSON 未改变且第二个几何不同。
- **验证：**`TestSpatialSimplify`，6/6 通过；完整 `backend/tests/test_spatial_tools.py`，234/234 通过；相关 `git diff --check` 通过。
- **协作与边界：**Gemini 未完成本项生产代码改动；Codex 根据已复现根因实施并验证。随后 Gemini 按限定代码和测试完成只读复核，未提出阻塞问题。成功消息新增实际图层名，普通文本消费者需接受这一补充内容。未提交或推送，持续审查其他工具。


### 2026-10-30 不同空间谓词的选择结果互相覆盖

- **复现与影响：**同一目标点图层对同一面图层分别使用 `intersects` 与 `within`。前者返回边界点和内部点共 2 个要素，后者仅返回内部点 1 个要素；两次原先都注册为 `<目标图层>_选择`，第二次替换第一份结果。
- **修复：**Gemini 在 `spatial_select` 中复用结果名消歧，并在 `_state_lock` 内完成名称选择和注册；成功消息返回实际图层名。新增回归断言两个不同名称、两份要素数不同的结果均保留。
- **验证：**`TestSpatialSelect`，3/3 通过；完整 `backend/tests/test_spatial_tools.py`，235/235 通过；相关 `git diff --check` 通过。
- **协作与边界：**Gemini 完成生产函数改动；Codex 补写回归测试，并清理了 Gemini 两次插入的重复测试（其中一份误放在 `TestSpatialDissolve` 且引用未定义变量），然后独立验证。未提交或推送，持续审查其他工具。


### 2026-10-30 不同聚类参数的结果互相覆盖

- **复现与影响：**四个点分别以 `eps=0.0001` 和 `eps=0.005`、`min_samples=2` 聚类。前者是 4 个噪声点，后者形成 2 个簇；两次原先都注册为 `<图层>_聚类`，第二次覆盖第一份 cluster 标签。
- **修复：**Gemini 在 `spatial_cluster` 中使用名称消歧，并在 `_state_lock` 内完成名称选择和注册；成功消息显示实际图层名。回归确认两份结果分别保留 `[-1,-1,-1,-1]` 与 `[0,0,1,1]` 标签。
- **验证：**`TestSpatialCluster`，14/14 通过；完整 `backend/tests/test_spatial_tools.py`，236/236 通过；相关 `git diff --check` 通过。
- **协作与边界：**Gemini 修改生产函数；测试文本插入交接给 Codex 完成并独立验证。未提交或推送，继续检查其他工具的结果生命周期。
- **修复：**Gemini 在 `spatial_near` 中使用 `_disambiguate_layer_name`，并在 `_state_lock` 内完成唯一名称分配与结果注册；成功消息返回实际图层名。Codex 独立添加重复查询回归用例。
- **验证：**先运行回归确认失败（两次结果只留下一个图层）；修复后 `TestSpatialNear` 10/10、完整 `backend/tests/test_spatial_tools.py` 237/237，相关 `git diff --check` 通过。完整文件有 1,690 条既有 deprecation/pending-deprecation warnings。
- **协作与边界：**Gemini 修改生产函数；Codex 审查并独立验证。未提交或推送，长程 Goal 继续审查其他工具。
### 2026-10-30 不同裁剪边界覆盖先前结果（已修复）

- **复现与影响：**同一正方形源图层先后使用左右两个不同裁剪边界，结果都注册为 `<源图层>_裁剪`；第二次替换第一次结果。新增回归 `TestSpatialClip.test_clipping_with_different_masks_preserves_previous_results`，修复前失败（注册结果数为 1，预期为 2）。
- **修复：**桥接回执两次报告本机 RPC 连接被拒绝，且 `::1:59895` 没有监听，无法确认 Gemini 收到任务。为解除已确认缺陷，Codex 在 `spatial_clip` 中复用名称消歧，并在 `_state_lock` 内完成命名和注册；保留裁剪来源 provenance，成功消息继续显示实际结果图层名。
- **验证：**目标回归先失败（只留下 1 个结果），修复后 `TestSpatialClip` 3/3、完整 `backend/tests/test_spatial_tools.py` 238/238，相关 `git diff --check` 通过。完整文件仍报告 1,690 条既有 deprecation/pending-deprecation warnings。
- **协作状态：**此修复由 Codex 临时接手；Gemini 已完成只读复核并给出“无阻塞问题”结论，覆盖锁内唯一命名、provenance、返回图层名及空结果行为。未提交或推送。

### 2026-10-30 不同空间谓词的连接结果互相覆盖

- **复现与影响：**同一多边形与内点、边界点分别以 `predicate=intersects` 和 `predicate=contains`、`how=inner` 连接，结果应为 2 条和 1 条。此前都固定注册为 `<目标>_连接<连接图层>`，后者覆盖前者。新增回归 `TestSpatialJoin.test_different_predicates_preserve_previous_join_results`。
- **修复：**Gemini 在 `spatial_join` 内通过 `_disambiguate_layer_name` 生成唯一名，在 `_state_lock` 内完成命名与注册；成功消息显示实际结果图层名。
- **验证：**新回归先失败（仅留下 1 个结果）；修复后 `TestSpatialJoin` 5/5，完整 `backend/tests/test_spatial_tools.py` 239/239，相关 `git diff --check` 通过。完整文件有 1,690 条既有弃用警告。
- **协作与边界：**Gemini 修改生产函数；Codex 编写回归、审阅改动并独立验证。Gemini 已在会话交接文件中对 `spatial_clip` 修复给出无阻塞审查结论。未提交或推送。

### 2026-10-30 不同随机样本覆盖先前结果（已修复）

- **复现与影响：**同一 8 点图层连续采样 3 个要素，通过受控 sampler 得到 `{0,1,2}` 与 `{5,6,7}`；两次都注册为 `<图层>_采样3`，后一次覆盖先前结果。回归 `TestSpatialSample.test_repeated_sampling_preserves_distinct_samples` 已复现失败。
- **修复：**Gemini 在 `spatial_sample` 中以 `_disambiguate_layer_name` 生成唯一结果名，并在 `_state_lock` 内完成名称选择和注册；成功消息返回实际图层名。保留既有抽样流程与参数验证。
- **验证：**受控 sampler 回归先失败（只留下 1 个图层）；修复后 `TestSpatialSample` 9/9、完整 `backend/tests/test_spatial_tools.py` 240/240，相关 `git diff --check` 通过。完整文件报告 1,690 条既有弃用警告。
- **协作与边界：**Gemini 修改生产函数；Codex 编写回归、审查改动并独立验证。Gemini 已在会话交接文件中确认对应实现及其测试状态。未提交或推送。

### 2026-10-30 不同网格大小的 KDE 结果互相覆盖（已修复）

- **复现与影响：**同一输入点分别以 `grid_size=10` 与 `20` 执行 KDE，两个网格结果不同，却都注册为 `<图层>_KDE`；第二个结果替换第一个。新增回归 `TestSpatialKDE.test_different_grid_sizes_preserve_previous_kde_results` 已稳定复现失败。
- **修复：**Gemini 在 `spatial_kde` 中使用 `_disambiguate_layer_name`，并在 `_state_lock` 内分配名称与注册结果；成功消息返回真实图层名。保持 KDE 计算与参数语义不变。
- **验证：**新回归修复前失败（仅留下一个结果）；修复后 `TestSpatialKDE` 9/9、完整 `backend/tests/test_spatial_stats.py` 19/19，完整 `backend/tests/test_spatial_tools.py` 240/240，相关 `git diff --check` 通过。KDE 测试辅助函数已更新为读取本次新建结果图层；空间工具文件仍有 1,690 条既有弃用警告。
- **协作与边界：**Gemini 修改生产函数；Codex 增加回归、调整因唯一结果命名而过时的测试假设并独立验证。Gemini 已在会话交接文件中确认实现与实际检查范围。未提交或推送。

### 2026-10-30 不同属性连接键覆盖先前结果（已修复）
- **复现与影响：**同一对图层分别按 `key_a/id_a` 和 `key_b/id_b` 执行属性连接，第一份结果匹配到 `score=10`，第二份应为未匹配 `NaN`；两次结果名原来都固定为 `<目标>_连接<源>`，后一次覆盖前一次。回归 `test_different_attribute_keys_preserve_previous_join_results` 已复现失败。
- **修复：**Gemini 在 `join_field` 中为连接结果使用名称消歧，并在 `_state_lock` 内完成唯一名称选择和注册；成功回复保留实际图层名。字段选择、键校验、连接类型与匹配计数逻辑未改动。
- **验证：**新回归修复前失败（只留下 1 个结果）；修复后属性连接相关测试 6/6、完整 `backend/tests/test_vector_gap_tools.py` 20/20，相关 `git diff --check` 通过。现有 inner 测试改为读取本次新建图层，未匹配值以 pandas 空值语义断言。
- **协作与边界：**Gemini 修改生产函数；Codex 编写回归、审查 diff、修正持久注册表引发的旧测试假设并独立验证。审查反馈已通过桥接发回 Gemini；未提交或推送。

### 2026-10-30 不同阈值的热点分析结果互相覆盖（已修复）

- **复现与影响：**同一输入与字段分别使用 `threshold=0.01` 和 `0.2` 运行 Gi*，热点统计属性不同，却都注册为 `<图层>_热点`；第二次覆盖第一份。新增回归 `TestSpatialHotspot.test_different_thresholds_preserve_previous_hotspot_results` 已确认结果内容不同且注册表只留一个图层。
- **修复：**由于桥接连续未带来生产代码变化，Codex 临时在 `spatial_hotspot` 中复用名称消歧；在 `_state_lock` 内选择唯一结果名并注册，成功回复显示实际图层名。
- **验证：**新回归修复前确认两个阈值结果不同、注册表仅留一层；修复后 `TestSpatialHotspot` 2/2 通过，相关 `git diff --check` 通过。Gemini 对此修复的只读审查已随 Moran 任务再次请求，尚未回传。

### 2026-10-30 不同阈值的 Moran’s I 结果互相覆盖（已修复）

- **复现与影响：**同一输入字段使用 `threshold=0.01` 与 `0.2` 运行局部 Moran’s I，`local_moran` 数值不同，却都固定注册为 `<图层>_MoranI`；后一次覆盖第一份。新增回归 `TestSpatialMoran.test_different_thresholds_preserve_previous_local_results` 已确认统计值不同且只留下一个图层。
- **修复：**桥接任务接受后生产函数仍未变化，Codex 临时修复局部 LISA 分支：在 `_state_lock` 内消歧、注册，并在结果消息显示实际图层名；保留 Moran/LISA 计算和字段。
- **验证：**新回归修复前确认阈值导致的 `local_moran` 不同但只剩 1 个结果；修复后 `TestSpatialMoran` 5/5，热点类 `TestSpatialHotspot` 2/2，三组相关测试联合运行 281/281，`git diff --check` 通过。Gemini 对两处临时修复的只读复核已通过桥接索取，待回传。
- **协作与边界：**Codex 临时接手生产实现和回归；Gemini 待只读审查。未提交或推送。

### 2026-10-30 不同字段的空间插值互相覆写栅格（已修复）

- **复现与影响：**同一输入图层、同一 IDW 算法以 `v_left` 和 `v_right` 分别插值，值栅格不同，但当前固定使用 `<图层>_idw.tif/.png` 和同名栅格层；第二次覆写源栅格及预览资源。回归 `TestInterpolate.test_different_fields_preserve_interpolation_rasters` 已复现同名失败。
- **修复：**桥接派发与跟进后生产函数仍未变化，Codex 临时接手。每次插值在写栅格前生成 UUID 命名空间，并在状态锁内经名称消歧确定输出标识；TIFF 与 PNG 共享该次唯一标识，成功消息显示栅格图层名。插值计算本身不持有全局状态锁。
- **验证：**新回归修复前确认同名结果；修复后 `TestInterpolate` 12/12 通过，空间工具、空间统计、矢量属性三组测试联合运行 282/282，相关 `git diff --check` 通过。用不同字段生成的栅格值不同，路径不同，首次文件在第二次运行后保持不变。
- **协作与边界：**Codex 临时修改生产函数并验证；已通过桥接请求 Gemini 只读复核 UUID 并发路径方案，待回复。未提交或推送。

### 2026-10-30 不同几何属性指标覆盖先前结果（已修复）

- **复现与影响：**同一面图层先后请求 `metrics=bbox` 和 `centroid`，输出字段集合不同，却都固定注册为 `<图层>_几何属性`；第二次替换第一份。回归 `test_different_geometry_metrics_preserve_previous_results` 已确认仅保留一个结果。
- **修复：**桥接派发后生产函数仍未变化，Codex 临时修复 `geometry_attributes`：在 `_state_lock` 内用 `_disambiguate_layer_name` 分配并注册唯一结果名；成功消息返回本次实际图层名，指标计算及字段语义保持不变。
- **验证：**新增回归通过；完整 `backend/tests/test_vector_gap_tools.py` 21/21，`test_spatial_tools.py`、`test_spatial_stats.py` 与 `test_vector_gap_tools.py` 联合 283/283，相关 `git diff --check` 通过。联合测试有 1,690 条既有弃用警告。
- **协作与边界：**Gemini 已通过 Antigravity 桥接收到只读审查请求；尚无审查交接。未提交或推送。

### 2026-10-30 不同栅格参数的输出相互覆盖（已修复，待 Gemini 复核）
- **复现与影响：**`raster_resample` 文件名遗漏比例/方法，`raster_reproject` 遗漏目标 CRS，`raster_reclassify` 遗漏规则/方式/类别数，`raster_focal_stats` 遗漏窗口大小，`raster_calculator` 固定为 `<layer>_calc` 而遗漏表达式。同一输入用不同参数运行会生成不同栅格，却写入同一 TIFF 路径并覆盖前次输出；preview 也沿用同一标识。五项新增回归在修复前均失败并确认路径相同。
- **修复：**桥接消息已接受，但 Gemini 会话没有新的执行记录或交接，生产文件保持不变。Codex 随后在五个输出名中加入全 UUID 标识：计算器、重采样、重投影、重分类、焦点统计均用本次标识生成栅格/预览层名；不在长计算阶段持有全局锁。重采样、重投影、重分类、焦点统计保留操作名后缀，方便现有文件匹配逻辑。
- **验证：**五项新增回归通过：不同参数产生不同图层名、TIFF 与预览 PNG 路径，第一次文件在第二次执行后仍保持原内容。完整 `test_raster_gap_tools.py` 79/79；`test_new_tools.py` 中重采样/重投影相关 5/5；`test_spatial_tools.py` 中计算器、重分类和流向后续重分类相关 8/8；`test_raster_provenance.py` 1/1；`test_coverage_gap.py` 中栅格相关 5/5；相关 `git diff --check` 通过。`test_project_raster_persistence.py` 因环境缺少 `keyring` 导致项目保存返回错误，整文件 34 项失败、13 项通过；两项直接调用端到端测试也因同一依赖在任务持久化阶段失败。不能把这些结果作为本次命名代码的回归结论。
- **协作与边界：**已通过 Antigravity 桥接通知 Gemini 停止写生产代码，改为只读审查五项修复及此前四项 Codex 改动。首个复核请求触发 OAuth 取令牌 EOF；一次短重试目前只看到 Gemini 的计划器回复和工作区状态检查，尚无实际审查结论。未提交或推送。
