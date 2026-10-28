<p align="center">
  <img src="frontend/assets/logo-readme.png" alt="GIS WorkTable" width="320">
</p>

# GIS WorkTable

[English README](README.en.md)

面向 GIS 学习和空间分析验证的 AI 原生地理工作台。用户可以用自然语言请求 AI 调用现有数据与 GIS 工具，并在地图、图层和工程中检查、继续处理结果；手动工具也可独立使用。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](backend/requirements.txt)

[快速开始](#快速开始) · [北京大赛提交要求](#北京大赛提交要求) · [比赛演示步骤](docs/competition/demo-runbook.zh-CN.md) · [功能说明](docs/features.md) · [架构](docs/architecture.md) · [参与贡献](CONTRIBUTING.md) · [更新日志](CHANGELOG.md)

适合 GIS 学习、空间分析原型验证和工作流演示。项目持续开发中；桌面客户端为实验性功能，分析结果需要结合数据质量、坐标系和方法适用性核验。

国内演示以简体中文为主。可下载并导入[便携演示工程](frontend/samples/GIS-WorkTable-Competition-Demo.giswork)，按[比赛演示步骤](docs/competition/demo-runbook.zh-CN.md)复现本地缓冲分析；在线公开服务演示为可选步骤，受网络和服务状态影响。

## 工作台预览

![GIS WorkTable：图层侧面板与卫星底图上的实心点](docs/images/worktable.png)

已验证的操作及未验证范围见 [工具验证记录](docs/tool-validation.md)，近期改动见 [更新日志](CHANGELOG.md)。

## 北京大赛提交要求

本项目拟参加**第四届开放原子大赛·2026 开源行业解决方案创新赛**赛道一“开源基础软件与解决方案”。按[赛事官网](https://www.oschina.net/oa2026/)当前公布的要求，赛道一需准备三项材料：

1. **代码仓库链接**：仓库需包含完整、可运行的代码。
2. **作品介绍文档**：推荐 PDF，介绍项目背景、技术架构、应用场景和创新点。
3. **作品演示视频链接**：展示核心功能和使用流程。

三项材料需打包，并于 **2026 年 10 月 31 日 24:00 前**发送至大赛组委会邮箱 `bjoscc@oschina.cn`；官网说明报名审核通过后会邮件通知提交指引。团队招募对象和报名主体须符合官网规则，个人资格如不确定需先向组委会核实。项目侧的演示步骤与材料核对见[参赛准备说明](docs/showcase.md)和[参赛作品说明工作稿](docs/competition/submission-brief.zh-CN.md)。

## 近期维护（2026-10-28）

本轮按模块追踪“入口 → 执行 → 结果 → 保存”，集中修复中途断开的调用与状态：

| 模块 | 主要改动 |
| --- | --- |
| 公开数据获取 | ArcGIS 图层检查、预览与分批完整获取；显示完整性状态，交付数据、报告、脱敏来源及复跑配方 |
| AI 执行与反馈 | 修复空响应恢复、任务与会话上下文、并行工具状态、重试及确认/取消；地图操作等待图层准备完成 |
| 图层与工程 | 注册和保存有序执行；按版本删除图层，避免清理旧结果时误删新数据；保留分组、样式和历史 |
| 上传与原始栅格 | 避免同名文件覆盖，校验格式与坐标系，处理取消后的迟到响应；磁盘空间不足时提示上传未完成并清理部分文件；原始 GeoTIFF 随工程保存、导出和导入，重载后可继续计算 |
| 工具菜单与分析启动器 | 补齐动态分析启动器的英文标题、分类和 20 个工具名称，切换语言时同步更新 |
| 数据源与空间分析 | 修复地铁字段、线路匹配及数据交付衔接；修正重复坐标的近邻选择，并限制统计计算的内存占用 |
| 启动与桌面客户端 | 修复进程探活、启动超时、失败反馈、退出清理和多实例隔离；完善本机 MCP 接入 |
| 日志与内部清理 | 加固凭据写入、任务/日志持久化及错误脱敏；移除无消费方的状态，过时测试改为覆盖当前入口 |
| 交接与导入可靠性 | 上传交接失败时回滚地图、图层面板和后台注册；共享状态桥接保留注册版本令牌；工程 ZIP 导入增加请求体、条目数与解压容量限制 |
| GeoSource 与请求安全 | 带 API Key 的跨主机跳转会停止并提示；目录只读 SQL 限制为 10,000 字符和 5 秒；代理响应隔离上游 HTML/SVG，公网跳内网仍会拦截 |
| 工程保存与结果说明 | 工程正文保存成功但索引写入失败时保留工程并提示；列表可从工程文件重建索引；网络服务区明确标注凸包近似，聊天纯文本按文本显示 |
| 新会话与工程隔离 | 新建会话时重置服务端活动工程图层上下文；删除旧工程不再清空新会话的图层注册 |

截至 2026-10-28 已完成多轮模块审查和高价值缺陷修复，后续审查仍在继续。自动化回归、真实数据检查和未验收范围分别记录在 [扫描进度](docs/validation/module-scan-progress.md)；通过本地检查不代表所有在线服务、真实模型或完整界面均已验收。

真实数据验收使用带 `EPSG:4326` 的 SRTM-derived DEM：在浏览器中生成坡度、坡向和五级分位重分类结果，保存并重载工程后再次运行坡度分析，再保存、重开并检查恢复的 4 个栅格图层及其来源、CRS、值单位和质量提示。该小范围样例验证工作流衔接，不代表外部地形精度或业务适用性已通过基准验证。

本地回归复核（2026-10-26）：前端 267 项通过；后端 1,432 项通过、5 项跳过、0 项失败（17 条警告）。远程服务、真实模型及完整浏览器任务不由这些自动化结果代表，具体范围见[扫描进度](docs/validation/module-scan-progress.md)。

本地文件上传另在隔离浏览器和临时服务（`127.0.0.1:8003`）中复测：小型 GeoJSON 与有效 `EPSG:4326` GeoTIFF 均进入图层面板；无效 TIFF 返回可读解析错误且无残片。故障注入代理模拟“后端已成功登记、浏览器响应丢失”后，前端通过请求编号恢复同一结果，最终只有一个图层和一份上传文件。该复现验证了响应丢失恢复机制，但不能确认用户最初在 8000 页面遇到 `Failed to fetch` 的具体原因；没有向 8000 上传文件。当前运行中的 8000 后端尚无上传状态查询接口（返回 404），因此需由用户重启/更新该服务后，新恢复流程才可用。

## 主要能力

| 能力 | 内容 | 使用条件 |
| --- | --- | --- |
| 手动 GIS 操作 | 图层管理、绘制、测量、缓冲、叠置、符号化、属性编辑、处理历史与重跑 | 本地分析无需模型 API Key |
| AI 助手 | 用自然语言组织 GIS 工具，结合当前图层执行任务 | 配置兼容 OpenAI 接口的模型服务 |
| 2D/3D 地图 | 共享图层、行政区浏览和面要素拉伸 | 底图和在线边界服务需要网络 |
| 空间分析 | 地形、遥感指数、插值、空间统计、网络分析及矢量栅格转换 | 需要对应输入；OD 矩阵需路网，部分工具需在线数据 |
| 数据接入 | 文件导入、GeoSource 目录检索、OGC/ArcGIS 服务、云原生格式 | 数据库快照、服务可用性及授权因来源而异 |
| 工程与导出 | 工程保存与恢复（.giswork）、图层/地图/报告导出、工作流 | Shapefile/GeoJSON 图层可用于 QGIS 和 ArcGIS |

详细功能见 [功能说明](docs/features.md) 和 [分析工具手册](docs/USER_GUIDE_ANALYSIS_TOOLS.md)。可调用工具以注册表为准，目录条目不保证来源始终可用。

## 快速开始

### 环境要求

- Python 3.11+，建议使用独立虚拟环境；依赖包含地理计算库。
- 现代浏览器；前端无需 Node.js 构建。
- 桌面版额外需要 Node.js / npm 和 Electron 依赖。
- 使用 AI 时需要模型服务配置；手动本地分析可先不配置模型。

### 安装与启动

Windows 64 位用户可直接双击 `start.bat`：自动检查 Python 3.11–3.13 与依赖，必要时创建项目虚拟环境并安装依赖，然后启动浏览器。首次运行需要联网、目录可写；安装缓存位于 `.bootstrap/`。已有可用 `.venv` 优先复用，`GIS_PYTHON` 可指定创建环境的基础解释器。

以下为手动安装方式（macOS / Linux 仍需按实际环境安装）：

以下命令在仓库根目录执行：

```bash
git clone https://gitee.com/wukeeeeee/GIS-WORKTABLE.git
cd GIS-WORKTABLE
python -m venv .venv
```

Windows PowerShell 激活环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS / Linux 激活环境：

```bash
source .venv/bin/activate
```

安装依赖并启动 Web 版：

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。开发时可在启动命令末尾添加 `--reload`。

Windows 可运行 `start.bat` 或 `scripts/start-desktop.bat`。启动器只复用当前仓库的 GIS 服务；默认固定使用 8000，冲突时报错，不自动切换端口，以保持浏览器本地存储地址稳定。可以用环境变量 `GIS_PORT` 手动指定其他端口。`scripts/stop.bat` 只停止默认端口（或 `GIS_PORT` 指定端口上）身份匹配的服务；更新前启动的旧服务请在原窗口按 Ctrl+C 关闭。

Windows 自动启动优先复用通过检查的项目 `.venv`；`GIS_PYTHON` 指定创建环境时使用的基础解释器，未指定时探测系统 Python，必要时下载运行时。上述手动安装命令尚未在全新环境验证，macOS / Linux 也尚未完成平台验收。

### 试用公开数据获取（可选）

这条数据流程不需要 WorkTable 的 AI 模型 Key。

1. 首页「公开数据获取」→「输入地址」，或选择「试用样例」。
2. 点击「检查图层」，确认图层和条件后选择「限量预览」或「完整获取」，再点击「获取」。
3. 查看结果状态和地图，下载数据、检查报告、来源清单与复跑配方。

预览不检查完整性；完整获取仅核对对象 ID，不证明属性、许可或分析结论正确。详细边界和操作见 [获取指南](docs/USER_GUIDE_ARCGIS_URL.md)。

### 配置

- **模型服务**：设置 → AI 模型，填写 Provider、Base URL、模型名和 API Key。配置保存在浏览器 localStorage；调用 AI 时，密钥随请求发送到本地后端，由后端访问所选模型服务。公网模型地址须使用 HTTPS；本机或明确解析为内网地址的 HTTP 服务仍可接入，但 HTTP 不加密，只应在可信本地网络使用。若配置了自定义代理，模型请求也会经过该代理，包括私网模型地址。
- **本机 API 请求来源**：浏览器发起的 API 请求（包括读取和状态变更）只接受本机来源，并拒绝标记为跨站的请求；这不是客户端身份认证，无来源头的本机程序或 MCP 客户端仍可调用 API。内置启动器默认绑定 `127.0.0.1`，不要将服务暴露给不可信用户。
- **Python 执行边界**：`execute_python` 在本地子进程运行，有 AST 代码规则和 120 秒超时，并按名称尽可能过滤常见凭据环境变量、移除带用户名密码的 HTTP(S) 代理环境变量；导入 OSMnx 不会自动探测 Overpass 网络。它仍不是操作系统级安全沙箱，不隔离本地文件、网络或资源，也无法识别改用自定义名称保存的秘密。内置启动器默认绑定 `127.0.0.1`；不要将服务暴露给不可信用户或作为公开多租户服务。
- **外部 AI 客户端（可选）**：已有 Codex 等客户端可通过本机 MCP 调用 GIS 工具，WorkTable 不必另配模型 Key；外部客户端仍需自己的模型服务。Windows 安装依赖后，在 `%USERPROFILE%/.codex/config.toml` 添加以下配置，并替换仓库路径：

  ```toml
  [mcp_servers.gis_worktable]
  command = "C:/path/to/Gis-WorkTable/.venv/Scripts/python.exe"
  args = ["-m", "backend.services.mcp_server"]
  cwd = "C:/path/to/Gis-WorkTable"
  ```

  当前为本机 `stdio` 连接。其他客户端、界面配置和目录权限见 [MCP 接入指南](docs/mcp_server.md)。
- **外部数据源**：按需在连接器中配置账号或密钥；无需为本地手动分析配置所有数据源。
- **GeoSource**：默认使用 `data/gis_services.db`；也可能优先读取更新时间更晚的同级 `GeoSource/gis_services.db`。可通过环境变量 `GEOSOURCE_DB_PATH` 指定已有数据库文件。界面展示所选快照时间及目录记录状态；这些信息不代表实时连通性。若服务支持 URL 查询参数形式的 API Key，用户可在接入时填写；GeoSource 请求经本机 WorkTable 代理发送，密钥只转发给原服务，不交给 AI 或保存到工程。带认证参数的请求若跳转到另一主机，代理会停止请求并提示使用服务方提供的直连地址；代理允许用户直接选择内网服务，并拦截公网服务跳转到内网或回环地址。目录只读 SQL 限制为 10,000 字符、最长运行 5 秒。请求头、OAuth 和账号密码认证暂不支持。服务目录关联项目与 MCP 集成见 [GeoSource-MCP](https://github.com/Wukeeeeee/GeoSource-MCP.git)。
- **本地状态**：会话、任务和处理历史位于 `cache/`，生成产物位于 `output/`；清理前请保存需要保留的工程和结果。

### Windows 脚本与桌面版

依赖安装完成后，可使用根目录 `start.bat` 启动 Web 版，`scripts/stop.bat` 停止服务。

桌面版先安装依赖，再运行 `scripts/start-desktop.bat`：

```bash
cd desktop
npm install
cd ..
```

桌面外壳依赖本机 Python 环境，目前仅有 Windows 人工验证。

## 架构与目录

```text
backend/       FastAPI 入口、Agent、GIS 工具、数据连接器、pytest 测试
frontend/      原生 HTML/CSS/JS、Leaflet 与 CesiumJS
desktop/       Electron 桌面外壳
knowledge/     GIS 方法与知识模块
skills/        项目内 GIS 领域提示文档（不是 Codex skill 安装目录）
data/          GeoSource SQLite 数据库快照
docs/          功能、架构、协作规范与发布文档
```

前端使用 `frontend/js/gis_state.js` 统一管理图层、选中要素和下钻状态；手动工具与 AI 调用复用后端 GIS 工具及图层产物通道。详见 [架构与模块](docs/architecture.md)。

## 开发与分层测试体系

项目构建了不与 GIS 主系统割裂的 **五层分层测试体系**（覆盖单元、Agent 决策、GIS 工具集成、地图图层与 E2E 业务），详情见 [分层测试指南](docs/layered-testing-guide.md)。

可使用统一测试脚本 `scripts/run_layered_tests.py` 按需分组执行：

```bash
# 1. 快速模式（~2s）：Layer 1 (单元) + Layer 2 (Agent)，适合 Prompt 或逻辑微调
python scripts/run_layered_tests.py --mode fast

# 2. 集成模式（~6s）：Layer 3 (GIS 工具) + Layer 4 (地图图层通道)，适合空间处理修改
python scripts/run_layered_tests.py --mode integration

# 3. 全量回归（Layer 1~5 全链路，合并前执行）：
python scripts/run_layered_tests.py --mode regression
```

也可在仓库根目录直接运行 pytest：

```bash
python -m pytest backend/tests/ -q
```

部分测试依赖外部网络或服务，跳过与失败原因应按实际输出记录。测试数量和通过率应附执行环境、命令及提交号，不在 README 中固定写入容易过期的数字。

- [分层测试指南](docs/layered-testing-guide.md)：测试架构、模块边界依赖与分层触发规范。
- [贡献指南](CONTRIBUTING.md)：开发流程、工具扩展、验证与 PR 要求。
- [命名与描述规范](docs/repository-standards.md)：项目名、文件名、分支、提交、Issue/PR、仓库 Description。
- [界面与面板规范](docs/ui-guidelines.md)：黑白灰风格、左侧 AI、数据入口及面板折叠与关闭行为。
- [更新日志](CHANGELOG.md) 与 [发布流程](docs/release-guide.md)：记录变更、版本和验证证据。
- [参赛与项目展示准备](docs/showcase.md)：演示流程、材料清单及待核验事项。
- 问题与建议请提交 [Issue](https://github.com/Wukeeeeee/GIS-WORKTABLE/issues)，尽量附最小复现数据。

## 本地数据存储与持久化说明

- **执行台账数据库**：`data/workspace.db`（本地 SQLite）。用于记录所有 Agent 执行轮次（`runs`）、工具调用与产物关联台账。
- **相对路径设计**：数据库内所有产物均存储为相对于工作区根目录的相对路径（如 `output/nanjing_buffer.geojson`），即便更换存放磁盘或移动项目文件夹，历史记录依然能自愈解析。
- **防历史污染机制**：基于 `run_id` 的单次执行隔离与三方核对（Claim ↔ Registry ↔ Filesystem），杜绝多轮对话中历史同名文件造成的“未真实执行却误判成功”假阳性。
- **工程数据**：保存到 `cache/projects/`；工程包 `.giswork` 包含图层、预览资源，以及已随工程保存的原始 GeoTIFF。既有仅含预览的栅格工程仍可展示，继续计算需要补充原始 TIFF。
- **备份与迁移**：分析工程优先通过 `.giswork` 导出；完整本机备份还需保留 `cache/`、`data/`、`output/` 和个人配置。浏览器内保存的模型密钥不包含在工程包中。

## 更多文档
- [ArcGIS REST 矢量数据获取](docs/USER_GUIDE_ARCGIS_URL.md)：检查图层、预览/完整获取、完整性状态、报告和配方复跑。
- [分析工具与 AI 助手使用手册](docs/USER_GUIDE_ANALYSIS_TOOLS.md)：20 个新工具的用法、AI 路由规则、上下文兜底与排查。

- [分层测试指南](docs/layered-testing-guide.md)
- [AI 对话与工具延迟检查](docs/performance-audit.md)
- [项目路线图](docs/ROADMAP.md)
- [仓库盘点与参赛方向评估](docs/repository-audit.md)
- [功能说明](docs/features.md)
- [架构与模块](docs/architecture.md)
- [MCP Server 配置](docs/mcp_server.md)
- [手动直连工具设计说明](docs/summary_manual_direct_tools.md)
- [3D 地球与下钻调研](docs/research_3d_globe_drilldown.md)

## 已知限制与数据使用

- 结果真实性检查核对已知文件与图层产物，不能证明分析方法或 AI 解读一定正确。
- 卫星影像巡检采用 RGB 启发式初筛，不等同于专业遥感分类。
- DEM 可上传 GeoTIFF，也可通过高程工具获取在线地形数据；在线获取受数据覆盖和网络影响。主地图 3D 视图与工具生成的地形预览是不同能力，不应混为一谈。
- 2026-10-26 在隔离浏览器页和临时服务中，通过本地文件选择分别上传小型 GeoJSON 与带 EPSG:4326 的 GeoTIFF，二者均进入图层面板并显示到地图。此测试没有复现既有 8000 页面上的 `Failed to fetch`，不能据此认定原故障已解决。
- 遥感平台下载、POI、底图、行政边界和 OSM 数据受账号、接口、配额与第三方服务条款约束；超大数据和路网任务可能耗时较长。
- 云原生加载中的预览、抽样或范围过滤可能只展示部分数据，需核对工具输出说明。
- Moran 与热点分析当前使用稠密距离矩阵，单次最多 3000 个要素；更大数据需先聚合或抽样。
- 当前默认启动方式面向本机使用；公开部署前需要单独评估身份认证、工具执行权限及数据隔离。

GIS 结果仅供研究和辅助分析，不替代专业判断。软件许可证不授予第三方底图、影像或数据的额外使用权；使用和分发这些数据时应遵守来源条款。

## 许可证与致谢

项目采用 [MIT License](LICENSE)。Leaflet、CesiumJS、FastAPI、LangGraph、GeoPandas、Shapely、Rasterio 等依赖及第三方数据仍适用各自许可证和使用条款。

卫星影像巡检的算法思路参考 [GeoHarness](https://github.com/Star-Learning/GeoHarness)；空间服务目录关联项目为 [GeoSource-MCP](https://github.com/Wukeeeeee/GeoSource-MCP.git)。

本次跨仓同步范围与验收：见 [同步记录](docs/SYNC-2026-10-16.md)。
