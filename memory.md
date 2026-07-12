# GIS WorkTable — 开发记忆

> 记录每次开发会话的关键决策、改动和待办事项。

---

## 2026-07-13：十字准星重构 + 地图性能优化

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
