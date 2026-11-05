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


def test_materialize_branching_pipeline_preserves_root_dependencies():
    """多步骤依赖同一个上游图层时，后续步骤不能被错误推断为依赖前一步骤。"""
    task_id = "task_test_branching_02"

    history_service.record(
        tool_name="get_admin_boundary",
        args={"name": "玄武区"},
        ok=True,
        layer_ids=["xuanwu_boundary"],
        task_id=task_id,
        duration_ms=100
    )
    history_service.record(
        tool_name="buffer_analysis",
        args={"layer_name": "xuanwu_boundary", "distance": 500},
        ok=True,
        layer_ids=["xuanwu_buffer_500"],
        task_id=task_id,
        duration_ms=200
    )
    history_service.record(
        tool_name="buffer_analysis",
        args={"layer_name": "xuanwu_boundary", "distance": 1000},
        ok=True,
        layer_ids=["xuanwu_buffer_1000"],
        task_id=task_id,
        duration_ms=250
    )
    history_service.record(
        tool_name="generate_static_map",
        args={"layer_ids": ["xuanwu_buffer_500", "xuanwu_buffer_1000"]},
        ok=True,
        layer_ids=[],
        task_id=task_id,
        duration_ms=150
    )

    wf = materialize_from_history(task_id, workflow_name="分支与列表工作流")
    assert wf is not None
    assert len(wf["nodes"]) == 4

    node1, node2, node3, node4 = wf["nodes"]

    # node2 与 node3 均应当依赖根节点 node1，node3 绝不能依赖 node2
    assert node2["depends_on"] == ["node_1"]
    assert node2["inputs"]["layer_name"] == "${node_1.layer_name}"

    assert node3["depends_on"] == ["node_1"]
    assert node3["inputs"]["layer_name"] == "${node_1.layer_name}"

    # node4 接收列表参数，应自动识别两个上游依赖
    assert sorted(node4["depends_on"]) == ["node_2", "node_3"]
    assert node4["inputs"]["layer_ids"] == ["${node_2.layer_name}", "${node_3.layer_name}"]


def test_materialize_comma_separated_layer_string():
    """逗号分隔的图层字符串也能识别并物化依赖。"""
    task_id = "task_test_comma_03"

    history_service.record(
        tool_name="extract_layer_a",
        args={"name": "a"},
        ok=True,
        layer_ids=["layer_a"],
        task_id=task_id,
    )
    history_service.record(
        tool_name="extract_layer_b",
        args={"name": "b"},
        ok=True,
        layer_ids=["layer_b"],
        task_id=task_id,
    )
    history_service.record(
        tool_name="overlay_tool",
        args={"layers": "layer_a,layer_b"},
        ok=True,
        layer_ids=["layer_ab"],
        task_id=task_id,
    )

    wf = materialize_from_history(task_id)
    assert wf is not None
    node3 = wf["nodes"][2]
    assert sorted(node3["depends_on"]) == ["node_1", "node_2"]
    assert node3["inputs"]["layers"] == "${node_1.layer_name},${node_2.layer_name}"


def test_materialize_preserves_sql_columns_and_links_table_dependencies():
    """验证 SQL 中的列名不会因逗号误判为图层替换，而表名引用能正确建立上游依赖。"""
    task_id = "task_test_sql_deps_04"

    # 步骤 1：产生图层，图层名恰好叫 'name' 和 'target_poly'
    history_service.record(
        tool_name="get_layer_name",
        args={},
        ok=True,
        layer_ids=["name"],
        task_id=task_id,
    )
    history_service.record(
        tool_name="make_buffer",
        args={},
        ok=True,
        layer_ids=["target_poly"],
        task_id=task_id,
    )
    # 步骤 2：SQL 查询，SELECT 中有字段 name（绝不能被替换），FROM "target_poly"（必须被替换）
    history_service.record(
        tool_name="query_spatial_sql",
        args={"sql": 'SELECT id, name, area FROM "target_poly" WHERE area > 100'},
        ok=True,
        layer_ids=["high_area_poly"],
        task_id=task_id,
    )

    wf = materialize_from_history(task_id)
    assert wf is not None
    assert len(wf["nodes"]) == 3
    node_sql = wf["nodes"][2]

    # 依赖应只包含 target_poly 所在的 node_2，而不误连包含 'name' 列的 node_1
    assert node_sql["depends_on"] == ["node_2"]
    # 字段列表里的 'name' 完好无损，表名引用被物化为变量
    assert node_sql["inputs"]["sql"] == 'SELECT id, name, area FROM "${node_2.layer_name}" WHERE area > 100'


def test_materialize_multi_output_layers_registers_indexed_keys():
    """步骤一次生成多个产物图层时，应分别输出 layer_name, layer_name_2 和 layer_names。"""
    task_id = "task_test_multi_out_05"

    history_service.record(
        tool_name="split_zones",
        args={},
        ok=True,
        layer_ids=["zone_north", "zone_south"],
        task_id=task_id,
    )
    history_service.record(
        tool_name="process_zone",
        args={"layer": "zone_south"},
        ok=True,
        layer_ids=["processed_south"],
        task_id=task_id,
    )

    wf = materialize_from_history(task_id)
    assert wf is not None
    n1, n2 = wf["nodes"]
    assert n1["outputs"]["layer_name"] == "zone_north"
    assert n1["outputs"]["layer_name_1"] == "zone_north"
    assert n1["outputs"]["layer_name_2"] == "zone_south"
    assert n1["outputs"]["layer_names"] == ["zone_north", "zone_south"]

    # n2 引用 zone_south，对应 node_1 的 layer_name_2
    assert n2["depends_on"] == ["node_1"]
    assert n2["inputs"]["layer"] == "${node_1.layer_name_2}"
