# -*- coding: utf-8 -*-
"""
LLMConfig 统一配置层测试（不打真实 API，全部本地 mock）

覆盖：
- build_llm 构造断言（model/base_url/key/temperature/max_tokens/timeout 透传，
  reasoning 开关 → ReasoningChatOpenAI 且只在 chat/completions 请求体注入）
- reasoning 解析 ↔ 回传闭环（mock 响应，验证正文干净 + 思考抽走 + 原样塞回）
- ai_service._build_system_content 按 glm_prompt / router 开关选提示词 / 路由
- 迁移：legacy_default_cfg / resolve_llm_config（旧 provider 字符串 → 内置默认 cfg）
- 通用 /api/test-key：入参即 cfg，旧只传 provider+api_key 也能映射
"""
import json

import pytest

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from backend.services.llm_config import (
    LLMConfig,
    build_llm,
    resolve_llm_config,
    legacy_default_cfg,
    ReasoningChatOpenAI,
    disable_reasoning,
    get_message_reasoning,
    normalize_base_url,
)


# ============================================================
# build_llm 构造断言
# ============================================================

def test_build_llm_plain_propagates_fields():
    cfg = LLMConfig(
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        api_key="sk-abc",
        temperature=0.7,
        max_tokens=2048,
        timeout=30,
    )
    llm = build_llm(cfg)
    assert isinstance(llm, ChatOpenAI)
    assert isinstance(llm, ReasoningChatOpenAI)
    assert llm._inject_reasoning is False   # 未开 reasoning 不注入请求体
    assert llm.model_name == "deepseek-chat"
    assert llm.openai_api_base == "https://api.deepseek.com"
    assert llm.openai_api_key.get_secret_value() == "sk-abc"
    assert llm.temperature == 0.7
    assert llm.max_tokens == 2048
    assert llm.request_timeout == 30
    assert llm.reasoning is None


def test_build_llm_reasoning_injects_zhipu_thinking():
    """智谱 bigmodel：思考开关按官方文档注入 thinking:{type:enabled}"""
    cfg = LLMConfig(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4.7-flash",
        api_key="glm-x",
        reasoning=True,
    )
    llm = build_llm(cfg)
    assert isinstance(llm, ReasoningChatOpenAI)
    # 不设置原生 reasoning 字段，避免触发 Responses API 路径
    assert llm.reasoning is None
    payload = llm._get_request_payload([HumanMessage(content="hi")])
    assert "messages" in payload
    assert payload["thinking"] == {"type": "enabled"}
    assert "reasoning" not in payload


def test_build_llm_no_reasoning_leaves_body_clean():
    cfg = LLMConfig(
        base_url="http://x/v1", model="m", api_key="k", reasoning=False,
    )
    llm = build_llm(cfg)
    payload = llm._get_request_payload([HumanMessage(content="hi")])
    assert "messages" in payload
    assert "reasoning" not in payload
    assert "thinking" not in payload


def test_build_llm_reasoning_on_generic_host_does_not_inject():
    """非 bigmodel 的 OpenAI 兼容接口：不塞思考参数（避免 400），只靠抽取展示"""
    cfg = LLMConfig(
        base_url="http://x/v1", model="m", api_key="k", reasoning=True,
    )
    llm = build_llm(cfg)
    assert isinstance(llm, ReasoningChatOpenAI)
    payload = llm._get_request_payload([HumanMessage(content="hi")])
    assert "messages" in payload
    assert "thinking" not in payload
    assert "reasoning" not in payload


def test_build_llm_omits_temperature_for_reasoning_when_unset():
    # 思考模型默认不允许 temperature：没显式给时不要往 body 塞 temperature
    cfg = LLMConfig(
        base_url="https://open.bigmodel.cn/api/paas/v4", model="glm", api_key="k",
        reasoning=True, temperature=None, max_tokens=1,
    )
    llm = build_llm(cfg)
    payload = llm._get_request_payload([HumanMessage(content="hi")])
    assert "temperature" not in payload
    assert llm.max_tokens == 1              # 透传到实例字段
    assert payload["thinking"] == {"type": "enabled"}


