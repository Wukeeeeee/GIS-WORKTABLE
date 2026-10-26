import os
# 启用 Windows 控制台 ANSI 颜色转义序列支持，防止乱码 [32m 显示
if os.name == 'nt':
    os.system('')

# ===== PROJ 数据目录修复 =====
# 部分机器安装了 PostGIS 等软件，会在系统环境变量 PROJ_LIB / PROJ_DATA 写入不兼容的
# proj.db 路径（版本过旧），导致 rasterio 的 EPSG 解析失败（CRSError: DATABASE.LAYOUT.VERSION.MINOR）。
# 这里在导入任何 GIS 库之前删除这两个变量，让 rasterio/pyproj 回退到各自捆绑的 proj 数据。
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)
# 关闭 langchain-openai 的底层 TCP Keepalive 注入，恢复标准 httpx 代理自动检测，避免终端弹出代理警告
os.environ.setdefault("LANGCHAIN_OPENAI_TCP_KEEPALIVE", "0")

from fastapi import FastAPI, UploadFile, File, HTTPException, Response, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import io
from io import BytesIO
import json
import urllib.parse
import subprocess, datetime, asyncio, functools
import threading, uuid, time
from concurrent.futures import ThreadPoolExecutor
from backend.services.ai_service import chat_with_ai, clear_memory, test_key, request_cancel, _TEMP_OUTPUT_DIR
from backend.services.llm_config import LLMConfig, resolve_llm_config
from backend.services.tools import _register_layer, _unregister_layer
from backend.services.layer_service import inspect_geojson
from backend.services import project_service
from backend.launcher import health_identity


# ===== 版本信息（服务器启动时自动生成） =====
_SERVER_START_TIME = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
_GIT_DIR = os.path.dirname(os.path.dirname(__file__))


def _read_git_version():
    """读取当前工作区版本；接口调用时重新读取，避免提交后显示启动时的旧号。"""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3, cwd=_GIT_DIR,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=3, cwd=_GIT_DIR,
        ).stdout.strip()
        return commit or "unknown", bool(status)
    except Exception:
        return "unknown", False


_GIT_COMMIT, _GIT_DIRTY = _read_git_version()

app = FastAPI()


class _ProjectImportBodyLimitExceeded(Exception):
    pass


class ProjectImportBodyLimitMiddleware:
    """Bound multipart bytes before Starlette spools a project upload."""

    def __init__(self, app, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http" or scope.get("method") != "POST"
                or scope.get("path") != "/api/projects/import"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except (TypeError, ValueError):
                declared_size = 0
            if declared_size > self.max_body_bytes:
                await self._send_too_large(scope, receive, send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _ProjectImportBodyLimitExceeded()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _ProjectImportBodyLimitExceeded:
            await self._send_too_large(scope, receive, send)

    async def _send_too_large(self, scope, receive, send):
        response = Response(
            content=json.dumps({
                "detail": "工程导入请求体超出允许大小（工程包上限为 1 GiB）",
            }, ensure_ascii=False),
            status_code=413,
            media_type="application/json",
        )
        await response(scope, receive, send)


app.add_middleware(
    ProjectImportBodyLimitMiddleware,
    max_body_bytes=project_service._MAX_PROJECT_ARCHIVE_COMPRESSED_BYTES + 1024 * 1024,
)

# URL vector acquisition jobs are local process tasks: progress is polled by the UI,
# while ArcGIS requests run off the ASGI event loop.
_url_fetch_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="url-vector-fetch")
_url_fetch_jobs = {}
_url_fetch_jobs_lock = threading.Lock()

# 启动 banner
print("")
print(r"""
   ____ ___ ____ 
  / ___|_ _/ ___|
 | |  _ | |\___ \
 | |_| || | ___) |
  \____|___|____/ 

 __        _____  ____  _  _______  _    ____  _     _____ 
 \ \      / / _ \|  _ \| |/ /_   _|/ \  | __ )| |   | ____|
  \ \ /\ / / | | | |_) | ' /  | | / _ \ |  _ \| |   |  _|  
   \ V  V /| |_| |  _ <| . \  | |/ ___ \| |_) | |___| |___ 
    \_/\_/  \___/|_| \_\_|\_\ |_/_/   \_\____/|_____|_____|
""")
print("  ========================================================")
print("    GIS-WORKTABLE  -  Intelligent GIS Workbench")
print("    AI Agent + GIS Knowledge + Spatial Analysis + Automation")
print("  ========================================================")
print("")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=10000)  # 10KB 以上自动 gzip 压缩

# 动态支持 /output 产物文件访问（支持时间戳前缀自动解析与子目录查找，防止 404）
@app.get("/output/{filename:path}")
async def serve_output_file(filename: str, download: bool = False):
    import glob
    # 路径穿越防护：解析后必须仍在 _TEMP_OUTPUT_DIR 内
    _norm_base = os.path.normpath(_TEMP_OUTPUT_DIR)
    direct_path = os.path.normpath(os.path.join(_TEMP_OUTPUT_DIR, filename))
    try:
        _in_base = os.path.commonpath([_norm_base, direct_path]) == _norm_base
    except ValueError:
        _in_base = False  # 跨盘符
    if not _in_base or filename.startswith('\\\\') or ':' in filename.split(os.sep)[0]:
        raise HTTPException(status_code=403, detail="非法路径")
    if os.path.isfile(direct_path):
        return FileResponse(direct_path, filename=os.path.basename(direct_path) if download else None)
    
    base_name = os.path.basename(filename)
    matches = glob.glob(os.path.join(_TEMP_OUTPUT_DIR, f"*_{base_name}"))
    if not matches:
        for root, _, files in os.walk(_TEMP_OUTPUT_DIR):
            for f in files:
                if f == base_name or f.endswith(f"_{base_name}"):
                    matches.append(os.path.join(root, f))
    if matches:
        matches.sort(key=os.path.getmtime, reverse=True)
        return FileResponse(matches[0], filename=os.path.basename(matches[0]) if download else None)
    
    raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")

