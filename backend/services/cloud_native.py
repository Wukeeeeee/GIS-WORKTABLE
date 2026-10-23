# -*- coding: utf-8 -*-
"""云原生格式流式加载（COG / PMTiles / GeoParquet / FlatGeobuf）

纯 Python 助手层：不定义 @tool，供三处复用：
- backend/services/tools.py 的 load_cog / get_cog_info / load_pmtiles /
  load_geoparquet / load_flatgeobuf（Agent 聊天入口）
- backend/main.py 的 /api/upload（.pmtiles/.parquet/.fgb 手动拖拽入口）
- backend/services/mcp_server.py（外部 AI 客户端）

流式原则：
- COG 走 rasterio /vsicurl/，只做降采样预览读取，不整体下载
- PMTiles 走 HTTP Range 请求按需读块
- GeoParquet / FlatGeobuf 走 pyogrio(GDAL /vsicurl/)，支持 BBOX 过滤与行数上限
"""
import gzip
import io
import json
import math
import os
import threading
from contextlib import contextmanager
import urllib.request

from backend.services.data_providers.errors import DataProviderError  # noqa: F401 (保持包初始化一致)


def get_effective_proxies() -> dict:
    """生效代理：优先 tools 模块的用户自定义代理，其次系统代理（延迟导入避免循环依赖）"""
    try:
        from backend.services.tools import get_proxy_config
        custom = get_proxy_config()
        if custom:
            return {"http": custom, "https": custom}
    except Exception:
        pass
    return urllib.request.getproxies()


class CloudNativeError(Exception):
    """云原生加载失败（消息可直接展示给用户）"""


def _as_vsi_path(source: str) -> str:
    """http(s) URL → GDAL /vsicurl/ 流式路径；本地路径原样返回"""
    s = str(source).strip()
    if s.lower().startswith(("http://", "https://")) and not s.lower().startswith("/vsi"):
        return "/vsicurl/" + s
    return s


def _is_http(source: str) -> bool:
    return str(source).strip().lower().startswith(("http://", "https://"))


def parse_bbox(bbox: str):
    """解析 "minx,miny,maxx,maxy" → (minx, miny, maxx, maxy)；空串返回 None"""
    if not bbox or not str(bbox).strip():
        return None
    parts = str(bbox).replace("，", ",").split(",")
    if len(parts) != 4:
        raise CloudNativeError("bbox 格式应为 minx,miny,maxx,maxy（经度,纬度,经度,纬度）")
    try:
        vals = [float(p.strip()) for p in parts]
    except ValueError:
        raise CloudNativeError(f"bbox 含非数字项: {bbox}")
    minx, miny, maxx, maxy = vals
    if not all(math.isfinite(v) for v in vals):
        raise CloudNativeError(f"bbox 必须是有限数值: {bbox}")
    if minx >= maxx or miny >= maxy:
        raise CloudNativeError(f"bbox 应为 minx<maxx, miny<maxy: {bbox}")
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        raise CloudNativeError(f"bbox 超出 WGS84 经纬度范围: {bbox}")
    return (minx, miny, maxx, maxy)


# ============================================================
# GDAL 网络回退：部分 Windows 机器 curl 编译为 schannel 且不做
# 中间证书补全（AIA fetching），访问 GitHub 等 CA 会出现
# "schannel: certificate chain is incomplete"，或在解码本地化网络错误时
# 抛出 UnicodeDecodeError。
# 此时回退 urllib（走系统证书存储）下载到临时文件再本地解析，
# 正常机器仍走 /vsicurl/ 流式，不整体下载。
# ============================================================

_DOWNLOAD_CAP_BYTES = 300 * 1024 * 1024
_OWNED_TEMP_DOWNLOADS = set()
_OWNED_TEMP_DOWNLOADS_LOCK = threading.Lock()


def _needs_gdal_download_fallback(err: Exception) -> bool:
    if isinstance(err, UnicodeDecodeError):
        return True
    msg = str(err)
    return "schannel" in msg or "CURL error" in msg


def _remove_temp_download(path: str | None) -> None:
    """删除本模块创建的回退下载文件，不触碰用户提供的本地路径。"""
    if not path:
        return
    candidate = os.path.abspath(path)
    with _OWNED_TEMP_DOWNLOADS_LOCK:
        owned = candidate in _OWNED_TEMP_DOWNLOADS
        _OWNED_TEMP_DOWNLOADS.discard(candidate)
    if owned:
        try:
            os.remove(candidate)
        except OSError:
            pass


@contextmanager
def _managed_temp_download(path: str):
    try:
        yield path
    finally:
        _remove_temp_download(path)


