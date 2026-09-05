# DEM 地形分析

## 适用场景

- 数字高程模型（DEM）的地形因子提取
- 坡度、坡向、山体阴影计算
- 等高线提取和地形剖面
- 水文分析（填洼、流向、汇流累积、河网提取）
- 地形可视化（3D 地形、剖面图）
- 地形统计（高程分布、面积-高程曲线）
- 用户要求"算坡度""提取河网""做地形剖面""3D 显示地形""流域分析"

## 输入数据要求

- 单波段 GeoTIFF DEM，像元值为高程（单位：米）
- 必须包含地理参考（transform + CRS）
- CRS 建议为投影坐标（如 UTM），经纬度 DEM 计算坡度时需处理分辨率单位
- 无数据区域（NoData）应正确设置
- 分辨率建议：30m（SRTM/ASTER GDEM）或更高
- 水文分析需要 DEM 覆盖完整流域（不能只截取上游部分）

## 分析思路

DEM 是连续的高程表面，地形分析通过"邻域运算"提取地形特征：

1. **描述地形**：高程范围、坡度（陡缓）、坡向（朝向）
2. **模拟水文**：水流从高到低 → 流向 → 汇流 → 河网 → 流域
3. **可视化**：山体阴影（模拟光照）、3D 地形、剖面图
4. **应用分析**：坡度阈值筛选（建设用地）、坡向分析（日照）、流域划分

核心原则：地形分析结果的精度取决于 DEM 分辨率和质量；洼地（sink）会影响水文分析，必须先填洼。

## 处理流程

```
1. 数据检查
   ├─ 上传 DEM GeoTIFF
   ├─ execute_python：rasterio.open 读取（count=1, dtype, nodata, transform, shape）
   ├─ 统计高程范围（np.min/max/mean）
   └─ 确认 CRS 和分辨率（transform 中的像素大小）

2. 基本地形因子
   ├─ dem_analysis(layer_name, analysis="slope") → 坡度（度）
   ├─ dem_analysis(layer_name, analysis="aspect") → 坡向（度，0=北）
   ├─ dem_analysis(layer_name, analysis="hillshade") → 山体阴影
   └─ 结果保存为 GeoTIFF + PNG 可视化

3. 等高线与剖面
   ├─ extract_contours(layer_name, interval) → 等高线矢量
   ├─ terrain_profile(layer_name, line_coords) → 地形剖面图
   └─ 等高距选择：根据高程范围选（山区 50-100m，平原 5-10m）

4. 水文分析
   ├─ hydrology_analysis(layer_name, analysis="fill") → 填洼
   ├─ hydrology_analysis(layer_name, analysis="flowdir") → D8 流向
   ├─ hydrology_analysis(layer_name, analysis="flowacc") → 汇流累积量
   ├─ hydrology_analysis(layer_name, analysis="stream") → 河网提取（阈值）
   └─ 注意：必须按 fill → flowdir → flowacc → stream 顺序执行

5. 3D 可视化
   ├─ view_3d_terrain(layer_name, exaggeration) → Three.js 3D 地形
   ├─ exaggeration：垂直夸张系数（2-5 倍增强地形起伏）
   └─ 配合山体阴影底图效果更佳

6. 地形统计与应用
   ├─ execute_python：高程直方图、坡度分布、坡向玫瑰图
   ├─ 坡度阈值筛选：np.where(slope < 15, 1, 0) → 适宜建设区
   ├─ 坡向分类：北/东北/东/东南/南/西南/西/西北八方位
   └─ 面积统计：各坡度/坡向等级的面积

7. 结果展示
   ├─ 坡度图：渐变色带（绿=缓，红=陡）
   ├─ 坡向图：圆形色带（Aspect 专用 colormap）
   ├─ 山体阴影：灰度图
   ├─ 河网：蓝色线图层叠加
   └─ 等高线：棕色线，标注高程
```

## 方法选择依据

### 坡度计算方法

