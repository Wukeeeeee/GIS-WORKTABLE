"""Local, capability-limited execution for protected GIS workspaces.

This is tokenization of known workspace data, not a general-purpose secret
detector. Only this module may approve model payloads while protection is on.
Mappings stay in process memory; durable session markers prevent old local chat
history from being replayed through the ordinary agent after a restart.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import threading
import time
import uuid


class PrivacyBoundaryError(ValueError):
    pass


_approved = ContextVar("private_gis_payload", default=None)
_vaults = {}
_lock = threading.RLock()
_SYSTEM = """你是受保护 GIS 工作区的操作助手。只使用下面的本地工具。
图层、字段、要素和已知属性值已替换为不透明代号；不得猜测、索取、解码或联网查询真实数据。
目录只提供代号和类型，不提供原始字段名、坐标、属性样本或要素总数。
使用用户明确引用的代号；无法确定字段或对象时，请用户在本地选择/输入准确字段或名称。
数值参数也可能是 V_ 开头的代号，直接传给本地工具，不要猜测其真实数值。
支持米制缓冲区、点间测地线距离、数值字段排名。真实计算与明细展示由本地完成。
距离工具只返回结果代号，真实距离由本地界面补充；不要编造数值。
不支持任意代码、联网、导出、原文理解或自动放行敏感数据。超出能力时明确说明限制。
不要输出代码或承诺未执行的操作。成功后简要说明完成的操作及结果图层代号。
"""


def workspace_protected():
    from backend.services import tools
    with tools._state_lock:
        # Legacy false/missing flags are migrated on sight. Protection is a
        # workspace invariant, never a per-layer opt-in.
        for info in tools._registered_layers.values():
            info["sensitive"] = True
        return bool(tools._registered_layers)


def _marker(session_id):
    from backend.services.ai_service import _history_path
    return Path(_history_path(session_id)).with_suffix(".privacy")


def session_protected(session_id="default"):
    return workspace_protected() or _marker(session_id).exists()


def mark_session(session_id):
    marker = _marker(session_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)


def forget_session(session_id):
    with _lock:
        _vaults.pop(session_id, None)
        _marker(session_id).unlink(missing_ok=True)


def _wire_messages(messages):
    # Match the actual provider adapter rather than a second approximation of it.
    from langchain_openai.chat_models.base import _convert_message_to_dict
    return [_convert_message_to_dict(message) for message in messages]


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@contextmanager
def approved_request(messages, schemas, audit_context=None):
    token = _approved.set({
        "messages": _canonical(_wire_messages(messages)),
        "schemas": _canonical(schemas),
        "audit_context": dict(audit_context or {}),
        "last_payload": None,
    })
    try:
        yield
    finally:
        _approved.reset(token)


def check_model_payload(payload, audit_context=None):
    """Fail closed before HTTP dispatch, including routers and fallback models."""
    fallback_context = dict(audit_context or {})
    permit = _approved.get()
    if permit is not None:
        fallback_context = permit["audit_context"]
        if (_canonical(payload.get("messages")) != permit["messages"]
                or _canonical(payload.get("tools", [])) != permit["schemas"]):
            from backend.services.privacy_audit_service import record_event
            record_event(event="blocked_payload_mismatch", audit_context=fallback_context,
                         payload=payload, detail="模型请求与已批准内容不一致")
            raise PrivacyBoundaryError("受保护请求内容发生变化，已阻止发送")
        permit["last_payload"] = payload
        from backend.services.privacy_audit_service import record_event
        record_event(event="outbound_preflight_passed", audit_context=fallback_context, payload=payload)
    elif workspace_protected():
        from backend.services.privacy_audit_service import record_event
        record_event(event="blocked_unapproved_model_call", audit_context=fallback_context, payload=payload,
                     detail="当前工作区有受保护图层，但请求未经过本地隐私边界")
        raise PrivacyBoundaryError("当前有受保护图层，此模型调用未经过本地隐私边界，已阻止发送")


def record_model_outcome(event, detail=None):
    permit = _approved.get()
    if permit is None:
        return
    from backend.services.privacy_audit_service import record_event
    record_event(event=event, audit_context=permit["audit_context"],
                 payload=permit.get("last_payload"), detail=detail)


class Vault:
    def __init__(self):
        self.ids = {}
        self.layers = {}
        self.fields = {}
        self.points = {}
        self.values = {}
        self.replacements = {}
        self.ambiguous = set()
        self.history = []

    def token(self, kind, key):
        return self.ids.setdefault((kind, key), kind + "_" + uuid.uuid4().hex[:16])

    def refresh(self):
        from backend.services import tools
        with tools._state_lock:
            snapshot = list(tools._registered_layers.items())
        previous_replacements = self.replacements
        self.replacements, self.ambiguous = {}, set()
        # Old string mappings remain private and redact references in later turns.
        self.layers, self.fields, self.points, self.values = {}, {}, {}, {}
        field_catalog = []
        value_occurrences = {}
        for name, info in snapshot:
            # References are bound to one registration revision. Re-registering,
            # editing, or restoring data invalidates old feature/field handles.
            identity = (info.get("layer_id") or name, info.get("registration_token") or "legacy")
            lid = self.token("L", identity)
            self.layers[lid] = (name, info)
            self.replacements[name] = lid
            for key in ("filename", "source_path", "raster_source_path", "group_name"):
                value = info.get(key)
                if isinstance(value, str) and value:
                    self.replacements[value] = self.token("V", value)
            features = (info.get("geojson") or {}).get("features", [])
            fields = {}
            for index, feature in enumerate(features):
                props = feature.get("properties") or {}
                pid = self.token("P", (identity, str(props.get("_fid", index))))
                self.points[pid] = (lid, feature)
                if props.get("_fid") is not None:
                    self.replacements[str(props["_fid"])] = pid
                for key, value in props.items():
                    if key == "_fid":
                        continue
                    fid = self.token("F", (identity, key))
                    self.fields[fid] = (lid, key)
                    raw_field = str(key)
                    previous_field = self.replacements.get(raw_field)
                    if previous_field is not None and previous_field != fid:
                        self.replacements.pop(raw_field, None)
                        self.ambiguous.add(raw_field)
                    elif raw_field not in self.ambiguous:
                        self.replacements[raw_field] = fid
                    dtype = ("number" if isinstance(value, (int, float)) and not isinstance(value, bool)
                             else "text" if isinstance(value, str) else "other")
                    fields.setdefault(fid, set()).add(dtype)
                    # Traverse nested attributes too: a note need not be a flat string.
                    for scalar in _scalars(value):
                        raw = str(scalar)
                        if raw:
                            vid = self.token("V", (type(scalar).__name__, raw))
                            self.values[vid] = scalar
                            value_occurrences.setdefault(raw, []).append((pid, vid))
                # Exact coordinate strings are also known sensitive values.
                for coordinate in _scalars((feature.get("geometry") or {}).get("coordinates", [])):
                    raw = str(coordinate)
                    self.replacements[raw] = self.token("V", ("coordinate", raw))
            field_catalog.append({"layer": lid, "geometry_types": [
                typ for typ in info.get("geometry_types", [])
                if typ in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "Raster"}
            ], "fields": [{"field": key, "types": sorted(types)} for key, types in fields.items()]})
        for raw, occurrences in value_occurrences.items():
            pids = {item[0] for item in occurrences}
            # A unique string value can identify a feature without exposing its name.
            numeric_text = re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", raw)
            target = (occurrences[0][0] if len(pids) == 1
                      and isinstance(self.values[occurrences[0][1]], str) and not numeric_text
                      else occurrences[0][1])
            self.replacements.setdefault(raw, target)
        self.replacements = {**previous_replacements, **self.replacements}
        for raw in self.ambiguous:
            self.replacements.pop(raw, None)
        self.catalog = field_catalog

    def redact(self, text):
        if not isinstance(text, str):
            raise PrivacyBoundaryError("隐私模式只接受文字指令，不发送附件或图片")
        if not self.replacements:
            return text
        # Resolve explicitly qualified duplicate fields locally before the
        # ambiguous bare-name check (for example, "layer A 的 population").
        for fid, (layer_id, field_name) in self.fields.items():
            if field_name not in self.ambiguous:
                continue
            layer_name, _ = self.layers[layer_id]
            qualified = re.compile(
                re.escape(layer_name) + r"\s*(?:的|中的|里的|中|\.|:)\s*" + re.escape(field_name)
            )
            text = qualified.sub(f"{layer_id} {fid}", text)
        # A single substitution pass avoids rewriting generated aliases. Longer
        # keys win; numeric/alphanumeric values require token boundaries.
        ambiguous = [key for key in self.ambiguous if key and key in text]
        if ambiguous:
            raise PrivacyBoundaryError("同名字段存在歧义，请在本地明确目标图层或先重命名字段")
        keys = sorted((key for key in self.replacements if key in text), key=len, reverse=True)
        if not keys:
            return text
        patterns = [r"(?<![A-Za-z0-9_.])" + re.escape(key) + r"(?![A-Za-z0-9_.])" if re.fullmatch(r"[\w.+-]+", key, re.ASCII)
                    else re.escape(key) for key in keys]
        return re.sub("|".join(patterns), lambda match: self.replacements[match.group(0)], text)

    def display(self, text):
        names = {lid: name for lid, (name, _) in self.layers.items()}
        names.update({fid: field for fid, (_, field) in self.fields.items()})
        return re.sub(r"\b[LF]_[a-f0-9]{16}\b", lambda m: names.get(m.group(0), m.group(0)), text)


def _scalars(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _scalars(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _scalars(item)
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        yield value


def _schema(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}}


_REF = {"type": "string"}
_NUMBER = {"type": ["number", "string"]}
SCHEMAS = [
    _schema("local_catalog", "查看可用图层和字段的代号及类型。", {}, []),
    _schema("local_buffer", "对图层建立米制缓冲区，真实几何在本地计算。",
            {"layer": _REF, "radius_m": _NUMBER}, ["layer", "radius_m"]),
    _schema("local_distance", "计算两个已明确引用的点之间的 WGS84 测地线距离；结果仅在本地展示。",
            {"first": _REF, "second": _REF}, ["first", "second"]),
    _schema("local_rank", "按数值字段排序，生成包含排名结果的本地图层。",
            {"layer": _REF, "field": _REF, "limit": _NUMBER, "descending": {"type": "boolean"}},
            ["layer", "field", "limit"]),
    _schema("local_filter", "在本地按字段和值筛选，生成受保护结果图层。值可传目录中的值代号。",
            {"layer": _REF, "field": _REF, "operator": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "between"]}, "value": _REF, "value_to": _REF},
            ["layer", "field", "operator", "value"]),
    _schema("local_statistics", "本地计算数值字段的汇总，完整数值只在本地展示。",
            {"layer": _REF, "field": _REF}, ["layer", "field"]),
    _schema("local_spatial_select", "按空间关系在本地筛选目标图层，生成受保护结果图层。",
            {"target": _REF, "source": _REF, "predicate": {"type": "string", "enum": ["intersects", "within", "contains", "touches", "crosses", "overlaps"]}},
            ["target", "source"]),
    _schema("local_overlay", "在本地执行 clip、intersect、union 或 difference 并生成受保护图层。",
            {"operation": {"type": "string", "enum": ["clip", "intersect", "union", "difference"]}, "layer_a": _REF, "layer_b": _REF},
            ["operation", "layer_a", "layer_b"]),
    _schema("local_spatial_join", "按空间关系在本地关联两个图层，生成受保护图层。",
            {"target": _REF, "join": _REF, "how": {"type": "string", "enum": ["left", "inner"]}, "predicate": {"type": "string", "enum": ["intersects", "within", "contains", "touches"]}},
            ["target", "join"]),
    _schema("local_style", "本地应用分级设色、分类设色或按字段显示标签；字段名和类别值不会发送。",
            {"operation": {"type": "string", "enum": ["graduated", "unique_values", "labels"]}, "layer": _REF, "field": _REF, "classes": {"type": "integer", "minimum": 2, "maximum": 12}},
            ["operation", "layer", "field"]),
    _schema("local_map_view", "本地将指定图层缩放至视图或清除分类样式。",
            {"operation": {"type": "string", "enum": ["fit", "clear_style"]}, "layer": _REF},
            ["operation", "layer"]),
]


def _number(vault, value):
    if isinstance(value, str):
        value = vault.values.get(value, value)
    if isinstance(value, bool):
        raise ValueError("invalid number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("invalid number")
    return number


def _execute(vault, name, args, local_results):
    from backend.services import tools
    if not isinstance(args, dict):
        return {"status": "blocked", "reason": "invalid_arguments"}
    schema = next((item["function"] for item in SCHEMAS if item["function"]["name"] == name), None)
    if schema is None or set(args) - set(schema["parameters"]["properties"]) or any(
            key not in args for key in schema["parameters"]["required"]):
        return {"status": "blocked", "reason": "unsupported_operation_or_arguments"}
    references = {"layer": vault.layers, "target": vault.layers, "source": vault.layers,
                  "join": vault.layers, "layer_a": vault.layers, "layer_b": vault.layers,
                  "field": vault.fields, "first": vault.points, "second": vault.points}
    if any(key in args and args[key] not in references[key] for key in references):
        return {"status": "needs_clarification", "reason": "unknown_ambiguous_or_expired_reference"}
    try:
        if name == "local_catalog":
            vault.refresh()
            return {"catalog": vault.catalog}
        if name == "local_distance":
            from pyproj import Geod
            first = vault.points[args["first"]][1]["geometry"]
            second = vault.points[args["second"]][1]["geometry"]
            if first["type"] != "Point" or second["type"] != "Point":
                raise ValueError("point required")
            a, b = first["coordinates"], second["coordinates"]
            distance = abs(Geod(ellps="WGS84").inv(a[0], a[1], b[0], b[1])[2])
            if not math.isfinite(distance):
                raise ValueError("invalid distance")
            rid = "R_" + uuid.uuid4().hex[:16]
            local_results.append({"result": rid, "operation": "distance", "distance_m": distance})
            return {"status": "ok", "result": rid}
        layer_name, info = vault.layers.get(args.get("layer"), (None, None))
        if name == "local_buffer":
            radius = _number(vault, args["radius_m"])
            if radius <= 0 or radius > 1_000_000:
                raise ValueError("invalid radius")
            before = {key: value.get("registration_token") for key, value in tools._registered_layers.items()}
            # Existing GIS implementation handles projection and extent limits.
            # Its free-text return is deliberately never sent to the model.
            tools.spatial_buffer.invoke({"layer_name": layer_name, "distance": radius, "unit": "m"})
            changed = [key for key, value in tools._registered_layers.items()
                       if value.get("registration_token") != before.get(key)]
            if not changed:
                return {"status": "failed", "reason": "local_geometry_operation_failed"}
            for key in changed:
                tools._registered_layers[key]["sensitive"] = True
            vault.refresh()
            return {"status": "ok", "layers": [lid for lid, (key, _) in vault.layers.items() if key in changed]}
        if name == "local_rank":
            field_layer, field = vault.fields[args["field"]]
            if field_layer != args["layer"]:
                raise ValueError("field mismatch")
            limit = _number(vault, args["limit"])
            if not limit.is_integer() or not 1 <= limit <= 1000:
                raise ValueError("invalid limit")
            if "descending" in args and not isinstance(args["descending"], bool):
                raise ValueError("invalid order")
            rows = []
            for feature in (info.get("geojson") or {}).get("features", []):
                value = (feature.get("properties") or {}).get(field)
                try:
                    score = _number(vault, value)
                except (TypeError, ValueError):
                    continue
                rows.append((score, feature))
            if not rows:
                return {"status": "failed", "reason": "no_numeric_values"}
            rows.sort(key=lambda item: item[0], reverse=args.get("descending", True))
            output = {"type": "FeatureCollection", "features": deepcopy([row[1] for row in rows[:int(limit)]])}
            result_name = "隐私排名_" + uuid.uuid4().hex[:8]
            tools._register_layer(result_name, output, sensitive=True)
            tools._push_layer(result_name, output)
            vault.refresh()
            lid = next(lid for lid, (key, _) in vault.layers.items() if key == result_name)
            return {"status": "ok", "layer": lid}
        if name in {"local_filter", "local_statistics", "local_style"}:
            field_layer, field = vault.fields[args["field"]]
            if field_layer != args["layer"]:
                raise ValueError("field mismatch")
            features = (info.get("geojson") or {}).get("features", [])
            if name == "local_statistics":
                values = []
                for feature in features:
                    raw = (feature.get("properties") or {}).get(field)
                    if raw is None:
                        continue
                    try:
                        number = _number(vault, raw)
                    except (ValueError, TypeError):
                        continue
                    if math.isfinite(number):
                        values.append(number)
                if not values:
                    return {"status": "failed", "reason": "no_numeric_values"}
                stats = {"count": len(values), "sum": sum(values), "mean": sum(values) / len(values),
                         "min": min(values), "max": max(values)}
                if not all(math.isfinite(value) for value in stats.values()):
                    return {"status": "failed", "reason": "numeric_overflow"}
                local_results.append({"result": "R_" + uuid.uuid4().hex[:16], "operation": "statistics", "statistics": stats})
                return {"status": "ok", "result": local_results[-1]["result"]}
            if name == "local_filter":
                op, expected = args["operator"], args["value"]
                if expected in vault.values:
                    expected = vault.values[expected]
                elif expected in vault.points:
                    point_layer, feature = vault.points[expected]
                    if point_layer != args["layer"]:
                        raise ValueError("point reference belongs to another layer")
                    expected = (feature.get("properties") or {}).get(field)
                if op == "between":
                    if "value_to" not in args:
                        raise ValueError("between needs both local bounds")
                    upper = vault.values.get(args["value_to"], args["value_to"])
                    low, high = _number(vault, expected), _number(vault, upper)
                else:
                    low = high = None
                matched = []
                for feature in features:
                    actual = (feature.get("properties") or {}).get(field)
                    try:
                        a_num, b_num = _number(vault, actual), _number(vault, expected)
                        comparable = (a_num, b_num)
                    except (ValueError, TypeError):
                        comparable = (str(actual), str(expected))
                    a, b = comparable
                    keep = {"eq": a == b, "ne": a != b, "gt": a > b, "gte": a >= b,
                            "lt": a < b, "lte": a <= b}.get(op)
                    if op == "contains":
                        keep = str(b).casefold() in str(a).casefold()
                    elif op == "between":
                        try:
                            keep = low <= _number(vault, actual) <= high
                        except (ValueError, TypeError):
                            keep = False
                    if keep:
                        matched.append(deepcopy(feature))
                if not matched:
                    local_results.append({"operation": "filter", "count": 0, "layer": None})
                    return {"status": "ok", "layer": None}
                result_name = "本地筛选_" + uuid.uuid4().hex[:8]
                output = {"type": "FeatureCollection", "features": matched}
                tools._register_layer(result_name, output, sensitive=True)
                tools._push_layer(result_name, output)
                local_results.append({"operation": "filter", "count": len(matched), "layer": result_name})
                vault.refresh()
                return {"status": "ok", "layer": next(lid for lid, (key, _) in vault.layers.items() if key == result_name)}
            operation = args["operation"]
            if operation == "graduated":
                count = args.get("classes", 5)
                if isinstance(count, bool) or not isinstance(count, (int, float)) or not float(count).is_integer() or not 2 <= count <= 12:
                    raise ValueError("invalid classes")
                tool = tools.spatial_graduated_colors
                tool.invoke({"layer_name": layer_name, "field": field, "n_classes": int(count)})
            elif operation == "unique_values":
                tool = tools.spatial_unique_values
                tool.invoke({"layer_name": layer_name, "field": field})
            else:
                tool = tools.add_labels
                tool.invoke({"layer_name": layer_name, "field": field})
            return {"status": "ok", "display": "style_applied"}
        if name == "local_spatial_select":
            target_name, source_name = vault.layers[args["target"]][0], vault.layers[args["source"]][0]
            before = {key: value.get("registration_token") for key, value in tools._registered_layers.items()}
            tools.spatial_select.invoke({"target_layer": target_name, "source_layer": source_name,
                                         "predicate": args.get("predicate", "intersects")})
            changed = [key for key, value in tools._registered_layers.items()
                       if value.get("registration_token") != before.get(key)]
            if not changed:
                return {"status": "failed", "reason": "local_geometry_operation_failed"}
            vault.refresh()
            return {"status": "ok", "layers": [lid for lid, (key, _) in vault.layers.items() if key in changed]}
        if name == "local_overlay":
            layer_a = vault.layers[args["layer_a"]][0]
            layer_b = vault.layers[args["layer_b"]][0]
            op = args["operation"]
            operation_tools = {"clip": tools.spatial_clip, "intersect": tools.spatial_intersect,
                               "union": tools.spatial_union, "difference": tools.spatial_difference}
            before = {key: value.get("registration_token") for key, value in tools._registered_layers.items()}
            operation_tools[op].invoke({"layer_name": layer_a, "clip_layer": layer_b} if op == "clip"
                                       else {"layer_a": layer_a, "layer_b": layer_b})
            changed = [key for key, value in tools._registered_layers.items()
                       if value.get("registration_token") != before.get(key)]
            if not changed:
                return {"status": "failed", "reason": "local_geometry_operation_failed"}
            vault.refresh()
            return {"status": "ok", "layers": [lid for lid, (key, _) in vault.layers.items() if key in changed]}
        if name == "local_spatial_join":
            target_name, join_name = vault.layers[args["target"]][0], vault.layers[args["join"]][0]
            before = {key: value.get("registration_token") for key, value in tools._registered_layers.items()}
            tools.spatial_join.invoke({"target_layer": target_name, "join_layer": join_name,
                                       "how": args.get("how", "left"), "predicate": args.get("predicate", "intersects")})
            changed = [key for key, value in tools._registered_layers.items()
                       if value.get("registration_token") != before.get(key)]
            if not changed:
                return {"status": "failed", "reason": "local_geometry_operation_failed"}
            vault.refresh()
            return {"status": "ok", "layers": [lid for lid, (key, _) in vault.layers.items() if key in changed]}
        if name == "local_map_view":
            layer_name = vault.layers[args["layer"]][0]
            action = "fit" if args["operation"] == "fit" else "clear_symbology"
            tools.layer_control.invoke({"action": action, "name": layer_name})
            return {"status": "ok", "display": "map_updated"}
    except Exception:
        # Errors may contain attribute values, coordinates, or filesystem paths.
        return {"status": "failed", "reason": "invalid_reference_or_local_operation_failed"}
    return {"status": "blocked"}


def run_private_agent(message, session_id, cfg, request_id=None, read_only=False):
    """Called under the normal agent's session + shared-workspace locks."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from backend.services import ai_service, tools
    from backend.services.llm_config import build_llm, disable_reasoning
    mark_session(session_id)
    with _lock:
        vault = _vaults.setdefault(session_id, Vault())
    tools.reset_state()
    tools.set_current_task(None)
    vault.refresh()
    local_results = []
    result = {"response": "", "reasoning": None, "layers": [], "images": [], "heatmap": None,
              "clear_layers": False, "layer_ops": [], "pending_suggestions": None,
              "privacy_mode": True, "privacy_results": local_results}
    if not vault.catalog:
        result["response"] = "当前受保护会话没有可用图层，未调用云端模型。请导入图层后继续，或清空会话后开始新的普通会话。"
        return result
    if read_only:
        result["response"] = "敏感图层模式下已停用联网位置分析，请使用本地点间距离、缓冲区或数值排名。"
        return result
    try:
        if (not isinstance(message, str) or len(message) > 6000 or "```" in message
                or re.search(r'["\'](?:coordinates|geometry|features|bbox)["\']\s*:', message)):
            result["response"] = "隐私模式不发送代码、图层原文或附件。请直接描述操作，并引用已导入的图层、字段或点名称。"
            return result
        safe_message = vault.redact(message)
        # Ordinary chat history, task code, attachments and reasoning are never
        # imported. Re-redact the small private history as the workspace evolves.
        messages = [SystemMessage(content=_SYSTEM + "\n目录：" + _canonical(vault.catalog))]
        messages += [HumanMessage(content=vault.redact(turn[0])) if turn[1] == "user"
                     else AIMessage(content=vault.redact(turn[0])) for turn in vault.history[-12:]]
        messages.append(HumanMessage(content=safe_message))
        model = build_llm(disable_reasoning(cfg))
        model.request_timeout = min(float(cfg.timeout or 45), 45)
        model.max_retries = 0
        llm = model.bind_tools(SCHEMAS)
        generation = ai_service.clear_session_cancel(session_id, request_id)
        deadline = time.monotonic() + 180
        for _ in range(12):
            if ai_service.is_session_cancelled(session_id, request_id, generation):
                result["response"] = "用户已取消"
                result["execution_status"] = "cancelled"
                break
            if time.monotonic() >= deadline:
                raise PrivacyBoundaryError("本轮请求超时")
            audit_context = {
                "base_url": cfg.base_url,
                "provider": "OpenAI-compatible endpoint",
                "model": cfg.model,
                "audit_id": uuid.uuid4().hex,
                "data_categories": [
                    "脱敏后的用户指令", "随机图层/字段/要素代号", "字段类型与几何类型",
                    "本地工具名称和参数", "工具返回的最小化状态或结果代号",
                ],
            }
            with approved_request(messages, SCHEMAS, audit_context):
                try:
                    reply = llm.invoke(messages)
                except Exception:
                    record_model_outcome("provider_call_failed_or_no_model_reply", "请求失败或超时；客户端无法仅凭异常判断服务端是否处理")
                    raise
                else:
                    record_model_outcome("provider_response_received")
            calls = getattr(reply, "tool_calls", None) or []
            content = vault.redact(reply.content) if isinstance(reply.content, str) else ""
            safe_calls = [{"name": call.get("name", ""), "args": call.get("args", {}),
                           "id": str(call.get("id", "")), "type": "tool_call"} for call in calls]
            # Do not replay hidden reasoning, provider extras, or raw output objects.
            messages.append(AIMessage(content=content, tool_calls=safe_calls))
            if not calls:
                result["response"] = vault.display(content) or "操作已结束。"
                vault.history.extend([(safe_message, "user"), (content, "assistant")])
                vault.history[:] = vault.history[-12:]
                break
            for call in safe_calls[:8]:
                if ai_service.is_session_cancelled(session_id, request_id, generation):
                    output = {"status": "cancelled"}
                else:
                    output = _execute(vault, call["name"], call["args"], local_results)
                messages.append(ToolMessage(content=_canonical(output), tool_call_id=call["id"]))
            if len(safe_calls) > 8:
                raise PrivacyBoundaryError("本轮操作数量超过隐私模式限制")
        else:
            result["response"] = "已达到本轮操作上限，请查看已有结果后继续。"
        for item in local_results:
            if item["operation"] == "distance":
                result["response"] += f"\n本地计算的点间测地线距离：{item['distance_m']:,.2f} 米。"
            elif item["operation"] == "statistics":
                stats = item["statistics"]
                result["response"] += (f"\n本地统计结果：共 {stats['count']} 个数值，和 {stats['sum']:,.4g}，"
                                        f"均值 {stats['mean']:,.4g}，最小值 {stats['min']:,.4g}，最大值 {stats['max']:,.4g}。")
            elif item["operation"] == "filter":
                result["response"] += f"\n本地筛选完成，匹配 {item['count']} 个要素。"
    except PrivacyBoundaryError as exc:
        if "同名字段" in str(exc):
            result["response"] = "存在重名字段，尚未发送本次请求。请先在本地图层面板选择目标图层，或为字段重命名后重试。"
            result["execution_status"] = "needs_clarification"
        else:
            result["response"] = "隐私边界检查未通过，请确认请求未包含原始图层数据后重试。未回退到普通模式。"
            result["execution_status"] = "blocked"
    except Exception:
        result["response"] = "隐私模式未能完成本轮请求。已停止后续调用；不会回退到普通模式。请检查模型连接或使用当前支持的本地操作。"
        result["execution_status"] = "error"
    pending = tools.get_pending_state()
    result["layers"] = pending.get("layers", [])
    result["layer_ops"] = pending.get("layer_ops", [])
    for layer in result["layers"]:
        layer["sensitive"] = True
    return result
