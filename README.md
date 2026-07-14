<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE -- 地理空间分析工作台
</p>

> 更新时间：2026-07-14

## 简介

基于 Web 的 GIS 数据处理可视化工作台，内置三模型 AI 助手，通过自然语言交互即可搜索数据、提取建筑轮廓、处理 GIS 数据并加载到地图。支持 `/` 斜杠命令面板一键调用 GIS 工具，chip 标签指示当前启用的技能模块。

AI 内置隐身反爬抓取、内容清洗、B站搜索等工具，Token 消耗降低约 80%。

### AI 协作机制

| 模型 | 能力 |
|------|------|
| **DeepSeek V4 Flash+** | 默认模型，GLM + DeepSeek 协作，GLM 自动路由分析任务需求，按需加载技能文档，画图/空间分析时自动参考 |
| **GLM-4.7-Flash+**（免费） | 备选模型，完整 Function Calling，本地路由 + 技能文档 |

**双模型：** 默认使用 DeepSeek V4 Flash+（GLM 协作模式），可在聊天框右上角下拉切换。所有模型均支持 `/` 斜杠命令 chip 标签系统，chip 指定的技能与 GLM 路由结果合并去重，人机互补。

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

**2026-07-14**
- 将属性表改为可编辑 input，支持保存添加行删除行
- 新增筛选栏支持字段匹配导出新图层
- 新增图层名双击内联编辑，重名自动去重
- 将上传状态改为居中对话气泡，支持取消导入
- 修复 execute_python 中文乱码
- 更新 GLM 模型名
- 将绘制 marker 自动转为 circleMarker，统一颜色系统
- 改用 setLayerColor 的 setStyle 直接改色
- 移除 header 版本信息
- 在设置弹窗新增关于面板
- 移除保存设置按钮
- 修复代码审查问题：phaseTimer 未清理、placeholder 竞争、marked 全局覆盖、conversation_history 截断、SHP 返回名带 .zip、内联 import 移到顶层、未使用 import 清理、模块加载超时检测、escapeHtml 统一到 GIS.utils、toQuadkey 边界检查、代理环境变量大小写兼容、高德 URL 编码、_add_pending_item 初始化
- 重构架构为 LangGraph create_react_agent
- 新增 amap_service
- 让 GLM 统一使用 DeepSeek SYSTEM_PROMPT 解决地理幻觉
- 放大设置弹窗布局
- 修复暗黑模式 SVG Logo

**2026-07-13**
- 修复 body 8px 偏移和 100vw 溢出和 Leaflet 版权裁切
- 新增连续绘制支持
- 在图层面板新增 AI 分析按钮
- 将 var 统一为 let/const
- 标注 CSS 变量迁移
- 新增 27 个几何操作单元测试
- 精简 SYSTEM_PROMPT 54%
- 将领域知识迁移到 skills 按需加载
- 新增 Skill Chip 标签系统
- 使 force_skills 支持全模型
- 新增 DeepSeek V4 Flash+ GLM 协作模式
- 在右键菜单新增协作模式选项
- 重构十字准星为 HTML fixed
- 优化热力图缩放
- 修复 matplotlib 中文字体
- 隔离地图渲染层

**2026-07-12**
- 让 GLM 启用完整 Function Calling
- 移除 toast 通知系统
- 修复 DataV 坐标转换
- 在日志添加模型名标识
- 让 Markdown 链接自动新标签打开

**2026-07-11**
- 重构浮动图层面板，支持来源标识显隐下载拖拽排序折叠
- 防止 GLM 切换重复
- 新增 Markdown 渲染流光动画
- 接入 GLM 免费模型
- 新增 pyecharts/matplotlib 绘图
- 新增 Toast 提示系统

**2026-07-10**
- 新增翻牌计时器日志系统和更新时间戳显示
- 新增 AOI 建筑轮廓抓取工具

**2026-07-06**
- 新增 Bing 搜索
- 新增 OSM 行政边界提取
- 支持更多文件格式
- 让 AI 新增空间操作能力

**2026-07-04**
- 新增 API 设置界面
- 新增 HTML 绘制 Demo

**2026-07-03**
- 新增 AI Function Calling 工具系统
- 新增新建会话清除记忆按钮
- 重构 SVG 图标

**2026-07-02**
- 新增定位按钮
- 支持上传文件自动加入图层列表
- 新增 Bing Maps 底图切换
- 搭建 FastAPI 后端
- 初始化项目