def http_download_to_temp(url: str, fmt: str = "") -> str:
    """urllib 下载远程文件到临时目录（上限 300MB），返回本地路径"""
    import tempfile
    from urllib.parse import urlparse
    u = str(url).strip()
    ext = os.path.splitext(urlparse(u).path)[1].lower() or (f".{fmt}" if fmt else ".bin")
    req = urllib.request.Request(u, headers={"User-Agent": "Gis-WorkTable/1.0"})
    proxies = get_effective_proxies()
    handler = urllib.request.ProxyHandler(proxies) if proxies else urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)
    path = None
    downloaded = False
    try:
        with opener.open(req, timeout=60) as resp:
            length = int(resp.headers.get("Content-Length") or 0)
            if length > _DOWNLOAD_CAP_BYTES:
                raise CloudNativeError(
                    f"远程文件 {length / 1e6:.0f}MB 超过下载回退上限 300MB"
                    "（本机 GDAL 网络通道受限，无法流式读取）")
            fd, path = tempfile.mkstemp(suffix=ext, prefix="gis_cloud_")
            with os.fdopen(fd, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 512)
                    if not chunk:
                        break
                    f.write(chunk)
                    if f.tell() > _DOWNLOAD_CAP_BYTES:
                        raise CloudNativeError("下载超过 300MB 上限，已中止")
        downloaded = True
        with _OWNED_TEMP_DOWNLOADS_LOCK:
            _OWNED_TEMP_DOWNLOADS.add(os.path.abspath(path))
        return path
    except CloudNativeError:
        raise
    except Exception as e:
        raise CloudNativeError(f"下载回退失败: {str(e)[:200]}")
    finally:
        if path and not downloaded:
            try:
                os.remove(path)
            except OSError:
                pass


def resolve_vector_source(source: str, fmt: str = "矢量") -> str:
    """矢量数据源解析：优先 /vsicurl/ 流式（元信息探测成功即用），证书受限时回退下载"""
    s_raw = str(source).strip()
    is_remote = _is_http(s_raw) or s_raw.lower().startswith(("/vsicurl/http://", "/vsicurl/https://"))
    src = _as_vsi_path(source)
    if not is_remote:
        if not os.path.exists(src):
            raise CloudNativeError(f"文件不存在: {src}")
        return src
    try:
        import pyogrio
        pyogrio.read_info(src)  # 轻量探测：能读元信息 = 流式通道可用
        return src
    except CloudNativeError:
        raise
    except Exception as e:
        # GDAL 网络错误表现不稳定（schannel 证书链 / 间歇性 open 失败），
        # http 源统一尝试 urllib 下载回退；下载也失败则报下载错误
        http_url = s_raw[len("/vsicurl/"):] if s_raw.lower().startswith("/vsicurl/") else s_raw
        if _needs_gdal_download_fallback(e):
            return http_download_to_temp(http_url, fmt)
        try:
            return http_download_to_temp(http_url, fmt)
        except CloudNativeError:
            raise CloudNativeError(f"{fmt} 元信息读取失败: {str(e)[:300]}")


# ============================================================
# COG（Cloud Optimized GeoTIFF）
# ============================================================

