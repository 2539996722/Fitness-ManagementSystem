"""当前用户路由：/users/me。"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import hash_password, verify_password
from app.db.models import User
from app.db.session import get_session

router = APIRouter()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserMeOut(BaseModel):
    """当前用户信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None
    avatar_url: str | None
    gender: int
    age: int | None
    height_cm: float | None
    weight_kg: float | None
    role: str
    created_at: datetime
    last_login_at: datetime | None


class UserMeUpdate(BaseModel):
    """更新当前用户信息。"""

    nickname: str | None = Field(None, min_length=1, max_length=32)
    avatar_url: str | None = Field(None, max_length=255)
    gender: int | None = Field(None, ge=0, le=2)
    age: int | None = Field(None, ge=0, le=150)
    height_cm: float | None = Field(None, ge=0, le=300)
    weight_kg: float | None = Field(None, ge=0, le=500)


class ChangePasswordIn(BaseModel):
    """修改密码。"""

    old_password: str = Field(..., min_length=8, max_length=20)
    new_password: str = Field(..., min_length=8, max_length=20)


@router.get("/me", response_model=UserMeOut, summary="当前用户信息")
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserMeOut:
    """获取当前登录用户的完整信息。"""
    return UserMeOut.model_validate(current_user)


@router.patch("/me", response_model=UserMeOut, summary="更新个人信息")
async def update_me(
    body: UserMeUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserMeOut:
    """更新当前用户的个人信息（昵称、身高、体重等）。"""
    update_data = body.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(current_user, k, v)

    await session.commit()
    await session.refresh(current_user)
    return UserMeOut.model_validate(current_user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT, summary="修改密码")
async def change_password(
    body: ChangePasswordIn,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """修改当前用户密码（需要提供旧密码）。"""
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误",
        )

    current_user.password_hash = hash_password(body.new_password)
    current_user.failed_login_count = 0
    current_user.locked_until = None
    await session.commit()
    logger.info("用户 {} 修改密码", current_user.id)
    return None