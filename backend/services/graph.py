"""
GIS WorkTable — LangGraph Agent 工作流

用 LangGraph 替换原来的手写 while/if 工具调用循环。

原来（ai_service.py）:
    while True:
        response = client.chat.completions.create(messages, tools)
        if tool_calls:
            for tc in tool_calls:
                if tc.name == "search_web": ...
                elif tc.name == "execute_python": ...
                # ... 15+ elif
        else:
            return response.text

现在（LangGraph Agent）:
    agent = create_react_agent(llm, tools)
    result = agent.invoke({"messages": messages})

LangGraph 自动管理:
    - LLM 判断是否需要调工具
    - ToolNode 自动路由到对应工具（不需要手动 if/elif）
    - 循环直到 AI 决定回复文本
    - 状态在 MessagesState 中自动维护

FC vs LangGraph 对比:
    ┌──────────────────────┬──────────────────────────────┐
    │ 手写 FC (Function Calling) │ LangGraph Agent            │
    ├──────────────────────┼──────────────────────────────┤
    │ while True + if/elif │ 框架自动管理循环               │
    │ 手动路由 15+ 工具     │ ToolNode 自动路由              │
    │ 状态靠全局变量"记住"  │ 状态在 graph 中显式维护         │
    │ 50 轮手写上限         │ recursion_limit 参数控制        │
    │ 无条件分支           │ 支持条件边 / 并行 / 子图        │
    │ 每次都要读所有 elif   │ 框架编译后高效执行              │
    └──────────────────────┴──────────────────────────────┘
"""

from typing import Any
import json
import re

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from backend.services.llm_config import (
    LLMConfig,
    build_llm,
    disable_reasoning,
    get_message_reasoning,
)
from backend.services.tools import tools, reset_state, get_pending_state, set_current_task
from backend.services import pending_action
import backend.services.tools as _tools_mod
import backend.services.ai_service as _ai_svc
from backend.services import task_manager


# ============================================================
# 自校验 Verifier Agent（Agent 2）
# ============================================================

_VERIFIER_SYSTEM_PROMPT = """你是一个 GIS 结果验证专家。判断以下 Agent 输出是否满足用户请求。

规则：
1. 输出结果是否直接回应用户的问题？如果不相关，判定不通过。
2. 如果用户要求加载地图数据/生成图层，是否有对应的 GeoJSON/图层生成？
3. 如果用户要求画图/图表，是否有图表文件生成？
4. 如果用户要求分析数据，回复中是否包含分析结论？
5. 输出的文字是否存在明显的错误或矛盾？

注意：你只关注"用户的请求是否被满足"，不关注代码实现细节。
如果结果是合理的，即使不完美也判定通过。

只需输出一行 JSON（不要其他文字）：
{"pass": true/false, "reason": "一句话原因"}

示例：
{"pass": true, "reason": "成功获取广州市边界并加载到地图"}
{"pass": false, "reason": "用户要求生成热力图，但输出中只有边界数据，没有热力图"}"""


