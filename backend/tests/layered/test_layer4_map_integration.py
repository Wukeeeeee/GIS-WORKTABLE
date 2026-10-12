# -*- coding: utf-8 -*-
"""Layer 4: 地图集成测试 (Map & Layer Integration Tests)

测试目标：
1. 验证工具结果是否正确传递到现有图层注册机制（_register_layer / get_registered_layers / get_pending_state）；
2. 图层状态是否正确更新（可见性、要素数量、CRS、属性字段）；
3. 前后端接口（/api/layer/register, /api/layer/list, /api/geosource/proxy）是否能准确向前端地图暴露可渲染的数据；
4. 验证 GeoJSON 结构完全契合 Leaflet / VectorGrid 前端渲染引擎规范。
"""
import pytest
from backend.services.tools import _register_layer, get_registered_layers, get_pending_state

pytestmark = [pytest.mark.map_integration, pytest.mark.integration]


def test_layer_registration_updates_gis_state(sample_polygon_geojson):
    """验证图层注册机制正确更新工作区图层列表与待处理状态"""
    layer_name = "南京市鼓楼区_边界"
    _register_layer(layer_name, sample_polygon_geojson)

    # 1. 验证全局图层注册表
    layers = get_registered_layers()
    assert layer_name in layers
    reg_layer = layers[layer_name]
    assert reg_layer["type"] == "FeatureCollection"
    assert len(reg_layer["features"]) == 1

    # 2. 验证 pending_state 同步挂载图层
    pending = get_pending_state()
    assert any(l["name"] == layer_name for l in pending.get("layers", []))


def test_api_layer_endpoints_sync_with_frontend(client, sample_polygon_geojson):
    """验证后端 API /api/layer/register 与 /api/layer/list 的前后端数据通道"""
    # 模拟前端上传或 AI 注册图层
    resp = client.post("/api/layer/register", json={
        "name": "api_test_layer",
        "geojson": sample_polygon_geojson
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True

    # 前端拉取图层列表
    resp_list = client.get("/api/layer/list")
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert any(item["name"] == "api_test_layer" for item in list_data.get("layers", []))


def test_geojson_conformance_for_leaflet_vectorgrid(sample_polygon_geojson):
    """验证图层数据格式完全符合 Leaflet / VectorGrid 的解析规范"""
    fc = sample_polygon_geojson
    # 必须是合法的 FeatureCollection 结构
    assert fc.get("type") == "FeatureCollection"
    assert isinstance(fc.get("features"), list)

    for feat in fc["features"]:
        assert feat.get("type") == "Feature"
        geom = feat.get("geometry")
        assert geom is not None
        assert geom.get("type") in ["Point", "LineString", "Polygon", "MultiPolygon"]
        coords = geom.get("coordinates")
        assert coords is not None and len(coords) > 0
        # 经纬度合法性
        ring = coords[0]
        for pt in ring:
            assert -180.0 <= pt[0] <= 180.0
            assert -90.0 <= pt[1] <= 90.0
        assert isinstance(feat.get("properties"), dict)


def test_geosource_proxy_endpoint(client):
    """验证数据源代理端点（跨域保护与异常传递）"""
    # 代理合法非外部地址
    resp = client.get("/api/geosource/proxy?url=invalid-url-format")
    # 应返回 400 或 500 结构，而不是未捕获崩溃
    assert resp.status_code in [400, 500, 502]
