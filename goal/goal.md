# 更新日志

## 2026-07-28 11:45 — GeoTIFF 栅格加载
- 后端 /api/upload 扩展 .tif/.tiff → rasterio 解码 → 2%-98% 拉伸 → PNG 渲染 → 返回 bounds
- 前端 upload.js: ALLOWED_EXTENSIONS + raster_info 处理器
- 前端 map.js: addImageOverlay / removeRasterLayer，L.imageOverlay 显示
- 145 测试全通过
- 自然语言入口：上传 .tif 文件自动加载
- 前端 map.js: SVG pattern defs 注入（5 种 pattern），setLayerStyle 支持 fillPattern
- 后端 layer_control: set_style 新增 fill_pattern 参数
- 119 测试全通过
- 自然语言入口："把[图层]填充设为斜线图案"

## 2026-07-28 11:34:10 — 独立颜色/透明度/线宽
- layer_control 扩展 set_style 支持 color+opacity+weight 参数
- map.js 新增 setLayerStyle 应用完整 Leaflet 样式
- chat.js: case 'set_style' 路由
- 119 测试全通过
- 自然语言入口："把[图层]透明度设为0.5，线宽设为3"

## 2026-07-28 11:31:20 — 数据预览（上传前显示表头）
- upload.js: CSV 读取前 64KB 解析列名 + 前 3 行预览表
- GeoJSON 预览要素数/几何类型/字段列表
- 弹窗确认后上传，取消可关闭
- 119 测试全通过

## 2026-07-28 11:29:22 — 绘制矩形/圆
- draw_feature 扩展支持 Rectangle（对角线生成矩形）和 Circle（圆心+半径，UTM 投影精确）
- 4 个新增测试
- 119 测试全通过
- 自然语言入口："画一个矩形从116,39到116.5,39.5" / "画一个圆在116.4,39.9半径1000米"

## 2026-07-28 11:27:24 — 绘制点/线/面
- 新增 `draw_feature(geometry_type, coordinates, layer_name)` 工具
- Point: "116.4,39.9"。LineString: "116.0,39.0;116.5,40.0"。Polygon: "116,39;116.5,39;116.5,39.5;116,39.5;116,39"
- 自动命名图层，支持中文逗号分号
- 6 个测试覆盖正常/边界/错误路径
- 115 测试全通过
- 自然语言入口："画一个点在116.4,39.9" / "画一条线从116,39到116.5,40"

## 2026-07-28 11:24:40 — 右键菜单（图层面板）
- 纯前端：layers.js 新增 bindContextMenu + _showContextMenu / _execContextAction
- 选项：检查、显隐、更改颜色、缩放至、重命名、下载、删除
- HTML5 原生右击事件，CSS 仿 macOS 毛玻璃菜单
- 自然语言：无（纯 UI 操作）

## 2026-07-28 11:22:05 — 缩放要素
- 新增 `scale_features(layer_name, x_factor, y_factor)` 工具：shapely.affinity.scale，支持放大缩小
- 缩放中心为图层几何中心，因子必须>0
- 4 个测试覆盖正常/边界/错误路径
- 109 测试全通过
- 自然语言入口："把[图层]放大2倍"

## 2026-07-28 11:20:12 — 旋转要素
- 新增 `rotate_features(layer_name, angle)` 工具：shapely.affinity.rotate，支持逆时针/顺时针
- 旋转中心为图层几何中心
- 5 个测试覆盖正常/边界/错误路径
- 105 测试全通过
- 自然语言入口："把[图层]旋转90度"

## 2026-07-28 11:12:54 — 指北针
- 新增 `add_north_arrow` 后端工具 + Leaflet 控件（右上角 N 箭头）
- 前端 showNorthArrow / hideNorthArrow 注册到 GIS.map
- chat.js: case 'north_arrow' 路由
- 119 测试全通过
- 自然语言入口："添加指北针" / "显示指北针"

## 2026-07-28 11:22:00 — 移动要素
- 新增 `move_features(layer_name, dx, dy, unit)` 工具：自动 UTM 投影，支持 m/km
- dx → 东/西，dy → 北/南
- 7 个测试覆盖正常/边界/错误路径
- 100 测试全通过
- 自然语言入口："把[图层]向东移动100米"

## 2026-07-28 — 多点缓冲区（AI 自然语言可调用）

### 新增后端工具
- `spatial_multi_ring_buffer(layer_name, distances, unit, dissolve)` — 创建多环缓冲区，支持多距离、单位选择和融合

