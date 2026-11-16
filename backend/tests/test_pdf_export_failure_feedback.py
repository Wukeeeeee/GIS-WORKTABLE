from backend.services import tools


def test_pdf_export_exception_is_reported_as_tool_failure(monkeypatch):
    class BrokenQueue:
        def append(self, _operation):
            raise RuntimeError("queue unavailable")

    monkeypatch.setattr(tools, "_pending_layer_ops", BrokenQueue())

    result = tools.export_pdf.invoke({"title": "故障测试"})

    assert result.startswith("PDF 出图失败:")
    assert tools._tool_result_failed("export_pdf", result)


def test_pdf_export_success_is_not_reported_as_failure(monkeypatch):
    from backend.services.tool_modules import runtime

    original_queue = runtime._pending_layer_ops
    original_queue_snapshot = list(original_queue)
    isolated_queue = []
    monkeypatch.setattr(tools, "_pending_layer_ops", isolated_queue)

    result = tools.export_pdf.invoke({"title": "正常测试"})

    assert "已触发 PDF 出图" in result
    assert not tools._tool_result_failed("export_pdf", result)
    assert isolated_queue == [{
        "action": "export_pdf",
        "title": "正常测试",
        "rotation_degrees": 0,
    }]
    assert runtime._pending_layer_ops is isolated_queue
    assert original_queue == original_queue_snapshot

    monkeypatch.undo()
    assert runtime._pending_layer_ops is original_queue
    assert original_queue == original_queue_snapshot
