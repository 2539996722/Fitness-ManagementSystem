"""安全模块：JWT 签发/校验、密码哈希。"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from loguru import logger
from passlib.context import CryptContext

from app.core.config import settings

# 密码哈希上下文（bcrypt，cost=12）
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.bcrypt_rounds,
)


def hash_password(plain: str) -> str:
    """对明文密码哈希。"""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return pwd_context.verify(plain, hashed)
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