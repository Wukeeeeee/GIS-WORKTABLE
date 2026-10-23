import os, json, hashlib, gzip, shutil, uuid, datetime, zipfile, io, re, stat, math, threading
from functools import wraps
from urllib.parse import unquote, urlsplit

_PROJECT_LOCK = threading.RLock()


def _with_project_lock(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with _PROJECT_LOCK:
            return func(*args, **kwargs)
    return wrapped

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


def _valid_opacity(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= 1
    except (OverflowError, TypeError):
        return False

# ============================================================
# 路径辅助
# ============================================================

def _ensure_dirs():
    os.makedirs(_BLOB_DIR, exist_ok=True)

def _project_dir(pid: str) -> str:
    if not isinstance(pid, str) or not pid or pid in {".", ".."}:
        raise ValueError("无效 project_id")
    if os.path.basename(pid) != pid or "/" in pid or "\\" in pid or "\0" in pid:
        raise ValueError("无效 project_id")
    root = os.path.realpath(_PROJECT_DIR)
    project_dir = os.path.realpath(os.path.join(root, f"proj_{pid}"))
    try:
        common = os.path.commonpath((root, project_dir))
    except ValueError as exc:
        raise ValueError("无效 project_id") from exc
    if os.path.normcase(common) != os.path.normcase(root):
        raise ValueError("无效 project_id")
    return project_dir

def _project_path(pid: str) -> str:
    return os.path.join(_project_dir(pid), "project.json")

def _blob_path(sha: str) -> str:
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{12}", sha) is None:
        raise ValueError("无效 blob 标识")
    return os.path.join(_BLOB_DIR, f"{sha}.geojson.gz")

def _project_raster_path(pid: str, filename: str) -> str | None:
    if not isinstance(pid, str) or not pid or os.path.basename(pid) != pid:
        return None
    if not isinstance(filename, str) or not filename or os.path.basename(filename) != filename:
        return None
    project_root = os.path.realpath(_PROJECT_DIR)
    try:
        project_dir = os.path.realpath(_project_dir(pid))
        project_common = os.path.commonpath([project_root, project_dir])
    except ValueError:
        return None
    if os.path.normcase(project_common) != os.path.normcase(project_root):
        return None
    assets_dir = os.path.realpath(os.path.join(project_dir, "assets"))
    path = os.path.realpath(os.path.join(assets_dir, filename))
    try:
        assets_common = os.path.commonpath([assets_dir, path])
    except ValueError:
        return None
    return path if os.path.normcase(assets_common) == os.path.normcase(assets_dir) else None

def _raster_source_path(raster: dict) -> str | None:
    asset = raster.get("asset")
    source_pid = raster.get("project_id")
    if asset and source_pid:
        path = _project_raster_path(source_pid, asset)
        return path if path and os.path.isfile(path) else None
    url_path = unquote(urlsplit(str(raster.get("url") or "")).path)
    prefix = "/output/uploads/"
    filename = url_path[len(prefix):] if url_path.startswith(prefix) else ""
    if not filename or os.path.basename(filename) != filename:
        return None
    from backend.services.ai_service import _TEMP_OUTPUT_DIR
    path = os.path.realpath(os.path.join(_TEMP_OUTPUT_DIR, "uploads", filename))
    uploads_dir = os.path.realpath(os.path.join(_TEMP_OUTPUT_DIR, "uploads"))
    return path if os.path.normcase(os.path.commonpath([uploads_dir, path])) == os.path.normcase(uploads_dir) and os.path.isfile(path) else None

def _raster_original_path(raster: dict) -> str | None:
    """Resolve only managed project/upload sources, never arbitrary local paths."""
    original = {"asset": raster.get("source_asset"), "project_id": raster.get("project_id"),
                "url": raster.get("source_url")}
    if not original["url"] and not original["asset"]:
        filename = raster.get("source_filename")
        if isinstance(filename, str) and filename and os.path.basename(filename) == filename:
            from urllib.parse import quote
            original["url"] = "/output/uploads/" + quote(filename, safe='')
    source = _raster_source_path(original)
    return source if source and os.path.splitext(source)[1].lower() in {".tif", ".tiff"} else None


def _raster_asset_names(raster: dict) -> set[str]:
    return {raster[key] for key in ("asset", "source_asset") if isinstance(raster.get(key), str) and raster[key]}


def _store_raster_asset(pid: str, source: str, allowed_extensions: set[str]) -> str:
    extension = os.path.splitext(source)[1].lower()
    if extension not in allowed_extensions:
        raise ValueError("工程栅格资源格式不受支持")
    digest = hashlib.sha256()
    with open(source, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    filename = digest.hexdigest()[:20] + extension
    target = _project_raster_path(pid, filename)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not os.path.exists(target):
        import tempfile
        fd, staging = tempfile.mkstemp(prefix='.raster-', dir=os.path.dirname(target))
        try:
            with os.fdopen(fd, 'wb') as output, open(source, 'rb') as original:
                shutil.copyfileobj(original, output)
            os.replace(staging, target)
        finally:
            if os.path.exists(staging):
                os.unlink(staging)
    return filename


def _store_project_raster(pid: str, raster: dict) -> dict:
    source = _raster_source_path(raster)
    if not source:
        raise ValueError("栅格图层资源不存在，无法保存工程")
    filename = _store_raster_asset(pid, source, {".png", ".jpg", ".jpeg", ".webp"})
    saved = {key: raster[key] for key in ("bounds", "width", "height") if key in raster}
    saved.update({
        "filename": os.path.basename(str(raster.get("filename") or filename)),
        "asset": filename,
        "project_id": pid,
        "url": f"/api/projects/{pid}/assets/{filename}",
    })
    if any(raster.get(key) for key in ("source_asset", "source_url", "source_filename")):
        original = _raster_original_path(raster)
        if not original:
            raise ValueError("栅格原始数据资源不存在，无法保存工程")
        original_asset = _store_raster_asset(pid, original, {".tif", ".tiff"})
        saved.update({"source_asset": original_asset,
                      "source_filename": os.path.basename(str(raster.get("source_filename") or original_asset)),
                      "source_url": f"/api/projects/{pid}/assets/{original_asset}"})
    return saved

@_with_project_lock
def get_project_raster_asset(pid: str, filename: str) -> str | None:
    proj = _load_project_data(pid)
    if not proj or not any(filename in _raster_asset_names(layer.get("raster") or {}) for layer in proj.get("layers", [])):
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
    try:
        path = _blob_path(sha)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)

def _blob_remove(sha: str):
    if not isinstance(sha, str):
        return
    _blob_refcount[sha] = _blob_refcount.get(sha, 0) - 1
    if _blob_refcount[sha] <= 0:
        try:
            path = _blob_path(sha)
        except ValueError:
            _blob_refcount.pop(sha, None)
            return
        if os.path.exists(path):
            os.remove(path)
        _blob_refcount.pop(sha, None)

# ============================================================
# Index 管理
# ============================================================

def _load_index() -> dict:
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            index = json.load(f)
        projects = index.get("projects") if isinstance(index, dict) else None
        if (isinstance(projects, dict)
                and all(isinstance(pid, str) and isinstance(summary, dict)
                        for pid, summary in projects.items())):
            return index
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass

    # Index 可能在旧版本崩溃或手动编辑后损坏；从各工程文件重建摘要，避免服务启动失败。
    projects = {}
    if os.path.isdir(_PROJECT_DIR):
        for entry in os.listdir(_PROJECT_DIR):
            if not entry.startswith("proj_"):
                continue
            pid = entry[len("proj_"):]
            proj = _load_project_data(pid)
            if not proj:
                continue
            messages = proj.get("messages") if isinstance(proj.get("messages"), list) else []
            layers = proj.get("layers") if isinstance(proj.get("layers"), list) else []
            preview = next((extract_clean_title(msg.get("content", ""), 60)
                            for msg in messages
                            if isinstance(msg, dict) and msg.get("role") == "user" and msg.get("content")), "")
            projects[pid] = {
                "id": pid,
                "name": proj.get("name") or f"工程 {pid[:4]}",
                "createdAt": proj.get("createdAt", ""),
                "updatedAt": proj.get("updatedAt", ""),
                "msgPreview": preview,
                "layerCount": len(layers),
                "messageCount": len(messages),
                "provider": proj.get("provider", ""),
            }
    rebuilt = {"projects": projects}
    try:
        _save_index(rebuilt)
    except OSError:
        # Keep serving the recovered view even if the index cannot be repaired on disk.
        pass
    return rebuilt

def _save_index(index: dict):
    _ensure_dirs()
    temp_path = _INDEX_PATH + f".{uuid.uuid4().hex}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, _INDEX_PATH)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def _rebuild_refcount():
    _blob_refcount.clear()
    index = _load_index()
    for pid in index.get("projects", {}):
        proj = _load_project_data(pid)
        if proj and isinstance(proj.get("layers"), list):
            for layer in proj["layers"]:
                if not isinstance(layer, dict):
                    continue
                blob = layer.get("blob")
                if not blob:
                    continue
                try:
                    _blob_path(blob)
                except ValueError:
                    continue
                _blob_refcount[blob] = _blob_refcount.get(blob, 0) + 1

# ============================================================
# 工程 CRUD
# ============================================================

def _generate_id() -> str:
    return uuid.uuid4().hex[:8]

def _now_str() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

def _load_project_data(pid: str) -> dict | None:
    try:
        path = _project_path(pid)
    except ValueError:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None

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

@_with_project_lock
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
        asset
        for layer in (existing or {}).get("layers", [])
        for raster in [layer.get("raster")]
        if isinstance(raster, dict)
        for asset in _raster_asset_names(raster)
    }

    # 存储图层 → CAS blob
    layer_refs = []
    raster_assets = set()
    new_blob_refs = []
    try:
        for idx, layer in enumerate(layers):
            geojson = None if isinstance(layer.get('raster'), dict) else layer.get("geojson") or layer.get("geojson_data")
            if geojson:
                blob = _blob_put(geojson)
                new_blob_refs.append(blob)
            else:
                blob = None
            raster = layer.get("raster") if isinstance(layer.get("raster"), dict) else None
            if raster:
                raster = _store_project_raster(pid, raster)
                raster_assets.update(_raster_asset_names(raster))
            layer_refs.append({
                "layer_id": layer.get("layer_id") if isinstance(layer.get("layer_id"), str) and layer.get("layer_id").strip() else None,
                "name": layer.get("filename") or layer.get("name", "未命名"),
                "blob": blob,
                "color": layer.get("color", "#1c1b1b"),
                "style": layer.get("style") if isinstance(layer.get("style"), dict) else {},
                "opacity": layer.get("opacity") if _valid_opacity(layer.get("opacity")) else 1,
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

    return {"id": pid, "name": sanitized_name, "updatedAt": now}

def _project_exists(pid: str) -> bool:
    try:
        return os.path.exists(_project_path(pid))
    except ValueError:
        return False

def _delete_project_data(pid: str, index: dict = None):
    """删除工程数据，释放 blob 引用"""
    proj = _load_project_data(pid)
    if proj:
        for layer in proj.get("layers", []):
            blob = layer.get("blob")
            if blob:
                _blob_remove(blob)
    try:
        d = _project_dir(pid)
    except ValueError:
        if index is None:
            index = _load_index()
        index["projects"].pop(pid, None)
        _save_index(index)
        return
    if os.path.exists(d):
        shutil.rmtree(d)
    if index is None:
        index = _load_index()
    index["projects"].pop(pid, None)
    _save_index(index)

@_with_project_lock
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
            if raster.get("source_asset"):
                raster["source_url"] = f"/api/projects/{pid}/assets/{raster['source_asset']}"
        resolved_layers.append({
            **layer,
            "geojson": geojson,
            "raster": raster,
        })
    result = {**proj, "layers": resolved_layers}
    return result

@_with_project_lock
def activate_project(pid: str, session_id: str = None) -> dict | None:
    """激活指定工程：加载工程并将其历史消息和图层恢复到后端，实现工程隔离与上下文精准记忆"""
    data = load_project(pid)
    if not data:
        return None
    sid = session_id or data.get("sessionId") or f"proj_{pid}"
    from backend.services.ai_service import conversation_history
    from backend.services import tools as registry
    layers = data.get("layers", [])
    with registry._state_lock:
        old = dict(registry._registered_layers)
        old_project = registry._active_project_id
        old_pending = list(registry._pending_layers)
        old_ops = list(registry._pending_layer_ops)
        try:
            registry.reset_registered_layers(layers)
            registry._active_project_id = pid
            tokens = {name: info.get('registration_token') for name, info in registry._registered_layers.items()}
        except Exception:
            registry._registered_layers.clear()
            registry._registered_layers.update(old)
            registry._active_project_id = old_project
            registry._pending_layers[:] = old_pending
            registry._pending_layer_ops[:] = old_ops
            raise
    conversation_history[sid] = list(data.get("messages", []))
    return {"sessionId": sid, "layerCount": len(data.get("layers", [])),
            "registration_tokens": tokens}

@_with_project_lock
def open_project(pid: str) -> dict | None:
    """Return the same project snapshot whose resources were activated."""
    data = load_project(pid)
    if data is None:
        return None
    activated = activate_project(pid)
    tokens = activated['registration_tokens']
    for layer in data.get('layers', []):
        layer['registration_token'] = tokens.get(layer.get('name') or layer.get('filename'))
    return data


@_with_project_lock
def list_projects() -> list:
    index = _load_index()
    projs = list(index.get("projects", {}).values())
    projs.sort(key=lambda p: p.get("updatedAt", ""), reverse=True)
    return projs

@_with_project_lock
def delete_project(pid: str):
    index = _load_index()
    _delete_project_data(pid, index)

@_with_project_lock
def delete_all_projects():
    index = _load_index()
    for pid in list(index.get("projects", {}).keys()):
        _delete_project_data(pid, index)
    # 清理残留文件夹
    if os.path.isdir(_PROJECT_DIR):
        for d in os.listdir(_PROJECT_DIR):
            full = os.path.join(_PROJECT_DIR, d)
            if d.startswith("proj_") and os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
    global _blob_refcount
    _blob_refcount.clear()

@_with_project_lock
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

@_with_project_lock
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
                try:
                    blob_path = _blob_path(blob)
                except ValueError:
                    continue
                if os.path.exists(blob_path):
                    zf.write(blob_path, f"blobs/{blob}.geojson.gz")
            raster = layer.get("raster")
            for asset in _raster_asset_names(raster) if isinstance(raster, dict) else []:
                if asset in archived_raster_assets:
                    continue
                asset_path = _project_raster_path(pid, asset)
                if not asset_path or not os.path.isfile(asset_path):
                    raise ValueError("工程栅格资源缺失，无法导出完整工程")
                zf.write(asset_path, f"assets/{asset}")
                archived_raster_assets.add(asset)
    buf.seek(0)
    return buf.read()

@_with_project_lock
def import_project(zip_bytes: bytes) -> dict:
    _ensure_dirs()
    pid = _generate_id()
    target_dir = _project_dir(pid)
    os.makedirs(target_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            _extract_project_archive(zf, target_dir)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ValueError("导入的工程文件无效：ZIP 包损坏") from exc
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

    proj_path = os.path.join(target_dir, "project.json")
    if not os.path.exists(proj_path):
        shutil.rmtree(target_dir)
        raise ValueError("导入的工程文件无效：缺少 project.json")

    try:
        with open(proj_path, "r", encoding="utf-8") as f:
            proj_data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ValueError("导入的工程文件无效：project.json 无法读取") from exc
    if (not isinstance(proj_data, dict)
            or not isinstance(proj_data.get("layers", []), list)
            or any(not isinstance(layer, dict) for layer in proj_data.get("layers", []))
            or not isinstance(proj_data.get("messages", []), list)):
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ValueError("导入的工程文件无效：project.json 结构不正确")
    for layer in proj_data.get("layers", []):
        blob = layer.get("blob")
        if blob is not None and (not isinstance(blob, str) or re.fullmatch(r"[0-9a-f]{12}", blob) is None):
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ValueError("导入的工程文件包含无效 blob 标识")
        raster = layer.get("raster")
        if raster is not None and not isinstance(raster, dict):
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ValueError("导入的工程文件包含无效栅格资源")
        for key in ("asset", "source_asset") if isinstance(raster, dict) else []:
            asset = raster.get(key)
            if asset is None:
                continue
            if (not isinstance(asset, str) or not asset
                    or os.path.basename(asset) != asset
                    or any(sep in asset for sep in ("/", "\\", ":", "\0"))):
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ValueError("导入的工程文件包含无效栅格资源路径")
            if not os.path.isfile(os.path.join(target_dir, 'assets', asset)):
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ValueError("导入的工程文件缺少栅格资源")

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

@_with_project_lock
def auto_save(
    session_id: str = "default", provider: str = "", map_state: dict = None,
    project_id: str = None, layer_groups: list | None = None,
    layer_assignments: list | None = None,
):
    """由 ai_service 或前端在每轮对话后调用，自动保存当前会话"""
    from backend.services.ai_service import conversation_history
    from backend.services.tools import _registered_layers, _state_lock

    messages = conversation_history.get(session_id, [])
    if not messages and not project_id and not layer_assignments:
        return None

    existing_proj = None
    layers = []
    allowed_names = None
    if layer_assignments is not None:
        if not isinstance(layer_assignments, list):
            raise ValueError("图层状态必须是列表，未自动保存")
        allowed_names = set()
        for assignment in layer_assignments:
            if not isinstance(assignment, dict):
                raise ValueError("图层状态必须是对象，未自动保存")
            canonical = assignment.get("registry_name")
            aliases = assignment.get("names", [])
            if (canonical is not None and not isinstance(canonical, str)
                    or not isinstance(aliases, list)
                    or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)):
                raise ValueError("图层注册名称格式无效，未自动保存")
            if isinstance(canonical, str) and canonical:
                allowed_names.add(canonical)
            else:
                allowed_names.update(aliases)
            if not canonical and not aliases and not isinstance(assignment.get("raster"), dict):
                raise ValueError("图层缺少注册名称，未自动保存")
    with _state_lock:
        registry = dict(_registered_layers)
    for assignment in layer_assignments or []:
        if isinstance(assignment.get("raster"), dict):
            continue
        canonical = assignment.get("registry_name")
        matches = [canonical] if canonical else assignment.get("names", [])
        if not any(name in registry for name in matches):
            raise ValueError("图层「%s」尚未完成注册，未自动保存" % (canonical or assignment.get("name") or "未命名"))
    for name, info in registry.items():
        if allowed_names is not None and name not in allowed_names:
            continue
        layers.append({
            "name": name,
            "geojson": info.get("geojson"),
            "raster": info.get("raster"),
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
        if session_id not in conversation_history and existing_proj:
            messages = existing_proj.get("messages", [])
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
                    "opacity": assignment.get("opacity") if _valid_opacity(assignment.get("opacity")) else None,
                    "symbology": assignment.get("symbology") if isinstance(assignment.get("symbology"), dict) else None,
                    "has_symbology": "symbology" in assignment,
                    "raster": assignment.get("raster") if isinstance(assignment.get("raster"), dict) else None,
                    "name": assignment.get("name"),
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
            if assignment["opacity"] is not None:
                layer["opacity"] = assignment["opacity"]
            else:
                layer["opacity"] = (previous or {}).get("opacity", 1)
            if assignment["has_symbology"]:
                layer["symbology"] = assignment["symbology"]
            elif previous and previous.get("symbology"):
                layer["symbology"] = previous["symbology"]
            if assignment["raster"]:
                layer["raster"] = assignment["raster"]
                layer['name'] = assignment['name'] or layer_name
        else:
            previous = existing_layers_by_name.get(layer_name)
            if previous:
                layer["groupId"] = previous.get("groupId")
                layer["layer_id"] = previous.get("layer_id")
                layer["style"] = previous.get("style", {})
                layer["opacity"] = previous.get("opacity", 1)
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
            "opacity": assignment.get("opacity") if _valid_opacity(assignment.get("opacity")) else 1,
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
