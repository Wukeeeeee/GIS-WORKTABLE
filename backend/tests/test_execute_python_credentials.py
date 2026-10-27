import os
import subprocess


def test_execute_python_description_states_actual_execution_boundary():
    from backend.services import tools
    from backend.services.ai_service import SYSTEM_PROMPT

    description = tools.execute_python.description
    assert "本地子进程" in description
    assert "不是操作系统级安全沙箱" in description
    assert "过滤常见凭据环境变量" in description
    assert "不提供文件、网络或资源隔离" in description
    assert "平台已预装 Python 沙箱" not in SYSTEM_PROMPT
    assert "不要把它描述为安全沙箱" in SYSTEM_PROMPT


def test_ai_prompts_do_not_claim_amap_key_is_injected():
    from backend.services.ai_service import SYSTEM_PROMPT, SYSTEM_PROMPT_GLM

    for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_GLM):
        assert "高德 Key 已自动注入为 _AMAP_KEY" not in prompt
    assert "不会把 `_current_amap_key` 注入用户代码为 `_AMAP_KEY`" in SYSTEM_PROMPT


def test_execute_python_does_not_forward_amap_credentials(monkeypatch, tmp_path):
    from backend.services import tools

    sentinel = "synthetic-amap-secret"
    monkeypatch.setenv("amap_key", sentinel)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-aws-secret")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "google.json"))
    monkeypatch.setenv("DATABASE_URL", "synthetic-db-credential-url")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "synthetic-azure-key")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "synthetic-azure-connection")
    monkeypatch.setenv("GDAL_HTTP_USERPWD", "synthetic-gdal-password")
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy-user:proxy-pass@proxy.example.test:8443")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.test:8080")
    monkeypatch.setenv("GIS_WORKTABLE_RUNTIME_FLAG", "keep-runtime-setting")
    monkeypatch.setattr(tools, "_current_amap_key", sentinel)
    monkeypatch.setattr(tools, "_exec_call_count", 0)
    monkeypatch.setattr(tools, "_current_task_id", "")
    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))
    observed = {}

    def fake_run(command, **kwargs):
        script = open(command[1], encoding="utf-8").read()
        observed["script_has_key_symbol"] = "_AMAP_KEY" in script
        observed["script_has_sentinel"] = sentinel in script
        observed["child_env_credentials"] = {
            name: any(key.casefold() == name.casefold() for key in kwargs["env"])
            for name in ("AMAP_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY",
                         "GOOGLE_APPLICATION_CREDENTIALS", "DATABASE_URL", "AZURE_STORAGE_ACCOUNT_KEY",
                         "AZURE_STORAGE_CONNECTION_STRING", "GDAL_HTTP_USERPWD", "HTTPS_PROXY")
        }
        observed["runtime_env_preserved"] = kwargs["env"].get("GIS_WORKTABLE_RUNTIME_FLAG")
        observed["unauthenticated_proxy_preserved"] = kwargs["env"].get("HTTP_PROXY")
        observed["python_io_encoding"] = kwargs["env"].get("PYTHONIOENCODING")
        return subprocess.CompletedProcess(command, 0, "probe-ok\n", "")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    result = tools.execute_python.func("print('probe-ok')")

    assert "probe-ok" in result
    assert observed == {
        "script_has_key_symbol": False,
        "script_has_sentinel": False,
        "child_env_credentials": {
            "AMAP_KEY": False,
            "OPENAI_API_KEY": False,
            "AWS_SECRET_ACCESS_KEY": False,
            "GOOGLE_APPLICATION_CREDENTIALS": False,
            "DATABASE_URL": False,
            "AZURE_STORAGE_ACCOUNT_KEY": False,
            "AZURE_STORAGE_CONNECTION_STRING": False,
            "GDAL_HTTP_USERPWD": False,
            "HTTPS_PROXY": False,
        },
        "runtime_env_preserved": "keep-runtime-setting",
        "unauthenticated_proxy_preserved": "http://proxy.example.test:8080",
        "python_io_encoding": "utf-8",
    }


def test_execute_python_removes_injected_os_alias_before_user_code(monkeypatch, tmp_path):
    from backend.services import tools

    monkeypatch.setattr(tools, "_exec_call_count", 0)
    monkeypatch.setattr(tools, "_current_task_id", "")
    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))

    result = tools.execute_python.func("_os.listdir('.')")

    assert "代码执行错误" in result
    assert "NameError" in result
    assert "_os" in result


def test_execute_python_does_not_copy_symlinked_output_files(monkeypatch, tmp_path):
    from backend.services import tools

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(tools, "_exec_call_count", 0)
    monkeypatch.setattr(tools, "_current_task_id", "")
    monkeypatch.setattr(tools, "_temp_output_dir", str(output_dir))
    real_islink = os.path.islink
    observed = {}

    def fake_run(command, **_kwargs):
        exec_dir = os.path.dirname(command[1])
        candidate = os.path.join(exec_dir, "output", "linked.png")
        os.makedirs(os.path.dirname(candidate), exist_ok=True)
        with open(candidate, "wb") as generated:
            generated.write(b"linked content")
        observed["candidate"] = candidate
        monkeypatch.setattr(
            tools.os.path,
            "islink",
            lambda path: os.fspath(path) == candidate or real_islink(path),
        )
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    result = tools.execute_python.func("print('ok')")

    assert "代码执行成功" in result
    assert not (output_dir / "linked.png").exists()
    assert observed["candidate"]


def test_execute_python_chart_renames_do_not_overwrite_same_second(monkeypatch, tmp_path):
    from datetime import datetime as RealDateTime
    from backend.services import tools

    class FixedDateTime:
        @classmethod
        def now(cls):
            return RealDateTime(2026, 10, 27, 9, 0, 0)

    monkeypatch.setattr(tools.datetime, "datetime", FixedDateTime)
    monkeypatch.setattr(tools, "_add_pending_item", lambda *_args: None)
    source = tmp_path / "chart.png"
    source.write_bytes(b"new chart")
    collision = tmp_path / "20261027090000_chart.png"
    collision.write_bytes(b"existing chart")

    first = tools._rename_output_files({"chart.png"}, ".png", str(tmp_path))
    second = tools._rename_output_files({"chart.png"}, ".png", str(tmp_path))

    assert first[0] != collision.name
    assert second[0] != first[0]
    assert collision.read_bytes() == b"existing chart"
    assert (tmp_path / first[0]).read_bytes() == b"new chart"
    assert (tmp_path / second[0]).read_bytes() == b"new chart"


def test_importing_osmnx_does_not_inject_overpass_network_probe(monkeypatch, tmp_path):
    from backend.services import tools

    monkeypatch.setattr(tools, "_exec_call_count", 0)
    monkeypatch.setattr(tools, "_current_task_id", "")
    monkeypatch.setattr(tools, "_temp_output_dir", str(tmp_path))
    observed = {}

    def fake_run(command, **kwargs):
        observed["script"] = open(command[1], encoding="utf-8").read()
        return subprocess.CompletedProcess(command, 0, "local-only\n", "")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    result = tools.execute_python.func("import osmnx as ox\nprint('local-only')")

    assert "local-only" in result
    assert "OVERPass_MIRRORS" not in observed["script"]
    assert "requests.get(" not in observed["script"]
    assert "overpass-api.de" not in observed["script"]
