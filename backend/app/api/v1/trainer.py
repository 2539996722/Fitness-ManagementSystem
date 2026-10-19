"""教练工作台路由（PRD §9.8）。

模板管理：
- GET    /api/v1/trainer/templates               我的模板（含全部状态）
- GET    /api/v1/trainer/templates/queue         我的待处理（draft + pending_review）
- POST   /api/v1/trainer/templates               新建模板（草稿）
- PATCH  /api/v1/trainer/templates/{id}          编辑模板（仅 draft / offline）
- DELETE /api/v1/trainer/templates/{id}          删除草稿
- POST   /api/v1/trainer/templates/{id}/submit   提交审核（draft → pending_review）

会员咨询会话工作台（M8/M4：教练兼任客服，统一处理 trainer + customer_service 两类会话）：
- GET    /api/v1/trainer/queue                          待处理队列（trainer + 旧 customer_service 兼容）
- POST   /api/v1/trainer/conversations/{id}/claim       接入会话
- POST   /api/v1/trainer/conversations/{id}/messages    发消息
- GET    /api/v1/trainer/conversations/{id}/messages    会话消息历史
- GET    /api/v1/trainer/conversations/{id}/stream      SSE 推送
- POST   /api/v1/trainer/conversations/{id}/close       结束会话，回退 AI
- POST   /api/v1/trainer/conversations/{id}/recommend-template   推荐模板
- POST   /api/v1/trainer/conversations/{id}/customize-plan       一键定制计划
"""

import re
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user, require_role
from app.db.models import Conversation, Message, Plan, PlanTemplate, User
from app.db.models.plan_template import (
    ALL_STATUSES,
    STATUS_DRAFT,
    STATUS_OFFLINE,
    STATUS_PENDING,
    STATUS_PUBLISHED,
)
from app.db.session import async_session, get_session
from app.schemas.chat import MessageOut
from app.schemas.plan_template import (
    PlanTemplateCreate,
    PlanTemplateListResponse,
    PlanTemplateOut,
    PlanTemplateUpdate,
)
from app.services.operation_log import record as log_operation
from pydantic import BaseModel, Field

router = APIRouter()

# 教练可见的状态：全部
_TRAINER_STATUSES = ALL_STATUSES

USERNAME_PATTERN = re.compile(r"^[\w一-龥]{3,32}$", re.UNICODE)
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,20}$")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_out(t: PlanTemplate) -> PlanTemplateOut:
    return PlanTemplateOut.model_validate(t)


# ============ 我的模板 ============

