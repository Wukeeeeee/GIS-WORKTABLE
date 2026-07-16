# GIS WorkTable — 开发记忆

> 记录每次开发会话的关键决策、改动和待办事项。

## 当前状态（AI 每次启动时读取）

- **阶段**: `WAITING`（下一个: `plan` → `build` → `test` → `land`）
- **功能/主题**: （空）
- **最后改动**: 2026-07-15 — Agnes 接入 + GLM 路由统一 + 默认模型改 GLM
- **待定**: （空 — 等开新 cycle）
- **CURRENT 文件**: 见项目根 `CURRENT`（不提交 git）

---

## 2026-07-15

- 新增 Agnes 2.0 Flash+ 作为第三模型提供商（`apihub.agnes-ai.com/v1`，免费）
- 移除 Agnes 自路由（`_agnes_route_skills()`），统一用 GLM 路由（减少跨洋往返）
- 为所有 Agnes OpenAI 客户端加 timeout（graph.py 60s / routing 15s / client 30s）
- 删除废弃的 gaode AOI 路由（`main.py` 中 model + endpoint + import 全清理）
- 前端模型选择器：新增 Agnes 选项，加「免费」标签，描述为「GLM 路由 + AGNES」
- 前端显示名统一为 Agnes 2.0 Flash+（含 + 后缀与 DS/GLM 对齐）
- 处理中加载消息适配 Agnes 模型名（路由分析中 / 执行中）
- 默认模型从 deepseek-routed 改为 glm-routed
- model-picker 各选项初始值和 JS 回退默认值统一为 glm-routed

---

## 2026-07-14（续）

- 重构 AOI 提取工具，删除废弃的 baidu_aoi_search 和 gaode_aoi_search，统一为 unified_aoi_search 和 unified_aoi_extract
- 五个图层控制工具合并为 layer_control，按 action 参数区分操作类型
- 工具总数从 25 个降到 18 个，功能不变，减少 AI 选择困惑
- 抽出文件重命名和 chart 清理等辅助函数，简化 execute_python
- 扩展 skills/arcpy.md 编写指南，增加 GeoPandas/Shapely 写 ArcPy 风格代码的完整映射表和工作流模板
- 更新 SYSTEM_PROMPT 引用 arcpy.md，对齐新工具结构
- 更新 skills/aoi.md、prompt_deepseek.md、prompt_glm.md 保持一致

---

## 2026-07-14

- 属性表改为可编辑 input，支持保存、添加行、删除行、空值填充、空行警告
- 筛选栏支持字段+运算符+值匹配，高亮匹配行，导出筛选结果为新图层
- 图层名双击内联编辑，Enter/blur 确认，ESC 取消，重名自动追加 (1)(2)
- 上传按钮绑定改用 getElementById 修复
- 上传状态改为居中对话气泡，支持取消导入（AbortController）、成功/失败图标
- upload() 新增 signal 参数支持中断
- execute_python 子进程添加 PYTHONIOENCODING=utf-8 修复中文乱码
- GLM 模型名 glm-4-flash 更新为 glm-4.7-flash
- 地图删除模式改用 e.layer 修复点击无效
- map.removeLayer 同时清理 drawnItems 解决 marker 残留
- 绘制 marker 自动转为 circleMarker 统一颜色系统
- setLayerColor 改用 setStyle 直接修改 Leaflet 图层，支持所有类型改色
- 颜色选择器改用 data-color 属性避免 RGB/Hex 转换问题
- 移除 header 版本信息 badge 和设置弹窗版本信息面板
- 设置弹窗新增关于面板，含 SVG Logo、项目介绍、GitHub 链接
- 移除设置弹窗保存设置按钮
- 代码审查修复：phaseTimer 清理、placeholder 竞争、marked 全局覆盖、conversation_history 截断、SHP 返回名去 .zip、escapeHtml 统一、main.py 内联 import 上提、graph.py 未使用 import 清理、app.js 超时检测、toQuadkey 边界检查、代理环境变量大小写兼容、Gaode URL 编码、_add_pending_item 初始化
- ArcPy 整合：创建 `backend/services/arcpy/` 包结构（analysis/management/conversion/da/sa/mp/stats 等 17 个模块），后取消手动实现，改为仅保留 `skills/arcpy.md` 作为代码编写指南。不注册冗余 LangChain 工具，AI 通过 `execute_python` + GeoPandas/Shapely 自行写 arcpy 风格代码。

