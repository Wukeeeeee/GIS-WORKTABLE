# -*- coding: utf-8 -*-
"""GIS URL 探测与数据抽取服务单元测试"""

import os
import io
import json
import zipfile
import tempfile
from unittest.mock import patch, MagicMock
import pytest
from backend.services import url_gis_service as ugs


@pytest.fixture
def mock_geojson_data():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.397, 39.908]},
                "properties": {"name": "天安门", "type": "A级景区", "city": "北京"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.405, 39.915]},
                "properties": {"name": "故宫", "type": "5A景区", "city": "北京"},
            },
        ],
    }


@pytest.fixture
def mock_arcgis_service_json():
    return {
        "currentVersion": 10.81,
        "mapName": "Beijing_POI",
        "description": "北京兴趣点与行政区划服务",
        "spatialReference": {"wkid": 4326, "latestWkid": 4326},
        "layers": [
            {"id": 0, "name": "景区点位", "parentLayerId": -1, "geometryType": "esriGeometryPoint"},
            {"id": 1, "name": "行政边界", "parentLayerId": -1, "geometryType": "esriGeometryPolygon"},
        ],
        "fullExtent": {"xmin": 115.4, "ymin": 39.4, "xmax": 117.5, "ymax": 41.0},
    }


@pytest.fixture
def mock_arcgis_layer_json():
    return {
        "id": 0,
        "name": "景区点位",
        "type": "Feature Layer",
        "geometryType": "esriGeometryPoint",
        "spatialReference": {"wkid": 4326, "latestWkid": 4326},
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "序号"},
            {"name": "NAME", "type": "esriFieldTypeString", "alias": "景点名称"},
            {"name": "LEVEL", "type": "esriFieldTypeString", "alias": "评级"},
        ],
        "extent": {"xmin": 116.0, "ymin": 39.5, "xmax": 116.8, "ymax": 40.2},
        "maxRecordCount": 2000,
    }


def _make_mock_response(json_data=None, text_data=None, content_bytes=None, headers=None, status_code=200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = headers or {"Content-Type": "application/json"}
    if json_data is not None:
        mock_resp.json = MagicMock(return_value=json_data)
        mock_resp.content = json.dumps(json_data).encode("utf-8")
        mock_resp.text = json.dumps(json_data)
    elif text_data is not None:
        mock_resp.text = text_data
        mock_resp.content = text_data.encode("utf-8")
    elif content_bytes is not None:
        mock_resp.content = content_bytes
        mock_resp.text = content_bytes.decode("utf-8", errors="ignore")
    return mock_resp


def _read_tls_client_hello_sni(stream):
    record_header = stream.read(5)
    if len(record_header) != 5 or record_header[0] != 22:
        return None
    record = stream.read(int.from_bytes(record_header[3:5], "big"))
    if len(record) < 4 or record[0] != 1:
        return None
    body = memoryview(record)[4:]
    offset = 2 + 32
    if len(body) <= offset:
        return None
    offset += 1 + body[offset]
    if len(body) < offset + 2:
        return None
    cipher_length = int.from_bytes(body[offset:offset + 2], "big")
    offset += 2 + cipher_length
    if len(body) <= offset:
        return None
    compression_length = body[offset]
    offset += 1 + compression_length
    if len(body) < offset + 2:
        return None
    extensions_length = int.from_bytes(body[offset:offset + 2], "big")
    offset += 2
    extensions_end = min(len(body), offset + extensions_length)
    while offset + 4 <= extensions_end:
        extension_type = int.from_bytes(body[offset:offset + 2], "big")
        extension_length = int.from_bytes(body[offset + 2:offset + 4], "big")
        offset += 4
        extension = body[offset:offset + extension_length]
        offset += extension_length
        if extension_type != 0 or len(extension) < 5:
            continue
        name_type = extension[2]
        name_length = int.from_bytes(extension[3:5], "big")
        if name_type == 0 and len(extension) >= 5 + name_length:
            return bytes(extension[5:5 + name_length]).decode("ascii", errors="replace")
    return None


def test_inspect_gis_url_geojson(mock_geojson_data):
    url = "https://example.com/beijing_poi.geojson"
    mock_resp = _make_mock_response(json_data=mock_geojson_data)
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.inspect_gis_url(url)
        assert res["ok"] is True
        assert res["service_type"] == "GeoJSON"
        assert res["feature_count"] == 2
        assert "Point" in res["geometry_types"]
        assert "name" in res["fields"]
        assert res["bbox"] is not None


def test_http_get_blocks_public_redirect_to_private_target(monkeypatch):
    monkeypatch.setattr(ugs, "is_public_http_target", lambda url: True)
    redirect = _make_mock_response(headers={"Location": "http://127.0.0.1/admin"}, status_code=302)
    request = MagicMock(return_value=redirect)
    with patch("backend.services.url_gis_service.requests.Session.get", request):
        with pytest.raises(ugs.UrlGisError, match="跳转地址不符合安全策略"):
            ugs._http_get("https://public.example/data")
    request.assert_called_once()
    assert request.call_args.kwargs["allow_redirects"] is False


def test_http_get_bypasses_configured_proxy_for_direct_private_source(monkeypatch):
    monkeypatch.setattr(ugs, "is_public_http_target", lambda _url: False)
    monkeypatch.setattr(ugs, "get_effective_proxies", lambda: {
        "http": "http://proxy.example:8080", "https": "http://proxy.example:8080",
    })
    response = _make_mock_response(content_bytes=b"private data")
    request = MagicMock(return_value=response)
    with patch("backend.services.url_gis_service.requests.Session.get", request):
        ugs._http_get("http://10.0.0.5/data.geojson")

    assert request.call_args.kwargs["proxies"] == {"http": None, "https": None}


def test_url_gis_blocks_public_http_query_credentials_before_connect(monkeypatch):
    from backend.services import url_security

    monkeypatch.setattr(ugs, "get_effective_proxies", lambda: {})
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )

    with pytest.raises(ugs.UrlGisError) as exc:
        ugs._http_get("http://provider.example/data.geojson?api_key=KEY_SENTINEL")

    assert "KEY_SENTINEL" not in str(exc.value)
    assert "公网 HTTP 不允许明文发送凭据" in str(exc.value)


