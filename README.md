<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE -- 地理空间分析工作台
</p>

> 更新时间：2026-07-14
>
> > ✅ 可编辑属性表 + 筛选导出为新图层 + 空值填充 + 图层重命名 + 上传状态气泡

## 简介

基于 Web 的 GIS 数据处理可视化工作台，内置三模型 AI 助手，通过自然语言交互即可搜索数据、提取建筑轮廓、处理 GIS 数据并加载到地图。支持 `/` 斜杠命令面板一键调用 GIS 工具，chip 标签指示当前启用的技能模块。

AI 内置隐身反爬抓取、内容清洗、B站搜索等工具，Token 消耗降低约 80%。

### AI 协作机制

| 模型 | 能力 |
|------|------|
| **DeepSeek V4 Flash+** | 默认模型，GLM + DeepSeek 协作，GLM 自动路由分析任务需求，按需加载技能文档，画图/空间分析时自动参考 |
| **GLM-4.7-Flash+**（免费） | 备选模型，完整 Function Calling，本地路由 + 技能文档 |

**三模型：** 默认使用 DeepSeek V4 Flash+（GLM 协作模式），可在聊天框右上角下拉切换。所有模型均支持 `/` 斜杠命令 chip 标签系统，chip 指定的技能与 GLM 路由结果合并去重，人机互补。

AI 回复支持 Markdown 渲染（外部链接自动新标签打开）、一键复制，加载状态带流光动画与计时器。所有系统提示统一显示在聊天框内。图层面板为浮动浮窗（地图右上角），支持折叠、来源标识、复选框显隐、行内下载、拖拽排序。

> ⚠️ **使用前必做：配置 API Key** — 本项目的 AI 功能依赖 DeepSeek 和 GLM 的 API 密钥，请在页面顶部 ⚙️ 齿轮按钮中配置，否则 AI 功能无法使用。（密钥会由浏览器自动保存）

## 快速开始

### 方式一：AI 辅助部署（推荐）

把下面的链接和指令发给 AI 助手（如 Claude）：

> **"https://github.com/Wukeeeeee/GIS-WORKTABLE.git 请帮我在本地部署好这个项目"**

AI 会自动读取项目结构和配置，逐步指导你完成：
1. 克隆仓库 → 2. 安装 Python 依赖 → 3. 安装 Playwright 浏览器 → 4. 配置 API Key → 5. 启动后端服务 → 6. 打开前端页面

全程无需手动查阅文档，AI 会解释每一步并帮你排查问题。

### 方式二：手动部署

```bash
# 1. 安装后端依赖
cd backend
pip install -r requirements.txt

# 2. 安装 Playwright 浏览器（用于 AOI 提取）
playwright install chromium

# 3. 启动服务
cd ..
python -m uvicorn backend.main:app --port 8000
```

> 后端建议不加 --reload，Playwright 在 Windows 热加载下存在兼容问题。

前端直接用浏览器打开 frontend/index.html。

### 配置 API Key

在页面顶部 ⚙️ 齿轮按钮中填入 DeepSeek 和 GLM 的 API 密钥即可，浏览器会自动保存。

## 核心功能

AI 对话 / 地图底图 / 图层面板 / 文件上传 / 图表生成 / 网页抓取与内容清洗 / 中国平台搜索 / AOI 建筑轮廓 / 行政边界 / GIS 代码执行 / 多步分析

## 技术栈

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/HTML5-E34F26?style=flat-square&logo=html5&logoColor=white" />
  <img src="https://img.shields.io/badge/CSS3-1572B6?style=flat-square&logo=css3&logoColor=white" />
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black" />
  <img src="https://img.shields.io/badge/Leaflet-199900?style=flat-square&logo=leaflet&logoColor=white" />
  <img src="https://img.shields.io/badge/DeepSeek-4F6BED?style=flat-square&logoColor=white" />
  <img src="https://img.shields.io/badge/GLM-2563EB?style=flat-square&logoColor=white" />
  <img src="https://img.shields.io/badge/GeoPandas-139C5A?style=flat-square&logoColor=white" />
  <img src="https://img.shields.io/badge/Shapely-333333?style=flat-square&logoColor=white" />
  <img src="https://img.shields.io/badge/Playwright-2EAD33?style=flat-square&logo=playwright&logoColor=white" />
</p>

