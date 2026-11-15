from backend.services import tools


def test_pdf_export_exception_is_reported_as_tool_failure(monkeypatch):
    class BrokenQueue:
        def append(self, _operation):
            raise RuntimeError("queue unavailable")

    monkeypatch.setattr(tools, "_pending_layer_ops", BrokenQueue())

    result = tools.export_pdf.invoke({"title": "故障测试"})

    assert result.startswith("PDF 出图失败:")
    assert tools._tool_result_failed("export_pdf", result)


def test_pdf_export_success_is_not_reported_as_failure():
    tools.reset_state()

    result = tools.export_pdf.invoke({"title": "正常测试"})

    assert "已触发 PDF 出图" in result
    assert not tools._tool_result_failed("export_pdf", result)
