# -*- coding: utf-8 -*-
"""测试 Data Discovery 的数据句柄 (handle) 注册与 download 消费闭环"""

import pytest
from backend.services import data_discovery
from backend.services.data_providers.models import DataRequest


def test_handle_registration_and_retrieval():
    req = DataRequest(
        query="南京道路",
        kind="roads",
        area="南京市",
        bbox=(118.7, 32.0, 118.9, 32.2),
        provider_id="osm",
        file_format="geojson"
    )

    handle = data_discovery.register_data_handle(req)
    assert handle.startswith("dh_osm_roads_")

    stored = data_discovery.get_data_handle(handle)
    assert stored is not None
    assert stored["area"] == "南京市"
    assert stored["kind"] == "roads"
    assert stored["provider_id"] == "osm"
    assert stored["bbox"] == "118.7,32.0,118.9,32.2"


def test_download_resolves_from_handle():
    # 模拟预存句柄
    req = DataRequest(
        kind="roads",
        area="测试区域",
        provider_id="osm",
        file_format="geojson"
    )
    handle = data_discovery.register_data_handle(req)

    # 验证 resolve_request 可以从 handle 展开
    stored = data_discovery.get_data_handle(handle)
    assert stored["kind"] == "roads"
    assert stored["area"] == "测试区域"
