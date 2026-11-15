# -*- coding: utf-8 -*-
"""
Tests for DataV Boundary Service & /api/boundary async offloading.
Deterministic mock-based test suite (no live network dependency).
"""
import asyncio
import functools
import json
import os
import time
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import datav_service as datav


@pytest.fixture
def clean_cache(tmp_path, monkeypatch):
    """隔离缓存目录，确保测试不污染或依赖生产 cache/aoi/"""
    monkeypatch.setattr(datav, "_CACHE_DIR", str(tmp_path))
    # 重置内存缓存以保证独立性
    monkeypatch.setattr(datav, "_CITY_ADCODES_MEM_CACHE", None)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================
# 1. 单元测试：内部辅助函数与内存缓存
# ============================================================

class TestDatavHelperUnits:
    def test_find_adcode_prefers_exact_city_over_province_substring(self, monkeypatch):
        monkeypatch.setattr(datav, "_load_city_adcodes", lambda: {"吉林市": 220200})
        assert datav._find_adcode("吉林市") == 220200
        assert datav._find_adcode("吉林省") == 220000

    def test_find_adcode_does_not_guess_province_for_unknown_city(self, monkeypatch):
        monkeypatch.setattr(datav, "_load_city_adcodes", lambda: {"吉林市": 220200})
        assert datav._find_adcode("吉林新区市") == 0

    def test_find_adcode_empty_and_whitespace(self):
        assert datav._find_adcode("") == 0
        assert datav._find_adcode("   ") == 0
        assert datav._find_adcode(None) == 0

    def test_find_adcode_ambiguous_districts(self):
        # 鼓楼区消歧
        assert datav._find_adcode("江苏省南京市鼓楼区") == 320106
        assert datav._find_adcode("福建省福州市鼓楼区") == 350102
        # 无法消歧的裸区名返回 0，不盲目猜第一个
        assert datav._find_adcode("鼓楼区") == 0

    def test_get_ambiguous_candidates(self):
        cands = datav.get_ambiguous_candidates("鼓楼区")
        assert cands is not None and len(cands) >= 2
        # 精确限定城市后返回 None（无需消歧）
        assert datav.get_ambiguous_candidates("南京市鼓楼区") is None
        # 非重名地名返回 None
        assert datav.get_ambiguous_candidates("广州市") is None

    def test_convert_coordinates_gcj02_to_wgs84(self):
        coords = [116.404, 39.915]
        wgs = datav._convert(coords)
        assert len(wgs) == 2
        assert abs(wgs[0] - 116.404) > 0.0001 or abs(wgs[1] - 39.915) > 0.0001

        # 嵌套 Polygon 转换
        poly = [[[116.4, 39.9], [116.5, 39.9], [116.5, 40.0], [116.4, 39.9]]]
        conv_poly = datav._convert(poly)
        assert len(conv_poly[0]) == 4

    def test_load_city_adcodes_in_memory_cache(self, clean_cache, monkeypatch):
        disk_reads = 0
        cache_file = os.path.join(str(clean_cache), "_city_adcodes.json")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"测试市": 990100}, f)

        orig_open = open
        def spy_open(file, *args, **kwargs):
            nonlocal disk_reads
            if str(file).endswith("_city_adcodes.json"):
                disk_reads += 1
            return orig_open(file, *args, **kwargs)

        monkeypatch.setattr("builtins.open", spy_open)

        # 首次调用：从磁盘读取并存入内存
        map1 = datav._load_city_adcodes()
        assert map1.get("测试市") == 990100
        assert disk_reads == 1

        # 二次调用：直接命中内存缓存，不再打开磁盘文件
        map2 = datav._load_city_adcodes()
        assert map2.get("测试市") == 990100
        assert disk_reads == 1, "未命中内存缓存，发生了额外的磁盘读取！"


# ============================================================
# 2. 单元测试：fetch_boundary_by_adcode
# ============================================================

