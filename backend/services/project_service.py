import os, json, hashlib, gzip, shutil, uuid, datetime, zipfile, io, re, stat, math, threading
from functools import wraps
from contextlib import contextmanager
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from backend.services.url_security import sanitize_http_url

_PROJECT_LOCK = threading.RLock()
_PROJECT_LOCK_STATE = threading.local()


@contextmanager
def _cross_process_project_lock():
    """Serialize project-store operations across app instances sharing a store."""
    import tempfile
    import time

    lock_key = hashlib.sha256(os.path.normcase(os.path.abspath(_PROJECT_DIR)).encode("utf-8")).hexdigest()
    lock_path = os.path.join(tempfile.gettempdir(), f"gis-worktable-project-{lock_key}.lock")
    with open(lock_path, "a+b") as lock_file:
        if os.path.getsize(lock_path) == 0:
            lock_file.write(b"0")
            lock_file.flush()

        try:
            import msvcrt
        except ImportError:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        else:
            while True:
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


class ProjectOpenSuperseded(Exception):
    """Raised when a newer project-open request supersedes this one."""


class ProjectActivationBusy(Exception):
    """Raised when the shared GIS operation lock cannot be acquired."""


def _with_project_lock(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with _PROJECT_LOCK:
            depth = getattr(_PROJECT_LOCK_STATE, "depth", 0)
            if depth:
                _PROJECT_LOCK_STATE.depth = depth + 1
                try:
                    return func(*args, **kwargs)
                finally:
                    _PROJECT_LOCK_STATE.depth = depth
            with _cross_process_project_lock():
                _PROJECT_LOCK_STATE.depth = 1
                try:
                    return func(*args, **kwargs)
                finally:
                    _PROJECT_LOCK_STATE.depth = 0
    return wrapped


def _project_service_metadata(layer: dict) -> dict:
    """Persist reconnectable service metadata without access-bearing URL values."""
    raw_url = layer.get("url") or layer.get("service_url") or ""
    auth_parameter = layer.get("auth_parameter")
    has_url_credentials = False
    try:
        raw_parts = urlsplit(str(raw_url))
        has_url_credentials = raw_parts.username is not None or raw_parts.password is not None
        if not isinstance(auth_parameter, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", auth_parameter):
            auth_parameter = next((key for key, _ in parse_qsl(raw_parts.query, keep_blank_values=True)
                                   if re.search(r"token|api[_-]?key|password|secret|auth|credential|signature|^key$", key, re.I)), "")
    except (TypeError, ValueError):
        has_url_credentials = False
        if not isinstance(auth_parameter, str):
            auth_parameter = ""
    safe_url = sanitize_http_url(raw_url)
    if not isinstance(auth_parameter, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", auth_parameter):
        auth_parameter = ""

    if safe_url and auth_parameter:
        try:
            parts = urlsplit(safe_url)
            query = [
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if key.lower() != auth_parameter.lower()
            ]
            safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        except (TypeError, ValueError):
            pass

    return {
        "url": safe_url,
        "requires_auth": layer.get("requires_auth") is True or bool(auth_parameter) or has_url_credentials,
        "auth_parameter": auth_parameter,
    }


def _sanitize_project_service_layers(project: dict) -> dict:
    """Return a project copy with service URLs cleaned, including legacy imports."""
    cleaned = dict(project)
    layers = []
    for layer in project.get("layers", []):
        if not isinstance(layer, dict):
            layers.append(layer)
            continue
        item = dict(layer)
        if item.get("url") or item.get("service_url"):
            metadata = _project_service_metadata(item)
            item.update(metadata)
            if "service_url" in item:
                item["service_url"] = metadata["url"]
        layers.append(item)
    cleaned["layers"] = layers
    return cleaned

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
# Imported project archives are user-selected ZIPs. Keep decompression bounded
# while leaving room for several source rasters in a portable GIS project.
_MAX_PROJECT_ARCHIVE_ENTRIES = 10000
_MAX_PROJECT_ARCHIVE_COMPRESSED_BYTES = 1024 * 1024 * 1024
_MAX_PROJECT_ARCHIVE_EXPANDED_BYTES = 1024 * 1024 * 1024
_MAX_PROJECT_BLOB_EXPANDED_BYTES = 1024 * 1024 * 1024
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)}
    | {f"{prefix}{digit}" for prefix in ("com", "lpt") for digit in ("¹", "²", "³")}
)


def _is_windows_reserved_path_component(component: str) -> bool:
    """Whether a portable path component aliases a Windows device, extension or not."""
    stem = component.split(".", 1)[0].rstrip(" .").casefold()
    return stem in _WINDOWS_RESERVED_DEVICE_NAMES

# 内存引用计数（启动时从 index.json 重建）
_blob_refcount = {}


