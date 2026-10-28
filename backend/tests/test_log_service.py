import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.services import log_service as logs


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "_LOG_DIR", str(tmp_path / "logs"))


def write_records(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def test_session_names_do_not_collide_and_records_have_distinct_ids():
    logs.log_turn("a/b", "first", "执行失败")
    logs.log_turn("a\\b", "second", "成功")
    first, second = logs.get_temp_log("a/b"), logs.get_temp_log("a\\b")
    assert first[0]["user"] == "first"
    assert second[0]["user"] == "second"
    assert first[0]["record_id"] != second[0]["record_id"]


def test_malformed_layer_snapshot_does_not_drop_the_conversation_record():
    logs.log_turn(
        "s", "请检查这张图", "已显示在地图",
        layers_snapshot={
            "valid": {"feature_count": 1, "geometry_types": ["Point"]},
            "broken": None,
        },
    )

    records = logs.get_temp_log("s")
    assert len(records) == 1
    assert records[0]["user"] == "请检查这张图"
    assert records[0]["layers"] == {"valid": {"feature_count": 1, "geometry_types": ["Point"]}}


def test_archive_retains_only_issues_and_clears_temporary_log():
    logs.log_turn("s", "normal", "完成")
    logs.log_turn("s", "problem", "执行失败")
    assert logs.archive_temp_to_perm("s") is True
    assert logs.get_temp_log("s") == []
    permanent = logs.get_perm_log()
    assert len(permanent) == 1
    assert permanent[0]["user"] == "problem"
    assert permanent[0]["session_id"] == "s"


def test_failed_batch_commit_keeps_both_original_logs_and_retries_once(monkeypatch):
    write_records(logs._perm_path(), [{"record_id": "old", "user": "old", "ai": "错误"}])
    logs.log_turn("s", "one", "执行失败")
    logs.log_turn("s", "two", "执行失败")
    original = Path(logs._perm_path()).read_bytes()
    with monkeypatch.context() as patch:
        def failed_replace(*args):
            raise OSError("disk unavailable")
        patch.setattr(logs.os, "replace", failed_replace)
        assert logs.archive_temp_to_perm("s") is False
    assert Path(logs._perm_path()).read_bytes() == original
    assert len(logs.get_temp_log("s")) == 2
    assert logs.archive_temp_to_perm("s") is True
    assert len(logs.get_perm_log(None)) == 3
    assert not list(Path(logs._LOG_DIR).glob(".log-archive-*.tmp"))


@pytest.mark.parametrize("legacy", [False, True])
def test_retry_after_failed_clear_does_not_duplicate_issues(monkeypatch, legacy):
    if legacy:
        record = {"time": "2026-10-23T12:34:56+08:00", "user": "same", "ai": "失败"}
        write_records(logs._temp_path("s"), [record, record])
    else:
        logs.log_turn("s", "same", "失败")
        logs.log_turn("s", "same", "失败")
    with monkeypatch.context() as patch:
        patch.setattr(logs, "clear_temp_log", lambda *args: False)
        assert logs.archive_temp_to_perm("s") is False
    assert len(logs.get_perm_log(None)) == 2
    assert logs.archive_temp_to_perm("s") is True
    assert len(logs.get_perm_log(None)) == 2
    assert logs.get_temp_log("s") == []


@pytest.mark.parametrize("unreadable", ["temp", "permanent"])
def test_unreadable_log_does_not_clear_pending_records(monkeypatch, unreadable):
    logs.log_turn("s", "keep", "失败")
    target = logs._temp_path("s") if unreadable == "temp" else logs._perm_path()
    real_open = open

    def denied(path, *args, **kwargs):
        if os.fspath(path) == target:
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", denied)
        assert logs.archive_temp_to_perm("s") is False
    assert len(logs.get_temp_log("s")) == 1


def test_turn_written_during_archive_remains_in_new_temporary_log(monkeypatch):
    logs.log_turn("s", "old", "失败")
    entered, commit, writer_done = threading.Event(), threading.Event(), threading.Event()
    original_write = logs._write_issues_atomic

    def paused_commit(issues):
        entered.set()
        assert commit.wait(5)
        original_write(issues)

    def write_turn():
        logs.log_turn("s", "new", "成功")
        writer_done.set()

    monkeypatch.setattr(logs, "_write_issues_atomic", paused_commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        archive = pool.submit(logs.archive_temp_to_perm, "s")
        assert entered.wait(5)
        writer = pool.submit(write_turn)
        try:
            assert not writer_done.wait(0.1)
        finally:
            commit.set()
        assert archive.result(timeout=5) is True
        writer.result(timeout=5)
    assert [record["user"] for record in logs.get_temp_log("s")] == ["new"]
    assert [record["user"] for record in logs.get_perm_log()] == ["old"]


def test_corrupt_lines_do_not_hide_later_records():
    path = Path(logs._temp_path("s"))
    path.parent.mkdir(parents=True)
    path.write_bytes(b'broken\n\xff\n' + json.dumps({"user": "retained", "ai": "失败"}, ensure_ascii=False).encode() + b'\n')
    assert logs.get_temp_log("s")[0]["user"] == "retained"
    assert logs.archive_temp_to_perm("s") is True
    assert logs.get_perm_log()[0]["user"] == "retained"


def test_stats_and_export_include_more_than_fifty_permanent_records():
    from backend.main import logs_stats, logs_export
    write_records(logs._perm_path(), [
        {"time": "2026-10-23T12:34:56+08:00", "user": f"issue-{index}", "ai": "失败"}
        for index in range(75)
    ])
    assert len(logs.get_perm_log()) == 50
    assert asyncio.run(logs_stats("empty"))["perm_count"] == 75
    exported = asyncio.run(logs_export("empty")).body.decode("utf-8")
    assert "历史问题记录：75 条" in exported
    assert "issue-0" in exported and "issue-74" in exported
    assert exported.count("**用户：**") == 75


def test_log_tool_shows_permanent_history_when_current_session_is_empty(monkeypatch):
    from backend.services import tools, pending_action
    write_records(logs._perm_path(), [{
        "time": "2026-10-23T12:34:56.123456+08:00", "user": "archived issue", "ai": "失败",
    }])
    monkeypatch.setattr(pending_action, "get_active_session", lambda: "empty")
    output = tools.get_session_logs.func()
    assert "archived issue" in output
    assert "2026-10-23 12:34:56" in output


def test_reading_missing_logs_does_not_create_directories():
    assert logs.get_temp_log("new") == []
    assert logs.get_perm_log() == []
    assert not Path(logs._LOG_DIR).exists()


@pytest.mark.parametrize("layers", [["bad"], {"bad": None}])
def test_malformed_layer_snapshot_does_not_abort_archiving(layers):
    write_records(logs._temp_path("s"), [{
        "user": "display", "ai": "已加载到地图", "layers": layers,
    }])
    assert logs.archive_temp_to_perm("s") is True
    assert logs.get_perm_log()[0]["user"] == "display"


def test_legacy_shared_log_is_exportable_without_becoming_current_session():
    from backend.main import logs_stats, logs_export
    legacy_path = Path(logs._LOG_DIR) / "temp.jsonl"
    write_records(legacy_path, [{"user": "legacy-shared", "ai": "old answer"}])
    logs.log_turn("new-session", "current-only", "new answer")
    stats = asyncio.run(logs_stats("new-session"))
    assert stats["temp_count"] == 1
    assert stats["legacy_temp_count"] == 1
    exported = asyncio.run(logs_export("new-session")).body.decode("utf-8")
    assert "旧版共享会话记录（未区分会话）" in exported
    assert "legacy-shared" in exported and "current-only" in exported
    assert [record["user"] for record in logs.get_temp_log("new-session")] == ["current-only"]
    assert legacy_path.exists()