def read_cog(source: str, max_size: int = 2048) -> dict:
    """降采样读取 COG 预览。返回 {png_bytes, bounds(w,s,e,n), meta}"""
    try:
        import numpy as np
        import rasterio
        from rasterio.warp import transform_bounds
        from PIL import Image
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}，请安装 rasterio pillow numpy")

    src_path = _as_vsi_path(source)
    ds = None
    downloaded_path = None
    try:
        try:
            ds = rasterio.open(src_path)
        except Exception as e:
            if _is_http(source) and _needs_gdal_download_fallback(e):
                downloaded_path = http_download_to_temp(str(source).strip(), "tif")
                src_path = downloaded_path
                ds = rasterio.open(src_path)
            else:
                raise
        with ds:
            width, height = ds.width, ds.height
            scale = max(1, math.ceil(max(width, height) / max(256, int(max_size))))
            out_w = max(1, width // scale)
            out_h = max(1, height // scale)
            count = ds.count

            if count >= 3:
                bands = [ds.read(i, out_shape=(out_h, out_w)).astype("float64") for i in (1, 2, 3)]
            else:
                b = ds.read(1, out_shape=(out_h, out_w)).astype("float64")
                bands = [b, b, b]

            nodata = ds.nodata
            if nodata is not None:
                mask = np.zeros_like(bands[0], dtype=bool)
                for b in bands:
                    mask |= np.isclose(b, nodata)
            else:
                mask = ~np.isfinite(bands[0])
                for b in bands[1:]:
                    mask |= ~np.isfinite(b)

            rgb = []
            for b in bands:
                valid = np.isfinite(b) & ~mask
                if valid.any():
                    lo, hi = np.percentile(b[valid], 2), np.percentile(b[valid], 98)
                    if hi <= lo:
                        hi = lo + 1.0
                    b = np.clip((b - lo) / (hi - lo), 0, 1)
                b = np.where(valid, b, 0)
                rgb.append((b * 255).astype("uint8"))
            png_image = Image.fromarray(np.stack(rgb, axis=-1))

            if ds.crs and ds.crs.to_string() != "EPSG:4326":
                bounds = list(transform_bounds(ds.crs, "EPSG:4326", *ds.bounds))
            else:
                bounds = [ds.bounds.left, ds.bounds.bottom, ds.bounds.right, ds.bounds.top]

            meta = {
                "width": width,
                "height": height,
                "count": count,
                "dtypes": list(ds.dtypes)[:6],
                "crs": ds.crs.to_string() if ds.crs else "未知",
                "nodata": nodata,
                "bounds_wgs84": [round(v, 6) for v in bounds],
                "resampled": [out_w, out_h],
                "compression": ds.compression.value if ds.compression else None,
                "is_tiled": bool(ds.profile.get("tiled", False)),
            }
    except CloudNativeError:
        raise
    except Exception as e:
        raise CloudNativeError(f"COG 读取失败: {str(e)[:300]}")
    finally:
        _remove_temp_download(downloaded_path)

    buf = io.BytesIO()
    png_image.save(buf, format="PNG")
    return {"png_bytes": buf.getvalue(), "bounds": bounds, "meta": meta}


def cog_info(source: str) -> dict:
    """COG/GeoTIFF 元信息：CRS/范围/波段/统计（统计基于降采样，避免全量下载）"""
    try:
        import numpy as np
        import rasterio
        from rasterio.warp import transform_bounds
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}")

    src_path = _as_vsi_path(source)
    ds = None
    downloaded_path = None
    try:
        try:
            ds = rasterio.open(src_path)
        except Exception as e:
            if _is_http(source) and _needs_gdal_download_fallback(e):
                downloaded_path = http_download_to_temp(str(source).strip(), "tif")
                src_path = downloaded_path
                ds = rasterio.open(src_path)
            else:
                raise
        with ds:
            scale = max(1, math.ceil(max(ds.width, ds.height) / 1024))
            out_h, out_w = max(1, ds.height // scale), max(1, ds.width // scale)
            stats = []
            for i in range(1, min(ds.count, 6) + 1):
                b = ds.read(i, out_shape=(out_h, out_w)).astype("float64")
                valid = np.isfinite(b)
                if ds.nodata is not None:
                    valid &= ~np.isclose(b, ds.nodata)
                if valid.any():
                    stats.append({
                        "band": i, "min": round(float(b[valid].min()), 4),
                        "max": round(float(b[valid].max()), 4),
                        "mean": round(float(b[valid].mean()), 4),
                    })
                else:
                    stats.append({"band": i, "min": None, "max": None, "mean": None})
            if ds.crs and ds.crs.to_string() != "EPSG:4326":
                bounds = list(transform_bounds(ds.crs, "EPSG:4326", *ds.bounds))
            else:
                bounds = [ds.bounds.left, ds.bounds.bottom, ds.bounds.right, ds.bounds.top]
            return {
                "crs": ds.crs.to_string() if ds.crs else "未知",
                "bounds_wgs84": [round(v, 6) for v in bounds],
                "bounds_native": [round(v, 4) for v in list(ds.bounds)],
                "width": ds.width, "height": ds.height,
                "count": ds.count,
                "dtypes": list(ds.dtypes)[:6],
                "nodata": ds.nodata,
                "stats_sampled": stats,
                "is_tiled": bool(ds.profile.get("tiled", False)),
                "compression": ds.compression.value if ds.compression else None,
            }
    except CloudNativeError:
        raise
    except Exception as e:
        raise CloudNativeError(f"COG 元信息读取失败: {str(e)[:300]}")
    finally:
        _remove_temp_download(downloaded_path)


# ============================================================
# PMTiles
# ============================================================

class _HttpRangeSource:
    """PMTiles HTTP Range 读取器（按需读块，不整体下载）"""

    def __init__(self, url: str):
        self.url = url.strip()

    def get_bytes(self, start: int, length: int) -> bytes:
        if (isinstance(start, bool) or not isinstance(start, int) or start < 0
                or isinstance(length, bool) or not isinstance(length, int) or length <= 0):
            raise CloudNativeError("PMTiles Range 参数无效")
        req = urllib.request.Request(
            self.url,
            headers={
                "Range": f"bytes={start}-{start + length - 1}",
                "Accept-Encoding": "identity",
                "User-Agent": "Gis-WorkTable/1.0",
            },
        )
        proxies = get_effective_proxies()
        handler = urllib.request.ProxyHandler(proxies) if proxies else urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        try:
            with opener.open(req, timeout=30) as resp:
                if getattr(resp, "status", None) != 206:
                    raise CloudNativeError("PMTiles 服务器未返回 HTTP 206 Range 分段响应")
                content_range = resp.headers.get("Content-Range", "")
                try:
                    unit, span = content_range.split(" ", 1)
                    byte_span, _total = span.split("/", 1)
                    first, last = (int(value) for value in byte_span.split("-", 1))
                except (ValueError, AttributeError):
                    raise CloudNativeError("PMTiles Range 响应缺少有效的 Content-Range")
                if unit.lower() != "bytes" or first != start or last < first or last - first + 1 > length:
                    raise CloudNativeError("PMTiles Range 响应范围与请求不匹配")
                data = resp.read(length + 1)
                if len(data) != last - first + 1:
                    raise CloudNativeError("PMTiles Range 响应长度与 Content-Range 不匹配")
                return data
        except CloudNativeError:
            raise
        except Exception as e:
            raise CloudNativeError(f"PMTiles 远程读取失败（Range 请求）: {str(e)[:200]}")


def _pmtiles_open(source: str):
    """打开 PMTiles：本地文件走 mmap，URL 走 HTTP Range。返回 (Reader, header, file_handle)"""
    try:
        from pmtiles.reader import Reader, MmapSource
        from pmtiles.tile import deserialize_header
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}，请安装 pmtiles")

    s = str(source).strip()
    f = None  # URL 分支无文件句柄；本地分支持有 mmap 源的文件句柄
    try:
        if _is_http(s):
            reader = Reader(_HttpRangeSource(s).get_bytes)
        else:
            if not os.path.exists(s):
                raise CloudNativeError(f"文件不存在: {s}")
            f = open(s, "rb")
            reader = Reader(MmapSource(f))
        header = deserialize_header(reader.get_bytes(0, 16384))
    except CloudNativeError:
        if f is not None:
            f.close()
        raise
    except Exception as e:
        if f is not None:
            f.close()
        raise CloudNativeError(f"PMTiles 打开失败: {str(e)[:300]}")
    return reader, header, f


@contextmanager
def _pmtiles_reader(source: str):
    """PMTiles Reader 上下文管理器：确保本地文件句柄用后关闭。"""
    reader, header, fh = _pmtiles_open(source)
    try:
        yield reader, header
    finally:
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass


def pmtiles_header(source: str) -> dict:
    """读取 PMTiles header 的独立副本，不向调用方暴露文件句柄生命周期。"""
    with _pmtiles_reader(source) as (_, header):
        return dict(header)

def pmtiles_header_summary(header: dict) -> dict:
    e7 = 1e7
    return {
        "tile_type": str(header.get("tile_type")),
        "min_zoom": header.get("min_zoom"),
        "max_zoom": header.get("max_zoom"),
        "bounds_wgs84": [
            round(header.get("min_lon_e7", 0) / e7, 6),
            round(header.get("min_lat_e7", 0) / e7, 6),
            round(header.get("max_lon_e7", 0) / e7, 6),
            round(header.get("max_lat_e7", 0) / e7, 6),
        ],
        "center": [
            round(header.get("center_lon_e7", 0) / e7, 6),
            round(header.get("center_lat_e7", 0) / e7, 6),
            header.get("center_zoom", 0),
        ],
        "addressed_tiles": header.get("addressed_tiles_count", 0),
    }


def _sampling_zoom(summary: dict, preferred: int) -> int:
    try:
        min_zoom = int(summary["min_zoom"]) if summary.get("min_zoom") is not None else 0
        max_zoom = int(summary["max_zoom"]) if summary.get("max_zoom") is not None else 30
    except (TypeError, ValueError, OverflowError) as e:
        raise CloudNativeError("PMTiles header 中的 zoom 范围无效") from e
    if not 0 <= min_zoom <= max_zoom <= 30:
        raise CloudNativeError("PMTiles header 中的 zoom 范围超出 0 到 30")
    return max(min_zoom, min(max_zoom, preferred))


def pmtiles_info(source: str) -> dict:
    """PMTiles 元信息（只读 header + metadata，不读瓦片）"""
    with _pmtiles_reader(source) as (reader, header):
        info = pmtiles_header_summary(header)
        try:
            raw_meta = reader.metadata()
            if isinstance(raw_meta, bytes):
                raw_meta = json.loads(gzip.decompress(raw_meta) if raw_meta[:2] == b"\x1f\x8b" else raw_meta)
            if isinstance(raw_meta, dict):
                info["vector_layers"] = [
                    {"name": l.get("id") or l.get("name"), "fields": list((l.get("fields") or {}).keys())[:15]}
                    for l in (raw_meta.get("vector_layers") or [])[:8]
                ]
        except CloudNativeError:
            raise
        except Exception:
            pass
        return info


def _deg2tile(lon: float, lat: float, z: int):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def _mvt_decode_tile(tile_bytes: bytes, tile_compression, z: int, x: int, y: int) -> list:
    """解码一块 MVT → [(shapely geom(WGS84), properties, layer_name)]"""
    try:
        import numpy as np
        import mapbox_vector_tile
        from shapely.ops import transform as shp_transform
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}，请安装 mapbox-vector-tile numpy")

    tc = tile_compression
    comp = int(tc.value) if hasattr(tc, "value") else (int(tc) if tc is not None else 0)
    if comp == 2:  # GZIP
        tile_bytes = gzip.decompress(tile_bytes)
    elif comp == 3:
        raise CloudNativeError("PMTiles 使用 Brotli 压缩，请先安装 brotli 支持")
    try:
        decoded = mapbox_vector_tile.decode(tile_bytes)
    except Exception as e:
        raise CloudNativeError(f"MVT 解码失败: {str(e)[:200]}")

    n = 2 ** z

    def _make_transformer(extent):
        def fn(xx, yy):
            xx = np.asarray(xx, dtype="float64")
            yy = np.asarray(yy, dtype="float64")
            lon = 360.0 * ((x + xx / extent) / n) - 180.0
            lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * (y + yy / extent) / n))))
            return lon, lat
        return fn

    from shapely.geometry import shape as shp_shape

    features = []
    for layer_name, layer in decoded.items():
        extent = layer.get("extent", 4096) or 4096
        transformer = _make_transformer(extent)
        for f in layer.get("features", []):
            geom = f.get("geometry")
            props = f.get("properties", {}) or {}
            if geom is None:
                continue
            try:
                # mapbox_vector_tile 返回 GeoJSON 风格 dict；兼容 shapely 对象
                if isinstance(geom, dict):
                    geom = shp_shape(geom)
                if geom.is_empty:
                    continue
                geom_wgs = shp_transform(transformer, geom)
            except Exception:
                continue
            features.append((geom_wgs, props, layer_name))
    return features


