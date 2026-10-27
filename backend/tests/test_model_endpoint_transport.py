import asyncio

import pytest
from fastapi import HTTPException

from backend import main
from backend.services import url_security
from backend.services.llm_config import LLMConfig, model_endpoint_transport_error


def _config(base_url):
    return LLMConfig(base_url=base_url, model="mock", api_key="sentinel-key")


def test_model_endpoint_transport_requires_https_for_public_or_unknown_http(monkeypatch):
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: True)
    assert "HTTPS" in model_endpoint_transport_error(_config("http://api.example.test/v1"))

    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: None)
    assert "HTTPS" in model_endpoint_transport_error(_config("http://unknown.example.test/v1"))


def test_model_endpoint_transport_allows_https_and_explicit_private_http(monkeypatch):
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: pytest.fail("must not resolve HTTPS"))
    assert model_endpoint_transport_error(_config("https://api.example.test/v1")) is None

    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: False)
    assert model_endpoint_transport_error(_config("http://10.0.0.5:11434/v1")) is None


@pytest.mark.parametrize("route", [main.chat, main.chat_stream])
def test_chat_routes_reject_public_http_before_model_call(monkeypatch, route):
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: True)
    monkeypatch.setattr(main, "chat_with_ai", lambda **_kwargs: pytest.fail("model must not be called"))
    request = main.ChatRequest(message="test", llm_config=_config("http://api.example.test/v1"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route(request))

    assert exc.value.status_code == 400
    assert "HTTPS" in exc.value.detail


def test_connection_test_reports_public_http_policy_without_calling_provider(monkeypatch):
    monkeypatch.setattr(url_security, "is_public_http_target", lambda _url: True)
    monkeypatch.setattr(main, "test_key", lambda _cfg: pytest.fail("provider must not be called"))
    request = main.TestKeyRequest(llm_config=_config("http://api.example.test/v1"))

    result = asyncio.run(main.test_key_endpoint(request))

    assert result["success"] is False
    assert "HTTPS" in result["message"]