# 挂载临时输出目录为静态文件兜底
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
    quoted: Optional[str] = None          # 用户点击"引用"的上一条 AI 回复（作为上下文注入）
    task_id: Optional[str] = None         # 任务 ID（跨轮保持）
    mode: str = "full"                    # 回复模式（已固定为完整模式，保留参数用于兼容）
    read_only_location_analysis: bool = False  # 右键位置分析只允许只读工具，禁止地图图层副作用

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
    # 如果前端附带了被引用的上一条回复，注入到消息中（让 Agent 明确讨论上下文）
    if request.quoted:
        msg = (
            f"[用户引用了上一条回复，请围绕其内容理解下面的问题]\n"
            f"{request.quoted[:4000]}\n\n"
            f"[当前问题]\n"
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
        mode=request.mode,
        task_id=request.task_id,
    ))
    # result 已包含 layers / images / heatmap / clear_layers / pending_suggestions / reasoning
    # 从 chat_with_ai 直接返回给前端，不需要再读全局变量
    response_text = result.get("response", "")

    # 组装前端响应（保持与原格式兼容）
    output = {"response": response_text}
    if result.get("execution_status"):
        output["execution_status"] = result["execution_status"]
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

    # 会话忙：把标记透传给前端，让它提示「未执行」而不是当成 AI 回答
    if result.get("busy"):
        output["busy"] = True

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
        "result_check": result.get("result_check"),
        "qa_warnings": result.get("qa_warnings", []),
        "task_id": result.get("task_id"),
        "run_id": result.get("run_id"),
        "execution_status": result.get("execution_status"),
    }
    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式聊天接口，实时推送 Agent 执行进度"""
    from backend.services.graph import run_agent_stream
    from backend.services.ai_service import (
        _build_system_content, _build_langgraph_messages, _get_or_create_history,
        _rebase_history_context,
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

    # === choose_option 上下文回填：用户点击选项后只发短 label，把原任务拼回，
    # === 避免「选完数据源，AI 忘记原任务地名（如上海）而幻觉成其他城市」
    # === 必须在 clear_pending_action 之前取值 ===
    _ctx_backfill = _pa.build_choice_backfill(session_id, request.message)

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

    if _ctx_backfill:
        request.message = _ctx_backfill

    # 构建 system prompt + 消息（复用 ai_service 的构建逻辑）
    force_skills = request.force_skills or []
    history = _get_or_create_history(session_id, request.message)
    # 技能路由可能等待远程模型；不能在事件循环中同步等待，阻塞健康检查和取消请求。
    system_content, skill_text, _ = await asyncio.to_thread(
        _build_system_content, cfg, request.message, session_id, force_skills, request.task_id)
    history = _rebase_history_context(session_id, history)

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

    # 如果前端附带了被引用的上一条回复，注入到上下文（让 Agent 明确讨论围绕该回复）
    if request.quoted:
        quoted_ctx = (
            f"[用户引用了上一条回复，请围绕其内容理解下面的问题]\n"
            f"{request.quoted[:4000]}\n\n"
        )
        if history and history[-1].get("role") == "user":
            history[-1]["content"] = quoted_ctx + history[-1]["content"]
        original_message = quoted_ctx + original_message

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
                mode=request.mode,
                read_only_location_analysis=request.read_only_location_analysis,
                task_id=request.task_id,
            ):
                if line.startswith("data: "):
                    try:
                        _evt = json.loads(line[6:])
                    except Exception:
                        _evt = None
                    if _evt and _evt.get("type") == "done" and not _evt.get("busy"):
                        commit_assistant_reply(
                            session_id,
                            _evt.get("response", ""),
                            _evt.get("reasoning"),
                            history_context=history,
                        )
                        # 记录日志（SSE 流式路径之前漏了，导致导出的日志当前会话为 0 条）
                        try:
                            from backend.services.log_service import log_turn
                            from backend.services.tools import _registered_layers
                            log_turn(
                                session_id=session_id,
                                user_message=original_message or request.message,
                                ai_reply=_evt.get("response", ""),
                                layers_snapshot=dict(_registered_layers),
                                saved_files=None,
                            )
                        except Exception:
                            pass
                yield line
        except GeneratorExit:
            # 客户端断开（用户取消/页面关闭）时，仅标记本会话取消，
            # 不再写全局标志并发中的其他会话不受影响
            import backend.services.ai_service as _ai_svc
            _ai_svc.clear_session_cancel(session_id)
            _ai_svc.request_cancel(session_id)
        except Exception:
            # 生成器初始化或执行阶段异常也要成为可读的 SSE 事件，
            # 否则浏览器只能看到断流并可能误判为可安全重试。
            import traceback
            traceback.print_exc()
            yield "data: " + json.dumps({
                "type": "error",
                "message": "AI 流式执行失败，请检查服务状态后重试。",
            }, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        _persisted_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )

@app.post("/api/cancel")
async def cancel_request(session_id: str = ""):
    """取消当前 AI 请求（带 session_id 时只取消该会话，兼容不带的全局取消）"""
    result = request_cancel(session_id)
    return {"status": "ok", "message": result}

@app.get("/favicon.ico")
async def favicon():
    from fastapi.responses import Response
    import os
    favicon_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets", "favicon.svg")
    if os.path.exists(favicon_path):
        with open(favicon_path, "r", encoding="utf-8") as f:
            svg = f.read()
        return Response(content=svg, media_type="image/svg+xml")
    return Response(status_code=404)

@app.post("/api/geo-credentials")
async def save_geo_credential(req: dict):
    """保存地理数据平台凭据（加密存储，不返回密码）"""
    from backend.services.credential_store import save_credential
    service = req.get("service", "")
    username = req.get("username", "")
    password = req.get("password", "")
    if not service or not username or not password:
        return {"status": "error", "message": "缺少 service/username/password"}
    ok = save_credential(service, username, password)
    if ok:
        return {"status": "ok", "message": f"{service} 凭据已保存", "configured": True}
    return {"status": "error", "message": "保存失败"}


@app.get("/api/geo-credentials/status")
async def geo_credentials_status():
    """查询已配置的凭据（只返回服务名，不返回密码）"""
    from backend.services.credential_store import get_configured_services
    services = get_configured_services()
    return {"configured": services, "count": len(services)}


@app.delete("/api/geo-credentials/{service}")
async def delete_geo_credential(service: str):
    """删除指定服务的凭据"""
    from backend.services.credential_store import delete_credential, has_credential
    if not has_credential(service):
        return {"status": "ok", "deleted": False, "already_absent": True}
    ok = delete_credential(service)
    return {"status": "ok" if ok else "error", "deleted": ok}


@app.get("/api/proxy-config")
async def get_proxy_config():
    """获取当前代理配置"""
    from backend.services.tools import get_proxy_config
    return {"proxy": get_proxy_config()}


@app.post("/api/proxy-config")
async def save_proxy_config(req: dict):
    """保存代理配置（如 http://127.0.0.1:7897，空字符串表示使用系统代理）"""
    from backend.services.tools import set_proxy_config
    proxy = req.get("proxy", "")
    result = set_proxy_config(proxy)
    return {"status": "ok", "message": result, "proxy": proxy}


_USER_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache", "user_settings.json")


def _sanitize_user_settings(data: dict) -> dict:
    """Persist Provider metadata only; model API keys belong to browser localStorage."""
    sanitized = dict(data)
    providers = sanitized.get("providers")
    if isinstance(providers, list):
        sanitized["providers"] = [
            {key: value for key, value in provider.items() if key != "api_key"}
            if isinstance(provider, dict) else provider
            for provider in providers
        ]
    return sanitized