def _geom_to_feature(geom, props):
    """shapely geom → GeoJSON Feature dict（属性值一律转字符串安全类型）"""
    safe_props = {}
    for k, v in (props or {}).items():
        try:
            json.dumps(v)
            safe_props[k] = v
        except Exception:
            safe_props[k] = str(v)
    return {"type": "Feature", "geometry": geom.__geo_interface__, "properties": safe_props}


def pmtiles_vector_to_geojson(source: str, max_features: int = 5000,
                              max_tiles: int = 16) -> tuple:
    """矢量 PMTiles → GeoJSON FeatureCollection。

    以数据中心所在瓦片为起点，同层螺旋扩圈取最多 max_tiles 块瓦片，
    解码 MVT 并转为 WGS84 GeoJSON。返回 (geojson, info)。
    """
    if isinstance(max_features, bool) or not isinstance(max_features, int) or max_features <= 0:
        raise CloudNativeError("max_features 必须是正整数")
    if isinstance(max_tiles, bool) or not isinstance(max_tiles, int) or max_tiles <= 0:
        raise CloudNativeError("max_tiles 必须是正整数")
    max_features = min(max_features, 50_000)
    max_tiles = min(max_tiles, 256)
    with _pmtiles_reader(source) as (reader, header):
        if int(header.get("tile_type", 0).value if hasattr(header.get("tile_type", 0), "value") else header.get("tile_type", 0)) != 1:  # TileType.MVT
            raise CloudNativeError(
                f"该 PMTiles 不是矢量瓦片（tile_type={header.get('tile_type')}），"
                "当前工具仅支持 MVT 矢量类型")

        summary = pmtiles_header_summary(header)
        lon_c, lat_c = summary["center"][0], summary["center"][1]
        z = _sampling_zoom(summary, 10)
        cx, cy = _deg2tile(lon_c, lat_c, z)

        collected = []
        seen_layers = set()
        seen_tiles = set()
        attempted_tiles = 0
        n = 2 ** z

        # 螺旋扩圈：先中心，再 1 圈、2 圈……（Chebyshev 距离）
        candidates = [(0, 0)]
        for radius in range(1, 8):
            candidates.extend([(dx, dy) for dx in range(-radius, radius + 1)
                               for dy in range(-radius, radius + 1)
                               if max(abs(dx), abs(dy)) == radius])

        for dx, dy in candidates:
            if len(collected) >= max_features or attempted_tiles >= max_tiles:
                break
            tx, ty = cx + dx, cy + dy
            if tx < 0 or ty < 0 or tx >= n or ty >= n:
                continue
            if (tx, ty) in seen_tiles:
                continue
            attempted_tiles += 1
            try:
                tile_bytes = reader.get(z, tx, ty)
            except CloudNativeError:
                raise
            except Exception:
                continue
            if not tile_bytes:
                continue
            seen_tiles.add((tx, ty))
            feats = _mvt_decode_tile(tile_bytes, header.get("tile_compression"), z, tx, ty)
            for geom, props, lname in feats:
                seen_layers.add(lname)
                collected.append(_geom_to_feature(geom, props))
                if len(collected) >= max_features:
                    break

        if not collected:
            raise CloudNativeError(
                f"在数据中心附近的 z={z} 级瓦片中未解出要素（该数据集此级别可能无数据），"
                "可尝试其他数据源或更高 zoom 的数据集")
        geojson = {"type": "FeatureCollection", "features": collected}
        info = dict(summary)
        info["zoom_sampled"] = z
        info["tiles_sampled"] = len(seen_tiles)
        info["feature_count"] = len(collected)
        info["layers"] = sorted(seen_layers)
        return geojson, info


