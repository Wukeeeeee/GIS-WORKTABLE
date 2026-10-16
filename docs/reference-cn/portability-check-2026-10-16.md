> CN 仓库历史材料：其中端口、部署档位和实测结果仅指 CN 仓库，不是国际版验收记录。

# Windows 独立环境与真实浏览器全流程验收检查（2026-10-16）

## 1. 范围与诚实原则说明

- **测试环境**：本机 Windows、Python 3.13.0；在独立虚拟环境及无头 Chromium 浏览器环境下实测。
- **关于“换机 / 全新环境”的真实边界**：
  > [!IMPORTANT]
  > **诚实声明**：受限于当前运行环境约束，**未能在外部第二台物理电脑或干净虚拟机中实测**。本次验证是在本机新建完全隔离、不继承全局包的 `.venv` 虚拟环境中严格执行安装与链路调用。绝不把本机独立环境测试伪作为异机测试通过。
- **关于 AI 链路的真实边界**：
  > [!NOTE]
  > **诚实声明**：当前测试环境中**未配置商业大模型有效 API Key**。按照交付原则，如实记录真实 AI 大模型调用为**未验证**，不伪造模型对话和工具编排记录。AI 离线单测（模拟 Mock/决策链）在 Layer 2 测试中通过。

---

## 2. 验收中发现的问题与代码修复清单

在本轮换机验收与端到端链路排查中，共发现并修复以下 8 项问题：

1. **`backend/requirements.txt` Windows 默认编码读取失败**
   - **现象**：在 Windows 默认 GBK/CP936 环境下，使用 `pip install -r backend/requirements.txt` 时因文件包含 UTF-8 特殊字符触发 `UnicodeDecodeError` 挂起。
   - **修复**：在 `requirements.txt` 首行显式声明 UTF-8 编码，规范中文注释。
2. **`scripts/run_layered_tests.py` Windows 控制台 Unicode 编码崩溃**
   - **现象**：测试运行器在 Windows 命令行下尝试输出 Unicode 对勾符号 `\u2713`，触发 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'` 崩溃。
   - **修复**：将测试通过状态输出规范化为跨平台安全的 `[PASS]` 纯文本。
3. **`backend/main.py` Shapefile 导出对多几何类型数据 500 崩溃**
   - **现象**：当待导出图层包含混合几何类型（如同时包含面与线/点）时，GDAL/Fiona 抛出 `Attempt to write non-polygon geometry to POLYGON shapefile`，导致 `/api/export/shapefile` 报 500 错误。
   - **修复**：在 `_export_shp_sync` 中加入几何类型统一化清洗，识别混合类型并明确提示拆分图层或使用 GeoJSON，避免静默丢失要素。
4. **`.gitignore` 误将复现样例数据排除**
   - **现象**：根目录 `.gitignore` 设置了 `*.geojson`，导致交付验收所需的合成示例数据无法提交进版本库和源码包。
   - **修复**：增加白名单规则 `!data/sample_delivery_test.geojson`，确保示例数据随仓分发。
5. **文档表述冲突与口径校对**
   - **现象**：`docs/competition/demo-script.md` 中提及启动档位与 `start.bat` 实际行为不一致，且部分章节存在绝对化描述。
   - **修复**：修正启动说明（`start.bat` 默认以 `cn` 档启动，显式 `set GISWTB_PROFILE=competition` 切换展示档）；规范地图合规与受控数据源口径，对齐 `README.md` 与 `docs/cn-network-audit.md`。
6. **连续双击并发冲突（端口 10048 崩溃与浏览器弹窗风暴）**
   - **现象**：用户在资源管理器中快速连续双击 `start.bat` 时，会并行触发两个 bootstrap 依赖安装进程或并发拉起两个 uvicorn 后端，导致套接字绑定冲突抛出 `[WinError 10048]`，并重复打开多个浏览器标签页。
   - **修复**：在 `scripts/bootstrap_windows.ps1` 引入 `bootstrap.lock` 独占锁，在 `backend/launcher.py` 增加启动互斥锁与单实例检测，同时在 `open_browser` 增加 3 秒防抖，降低并发冲突风险；提交前补充锁等待超时必须报错退出的保护。
