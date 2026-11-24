"""本文件提供 API Key 对称加密封装，基于 Fernet，用于 BYOK 场景下用户密钥的安全存储。"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from backend.config import settings


def _derive_key() -> bytes:
    """从配置密钥派生 Fernet 所需的 32 字节 base64 密钥。"""
    secret = settings.llm_config_secret or settings.jwt_secret
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_key())


def encrypt(plaintext: str) -> str:
    """加密明文，返回可安全入库的密文字符串。"""
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """解密密文，返回原始明文。"""
    return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def mask(api_key: str) -> str:
    """对 API Key 脱敏，只保留首尾若干字符，用于接口返回和日志。"""
    if len(api_key) <= 12:
        return "***"
    return f"{api_key[:8]}...{api_key[-4:]}"
