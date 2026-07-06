from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
    api_key: str = None                   # DeepSeek API 密钥，由前端 localStorage 传来，用完即弃

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
#加载文件，打开文件
async def upload(file:UploadFile=File(...)):
    content=await file.read()
    filename=file.filename
    #判断文件类型
    if file.filename.endswith('.geojson'):
        import json
        geojson_data=json.loads(content)
        return {"geojson":geojson_data,"name":filename}
