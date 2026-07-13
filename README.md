<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE -- 地理空间分析工作台
</p>

> 更新时间：2026-07-13
>
> > ✅ 几何操作自动化测试已覆盖 27 个用例（buffer/intersection/centroid/area/make_valid/simplify），改完代码跑 `python -m pytest backend/tests/` 验证

## 简介

基于 Web 的 GIS 数据处理可视化工作台，内置三模型 AI 助手，通过自然语言交互即可搜索数据、提取建筑轮廓、处理 GIS 数据并加载到地图。支持 `/` 斜杠命令面板一键调用 GIS 工具，chip 标签指示当前启用的技能模块。

AI 内置隐身反爬抓取、内容清洗、B站搜索等工具，Token 消耗降低约 80%。

### AI 协作机制

| 模型 | 能力 |
|------|------|
| **DeepSeek V4 Flash+** | 默认模型，GLM + DeepSeek 协作，GLM 自动路由分析任务需求，按需加载技能文档，画图/空间分析时自动参考 |
| **DeepSeek V4 Flash** | 标准模式，独立 Function Calling，搜索网页、执行 Python、操作地图 |
| **GLM-4.7-Flash**（免费） | 备选模型，完整 Function Calling，能力对等 |

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
frontend/          # 前端页面
  index.html       # 主页面
  css/             # 样式
  js/              # JS 模块（含斜杠命令 chip 标签系统）
backend/           # 后端服务
  main.py          # FastAPI 入口
  services/        # 服务模块
    ai_service.py  # AI 对话 + GLM 路由 + force_skills 合并
    datav_service.py
    log_service.py
    gaode_aoi_service.py
    baidu_aoi_service.py
skills/            # 按需加载的技能文档（Markdown）
  geometry.md      # 几何操作规则
  aoi.md           # AOI 建筑轮廓提取
  datav.md         # 行政区划边界
  heatmap.md       # 热力图参数
  visualization.md # 数据可视化代码示例
  analysis.md      # 空间分析指南
cache/             # 缓存
logs/              # 日志
```

## 更新日志

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
