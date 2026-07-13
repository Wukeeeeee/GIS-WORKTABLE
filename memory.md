# GIS WorkTable — 开发记忆

> 记录每次开发会话的关键决策、改动和待办事项。

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
