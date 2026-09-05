# -*- coding: utf-8 -*-
"""
GIS 专业知识库加载测试

覆盖：
- knowledge/ 目录存在且包含 11 个模块
- _KNOWLEDGE_MAP 标签与文件一一对应
- _load_skill_from_file 能正确加载知识库模块
- 知识库模块包含必需的 8 个章节
- 旧 skills/ 加载不受影响（向后兼容）
- 路由提示词包含知识库标签
"""
import os
import pytest

from backend.services.ai_service import (
    _KNOWLEDGE_DIR,
    _KNOWLEDGE_MAP,
    _load_skill_from_file,
    _GLM_ROUTER_PROMPT,
    _SKILLS_DIR,
)


class TestKnowledgeBase:
    """知识库目录和文件结构测试"""

    def test_knowledge_dir_exists(self):
        assert os.path.isdir(_KNOWLEDGE_DIR), "knowledge/ 目录不存在"

    def test_knowledge_map_has_11_entries(self):
        assert len(_KNOWLEDGE_MAP) == 11, f"知识库映射应有 11 条，实际 {len(_KNOWLEDGE_MAP)}"

    def test_all_knowledge_files_exist(self):
        missing = []
        for label, filename in _KNOWLEDGE_MAP.items():
            path = os.path.join(_KNOWLEDGE_DIR, filename)
            if not os.path.isfile(path):
                missing.append(f"{label} -> {filename}")
        assert not missing, f"知识库文件缺失: {missing}"

    def test_all_knowledge_files_nonempty(self):
        for label, filename in _KNOWLEDGE_MAP.items():
            path = os.path.join(_KNOWLEDGE_DIR, filename)
            size = os.path.getsize(path)
            assert size > 100, f"知识库文件 {filename} 内容过空 ({size} bytes)"


class TestKnowledgeLoading:
    """知识库加载功能测试"""

    def test_load_gis_basics(self):
        content = _load_skill_from_file("gis_basics")
        assert content, "gis_basics 加载为空"
        assert "GIS" in content
        assert "适用场景" in content

    def test_load_spatial_analysis(self):
        content = _load_skill_from_file("spatial_analysis")
        assert content, "spatial_analysis 加载为空"
        assert "缓冲区" in content or "叠置" in content

    def test_load_coordinate_systems(self):
        content = _load_skill_from_file("coordinate_systems")
        assert content, "coordinate_systems 加载为空"
        assert "CRS" in content or "坐标" in content

    def test_load_remote_sensing_advanced(self):
        content = _load_skill_from_file("remote_sensing_advanced")
        assert content, "remote_sensing_advanced 加载为空"
        assert "NDVI" in content

    def test_load_gis_workflows(self):
        content = _load_skill_from_file("gis_workflows")
        assert content, "gis_workflows 加载为空"
        assert "选址" in content or "工作流" in content

    def test_load_nonexistent_returns_empty(self):
        content = _load_skill_from_file("nonexistent_label_xyz")
        assert content == "" or content is None

    def test_old_skills_still_load(self):
        """向后兼容：旧 skills/ 目录的文件仍能加载"""
        content = _load_skill_from_file("analysis")
        assert content, "旧技能 analysis 加载为空（向后兼容失败）"
        assert "geopandas" in content.lower() or "空间" in content

    def test_old_skill_geometry_still_loads(self):
        content = _load_skill_from_file("geometry")
        assert content, "旧技能 geometry 加载为空"


class TestKnowledgeStructure:
    """知识库模块结构完整性测试"""

    REQUIRED_SECTIONS = [
        "适用场景",
        "输入数据要求",
        "处理流程",
        "方法选择依据",
        "推荐工具",
        "输出结果",
        "常见问题",
    ]

    @pytest.mark.parametrize("label", list(_KNOWLEDGE_MAP.keys()))
    def test_module_has_required_sections(self, label):
        """每个知识库模块应包含必需的章节结构（00_index 除外）"""
        if label == "gis_index":
            pytest.skip("索引模块不要求完整章节结构")
        content = _load_skill_from_file(label)
        assert content, f"{label} 加载为空"
        missing = []
        for section in self.REQUIRED_SECTIONS:
            if section not in content:
                missing.append(section)
        assert not missing, f"{label} 缺少章节: {missing}"


class TestKnowledgeRouter:
    """知识库路由集成测试"""

    def test_router_prompt_contains_knowledge_labels(self):
        for label in ["gis_basics", "coordinate_systems", "spatial_analysis",
                       "spatial_statistics", "remote_sensing_advanced",
                       "dem_terrain", "cartography", "gis_workflows"]:
            assert label in _GLM_ROUTER_PROMPT, f"路由提示词缺少知识库标签: {label}"

    def test_router_prompt_has_knowledge_section(self):
        assert "GIS 专业知识库" in _GLM_ROUTER_PROMPT

    def test_router_prompt_still_has_old_skills(self):
        """旧技能标签仍在路由提示词中"""
        for label in ["geometry", "analysis", "remote_sensing", "road_network"]:
            assert label in _GLM_ROUTER_PROMPT, f"路由提示词缺少旧技能标签: {label}"
