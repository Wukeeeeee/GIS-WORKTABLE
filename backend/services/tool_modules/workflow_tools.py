"""Stateless workflow-tool implementations used by the tools facade."""

import json
import os
import uuid


def create_workflow_impl(workflow_json: str, *, tool_provider, failure_classifier) -> str:
    """Run an ordered list of registered tools with ``$prev``/``$N`` references."""
    try:
        steps = json.loads(workflow_json)
        if not isinstance(steps, list) or not steps:
            return "工作流执行失败：workflow_json 必须是非空数组"
        outputs = {}
        results = []
        tool_map = {}
        for tool in tool_provider():
            name = tool.name if hasattr(tool, "name") else str(tool)
            tool_map[name] = tool
        for index, step in enumerate(steps):
            step_num = index + 1
            if not isinstance(step, dict):
                return f"工作流执行失败：第{step_num}步必须是对象"
            tool_name = step.get("tool", "")
            raw_params = step.get("params", {})
            if not isinstance(raw_params, dict):
                return f"工作流执行失败：第{step_num}步 params 必须是对象"
            output_name = step.get("output", f"step_{step_num}")
            if not isinstance(output_name, str) or not output_name.strip():
                return f"工作流执行失败：第{step_num}步 output 必须是非空字符串"
            if not isinstance(tool_name, str) or tool_name not in tool_map:
                return f"工作流执行失败：第{step_num}步未找到工具 '{tool_name}'"

            resolved_params = {}
            for key, value in raw_params.items():
                if isinstance(value, str) and value.startswith("$"):
                    reference = value[1:]
                    if reference == "prev":
                        if not outputs:
                            return f"工作流执行失败：第{step_num}步参数 {key} 引用了不存在的上一步输出"
                        resolved_params[key] = list(outputs.values())[-1]
                    elif reference.isdigit():
                        number = int(reference)
                        if number in outputs:
                            resolved_params[key] = outputs[number]
                        else:
                            return f"工作流执行失败：第{step_num}步参数 {key} 引用了不存在的第 {number} 步输出"
                    else:
                        return f"工作流执行失败：第{step_num}步参数 {key} 的输出引用格式无效：{value}"
                else:
                    resolved_params[key] = value

            try:
                step_result = tool_map[tool_name].invoke(resolved_params)
            except Exception as error:
                return f"工作流执行失败：第{step_num}步 '{tool_name}' 执行失败: {str(error)[:200]}"
            if failure_classifier(tool_name, step_result):
                return f"工作流执行失败：第{step_num}步 '{tool_name}' 执行失败: {str(step_result)[:200]}"
            step_output = output_name
            outputs[step_num] = step_output
            outputs[output_name] = step_output
            results.append(f"步骤{step_num}({tool_name}) → {output_name}: {str(step_result)[:100]}")
        return "工作流执行完成:\n" + "\n".join(results)
    except Exception as error:
        return f"工作流执行失败: {str(error)[:300]}"


def materialize_workflow_impl(
    workflow_name: str = "", *, task_id_provider, output_dir,
    materialize_from_history, save_workflow,
) -> str:
    """Build and persist a reusable workflow from successful task history."""
    try:
        task_id = task_id_provider() or ""
        if not task_id:
            return "当前会话暂无活跃的任务记录，请先执行至少一次 GIS 分析操作。"

        workflow = materialize_from_history(task_id, workflow_name=workflow_name)
        if not workflow or not workflow.get("nodes"):
            return f"任务 {task_id} 中未找到成功的工具执行记录，无法物化工作流。"

        save_dir = os.path.join(output_dir, "workflows")
        os.makedirs(save_dir, exist_ok=True)
        filepath = os.path.join(save_dir, f"{workflow['id']}.giswork")
        if not save_workflow(workflow, filepath):
            return "工作流物化生成成功，但保存到磁盘时失败。"

        node_summaries = [
            f"  {index + 1}. {node['name']} (工具: {node['tool']})"
            for index, node in enumerate(workflow["nodes"])
        ]
        nodes_text = "\n".join(node_summaries)
        return (
            "已成功从真实执行历史中物化 DAG 工作流！\n"
            f"工作流名称：{workflow['name']}\n"
            f"包含节点（{len(workflow['nodes'])}个）：\n"
            f"{nodes_text}\n"
            f"保存路径：{filepath}\n"
            "后续可通过 execute_workflow 工具或前端工作流面板直接复用/重算。"
        )
    except Exception as error:
        return f"物化工作流失败: {str(error)[:200]}"


