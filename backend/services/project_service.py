import os, json, hashlib, gzip, shutil, uuid, datetime, time, zipfile, io, re, stat
from urllib.parse import unquote, urlsplit

def extract_clean_title(content: str, max_len: int = 30) -> str:
    """从可能包含引用回复、图层注入等系统前缀的用户消息中，提取真实提问作为工程名/摘要"""
    if not content:
        return "未命名工程"
    text = str(content).strip()

    # 1. 如果包含 [当前问题]，真实问题在后面
    if "[当前问题]" in text:
        parts = text.split("[当前问题]", 1)
        if len(parts) > 1 and parts[1].strip():
            text = parts[1].strip()

    # 2. 剥离 [用户引用了上一条回复...]
    text = re.sub(r"^\[用户引用了上一条回复.*?\]\s*", "", text, flags=re.DOTALL).strip()

    # 3. 剥离 [附图层: ...] 以及 GeoJSON 代码块
    if text.startswith("[附图层:"):
        parts = text.split("```")
        if len(parts) >= 3 and parts[-1].strip():
            text = parts[-1].strip()
        else:
            m_name = re.search(r"\[附图层:\s*([^\]]+)\]", text)
            text = m_name.group(1).strip() if m_name else "图层工程"

    # 4. 再次清理开头的提示词注入块
    text = re.sub(r"^\[.*?\]\s*", "", text).strip()

    # 5. 清理多余换行与空白
    text = re.sub(r"[\r\n\t]+", " ", text).strip()
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return "未命名工程"

    if len(text) > max_len:
        return text[:max_len].strip() + "…"
    return text

_PROJECT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cache", "projects")
_BLOB_DIR = os.path.join(_PROJECT_DIR, "blobs")
_INDEX_PATH = os.path.join(_PROJECT_DIR, "index.json")
_MAX_PROJECTS = 30

# 内存引用计数（启动时从 index.json 重建）
_blob_refcount = {}

# ============================================================
# 路径辅助
# ============================================================

def _ensure_dirs():
    os.makedirs(_BLOB_DIR, exist_ok=True)

def _project_dir(pid: str) -> str:
    return os.path.join(_PROJECT_DIR, f"proj_{pid}")

def _project_path(pid: str) -> str:
    return os.path.join(_project_dir(pid), "project.json")

def _blob_path(sha: str) -> str:
    return os.path.join(_BLOB_DIR, f"{sha}.geojson.gz")

def _project_raster_path(pid: str, filename: str) -> str | None:
    if not isinstance(pid, str) or not pid or os.path.basename(pid) != pid:
        return None
    if not isinstance(filename, str) or not filename or os.path.basename(filename) != filename:
        return None
    project_root = os.path.realpath(_PROJECT_DIR)
    project_dir = os.path.realpath(_project_dir(pid))
    if os.path.commonpath([project_root, project_dir]) != project_root:
        return None
    assets_dir = os.path.realpath(os.path.join(project_dir, "assets"))
    path = os.path.realpath(os.path.join(assets_dir, filename))
    return path if os.path.commonpath([assets_dir, path]) == assets_dir else None

def _raster_source_path(raster: dict) -> str | None:
    asset = raster.get("asset")
    source_pid = raster.get("project_id")
    if asset and source_pid:
        path = _project_raster_path(source_pid, asset)
        if path and os.path.isfile(path):
            return path
    url_path = unquote(urlsplit(str(raster.get("url") or "")).path)
    prefix = "/output/uploads/"
    filename = url_path[len(prefix):] if url_path.startswith(prefix) else ""
    if not filename or os.path.basename(filename) != filename:
        return None
    from backend.services.ai_service import _TEMP_OUTPUT_DIR
    path = os.path.realpath(os.path.join(_TEMP_OUTPUT_DIR, "uploads", filename))
    uploads_dir = os.path.realpath(os.path.join(_TEMP_OUTPUT_DIR, "uploads"))
    return path if os.path.commonpath([uploads_dir, path]) == uploads_dir and os.path.isfile(path) else None

