# -*- coding: utf-8 -*-
"""Docstring 关键字守卫测试：防止后续维护中误删关键参数说明（如坐标轴、单位、图层名等）"""
import json

import pytest
from backend.services.tools import tools


@pytest.fixture(scope="module")
def tool_map():
    return {t.name: t.description or "" for t in tools}


class TestToolDocstringGuards:
    def test_spatial_buffer_guard(self, tool_map):
        """spatial_buffer 必须明确说明缓冲距离与单位"""
        doc = tool_map["spatial_buffer"]
        assert "distance" in doc, "spatial_buffer 丢失 distance 参数说明"
        assert "m" in doc or "km" in doc or "米" in doc, "spatial_buffer 丢失单位说明"

    def test_spatial_join_guard(self, tool_map):
        """spatial_join 必须包含空间关系谓词说明"""
        doc = tool_map["spatial_join"]
        assert "target_layer" in doc and "join_layer" in doc, "spatial_join 丢失图层参数说明"
        assert "predicate" in doc or "intersects" in doc, "spatial_join 丢失空间谓词说明"

    def test_convert_crs_guard(self, tool_map):
        """convert_crs 必须说明 target_crs 常见取值"""
        doc = tool_map["convert_crs"]
        assert "wgs84" in doc.lower() or "4326" in doc, "convert_crs 丢失 WGS84 说明"
        assert "layer_name" in doc, "convert_crs 丢失 layer_name 说明"

    def test_get_elevation_data_guard(self, tool_map):
        """get_elevation_data 必须说明 bbox 格式"""
        doc = tool_map["get_elevation_data"]
        assert "bbox" in doc, "get_elevation_data 丢失 bbox 说明"
        assert "wgs84" in doc.lower() or "minlng" in doc.lower() or "minlat" in doc.lower(), "get_elevation_data 丢失 WGS84/坐标说明"

    def test_network_analysis_guard(self, tool_map):
        """network_analysis 必须说明分析类型与经纬度顺序"""
        doc = tool_map["network_analysis"]
        assert "route" in doc or "analysis_type" in doc, "network_analysis 丢失 analysis_type 说明"
        assert "经度,纬度" in doc or "origin" in doc, "network_analysis 丢失坐标格式说明"

    def test_calc_spectral_index_guard(self, tool_map):
        """calc_spectral_index 必须说明支持的指数类型枚举"""
        doc = tool_map["calc_spectral_index"]
        assert "ndvi" in doc.lower() and "ndwi" in doc.lower(), "calc_spectral_index 丢失支持的指数枚举说明"

    # ---------- 光谱指数工具：波段序号基准与传感器对照 ----------

    @pytest.mark.parametrize("tool_name", [
        "ndvi_analysis", "ndwi_analysis", "ndbi_analysis", "evi_analysis", "ndmi_analysis",
    ])
    def test_spectral_band_numbering_guard(self, tool_map, tool_name):
        """光谱指数工具必须保留波段序号说明（从1开始）与传感器对照（Sentinel/Landsat）——丢失会导致读错波段"""
        doc = tool_map[tool_name]
        assert "从1开始" in doc, f"{tool_name} 丢失波段序号基准说明（从1开始）"
        assert "Sentinel" in doc or "Landsat" in doc, f"{tool_name} 丢失传感器波段对照说明"

    # ---------- Facade 参数契约：index 必填 + Literal 枚举进 Schema ----------
    # 无默认值 = 漏传时显式报错，而不是静默产出一张错误的 NDVI 图层。

    def test_facade_index_is_required_enum(self, tool_map):
        from backend.services.tools import tools as _tools
        t = next(x for x in _tools if x.name == "calc_spectral_index")
        schema = t.args_schema.model_json_schema()
        props = schema.get("properties", {})
        assert "index" in props, "calc_spectral_index 缺少 index 参数"
        assert "index" in schema.get("required", []), (
            "calc_spectral_index.index 不应是可选参数：漏传会静默产出 NDVI 图层，掩盖参数缺失"
        )
        assert set(props["index"].get("enum", [])) == {"ndvi", "ndwi", "ndbi", "evi", "ndmi"}, (
            "index 应使用 Literal 枚举，让非法值在模型采样阶段就被约束住"
        )

    # ---------- Schema 体积天花板：防止工具描述回胖 ----------
    # 2026-10-13 瘦身后实测 53,685 字符，留约 12% 余量到 60,000。
    # 新增工具属正常增长；超限说明描述又堆冗余了，或该上动态路由绑定。

    SCHEMA_CHAR_CEILING = 60_000

    def test_total_schema_size_below_ceiling(self, tool_map):
        from langchain_core.utils.function_calling import convert_to_openai_tool
        total = len(json.dumps(
            [convert_to_openai_tool(t) for t in tools], ensure_ascii=False
        ))
        assert total <= self.SCHEMA_CHAR_CEILING, (
            f"工具 Schema 总体积 {total} 字符超过天花板 {self.SCHEMA_CHAR_CEILING}，"
            f"新增工具时请同步精简描述，或考虑动态路由绑定"
        )
