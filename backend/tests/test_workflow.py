# -*- coding: utf-8 -*-
"""Workflow 执行引擎测试"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.workflow import (
    new_workflow, new_node, validate_workflow,
    topological_sort, _detect_cycle, WorkflowExecutor
)


# ============================================================
# Schema 校验测试
# ============================================================

def test_validate_valid_workflow():
    """合法 Workflow 应该通过校验"""
    wf = new_workflow("测试", nodes=[
        new_node("n1", "步骤1", "amap_geocode", {"name": "广州"}),
        new_node("n2", "步骤2", "spatial_buffer", {"radius": 1000}, depends_on=["n1"]),
    ])
    errors = validate_workflow(wf, ["amap_geocode", "spatial_buffer"])
    assert errors == [], f"不应有错误: {errors}"


def test_validate_missing_name():
    """缺少 name 应该报错"""
    wf = {"nodes": [{"id": "n1", "tool": "amap_geocode"}]}
    errors = validate_workflow(wf, ["amap_geocode"])
    assert any("name" in e for e in errors)


def test_validate_empty_nodes():
    """没有节点应该报错"""
    wf = new_workflow("测试", nodes=[])
    errors = validate_workflow(wf, [])
    assert any("没有任何节点" in e for e in errors)


def test_validate_missing_tool():
    """缺少 tool 字段应该报错"""
    wf = new_workflow("测试", nodes=[{"id": "n1", "name": "步骤1"}])
    errors = validate_workflow(wf, [])
    assert any("tool" in e for e in errors)


def test_validate_unknown_tool():
    """工具不存在应该报错"""
    wf = new_workflow("测试", nodes=[
        new_node("n1", "步骤1", "nonexistent_tool"),
    ])
    errors = validate_workflow(wf, ["amap_geocode"])
    assert any("nonexistent_tool" in e for e in errors)


def test_validate_duplicate_node_id():
    """重复节点 id 应该报错"""
    wf = new_workflow("测试", nodes=[
        new_node("n1", "步骤1", "amap_geocode"),
        new_node("n1", "步骤2", "spatial_buffer"),
    ])
    errors = validate_workflow(wf, ["amap_geocode", "spatial_buffer"])
    assert any("重复" in e for e in errors)


def test_validate_missing_dependency():
    """依赖不存在的节点应该报错"""
    wf = new_workflow("测试", nodes=[
        new_node("n1", "步骤1", "amap_geocode", depends_on=["n999"]),
    ])
    errors = validate_workflow(wf, ["amap_geocode"])
    assert any("n999" in e for e in errors)


# ============================================================
# DAG 测试
# ============================================================

def test_topological_sort_linear():
    """线性依赖应该按顺序执行"""
    nodes = [
        new_node("n1", "1", "t1"),
        new_node("n2", "2", "t2", depends_on=["n1"]),
        new_node("n3", "3", "t3", depends_on=["n2"]),
    ]
    order = topological_sort(nodes)
    assert order.index("n1") < order.index("n2") < order.index("n3")


def test_topological_sort_multiple_deps():
    """多依赖节点应该在所有依赖之后"""
    nodes = [
        new_node("n1", "1", "t1"),
        new_node("n2", "2", "t2"),
        new_node("n3", "3", "t3", depends_on=["n1", "n2"]),
    ]
    order = topological_sort(nodes)
    assert order.index("n1") < order.index("n3")
    assert order.index("n2") < order.index("n3")


def test_detect_cycle_simple():
    """简单循环应该被检测到"""
    nodes = [
        new_node("n1", "1", "t1", depends_on=["n2"]),
        new_node("n2", "2", "t2", depends_on=["n1"]),
    ]
    cycle = _detect_cycle(nodes)
    assert cycle is not None
    assert "n1" in cycle and "n2" in cycle


def test_detect_cycle_none():
    """无循环应该返回 None"""
    nodes = [
        new_node("n1", "1", "t1"),
        new_node("n2", "2", "t2", depends_on=["n1"]),
    ]
    assert _detect_cycle(nodes) is None


def test_validate_cycle():
    """循环依赖应该在校验时报错"""
    wf = new_workflow("测试", nodes=[
        new_node("n1", "1", "t1", depends_on=["n2"]),
        new_node("n2", "2", "t2", depends_on=["n1"]),
    ])
    errors = validate_workflow(wf, ["t1", "t2"])
    assert any("循环" in e for e in errors)


# ============================================================
# 执行引擎测试
# ============================================================

def _make_mock_tools():
    """创建模拟工具注册表"""
    def tool_a(x=0):
        return {"result": x + 1, "geojson": {"type": "FeatureCollection", "features": []}}
    def tool_b(y=0):
        return {"result": y * 2}
    def tool_fail():
        raise ValueError("模拟失败")
    return {"tool_a": tool_a, "tool_b": tool_b, "tool_fail": tool_fail}


def test_executor_all_success():
    """全部成功的 Workflow"""
    tools = _make_mock_tools()
    wf = new_workflow("测试", nodes=[
        new_node("n1", "步骤A", "tool_a", {"x": 5}),
        new_node("n2", "步骤B", "tool_b", {"y": "${n1.result}"}, depends_on=["n1"]),
    ])
    executor = WorkflowExecutor(tools)
    result = executor.execute(wf)
    assert result["status"] == "success"
    assert result["nodes"][0]["status"] == "success"
    assert result["nodes"][1]["status"] == "success"
    assert result["nodes"][0]["outputs"]["result"] == 6
    assert result["nodes"][1]["outputs"]["result"] == 12  # 6 * 2


def test_executor_upstream_failure_skips_downstream():
    """上游失败应该跳过下游节点"""
    tools = _make_mock_tools()
    wf = new_workflow("测试", nodes=[
        new_node("n1", "失败步骤", "tool_fail"),
        new_node("n2", "下游步骤", "tool_b", depends_on=["n1"]),
    ])
    executor = WorkflowExecutor(tools)
    result = executor.execute(wf)
    assert result["status"] == "failed"
    assert result["nodes"][0]["status"] == "failed"
    assert result["nodes"][1]["status"] == "skipped"
    assert "上游" in result["nodes"][1]["error"]


def test_executor_tool_not_found():
    """工具不存在应该失败"""
    tools = _make_mock_tools()
    wf = new_workflow("测试", nodes=[
        new_node("n1", "步骤", "nonexistent"),
    ])
    executor = WorkflowExecutor(tools)
    result = executor.execute(wf)
    assert result["nodes"][0]["status"] == "failed"
    assert "不存在" in result["nodes"][0]["error"]


def test_executor_auto_register_layer():
    """输出含 GeoJSON 应该自动注册图层"""
    tools = _make_mock_tools()
    registered = []
    def register_fn(name, geojson):
        registered.append((name, geojson))
    wf = new_workflow("测试", nodes=[
        new_node("n1", "步骤A", "tool_a", {"x": 1}),
    ])
    executor = WorkflowExecutor(tools, register_layer_fn=register_fn)
    result = executor.execute(wf)
    assert len(registered) == 1
    assert "步骤A" in registered[0][0]


def test_executor_event_callback():
    """事件回调应该被调用"""
    tools = _make_mock_tools()
    events = []
    def callback(event):
        events.append(event["type"])
    wf = new_workflow("测试", nodes=[
        new_node("n1", "步骤A", "tool_a"),
    ])
    executor = WorkflowExecutor(tools, event_callback=callback)
    executor.execute(wf)
    assert "workflow_started" in events
    assert "workflow_node_started" in events
    assert "workflow_node_completed" in events
    assert "workflow_completed" in events


# ============================================================
# execute_workflow 工具测试
# ============================================================

def test_execute_workflow_tool_valid():
    """execute_workflow 工具应该能执行合法 Workflow"""
    import json
    from backend.services.tools import execute_workflow
    wf = {
        "name": "测试工作流",
        "nodes": [
            {"id": "n1", "name": "地理编码", "tool": "amap_geocode", "inputs": {"name": "广州"}, "depends_on": []},
        ]
    }
    result = execute_workflow.func(json.dumps(wf, ensure_ascii=False))
    assert "测试工作流" in result
    assert "amap_geocode" in result


def test_execute_workflow_tool_invalid_json():
    """非法 JSON 应该返回错误"""
    from backend.services.tools import execute_workflow
    result = execute_workflow.func("not valid json")
    assert "解析失败" in result


def test_execute_workflow_tool_unknown_tool():
    """不存在的工具应该返回校验错误"""
    import json
    from backend.services.tools import execute_workflow
    wf = {
        "name": "测试",
        "nodes": [{"id": "n1", "name": "步骤", "tool": "nonexistent_xyz"}],
    }
    result = execute_workflow.func(json.dumps(wf))
    assert "校验失败" in result
    assert "nonexistent_xyz" in result


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