def _store_project_raster(pid: str, raster: dict) -> dict:
    source = _raster_source_path(raster)
    if not source:
        raise ValueError("栅格图层资源不存在，无法保存工程")
    extension = os.path.splitext(source)[1].lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("工程栅格资源格式不受支持")
    digest = hashlib.sha256()
    with open(source, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    filename = digest.hexdigest()[:20] + extension
    target = _project_raster_path(pid, filename)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.realpath(source) != os.path.realpath(target):
        shutil.copyfile(source, target)
    saved = {key: raster[key] for key in ("bounds", "width", "height") if key in raster}
    saved.update({
        "filename": os.path.basename(str(raster.get("filename") or filename)),
        "asset": filename,
        "project_id": pid,
        "url": f"/api/projects/{pid}/assets/{filename}",
    })
    return saved

def get_project_raster_asset(pid: str, filename: str) -> str | None:
    proj = _load_project_data(pid)
    if not proj or not any((layer.get("raster") or {}).get("asset") == filename for layer in proj.get("layers", [])):
        return None
    path = _project_raster_path(pid, filename)
    return path if path and os.path.isfile(path) else None

def _cleanup_project_raster_assets(pid: str, keep_assets: set[str]):
    assets_dir = os.path.join(_project_dir(pid), "assets")
    if not os.path.isdir(assets_dir):
        return
    for filename in os.listdir(assets_dir):
        if filename in keep_assets:
            continue
        try:
            os.unlink(os.path.join(assets_dir, filename))
        except OSError:
            pass

def _extract_project_archive(zf: zipfile.ZipFile, target_dir: str):
    root = os.path.realpath(target_dir)
    members = zf.infolist()
    for member in members:
        name = member.filename
        normalized = name.replace("\\", "/")
        parts = normalized.split("/")
        if member.is_dir() and parts[-1:] == [""]:
            parts.pop()
        mode = member.external_attr >> 16
        if (not normalized or "\x00" in normalized or normalized.startswith("/")
                or re.match(r"^[A-Za-z]:", normalized)
                or not parts or any(part in {"", ".", ".."} for part in parts)
                or stat.S_ISLNK(mode)):
            raise ValueError("导入的工程文件包含不安全路径")
        destination = os.path.realpath(os.path.join(root, *parts))
        try:
            common_root = os.path.commonpath([root, destination])
        except ValueError as error:
            raise ValueError("导入的工程文件包含不安全路径") from error
        if common_root != root:
            raise ValueError("导入的工程文件包含不安全路径")
    zf.extractall(root)

# ============================================================
# CAS Blob 存储
# ============================================================

def _blob_put(geojson: dict) -> str:
    raw = json.dumps(geojson, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(raw.encode()).hexdigest()[:12]
    path = _blob_path(sha)
    if not os.path.exists(path):
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(raw)
    _blob_refcount[sha] = _blob_refcount.get(sha, 0) + 1
    return sha

def _blob_get(sha: str) -> dict | None:
    path = _blob_path(sha)
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)

def _blob_remove(sha: str):
    _blob_refcount[sha] = _blob_refcount.get(sha, 0) - 1
    if _blob_refcount[sha] <= 0:
        path = _blob_path(sha)
        if os.path.exists(path):
            os.remove(path)
        _blob_refcount.pop(sha, None)

# ============================================================
# Index 管理
# ============================================================

def _load_index() -> dict:
    if not os.path.exists(_INDEX_PATH):
        return {"projects": {}}
    with open(_INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_index(index: dict):
    _ensure_dirs()
    with open(_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

def _rebuild_refcount():
    _blob_refcount.clear()
    index = _load_index()
    for pid, info in index.get("projects", {}).items():
        proj = _load_project_data(pid)
        if proj:
            for layer in proj.get("layers", []):
                blob = layer.get("blob")
                if blob:
                    _blob_refcount[blob] = _blob_refcount.get(blob, 0) + 1

# ============================================================
# 工程 CRUD
# ============================================================

def _generate_id() -> str:
    return uuid.uuid4().hex[:8]

def _now_str() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

def _load_project_data(pid: str) -> dict | None:
    path = _project_path(pid)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_project_data(pid: str, data: dict):
    _ensure_dirs()
    d = _project_dir(pid)
    os.makedirs(d, exist_ok=True)
    path = _project_path(pid)
    temp_path = path + f".{uuid.uuid4().hex}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def save_project(
    project_id: str | None,
    name: str,
    session_id: str,
    provider: str,
    map_state: dict,
    messages: list,
    layers: list,
    layer_groups: list | None = None,
) -> dict:
    _ensure_dirs()
    now = _now_str()
    is_new = project_id is None or not _project_exists(project_id)
    existing = None

    if is_new:
        pid = _generate_id()
        created = now
    else:
        pid = project_id
        existing = _load_project_data(pid)
        created = existing.get("createdAt", now) if existing else now
    old_blob_refs = [
        layer.get("blob") for layer in (existing or {}).get("layers", []) if layer.get("blob")
    ]
    old_raster_assets = {
        raster.get("asset")
        for layer in (existing or {}).get("layers", [])
        for raster in [layer.get("raster")]
        if isinstance(raster, dict) and isinstance(raster.get("asset"), str)
    }

    # 存储图层 → CAS blob
    layer_refs = []
    raster_assets = set()
    new_blob_refs = []
    try:
        for idx, layer in enumerate(layers):
            geojson = layer.get("geojson") or layer.get("geojson_data")
            if geojson:
                blob = _blob_put(geojson)
                new_blob_refs.append(blob)
            else:
                blob = None
            raster = layer.get("raster") if isinstance(layer.get("raster"), dict) else None
            if raster:
                raster = _store_project_raster(pid, raster)
                raster_assets.add(raster["asset"])
            layer_refs.append({
                "layer_id": layer.get("layer_id") if isinstance(layer.get("layer_id"), str) and layer.get("layer_id").strip() else None,
                "name": layer.get("filename") or layer.get("name", "未命名"),
                "blob": blob,
                "color": layer.get("color", "#1c1b1b"),
                "style": layer.get("style") if isinstance(layer.get("style"), dict) else {},
                "symbology": layer.get("symbology") if isinstance(layer.get("symbology"), dict) else None,
                "visible": layer.get("visible", True) if layer.get("visible") is not False else False,
                "geometry_type": layer.get("geometry_type", "未知"),
                "source": layer.get("source", "ai"),
                "order": idx,
                "url": layer.get("url") or layer.get("service_url") or "",
                "service_type": layer.get("service_type") or layer.get("protocol") or "",
                "sublayer": layer.get("sublayer") or layer.get("sublayer_name") or "",
                "crs": layer.get("crs") or "WGS-84",
                "groupId": layer.get("groupId") or None,
                "raster": raster,
            })
    except Exception:
        for blob in new_blob_refs:
            _blob_remove(blob)
        _cleanup_project_raster_assets(pid, old_raster_assets)
        raise

    saved_layer_groups = [
        {"id": group["id"], "name": group["name"], "collapsed": bool(group.get("collapsed", False))}
        for group in (layer_groups or [])
        if isinstance(group, dict) and isinstance(group.get("id"), str) and group.get("id")
        and isinstance(group.get("name"), str) and group.get("name", "").strip()
    ]

    # 规范化并清洗工程名
    sanitized_name = extract_clean_title(name, max_len=30) if name and ("[" in name or len(name) > 30) else (name or f"工程 {pid[:4]}")

    # 构造工程数据
    proj_data = {
        "id": pid,
        "name": sanitized_name,
        "createdAt": created,
        "updatedAt": now,
        "sessionId": session_id,
        "provider": provider,
        "mapState": map_state,
        "messages": messages,
        "layers": layer_refs,
        "layerGroups": saved_layer_groups,
    }

    try:
        _save_project_data(pid, proj_data)
    except Exception:
        for blob in new_blob_refs:
            _blob_remove(blob)
        _cleanup_project_raster_assets(pid, old_raster_assets)
        raise

    # The old metadata no longer references these blobs after the atomic replacement.
    for blob in old_blob_refs:
        _blob_remove(blob)

    assets_dir = os.path.join(_project_dir(pid), "assets")
    if os.path.isdir(assets_dir):
        for filename in os.listdir(assets_dir):
            if filename not in raster_assets:
                try:
                    os.unlink(os.path.join(assets_dir, filename))
                except OSError:
                    pass

    # 更新 index
    preview = ""
    for msg in messages:
        if msg.get("role") == "user" and msg.get("content"):
            preview = extract_clean_title(msg["content"], max_len=60)
            break
    index = _load_index()
    index["projects"][pid] = {
        "id": pid,
        "name": sanitized_name,
        "createdAt": created,
        "updatedAt": now,
        "msgPreview": preview,
        "layerCount": len(layer_refs),
        "messageCount": len(messages),
        "provider": provider,
    }
    # 上限修剪
    projs = index["projects"]
    if len(projs) > _MAX_PROJECTS:
        sorted_items = sorted(projs.items(), key=lambda x: x[1].get("updatedAt", ""))
        for old_pid, _ in sorted_items[:len(projs) - _MAX_PROJECTS]:
            _delete_project_data(old_pid, index)
    _save_index(index)

    return {"id": pid, "name": name or f"工程 {pid[:4]}", "updatedAt": now}

def _project_exists(pid: str) -> bool:
    return os.path.exists(_project_path(pid))

def _delete_project_data(pid: str, index: dict = None):
    """删除工程数据，释放 blob 引用"""
    proj = _load_project_data(pid)
    if proj:
        for layer in proj.get("layers", []):
            blob = layer.get("blob")
            if blob:
                _blob_remove(blob)
    d = _project_dir(pid)
    if os.path.exists(d):
        shutil.rmtree(d)
    if index is None:
        index = _load_index()
    index["projects"].pop(pid, None)
    _save_index(index)

def load_project(pid: str) -> dict | None:
    proj = _load_project_data(pid)
    if not proj:
        return None
    # 解析 blob → 完整图层
    resolved_layers = []
    for layer in proj.get("layers", []):
        blob = layer.get("blob")
        if blob:
            geojson = _blob_get(blob)
        else:
            geojson = None
        raster = layer.get("raster")
        if isinstance(raster, dict) and raster.get("asset"):
            raster = {**raster, "project_id": pid,
                      "url": f"/api/projects/{pid}/assets/{raster['asset']}"}
        resolved_layers.append({
            **layer,
            "geojson": geojson,
            "raster": raster,
        })
    result = {**proj, "layers": resolved_layers}
    return result

def activate_project(pid: str, session_id: str = None) -> dict | None:
    """激活指定工程：加载工程并将其历史消息和图层恢复到后端，实现工程隔离与上下文精准记忆"""
    data = load_project(pid)
    if not data:
        return None
    sid = session_id or data.get("sessionId") or f"proj_{pid}"
    try:
        from backend.services.ai_service import conversation_history
        from backend.services.tools import reset_registered_layers

        # 1. 恢复消息历史
        conversation_history[sid] = list(data.get("messages", []))
        # 2. 恢复图层到 tools._registered_layers
        layers = data.get("layers", [])
        reset_registered_layers(layers)
    except Exception:
        pass
    return {"sessionId": sid, "layerCount": len(data.get("layers", []))}

def list_projects() -> list:
    index = _load_index()
    projs = list(index.get("projects", {}).values())
    projs.sort(key=lambda p: p.get("updatedAt", ""), reverse=True)
    return projs

def delete_project(pid: str):
    index = _load_index()
    _delete_project_data(pid, index)

def delete_all_projects():
    index = _load_index()
    for pid in list(index.get("projects", {}).keys()):
        _delete_project_data(pid, index)
    # 清理残留文件夹
    import shutil
    for d in os.listdir(_PROJECT_DIR):
        full = os.path.join(_PROJECT_DIR, d)
        if d.startswith("proj_") and os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)
    global _blob_refcount
    _blob_refcount.clear()

def rename_project(pid: str, new_name: str):
    proj = _load_project_data(pid)
    if not proj:
        return None
    proj["name"] = new_name
    _save_project_data(pid, proj)
    index = _load_index()
    if pid in index.get("projects", {}):
        index["projects"][pid]["name"] = new_name
    _save_index(index)
    return {"id": pid, "name": new_name}

def export_project(pid: str) -> bytes:
    proj = _load_project_data(pid)
    if not proj:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 工程数据
        zf.writestr("project.json", json.dumps(proj, ensure_ascii=False, indent=2))
        archived_raster_assets = set()
        # 包含图层 blob
        for layer in proj.get("layers", []):
            blob = layer.get("blob")
            if blob:
                blob_path = _blob_path(blob)
                if os.path.exists(blob_path):
                    zf.write(blob_path, f"blobs/{blob}.geojson.gz")
            raster = layer.get("raster")
            asset = raster.get("asset") if isinstance(raster, dict) else None
            if asset and asset not in archived_raster_assets:
                asset_path = _project_raster_path(pid, asset)
                if asset_path and os.path.exists(asset_path):
                    zf.write(asset_path, f"assets/{asset}")
                    archived_raster_assets.add(asset)
    buf.seek(0)
    return buf.read()

def import_project(zip_bytes: bytes) -> dict:
    _ensure_dirs()
    pid = _generate_id()
    target_dir = _project_dir(pid)
    os.makedirs(target_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            _extract_project_archive(zf, target_dir)
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

    proj_path = os.path.join(target_dir, "project.json")
    if not os.path.exists(proj_path):
        shutil.rmtree(target_dir)
        raise ValueError("导入的工程文件无效：缺少 project.json")

    with open(proj_path, "r", encoding="utf-8") as f:
        proj_data = json.load(f)

    # 迁移 blob 到全局 blob 目录
    imported_blobs = os.path.join(target_dir, "blobs")
    if os.path.exists(imported_blobs):
        for fname in os.listdir(imported_blobs):
            src = os.path.join(imported_blobs, fname)
            if os.path.isfile(src):
                dst = os.path.join(_BLOB_DIR, fname)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
        shutil.rmtree(imported_blobs)

    proj_data["id"] = pid
    now = _now_str()
    proj_data["createdAt"] = now
    proj_data["updatedAt"] = now
    _save_project_data(pid, proj_data)

    index = _load_index()
    index["projects"][pid] = {
        "id": pid,
        "name": proj_data.get("name", f"导入工程 {pid[:4]}"),
        "createdAt": now,
        "updatedAt": now,
        "msgPreview": "",
        "layerCount": len(proj_data.get("layers", [])),
        "messageCount": len(proj_data.get("messages", [])),
        "provider": proj_data.get("provider", ""),
    }
    _save_index(index)
    _rebuild_refcount()
    return {"id": pid, "name": proj_data.get("name", "导入工程")}

def auto_save(
    session_id: str = "default", provider: str = "", map_state: dict = None,
    project_id: str = None, layer_groups: list | None = None,
    layer_assignments: list | None = None,
):
    """由 ai_service 或前端在每轮对话后调用，自动保存当前会话"""
    from backend.services.ai_service import conversation_history
    from backend.services.tools import _registered_layers

    messages = conversation_history.get(session_id, [])
    if not messages:
        return None

    existing_proj = None
    layers = []
    for name, info in _registered_layers.items():
        layers.append({
            "name": name,
            "geojson": info.get("geojson"),
            "geometry_type": ", ".join(info.get("geometry_types", [])),
            "feature_count": info.get("feature_count", 0),
            "source": "ai",
        })

    # 从 index 找这个 session 对应的工程（优先匹配显式 project_id，其次 session_id）
    index = _load_index()
    existing_pid = project_id if (project_id and _project_exists(project_id)) else None
    if not existing_pid:
        for pid, info in index.get("projects", {}).items():
            proj = _load_project_data(pid)
            if proj and proj.get("sessionId") == session_id:
                existing_pid = pid
                break

    if existing_pid:
        existing_proj = _load_project_data(existing_pid)
    existing_layers_by_name = {
        layer.get("name"): layer for layer in (existing_proj or {}).get("layers", []) if layer.get("name")
    }
    assignments_by_name = {}
    for assignment in layer_assignments or []:
        if not isinstance(assignment, dict):
            continue
        for alias in assignment.get("names", []):
            if isinstance(alias, str) and alias:
                assignments_by_name[alias] = {
                    "groupId": assignment.get("groupId") or None,
                    "visible": assignment.get("visible") if isinstance(assignment.get("visible"), bool) else None,
                    "layer_id": assignment.get("layer_id") if isinstance(assignment.get("layer_id"), str) and assignment.get("layer_id").strip() else None,
                    "style": assignment.get("style") if isinstance(assignment.get("style"), dict) else None,
                    "symbology": assignment.get("symbology") if isinstance(assignment.get("symbology"), dict) else None,
                    "has_symbology": "symbology" in assignment,
                    "raster": assignment.get("raster") if isinstance(assignment.get("raster"), dict) else None,
                }
    for layer in layers:
        layer_name = layer.get("name")
        if layer_name in assignments_by_name:
            assignment = assignments_by_name[layer_name]
            layer["groupId"] = assignment["groupId"]
            if assignment["visible"] is not None:
                layer["visible"] = assignment["visible"]
            previous = existing_layers_by_name.get(layer_name)
            layer["layer_id"] = assignment["layer_id"] or (previous or {}).get("layer_id")
            layer["style"] = assignment["style"] if assignment["style"] is not None else (previous or {}).get("style", {})
            if assignment["has_symbology"]:
                layer["symbology"] = assignment["symbology"]
            elif previous and previous.get("symbology"):
                layer["symbology"] = previous["symbology"]
            if assignment["raster"]:
                layer["raster"] = assignment["raster"]
        else:
            previous = existing_layers_by_name.get(layer_name)
            if previous:
                layer["groupId"] = previous.get("groupId")
                layer["layer_id"] = previous.get("layer_id")
                layer["style"] = previous.get("style", {})
                layer["symbology"] = previous.get("symbology")

    for assignment in layer_assignments or []:
        if not isinstance(assignment, dict) or not isinstance(assignment.get("raster"), dict):
            continue
        layer_name = assignment.get("name") or next(
            (name for name in assignment.get("names", []) if isinstance(name, str) and name), None
        )
        if not layer_name:
            continue
        existing = next((layer for layer in layers if layer.get("name") == layer_name), None)
        if existing:
            existing["raster"] = assignment["raster"]
            continue
        layers.append({
            "name": layer_name,
            "layer_id": assignment.get("layer_id"),
            "geometry_type": "Raster",
            "source": "upload",
            "raster": assignment["raster"],
            "style": assignment.get("style") if isinstance(assignment.get("style"), dict) else {},
            "visible": assignment.get("visible") is not False,
            "groupId": assignment.get("groupId") or None,
        })

    # 取工程名：如果已有工程名则保留已有名称；否则用第一条用户消息的真实提问文本
    name = "未命名工程"
    if existing_pid:
        if existing_proj and existing_proj.get("name"):
            name = existing_proj["name"]
    if name == "未命名工程":
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content"):
                name = extract_clean_title(msg["content"], max_len=24)
                break

    return save_project(
        project_id=existing_pid,
        name=name,
        session_id=session_id,
        provider=provider,
        map_state=map_state or {},
        messages=messages,
        layers=layers,
        layer_groups=layer_groups if layer_groups is not None else (existing_proj or {}).get("layerGroups", []),
    )

# 启动时重建引用计数
_rebuild_refcount()
