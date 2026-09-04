"""
GIS WorkTable — 统一 LLM 配置与通用构造

架构目标（OpenRouter GLM-5.2 + Provider 列表化重构）：
  后端彻底去「模型名 / 提供商名」硬编码，只认一份通用 LLMConfig。
  凡 OpenAI 兼容接口都能用，加模型 = 前端 Provider 列表加一项。

LLMConfig 字段：
    base_url / model / api_key   必需（OpenAI 兼容接口三要素）
    glm_prompt: bool  用 GLM 专属 system prompt（ai_service 读）
    router:     bool  是否先跑一次技能路由（ai_service 读）
    reasoning:  bool  请求体注入 reasoning:{enabled:true}，并把
                      reasoning_content/details 抽进 assistant 消息
                      元数据、在下一轮序列化时原样塞回
    temperature / max_tokens / timeout: 可选，透传给 ChatOpenAI

兼容迁移：
    旧的 provider 字符串（deepseek/glm/deepseek-routed/glm-routed/agnes）
    不再参与任何调用 if/else；仅当请求不带 llm_config 时，
    legacy_default_cfg() 把它翻译成一份等价的内置默认 cfg，
    保证旧工程 / 旧历史仍能跑。
"""

from typing import List, Optional

from pydantic import BaseModel, field_validator

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, BaseMessage


# ============================================================
# base_url 规整 —— 全项目唯一的 URL 规则
# ============================================================

def normalize_base_url(url: str) -> str:
    """把用户填的「接口地址」规整成 OpenAI 兼容的 API 根地址。

    用户可能填三种形态，最终都会被归一成根地址：
      - 根地址       https://host/v1
      - 完整端点     https://host/v1/chat/completions
      - 重复端点     https://host/v1/chat/completions/chat/completions

    OpenAI SDK 会自动在根地址后拼 /chat/completions。若根地址里残留了
    /chat/completions，SDK 会再拼一次，产生 …/chat/completions/chat/completions
    → 404。这里把结尾的 /chat/completions 剥掉（可重复剥），只留根地址。

    这是全项目唯一一份「用户填的 base_url → 最终请求根地址」的规则：
    LLMConfig 校验、build_llm 出参、连接测试与正式聊天全部经由它，
    保证任意标准 OpenAI 兼容接口行为一致。
    """
    if not url:
        return url
    url = str(url).strip().rstrip("/")
    low = url.lower()
    suffix = "/chat/completions"
    while low.endswith(suffix):
        url = url[: -len(suffix)].rstrip("/")
        low = url.lower()
    return url


# ============================================================
# LLMConfig
# ============================================================

class LLMConfig(BaseModel):
    """一份 OpenAI 兼容模型的完整配置（前后端共享 schema）"""

    base_url: str                                  # API 根地址
    model: str                                     # 模型名
    api_key: str = ""                              # Key 仅随每次请求携带
    glm_prompt: bool = False                       # 用 GLM 专属 system prompt
    router: bool = False                           # 是否先跑技能路由
    reasoning: bool = False                        # 是否启用推理（reasoning）
    temperature: Optional[float] = None            # 缺省交给服务端默认
    max_tokens: Optional[int] = None
    timeout: Optional[float] = None                # 秒

    @field_validator("base_url")
    @classmethod
    def _strip_endpoint_suffix(cls, v: str) -> str:
        """统一入口：把 base_url 规整成根地址（见 normalize_base_url）"""
        return normalize_base_url(v)


# reasoning 存进消息元数据的键（不进最终回复正文，供前端 thinking 展示）
_REASONING_KEY = "reasoning_content"


def disable_reasoning(cfg: LLMConfig) -> LLMConfig:
    """返回一份强制关掉 reasoning 的 cfg（Verifier 保证吐纯 JSON 用）"""
    return cfg.model_copy(update={"reasoning": False})


