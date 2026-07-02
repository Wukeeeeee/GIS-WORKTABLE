from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.services.ai_service import chat_with_ai, clear_memory
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5501", "http://127.0.0.1:5501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

@app.post("/api/chat")
async def chat(request: ChatRequest):
    response = chat_with_ai(request.message, request.session_id)
    return {"response": response}

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.delete("/api/chat/memory")
async def clear_chat_memory(session_id: str = "default"):
    clear_memory(session_id)
    return {"status": "ok", "message": "记忆已清除"}

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