class TestFetchBoundaryByAdcode:
    def test_invalid_adcode_returns_none(self):
        assert datav.fetch_boundary_by_adcode("43") is None
        assert datav.fetch_boundary_by_adcode("abcdef") is None
        assert datav.fetch_boundary_by_adcode("1234567") is None
        assert datav.fetch_boundary_by_adcode("") is None

    def test_mock_success_and_cache(self, clean_cache, monkeypatch):
        mock_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "长沙市", "adcode": 430100, "level": "city"},
                    "geometry": {"type": "Polygon", "coordinates": [[[112.9, 28.1], [113.0, 28.1], [113.0, 28.2], [112.9, 28.1]]]}
                }
            ]
        }
        class MockResp:
            status_code = 200
            def json(self): return mock_data

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockResp())

        res = datav.fetch_boundary_by_adcode("430000")
        assert res is not None
        assert res["type"] == "FeatureCollection"
        assert "_cache_version" not in res

        # 验证写入缓存文件
        cache_file = os.path.join(str(clean_cache), "datav_adcode_430000.json")
        assert os.path.exists(cache_file)

    def test_cache_version_invalidation(self, clean_cache, monkeypatch):
        # 写入旧版本缓存
        cache_file = os.path.join(str(clean_cache), "datav_adcode_430000.json")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "_cache_version": 1, "features": []}, f)

        # 网络 mock 返回新数据
        class MockResp:
            status_code = 200
            def json(self):
                return {
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "properties": {"name": "新版"}}]
                }
        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockResp())

        res = datav.fetch_boundary_by_adcode("430000")
        assert res is not None
        assert res["features"][0]["properties"]["name"] == "新版"

    def test_network_failure_returns_none(self, clean_cache, monkeypatch):
        class Mock404:
            status_code = 404
            def json(self): return {}
        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: Mock404())
        assert datav.fetch_boundary_by_adcode("999999") is None


# ============================================================
# 3. 单元测试：fetch_boundary 与 404 惩罚消除
# ============================================================

