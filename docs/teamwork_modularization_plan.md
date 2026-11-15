# tools.py 分阶段模块化迁移与 /teamwork 实施方案

## 1. 核心现状与边界核验

> 下方“迁移前规模”与“2,090 项测试”是本计划建立时的历史基线，不代表当前工作树规模或当前收集到的测试数。

- **迁移前代码基线**：计划建立时记录 `backend/services/tools.py` 约 **671 KB、14,115 行、273 个函数/类**；这是历史快照。
- **当前工作树核查（2026-11-15）**：`tools.py` 当前为 **5,031 行**（HEAD 为 5,030 行）；`vector.py` 有 **57 个 `@tool` 实现**，合同表现含属性编辑及 move/rotate/scale 几何编辑。混合属性类型的 `geojson_to_export_gdf` 转换实现归 `runtime.py` 所有，`io_export.py` 同对象重导出；`io_export.py` 也拥有文件导出及地图/PDF 导出操作实现，`tools.py` 保留原名 `@tool` 兼容包装并传入权威 pending-op 队列；图层注册变更归唯一 runtime 状态模块，`layer_control` / `focus_map` 实现在 `map_ops.py`，facade 只保留原工具包装。空要素集转换为带 WGS-84 几何列的空 GeoDataFrame。工具门面维持原名和注册顺序，运行时图层注册与同步使用共享状态。独立 `shared_state.py` 和 `registry.py` 仍未建立，`tools.py` 也远未收口为薄门面。
- **当前验证边界**：compat、registry、字段管理、图层生命周期、move/rotate/scale/convert_crs/convert_coordinates 特性与失败反馈组合：143 passed（前轮）；任务管理、adversarial、显式跨会话引用、归档引用恢复、链接删除和归档/恢复竞态：45 passed（本轮）。`find_active_task_for_session` 磁盘回扫并发删除/创建竞态有确定性屏障回归；显式跨会话引用已持久化并在缓存清空后恢复，旧版缺 `linked_sessions` 的任务仍可读取。显式引用归档任务时恢复为 active 并切换两个相关 session 索引；删除链接任务会清理全部活跃索引，删除/归档失败保留既有状态。已修正空旋转图层失败分类并将 `rotate_features` 迁入 vector；0° 旋转不再误报方向或产生副作用。`convert_crs` 和 `convert_coordinates` 均拒绝 EPSG:3857 area-of-use 外数据并保留边界内输入。未跑后端全量；“2,090 项”仅为计划初始基线，不代表本次收集数。
- **兼容性门禁进度**：`backend/tests/test_tool_modules_compat.py` 检查门面重导出的可变共享状态身份、输出目录动态转发、domain modules 对 runtime 注册表的单一引用、vector 与 runtime `_pending_layer_ops` 单一引用，以及 vector 工具所属关系、门面对象身份与注册表顺序；目前覆盖 `add_field`/`delete_field`/`move_features`/`rotate_features`/`scale_features` 门面身份和 `geojson_to_export_gdf` 的 runtime 单一所有权。最新 compat 与 registry 对应测试已通过；它仍不等于全部公开符号兼容性审计完成。
- **核心风险点**：
  1. **导入遮蔽（Import Shadowing）**：绝不能同名共存 `backend/services/tools.py` 与 `backend/services/tools/`，否则在不同运行环境和导入语法下会触发模块与包的解析冲突。
  2. **隐式全局状态耦合**：文件中存在 `_registered_layers`、`_tile_cache`、`_geocode_cache`、`_custom_proxy`、任务上下文锁等，必须先确立“状态唯一归属”，严防拆分后产生状态分裂或多份副本。

---

## 2. 目标架构设计

采用独立子包 `tool_modules/`，原 `tools.py` 退化为薄兼容门面（Facade）：

```text
backend/services/
├── tools.py                     # 唯一兼容门面：重导出公开符号、组装注册表、转发状态访问
└── tool_modules/
    ├── __init__.py
    ├── shared_state.py          # 状态归属中心：图层注册表、锁、缓存、代理配置与存取方法
    ├── registry.py              # 工具注册中心：@tool 注册与 _TOOL_REGISTRY 组装调度
    ├── io_export.py             # 领域 1（低耦合）：Shapefile、GeoJSON、COG、GeoPackage 导出
    ├── vector.py                # 领域 2（中耦合）：缓冲区、相交、裁剪、空间关联、质心等矢量分析
    ├── network.py               # 领域 3（中耦合）：最短路径、可达圈、服务区凸包计算
    ├── raster.py                # 领域 4（高耦合）：栅格计算器、重采样、重分类、波段代数
    └── terrain.py               # 领域 5（高耦合）：DEM 坡度、坡向、山体阴影、汇流与水文计算
```