def _run_verifier(llm: ChatOpenAI, original_message: str, response: str, pending: dict) -> dict:
    """执行校验，返回 {"pass": bool, "reason": str}"""
    has_gis_result = bool(
        pending.get("layers") or
        pending.get("images") or
        pending.get("heatmap") or
        pending.get("clear_layers") or
        pending.get("layer_ops")
    )
    # 纯文本对话，不需要校验
    if not has_gis_result and len(response) < 100:
        return {"pass": True, "reason": "简单文本回答，跳过校验"}

    # 构造工具使用摘要
    summary_parts = []
    if pending.get("layers"):
        layer_names = [l.get("name", "未命名") for l in pending["layers"]]
        summary_parts.append(f"生成了 {len(pending['layers'])} 个图层：{', '.join(layer_names[:3])}")
    if pending.get("images"):
        summary_parts.append(f"生成了 {len(pending['images'])} 个图表/文件")
    if pending.get("heatmap"):
        summary_parts.append("生成了热力图")
    if pending.get("clear_layers"):
        summary_parts.append("清空了地图图层")
    if pending.get("layer_ops"):
        summary_parts.append(f"执行了 {len(pending['layer_ops'])} 个图层操作")
    tool_summary = "；".join(summary_parts) if summary_parts else "无 GIS 操作"

    try:
        verifier_messages = [
            SystemMessage(content=_VERIFIER_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"用户请求：{original_message}\n\n"
                    f"Agent 操作摘要：{tool_summary}\n\n"
                    f"Agent 文字回复：{response[:2000]}"
                )
            ),
        ]
        result = llm.invoke(verifier_messages, max_tokens=200)
        text = result.content.strip()

        # 尝试解析 JSON
        if text.startswith("{"):
            parsed = json.loads(text)
            return {"pass": bool(parsed.get("pass", True)), "reason": str(parsed.get("reason", ""))}

        # fallback：正则提取
        m = re.search(r'["\']?pass["\']?\s*:\s*(true|false)', text, re.IGNORECASE)
        if m:
            return {"pass": m.group(1).lower() == "true", "reason": text[:100]}
        return {"pass": True, "reason": "无法解析校验结果，默认通过"}
    except Exception as e:
        print(f"[GIS] Verifier 异常（不影响主流程）: {e}", flush=True)
        return {"pass": True, "reason": f"校验异常，默认通过"}


# ============================================================
# 运行 Agent（核心入口）
# ============================================================

def _last_ai_text(msgs: list):
    """返回 (最后一条非空 AI 文本, 它的 reasoning/None)"""
    for msg in reversed(msgs):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content, get_message_reasoning(msg)
    return "", None


def _tool_not_callable(e: Exception) -> bool:
    """识别 LangChain 框架角例：'StructuredTool' object is not callable。"""
    return isinstance(e, TypeError) and "callable" in str(e)


_PROMISE_PREFIXES = (
    "好的", "好", "行", "可以", "没问题", "稍等", "马上",
    "我这就", "我现在", "我先", "让我", "我来", "这就去",
    "现在开始", "好嘞",
)
_PROMISE_VERBS = re.compile(
    r"(获取|下载|加载|搜索|查找|抓取|截取|提取|分析|计算|生成|绘制|采集|整理|统计|构建|创建|调用|做一下|找一下)"
)


def _looks_like_incomplete_promise(text) -> bool:
    """识别「AI 说开始做但实际没做」的结尾：以应允/开场白开头、带动作词、且文本很短。

    这类结尾典型形态：“好的，我现在开始获取法国边界数据”。若本轮没执行任何工具，
    说明它只承诺未交付（常见于低价模型只叙事不调工具）。
    """
    if not text:
        return False
    t = (text or "").strip()
    if len(t) > 600:
        return False
    if not t.startswith(_PROMISE_PREFIXES):
        return False
    return bool(_PROMISE_VERBS.search(t))


def _promise_without_action(text, msgs) -> bool:
    """最终回复是"承诺式开头"且本轮没有任何工具消息 → 判定为只承诺未执行。"""
    if not _looks_like_incomplete_promise(text):
        return False
    return not any(isinstance(m, ToolMessage) for m in (msgs or []))


def _count_tool_calls(msgs: list) -> int:
    """统计消息列表中实际的工具调用次数"""
    count = 0
    for m in (msgs or []):
        if isinstance(m, AIMessage) and hasattr(m, 'tool_calls') and m.tool_calls:
            count += len(m.tool_calls)
    return count


def _has_tool_messages(msgs: list) -> bool:
    """检查消息列表中是否有工具返回结果"""
    return any(isinstance(m, ToolMessage) for m in (msgs or []))


def _auto_promote_pending(session_id: str, start_registered: set, pushed_names: list):
    """一轮 Agent 结束：把「新注册但未推送到地图」的图层挂起为 pending load_layer。

    用户下一条“继续/确认/执行”会确定性加载；“取消”会清除。不打扰已展示的图层。
    """
    try:
        pending_action.promote_registered_undisplayed(
            session_id, start_registered, pushed_names)
    except Exception as _e:  # 永不因挂起失败破坏主流程
        print(f"[GIS] auto-promote pending 失败（忽略）: {_e}", flush=True)


