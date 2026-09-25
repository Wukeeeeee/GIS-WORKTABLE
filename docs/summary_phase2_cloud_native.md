# 阶段二变更摘要：云原生格式流式加载（COG / PMTiles / GeoParquet / FlatGeobuf）

## 后端

新增 `backend/services/cloud_native.py`（纯函数助手层，@tool / 上传端点 / MCP 三处复用）：

- **COG**：`read_cog`（rasterio `/vsicurl/` 流式 + 降采样 ≤2048px 渲染 PNG）与
  `cog_info`（CRS/范围/尺寸/波段/nodata/统计，统计基于降采样避免全量下载）。
- **PMTiles**：本地文件走 mmap、URL 走自实现 HTTP Range 读取器（`_HttpRangeSource`，
  支持用户自定义代理）；矢量 PMTiles 以数据中心瓦片为起点螺旋扩圈取 ≤16 块 MVT，
  `mapbox-vector-tile` 解码 + shapely 投影转换到 WGS84 → GeoJSON；栅格 PMTiles 取
  中心瓦片做影像叠加预览。
- **GeoParquet / FlatGeobuf**：pyogrio(GDAL) 通道，先 `read_info` 读 metadata
  （要素数/CRS/几何类型/字段），支持 `bbox="minx,miny,maxx,maxy"` 空间过滤与
  `limit` 截断；非 4326 自动重投影。本机 pyogrio wheel 无 Parquet 驱动时自动切
  geopandas+pyarrow 通道（含 GeoParquet 列元数据解析）。
- **GDAL 网络回退**：部分 Windows 机器 curl 编译为 schannel 且不做中间证书补全
  （`schannel: certificate chain is incomplete`），此时自动回退 urllib 下载到临时
  文件再本地解析（上限 300MB）；正常机器仍走 `/vsicurl/` 流式。

`backend/services/tools.py` 新增 5 个 @tool（106 → 114）：
- `load_cog(url, layer_name, max_size)`：PNG 影像叠加（`dem_result` 通道）+ 注册
  同名范围框图层（`_push_layer/_register_layer`，供查询/卷帘）
- `get_cog_info(url)`
- `load_pmtiles(source, layer_name, max_features)`：矢量→GeoJSON 图层；栅格→中心瓦片叠加
- `load_geoparquet(source, layer_name, bbox, limit)` / `load_flatgeobuf(...)`

`backend/main.py`：
- `/api/upload` 新增 `.pmtiles/.parquet/.geoparquet/.fgb` 分支（拖拽/手动上传入口）
- 新增 `POST /api/online/load {source, type, layer_name, bbox}`（连接器面板
  「粘贴 URL」入口；type=auto 按扩展名识别）

`backend/requirements.txt` 新增：`pmtiles>=3.0.0`、`mapbox-vector-tile>=2.0.0`。

## 前端

- 上传对话框 `accept` 与 `upload.js ALLOWED_EXTENSIONS` 新增四类扩展名，
  拖拽 `.pmtiles/.parquet/.fgb` 文件进地图即可加载。
- 连接器（数据源）面板新增「添加在线数据（云原生格式）」区：格式下拉
  （自动识别/COG/PMTiles/GeoParquet/FlatGeobuf）+ URL 输入 + 加载按钮；
  设置页「地理服务」页签顶部新增同名字入口按钮（浮层面板可达）。
- 栅格结果走 `addImageOverlay`，矢量结果走 `GIS.state.addLayer` 统一上图。

## 测试

`backend/tests/test_cloud_native.py`（23 项）：
- 离线单测（本地夹具，确定性）：本地 GeoTIFF 的 info/预览/load_cog 工具链路、
  pmtiles.writer 构造的矢量夹具解码/load_pmtiles、geopandas 写的本地
  GeoParquet/FlatGeobuf 读取/bbox 过滤/limit 截断/超限拒绝、bbox 解析错误。
- 集成测试（`pytest.mark.slow` + 无网络自动 skip，公开测试 URL）：
  - COG: rasterio 仓库 RGB.byte.tif
  - PMTiles: protomaps 官方 spec 夹具 protomaps(vector)ODbL_firenze.pmtiles
    （HTTP Range 流式读取，实测通过）
  - GeoParquet: OGC geoparquet 仓库 example.parquet（实测通过）
  - FlatGeobuf: flatgeobuf 仓库 UScounties.fgb（实测通过）

## 实测记录

- 远程矢量 PMTiles：200 要素 / 4 瓦片解码成功（Firenze 数据，zoom 0-15）
- 本机 GDAL schannel 证书受限场景下 COG/Parquet/FGB 均经下载回退成功加载