| 类别 | 技术 | 链接 |
|------|------|------|
| 前端设计 | HTML + CSS（[Google Stitch](https://labs.google.com/stitch) · `DESIGN.md`） | — |
| 地图引擎 | Leaflet | — |
| 后端 | FastAPI | — |
| **AI 主力** | **DeepSeek V4 Flash** | [DeepSeek 开放平台](https://platform.deepseek.com/) |
| **AI 备选** | **GLM-4.7-Flash（免费）** | [智谱开放平台](https://open.bigmodel.cn/) |
| GIS | shapely + geopandas | — |
| 抓取 | Scrapling + markdownify | [Scrapling](https://github.com/D4Vinci/Scrapling) · [markdownify](https://github.com/matthewwithanm/python-markdownify) |
| 搜索 | Agent-Reach | [Agent-Reach](https://github.com/Panniantong/Agent-Reach) |

## 致谢

- [Scrapling](https://github.com/D4Vinci/Scrapling) - 隐身反爬抓取引擎
- [markdownify](https://github.com/matthewwithanm/python-markdownify) - HTML 转 Markdown
- [Agent-Reach](https://github.com/Panniantong/Agent-Reach) - 多平台搜索
- [Crawl4AI](https://github.com/unclecode/crawl4ai) - AI 爬取框架
- [Browser-Use](https://github.com/browser-use/browser-use) - 浏览器自动化

## 项目结构

```
frontend/             # 前端页面
  index.html          # 主页面（含设置弹窗三栏布局、模型选择器、图层检查器等）
  css/style.css       # 样式（Material Design 3 主题变量 + 暗黑模式完整覆盖）
  js/                 # JS 模块
    chat.js           # AI 对话（斜杠命令 / chip 标签 / Markdown 渲染 / 流式状态）
    map.js            # 地图（绘制工具 / 十字准星 position:fixed / 热力图 / 右键菜单）
    layers.js         # 图层面板（拖拽排序 / 检查器 / AI 分析按钮 / 显隐切换）
    task.js           # 任务管理系统（5 种状态 / localStorage 持久化 / 代码折叠）
    api.js            # API 通信层
    upload.js         # 文件上传
    app.js            # 应用初始化
backend/              # 后端服务
  main.py             # FastAPI 入口（LangGraph Agent 替代手写 while 循环）
  services/
    ai_service.py     # AI 对话 + SYSTEM_PROMPT + GLM 路由 + force_skills 合并
    tools.py          # LangChain @tool 装饰器定义的所有工具（搜索/抓取/AOI/Python执行等）
    graph.py          # LangGraph StateGraph（create_react_agent 替代手写 if/elif 循环路由）
    amap_service.py   # 高德地图 Web API（POI 搜索 / 坐标转换 GCJ-02↔WGS-84）
    datav_service.py  # DataV 行政边界获取（省/市/区三级，自动 WGS-84 转换）
    log_service.py    # 问答日志记录
    gaode_aoi_service.py  # 高德 AOI 建筑轮廓提取
    baidu_aoi_service.py  # 百度 AOI 建筑轮廓提取
  tests/
    test_geometry.py  # 27 个几何操作单元测试（buffer/intersection/centroid/area/make_valid/simplify）
    test_layer_inspect.py  # 图层检查器单元测试
skills/               # 按需加载的技能文档（Markdown），由 GLM 路由按需加载
  geometry.md         # 几何操作规则（CRS 处理、UTM 投影 buffer）
  aoi.md              # AOI 建筑轮廓提取流程
  datav.md            # 行政区划边界（DataV 三级）
  heatmap.md          # 热力图参数 + 城市→热力图工作流
  visualization.md    # matplotlib/pyecharts 代码示例
  analysis.md         # 空间分析指南（途经省份判定等）
  amap.md             # 高德 Web API 完整文档（POI/天气/地理编码 / 坐标转换）
  gdal.md             # GDAL 地理数据处理
  remote_sensing.md   # 遥感影像处理（NDVI/NDWI/分类）
prompt_deepseek.md    # DeepSeek 系统提示词文档
prompt_glm.md         # GLM 系统提示词文档
```

## 更新日志

- **2026-07-14**：可编辑属性表（图层检查器 `<input>` 单元格，保存/添加/删除行，空行验证警告）；筛选导出（字段+运算符+值过滤，`导出为新图层` 一键创建）；空值填充（表格顶部输入框，保存自动填充空白单元格）；图层重命名（双击图层名内联编辑，ESC 取消，Enter/blur 确认）；重名自动去重 (1)(2)；上传修复（按钮绑定改用 `getElementById`，状态改为居中对话气泡，含取消按钮/成功勾/失败叉，AbortController 取消中断）；`glm-4-flash` → `glm-4.7-flash` 模型名更新（4 处）；`execute_python` 添加 `PYTHONIOENCODING=utf-8` 修复中文乱码
- **2026-07-14**：后端 GLM 模型名 `glm-4-flash` → `glm-4.7-flash`，对齐 GLM-4.7-Flash 最新版本；GLM 统一使用 DeepSeek 完整 SYSTEM_PROMPT，彻底解决 GLM 地理幻觉问题（平壤→哈尔滨等坐标误判）；设置弹窗三栏布局宽度 580→720px/高度 420→520px 放大；暗黑模式 SVG Logo 修复（硬编码 #1A1A1A 改用 CSS 变量 `--ui-gray-900`）
- **2026-07-14**：架构重构——手写 while/if/elif 15+ 分支工具调用循环迁移为 **LangGraph StateGraph + create_react_agent**（`graph.py`），工具函数统一迁移至 `tools.py`（`@tool` 装饰器，19 个工具），ToolNode 自动路由替代手动 dispatch。`recursion_limit=50` 安全限制防止工具调用死循环
- **2026-07-14**：新增 `amap_service.py` — 高德地图 Web API 独立服务层（POI 关键字搜索/周边搜索，自动 GCJ-02→WGS-84 坐标转换，结果自动加载地图）；设置弹窗新增高德 API Key 配置卡片；`amap_poi_search` 独立工具
- **2026-07-13**：布局修复（body 8px 偏移 / 100vw 右侧溢出 / Leaflet 版权裁切）；连续绘制支持（画完自动继续）；图层面板新增"发送给AI分析"按钮（⭐），提取 GeoJSON 坐标发给 AI 分析位置信息；删除按钮重写（自定义 click-to-delete 替代不可用的 L.Edit.Delete）
- **2026-07-13**：代码质量工程化——`var`→`let`/`const` 统一（102 处）、CSS 变量迁移标注（159 处）、新增 27 个几何操作单元测试（`backend/tests/test_geometry.py`）、Python 清理冗余注释、README 修正
- **2026-07-13**：SYSTEM_PROMPT 精简 54%（10423→4826 字符），领域知识迁移到 skills/*.md 按需加载；Skill Chip 标签系统（`[ /buffer ✕ ]` 圆角标签嵌入输入框，支持多 chip 叠加、Backspace 删除）；force_skills 全模型支持（chip 技能 + GLM 路由合并去重）；skills/*.md 充实（geometry 坐标系规则、visualization 代码示例、analysis 途经省份判定）
- **2026-07-13**：新增 DeepSeek V4 Flash+ GLM 协作模式（GLM 预分析 + DeepSeek 执行，按需加载技能文档）；右键菜单新增协作模式选项 + 十字准星 HTML fixed 重构；热力图缩放优化（自动显隐 + 动态 radius）；内联技能文档系统（matplotlib/pyecharts/geopandas/shapely）；matplotlib 中文字体修复；hexbin 六边形分箱对比图支持；地图渲染隔离（contain: paint layout style）；DOM 引用缓存性能优化
- **2026-07-12**：GLM-4.7-Flash 启用完整 Function Calling（能力与 DeepSeek 对等）；移除 toast 通知系统，所有提示统一走聊天框；DataV 坐标转换修复（areas_v3 已直出 WGS-84，移除多余 GCJ-02 转换）；日志添加模型名标识；修复 DataV 城市级 adcode 查找（支持广州市/深圳市等）；Markdown 链接自动新标签打开；清理冗余 workspace 日志字段
- **2026-07-11**：浮动图层面板重构（移除底部面板），支持来源标识、复选框显隐、行内下载、拖拽排序、折叠按钮；GLM 切换按钮防重复；新增 Markdown 渲染、流光动画、复制按钮
- **2026-07-11**：接入 GLM-4.7-Flash 免费模型，双模型协作（GLM 规划 + DeepSeek 执行）；输入框布局优化
- **2026-07-11**：新增 pyecharts / matplotlib 绘图功能；图层列表展开折叠按钮；Toast 提示系统
- **2026-07-10**：新增翻牌计时器；Log 系统；更新时间戳显示；优化 AI 提示词
- **2026-07-10**：AOI 建筑轮廓抓取工具（高德 + 百度），选项框选择确认后加载到地图
- **2026-07-06**：Bing 搜索、OSM 行政边界提取、图层显示与保存
- **2026-07-06**：更多文件格式支持；AI 新增空间操作能力；导出功能
- **2026-07-04**：API 设置界面；HTML 绘制 Demo 功能
- **2026-07-03**：AI Function Calling 工具系统（时间感知、Python 执行、网页搜索）
- **2026-07-03**：新建会话、清除记忆按钮；SVG 图标重构
- **2026-07-02**：定位按钮 + 脉冲蓝点；上传文件自动加入图层列表、颜色切换、小眼睛显隐
- **2026-07-02**：Bing Maps 底图切换（街道图/无文字版/卫星图）；移除多余图源
- **2026-07-02**：FastAPI 后端搭建，AI 对话接入
- **2026-07-02**：项目初始化，GIS WorkTable 前端原型
