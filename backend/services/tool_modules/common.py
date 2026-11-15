"""
Gis-WorkTable Tool Modules — Common Stateless Utilities & Security Constants

This module provides pure, stateless helper functions for GeoJSON normalization,
bounding box computation, geometry validation, provenance sanitization, feature IDs,
and AST security validation for code execution sandboxing.

Architectural contract:
Layer 0 utility module. It must NEVER import `backend.services.tools` or any stateful registry.
"""

from __future__ import annotations

import ast
import datetime
import math
import re
from numbers import Real
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlsplit


# ============================================================
# 表达式 AST 白名单校验与安全常量
# ============================================================

_ALLOWED_OPS = {
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.And, ast.Or, ast.Not,
    ast.BitXor, ast.BitAnd, ast.BitOr,
}

_ALLOWED_AST_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name,
    ast.Constant, ast.List, ast.Tuple, ast.Attribute, ast.Compare,
    ast.IfExp, ast.Subscript, ast.Slice, ast.Dict, ast.BoolOp,
)

ALLOWED_IMPORTS = {
    'geopandas', 'shapely', 'numpy', 'pandas', 'matplotlib',
    'pyecharts', 'json', 'math', 're', 'datetime', 'io',
    'tempfile', 'pyproj', 'rasterio', 'osmnx',
}

BANNED_FUNCTIONS = {
    'eval', 'exec', '__import__', 'getattr', 'setattr', 'compile',
    'vars', 'locals', 'globals', 'delattr', 'input', 'breakpoint',
}

BANNED_ATTR_CALLS = {
    'system', 'popen', 'call', 'Popen', 'run', 'check_call', 'check_output',
    'startfile', 'spawnl', 'spawnle', 'spawnlp', 'spawnlpe',
    'spawnv', 'spawnve', 'spawnvp', 'spawnvpe', 'posix_spawn', 'posix_spawnp',
    'load_library',
}

BANNED_MAGIC_ATTRS = {
    '__dict__', '__globals__', '__builtins__', '__class__', '__bases__',
    '__subclasses__', '__mro__', '__getattribute__', '__self__', '__func__',
    '__code__', '__traceback__', '__qualname__', '__module__',
    '__init_subclass__', '__set_name__',
}

BANNED_BUILTINS = {
    'type', 'object', 'super', 'staticmethod', 'classmethod',
    'property', 'memoryview', 'bytearray',
}
_BANNED_BUILTINS = BANNED_BUILTINS

BANNED_SYSTEM_MODULES = {
    'os', 'subprocess', 'shutil', 'sys', 'ctypes', 'ctypeslib',
    'socket', 'pathlib', 'shlex', 'signal',
}
_BANNED_IMPORTS = BANNED_SYSTEM_MODULES

# 帧/追踪属性——经典内省逃逸链的关键跳板
BANNED_FRAME_ATTRS = {
    'tb_frame', 'tb_next', 'f_back', 'f_globals', 'f_locals',
    'f_builtins', 'f_code', 'f_trace',
}


def _validate_ast(node: ast.AST) -> None:
    """递归检查 AST 节点是否在白名单内。"""
    if isinstance(node, ast.Expression):
        _validate_ast(node.body)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        _validate_ast(node.left)
        _validate_ast(node.right)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        _validate_ast(node.operand)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("只支持直接函数名调用")
        for arg in node.args:
            _validate_ast(arg)
        for kw in node.keywords:
            _validate_ast(kw.value)
    elif isinstance(node, ast.Name):
        pass
    elif isinstance(node, ast.Constant):
        pass
    elif isinstance(node, ast.List):
        for elt in node.elts:
            _validate_ast(elt)
    elif isinstance(node, ast.Tuple):
        for elt in node.elts:
            _validate_ast(elt)
    elif isinstance(node, ast.Attribute):
        if node.attr.startswith('_'):
            raise ValueError(f"沙箱拦截：禁止访问以 _ 开头的属性「{node.attr}」")
        _validate_ast(node.value)
    elif isinstance(node, ast.Compare):
        _validate_ast(node.left)
        for c in node.comparators:
            _validate_ast(c)
        for op in node.ops:
            if type(op) not in {ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE}:
                raise ValueError(f"不支持的比较操作: {type(op).__name__}")
    elif isinstance(node, ast.IfExp):
        _validate_ast(node.test)
        _validate_ast(node.body)
        _validate_ast(node.orelse)
    elif isinstance(node, ast.Subscript):
        _validate_ast(node.value)
        _validate_ast(node.slice)
    elif isinstance(node, ast.Slice):
        if node.lower:
            _validate_ast(node.lower)
        if node.upper:
            _validate_ast(node.upper)
        if node.step:
            _validate_ast(node.step)
    elif isinstance(node, ast.Dict):
        for k in node.keys:
            if k:
                _validate_ast(k)
        for v in node.values:
            _validate_ast(v)
    else:
        raise ValueError(f"不支持的表达式语法: {type(node).__name__}")


