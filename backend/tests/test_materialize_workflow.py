# -*- coding: utf-8 -*-
"""测试从真实执行历史中物化生成 DAG 工作流 (Materialize Workflow)"""

import os
import pytest
from backend.services import history_service
from backend.services.workflow import materialize_from_history, save_workflow, load_workflow, validate_workflow


@pytest.fixture(autouse=True)
def clean_history(tmp_path):
    h_file = str(tmp_path / "test_tool_history.json")
    history_service.set_history_file(h_file)
    history_service.clear()
    yield
    history_service.clear()


def test_materialize_empty_history():
    wf = materialize_from_history("non_existent_task")
    assert wf is None


def test_materialize_linear_pipeline(tmp_path):
    task_id = "task_test_nanjing_01"

    # 模拟历史步骤 1：获取南京玄武区边界，产出图层 'xuanwu_boundary'
    history_service.record(
        tool_name="get_admin_boundary",
        args={"name": "玄武区"},
        ok=True,
        layer_ids=["xuanwu_boundary"],
        task_id=task_id,
        duration_ms=120
    )

    # 模拟历史步骤 2：对玄武区做 500m 缓冲区，产出图层 'xuanwu_buffer'
    history_service.record(
        tool_name="buffer_analysis",
        args={"layer_name": "xuanwu_boundary", "distance": 500},
        ok=True,
        layer_ids=["xuanwu_buffer"],
        task_id=task_id,
        duration_ms=300
    )

    # 模拟历史步骤 3：某失败步骤（物化时应自动过滤）
    history_service.record(
        tool_name="failed_tool",
        args={"bad": "param"},
        ok=False,
        error="模拟失败",
        task_id=task_id
    )

    # 执行物化
    wf = materialize_from_history(task_id, workflow_name="玄武区缓冲分析工作流")
    assert wf is not None
    assert wf["name"] == "玄武区缓冲分析工作流"
    assert len(wf["nodes"]) == 2  # 失败步骤被过滤，保留 2 个成功步骤

    node1 = wf["nodes"][0]
    node2 = wf["nodes"][1]

    assert node1["tool"] == "get_admin_boundary"
    assert node1["depends_on"] == []

    assert node2["tool"] == "buffer_analysis"
    # 验证依赖自动建立：node2 依赖 node1，参数被自动转为 ${node_1.layer_name} 引用
    assert node2["depends_on"] == ["node_1"]
    assert node2["inputs"]["layer_name"] == "${node_1.layer_name}"

    # 测试工作流保存与读取
    save_path = str(tmp_path / "xuanwu.giswork")
    assert save_workflow(wf, save_path) is True
    assert os.path.exists(save_path)

    loaded_wf = load_workflow(save_path)
    assert loaded_wf["id"] == wf["id"]
    assert len(loaded_wf["nodes"]) == 2
