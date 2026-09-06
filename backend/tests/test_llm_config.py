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










# ============================================================
# reasoning 解析 ↔ 回传闭环（本地 mock 响应）
# ============================================================

def _reasoning_llm():
    cfg = LLMConfig(
        base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-4.7-flash",
        api_key="k", reasoning=True,
    )
    return build_llm(cfg)




















# ============================================================
# 迁移：旧 provider 字符串 → 内置默认 cfg
# ============================================================









# ============================================================
# _build_system_content：按 glm_prompt / router 开关
# ============================================================







# ============================================================
# 通用 /api/test-key
# ============================================================







