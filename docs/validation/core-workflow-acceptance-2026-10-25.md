# GIS WorkTable 核心流程验收记录

日期：2026-10-25
环境：Windows，本地 FastAPI 工作台，Python 3.13.0，Codex 内置浏览器。
工程：`GIS WorkTable 验收 2026-10-25`（本地工程 ID `8bc72c24`）。

本记录依据当前工作区中的实际界面操作及定向后台回归。验收开始时，以下已有未提交变更已存在，本轮保留且未修改：`backend/services/tool_args_guard.py`、`backend/services/tools.py`、`backend/tests/test_spatial_tools.py`、`frontend/ui-style-comparison.html`。

## 用户流程清单

| 流程 | 复现步骤 | 结果与证据 | 状态 |
| --- | --- | --- | --- |
| 加载并显示数据 | 新建空白工程 → 首页“快速体验” → 加载“多边形地块”样例 → 打开图层面板 | 页面提示样例已加载；图层面板显示 1 个 Polygon 图层、3 个要素，地图显示范围随样例调整。 | 通过 |
| 执行主要空间工具 | “空间分析” → 选样例图层 → 距离 500 米 → “运行缓冲区” | 页面提示成功、生成 1 个缓冲结果图层；图层面板显示原图层和结果图层，各 3 个 Polygon 要素。 | 通过 |
| 拒绝无效缓冲输入 | 距离设为 0 并运行；再输入多环距离 `100,,200` 并运行 | 分别显示“缓冲距离必须大于 0”与“每项距离必须为有限正数”；两个失败操作均未创建结果图层。 | 通过 |
| 保存并重新打开工程 | 保存到工作台 → 刷新浏览器 → 从首页最近工程打开该工程 | 工程名恢复；图层面板恢复为 3 个图层：样例面、缓冲面、COG 栅格。`GET /api/projects/8bc72c24` 返回三项记录及地图视图；`GET /api/projects/8bc72c24/assets/83ec9edc8a5af25feacd.png` 返回 HTTP 200、`image/png`、786609 字节。 | 通过 |
| 加载远程 COG 并显示 | AI 助手 → 连接器 → 添加在线数据；保留自动识别，输入下方公开 `.tif` 地址并加载 | 界面提示 COG 已加载，图层面板出现 `COG影像`（Raster）；保存、刷新并重开后该图层和工程内 PNG 预览资产仍可访问。独立远程集成用例也通过，但伴随一条 Rasterio 解码警告，详见下文。 | 通过（有警告） |

远程 COG 样例地址（与现有集成测试相同）：

`https://raw.githubusercontent.com/rasterio/rasterio/main/tests/data/RGB.byte.tif`

## 定向自动化回归

命令：

```text
python -m pytest -p no:cacheprovider -q --disable-warnings --maxfail=1 backend/tests/test_spatial_tools.py backend/tests/test_project_raster_persistence.py backend/tests/test_cloud_native.py -m "not slow"
```

结果：**139 passed，4 deselected，1 warning**。范围仅为上述三个测试文件；4 个 `slow` 用例未计入，不能据此声称整个后台测试集通过。此批次单独记录，不与 2026-10-24 的 531 项回归合并或相加。定向测试包含本工作区已有的空间缓冲修改；远程 COG 的真实网络加载证据来自本记录中的界面操作，不计入 139 项。

另外单独运行 `python -m pytest -p no:cacheprovider -q -rW backend/tests/test_cloud_native.py::test_integration_cog_remote -m slow`：**1 passed，1 warning**。公开远程 COG 读取成功；警告为 `PytestUnraisableExceptionWarning`，Rasterio 的 `log_error` 回调在 Windows 上解码 GDAL 错误字节时触发 `UnicodeDecodeError`。现有下载回退仍完成了影像读取并生成预览，但该运行时警告尚未消除；因此 COG 路径记为“功能通过，有非致命运行时警告”。此单项 slow 测试是独立批次，不并入 139 项。

## 未覆盖范围

