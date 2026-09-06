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
    yield
    task_manager._tasks.clear()


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

