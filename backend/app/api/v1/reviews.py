"""动作评论路由（M7, PRD §9.6）。

C 端：
- GET    /api/v1/exercises/{id}/reviews         公开评论列表（分页）
- POST   /api/v1/exercises/{id}/reviews         当前用户对该动作写评论（UPSERT）
- DELETE /api/v1/exercises/{id}/reviews/{rid}   当前用户删自己的评论（软删）

B 端：
- DELETE /api/v1/admin/reviews/{id}             管理员强制删除任意评论
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.core.security import decode_token
from app.db.models import Exercise, ExerciseReview, User
from app.db.session import get_session
from app.schemas.review import (
    ReviewAuthor,
    ReviewCreate,
    ReviewListResponse,
    ReviewOut,
)
from app.services.operation_log import record as log_operation

router = APIRouter()


# ============ 工具 ============

async def _optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User | None:
    """可选当前用户：没有 token 时返回 None，不抛 401。"""
    if not credentials or not credentials.credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    result = await session.execute(select(User).where(User.id == int(user_id)))
    return result.scalar_one_or_none()


# ============ 工具 ============

async def _recalc_exercise_stats(session: AsyncSession, exercise_id: str) -> None:
    """重算 exercises.avg_rating / review_count，只统计 status=0 的评论。"""
    row = (
        await session.execute(
            select(func.avg(ExerciseReview.rating), func.count(ExerciseReview.id))
            .where(ExerciseReview.exercise_id == exercise_id)
            .where(ExerciseReview.status == 0)
        )
    ).one()
    avg, count = row
    exercise = await session.get(Exercise, exercise_id)
    if exercise is None:
        return
    exercise.avg_rating = Decimal(str(round(float(avg), 2))) if avg is not None else None
    exercise.review_count = int(count or 0)


def _to_out(review: ExerciseReview, current_user_id: int | None) -> ReviewOut:
    return ReviewOut(
        id=review.id,
        exercise_id=review.exercise_id,
        rating=review.rating,
        content=review.content,
        created_at=review.created_at,
        updated_at=review.updated_at,
        is_mine=current_user_id is not None and review.user_id == current_user_id,
        author=ReviewAuthor.model_validate(review.user) if review.user else None,
    )


# ============ C 端：列表 / 写 / 删自己 ============

@router.get(
    "/exercises/{exercise_id}/reviews",
    response_model=ReviewListResponse,
    summary="动作的评论列表",
)
async def list_reviews(
    exercise_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User | None, Depends(_optional_user)] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> ReviewListResponse:
    # 确认动作存在
    if await session.get(Exercise, exercise_id) is None:
        raise HTTPException(status_code=404, detail=f"动作 {exercise_id} 不存在")

    base = (
        select(ExerciseReview)
        .where(ExerciseReview.exercise_id == exercise_id)
        .where(ExerciseReview.status == 0)
    )
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    rows = (
        await session.execute(
            base.order_by(ExerciseReview.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size + 1)
        )
    ).scalars().all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]

    # 加载作者信息（一次 N+1 避免，简单的做法是再发一次 join 查询）
    if rows:
        from app.db.models import User as UserModel

        user_ids = {r.user_id for r in rows}
        users = (
            await session.execute(select(UserModel).where(UserModel.id.in_(user_ids)))
        ).scalars().all()
        user_map = {u.id: u for u in users}
        for r in rows:
            r.user = user_map.get(r.user_id)

    uid = current_user.id if current_user else None
    return ReviewListResponse(
        items=[_to_out(r, uid) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.post(
    "/exercises/{exercise_id}/reviews",
    response_model=ReviewOut,
    summary="写评论（UPSERT）",
)
async def upsert_review(
    exercise_id: str,
    body: ReviewCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReviewOut:
    if await session.get(Exercise, exercise_id) is None:
        raise HTTPException(status_code=404, detail=f"动作 {exercise_id} 不存在")

    existing = (
        await session.execute(
            select(ExerciseReview)
            .where(ExerciseReview.exercise_id == exercise_id)
            .where(ExerciseReview.user_id == current_user.id)
        )
    ).scalar_one_or_none()

    if existing is None:
        review = ExerciseReview(
            user_id=current_user.id,
            exercise_id=exercise_id,
            rating=body.rating,
            content=body.content,
            status=0,
        )
        session.add(review)
        await session.flush()  # 立刻落库，让后面的 AVG() 看到
    else:
        existing.rating = body.rating
        existing.content = body.content
        # 之前如果软删了，复活
        existing.status = 0
        review = existing
        await session.flush()

    await _recalc_exercise_stats(session, exercise_id)
    await session.commit()
    await session.refresh(review)
    review.user = current_user

    logger.info(
        "评论 {}：用户 {} 动作 {} rating={}",
        "新增" if existing is None else "更新",
        current_user.id, exercise_id, body.rating,
    )
    return _to_out(review, current_user.id)


@router.delete(
    "/exercises/{exercise_id}/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删自己的评论",
)
async def delete_own_review(
    exercise_id: str,
    review_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    review = await session.get(ExerciseReview, review_id)
    if review is None or review.exercise_id != exercise_id:
        raise HTTPException(status_code=404, detail="评论不存在")
    if review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能删除自己的评论")

    review.status = 1  # 软删
    await session.flush()  # 让 AVG() 看到 status=1
    await _recalc_exercise_stats(session, exercise_id)
    await session.commit()
    logger.info("用户 {} 软删评论 {}", current_user.id, review_id)


# ============ B 端：管理员强删 / 列出 ============

@router.get(
    "/admin/reviews",
    summary="列出全部评论（admin 用）",
)
async def list_all_reviews(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    exercise_id: str | None = Query(None, description="按动作 ID 筛"),
    user_id: int | None = Query(None),
    keyword: str | None = Query(None, description="按评论内容模糊匹配"),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """admin 视角的全部评论列表，支持筛选 + 分页。"""
    stmt = select(ExerciseReview).order_by(ExerciseReview.created_at.desc())
    if not include_deleted:
        stmt = stmt.where(ExerciseReview.status == 0)
    if exercise_id:
        stmt = stmt.where(ExerciseReview.exercise_id == exercise_id)
    if user_id:
        stmt = stmt.where(ExerciseReview.user_id == user_id)
    if keyword:
        stmt = stmt.where(ExerciseReview.content.ilike(f"%{keyword}%"))

    # ponytail: total 用独立 count 查询；items 用 limit/offset
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0
    rows = (
        await session.execute(stmt.limit(limit).offset(offset))
    ).scalars().all()

    # 批量加载 user + exercise，避免 N+1
    user_ids = {r.user_id for r in rows}
    exercise_ids = {r.exercise_id for r in rows}
    users = (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all() if user_ids else []
    exercises = (await session.execute(select(Exercise).where(Exercise.id.in_(exercise_ids)))).scalars().all() if exercise_ids else []
    u_map = {u.id: u for u in users}
    e_map = {e.id: e for e in exercises}

    out = []
    for r in rows:
        u = u_map.get(r.user_id)
        e = e_map.get(r.exercise_id)
        out.append({
            "id": r.id,
            "user_id": r.user_id,
            "username": u.username if u else "未知",
            "nickname": u.nickname if u else None,
            "exercise_id": r.exercise_id,
            "exercise_name": e.name_zh if e else None,
            "rating": r.rating,
            "content": r.content,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"items": out, "total": total, "limit": limit, "offset": offset}


@router.delete(
    "/admin/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="管理员强制删除评论",
)
async def admin_delete_review(
    review_id: int,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    review = await session.get(ExerciseReview, review_id)
    if review is None or review.status == 1:
        raise HTTPException(status_code=404, detail="评论不存在")

    exercise_id = review.exercise_id
    review.status = 1
    await session.flush()
    await _recalc_exercise_stats(session, exercise_id)
    await session.commit()
    logger.warning("管理员强删评论 {}", review_id)
    await log_operation(
        session=session,
        operator=admin,
        action="admin_delete_review",
        target_type="review",
        target_id=review_id,
        summary=f"强删评论 {review_id}（动作 {exercise_id}）",
        details={"exercise_id": exercise_id, "review_user_id": review.user_id, "rating": review.rating},
    )
