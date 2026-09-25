# GIS-WorkTable 3D Globe / 下钻式地图可视化 — 技术调研与架构规划报告

> 调研日期：2026-09-25
> 范围：现有代码库精读（前端 18 模块 + 后端 services）、CesiumJS API、GeoLibre（opengeos）与吴秋生相关项目、中国 GIS 数据源与合规、Cesium Ion 解耦方案。
> 目标：回答「是否引入 Cesium / 是否双 Renderer / 是否共享状态 / 下钻是否值得作为核心交互」，并给出落到具体文件的 MVP 实施计划。

---

## 1. 技术结论（TL;DR）

| 问题 | 结论 |
|---|---|
| 是否值得加入 Cesium 3D Globe？ | **值得**。项目已有完整的数据底座（GeoJSON 图层通道、DataV 行政区边界、bbox/flyTo、要素选中），加 3D 只需「一个共享状态 + 一个新 Renderer + 一个下钻工具组」，边际成本远低于价值。 |
| 是否采用 MapLibre + Cesium 双 Renderer？ | **不采用 MapLibre。保持 Leaflet(2D, 现状) + 新增 CesiumJS(3D)**。理由：① Leaflet 承载着绘制/编辑/捕捉（Leaflet.Draw）、VectorGrid 大数据、热力、属性联动等大量已实现功能，替换风险高；② MapLibre v5 虽有 globe（2025-01），但其 3D 分析能力（extrudedHeight 实体体系、成熟 picking、quantized-mesh 地形、3D Tiles 全家桶）弱于 Cesium，而项目明确规划了 DEM/3D Tiles 方向；③ 引入 MapLibre 作为第三引擎会加剧「三个 Renderer」问题。 |
| 是否共享 GIS Layer / Project State？ | **必须共享，且这是本方案的第一优先级工程**。当前 GIS 状态分散在三处（见 §2 诊断），不先收敛状态就上 3D，会变成第四份副本。 |
| 下钻式地图是否值得作为核心交互？ | **值得，且成本极低**。后端 `datav_boundary`（tools.py）+ `datav_service.py` 已能取省/市/区三级边界（GCJ-02→WGS84 已修好），`focus_map` 已能按 bbox 飞行；下钻只是把「加载数据 + 飞行 + 选中」编排成一个状态机。建议 2D/3D 共用同一个下钻状态机。 |
| Cesium Ion 是否必须？ | **不必须**。CesiumJS 是 Apache-2.0 开源库，可完全离线运行；Ion 只是可选云服务。详见 §7。 |

**一句话方案**：新建 `frontend/js/gis_state.js` 作为唯一 GIS 状态源（图层/选中/下钻栈），把现有 Leaflet 封装改造成它的一个 Renderer 适配器，新增 `renderer_cesium.js` 作为第二个适配器；后端新增 `drill_down / drill_up / visualize_regions` 三个 Agent 工具，复用现有 `_push_layer / layer_ops` 通道。

---

## 2. 现有代码库诊断（第一阶段调研结果）

### 2.1 总体架构

```
前端（原生 JS，无构建，CDN 引入 Leaflet 1.9.4 / Leaflet.Draw / VectorGrid / leaflet-heat / marked）
  frontend/js/*.js — 18 个 IIFE 模块，全局命名空间 window.GIS.*
后端（FastAPI + LangGraph ReAct）
  backend/services/tools.py — 101 个 @tool，模块级全局变量持有图层状态
  SSE/JSON 通道：tools 收集 pending 状态 → chat_with_ai 返回 → 前端 chat.js 分发渲染
```

### 2.2 关键回答：**现在不存在一个可作为 2D/3D 共同数据源的 GIS State**

GIS 状态目前分散在**三处、以不同键互相耦合**：

| 位置 | 状态 | 键 | 内容 |
|---|---|---|---|
| `frontend/js/map.js`（模块闭包，map.js:21-38） | `layers{name→LeafletLayer}`、`geoStore{name→{geojson,style}}`、`_featureMap{"name:idx"→LeafletLayer}`、`_rasterLayers`、`_labelConfigs`、undo/redo 栈 | **图层名字符串 + 要素下标** | 实际渲染 |
| `frontend/js/layers.js`（layers.js:16-18, 1006） | `layerData[]`（layer_id/filename/_rawName/visible/color/geojson/…）、`_symbologyConfig{layer_id→config}` | layer_id（列表）/ _rawName（地图） | 图层面板、符号化配置 |
| `backend/services/tools.py`（tools.py:169-199, 181） | `_registered_layers{name→{geojson,bbox,feature_count,geometry_types}}`、`_pending_layers`、`_pending_layer_ops` | **图层名字符串** | Agent 可见的图层表、推送队列 |

问题清单（直接影响 3D 集成）：

1. **要素身份不稳定**：前端要素 = `图层名:下标`（map.js:497-500 `_featureMap[key]`）。任何重载（符号化 applySymbology、撤销恢复、重命名）都重建映射。3D 选中同步需要跨渲染器稳定 ID，目前没有。
2. **无事件/订阅机制**：模块间直接函数调用（`GIS.map.loadGeoJSON(...)`），chat.js 用 switch-case 手工分发 `layer_ops`（chat.js:1150-1212）。加第三、第四个消费者（3D、面包屑、属性面板）只能继续 if-else。
3. **后端以 name 为唯一键**：`_registered_layers` 是模块级全局、key 是名字，重名靠前端加时间戳后缀绕过（chat.js:1241 `uniqueName = layerName + '_' + Date.now()`）；前后端各自拼 uniqueName，可能出现前端叫 A_123、后端叫 A 的漂移。
4. **符号化配置只在前端**：`_symbologyConfig` 不进工程文件、不回传后端，Agent 每轮重新用 `spatial_graduated_colors` 生成，与用户手调状态会互相覆盖。
5. **CRS 约定为隐式**：全链路默认 WGS-84（map.js 头注释），DataV 的 GCJ-02 在后端转好（datav_service.py:191-195），前端只留了一个经纬度颠倒的兜底（map.js:489-495）。没有正式的 per-layer CRS 字段（`layer_service.inspect_geojson` 只做检测）。
6. **Project 状态**：`project_service.py` 用 CAS blob（sha256 gzip）存 layers/messages/map_state，结构健康，可平滑加入 `crs`、`style`、`fid` 字段。

