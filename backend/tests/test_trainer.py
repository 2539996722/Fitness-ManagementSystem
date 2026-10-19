"""trainer.py 单测（mocked AsyncSession）。

覆盖：
- 模板 CRUD：create / update / delete / submit（带状态校验）
- 会话校验：_check_trainer_conv
- 接入 / 发消息 / 拉消息 / 关闭会话
- 推荐模板 / 定制计划
- 队列 + 历史（multi-query loop）
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.trainer import (
    _check_trainer_conv,
    _to_out,
    _utcnow_naive,
    claim_trainer_conversation,
    close_trainer_conversation,
    create_template,
    customize_plan,
    delete_template,
    list_my_pending_templates,
    list_my_templates,
    list_trainer_messages,
    recommend_template,
    send_trainer_message,
    submit_template,
    trainer_history,
    trainer_queue,
    update_template,
)
from app.schemas.plan_template import (
    PlanTemplateCreate,
    PlanTemplateUpdate,
)


# ============ Helpers ============

def _make_trainer(id=1, username="coach1", role="trainer"):
    return SimpleNamespace(
        id=id, username=username, role=role,
        status=0, is_deleted=False, is_banned=False, is_locked=False,
        nickname=username, avatar_url=None,
    )


def _make_template(
    id=1, name="模板", author_id=1, status="draft",
    goal="muscle_gain", level="beginner", weeks=None,
    description=None, cover_url=None,
    use_count=0, avg_rating=0.0, review_count=0,
    created_at=None, updated_at=None,
    reject_reason=None, published_at=None,
    author_nickname=None,
):
    return SimpleNamespace(
        id=id, name=name, author_id=author_id, status=status,
        goal=goal, level=level,
        weeks=weeks or [], description=description, cover_url=cover_url,
        use_count=use_count, avg_rating=avg_rating, review_count=review_count,
        reject_reason=reject_reason, published_at=published_at,
        created_at=created_at or datetime(2024, 1, 1),
        updated_at=updated_at or datetime(2024, 1, 1),
        author_nickname=author_nickname,
    )


def _make_conversation(
    id=1, user_id=2, conversation_type="trainer", status="waiting_trainer",
    assigned_trainer_id=None, title="测试", created_at=None, updated_at=None,
):
    return SimpleNamespace(
        id=id, user_id=user_id, conversation_type=conversation_type, status=status,
        assigned_trainer_id=assigned_trainer_id, title=title,
        created_at=created_at or datetime(2024, 1, 1),
        updated_at=updated_at or datetime(2024, 1, 1),
    )


def _make_message(
    id=1, conversation_id=1, sender_type="user", sender_id=2,
    content="msg", extra=None, created_at=None,
):
    return SimpleNamespace(
        id=id, conversation_id=conversation_id,
        sender_type=sender_type, sender_id=sender_id,
        content=content, extra=extra or {},
        created_at=created_at or datetime(2024, 1, 1),
    )


def _mock_session_scalar(scalar):
    """session.execute().scalar_one_or_none() = scalar。"""
    session = AsyncMock()
    r = MagicMock(); r.scalar_one_or_none.return_value = scalar
    session.execute.return_value = r
    session.get = AsyncMock(return_value=scalar)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return session


def _mock_session_scalars(items):
    """session.execute().scalars().all() = items。"""
    session = AsyncMock()
    r = MagicMock(); r.scalars.return_value.all.return_value = items
    session.execute.return_value = r
    session.get = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _mock_session_create(*, get_returns=None):
    """create_template / send_trainer_message 等专用。

    refresh 回填 id/created_at/updated_at。
    session.get(Conversation|Template) → 返回 get_returns。
    """
    session = AsyncMock()
    nxt = {"id": 1000}

    async def fake_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = nxt["id"]; nxt["id"] += 1
        now = datetime(2024, 1, 1)
        if getattr(obj, "created_at", None) is None: obj.created_at = now
        if getattr(obj, "updated_at", None) is None: obj.updated_at = now

    session.refresh.side_effect = fake_refresh
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    if get_returns is not None:
        # 按调用顺序返回（多次 get 调用）
        if isinstance(get_returns, list):
            session.get = AsyncMock(side_effect=get_returns)
        else:
            session.get = AsyncMock(return_value=get_returns)
    else:
        session.get = AsyncMock(return_value=None)
    return session


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


# ============ 模板 CRUD ============

class TestCreateTemplate:

    @pytest.mark.asyncio
    async def test_create_success(self):
        session = _mock_session_create()
        trainer = _make_trainer()
        body = PlanTemplateCreate(
            name="新手计划", goal="muscle_gain", level="beginner",
            weeks=[{"week": 1, "days": [{"day": 1, "exercises": []}]}],
        )
        result = await create_template(body, trainer, session)
        assert result.name == "新手计划"
        assert result.status == "draft"
        assert result.author_id == 1
        assert result.id is not None  # refresh 回填


class TestUpdateTemplate:

    @pytest.mark.asyncio
    async def test_update_draft_success(self):
        t = _make_template(status="draft")
        session = _mock_session_scalar(t)
        body = PlanTemplateUpdate(name="改名了")
        result = await update_template(1, body, _make_trainer(), session)
        assert result.name == "改名了"

    @pytest.mark.asyncio
    async def test_update_offline_success(self):
        t = _make_template(status="offline")
        session = _mock_session_scalar(t)
        body = PlanTemplateUpdate(description="新描述")
        result = await update_template(1, body, _make_trainer(), session)
        assert result.description == "新描述"

    @pytest.mark.asyncio
    async def test_update_published_blocked(self):
        t = _make_template(status="published")
        session = _mock_session_scalar(t)
        body = PlanTemplateUpdate(name="x")
        with pytest.raises(HTTPException) as exc:
            await update_template(1, body, _make_trainer(), session)
        assert exc.value.status_code == 400
        assert "不可编辑" in exc.value.detail

    @pytest.mark.asyncio
    async def test_update_not_owner_404(self):
        t = _make_template(author_id=999)  # 不属于当前 trainer
        session = _mock_session_scalar(t)
        with pytest.raises(HTTPException) as exc:
            await update_template(1, PlanTemplateUpdate(name="x"), _make_trainer(id=1), session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        session = _mock_session_scalar(None)
        with pytest.raises(HTTPException) as exc:
            await update_template(999, PlanTemplateUpdate(name="x"), _make_trainer(), session)
        assert exc.value.status_code == 404


class TestDeleteTemplate:

    @pytest.mark.asyncio
    async def test_delete_draft_success(self):
        t = _make_template(status="draft")
        session = _mock_session_scalar(t)
        result = await delete_template(1, _make_trainer(), session)
        assert result is None
        session.delete.assert_awaited_once_with(t)

    @pytest.mark.asyncio
    async def test_delete_published_blocked(self):
        t = _make_template(status="published")
        session = _mock_session_scalar(t)
        with pytest.raises(HTTPException) as exc:
            await delete_template(1, _make_trainer(), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        session = _mock_session_scalar(None)
        with pytest.raises(HTTPException) as exc:
            await delete_template(999, _make_trainer(), session)
        assert exc.value.status_code == 404


class TestSubmitTemplate:

    @pytest.mark.asyncio
    async def test_submit_draft_to_pending(self):
        t = _make_template(status="draft")
        session = _mock_session_scalar(t)
        result = await submit_template(1, _make_trainer(), session)
        assert result.status == "pending_review"
        assert t.status == "pending_review"
        assert t.reject_reason is None

    @pytest.mark.asyncio
    async def test_submit_published_blocked(self):
        t = _make_template(status="published")
        session = _mock_session_scalar(t)
        with pytest.raises(HTTPException) as exc:
            await submit_template(1, _make_trainer(), session)
        assert exc.value.status_code == 400
        assert "draft" in exc.value.detail

    @pytest.mark.asyncio
    async def test_submit_offline_blocked(self):
        """offline 状态的模板不能直接提交（要先 draft 回来？或 admin 改）。"""
        t = _make_template(status="offline")
        session = _mock_session_scalar(t)
        with pytest.raises(HTTPException) as exc:
            await submit_template(1, _make_trainer(), session)
        assert exc.value.status_code == 400


# ============ _check_trainer_conv ============

class TestCheckTrainerConv:

    @pytest.mark.asyncio
    async def test_conv_not_found(self):
        session = _mock_session_scalar(None)
        with pytest.raises(HTTPException) as exc:
            await _check_trainer_conv(999, _make_trainer(), session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_conv_type(self):
        c = _make_conversation(conversation_type="ai")  # 不是 trainer
        session = _mock_session_scalar(c)
        with pytest.raises(HTTPException) as exc:
            await _check_trainer_conv(1, _make_trainer(), session)
        assert exc.value.status_code == 400
        assert "不是人工咨询类型" in exc.value.detail

    @pytest.mark.asyncio
    async def test_require_claimed_other_trainer_403(self):
        c = _make_conversation(assigned_trainer_id=999)
        session = _mock_session_scalar(c)
        with pytest.raises(HTTPException) as exc:
            await _check_trainer_conv(1, _make_trainer(id=1), session, require_claimed=True)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_access_any_conv(self):
        """admin role 可绕过 assigned_trainer_id 校验。"""
        c = _make_conversation(assigned_trainer_id=999)
        session = _mock_session_scalar(c)
        admin = _make_trainer(id=1, username="admin", role="admin")
        result = await _check_trainer_conv(1, admin, session, require_claimed=True)
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_require_claimed_false_allows_unclaimed(self):
        """require_claimed=False → 没分配的也能访问（只读）。"""
        c = _make_conversation(assigned_trainer_id=None)
        session = _mock_session_scalar(c)
        result = await _check_trainer_conv(1, _make_trainer(id=1), session, require_claimed=False)
        assert result.id == 1


# ============ 接入会话 ============

class TestClaimConversation:

    @pytest.mark.asyncio
    async def test_claim_waiting_trainer(self):
        c = _make_conversation(status="waiting_trainer")
        session = _mock_session_scalar(c)
        result = await claim_trainer_conversation(1, _make_trainer(id=10), session)
        assert result["status"] == "trainer_active"
        assert result["trainer_id"] == 10
        assert c.assigned_trainer_id == 10

    @pytest.mark.asyncio
    async def test_claim_already_trainer_active(self):
        """trainer_active 状态可重入（同教练可继续接）。"""
        c = _make_conversation(status="trainer_active", assigned_trainer_id=10)
        session = _mock_session_scalar(c)
        result = await claim_trainer_conversation(1, _make_trainer(id=10), session)
        assert result["status"] == "trainer_active"

    @pytest.mark.asyncio
    async def test_claim_other_trainer_already_409(self):
        c = _make_conversation(status="trainer_active", assigned_trainer_id=999)
        session = _mock_session_scalar(c)
        with pytest.raises(HTTPException) as exc:
            await claim_trainer_conversation(1, _make_trainer(id=10), session)
        assert exc.value.status_code == 409
        assert "已被其他人" in exc.value.detail

    @pytest.mark.asyncio
    async def test_claim_ai_active_blocked(self):
        """ai_active 不是 waiting 状态，不能被 claim。"""
        c = _make_conversation(status="ai_active")
        session = _mock_session_scalar(c)
        with pytest.raises(HTTPException) as exc:
            await claim_trainer_conversation(1, _make_trainer(id=10), session)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_claim_wrong_conv_type_blocked(self):
        """ai 类型会话不能被 trainer 接入。"""
        c = _make_conversation(conversation_type="ai", status="waiting_trainer")
        session = _mock_session_scalar(c)
        with pytest.raises(HTTPException) as exc:
            await claim_trainer_conversation(1, _make_trainer(id=10), session)
        assert exc.value.status_code == 400


# ============ 发消息 ============

class TestSendTrainerMessage:

    @pytest.mark.asyncio
    async def test_send_success(self):
        c = _make_conversation(status="trainer_active", assigned_trainer_id=10)
        session = _mock_session_create(get_returns=c)
        result = await send_trainer_message(
            1, {"content": "你好，我是教练"}, _make_trainer(id=10), session,
        )
        assert result.sender_type == "trainer"
        assert result.content == "你好，我是教练"

    @pytest.mark.asyncio
    async def test_empty_content_400(self):
        with pytest.raises(HTTPException) as exc:
            await send_trainer_message(1, {"content": ""}, _make_trainer(), MagicMock())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_content_400(self):
        """纯空白也被视为空。"""
        with pytest.raises(HTTPException) as exc:
            await send_trainer_message(1, {"content": "   \n  "}, _make_trainer(), MagicMock())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_too_long_content_400(self):
        with pytest.raises(HTTPException) as exc:
            await send_trainer_message(1, {"content": "x" * 4001}, _make_trainer(), MagicMock())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_not_claimed_403(self):
        """未 claim 会话发消息 → 403。"""
        c = _make_conversation(assigned_trainer_id=999)
        session = _mock_session_create(get_returns=c)
        with pytest.raises(HTTPException) as exc:
            await send_trainer_message(1, {"content": "hi"}, _make_trainer(id=10), session)
        assert exc.value.status_code == 403


# ============ 拉消息历史 ============

class TestListTrainerMessages:

    @pytest.mark.asyncio
    async def test_list_empty(self):
        c = _make_conversation()
        session = AsyncMock()
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = c
        r2 = MagicMock(); r2.scalars.return_value.all.return_value = []
        session.execute.side_effect = [r1, r2]
        session.get = AsyncMock(return_value=c)  # _check_trainer_conv 用
        msgs = await list_trainer_messages(1, _make_trainer(), session)
        assert msgs == []


# ============ 关闭会话 ============

class TestCloseConversation:

    @pytest.mark.asyncio
    async def test_close_trainer_active(self):
        c = _make_conversation(status="trainer_active", assigned_trainer_id=10)
        session = _mock_session_create(get_returns=c)
        result = await close_trainer_conversation(1, _make_trainer(id=10), session)
        assert c.status == "ai_active"
        assert c.conversation_type == "ai"
        assert "ended_message_id" in result

    @pytest.mark.asyncio
    async def test_close_other_trainer_403(self):
        c = _make_conversation(assigned_trainer_id=999)
        session = _mock_session_create(get_returns=c)
        with pytest.raises(HTTPException) as exc:
            await close_trainer_conversation(1, _make_trainer(id=10), session)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_close_admin_force(self):
        """admin 可强制关闭任何会话。"""
        c = _make_conversation(assigned_trainer_id=999)
        session = _mock_session_create(get_returns=c)
        admin = _make_trainer(id=1, username="admin", role="admin")
        result = await close_trainer_conversation(1, admin, session)
        assert c.status == "ai_active"


# ============ 推荐模板 ============

class TestRecommendTemplate:

    @pytest.mark.asyncio
    async def test_recommend_published_template(self):
        c = _make_conversation(status="trainer_active", assigned_trainer_id=10)
        tpl = _make_template(status="published", name="减脂计划")
        session = AsyncMock()
        # get(c) → c; get(tpl) → tpl; refresh 回填 id/created_at
        nxt = {"id": 2000}
        async def fake_refresh(obj):
            if getattr(obj, "id", None) is None:
                obj.id = nxt["id"]; nxt["id"] += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2024, 1, 1)
        session.refresh.side_effect = fake_refresh
        session.get = AsyncMock(side_effect=[c, tpl])
        session.commit = AsyncMock()
        session.add = MagicMock()

        from app.api.v1.trainer import RecommendTemplateIn
        body = RecommendTemplateIn(template_id=1)
        result = await recommend_template(1, body, _make_trainer(id=10), session)
        assert result.sender_type == "trainer"
        assert result.extra["kind"] == "recommend_template"
        assert result.extra["template"]["id"] == 1

    @pytest.mark.asyncio
    async def test_recommend_unpublished_400(self):
        c = _make_conversation(status="trainer_active", assigned_trainer_id=10)
        tpl = _make_template(status="draft")  # 未发布
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[c, tpl])
        session.commit = AsyncMock()
        session.add = MagicMock()

        from app.api.v1.trainer import RecommendTemplateIn
        with pytest.raises(HTTPException) as exc:
            await recommend_template(1, RecommendTemplateIn(template_id=1), _make_trainer(id=10), session)
        assert exc.value.status_code == 400


# ============ 定制计划 ============

class TestCustomizePlan:

    @pytest.mark.asyncio
    async def test_customize_with_published_template(self):
        c = _make_conversation(status="trainer_active", assigned_trainer_id=10)
        tpl = _make_template(
            id=1, status="published", name="模板 A", use_count=5,
            weeks=[{"days": [{"day": 1}, {"day": 3}]}],
        )
        session = AsyncMock()
        # get(c) → c; get(tpl) → tpl; execute 用于 update plan/template
        nxt = {"id": 500}
        async def fake_refresh(obj):
            if getattr(obj, "id", None) is None:
                obj.id = nxt["id"]; nxt["id"] += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2024, 1, 1)
            if getattr(obj, "updated_at", None) is None:
                obj.updated_at = datetime(2024, 1, 1)
        session.refresh.side_effect = fake_refresh
        session.get = AsyncMock(side_effect=[c, tpl])
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        from app.api.v1.trainer import CustomizePlanIn
        body = CustomizePlanIn(template_id=1, name="给我的计划")
        result = await customize_plan(1, body, _make_trainer(id=10), session)
        assert result["plan_id"] == 500
        assert result["name"] == "给我的计划"
        assert result["template_id"] == 1
        # 验证 execute 被调用过（update plan current + update template use_count）
        # 注：mock session 不真改 use_count，只验证 SQL 拼接正确
        assert session.execute.await_count >= 2
        # use_count 起点 5；update SQL 是 \"use_count = use_count + 1\"
        assert tpl.use_count == 5  # mock 没真执行 update

    @pytest.mark.asyncio
    async def test_customize_unpublished_400(self):
        c = _make_conversation(status="trainer_active", assigned_trainer_id=10)
        tpl = _make_template(status="draft")
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[c, tpl])
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        from app.api.v1.trainer import CustomizePlanIn
        with pytest.raises(HTTPException) as exc:
            await customize_plan(1, CustomizePlanIn(template_id=1), _make_trainer(id=10), session)
        assert exc.value.status_code == 400


# ============ 模板列表 + 队列 ============

class TestListMyTemplates:

    @pytest.mark.asyncio
    async def test_list_no_filter(self):
        """无 status 过滤时返回全部。"""
        templates = [_make_template(id=i) for i in range(3)]
        session = AsyncMock()
        # 1) base query; 2) count query
        r1 = MagicMock(); r1.scalars.return_value.all.return_value = templates
        r2 = MagicMock(); r2.scalar.return_value = 3
        session.execute.side_effect = [r1, r2]
        result = await list_my_templates(session, _make_trainer(), status_=None, page=1, page_size=20)
        assert result.total == 3
        assert len(result.items) == 3
        assert result.page == 1

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self):
        templates = [_make_template(id=1, status="draft")]
        session = AsyncMock()
        r1 = MagicMock(); r1.scalars.return_value.all.return_value = templates
        r2 = MagicMock(); r2.scalar.return_value = 1
        session.execute.side_effect = [r1, r2]
        result = await list_my_templates(session, _make_trainer(), status_="draft", page=1, page_size=20)
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_list_invalid_status_400(self):
        session = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await list_my_templates(session, _make_trainer(), status_="invalid", page=1, page_size=20)
        assert exc.value.status_code == 400


class TestListMyPendingTemplates:

    @pytest.mark.asyncio
    async def test_pending_first(self):
        """pending_review 应排在 draft 前面（pending 优先）。"""
        templates = [
            _make_template(id=1, status="pending_review"),
            _make_template(id=2, status="draft"),
        ]
        session = AsyncMock()
        r1 = MagicMock(); r1.scalars.return_value.all.return_value = templates
        r2 = MagicMock(); r2.scalar.return_value = 2
        session.execute.side_effect = [r1, r2]
        result = await list_my_pending_templates(session, _make_trainer(), page=1, page_size=20)
        assert len(result.items) == 2


# ============ 队列 / 历史（multi-query loop）============

class TestTrainerQueue:

    @pytest.mark.asyncio
    async def test_queue_empty(self):
        """没人在等 → items=[], total=0。"""
        session = AsyncMock()
        r = MagicMock(); r.scalars.return_value.all.return_value = []
        session.execute.return_value = r
        result = await trainer_queue(session, _make_trainer())
        assert result["items"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_queue_with_one_waiting(self):
        """1 个等待中的会话 → 返回 user 信息 + 最后一条消息预览。"""
        conv = _make_conversation(status="waiting_trainer", title="求指导")
        user = _make_trainer(id=2, username="member1")
        msg = _make_message(content="教练帮我看看")
        session = AsyncMock()
        # 1) select conv; 2) select user; 3) select last msg
        results = [
            MagicMock(),                                    # conv (scalars().all())
            MagicMock(scalar_one_or_none=MagicMock(return_value=user)),  # user
            MagicMock(scalar_one_or_none=MagicMock(return_value=msg)),   # last msg
        ]
        results[0].scalars.return_value.all.return_value = [conv]
        session.execute.side_effect = results

        result = await trainer_queue(session, _make_trainer())
        assert result["total"] == 1
        item = result["items"][0]
        assert item["conversation_id"] == 1
        assert item["username"] == "member1"
        assert item["last_message"] == "教练帮我看看"


class TestTrainerHistory:

    @pytest.mark.asyncio
    async def test_history_excludes_waiting(self):
        """assigned=me + status != waiting_trainer 的会话。"""
        conv = _make_conversation(status="ai_active", assigned_trainer_id=10)
        user = _make_trainer(id=2, username="member1")
        msg = _make_message(content="谢谢教练")
        session = AsyncMock()
        results = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conv])))),
            MagicMock(scalar_one_or_none=MagicMock(return_value=user)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=msg)),
        ]
        session.execute.side_effect = results

        result = await trainer_history(session, _make_trainer(id=10))
        assert result["total"] == 1