def _load_user_settings() -> dict:
    if os.path.exists(_USER_SETTINGS_PATH):
        try:
            with open(_USER_SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                sanitized = _sanitize_user_settings(data)
                if sanitized != data:
                    _save_user_settings(sanitized)
                return sanitized
        except Exception:
            pass
    return {}


def _save_user_settings(data: dict) -> bool:
    os.makedirs(os.path.dirname(_USER_SETTINGS_PATH), exist_ok=True)
    try:
        with open(_USER_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(_sanitize_user_settings(data), f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[GIS] 保存 user_settings 失败: {e}", flush=True)
        return False


@app.get("/api/user-settings")
async def get_user_settings():
    """获取用户持久化设置；Provider 仅同步元数据，API Key 保留在浏览器。"""
    return _load_user_settings()


@app.post("/api/user-settings")
async def save_user_settings(req: dict):
    """保存用户持久化配置（增量合并更新）"""
    current = _load_user_settings()
    current.update(_sanitize_user_settings(req))
    ok = _save_user_settings(current)
    return {"status": "ok" if ok else "error"}


@app.get("/api/health")
async def health():
    return health_identity()

@app.get("/api/layers/names")
async def list_layer_names():
    """注册图层名列表（轻量，供手动面板下拉框精确匹配后端工具）"""
    from backend.services.tools import _registered_layers, _state_lock
    with _state_lock:
        names = list(_registered_layers.keys())
    return {"names": names}


@app.get("/api/layers")
async def list_layers():
    from backend.services.tools import _registered_layers, _state_lock
    with _state_lock:
        snapshot = list(_registered_layers.items())
    layers = []
    for name, info in snapshot:
        layers.append({
            "name": name,
            "geojson": info.get("geojson"),
            "bbox": info.get("bbox"),
            "style": info.get("style"),
        })
    return {"layers": layers}

@app.post("/api/reset_state")
async def api_reset_state():
    from backend.services.tools import reset_state, acquire_shared_state_lock, release_shared_state_lock
    if not await asyncio.to_thread(acquire_shared_state_lock, 0):
        raise HTTPException(status_code=409, detail="当前 GIS 工作区正在处理另一项操作")
    try:
        reset_state()
    finally:
        release_shared_state_lock()
    return {"status": "ok", "message": "状态已重置"}

@app.get("/api/logs/stats")
async def logs_stats(session_id: str = "default"):
    from backend.services.log_service import get_log_stats
    return await asyncio.to_thread(get_log_stats, session_id)


@app.get("/api/logs/export")
async def logs_export(session_id: str = "default"):
    from backend.services.log_service import get_log_snapshot
    snapshot = await asyncio.to_thread(get_log_snapshot, session_id)
    temp, perm = snapshot["temp"], snapshot["permanent"]
    legacy = snapshot["legacy_temp"]

    lines = []
    lines.append("# GIS-WORKTABLE 会话日志导出")
    lines.append("")
    lines.append(f"- 导出时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 当前会话问答记录：{len(temp)} 条")
    lines.append(f"- 历史问题记录：{len(perm)} 条")
    if legacy:
        lines.append(f"- 旧版共享会话记录：{len(legacy)} 条（未区分会话）")
    lines.append("")
    lines.append("---")
    lines.append("")

    for title, records in (("当前会话问答记录", temp), ("旧版共享会话记录（未区分会话）", legacy)):
        if not records:
            continue
        lines.append(f"## {title}（{len(records)} 条）")
        lines.append("")
        for i, r in enumerate(records, 1):
            t = r.get("time", "")[:19].replace("T", " ")
            lines.append(f"### {i}. [{t}]")
            lines.append("")
            lines.append(f"**用户：** {r.get('user', '')}")
            lines.append("")
            lines.append(f"**AI：** {r.get('ai', '')}")
            lines.append("")
            layers = r.get("layers", {})
            if layers:
                lines.append("**当时图层：**")
                lines.append("")
                for name, info in layers.items():
                    fc = info.get("feature_count", 0)
                    gt = ", ".join(info.get("geometry_types", [])) or "未知"
                    lines.append(f"- {name}（要素数：{fc}，几何类型：{gt}）")
                    fields = info.get("property_fields", [])
                    if fields:
                        lines.append(f"  - 属性字段：{', '.join(fields[:10])}")
                lines.append("")
            saved = r.get("saved_files", [])
            if saved:
                lines.append(f"**保存文件：** {', '.join(saved)}")
                lines.append("")
            lines.append("---")
            lines.append("")

    if perm:
        lines.append(f"## 历史问题记录（{len(perm)} 条）")
        lines.append("")
        for i, r in enumerate(perm, 1):
            t = r.get("time", "")[:19].replace("T", " ")
            lines.append(f"### {i}. [{t}]")
            lines.append("")
            lines.append(f"**用户：** {r.get('user', '')}")
            lines.append("")
            lines.append(f"**AI：** {r.get('ai', '')}")
            lines.append("")
            lines.append("---")
            lines.append("")

    if not temp and not perm and not legacy:
        lines.append("暂无日志记录。")
        lines.append("")

    content = chr(10).join(lines)
    filename = f"gis_worktable_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/logs/clear")
async def logs_clear(session_id: str = "default"):
    from backend.services.log_service import clear_temp_log
    if not clear_temp_log(session_id):
        raise HTTPException(status_code=500, detail="当前会话日志清除失败")
    return {"status": "ok", "message": "当前会话日志已清除"}

@app.get("/api/version")
async def version():
    commit, dirty = _read_git_version()
    return {
        "commit": commit,
        "start_time": _SERVER_START_TIME,
        "dirty": dirty,
    }

# ===== 清除记忆 =====
# 前端点 "+" 按钮时调用，清空后端内存里的对话历史记录
@app.delete("/api/chat/memory")
async def clear_chat_memory(session_id: str = "default"):
    if not await asyncio.to_thread(clear_memory, session_id):
        raise HTTPException(status_code=409, detail="当前 GIS 工作区正在处理另一项操作，请稍后重试")
    return {"status": "ok", "message": "记忆已清除"}

# ===== 测试 LLM 连接（通用） =====
# 前端设置面板点 [测速] 调用；入参即 cfg —— 任意 OpenAI 兼容接口都能测。
# 返回 { success: true/false, message: "连接成功"/"密钥无效" }
@app.post("/api/test-key")
async def test_key_endpoint(request: TestKeyRequest):
    # 兼容旧前端：只带 provider + api_key 时翻译成内置默认 cfg
    cfg = resolve_llm_config(request.llm_config, request.provider or "", request.api_key or "")
    success, message = await asyncio.to_thread(test_key, cfg)
    return {"success": success, "message": message}

@app.get('/api/boundary')
async def get_boundary_api(place: str = "长沙市", adcode: str = ""):
    """从阿里云 DataV 获取行政边界（国内可访问），返回 GeoJSON。

    两种模式：
    - place=名称：取该行政区自身边界（兼容旧调用，错误以 {"error":...} 返回）
    - adcode=6位码：取该行政区的下一级全集边界（下钻用），WGS-84 已转换
    """
    if adcode:
        from backend.services.datav_service import fetch_boundary_by_adcode
        if not (adcode.isdigit() and len(adcode) == 6):
            raise HTTPException(status_code=400, detail="adcode 必须是 6 位数字")
        # 阻塞 IO 放线程池，避免卡事件循环
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, functools.partial(fetch_boundary_by_adcode, adcode))
        if data is None:
            raise HTTPException(status_code=404, detail=f"未找到 adcode={adcode} 的边界数据")
        return {"geojson": data, "name": f"adcode {adcode} 下级边界", "adcode": adcode}
    try:
        from backend.services.datav_service import fetch_boundary
        data = fetch_boundary(place)
        if data is None:
            return {"error": f"DataV 未找到「{place}」的边界数据"}
        return {"geojson": data, "name": f"{place}边界"}
    except Exception as e:
        return {"error": str(e)}

class _MissingGeoTiffCrsError(Exception):
    pass


_MAX_RASTER_PREVIEW_PIXELS = 4_000_000


def _is_safe_zip_member(name: str) -> bool:
    import ntpath
    from pathlib import PurePosixPath

    raw_name = str(name or "")
    normalized = raw_name.replace("\\", "/")
    path = PurePosixPath(normalized)
    drive, _ = ntpath.splitdrive(raw_name)
    return bool(normalized) and not drive and not path.is_absolute() and ".." not in path.parts


def _uploaded_vector_provenance(filename, source_crs, file_format=None):
    import os
    from backend.services.tools import _normalize_layer_provenance

    ext = os.path.splitext(str(filename or ""))[1].lower()
    format_label = file_format or {
        ".geojson": "GeoJSON", ".json": "GeoJSON", ".zip": "Shapefile ZIP",
        ".gpkg": "GeoPackage", ".kml": "KML", ".kmz": "KMZ",
        ".gpx": "GPX", ".dxf": "DXF", ".pmtiles": "PMTiles",
        ".parquet": "GeoParquet", ".geoparquet": "GeoParquet", ".fgb": "FlatGeobuf",
    }.get(ext, ext.lstrip(".").upper() or "Vector")
    crs = str(source_crs).strip() if source_crs else "未知"
    crs_known = bool(source_crs) and crs.lower() not in {"未知", "unknown", "none"}
    return _normalize_layer_provenance({
        "provider": "local_upload",
        "kind": "vector_upload",
        "file_format": format_label,
        "crs": crs,
        "crs_known": crs_known,
    })


def _register_uploaded_vector(name, geojson, provenance=None):
    import math
    from backend.services.tools import _compute_bbox

    bounds = _compute_bbox(geojson)
    if (not all(isinstance(value, (int, float)) and math.isfinite(value) for value in bounds)
            or not (-180 <= bounds[0] <= bounds[2] <= 180 and -90 <= bounds[1] <= bounds[3] <= 90)):
        raise ValueError("坐标超出 WGS-84 范围；请提供正确 CRS 或转换为 EPSG:4326 后上传")
    return _register_layer(name, geojson, provenance=provenance)


@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    import os, tempfile, zipfile, orjson
    from urllib.parse import quote
    loop = asyncio.get_event_loop()
    # UploadFile.filename is client-controlled. Treat both slash styles as
    # separators so Windows paths are safe even when the server runs elsewhere.
    filename = str(file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    if (filename in ('', '.', '..') or len(filename) > 240
            or any(ord(char) < 32 or char in '<>:"|?*' for char in filename)
            or filename.rstrip(' .') != filename
            or filename.split('.', 1)[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
        return {"error": "无效的上传文件名"}
    ext = os.path.splitext(filename)[1].lower()
    allowed = {'.geojson', '.json', '.gpkg', '.kml', '.kmz', '.gpx', '.dxf', '.zip',
               '.csv', '.tif', '.tiff', '.pmtiles', '.parquet', '.geoparquet', '.fgb'}
    if ext not in allowed:
        return {"error": "不支持的文件格式: %s；Shapefile 请打包为 ZIP 上传" % (ext or "无扩展名")}
    upload_dir = os.path.join(_TEMP_OUTPUT_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    upload_fd = None
    from backend.services.tools import get_registered_layers_snapshot
    registered_names = {item.get('filename') or item.get('name') for item in get_registered_layers_snapshot()}
    if ext not in ('.tif', '.tiff'):
        # 所有格式原子预留文件名，避免同名 CSV/数据源覆盖仍在使用的文件。
        stem, file_ext = os.path.splitext(filename)
        suffix = 0
        while True:
            candidate = filename if suffix == 0 else f"{stem}_{suffix}{file_ext}"
            candidate_path = os.path.join(upload_dir, candidate)
            if candidate in registered_names or os.path.splitext(candidate)[0] in registered_names:
                suffix += 1
                continue
            try:
                upload_fd = os.open(candidate_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0), 0o666)
                filename = candidate
                break
            except FileExistsError:
                suffix += 1
    elif ext in ('.tif', '.tiff'):
        # Reserve the source and preview together so a same-stem .tif/.tiff
        # cannot overwrite a raster already on the map.
        stem, file_ext = os.path.splitext(filename)
        suffix = 0
        while True:
            candidate = filename if suffix == 0 else f"{stem}_{suffix}{file_ext}"
            candidate_path = os.path.join(upload_dir, candidate)
            candidate_png_path = os.path.join(upload_dir, f"{os.path.splitext(candidate)[0]}.png")
            if candidate in registered_names or os.path.splitext(candidate)[0] in registered_names:
                suffix += 1
                continue
            try:
                upload_fd = os.open(candidate_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0), 0o666)
            except FileExistsError:
                suffix += 1
                continue
            try:
                png_fd = os.open(candidate_png_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0), 0o666)
            except FileExistsError:
                os.close(upload_fd)
                upload_fd = None
                os.unlink(candidate_path)
                suffix += 1
                continue
            except Exception:
                os.close(upload_fd)
                upload_fd = None
                os.unlink(candidate_path)
                raise
            os.close(png_fd)
            filename = candidate
            break
    saved_path = os.path.join(upload_dir, filename)
    png_path = os.path.join(upload_dir, f"{os.path.splitext(filename)[0]}.png") if ext in ('.tif', '.tiff') else None
    def _discard_saved_upload():
        for path in (saved_path, png_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    max_bytes = (64 if ext in ('.geojson', '.json', '.csv') else 300) * 1024 * 1024
    file_size = 0
    try:
        with os.fdopen(upload_fd, 'wb') as f:
            while True:
                chunk = await file.read(8 * 1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > max_bytes:
                    break
                f.write(chunk)
    except BaseException:
        _discard_saved_upload()
        raise
    if file_size > max_bytes:
        _discard_saved_upload()
        return {"error": "文件超过 %dMB 读取限制，请拆分后上传" % (max_bytes // (1024 * 1024))}
    content = None
    if ext in ('.geojson', '.json') and file_size <= 64 * 1024 * 1024:
        with open(saved_path, 'rb') as f:
            content = f.read()

    # ===== GeoJSON =====
    if ext == '.geojson' or ext == '.json':
        if content is None:
            _discard_saved_upload()
            return {"error": f"GeoJSON 文件过大（{file_size/1024/1024:.0f}MB > 64MB），请先在桌面 GIS 中抽稀后再上传"}
        try:
            geojson_data = await loop.run_in_executor(None, orjson.loads, content)
        except orjson.JSONDecodeError:
            _discard_saved_upload()
            return {"error": "GeoJSON 文件格式无效，请检查 JSON 语法后重新上传"}
        source_crs = "EPSG:4326"  # RFC 7946 GeoJSON coordinates use WGS-84 when CRS is omitted.
        if isinstance(geojson_data, dict) and geojson_data.get('crs'):
            try:
                def read_projected_geojson():
                    import geopandas as gpd
                    data = gpd.read_file(saved_path)
                    if data.crs is None:
                        raise ValueError("无法识别声明的坐标参考系")
                    return data.to_crs('EPSG:4326').__geo_interface__, data.crs.to_string()
                geojson_data, source_crs = await asyncio.to_thread(read_projected_geojson)
            except Exception as exc:
                _discard_saved_upload()
                return {"error": "GeoJSON 坐标转换失败: %s" % str(exc)[:200]}
        if isinstance(geojson_data, dict) and geojson_data.get('type') in (
            'Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon',
        ):
            geojson_data = {"type": "Feature", "properties": {}, "geometry": geojson_data}
        if isinstance(geojson_data, dict) and geojson_data.get('type') in ('FeatureCollection', 'Feature'):
            try:
                provenance = _uploaded_vector_provenance(filename, source_crs)
                token = await asyncio.to_thread(_register_uploaded_vector, filename, geojson_data, provenance)
            except (ValueError, TypeError, AttributeError) as exc:
                _discard_saved_upload()
                return {"error": "GeoJSON 格式无效: %s" % exc}
            return {"geojson": geojson_data, "name": filename, "registration_token": token, "provenance": provenance}
        # 支持 GeometryCollection → 转 FeatureCollection
        if isinstance(geojson_data, dict) and geojson_data.get('type') == 'GeometryCollection':
            geoms = geojson_data.get('geometries', [])
            if not isinstance(geoms, list) or any(not isinstance(geom, dict) for geom in geoms):
                _discard_saved_upload()
                return {"error": "GeometryCollection 的 geometries 必须是几何对象列表"}
            features = [{"type": "Feature", "geometry": g, "properties": {}} for g in geoms]
            fc = {"type": "FeatureCollection", "features": features}
            try:
                provenance = _uploaded_vector_provenance(filename, source_crs)
                token = await asyncio.to_thread(_register_uploaded_vector, filename, fc, provenance)
            except (ValueError, TypeError, AttributeError) as exc:
                _discard_saved_upload()
                return {"error": "GeoJSON 格式无效: %s" % exc}
            return {"geojson": fc, "name": filename, "registration_token": token, "provenance": provenance}
        _discard_saved_upload()
        return {"error": "文件不是有效的 GeoJSON 格式"}

    # ===== SHP (zip 包) =====
    if ext == '.zip':
        try:
            with zipfile.ZipFile(saved_path) as zf:
                def _reject_zip_upload(message: str):
                    zf.close()
                    _discard_saved_upload()
                    return {"error": message}

                members = zf.namelist()
                if any(not _is_safe_zip_member(member) for member in members):
                    return _reject_zip_upload("ZIP 包包含不安全的文件路径，已拒绝解压")
                if len(members) > 10000 or sum(info.file_size for info in zf.infolist()) > 512 * 1024 * 1024:
                    return _reject_zip_upload("ZIP 解压内容超过 512MB 或 10000 个文件限制，请拆分后上传")
                shp_files = [n for n in members if n.lower().endswith('.shp')]
                if not shp_files:
                    return _reject_zip_upload("ZIP 包中没有找到 .shp 文件")
                if len(shp_files) > 1:
                    return _reject_zip_upload("ZIP 包包含多个 Shapefile 数据集，请拆分后分别上传")
                with tempfile.TemporaryDirectory() as tmpdir:
                    await asyncio.to_thread(zf.extractall, tmpdir)
                    shp_path = os.path.join(tmpdir, shp_files[0])
                    if not os.path.exists(shp_path):
                        return _reject_zip_upload("无法读取 Shapefile")
                    import geopandas as gpd
                    gdf = await loop.run_in_executor(None, functools.partial(gpd.read_file, shp_path))
                    if gdf.crs is None:
                        return _reject_zip_upload("矢量文件缺少坐标参考系，无法安全转换为 WGS-84；请补充 .prj 文件后重新上传")
                    source_crs = gdf.crs.to_string()
                    geojson_data = await asyncio.to_thread(lambda: gdf.to_crs("EPSG:4326").__geo_interface__)
                    # The archive name was atomically reserved. An internal
                    # common name such as data.shp would collide across ZIPs.
                    name = os.path.splitext(filename)[0]
                    provenance = _uploaded_vector_provenance(filename, source_crs)
                    token = await asyncio.to_thread(_register_uploaded_vector, name, geojson_data, provenance)
                    return {"geojson": geojson_data, "name": name, "registration_token": token, "provenance": provenance}
        except zipfile.BadZipFile:
            _discard_saved_upload()
            return {"error": "ZIP 文件损坏或格式无效，请重新压缩后上传"}
        except Exception as e:
            _discard_saved_upload()
            return {"error": f"无法读取 ZIP 中的 Shapefile: {str(e)[:200]}"}

    # ===== GPKG / KML / GPX 等（geopandas 支持的多图层格式） =====
    supported = {'.gpkg', '.kml', '.kmz', '.gpx', '.dxf'}
    if ext in supported:
        tmp_path = saved_path
        try:
            import geopandas as gpd
            import pyogrio
            # 探测所有图层，取首个非空图层
            layers = await asyncio.to_thread(pyogrio.list_layers, tmp_path)
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
            if gdf.crs is None:
                return {"error": "矢量文件缺少坐标参考系，无法安全转换为 WGS-84"}
            source_crs = gdf.crs.to_string()
            geojson_data = await asyncio.to_thread(lambda: gdf.to_crs("EPSG:4326").__geo_interface__)
            name = os.path.splitext(filename)[0]
            provenance = _uploaded_vector_provenance(filename, source_crs)
            token = await asyncio.to_thread(_register_uploaded_vector, name, geojson_data, provenance)
            return {"geojson": geojson_data, "name": name, "registration_token": token, "provenance": provenance}
        except Exception as e:
            return {"error": f"无法读取 {ext} 文件: {str(e)[:200]}"}
        finally:
            try: os.unlink(tmp_path)
            except: pass

    # ===== GeoTIFF 栅格加载 =====
    if ext in ('.tif', '.tiff'):
        tif_path = saved_path
        try:
            import rasterio
            from rasterio.enums import Resampling
            from rasterio.transform import Affine, array_bounds
            from rasterio.warp import calculate_default_transform, reproject, transform_bounds
            import numpy as np
            from PIL import Image

            with rasterio.open(tif_path) as src:
                nodata = src.nodata
                if src.crs is None:
                    raise _MissingGeoTiffCrsError(
                        "GeoTIFF 缺少坐标参考系，无法安全定位到地图；请先定义 CRS 后重新上传"
                    )
                source_crs = src.crs
                source_width, source_height = src.width, src.height
                source_bands = src.count
                source_nodata = src.nodata
                source_transform = src.transform
                source_is_geographic = source_crs.is_geographic
                source_tags = {key.upper(): value for key, value in src.tags().items()}
                source_value_units = (
                    (src.units[0] if src.units and src.units[0] else None)
                    or source_tags.get("VALUE_UNITS")
                    or source_tags.get("UNITTYPE")
                )
                source_label = (
                    source_tags.get("SOURCE_LABEL") or source_tags.get("SOURCE")
                    or "本地上传（文件未包含来源标签）"
                )
                source_quality_note = source_tags.get("QUALITY_NOTE")
                preview_scale = max(1.0, (src.width * src.height / _MAX_RASTER_PREVIEW_PIXELS) ** 0.5)
                preview_width = max(1, int(src.width / preview_scale))
                preview_height = max(1, int(src.height / preview_scale))
                preview_downsampled = preview_width < src.width or preview_height < src.height
                preview_transform = src.transform * Affine.scale(
                    src.width / preview_width, src.height / preview_height,
                )
                if src.count >= 3:
                    source_rgb = src.read(
                        (1, 2, 3), out_shape=(3, preview_height, preview_width),
                        resampling=Resampling.bilinear, masked=True,
                    )
                    red, green, blue = [
                        np.ma.filled(source_rgb[index].astype(np.float32), np.nan)
                        for index in range(3)
                    ]
                    valid = ~np.ma.getmaskarray(source_rgb).any(axis=0)
                else:
                    source_band = src.read(
                        1, out_shape=(preview_height, preview_width),
                        resampling=Resampling.bilinear, masked=True,
                    )
                    band = np.ma.filled(source_band.astype(np.float32), np.nan)
                    red = green = blue = band
                    valid = ~np.ma.getmaskarray(source_band)

                valid &= np.isfinite(red) & np.isfinite(green) & np.isfinite(blue)

                def norm(b):
                    values = b[valid]
                    if not values.size:
                        return np.full(b.shape, -9999, dtype=np.float32)
                    low, high = np.percentile(values, [2, 98])
                    if high <= low:
                        scaled = np.zeros(b.shape, dtype=np.float32)
                    else:
                        scaled = (np.clip(b, low, high) - low) / (high - low) * 255
                    scaled[~valid] = -9999
                    return scaled.astype(np.float32)

                dst_crs = "EPSG:3857"
                dst_transform, dst_width, dst_height = calculate_default_transform(
                    source_crs, dst_crs, preview_width, preview_height, *src.bounds
                )
                output_downsampled = False
                for _ in range(3):
                    if dst_width * dst_height <= _MAX_RASTER_PREVIEW_PIXELS:
                        break
                    output_downsampled = True
                    target_scale = (dst_width * dst_height / _MAX_RASTER_PREVIEW_PIXELS) ** 0.5
                    target_width = max(1, int(dst_width / target_scale))
                    target_height = max(1, int(dst_height / target_scale))
                    dst_transform, dst_width, dst_height = calculate_default_transform(
                        source_crs, dst_crs, preview_width, preview_height, *src.bounds,
                        dst_width=target_width, dst_height=target_height,
                    )
                if dst_width * dst_height > _MAX_RASTER_PREVIEW_PIXELS:
                    raise ValueError("无法将栅格地图预览缩小到安全像元数")
                preview_downsampled = preview_downsampled or output_downsampled
                rgb = np.zeros((dst_height, dst_width, 3), dtype=np.uint8)
                for index, band in enumerate((red, green, blue)):
                    destination = np.zeros((dst_height, dst_width), dtype=np.float32)
                    reproject(
                        source=norm(band), destination=destination,
                        src_transform=preview_transform, src_crs=source_crs,
                        dst_transform=dst_transform, dst_crs=dst_crs,
                        src_nodata=-9999, dst_nodata=0, resampling=Resampling.bilinear,
                    )
                    rgb[:, :, index] = np.clip(destination, 0, 255).astype(np.uint8)

                source_valid = valid.astype(np.uint8)
                destination_valid = np.zeros((dst_height, dst_width), dtype=np.uint8)
                reproject(
                    source=source_valid, destination=destination_valid,
                    src_transform=preview_transform, src_crs=source_crs,
                    dst_transform=dst_transform, dst_crs=dst_crs,
                    src_nodata=0, dst_nodata=0, resampling=Resampling.nearest,
                )
                rgba = np.dstack((rgb, destination_valid * 255))
                img = Image.fromarray(rgba, mode="RGBA")
                name = os.path.splitext(filename)[0]
                png_name = f"{name}.png"
                img.save(png_path)

                bounds_mercator = array_bounds(dst_height, dst_width, dst_transform)
                bounds_wgs84 = transform_bounds(dst_crs, 'EPSG:4326', *bounds_mercator)
                w, h = dst_width, dst_height

            from backend.services.tools import _register_raster_layer
            raster_info = {
                "filename": png_name, "url": f"/output/uploads/{quote(png_name, safe='')}",
                "source_filename": filename, "source_name": name,
                "source_url": f"/output/uploads/{quote(filename, safe='')}",
                "bounds": list(bounds_wgs84), "width": w, "height": h,
                "crs": source_crs.to_string(),
                "source_width": source_width, "source_height": source_height,
                "preview_downsampled": preview_downsampled,
                "bands": source_bands, "nodata": source_nodata if source_nodata is None or np.isfinite(source_nodata) else None,
                "pixel_size": [abs(source_transform.a), abs(source_transform.e)],
                "pixel_units": source_crs.linear_units if source_crs.is_projected else ("degree" if source_is_geographic else "unknown"),
                "value_units": source_value_units,
                "vertical_datum": source_tags.get("VERTICAL_DATUM"),
                "source_label": source_label,
                "source_reference": source_tags.get("SOURCE_URL") or source_tags.get("CITATION"),
                "quality_warnings": (
                    (["栅格值单位未在文件元数据中标注；解释高程或计算坡度前请核实源数据单位"] if not source_value_units else [])
                    + (["地图预览已降采样；后续栅格分析仍使用保留的原始 GeoTIFF"] if preview_downsampled else [])
                    + ([source_quality_note] if source_quality_note else [])
                ),
            }
            token = await asyncio.to_thread(_register_raster_layer, name, raster_info, saved_path)
            return {
                "name": name,
                "raster_info": raster_info,
                "registration_token": token,
                "message": f"已加载栅格图层: {name}"
            }
        except _MissingGeoTiffCrsError as e:
            for path in (tif_path, png_path):
                try: os.unlink(path)
                except OSError: pass
            return {"error": str(e)}
        except ImportError:
            for path in (tif_path, png_path):
                try: os.unlink(path)
                except OSError: pass
            return {"error": "栅格处理依赖 rasterio/PIL，请安装: pip install rasterio pillow numpy"}
        except Exception as e:
            for path in (tif_path, png_path):
                if path:
                    try: os.unlink(path)
                    except OSError: pass
            import traceback
            return {"error": f"GeoTIFF 处理失败: {str(e)[:300]}"}

    # ===== CSV（保存文件，让AI处理转换） =====
    if ext == '.csv':
        try:
            def read_csv_preview():
                import pandas as pd
                with open(saved_path, 'r', encoding='utf-8-sig', newline='') as source:
                    df = pd.read_csv(source)
                return df.columns.tolist(), orjson.loads(df.head(3).to_json(orient='records')), len(df)
            columns, preview, rows = await asyncio.to_thread(read_csv_preview)

            return {
                "csv_info": {
                    "filename": filename,
                    "rows": rows,
                    "columns": columns,
                    "preview": preview,
                    "path": saved_path
                },
                "message": f"CSV已保存，共{rows}行，列名：{', '.join(columns)}"
            }
        except Exception as e:
            _discard_saved_upload()
            return {"error": f"CSV 读取失败: {str(e)[:200]}"}

    # ===== 云原生格式：PMTiles / GeoParquet / FlatGeobuf =====
    if ext in ('.pmtiles', '.parquet', '.geoparquet', '.fgb'):
        from backend.services import cloud_native as cn
        name = os.path.splitext(filename)[0]
        try:
            if ext == '.pmtiles':
                try:
                    geojson, info = await asyncio.to_thread(cn.pmtiles_vector_to_geojson, saved_path)
                    source_crs = info.get("crs") if isinstance(info, dict) else None
                    provenance = _uploaded_vector_provenance(filename, source_crs)
                    token = await asyncio.to_thread(_register_uploaded_vector, name, geojson, provenance)
                    return {"geojson": geojson, "name": name, "registration_token": token, "pmtiles_info": info, "provenance": provenance}
                except cn.CloudNativeError:
                    # 栅格 PMTiles：中心瓦片作为影像叠加
                    tile_bytes, bounds, fmt, info = await asyncio.to_thread(cn.pmtiles_raster_tile_bounds, saved_path)
                    upload_dir = os.path.join(_TEMP_OUTPUT_DIR, "uploads")
                    os.makedirs(upload_dir, exist_ok=True)
                    tile_name = f"pmtiles_{name}.{fmt}"
                    tile_suffix = 0
                    while True:
                        tile_name = f"pmtiles_{name}{'_' + str(tile_suffix) if tile_suffix else ''}.{fmt}"
                        tile_path = os.path.join(upload_dir, tile_name)
                        try:
                            tile_fd = os.open(tile_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0), 0o666)
                            break
                        except FileExistsError:
                            tile_suffix += 1
                    try:
                        with os.fdopen(tile_fd, "wb") as f:
                            f.write(tile_bytes)
                    except BaseException:
                        try: os.unlink(tile_path)
                        except OSError: pass
                        raise
                    return {
                        "name": name,
                        "raster_info": {
                            "filename": tile_name,
                            "url": f"/output/uploads/{quote(tile_name, safe='')}",
                            "bounds": [float(v) for v in bounds],
                        },
                        "message": f"已加载栅格 PMTiles: {name}",
                    }
            fmt = "GeoParquet" if ext in ('.parquet', '.geoparquet') else "FlatGeobuf"
            geojson, meta = await asyncio.to_thread(cn.cloud_vector_to_geojson, saved_path, fmt)
            source_crs = meta.get("crs") if isinstance(meta, dict) else None
            provenance = _uploaded_vector_provenance(filename, source_crs, fmt)
            token = await asyncio.to_thread(_register_uploaded_vector, name, geojson, provenance)
            return {"geojson": geojson, "name": name, "registration_token": token, "meta": meta, "provenance": provenance}
        except cn.CloudNativeError as e:
            _discard_saved_upload()
            return {"error": str(e)}
        except Exception as e:
            _discard_saved_upload()
            return {"error": "云原生文件读取失败: %s" % str(e)[:200]}

    _discard_saved_upload()
    return {"error": f"不支持的文件格式: {ext}，支持: .geojson .json .gpkg .kml .kmz .gpx .dxf .tif .tiff .zip(含shp) .pmtiles .parquet .fgb"}

	# ===== 工程保存/加载 =====
class ProjectSaveRequest(BaseModel):
    project_id: Optional[str] = None
    name: str = ""
    session_id: str = "default"
    provider: str = "glm-routed"
    map_state: dict = {}
    messages: list = []
    layers: list = []
    layer_groups: list = []

class ProjectAutoSaveRequest(BaseModel):
    layer_groups: list = []
    layer_assignments: list[dict] = []

class ProjectRenameRequest(BaseModel):
    name: str

@app.post("/api/projects/auto-save")
async def auto_save_project(
    session_id: str = "default",
    project_id: str = None,
    req: Optional[ProjectAutoSaveRequest] = None,
):
    """由前端在对话完成后调用，自动保存当前工程"""
    try:
        result = await asyncio.to_thread(
            project_service.auto_save,
            session_id=session_id,
            project_id=project_id,
            layer_groups=req.layer_groups if req else None,
            layer_assignments=req.layer_assignments if req else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        return {"id": None, "note": "无消息，跳过保存"}
    return result

@app.get("/api/projects")
async def list_projects():
    projs = await asyncio.to_thread(project_service.list_projects)
    return {"projects": projs}

@app.post("/api/projects")
async def save_project(req: ProjectSaveRequest):
    try:
        result = await asyncio.to_thread(
            project_service.save_project,
            project_id=req.project_id,
            name=req.name or "未命名工程",
            session_id=req.session_id,
            provider=req.provider,
            map_state=req.map_state,
            messages=req.messages,
            layers=req.layers,
            layer_groups=req.layer_groups,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result

@app.get("/api/projects/{project_id}")
async def load_project(project_id: str):
    # activate_project 内部会做图层注册/边界计算等重活（含锁操作），
    # 必须挪出事件循环，否则大工程会卡死健康检查/取消等所有请求
    try:
        result = await asyncio.to_thread(project_service.open_project, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return result

@app.get("/api/projects/{project_id}/assets/{filename}")
async def get_project_asset(project_id: str, filename: str):
    path = await asyncio.to_thread(project_service.get_project_raster_asset, project_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="工程资源不存在")
    import mimetypes
    return FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "application/octet-stream")

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    await asyncio.to_thread(project_service.delete_project, project_id)
    return {"success": True}

@app.delete("/api/projects")
async def delete_all_projects():
    await asyncio.to_thread(project_service.delete_all_projects)
    return {"success": True}

@app.post("/api/projects/{project_id}/rename")
async def rename_project(project_id: str, req: ProjectRenameRequest):
    result = await asyncio.to_thread(project_service.rename_project, project_id, req.name)
    if result is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return result

@app.get("/api/projects/{project_id}/export")
async def export_project(project_id: str):
    try:
        data = await asyncio.to_thread(project_service.export_project, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if data is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=project_{project_id}.giswork"},
    )

@app.post("/api/projects/import")
async def import_project(file: UploadFile = File(...)):
    # UploadFile is already spooled to memory/disk by Starlette; pass its stream
    # through instead of materializing a second full copy of a potentially large project.
    await file.seek(0)
    try:
        result = await asyncio.to_thread(project_service.import_project, file.file)
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
    registration_token: Optional[str] = None

@app.post("/api/layer/unregister")
async def unregister_layer(request: UnregisterLayerRequest):
    from backend.services import tools as registry_tools
    with registry_tools._state_lock:
        current = registry_tools._registered_layers.get(request.name)
        stale = bool(request.registration_token is not None and current
                     and current.get("registration_token") != request.registration_token)
        removed = _unregister_layer(request.name, request.registration_token)
    return {"success": True, "removed": removed, "stale": stale,
            "message": f"已取消注册图层: {request.name}" if removed else "旧注册项已不存在或已更新，保留当前版本"}


class RegisterLayerRequest(BaseModel):
    name: str
    geojson: Optional[dict] = None
    raster: Optional[dict] = None
    group_name: Optional[str] = None

@app.post("/api/layer/register")
async def register_layer(request: RegisterLayerRequest):
    try:
        if request.raster is not None:
            from backend.services.tools import _register_raster_layer
            token = await asyncio.to_thread(_register_raster_layer, request.name, request.raster)
        elif request.geojson is not None:
            token = _register_layer(request.name, request.geojson, group_name=request.group_name)
        else:
            raise ValueError("图层缺少矢量或栅格数据")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "registration_token": token, "message": f"已注册图层: {request.name}"}


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


def _export_shp_sync(geojson: dict, crs: str, name: str):
    """同步实现：GeoJSON → Shapefile → zip。返回 (BytesIO, None) 或 (None, 错误信息)。

    geopandas 转换 + zip 打包是纯 CPU/IO 重活，大图层可达数十秒，
    必须经 asyncio.to_thread 调用，不能占着事件循环。
    """
    import tempfile, zipfile, shutil
    import geopandas as gpd

    try:
        gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs=crs)
        if gdf.empty:
            return None, "没有可导出的要素"

        # 不静默丢弃混合几何要素；由用户选择同类型图层后重试。
        types = gdf.geom_type.value_counts()
        if len(types) > 1:
            return None, "Shapefile 不支持混合几何类型，请按几何类型拆分图层后导出，或使用 GeoJSON 保留全部要素"

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
        shp_base = os.path.join(tmp_dir, name)
        gdf.to_file(shp_base + ".shp", driver="ESRI Shapefile", encoding="utf-8")

        # 打包 zip
        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(tmp_dir):
                fpath = os.path.join(tmp_dir, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, fname)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        zip_buf.seek(0)
        return zip_buf, None
    except Exception as e:
        return None, f"SHP 导出失败: {str(e)[:200]}"


@app.post("/api/layer/export-shp")
async def export_shp(request: ExportShpRequest):
    """将 GeoJSON 导出为 Shapefile (zip 包)，包含 .shp .shx .dbf .prj .cpg"""
    zip_buf, err = await asyncio.to_thread(
        _export_shp_sync, request.geojson, request.crs, request.name)
    if err:
        return {"error": err}
    safe_name = request.name.replace(" ", "_").replace("/", "_").replace("\\", "_")
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={safe_name}.zip"},
    )


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
    handle: str = ""
    query: str = ""
    kind: str = ""
    area: str = ""
    bbox: str = ""
    provider: str = ""
    file_format: str = ""
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
                handle=request.handle,
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


# ===== GeoSource 全球 GIS 空间服务库（内嵌版接口） =====

class GeoSourceSearchRequest(BaseModel):
    keyword: Optional[str] = ""
    country: Optional[str] = ""
    protocol: Optional[str] = ""
    category: Optional[str] = ""
    is_free: Optional[bool] = None
    need_no_key: Optional[bool] = None
    page: int = 1
    page_size: int = 20
    limit: Optional[int] = None

class GeoSourceSQLRequest(BaseModel):
    query: str


@app.get('/api/geosource/stats')
async def api_geosource_stats():
    """获取 GeoSource 数据源库全貌统计信息（服务数、图层数、顶部分类/协议/国家）。"""
    from backend.services import geosource_service
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, geosource_service.list_categories_and_stats)


@app.post('/api/geosource/search')
async def api_geosource_search(request: GeoSourceSearchRequest):
    """搜索全球 GIS 空间服务（支持分页与全量检索）。"""
    from backend.services import geosource_service
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: geosource_service.search_services(
            keyword=request.keyword or None,
            country=request.country or None,
            protocol=request.protocol or None,
            category=request.category or None,
            is_free=request.is_free,
            need_no_key=request.need_no_key,
            page=request.page,
            page_size=request.page_size,
            limit=request.limit,
        ),
    )


@app.get('/api/geosource/service/{service_id}')
async def api_geosource_detail(service_id: str):
    """获取指定服务详情及包含的子图层列表。"""
    from backend.services import geosource_service
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: geosource_service.get_service_detail(service_id))
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@app.get('/api/geosource/proxy')
@app.post('/api/geosource/proxy')
async def api_geosource_proxy(url: str = Query(..., description="远程目标 URL")):
    """代理获取远程 GIS 服务端点、GeoJSON 或元数据，避免浏览器端跨域（CORS）与网络限制。"""
    from backend.services.model_transport import effective_model_proxy
    import urllib.request
    import urllib.error

    url_str = (url or "").strip()
    if not url_str.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="非法 URL 地址")

    loop = asyncio.get_event_loop()

    def _fetch():
        proxy = effective_model_proxy(url_str)
        proxy_dict = {"http": proxy, "https": proxy} if proxy else {}
        handler = urllib.request.ProxyHandler(proxy_dict) if proxy_dict else urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(
            url_str,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 GIS-WorkTable",
                "Accept": "application/json, text/plain, */*"
            }
        )
        try:
            with opener.open(req, timeout=12) as resp:
                content = resp.read()
                raw_type = resp.headers.get("Content-Type", "application/json")
                return content, raw_type.split(";")[0]
        except urllib.error.HTTPError as e:
            raise HTTPException(status_code=e.code, detail=f"远程 GIS 服务返回 HTTP {e.code}")
        except Exception:
            raise HTTPException(status_code=502, detail="代理请求失败，请检查目标服务连接；请求细节已隐藏。")

    content, media_type = await loop.run_in_executor(None, _fetch)
    return Response(content=content, media_type=media_type)


