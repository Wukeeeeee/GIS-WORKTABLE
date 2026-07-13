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
