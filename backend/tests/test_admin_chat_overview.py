"""chat-overview 端点单测（admin_dashboard.chat_overview）。

覆盖：
- 历史 + 实时 双视图结构正确
- 今日 totals 聚合正确
- 近 N 天趋势（含中间空日期补 0）
- by_intent token 分布
- top_models（按 call 数倒序，最多 5 个）
- 空 DB 时所有值都 = 0
- days 参数从 query 透传
- realtime 字段来自 chat_metrics（mock snapshot）
- null intent / null model 容错
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestChatOverviewHappyPath:
    """完整数据路径：DB 有 ai_call_logs + chat_metrics 有流。"""

    @pytest.mark.asyncio
    async def test_returns_history_and_realtime_blocks(self):
        from app.api.v1.admin_dashboard import chat_overview
        from app.services import chat_metrics

        # 动态日期：基于 today - N 推算，避免历史日期跑出 trend 窗口
        now_date = datetime.now().date()
        d_minus_2 = (now_date - timedelta(days=2)).isoformat()  # trend 范围内
        d_minus_0 = now_date.isoformat()  # 当天

        # mock session（按路由调用顺序返回结果）
        session = AsyncMock()

        # 1) today_calls count
        r1 = MagicMock(); r1.scalar.return_value = 12
        # 2) today tokens + cost
        r2 = MagicMock(); r2.first.return_value = (15000, 0.012345)
        # 3) daily trend rows：两天有数据，中间一天无数据补 0
        r3 = MagicMock(); r3.all.return_value = [
            (d_minus_2, 5, 5000, 0.005),
            (d_minus_0, 3, 3000, 0.003),
        ]
        # 4) by_intent rows
        r4 = MagicMock(); r4.all.return_value = [
            ('qa', 8000),
            ('plan', 2000),
            (None, 500),  # null intent → 'unknown'
        ]
        # 5) top_models rows
        r5 = MagicMock(); r5.all.return_value = [
            ('MiniMax-Text-01', 8),
            ('embo-01', 4),
        ]
        session.execute.side_effect = [r1, r2, r3, r4, r5]

        # 注入 realtime 数据
        metrics = chat_metrics.chat_metrics
        sid = metrics.stream_started(user_id=1, conversation_id=42, intent="qa")
        metrics.stream_first_byte(stream_id=sid, model="MiniMax-Text-01")
        metrics.stream_stopped(stream_id=sid)

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=7)

        # top-level 结构
        assert result["days"] == 7
        assert "history" in result
        assert "realtime" in result

        # history.today
        today = result["history"]["today"]
        assert today["calls"] == 12
        assert today["total_tokens"] == 15000
        assert today["cost_cny"] == 0.012345

        # history.trend：7 天，每天都有 slot（无数据的日期 = 0）
        trend = result["history"]["trend"]
        assert len(trend) == 7
        for i, point in enumerate(trend):
            assert "date" in point
            assert "calls" in point
            assert "tokens" in point
            assert "cost" in point
        # 验证 mock 的两个日期非空
        by_date = {p["date"]: p for p in trend}
        assert by_date[d_minus_2]["calls"] == 5
        assert by_date[d_minus_2]["tokens"] == 5000
        assert by_date[d_minus_2]["cost"] == 0.005
        assert by_date[d_minus_0]["calls"] == 3
        # 中间没数据的日期补 0
        d_minus_1 = (now_date - timedelta(days=1)).isoformat()
        assert by_date[d_minus_1]["calls"] == 0
        assert by_date[d_minus_1]["cost"] == 0.0

        # history.by_intent：null intent → 'unknown'
        by_intent = {x["intent"]: x["tokens"] for x in result["history"]["by_intent"]}
        assert by_intent == {"qa": 8000, "plan": 2000, "unknown": 500}

        # history.top_models：按调用数倒序
        top_models = result["history"]["top_models"]
        assert len(top_models) == 2
        assert top_models[0] == {"model": "MiniMax-Text-01", "calls": 8}
        assert top_models[1] == {"model": "embo-01", "calls": 4}

        # realtime：来自 chat_metrics.snapshot()，至少有 active_streams=0、today 等
        realtime = result["realtime"]
        assert "active_streams" in realtime
        assert "today" in realtime
        assert realtime["today"]["total_streams"] >= 1


class TestChatOverviewEmptyDB:
    """DB 空时所有数 = 0，但仍返回完整结构。"""

    @pytest.mark.asyncio
    async def test_zero_history_full_realtime(self):
        from app.api.v1.admin_dashboard import chat_overview
        from app.services import chat_metrics

        session = AsyncMock()
        # 所有 select 都返 0 / 空
        r1 = MagicMock(); r1.scalar.return_value = 0
        r2 = MagicMock(); r2.first.return_value = (0, 0.0)
        r3 = MagicMock(); r3.all.return_value = []
        r4 = MagicMock(); r4.all.return_value = []
        r5 = MagicMock(); r5.all.return_value = []
        session.execute.side_effect = [r1, r2, r3, r4, r5]

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=7)

        assert result["history"]["today"]["calls"] == 0
        assert result["history"]["today"]["total_tokens"] == 0
        assert result["history"]["today"]["cost_cny"] == 0.0
        # 空 DB 时 trend 也是 N 天零值点（路由按 days 长度生成）
        assert len(result["history"]["trend"]) == 7
        assert all(p["calls"] == 0 and p["tokens"] == 0 and p["cost"] == 0.0 for p in result["history"]["trend"])
        assert result["history"]["by_intent"] == []
        assert result["history"]["top_models"] == []


class TestChatOverviewDaysParam:
    """days 参数透传到 trend 长度 + start_date 计算。"""

    @pytest.mark.asyncio
    async def test_days_1_trend_has_one_point(self):
        from app.api.v1.admin_dashboard import chat_overview

        session = AsyncMock()
        r1 = MagicMock(); r1.scalar.return_value = 0
        r2 = MagicMock(); r2.first.return_value = (0, 0.0)
        r3 = MagicMock(); r3.all.return_value = []
        r4 = MagicMock(); r4.all.return_value = []
        r5 = MagicMock(); r5.all.return_value = []
        session.execute.side_effect = [r1, r2, r3, r4, r5]

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=1)

        assert result["days"] == 1
        assert len(result["history"]["trend"]) == 1

    @pytest.mark.asyncio
    async def test_days_30_trend_has_30_points(self):
        from app.api.v1.admin_dashboard import chat_overview

        session = AsyncMock()
        # 简单 5 个 mock result
        r1 = MagicMock(); r1.scalar.return_value = 0
        r2 = MagicMock(); r2.first.return_value = (0, 0.0)
        r3 = MagicMock(); r3.all.return_value = []
        r4 = MagicMock(); r4.all.return_value = []
        r5 = MagicMock(); r5.all.return_value = []
        session.execute.side_effect = [r1, r2, r3, r4, r5]

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=30)
        assert result["days"] == 30
        assert len(result["history"]["trend"]) == 30

        # 30 天 trend 应连续（无 gap）
        dates = [p["date"] for p in result["history"]["trend"]]
        assert len(dates) == 30
        # 第一天是 days-1 天前（30-1=29 天前），最后一天是今天
        first = datetime.fromisoformat(dates[0])
        last = datetime.fromisoformat(dates[-1])
        assert (last.date() - first.date()).days == 29


class TestChatOverviewCostRounding:
    """cost_cny 保留 6 位小数。"""

    @pytest.mark.asyncio
    async def test_cost_rounded_to_6_decimals(self):
        from app.api.v1.admin_dashboard import chat_overview

        session = AsyncMock()
        r1 = MagicMock(); r1.scalar.return_value = 1
        # cost = 0.123456789012 → round 6 位 = 0.123457
        r2 = MagicMock(); r2.first.return_value = (100, 0.123456789012)
        r3 = MagicMock(); r3.all.return_value = []
        r4 = MagicMock(); r4.all.return_value = []
        r5 = MagicMock(); r5.all.return_value = []
        session.execute.side_effect = [r1, r2, r3, r4, r5]

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=7)

        assert result["history"]["today"]["cost_cny"] == 0.123457

    @pytest.mark.asyncio
    async def test_zero_cost_stays_zero(self):
        from app.api.v1.admin_dashboard import chat_overview

        session = AsyncMock()
        r1 = MagicMock(); r1.scalar.return_value = 0
        r2 = MagicMock(); r2.first.return_value = (0, 0.0)
        for _ in range(3):
            r = MagicMock(); r.all.return_value = []
        session.execute.side_effect = [r1, r2, r, r, r]

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=7)
        assert result["history"]["today"]["cost_cny"] == 0.0


class TestChatOverviewTopModelsNull:
    """model 为 None 的 ai_call_log 不进 top_models。"""

    @pytest.mark.asyncio
    async def test_null_model_excluded(self):
        from app.api.v1.admin_dashboard import chat_overview

        session = AsyncMock()
        r1 = MagicMock(); r1.scalar.return_value = 0
        r2 = MagicMock(); r2.first.return_value = (0, 0.0)
        r3 = MagicMock(); r3.all.return_value = []
        r4 = MagicMock(); r4.all.return_value = []
        # top_models query: where AiCallLog.model.isnot(None) 已经过滤掉 None
        # 测试时只返非 None 的行
        r5 = MagicMock(); r5.all.return_value = [
            ('valid-model', 5),
        ]
        session.execute.side_effect = [r1, r2, r3, r4, r5]

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=7)
        assert result["history"]["top_models"] == [{"model": "valid-model", "calls": 5}]


class TestChatOverviewRealtimeCall:
    """验证 realtime 是 chat_metrics.snapshot() 的当前快照（不是缓存）。"""

    @pytest.mark.asyncio
    async def test_realtime_reflects_current_metrics(self):
        from app.api.v1.admin_dashboard import chat_overview
        from app.services import chat_metrics

        session = AsyncMock()
        r1 = MagicMock(); r1.scalar.return_value = 0
        r2 = MagicMock(); r2.first.return_value = (0, 0.0)
        for _ in range(3):
            r = MagicMock(); r.all.return_value = []
        session.execute.side_effect = [r1, r2, r, r, r]

        # 调用前 snapshot 是空的
        snap_before = chat_metrics.chat_metrics.snapshot()
        assert snap_before["active_streams"] == 0

        # 启动一个流
        sid = chat_metrics.chat_metrics.stream_started(
            user_id=99, conversation_id=999, intent="qa"
        )

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=7)

        # realtime 应反映刚才的流（实时调用）
        assert result["realtime"]["active_streams"] == 1
        assert result["realtime"]["today"]["by_intent"]["qa"] >= 1

        # 清理
        chat_metrics.chat_metrics.stream_stopped(stream_id=sid)


class TestChatOverviewTrendDateMath:
    """trend 日期从今天回推 N 天，连续无 gap。"""

    @pytest.mark.asyncio
    async def test_30day_trend_dates_continous(self):
        from app.api.v1.admin_dashboard import chat_overview

        session = AsyncMock()
        r1 = MagicMock(); r1.scalar.return_value = 0
        r2 = MagicMock(); r2.first.return_value = (0, 0.0)
        # 只在某一天有数据
        today_iso = datetime.utcnow().date().isoformat()
        r3 = MagicMock(); r3.all.return_value = [(today_iso, 5, 1000, 0.001)]
        r4 = MagicMock(); r4.all.return_value = []
        r5 = MagicMock(); r5.all.return_value = []
        session.execute.side_effect = [r1, r2, r3, r4, r5]

        user = SimpleNamespace(id=1, role="admin")
        result = await chat_overview(_user=user, session=session, days=30)
        trend = result["history"]["trend"]
        # 验证日期连续
        dates = [datetime.fromisoformat(p["date"]).date() for p in trend]
        for i in range(1, len(dates)):
            assert (dates[i] - dates[i-1]).days == 1

        # 今天有数据，其他都是 0
        for p in trend:
            if p["date"] == today_iso:
                assert p["calls"] == 5
                assert p["cost"] == 0.001
            else:
                assert p["calls"] == 0


class TestChatOverviewTrainerRole:
    """trainer 角色也能访问（不只 admin）。"""

    @pytest.mark.asyncio
    async def test_trainer_user_passes_role_check(self):
        """端点用 require_role('admin', 'trainer')，trainer 应能通过。

        这里只验证角色参数正确传入，不实际测 require_role（那个在 FastAPI 层）。
        """
        from app.api.v1.admin_dashboard import chat_overview

        session = AsyncMock()
        results = [
            MagicMock(scalar=MagicMock(return_value=0)),
            MagicMock(first=MagicMock(return_value=(0, 0.0))),
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(all=MagicMock(return_value=[])),
        ]
        session.execute.side_effect = results

        trainer = SimpleNamespace(id=2, role="trainer")
        result = await chat_overview(_user=trainer, session=session, days=7)

        # 端点对 trainer 角色也应能调用（role check 在依赖层）
        assert result["days"] == 7
        assert "history" in result
        assert "realtime" in result