def test_http_get_allows_user_direct_private_url_and_private_redirect(monkeypatch):
    monkeypatch.setattr(ugs, "is_public_http_target", lambda _url: False)
    redirect = _make_mock_response(headers={"Location": "http://10.0.0.8/data"}, status_code=302)
    final = _make_mock_response(json_data={"ok": True})
    request = MagicMock(side_effect=[redirect, final])
    with patch("backend.services.url_gis_service.requests.Session.get", request):
        assert ugs._http_get("http://10.0.0.5/catalog") is final
    assert request.call_count == 2
    assert request.call_args_list[1].args[0] == "http://10.0.0.8/data"


def test_http_get_blocks_private_redirect_chain_returning_from_public(monkeypatch):
    from backend.services import url_security

    classifications = {
        "http://10.0.0.5/catalog": False,
        "https://public.example/data": True,
        "http://10.0.0.8/admin": False,
    }
    monkeypatch.setattr(ugs, "is_public_http_target", lambda url: classifications[url])
    monkeypatch.setattr(url_security, "is_public_http_target", lambda url: classifications[url])
    to_public = _make_mock_response(
        headers={"Location": "https://public.example/data"}, status_code=302
    )
    back_to_private = _make_mock_response(
        headers={"Location": "http://10.0.0.8/admin"}, status_code=302
    )
    request = MagicMock(side_effect=[to_public, back_to_private])
    with patch("backend.services.url_gis_service.requests.Session.get", request):
        with pytest.raises(ugs.UrlGisError, match="跳转地址不符合安全策略"):
            ugs._http_get("http://10.0.0.5/catalog")

    assert request.call_count == 2


def test_http_get_allows_public_redirect_to_public_target(monkeypatch):
    from backend.services import url_security
    monkeypatch.setattr(ugs, "is_public_http_target", lambda _url: True)
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: True)
    redirect = _make_mock_response(headers={"Location": "/data.geojson"}, status_code=302)
    final = _make_mock_response(json_data={"type": "FeatureCollection", "features": []})
    request = MagicMock(side_effect=[redirect, final])
    with patch("backend.services.url_gis_service.requests.Session.get", request):
        assert ugs._http_get("https://public.example/catalog") is final
    assert request.call_args_list[1].args[0] == "https://public.example/data.geojson"


def test_http_get_strips_sensitive_query_credentials_on_cross_origin_redirect(monkeypatch):
    from backend.services import url_security

    monkeypatch.setattr(ugs, "is_public_http_target", lambda _url: True)
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: True)
    redirect = _make_mock_response(
        headers={
            "Location": "https://cdn.example/data?api_key=KEY_SENTINEL&format=geojson&signature=CDN_SIG",
        },
        status_code=302,
    )
    final = _make_mock_response(json_data={"ok": True})
    request = MagicMock(side_effect=[redirect, final])
    source = "https://provider.example/data?api_key=KEY_SENTINEL&format=geojson"

    with patch("backend.services.url_gis_service.requests.Session.get", request):
        assert ugs._http_get(source) is final

    assert request.call_args_list[1].args[0] == (
        "https://cdn.example/data?format=geojson&signature=CDN_SIG"
    )


def test_http_get_strips_sensitive_params_on_cross_origin_redirect(monkeypatch):
    from backend.services import url_security

    monkeypatch.setattr(ugs, "is_public_http_target", lambda _url: True)
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: True)
    redirect = _make_mock_response(
        headers={"Location": "https://cdn.example/query?token=TOKEN_SENTINEL&f=json"},
        status_code=302,
    )
    final = _make_mock_response(json_data={"ok": True})
    request = MagicMock(side_effect=[redirect, final])
    params = {"token": "TOKEN_SENTINEL", "f": "json"}

    with patch("backend.services.url_gis_service.requests.Session.get", request):
        assert ugs._http_get("https://provider.example/arcgis", params=params) is final

    assert request.call_args_list[0].kwargs["params"] == params
    assert request.call_args_list[1].args[0] == "https://cdn.example/query?f=json"


def test_http_get_explains_auth_failure_after_stripping_cross_origin_credentials(monkeypatch):
    from backend.services import url_security

    monkeypatch.setattr(ugs, "is_public_http_target", lambda _url: True)
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: True)
    redirect = _make_mock_response(
        headers={"Location": "https://cdn.example/data?token=TOKEN_SENTINEL"},
        status_code=302,
    )
    unauthorized = _make_mock_response(status_code=403)
    request = MagicMock(side_effect=[redirect, unauthorized])

    with patch("backend.services.url_gis_service.requests.Session.get", request):
        with pytest.raises(ugs.UrlGisError, match="改用服务方提供的直连地址") as exc:
            ugs._http_get("https://provider.example/data?token=TOKEN_SENTINEL")

    assert "TOKEN_SENTINEL" not in str(exc.value)
    assert request.call_args_list[1].args[0] == "https://cdn.example/data"
    unauthorized.close.assert_called_once()