def pmtiles_raster_tile_bounds(source: str):
    """取栅格 PMTiles 中心瓦片，返回 (bytes, bounds, fmt, header_summary)。"""
    with _pmtiles_reader(source) as (reader, header):
        ttype = header.get("tile_type", 0)
        ttype = int(ttype.value) if hasattr(ttype, "value") else int(ttype)
        if ttype not in (2, 3, 4, 5):  # PNG/JPEG/WEBP/AVIF
            raise CloudNativeError(f"该 PMTiles 不是栅格瓦片（tile_type={header.get('tile_type')}）")
        summary = pmtiles_header_summary(header)
        lon_c, lat_c = summary["center"][0], summary["center"][1]
        z = _sampling_zoom(summary, 12)
        x, y = _deg2tile(lon_c, lat_c, z)
        tile_bytes = reader.get(z, x, y)
        if not tile_bytes:
            raise CloudNativeError("中心瓦片为空")
        fmt = {2: "png", 3: "jpeg", 4: "webp", 5: "avif"}[ttype]
        return tile_bytes, list(_tile_bounds(z, x, y)), fmt, summary


def _tile_bounds(z: int, x: int, y: int):
    """Web Mercator 瓦片 → WGS84 边界 (w, s, e, n)"""
    n = 2 ** z
    w = 360.0 * x / n - 180.0
    e = 360.0 * (x + 1) / n - 180.0
    lat_rad_n = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_rad_s = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
    return (w, math.degrees(lat_rad_s), e, math.degrees(lat_rad_n))


