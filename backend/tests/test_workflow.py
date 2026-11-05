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


def test_executor_rerun_does_not_reuse_outputs_from_previous_run():
    """重跑已保存工作流时，下游不能读取上次运行遗留的输出。"""
    received = []

    def source():
        return {"fresh_value": "new-run"}

    def sink(value=None):
        received.append(value)
        return {"received": value}

    wf = new_workflow("重跑", nodes=[
        new_node("source", "来源", "source"),
        new_node("sink", "下游", "sink", {"value": "${source.layer_name}"}, ["source"]),
    ])
    # 已保存的工作流可能携带上一次运行的结果字段。
    wf["nodes"][0]["outputs"] = {"layer_name": "old-layer-from-prior-run"}

    result = WorkflowExecutor({"source": source, "sink": sink}).execute(wf)

    assert result["status"] == "failed"
    assert result["nodes"][0]["outputs"] == {"fresh_value": "new-run"}
    assert "未产生输出 layer_name" in result["nodes"][1]["error"]
    assert received == []


def test_executor_rerun_clears_previous_workflow_error():
    """成功重跑后，顶层不能继续携带上次失败原因。"""
    calls = {"count": 0}

    def maybe_fail():
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("first run failed")
        return {"result": "ok"}

    wf = new_workflow("重跑状态", nodes=[new_node("n1", "步骤", "maybe_fail")])
    executor = WorkflowExecutor({"maybe_fail": maybe_fail})

    assert executor.execute(wf)["status"] == "failed"
    result = executor.execute(wf)

    assert result["status"] == "success"
    assert result["error"] is None


def test_executor_invokes_langchain_structured_tool():
    """WorkflowExecutor 应通过 invoke 执行 LangChain StructuredTool。"""
    from langchain_core.tools import StructuredTool

    calls = []

    def list_layers():
        """列出当前图层。"""
        calls.append("called")
        return "当前地图没有已加载或注册的图层"

    tool = StructuredTool.from_function(list_layers, name="list_layers")
    wf = new_workflow("图层检查", nodes=[
        new_node("n1", "检查图层", "list_layers"),
    ])

    result = WorkflowExecutor({"list_layers": tool}).execute(wf)

    assert calls == ["called"]
    assert result["status"] == "success"
    assert result["nodes"][0]["outputs"]["result"] == "当前地图没有已加载或注册的图层"


def test_executor_marks_explicit_tool_error_as_failed():
    """工具显式返回失败文本时不能把 Workflow 节点标记成功。"""
    wf = new_workflow("失败检查", nodes=[
        new_node("n1", "调用工具", "broken_tool"),
    ])
    result = WorkflowExecutor({
        "broken_tool": lambda: "工具执行失败: simulated failure",
    }).execute(wf)

    assert result["status"] == "failed"
    assert result["nodes"][0]["status"] == "failed"
    assert "simulated failure" in result["nodes"][0]["error"]


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


def test_executor_global_validation_failure_marks_nodes_skipped():
    wf = {"name": "", "nodes": [new_node("n1", "步骤", "tool_a")]}

    result = WorkflowExecutor(_make_mock_tools()).execute(wf)

    assert result["status"] == "failed"
    assert result["nodes"][0]["status"] == "skipped"
    assert "未执行" in result["nodes"][0]["error"]


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


def test_execute_workflow_uses_structured_tool_in_registry(monkeypatch):
    """execute_workflow 应把 LangChain 工具对象交给执行器并通过 invoke 调用。"""
    import json
    from langchain_core.tools import StructuredTool
    import backend.services.tools as gis_tools

    calls = []

    def list_layers():
        """列出当前图层。"""
        calls.append("called")
        return "当前地图没有已加载或注册的图层"

    monkeypatch.setattr(gis_tools, "tools", [
        StructuredTool.from_function(list_layers, name="list_layers"),
    ])
    workflow = {
        "name": "检查当前图层",
        "nodes": [{"id": "n1", "name": "列出图层", "tool": "list_layers", "inputs": {}}],
    }

    result = gis_tools.execute_workflow.func(json.dumps(workflow, ensure_ascii=False))

    assert calls == ["called"]
    assert "状态: success" in result


