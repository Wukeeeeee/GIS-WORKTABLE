# 栅格数据处理

## 适用场景

- GeoTIFF 遥感影像、DEM 高程数据的读取和处理
- 栅格裁剪、重采样、格式转换
- 多波段影像的波段运算和指数计算
- 栅格与矢量叠加（用矢量面裁剪栅格）
- 栅格分类、重分类、阈值提取
- 大影像的分块处理和性能优化

## 输入数据要求

- 格式：GeoTIFF（.tif / .tiff），必须包含地理参考（仿射变换 + CRS）
- 无地理参考的纯图片（PNG/JPG）不能做空间分析，只能作为底图显示
- 单波段：DEM（浮点型高程）、分类结果（整型）、索引图
- 多波段：遥感影像（Landsat 7/8 波段、Sentinel-2 波段）
- 数据类型：uint8 / uint16 / float32 / float64，NoData 值应正确设置

## 分析思路

栅格数据是"像元矩阵 + 地理参考"，处理思路与矢量完全不同：

1. **先读元数据**：波段数、尺寸、数据类型、CRS、NoData 值、分辨率
2. **判断处理类型**：波段运算（逐像元）、空间操作（裁剪/重采样）、统计（像元值分布）
3. **注意 NoData**：运算时必须掩膜 NoData，否则结果会污染
4. **内存管理**：大影像不要一次性读入内存，用分块（window）处理
5. **输出保留地理参考**：写出时必须复制 profile（transform + crs），否则结果无法定位

## 处理流程

```
1. 数据加载与检查
   ├─ 上传 GeoTIFF → /api/upload 自动渲染为 PNG 底图叠加
   ├─ execute_python 用 rasterio.open 读取元数据（count/shape/dtype/crs/nodata/transform）
   └─ 检查波段数和数据类型是否匹配分析需求

2. 预处理
   ├─ 裁剪 → clip_raster(layer_name, clip_layer_name, output_name)
   ├─ 重采样 → execute_python（rasterio.warp.reproject，指定目标分辨率）
   ├─ 格式转换 → execute_python（rasterio 写出为新格式）
   └─ NoData 处理 → 读取时掩膜，运算后恢复 NoData

3. 波段运算
   ├─ 单波段指数 → ndvi_analysis(layer_name, red_band, nir_band)
   ├─ 自定义运算 → raster_calculator(layer_name, expression)
   ├─ 多指数批量 → execute_python（一次计算 NDVI/NDWI/NDBI 等）
   └─ 结果保存为新 GeoTIFF（保留 transform + crs）

4. 分类与重分类
   ├─ 监督分类 → execute_python（scikit-learn RandomForest / KMeans）
   ├─ 阈值分割 → execute_python（np.where / np.digitize）
   └─ 分类结果转矢量 → execute_python（rasterio.features.shapes）

5. 统计与可视化
   ├─ 像元统计 → execute_python（np.mean/np.percentile/直方图）
   ├─ 显示 → matplotlib.imshow + colorbar，savefig 到 output/
   └─ 图例 → 分类结果配离散色带和图例

6. 结果导出
   ├─ 栅格 → execute_python 写出 GeoTIFF（rasterio.open + write）
   ├─ 矢量 → 分类结果矢量化后 export_layer
   └─ 图片 → plt.savefig 已自动注册 Artifact
```

## 方法选择依据

### 重采样方法选择

| 方法 | 适用数据 | 原因 |
|------|---------|------|
| 最近邻 (nearest) | 分类数据、土地覆盖 | 不产生新的像元值，保持类别完整性 |
| 双线性 (bilinear) | 连续数据（DEM、温度） | 平滑过渡，计算快 |
| 三次卷积 (cubic) | 影像、连续表面 | 更平滑，细节保留好，计算慢 |
| 众数 (mode) | 分类数据降采样 | 取最多类别，适合聚合 |

### 裁剪方式

- 用矢量面裁剪栅格 → `clip_raster` 工具（内部用 rasterio.mask.mask）
- 用 bbox 裁剪 → execute_python（rasterio.windows.Window）
- 裁剪后必须更新 transform（origin 变化），否则定位错误

### NoData 处理原则

- 读取时：`data = src.read(1, masked=True)` 自动掩膜
- 运算时：用 `np.ma` 模块或手动 `where(data != nodata)`
- 写出时：`profile.update(nodata=nodata)`，并将掩膜位置写回 nodata 值
- 显示时：`np.ma.masked_array` 配合 `cmap.set_bad('white')`

## 推荐工具

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `clip_raster` | 用矢量面裁剪栅格 | layer_name, clip_layer_name, output_name |
| `ndvi_analysis` | NDVI 计算（可指定红/近红外波段） | red_band, nir_band |
| `raster_calculator` | 自定义波段算术表达式 | expression（如 "(B4-B3)/(B4+B3)"） |
| `dem_analysis` | DEM 坡度/坡向/山体阴影 | analysis: slope/aspect/hillshade |
| `hydrology_analysis` | 水文分析（填洼/流向/汇流/河网） | analysis: fill/flowdir/flowacc/stream |
| `extract_contours` | 等高线提取 | interval（等高距，0=自动） |
| `spatial_interpolate` | 点数据插值为栅格（IDW/RBF） | method: idw/rbf |
| `execute_python` | 自定义栅格处理（rasterio/numpy/sklearn） | 所有复杂操作 |

## 输出结果

- 栅格运算结果保存为 GeoTIFF 到 output/ 目录，保留地理参考
- 可视化结果保存为 PNG（带 colorbar），自动注册 Artifact
- 分类结果可矢量化为 GeoJSON 图层加载到地图
- Agent 应说明：输入波段、运算公式、输出值域范围、NoData 处理方式

## 常见问题

### Q1：上传 GeoTIFF 后地图上看不到
- 原因：影像太大或坐标范围超出当前视图，或渲染 PNG 失败
- 解决：上传返回 raster_info（url + bounds），前端会自动叠加；用 get_layer_detail 或查看 /output/uploads/ 下的 PNG

### Q2：raster_calculator 表达式报错
- 原因：波段引用格式错误，或使用了不支持的函数
- 解决：用 B1/B2/B3 引用波段；只支持基本算术（+ - * /）和简单函数；复杂运算用 execute_python

### Q3：NDVI 结果全是 NaN 或 0
- 原因：红/近红外波段编号错误，或 NoData 未处理
- 解决：Landsat 8/9：红=B4，近红外=B5；Sentinel-2：红=B4，近红外=B8；先 execute_python 打印各波段统计确认

### Q4：输出的 GeoTIFF 没有坐标信息
- 原因：写出时没有复制 src.profile 或 transform
- 解决：execute_python 中必须 `with rasterio.open(out_path, 'w', **src.profile) as dst:` 并写出 transform 和 crs

### Q5：大影像处理内存溢出
- 原因：一次性 read() 读入全部像元
- 解决：用 rasterio 的 window 分块读取处理，或先 clip_raster 裁剪到研究区再处理

### Q6：DEM 坡度结果异常（全是 0 或极大值）
- 原因：DEM 单位是米但 CRS 是经纬度，坡度计算时 x/y 单位与 z 单位不一致
- 解决：dem_analysis 内部已处理；自定义代码需用 rasterio.warp.reproject 转到投影坐标，或计算时加 z 因子转换
