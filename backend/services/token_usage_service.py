# -*- coding: utf-8 -*-
"""汇总本轮返回消息中的接口用量，并估算缺少接口用量的调用。"""
import os
import json
import datetime
from typing import Dict, Any, List
from langchain_core.messages import AIMessage, BaseMessage

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
_TOKEN_LOG_PATH = os.path.join(_LOG_DIR, "token_usage.jsonl")


def extract_and_record_token_usage(
    messages: List[BaseMessage],
    model_name: str = "",
    task_id: str = "",
    tool_count: int = 0,
    schema_chars: int = 0,
    duration_ms: int = 0,
    input_message_count: int = 0,
    previous_attempts: List[List[BaseMessage]] | None = None,
) -> Dict[str, Any]:
    """统计 input_message_count 之后的 AI 消息，历史消息只作为输入上下文。

    每条新 AI 消息优先采用完整、非负的 usage_metadata（包括零用量）；
    否则按该次调用的前序消息、工具 schema 和回复内容估算。
    任一调用需要估算时 type 为 estimate，避免把混合计量误报为纯接口数据。
    previous_attempts 保留被重试替换的消息链，按消息 ID（无 ID 时按对象）去重。
    此统计基于返回消息链，不代表供应商账单。
    """
    if (isinstance(input_message_count, bool) or not isinstance(input_message_count, int)
            or input_message_count < 0):
        raise ValueError("input_message_count 必须是非负整数")
    total_input = 0
    total_output = 0
    api_calls = estimated_calls = 0
    counts_cache = {}

    def message_counts(message):
        if id(message) in counts_cache:
            return counts_cache[id(message)]
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "".join(
                block if isinstance(block, str) else block.get("text", "")
                for block in content if isinstance(block, str)
                or isinstance(block, dict) and isinstance(block.get("text"), str)
            )
        text = content if isinstance(content, str) else ""
        if isinstance(message, AIMessage):
            reasoning = message.additional_kwargs.get("reasoning_content")
            if isinstance(reasoning, str):
                text += reasoning
            if message.tool_calls:
                text += json.dumps(message.tool_calls, ensure_ascii=False)
        cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
        counts_cache[id(message)] = (cjk, len(text) - cjk)
        return counts_cache[id(message)]

    def estimate(cjk, other):
        return max(1, int(cjk + other / 4.0)) if cjk or other else 0

    seen_calls = set()
    for chain in [*(previous_attempts or []), messages]:
        prefix_cjk = prefix_other = 0
        for index, message in enumerate(chain):
            cjk, other = message_counts(message)
            call_key = ("id", message.id) if message.id else ("object", id(message))
            if (isinstance(message, AIMessage) and index >= input_message_count
                    and call_key not in seen_calls):
                seen_calls.add(call_key)
                meta = getattr(message, "usage_metadata", None)
                if isinstance(meta, dict) and all(
                    isinstance(meta.get(key), int) and not isinstance(meta[key], bool) and meta[key] >= 0
                    for key in ("input_tokens", "output_tokens")
                ):
                    total_input += meta["input_tokens"]
                    total_output += meta["output_tokens"]
                    api_calls += 1
                else:
                    total_input += estimate(prefix_cjk, prefix_other + max(0, int(schema_chars or 0)))
                    total_output += estimate(cjk, other)
                    estimated_calls += 1
            prefix_cjk += cjk
            prefix_other += other

    usage_type = "api" if api_calls and not estimated_calls else "estimate"

    usage_record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "type": usage_type,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "model": model_name or "unknown",
        "task_id": task_id or "",
        "tool_count": tool_count,
        "schema_chars": schema_chars,
        "duration_ms": duration_ms,
        "api_calls": api_calls,
        "estimated_calls": estimated_calls,
    }

    # 容错写入 logs/token_usage.jsonl
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_TOKEN_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(usage_record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[GIS] 记录 token usage 失败: {e}", flush=True)

    return {
        "type": usage_type,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "schema_chars": schema_chars,
        "tool_count": tool_count,
    }
