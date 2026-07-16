# 热力图技能

用 leaflet.heat 在浏览器端渲染热力图。

## 接口
`create_heatmap(layer_name, weight_field, radius, gradient)`

## 参数
- `layer_name`: 已有图层的名称（点类型）
- `weight_field`: 权重字段（可选）
- `radius`: 像素半径，默认 20
- `gradient`: 颜色渐变，如 "0.4=blue,0.6=cyan,0.7=lime,0.8=yellow,1.0=red"

## 规则
- 只能从已有图层生成，不能凭空创建
- 如果图层不是点类型，先提取点
- 先用 `get_registered_layers` 看看有什么图层可用

## 从城市名生成热力图的工作流（无现成图层时）
1. 调 `datav_boundary("广州市")` 获取行政边界
2. 调 `search_web` 搜索该城市的统计数据
3. 调 `execute_python` 在边界内生成随机采样点（带权重字段），打印 GeoJSON 加载到地图
4. 调 `create_heatmap` 对刚加载的点图层生成热力图
- **严禁直接 web 爬取百度地图页面来获取区域数据，始终用 datav_boundary 获取边界**