def _validate_field_calculation_ast(node: ast.AST, column_names: Any) -> None:
    """字段计算器仅允许字段、常量、运算和明确列出的标量函数。"""
    safe_functions = {"abs", "round", "int", "float", "str", "len", "min", "max", "sum", "pow", "bool"}
    if isinstance(node, ast.Expression):
        _validate_field_calculation_ast(node.body, column_names)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        _validate_field_calculation_ast(node.left, column_names)
        _validate_field_calculation_ast(node.right, column_names)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        _validate_field_calculation_ast(node.operand, column_names)
    elif isinstance(node, ast.BoolOp):
        if type(node.op) not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作: {type(node.op).__name__}")
        for value in node.values:
            _validate_field_calculation_ast(value, column_names)
    elif isinstance(node, ast.Compare):
        _validate_field_calculation_ast(node.left, column_names)
        for comparator in node.comparators:
            _validate_field_calculation_ast(comparator, column_names)
        allowed_comparisons = {ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE}
        if any(type(op) not in allowed_comparisons for op in node.ops):
            raise ValueError("不支持的比较操作")
    elif isinstance(node, ast.IfExp):
        _validate_field_calculation_ast(node.test, column_names)
        _validate_field_calculation_ast(node.body, column_names)
        _validate_field_calculation_ast(node.orelse, column_names)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in safe_functions or node.keywords:
            raise ValueError("只支持 abs/round/int/float/str/len/min/max/sum/pow/bool 函数")
        for arg in node.args:
            _validate_field_calculation_ast(arg, column_names)
    elif isinstance(node, ast.Name):
        if node.id not in column_names and node.id not in safe_functions:
            raise ValueError(f"字段或函数「{node.id}」不在允许范围内")
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ValueError("不支持该常量类型")
    else:
        raise ValueError(f"字段计算不支持该语法: {type(node).__name__}")


# ============================================================
# GeoJSON 纯函数与坐标/包围盒计算
# ============================================================

def _normalize_geojson(geojson: dict) -> dict:
    """将任意 GeoJSON 归一化为 FeatureCollection"""
    if not isinstance(geojson, dict):
        return geojson
    t = geojson.get("type")
    if t == "FeatureCollection":
        return geojson
    if t == "Feature":
        return {"type": "FeatureCollection", "features": [geojson]}
    if t in ("Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"):
        return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geojson, "properties": {}}]}
    return geojson


def _valid_registration_geometry(geometry: dict) -> bool:
    """校验几何字典是否具备有限数值的合法坐标拓扑。"""
    if not isinstance(geometry, dict):
        return False

    def valid_position(position):
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            return False
        for value in position:
            if not isinstance(value, Real) or isinstance(value, bool):
                return False
            try:
                if not math.isfinite(float(value)):
                    return False
            except (OverflowError, TypeError, ValueError):
                return False
        return True

    def valid_line(line, minimum=2):
        return (
            isinstance(line, (list, tuple)) and len(line) >= minimum
            and all(valid_position(p) for p in line)
        )

    def valid_ring(ring):
        return valid_line(ring, minimum=4) and tuple(ring[0]) == tuple(ring[-1])

    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Point":
        return valid_position(coordinates)
    if kind == "MultiPoint":
        return (
            isinstance(coordinates, (list, tuple)) and bool(coordinates)
            and all(valid_position(p) for p in coordinates)
        )
    if kind == "LineString":
        return valid_line(coordinates)
    if kind == "MultiLineString":
        return (
            isinstance(coordinates, (list, tuple)) and bool(coordinates)
            and all(valid_line(line) for line in coordinates)
        )
    if kind == "Polygon":
        return (
            isinstance(coordinates, (list, tuple)) and bool(coordinates)
            and all(valid_ring(ring) for ring in coordinates)
        )
    if kind == "MultiPolygon":
        return (isinstance(coordinates, (list, tuple)) and bool(coordinates)
                and all(isinstance(polygon, (list, tuple)) and bool(polygon)
                        and all(valid_ring(ring) for ring in polygon) for polygon in coordinates))
    if kind == "GeometryCollection":
        geometries = geometry.get("geometries")
        return isinstance(geometries, list) and all(_valid_registration_geometry(child) for child in geometries)
    return False


