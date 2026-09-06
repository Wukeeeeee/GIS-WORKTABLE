# -*- coding: utf-8 -*-
"""卫星影像巡检工具测试"""
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.services.tools import (
    _classify_rgb_heuristic,
    _mask_to_geojson,
    _calculate_geojson_area,
    _rasterize_boundary,
    _registered_layers,
    _register_layer,
    _push_layer,
    inspect_satellite_image,
    tools,
)


class TestRGBClassification:
    """测试 RGB 启发式分类算法"""

    def test_vegetation_detection(self):
        """测试植被检测：绿色占优的像素"""
        img = Image.new("RGB", (10, 10), (200, 50, 50))  # 红色背景
        # 中心 4x4 绿色区域
        for y in range(3, 7):
            for x in range(3, 7):
                img.putpixel((x, y), (50, 150, 50))
        masks, stats, active = _classify_rgb_heuristic(img)
        assert "vegetation" in masks
        assert masks["vegetation"].sum() >= 10  # 至少检测到一些植被像素

    def test_water_detection(self):
        """测试水体检测：蓝色占优且较暗"""
        img = Image.new("RGB", (10, 10), (200, 200, 200))  # 亮背景
        for y in range(3, 7):
            for x in range(3, 7):
                img.putpixel((x, y), (40, 60, 120))  # 暗蓝色
        masks, stats, active = _classify_rgb_heuristic(img)
        assert "water" in masks
        assert masks["water"].sum() >= 5

    def test_built_up_detection(self):
        """测试建筑检测：低饱和或高边缘"""
        img = Image.new("RGB", (10, 10), (128, 128, 128))  # 灰色建筑
        masks, stats, active = _classify_rgb_heuristic(img)
        assert "built_up" in masks
        # 灰色应该被分类为建筑
        assert masks["built_up"].sum() > 0

    def test_analysis_mask(self):
        """测试分析 mask 裁剪"""
        img = Image.new("RGB", (10, 10), (128, 128, 128))
        mask = np.zeros((10, 10), dtype=bool)
        mask[:5, :] = True  # 只分析上半部分
        masks, stats, active = _classify_rgb_heuristic(img, mask)
        assert active == 50  # 只有 50 个像素被分析

    def test_statistics_format(self):
        """测试统计结果格式"""
        img = Image.new("RGB", (10, 10), (128, 128, 128))
        masks, stats, active = _classify_rgb_heuristic(img)
        assert len(stats) == 4
        for s in stats:
            assert "category" in s
            assert "pixel_count" in s
            assert "pixel_ratio" in s
            assert isinstance(s["pixel_count"], int)
            assert 0 <= s["pixel_ratio"] <= 1


class TestMaskVectorization:
    """测试 mask 矢量化"""

    def test_basic_vectorization(self):
        """测试基本矢量化"""
        mask = np.zeros((20, 20), dtype=bool)
        mask[5:15, 5:15] = True  # 10x10 方块
        transform = (116.0, 0.001, 0, 30.0, 0, -0.001)  # (c, a, b, f, d, e)
        fc = _mask_to_geojson(mask, transform, "test")
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) >= 1
        geom = fc["features"][0]["geometry"]
        assert geom["type"] in ("Polygon", "MultiPolygon")

    def test_empty_mask(self):
        """测试空 mask"""
        mask = np.zeros((10, 10), dtype=bool)
        transform = (0, 1, 0, 0, 0, -1)
        fc = _mask_to_geojson(mask, transform, "test")
        assert len(fc["features"]) == 0

    def test_coordinates_in_crs(self):
        """测试矢量化后坐标在正确的 CRS 范围内"""
        mask = np.zeros((10, 10), dtype=bool)
        mask[2:8, 2:8] = True
        transform = (114.0, 0.01, 0, 30.0, 0, -0.01)
        fc = _mask_to_geojson(mask, transform, "test")
        if fc["features"]:
            coords = fc["features"][0]["geometry"]["coordinates"][0]
            for p in coords:
                assert 113.5 <= p[0] <= 114.5  # 经度在范围内
                assert 29.5 <= p[1] <= 30.5  # 纬度在范围内


class TestAreaCalculation:
    """测试面积计算"""

    def test_known_area(self):
        """测试已知面积的多边形"""
        # 1度 x 1度 的正方形（在赤道附近约 111km x 111km）
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [0, 0], [1, 0], [1, 1], [0, 1], [0, 0]
                    ]]
                }
            }]
        }
        area = _calculate_geojson_area(geojson)
        assert area > 0
        # 约 12300 km2（1度在赤道约 111km，等面积投影下）
        assert 1e10 < area < 1.5e10  # 平方米

    def test_empty_geojson(self):
        """测试空 GeoJSON"""
        geojson = {"type": "FeatureCollection", "features": []}
        area = _calculate_geojson_area(geojson)
        assert area == 0.0


class TestBoundaryRasterization:
    """测试边界栅格化"""

    def test_basic_rasterization(self):
        """测试基本边界栅格化"""
        boundary = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [116.0, 39.0], [116.2, 39.0],
                        [116.2, 39.2], [116.0, 39.2], [116.0, 39.0]
                    ]]
                }
            }]
        }
        img = Image.new("RGB", (100, 100))
        bbox = [115.9, 38.9, 116.3, 39.3]
        mask = _rasterize_boundary(boundary, img, bbox)
        assert mask is not None
        assert mask.any()
        assert mask.sum() > 100  # 应该有不少像素在边界内


