"""DEM tile 磁盘缓存。

布局：
    <cache_root>/<provider_id>/<z>/<x>/<y>.png

原子写入：先写 .tmp，再 os.replace 到目标路径；中途异常不影响旧文件。
损坏 / 大小异常的缓存文件视为无效，返回 None（让上层重新下载）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


# 单个 tile PNG 的大小上限：4 MB（正常 tile < 50 KB；4 MB 是非常宽松的安全边界）
_MAX_TILE_BYTES = 4 * 1024 * 1024
# 缓存目录名（DEM 缓存独立于 data/cache，便于单独清理）
_DEFAULT_CACHE_SUBDIR = "dem_tiles"


def default_cache_root() -> str:
    """默认缓存根目录（项目 cache/dem_tiles）。

    依赖 tools.init_temp_dir() 已在请求开始时初始化 _temp_output_dir；
    若尚未初始化则回退到 tempfile.gettempdir()/gis_worktable_cache/dem_tiles。
    """
    try:
        from backend.services import tools as _t
        base = _t._temp_output_dir
    except Exception:
        base = ""
    if not base:
        import tempfile
        base = os.path.join(tempfile.gettempdir(), "gis_worktable_output")
    root = os.path.join(base, _DEFAULT_CACHE_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


def tile_path(cache_root: str, provider_id: str, z: int, x: int, y: int) -> str:
    """tile 在缓存中的绝对路径。"""
    p = Path(cache_root) / provider_id / str(z) / str(x)
    p.mkdir(parents=True, exist_ok=True)
    return str(p / f"{y}.png")


def load_cached_tile(
    cache_root: str, provider_id: str, z: int, x: int, y: int,
) -> Optional[bytes]:
    """读缓存的 tile bytes；文件不存在 / 为空 / 损坏 / 超过大小上限 → 返回 None。"""
    path = tile_path(cache_root, provider_id, z, x, y)
    if not os.path.isfile(path):
        return None
    try:
        size = os.path.getsize(path)
        if size <= 0 or size > _MAX_TILE_BYTES:
            return None
        with open(path, "rb") as f:
            data = f.read()
        if not data:
            return None
        # PNG 魔数校验（前 8 字节）
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        return data
    except OSError:
        return None


def save_tile_atomic(
    cache_root: str, provider_id: str, z: int, x: int, y: int, png_bytes: bytes,
) -> Optional[str]:
    """原子写入 tile。

    步骤：先写 <path>.tmp.part → os.replace 到 <path>.tmp → os.replace 到 <path>。
    任一步失败：保留旧 <path>（如已存在），不影响已有缓存；返回 None。
    """
    if not png_bytes or len(png_bytes) > _MAX_TILE_BYTES:
        return None
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    final = tile_path(cache_root, provider_id, z, x, y)
    tmp = final + ".tmp"
    part = final + ".tmp.part"
    try:
        with open(part, "wb") as f:
            f.write(png_bytes)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                pass
        os.replace(part, tmp)
        os.replace(tmp, final)
        return final
    except OSError:
        # 清理半成品（不删 final，避免误删已有缓存）
        for p in (part, tmp):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        return None


def clear_provider_cache(cache_root: str, provider_id: str) -> int:
    """删除某 provider 的全部缓存 tile，返回删除文件数。"""
    base = Path(cache_root) / provider_id
    if not base.exists():
        return 0
    n = 0
    for p in base.rglob("*.png"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    # 清理空目录
    try:
        for d in sorted(base.glob("**/*"), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass
        base.rmdir()
    except OSError:
        pass
    return n