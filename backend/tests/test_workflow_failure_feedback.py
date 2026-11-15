from backend.services import tools
from backend.services import workflow


def test_execute_workflow_errors_are_classified_as_failures():
    assert tools._tool_result_failed("execute_workflow", "Workflow 执行失败: invalid DAG")
    assert tools._tool_result_failed("execute_workflow", "Workflow JSON 解析失败: invalid JSON")
    assert not tools._tool_result_failed("execute_workflow", "工作流执行完成")


def test_materialize_workflow_disk_save_failure_is_classified(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.runtime, "get_current_task_id", lambda: "")
    monkeypatch.setattr(tools, "_current_task_id", "task-probe")
    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))
    monkeypatch.setattr(
        workflow,
        "materialize_from_history",
        lambda *_args, **_kwargs: {
            "id": "workflow-probe",
            "name": "probe",
            "nodes": [{"name": "step", "tool": "spatial_buffer"}],
        },
    )
    monkeypatch.setattr(workflow, "save_workflow", lambda *_args, **_kwargs: False)

    result = tools.materialize_workflow.invoke({})

    assert "保存到磁盘时失败" in result
    assert tools._tool_result_failed("materialize_workflow", result)
