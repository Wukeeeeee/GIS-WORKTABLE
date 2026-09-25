# -*- coding: utf-8 -*-
"""阶段二：云原生格式流式加载（COG / PMTiles / GeoParquet / FlatGeobuf）

单测全部用本地夹具（离线确定性）；
集成测试访问公开测试 URL，无网络环境自动 skip。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import gzip
import tempfile
import urllib.request

import pytest

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

from backend.services import tools as T
from backend.services.tools import tools as TOOL_LIST, reset_state, get_pending_state, _registered_layers
from backend.services import cloud_native as cn


def _registry():
    return {t.name: t for t in TOOL_LIST}


# ============================================================
# 本地夹具
# ============================================================

@pytest.fixture(scope="module")
def local_tif(tmp_path_factory):
    """用 rasterio 生成一个小 GeoTIFF（3 波段，EPSG:4326）"""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    path = str(tmp_path_factory.mktemp("cog") / "demo.tif")
    data = np.zeros((3, 64, 64), dtype="uint8")
    data[0] = 200
    data[1] = np.linspace(0, 255, 64, dtype="uint8")[None, :]
    data[2] = 100
    transform = from_bounds(116.0, 39.0, 117.0, 40.0, 64, 64)
    with rasterio.open(path, "w", driver="GTiff", width=64, height=64, count=3,
                       dtype="uint8", crs="EPSG:4326", transform=transform) as ds:
        ds.write(data)
    return path


@pytest.fixture(scope="module")
def local_pmtiles(tmp_path_factory):
    """构造一个极小矢量 PMTiles（1 个点要素，z8，北京附近）"""
    import mapbox_vector_tile
    from pmtiles.writer import write
    from pmtiles.tile import TileType, Compression, zxy_to_tileid
    tile_buf = mapbox_vector_tile.encode([
        {"name": "cities", "extent": 4096, "version": 2,
         "features": [{"geometry": "POINT(2048 2048)",
                       "properties": {"name": "Beijing", "population": 21000000}}]},
    ])
    path = str(tmp_path_factory.mktemp("pm") / "fixture.pmtiles")
    tx, ty = cn._deg2tile(116.4, 40.0, 8)
    header = {"tile_compression": Compression.GZIP, "tile_type": TileType.MVT,
              "min_lon_e7": 1159000000, "min_lat_e7": 394000000,
              "max_lon_e7": 1171000000, "max_lat_e7": 406000000,
              "center_lon_e7": 1164000000, "center_lat_e7": 400000000,
              "center_zoom": 8}
    with write(path) as w:
        w.write_tile(zxy_to_tileid(8, tx, ty), gzip.compress(tile_buf))
        w.finalize(header, {"vector_layers": [{"id": "cities", "fields": {"name": "String"}}]})
    return path


@pytest.fixture(scope="module")
def local_parquet(tmp_path_factory):
    """geopandas 写一个本地 GeoParquet"""
    import geopandas as gpd
    from shapely.geometry import Point
    gdf = gpd.GeoDataFrame(
        {"name": [f"p{i}" for i in range(20)]},
        geometry=[Point(116 + i * 0.01, 39.5 + i * 0.01) for i in range(20)],
        crs="EPSG:4326")
    path = str(tmp_path_factory.mktemp("pq") / "points.parquet")
    gdf.to_parquet(path)
    return path


@pytest.fixture(scope="module")
def local_fgb(tmp_path_factory):
    """geopandas/pyogrio 写一个本地 FlatGeobuf"""
    import geopandas as gpd
    from shapely.geometry import Point
    gdf = gpd.GeoDataFrame(
        {"name": [f"f{i}" for i in range(15)]},
        geometry=[Point(110 + i * 0.1, 30.0 + i * 0.1) for i in range(15)],
        crs="EPSG:4326")
    path = str(tmp_path_factory.mktemp("fgb") / "points.fgb")
    gdf.to_file(path, driver="FlatGeobuf")
    return path


# ============================================================
# parse_bbox
# ============================================================

def test_parse_bbox_ok():
    assert cn.parse_bbox("116,39,117,40") == (116.0, 39.0, 117.0, 40.0)
    assert cn.parse_bbox("") is None
    assert cn.parse_bbox(None) is None


def test_parse_bbox_errors():
    with pytest.raises(cn.CloudNativeError):
        cn.parse_bbox("116,39,117")          # 少一个数
    with pytest.raises(cn.CloudNativeError):
        cn.parse_bbox("a,b,c,d")             # 非数字
    with pytest.raises(cn.CloudNativeError):
        cn.parse_bbox("120,39,117,40")       # minx > maxx


# ============================================================
# COG
# ============================================================

def test_cog_info_local(local_tif):
    info = cn.cog_info(local_tif)
    assert info["crs"] == "EPSG:4326"
    assert info["count"] == 3
    assert info["width"] == 64 and info["height"] == 64
    assert len(info["bounds_wgs84"]) == 4
    assert info["stats_sampled"][0]["min"] is not None


def test_read_cog_preview(local_tif):
    r = cn.read_cog(local_tif, max_size=256)
    assert r["png_bytes"][:8] == b"\x89PNG\r\n\x1a\n"
    w, s, e, n = r["bounds"]
    assert 115.9 <= w < 116.1 and 39.9 < n <= 40.1
    assert r["meta"]["count"] == 3


def test_load_cog_tool_registers_layer_and_overlay(local_tif):
    reset_state()
    r = _registry()["load_cog"].invoke({"url": local_tif, "layer_name": "测试影像"})
    assert "已加载" in r
    pending = get_pending_state()
    assert any(op["action"] == "dem_result" for op in pending["layer_ops"])
    # 产物 PNG 真实落盘
    overlay = next(op for op in pending["layer_ops"] if op["action"] == "dem_result")
    assert os.path.exists(os.path.join(T._temp_output_dir, "uploads",
                                       os.path.basename(overlay["url"])))
    # 范围框图层已注册且上图
    assert "测试影像" in _registered_layers
    assert any(l["name"] == "测试影像" for l in pending["layers"])


def test_get_cog_info_tool(local_tif):
    r = _registry()["get_cog_info"].invoke({"url": local_tif})
    assert "EPSG:4326" in r and "波段" in r


# ============================================================
# PMTiles
# ============================================================

def test_pmtiles_info(local_pmtiles):
    info = cn.pmtiles_info(local_pmtiles)
    assert info["tile_type"].endswith("MVT") or "MVT" in info["tile_type"]
    assert info["min_zoom"] == 8


def test_pmtiles_vector_decode(local_pmtiles):
    gj, info = cn.pmtiles_vector_to_geojson(local_pmtiles)
    assert info["feature_count"] == 1
    assert info["layers"] == ["cities"]
    feat = gj["features"][0]
    assert feat["geometry"]["type"] == "Point"
    lon, lat = feat["geometry"]["coordinates"][0], feat["geometry"]["coordinates"][1]
    # 点位于夹具 bbox（115.9~117.1, 39.4~40.6）内（MVT 点编码在瓦片中心）
    assert 115.9 < lon < 117.1 and 39.4 < lat < 40.6
    assert feat["properties"]["name"] == "Beijing"


def test_load_pmtiles_tool(local_pmtiles):
    reset_state()
    r = _registry()["load_pmtiles"].invoke({"source": local_pmtiles, "layer_name": "PM点"})
    assert "已加载" in r
    assert "PM点" in _registered_layers
    pending = get_pending_state()
    assert any(l["name"] == "PM点" for l in pending["layers"])


def test_load_pmtiles_missing_file():
    r = _registry()["load_pmtiles"].invoke({"source": "Z:/不存在/none.pmtiles"})
    assert "失败" in r or "不存在" in r


# ============================================================
# GeoParquet / FlatGeobuf
# ============================================================

def test_geoparquet_metadata(local_parquet):
    meta = cn.cloud_vector_metadata(local_parquet, "GeoParquet")
    assert meta["features"] == 20
    assert "name" in meta["fields"]


def test_geoparquet_to_geojson(local_parquet):
    gj, meta = cn.cloud_vector_to_geojson(local_parquet, "GeoParquet")
    assert meta["loaded_features"] == 20
    assert gj["features"][0]["geometry"]["type"] == "Point"


def test_flatgeobuf_to_geojson(local_fgb):
    gj, meta = cn.cloud_vector_to_geojson(local_fgb, "FlatGeobuf")
    assert meta["loaded_features"] == 15
    assert gj["features"][0]["geometry"]["type"] == "Point"


def test_flatgeobuf_bbox_filter(local_fgb):
    gj, meta = cn.cloud_vector_to_geojson(
        local_fgb, "FlatGeobuf", bbox=(110.0, 30.0, 111.0, 31.0))
    assert 0 < meta["loaded_features"] < 15
    assert meta["bbox_filtered"] == [110.0, 30.0, 111.0, 31.0]


def test_geoparquet_explicit_limit_truncates(local_parquet, monkeypatch):
    gj, meta = cn.cloud_vector_to_geojson(local_parquet, "GeoParquet", limit=5)
    assert meta["loaded_features"] == 5


def test_geoparquet_over_limit_refuses_without_bbox(local_parquet, monkeypatch):
    monkeypatch.setattr(cn, "_CLOUD_VECTOR_LIMIT_DEFAULT", 10)
    with pytest.raises(cn.CloudNativeError) as e:
        cn.cloud_vector_to_geojson(local_parquet, "GeoParquet")
    assert "bbox" in str(e.value)


def test_load_geoparquet_tool(local_parquet):
    reset_state()
    r = _registry()["load_geoparquet"].invoke({"source": local_parquet, "layer_name": "PQ点"})
    assert "已加载" in r
    assert "PQ点" in _registered_layers


def test_load_flatgeobuf_tool(local_fgb):
    reset_state()
    r = _registry()["load_flatgeobuf"].invoke({"source": local_fgb, "layer_name": "FGB点"})
    assert "已加载" in r
    assert "FGB点" in _registered_layers


# ============================================================
# 工具注册完整性
# ============================================================

def test_cloud_native_tools_registered():
    names = {t.name for t in TOOL_LIST}
    for n in ("load_cog", "get_cog_info", "load_pmtiles", "load_geoparquet", "load_flatgeobuf"):
        assert n in names


# ============================================================
# 集成测试：公开测试 URL（无网络环境自动 skip）
# ============================================================

def _network_ok(url) -> bool:
    """探测：对目标发 Range GET（bytes=0-0）。HEAD 对部分 CDN 会挂起，不可靠。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Gis-WorkTable/1.0",
                                                   "Range": "bytes=0-0"})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception:
        return False


