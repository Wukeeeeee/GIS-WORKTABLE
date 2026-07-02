from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.services.ai_service import chat_with_ai

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
