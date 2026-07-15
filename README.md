<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE -- 地理空间分析工作台
</p>

## 简介

基于 Web 的 GIS 数据处理可视化工作台，内置三模型 AI 助手（GLM/DeepSeek/Agnes），通过自然语言交互即可搜索数据、处理 GIS 数据并加载到地图。

AI 内置网页抓取、内容清洗、搜索等工具。

## 模型

| 模型 | 说明 |
|------|------|
| GLM-4.7-Flash+（默认） | 免费，完整 Function Calling |
| DeepSeek V4 Flash+ | 需 API Key |
| Agnes 2.0 Flash+ | 免费，512K 上下文 |

所有 AI 回复支持 Markdown 渲染，一键复制，加载状态带计时器。

> 使用前需配置 API Key — 点击页面顶部齿轮按钮设置。GLM 和 Agnes 目前免费。

## 快速开始

```bash
# 安装后端依赖
cd backend
pip install -r requirements.txt

# 启动服务
cd ..
python -m uvicorn backend.main:app --port 8000
```

前端直接用浏览器打开 `frontend/index.html`。

## 功能

- AI 对话（自然语言驱动 GIS 操作）
- 地图底图（Bing 卫星）+ 绘制工具
- 浮动图层面板（显隐/排序/颜色/删除）
- 文件上传（GeoJSON/SHP/GPKG/KML/CSV）
- 行政边界获取（DataV 省市区三级）
- 热力图生成
- 网页抓取与内容清洗（Scrapling）
- 中国平台搜索（B站）
- 右键发送位置给 AI
- 斜杠命令面板（/buffer /intersection /aoi 等）

## 技术栈

| 类别 | 技术 |
|------|------|
| 前端 | HTML + CSS + JavaScript |
| 地图 | Leaflet |
| 后端 | FastAPI + Python |
| AI | GLM-4.7-Flash+ / DeepSeek V4 Flash+ / Agnes 2.0 Flash+ |
| GIS | GeoPandas + Shapely + PyProj |
| 抓取 | Scrapling + markdownify |

## 项目结构

```
frontend/
  index.html      # 主页面
  css/style.css   # 样式
  js/             # JS 模块
    chat.js       # AI 对话
    map.js        # 地图
    layers.js     # 图层面板
    task.js       # 任务管理
    api.js        # API 通信
    upload.js     # 文件上传
    app.js        # 应用初始化
backend/
  main.py         # FastAPI 入口
  services/
    ai_service.py     # AI 对话 + 系统提示词
    tools.py          # @tool 工具集
    graph.py          # LangGraph Agent
    geo_coords.py     # 坐标转换
    amap_service.py   # 高德 Web API
    datav_service.py  # DataV 行政边界
    log_service.py    # 问答日志
skills/               # 技能文档
  geometry.md / aoi.md / datav.md / heatmap.md
  visualization.md / analysis.md / amap.md / gdal.md / remote_sensing.md
```

## 许可证

AGPL v3 — 详见 [LICENSE](LICENSE)。
