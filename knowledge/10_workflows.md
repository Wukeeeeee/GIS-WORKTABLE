# 常见 GIS 项目工作流

## 适用场景

用户提出的是一个完整的 GIS 项目任务，而非单一操作。典型场景：
- 选址分析（设施选址、商店选址、学校选址）
- 适宜性评价（土地适宜性、生态敏感性）
- 灾害评估（洪水淹没、滑坡风险、地震影响）
- 城市分析（人口分布、交通可达性、服务覆盖）
- 环境分析（污染源影响、生态廊道、保护区划定）
- 用户描述"帮我做一个 XX 分析"而非"帮我算一个缓冲区"

## 输入数据要求

综合项目通常需要多源数据：
- 研究区边界（行政边界 datav_boundary 或自定义）
- 影响因子图层（道路、POI、地形、土地利用、人口等）
- 约束条件（保护区、禁建区等）
- 数据格式可以混合（矢量+栅格），但 CRS 必须统一

## 分析思路

GIS 项目工作流的核心是"多准则决策"：将多个空间因子按权重叠加，得到综合评价结果。

通用框架：
1. **明确目标**：要解决什么问题？评价对象是什么？
2. **确定因子**：哪些空间因素影响目标？（可达性、环境、社会经济）
3. **数据准备**：获取/上传各因子数据，统一 CRS 和范围
4. **因子标准化**：不同量纲的因子转为统一评价尺度（0-1 或 1-5 分）
5. **权重确定**：各因子的相对重要性（专家打分、AHP、等权重）
6. **叠加分析**：加权叠加得到综合评价
7. **结果验证**：与实际情况对比，敏感性分析
8. **成果输出**：地图、报告、统计

## 处理流程

### 工作流一：设施选址分析

```
目标：找到最适合建设 XX 设施的位置

1. 确定评价因子（示例：商店选址）
   ├─ 交通可达性 → 道路缓冲区 / 网络服务区
   ├─ 人口密度 → 人口数据核密度
   ├─ 竞争分布 → 同类 POI 缓冲区（负因子）
   ├─ 租金/地价 → 地块属性（负因子）
   └─ 约束条件 → 保护区/禁建区（排除）

2. 数据准备
   ├─ datav_boundary 获取研究区边界
   ├─ amap_poi_search 获取 POI（竞争/配套）
   ├─ download_road_network 获取路网
   ├─ discover_gis_data / download_gis_data 获取人口/土地利用
   └─ 统一 CRS，裁剪到研究区

3. 单因子评价
   ├─ 交通可达性 → network_analysis 服务区 / spatial_buffer 道路缓冲
   ├─ 人口密度 → spatial_interpolate 或 KDE 核密度
   ├─ 竞争影响 → spatial_buffer + spatial_difference（距离竞争越远越好）
   └─ 每个因子转为 0-1 标准化得分（field_calculate 或 execute_python）

4. 加权叠加
   ├─ 确定权重（如交通 0.3、人口 0.4、竞争 0.2、地价 0.1）
   ├─ execute_python：加权栅格叠加（rasterio + numpy）
   └─ 或矢量叠加：spatial_join + field_calculate 加权求和

5. 约束排除
   ├─ spatial_clip 或 spatial_difference 去掉禁建区
   └─ 按阈值筛选适宜区（如得分 > 0.7）

6. 结果输出
   ├─ 适宜性分级图（spatial_graduated_colors）
   ├─ 候选位置排序（spatial_field_stats + 排序）
   ├─ create_chart 因子贡献分析
   ├─ export_pdf 成果图
   └─ 文字解释：推荐位置、各因子得分、局限性
```

### 工作流二：生态适宜性评价

```
1. 确定生态因子：高程、坡度、坡向、植被覆盖(NDVI)、水体、土地利用
2. 数据准备：DEM + 遥感影像 + 土地利用矢量
3. 单因子：dem_analysis(坡度/坡向) + ndvi_analysis + 距离水体(spatial_buffer)
4. 分级标准：每个因子按生态适宜性分 1-5 级
5. 加权叠加：AHP 确定权重
6. 结果：生态适宜性分区（最适宜/适宜/一般/不适宜）
```

### 工作流三：灾害影响评估

