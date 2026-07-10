from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from io import BytesIO
from backend.services.ai_service import chat_with_ai, clear_memory, test_deepseek_key, generated_geojson, pending_aoi_suggestions, pending_layers, _register_layer, registered_layers
from backend.services.baidu_aoi_service import search_suggestions as baidu_search_suggestions
from backend.services.baidu_aoi_service import extract_boundary as baidu_extract_boundary
from backend.services.gaode_aoi_service import search_suggestions as gaode_search_suggestions
from backend.services.gaode_aoi_service import extract_boundary as gaode_extract_boundary
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 请求体数据结构 ----
class ChatRequest(BaseModel):
    message: str                          # 用户发送的消息
    session_id: str = "default"           # 会话ID，用来区分不同的聊天会话
    api_key: Optional[str] = None         # DeepSeek API 密钥，由前端 localStorage 传来，用完即弃

class TestKeyRequest(BaseModel):
    api_key: str                          # 要测试的 DeepSeek API 密钥

# ===== 百度 AOI 提取请求体 =====
class BaiduSearchRequest(BaseModel):
    query: str                            # 搜索关键词

class BaiduExtractRequest(BaseModel):
    uid: str                              # POI 的 UID
    name: str = "未命名"                  # 地点名称

# ===== 聊天接口 =====
# 前端发消息到这里，后端调 DeepSeek API 获取 AI 回复
@app.post("/api/chat")
async def chat(request: ChatRequest):
    response = chat_with_ai(request.message, request.session_id, request.api_key)
    result = {"response": response}
    # 如果有最新生成的 GeoJSON，一起返回给前端
    geo_data = generated_geojson.get('latest')
    if geo_data and geo_data.get('sent') != True:
        result["geojson"] = geo_data["geojson"]
        result["layerName"] = geo_data["name"]
        geo_data['sent'] = True  # 标记已发送，不再重复发

    # 返回所有待发送的图层（支持 AI 一次生成多个独立图层）
    if pending_layers:
        result["layers"] = list(pending_layers)
        pending_layers.clear()
    # 如果有待处理的百度 AOI 候选列表，传给前端弹出选择窗口
    suggest_data = pending_aoi_suggestions.get('latest')
    if suggest_data and suggest_data.get('sent') != True:
        result["pending_suggestions"] = suggest_data["suggestions"]
        suggest_data['sent'] = True  # 标记已发送
    # 如果 AI 调用了 clear_layers，通知前端清空地图
    import backend.services.ai_service as _ai_svc
    if _ai_svc.clear_layers_flag:
        result["clear_layers"] = True
        _ai_svc.clear_layers_flag = False
    return result

@app.get("/api/health")
async def health():
    return {"status": "ok"}

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

@app.get('/api/boundary')
async def get_boundary_api(place: str = "长沙市"):
    """从OSM获取行政边界，返回GeoJSON"""
    from backend.services.ai_service import get_boundary
    import json, os
    try:
        import osmnx as ox
        ox.settings.timeout = 30
        gdf = ox.geocode_to_gdf(place)
        geojson = json.loads(gdf.to_json())
        return {"geojson": geojson, "name": f"{place}边界"}
    except Exception as e:
        return {"error": str(e)}

# ===== 百度地图 AOI 提取接口 =====

class BaiduSearchResponse(BaseModel):
    suggestions: list
    message: str = ""

class BaiduExtractResponse(BaseModel):
    geojson: Optional[dict] = None
    name: str = ""
    message: str = ""
    success: bool = False

@app.post("/api/baidu/search", response_model=BaiduSearchResponse)
async def baidu_search(request: BaiduSearchRequest):
    """搜索百度地图，返回候选地点列表"""
    try:
        suggestions = baidu_search_suggestions(request.query)
        if not suggestions:
            return BaiduSearchResponse(
                suggestions=[],
                message="未找到候选地点，可以尝试其他关键词"
            )
        return BaiduSearchResponse(
            suggestions=suggestions,
            message=f"找到 {len(suggestions)} 个候选地点"
        )
    except Exception as e:
        return BaiduSearchResponse(
            suggestions=[],
            message=f"搜索失败: {str(e)}"
        )

@app.post("/api/baidu/extract", response_model=BaiduExtractResponse)
async def baidu_extract(request: BaiduExtractRequest):
    """根据 UID 提取 AOI 边界，返回 GeoJSON"""
    try:
        geojson = baidu_extract_boundary(request.uid, request.name)
        if geojson:
            # 也存到 generated_geojson 供前端加载
            from backend.services.ai_service import generated_geojson
            generated_geojson['latest'] = {'geojson': geojson, 'name': request.name}
            return BaiduExtractResponse(
                geojson=geojson,
                name=request.name,
                message="提取成功",
                success=True
            )
        return BaiduExtractResponse(
            message="未能提取到边界数据，该地点可能没有建筑轮廓数据",
            success=False
        )
    except Exception as e:
        return BaiduExtractResponse(
            message=f"提取失败: {str(e)}",
            success=False
        )

# ===== 高德地图 AOI 提取接口 =====

class GaodeSearchRequest(BaseModel):
    query: str

class GaodeExtractRequest(BaseModel):
    id: str
    name: str = "未命名"

class GaodeSearchResponse(BaseModel):
    suggestions: list
    message: str = ""

class GaodeExtractResponse(BaseModel):
    geojson: Optional[dict] = None
    name: str = ""
    message: str = ""
    success: bool = False

@app.post("/api/gaode/search", response_model=GaodeSearchResponse)
async def gaode_search(request: GaodeSearchRequest):
    """搜索高德地图，返回候选地点列表"""
    try:
        suggestions = gaode_search_suggestions(request.query)
        if not suggestions:
            return GaodeSearchResponse(
                suggestions=[],
                message="未找到候选地点，可以尝试其他关键词"
            )
        return GaodeSearchResponse(
            suggestions=suggestions,
            message=f"找到 {len(suggestions)} 个候选地点"
        )
    except Exception as e:
        return GaodeSearchResponse(
            suggestions=[],
            message=f"搜索失败: {str(e)}"
        )

@app.post("/api/gaode/extract", response_model=GaodeExtractResponse)
async def gaode_extract(request: GaodeExtractRequest):
    """根据 POI ID 提取 AOI 边界，返回 GeoJSON"""
    try:
        geojson = gaode_extract_boundary(request.id, request.name)
        if geojson:
            from backend.services.ai_service import generated_geojson
            generated_geojson['latest'] = {'geojson': geojson, 'name': request.name}
            return GaodeExtractResponse(
                geojson=geojson,
                name=request.name,
                message="提取成功",
                success=True
            )
        return GaodeExtractResponse(
            message="未能提取到边界数据，该地点可能没有建筑轮廓数据",
            success=False
        )
    except Exception as e:
        return GaodeExtractResponse(
            message=f"提取失败: {str(e)}",
            success=False
        )

@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    import json, os, tempfile, zipfile
    content = await file.read()
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()

    # 所有上传的文件都存一份到 output/uploads/，供 AI 后续处理用
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "output", "uploads")
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
            # 解压到临时目录
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
                return {"geojson": geojson_data, "name": name + ".zip"}

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
