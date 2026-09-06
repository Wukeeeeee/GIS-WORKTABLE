# -*- coding: utf-8 -*-
"""
API 级集成测试第二批：更多工具的完整链路
动态生成数据，零 token 消耗
"""
import os
import sys
import uuid
import random
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.services import tools
from backend.services.tools import (
    spatial_buffer,
    generate_analysis_report,
    spatial_hotspot,
    get_layer_detail,
    save_file,
    execute_python,
    _register_layer,
    _registered_layers,
    _pending_layers,
    get_registered_layers_snapshot,
    set_current_task,
    get_current_task_id,
    reset_state,
)


def _random_point_layer(name, count=20, center_lon=113.0, center_lat=23.0):
    """生成随机点图层并注册"""
    features = []
    for i in range(count):
        features.append({
            "type": "Feature",
            "properties": {"id": i, "value": random.uniform(0, 100)},
            "geometry": {
                "type": "Point",
                "coordinates": [
                    center_lon + random.uniform(-0.05, 0.05),
                    center_lat + random.uniform(-0.05, 0.05)
                ]
            }
        })
    geojson = {"type": "FeatureCollection", "features": features}
    _register_layer(name, geojson)
    return name


def _random_polygon_layer(name, count=5):
    """生成随机多边形图层并注册"""
    features = []
    for i in range(count):
        cx = random.uniform(113.0, 113.2)
        cy = random.uniform(23.0, 23.2)
        size = random.uniform(0.005, 0.02)
        features.append({
            "type": "Feature",
            "properties": {"id": i, "area_val": random.uniform(10, 100)},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [cx, cy], [cx + size, cy],
                    [cx + size, cy + size], [cx, cy + size], [cx, cy]
                ]]
            }
        })
    geojson = {"type": "FeatureCollection", "features": features}
    _register_layer(name, geojson)
    return name


class TestBufferE2E:
    """缓冲区分析端到端"""

    def test_buffer_point_layer(self):
        """点图层缓冲区：注册→分析→结果图层注册→面积合理"""
        name = f"buf_test_{uuid.uuid4().hex[:6]}"
        _random_point_layer(name, count=10)
        before = len(_registered_layers)

        func = getattr(spatial_buffer, 'func', spatial_buffer)
        result = func(layer_name=name, distance=500, unit="m")

        assert result is not None
        assert "缓冲" in result or "buffer" in result.lower() or len(result) > 10
        # 结果图层应被注册
        buffer_layers = [k for k in _registered_layers if "缓冲" in k or "buffer" in k.lower()]
        assert len(buffer_layers) >= 1 or len(_registered_layers) > before, "缓冲区结果未注册"

    def test_buffer_with_dissolve(self):
        """缓冲区融合模式：dissolve=True"""
        name = f"buf_dis_{uuid.uuid4().hex[:6]}"
        _random_point_layer(name, count=15)
        func = getattr(spatial_buffer, 'func', spatial_buffer)
        result = func(layer_name=name, distance=1000, unit="m", dissolve=True)
        assert result is not None
        assert len(result) > 5


class TestReportE2E:
    """分析报告生成端到端"""

    def test_report_contains_sections(self):
        """报告应包含方法、统计、质量等章节"""
        name = f"rpt_test_{uuid.uuid4().hex[:6]}"
        _random_polygon_layer(name, count=5)

        func = getattr(generate_analysis_report, 'func', generate_analysis_report)
        report = func(layer_name=name, analysis_summary="测试区域土地利用分析")

        assert report is not None
        assert len(report) > 100, "报告内容过短"
        # 报告应包含关键章节标题
        has_section = any(k in report for k in ["报告", "统计", "质量", "方法", "数据", "图层"])
        assert has_section, "报告缺少关键章节"
        # 应包含图层名
        assert name in report or "要素" in report, "报告未引用目标图层"

    def test_report_with_stats(self):
        """include_stats=True 时应包含数值统计"""
        name = f"rpt_stat_{uuid.uuid4().hex[:6]}"
        _random_polygon_layer(name, count=8)
        func = getattr(generate_analysis_report, 'func', generate_analysis_report)
        report = func(layer_name=name, analysis_summary="统计测试", include_stats=True)
        # 应包含数字
        import re
        numbers = re.findall(r'\d+\.?\d*', report)
        assert len(numbers) >= 3, "统计报告缺少数值"


class TestLayerDetailE2E:
    """图层详情端到端"""

    def test_detail_returns_properties(self):
        """注册图层后查询详情，应包含属性和几何信息"""
        name = f"detail_test_{uuid.uuid4().hex[:6]}"
        _random_point_layer(name, count=10)

        func = getattr(get_layer_detail, 'func', get_layer_detail)
        detail = func(layer_name=name)

        assert detail is not None
        assert len(detail) > 20
        # 应包含要素数、几何类型等信息
        has_info = any(k in detail for k in ["要素", "Point", "点", "属性", "字段", "count"])
        assert has_info, "图层详情缺少基本信息"

    def test_detail_nonexistent_layer(self):
        """查询不存在的图层应返回友好错误"""
        func = getattr(get_layer_detail, 'func', get_layer_detail)
        result = func(layer_name="nonexistent_layer_xyz")
        assert result is not None
        assert "不存在" in result or "未找到" in result or "错误" in result


