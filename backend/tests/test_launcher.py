"""Launchers must never reuse a healthy service from another project."""
import json
import ctypes
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend import launcher


@pytest.mark.parametrize("payload, expected", [
    ({"status": "ok", "service": "soc-workbench"}, False),
    ({"status": "ok"}, False),
    ({**launcher.health_identity(), "workspace": "another-checkout"}, False),
    (launcher.health_identity(), True),
    ([], False),
])
def test_probe_requires_service_and_workspace(monkeypatch, payload, expected):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    monkeypatch.setattr(launcher.urllib.request, "build_opener", lambda *args: opener)
    assert bool(launcher.probe(8000)) is expected


def test_default_port_conflict_does_not_switch_ports(monkeypatch):
    monkeypatch.delenv("GIS_PORT", raising=False)
    monkeypatch.setattr(launcher, "port_available", lambda port: port >= 8002)
    monkeypatch.setattr(launcher, "probe", lambda port: None)
    with pytest.raises(RuntimeError, match="Port 8000"):
        launcher.select_port()


def test_port_selection_reuses_current_checkout(monkeypatch):
    monkeypatch.delenv("GIS_PORT", raising=False)
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    monkeypatch.setattr(launcher, "probe", lambda port: launcher.health_identity() if port == 8000 else None)
    assert launcher.select_port() == 8000


def test_default_port_and_explicit_override(monkeypatch):
    monkeypatch.delenv("GIS_PORT", raising=False)
    monkeypatch.setattr(launcher, "port_available", lambda port: True)
    assert launcher.select_port() == 8000
    monkeypatch.setenv("GIS_PORT", "8002")
    assert launcher.select_port() == 8002


def test_explicit_port_conflict_fails(monkeypatch):
    monkeypatch.setenv("GIS_PORT", "8000")
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    monkeypatch.setattr(launcher, "probe", lambda port: None)
    with pytest.raises(RuntimeError):
        launcher.select_port()


def test_stop_ignores_foreign_services(monkeypatch):
    monkeypatch.delenv("GIS_PORT", raising=False)
    monkeypatch.setattr("sys.argv", ["launcher", "stop"])
    monkeypatch.setattr(launcher, "probe", lambda port: None)
    kill = MagicMock()
    monkeypatch.setattr(launcher.os, "kill", kill)
    with pytest.raises(SystemExit) as exit_info:
        launcher.main()
    assert exit_info.value.code == 0
    kill.assert_not_called()


def test_abandoned_startup_lock_is_stale(tmp_path):
    lock_file = tmp_path / "start.lock"
    lock_file.write_text("", encoding="ascii")
    assert launcher._startup_lock_is_stale(lock_file, grace_seconds=0)


def test_active_startup_lock_is_not_stale(tmp_path):
    lock_file = tmp_path / "start.lock"
    lock_file.write_text(str(launcher.os.getpid()), encoding="ascii")
    assert not launcher._startup_lock_is_stale(lock_file)