def _reasoning_request_body(base_url: str) -> Optional[dict]:
    """根据接口根地址决定「思考开关」要往请求体塞什么（不认识的接口不塞）。

    不同 OpenAI 兼容厂商思考模式的请求参数不一样，塞错会被 400/404：
      - 智谱 bigmodel（open.bigmodel.cn）：官方文档为
          thinking: {"type": "enabled"}
        GLM-4.7-Flash / GLM-4.7 / GLM-5.2 思考模式都用这个参数。
      - openrouter / 其它 OpenAI 兼容接口：不注入（reasoner 默认会返回
        reasoning_content，我们只做抽取展示，不强塞参数以免被拒）。
    """
    if not base_url:
        return None
    if "bigmodel.cn" in base_url.lower():
        return {"thinking": {"type": "enabled"}}
    return None


# ============================================================
# Reasoning 薄适配层
# ============================================================

def _extract_reasoning(message) -> Optional[str]:
    """从 OpenAI 兼容的 message 对象里抽出 reasoning 文本。

    兼容两种形态：
      - message.reasoning_content = "……"   （字符串）
      - message.reasoning_details = [{"type":"text","content":"……"}, ...]
    """
    if message is None:
        return None
    try:
        if hasattr(message, "reasoning_content"):
            rc = message.reasoning_content
            if isinstance(rc, str) and rc.strip():
                return rc
        if hasattr(message, "reasoning_details"):
            rd = message.reasoning_details
            return _join_reasoning_details(rd)
        # dict 形态（部分兼容端点以 dict 返回）
        if isinstance(message, dict):
            rc = message.get("reasoning_content") or message.get("reasoning")
            if isinstance(rc, str) and rc.strip():
                return rc
            rd = message.get("reasoning_details")
            if rd is not None:
                return _join_reasoning_details(rd)
    except Exception:
        pass
    return None


def _join_reasoning_details(rd) -> Optional[str]:
    if isinstance(rd, str):
        return rd if rd.strip() else None
    if isinstance(rd, dict):
        c = rd.get("content")
        return c if isinstance(c, str) and c.strip() else None
    if isinstance(rd, (list, tuple)):
        parts = []
        for item in rd:
            if isinstance(item, dict):
                c = item.get("content") or item.get("text")
            else:
                c = getattr(item, "content", None) or getattr(item, "text", None)
            if isinstance(c, str) and c.strip():
                parts.append(c)
        return "\n".join(parts) if parts else None
    return None


class ReasoningChatOpenAI(ChatOpenAI):
    """ChatOpenAI 薄适配层：reasoning/thinking 的注入 ↔ 抽取 ↔ 回传。

    不用 langchain-openai 原生 reasoning 字段（那个会触发 Responses API 路径，
    glm / openrouter 这类 chat/completions 接口用不了），只在 chat/completions
    请求体上做手脚：
      1) 请求：cfg.reasoning 开启时，按接口类型注入思考开关
               （智谱 bigmodel → thinking:{"type":"enabled"}，见
               _reasoning_request_body；其它接口不注入，避免被拒）
      2) 响应：_create_chat_result 把 reasoning_content/details 抽进
               AIMessage.additional_kwargs["reasoning_content"]
               （不进 content，正文保持干净）
      3) 回传：_get_request_payload 序列化 assistant 消息回上游时，把上一步
               存下的 reasoning_content 原样塞回 assistant 体
               （GLM 思考模型在工具循环续推时需要它）
    """

    # 是否在请求体注入思考开关（不走 self.reasoning 字段，见类 docstring）
    _inject_reasoning = False

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        try:
            raw = response
            message_obj = None
            if isinstance(raw, dict):
                choices = raw.get("choices") or []
                if choices:
                    message_obj = choices[0].get("message")
            else:
                choices = getattr(raw, "choices", None)
                if choices:
                    message_obj = choices[0].message
            reasoning = _extract_reasoning(message_obj)
            if reasoning:
                for gen in result.generations:
                    msg = gen.message
                    if isinstance(msg, AIMessage):
                        msg.additional_kwargs.setdefault(_REASONING_KEY, reasoning)
        except Exception:
            pass
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # 只在 chat/completions 路径（payload 带 messages）注入思考开关
        if getattr(self, "_inject_reasoning", False) and isinstance(payload.get("messages"), list):
            body = _reasoning_request_body(getattr(self, "openai_api_base", ""))
            if body:
                payload.update(body)
        serialized = payload.get("messages")
        if not isinstance(serialized, list) or not serialized:
            return payload
        # 响应走 chat/completions 时 messages 与输入消息一一对应
        input_messages: List[BaseMessage] = self._convert_input(input_).to_messages()
        for lc_msg, body in zip(input_messages, serialized):
            if isinstance(lc_msg, AIMessage) and isinstance(body, dict):
                rc = lc_msg.additional_kwargs.get(_REASONING_KEY)
                if rc not in (None, ""):
                    body[_REASONING_KEY] = rc
        return payload


