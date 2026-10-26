import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import model_transport


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [("network", 502), ("http", 403)],
)
def test_geosource_proxy_errors_do_not_echo_sensitive_url_parts(
    monkeypatch, failure, expected_status
):
    url = "https://user:URL_PASSWORD_SENTINEL@example.test/private/path?token=URL_TOKEN_SENTINEL"

    class FailingOpener:
        def open(self, request, timeout):
            assert timeout == 12
            if failure == "http":
                raise urllib.error.HTTPError(
                    request.full_url, 403, f"denied {request.full_url}", None, None
                )
            raise urllib.error.URLError(f"connection failed for {request.full_url}")

    monkeypatch.setattr(model_transport, "effective_model_proxy", lambda _url: None)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args, **kwargs: FailingOpener())

    response = TestClient(app).get("/api/geosource/proxy", params={"url": url})

    assert response.status_code == expected_status
    body = response.text
    assert "URL_PASSWORD_SENTINEL" not in body
    assert "URL_TOKEN_SENTINEL" not in body
    assert "/private/path" not in body
    assert "user:" not in body
