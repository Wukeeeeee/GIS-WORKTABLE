"""Local, content-free records of protected AI egress decisions."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
import uuid
from urllib.parse import urlsplit


_AUDIT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "cache", "privacy", "egress.jsonl",
)
_LOCK = threading.RLock()
_MAX_RETURNED_EVENTS = 500


def _text(value, limit=120):
    value = str(value or "")
    return "".join(ch for ch in value if ch >= " " and ch not in "\x7f")[:limit]


def _destination(base_url):
    try:
        parts = urlsplit(str(base_url or ""))
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return "unknown"
        host = parts.hostname.encode("idna").decode("ascii").lower()
        port = parts.port
        default_port = 443 if parts.scheme == "https" else 80
        return f"{parts.scheme}://{host}" + (f":{port}" if port and port != default_port else "")
    except (TypeError, ValueError, UnicodeError):
        return "unknown"


def record_event(*, event, audit_context=None, payload=None, detail=None):
    """Append metadata only. Never persist prompts, coordinates, attributes, or keys."""
    context = audit_context if isinstance(audit_context, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    tools = payload.get("tools", [])
    tool_names = []
    if isinstance(tools, list):
        for item in tools[:64]:
            function = item.get("function", {}) if isinstance(item, dict) else {}
            name = function.get("name") if isinstance(function, dict) else ""
            if isinstance(name, str) and name:
                tool_names.append(_text(name, 80))
    messages = payload.get("messages", [])
    event_data = {
        "event_id": uuid.uuid4().hex,
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": _text(event, 48),
        "destination": _destination(context.get("base_url")),
        "provider": _text(context.get("provider"), 64),
        "model": _text(context.get("model"), 100),
        "request_id": _text(context.get("audit_id"), 64),
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "tool_names": tool_names,
        "payload_bytes": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
        "data_categories": list(context.get("data_categories", []))[:16],
    }
    if detail:
        event_data["detail"] = _text(detail, 120)
    line = (json.dumps(event_data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    directory = os.path.dirname(_AUDIT_PATH)
    os.makedirs(directory, exist_ok=True)
    with _LOCK:
        fd = os.open(_AUDIT_PATH, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            written = os.write(fd, line)
            if written != len(line):
                raise OSError("短写入隐私审计记录")
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            if os.path.getsize(_AUDIT_PATH) > 5 * 1024 * 1024:
                with open(_AUDIT_PATH, "rb") as source:
                    recent = source.readlines()[-5000:]
                temp_path = _AUDIT_PATH + ".tmp"
                with open(temp_path, "wb") as target:
                    target.writelines(recent)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temp_path, _AUDIT_PATH)
        except OSError:
            # The current event is already durable; a later append can retry compaction.
            pass
    return event_data


def list_events(limit=100):
    try:
        limit = max(1, min(int(limit), _MAX_RETURNED_EVENTS))
    except (TypeError, ValueError, OverflowError):
        limit = 100
    if not os.path.isfile(_AUDIT_PATH):
        return []
    with _LOCK, open(_AUDIT_PATH, "rb") as source:
        lines = source.readlines()[-limit:]
    events = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            events.append(item)
    return events
