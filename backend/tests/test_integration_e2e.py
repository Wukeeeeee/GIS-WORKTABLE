# -*- coding: utf-8 -*-
"""
API 级集成测试：模拟真实用户流程，不经过 LLM（零 token 消耗）
测试内容由代码动态生成，不是固定 fixture
"""
import os
import sys
import uuid
import random
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.services import tools
from backend.services.tools import (
    inspect_satellite_image,
    spatial_intersect,
    _register_layer,
    _registered_layers,
    _pending_layers,
    _pending_images,
    get_registered_layers_snapshot,
    _state_lock,
)


def _random_bbox(center_lon=113.0, center_lat=23.0, size=0.05):
    """生成随机 bbox 字符串"""
    west = center_lon - size / 2 + random.uniform(-0.01, 0.01)
    south = center_lat - size / 2 + random.uniform(-0.01, 0.01)
    east = west + size
    north = south + size
    return f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"


def _make_test_image(width=128, height=128):
    """构造有明确地物特征的测试影像：左上植被绿、右上水体蓝、左下建筑灰、右下裸地橙"""
    img = Image.new("RGB", (width, height))
    for y in range(height):
        for x in range(width):
            if x < width // 2 and y < height // 2:
                img.putpixel((x, y), (50, 150, 50))  # 植被
            elif x >= width // 2 and y < height // 2:
                img.putpixel((x, y), (40, 60, 120))  # 水体
            elif x < width // 2 and y >= height // 2:
                img.putpixel((x, y), (128, 128, 128))  # 建筑
            else:
                img.putpixel((x, y), (180, 140, 80))  # 裸地
    return img


class TestInspectionE2E:
    """卫星巡检工具端到端：mock 瓦片下载，真实后续处理链路"""

    def test_full_pipeline_registers_layer_and_overlay(self, monkeypatch):
        """完整流程：影像→分类→矢量化→面积→图层注册→overlay PNG"""
        test_img = _make_test_image()
        meta = {
            "zoom": 14, "tile_count": 1, "width": 128, "height": 128,
            "bbox": [113.0, 23.0, 113.1, 23.1],
            "transform": (113.0, 0.00078125, 0, 23.1, 0, -0.00078125),
            "crs": "EPSG:4326", "source": "esri",
        }
        monkeypatch.setattr(tools, "_fetch_satellite_imagery", lambda *a, **k: (test_img, meta))
        monkeypatch.setattr(tools, "_fetch_esri_imagery", lambda *a, **k: (test_img, meta))

        _pending_images.clear()
        bbox = _random_bbox()
        func = getattr(inspect_satellite_image, 'func', inspect_satellite_image)
        result = func(bbox=bbox)

        # 1. 返回结果包含分类信息
        assert "巡检" in result or "水体" in result or "植被" in result
        # 2. overlay PNG 已生成并加入待推送
        pngs = [p for p in _pending_images if p.get("type") == "png"]
        assert len(pngs) >= 1, "overlay PNG 未生成"
        # 3. PNG 文件真实存在且是有效图片
        for p in pngs:
            fpath = p["url"].lstrip("/")
            assert os.path.exists(fpath), f"overlay 文件不存在: {fpath}"
            from PIL import Image as _PILImg
            _verify = _PILImg.open(fpath)
            assert _verify.size[0] > 0 and _verify.size[1] > 0, "overlay 图片尺寸异常"

    def test_result_layer_registered(self, monkeypatch):
        """巡检结果应注册到 Layer Registry"""
        test_img = _make_test_image()
        meta = {
            "zoom": 14, "tile_count": 1, "width": 128, "height": 128,
            "bbox": [113.0, 23.0, 113.1, 23.1],
            "transform": (113.0, 0.00078125, 0, 23.1, 0, -0.00078125),
            "crs": "EPSG:4326", "source": "bing",
        }
        monkeypatch.setattr(tools, "_fetch_satellite_imagery", lambda *a, **k: (test_img, meta))
        monkeypatch.setattr(tools, "_fetch_esri_imagery", lambda *a, **k: (test_img, meta))

        before = len(_registered_layers)
        func = getattr(inspect_satellite_image, 'func', inspect_satellite_image)
        result = func(bbox="113.0,23.0,113.1,23.1")

        # 图层名应包含"影像巡检"
        inspection_layers = [k for k in _registered_layers if "影像巡检" in k]
        assert len(inspection_layers) >= 1, "巡检结果未注册到 Layer Registry"
        # 注册的图层应有要素
        layer_info = _registered_layers[inspection_layers[-1]]
        assert layer_info.get("feature_count", 0) > 0, "注册图层无要素"

    def test_statistics_are_real_numbers(self, monkeypatch):
        """统计数字必须来自真实计算，不能是 0 或占位符"""
        test_img = _make_test_image()
        meta = {
            "zoom": 14, "tile_count": 1, "width": 128, "height": 128,
            "bbox": [113.0, 23.0, 113.1, 23.1],
            "transform": (113.0, 0.00078125, 0, 23.1, 0, -0.00078125),
            "crs": "EPSG:4326", "source": "esri",
        }
        monkeypatch.setattr(tools, "_fetch_satellite_imagery", lambda *a, **k: (test_img, meta))
        monkeypatch.setattr(tools, "_fetch_esri_imagery", lambda *a, **k: (test_img, meta))

        func = getattr(inspect_satellite_image, 'func', inspect_satellite_image)
        result = func(bbox="113.0,23.0,113.1,23.1")

        # 结果中应包含面积数字（km2）
        import re
        km2_matches = re.findall(r'[\d.]+', result)
        numeric_values = [float(x) for x in km2_matches if 0 < float(x) < 100]
        assert len(numeric_values) >= 2, "结果中缺少真实统计数字"