def test_liveness_check_preserves_a_real_child_process():
    proc = subprocess.Popen(
        [launcher.sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert launcher._process_is_alive(proc.pid)
        assert proc.poll() is None
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=5)
    assert not launcher._process_is_alive(proc.pid)


@pytest.mark.parametrize("wait_status,expected", [(258, True), (0, False), (0xFFFFFFFF, True)])
def test_windows_liveness_uses_read_only_process_handle(monkeypatch, wait_status, expected):
    api = SimpleNamespace(OpenProcess=MagicMock(return_value=123),
                          WaitForSingleObject=MagicMock(return_value=wait_status),
                          CloseHandle=MagicMock())
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", MagicMock(return_value=api), raising=False)
    kill = MagicMock()
    monkeypatch.setattr(launcher.os, "kill", kill)
    assert launcher._process_is_alive(567) is expected
    api.OpenProcess.assert_called_once_with(0x00100000, False, 567)
    api.WaitForSingleObject.assert_called_once_with(123, 0)
    api.CloseHandle.assert_called_once_with(123)
    kill.assert_not_called()


@pytest.mark.parametrize("error,expected", [(87, False), (5, True)])
def test_windows_missing_and_inaccessible_processes(monkeypatch, error, expected):
    api = SimpleNamespace(OpenProcess=MagicMock(return_value=None),
                          WaitForSingleObject=MagicMock(), CloseHandle=MagicMock())
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", MagicMock(return_value=api), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    assert launcher._process_is_alive(567) is expected
    api.CloseHandle.assert_not_called()


@pytest.mark.parametrize("pid", [0, -1, True, None, "123", 2 ** 32])
def test_invalid_lock_pid_never_checks_a_process(monkeypatch, pid):
    kill = MagicMock()
    monkeypatch.setattr(launcher.os, "kill", kill)
    assert launcher._process_is_alive(pid) is False
    kill.assert_not_called()


@pytest.mark.parametrize("error,expected", [(None, True), (ProcessLookupError(), False),
                                          (PermissionError(), True), (OSError(), False)])
def test_posix_liveness_keeps_signal_zero_behavior(monkeypatch, error, expected):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    kill = MagicMock(side_effect=error)
    monkeypatch.setattr(launcher.os, "kill", kill)
    assert launcher._process_is_alive(567) is expected
    kill.assert_called_once_with(567, 0)


def test_non_ascii_abandoned_lock_can_be_recovered(tmp_path):
    lock_file = tmp_path / "start.lock"
    lock_file.write_bytes(b"\xffbroken")
    assert launcher._startup_lock_is_stale(lock_file, grace_seconds=0)


@pytest.mark.parametrize("short_write", [False, True])
def test_failed_lock_write_never_spawns_or_leaks_lock(tmp_path, monkeypatch, short_write):
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(launcher, "probe", lambda port: None)
    if short_write:
        monkeypatch.setattr(launcher.os, "write", lambda *args: 0)
    else:
        monkeypatch.setattr(launcher.os, "write", MagicMock(side_effect=OSError("disk full")))
    spawn = MagicMock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    with pytest.raises(OSError):
        launcher.start_backend(8010)
    spawn.assert_not_called()
    assert list((tmp_path / ".bootstrap").iterdir()) == []


@pytest.mark.parametrize("force_kill", [False, True])
def test_start_timeout_cleans_up_owned_process_and_lock(tmp_path, monkeypatch, force_kill):
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(launcher, "probe", lambda port: None)
    ticks = iter([0, 0, 0, 91])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(ticks))
    proc = MagicMock()
    proc.poll.return_value = None
    if force_kill:
        proc.wait.side_effect = [subprocess.TimeoutExpired("backend", 5), 0]
    monkeypatch.setattr(launcher.subprocess, "Popen", MagicMock(return_value=proc))
    with pytest.raises(RuntimeError, match="not ready"):
        launcher.start_backend(8010)
    proc.terminate.assert_called_once()
    assert proc.kill.call_count == int(force_kill)
    assert list((tmp_path / ".bootstrap").iterdir()) == []


def test_existing_backend_is_never_terminated_by_start(monkeypatch):
    monkeypatch.setattr(launcher, "probe", lambda port: {"pid": 123})
    spawn = MagicMock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    assert launcher.start_backend(8010) == 0
    spawn.assert_not_called()


def test_stop_timeout_reports_failure(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "candidate_ports", lambda: [8010])
    monkeypatch.setattr(launcher, "probe", lambda port: {"pid": 123})
    ticks = iter([0, 6])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(ticks))
    kill = MagicMock()
    monkeypatch.setattr(launcher.os, "kill", kill)
    assert launcher.stop_backend() == 1
    kill.assert_called_once_with(123, launcher.signal.SIGTERM)
    output = capsys.readouterr().out
    assert "still responds" in output and "Stopped GIS-WORKTABLE" not in output
    assert "No running" not in output


def test_stop_does_not_wait_for_a_replacement_backend(monkeypatch):
    monkeypatch.setattr(launcher, "candidate_ports", lambda: [8010])
    probes = iter([{"pid": 123}, {"pid": 456}])
    monkeypatch.setattr(launcher, "probe", lambda port: next(probes))
    kill = MagicMock()
    monkeypatch.setattr(launcher.os, "kill", kill)
    assert launcher.stop_backend() == 0
    kill.assert_called_once_with(123, launcher.signal.SIGTERM)


def test_stop_permission_error_returns_failure(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "candidate_ports", lambda: [8010])
    monkeypatch.setattr(launcher, "probe", lambda port: {"pid": 123})
    monkeypatch.setattr(launcher.os, "kill", MagicMock(side_effect=PermissionError("denied")))
    assert launcher.stop_backend() == 1
    assert "No running" not in capsys.readouterr().out


def test_browser_stamp_from_future_does_not_block_opening(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    bootstrap = tmp_path / ".bootstrap"
    bootstrap.mkdir()
    (bootstrap / "browser_8010.stamp").write_text("200", encoding="ascii")
    monkeypatch.setattr(launcher.time, "time", lambda: 100)
    open_browser = MagicMock()
    monkeypatch.setattr(launcher.webbrowser, "open", open_browser)
    assert launcher.open_browser(8010) == 0
    open_browser.assert_called_once_with("http://127.0.0.1:8010")
