"""admin_templates.py 单测（mocked AsyncSession）。

覆盖端点（15 个）：
- GET    /admin/templates/queue              list_queue_templates
- GET    /admin/templates/pending            list_pending_templates
- GET    /admin/templates                    list_all_templates
- GET    /admin/templates/{id}               get_template
- PATCH  /admin/templates/{id}               admin_update_template
- POST   /admin/templates                    admin_create_template
- POST   /admin/templates/{id}/publish       admin_publish_template
- DELETE /admin/templates/{id}               admin_delete_template
- POST   /admin/templates/{id}/approve       approve_template
- POST   /admin/templates/{id}/reject        reject_template
- POST   /admin/templates/{id}/offline       offline_template
- POST   /admin/templates/{id}/republish     republish_template
- GET    /admin/trainer-accounts             list_trainers
- POST   /admin/trainer-accounts             create_trainer
- PATCH  /admin/trainer-accounts/{id}        toggle_trainer

业务规则：
- 状态机：draft → pending_review → published → offline ↔ draft
- 仅 draft / offline 可 PATCH
- approve / reject 仅 pending；offline 仅 published；publish 仅 draft；republish 仅 offline
- reject / offline 必须带 reason（reason 非空）
- trainer 角色访问 get_template 必须 author_id==self，否则 404
- 创建教练：用户名/密码正则校验 + IntegrityError 兜底 409
- 切换教练启停：0↔1；不能操作自己；非 trainer → 404
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.v1.admin_templates import (
    TrainerCreate,
    TrainerItem,
    _to_out,
    _utcnow_naive,
    admin_create_template,
    admin_delete_template,
    admin_publish_template,
    admin_update_template,
    approve_template,
    create_trainer,
    get_template,
    list_all_templates,
    list_pending_templates,
    list_queue_templates,
    list_trainers,
    offline_template,
    reject_template,
    republish_template,
    toggle_trainer,
)
from app.schemas.plan_template import (
    PlanTemplateCreate,
    PlanTemplateListResponse,
    PlanTemplateReviewUpdate,
    PlanTemplateUpdate,
)


# ============ Helpers ============

def _make_admin(id=1, username="admin1"):
    return SimpleNamespace(
        id=id, username=username, nickname=username, role="admin",
        status=0, is_deleted=False, is_banned=False, is_locked=False,
    )


def _make_trainer(id=10, username="coach1", nickname=None, status=0, role="trainer", created_at=None):
    return SimpleNamespace(
        id=id, username=username,
        nickname=nickname or username, role=role,
        status=status, is_deleted=False, is_banned=False, is_locked=False,
        last_login_at=None,
        created_at=created_at or datetime(2024, 1, 1),
    )


def _make_template(
    id=1, name="模板", author_id=10, status="draft",
    goal="muscle_gain", level="beginner", weeks=None,
    description=None, cover_url=None,
    use_count=0, avg_rating=0.0, review_count=0,
    reject_reason=None, published_at=None,
    created_at=None, updated_at=None,
    author_nickname=None, days_per_week=3,
):
    return SimpleNamespace(
        id=id, name=name, author_id=author_id, status=status,
        goal=goal, level=level, days_per_week=days_per_week,
        weeks=weeks or [], description=description, cover_url=cover_url,
        use_count=use_count, avg_rating=avg_rating, review_count=review_count,
        reject_reason=reject_reason, published_at=published_at,
        created_at=created_at or datetime(2024, 1, 1),
        updated_at=updated_at or datetime(2024, 1, 1),
        author_nickname=author_nickname,
    )


def _mock_session_scalar(scalar, *, get_returns=None):
    """session.execute().scalar_one_or_none() = scalar；session.get 可指定。"""
    s = AsyncMock()
    r = MagicMock(); r.scalar_one_or_none.return_value = scalar
    s.execute.return_value = r
    if get_returns is not None:
        s.get = AsyncMock(return_value=get_returns)
    else:
        s.get = AsyncMock(return_value=scalar)
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    s.delete = AsyncMock()
    s.add = MagicMock()
    s.rollback = AsyncMock()
    return s


def _mock_session_scalars(items, *, scalar_total=0):
    """session.execute().scalars().all() = items；session.execute().scalar() = scalar_total。"""
    s = AsyncMock()
    results = [
        MagicMock(),  # base query
        MagicMock(),  # count query
    ]
    results[0].scalars.return_value.all.return_value = items
    results[1].scalar.return_value = scalar_total
    s.execute.side_effect = results
    s.get = AsyncMock()
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    s.add = MagicMock()
    s.delete = AsyncMock()
    s.rollback = AsyncMock()
    return s


def _mock_session_create(*, get_returns=None):
    """create_template / send_trainer_message 等专用。"""
    s = AsyncMock()
    nxt = {"id": 1000}

    async def fake_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = nxt["id"]; nxt["id"] += 1
        now = datetime(2024, 1, 1)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        # PlanTemplate 字段默认值（避免 Pydantic 校验失败）
        if not hasattr(obj, "use_count") or obj.use_count is None:
            obj.use_count = 0
        if not hasattr(obj, "review_count") or obj.review_count is None:
            obj.review_count = 0

    s.refresh.side_effect = fake_refresh
    s.commit = AsyncMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.delete = AsyncMock()
    s.rollback = AsyncMock()
    # 默认 execute 返回 scalar_one_or_none=None（用于 create_trainer 的"已存在"预检）
    r_default = MagicMock()
    r_default.scalar_one_or_none.return_value = None
    s.execute = AsyncMock(return_value=r_default)
    if get_returns is not None:
        s.get = AsyncMock(return_value=get_returns)
    else:
        s.get = AsyncMock(return_value=None)
    return s


# ============ 工具函数 ============

class TestUtilFunctions:

    def test_utcnow_naive(self):
        t = _utcnow_naive()
        assert t.tzinfo is None
        assert isinstance(t, datetime)

    def test_to_out_passes_through(self):
        t = _make_template()
        out = _to_out(t)
        assert out.id == 1
        assert out.name == "模板"


# ============ /templates/queue ============

class TestListQueue:

    @pytest.mark.asyncio
    async def test_queue_with_data(self):
        templates = [_make_template(id=1), _make_template(id=2, status="pending_review")]
        session = _mock_session_scalars(templates, scalar_total=2)
        result = await list_queue_templates(_make_admin(), session, page=1, page_size=20)
        assert isinstance(result, PlanTemplateListResponse)
        assert result.total == 2
        assert len(result.items) == 2
        assert result.page == 1

    @pytest.mark.asyncio
    async def test_queue_empty(self):
        session = _mock_session_scalars([], scalar_total=0)
        result = await list_queue_templates(_make_admin(), session, page=1, page_size=20)
        assert result.total == 0
        assert result.items == []
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_queue_has_more_truncation(self):
        """返回 page_size+1 行时，has_more=True 且 items 截断。"""
        templates = [_make_template(id=i) for i in range(1, 22)]  # 21 行
        session = _mock_session_scalars(templates, scalar_total=21)
        result = await list_queue_templates(_make_admin(), session, page=1, page_size=20)
        assert len(result.items) == 20
        assert result.has_more is True


# ============ /templates/pending ============

class TestListPending:

    @pytest.mark.asyncio
    async def test_pending_with_data(self):
        templates = [_make_template(id=1, status="pending_review")]
        session = _mock_session_scalars(templates, scalar_total=1)
        result = await list_pending_templates(_make_admin(), session, page=1, page_size=20)
        assert result.total == 1
        assert result.items[0].status == "pending_review"

    @pytest.mark.asyncio
    async def test_pending_empty(self):
        session = _mock_session_scalars([], scalar_total=0)
        result = await list_pending_templates(_make_admin(), session, page=1, page_size=20)
        assert result.total == 0


# ============ /templates ============

class TestListAll:

    @pytest.mark.asyncio
    async def test_list_all_no_filter(self):
        templates = [
            _make_template(id=1, status="draft"),
            _make_template(id=2, status="published"),
        ]
        session = _mock_session_scalars(templates, scalar_total=2)
        result = await list_all_templates(_make_admin(), session, status_=None, page=1, page_size=20)
        assert result.total == 2
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_list_all_with_status(self):
        templates = [_make_template(id=1, status="published")]
        session = _mock_session_scalars(templates, scalar_total=1)
        result = await list_all_templates(_make_admin(), session, status_="published", page=1, page_size=20)
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_list_all_invalid_status_400(self):
        session = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await list_all_templates(_make_admin(), session, status_="garbage", page=1, page_size=20)
        assert exc.value.status_code == 400
        assert "未知状态" in exc.value.detail


# ============ /templates/{id} ============

class TestGetOne:

    @pytest.mark.asyncio
    async def test_admin_can_view_any(self):
        t = _make_template(author_id=999)  # 作者不是 admin
        session = _mock_session_scalar(None, get_returns=t)
        result = await get_template(1, _make_admin(), session)
        assert result.id == 1
        assert result.author_id == 999

    @pytest.mark.asyncio
    async def test_trainer_can_view_own(self):
        t = _make_template(id=1, author_id=10)
        session = _mock_session_scalar(None, get_returns=t)
        result = await get_template(1, _make_trainer(id=10), session)
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_trainer_cannot_view_others_404(self):
        """trainer 看别人的模板 → 404（避免泄露存在性）。"""
        t = _make_template(id=1, author_id=999)
        session = _mock_session_scalar(None, get_returns=t)
        with pytest.raises(HTTPException) as exc:
            await get_template(1, _make_trainer(id=10), session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await get_template(999, _make_admin(), session)
        assert exc.value.status_code == 404


# ============ PATCH /templates/{id} ============

class TestPatch:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ok_status", ["draft", "offline"])
    async def test_patch_editable_status_success(self, ok_status):
        t = _make_template(status=ok_status)
        session = _mock_session_scalar(None, get_returns=t)
        result = await admin_update_template(1, PlanTemplateUpdate(name="新名"), _make_admin(), session)
        assert result.name == "新名"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_status", ["pending_review", "published"])
    async def test_patch_non_editable_status_blocked(self, bad_status):
        t = _make_template(status=bad_status)
        session = _mock_session_scalar(None, get_returns=t)
        with pytest.raises(HTTPException) as exc:
            await admin_update_template(1, PlanTemplateUpdate(name="x"), _make_admin(), session)
        assert exc.value.status_code == 400
        assert "不可编辑" in exc.value.detail

    @pytest.mark.asyncio
    async def test_patch_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await admin_update_template(999, PlanTemplateUpdate(name="x"), _make_admin(), session)
        assert exc.value.status_code == 404


# ============ POST /templates ============

class TestCreate:

    @pytest.mark.asyncio
    async def test_create_default_draft(self):
        session = _mock_session_create()
        body = PlanTemplateCreate(
            name="新手计划", goal="muscle_gain", level="beginner",
            weeks=[{"week": 1, "days": [{"day": 1, "exercises": []}]}],
        )
        result = await admin_create_template(body, _make_admin(), session)
        assert result.name == "新手计划"
        assert result.status == "draft"
        assert result.author_id == 1
        assert session.add.called
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_with_published_status(self):
        session = _mock_session_create()
        body = PlanTemplateCreate(
            name="已上架", goal="fat_loss", level="intermediate",
            weeks=[{"week": 1, "days": [{"day": 1, "exercises": []}]}],
            status="published",
        )
        result = await admin_create_template(body, _make_admin(), session)
        assert result.status == "published"
        assert result.published_at is not None

    @pytest.mark.asyncio
    async def test_create_invalid_status_falls_back_to_draft(self):
        session = _mock_session_create()
        body = PlanTemplateCreate(
            name="X", goal="muscle_gain", level="beginner",
            weeks=[{"week": 1, "days": []}],
        )
        # 直接构造一个非法 status（绕开 Pydantic 校验）
        body.status = "invalid_status_xxx"  # type: ignore[assignment]
        result = await admin_create_template(body, _make_admin(), session)
        assert result.status == "draft"


# ============ POST /templates/{id}/publish ============

class TestPublish:

    @pytest.mark.asyncio
    async def test_publish_draft_success(self):
        t = _make_template(status="draft")
        session = _mock_session_scalar(None, get_returns=t)
        result = await admin_publish_template(1, _make_admin(), session)
        assert result.status == "published"
        assert t.status == "published"
        assert t.published_at is not None
        assert t.reject_reason is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_status", ["pending_review", "published", "offline"])
    async def test_publish_non_draft_blocked(self, bad_status):
        t = _make_template(status=bad_status)
        session = _mock_session_scalar(None, get_returns=t)
        with pytest.raises(HTTPException) as exc:
            await admin_publish_template(1, _make_admin(), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_publish_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await admin_publish_template(999, _make_admin(), session)
        assert exc.value.status_code == 404


# ============ DELETE /templates/{id} ============

class TestDelete:

    @pytest.mark.asyncio
    async def test_delete_any_status(self):
        for st in ("draft", "pending_review", "published", "offline"):
            t = _make_template(status=st)
            session = _mock_session_scalar(None, get_returns=t)
            result = await admin_delete_template(1, _make_admin(), session)
            assert result is None
            session.delete.assert_awaited_with(t)

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await admin_delete_template(999, _make_admin(), session)
        assert exc.value.status_code == 404


# ============ POST /templates/{id}/approve ============

class TestApprove:

    @pytest.mark.asyncio
    async def test_approve_pending_success(self):
        t = _make_template(status="pending_review", reject_reason="旧理由")
        session = _mock_session_scalar(None, get_returns=t)
        result = await approve_template(1, _make_admin(), session)
        assert result.status == "published"
        assert t.status == "published"
        assert t.published_at is not None
        assert t.reject_reason is None  # 清掉旧理由

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_status", ["draft", "published", "offline"])
    async def test_approve_non_pending_blocked(self, bad_status):
        t = _make_template(status=bad_status)
        session = _mock_session_scalar(None, get_returns=t)
        with pytest.raises(HTTPException) as exc:
            await approve_template(1, _make_admin(), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_approve_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await approve_template(999, _make_admin(), session)
        assert exc.value.status_code == 404


# ============ POST /templates/{id}/reject ============

class TestReject:

    @pytest.mark.asyncio
    async def test_reject_pending_with_reason_success(self):
        t = _make_template(status="pending_review")
        session = _mock_session_scalar(None, get_returns=t)
        body = PlanTemplateReviewUpdate(reason="理由不充分")
        result = await reject_template(1, body, _make_admin(), session)
        assert result.status == "draft"
        assert t.status == "draft"
        assert t.reject_reason == "理由不充分"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_reason", [None, "", "   \n  "])
    async def test_reject_pending_bad_reason_400(self, bad_reason):
        t = _make_template(status="pending_review")
        session = _mock_session_scalar(None, get_returns=t)
        body = PlanTemplateReviewUpdate(reason=bad_reason)
        with pytest.raises(HTTPException) as exc:
            await reject_template(1, body, _make_admin(), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_status", ["draft", "published", "offline"])
    async def test_reject_non_pending_blocked(self, bad_status):
        t = _make_template(status=bad_status)
        session = _mock_session_scalar(None, get_returns=t)
        with pytest.raises(HTTPException) as exc:
            await reject_template(1, PlanTemplateReviewUpdate(reason="x"), _make_admin(), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_reject_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await reject_template(999, PlanTemplateReviewUpdate(reason="x"), _make_admin(), session)
        assert exc.value.status_code == 404


# ============ POST /templates/{id}/offline ============

class TestOffline:

    @pytest.mark.asyncio
    async def test_offline_published_with_reason_success(self):
        t = _make_template(status="published")
        session = _mock_session_scalar(None, get_returns=t)
        body = PlanTemplateReviewUpdate(reason="违反规范")
        result = await offline_template(1, body, _make_admin(), session)
        assert result.status == "offline"
        assert t.status == "offline"
        assert t.reject_reason == "违反规范"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_reason", [None, ""])
    async def test_offline_published_bad_reason_400(self, bad_reason):
        t = _make_template(status="published")
        session = _mock_session_scalar(None, get_returns=t)
        body = PlanTemplateReviewUpdate(reason=bad_reason)
        with pytest.raises(HTTPException) as exc:
            await offline_template(1, body, _make_admin(), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_status", ["draft", "pending_review", "offline"])
    async def test_offline_non_published_blocked(self, bad_status):
        t = _make_template(status=bad_status)
        session = _mock_session_scalar(None, get_returns=t)
        with pytest.raises(HTTPException) as exc:
            await offline_template(1, PlanTemplateReviewUpdate(reason="x"), _make_admin(), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_offline_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await offline_template(999, PlanTemplateReviewUpdate(reason="x"), _make_admin(), session)
        assert exc.value.status_code == 404


# ============ POST /templates/{id}/republish ============

class TestRepublish:

    @pytest.mark.asyncio
    async def test_republish_offline_success(self):
        t = _make_template(status="offline", reject_reason="旧理由")
        session = _mock_session_scalar(None, get_returns=t)
        result = await republish_template(1, _make_admin(), session)
        assert result.status == "published"
        assert t.status == "published"
        assert t.published_at is not None
        assert t.reject_reason is None  # 清掉旧理由

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_status", ["draft", "pending_review", "published"])
    async def test_republish_non_offline_blocked(self, bad_status):
        t = _make_template(status=bad_status)
        session = _mock_session_scalar(None, get_returns=t)
        with pytest.raises(HTTPException) as exc:
            await republish_template(1, _make_admin(), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_republish_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await republish_template(999, _make_admin(), session)
        assert exc.value.status_code == 404


# ============ GET /trainer-accounts ============

class TestListTrainerAccounts:

    @pytest.mark.asyncio
    async def test_list_trainers_success(self):
        trainers = [
            _make_trainer(id=10, username="coach1"),
            _make_trainer(id=11, username="coach2"),
        ]
        session = AsyncMock()
        r = MagicMock()
        r.scalars.return_value.all.return_value = trainers
        session.execute.return_value = r
        result = await list_trainers(_make_admin(), session)
        assert len(result) == 2
        assert all(isinstance(x, TrainerItem) for x in result)
        assert result[0].username == "coach1"

    @pytest.mark.asyncio
    async def test_list_trainers_empty(self):
        session = AsyncMock()
        r = MagicMock()
        r.scalars.return_value.all.return_value = []
        session.execute.return_value = r
        result = await list_trainers(_make_admin(), session)
        assert result == []


# ============ POST /trainer-accounts ============

class TestCreateTrainerAccount:

    @pytest.mark.asyncio
    async def test_create_trainer_success(self):
        session = _mock_session_create()
        body = TrainerCreate(username="newcoach1", password="Abcd1234", nickname="新教练")
        result = await create_trainer(body, _make_admin(), session)
        assert result.username == "newcoach1"
        assert result.role == "trainer"
        assert result.status == 0
        assert session.add.called
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_trainer_chinese_username(self):
        """中文字符串用户名应被接受。"""
        session = _mock_session_create()
        body = TrainerCreate(username="张三教练", password="Abcd1234")
        result = await create_trainer(body, _make_admin(), session)
        assert result.username == "张三教练"

    @pytest.mark.asyncio
    async def test_create_invalid_username_400(self):
        """含特殊字符的用户名 → 400（regex 在 endpoint 校验）。"""
        body = TrainerCreate(username="a b", password="Abcd1234")  # 空格不在正则范围
        with pytest.raises(HTTPException) as exc:
            await create_trainer(body, _make_admin(), AsyncMock())
        assert exc.value.status_code == 400
        assert "用户名" in exc.value.detail

    @pytest.mark.asyncio
    async def test_create_username_too_short_pydantic(self):
        """太短（<3 字符）由 Pydantic 拦截 → ValueError。"""
        with pytest.raises(ValueError):
            TrainerCreate(username="ab", password="Abcd1234")

    @pytest.mark.asyncio
    async def test_create_password_no_letter_400(self):
        body = TrainerCreate(username="newcoach1", password="12345678")  # 无字母
        with pytest.raises(HTTPException) as exc:
            await create_trainer(body, _make_admin(), AsyncMock())
        assert exc.value.status_code == 400
        assert "密码" in exc.value.detail

    @pytest.mark.asyncio
    async def test_create_password_no_digit_400(self):
        body = TrainerCreate(username="newcoach1", password="abcdefgh")  # 无数字
        with pytest.raises(HTTPException) as exc:
            await create_trainer(body, _make_admin(), AsyncMock())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_password_too_short_pydantic(self):
        """密码 <8 由 Pydantic 拦截 → ValueError。"""
        with pytest.raises(ValueError):
            TrainerCreate(username="newcoach1", password="Ab1")

    @pytest.mark.asyncio
    async def test_create_existing_username_409(self):
        """预检查到已存在 → 409。"""
        session = _mock_session_create()
        existing = _make_trainer(id=99, username="dupcoach")
        r = MagicMock(); r.scalar_one_or_none.return_value = existing
        session.execute.return_value = r
        body = TrainerCreate(username="dupcoach", password="Abcd1234")
        with pytest.raises(HTTPException) as exc:
            await create_trainer(body, _make_admin(), session)
        assert exc.value.status_code == 409
        assert "已被占用" in exc.value.detail

    @pytest.mark.asyncio
    async def test_create_integrity_error_409(self):
        """预检未命中但 commit 时 IntegrityError → 409（rollback）。"""
        session = _mock_session_create()
        r = MagicMock(); r.scalar_one_or_none.return_value = None
        session.execute.return_value = r
        session.commit.side_effect = IntegrityError("stmt", {}, Exception("dup"))
        body = TrainerCreate(username="racecoach", password="Abcd1234")
        with pytest.raises(HTTPException) as exc:
            await create_trainer(body, _make_admin(), session)
        assert exc.value.status_code == 409
        session.rollback.assert_awaited()


# ============ PATCH /trainer-accounts/{id} ============

class TestUpdateTrainerAccount:

    @pytest.mark.asyncio
    async def test_toggle_active_to_disabled(self):
        """status=0 → 1。"""
        u = _make_trainer(id=20, username="coach1", status=0)
        session = _mock_session_scalar(None, get_returns=u)
        result = await toggle_trainer(20, _make_admin(id=1), session)
        assert u.status == 1
        assert result.status == 1

    @pytest.mark.asyncio
    async def test_toggle_disabled_to_active(self):
        """status=1 → 0。"""
        u = _make_trainer(id=20, username="coach1", status=1)
        session = _mock_session_scalar(None, get_returns=u)
        result = await toggle_trainer(20, _make_admin(id=1), session)
        assert u.status == 0
        assert result.status == 0

    @pytest.mark.asyncio
    async def test_toggle_self_blocked_400(self):
        """admin 操作自己（角色必须是 trainer 才走到 self 检查）→ 400。"""
        u = _make_trainer(id=1, username="selfcoach", role="trainer", status=0)
        session = _mock_session_scalar(None, get_returns=u)
        with pytest.raises(HTTPException) as exc:
            await toggle_trainer(1, _make_admin(id=1), session)
        assert exc.value.status_code == 400
        assert "自己" in exc.value.detail

    @pytest.mark.asyncio
    async def test_toggle_non_trainer_404(self):
        """user.role != trainer → 404（避免泄露其他角色用户）。"""
        u = SimpleNamespace(id=30, username="normaluser", role="user", status=0)
        session = _mock_session_scalar(None, get_returns=u)
        with pytest.raises(HTTPException) as exc:
            await toggle_trainer(30, _make_admin(id=1), session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_not_found(self):
        session = _mock_session_scalar(None, get_returns=None)
        with pytest.raises(HTTPException) as exc:
            await toggle_trainer(999, _make_admin(id=1), session)
        assert exc.value.status_code == 404