def _extract_coords(geom: dict, coords: list) -> None:
    """递归提取 GeoJSON 几何中的所有坐标点。"""
    if not isinstance(geom, dict):
        return
    t = geom.get("type")
    c = geom.get("coordinates")
    if not t:
        return
    if t == "Point":
        if c: coords.append(c)
    elif t in ("MultiPoint", "LineString"):
        if c: coords.extend(c)
    elif t in ("MultiLineString", "Polygon"):
        if c:
            for ring in c:
                coords.extend(ring)
    elif t == "MultiPolygon":
        if c:
            for poly in c:
                for ring in poly:
                    coords.extend(ring)
    elif t == "GeometryCollection":
        for g in geom.get("geometries", []):
            _extract_coords(g, coords)
    elif t == "Feature":
        _extract_coords(geom.get("geometry", {}), coords)
    elif t == "FeatureCollection":
        for f in geom.get("features", []):
            _extract_coords(f.get("geometry", {}), coords)


def _compute_bbox(geojson: dict) -> list:
    """计算 GeoJSON 的包围盒 [minLng, minLat, maxLng, maxLat]"""
    coords = []
    fc = _normalize_geojson(geojson)
    for f in fc.get("features", []):
        geom = f.get("geometry") or {}
        _extract_coords(geom, coords)
    if not coords:
        return [0, 0, 0, 0]
    # 防护：坐标可能为 None 或长度不足
    valid = [c for c in coords if c and len(c) >= 2]
    if not valid:
        return [0, 0, 0, 0]
    lngs = [c[0] for c in valid]
    lats = [c[1] for c in valid]
    return [min(lngs), min(lats), max(lngs), max(lats)]


def _validate_wgs84_geojson(geojson: dict) -> None:
    """Validate GeoJSON structure and coordinate bounds before accepting a vector layer."""
    try:
        feature_collection = _normalize_geojson(geojson)
        structurally_valid = (
            isinstance(feature_collection, dict)
            and isinstance(feature_collection.get("features"), list)
            and all(
                isinstance(feature, dict)
                and (feature.get("geometry") is None or _valid_registration_geometry(feature["geometry"]))
                for feature in feature_collection["features"]
            )
        )
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
        structurally_valid = False
    if not structurally_valid:
        raise ValueError("GeoJSON 几何结构无效：坐标需包含有效位置和有限数值")
    try:
        bounds = _compute_bbox(feature_collection)
        valid_bounds = (
            isinstance(bounds, (list, tuple)) and len(bounds) == 4
            and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(float(value)) for value in bounds)
            and -180 <= bounds[0] <= bounds[2] <= 180
            and -90 <= bounds[1] <= bounds[3] <= 90
        )
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
        valid_bounds = False
    if not valid_bounds:
        raise ValueError("矢量图层坐标超出 WGS-84 范围或格式无效")


def _make_fid(props: dict, idx: int) -> str:
    """稳定要素 ID：行政代码 > 数据源 ID > 名称 > 顺序兜底。"""
    if props.get("adcode") not in (None, ""):
        return f"p:{props['adcode']}"
    if props.get("id") not in (None, ""):
        return f"id:{props['id']}"
    if props.get("name"):
        return f"n:{props['name']}"
    return f"i:{idx}"