class TestFetchBoundary:
    def test_empty_name_returns_none(self):
        assert datav.fetch_boundary("") is None
        assert datav.fetch_boundary("   ") is None
        assert datav.fetch_boundary(None) is None

    def test_eliminates_guaranteed_404_penalty(self, clean_cache, monkeypatch):
        requested_urls = []

        class MockResp:
            status_code = 200
            def json(self):
                return {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "北京市", "adcode": 110000},
                            "geometry": {"type": "Polygon", "coordinates": [[[116.4, 39.9], [116.5, 39.9], [116.5, 40.0], [116.4, 39.9]]]}
                        }
                    ]
                }

        def mock_get(url, *args, **kwargs):
            requested_urls.append(url)
            return MockResp()

        monkeypatch.setattr(datav.requests, "get", mock_get)

        res = datav.fetch_boundary("北京市")
        assert res is not None

        # 核心断言：严禁包含 URL-encoded 中文字符，严禁尝试获取不存在的中文名 JSON
        for url in requested_urls:
            assert "%" not in url, f"请求了 URL 编码的中文路径: {url}"
            assert "北京市" not in url, f"请求了中文路径: {url}"

        # 必须直接请求 110000_full.json
        assert any("110000_full.json" in url for url in requested_urls)
        assert len(requested_urls) == 1

    def test_direct_controlled_municipality_district_extraction(self, clean_cache, monkeypatch):
        """直辖市（北京、上海、天津、重庆）区县回溯上级代码必须为 110000, 310000 等"""
        requested_urls = []
        beijing_fc = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"name": "东城区", "adcode": 110101}},
                {
                    "type": "Feature",
                    "properties": {"name": "朝阳区", "adcode": 110105},
                    "geometry": {"type": "Polygon", "coordinates": [[[116.4, 39.9], [116.5, 39.9], [116.5, 40.0], [116.4, 39.9]]]}
                }
            ]
        }
        class MockResp:
            def __init__(self, code, data):
                self.status_code = code
                self._data = data
            def json(self): return self._data

        def mock_get(url, *a, **k):
            requested_urls.append(url)
            if "110105.json" in url or "110105_full.json" in url:
                return MockResp(404, {})
            if "110000_full.json" in url:
                return MockResp(200, beijing_fc)
            return MockResp(404, {})

        monkeypatch.setattr(datav.requests, "get", mock_get)
        monkeypatch.setattr(datav, "_load_city_adcodes", lambda: {"北京市朝阳区": 110105})

        res = datav.fetch_boundary("北京市朝阳区")
        assert res is not None
        assert res["type"] == "FeatureCollection"
        assert len(res["features"]) == 1
        assert res["features"][0]["properties"]["name"] == "朝阳区"
        # 确认回溯上级是直辖市代码 110000，而不是错误的 110100
        assert any("110000_full.json" in url for url in requested_urls)
        assert not any("110100_full.json" in url for url in requested_urls)

    def test_prefecture_district_extraction(self, clean_cache, monkeypatch):
        """常规地级市区县回溯上级代码为前四位+00（如 320100）"""
        requested_urls = []
        city_mock = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"name": "玄武区", "adcode": 320102}},
                {
                    "type": "Feature",
                    "properties": {"name": "鼓楼区", "adcode": 320106},
                    "geometry": {"type": "Polygon", "coordinates": [[[118.7, 32.0], [118.8, 32.0], [118.8, 32.1], [118.7, 32.0]]]}
                }
            ]
        }
        class MockResp:
            def __init__(self, code, data):
                self.status_code = code
                self._data = data
            def json(self): return self._data

        def mock_get(url, *a, **k):
            requested_urls.append(url)
            if "320106.json" in url or "320106_full.json" in url:
                return MockResp(404, {})
            if "320100_full.json" in url:
                return MockResp(200, city_mock)
            return MockResp(404, {})

        monkeypatch.setattr(datav.requests, "get", mock_get)

        res = datav.fetch_boundary("江苏省南京市鼓楼区")
        assert res is not None
        assert res["type"] == "FeatureCollection"
        assert len(res["features"]) == 1
        assert res["features"][0]["properties"]["name"] == "鼓楼区"
        assert any("320100_full.json" in url for url in requested_urls)

    def test_single_district_json_endpoint_priority(self, clean_cache, monkeypatch):
        """当单区县 {adcode}.json 可用时直接使用，无需拉取上级全集"""
        district_fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "天河区", "adcode": 440106},
                    "geometry": {"type": "Polygon", "coordinates": [[[113.3, 23.1], [113.4, 23.1], [113.4, 23.2], [113.3, 23.1]]]}
                }
            ]
        }
        requested_urls = []
        class MockResp:
            status_code = 200
            def json(self): return district_fc

        def mock_get(url, *a, **k):
            requested_urls.append(url)
            return MockResp()

        monkeypatch.setattr(datav.requests, "get", mock_get)
        monkeypatch.setattr(datav, "_load_city_adcodes", lambda: {"天河区": 440106})

        res = datav.fetch_boundary("天河区")
        assert res is not None
        assert res["features"][0]["properties"]["name"] == "天河区"
        assert any("440106.json" in url for url in requested_urls)
        # 不应拉取 440100_full.json
        assert not any("440100_full.json" in url for url in requested_urls)

    def test_shared_adcode_cache(self, clean_cache, monkeypatch):
        """若 datav_adcode_{adcode}.json 已存在，fetch_boundary 能够复用该缓存"""
        cache_file = os.path.join(str(clean_cache), "datav_adcode_110000.json")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "type": "FeatureCollection",
                "_cache_version": datav._CACHE_VERSION,
                "features": [{"type": "Feature", "properties": {"name": "北京市（来自adcode缓存）"}}]
            }, f)

        # 没有网络请求应被触发
        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: pytest.fail("不应发生网络请求"))

        res = datav.fetch_boundary("北京市")
        assert res is not None
        assert res["features"][0]["properties"]["name"] == "北京市（来自adcode缓存）"

    def test_numeric_adcode_input(self, clean_cache, monkeypatch):
        """传入 6 位数字代码时直接作为 adcode 处理"""
        class MockResp:
            status_code = 200
            def json(self):
                return {
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "properties": {"name": "湖南省", "adcode": 430000}}]
                }
        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockResp())
        res = datav.fetch_boundary("430000")
        assert res is not None
        assert res["features"][0]["properties"]["name"] == "湖南省"

    def test_not_found_adcode_returns_none(self, clean_cache, monkeypatch):
        monkeypatch.setattr(datav, "_load_city_adcodes", lambda: {})
        res = datav.fetch_boundary("不存在的虚构地点")
        assert res is None


# ============================================================
# 4. 路由集成测试：/api/boundary 契约与状态码规范
# ============================================================