---

## 2026-07-13（续11）：图层检查器 + 任务管理系统 + 右键十字准星优化 + /amap 命令

### 改动清单

#### 前端 — layers.js
- **图层检查器**：新增 ⓘ 检查按钮，`_fastInspect()` 快速统计 GeoJSON 要素数/字段/坐标范围，`showLayerInspector()` 弹窗展示图层详情，`closeInspector()` 关闭。

#### 前端 — map.js
- **右键十字准星优化**：点击右键菜单发送后十字准星保留在地图上不消失，`position:fixed` 直接固定在视口坐标，缩放/拖拽不偏移。

#### 前端 — task.js
- **任务管理系统**：AI 分析任务的 CRUD，5 种状态（pending/planning/executing/success/failed），localStorage 持久化（key: `gis_task_history`，最大 50 条），任务卡片 UI 渲染与折叠代码块。

#### 前端 — chat.js
- **新增 `/amap` 命令**：在斜杠命令面板中新增「高德POI搜索」，带地图 pin SVG 图标，映射到 `amap` 技能标签，发送气泡底部保留 `/amap` chip。

#### 技能文档
- **skills/amap.md**：高德地图 Web API 完整文档（POI 搜索/天气/地理编码/坐标转换 GCJ-02→WGS-84）。
- **skills/heatmap.md**：补充从城市名生成热力图的工作流（datav_boundary → search_web → execute_python 采样 → create_heatmap）。

---

## 2026-07-13（续10）：接入高德地图 Web API

### 改动清单

#### 前端 — index.html
- **设置弹窗新增高德 API Key 输入**：在 API 密钥面板 GLM 下方新增"高德地图 Web API"配置卡片（`amapApiKeyInput`），含密钥输入框、显隐切换、保存按钮、状态 badge。

#### 前端 — js/api.js
- **新增 getAmapKey/setAmapKey**：用 `gis_amap_api_key` localStorage key 存储高德密钥。
- **chat() 自动附带 amap_key**：发送聊天请求时，自动将高德密钥字段 `amap_key` 传给后端。

#### 后端 — main.py
- **ChatRequest 新增 amap_key 字段**：`Optional[str]`，接收前端传来的高德密钥。

#### 后端 — services/ai_service.py
- **`_current_amap_key` 全局变量**：在 chat_with_ai 中接收并存储高德密钥。
- **execute_python 注入 AMAP_KEY 环境变量**：子进程通过 `os.environ.get('AMAP_KEY', '')` 获取高德密钥，AI 编写的 Python 代码可直接调用高德 Web API。
- **SYSTEM_PROMPT 新增高德章节**：说明 AMAP_KEY 获取方式、GCJ-02→WGS-84 转换约束、offset 每页 25 条/最多 200 条、API 端点示例。
- **SYSTEM_PROMPT GLM 版同样更新**。
- **GLM 路由新增 amap 标签**。
- **execute_python 可用库添加 requests**。

#### 技能文件
- **skills/amap.md**：完整高德 Web API 文档，包含：
  - GCJ-02→WGS-84 转换代码
  - 关键字/周边/多边形搜索 POI 参数说明
  - 天气查询（实况+预报）
  - 地理/逆地理编码
  - 行政区域查询
  - POI 分类编码表
  - 使用工作流（调用→转坐标→加载地图）

