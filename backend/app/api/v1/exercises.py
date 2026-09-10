"""动作路由：列表、详情、筛选。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Exercise
from app.db.session import get_session
from app.schemas.exercise import (
    ExerciseFilterOptions,
    ExerciseListResponse,
    ExerciseOut,
)

router = APIRouter()


@router.get("/", response_model=ExerciseListResponse, summary="动作列表")
async def list_exercises(
    session: Annotated[AsyncSession, Depends(get_session)],
    # 筛选
    category: str | None = Query(None, description="大分类"),
    body_part: str | None = Query(None, description="身体部位"),
    equipment: str | None = Query(None, description="器械"),
    target: str | None = Query(None, description="目标肌肉"),
    keyword: str | None = Query(None, description="搜索关键词（中文名/英文名）"),
    # 分页
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(24, ge=1, le=2000, description="每页条数（最大2000）"),
) -> ExerciseListResponse:
    """分页查询动作。

    支持多条件筛选 + 关键词搜索（中英文名）。
    """
    # 构造查询
    stmt = select(Exercise)
    count_stmt = select(func.count()).select_from(Exercise)

    if category:
        stmt = stmt.where(Exercise.category == category)
        count_stmt = count_stmt.where(Exercise.category == category)
    if body_part:
        stmt = stmt.where(Exercise.body_part == body_part)
        count_stmt = count_stmt.where(Exercise.body_part == body_part)
    if equipment:
        stmt = stmt.where(Exercise.equipment == equipment)
        count_stmt = count_stmt.where(Exercise.equipment == equipment)
    if target:
        stmt = stmt.where(Exercise.target == target)
        count_stmt = count_stmt.where(Exercise.target == target)
    if keyword:
        like = f"%{keyword}%"
        # 简单搜索：中文名或英文名
        stmt = stmt.where(
            (Exercise.name_zh.like(like)) | (Exercise.name_en.ilike(like))
        )
        count_stmt = count_stmt.where(
            (Exercise.name_zh.like(like)) | (Exercise.name_en.ilike(like))
        )

    # 排序 + 分页
    stmt = stmt.order_by(Exercise.id).offset((page - 1) * page_size).limit(page_size + 1)

    # 执行
    result = await session.execute(stmt)
    rows = result.scalars().all()

    # 多查一条用于判断 has_more
    has_more = len(rows) > page_size
    items = rows[:page_size]

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    return ExerciseListResponse(
        items=[ExerciseOut.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get("/filters", response_model=ExerciseFilterOptions, summary="获取所有可筛选项")
async def get_filter_options(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExerciseFilterOptions:
    """返回前端筛选下拉的所有可选值（去重）。"""
    cats = await session.execute(select(Exercise.category).distinct().order_by(Exercise.category))
    parts = await session.execute(select(Exercise.body_part).distinct().order_by(Exercise.body_part))
    eqs = await session.execute(select(Exercise.equipment).distinct().order_by(Exercise.equipment))
    targets = await session.execute(select(Exercise.target).distinct().order_by(Exercise.target))

    return ExerciseFilterOptions(
        categories=[r for r in cats.scalars().all() if r],
        body_parts=[r for r in parts.scalars().all() if r],
        equipment=[r for r in eqs.scalars().all() if r],
        targets=[r for r in targets.scalars().all() if r],
    )


@router.get("/{exercise_id}", response_model=ExerciseOut, summary="动作详情")
async def get_exercise(
    exercise_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExerciseOut:
    """根据 ID 获取动作详情。"""
    result = await session.execute(select(Exercise).where(Exercise.id == exercise_id))
    exercise = result.scalar_one_or_none()

    if not exercise:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"动作 {exercise_id} 不存在",
        )

    return ExerciseOut.model_validate(exercise)