@app.post('/api/geosource/query-sql')
async def api_geosource_query_sql(request: GeoSourceSQLRequest):
    """执行安全只读 SQL 查询。"""
    from backend.services import geosource_service
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: geosource_service.query_sql(request.query))


def _reverse_geocode_sync(lng: float, lat: float) -> dict:
    """逆地理编码同步实现：高德（国内高精度）→ Nominatim（免费回退）。

    内含同步 requests 网络调用（各 4~5s 超时），必须经由 asyncio.to_thread 调用，
    不能直接在事件循环上跑，否则每次点图都会卡住健康检查/取消等所有请求。
    """
    from backend.services.tools import _current_amap_key
    from backend.services.cloud_native import get_effective_proxies
    import requests

    result = {
        "ok": True,
        "lng": lng,
        "lat": lat,
        "formatted_address": f"经度 {lng:.5f}°, 纬度 {lat:.5f}°",
        "country": "",
        "province": "",
        "city": "",
        "district": "",
        "poi_name": "",
    }

    # 1. 优先尝试高德（国内高精度）
    if _current_amap_key:
        try:
            from backend.services.geo_coords import wgs84_to_gcj02
            gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
            resp = requests.get(
                "https://restapi.amap.com/v3/geocode/regeo",
                params={"key": _current_amap_key, "location": f"{gcj_lng},{gcj_lat}", "output": "JSON", "radius": 200, "extensions": "all"},
                timeout=4,
            )
            data = resp.json()
            if data.get("status") == "1":
                regeo = data.get("regeocode", {})
                addr = regeo.get("formatted_address", "")
                comp = regeo.get("addressComponent", {})
                if addr:
                    result["formatted_address"] = addr
                    result["country"] = comp.get("country", "中国")
                    result["province"] = comp.get("province", "")
                    result["city"] = comp.get("city", "") or comp.get("province", "")
                    result["district"] = comp.get("district", "")
                    pois = regeo.get("pois", [])
                    if pois:
                        result["poi_name"] = pois[0].get("name", "")
                    return result
        except Exception:
            pass

    # 2. 免费回退：OSM Nominatim（全球通用）
    try:
        proxies = get_effective_proxies()
        headers = {"User-Agent": "GIS-WorkTable/2.0 ReverseGeocoder"}
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lng, "format": "json", "zoom": 14, "addressdetails": 1},
            headers=headers,
            proxies=proxies,
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            display_name = data.get("display_name", "")
            addr = data.get("address", {})
            if display_name:
                result["formatted_address"] = display_name
                result["country"] = addr.get("country", "")
                result["province"] = addr.get("state", "") or addr.get("province", "")
                result["city"] = addr.get("city", "") or addr.get("county", "")
                result["district"] = addr.get("suburb", "") or addr.get("district", "") or addr.get("town", "")
                result["poi_name"] = addr.get("amenity", "") or addr.get("building", "") or addr.get("road", "")
                return result
    except Exception:
        pass

    return result


