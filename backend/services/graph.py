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
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from backend.services.tools import tools, reset_state, get_pending_state
import backend.services.ai_service as _ai_svc


# ============================================================
# 构建 LLM
# ============================================================

def build_llm(api_key: str, provider: str) -> ChatOpenAI:
    """根据 provider 构建对应的 ChatOpenAI 实例"""
    if provider in ("glm", "glm-routed"):
        return ChatOpenAI(
            model="glm-4.7-flash",
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            temperature=0.7,
        )
    elif provider == "agnes":
        return ChatOpenAI(
            model="agnes-2.0-flash",
            api_key=api_key,
            base_url="https://apihub.agnes-ai.com/v1",
            temperature=0.7,
            max_tokens=4096,
            timeout=60,
        )
    else:
        return ChatOpenAI(
            model="deepseek-chat",
            api_key=api_key,
            base_url="https://api.deepseek.com",
            temperature=0.7,
            max_tokens=2048,
        )


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

def run_agent(
    messages: list,
    api_key: str,
    provider: str,
    amap_key: str = "",
    skill_text: str = "",
    original_message: str = "",
) -> dict:
    """运行 LangGraph Agent + 自校验

    用 create_react_agent 替换原来的 while/if 手写循环。
    Agent 自动管理：LLM 调用 → 工具调用 → 结果观察 → 继续工具调用 → ... → 文本回复

    Args:
        messages: LangChain BaseMessage 列表（SystemMessage + HumanMessage）
        api_key: LLM API Key
        provider: 模型提供商
        amap_key: 高德地图 API Key
        skill_text: 技能文档
        original_message: 用户原始请求（用于校验）

    Returns:
        {
            "response": str,          # AI 最终回复
            "layers": [...],          # 待加载到地图的 GeoJSON 图层
            "images": [...],          # 生成的图表
            "heatmap": {...} | None,  # 热力图数据
            "clear_layers": bool,     # 是否清空地图
            "pending_suggestions": {...} | None,  # AOI 候选
        }
    """
    # 重置共享状态（tools.py 中的全局变量）
    reset_state(amap_key)

    # 构建 LLM
    llm = build_llm(api_key, provider)

    # 简单文本对话（无关键词）直接调 LLM，不走 LangGraph 省掉框架开销
    _simple = True
    if messages and len(messages) > 1:
        _last = messages[-1].content if hasattr(messages[-1], 'content') else str(messages[-1])
        _need_tools = any(kw in _last for kw in ['搜索','搜','查','画','图','分析','加载','地图','生成','计算','执行','边界','提取','POI','AOI','热力','标记','导出','下载','求','多少','什么','哪','?','？'])
        if _need_tools or len(_last) > 80:
            _simple = False
    if _simple:
        if _ai_svc._request_cancelled:
            return {"response": "用户已取消", "layers": [], "images": [],
                    "heatmap": None, "clear_layers": False, "layer_ops": [],
                    "pending_suggestions": None}
        try:
            _resp = llm.invoke(messages)
            return {
                "response": _resp.content,
                "layers": [], "images": [], "heatmap": None,
                "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
            }
        except Exception as e:
            return {"response": f"AI 回复失败: {str(e)[:200]}",
                "layers": [], "images": [], "heatmap": None,
                "clear_layers": False, "layer_ops": [], "pending_suggestions": None}

    # 构建 LangGraph ReAct Agent
    agent = create_react_agent(llm, tools)

    # 运行 Agent
    try:
        if _ai_svc._request_cancelled:
            return {"response": "用户已取消", "layers": [], "images": [],
                    "heatmap": None, "clear_layers": False, "layer_ops": [],
                    "pending_suggestions": None}
        result = agent.invoke(
            {"messages": messages},
            {"recursion_limit": 120},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        if "recursion_limit" in error_msg or "RecursionError" in error_msg:
            friendly = "AI 在处理复杂任务时超限。已优化限制，请重试。如仍有问题，请简化请求描述。"
            print(f"[GIS] 递归超限: {error_msg}", flush=True)
        else:
            friendly = f"AI 服务调用失败: {error_msg}"
        return {
            "response": friendly,
            "layers": [],
            "images": [],
            "heatmap": None,
            "clear_layers": False,
            "layer_ops": [],
            "pending_suggestions": None,
        }

    # 提取最终回复
    final_messages = result.get("messages", [])
    final_text = ""
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage) and msg.content:
            final_text = msg.content
            break

    # 收集本轮产生的共享状态
    pending = get_pending_state()

    # === 自校验：Agent 2 验证 ===
    if original_message and len(original_message) > 3:
        verdict = _run_verifier(llm, original_message, final_text, pending)
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
                for msg in reversed(corr_msgs):
                    if isinstance(msg, AIMessage) and msg.content:
                        final_text = msg.content
                        break
                # 合并修正中产生的新图层/图片
                corr_pending = get_pending_state()
                for key in ("layers", "images", "layer_ops"):
                    if corr_pending.get(key):
                        pending[key].extend(corr_pending[key])
                print(f"[GIS] 修正完成", flush=True)
            except Exception as fix_err:
                print(f"[GIS] 修正尝试失败，使用原结果: {fix_err}", flush=True)

    return {
        "response": final_text,
        "layers": pending["layers"],
        "images": pending["images"],
        "heatmap": pending["heatmap"],
        "clear_layers": pending["clear_layers"],
        "layer_ops": pending["layer_ops"],
        "pending_suggestions": (pending["aoi_suggestions"] or {}).get("suggestions"),
    }


