# GeoLibre 手动交互与性能优化学习笔记

> 目标：把「不接 Agent 也能干活的人工操作」补齐到 GIS-WorkTable。
> 来源：geolibre.app 用户指南（Map Controls & Tools 页面抓取，2026-09）+ 此前源码调研（见 research_3d_globe_drilldown.md）。

## 1. GeoLibre 的手动功能清单（按钮/控件盘点）

GeoLibre 的所有核心能力都有**常驻手动按钮**，AI 只是锦上添花：

| 类别 | 控件 | 我们的状态 |
|---|---|---|
| 视图 | 缩放/指北/2D-3D 投影切换/全屏/视图书签 | 缩放有；2D-3D 切换 P0 已加；**底图切换、复位视角 本次补齐** |
| 底图 | 影像/街道/地形/深色 多源切换器 | 2D 无；**3D 已加（影像/街道/深色）** |
| 绘制 | 点/线/面/文字标注/编辑顶点/捕捉 | 已有（Leaflet.Draw） |
| 测量 | 距离/面积/即时读数 | 已有 |
| 图层 | 显隐/透明度滑块/重命名/分组/拖拽排序 | 显隐有；**透明度滑块本次补齐** |
| 符号化 | 单一符号/唯一值/分级/比例符号/图例 | 已有（检查器符号系统 tab）；**3D 拉伸本次补齐** |
| 检查 | 属性表/筛选/字段统计/定位 | 已有 |
| 下钻 | （GeoLibre 无此功能，我们自研） | P0 已有：面包屑 + 要素面板下钻按钮 |
| 导出 | PNG/GeoJSON/SHP/截图 | 已有 |

## 2. GeoLibre 的性能/流畅性做法（与本次采纳对照)

| GeoLibre 做法 | 原理 | 本次采纳 |
|---|---|---|
| MapLibre/deck.gl GPU 按需渲染 | 场景不变就不画帧，省 GPU、风扇不转、笔记本省电 | **Cesium `requestRenderMode: true` + `maximumRenderTimeChange: Infinity`**：交互/相机飞行自动触发，实体材质变更显式 `scene.requestRender()` |
| WASM(DuckDB) 把重计算放前端本地 | 不等网络往返，操作即时反馈 | 未采纳（我们重计算在后端 Python，属架构差异） |
| 大数据虚拟化/分块渲染 | 一次只画视野内要素 | 部分已做（map.js >5000 要素跳过逐要素绑定）；后续可做 Canvas 渲染器切换 |
| 懒加载重资源 | 首屏只加载必需模块 | 已做（Cesium 懒加载，点 3D 才拉取） |

## 3. 本次落地（人工操作不经过 Agent）

### 3.1 全部图层进入共享状态（手动同步的地基）
- `layers.js addLayer` 桥接：上传/绘制/工程恢复/网络分析等**所有**手动图层统一注册进 `GIS.state`（`_panelSync` 防递归、`_mapName` 保持 2D 地图名、`_skip2DRender` 防重复渲染、保留后端 register 行为）。
- `removeLayer`/`toggleVisibility` 同步走 state 删除/显隐。
- 效果：**上传图层在 3D 里可见了**（P0 时只有 Agent 图层能进 3D），删图层 3D 同步消失。

### 3.2 图层检查器新增手动控件
- **透明度滑块**（基础信息 tab）：2D 直接驱动 `map.setLayerOpacity`（基样式缓存缩放，反复拖动不累积），3D 经 `state.setOpacity` 广播（基色 × alpha）。
- **3D 拉伸可视化**（符号系统 tab，面图层专属）：选数值字段 + 最大高度 → `state.applyVisualization({type:'extrusion',...})`，色带自动取顺序色带首尾；「应用符号化」联动拉伸，「清除符号化」联动清除。**这就是原 P1 visualize op 的手动版**。

### 3.3 3D 常驻控制条（GeoLibre 式按钮）
- 底图切换：影像 / 街道 / 深色球体（Esri XYZ 免 key）。
- 复位视角：优先飞当前下钻层级范围，否则全国。
- 随 2D/3D 切换显隐，激活态高亮。

### 3.4 流畅性
- Cesium 空闲零渲染（requestRenderMode），所有同步操作（装载/显隐/透明度/拉伸/高亮/底图）补 `scene.requestRender()`。