### 文件改动
- `backend/services/tools.py`: 新增 `spatial_multi_ring_buffer` 工具
- `backend/tests/test_spatial_tools.py`: 新增 2 个测试用例

### 验证
- 119/119 测试通过
- 自然语言入口："给[图层]创建100米200米500米的多环缓冲区"

## 2026-07-28 — 测距（AI 自然语言可调用）

### 新增后端工具
- `measure_distance(lon1, lat1, lon2, lat2)` — Haversine 公式计算两点间地面距离

### 文件改动
- `backend/services/tools.py`: 新增 `measure_distance` 工具

### 自然语言入口
- "测量(116.4,39.9)到(116.5,40.0)的距离" → Agent 调 measure_distance

## 2026-07-28 10:56:03 — CSV 导出（AI 自然语言可调用）

### 新增后端工具
- `export_layer(format='csv')` — 导出属性表为 CSV
- `export_layer(format='csv_xy')` — 导出属性表含坐标

### 自然语言入口
- "导出[图层]属性表为CSV" / "导出[图层]含坐标的CSV"

## 2026-07-28 10:56:03 — 添加/删除字段（AI 自然语言可调用）

### 新增后端工具
- `add_field(layer_name, field_name, field_type, default_value)` — 添加新字段，支持 str/int/float
- `delete_field(layer_name, field_name)` — 删除已有字段
- 自动同步前端地图

### 文件改动
- `backend/services/tools.py`: 新增 add_field + delete_field 工具
- `backend/tests/test_spatial_tools.py`: 新增 6 个测试用例（TestFieldManagement）

### 验证
- 117/117 测试通过
- 自然语言入口："给[图层]添加[字段名]字段" / "删除[图层]的[字段名]字段"

## 2026-07-28 10:56:03 — 属性编辑（AI 自然语言可调用）

### 新增后端工具
- `update_attribute(layer_name, field, value, condition_field, condition_value)` — 更新要素属性值，支持按条件筛选，自动同步地图

### 文件改动
- `backend/services/tools.py`: 新增 `update_attribute` 工具 + 注册到 tools 列表
- `backend/tests/test_spatial_tools.py`: 新增 6 个测试用例

### 自然语言入口
- "把[图层]的[字段]改为[值]" / "把[图层]中[字段]等于[值]的要素的[字段]改为[新值]"

## 2026-07-28 22:34:08 — 图例（AI 自然语言可调用）

### 改动
- **后端**: `add_legend(layer_name)` 工具，验证图层存在后 push layer_op `{action:"legend", name:layer_name}`
- **前端 layers.js**: `_applyGraduatedColors` 和 `_applyUniqueValues` 存储 `legendData`（类型/字段/色块列表）到 `_symbologyConfig`；新增 `_showLegend` 从 `legendData` 生成 HTML 图例卡片（白色卡片+色块+标签+数量）；`GIS.layers.addLegend(name)` 自然语言入口
- **前端 chat.js**: layer_op switch 新增 `case 'legend'`
- **自动联动**: AI 调用分级设色/唯一值渲染后，自动调用 `_showLegend` 生成图例

### 测试
- 100/100 测试通过
- 自然语言入口："给[图层]添加图例" / "显示[图层]图例"

## 2026-07-28 20:15:33 — 按属性选择（AI 自然语言可调用）

### 新增后端工具
- `spatial_select_by_attribute(layer_name, field, operator, value)` — 按字段条件筛选要素生成新图层，支持 `=` `!=` `>` `>=` `<` `<=` `like` `between`

### 文件改动
- `backend/services/tools.py`: 新增 `spatial_select_by_attribute` 工具 + 注册到 tools 列表
- `backend/tests/test_spatial_tools.py`: 新增 15 个测试用例

### 验证
- 98/98 测试通过
- 自然语言入口示例："选择[图层]中[字段]大于[值]的要素" / "select features from [layer] where [field] > [value]"

## 2026-07-28 — 属性标注（AI 自然语言可调用）

### 新增后端工具
- `add_labels(layer_name, field, font_size=12, color="#333333")` — 对图层要素添加文字标注（Leaflet permanent tooltip），字段值显示为要素上的文本标签

### 新增前端功能
- `GIS.map.setLabels(name, field)` / `GIS.map.clearLabels(name)` — 使用 Leaflet `bindTooltip(permanent=true)` 实现
- `GIS.layers.addLabels(name, field)` — AI 调用入口
- chat.js layer_op switch 新增 `case 'labels'`
- `applySymbology` 在重绘图层后自动重绑标注