def test_http_get_preserves_sensitive_query_credentials_on_same_origin_redirect(monkeypatch):
    from backend.services import url_security

    monkeypatch.setattr(ugs, "is_public_http_target", lambda _url: True)
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: True)
    redirect = _make_mock_response(
        headers={"Location": "/next?token=TOKEN_SENTINEL&format=geojson"},
        status_code=302,
    )
    final = _make_mock_response(json_data={"ok": True})
    request = MagicMock(side_effect=[redirect, final])

    with patch("backend.services.url_gis_service.requests.Session.get", request):
        assert ugs._http_get("https://provider.example/data?token=TOKEN_SENTINEL") is final

    assert request.call_args_list[1].args[0] == (
        "https://provider.example/next?token=TOKEN_SENTINEL&format=geojson"
    )


def test_sensitive_query_parameter_names_recognizes_credentials():
    from backend.services.url_security import sensitive_query_parameter_names

    assert sensitive_query_parameter_names(
        "https://provider.example/data?api_key=KEY_SENTINEL&access_token=TOKEN_SENTINEL&key=KEY2&format=json&monkey=ordinary"
    ) == {"api_key", "access_token", "key"}


def test_http_get_closes_and_rejects_oversized_streamed_response(monkeypatch):
    monkeypatch.setattr(ugs, "_HTTP_RESPONSE_CAP_BYTES", 5)
    response = _make_mock_response(headers={})
    response.iter_content = MagicMock(return_value=iter([b"1234", b"5678"]))
    response.close = MagicMock()
    with patch("backend.services.url_gis_service.requests.Session.get", return_value=response):
        with pytest.raises(ugs.UrlGisError, match="远程 GIS 响应超过"):
            ugs._http_get("https://public.example/large.geojson")
    response.close.assert_called_once()


def test_http_get_rejects_oversized_content_length_without_reading(monkeypatch):
    monkeypatch.setattr(ugs, "_HTTP_RESPONSE_CAP_BYTES", 5)
    response = _make_mock_response(headers={"Content-Length": "6"})
    response.iter_content = MagicMock(side_effect=AssertionError("body should not be read"))
    response.close = MagicMock()
    with patch("backend.services.url_gis_service.requests.Session.get", return_value=response):
        with pytest.raises(ugs.UrlGisError, match="远程 GIS 响应超过"):
            ugs._http_get("https://public.example/large.geojson")
    response.close.assert_called_once()


def test_http_get_keeps_bounded_response_readable_after_closing_stream():
    body = b'{"features": []}'
    response = ugs.requests.Response()
    response.status_code = 200
    response.url = "https://public.example/data.geojson"
    response.headers = {"Content-Length": str(len(body)), "Content-Type": "application/json"}
    response.raw = io.BytesIO(body)
    with patch("backend.services.url_gis_service.requests.Session.get", return_value=response):
        result = ugs._http_get(response.url)

    assert result is response
    assert result.content == body
    assert result.json() == {"features": []}


def test_http_get_connects_to_the_same_dns_answer_used_for_public_check(monkeypatch):
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from backend.services import url_security

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"features": []}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_getaddrinfo = socket.getaddrinfo
    original_create_connection = url_security.create_connection
    host_resolution_count = 0
    monkeypatch.setattr(ugs, "get_effective_proxies", lambda: {})
    monkeypatch.setattr(ugs.requests.sessions, "get_environ_proxies", lambda *_args, **_kwargs: {})

    def rebinding_getaddrinfo(host, port, *args, **kwargs):
        nonlocal host_resolution_count
        if host == "public-pin.example":
            host_resolution_count += 1
            answer = "8.8.8.8" if host_resolution_count <= 2 else "127.0.0.1"
            return original_getaddrinfo(answer, port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    def route_fixture_ip_to_loopback(address, *args, **kwargs):
        if address[0] == "8.8.8.8":
            address = ("127.0.0.1", server.server_port)
        return original_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)
    monkeypatch.setattr(url_security, "create_connection", route_fixture_ip_to_loopback)
    try:
        response = ugs._http_get(f"http://public-pin.example:{server.server_port}/data")
        assert response.json() == {"features": []}
        assert host_resolution_count == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_get_rejects_public_to_private_dns_change_before_connect(monkeypatch):
    import socket
    from backend.services import url_security

    original_getaddrinfo = socket.getaddrinfo
    host_resolution_count = 0
    monkeypatch.setattr(ugs, "get_effective_proxies", lambda: {})
    monkeypatch.setattr(ugs.requests.sessions, "get_environ_proxies", lambda *_args, **_kwargs: {})

    def rebinding_getaddrinfo(host, port, *args, **kwargs):
        nonlocal host_resolution_count
        if host == "rebinding.example":
            host_resolution_count += 1
            answer = "8.8.8.8" if host_resolution_count == 1 else "127.0.0.1"
            return original_getaddrinfo(answer, port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    def unexpected_connect(*_args, **_kwargs):
        raise AssertionError("connection must not start after the DNS answer changes to private")

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)
    monkeypatch.setattr(url_security, "create_connection", unexpected_connect)
    with pytest.raises(ugs.UrlGisError, match="公网 DNS 安全检查"):
        ugs._http_get("http://rebinding.example/data")
    assert host_resolution_count == 2