# ============================================================
# GeoParquet / FlatGeobuf（pyogrio 通道）
# ============================================================

_CLOUD_VECTOR_LIMIT_DEFAULT = 50000


def _bbox_to_source_crs(bbox, source_crs):
    """把公开接口的 WGS84 bbox 转为数据源 CRS，供 GDAL/GeoParquet 过滤使用。"""
    if bbox is None:
        return None
    if not source_crs or str(source_crs).strip().lower() in {"未知", "unknown", "none"}:
        raise CloudNativeError("数据源未声明坐标系，无法安全应用 WGS84 bbox 过滤")
    try:
        from pyproj import CRS, Transformer
        transformer = Transformer.from_crs(
            CRS.from_epsg(4326), CRS.from_user_input(source_crs), always_xy=True
        )
        return transformer.transform_bounds(*bbox, densify_pts=21)
    except Exception as e:
        raise CloudNativeError(f"bbox 转换到数据源坐标系失败: {str(e)[:250]}") from e


def _gdal_has_parquet_driver() -> bool:
    try:
        import pyogrio
        return "Parquet" in pyogrio.list_drivers()
    except Exception:
        return False


def _geoparquet_local_path(source: str) -> str:
    """GeoParquet 数据源解析：GDAL 无 Parquet 驱动的环境（如部分 pyogrio wheel）
    走 geopandas+pyarrow 通道，远程文件先回退下载到临时文件"""
    s = str(source).strip()
    if _is_http(s):
        return http_download_to_temp(s, "parquet")
    if not os.path.exists(s):
        raise CloudNativeError(f"文件不存在: {s}")
    return s


def cloud_vector_metadata(source: str, fmt: str) -> dict:
    """先读 metadata：要素数 / CRS / 几何类型 / 字段，供大文件提示与 BBOX 过滤决策"""
    if fmt == "GeoParquet" and not _gdal_has_parquet_driver():
        return _geoparquet_metadata_pyarrow(source)
    try:
        import pyogrio
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}，请安装 pyogrio")
    src_path = resolve_vector_source(source, fmt)
    with _managed_temp_download(src_path):
        return _cloud_vector_metadata_from_path(src_path, fmt, pyogrio)


def _cloud_vector_metadata_from_path(src_path: str, fmt: str, pyogrio) -> dict:
    try:
        info = pyogrio.read_info(src_path)
    except CloudNativeError:
        raise
    except Exception as e:
        raise CloudNativeError(f"{fmt} 元信息读取失败: {str(e)[:300]}")
    fields = info.get("fields")
    fields = [str(f) for f in (fields.tolist() if hasattr(fields, "tolist") else list(fields or []))][:20]
    bbox = info.get("bbox")
    return {
        "features": int(info.get("features") or 0),
        "crs": str(info.get("crs") or "未知")[:80],
        "geometry_type": str(info.get("geometry_type") or "未知"),
        "fields": fields,
        "bbox_native": [round(float(v), 6) for v in bbox] if bbox is not None else None,
    }