### 2.3 可复用的积木（好消息）

- **数据通道已统一且有静态守卫**：`_push_layer/_register_layer`（tools.py:267/339）是唯一合法图层入口（AST 守卫测试钉死），`get_pending_state()` 消费式下发 → `main.py /api/chat` → `chat.js`。3D 只需挂到这条通道下游。
- **行政区数据已在库**：`datav_boundary` 工具 + `datav_service.fetch_boundary`（省/市/区三级、adcode 缓存 `cache/aoi/`、GCJ-02→WGS84 已修复并测试）。**下钻的数据源就是它**。
- **相机飞行已有**：`focus_map`（tools.py，按图层名/bbox/经纬度，zoom 夹取 3-19）、前端 `GIS.map.flyTo/fitLayer`。
- **选中已有雏形**：`highlightLayerFeature(name, idx)`（map.js:703）、属性表定位联动（layers.js:923-934）。只差把「选中」提升为全局状态。
- **工程保存/加载**：CAS 结构可直接扩展。

---

## 3. CesiumJS 深度调研

### 3.1 GeoJSON 加载（MVP 的核心）

```js
const ds = await Cesium.GeoJsonDataSource.load(geojsonObjectOrUrl, {
  stroke: Cesium.Color.fromCssColorString('#1c1b1b'),
  fill: Cesium.Color.fromCssColorString('#1c1b1b').withAlpha(0.35),
  strokeWidth: 2,
  markerSymbol: '?', markerSize: 24, markerColor: Cesium.Color.ROYALBLUE,
  clampToGround: false,   // true 时贴地（需地形），关闭时按 z/0 高度
});
viewer.dataSources.add(ds);
```

- 直接支持 `Point/MultiPoint/LineString/MultiLineString/Polygon/MultiPolygon`（含 GeometryCollection），**可直接吃 GeoJSON 对象或 URL**；坐标含第三维时自动作为高程使用（clampToGround=false 时）。
- 每个 Feature 变成一个 `Cesium.Entity`：`entity.properties` 是 `PropertyBag`，取原始值 `entity.properties.adcode.getValue(Cesium.JulianDate.now())`；`entity.properties.getValue(date)` 返回整个属性对象。
- 与 Leaflet 的行为差异：GeoJsonDataSource 不会自动 fitBounds，需手动 `viewer.zoomTo(ds)` / `viewer.flyTo(ds)`。
- 性能：**Entity 模式在数千~一万级 Polygon 下可用**（中国区县级约 2800 个面没问题，市/省级只有几十个）。每 entity 一份 geometry batch，样式变更触发重编译。十万级以上才需要换 Primitive API（`GeometryInstance + PerInstanceColorAppearance` 一次 GPU 批处理）或新版提供的 primitive 化 GeoJSON 管线（新文档已出现 `GeoJsonPrimitive` / `MVTDataProvider`，说明官方在补矢量瓦片路径）。MVP 用 Entity 模式，够用且可逆。

### 3.2 点击 / Picking / 选中（下钻交互的核心）

```js
const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
handler.setInputAction((movement) => {
  const picked = viewer.scene.pick(movement.position);           // 单个；drillPick 可取多层
  if (Cesium.defined(picked) && picked.id instanceof Cesium.Entity) {
    const props = picked.id.properties.getValue(Cesium.JulianDate.now());
    onSelectFeature(picked.id, props);   // → 写入共享 GIS.state.selection
  }
}, Cesium.ScreenSpaceEventType.LEFT_CLICK);
```

- `scene.pick` 返回 `{id: Entity, primitive}`；`scene.drillPick(position)` 可穿透取栈。
- **高亮标准做法**：直接改 entity 材质 + 轮廓：
  ```js
  entity.polygon.material = Cesium.Color.RED.withAlpha(0.5);
  entity.polygon.outline = true; // 注意：outline 在地形上会被深度剔除，MVP 关闭 clampToGround 时可靠
  ```
  需要永不遮挡的描边时用 `Cesium.PolylineCollection` 沿边界画线，或叠一个同几何 highlight entity。默认 `viewer.selectedEntity` 会弹内置 InfoBox，可用 `infoBox: false` 关掉、换成自己的属性面板。
- Hover：`MOUSE_MOVE` + `scene.pick`，节流即可。

### 3.3 数据驱动的 3D 可视化（人口→高度 / GDP→颜色）

这是 Cesium 与 Leaflet 体验差距最大的地方，实现却很简单——遍历 entity、读属性、写样式：

```js
function applyViz(ds, viz) {
  // 1) 归一化字段
  const vals = ds.entities.values.map(e => e.properties[viz.field].getValue(...));
  const min = Math.min(...vals), max = Math.max(...vals);
  const norm = v => (v - min) / (max - min || 1);

  ds.entities.values.forEach(e => {
    const t = norm(e.properties[viz.field].getValue(...));
    if (viz.type === 'extrusion') {
      // 面要素直接拉伸：人口越多柱子越高（本质是 extrudedHeight）
      e.polygon.extrudedHeight = (viz.minHeight ?? 0) + t * (viz.maxHeight ?? 200000);
      e.polygon.height = 0;                       // 底面贴地
      e.polygon.material = Cesium.Color.fromCssColorString(rampColor(t)).withAlpha(0.85);
    } else if (viz.type === 'choropleth') {
      e.polygon.material = Cesium.Color.fromCssColorString(rampColor(t)).withAlpha(0.8);
    }
  });
}
```

