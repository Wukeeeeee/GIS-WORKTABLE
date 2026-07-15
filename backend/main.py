from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from io import BytesIO
import subprocess, datetime, time, os, asyncio, functools
from backend.services.ai_service import chat_with_ai, clear_memory, test_deepseek_key, test_glm_key, test_agnes_key, request_cancel, _TEMP_OUTPUT_DIR
from backend.services.tools import _register_layer, _unregister_layer
from backend.services.layer_service import inspect_geojson


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

# 挂载临时输出目录为静态文件（不触发 Live Server 刷新）
app.mount("/output", StaticFiles(directory=_TEMP_OUTPUT_DIR), name="output")

# ---- 请求体数据结构 ----
class ChatRequest(BaseModel):
    message: str                          # 用户发送的消息
    session_id: str = "default"           # 会话ID，用来区分不同的聊天会话
    api_key: Optional[str] = None         # API 密钥，前端 localStorage 传来，用完即弃
    provider: str = "deepseek"            # 模型提供商：deepseek 或 glm
    force_skills: list = []              # 用户通过 chip 标签指定的技能
    amap_key: Optional[str] = None        # 高德地图 Web API 密钥
    pending_layer: Optional[dict] = None  # 待分析的图层附件（前端输入框上方暂存）

class TestKeyRequest(BaseModel):
    api_key: str                          # 要测试的 DeepSeek API 密钥

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
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, functools.partial(
        chat_with_ai, msg, request.session_id, request.api_key, request.provider, request.force_skills, request.amap_key
    ))
    # result 已包含 layers / images / heatmap / clear_layers / pending_suggestions
    # 从 chat_with_ai 直接返回给前端，不需要再读全局变量
    response_text = result.get("response", "")

    # 组装前端响应（保持与原格式兼容）
    output = {"response": response_text}

    # 如果有图层
    layers = result.get("layers", [])
    if layers:
        output["layers"] = layers
        # 兼容旧格式：第一个图层作为 geojson + layerName
        if layers and len(layers) > 0:
            output["geojson"] = layers[0].get("geojson")
            output["layerName"] = layers[0].get("name", "")

    # 如果有待处理的 AOI 候选列表
    suggest_data = result.get("pending_suggestions")
    if suggest_data and suggest_data.get("sent") != True:
        output["pending_suggestions"] = suggest_data["suggestions"]
        suggest_data["sent"] = True

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

    return output

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式聊天接口，实时推送 Agent 执行进度"""
    from backend.services.graph import run_agent_stream
    from backend.services.tools import reset_state
    from backend.services.ai_service import _build_system_content, _build_langgraph_messages, _get_or_create_history

    provider = request.provider or "deepseek"
    amap_key = request.amap_key or ""
    reset_state(amap_key)

    # 构建 system prompt + 消息（复用 ai_service 的构建逻辑）
    force_skills = request.force_skills or []
    history = _get_or_create_history(request.session_id or "default", request.message)
    system_content, skill_text, _ = _build_system_content(provider, request.message, force_skills)

    # 如果前端附带了待分析图层，将 GeoJSON 注入到用户消息中（同时进入 agent 上下文和校验器）
    original_message = request.message
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

    return StreamingResponse(
        run_agent_stream(
            messages=langgraph_messages,
            api_key=request.api_key or "",
            provider=provider,
            amap_key=amap_key,
            skill_text=skill_text,
            original_message=original_message,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@app.post("/api/cancel")
async def cancel_request():
    """取消当前 AI 请求"""
    result = request_cancel()
    return {"status": "ok", "message": result}

@app.get("/api/health")
async def health():
    return {"status": "ok"}

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

# ===== 测试 API 密钥 =====
# 前端设置弹窗里点 [测速] 时调用，验证 DeepSeek 密钥能不能连上
@app.post("/api/test-key")
async def test_key(request: TestKeyRequest):
    # 返回 { success: true/false, message: "连接成功"/"密钥无效" }
    success, message = test_deepseek_key(request.api_key)
    return {"success": success, "message": message}

# ===== 测试 GLM API 密钥 =====
@app.post("/api/test-key-glm")
async def test_key_glm(request: TestKeyRequest):
    success, message = test_glm_key(request.api_key)
    return {"success": success, "message": message}

@app.post("/api/test-key-agnes")
async def test_key_agnes(request: TestKeyRequest):
    success, message = test_agnes_key(request.api_key)
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
    import json, os, tempfile, zipfile
    content = await file.read()
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()

    # 所有上传的文件存到临时目录，供 AI 后续处理用
    upload_dir = os.path.join(_TEMP_OUTPUT_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    saved_path = os.path.join(upload_dir, filename)
    with open(saved_path, 'wb') as f:
        f.write(content)

    # ===== GeoJSON =====
    if ext == '.geojson' or ext == '.json':
        geojson_data = json.loads(content)
        if isinstance(geojson_data, dict) and geojson_data.get('type') in ('FeatureCollection', 'Feature'):
            _register_layer(filename, geojson_data)
            return {"geojson": geojson_data, "name": filename, "saved_path": saved_path}
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
                gdf = gpd.read_file(shp_path)
                geojson_data = json.loads(gdf.to_json())
                name = os.path.splitext(shp_files[0])[0]
                _register_layer(name, geojson_data)
                return {"geojson": geojson_data, "name": name}

    # ===== GPKG / KML 等（geopandas 支持的单文件格式） =====
    supported = {'.gpkg', '.kml', '.kmz', '.gpx', '.dxf'}
    if ext in supported:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            import geopandas as gpd
            gdf = gpd.read_file(tmp_path)
            if gdf.empty:
                return {"error": "文件未包含有效的地理数据"}
            geojson_data = json.loads(gdf.to_json())
            name = os.path.splitext(filename)[0]
            _register_layer(name, geojson_data)
            return {"geojson": geojson_data, "name": name}
        except Exception as e:
            return {"error": f"无法读取 {ext} 文件: {str(e)[:200]}"}
        finally:
            try: os.unlink(tmp_path)
            except: pass

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

    return {"error": f"不支持的文件格式: {ext}，支持: .geojson .json .gpkg .kml .kmz .gpx .dxf .zip(含shp)"}


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
