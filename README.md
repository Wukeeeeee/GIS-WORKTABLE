<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE -- 地理空间分析工作台
</p>

> 更新时间：2026-07-12

> 🚧 **项目持续开发中，可能存在 Bug 或未完善的功能，如遇问题欢迎提交 Issue 反馈！**

## 简介

基于 Web 的 GIS 数据处理可视化工作台，内置双模型 AI 助手，通过自然语言交互即可搜索数据、提取建筑轮廓、处理 GIS 数据并加载到地图。

AI 内置隐身反爬抓取、内容清洗、B站搜索等工具，Token 消耗降低约 80%。

### AI 协作机制

| 模型 | 角色 | 能力 |
|------|------|------|
| **DeepSeek V4 Flash** | 执行者 | Function Calling，可搜索网页、执行 Python、生成图表、获取边界、操作地图 |
| **GLM-4.7-Flash**（免费） | 规划+执行 | 支持 Function Calling，可搜索网页、执行 Python、获取边界、操作地图，无需切换模型 |

**双模型：** 默认使用 DeepSeek V4 Flash，可在聊天框右上角下拉切换为 GLM-4.7-Flash

AI 回复支持 Markdown 渲染、一键复制，加载状态带流光动画与计时器。图层面板为浮动浮窗（地图右上角），支持折叠、来源标识、复选框显隐、行内下载、拖拽排序。

> ⚠️ **使用前必做：配置 API Key** — 本项目的 AI 功能依赖 DeepSeek 和 GLM 的 API 密钥，请在页面左下角 ⚙️ 齿轮按钮中配置，否则 AI 功能无法使用。（密钥会由浏览器自动保存）

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

在页面左下角 ⚙️ 齿轮按钮中填入 DeepSeek 和 GLM 的 API 密钥即可，浏览器会自动保存。

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
| **AI 执行** | **DeepSeek** | [DeepSeek 开放平台](https://platform.deepseek.com/) |
| **AI 规划** | **GLM-4.7-Flash（免费）** | [智谱开放平台](https://open.bigmodel.cn/) |
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
  js/              # JS 模块
backend/           # 后端服务
  main.py          # FastAPI 入口
  services/        # 服务模块
    ai_service.py  # AI 对话 + 工具系统
    datav_service.py
    log_service.py
    gaode_aoi_service.py
    baidu_aoi_service.py
cache/             # 缓存
logs/              # 日志
```

## 更新日志

- **2026-07-12**：集成 Scrapling（隐身反爬抓取）、markdownify（HTML 转 Markdown 清洗）、Agent-Reach/B站搜索（中国平台数据采集），网页抓取 Token 消耗降低约 80%；新增工具测试脚本；前端增加模型 Key 未配置警告提示；地图自动缩放至数据范围；错误提示改为聊天框系统消息
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
