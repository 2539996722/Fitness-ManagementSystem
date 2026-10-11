"""MySQL 集成测试（标记 integration，自动 skip 如果 MySQL 不可达）。

需要：
- 本地 MySQL 在 localhost:3306 运行
- 用户名密码与 .env 中的 MYSQL_DSN 一致（默认 root / Lb@403706）
- 测库 fithub_test 会被自动创建（CREATE DATABASE IF NOT EXISTS）
- 测试结束回滚（不污染 fithub_test）
"""
from __future__ import annotations

from datetime import datetime

import pytest

# 全部测试默认需要 integration marker；缺 marker 不会自动加，需要显式标
pytestmark = pytest.mark.integration


class TestMysqlConnectivity:
    """基础连通性检查。"""

    def test_mysql_reachable(self, mysql_available):
        assert mysql_available is True, "本机 MySQL 未运行，请先 docker run / brew services start mysql"

    def test_test_database_created(self, integration_session):
        """fixture 自身验证 fithub_test 库 + 表已创建。"""
        # 能拿到 session 就说明连上了，schema 也建好了
        assert integration_session is not None
        assert integration_session.is_active


class TestPlanCrudIntegration:
    """Plan 模型的真实 DB 写入 + 回滚隔离。"""

    @pytest.mark.asyncio
    async def test_create_and_query_plan(self, integration_session):
        from app.db.models import Plan, User

        # 创建测试用户
        user = User(username="integration_tester", role="user", status=0)
        user.password_hash = "fake_hash"
        integration_session.add(user)
        await integration_session.flush()
        await integration_session.refresh(user)  # 显式 refresh 加载 id

        # 创建 plan
        plan = Plan(
            user_id=user.id,
            name="Integration Test Plan",
            goal="muscle_gain",
            weeks=[{"week": 1, "days": [{"day": 1, "exercises": [{"exercise_id": "0001"}]}]}],
            days_per_week=3,
            is_current=1,
        )
        integration_session.add(plan)
        await integration_session.flush()
        await integration_session.refresh(plan)

        assert plan.id is not None
        assert plan.created_at is not None

    @pytest.mark.asyncio
    async def test_unique_user_username(self, integration_session):
        from app.db.models import User
        from sqlalchemy.exc import IntegrityError

        u1 = User(username="dup_user", role="user", status=0, password_hash="x")
        integration_session.add(u1)
        await integration_session.flush()
        await integration_session.refresh(u1)

        u2 = User(username="dup_user", role="user", status=0, password_hash="y")
        integration_session.add(u2)
        with pytest.raises(IntegrityError):
            await integration_session.flush()


class TestAiCallLogIntegration:
    """ai_call_logs 表的基本约束。"""

    @pytest.mark.asyncio
    async def test_create_call_log(self, integration_session):
        from app.db.models import AiCallLog

        log = AiCallLog(
            user_id=None,
            conversation_id=None,
            intent="qa",
            call_type="chat",
            model="gpt-4o-mini",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_cny=0.001,
            latency_ms=500,
        )
        integration_session.add(log)
        await integration_session.flush()
        await integration_session.refresh(log)
        assert log.id is not None
        assert log.created_at is not None
