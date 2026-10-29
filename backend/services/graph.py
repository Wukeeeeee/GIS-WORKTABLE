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

import json
import queue
import re
import threading
import uuid
import time
from contextvars import copy_context
from functools import wraps

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from backend.services.llm_config import (
    LLMConfig,
    build_llm,
    disable_reasoning,
    get_message_reasoning,
)
from backend.services.tools import tools, reset_state, get_pending_state, set_current_task
from backend.services import pending_action
from backend.services import result_guard
import backend.services.tools as _tools_mod
import backend.services.ai_service as _ai_svc
from backend.services import task_manager
from backend.services.token_usage_service import extract_and_record_token_usage
from backend.services.url_security import sanitize_error_text
from langchain_core.utils.function_calling import convert_to_openai_tool


# The map context-menu location analysis is read-only. Keep its capability set
# explicit so the model cannot create/remove layers even if it ignores prompt text.
_READ_ONLY_LOCATION_TOOL_NAMES = frozenset({
    "reverse_geocode",
    "search_web",
    "fetch_weather_data",
})


def _safe_model_error(error, cfg) -> str:
    """Hide the configured model key and access-bearing URLs in provider errors."""
    message = str(error)
    api_key = getattr(cfg, "api_key", "")
    if api_key:
        message = message.replace(str(api_key), "[已隐藏]")
    return sanitize_error_text(message)


def _tools_for_request(read_only_location_analysis: bool = False):
    if not read_only_location_analysis:
        return tools
    return [tool for tool in tools if getattr(tool, "name", "") in _READ_ONLY_LOCATION_TOOL_NAMES]

_PLAIN_CHAT_PATTERN = re.compile(
    r"(?:你好(?:呀|啊|哇)?|您好|嗨|哈喽|hello|hi|hey|早上好|晚上好|"
    r"谢谢(?:你)?|多谢|感谢|好的|好|收到|明白了|再见|拜拜|"
    r"你是谁(?:呀|啊)?|你叫什么(?:名字)?|介绍一下你自己)[\s!！?？。,.，~～]*",
    re.IGNORECASE,
)


def _should_use_agent(messages: list, session_id: str) -> bool:
    """Shared tool-routing decision for streamed and non-streamed requests."""
    if not messages:
        return False
    last = messages[-1]
    content = getattr(last, "content", last if isinstance(last, str) else "")
    if not isinstance(content, str):
        content = str(content or "")
    try:
        has_pending = bool(pending_action.get_pending_action(session_id or "default"))
    except Exception:
        has_pending = False
    # 只有明确的闲聊才能省略工具。任务是否需要工具交给绑定了工具的模型判断，
    # 避免自然表达（如“把两点连上线”）因漏掉关键词而彻底失去工具能力。
    return has_pending or not bool(_PLAIN_CHAT_PATTERN.fullmatch(content.strip()))


# ============================================================
# 运行 Agent（核心入口）
# ============================================================

def _clean_ai_text(text: str) -> str:
    """清理 AI 回复中的工具调用协议文本，避免内部协议泄露给用户。

    委托给 ai_service._strip_protocol_text（逐行状态机，不依赖标签正确配对）。
    """
    try:
        from backend.services.ai_service import _strip_protocol_text
        return _strip_protocol_text(text)
    except Exception:
        if not text:
            return text
        cleaned = re.sub(r'</?[|\s｜]*DSML[|\s｜]*[^>]*>', '', text)
        cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'</?tool_call>', '', cleaned)
        cleaned = re.sub(r'```tool_call.*?```', '', cleaned, flags=re.DOTALL)
        return re.sub(r'\n{3,}', '\n\n', cleaned).strip()


def _last_ai_text(msgs: list):
    """取本轮最后一条 AI 回复，不能把历史回复或早先的计划当成空响应的结果。"""
    for msg in reversed(msgs):
        if isinstance(msg, HumanMessage):
            break
        if isinstance(msg, AIMessage):
            return _clean_ai_text(msg.content or ""), get_message_reasoning(msg)
    return "", None


import time as _time_mod
import concurrent.futures as _cf_mod

_GRAPH_TOTAL_TIMEOUT_S = float(__import__("os").environ.get("GIS_GRAPH_TIMEOUT", "420"))

# ============================================================
# 上下文膨胀兜底（2026-10-15）
# 背景：Agent 多轮循环会把工具输出整段回填上下文，输入 token 可涨到
# 数十万甚至百万级（台账实测 330 万），表现为「说完开始执行就没反应」，
# 直到 420s 时间预算才收尾  期间纯粹在烧 token。
# 这里加三道闸，与时间预算互补：时间闸管墙钟，下面三道管上下文体积。
# 均可用环境变量关闭/调整，默认保守（只截大结果，不丢小结果）。
# ============================================================
# 1) 单条工具输出超过该字符数 -> 截断保留头尾（防止省界/搜索结果整段灌入）
GRAPH_TOOL_OUT_MAX_CHARS = int(__import__('os').environ.get('GIS_TOOL_OUT_MAX', '4000'))
# 2) 消息总字符超过该值 -> 压缩更早的工具消息（保留最近 N 条工具结果原文）
GRAPH_CTX_MAX_CHARS = int(__import__('os').environ.get('GIS_CTX_MAX', '150000'))
GRAPH_CTX_KEEP_TOOLS = int(__import__('os').environ.get('GIS_CTX_KEEP_TOOLS', '4'))
# 3) 累计输入 token 超过该值 -> 提前触发「停止调工具、文字总结」收尾
GRAPH_TOKEN_BUDGET = int(__import__('os').environ.get('GIS_TOKEN_BUDGET', '260000'))


def _trim_text(s: str, limit: int) -> str:
    '''把超长文本截断为 头 + ... + 尾，避免单条结果撑爆上下文'''
    if limit <= 0 or not isinstance(s, str) or len(s) <= limit:
        return s
    head = int(limit * 0.7)
    tail = max(0, limit - head - 60)
    return (s[:head] + '\n...[结果过长已截断 ' + str(len(s) - head - tail) + ' 字符]...\n' + s[len(s) - tail:] if tail else s[:head])


def _compact_messages(msgs: list) -> list:
    '''上下文压缩：把较早的工具结果压成一行摘要，保留最近 K 条原文。'''
    if not msgs:
        return msgs
    try:
        total = sum(len(str(getattr(m, 'content', '') or '')) for m in msgs)
    except Exception:
        return msgs
    if total <= GRAPH_CTX_MAX_CHARS:
        return msgs
    # 找出工具消息下标（ToolMessage 通常带 name/type=tool）
    tool_idx = [i for i, m in enumerate(msgs)
                if getattr(m, 'type', '') == 'tool' or hasattr(m, 'tool_call_id')]
    if len(tool_idx) <= GRAPH_CTX_KEEP_TOOLS:
        return msgs
    keep = set(tool_idx[-GRAPH_CTX_KEEP_TOOLS:])
    out = []
    for i, m in enumerate(msgs):
        if i in keep or getattr(m, 'type', '') != 'tool' and not hasattr(m, 'tool_call_id'):
            out.append(m)
            continue
        txt = str(getattr(m, 'content', '') or '')
        summary = txt.strip().splitlines()
        first = summary[0][:120] if summary else ''
        try:
            m.content = '[历史工具结果已压缩，原 %d 字符] %s' % (len(txt), first)
        except Exception:
            pass
        out.append(m)
    print('[GIS] 上下文超过 %d 字符，已压缩 %d 条历史工具结果' %
          (GRAPH_CTX_MAX_CHARS, len(tool_idx) - len(keep)), flush=True)
    return out

_GRAPH_RECURSION_LIMIT = int(__import__("os").environ.get("GIS_GRAPH_RECURSION", "120"))
_AGENT_LOCK_LEASE = threading.local()
_STREAM_CANCELLED = object()


class _DeferredLockLease:
    """Keep request locks held until timed-out background workers have stopped."""

    def __init__(self, release_locks):
        self._release_locks = release_locks
        self._guard = threading.Lock()
        self._workers = 0
        self._finished = False
        self._released = False

    def worker_started(self):
        with self._guard:
            self._workers += 1

    def worker_finished(self):
        release = False
        with self._guard:
            self._workers -= 1
            if self._finished and self._workers == 0 and not self._released:
                self._released = True
                release = True
        if release:
            self._release_locks()

    def finish(self):
        release = False
        with self._guard:
            self._finished = True
            if self._workers == 0 and not self._released:
                self._released = True
                release = True
        if release:
            self._release_locks()

    def track_future(self, future):
        self.worker_started()
        future.add_done_callback(lambda _: self.worker_finished())


class _ToolInvocationTracker(BaseCallbackHandler):
    """Track whether an Agent attempt reached a tool before an exception."""

    def __init__(self):
        self.started = threading.Event()

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.started.set()


def _invoke_agent_with_budget(agent, payload, limit, timeout_s, callbacks=None, cancel_check=None):
    """在调用方剩余总时长预算内等待一次 agent.invoke。"""
    executor = _cf_mod.ThreadPoolExecutor(max_workers=1)
    config = {"recursion_limit": limit}
    if callbacks:
        config["callbacks"] = callbacks
    invoke_context = copy_context()
    future = executor.submit(invoke_context.run, agent.invoke, payload, config)
    try:
        deadline = _time_mod.monotonic() + max(0.0, float(timeout_s))
        while True:
            if cancel_check is not None and cancel_check():
                lease = getattr(_AGENT_LOCK_LEASE, "current", None)
                if lease is not None:
                    lease.track_future(future)
                future.cancel()
                return "cancelled", None
            remaining = deadline - _time_mod.monotonic()
            if remaining <= 0:
                if future.done():
                    try:
                        return "ok", future.result()
                    except Exception as error:
                        return "err", error
                lease = getattr(_AGENT_LOCK_LEASE, "current", None)
                if lease is not None:
                    lease.track_future(future)
                future.cancel()
                return "timeout", TimeoutError("graph total budget exceeded")
            try:
                result = future.result(timeout=min(remaining, 0.1) if cancel_check is not None else remaining)
                if cancel_check is not None and cancel_check():
                    return "cancelled", None
                return "ok", result
            except _cf_mod.TimeoutError as error:
                if future.done():
                    return "err", error
                if cancel_check is None:
                    lease = getattr(_AGENT_LOCK_LEASE, "current", None)
                    if lease is not None:
                        lease.track_future(future)
                    future.cancel()
                    return "timeout", TimeoutError("graph total budget exceeded")
    except Exception as e:
        return ("err", e)
    finally:
        # Python cannot stop an already-running worker thread; do not block the
        # request thread while the underlying model/tool call winds down.
        executor.shutdown(wait=False)


