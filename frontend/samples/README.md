# 测试数据

把这些 GeoJSON 文件拖入浏览器窗口即可加载到地图，然后用 AI 对话框测试以下命令：

## polygons.geojson — 测试叠置分析
- "对 polygons 做缓冲区 500 米"
- "polygons 和 points 做空间相交"
- "对 polygons 做空间合并"
- "提取 polygons 的质心"
- "按 group 字段融合 polygons"
- "空间连接 polygons 和 points"

## points.geojson — 测试采样/聚类/统计
- "从 points 随机采样 3 个要素"
- "对 points 做聚类 eps=0.01"
- "统计 points 的 score 字段"
- "给 points 生成泰森多边形"

## line.geojson — 测试简化/缓冲区
- "简化 line 容差 0.005"
- "对 line 做缓冲区 200 米"

## cluster.geojson — 测试 DBSCAN 聚类
- "对 cluster 做聚类 eps=0.005 min_samples=3"

## buffer_test.geojson — 测试缓冲区
- "对 buffer_test 做缓冲区 1 km"

## 工具快测（贴到 AI 对话框）
```
对 polygons 做缓冲区 500 米
对 points 按 type 字段融合
从 points 随机采样 n=3
统计 points 的 score 字段
```
