# MCP Server — 把 Gis-WorkTable 工具开放给外部 AI 客户端

Gis-WorkTable 内置一个 **MCP（Model Context Protocol）Server**，把后端全部
`@tool` 注册的 GIS 工具（当前 114 个）暴露给支持 MCP 的外部 AI 客户端
（Claude Code、Cursor 等）。工具清单从注册表自动反射，无需手写维护。

## 启动方式

stdio 传输，独立进程运行：

```bash
python -m backend.services.mcp_server
```

启动后通过 stdin/stdout 与客户端通信，不占用网络端口。

## 暴露的 MCP 工具

| 工具 | 说明 |
| --- | --- |
| `tools_list` | 列出全部 GIS 工具：名称 + 描述 + 参数 JSON Schema（注册表反射） |
| `tool_call(name, arguments)` | 执行任意注册工具（复用服务层，不含 LLM/Agent 循环）；图层产物落盘到会话目录并返回文件路径 |
| `list_layers` | 当前 MCP 会话已注册图层（名称/要素数/几何类型/范围） |
| `get_task_status(task_id)` | 任务状态；`task_id` 省略时列出最近任务 |

`tool_call` 返回结构：

```json
{
  "ok": true,
  "response": "工具返回文本",
  "layers": [{"name": "图层名", "file": "<会话目录>/xxx.geojson", "feature_count": 42}],
  "images": ["/output/uploads/xxx.png"]
}
```

## 路径 Confinement

所有文件读写限制在白名单根目录内。默认白名单：

- 仓库根目录（`Gis-WorkTable/`）
- 系统临时输出目录（`%TEMP%/gis_worktable_output`）

可通过环境变量 `GEOWORKTABLE_MCP_ROOTS` 覆盖（**分号分隔**多个根目录）：

```bash
set GEOWORKTABLE_MCP_ROOTS=D:\gis_data;E:\my_repo\Gis-WorkTable
```

白名单外的本地路径入参会被拒绝并提示（`http(s)://` 等远程 URL 不受限）。

## 在 Claude Code 中配置

项目级配置：在项目根目录创建/编辑 `.mcp.json`，或全局 `claude mcp add`：

```json
{
  "mcpServers": {
    "gis-worktable": {
      "command": "python",
      "args": ["-m", "backend.services.mcp_server"],
      "env": {
        "PYTHONPATH": "E:\\my_repo\\Gis-WorkTable",
        "GEOWORKTABLE_MCP_ROOTS": "E:\\my_repo\\Gis-WorkTable;D:\\gis_data"
      }
    }
  }
}
```

注意：`args` 中的模块路径依赖 `PYTHONPATH` 指向仓库根目录（Windows 路径转义为 `\\`）。

## 在 Cursor 中配置

`~/.cursor/mcp.json`（全局）或项目 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "gis-worktable": {
      "command": "python",
      "args": ["-m", "backend.services.mcp_server"],
      "env": {
        "PYTHONPATH": "E:\\my_repo\\Gis-WorkTable",
        "GEOWORKTABLE_MCP_ROOTS": "E:\\my_repo\\Gis-WorkTable"
      }
    }
  }
}
```

## 使用示例（客户端对话）

配置后可直接在 Claude Code / Cursor 中说：

- 「用 gis-worktable 的 tools_list 看看有哪些 GIS 工具」
- 「tool_call 调用 datav_boundary，参数 place=长沙市，把返回的图层文件读出来」
- 「list_layers 看看当前有哪些图层」

## 依赖

`backend/requirements.txt` 已声明：

```
mcp>=1.0.0
```

## 测试

`backend/tests/test_mcp_server.py` 用 SDK 内存传输客户端验证：
四个 MCP 工具可达、注册表反射数量一致、tool_call 执行 + 图层落盘、
路径 confinement 拦截越界路径。