def test_safe_urllib_opener_connects_to_checked_dns_answer(monkeypatch):
    import socket
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from backend.services import url_security

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"pinned"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_getaddrinfo = socket.getaddrinfo
    original_create_connection = socket.create_connection
    host_resolution_count = 0

    def rebinding_getaddrinfo(host, port, *args, **kwargs):
        nonlocal host_resolution_count
        if host == "urllib-pin.example":
            host_resolution_count += 1
            answer = "8.8.8.8" if host_resolution_count <= 2 else "127.0.0.1"
            return original_getaddrinfo(answer, port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    def route_fixture_ip_to_loopback(address, *args, **kwargs):
        if address[0] == "8.8.8.8":
            address = ("127.0.0.1", server.server_port)
        return original_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", route_fixture_ip_to_loopback)
    source = f"http://urllib-pin.example:{server.server_port}/data"
    try:
        opener = url_security.safe_redirect_opener(urllib.request.ProxyHandler({}), source)
        with opener.open(source, timeout=2) as response:
            assert response.read() == b"pinned"
        assert host_resolution_count == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_safe_urllib_opener_bypasses_proxy_for_direct_private_source(monkeypatch):
    import urllib.request
    from backend.services import url_security

    configured_proxy = urllib.request.ProxyHandler({
        "http": "http://proxy.example:8080", "https": "http://proxy.example:8080",
    })
    original_build_opener = urllib.request.build_opener
    passed_handlers = []

    def capture_handlers(*handlers):
        passed_handlers.extend(handlers)
        return original_build_opener(*handlers)

    monkeypatch.setattr(url_security.urllib.request, "build_opener", capture_handlers)
    opener = url_security.safe_redirect_opener(configured_proxy, "http://10.0.0.5/catalog")
    proxy_handlers = [handler for handler in passed_handlers if isinstance(handler, urllib.request.ProxyHandler)]

    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    assert opener is not None


def test_http_get_pins_public_target_before_forwarding_through_http_proxy(monkeypatch):
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from backend.services import url_security

    observed = {}

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed["target"] = self.path
            observed["host"] = self.headers.get("Host")
            body = b'{"features": []}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            pass

    proxy_server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    thread.start()
    original_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(ugs, "get_effective_proxies", lambda: {
        "http": f"http://127.0.0.1:{proxy_server.server_port}",
        "https": f"http://127.0.0.1:{proxy_server.server_port}",
    })
    monkeypatch.setattr(ugs.requests.sessions, "get_environ_proxies", lambda *_args, **_kwargs: {})

    def resolve_public_target(host, port, *args, **kwargs):
        if host == "public-proxy.example":
            return original_getaddrinfo("8.8.8.8", port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_target)
    source = "http://public-proxy.example:8088/data.geojson"
    try:
        response = ugs._http_get(source)
        assert response.json() == {"features": []}
        assert observed == {
            "target": "http://8.8.8.8:8088/data.geojson",
            "host": "public-proxy.example:8088",
        }
    finally:
        proxy_server.shutdown()
        proxy_server.server_close()
        thread.join(timeout=2)


def test_safe_urllib_opener_pins_public_target_before_http_proxy(monkeypatch):
    import socket
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from backend.services import url_security

    observed = {}

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed["target"] = self.path
            observed["host"] = self.headers.get("Host")
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            pass

    proxy_server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    thread.start()
    original_getaddrinfo = socket.getaddrinfo

    def resolve_public_target(host, port, *args, **kwargs):
        if host == "public-urllib-proxy.example":
            return original_getaddrinfo("8.8.8.8", port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_target)
    source = "http://public-urllib-proxy.example:8088/data"
    proxy_handler = urllib.request.ProxyHandler({
        "http": f"http://127.0.0.1:{proxy_server.server_port}",
    })
    try:
        opener = url_security.safe_redirect_opener(proxy_handler, source)
        with opener.open(source, timeout=3) as response:
            assert response.read() == b"ok"
        assert observed == {
            "target": "http://8.8.8.8:8088/data",
            "host": "public-urllib-proxy.example:8088",
        }
    finally:
        proxy_server.shutdown()
        proxy_server.server_close()
        thread.join(timeout=2)


def test_https_requests_proxy_tunnels_to_pinned_ip(monkeypatch):
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from backend.services import url_security

    observed = []

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            self.send_response(200, "Connection Established")
            self.end_headers()
            self.wfile.flush()
            self.connection.settimeout(3)
            observed.append((self.path, _read_tls_client_hello_sni(self.rfile)))

        def log_message(self, _format, *_args):
            pass

    proxy_server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    thread.start()
    original_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(ugs, "get_effective_proxies", lambda: {
        "http": f"http://127.0.0.1:{proxy_server.server_port}",
        "https": f"http://127.0.0.1:{proxy_server.server_port}",
    })
    monkeypatch.setattr(ugs.requests.sessions, "get_environ_proxies", lambda *_args, **_kwargs: {})

    def resolve_public_target(host, port, *args, **kwargs):
        if host == "public-https-proxy.example":
            return original_getaddrinfo("8.8.8.8", port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_target)
    try:
        with pytest.raises(ugs.UrlGisError):
            ugs._http_get("https://public-https-proxy.example/data")
        assert observed == [("8.8.8.8:443", "public-https-proxy.example")]
    finally:
        proxy_server.shutdown()
        proxy_server.server_close()
        thread.join(timeout=2)


def test_https_urllib_proxy_tunnels_to_pinned_ip(monkeypatch):
    import socket
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from backend.services import url_security

    observed = []

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            self.send_response(200, "Connection Established")
            self.end_headers()
            self.wfile.flush()
            self.connection.settimeout(3)
            observed.append((self.path, _read_tls_client_hello_sni(self.rfile)))

        def log_message(self, _format, *_args):
            pass

    proxy_server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    thread.start()
    original_getaddrinfo = socket.getaddrinfo

    def resolve_public_target(host, port, *args, **kwargs):
        if host == "public-https-urllib-proxy.example":
            return original_getaddrinfo("8.8.8.8", port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve_public_target)
    source = "https://public-https-urllib-proxy.example/data"
    proxy_handler = urllib.request.ProxyHandler({
        "https": f"http://127.0.0.1:{proxy_server.server_port}",
    })
    try:
        opener = url_security.safe_redirect_opener(proxy_handler, source)
        with pytest.raises((urllib.error.URLError, OSError)):
            opener.open(source, timeout=3)
        assert observed == [("8.8.8.8:443", "public-https-urllib-proxy.example")]
    finally:
        proxy_server.shutdown()
        proxy_server.server_close()
        thread.join(timeout=2)


def test_mixed_public_and_private_dns_results_keep_redirect_protection(monkeypatch):
    from backend.services import url_security

    monkeypatch.setattr(url_security.socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("8.8.8.8", 443)),
        (None, None, None, None, ("10.0.0.9", 443)),
    ])
    source = "https://mixed.example/data"
    assert url_security.is_public_http_target(source) is None

    opener = url_security.safe_redirect_opener(url_security.urllib.request.ProxyHandler({}), source)
    redirect_handler = next(
        handler for handler in opener.handlers
        if isinstance(handler, url_security.SafeHTTPRedirectHandler)
    )
    assert redirect_handler.protect_public_target is True
    assert not url_security.redirect_is_allowed("http://10.0.0.9/admin", redirect_handler.protect_public_target)


