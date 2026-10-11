"""当前用户路由：/users/me。

基础：
- GET    /users/me               当前用户信息
- PATCH  /users/me               更新个人信息
- POST   /users/me/password      修改密码
- DELETE /users/me               注销账号（软删自己）

扩展（M11 个人中心阶段二）：
- GET    /users/me/weight-logs          体重打卡历史
- POST   /users/me/weight-logs          记一条体重
- DELETE /users/me/weight-logs/{id}     删一条
- GET    /users/me/reviews              我发过的评论
- DELETE /users/me/reviews/{id}         删我自己的评论（软删）
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import hash_password, verify_password
from app.db.models import (
    Exercise,
    ExerciseReview,
    User,
    WeightLog,
)
from app.db.session import get_session
from app.schemas.profile_extra import (
    MyReviewOut,
    MyReviewsList,
    WeightLogIn,
    WeightLogList,
    WeightLogOut,
)

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


# ============ 体重打卡（M11 阶段二）============

@router.post(
    "/me/weight-logs",
    response_model=WeightLogOut,
    status_code=status.HTTP_201_CREATED,
    summary="记一条体重",
)
async def create_weight_log(
    body: WeightLogIn,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WeightLogOut:
    """记录当前用户的体重。recorded_at 默认 = 现在。"""
    log = WeightLog(
        user_id=current_user.id,
        weight_kg=body.weight_kg,
        recorded_at=body.recorded_at or _utcnow_naive(),
        note=body.note,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return WeightLogOut.model_validate(log)


@router.get(
    "/me/weight-logs",
    response_model=WeightLogList,
    summary="体重打卡历史（默认最近 90 天）",
)
async def list_weight_logs(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: int = Query(90, ge=1, le=730, description="最近 N 天"),
    limit: int = Query(200, ge=1, le=500),
) -> WeightLogList:
    """按 recorded_at 倒序返回。"""
    from datetime import timedelta

    since = _utcnow_naive() - timedelta(days=days)
    rows = (
        await session.execute(
            select(WeightLog)
            .where(WeightLog.user_id == current_user.id, WeightLog.recorded_at >= since)
            .order_by(WeightLog.recorded_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    total = (
        await session.execute(
            select(func.count(WeightLog.id))
            .where(WeightLog.user_id == current_user.id, WeightLog.recorded_at >= since)
        )
    ).scalar() or 0
    return WeightLogList(
        items=[WeightLogOut.model_validate(r) for r in rows],
        total=total,
    )


@router.delete(
    "/me/weight-logs/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除一条体重记录",
)
async def delete_weight_log(
    log_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    log = await session.get(WeightLog, log_id)
    if log is None or log.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="记录不存在")
    await session.delete(log)
    await session.commit()


# ============ 我的评论 ============

@router.get(
    "/me/reviews",
    response_model=MyReviewsList,
    summary="我发过的评论（含动作名）",
)
async def list_my_reviews(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    include_deleted: bool = Query(False, description="是否含已删评论"),
) -> MyReviewsList:
    base = select(ExerciseReview).where(ExerciseReview.user_id == current_user.id)
    if not include_deleted:
        base = base.where(ExerciseReview.status == 0)
    base = base.order_by(ExerciseReview.created_at.desc())
    count = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0
    rows = (
        await session.execute(base.offset((page - 1) * page_size).limit(page_size + 1))
    ).scalars().all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]

    # 批量加载 exercise，避免 N+1
    ex_ids = {r.exercise_id for r in rows}
    ex_map: dict[str, Exercise] = {}
    if ex_ids:
        ex_rows = (
            await session.execute(select(Exercise).where(Exercise.id.in_(ex_ids)))
        ).scalars().all()
        ex_map = {e.id: e for e in ex_rows}

    items = [
        MyReviewOut(
            id=r.id,
            exercise_id=r.exercise_id,
            exercise_name_zh=ex_map[r.exercise_id].name_zh if r.exercise_id in ex_map else None,
            rating=r.rating,
            content=r.content,
            status=r.status,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return MyReviewsList(
        items=items, total=count, page=page, page_size=page_size, has_more=has_more,
    )


@router.delete(
    "/me/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删我自己的评论（软删）",
)
async def delete_my_review(
    review_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    r = await session.get(ExerciseReview, review_id)
    if r is None or r.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="评论不存在")
    if r.status == 1:
        return  # 已删，幂等
    r.status = 1
    # 同步重算 exercise 的聚合（avg_rating / review_count）
    row = (
        await session.execute(
            select(func.avg(ExerciseReview.rating), func.count(ExerciseReview.id))
            .where(ExerciseReview.exercise_id == r.exercise_id, ExerciseReview.status == 0)
        )
    ).one()
    avg, cnt = row
    ex = await session.get(Exercise, r.exercise_id)
    if ex:
        ex.avg_rating = round(float(avg), 2) if avg is not None else None
        ex.review_count = int(cnt or 0)
    await session.commit()


# ============ 注销账号（软删自己）============

@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="注销当前账号（软删）",
)
async def delete_me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """用户主动注销：标记 is_deleted=1，清 password_hash，下次登录会被拦截。"""
    from app.core.security import hash_password
    import secrets

    current_user.is_deleted = True
    current_user.status = 1
    # 清密码 + 随机化（防止有人靠原密码再次登录）
    current_user.password_hash = hash_password(secrets.token_urlsafe(32))
    current_user.failed_login_count = 0
    current_user.locked_until = None
    await session.commit()
    logger.warning("用户 {} 主动注销账号", current_user.id)