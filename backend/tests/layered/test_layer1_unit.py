# -*- coding: utf-8 -*-
"""Layer 1: 单元测试 (Unit Tests)

测试目标：
1. Prompt 模板组装、核心准则约束（行动优先、单区规范、禁止过度追问、默认内置底图）；
2. 工具函数入参校验与上下文存取；
3. 未执行代码与"复制到本地/Jupyter"免责声明探测；
4. 结果质量守护（Result Guard）规则校验；
5. 纯逻辑测试，耗时极短（<1s），不依赖外部网络与大模型。

注：2026-10-12 与源码对齐——result_guard 当前 API 为 apply_guard/verify_result，
_is_unexecuted_code_or_disclaimer 签名为 (text, msgs)，Prompt 措辞同步更新。
"""
import pytest
from langchain_core.messages import ToolMessage
from backend.services.ai_service import SYSTEM_PROMPT, SYSTEM_PROMPT_GLM
from backend.services.tools import (
    set_conversation_context,
    get_conversation_context,
    tools as all_tools
)
from backend.services.graph import (
    _is_unexecuted_code_or_disclaimer,
    _strip_executed_code_blocks,
    _RECOVERY_PROMPT_CODE_DUMP,
    _RECOVERY_PROMPT_NO_ACTION,
)
from backend.services.result_guard import apply_guard

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_system_prompt_contains_core_thematic_rules():
    """验证系统提示词中包含核心交付红线，严禁过度追问与推诿。

    注：GLM 专属提示词为精简版，仅校验通用红线子集。
    """
    # 主提示词：全部核心规则
    p = SYSTEM_PROMPT
    assert "继承对象与字段" in p              # 1. 上下文继承依赖会话状态
    assert "问卷式选项" in p                  # 2. 严禁过度追问与问卷
    assert "手动打字回复特定格式" in p        # 3. 严禁要求用户手动打字回复特定格式
    assert "索要本地" in p                    # 4. 严禁索要用户本地 shp
    assert "按当前请求注入的 `cartography` 知识处理" in p  # 5. 制图细则按需注入
    # GLM 提示词：通用红线子集
    g = SYSTEM_PROMPT_GLM
    assert "问卷式选项" in g
    assert "索要本地" in g


def test_conversation_context_storage_and_retrieval():
    """验证工具层上下文存储与提取机制（API 为字符串摘要）"""
    ctx = "用户想查鼓楼区的GDP2025年；回答：南京市鼓楼区 2025 年地区生产总值 2245.8 亿元。"
    set_conversation_context(ctx)
    retrieved = get_conversation_context()
    assert isinstance(retrieved, str)
    assert "鼓楼区" in retrieved
    assert "南京市鼓楼区" in retrieved


def test_unexecuted_code_detection():
    """验证未执行代码与'复制到本地/Jupyter'免责声明探测逻辑"""
    # 典型负面样本 1: 声明无法在此出图（无任何工具消息）
    text_disclaimer_1 = "我没法在这边直接跑出图片文件给你，但代码是完整可运行的，你复制到本地或 Jupyter 里直接出图。"
    assert _is_unexecuted_code_or_disclaimer(text_disclaimer_1, []) is True

    # 典型负面样本 2: 给出制图代码但未调用 execute_python
    text_code_block = (
        "以下是绘制专题图的完整代码：\n```python\n"
        "import matplotlib.pyplot as plt\nplt.figure()\nplt.savefig('output/test.png')\n```"
    )
    assert _is_unexecuted_code_or_disclaimer(text_code_block, []) is True

    # 典型负面样本 3: 让用户把代码存成本地运行
    text_dump = "平台不直接出图，请把下面代码存成 run.py 在本地执行。"
    assert _is_unexecuted_code_or_disclaimer(text_dump, []) is True

    # 正常样本: 已经调用过工具并正常回复（消息列表含 ToolMessage → 直接放行）
    text_normal = "已成功获取南京市鼓楼区边界并生成 2025 年经济数据看板图：output/gulou_2025.png"
    tool_msgs = [ToolMessage(content="ok", tool_call_id="call_1")]
    assert _is_unexecuted_code_or_disclaimer(text_normal, tool_msgs) is False

    # 纠错指令常量存在且包含关键约束（非流式/流式共用）
    assert "execute_python" in _RECOVERY_PROMPT_CODE_DUMP
    assert "严禁向用户声称" in _RECOVERY_PROMPT_CODE_DUMP
    assert "不要再只做口头承诺" in _RECOVERY_PROMPT_NO_ACTION