GITHUB_RAW = "https://raw.githubusercontent.com/rasterio/rasterio/main/tests/data/RGB.byte.tif"
PM_URL = ("https://raw.githubusercontent.com/protomaps/PMTiles/main/spec/v3/"
          "protomaps(vector)ODbL_firenze.pmtiles")
PQ_URL = "https://github.com/opengeospatial/geoparquet/raw/v1.1.0/examples/example.parquet"
FGB_URL = "https://raw.githubusercontent.com/flatgeobuf/flatgeobuf/master/test/data/UScounties.fgb"


@pytest.mark.slow
def test_integration_cog_remote():
    if not _network_ok(GITHUB_RAW):
        pytest.skip("无网络环境，跳过远程 COG 集成测试")
    r = _registry()["load_cog"].invoke({"url": GITHUB_RAW, "layer_name": "远程影像"})
    assert "已加载" in r, r


@pytest.mark.slow
def test_integration_pmtiles_remote():
    if not _network_ok(PM_URL.replace("(", "%28").replace(")", "%29")):
        pytest.skip("无网络环境，跳过远程 PMTiles 集成测试")
    reset_state()
    r = _registry()["load_pmtiles"].invoke(
        {"source": PM_URL, "layer_name": "firenze", "max_features": 500})
    assert "已加载" in r, r
    assert "firenze" in _registered_layers


@pytest.mark.slow
def test_integration_geoparquet_remote():
    if not _network_ok(PQ_URL):
        pytest.skip("无网络环境，跳过远程 GeoParquet 集成测试")
    reset_state()
    r = _registry()["load_geoparquet"].invoke({"source": PQ_URL, "layer_name": "远程PQ"})
    assert "已加载" in r, r


@pytest.mark.slow
def test_integration_flatgeobuf_remote():
    if not _network_ok(FGB_URL):
        pytest.skip("无网络环境，跳过远程 FlatGeobuf 集成测试")
    reset_state()
    r = _registry()["load_flatgeobuf"].invoke(
        {"source": FGB_URL, "layer_name": "远程FGB", "limit": 100})
    assert "已加载" in r, r