def _geoparquet_metadata_pyarrow(source: str) -> dict:
    """GeoParquet 元信息（pyarrow 通道）：行数 + GeoParquet 列元数据"""
    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}，请安装 pyarrow")
    path = _geoparquet_local_path(source)
    with _managed_temp_download(path):
        return _geoparquet_metadata_pyarrow_from_path(path)


def _geoparquet_metadata_pyarrow_from_path(path: str) -> dict:
    try:
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(path)
        num_rows = int(pf.metadata.num_rows)
        geo = {}
        meta = pf.schema_arrow.metadata or {}
        raw = meta.get(b"geo")
        if raw:
            geo = json.loads(raw.decode("utf-8"))
        primary = geo.get("primary_column", "geometry")
        column_meta = geo.get("columns", {}).get(primary, {})
        crs = column_meta.get("crs")
        if isinstance(crs, dict):
            crs = json.dumps(crs)
        fields = [f for f in pf.schema_arrow.names if f != primary][:20]
        return {
            "features": num_rows,
            "crs": str(crs or "未知"),
            "geometry_type": str(column_meta.get("geometry_type") or "未知"),
            "fields": fields,
            "bbox_native": column_meta.get("bbox"),
            "engine": "pyarrow",
        }
    except CloudNativeError:
        raise
    except Exception as e:
        raise CloudNativeError(f"GeoParquet 元信息读取失败: {str(e)[:300]}")


def cloud_vector_to_geojson(source: str, fmt: str, bbox=None, limit: int = 0) -> tuple:
    """GeoParquet / FlatGeobuf → GeoJSON。bbox=(minx,miny,maxx,maxy) 为 WGS84 过滤。

    返回 (geojson, meta)。要素数超过 limit 且未给 bbox 时抛 CloudNativeError（带提示）。
    """
    if fmt == "GeoParquet" and not _gdal_has_parquet_driver():
        return _geoparquet_to_geojson_pyarrow(source, bbox=bbox, limit=limit)

    try:
        import pyogrio
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}，请安装 pyogrio")
    src_path = resolve_vector_source(source, fmt)
    with _managed_temp_download(src_path):
        return _cloud_vector_to_geojson_from_path(src_path, fmt, bbox, limit, pyogrio)


def _cloud_vector_to_geojson_from_path(src_path: str, fmt: str, bbox, limit: int, pyogrio) -> tuple:
    meta = _cloud_vector_metadata_from_path(src_path, fmt, pyogrio)
    total = meta["features"]

    if limit and limit > 0:
        max_features = min(int(limit), _CLOUD_VECTOR_LIMIT_DEFAULT)
    else:
        max_features = _CLOUD_VECTOR_LIMIT_DEFAULT

    # 用户显式传了 limit = 主动截断；未传 limit 超上限才拒绝并提示
    explicit_limit = limit and 0 < int(limit) <= _CLOUD_VECTOR_LIMIT_DEFAULT
    if total > max_features and bbox is None and not explicit_limit:
        raise CloudNativeError(
            f"该 {fmt} 共 {total} 个要素，超过单次加载上限 {max_features}。"
            "请带 bbox 参数做空间过滤（minx,miny,maxx,maxy），或显式传较小的 limit")

    kwargs = {}
    if bbox is not None:
        kwargs["bbox"] = _bbox_to_source_crs(bbox, meta.get("crs"))
    if max_features:
        kwargs["max_features"] = max_features
    try:
        gdf = pyogrio.read_dataframe(src_path, **kwargs)
    except CloudNativeError:
        raise
    except Exception as e:
        raise CloudNativeError(f"{fmt} 读取失败: {str(e)[:300]}")
    return _gdf_to_geojson_result(gdf, meta, fmt, bbox)


def _geoparquet_to_geojson_pyarrow(source: str, bbox=None, limit: int = 0) -> tuple:
    """GeoParquet → GeoJSON（geopandas+pyarrow 通道，GDAL 无 Parquet 驱动时的回退）"""
    try:
        import geopandas as gpd
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}，请安装 geopandas pyarrow")
    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError as e:
        raise CloudNativeError(f"缺少依赖: {e}，请安装 geopandas pyarrow")

    path = _geoparquet_local_path(source)
    with _managed_temp_download(path):
        return _geoparquet_to_geojson_pyarrow_from_path(path, bbox, limit, gpd)


