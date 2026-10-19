"""B 端会员管理路由（M6, PRD §5.2.1）。

- GET    /api/v1/admin/members                  列表（筛选 + 分页）
- POST   /api/v1/admin/members                  新建用户（任意角色，留空密码自动生成）
- GET    /api/v1/admin/members/{id}             详情（含最近计划 / 会话）
- PATCH  /api/v1/admin/members/{id}/status      封禁 / 解封（带原因）
- PATCH  /api/v1/admin/members/{id}/remark      修改管理员备注
- POST   /api/v1/admin/members/{id}/reset-password   重置密码（返回新密码）
- GET    /api/v1/admin/members/export           导出 CSV（按当前筛选条件）
"""

import csv
import io
import re
import secrets
import string
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role  # ponytail: 会员管理对 admin+trainer 都开放
from app.core.security import hash_password
from app.db.models import Conversation, Message, Plan, User
from app.db.session import get_session
from app.schemas.admin_member import (
    ConversationBrief,
    PlanBrief,
    UserCreate,
    UserCreateOut,
    UserDetail,
    UserListItem,
    UserListResponse,
    UserRemarkUpdate,
    UserResetPasswordOut,
    UserStatusUpdate,
)
from app.services.operation_log import record as log_operation

router = APIRouter()

ROLE_LABELS = {
    "user": "普通用户",
    "trainer": "教练",
    "admin": "管理员",
}

# 用户名格式：3-32 字符，字母/数字/下划线/中文（与 trainer.py 保持一致）
USERNAME_PATTERN = re.compile(r"^[\w一-龥]{3,32}$", re.UNICODE)
# 密码格式：8-20 字符，必须含字母 + 数字
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,20}$")


# ============ 工具 ============

def _gen_password(length: int = 10) -> str:
    """生成管理员下发的随机密码（大小写 + 数字）。"""
    alphabet = string.ascii_letters + string.digits
    # 保证至少一个大写 + 一个数字
    pwd = [secrets.choice(string.ascii_uppercase), secrets.choice(string.digits)]
    pwd += [secrets.choice(alphabet) for _ in range(length - 2)]
    secrets.SystemRandom().shuffle(pwd)
    return "".join(pwd)


async def _counts_subqueries(session: AsyncSession) -> tuple[Any, Any]:
    """返回 (plan_count_subq, ai_msg_count_subq)，按 user_id 聚合。"""
    plan_count = (
        select(Plan.user_id, func.count(Plan.id).label("c"))
        .group_by(Plan.user_id)
        .subquery()
    )
    # AI 对话数 = 该用户作为 sender_type='user' 发送的消息条数（每条 = 一轮 AI 问答）
    ai_msg_count = (
        select(Message.sender_id, func.count(Message.id).label("c"))
        .where(Message.sender_type == "user")
        .group_by(Message.sender_id)
        .subquery()
    )
    return plan_count, ai_msg_count


# ============ 列表 ============

