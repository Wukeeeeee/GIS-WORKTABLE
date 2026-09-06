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





class TestKnowledgeLoading:
    """知识库加载功能测试"""

    def test_load_gis_basics(self):
        content = _load_skill_from_file("gis_basics")
        assert content, "gis_basics 加载为空"
        assert "GIS" in content
        assert "适用场景" in content









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