def execute_workflow_impl(
    workflow_json: str,
    *,
    tool_provider,
    new_workflow,
    validate_workflow,
    executor_factory,
    register_layer_fn,
    failure_detector,
    layer_snapshot_fn,
    stream_writer_provider,
) -> str:
    """Validate and execute a GIS DAG while preserving optional progress events."""
    try:
        wf_data = json.loads(workflow_json)

        try:
            stream_writer = stream_writer_provider()
        except Exception:
            stream_writer = None

        workflow_invocation_id = uuid.uuid4().hex[:12]
        workflow_name = str(wf_data.get("name") or "未命名工作流")[:120]
        workflow_nodes = {
            str(node.get("id")): node
            for node in wf_data.get("nodes", [])
            if isinstance(node, dict) and node.get("id") is not None
        }

        def publish_workflow_event(event):
            if not callable(stream_writer) or not isinstance(event, dict):
                return
            detail = dict(event)
            node = workflow_nodes.get(str(detail.get("node_id")), {})
            detail.setdefault("tool", node.get("tool", ""))
            try:
                stream_writer({
                    "type": "workflow_progress",
                    "invocation_id": workflow_invocation_id,
                    "workflow_name": workflow_name,
                    "event": detail,
                })
            except Exception:
                # Progress delivery is best-effort; it must not change GIS execution.
                pass

        # Keep the tool objects themselves so WorkflowExecutor uses invoke() and
        # the regular tool-recording path.
        tool_registry = {}
        for tool in tool_provider():
            try:
                tool_registry[tool.name] = tool
            except Exception:
                pass

        errors = validate_workflow(wf_data, list(tool_registry.keys()))
        if errors:
            for node in wf_data.get("nodes", []):
                if not isinstance(node, dict):
                    continue
                node_id = node.get("id")
                node_errors = [error for error in errors if node_id and f"节点 {node_id} " in error]
                if node_errors:
                    publish_workflow_event({
                        "type": "workflow_node_failed", "node_id": node_id,
                        "name": node.get("name", ""), "tool": node.get("tool", ""),
                        "error": "; ".join(node_errors)[:500],
                    })
                else:
                    publish_workflow_event({
                        "type": "workflow_node_skipped", "node_id": node_id,
                        "name": node.get("name", ""), "tool": node.get("tool", ""),
                        "error": "工作流结构校验未通过，节点未执行",
                    })
            return "Workflow 校验失败：\n" + "\n".join(f"- {error}" for error in errors)

        workflow = new_workflow(
            name=wf_data.get("name", "未命名工作流"),
            description=wf_data.get("description", ""),
            nodes=wf_data.get("nodes", []),
        )
        executor = executor_factory(
            tool_registry=tool_registry,
            register_layer_fn=register_layer_fn,
            event_callback=publish_workflow_event,
            failure_detector=failure_detector,
            layer_snapshot_fn=layer_snapshot_fn,
        )
        result = executor.execute(workflow)

        lines = [f"工作流「{result['name']}」执行完成，状态: {result['status']}"]
        for node in result["nodes"]:
            status_icon = {"success": "✓", "failed": "✗", "skipped": "⊘", "running": "⟳", "pending": "○"}.get(node["status"], "?")
            duration = f" ({node['duration']}s)" if node.get("duration") else ""
            lines.append(f"  {status_icon} {node['name']} [{node['tool']}] - {node['status']}{duration}")
            if node.get("error"):
                lines.append(f"    错误: {node['error'][:100]}")
        return "\n".join(lines)

    except json.JSONDecodeError as error:
        return f"Workflow JSON 解析失败: {str(error)}"
    except Exception as error:
        return f"Workflow 执行失败: {str(error)[:200]}"