### 额度参考
| 服务 | 月配额 |
|------|--------|
| 搜索 POI（关键字/周边/多边形/ID） | 5000 次 |
| 天气查询 | 5000 次 |
| 地理/逆地理编码 | 大量 |
| 行政区域查询 | 大量 |

---

## 2026-07-13（续9）：skill chip 在已发送消息中保留

### 改动清单

#### 前端 — chat.js
- **send() 捕获 chips 快照**：发送前将 `_skillChips.slice()` 存入 `chipsSnapshot`，传给 `addMessage` 的 options.chips。之后芯片在发送框中清除（API 返回后），但已发送气泡中仍显示。
- **addMessage() 渲染芯片**：用户消息气泡底部新增 chip 行，显示 `/buffer` 等黑色圆角标签，与输入框中的 chip 风格一致。

---

## 2026-07-13（续8）：十字准星发送后保留 + heatmap 用 DataV 非百度爬取

### 改动清单

#### 前端 — map.js
- **十字准星发送后保留**：右键菜单点击发送后，不再调用 `_hideContextMenu()`（该函数同时隐藏菜单和十字准星），改为只隐藏菜单，十字准星继续留在地图上供用户参考。点击地图其他位置时正常消失。

#### 后端 — ai_service.py
- **SYSTEM_PROMPT 修正**：第 402 行「任何数据都先 search_web」改为「统计数据才 search_web，行政边界优先用 datav_boundary」，避免 AI 用百度爬取替代 DataV。
- **新增热力图工作流**：SYSTEM_PROMPT 新增「热力图生成」章节，明确：datav_boundary 拿边界 → search_web 搜统计 → execute_python 在边界内采样 → create_heatmap。禁止用百度/高德 AOI 替代。

#### 技能文件
- `skills/heatmap.md`：新增「从城市名生成热力图的工作流」章节，明确 datav_boundary 优先，禁止 web 爬取百度地图。

---

## 2026-07-13（续7）：十字准星 viewport 固定 + 历史面板注册

### 改动清单

#### 前端 — map.js
- **十字准星重写**：所有子元素（竖线/横线/圆点/标签）从 `position:absolute` 相对于容器改为 `position:fixed` 直接使用视口坐标 `(x, y)`。移除对地图容器 `getBoundingClientRect()` 的依赖，缩放/拖拽时不再偏移。
- 容器 `#crosshair-overlay` 改为 `position:fixed; left:0; top:0; width:100%; height:100%` 全屏占位，仅作为统一移除的父节点。

#### 前端 — index.html
- **`panels` 映射表新增 `history`**：`var panels = {...}` 缺少 `history: document.getElementById('panelHistory')`，导致侧边栏"历史记录"点击无对应面板显示。

---

## 2026-07-13（续6）：布局修复 + 连续绘制 + 图层AI分析 + 删除优化

### 改动清单

#### 前端 — style.css
- **body 8px 默认边距修复**：`html, body { margin: 0 }` 显式声明（`*` 通配符在某些浏览器不覆盖 body 默认边距）
- **100vw → 100%**：`width: 100vw` 在 `overflow:hidden` 下仍计入滚动条宽度，导致右侧 8px 溢出，改为 `width: 100%`
- **Leaflet 版权署名定位**：`#map .leaflet-bottom { bottom: 4px !important }`，留呼吸空间，不被 `overflow:hidden` 裁切
- **图层面板操作列扩容**：`.map-layer-table .col-actions` 从 `64px` → `88px`，容纳新增的分析按钮

#### 前端 — index.html
- **删除按钮移除**：右上角 🗑 按钮去掉（用户反馈无实际用处）
- **模型选择 inline script**：精简模型列表为两个（deepseek-routed / glm-routed）

