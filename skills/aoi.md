# AOI 提取技能

从地图服务提取建筑/地块轮廓。

## 数据源
- **unified_aoi_search("地点名")** → 选候选 → **unified_aoi_extract(uid, name)**
- DataV（行政边界）: `datav_boundary("广东省")`

## 流程规则
1. 行政边界用 `datav_boundary`，不用 AOI 工具
2. 建筑/地块轮廓用 `unified_aoi_search` + `unified_aoi_extract`
3. 如果用户说一个地名，先 `unified_aoi_search` 让用户选
4. 提取结果自动加载到地图

## 坐标
- AOI 提取结果已转 WGS-84，直接加载
- DataV 边界也会自动转 WGS-84
