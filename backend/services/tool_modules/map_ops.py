# -*- coding: utf-8 -*-
"""Map-operation implementations backed by the authoritative runtime state."""

from __future__ import annotations

import math
import uuid

from backend.services.tool_modules import runtime as _runtime


def _layer_control_impl(
    action: str, name: str = "", new_name: str = "", color: str = "",
    opacity: float = 1.0, weight: int = 2, fill_pattern: str = "",
) -> str:
    """Apply a layer-registry mutation or queue a frontend layer operation."""
    if action in ("remove", "toggle", "set_color", "set_style", "clear_symbology", "fit", "rename"):
        resolved, _, error = _runtime._get_exact_registered_layer(name)
        if not resolved:
            return error.replace("未执行修改", "未执行操作")
        name = resolved
    if action == "remove":
        _runtime._pending_layer_ops.append({"action": "remove", "name": name})
        _runtime._unregister_layer(name)
        return f"已删除图层: {name}（当前剩余 {len(_runtime._registered_layers)} 个图层）"
    if action == "toggle":
        _runtime._pending_layer_ops.append({"action": "toggle", "name": name})
        return f"已标记切换图层显隐: {name}"
    if action == "set_color":
        _runtime._pending_layer_ops.append({"action": "set_color", "name": name, "color": color})
        return f"已标记修改图层颜色: {name} → {color}"
    if action == "set_style":
        style = {"color": color}
        if opacity != 1.0:
            style["opacity"] = max(0.0, min(1.0, opacity))
        if weight != 2:
            style["weight"] = max(1, weight)
        if fill_pattern:
            style["fillPattern"] = fill_pattern
        _runtime._pending_layer_ops.append({"action": "set_style", "name": name, "style": style})
        parts = [f"颜色={color}"]
        if "opacity" in style:
            parts.append(f"透明度={style['opacity']}")
        if "weight" in style:
            parts.append(f"线宽={style['weight']}")
        if "fillPattern" in style:
            parts.append(f"填充图案={style['fillPattern']}")
        return f"已标记修改图层样式: {name} → {'，'.join(parts)}"
    if action == "clear_symbology":
        _runtime._pending_layer_ops.append({"action": "clear_symbology", "name": name})
        return f"已标记清除图层「{name}」的分级/唯一值符号化与对应图例"
    if action == "rename":
        if not isinstance(new_name, str) or not new_name.strip():
            return "图层重命名失败: 新图层名不能为空；未重命名任何图层"
        new_name = new_name.strip()
        with _runtime._state_lock:
            if name not in _runtime._registered_layers:
                return f"图层重命名失败: 图层「{name}」已被移除，请刷新后重试"
            if new_name != name and new_name in _runtime._registered_layers:
                return f"图层重命名失败: 图层「{new_name}」已存在；未重命名任何图层"
            _runtime._registered_layers[new_name] = _runtime._registered_layers.pop(name)
            _runtime._registered_layers[new_name]["name"] = new_name
            # Invalidate session-scoped AI handles bound to the previous name.
            _runtime._registered_layers[new_name]["registration_token"] = uuid.uuid4().hex
            _runtime._pending_layer_ops.append({"action": "rename", "name": name, "new_name": new_name})
        return f"已重命名图层: {name} → {new_name}"
    if action == "fit":
        _runtime._pending_layer_ops.append({"action": "fit", "name": name})
        return f"已标记缩放到图层: {name}"
    return f"未知操作: {action}，可选：remove / toggle / set_color / set_style / clear_symbology / rename / fit"


def _focus_map_impl(layer_name: str = "", center: str = "", zoom: int = 13) -> str:
    """Resolve a registered layer or queue a validated map-center operation."""
    if layer_name:
        if layer_name in _runtime._registered_layers:
            _runtime._pending_layer_ops.append({"action": "fit", "name": layer_name})
            return f"已定位到图层「{layer_name}」（缩放至其范围）"
        for key in list(_runtime._registered_layers.keys()):
            if layer_name in key or key in layer_name:
                _runtime._pending_layer_ops.append({"action": "fit", "name": key})
                return f"已定位到图层「{key}」（缩放至其范围）"
        names = "、".join(_runtime._registered_layers.keys()) or "无"
        return f"未找到图层「{layer_name}」，当前图层：{names}。可改用 center 参数按坐标定位。"
    if center:
        try:
            parts = center.replace("，", ",").split(",")
            if len(parts) != 2:
                return f"center 格式应为「经度,纬度」，收到：{center}"
            lon, lat = float(parts[0].strip()), float(parts[1].strip())
            if (not math.isfinite(lon) or not math.isfinite(lat)
                    or not -180 <= lon <= 180 or not -90 <= lat <= 90):
                return "坐标范围无效：经度须在 -180 到 180 之间，纬度须在 -90 到 90 之间。"
            clamped_zoom = max(3, min(19, int(zoom)))
            _runtime._pending_layer_ops.append({
                "action": "center", "center": [lon, lat], "zoom": clamped_zoom,
            })
            return f"已定位到 ({lat:.4f}, {lon:.4f})，缩放级别 {clamped_zoom}"
        except ValueError:
            return f"无法解析坐标：{center}，格式应为「经度,纬度」（如 121.4593,31.2513）"
    return "请提供 layer_name（图层名）或 center（「经度,纬度」）进行定位"