#### 前端 — map.js
- **ResizeObserver**：新增 `ResizeObserver` 监听 `.map-area` 尺寸变化，配合 50/200/500/1000ms 四次 `invalidateSize()`，确保 Leaflet 容器尺寸正确
- **删除按钮重写**：用 `L.Edit.Delete` API 不可用，改为自定义 `_enterDeleteMode()` / `_exitDeleteMode()` / `_onDeleteClick()`，通过 `drawnItems.on('click')` 事件委托实现点击图形删除，从地图 FeatureGroup 和 GIS layers 系统同时移除
- **连续绘制**：`L.Draw.Event.CREATED` 完成后检查按钮是否仍高亮，是则 50ms 后自动重新启用同款绘制工具，无需反复点击
- 暴露 `invalidateSize()` 公共方法

#### 前端 — layers.js
- **图层 → AI 分析按钮**：每个图层行新增 `data-action="analyze"` 按钮（⭐ icon-ai-send 图标），点击后：
  - 提取图层 GeoJSON + 计算中心坐标（`getGeoJSONCenter()`：遍历所有坐标求平均）
  - 组装提示词：位置归属 / 地理特征 / 气候海拔等
  - 通过 `GIS.chat.send()` 发给当前选中的 AI 模型
  - AI 分析后在地图加标记点 + 表格回复
- 新增 `analyzeLayer()`, `getGeoJSONCenter()` 函数
- `bindActionEvents()` 新增 `action === 'analyze'` 分支

### 已修复的问题
- 地图顶上有白框 → body 8px margin 导致布局偏移
- 地图右侧空白 → 100vw 溢出
- Bing 版权署名只显示一半 → `overflow:hidden` 裁切 + body margin 双重原因
- 删除按钮没反应 → `L.Edit.Delete` API 不存在
- 画完一个就停 → 缺乏连续绘制支持
- 图层想发给 AI 分析 → 无此入口

---## 2026-07-13（续5）：新增 GDAL 技能 + GLM+ 模式 + 右键修复

### 改动清单

#### 新增技能文件
- `skills/gdal.md`：GDAL 地理数据处理（栅格/矢量格式转换、投影转换、裁剪拼接、COG），从 GitHub GDAL Skill 适配

#### 新增 GLM-4.7-Flash+ 模式
- 模型选择器从 4 个精简为 2 个：DeepSeek V4 Flash+ 和 GLM-4.7-Flash+
- 淘汰标准 DS 和标准 GLM（DS+ 和 GLM+ 分别覆盖）
- GLM+ 流程：GLM 路由分析 → 加载 skill 文件 → GLM 执行（全程免费）
- 修正 api.js/chat.js/ai_service.py/main.py 中 glm-routed 链路不识别的问题

#### 右键菜单修复
- 去除标准 DeepSeek 选项，只保留一个"发送此位置给AI"
- 使用当前选中的模型（DS+ 或 GLM+）
- 提示词明确"只加一个点，不要生成多个点位"

---

## 2026-07-13（续3）：SYSTEM_PROMPT 精简 + Skill Chip 标签系统 + force_skills

### 背景
`SYSTEM_PROMPT` 过重（10423 字符），大量领域知识（matplotlib 代码示例、pyecharts 教程、途经省份判定模板等）每次都塞进 system prompt 浪费 token。同时斜杠命令 `/` 只是文本模板，用户想要可视化 chip 标签交互。

### 改动清单

#### skills/*.md — 充实领域知识（从 SYSTEM_PROMPT 迁移）
- **geometry.md**：添加坐标系规则、buffer 距离处理（投影→buffer→转回）
- **visualization.md**：添加 matplotlib 完整代码示例、pyecharts 雷达图/中国省级地图、hexbin 六边形分箱对比图
- **analysis.md**：添加途经省份精确判定流程（含 datav_boundary + get_layer_detail + shapely 空间分析模板）

