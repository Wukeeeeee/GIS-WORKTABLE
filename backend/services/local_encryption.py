"""Authenticated, chunked encryption for sensitive files stored on this device.

The data key is held in the operating-system keyring. File names and declared
metadata remain visible; this protects file contents at rest, not a running
process, a compromised account, or data deliberately sent to a remote service.
"""
from __future__ import annotations

from contextlib import contextmanager
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
import hashlib
import hmac
import io
import os
import struct
import tempfile
import threading
import uuid


_MAGIC = b"GISWENC1"
_MAGIC_PREFIX = b"GISWENC"
_CHUNK_SIZE = 1024 * 1024
_HEADER_SIZE = len(_MAGIC) + 4 + 16
_KEYRING_SERVICE = "GIS WorkTable local data encryption"
_KEYRING_USER = "master-key-v1"
_KEY_LOCK = threading.RLock()


class LocalEncryptionUnavailable(ValueError):
    pass


def secure_keyring():
    try:
        import keyring
        backend = keyring.get_keyring()
        backend_module = type(backend).__module__.casefold()
        if (getattr(backend, "priority", 0) <= 0
                or any(part in backend_module for part in ("keyrings.alt", ".fail", ".null", "plaintext"))):
            raise LocalEncryptionUnavailable("没有可用的系统安全密钥库")
        return keyring
    except LocalEncryptionUnavailable:
        raise
    except Exception as exc:
        raise LocalEncryptionUnavailable("无法访问系统安全密钥库") from exc


def _master_key() -> bytes:
    """Get or create the AES key in a platform keyring; never write it beside data."""
    with _KEY_LOCK:
        try:
            keyring = secure_keyring()
            stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            if stored:
                key = base64.urlsafe_b64decode(stored.encode("ascii"))
                if len(key) != 32:
                    raise LocalEncryptionUnavailable("系统密钥库中的本地数据密钥无效")
                return key
            key = AESGCM.generate_key(bit_length=256)
            encoded = base64.urlsafe_b64encode(key).decode("ascii")
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, encoded)
            verify = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            if verify != encoded:
                raise LocalEncryptionUnavailable("无法确认本地数据密钥已安全保存")
            return key
        except LocalEncryptionUnavailable:
            raise
        except Exception as exc:
            raise LocalEncryptionUnavailable("无法访问系统安全密钥库，已停止读取或保存加密数据") from exc


def is_encrypted_bytes(data: bytes) -> bool:
    return isinstance(data, bytes) and data.startswith(_MAGIC)


def is_encrypted_file(path: str) -> bool:
    try:
        with open(path, "rb") as source:
            prefix = source.read(len(_MAGIC))
            if prefix.startswith(_MAGIC_PREFIX) and prefix != _MAGIC:
                raise ValueError("本地加密文件头损坏")
            return prefix == _MAGIC
    except OSError:
        return False


def _file_key(master_key: bytes, salt: bytes, context: str) -> bytes:
    return hmac.new(master_key, b"GIS WorkTable file key\0" + salt + context.encode("utf-8"),
                    hashlib.sha256).digest()


def _nonce(counter: int) -> bytes:
    return counter.to_bytes(12, "big")


def _aad(context: str, counter: int, size: int) -> bytes:
    return context.encode("utf-8") + b"\0chunk\0" + struct.pack(">II", counter, size)


class _EncryptedStreamWriter:
    def __init__(self, target, context):
        salt = os.urandom(16)
        self.target = target
        self.context = context
        self.aes = AESGCM(_file_key(_master_key(), salt, context))
        self.target.write(_MAGIC + struct.pack(">I", _CHUNK_SIZE) + salt)
        self.buffer = bytearray()
        self.counter = 0
        self.total = 0
        self.finished = False

    def write(self, data):
        if self.finished:
            raise ValueError("加密写入流已关闭")
        view = memoryview(data)
        self.buffer.extend(view)
        while len(self.buffer) >= _CHUNK_SIZE:
            self._write_chunk(_CHUNK_SIZE)
        return len(view)

    def _write_chunk(self, size):
        chunk = bytes(self.buffer[:size])
        del self.buffer[:size]
        self.target.write(struct.pack(">I", size))
        self.target.write(self.aes.encrypt(_nonce(self.counter), chunk,
                                           _aad(self.context, self.counter, size)))
        self.counter += 1
        self.total += size

    def flush(self):
        self.target.flush()

    def finish(self):
        if self.finished:
            return
        if self.buffer:
            self._write_chunk(len(self.buffer))
        self.target.write(struct.pack(">I", 0))
        final_aad = self.context.encode("utf-8") + b"\0final\0" + struct.pack(">QQ", self.counter, self.total)
        self.target.write(self.aes.encrypt(_nonce(self.counter), b"", final_aad))
        self.target.flush()
        self.finished = True


@contextmanager
def encrypted_writer(target, context: str):
    """Stream data directly to authenticated ciphertext without a plaintext staging file."""
    writer = _EncryptedStreamWriter(target, context)
    try:
        yield writer
        writer.finish()
    except Exception:
        raise


