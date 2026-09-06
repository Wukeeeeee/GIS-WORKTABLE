# -*- coding: utf-8 -*-
"""天气与地震数据工具测试"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import tools


class TestFetchWeather:
    def test_tool_registered(self):
        """fetch_weather_data 工具已注册（StructuredTool 对象）"""
        assert hasattr(tools, "fetch_weather_data")
        assert tools.fetch_weather_data is not None
        assert hasattr(tools.fetch_weather_data, "invoke")





class TestFetchEarthquake:
    def test_tool_registered(self):
        """fetch_earthquake_data 工具已注册"""
        assert hasattr(tools, "fetch_earthquake_data")
        assert tools.fetch_earthquake_data is not None
        assert hasattr(tools.fetch_earthquake_data, "invoke")




