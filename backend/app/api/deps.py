"""共享 FastAPI 依赖：鉴权、当前用户、角色校验。"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_session

# Bearer Token 解析（auto_error=False 让 401 错误由我们自己抛出）
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """从 Authorization Header 解析 Token，返回当前用户。

    失败抛出 401。
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="凭证无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 仅接受 access token
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="凭证类型错误",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="凭证无效",
        )

    # 查询用户
    from sqlalchemy import select

    result = await session.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被封禁",
        )

    if user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号不存在或已注销",
        )

    return user


def require_role(*allowed_roles: str):
    """依赖工厂：要求当前用户具备指定角色之一。

    使用示例：
        @router.post("/admin/users/{id}/ban",
                     dependencies=[Depends(require_role("admin"))])
    """

    async def role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_roles:
            logger.warning(
                "权限不足：用户 {} (角色={}) 尝试访问需要 {} 的接口",
                current_user.id,
                current_user.role,
                allowed_roles,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要角色：{', '.join(allowed_roles)}",
            )
        return current_user

    return role_checker


# 便捷依赖
require_admin = require_role("admin")
require_trainer = require_role("trainer", "admin")


# ============ slowapi 限流 key 函数 ============

def user_id_key_func(request: Request) -> str:
    """按 user_id 限流的 key 函数。

    ponytail: 优先用 JWT 里的 user_id，未登录或解析失败回退到 IP；
    同一 IP 多个用户会共享 IP 额度——MVP 阶段可接受。
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = decode_token(auth[7:])
            uid = payload.get("sub") if payload else None
            if uid:
                return f"user:{uid}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"