def run_agent(
    messages: list,
    cfg: LLMConfig,
    amap_key: str = "",
    skill_text: str = "",
    original_message: str = "",
    session_id: str = "default",
) -> dict:
    """运行 LangGraph Agent + 自校验

    用 create_react_agent 替换原来的 while/if 手写循环。
    Agent 自动管理：LLM 调用 → 工具调用 → 结果观察 → 继续工具调用 → ... → 文本回复

    Args:
        messages: LangChain BaseMessage 列表（SystemMessage + HumanMessage）
        cfg: LLMConfig，构造所用模型（glm_prompt/router/reasoning 均由此决定）
        amap_key: 高德地图 API Key
        skill_text: 技能文档
        original_message: 用户原始请求（用于校验）
        session_id: 会话 ID（用于跨轮 pending task 自动挂起）

    Returns:
        {
            "response": str,          # AI 最终回复
            "reasoning": str|None,    # 思考过程（reasoning 开启时有，供前端折叠展示）
            "layers": [...],          # 待加载到地图的 GeoJSON 图层
            "images": [...],          # 生成的图表
            "heatmap": {...} | None,  # 热力图数据
            "clear_layers": bool,     # 是否清空地图
            "pending_suggestions": {...} | None,  # AOI 候选
        }
    """
    # 重置共享状态（tools.py 中的全局变量）
    reset_state(amap_key)
    # 绑定本请求会话（hold 等工具写 pending 用）
    pending_action.set_active_session(session_id or "default")
    _start_registered = set(getattr(_tools_mod, "_registered_layers", {}).keys())

    # === Task Manager: 解析/创建任务，绑定到 tools ===
    _task_id = task_manager.find_or_create_task(session_id or "default", original_message or "")
    set_current_task(_task_id)
    print(f"[GIS] Task ID: {_task_id}", flush=True)

    # 构建 LLM
    llm = build_llm(cfg)

    # 简单文本对话（无关键词）直接调 LLM，不走 LangGraph 省掉框架开销
    _simple = True
    if messages and len(messages) > 1:
        _last = messages[-1].content if hasattr(messages[-1], 'content') else str(messages[-1])
        _need_tools = any(kw in _last for kw in ['搜索','搜','查','画','图','分析','加载','地图','生成','计算','执行','边界','提取','POI','AOI','热力','标记','导出','下载','找','获取','道路','建筑','水系','影像','遥感','DEM','要素','求','多少','什么','哪','?','？','继续','确认','取消','接着'])
        if _need_tools or len(_last) > 80:
            _simple = False
    if _simple:
        if _ai_svc._request_cancelled:
            return {"response": "用户已取消", "reasoning": None, "layers": [], "images": [],
                    "heatmap": None, "clear_layers": False, "layer_ops": [],
                    "pending_suggestions": None}
        try:
            _resp = llm.invoke(messages)
            return {
                "response": _resp.content,
                "reasoning": get_message_reasoning(_resp),
                "layers": [], "images": [], "heatmap": None,
                "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
            }
        except Exception as e:
            return {"response": f"AI 回复失败: {str(e)[:200]}", "reasoning": None,
                "layers": [], "images": [], "heatmap": None,
                "clear_layers": False, "layer_ops": [], "pending_suggestions": None}

    # 构建 LangGraph ReAct Agent
    agent = create_react_agent(llm, tools)

    # 运行 Agent
    # 框架角例：langchain 1.x 下 @tool 返回 StructuredTool（无 __call__），reasoning 模型
    # 在长工具链末尾偶发把工具对象当普通函数调用 → TypeError "'StructuredTool' object is not callable"。
    # 处理：自动降级重试一次（追加“请纯文本收尾，不再调工具”），有界且保留已产出图层/数据。
    result = None
    _msgs = list(messages)
    for _attempt in range(2):
        try:
            if _ai_svc._request_cancelled:
                return {"response": "用户已取消", "reasoning": None, "layers": [], "images": [],
                        "heatmap": None, "clear_layers": False, "layer_ops": [],
                        "pending_suggestions": None}
            result = agent.invoke(
                {"messages": _msgs},
                {"recursion_limit": 120},
            )
            break
        except Exception as e:
            import traceback
            traceback.print_exc()
            if _attempt == 0 and _tool_not_callable(e):
                print("[GIS] 工具调度 TypeError，自动纯文本收尾重试一次", flush=True)
                _msgs = list(messages) + [HumanMessage(
                    content="请停止调用任何工具，直接用文字总结最终结果（可引用前面已经完成的数据/图层）。")]
                continue
            error_msg = str(e)
            if "recursion_limit" in error_msg or "RecursionError" in error_msg:
                friendly = "AI 在处理复杂任务时超限。已优化限制，请重试。如仍有问题，请简化请求描述。"
                print(f"[GIS] 递归超限: {error_msg}", flush=True)
            else:
                friendly = f"AI 服务调用失败: {error_msg}"
            return {
                "response": friendly, "reasoning": None,
                "layers": [],
                "images": [],
                "heatmap": None,
                "clear_layers": False,
                "layer_ops": [],
                "pending_suggestions": None,
            }

    # 提取最终回复
    final_messages = result.get("messages", [])
    final_text, final_reasoning = _last_ai_text(final_messages)

    # 收集本轮产生的共享状态
    pending = get_pending_state()

    # === 防“只说开始就结束”：只承诺未执行（无任何工具调用）时强制补一轮真实执行 ===
    _initial_tool_calls = _count_tool_calls(final_messages)
    _initial_has_tools = _has_tool_messages(final_messages)
    print(f"[GIS DEBUG] 初始工具调用: {_initial_tool_calls} 次, 有工具消息: {_initial_has_tools}", flush=True)
    
    if _promise_without_action(final_text, final_messages):
        try:
            print("[GIS] 只承诺未执行，强制补一轮真实工具执行", flush=True)
            _forced = agent.invoke(
                {"messages": list(final_messages) + [HumanMessage(
                    content="你刚才只是说“开始执行”，但实际没有调用任何工具。"
                            "请现在就调用合适工具真正完成你承诺的任务，不要再只做口头承诺。")]},
                {"recursion_limit": 60},
            )
            _fm = _forced.get("messages", [])
            if _fm:
                # 检查强制执行是否真的调用了工具
                _forced_tool_calls = _count_tool_calls(_fm)
                _forced_has_tools = _has_tool_messages(_fm)
                print(f"[GIS DEBUG] 强制执行后工具调用: {_forced_tool_calls} 次, 有工具消息: {_forced_has_tools}", flush=True)
                
                # 只有当强制执行确实调用了工具时才更新结果
                if _forced_has_tools or _forced_tool_calls > 0:
                    final_messages = _fm
                    final_text, final_reasoning = _last_ai_text(_fm)
                    _extra = get_pending_state()
                    for _k in ("layers", "images", "layer_ops"):
                        if _extra.get(_k):
                            pending[_k].extend(_extra[_k])
                    print("[GIS] 强制执行成功，已更新结果", flush=True)
                else:
                    print("[GIS] 强制执行仍然没有调用工具，模型可能不支持tool calling", flush=True)
                    # 追加提示信息
                    final_text = final_text + "\n\n【注意】当前AI模型可能不支持工具调用，无法自动执行操作。请尝试更换支持tool calling的模型（如GPT-4、DeepSeek等）。"
        except Exception as _pe:
            print(f"[GIS] 强制补执行失败（保留原结果）: {_pe}", flush=True)

    # === 自校验：Agent 2 验证 ===
    # Verifier 复用同一份 cfg，但强制关 reasoning，保证吐纯 JSON
    if original_message and len(original_message) > 3:
        verdict = _run_verifier(build_llm(disable_reasoning(cfg)), original_message, final_text, pending)
        if not verdict.get("pass", True):
            reason = verdict.get("reason", "未知原因")
            print(f"[GIS] 自校验未通过，启动修正: {reason}", flush=True)
            # 修正：追加一条 HumanMessage，让 Agent 1 修正结果
            try:
                fix_msg = HumanMessage(
                    content=(
                        f"你上一轮的结果未通过质量检查。\n"
                        f"问题：{reason}\n"
                        f"请针对上述问题，在现有结果基础上修复后重新输出。"
                        f"不要从头开始，只修正问题所在。"
                    )
                )
                corrected = agent.invoke(
                    {"messages": final_messages + [fix_msg]},
                    {"recursion_limit": 40},
                )
                corr_msgs = corrected.get("messages", [])
                final_text, final_reasoning = _last_ai_text(corr_msgs)
                # 合并修正中产生的新图层/图片
                corr_pending = get_pending_state()
                for key in ("layers", "images", "layer_ops"):
                    if corr_pending.get(key):
                        pending[key].extend(corr_pending[key])
                print(f"[GIS] 修正完成", flush=True)
            except Exception as fix_err:
                print(f"[GIS] 修正尝试失败，使用原结果: {fix_err}", flush=True)

    # 一轮结束：新注册但未展示的图层 → 挂起为 pending（用户“继续/确认”即加载）
    _auto_promote_pending(
        session_id, _start_registered, [l.get("name") for l in pending.get("layers", [])]
    )

    return {
        "response": final_text,
        "reasoning": final_reasoning,
        "layers": pending["layers"],
        "images": pending["images"],
        "heatmap": pending["heatmap"],
        "clear_layers": pending["clear_layers"],
        "layer_ops": pending["layer_ops"],
        "pending_suggestions": (pending["aoi_suggestions"] or {}).get("suggestions"),
        "task_id": _task_id,
    }