def test_execute_workflow_publishes_node_events_to_langgraph_custom_stream(monkeypatch):
    import json
    from typing_extensions import TypedDict
    from langgraph.graph import END, START, StateGraph
    import backend.services.tools as gis_tools
    import backend.services.workflow as workflow_module
    from backend.services.tools import execute_workflow

    class State(TypedDict):
        result: str

    class FakeExecutor:
        def __init__(self, tool_registry, event_callback=None, **kwargs):
            self.event_callback = event_callback

        def execute(self, workflow):
            node = workflow["nodes"][0]
            self.event_callback({
                "type": "workflow_node_started", "node_id": node["id"],
                "name": node["name"], "tool": node["tool"],
            })
            self.event_callback({
                "type": "workflow_node_completed", "node_id": node["id"],
                "name": node["name"], "status": "success",
            })
            return {"name": workflow["name"], "status": "success", "nodes": [
                {"name": node["name"], "tool": node["tool"], "status": "success", "duration": 0.1},
            ]}

    monkeypatch.setattr(workflow_module, "WorkflowExecutor", FakeExecutor)
    workflow = json.dumps({
        "name": "流式测试工作流",
        "nodes": [{"id": "n1", "name": "读取图层", "tool": "list_layers", "inputs": {}}],
    }, ensure_ascii=False)
    invalid_workflow = json.dumps({
        "name": "无效流式工作流",
        "nodes": [
            {"id": "bad", "name": "未知工具", "tool": "missing_tool", "inputs": {}},
            {"id": "downstream", "name": "后续步骤", "tool": "list_layers",
             "inputs": {}, "depends_on": ["bad"]},
        ],
    }, ensure_ascii=False)
    monkeypatch.setattr(gis_tools, "tools", [
        gis_tools.list_layers,
    ])

    def invoke(state):
        result = execute_workflow.invoke({"workflow_json": workflow})
        invalid_result = execute_workflow.invoke({"workflow_json": invalid_workflow})
        return {"result": result + invalid_result}

    graph = StateGraph(State)
    graph.add_node("invoke_workflow", invoke)
    graph.add_edge(START, "invoke_workflow")
    graph.add_edge("invoke_workflow", END)
    custom_events = [
        payload for mode, payload in graph.compile().stream(
            {"result": ""}, stream_mode=["values", "custom"]
        ) if mode == "custom"
    ]

    progress = [event for event in custom_events if event.get("type") == "workflow_progress"]
    assert [event["event"]["type"] for event in progress] == [
        "workflow_node_started", "workflow_node_completed",
        "workflow_node_failed", "workflow_node_skipped",
    ]
    assert [event["workflow_name"] for event in progress] == [
        "流式测试工作流", "流式测试工作流", "无效流式工作流", "无效流式工作流",
    ]


def test_execute_workflow_passes_registered_gis_layer_to_downstream_tool(monkeypatch):
    """Spatial tools return text but register layers as side effects; expose that output to dependent nodes."""
    import json
    import backend.services.tools as gis_tools

    monkeypatch.setattr(gis_tools, "_registered_layers", {})
    monkeypatch.setattr(gis_tools, "_pending_layers", [])
    source_name = "workflow_chain_source"
    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": 1},
         "geometry": {"type": "Point", "coordinates": [-73.98, 40.75]}},
    ]}
    gis_tools._register_layer(source_name, geojson)
    monkeypatch.setattr(gis_tools, "tools", [gis_tools.spatial_buffer, gis_tools.spatial_centroid])
    workflow = {
        "name": "缓冲后提取质心",
        "nodes": [
            {"id": "buffer", "name": "缓冲站点", "tool": "spatial_buffer",
             "inputs": {"layer_name": source_name, "distance": 100, "unit": "m"}},
            {"id": "centroid", "name": "缓冲区质心", "tool": "spatial_centroid",
             "inputs": {"layer_name": "${buffer.layer_name}"}, "depends_on": ["buffer"]},
        ],
    }

    result = gis_tools.execute_workflow.func(json.dumps(workflow, ensure_ascii=False))

    assert "状态: success" in result
    assert "缓冲区质心 [spatial_centroid] - success" in result
    assert "workflow_chain_source_缓冲区_质心" in gis_tools._registered_layers


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


