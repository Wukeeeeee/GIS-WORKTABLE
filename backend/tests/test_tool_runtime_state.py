"""Regression coverage for state crossing the tools/runtime boundary."""
import time
import pytest

from backend.services import tools
from backend.services.tool_modules import network, runtime, vector


def test_clear_layers_emits_one_clear_event(monkeypatch):
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_clear_layers_flag", False)
    tools.clear_layers.invoke({})
    assert tools.get_pending_state()["clear_layers"] is True
    assert tools.get_pending_state()["clear_layers"] is False


def test_request_reset_restores_web_fetch_budget(monkeypatch):
    monkeypatch.setattr(tools, "_search_call_count", 30)
    monkeypatch.setattr(tools, "fetch_webpage_impl", lambda url: "page content")
    assert "已停止" in tools.fetch_webpage.invoke({"url": "https://example.test"})
    tools.reset_state()
    assert "page content" in tools.fetch_webpage.invoke({"url": "https://example.test"})
    assert tools._search_call_count == 1


def test_request_reset_restarts_python_execution_sequence(monkeypatch):
    monkeypatch.setattr(tools, "_exec_call_count", 0)
    monkeypatch.setattr(tools, "_exec_log", [])
    monkeypatch.setattr(tools, "_ast_sandbox_check", lambda code: "blocked by test")
    tools.reset_state()
    tools.execute_python.invoke({"code": "print(1)"})
    assert tools.get_pending_state()["exec_log"][0]["seq"] == 1
    tools.reset_state()
    tools.execute_python.invoke({"code": "print(2)"})
    assert tools.get_pending_state()["exec_log"][0]["seq"] == 1


def test_request_reset_restores_web_search_budget(monkeypatch):
    monkeypatch.setattr(tools, "_search_call_count", 30)
    monkeypatch.setattr(tools, "_search_cache", {"cached query": (time.time(), "cached result")})
    assert "已停止" in tools.search_web.invoke({"query": "cached query"})
    tools.reset_state()
    assert tools.search_web.invoke({"query": "cached query"}) == "cached result"
    assert tools._search_call_count == 1


def test_network_raster_lookup_after_project_deactivation(monkeypatch, tmp_path):
    from backend.services.project_service import _deactivate_deleted_project

    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))
    monkeypatch.setattr(tools, "_registered_layers", {})
    monkeypatch.setattr(tools, "_pending_layers", [])
    monkeypatch.setattr(tools, "_pending_layer_ops", [])
    monkeypatch.setattr(tools, "_active_project_id", "deleted-project")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = uploads / "local_cost.tif"
    source.write_bytes(b"lookup fixture")
    assert network._find_uploaded_tif("local_cost") is None
    _deactivate_deleted_project("deleted-project")
    assert tools.get_active_project_id() is None
    assert network._find_uploaded_tif("local_cost") == str(source)


def test_network_raster_outputs_follow_runtime_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "_temp_output_dir", str(tmp_path))
    assert network._raster_output_dir() == str(tmp_path / "uploads")


@pytest.mark.parametrize("module", [vector, network])
def test_statistics_outputs_follow_runtime_directory(monkeypatch, tmp_path, module):
    monkeypatch.setattr(runtime, "_temp_output_dir", str(tmp_path))
    assert module._stats_out_dir("weights") == str(tmp_path / "stats" / "weights")
