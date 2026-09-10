"""鉴权路由：注册、登录、刷新。"""

import re

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Annotated
from fastapi import Depends

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.db.session import get_session
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, TokenOut
from app.schemas.user import UserOut
from sqlalchemy.ext.asyncio import AsyncSession


def _utcnow_naive() -> datetime:
    """Python 3.13 兼容：返回无时区的 UTC now（与 MySQL DATETIME 列匹配）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

router = APIRouter()

# 用户名规则：中英文/数字/下划线，3-32 字符
USERNAME_PATTERN = re.compile(r"^[\w一-龥]{3,32}$", re.UNICODE)
# 密码规则：8-20 字符，含字母+数字
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,20}$")

LOCK_AFTER_FAILS = 5
LOCK_MINUTES = 10


def _make_token_pair(user: User) -> tuple[str, str, int]:
    """生成 Access + Refresh Token 对。"""
    extra = {"role": user.role}
    access = create_access_token(user.id, extra)
    refresh = create_refresh_token(user.id, extra)
    return access, refresh, settings.access_token_expire_minutes * 60


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED, summary="注册新用户（C 端）")
async def register(
    body: RegisterIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    """注册新用户。成功后自动登录。"""
    # 校验用户名
    if not USERNAME_PATTERN.match(body.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名格式错误（仅允许中英文/数字/下划线，3-32 字符）",
        )

    # 校验密码
    if not PASSWORD_PATTERN.match(body.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码格式错误（8-20 字符，必须含字母和数字）",
        )

    # 查重
    existing = await session.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被注册",
        )

    # 创建用户
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.username,
        role="user",
        status=0,
    )
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        logger.warning("注册冲突: {}", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被注册",
        )

    await session.refresh(user)

    access, refresh, expires_in = _make_token_pair(user)
    logger.info("新用户注册: id={} username={}", user.id, user.username)

    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenOut, summary="登录")
async def login(
    body: LoginIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    """账号密码登录。"""
    result = await session.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user:
        # 不暴露用户是否存在
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if user.is_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="账号已被锁定，请稍后再试",
        )

    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被封禁",
        )

    if user.is_deleted:
        # ponytail: 软删除的用户彻底失效（密码已置空，正常也登不上；这里加一道显式拦截）
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号不存在或已注销",
        )

    if not verify_password(body.password, user.password_hash):
        # 增加失败计数
        user.failed_login_count += 1
        if user.failed_login_count >= LOCK_AFTER_FAILS:
            from datetime import datetime, timedelta

            user.locked_until = _utcnow_naive() + timedelta(minutes=LOCK_MINUTES)
            user.failed_login_count = 0
            logger.warning("账号锁定: username={}", user.username)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    # 登录成功，重置失败计数
    from datetime import datetime

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _utcnow_naive()
    await session.commit()
    await session.refresh(user)

    access, refresh, expires_in = _make_token_pair(user)
    logger.info("用户登录: id={} username={}", user.id, user.username)

    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenOut, summary="刷新 Access Token")
async def refresh(
    body: RefreshIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    """用 Refresh Token 换取新的 Access Token。"""
    from app.core.security import decode_token

    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token 无效",
        )

    user_id = payload.get("sub")
    result = await session.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user or user.is_banned or user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被封禁",
        )

    access, refresh_token, expires_in = _make_token_pair(user)

    return TokenOut(
        access_token=access,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )