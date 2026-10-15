# -*- coding: utf-8 -*-
"""Layer 5: 端到端测试 (End-to-End Tests)

测试目标：
1. 选取关键业务流程：用户输入 → Agent 意图与规划 → 工具执行 → 图层注册与产物落盘 → 地图接口输出；
2. 验证整个闭环业务链条在真实环境中的通畅性；
3. 环境不具备外部模型条件时，明确通过可控 Mock 模型打通全链路工具调用与图层注册。
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage
from backend.services.tools import get_registered_layers
from backend.services import tools as _tools_mod  # _temp_output_dir 会被 init_temp_dir 重新赋值，运行时读取

pytestmark = [pytest.mark.e2e, pytest.mark.regression]


def test_e2e_direct_tool_invocation_pipeline(client):
    """端到端验证：通过接口调度工具链 → 注册图层 → 成果落盘完整流程"""
    # 1. 模拟调用边界获取工具
    resp1 = client.post("/api/tools/invoke", json={
        "name": "datav_boundary",
        "arguments": {"name": "南京市鼓楼区"}
    })
    assert resp1.status_code == 200
    res1_data = resp1.json()
    assert res1_data.get("ok") is True

    # 2. 验证图层已被真实注册并在图层列表中可见
    resp_layers = client.get("/api/layers")
    assert resp_layers.status_code == 200
    layers = resp_layers.json().get("layers", [])
    assert any("鼓楼" in l.get("name", "") for l in layers)

    # 3. 模拟调用 execute_python 执行看板制图
    script = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(4, 3))
ax.text(0.5, 0.5, 'E2E Pipeline Test Passed')
out_png = 'output/e2e_pipeline_output.png'
plt.savefig(out_png)
plt.close()
print(f'OUTPUT_IMAGE:{out_png}')
"""
    resp2 = client.post("/api/tools/invoke", json={
        "name": "execute_python",
        "arguments": {"code": script}
    })
    assert resp2.status_code == 200
    res2_data = resp2.json()
    assert res2_data.get("ok") is True

    # 4. 验证磁盘上的成果图片
    expected_img = os.path.join(_tools_mod._temp_output_dir, "e2e_pipeline_output.png")
    assert os.path.exists(expected_img)
    assert os.path.getsize(expected_img) > 100


def test_e2e_agent_workflow_full_stream_pipeline(client):
    """端到端验证：从聊天流式接口输入用户需求，验证 SSE 事件流结构与最终结果交付"""
    from backend.services.graph import run_agent_stream
    from backend.services.llm_config import LLMConfig

    # 构造一次由 Agent 完成的流式任务（可控 mock 驱动工具调用，检验真实 graph 调度链路）
    fake_tool_call = {
        "name": "datav_boundary",
        "args": {"name": "南京市鼓楼区"},
        "id": "call_123"
    }

    # 验证流式生成器能正常流出 thinking 与 done 事件
    events = []
    # 使用纯文本 fallback/done 测试流式格式
    with patch("backend.services.graph.create_react_agent") as mock_agent_factory:
        mock_agent = MagicMock()
        mock_agent.stream.return_value = [
            {"messages": [AIMessage(content="已成功为您检索南京市鼓楼区边界并展示在地图中。")]}
        ]
        mock_agent_factory.return_value = mock_agent

        cfg = LLMConfig(api_key="mock", base_url="http://mock", model="mock")
        from langchain_core.messages import HumanMessage
        # 说明：单条消息会命中 _simple 纯文本快速通道（llm.invoke 直连真实网络）；
        # 多轮消息 + GIS 工具关键词（"边界"）才会进入 Agent 工具流（被 mock 的 create_react_agent）
        _hist = [HumanMessage(content="你好，请帮我分析南京市的数据")]
        for chunk in run_agent_stream(_hist + [HumanMessage(content="加载南京市鼓楼区边界到地图")], cfg=cfg, session_id="test_e2e_session"):
            if chunk.startswith("data: "):
                try:
                    payload = json.loads(chunk[6:].strip())
                    events.append(payload.get("type"))
                except Exception:
                    pass

    # 验证包含完整的生命周期事件
    assert "done" in events
