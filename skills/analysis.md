# 空间分析技能参考

用 geopandas 做空间分析。

## 常用操作
- `gpd.sjoin(gdf1, gdf2, how='inner', predicate='intersects')` — 空间连接
- `gdf.clip(mask_geodf)` — 按范围裁剪
- `gdf.dissolve(by='字段')` — 按属性合并
- `gdf.explode()` — 拆分多部件
- `gdf.overlay(gdf2, how='intersection')` — 叠置分析

## 字段计算器（field_calculate）
AI 对已有图层添加计算字段时，**优先用 field_calculate 工具**。
1. 先调 `get_registered_layers()` 确认图层名存在
2. 调 `field_calculate(layer_name, expression, new_field, field_type)`
3. **不需要再打印 GeoJSON**，field_calculate 自动更新地图图层
4. 如果失败，查 `get_layer_detail` 确认字段名后重试

## 途经省份/城市路线查询（安全模板）
当用户问从A到B经过哪些省份/城市时，**必须用空间分析精确判定，严禁凭知识列省份**。

### 安全代码模板（直接套用）
```python
import json, shapely.geometry as geom
# 用 get_layer_detail 拿到的省份 GeoJSON 嵌入到这里
line = geom.LineString([[起点经度, 起点纬度], [终点经度, 终点纬度]])
provinces = {"广东省": {...}, "湖南省": {...}}  # 从 get_layer_detail 获取
crossed = []
for name, gj in provinces.items():
    for feat in gj["features"]:
        poly = geom.shape(feat["geometry"])
        if line.crosses(poly) or line.intersects(poly):
            crossed.append(name)
            break
print("经过的省份:", crossed)
```
**注意：** 起点和终点所在的省份也计入途经省份

### 安全规则
1. 先调 datav_boundary 获取沿途可能经过的省份边界
2. 调 get_layer_detail 获取每个省份的 GeoJSON
3. **必须用 shapely 做空间分析**，不能凭自己的知识判断
4. 结果每个省单独一个图层，不同颜色区分