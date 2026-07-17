# GIS WorkTable — 开发记忆

> 简化版，记录关键改动和设计决策。

## 当前状态

- **阶段**: BUILD（plan → build → test → land）
- **最新**: 工作流系统搭建（WORKFLOW + .opencode 配置）
- **CURRENT 文件**: 项目根 `CURRENT`

---

### 2026-07-18
- Add settings.js 提取设置弹窗、密钥管理、模型选择、主题/字号
- Add `chat.clearSession()` 统一清会话，inline script 缩减 630→64 行
- Add 要素选择与高亮系统（popup + _featureMap + 属性表定位按钮）
- Add 顶部菜单栏（文件/绘制/视图/工具/帮助）+ 快捷栏定制
- Add 操作手册弹窗（左侧目录 + 右侧内容）/ `/help` 斜杠命令
- Add 绘制工具互斥选中 ✓ 标记，坐标信息持久勾选开关
- Remove 放大/缩小/定位按钮、底图切换、快捷键项
- Fix style.css 各组件偏移适配菜单栏 30px

### 2026-07-17
- Add `frontend/js/settings.js`（640 行）— 从 index.html inline script 提取设置弹窗、密钥管理、模型选择器、主题/字号、自动检测功能
- Add `chat.clearSession()` 方法 — 统一清会话流程，消除 inline script 中的重复 UI 重置逻辑
- Reduce `frontend/index.html` inline script 630→64 行（-90%）
- Fix `app.js` — 移除冗余 settingsBtn handler，集成 `GIS.settings.init()`
- Add 要素选择与定位系统 — map.js 加 onEachFeature 要素点击高亮+popup、_featureMap 映射、highlightLayerFeature/clearHighlight 公开方法；layers.js 属性表每行加 ◎ 定位按钮，点击后地图 flyTo 并高亮，属性表行橙色高亮；style.css feat-popup/attr-locate-btn/feat-row-active 样式加暗色适配

### 2026-07-16（续）
- Add WORKFLOW.md — build/fix/refactor/optimize 流程定义，含步骤表
- Add .opencode/skills/gis-worktable/SKILL.md — AI 工作流规则
- Add .opencode/opencode.json — 注册 instructions（自动读 CURRENT/WORKFLOW/memory）
- Fix CURRENT 增强 — 加 workflow/step/next 字段追踪
- 39 个测试通过

### 2026-07-16
- Add SYSTEM_PROMPT 精简：DeepSeek 版 200→113 行 (-44%)，GLM 版 68→64 行
- Add Skills 精简：11 个文件 688→362 行 (-47%)，安全代码模板全部保留
- Add 新建会话改进（先中止 AI 再清 UI）、历史面板全删按钮
- Add 密钥浏览器自动填充检测、AI 超时可配置
- Remove 冗余：工具一览、技能文档列表、话题切换/基本原则/身份与记忆
- Remove 高程查询工具及服务
- Fix 历史面板右括号缺失、AOI 候选列表不显示、删不掉图层、工程 AI 消息不显示
- Fix prompt_deepseek.md & prompt_glm.md 同步更新

### 2026-07-15
- Add Agnes 2.0 Flash+ 第三模型（免费）
- Add 路网提取工具（OSMnx + Overpass）
- Fix Agnes 统一 GLM 路由（省跨洋往返）
- 默认模型从 deepseek-routed 改为 glm-routed

### 2026-07-14
- Add 属性表编辑/筛选/导出、字段计算器
- Add 上传取消（AbortController）与状态气泡
- Add AGPL v3 许可、自校验 Agent、高德 POI 搜索
- Consolidate: 25 工具→18（AOI合并、layer_control统一）
- Fix 中文乱码、代理大小写兼容、URL编码

### 2026-07-13
- Add 图层检查器、任务管理系统、斜杠命令面板（13个）
- Add 技能文档系统（11个*.md）、连续绘制、图层AI分析
- Add 27个几何测试、十字准星CSS fixed、GLM协作模式
- Fix 布局溢出、十字准星偏移、右键只加一点

### 2026-07-12
- Add 网页抓取（Scrapling）、平台搜索（B站）、Key未配置警告

### 2026-07-11
- Add GLM-4.7-Flash+ 免费模型、Markdown渲染、浮动面板

### 2026-07-10
- Add AOI边界抓取、翻牌计时器、问答日志系统

### 2026-07-06
- Add Bing搜索、OSM边界提取、多格式上传（SHP/GPKG/KML）

### 2026-07-04
- Add API密钥设置界面、绘制HTML Demo

### 2026-07-03
- Add AI Function Calling 工具系统、清除记忆、新会话按钮

### 2026-07-02
- 项目初始化：FastAPI + Leaflet 原型、AI对话接入、底图切换、文件上传