def test_safe_urllib_opener_rejects_mixed_dns_answers_before_connect(monkeypatch):
    import socket
    import urllib.error
    import urllib.request
    from backend.services import url_security

    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 80)),
    ]
    monkeypatch.setattr(url_security.socket, "getaddrinfo", lambda *_args, **_kwargs: records)
    monkeypatch.setattr(
        url_security,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ambiguous target must not connect")),
    )
    opener = url_security.safe_redirect_opener(
        urllib.request.ProxyHandler({}), "http://mixed-urllib.example/data"
    )

    with pytest.raises(urllib.error.URLError, match="public DNS safety check"):
        opener.open("http://mixed-urllib.example/data", timeout=1)


def test_safe_urllib_opener_rejects_private_to_public_dns_change(monkeypatch):
    import socket
    import urllib.error
    import urllib.request
    from backend.services import url_security

    original_getaddrinfo = socket.getaddrinfo
    resolution_count = 0

    def rebinding_getaddrinfo(host, port, *args, **kwargs):
        nonlocal resolution_count
        if host == "private-urllib-rebinding.example":
            resolution_count += 1
            address = "10.0.0.8" if resolution_count == 1 else "8.8.8.8"
            return original_getaddrinfo(address, port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)
    monkeypatch.setattr(
        url_security,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("changed target must not connect")),
    )
    source = "http://private-urllib-rebinding.example/data?api_key=TEST_KEY"
    opener = url_security.safe_redirect_opener(urllib.request.ProxyHandler({}), source)

    with pytest.raises(urllib.error.URLError, match="public DNS safety check"):
        opener.open(source, timeout=1)
    assert resolution_count == 2


def test_http_get_rejects_mixed_dns_answers_before_connect(monkeypatch):
    import socket
    from backend.services import url_security

    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 80)),
    ]
    monkeypatch.setattr(url_security.socket, "getaddrinfo", lambda *_args, **_kwargs: records)
    monkeypatch.setattr(ugs, "get_effective_proxies", lambda: {})
    monkeypatch.setattr(ugs.requests.sessions, "get_environ_proxies", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        url_security,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ambiguous target must not connect")),
    )

    with pytest.raises(ugs.UrlGisError, match="公网 DNS 安全检查"):
        ugs._http_get("http://mixed.example/data")


def test_http_get_rejects_private_to_public_dns_change_before_connect(monkeypatch):
    import socket
    from backend.services import url_security

    original_getaddrinfo = socket.getaddrinfo
    resolution_count = 0
    monkeypatch.setattr(ugs, "get_effective_proxies", lambda: {})
    monkeypatch.setattr(ugs.requests.sessions, "get_environ_proxies", lambda *_args, **_kwargs: {})

    def rebinding_getaddrinfo(host, port, *args, **kwargs):
        nonlocal resolution_count
        if host == "private-rebinding.example":
            resolution_count += 1
            address = "10.0.0.8" if resolution_count == 1 else "8.8.8.8"
            return original_getaddrinfo(address, port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)
    monkeypatch.setattr(
        url_security,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("changed target must not connect")),
    )

    with pytest.raises(ugs.UrlGisError, match="公网 DNS 安全检查"):
        ugs._http_get("http://private-rebinding.example/data?api_key=TEST_KEY")
    assert resolution_count == 2


def test_sanitize_error_text_hides_embedded_url_credentials_and_query_secrets():
    from backend.services.url_security import sanitize_error_text
    source = "https://user:PASS_SENTINEL@example.test/data.tif?token=TOKEN_SENTINEL&key=KEY_SENTINEL&format=tif#private"
    detail = sanitize_error_text(RuntimeError(f"read failed for {source}"), source)

    assert "PASS_SENTINEL" not in detail
    assert "TOKEN_SENTINEL" not in detail
    assert "KEY_SENTINEL" not in detail
    assert "private" not in detail
    assert "format=tif" in detail
    assert "https://example.test/data.tif?format=tif" in detail


def test_sanitize_http_url_leaves_local_paths_unchanged():
    from backend.services.url_security import sanitize_http_url
    assert sanitize_http_url(r"C:\gis\source.tif") == r"C:\gis\source.tif"
def test_inspect_gis_url_arcgis_service(mock_arcgis_service_json):
    url = "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Beijing/MapServer"
    mock_resp = _make_mock_response(json_data=mock_arcgis_service_json)
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.inspect_gis_url(url)
        assert res["ok"] is True
        assert res["service_type"] == "ArcGIS_REST_Service"
        assert res["layer_count"] == 2
        assert len(res["layers"]) == 2
        assert res["layers"][0]["name"] == "景区点位"


def test_inspect_gis_url_arcgis_layer(mock_arcgis_layer_json):
    url = "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Beijing/MapServer/0"
    mock_resp = _make_mock_response(json_data=mock_arcgis_layer_json)
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.inspect_gis_url(url)
        assert res["ok"] is True
        assert res["service_type"] == "ArcGIS_REST_Layer"
        assert res["layer_name"] == "景区点位"
        assert res["field_count"] == 3
        assert "NAME" in [f["name"] for f in res["fields"]]


