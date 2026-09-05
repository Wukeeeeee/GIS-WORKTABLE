# 空间分析

## 适用场景

- 缓冲区分析（点/线/面的影响范围）
- 叠置分析（相交、合并、差异、裁剪）
- 空间查询与空间连接
- 邻近分析（最近邻、距离计算）
- 空间聚类与聚合
- 泰森多边形、随机采样
- 任何需要"根据空间关系处理数据"的任务

## 输入数据要求

- 矢量图层（点/线/面），已注册到系统
- 参与分析的图层 CRS 必须一致（不一致时先 convert_crs）
- 缓冲区分析：输入要素 + 距离参数 + 单位
- 叠置分析：两个同维度图层（面-面、线-面等）
- 空间连接：目标图层 + 连接图层 + 空间关系谓词
- 面积/距离计算：建议先投影到合适坐标系

## 分析思路

空间分析的核心是"要素之间的空间关系"。Agent 应按以下逻辑决策：

1. **分析目标是什么？** 是找范围（缓冲区）、找重叠（叠加）、找关联（连接）、找模式（聚类）还是找位置（查询）？
2. **需要哪些图层？** 确认图层已加载，几何类型匹配分析要求
3. **用什么方法？** 根据目标选择对应工具，注意方法的假设和局限
4. **结果怎么验证？** 抽查要素数、面积、空间位置是否合理

## 处理流程

```
1. 分析前检查
   ├─ get_registered_layers() 确认所需图层存在
   ├─ get_layer_detail() 确认几何类型和要素数
   ├─ 确认 CRS 一致（不一致先 convert_crs）
   └─ 面图层先 topology_check 修复无效几何

2. 缓冲区分析
   ├─ spatial_buffer(layer_name, distance, unit, dissolve)
   ├─ spatial_multi_ring_buffer(layer_name, distances, unit, dissolve)
   └─ 结果验证：measure_area 抽查缓冲区面积

3. 叠置分析
   ├─ spatial_intersect(layer_a, layer_b) → 保留重叠部分
   ├─ spatial_union(layer_a, layer_b) → 合并全部
   ├─ spatial_difference(layer_a, layer_b) → A 减去 B
   ├─ spatial_clip(layer_name, clip_layer) → 用裁剪层截取
   └─ 结果验证：要素数变化、面积守恒检查

4. 空间查询与连接
   ├─ spatial_select(target_layer, source_layer, predicate) → 筛选满足关系的要素
   ├─ spatial_join(target_layer, join_layer, how, predicate) → 属性连接
   ├─ spatial_near(layer_name, target_layer, distance) → 邻近查找
   └─ 结果验证：连接后字段数、匹配率

5. 空间模式分析
   ├─ spatial_cluster(layer_name, eps, min_samples) → DBSCAN 聚类
   ├─ spatial_voronoi(layer_name) → 泰森多边形
   ├─ spatial_sample(layer_name, n, frac) → 随机采样
   └─ 结果验证：聚类数、采样比例

6. 结果展示
   ├─ spatial_graduated_colors / spatial_unique_values → 符号化
   ├─ create_chart → 属性统计图
   ├─ add_legend → 图例
   └─ export_layer / export_map → 导出
```

## 方法选择依据

### 缓冲区分析

| 场景 | 方法 | 注意 |
|------|------|------|
| 单点/线/面固定距离 | spatial_buffer | unit="m" 时内部自动投影 |
| 多距离分级 | spatial_multi_ring_buffer | distances 用逗号分隔字符串 |
| 缓冲区融合 | dissolve=True | 重叠缓冲区合并为一个 |
| 保留各要素独立缓冲区 | dissolve=False | 每个要素一个缓冲区面 |

距离单位：WGS84 数据用 unit="m"（工具内部投影到球面等距方位投影）；投影坐标数据距离单位与投影一致。

### 叠置分析选择

