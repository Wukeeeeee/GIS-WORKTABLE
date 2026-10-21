import asyncio
from types import SimpleNamespace

from backend import main


def test_version_endpoint_reads_current_commit_and_dirty_state(monkeypatch):
    outputs = iter([
        "aa90473\n", " M frontend/js/workspace.js\n",
        "b71c102\n", "",
    ])

    def fake_run(*args, **kwargs):
        return SimpleNamespace(stdout=next(outputs))

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    first = asyncio.run(main.version())
    second = asyncio.run(main.version())

    assert first["commit"] == "aa90473"
    assert first["dirty"] is True
    assert second["commit"] == "b71c102"
    assert second["dirty"] is False