def test_topological_sort_dangling_dependency_does_not_crash():
    """节点依赖不存在的 ID 时，拓扑排序不应触发 KeyError 异常。"""
    nodes = [
        new_node("n1", "步骤1", "tool_a", depends_on=["missing_upstream"]),
        new_node("n2", "步骤2", "tool_b", depends_on=["n1"]),
    ]
    order = topological_sort(nodes)
    assert order.index("n1") < order.index("n2")


def test_executor_resolves_nested_list_and_whitespace_references():
    """解析上游变量时应支持内部空白、列表参数及字典嵌套。"""
    called_args = []

    def mock_sink(**kwargs):
        called_args.append(kwargs)
        return {"ok": True}

    tools = {
        "producer": lambda: {"layer_name": "poly_layer", "count": 10},
        "producer2": lambda: {"layer_name": "line_layer"},
        "consumer": mock_sink,
    }

    wf = new_workflow("测试模板解析", nodes=[
        new_node("p1", "生成多边形", "producer"),
        new_node("p2", "生成线", "producer2"),
        new_node("c1", "下游汇总", "consumer", {
            "single": " ${ p1.layer_name } ",
            "layers": ["${p1.layer_name}", "${p2.layer_name}"],
            "nested": {"target": "${p1.layer_name}", "num": "${p1.count}"},
            "interpolated": "${p1.layer_name}+${p2.layer_name}",
        }, depends_on=["p1", "p2"]),
    ])

    result = WorkflowExecutor(tools).execute(wf)
    assert result["status"] == "success"
    assert len(called_args) == 1
    args = called_args[0]
    assert args["single"] == "poly_layer"
    assert args["layers"] == ["poly_layer", "line_layer"]
    assert args["nested"] == {"target": "poly_layer", "num": 10}
    assert args["interpolated"] == "poly_layer+line_layer"


def test_executor_unexecuted_nodes_prevent_success_status():
    """若由于非标准拓扑导致部分节点仍处于 pending 状态，整体工作流不能标记为 success。"""
    tools = {
        "tool_a": lambda: {"ok": True},
    }
    wf = new_workflow("未执行节点", nodes=[
        new_node("n1", "执行节点", "tool_a"),
        new_node("n2", "未触发节点", "tool_a"),
    ])
    executor = WorkflowExecutor(tools)
    # 模拟拓扑排序仅返回第一个节点（例如因环或断图导致第二个节点未排入队列）
    import backend.services.workflow as wf_module
    orig_topo = wf_module.topological_sort
    wf_module.topological_sort = lambda nodes: ["n1"]
    try:
        res = executor.execute(wf)
        assert res["status"] == "partial"
        assert "1 个节点未执行" in res["error"]
        assert res["nodes"][0]["status"] == "success"
        assert res["nodes"][1]["status"] == "pending"
    finally:
        wf_module.topological_sort = orig_topo


def test_executor_resolves_string_interpolation_with_mixed_braces():
    """测试包含 ${...} 且尾部或中间包含普通花括号的字符串能正确解析，而不误判为单变量引用。"""
    called_args = []
    tools = {
        "producer": lambda: {"name": "boundary_1"},
        "consumer": lambda **kwargs: called_args.append(kwargs) or {"ok": True},
    }
    wf = new_workflow("混合花括号解析", nodes=[
        new_node("p1", "产出", "producer"),
        new_node("c1", "消费", "consumer", {
            "template": "${p1.name} and {literal_extra}",
            "json_like": '{"target": "${p1.name}", "flag": 1}',
        }, depends_on=["p1"]),
    ])
    result = WorkflowExecutor(tools).execute(wf)
    assert result["status"] == "success"
    assert len(called_args) == 1
    assert called_args[0]["template"] == "boundary_1 and {literal_extra}"
    assert called_args[0]["json_like"] == '{"target": "boundary_1", "flag": 1}'