@router.get("/members", response_model=UserListResponse, summary="会员列表")
async def list_members(
    _user: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    keyword: str | None = Query(None, description="用户名/昵称/ID 模糊匹配"),
    role: str | None = Query(None, description="user / trainer / admin"),
    status_: int | None = Query(None, alias="status", ge=0, le=1, description="0 正常 1 封禁"),
    include_deleted: bool = Query(False, description="是否包含已软删用户（默认过滤掉）"),
    date_from: datetime | None = Query(None, description="注册起始时间"),
    date_to: datetime | None = Query(None, description="注册截止时间"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> UserListResponse:
    plan_sq, ai_sq = await _counts_subqueries(session)

    base = (
        select(
            User,
            func.coalesce(plan_sq.c.c, 0).label("plan_count"),
            func.coalesce(ai_sq.c.c, 0).label("ai_msg_count"),
        )
        .outerjoin(plan_sq, plan_sq.c.user_id == User.id)
        .outerjoin(ai_sq, ai_sq.c.sender_id == User.id)
    )
    count_base = select(func.count(User.id))

    # ponytail: 默认过滤已软删用户；include_deleted=true 才看得到（含审计追溯用）
    if not include_deleted:
        base = base.where(User.is_deleted.is_(False))
        count_base = count_base.where(User.is_deleted.is_(False))

    if keyword:
        # 纯数字 → 走 ID 精确匹配；否则 → username/nickname LIKE
        if keyword.isdigit():
            base = base.where(User.id == int(keyword))
            count_base = count_base.where(User.id == int(keyword))
        else:
            like = f"%{keyword}%"
            cond = or_(User.username.like(like), User.nickname.like(like))
            base = base.where(cond)
            count_base = count_base.where(cond)
    if role:
        base = base.where(User.role == role)
        count_base = count_base.where(User.role == role)
    if status_ is not None:
        base = base.where(User.status == status_)
        count_base = count_base.where(User.status == status_)
    if date_from:
        base = base.where(User.created_at >= date_from)
        count_base = count_base.where(User.created_at >= date_from)
    if date_to:
        base = base.where(User.created_at <= date_to)
        count_base = count_base.where(User.created_at <= date_to)

    total = (await session.execute(count_base)).scalar() or 0

    rows = (
        await session.execute(
            base.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size + 1)
        )
    ).all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]

    items = [
        UserListItem(
            id=u.id,
            username=u.username,
            nickname=u.nickname,
            role=u.role,
            status=u.status,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            remark=u.remark,
            plan_count=pc,
            ai_msg_count=ac,
        )
        for u, pc, ac in rows
    ]
    return UserListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


# ============ 新建用户 ============

@router.post(
    "/members",
    response_model=UserCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建用户（任意角色，留空密码自动生成）",
)
async def create_member(
    body: UserCreate,
    admin: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserCreateOut:
    """admin 可创建任意角色账号；trainer 仅能创建 user（防提权）。"""
    # 角色归一化：customer_service → trainer 迁移已删（M12 #122，DB 字段无此值）
    # trainer 不能创建 admin / trainer 账号（防提权）

    # trainer 不能创建 admin / trainer 账号（防提权）
    if admin.role == "trainer" and body.role in ("admin", "trainer"):
        raise HTTPException(
            status_code=403,
            detail="教练只能创建普通用户账号",
        )
    username = body.username.strip()
    if not USERNAME_PATTERN.match(username):
        raise HTTPException(status_code=400, detail="用户名格式错误（3-32 字符，字母/数字/下划线/中文）")

    # 密码：留空 → 自动生成；非空 → 校验格式
    if body.password:
        if not PASSWORD_PATTERN.match(body.password):
            raise HTTPException(status_code=400, detail="密码格式错误（8-20 字符，必须含字母和数字）")
        initial_pwd = body.password
    else:
        initial_pwd = _gen_password()

    # 用户名唯一性
    existing = await session.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="用户名已被占用")

    user = User(
        username=username,
        password_hash=hash_password(initial_pwd),
        nickname=body.nickname or username,
        role=body.role,
        status=0,
        remark=body.remark,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="用户名已被占用")
    await session.refresh(user)

    logger.warning(
        "admin={} 创建用户 id={} username={} role={}",
        admin.id, user.id, user.username, user.role,
    )
    await log_operation(
        session=session,
        operator=admin,
        action="create_user",
        target_type="user",
        target_id=user.id,
        summary=f"创建用户 {user.username}（角色：{user.role}）",
        details={"role": user.role, "username": user.username, "nickname": user.nickname},
    )
    item = UserListItem(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        remark=user.remark,
        plan_count=0,
        ai_msg_count=0,
    )
    return UserCreateOut(user=item, initial_password=initial_pwd)


# ============ 导出 CSV（必须放在 /{user_id} 之前，避免 export 被当 ID） ============

