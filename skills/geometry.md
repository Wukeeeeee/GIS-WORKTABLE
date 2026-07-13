# 几何操作技能参考

用 shapely 和 geopandas 做几何操作。

## 坐标系规则（重要）
- 输入图层都是 WGS-84（EPSG:4326）
- 涉及距离/面积的 buffer 必须先投影再操作
- `pyproj` 已安装，用 `pyproj.Transformer` 做投影
- 自动获取 UTM Zone: `pyproj.Proj(f"+proj=utm +zone={zone}, +datum=WGS84")`
- 短距离估算：中纬度 1度 ≈ 111km，但正式分析**必须用投影**
- 计算面积也同理：必须投影后算，不能直接用 WGS84 的 shapely.area
- 用户上传的数据坐标系未知时，默认视为 WGS84 (EPSG:4326)

## 常用操作
- buffer: `shapely.buffer(geometry, distance)` — 先转 UTM，buffer 完转回 WGS-84
- intersection: `geom1.intersection(geom2)` — 直接 WGS-84 做
- union: `geom1.union(geom2)`
- difference: `geom1.difference(geom2)`
- centroid: `geom.centroid` — 返回 Point
- convex_hull: `geom.convex_hull`
- simplify: `geom.simplify(tolerance)` — tolerance 在 WGS-84 里约 0.001 ≈ 100m
- make_valid: `shapely.validation.make_valid(geom)`

## 缓冲区分析（注意事项）
- 用户说"缓冲区"时，说的是**实际距离**（米、公里），不是度数
- 正确做法：
  1. 用 pyproj 或 geopandas 把数据投影到合适的平面坐标系（如 EPSG:3857 Web Mercator 或当地 UTM）
  2. 用米做 buffer
  3. 再转回 EPSG:4326 输出

## 输出到地图
结果 GeoJSON 一定要加上 `"name"` 字段，
或者 print 时确保每行是一个完整的 JSON，
这样前端能自动加载到图层面板。