@app.get("/api/geo/reverse-geocode")
async def api_reverse_geocode(lng: float = Query(...), lat: float = Query(...)):
    """秒级逆地理编码：将 (lng, lat) 经纬度快速反解为行政区划地址与地理特征"""
    # 同步网络调用挪出事件循环（见 _reverse_geocode_sync 注释）
    return await asyncio.to_thread(_reverse_geocode_sync, lng, lat)


# ===== 处理历史（前端「历史」面板） =====

@app.get("/api/history")
async def api_history(limit: int = 50):
    """工具执行历史（倒序），供右侧历史面板展示"""
    from backend.services.history_service import list_entries
    from backend.services.history_service import get_storage_warning
    return {"history": list_entries(limit), "warning": get_storage_warning()}


@app.delete("/api/history")
async def api_history_clear():
    from backend.services.history_service import clear
    if not clear():
        from backend.services.history_service import get_storage_warning
        raise HTTPException(status_code=500, detail=get_storage_warning() or "历史未能写入磁盘")
    return {"status": "ok", "message": "历史已清空"}


class HistoryRerunRequest(BaseModel):
    index: int


@app.post("/api/history/rerun")
async def api_history_rerun(request: HistoryRerunRequest):
    """按编号重跑历史工具（前端历史面板「重跑」按钮）。
    返回结构与聊天侧一致：layers/layer_ops 由前端照常上图。"""
    from backend.services.tools import (
        tools as _tool_list, get_pending_state, reset_state,
        acquire_shared_state_lock, release_shared_state_lock,
    )
    if not await asyncio.to_thread(acquire_shared_state_lock, 0):
        raise HTTPException(status_code=409, detail="当前 GIS 工作区正在处理另一项操作")
    try:
        reg = {t.name: t for t in _tool_list}
        rerun_tool = reg.get("rerun_history")
        if rerun_tool is None:
            raise HTTPException(status_code=500, detail="rerun_history 工具未注册")
        reset_state()
        resp = rerun_tool.invoke({"index": request.index})
        pending = get_pending_state()
        # rerun_history 的响应首句包含目标工具的真实执行状态；仅工具返回了一段
        # “失败”文本并不代表重跑成功，前端必须据此决定是否应用本次产物。
        status_line = str(resp).split("；", 1)[0]
        rerun_ok = status_line.startswith(f"已重跑 #{request.index} ") and status_line.endswith("→ 成功")
        return {
            "response": resp,
            "ok": rerun_ok,
            "error": "" if rerun_ok else str(resp),
            "layers": pending.get("layers", []),
            "layer_ops": pending.get("layer_ops", []),
            "images": pending.get("images", []),
            "clear_layers": pending.get("clear_layers", False),
        }
    finally:
        release_shared_state_lock()


