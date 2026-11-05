from backend.services import datav_service as datav


def test_find_adcode_prefers_exact_city_over_province_substring(monkeypatch):
    monkeypatch.setattr(datav, "_load_city_adcodes", lambda: {"吉林市": 220200})

    assert datav._find_adcode("吉林市") == 220200
    assert datav._find_adcode("吉林省") == 220000


def test_find_adcode_does_not_guess_province_for_unknown_city(monkeypatch):
    monkeypatch.setattr(datav, "_load_city_adcodes", lambda: {"吉林市": 220200})

    assert datav._find_adcode("吉林新区市") == 0