# ============================================================
# reasoning 解析 ↔ 回传闭环（本地 mock 响应）
# ============================================================

def _reasoning_llm():
    cfg = LLMConfig(
        base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-4.7-flash",
        api_key="k", reasoning=True,
    )
    return build_llm(cfg)


def test_reasoning_content_kept_out_of_body():
    llm = _reasoning_llm()
    response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "这是正文",
                "reasoning_content": "思考过程…",
            },
            "finish_reason": "stop",
        }],
        "model": "glm",
    }
    result = llm._create_chat_result(response)
    msg = result.generations[0].message
    assert isinstance(msg, AIMessage)
    assert msg.content == "这是正文"          # 正文保持干净
    assert msg.additional_kwargs["reasoning_content"] == "思考过程…"
    assert get_message_reasoning(msg) == "思考过程…"


def test_reasoning_details_list_joined():
    llm = _reasoning_llm()
    response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "ok",
                "reasoning_details": [
                    {"type": "text", "content": "第一步"},
                    {"type": "text", "content": "第二步"},
                ],
            },
            "finish_reason": "stop",
        }],
    }
    result = llm._create_chat_result(response)
    msg = result.generations[0].message
    assert get_message_reasoning(msg) == "第一步\n第二步"
    assert msg.content == "ok"


def test_reasoning_echoed_back_to_assistant_body():
    """解析得到 reasoning → 序列化 assistant 回上游时原样塞回 → 闭环"""
    llm = _reasoning_llm()
    resp = llm._create_chat_result({
        "choices": [{
            "message": {"role": "assistant", "content": "hi", "reasoning_content": "想了下"},
            "finish_reason": "stop",
        }],
    })
    assistant_msg = resp.generations[0].message
    payload = llm._get_request_payload([
        SystemMessage(content="sys"),
        HumanMessage(content="q"),
        assistant_msg,
    ])
    bodies = payload["messages"]
    assert bodies[2]["reasoning_content"] == "想了下"
    assert bodies[2]["content"] == "hi"
    assert payload["thinking"] == {"type": "enabled"}


def test_base_url_normalized_strips_endpoint_suffix():
    # 用户把完整端点粘进 base_url → 自动剥掉 /chat/completions，避免双拼 404
    cfg = LLMConfig(
        base_url="https://open.bigmodel.cn/api/paas/v4/chat/completions/",
        model="glm-4.7-flash", api_key="k",
    )
    assert cfg.base_url == "https://open.bigmodel.cn/api/paas/v4"
    # 重复粘贴也能剥干净
    cfg2 = LLMConfig(
        base_url="https://x.com/v1/chat/completions/chat/completions",
        model="m", api_key="k",
    )
    assert cfg2.base_url == "https://x.com/v1"


def test_normalize_base_url_variants():
    """规整规则唯一化：根地址/完整端点/重复端点/尾斜杠/大小写 全部归一"""
    cases = [
        ("", ""),
        ("   ", ""),
        ("https://host/v4", "https://host/v4"),
        ("https://host/v4/", "https://host/v4"),
        ("https://host/v4//", "https://host/v4"),
        ("https://host/v4/chat/completions", "https://host/v4"),
        ("https://host/v4/chat/completions/", "https://host/v4"),
        ("https://host/v1/chat/completions/chat/completions", "https://host/v1"),
        # 大小写不敏感（OpenAI SDK 拼的是固定小写路径）
        ("https://host/v1/CHAT/COMPLETIONS", "https://host/v1"),
        # 不带 /chat/completions 子路径的中间层不动
        ("https://host/api/paas/v4", "https://host/api/paas/v4"),
    ]
    for raw, want in cases:
        assert normalize_base_url(raw) == want, (raw, want)


def test_http_request_ctx_reports_method_url_status():
    """HTTP 异常应还原出真正 POST 的 method + url + status（不含 key/body）"""
    from backend.services import ai_service as svc

    class _FakeReq:
        method = "POST"
        url = "http://mock/v1/chat/completions"

    class _FakeResp:
        request = _FakeReq()

    class _FakeHTTPErr(Exception):
        status_code = 405
        response = _FakeResp()

    ctx = svc._http_request_ctx(_FakeHTTPErr())
    assert ctx == "POST http://mock/v1/chat/completions → HTTP 405"