@router.get("/members/export", summary="导出会员 CSV")
async def export_members_csv(
    operator: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    keyword: str | None = Query(None),
    role: str | None = Query(None),
    status_: int | None = Query(None, alias="status", ge=0, le=1),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
) -> StreamingResponse:
    plan_sq, ai_sq = await _counts_subqueries(session)
    stmt = (
        select(User, func.coalesce(plan_sq.c.c, 0), func.coalesce(ai_sq.c.c, 0))
        .outerjoin(plan_sq, plan_sq.c.user_id == User.id)
        .outerjoin(ai_sq, ai_sq.c.sender_id == User.id)
    )
    if keyword:
        if keyword.isdigit():
            stmt = stmt.where(User.id == int(keyword))
        else:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(User.username.like(like), User.nickname.like(like)))
    if role:
        stmt = stmt.where(User.role == role)
    if status_ is not None:
        stmt = stmt.where(User.status == status_)
    if date_from:
        stmt = stmt.where(User.created_at >= date_from)
    if date_to:
        stmt = stmt.where(User.created_at <= date_to)
    stmt = stmt.order_by(User.created_at.desc()).limit(10000)

    rows = (await session.execute(stmt)).all()

    def _gen() -> Any:
        buf = io.StringIO()
        # 加 BOM 让 Excel 正确识别 UTF-8
        buf.write("﻿")
        w = csv.writer(buf)
        w.writerow(
            [
                "用户ID", "用户名", "昵称", "角色", "状态",
                "注册时间", "最近登录", "计划数", "AI对话数", "备注",
            ]
        )
        for u, pc, ac in rows:
            w.writerow(
                [
                    u.id,
                    u.username,
                    u.nickname or "",
                    ROLE_LABELS.get(u.role, u.role),
                    "封禁" if u.status == 1 else "正常",
                    u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "",
                    u.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if u.last_login_at else "",
                    pc,
                    ac,
                    (u.remark or "").replace("\n", " "),
                ]
            )
        yield buf.getvalue()

    fname = f"members_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    logger.info("导出会员 CSV：admin={} rows={}", operator.id, len(rows))
    return StreamingResponse(
        _gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ============ 详情 ============

@router.get("/members/{user_id}", response_model=UserDetail, summary="会员详情")
async def get_member(
    user_id: int,
    _user: Annotated[User, Depends(require_role("admin", "trainer"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserDetail:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")

    plan_count = (
        await session.execute(
            select(func.count(Plan.id)).where(Plan.user_id == user_id)
        )
    ).scalar() or 0
    ai_msg_count = (
        await session.execute(
            select(func.count(Message.id)).where(
                Message.sender_type == "user",
                Message.conversation_id.in_(
                    select(Conversation.id).where(Conversation.user_id == user_id)
                ),
            )
        )
    ).scalar() or 0

    recent_plans = (
        (
            await session.execute(
                select(Plan)
                .where(Plan.user_id == user_id)
                .order_by(Plan.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    recent_convs = (
        (
            await session.execute(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )

    return UserDetail(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        avatar_url=user.avatar_url,
        gender=user.gender,
        age=user.age,
        height_cm=float(user.height_cm) if user.height_cm is not None else None,
        weight_kg=float(user.weight_kg) if user.weight_kg is not None else None,
        role=user.role,
        status=user.status,
        remark=user.remark,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        plan_count=plan_count,
        ai_msg_count=ai_msg_count,
        recent_plans=[PlanBrief.model_validate(p) for p in recent_plans],
        recent_conversations=[ConversationBrief.model_validate(c) for c in recent_convs],
    )


# ============ 封禁 / 解封 ============

@router.patch("/members/{user_id}/status", response_model=UserListItem, summary="封禁/解封")
async def update_member_status(
    user_id: int,
    body: UserStatusUpdate,
    admin: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserListItem:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能操作自己的账号")
    if body.status == 1 and not (body.reason and body.reason.strip()):
        raise HTTPException(status_code=400, detail="封禁时必须填写原因")

    user.status = body.status
    # 封禁原因写到 remark（若用户已有 remark，附加；否则覆盖）
    if body.reason:
        stamp = datetime.utcnow().strftime("%Y-%m-%d")
        tag = f"[{stamp}{'封禁' if body.status == 1 else '解封'}] {body.reason.strip()}"
        user.remark = f"{user.remark}\n{tag}" if user.remark else tag
    await session.commit()

    logger.info("会员 {} 状态 → {}，操作人 admin={}", user.id, body.status, admin.id)
    await log_operation(
        session=session,
        operator=admin,
        action="ban_user" if body.status == 1 else "unban_user",
        target_type="user",
        target_id=user.id,
        summary=("封禁" if body.status == 1 else "解封") + f" {user.username}（{user.id}）",
        details={"new_status": body.status, "reason": body.reason},
    )
    # 返回最新行（plan_count / ai_msg_count 由前端在刷新时拉取，这里给默认值即可）
    return UserListItem(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        remark=user.remark,
        plan_count=0,
        ai_msg_count=0,
    )


# ============ 备注 ============

@router.patch("/members/{user_id}/remark", response_model=UserListItem, summary="修改备注")
async def update_member_remark(
    user_id: int,
    body: UserRemarkUpdate,
    admin: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserListItem:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")

    user.remark = body.remark or None
    await session.commit()
    logger.info("会员 {} 备注已更新：admin={}", user.id, admin.id)
    await log_operation(
        session=session,
        operator=admin,
        action="update_user_remark",
        target_type="user",
        target_id=user.id,
        summary=f"更新 {user.username}（{user.id}）备注",
        details={"remark": user.remark},
    )
    return UserListItem(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        remark=user.remark,
        plan_count=0,
        ai_msg_count=0,
    )


# ============ 重置密码 ============

@router.post(
    "/members/{user_id}/reset-password",
    response_model=UserResetPasswordOut,
    summary="重置密码（返回新密码）",
)
async def reset_member_password(
    user_id: int,
    admin: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResetPasswordOut:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能重置自己的密码（请用修改密码功能）")

    new_pwd = _gen_password()
    user.password_hash = hash_password(new_pwd)
    user.failed_login_count = 0
    user.locked_until = None
    await session.commit()
    logger.warning("会员 {} 密码已被 admin={} 重置", user.id, admin.id)
    await log_operation(
        session=session,
        operator=admin,
        action="reset_user_password",
        target_type="user",
        target_id=user.id,
        summary=f"重置 {user.username}（{user.id}）密码",
        details={"new_password_returned": True},
    )
    return UserResetPasswordOut(user_id=user.id, username=user.username, new_password=new_pwd)


# ============ 软删除 ============

@router.delete(
    "/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="软删除会员（admin 限定）",
)
async def delete_member(
    user_id: int,
    admin: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    reason: str | None = Query(None, description="操作说明（写入日志）", max_length=200),
) -> None:
    """软删除会员：
    - 置 is_deleted=True、status=1（封禁）、password_hash 置空
    - 用户名加 `del_<id>_` 前缀，释放 unique 约束便于同名重建
    - 不能删除自己、不能删除其他 admin（防止误删全部管理员）
    - 已在操作日志记录，可通过 operation_logs 追溯
    """
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None or user.is_deleted:
        raise HTTPException(status_code=404, detail="会员不存在或已删除")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    if user.role == "admin":
        # ponytail: 至少保留一个 admin 在 DB；防止误操作清空所有管理员
        admin_count = (
            await session.execute(
                select(func.count(User.id)).where(
                    User.role == "admin", User.is_deleted.is_(False)
                )
            )
        ).scalar() or 0
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="系统内只剩最后一个管理员，不能删除",
            )

    original_username = user.username
    original_nickname = user.nickname
    user.is_deleted = True
    user.status = 1  # 同时设为封禁态，登录拦截多重保险
    user.password_hash = ""  # 凭据失效
    user.username = f"del_{user.id}_{original_username}"
    if user.nickname:
        user.nickname = f"[已删除]{original_nickname}"
    stamp = datetime.utcnow().strftime("%Y-%m-%d")
    tag = f"[{stamp}已删除] 操作人 admin={admin.id}"
    user.remark = f"{user.remark}\n{tag}" if user.remark else tag
    await session.commit()

    logger.warning("admin={} 软删除会员 {} ({} 原 username={})", admin.id, user.id, user.role, original_username)
    await log_operation(
        session=session,
        operator=admin,
        action="delete_user",
        target_type="user",
        target_id=user.id,
        summary=f"软删除会员「{original_username}」（{user.id}）",
        details={
            "original_username": original_username,
            "original_nickname": original_nickname,
            "role": user.role,
            "reason": reason,
        },
    )