def _geoparquet_to_geojson_pyarrow_from_path(path: str, bbox, limit: int, gpd) -> tuple:
    meta = _geoparquet_metadata_pyarrow_from_path(path)
    total = meta["features"]

    if limit and limit > 0:
        max_features = min(int(limit), _CLOUD_VECTOR_LIMIT_DEFAULT)
    else:
        max_features = _CLOUD_VECTOR_LIMIT_DEFAULT

    explicit_limit = limit and 0 < int(limit) <= _CLOUD_VECTOR_LIMIT_DEFAULT
    if total > max_features and bbox is None and not explicit_limit:
        raise CloudNativeError(
            f"该 GeoParquet 共 {total} 个要素，超过单次加载上限 {max_features}。"
            "请带 bbox 参数做空间过滤（minx,miny,maxx,maxy），或显式传较小的 limit")

    if total > max_features:
        gdf = _read_geoparquet_batches(path, bbox, meta, max_features, gpd)
    else:
        kwargs = {}
        if bbox is not None:
            kwargs["bbox"] = _bbox_to_source_crs(bbox, meta.get("crs"))
        try:
            gdf = gpd.read_parquet(path, **kwargs)
        except CloudNativeError:
            raise
        except Exception as e:
            raise CloudNativeError(f"GeoParquet 读取失败: {str(e)[:300]}")
    return _gdf_to_geojson_result(gdf, meta, "GeoParquet", bbox)


def _read_geoparquet_batches(path: str, bbox, meta: dict, limit: int, gpd):
    """按批读取 GeoParquet WKB 几何，限制峰值内存和返回要素数。"""
    try:
        import pandas as pd
        import pyarrow.parquet as pq
        from shapely.geometry import box

        parquet = pq.ParquetFile(path)
        raw_geo = (parquet.schema_arrow.metadata or {}).get(b"geo")
        geo = json.loads(raw_geo.decode("utf-8")) if raw_geo else {}
        primary = geo.get("primary_column", "geometry")
        column_meta = geo.get("columns", {}).get(primary, {})
        if (column_meta.get("encoding") or "WKB").upper() != "WKB":
            raise CloudNativeError("GeoParquet 几何编码不是 WKB，当前无法安全分批读取。")
        if primary not in parquet.schema_arrow.names:
            raise CloudNativeError("GeoParquet 缺少主几何列，无法分批读取。")

        crs = meta.get("crs")
        if crs == "未知":
            crs = None
        source_bounds = _bbox_to_source_crs(bbox, crs) if bbox is not None else None
        query_geometry = box(*source_bounds) if source_bounds is not None else None
        frames = []
        remaining = limit
        for batch in parquet.iter_batches(batch_size=min(max(1, limit), 4096)):
            frame = batch.to_pandas()
            geometry_wkb = frame.pop(primary)
            geometry = gpd.GeoSeries.from_wkb(geometry_wkb, crs=crs).rename("geometry")
            part = gpd.GeoDataFrame(frame, geometry=geometry, crs=crs)
            if query_geometry is not None:
                intersects = part.geometry.notna() & part.geometry.intersects(query_geometry)
                part = part.loc[intersects]
            if len(part) > remaining:
                part = part.head(remaining)
            if not part.empty:
                frames.append(part)
                remaining -= len(part)
            if remaining <= 0:
                break

        if not frames:
            return gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs=crs), crs=crs)
        return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=crs)
    except CloudNativeError:
        raise
    except Exception as e:
        raise CloudNativeError(f"GeoParquet 分批读取失败: {str(e)[:300]}") from e


def _gdf_to_geojson_result(gdf, meta: dict, fmt: str, bbox) -> tuple:
    """GeoDataFrame → (GeoJSON, meta)：序列化 + 非 4326 重投影 + 统计回填"""
    if gdf is None or len(gdf) == 0:
        raise CloudNativeError(f"{fmt} 未读出要素（bbox 过滤后可能为空）")

    try:
        geojson = json.loads(gdf.to_json(na="null", show_bbox=False))
    except Exception:
        geojson = json.loads(gdf.to_json())

    meta = dict(meta)
    meta["loaded_features"] = len(gdf)
    meta["bbox_filtered"] = list(bbox) if bbox else None
    meta["geometry_reprojected"] = False
    # GeoParquet/FGB 可能不是 4326：非 4326 时重投影，保证上图正确
    try:
        crs = gdf.crs
        if crs is None:
            raise CloudNativeError(f"{fmt} 未声明坐标系，无法安全转换为 WGS84")
        if crs.to_epsg() != 4326:
            gdf4326 = gdf.to_crs(4326)
            geojson = json.loads(gdf4326.to_json(na="null", show_bbox=False))
            meta["geometry_reprojected"] = True
            meta["crs"] = str(crs.to_string())
    except CloudNativeError:
        raise
    except Exception as e:
        raise CloudNativeError(f"{fmt} 坐标系转换到 WGS84 失败: {str(e)[:250]}") from e
    return geojson, meta
