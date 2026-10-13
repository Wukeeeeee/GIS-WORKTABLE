# -*- coding: utf-8 -*-
"""Token 计量基建：从 AIMessage 提取 usage_metadata，无 metadata 时用字符数 ÷ 3.0 兜底，并追加到 logs/token_usage.jsonl"""
import os
import json
import time
import datetime
from typing import Optional, Dict, Any, List
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
) -> Dict[str, Any]:
    """从给定的消息链中汇总最后一轮或整个回合的 token 消耗。
    
    规则：
    1. 优先从 AIMessage.usage_metadata 读取官方数据（标记为 'api'）
    2. 若未返回 usage_metadata，统计所有 messages 字符数并除以 3.0 进行校准估算（标记为 'estimate'）
    3. 写入 logs/token_usage.jsonl
    4. 返回前端友好的结构体字典
    """
    total_input = 0
    total_output = 0
    has_api_usage = False

    # 尝试从消息中寻找 usage_metadata
    for m in messages:
        if isinstance(m, AIMessage):
            meta = getattr(m, "usage_metadata", None)
            if isinstance(meta, dict) and (meta.get("input_tokens") or meta.get("output_tokens")):
                total_input += int(meta.get("input_tokens", 0))
                total_output += int(meta.get("output_tokens", 0))
                has_api_usage = True

    if has_api_usage and (total_input > 0 or total_output > 0):
        usage_type = "api"
    else:
        # 兜底：字符数估算（中文+英文混合模式校准比率 3.0）
        usage_type = "estimate"
        # 估算 input：输入消息字符 + 工具 schema 字符
        input_chars = schema_chars
        output_chars = 0
        for m in messages:
            content = getattr(m, "content", "")
            if isinstance(content, str):
                if isinstance(m, AIMessage):
                    output_chars += len(content)
                else:
                    input_chars += len(content)
        total_input = max(1, int(input_chars / 3.0))
        total_output = max(1, int(output_chars / 3.0))

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
    }

    # 异步/容错写入 logs/token_usage.jsonl
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
