"""训练计划路由：CRUD + 打卡 + 统计。"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Exercise, Plan, TrainingRecord, User
from app.db.session import get_session
from app.schemas.plan import (
    PlanCreate,
    PlanListItem,
    PlanOut,
    PlanUpdate,
    TrainingRecordIn,
    TrainingRecordOut,
)

router = APIRouter()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/", response_model=list[PlanListItem], summary="我的计划列表")
async def list_my_plans(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PlanListItem]:
    """列出当前用户的所有训练计划（含进度统计）。"""
    # 1. 查所有计划
    result = await session.execute(
        select(Plan)
        .where(Plan.user_id == current_user.id)
        .order_by(Plan.is_current.desc(), Plan.updated_at.desc())
    )
    plans = result.scalars().all()

    # 2. 对每个计划统计进度
    items: list[PlanListItem] = []
    for plan in plans:
        # weeks 是 JSON 列，读出来是 list of dict（不是 ORM 对象）
        # 所以访问要用 w["days"] 而非 w.days
        total_days = sum(len(w.get("days", [])) for w in plan.weeks)

        # 已打卡数（按 week+day+exercise 组合去重）
        rec_result = await session.execute(
            select(TrainingRecord.plan_week, TrainingRecord.plan_day)
            .where(
                TrainingRecord.plan_id == plan.id,
                TrainingRecord.user_id == current_user.id,
            )
            .distinct()
        )
        unique_day_combos = {(r.plan_week, r.plan_day) for r in rec_result.all()}
        completed_days = len(unique_day_combos)

        progress_pct = (completed_days / total_days * 100) if total_days > 0 else 0.0

        # 收集该计划涉及的 exercise_id，去重查媒体字段
        ex_ids: set[str] = set()
        for w in plan.weeks:
            for d in w.get("days", []):
                for ex in d.get("exercises", []):
                    if ex.get("exercise_id"):
                        ex_ids.add(ex["exercise_id"])

        media_map: dict[str, dict] = {}
        if ex_ids:
            ex_rows = await session.execute(
                select(Exercise.id, Exercise.image, Exercise.gif_url).where(Exercise.id.in_(ex_ids))
            )
            for row in ex_rows.all():
                media_map[row.id] = {
                    "image": f"/static/images/{row.image.split('/')[-1]}" if row.image else None,
                    "gif": f"/static/videos/{row.gif_url.split('/')[-1]}" if row.gif_url else None,
                }

        # 从第一周抽前 6 个动作的完整媒体信息
        thumb_items: list[dict] = []
        if plan.weeks:
            for day in plan.weeks[0].get("days", []):
                for ex in day.get("exercises", []):
                    eid = ex.get("exercise_id")
                    if eid and eid in media_map and len(thumb_items) < 6:
                        thumb_items.append({
                            "id": eid,
                            **media_map[eid],
                        })

        items.append(
            PlanListItem(
                id=plan.id,
                user_id=plan.user_id,
                name=plan.name,
                goal=plan.goal,
                is_current=plan.is_current,
                days_per_week=plan.days_per_week,
                created_at=plan.created_at,
                updated_at=plan.updated_at,
                total_days=total_days,
                completed_days=completed_days,
                progress_pct=round(progress_pct, 1),
                weeks=plan.weeks or [],
                thumbnails=thumb_items,
            )
        )
    return items


@router.post("/", response_model=PlanOut, status_code=status.HTTP_201_CREATED, summary="创建计划")
async def create_plan(
    body: PlanCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanOut:
    """创建新的训练计划。"""
    # 如果标记为 current，先把其他计划的 current 标记取消
    plan = Plan(
        user_id=current_user.id,
        name=body.name,
        goal=body.goal,
        weeks=[w.model_dump() for w in body.weeks],
        days_per_week=body.days_per_week,
        equipment=body.equipment,
        is_current=1,
    )
    session.add(plan)
    await session.flush()

    # 把其他计划的 current 标记取消
    if plan.is_current == 1:
        from sqlalchemy import update

        await session.execute(
            update(Plan)
            .where(Plan.user_id == current_user.id, Plan.id != plan.id)
            .values(is_current=0)
        )

    await session.commit()
    await session.refresh(plan)
    logger.info("用户 {} 创建计划：{}", current_user.id, plan.name)
    return PlanOut.model_validate(plan)


@router.get("/{plan_id}", response_model=PlanOut, summary="计划详情")
async def get_plan(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanOut:
    """获取某个计划的完整结构。"""
    result = await session.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == current_user.id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"计划 {plan_id} 不存在")
    return PlanOut.model_validate(plan)


@router.patch("/{plan_id}", response_model=PlanOut, summary="更新计划")
async def update_plan(
    plan_id: int,
    body: PlanUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanOut:
    """更新计划（部分字段）。如果 is_current 设为 true，其他计划自动取消。"""
    result = await session.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == current_user.id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"计划 {plan_id} 不存在")

    # 更新字段
    update_data = body.model_dump(exclude_unset=True)
    if "weeks" in update_data and update_data["weeks"]:
        update_data["weeks"] = [w if isinstance(w, dict) else w.model_dump() for w in update_data["weeks"]]

    for k, v in update_data.items():
        setattr(plan, k, v)

    # 如果标记为 current，同步其他计划
    if plan.is_current == 1:
        from sqlalchemy import update

        await session.execute(
            update(Plan)
            .where(Plan.user_id == current_user.id, Plan.id != plan.id)
            .values(is_current=0)
        )

    await session.commit()
    await session.refresh(plan)
    return PlanOut.model_validate(plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除计划")
async def delete_plan(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """删除计划（同时级联删除所有打卡记录）。"""
    result = await session.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == current_user.id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"计划 {plan_id} 不存在")

    await session.delete(plan)
    await session.commit()
    return None


# ============ 训练记录（打卡）============

@router.post(
    "/{plan_id}/records",
    response_model=TrainingRecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="提交打卡",
)
async def submit_training_record(
    plan_id: int,
    body: TrainingRecordIn,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingRecordOut:
    """记录一次打卡。"""
    if body.plan_id != plan_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL 中的 plan_id 与请求体不一致",
        )

    # 验证计划存在且属于当前用户
    plan_result = await session.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == current_user.id)
    )
    if not plan_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"计划 {plan_id} 不存在")

    record = TrainingRecord(
        user_id=current_user.id,
        plan_id=plan_id,
        exercise_id=body.exercise_id,
        plan_week=body.plan_week,
        plan_day=body.plan_day,
        completed_sets=body.completed_sets,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return TrainingRecordOut.model_validate(record)


@router.get(
    "/{plan_id}/records",
    response_model=list[TrainingRecordOut],
    summary="获取打卡记录",
)
async def list_training_records(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    week: int | None = None,
    day: int | None = None,
) -> list[TrainingRecordOut]:
    """获取某个计划的所有打卡记录（可按周/天筛选）。"""
    stmt = select(TrainingRecord).where(
        TrainingRecord.plan_id == plan_id,
        TrainingRecord.user_id == current_user.id,
    )
    if week is not None:
        stmt = stmt.where(TrainingRecord.plan_week == week)
    if day is not None:
        stmt = stmt.where(TrainingRecord.plan_day == day)
    stmt = stmt.order_by(TrainingRecord.recorded_at.desc())

    result = await session.execute(stmt)
    records = result.scalars().all()
    return [TrainingRecordOut.model_validate(r) for r in records]


@router.post(
    "/{plan_id}/set-current",
    response_model=PlanOut,
    summary="设为当前计划",
)
async def set_current_plan(
    plan_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanOut:
    """把某个计划设为当前计划（其他自动取消）。"""
    result = await session.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == current_user.id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"计划 {plan_id} 不存在")

    from sqlalchemy import update

    await session.execute(
        update(Plan)
        .where(Plan.user_id == current_user.id, Plan.id != plan_id)
        .values(is_current=0)
    )
    plan.is_current = 1
    await session.commit()
    await session.refresh(plan)
    return PlanOut.model_validate(plan)