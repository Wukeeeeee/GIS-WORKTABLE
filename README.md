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
- 斜杠命令面板（/buffer /intersection /aoi /help 等）
- 顶部菜单栏（文件/绘制/视图/工具/帮助），SVG+文字风格
- 快捷栏定制：通过菜单开关右侧工具栏按钮显隐
- 操作手册弹窗（左侧目录+右侧内容），支持 `/help` 打开
- 要素选择工具：点击地图要素弹出属性信息卡片
- 绘制工具互斥选中 + ✓ 图标高亮

## 技术栈

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/HTML5-E34F26?style=flat-square&logo=html5&logoColor=white" />
  <img src="https://img.shields.io/badge/CSS3-1572B6?style=flat-square&logo=css3&logoColor=white" />
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black" />
  <img src="https://img.shields.io/badge/Leaflet-199900?style=flat-square&logo=leaflet&logoColor=white" />
  <img src="https://img.shields.io/badge/DeepSeek-4F6BED?style=flat-square&logo=deepseek&logoColor=white" />
  <img src="https://img.shields.io/badge/GLM-2563EB?style=flat-square&logo=zhipu&logoColor=white" />
  <img src="https://img.shields.io/badge/GeoPandas-139C5A?style=flat-square&logo=geopandas&logoColor=white" />
  <img src="https://img.shields.io/badge/Shapely-333333?style=flat-square&logo=shapely&logoColor=white" />
  <img src="https://img.shields.io/badge/Playwright-2EAD33?style=flat-square&logo=playwright&logoColor=white" />
  <img src="https://img.shields.io/badge/License-AGPL%20v3-1a1a2e?style=flat-square" />
</p>

| 类别 | 技术 |
|------|------|
| 前端 | HTML + CSS + JavaScript |
| 地图 | Leaflet |
| 后端 | FastAPI + Python |
| AI | GLM-4.7-Flash+ / DeepSeek V4 Flash+ / Agnes 2.0 Flash+ |
| GIS | GeoPandas + Shapely + PyProj |
| 抓取 | Scrapling + markdownify |

### 使用的开源项目