class TestBoundaryApiRoutes:
    def test_route_boundary_with_valid_adcode(self, monkeypatch, client):
        monkeypatch.setattr(datav, "fetch_boundary_by_adcode", lambda ad: {"type": "FeatureCollection", "features": []})
        resp = client.get("/api/boundary", params={"adcode": "430000"})
        assert resp.status_code == 200
        body = resp.json()
        assert "geojson" in body
        assert body["adcode"] == "430000"

    def test_route_boundary_with_invalid_adcode(self, client):
        resp = client.get("/api/boundary", params={"adcode": "43"})
        assert resp.status_code == 400
        assert "6 位数字" in resp.json()["detail"]

        resp_alpha = client.get("/api/boundary", params={"adcode": "abcdef"})
        assert resp_alpha.status_code == 400

    def test_route_boundary_with_adcode_not_found(self, monkeypatch, client):
        monkeypatch.setattr(datav, "fetch_boundary_by_adcode", lambda ad: None)
        resp = client.get("/api/boundary", params={"adcode": "999999"})
        assert resp.status_code == 404
        assert "未找到" in resp.json()["detail"]

    def test_route_boundary_with_valid_place(self, monkeypatch, client):
        monkeypatch.setattr(datav, "fetch_boundary", lambda p: {"type": "FeatureCollection", "features": []})
        resp = client.get("/api/boundary", params={"place": "北京市"})
        assert resp.status_code == 200
        body = resp.json()
        assert "geojson" in body
        assert body["name"] == "北京市边界"

    def test_route_boundary_default_place(self, monkeypatch, client):
        monkeypatch.setattr(datav, "fetch_boundary", lambda p: {"type": "FeatureCollection", "features": []})
        resp = client.get("/api/boundary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "长沙市边界"

    def test_route_boundary_empty_place_returns_400(self, client):
        resp = client.get("/api/boundary", params={"place": ""})
        assert resp.status_code == 400
        assert "不能为空" in resp.json()["detail"]

    def test_route_boundary_whitespace_place_returns_400(self, client):
        resp_space = client.get("/api/boundary", params={"place": "   "})
        assert resp_space.status_code == 400
        assert "不能为空" in resp_space.json()["detail"]

    def test_route_boundary_place_not_found_returns_404(self, monkeypatch, client):
        monkeypatch.setattr(datav, "fetch_boundary", lambda p: None)
        resp = client.get("/api/boundary", params={"place": "不存在的虚拟城市"})
        assert resp.status_code == 404
        assert "未找到" in resp.json()["detail"]

    def test_route_boundary_internal_error_returns_500(self, monkeypatch, client):
        def raise_err(name):
            raise RuntimeError("模拟底层异常")
        monkeypatch.setattr(datav, "fetch_boundary", raise_err)
        resp = client.get("/api/boundary", params={"place": "北京市"})
        assert resp.status_code == 500
        assert "获取边界数据失败" in resp.json()["detail"]


# ============================================================
# 5. 事件循环非阻塞验证（异步并发探针）
# ============================================================

class TestBoundaryEventLoopNonBlocking:
    def test_route_boundary_place_does_not_block_event_loop(self, monkeypatch):
        """验证 fetch_boundary 在 place 分支中已正确移交线程池，不冻结 asyncio 事件循环"""
        ticks = 0

        def slow_fetch(name):
            t0 = ticks
            time.sleep(0.12)  # 模拟网络 IO 阻塞 120ms
            t1 = ticks
            return t1 - t0

        ticks_during_fetch = []

        def tracked_fetch(name):
            delta = slow_fetch(name)
            ticks_during_fetch.append(delta)
            return {"type": "FeatureCollection", "features": []}

        monkeypatch.setattr(datav, "fetch_boundary", tracked_fetch)

        async def run_probe():
            stop = False
            async def ticker():
                nonlocal stop, ticks
                while not stop:
                    await asyncio.sleep(0.01)
                    ticks += 1

            ticker_task = asyncio.create_task(ticker())
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get("/api/boundary", params={"place": "北京市"})
                    assert resp.status_code == 200
            finally:
                stop = True
                await ticker_task

        asyncio.run(run_probe())

        assert len(ticks_during_fetch) == 1
        # 若直接在主事件循环运行，主循环冻结，ticks 恒为 0
        # 正确交由 run_in_executor 线程池运行时，心跳协程持续累加
        assert ticks_during_fetch[0] >= 3, f"事件循环被阻塞！心跳滴答数仅为: {ticks_during_fetch[0]}"