#### 后端 — ai_service.py
- **SYSTEM_PROMPT 精简 54%**：10423 → 4826 字符，移除所有领域知识（迁移到 skills/*.md），新增"技能参考文档"节告知 AI 按需加载
- **force_skills 参数**：`chat_with_ai()` 新增 `force_skills: list`，接收前端 chip 标签指定的技能
- **GLM 路由 + force_skills 合并**：chip 技能作为补充（不是替代），与 GLM 路由结果合并去重，人机互补
- **全模型支持**：force_skills 对所有三个模型生效（不局限于 deepseek-routed）

#### 后端 — main.py
- `ChatRequest` 新增 `force_skills: list = []` 字段

#### 前端 — chat.js
- **Skill Chip 标签系统**：选中 `/` 命令后在输入框上方显示黑色圆角 chip `[ /buffer ✕ ]`
- **多 chip 叠加**：依次选中多个命令，chip 横向排列 `[ /buffer ] [ /heatmap ]`
- **Backspace 删除**：输入框为空时按 Backspace 删除最后一个 chip
- **✕ 按钮删除**：每个 chip 带关闭按钮
- **CHIP_TO_SKILL 映射**：chip 命令名 → 技能标签（buffer→geometry, heatmap→heatmap 等）
- **force_skills 传递**：发送时收集 chip 技能标签传入 API，发送后自动清空 chip
- **SVG 图标**：每个斜杠命令菜单项左侧显示 14×14 SVG 图标（几何/热力图/图表等）
- **选中后清 `/`**：按 Enter/Tab 选中命令后，自动移除输入框中的 `/command` 文字
- **Enter 冲突修复**：斜杠菜单打开时，Enter 优先选择命令，不会同时触发发送
- 新增函数：`_addChip()`, `_removeChip()`, `_removeLastChip()`, `_renderChips()`

#### 前端 — index.html
- `.chat-input-wrapper` 内新增 `.chip-container#chipContainer`（absolute 定位在输入框内部顶部）

#### 前端 — style.css
- `.chat-input-wrapper` 改为持 border，`textarea` 去掉 border，`:focus-within` 统一高亮
- 新增 `.chip-container` 样式（absolute 定位在输入框顶部，不占文本流）
- 新增 `.skill-chip` 样式（圆角 12px 黑色标签，chip-pop 入场动画）
- 新增 `.chip-close` 样式（✕ 按钮，hover 高亮）
- `.chat-input-wrapper.has-chips textarea.chat-input` 增加 `padding-top: 32px` 为 chip 留空间
- 新增 `.slash-item-icon`（20×20 容器，14×14 SVG 图标，灰色）
- 新增 `.slash-item-hint`（小号等宽字体显示 `/command` 快捷键提示）
- 调整 `.slash-item-left` 布局从 `baseline` 改为 `center` 对齐

#### 前端 — api.js
- `chat()` 新增 `forceSkills` 参数，POST body 中传递 `force_skills`

### 设计决策（补充）
- **Chip 嵌入输入框内部**：chip 用 absolute 定位在 wrapper 顶部，看起来像 GitHub 标签一样嵌在输入框里，不是独立的栏
- **无模板填充**：选中 `/` 命令后只加 chip，不往 textarea 填 prompt 模板，用户完全自由输入

### Token 节省
| 场景 | 之前 | 之后 | 节省 |
|------|------|------|------|
| 纯聊天（无需技能） | 10400 char/system prompt | 4800 char | **~54%** |
| 需要 1 个技能 | 10400 | 4800 + 600 = 5400 | **~48%** |
| 需要 2 个技能 | 10400 | 4800 + 1200 = 6000 | **~42%** |

### 设计决策
- **Chip 不跳过 GLM 路由**：chip 技能 + GLM 路由结果合并去重，人可能漏选但 GLM 兜底
- **数据只存临时目录**：所有生成文件在系统 temp 目录，用户主动下载才落本机
- **架构**：chip 是人为指定的技能标签，GLM 是自动补全，两者是"补充"关系不是"替代"关系

## 2026-07-13（续4）：代码质量工程化 + 单元测试

### 改动清单

#### 前端 — chat.js
- `var` → `let`/`const` 统一：102 处 `var` 改为 `const`（不重新赋值）、6 处改为 `let`（需重新赋值）
- 删除冗余 AI 生成注释（如 `// 点击选择`、`// 遍历数组`）

#### 前端 — style.css
- CSS 变量迁移标注：159 处 `--ui-*` 使用处添加 `/* -> --md3-xxx */` 注释
- `:root` 添加变量迁移说明块

#### 后端 — 新增单元测试
- `backend/tests/test_geometry.py`：27 个测试用例覆盖 6 类几何操作
  - buffer 4 个（正常/零距离/负数/精度）
  - intersection 4 个（相交/相接/不相交/包含）
  - centroid 4 个（正方形/点/线/空）
  - area 4 个（正方形/圆形/零面积/多部件）
  - make_valid 4 个（自相交/窄缝/环方向/已有效）
  - simplify 3 个（拓扑保持/顶点减少/高容差）
  - 实战 2 个（WGS-84↔UTM buffer 转投影、投影面积计算）
- `requirements.txt` 新增 `pytest>=9.0.0`
- 运行方式：`python -m pytest backend/tests/ -v`

#### 后端 — 清理
- `main.py`、`ai_service.py`：删除 2 条冗余注释
- `prompt_deepseek.md`、`prompt_glm.md`：同步更新为最新 system prompt 内容

### 背景
右键菜单十字准星存在三个 bug：① 地图拖拽到世界副本时准星定位到第一张图；② 缩放时准星偏移；③ 经度出现 1521° 荒谬值。同时空地图拖拽出现卡顿（Presentation Delay 76ms）。

### 改动清单

#### 前端 — map.js
- **十字准星**：从 Leaflet 地理图层（L.polyline/circleMarker/marker）彻底改为 HTML position:fixed 覆盖层，所有子元素相对于视口定位，overflow:hidden 裁剪到地图区域。不跟踪地图移动/缩放，点击在哪就固定在哪。
- **右键坐标**：恢复归一化到 -180~180，取消之前 layerPointToLatLng 的尝试（该方案会导致 1521° 异常值）。
- **mousemove 性能**：缓存 `_coordsEl` / `_zoomLabelEl` 的 DOM 引用，移除 querySelector 调用。
- **loadHeatmap**：增加 `typeof L.heatLayer !== 'function'` 防御检查。

#### 前端 — index.html
- 添加 leaflet.heat CDN 引用（cdnjs），位于 Leaflet 和 marked 之后。

#### 前端 — style.css
- `#map` 添加 `contain: paint layout style`，隔离地图渲染层，降低合成开销。
- 添加右键菜单（`.map-context-menu`）、十字准星标签（`.crosshair-leaflet-label`）、模型徽章（`.msg-badge`）样式。
- 移除了之前尝试的 `will-change: transform`（在某些 GPU 上降性能）。