def _valid_opacity(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= 1
    except (OverflowError, TypeError):
        return False


def _sanitize_label_config(value):
    if not isinstance(value, dict):
        return None
    field = value.get("field")
    font_size = value.get("fontSize", 12)
    color = value.get("color", "#333333")
    if not isinstance(field, str) or not field or len(field) > 256:
        return None
    if isinstance(font_size, bool) or not isinstance(font_size, (int, float)) or not math.isfinite(font_size) or not 6 <= font_size <= 48:
        return None
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        return None
    return {"field": field, "fontSize": font_size, "color": color}

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

def _project_assets_dir(pid: str) -> str | None:
    try:
        project_dir = _project_dir(pid)
    except ValueError:
        return None
    expected = os.path.abspath(os.path.join(project_dir, "assets"))
    assets_dir = os.path.realpath(expected)
    # The managed assets directory is a normal child directory. Reject a
    # symlink/junction replacement even when its target is another in-project
    # path, so reads and cleanup remain anchored to this project's directory.
    return assets_dir if os.path.normcase(assets_dir) == os.path.normcase(expected) else None

def _blob_path(sha: str) -> str:
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{12}", sha) is None:
        raise ValueError("无效 blob 标识")
    return os.path.join(_BLOB_DIR, f"{sha}.geojson.gz")

def _project_raster_path(pid: str, filename: str) -> str | None:
    if not isinstance(pid, str) or not pid or os.path.basename(pid) != pid:
        return None
    if not isinstance(filename, str) or not filename or os.path.basename(filename) != filename:
        return None
    try:
        project_dir = _project_dir(pid)
    except ValueError:
        return None
    assets_dir = _project_assets_dir(pid)
    if assets_dir is None:
        return None
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
    if target is None:
        raise ValueError("工程栅格资源路径无效")
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
    # Keep the inspectable raster metadata alongside its managed preview/source
    # assets. Dropping these fields on save made a restored result lose its CRS,
    # units, processing label and quality warnings in the layer inspector.
    metadata_fields = (
        "bounds", "width", "height", "crs", "source_width", "source_height",
        "preview_width", "preview_height", "preview_only", "source_name",
        "preview_downsampled", "bands", "nodata", "pixel_size", "pixel_units",
        "value_units", "vertical_datum", "source_layer", "source_label",
        "source_reference", "processing", "valid_pixel_ratio", "quality_warnings",
    )
    saved = {key: raster[key] for key in metadata_fields if key in raster}
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
    assets_dir = _project_assets_dir(pid)
    if assets_dir is None or not os.path.isdir(assets_dir):
        return
    for filename in os.listdir(assets_dir):
        if filename in keep_assets:
            continue
        try:
            os.unlink(os.path.join(assets_dir, filename))
        except OSError:
            pass

def _extract_project_archive(zf: zipfile.ZipFile, target_dir: str):
    import unicodedata

    root = os.path.realpath(target_dir)
    members = zf.infolist()
    if len(members) > _MAX_PROJECT_ARCHIVE_ENTRIES:
        raise ValueError(f"导入的工程文件条目过多（最多 {_MAX_PROJECT_ARCHIVE_ENTRIES} 项）")
    expanded_size = sum(member.file_size for member in members)
    if expanded_size > _MAX_PROJECT_ARCHIVE_EXPANDED_BYTES:
        limit_mb = _MAX_PROJECT_ARCHIVE_EXPANDED_BYTES // (1024 * 1024)
        raise ValueError(f"导入的工程解压后超过 {limit_mb} MB 限制")

    normalized_members = set()
    file_marker = object()
    path_tree = {}
    windows_name_translation = str.maketrans(':<>|"?*', '_' * 7)
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
        # ZipFile applies these transformations when extracting on Windows.
        # Reject aliases consistently on every host so later entries cannot
        # silently replace project.json or an asset from an earlier entry.
        safe_parts = [part.translate(windows_name_translation).rstrip(" .") for part in parts]
        if any(_is_windows_reserved_path_component(part) for part in safe_parts):
            raise ValueError("导入的工程文件包含 Windows 保留设备名")
        normalized_name = unicodedata.normalize(
            "NFC", "/".join(part for part in safe_parts if part)
        ).casefold()
        if not normalized_name:
            raise ValueError("导入的工程文件包含无法安全解压的路径")
        if normalized_name in normalized_members:
            raise ValueError("导入的工程文件包含重复的文件路径")
        normalized_parts = normalized_name.split("/")
        node = path_tree
        for part in normalized_parts:
            if node.get(file_marker):
                raise ValueError("导入的工程文件包含文件与目录路径冲突")
            node = node.setdefault(part, {})
        if not member.is_dir() and node:
            raise ValueError("导入的工程文件包含文件与目录路径冲突")
        normalized_members.add(normalized_name)
        if not member.is_dir():
            node[file_marker] = True
        destination = os.path.realpath(os.path.join(root, *parts))
        try:
            common_root = os.path.commonpath([root, destination])
        except ValueError as error:
            raise ValueError("导入的工程文件包含不安全路径") from error
        if common_root != root:
            raise ValueError("导入的工程文件包含不安全路径")
    zf.extractall(root)


class _ProjectArchiveLimitError(ValueError):
    """An imported project exceeds a decompression limit."""

# ============================================================
# CAS Blob 存储
# ============================================================

def _blob_put(geojson: dict) -> str:
    raw = json.dumps(geojson, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(raw.encode()).hexdigest()[:12]
    path = _blob_path(sha)
    if os.path.isfile(path) and _blob_file_matches_digest(path, sha):
        _blob_refcount[sha] = _blob_refcount.get(sha, 0) + 1
        return sha

    import tempfile
    fd, staging = tempfile.mkstemp(prefix=f".{sha}.", suffix=".tmp", dir=_BLOB_DIR)
    os.close(fd)
    try:
        with gzip.open(staging, "wt", encoding="utf-8") as f:
            f.write(raw)
        # A failed or interrupted write must never leave a partial blob at its
        # content-addressed path. Replace a corrupt leftover atomically on retry.
        os.replace(staging, path)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)
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


def _blob_reference_count_on_disk(sha: str) -> int | None:
    """Return an authoritative count, or None when a project cannot be inspected safely."""
    try:
        _blob_path(sha)
    except ValueError:
        return 0
    count = 0
    if not os.path.exists(_PROJECT_DIR):
        return 0
    try:
        entries = os.listdir(_PROJECT_DIR)
    except OSError:
        return None
    for entry in entries:
        if not entry.startswith("proj_"):
            continue
        pid = entry[len("proj_"):]
        try:
            project_dir = _project_dir(pid)
        except ValueError:
            continue
        if not os.path.isdir(project_dir):
            continue
        project = _load_project_data(pid)
        if project is None:
            return None
        layers = project.get("layers")
        if layers is None:
            continue
        if not isinstance(layers, list):
            return None
        count += sum(1 for layer in layers if isinstance(layer, dict) and layer.get("blob") == sha)
    return count


def _blob_file_matches_digest(path: str, sha: str) -> bool:
    try:
        digest = hashlib.sha256()
        with gzip.open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()[:12] == sha
    except Exception:
        return False

def _blob_remove(sha: str):
    if not isinstance(sha, str):
        return True
    _blob_refcount[sha] = _blob_refcount.get(sha, 0) - 1
    if _blob_refcount[sha] > 0:
        return True
    disk_refcount = _blob_reference_count_on_disk(sha)
    if disk_refcount is None:
        # A project with an unreadable file may still reference this Blob.
        # Preserve it until the project can be inspected safely.
        _blob_refcount[sha] = 1
        return True
    if disk_refcount > 0:
        _blob_refcount[sha] = disk_refcount
        return True
    try:
        path = _blob_path(sha)
    except ValueError:
        _blob_refcount.pop(sha, None)
        return True
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        # The referring project is already gone; keep the cache orphaned but do
        # not leave a negative in-memory reference count behind.
        _blob_refcount.pop(sha, None)
        return False
    _blob_refcount.pop(sha, None)
    return True

# ============================================================
# Index 管理
# ============================================================

def _project_index_summary(pid: str, proj: dict) -> dict:
    messages = proj.get("messages") if isinstance(proj.get("messages"), list) else []
    layers = proj.get("layers") if isinstance(proj.get("layers"), list) else []
    preview = next((extract_clean_title(msg.get("content", ""), 60)
                    for msg in messages
                    if isinstance(msg, dict) and msg.get("role") == "user" and msg.get("content")), "")
    return {
        "id": pid,
        "name": proj.get("name") or f"工程 {pid[:4]}",
        "createdAt": proj.get("createdAt", ""),
        "updatedAt": proj.get("updatedAt", ""),
        "msgPreview": preview,
        "layerCount": len(layers),
        "messageCount": len(messages),
        "provider": proj.get("provider", ""),
    }


def _project_index_matches_files(index: dict) -> bool:
    summaries = index.get("projects") if isinstance(index, dict) else None
    if not isinstance(summaries, dict) or not os.path.isdir(_PROJECT_DIR):
        return False
    valid_project_ids = set()
    for entry in os.listdir(_PROJECT_DIR):
        if not entry.startswith("proj_"):
            continue
        pid = entry[len("proj_"):]
        try:
            if not os.path.isdir(_project_dir(pid)):
                continue
        except ValueError:
            continue
        proj = _load_project_data(pid)
        if proj is None:
            continue
        valid_project_ids.add(pid)
        if summaries.get(pid) != _project_index_summary(pid, proj):
            return False
    # A missing/corrupt project file should retain its existing summary so the
    # user can see that a project needs recovery; only remove entries whose
    # project directory is actually gone.
    for pid in summaries:
        try:
            if not os.path.isdir(_project_dir(pid)):
                return False
        except ValueError:
            return False
    return valid_project_ids.issubset(summaries)


def _load_index() -> dict:
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            index = json.load(f)
        projects = index.get("projects") if isinstance(index, dict) else None
        if (isinstance(projects, dict)
                and all(isinstance(pid, str) and isinstance(summary, dict)
                        for pid, summary in projects.items())):
            if _project_index_matches_files(index):
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
            projects[pid] = _project_index_summary(pid, proj)
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


def _allocate_project_id() -> str:
    """Choose an unused project directory while holding the project lock."""
    for _ in range(128):
        pid = _generate_id()
        candidate = os.path.join(_PROJECT_DIR, f"proj_{pid}")
        if os.path.lexists(candidate):
            continue
        _project_dir(pid)  # Validate the ID before the caller creates its directory.
        return pid
    raise RuntimeError("无法分配唯一工程 ID")

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
        pid = _allocate_project_id()
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
                _validate_project_vector_coordinates(geojson)
                blob = _blob_put(geojson)
                new_blob_refs.append(blob)
            else:
                blob = None
            raster = layer.get("raster") if isinstance(layer.get("raster"), dict) else None
            if raster:
                raster = _store_project_raster(pid, raster)
                raster_assets.update(_raster_asset_names(raster))
            service_metadata = _project_service_metadata(layer)
            if blob is None and raster is None and not service_metadata["url"]:
                raise ValueError("工程图层缺少矢量、栅格或服务数据")
            layer_refs.append({
                "layer_id": layer.get("layer_id") if isinstance(layer.get("layer_id"), str) and layer.get("layer_id").strip() else None,
                "name": layer.get("filename") or layer.get("name", "未命名"),
                "blob": blob,
                "color": layer.get("color", "#1c1b1b"),
                "style": layer.get("style") if isinstance(layer.get("style"), dict) else {},
                "opacity": layer.get("opacity") if _valid_opacity(layer.get("opacity")) else 1,
                "symbology": layer.get("symbology") if isinstance(layer.get("symbology"), dict) else None,
                "labels": _sanitize_label_config(layer.get("labels")) if isinstance(layer.get("labels"), dict) else None,
                "visible": layer.get("visible", True) if layer.get("visible") is not False else False,
                "geometry_type": layer.get("geometry_type", "未知"),
                "source": layer.get("source", "ai"),
                "provenance": layer.get("provenance") if isinstance(layer.get("provenance"), dict) else None,
                "order": idx,
                "url": service_metadata["url"],
                "service_type": layer.get("service_type") or layer.get("protocol") or "",
                "sublayer": layer.get("sublayer") or layer.get("sublayer_name") or "",
                "requires_auth": service_metadata["requires_auth"],
                "auth_parameter": service_metadata["auth_parameter"],
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

    assets_dir = _project_assets_dir(pid)
    if assets_dir and os.path.isdir(assets_dir):
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
        # The current save must survive even when timestamps have only
        # second-level precision and tie with an older project.
        older_projects = ((old_pid, summary) for old_pid, summary in projs.items() if old_pid != pid)
        sorted_items = sorted(older_projects, key=lambda x: x[1].get("updatedAt", ""))
        for old_pid, _ in sorted_items[:max(0, len(projs) - _MAX_PROJECTS)]:
            _delete_project_data(old_pid, index, persist_index=False)
    index_warning = None
    try:
        _save_index(index)
    except OSError:
        # The project file is already the durable source of truth. The index is
        # a rebuildable summary, so do not report a committed save as failed.
        index_warning = "工程内容已保存，但最近工程列表暂未写入索引；刷新列表会从工程文件恢复。"

    result = {"id": pid, "name": sanitized_name, "updatedAt": now}
    if index_warning:
        result["warning"] = index_warning
    return result

def _project_exists(pid: str) -> bool:
    try:
        return os.path.exists(_project_path(pid))
    except ValueError:
        return False


def _validate_project_vector_coordinates(geojson: dict) -> None:
    """Reject vector layers whose coordinates cannot be interpreted as WGS-84."""
    try:
        from backend.services.tools import _validate_wgs84_geojson
        _validate_wgs84_geojson(geojson)
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
        raise ValueError("工程矢量图层坐标超出 WGS-84 范围或格式无效")

def _delete_project_data(pid: str, index: dict = None, persist_index: bool = True):
    """删除工程数据，释放 blob 引用"""
    proj = _load_project_data(pid)
    try:
        d = _project_dir(pid)
    except ValueError:
        # _project_dir intentionally rejects links that resolve outside the
        # project root. A direct delete should still remove the link itself,
        # without following it or touching anything in its target.
        if (isinstance(pid, str) and pid and os.path.basename(pid) == pid
                and "/" not in pid and "\\" not in pid and "\0" not in pid):
            link_path = os.path.join(_PROJECT_DIR, f"proj_{pid}")
            if os.path.islink(link_path):
                os.unlink(link_path)
        if index is None:
            index = _load_index()
        index["projects"].pop(pid, None)
        if persist_index:
            try:
                _save_index(index)
            except OSError:
                return "工程已删除，但最近工程列表索引暂未更新；刷新列表会从工程文件恢复。"
        return None
    if os.path.exists(d):
        shutil.rmtree(d)
    # Keep referenced blobs intact until the project directory is gone. If
    # removing the directory fails, the project remains readable and retains
    # its vector data. A failed blob unlink after this point only leaves an
    # orphaned blob, which is safer than a project pointing at missing data.
    blob_cleanup_failed = False
    if proj:
        layers = proj.get("layers")
        for layer in layers if isinstance(layers, list) else []:
            if not isinstance(layer, dict):
                continue
            blob = layer.get("blob")
            if blob:
                if not _blob_remove(blob):
                    blob_cleanup_failed = True
    if index is None:
        index = _load_index()
    index["projects"].pop(pid, None)
    warnings = []
    if blob_cleanup_failed:
        warnings.append("工程已删除，但未能清理无引用的矢量 Blob 缓存。")
    if persist_index:
        try:
            _save_index(index)
        except OSError:
            # The project directory is the source of truth. Listing projects
            # detects the stale summary and reconstructs the index from disk.
            warnings.append("最近工程列表索引暂未更新；刷新列表会从工程文件恢复。")
    return "；".join(warnings) if warnings else None


def _deactivate_deleted_project(pid: str):
    """Drop in-memory GIS state when its owning project has been removed."""
    from backend.services import tools as registry

    with registry._state_lock:
        if registry._active_project_id == pid:
            registry.reset_registered_layers([])

@_with_project_lock
def load_project(pid: str) -> dict | None:
    proj = _load_project_data(pid)
    if not proj:
        return None
    proj = _sanitize_project_service_layers(proj)
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


def _restorable_project_messages(messages):
    if not isinstance(messages, list):
        return []
    return [
        message for message in messages
        if isinstance(message, dict)
        and message.get("role") in {"user", "assistant"}
        and isinstance(message.get("content"), str)
    ]

def _activate_project_data(pid: str, data: dict, session_id: str = None) -> dict:
    """Activate an already loaded snapshot without resolving its resources again."""
    sid = session_id or data.get("sessionId") or f"proj_{pid}"
    from backend.services.ai_service import conversation_history
    from backend.services import tools as registry
    layers = data.get("layers", [])
    skipped_layers = []
    restorable_layers = []
    for layer in layers:
        geojson = layer.get("geojson") or layer.get("geojson_data") if isinstance(layer, dict) else None
        if geojson:
            try:
                _validate_project_vector_coordinates(geojson)
            except ValueError:
                skipped_layers.append(layer.get("name") or layer.get("filename") or "图层")
                continue
        restorable_layers.append(layer)
    with registry._state_lock:
        old = dict(registry._registered_layers)
        old_project = registry._active_project_id
        old_pending = list(registry._pending_layers)
        old_ops = list(registry._pending_layer_ops)
        try:
            skipped_layers.extend(registry.reset_registered_layers(restorable_layers, tolerate_invalid=True))
            registry._active_project_id = pid
            tokens = {name: info.get('registration_token') for name, info in registry._registered_layers.items()}
        except Exception:
            registry._registered_layers.clear()
            registry._registered_layers.update(old)
            registry._active_project_id = old_project
            registry._pending_layers[:] = old_pending
            registry._pending_layer_ops[:] = old_ops
            raise
    conversation_history[sid] = _restorable_project_messages(data.get("messages", []))
    return {"sessionId": sid, "layerCount": len(data.get("layers", [])),
            "registration_tokens": tokens, "registration_warnings": skipped_layers}


@_with_project_lock
def activate_project(pid: str, session_id: str = None) -> dict | None:
    """激活指定工程：加载工程并将其历史消息和图层恢复到后端，实现工程隔离与上下文精准记忆"""
    data = load_project(pid)
    if not data:
        return None
    from backend.services import tools as registry
    if not registry.acquire_shared_state_lock():
        raise ProjectActivationBusy(pid)
    try:
        return _activate_project_data(pid, data, session_id)
    finally:
        registry.release_shared_state_lock()


@_with_project_lock
def open_project(pid: str, should_activate=None) -> dict | None:
    """Return and activate one project snapshot, resolving resources only once."""
    data = load_project(pid)
    if data is None:
        return None
    if should_activate is not None and not should_activate():
        raise ProjectOpenSuperseded(pid)
    from backend.services import tools as registry
    if not registry.acquire_shared_state_lock():
        raise ProjectActivationBusy(pid)
    try:
        # Direct panel tools do not use chat cancellation. Serialize activation
        # with their shared-state transaction and recheck after waiting so a
        # superseded open cannot activate over a newer request.
        if should_activate is not None and not should_activate():
            raise ProjectOpenSuperseded(pid)
        if should_activate is None:
            activated = _activate_project_data(pid, data)
        else:
            from backend.services.ai_service import conversation_history
            sid = data.get("sessionId") or f"proj_{pid}"
            with registry._state_lock:
                old_layers = dict(registry._registered_layers)
                old_project = registry._active_project_id
                old_pending = list(registry._pending_layers)
                old_ops = list(registry._pending_layer_ops)
                had_history = sid in conversation_history
                old_history = conversation_history.get(sid)
                activated = _activate_project_data(pid, data)
                if not should_activate():
                    registry._registered_layers.clear()
                    registry._registered_layers.update(old_layers)
                    registry._active_project_id = old_project
                    registry._pending_layers[:] = old_pending
                    registry._pending_layer_ops[:] = old_ops
                    if had_history:
                        conversation_history[sid] = old_history
                    else:
                        conversation_history.pop(sid, None)
                    raise ProjectOpenSuperseded(pid)
    finally:
        registry.release_shared_state_lock()
    tokens = activated['registration_tokens']
    data['registration_warnings'] = activated.get('registration_warnings', [])
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
    warning = _delete_project_data(pid, index)
    _deactivate_deleted_project(pid)
    return {"warning": warning} if warning else {}

@_with_project_lock
def delete_all_projects():
    index = _load_index()
    failed_ids = set()
    cleanup_warnings = []
    for pid in list(index.get("projects", {}).keys()):
        try:
            warning = _delete_project_data(pid, index, persist_index=False)
            if warning:
                cleanup_warnings.append(warning)
        except OSError:
            failed_ids.add(pid)
    # 清理索引外的工程目录。目录删除失败时保留数据并报告部分失败。
    if os.path.isdir(_PROJECT_DIR):
        for d in os.listdir(_PROJECT_DIR):
            full = os.path.join(_PROJECT_DIR, d)
            if not d.startswith("proj_"):
                continue
            pid = d[len("proj_"):]
            if os.path.islink(full):
                # Remove only the project-root link itself; never traverse its target.
                try:
                    os.unlink(full)
                except OSError:
                    failed_ids.add(pid)
                continue
            if os.path.isdir(full):
                try:
                    shutil.rmtree(full)
                except OSError:
                    failed_ids.add(pid)

    def _project_directory_remains(pid):
        try:
            return os.path.isdir(_project_dir(pid))
        except ValueError:
            # Invalid or escaped project entries must not crash the bulk delete.
            return True

    failed_ids = {pid for pid in failed_ids if _project_directory_remains(pid)}
    from backend.services import tools as registry
    if registry._active_project_id and not _project_exists(registry._active_project_id):
        _deactivate_deleted_project(registry._active_project_id)

    remaining_projects = {}
    if os.path.isdir(_PROJECT_DIR):
        for d in os.listdir(_PROJECT_DIR):
            if not d.startswith("proj_"):
                continue
            pid = d[len("proj_"):]
            proj = _load_project_data(pid)
            if proj:
                remaining_projects[pid] = _project_index_summary(pid, proj)
    try:
        _save_index({"projects": remaining_projects})
    except OSError:
        if not failed_ids:
            _blob_refcount.clear()
            cleanup_warnings.append("工程已删除，但最近工程列表索引暂未更新；刷新列表会从工程文件恢复。")
        else:
            cleanup_warnings.append("最近工程列表索引暂未更新；刷新列表会从工程文件恢复。")
    if failed_ids:
        # Recount from project files so blobs referenced by undeleted projects stay alive.
        _rebuild_refcount()
        return {
            "success": False,
            "warning": "；".join([
                f"有 {len(failed_ids)} 个工程未能删除；其余工程已删除，请稍后重试。",
                *cleanup_warnings,
            ]),
        }
    _blob_refcount.clear()
    return {"warning": "；".join(cleanup_warnings)} if cleanup_warnings else {}

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
    result = {"id": pid, "name": new_name}
    try:
        _save_index(index)
    except OSError:
        result["warning"] = "工程名称已修改，但最近工程列表索引未能写入；刷新列表会从工程文件恢复。"
    return result

@_with_project_lock
def export_project(pid: str) -> bytes:
    proj = _load_project_data(pid)
    if not proj:
        return None
    proj = _sanitize_project_service_layers(proj)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 工程数据
        zf.writestr("project.json", json.dumps(proj, ensure_ascii=False, indent=2))
        archived_raster_assets = set()
        archived_vector_blobs = set()
        # 包含图层 blob
        for layer in proj.get("layers", []):
            blob = layer.get("blob")
            if blob is not None and blob not in archived_vector_blobs:
                try:
                    blob_path = _blob_path(blob)
                except ValueError as exc:
                    raise ValueError("工程包含无效矢量图层数据，无法导出完整工程") from exc
                if not os.path.isfile(blob_path):
                    raise ValueError("工程矢量图层数据缺失，无法导出完整工程")
                try:
                    digest = hashlib.sha256()
                    with gzip.open(blob_path, "rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                except Exception as exc:
                    raise ValueError("工程矢量图层数据无效，无法导出完整工程") from exc
                if digest.hexdigest()[:12] != blob:
                    raise ValueError("工程矢量图层数据校验失败，无法导出完整工程")
                zf.write(blob_path, f"blobs/{blob}.geojson.gz")
                archived_vector_blobs.add(blob)
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
def import_project(zip_bytes) -> dict:
    _ensure_dirs()
    if len(_load_index().get("projects", {})) >= _MAX_PROJECTS:
        raise ValueError(f"工程数量已达到上限（最多 {_MAX_PROJECTS} 个）；请先删除不需要的工程后再导入")
    pid = _allocate_project_id()
    target_dir = _project_dir(pid)
    os.makedirs(target_dir, exist_ok=True)

    try:
        if hasattr(zip_bytes, "read"):
            zip_bytes.seek(0)
            zip_bytes.seek(0, io.SEEK_END)
            compressed_size = zip_bytes.tell()
            zip_bytes.seek(0)
            archive_source = zip_bytes
        else:
            compressed_size = len(zip_bytes)
            archive_source = io.BytesIO(zip_bytes)
        if compressed_size > _MAX_PROJECT_ARCHIVE_COMPRESSED_BYTES:
            limit_mb = _MAX_PROJECT_ARCHIVE_COMPRESSED_BYTES // (1024 * 1024)
            raise ValueError(f"导入的工程压缩包超过 {limit_mb} MB 限制")
        with zipfile.ZipFile(archive_source) as zf:
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
    if not isinstance(proj_data.get("name"), str):
        proj_data["name"] = f"导入工程 {pid[:4]}"
    proj_data = _sanitize_project_service_layers(proj_data)
    verified_blobs = set()
    expanded_blob_bytes = 0
    for layer in proj_data.get("layers", []):
        blob = layer.get("blob")
        raster = layer.get("raster")
        service_url = layer.get("url") or layer.get("service_url")
        if blob is None and raster is None and not service_url:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ValueError("导入的工程文件缺少矢量图层数据")
        if blob is not None and (not isinstance(blob, str) or re.fullmatch(r"[0-9a-f]{12}", blob) is None):
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ValueError("导入的工程文件包含无效 blob 标识")
        if blob and blob not in verified_blobs:
            blob_path = os.path.join(target_dir, "blobs", blob + ".geojson.gz")
            if not os.path.isfile(blob_path):
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ValueError("导入的工程文件缺少矢量图层数据")
            try:
                digest = hashlib.sha256()
                with gzip.open(blob_path, "rb") as source:
                    while True:
                        remaining = _MAX_PROJECT_BLOB_EXPANDED_BYTES - expanded_blob_bytes
                        chunk = source.read(min(1024 * 1024, remaining + 1))
                        if not chunk:
                            break
                        expanded_blob_bytes += len(chunk)
                        if expanded_blob_bytes > _MAX_PROJECT_BLOB_EXPANDED_BYTES:
                            raise _ProjectArchiveLimitError(
                                "导入的工程矢量数据解压后超过 1024 MB 限制"
                            )
                        digest.update(chunk)
            except _ProjectArchiveLimitError:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise
            except Exception as exc:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ValueError("导入的工程文件包含无效矢量图层数据") from exc
            if digest.hexdigest()[:12] != blob:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ValueError("导入的工程文件包含不匹配的矢量图层数据")
            try:
                with gzip.open(blob_path, "rt", encoding="utf-8") as source:
                    parsed_blob = json.load(source)
                if not isinstance(parsed_blob, dict):
                    raise ValueError("矢量 Blob 根节点必须是对象")
            except Exception as exc:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ValueError("导入的工程文件包含无效矢量图层数据") from exc
            verified_blobs.add(blob)
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
    newly_migrated_blobs = []
    try:
        if os.path.exists(imported_blobs):
            for blob_name in sorted(verified_blobs):
                fname = f"{blob_name}.geojson.gz"
                src = os.path.join(imported_blobs, fname)
                dst = os.path.join(_BLOB_DIR, fname)
                if os.path.exists(dst) and not _blob_file_matches_digest(dst, blob_name):
                    temp_path = dst + f".{uuid.uuid4().hex}.tmp"
                    try:
                        shutil.copy2(src, temp_path)
                        os.replace(temp_path, dst)
                    finally:
                        try:
                            os.unlink(temp_path)
                        except OSError:
                            pass
                elif not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        try:
                            os.unlink(dst)
                        except OSError:
                            pass
                        raise
                    newly_migrated_blobs.append(dst)
            shutil.rmtree(imported_blobs)

        proj_data["id"] = pid
        now = _now_str()
        proj_data["createdAt"] = now
        proj_data["updatedAt"] = now
        _save_project_data(pid, proj_data)
    except Exception:
        # If the project JSON did not become durable, remove its staging tree
        # and only the global blobs this import created. Keep pre-existing or
        # currently referenced blobs intact.
        if _load_project_data(pid) != proj_data:
            shutil.rmtree(target_dir, ignore_errors=True)
            for path in newly_migrated_blobs:
                blob_name = os.path.basename(path).split(".", 1)[0]
                disk_refcount = _blob_reference_count_on_disk(blob_name)
                if disk_refcount is None or disk_refcount > 0:
                    if disk_refcount is not None:
                        _blob_refcount[blob_name] = disk_refcount
                    continue
                try:
                    os.unlink(path)
                except OSError:
                    pass
                _blob_refcount.pop(blob_name, None)
        raise

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
    warning = None
    try:
        _save_index(index)
    except OSError:
        # The project file is already durable; listing can rebuild this summary from it.
        warning = "工程已导入，但最近工程列表索引暂未更新；刷新列表会从工程文件恢复。"
    _rebuild_refcount()
    result = {"id": pid, "name": proj_data.get("name", "导入工程")}
    if warning:
        result["warning"] = warning
    return result

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
            if "labels" in assignment and assignment["labels"] is not None and _sanitize_label_config(assignment["labels"]) is None:
                raise ValueError("图层标注配置无效，未自动保存")
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
            **({"provenance": dict(info["provenance"])} if isinstance(info.get("provenance"), dict) else {}),
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
    if layer_assignments is None and existing_proj:
        # A caller that omits panel assignments has not declared that the
        # current layer set is empty. Merge stored layers absent from the live
        # registry so older clients and backend-only autosaves cannot erase
        # project data merely because their registry snapshot is unavailable.
        live_names = {layer.get("name") for layer in layers if layer.get("name")}
        for stored_layer in existing_proj.get("layers", []):
            if not isinstance(stored_layer, dict):
                continue
            name = stored_layer.get("name")
            if not isinstance(name, str) or not name or name in live_names:
                continue
            preserved = dict(stored_layer)
            blob = preserved.get("blob")
            if blob:
                geojson = _blob_get(blob)
                if geojson is None:
                    raise ValueError("已有工程图层数据缺失，已跳过自动保存以避免数据丢失")
                preserved["geojson"] = geojson
            layers.append(preserved)
            live_names.add(name)
    existing_layers_by_name = {
        layer.get("name"): layer for layer in (existing_proj or {}).get("layers", []) if layer.get("name")
    }
    assignments_by_name = {}
    for assignment in layer_assignments or []:
        if not isinstance(assignment, dict):
            continue
        aliases = list(assignment.get("names", []))
        canonical = assignment.get("registry_name")
        if isinstance(canonical, str) and canonical and canonical not in aliases:
            aliases.append(canonical)
        for alias in aliases:
            if isinstance(alias, str) and alias:
                assignments_by_name[alias] = {
                    "groupId": assignment.get("groupId") or None,
                    "visible": assignment.get("visible") if isinstance(assignment.get("visible"), bool) else None,
                    "layer_id": assignment.get("layer_id") if isinstance(assignment.get("layer_id"), str) and assignment.get("layer_id").strip() else None,
                    "style": assignment.get("style") if isinstance(assignment.get("style"), dict) else None,
                    "opacity": assignment.get("opacity") if _valid_opacity(assignment.get("opacity")) else None,
                    "symbology": assignment.get("symbology") if isinstance(assignment.get("symbology"), dict) else None,
                    "has_symbology": "symbology" in assignment,
                    "labels": _sanitize_label_config(assignment.get("labels")) if isinstance(assignment.get("labels"), dict) else None,
                    "has_labels": "labels" in assignment,
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
            if assignment["has_labels"]:
                if assignment["labels"] is None:
                    layer.pop("labels", None)
                else:
                    layer["labels"] = assignment["labels"]
            elif previous and previous.get("labels"):
                layer["labels"] = previous["labels"]
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
                if previous.get("labels"):
                    layer["labels"] = previous["labels"]

    for assignment in layer_assignments or []:
        if not isinstance(assignment, dict) or not isinstance(assignment.get("raster"), dict):
            continue
        layer_name = assignment.get("name") or assignment.get("registry_name") or next(
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

    # Auto-save receives the user's current panel order with each assignment.
    # Preserve registry order for older callers that do not send a full order.
    assignment_order = {}
    for assignment in layer_assignments or []:
        if not isinstance(assignment, dict) or type(assignment.get("order")) is not int or assignment["order"] < 0:
            continue
        aliases = assignment.get("names", [])
        for alias in aliases if isinstance(aliases, list) else []:
            if isinstance(alias, str) and alias:
                assignment_order[alias] = assignment["order"]
        canonical = assignment.get("registry_name")
        if isinstance(canonical, str) and canonical:
            assignment_order[canonical] = assignment["order"]
        if isinstance(assignment.get("name"), str) and assignment["name"]:
            assignment_order[assignment["name"]] = assignment["order"]
    if layers and all(layer.get("name") in assignment_order for layer in layers):
        layers.sort(key=lambda layer: assignment_order[layer["name"]])

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
