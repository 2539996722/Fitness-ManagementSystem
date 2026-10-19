"""admin_member.py 单测（mocked AsyncSession）。

覆盖 8 个端点 + 关键业务规则：
- GET    /members                列表（多条件 + 分页 + has_more）
- POST   /members                新建（角色归一化、trainer 防提权、重复、格式校验）
- GET    /members/export         CSV 导出
- GET    /members/{id}           详情（plan_count / ai_msg_count / recent）
- PATCH  /members/{id}/status    封禁/解封（自己、原因、remark append）
- PATCH  /members/{id}/remark    备注修改
- POST   /members/{id}/reset-password  重置密码（自己、清锁定）
- DELETE /members/{id}           软删除（自己、最后一个 admin、已删）

ponytail: Pydantic 校验失败（min_length / Literal role）发生在路由函数前，断言用 ValidationError 而非 HTTPException。
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api.v1.admin_member import (
    _gen_password,
    create_member,
    delete_member,
    export_members_csv,
    get_member,
    list_members,
    reset_member_password,
    update_member_remark,
    update_member_status,
)
from app.schemas.admin_member import UserCreate, UserRemarkUpdate, UserStatusUpdate


# ============ Helpers ============

def _make_user(
    id=1, username="u1", nickname="n1", role="user",
    status=0, is_deleted=False, remark=None,
    created_at=None, last_login_at=None, password_hash="x",
    failed_login_count=0, locked_until=None,
    avatar_url=None, gender=0, age=None, height_cm=None, weight_kg=None,
):
    return SimpleNamespace(
        id=id, username=username, nickname=nickname, role=role,
        status=status, is_deleted=is_deleted, remark=remark,
        password_hash=password_hash, failed_login_count=failed_login_count,
        locked_until=locked_until,
        avatar_url=avatar_url, gender=gender, age=age,
        height_cm=height_cm, weight_kg=weight_kg,
        created_at=created_at or datetime(2024, 1, 1),
        last_login_at=last_login_at,
    )


def _admin(id=99, role="admin"):
    return _make_user(id=id, username=f"admin{id}", role=role, nickname=f"admin{id}")


def _mock_session_scalar(value):
    """session.execute(...).scalar_one_or_none() → value"""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    return m


def _mock_session_scalar_one(value):
    """session.execute(...).scalar() → value"""
    m = MagicMock()
    m.scalar.return_value = value
    return m


def _mock_session_rows(rows):
    """session.execute(...).all() → rows"""
    m = MagicMock()
    m.all.return_value = rows
    return m


def _setup_create_session(existing_user=None):
    """构造 create_member 用的 session：用户查重 + commit/refresh 后 id 填充。

    ponytail: 真实 ORM 在 commit + refresh 后由 DB 填 id/created_at。MagicMock 的
    commit/refresh 是 noop，user 对象不会被自动填值。我们在 refresh 之前手动
    给 user 加 id/created_at/updated_at（模拟 DB autoincrement + DEFAULT NOW()）。
    """
    session = AsyncMock()
    session.execute.return_value = _mock_session_scalar(existing_user)

    def add_then_fill_defaults(obj):
        # 模拟 DB autoincrement + DEFAULT NOW()
        if not getattr(obj, "id", None):
            obj.id = 200
        if not getattr(obj, "created_at", None):
            obj.created_at = datetime(2024, 1, 1)
        if not getattr(obj, "updated_at", None):
            obj.updated_at = datetime(2024, 1, 1)
    session.add.side_effect = add_then_fill_defaults

    # session.refresh(user) 是 await 调用，需要 AsyncMock 走通 + 填字段
    async def refresh_fill(obj):
        if not getattr(obj, "id", None):
            obj.id = 200
        if not getattr(obj, "created_at", None):
            obj.created_at = datetime(2024, 1, 1)
        if not getattr(obj, "updated_at", None):
            obj.updated_at = datetime(2024, 1, 1)
    session.refresh.side_effect = refresh_fill

    # log_operation 内部也会 session.add(operation_log)，需要让该调用 noop
    # （已经走通，但需要确保不会因为没填字段而让 add 抛错——我们的 side_effect 通用）
    return session


# ============ list_members ============

class TestListMembers:
    """GET /members：列表 + 多条件 + has_more。"""

    @pytest.mark.asyncio
    async def test_returns_paginated_list_with_has_more(self):
        u1 = _make_user(id=1)
        u2 = _make_user(id=2)
        session = AsyncMock()
        count_result = _mock_session_scalar_one(100)
        rows_result = _mock_session_rows([(u1, 2, 5), (u2, 1, 3), (_make_user(id=3), 0, 0)])
        session.execute.side_effect = [count_result, rows_result]

        result = await list_members(
            _user=_admin(), session=session,
            keyword=None, role=None, status_=None, include_deleted=False,
            date_from=None, date_to=None, page=1, page_size=2,
        )

        assert result.total == 100
        assert result.page == 1
        assert result.page_size == 2
        assert result.has_more is True  # 返回 3 行 > page_size 2
        assert len(result.items) == 2  # 截断到 page_size
        assert result.items[0].plan_count == 2

    @pytest.mark.asyncio
    async def test_keyword_digit_matches_id(self):
        session = AsyncMock()
        count_result = _mock_session_scalar_one(1)
        u1 = _make_user(id=42)
        rows_result = _mock_session_rows([(u1, 0, 0)])
        session.execute.side_effect = [count_result, rows_result]

        result = await list_members(
            _user=_admin(), session=session,
            keyword="42", role=None, status_=None, include_deleted=False,
            date_from=None, date_to=None, page=1, page_size=20,
        )
        assert result.items[0].id == 42

    @pytest.mark.asyncio
    async def test_include_deleted_true_keeps_soft_deleted(self):
        session = AsyncMock()
        count_result = _mock_session_scalar_one(0)
        rows_result = _mock_session_rows([])
        session.execute.side_effect = [count_result, rows_result]

        result = await list_members(
            _user=_admin(), session=session,
            keyword=None, role=None, status_=None, include_deleted=True,
            date_from=None, date_to=None, page=1, page_size=20,
        )
        assert result.total == 0
        assert result.items == []


# ============ create_member ============

class TestCreateMember:
    """POST /members：新建用户 + 角色归一化 + 权限。"""

    @pytest.mark.asyncio
    async def test_create_user_role_success(self):
        body = UserCreate(username="newuser", password="pass1234", role="user")
        session = _setup_create_session()

        result = await create_member(body=body, admin=_admin(id=99, role="admin"), session=session)

        assert result.user.username == "newuser"
        assert result.user.role == "user"
        assert result.initial_password == "pass1234"
        # session.add 至少被调用一次（User + OperationLog）
        assert session.add.call_count >= 1

    @pytest.mark.asyncio
    async def test_create_trainer_role_as_admin_success(self):
        body = UserCreate(username="newcoach", password="pass1234", role="trainer")
        session = _setup_create_session()

        result = await create_member(body=body, admin=_admin(id=99, role="admin"), session=session)
        assert result.user.role == "trainer"

    @pytest.mark.asyncio
    async def test_user_create_literal_rejects_customer_service(self):
        """UserCreate.role Literal 不含 customer_service → Pydantic 校验直接拒。"""
        with pytest.raises(ValidationError) as exc:
            UserCreate(username="csuser", password="pass1234", role="customer_service")
        assert "customer_service" not in str(exc.value) or "literal_error" in str(exc.value)

    @pytest.mark.asyncio
    async def test_user_create_literal_allows_trainer_and_admin(self):
        """确认 Literal 枚举只含 user/trainer/admin（CS 归一化在 Pydantic 层不可达）。"""
        # 不报错即通过
        UserCreate(username="trainer01", role="trainer")
        UserCreate(username="admin001", role="admin")
        UserCreate(username="user0001", role="user")

    @pytest.mark.asyncio
    async def test_trainer_cannot_create_trainer(self):
        body = UserCreate(username="xcoach", password="pass1234", role="trainer")
        with pytest.raises(HTTPException) as exc:
            await create_member(body=body, admin=_admin(id=99, role="trainer"), session=AsyncMock())
        assert exc.value.status_code == 403
        assert "教练只能创建" in exc.value.detail

    @pytest.mark.asyncio
    async def test_trainer_cannot_create_admin(self):
        body = UserCreate(username="xadmin", password="pass1234", role="admin")
        with pytest.raises(HTTPException) as exc:
            await create_member(body=body, admin=_admin(id=99, role="trainer"), session=AsyncMock())
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_username_409(self):
        body = UserCreate(username="dup", password="pass1234", role="user")
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(_make_user(id=999, username="dup"))

        with pytest.raises(HTTPException) as exc:
            await create_member(body=body, admin=_admin(), session=session)
        assert exc.value.status_code == 409
        assert "已被占用" in exc.value.detail

    @pytest.mark.asyncio
    async def test_username_too_short_via_pydantic(self):
        """username min_length=3 → Pydantic ValidationError。"""
        with pytest.raises(ValidationError) as exc:
            UserCreate(username="a", password="pass1234", role="user")
        assert "username" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_password_too_short_via_pydantic(self):
        """password min_length=8 → Pydantic ValidationError。"""
        with pytest.raises(ValidationError) as exc:
            UserCreate(username="validuser", password="123", role="user")
        assert "password" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_password_8chars_no_letter_rejected_by_regex(self):
        """password 满足长度但不满足"含字母+数字" → 路由层正则 400。"""
        body = UserCreate(username="validuser", password="12345678", role="user")  # 全数字
        session = _setup_create_session()

        with pytest.raises(HTTPException) as exc:
            await create_member(body=body, admin=_admin(), session=session)
        assert exc.value.status_code == 400
        assert "密码格式" in exc.value.detail

    @pytest.mark.asyncio
    async def test_empty_password_auto_generates(self):
        body = UserCreate(username="autopwd", password=None, role="user")
        session = _setup_create_session()

        result = await create_member(body=body, admin=_admin(), session=session)
        assert result.initial_password  # 非空
        assert len(result.initial_password) == 10  # _gen_password 默认 10 位

    @pytest.mark.asyncio
    async def test_integrity_error_409_rollback(self):
        """commit 时撞 unique 约束 → 409 + rollback。"""
        body = UserCreate(username="race", password="pass1234", role="user")
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(None)
        session.commit.side_effect = IntegrityError("stmt", "params", "orig")

        with pytest.raises(HTTPException) as exc:
            await create_member(body=body, admin=_admin(), session=session)
        assert exc.value.status_code == 409
        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_username_strip(self):
        """用户名 trim 后再校验（前后空格被去掉）。"""
        body = UserCreate(username="  spaced  ", password="pass1234", role="user")
        session = _setup_create_session()

        result = await create_member(body=body, admin=_admin(), session=session)
        assert result.user.username == "spaced"  # 无前后空格


# ============ get_member ============

class TestGetMember:
    """GET /members/{id}：详情。"""

    @pytest.mark.asyncio
    async def test_returns_detail_with_counts(self):
        u = _make_user(id=10, username="target", avatar_url="http://x", gender=1, age=25, height_cm=175.0, weight_kg=70.0)
        session = AsyncMock()
        user_result = _mock_session_scalar(u)
        plan_count_result = _mock_session_scalar_one(5)
        ai_count_result = _mock_session_scalar_one(20)
        empty_rows = _mock_session_rows([])
        session.execute.side_effect = [user_result, plan_count_result, ai_count_result, empty_rows, empty_rows]

        result = await get_member(user_id=10, _user=_admin(), session=session)
        assert result.id == 10
        assert result.username == "target"
        assert result.plan_count == 5
        assert result.ai_msg_count == 20
        assert result.avatar_url == "http://x"

    @pytest.mark.asyncio
    async def test_user_not_found_404(self):
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(None)

        with pytest.raises(HTTPException) as exc:
            await get_member(user_id=999, _user=_admin(), session=session)
        assert exc.value.status_code == 404


# ============ update_member_status ============

class TestUpdateMemberStatus:
    """PATCH /members/{id}/status：封禁/解封。"""

    @pytest.mark.asyncio
    async def test_ban_user_appends_remark(self):
        u = _make_user(id=10, remark="旧备注")
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        body = UserStatusUpdate(status=1, reason="违规发广告")
        result = await update_member_status(user_id=10, body=body, admin=_admin(id=99), session=session)

        assert result.status == 1
        assert "旧备注" in (u.remark or "")
        assert "封禁" in u.remark
        assert "违规发广告" in u.remark

    @pytest.mark.asyncio
    async def test_ban_without_reason_400(self):
        u = _make_user(id=10)
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        body = UserStatusUpdate(status=1, reason="")
        with pytest.raises(HTTPException) as exc:
            await update_member_status(user_id=10, body=body, admin=_admin(id=99), session=session)
        assert exc.value.status_code == 400
        assert "原因" in exc.value.detail

    @pytest.mark.asyncio
    async def test_cannot_ban_self(self):
        admin = _admin(id=10, role="admin")
        u = _make_user(id=10, role="admin")
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        body = UserStatusUpdate(status=1, reason="测试")
        with pytest.raises(HTTPException) as exc:
            await update_member_status(user_id=10, body=body, admin=admin, session=session)
        assert exc.value.status_code == 400
        assert "自己" in exc.value.detail

    @pytest.mark.asyncio
    async def test_unban_appends_unban_tag(self):
        u = _make_user(id=10, status=1, remark=None)
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        body = UserStatusUpdate(status=0, reason="复审通过")
        result = await update_member_status(user_id=10, body=body, admin=_admin(id=99), session=session)
        assert result.status == 0
        assert "解封" in u.remark
        assert "复审通过" in u.remark

    @pytest.mark.asyncio
    async def test_user_not_found_404(self):
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(None)

        body = UserStatusUpdate(status=1, reason="x")
        with pytest.raises(HTTPException) as exc:
            await update_member_status(user_id=999, body=body, admin=_admin(), session=session)
        assert exc.value.status_code == 404


# ============ update_member_remark ============

class TestUpdateMemberRemark:
    """PATCH /members/{id}/remark：备注修改。"""

    @pytest.mark.asyncio
    async def test_set_remark(self):
        u = _make_user(id=10, remark="旧")
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        body = UserRemarkUpdate(remark="新备注")
        result = await update_member_remark(user_id=10, body=body, admin=_admin(), session=session)
        assert u.remark == "新备注"
        assert result.remark == "新备注"

    @pytest.mark.asyncio
    async def test_empty_remark_to_none(self):
        """空字符串应归一为 None（清空）。"""
        u = _make_user(id=10, remark="旧")
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        body = UserRemarkUpdate(remark="")
        result = await update_member_remark(user_id=10, body=body, admin=_admin(), session=session)
        assert u.remark is None
        assert result.remark is None

    @pytest.mark.asyncio
    async def test_user_not_found_404(self):
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(None)

        with pytest.raises(HTTPException) as exc:
            await update_member_remark(user_id=999, body=UserRemarkUpdate(remark="x"), admin=_admin(), session=session)
        assert exc.value.status_code == 404


# ============ reset_member_password ============

class TestResetPassword:
    """POST /members/{id}/reset-password：重置密码 + 清锁定。"""

    @pytest.mark.asyncio
    async def test_resets_password_and_clears_lock(self):
        u = _make_user(id=10, failed_login_count=5, locked_until=datetime(2026, 1, 1))
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        result = await reset_member_password(user_id=10, admin=_admin(id=99), session=session)
        assert result.user_id == 10
        assert result.new_password  # 非空
        assert u.failed_login_count == 0
        assert u.locked_until is None
        assert u.password_hash  # 新的 hash

    @pytest.mark.asyncio
    async def test_cannot_reset_self(self):
        admin = _admin(id=10)
        u = _make_user(id=10)
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        with pytest.raises(HTTPException) as exc:
            await reset_member_password(user_id=10, admin=admin, session=session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_user_not_found_404(self):
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(None)

        with pytest.raises(HTTPException) as exc:
            await reset_member_password(user_id=999, admin=_admin(), session=session)
        assert exc.value.status_code == 404


# ============ delete_member ============

class TestDeleteMember:
    """DELETE /members/{id}：软删除。"""

    @pytest.mark.asyncio
    async def test_soft_delete_user(self):
        u = _make_user(id=10, username="victim", nickname="昵称", role="user")
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        await delete_member(user_id=10, admin=_admin(id=99), session=session, reason="违规")

        assert u.is_deleted is True
        assert u.status == 1
        assert u.password_hash == ""
        assert u.username.startswith("del_10_")
        assert u.username.endswith("victim")
        assert u.nickname == "[已删除]昵称"

    @pytest.mark.asyncio
    async def test_cannot_delete_self(self):
        admin = _admin(id=10)
        u = _make_user(id=10, role="admin")
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        with pytest.raises(HTTPException) as exc:
            await delete_member(user_id=10, admin=admin, session=session, reason=None)
        assert exc.value.status_code == 400
        assert "自己" in exc.value.detail

    @pytest.mark.asyncio
    async def test_cannot_delete_last_admin(self):
        u = _make_user(id=10, role="admin")
        session = AsyncMock()
        session.execute.side_effect = [_mock_session_scalar(u), _mock_session_scalar_one(1)]

        with pytest.raises(HTTPException) as exc:
            await delete_member(user_id=10, admin=_admin(id=99), session=session, reason=None)
        assert exc.value.status_code == 400
        assert "最后一个" in exc.value.detail

    @pytest.mark.asyncio
    async def test_can_delete_admin_when_multiple_exist(self):
        u = _make_user(id=10, role="admin")
        session = AsyncMock()
        session.execute.side_effect = [_mock_session_scalar(u), _mock_session_scalar_one(3)]

        await delete_member(user_id=10, admin=_admin(id=99), session=session, reason="交接")
        assert u.is_deleted is True

    @pytest.mark.asyncio
    async def test_already_deleted_404(self):
        u = _make_user(id=10, is_deleted=True)
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(u)

        with pytest.raises(HTTPException) as exc:
            await delete_member(user_id=10, admin=_admin(id=99), session=session, reason=None)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_user_not_found_404(self):
        session = AsyncMock()
        session.execute.return_value = _mock_session_scalar(None)

        with pytest.raises(HTTPException) as exc:
            await delete_member(user_id=999, admin=_admin(), session=session, reason=None)
        assert exc.value.status_code == 404


# ============ export_members_csv ============

class TestExportCsv:
    """GET /members/export：CSV 导出。"""

    @pytest.mark.asyncio
    async def test_export_with_rows(self):
        u1 = _make_user(id=1, username="u1", nickname="n1", role="user", status=0, remark="备注\n带换行")
        u2 = _make_user(id=2, username="u2", nickname="n2", role="trainer", status=1)
        session = AsyncMock()
        session.execute.return_value = _mock_session_rows([(u1, 1, 2), (u2, 0, 0)])

        resp = await export_members_csv(
            operator=_admin(), session=session,
            keyword=None, role=None, status_=None, date_from=None, date_to=None,
        )
        assert resp.media_type.startswith("text/csv")
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        csv_text = "".join(chunks)
        assert "用户ID" in csv_text
        assert "用户名" in csv_text
        assert "u1" in csv_text
        assert "u2" in csv_text
        assert "封禁" in csv_text  # u2 status=1
        # remark 换行被替换为空格
        assert "\n带换行" not in csv_text
        assert "备注 带换行" in csv_text

    @pytest.mark.asyncio
    async def test_export_empty_only_header(self):
        session = AsyncMock()
        session.execute.return_value = _mock_session_rows([])

        resp = await export_members_csv(
            operator=_admin(), session=session,
            keyword=None, role=None, status_=None, date_from=None, date_to=None,
        )
        chunks = [c async for c in resp.body_iterator]
        csv_text = "".join(chunks)
        assert "用户ID" in csv_text
        assert "u1" not in csv_text  # 无数据行


# ============ _gen_password 工具 ============

class TestGenPassword:
    def test_length_and_charset(self):
        for length in (8, 10, 12):
            pwd = _gen_password(length=length)
            assert len(pwd) == length
            assert any(c.isupper() for c in pwd)
            assert any(c.isdigit() for c in pwd)
            assert all(c.isalnum() for c in pwd)

    def test_unique_each_time(self):
        """连续生成 100 次至少出现多个不同值（高概率唯一）。"""
        passwords = {_gen_password() for _ in range(100)}
        assert len(passwords) > 50
