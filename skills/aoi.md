# AOI 提取技能

从地图服务提取建筑/地块轮廓。

## 数据源
- 百度地图: `baidu_aoi_search("地点名")` → 选候选 → `baidu_aoi_extract(uid, name)`
- 高德地图: `gaode_aoi_search("地点名")` → 选候选 → `gaode_aoi_extract(id, name)`
- 统一接口: `unified_aoi_search("地点名")` → 弹框选 → `unified_aoi_extract(id, name, source)`
- DataV（行政边界）: `datav_boundary("广东省")`

## 流程规则
1. 行政边界用 `datav_boundary`，不用 AOI 工具
2. 建筑/地块轮廓用 AOI 工具
3. 如果用户说一个地名，先 `unified_aoi_search` 让用户选
4. 提取结果自动加载到地图

## 坐标
- AOI 提取结果已转 WGS-84，直接加载
- DataV 边界也会自动转 WGS-84