def test_inspect_gis_url_wfs_xml():
    url = "https://example.com/geoserver/wfs"
    wfs_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <wfs:WFS_Capabilities version="2.0.0" xmlns:wfs="http://www.opengis.net/wfs/2.0">
        <wfs:FeatureTypeList>
            <wfs:FeatureType>
                <wfs:Name>workspace:roads</wfs:Name>
                <wfs:Title>Urban Roads</wfs:Title>
                <wfs:DefaultCRS>urn:ogc:def:crs:EPSG::4326</wfs:DefaultCRS>
            </wfs:FeatureType>
        </wfs:FeatureTypeList>
    </wfs:WFS_Capabilities>"""
    mock_resp = _make_mock_response(text_data=wfs_xml, headers={"Content-Type": "text/xml"})
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.inspect_gis_url(url)
        assert res["ok"] is True
        assert res["service_type"] == "OGC_WFS"
        assert res["layer_count"] == 1
        assert res["layers"][0]["name"] == "workspace:roads"


def test_fetch_gis_data_url_geojson(mock_geojson_data, tmp_path, monkeypatch):
    url = "https://example.com/data.geojson"
    monkeypatch.setattr("backend.services.url_gis_service._get_output_dir", lambda: str(tmp_path))

    mock_resp = _make_mock_response(json_data=mock_geojson_data)
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.fetch_gis_data_url(url, output_format="geojson")

        assert res["ok"] is True
        assert res["feature_count"] == 2
        assert os.path.exists(res["file_path"])
        assert "name" in res["fields"]

        # 检查生成的文件
        with open(res["file_path"], "r", encoding="utf-8") as f:
            saved_gj = json.load(f)
            assert len(saved_gj["features"]) == 2


def test_get_output_dir_reads_temp_dir_after_initialization(tmp_path, monkeypatch):
    from backend.services import tools
    monkeypatch.setattr(tools, "_temp_output_dir", "")
    monkeypatch.setattr(tools, "init_temp_dir", lambda: setattr(tools, "_temp_output_dir", str(tmp_path)))
    result = ugs._get_output_dir()
    assert result == str(tmp_path / "downloads")
    assert os.path.isdir(result)


def test_fetch_gis_data_url_csv(tmp_path, monkeypatch):
    url = "https://example.com/points.csv"
    csv_text = "id,name,lng,lat,val\n1,站点A,120.1,30.2,99\n2,站点B,120.2,30.3,88\n"
    monkeypatch.setattr("backend.services.url_gis_service._get_output_dir", lambda: str(tmp_path))

    mock_resp = _make_mock_response(text_data=csv_text, headers={"Content-Type": "text/csv"})
    with patch("backend.services.url_gis_service._http_get", return_value=mock_resp):
        res = ugs.fetch_gis_data_url(url, output_format="geojson")
        assert res["ok"] is True
        assert res["feature_count"] == 2
        assert res["crs"] == "EPSG:4326"
        assert os.path.exists(res["file_path"])


def test_arcgis_full_fetch_uses_object_id_batches_and_writes_delivery_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/arcgis/rest/services/roads/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {
        "service_type": "ArcGIS_REST_Layer", "layer_id": 0, "layer_name": "roads", "crs": "EPSG:4326"
    })
    metadata = {
        "objectIdField": "OBJECTID", "maxRecordCount": 2,
        "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
        "spatialReference": {"wkid": 4326},
    }
    calls = []
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        calls.append(dict(params))
        if "f=pjson" in _url or params.get("f") == "pjson":
            return _make_mock_response(json_data=metadata)
        if params.get("returnCountOnly"):
            return _make_mock_response(json_data={"count": 3})
        if params.get("returnIdsOnly"):
            return _make_mock_response(json_data={"objectIdFieldName": "OBJECTID", "objectIds": [1, 2, 3]})
        ids = [int(value) for value in params["objectIds"].split(",")]
        return _make_mock_response(json_data={
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [i, i]},
                          "properties": {"OBJECTID": i, "name": f"road-{i}"}} for i in ids],
        })
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url + "?token=secret", mode="full", output_format="gpkg")
    assert result["completeness"] == "complete"
    assert result["expected_count"] == result["feature_count"] == 3
    assert result["expected_count_known"] is True
    assert result["source_url"] == layer_url
    assert len([c for c in calls if c.get("objectIds")]) == 2
    assert os.path.exists(result["file_path"])
    manifest = json.loads(open(result["recipe_path"], encoding="utf-8").read())
    assert manifest["source_url"] == layer_url
    assert "secret" not in open(result["report_path"], encoding="utf-8").read()
    assert len(result["sha256"]) == 64


def test_arcgis_full_fetch_reports_missing_object_ids_as_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    def response_for(_url, params=None, **_kwargs):
        if "f=pjson" in _url or (params or {}).get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 100})
        if (params or {}).get("returnCountOnly"):
            return _make_mock_response(json_data={"count": 2})
        if (params or {}).get("returnIdsOnly"):
            return _make_mock_response(json_data={"objectIds": [1, 2]})
        return _make_mock_response(json_data={"features": [{"type": "Feature", "geometry": None,
                                                               "properties": {"OID": 1}}]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")
    assert result["completeness"] == "partial"
    assert result["feature_count"] == 1
    assert any(check["name"] == "missing_ids" and check["status"] == "failed" for check in result["checks"])


def test_arcgis_full_fetch_reports_duplicate_object_ids_as_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})

    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 100})
        if params.get("returnCountOnly"):
            return _make_mock_response(json_data={"count": 2})
        if params.get("returnIdsOnly"):
            return _make_mock_response(json_data={"objectIds": [1, 2]})
        return _make_mock_response(json_data={"features": [
            {"type": "Feature", "geometry": None, "properties": {"OID": 1}},
            {"type": "Feature", "geometry": None, "properties": {"OID": 1}},
            {"type": "Feature", "geometry": None, "properties": {"OID": 2}},
        ]})

    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")

    assert result["completeness"] == "partial"
    assert result["feature_count"] == 3
    assert any(check["name"] == "duplicate_ids" and check["status"] == "failed" for check in result["checks"])


def test_arcgis_empty_full_query_creates_a_valid_empty_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "fields": [{"name": "OID"}],
                                                  "sourceSpatialReference": {"wkid": 4326, "latestWkid": 4326}})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 0})
        if params.get("returnIdsOnly"): return _make_mock_response(json_data={"objectIds": []})
        return _make_mock_response(json_data={"features": []})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="full")
    assert result["feature_count"] == result["expected_count"] == 0
    assert result["completeness"] == "complete"
    assert result["bbox"] is None
    assert json.loads(open(result["file_path"], encoding="utf-8").read())["features"] == []


def test_arcgis_batch_failure_keeps_partial_file_after_bounded_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    failed_batch_calls = []
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 1})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 2})
        if params.get("returnIdsOnly"): return _make_mock_response(json_data={"objectIds": [1, 2]})
        if params.get("objectIds"):
            failed_batch_calls.append(params["objectIds"])
            raise ugs.UrlGisError("temporary network timeout")
        return _make_mock_response(json_data={"objectIds": [1, 2]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="full")
    assert result["completeness"] == "partial"
    assert result["feature_count"] == 0
    assert "重试耗尽" in result["completeness_reason"]
    assert len(failed_batch_calls) == 2
    assert os.path.exists(result["file_path"])


def test_arcgis_layer_crs_uses_source_spatial_reference_fallback():
    info = ugs._parse_arcgis_json_metadata("https://example.test/FeatureServer/0", {
        "name": "states", "geometryType": "esriGeometryPolygon", "spatialReference": None,
        "sourceSpatialReference": {"wkid": 4326, "latestWkid": 4326}, "fields": []
    })
    assert info["crs"] == "EPSG:4326"


def test_arcgis_preview_is_never_reported_as_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    def response_for(_url, params=None, **_kwargs):
        if "f=pjson" in _url or (params or {}).get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 100})
        return _make_mock_response(json_data={"features": [{"type": "Feature", "geometry": None,
                                                               "properties": {"OID": 1}}]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="preview", limit=1)
    assert result["completeness"] == "not_checked"
    assert result["expected_count_known"] is False


def test_arcgis_full_fetch_uses_stable_offset_pagination_when_ids_are_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    metadata = {"objectIdField": "OID", "maxRecordCount": 2,
                "advancedQueryCapabilities": {"supportsPagination": True}}
    def feature(i):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [i, i]},
                "properties": {"OID": i}}
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data=metadata)
        if params.get("returnIdsOnly"): return _make_mock_response(json_data={"objectIds": [1, 2]})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 3})
        offset = int(params["resultOffset"])
        if params.get("f") == "json":
            rows = [feature(1), feature(2)] if offset == 0 else [feature(3)]
            return _make_mock_response(json_data={"features": [{"attributes": row["properties"]} for row in rows],
                                                  "exceededTransferLimit": offset == 0})
        rows = [feature(1), feature(2)] if offset == 0 else [feature(3)]
        return _make_mock_response(json_data={"features": rows, "exceededTransferLimit": offset == 0})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")
    assert result["completeness"] == "complete"
    assert result["expected_count"] == result["feature_count"] == 3
    assert any(check["name"] == "stable_pagination" and check["status"] == "passed" for check in result["checks"])


def test_arcgis_full_fetch_returns_unknown_when_no_safe_pagination_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    with patch("backend.services.url_gis_service._http_get", return_value=_make_mock_response(json_data={"fields": []})):
        with pytest.raises(ugs.UrlGisError, match="完整性未知"):
            ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="full")


def test_arcgis_full_fetch_refuses_to_trust_ids_without_independent_count(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 10})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"error": {"message": "unsupported"}})
        return _make_mock_response(json_data={"objectIds": [1]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        with pytest.raises(ugs.UrlGisError, match="完整性未知"):
            ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="full")


def test_arcgis_full_fetch_marks_changed_source_ids_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    calls = {"ids": 0}
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 10})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 2})
        if params.get("returnIdsOnly"):
            calls["ids"] += 1
            return _make_mock_response(json_data={"objectIds": [1, 2] if calls["ids"] == 1 else [1, 3]})
        return _make_mock_response(json_data={"features": [
            {"type": "Feature", "geometry": None, "properties": {"OID": i}} for i in (1, 2)
        ]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")
    assert result["completeness"] == "partial"
    assert "期间" in result["completeness_reason"]


def test_arcgis_full_fetch_preserves_multipart_polygon_holes(tmp_path, monkeypatch):
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    layer_url = "https://example.test/FeatureServer/0"
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    geometry = {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]],
        [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]],
    ]}
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson": return _make_mock_response(json_data={"objectIdField": "OID", "maxRecordCount": 10})
        if params.get("returnCountOnly"): return _make_mock_response(json_data={"count": 1})
        if params.get("returnIdsOnly"): return _make_mock_response(json_data={"objectIds": [1]})
        return _make_mock_response(json_data={"features": [{"type": "Feature", "geometry": geometry, "properties": {"OID": 1}}]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url(layer_url, mode="full")
    exported = json.loads(open(result["file_path"], encoding="utf-8").read())
    output_geometry = exported["features"][0]["geometry"]
    assert output_geometry["type"] == "MultiPolygon"
    assert len(output_geometry["coordinates"]) == 2
    assert len(output_geometry["coordinates"][0]) == 2


def test_arcgis_esrijson_polygon_conversion_preserves_parts_and_holes():
    from shapely.geometry import shape
    rings = [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]],
        [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]],
    ]
    result = shape(ugs._arcgis_json_geometry({"rings": rings}))
    assert result.geom_type == "MultiPolygon"
    assert len(result.geoms) == 2
    assert len(result.geoms[0].interiors) == 1


def test_arcgis_fetch_falls_back_to_esrijson_without_losing_geometry(tmp_path, monkeypatch):
    from shapely.geometry import shape
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "ArcGIS_REST_Layer", "layer_id": 0})
    rings = [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]],
        [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]],
    ]
    def response_for(_url, params=None, **_kwargs):
        params = params or {}
        if params.get("f") == "pjson":
            return _make_mock_response(json_data={"objectIdField": "OID", "sourceSpatialReference": {"wkid": 4326, "latestWkid": 4326}})
        if params.get("f") == "geojson":
            return _make_mock_response(json_data={"error": {"message": "GeoJSON format unsupported"}})
        return _make_mock_response(json_data={"features": [{"geometry": {"rings": rings}, "attributes": {"OID": 1, "name": "area"}}]})
    with patch("backend.services.url_gis_service._http_get", side_effect=response_for):
        result = ugs.fetch_gis_data_url("https://example.test/FeatureServer/0", mode="preview")
    exported = json.loads(open(result["file_path"], encoding="utf-8").read())
    geometry = shape(exported["features"][0]["geometry"])
    assert geometry.geom_type == "MultiPolygon"
    assert len(geometry.geoms[0].interiors) == 1


def test_fetch_geojson_rejects_unknown_crs_instead_of_guessing(tmp_path, monkeypatch):
    import geopandas as gpd
    from shapely.geometry import Point
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "GeoJSON"})
    response = _make_mock_response(content_bytes=b"unknown CRS fixture")
    unknown = gpd.GeoDataFrame({"geometry": [Point(1, 2)]}, geometry="geometry")
    with patch("backend.services.url_gis_service._http_get", return_value=response), \
            patch("geopandas.read_file", return_value=unknown):
        with pytest.raises(ugs.UrlGisError, match="未提供可确认的坐标系"):
            ugs.fetch_gis_data_url("https://example.test/data.geojson")


@pytest.mark.parametrize("member", ["../escape.shp", r"..\escape.shp", "C:/escape.shp", "/escape.shp"])
def test_inspect_remote_shapefile_zip_rejects_unsafe_member_paths(tmp_path, monkeypatch, member):
    extract_dir = tmp_path / "inspect-extract"
    extract_dir.mkdir()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("safe.shp", b"safe")
        archive.writestr(member, b"unsafe")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_kwargs: str(extract_dir))
    response = _make_mock_response(content_bytes=archive_bytes.getvalue())

    with patch("backend.services.url_gis_service._http_get", return_value=response):
        with pytest.raises(ugs.UrlGisError, match="不安全的文件路径"):
            ugs._inspect_zip_shapefile("https://example.com/data.zip")

    assert not (extract_dir / "safe.shp").exists()
    assert not (tmp_path / "escape.shp").exists()


def test_safe_extract_remote_shapefile_zip_accepts_relative_members(tmp_path):
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("roads.shp", b"safe shapefile data")

    with zipfile.ZipFile(io.BytesIO(archive_bytes.getvalue())) as archive:
        ugs._safe_extract_zip(archive, str(tmp_path))

    assert (tmp_path / "roads.shp").read_bytes() == b"safe shapefile data"


def test_safe_extract_remote_shapefile_zip_rejects_expansion_over_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(ugs, "_ZIP_MAX_UNCOMPRESSED_BYTES", 5)
    archive = MagicMock()
    archive.infolist.return_value = [MagicMock(filename="large.shp", file_size=6)]

    with pytest.raises(ugs.UrlGisError, match="ZIP 压缩包解压后超过"):
        ugs._safe_extract_zip(archive, str(tmp_path))
    archive.extractall.assert_not_called()


def test_safe_extract_remote_shapefile_zip_rejects_too_many_members(monkeypatch, tmp_path):
    monkeypatch.setattr(ugs, "_ZIP_MAX_MEMBERS", 1)
    archive = MagicMock()
    archive.infolist.return_value = [
        MagicMock(filename="one.shp", file_size=1),
        MagicMock(filename="two.shx", file_size=1),
    ]

    with pytest.raises(ugs.UrlGisError, match="ZIP 压缩包文件数量超过限制"):
        ugs._safe_extract_zip(archive, str(tmp_path))
    archive.extractall.assert_not_called()


def test_fetch_remote_shapefile_zip_rejects_unsafe_member_paths(tmp_path, monkeypatch):
    extract_dir = tmp_path / "fetch-extract"
    extract_dir.mkdir()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("safe.shp", b"safe")
        archive.writestr("../escape.shp", b"unsafe")
    monkeypatch.setattr(ugs, "inspect_gis_url", lambda _url: {"service_type": "Shapefile_ZIP"})
    monkeypatch.setattr(ugs, "_get_output_dir", lambda: str(tmp_path / "downloads"))
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_kwargs: str(extract_dir))
    response = _make_mock_response(content_bytes=archive_bytes.getvalue())

    with patch("backend.services.url_gis_service._http_get", return_value=response):
        with pytest.raises(ugs.UrlGisError, match="不安全的文件路径"):
            ugs.fetch_gis_data_url("https://example.com/data.zip")

    assert not (extract_dir / "safe.shp").exists()
    assert not (tmp_path / "escape.shp").exists()