def test_executor_resolves_nested_path_and_list_index():
    """解析上游引用应支持嵌套字典路径及列表索引访问。"""
    called_args = []
    tools = {
        "producer": lambda: {
            "meta": {"layer_name": "nested_roads", "count": 42},
            "layer_names": ["layer_alpha", "layer_beta"],
        },
        "consumer": lambda **kwargs: called_args.append(kwargs) or {"ok": True},
    }
    wf = new_workflow("嵌套属性引用", nodes=[
        new_node("p1", "产出嵌套数据", "producer"),
        new_node("c1", "消费嵌套数据", "consumer", {
            "road": "${p1.meta.layer_name}",
            "total": "${p1.meta.count}",
            "second": "${p1.layer_names.1}",
        }, depends_on=["p1"]),
    ])
    result = WorkflowExecutor(tools).execute(wf)
    assert result["status"] == "success"
    assert called_args[0]["road"] == "nested_roads"
    assert called_args[0]["total"] == 42
    assert called_args[0]["second"] == "layer_beta"


def test_executor_rerun_resets_stale_status_and_timing():
    """同一 Workflow 实例重跑时，所有节点的 status、duration 和时间戳必须重置为 pending。"""
    import backend.services.workflow as wf_module
    tools = {"tool_a": lambda: {"ok": True}}
    wf = new_workflow("重跑工作流", nodes=[
        new_node("n1", "节点1", "tool_a"),
        new_node("n2", "节点2", "tool_a"),
    ])
    executor = WorkflowExecutor(tools)
    res1 = executor.execute(wf)
    assert res1["status"] == "success"
    assert res1["nodes"][0]["status"] == "success"
    assert res1["nodes"][1]["status"] == "success"

    # 模拟第二次执行时，拓扑排序因断图等原因仅调度 n1
    orig_topo = wf_module.topological_sort
    wf_module.topological_sort = lambda nodes: ["n1"]
    try:
        res2 = executor.execute(wf)
        assert res2["status"] == "partial"
        assert "1 个节点未执行" in res2["error"]
        assert res2["nodes"][0]["status"] == "success"
        # 核心：n2 不能残留第一次执行的 success
        assert res2["nodes"][1]["status"] == "pending"
        assert res2["nodes"][1]["duration"] is None
    finally:
        wf_module.topological_sort = orig_topo


def test_executor_multi_layer_output_resolution():
    """上游产生多个新图层时，下游引用 ${node.layer_name_2} 和 ${node.layer_names} 均可正常解析。"""
    state = {"existing": "v1"}
    def snapshot():
        return dict(state)

    def multi_producer():
        state["layer_first"] = "v2"
        state["layer_second"] = "v3"
        return "多图层生成成功"

    received = []
    def consumer(l1, l2, all_layers):
        received.append((l1, l2, all_layers))
        return {"ok": True}

    tools = {
        "multi_producer": multi_producer,
        "consumer": consumer,
    }

    wf = new_workflow("多产物图层下游消费", nodes=[
        new_node("p1", "多图层生成", "multi_producer"),
        new_node("c1", "下游消费", "consumer", {
            "l1": "${p1.layer_name}",
            "l2": "${p1.layer_name_2}",
            "all_layers": "${p1.layer_names}",
        }, depends_on=["p1"]),
    ])

    executor = WorkflowExecutor(tools, layer_snapshot_fn=snapshot)
    res = executor.execute(wf)
    assert res["status"] == "success"
    assert len(received) == 1
    assert received[0][0] == "layer_first"
    assert received[0][1] == "layer_second"
    assert received[0][2] == ["layer_first", "layer_second"]


def test_topological_sort_and_detect_cycle_handle_invalid_nodes():
    """topological_sort 与 _detect_cycle 传入 None 或缺少 id 的非法字典不崩溃。"""
    from backend.services.workflow import _detect_cycle
    # 包含 None 及无 id 字典
    nodes = [{"id": "a", "depends_on": []}, None, {"name": "missing_id"}, {"id": "b", "depends_on": ["a"]}]
    order = topological_sort(nodes)
    assert order == ["a", "b"]

    cycle = _detect_cycle(nodes)
    assert cycle is None


def test_tool_failure_message_detects_exceptions_and_json_payloads():
    """统一识别异常前缀及 JSON 格式失败载荷。"""
    from backend.services.workflow import _tool_failure_message
    assert _tool_failure_message("SQL 查询执行异常: table not found") is not None
    assert _tool_failure_message('{"ok": false, "error": "参数越界"}') == "参数越界"
    assert _tool_failure_message("空间计算异常：坐标超限") is not None
    assert _tool_failure_message("正常执行成功结果") is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