def test_http_request_ctx_none_for_non_http_error():
    from backend.services import ai_service as svc
    assert svc._http_request_ctx(RuntimeError("boom")) is None


def test_test_key_405_reports_url_instead_of_html(monkeypatch):
    """405 时不再把服务端 HTML 原样吐给用户，而是报真实请求 URL + 状态码"""
    from backend.services import ai_service as svc

    class _FakeReq:
        method = "POST"
        url = "http://mock/v1/chat/completions"

    class _FakeResp:
        request = _FakeReq()

    class _FakeHTTPErr(Exception):
        status_code = 405
        response = _FakeResp()

    class _Bad:
        def invoke(self, messages):
            raise _FakeHTTPErr("nginx 405 html……")

    monkeypatch.setattr("backend.services.llm_config.build_llm", lambda cfg: _Bad())
    ok, msg = svc.test_key(LLMConfig(base_url="http://mock/v1", model="m", api_key="sk-secret"))
    assert ok is False
    assert "POST http://mock/v1/chat/completions" in msg
    assert "405" in msg
    assert "nginx" not in msg          # 不再透出服务端 HTML
    assert "sk-secret" not in msg      # 不泄露 API Key


def test_disable_reasoning_keeps_other_fields():
    cfg = LLMConfig(base_url="b", model="m", api_key="k",
                    glm_prompt=True, router=True, reasoning=True, temperature=0.7)
    off = disable_reasoning(cfg)
    assert off.reasoning is False
    assert off.glm_prompt is True and off.router is True
    assert off.temperature == 0.7
    # 不影响原对象
    assert cfg.reasoning is True


# ============================================================
# 迁移：旧 provider 字符串 → 内置默认 cfg
# ============================================================

def test_legacy_default_cfg_mapping():
    cases = {
        "deepseek": ("https://api.deepseek.com", "deepseek-chat", False, False),
        "deepseek-routed": ("https://api.deepseek.com", "deepseek-chat", False, True),
        "glm": ("https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash", True, False),
        "glm-routed": ("https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash", True, True),
        "agnes": ("https://apihub.agnes-ai.com/v1", "agnes-2.0-flash", False, True),
    }
    for provider, (base_url, model, glm_prompt, router) in cases.items():
        cfg = legacy_default_cfg(provider, "key-x")
        assert cfg.base_url == base_url, provider
        assert cfg.model == model, provider
        assert cfg.glm_prompt == glm_prompt, provider
        assert cfg.router == router, provider
        assert cfg.api_key == "key-x"
    # 未知 provider 兜底到 deepseek
    assert legacy_default_cfg("bogus", "k").base_url == "https://api.deepseek.com"


def test_resolve_llm_config_legacy_when_no_cfg():
    cfg = resolve_llm_config(None, provider="glm-routed", api_key="old-key")
    assert cfg.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert cfg.api_key == "old-key"


def test_resolve_llm_config_prefers_explicit_cfg():
    given = LLMConfig(base_url="http://or/v1", model="z-ai/glm-5.2:free", api_key="or-key")
    cfg = resolve_llm_config(given, provider="glm-routed", api_key="old-key")
    assert cfg.base_url == "http://or/v1"
    assert cfg.model == "z-ai/glm-5.2:free"
    assert cfg.api_key == "or-key"          # 显式 key 优先
    assert cfg.router is False              # 不再吃 provider 的 router


def test_resolve_llm_config_backfills_missing_key():
    given = LLMConfig(base_url="http://or/v1", model="m", api_key="")
    cfg = resolve_llm_config(given, provider="glm", api_key="req-key")
    assert cfg.api_key == "req-key"


# ============================================================
# _build_system_content：按 glm_prompt / router 开关
# ============================================================