def encrypt_stream(source, target, context: str) -> None:
    salt = os.urandom(16)
    aes = AESGCM(_file_key(_master_key(), salt, context))
    target.write(_MAGIC + struct.pack(">I", _CHUNK_SIZE) + salt)
    counter = 0
    total = 0
    while True:
        chunk = source.read(_CHUNK_SIZE)
        if not chunk:
            break
        if counter >= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("加密文件超过分块数量上限")
        target.write(struct.pack(">I", len(chunk)))
        target.write(aes.encrypt(_nonce(counter), chunk,
                                 _aad(context, counter, len(chunk))))
        counter += 1
        total += len(chunk)
    target.write(struct.pack(">I", 0))
    final_aad = context.encode("utf-8") + b"\0final\0" + struct.pack(">QQ", counter, total)
    target.write(aes.encrypt(_nonce(counter), b"", final_aad))


def decrypt_stream(source, target, context: str) -> None:
    header = source.read(_HEADER_SIZE)
    if len(header) != _HEADER_SIZE or not header.startswith(_MAGIC):
        raise ValueError("本地加密文件格式无效")
    chunk_size = struct.unpack(">I", header[len(_MAGIC):len(_MAGIC) + 4])[0]
    if chunk_size != _CHUNK_SIZE:
        raise ValueError("本地加密文件分块格式不受支持")
    salt = header[-16:]
    aes = AESGCM(_file_key(_master_key(), salt, context))
    counter = 0
    total = 0
    while True:
        size_raw = source.read(4)
        if len(size_raw) != 4:
            raise ValueError("本地加密文件不完整")
        size = struct.unpack(">I", size_raw)[0]
        if size == 0:
            break
        if size > _CHUNK_SIZE or counter >= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("本地加密文件分块无效")
        encrypted = source.read(size + 16)
        if len(encrypted) != size + 16:
            raise ValueError("本地加密文件不完整")
        clear = aes.decrypt(_nonce(counter), encrypted,
                            _aad(context, counter, size))
        target.write(clear)
        counter += 1
        total += size
    final_tag = source.read(16)
    if len(final_tag) != 16:
        raise ValueError("本地加密文件缺少完整性标记")
    final_aad = context.encode("utf-8") + b"\0final\0" + struct.pack(">QQ", counter, total)
    aes.decrypt(_nonce(counter), final_tag, final_aad)
    if source.read(1):
        raise ValueError("本地加密文件包含未识别的尾随数据")


def encrypt_file(source_path: str, target_path: str, context: str) -> None:
    with open(source_path, "rb") as source, open(target_path, "wb") as target:
        encrypt_stream(source, target, context)
        target.flush()
        os.fsync(target.fileno())


def decrypt_file(source_path: str, target_path: str, context: str) -> None:
    with open(source_path, "rb") as source, open(target_path, "wb") as target:
        decrypt_stream(source, target, context)
        target.flush()
        os.fsync(target.fileno())


def encrypt_bytes(data: bytes, context: str) -> bytes:
    source, target = io.BytesIO(data), io.BytesIO()
    encrypt_stream(source, target, context)
    return target.getvalue()


def read_bytes(path: str, context: str, *, migrate_legacy=True) -> bytes:
    with open(path, "rb") as source:
        prefix = source.read(len(_MAGIC))
        source.seek(0)
        if prefix.startswith(_MAGIC_PREFIX) and prefix != _MAGIC:
            raise ValueError("本地加密文件头损坏")
        if prefix == _MAGIC:
            target = io.BytesIO()
            decrypt_stream(source, target, context)
            return target.getvalue()
        clear = source.read()
    if migrate_legacy:
        write_bytes_atomic(path, clear, context)
    return clear


def write_bytes_atomic(path: str, data: bytes, context: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp_path = os.path.join(directory, ".secure-" + uuid.uuid4().hex + ".tmp")
    try:
        with open(temp_path, "wb") as target:
            encrypt_stream(io.BytesIO(data), target, context)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass


@contextmanager
def decrypted_file(path: str, context: str, *, migrate_legacy=True):
    """Yield a temporary plaintext path and remove it after use; migrate old files."""
    directory = tempfile.gettempdir()
    clear_fd, clear_path = tempfile.mkstemp(prefix="gisw-clear-", dir=directory)
    os.close(clear_fd)
    encrypted_path = None
    try:
        if is_encrypted_file(path):
            decrypt_file(path, clear_path, context)
        else:
            with open(path, "rb") as source, open(clear_path, "wb") as target:
                while True:
                    chunk = source.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    target.write(chunk)
            if migrate_legacy:
                encrypted_path = path + ".secure-" + uuid.uuid4().hex + ".tmp"
                encrypt_file(path, encrypted_path, context)
                os.replace(encrypted_path, path)
                encrypted_path = None
        yield clear_path
    finally:
        for target in (clear_path, encrypted_path):
            if target:
                try:
                    os.remove(target)
                except FileNotFoundError:
                    pass
