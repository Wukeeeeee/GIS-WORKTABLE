import urllib.error
import urllib.parse
import urllib.request
import logging
from uvicorn.logging import AccessFormatter

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.main import app
from backend.services import model_transport
from backend.services import url_security


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [("network", 502), ("http", 403)],
)
def test_geosource_proxy_errors_do_not_echo_sensitive_url_parts(
    monkeypatch, failure, expected_status
):
    url = "https://example.test/private/path?token=URL_TOKEN_SENTINEL"

    class FailingOpener:
        def open(self, request, timeout):
            assert timeout == 12
            if failure == "http":
                raise urllib.error.HTTPError(
                    request.full_url, 403, f"denied {request.full_url}", None, None
                )
            raise urllib.error.URLError(f"connection failed for {request.full_url}")

    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )
    def build_opener(*handlers, **_kwargs):
        redirect_handlers = [h for h in handlers if isinstance(h, main._GeoSourceRedirectHandler)]
        assert len(redirect_handlers) == 1
        assert redirect_handlers[0].protect_public_target
        return FailingOpener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)

    response = TestClient(app).get("/api/geosource/proxy", params={"url": url})

    assert response.status_code == expected_status
    body = response.text
    assert "URL_PASSWORD_SENTINEL" not in body
    assert "URL_TOKEN_SENTINEL" not in body
    assert "/private/path" not in body
    assert "user:" not in body


@pytest.mark.parametrize(
    ("base_url", "origin"),
    [
        ("http://testserver", "https://attacker.example"),
        ("http://attacker.example", "http://attacker.example"),
    ],
)
def test_geosource_proxy_rejects_cross_site_and_rebound_hosts(
    monkeypatch, base_url, origin
):
    def unexpected_proxy_lookup(_url):
        pytest.fail("cross-site requests must be rejected before outbound access")

    monkeypatch.setattr(model_transport, "effective_model_proxy", unexpected_proxy_lookup)

    response = TestClient(app, base_url=base_url).get(
        "/api/geosource/proxy",
        params={"url": "https://example.test/data.geojson"},
        headers={"Origin": origin},
    )

    assert response.status_code == 403
    assert "跨站" in response.json()["detail"]


def test_geosource_proxy_rejects_cross_site_fetch_without_origin(monkeypatch):
    def unexpected_proxy_lookup(_url):
        pytest.fail("cross-site requests must be rejected before outbound access")

    monkeypatch.setattr(model_transport, "effective_model_proxy", unexpected_proxy_lookup)

    response = TestClient(app).get(
        "/api/geosource/proxy",
        params={"url": "https://example.test/data.geojson"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
    assert "跨站" in response.json()["detail"]


@pytest.mark.parametrize(
    ("content_length", "expected_read_limit"),
    [("9", None), (None, 9)],
)
def test_geosource_proxy_caps_large_responses(
    monkeypatch, content_length, expected_read_limit
):
    monkeypatch.setattr(main, "_GEOSOURCE_PROXY_MAX_BYTES", 8)
    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )

    class OversizedResponse:
        headers = {"Content-Type": "application/json"}
        read_limit = None

        def __init__(self):
            if content_length is not None:
                self.headers["Content-Length"] = content_length

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            self.read_limit = limit
            return b"x" * limit

    response_body = OversizedResponse()
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *args, **kwargs: type("Opener", (), {"open": lambda self, request, timeout: response_body})(),
    )

    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/api/geosource/proxy",
        json={"url": "https://example.test/data.geojson"},
        headers={"Origin": "http://localhost:8003"},
    )

    assert response.status_code == 413
    assert response_body.read_limit == expected_read_limit