| 项目 | 用途 | GitHub |
|------|------|--------|
| Firecrawl | 网页抓取 API（自托管） | [nicholasgriffintn/firecrawl](https://github.com/nicholasgriffintn/firecrawl) |
| browser_use | 浏览器自动化 AI 代理 | [nicholasgriffintn/browser-use](https://github.com/nicholasgriffintn/browser-use) |
| Scrapling | 隐身网页抓取（TLS 指纹混淆） | [niespodd/scrapling](https://github.com/niespodd/scrapling) |

### 开放平台

| 平台 | 用途 | 链接 |
|------|------|------|
| 高德开放平台 | POI 搜索、地理编码、行政区域查询 | [lbs.amap.com](https://lbs.amap.com/) |
| 百度地图开放平台 | AOI 建筑轮廓提取 | [lbsyun.baidu.com](https://lbsyun.baidu.com/) |
| DataV 地理工具 | 省市区行政边界 GeoJSON | [datav.aliyun.com](https://datav.aliyun.com/portal/school/atlas/area_selector) |
| Bing Maps 中国区 | 地图底图（卫星图） | [bingmapsportal.com](https://www.bingmapsportal.com/) |
| DeepSeek 开放平台 | AI 推理模型 | [platform.deepseek.com](https://platform.deepseek.com/) |
| 智谱开放平台 | GLM AI 模型（免费） | [open.bigmodel.cn](https://open.bigmodel.cn/) |
| Agnes API | Agnes 2.0 Flash+ AI 模型 | [apihub.agnes-ai.com](https://apihub.agnes-ai.com/) |
| Firecrawl | 网页抓取 API | [firecrawl.dev](https://www.firecrawl.dev/) |

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

## 更新日志

### 2026-07-18
- Add settings.js 提取设置弹窗、密钥管理、模型选择、主题/字号
- Add `chat.clearSession()` 统一清会话，inline script 缩减 630→64 行
- Add 要素选择与高亮系统（popup + _featureMap + 属性表定位按钮）
- Add 顶部菜单栏（文件/绘制/视图/工具/帮助）+ 快捷栏定制
- Add 操作手册弹窗（左侧目录 + 右侧内容）/ `/help` 斜杠命令
- Add 绘制工具互斥选中 ✓ 标记，坐标信息持久勾选开关
- Add SHP 导出 — 后端 `/api/layer/export-shp` + 前端下载弹窗 + AI 工具 `export_layer`
- Add 图层符号化 — 属性检查器三标签页（基础信息/符号系统/属性表）
- Add 符号化面板仿 ArcMap 交互：启用/禁用、4种渲染方式、色带选择、类别预览
- Add 符号化按几何类型自动适配（点实心/线有宽度/面半透明）
- Add 符号化启用时 color dot 锁定（图层面板颜色调整失效）
- Add 统计图表 — AI 工具 `create_chart`（bar/pie/histogram/scatter/line）
- Add 底图切换（视图菜单 → 卫星/纯白两档），localStorage 持久化
- Add 实心点渲染（weight=0, fillOpacity=1）
- Add 纯白底图层（data URI 单像素白色 TileLayer）
- Add 代码审查 - 发现 4 个 bug
- Remove 放大/缩小/定位按钮、底图快捷键项
- Remove 旧版 _showSymbologyPanel 弹窗、_updateSymbologyPreview
- Fix style.css 各组件偏移适配菜单栏 30px
- Fix 符号化启用/禁用时 _symbologyConfig 未初始化/已删除导致 TypeError
- Fix CSS info-panel/symb-panel 新样式，替换旧 symbology-inline


### 2026-07-16
- Add SYSTEM_PROMPT 精简：DeepSeek 版 200→113 行 (-44%)，GLM 版 68→64 行
- Add Skills 文档精简：11 个文件 688→362 行 (-47%)，安全代码模板全部保留
- Add 新建会话按钮改进：先中止 AI 请求再清 UI
- Add 历史会话面板全部删除按钮（垃圾桶 SVG）
- Add 浏览器自动填充密钥检测（Edge）
- Add AI 流式超时可配置（sessionStorage gis_timeout）
- Remove 冗余：工具一览、技能文档列表、话题切换/基本原则/身份与记忆
- Remove 高程查询工具、百度 AOI 服务、高德高程查询服务
- Fix 历史面板右括号缺失导致所有按钮无响应（SyntaxError）
- Fix AOI 候选列表不显示：SSE 流式 pending_suggestions 格式修复
- Fix 百度 AOI 服务文件被误删，恢复 baidu_aoi_service.py
- Fix 点击"+"时 AI 仍在后台运行导致图层删不掉
- Fix 工程加载时 AI 消息不显示（_hideHistory 顺序问题）
- Fix 默认超时 120s → 600s
- Fix AI 服务清理引用残留
- Fix prompt_deepseek.md & prompt_glm.md 同步更新

### 2026-07-15
- Add Agnes 2.0 Flash+ 模型
- Add 道路网络提取工具（OSMnx + Overpass）
- Remove 独立高德/百度 AOI 路由（合并为统一工具）
- Fix Agnes 路由统一走 GLM

### 2026-07-14
- Add 图层属性表编辑与筛选导出
- Add 自校验 Agent 架构
- Add 高德 POI 搜索
- Add 上传取消（AbortController）与状态气泡
- Add AGPL v3 许可证
- Fix execute_python 子进程中文乱码
- Fix 代理环境变量大小写兼容
- Fix Gaode URL 编码

### 2026-07-13
- Add 图层检查器（GeoJSON 分析面板）
- Add 任务管理系统（localStorage）
- Add 斜杠命令面板（/buffer /intersection /aoi 等）
- Add 技能文档系统（geometry/aoi/datav/heatmap 等 6 个）
- Add 连续绘制模式
- Add 图层 AI 分析入口
- Add 27 个几何单元测试
- Add GLM 协作模式（免费规划 + DS 执行）
- Add 十字准星 CSS fixed 定位
- Add 设置弹窗三栏重构
- Add 全局字号缩放
- Fix 十字准星偏移
- Fix 地图顶部白框与右侧空白溢出
- Fix 右键发送只加一个点

### 2026-07-12
- Add 网页抓取（Scrapling）
- Add 平台搜索（B站）
- Add 模型 Key 未配置警告
- Add 地图自动缩放至数据范围
- Remove Toast 通知
- Fix JS 错误改为聊天框系统消息

### 2026-07-11
- Add GLM-4.7-Flash+ 免费模型
- Add Markdown 渲染与复制按钮
- Add 流光动画
- Add GLM 时间感知
- Add Matplotlib/PyEcharts 绘图
- Add 浮动图层面板
- Remove 旧底部面板

### 2026-07-10
- Add AOI 边界抓取工具
- Add 翻牌计时器
- Add 问答日志系统
- Add AI 回复时间戳
- Remove Bing 暗色图层
- Fix 底图统一为 Bing 卫星图（WGS84）

### 2026-07-06
- Add Bing 搜索工具
- Add OSM 行政边界提取
- Add 图层导出功能
- Add AI 空间操作能力
- Add 多文件格式支持（SHP/GPKG/KML）

### 2026-07-04
- Add API 密钥设置界面
- Add 绘制 HTML Demo 功能

### 2026-07-03
- Add AI Function Calling 工具系统
- Add 清除记忆按钮
- Add 新会话按钮（SVG 加号）
- Add 时间感知功能
- Fix 事件重复绑定
- Fix Live Server 刷新冲突

### 2026-07-02
- Add 前端原型 + FastAPI 后端
- Add AI 对话接入
- Add Bing Maps 底图切换
- Add 定位按钮与脉冲蓝点
- Add 文件上传与图层列表（显隐/颜色/删除）

## 许可证

AGPL v3 — 详见 [LICENSE](LICENSE)。
