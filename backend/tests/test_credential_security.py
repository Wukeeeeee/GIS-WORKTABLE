# -*- coding: utf-8 -*-
"""安全凭据管理测试：验证密码不进入 LLM context"""
import os
import sys
import json
import pytest
from cryptography.fernet import Fernet

from backend.services import credential_store

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(autouse=True)
def isolate_credential_store(tmp_path, monkeypatch):
    """Never let credential tests read or mutate a developer's local store/keyring."""
    monkeypatch.setattr(credential_store, "_CRED_DIR", str(tmp_path / "credentials"))
    monkeypatch.setattr(credential_store, "_KEY_FILE", str(tmp_path / "credentials" / ".key"))
    monkeypatch.setattr(credential_store, "_CRED_FILE", str(tmp_path / "credentials" / "credentials.enc"))
    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(credential_store, "_get_fernet", lambda: fernet)


class TestCredentialSecurity:
    """测试凭据存储安全性"""

    def test_save_and_get_credential(self):
        """测试保存和读取凭据"""
        from backend.services.credential_store import save_credential, get_credential, delete_credential
        # 用测试凭据
        save_credential("test_service", "testuser", "testpass123")
        cred = get_credential("test_service")
        assert cred is not None
        assert cred["username"] == "testuser"
        assert cred["password"] == "testpass123"
        # 清理
        delete_credential("test_service")

    def test_has_credential_only_returns_bool(self):
        """测试 has_credential 只返回布尔，不返回内容"""
        from backend.services.credential_store import save_credential, has_credential, delete_credential
        save_credential("test_service2", "user", "pass")
        result = has_credential("test_service2")
        assert isinstance(result, bool)
        assert result is True
        # 未配置的返回 False
        assert has_credential("nonexistent") is False
        delete_credential("test_service2")




class TestLoginToolSecurity:
    """测试登录工具不返回密码"""

    def test_login_gscloud_no_credential(self):
        """当前未实现自动登录，应明确返回不支持，不返回密码"""
        from backend.services.tools import login_gscloud
        result = json.loads(login_gscloud.invoke({}))
        assert result["success"] is False
        assert "不支持自动登录" in result["reason"]
        # 确保返回值里没有 password 字段
        assert "password" not in result

    def test_login_gscloud_does_not_claim_success_or_return_credentials(self):
        """不论设置中是否有账号密码，都不能伪报登录成功或回传凭据"""
        from backend.services.credential_store import save_credential, delete_credential
        from backend.services.tools import login_gscloud
        # 配置测试凭据
        save_credential("gscloud", "testuser", "testpassword456")
        result = json.loads(login_gscloud.invoke({}))
        assert result["success"] is False
        assert "不支持自动登录" in result["reason"]
        # 返回值不应该包含密码
        result_str = json.dumps(result)
        assert "testpassword456" not in result_str
        assert "password" not in result
        assert "username" not in result
        # 清理
        delete_credential("gscloud")