- **Polygon 拉伸** = `entity.polygon.extrudedHeight`（ConstantProperty 或 `CallbackProperty` 做动画生长）。
- **颜色映射** = `entity.polygon.material`（ColorMaterialProperty / ImageMaterialProperty / CheckerboardMaterialProperty…）。
- **点要素柱状**：`BoxGraphics`（dimensions + position 抬高）或 `CylinderGraphics`。
- **标注**：`LabelGraphics` + `DistanceDisplayCondition` 控制缩放级显隐；Text 走 Canvas。
- **聚合**：`ds.clustering.enabled = true; ds.clustering.pixelRange = 30; ds.clustering.minimumClusterSize = 5;` + `clusterEvent` 自定义聚合样式。对 POI 点层直接可用。
- 动态样式（按帧/按相机距离）用 `CallbackProperty`；静态一次性设置用 ConstantProperty（性能好一个数量级）。

### 3.4 Camera

```js
// 按 GeoJSON 边界飞（下钻的标准动作）
viewer.camera.flyTo({ destination: Cesium.Rectangle.fromDegrees(w, s, e, n) });
// 或带朝向的包围球
viewer.camera.flyToBoundingSphere(boundingSphere, { duration: 1.5, offset: new Cesium.HeadingPitchRange(h, -Cesium.Math.PI_OVER_TWO * 0.7, range) });
viewer.flyTo(dataSource); viewer.zoomTo(entity);
```
现有后端 bbox（`_registered_layers[name].bbox` = `[minLng,minLat,maxLng,maxLat]`）可直接喂 `Rectangle.fromDegrees`，与 `focus_map` 的逻辑完全同构。

### 3.5 Imagery / Terrain / 3D Tiles（P2 方向）

- **Imagery**：任意 XYZ 瓦片用 `UrlTemplateImageryProvider({url, credit})`；WMTS 用 `WebMapTileServiceImageryProvider`。天地图可直连（`https://t{s}.tianditu.gov.cn/DataServer?T=img_w&x={x}&y={y}&l={z}&tk=KEY`，web 墨卡托版 `_w`；CGCS2000 经纬度版 `_c` 用 `GeographicTilingScheme`）；高德/谷歌瓦片是 GCJ-02 偏移的，叠加 WGS84 矢量会有约 500m 偏差——Bing 卫星（项目 2D 默认底图，quadkey URL）在 Cesium 里也有 `BingMapsImageryProvider`，但需要 key；离线场景用本地 XYZ 或 SingleTileImageryProvider。
- **Terrain**：默认 `EllipsoidTerrainProvider`（纯椭球，零依赖）。本地地形两条路：① `CesiumTerrainProvider({url})` 指向自托管 quantized-mesh（用 Cesium Terrain Builder / ctb-tile 从 DEM 生成 `layer.json + 0/1/2...` 瓦片，静态文件即可）；② `ArcGISTiledElevationTerrainProvider` 直连 LERC 高程瓦片（可自建）。**不需要 Ion。**
- **3D Tiles**：自托管 = 一组 `.b3dm/.glb + tileset.json` 静态文件，`Cesium3DTileset({url})` 加载；转换用 `3d-tiles-tools` / obj2gltf / osgb23dtile 等。OSM Buildings 可从 ion 免费层取，也可用 OSM 数据自转。

### 3.6 与 Leaflet 的分工（回答「3D 的真正价值」）

| 放 2D（Leaflet，现状不动） | 放 3D（Cesium，新增） |
|---|---|
| 数据编辑（Leaflet.Draw 折点编辑、捕捉） | Globe/全球尺度浏览 |
| 属性表编辑、筛选、导出 | DEM/地形（已有后端 DEM 工具链，未来直接 3D 呈现） |
| Buffer/Overlay/Intersection/KDE/Moran's I 等分析（后端算，2D 看结果更精确） | 数据驱动 extrusion（人口→高度、GDP→颜色） |
| 专题制图（分级色彩/唯一值/打印/PDF） | 大规模点/建筑/3D Tiles/点云 |
| 下钻的「精确选面」操作 | 下钻的「空间感」呈现与飞行叙事 |

**下钻状态机是 2D/3D 共用的**——这正是共享状态的价值：同一个 `drill.stack`，两个 Renderer 只是两种「看」法。

---

## 4. 下钻式 GIS 设计（Hierarchical Drill-down）

### 4.1 状态模型

```js
// gis_state.js 中的一段
GIS.state.drill = {
  stack: [
    { level: 'country',  adcode: 100000, name: '中国',   layerId: 'l_base' },
    { level: 'province', adcode: 430000, name: '湖南省', layerId: 'l_prov' },
    { level: 'city',     adcode: 430100, name: '长沙市', layerId: 'l_city' },
  ],          // 导航历史栈（back = pop）
  current: <栈顶引用>,
  breadcrumb: ['中国', '湖南省', '长沙市'],
}
```

- **层级判定**（纯 adcode 规则，无魔法）：`xxxxx000 + level 字段`——DataV 每个 feature 自带 `properties.level`（'province'/'city'/'district'）和 `adcode`，比字符串规则更可靠；**直接使用 DataV 的 level 字段**。
- **drillDown(feature)**：
  1. 读 `feature.properties.adcode`（无 adcode 的图层不支持下钻，按钮置灰）；
  2. 调后端取子级边界：MVP 直接前端 `fetch('https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json')`（GCJ-02，需前端转换）或走后端 `datav_boundary`（已有 WGS84 转换+缓存，**推荐走后端**）；
  3. `GIS.state.addLayer(childLayer, {drill: true})`、隐藏同级父层；
  4. `GIS.state.setView({bbox: childLayer.bbox, mode: current})` → 两个 Renderer 各自飞；
  5. `stack.push(...)` → 面包屑自动更新。
- **drillUp(n)**：`stack.pop()` n 次 → 恢复父级图层显隐 → flyTo 父级 bbox。History 就是栈，浏览器级 undo 不需要。
- **selectedFeature 与下钻解耦**：`selection` 记录 `{layerId, featureId, props}`；点「进入」按钮或双击才触发 drillDown，单击只选中——避免误触钻取。

