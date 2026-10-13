"""密码哈希与 JWT。

选择直接使用 bcrypt 而非 passlib：passlib 1.7.4 与 bcrypt 4.x 存在版本探测告警/异常，
本项目体量小，直接用官方 bcrypt 库更稳（PRD 8. 安全）。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from .config import settings


def hash_password(plain: str) -> str:
    """生成 bcrypt 哈希（含盐）。轮数可通过 XUNJIA_BCRYPT_ROUNDS 调整以加速测试。"""
    rounds = max(4, min(16, settings.bcrypt_rounds))
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码；哈希格式异常时返回 False 而不是抛错。"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_fingerprint(password_hash: str) -> str:
    """密码指纹：取哈希的摘要，用于让"改密/重置密码"立即作废旧 token。

    不直接放哈希本身，避免 token 泄露时暴露可离线爆破的哈希。
    """
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_access_token(
    *,
    user_id: int,
    username: str,
    role: str,
    supplier_id: int | None,
    password_hash: str,
    expires_minutes: int | None = None,
) -> str:
    """签发 JWT。

    关键：
    - supplier_id 写进 token，供货商接口只信任 token 中的值，
      绝不接受前端传入的 supplier_id（PRD 7.3 安全要求）。
    - pwd 写进 token：管理员重置密码或用户改密后，旧 token 的指纹不再匹配，
      立即失效（补齐"重置密码使既有会话失效"的要求）。
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "supplier_id": supplier_id,
        "pwd": password_fingerprint(password_hash),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解析 JWT；过期或签名错误返回 None。"""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
