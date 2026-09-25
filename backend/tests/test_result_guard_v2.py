# -*- coding: utf-8 -*-
"""result_guard v2 三方一致性核对测试

覆盖：Claim ↔ Registry ↔ Filesystem 的所有组合
"""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services import result_guard as RG
from backend.services import task_manager


OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "gis_worktable_output")


def _create_file(filename, content="hello"):
    """在 output 目录创建文件，返回绝对路径"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _cleanup_file(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(path):
        os.remove(path)


def _make_task():
    """创建一个临时任务，返回 task_id"""
    return task_manager.create_task("test-v2-" + os.urandom(4).hex())


# ============================================================
# 三方核对状态机
# ============================================================

def test_claimed_registered_exists_verified():
    """claimed + registered + exists + non_empty + path_matches → VERIFIED"""
    task_id = _make_task()
    fn = "v2_verified.png"
    try:
        path = _create_file(fn, "fake-image-data")
        task_manager.register_artifact(task_id, fn, path, artifact_type="image")
        text = f"已生成 output/{fn}"
        res = RG.verify_result(text, {}, task_id=task_id)
        assert res["registry_count"] == 1
        checks = res["artifact_checks"]
        assert len(checks) == 1
        assert checks[0]["status"] == RG.ST_VERIFIED
        assert checks[0]["claimed"] is True
        assert checks[0]["registered"] is True
        assert checks[0]["exists"] is True
        assert checks[0]["non_empty"] is True
        assert checks[0]["belongs_to_current_task"] is True
        # VERIFIED 不应产生 issue
        assert res["ok"] is True
    finally:
        _cleanup_file(fn)


def test_claimed_registered_missing():
    """claimed + registered + missing（文件被删）→ MISSING"""
    task_id = _make_task()
    fn = "v2_missing.png"
    path = _create_file(fn, "data")
    task_manager.register_artifact(task_id, fn, path, artifact_type="image")
    # 删除文件
    os.remove(path)
    text = f"已生成 output/{fn}"
    res = RG.verify_result(text, {}, task_id=task_id)
    checks = res["artifact_checks"]
    assert len(checks) == 1
    assert checks[0]["status"] == RG.ST_MISSING
    assert checks[0]["exists"] is False
    assert res["ok"] is False


def test_claimed_unregistered_exists():
    """claimed + unregistered + exists（文件有但没登记）→ UNREGISTERED"""
    task_id = _make_task()
    fn = "v2_unregistered.png"
    try:
        _create_file(fn, "data")
        # 不注册 artifact
        text = f"已生成 output/{fn}"
        res = RG.verify_result(text, {}, task_id=task_id)
        checks = res["artifact_checks"]
        assert len(checks) == 1
        assert checks[0]["status"] == RG.ST_UNREGISTERED
        assert checks[0]["registered"] is False
        assert checks[0]["exists"] is True
        # UNREGISTERED 应产生 issue
        assert res["ok"] is False
    finally:
        _cleanup_file(fn)


def test_claimed_unregistered_missing():
    """claimed + unregistered + missing → MISSING"""
    task_id = _make_task()
    fn = "v2_ghost.png"
    # 文件不存在，也不注册
    text = f"已生成 output/{fn}"
    res = RG.verify_result(text, {}, task_id=task_id)
    checks = res["artifact_checks"]
    assert len(checks) == 1
    assert checks[0]["status"] == RG.ST_MISSING
    assert checks[0]["exists"] is False
    assert checks[0]["registered"] is False


def test_registered_exists_not_claimed_silent():
    """registered + exists + not claimed → 静默（不产生 issue）"""
    task_id = _make_task()
    fn = "v2_silent.png"
    try:
        path = _create_file(fn, "data")
        task_manager.register_artifact(task_id, fn, path, artifact_type="image")
        # LLM 回复里不提这个文件
        text = "分析完成。"
        res = RG.verify_result(text, {}, task_id=task_id)
        # 没有声称 → 没有 check
        assert len(res["artifact_checks"]) == 0
        assert res["ok"] is True
    finally:
        _cleanup_file(fn)


def test_empty_file():
    """claimed + registered + exists + size=0 → EMPTY"""
    task_id = _make_task()
    fn = "v2_empty.png"
    try:
        path = _create_file(fn, "")  # 空文件
        task_manager.register_artifact(task_id, fn, path, artifact_type="image")
        text = f"已生成 output/{fn}"
        res = RG.verify_result(text, {}, task_id=task_id)
        checks = res["artifact_checks"]
        assert len(checks) == 1
        assert checks[0]["status"] == RG.ST_EMPTY
        assert checks[0]["non_empty"] is False
        assert res["ok"] is False
    finally:
        _cleanup_file(fn)


# ============================================================
# 多 artifact / 中文文件名 / 边界情况
# ============================================================

def test_multiple_artifacts_mixed_status():
    """多 artifact：一个 VERIFIED + 一个 MISSING"""
    task_id = _make_task()
    fn_ok = "v2_multi_ok.png"
    fn_bad = "v2_multi_bad.png"
    try:
        path_ok = _create_file(fn_ok, "data")
        task_manager.register_artifact(task_id, fn_ok, path_ok, artifact_type="image")
        # bad 文件不创建
        text = f"已生成 output/{fn_ok} 和 output/{fn_bad}"
        res = RG.verify_result(text, {}, task_id=task_id)
        checks = res["artifact_checks"]
        assert len(checks) == 2
        statuses = {c["path"]: c["status"] for c in checks}
        assert statuses[f"output/{fn_ok}"] == RG.ST_VERIFIED
        assert statuses[f"output/{fn_bad}"] == RG.ST_MISSING
        assert res["ok"] is False  # 因为有 MISSING
    finally:
        _cleanup_file(fn_ok)


def test_chinese_filename():
    """中文文件名"""
    task_id = _make_task()
    fn = "v2_专题图.png"
    try:
        path = _create_file(fn, "data")
        task_manager.register_artifact(task_id, fn, path, artifact_type="image")
        text = f"已生成 output/{fn}"
        res = RG.verify_result(text, {}, task_id=task_id)
        checks = res["artifact_checks"]
        assert len(checks) == 1
        assert checks[0]["status"] == RG.ST_VERIFIED
    finally:
        _cleanup_file(fn)


def test_relative_path_normalized():
    """相对路径 output/xxx.png 与 /output/xxx.png 应解析到同一文件"""
    a = RG.resolve_artifact_path("output/rel.png")
    b = RG.resolve_artifact_path("/output/rel.png")
    assert a == b


def test_non_output_dir_path_ignored():
    """非 output/cache/uploads/reports/data 目录的路径不参与校验"""
    text = "请参考 /home/user/notes.txt 和 output/real.png"
    # /home/user/notes.txt 不在已知目录 → 不参与
    # output/real.png 参与（即使文件不存在）
    paths = RG.extract_output_paths(text)
    assert "output/real.png" in paths
    # /home/user/notes.txt 不应被提取
    assert not any("notes.txt" in p for p in paths)


# ============================================================
# Registry 路径与实际路径不一致
# ============================================================

def test_registry_path_mismatch():
    """registry 登记的路径与实际解析路径不一致 → PATH_MISMATCH"""
    task_id = _make_task()
    fn = "v2_mismatch.png"
    # 创建真实文件
    real_path = _create_file(fn, "data")
    # 注册时用一个"错误"的路径（比如多了一个不存在的子目录）
    wrong_path = os.path.join(OUTPUT_DIR, "wrong_subdir", fn)
    task_manager.register_artifact(task_id, fn, wrong_path, artifact_type="image")
    # LLM 声称 output/v2_mismatch.png（指向真实文件）
    text = f"已生成 output/{fn}"
    res = RG.verify_result(text, {}, task_id=task_id)
    checks = res["artifact_checks"]
    assert len(checks) == 1
    # 真实文件存在，但 registry 登记的路径与实际不一致
    # 注意：basename 匹配（都是 v2_mismatch.png），但 normpath 不一致
    assert checks[0]["status"] == RG.ST_PATH_MISMATCH
    _cleanup_file(fn)


# ============================================================
# 其他 task 的 artifact 不应混淆
# ============================================================

def test_other_task_artifact_not_confused():
    """其他 task 登记的 artifact 不应被当作当前 task 的产物"""
    task_a = _make_task()
    task_b = _make_task()
    fn = "v2_other_task.png"
    try:
        path = _create_file(fn, "data")
        # 在 task_a 注册
        task_manager.register_artifact(task_a, fn, path, artifact_type="image")
        # task_b 声称这个文件
        text = f"已生成 output/{fn}"
        res = RG.verify_result(text, {}, task_id=task_b)
        checks = res["artifact_checks"]
        assert len(checks) == 1
        # task_b 的 registry 里没有这个文件 → UNREGISTERED（因为 task_b 没有登记）
        # 注意：check 只查 task_id 对应的 registry
        assert checks[0]["registered"] is False
        assert checks[0]["status"] == RG.ST_UNREGISTERED
    finally:
        _cleanup_file(fn)


# ============================================================
# 向后兼容：不传 task_id 时保持原行为
# ============================================================

def test_backward_compat_no_task_id():
    """不传 task_id 时，registry_count=0 且不做三方核对"""
    fn = "v2_compat.png"
    try:
        _create_file(fn, "data")
        text = f"已生成 output/{fn}"
        # 不传 task_id
        res = RG.verify_result(text, {}, task_id=None)
        assert res["registry_count"] == 0
        assert res["artifact_checks"] == []
        # 但原文件系统核对仍然工作
        assert res["ok"] is True
    finally:
        _cleanup_file(fn)


def test_backward_compat_missing_file_no_task_id():
    """不传 task_id 时，文件不存在仍报 missing"""
    text = "已生成 output/v2_ghost_nonexist.png"
    res = RG.verify_result(text, {}, task_id=None)
    assert res["ok"] is False
    assert "output/v2_ghost_nonexist.png" in res["missing_paths"]