### 4.2 交互矩阵

| 交互 | 2D (Leaflet) | 3D (Cesium) |
|---|---|---|
| 单击行政区 | 高亮 + 属性面板（复用 `_highlightFeature`） | 高亮 + 属性面板（`scene.pick`） |
| 双击/「下钻」按钮 | drillDown | drillDown（相机带 pitch 的飞行更出彩） |
| 面包屑点击任意级 | drillUpTo(i) | drillUpTo(i) |
| Esc | drillUp(1) | drillUp(1) |
| Agent 说「下钻到长沙」 | `drill_down` 工具 → layer_ops `drill` → 状态机统一处理 | 同左 |

### 4.3 行政数据与层级边界

- DataV areas_v3：省 34 → 市 333 → 区县 ~2800；`{adcode}_full.json` 是「下一级全集」。**街道级（9 位 adcode）DataV 不完整**，MVP 下钻到区县为止（与用户 MVP 定义一致）；街道/POI 属 P2，届时用高德行政区 API（geocodes + district 接口有 street 级）或 webmap.cn 数据补。
- 所有 DataV 坐标是 GCJ-02。**复用后端转换**（datav_service 已有 gcj02_to_wgs84 + 磁盘缓存），不要在前端再实现一份——这是项目踩过的坑（README「第三阶段优化」：重复 GCJ-02 转换代码导致 5 倍过度修正）。

---

## 5. 2D/3D 共享状态架构（核心设计）

### 5.1 目标架构

```
                       GIS Project State（工程持久化，已有 CAS 结构，扩展字段）
                                  │
                        ┌─────────┴──────────┐
                        │   GIS.state（新）    │   ← 唯一运行时状态源 + Pub/Sub
                        │  layers / selection │
                        │  view / drill / viz │
                        └─────────┬──────────┘
              ┌───────────────────┼─────────────────────┐
        Renderer: Leaflet     Renderer: Cesium       UI: 面包屑/属性面板/图层面板
        （map.js 改造）        （renderer_cesium.js 新） （layers.js 改造）
              └────── 事件回写 state（select/hover/camera）──────┘
                        ▲
                 Agent 通道（不变）
     tools.py: _push_layer/_register_layer/layer_ops → /api/chat → chat.js → state.dispatch
```

### 5.2 LayerRecord 数据结构（2D/3D 通用）

```js
{
  layer_id: 'ai_1727...',        // 已有，稳定
  name: '湖南省_市',              // 显示名（可重名）
  source: 'ai' | 'upload' | 'draw' | 'datav',
  data: FeatureCollection,       // WGS-84 GeoJSON（唯一数据真身）
  crs: 'EPSG:4326',              // 显式化（现状是隐式约定）
  bbox: [w, s, e, n],
  featureCount: 14,
  visible: true,
  opacity: 1.0,
  style: { color, fillColor, fillOpacity, weight } | { symbology: {...} },
  metadata: { level: 'province', adcodeField: 'adcode', parentAdcode: 100000 },  // 下钻所需
}
```

**Feature ID 方案**（解决跨渲染器身份）：`_register_layer`（tools.py:339）注册时为每个 feature 注入 `_fid`（有 `adcode`/`name`/`id` 属性时用稳定值 `p:430000`，否则用坐标+属性哈希，最后兜底 index）。前端 `_featureMap` 键从 `name:idx` 改为 `layer_id:_fid`。成本极低，收益是选中/同步/撤销全链路稳定。

### 5.3 2D↔3D 同步原则（回答「同步什么、不同步什么」）

| 同步（GIS 数据状态） | 不同步（Renderer 私有） |
|---|---|
| selectedFeature / hover 高亮 | 相机视角（唯一例外：选中时**单向** flyTo 定位到对方视图） |
| 图层增删/显隐/顺序/重命名 | Leaflet 的 Draw/编辑会话状态 |
| 样式（颜色/透明度/符号化配置） | Cesium 的 heading/pitch/exaggeration |
| 下钻栈与面包屑 | 瓦片缓存、LOD |
| 图例/可视化 spec | 帧率优化内部状态 |

实现：`GIS.state` 只发 `{type, payload}` 动作，两个 Renderer 各自订阅并 diff 自己的表示。**主动权在状态，Renderer 是纯函数式视图**——这与 GeoLibre「一个引擎两个投影」不同（见 §6），但同样把渲染器当无状态消费者。

---

## 6. GeoLibre（opengeos / 吴秋生）调研结论

已核查 GitHub 仓库 opengeos/GeoLibre 与 geolibre.app 文档站（Reference: Architecture / Project format / Cesium Renderer 等）：

1. **技术栈**：Tauri v2 + React + TypeScript + **MapLibre GL JS** + DuckDB-WASM Spatial + deck.gl + WhiteboxTools WASM（1000+ 分析工具跑在浏览器/桌面端）。
2. **GeoLibre 不用 Cesium 做 3D**。它的「2D+3D」来自 **MapLibre GL JS v5 的 globe 投影**（maplibre-gl-js v5.0.0, 2025-01：globe mode #3963、globe terrain #4976、GlobeControl）+ deck.gl 图层（含 Tile3DLayer 渲染 3D Tiles）。即：**一个引擎、两种投影**，而不是两个引擎共享状态。这回答了「GeoLibre 为什么可以同时处理 2D 和 3D」——它规避了双引擎同步问题，代价是没有 Cesium 级别的实体/picking/地形生态。
3. **状态组织**：React 组件树持有项目/图层状态，Project format 是文件化规范（与 GIS-WorkTable 的 project.json 定位相同）；分析跑 DuckDB-WASM（GIS-WorkTable 是 Python 后端，不需要这层）。
4. **吴秋生系列的可借鉴思想**（geemap/leafmap 的核心模式）：
   - **渲染器无关的图层记录 + 每渲染器适配器**（leafmap 支持 folium/ipyleaflet 多后端，同一份 layer 定义各自渲染）→ 直接印证 §5 的 adapter 设计；
   - 工具按「分析在计算层、呈现分层」解耦；
   - 他的文档站把 Cesium Renderer 列为可选渲染引擎之一，说明**轻量 GIS 平台把 Cesium 当作「重 3D 可选件」而非默认**——GIS-WorkTable 也应把 Cesium 按需加载（点「3D」才拉取脚本）。
