# 矢量数据处理

## 适用场景

- 上传矢量数据后需要清洗、修复、编辑
- 几何质量差（自相交、无效几何、重叠）需要修复
- 属性表需要计算、增删字段、筛选要素
- 需要合并、拆分、转换几何类型
- 空间分析前的数据预处理
- 数据格式转换（GeoJSON / Shapefile / GeoPackage / CSV）

## 输入数据要求

- 支持格式：GeoJSON、Shapefile(.zip)、GeoPackage、KML/KMZ、GPX、DXF、CSV（经纬度列）
- 几何类型：Point / LineString / Polygon 及 Multi 类型
- CSV 转点需要明确经纬度列名（longitude/latitude 或 lon/lat 或 x/y）
- 属性字段名避免特殊字符和中文（Shapefile 导出时会截断）

## 分析思路

矢量数据处理的核心是"几何 + 属性"的联合操作。处理前必须先评估数据质量：

1. **几何质量**：是否有无效几何、自相交、重复点、环方向错误
2. **属性质量**：是否有缺失值、异常值、字段类型错误
3. **拓扑关系**：面要素之间是否有重叠、缝隙、相邻关系错误
4. **数据完整性**：是否有几何为空的要素、属性为空的要素

处理顺序原则：先修复几何，再处理属性，最后做格式转换。

## 处理流程

```
1. 数据检查
   ├─ get_layer_detail(layer_name) → 几何类型、要素数、字段列表、bbox
   ├─ topology_check(layer_name) → 面图层拓扑错误检测和自动修复
   └─ spatial_field_stats(layer_name, field) → 关键字段统计（缺失值、异常值）

2. 几何修复（按需）
   ├─ topology_check 自动修复无效几何、自相交
   ├─ spatial_simplify(layer_name, tolerance) → 简化几何（减少顶点）
   ├─ spatial_centroid(layer_name) → 面转点（质心）
   └─ execute_python → 自定义修复（如 remove_repeated_points、make_valid）

3. 属性处理
   ├─ field_calculate(layer_name, expression, new_field, field_type) → 计算新字段
   ├─ add_field / delete_field → 字段增删
   ├─ update_attribute(layer_name, field, value, condition_field, condition_value) → 按条件更新
   ├─ delete_features(layer_name, condition_field, condition_value) → 按条件删除
   └─ spatial_select_by_attribute(layer_name, field, operator, value) → 按属性筛选

4. 几何编辑
   ├─ move_features(layer_name, dx, dy, unit) → 平移
   ├─ rotate_features(layer_name, angle) → 旋转
   ├─ scale_features(layer_name, x_factor, y_factor) → 缩放
   ├─ draw_feature(geometry_type, coordinates, layer_name) → 新建要素
   └─ layer_add_geometry(layer_name, lon_field, lat_field) → CSV/表格转点

5. 图层管理
   ├─ layer_merge(layer_names, new_name) → 合并同类型图层
   ├─ layer_split(layer_name, by_field) → 按字段拆分
   ├─ layer_control(action, name, ...) → 显隐/重命名/样式
   └─ export_layer(layer_name, format) → 导出

6. 质量验证
   ├─ get_layer_detail → 确认要素数、字段正确
   ├─ topology_check → 确认无拓扑错误
   └─ spatial_field_stats → 确认计算字段值合理
```

## 方法选择依据

### 几何简化 tolerance 选择

- tolerance 单位与数据 CRS 一致：WGS84 下是度（0.001 ≈ 100米），投影下是米
- 简化过度会丢失形状特征，不足则文件仍大
- 建议：Web 显示用 0.0001-0.001 度，打印出图用 0.00001 度或不简化

### 字段计算 expression 规则

field_calculate 使用安全表达式求值（AST 白名单），支持：
- 算术：+ - * / % **
- 比较：== != < <= > >=
- 逻辑：and or not
- 字段引用：直接写字段名（如 `price / area`）
- 数学函数：通过 execute_python 实现复杂计算
- 不支持：import、函数定义、循环、文件操作

