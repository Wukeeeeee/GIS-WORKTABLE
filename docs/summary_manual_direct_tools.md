# 变更摘要：手动直连工具通道 + 地理质量守卫 + 对标补新工具

## 定位调整（对标吴秋生 GeoLibre 的"手动优先"形态）

审计发现 114 个 @tool 中 103 个在前端无任何直接引用；更关键的是，
原有"手动"空间分析/统计面板实际只是**把一句话发给 AI**（`GIS.chat.send`）——
没有 API Key 就全瘫、慢、且 LLM 可能转述错参数。本轮把确定性小任务全部
改为**按钮直连后端工具**，AI 只负责长任务调度（如"先搜 POI 再做空间分析"）。

## 1. 直连执行通道

- 后端 `POST /api/tools/invoke {name, arguments}`（main.py）：直接调用注册工具，
  不经 LLM；与聊天侧同链路（`_push_layer` 通道上图、自动进处理历史可重跑）。
- 新增 `GET /api/layers/names`：轻量返回后端注册图层名，供面板下拉精确匹配。
- 前端 `GIS.api.invokeTool(name, args)` + `GIS.api.syncLayer(name)`：
  执行前自动把前端自建图层（绘制/演示）补注册进后端（>2 万要素跳过）。
- `GIS.chat.applyToolResult(result)`：统一结果上图（图层/卷帘 op/热力图/
  影像叠加/QA 警告提示/历史面板刷新），聊天与直连共用。

## 2. 空间分析面板重写（spatial.js，7 个 tab 全直连）

缓冲区（含多环）、叠置（相交/合并/差异）、裁剪、几何工具（质心/简化/融合/
聚类/泰森/合并/修几何/查重/分解多部件/面→线/外接矩形/长度字段）、
选择（空间关系/属性条件/近邻/采样）、统计（字段统计/面积量测/空间连接/
分区统计）、数据获取（行政区边界/POI/地震/天气/路网——全是确定性工具）。

空间统计面板（spatial_stats.js）同步直连：Moran's I / Getis-Ord Gi* / KDE。
顺带修正两个假 UI/错换算：删掉无对应工具参数的"显著性水平"选择；
米→度阈值换算（原 UI 填 1000 米，工具收 0.01 度）；KDE 网格选择改为与
工具参数一致的格网数语义。

## 3. 地理质量自检守卫（backend/services/geo_qa.py）

在图层通道出口（`_push_layer`）对每个产出图层自动体检，可疑地理错误变成
显式警告（`qa_warnings` 随 pending 状态返回，前端展示为系统消息）：

- 坐标超出 WGS-84 范围 → 疑似 CRS 未转换 / 经纬度颠倒
- 空结果（0 要素）→ 提示检查过滤条件
- 抽样几何有效性（shapely is_valid）→ 给出 `spatial_fix_geometry` 修复提示
- 退化多边形（顶点数不足）

明确**不做**"经度>90 即颠倒"启发式——中国区域经度普遍 >90，会大面积误报
（开发中自检抓到并移除）。守卫异常打日志不静默，且永不阻塞出图。
测试 `test_geo_qa.py`（14 项）：正常中国/国外数据零误报、四类错误全抓住、
畸形输入不抛异常、图层通道集成。

## 4. 对标 GeoLibre 补齐 6 个新工具（114 → 120）

GeoLibre（opengeos/GeoLibre，1000+ 工具：Vector 313 / Raster 256 / RS 154 /
Hydrology 100 / Terrain 99 / LiDAR 65 / Conversion 49 / Network 26 /
Projection 4）分类对照后，挑我们缺失且高频的补齐：

| 新工具 | 对标类别 | 说明 |
| --- | --- | --- |
| `zonal_statistics` | Raster | 分区统计：面×栅格 → zonal_mean/sum/min/max/count 写回分区属性 |
| `add_length_field` | Vector | 逐要素长度字段（UTM 精确，km） |
| `spatial_explode` | Vector | 多部件分解 Multi* → 单部件 |
| `geometry_convert` | Vector | 面→边界线 / 线→面（polygonize）/ 凸包 / 外接矩形 |
| `raster_resample` | Raster | 按倍数重采样（nearest/bilinear/cubic），GeoTIFF 落盘 + 预览叠加 |
| `raster_reproject` | Projection | 栅格重投影（默认 EPSG:4326），落盘 + 预览叠加 |

后两者接入既有 `dem_result` 影像叠加通道。测试 `test_new_tools.py`（15 项），
其中验证：UTM 长度精度（0.01°≈0.855km）、多部件 1→2、外接矩形顶点坐标、
重投影后 CRS 确实变为 32650、新工具产物过 QA 零警告。

新工具同时接入直连面板（几何工具/统计 tab），AI 与按钮双入口。

## 验证

- 全量 pytest：478 passed + 5 skipped（远程集成测试无网络自动跳过），零回归
- 浏览器实测（无 API Key）：缓冲区、叠置相交、DataV 行政区边界、KDE、
  分解多部件、外接矩形全部直连成功上图；处理历史自动记录可重跑
- 面板下拉合并后端注册名与前端图层名，执行前自动同步补注册

## 后续对标方向（记录备查）

- LiDAR 类（65 工具）完全空白——需要 laspy 依赖，优先级待定
- Hydrology 已有骨架（flowacc 等），可对照补 watershed/stream order 细分
- Whitebox 工具箱规模不追求对标总数，按"高频 + 确定性"逐批补
