import os, json, hashlib, gzip, shutil, uuid, datetime, time, zipfile, io

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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_project(
    project_id: str | None,
    name: str,
    session_id: str,
    provider: str,
    map_state: dict,
    messages: list,
    layers: list,
) -> dict:
    _ensure_dirs()
    now = _now_str()
    is_new = project_id is None or not _project_exists(project_id)

    if is_new:
        pid = _generate_id()
        created = now
    else:
        pid = project_id
        existing = _load_project_data(pid)
        created = existing.get("createdAt", now) if existing else now
        # 释放旧图层引用
        if existing:
            for layer in existing.get("layers", []):
                blob = layer.get("blob")
                if blob:
                    _blob_remove(blob)

    # 存储图层 → CAS blob
    layer_refs = []
    for layer in layers:
        geojson = layer.get("geojson") or layer.get("geojson_data")
        if geojson:
            blob = _blob_put(geojson)
        else:
            blob = None
        layer_refs.append({
            "name": layer.get("filename") or layer.get("name", "未命名"),
            "blob": blob,
            "color": layer.get("color", "#1c1b1b"),
            "visible": layer.get("visible", True),
            "geometry_type": layer.get("geometry_type", "未知"),
            "source": layer.get("source", "ai"),
        })

    # 构造工程数据
    proj_data = {
        "id": pid,
        "name": name or f"工程 {pid[:4]}",
        "createdAt": created,
        "updatedAt": now,
        "sessionId": session_id,
        "provider": provider,
        "mapState": map_state,
        "messages": messages,
        "layers": layer_refs,
    }

    _save_project_data(pid, proj_data)

    # 更新 index
    preview = ""
    for msg in messages:
        if msg.get("role") == "user" and msg.get("content"):
            preview = msg["content"][:60]
            break
    index = _load_index()
    index["projects"][pid] = {
        "id": pid,
        "name": name or f"工程 {pid[:4]}",
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
        resolved_layers.append({
            **layer,
            "geojson": geojson,
        })
    result = {**proj, "layers": resolved_layers}
    return result

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
        # 包含图层 blob
        for layer in proj.get("layers", []):
            blob = layer.get("blob")
            if blob:
                blob_path = _blob_path(blob)
                if os.path.exists(blob_path):
                    zf.write(blob_path, f"blobs/{blob}.geojson.gz")
    buf.seek(0)
    return buf.read()

def import_project(zip_bytes: bytes) -> dict:
    _ensure_dirs()
    pid = _generate_id()
    target_dir = _project_dir(pid)
    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(target_dir)

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

def auto_save(session_id: str = "default", provider: str = "", map_state: dict = None):
    """由 ai_service 在每轮对话后调用，自动保存当前会话"""
    # 延迟导入，避免循环依赖
    from backend.services.ai_service import conversation_history, _get_or_create_history, _history_path
    from backend.services.tools import _registered_layers

    messages = conversation_history.get(session_id, [])
    if not messages:
        return None

    layers = []
    for name, info in _registered_layers.items():
        layers.append({
            "name": name,
            "geojson": info.get("geojson"),
            "geometry_type": ", ".join(info.get("geometry_types", [])),
            "feature_count": info.get("feature_count", 0),
            "source": "ai",
        })

    # 从 index 找这个 session 对应的工程
    index = _load_index()
    existing_pid = None
    for pid, info in index.get("projects", {}).items():
        if info.get("id") == pid:
            proj = _load_project_data(pid)
            if proj and proj.get("sessionId") == session_id:
                existing_pid = pid
                break

    # 取工程名：用第一条用户消息的前 30 字
    name = "未命名工程"
    for msg in messages:
        if msg.get("role") == "user" and msg.get("content"):
            name = msg["content"][:30].strip()
            if len(msg["content"]) > 30:
                name += "…"
            break

    return save_project(
        project_id=existing_pid,
        name=name,
        session_id=session_id,
        provider=provider,
        map_state=map_state or {},
        messages=messages,
        layers=layers,
    )

# 启动时重建引用计数
_rebuild_refcount()