5. **不适用的部分**：Tauri/React/DuckDB 与本项目原生 JS + Python 后端架构无关；GeoLibre 没有解决「Agent 生成结果→渲染」的通道（GIS-WorkTable 的 `_push_layer` 通道反而更成熟）。

---

## 7. CesiumJS vs Cesium Ion（必须回答的问题）

**CesiumJS**（`npm i cesium` / 本地静态文件，Apache-2.0 开源）与 **Cesium Ion**（商业云服务：Bing 影像代理、Cesium World Terrain、OSM Buildings、geocoder、资产托管）是两个东西。**CesiumJS 可 100% 独立运行**，Viewer 默认值里藏着的 Ion 依赖需要显式关掉：

```js
const viewer = new Cesium.Viewer(container, {
  baseLayer: Cesium.ImageryLayer.fromProviderAsync(
    Cesium.UrlTemplateImageryProvider({ url: '本地或天地图 XYZ', credit: '...' })
  ),        // 默认是 Ion World Imagery（需 token）—— 必须覆盖
  baseLayerPicker: false,   // 默认列表含 Ion imagery
  geocoder: false,          // 默认走 Ion geocoder
  // terrainProvider 默认 EllipsoidTerrainProvider，无 Ion 依赖，不用动
  sceneModePicker: true, timeline: false, animation: false, homeButton: false,
});
// 不要调用 Cesium.Ion.defaultAccessToken = ...；整个应用不引用 Ion 资源即零依赖
```

| 能力 | 无 Ion 方案 |
|---|---|
| Globe + 矢量 | ✅ 本来就是本地的 |
| GeoJSON | ✅ `GeoJsonDataSource.load(本地对象/URL)` |
| Imagery | ✅ `UrlTemplateImageryProvider`(XYZ) / `WebMapTileServiceImageryProvider`（天地图）/ `SingleTileImageryProvider`（单图）/ 本地瓦片目录 |
| Terrain | ✅ 自托管 quantized-mesh（CTB 转换）或 `ArcGISTiledElevationTerrainProvider`；默认椭球够 MVP |
| 3D Tiles | ✅ 静态 tileset.json 自托管 |
| Geocoder | ❌ 换高德/天地图地理编码（后端已有 amap_geocode 工具） |
| OSM Buildings / 全球精地形 | ⚠️ 这些成品在 Ion 上（免费层可用），自建可替代但费工 |

Ion 何时有价值：想要开箱即用的全球地形/建筑/影像且接受外部服务。**对面向学生/开源的 GIS-WorkTable：默认零 Ion；可在设置面板提供「Ion 增强」可选开关（用户自己的 token）。** 体积注意：Cesium 分发约 30-40MB（Workers/Assets/Widgets），Electron 桌面端本地加载无感；Web 模式按需 script 注入。

---

## 8. 中国 GIS 数据源与合规

### 8.1 数据源总表（★=建议 MVP 直接采用）

| 数据 | 来源 | 格式 | CRS | 更新 | 精度 | 许可 | 学术 | 商业 |
|---|---|---|---|---|---|---|---|---|
| ★行政区划（国/省/市/区县） | 阿里 DataV.GeoAtlas（已集成 `datav_service.py`） | GeoJSON | GCJ-02（后端已转 WGS84） | 不定期（跟随民政部区划） | 中（可视化级） | 无正式授权文档，免费开放接口；属演示服务，有下线风险（需缓存兜底，项目已做 `cache/aoi/`） | ✅ | ⚠️ 灰色（建议仅展示用途） |
| ★行政区划（官方底图） | 天地图 tianditu.gov.cn（Web API key 免费） | API/瓦片 | CGCS2000 公开加密 | 官方维护 | 官方 | 开发者许可，非商用免费、商用需授权 | ✅ | ⚠️ 需审批 |
| 基础地理 | 全国地理信息资源目录服务 webmap.cn（1:100万公众版） | SHP/GDB | CGCS2000 | 版本制 | 1:100万 | 公众版免费下载，署名、不得转让 | ✅ | ⚠️ |
| 行政边界（全球） | Natural Earth | SHP/GeoJSON | WGS84 | 稳定 | 1:10m（粗） | Public Domain | ✅ | ✅ |
| 行政边界（全球） | OSM / Geofabrik 中国抽取 | GeoJSON/PBF | WGS84 | 持续 | 城市好、乡镇弱 | ODbL（署名+同方式共享） | ✅ | ✅（注意 share-alike） |
| 行政边界（全球） | GADM | SHP/GeoJSON | WGS84 | 4.x | 中 | 仅学术非商业；**中国边界表达（台湾/藏南等）有严重合规问题，禁止用于境内公开展示** | ⚠️ | ❌ |
| ★POI | 高德 Web API（已集成） | JSON | GCJ-02 | 实时 | 高 | 免费配额；**条款禁止存储/批量导出 POI 结果** | ✅（实时查询） | ⚠️ |
| POI/路网（开放） | OSM | PBF | WGS84 | 持续 | 中国城市覆盖尚可 | ODbL | ✅ | ✅ |
| ★路网 | OSM via osmnx（已集成） | — | WGS84 | 持续 | — | ODbL | ✅ | ✅ |
| ★DEM | Copernicus DEM GLO-30 | GeoTIFF | WGS84 | 2021 基准 | 30m | 免费开放（Copernicus 许可，可商用） | ✅ | ✅ |
| DEM | SRTM 30m（gscloud.cn 有镜像） | GeoTIFF | WGS84 | 2000 | 30m | NASA Public Domain | ✅ | ✅ |
| ★土地利用 | ESA WorldCover 10m | GeoTIFF | WGS84 | 2020/2021 | 10m | CC-BY 4.0 | ✅ | ✅（署名） |
| 土地利用 | ESRI 10m Land Cover | GeoTIFF | WGS84 | 年度 | 10m | CC-BY 4.0（Esri 条款） | ✅ | ✅（署名） |
| ★人口栅格 | GHSL (JRC) / WorldPop | GeoTIFF | WGS84 | 年份制 | ~100m/1km | CC-BY 4.0（GHSL）/ CC-BY 3.0/4.0（WorldPop） | ✅ | ✅ |
| ★人口/GDP 表格 | 七普分县公报、各市统计公报（表格 → adcode join） | CSV | — | 2020/年度 | 官方统计 | 公开统计资料 | ✅ | ✅ |
| 夜光(GDP proxy) | VIIRS DNB (NOAA/EOG) | GeoTIFF | WGS84 | 月度 | ~500m | 免费、署名 | ✅ | ⚠️（EOG 条款） |
| ★气象 | ERA5 / Open-Meteo（已集成） | NetCDF/JSON | WGS84 | 小时/实时 | 9-25km | Copernicus 免费开放 / Open-Meteo CC-BY（非商业） | ✅ | ⚠️（OM 商用收费） |
| ★卫星影像 | Sentinel-2 / Landsat（已集成） | GeoTIFF | WGS84 | 5/16天 | 10-30m | Copernicus 免费开放 / USGS Public Domain | ✅ | ✅ |
| 卫星（国内） | 高分一号/六号 16m（CRESDA） | GeoTIFF | — | 按日 | 16m | 注册免费下载国内区域 | ✅ | ⚠️ |
| 瓦片底图 | 天地图 xyz/wmts（推荐默认底图）、Bing/Esri（现状） | 瓦片 | CGCS2000加密 / WGS84 | — | — | 见上 | — | — |
| 3D Tiles | 自托管（3d-tiles-tools 转换）| 3D Tiles | ECEF | — | — | 取决于源数据 | — | — |

