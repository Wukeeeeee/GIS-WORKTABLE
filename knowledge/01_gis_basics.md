# GIS 基础知识

## 适用场景

本模块是所有 GIS 任务的基础参考。当 Agent 遇到以下情况时应查阅本模块：

- 用户首次上传数据，需要判断数据类型和质量
- 任务涉及矢量与栅格数据的区别和选择
- 需要理解几何类型（点/线/面）与属性数据的关系
- 空间分析前需要确认数据是否满足基本要求
- 用户询问 GIS 基础概念（如"什么是拓扑""属性表是什么"）

## 输入数据要求

### 矢量数据
- 格式：GeoJSON、Shapefile(.zip)、GeoPackage、KML/KMZ、GPX、DXF、CSV（经纬度转点）
- 必须包含有效的几何对象（Point / LineString / Polygon / Multi*）
- 建议包含属性字段（非必须，但空间连接、统计、符号化依赖属性）
- 坐标应为经纬度（WGS84 / EPSG:4326），若为投影坐标需先确认 CRS

### 栅格数据
- 格式：GeoTIFF（.tif / .tiff）
- 必须包含地理参考信息（仿射变换 + CRS），无坐标的纯图片无法做空间分析
- 单波段或多波段均可，DEM 应为单波段浮点型，遥感影像通常为多波段

### 数据质量最低要求
- 几何对象不能为空（`geometry` 不为 null）
- 坐标值在合理范围内（经度 -180~180，纬度 -90~90）
- 面要素环闭合、方向正确（Shapely 可自动修复部分问题）
- 属性表字段名无特殊字符、无重名

## 分析思路

GIS 分析的核心是"空间位置 + 属性"的联合处理。任何 GIS 任务都可以拆解为三个层次：

1. **数据层**：数据是什么格式？什么几何类型？什么坐标系？质量如何？
2. **空间层**：要素之间有什么空间关系？（相交、包含、邻近、重叠）
3. **属性层**：要素携带什么属性？需要做什么统计、计算、分类？

Agent 在接到任务时，应先判断任务属于哪一层或哪几层的组合，再选择对应工具。

## 处理流程

### 标准 GIS 任务处理流程

```
1. 数据接入
   ├─ 用户上传 → /api/upload 自动解析并注册图层
   ├─ AI 获取数据 → discover_gis_data / download_gis_data
   └─ 手动绘制 → draw_feature

2. 数据检查（必须步骤，不可跳过）
   ├─ get_registered_layers() 确认图层已加载
   ├─ get_layer_detail(layer_name) 查看几何类型、要素数、字段列表
   ├─ topology_check(layer_name) 检查几何有效性（面图层必做）
   └─ 若 CRS 不一致 → convert_crs 统一坐标系

3. 数据预处理（按需）
   ├─ 几何修复 → topology_check 自动修复无效几何
   ├─ 字段计算 → field_calculate
   ├─ 投影转换 → convert_crs
   └─ 格式转换 → export_layer

4. 空间分析（核心）
   ├─ 矢量分析 → spatial_buffer / spatial_intersect / spatial_join 等
   ├─ 栅格分析 → dem_analysis / ndvi_analysis / raster_calculator 等
   └─ 网络分析 → network_analysis

5. 结果验证
   ├─ get_layer_detail 检查输出图层要素数和字段
   ├─ measure_area / measure_distance 抽查结果合理性
   └─ spatial_field_stats 统计输出字段分布

6. 结果展示与导出
   ├─ 符号化 → spatial_graduated_colors / spatial_unique_values
   ├─ 图表 → create_chart
   ├─ 热力图 → create_heatmap
   └─ 导出 → export_layer / export_map / export_pdf
```

## 方法选择依据

### 矢量 vs 栅格：什么时候用哪种？

| 任务类型 | 推荐数据模型 | 原因 |
|----------|-------------|------|
| 精确边界、行政区域、宗地 | 矢量 | 边界清晰、属性丰富、面积计算准确 |
| 连续表面（温度、高程、降水） | 栅格 | 连续场天然适合栅格表示 |
| 路径分析、网络导航 | 矢量（网络） | 需要节点-边拓扑结构 |
| 土地覆盖分类、遥感影像 | 栅格 | 像素级分类和波段运算 |
| 点位密度、热点分布 | 矢量点 + 栅格密度 | 点是矢量，密度面是栅格 |
| 叠加分析（两个图层求交） | 矢量（overlay）或栅格（地图代数） | 精确边界用矢量，连续表面用栅格 |

### 几何类型选择

- **点（Point）**：表示零维地物（POI、采样点、城市位置）
- **线（LineString）**：表示一维地物（道路、河流、管线）
- **面（Polygon）**：表示二维地物（行政区、湖泊、土地利用斑块）
- 多部件（MultiPoint / MultiLineString / MultiPolygon）：同类地物的集合，如群岛、多段道路

### 空间关系判断（predicate 选择）

`spatial_select` 和 `spatial_join` 的 `predicate` 参数选择：

