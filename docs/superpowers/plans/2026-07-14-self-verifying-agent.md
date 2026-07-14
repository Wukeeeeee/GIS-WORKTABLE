# 自校验双智能体架构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans

**Goal:** 在 LangGraph Agent 执行完毕后增加 Verifier Agent 校验环节，确保结果符合用户需求，不满足时自动修正。

**架构：** Agent 1（执行者）完成工具调用后，将用户原始请求 + 最终输出传给 Agent 2（校验者），Agent 2 做一次极简 LLM 调用判断是否通过。不通过则回传给 Agent 1 修正，最多循环 2 次。

**Tech Stack:** LangGraph, langchain-openai, 已有 `run_agent()` 函数

---

## 文件改动

- Modify: `backend/services/graph.py` — 在 `run_agent()` 末尾增加校验步骤
- Modify: `backend/services/ai_service.py` — 将用户原始消息传给 `run_agent()`
- Modify: `backend/main.py` — 确保 chat_with_ai / chat_stream 传 original_message

---

### Task 1: 在 `run_agent()` 中增加校验 + 修正循环

**Files:**
- Modify: `backend/services/graph.py`

**Interfaces:**
- Consumes: `run_agent()` 的现有参数 + 新增 `original_message: str = ""`
- Produces: 增加校验步骤，结果可能经过一轮修正

- [ ] **Step 1: 修改 `run_agent()` 签名，增加 `original_message` 参数**

```python
def run_agent(
    messages: list,
    api_key: str,
    provider: str,
    amap_key: str = "",
    skill_text: str = "",
    original_message: str = "",  # 新增：用户原始请求
) -> dict:
```

- [ ] **Step 2: 在 Agent 执行完毕后增加校验逻辑**

```python
    # === 自校验：Agent 2 验证 ===
    # 只在非流式模式下、且有原始消息时做校验
    if original_message and final_text and len(original_message) > 3:
        _verifier_check = _run_verifier(llm, original_message, final_text, pending)
        if not _verifier_check.get("pass", True):
            print(f"[GIS] 校验未通过: {_verifier_check.get('reason', '')}", flush=True)
            # 回传给 Agent 1 修正
            correction_msg = HumanMessage(
                content=f"上一轮结果未通过质量检查。问题：{_verifier_check.get('reason', '')}\n"
                        f"请在现有结果基础上修复后重新输出。不要从头开始，只修正问题所在。"
            )
            try:
                corrected = agent.invoke(
                    {"messages": messages + [correction_msg]},
                    {"recursion_limit": 30},
                )
                # 提取修正后的回复
                corr_msgs = corrected.get("messages", [])
                for msg in reversed(corr_msgs):
                    if isinstance(msg, AIMessage) and msg.content:
                        final_text = msg.content
                        break
                # 合并修正后的图层/图片（增量追加，不去重）
                corr_pending = get_pending_state()
                pending["layers"].extend(corr_pending["layers"])
                pending["images"].extend(corr_pending["images"])
            except Exception as e:
                print(f"[GIS] 修正尝试失败，使用原结果: {e}", flush=True)
```

- [ ] **Step 3: 实现 `_run_verifier()` 函数**

```python
def _run_verifier(llm: ChatOpenAI, original_message: str, response: str, pending: dict) -> dict:
    """执行校验，返回 {"pass": bool, "reason": str}"""
    # 只有包含 GIS 操作结果时才需要校验
    has_result = bool(pending.get("layers") or pending.get("images") or pending.get("heatmap"))
    if not has_result:
        return {"pass": True, "reason": "纯文本回答，跳过校验"}

    # 工具使用摘要
    summary_parts = []
    if pending.get("layers"):
        summary_parts.append(f"生成了 {len(pending['layers'])} 个地图图层")
    if pending.get("images"):
        summary_parts.append(f"生成了 {len(pending['images'])} 个图表/文件")
    if pending.get("heatmap"):
        summary_parts.append("生成了热力图")
    tool_summary = "；".join(summary_parts) if summary_parts else "无"

    verify_prompt = (
        "你是一个 GIS 结果验证专家。判断以下 Agent 输出是否满足用户请求。\n\n"
        "规则：\n"
        "1. 输出结果是否直接回应用户的问题？\n"
        "2. 如果用户要求加载地图数据，是否有对应的 GeoJSON/图层生成？\n"
        "3. 如果用户要求画图，是否有图表生成？\n"
        "4. 输出的文本是否和用户问题相关？\n\n"
        "只需输出 JSON 格式（不要其他文字）：\n"
        '{"pass": true/false, "reason": "一句话原因"}'
    )

    try:
        verifier_messages = [
            SystemMessage(content=verify_prompt),
            HumanMessage(
                content=f"用户请求：{original_message}\n\n"
                        f"Agent 操作摘要：{tool_summary}\n\n"
                        f"Agent 文字回复：{response[:2000]}"
            ),
        ]
        result = llm.invoke(verifier_messages, max_tokens=200)
        text = result.content.strip()
        # 尝试解析 JSON
        import json
        if text.startswith("{"):
            return json.loads(text)
        # fallback：如果 LLM 没输出纯 JSON，用正则提取
        import re
        m = re.search(r'\{"pass":\s*(true|false)', text)
        if m:
            return {"pass": m.group(1) == "true", "reason": text[:100]}
        return {"pass": True, "reason": "无法解析校验结果，默认通过"}
    except Exception as e:
        print(f"[GIS] Verifier 异常: {e}", flush=True)
        return {"pass": True, "reason": f"校验异常: {e}"}
```

- [ ] **Step 4: 更新 `run_agent_stream()` 同理增加校验**

```python
# 在流式版本的末尾，收集完结果后同样调用 _run_verifier
```

- [ ] **Step 5: 更新 `ai_service.py` 和 `main.py` 传入 `original_message`**

在 `chat_with_ai()` 中：
```python
result = run_agent(
    messages=langgraph_messages,
    api_key=api_key or _get_default_key(),
    provider=provider,
    amap_key=amap_key or "",
    skill_text=skill_text,
    original_message=message,  # 新增
)
```

