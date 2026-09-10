"""B 端客服路由（customer_service / M5）。

权限：customer_service / trainer / admin 都能访问（per require_cs_or_above）。

- GET    /admin/cs/queue                          待接入会话列表
- POST   /admin/cs/conversations/{id}/claim       客服接入会话
- POST   /admin/cs/conversations/{id}/messages    客服发消息
- POST   /admin/cs/conversations/{id}/close       客服结束会话 → 回退 AI + 插入 CS 气泡
- GET    /admin/cs/conversations/history         我处理过的会话
- GET    /admin/cs/conversations/{id}/stream      SSE 流（推送新消息）

ponytail: SSE 用 1s 轮询 DB 检测新消息，简单可靠；上 Redis pubsub 时再换。
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_cs_or_above
from app.db.models import Conversation, Message, User
from app.db.session import async_session, get_session
from app.schemas.chat import MessageOut

router = APIRouter(dependencies=[Depends(require_cs_or_above)])


# ============ 队列 ============

@router.get("/cs/queue", summary="待接入会话队列")
async def list_queue(
    current_user: Annotated[User, Depends(require_cs_or_above)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    """返回 waiting_human 状态的会话，按更新时间正序（等待最久的排前）。"""
    result = await session.execute(
        select(Conversation)
        .where(Conversation.status == "waiting_human")
        .order_by(Conversation.updated_at.asc())
        .limit(50)
    )
    convs = result.scalars().all()

    out: list[dict] = []
    for c in convs:
        # 取用户昵称
        user_result = await session.execute(select(User).where(User.id == c.user_id))
        u = user_result.scalar_one_or_none()
        # 取最近一条消息作预览
        msg_result = await session.execute(
            select(Message)
            .where(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()
        out.append({
            "conversation_id": c.id,
            "user_id": c.user_id,
            "username": u.username if u else "未知",
            "nickname": u.nickname if u else None,
            "title": c.title,
            "last_message": last_msg.content[:80] if last_msg else None,
            "waiting_since": c.updated_at.isoformat() if c.updated_at else None,
            # 加这个：前端需要知道真实状态，避免在 waiting_human 时误判为 human_active
            "status": c.status,
        })
    return out


# ============ 接入 / 关闭 ============

@router.post("/cs/conversations/{conv_id}/claim", summary="客服接入会话")
async def claim_conversation(
    conv_id: int,
    current_user: Annotated[User, Depends(require_cs_or_above)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    conv = await session.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.status not in ("waiting_human", "human_active"):
        raise HTTPException(status_code=400, detail=f"会话状态 {conv.status} 不可接入")
    if conv.assigned_cs_id and conv.assigned_cs_id != current_user.id:
        # 已被别人接入（极小概率 race condition）
        raise HTTPException(status_code=409, detail="会话已被其他客服接入")

    conv.assigned_cs_id = current_user.id
    conv.status = "human_active"
    conv.conversation_type = "customer_service"
    await session.commit()

    return {
        "conversation_id": conv.id,
        "assigned_cs_id": current_user.id,
        "status": conv.status,
    }


@router.post("/cs/conversations/{conv_id}/close", summary="客服结束会话，回退 AI")
async def close_conversation(
    conv_id: int,
    current_user: Annotated[User, Depends(require_cs_or_above)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """结束本次客服服务：插入一条 CS 气泡消息 + 状态回到 ai_active。
    assigned_cs_id 保留，用于历史归属追踪（前端 /history 用它筛"我处理过的"）。
    用户在同会话继续说"转人工"即可再次回到人工态（transfer_to_human 幂等）。
    """
    conv = await session.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.assigned_cs_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权结束此会话")

    # 1) 插入"客服结束"消息（sender_type=customer_service → 前端渲染为绿色气泡）
    msg = Message(
        conversation_id=conv.id,
        sender_type="customer_service",
        sender_id=current_user.id,
        content="本次客服服务已结束，后续将由 AI 教练继续为你服务。如需再次接入客服，请说「转人工」。",
    )
    session.add(msg)

    # 2) 状态回到 ai_active，保留 assigned_cs_id 给历史查询
    conv.status = "ai_active"
    conv.conversation_type = "ai"

    await session.commit()
    await session.refresh(msg)
    return {
        "conversation_id": conv.id,
        "status": conv.status,
        "ended_message_id": msg.id,
    }


@router.get("/cs/conversations/history", summary="我处理过的会话历史")
async def list_my_history(
    current_user: Annotated[User, Depends(require_cs_or_above)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """返回 assigned_cs_id = 当前用户 的会话（含全部状态）；
    admin 看所有会话。按 updated_at desc 排序。
    """
    stmt = (
        select(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(limit).offset(offset)
    )
    if current_user.role != "admin":
        stmt = stmt.where(Conversation.assigned_cs_id == current_user.id)
    convs = (await session.execute(stmt)).scalars().all()

    out: list[dict] = []
    for c in convs:
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
            "type": c.conversation_type,
            "last_message": last_msg.content[:80] if last_msg else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return out


# ============ 客服发消息 / 读消息 ============

@router.post(
    "/cs/conversations/{conv_id}/messages",
    response_model=MessageOut,
    summary="客服发送消息",
)
async def send_cs_message(
    conv_id: int,
    body: dict,
    current_user: Annotated[User, Depends(require_cs_or_above)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageOut:
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    if len(content) > 4000:
        raise HTTPException(status_code=400, detail="内容过长")

    conv = await session.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.assigned_cs_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="未接入此会话，无法发消息")
    if conv.status != "human_active":
        raise HTTPException(status_code=400, detail="会话不在人工服务状态")

    msg = Message(
        conversation_id=conv.id,
        sender_type="customer_service",
        sender_id=current_user.id,
        content=content,
        extra={"cs_nickname": current_user.nickname or current_user.username},
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return MessageOut.model_validate(msg)


@router.get(
    "/cs/conversations/{conv_id}/messages",
    response_model=list[MessageOut],
    summary="拉取会话消息历史（给 B 端）",
)
async def list_cs_messages(
    conv_id: int,
    current_user: Annotated[User, Depends(require_cs_or_above)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MessageOut]:
    conv = await session.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    return [MessageOut.model_validate(m) for m in result.scalars().all()]


@router.delete(
    "/cs/conversations/{conv_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除会话（admin 全部；CS 仅自己 assigned_cs_id 的）",
)
async def delete_cs_conversation(
    conv_id: int,
    current_user: Annotated[User, Depends(require_cs_or_above)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """删除会话及其所有消息。
    - admin 可删任何会话
    - CS / trainer 只能删 assigned_cs_id == 自己.id 的会话
    """
    conv = await session.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if current_user.role != "admin" and conv.assigned_cs_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此会话")

    # 先删消息（messages 表对 conversations 没有 ondelete cascade，保险做法）
    msgs = await session.execute(select(Message).where(Message.conversation_id == conv_id))
    for m in msgs.scalars().all():
        await session.delete(m)
    await session.delete(conv)
    await session.commit()
    return None


# ============ SSE：推送新消息 ============

@router.get("/cs/conversations/{conv_id}/stream", summary="SSE 推送会话新消息")
async def stream_messages(
    conv_id: int,
    current_user: Annotated[User, Depends(require_cs_or_above)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventSourceResponse:
    """每 1 秒查一次 DB，把自 last_id 以来新出现的 message 推给前端。

    ponytail: 用轮询而非 pub/sub，避免引入 Redis。1,000 并发时 DB 压力可控；
    后续切换：ConversationStreamNotifier + Redis Streams。
    """
    conv = await session.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 初始 last_id = 当前最新消息 id
    last_id_result = await session.execute(
        select(Message.id)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.id.desc())
        .limit(1)
    )
    last_id = last_id_result.scalar() or 0

    async def event_gen() -> AsyncIterator[dict]:
        nonlocal last_id
        # 第一次立刻发当前状态
        try:
            async with async_session() as s:
                cv = await s.get(Conversation, conv_id)
                if cv:
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "status",
                                "status": cv.status,
                                "assigned_cs_id": cv.assigned_cs_id,
                            },
                            ensure_ascii=False,
                        ),
                    }
        except Exception as e:
            logger.warning("SSE 初始状态失败：{}", e)

        while True:
            try:
                async with async_session() as s:
                    # 新消息
                    new_msgs = await s.execute(
                        select(Message)
                        .where(
                            Message.conversation_id == conv_id,
                            Message.id > last_id,
                        )
                        .order_by(Message.id.asc())
                    )
                    msgs = new_msgs.scalars().all()
                    for m in msgs:
                        last_id = max(last_id, m.id)
                        yield {
                            "event": "message",
                            "data": json.dumps(
                                {
                                    "type": "message",
                                    "message": {
                                        "id": m.id,
                                        "conversation_id": m.conversation_id,
                                        "sender_type": m.sender_type,
                                        "sender_id": m.sender_id,
                                        "content": m.content,
                                        "extra": m.extra or {},
                                        "created_at": m.created_at.isoformat() if m.created_at else None,
                                    },
                                },
                                ensure_ascii=False,
                            ),
                        }

                    # 状态变化
                    cv = await s.get(Conversation, conv_id)
                    if cv:
                        # ponytail: 1s 推一次当前状态，前端做对比；
                        # close 改为 ai_active 后这里不再 return，SSE 继续由前端断开时收尾。
                        yield {
                            "event": "message",
                            "data": json.dumps(
                                {
                                    "type": "status",
                                    "status": cv.status,
                                    "assigned_cs_id": cv.assigned_cs_id,
                                },
                                ensure_ascii=False,
                            ),
                        }
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("SSE 轮询失败：{}", e)

            await asyncio.sleep(1)

    return EventSourceResponse(event_gen())
