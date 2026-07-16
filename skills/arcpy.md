# ArcPy 风格代码编写指南

在 `execute_python` 沙箱中，使用 GeoPandas/Shapely 编写 ArcPy 风格的 GIS 代码。

## 基本原则
沙箱内可用 `geopandas`、`shapely`、`pyproj`、`rasterio`、`numpy`、`matplotlib` 等库。

## 安全代码模板（直接套用，不要改）

### CSV/Excel 生成点图层
```python
import pandas as pd, geopandas as gpd, json
df = pd.read_csv("data.csv")  # 或 pd.read_excel("data.xlsx")
gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["经度"], df["纬度"]), crs="EPSG:4326")
print(gdf.to_json())
```

### 输出到地图（正确方式）
```python
# 正确：print(gdf.to_json()) 自动加载
print(gdf.to_json())
# 如果要加图层名：
geojson = json.loads(gdf.to_json())
geojson["name"] = "分析结果"
print(json.dumps(geojson, ensure_ascii=False))
```

**绝对不要这样输出：** 不要 print 完整坐标列表，不要用 print(geojson["features"]) 片段输出

### 空间连接（省/市/区归属判定）
```python
joined = gpd.sjoin(gdf_wgs84, boundary_gdf, how="left", predicate="within")
print(joined.to_json())
```

### 面积计算（必须投影后算，绝对不能在 WGS84 上直接算）
```python
albers = gdf.to_crs("EPSG:9822")  # 或对应区域的 UTM
gdf["面积_亩"] = albers.area * 0.0015
gdf["面积_公顷"] = albers.area / 10000
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
| `Erase_analysis` | `gpd.overlay(gdf, erase, how="difference")` |
| `Select_analysis` | `gdf.query("condition")` 或 `gdf[gdf["field"] > 0]` |
| `SelectLayerByLocation` | `gdf[gdf.geometry.within(poly)]` / `.intersects()` / `.contains()` |
| `Dissolve_analysis` | `gdf.dissolve(by="field")` / `gdf.dissolve()` |
| `SpatialJoin_analysis` | `gpd.sjoin(gdf1, gdf2, how="left", predicate="intersects")` |
| `Simplify_analysis` | `gdf.geometry.simplify(tolerance)` |
| `MultipartToSinglepart` | `gdf.explode(index_parts=True)` |
| `XYTableToPoint` | `gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.x, df.y), crs="EPSG:4326")` |
| `Merge_management` | `gpd.GeoDataFrame(pd.concat([gdf1, gdf2], ignore_index=True))` |

### 栅格处理 (rasterio)
| ArcPy 函数 | rasterio 实现 |
|-----------|--------------|
| `Clip_management`（栅格） | `rasterio.mask.mask(dataset, shapes)` |
| `Resample_management` | `dataset.read(out_shape=(h,w), resampling=Resampling.bilinear)` |

## 坐标系转换
```python
gdf_wgs84 = gdf.to_crs("EPSG:4326")            # WGS84（输出到地图用）
gdf_mercator = gdf.to_crs("EPSG:3857")          # Web Mercator
gdf_utm = gdf.to_crs("EPSG:32650")              # 当地 UTM 带号
```

## 注意
- `print(GeoJSON)` 自动推送到前端地图，加 `"name"` 字段作为图层名
- 图表用 `plt.savefig("chart_xxx.png")` 自动显示在聊天框
- **绝对不要用 WGS84 直接算面积**，必须投影到等面积投影再算