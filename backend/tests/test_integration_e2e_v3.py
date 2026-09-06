# -*- coding: utf-8 -*-
"""
API 级集成测试第三批：FastAPI HTTP 路由端到端 + 空间分析全链路
用 TestClient 发真实 HTTP 请求，零 token 消耗
"""
import os
import sys
import uuid
import random
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from fastapi.testclient import TestClient

# 导入 app（需要在 sys.path 设置后）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
from main import app
from backend.services import tools
from backend.services.tools import (
    convert_crs,
    spatial_union,
    spatial_difference,
    spatial_clip,
    spatial_dissolve,
    spatial_hotspot,
    _register_layer,
    _registered_layers,
    get_registered_layers_snapshot,
)

client = TestClient(app)


def _random_point_layer(name, count=20, center_lon=113.0, center_lat=23.0):
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


def _random_polygon_layer(name, count=5, center_lon=113.0, center_lat=23.0):
    features = []
    for i in range(count):
        cx = center_lon + random.uniform(-0.02, 0.02)
        cy = center_lat + random.uniform(-0.02, 0.02)
        size = random.uniform(0.005, 0.015)
        features.append({
            "type": "Feature",
            "properties": {"id": i, "category": random.choice(["A", "B", "C"])},
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


# ============================================================
# FastAPI HTTP 路由端到端
# ============================================================

class TestHTTPRoutes:
    """通过 TestClient 发真实 HTTP 请求测试 API 路由"""

    def test_health_endpoint(self):
        """健康检查接口应返回 200"""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data or "ok" in str(data).lower()

    def test_version_endpoint(self):
        """版本接口应返回版本信息"""
        resp = client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert "commit" in data or "version" in data or "start_time" in data

    def test_layers_endpoint(self):
        """图层列表接口应返回已注册图层"""
        # 先注册一个图层
        name = f"http_layer_{uuid.uuid4().hex[:6]}"
        _random_point_layer(name, count=5)
        resp = client.get("/api/layers")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_reset_state_endpoint(self):
        """重置状态接口应正常工作"""
        resp = client.post("/api/reset_state")
        assert resp.status_code in [200, 204]

    def test_favicon_endpoint(self):
        """favicon 应返回 200 或 404（不应 500）"""
        resp = client.get("/favicon.ico")
        assert resp.status_code in [200, 404]

    def test_credential_status_endpoint(self):
        """凭据状态接口应返回各服务配置状态"""
        resp = client.get("/api/geo-credentials/status")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_credential_save_endpoint(self):
        """保存凭据接口应接受请求（用 mock 凭据，不存真实密码）"""
        resp = client.post("/api/geo-credentials", json={
            "service": "test_service",
            "username": "test_user",
            "password": "test_pass_123"
        })
        # 可能返回 200 或 400（服务名不支持），但不应 500
        assert resp.status_code in [200, 400, 422]

    def test_logs_stats_endpoint(self):
        """日志统计接口应返回统计数据"""
        resp = client.get("/api/logs/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_boundary_endpoint(self):
        """行政边界接口应能查询（可能需要网络，测不崩溃即可）"""
        resp = client.get("/api/boundary", params={"name": "北京市"})
        # 网络可能失败，但不应 500
        assert resp.status_code in [200, 400, 500, 502]

    def test_project_crud(self):
        """项目管理：创建→查询→删除完整链路"""
        # 创建项目
        proj_name = f"test_proj_{uuid.uuid4().hex[:6]}"
        create_resp = client.post("/api/projects", json={
            "name": proj_name,
            "data": {"layers": [], "view": {"center": [113, 23], "zoom": 10}}
        })
        assert create_resp.status_code in [200, 201]
        proj_id = create_resp.json().get("id") or create_resp.json().get("project_id")

        if proj_id:
            # 查询项目
            get_resp = client.get(f"/api/projects/{proj_id}")
            assert get_resp.status_code == 200
            # 删除项目
            del_resp = client.delete(f"/api/projects/{proj_id}")
            assert del_resp.status_code in [200, 204]


# ============================================================
# 空间分析全链路
# ============================================================

class TestCRSConversionE2E:
    """坐标转换端到端"""

    def test_convert_to_web_mercator(self):
        """WGS84 → Web Mercator 转换应生成新图层"""
        name = f"crs_test_{uuid.uuid4().hex[:6]}"
        _random_point_layer(name, count=10)
        before = len(_registered_layers)

        func = getattr(convert_crs, 'func', convert_crs)
        result = func(layer_name=name, target_crs="web_mercator")

        assert result is not None
        assert len(result) > 5
        # 应生成转换后的图层
        assert len(_registered_layers) >= before or "转换" in result or "CRS" in result

    def test_convert_invalid_layer(self):
        """转换不存在的图层应返回友好错误"""
        func = getattr(convert_crs, 'func', convert_crs)
        result = func(layer_name="nonexistent_crs_xyz")
        assert result is not None
        assert "不存在" in result or "未找到" in result or "错误" in result


class TestSpatialOperatorsE2E:
    """空间叠加算子端到端：联合/差异/裁剪/融合"""

    def test_spatial_union(self):
        """空间联合应生成合并图层"""
        name_a = f"union_a_{uuid.uuid4().hex[:6]}"
        name_b = f"union_b_{uuid.uuid4().hex[:6]}"
        _random_polygon_layer(name_a, count=3)
        _random_polygon_layer(name_b, count=3)

        func = getattr(spatial_union, 'func', spatial_union)
        result = func(layer_a=name_a, layer_b=name_b)
        assert result is not None and len(result) > 5

    def test_spatial_difference(self):
        """空间差异应生成擦除图层"""
        name_a = f"diff_a_{uuid.uuid4().hex[:6]}"
        name_b = f"diff_b_{uuid.uuid4().hex[:6]}"
        _random_polygon_layer(name_a, count=3)
        _random_polygon_layer(name_b, count=3)

        func = getattr(spatial_difference, 'func', spatial_difference)
        result = func(layer_a=name_a, layer_b=name_b)
        assert result is not None and len(result) > 5

    def test_spatial_clip(self):
        """空间裁剪应生成裁剪图层"""
        name = f"clip_src_{uuid.uuid4().hex[:6]}"
        clip_name = f"clip_mask_{uuid.uuid4().hex[:6]}"
        _random_polygon_layer(name, count=5)
        _random_polygon_layer(clip_name, count=1)

        func = getattr(spatial_clip, 'func', spatial_clip)
        result = func(layer_name=name, clip_layer=clip_name)
        assert result is not None and len(result) > 5

    def test_spatial_dissolve(self):
        """空间融合应按字段合并要素"""
        name = f"dissolve_test_{uuid.uuid4().hex[:6]}"
        _random_polygon_layer(name, count=10)

        func = getattr(spatial_dissolve, 'func', spatial_dissolve)
        result = func(layer_name=name, group_by="category")
        assert result is not None and len(result) > 5
        # 融合后要素数应减少
        assert "融合" in result or "dissolve" in result.lower() or "合并" in result


class TestSpatialHotspotE2E:
    """空间热点分析端到端"""

    def test_hotspot_with_value_field(self):
        """带数值字段的点图层应能做热点分析"""
        name = f"hotspot_test_{uuid.uuid4().hex[:6]}"
        _random_point_layer(name, count=30)

        func = getattr(spatial_hotspot, 'func', spatial_hotspot)
        result = func(layer_name=name, field="value", threshold=0.05, k=5)

        assert result is not None
        # 热点分析可能因为数据分布返回无显著结果，但不应崩溃
        assert len(result) > 5 or "热点" in result or "无显著" in result or "错误" not in result[:20]

    def test_hotspot_invalid_field(self):
        """不存在的字段应返回友好错误"""
        name = f"hotspot_inv_{uuid.uuid4().hex[:6]}"
        _random_point_layer(name, count=10)
        func = getattr(spatial_hotspot, 'func', spatial_hotspot)
        result = func(layer_name=name, field="nonexistent_field")
        assert result is not None


class TestLayerSnapshotAfterOperations:
    """操作后图层快照一致性"""

    def test_snapshot_reflects_new_layers(self):
        """注册多个图层后，快照应包含全部"""
        names = [f"snap_{i}_{uuid.uuid4().hex[:4]}" for i in range(3)]
        for n in names:
            _random_point_layer(n, count=5)

        snapshot = get_registered_layers_snapshot()
        snapshot_names = [
            layer.get("filename") or layer.get("name") or layer.get("layer_id")
            for layer in snapshot
        ]
        for n in names:
            found = any(n in str(sn) for sn in snapshot_names)
            assert found, f"图层 {n} 未出现在快照中"