复杂计算（如条件判断、字符串处理）应使用 execute_python。

### 拓扑修复策略

| 问题 | 处理方式 |
|------|---------|
| 自相交 | topology_check 自动用 make_valid 修复 |
| 要素间重叠 | 检测后标注，由用户决定是否合并/裁剪 |
| 缝隙 | 检测后标注，需手动编辑或用 spatial_union 后重新拆分 |
| 无效几何（环方向/开口） | make_valid 自动修复 |
| 重复要素 | execute_python 用 drop_duplicates 去重 |

## 推荐工具

### 数据检查
| 工具 | 用途 |
|------|------|
| `get_layer_detail` | 图层详情（几何类型、要素数、字段、bbox） |
| `topology_check` | 面图层拓扑检查 + 自动修复 |
| `spatial_field_stats` | 字段统计（均值/分位数/缺失/唯一值） |
| `get_registered_layers` | 列出所有图层 |

### 几何操作
| 工具 | 用途 |
|------|------|
| `spatial_simplify` | 几何简化 |
| `spatial_centroid` | 质心提取 |
| `move_features` / `rotate_features` / `scale_features` | 几何变换 |
| `draw_feature` | 新建点/线/面要素 |
| `layer_add_geometry` | 经纬度字段转点图层 |

### 属性操作
| 工具 | 用途 |
|------|------|
| `field_calculate` | 表达式计算新字段 |
| `add_field` / `delete_field` | 字段增删 |
| `update_attribute` | 按条件更新属性 |
| `delete_features` | 按条件删除要素 |
| `spatial_select_by_attribute` | 按属性筛选生成新图层 |

### 图层管理
| 工具 | 用途 |
|------|------|
| `layer_merge` | 合并图层 |
| `layer_split` | 按字段拆分 |
| `layer_control` | 显隐/重命名/颜色/透明度 |
| `export_layer` | 导出 GeoJSON/SHP/CSV |

## 输出结果

- 处理后的新图层自动注册并推送到地图
- 字段计算直接更新原图层属性
- 导出文件保存到 output 目录，返回下载路径
- Agent 应说明：处理了多少要素、新增/删除了什么、数据质量变化

## 常见问题

### Q1：field_calculate 报错"不支持的表达式语法"
- 原因：表达式中使用了函数调用、import、循环等不支持的语法
- 解决：简单算术用 field_calculate；复杂计算（条件、字符串、数学函数）改用 execute_python

### Q2：topology_check 修复后要素数变了
- 原因：make_valid 可能将自相交多边形拆为 MultiPolygon，或消除了零面积碎片
- 解决：这是正常行为；用 get_layer_detail 确认要素数变化，必要时用 spatial_dissolve 重新聚合

### Q3：CSV 上传后没有生成图层
- 原因：CSV 上传只返回 csv_info（列名、行数、预览），不自动转点
- 解决：用 layer_add_geometry(layer_name, lon_field, lat_field) 将经纬度列转为点图层；或在对话中让 AI 处理

### Q4：export_layer 导出 Shapefile 字段名乱码或截断
- 原因：Shapefile 字段名限制 10 字符，中文编码问题
- 解决：优先导出 GeoJSON 或 GeoPackage；导出 Shapefile 前用 add_field 建英文短字段名

### Q5：spatial_select_by_attribute 筛选结果为空
- 原因：字段名拼写错误、值类型不匹配（数字 vs 字符串）、operator 用错
- 解决：先用 get_layer_detail 确认字段名和类型；字符串值加引号；数字比较用 > < 等

### Q6：合并图层后属性字段对不齐
- 原因：两个图层字段名不同，合并后缺失字段填 NaN
- 解决：合并前用 add_field / update_attribute 统一字段名和类型；或用 spatial_join 做属性连接而非简单合并