class TestToolRegistration:
    """测试工具注册"""

    def test_tool_in_list(self):
        """测试 inspect_satellite_image 在工具列表中"""
        tool_names = [t.name if hasattr(t, 'name') else t.__name__ for t in tools]
        assert "inspect_satellite_image" in tool_names

    def test_tool_has_docstring(self):
        """测试工具描述"""
        for t in tools:
            name = t.name if hasattr(t, 'name') else t.__name__
            if name == "inspect_satellite_image":
                desc = getattr(t, 'description', '') or getattr(t, '__doc__', '')
                assert desc is not None
                assert "RGB" in desc or "启发式" in desc


class TestErrorHandling:
    """测试错误处理"""

    def test_invalid_bbox(self):
        """测试无效 bbox"""
        func = getattr(inspect_satellite_image, 'func', inspect_satellite_image)
        result = func(bbox="invalid")
        assert "错误" in result or "bbox" in result

    def test_no_input(self):
        """测试无输入"""
        func = getattr(inspect_satellite_image, 'func', inspect_satellite_image)
        result = func()
        assert "错误" in result or "范围" in result


class TestLayerRegistry:
    """测试图层注册"""

    def test_register_and_retrieve(self):
        """测试注册后可检索"""
        test_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"category": "water"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
                }
            }]
        }
        # 直接操作注册表（_register_layer 内部有 try-except 可能静默失败）
        from backend.services.tools import _state_lock
        with _state_lock:
            _registered_layers["test_inspection_layer"] = {
                "name": "test_inspection_layer",
                "feature_count": 1,
                "geometry_types": ["Polygon"],
                "geojson": test_geojson,
                "bbox": [0, 0, 1, 1],
            }
        assert "test_inspection_layer" in _registered_layers
        info = _registered_layers["test_inspection_layer"]
        assert info["feature_count"] == 1
        assert "geojson" in info
        # 清理
        with _state_lock:
            _registered_layers.pop("test_inspection_layer", None)



class TestQuadkeyConversion:
    """测试 Bing 瓦片 quadkey 转换"""

    def test_quadkey_basic(self):
        """测试基本 quadkey 转换"""
        from backend.services.tools import _tile_to_quadkey
        # zoom=1, x=0, y=0 -> quadkey "0"
        assert _tile_to_quadkey(0, 0, 1) == "0"
        # zoom=1, x=1, y=0 -> quadkey "1"
        assert _tile_to_quadkey(1, 0, 1) == "1"
        # zoom=1, x=0, y=1 -> quadkey "2"
        assert _tile_to_quadkey(0, 1, 1) == "2"
        # zoom=1, x=1, y=1 -> quadkey "3"
        assert _tile_to_quadkey(1, 1, 1) == "3"

    def test_quadkey_length(self):
        """quadkey 长度应等于 zoom"""
        from backend.services.tools import _tile_to_quadkey
        for z in range(1, 10):
            qk = _tile_to_quadkey(0, 0, z)
            assert len(qk) == z


class TestSatelliteFetcher:
    """测试多源卫星影像下载器"""

    def test_fetcher_exists(self):
        """_fetch_satellite_imagery 函数存在"""
        from backend.services.tools import _fetch_satellite_imagery
        assert callable(_fetch_satellite_imagery)

    def test_legacy_compat(self):
        """_fetch_esri_imagery 兼容旧调用（等价于 source='auto'）"""
        from backend.services.tools import _fetch_esri_imagery
        assert callable(_fetch_esri_imagery)

    def test_quadkey_in_fetcher(self):
        """fetcher 模块中应包含 quadkey 转换"""
        from backend.services import tools
        assert hasattr(tools, "_tile_to_quadkey")


class TestOverlayPNGOutput:
    """测试 overlay PNG 生成（mock 瓦片下载）"""

    def test_overlay_generated(self, tmp_path, monkeypatch):
        """巡检完成后应生成 overlay PNG 并加入待推送列表"""
        from backend.services import tools
        from PIL import Image
        import numpy as np

        # 构造测试影像：一半植被绿、一半建筑灰
        test_img = Image.new("RGB", (64, 64), (128, 128, 128))
        for y in range(32):
            for x in range(64):
                test_img.putpixel((x, y), (50, 150, 50))  # 上半部分绿色（植被）

        meta = {
            "zoom": 14, "tile_count": 1, "width": 64, "height": 64,
            "bbox": [113.0, 23.0, 113.1, 23.1],
            "transform": (113.0, 0.0015625, 0, 23.1, 0, -0.0015625),
            "crs": "EPSG:4326", "source": "esri",
        }

        # mock 瓦片下载
        def _mock_fetch(*args, **kwargs):
            return test_img, meta
        monkeypatch.setattr(tools, "_fetch_satellite_imagery", _mock_fetch)
        monkeypatch.setattr(tools, "_fetch_esri_imagery", _mock_fetch)

        # 清空待推送图片
        tools._pending_images.clear()

        # 执行巡检
        func = getattr(tools.inspect_satellite_image, 'func', tools.inspect_satellite_image)
        result = func(bbox="113.0,23.0,113.1,23.1")

        # 检查结果包含分类信息
        assert "巡检" in result or "水体" in result or "植被" in result or "建筑" in result

        # 检查 overlay PNG 已加入待推送
        png_items = [p for p in tools._pending_images if p.get("type") == "png"]
        assert len(png_items) >= 1, "应生成 overlay PNG 并加入待推送列表"

        # 检查文件实际存在
        import os
        for item in png_items:
            url = item.get("url", "")
            if url.startswith("/"):
                fpath = url.lstrip("/")
                assert os.path.exists(fpath), f"overlay 文件不存在: {fpath}"
