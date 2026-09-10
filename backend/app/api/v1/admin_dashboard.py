"""B 端数据看板路由（M6, PRD §5.2.3）。

- GET /api/v1/admin/dashboard/overview             6 张 KPI 卡
- GET /api/v1/admin/dashboard/user-trend?days=30   每日新增用户（折线）
- GET /api/v1/admin/dashboard/goal-distribution    计划目标分布（饼）
- GET /api/v1/admin/dashboard/body-part-top        部位偏好 TOP10（柱）
- GET /api/v1/admin/dashboard/intent-distribution  AI 意图分布（饼）
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role  # ponytail: 看板对 admin+trainer 都开放，如需细分再细分
from app.db.models import (
    AiCallLog,
    Conversation,
    Exercise,
    Message,
    Plan,
    TrainingRecord,
    User,
)
from app.db.session import get_session
from app.schemas.admin_dashboard import (
    DistributionResponse,
    MetricsOut,
    NamedCount,
    TrendPoint,
    TrendResponse,
)

router = APIRouter()


def _today_range() -> tuple[datetime, datetime]:
    """返回 [今天 00:00, 明天 00:00) 的 UTC 区间。"""
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day)
    return start, start + timedelta(days=1)


# ============ KPI 总览 ============

@router.get("/dashboard/overview", response_model=MetricsOut, summary="KPI 总览")
async def dashboard_overview(
    _user: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MetricsOut:
    today_start, tomorrow_start = _today_range()

    total_users = (
        await session.execute(select(func.count(User.id)))
    ).scalar() or 0

    today_new = (
        await session.execute(
            select(func.count(User.id)).where(
                User.created_at >= today_start, User.created_at < tomorrow_start
            )
        )
    ).scalar() or 0

    # DAU：按 last_login_at 当日去重计数（最近一次登录落在今天的用户）
    dau = (
        await session.execute(
            select(func.count(func.distinct(User.id))).where(
                User.last_login_at >= today_start,
                User.last_login_at < tomorrow_start,
            )
        )
    ).scalar() or 0

    # AI 对话总数：sender_type='user' 的消息条数（每条 = 一轮问答）
    ai_total = (
        await session.execute(
            select(func.count(Message.id)).where(Message.sender_type == "user")
        )
    ).scalar() or 0

    ai_today = (
        await session.execute(
            select(func.count(Message.id)).where(
                Message.sender_type == "user",
                Message.created_at >= today_start,
                Message.created_at < tomorrow_start,
            )
        )
    ).scalar() or 0

    # 人工会话数：conversation_type IN (customer_service, trainer)
    human_total = (
        await session.execute(
            select(func.count(Conversation.id)).where(
                Conversation.conversation_type.in_(["customer_service", "trainer"])
            )
        )
    ).scalar() or 0

    human_pending = (
        await session.execute(
            select(func.count(Conversation.id)).where(
                Conversation.status == "waiting_human"
            )
        )
    ).scalar() or 0

    return MetricsOut(
        total_users=total_users,
        today_new_users=today_new,
        dau=dau,
        ai_total=ai_total,
        ai_today=ai_today,
        human_total=human_total,
        human_pending=human_pending,
    )


# ============ 新增用户趋势 ============

@router.get("/dashboard/user-trend", response_model=TrendResponse, summary="N 天新增用户趋势")
async def user_trend(
    _user: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: int = Query(30, ge=1, le=90),
) -> TrendResponse:
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=days - 1)
    start_dt = datetime(start_date.year, start_date.month, start_date.day)

    # 用 MySQL 的 DATE() 按天聚合
    day_col = func.date(User.created_at).label("d")
    rows = (
        await session.execute(
            select(day_col, func.count(User.id))
            .where(User.created_at >= start_dt)
            .group_by("d")
            .order_by("d")
        )
    ).all()

    bucket = {d.isoformat(): c for d, c in rows}
    points: list[TrendPoint] = []
    for i in range(days):
        d = (start_date + timedelta(days=i)).isoformat()
        points.append(TrendPoint(date=d, count=bucket.get(d, 0)))
    return TrendResponse(points=points)


# ============ 目标分布 ============

GOAL_LABELS = {
    "muscle_gain": "增肌",
    "fat_loss": "减脂",
    "body_shape": "塑形",
    "endurance": "体能",
}


@router.get("/dashboard/goal-distribution", response_model=DistributionResponse, summary="计划目标分布")
async def goal_distribution(
    _user: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DistributionResponse:
    rows = (
        await session.execute(
            select(Plan.goal, func.count(Plan.id)).group_by(Plan.goal)
        )
    ).all()
    items = [
        NamedCount(name=GOAL_LABELS.get(g, g) or g or "未知", count=c)
        for g, c in rows
    ]
    items.sort(key=lambda x: x.count, reverse=True)
    return DistributionResponse(items=items)


# ============ 部位 TOP10 ============

@router.get("/dashboard/body-part-top", response_model=DistributionResponse, summary="部位偏好 TOP10")
async def body_part_top(
    _user: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DistributionResponse:
    rows = (
        await session.execute(
            select(Exercise.body_part, func.count(TrainingRecord.id))
            .join(TrainingRecord, TrainingRecord.exercise_id == Exercise.id)
            .group_by(Exercise.body_part)
            .order_by(func.count(TrainingRecord.id).desc())
            .limit(10)
        )
    ).all()
    items = [NamedCount(name=bp or "未知", count=c) for bp, c in rows]
    return DistributionResponse(items=items)


# ============ 意图分布 ============

INTENT_LABELS = {
    "qa": "健身问答",
    "plan": "计划生成",
    "substitute": "动作替代",
    "diet": "饮食建议",
}


@router.get("/dashboard/intent-distribution", response_model=DistributionResponse, summary="AI 场景调用分布")
async def intent_distribution(
    _user: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DistributionResponse:
    # 只统计 AI 已经识别的 intent（排除 NULL）
    rows = (
        await session.execute(
            select(Message.intent, func.count(Message.id))
            .where(Message.intent.is_not(None))
            .group_by(Message.intent)
            .order_by(func.count(Message.id).desc())
        )
    ).all()
    items = [
        NamedCount(name=INTENT_LABELS.get(i, i) or i, count=c)
        for i, c in rows
    ]
    return DistributionResponse(items=items)


# ============ AI 用量趋势（按日聚合 token / cost） ============


@router.get("/dashboard/ai-cost", summary="N 天 AI 用量趋势（按日聚合）")
async def ai_cost_trend(
    _user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: int = Query(7, ge=1, le=90),
) -> dict:
    """返回 {days, points: [{date, calls, total_tokens, cost_cny, by_intent}], total: {...}}。

    by_intent: {intent_name: tokens} 累计（不分日）。
    """
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=days - 1)
    start_dt = datetime(start_date.year, start_date.month, start_date.day)

    day_col = func.date(AiCallLog.created_at).label("d")
    rows = (
        await session.execute(
            select(
                day_col,
                AiCallLog.intent,
                func.count(AiCallLog.id).label("calls"),
                func.coalesce(func.sum(AiCallLog.total_tokens), 0).label("toks"),
                func.coalesce(func.sum(AiCallLog.cost_cny), 0).label("cost"),
            )
            .where(AiCallLog.created_at >= start_dt)
            .group_by("d", AiCallLog.intent)
            .order_by("d")
        )
    ).all()

    bucket: dict[str, dict] = {}
    for d, intent, calls, toks, cost in rows:
        d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        slot = bucket.setdefault(
            d_str,
            {"date": d_str, "calls": 0, "total_tokens": 0, "cost_cny": 0.0, "by_intent_tokens": {}},
        )
        slot["calls"] += int(calls or 0)
        slot["total_tokens"] += int(toks or 0)
        slot["cost_cny"] = round(slot["cost_cny"] + float(cost or 0), 6)
        if intent:
            slot["by_intent_tokens"][intent] = slot["by_intent_tokens"].get(intent, 0) + int(toks or 0)

    # 补齐缺失日期
    points: list[dict] = []
    for i in range(days):
        d_str = (start_date + timedelta(days=i)).isoformat()
        slot = bucket.get(d_str) or {
            "date": d_str, "calls": 0, "total_tokens": 0, "cost_cny": 0.0, "by_intent_tokens": {},
        }
        points.append(slot)

    total_calls = sum(p["calls"] for p in points)
    total_tokens = sum(p["total_tokens"] for p in points)
    total_cost = round(sum(p["cost_cny"] for p in points), 6)
    return {
        "days": days,
        "points": points,
        "total": {"calls": total_calls, "total_tokens": total_tokens, "cost_cny": total_cost},
    }
