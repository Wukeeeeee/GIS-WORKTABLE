# 阶段一变更摘要：卷帘对比（Swipe）+ 处理历史重跑

## 1. 卷帘对比

### 后端（backend/services/tools.py）
- 新增 `@tool create_swipe(left_layer, right_layer, orientation)`：校验两个图层存在
  （精确 + 子串模糊匹配），向 `_pending_layer_ops` 推送 `{"action": "swipe", left, right, orientation}`
  图层操作指令；orientation 支持 `vertical`（左右分割）/ `horizontal`（上下分割）。
- 新增 `@tool close_swipe()`：推送 `{"action": "swipe_close"}`。
- 图层结果均走既有 `_push_layer/_pending_layer_ops` 通道，未绕过（AST 守卫通过）。

### 前端
- `frontend/js/map.js`：`startSwipe/stopSwipe`。两个图层挂到独立 Leaflet pane
  （`swipeLeftPane`/`swipeRightPane`），**对 pane 的实际渲染子容器（canvas/svg）应用
  clip-path 裁剪**（Leaflet pane 本身是 0 尺寸容器，直接裁 pane 会把内容全部裁掉——
  实测踩坑后修正）；拖动分割线 5%~95%，分割线带拖柄与 ✕ 关闭按钮。
- `frontend/js/chat.js`：op 分发新增 `swipe` / `swipe_close` 两个 case；3D 模式下提示
  仅 2D 支持（不报错）。
- `frontend/js/layers.js`：每个图层行新增「卷帘」按钮——点第一个图层选中为 A
  （按钮高亮），再点另一个图层即开启 A|B 对比；卷帘已开启时点任意「卷帘」按钮关闭。
- `frontend/css/style.css`：分割线/拖柄/armed 态样式。

### 手动入口
图层面板中两个图层的悬停操作按钮 →「卷帘」图标（先点 A 再点 B）。

## 2. 处理历史

### 后端
- 新增 `backend/services/history_service.py`：统一记录（index、tool、args、time、
  ok、layer_ids、task_id、error、duration_ms），持久化到 `cache/tool_history.json`
  （上限 200 条），线程安全；`set_history_file` 供测试隔离。
- `tools.py`：在 `tools` 列表出口统一包装（`_recorded`，StructuredTool 反射包装，
  工具本体零侵入）——Agent 链路每次工具执行自动入历史；`_TOOL_REGISTRY` 保留未包装
  原件供重跑。
- 新增 `@tool list_history(limit)` / `@tool rerun_history(index)`：
  - rerun 用原始参数重跑对应工具，产物作为新图层上图；
  - 重跑前快照注册表，被同名覆盖的旧图层自动以「_原」后缀重新注册保留（不覆盖原图层）；
  - 重跑本身入历史并带 `rerun_of` 标记；历史类工具自身拒绝重跑（防递归）。
- `backend/main.py`：`GET /api/history`、`DELETE /api/history`、
  `POST /api/history/rerun {index}`（返回与聊天侧一致的 layers/layer_ops 结构）。

### 前端
- `frontend/js/history.js`（新）：右侧「处理历史」浮层面板——按时间倒序展示
  编号/工具名/成败徽章/时间/参数 JSON/产物图层，每条带「重跑」与「复制参数」按钮；
  重跑结果经 `GIS.state.addLayer` 上图（新图层名自动加后缀，不覆盖）。
- `frontend/index.html`：快捷栏新增「处理历史」时钟按钮 + 面板结构；
  面板类名用 `toolhist-` 前缀（避开工程面板既有 `.history-item` 等类名冲突）。

## 测试
`backend/tests/test_swipe_history.py`（17 项）：swipe op 推送/模糊匹配/缺图层报错/
横向模式、历史记录经注册链路写入、落盘持久化、重跑参数重放/新图层不覆盖/防自递归。
另将 3 处按对象同一性断言注册的旧守卫测试改为按 name 匹配（tools 列表出口已有包装层）。
