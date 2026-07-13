# 数据可视化技能参考

用 matplotlib 和 pyecharts 生成图表。

## Matplotlib
- `plt.figure(figsize=(10, 6))` 创建画布
- 支持: 线图/散点图/柱状图/饼图/直方图/箱线图/小提琴图/热图/等高线图/3D图/极坐标图/六边形分箱/误差条图/Q-Q图
- 中文字体已自动配置（Microsoft YaHei / SimHei），直接写 plt.title("中文") 即可
- 保存: `plt.savefig("output/chart_name.png", dpi=200, bbox_inches='tight')`
- 图片自动显示在聊天框
- 必须加图例（plt.legend()），除非是只有一个系列的简单柱状图
- 必须加坐标轴标签（plt.xlabel/ylabel）和标题（plt.title）
- 单位符号正常使用：㎡、km²、℃、%、万人等 Unicode 字符
- plt.style.use("ggplot") 或 seaborn 风格可以让图表更好看
- **子图布局**：fig, axes = plt.subplots(2, 3, figsize=(15, 10))
- seaborn 统计图表：sns.boxplot(), sns.violinplot(), sns.heatmap(), sns.pairplot()

## Pyecharts
- 支持交互式 HTML 图表
- `from pyecharts.charts import Map, Bar, Line, Pie, Radar`
- 保存: `chart.render("chart_name.html")`
- 生成的 HTML 会自动嵌入聊天框预览

### pyecharts 中国省级地图示例
```python
from pyecharts.charts import Map
from pyecharts import options as opts
from pyecharts.globals import CurrentConfig
CurrentConfig.ONLINE_HOST = "https://cdn.jsdelivr.net/npm/echarts@5/dist/"
map = Map()
map.add("省份", [("广东省", 100), ("江苏省", 90), ...], "china")
map.set_global_opts(title_opts=opts.TitleOpts(title="标题"), visualmap_opts=opts.VisualMapOpts())
map.render("china_map.html")
```

### pyecharts 雷达图示例（六边形对比）
```python
from pyecharts.charts import Radar
from pyecharts import options as opts
from pyecharts.globals import CurrentConfig
CurrentConfig.ONLINE_HOST = "https://cdn.jsdelivr.net/npm/echarts@5/dist/"
schema = [{"name": "指标A", "max": 100}, ...]
data = [{"value": [80, 65, 90, 70, 85, 60], "name": "对比项1"}]
radar = Radar()
radar.add_schema(schema)
radar.add("对比项1", [data[0]["value"]])
radar.set_global_opts(title_opts=opts.TitleOpts(title="六边形对比图"))
radar.render("radar.html")
```

## 六边形分箱图（hexbin）
`plt.hexbin(x, y, gridsize=20, cmap="YlOrRd")` — 适合大量散点的空间分布聚合统计。

### 六边形分箱对比图（左散点 + 右 hexbin）
```python
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
ax1.scatter(x, y, s=2, alpha=0.5, c="#3498db")
ax1.set_title("原始散点分布")
hb = ax2.hexbin(x, y, gridsize=20, cmap="YlOrRd", mincnt=1)
ax2.set_title("六边形分箱聚合")
plt.colorbar(hb, ax=ax2, label="计数")
plt.suptitle("散点 vs 六边形分箱对比")
plt.tight_layout()
plt.savefig("chart_hexbin_comparison.png")
```

## 其他
- 统计图表放在 `output/` 目录
- pyecharts 不用加 `output/` 前缀
- 如果用户要求修改图表样式，查看对话历史中的上一段代码，修改后重新生成