- 本轮数据加载使用内置样例，没有通过本地文件选择器重新验收真实文件上传。
- 本轮远程样例为 RGB COG，不是 DEM；未在浏览器中验收真实 DEM 的栅格计算结果进入图层面板、保存并重新打开。现有后台测试覆盖真实 TIFF 的保存/恢复与栅格重采样链路，但不等同于完整浏览器操作。
- 未验收 `.giswork` 导出/导入、完整 Electron 窗口、真实 AI 模型调用或其他外部数据服务。恢复工程时界面显示当前模型未配置 Key。

本轮核心用户流程未发现需修改代码的复现故障，因此未对已有源代码改动。全库逐模块扫描仍未完成。

## 英文界面与本地文件导入补充验收

日期：2026-10-25。使用当前工作区代码，在 Windows 本地服务的另一空闲端口及 Codex 内置浏览器中继续验收。与上方最初验收相比，本补充记录了后续英文界面和本地文件操作；两部分不是同一次从空白开始的会话。

| 流程 | 复现步骤 | 结果与证据 | 状态 |
| --- | --- | --- | --- |
| 英文主工作区 | 设置 → Appearance → English；分别打开 Home、Data、Layers、Tools | 导航、数据接入、空间工具、图层类型/计数、缓冲参数、常用地图控件、坐标状态和 Bing 地图署名以英文显示。保留原始用户数据名；部分高级设置、处理历史、帮助、地图提示及 API 错误仍有中文。 | 通过（局部覆盖） |
| 本地 GeoJSON 选择器导入 | Layers → Upload → 选择仓库中的 `frontend/samples/demo-polygons.json` → 检查预览 → Upload | 浏览器文件选择器、上传前预览和本地 FastAPI 上传实际完成；预览显示 3 个 Polygon 要素与 `name`、`group`、`score` 字段，上传成功后图层列表显示 3 个要素。该证据只覆盖仓库内的小型 GeoJSON fixture，不代表 Shapefile、GeoPackage 或大型文件等格式均已通过。 | 通过（GeoJSON fixture） |
| 本地导入后的分析与恢复 | 对 `demo-polygons.json` 运行 500 米缓冲 → 保存为/更新 `GIS WorkTable International Demo` → 刷新 → 从最近工程打开 | 缓冲输出新增 1 图层、3 个 Polygon 要素；工程恢复后显示 4 个图层，包含本地导入文件及其结果。英文完成状态和 500 米结果说明可见。工程记录保存在本机应用工作区数据库，不是仓库内的可移植 `.giswork` 文件。 | 通过 |

本补充验收没有运行完整测试集；针对修改脚本的 `node --check` 及 `git diff --check` 通过，词条检查覆盖了 110 个静态界面键且未发现缺失。它不构成跨浏览器、跨平台、完整国际化或性能验证。

## 英文在线数据配置入口补充检查

日期：2026-10-25。使用当前工作区代码在 Windows 本地 FastAPI 服务（`127.0.0.1:8010`）和 Codex 内置浏览器中打开英文设置及数据连接器。

| 流程 | 复现步骤 | 结果与证据 | 状态 |
| --- | --- | --- | --- |
| 英文在线数据配置说明 | 设置 → Geospatial services | GeoSource 索引目录、云原生格式在线数据入口、账号与 API Key 状态、用户名/密码表单和主要全球/中国区域服务说明可读；动态凭据状态显示为英文。 | 通过（配置界面） |
| 英文数据连接器面板 | 设置 → Geospatial services → Add online data | 动态服务清单、配置计数、服务说明、设置按钮、格式选择项、URL 输入提示、加载按钮及格式说明均显示英文。列出的格式包含 COG/远程 GeoTIFF、PMTiles、GeoParquet、FlatGeobuf 和 ArcGIS REST。 | 通过（入口界面） |

这项检查只验证英文配置界面和入口文案，没有在本轮填写或发送服务凭据，也没有重新请求第三方在线服务。此前公开 RGB COG 的浏览器加载证据仍以本记录上方流程为准；ArcGIS REST、PMTiles、GeoParquet、FlatGeobuf 和需要账号的供应商在本轮均未重新端到端验收。在线端点可用性、授权、跨域策略和服务条款需要逐个服务确认。GeoSource 检索结果与动态加载提示中的其他语言覆盖仍需继续审查。

