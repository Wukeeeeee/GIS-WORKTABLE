# MCP Server — 让外部 AI 客户端调用 GIS-WORKTABLE

GIS-WORKTABLE 内置一个本地 **MCP（Model Context Protocol）Server**。Codex、Claude Code、Cursor 等 MCP 客户端可以使用它调用 GIS 工具；模型由外部客户端提供，因此**不需要在 GIS-WORKTABLE 再配置一份模型 API Key**。外部客户端仍需要自己的模型账户或服务。

当前实现使用本机 `stdio` 传输：MCP 客户端按需启动独立 Python 进程，不开放网络端口。它会执行 GIS 工具并返回文字、元数据或本地结果文件路径；MCP 进程与浏览器工作台不是同一个运行会话，结果文件不会自动同步成当前窗口中的地图图层。

## 客户端接入

## 在 Codex 桌面版中连接（Windows）

先按 README 启动前置安装并确认 `.venv` 可用，然后在 Codex 桌面版打开 **Settings → MCP servers → Add server**，传输类型选 **STDIO**：

- **Command**：`<仓库根目录>/.venv/Scripts/python.exe`
- **Arguments**：`-m`、`backend.services.mcp_server`
- **Working directory**：`<仓库根目录>`
- **Environment（可选）**：`GEOWORKTABLE_MCP_ROOTS=<允许读写的仓库或 GIS 数据目录>`

例如仓库位于 `E:/my_repo/Gis-WorkTable` 时，Command 是 `E:/my_repo/Gis-WorkTable/.venv/Scripts/python.exe`，Working directory 是 `E:/my_repo/Gis-WorkTable`。保存后重启 Codex，在对话中输入 `/mcp` 确认连接。

Codex 菜单名称和配置选项可参考[官方 MCP 文档](https://developers.openai.com/codex/mcp/)。

也可以编辑 `%USERPROFILE%/.codex/config.toml`：

```toml
[mcp_servers.gis_worktable]
command = "E:/my_repo/Gis-WorkTable/.venv/Scripts/python.exe"
args = ["-m", "backend.services.mcp_server"]
cwd = "E:/my_repo/Gis-WorkTable"

[mcp_servers.gis_worktable.env]
GEOWORKTABLE_MCP_ROOTS = "E:/my_repo/Gis-WorkTable;D:/GIS_Data"
```

将示例路径换成你的实际路径。路径白名单只包含你信任的目录；给 MCP 客户端开放目录读写能力前，请先检查连接的工具和客户端权限。

## 手动启动

在仓库根目录的终端运行：

```bash
python -m backend.services.mcp_server
```

启动后通过 stdin/stdout 与客户端通信，不占用网络端口；运行诊断写入 stderr，stdout 留给 MCP 协议。正常使用时由 MCP 客户端自动启动，无需手动运行此命令。

## 暴露的 MCP 工具

| 工具 | 说明 |
| --- | --- |
| `tools_list` | 列出全部 GIS 工具：名称 + 描述 + 参数 JSON Schema（注册表反射） |
| `tool_call(name, arguments)` | 执行任意注册工具（复用服务层，不含 LLM/Agent 循环）；图层产物落盘到会话目录并返回文件路径 |
| `list_layers` | 当前 MCP 会话已注册图层（名称/要素数/几何类型/范围） |
| `get_task_status(task_id)` | 任务状态；`task_id` 省略时列出最近任务 |
| `inspect_url(url)` | 识别公开 GIS 服务/数据 URL 并返回元数据 |
| `fetch_url_data(...)` | 获取指定公开空间数据并返回文件路径与报告 |
| `search_wikidata(query)` | 搜索 Wikidata 地理实体 |
| `search_osm(query)` | 搜索 OpenStreetMap 地名与边界 |

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
        "PYTHONPATH": "<你的Gis-WorkTable仓库根目录绝对路径，如 D:\\projects\\Gis-WorkTable>",
        "GEOWORKTABLE_MCP_ROOTS": "<允许读写的GIS数据根目录，多个用分号分隔>"
      }
    }
  }
}
```

注意：`args` 中的模块路径依赖 `PYTHONPATH` 指向仓库根目录（Windows 路径在 JSON 中需双斜杠 `\\` 转义）。

## 在 Cursor 中配置

`~/.cursor/mcp.json`（全局）或项目 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "gis-worktable": {
      "command": "python",
      "args": ["-m", "backend.services.mcp_server"],
      "env": {
        "PYTHONPATH": "<你的Gis-WorkTable仓库根目录绝对路径>",
        "GEOWORKTABLE_MCP_ROOTS": "<你的Gis-WorkTable仓库根目录绝对路径>"
      }
    }
  }
}
```

## 使用示例（客户端对话）

连接后，先用 `tools_list` 查看当前工具和参数，再让客户端调用专门的 MCP 工具或 `tool_call`。例如：

- “先调用 `tools_list`，告诉我 GIS-WORKTABLE 当前有哪些工具；不要执行任何修改。”
- “调用 `inspect_url` 检查 `https://sampleserver6.arcgisonline.com/arcgis/rest/services/Census/MapServer/2`，告诉我服务图层和要素量级；不要下载数据。”
- “用 `inspect_url` 检查这个公开 FeatureServer URL，说明图层、字段和要素量级；未确认前不要下载全量数据。”
- “调用 `draw_feature` 创建一个坐标为 116.4,39.9 的测试点，并告诉我返回的 GeoJSON 文件位置。”

MCP 客户端可以读写 MCP 进程允许的本地目录。默认白名单包含仓库和临时输出目录；不要把服务直接暴露到公网。若要让云端或其他设备通过 HTTP 访问，需要单独实现并验证认证、授权、租户隔离和传输保护；当前 stdio 实现不提供这些能力。

## 依赖

`backend/requirements.txt` 已声明：

```
mcp>=1.28.1,<2
```

请同步安装 `backend/requirements.txt`，不要仅保留旧环境中的 MCP SDK。若启动时报 `cannot import name 'eval_type_backport'`，这是旧 MCP SDK 与新版 Pydantic 的依赖不兼容；更新项目依赖后再连接。项目使用 MCP 1.x API，尚未验证 MCP 2.x。

## 测试

`backend/tests/test_mcp_server.py` 用 SDK 内存传输客户端验证：
八个 MCP 工具可达、注册表反射数量一致、tool_call 执行 + 图层落盘、
路径 confinement 拦截越界路径。

另有真实 Python 子进程的 STDIO 握手与工具列表测试，覆盖 Windows 非 UTF-8 控制台下日志混入协议的问题；它不等同于已在所有外部客户端逐一完成配置验收。
