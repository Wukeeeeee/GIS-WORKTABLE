"""GIS 文件落盘 + 完整性校验 + CRS 保留 + metadata 保存。

这是"数据导入（Data Import）"的确定性层：
  1. 只允许白名单格式（GeoJSON / GPKG / SHP / GeoTIFF）；
  2. 矢量统一保留 CRS（geopandas 写 GPKG/SHP 会写 .prj / 内嵌 CRS）；
  3. 写入前做基本完整性校验，CRS 未知的数据拒绝落盘；
  4. 落盘后回读校验，并生成 sidecar metadata（来源/名称/时间/格式/CRS…）；
  5. 对未知格式 / 未知来源 / 空数据一律明确报错，不直接加载到地图。
"""

from __future__ import annotations

import datetime
import json
import math
import numbers
import os
import shutil
import tempfile
import threading
from typing import Optional

from backend.services.ai_service import _TEMP_OUTPUT_DIR
from backend.services.data_providers.errors import DataValidationError, DownloadError
from backend.services.data_providers.models import (
    ALLOWED_FORMAT_EXTS,
    sanitize_name,
)

# 已知几何类型白名单（GeoJSON 规范）
_ALLOWED_GEOM = {
    "Point", "MultiPoint", "LineString", "MultiLineString",
    "Polygon", "MultiPolygon", "GeometryCollection",
}
_CATALOG_LOCK = threading.RLock()

# 数据缓存根目录：/output 静态目录下的 data/<provider>/
def data_root() -> str:
    root = os.path.join(_TEMP_OUTPUT_DIR, "data")
    os.makedirs(root, exist_ok=True)
    return root


def asset_dir(provider_id: str) -> str:
    d = os.path.join(data_root(), sanitize_name(provider_id))
    os.makedirs(d, exist_ok=True)
    return d


def to_download_url(abs_path: str) -> str:
    """把落盘绝对路径转成前端可访问的相对 URL（/output/...）。"""
    try:
        rel = os.path.relpath(abs_path, _TEMP_OUTPUT_DIR)
    except ValueError:
        rel = os.path.basename(abs_path)
    return "/" + rel.replace("\\", "/")


# ============================================================
# 矢量 GeoJSON 校验 / 归一化
# ============================================================

def _geom_types(fc: dict) -> list:
    types = set()
    for f in fc.get("features", []):
        g = (f.get("geometry") or {}).get("type")
        if g:
            types.add(g)
    return sorted(types)


def _compute_bbox(fc: dict) -> Optional[list]:
    """计算 [minLng, minLat, maxLng, maxLat]，空返回 None。"""
    xs, ys = [], []
    for f in fc.get("features", []):
        g = f.get("geometry")
        if not g:
            continue
        for c in _iter_coords(g):
            if len(c) >= 2:
                xs.append(c[0]); ys.append(c[1])
    if not xs or not ys:
        return None
    return [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)]


def _iter_coords(g: dict):
    t = g.get("type")
    c = g.get("coordinates") or []
    if t == "Point":
        yield c
    elif t in ("MultiPoint", "LineString"):
        for p in c:
            yield p
    elif t in ("MultiLineString", "Polygon"):
        for ring in c:
            if t == "Polygon" and isinstance(ring, list) and ring and isinstance(ring[0], (int, float)):
                yield ring
            else:
                for p in ring:
                    yield p
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                for p in ring:
                    yield p
    elif t == "GeometryCollection":
        for sub in g.get("geometries", []):
            for p in _iter_coords(sub):
                yield p


def normalize_featurecollection(geojson: dict) -> dict:
    """把 Feature / Geometry / 裸几何归一化为 FeatureCollection。"""
    if not isinstance(geojson, dict):
        raise DataValidationError("数据不是有效的 GeoJSON 对象。")
    t = geojson.get("type")
    if t == "FeatureCollection":
        features = geojson.get("features")
        if not isinstance(features, list) or any(not isinstance(feature, dict) for feature in features):
            raise DataValidationError("FeatureCollection.features 必须是要素对象列表。")
        return {"type": "FeatureCollection", "features": list(features)}
    if t == "Feature":
        if not isinstance(geojson.get("geometry"), (dict, type(None))):
            raise DataValidationError("Feature.geometry 必须是几何对象或 null。")
        if geojson.get("properties") is not None and not isinstance(geojson.get("properties"), dict):
            raise DataValidationError("Feature.properties 必须是对象或 null。")
        return {"type": "FeatureCollection", "features": [geojson]}
    if isinstance(t, str) and t in _ALLOWED_GEOM:
        return {"type": "FeatureCollection",
                "features": [{"type": "Feature", "geometry": geojson, "properties": {}}]}
    raise DataValidationError(f"数据格式未知（GeoJSON type={t}），已拒绝加载。")


