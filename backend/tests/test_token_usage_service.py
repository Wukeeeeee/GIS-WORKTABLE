import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.services import token_usage_service as usage


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(usage, "_TOKEN_LOG_PATH", str(tmp_path / "tokens.jsonl"))


def api_message(text, input_tokens, output_tokens):
    return AIMessage(content=text, usage_metadata={
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    })


def test_explicit_zero_api_usage_is_not_estimated():
    result = usage.extract_and_record_token_usage([
        HumanMessage(content="问题"), api_message("接口明确报告零用量", 0, 0),
    ])
    assert result["type"] == "api"
    assert result["total_tokens"] == 0


def test_history_is_context_and_not_current_output():
    messages = [SystemMessage(content="系"), HumanMessage(content="旧"),
                api_message("历史", 900, 800), HumanMessage(content="新"),
                AIMessage(content="回复")]
    result = usage.extract_and_record_token_usage(messages, input_message_count=4)
    assert result["type"] == "estimate"
    assert result["input_tokens"] == 5
    assert result["output_tokens"] == 2


def test_each_estimated_call_includes_prior_context_and_schema():
    result = usage.extract_and_record_token_usage([
        HumanMessage(content="甲乙"), AIMessage(content="丙"),
        ToolMessage(content="丁戊", tool_call_id="call"), AIMessage(content="己庚"),
    ], schema_chars=4)
    assert result["input_tokens"] == 9
    assert result["output_tokens"] == 3


def test_partial_api_usage_adds_missing_call_and_is_labeled_estimate():
    result = usage.extract_and_record_token_usage([
        HumanMessage(content="甲"), api_message("乙", 10, 2),
        ToolMessage(content="丙", tool_call_id="call"), AIMessage(content="丁"),
    ])
    assert result["type"] == "estimate"
    assert result["input_tokens"] == 13
    assert result["output_tokens"] == 3
    with open(usage._TOKEN_LOG_PATH, encoding="utf-8") as log:
        record = json.loads(log.readline())
    assert record["api_calls"] == 1
    assert record["estimated_calls"] == 1


def test_text_blocks_and_tool_call_arguments_contribute_to_estimate():
    result = usage.extract_and_record_token_usage([
        HumanMessage(content="问题"), AIMessage(content=[{"type": "text", "text": "回复"}]),
    ])
    assert result["output_tokens"] == 2
    call = AIMessage(content="", tool_calls=[{
        "name": "lookup", "args": {"city": "长沙"}, "id": "call",
    }])
    assert usage.extract_and_record_token_usage([HumanMessage(content="查找"), call])["output_tokens"] > 0


def test_malformed_metadata_falls_back_without_negative_counts():
    message = AIMessage(content="回复").model_copy(update={
        "usage_metadata": {"input_tokens": "bad", "output_tokens": -5},
    })
    result = usage.extract_and_record_token_usage([HumanMessage(content="问题"), message])
    assert result["type"] == "estimate"
    assert result["input_tokens"] == result["output_tokens"] == 2


def test_no_new_ai_message_does_not_bill_history_or_schema():
    result = usage.extract_and_record_token_usage([
        api_message("旧回复", 500, 100), HumanMessage(content="新问题"),
    ], input_message_count=2, schema_chars=10000)
    assert result["total_tokens"] == 0


def test_replaced_attempt_is_counted_and_repeated_stream_states_are_deduplicated():
    context = [SystemMessage(content="系"), HumanMessage(content="问")]
    first = api_message("第一轮", 10, 2).model_copy(update={"id": "first-call"})
    second = api_message("重试", 20, 3).model_copy(update={"id": "retry-call"})
    result = usage.extract_and_record_token_usage(
        context + [second.model_copy()], input_message_count=2,
        previous_attempts=[context + [first], context + [first.model_copy()], context + [second]],
    )
    assert result["type"] == "api"
    assert result["input_tokens"] == 30
    assert result["output_tokens"] == 5


def test_empty_final_state_keeps_attempt_usage_without_billing_history():
    context = [api_message("历史", 900, 800), HumanMessage(content="问")]
    result = usage.extract_and_record_token_usage(
        [], input_message_count=2, previous_attempts=[context + [api_message("答", 10, 2)]],
    )
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 2