#### 性能诊断
- Chrome DevTools Performance 录得 INP 80ms，其中 Presentation Delay 76ms（占 95%）
- 瓶颈为 Bing 卫星瓦片 JPEG 解码 + 页面合成层开销
- `contain: paint layout style` 可将地图的渲染与页面其他部分隔离

### 未解决
- 地图卡顿可能根源在 Bing CDN 瓦片加载或系统级 GPU 渲染，纯前端优化空间有限

## 2026-07-13（续2）：斜杠命令系统 + 技能文件化

### 背景
AI 与地图图层联动不够直接，用户需手动写 shapely 代码 + print GeoJSON。同时内联技能存在 Python 字典中，增删改不便。

### 改动清单

#### 前端 — index.html
- 输入框上方新增 `/` 斜杠命令弹出菜单容器
- 输入框 placeholder 提示"键入 / 打开命令面板"

#### 前端 — chat.js
- 新增 `SLASH_COMMANDS` 数组，定义 13 个斜杠命令：
  - `/buffer` / `/intersection` / `/union` / `/difference` — 几何操作
  - `/centroid` / `/simplify` / `/make_valid` / `/area` / `/length` — 几何工具
  - `/aoi` / `/boundary` — 边界提取
  - `/heatmap` — 热力图
  - `/plot` — 统计图表