def test_system_prompt_toggles_glm_prefix():
    from backend.services import ai_service as svc
    cfg_plain = LLMConfig(base_url="b", model="m", api_key="k", glm_prompt=False)
    sc_plain, _, _ = svc._build_system_content(cfg_plain, "你好")
    assert sc_plain.startswith(svc.SYSTEM_PROMPT)
    assert not sc_plain.startswith(svc.SYSTEM_PROMPT_GLM)

    cfg_glm = cfg_plain.model_copy(update={"glm_prompt": True})
    sc_glm, _, display = svc._build_system_content(cfg_glm, "你好")
    assert sc_glm.startswith(svc.SYSTEM_PROMPT_GLM)
    assert display == "m"


def test_router_flag_triggers_route_and_merges_force_skills(monkeypatch):
    from backend.services import ai_service as svc

    called = {"n": 0}

    def fake_route(message, cfg):
        called["n"] += 1
        return ["geometry"]

    monkeypatch.setattr(svc, "_route_skills", fake_route)
    cfg = LLMConfig(base_url="b", model="m", api_key="k", router=True)
    sc, skill_text, _ = svc._build_system_content(cfg, "帮我分析路网", force_skills=["analysis"])
    assert called["n"] == 1
    assert "geometry 技能参考" in skill_text
    assert "analysis 技能参考" in skill_text
    assert "参考技能文档" in sc


def test_no_router_does_not_call_route(monkeypatch):
    from backend.services import ai_service as svc

    def boom(*a, **k):
        raise AssertionError("router=False 不应触发路由")

    monkeypatch.setattr(svc, "_route_skills", boom)
    cfg = LLMConfig(base_url="b", model="m", api_key="k", router=False)
    svc._build_system_content(cfg, "随便聊聊", force_skills=None)


# ============================================================
# 通用 /api/test-key
# ============================================================

def test_ai_service_test_key_success(monkeypatch):
    from backend.services import ai_service as svc

    class _FakeResp:
        content = "hi"

    class _FakeLLM:
        def invoke(self, messages):
            assert len(messages) == 1
            return _FakeResp()

    monkeypatch.setattr(
        "backend.services.llm_config.build_llm",
        lambda cfg: _FakeLLM(),
    )
    ok, msg = svc.test_key(LLMConfig(base_url="b", model="m", api_key="k"))
    assert ok is True


def test_ai_service_test_key_401_message(monkeypatch):
    from backend.services import ai_service as svc

    def bad_llm(cfg):
        class _Bad:
            def invoke(self, messages):
                raise RuntimeError("401 Unauthorized")
        return _Bad()

    monkeypatch.setattr("backend.services.llm_config.build_llm", bad_llm)
    ok, msg = svc.test_key(LLMConfig(base_url="b", model="m", api_key="bad"))
    assert ok is False
    assert "无效" in msg


def test_test_key_endpoint_legacy_mapping(monkeypatch):
    """旧前端只带 provider+api_key → 端点翻译成内置默认 cfg 再测"""
    import asyncio
    import backend.main as main

    captured = {}

    def fake_test_key(cfg):
        captured["cfg"] = cfg
        return True, "连接成功 ✓"

    monkeypatch.setattr(main, "test_key", fake_test_key)
    req = main.TestKeyRequest(provider="glm", api_key="sk-glm")
    result = asyncio.run(main.test_key_endpoint(req))
    assert result == {"success": True, "message": "连接成功 ✓"}
    assert captured["cfg"].base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert captured["cfg"].api_key == "sk-glm"
    assert captured["cfg"].glm_prompt is True


def test_test_key_endpoint_uses_llm_config_directly(monkeypatch):
    import asyncio
    import backend.main as main

    captured = {}
    monkeypatch.setattr(
        main, "test_key",
        lambda cfg: captured.update(cfg=cfg) or (False, "挂了"),
    )
    given = LLMConfig(base_url="http://or/v1", model="z-ai/glm-5.2:free", api_key="or-k")
    req = main.TestKeyRequest(llm_config=given)
    result = asyncio.run(main.test_key_endpoint(req))
    assert result["success"] is False
    assert captured["cfg"].model == "z-ai/glm-5.2:free"
