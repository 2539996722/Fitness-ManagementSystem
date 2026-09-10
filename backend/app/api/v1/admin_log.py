"""B 端操作日志路由（M9）。

- GET    /admin/operation-logs             列出全部日志（支持筛选 + 分页）
- GET    /admin/operation-logs/actions     distinct action + count（用于筛选下拉）
- GET    /admin/operation-logs/target-types distinct target_type + count
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import require_admin
from app.db.models import OperationLog, User
from app.db.session import get_session
from app.schemas.operation_log import (
    ActionOption,
    OperationLogListOut,
    OperationLogOut,
    TargetTypeOption,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get(
    "/operation-logs",
    response_model=OperationLogListOut,
    summary="列出全部操作日志",
)
async def list_operation_logs(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    action: str | None = Query(None, description="按 action 精确匹配"),
    target_type: str | None = Query(None, description="按 target_type 精确匹配"),
    operator_id: int | None = Query(None),
    keyword: str | None = Query(None, description="按 summary 模糊匹配"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> OperationLogListOut:
    """列出操作日志，按 created_at DESC 排序。"""
    stmt = select(OperationLog)

    if action:
        stmt = stmt.where(OperationLog.action == action)
    if target_type:
        stmt = stmt.where(OperationLog.target_type == target_type)
    if operator_id is not None:
        stmt = stmt.where(OperationLog.operator_id == operator_id)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(OperationLog.summary.ilike(like))
    if date_from:
        stmt = stmt.where(OperationLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(OperationLog.created_at <= date_to)

    # total（同一条件）
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    # 分页
    stmt = stmt.order_by(OperationLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()

    items = [
        OperationLogOut(
            id=r.id,
            operator_id=r.operator_id,
            operator_name=r.operator_name,
            operator_role=r.operator_role,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            summary=r.summary,
            details=r.details,
            ip=r.ip,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return OperationLogListOut(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/operation-logs/actions",
    response_model=list[ActionOption],
    summary="操作动作下拉项（distinct + count）",
)
async def list_actions(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ActionOption]:
    """供前端筛选下拉：所有出现过的 action 及其日志数。"""
    rows = (await session.execute(
        select(OperationLog.action, func.count().label("c"))
        .group_by(OperationLog.action)
        .order_by(func.count().desc())
    )).all()
    return [ActionOption(action=r[0], count=r[1]) for r in rows]


@router.get(
    "/operation-logs/target-types",
    response_model=list[TargetTypeOption],
    summary="对象类型下拉项（distinct + count）",
)
async def list_target_types(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TargetTypeOption]:
    rows = (await session.execute(
        select(OperationLog.target_type, func.count().label("c"))
        .where(OperationLog.target_type.is_not(None))
        .group_by(OperationLog.target_type)
        .order_by(func.count().desc())
    )).all()
    return [TargetTypeOption(target_type=r[0], count=r[1]) for r in rows]