### 状态归属原则
所有原先在 `tools.py` 内的全局变量转移至 `tool_modules/shared_state.py`。
`tools.py` 通过引用绑定重导出（例如 `_registered_layers = shared_state._registered_layers`），或通过属性转发确保读取和原地就改时操作的是同一个字典/对象。

---

## 3. 分阶段迁移步骤 (Staged Migration)

禁止多个 Agent 一窝蜂直接修改 `tools.py`，必须按明确的依赖序推进：

```mermaid
flowchart TD
    S1["阶段 1：状态归属与兼容器搭建<br/>(创建 shared_state.py, registry.py, test_compat)"] --> S2["阶段 2：低耦合试点迁移<br/>(剥离 io_export.py，tools.py 转发导出，跑通测试)"]
    S2 --> S3["阶段 3：独立矢量与网络迁移<br/>(剥离 vector.py, network.py，验证关联测试)"]
    S3 --> S4["阶段 4：高耦合栅格与地形水文迁移<br/>(剥离 raster.py, terrain.py，验证空间测试)"]
    S4 --> S5["阶段 5：全量回归与收口<br/>(tools.py 最终瘦身，全量跑通 2,090 项测试)"]
```

1. **阶段 1：骨架与状态收拢**
   - 新建 `backend/services/tool_modules/shared_state.py` 与 `registry.py`。
   - 新建兼容性测试套件 `backend/tests/test_tool_modules_compat.py`，冻结 `tools.py` 现有公开符号与全局变量签名。
2. **阶段 2：低耦合先行试点（`io_export.py`）**
   - 提取文件转换与导出相关逻辑（代码纯度高、对外部全局状态依赖少）。
   - 在 `tools.py` 补充符号重导出，运行对应测试确认无损。
3. **阶段 3：矢量与网络分析解耦（`vector.py` / `network.py`）**
   - 依赖 `shared_state` 的图层解析与数据提取。
   - 验证 `backend/tests/layered/test_layer3_gis_tools.py` 等相关测试。
4. **阶段 4：栅格与地形水文解耦（`raster.py` / `terrain.py`）**
   - 处理 DEM Provider 与复杂缓存逻辑。
   - 验证栅格重投影、坡度计算等高耦合逻辑。
5. **阶段 5：收口与全量回归**
   - `tools.py` 彻底精简为纯导入代理与门面。
   - 运行全量 2,090 项测试无失败。

---

## 4. 修正后的 /teamwork 启动 Prompt

```text
/teamwork 对 Gis-WorkTable 的 14,115 行巨石服务 backend/services/tools.py 启动分阶段模块化迁移。

【核心原则】
1. 架构方案：保留 backend/services/tools.py 作为向后兼容门面，新建 backend/services/tool_modules/ 目录承载实现，严防模块/包同名遮蔽。
2. 状态先行：必须先在 tool_modules/shared_state.py 中统一定义图层注册表、锁、缓存及代理配置，tools.py 仅做兼容转发，禁止多重副本。
3. 验收红线：现有全部 2,090 项 pytest 测试必须保持 100% 通过，不得为了迁移删改既有断言。

【分工与推进时序】
- Agent A (架构与状态)：负责建立 tool_modules/shared_state.py、registry.py 及符号兼容性测试，定义模块切分标准；
- Agent B (IO与矢量分片)：先迁移低耦合的 io_export.py，再迁移 vector.py 与 network.py，每完成一个切片即在 tools.py 建立导出并跑对应测试；
- Agent C (栅格与地形水文)：负责高耦合的 raster.py 与 terrain.py 迁移，理顺 DEM 与缓存调用；
- Agent D (流水线审计与回归)：统筹分阶段验收，监督 tools.py 符号完整性，最终运行全量 2,090 项测试并生成迁移前后行数与架构对照报告。
```