def _normalize_fid(fid_or_props: Any, idx: Optional[int] = None) -> str:
    """规范化要素 FID 或根据要素属性与序号生成稳定 FID。"""
    if isinstance(fid_or_props, dict):
        return _make_fid(fid_or_props, idx if idx is not None else 0)
    if idx is not None and isinstance(idx, (int, str)):
        if isinstance(fid_or_props, (int, str)) and str(fid_or_props).strip():
            return str(fid_or_props).strip()
        return f"i:{idx}"
    if fid_or_props is not None:
        val = str(fid_or_props).strip()
        if val:
            return val
    return f"i:{idx if idx is not None else 0}"


def _normalize_layer_provenance(provenance: Any) -> Optional[dict]:
    """Keep only bounded, non-secret source facts suitable for project persistence."""
    if not isinstance(provenance, dict):
        return None
    allowed = ("provider", "provider_name", "kind", "kind_label", "file_format", "crs")
    result = {}
    for key in allowed:
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()[:200]
    crs_known = provenance.get("crs_known")
    if isinstance(crs_known, bool):
        result["crs_known"] = crs_known
    processing = provenance.get("processing")
    if isinstance(processing, dict) and processing.get("tool") == "spatial_buffer":
        source_layer = processing.get("source_layer")
        parameters = processing.get("parameters")
        if isinstance(source_layer, str) and source_layer.strip() and isinstance(parameters, dict):
            distance = parameters.get("distance")
            unit = parameters.get("unit")
            dissolve = parameters.get("dissolve")
            try:
                distance_value = float(distance) if isinstance(distance, (int, float)) and not isinstance(distance, bool) else None
            except (OverflowError, TypeError, ValueError):
                distance_value = None
            if (distance_value is not None and math.isfinite(distance_value) and distance_value > 0
                    and isinstance(unit, str) and unit in {"m", "km"} and isinstance(dissolve, bool)):
                result["processing"] = {
                    "tool": "spatial_buffer",
                    "source_layer": source_layer.strip()[:200],
                    "parameters": {"distance": distance_value, "unit": unit, "dissolve": dissolve},
                }
    elif isinstance(processing, dict) and processing.get("tool") == "spatial_clip":
        source_layer = processing.get("source_layer")
        clip_layer = processing.get("clip_layer")
        if (isinstance(source_layer, str) and source_layer.strip()
                and isinstance(clip_layer, str) and clip_layer.strip()):
            result["processing"] = {
                "tool": "spatial_clip",
                "source_layer": source_layer.strip()[:200],
                "clip_layer": clip_layer.strip()[:200],
            }
    elif isinstance(processing, dict) and processing.get("tool") == "spatial_union":
        source_layer = processing.get("source_layer")
        other_layer = processing.get("other_layer")
        if (isinstance(source_layer, str) and source_layer.strip()
                and isinstance(other_layer, str) and other_layer.strip()):
            result["processing"] = {
                "tool": "spatial_union",
                "source_layer": source_layer.strip()[:200],
                "other_layer": other_layer.strip()[:200],
            }
    elif isinstance(processing, dict) and processing.get("tool") == "spatial_intersect":
        source_layer = processing.get("source_layer")
        other_layer = processing.get("other_layer")
        if (isinstance(source_layer, str) and source_layer.strip()
                and isinstance(other_layer, str) and other_layer.strip()):
            result["processing"] = {
                "tool": "spatial_intersect",
                "source_layer": source_layer.strip()[:200],
                "other_layer": other_layer.strip()[:200],
            }
    elif isinstance(processing, dict) and processing.get("tool") == "spatial_difference":
        source_layer = processing.get("source_layer")
        other_layer = processing.get("other_layer")
        if (isinstance(source_layer, str) and source_layer.strip()
                and isinstance(other_layer, str) and other_layer.strip()):
            result["processing"] = {
                "tool": "spatial_difference",
                "source_layer": source_layer.strip()[:200],
                "other_layer": other_layer.strip()[:200],
            }
    source_url = provenance.get("source_url")
    if isinstance(source_url, str) and len(source_url) <= 1000:
        try:
            parsed = urlsplit(source_url.strip())
            if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
                result["source_url"] = source_url.strip()
        except ValueError:
            pass
    return result or None