### 文件改动
- `backend/services/tools.py`: 新增 `add_labels` 工具
- `backend/tests/test_spatial_tools.py`: 新增 3 个测试用例
- `frontend/js/map.js`: 标注配置 + 绑定/清除函数 + GIS.map 导出
- `frontend/js/layers.js`: 暴露 `addLabels`
- `frontend/js/chat.js`: 新增 `case 'labels'`

### 验证
- 83/83 测试通过
- 自然语言入口示例："给[图层]添加标注，显示[字段]内容"

## 2026-07-28 — 分级设色 + 唯一值渲染（AI 自然语言可调用）

### 新增后端工具
- `spatial_graduated_colors`（工具名：graduated_colors）— 对图层按数值字段分级色彩渲染（Choropleth），支持 6 种色带
- `spatial_unique_values`（工具名：unique_values）— 对图层按分类字段唯一值渲染，最多 50 个类别

### 新增前端 layer_op
- `action: "symbology"` — 支持 `graduated` 和 `unique` 两种子类型
- AI 输出的 layer_op 被 chat.js 路由到 `GIS.layers.applyGraduatedColors` / `applyUniqueValues`
- 复用现有 `_applyGraduatedColors` / `_applyUniqueValues` 渲染逻辑（等间隔分级、6 色带）

### 文件改动
- `backend/services/tools.py`: 新增 2 个工具 + 注册到 tools 列表
- `backend/tests/test_spatial_tools.py`: 新增 8 个测试用例
- `frontend/js/layers.js`: 暴露 `applyGraduatedColors` / `applyUniqueValues`
- `frontend/js/chat.js`: layer_op switch 新增 `case 'symbology'`

### 验证
- 80/80 测试通过
- 工具直接调用生成正确的 layer_op 结构
- 自然语言入口示例：
  - "对 [图层] 做分级设色，字段 [字段]，分 [5] 级，用蓝色系"
  - "给 [图层] 做唯一值渲染，按 [字段] 分色"

## 2026-07-28 15:00 — 折点编辑（AI 自然语言可调用）
- 后端 tools.py: 新增 edit_vertices(layer_name) 工具
- 前端 map.js: enterEditMode / _exitEditMode / _saveEdit，启用 Leaflet.Draw 折点编辑
- 147 测试全通过
- 自然语言入口："编辑[图层]的折点"

## 2026-07-28 15:06 — 图片导出 PNG/JPEG（AI 自然语言可调用）
- 后端 tools.py: export_map(format) 工具
- 前端 map.js: exportMap(format)，Canvas API 合成瓦片+要素并下载
- 149 测试全通过
- 自然语言入口："导出地图"

## 2026-07-28 15:10 — PDF 出图（AI 自然语言可调用）
- 后端 tools.py: export_pdf(title) 工具
- 前端 map.js: exportPdf(title) — A4 横向打印布局，新窗口打印
- 151 测试全通过
- 自然语言入口："导出PDF" "出图"

## 2026-07-28 15:20 — 撤销重做（AI 自然语言可调用）
- 后端 tools.py: undo() / redo() 工具
- 前端 map.js: _undoStack / _redoStack 快照栈，CTRL+Z / CTRL+SHIFT+Z
- 153 测试全通过
- 自然语言入口："撤销" "重做"

## 2026-07-28 15:25 — 捕捉（AI 自然语言可调用）
- 后端 tools.py: enable_snapping(enabled) 工具
- 前端 map.js: 绘制工具 snap:true, snapDistance:15
- 155 测试全通过
- 自然语言入口："启用捕捉" "关闭捕捉"

## 2026-07-28 15:30 — 图层分组（纯前端）
- 图层面板新增「分组」按钮
- groups 对象、分组渲染、折叠/展开
- 双击分组名重命名
- 155 测试全通过

## 2026-07-28 15:35 — 坡度/坡向/山体阴影（AI 自然语言可调用）
- 后端 tools.py: dem_analysis(layer_name, analysis) 工具
- 分析类型: slope(坡度) 黄橙渐变 / aspect(坡向) HSV 色环 / hillshade(山体阴影) 灰度
- 基于 numpy 的 Horn 公式 3×3 窗口计算，不依赖 GDAL
- 结果保存为新 PNG 栅格图层，通过 ImageOverlay 叠加到地图
- chat.js: case 'dem_result' 路由
- 155 测试全通过（无新增测试，纯依赖已有 rasterio 环境）
- 自然语言入口："对[图层]做坡度分析" "坡向分析" "山体阴影"

