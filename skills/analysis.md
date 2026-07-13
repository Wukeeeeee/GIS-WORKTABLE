# 空间分析技能参考

用 geopandas 做空间分析。

## 常用操作
- `gpd.sjoin(gdf1, gdf2, how='inner', predicate='intersects')` — 空间连接
- `gdf.clip(mask_geodf)` — 按范围裁剪
- `gdf.dissolve(by='字段')` — 按属性合并
- `gdf.explode()` — 拆分多部件
- `gdf.to_crs(epsg=4326)` — 投影转换
- `gdf.overlay(gdf2, how='intersection')` — 叠置分析

## 图层联动
1. `get_registered_layers()` 查看当前图层列表
2. `get_layer_detail("图层名")` 查看具体数据
3. 分析结果 print GeoJSON 自动加载到地图

## 途经省份/城市路线查询
当用户问从A到B经过哪些省份/城市时，必须通过 execute_python 做**空间分析**精确判定，**严禁凭自己的知识列省份**。

### 画直线的代码模板
```python
import json
geojson = {"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":"路线"},"geometry":{"type":"LineString","coordinates":[[起点经度,起点纬度],[终点经度,终点纬度]]}}]}
print(json.dumps(geojson, ensure_ascii=False))
```

### 精确判定途经省份的方法（必须按此流程）
1. 先调用 datav_boundary 获取沿途可能经过的省份边界
2. 调 get_layer_detail("省份名") 获取每个省份的 GeoJSON 数据
3. 调 execute_python，把 get_layer_detail 拿到的 GeoJSON 数据嵌入到代码里，用 shapely 做空间分析：
```python
import json, shapely.geometry as geom
line = geom.LineString([[起点经度, 起点纬度], [终点经度, 终点纬度]])
provinces = {
    "广东省": {"type":"FeatureCollection","features":[...]},
    "湖南省": {"type":"FeatureCollection","features":[...]},
}
crossed = []
for name, gj in provinces.items():
    for feat in gj["features"]:
        try:
            poly = geom.shape(feat["geometry"])
            if line.crosses(poly) or line.intersects(poly) or line.touches(poly):
                crossed.append(name)
                break
        except:
            pass
print("经过的省份:", crossed)
```
**注意：** 起点和终点所在的省份也计入途经省份。

4. 空间分析完成后，逐个调用 datav_boundary 获取边界（如果还没加载过的话）
5. **不要合并成一个图层**，每个省/市单独一个图层，名称就是省/市名
6. 每个省/市用不同的颜色区分（红橙黄绿青蓝紫循环）