def _sanitize_property_name(name: str) -> str:
    """清洗 GeoJSON 属性名，移除前后空白并过滤非法特殊字符。"""
    if not isinstance(name, str):
        name = str(name) if name is not None else ""
    cleaned = name.strip()
    cleaned = re.sub(r'[\r\n\t]+', ' ', cleaned)
    return cleaned


def _parse_iso_datetime(value: Any) -> Optional[datetime.datetime]:
    """安全解析 ISO 8601 或常见日期时间字符串为 datetime 对象。"""
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime(value.year, value.month, value.day)
    if not isinstance(value, str) or not value.strip():
        return None
    val = value.strip()
    try:
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(val)
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(val, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _extract_geometry_type(geom_or_feature: dict) -> Optional[str]:
    """提取 GeoJSON 几何或要素对象的几何类型字符串。"""
    if not isinstance(geom_or_feature, dict):
        return None
    if geom_or_feature.get("type") == "Feature":
        geom = geom_or_feature.get("geometry")
        return geom.get("type") if isinstance(geom, dict) else None
    return geom_or_feature.get("type")


def _geometry_to_wkt(geometry: dict) -> str:
    """将 GeoJSON 几何字典转换为 WKT 字符串表示。"""
    if not isinstance(geometry, dict):
        raise ValueError("几何对象必须为有效字典")
    import shapely.geometry
    geom_obj = shapely.geometry.shape(geometry)
    return geom_obj.wkt


def _wkt_to_geometry(wkt_str: str) -> dict:
    """将 WKT 字符串解析为 GeoJSON 几何字典。"""
    if not isinstance(wkt_str, str) or not wkt_str.strip():
        raise ValueError("WKT 字符串不能为空")
    import shapely.geometry
    import shapely.wkt
    geom_obj = shapely.wkt.loads(wkt_str.strip())
    return shapely.geometry.mapping(geom_obj)


def _layer_property_examples(geojson: dict, limit: int = 3) -> list:
    """抽取少量分散的非敏感属性样例，帮助模型理解图层内容。"""
    features = geojson.get("features", []) if isinstance(geojson, dict) else []
    if not features:
        return []
    if len(features) <= limit:
        indices = list(range(len(features)))
    else:
        indices = sorted({round(i * (len(features) - 1) / (limit - 1)) for i in range(limit)}) if limit > 1 else [0]
    examples = []
    for index in indices:
        props = features[index].get("properties") or {}
        example = {}
        for key, value in props.items():
            key_text = str(key)
            if key_text == "_fid" or any(term in key_text.casefold() for term in ("password", "secret", "token", "api_key", "phone", "email")):
                continue
            if isinstance(value, (str, int, float)) and str(value).strip():
                example[key_text] = str(value)[:72]
            if len(example) >= 5:
                break
        if example:
            examples.append(example)
    return examples


def _safe_layer_export_stem(layer_name: str) -> str:
    """把图层名转换为安全且可被聊天附件识别的有限长度文件名。"""
    stem = re.sub(r'[^A-Za-z0-9_\-\u4e00-\u9fa5.()（）]+', "_", str(layer_name)).strip(" ._")
    return (stem[:100] or "layer")


__all__ = [
    # AST Constants & Validators
    "_ALLOWED_OPS",
    "_ALLOWED_AST_NODES",
    "ALLOWED_IMPORTS",
    "BANNED_FUNCTIONS",
    "BANNED_ATTR_CALLS",
    "BANNED_MAGIC_ATTRS",
    "BANNED_BUILTINS",
    "_BANNED_BUILTINS",
    "BANNED_SYSTEM_MODULES",
    "_BANNED_IMPORTS",
    "BANNED_FRAME_ATTRS",
    "_validate_ast",
    "_validate_field_calculation_ast",
    # GeoJSON & Geometry Helpers
    "_normalize_geojson",
    "_valid_registration_geometry",
    "_extract_coords",
    "_compute_bbox",
    "_validate_wgs84_geojson",
    "_make_fid",
    "_normalize_fid",
    "_normalize_layer_provenance",
    "_sanitize_property_name",
    "_parse_iso_datetime",
    "_extract_geometry_type",
    "_geometry_to_wkt",
    "_wkt_to_geometry",
    "_layer_property_examples",
    "_safe_layer_export_stem",
]
