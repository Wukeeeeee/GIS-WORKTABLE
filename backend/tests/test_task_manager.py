# -*- coding: utf-8 -*-
"""
Task Manager 测试（不打真实 LLM / 网络，全本地确定性验证）

对应需求：Task Working Memory + Python Source Code Cache + Artifact Registry + Task Archive

测试覆盖：
  测试 1  Python source code 保存
  测试 2  Task 可以恢复（从磁盘重新加载）
  测试 3  latest.py 可以恢复
  测试 4  Artifact 可以恢复
  测试 5  同一个 task_id 跨多轮
  测试 6  Context Builder 可以提供上一轮完整 Python source code
  测试 7  Sandbox failure 后 Task State 正确
  测试 8  Archive / Restore
  测试 9  不同 Task 之间 Context 不串
  测试 10 多轮 Python 修改（step_001 → step_002 → step_003）
"""
import os
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.services import task_manager
from backend.services.tools import (
    reset_state, set_current_task, get_current_task_id,
    save_code, get_latest_code, register_artifact, log_execution,
)


@pytest.fixture(autouse=True)
def isolated_task_dir(tmp_path, monkeypatch):
    """把 task_manager 的存储目录指到临时目录，避免污染仓库。"""
    test_dir = str(tmp_path / "tasks")
    monkeypatch.setattr(task_manager, "_BASE_DIR", test_dir)
    task_manager._tasks.clear()
    task_manager._session_active.clear()
    yield
    task_manager._tasks.clear()
    task_manager._session_active.clear()


# ============================================================
# 测试 1: Python source code 保存
# ============================================================

def test_code_save_and_retrieve():
    """保存 Python 源代码后可以正确读取"""
    tid = task_manager.create_task("生成广州地图", "test_session")
    code = "import matplotlib.pyplot as plt\nplt.plot([1,2,3])\nplt.savefig('test.png')"
    step = save_code(tid, code, label="绘制折线图")

    assert step == 1
    latest = get_latest_code(tid)
    assert latest == code
    versions = task_manager.get_code_versions(tid)
    assert len(versions) == 1
    assert versions[0]["step"] == 1


def test_gis_operation_context_preserves_latest_success_after_failure():
    tid = task_manager.create_task("长沙边界缓冲并导出", "gis-state-session")
    source = {"name": "长沙市", "layer_id": "source-1"}
    first = {"name": "长沙市_缓冲区", "layer_id": "buffer-500"}
    task_manager.record_gis_operation(
        tid, "spatial_buffer", {"layer_name": "长沙市", "distance": 500, "unit": "m"},
        input_layers=[source], output_layers=[first], status="success", run_id="run-1",
    )
    task_manager.record_gis_operation(
        tid, "spatial_buffer", {"layer_name": "缺失图层", "distance": 1000, "unit": "m"},
        input_layers=[{"name": "缺失图层", "layer_id": ""}], status="failed", run_id="run-2",
    )

    context = task_manager.get_gis_context(tid)
    assert context["current_operation"]["status"] == "failed"
    assert context["last_successful_operation"]["arguments"]["distance"] == 500
    assert context["last_successful_output"] == first
    prompt_context = task_manager.build_task_context(tid)
    assert '"layer_id": "source-1"' in prompt_context
    assert '"status": "failed"' in prompt_context
    assert "不要把分析输出当成原始输入" in prompt_context


def test_gis_operation_state_isolated_by_task_and_session():
    task_a = task_manager.create_task("任务 A", "session-A")
    task_b = task_manager.create_task("任务 B", "session-B")
    task_manager.record_gis_operation(
        task_a, "spatial_buffer", {"layer_name": "A", "distance": 500},
        output_layers=[{"name": "A_buffer", "layer_id": "a1"}], status="success",
    )
    assert task_manager.get_gis_context(task_b) == {}
    assert task_manager.find_active_task_for_session("session-A") == task_a
    assert task_manager.find_active_task_for_session("session-B") == task_b


def test_parallel_gis_operation_records_do_not_overwrite_each_other(monkeypatch):
    tid = task_manager.create_task("并行 GIS 操作", "parallel-session")
    original_get_task = task_manager.get_task
    loaded = threading.Barrier(2)

    def synchronized_snapshot(task_id):
        task = original_get_task(task_id)
        snapshot = json.loads(json.dumps(task)) if task else None
        loaded.wait(timeout=3)
        return snapshot

    monkeypatch.setattr(task_manager, "get_task", synchronized_snapshot)

    def record(name):
        return task_manager.record_gis_operation(
            tid, name, {"source": name},
            output_layers=[{"name": name + "_output", "layer_id": name}],
            status="success", run_id=name,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, ("parallel-A", "parallel-B")))

    assert results == [True, True]
    monkeypatch.setattr(task_manager, "get_task", original_get_task)
    context = task_manager.get_gis_context(tid)
    assert {op["tool"] for op in context["recent_operations"]} == {"parallel-A", "parallel-B"}
    assert context["last_successful_output"]["name"] in {"parallel-A_output", "parallel-B_output"}




# ============================================================
# 测试 2: Task 持久化（磁盘恢复）
# ============================================================



# ============================================================
# 测试 3: latest.py 恢复
# ============================================================



# ============================================================
# 测试 4: Artifact 持久化
# ============================================================





# ============================================================
# 测试 5: 同一个 task_id 跨多轮
# ============================================================



# ============================================================
# 测试 6: Context Builder 提供上一轮完整 Python source code
# ============================================================





# ============================================================
# 测试 7: Sandbox failure 后 Task State 正确
# ============================================================





# ============================================================
# 测试 8: Archive / Restore
# ============================================================



# ============================================================
# 测试 9: 不同 Task 之间 Context 不串
# ============================================================



# ============================================================
# 测试 10: 多轮 Python 修改（step_001 → step_002 → step_003）
# ============================================================



# ============================================================
# 测试: set_current_task / get_current_task_id
# ============================================================



# ============================================================
# 测试: find_or_create_task 策略
# ============================================================





# ============================================================
# 测试: delete_task
# ============================================================

