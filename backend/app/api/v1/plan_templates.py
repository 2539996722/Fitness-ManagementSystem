"""计划模板路由（C 端，PRD §9.7）。

- GET    /api/v1/plan-templates                  模板市场（仅 published）
- GET    /api/v1/plan-templates/{id}             模板详情（仅 published）
- POST   /api/v1/plan-templates/{id}/adopt       采用模板为我的计划
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Plan, PlanTemplate, User
from app.db.session import get_session
from app.db.models.plan_template import STATUS_PUBLISHED
from app.schemas.plan_template import (
    PlanTemplateAdoptResponse,
    PlanTemplateListResponse,
    PlanTemplateOut,
)
from app.schemas.plan import PlanWeek

router = APIRouter()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_out(t: PlanTemplate) -> PlanTemplateOut:
    return PlanTemplateOut.model_validate(t)


@router.get(
    "",
    response_model=PlanTemplateListResponse,
    summary="模板市场（仅已发布）",
)
async def list_market_templates(
    session: Annotated[AsyncSession, Depends(get_session)],
    goal: str | None = Query(None, description="目标筛选"),
    level: str | None = Query(None, description="适用人群筛选"),
    keyword: str | None = Query(None, description="模板名模糊匹配"),
    sort: str = Query("hot", description="hot / new / rating"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
) -> PlanTemplateListResponse:
    base = select(PlanTemplate).where(PlanTemplate.status == STATUS_PUBLISHED)
    count_stmt = select(func.count()).select_from(base.subquery())

    if goal:
        base = base.where(PlanTemplate.goal == goal)
        count_stmt = count_stmt.where(PlanTemplate.goal == goal)
    if level:
        base = base.where(PlanTemplate.level == level)
        count_stmt = count_stmt.where(PlanTemplate.level == level)
    if keyword:
        like = f"%{keyword}%"
        base = base.where(PlanTemplate.name.like(like))
        count_stmt = count_stmt.where(PlanTemplate.name.like(like))

    if sort == "new":
        base = base.order_by(PlanTemplate.published_at.desc())
    elif sort == "rating":
        base = base.order_by(PlanTemplate.avg_rating.desc().nullslast(), PlanTemplate.use_count.desc())
    else:  # hot
        base = base.order_by(PlanTemplate.use_count.desc(), PlanTemplate.published_at.desc())

    base = base.offset((page - 1) * page_size).limit(page_size + 1)
    rows = (await session.execute(base)).scalars().all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    total = (await session.execute(count_stmt)).scalar() or 0

    return PlanTemplateListResponse(
        items=[_to_out(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get(
    "/{template_id}",
    response_model=PlanTemplateOut,
    summary="模板详情（仅已发布）",
)
async def get_market_template(
    template_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t or t.status != STATUS_PUBLISHED:
        raise HTTPException(status_code=404, detail=f"模板 {template_id} 不存在或未发布")
    return _to_out(t)


@router.post(
    "/{template_id}/adopt",
    response_model=PlanTemplateAdoptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="采用模板为我的计划",
)
async def adopt_template(
    template_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateAdoptResponse:
    tpl = await session.get(PlanTemplate, template_id)
    if not tpl or tpl.status != STATUS_PUBLISHED:
        raise HTTPException(status_code=404, detail=f"模板 {template_id} 不存在或未发布")

    # weeks 是 list[PlanWeek]（dict），直接存入 plans.weeks
    weeks_payload = tpl.weeks if isinstance(tpl.weeks, list) else []
    days_per_week = max((len(w.get("days", [])) for w in weeks_payload), default=3)

    new_plan = Plan(
        user_id=current_user.id,
        name=tpl.name,
        goal=tpl.goal,
        weeks=weeks_payload,
        days_per_week=days_per_week,
        equipment=[],
        is_current=1,
    )
    session.add(new_plan)
    await session.flush()  # 拿到新 plan.id

    # 把其他计划置为非 current
    await session.execute(
        update(Plan)
        .where(Plan.user_id == current_user.id, Plan.id != new_plan.id)
        .values(is_current=0)
    )

    # use_count +1
    await session.execute(
        update(PlanTemplate)
        .where(PlanTemplate.id == template_id)
        .values(use_count=PlanTemplate.use_count + 1)
    )

    await session.commit()
    await session.refresh(new_plan)
    logger.info("用户 {} 采用模板 {} → 新计划 {}", current_user.id, template_id, new_plan.id)

    return PlanTemplateAdoptResponse(plan_id=new_plan.id, template_id=template_id)