def _valid_geometry(geometry: dict) -> bool:
    if not isinstance(geometry, dict):
        return False
    kind = geometry.get("type")
    if not isinstance(kind, str) or kind not in _ALLOWED_GEOM:
        return False
    def valid_position(position) -> bool:
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            return False
        for value in position:
            if not isinstance(value, numbers.Real) or isinstance(value, bool):
                return False
            try:
                if not math.isfinite(float(value)):
                    return False
            except (OverflowError, TypeError, ValueError):
                return False
        return True

    def valid_line(line, minimum=2) -> bool:
        return isinstance(line, (list, tuple)) and len(line) >= minimum and all(valid_position(p) for p in line)

    def valid_ring(ring) -> bool:
        return valid_line(ring, minimum=4) and tuple(ring[0]) == tuple(ring[-1])

    coordinates = geometry.get("coordinates")
    if kind == "GeometryCollection":
        children = geometry.get("geometries")
        return isinstance(children, list) and bool(children) and all(_valid_geometry(child) for child in children)
    if kind == "Point":
        return valid_position(coordinates)
    if kind == "MultiPoint":
        return isinstance(coordinates, (list, tuple)) and bool(coordinates) and all(valid_position(p) for p in coordinates)
    if kind == "LineString":
        return valid_line(coordinates)
    if kind == "MultiLineString":
        return isinstance(coordinates, (list, tuple)) and bool(coordinates) and all(valid_line(line) for line in coordinates)
    if kind == "Polygon":
        return isinstance(coordinates, (list, tuple)) and bool(coordinates) and all(valid_ring(ring) for ring in coordinates)
    return (isinstance(coordinates, (list, tuple)) and bool(coordinates)
            and all(isinstance(polygon, (list, tuple)) and bool(polygon)
                    and all(valid_ring(ring) for ring in polygon) for polygon in coordinates))


def validate_vector(geojson: dict, *, provider: str = "", crs: str = "",
                    crs_known: bool = True, max_features: int = 0) -> dict:
    """矢量完整性/安全校验，返回归一化 FeatureCollection。

    校验不通过抛 DataValidationError（明确失败，禁止静默）。
    """
    fc = normalize_featurecollection(geojson)
    features = fc.get("features", [])

    if not features:
        raise DataValidationError(
            f"数据源返回 0 个要素（{provider or '未知来源'}），未生成有效图层。",
            provider=provider,
            hint="无结果，建议扩大范围或更换要素类型。",
        )

    # 未知 CRS 不得落盘/加载（要求：不允许把未知来源/未知 CRS 数据直接加载）
    if not crs_known or not crs:
        raise DataValidationError(
            "数据缺少 CRS（坐标系）信息，无法确认其空间参考，已拒绝加载。",
            provider=provider,
            hint="请改用声明了 CRS 的数据源，或先完成坐标定义。",
        )

    if max_features and len(features) > max_features:
        raise DataValidationError(
            f"要素数量 {len(features)} 超过单次获取上限 {max_features}，请缩小空间范围。",
            provider=provider,
        )

    # 检查几何类型白名单 + 至少一条含几何
    bad = 0
    has_geom = False
    for f in features:
        if not isinstance(f, dict) or f.get("type") != "Feature":
            bad += 1
            continue
        properties = f.get("properties")
        if properties is not None and not isinstance(properties, dict):
            bad += 1
            continue
        g = f.get("geometry")
        if g is None:
            continue
        if not _valid_geometry(g):
            bad += 1
            continue
        has_geom = True
    if not has_geom:
        raise DataValidationError("数据中没有任何有效几何，已拒绝加载。", provider=provider)
    if bad:
        raise DataValidationError(f"数据中有 {bad} 条要素的结构或几何无效，已拒绝加载。", provider=provider)
    return fc


# ============================================================
# 矢量写入 & 回读校验
# ============================================================

def _gdf_from_features(fc: dict, crs: str):
    import geopandas as gpd
    try:
        gdf = gpd.GeoDataFrame.from_features(fc["features"], crs=crs)
    except Exception as e:
        raise DataValidationError(f"数据无法转换为 GeoDataFrame：{e}", hint="几何可能不合法。") from e
    return gdf


