"""安全模块：JWT 签发/校验、密码哈希。

密码哈希改用 bcrypt 包直接调用，避开 passlib 1.7.4 在 bcrypt 4.x 上的
"detect_wrap_bug" 探测问题（探测密码 > 72 字节触发 ValueError，
即便业务侧已截断也救不了 passlib 自身的探测）。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt
from loguru import logger

from app.core.config import settings


def _truncate(plain: str) -> bytes:
    """bcrypt 仅接受 ≤72 字节；超长密码在 UTF-8 边界截断。"""
    b = plain.encode("utf-8")
    if len(b) <= 72:
        return b
    return b[:72].decode("utf-8", errors="ignore").encode("utf-8")


def hash_password(plain: str) -> str:
    """对明文密码哈希。"""
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(_truncate(plain), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))
    except Exception as e:
        logger.warning("密码校验异常: {}", e)
        return False


def create_access_token(subject: str | int, extra_claims: dict[str, Any] | None = None) -> str:
    """生成 Access Token（默认 2 小时）。"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
        **(extra_claims or {}),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str | int, extra_claims: dict[str, Any] | None = None) -> str:
    """生成 Refresh Token（默认 7 天）。"""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
        **(extra_claims or {}),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """解码 JWT。失败返回 None。"""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        logger.debug("JWT 解码失败: {}", e)
        return None
    except Exception as e:
        logger.warning("JWT 解码异常: {}", e)
        return None