### 8.2 中国国情三件事（必须写进实现）

1. **GCJ-02 偏移**：DataV/高德/百度 = GCJ-02；OSM/Sentinel/DEM/天地图(CS2000加密≈WGS84 级) = 无偏。规则：**所有入库数据统一 WGS-84（后端转换），GCJ-02 只存在于外部 API 调用瞬间**。项目已有 `geo_coords.py`，继续执行；天地图瓦片与 WGS84 矢量基本对齐，高德瓦片永远不要直接叠 WGS84 矢量。
2. **审图号/地图公开合规**（《地图管理条例》）：境内向社会公开的中国地图原则上需审图号。开源项目在 GitHub 展示属灰色地带，但**境内部署/演示时**应：① 默认底图用天地图或标准地图服务（自带审图号）；② 行政边界标注「示意图，非精确边界」；③ 不做导航/权属用途。建议在 `README` 与页面 attribution 中加一行免责声明（项目已有瓦片版权声明，扩展即可）。
3. **DataV 服务可靠性**：它是可视化演示接口，无 SLA。对策（已在做+加强）：磁盘缓存已有；建议把「中国省级 `_full.json`」等关键层随仓库/首次运行预缓存，防止接口变动导致下钻功能整体失效。

---

## 9. Agent → GIS Tool → Visualization Spec → Renderer（回答第十二节）

**结论：架构合理，且 GIS-WorkTable 已有 80% 的管线。** 现状：Agent 工具返回字符串给 LLM、副作用通过 `_pending_layers/_pending_layer_ops` 下发，前端 chat.js switch 分发——这本质就是一个朴素 VisSpec 协议，只是 op 类型少（remove/toggle/set_color/set_style/rename/fit/center/…）。要做的是**把协议升级为声明式 VisSpec**，而不是新起炉灶：

```jsonc
// 新增 layer_ops op 类型："visualize"（后端 tools.py 新工具 visualize_regions 产出）
{
  "action": "visualize",
  "layer": "湖南省_市",
  "viz": {
    "type": "extrusion",          // extrusion | choropleth | proportional_point
    "field": "population",
    "colorRamp": "blues",
    "heightScale": "normalized",  // 归一化后映射到 [minHeight, maxHeight]
    "maxHeight": 300000           // 米
  },
  "selection": { "field": "gdp", "operator": "max" }   // 可选：自动选中/高亮极值
}
```

- **Agent 不碰渲染器**：工具只负责「空间连接/统计 → 把数值 join 到行政区 GeoJSON 属性 → 发 visualize op」，符合现有 `spatial_graduated_colors`（tools.py:3599）的分工，只是多了 3D 维度（extrusion）。
- **前端**：`chat.js` 的 switch 增加 `visualize` 分支 → `GIS.state.applyVisualization(layerId, viz)` → Leaflet 适配器应用颜色/半径（复用 `applySymbology`），Cesium 适配器应用 extrudedHeight + 材质。**同一 spec，两种呈现**。
- **安全模型不变**：spec 由确定性代码执行（不 eval），LLM 只产出受限 schema（工具函数签名约束 + docstring），不存在「AI 直接操作 DOM」。
- 用户示例「显示湖南省各市人口」的完整链路：`datav_boundary('湖南省')` → `spatial_join/字段统计`（已有）→ `visualize_regions(layer, field='population', type='extrusion')` → op 下发 → 2D 染色 + 3D 拉伸 → `select {max}` 高亮岳阳市/长沙市（按真实数据）。

---

## 10. 技术选型对比（第十三节）

