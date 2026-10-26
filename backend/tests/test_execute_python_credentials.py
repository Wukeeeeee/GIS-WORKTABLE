import subprocess


def test_ai_prompts_do_not_claim_amap_key_is_injected():
    from backend.services.ai_service import SYSTEM_PROMPT, SYSTEM_PROMPT_GLM

    for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_GLM):
        assert "高德 Key 已自动注入为 _AMAP_KEY" not in prompt
    assert "不会把 `_current_amap_key` 注入用户代码为 `_AMAP_KEY`" in SYSTEM_PROMPT


def test_execute_python_does_not_forward_amap_credentials(monkeypatch, tmp_path):
    from backend.services import tools

    sentinel = "synthetic-amap-secret"
    monkeypatch.setenv("AMAP_KEY", sentinel)
    monkeypatch.setattr(tools, "_current_amap_key", sentinel)
    monkeypatch.setattr(tools, "_exec_call_count", 0)
    monkeypatch.setattr(tools, "_current_task_id", "")
    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))
    observed = {}

    def fake_run(command, **kwargs):
        script = open(command[1], encoding="utf-8").read()
        observed["script_has_key_symbol"] = "_AMAP_KEY" in script
        observed["script_has_sentinel"] = sentinel in script
        observed["child_env_has_key"] = "AMAP_KEY" in kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "probe-ok\n", "")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    result = tools.execute_python.func("print('probe-ok')")

    assert "probe-ok" in result
    assert observed == {
        "script_has_key_symbol": False,
        "script_has_sentinel": False,
        "child_env_has_key": False,
    }