# ===== 在线云原生数据加载（连接器面板「粘贴 URL」入口） =====

class OnlineLoadRequest(BaseModel):
    source: str                          # http(s) URL 或本地路径
    type: str = "auto"                   # cog | pmtiles | geoparquet | flatgeobuf | auto
    layer_name: str = ""
    bbox: str = ""                       # minx,miny,maxx,maxy（矢量类可选）


@app.post('/api/online/load')
async def api_online_load(request: OnlineLoadRequest):
    """按 URL/路径加载云原生数据（COG/PMTiles/GeoParquet/FlatGeobuf）→ 注册为图层。"""
    from backend.services import cloud_native as cn
    src = (request.source or "").strip()
    if not src:
        return {"error": "请提供数据 URL 或路径"}
    ltype = (request.type or "auto").strip().lower()
    if ltype == "auto":
        ext = os.path.splitext(src)[1].lower()
        ltype = {'.tif': 'cog', '.tiff': 'cog', '.pmtiles': 'pmtiles',
                 '.parquet': 'geoparquet', '.geoparquet': 'geoparquet',
                 '.fgb': 'flatgeobuf'}.get(ext, "")
        if not ltype:
            return {"error": f"无法从扩展名识别数据类型（{ext or '无'}），请显式指定 type"}
    loop = asyncio.get_event_loop()

    def _load():
        if ltype == "cog":
            return {"type": "cog", "result": cn.read_cog(src), "name": request.layer_name}
        if ltype == "pmtiles":
            try:
                geojson, info = cn.pmtiles_vector_to_geojson(src)
                return {"type": "pmtiles_vector", "geojson": geojson, "info": info}
            except cn.CloudNativeError:
                tile_bytes, bounds, fmt, info = cn.pmtiles_raster_tile_bounds(src)
                return {"type": "pmtiles_raster", "tile_bytes": tile_bytes,
                        "bounds": bounds, "fmt": fmt, "info": info}
        fmt = "GeoParquet" if ltype == "geoparquet" else "FlatGeobuf"
        bbox = cn.parse_bbox(request.bbox) if request.bbox else None
        geojson, meta = cn.cloud_vector_to_geojson(src, fmt, bbox=bbox)
        return {"type": ltype, "geojson": geojson, "meta": meta}

    try:
        result = await loop.run_in_executor(None, _load)
    except cn.CloudNativeError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"加载失败: {str(e)[:300]}"}

    name = request.layer_name.strip()
    if result["type"] == "cog":
        import re as _re
        import time as _time
        r = result["result"]
        name = name or "COG影像"
        safe = _re.sub(r'[\\/:*?"<>|]', "_", name)
        png_name = f"cog_{safe}_{int(_time.time())}.png"
        upload_dir = os.path.join(_TEMP_OUTPUT_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        with open(os.path.join(upload_dir, png_name), "wb") as f:
            f.write(r["png_bytes"])
        return {
            "raster_info": {
                "filename": png_name,
                "url": f"/output/uploads/{png_name}",
                "bounds": [float(v) for v in r["bounds"]],
            },
            "message": f"已加载 COG 影像: {name}",
            "name": name,
            "meta": r["meta"],
        }
    if result["type"] == "pmtiles_raster":
        import re as _re
        import time as _time
        name = name or "PMTiles栅格"
        safe = _re.sub(r'[\\/:*?"<>|]', "_", name)
        tile_name = f"pmtiles_{safe}_{int(_time.time())}.{result['fmt']}"
        upload_dir = os.path.join(_TEMP_OUTPUT_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        with open(os.path.join(upload_dir, tile_name), "wb") as f:
            f.write(result["tile_bytes"])
        return {
            "raster_info": {
                "filename": tile_name,
                "url": f"/output/uploads/{tile_name}",
                "bounds": [float(v) for v in result["bounds"]],
            },
            "message": f"已加载栅格 PMTiles: {name}",
            "name": name,
            "meta": result["info"],
        }
    # 矢量类
    geojson = result["geojson"]
    if not name:
        name = os.path.splitext(os.path.basename(src))[0] or "云原生图层"
    _register_layer(name, geojson)
    return {"geojson": geojson, "name": name, "meta": result.get("meta") or result.get("info")}


# ===== 工具直连执行（手动面板通道：不经 LLM，直接调用注册工具） =====

class ToolInvokeRequest(BaseModel):
    name: str                            # tools.py 注册的工具名
    arguments: dict = {}                 # 工具参数


class UrlVectorFetchRequest(BaseModel):
    url: str
    layer_id: str = ""
    bbox: str = ""
    where: str = "1=1"
    mode: str = "preview"
    limit: int = 1000
    max_features: int = 100000
    output_format: str = "geojson"
    output_filename: str = ""


class UrlInspectRequest(BaseModel):
    url: str
    layer_id: str = ""


@app.post('/api/url-data/inspect')
async def api_inspect_url_vector(request: UrlInspectRequest):
    if not (request.url or "").strip():
        raise HTTPException(status_code=400, detail="请输入 ArcGIS REST 图层 URL")
    from backend.services import url_gis_service as _ugs
    loop = asyncio.get_event_loop()
    try:
        inspect_url = request.url.strip()
        if request.layer_id:
            clean = inspect_url.split("?")[0].rstrip("/")
            parsed = urllib.parse.urlsplit(inspect_url)
            if not clean.endswith("/" + str(request.layer_id)):
                inspect_url = clean + "/" + str(request.layer_id) + (("?" + parsed.query) if parsed.query else "")
        result = await loop.run_in_executor(None, _ugs.inspect_gis_url, inspect_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:400])
    result["url"] = _ugs._sanitize_source_url(inspect_url)
    return result


def _run_url_vector_fetch(job_id: str, request: UrlVectorFetchRequest, cancel_event):
    started = time.time()
    def progress(update):
        with _url_fetch_jobs_lock:
            job = _url_fetch_jobs.get(job_id)
            if job:
                job["progress"] = dict(update)
    try:
        from backend.services import url_gis_service as _ugs
        result = _ugs.fetch_gis_data_url(
            request.url, layer_id=request.layer_id, bbox=request.bbox, where=request.where,
            mode=request.mode, limit=request.limit, max_features=request.max_features,
            output_format=request.output_format, output_filename=request.output_filename,
            progress_callback=progress, cancel_check=cancel_event.is_set,
        )
        output_urls = {
            key: f"/output/downloads/{os.path.basename(result[path_key])}"
            for key, path_key in (("data_url", "file_path"), ("recipe_url", "recipe_path"),
                                  ("report_url", "report_path"), ("manifest_url", "manifest_path"))
        }
        safe_result = {key: value for key, value in result.items() if key not in {"file_path", "recipe_path", "report_path", "manifest_path", "geojson_data"}}
        safe_result.update(output_urls)
        # 获取函数正常返回表示结果文件已完整生成；仅协作式取消抛出的异常才标记取消。
        # 非分页预览无法中断正在进行的 HTTP 请求，避免把已经生成的交付物隐藏掉。
        state = "completed"
        with _url_fetch_jobs_lock:
            _url_fetch_jobs[job_id].update({"status": state, "result": safe_result, "finished_at": time.time()})
        try:
            from backend.services import history_service as _hs
            artifacts = [{"filename": os.path.basename(result[k]), "path": f"downloads/{os.path.basename(result[k])}",
                          "url": output_urls[url_key]} for k, url_key in (("file_path", "data_url"), ("recipe_path", "recipe_url"),
                                                                          ("report_path", "report_url"), ("manifest_path", "manifest_url"))]
            history_params = request.dict()
            history_params["url"] = _ugs._sanitize_source_url(request.url)
            _hs.record("fetch_gis_data_url", history_params, state == "completed", [],
                       error="获取已由用户取消" if state == "cancelled" else "",
                       duration_ms=int((time.time() - started) * 1000), file_artifacts=artifacts)
        except Exception as history_error:
            print(f"[URL Fetch] history record failed: {history_error}", flush=True)
    except Exception as exc:
        state = "cancelled" if cancel_event.is_set() else "unknown" if "完整性未知" in str(exc) else "failed"
        with _url_fetch_jobs_lock:
            _url_fetch_jobs[job_id].update({"status": state, "error": str(exc)[:500], "finished_at": time.time()})


@app.post('/api/url-data/jobs')
async def api_start_url_vector_fetch(request: UrlVectorFetchRequest):
    if not (request.url or "").strip():
        raise HTTPException(status_code=400, detail="请输入 ArcGIS REST 图层 URL")
    if request.mode not in {"preview", "full"}:
        raise HTTPException(status_code=400, detail="mode 只能是 preview 或 full")
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    with _url_fetch_jobs_lock:
        _url_fetch_jobs[job_id] = {"status": "running", "progress": {"phase": "inspecting", "completed": 0, "total": None},
                                   "cancel_event": cancel_event, "created_at": time.time()}
        finished = [key for key, value in _url_fetch_jobs.items()
                    if value.get("status") not in {"running", "cancelling"}]
        for key in finished[:-40]:
            _url_fetch_jobs.pop(key, None)
    _url_fetch_executor.submit(_run_url_vector_fetch, job_id, request, cancel_event)
    return {"job_id": job_id, "status": "running"}


@app.get('/api/url-data/jobs/{job_id}')
async def api_get_url_vector_fetch(job_id: str):
    with _url_fetch_jobs_lock:
        job = _url_fetch_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="获取任务不存在或已过期")
        return {key: job.get(key) for key in ("status", "progress", "result", "error", "created_at", "finished_at")}