- **三阶反距离平方权差分（Horn 算法）**：最常用，dem_analysis 内部使用，对噪声有一定平滑
- 坡度单位：度（0-90°）或百分比（rise/run × 100）
- 经纬度 DEM：x 方向分辨率（度）需转换为米（1°经度 ≈ 111320 × cos(lat) 米），否则坡度不准

### 坡向解读

- 0° = 北（N），90° = 东（E），180° = 南（S），270° = 西（W）
- -1° 表示平坦区域（坡度接近 0，无明确坡向）
- 北半球：南坡日照好、温度高，北坡湿润、温度低

### 水文分析 D8 算法

- D8（Deterministic 8）：每个像元的水流向 8 个邻域中坡度最陡的一个
- 优点：简单、计算快、是 ArcGIS 默认算法
- 局限：不能处理分流（水只往一个方向流），平地流向随机
- 填洼是必须的前置步骤：洼地会阻止水流，导致汇流异常
- 河网阈值：汇流累积量 > 阈值的像元定义为河道，阈值越小河网越密

### 山体阴影参数

- 太阳方位角（azimuth）：默认 315°（西北），模拟上午光照
- 太阳高度角（altitude）：默认 45°
- 改变方位角可突出不同方向的地形特征

## 推荐工具

| 工具名 | 用途 | 参数 |
|--------|------|------|
| `dem_analysis` | 坡度/坡向/山体阴影 | analysis: slope/aspect/hillshade |
| `hydrology_analysis` | 填洼/流向/汇流/河网 | analysis: fill/flowdir/flowacc/stream |
| `extract_contours` | 等高线提取 | interval: 等高距（0=自动） |
| `terrain_profile` | 地形剖面图 | line_coords: 折线坐标 JSON |
| `view_3d_terrain` | 3D 地形可视化 | exaggeration: 垂直夸张系数 |
| `clip_raster` | DEM 裁剪 | 用研究区矢量裁剪 |
| `execute_python` | 自定义地形分析 | 坡度分类、面积统计、流域边界 |

## 输出结果

- 地形因子：GeoTIFF（坡度/坡向/山体阴影/汇流累积）+ PNG 可视化
- 等高线/河网：GeoJSON 矢量图层，加载到地图
- 地形剖面：PNG 图片（横轴距离，纵轴高程）
- 3D 地形：HTML 页面（Three.js）
- Agent 应说明：DEM 来源和分辨率、计算方法、关键参数（等高距、河网阈值）、主要发现（最高/最低点、平均坡度、主要河流走向、流域特征）、局限性（DEM 误差、洼地处理、D8 算法假设）

## 常见问题

### Q1：坡度结果全是 0 或异常大
- 原因：DEM 是经纬度坐标，x/y 分辨率是度而非米，坡度计算时单位不匹配
- 解决：dem_analysis 内部已处理经纬度转换；自定义代码需将经纬度分辨率转为米，或先 reproject 到投影坐标系

### Q2：水文分析汇流累积量全是 0
- 原因：没有先填洼，或流向计算失败
- 解决：严格按 fill → flowdir → flowacc 顺序执行；确认 DEM 没有大面积 NoData

### Q3：河网提取结果太稀疏或太密
- 原因：汇流累积阈值设置不当
- 解决：阈值 = 研究区面积 / 期望河道数；先看 flowacc 的统计（最大值、分位数），选择合适阈值；通常取最大汇流量的 1%-5%

### Q4：等高线在平坦区域密集混乱
- 原因：DEM 噪声（平坦区微小高程波动被放大）
- 解决：先对 DEM 做轻微滤波（scipy.ndimage.gaussian_filter，sigma=1）再提取等高线；或增大等高距

### Q5：3D 地形显示不出来
- 原因：DEM 文件路径未注册，或 Three.js 加载失败
- 解决：确认 DEM 已上传并在 output/ 目录可访问；view_3d_terrain 生成 HTML 后通过 /output/ 路径访问

### Q6：地形剖面线不经过 DEM 区域
- 原因：line_coords 坐标范围与 DEM bbox 不重叠
- 解决：用 get_layer_detail 或 rasterio 查看 DEM bounds，确保剖面线在范围内
