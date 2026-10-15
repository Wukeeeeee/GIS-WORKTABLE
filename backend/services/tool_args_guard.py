# -*- coding: utf-8 -*-
"""参数角色校验层（最小可用版）

灵感：ESRI 的参数类型系统（Feature Layer / Field / Linear unit / 枚举约束等，
从解包的 1001 个工具规格中提炼的 186 种参数类型中精选 8 种最高频的）。
做法：不改工具签名，按"参数角色"注册规则，工具执行前校验并给出纠正建议。

8 种角色：
  layer        - 必须是已注册矢量图层
  raster_layer - 必须能找到已上传 GeoTIFF
  field_of:X   - 必须存在于参数 X 指定图层的字段中
  enum:a|b|c   - 必须在枚举内（自动大小写纠正）
  positive_num - 正数
  nonneg_num   - 非负数
  odd_int      - 奇数整数（偶数自动 +1 纠正）
  unit_km_m    - m 或 km（别名自动纠正）
"""
from __future__ import annotations

PARAM_ROLES = {
    "spatial_buffer":       {"layer_name": "layer", "distance": "positive_num", "unit": "unit_km_m"},
    "spatial_multi_ring_buffer": {"layer_name": "layer"},
    "spatial_intersect":    {"layer_a": "layer", "layer_b": "layer"},
    "spatial_union":        {"layer_a": "layer", "layer_b": "layer"},
    "spatial_difference":   {"layer_a": "layer", "layer_b": "layer"},
    "spatial_clip":         {"layer_name": "layer", "clip_layer": "layer"},
    "spatial_centroid":     {"layer_name": "layer"},
    "surface_volumes":      {"before_layer": "raster_layer", "after_layer": "raster_layer", "reference": "nonneg_num"},
    "raster_focal_stats":   {"layer_name": "raster_layer", "size": "odd_int"},
    "raster_reclassify":    {"layer_name": "raster_layer", "classes": "nonneg_num"},
    "join_field":           {"target_layer": "layer", "join_layer": "layer"},
    "generate_points_along_lines": {"layer_name": "layer", "interval": "positive_num", "unit": "unit_km_m"},
    "minimum_bounding_geometry": {"layer_name": "layer"},
    "points_to_line":       {"layer_name": "layer"},
}

_FIELD_ROLE = "field_of:"


def _resolve_layer(value):
    """按 tools 的解析习惯找图层；返回 (info, err_msg)。"""
    try:
        from backend.services.tools import _registered_layers
    except Exception:
        return None, None
    info = _registered_layers.get(value)
    if not info:
        matches = [n for n in _registered_layers if value and value in n]
        if len(matches) == 1:
            info = _registered_layers[matches[0]]
        elif len(matches) > 1:
            return None, "参数模糊：多个图层匹配「%s」，请用完整名称（可选：%s）" % (value, ", ".join(matches[:5]))
        else:
            avail = ", ".join(list(_registered_layers.keys())[:8]) or "无"
            return None, "图层「%s」不存在（当前可用：%s）" % (value, avail)
    fc = (info or {}).get("geojson") or {}
    feats = fc.get("features") or []
    if not feats:
        return None, "图层「%s」为空" % value
    return info, None


def _layer_fields(value):
    info, err = _resolve_layer(value)
    if err:
        return None, err
    feats = (info or {}).get("geojson", {}).get("features") or []
    props = (feats[0] or {}).get("properties") or {}
    return list(props.keys()), None


def validate_tool_args(tool_name: str, args: dict):
    """校验并尽量纠正参数。返回 (clean_args, warnings)。

    可自动修的（unit 大小写、偶数窗口）直接修并记入 warnings；
    不可修的（图层不存在、枚举非法等）给出带纠正建议的 warnings，
    由调用方决定是否拦截（默认只提示不拦截，保持向后兼容）。
    """
    roles = PARAM_ROLES.get(tool_name) or {}
    warnings = []
    clean = dict(args or {})
    layer_cache = {}

    for pname, role in roles.items():
        if pname not in clean:
            continue
        val = clean[pname]
        if val is None or (isinstance(val, str) and not val.strip()):
            continue

        if role == "layer":
            _, err = _resolve_layer(val)
            if err:
                warnings.append("%s: %s" % (pname, err))

        elif role == "raster_layer":
            try:
                from backend.services.tools import _find_uploaded_tif
                if _find_uploaded_tif(str(val)) is None:
                    warnings.append("%s: 未找到栅格文件「%s」，请先上传 GeoTIFF" % (pname, val))
            except Exception:
                pass

        elif role.startswith(_FIELD_ROLE):
            src_param = role[len(_FIELD_ROLE):]
            if src_param not in layer_cache:
                lv = clean.get(src_param)
                layer_cache[src_param] = _layer_fields(lv)[0] if lv else None
            fields = layer_cache[src_param]
            if fields is not None and str(val) not in [str(f) for f in fields]:
                warnings.append("%s: 字段「%s」不在图层字段中（可用：%s）" %
                                (pname, val, ", ".join(str(f) for f in fields[:10])))

        elif role.startswith("enum:"):
            allowed = role[5:].split("|")
            sv = str(val).strip().lower()
            if sv not in [a.lower() for a in allowed]:
                warnings.append("%s: 应为 %s，实际得到「%s」" % (pname, "|".join(allowed), val))
            else:
                fixed = next(a for a in allowed if a.lower() == sv)
                if fixed != val:
                    clean[pname] = fixed
                    warnings.append("%s: 已自动纠正为「%s」" % (pname, fixed))

        elif role == "unit_km_m":
            sv = str(val).strip().lower()
            if sv in ("kilometer", "kilometers", "km"):
                if val != "km":
                    clean[pname] = "km"
                    warnings.append("%s: 已自动纠正为 km" % pname)
            elif sv in ("m", "meter", "meters", "米"):
                if val != "m":
                    clean[pname] = "m"
                    warnings.append("%s: 已自动纠正为 m" % pname)
            else:
                warnings.append("%s: 单位应为 m 或 km，实际得到「%s」" % (pname, val))

        elif role == "positive_num":
            try:
                fv = float(val)
                if fv <= 0:
                    warnings.append("%s: 应为正数，实际 %s" % (pname, fv))
            except (TypeError, ValueError):
                warnings.append("%s: 应为数值，实际得到「%s」" % (pname, val))

        elif role == "nonneg_num":
            try:
                fv = float(val)
                if fv < 0:
                    warnings.append("%s: 不应为负数，实际 %s" % (pname, fv))
            except (TypeError, ValueError):
                warnings.append("%s: 应为数值，实际得到「%s」" % (pname, val))

        elif role == "odd_int":
            try:
                iv = int(val)
                if iv % 2 == 0:
                    clean[pname] = iv + 1
                    warnings.append("%s: 窗口应为奇数（3/5/7），已自动调整为 %d" % (pname, iv + 1))
            except (TypeError, ValueError):
                warnings.append("%s: 应为整数，实际得到「%s」" % (pname, val))

    return clean, warnings
