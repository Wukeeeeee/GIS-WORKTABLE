<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GIS WorkTable" width="320">
</p>

<p align="center">
  GIS WORKTABLE -- 地理空间分析工作台
</p>

> 更新时间：2026-07-11

## 简介

基于 Web 的 GIS 数据处理可视化工作台，内置双模型 AI 助手，通过自然语言交互即可搜索数据、提取建筑轮廓、处理 GIS 数据并加载到地图。

### 🤖 双模型协作机制

| 模型 | 角色 | 能力 |
|------|------|------|
| **DeepSeek V4 Flash** | 🛠️ 执行者 | 支持 Function Calling，可搜索网页、执行 Python 代码、生成图表、获取边界、操作地图 |
| **GLM-4.7-Flash**（免费） | 📋 规划者 | 纯文本问答，设计 GIS 工作流，完成后自动提示切换到 DeepSeek 执行 |

**工作流：** 使用 GLM 规划分析步骤 → 点击"切换到 DeepSeek 执行"按钮 → DeepSeek 自动按规划执行全部操作。

AI 回复支持 **Markdown 渲染**（标题、代码块、表格等）、**一键复制**，加载状态带模型名显示、**流光扫描动画**与**翻牌计时器**。

## 快速开始

### 启动后端

```bash
# 1. 安装依赖
cd backend
pip install -r requirements.txt

# 2. 安装 Playwright 浏览器（用于 AOI 提取）
playwright install chromium

# 3. 启动服务
cd ..
python -m uvicorn backend.main:app --port 8000
```

> 后端建议不加 --reload，Playwright 在 Windows 热加载下存在兼容问题。

### 前端

直接用浏览器打开 frontend/index.html（或使用 Live Server）。

### 配置 API Key

打开前端页面，点击左下角齿轮按钮，在设置弹窗中配置：

- **DeepSeek V4 Flash**：输入 API Key，点击保存
- **GLM-4.7-Flash（免费）**：输入智谱 API Key，点击保存

或者在项目根目录创建密钥文件：

```bash
# DeepSeek
echo "your-deepseek-api-key" > apikey.txt
# GLM
echo "your-glm-api-key" > glm_apikey.txt
```

## 核心功能

### 🤖 AI 对话
- 双模型协作：GLM 免费规划 → 一键切换到 **DeepSeek V4 Flash** 自动执行
- Markdown 渲染：AI 回复支持标题、列表、代码块、表格，阅读体验更佳
- 一键复制：AI 回复右下角复制按钮（常驻半透明，hover 强化），点击复制纯文本
- 加载动效：思考气泡显示模型名 + **流光扫描动画** + 翻牌计时器（独立一行）
- 模型切换：底部栏点击模型名称弹出选择器，状态圆点显示连接状态（绿色=可用/红色=未通过）
- 地图：Leaflet + Bing 卫星底图（WGS-84），坐标显示、定位、缩放
- 图层管理：显隐控制、颜色自定义、拖拽排序、删除
- 文件上传：支持 GeoJSON / Shapefile / GPKG / KML / CSV
- 图表生成：支持 matplotlib / seaborn 统计图和 pyecharts 省级交互地图
- AOI 建筑轮廓：百度 + 高德双源查询，自动转 WGS-84
- 行政边界：DataV 数据源，省/市/区三级
- GIS 代码执行：AI 自动写 Python 代码（shapely/geopandas），结果直接上地图
- 多步分析：支持分步保存中间结果到工作区

## 用 AI 部署

复制以下提示词给 AI 助手（如 Claude、ChatGPT）：

```
帮我从 https://github.com/Wukeeeeee/GIS-WORKTABLE.git 部署 GIS WorkTable，配置好所有依赖并启动。
```

## 技术栈

- 前端：原生 HTML + CSS
- 地图：Leaflet 1.9.4 + Bing 卫星底图
- Markdown 渲染：marked.js
- 后端：FastAPI（Python）
- AI：DeepSeek V4 Flash API（Function Calling，执行）/ GLM-4.7-Flash API（纯文本，规划）
- GIS 处理：shapely + geopandas
- 图表：matplotlib + seaborn + pyecharts
- 数据源：阿里云 DataV / 百度地图 / 高德地图

## 项目结构

```
frontend/          # 前端页面
  index.html       # 主页面
  css/style.css    # 样式
  js/              # JS 模块
backend/           # 后端服务
  main.py          # FastAPI 入口
  services/        # 服务模块
    ai_service.py        # AI 对话 + 工具系统
    datav_service.py     # DataV 行政区划
    log_service.py       # 双轨日志
    gaode_aoi_service.py # 高德 AOI
    baidu_aoi_service.py # 百度 AOI
cache/             # 缓存
logs/              # 日志
```