| predicate | 含义 | 典型场景 |
|-----------|------|---------|
| `intersects` | 有任何空间接触（最常用） | 查找落在研究区内的所有要素 |
| `within` | 完全在目标内部（边界不接触） | 严格筛选区内点 |
| `contains` | 目标完全在本要素内 | 面包含点/线 |
| `touches` | 仅边界接触，内部不重叠 | 找相邻行政区 |
| `overlaps` | 部分重叠（同维度） | 两个面图层的重叠区域 |
| `crosses` | 线穿过面/线 | 道路穿越行政区 |

## 推荐工具

### 数据管理
| 工具名 | 用途 |
|--------|------|
| `get_registered_layers` | 列出当前所有已加载图层 |
| `get_layer_detail` | 查看指定图层的几何类型、要素数、字段、bbox |
| `layer_control` | 图层显隐、重命名、颜色、透明度控制 |
| `layer_merge` | 合并多个同类型图层 |
| `layer_split` | 按字段拆分图层 |

### 数据检查与修复
| 工具名 | 用途 |
|--------|------|
| `topology_check` | 面图层拓扑检查（自相交、重叠、缝隙、无效几何），自动修复 |
| `convert_crs` | 图层坐标系转换 |
| `convert_coordinates` | 单点/多点坐标转换 |

### 属性操作
| 工具名 | 用途 |
|--------|------|
| `field_calculate` | 基于表达式计算新字段（安全表达式求值） |
| `add_field` / `delete_field` | 字段增删 |
| `update_attribute` | 按条件更新属性值 |
| `delete_features` | 按条件删除要素 |
| `spatial_select_by_attribute` | 按属性条件筛选要素 |
| `spatial_field_stats` | 字段统计（均值、最大最小、分位数等） |

### 空间分析入口
| 工具名 | 用途 |
|--------|------|
| `spatial_buffer` | 缓冲区分析 |
| `spatial_intersect` / `spatial_union` / `spatial_difference` | 叠置分析 |
| `spatial_clip` | 裁剪 |
| `spatial_join` | 空间连接 |
| `spatial_select` | 空间查询 |
| `spatial_centroid` | 质心提取 |
| `measure_area` / `measure_distance` | 量算 |

## 输出结果

GIS 分析的输出通常包含三类：

1. **空间数据**：新的 GeoJSON 图层（自动注册并推送到前端地图）
2. **统计数据**：字段统计、面积/长度量算结果（文本返回）
3. **可视化产物**：图表 PNG、热力图、分级设色地图

Agent 在输出结果时应：
- 说明输出图层的名称、要素数、关键字段
- 给出关键统计数字（如"缓冲区覆盖了 XX 个 POI"）
- 指出结果的空间范围和 CRS
- 如有局限性（如数据不完整、方法假设），主动说明

## 常见问题

### Q1：上传的 Shapefile 报错"无法读取"
- 原因：ZIP 包中缺少 .shp / .shx / .dbf 之一，或文件编码不是 UTF-8 / GBK
- 解决：确保 ZIP 包含完整的 shp/shx/dbf/prj 四个文件；属性表乱码时用 QGIS 另存为 UTF-8 编码

### Q2：面图层面积计算结果明显不对
- 原因：数据是 WGS84 经纬度坐标，直接用度算面积，1 度在不同纬度对应距离不同
- 解决：先 `convert_crs` 到等面积投影（如 Asia South Albers Equal Area / EPSG 项目自定义），再算面积。`measure_area` 工具内部已做投影处理，但自定义代码中需注意

### Q3：空间连接结果为空
- 原因：两个图层 CRS 不一致，或 predicate 选择不当（如用 `within` 但点在边界上）
- 解决：先用 `get_layer_detail` 确认两个图层的 bbox 是否重叠；统一 CRS；改用 `intersects` 试试

### Q4：缓冲区结果是椭圆形不是圆形
- 原因：在经纬度坐标系下做缓冲区，经度方向被压缩
- 解决：`spatial_buffer` 的 `unit="m"` 时内部会自动投影到球面等距方位投影；若用 `execute_python` 自定义代码，需先投影到合适的投影坐标系

### Q5：GeoJSON 文件太大加载慢
- 原因：要素过多或几何精度过高（坐标小数位太多）
- 解决：用 `spatial_simplify` 简化几何；或用 `export_layer` 导出为 GeoPackage（更紧凑）；前端渲染大量要素时考虑聚合

### Q6：属性表字段名出现乱码或被截断
- 原因：Shapefile 字段名限制 10 字符，中文编码问题
- 解决：优先使用 GeoJSON 或 GeoPackage 格式；导出 Shapefile 时字段名会自动截断，需在导出前重命名

### Q7：两个图层看起来重叠但 spatial_intersect 结果为空
- 原因：边界未精确重合（浮点精度问题），或一个是 MultiPolygon 另一个是 Polygon
- 解决：先用 `topology_check` 修复几何；对边界接触的场景用 `intersects` 而非 `within`；必要时做微小缓冲区（0.0001度）后再叠加
