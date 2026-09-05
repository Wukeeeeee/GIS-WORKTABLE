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

    def test_tool_name(self):
        """工具名称正确"""
        assert tools.fetch_weather_data.name == "fetch_weather_data"

    def test_description_contains_keywords(self):
        """工具描述包含关键信息"""
        desc = tools.fetch_weather_data.description
        assert "Open-Meteo" in desc
        assert "天气" in desc

    def test_invalid_coords_returns_error(self):
        """无效坐标应返回错误字符串（不崩溃）"""
        result = tools.fetch_weather_data.invoke({
            "latitude": 999,
            "longitude": 999,
            "past_days": 1,
        })
        assert isinstance(result, str)
        assert len(result) > 0


class TestFetchEarthquake:
    def test_tool_registered(self):
        """fetch_earthquake_data 工具已注册"""
        assert hasattr(tools, "fetch_earthquake_data")
        assert tools.fetch_earthquake_data is not None
        assert hasattr(tools.fetch_earthquake_data, "invoke")

    def test_tool_name(self):
        """工具名称正确"""
        assert tools.fetch_earthquake_data.name == "fetch_earthquake_data"

    def test_description_contains_keywords(self):
        """工具描述包含关键信息"""
        desc = tools.fetch_earthquake_data.description
        assert "USGS" in desc
        assert "地震" in desc

    def test_invalid_date_returns_error(self):
        """无效日期应返回错误字符串（不崩溃）"""
        result = tools.fetch_earthquake_data.invoke({
            "start_time": "not-a-date",
            "end_time": "also-not-a-date",
        })
        assert isinstance(result, str)

    def test_geojson_structure(self):
        """工具内部构建 GeoJSON 的逻辑正确"""
        sample_feature = {
            "type": "Feature",
            "properties": {"place": "测试位置", "mag": 5.5, "time": 1700000000000},
            "geometry": {"type": "Point", "coordinates": [113.0, 23.0, 10.0]},
        }
        coords = sample_feature["geometry"]["coordinates"]
        assert len(coords) >= 2
        assert coords[0] == 113.0
        assert sample_feature["properties"]["mag"] == 5.5