- 每个命令包含 name/label/desc/prompt（带 `{变量}` 占位符）
- 输入`/`自动弹出菜单，支持↑↓选择、Enter确认、Esc取消
- 选中命令后自动替换输入框内容，光标定位到 `{变量}` 处
- 点击外部自动关闭菜单

#### 前端 — style.css
- 新增 `.slash-menu` 系列样式（底部弹出、阴影、白色背景）

#### 项目根
- 新增 `skills/` 目录，包含 6 个 Markdown 技能文件：
  - `geometry.md` — 几何操作（含 CRS 处理规则）
  - `aoi.md` — AOI 建筑轮廓提取
  - `datav.md` — DataV 行政边界
  - `heatmap.md` — 热力图参数
  - `visualization.md` — 图表可视化
  - `analysis.md` — 空间分析

#### 后端 — ai_service.py
- `_INLINE_SKILLS` 字典精简为回退缓存（简短描述）
- 新增 `_load_skill_from_file()`：优先从 `skills/*.md` 加载，找不到才回退内联
- `_read_skill_files()` 改为调用文件加载器
- `_GLM_ROUTER_PROMPT` 新增 6 个新技能标签
- `_SKILLS_DIR` 定位到项目根 `skills/` 目录

### 架构
```
用户键入 /buffer
  → 弹出命令菜单，选中
  → 输入框填入 "为当前选中的图层创建 {距离} 米的缓冲区"
  → 用户填参数，回车发送
  → GLM 路由识别需要 geometry 技能
  → 加载 skills/geometry.md → 注入 DeepSeek
  → DeepSeek 按技能规则自动转 UTM → buffer → 结果上地图
```

## 2026-07-13（续）：DeepSeek V4 Flash GLM 协作模式 + 技能文档系统

### 背景
用户希望 DeepSeek 画图/空间分析时能参考完整的 matplotlib/pyecharts 技能文档，但又不希望每次都把技能文档塞进 prompt 浪费 token。核心方案：GLM（免费）先分析问题，按需加载技能文件，再注入 DeepSeek。

### 改动清单

#### 后端 — ai_service.py
- **DeepSeek V4 Flash（`deepseek-routed`）GLM 协作模式**：新增 GLM 预分析层
  1. `_glm_route_skills()` — 调 GLM 分析用户问题，返回需要的技能标签（JSON 数组）
  2. `_read_skill_files()` — 根据标签读取内联技能文档
  3. 在 `chat_with_ai` 中插入路由逻辑：`deepseek-routed` 时先路由 → 再 DeepSeek 执行
- **内联技能文档**：`_INLINE_SKILLS` 字典，包含 matplotlib/pyecharts/geopandas/shapely 四个技能的核心用法。不依赖外部文件（删除了 `claude-scientific-skills/` 目录）
- **GLM 路由降级**：GLM 密钥未配置或分析失败时自动降级为纯 DeepSeek
- **matplotlib 中文字体修复**：从 `font.family = 字体名` 改为 `font.sans-serif + font.family = 'sans-serif'`，兼容性更好
- **hexbin 对比图 prompt**：添加完整代码示例（左散点 + 右六边形分箱，颜色梯度）
- **SYSTEM_PROMPT 增强**：引用内联技能文档路径，支持 execute_python 读取

#### 前端 — index.html
- **模型选择器**：三模型排列
  - `DeepSeek V4 Flash`（默认，最上方，小字说明 GLM 协作节省 token）
  - `DeepSeek V4 Flash`
  - `GLM-4.7-Flash`（免费）
- **右键菜单**：新增"增强"选项（`send-location-routed`），badge 深色"增强"

#### 前端 — map.js
- **右键菜单 handler**：`send-location-routed` 固定走 `deepseek-routed` 模式
- 修复多余的 `}` 语法错误（导致地图不加载）

