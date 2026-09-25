# -*- coding: utf-8 -*-
"""Gis-WorkTable MCP Server

把 tools.py 的全部 @tool 工具开放给外部 AI 客户端（Claude Code / Cursor 等）。
基于官方 mcp Python SDK，stdio 传输，独立入口：

    python -m backend.services.mcp_server

暴露 4 个 MCP 工具（不重复手写清单，全部从 @tool 注册表反射）：
- tools_list():              名称 + 描述 + 参数 JSON Schema
- tool_call(name, arguments): 执行任意注册工具（复用服务层，不含 LLM/Agent 循环），
                              图层产物落盘到会话目录并返回文件路径
- list_layers():             当前会话已注册图层
- get_task_status(task_id):  任务状态（缺省列出任务）

路径 confinement：所有文件读写限制在白名单根目录内。
环境变量 GEOWORKTABLE_MCP_ROOTS（分号分隔）可覆盖，
默认 = 仓库根目录 + 系统临时输出目录（参考 GeoLibre GEOLIBRE_MCP_ROOTS 的做法）。
"""
import os
import json
import datetime

from mcp.server.fastmcp import FastMCP

# PROJ 环境冲突修复（与 main.py/conftest.py 一致）
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

mcp = FastMCP("gis-worktable")

_SESSION_ID = os.environ.get("GEOWORKTABLE_MCP_SESSION", "mcp_default")


# ============================================================
# 路径 confinement
# ============================================================

def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _default_roots() -> list:
    from backend.services.tools import _temp_output_dir, init_temp_dir
    init_temp_dir()
    return [_repo_root(), _temp_output_dir]


def get_allowed_roots() -> list:
    """白名单根目录：GEOWORKTABLE_MCP_ROOTS（分号分隔）优先，默认仓库根 + 临时输出目录"""
    raw = os.environ.get("GEOWORKTABLE_MCP_ROOTS", "").strip()
    if raw:
        return [os.path.abspath(p.strip()) for p in raw.split(";") if p.strip()]
    return [os.path.abspath(p) for p in _default_roots()]


def assert_path_allowed(path: str) -> str:
    """校验路径在白名单内；返回规范化绝对路径。越界抛 PermissionError。"""
    p = os.path.abspath(os.path.expanduser(str(path)))
    for root in get_allowed_roots():
        try:
            if os.path.commonpath([p, root]) == root:
                return p
        except ValueError:
            continue
    raise PermissionError(
        f"路径越界: {path}。允许的根目录: {'; '.join(get_allowed_roots())}"
        "（可用环境变量 GEOWORKTABLE_MCP_ROOTS 配置，分号分隔）")


def _check_args_paths(name: str, arguments: dict) -> None:
    """工具入参 confinement：字符串参数若形似本地文件路径，必须在白名单内。
    http(s) URL 与输出名等非路径参数不受限。"""
    for key, val in (arguments or {}).items():
        if not isinstance(val, str) or not val:
            continue
        v = val.strip()
        if v.startswith(("http://", "https://", "/vsi", "/vsicurl", "s3://", "gs://")):
            continue
        if v.startswith("{") or v.startswith("["):
            continue  # JSON 文本参数
        looks_like_path = ("\\" in v or "/" in v or os.path.isabs(v)
                           or v.lower().endswith(
                               (".tif", ".tiff", ".geojson", ".json", ".gpkg", ".kml",
                                ".kmz", ".gpx", ".dxf", ".zip", ".csv", ".parquet",
                                ".geoparquet", ".fgb", ".pmtiles", ".shp")))
        if looks_like_path:
            assert_path_allowed(v)


# ============================================================
# 工具注册表反射（不手写重复清单）
# ============================================================

def _tool_registry() -> dict:
    """{name: tool}，来自 tools 列表（含执行历史包装层，MCP 调用同样入历史）"""
    from backend.services.tools import tools as tool_list
    return {t.name: t for t in tool_list}


def _args_schema_of(t) -> dict:
    """@tool 的 args_schema (pydantic) → JSON Schema"""
    schema = getattr(t, "args_schema", None)
    if schema is None:
        return {"type": "object", "properties": {}}
    try:
        return schema.model_json_schema()
    except Exception:
        try:
            return schema.schema()
        except Exception:
            return {"type": "object", "properties": {}}


# ============================================================
# 会话产物落盘
# ============================================================

def _session_dir() -> str:
    from backend.services.tools import _temp_output_dir, init_temp_dir
    init_temp_dir()
    d = os.path.join(_temp_output_dir, "mcp_sessions", _SESSION_ID)
    os.makedirs(d, exist_ok=True)
    return d


