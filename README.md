<p align="center">
  <img src="frontend/assets/logo-readme.svg" alt="GeoMind" width="320">
</p>

<p align="center">
  <b>地理空间分析工作台 · AI 驱动的 GIS 工具</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black" />
  <img src="https://img.shields.io/badge/Leaflet-199900?style=flat-square&logo=leaflet&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square&logo=langchain&logoColor=white" />
  <img src="https://img.shields.io/badge/License-AGPL%20v3-1a1a2e?style=flat-square" />
</p>

---

一个基于 Web 的 GIS 数据处理与可视化工作台，内置三模型 AI Agent，通过自然语言对话即可驱动地图操作、空间分析和数据加载。

## 截图

![界面截图](firstHtml.png)

## 快速开始

```bash
# 安装后端依赖
cd backend
pip install -r requirements.txt

# 启动服务
cd ..
python -m uvicorn backend.main:app --port 8000
```

打开浏览器访问 `http://localhost:8000`，或在开发时直接用浏览器打开 `frontend/index.html`（需后端运行中）。

## 功能

### AI Agent 系统
- 三模型支持：**GLM-4.7-Flash+**（免费默认）、**DeepSeek V4 Flash+**、**Agnes 2.0 Flash+**（免费 512K 上下文）
- LangGraph 驱动的 ReAct Agent，自动管理多轮工具调用
- 自校验 Verifier（Agent 2），自动验证结果质量，不通过则自动修正
- GLM 路由系统，自动加载技能文档辅助任务
- SSE 流式响应，前端实时展示工具调用进度
- 话题切换检测，自动清空无关历史

### 地图与空间数据
- 多格式文件上传：GeoJSON / SHP / GPKG / KML / CSV
- 浮动图层面板：显隐、排序、颜色、删除、重命名
- 属性检查器三标签页：基础信息 / 符号系统 / 属性表
- 符号系统：唯一值 / 分级色彩 / 分级符号 / 比例符号，色带选择，启用/禁用
- 属性表：查看、编辑、筛选、导出、字段计算器、地图定位
- 底图切换：Bing 卫星图 / 纯白底图
- SHP 导出，要素选择与高亮

### 数据获取
- 行政边界（DataV 省市区三级）
- 高德 POI 搜索、地理编码、天气
- 百度 AOI 建筑轮廓提取
- Bing 搜索、网页抓取（Scrapling 隐身引擎）
- B 站搜索
- OSM 道路网络提取（Overpass 多镜像自动切换）

### 空间分析
- 缓冲区、相交、合并、裁剪、坐标转换
- 热力图生成
- 面积精确测量（自动选 UTM 投影 + Albers 交叉验证）
- 统计图表（柱状图/饼图/直方图/散点图/折线图）
- 三层沙箱隔离的 Python 代码执行
- **网络分析面板**：最短路径（含途经点/方向箭头）、服务区（多级断值）、最近设施（图层+手动设施点混合），点击地图自动吸附路网，结果可导出为图层
- **AI 驱动网络分析**：用自然语言指挥 AI 完成「识别城市→下载路网→分析路径/服务区/最近设施→加载结果」全流程，Agent 自动调用 `amap_poi_search` 转坐标、`download_road_network` 从 OSM 下载路网、`network_analysis` 执行分析（国内用户若 OSM 连不通，AI 会给出 Geofabrik/BBBike 替代下载指引）

### UI
- 顶部菜单栏（文件/绘制/视图/工具/帮助）
- 操作手册弹窗（左侧目录 + 右侧内容）
- 斜杠命令面板（`/buffer` `/intersection` `/aoi` `/help` 等）
- 任务管理、问答日志、工程持久化

## AI Agent 架构

```
用户消息
    │
    ▼
┌──────────────────────────────────────┐
│ GLM 路由 (ai_service.py)            │
│ → 分析消息 → 加载对应技能文档        │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│ LangGraph ReAct Agent (graph.py)    │
│ → create_react_agent(llm, tools)     │
│ → 自动循环：LLM → 工具 → 结果 → ... │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│ 15+ @tool 工具集 (tools.py)         │
│ search_web / execute_python /        │
│ datav_boundary / amap_poi_search /   │
│ create_heatmap / field_calculate /   │
│ export_layer / layer_control / ...   │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│ 自校验 Verifier (graph.py)          │
│ → 验证结果是否满足用户请求          │
│ → 不通过则自动追加修正轮            │
└──────────────────────────────────────┘
    │
    ▼
AI 回复 + 数据推送到前端
```

每一个文件都有详细注释说明架构演进和设计决策。

## 项目结构

```
frontend/
├── index.html         # 主页面
├── css/style.css      # 样式
└── js/                # JS 模块
    ├── app.js         # 应用初始化
    ├── chat.js        # AI 对话
    ├── map.js         # 地图控制
    ├── layers.js      # 图层面板 + 属性检查器
    ├── settings.js    # 设置弹窗
    ├── task.js        # 任务管理
    ├── api.js         # API 通信
    ├── upload.js      # 文件上传
    ├── aoi.js         # AOI 交互
    ├── network.js     # 网络分析面板
    └── project.js     # 工程持久化

backend/
├── main.py            # FastAPI 入口
└── services/
    ├── ai_service.py  # AI 服务层（系统提示词、历史管理、路由）
    ├── graph.py       # LangGraph Agent（主循环 + 自校验）
    ├── tools.py       # @tool 工具集（15+ 个工具）
    ├── layer_service.py
    ├── amap_service.py
    ├── baidu_aoi_service.py
    ├── datav_service.py
    ├── geo_coords.py
    ├── log_service.py
    └── project_service.py
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 前端 | HTML + CSS + JavaScript |
| 地图 | Leaflet |
| 后端 | FastAPI + Python |
| AI 框架 | LangGraph (ReAct Agent) |
| 模型 | GLM-4.7-Flash+ / DeepSeek V4 Flash+ / Agnes 2.0 Flash+ |
| GIS | GeoPandas + Shapely + PyProj |
| 沙箱 | AST 静态校验 + 子进程 + 超时强杀（三层） |
| 抓取 | Scrapling + Playwright |



## 更新日志

### 2026-07-21
- Main 测试网络分析面板
- Fix AI 工具路由：`execute_python` docstring 改为"最后选择"、系统提示词新增工具优先级规则
- Fix `_push_layer` 推图层不生效：`get_pending_state()` 改为读取即消费 + 线程锁，修复校验器路径图层重复累积
- Fix SSE 端点冗余 `reset_state` 调用，`run_agent_stream` `msgs` 变量初始化
- Update 操作手册：新增空间分析 section（网络分析/AOI/行政边界/热力图）、AI 斜杠命令完整表格（18 条）、图层管理补充导出/字段计算/图表、顶部菜单更新
- Add 网络分析面板单元测试（26 项）
- Add 网络分析面板重构（三栏结构，与设置弹窗风格统一）
- Add 面板拖拽约束（左边界限定在聊天面板右侧，底部限 vh-10）
- Add 导入性能优化：json.loads/gpd.read_file 移至线程池，SHP/GPKG/KML 路径省掉 JSON 序列化往返
- Fix 选点卡死：snap 失败时重置 _inputMode 和光标
- Fix 后端 error 字段被忽略：路网为空时显示具体错误
- Fix 面板关闭后 _initialized 被重置导致每次打开全量重建 DOM
- Fix 导出空白：_exportResult 调用 addLayer 传参错误
- Fix 方向箭头 ▶ 残留：添加 _arrowMarker 变量跟踪并随结果清理

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