#### 前端 — chat.js
- **DS+ 加载状态**：先显示"GLM 路由分析中..."（1.5 秒后切到"执行中..."），让用户感知双阶段
- `_phaseTimer` 清理逻辑，防止内存泄漏

#### 前端 — api.js
- 默认模型从 `deepseek` 改为 `deepseek-routed`

### 架构设计

```
用户问题
  │
  ▼
GLM（免费）→ 分析问题 → 返回技能标签如 ["matplotlib"]
  │
  ▼
读取 _INLINE_SKILLS 字典 → 取出 matplotlib 技能内容
  │
  ▼
注入 DeepSeek SYSTEM_PROMPT → DeepSeek 正常执行（无感）
  │
  ▼
回复用户
```

- 不需要技能时（纯聊天）：无额外 DeepSeek token 消耗
- 需要技能时（画图等）：+~700 DeepSeek token / 次
- GLM 路由消耗：免费

### 设计决策
- **不塞进固定 prompt**：固定 prompt 每次对话都消耗 token，路由按需加载更省
- **不依赖外部文件**：技能内容内联在 Python 字典中，部署不需要额外文件
- **右键全留给 DeepSeek 系**：右键菜单只出现 DeepSeek / DS+，GLM 不出现

---

## 2026-07-12：新增 12 个 GIS 空间分析工具

### 背景
用户希望项目拥有类似 ArcGIS 的自然语言驱动空间分析能力，且地图（Leaflet）能渲染热力图。

### 改动清单

#### 前端
- **index.html**：加入 `leaflet.heat` CDN（热力图插件）
- **map.js**：新增 `loadHeatmap(points, name, options)` 和 `removeHeatmap(name)` 函数
- **chat.js**：新增 `result.heatmap` 接收与渲染逻辑

#### 后端
- **ai_service.py**：
  - 新增全局变量 `pending_heatmap`
  - 新增 12 个工具函数（见下方列表）
  - 在 `tools` 列表中注册 12 个 JSON Schema
  - 在 dispatch 链中新增 12 个 `elif` 路由
  - DeepSeek + GLM 两个 SYSTEM_PROMPT 同步更新
- **main.py**：新增 `pending_heatmap` 导入 + `/api/chat` 响应字段

### 回退：去掉专用工具，全部走 execute_python

回到项目的原始设计理念 — AI 用 `execute_python` 自己写代码处理空间分析。

**保留的工具：**
- `create_heatmap` — 需要前端 leaflet.heat 配合渲染
- `clear_layers` — 清空地图
- 原有的 `datav_boundary` / `search_web` / `fetch_webpage` 等不变

**去掉的 11 个工具：**
buffer_analysis, clip_analysis, intersect_analysis, centroid_extract, distance_measure, coordinate_transform, attribute_query, spatial_query, merge_layers, simplify_geometry, voronoi_analysis

以及后加的 generate_contour。

**提示词改造：**
- 在 `execute_python` 说明里详细列出每种空间分析对应的代码模板
- AI 通过 execute_python 自行写代码，print GeoJSON 自动加载地图

### 架构核心
- AI 用 `execute_python` 写 Python（shapely/geopandas/matplotlib）
- `print(json.dumps(geojson))` → 自动加载到地图
- `plt.savefig("output/chart.png")` → 自动显示在聊天框
- 不需要为每种分析定义专用工具

---

## 更新日志

### 2026-07-16
- Add 高程查询工具（随后移除）
- Remove 高程查询工具、百度 AOI 服务、高德高程查询服务
- Fix AI 服务清理引用残留

### 2026-07-15
- Add Agnes 2.0 Flash+ 模型
- Add 道路网络提取工具（OSMnx + Overpass）
- Remove 独立高德/百度 AOI 路由（合并为统一工具）
- Fix Agnes 路由统一走 GLM

### 2026-07-14
- Add 图层属性表编辑与筛选导出
- Add 字段计算器
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