# ============================================================
# Agent 流式执行（SSE 实时进度）
# ============================================================

# _cached_graph 在模块顶部已初始化

def run_agent_stream(
    messages: list,
    api_key: str,
    provider: str,
    amap_key: str = "",
    skill_text: str = "",
    original_message: str = "",
):
    """运行 Agent 并逐步 yield 事件（供 SSE 端点使用）

    Yields:
        JSON 字符串，每行一条事件：
        {"type":"tool_start","name":"search_web","input":"..."}
        {"type":"tool_end","name":"search_web","output":"..."}
        {"type":"thinking"}
        {"type":"done","response":"...","layers":[...],...}
    """
    reset_state(amap_key)
    # 重置取消标志（每次新请求开始）
    import backend.services.ai_service as _ai_svc
    _ai_svc._request_cancelled = False
    llm = build_llm(api_key, provider)

    # 简单问题快速 bypass
    _simple = True
    if messages and len(messages) > 1:
        _last = messages[-1].content if hasattr(messages[-1], 'content') else str(messages[-1])
        _need_tools = any(kw in _last for kw in ['搜索','搜','查','画','图','分析','加载','地图','生成','计算','执行','边界','提取','POI','AOI','热力','标记','导出','下载','求','多少','什么','哪','?','？'])
        if _need_tools or len(_last) > 80:
            _simple = False
    if _simple:
        _resp = llm.invoke(messages)
        yield f"data: {{\"type\":\"thinking\"}}\n\n"
        yield f"data: {{\"type\":\"done\",\"response\":{json.dumps(_resp.content, ensure_ascii=False)},\"layers\":[],\"images\":[],\"heatmap\":null,\"clear_layers\":false,\"layer_ops\":[],\"pending_suggestions\":null}}\n\n"
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
        event = json.dumps({"type": "error", "message": str(e)})
        yield f"data: {event}\n\n"

    # 收集最终结果
    pending = get_pending_state()
    final_text = ""
    try:
        for msg in reversed(msgs):
            if isinstance(msg, AIMessage) and msg.content:
                final_text = msg.content
                break
    except Exception:
        pass

    # === 自校验（流式模式也做，只做一轮修正，防止延迟过长） ===
    if original_message and len(original_message) > 3:
        yield "data: {\"type\":\"verifying\"}\n\n"
        verdict = _run_verifier(llm, original_message, final_text, pending)
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
                for msg in reversed(corr_msgs):
                    if isinstance(msg, AIMessage) and msg.content:
                        final_text = msg.content
                        break
                corr_pending = get_pending_state()
                for key in ("layers", "images", "layer_ops"):
                    if corr_pending.get(key):
                        pending[key].extend(corr_pending[key])
            except Exception as fix_err:
                print(f"[GIS] 流式修正失败，使用原结果: {fix_err}", flush=True)

    result = {
        "response": final_text,
        "layers": pending["layers"],
        "images": pending["images"],
        "heatmap": pending["heatmap"],
        "clear_layers": pending["clear_layers"],
        "layer_ops": pending["layer_ops"],
        "pending_suggestions": (pending["aoi_suggestions"] or {}).get("suggestions"),
    }
    yield f"data: {json.dumps({'type': 'done', **result}, ensure_ascii=False)}\n\n"