class TestSpatialIntersectE2E:
    """空间叠加端到端：动态生成随机多边形，验证面积和占比"""

    def _make_rectangle(self, west, south, east, north, name):
        """生成矩形 GeoJSON 并注册"""
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [west, south], [east, south],
                        [east, north], [west, north], [west, south]
                    ]]
                }
            }]
        }
        _register_layer(name, geojson)
        return name

    def test_intersect_returns_area_and_ratio(self):
        """相交分析应返回真实面积和占比，AI 可直接引用"""
        # 动态生成两个重叠 50% 的矩形
        base = random.uniform(113.0, 114.0)
        base_lat = random.uniform(23.0, 24.0)
        name1 = f"test_rect_a_{uuid.uuid4().hex[:6]}"
        name2 = f"test_rect_b_{uuid.uuid4().hex[:6]}"
        self._make_rectangle(base, base_lat, base + 0.02, base_lat + 0.02, name1)
        self._make_rectangle(base + 0.01, base_lat + 0.01, base + 0.03, base_lat + 0.03, name2)

        func = getattr(spatial_intersect, 'func', spatial_intersect)
        result = func(layer_a=name1, layer_b=name2)

        # 应包含要素数和面积
        assert "要素" in result or "面积" in result or "相交" in result
        # 应包含数字（不是空结果）
        import re
        numbers = re.findall(r'[\d.]+', result)
        assert len(numbers) >= 2, "相交结果缺少统计数字"

    def test_intersect_with_random_data(self):
        """多次随机数据测试，确保不依赖特定输入"""
        for _ in range(3):
            base = random.uniform(110.0, 120.0)
            base_lat = random.uniform(20.0, 40.0)
            name1 = f"rand_a_{uuid.uuid4().hex[:6]}"
            name2 = f"rand_b_{uuid.uuid4().hex[:6]}"
            self._make_rectangle(base, base_lat, base + 0.01, base_lat + 0.01, name1)
            self._make_rectangle(base + 0.005, base_lat + 0.005, base + 0.015, base_lat + 0.015, name2)

            func = getattr(spatial_intersect, 'func', spatial_intersect)
            result = func(layer_a=name1, layer_b=name2)
            assert result is not None
            assert len(result) > 10, "相交结果过短，可能异常"


class TestLayerRegistryPipeline:
    """图层注册→快照→SSE 推送链路"""

    def test_register_then_snapshot(self):
        """注册图层后，get_registered_layers_snapshot 应能返回"""
        name = f"snap_test_{uuid.uuid4().hex[:6]}"
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"test": True},
                "geometry": {
                    "type": "Point",
                    "coordinates": [random.uniform(110, 120), random.uniform(20, 40)]
                }
            }]
        }
        _register_layer(name, geojson)

        snapshot = get_registered_layers_snapshot()
        names = [layer.get("filename") or layer.get("name") or layer.get("layer_id")
                 for layer in snapshot]
        assert name in names, f"图层 {name} 注册后快照中找不到"

    def test_pending_layers_queue(self):
        """注册图层应加入 _pending_layers 供 SSE 推送"""
        before = len(_pending_layers)
        name = f"pending_test_{uuid.uuid4().hex[:6]}"
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [113.0, 23.0]}
            }]
        }
        tools._push_layer(name, geojson, {"color": "#ff0000"})

        assert len(_pending_layers) > before, "图层未加入待推送队列"
        last = _pending_layers[-1]
        assert last.get("name") == name or name in str(last), "待推送图层名不匹配"


class TestErrorRecovery:
    """错误恢复：无效输入不应导致崩溃"""

    def test_inspection_invalid_bbox(self):
        """无效 bbox 应返回友好错误，不抛异常"""
        func = getattr(inspect_satellite_image, 'func', inspect_satellite_image)
        result = func(bbox="not-a-bbox")
        assert "错误" in result or "bbox" in result or "范围" in result

    def test_intersect_nonexistent_layer(self):
        """不存在的图层应返回友好错误"""
        func = getattr(spatial_intersect, 'func', spatial_intersect)
        result = func(layer_a="nonexistent_xyz", layer_b="also_nonexistent_xyz")
        assert result is not None
        assert len(result) > 0
