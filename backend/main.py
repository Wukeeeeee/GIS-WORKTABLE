from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from io import BytesIO
from backend.services.ai_service import chat_with_ai, clear_memory, test_deepseek_key, generated_geojson
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