7. **复制来的失效 `.venv` 自动识别、备份与重建**
   - **现象**：若用户从其他电脑或目录直接拷贝带绝对路径的失效 `.venv`，原脚本未明确提示且容易在损坏环境上继续执行失败。
   - **修复**：在 `scripts/bootstrap_windows.ps1` 增加对 `.venv` 解释器可用性的主动探测；一旦发现损坏/失效，主动发出 `[WARN]` 警示并自动将旧环境安全备份至 `.bootstrap/old-venv-<guid>`，原地调用 uv 重建干净纯净的 `.venv`。
8. **GitHub 无法访问时的明确故障恢复指引**
   - **现象**：全新机器既无 Python 也无 uv 时，下载依赖 GitHub Releases，直连超时后报错模糊；且清华源等 PyPI 镜像只能加速 Python 库，无法解决 Python 解释器本身的下载。
   - **修复**：在 `scripts/bootstrap_windows.ps1` 为 `uv` 补充加速镜像重试；若仍不可达，抛出针对国内用户的中文结构化解决方案（明确指出依赖镜像无法解决 Python 下载，提供华为云/淘宝镜像下载直链及勾选 PATH 说明，并支持 `GIS_PYTHON` 指定已有解释器）。


---

## 3. 验收验证证据

### 3.1 真实浏览器端到端全流程（Playwright 自动化实测）

运行脚本 `scripts/verify_browser_delivery_flow.py`，完整覆盖真实用户操作链路，控制台报错为 0，各步骤验证记录如下：

| 步骤 | 操作环节 | 实测结果 | 产物 / 验证依据 |
| :--- | :--- | :--- | :--- |
| **[1/8]** | 访问工作台首页 | **PASS** | 端口 8010，DOM 及 `#map` 地图容器就绪 (`01_homepage_loaded.png`) |
| **[2/8]** | 导入随仓合成 GeoJSON | **PASS** | 成功解析 3 个要素（面、线、点），图层自动渲染上图 (`02_geojson_imported.png`) |
| **[3/8]** | 500 米缓冲区空间分析 | **PASS** | 手动空间分析面板触发，成功生成 `sample_delivery_test.geojson_缓冲区` 图层（类型 Polygon） (`03_buffer_analyzed.png`) |
| **[4/8]** | 属性表检查 | **PASS** | 属性面板成功打开，表头共 11 列，数据真实渲染 3 行 (`04_attribute_table.png`) |
| **[5/8]** | 处理历史审查与重跑 | **PASS** | 历史记录抽屉审查通过，重跑按钮成功触发空间计算 (`05_history_and_rerun.png`) |
| **[6/8]** | Shapefile 导出解包核查 | **PASS** | 导出接口返回 3682 字节 ZIP，解包校验完整包含 `.shp`, `.shx`, `.dbf`, `.prj`, `.cpg` 五大核心文件 |
| **[7/8]** | 保存当前工程 | **PASS** | 生成持久化工程 ID `8a5a9adf`，落盘保存至工程库 (`06_project_saved.png`) |
| **[8/8]** | 服务关停与重启恢复 | **PASS** | 杀掉后端进程后重新拉起端口 8010，新会话加载该工程 ID，成功恢复全部 3 个图层 (`07_project_reopened.png`) |

> 截图证据文件保存在 `output/browser_verification_20261016/` 目录下。

### 3.2 分层回归测试证据

运行 `python scripts/run_layered_tests.py --mode all`，五层架构全绿：
- **Layer 1 (单元测试)**: CRS 坐标转换、Shapefile 导出规范、网络域名白名单全部通过；
- **Layer 2 (Agent 决策)**: 意图解析、工具选择、重试机制测试全部通过；
- **Layer 3 (GIS 工具服务)**: 缓冲区、相交、面合并等算法全部通过；
- **Layer 4 (地图集成)**: 图层注册、状态同步、GeoJSON 序列化全部通过；
- **Layer 5 (端到端集成)**: 服务启动器、健康检查接口全部通过。

---

## 4. 交付未覆盖项清单（真实记录）

1. **全新异机安装**：未在另一台物理 PC（如不同的 Windows 用户权限、不同 CPU 架构或全新未配置 Python 的机器）上测试；
2. **真实大模型联网对话**：未填入有效付费商用 API Key 实测模型推理与动态工具编排；
3. **完全离线无网依赖安装**：未测试在完全切断互联网连接的主机上从零执行 `pip install`（需要离线 wheel 包镜像）。
