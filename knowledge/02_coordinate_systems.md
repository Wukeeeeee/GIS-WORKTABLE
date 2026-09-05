# 坐标系与投影

## 适用场景

- 上传数据后需要确认或转换坐标系
- 空间分析前需要统一多个图层的 CRS
- 面积、距离、缓冲区计算结果异常时
- 需要将数据从 WGS84 转到投影坐标系做精确量算
- 栅格数据需要重投影或与矢量数据叠加
- 用户询问"为什么我的数据位置不对""面积算出来不对"

## 输入数据要求

- 矢量数据应携带 CRS 信息（GeoJSON 默认 WGS84；Shapefile 需 .prj 文件；GeoPackage 内嵌 CRS）
- 栅格数据必须有仿射变换和 CRS（GeoTIFF 的 GeoKeys）
- 无 CRS 的数据需先确认来源（通常默认 WGS84 经纬度，但不能假设）
- 坐标值范围可辅助判断：经纬度（lng -180~180, lat -90~90），投影坐标（通常是大数，如 UTM 东偏 500000m）

## 分析思路

坐标系问题是 GIS 分析中最常见的错误来源。核心原则：

1. **显示用地理坐标（WGS84），分析用投影坐标**：Leaflet 地图显示用经纬度，但做面积/距离/缓冲区必须用投影坐标
2. **所有参与分析的图层必须 CRS 一致**：不一致时叠加结果为空或错误
3. **投影选择取决于分析类型**：等面积投影算面积，等距投影算距离，等角投影保持形状
4. **中国区域常用投影**：CGCS2000 / 高斯-克吕格 / UTM（50N 区覆盖中国东部）/ Albers 等面积圆锥

## 处理流程

```
1. 检查 CRS
   ├─ get_layer_detail 查看图层信息（项目中 GeoJSON 统一按 WGS84 处理）
   ├─ 栅格数据上传时自动读取 CRS
   └─ 若无 CRS 信息，询问用户或默认 WGS84 并标注

2. 判断是否需要转换
   ├─ 多图层叠加 → 必须统一 CRS
   ├─ 面积/距离计算 → 必须转到投影坐标
   ├─ 仅显示 → WGS84 即可
   └─ 与底图叠加 → WGS84（Web Mercator 显示）

3. 执行转换
   ├─ 矢量图层 → convert_crs(layer_name, target_crs)
   ├─ 单点坐标 → convert_coordinates(coords, source_crs, target_crs)
   └─ 栅格数据 → execute_python 用 rasterio.warp.reproject

4. 验证结果
   ├─ get_layer_detail 确认转换后 bbox 合理
   ├─ measure_distance 抽查两点距离是否合理
   └─ 与已知地物对比位置是否正确
```

## 方法选择依据

### 投影坐标系选择

| 分析目的 | 推荐投影 | 原因 |
|---------|---------|------|
| 面积计算（土地统计、覆盖分析） | 等面积投影（Albers / Lambert Azimuthal Equal Area） | 面积无变形 |
| 距离计算（路径、缓冲区） | 等距投影（方位等距 / 圆锥等距）或 UTM | 局部距离准确 |
| 形状/方向（导航、制图） | 等角投影（Mercator / UTM / Gauss-Kruger） | 角度和形状不变 |
| 中国全国范围分析 | Albers 等面积圆锥（标准纬线 25°N, 47°N） | 全国范围内面积变形最小 |
| 城市级小范围分析 | UTM 或高斯-克吕格 3度带 | 局部精度高，计算快 |

### 常见 CRS 代号

| CRS | 用途 |
|-----|------|
| EPSG:4326 (WGS84) | 地理坐标，经纬度，GPS 默认，Web 地图数据标准 |
| EPSG:3857 (Web Mercator) | Web 地图显示投影（Google/OSM/高德），面积变形大，不可用于分析 |
| EPSG:4490 (CGCS2000) | 中国国家大地坐标系 |
| EPSG:32649 ~ EPSG:32655 | UTM 北半球 49N-55N 带（覆盖中国） |
| ESRI:102012 | Asia North Albers Equal Area Conic |

### 坐标转换注意事项

- WGS84 ↔ CGCS2000：差异在厘米级，一般应用可视为等同
- WGS84 ↔ 北京54/西安80：需要七参数或三参数转换，直接转会有几十米到上百米偏差
- 高德/百度坐标有偏移（GCJ-02 / BD-09），项目中 amap_geocode 返回的是 GCJ-02，需注意与 WGS84 数据的偏移

## 推荐工具

| 工具名 | 用途 | 参数说明 |
|--------|------|---------|
| `convert_crs` | 矢量图层坐标系转换 | `target_crs` 支持 "wgs84" / "web mercator" / EPSG 代号 |
| `convert_coordinates` | 单点或多点坐标转换 | `source_crs` / `target_crs`，coords 为 JSON 数组 |
| `get_layer_detail` | 查看图层 bbox 和几何信息 | 间接判断 CRS 是否合理 |
| `measure_distance` | 验证转换后距离是否合理 | 经纬度输入，内部用 Haversine 公式算球面距离 |
| `measure_area` | 验证转换后面积是否合理 | 内部自动投影到等面积投影 |

## 输出结果

- 转换后的图层自动注册为新图层（名称带 CRS 后缀）
- 坐标转换返回转换后的坐标列表
- Agent 应说明：原 CRS → 目标 CRS，转换后数据的空间范围，是否有精度损失

## 常见问题

### Q1：convert_crs 后数据位置不对
- 原因：源 CRS 判断错误。如果数据本身是投影坐标但被当成 WGS84，转换会完全错位
- 解决：先用 get_layer_detail 看 bbox，如果坐标是大数（如 500000, 3000000）说明是投影坐标，需要先确认源 CRS 再转

### Q2：面积算出来是个很大的数（几万度）
- 原因：在 WGS84 经纬度下直接算面积，单位是"平方度"不是平方米
- 解决：measure_area 工具内部已自动处理；如果是 execute_python 自定义代码，必须先 to_crs 到投影坐标系

### Q3：两个图层叠在一起但 spatial_join 结果为空
- 原因：CRS 不一致。一个是 WGS84，另一个可能是投影坐标
- 解决：用 convert_crs 统一到 WGS84 或同一投影坐标系后再分析

### Q4：缓冲区半径设了 1000 米但结果范围不对
- 原因：spatial_buffer 的 unit="m" 时内部会自动投影，但如果数据本身 CRS 异常会失败
- 解决：确认数据是 WGS84 经纬度；如果是投影坐标，unit 应设为"m"且距离单位与投影单位一致

### Q5：高德 POI 坐标和上传数据对不上
- 原因：高德用 GCJ-02 火星坐标，WGS84 数据有偏移（国内约 50-500 米）
- 解决：项目中 amap 数据统一处理；如需精确配准，需做 GCJ-02 → WGS84 纠偏（execute_python 可实现）

### Q6：栅格和矢量叠加位置不对
- 原因：栅格 CRS 与矢量不一致，或栅格无 GeoTIFF 地理参考
- 解决：用 rasterio 读取栅格 CRS，必要时用 rasterio.warp.reproject 重投影到 WGS84
