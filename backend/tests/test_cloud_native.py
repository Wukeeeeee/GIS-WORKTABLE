# -*- coding: utf-8 -*-
"""阶段二：云原生格式流式加载（COG / PMTiles / GeoParquet / FlatGeobuf）

单测全部用本地夹具（离线确定性）；
集成测试访问公开测试 URL，无网络环境自动 skip。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import socket
import json
import gzip
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

from backend.services import tools as T
from backend.services.tools import tools as TOOL_LIST, reset_state, get_pending_state, _registered_layers
from backend.services import cloud_native as cn
from backend.services import url_security


def _registry():
    return {t.name: t for t in TOOL_LIST}


@pytest.fixture
def range_test_server():
    body = b"0123456789abcdefghijklmnopqrstuvwxyz"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/private")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            range_header = self.headers.get("Range")
            if range_header:
                start, end = range_header.removeprefix("bytes=").split("-", 1)
                first = int(start)
                last = min(int(end), len(body) - 1)
                payload = body[first:last + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {first}-{last}/{len(body)}")
            else:
                payload = body
                self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_guarded_vsi_source_relays_range_requests_with_or_without_query(range_test_server, monkeypatch):
    original_opener = cn.safe_redirect_opener
    observed_timeouts = []

    def tracked_opener(*args, **kwargs):
        opener = original_opener(*args, **kwargs)

        class TrackedOpener:
            def open(self, request, timeout):
                observed_timeouts.append(timeout)
                return opener.open(request, timeout=timeout)

        return TrackedOpener()

    monkeypatch.setattr(cn, "safe_redirect_opener", tracked_opener)
    source = range_test_server + "/data"
    with cn.guarded_vsi_source(source) as vsi_path:
        local_url = vsi_path.removeprefix("/vsicurl/")
        for suffix in ("", "?cache=1", "/?cache=1"):
            request = urllib.request.Request(local_url + suffix, headers={"Range": "bytes=2-5"})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 206
                assert response.headers["Content-Range"] == "bytes 2-5/36"
                assert response.read() == b"2345"
    assert observed_timeouts == [cn._REMOTE_HTTP_TIMEOUT_SECONDS] * 3


def test_guarded_vsi_suppresses_expected_error_when_client_has_disconnected():
    class ClosedPipe:
        def write(self, _body):
            raise ConnectionAbortedError("client disconnected")

    class Handler(cn._GuardedVsiProxyHandler):
        def send_response(self, *_args, **_kwargs):
            return

        def send_header(self, *_args, **_kwargs):
            return

        def end_headers(self):
            return

    handler = object.__new__(Handler)
    handler.command = "GET"
    handler.close_connection = False
    handler.wfile = ClosedPipe()

    handler.send_error(404)

    assert handler.close_connection is True


def test_guarded_vsi_source_stops_on_a_stalled_upstream(monkeypatch):
    class SlowHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            threading.Event().wait(0.2)
            self.send_response(206)
            self.send_header("Content-Range", "bytes 0-3/36")
            self.send_header("Content-Length", "4")
            self.end_headers()
            self.wfile.write(b"0123")

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(cn, "_REMOTE_HTTP_TIMEOUT_SECONDS", 0.05)
    source = f"http://127.0.0.1:{server.server_port}/data"
    try:
        with cn.guarded_vsi_source(source) as vsi_path:
            request = urllib.request.Request(
                vsi_path.removeprefix("/vsicurl/"), headers={"Range": "bytes=0-3"}
            )
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request, timeout=3)
            assert error.value.code == 502
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_guarded_vsi_source_blocks_public_redirect_to_private(range_test_server, monkeypatch):
    def classify_target(url):
        return "/redirect" in url

    monkeypatch.setattr(url_security, "is_public_http_target", classify_target)
    source = range_test_server + "/redirect"
    port = urllib.parse.urlsplit(source).port
    original_getaddrinfo = socket.getaddrinfo
    original_create_connection = socket.create_connection

    def resolve_as_public(_url):
        return True, tuple(original_getaddrinfo("8.8.8.8", port, type=socket.SOCK_STREAM))

    def route_public_fixture_to_loopback(address, *args, **kwargs):
        if address[0] == "8.8.8.8":
            address = ("127.0.0.1", port)
        return original_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(url_security, "resolve_http_target", resolve_as_public)
    monkeypatch.setattr(socket, "create_connection", route_public_fixture_to_loopback)
    with cn.guarded_vsi_source(source) as vsi_path:
        request = urllib.request.Request(vsi_path.removeprefix("/vsicurl/"), headers={"Range": "bytes=0-3"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == 403


@pytest.mark.parametrize("reader", ["download", "pmtiles"])
def test_cloud_native_explains_auth_failure_after_cross_origin_redirect(monkeypatch, reader):
    from types import SimpleNamespace

    source = "https://provider.example/data?token=KEY_SENTINEL"
    redirect_guard = SimpleNamespace(credentials_stripped=True)

    class Opener:
        handlers = [redirect_guard]

        def open(self, _request, timeout):
            raise urllib.error.HTTPError(source, 403, "Forbidden", {}, None)

    monkeypatch.setattr(cn, "get_effective_proxies", lambda: {})
    monkeypatch.setattr(cn, "safe_redirect_opener", lambda *_args, **_kwargs: Opener())

    with pytest.raises(cn.CloudNativeError, match="没有把认证参数转发过去") as exc:
        if reader == "download":
            cn.http_download_to_temp(source, "tif")
        else:
            cn._HttpRangeSource(source).get_bytes(0, 4)

    assert "KEY_SENTINEL" not in str(exc.value)


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


def test_remote_cog_uses_guarded_source_context(local_tif, monkeypatch):
    from contextlib import contextmanager
    opened = []

    @contextmanager
    def guarded_source(source):
        opened.append(source)
        yield local_tif

    monkeypatch.setattr(cn, "guarded_vsi_source", guarded_source)
    result = cn.read_cog("https://public.example/data.tif")
    assert result["meta"]["width"] == 64
    assert opened == ["https://public.example/data.tif"]


@pytest.mark.parametrize("reader_name", ["read_cog", "cog_info"])
def test_remote_cog_uses_bounded_gdal_http_options(monkeypatch, reader_name):
    import rasterio
    from contextlib import contextmanager

    source = "https://public.example/data.tif"
    observed = {}
    previous_timeout = rasterio.env.get_gdal_config("GDAL_HTTP_TIMEOUT")

    @contextmanager
    def guarded_source(_source):
        yield "/vsicurl/http://127.0.0.1:12345/data"

    def inspect_options(_source, *args, **kwargs):
        assert kwargs["fallback_url"] == source
        observed.update({
            key: rasterio.env.get_gdal_config(key)
            for key in (
                "GDAL_HTTP_TIMEOUT", "GDAL_HTTP_CONNECTTIMEOUT", "GDAL_HTTP_MAX_RETRY",
                "GDAL_HTTP_LOW_SPEED_LIMIT", "GDAL_HTTP_LOW_SPEED_TIME",
            )
        })
        return {"ok": True}

    monkeypatch.setattr(cn, "guarded_vsi_source", guarded_source)
    implementation_name = "_read_cog_impl" if reader_name == "read_cog" else "_cog_info_impl"
    monkeypatch.setattr(cn, implementation_name, inspect_options)

    assert getattr(cn, reader_name)(source) == {"ok": True}
    assert observed == {
        "GDAL_HTTP_TIMEOUT": 20,
        "GDAL_HTTP_CONNECTTIMEOUT": 5,
        "GDAL_HTTP_MAX_RETRY": 0,
        "GDAL_HTTP_LOW_SPEED_LIMIT": 1,
        "GDAL_HTTP_LOW_SPEED_TIME": 20,
    }
    assert rasterio.env.get_gdal_config("GDAL_HTTP_TIMEOUT") == previous_timeout


@pytest.mark.parametrize("reader_name", ["read_cog", "cog_info"])
def test_remote_cog_502_error_includes_proxy_connect_hint(monkeypatch, reader_name):
    from contextlib import contextmanager

    @contextmanager
    def guarded_source(_source):
        yield "/vsicurl/http://127.0.0.1:12345/data"

    def fail_with_502(*_args, **_kwargs):
        raise cn.CloudNativeError("COG 读取失败: HTTP response code: 502")

    monkeypatch.setattr(cn, "guarded_vsi_source", guarded_source)
    implementation_name = "_read_cog_impl" if reader_name == "read_cog" else "_cog_info_impl"
    monkeypatch.setattr(cn, implementation_name, fail_with_502)

    with pytest.raises(cn.CloudNativeError, match="HTTPS CONNECT"):
        getattr(cn, reader_name)("https://public.example/data.tif")


@pytest.mark.parametrize('reader', [cn.read_cog, cn.cog_info], ids=['preview', 'metadata'])
@pytest.mark.parametrize('fail_local', [False, True], ids=['success', 'local-failure'])
def test_remote_cog_decode_failure_uses_bounded_download_and_cleans_it(local_tif, tmp_path, monkeypatch, reader, fail_local):
    import rasterio
    original_open = rasterio.open
    downloaded = tmp_path / 'fallback.tif'
    monkeypatch.setattr(cn, '_OWNED_TEMP_DOWNLOADS', set())
    requests = []
    def download(url, fmt):
        requests.append((url, fmt))
        downloaded.write_bytes(Path(local_tif).read_bytes())
        cn._OWNED_TEMP_DOWNLOADS.add(str(downloaded.resolve()))
        return str(downloaded)
    def open_source(source, *args, **kwargs):
        if str(source).startswith('/vsicurl/'):
            raise UnicodeDecodeError('utf-8', b'\xb0', 0, 1, 'invalid start byte')
        if fail_local: raise ValueError('invalid local TIFF')
        return original_open(source, *args, **kwargs)
    monkeypatch.setattr(cn, 'http_download_to_temp', download)
    monkeypatch.setattr(rasterio, 'open', open_source)
    if fail_local:
        with pytest.raises(cn.CloudNativeError, match='invalid local TIFF'):
            reader('https://example.invalid/source.tif')
    else:
        result = reader('https://example.invalid/source.tif')
        assert result
    assert requests == [('https://example.invalid/source.tif', 'tif')]
    assert not downloaded.exists()
    assert Path(local_tif).exists()


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


def test_load_cog_does_not_store_credentials_in_registered_layer(tmp_path, monkeypatch):
    reset_state()
    monkeypatch.setattr(T, "_temp_output_dir", str(tmp_path))
    monkeypatch.setattr(T, "init_temp_dir", lambda: None)
    source = "https://user:PASS_SENTINEL@example.test/data.tif?token=TOKEN_SENTINEL"
    monkeypatch.setattr(cn, "read_cog", lambda *_args, **_kwargs: {
        "png_bytes": b"png",
        "bounds": [0, 0, 1, 1],
        "meta": {
            "width": 1, "height": 1, "count": 1, "crs": "EPSG:4326",
            "bounds_wgs84": [0, 0, 1, 1], "resampled": [1, 1],
        },
    })

    result = _registry()["load_cog"].invoke({"url": source})
    pending_text = json.dumps(get_pending_state(), ensure_ascii=False)

    assert "已加载" in result
    assert "PASS_SENTINEL" not in pending_text
    assert "TOKEN_SENTINEL" not in pending_text
    assert "https://example.test/data.tif" in pending_text


def test_get_cog_info_redacts_credentials_from_error(monkeypatch):
    source = "https://user:PASS_SENTINEL@example.test/data.tif?token=TOKEN_SENTINEL"
    monkeypatch.setattr(
        cn, "cog_info", lambda _source: (_ for _ in ()).throw(
            cn.CloudNativeError(f"COG failed to read {source}")
        ),
    )

    result = _registry()["get_cog_info"].invoke({"url": source})

    assert "PASS_SENTINEL" not in result
    assert "TOKEN_SENTINEL" not in result
    assert "https://example.test/data.tif" in result


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


def test_remote_flatgeobuf_uses_guarded_source_context(local_fgb, monkeypatch):
    from contextlib import contextmanager
    opened = []

    @contextmanager
    def guarded_source(source):
        opened.append(source)
        yield local_fgb

    monkeypatch.setattr(cn, "guarded_vsi_source", guarded_source)
    geojson, meta = cn.cloud_vector_to_geojson("https://public.example/data.fgb", "FlatGeobuf")
    assert meta["loaded_features"] == 15
    assert opened == ["https://public.example/data.fgb"]


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
    try:
        r = _registry()["load_flatgeobuf"].invoke(
            {"source": FGB_URL, "layer_name": "远程FGB", "limit": 100})
        if "timed out" in r.lower() or "timeout" in r.lower():
            pytest.skip(f"远程 FlatGeobuf 网络超时: {r}")
        assert "已加载" in r, r
    except Exception as e:
        if "timeout" in str(e).lower() or "timed out" in str(e).lower():
            pytest.skip(f"远程 FlatGeobuf 网络超时: {e}")
        raise
