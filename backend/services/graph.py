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

from typing import Any, Literal

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, END, MessagesState
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent, ToolNode

from backend.services.tools import tools, reset_state, get_pending_state


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
    else:
        return ChatOpenAI(
            model="deepseek-chat",
            api_key=api_key,
            base_url="https://api.deepseek.com",
            temperature=0.7,
            max_tokens=2048,
        )


# ============================================================
# 运行 Agent（核心入口）
# ============================================================

def run_agent(
    messages: list,
    api_key: str,
    provider: str,
    amap_key: str = "",
    skill_text: str = "",
) -> dict:
    """运行 LangGraph Agent

    用 create_react_agent 替换原来的 while/if 手写循环。
    Agent 自动管理：LLM 调用 → 工具调用 → 结果观察 → 继续工具调用 → ... → 文本回复

    Args:
        messages: LangChain BaseMessage 列表（SystemMessage + HumanMessage）
        api_key: LLM API Key
        provider: 模型提供商
        amap_key: 高德地图 API Key
        skill_text: 技能文档

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

    # 构建 LangGraph ReAct Agent
    # create_react_agent 内部使用 ToolNode，自动管理：
    #   1. LLM 判断是否有 tool_calls
    #   2. 有 → ToolNode 执行 → 结果返回给 LLM → 回到 1
    #   3. 无 → 返回文本 → 结束
    agent = create_react_agent(llm, tools)

    # 运行 Agent
    try:
        result = agent.invoke(
            {"messages": messages},
            {"recursion_limit": 50},  # 安全限制，防止死循环
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "response": f"AI 服务调用失败: {str(e)}",
            "layers": [],
            "images": [],
            "heatmap": None,
            "clear_layers": False,
            "pending_suggestions": None,
        }

    # 提取最终回复（最后一个 AIMessage 的 content）
    final_messages = result.get("messages", [])
    final_text = ""
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage) and msg.content:
            final_text = msg.content
            break

    # 收集本轮产生的共享状态
    pending = get_pending_state()

    return {
        "response": final_text,
        "layers": pending["layers"],
        "images": pending["images"],
        "heatmap": pending["heatmap"],
        "clear_layers": pending["clear_layers"],
        "pending_suggestions": pending["aoi_suggestions"],
    }