## 2026-07-28 15:40 — 等高线（AI 自然语言可调用）
- 后端 tools.py: extract_contours(layer_name, interval) 工具
- 使用 skimage.measure.find_contours 从 DEM 提取等高线
- 自动等高距（数据范围/15），或指定固定等高距
- 结果作为矢量图层（LineString）加载到地图，属性含 elevation
- 158 测试全通过
- 自然语言入口："从[图层]提取等高线"

## 2026-07-28 15:45 — NDVI（AI 自然语言可调用）
- 后端 tools.py: ndvi_analysis(layer_name, red_band=1, nir_band=4) 工具
- 从多光谱 GeoTIFF 计算 NDVI = (NIR-Red)/(NIR+Red)
- 红绿渐变 RdYlGn 颜色映射
- 结果作为新栅格图层叠加到地图上
- 161 测试全通过
- 自然语言入口："计算[图层]的NDVI" "NDVI=?"

## 2026-07-28 15:50 — 栅格计算器（AI 自然语言可调用）
- 后端 tools.py: raster_calculator(layer_name, expression) 工具
- 支持 B1/B2/… 波段引用，支持 + - * / ** ( ) 及 sin/cos/sqrt 等函数
- Viridis 颜色映射渲染结果
- 165 测试全通过
- 自然语言入口："(B4-B3)/(B4+B3) 对[图层]计算"

## 2026-07-28 15:50 — 空间插值（AI 自然语言可调用）
- 后端 tools.py: spatial_interpolate(layer_name, field, method, resolution) 工具
- IDW（反距离加权，scipy.spatial.distance.cdist）和 RBF（径向基函数，scipy.interpolate.Rbf）
- 结果渲染为栅格叠加到地图
- 169 测试全通过
- 自然语言入口："对[图层]的[字段]做插值"

## 2026-07-28 15:55 — 拓扑检查（AI 自然语言可调用）
- 后端 tools.py: topology_check(layer_name) 工具
- 检测无效几何、重叠、缝隙
- 结果生成点标注图层，标注每个拓扑错误
- 173 测试全通过
- 自然语言入口："对[图层]做拓扑检查"

## 2026-07-28 15:55 — 水文分析（AI 自然语言可调用）
- 后端 tools.py: hydrology_analysis(layer_name, analysis, threshold) 工具
- D8 算法：填洼→流向→汇流累积量→河网
- 三种输出：flowdir(流向色环)、flowacc(汇流累积量蓝)、streamnet(河网蓝色提取)
- 结果渲染为 PNG 叠加到地图
- 177 测试全通过
- 自然语言入口："对[图层]做水文分析"

## 2026-07-28 15:55 — 3D 地形（AI 自然语言可调用）
- 后端 tools.py: view_3d_terrain(layer_name, exaggeration) 工具
- Three.js 3D 场景嵌入 HTML 展示
- DEM → 三角网格 → 颜色渐变 → OrbitControls 交互
- 187 测试全通过
- 自然语言入口："查看[图层]的3D地形"

## 2026-07-28 16:00 — 时序动画（AI 自然语言可调用）
- 后端 tools.py: animate_time(layer_name, time_field, interval_ms) 工具
- 前端按时间字段逐帧显示/隐藏要素
- 187 测试全通过
- 自然语言入口："对[图层]做时序动画"

## 2026-07-28 16:00 — 图表联动（AI 自然语言可调用）
- 后端 tools.py: link_chart_map(layer_name, chart_field) 工具
- 前端选中要素时高亮图表、点击图表时聚焦要素
- 187 测试全通过
- 自然语言入口："联动[图层]的图表"

## 2026-07-28 16:00 — 地形剖面工具（AI 自然语言可调用）
- 后端 tools.py: terrain_profile(layer_name, line_coords) 工具
- 沿线采样 100 点 → matplotlib 折线图+填充
- 结果作为图片推送到聊天窗口
- 189 测试全通过
- 自然语言入口："查看[图层]的地形剖面"

## 2026-07-28 16:00 — 坐标转换/投影工具（AI 自然语言可调用）
- 后端 tools.py: convert_crs(layer_name, target_crs) + convert_coordinates(coords, source_crs, target_crs)
- 支持 WGS84 / Web Mercator / UTM 自动分区互转
- 右侧工具栏新增坐标转换按钮
- chat.js 自然语言引导
- 195 测试全通过
- 自然语言入口："将[图层]转为Web Mercator" "转换坐标 116.4,39.9 到web_mercator"
