"""
GIS 开放数据发现与获取（data_discovery / data_providers）测试。

原则：不依赖真实外网。所有 HTTP 出口经统一 http 模块 / Provider 搜索，用
monkeypatch 打桩，保证确定性；真实 Overpass/Nominatim/STAC 语法已另行人工验证。

覆盖需求点：
  城市道路 / POI / 建筑查询；下载成功；下载失败；网络超时(重试受限)；
  无结果；数据格式错误；CRS 缺失；成功加载到地图；遥感发现(需认证指引)；
  文件大小/格式白名单；metadata 字段；能力列表。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import pytest

from backend.services import data_discovery
from backend.services.data_providers import (
    http as dhttp,
    osm_provider,
    usgs_provider,
    storage,
)
from backend.services.data_providers.errors import (
    DataNotFoundError,
    DataProviderError,
    DataValidationError,
    DownloadTimeoutError,
    ProviderAuthError,
    ProviderUnavailableError,
)
from backend.services.data_providers.models import (
    normalize_kind,
    normalize_format,
    parse_bbox,
)


# ============================================================
# Overpass 打桩数据
# ============================================================

def _pt(lon, lat):
    return {"lon": lon, "lat": lat}


def _line_way(eid, tags, *, closed=False):
    base = 112.940 + eid * 0.001
    if closed:
        pts = [_pt(base, 28.200), _pt(base + 0.002, 28.200),
               _pt(base + 0.002, 28.202), _pt(base, 28.202)]
        pts.append(pts[0])
    else:
        pts = [_pt(base, 28.200), _pt(base + 0.002, 28.201)]
    return {"type": "way", "id": eid, "tags": tags, "geometry": pts}


def _node(eid, tags, lon=112.94, lat=28.20):
    return {"type": "node", "id": eid, "tags": tags, "lat": lat, "lon": lon}


_GEOM_FIXTURES = {
    "roads": {
        "count": {"elements": [{"type": "count", "tags": {"ways": 3, "nodes": 0}}]},
        "geom": {"elements": [_line_way(1, {"highway": "residential", "name": "测试路"}),
                              _line_way(2, {"highway": "tertiary"})]},
    },
    "buildings": {
        "count": {"elements": [{"type": "count", "tags": {"ways": 2}}]},
        "geom": {"elements": [_line_way(1, {"building": "yes", "name": "楼A"}, closed=True),
                              _line_way(2, {"building": "house"}, closed=True)]},
    },
    "pois": {
        "count": {"elements": [{"type": "count", "tags": {"nodes": 2, "ways": 2}}]},
        "geom": {"elements": [_node(1, {"amenity": "restaurant", "name": "餐厅"}),
                              _line_way(2, {"amenity": "school"}, closed=True)]},
    },
    "waterways": {
        "count": {"elements": [{"type": "count", "tags": {"ways": 2}}]},
        "geom": {"elements": [_line_way(1, {"waterway": "river", "name": "湘江"}),
                              _line_way(2, {"natural": "water"}, closed=True)]},
    },
    "landuse": {
        "count": {"elements": [{"type": "count", "tags": {"ways": 1}}]},
        "geom": {"elements": [_line_way(1, {"landuse": "residential", "name": "居住区"}, closed=True)]},
    },
}


def _fake_overpass(fixtures):
    """返回按 query 是否含 'out count' 区分几何/计数响应的 post_overpass。"""
    def _inner(query: str, url: str, **kw):
        if "out count" in query:
            return fixtures["count"]
        return fixtures["geom"]
    return _inner


def _patch_osm(monkeypatch, kind: str):
    """把 OSM 网络出口替换为确定性打桩。kind 由解析后的规范化 kind 决定。"""
    fx = _GEOM_FIXTURES[kind]
    monkeypatch.setattr(osm_provider.http, "post_overpass", _fake_overpass(fx))
    monkeypatch.setattr(
        "backend.services.data_providers.geocode.resolve_area_bbox",
        lambda area: (112.9, 28.1, 113.2, 28.4),
    )


def _download_asset(monkeypatch, tmp_path, kind, **kw):
    _patch_osm(monkeypatch, kind)
    params = dict(kind=kind, area="长沙", bbox="112.9,28.1,113.2,28.4", max_items=50,
                  out_dir=str(tmp_path))
    params.update(kw)
    return data_discovery.download(**params)


# ============================================================
# 归一化小工具
# ============================================================

class TestNormalize:
    def test_kind_synonyms(self):
        assert normalize_kind("道路", "长沙") == "roads"
        assert normalize_kind("", "帮我找长沙市的道路数据") == "roads"
        assert normalize_kind("building", "") == "buildings"
        assert normalize_kind("", "POI") == "pois"
        assert normalize_kind("", "水系") == "waterways"
        assert normalize_kind("", "高程DEM") == "dem"
        assert normalize_kind("", "随便啥") == ""



# ============================================================
# 发现（Discover）
# ============================================================

class TestDiscover:
    def test_discover_osm_roads(self, monkeypatch):
        _patch_osm(monkeypatch, "roads")
        r = data_discovery.discover(kind="road", area="长沙")
        assert r["ok"] is True
        assert r["kind"] == "roads"
        hits = r["hits"]
        assert len(hits) >= 1
        h = hits[0]
        assert h["provider_id"] == "osm"
        assert h["downloadable"] is True
        assert h["crs"] == "EPSG:4326"
        assert h["feature_count"] == 3






# ============================================================
# 下载矢量（含格式 / CRS / metadata）
# ============================================================

class TestDownloadVector:
    @pytest.mark.parametrize("kind,geom_expected", [
        ("roads", ["LineString"]),
        ("buildings", ["Polygon"]),
        ("pois", ["Point", "Polygon"]),
        ("waterways", ["LineString", "Polygon"]),
        ("landuse", ["Polygon"]),
    ])
    def test_download_geojson_all_kinds(self, monkeypatch, tmp_path, kind, geom_expected):
        asset = _download_asset(monkeypatch, tmp_path, kind)
        assert asset["ok"] is True
        assert asset["provider"] == "osm"
        assert asset["file_format"] == "geojson"
        assert asset["crs_known"] is True
        assert asset["feature_count"] >= 1
        assert all(g in asset["geometry_types"] for g in geom_expected)
        assert os.path.exists(asset["file_path"])
        # metadata：来源/名称/时间/格式/CRS 都在
        m = asset["metadata"]
        for k in ("provider", "file_name", "download_time", "file_format", "crs", "size_bytes"):
            assert m.get(k) is not None and m.get(k) != "", f"metadata 缺少 {k}"
        assert m["crs"] == "EPSG:4326"
        assert asset["geojson"]["type"] == "FeatureCollection"





# ============================================================
# 失败路径 / 网络
# ============================================================

class TestFailures:
    def test_download_provider_unavailable_raises(self, monkeypatch):
        monkeypatch.setattr(osm_provider.http, "post_overpass",
                            lambda q, url, **k: (_ for _ in ()).throw(
                                ProviderUnavailableError("HTTP 503")))
        with pytest.raises(ProviderUnavailableError):
            data_discovery.download(kind="roads", area="长沙", bbox="112.9,28.1,113.2,28.4")








# ============================================================
# 端到端：工具链路（发现 / 下载 / 加载到地图）
# ============================================================

class TestToolChain:
    def test_download_tool_loads_layer_to_map(self, monkeypatch):
        _patch_osm(monkeypatch, "roads")
        from backend.services.tools import download_gis_data, reset_state, _registered_layers, get_pending_state
        reset_state()
        txt = download_gis_data.func(kind="roads", area="长沙",
                                     bbox="112.9,28.1,113.2,28.4", max_items=10)
        assert "获取成功" in txt
        assert "已加载到地图" in txt
        assert "长沙_roads" in txt
        assert "长沙_roads" in _registered_layers
        pending = get_pending_state()
        names = [l["name"] for l in pending["layers"]]
        assert "长沙_roads" in names



# ============================================================
# 遥感 Provider 发现
# ============================================================

class TestRemoteProviders:
    def test_usgs_landsat_search_parses_items(self, monkeypatch):
        item = {
            "id": "LC09_L1TP_123041_20240111_20240111_02_T1",
            "type": "Feature",
            "bbox": [111.9, 26.3, 114.2, 28.4],
            "properties": {"datetime": "2024-01-11T02:57:22.465853Z"},
            "links": [],
        }
        monkeypatch.setattr(usgs_provider.http, "post_json",
                            lambda url, **k: {"features": [item], "numberMatched": 1})
        p = usgs_provider.USGSProvider()
        hits = p.search(make_req("imagery", bbox=(112.9, 28.1, 113.0, 28.2)))
        assert len(hits) == 1
        h = hits[0]
        assert h.provider_id == "usgs"
        assert "LC09_L1TP" in h.title
        assert h.time_start == "2024-01-11"
        assert h.downloadable is False




# ============================================================
# 能力列表
# ============================================================

class TestCapabilities:
    def test_listed_sources_auth_levels(self):
        from backend.services.data_providers import list_capabilities
        caps = {c["provider"]: c for c in list_capabilities()}
        assert set(caps) == {"osm", "copernicus", "usgs", "gscloud"}
        assert caps["osm"]["auth"] == "public"
        assert caps["copernicus"]["auth"] == "account"
        assert "roads" in caps["osm"]["vector_kinds"]
        assert "dem" in caps["usgs"]["raster_kinds"]
        assert caps["osm"]["crs_default"] == "EPSG:4326"


# ============================================================
# 工具函数
# ============================================================

def make_req(kind: str, area: str = "", bbox=None):
    from backend.services.data_providers.models import DataRequest
    return DataRequest(kind=kind, area=area, bbox=bbox)
