# 统计图表技能参考（create_chart 工具）

## chart_type 选择指南
- **bar（柱状图）**：统计分类字段各值频次，或双字段对比
- **pie（饼图）**：看分类字段占比
- **histogram（直方图）**：看数值字段分布（如面积、人口、GDP）
- **scatter（散点图）**：双数值字段看相关性（如面积 vs 人口）
- **line（折线图）**：有序字段看趋势（如年份、月份）

## 参数传法
- **单字段**：只传 `field`（如 `create_chart("图层名", "histogram", "面积")`）
- **双字段**：传 `x_field` + `y_field`（如 `create_chart("图层名", "scatter", x_field="面积", y_field="人口")`）
- 不传 `title` 会自动用图层名+图表类型命名

## 典型流程
1. 已有图层 → 直接调 create_chart
2. 不知道有什么字段 → 先调 get_registered_layers 看字段列表
3. 需要改图表样式 → 看数据用 create_chart，改样式用 execute_python

## 注意事项
- 数据量 > 1000 条时 histogram 更清晰，bar 会挤在一起
- pie 饼图最多显示前 20 个分类，数量过多时用 bar
- 中文字体自动支持，不需额外配置