def test_geosource_proxy_sandboxes_provider_controlled_document_responses(monkeypatch):
    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )

    class ProviderResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b"<script>fetch('/api/user-settings')</script>"

    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *args, **kwargs: type("Opener", (), {"open": lambda self, request, timeout: ProviderResponse()})(),
    )

    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/api/geosource/proxy",
        json={"url": "https://provider.example/response"},
        headers={"Origin": "http://localhost:8003"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "sandbox" in response.headers["content-security-policy"]
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_geosource_tile_proxy_forwards_wms_parameters_and_returns_binary(monkeypatch):
    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )
    captured = {}

    class ImageResponse:
        headers = {"Content-Type": "image/png"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            captured["read_limit"] = limit
            return b"\x89PNG\r\n\x1a\n"

    class Opener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["accept"] = request.get_header("Accept")
            assert timeout == 12
            return ImageResponse()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args, **kwargs: Opener())
    response = TestClient(app, base_url="http://127.0.0.1").get(
        "/api/geosource/proxy",
        params={
            "_geosource_tile": "1",
            "_geosource_auth_parameter": "token",
            "url": "https://example.test/wms?token=KEY_SENTINEL&layers=old",
            "service": "WMS",
            "request": "GetMap",
            "layers": "roads",
            "bbox": "1,2,3,4",
        },
        headers={"Origin": "http://localhost:8003"},
    )

    forwarded = urllib.parse.parse_qs(urllib.parse.urlsplit(captured["url"]).query)
    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n\x1a\n"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert captured["accept"] == "*/*"
    assert captured["read_limit"] == main._GEOSOURCE_TILE_MAX_BYTES + 1
    assert forwarded == {
        "token": ["KEY_SENTINEL"], "service": ["WMS"], "request": ["GetMap"],
        "layers": ["roads"], "bbox": ["1,2,3,4"],
    }
    assert "_geosource_tile" not in forwarded
    assert "_geosource_auth_parameter" not in forwarded


def test_geosource_proxy_passes_manual_auth_parameter_to_redirect_guard(monkeypatch):
    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)
    captured = {}

    class Response:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"type":"FeatureCollection","features":[]}'

    class Opener:
        def open(self, _request, timeout):
            captured["timeout"] = timeout
            return Response()

    def opener_factory(proxy_handler, initial_url, **options):
        captured.update(options)
        captured["initial_url"] = initial_url
        return Opener()

    monkeypatch.setattr(main, "safe_redirect_opener", opener_factory)
    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/api/geosource/proxy",
        json={"url": "https://provider.example/data?code=KEY_SENTINEL", "auth_parameter": "code"},
        headers={"Origin": "http://localhost:8003"},
    )

    assert response.status_code == 200
    assert captured["credential_parameters"] == ["code"]
    assert captured["strip_sensitive_query"] is True
    assert captured["require_https_for_credentials"] == {"code"}
    assert captured["reject_authenticated_cross_origin"] is True
    assert captured["initial_url"] == "https://provider.example/data?code=KEY_SENTINEL"


@pytest.mark.parametrize("classification", [True, None])
def test_geo_source_proxy_rejects_credentials_over_public_or_unknown_http(monkeypatch, classification):
    monkeypatch.setattr(main, "_is_public_http_target", lambda _url: classification)
    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)
    monkeypatch.setattr(
        main, "safe_redirect_opener",
        lambda *_args, **_kwargs: pytest.fail("insecure credential request must not open"),
    )

    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/api/geosource/proxy",
        json={"url": "http://provider.example/data?code=KEY_SENTINEL", "auth_parameter": "code"},
        headers={"Origin": "http://localhost:8003"},
    )

    assert response.status_code == 400
    assert "必须使用 HTTPS" in response.json()["detail"]


def test_geo_source_proxy_allows_credentials_over_explicit_private_http(monkeypatch):
    monkeypatch.setattr(main, "_is_public_http_target", lambda _url: False)
    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)

    class Response:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"type":"FeatureCollection","features":[]}'

    class Opener:
        def open(self, _request, timeout):
            assert timeout == 12
            return Response()

    monkeypatch.setattr(main, "safe_redirect_opener", lambda *_args, **_kwargs: Opener())
    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/api/geosource/proxy",
        json={"url": "http://private.example/data?code=KEY_SENTINEL", "auth_parameter": "code"},
        headers={"Origin": "http://localhost:8003"},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "url",
    [
        "https://user:URL_PASSWORD_SENTINEL@provider.example/data.geojson",
        "http://user@provider.example/data.geojson",
        "https://:password@provider.example/data.geojson",
    ],
)
def test_geo_source_proxy_rejects_initial_url_userinfo(monkeypatch, url):
    monkeypatch.setattr(
        main, "safe_redirect_opener",
        lambda *_args, **_kwargs: pytest.fail("userinfo URL must be rejected before opening"),
    )
    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/api/geosource/proxy",
        json={"url": url},
        headers={"Origin": "http://localhost:8003"},
    )

    assert response.status_code == 400
    assert "不支持地址中嵌入用户名或密码" in response.json()["detail"]
    assert "password" not in response.text
    assert "URL_PASSWORD_SENTINEL" not in response.text


def test_shared_geo_source_opener_rejects_public_http_credentials_at_connect(monkeypatch):
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )
    opener = url_security.safe_redirect_opener(
        urllib.request.ProxyHandler({}),
        "http://provider.example/data?code=KEY_SENTINEL",
        credential_parameters=["code"],
        require_https_for_credentials={"code"},
    )

    with pytest.raises(urllib.error.URLError) as exc:
        opener.open("http://provider.example/data?code=KEY_SENTINEL", timeout=1)

    assert "KEY_SENTINEL" not in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/data?token=KEY_SENTINEL",
        "http://user:PASS_SENTINEL@provider.example/data",
    ],
)
def test_shared_opener_blocks_any_public_http_url_credentials_at_connect(monkeypatch, url):
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )
    opener = url_security.safe_redirect_opener(urllib.request.ProxyHandler({}), url)

    with pytest.raises(urllib.error.URLError) as exc:
        opener.open(url, timeout=1)

    assert "KEY_SENTINEL" not in str(exc.value)
    assert "PASS_SENTINEL" not in str(exc.value)


def test_shared_opener_strips_sensitive_query_on_cross_origin_redirect_by_default(monkeypatch):
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )
    opener = url_security.safe_redirect_opener(
        urllib.request.ProxyHandler({}),
        "https://source.example/data?token=KEY_SENTINEL&format=tif",
    )
    handler = next(
        item for item in opener.handlers
        if isinstance(item, url_security.SafeHTTPRedirectHandler)
    )
    source = urllib.request.Request("https://source.example/data?token=KEY_SENTINEL&format=tif")

    same_origin = handler.redirect_request(
        source, None, 302, "Found", {}, "https://source.example/cdn?token=KEY_SENTINEL&format=tif"
    )
    cross_origin = handler.redirect_request(
        source, None, 302, "Found", {}, "https://cdn.example/data?token=KEY_SENTINEL&format=tif"
    )

    assert "token=KEY_SENTINEL" in same_origin.full_url
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(cross_origin.full_url).query) == {"format": ["tif"]}
    assert handler.credentials_stripped is True


def test_geo_source_proxy_explains_auth_stripping_when_redirect_target_rejects_request(monkeypatch):
    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)
    guard = main._GeoSourceRedirectHandler(protect_public_target=True, credential_parameters={"code"})
    guard.credentials_stripped = True

    class Opener:
        handlers = [guard]

        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(main, "safe_redirect_opener", lambda *_args, **_kwargs: Opener())
    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/api/geosource/proxy",
        json={"url": "https://provider.example/data?code=KEY_SENTINEL", "auth_parameter": "code"},
        headers={"Origin": "http://localhost:8003"},
    )

    assert response.status_code == 502
    assert "没有把认证参数转发到新主机" in response.json()["detail"]
    assert "KEY_SENTINEL" not in response.text


def test_cross_origin_redirect_strips_only_manual_credential_parameter(monkeypatch):
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )
    handler = main._GeoSourceRedirectHandler(
        protect_public_target=True, credential_parameters={"code"}
    )
    request = urllib.request.Request("https://provider.example/data?code=KEY_SENTINEL&layers=roads")

    redirected = handler.redirect_request(
        request, None, 302, "Found", {},
        "https://cdn.example/data?code=KEY_SENTINEL&layers=roads&signature=cdn-signature",
    )
    same_origin = handler.redirect_request(
        request, None, 302, "Found", {},
        "https://provider.example/next?code=KEY_SENTINEL&layers=roads",
    )

    assert urllib.parse.parse_qs(urllib.parse.urlsplit(redirected.full_url).query) == {
        "layers": ["roads"], "signature": ["cdn-signature"],
    }
    assert handler.credentials_stripped is True
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(same_origin.full_url).query) == {
        "code": ["KEY_SENTINEL"], "layers": ["roads"],
    }


def test_geo_source_blocks_authenticated_cross_origin_redirect(monkeypatch):
    monkeypatch.setattr(
        url_security.socket,
        "getaddrinfo",
        lambda _host, port, type: [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))],
    )
    opener = url_security.safe_redirect_opener(
        urllib.request.ProxyHandler({}),
        "https://provider.example/data?code=KEY_SENTINEL",
        credential_parameters=["code"],
        reject_authenticated_cross_origin=True,
    )
    handler = next(h for h in opener.handlers if isinstance(h, main._GeoSourceRedirectHandler))
    request = urllib.request.Request("https://provider.example/data?code=KEY_SENTINEL")

    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(
            request, None, 302, "Found", {},
            "https://cdn.example/data?code=KEY_SENTINEL",
        )

    assert exc.value.code == 403
    assert handler.authenticated_redirect_blocked is True
    assert handler.credentials_stripped is False
    assert "KEY_SENTINEL" not in str(exc.value)


def test_geosource_proxy_access_log_redacts_legacy_target_query():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:12345",
            "GET",
            "/api/geosource/proxy?url=https%3A%2F%2Fexample.test%2F%3Ftoken%3BLOG_TOKEN_SENTINEL",
            "1.1",
            200,
        ),
        None,
    )

    assert main._GeoSourceProxyAccessLogRedactor().filter(record)
    message = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record)
    assert "LOG_TOKEN_SENTINEL" not in message
    assert "/api/geosource/proxy" in message


def test_public_geo_source_redirect_cannot_enter_private_network(monkeypatch):
    def resolve(host, port, type):
        address = "93.184.216.34" if host == "public.example" else "10.12.0.8"
        return [(url_security.socket.AF_INET, type, 6, "", (address, port))]

    monkeypatch.setattr(url_security.socket, "getaddrinfo", resolve)
    handler = main._GeoSourceRedirectHandler(protect_public_target=True)
    request = urllib.request.Request("https://public.example/catalog")

    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(
            request, None, 302, "Found", {}, "http://private.example/admin"
        )

    assert exc.value.code == 403
    assert "private.example" not in str(exc.value)


def test_public_geo_source_redirect_cannot_enter_loopback(monkeypatch):
    def resolve(host, port, type):
        address = "93.184.216.34" if host == "public.example" else "127.0.0.1"
        return [(url_security.socket.AF_INET, type, 6, "", (address, port))]

    monkeypatch.setattr(url_security.socket, "getaddrinfo", resolve)
    handler = main._GeoSourceRedirectHandler(protect_public_target=True)
    request = urllib.request.Request("https://public.example/catalog")

    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(request, None, 302, "Found", {}, "http://localhost:8000/api/health")

    assert exc.value.code == 403


def test_public_geo_source_redirect_allows_public_and_blocks_unknown(monkeypatch):
    def resolve(host, port, type):
        if host == "unknown.example":
            raise OSError("name resolution failed")
        return [(url_security.socket.AF_INET, type, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(url_security.socket, "getaddrinfo", resolve)
    handler = main._GeoSourceRedirectHandler(protect_public_target=True)
    request = urllib.request.Request("https://public.example/catalog")

    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "https://cdn.example/data.geojson"
    )
    assert redirected.full_url == "https://cdn.example/data.geojson"

    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(
            request, None, 302, "Found", {}, "https://unknown.example/data.geojson"
        )
    assert exc.value.code == 403


def test_explicit_private_geo_source_keeps_private_redirects(monkeypatch):
    assert main._is_public_http_target("http://10.0.0.5/catalog") is False
    handler = main._GeoSourceRedirectHandler(protect_public_target=False)
    request = urllib.request.Request("http://10.0.0.5/catalog")

    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "http://10.0.0.8/geoserver/wms"
    )

    assert redirected.full_url == "http://10.0.0.8/geoserver/wms"


def test_private_geo_source_redirect_chain_cannot_return_private_after_public(monkeypatch):
    def resolve(host, port, type):
        address = {
            "private.example": "10.12.0.8",
            "public.example": "93.184.216.34",
            "other-private.example": "10.12.0.9",
        }[host]
        return [(url_security.socket.AF_INET, type, 6, "", (address, port))]

    monkeypatch.setattr(url_security.socket, "getaddrinfo", resolve)
    opener = url_security.safe_redirect_opener(
        urllib.request.ProxyHandler({}), "http://private.example/catalog"
    )
    handler = next(
        item for item in opener.handlers
        if isinstance(item, url_security.SafeHTTPRedirectHandler)
    )
    private_request = urllib.request.Request("http://private.example/catalog")
    public_request = handler.redirect_request(
        private_request, None, 302, "Found", {}, "https://public.example/data"
    )

    assert public_request.full_url == "https://public.example/data"
    assert handler.protect_public_target is True

    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(
            public_request, None, 302, "Found", {}, "http://other-private.example/admin"
        )
    assert exc.value.code == 403


def test_private_geo_source_redirect_to_ambiguous_host_enables_protection(monkeypatch):
    def resolve(host, port, type):
        addresses = {
            "private.example": ["10.12.0.8"],
            "mixed.example": ["93.184.216.34", "10.12.0.9"],
            "other-private.example": ["10.12.0.10"],
        }[host]
        return [
            (url_security.socket.AF_INET, type, 6, "", (address, port))
            for address in addresses
        ]

    monkeypatch.setattr(url_security.socket, "getaddrinfo", resolve)
    opener = url_security.safe_redirect_opener(
        urllib.request.ProxyHandler({}), "http://private.example/catalog"
    )
    handler = next(
        item for item in opener.handlers
        if isinstance(item, url_security.SafeHTTPRedirectHandler)
    )
    private_request = urllib.request.Request("http://private.example/catalog")
    mixed_request = handler.redirect_request(
        private_request, None, 302, "Found", {}, "http://mixed.example/data"
    )

    assert mixed_request.full_url == "http://mixed.example/data"
    assert handler.protect_public_target is True

    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(
            mixed_request, None, 302, "Found", {}, "http://other-private.example/admin"
        )
    assert exc.value.code == 403


@pytest.mark.parametrize(
    "target_url",
    ["file:///etc/passwd", "ftp://public.example/data", "http://user:pass@public.example/data"],
)
def test_redirect_guard_rejects_non_http_and_userinfo_targets(target_url):
    handler = main._GeoSourceRedirectHandler(protect_public_target=False)
    request = urllib.request.Request("http://10.0.0.5/catalog")

    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(request, None, 302, "Found", {}, target_url)

    assert exc.value.code == 403