def _stream_with_deadline(stream, deadline, lease=None, cancel_check=None):
    """Consume a blocking LangGraph stream without exceeding the caller deadline."""
    events = queue.Queue(maxsize=1)
    stopped = threading.Event()

    def publish(event):
        while not stopped.is_set():
            try:
                events.put(event, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def produce():
        try:
            for item in stream:
                if not publish(("item", item)):
                    return
        except BaseException as error:
            publish(("error", error))
        else:
            publish(("done", None))
        finally:
            if lease is not None:
                lease.worker_finished()

    stream_context = copy_context()
    worker = threading.Thread(
        target=stream_context.run, args=(produce,), name="gis-agent-stream", daemon=True,
    )
    if lease is not None:
        lease.worker_started()
    try:
        worker.start()
    except BaseException:
        if lease is not None:
            lease.worker_finished()
        raise
    try:
        while True:
            remaining = deadline - _time_mod.monotonic()
            if remaining <= 0:
                raise TimeoutError("graph stream total budget exceeded")
            if cancel_check is not None and cancel_check():
                stopped.set()
                yield _STREAM_CANCELLED
                return
            try:
                wait_for = min(remaining, 0.1) if cancel_check is not None else remaining
                kind, value = events.get(timeout=wait_for)
            except queue.Empty as error:
                if cancel_check is not None:
                    continue
                raise TimeoutError("graph stream total budget exceeded") from error
            if kind == "done":
                return
            if kind == "error":
                raise value
            yield value
    finally:
        stopped.set()


def _tool_not_callable(e: Exception) -> bool:
    """识别 LangChain 框架角例：'StructuredTool' object is not callable。"""
    return isinstance(e, TypeError) and "callable" in str(e)


def _recover_tool_dispatch_text(cfg, messages) -> str:
    """工具调度异常后只做纯文本收尾，避免从原始请求重跑已执行过的工具。"""
    fallback_llm = build_llm(disable_reasoning(cfg))
    response = fallback_llm.invoke(
        list(messages) + [HumanMessage(
            content="请停止调用任何工具，直接用文字总结已经完成的结果；"
                    "如果工具没有成功完成，请明确说明，不要声称成功。"
        )],
        max_tokens=800,
    )
    return (getattr(response, "content", "") or "").strip()


_PROMISE_PREFIXES = (
    "好的", "好", "行", "可以", "没问题", "稍等", "请稍等", "马上",
    "我这就", "我现在", "我先", "让我", "我来", "这就去", "正在",
    "现在开始", "好嘞", "我先确认", "我来确认", "正在查询", "正在查找",
)
_PROMISE_VERBS = re.compile(
    r"(获取|下载|加载|搜索|查找|抓取|截取|提取|分析|计算|生成|绘制|采集|整理|统计|构建|创建|调用|做一下|找一下|确认|查询|核对|测量|测算|标注|标出|标到|重绘)"
)


def _looks_like_incomplete_promise(text) -> bool:
    """识别「AI 说开始做但实际没做」的结尾：以应允/开场白开头、带动作词、且文本很短。

    这类结尾典型形态：“好的，我现在开始获取法国边界数据”、“我先确认一下这个图层的存在...请稍等，我来调用工具”。若本轮没执行任何工具，
    说明它只承诺未交付（常见于部分模型只叙事不调工具）。
    """
    if not text:
        return False
    t = (text or "").strip()
    if len(t) > 600:
        return False
    # 只要命中口头承接前缀或者文本中明显包含"请稍等/我来调用工具/正在查询"
    has_prefix = t.startswith(_PROMISE_PREFIXES)
    has_monologue = bool(re.search(r"(请稍等.*调用工具|正在查询|我来调用工具|确认一下.*再计算)", t))
    if not (has_prefix or has_monologue):
        return False
    return bool(_PROMISE_VERBS.search(t))


def _promise_without_action(text, msgs) -> bool:
    """最终回复是"承诺式开头"且本轮没有任何工具消息 → 判定为只承诺未执行。"""
    if not _looks_like_incomplete_promise(text):
        return False
    return not any(isinstance(m, ToolMessage) for m in (msgs or []))


_CODE_DUMP_PATTERNS = re.compile(
    r"(没法在这边|无法直接生成|不能直接生成|无法直接跑出|没法直接出图|复制到本地|在\s*(Jupyter|本地|VSCode|终端)\s*里?(直接)?(出图|运行|执行)|代码复制到|把下面代码存成)",
    re.IGNORECASE
)


_CODE_BLOCK_RE = re.compile(r"```[ \t]*([a-zA-Z0-9_+-]*)[ \t]*\r?\n[\s\S]*?```", re.MULTILINE)
_CODE_REQUEST_KWS = (
    "代码", "源码", "脚本", "怎么写", "如何写", "给我写", "贴一下",
    "python", "code", "script", "snippet",
)
_EXECUTED_CODE_NOTE = "〔已执行的 Python 脚本，源码省略〕"


def _strip_executed_code_blocks(text: str, msgs: list, original_message: str = "") -> str:
    """把「本轮已经真实执行过」的 Python 源码从最终正文中折叠掉。

    背景：模型习惯先把整坨 matplotlib 代码粘进回复、再贴结论，用户看到的是几百行源码
    而不是交付物。代码只是执行细节，不是答案——但用户明确索要代码时必须保留原样。

    触发条件（全满足才折叠）：
    1. 正文里存在代码块；
    2. 本轮确实有工具消息（代码已经在服务端跑过，不是甩给用户跑）；
    3. 用户原话没有索要代码。
    """
    if not text or "```" not in text:
        return text
    if not _has_tool_messages(msgs):
        return text
    if original_message and any(k in original_message.lower() for k in _CODE_REQUEST_KWS):
        return text

    def _repl(m: "re.Match") -> str:
        lang = (m.group(1) or "").lower()
        if lang and lang != "python":
            # 非 Python 代码块（JSON 数据、SQL、命令行输出等）属于结论的一部分，保留
            return m.group(0)
        lines = m.group(0).splitlines()[1:-1]
        if not any(l.strip() for l in lines):
            return m.group(0)
        return _EXECUTED_CODE_NOTE

    cleaned = _CODE_BLOCK_RE.sub(_repl, text)
    # 折叠后可能出现连续空 Note 行 → 合并
    cleaned = re.sub(rf"(?:{re.escape(_EXECUTED_CODE_NOTE)}\s*){{2,}}", _EXECUTED_CODE_NOTE + "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _is_unexecuted_code_or_disclaimer(text, msgs) -> bool:
    """识别 AI 宣称自己无法出图、或把制图代码甩给用户让用户本地运行但自己未调工具的情况。"""
    if not text:
        return False
    if any(isinstance(m, ToolMessage) for m in (msgs or [])):
        return False
    # 情况 1：明确出现“无法在这边生成图片/复制到本地/Jupyter运行”这类卸责话术
    if bool(_CODE_DUMP_PATTERNS.search(text)):
        return True
    # 情况 2：输出了带有 plt.savefig / fig.savefig / plt.show 的 Python 代码块，但本轮未调用任何工具
    if ("plt.savefig" in text or "fig.savefig" in text or "plt.show" in text) and ("```python" in text or "```" in text):
        return True
    return False


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


def _empty_response_diagnostic(msgs: list) -> str:
    """记录空响应的可观测原因，不记录推理正文或密钥。"""
    for msg in reversed(msgs or []):
        if not isinstance(msg, AIMessage):
            continue
        metadata = getattr(msg, "response_metadata", {}) or {}
        reasoning = msg.additional_kwargs.get("reasoning_content")
        return (
            f"finish_reason={metadata.get('finish_reason', 'unknown')}, "
            f"content_chars={len(str(msg.content or ''))}, "
            f"has_reasoning={bool(reasoning)}, "
            f"tool_calls={len(getattr(msg, 'tool_calls', None) or [])}"
        )
    return "no_ai_message"


# 强制补执行时注入的纠错指令（非流式/流式共用，抽为常量便于测试回归）
_RECOVERY_PROMPT_CODE_DUMP = (
    "系统提示：平台完全具备直接执行 Python 并渲染图件的能力，严禁向用户声称“无法直接出图”或让用户复制代码去本地/Jupyter运行！"
    "请你现在就直接调用 execute_python 工具执行你编写的 Python 制图代码，将成果保存为图片（例如 plt.savefig('output/xxx.png')），平台会自动渲染展示图片卡片！"
)
_RECOVERY_PROMPT_NO_ACTION = (
    "你刚才只是说“开始执行”，但实际没有调用任何工具。"
    "请现在就调用合适工具真正完成你承诺的任务，不要再只做口头承诺。"
)
_RECOVERY_PROMPT_EMPTY = (
    "上一轮没有返回用户可见的正文，也没有产生真实工具调用。请回到最初的用户请求继续完成任务："
    "需要查询数据或操作图层时，直接发出已绑定工具的结构化调用并根据工具结果回答；"
    "不要只在文字中描述工具计划，也不要输出内部思考过程。纯知识问题则直接简洁回答。"
)


def _invoke_empty_response_recovery(agent, messages: list, recursion_limit: int = 60,
                                    cfg: LLMConfig = None, available_tools: list = None,
                                    recovery_prompt: str = _RECOVERY_PROMPT_EMPTY,
                                    timeout_s: float | None = None, cancel_check=None):
    """空正文/空口承诺时，关闭推理并强制发出结构化工具调用，再执行 ReAct 循环。"""
    if cancel_check is not None and cancel_check():
        return _STREAM_CANCELLED
    recovery_agent = agent
    fallback_agent = agent
    if cfg is not None and available_tools:
        try:
            # 思考内容只是 AIMessage 元数据，不会触发 LangGraph 工具节点。
            # DeepSeek 思考模式不接受 tool_choice=required；恢复调用关闭 reasoning，
            # 明确要求模型至少选择一个工具，避免仅重复生成 reasoning 后再次空响应。
            recovery_llm = build_llm(disable_reasoning(cfg))
            fallback_agent = create_react_agent(recovery_llm, available_tools)
            auto_llm = recovery_llm.bind_tools(available_tools)
            required_llm = recovery_llm.bind_tools(available_tools, tool_choice="required")

            def select_recovery_model(state, runtime):
                # 只强制恢复后的第一步选择工具；工具返回后恢复 auto，允许模型正常总结。
                last = state["messages"][-1]
                return required_llm if isinstance(last, HumanMessage) else auto_llm

            recovery_agent = create_react_agent(select_recovery_model, available_tools)
        except Exception as bind_error:
            recovery_agent = fallback_agent
            print(f"[GIS] 无法启用强制工具调用恢复，退回关闭推理的普通工具模式: {bind_error}", flush=True)

    payload = {"messages": list(messages) + [HumanMessage(content=recovery_prompt)]}
    deadline = None if timeout_s is None else _time_mod.monotonic() + max(0.0, float(timeout_s))

    def invoke_bounded(target):
        if deadline is None and cancel_check is None:
            return target.invoke(payload, {"recursion_limit": recursion_limit})
        remaining = float("inf") if deadline is None else max(0.0, deadline - _time_mod.monotonic())
        status, result = _invoke_agent_with_budget(
            target, payload, recursion_limit, remaining, cancel_check=cancel_check,
        )
        if status == "cancelled":
            return _STREAM_CANCELLED
        if status == "ok":
            return result
        raise result

    try:
        return invoke_bounded(recovery_agent)
    except Exception as recovery_error:
        if cancel_check is not None and cancel_check():
            return _STREAM_CANCELLED
        if recovery_agent is fallback_agent:
            raise
        # Provider 可能不支持 tool_choice=required。保留有界回退，至少重试一次普通工具模式。
        print(f"[GIS] 强制工具调用恢复失败，退回普通工具调用: {recovery_error}", flush=True)
        return invoke_bounded(fallback_agent)


def _tool_result_fallback(msgs: list) -> str:
    """工具已执行但模型未总结时，返回最近一条工具结果，避免伪造成功或空回复。"""
    for msg in reversed(msgs or []):
        if isinstance(msg, ToolMessage):
            content = str(msg.content or "").strip()
            if content:
                return "工具已执行，但模型没有生成总结。工具返回：\n" + content[:3000]
    return ""


def _auto_promote_pending(session_id: str, start_registered: set, pushed_names: list):
    """一轮 Agent 结束：把「新注册但未推送到地图」的图层挂起为 pending load_layer。

    用户下一条“继续/确认/执行”会确定性加载；“取消”会清除。不打扰已展示的图层。
    """
    try:
        pending_action.promote_registered_undisplayed(
            session_id, start_registered, pushed_names)
    except Exception as _e:  # 永不因挂起失败破坏主流程
        print(f"[GIS] auto-promote pending 失败（忽略）: {_e}", flush=True)


def _ensure_ops_layers_present(pending: dict):
    """layer_ops 引用的图层若只注册未推送（常见于上轮卡死/模型偷懒复用注册层），
    直接从注册表补推进 pending——杜绝「正文说已标出、done 里却没有该图层」。

    幂等：已在 pending.layers 里的跳过；注册表没有的忽略（保持原有报错路径）。
    """
    try:
        pushed_names = {l.get("name") for l in (pending.get("layers") or [])}
        for op in (pending.get("layer_ops") or []):
            name = (op or {}).get("name")
            if not name or name in pushed_names:
                continue
            reg = getattr(_tools_mod, "_registered_layers", {}) or {}
            info = reg.get(name)
            if info is None:
                # 模糊匹配：op 名与注册名互为前缀
                for rname, rinfo in reg.items():
                    if rname and (rname.startswith(name) or name.startswith(rname)):
                        info, name = rinfo, rname
                        break
            if info and info.get("geojson") is not None:
                _tools_mod._push_layer(name, info["geojson"], style=info.get("style"))
                pushed_names.add(name)
                print(f"[GIS] layer_ops 引用图层「{name}」未推送，已从注册表补推", flush=True)
    except Exception as _e:
        print(f"[GIS] ops-layers 补推失败（忽略）: {_e}", flush=True)


def _with_session_lock(func):
    """确保同步 Agent 入口在所有返回和异常路径上都释放会话锁。"""
    @wraps(func)
    def wrapped(*args, **kwargs):
        session_id = kwargs.get("session_id", args[5] if len(args) > 5 else "default") or "default"
        if not _tools_mod.acquire_session_lock(session_id):
            return {
                "response": "当前会话已有请求在处理中，请等待上一条完成后再发送新消息。",
                "reasoning": None, "layers": [], "images": [], "heatmap": None,
                "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
                "confirm_pending": None,
                "busy": True,
            }
        try:
            shared_acquired = _tools_mod.acquire_shared_state_lock(0)
        except BaseException:
            _tools_mod.release_session_lock(session_id)
            raise
        if not shared_acquired:
            _tools_mod.release_session_lock(session_id)
            return {
                "response": "当前 GIS 工作区正在处理另一项操作，请稍后重试。",
                "reasoning": None, "layers": [], "images": [], "heatmap": None,
                "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
                "confirm_pending": None, "busy": True,
            }
        request_id = kwargs.get("request_id", args[7] if len(args) > 7 else None)
        import backend.services.ai_service as _cancel_service
        _cancel_service.register_cancel_request(session_id, request_id)
        cancel_context_token = _cancel_service.set_request_cancel_context(session_id, request_id)
        lease = _DeferredLockLease(lambda: (
            _cancel_service.finish_cancel_request(session_id, request_id),
            _tools_mod.release_shared_state_lock(),
            _tools_mod.release_session_lock(session_id),
        ))
        previous_lease = getattr(_AGENT_LOCK_LEASE, "current", None)
        _AGENT_LOCK_LEASE.current = lease
        try:
            return func(*args, **kwargs)
        finally:
            _AGENT_LOCK_LEASE.current = previous_lease
            lease.finish()
            _cancel_service.reset_request_cancel_context(cancel_context_token)
    return wrapped


def _record_run_finish(run_id: str, response: str, status: str, guard_status: str = "NOT_CHECKED") -> None:
    """Best-effort close for every run that already has a start record."""
    try:
        from backend.services import storage_service
        storage_service.record_run_finish(run_id, response, status, guard_status)
    except Exception:
        pass


@_with_session_lock
def run_agent(
    messages: list,
    cfg: LLMConfig,
    amap_key: str = "",
    skill_text: str = "",
    original_message: str = "",
    session_id: str = "default",
    task_id: str = None,
    request_id: str = None,
) -> dict:
    """运行 LangGraph Agent 并对最终产物执行确定性真实性检查。

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
    from backend.services.privacy_service import session_protected, run_private_agent
    if session_protected(session_id):
        return run_private_agent(original_message, session_id, cfg, request_id)
    # 重置共享状态（tools.py 中的全局变量）
    import backend.services.ai_service as _ai_cancel_svc
    _cancel_generation = _ai_cancel_svc.clear_session_cancel(session_id or "default", request_id)
    reset_state(amap_key)
    _tools_mod.set_last_user_message(original_message or "")
    # 提取最近多轮上下文（供工具层消歧与实体复用）
    _ctx_texts = []
    for _m in (messages or [])[-10:]:
        _c = getattr(_m, "content", "")
        if isinstance(_c, str) and _c.strip():
            _ctx_texts.append(_c.strip())
    _tools_mod.set_conversation_context("\n".join(_ctx_texts))
    # === P1-1: Agent 运行状态与 SQLite 台账 ===
    _run_id = uuid.uuid4().hex[:12]
    _run_started_at = time.time()
    _run_retry_count = 0
    _tools_mod.set_current_run(_run_id)
    print(f"[GIS] run_id={_run_id} status=planning", flush=True)
    # 绑定本请求会话（hold 等工具写 pending 用）
    pending_action.set_active_session(session_id or "default")
    _start_registered = set(getattr(_tools_mod, "_registered_layers", {}).keys())

    # === Task Manager: 解析/创建任务，绑定到 tools ===
    _task_id = task_manager.find_or_create_task(session_id or "default", original_message or "", task_id=task_id)
    set_current_task(_task_id)
    print(f"[GIS] Task ID: {_task_id}", flush=True)

    # 记录到 SQLite 本地台账
    try:
        from backend.services import storage_service
        storage_service.record_run_start(_run_id, session_id or "default", original_message or "", _task_id)
    except Exception:
        pass

    # 构建 LLM
    try:
        llm = build_llm(cfg)
    except Exception:
        _record_run_finish(_run_id, "模型初始化失败", "error")
        raise

    # 简单文本对话（无关键词）直接调 LLM，不走 LangGraph 省掉框架开销
    # A+ 优化：去掉"帮我"等易误判词，短路时用精简版 system prompt
    _simple = not _should_use_agent(messages, session_id)
    if _simple:
        if _ai_svc.is_session_cancelled(session_id or "default", request_id, _cancel_generation):
            _record_run_finish(_run_id, "用户已取消", "cancelled")
            return {"response": "用户已取消", "reasoning": None, "layers": [], "images": [],
                    "heatmap": None, "clear_layers": False, "layer_ops": [],
                    "pending_suggestions": None, "execution_status": "cancelled"}
        try:
            def _invoke_simple_model():
                yield llm.invoke(messages)

            _resp = None
            for _simple_result in _stream_with_deadline(
                _invoke_simple_model(),
                _time_mod.monotonic() + _GRAPH_TOTAL_TIMEOUT_S,
                lease=getattr(_AGENT_LOCK_LEASE, "current", None),
                cancel_check=lambda: _ai_svc.is_session_cancelled(
                    session_id or "default", request_id, _cancel_generation
                ),
            ):
                if _simple_result is _STREAM_CANCELLED:
                    _record_run_finish(_run_id, "用户已取消", "cancelled")
                    return {"response": "用户已取消", "reasoning": None, "layers": [], "images": [],
                            "heatmap": None, "clear_layers": False, "layer_ops": [],
                            "pending_suggestions": None, "execution_status": "cancelled"}
                _resp = _simple_result
            _quick_text = _clean_ai_text(_resp.content or "")
            if _looks_like_incomplete_promise(_quick_text):
                # 快路径不带任何工具：模型只是"口头承诺去获取/生成"时必须改走 Agent，
                # 否则用户看到的就是一句"我来获取"然后没有下文。
                print("[GIS] 快路径命中空口承诺，改走 Agent 工具通道", flush=True)
                _simple = False
            else:
                try:
                    _record_run_finish(_run_id, _quick_text, "success", "BYPASS")
                except Exception:
                    pass
                return {
                    "response": _quick_text or "模型本轮没有返回可见答复，请重试。",
                    "reasoning": get_message_reasoning(_resp),
                    "layers": [], "images": [], "heatmap": None,
                    "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
                }
        except Exception as e:
            _err_str = str(e)
            if "402" in _err_str or "Insufficient Balance" in _err_str:
                _err_str = "API 余额不足（402），请充值或在设置中更换有余额的 API Key 后重试。"
            elif "401" in _err_str or "invalid_api_key" in _err_str:
                _err_str = "API Key 无效或已过期（401），请在设置中检查 API Key 配置。"
            elif "429" in _err_str or "rate_limit" in _err_str:
                _err_str = "API 请求频率超限（429），请稍后重试。"
            elif "timeout" in _err_str.lower():
                _err_str = "API 请求超时，请检查网络连接或稍后重试。"
            _record_run_finish(_run_id, f"AI 回复失败: {_err_str[:200]}", "error")
            return {"response": f"AI 回复失败: {_err_str[:200]}", "reasoning": None,
                "layers": [], "images": [], "heatmap": None,
                "clear_layers": False, "layer_ops": [], "pending_suggestions": None}

    # 构建 LangGraph ReAct Agent
    try:
        agent = create_react_agent(llm, tools)
    except Exception:
        _record_run_finish(_run_id, "Agent 初始化失败", "error")
        raise

    # 快照进入本轮 invoke 之前的 pending 状态（失败重试时只保留"本次 invoke 产生的差量"）
    _pre_invoke_pending = None
    try:
        _pre_invoke_pending = get_pending_state()
    except Exception:
        _pre_invoke_pending = None

    # 运行 Agent
    # 框架角例：langchain 1.x 下 @tool 返回 StructuredTool（无 __call__），reasoning 模型
    # 在长工具链末尾偶发把工具对象当普通函数调用 → TypeError "'StructuredTool' object is not callable"。
    # 处理：自动降级重试一次（追加“请纯文本收尾，不再调工具”），有界且保留已产出图层/数据。
    result = None
    _usage_attempts = []
    _invoke_pending = None
    _msgs = list(messages)
    _budget_deadline = _time_mod.monotonic() + _GRAPH_TOTAL_TIMEOUT_S
    _budget_hit = False
    for _attempt in range(2):
        _tool_tracker = _ToolInvocationTracker()
        try:
            if _ai_svc.is_session_cancelled(session_id or "default", request_id, _cancel_generation):
                _record_run_finish(_run_id, "用户已取消", "cancelled")
                return {"response": "用户已取消", "reasoning": None, "layers": [], "images": [],
                        "heatmap": None, "clear_layers": False, "layer_ops": [],
                        "pending_suggestions": None}
            if _time_mod.monotonic() > _budget_deadline:
                _budget_hit = True
                raise TimeoutError(f"graph total budget exceeded ({_GRAPH_TOTAL_TIMEOUT_S:.0f}s)")
            _remaining_budget = _budget_deadline - _time_mod.monotonic()
            _status, _inv = _invoke_agent_with_budget(
                agent, {"messages": _msgs}, _GRAPH_RECURSION_LIMIT, _remaining_budget,
                callbacks=[_tool_tracker],
                cancel_check=lambda: _ai_svc.is_session_cancelled(
                    session_id or "default", request_id, _cancel_generation
                ),
            )
            if _status == "cancelled":
                _record_run_finish(_run_id, "用户已取消", "cancelled")
                return {"response": "用户已取消", "reasoning": None, "layers": [], "images": [],
                        "heatmap": None, "clear_layers": False, "layer_ops": [],
                        "pending_suggestions": None, "execution_status": "cancelled"}
            if _status == "timeout":
                _budget_hit = True
                raise _inv
            if _status == "ok":
                result = _inv
                # 重试成功：把 invoke 前快照的 pending 差量合并回原 pending 列表（去重）
                if _pre_invoke_pending is not None:
                    try:
                        _cur = get_pending_state()
                        _invoke_pending = _cur
                        for _k in ("layers", "images", "layer_ops", "qa_warnings"):
                            _prev = _pre_invoke_pending.get(_k) or []
                            _now = _cur.get(_k) or []
                            if _prev or _now:
                                _seen = set()
                                _merged = []
                                for _it in _prev + _now:
                                    _key = json.dumps(_it, ensure_ascii=False, sort_keys=True, default=str)
                                    if _key in _seen:
                                        continue
                                    _seen.add(_key)
                                    _merged.append(_it)
                                if _k in _cur:
                                    _cur[_k] = _merged
                    except Exception:
                        pass
                break
            raise _inv
        except Exception as e:
            import traceback
            traceback.print_tb(e.__traceback__)
            print(f"[GIS] Agent 请求异常: {_safe_model_error(e, cfg)[:300]}", flush=True)
            if _budget_hit:
                _record_run_finish(_run_id, "任务执行时长已达上限", "timeout")
                return {
                    "response": (
                        "任务等待时限已到（约 %d 秒）。底层 Agent 调用无法被强制中止，后台调用仍可能继续并完成工具操作。"
                        "工作区会保持忙碌，直到后台调用结束；本次超时响应没有收到它的最终结果。\n\n"
                        "请勿立即重复提交。工作区解除忙碌后，先检查图层和输出文件，再决定是否重试。"
                    ) % int(_GRAPH_TOTAL_TIMEOUT_S),
                    "reasoning": None, "layers": [], "images": [],
                    "heatmap": None, "clear_layers": False, "layer_ops": [],
                    "pending_suggestions": None, "execution_status": "timeout",
                }
            if _attempt == 0 and _tool_not_callable(e):
                print("[GIS] 工具调度 TypeError，使用无工具模型收尾，避免重放原任务", flush=True)
                try:
                    _recovery_text = _recover_tool_dispatch_text(cfg, messages)
                except Exception as _recovery_error:
                    print(f"[GIS] 工具调度异常后的文本收尾失败: {_safe_model_error(_recovery_error, cfg)}", flush=True)
                    _recovery_text = ""
                if _recovery_text:
                    result = {"messages": list(messages) + [AIMessage(content=_recovery_text)]}
                    break
                _record_run_finish(_run_id, "工具调度发生异常，未重放任务", "error")
                return {
                    "response": "工具调度发生异常，已停止自动重放以避免重复执行。请检查工具记录后重试。",
                    "reasoning": None, "layers": [], "images": [],
                    "heatmap": None, "clear_layers": False, "layer_ops": [],
                    "pending_suggestions": None,
                }
            # P1-2: 网络临时异常重试一次（不重试确定性错误）
            _err_lower = str(e).lower()
            _is_temp = any(k in _err_lower for k in [
                "timeout", "timed out", "connection", "502", "503", "504",
                "rate limit", "429", "temporarily", "server error",
                "api connection", "network", "reset by peer",
            ])
            _tool_may_have_run = _tool_tracker.started.is_set()
            if _attempt == 0 and _is_temp and not _tool_may_have_run:
                _run_retry_count = 1
                print("[GIS] 网络临时异常，自动重试一次: " + _safe_model_error(e, cfg)[:100], flush=True)
                import time as _time; _time.sleep(1)
                continue
            if _tool_may_have_run:
                friendly = (
                    "GIS 工具已开始执行，但 AI 服务随后连接中断。为避免重复操作，系统未自动重跑；"
                    "请检查已生成图层或文件后再决定是否重试。"
                )
                _record_run_finish(_run_id, friendly, "error")
                partial = get_pending_state()
                return {
                    "response": friendly, "reasoning": None,
                    "layers": partial["layers"], "images": partial["images"],
                    "heatmap": partial["heatmap"], "clear_layers": partial["clear_layers"],
                    "layer_ops": partial["layer_ops"],
                    "pending_suggestions": (partial["aoi_suggestions"] or {}).get("suggestions"),
                    "qa_warnings": partial["qa_warnings"],
                }
            error_msg = _safe_model_error(e, cfg)
            if "recursion_limit" in error_msg or "RecursionError" in error_msg:
                friendly = "AI 在处理复杂任务时超限。已优化限制，请重试。如仍有问题，请简化请求描述。"
                print(f"[GIS] 递归超限: {error_msg}", flush=True)
            else:
                friendly = f"AI 服务调用失败: {error_msg}"
            _record_run_finish(_run_id, friendly, "error")
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
    _usage_attempts.append(list(final_messages))
    final_text, final_reasoning = _last_ai_text(final_messages)

    # === P0-2: 检查 LLM finish_reason ===
    # 保守处理：只在最后一条 AIMessage 做用户可见提示；
    # 全流式中间消息若发生截断，暂不另行重试（风险：后续工具结果可能让模型继续走、错误不被观察到），
    # 这里仅做一次任何 AIMessage 截断的日志提示，保持现有行为但对调试可见。
    _any_truncation = False
    for _msg in final_messages:
        if not isinstance(_msg, AIMessage):
            continue
        _fr = (_msg.response_metadata or {}).get("finish_reason", "")
        if _fr in ("length", "content_filter", "insufficient_system_resource"):
            _any_truncation = True
            break
    if _any_truncation:
        print("[GIS] 流程中存在 AIMessage 被截断（length/content_filter/insufficient_system_resource），结果可能不完整。", flush=True)

    for _msg in reversed(final_messages):
        if isinstance(_msg, AIMessage):
            _fr = (_msg.response_metadata or {}).get("finish_reason", "")
            if _fr == "length":
                final_text = (final_text or "") + "\n\n[注意] 回复因模型输出长度限制被截断，内容可能不完整。"
            elif _fr == "content_filter":
                final_text = (final_text or "") + "\n\n[注意] 回复因内容安全策略被部分拦截。"
            elif _fr == "insufficient_system_resource":
                final_text = (final_text or "") + "\n\n[注意] 模型服务资源不足，回复可能不完整，请稍后重试。"
            break

    _run_finish_status = "success"
    # 空响应处理：此前会追加“不要调用工具”，可能直接压掉模型原本要执行的 GIS 请求。
    if not final_text and not _has_tool_messages(final_messages) and _count_tool_calls(final_messages) == 0:
        print(f"[GIS] 空响应且没有工具调用（{_empty_response_diagnostic(final_messages)}），关闭推理并强制调用工具重试", flush=True)
        try:
            _retry = _invoke_empty_response_recovery(
                agent, messages, recursion_limit=60, cfg=cfg, available_tools=tools,
                timeout_s=max(0.0, _budget_deadline - _time_mod.monotonic()),
                cancel_check=lambda: _ai_svc.is_session_cancelled(
                    session_id or "default", request_id, _cancel_generation
                ))
            if _retry is _STREAM_CANCELLED:
                _record_run_finish(_run_id, "用户已取消", "cancelled")
                return {"response": "用户已取消", "reasoning": None, "layers": [], "images": [],
                        "heatmap": None, "clear_layers": False, "layer_ops": [],
                        "pending_suggestions": None, "execution_status": "cancelled"}
            _retry_msgs = _retry.get("messages", [])
            _usage_attempts.append(list(_retry_msgs))
            _retry_text, _retry_reasoning = _last_ai_text(_retry_msgs)
            _retry_tools = _count_tool_calls(_retry_msgs) > 0 or _has_tool_messages(_retry_msgs)
            if _retry_text:
                final_text = _retry_text
                final_reasoning = _retry_reasoning
                final_messages = _retry_msgs
            elif _retry_tools:
                final_messages = _retry_msgs
                final_text = _tool_result_fallback(_retry_msgs)
            if _retry_tools:
                _invoke_pending = get_pending_state()
        except Exception as _re:
            print(f"[GIS] 空响应执行重试失败: {_re}", flush=True)
            if isinstance(_re, TimeoutError) and "budget exceeded" in str(_re).lower():
                _budget_hit = True
                _run_finish_status = "timeout"
                final_text = "自动恢复达到执行时限，本轮结果可能不完整；请缩小任务范围后重试。"
        if not final_text:
            final_text = "模型本轮没有生成答复，也没有实际调用工具；已自动重试但仍未完成。这次没有完成计算，请重试该请求。"
    if not final_text:
        final_text = _tool_result_fallback(final_messages) or (
            "模型提出了工具调用，但工具没有返回结果；本次操作未确认完成，请检查工具记录后重试。"
            if _count_tool_calls(final_messages) else
            "AI 未返回有效响应，请重试或更换模型。"
        )

    # 收集本轮产生的共享状态
    # The successful invoke snapshot is already consumed from shared state; carry it
    # forward instead of returning an empty done payload for map updates/artifacts.
    pending = _invoke_pending if _invoke_pending is not None else get_pending_state()
    # layer_ops 引用但未推送的注册图层 → 补推进 done，防止前端「未找到图层」
    _ensure_ops_layers_present(pending)
    # ask_user_choice 弹选项（非流式一次性 invoke 无法中途打断，收尾时发现标记
    # 则直接用提示文本收尾，并跳过"强制补执行"否则 force exec 会把选项流程搅黄）
    _waiting_choice = False
    for _m in final_messages:
        _mc = str(getattr(_m, "content", "") or "")
        if not isinstance(_m, AIMessage) and "[WAITING_USER_CHOICE]" in _mc:
            _waiting_choice = True
            break
    if _waiting_choice and not final_text:
        final_text = "已向用户弹出选项，请点击选择后继续。"

    # === 防“只说开始就结束”：只承诺未执行（无任何工具调用）时强制补一轮真实执行 ===
    _initial_tool_calls = _count_tool_calls(final_messages)
    _initial_has_tools = _has_tool_messages(final_messages)
    print(f"[GIS DEBUG] 初始工具调用: {_initial_tool_calls} 次, 有工具消息: {_initial_has_tools}", flush=True)
    
    _need_force_exec = (not _waiting_choice) and (_promise_without_action(final_text, final_messages) or _is_unexecuted_code_or_disclaimer(final_text, final_messages))
    # 每轮请求只检查一次并最多补执行一轮；状态放在局部变量中，避免相同文本的后续新请求被误拦。
    _allow_force = _need_force_exec
    if _allow_force:
        try:
            print("[GIS] 检测到未执行承诺或未执行制图代码，强制补一轮真实工具执行", flush=True)
            _prompt_text = (
                _RECOVERY_PROMPT_CODE_DUMP
                if _is_unexecuted_code_or_disclaimer(final_text, final_messages)
                else _RECOVERY_PROMPT_NO_ACTION
            )
            _forced = _invoke_empty_response_recovery(
                agent, final_messages, recursion_limit=60, cfg=cfg,
                available_tools=tools, recovery_prompt=_prompt_text,
                timeout_s=max(0.0, _budget_deadline - _time_mod.monotonic()),
                cancel_check=lambda: _ai_svc.is_session_cancelled(
                    session_id or "default", request_id, _cancel_generation
                ))
            if _forced is _STREAM_CANCELLED:
                _record_run_finish(_run_id, "用户已取消", "cancelled")
                return {"response": "用户已取消", "reasoning": None, "layers": [], "images": [],
                        "heatmap": None, "clear_layers": False, "layer_ops": [],
                        "pending_suggestions": None, "execution_status": "cancelled"}
            _fm = _forced.get("messages", [])
            _usage_attempts.append(list(_fm))
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
            if isinstance(_pe, TimeoutError) and "budget exceeded" in str(_pe).lower():
                _budget_hit = True
                _run_finish_status = "timeout"
                final_text = (final_text or "") + "\n\n[注意] 自动补执行达到时限，结果可能不完整。"
    # === 正文净化：本轮已执行的 Python 源码折叠为一行，避免几百行代码盖住交付物 ===
    final_text = _strip_executed_code_blocks(final_text, final_messages, original_message or "")

    # === 结果真实性自检（确定性：核对磁盘与内存状态，无额外 LLM 调用）===
    # 仅在后台自检并记录日志，默认不向用户端追加内部检查说明（避免误报和干扰用户）
    final_text, _guard = result_guard.apply_guard(
        final_text, pending, task_id=_task_id, run_id=_run_id, run_start_time=_run_started_at, append_note=False
    )
    if not _guard["ok"]:
        print(f"[GIS] 结果真实性自检未通过: {_guard['issues'][:3]}", flush=True)

    # 一轮结束：新注册但未展示的图层 → 挂起为 pending（用户“继续/确认”即加载）
    _auto_promote_pending(
        session_id, _start_registered, [l.get("name") for l in pending.get("layers", [])]
    )

    # 结束记录落入 SQLite 台账
    _g_status = "PASS" if _guard.get("ok") else "FAIL"
    _record_run_finish(_run_id, final_text, _run_finish_status, _g_status)

    # === Token 计量基建：提取与持久化 ===
    _dur_ms = int((time.time() - _run_started_at) * 1000)
    _schema_chars = len(json.dumps([convert_to_openai_tool(t) for t in tools], ensure_ascii=False))
    _token_usage = extract_and_record_token_usage(
        messages=final_messages,
        input_message_count=len(messages),
        previous_attempts=_usage_attempts,
        model_name=cfg.model,
        task_id=_task_id,
        tool_count=len(tools),
        schema_chars=_schema_chars,
        duration_ms=_dur_ms,
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
        "result_check": _guard,
        "task_id": _task_id,
        "run_id": _run_id,
        "token_usage": _token_usage,
    }


# ============================================================
# Agent 流式执行（SSE 实时进度）
# ============================================================

def _stream_step_descriptor(tool_name: str, args: dict, user_text: str, active_web: dict | None = None) -> tuple[str, str, str]:
    """Build a compact task-step key/label from actual tool arguments and the user request."""
    args = args if isinstance(args, dict) else {}
    def clean_target(value: object) -> str:
        value = str(value or "").lower()
        value = re.sub(r"https?://|www\.", "", value)
        value = re.sub(r"[a-z0-9_-]+\.[a-z]{2,}", " ", value)
        value = re.sub(r"[，,。.!！?？:：;；()（）\[\]{}\"']+", " ", value)
        stop = ("please", "find", "search", "look up", "check", "current", "today", "weather", "forecast", "in ",
                "查询", "搜索", "网页", "天气", "预报", "现在", "今天", "请问", "帮我", "查一下", "搜一下", "看看", "获取", "的", "一下")
        for word in stop:
            value = value.replace(word, " ")
        return re.sub(r"\s+", " ", value).strip(" _-")[:56]

    def canonical_target(value: str) -> tuple[str, str]:
        aliases = (
            (("new york city", "new york", "nyc", "纽约市", "纽约"), "new-york", "纽约"),
            (("london", "伦敦"), "london", "伦敦"),
            (("united states", "usa", "us", "america", "美国"), "united-states", "美国"),
            (("changsha", "长沙"), "changsha", "长沙"),
        )
        low = value.lower()
        for forms, key, display in aliases:
            if any((form in low if any(ord(ch) > 127 for ch in form) else re.search(r"\b" + re.escape(form) + r"\b", low)) for form in forms):
                return key, display
        return value.replace(" ", "-"), value

    name = str(tool_name or "tool")
    if name in {"search_web", "fetch_webpage", "fetch_webpage_scrapling"}:
        raw_query = str(args.get("query") or "")
        target = clean_target(raw_query or args.get("url") or user_text)
        if name != "search_web" and active_web:
            key, label = active_web["key"], active_web["label"]
        else:
            target_key, target_label = canonical_target(target)
            is_weather = bool(re.search(r"weather|forecast|天气|气温|降水", raw_query, re.I))
            key = ("weather:" if is_weather else "web:") + (target_key or "request")
            label = "查询" + (target_label or "网页信息") + ("天气" if is_weather else "")
        return key, label, "web"
    if name == "fetch_weather_data":
        match = re.search(r"(?:查一下|查询|查看|获取|weather in)\s*(.+?)(?:的?天气|天气|weather|$)", user_text, re.I)
        target = clean_target(match.group(1) if match else user_text) or "指定地点"
        target_key, target_label = canonical_target(target)
        # 与同一请求中围绕该地点进行的天气搜索/网页读取归入同一任务卡。
        if active_web and active_web["key"].endswith(target_key):
            return active_web["key"], active_web["label"], "weather"
        return "weather:" + target_key, "查询" + target_label + "天气", "weather"
    if name == "focus_map":
        match = re.search(r"(?:定位到|飞到|定位)\s*([^，,。.!！?？]+)", user_text)
        target = clean_target(args.get("layer_name") or (match.group(1) if match else user_text)) or "指定位置"
        target_key, target_label = canonical_target(target)
        return "map:" + target_key, "定位" + target_label, "map"
    target = clean_target(args.get("query") or args.get("location") or args.get("layer_name") or args.get("name") or user_text)
    return name + ":" + (target or "task"), name.replace("_", " ") + (" · " + target if target else ""), name


def _stream_tool_failure(content: object) -> tuple[bool, str]:
    """Recognize explicit structured tool failures and return a concise reason."""
    value = content
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = content
    if isinstance(value, dict):
        failed = value.get("ok") is False or value.get("success") is False or value.get("is_error") is True
        failed = failed or str(value.get("status", "")).lower() in {"error", "failed", "failure"}
        if failed:
            reason = value.get("error") or value.get("message") or value.get("hint") or "工具执行失败"
            return True, str(reason).strip()[:240]
    text = str(content or "").strip()
    failed = bool(re.match(
        r"^(?:错误|失败|无法|未找到|请提供|\[[ \t]*(?:error|failed|failure|exception)[ \t]*\]|"
        r"(?:error|failed|failure|exception)\b|"
        r"[^\r\n。；;]{1,40}?(?:失败|错误|异常|未通过|未能|无法)(?=[:：,，\s]|$)|"
        r"[^\r\n.!?]{1,48}\b(?:failed|failure|error|exception)(?:[:.,\s]|$))",
        text,
        re.IGNORECASE,
    ))
    return failed, (text[:240] if failed else "")


def _stream_tool_warning(content: object) -> bool:
    """读取完整结果的部分成功标记，避免 SSE 文本截断丢失警告。"""
    value = content
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return False
    if not isinstance(value, dict):
        return False
    warning = (value.get("partial") is True or value.get("has_warning") is True
               or str(value.get("status", "")).lower() == "partial"
               or any(isinstance(value.get(key), list) and value[key] for key in ("warnings", "qa_warnings")))
    try:
        return bool(warning or float(value.get("skipped_count") or 0) > 0)
    except (TypeError, ValueError, OverflowError):
        return bool(warning)


def _workflow_progress_tool_events(payload: object, active_nodes: dict) -> list[dict]:
    """Translate Workflow custom stream events into the existing execution-card protocol."""
    if not isinstance(payload, dict) or payload.get("type") != "workflow_progress":
        return []
    detail = payload.get("event")
    if not isinstance(detail, dict):
        return []
    event_type = detail.get("type")
    if event_type not in {
        "workflow_node_started", "workflow_node_completed",
        "workflow_node_failed", "workflow_node_skipped",
    }:
        return []

    invocation_id = str(payload.get("invocation_id") or "workflow")[:80]
    node_id = str(detail.get("node_id") or "node")[:80]
    key = (invocation_id, node_id)
    node_name = str(detail.get("name") or node_id)[:120]
    tool_name = str(detail.get("tool") or "workflow_node")[:100]
    workflow_name = str(payload.get("workflow_name") or "工作流")[:120]
    step_label = f"{workflow_name} · {node_name}"[:180]
    result = []
    call = active_nodes.get(key)

    if event_type == "workflow_node_started":
        if call:
            return []
        call = {
            "tool_call_id": "workflow-node-" + uuid.uuid4().hex[:16],
            "step_id": "workflow-step-" + uuid.uuid4().hex[:16],
            "step_label": step_label,
            "name": tool_name,
        }
        active_nodes[key] = call
        return [{
            "type": "tool_start", **call,
            "input": json.dumps({"workflow_node": node_name, "tool": tool_name}, ensure_ascii=False),
        }]

    if call is None:
        # Validation failures and skipped nodes may have no started event.
        call = {
            "tool_call_id": "workflow-node-" + uuid.uuid4().hex[:16],
            "step_id": "workflow-step-" + uuid.uuid4().hex[:16],
            "step_label": step_label,
            "name": tool_name,
        }
        active_nodes[key] = call
        result.append({
            "type": "tool_start", **call,
            "input": json.dumps({"workflow_node": node_name, "tool": tool_name}, ensure_ascii=False),
        })
    else:
        tool_name = call["name"]

    active_nodes.pop(key, None)
    error = str(detail.get("error") or "")[:500]
    if event_type == "workflow_node_failed":
        result.append({
            "type": "tool_end", **call, "output": error or "工作流节点执行失败",
            "status": "error", "is_error": True,
            "error_message": error or "工作流节点执行失败",
        })
    elif event_type == "workflow_node_skipped":
        if "上游" in error:
            skip_output = "未执行：依赖的上游节点未完成"
        elif "校验" in error or "未通过" in error:
            skip_output = "未执行：工作流结构校验条件未满足"
        else:
            skip_output = error or "工作流节点未执行"
        result.append({
            "type": "tool_end", **call, "output": skip_output,
            "status": "partial", "has_warning": True,
        })
    else:
        result.append({
            "type": "tool_end", **call, "output": "工作流节点已完成",
            "status": "success", "is_error": False,
        })
    return result


def _run_agent_stream_impl(
    messages: list,
    cfg: LLMConfig,
    amap_key: str = "",
    skill_text: str = "",
    original_message: str = "",
    session_id: str = "default",
    mode: str = "full",
    read_only_location_analysis: bool = False,
    task_id: str = None,
    request_id: str = None,
    run_context: dict | None = None,
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
    from backend.services.privacy_service import session_protected, run_private_agent
    if session_protected(session_id):
        yield 'data: ' + json.dumps({"type": "thinking", "privacy_mode": True}) + '\n\n'
        result = run_private_agent(original_message, session_id, cfg, request_id,
                                   read_only=read_only_location_analysis)
        yield 'data: ' + json.dumps({"type": "done", **result}, ensure_ascii=False) + '\n\n'
        return
    reset_state(amap_key)
    available_tools = _tools_for_request(read_only_location_analysis)
    _tools_mod.set_last_user_message(original_message or "")
    # 提取最近多轮上下文（供工具层消歧与实体复用）
    _ctx_texts = []
    for _m in (messages or [])[-10:]:
        _c = getattr(_m, "content", "")
        if isinstance(_c, str) and _c.strip():
            _ctx_texts.append(_c.strip())
    _tools_mod.set_conversation_context("\n".join(_ctx_texts))
    pending_action.set_active_session(session_id or "default")
    _start_registered = set(getattr(_tools_mod, "_registered_layers", {}).keys())
    _stream_step_ids: dict[str, str] = {}
    _stream_call_steps: dict[str, dict] = {}
    _stream_active_web: dict | None = None
    _streamed_layer_op_ids: set[str] = set()
    # 捕获本次请求的取消代次；有 request_id 时不清理其他请求的取消标志。
    import backend.services.ai_service as _ai_svc
    _cancel_generation = _ai_svc.clear_session_cancel(session_id or "default", request_id)
    llm = build_llm(cfg)
    # 流式总预算：与非流式 _GRAPH_TOTAL_TIMEOUT_S 一致
    _stream_budget_deadline = _time_mod.monotonic() + _GRAPH_TOTAL_TIMEOUT_S

    # === Task Manager 与 SQLite 台账: 解析/创建任务与运行轮次 ===
    _run_started_at = time.time()
    _run_id = uuid.uuid4().hex[:12]
    _tools_mod.set_current_run(_run_id)
    _task_id = task_manager.find_or_create_task(session_id or "default", original_message or "", task_id=task_id)
    set_current_task(_task_id)
    print(f"[GIS] 流式 run_id={_run_id} Task ID: {_task_id} mode={mode}", flush=True)

    try:
        from backend.services import storage_service
        storage_service.record_run_start(_run_id, session_id or "default", original_message or "", _task_id)
    except Exception:
        pass
    if run_context is not None:
        run_context["run_id"] = _run_id
        run_context["finished"] = False
    _run_finish_status = "success"

    # 简单问题快速 bypass（A+ 优化：精简 prompt + 去掉易误判词）
    _simple = not _should_use_agent(messages, session_id)
    if _simple:
        try:
            # Keep the synchronous SDK call off the SSE consumer thread so a
            # cancel can be observed while the provider is still responding.
            def _invoke_simple_model():
                yield llm.invoke(messages)

            _resp = None
            for _simple_result in _stream_with_deadline(
                _invoke_simple_model(),
                _stream_budget_deadline,
                lease=getattr(_AGENT_LOCK_LEASE, "current", None),
                cancel_check=lambda: _ai_svc.is_session_cancelled(
                    session_id or "default", request_id, _cancel_generation
                ),
            ):
                if _simple_result is _STREAM_CANCELLED:
                    _record_run_finish(_run_id, "用户已取消", "cancelled")
                    if run_context is not None:
                        run_context["finished"] = True
                    yield f"data: {json.dumps({'type': 'cancelled', 'message': '用户取消了请求'})}\n\n"
                    return
                _resp = _simple_result
        except Exception:
            _record_run_finish(_run_id, "AI 回复失败", "error")
            if run_context is not None:
                run_context["finished"] = True
            raise
        _quick_text = _clean_ai_text(_resp.content or "")
        if _looks_like_incomplete_promise(_quick_text):
            # 快路径不带任何工具：模型只是"口头承诺去获取/生成"时必须改走 Agent
            print("[GIS] 流式快路径命中空口承诺，改走 Agent 工具通道", flush=True)
            _simple = False
        else:
            try:
                _record_run_finish(_run_id, _quick_text, "success", "BYPASS")
            except Exception:
                pass
            if run_context is not None:
                run_context["finished"] = True
            yield "data: {\"type\":\"thinking\"}\n\n"
            result = {
                "response": _quick_text or "模型本轮没有返回可见答复，请重试。",
                "reasoning": get_message_reasoning(_resp),
                "layers": [], "images": [], "heatmap": None,
                "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
                "confirm_pending": None,  # 与非流式 run_agent 返回结构保持一致，便于前端统一处理
            }
            yield "data: " + json.dumps({"type": "done", **result}, ensure_ascii=False) + "\n\n"
            return

    try:
        agent = create_react_agent(llm, available_tools)
    except Exception:
        _record_run_finish(_run_id, "Agent 初始化失败", "error")
        if run_context is not None:
            run_context["finished"] = True
        raise

    # 预算用：本轮工具 schema 字符数（粗估，不重复 JSON 序列化）
    try:
        _schema_chars_est = len(json.dumps([convert_to_openai_tool(t) for t in available_tools], ensure_ascii=False))
    except Exception:
        _schema_chars_est = 60000

    _usage_attempts = []
    _ai_waiting_choice = False  # 初始化，防止 stream 提前异常/空流时 L1021 引用未定义变量
    try:
        msgs = []  # 初始化，防止空流时后续结果整理引用未定义变量
        _workflow_node_calls = {}
        for _stream_item in _stream_with_deadline(
            agent.stream(
                {"messages": messages},
                {"recursion_limit": 120},
                stream_mode=["values", "custom"],
            ),
            _stream_budget_deadline,
            lease=getattr(_AGENT_LOCK_LEASE, "current", None),
            cancel_check=lambda: _ai_svc.is_session_cancelled(
                session_id or "default", request_id, _cancel_generation
            ),
        ):
            if _stream_item is _STREAM_CANCELLED:
                _record_run_finish(_run_id, "用户已取消", "cancelled")
                if run_context is not None:
                    run_context["finished"] = True
                yield f"data: {json.dumps({'type': 'cancelled', 'message': '用户取消了请求'})}\n\n"
                return
            _stream_channel = None
            step = _stream_item
            if (isinstance(_stream_item, tuple) and len(_stream_item) == 2
                    and isinstance(_stream_item[0], str)):
                _stream_channel, step = _stream_item
            # 每次循环检查是否被取消
            if _ai_svc.is_session_cancelled(session_id or "default", request_id, _cancel_generation):
                _record_run_finish(_run_id, "用户已取消", "cancelled")
                if run_context is not None:
                    run_context["finished"] = True
                yield f"data: {json.dumps({'type': 'cancelled', 'message': '用户取消了请求'})}\n\n"
                return

            if _stream_channel == "custom":
                for _progress_event in _workflow_progress_tool_events(step, _workflow_node_calls):
                    yield "data: " + json.dumps(_progress_event, ensure_ascii=False) + "\n\n"
                continue
            if _stream_channel not in (None, "values"):
                continue

            # --- 上下文膨胀兜底 3：累计输入 token 预算（早于 420s 触发）---
            # 只按字符粗估（1 token ~ 2-3 字符，取保守 3），避免额外依赖
            if GRAPH_TOKEN_BUDGET > 0:
                try:
                    _est = sum(len(str(getattr(_m, "content", "") or "")) for _m in (msgs or []))
                    _est = int(_est / 3) + int(_schema_chars_est / 3)
                except Exception:
                    _est = 0
                if _est > GRAPH_TOKEN_BUDGET:
                    print(f"[GIS] 累计输入约 {_est} token 超预算 {GRAPH_TOKEN_BUDGET}，强制收尾", flush=True)
                    try:
                        _b_llm = build_llm(disable_reasoning(cfg))
                        _b_rep = _b_llm.invoke(
                            list(msgs) + [HumanMessage(content="请停止调用任何工具，直接用文字总结最终结果（可引用前面已经完成的数据/图层）。")],
                            max_tokens=800,
                        )
                        _b_text = (_b_rep.content or "").strip()
                    except Exception:
                        _b_text = ""
                    if not _b_text:
                        _b_text = ("上下文已达上限（累计输入约 %d token），已自动停止以避免无效消耗。"
                                   "\\n\\n请基于本轮已生成的图层/数据继续操作，或把任务拆成更小的步骤重试。" % _est)
                    msgs.append(AIMessage(content=_b_text))
                    break

            # 总时长预算检查（与非流式 run_agent 相同的 420s 预算）：
            # 流式 path 之前完全无预算，模型陷入「调工具失败再调」可无限烧 token
            if _time_mod.monotonic() > _stream_budget_deadline:
                print(f"[GIS] 流式总时长超预算（{_GRAPH_TOTAL_TIMEOUT_S:.0f}s），强制收尾", flush=True)
                try:
                    _budget_llm = build_llm(disable_reasoning(cfg))
                    _budget_reply = _budget_llm.invoke(
                        list(msgs) + [HumanMessage(content="请停止调用任何工具，直接用文字总结最终结果（可引用前面已经完成的数据/图层）。")],
                        max_tokens=800,
                    )
                    _budget_text = (_budget_reply.content or "").strip()
                except Exception:
                    _budget_text = ""
                if _budget_text:
                    msgs.append(AIMessage(content=_budget_text))
                else:
                    _budget_text = "任务执行时长已达上限（约 %.0f 秒），已自动停止以避免无效消耗。\n\n请基于本轮已生成的图层/数据继续操作，或把任务拆分成更小的步骤后重试。" % _GRAPH_TOTAL_TIMEOUT_S
                    msgs.append(AIMessage(content=_budget_text))
                break  # 跳出 stream 循环，走正常收尾（done 事件照常发）

            msgs = step.get("messages", [])
            if not msgs:
                continue
            _usage_attempts.append(list(msgs))
            # --- 上下文膨胀兜底 1：截断过大的工具结果 ---
            if GRAPH_TOOL_OUT_MAX_CHARS > 0:
                for _m in msgs:
                    _is_tool = getattr(_m, "type", "") == "tool" or hasattr(_m, "tool_call_id")
                    if _is_tool:
                        _c = getattr(_m, "content", "") or ""
                        if isinstance(_c, str) and len(_c) > GRAPH_TOOL_OUT_MAX_CHARS:
                            try:
                                _m.content = _trim_text(_c, GRAPH_TOOL_OUT_MAX_CHARS)
                            except Exception:
                                pass
            # --- 上下文膨胀兜底 2：压缩较早的工具结果 ---
            msgs = _compact_messages(msgs)
            last = msgs[-1]

            # DEBUG: 打印最后一条消息的类型和内容
            _debug_msg_type = type(last).__name__
            _debug_has_tool_calls = hasattr(last, 'tool_calls') and bool(getattr(last, 'tool_calls', None))
            _debug_content_preview = str(getattr(last, 'content', ''))[:100] if hasattr(last, 'content') else 'N/A'
            print(f"[GIS DEBUG] Step msg: type={_debug_msg_type}, has_tool_calls={_debug_has_tool_calls}, content={_debug_content_preview}", flush=True)

            # AI 调用了工具
            if isinstance(last, AIMessage) and last.tool_calls:
                for tc in last.tool_calls:
                    _tool_name = tc.get("name", "?")
                    _tool_args = tc.get("args", {}) if isinstance(tc.get("args"), dict) else {}
                    _step_key, _step_label, _step_kind = _stream_step_descriptor(
                        _tool_name, _tool_args, original_message or "", _stream_active_web
                    )
                    if _step_key not in _stream_step_ids:
                        _stream_step_ids[_step_key] = "step-" + uuid.uuid4().hex[:12]
                    _step_id = _stream_step_ids[_step_key]
                    if _step_kind == "web":
                        _stream_active_web = {"key": _step_key, "label": _step_label, "step_id": _step_id}
                    _call_id = str(tc.get("id") or ("legacy-" + uuid.uuid4().hex[:12]))
                    _stream_call_steps[_call_id] = {"step_id": _step_id, "step_label": _step_label, "name": _tool_name, "args": _tool_args}
                    event = json.dumps({
                        "type": "tool_start",
                        "name": _tool_name,
                        "input": json.dumps(_tool_args, ensure_ascii=False, default=str)[:1200],
                        "tool_call_id": _call_id,
                        "step_id": _step_id,
                        "step_label": _step_label,
                        "map_ops_pending": 1 if _tool_name == "focus_map" else 0,
                    }, ensure_ascii=False)
                    yield f"data: {event}\n\n"

            # 工具返回结果
            elif hasattr(last, "name") and last.name and hasattr(last, "content"):
                _call_id = str(getattr(last, "tool_call_id", "") or "")
                _call_meta = _stream_call_steps.pop(_call_id, None)
                if _call_meta is None:
                    _step_key, _step_label, _step_kind = _stream_step_descriptor(last.name, {}, original_message or "", _stream_active_web)
                    if _step_key not in _stream_step_ids:
                        _stream_step_ids[_step_key] = "step-" + uuid.uuid4().hex[:12]
                    _call_meta = {"step_id": _stream_step_ids[_step_key], "step_label": _step_label, "name": last.name}
                _tool_output = str(last.content)
                _content_error, _error_message = _stream_tool_failure(last.content)
                _tool_error = getattr(last, "status", None) == "error" or _content_error
                event = json.dumps({
                    "type": "tool_end",
                    "name": last.name,
                    "output": _tool_output[:1200],
                    "tool_call_id": _call_id,
                    "step_id": _call_meta["step_id"],
                    "step_label": _call_meta["step_label"],
                    "status": "error" if _tool_error else "success",
                    "is_error": _tool_error,
                    "has_warning": _stream_tool_warning(last.content),
                    "error_message": _error_message if _tool_error else "",
                }, ensure_ascii=False)
                yield f"data: {event}\n\n"
                # 让 focus_map 等地图操作在当前工具返回后立即应用；done 仍携带原操作并由前端按 _stream_id 去重。
                _pending_ops = getattr(_tools_mod, "_pending_layer_ops", []) if last.name == "focus_map" else []
                _delta_ops = []
                _focus_args = _call_meta.get("args", {})
                _focus_center = None
                if _focus_args.get("center"):
                    try:
                        _parts = str(_focus_args["center"]).replace("，", ",").split(",")
                        _focus_center = [float(_parts[0].strip()), float(_parts[1].strip())]
                    except (ValueError, IndexError):
                        pass
                for _op in _pending_ops:
                    if not isinstance(_op, dict) or _op.get("action") not in {"center", "fit"}:
                        continue
                    if _op.get("_stream_id"):
                        continue
                    if _op.get("action") == "center" and _focus_center != _op.get("center"):
                        continue
                    if _op.get("action") == "fit":
                        _requested_layer = str(_focus_args.get("layer_name") or "")
                        _resolved_layer = str(_op.get("name") or "")
                        if not (_resolved_layer == _requested_layer or _requested_layer in _resolved_layer or _resolved_layer in _requested_layer):
                            continue
                    _op["_stream_id"] = "op-" + uuid.uuid4().hex[:12]
                    _op["_step_id"] = _call_meta["step_id"]
                    _delta_ops.append(dict(_op))
                    _streamed_layer_op_ids.add(_op["_stream_id"])
                if _delta_ops:
                    _delta_evt = json.dumps({"type": "layer_ops_delta", "step_id": _call_meta["step_id"],
                                             "step_label": _call_meta["step_label"], "layer_ops": _delta_ops}, ensure_ascii=False)
                    yield f"data: {_delta_evt}\n\n"
                # ask_user_choice 已弹出选项：立即停止 agent 循环，
                # 等用户选择后走下一轮（防 LLM 拿到"等待选择"文本后继续乱跑）
                if "[WAITING_USER_CHOICE]" in str(last.content or ""):
                    _wait_evt = json.dumps({"type": "waiting_choice", "step_id": _call_meta["step_id"],
                                            "step_label": _call_meta["step_label"]}, ensure_ascii=False)
                    yield f"data: {_wait_evt}\n\n"
                    print("[GIS] 检测到 ask_user_choice 弹出选项，停止本轮 agent 循环", flush=True)
                    _ai_waiting_choice = True
                    break

            # AI 正在思考（没有 tool_calls）
            elif isinstance(last, AIMessage) and last.content:
                yield "data: {\"type\":\"thinking\"}\n\n"

    except Exception as e:
        import traceback
        traceback.print_tb(e.__traceback__)
        _safe_err_str = _safe_model_error(e, cfg)
        print(f"[GIS] 流式模型请求异常: {_safe_err_str[:300]}", flush=True)
        _budget_timeout = isinstance(e, TimeoutError) and "budget exceeded" in str(e).lower()
        if _budget_timeout:
            _run_finish_status = "timeout"
        # 框架角例容错：StructuredTool 被当普通函数调用的偶发 TypeError →
        # 自动“纯文本收尾”一次（保留前面已产出的图层），尽量不让整轮失败。
        if _tool_not_callable(e):
            try:
                _fb_text = _recover_tool_dispatch_text(cfg, messages)
            except Exception:
                _fb_text = ""
            if _fb_text:
                print("[GIS] 工具调度 TypeError，流式纯文本收尾", flush=True)
                msgs.append(AIMessage(content=_fb_text))
            else:
                _run_finish_status = "error"
                event = json.dumps({"type": "error", "message": _safe_err_str}, ensure_ascii=False)
                yield f"data: {event}\n\n"
        else:
            _err_str = _safe_err_str
            # --- 服务端临时故障兜底：流式路径对 5xx/断连等整轮重试一次 ---
            # 背景：非流式 path 有 _is_temp 重试，流式没有；服务端（如 DeepSeek）
            # 间歇性崩溃时，第一次 stream 中途断流，重试往往即可恢复。
            _err_lower0 = _err_str.lower()
            _is_temp_stream = (not _budget_timeout) and any(k in _err_lower0 for k in [
                "timeout", "timed out", "connection", "502", "503", "504",
                "rate limit", "429", "temporarily", "server error",
                "api connection", "network", "reset by peer", "internal server",
                "overloaded", "bad gateway", "service unavailable",
            ])
            # 从原始输入整轮重试会重放此前已经运行过的 GIS 工具，可能重复导出、
            # 写入图层或访问外部服务。只有尚未产生任何工具调用/结果时才安全重试。
            _attempt_has_tool_activity = _count_tool_calls(msgs) > 0 or _has_tool_messages(msgs)
            if (_is_temp_stream and not _attempt_has_tool_activity
                    and not _ai_svc.is_session_cancelled(session_id or "default", request_id, _cancel_generation)):
                _retry_ok = False
                try:
                    print("[GIS] 流式遇到临时性服务端异常，整轮重试一次: " + _err_str[:100], flush=True)
                    import time as _rt; _rt.sleep(1.5)
                    _retry_status, _retry_res = _invoke_agent_with_budget(
                        agent, {"messages": list(messages)}, 60,
                        max(0.0, _stream_budget_deadline - _time_mod.monotonic()),
                        cancel_check=lambda: _ai_svc.is_session_cancelled(
                            session_id or "default", request_id, _cancel_generation
                        ),
                    )
                    if _retry_status == "cancelled":
                        _record_run_finish(_run_id, "用户已取消", "cancelled")
                        if run_context is not None:
                            run_context["finished"] = True
                        yield f"data: {json.dumps({'type': 'cancelled', 'message': '用户取消了请求'})}\n\n"
                        return
                    if _retry_status != "ok":
                        raise _retry_res
                    _rm = _retry_res.get("messages", [])
                    if _rm:
                        _r_text, _r_reason = _last_ai_text(_rm)
                        if _r_text:
                            msgs = _rm
                            _retry_ok = True
                            event = json.dumps({"type": "note", "message": "服务端临时故障已自动重试成功。"}, ensure_ascii=False)
                            yield f"data: {event}\n\n"
                except Exception as _re:
                    _safe_retry_error = _safe_model_error(_re, cfg)
                    print("[GIS] 流式重试仍失败: " + _safe_retry_error[:100], flush=True)
                    _err_str = _safe_retry_error
                if _retry_ok:
                    # 跳过错误上报，走正常收尾（msgs 已是重跑结果）
                    _final2, _r2 = "", None
                    try:
                        _final2, _r2 = _last_ai_text(msgs)
                    except Exception:
                        pass
                    if _final2:
                        event = json.dumps({"type": "partial", "text": _final2}, ensure_ascii=False)
                        yield f"data: {event}\n\n"
                    # 直接跳到收尾段（复用下方 done 逻辑）：以一个跳标记完成
                    _stream_retry_done = True
                else:
                    _stream_retry_done = False
            else:
                _stream_retry_done = False
            if not _stream_retry_done:
                if not _budget_timeout:
                    _run_finish_status = "error"
                if "402" in _err_str or "Insufficient Balance" in _err_str:
                    _err_str = "API 余额不足（402），请充值或在设置中更换有余额的 API Key 后重试。"
                elif "401" in _err_str or "invalid_api_key" in _err_str:
                    _err_str = "API Key 无效或已过期（401），请在设置中检查 API Key 配置。"
                elif "429" in _err_str or "rate_limit" in _err_str:
                    _err_str = "API 请求频率超限（429），请稍后重试。"
                elif "timeout" in _err_str.lower():
                    _err_str = "API 请求超时，请检查网络连接或稍后重试。"
                event = json.dumps({"type": "error", "message": _err_str})
                yield f"data: {event}\n\n"

    # 收集最终结果
    pending = get_pending_state()
    # layer_ops 引用但未推送的注册图层 → 补推进 done，防止前端「未找到图层」
    _ensure_ops_layers_present(pending)
    # ask_user_choice 弹选项导致 break：msgs 尾部是 ToolMessage 而无 AIMessage，
    # 补一条收尾消息，让 _last_ai_text / done 事件正常工作
    if _ai_waiting_choice and (not msgs or not isinstance(msgs[-1], AIMessage)):
        msgs.append(AIMessage(content="已向用户弹出选项，请点击选择后继续。"))
    final_text, final_reasoning = "", None
    try:
        final_text, final_reasoning = _last_ai_text(msgs)
    except Exception:
        pass

    # 流式模型有时只返回 reasoning 或空正文，ReAct 因而没有发出工具调用；收尾前自动按原请求重试。
    if (not final_text and not _ai_waiting_choice
            and not _has_tool_messages(msgs) and _count_tool_calls(msgs) == 0):
        print(f"[GIS] 流式空响应且没有工具调用（{_empty_response_diagnostic(msgs)}），关闭推理并强制调用工具重试", flush=True)
        note = json.dumps({"type": "note", "message": "本轮没有收到可见答复，正在按原请求自动重试。"}, ensure_ascii=False)
        yield f"data: {note}\n\n"
        try:
            _retry = _invoke_empty_response_recovery(
                agent, messages, recursion_limit=60, cfg=cfg, available_tools=available_tools,
                timeout_s=max(0.0, _stream_budget_deadline - _time_mod.monotonic()),
                cancel_check=lambda: _ai_svc.is_session_cancelled(
                    session_id or "default", request_id, _cancel_generation
                ))
            if _retry is _STREAM_CANCELLED:
                _record_run_finish(_run_id, "用户已取消", "cancelled")
                if run_context is not None:
                    run_context["finished"] = True
                yield f"data: {json.dumps({'type': 'cancelled', 'message': '用户取消了请求'})}\n\n"
                return
            _retry_msgs = _retry.get("messages", [])
            _usage_attempts.append(list(_retry_msgs))
            _retry_text, _retry_reasoning = _last_ai_text(_retry_msgs)
            _retry_tools = _count_tool_calls(_retry_msgs) > 0 or _has_tool_messages(_retry_msgs)
            if _retry_text:
                msgs = _retry_msgs
                final_text, final_reasoning = _retry_text, _retry_reasoning
            elif _retry_tools:
                msgs = _retry_msgs
                final_text = _tool_result_fallback(_retry_msgs)

            if _retry_tools:
                # 恢复调用在主流循环之后运行，仍把真实工具调用和结果记录到前端。
                _retry_step_ids = {}
                _retry_call_steps = {}
                for _retry_msg in _retry_msgs:
                    if isinstance(_retry_msg, AIMessage) and _retry_msg.tool_calls:
                        for _tc in _retry_msg.tool_calls:
                            _tool_name = _tc.get("name", "?")
                            _tool_args = _tc.get("args", {}) if isinstance(_tc.get("args"), dict) else {}
                            _step_key, _step_label, _step_kind = _stream_step_descriptor(
                                _tool_name, _tool_args, original_message or "", _stream_active_web
                            )
                            _step_id = _retry_step_ids.setdefault(_step_key, "step-" + uuid.uuid4().hex[:12])
                            _call_id = str(_tc.get("id") or ("legacy-" + uuid.uuid4().hex[:12]))
                            _retry_call_steps[_call_id] = (_step_id, _step_label, _tool_name)
                            event = json.dumps({
                                "type": "tool_start", "name": _tool_name, "input": json.dumps(_tool_args, ensure_ascii=False, default=str)[:1200],
                                "tool_call_id": _call_id, "step_id": _step_id, "step_label": _step_label,
                            }, ensure_ascii=False)
                            yield f"data: {event}\n\n"
                    elif isinstance(_retry_msg, ToolMessage):
                        _tool_name = getattr(_retry_msg, "name", None) or "工具"
                        _call_id = str(getattr(_retry_msg, "tool_call_id", "") or "")
                        _step_id, _step_label, _ = _retry_call_steps.pop(_call_id, ("", "", _tool_name))
                        if not _step_id:
                            _step_key, _step_label, _ = _stream_step_descriptor(
                                _tool_name, {}, original_message or "", _stream_active_web
                            )
                            _step_id = _retry_step_ids.setdefault(_step_key, "step-" + uuid.uuid4().hex[:12])
                        _content_error, _error_message = _stream_tool_failure(_retry_msg.content)
                        _tool_error = getattr(_retry_msg, "status", None) == "error" or _content_error
                        event = json.dumps({
                            "type": "tool_end", "name": _tool_name,
                            "output": str(_retry_msg.content or "")[:1200],
                            "tool_call_id": _call_id,
                            "step_id": _step_id, "step_label": _step_label,
                            "status": "error" if _tool_error else "success",
                            "is_error": _tool_error,
                            "error_message": _error_message if _tool_error else "",
                            "has_warning": _stream_tool_warning(_retry_msg.content),
                        }, ensure_ascii=False)
                        yield f"data: {event}\n\n"
                pending = get_pending_state()
                _ensure_ops_layers_present(pending)
        except Exception as _re:
            print(f"[GIS] 流式空响应执行重试失败: {_re}", flush=True)
            if isinstance(_re, TimeoutError) and "budget exceeded" in str(_re).lower():
                _run_finish_status = "timeout"
                final_text = "自动恢复达到执行时限，本轮结果可能不完整；请缩小任务范围后重试。"
        if not final_text:
            final_text = "模型本轮没有生成答复，也没有实际调用工具；已自动重试但仍未完成。这次没有完成计算，请重试该请求。"
    if not final_text:
        final_text = _tool_result_fallback(msgs) or (
            "模型提出了工具调用，但工具没有返回结果；本次操作未确认完成，请检查工具记录后重试。"
            if _count_tool_calls(msgs) else
            "AI 未返回有效响应，请重试或更换模型。"
        )

    # === P0-2: 流式版本 finish_reason 检查 ===
    # 保守：对所有 AIMessage 做截断类 finish_reason 日志；仅当最后一条也截断时才提示给用户
    _any_truncation = False
    for _msg in msgs:
        if not isinstance(_msg, AIMessage):
            continue
        _fr = (_msg.response_metadata or {}).get("finish_reason", "")
        if _fr in ("length", "content_filter", "insufficient_system_resource"):
            _any_truncation = True
            break
    if _any_truncation:
        print("[GIS] 流式：存在 AIMessage 截断（length/content_filter/insufficient_system_resource），结果可能不完整。", flush=True)

    for _msg in reversed(msgs):
        if isinstance(_msg, AIMessage):
            _fr = (_msg.response_metadata or {}).get("finish_reason", "")
            if _fr == "length":
                final_text = (final_text or "") + "\n\n[注意] 回复因模型输出长度限制被截断，内容可能不完整。"
            elif _fr == "content_filter":
                final_text = (final_text or "") + "\n\n[注意] 回复因内容安全策略被部分拦截。"
            elif _fr == "insufficient_system_resource":
                final_text = (final_text or "") + "\n\n[注意] 模型服务资源不足，回复可能不完整，请稍后重试。"
            break

    # === 防“只说开始就结束”：只承诺未执行（无任何工具调用）时强制补一轮真实执行 ===
    _initial_tool_calls = _count_tool_calls(msgs)
    _initial_has_tools = _has_tool_messages(msgs)
    print(f"[GIS DEBUG] 流式初始工具调用: {_initial_tool_calls} 次, 有工具消息: {_initial_has_tools}", flush=True)
    
    _need_force_exec = _promise_without_action(final_text, msgs) or _is_unexecuted_code_or_disclaimer(final_text, msgs)
    # 每轮请求只检查一次并最多补执行一轮；状态放在局部变量中，避免相同文本的后续新请求被误拦。
    _allow_force = _need_force_exec
    if _allow_force:
        try:
            print("[GIS] 流式：检测到未执行承诺或未执行制图代码，强制补一轮真实工具执行", flush=True)
            yield "data: {\"type\":\"thinking\"}\n\n"
            _prompt_text = (
                _RECOVERY_PROMPT_CODE_DUMP
                if _is_unexecuted_code_or_disclaimer(final_text, msgs)
                else _RECOVERY_PROMPT_NO_ACTION
            )
            _forced = _invoke_empty_response_recovery(
                agent, msgs, recursion_limit=60, cfg=cfg,
                available_tools=available_tools, recovery_prompt=_prompt_text,
                timeout_s=max(0.0, _stream_budget_deadline - _time_mod.monotonic()),
                cancel_check=lambda: _ai_svc.is_session_cancelled(
                    session_id or "default", request_id, _cancel_generation
                ))
            if _forced is _STREAM_CANCELLED:
                _record_run_finish(_run_id, "用户已取消", "cancelled")
                if run_context is not None:
                    run_context["finished"] = True
                yield f"data: {json.dumps({'type': 'cancelled', 'message': '用户取消了请求'})}\n\n"
                return
            _fm = _forced.get("messages", [])
            _usage_attempts.append(list(_fm))
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
            if isinstance(_pe, TimeoutError) and "budget exceeded" in str(_pe).lower():
                _run_finish_status = "timeout"
                final_text = (final_text or "") + "\n\n【注意】自动补执行达到时限，结果可能不完整。"
    # === 正文净化：本轮已执行的 Python 源码折叠为一行，避免几百行代码盖住交付物 ===
    if _run_finish_status == "timeout":
        final_text = (final_text or "") + (
            "\n\n【超时说明】等待时限已到，底层调用无法被强制中止，后台操作仍可能继续。"
            "工作区会保持忙碌直到调用结束；请勿立即重复提交，解除忙碌后先检查已产生的结果。"
        )
    final_text = _strip_executed_code_blocks(final_text, msgs, original_message or "")

    # === 结果真实性自检（确定性：核对磁盘与内存状态，无额外 LLM 调用）===
    # 仅在后台自检并记录日志，默认不向用户端追加内部检查说明（避免误报和干扰用户）
    final_text, _guard = result_guard.apply_guard(
        final_text, pending, task_id=_task_id, run_id=_run_id, run_start_time=_run_started_at, append_note=False
    )
    if not _guard["ok"]:
        print(f"[GIS] 流式结果真实性自检未通过: {_guard['issues'][:3]}", flush=True)

    # 一轮结束：新注册但未展示的图层 → 挂起为 pending（用户“继续/确认”即加载）
    _auto_promote_pending(
        session_id, _start_registered, [l.get("name") for l in pending.get("layers", [])]
    )

    _g_status = "PASS" if _guard.get("ok") else "FAIL"
    _record_run_finish(_run_id, final_text, _run_finish_status, _g_status)
    if run_context is not None:
        run_context["finished"] = True

    # === Token 计量基建：提取与持久化 ===
    _dur_ms = int((time.time() - _run_started_at) * 1000)
    _schema_chars = len(json.dumps([convert_to_openai_tool(t) for t in available_tools], ensure_ascii=False))
    _token_usage = extract_and_record_token_usage(
        messages=msgs,
        input_message_count=len(messages),
        previous_attempts=_usage_attempts,
        model_name=cfg.model,
        task_id=_task_id,
        tool_count=len(available_tools),
        schema_chars=_schema_chars,
        duration_ms=_dur_ms,
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
        "result_check": _guard,
        "qa_warnings": pending.get("qa_warnings", []),
        "task_id": _task_id,
        "run_id": _run_id,
        "execution_status": _run_finish_status,
        "mode": "full",
        "token_usage": _token_usage,
    }
    yield "data: " + json.dumps({"type": "done", **result}, ensure_ascii=False) + "\n\n"


def run_agent_stream(
    messages: list,
    cfg: LLMConfig,
    amap_key: str = "",
    skill_text: str = "",
    original_message: str = "",
    session_id: str = "default",
    mode: str = "full",
    read_only_location_analysis: bool = False,
    task_id: str = None,
    request_id: str = None,
):
    """运行流式 Agent，并在正常结束、异常或客户端断开时释放会话锁。"""
    sid = session_id or "default"
    if not _tools_mod.acquire_session_lock(sid):
        busy_event = json.dumps({
            "type": "done",
            "response": "当前会话已有请求在处理中，请等待上一条完成后再发送新消息。",
            "reasoning": None, "layers": [], "images": [], "heatmap": None,
            "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
            "confirm_pending": None,
            "busy": True,
        }, ensure_ascii=False)
        yield f"data: {busy_event}\n\n"
        return
    if not _tools_mod.acquire_shared_state_lock(0):
        _tools_mod.release_session_lock(sid)
        busy_event = json.dumps({
            "type": "done",
            "response": "当前 GIS 工作区正在处理另一项操作，请稍后重试。",
            "reasoning": None, "layers": [], "images": [], "heatmap": None,
            "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
            "confirm_pending": None,
            "busy": True,
        }, ensure_ascii=False)
        yield f"data: {busy_event}\n\n"
        return
    import backend.services.ai_service as _cancel_service
    run_context = {}
    lease = _DeferredLockLease(lambda: (
        _cancel_service.finish_cancel_request(sid, request_id),
        _tools_mod.release_shared_state_lock(),
        _tools_mod.release_session_lock(sid),
    ))
    _cancel_service.register_cancel_request(sid, request_id)
    cancel_context_token = _cancel_service.set_request_cancel_context(sid, request_id)
    previous_lease = getattr(_AGENT_LOCK_LEASE, "current", None)
    _AGENT_LOCK_LEASE.current = lease
    try:
        yield from _run_agent_stream_impl(
            messages=messages,
            cfg=cfg,
            amap_key=amap_key,
            skill_text=skill_text,
            original_message=original_message,
            session_id=sid,
            mode=mode,
            read_only_location_analysis=read_only_location_analysis,
            task_id=task_id,
            request_id=request_id,
            run_context=run_context,
        )
    finally:
        _AGENT_LOCK_LEASE.current = previous_lease
        try:
            # Starlette can resume a sync generator in a different copied
            # Context. A token from its first iteration cannot be reset there.
            _cancel_service.reset_request_cancel_context(cancel_context_token)
        except ValueError:
            pass
        finally:
            if run_context.get("run_id") and not run_context.get("finished"):
                _record_run_finish(run_context["run_id"], "流式请求中断", "interrupted")
            lease.finish()
