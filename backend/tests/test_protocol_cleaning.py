# -*- coding: utf-8 -*-
"""协议过滤测试"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.graph import _clean_ai_text


class TestProtocolCleaning:
    def test_remove_dsml_tool_calls(self):
        """移除 GLM DSML 格式的工具调用"""
        text = '我来帮你查询天气\n<｜｜DSML｜｜tool_calls>\n<｜｜DSML｜｜invoke name="amap_geocode">\n<｜｜DSML｜｜parameter string="name">广州</｜｜DSML｜｜parameter>\n</｜｜DSML｜｜invoke>\n</｜｜DSML｜｜tool_calls>\n请稍候'
        result = _clean_ai_text(text)
        assert "DSML" not in result
        assert "amap_geocode" not in result
        assert "查询天气" in result





