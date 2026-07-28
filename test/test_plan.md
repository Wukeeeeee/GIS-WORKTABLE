# 全功能测试计划

## 测试数据目录
`test/data/` — 存放自生成的测试数据文件，供后续复用

## 测试报告目录
`test/reports/` — 每次测试的结果报告

## 测试流程

每个功能测试三步走：
1. 生成测试数据 → 保存到 `test/data/`
2. 执行功能 → 记录结果
3. 失败则分析原因并修复

## 测试数据生成规则

| 数据 | 生成方式 | 保存文件名 |
|------|---------|-----------|
| 点 (10个) | 北京周边随机点 116.3~116.5, 39.8~40.0 | `test_points.geojson` |
| 线 (3条) | 简单折线 | `test_lines.geojson` |
| 面 (2个) | 矩形 | `test_polygons.geojson` |
| DEM | numpy 10x10 随机高程 | `test_dem.tif` |
| 多光谱 | 4波段 10x10 GeoTIFF | `test_multiband.tif` |
| 道路网 | 简单线网 | `test_roads.geojson` |
