from backend.services import tools


def test_geocode_without_api_key_is_classified_as_failure(monkeypatch):
    monkeypatch.setattr(tools, "_current_amap_key", "")

    result = tools.amap_geocode.invoke({"address": "广州塔"})

    assert "高德 API Key 未配置" in result
    assert tools._tool_result_failed("amap_geocode", result)


def test_geocode_no_match_is_classified_as_failure(monkeypatch):
    import requests

    class EmptyResponse:
        def json(self):
            return {"status": "1", "geocodes": []}

    monkeypatch.setattr(tools, "_current_amap_key", "test-key")
    monkeypatch.setattr(tools, "_geocode_cache", {})
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: EmptyResponse())

    result = tools.amap_geocode.invoke({"address": "不存在的地点"})

    assert "未找到" in result
    assert tools._tool_result_failed("amap_geocode", result)
