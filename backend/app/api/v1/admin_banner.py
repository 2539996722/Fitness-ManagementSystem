"""公告 Banner 路由（M9）。

- /admin/banners*       admin CRUD
- /banners/active       C 端公开读取（仅返回启用 + 在生效区间内的 Banner）
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.models import Banner, User
from app.db.session import get_session
from app.schemas.banner import BannerCreate, BannerOut, BannerUpdate
from app.services.operation_log import record as log_operation


def _utcnow_naive() -> datetime:
    """与 MySQL DATETIME 列匹配的 UTC now（无 tzinfo）。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============ C 端公开接口 ============

public_router = APIRouter(prefix="/banners", tags=["公告"])


@public_router.get("/active", response_model=list[BannerOut], summary="C 端首页：当前生效的 Banner 列表")
async def list_active_banners(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Banner]:
    """返回 is_active=True 且当前时间在 [starts_at, ends_at] 内的 Banner，按 sort_order asc, id desc。"""
    now = _utcnow_naive()
    stmt = (
        select(Banner)
        .where(Banner.is_active.is_(True))
        .order_by(Banner.sort_order.asc(), Banner.id.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    # 在应用层做时间区间过滤（避免 SQL 写一堆 OR NULL 条件）
    out = []
    for b in rows:
        if b.starts_at is not None and b.starts_at > now:
            continue
        if b.ends_at is not None and b.ends_at < now:
            continue
        out.append(b)
    return out


# ============ B 端 CRUD ============

admin_router = APIRouter(
    prefix="/admin/banners",
    tags=["公告管理"],
    dependencies=[Depends(require_role("admin"))],
)


@admin_router.get("", response_model=list[BannerOut], summary="列出全部 Banner")
async def list_banners(
    session: Annotated[AsyncSession, Depends(get_session)],
    include_inactive: bool = True,
) -> list[Banner]:
    """列出全部 Banner（默认含未启用），按 sort_order asc, id desc。"""
    stmt = select(Banner).order_by(Banner.sort_order.asc(), Banner.id.desc())
    if not include_inactive:
        stmt = stmt.where(Banner.is_active.is_(True))
    return (await session.execute(stmt)).scalars().all()


@admin_router.post(
    "",
    response_model=BannerOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建 Banner",
)
async def create_banner(
    body: BannerCreate,
    admin: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Banner:
    """新建公告 Banner。"""
    # 时间区间合法性校验
    if body.starts_at and body.ends_at and body.ends_at < body.starts_at:
        raise HTTPException(status_code=400, detail="失效时间不能早于生效时间")

    banner = Banner(**body.model_dump())
    session.add(banner)
    await session.commit()
    await session.refresh(banner)

    await log_operation(
        session=session,
        operator=admin,
        action="create_banner",
        target_type="banner",
        target_id=banner.id,
        summary=f"新建 Banner「{banner.title}」（{banner.id}）",
        details={"title": banner.title, "is_active": banner.is_active, "sort_order": banner.sort_order},
    )
    return banner


@admin_router.patch(
    "/{banner_id}",
    response_model=BannerOut,
    summary="更新 Banner",
)
async def update_banner(
    banner_id: int,
    body: BannerUpdate,
    admin: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Banner:
    """部分更新。"""
    banner = (await session.execute(select(Banner).where(Banner.id == banner_id))).scalar_one_or_none()
    if banner is None:
        raise HTTPException(status_code=404, detail="Banner 不存在")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return banner

    # 时间区间校验
    new_start = updates.get("starts_at", banner.starts_at)
    new_end = updates.get("ends_at", banner.ends_at)
    if new_start and new_end and new_end < new_start:
        raise HTTPException(status_code=400, detail="失效时间不能早于生效时间")

    old_title = banner.title
    for k, v in updates.items():
        setattr(banner, k, v)
    await session.commit()
    await session.refresh(banner)

    await log_operation(
        session=session,
        operator=admin,
        action="update_banner",
        target_type="banner",
        target_id=banner.id,
        summary=f"更新 Banner「{old_title}」→「{banner.title}」（{banner.id}）",
        details={"changed_fields": list(updates.keys())},
    )
    return banner


@admin_router.delete(
    "/{banner_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 Banner",
)
async def delete_banner(
    banner_id: int,
    admin: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    banner = (await session.execute(select(Banner).where(Banner.id == banner_id))).scalar_one_or_none()
    if banner is None:
        raise HTTPException(status_code=404, detail="Banner 不存在")

    title = banner.title
    await session.delete(banner)
    await session.commit()

    await log_operation(
        session=session,
        operator=admin,
        action="delete_banner",
        target_type="banner",
        target_id=banner_id,
        summary=f"删除 Banner「{title}」（{banner_id}）",
    )