## 4. 后续可学（未做，按价值排序）
1. **视图书签**（保存当前相机 → 一键回到工作区视角；2D 存 center/zoom，3D 存 camera cartographic）。
2. 图层面板右键菜单（缩放到图层 / 置顶 / 重命名，已有雏形可扩展）。
3. fillPattern 填充图案在 Canvas 渲染器下失效的兼容（`preferCanvas:true` 已全局开启，但 `_path.setAttribute` 仅 SVG 生效）。
4. 3D 底图与 2D 底图选项对齐（2D 已有 Bing/Esri/白底菜单；3D 影像/街道/深色）。

## 5. 第二轮 3D 优化（2026-09-25，持续优化目标）

**2D 功能进 3D**
- 空间分析按钮（缓冲区/叠置/裁剪/质心/简化/融合）在 3D 可用：面板本身 `position:fixed; z-index:9998`，分析走后端 GeoJSON，结果经 chat → state.addLayer → 3D 自动装载，链路闭环。
- 3D 下隐藏坐标显示（Leaflet 驱动、在 3D 不更新）：`body.gis-mode-3d` 标记 + CSS。

**AI ↔ 3D 数据关联**
- 新增 `visualize_3d` 后端工具（P1 visualize op 落地）：校验图层存在/面图层/字段数值/高度范围 → 发 `{"action":"visualize","viz":{type:"extrusion",field,maxHeight}}` spec → chat.js 执行 `state.applyVisualization`。字符串数字字段兼容；8 项测试钉住校验分支。
- `center` op 在 3D 下按 zoom 粗略换算相机高度 flyTo（原来只动隐藏的 Leaflet 地图）。

**数据展示修复**
- 3D 下新图层装载后自动飞到其 bbox（对齐 2D fitBounds 行为；初始批量同步不触发）。
- 点要素：pixelSize 按线宽放大（默认过小不易点选）；选中高亮与透明度同步支持点/线（原来只有面）。

**UI 修复**
- 属性面板 `right:12→68px`，不再覆盖右侧控件栏（2D/3D 都修）。
- 控件栏 `mode-3d`：只留 2D/3D 切换 + 影像/街道/深色 + 复位；`body.gis-mode-3d` 用于 body 级 CSS 联动。

## 6. 第三轮：符号化颜色同步 3D（2026-09-25）

- **2D 符号化 → 3D 按要素设色**：四类符号化（唯一值/分级色彩/分级符号/比例符号，UI 与 AI 两路汇聚的内部函数）应用后，把 `{_fid: 颜色}` 经 `state.setFeatureColors` 推给 3D 渲染器（`feature-style` 事件），面/线/点全部按要素着色。清除符号化时经 `setFeatureColors(null)` 触发 3D 重载回基础色；重载后按「featureColors → viz」顺序重放（拉伸仍然优先于符号化颜色）。
- **`fit`（缩放到图层）op 在 3D 生效**：从共享状态按名找图层 bbox，经 `GIS.renderers.flyToBbox`（本轮导出）飞行；2D 分支不变。
- 复盘修正：2D 底图切换（Bing/Esri/白底菜单）与全局 `preferCanvas` 项目里**已有实现**，此前误列积压。

## 7. 第四轮：视图书签 + 两个真实缺陷（2026-09-25）

- **视图书签**（积压第 1 项落地）：控件栏书签按钮（2D/3D 常驻）→ 面板保存/删除/一键回到视角，localStorage 持久化（`gis_view_bookmarks`）。2D 存 center/zoom，3D 存相机经纬度/高度/heading/pitch/roll；应用时模式不匹配自动切换。GeoLibre 的 Map Controls 里「视图书签」是高频功能。
- **缺陷修复①：进 3D 画布尺寸错误风险**——容器 `display:none → block` 时 Cesium 不自动感知（它只监听 window resize），首次进入可能出现画布比例/分辨率不对；现在显式 `viewer.resize()`。
- **缺陷修复②：2D 下钻返回不回位**——`view-changed` 事件原本只有 3D 在听，2D 面包屑返回上一级时相机停在子级范围；map.js 现在订阅该事件 fitBounds，下钻进/出相机行为 2D/3D 一致。
- 已知问题（未修，记录）：AI `rename` op 只改面板 `filename/_rawName`，不同步共享状态与后端注册名，重命名后 AI 按新名可能查不到图层（历史遗留，与 3D 无关）。
