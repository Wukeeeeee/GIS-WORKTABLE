"""防止与任务无关的初始化、模型路由阻塞请求处理。无需模型密钥或外部网络。"""
import asyncio
import builtins
import contextlib
import io
import subprocess
import threading

import pytest


@pytest.mark.parametrize("code, expected", [
    ("print(2 + 2)", "4"),
    ("import numpy as np; print(np.arange(3).sum())", "3"),
])
def test_python_compute_does_not_load_unrelated_network_or_plotting(
    monkeypatch, tmp_path, code, expected,
):
    from backend.services import tools as tool_module

    attempted = []
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split('.')[0] in {"osmnx", "requests", "matplotlib"}:
            attempted.append(name)
            raise ImportError("Unrelated dependency must not be initialized")
        return real_import(name, *args, **kwargs)

    def run_generated_script(command, **kwargs):
        # 在受控命名空间执行真正生成的脚本：仅验证初始化行为，不启动外部网络。
        with open(command[-1], encoding="utf-8") as source:
            script = source.read()
        namespace = {"__builtins__": {**vars(builtins), "__import__": guarded_import}}
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exec(compile(script, command[-1], "exec"), namespace)
        return subprocess.CompletedProcess(command, 0, stdout.getvalue(), "")

    monkeypatch.setattr(tool_module, "_temp_output_dir", str(tmp_path))
    monkeypatch.setattr(tool_module, "_current_task_id", "")
    monkeypatch.setattr(tool_module, "_exec_call_count", 0)
    monkeypatch.setattr(tool_module.subprocess, "run", run_generated_script)
    result = tool_module.execute_python.invoke({"code": code})
    assert expected in result
    assert attempted == []


def test_stream_prompt_routing_leaves_event_loop_available(monkeypatch):
    import backend.main as main
    from backend.services import ai_service

    async def check():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_prompt(*args):
            loop.call_soon_threadsafe(started.set)
            release.wait(0.5)
            finished.set()
            return "system", "", "mock"

        monkeypatch.setattr(ai_service, "_build_system_content", slow_prompt)
        monkeypatch.setattr(ai_service, "_get_or_create_history", lambda *args: [])
        monkeypatch.setattr(ai_service, "_try_handle_confirm_command", lambda *args: None)
        request = main.ChatRequest(
            message="计算缓冲区", session_id="performance-event-loop",
            llm_config={"base_url": "https://example.invalid/v1", "model": "mock"},
        )
        task = asyncio.create_task(main.chat_stream(request))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            assert not finished.is_set(), "Model routing blocked the event loop"
            assert (await main.health())["status"] == "ok"
        finally:
            release.set()
            await task

    asyncio.run(check())
