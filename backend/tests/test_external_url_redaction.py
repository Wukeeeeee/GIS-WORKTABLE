import sys
import types
from types import SimpleNamespace

from backend.services import tools


def test_web_fetch_failure_redacts_url_credentials_and_query_from_logs_and_error(monkeypatch, capsys):
    url = "https://user:PASS_SHOULD_NOT_LEAK@example.com/private/path?token=URL_SECRET_SHOULD_NOT_LEAK"
    fetchers = types.ModuleType("scrapling.fetchers")
    def unavailable(*args, **kwargs):
        raise ImportError("simulated optional fetcher unavailable")
    fetchers.Fetcher = SimpleNamespace(get=unavailable)
    scrapling = types.ModuleType("scrapling")
    scrapling.__path__ = []
    monkeypatch.setitem(sys.modules, "scrapling", scrapling)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fetchers)
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=(f"browser failed at {url}").encode(),
        ),
    )

    result = tools._fetch_webpage_impl_inner(url)
    log_output = capsys.readouterr().out

    assert "PASS_SHOULD_NOT_LEAK" not in log_output + result
    assert "URL_SECRET_SHOULD_NOT_LEAK" not in log_output + result
    assert "/private/path" not in log_output + result
    assert "目标站点未能加载" in result


def test_web_fetch_http_failure_logs_only_safe_site_label(monkeypatch, capsys):
    url = "https://user:PASS_SHOULD_NOT_LEAK@example.com/private/path?token=URL_SECRET_SHOULD_NOT_LEAK"
    fetchers = types.ModuleType("scrapling.fetchers")
    fetchers.Fetcher = SimpleNamespace(get=lambda *args, **kwargs: SimpleNamespace(status=503))
    scrapling = types.ModuleType("scrapling")
    scrapling.__path__ = []
    monkeypatch.setitem(sys.modules, "scrapling", scrapling)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fetchers)

    result = tools._fetch_webpage_impl_inner(url)
    log_output = capsys.readouterr().out

    assert result is None
    assert "https://example.com" in log_output
    assert "PASS_SHOULD_NOT_LEAK" not in log_output
    assert "URL_SECRET_SHOULD_NOT_LEAK" not in log_output
    assert "/private/path" not in log_output


def test_scrape_page_error_redacts_credentials_and_query(monkeypatch):
    import scrapling.fetchers

    url = "https://user:PASS_SHOULD_NOT_LEAK@example.com/private/path?token=URL_SECRET_SHOULD_NOT_LEAK"

    class FakeFetcher:
        @staticmethod
        def get(request_url, timeout):
            raise RuntimeError(f"failed to fetch {request_url}")

    monkeypatch.setattr(scrapling.fetchers, "Fetcher", FakeFetcher)

    result = tools.scrape_page.func(url=url, selector="body")

    assert "https://example.com" in result
    assert "RuntimeError" in result
    assert "PASS_SHOULD_NOT_LEAK" not in result
    assert "URL_SECRET_SHOULD_NOT_LEAK" not in result
    assert "/private/path" not in result
