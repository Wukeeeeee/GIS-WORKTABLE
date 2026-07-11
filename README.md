<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE -- 地理空间分析工作台
</p>

> 更新时间：2026-07-12

## 简介

基于 Web 的 GIS 数据处理可视化工作台，内置双模型 AI 助手，通过自然语言交互即可搜索数据、提取建筑轮廓、处理 GIS 数据并加载到地图。

AI 内置隐身反爬抓取、内容清洗、B站搜索等工具，Token 消耗降低约 80%。

### AI 协作机制

| 模型 | 角色 | 能力 |
|------|------|------|
| **DeepSeek V4 Flash** | 执行者 | Function Calling，可搜索网页、执行 Python、生成图表、获取边界、操作地图 |
| **GLM-4.7-Flash**（免费） | 规划者 | 纯文本问答，设计 GIS 工作流，完成后提示切换到 DeepSeek 执行 |

**工作流：** GLM 规划步骤 -> 一键切换到 DeepSeek 执行

AI 回复支持 Markdown 渲染、一键复制，加载状态带流光动画与计时器。图层面板为浮动浮窗（地图右上角），支持折叠、来源标识、复选框显隐、行内下载、拖拽排序。

## 快速开始

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

前端直接用浏览器打开 frontend/index.html。API Key 通过页面左下角齿轮按钮配置（DeepSeek + GLM），或写入 apikey.txt / glm_apikey.txt。

## 核心功能

AI 对话 / 地图底图 / 图层面板 / 文件上传 / 图表生成 / 网页抓取与内容清洗 / 中国平台搜索 / AOI 建筑轮廓 / 行政边界 / GIS 代码执行 / 多步分析

## 技术栈

前端：HTML+CSS+Leaflet  |  后端：FastAPI  |  AI：DeepSeek+GLM
GIS：shapely+geopandas  |  抓取：[Scrapling](https://github.com/D4Vinci/Scrapling)+[markdownify](https://github.com/matthewwithanm/python-markdownify)  |  搜索：[Agent-Reach](https://github.com/Panniantong/Agent-Reach)

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

- **2026-07-12**：集成 Scrapling（隐身反爬抓取）、markdownify（HTML 转 Markdown 清洗）、Agent-Reach/B站搜索（中国平台数据采集），网页抓取 Token 消耗降低约 80%
- **2026-07-11**：图层面板改为浮动浮窗，支持来源标识、复选框显隐、行内下载；GLM 切换按钮防重复；新增 Markdown 渲染、复制按钮、流光动画