| 技术 | 2D | 3D Globe | Terrain | 3D Tiles | GIS 语义 | 难度 | React | 自有数据 | Agent 集成 |
|---|---|---|---|---|---|---|---|---|---|
| Leaflet（现状） | ★★★（插件生态） | ✗ | ✗ | ✗ | 中 | 已熟练 | 无关 | ✅ | ✅ 已集成 |
| Mapbox GL JS | ★★★ | ✅（globe 已回归） | ✅ | 需 deck.gl | 中 | 低 | 无关 | ⚠️瓦片绑定服务 | ✅ |
| **CesiumJS** | △（SceneMode 不替代专业 2D） | ★★★ | ★★★（自托管可） | ★★★ 原生 | ★★（Entity=Feature 概念） | 中 | 无关（resium 可选） | ✅ 完全本地 | ✅ JSON 可控 |
| Three.js | ✗ | 自建 | 自建 | 自建 | ✗（一切自建） | 极高 | 无关 | ✅ | ✗ 全部自研 |
| deck.gl | 叠加层 | △（依附底图） | △ | ✅ Tile3DLayer | ★★ | 中 | 无关 | ✅ | ✅ |
| MapLibre GL JS v5 | ★★★ | ★★（globe 新，2025-01） | ★★（globe terrain 新） | 需 deck.gl | 中 | 低 | 无关 | ✅ | ✅ |

**为什么是 Cesium**：
1. GIS-WorkTable 的 2D 已经被 Leaflet 深度占用（Draw/VectorGrid/heat/属性联动），换 2D 引擎 = 重写工作台，收益不成比例；
2. 3D 需求里权重最高的「数据驱动 extrusion + 成熟 picking + 未来 DEM/3D Tiles」正是 Cesium 的原生强项，MapLibre globe 尚年轻（terrain-in-globe 2025 年才落地），deck.gl 方案需要同时维护底图与叠加层的坐标/相机一致性；
3. Three.js 一切自建，与「AI 工作台」目标完全错位；
4. Cesium Entity 模型（properties/picking/material）与 GeoJSON Feature 概念几乎一一对应，Agent 产出的 GeoJSON 零转换进 3D——这是 deck.gl/Three 不具备的开发效率。
5. 许可 Apache-2.0，与项目 AGPL-3.0 无冲突。

---

## 11. 当前代码修改点清单（最重要部分）

> 每项含：文件 → 修改原因 → 修改内容 → 风险 → 是否需要重构。

### 新建文件（3 个）

**① `frontend/js/gis_state.js`（新建，约 300 行）**
- 原因：状态收敛，2D/3D/UI 共同数据源（§5）。
- 内容：`GIS.state` —— layers 有序 Map、selection、drill 栈、viz specs；`dispatch(action)` + `subscribe(selector, cb)` 极简 pub/sub；动作：`addLayer/removeLayer/setVisible/setStyle/selectFeature/drillDown/drillUp/applyVisualization/setView`。
- 风险：无（纯新增）。
- 重构：是（这是本次的架构中枢）。

**② `frontend/js/renderer_cesium.js`（新建，约 500 行）**
- 原因：3D 渲染适配器。
- 内容：懒加载 Cesium 脚本（`window.CESIUM_BASE_URL` 指向本地 `frontend/vendor/cesium/`，Ion 零依赖初始化见 §7）；订阅 state → `GeoJsonDataSource` 增删/显隐/样式 diff；`scene.pick` 点击 → `state.selectFeature`；`Rectangle.fromDegrees(bbox)` flyTo；extrusion/choropleth 渲染；与 Leaflet 互斥挂载（同容器切换，省内存）。
- 风险：Cesium 体积（按需加载规避）；WebGL 上下文与 Leaflet Canvas 并存于互斥切换下无冲突。
- 重构：否（新增模块）。

**③ `frontend/vendor/cesium/`（构建产物拷贝，不进 git 或用 LFS）**
- 内容：`Build/Cesium/*`（Workers/Assets/Widgets/ThirdParty）。Electron/Web 均本地服务。
- 风险：仓库体积；建议提供 `scripts/fetch_cesium.py` 下载脚本。

### 修改文件（6 个）

**④ `frontend/js/map.js`**
- 原因：Leaflet 成为 state 的订阅者，而非状态持有者；要素身份稳定化。
- 内容：
  - `loadGeoJSON/removeLayer/setLayerVisible/setLayerStyle/applySymbology`（map.js:434/541/563/594/1182）保留实现，但入口改为由 `GIS.state` 驱动（state diff → 调这些函数），同时把点击选中回调（map.js:502-527 与 1234-1253 两处 onEachFeature click）改为 `GIS.state.selectFeature(layerId, fid, feature)`，弹窗逻辑移到属性面板统一处理；
  - `_featureMap` 键 `name:idx` → `layer_id:_fid`（`highlightLayerFeature` map.js:703 同步改）。
- 风险：**本文件改动面最大**。分两步走：P0 先做「state 同步写 + 点击回写」，渲染实现不动（增量、可回归）；P1 再把 geoStore 收编。
- 重构：部分（渐进式，不阻塞 MVP）。

**⑤ `frontend/js/layers.js`**
- 原因：`layerData` 与 `_symbologyConfig` 上移进 state，避免双份真身。
- 内容：`addLayer/removeLayer/toggleVisibility/downloadLayer/showLayerInspector`（layers.js:132/154/179/193/628）改读 `GIS.state.layers`；`_symbologyConfig` 存入 layer.style；`_applyStyleToMap`（layers.js:1408）改为同时分发到两个 Renderer。
- 风险：与 map.js 改动耦合，需要同一批回归（图层面板操作、属性表定位、符号化）。
- 重构：同上，渐进式。

**⑥ `frontend/js/chat.js`**
- 原因：Agent 产物的统一入口。
- 内容：`result.layers` 处理（chat.js:1225-1298）改为 `GIS.state.addLayer(...)` 单一调用（保留重试包装）；layer_ops switch（chat.js:1150-1212）新增 `visualize`、`drill`（drill_down/drill_up 工具回传）两个分支。
- 风险：低（增量分支）。
- 重构：否。

