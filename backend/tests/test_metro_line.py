# -*- coding: utf-8 -*-
"""metro_line 工具测试：固定数据验证上图链路，避免依赖实时站点数量。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(autouse=True)
def fixed_metro_data(monkeypatch):
    from backend.services import metro_service as M, tools as T

    def line(number, names, color):
        return {"ln": f"{number}号线", "cl": color, "c": ["1512 709"], "st": [
            {"n": name, "sl": f"{112.98 + i * .01},{28.10 + i * .01}",
             "su": "1", "t": str(i % 2)} for i, name in enumerate(names)
        ]}

    payload = {"l": [
        line(1, ["起点", "换乘站", "终点"], "ABCDEF"),
        line(11, ["十一号起点", "十一号终点"], "112233"),
        line(21, ["二十一号起点", "二十一号终点"], "445566"),
    ]}
    monkeypatch.setattr(M, "fetch_cn", lambda city: payload)
    monkeypatch.setattr(T, "_registered_layers", {})
    monkeypatch.setattr(T, "_pending_layers", [])
    monkeypatch.setattr(T, "_pending_qa_warnings", [])


def _inv(city, line=""):
    from backend.services import tools as T
    return T.metro_line.invoke({"city": city, "line": line})


def test_changsha_line1_structure():
    """国内线路：站点、起讫站、WGS-84 坐标和换乘标记。"""
    from backend.services import tools as T
    r = _inv("长沙", "1号线")
    assert "1号线" in r and "3 站" in r, r
    assert "已上图" in r
    pts = T._registered_layers["长沙地铁站点"]["geojson"]["features"]
    assert len(pts) == 3
    for f in pts:
        lon, lat = f["geometry"]["coordinates"]
        assert 112 < lon < 114 and 27.5 < lat < 29, (lon, lat)
    names = [f["properties"]["name"] for f in pts]
    assert names == ["起点", "换乘站", "终点"]
    assert [f["properties"]["transfer"] for f in pts] == [False, True, False]
    assert pts[0]["geometry"]["coordinates"] != [112.98, 28.10]


def test_changsha_line_color():
    from backend.services import tools as T
    _inv("长沙", "1号线")
    feat = T._registered_layers["长沙地铁1号线"]["geojson"]["features"][0]
    assert feat["properties"]["color"] == "#ABCDEF"
    assert T._pending_layers[0]["style"]["color"] == "#ABCDEF"


def test_full_network():
    from backend.services import tools as T
    r = _inv("长沙")
    assert "3 条线" in r and "7 站" in r, r[:200]
    line_layers = [n for n in T._registered_layers if n.startswith("长沙地铁") and "站点" not in n]
    assert len(line_layers) == 3


def test_unsupported_city_clear_error():
    from backend.services.tools import _tool_result_failed

    r = _inv("亚特兰蒂斯")
    assert "暂不支持" in r or "失败" in r, r
    assert _tool_result_failed("metro_line", r)


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
    assert len(stations) == 3, len(stations)
