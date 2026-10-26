"""网页抓取工具在可选反爬依赖缺失时的降级行为。"""

import builtins

from backend.services import tools as gis_tools


def _without_scrapling(monkeypatch):
    real_import = builtins.__import__

    def import_without_scrapling(name, *args, **kwargs):
        if name == "scrapling.fetchers" or name.startswith("scrapling."):
            raise ImportError("Scrapling unavailable in test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_scrapling)


def test_scrape_page_falls_back_for_body_selector(monkeypatch):
    _without_scrapling(monkeypatch)
    monkeypatch.setattr(
        gis_tools, "fetch_webpage_impl",
        lambda url, max_length=10000: "网页正文内容",
    )

    result = gis_tools.scrape_page.func(url="https://example.test", selector="body")

    assert "备用抓取" in result
    assert "网页正文内容" in result


def test_scrape_page_does_not_fake_css_selector_fallback(monkeypatch):
    _without_scrapling(monkeypatch)
    monkeypatch.setattr(
        gis_tools, "fetch_webpage_impl",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    result = gis_tools.scrape_page.func(
        url="https://example.test", selector="article.main"
    )

    assert "仅支持 selector='body'" in result


def test_scrape_and_fetch_unwrap_markdown_links(monkeypatch):
    expected = "https://example.test/page?a=1&b=2"
    markdown_url = f"[{expected}]({expected})"
    seen = []

    monkeypatch.setattr(
        gis_tools, "_fetch_webpage_impl_inner",
        lambda url, max_length: seen.append(url) or "网页正文",
    )
    monkeypatch.setattr(gis_tools, "_domain_fail", {})
    assert gis_tools.fetch_webpage_impl(markdown_url) == "网页正文"
    assert seen == [expected]

    class FakePage:
        status = 200
        html_content = "<body>正文</body>"

        def css(self, selector):
            return [type("Element", (), {"text": "正文"})()]

    class FakeFetcher:
        @staticmethod
        def get(url, timeout):
            seen.append(url)
            return FakePage()

    import scrapling.fetchers
    monkeypatch.setattr(scrapling.fetchers, "Fetcher", FakeFetcher)
    assert gis_tools.scrape_page.func(url=markdown_url) == "正文"
    assert seen == [expected, expected]


def test_fetch_webpage_reports_browser_failure_without_traceback_or_url_details(monkeypatch):
    _without_scrapling(monkeypatch)
    monkeypatch.setattr(
        gis_tools.subprocess, "run",
        lambda *args, **kwargs: type("Result", (), {
            "returncode": 1,
            "stdout": b"",
            "stderr": b'Traceback (most recent call last):\n  File "<string>", line 13\nError: net::ERR_NAME_NOT_RESOLVED',
        })(),
    )

    result = gis_tools._fetch_webpage_impl_inner(
        "https://user:password@example.test/private?token=secret-value"
    )

    assert "目标站点未能加载：https://example.test" in result
    assert "net::ERR_NAME_NOT_RESOLVED" not in result
    assert "password" not in result
    assert "secret-value" not in result
    assert "Traceback" not in result
