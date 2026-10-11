"""plans.py 路由单测（mocked AsyncSession）。"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.plans import (
    _utcnow_naive,
    create_plan,
    delete_plan,
    get_plan,
    list_my_plans,
    list_training_records,
    set_current_plan,
    submit_training_record,
    update_plan,
)
from app.schemas.plan import (
    PlanCreate,
    PlanDay,
    PlanUpdate,
    PlanWeek,
    PlanExerciseItem,
    TrainingRecordIn,
)


def _make_user(id=1, username="tester", role="user"):
    return SimpleNamespace(
        id=id, username=username, role=role,
        status=0, is_deleted=False, is_banned=False, is_locked=False,
    )


def _make_plan(
    id=1, user_id=1, name="My Plan", goal="muscle_gain",
    weeks=None, days_per_week=3, equipment=None,
    is_current=1,
    created_at=None, updated_at=None,
):
    return SimpleNamespace(
        id=id, user_id=user_id, name=name, goal=goal,
        weeks=weeks or [], days_per_week=days_per_week,
        equipment=equipment or [],
        is_current=is_current,
        created_at=created_at or datetime(2024, 1, 1),
        updated_at=updated_at or datetime(2024, 1, 1),
    )


def _make_exercise(id="0001", image="/static/images/0001.jpg", gif_url="/static/videos/0001.gif"):
    return SimpleNamespace(id=id, image=image, gif_url=gif_url)


def _mock_session_single(scalar):
    """session.execute() 返回带 scalar_one_or_none() 的对象。"""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    session.execute.return_value = result
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    return session


def _mock_session_create(_next_id: int = 1000):
    """create_plan 专用：refresh 回填 id/created_at/updated_at。"""
    session = AsyncMock()
    counter = {"id": _next_id}

    async def fake_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = counter["id"]
            counter["id"] += 1
        now = datetime(2024, 1, 1)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        if getattr(obj, "recorded_at", None) is None:
            obj.recorded_at = now
    session.refresh.side_effect = fake_refresh
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


def _mock_session_scalars(items):
    """session.execute() 返回 .scalars().all() == items 的链。"""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    session.execute.return_value = result
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _mock_session_multi_result(*result_list):
    """session.execute() 按调用顺序返回不同 result（用于多次 execute 的路由）。"""
    session = AsyncMock()
    results = []
    for r in result_list:
        m = MagicMock()
        if isinstance(r, list):
            m.scalars.return_value.all.return_value = r
        else:
            m.scalar_one_or_none.return_value = r
        results.append(m)
    session.execute.side_effect = results
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return session


def _sample_plan_body(name="Test Plan", goal="muscle_gain"):
    """构造一个合法的 PlanCreate 请求体。"""
    return PlanCreate(
        name=name,
        goal=goal,
        weeks=[
            PlanWeek(
                week=1,
                days=[
                    PlanDay(
                        day=1, name="推",
                        exercises=[
                            PlanExerciseItem(exercise_id="0001", sets=3, reps=10),
                            PlanExerciseItem(exercise_id="0002", sets=3, reps=8),
                        ],
                    ),
                    PlanDay(
                        day=3, name="腿",
                        exercises=[PlanExerciseItem(exercise_id="0030", sets=4, reps=12)],
                    ),
                ],
            ),
        ],
        days_per_week=2,
        equipment=["barbell"],
    )


# ============ 创建计划 ============

class TestCreatePlan:

    @pytest.mark.asyncio
    async def test_create_success(self):
        body = _sample_plan_body()
        session = _mock_session_create()  # refresh 回填 id/created_at
        result = await create_plan(body, _make_user(), session)
        assert result.name == "Test Plan"
        assert result.goal == "muscle_gain"
        assert result.days_per_week == 2
        assert result.id is not None  # refresh 后回填
        assert result.created_at is not None


# ============ 获取详情 ============

class TestGetPlan:

    @pytest.mark.asyncio
    async def test_get_success(self):
        plan = _make_plan(id=10, name="Found")
        session = _mock_session_single(plan)
        result = await get_plan(10, _make_user(), session)
        assert result.name == "Found"
        assert result.id == 10

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        session = _mock_session_single(None)
        with pytest.raises(HTTPException) as exc:
            await get_plan(999, _make_user(), session)
        assert exc.value.status_code == 404


# ============ 更新计划 ============

class TestUpdatePlan:

    @pytest.mark.asyncio
    async def test_update_name(self):
        plan = _make_plan()
        # 两次 execute：① find plan ② clear other is_current（update，返回 rowcount）
        session = AsyncMock()
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = plan
        r2 = MagicMock()  # update 不需要返回值
        session.execute.side_effect = [r1, r2]
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        result = await update_plan(1, PlanUpdate(name="New Name"), _make_user(), session)
        assert result.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_partial_no_weeks(self):
        """不传 weeks 时应保留原值。"""
        plan = _make_plan()
        session = AsyncMock()
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = plan
        r2 = MagicMock()
        session.execute.side_effect = [r1, r2]
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        result = await update_plan(1, PlanUpdate(days_per_week=4), _make_user(), session)
        assert result.days_per_week == 4

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        session = _mock_session_multi_result(None)
        with pytest.raises(HTTPException) as exc:
            await update_plan(999, PlanUpdate(name="x"), _make_user(), session)
        assert exc.value.status_code == 404


# ============ 删除计划 ============

class TestDeletePlan:

    @pytest.mark.asyncio
    async def test_delete_success(self):
        plan = _make_plan()
        session = _mock_session_multi_result(plan)
        result = await delete_plan(1, _make_user(), session)
        assert result is None
        session.delete.assert_awaited_once_with(plan)

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        session = _mock_session_multi_result(None)
        with pytest.raises(HTTPException) as exc:
            await delete_plan(999, _make_user(), session)
        assert exc.value.status_code == 404


# ============ 列表（含进度统计 + 缩略图）============

class TestListPlans:

    @pytest.mark.asyncio
    async def test_list_empty(self):
        """用户无计划时返回空列表。"""
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute.return_value = result
        items = await list_my_plans(_make_user(), session)
        assert items == []

    @pytest.mark.asyncio
    async def test_list_with_plan_no_records(self):
        """有计划但没打卡 → progress_pct=0, completed_days=0。"""
        plan = _make_plan(
            weeks=[
                {"days": [
                    {"day": 1, "exercises": [{"exercise_id": "0001"}]},
                    {"day": 3, "exercises": [{"exercise_id": "0002"}]},
                ]}
            ]
        )
        # 第一次 execute: plans 列表；第二次 execute (records): 空；第三次 execute (exercise media): 可省
        session = AsyncMock()
        r1 = MagicMock(); r1.scalars.return_value.all.return_value = [plan]
        r2 = MagicMock(); r2.all.return_value = []  # 无 records
        r3 = MagicMock(); r3.all.return_value = []
        session.execute.side_effect = [r1, r2, r3]
        items = await list_my_plans(_make_user(), session)
        assert len(items) == 1
        item = items[0]
        assert item.total_days == 2
        assert item.completed_days == 0
        assert item.progress_pct == 0.0

    @pytest.mark.asyncio
    async def test_progress_pct_calculation(self):
        """3 天计划，已完成 2 天 → 66.7%。"""
        plan = _make_plan(
            weeks=[
                {"days": [
                    {"day": 1, "exercises": [{"exercise_id": "0001"}]},
                    {"day": 2, "exercises": [{"exercise_id": "0002"}]},
                    {"day": 3, "exercises": [{"exercise_id": "0003"}]},
                ]}
            ]
        )
        session = AsyncMock()
        r1 = MagicMock(); r1.scalars.return_value.all.return_value = [plan]
        # records: 已完成 2 个不同 (week, day)
        r2 = MagicMock()
        r2.all.return_value = [
            SimpleNamespace(plan_week=1, plan_day=1),
            SimpleNamespace(plan_week=1, plan_day=2),
        ]
        r3 = MagicMock(); r3.all.return_value = []
        session.execute.side_effect = [r1, r2, r3]
        items = await list_my_plans(_make_user(), session)
        assert items[0].completed_days == 2
        assert items[0].progress_pct == round(2/3 * 100, 1)

    @pytest.mark.asyncio
    async def test_progress_distinct_same_day_counted_once(self):
        """同一 (week, day) 多次打卡只算一天。"""
        plan = _make_plan(
            weeks=[{"days": [{"day": 1, "exercises": [{"exercise_id": "0001"}]}]}]
        )
        session = AsyncMock()
        r1 = MagicMock(); r1.scalars.return_value.all.return_value = [plan]
        r2 = MagicMock()
        r2.all.return_value = [
            SimpleNamespace(plan_week=1, plan_day=1),  # 3 次同一天
            SimpleNamespace(plan_week=1, plan_day=1),
            SimpleNamespace(plan_week=1, plan_day=1),
        ]
        r3 = MagicMock(); r3.all.return_value = []
        session.execute.side_effect = [r1, r2, r3]
        items = await list_my_plans(_make_user(), session)
        assert items[0].completed_days == 1
        assert items[0].progress_pct == 100.0

    @pytest.mark.asyncio
    async def test_thumbnails_first_6_exercises(self):
        """缩略图只取首周前 6 个动作的媒体 URL。"""
        plan = _make_plan(
            weeks=[
                {"days": [
                    {"day": 1, "exercises": [
                        {"exercise_id": f"{i:04d}"} for i in range(1, 11)  # 10 个动作
                    ]},
                ]}
            ]
        )
        # 第一次 execute: plans
        r1 = MagicMock(); r1.scalars.return_value.all.return_value = [plan]
        # 第二次: records（空）
        r2 = MagicMock(); r2.all.return_value = []
        # 第三次: exercise media（10 个）
        r3 = MagicMock()
        r3.all.return_value = [_make_exercise(id=f"{i:04d}") for i in range(1, 11)]
        session = AsyncMock()
        session.execute.side_effect = [r1, r2, r3]
        items = await list_my_plans(_make_user(), session)
        assert len(items[0].thumbnails) == 6  # 截断到 6


# ============ 提交打卡 ============

class TestSubmitRecord:

    @pytest.mark.asyncio
    async def test_submit_success(self):
        plan = _make_plan()
        session = _mock_session_create()
        body = TrainingRecordIn(
            plan_id=1, exercise_id="0001",
            plan_week=1, plan_day=1,
            completed_sets=[True, True, True],
        )
        result = await submit_training_record(1, body, _make_user(), session)
        assert result.completed_sets == [True, True, True]
        assert result.id is not None

    @pytest.mark.asyncio
    async def test_submit_url_body_mismatch(self):
        """URL plan_id ≠ body plan_id 应 400。"""
        body = TrainingRecordIn(
            plan_id=999, exercise_id="0001",
            plan_week=1, plan_day=1,
            completed_sets=[True],
        )
        session = _mock_session_single(None)
        with pytest.raises(HTTPException) as exc:
            await submit_training_record(1, body, _make_user(), session)
        assert exc.value.status_code == 400
        assert "不一致" in exc.value.detail

    @pytest.mark.asyncio
    async def test_submit_plan_not_found(self):
        body = TrainingRecordIn(
            plan_id=999, exercise_id="0001",
            plan_week=1, plan_day=1,
            completed_sets=[True],
        )
        session = _mock_session_single(None)
        with pytest.raises(HTTPException) as exc:
            await submit_training_record(999, body, _make_user(), session)
        assert exc.value.status_code == 404


# ============ 列出打卡 ============

class TestListRecords:

    @pytest.mark.asyncio
    async def test_list_no_filter(self):
        records = [
            SimpleNamespace(
                id=1, user_id=1, plan_id=1, exercise_id="0001",
                plan_week=1, plan_day=1, completed_sets=[True],
                recorded_at=datetime(2024, 1, 1),
            ),
            SimpleNamespace(
                id=2, user_id=1, plan_id=1, exercise_id="0002",
                plan_week=1, plan_day=2, completed_sets=[True, False],
                recorded_at=datetime(2024, 1, 2),
            ),
        ]
        session = AsyncMock()
        result = MagicMock(); result.scalars.return_value.all.return_value = records
        session.execute.return_value = result
        # 真实调用：传入完整 kwargs（无 week/day 时不传）
        items = await list_training_records(plan_id=1, current_user=_make_user(), session=session)
        assert len(items) == 2


class TestSetCurrent:

    @pytest.mark.asyncio
    async def test_set_current_success(self):
        plan = _make_plan(is_current=0)
        # 2 次 execute：① find plan ② clear other current
        session = AsyncMock()
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = plan
        r2 = MagicMock()
        session.execute.side_effect = [r1, r2]
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        result = await set_current_plan(1, _make_user(), session)
        assert result.is_current == 1

    @pytest.mark.asyncio
    async def test_set_current_not_found(self):
        session = _mock_session_multi_result(None)
        with pytest.raises(HTTPException) as exc:
            await set_current_plan(999, _make_user(), session)
        assert exc.value.status_code == 404


# ============ 边界 ============

class TestUtcnowNaive:

    def test_returns_naive(self):
        t = _utcnow_naive()
        assert t.tzinfo is None
        assert isinstance(t, datetime)