def get_message_reasoning(message: BaseMessage) -> Optional[str]:
    """读回某条消息上存的 reasoning 文本（跑完 agent 后取来展示）"""
    if isinstance(message, AIMessage):
        rc = message.additional_kwargs.get(_REASONING_KEY)
        return rc if isinstance(rc, str) and rc else None
    return None


# ============================================================
# build_llm —— 通用构造
# ============================================================

def build_llm(cfg: LLMConfig) -> ChatOpenAI:
    """按 LLMConfig 构造 ChatOpenAI（恒用适配子类，reasoning 开则注入请求体）

    - cfg.reasoning True  → 请求体注入 reasoning:{enabled:true}
    - 不注入也会抽取响应里的 reasoning_content/details（有些思考模型不传参
      也会吐思考，仍能展示 & 跨轮回传）
    """
    kwargs = {
        "model": cfg.model,
        "api_key": cfg.api_key,
        "base_url": cfg.base_url,
    }
    # 思考模型通常不允许 temperature；仅在用户显式给时传
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    if cfg.max_tokens is not None:
        kwargs["max_tokens"] = cfg.max_tokens
    if cfg.timeout is not None:
        kwargs["timeout"] = cfg.timeout

    llm = ReasoningChatOpenAI(**kwargs)
    if cfg.reasoning:
        llm._inject_reasoning = True
    return llm


# ============================================================
# 迁移期：旧 provider 字符串 → 内置默认 cfg
# ============================================================

_LEGACY_DEFAULTS: dict = {
    "deepseek": dict(
        base_url="https://api.deepseek.com", model="deepseek-chat",
        temperature=0.7, max_tokens=2048),
    "deepseek-routed": dict(
        base_url="https://api.deepseek.com", model="deepseek-chat",
        router=True, temperature=0.7, max_tokens=2048),
    "glm": dict(
        base_url="https://open.bigmodel.cn/api/paas/v4/", model="glm-4.7-flash",
        glm_prompt=True, temperature=0.7),
    "glm-routed": dict(
        base_url="https://open.bigmodel.cn/api/paas/v4/", model="glm-4.7-flash",
        glm_prompt=True, router=True, temperature=0.7),
    "agnes": dict(
        base_url="https://apihub.agnes-ai.com/v1", model="agnes-2.0-flash",
        router=True, temperature=0.7, max_tokens=4096, timeout=60),
    # 顶层 openrouter 兜底：模型名由 api_key 携带时的 deepseek-chat 形态
    "openrouter": dict(
        base_url="https://openrouter.ai/api/v1", model="deepseek/deepseek-chat",
        temperature=0.7),
}


def legacy_default_cfg(provider: str = "", api_key: str = "") -> LLMConfig:
    """旧工程不带 llm_config 时，按 provider 名字翻译成内置默认 cfg"""
    defaults = _LEGACY_DEFAULTS.get(provider or "", _LEGACY_DEFAULTS["deepseek"])
    return LLMConfig(api_key=api_key or "", **defaults)


def resolve_llm_config(
    llm_config: Optional[LLMConfig] = None,
    provider: str = "",
    api_key: str = "",
) -> LLMConfig:
    """请求入口归一：有 llm_config 用它的，否则用旧 provider 翻译一份。

    Key 优先取 llm_config 里的；空则回填请求带的 api_key（随请求即用即弃）。
    """
    if llm_config is None:
        return legacy_default_cfg(provider, api_key)
    cfg = llm_config.model_copy(deep=True)
    if not cfg.api_key:
        cfg.api_key = api_key or ""
    return cfg