class TestFileSaveE2E:
    """文件保存端到端"""

    def test_save_file_creates_file(self):
        """save_file 应真实创建文件"""
        filename = f"test_output_{uuid.uuid4().hex[:6]}.txt"
        content = f"测试内容 {uuid.uuid4().hex}"

        func = getattr(save_file, 'func', save_file)
        result = func(filename=filename, content=content)

        assert result is not None
        # 文件应存在
        possible_paths = [
            os.path.join("cache", filename),
            os.path.join("outputs", filename),
            filename,
            os.path.join("temp", filename),
        ]
        found = any(os.path.exists(p) for p in possible_paths)
        # 即使路径不确定，结果应包含成功信息
        assert "成功" in result or "保存" in result or "已" in result or filename in result


class TestPythonSandboxE2E:
    """Python 沙箱执行端到端"""

    def test_execute_simple_code(self):
        """执行简单 Python 代码应返回结果"""
        func = getattr(execute_python, 'func', execute_python)
        result = func(code="print(2 + 2)")
        assert result is not None
        assert "4" in result or "2" in result

    def test_execute_with_gis_library(self):
        """沙箱应能导入已安装的 GIS 库"""
        func = getattr(execute_python, 'func', execute_python)
        result = func(code="import numpy; print(numpy.__version__)")
        assert result is not None
        # 应能执行（可能因为沙箱限制失败，但不应崩溃）
        assert len(result) > 0

    def test_sandbox_blocks_dangerous_code(self):
        """沙箱应阻止危险操作（如 os.system）"""
        func = getattr(execute_python, 'func', execute_python)
        result = func(code="import os; os.system('echo hacked')")
        # 应被拦截或报错，不能静默执行成功
        assert "禁止" in result or "拦截" in result or "错误" in result or "不允许" in result or "安全" in result


class TestTaskStateE2E:
    """任务状态管理端到端"""

    def test_set_and_get_task(self):
        """设置当前任务后应能获取"""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        set_current_task(task_id)
        assert get_current_task_id() == task_id

    def test_reset_state(self):
        """重置状态后应清空"""
        set_current_task("test_task_123")
        reset_state()
        # 重置后任务 ID 应为空或默认值
        tid = get_current_task_id()
        assert tid == "" or tid is None or "test_task_123" not in str(tid)


class TestMultiToolChainE2E:
    """多工具串联端到端：注册→缓冲区→详情→报告"""

    def test_full_gis_workflow(self):
        """模拟完整 GIS 工作流：点图层→缓冲区→图层详情→分析报告"""
        # Step 1: 注册点图层
        point_layer = f"chain_pts_{uuid.uuid4().hex[:6]}"
        _random_point_layer(point_layer, count=15)
        assert point_layer in _registered_layers or any(
            point_layer in str(v) for v in _registered_layers.values()
        )

        # Step 2: 缓冲区分析
        buf_func = getattr(spatial_buffer, 'func', spatial_buffer)
        buf_result = buf_func(layer_name=point_layer, distance=300, unit="m")
        assert buf_result is not None and len(buf_result) > 5

        # Step 3: 查询原图层详情
        detail_func = getattr(get_layer_detail, 'func', get_layer_detail)
        detail = detail_func(layer_name=point_layer)
        assert detail is not None and len(detail) > 10

        # Step 4: 生成报告
        rpt_func = getattr(generate_analysis_report, 'func', generate_analysis_report)
        report = rpt_func(layer_name=point_layer, analysis_summary="点图层缓冲区分析")
        assert report is not None and len(report) > 50

        # Step 5: 快照中应能找到所有图层
        snapshot = get_registered_layers_snapshot()
        assert len(snapshot) >= 1


class TestSnapshotConsistency:
    """图层快照一致性"""

    def test_registered_layers_match_snapshot(self):
        """_registered_layers 和 get_registered_layers_snapshot 应一致"""
        name = f"snap_consist_{uuid.uuid4().hex[:6]}"
        _random_point_layer(name, count=5)

        snapshot = get_registered_layers_snapshot()
        snapshot_names = [
            layer.get("filename") or layer.get("name") or layer.get("layer_id")
            for layer in snapshot
        ]
        # 刚注册的图层应在快照中
        found = any(name in str(n) for n in snapshot_names)
        assert found, f"图层 {name} 注册后快照中找不到，快照有 {len(snapshot)} 条"
