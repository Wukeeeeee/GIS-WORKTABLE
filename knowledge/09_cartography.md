# 地图制图规范

## 适用场景

- 分析结果需要制作专业地图输出
- 图层符号化、分级设色、唯一值渲染
- 添加图例、比例尺、指北针、图名
- 导出 PNG/JPEG 图片或 PDF 地图
- 地图布局和排版
- 用户要求"出图""做一张地图""导出成果图""美化地图"

## 输入数据要求

- 已注册的矢量或栅格图层
- 矢量图层有用于符号化的属性字段（分级设色需要数值字段，唯一值需要分类字段）
- 地图范围已确定（bbox 或研究区边界）
- 输出格式：PNG（图片）、PDF（打印）、GeoJSON/SHP（数据）

## 分析思路

地图制图的核心是"用视觉变量准确传达空间信息"。专业地图不是简单的数据叠加，而是有目的的信息传达：

1. **地图主题是什么？** 决定主图层和符号化方式
2. **读者是谁？** 专业人士用详细符号，公众用简洁直观
3. **空间范围多大？** 决定比例尺和标注密度
4. **输出媒介？** 屏幕显示用 RGB，打印用 CMYK 和更高分辨率

制图原则：
- 一幅地图一个主题，避免信息过载
- 颜色有含义：分级用渐变色，分类用定性色，不要用彩虹色
- 重要要素突出（颜色、线宽），次要要素淡化
- 必须的地图要素：图名、图例、比例尺、指北针、数据源

## 处理流程

```
1. 确定制图主题和范围
   ├─ 明确地图要表达的核心信息
   ├─ 确定研究区范围（用 boundary 或自定义 bbox）
   └─ 选择底图（浅色/深色/无底色，避免干扰数据层）

2. 图层符号化
   ├─ 数值字段分级 → spatial_graduated_colors(layer_name, field, n_classes, color_scheme)
   ├─ 分类字段唯一值 → spatial_unique_values(layer_name, field, color_scheme)
   ├─ 点图层 → 大小/颜色/形状编码属性
   ├─ 线图层 → 颜色/粗细/线型编码
   ├─ 面图层 → 填充色/透明度/边框编码
   └─ layer_control 设置颜色、透明度、线宽、填充图案

3. 标注与图例
   ├─ add_labels(layer_name, field, font_size, color) → 属性标注
   ├─ add_legend(layer_name) → 图例
   ├─ add_north_arrow() → 指北针
   └─ 图名和比例尺在导出时添加

4. 图表联动
   ├─ create_chart(layer_name, chart_type, field) → 统计图表
   ├─ link_chart_map(layer_name, chart_field) → 图表-地图联动
   └─ 图表作为地图的补充信息

5. 地图导出
   ├─ export_map(format="png"/"jpeg") → 图片导出
   ├─ export_pdf(title) → PDF 出图（含图名、图例、比例尺）
   ├─ export_layer → 数据导出（GeoJSON/SHP/CSV）
   └─ 分辨率建议：屏幕 150dpi，打印 300dpi

6. 质量检查
   ├─ 图例是否完整对应所有符号
   ├─ 比例尺是否准确
   ├─ 指北针方向是否正确
   ├─ 标注是否有重叠
   ├─ 颜色是否色盲友好
   └─ 数据源和投影是否标注
```

## 方法选择依据

### 符号化方法选择

| 数据类型 | 符号化方法 | 工具 |
|---------|-----------|------|
| 数值字段（连续） | 分级设色（渐变色） | spatial_graduated_colors |
| 分类字段（离散） | 唯一值渲染（定性色） | spatial_unique_values |
| 点密度 | 热力图 / 核密度 | create_heatmap / KDE |
| 数量大小 | 比例符号（点大小编码） | layer_control + field_calculate |
| 路线/网络 | 线宽 + 颜色 | layer_control |

### 分级方法