## 英文 GeoSource 目录检索补充检查

日期：2026-10-25。当前工作区在 Windows 本地 FastAPI 工作台和 Codex 内置浏览器中以英文界面运行。

| 流程 | 复现步骤 | 结果与证据 | 状态 |
| --- | --- | --- | --- |
| 打开并检索在线服务目录 | 设置 → Geospatial services → Open data catalog → 搜索 `DEM` | 目录标题、筛选器、类别/国家标签、计数、分页及结果卡片动作以英文显示。后端本地目录返回 62 条匹配服务、当前页显示 20 条；结果源字段中的服务描述保留提供方原始语言。切换到简体中文并重新打开目录时，国家选项、结果数量和卡片动作恢复中文；再切回英文后恢复英文。 | 通过（本地目录查询、界面与双语切换） |
| 查看服务详情 | 在首条结果点击 Layers and details | Protocol、Format、Update frequency、Coverage 等界面标签和子图层操作以英文显示；详情来自本地服务目录 API。 | 通过（本地详情查询与界面） |

以上只证明本地 GeoSource 索引可检索并返回元数据，不能证明列出的外部服务端点当前可访问、免密、完整或获准用于特定用途。本轮没有调用第三方服务端点或发送凭据。英文版仍有未翻译界面；中国用户及国内演示应保留简体中文，翻译能力作为可切换界面而非在线数据可用性的证明。

## 便携工程往返与远程 ArcGIS REST 获取补充验收

日期：2026-10-25。使用 Windows 本地 FastAPI 工作台（`127.0.0.1:8010`）和 Codex 内置浏览器。

| 流程 | 复现步骤 | 结果与证据 | 状态 |
| --- | --- | --- | --- |
| 生成便携演示工程 | 导入 `frontend/samples/demo-polygons.json` → 运行 500 米缓冲 → 导出 `.giswork` | 仓库新增 `frontend/samples/GIS-WorkTable-Competition-Demo.giswork`，包含工程元数据和两个压缩 GeoJSON 图层；输入、缓冲结果各 3 个 Polygon 要素。 | 通过 |
| 便携工程导入恢复 | 在另一空白浏览器工作台通过“文件 → 打开工程 → 导入本地 .giswork 文件”导入上述文件 | 工程名恢复；图层列表显示输入层和 `demo-buffer-500m`，各 3 个要素。该项验证工程包可从仓库示例路径导入并恢复图层数据。 | 通过 |
| 公开 ArcGIS REST 预览获取并上图 | “数据 → 数据源连接器 → 添加在线数据” → 选择 ArcGIS REST → 输入 `https://sampleserver6.arcgisonline.com/arcgis/rest/services/Census/MapServer/1` → 保留限量预览 → 获取 | 任务 `8528bf719f23484c92deb6718d93546f` 完成；生成 GeoJSON 文件 22,285,981 字节，预览 1,000 个 Polygon/MultiPolygon 要素、EPSG:4326；图层面板显示 1 个 ArcGIS 数据图层和 1,000 features。无账号或 API Key。界面和报告标明完整性未检查，结果没有核对源服务要素总数。 | 通过（限量预览） |

在线服务地址由 [Esri Census 示例 MapServer](https://sampleserver6.arcgisonline.com/arcgis/rest/services/Census/MapServer) 提供，属于第三方示例端点，服务方可调整或移除。该次结果只证明当时从此工作环境成功请求并加载了预览；不证明现场网络、其他地区、其他服务或完整下载均可用。`frontend/samples/GIS-WorkTable-Competition-Demo.giswork` 是可移植的离线主演示；公开服务连接作为可选演示环节。

本补充验收为人工浏览器流程，没有运行自动化测试集；不代表完整 ArcGIS 获取、外部服务目录条目的可用性或清洁电脑首次安装已验证。
