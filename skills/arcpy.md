# ArcPy 风格代码编写指南

在 `execute_python` 沙箱中，使用 GeoPandas/Shapely 编写 ArcPy 风格的 GIS 代码。

## 基本原则

沙箱内可用 `geopandas`、`shapely`、`pyproj`、`rasterio`、`numpy`、`matplotlib` 等库。
代码风格参照 ArcPy 的命名习惯可以让意图更清晰：

```python
import geopandas as gpd
import json

# 读取已有图层
with open('layer.geojson') as f:
    data = json.load(f)

gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")

# 缓冲区分析（类似 arcpy.Buffer_analysis）
buffered = gdf.copy()
buffered.geometry = buffered.geometry.buffer(0.01)  # 度单位
print(buffered.to_json())

# 裁剪（类似 arcpy.Clip_analysis）
from shapely.geometry import shape
clip_poly = shape(clip_data["features"][0]["geometry"])
clipped = gdf[gdf.geometry.within(clip_poly) | gdf.geometry.intersects(clip_poly)]
print(clipped.to_json())
```

## 常用映射

### 矢量化分析

| ArcPy 函数 | GeoPandas/Shapely 实现 |
|-----------|----------------------|
| `Buffer_analysis` | `gdf.geometry.buffer(distance)` |
| `Clip_analysis` | `gpd.clip(gdf, clip_gdf)` |
| `Intersect_analysis` | `gpd.overlay(gdf1, gdf2, how="intersection")` |
| `Union_analysis` | `gpd.overlay(gdf1, gdf2, how="union")` |
| `SymDiff_analysis` | `gpd.overlay(gdf1, gdf2, how="symmetric_difference")` |
| `Identity_analysis` | `gpd.overlay(gdf1, gdf2, how="identity")` |
| `Erase_analysis` | `gpd.overlay(gdf, erase, how="difference")` |
| `Select_analysis` | `gdf.query("condition")` 或 `gdf[gdf["field"] > 0]` |
| `SelectLayerByLocation` | `gdf[gdf.geometry.within(poly)]` / `.intersects()` / `.contains()` |
| `Near_analysis` | `gdf.geometry.distance(other_geom)` |
| `GenerateNearTable` | `gdf.geometry.apply(lambda g: other_gdf.distance(g).min())` |
| `Dissolve_analysis` | `gdf.dissolve(by="field")` / `gdf.dissolve()`（合并全部） |
| `SpatialJoin_analysis` | `gpd.sjoin(gdf1, gdf2, how="left", predicate="intersects")` |
| `AddField_management` | `gdf["new_field"] = values` |
| `CalculateField_management` | `gdf["field"] = gdf.eval("expression")` / `gdf["field"].apply(func)` |
| `AddGeometryAttributes` | `gdf.area` / `gdf.length` / `gdf.geometry.centroid` |
| `Simplify_analysis` | `gdf.geometry.simplify(tolerance)` |
| `MultipartToSinglepart` | `gdf.explode(index_parts=True)` |
| `FeatureToPoint` | `gdf.geometry.centroid` |
| `XYTableToPoint` | `gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.x, df.y), crs="EPSG:4326")` |
| `Merge_management` | `gpd.GeoDataFrame(pd.concat([gdf1, gdf2], ignore_index=True))` |
| `CopyFeatures_management` | `gdf.copy()` |

### 栅格处理 (rasterio)

| ArcPy 函数 | rasterio 实现 |
|-----------|--------------|
| `Describe_management` | `rasterio.open(path).meta` |
| `Clip_management`（栅格） | `rasterio.mask.mask(dataset, shapes)` |
| `Resample_management` | `dataset.read(out_shape=(h,w), resampling=Resampling.bilinear)` |
| `ExtractByMask` | `rasterio.mask.mask(dataset, shapes)` |
| `BuildPyramids` | `rasterio.warp.reproject(..., precompute=False)` |
| `RasterToOtherFormat` | `with rasterio.open("output.tif", "w", **profile) as dst:` |

## 常见工作流模板

### CSV/Excel 生成点图层

```python
import pandas as pd
import geopandas as gpd

df = pd.read_csv("data.csv")  # 或 pd.read_excel("data.xlsx")
gdf = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df["经度"], df["纬度"]),
    crs="EPSG:4326",
)
print(gdf.to_json())
```

### 空间连接（省/市/区归属判定）

```python
# boundary_gdf 是行政区边界图层
gdf_wgs84 = gdf.to_crs("EPSG:4326")
joined = gpd.sjoin(gdf_wgs84, boundary_gdf, how="left", predicate="within")
# joined 多了一个 index_right 列指向 boundary_gdf 的索引
print(joined.to_json())
```

### 途经省份判定

```python
# line_gdf 是路线，province_gdf 是省界
# 求每条线与各省界交点 → 提取交点 → 唯一省份列表
intersections = gpd.overlay(line_gdf, province_gdf, how="intersection")
provinces = intersections["name"].unique().tolist()
print(f"途经省份: {', '.join(provinces)}")
```

### 栅格波段运算（NDVI）

```python
import rasterio
import numpy as np

with rasterio.open("sentinel2.tif") as src:
    red = src.read(1).astype(float)
    nir = src.read(2).astype(float)
    ndvi = (nir - red) / (nir + red + 1e-10)

# 保存 NDVI 结果
profile = src.profile
profile.update(dtype=rasterio.float32, count=1)
with rasterio.open("ndvi.tif", "w", **profile) as dst:
    dst.write(ndvi.astype(rasterio.float32), 1)
```

## 输出到地图

```python
print(gdf.to_json())  # 自动加载到前端地图
# 加 name 字段作为图层名
geojson = json.loads(gdf.to_json())
geojson["name"] = "缓冲区分析结果"
print(json.dumps(geojson))
```

```python
# 图表用 plt.savefig
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(10, 8))
gdf.plot(ax=ax, column="field", legend=True)
plt.savefig("chart_map.png")  # 自动推送到聊天框
```

## 坐标系转换

```python
gdf_wgs84 = gdf.to_crs("EPSG:4326")            # WGS84（输出到地图用）
gdf_mercator = gdf.to_crs("EPSG:3857")          # Web Mercator（面积计算慎用）
gdf_cgcs = gdf.to_crs("EPSG:4490")              # CGCS2000（国家大地坐标系）
gdf_utm = gdf.to_crs("EPSG:32650")              # UTM 50N（面积/长度可视化用）
```

**面积计算最佳实践：**
```python
# 先用 Albers 等面积投影再算
albers = gdf.to_crs("EPSG:9822")  # 或对应区域的 UTM
gdf["面积_亩"] = albers.area * 0.0015  # 平方米 → 亩
gdf["面积_公顷"] = albers.area / 10000
```

## 注意

- 沙箱白名单库：geopandas, shapely, numpy, pandas, matplotlib, pyecharts, pyproj, rasterio, json, requests, math, re, datetime, io, tempfile
- `print(GeoJSON)` 自动推送到前端地图
- GeoJSON 中加 `"name"` 字段 → 前端图层名
- 图表用 `plt.savefig("chart_xxx.png")` 自动显示在聊天框
- 栅格数据用 rasterio（不在白名单中但沙箱内可用需确认）
- 坐标系转换后检查范围是否合理（如 WGS84 经度应在 -180~180）