- **等间距（Equal Interval）**：每级范围相同，适合均匀分布数据
- **分位数（Quantile）**：每级要素数相同，适合偏态分布，最常用
- **自然断点（Jenks/Natural Breaks）**：类内差异最小、类间差异最大，适合有自然聚类的数据
- **标准差（Standard Deviation）**：以均值为中心分级，适合正态分布数据

项目 spatial_graduated_colors 默认使用分位数法（pandas qcut），适合大多数 GIS 数据。

### 颜色方案选择

| 数据类型 | 推荐色带 | 示例 |
|---------|---------|------|
| 连续数值（低→高） | 单色渐变 | Blues, Greens, Oranges |
| 连续数值（有中心点） | 发散色 | RdYlBu, PiYG（红-蓝） |
| 分类数据 | 定性色 | Set1, Set2, Paired（区分度高） |
| 植被/NDVI | 绿-黄-红 | RdYlGn（红=低，绿=高） |
| 地形/高程 | 地形色 | terrain, gist_earth |
| 水体 | 蓝色系 | Blues |

避免使用：jet/彩虹色带（色盲不友好、色调变化误导数值感知）。

### 出图分辨率

- 屏幕展示 / PPT：120-150 dpi
- 打印 / 报告：300 dpi
- 海报 / 大幅面：300-600 dpi
- export_map 默认 PNG，可通过 execute_python 用 matplotlib 控制 dpi

## 推荐工具

| 工具名 | 用途 |
|--------|------|
| `spatial_graduated_colors` | 分级设色（数值字段） |
| `spatial_unique_values` | 唯一值渲染（分类字段） |
| `layer_control` | 图层颜色/透明度/线宽/填充图案 |
| `add_labels` | 属性标注 |
| `add_legend` | 图例 |
| `add_north_arrow` | 指北针 |
| `create_chart` | 统计图表 |
| `link_chart_map` | 图表-地图联动 |
| `export_map` | 图片导出（PNG/JPEG） |
| `export_pdf` | PDF 出图 |
| `export_layer` | 数据导出 |
| `animate_time` | 时序动画（时间字段） |

## 输出结果

- 地图图片：PNG/JPEG，保存到 output/ 目录，自动注册 Artifact
- PDF 地图：含图名、图例、比例尺、指北针
- 符号化后的图层：样式保存在图层注册信息中，前端渲染
- Agent 应说明：地图主题、符号化方法和字段、分级数和色带、输出格式和分辨率、地图包含的图层

## 常见问题

### Q1：分级设色后所有要素一个颜色
- 原因：字段值全相同，或字段名拼写错误，或 n_classes 大于唯一值数
- 解决：先用 spatial_field_stats 看字段分布；确认字段名；减少分级数或改用唯一值渲染

### Q2：导出的地图没有图例和比例尺
- 原因：export_map 只导出当前地图视图，图例/比例尺需要前端面板或 export_pdf
- 解决：用 export_pdf 出图（含图名、图例、比例尺、指北针）；或先 add_legend 再截图

### Q3：颜色在打印后和屏幕上不一样
- 原因：屏幕是 RGB 自发光，打印是 CMYK 反射光，颜色空间不同
- 解决：打印用 export_pdf；选择打印友好的颜色方案；避免用极浅的颜色（打印后看不清）

### Q4：标注重叠严重
- 原因：要素密集，标注全部显示
- 解决：减少标注要素（按属性筛选后标注）；减小 font_size；用 execute_python 做标注避让（adjustText 库）

### Q5：唯一值渲染颜色区分度不够
- 原因：类别太多（>8 类），定性色带不够用
- 解决：合并小类别为"其他"；限制最多 6-8 类；用形状+颜色双重编码

### Q6：export_pdf 中文字体乱码
- 原因：matplotlib 默认字体不支持中文
- 解决：项目已配置中文字体（execute_python 环境中 plt.rcParams 已设）；如仍乱码，在 execute_python 中显式设置 plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