def test_tool_registry_schemas_integrity():
    """验证已注册的生产工具清单及描述完整性"""
    tool_names = [t.name for t in all_tools]
    # 核心工具必须存在
    assert "datav_boundary" in tool_names
    assert "spatial_graduated_colors" in tool_names
    assert "execute_python" in tool_names
    assert "create_chart" in tool_names
    assert "spatial_buffer" in tool_names


def test_result_guard_apply_guard_normal_text():
    """验证结果守护层对正常回复不误伤（apply_guard 当前 API）"""
    raw_response = "任务完成。这里是分析结果。"
    final_text, check = apply_guard(raw_response)
    assert isinstance(check, dict)
    assert "ok" in check
    assert check["ok"] is True
    assert final_text == raw_response


# ============================================================
# 源码折叠：杜绝"已执行的 Python 代码块原样糊到用户脸上"
# ============================================================

_CODE_REPLY = """我来把复合图拆成两张独立的成果图：

```python
import geopandas as gpd
import matplotlib.pyplot as plt
plt.savefig('output/南京各区人口_分级设色图.png', dpi=150)
```

已拆分为两张独立成果图：

图件1：南京市各区常住人口分级设色图

数据说明：共 931.5 万人
"""


def _tools_ran():
    return [ToolMessage(content="saved output/a.png", tool_call_id="call_1")]


def test_strip_executed_code_blocks_folds_source():
    """本轮真跑过工具 → 源码折叠，结论与正文必须原样保留"""
    out = _strip_executed_code_blocks(_CODE_REPLY, _tools_ran(), "我希望你能拆成两个图片")
    assert "import geopandas" not in out
    assert "plt.savefig" not in out
    assert "```python" not in out
    # 交付物描述不能被误删
    assert "图件1：南京市各区常住人口分级设色图" in out
    assert "931.5 万人" in out


def test_strip_executed_code_blocks_keeps_result_blocks():
    """非 Python 代码块（JSON 数据/结论）必须保留"""
    reply = "结果如下：\n\n```json\n{\"file\": \"a.png\"}\n```\n"
    out = _strip_executed_code_blocks(reply, _tools_ran(), "查一下")
    assert '"file": "a.png"' in out


def test_strip_executed_code_blocks_skips_without_tool_call():
    """本轮没有工具调用 → 代码可能正是交付物，禁止折叠"""
    out = _strip_executed_code_blocks(_CODE_REPLY, [], "帮我出图")
    assert "import geopandas" in out


def test_strip_executed_code_blocks_skips_when_code_requested():
    """用户明确索要代码 → 原样保留"""
    out = _strip_executed_code_blocks(_CODE_REPLY, _tools_ran(), "把刚才那段代码给我看看")
    assert "import geopandas" in out


def test_prompt_forbids_echoing_executed_source():
    """系统提示必须显式禁止复述已执行源码（防回归）"""
    for p in (SYSTEM_PROMPT, SYSTEM_PROMPT_GLM):
        assert "严禁在最终回复里粘贴你已经执行过的源码" in p


# ============================================================
# 跨会话上下文污染：新会话不得被注入旧会话的任务上下文
# ============================================================

def test_build_system_content_no_cross_session_task_leak():
    """新会话构建 system prompt 时，全局 current_task_id 还残留着别的会话
    （上一请求）的任务 → 不允许把那个任务的目标/源码/历史注入新会话。"""
    import types
    from backend.services import task_manager
    from backend.services import tools as _tools
    from backend.services.ai_service import _build_system_content

    _tid = task_manager.create_task("广东各市GDP排名（旧会话任务）", "session_OLD")
    try:
        # 模拟真实时序：全局 current_task_id 停留在旧会话的任务上
        _tools.set_current_task(_tid)

        cfg = types.SimpleNamespace(glm_prompt=False, router=False, model="test-model")
        # 新会话第一条消息构建 prompt
        sys_new, _, _ = _build_system_content(cfg, "解析广州", session_id="session_NEW", force_skills=[])
        assert "广东各市GDP排名" not in sys_new, "新会话 system prompt 泄漏了旧会话任务目标！"

        # 旧会话自己的 prompt 仍应包含其活跃任务（原有能力不回退）
        sys_old, _, _ = _build_system_content(cfg, "继续", session_id="session_OLD", force_skills=[])
        assert "广东各市GDP排名" in sys_old
    finally:
        task_manager.delete_task(_tid)
