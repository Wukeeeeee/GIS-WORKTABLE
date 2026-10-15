# -*- coding: utf-8 -*-
"""metro_line 工具测试：国内链路结构/数值断言"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _inv(city, line=""):
    from backend.services import tools as T
    return T.metro_line.invoke({"city": city, "line": line})


def test_changsha_line1_structure():
    """长沙 1 号线：25 站、起讫站、WGS-84 坐标落在长沙范围"""
    from backend.services import tools as T
    r = _inv("长沙", "1号线")
    assert "1号线" in r and "25 站" in r, r
    assert "已上图" in r
    pts = T._registered_layers["长沙地铁站点"]["geojson"]["features"]
    assert len(pts) == 25
    for f in pts:
        lon, lat = f["geometry"]["coordinates"]
        assert 112 < lon < 114 and 27.5 < lat < 29, (lon, lat)
    names = [f["properties"]["name"] for f in pts]
    assert names[0].startswith("金盆丘") and names[-1] == "尚双塘"


def test_changsha_line_color():
    from backend.services import tools as T
    _inv("长沙", "1号线")
    feat = T._registered_layers["长沙地铁1号线"]["geojson"]["features"][0]
    assert feat["properties"]["color"] == "#d02129"


def test_full_network():
    from backend.services import tools as T
    r = _inv("长沙")
    assert "7 条线" in r and "170 站" in r, r[:200]
    line_layers = [n for n in T._registered_layers if n.startswith("长沙地铁") and "站点" not in n]
    assert len(line_layers) == 7


def test_unsupported_city_clear_error():
    r = _inv("亚特兰蒂斯")
    assert "暂不支持" in r or "失败" in r, r


def test_registered_in_registry():
    from backend.services.tools import tools
    assert "metro_line" in {t.name for t in tools}


def test_line_matches_uses_exact_line_number():
    """「1号线」只能命中 1 号线，不能再子串命中 11/21 号线。"""
    from backend.services.metro_service import line_matches

    assert line_matches("1号线", "1号线") is True
    assert line_matches("11号线", "1号线") is False
    assert line_matches("21号线", "1号线") is False
    assert line_matches("广州地铁1号线", "1") is True
    assert line_matches("1号线", "1") is True
    assert line_matches("APM线", "APM") is True
    assert line_matches("1号线", "") is True
    assert line_matches("", "1号线") is False


def test_guangzhou_line1_alone():
    """用户问「广州地铁1号线」：只应有 1 号线，不该混进 11/21 号线。"""
    from backend.services import tools as T

    r = _inv("广州", "1号线")
    assert "广州地铁1号线" in r, r
    assert "11号线" not in r and "21号线" not in r, r
    lines = [n for n in T._registered_layers if n.startswith("广州地铁") and "站点" not in n]
    assert lines == ["广州地铁1号线"], lines
    stations = T._registered_layers["广州地铁站点"]["geojson"]["features"]
    assert len(stations) == 16, len(stations)