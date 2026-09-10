"""B 端链路追踪路由（M10+）。

- GET /admin/traces                按 request_id 聚合的轨迹列表（支持筛选 + 分页）
- GET /admin/traces/{request_id}   单次请求的完整 span 时间线
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.models import TraceSpan, User
from app.db.session import get_session
from app.schemas.trace import (
    TraceDetailOut,
    TraceListItemOut,
    TraceListOut,
    TraceSpanOut,
)

router = APIRouter()


@router.get(
    "/traces",
    response_model=TraceListOut,
    summary="列出按 request_id 聚合的链路轨迹",
)
async def list_traces(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    request_id: str | None = Query(None, description="按 request_id 精确匹配"),
    user_id: int | None = Query(None),
    intent: str | None = Query(None, description="qa / plan / substitute / diet"),
    status: str | None = Query(None, description="success / error"),
    days: int = Query(7, ge=1, le=90, description="仅看最近 N 天"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> TraceListOut:
    """按 request_id GROUP BY，返回每次请求的聚合摘要。"""
    since = datetime.utcnow() - timedelta(days=days)

    # 聚合列：每条请求挑一个代表 intent / user_id / conversation_id（同一 request 内一致）
    span_count = func.count(TraceSpan.id).label("span_count")
    total_latency = func.sum(TraceSpan.latency_ms).label("total_latency")
    total_tokens = func.sum(TraceSpan.total_tokens).label("total_tokens")
    err_count = func.sum(
        func.if_(TraceSpan.status != "success", 1, 0)
    ).label("err_count")

    base = (
        select(
            TraceSpan.request_id,
            TraceSpan.conversation_id,
            TraceSpan.user_id,
            TraceSpan.intent,
            span_count,
            total_latency,
            total_tokens,
            err_count,
            func.min(TraceSpan.created_at).label("started_at"),
            func.max(TraceSpan.created_at).label("last_span_at"),
        )
        .where(TraceSpan.created_at >= since)
        .group_by(
            TraceSpan.request_id,
            TraceSpan.conversation_id,
            TraceSpan.user_id,
            TraceSpan.intent,
        )
    )

    if request_id:
        base = base.having(TraceSpan.request_id == request_id)
    if user_id is not None:
        base = base.having(TraceSpan.user_id == user_id)
    if intent:
        base = base.having(TraceSpan.intent == intent)
    if status:
        # 仅返回整体状态匹配的请求
        base = base.having(
            func.sum(func.if_(TraceSpan.status != "success", 1, 0)) == 0
            if status == "success"
            else func.sum(func.if_(TraceSpan.status != "success", 1, 0)) > 0
        )

    # 总数（独立 request_id 数）
    total_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(total_stmt)).scalar() or 0

    rows = (
        await session.execute(
            base.order_by(func.max(TraceSpan.created_at).desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    # 阶段名：单独查（GROUP_CONCAT 兼容 MySQL，更省一次往返）
    rids = [r[0] for r in rows]
    stage_map: dict[str, list[str]] = {rid: [] for rid in rids}
    if rids:
        srows = (
            await session.execute(
                select(TraceSpan.request_id, TraceSpan.stage)
                .where(TraceSpan.request_id.in_(rids))
                .order_by(TraceSpan.request_id, TraceSpan.stage)
            )
        ).all()
        for rid, stage in srows:
            if stage not in stage_map.setdefault(rid, []):
                stage_map[rid].append(stage)

    items = [
        TraceListItemOut(
            request_id=r.request_id,
            conversation_id=r.conversation_id,
            user_id=r.user_id,
            intent=r.intent,
            status="success" if (r.err_count or 0) == 0 else "error",
            total_latency_ms=int(r.total_latency or 0),
            total_tokens=int(r.total_tokens or 0),
            span_count=int(r.span_count or 0),
            stage_names=stage_map.get(r.request_id, []),
            started_at=r.started_at,
            last_span_at=r.last_span_at,
        )
        for r in rows
    ]
    return TraceListOut(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/traces/{request_id}",
    response_model=TraceDetailOut,
    summary="单次请求的完整 span 时间线",
)
async def get_trace(
    request_id: str,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TraceDetailOut:
    """返回该 request_id 全部 span，按 id ASC。整体 status：全部 success 才 success。"""
    rows = (
        await session.execute(
            select(TraceSpan)
            .where(TraceSpan.request_id == request_id)
            .order_by(TraceSpan.id.asc())
        )
    ).scalars().all()

    spans = [
        TraceSpanOut(
            id=s.id,
            request_id=s.request_id,
            conversation_id=s.conversation_id,
            user_id=s.user_id,
            stage=s.stage,
            intent=s.intent,
            status=s.status,
            latency_ms=s.latency_ms,
            prompt_tokens=s.prompt_tokens,
            completion_tokens=s.completion_tokens,
            total_tokens=s.total_tokens,
            input_preview=s.input_preview,
            output_preview=s.output_preview,
            meta=s.meta,
            error_message=s.error_message,
            created_at=s.created_at,
        )
        for s in rows
    ]
    total_latency = sum(s.latency_ms for s in rows)
    total_tokens = sum(s.total_tokens for s in rows)
    overall = "success" if rows and all(s.status == "success" for s in rows) else (
        "error" if rows else "success"
    )
    return TraceDetailOut(
        request_id=request_id,
        spans=spans,
        total_latency_ms=total_latency,
        total_tokens=total_tokens,
        status=overall,
    )