def write_vector(geojson: dict, *, out_format: str, name: str, dirpath: str,
                 crs: str = "EPSG:4326", crs_known: bool = True) -> str:
    """校验并把矢量写入指定格式文件，返回绝对路径。

    支持 out_format: geojson / gpkg / shp。
    """
    out_format = out_format.lower().strip().lstrip(".")
    if out_format not in ("geojson", "gpkg", "shp"):
        raise DataValidationError(
            f"矢量导出格式不支持：{out_format}（仅 geojson / gpkg / shp）。",
            hint="未知格式不允许写入或加载。",
        )
    fc = validate_vector(geojson, crs=crs, crs_known=crs_known)
    ext = ALLOWED_FORMAT_EXTS[out_format]
    base = sanitize_name(name)
    path = os.path.join(dirpath, f"{base}{ext}")
    os.makedirs(dirpath, exist_ok=True)
    staging_dir = tempfile.mkdtemp(prefix=".vector-write-", dir=dirpath)
    staging_path = os.path.join(staging_dir, f"{base}{ext}")

    try:
        if out_format == "geojson":
            with open(staging_path, "w", encoding="utf-8") as f:
                json.dump(fc, f, ensure_ascii=False)
        else:
            gdf = _gdf_from_features(fc, crs)
            driver = "GPKG" if out_format == "gpkg" else "ESRI Shapefile"
            if out_format == "shp":
                # shapefile 字段名 ≤ 10，先截断，避免写失败
                _truncate_shapefile_columns(gdf)
            gdf.to_file(staging_path, driver=driver, encoding="utf-8")

        # 回读临时成果，校验通过后再替换正式文件，失败不会破坏上一次有效结果。
        _verify_vector_file(staging_path, out_format)
        if out_format == "shp":
            staged_names = {
                filename for filename in os.listdir(staging_dir)
                if filename.startswith(base + ".")
            }
            if not staged_names:
                raise DownloadError("Shapefile 写入未生成任何文件。")
            component_extensions = {
                ".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".fix", ".sbn", ".sbx",
            }
            previous_names = {
                filename for filename in os.listdir(dirpath)
                if filename.startswith(base + ".")
                and os.path.splitext(filename)[1].lower() in component_extensions
                and os.path.isfile(os.path.join(dirpath, filename))
            }
            backup_dir = tempfile.mkdtemp(prefix=".vector-backup-", dir=dirpath)
            preserve_backup = False
            try:
                for filename in previous_names:
                    shutil.copy2(os.path.join(dirpath, filename), os.path.join(backup_dir, filename))
                installed_names = []
                try:
                    for filename in sorted(staged_names):
                        os.replace(os.path.join(staging_dir, filename), os.path.join(dirpath, filename))
                        installed_names.append(filename)
                except Exception as exc:
                    rollback_errors = []
                    for filename in previous_names:
                        try:
                            shutil.copy2(os.path.join(backup_dir, filename), os.path.join(dirpath, filename))
                        except OSError as rollback_exc:
                            rollback_errors.append(rollback_exc)
                    for filename in set(installed_names) - previous_names:
                        try:
                            os.remove(os.path.join(dirpath, filename))
                        except FileNotFoundError:
                            pass
                        except OSError as rollback_exc:
                            rollback_errors.append(rollback_exc)
                    if rollback_errors:
                        preserve_backup = True
                        raise DownloadError(
                            "Shapefile 更新失败，旧数据未能完全恢复；恢复副本已保留在输出目录。"
                        ) from exc
                    raise DownloadError("Shapefile 更新失败，已恢复原有数据。") from exc

                for filename in previous_names - staged_names:
                    try:
                        os.remove(os.path.join(dirpath, filename))
                    except OSError:
                        pass
            finally:
                if not preserve_backup:
                    shutil.rmtree(backup_dir, ignore_errors=True)
        else:
            os.replace(staging_path, path)
        return path
    except (DataValidationError, DownloadError):
        raise
    except Exception as e:
        raise DownloadError(f"写入或校验 {out_format} 失败：{e}", hint="磁盘或驱动异常。") from e
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _truncate_shapefile_columns(gdf) -> None:
    import geopandas as gpd
    if not isinstance(gdf, gpd.GeoDataFrame):
        return
    columns = [col for col in gdf.columns if col != "geometry"]
    reserved = {str(col).casefold() for col in columns if len(str(col)) <= 10}
    used = set()
    short_seen = set()
    renames = {}
    for col in columns:
        original = str(col)
        if len(original) <= 10:
            new = original
            if new.casefold() not in short_seen:
                short_seen.add(new.casefold())
                used.add(new.casefold())
                continue
            reserved_names = reserved
        else:
            new = original[:10]
            reserved_names = reserved
        suffix_index = 1
        while new.casefold() in used or new.casefold() in reserved_names:
            suffix = f"_{suffix_index}"
            new = f"{original[:10 - len(suffix)]}{suffix}"
            suffix_index += 1
        used.add(new.casefold())
        renames[col] = new
    if renames:
        gdf.rename(columns=renames, inplace=True)


