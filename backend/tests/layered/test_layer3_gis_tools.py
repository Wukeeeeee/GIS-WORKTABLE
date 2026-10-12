# -*- coding: utf-8 -*-
"""Layer 3: GIS 工具集成测试 (GIS Tools Integration Tests)

测试目标：
1. 空间数据处理工具（缓冲区、分级设色、数据查询）；
2. 专题图与可视化生成（execute_python 实际产出图片文件）；
3. 真实/可控测试数据验证；
4. 真实工具执行入口，不 mock 核心空间算法。
"""
import os
import json
import pytest
from backend.services.tools import (
    datav_boundary,
    spatial_graduated_colors,
    spatial_buffer,
    execute_python,
    _register_layer,
    _temp_output_dir
)

pytestmark = [pytest.mark.gis_tools, pytest.mark.integration]


def test_gis_tool_datav_boundary_real_or_controlled_execution():
    """验证边界查询工具生成符合 GIS 规范的 WGS-84 矢量边界"""
    # 查询南京市鼓楼区
    res_str = datav_boundary.invoke({"name": "南京市鼓楼区"})
    data = json.loads(res_str)
    assert data.get("type") == "FeatureCollection"
    assert len(data.get("features", [])) > 0

    feature = data["features"][0]
    assert feature["geometry"]["type"] in ["Polygon", "MultiPolygon"]
    assert "鼓楼" in feature["properties"]["name"]

    # 坐标范围应在南京经纬度范围内 (118°E, 32°N 附近)
    coords = feature["geometry"]["coordinates"]
    sample_pt = coords[0][0] if feature["geometry"]["type"] == "Polygon" else coords[0][0][0]
    assert 118.0 < sample_pt[0] < 119.5
    assert 31.5 < sample_pt[1] < 32.5


def test_gis_tool_execute_python_generates_real_image():
    """验证 execute_python 真实执行 Python/Matplotlib 制图，产出真实有效的 PNG 图片"""
    script = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(6, 4))
ax.text(0.5, 0.5, '2025 GDP: 2245.8', ha='center', va='center', fontsize=14)
ax.set_title('Integration Test Card')
output_path = 'output/integration_test_card.png'
plt.savefig(output_path, dpi=100)
plt.close()
print(f'OUTPUT_IMAGE:{output_path}')
"""
    result = execute_python.invoke({"code": script})
    assert "integration_test_card.png" in result

    target_file = os.path.join(_temp_output_dir, "integration_test_card.png")
    assert os.path.exists(target_file), f"成果文件 {target_file} 未实际生成"
    assert os.path.getsize(target_file) > 500, "生成的图片文件大小异常"

    # 验证 PNG 文件签名 (Magic Bytes: \x89PNG\r\n\x1a\n)
    with open(target_file, "rb") as f:
        header = f.read(8)
        assert header == b"\x89PNG\r\n\x1a\n", "文件头不属于标准 PNG 图像"


def test_gis_tool_spatial_graduated_colors_multi_feature(sample_multi_polygon_geojson):
    """验证多要素分级设色工具正常生成渲染样式"""
    _register_layer("nanjing_districts", sample_multi_polygon_geojson)
    res = spatial_graduated_colors.invoke({
        "layer_name": "nanjing_districts",
        "value_field": "gdp",
        "classes": 2
    })
    # 成功生成样式或色阶
    assert "分级" in res or "颜色" in res or "成功" in res or "classes" in res or "graduated" in res.lower()


def test_gis_tool_spatial_graduated_colors_single_feature_graceful_guidance(sample_polygon_geojson):
    """验证单要素分级设色优雅降级，给出建设性建议而非死锁报错"""
    _register_layer("single_district", sample_polygon_geojson)
    res = spatial_graduated_colors.invoke({
        "layer_name": "single_district",
        "value_field": "gdp"
    })
    # 返回友好指引提示
    assert "单要素" in res or "单个" in res or "建议" in res or "看板" in res