@app.delete('/api/url-data/jobs/{job_id}')
async def api_cancel_url_vector_fetch(job_id: str):
    with _url_fetch_jobs_lock:
        job = _url_fetch_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="获取任务不存在或已过期")
        if job.get("status") == "running":
            job["cancel_event"].set()
            job["status"] = "cancelling"
        status = job.get("status")
    return {"job_id": job_id, "status": status}


@app.post('/api/tools/invoke')
async def api_tools_invoke(request: ToolInvokeRequest):
    """直连执行一个 @tool 注册工具（前端手动面板用，不走 AI）。

    与聊天侧同链路：图层产物经 _push_layer 通道返回，执行自动进处理历史（可重跑）。
    """
    from backend.services.tools import (
        tools as _tool_list, get_pending_state, reset_state,
        acquire_shared_state_lock, release_shared_state_lock,
    )
    reg = {t.name: t for t in _tool_list}
    tool = reg.get(request.name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"工具不存在: {request.name}")
    args = request.arguments or {}
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="arguments 应为对象")
    if not await asyncio.to_thread(acquire_shared_state_lock, 0):
        return {"ok": False, "busy": True, "error": "当前 GIS 工作区正在处理另一项操作"}
    try:
        # 在工作区锁内检查图层参数，避免与并行图层更新竞争。
        from backend.services.tool_args_guard import validate_tool_args
        args, _arg_warnings = validate_tool_args(request.name, args)
        reset_state()
        # 直连链路同样绑定 run/task，让工具产物（图片/文件）进历史与 SQLite 台账
        from backend.services.tools import set_current_run as _scr, set_current_task as _sct
        import uuid as _uuid_mod
        run_id = _uuid_mod.uuid4().hex[:12]
        from backend.services import task_manager as _tm
        task_id = _tm.find_or_create_task('default', request.name)
        from backend.services import storage_service as _ss
        _ss.record_run_start(run_id, "default", f"直接工具调用: {request.name}", task_id)
        _scr(run_id)
        _sct(task_id)
        response = ""
        ok = False
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None, functools.partial(tool.invoke, args))
            from backend.services.tools import _tool_result_failed
            ok = not _tool_result_failed(request.name, response)
        except Exception as e:
            response = f"工具执行失败: {str(e)[:400]}"
            ok = False
        _ss.record_run_finish(
            run_id, str(response), "success" if ok else "failed", "NOT_CHECKED")
        pending = get_pending_state()
        return {
            "ok": ok,
            "tool": request.name,
            "param_warnings": _arg_warnings if _arg_warnings else [],
            "response": response,
            "layers": pending.get("layers", []),
            "layer_ops": pending.get("layer_ops", []),
            "images": pending.get("images", []),
            "heatmap": pending.get("heatmap"),
            "clear_layers": pending.get("clear_layers", False),
            "qa_warnings": pending.get("qa_warnings", []),
        }
    finally:
        try:
            from backend.services.tools import set_current_run as _scr, set_current_task as _sct
            _scr("")
            _sct("")
        except Exception:
            pass
        release_shared_state_lock()


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


@app.get("/api/storage/stats")
async def get_storage_stats():
    """获取本地 SQLite 数据库与存储状态（供设置面板查看与检查）"""
    from backend.services import storage_service
    return storage_service.get_db_stats()


# ===== 前端静态文件（必须放在所有 /api 路由之后，否则 catch-all 会遮蔽 API） =====
# 自定义 StaticFiles：响应加 Cache-Control: no-cache，保证改前端后浏览器拿到最新资源（避免强刷）
from starlette.responses import Response

class _NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

# ===== cache 静态文件（图表/导出文件，必须在 / 之前挂载）=====
_cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
os.makedirs(_cache_dir, exist_ok=True)
os.makedirs(os.path.join(_cache_dir, "charts"), exist_ok=True)
app.mount("/cache", StaticFiles(directory=_cache_dir), name="cache")

_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/", _NoCacheStaticFiles(directory=_frontend_dir, html=True), name="frontend")