def _verify_vector_file(path: str, out_format: str) -> dict:
    """回读文件，确认可解析、非空、CRS 已保留。失败抛明确错误。"""
    if out_format == "geojson":
        with open(path, "r", encoding="utf-8") as f:
            try:
                fc = json.load(f)
            except (ValueError, UnicodeDecodeError) as e:
                raise DownloadError(f"GeoJSON 回读失败：文件损坏（{path}）") from e
        n = len(fc.get("features", []))
        if n == 0:
            raise DataValidationError("写入结果为空，已丢弃该文件。")
        return {"features": n, "crs_known": True}
    # gpkg / shp 用 geopandas 回读
    import geopandas as gpd
    try:
        gdf = gpd.read_file(path)
    except Exception as e:
        raise DownloadError(f"{out_format} 文件回读失败：{e}") from e
    if gdf.empty or len(gdf) == 0:
        raise DataValidationError(f"写入 {out_format} 后回读为空，已丢弃该文件。")
    crs_known = bool(gdf.crs)
    if not crs_known:
        raise DataValidationError(
            f"文件缺少 CRS（{out_format} 未写入坐标参考），已拒绝。",
            hint="CRS 保留失败，属存储层问题。",
        )
    return {"features": len(gdf), "crs_known": crs_known}


# ============================================================
# metadata
# ============================================================

def now_iso() -> str:
    # 供外部测试覆盖
    return datetime.datetime.now().isoformat(timespec="seconds")


def build_metadata(*, provider: str, provider_name: str, kind: str, area: str,
                   source_url: str, file_path: str, file_format: str, crs: str,
                   crs_known: bool, size_bytes: int, feature_count: Optional[int],
                   geometry_types: list, bbox: Optional[list], query: str = "",
                   auth: str = "", note: str = "") -> dict:
    """按需求保存 metadata：来源、数据名称、下载时间、格式、CRS 等。"""
    return {
        "provider": provider,
        "provider_name": provider_name,
        "kind": kind,
        "area": area,
        "query": query,
        "source": provider_name if not source_url else source_url,
        "source_url": source_url,
        "file_name": os.path.basename(file_path),
        "download_time": now_iso(),
        "file_format": file_format,
        "crs": crs,
        "crs_known": bool(crs_known),
        "size_bytes": int(size_bytes),
        "feature_count": feature_count,
        "geometry_types": geometry_types,
        "bbox": bbox,
        "auth": auth,
        "note": note,
        "created_by": "gis-data-provider",
    }


def save_metadata(metadata: dict, *, dirpath: str, name: str) -> str:
    """写 sidecar <name>.metadata.json，并追加到目录级 catalog.json。"""
    base = sanitize_name(name)
    meta_path = os.path.join(dirpath, f"{base}.metadata.json")
    metadata_file = os.path.basename(meta_path)
    os.makedirs(dirpath, exist_ok=True)
    with _CATALOG_LOCK:
        _write_json_atomic(meta_path, metadata)
        catalog = os.path.join(dirpath, "catalog.json")
        records = []
        if os.path.exists(catalog):
            try:
                with open(catalog, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                records = loaded if isinstance(loaded, list) else []
            except (ValueError, OSError):
                records = []
        records = [
            record for record in records
            if not (isinstance(record, dict)
                    and str(record.get("metadata_file", "")).casefold() == metadata_file.casefold())
        ]
        records.append({"metadata": metadata, "metadata_file": metadata_file})
        if len(records) > 200:
            records = records[-200:]
        _write_json_atomic(catalog, records)
    return meta_path


def _write_json_atomic(path: str, value) -> None:
    fd, temp_path = tempfile.mkstemp(prefix=".json-write-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


# 公有便捷包装（供 data_discovery 调用）
def geom_types_of(fc: dict) -> list:
    return _geom_types(fc)


def compute_bbox(fc: dict) -> Optional[list]:
    return _compute_bbox(fc)