| 需求 | 工具 | 输出 |
|------|------|------|
| 找两个图层的共同区域 | spatial_intersect | 重叠部分（属性合并） |
| 合并两个图层全部范围 | spatial_union | 全部区域（重叠处分割） |
| 从 A 中去掉 B 的部分 | spatial_difference | A-B 的区域 |
| 用 B 的范围截取 A | spatial_clip | A 在 B 内的部分 |

关键区别：intersect 保留双方属性，clip 只保留被裁剪层属性；difference 有方向（A-B ≠ B-A）。

### 空间连接 predicate 选择

参考 01_gis_basics 中的空间关系表。最常用：
- `intersects`：默认选择，有任何接触就算
- `within`：严格在内部（点在面内最准确）
- `contains`：面包含点/线
- `touches`：仅边界接触（找相邻）

### 聚类参数选择

DBSCAN 的 eps 和 min_samples：
- eps：邻域半径（WGS84 下是度，0.001≈100m），根据数据点间距选择
- min_samples：一个簇最少要素数，通常 3-5
- 数据点密集时 eps 取小，稀疏时取大
- 结果中噪声点（label=-1）是正常的

## 推荐工具

### 缓冲区
| 工具 | 用途 |
|------|------|
| `spatial_buffer` | 单环缓冲区 |
| `spatial_multi_ring_buffer` | 多环缓冲区 |

### 叠置分析
| 工具 | 用途 |
|------|------|
| `spatial_intersect` | 相交 |
| `spatial_union` | 合并 |
| `spatial_difference` | 差异 |
| `spatial_clip` | 裁剪 |
| `spatial_dissolve` | 融合（按字段或全图） |

### 空间查询与连接
| 工具 | 用途 |
|------|------|
| `spatial_select` | 空间查询（筛选） |
| `spatial_join` | 空间连接（属性合并） |
| `spatial_near` | 邻近查找 |
| `spatial_select_by_attribute` | 属性查询 |

### 空间模式
| 工具 | 用途 |
|------|------|
| `spatial_cluster` | DBSCAN 聚类 |
| `spatial_voronoi` | 泰森多边形 |
| `spatial_sample` | 随机采样 |
| `spatial_centroid` | 质心 |
| `spatial_simplify` | 几何简化 |

### 量算
| 工具 | 用途 |
|------|------|
| `measure_area` | 面积量算（自动投影） |
| `measure_distance` | 距离量算（Haversine） |

## 输出结果

- 分析结果为新的 GeoJSON 图层，自动注册并推送到地图
- 空间连接结果包含双方属性字段
- 缓冲区结果为面图层
- Agent 应说明：输入图层、分析方法、关键参数、输出要素数、结果空间范围

## 常见问题

### Q1：缓冲区结果是椭圆形不是圆形
- 原因：在 WGS84 经纬度下直接做缓冲区，经度方向被压缩
- 解决：spatial_buffer 的 unit="m" 时内部已自动投影；若仍异常，检查数据 CRS 是否正确

### Q2：spatial_intersect 结果为空
- 原因：两个图层空间上不重叠，或 CRS 不一致
- 解决：用 get_layer_detail 看两个图层的 bbox 是否有交集；统一 CRS 后重试

### Q3：空间连接后字段数没变
- 原因：predicate 选择不当导致匹配率为 0，或 how="left" 时未匹配的字段为 NaN
- 解决：改用 intersects；检查连接图层是否有非几何属性字段；get_layer_detail 确认输出字段

### Q4：面叠置后面积总和对不上
- 原因：重叠区域被分割计算，或有 slivery polygon（碎片多边形）
- 解决：这是正常的；可用 spatial_dissolve 融合后重新算总面积对比；极小碎片可 spatial_simplify 或过滤

### Q5：DBSCAN 聚类所有点都是噪声
- 原因：eps 太小或 min_samples 太大
- 解决：先 measure_distance 看最近邻点间距，将 eps 设为平均间距的 1.5-2 倍；min_samples 降到 3

### Q6：泰森多边形结果范围太大
- 原因：泰森多边形会延伸到无穷远，边界点的多边形非常大
- 解决：用研究区边界 spatial_clip 裁剪泰森多边形结果
