"""Unsupported platform and search exceptions must be classified as failures."""

import sys
from types import SimpleNamespace

import pytest

from backend.services import history_service, tools


def _raise_offline(*_args, **_kwargs):
    raise RuntimeError("offline")


@pytest.mark.parametrize("platform,request_module,expected", [
    ("unknown", None, "暂不支持"),
    ("bilibili", SimpleNamespace(get=_raise_offline), "搜索出错"),
])
def test_platform_search_errors_are_recorded_as_failures(monkeypatch, platform, request_module, expected):
    history = []
    monkeypatch.setattr(history_service, "record", lambda *args, **kwargs: history.append(args))
    if request_module is not None:
        monkeypatch.setitem(sys.modules, "requests", request_module)

    result = next(tool for tool in tools.tools if tool.name == "search_platform").invoke({
        "platform": platform, "query": "test",
    })

    assert expected in result
    assert tools._tool_result_failed("search_platform", result)
    assert history[-1][2] is False
