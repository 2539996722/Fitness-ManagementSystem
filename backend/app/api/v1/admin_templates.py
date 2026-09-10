"""管理员：模板审核 + 教练账号管理（PRD §9.9 中与模板相关部分）。

模板审核：
- GET    /api/v1/admin/templates/pending            待审核模板
- GET    /api/v1/admin/templates                    全部模板（任意状态）
- POST   /api/v1/admin/templates/{id}/approve       通过 → published
- POST   /api/v1/admin/templates/{id}/reject        驳回 → draft（带理由）
- POST   /api/v1/admin/templates/{id}/offline       强制下架 → offline
- POST   /api/v1/admin/templates/{id}/republish     重新上架（offline → published）

教练账号（MVP 最小集，仅创建，用于打通模板流程）：
- GET    /api/v1/admin/trainer-accounts             教练列表
- POST   /api/v1/admin/trainer-accounts             创建教练账号
- PATCH  /api/v1/admin/trainer-accounts/{id}        启停（status 切换）
"""

import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_role
from app.core.security import hash_password
from app.db.models import PlanTemplate, User
from app.db.models.plan_template import (
    ALL_STATUSES,
    STATUS_DRAFT,
    STATUS_OFFLINE,
    STATUS_PENDING,
    STATUS_PUBLISHED,
)
from app.db.session import get_session
from app.schemas.plan_template import (
    PlanTemplateCreate,
    PlanTemplateListResponse,
    PlanTemplateOut,
    PlanTemplateReviewUpdate,
    PlanTemplateUpdate,
)
from app.services.operation_log import record as log_operation
from pydantic import BaseModel, Field

router = APIRouter()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_out(t: PlanTemplate) -> PlanTemplateOut:
    return PlanTemplateOut.model_validate(t)


# ============ 模板审核 ============

