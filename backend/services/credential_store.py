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
from cryptography.fernet import Fernet

_CRED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "cache", "credentials")
_KEY_FILE = os.path.join(_CRED_DIR, ".key")
_CRED_FILE = os.path.join(_CRED_DIR, "credentials.enc")


def _ensure_dir():
    os.makedirs(_CRED_DIR, exist_ok=True)


def _get_or_create_key() -> bytes:
    """获取或生成加密密钥（存在本地，仅本机可用）"""
    _ensure_dir()
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(_KEY_FILE, "wb") as f:
        f.write(key)
    try:
        os.chmod(_KEY_FILE, 0o600)
    except Exception:
        pass
    return key


def _get_fernet() -> Fernet:
    return Fernet(_get_or_create_key())


def save_credential(service: str, username: str, password: str, extra: dict = None) -> bool:
    """保存凭据（加密存储）。供后端 API 调用，Agent 不可调用。"""
    if not service or not username:
        return False
    _ensure_dir()
    try:
        creds = _load_all()
        entry = {"username": username, "password": password}
        if extra:
            entry.update(extra)
        creds[service] = entry
        fernet = _get_fernet()
        encrypted = fernet.encrypt(json.dumps(creds, ensure_ascii=False).encode("utf-8"))
        with open(_CRED_FILE, "wb") as f:
            f.write(encrypted)
        return True
    except Exception:
        return False


def _load_all() -> dict:
    """加载所有凭据（内部函数，不暴露给 Agent）"""
    if not os.path.exists(_CRED_FILE):
        return {}
    try:
        with open(_CRED_FILE, "rb") as f:
            encrypted = f.read()
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted)
        return json.loads(decrypted.decode("utf-8"))
    except Exception:
        return {}


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
    creds = _load_all()
    if service in creds:
        del creds[service]
        try:
            fernet = _get_fernet()
            encrypted = fernet.encrypt(json.dumps(creds, ensure_ascii=False).encode("utf-8"))
            with open(_CRED_FILE, "wb") as f:
                f.write(encrypted)
            return True
        except Exception:
            return False
    return False
