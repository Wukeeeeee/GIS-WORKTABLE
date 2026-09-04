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


def test_code_version_increments():
    """每次保存代码版本号递增"""
    tid = task_manager.create_task("测试版本", "s1")
    s1 = save_code(tid, "code_v1")
    s2 = save_code(tid, "code_v2")
    s3 = save_code(tid, "code_v3")

    assert s1 == 1
    assert s2 == 2
    assert s3 == 3
    assert get_latest_code(tid) == "code_v3"
    assert task_manager.get_code_version(tid, 1) == "code_v1"
    assert task_manager.get_code_version(tid, 2) == "code_v2"
    assert task_manager.get_code_version(tid, 3) == "code_v3"


# ============================================================
# 测试 2: Task 持久化（磁盘恢复）
# ============================================================

def test_task_persists_to_disk():
    """Task 保存到磁盘后可以重新加载"""
    tid = task_manager.create_task("持久化测试", "s2")
    save_code(tid, "print('hello')")

    # 清除内存缓存
    task_manager._tasks.clear()

    # 从磁盘重新加载
    task = task_manager.get_task(tid)
    assert task is not None
    assert task["user_goal"] == "持久化测试"
    assert task["current_step"] == 1


# ============================================================
# 测试 3: latest.py 恢复
# ============================================================

def test_latest_code_file_exists():
    """latest.py 文件始终存在且指向最新版本"""
    tid = task_manager.create_task("latest测试", "s3")
    save_code(tid, "step1_code")
    save_code(tid, "step2_code")
    save_code(tid, "step3_code")

    # 清除内存缓存
    task_manager._tasks.clear()

    latest = get_latest_code(tid)
    assert latest == "step3_code"

    # 验证 latest.py 文件真实存在
    code_dir = task_manager._code_dir(tid)
    assert os.path.exists(os.path.join(code_dir, "latest.py"))
    assert os.path.exists(os.path.join(code_dir, "step_001.py"))
    assert os.path.exists(os.path.join(code_dir, "step_002.py"))
    assert os.path.exists(os.path.join(code_dir, "step_003.py"))


# ============================================================
# 测试 4: Artifact 持久化
# ============================================================

