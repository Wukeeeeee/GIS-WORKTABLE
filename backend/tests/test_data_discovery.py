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

    def test_format_and_bbox(self):
        assert normalize_format("GeoJSON") == "geojson"
        assert normalize_format("json") == "geojson"
        assert normalize_format("gpkg") == "gpkg"
        assert normalize_format(".tif") == "geotiff"
        assert normalize_format("kmz") == ""
        assert parse_bbox("112.9,28.1,113.2,28.4") == (112.9, 28.1, 113.2, 28.4)
        assert parse_bbox("a,b,c") is None
        assert parse_bbox("200,0,201,1") is None


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

    def test_discover_missing_area_raises(self):
        with pytest.raises(DataProviderError) as ei:
            data_discovery.discover(kind="roads", area="")
        assert "空间范围" in str(ei.value) or "空间范围" in ei.value.message

    def test_discover_unknown_provider(self):
        with pytest.raises(DataProviderError) as ei:
            data_discovery.discover(kind="roads", area="长沙", provider_id="nope")
        assert "未知数据源" in ei.value.message

    def test_discover_rejects_unknown_format(self):
        with pytest.raises(DataProviderError) as ei:
            data_discovery.discover(kind="roads", area="长沙", file_format="kmz")
        assert "不支持的文件格式" in ei.value.message

    def test_discover_raster_returns_auth_guidance(self, monkeypatch):
        # dem：copernicus 无 token → 认证说明；usgs/gscloud → 指引（downloadable=False）
        monkeypatch.setattr(
            "backend.services.data_providers.geocode.resolve_area_bbox",
            lambda area: (112.9, 28.1, 113.2, 28.4),
        )
        monkeypatch.delenv("COPERNICUS_API_TOKEN", raising=False)
        r = data_discovery.discover(kind="dem", area="长沙")
        assert r["kind"] == "dem"
        assert r["hits"], "应返回 USGS/地理空间数据云 的指引命中"
        assert all(h["downloadable"] is False for h in r["hits"])
        auth_msgs = [(n["message"] or "") + (n.get("hint") or "") for n in r["notes"]]
        assert any("COPERNICUS_API_TOKEN" in m for m in auth_msgs)


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

    def test_download_gpkg_preserves_crs(self, monkeypatch, tmp_path):
        asset = _download_asset(monkeypatch, tmp_path, "roads", file_format="gpkg")
        import geopandas as gpd
        gdf = gpd.read_file(asset["file_path"])
        assert gdf.crs and gdf.crs.to_string() == "EPSG:4326"
        assert len(gdf) == 2

    def test_download_shp(self, monkeypatch, tmp_path):
        asset = _download_asset(monkeypatch, tmp_path, "roads", file_format="shp")
        assert asset["file_path"].endswith(".shp")
        assert asset["url"].startswith("/")
        # 回读
        import geopandas as gpd
        gdf = gpd.read_file(asset["file_path"])
        assert len(gdf) == 2

    def test_download_empty_raises_not_found(self, monkeypatch):
        monkeypatch.setattr(osm_provider.http, "post_overpass",
                            lambda q, url, **k: {"elements": []})
        with pytest.raises(DataNotFoundError):
            data_discovery.download(kind="roads", area="长沙", bbox="112.9,28.1,113.2,28.4")


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

    def test_osmirror_timeout_exhausted(self, monkeypatch):
        monkeypatch.setattr(osm_provider, "OVERPASS_ENDPOINTS", ["https://m1", "https://m2"])
        calls = []

        def _boom(q, url, **k):
            calls.append(url)
            raise DownloadTimeoutError("超时")
        monkeypatch.setattr(osm_provider.http, "post_overpass", _boom)
        p = osm_provider.OpenStreetMapProvider()
        with pytest.raises(DownloadTimeoutError):
            p.download(make_req("roads", bbox=(112.9, 28.1, 113.2, 28.4)))
        # 两个镜像都试过且次数受限
        assert len(calls) == 2

    def test_http_retry_limited_on_timeout(self, monkeypatch):
        n = {"c": 0}

        def _boom(*a, **k):
            n["c"] += 1
            raise DownloadTimeoutError("timeout")
        monkeypatch.setattr(dhttp, "request_once", _boom)
        with pytest.raises(DownloadTimeoutError):
            dhttp.request_with_retry("GET", "https://x", retries=2, backoff=0)
        assert n["c"] == 3  # 1 次 + 重试 2 次，不超过限制

    def test_http_no_retry_on_size_limit(self, monkeypatch):
        n = {"c": 0}

        def _boom(*a, **k):
            n["c"] += 1
            raise DataValidationError("数据响应超过大小上限，已中断")
        monkeypatch.setattr(dhttp, "request_once", _boom)
        with pytest.raises(DataValidationError):
            dhttp.request_with_retry("GET", "https://x", retries=3, backoff=0)
        assert n["c"] == 1  # 数据本身问题不重试

    def test_format_error_rejected(self, monkeypatch):
        # 返回非 GeoJSON → 明确拒绝
        with pytest.raises(DataValidationError):
            storage.validate_vector({"type": "wat"}, crs="EPSG:4326", crs_known=True)

    def test_crs_missing_rejected(self, monkeypatch):
        # Provider 返回缺 CRS 的数据 → 拒绝加载
        from backend.services.data_providers.base import provider_by_id
        p = provider_by_id("osm")
        fc = {"type": "FeatureCollection",
              "features": [{"type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [112.9, 28.2]},
                            "properties": {}}]}
        monkeypatch.setattr(p, "download",
                            lambda req: {"geojson": fc, "crs": "", "crs_known": False})
        with pytest.raises(DataValidationError) as ei:
            data_discovery.download(kind="roads", area="长沙", bbox="112.9,28.1,113.2,28.4")
        assert "CRS" in ei.value.message

    def test_unknown_format_write_rejected(self):
        from backend.services.data_providers import storage as st
        fc = {"type": "FeatureCollection",
              "features": [{"type": "Feature", "geometry": {"type": "Point",
                             "coordinates": [112.9, 28.2]}, "properties": {}}]}
        with pytest.raises(DataValidationError):
            st.write_vector(fc, out_format="dwg", name="x", dirpath=".")


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

    def test_discover_tool_returns_text(self, monkeypatch):
        _patch_osm(monkeypatch, "roads")
        from backend.services.tools import discover_gis_data
        txt = discover_gis_data.func(query="长沙道路", area="长沙")
        assert "OpenStreetMap" in txt
        assert "可获取" in txt
        assert "download_gis_data" in txt


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

    def test_copernicus_requires_token(self, monkeypatch):
        monkeypatch.delenv("COPERNICUS_API_TOKEN", raising=False)
        from backend.services.data_providers.copernicus_provider import CopernicusProvider
        with pytest.raises(ProviderAuthError) as ei:
            CopernicusProvider().search(make_req("imagery", bbox=(112.9, 28.1, 113.0, 28.2)))
        assert "token" in ei.value.message.lower() or "COPERNICUS_API_TOKEN" in ei.value.hint

    def test_gscloud_guidance_only(self):
        from backend.services.data_providers.gscloud_provider import GSCloudProvider
        hits = GSCloudProvider().search(make_req("dem", area="长沙"))
        assert len(hits) == 1
        assert hits[0].downloadable is False
        assert "gscloud" in hits[0].source_url


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