```
1. 确定灾害源和影响范围（如洪水水位 → 高程阈值，或污染源 → 缓冲区）
2. 影响范围提取：dem_analysis + 阈值（洪水）/ spatial_buffer（污染源）
3. 受影响要素统计：spatial_select（落在影响区内的建筑/人口/POI）
4. 损失评估：field_calculate 计算受影响人口数、建筑数、经济价值
5. 结果：影响范围图 + 受影响要素统计表 + 损失评估
```

### 工作流四：城市服务覆盖分析

```
1. 确定服务设施（学校/医院/公园）和服务半径
2. spatial_buffer 或 network_analysis 服务区
3. spatial_join 统计每个服务区内的人口/小区
4. spatial_difference 找服务空白区
5. 结果：覆盖率统计 + 空白区定位 + 设施优化建议
```

## 方法选择依据

### 叠加方法

| 方法 | 适用场景 | 工具 |
|------|---------|------|
| 矢量叠加（overlay） | 因子是矢量面，类别少 | spatial_intersect / spatial_union |
| 栅格叠加（地图代数） | 因子是连续表面，多因子 | execute_python（rasterio + numpy） |
| 空间连接 + 属性计算 | 因子可关联到同一评价单元 | spatial_join + field_calculate |

多因子连续评价优先用栅格叠加（计算效率高，结果平滑）；类别型因子用矢量叠加。

### 权重确定方法

- **等权重**：所有因子同等重要，最简单，适合探索性分析
- **专家打分**：领域专家给定权重，最常用
- **AHP（层次分析法）**：成对比较矩阵计算权重，有一致性检验
- **敏感性分析**：改变权重看结果变化，评估稳健性

项目中权重通过 execute_python 实现，Agent 应向用户说明权重假设并建议做敏感性分析。

### 评价尺度

- 连续尺度（0-1）：适合栅格叠加，结果是连续适宜性表面
- 离散尺度（1-5 级）：适合矢量叠加，结果是分级适宜区
- 阈值法（适宜/不适宜）：最简单，适合约束条件

## 推荐工具

| 阶段 | 工具 |
|------|------|
| 数据获取 | datav_boundary, amap_poi_search, amap_geocode, download_road_network, discover_gis_data, download_gis_data |
| 数据准备 | convert_crs, spatial_clip, layer_merge, topology_check |
| 单因子分析 | spatial_buffer, network_analysis, dem_analysis, ndvi_analysis, spatial_interpolate, create_heatmap |
| 叠加分析 | spatial_intersect, spatial_union, spatial_difference, spatial_join, field_calculate, execute_python |
| 统计 | spatial_field_stats, measure_area, create_chart |
| 制图 | spatial_graduated_colors, add_legend, add_north_arrow, export_map, export_pdf |

## 输出结果

综合项目输出应包含：
1. **评价结果图**：适宜性/风险/覆盖分级地图
2. **统计数据**：各等级面积/数量、占比
3. **关键发现**：最适宜区域位置、主要限制因子、空白区
4. **方法说明**：因子清单、权重、分级标准、数据来源
5. **局限性**：数据精度、权重主观性、未考虑因子

Agent 应主动生成结构化的分析结论，而非只返回原始数据。

## 常见问题

### Q1：多因子叠加时数据范围不一致
- 原因：各图层 bbox 不同，或分辨率不同
- 解决：统一用研究区边界 spatial_clip 所有因子；栅格叠加前 reproject 到同一分辨率和范围

### Q2：权重怎么定才合理
- 原因：权重是主观的，不同权重结果差异大
- 解决：先用等权重做基线；再用 2-3 组权重做敏感性分析；报告中说明权重假设和结果稳健性

### Q3：矢量叠加后要素数爆炸
- 原因：多个面图层 overlay 产生大量碎片多边形
- 解决：先用 spatial_dissolve 融合同类区域；减少叠加层数；或改用栅格叠加

### Q4：结果和预期不符
- 原因：因子遗漏、权重不当、数据质量差
- 解决：检查每个单因子结果是否合理；调整权重；补充缺失因子；做敏感性分析

### Q5：项目需要的数据系统里没有
- 解决：先用 discover_gis_data 搜索公开数据源；OSM 可获取道路/建筑/POI/水系；DEM 和遥感影像需账号（Copernicus/USGS）；必要时提示用户上传数据

### Q6：分析流程太长，Agent 中途忘记前面的结果
- 解决：Task Working Memory 自动保存每步代码和 Artifact；Agent 应在每步结束时简要总结中间结果，下一步引用 task 上下文；复杂项目建议分轮对话，每轮完成一个子任务