def test_artifact_persists():
    """Artifact 注册后可以恢复"""
    tid = task_manager.create_task("Artifact测试", "s4")
    # 创建一个临时文件作为 artifact
    code_dir = task_manager._code_dir(tid)
    os.makedirs(code_dir, exist_ok=True)
    fake_png = os.path.join(code_dir, "test_map.png")
    with open(fake_png, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    art = register_artifact(tid, "test_map.png", fake_png,
                            artifact_type="image", created_by_step=1)
    assert art["status"] == "success"
    assert art["size"] > 0

    # 清除内存，从磁盘恢复
    artifacts = task_manager.get_artifacts(tid)
    assert len(artifacts) == 1
    assert artifacts[0]["filename"] == "test_map.png"
    assert artifacts[0]["status"] == "success"


def test_artifact_file_not_exist_marks_failed():
    """文件不存在时 Artifact 标记为 failed"""
    tid = task_manager.create_task("Artifact失败测试", "s4b")
    art = register_artifact(tid, "nonexistent.png", "/fake/path.png",
                            artifact_type="image", created_by_step=1)
    assert art["status"] == "failed"


# ============================================================
# 测试 5: 同一个 task_id 跨多轮
# ============================================================

def test_same_task_id_across_turns():
    """多轮对话使用同一个 task_id"""
    tid = task_manager.create_task("广州地图", "session_multi")
    save_code(tid, "step1_code")

    # 模拟第二轮：查找同一 session 的活跃任务
    found = task_manager.find_active_task_for_session("session_multi")
    assert found == tid

    # 第二轮继续保存代码
    save_code(tid, "step2_code")
    assert get_latest_code(tid) == "step2_code"
    assert task_manager.get_task(tid)["current_step"] == 2


# ============================================================
# 测试 6: Context Builder 提供上一轮完整 Python source code
# ============================================================

def test_context_builder_includes_latest_code():
    """Context Builder 构建的上下文包含最新 Python 源代码"""
    tid = task_manager.create_task("上下文测试", "s6")
    code = "import geopandas as gpd\ngdf = gpd.read_file('test.geojson')\nprint(gdf)"
    save_code(tid, code, label="读取GeoJSON")

    ctx = task_manager.build_task_context(tid)
    assert "上下文测试" in ctx
    assert "import geopandas" in ctx
    assert "step_001" in ctx
    assert "重要" in ctx


def test_context_builder_includes_gis_context():
    """Context Builder 包含 GIS 上下文"""
    tid = task_manager.create_task("GIS上下文", "s6b")
    task_manager.update_gis_context(tid, crs="EPSG:4326", data_path="/tmp/test.geojson")

    ctx = task_manager.build_task_context(tid)
    assert "EPSG:4326" in ctx
    assert "/tmp/test.geojson" in ctx


# ============================================================
# 测试 7: Sandbox failure 后 Task State 正确
# ============================================================

def test_execution_log_records_failure():
    """执行失败时 Task State 正确记录"""
    tid = task_manager.create_task("失败测试", "s7")
    step = save_code(tid, "bad_code")

    record = log_execution(tid, step, "bad_code", "", "failed",
                           stderr="SyntaxError", exit_code=1)
    assert record["status"] == "failed"
    assert record["exit_code"] == 1

    log = task_manager.get_exec_log(tid)
    assert len(log) == 1
    assert log[0]["status"] == "failed"


def test_execution_log_records_success():
    """执行成功时 Task State 正确记录"""
    tid = task_manager.create_task("成功测试", "s7b")
    step = save_code(tid, "print('hello')")

    record = log_execution(tid, step, "print('hello')", "", "success",
                           stdout="hello")
    assert record["status"] == "success"

    log = task_manager.get_exec_log(tid)
    assert len(log) == 1
    assert log[0]["status"] == "success"


# ============================================================
# 测试 8: Archive / Restore
# ============================================================

def test_archive_and_restore():
    """归档后任务不在默认列表中，恢复后重新出现"""
    tid = task_manager.create_task("归档测试", "s8")
    save_code(tid, "archived_code")

    # 归档
    assert task_manager.archive_task(tid)
    task = task_manager.get_task(tid)
    assert task["status"] == "archived"
    assert task["archived"] is True

    # 默认列表不包含
    tasks = task_manager.list_tasks("s8", include_archived=False)
    assert len(tasks) == 0

    # 包含归档的列表
    tasks = task_manager.list_tasks("s8", include_archived=True)
    assert len(tasks) == 1

    # 恢复
    assert task_manager.restore_task(tid)
    task = task_manager.get_task(tid)
    assert task["status"] == "active"
    assert task["archived"] is False

    tasks = task_manager.list_tasks("s8", include_archived=False)
    assert len(tasks) == 1


# ============================================================
# 测试 9: 不同 Task 之间 Context 不串
# ============================================================

def test_cross_task_isolation():
    """不同 Task 的代码和 Artifact 互不影响"""
    tid1 = task_manager.create_task("任务A", "s9")
    tid2 = task_manager.create_task("任务B", "s9")

    save_code(tid1, "code_for_A")
    save_code(tid2, "code_for_B")
    save_code(tid2, "code_for_B_v2")

    assert get_latest_code(tid1) == "code_for_A"
    assert get_latest_code(tid2) == "code_for_B_v2"
    assert task_manager.get_task(tid1)["current_step"] == 1
    assert task_manager.get_task(tid2)["current_step"] == 2

    # Context 不串
    ctx1 = task_manager.build_task_context(tid1)
    ctx2 = task_manager.build_task_context(tid2)
    assert "code_for_A" in ctx1
    assert "code_for_A" not in ctx2
    assert "code_for_B_v2" in ctx2
    assert "code_for_B_v2" not in ctx1


# ============================================================
# 测试 10: 多轮 Python 修改（step_001 → step_002 → step_003）
# ============================================================

def test_multi_step_code_evolution():
    """多轮代码修改：step_001 → step_002 → step_003"""
    tid = task_manager.create_task("广州地图", "s10")

    # 第一轮：生成广州地图
    code1 = """import geopandas as gpd
import matplotlib.pyplot as plt
gdf = gpd.read_file('gz_districts.geojson')
gdf.plot()
plt.savefig('gz_map_v1.png')"""
    step1 = save_code(tid, code1, label="生成广州地图")
    assert step1 == 1

    # 第二轮：加上比例尺和指北针
    code2 = """import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib_scalebar.scalebar import ScaleBar
gdf = gpd.read_file('gz_districts.geojson')
ax = gdf.plot()
ax.set_title('广州市行政区划')
ax.add_artist(ScaleBar(1))
# 指北针
ax.annotate('N', xy=(0.95, 0.05), xycoords='axes fraction', fontsize=20)
plt.savefig('gz_map_v2.png')"""
    step2 = save_code(tid, code2, label="加比例尺指北针")
    assert step2 == 2

    # 第三轮：修改配色
    code3 = """import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib_scalebar.scalebar import ScaleBar
gdf = gpd.read_file('gz_districts.geojson')
ax = gdf.plot(cmap='Blues')
ax.set_title('广州市行政区划 - 蓝色渐变')
ax.add_artist(ScaleBar(1))
ax.annotate('N', xy=(0.95, 0.05), xycoords='axes fraction', fontsize=20)
plt.savefig('gz_map_v3.png')"""
    step3 = save_code(tid, code3, label="蓝色渐变")
    assert step3 == 3

    # 验证所有版本都存在
    versions = task_manager.get_code_versions(tid)
    assert len(versions) == 3

    # latest 始终是最新版
    assert get_latest_code(tid) == code3

    # 可以读取任意历史版本
    assert task_manager.get_code_version(tid, 1) == code1
    assert task_manager.get_code_version(tid, 2) == code2
    assert task_manager.get_code_version(tid, 3) == code3

    # Context Builder 包含最新代码
    ctx = task_manager.build_task_context(tid)
    assert "cmap='Blues'" in ctx
    assert "step_003" in ctx

    # 清除内存，从磁盘恢复后依然正确
    task_manager._tasks.clear()
    assert get_latest_code(tid) == code3
    assert task_manager.get_task(tid)["current_step"] == 3


# ============================================================
# 测试: set_current_task / get_current_task_id
# ============================================================

def test_set_current_task():
    """set_current_task / get_current_task_id 正确工作"""
    set_current_task("abc123")
    assert get_current_task_id() == "abc123"
    set_current_task("")
    assert get_current_task_id() == ""


# ============================================================
# 测试: find_or_create_task 策略
# ============================================================

def test_find_or_create_task_reuses_existing():
    """有活跃任务时复用，不创建新任务"""
    tid1 = task_manager.find_or_create_task("s_reuse", "第一轮")
    tid2 = task_manager.find_or_create_task("s_reuse", "第二轮")
    assert tid1 == tid2


def test_find_or_create_task_creates_new():
    """没有活跃任务时创建新任务"""
    tid1 = task_manager.find_or_create_task("s_new1", "任务A")
    # 模拟任务完成（归档）
    task_manager.archive_task(tid1)
    tid2 = task_manager.find_or_create_task("s_new1", "任务B")
    assert tid1 != tid2


# ============================================================
# 测试: delete_task
# ============================================================

def test_delete_task():
    """删除任务后文件清除"""
    tid = task_manager.create_task("删除测试", "s_del")
    save_code(tid, "doomed_code")

    # 确认文件存在
    assert os.path.exists(task_manager._task_dir(tid))

    # 删除
    assert task_manager.delete_task(tid)

    # 确认文件已删除
    assert not os.path.exists(task_manager._task_dir(tid))
    assert task_manager.get_task(tid) is None
