from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import io
from io import BytesIO
import json
import subprocess, datetime, time, os, asyncio, functools
from backend.services.ai_service import chat_with_ai, clear_memory, test_key, request_cancel, _TEMP_OUTPUT_DIR
from backend.services.llm_config import LLMConfig, resolve_llm_config
from backend.services.tools import _register_layer, _unregister_layer
from backend.services.layer_service import inspect_geojson
from backend.services import project_service


# ===== 版本信息（服务器启动时自动生成） =====
_SERVER_START_TIME = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
_GIT_COMMIT = ""
_GIT_DIRTY = False
try:
    _GIT_COMMIT = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=3,
        cwd=os.path.dirname(os.path.dirname(__file__))
    ).stdout.strip()
    # 检测是否有未提交的改动
    _status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, timeout=3,
        cwd=os.path.dirname(os.path.dirname(__file__))
    ).stdout.strip()
    _GIT_DIRTY = bool(_status)
except Exception:
    _GIT_COMMIT = "unknown"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=10000)  # 10KB 以上自动 gzip 压缩

# 挂载临时输出目录为静态文件（不触发 Live Server 刷新）
app.mount("/output", StaticFiles(directory=_TEMP_OUTPUT_DIR), name="output")

# ---- 请求体数据结构 ----
class ChatRequest(BaseModel):
    message: str                          # 用户发送的消息
    session_id: str = "default"           # 会话ID，用来区分不同的聊天会话
    api_key: Optional[str] = None         # API 密钥（迁移兼容：llm_config 为空时兜底）
    provider: str = "deepseek"            # 旧 provider 名，仅展示/兼容，不参与调用逻辑
    llm_config: Optional[LLMConfig] = None  # 完整 Provider 配置（主数据源，含 base_url/model/api_key/开关）
    force_skills: list = []              # 用户通过 chip 标签指定的技能
    amap_key: Optional[str] = None        # 高德地图 Web API 密钥
    pending_layer: Optional[dict] = None  # 待分析的图层附件（前端输入框上方暂存）
    task_id: Optional[str] = None         # 任务 ID（跨轮保持）

class TestKeyRequest(BaseModel):
    llm_config: Optional[LLMConfig] = None  # 通用测速入参即 cfg
    provider: str = ""                    # 旧前端只传 key/provider 时的迁移兜底
    api_key: str = ""

class NetworkRequest(BaseModel):
    geojson: dict                        # 路网数据
    type: str                            # route / service_area / closest_facility
    origin: Optional[list] = None        # 起点 [lng, lat]
    dest: Optional[list] = None          # 终点 [lng, lat]
    facility: Optional[list] = None      # 设施点 [lng, lat]
    events: Optional[list] = None        # 事件点列表 [[lng,lat], ...]
    waypoints: Optional[list] = None     # 途经点列表 [[lng,lat], ...]
    breaks: Optional[list] = None        # 服务区断值 [1000, 3000, 5000]
    n: int = 3                           # 最近设施返回条数

class SnapRequest(BaseModel):
    geojson: dict                        # 路网数据
    point: list                          # [lng, lat]

