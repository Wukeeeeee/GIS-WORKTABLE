# GIS WorkTable 比赛演示步骤

本文对应仓库中的[便携演示工程](../../frontend/samples/GIS-WorkTable-Competition-Demo.giswork)。演示以简体中文和手动 GIS 工具为主，不需要配置 AI 模型 Key。

## 本地数据与分析

1. 在仓库根目录运行 `start.bat`，或按 [README 快速开始](../../README.md#快速开始)启动本地 Web 工作台。
2. 打开 **文件 → 打开工程**，选择**导入本地 .giswork 文件**，导入 `frontend/samples/GIS-WorkTable-Competition-Demo.giswork`。
3. 打开**图层**面板，确认有两个 Polygon 图层：`demo-polygons_1.json` 和 `demo-buffer-500m`，各包含 3 个要素。
4. 打开**空间分析 → 缓冲区**，选择 `demo-polygons_1.json`，设置距离 `500`、单位**米**，运行缓冲。预期新增 1 个结果图层，包含 3 个面要素。
5. 点击**保存工程**并保存到工作台；刷新页面后通过**文件 → 打开工程 → 已保存工程 → 恢复**重新打开，确认两层仍在。

也可从原始输入重新开始：打开**数据 → 导入本地文件**，选择 `frontend/samples/demo-polygons.json`。预览应显示 3 个 Polygon 要素及 `name`、`group`、`score` 字段，再按第 3–5 步完成分析和保存。

## 可选：公开在线数据连通性演示

此步骤访问 Esri 的公开 Census 示例服务，数据主题是美国 Census 区块组。示例端点由第三方维护，可能调整或停止；使用前确认网络可访问，并遵守服务方条款。

1. 打开**数据 → 数据源连接器 → 添加在线数据**。
2. 格式选择 **ArcGIS REST 矢量图层**，粘贴：

   `https://sampleserver6.arcgisonline.com/arcgis/rest/services/Census/MapServer/1`

3. 保留**限量预览**，点击**获取**并等待完成。
4. 当前验收结果为成功获取并加载 1,000 个 Polygon / MultiPolygon 要素。界面明确显示“完整性未检查”；这只能证明该次请求返回了预览，不能说明完整图层已下载。

若现场无法访问该服务，跳过此可选步骤，继续演示已打包的本地工程。在线目录搜索只返回本地索引中的元数据，不能代替对远程端点的实际请求。是否需要 VPN 或代理取决于现场网络和目标服务；不要把个人账号或密钥写进演示文件。

## 当前验收边界

已在 Windows 本地 FastAPI 工作台的内置浏览器中完成 GeoJSON 文件导入、500 米缓冲、`.giswork` 导出后导入和两层恢复；另在公开 ArcGIS REST 示例服务完成 1,000 要素限量预览并加载到图层。未验收完整 ArcGIS 图层下载、所有地区的网络可达性、Shapefile/GeoPackage 上传、干净电脑首次安装或 Electron 完整交付。详细记录见[核心流程验收记录](../validation/core-workflow-acceptance-2026-10-25.md)。
