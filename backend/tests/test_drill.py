# -*- coding: utf-8 -*-
"""行政区下钻（drill_down / drill_up / _fid / /api/boundary）测试

下钻链路最容易出的问题：adcode 解析静默失败、DataV parent 字段是 dict 时拼出
乱码图层名、_fid 注入不稳定导致 2D/3D 选中同步失效。这里逐条钉住。
网络全部 mock，不打真实 DataV。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.services import tools as T
from backend.services.tools import drill_down, drill_up, _register_layer, _registered_layers, reset_state


def _cities_fc(parent_adcode="430000"):
    """模拟 DataV {adcode}_full.json 返回：湖南下 2 个地级市"""
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[[112.0, 27.0], [113.0, 27.0], [113.0, 28.0], [112.0, 28.0], [112.0, 27.0]]]},
         "properties": {"adcode": 430100, "name": "长沙市", "level": "city",
                        "parent": {"adcode": parent_adcode, "name": "湖南省"}}},
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[[113.0, 26.0], [114.0, 26.0], [114.0, 27.0], [113.0, 27.0], [113.0, 26.0]]]},
         "properties": {"adcode": 430200, "name": "株洲市", "level": "city",
                        "parent": {"adcode": parent_adcode, "name": "湖南省"}}},
    ]}


@pytest.fixture(autouse=True)
def _clean_state():
    reset_state()
    T._pending_layer_ops.clear()
    T._registered_layers.clear()
    yield
    T._registered_layers.clear()


class TestMakeFid:
    def test_adcode_priority(self):
        assert T._make_fid({"adcode": 430000, "name": "湖南省"}, 0) == "p:430000"

    def test_name_fallback(self):
        assert T._make_fid({"name": "长沙"}, 3) == "n:长沙"

    def test_index_fallback(self):
        assert T._make_fid({}, 7) == "i:7"


class TestRegisterLayerFidInjection:
    def test_fid_injected(self):
        fc = _cities_fc()
        _register_layer("湖南省_市", fc)
        feats = _registered_layers["湖南省_市"]["geojson"]["features"]
        assert feats[0]["properties"]["_fid"] == "p:430100"
        assert feats[1]["properties"]["_fid"] == "p:430200"

    def test_fid_idempotent(self):
        fc = _cities_fc()
        fc["features"][0]["properties"]["_fid"] = "p:custom"
        _register_layer("层A", fc)
        assert _registered_layers["层A"]["geojson"]["features"][0]["properties"]["_fid"] == "p:custom"

    def test_missing_properties_dict_created(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": None}]}
        _register_layer("层B", fc)
        assert _registered_layers["层B"]["geojson"]["features"][0]["properties"]["_fid"] == "i:0"


class TestDrillDownTool:
    def test_drill_down_by_adcode(self, monkeypatch):
        import backend.services.datav_service as dv
        monkeypatch.setattr(dv, "fetch_boundary_by_adcode", lambda ad: _cities_fc())
        r = drill_down.invoke({"adcode": "430000"})
        assert "已下钻" in r and "长沙市" in r
        # 图层已推送并注册
        assert any(l["name"].endswith("_地级市") for l in T._pending_layers)
        # 下钻 op 已下发，方向 down，adcode 正确
        ops = [o for o in T._pending_layer_ops if o["action"] == "drill"]
        assert len(ops) == 1
        assert ops[0]["direction"] == "down"
        assert ops[0]["adcode"] == "430000"
        assert ops[0]["level"] == "city"

    def test_drill_down_by_region_name(self, monkeypatch):
        import backend.services.datav_service as dv
        monkeypatch.setattr(dv, "fetch_boundary_by_adcode", lambda ad: _cities_fc())
        monkeypatch.setattr(dv, "_find_adcode", lambda name: 430000)
        r = drill_down.invoke({"region": "湖南省"})
        assert "已下钻" in r

    def test_drill_down_parent_dict_handled(self, monkeypatch):
        """DataV parent 字段是 dict 时，图层名不得出现 dict 字符串"""
        import backend.services.datav_service as dv
        monkeypatch.setattr(dv, "fetch_boundary_by_adcode", lambda ad: _cities_fc())
        drill_down.invoke({"adcode": "430000"})
        names = [l["name"] for l in T._pending_layers]
        assert names and "dict" not in names[0]
        assert names[0].startswith("湖南省")

    def test_drill_down_invalid_adcode(self):
        r = drill_down.invoke({"adcode": "abc"})
        assert "失败" in r

    def test_drill_down_no_data(self, monkeypatch):
        import backend.services.datav_service as dv
        monkeypatch.setattr(dv, "fetch_boundary_by_adcode", lambda ad: None)
        r = drill_down.invoke({"adcode": "999999"})
        assert "失败" in r

    def test_drill_down_empty_children(self, monkeypatch):
        import backend.services.datav_service as dv
        monkeypatch.setattr(dv, "fetch_boundary_by_adcode", lambda ad: {"type": "FeatureCollection", "features": []})
        r = drill_down.invoke({"adcode": "430000"})
        assert "失败" in r and "下级" in r


class TestDrillUpTool:
    def test_drill_up_emits_op(self):
        r = drill_up.invoke({})
        assert "返回上一级" in r
        ops = [o for o in T._pending_layer_ops if o["action"] == "drill"]
        assert ops and ops[0]["direction"] == "up"


class TestBoundaryApi:
    def _client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_boundary_ok(self, monkeypatch):
        import backend.services.datav_service as dv
        monkeypatch.setattr(dv, "fetch_boundary_by_adcode", lambda ad: _cities_fc())
        resp = self._client().get("/api/boundary", params={"adcode": "430000"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["geojson"]["type"] == "FeatureCollection"
        assert len(body["geojson"]["features"]) == 2

    def test_boundary_bad_adcode(self):
        resp = self._client().get("/api/boundary", params={"adcode": "43"})
        assert resp.status_code == 400

    def test_boundary_not_found(self, monkeypatch):
        import backend.services.datav_service as dv
        monkeypatch.setattr(dv, "fetch_boundary_by_adcode", lambda ad: None)
        resp = self._client().get("/api/boundary", params={"adcode": "999999"})
        assert resp.status_code == 404


class TestFetchBoundaryByAdcodeValidation:
    def test_rejects_non_6digit(self):
        from backend.services.datav_service import fetch_boundary_by_adcode
        assert fetch_boundary_by_adcode("43") is None
        assert fetch_boundary_by_adcode("abcd00") is None