# ============================================================
# Agent 流式执行（SSE 实时进度）
# ============================================================

# _cached_graph 在模块顶部已初始化

def run_agent_stream(
    messages: list,
    cfg: LLMConfig,
    amap_key: str = "",
    skill_text: str = "",
    original_message: str = "",
    session_id: str = "default",
):
    """运行 Agent 并逐步 yield 事件（供 SSE 端点使用）

    Args:
        messages: LangChain BaseMessage 列表
        cfg: LLMConfig，构造所用模型
        session_id: 会话 ID（用于跨轮 pending task 自动挂起）

    Yields:
        JSON 字符串，每行一条事件：
        {"type":"tool_start","name":"search_web","input":"..."}
        {"type":"tool_end","name":"search_web","output":"..."}
        {"type":"thinking"}
        {"type":"done","response":"...","reasoning":...,"layers":[...],...}
    """
    reset_state(amap_key)
    pending_action.set_active_session(session_id or "default")
    _start_registered = set(getattr(_tools_mod, "_registered_layers", {}).keys())
    # 重置取消标志（每次新请求开始）
    import backend.services.ai_service as _ai_svc
    _ai_svc._request_cancelled = False
    llm = build_llm(cfg)

    # === Task Manager: 解析/创建任务，绑定到 tools ===
    _task_id = task_manager.find_or_create_task(session_id or "default", original_message or "")
    set_current_task(_task_id)
    print(f"[GIS] 流式 Task ID: {_task_id}", flush=True)

    # 简单问题快速 bypass
    _simple = True
    if messages and len(messages) > 1:
        _last = messages[-1].content if hasattr(messages[-1], 'content') else str(messages[-1])
        _need_tools = any(kw in _last for kw in ['搜索','搜','查','画','图','分析','加载','地图','生成','计算','执行','边界','提取','POI','AOI','热力','标记','导出','下载','找','获取','道路','建筑','水系','影像','遥感','DEM','要素','求','多少','什么','哪','?','？','继续','确认','取消','接着'])
        if _need_tools or len(_last) > 80:
            _simple = False
    if _simple:
        _resp = llm.invoke(messages)
        yield f"data: {{\"type\":\"thinking\"}}\n\n"
        result = {
            "response": _resp.content,
            "reasoning": get_message_reasoning(_resp),
            "layers": [], "images": [], "heatmap": None,
            "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
        }
        yield f"data: {json.dumps({'type': 'done', **result}, ensure_ascii=False)}\n\n"
        return

    agent = create_react_agent(llm, tools)

    global _cached_graph
    _cached_graph = agent

    try:
        msgs = []  # 初始化，防止空流时 verifier 引用未定义变量
        for step in agent.stream(
            {"messages": messages},
            {"recursion_limit": 120},
            stream_mode="values",
        ):
            # 每次循环检查是否被取消
            if _ai_svc._request_cancelled:
                yield f"data: {json.dumps({'type': 'cancelled', 'message': '用户取消了请求'})}\n\n"
                return

            msgs = step.get("messages", [])
            if not msgs:
                continue
            last = msgs[-1]

            # DEBUG: 打印最后一条消息的类型和内容
            _debug_msg_type = type(last).__name__
            _debug_has_tool_calls = hasattr(last, 'tool_calls') and bool(getattr(last, 'tool_calls', None))
            _debug_content_preview = str(getattr(last, 'content', ''))[:100] if hasattr(last, 'content') else 'N/A'
            print(f"[GIS DEBUG] Step msg: type={_debug_msg_type}, has_tool_calls={_debug_has_tool_calls}, content={_debug_content_preview}", flush=True)

            # AI 调用了工具
            if isinstance(last, AIMessage) and last.tool_calls:
                for tc in last.tool_calls:
                    event = json.dumps({
                        "type": "tool_start",
                        "name": tc.get("name", "?"),
                        "input": str(tc.get("args", {}))[:300],
                    }, ensure_ascii=False)
                    yield f"data: {event}\n\n"

            # 工具返回结果
            elif hasattr(last, "name") and last.name and hasattr(last, "content"):
                event = json.dumps({
                    "type": "tool_end",
                    "name": last.name,
                    "output": str(last.content)[:300],
                }, ensure_ascii=False)
                yield f"data: {event}\n\n"

            # AI 正在思考（没有 tool_calls）
            elif isinstance(last, AIMessage) and last.content:
                yield "data: {\"type\":\"thinking\"}\n\n"

    except Exception as e:
        import traceback
        traceback.print_exc()
        # 框架角例容错：StructuredTool 被当普通函数调用的偶发 TypeError →
        # 自动“纯文本收尾”一次（保留前面已产出的图层），尽量不让整轮失败。
        if _tool_not_callable(e):
            try:
                fb_llm = build_llm(disable_reasoning(cfg))
                _fb = fb_llm.invoke(
                    list(messages) + [HumanMessage(
                        content="请停止调用任何工具，直接用文字总结最终结果"
                                "（可引用前面已经完成的数据/图层）。")],
                    max_tokens=800,
                )
                _fb_text = (_fb.content or "").strip()
            except Exception:
                _fb_text = ""
            if _fb_text:
                print("[GIS] 工具调度 TypeError，流式纯文本收尾", flush=True)
                msgs.append(AIMessage(content=_fb_text))
            else:
                event = json.dumps({"type": "error", "message": str(e)})
                yield f"data: {event}\n\n"
        else:
            event = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {event}\n\n"

    # 收集最终结果
    pending = get_pending_state()
    final_text, final_reasoning = "", None
    try:
        final_text, final_reasoning = _last_ai_text(msgs)
    except Exception:
        pass

    # === 防“只说开始就结束”：只承诺未执行（无任何工具调用）时强制补一轮真实执行 ===
    _initial_tool_calls = _count_tool_calls(msgs)
    _initial_has_tools = _has_tool_messages(msgs)
    print(f"[GIS DEBUG] 流式初始工具调用: {_initial_tool_calls} 次, 有工具消息: {_initial_has_tools}", flush=True)
    
    if _promise_without_action(final_text, msgs):
        try:
            print("[GIS] 流式：只承诺未执行，强制补一轮真实工具执行", flush=True)
            yield "data: {\"type\":\"thinking\"}\n\n"
            _forced = agent.invoke(
                {"messages": list(msgs) + [HumanMessage(
                    content="你刚才只是说“开始执行”，但实际没有调用任何工具。"
                            "请现在就调用合适工具真正完成你承诺的任务，不要再只做口头承诺。")]},
                {"recursion_limit": 60},
            )
            _fm = _forced.get("messages", [])
            if _fm:
                # 检查强制执行是否真的调用了工具
                _forced_tool_calls = _count_tool_calls(_fm)
                _forced_has_tools = _has_tool_messages(_fm)
                print(f"[GIS DEBUG] 流式强制执行后工具调用: {_forced_tool_calls} 次, 有工具消息: {_forced_has_tools}", flush=True)
                
                # 只有当强制执行确实调用了工具时才更新结果
                if _forced_has_tools or _forced_tool_calls > 0:
                    msgs = _fm
                    final_text, final_reasoning = _last_ai_text(_fm)
                    _extra = get_pending_state()
                    for _k in ("layers", "images", "layer_ops"):
                        if _extra.get(_k):
                            pending[_k].extend(_extra[_k])
                    print("[GIS] 流式强制执行成功，已更新结果", flush=True)
                else:
                    print("[GIS] 流式强制执行仍然没有调用工具，模型可能不支持tool calling", flush=True)
                    # 追加提示信息
                    final_text = final_text + "\n\n【注意】当前AI模型可能不支持工具调用，无法自动执行操作。请尝试更换支持tool calling的模型（如GPT-4、DeepSeek等）。"
        except Exception as _pe:
            print(f"[GIS] 流式强制补执行失败（保留原结果）: {_pe}", flush=True)

    # === 自校验（流式模式也做，只做一轮修正，防止延迟过长） ===
    if original_message and len(original_message) > 3:
        yield "data: {\"type\":\"verifying\"}\n\n"
        verdict = _run_verifier(build_llm(disable_reasoning(cfg)), original_message, final_text, pending)
        if not verdict.get("pass", True):
            reason = verdict.get("reason", "未知原因")
            print(f"[GIS] 流式自校验未通过，启动修正: {reason}", flush=True)
            try:
                fix_msg = HumanMessage(
                    content=(
                        f"你上一轮的结果未通过质量检查。\n"
                        f"问题：{reason}\n"
                        f"请在现有结果基础上修复后重新输出，不要从头开始。"
                    )
                )
                corrected = agent.invoke(
                    {"messages": msgs + [fix_msg]},
                    {"recursion_limit": 40},
                )
                corr_msgs = corrected.get("messages", [])
                final_text, final_reasoning = _last_ai_text(corr_msgs)
                corr_pending = get_pending_state()
                for key in ("layers", "images", "layer_ops"):
                    if corr_pending.get(key):
                        pending[key].extend(corr_pending[key])
            except Exception as fix_err:
                print(f"[GIS] 流式修正失败，使用原结果: {fix_err}", flush=True)

    # 一轮结束：新注册但未展示的图层 → 挂起为 pending（用户“继续/确认”即加载）
    _auto_promote_pending(
        session_id, _start_registered, [l.get("name") for l in pending.get("layers", [])]
    )

    result = {
        "response": final_text,
        "reasoning": final_reasoning,
        "layers": pending["layers"],
        "images": pending["images"],
        "heatmap": pending["heatmap"],
        "clear_layers": pending["clear_layers"],
        "layer_ops": pending["layer_ops"],
        "pending_suggestions": (pending["aoi_suggestions"] or {}).get("suggestions"),
        # 存在待确认动作时前端渲染「继续/取消」按钮（免手打）
        "confirm_pending": pending_action.describe_action(
            pending_action.get_pending_action(session_id)),
        "task_id": _task_id,
    }
    yield f"data: {json.dumps({'type': 'done', **result}, ensure_ascii=False)}\n\n"