@router.get(
    "/templates/queue",
    response_model=PlanTemplateListResponse,
    summary="admin 待处理队列（草稿 + 待审核，pending 优先）",
)
async def list_queue_templates(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PlanTemplateListResponse:
    base = (
        select(PlanTemplate)
        .where(PlanTemplate.status.in_([STATUS_DRAFT, STATUS_PENDING]))
        .order_by(
            # pending 排前（True=1，但 desc 后排在前）；updated_at 旧→新
            (PlanTemplate.status == STATUS_PENDING).desc(),
            PlanTemplate.updated_at.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
    )
    rows = (await session.execute(base)).scalars().all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    total = (
        await session.execute(
            select(func.count(PlanTemplate.id)).where(
                PlanTemplate.status.in_([STATUS_DRAFT, STATUS_PENDING])
            )
        )
    ).scalar() or 0
    return PlanTemplateListResponse(
        items=[_to_out(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get(
    "/templates/pending",
    response_model=PlanTemplateListResponse,
    summary="待审核模板",
)
async def list_pending_templates(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PlanTemplateListResponse:
    base = (
        select(PlanTemplate)
        .where(PlanTemplate.status == STATUS_PENDING)
        .order_by(PlanTemplate.updated_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
    )
    rows = (await session.execute(base)).scalars().all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    total = (
        await session.execute(
            select(func.count(PlanTemplate.id)).where(PlanTemplate.status == STATUS_PENDING)
        )
    ).scalar() or 0
    return PlanTemplateListResponse(
        items=[_to_out(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get(
    "/templates",
    response_model=PlanTemplateListResponse,
    summary="全部模板（任意状态）",
)
async def list_all_templates(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PlanTemplateListResponse:
    base = select(PlanTemplate)
    count_stmt = select(func.count()).select_from(PlanTemplate)
    if status_:
        if status_ not in ALL_STATUSES:
            raise HTTPException(status_code=400, detail=f"未知状态：{status_}")
        base = base.where(PlanTemplate.status == status_)
        count_stmt = count_stmt.where(PlanTemplate.status == status_)
    base = base.order_by(PlanTemplate.updated_at.desc()).offset((page - 1) * page_size).limit(page_size + 1)
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
    "/templates/{template_id}",
    response_model=PlanTemplateOut,
    summary="模板详情（admin 看任意；trainer 看自己的）",
)
async def get_template(
    template_id: int,
    actor: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if actor.role == "trainer" and t.author_id != actor.id:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _to_out(t)


@router.patch(
    "/templates/{template_id}",
    response_model=PlanTemplateOut,
    summary="admin 编辑任意模板（仅 draft / offline 可改）",
)
async def admin_update_template(
    template_id: int,
    body: PlanTemplateUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if t.status not in (STATUS_DRAFT, STATUS_OFFLINE):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态「{t.status}」不可编辑（仅 draft / offline 可改）",
        )

    update_data = body.model_dump(exclude_unset=True)
    if "weeks" in update_data and update_data["weeks"]:
        update_data["weeks"] = [
            w if isinstance(w, dict) else w.model_dump() for w in update_data["weeks"]
        ]
    for k, v in update_data.items():
        setattr(t, k, v)
    await session.commit()
    await session.refresh(t)
    return _to_out(t)


@router.post(
    "/templates",
    response_model=PlanTemplateOut,
    status_code=status.HTTP_201_CREATED,
    summary="admin 新建模板（默认草稿，可指定 status）",
)
async def admin_create_template(
    body: PlanTemplateCreate,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    initial_status = body.status if body.status in ALL_STATUSES else STATUS_DRAFT
    t = PlanTemplate(
        name=body.name,
        goal=body.goal,
        level=body.level,
        cover_url=body.cover_url,
        description=body.description,
        weeks=[w if isinstance(w, dict) else w.model_dump() for w in body.weeks],
        author_id=admin.id,
        status=initial_status,
        published_at=_utcnow_naive() if initial_status == STATUS_PUBLISHED else None,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    logger.info("admin={} 新建模板 {} 「{}」 (status={})", admin.id, t.id, t.name, initial_status)
    await log_operation(
        session=session,
        operator=admin,
        action="admin_create_template",
        target_type="template",
        target_id=t.id,
        summary=f"新建模板「{t.name}」（状态：{initial_status}）",
        details={"name": t.name, "goal": t.goal, "level": t.level, "status": initial_status},
    )
    return _to_out(t)


@router.post(
    "/templates/{template_id}/publish",
    response_model=PlanTemplateOut,
    summary="admin 直接上架（draft → published）",
)
async def admin_publish_template(
    template_id: int,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if t.status != STATUS_DRAFT:
        raise HTTPException(status_code=400, detail=f"只有 draft 可上架，当前：{t.status}")
    t.status = STATUS_PUBLISHED
    t.published_at = _utcnow_naive()
    t.reject_reason = None
    await session.commit()
    await session.refresh(t)
    logger.info("admin={} 直接上架模板 {} 「{}」", admin.id, template_id, t.name)
    await log_operation(
        session=session,
        operator=admin,
        action="admin_publish_template",
        target_type="template",
        target_id=template_id,
        summary=f"直接上架模板「{t.name}」",
    )
    return _to_out(t)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="admin 删除任意模板（任意状态）",
)
async def admin_delete_template(
    template_id: int,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    t = await session.get(PlanTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    await session.delete(t)
    await session.commit()
    logger.warning("admin={} 删除模板 {} 「{}」", admin.id, template_id, t.name)
    await log_operation(
        session=session,
        operator=admin,
        action="admin_delete_template",
        target_type="template",
        target_id=template_id,
        summary=f"删除模板「{t.name}」",
        details={"name": t.name, "status_before_delete": t.status},
    )


@router.post(
    "/templates/{template_id}/approve",
    response_model=PlanTemplateOut,
    summary="通过审核 → published",
)
async def approve_template(
    template_id: int,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if t.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail=f"只有 pending_review 可通过，当前：{t.status}")

    t.status = STATUS_PUBLISHED
    t.published_at = _utcnow_naive()
    t.reject_reason = None
    await session.commit()
    await session.refresh(t)
    logger.info("admin={} 审核通过模板 {}", admin.id, template_id)
    await log_operation(
        session=session,
        operator=admin,
        action="approve_template",
        target_type="template",
        target_id=template_id,
        summary=f"审核通过模板「{t.name}」",
    )
    return _to_out(t)


@router.post(
    "/templates/{template_id}/reject",
    response_model=PlanTemplateOut,
    summary="驳回（pending → draft，带理由）",
)
async def reject_template(
    template_id: int,
    body: PlanTemplateReviewUpdate,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if t.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail=f"只有 pending_review 可驳回，当前：{t.status}")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="驳回必须填写理由")

    t.status = STATUS_DRAFT
    t.reject_reason = reason
    await session.commit()
    await session.refresh(t)
    logger.info("admin={} 驳回模板 {} 理由={}", admin.id, template_id, reason)
    await log_operation(
        session=session,
        operator=admin,
        action="reject_template",
        target_type="template",
        target_id=template_id,
        summary=f"驳回模板「{t.name}」",
        details={"reason": reason},
    )
    return _to_out(t)


@router.post(
    "/templates/{template_id}/offline",
    response_model=PlanTemplateOut,
    summary="强制下架（published → offline）",
)
async def offline_template(
    template_id: int,
    body: PlanTemplateReviewUpdate,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if t.status != STATUS_PUBLISHED:
        raise HTTPException(status_code=400, detail=f"只有 published 可下架，当前：{t.status}")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="下架必须填写理由")

    t.status = STATUS_OFFLINE
    t.reject_reason = reason
    await session.commit()
    await session.refresh(t)
    logger.warning("admin={} 强下架模板 {} 理由={}", admin.id, template_id, reason)
    await log_operation(
        session=session,
        operator=admin,
        action="offline_template",
        target_type="template",
        target_id=template_id,
        summary=f"强下架模板「{t.name}」",
        details={"reason": reason},
    )
    return _to_out(t)


@router.post(
    "/templates/{template_id}/republish",
    response_model=PlanTemplateOut,
    summary="重新上架（offline → published）",
)
async def republish_template(
    template_id: int,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")
    if t.status != STATUS_OFFLINE:
        raise HTTPException(status_code=400, detail=f"只有 offline 可重新上架，当前：{t.status}")

    t.status = STATUS_PUBLISHED
    t.published_at = _utcnow_naive()
    t.reject_reason = None
    await session.commit()
    await session.refresh(t)
    logger.info("admin={} 重新上架模板 {}", admin.id, template_id)
    await log_operation(
        session=session,
        operator=admin,
        action="republish_template",
        target_type="template",
        target_id=template_id,
        summary=f"重新上架模板「{t.name}」",
    )
    return _to_out(t)


# ============ 教练账号管理（最小集） ============

USERNAME_PATTERN = re.compile(r"^[\w一-龥]{3,32}$", re.UNICODE)
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,20}$")


class TrainerCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=20)
    nickname: str | None = Field(None, max_length=32)


class TrainerItem(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    username: str
    nickname: str | None
    role: str
    status: int
    created_at: datetime
    last_login_at: datetime | None


@router.get(
    "/trainer-accounts",
    response_model=list[TrainerItem],
    summary="教练列表",
)
async def list_trainers(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TrainerItem]:
    rows = (
        await session.execute(
            select(User).where(User.role == "trainer").order_by(User.created_at.desc())
        )
    ).scalars().all()
    return [TrainerItem.model_validate(u) for u in rows]


@router.post(
    "/trainer-accounts",
    response_model=TrainerItem,
    status_code=status.HTTP_201_CREATED,
    summary="创建教练账号",
)
async def create_trainer(
    body: TrainerCreate,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainerItem:
    if not USERNAME_PATTERN.match(body.username):
        raise HTTPException(status_code=400, detail="用户名格式错误")
    if not PASSWORD_PATTERN.match(body.password):
        raise HTTPException(status_code=400, detail="密码格式错误（8-20 字符，必须含字母和数字）")

    existing = await session.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="用户名已被占用")

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.username,
        role="trainer",
        status=0,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="用户名已被占用")
    await session.refresh(user)
    logger.info("admin={} 创建教练账号 id={} username={}", admin.id, user.id, user.username)
    await log_operation(
        session=session,
        operator=admin,
        action="create_trainer_account",
        target_type="user",
        target_id=user.id,
        summary=f"创建教练账号 {user.username}（{user.id}）",
        details={"username": user.username, "nickname": user.nickname},
    )
    return TrainerItem.model_validate(user)


@router.patch(
    "/trainer-accounts/{user_id}",
    response_model=TrainerItem,
    summary="启停教练账号（status 切换）",
)
async def toggle_trainer(
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainerItem:
    user = await session.get(User, user_id)
    if not user or user.role != "trainer":
        raise HTTPException(status_code=404, detail="教练不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能操作自己的账号")
    user.status = 0 if user.status == 1 else 1
    await session.commit()
    await session.refresh(user)
    logger.info("admin={} 切换教练 {} 状态 → {}", admin.id, user_id, user.status)
    await log_operation(
        session=session,
        operator=admin,
        action="toggle_trainer_status",
        target_type="user",
        target_id=user_id,
        summary=f"{'启用' if user.status == 0 else '停用'}教练 {user.username}（{user_id}）",
        details={"new_status": user.status},
    )
    return TrainerItem.model_validate(user)