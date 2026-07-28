"""
对称加密层：所有需要落库的敏感字段（百度 access_token / refresh_token / session_secret 等）
都走这里的 encrypt / decrypt。

起步阶段主密钥从 env 读，上线前切阿里云 KMS——只改本文件 _load_master_key 实现，
对外接口不变。
"""
import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_NONCE_LEN = 12
_KEY_LEN = 32


def _load_master_key() -> bytes:
    settings = get_settings()
    raw = base64.b64decode(settings.crypto_master_key_b64)
    if len(raw) != _KEY_LEN:
        raise RuntimeError(
            f"CRYPTO_MASTER_KEY_B64 解码后必须是 {_KEY_LEN} 字节，当前是 {len(raw)} 字节"
        )
    return raw


def _aead() -> AESGCM:
    return AESGCM(_load_master_key())


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        raise ValueError("encrypt 不接受 None")
    nonce = os.urandom(_NONCE_LEN)
    ct = _aead().encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(ciphertext_b64: str) -> str:
    raw = base64.b64decode(ciphertext_b64)
    nonce, ct = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    return _aead().decrypt(nonce, ct, associated_data=None).decode("utf-8")


def generate_master_key_b64() -> str:
    """开发期一次性用：python -c 'from app.security.crypto import generate_master_key_b64 as g; print(g())'"""
    return base64.b64encode(secrets.token_bytes(_KEY_LEN)).decode("ascii")