def _dump_pending_layers(session_tag: str) -> list:
    """把本轮工具产出的图层落盘为 GeoJSON，返回 [{name, file, feature_count}]"""
    from backend.services.tools import get_pending_state
    pending = get_pending_state()
    out = []
    for i, layer in enumerate(pending.get("layers", [])):
        name = layer.get("name") or f"layer_{i}"
        geojson = layer.get("geojson")
        if not isinstance(geojson, dict):
            continue
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60]
        fname = f"{session_tag}_{i}_{safe}.geojson"
        fpath = os.path.join(_session_dir(), fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
        features = geojson.get("features", []) if geojson.get("type") == "FeatureCollection" else [geojson]
        out.append({"name": name, "file": fpath, "feature_count": len(features)})
    return out


# ============================================================
# 4 个 MCP 工具
# ============================================================

@mcp.tool()
def tools_list() -> str:
    """列出 Gis-WorkTable 全部 GIS 工具：名称、描述、参数 JSON Schema（从注册表自动反射）。"""
    registry = _tool_registry()
    items = []
    for name, t in registry.items():
        items.append({
            "name": name,
            "description": (t.description or "").strip(),
            "parameters": _args_schema_of(t),
        })
    return json.dumps({"count": len(items), "tools": items}, ensure_ascii=False)


@mcp.tool()
def tool_call(name: str, arguments: str = "{}") -> str:
    """执行一个 Gis-WorkTable 注册工具。
    name: tools_list 返回的工具名；arguments: JSON 对象字符串（参数名 → 值）。
    返回 JSON：{ok, response, layers:[{name,file,feature_count}], images}。
    图层产物落盘到会话目录，文件路径可直接读取/下载。"""
    registry = _tool_registry()
    t = registry.get(name)
    if t is None:
        return json.dumps({"ok": False, "error": f"工具不存在: {name}"},
                          ensure_ascii=False)
    try:
        args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else {}
    except Exception as e:
        return json.dumps({"ok": False, "error": f"arguments 不是合法 JSON: {e}"},
                          ensure_ascii=False)
    if not isinstance(args, dict):
        return json.dumps({"ok": False, "error": "arguments 应为 JSON 对象"},
                          ensure_ascii=False)
    try:
        _check_args_paths(name, args)
    except PermissionError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    from backend.services.tools import reset_state
    reset_state()
    session_tag = datetime.datetime.now().strftime("%H%M%S")
    try:
        response = t.invoke(args)
        ok = True
    except Exception as e:
        response = f"工具执行失败: {str(e)[:400]}"
        ok = False

    from backend.services.tools import get_pending_state as _gps, _registered_layers
    try:
        layers_out = _dump_pending_layers(session_tag)
    except Exception:
        layers_out = []
    images = []
    try:
        images = [img.get("url") if isinstance(img, dict) else str(img)
                  for img in _gps().get("images", [])]
    except Exception:
        pass
    return json.dumps({
        "ok": ok,
        "response": response,
        "layers": layers_out,
        "images": images,
        "registered_layer_count": len(_registered_layers),
    }, ensure_ascii=False)


@mcp.tool()
def list_layers() -> str:
    """列出当前 MCP 会话已注册的图层（名称/要素数/几何类型/范围）。"""
    from backend.services.tools import _registered_layers
    layers = []
    for name, info in _registered_layers.items():
        layers.append({
            "name": name,
            "feature_count": info.get("feature_count", 0),
            "geometry_types": info.get("geometry_types", []),
            "bbox": info.get("bbox"),
        })
    return json.dumps({"count": len(layers), "layers": layers}, ensure_ascii=False)


@mcp.tool()
def get_task_status(task_id: str = "") -> str:
    """查询任务状态。task_id 为空时列出最近任务；否则返回该任务详情（含产物/执行日志计数）。"""
    from backend.services import task_manager
    if task_id:
        task = task_manager.get_task(task_id)
        if not task:
            return json.dumps({"ok": False, "error": f"任务不存在: {task_id}"},
                              ensure_ascii=False)
        return json.dumps({"ok": True, "task": task}, ensure_ascii=False, default=str)
    tasks = task_manager.list_tasks(_SESSION_ID, include_archived=False)[:20]
    return json.dumps({"count": len(tasks), "tasks": tasks}, ensure_ascii=False, default=str)


# ============================================================
# 入口
# ============================================================

def main():
    print(f"[GIS MCP] 启动 stdio MCP server，会话: {_SESSION_ID}", flush=True)
    print(f"[GIS MCP] 允许根目录: {'; '.join(get_allowed_roots())}", flush=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