**⑦ `frontend/index.html`**
- 原因：加载新模块与 Cesium。
- 内容：script 顺序 `gis_state.js` → `map.js` → … → `renderer_cesium.js`（懒加载则只加 gis_state/renderer 壳）；地图容器旁加 2D/3D 切换按钮与面包屑容器；Cesium CSS。
- 风险：无。
- 重构：否。

**⑧ `backend/services/tools.py`**
- 原因：为 Agent 提供下钻与 3D 可视化能力；要素身份稳定化。
- 内容：
  - `_register_layer`（tools.py:339）为每个 feature 注入 `_fid`，并在注册表里加 `metadata`（level/adcode 探测：看 properties 里有无 `adcode`+`level`）；
  - 新增工具 `drill_down(region)` / `drill_up()` / `list_drill_levels()`：内部复用 `datav_service.fetch_boundary`，push 子级图层 + `_pending_layer_ops` 发 `drill` op（携带 adcode/bbox 让前端状态机对齐）；
  - 新增工具 `visualize_regions(layer_name, field, type='extrusion'|'choropleth', color_scheme, max_height)`：数值归一化后发 `visualize` op（§9 schema）。
  - 三个工具名加入 `tools` 列表 + docstring 按规范 + 对应 pytest（项目有工具注册守卫测试，漏注册会被抓）。
- 风险：中低。注意工具返回字符串的 token 成本（返回摘要而非全量数据）。
- 重构：否（新增 + 小改 `_register_layer`）。

**⑨ `backend/services/datav_service.py`**
- 原因：下钻数据可靠性。
- 内容：`fetch_boundary` 增加按 adcode 直取的公开签名（现在按名称）；预置省级 `_full.json` 的首次运行预热；区县级已有，街道级 P2 再议。
- 风险：低。
- 重构：否。

### 不需要改的
`backend/main.py`（layers/layer_ops 通道原样够用）、`project_service.py`（字段向后兼容，P1 再加 style/crs 持久化）、`graph.py`/`ai_service.py`（工具自动注册即生效）、`desktop/main.js`（Electron 对 Cesium 本地文件友好，仅需确认 file:// 或 http 均可）。

---

## 12. MVP 实施计划

### P0 —「能看、能点、能钻」（建议 1-2 周）
范围严格限定：**Globe + GeoJSON + 省级 + Click + Highlight + 属性 + Drill-down + 面包屑 + 2D↔3D 选中同步**。
1. `gis_state.js`（layers/selection/drill + pub/sub）
2. Leaflet 接入 state（点击回写、加载走 state）—— 不改渲染实现
3. `renderer_cesium.js` 最小版：零 Ion Viewer、GeoJsonDataSource、pick 选中、flyTo bbox
4. `drill_down/drill_up` 后端工具 + DataV 预缓存
5. UI：2D/3D 切换按钮、面包屑、右侧属性面板（复用 inspector 样式）
6. 验收剧本：打开 3D → 全球 → 点击湖南省 → 高亮+属性 → 下钻出 14 个市 → 点击长沙市 → 继续下钻到区县 → 面包屑逐级返回 → 切到 2D，选中状态一致。

### P1 —「数据驱动可视化 + Agent 联动」（再 1-2 周）
1. `visualize` op + 前端 `applyVisualization`（2D 染色 + 3D extrusion）
2. `visualize_regions` Agent 工具（join 统计值 → spec）
3. 图层显隐/样式/透明度双端同步；`_fid` 全链路
4. 工程 save/load 扩展（style、crs、drill 栈可选持久化）
5. `focus_map` 兼容 3D（flyTo 双发）

### P2 —「真 3D 资产」（按需）
1. 本地 DEM → quantized-mesh 地形（CTB 转换脚本），与现有 DEM 工具链打通（坡向/晕渲在 3D 中呈现）
2. 天地图 XYZ 作为 Cesium 默认底图（含审图号合规）；Bing/Esri 复用现状
3. 3D Tiles 自托管（OSM Buildings 自转 / 城市白模）；EntityCluster 用于 POI 层
4. 街道级下钻（高德 district API 补数据）
5. 时间动画（time_animation op）在 3D 的等价实现

### 明确不做（第一、二阶段）
- 用 Cesium SceneMode 替代 Leaflet；CZML；粒子/天气； Ion 托管资产依赖；React 化改造；替换项目状态为 Redux 类框架（原生 JS 保持一致）。

---

## 附录 A：风险登记

| 风险 | 等级 | 缓解 |
|---|---|---|
| map.js/layers.js 状态迁移引入回归 | 高 | P0 只做「同步写+事件回写」，渲染实现不动；现有 366 项测试 + 手工回归清单 |
| DataV 接口变动/下线 | 中 | 磁盘缓存已有 + 省级数据预缓存 + 预留 webmap.cn 备源 |
| Cesium 首载体积（Web 模式） | 中 | 懒加载脚本；Electron 本地无感 |
| Leaflet+WebGL 内存 | 低 | 视图互斥切换（卸载不销毁，挂起恢复） |
| 合规（审图号/边界） | 中 | 天地图默认底图选项 + 免责声明 + 「示意图」标注 |
| 中期被 MapLibre globe 反超 | 低 | adapter 架构保证 Renderer 可替换（这正是共享状态的第二收益） |

## 附录 B：参考资料
- CesiumJS 文档：GeoJsonDataSource / Viewer (ConstructorOptions: baseLayer, geocoder, terrainProvider…) — cesium.com/learn/cesiumjs/ref-doc
- MapLibre GL JS v5.0.0 Release Notes（globe mode #3963, terrain in globe #4976, GlobeControl #4960）
- opengeos/GeoLibre（GitHub README、geolibre.app/docs Reference：Architecture / Project format / Renderers）
- 《地图管理条例》（国务院令第 664 号）；自然资源部标准地图服务
- Copernicus/ESA/USGS/NOAA 数据许可页（各数据源官方条款）
