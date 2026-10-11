from unittest.mock import MagicMock

import pytest

from backend.services import model_transport, tools


@pytest.fixture(autouse=True)
def system_proxy(monkeypatch):
    monkeypatch.setattr(tools, 'get_proxy_config', lambda: '')
    monkeypatch.setattr(model_transport.urllib.request, 'proxy_bypass', lambda host: False)
    monkeypatch.setattr(model_transport.urllib.request, 'getproxies', lambda: {'https': 'http://127.0.0.1:7890'})


def test_dead_loopback_proxy_uses_direct_connection(monkeypatch):
    def refused(*args, **kwargs):
        raise ConnectionRefusedError()
    monkeypatch.setattr(model_transport.socket, 'create_connection', refused)
    assert model_transport.effective_model_proxy('https://api.deepseek.com') is None


def test_live_loopback_proxy_is_preserved(monkeypatch):
    monkeypatch.setattr(model_transport.socket, 'create_connection', MagicMock())
    assert model_transport.effective_model_proxy('https://api.deepseek.com') == 'http://127.0.0.1:7890'


def test_explicit_proxy_is_not_silently_bypassed(monkeypatch):
    monkeypatch.setattr(tools, 'get_proxy_config', lambda: 'http://localhost:9999')
    assert model_transport.effective_model_proxy('https://api.deepseek.com') == 'http://localhost:9999'


def test_remote_proxy_is_preserved(monkeypatch):
    monkeypatch.setattr(model_transport.urllib.request, 'getproxies', lambda: {'https': 'http://proxy.example:8080'})
    assert model_transport.effective_model_proxy('https://api.deepseek.com') == 'http://proxy.example:8080'


def test_no_proxy_is_respected(monkeypatch):
    monkeypatch.setattr(model_transport.urllib.request, 'proxy_bypass', lambda host: True)
    assert model_transport.effective_model_proxy('https://api.deepseek.com') is None