@router.get(
    "/templates",
    response_model=PlanTemplateListResponse,
    summary="教练：我的模板列表",
)
async def list_my_templates(
    session: Annotated[AsyncSession, Depends(get_session)],
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    status_: str | None = Query(None, alias="status", description="按状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PlanTemplateListResponse:
    base = select(PlanTemplate).where(PlanTemplate.author_id == trainer.id)
    count_stmt = select(func.count()).select_from(base.subquery())
    if status_:
        if status_ not in _TRAINER_STATUSES:
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
    "/templates/queue",
    response_model=PlanTemplateListResponse,
    summary="教练：我的待处理（draft + pending_review，pending 优先）",
)
async def list_my_pending_templates(
    session: Annotated[AsyncSession, Depends(get_session)],
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PlanTemplateListResponse:
    base = (
        select(PlanTemplate)
        .where(PlanTemplate.author_id == trainer.id)
        .where(PlanTemplate.status.in_([STATUS_DRAFT, STATUS_PENDING]))
        .order_by(
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
            select(func.count(PlanTemplate.id))
            .where(PlanTemplate.author_id == trainer.id)
            .where(PlanTemplate.status.in_([STATUS_DRAFT, STATUS_PENDING]))
        )
    ).scalar() or 0
    return PlanTemplateListResponse(
        items=[_to_out(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.post(
    "/templates",
    response_model=PlanTemplateOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建模板（草稿）",
)
async def create_template(
    body: PlanTemplateCreate,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = PlanTemplate(
        name=body.name,
        goal=body.goal,
        level=body.level,
        cover_url=body.cover_url,
        description=body.description,
        weeks=[w if isinstance(w, dict) else w.model_dump() for w in body.weeks],
        author_id=trainer.id,
        status=STATUS_DRAFT,
        use_count=0,         # 默认 0（必须显式，ORM 不给非 nullable 列默认值）
        avg_rating=0.0,
        review_count=0,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    logger.info("教练 {} 新建模板 {} 「{}」", trainer.id, t.id, t.name)
    await log_operation(
        session=session,
        operator=trainer,
        action="trainer_create_template",
        target_type="template",
        target_id=t.id,
        summary=f"教练 {trainer.username} 新建模板「{t.name}」",
    )
    return _to_out(t)


@router.patch(
    "/templates/{template_id}",
    response_model=PlanTemplateOut,
    summary="编辑模板（仅 draft / offline）",
)
async def update_template(
    template_id: int,
    body: PlanTemplateUpdate,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t or t.author_id != trainer.id:
        raise HTTPException(status_code=404, detail="模板不存在或不是你的")
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
    await log_operation(
        session=session,
        operator=trainer,
        action="trainer_update_template",
        target_type="template",
        target_id=template_id,
        summary=f"教练 {trainer.username} 编辑模板「{t.name}」",
        details={"updated_fields": list(update_data.keys())},
    )
    return _to_out(t)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除草稿（draft / offline）",
)
async def delete_template(
    template_id: int,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    t = await session.get(PlanTemplate, template_id)
    if not t or t.author_id != trainer.id:
        raise HTTPException(status_code=404, detail="模板不存在或不是你的")
    if t.status not in (STATUS_DRAFT, STATUS_OFFLINE):
        raise HTTPException(status_code=400, detail=f"状态「{t.status}」不可删除")
    await session.delete(t)
    await session.commit()
    await log_operation(
        session=session,
        operator=trainer,
        action="trainer_delete_template",
        target_type="template",
        target_id=template_id,
        summary=f"教练 {trainer.username} 删除模板 {template_id}（草稿/已下架）",
    )


@router.post(
    "/templates/{template_id}/submit",
    response_model=PlanTemplateOut,
    summary="提交审核（draft → pending_review）",
)
async def submit_template(
    template_id: int,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlanTemplateOut:
    t = await session.get(PlanTemplate, template_id)
    if not t or t.author_id != trainer.id:
        raise HTTPException(status_code=404, detail="模板不存在或不是你的")
    if t.status != STATUS_DRAFT:
        raise HTTPException(status_code=400, detail=f"只有 draft 可提交审核，当前状态：{t.status}")

    t.status = STATUS_PENDING
    t.reject_reason = None
    await session.commit()
    await session.refresh(t)
    logger.info("教练 {} 提交模板 {} 审核", trainer.id, template_id)
    await log_operation(
        session=session,
        operator=trainer,
        action="trainer_submit_template",
        target_type="template",
        target_id=template_id,
        summary=f"教练 {trainer.username} 提交模板「{t.name}」审核",
    )
    return _to_out(t)


# ============ 教练会话工作台（M8 / M4 合并：教练兼任客服） ============

# 教练工作台认领的会话类型（M4 合并后只剩 trainer）
_HUMAN_CONV_TYPES = ("trainer",)


async def _check_trainer_conv(
    conv_id: int,
    trainer: User,
    session: AsyncSession,
    require_claimed: bool = False,
) -> Conversation:
    """共用的会话校验：存在 → conversation_type='trainer' → 已分配给当前教练（如果 require_claimed）。"""
    conv = await session.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.conversation_type not in _HUMAN_CONV_TYPES:
        raise HTTPException(status_code=400, detail="该会话不是人工咨询类型")
    if require_claimed and conv.assigned_trainer_id != trainer.id and trainer.role != "admin":
        raise HTTPException(status_code=403, detail="未接入此会话")
    return conv


@router.get(
    "/queue",
    summary="教练：待处理队列",
)
async def trainer_queue(
    session: Annotated[AsyncSession, Depends(get_session)],
    _trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
):
    """返回 conversation_type='trainer' AND status='waiting_trainer' 的会话。"""
    rows = (
        await session.execute(
            select(Conversation)
            .where(
                Conversation.conversation_type.in_(_HUMAN_CONV_TYPES),
                Conversation.status.in_(("waiting_trainer", "waiting_human")),
            )
            .order_by(Conversation.updated_at.asc())
            .limit(50)
        )
    ).scalars().all()

    out = []
    for c in rows:
        u = (await session.execute(select(User).where(User.id == c.user_id))).scalar_one_or_none()
        last_msg = (await session.execute(
            select(Message)
            .where(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        out.append({
            "conversation_id": c.id,
            "user_id": c.user_id,
            "username": u.username if u else "未知",
            "nickname": u.nickname if u else None,
            "title": c.title,
            "last_message": last_msg.content[:80] if last_msg else None,
            "status": c.status,
            "waiting_since": c.updated_at.isoformat() if c.updated_at else None,
        })

    return {"items": out, "total": len(out)}


@router.get(
    "/conversations/history",
    summary="教练：我处理过的会话（已结束 / 退回 AI）",
)
async def trainer_history(
    session: Annotated[AsyncSession, Depends(get_session)],
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    limit: int = 50,
    offset: int = 0,
):
    """assigned_trainer_id = me，排除还在 waiting_* 队列里的。"""
    rows = (
        await session.execute(
            select(Conversation)
            .where(
                Conversation.conversation_type.in_(_HUMAN_CONV_TYPES),
                Conversation.assigned_trainer_id == trainer.id,
                Conversation.status.notin_(("waiting_trainer", "waiting_human")),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit).offset(offset)
        )
    ).scalars().all()

    out = []
    for c in rows:
        u = (await session.execute(select(User).where(User.id == c.user_id))).scalar_one_or_none()
        last_msg = (await session.execute(
            select(Message)
            .where(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        out.append({
            "conversation_id": c.id,
            "user_id": c.user_id,
            "username": u.username if u else "未知",
            "nickname": u.nickname if u else None,
            "title": c.title,
            "status": c.status,
            "last_message": last_msg.content[:80] if last_msg else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })

    return {"items": out, "total": len(out)}


@router.post(
    "/conversations/{conv_id}/claim",
    summary="教练接入会话",
)
async def claim_trainer_conversation(
    conv_id: int,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    conv = await _check_trainer_conv(conv_id, trainer, session)
    if conv.status not in ("waiting_trainer", "waiting_human", "trainer_active", "human_active"):
        raise HTTPException(status_code=400, detail=f"会话状态 {conv.status} 不可接入")
    if conv.assigned_trainer_id and conv.assigned_trainer_id != trainer.id:
        raise HTTPException(status_code=409, detail="会话已被其他人接入")

    conv.assigned_trainer_id = trainer.id
    conv.status = "trainer_active"
    await session.commit()
    logger.info("教练 {} 接入会话 {}", trainer.id, conv_id)
    await log_operation(
        session=session,
        operator=trainer,
        action="trainer_claim_conversation",
        target_type="conversation",
        target_id=conv_id,
        summary=f"教练 {trainer.username} 接入会话 {conv_id}",
    )
    return {"conversation_id": conv.id, "status": conv.status, "trainer_id": trainer.id}


@router.post(
    "/conversations/{conv_id}/messages",
    response_model=MessageOut,
    summary="教练发消息",
)
async def send_trainer_message(
    conv_id: int,
    body: dict,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageOut:
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    if len(content) > 4000:
        raise HTTPException(status_code=400, detail="内容过长")

    conv = await _check_trainer_conv(conv_id, trainer, session, require_claimed=True)
    if conv.status not in ("trainer_active", "human_active"):
        raise HTTPException(status_code=400, detail="会话不在服务状态")

    msg = Message(
        conversation_id=conv.id,
        sender_type="trainer",
        sender_id=trainer.id,
        content=content,
        extra={"trainer_nickname": trainer.nickname or trainer.username},
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return MessageOut.model_validate(msg)


@router.get(
    "/conversations/{conv_id}/messages",
    response_model=list[MessageOut],
    summary="拉取会话消息历史（教练视角）",
)
async def list_trainer_messages(
    conv_id: int,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MessageOut]:
    conv = await _check_trainer_conv(conv_id, trainer, session)
    rows = (await session.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )).scalars().all()
    return [MessageOut.model_validate(m) for m in rows]


@router.get(
    "/conversations/{conv_id}/stream",
    summary="教练 SSE：推送会话新消息",
)
async def trainer_stream(
    conv_id: int,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventSourceResponse:
    conv = await _check_trainer_conv(conv_id, trainer, session)
    last_id_result = await session.execute(
        select(Message.id)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.id.desc())
        .limit(1)
    )
    last_id = last_id_result.scalar() or 0

    async def event_gen() -> AsyncIterator[dict]:
        nonlocal last_id
        try:
            async with async_session() as s:
                cv = await s.get(Conversation, conv_id)
                if cv:
                    yield {"event": "message", "data": json.dumps(
                        {"type": "status", "status": cv.status, "assigned_trainer_id": cv.assigned_trainer_id},
                        ensure_ascii=False,
                    )}
        except Exception as e:
            logger.warning("trainer SSE 初始状态失败：{}", e)

        while True:
            try:
                async with async_session() as s:
                    new_msgs = await s.execute(
                        select(Message)
                        .where(Message.conversation_id == conv_id, Message.id > last_id)
                        .order_by(Message.id.asc())
                    )
                    msgs = new_msgs.scalars().all()
                    for m in msgs:
                        last_id = max(last_id, m.id)
                        yield {"event": "message", "data": json.dumps(
                            {"type": "message", "message": {
                                "id": m.id, "conversation_id": m.conversation_id,
                                "sender_type": m.sender_type, "sender_id": m.sender_id,
                                "content": m.content, "extra": m.extra or {},
                                "created_at": m.created_at.isoformat() if m.created_at else None,
                            }},
                            ensure_ascii=False,
                        )}
                    cv = await s.get(Conversation, conv_id)
                    if cv:
                        yield {"event": "message", "data": json.dumps(
                            {"type": "status", "status": cv.status, "assigned_trainer_id": cv.assigned_trainer_id},
                            ensure_ascii=False,
                        )}
            except Exception as e:
                logger.warning("trainer SSE 轮询失败：{}", e)
            import asyncio
            await asyncio.sleep(1)

    return EventSourceResponse(event_gen())


@router.post(
    "/conversations/{conv_id}/close",
    summary="教练结束会话，回退 AI",
)
async def close_trainer_conversation(
    conv_id: int,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """结束本次教练服务：插入 CS 风格消息（sender_type=trainer） + 状态回到 ai_active。"""
    conv = await _check_trainer_conv(conv_id, trainer, session, require_claimed=True)
    if conv.assigned_trainer_id != trainer.id and trainer.role != "admin":
        raise HTTPException(status_code=403, detail="无权结束此会话")

    msg = Message(
        conversation_id=conv.id,
        sender_type="trainer",
        sender_id=trainer.id,
        content="本次教练咨询已结束，后续将由 AI 教练继续为你服务。如需再次接入教练，请说「找教练」。",
    )
    session.add(msg)
    conv.status = "ai_active"
    conv.conversation_type = "ai"
    # assigned_trainer_id 保留给历史查询
    await session.commit()
    await session.refresh(msg)
    logger.info("教练 {} 结束会话 {} → ai_active", trainer.id, conv_id)
    await log_operation(
        session=session,
        operator=trainer,
        action="trainer_end_conversation",
        target_type="conversation",
        target_id=conv_id,
        summary=f"教练 {trainer.username} 结束会话 {conv_id}",
    )
    return {"conversation_id": conv.id, "status": conv.status, "ended_message_id": msg.id}


# ============ 教练专有能力：推荐模板 + 定制计划 ============

class RecommendTemplateIn(BaseModel):
    template_id: int = Field(..., description="要推荐的模板 ID")


@router.post(
    "/conversations/{conv_id}/recommend-template",
    response_model=MessageOut,
    summary="推荐模板给会员（在聊天中插入模板卡片）",
)
async def recommend_template(
    conv_id: int,
    body: RecommendTemplateIn,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageOut:
    conv = await _check_trainer_conv(conv_id, trainer, session, require_claimed=True)
    tpl = await session.get(PlanTemplate, body.template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    if tpl.status != STATUS_PUBLISHED:
        raise HTTPException(status_code=400, detail=f"模板「{tpl.name}」未发布，不能推荐")

    msg = Message(
        conversation_id=conv.id,
        sender_type="trainer",
        sender_id=trainer.id,
        content=f"教练向你推荐训练计划模板：「{tpl.name}」",
        extra={
            "kind": "recommend_template",
            "template": {
                "id": tpl.id,
                "name": tpl.name,
                "goal": tpl.goal,
                "level": tpl.level,
                "cover_url": tpl.cover_url,
                "description": tpl.description,
            },
        },
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    logger.info("教练 {} 推荐模板 {} 给会话 {}", trainer.id, tpl.id, conv_id)
    await log_operation(
        session=session,
        operator=trainer,
        action="trainer_recommend_template",
        target_type="conversation",
        target_id=conv_id,
        summary=f"教练 {trainer.username} 向会话 {conv_id} 推荐模板「{tpl.name}」（{tpl.id}）",
    )
    return MessageOut.model_validate(msg)


class CustomizePlanIn(BaseModel):
    """MVP 简化：基于已发布模板一键为会员复制 plan（可改名）。"""
    template_id: int = Field(..., description="要基于的模板 ID")
    name: str | None = Field(None, max_length=64, description="计划名（不填则用模板名）")


@router.post(
    "/conversations/{conv_id}/customize-plan",
    summary="为会员定制计划（基于模板一键复制 plan）",
)
async def customize_plan(
    conv_id: int,
    body: CustomizePlanIn,
    trainer: Annotated[User, Depends(require_role("trainer", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    conv = await _check_trainer_conv(conv_id, trainer, session, require_claimed=True)
    tpl = await session.get(PlanTemplate, body.template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    if tpl.status != STATUS_PUBLISHED:
        raise HTTPException(status_code=400, detail=f"模板「{tpl.name}」未发布")

    # 复制 weeks
    weeks_payload = tpl.weeks if isinstance(tpl.weeks, list) else []
    days_per_week = max((len(w.get("days", [])) for w in weeks_payload), default=3)

    new_plan = Plan(
        user_id=conv.user_id,
        name=body.name or tpl.name,
        goal=tpl.goal,
        weeks=weeks_payload,
        days_per_week=days_per_week,
        equipment=[],
        is_current=1,
    )
    session.add(new_plan)
    await session.flush()

    # 把该会员的其他计划置为非 current
    await session.execute(
        update(Plan)
        .where(Plan.user_id == conv.user_id, Plan.id != new_plan.id)
        .values(is_current=0)
    )

    # 模板使用次数 +1
    await session.execute(
        update(PlanTemplate)
        .where(PlanTemplate.id == tpl.id)
        .values(use_count=PlanTemplate.use_count + 1)
    )

    # 在会话里推一条系统消息
    sys_msg = Message(
        conversation_id=conv.id,
        sender_type="trainer",
        sender_id=trainer.id,
        content=f"教练为你定制了训练计划「{new_plan.name}」，已设为你的当前计划",
        extra={"kind": "customize_plan", "plan_id": new_plan.id, "template_id": tpl.id},
    )
    session.add(sys_msg)
    await session.commit()
    await session.refresh(new_plan)
    logger.info("教练 {} 为会话 {} 定制计划 {} (基于模板 {})", trainer.id, conv_id, new_plan.id, tpl.id)
    await log_operation(
        session=session,
        operator=trainer,
        action="trainer_customize_plan",
        target_type="conversation",
        target_id=conv_id,
        summary=f"教练 {trainer.username} 为会话 {conv_id} 定制计划「{new_plan.name}」（基于模板 {tpl.id}）",
        details={"plan_id": new_plan.id, "template_id": tpl.id, "user_id": conv.user_id},
    )
    return {"plan_id": new_plan.id, "template_id": tpl.id, "name": new_plan.name, "message_id": sys_msg.id}


# ============ C 端：转教练 ============
# ponytail: 这条路由虽然写在 trainer.py，但属于 C 端用户主动触发，需放在 chat.py 才不会被 /trainer 前缀遮蔽
# 实际逻辑见 chat.py:user_transfer_to_trainer；这里只留空函数防 grep 找到死链
