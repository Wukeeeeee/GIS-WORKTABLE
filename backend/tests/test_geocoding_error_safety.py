import requests
import pytest

from backend.services import tools


def _raise_key_bearing_connection_error(*args, **kwargs):
    raise requests.ConnectionError(
        "request failed: https://restapi.amap.com/v3/geocode/regeo?key=TEST_KEY_MUST_NOT_LEAK"
    )


def test_reverse_geocode_does_not_return_key_bearing_request_exception(monkeypatch):
    monkeypatch.setattr(tools, "_current_amap_key", "TEST_KEY_MUST_NOT_LEAK")
    monkeypatch.setattr(requests, "get", _raise_key_bearing_connection_error)

    result = tools.reverse_geocode.invoke({"lng": 113.26, "lat": 23.13})

    assert "TEST_KEY_MUST_NOT_LEAK" not in result
    assert "ConnectionError" in result


def test_batch_geocode_does_not_return_key_bearing_request_exception(monkeypatch):
    monkeypatch.setattr(tools, "_current_amap_key", "TEST_KEY_MUST_NOT_LEAK")
    monkeypatch.setattr(requests, "get", _raise_key_bearing_connection_error)

    result = tools.batch_geocode.invoke({"addresses": "广州塔"})

    assert "TEST_KEY_MUST_NOT_LEAK" not in result
    assert "ConnectionError" in result


def test_batch_geocode_rejects_more_than_twenty_addresses_before_request(monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "_current_amap_key", "test-key")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)))
    addresses = ";".join(f"address-{index}" for index in range(21))

    result = tools.batch_geocode.invoke({"addresses": addresses})

    assert "最多查询 20 个地址" in result
    assert calls == []


@pytest.mark.parametrize(
    ("lng", "lat"),
    [(181, 0), (-181, 0), (0, 91), (0, -91), (float("nan"), 0), (0, float("inf"))],
)
def test_reverse_geocode_rejects_invalid_wgs84_coordinates_before_request(monkeypatch, lng, lat):
    calls = []
    monkeypatch.setattr(tools, "_current_amap_key", "TEST_KEY_MUST_NOT_LEAK")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = tools.reverse_geocode.invoke({"lng": lng, "lat": lat})

    assert "坐标无效" in result
    assert calls == []
