# 阶段三变更摘要：MCP Server（GIS 工具开放给外部 AI 客户端）

## 新增 `backend/services/mcp_server.py`

基于官方 `mcp` Python SDK（FastMCP），stdio 传输，独立入口：

```bash
python -m backend.services.mcp_server
```

### 暴露的 4 个 MCP 工具

| 工具 | 说明 |
| --- | --- |
| `tools_list()` | 全部 @tool 工具的名称 + 描述 + 参数 JSON Schema，**从注册表自动反射**（含 pydantic args_schema → model_json_schema），不手写重复清单 |
| `tool_call(name, arguments)` | 执行任意注册工具（复用服务层，不含 LLM/Agent 循环）；每次调用前 `reset_state()` 隔离，返回 `{ok, response, layers[], images[], registered_layer_count}` |
| `list_layers()` | 当前会话已注册图层（名称/要素数/几何类型/bbox） |
| `get_task_status(task_id)` | 任务状态；缺省列出最近任务（task_manager） |

### 图层产物落盘

tool_call 产出的图层经 `get_pending_state()` 消费后逐个写为 GeoJSON 文件，
落盘到会话目录 `<temp>/gis_worktable_output/mcp_sessions/<session>/`，
返回 `{name, file, feature_count}` 文件路径列表 —— 满足 Result Guard
（产物真实落盘），外部客户端可直接读取文件。

### 路径 Confinement（参考 GeoLibre GEOLIBRE_MCP_ROOTS 做法）

- 白名单根目录：环境变量 `GEOWORKTABLE_MCP_ROOTS`（**分号分隔**）优先；
  默认 = 仓库根目录 + 系统临时输出目录。
- `tool_call` 对每个字符串入参做路径形状检测（本地路径特征/常见 GIS 扩展名），
  白名单外的本地路径直接拒绝并提示；`http(s)://`、`/vsicurl/` 等远程 URL 与
  JSON 文本参数不受限。

### 会话标识

`GEOWORKTABLE_MCP_SESSION` 环境变量（默认 `mcp_default`），决定任务归属与产物目录。

### 工具执行历史

MCP 侧经 `tools` 列表（含阶段一的历史包装层）调用工具，MCP 的调用同样进入
处理历史（`cache/tool_history.json`），与聊天侧同源。

## 文档

`docs/mcp_server.md`：启动方式、四个 MCP 工具说明、confinement 配置、
**Claude Code（项目 `.mcp.json`）与 Cursor（`~/.cursor/mcp.json`）的完整 JSON 配置示例**
（含 PYTHONPATH 与 GEOWORKTABLE_MCP_ROOTS 环境变量写法）。

## 依赖

`backend/requirements.txt` 新增 `mcp>=1.0.0`。

## 测试

`backend/tests/test_mcp_server.py`（8 项，用 SDK 内存传输客户端
`create_connected_server_and_client_session` 验证）：
- 四个 MCP 工具可达
- tools_list 反射数量与 `tools` 列表一致、参数 schema 存在
- tool_call 执行 draw_feature → 图层 GeoJSON 真实落盘且内容合法
- 未知工具 / 非法 JSON 参数的优雅错误返回
- confinement：白名单外路径拒绝（"路径越界"），白名单内路径与 http URL 放行
- list_layers / get_task_status 正常返回