# ===== 聊天接口 =====
# 前端发消息到这里，用 LangGraph Agent 处理
@app.post("/api/chat")
async def chat(request: ChatRequest):
    # 如果前端附带了待分析图层，注入到消息中
    msg = request.message
    pending = request.pending_layer
    if pending and pending.get("geojson"):
        import json
        layer_name = pending.get("name", "未命名图层")
        layer_type = pending.get("type", "未知")
        layer_coords = pending.get("coords", "")
        layer_count = pending.get("count", 0)
        geo_json_str = json.dumps(pending["geojson"], ensure_ascii=False, indent=2)
        max_geo_len = 8000
        if len(geo_json_str) > max_geo_len:
            geo_json_str = geo_json_str[:max_geo_len] + "\n  // ... (已截断)"
        msg = (
            f"[附图层: {layer_name}]\n"
            f"类型: {layer_type}\n"
            f"坐标: {layer_coords}\n"
            f"要素数: {layer_count}\n\n"
            f"GeoJSON:\n```json\n{geo_json_str}\n```\n\n"
        ) + msg
    cfg = resolve_llm_config(request.llm_config, request.provider or "", request.api_key or "")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, functools.partial(
        chat_with_ai,
        message=msg,
        session_id=request.session_id,
        cfg=cfg,
        force_skills=request.force_skills,
        amap_key=request.amap_key,
        provider=request.provider or "",
    ))
    # result 已包含 layers / images / heatmap / clear_layers / pending_suggestions / reasoning
    # 从 chat_with_ai 直接返回给前端，不需要再读全局变量
    response_text = result.get("response", "")

    # 组装前端响应（保持与原格式兼容）
    output = {"response": response_text}
    # 任务 ID（跨轮保持）
    if result.get("task_id"):
        output["task_id"] = result["task_id"]
    # 思考过程（reasoning 开启时有）—— 前端折叠「思考」块展示
    if result.get("reasoning"):
        output["reasoning"] = result["reasoning"]

    # 如果有图层
    layers = result.get("layers", [])
    if layers:
        output["layers"] = layers
        # 兼容旧格式：第一个图层作为 geojson + layerName
        if layers and len(layers) > 0:
            output["geojson"] = layers[0].get("geojson")
            output["layerName"] = layers[0].get("name", "")

    # 如果有待处理的 AOI 候选列表（兼容新旧格式）
    suggest_data = result.get("pending_suggestions")
    if suggest_data:
        if isinstance(suggest_data, dict):
            output["pending_suggestions"] = suggest_data.get("suggestions")
            suggest_data["sent"] = True
        else:
            output["pending_suggestions"] = suggest_data

    # 如果 AI 调用了 clear_layers
    if result.get("clear_layers"):
        output["clear_layers"] = True

    # 如果有图表图片
    images = result.get("images", [])
    if images:
        print(f"[GIS Debug] 返回 {len(images)} 个图片/文件: {images}", flush=True)
        output["images"] = images

    # 如果有热力图数据
    heatmap = result.get("heatmap")
    if heatmap:
        output["heatmap"] = {
            "points": heatmap["points"],
            "name": heatmap.get("name", "热力图"),
            "options": heatmap.get("options", {}),
        }

    # 图层控制操作
    layer_ops = result.get("layer_ops", [])
    if layer_ops:
        output["layer_ops"] = layer_ops

    # 待确认动作（前端渲染「继续/取消」按钮；非流式 fallback 也一致）
    try:
        from backend.services import pending_action as _pa
        output["confirm_pending"] = _pa.describe_action(
            _pa.get_pending_action(request.session_id or "default"))
    except Exception:
        output["confirm_pending"] = None

    return output

