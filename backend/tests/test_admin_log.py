"""admin_log.py 单测（mocked AsyncSession）。

覆盖：
- GET /admin/operation-logs              列出日志（无筛选 / 多条件 / 空结果）
- GET /admin/operation-logs/actions      distinct action + count
- GET /admin/operation-logs/target-types distinct target_type + count（自动过滤 NULL）
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.admin_log import (
    list_actions,
    list_operation_logs,
    list_target_types,
)


# ============ Helpers ============

def _make_admin(id=1, username="admin", role="admin"):
    return SimpleNamespace(
        id=id, username=username, role=role,
        status=0, is_deleted=False, is_banned=False, is_locked=False,
        nickname=username, avatar_url=None,
    )


def _make_log(
    id=1, operator_id=1, operator_name="admin", operator_role="admin",
    action="ban_user", target_type="user", target_id="5",
    summary="封禁用户 5", details=None, ip="127.0.0.1",
    created_at=None,
):
    return SimpleNamespace(
        id=id, operator_id=operator_id, operator_name=operator_name,
        operator_role=operator_role, action=action, target_type=target_type,
        target_id=target_id, summary=summary, details=details, ip=ip,
        created_at=created_at or datetime(2024, 1, 1),
    )


def _mock_session_two_queries(scalars_items, count_value):
    """list_operation_logs 用：1) count → .scalar(); 2) list → .scalars().all()."""
    session = AsyncMock()
    r1 = MagicMock(); r1.scalar.return_value = count_value
    r2 = MagicMock(); r2.scalars.return_value.all.return_value = scalars_items
    session.execute.side_effect = [r1, r2]
    return session


def _mock_session_all(items):
    """list_actions / list_target_types 用：session.execute().all() = items."""
    session = AsyncMock()
    r = MagicMock(); r.all.return_value = items
    session.execute.return_value = r
    return session


# ============ 列出操作日志 ============

class TestListLogs:

    @pytest.mark.asyncio
    async def test_no_filter_returns_all(self):
        """无任何筛选 → 返回全部日志 + total。"""
        logs = [_make_log(id=i) for i in range(3)]
        session = _mock_session_two_queries(logs, 3)
        result = await list_operation_logs(
            _make_admin(), session, limit=50, offset=0,
        )
        assert result.total == 3
        assert len(result.items) == 3
        assert result.limit == 50
        assert result.offset == 0
        assert result.items[0].action == "ban_user"

    @pytest.mark.asyncio
    async def test_multi_filter(self):
        """多条件筛选（action/target_type/keyword + 时间区间）。"""
        logs = [_make_log(id=10, action="ban_user", target_type="user", summary="封禁测试用户")]
        session = _mock_session_two_queries(logs, 1)
        result = await list_operation_logs(
            _make_admin(),
            session,
            action="ban_user",
            target_type="user",
            keyword="测试",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 12, 31),
            limit=10,
            offset=0,
        )
        assert result.total == 1
        assert result.items[0].action == "ban_user"
        assert result.items[0].target_type == "user"
        assert result.limit == 10

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """无匹配 → items=[], total=0。"""
        session = _mock_session_two_queries([], 0)
        result = await list_operation_logs(
            _make_admin(), session, action="nonexistent", limit=50, offset=0,
        )
        assert result.total == 0
        assert result.items == []


# ============ Action 下拉项 ============

class TestListActions:

    @pytest.mark.asyncio
    async def test_actions_with_counts(self):
        """返回 (action, count) 元组列表。"""
        items = [("ban_user", 12), ("unban_user", 5), ("update_config", 2)]
        session = _mock_session_all(items)
        result = await list_actions(_make_admin(), session)
        assert len(result) == 3
        assert result[0].action == "ban_user"
        assert result[0].count == 12
        assert result[2].count == 2

    @pytest.mark.asyncio
    async def test_actions_empty(self):
        """没有日志 → 空列表。"""
        session = _mock_session_all([])
        result = await list_actions(_make_admin(), session)
        assert result == []


# ============ Target Type 下拉项 ============

class TestListTargetTypes:

    @pytest.mark.asyncio
    async def test_target_types_with_counts(self):
        """返回 (target_type, count) 元组列表（NULL 已被 SQL 过滤）。"""
        items = [("user", 8), ("template", 3), ("config", 1)]
        session = _mock_session_all(items)
        result = await list_target_types(_make_admin(), session)
        assert len(result) == 3
        assert result[0].target_type == "user"
        assert result[0].count == 8
        assert result[2].target_type == "config"

    @pytest.mark.asyncio
    async def test_target_types_empty(self):
        """全是 NULL → 空列表。"""
        session = _mock_session_all([])
        result = await list_target_types(_make_admin(), session)
        assert result == []