# -*- coding: utf-8 -*-
"""
安全凭据存储模块（Credential Store）

设计原则：
- 凭据加密存储到本地文件，不明文保存
- 只提供 get_credential(service) 接口，供工具内部调用
- 不提供 get_password / read_password 等可被 Agent 调用的接口
- Agent 只能调用 login_xxx() 工具，收到 {success: true/false}，看不到密码
"""
import os
import json
import tempfile
import threading
from cryptography.fernet import Fernet

_CRED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "credentials")
_KEY_FILE = os.path.join(_CRED_DIR, ".key")
_CRED_FILE = os.path.join(_CRED_DIR, "credentials.enc")
_CRED_LOCK = threading.RLock()


def _ensure_dir():
    os.makedirs(_CRED_DIR, exist_ok=True)


def _get_or_create_key() -> bytes:
    """获取或生成加密密钥；新密钥放系统密钥库，迁移后删除旧明文密钥文件。"""
    with _CRED_LOCK:
        _ensure_dir()
        from backend.services.local_encryption import secure_keyring, LocalEncryptionUnavailable
        try:
            keyring = secure_keyring()
            service, username = "GIS WorkTable credential encryption", "fernet-key-v1"
            stored = keyring.get_password(service, username)
            if stored:
                key = stored.encode("ascii")
                Fernet(key)
                if os.path.exists(_KEY_FILE):
                    with open(_KEY_FILE, "rb") as f:
                        legacy_key = f.read()
                    if legacy_key == key:
                        os.remove(_KEY_FILE)
                return key
            if os.path.exists(_KEY_FILE):
                with open(_KEY_FILE, "rb") as f:
                    key = f.read()
                Fernet(key)
            else:
                key = Fernet.generate_key()
            encoded = key.decode("ascii")
            keyring.set_password(service, username, encoded)
            if keyring.get_password(service, username) != encoded:
                raise LocalEncryptionUnavailable("无法确认凭据密钥已安全保存")
            if os.path.exists(_KEY_FILE):
                os.remove(_KEY_FILE)
        except LocalEncryptionUnavailable:
            raise
        except Exception as exc:
            raise LocalEncryptionUnavailable("系统密钥库不可用，无法读取或保存凭据") from exc
        return key


def _get_fernet() -> Fernet:
    return Fernet(_get_or_create_key())


def save_credential(service: str, username: str, password: str, extra: dict = None) -> bool:
    """保存凭据（加密存储）。供后端 API 调用，Agent 不可调用。"""
    if not service or not username:
        return False
    with _CRED_LOCK:
        _ensure_dir()
        try:
            creds = _load_all(strict=True)
            entry = dict(extra or {})
            # Explicit arguments are authoritative and cannot be overwritten by extras.
            entry.update({"username": username, "password": password})
            creds[service] = entry
            fernet = _get_fernet()
            encrypted = fernet.encrypt(json.dumps(creds, ensure_ascii=False).encode("utf-8"))
            _write_atomic(_CRED_FILE, encrypted)
            return True
        except Exception:
            return False


def _load_all(strict: bool = False) -> dict:
    """加载所有凭据（内部函数，不暴露给 Agent）"""
    with _CRED_LOCK:
        if not os.path.exists(_CRED_FILE):
            return {}
        try:
            with open(_CRED_FILE, "rb") as f:
                encrypted = f.read()
            fernet = _get_fernet()
            decrypted = fernet.decrypt(encrypted)
            data = json.loads(decrypted.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("凭据文件内容不是对象")
            return data
        except Exception:
            if strict:
                raise
            return {}


def _write_atomic(path: str, content: bytes) -> None:
    """在凭据目录内写临时文件并替换，避免并发/中断留下半份密文或密钥。"""
    fd, tmp_path = tempfile.mkstemp(prefix=".credential_", dir=_CRED_DIR)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass


def get_credential(service: str) -> dict | None:
    """
    获取指定服务的凭据（内部函数，仅供工具调用）。
    
    重要：此函数不应被 Agent 直接调用，只在 login_xxx() 工具内部使用。
    返回 {username, password}，工具用完即弃，不返回给 Agent。
    """
    creds = _load_all()
    return creds.get(service)


def has_credential(service: str) -> bool:
    """检查是否已配置凭据（只返回布尔，不返回内容）。可被 Agent 调用。"""
    return service in _load_all()


def get_configured_services() -> list:
    """获取已配置的服务列表（只返回服务名，不返回凭据）。可被 Agent 调用。"""
    return list(_load_all().keys())


def delete_credential(service: str) -> bool:
    """删除指定服务的凭据。供后端 API 调用，Agent 不可调用。"""
    with _CRED_LOCK:
        try:
            creds = _load_all(strict=True)
            if service not in creds:
                return False
            del creds[service]
            fernet = _get_fernet()
            encrypted = fernet.encrypt(json.dumps(creds, ensure_ascii=False).encode("utf-8"))
            _write_atomic(_CRED_FILE, encrypted)
            return True
        except Exception:
            return False