def _synthetic_done_stream(result: dict):
    """把确定性"继续/确认"处理结果包成 SSE done 事件，前端照常渲染图层。"""
    payload = {
        "type": "done",
        "response": result.get("response", ""),
        "reasoning": result.get("reasoning"),
        "layers": result.get("layers", []),
        "images": result.get("images", []),
        "heatmap": result.get("heatmap"),
        "clear_layers": result.get("clear_layers", False),
        "layer_ops": result.get("layer_ops", []),
        "pending_suggestions": result.get("pending_suggestions"),
        "confirm_pending": result.get("confirm_pending"),
        "task_id": result.get("task_id"),
    }
    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式聊天接口，实时推送 Agent 执行进度"""
    from backend.services.graph import run_agent_stream
    from backend.services.ai_service import (
        _build_system_content, _build_langgraph_messages, _get_or_create_history,
        _try_handle_confirm_command, commit_assistant_reply,
    )
    from backend.services import pending_action as _pa

    cfg = resolve_llm_config(request.llm_config, request.provider or "", request.api_key or "")
    amap_key = request.amap_key or ""
    session_id = request.session_id or "default"

    _SSE_HEADERS = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    # 附图层分析时不做短指令拦截（消息语义是被附加的图层）
    has_attachment = bool(request.pending_layer and request.pending_layer.get("geojson"))

    # === 确定性短指令：pending task 的“继续/确认/执行/取消”直接处理，不走 LLM ===
    if not has_attachment:
        handled = _try_handle_confirm_command(session_id, request.message)
        if handled is not None:
            return StreamingResponse(
                _synthetic_done_stream(handled),
                media_type="text/event-stream",
                headers=_SSE_HEADERS,
            )
        # 正常 Agent 流程：先清掉上一轮遗留 pending（本轮结束时由 auto-promote 重新挂起）
        _pa.clear_pending_action(session_id)

    # 构建 system prompt + 消息（复用 ai_service 的构建逻辑）
    force_skills = request.force_skills or []
    history = _get_or_create_history(session_id, request.message)
    system_content, skill_text, _ = _build_system_content(cfg, request.message, force_skills)

    # 如果前端附带了待分析图层，将 GeoJSON 注入到用户消息中（同时进入 agent 上下文和校验器）
    original_message = request.message
    pending = request.pending_layer
    if pending and pending.get("geojson"):
        layer_name = pending.get("name", "未命名图层")
        layer_type = pending.get("type", "未知")
        layer_coords = pending.get("coords", "")
        layer_count = pending.get("count", 0)
        geo_json_str = json.dumps(pending["geojson"], ensure_ascii=False, indent=2)
        max_geo_len = 8000
        if len(geo_json_str) > max_geo_len:
            geo_json_str = geo_json_str[:max_geo_len] + "\n  // ... (已截断，完整数据共 " + str(len(geo_json_str)) + " 字符)"
        layer_ctx = (
            f"[用户附带了图层「{layer_name}」等待分析]\n"
            f"类型: {layer_type}\n"
            f"坐标: {layer_coords}\n"
            f"要素数: {layer_count}\n\n"
            f"图层 GeoJSON 数据:\n```json\n{geo_json_str}\n```\n\n"
        )
        # 注入到 history 最后一条用户消息（给 agent 上下文）
        if history and history[-1].get("role") == "user":
            history[-1]["content"] = layer_ctx + history[-1]["content"]
        # 也注入到 original_message（给校验器）
        original_message = layer_ctx + original_message

    langgraph_messages = _build_langgraph_messages(system_content, history)

    def _persisted_stream():
        """流式执行 run_agent_stream；done 事件到达时把 AI 回复写回会话历史并落盘。
        修复 SSE 模式此前从不写回 assistant → 下一轮模型看不到上一轮 AI 说了什么。"""
        try:
            for line in run_agent_stream(
                messages=langgraph_messages,
                cfg=cfg,
                amap_key=amap_key,
                skill_text=skill_text,
                original_message=original_message,
                session_id=session_id,
            ):
                if line.startswith("data: "):
                    try:
                        _evt = json.loads(line[6:])
                    except Exception:
                        _evt = None
                    if _evt and _evt.get("type") == "done":
                        commit_assistant_reply(
                            session_id,
                            _evt.get("response", ""),
                            _evt.get("reasoning"),
                        )
                yield line
        except GeneratorExit:
            pass

    return StreamingResponse(
        _persisted_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )

@app.post("/api/cancel")
async def cancel_request():
    """取消当前 AI 请求"""
    result = request_cancel()
    return {"status": "ok", "message": result}

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/layers")
async def list_layers():
    from backend.services.tools import _registered_layers
    layers = []
    for name, info in _registered_layers.items():
        layers.append({
            "name": name,
            "geojson": info.get("geojson"),
            "bbox": info.get("bbox"),
            "style": info.get("style"),
        })
    return {"layers": layers}

@app.post("/api/reset_state")
async def api_reset_state():
    from backend.services.tools import reset_state
    reset_state()
    return {"status": "ok", "message": "状态已重置"}

@app.get("/api/session_logs")
async def session_logs():
    from backend.services.tools import _exec_call_count
    return {"logs": [], "exec_count": _exec_call_count}

@app.post("/api/session_logs/clear")
async def clear_session_logs():
    import backend.services.tools as tools_mod
    tools_mod._exec_call_count = 0
    return {"status": "ok", "message": "日志已清除"}

@app.get("/api/version")
async def version():
    return {
        "commit": _GIT_COMMIT,
        "start_time": _SERVER_START_TIME,
        "dirty": _GIT_DIRTY,
    }

# ===== 清除记忆 =====
# 前端点 "+" 按钮时调用，清空后端内存里的对话历史记录
@app.delete("/api/chat/memory")
async def clear_chat_memory(session_id: str = "default"):
    clear_memory(session_id)
    return {"status": "ok", "message": "记忆已清除"}

# ===== 测试 LLM 连接（通用） =====
# 前端设置面板点 [测速] 调用；入参即 cfg —— 任意 OpenAI 兼容接口都能测。
# 返回 { success: true/false, message: "连接成功"/"密钥无效" }
@app.post("/api/test-key")
async def test_key_endpoint(request: TestKeyRequest):
    # 兼容旧前端：只带 provider + api_key 时翻译成内置默认 cfg
    cfg = resolve_llm_config(request.llm_config, request.provider or "", request.api_key or "")
    success, message = test_key(cfg)
    return {"success": success, "message": message}

@app.get('/api/boundary')
async def get_boundary_api(place: str = "长沙市"):
    """从阿里云 DataV 获取行政边界（国内可访问），返回 GeoJSON"""
    try:
        from backend.services.datav_service import fetch_boundary
        data = fetch_boundary(place)
        if data is None:
            return {"error": f"DataV 未找到「{place}」的边界数据"}
        return {"geojson": data, "name": f"{place}边界"}
    except Exception as e:
        return {"error": str(e)}

@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    import os, tempfile, zipfile, orjson
    loop = asyncio.get_event_loop()
    content = await file.read()
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()

    # GeoJSON 已有内存副本，跳过磁盘写；其余格式落地供 AI 后续处理
    saved_path = None
    if ext not in ('.geojson', '.json'):
        upload_dir = os.path.join(_TEMP_OUTPUT_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        saved_path = os.path.join(upload_dir, filename)
        with open(saved_path, 'wb') as f:
            f.write(content)

    # ===== GeoJSON =====
    if ext == '.geojson' or ext == '.json':
        geojson_data = await loop.run_in_executor(None, orjson.loads, content)
        if isinstance(geojson_data, dict) and geojson_data.get('type') in ('FeatureCollection', 'Feature'):
            _register_layer(filename, geojson_data)
            return {"geojson": geojson_data, "name": filename}
        # 支持 GeometryCollection → 转 FeatureCollection
        if isinstance(geojson_data, dict) and geojson_data.get('type') == 'GeometryCollection':
            geoms = geojson_data.get('geometries', [])
            features = [{"type": "Feature", "geometry": g, "properties": {}} for g in geoms if g]
            fc = {"type": "FeatureCollection", "features": features}
            _register_layer(filename, fc)
            return {"geojson": fc, "name": filename}
        return {"error": "文件不是有效的 GeoJSON 格式"}

    # ===== SHP (zip 包) =====
    if ext == '.zip':
        # 看看 zip 里有没有 .shp
        with zipfile.ZipFile(BytesIO(content)) as zf:
            shp_files = [n for n in zf.namelist() if n.endswith('.shp')]
            if not shp_files:
                return {"error": "ZIP 包中没有找到 .shp 文件"}
            with tempfile.TemporaryDirectory() as tmpdir:
                zf.extractall(tmpdir)
                shp_path = os.path.join(tmpdir, shp_files[0])
                if not os.path.exists(shp_path):
                    return {"error": "无法读取 Shapefile"}
                import geopandas as gpd
                gdf = await loop.run_in_executor(None, functools.partial(gpd.read_file, shp_path))
                geojson_data = gdf.__geo_interface__
                name = os.path.splitext(shp_files[0])[0]
                _register_layer(name, geojson_data)
                return {"geojson": geojson_data, "name": name}

    # ===== GPKG / KML / GPX 等（geopandas 支持的多图层格式） =====
    supported = {'.gpkg', '.kml', '.kmz', '.gpx', '.dxf'}
    if ext in supported:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            import geopandas as gpd
            import pyogrio
            # 探测所有图层，取首个非空图层
            layers = pyogrio.list_layers(tmp_path)
            gdf = None
            for lname, _ in layers:
                try:
                    gdf = await loop.run_in_executor(
                        None, functools.partial(gpd.read_file, tmp_path, layer=lname)
                    )
                    if gdf is not None and not gdf.empty:
                        break
                except Exception:
                    continue
            if gdf is None or gdf.empty:
                return {"error": "文件未包含有效的地理数据"}
            geojson_data = gdf.__geo_interface__
            name = os.path.splitext(filename)[0]
            _register_layer(name, geojson_data)
            return {"geojson": geojson_data, "name": name}
        except Exception as e:
            return {"error": f"无法读取 {ext} 文件: {str(e)[:200]}"}
        finally:
            try: os.unlink(tmp_path)
            except: pass

    # ===== GeoTIFF 栅格加载 =====
    if ext in ('.tif', '.tiff'):
        try:
            import rasterio
            from rasterio.warp import transform_bounds
            import numpy as np
            from PIL import Image

            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
                tmp.write(content)
                tif_path = tmp.name

            with rasterio.open(tif_path) as src:
                nodata = src.nodata
                if src.count >= 3:
                    red = src.read(1).astype(np.float64)
                    green = src.read(2).astype(np.float64)
                    blue = src.read(3).astype(np.float64)
                else:
                    band = src.read(1).astype(np.float64)
                    red = green = blue = band

                if nodata is not None:
                    mask = (red == nodata) & (green == nodata) & (blue == nodata)
                else:
                    mask = None

                def norm(b):
                    b = np.clip(b, np.percentile(b[~np.isnan(b)], 2), np.percentile(b[~np.isnan(b)], 98)) if np.isfinite(b).any() else b
                    b = (b - b.min()) / (b.max() - b.min() + 1e-10) * 255
                    return b.astype(np.uint8)

                rgb = np.stack([norm(red), norm(green), norm(blue)], axis=-1)
                if mask is not None:
                    rgb[mask] = 0

                img = Image.fromarray(rgb)
                name = os.path.splitext(filename)[0]
                png_name = f"{name}.png"
                png_path = os.path.join(upload_dir, png_name)
                img.save(png_path)

                if src.crs and src.crs.to_string() != 'EPSG:4326':
                    bounds_wgs84 = transform_bounds(src.crs, 'EPSG:4326', *src.bounds)
                else:
                    bounds_wgs84 = src.bounds
                w, h = src.width, src.height

            try: os.unlink(tif_path)
            except: pass

            return {
                "raster_info": {
                    "filename": png_name,
                    "url": f"/output/uploads/{png_name}",
                    "bounds": list(bounds_wgs84),
                    "width": w,
                    "height": h,
                },
                "message": f"已加载栅格图层: {name}"
            }
        except ImportError:
            return {"error": "栅格处理依赖 rasterio/PIL，请安装: pip install rasterio pillow numpy"}
        except Exception as e:
            import traceback
            return {"error": f"GeoTIFF 处理失败: {str(e)[:300]}"}

    # ===== CSV（保存文件，让AI处理转换） =====
    if ext == '.csv':
        try:
            content_str = content.decode('utf-8-sig')
            import pandas as pd
            from io import StringIO
            df = pd.read_csv(StringIO(content_str))
            columns = df.columns.tolist()
            preview = df.head(3).to_dict(orient='records')

            return {
                "csv_info": {
                    "filename": filename,
                    "rows": len(df),
                    "columns": columns,
                    "preview": preview,
                    "path": saved_path
                },
                "message": f"CSV已保存，共{len(df)}行，列名：{', '.join(columns)}"
            }
        except Exception as e:
            return {"error": f"CSV 读取失败: {str(e)[:200]}"}

    return {"error": f"不支持的文件格式: {ext}，支持: .geojson .json .gpkg .kml .kmz .gpx .dxf .tif .tiff .zip(含shp)"}

	# ===== 工程保存/加载 =====
class ProjectSaveRequest(BaseModel):
    project_id: Optional[str] = None
    name: str = ""
    session_id: str = "default"
    provider: str = "glm-routed"
    map_state: dict = {}
    messages: list = []
    layers: list = []

class ProjectRenameRequest(BaseModel):
    name: str

@app.post("/api/projects/auto-save")
async def auto_save_project():
    """由前端在对话完成后调用，自动保存当前工程"""
    from backend.services.ai_service import get_session_state, conversation_history
    session_id = "default"
    state = get_session_state(session_id)
    result = project_service.auto_save(
        session_id=session_id,
    )
    if result is None:
        return {"id": None, "note": "无消息，跳过保存"}
    return result

@app.get("/api/projects")
async def list_projects():
    projs = project_service.list_projects()
    return {"projects": projs}

@app.post("/api/projects")
async def save_project(req: ProjectSaveRequest):
    result = project_service.save_project(
        project_id=req.project_id,
        name=req.name or "未命名工程",
        session_id=req.session_id,
        provider=req.provider,
        map_state=req.map_state,
        messages=req.messages,
        layers=req.layers,
    )
    return result

@app.get("/api/projects/{project_id}")
async def load_project(project_id: str):
    result = project_service.load_project(project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return result

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    project_service.delete_project(project_id)
    return {"success": True}

@app.delete("/api/projects")
async def delete_all_projects():
    project_service.delete_all_projects()
    return {"success": True}

@app.post("/api/projects/{project_id}/rename")
async def rename_project(project_id: str, req: ProjectRenameRequest):
    result = project_service.rename_project(project_id, req.name)
    if result is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return result

@app.get("/api/projects/{project_id}/export")
async def export_project(project_id: str):
    data = project_service.export_project(project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=project_{project_id}.giswork"},
    )

@app.post("/api/projects/import")
async def import_project(file: UploadFile = File(...)):
    content = await file.read()
    try:
        result = project_service.import_project(content)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===== 图层检测接口 =====
class InspectLayerRequest(BaseModel):
    geojson: dict
    name: str = ""

@app.post("/api/layer/inspect")
async def inspect_layer(request: InspectLayerRequest):
    result = inspect_geojson(request.geojson)
    result["name"] = request.name
    return result


class UnregisterLayerRequest(BaseModel):
    name: str

@app.post("/api/layer/unregister")
async def unregister_layer(request: UnregisterLayerRequest):
    _unregister_layer(request.name)
    return {"success": True, "message": f"已取消注册图层: {request.name}"}


class RegisterLayerRequest(BaseModel):
    name: str
    geojson: dict

@app.post("/api/layer/register")
async def register_layer(request: RegisterLayerRequest):
    _register_layer(request.name, request.geojson)
    return {"success": True, "message": f"已注册图层: {request.name}"}


# ===== SHP 导出接口 =====
class ExportShpRequest(BaseModel):
    geojson: dict
    name: str = "图层"
    crs: str = "EPSG:4326"

# ===== 网络分析 - 吸附端点 =====
@app.post("/api/network/snap")
async def snap_network(request: SnapRequest):
    """将点吸附到最近的路网节点，返回吸附后的坐标"""
    from backend.services.network_service import snap_to_network
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, functools.partial(
                snap_to_network, request.geojson, tuple(request.point),
            )
        )
        return result
    except Exception as e:
        return {"snapped": None, "distance_m": 0, "found": False, "error": str(e)[:200]}


# ===== 网络分析 - 求解端点 =====
@app.post("/api/network/solve")
async def solve_network(request: NetworkRequest):
    """网络分析统一入口：路线/服务区/最近设施"""
    from backend.services.network_service import (
        shortest_route, service_area, closest_facilities,
    )
    loop = asyncio.get_event_loop()
    try:
        if request.type == "route":
            if not request.origin or not request.dest:
                return {"error": "路线分析需要起点和终点"}
            wp = [tuple(w) for w in request.waypoints] if request.waypoints else None
            result = await loop.run_in_executor(
                None, functools.partial(
                    shortest_route, request.geojson,
                    tuple(request.origin), tuple(request.dest),
                    waypoints=wp,
                )
            )
        elif request.type == "service_area":
            if not request.facility:
                return {"error": "服务区分析需要设施点"}
            result = await loop.run_in_executor(
                None, functools.partial(
                    service_area, request.geojson,
                    tuple(request.facility),
                    request.breaks or [1000, 3000, 5000],
                )
            )
        elif request.type == "closest_facility":
            if not request.origin:
                return {"error": "最近设施分析需要事件点"}
            fac_list = [tuple(e) for e in request.events] if request.events else []
            if not fac_list:
                return {"error": "需要至少一个设施点（通过设施图层或手动添加）"}
            result = await loop.run_in_executor(
                None, functools.partial(
                    closest_facilities, request.geojson,
                    tuple(request.origin),
                    fac_list,
                    request.n,
                )
            )
        else:
            return {"error": f"不支持的类型: {request.type}"}
        return result
    except Exception as e:
        return {"error": f"网络分析失败: {str(e)[:300]}"}


@app.post("/api/layer/export-shp")
async def export_shp(request: ExportShpRequest):
    """将 GeoJSON 导出为 Shapefile (zip 包)，包含 .shp .shx .dbf .prj .cpg"""
    import tempfile, zipfile, shutil
    import geopandas as gpd

    try:
        gdf = gpd.GeoDataFrame.from_features(request.geojson["features"], crs=request.crs)
        if gdf.empty:
            return {"error": "没有可导出的要素"}

        # 字段名截断（Shapefile 限制 10 字符）
        rename_map = {}
        for col in gdf.columns:
            if col != "geometry" and len(col) > 10:
                new_name = col[:10]
                suffix = 1
                while new_name in rename_map.values() or new_name == "geometry":
                    new_name = col[:8] + str(suffix)
                    suffix += 1
                rename_map[col] = new_name
        if rename_map:
            gdf = gdf.rename(columns=rename_map)

        # 写入临时目录
        tmp_dir = tempfile.mkdtemp(prefix="shp_export_")
        shp_base = os.path.join(tmp_dir, request.name)
        gdf.to_file(shp_base, driver="ESRI Shapefile", encoding="utf-8")

        # 打包 zip
        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(tmp_dir):
                fpath = os.path.join(tmp_dir, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, fname)

        shutil.rmtree(tmp_dir, ignore_errors=True)

        zip_buf.seek(0)
        safe_name = request.name.replace(" ", "_").replace("/", "_").replace("\\", "_")
        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={safe_name}.zip"},
        )
    except Exception as e:
        return {"error": f"SHP 导出失败: {str(e)[:200]}"}


# ============================================================
# GIS 开放数据发现与获取（确定性端点，供前端/未来 UI 直接调用）
# ============================================================

class DataDiscoverRequest(BaseModel):
    query: str = ""
    kind: str = ""
    area: str = ""
    bbox: str = ""
    provider: str = "auto"
    file_format: str = ""
    time_start: str = ""
    time_end: str = ""
    max_items: int = 0


class DataDownloadRequest(BaseModel):
    query: str = ""
    kind: str = ""
    area: str = ""
    bbox: str = ""
    provider: str = ""
    file_format: str = "geojson"
    time_start: str = ""
    time_end: str = ""
    layer_name: str = ""
    max_items: int = 0


@app.get('/api/data/providers')
async def api_data_providers():
    """列出数据源及其能力/认证级别。"""
    from backend.services import data_discovery
    return data_discovery.sources()


@app.post('/api/data/discover')
async def api_data_discover(request: DataDiscoverRequest):
    """数据发现：返回各数据源元信息（数据源/类型/格式/区域/CRS/来源/状态）。"""
    from backend.services import data_discovery
    from backend.services.data_providers.errors import DataProviderError
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: data_discovery.discover(
                query=request.query, kind=request.kind, area=request.area,
                bbox=request.bbox, provider_id=request.provider,
                file_format=request.file_format, time_start=request.time_start,
                time_end=request.time_end, max_items=request.max_items,
            ),
        )
    except DataProviderError as e:
        return {"error": e.message, "hint": e.hint, "type": type(e).__name__}


@app.post('/api/data/download')
async def api_data_download(request: DataDownloadRequest):
    """获取数据 → GIS 文件(完整性/CRS 校验 + metadata) → 注册到图层。"""
    from backend.services import data_discovery
    from backend.services.data_providers.errors import DataProviderError
    loop = asyncio.get_event_loop()
    try:
        asset = await loop.run_in_executor(
            None,
            lambda: data_discovery.download(
                query=request.query, kind=request.kind, area=request.area,
                bbox=request.bbox, provider_id=request.provider,
                file_format=request.file_format, time_start=request.time_start,
                time_end=request.time_end, layer_name=request.layer_name,
                max_items=request.max_items,
            ),
        )
    except DataProviderError as e:
        return {"error": e.message, "hint": e.hint, "type": type(e).__name__}

    # 矢量结果注册为可查询图层（与 /api/upload 一致）
    if asset.get("geojson") is not None:
        _register_layer(asset["layer_name"], asset["geojson"])
    return asset


# ===== Task Manager API =====

@app.get("/api/tasks")
async def list_tasks(session_id: str = "default"):
    """列出任务"""
    from backend.services import task_manager
    return {"tasks": task_manager.list_tasks(session_id, include_archived=True)}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    from backend.services import task_manager
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    snap = task_manager.task_snapshot(task_id)
    snap["code_versions"] = task_manager.get_code_versions(task_id)
    snap["artifacts"] = task_manager.get_artifacts(task_id)
    snap["exec_log"] = task_manager.get_exec_log(task_id)
    snap["latest_code"] = task_manager.get_latest_code(task_id)
    return snap


@app.get("/api/tasks/{task_id}/code")
async def get_task_code(task_id: str, step: int = None):
    """获取任务的 Python 源代码"""
    from backend.services import task_manager
    if step:
        code = task_manager.get_code_version(task_id, step)
    else:
        code = task_manager.get_latest_code(task_id)
    if code is None:
        raise HTTPException(status_code=404, detail="Code not found")
    return {"code": code, "step": step or "latest"}


@app.post("/api/tasks/{task_id}/archive")
async def archive_task(task_id: str):
    """归档任务"""
    from backend.services import task_manager
    ok = task_manager.archive_task(task_id)
    return {"success": ok}


@app.post("/api/tasks/{task_id}/restore")
async def restore_task(task_id: str):
    """恢复任务"""
    from backend.services import task_manager
    ok = task_manager.restore_task(task_id)
    return {"success": ok}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务"""
    from backend.services import task_manager
    ok = task_manager.delete_task(task_id)
    return {"success": ok}


# ===== 前端静态文件（必须放在所有 /api 路由之后，否则 catch-all 会遮蔽 API） =====
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
