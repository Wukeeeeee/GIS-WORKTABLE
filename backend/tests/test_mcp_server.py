# -*- coding: utf-8 -*-
"""阶段三：MCP Server 测试

用 mcp SDK 内存传输客户端验证：
- tools_list / tool_call / list_layers / get_task_status 四个 MCP 工具可达
- tool_call 执行注册工具并落盘图层产物
- 路径 confinement 拦截白名单外的文件路径
- 注册表反射数量与 tools.py 一致
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import pytest

pytest.importorskip("mcp", reason="未安装 mcp SDK")

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

from mcp.shared.memory import create_connected_server_and_client_session

from backend.services import mcp_server as ms
from backend.services.tools import tools as TOOL_LIST


@pytest.fixture(autouse=True)
def _confine_to_repo(tmp_path, monkeypatch):
    """confinement 白名单限定到仓库根 + tmp（互不干扰）"""
    monkeypatch.setenv("GEOWORKTABLE_MCP_ROOTS", f"{os.path.abspath(os.getcwd())};{tmp_path}")


@pytest.fixture()
def session():
    async def _open():
        return create_connected_server_and_client_session(ms.mcp)
    return _open


def _text(result) -> str:
    return result.content[0].text


def test_mcp_tools_exposed(session):
    async def run():
        async with create_connected_server_and_client_session(ms.mcp) as s:
            result = await s.list_tools()
            return [t.name for t in result.tools]
    names = __import__("asyncio").run(run())
    for n in ("tools_list", "tool_call", "list_layers", "get_task_status"):
        assert n in names


def test_tools_list_reflects_registry(session):
    async def run():
        async with create_connected_server_and_client_session(ms.mcp) as s:
            r = await s.call_tool("tools_list", {})
            return json.loads(_text(r))
    data = __import__("asyncio").run(run())
    assert data["count"] == len(TOOL_LIST)
    names = {t["name"] for t in data["tools"]}
    assert "spatial_buffer" in names and "load_cog" in names and "create_swipe" in names
    # 参数 schema 已反射
    buf = next(t for t in data["tools"] if t["name"] == "spatial_buffer")
    assert "properties" in buf["parameters"]


def test_tool_call_executes_and_dumps_layers(tmp_path):
    import asyncio

    async def run():
        async with create_connected_server_and_client_session(ms.mcp) as s:
            r = await s.call_tool("tool_call", {
                "name": "draw_feature",
                "arguments": json.dumps({
                    "geometry_type": "Point", "coordinates": "116.4,39.9",
                    "layer_name": "MCP测试点"}),
            })
            return json.loads(_text(r))

    data = asyncio.run(run())
    assert data["ok"] is True
    assert data["registered_layer_count"] >= 1
    assert len(data["layers"]) == 1
    layer = data["layers"][0]
    assert layer["name"] == "MCP测试点"
    # 图层产物真实落盘且内容为合法 GeoJSON
    assert os.path.exists(layer["file"])
    gj = json.loads(open(layer["file"], encoding="utf-8").read())
    assert gj["type"] == "FeatureCollection"


def test_tool_call_unknown_tool(session):
    async def run():
        async with create_connected_server_and_client_session(ms.mcp) as s:
            r = await s.call_tool("tool_call", {"name": "no_such_tool", "arguments": "{}"})
            return json.loads(_text(r))
    data = __import__("asyncio").run(run())
    assert data["ok"] is False and "不存在" in data["error"]


def test_tool_call_invalid_json_args(session):
    async def run():
        async with create_connected_server_and_client_session(ms.mcp) as s:
            r = await s.call_tool("tool_call", {"name": "focus_map", "arguments": "not-json"})
            return json.loads(_text(r))
    data = __import__("asyncio").run(run())
    assert data["ok"] is False and "JSON" in data["error"]


def test_path_confinement_blocks_outside_roots(session):
    async def run():
        async with create_connected_server_and_client_session(ms.mcp) as s:
            r = await s.call_tool("tool_call", {
                "name": "load_geoparquet",
                "arguments": json.dumps({"source": "C:/Windows/system32/evil.parquet"}),
            })
            return json.loads(_text(r))
    data = __import__("asyncio").run(run())
    assert data["ok"] is False
    assert "路径越界" in data["error"]


def test_path_confinement_allows_roots_and_urls(session, tmp_path):
    """白名单内的路径与 http URL 不被拦截"""
    import asyncio
    inside = str(tmp_path / "ok.parquet")

    async def run():
        async with create_connected_server_and_client_session(ms.mcp) as s:
            r1 = await s.call_tool("tool_call", {
                "name": "load_geoparquet",
                "arguments": json.dumps({"source": inside}),
            })
            d1 = json.loads(_text(r1))
            r2 = await s.call_tool("tool_call", {
                "name": "load_geoparquet",
                "arguments": json.dumps({"source": "https://example.com/ok.parquet"}),
            })
            d2 = json.loads(_text(r2))
            return d1, d2

    d1, d2 = asyncio.run(run())
    # 路径在白名单内 → 通过 confinement 进入实际加载（文件不存在 → 业务错误而非权限错误）
    assert "路径越界" not in d1.get("error", "")
    assert "路径越界" not in d2.get("error", "")


def test_list_layers_and_task_status(session):
    import asyncio

    async def run():
        async with create_connected_server_and_client_session(ms.mcp) as s:
            await s.call_tool("tool_call", {
                "name": "draw_feature",
                "arguments": json.dumps({
                    "geometry_type": "Point", "coordinates": "121.4,31.2",
                    "layer_name": "MCP上海"}),
            })
            r1 = await s.call_tool("list_layers", {})
            r2 = await s.call_tool("get_task_status", {})
            return json.loads(_text(r1)), json.loads(_text(r2))

    layers, tasks = asyncio.run(run())
    assert any(l["name"] == "MCP上海" for l in layers["layers"])
    assert "tasks" in tasks or "count" in tasks
