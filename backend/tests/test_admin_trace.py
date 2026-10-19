"""admin_trace.py 单测（mocked AsyncSession）。

覆盖：
- GET /admin/traces              按 request_id 聚合的轨迹列表（status 推断、stage 补全、分页、空结果）
- GET /admin/traces/{request_id} 单次请求的完整 span 时间线（overall status 计算）
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.admin_trace import get_trace, list_traces


# ============ Helpers ============

class _Row:
    """模拟 SQLAlchemy Row 的聚合行：同时支持 r.attr 和 r[0] 访问。"""

    def __init__(self, pairs):
        self._keys = []
        for k, v in pairs:
            setattr(self, k, v)
            self._keys.append(k)

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return getattr(self, self._keys[idx])
        return getattr(self, idx)


def _make_admin(id=1, username="admin", role="admin"):
    return SimpleNamespace(
        id=id, username=username, role=role,
        status=0, is_deleted=False, is_banned=False, is_locked=False,
    )


def _make_row(
    request_id="req-001",
    conversation_id=10,
    user_id=2,
    intent="qa",
    span_count=3,
    total_latency=200,
    total_tokens=100,
    err_count=0,
    started_at=None,
    last_span_at=None,
):
    """模拟 trace_spans GROUP BY 之后的聚合行。

    用 `_Row` 而非 SimpleNamespace，因为路由用 `r[0]` 切片拿 request_id。
    """
    keys = (
        "request_id", "conversation_id", "user_id", "intent",
        "span_count", "total_latency", "total_tokens", "err_count",
        "started_at", "last_span_at",
    )
    vals = (
        request_id, conversation_id, user_id, intent,
        span_count, total_latency, total_tokens, err_count,
        started_at or datetime(2024, 1, 1, 10, 0),
        last_span_at or datetime(2024, 1, 1, 10, 5),
    )
    return _Row(zip(keys, vals))


def _make_span(
    id=1,
    request_id="req-001",
    conversation_id=10,
    user_id=2,
    stage="llm",
    intent="qa",
    status="success",
    latency_ms=100,
    prompt_tokens=50,
    completion_tokens=30,
    total_tokens=80,
    input_preview="hi",
    output_preview="hello",
    meta=None,
    error_message=None,
    created_at=None,
):
    return SimpleNamespace(
        id=id,
        request_id=request_id,
        conversation_id=conversation_id,
        user_id=user_id,
        stage=stage,
        intent=intent,
        status=status,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        input_preview=input_preview,
        output_preview=output_preview,
        meta=meta or {},
        error_message=error_message,
        created_at=created_at or datetime(2024, 1, 1, 10, 0),
    )


def _multi(*results):
    """session.execute.side_effect 链：依次返回每个 mock。"""
    session = AsyncMock()
    session.execute.side_effect = list(results)
    return session


# ============ GET /admin/traces ============

class TestListTraces:

    @pytest.mark.asyncio
    async def test_success_rows_status_success(self):
        """err_count=0 → status='success'；stage_names 从 3rd 查询聚合。"""
        r1 = _make_row(request_id="req-001", err_count=0)
        r2 = _make_row(request_id="req-002", err_count=0, intent="plan")
        r_total = MagicMock(); r_total.scalar.return_value = 2
        r_rows = MagicMock(); r_rows.all.return_value = [r1, r2]
        r_stages = MagicMock(); r_stages.all.return_value = [
            ("req-001", "intent"),
            ("req-001", "llm"),
            ("req-002", "rag"),
        ]
        session = _multi(r_total, r_rows, r_stages)

        result = await list_traces(_make_admin(), session, days=7, limit=50, offset=0)
        assert result.total == 2
        assert len(result.items) == 2
        for it in result.items:
            assert it.status == "success"
        rid_to_stages = {it.request_id: it.stage_names for it in result.items}
        assert set(rid_to_stages["req-001"]) == {"intent", "llm"}
        assert rid_to_stages["req-002"] == ["rag"]
        assert result.limit == 50
        assert result.offset == 0

    @pytest.mark.asyncio
    async def test_error_row_status_error(self):
        """err_count > 0 → 该条 request_id 显示 status='error'。"""
        r1 = _make_row(request_id="req-err", err_count=2, total_latency=500, total_tokens=300)
        r_total = MagicMock(); r_total.scalar.return_value = 1
        r_rows = MagicMock(); r_rows.all.return_value = [r1]
        r_stages = MagicMock(); r_stages.all.return_value = [("req-err", "llm")]
        session = _multi(r_total, r_rows, r_stages)

        result = await list_traces(_make_admin(), session, days=7, limit=50, offset=0)
        assert result.total == 1
        assert result.items[0].status == "error"
        assert result.items[0].request_id == "req-err"
        assert result.items[0].total_latency_ms == 500
        assert result.items[0].total_tokens == 300

    @pytest.mark.asyncio
    async def test_empty_no_third_query(self):
        """rows 为空时跳过 3rd stage 查询，execute 只被调 2 次。"""
        r_total = MagicMock(); r_total.scalar.return_value = 0
        r_rows = MagicMock(); r_rows.all.return_value = []
        session = _multi(r_total, r_rows)

        result = await list_traces(_make_admin(), session, days=7, limit=50, offset=0)
        assert result.total == 0
        assert result.items == []
        assert session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_status_filter_passes_through(self):
        """status='success' / 'error' 被透传给后端（mock 端只验证调用链）。"""
        r1 = _make_row(request_id="req-ok", err_count=0)
        r_total = MagicMock(); r_total.scalar.return_value = 1
        r_rows = MagicMock(); r_rows.all.return_value = [r1]
        r_stages = MagicMock(); r_stages.all.return_value = [("req-ok", "llm")]
        session = _multi(r_total, r_rows, r_stages)

        result = await list_traces(
            _make_admin(), session, days=7, limit=50, offset=0, status="success",
        )
        assert len(result.items) == 1
        assert result.items[0].status == "success"
        assert session.execute.await_count == 3

    @pytest.mark.asyncio
    async def test_pagination_limit_offset(self):
        """limit / offset 透传到返回体。"""
        r1 = _make_row(request_id="r1")
        r_total = MagicMock(); r_total.scalar.return_value = 100
        r_rows = MagicMock(); r_rows.all.return_value = [r1]
        r_stages = MagicMock(); r_stages.all.return_value = [("r1", "llm")]
        session = _multi(r_total, r_rows, r_stages)

        result = await list_traces(_make_admin(), session, days=7, limit=20, offset=40)
        assert result.limit == 20
        assert result.offset == 40
        assert result.total == 100
        assert len(result.items) == 1


# ============ GET /admin/traces/{request_id} ============

class TestGetTraceDetail:

    @pytest.mark.asyncio
    async def test_all_success_overall_success(self):
        """全部 span status='success' → overall='success'。"""
        spans = [
            _make_span(id=1, stage="intent", status="success", latency_ms=50, total_tokens=20),
            _make_span(id=2, stage="llm", status="success", latency_ms=150, total_tokens=80),
        ]
        session = AsyncMock()
        r = MagicMock(); r.scalars.return_value.all.return_value = spans
        session.execute.return_value = r

        result = await get_trace("req-001", _make_admin(), session)
        assert result.request_id == "req-001"
        assert result.status == "success"
        assert len(result.spans) == 2
        assert result.spans[0].id == 1
        assert result.spans[1].id == 2
        assert result.total_latency_ms == 200
        assert result.total_tokens == 100

    @pytest.mark.asyncio
    async def test_any_error_overall_error(self):
        """任一 span error → overall='error'。"""
        spans = [
            _make_span(id=1, status="success", latency_ms=100, total_tokens=50),
            _make_span(id=2, status="error", latency_ms=50, total_tokens=20,
                       error_message="LLM timeout"),
        ]
        session = AsyncMock()
        r = MagicMock(); r.scalars.return_value.all.return_value = spans
        session.execute.return_value = r

        result = await get_trace("req-err", _make_admin(), session)
        assert result.status == "error"
        assert len(result.spans) == 2
        assert result.total_latency_ms == 150
        assert result.total_tokens == 70
        assert result.spans[1].error_message == "LLM timeout"

    @pytest.mark.asyncio
    async def test_empty_spans_status_success(self):
        """空结果 → status='success'（按规格：空不算 error）。"""
        session = AsyncMock()
        r = MagicMock(); r.scalars.return_value.all.return_value = []
        session.execute.return_value = r

        result = await get_trace("nope", _make_admin(), session)
        assert result.request_id == "nope"
        assert result.status == "success"
        assert result.spans == []
        assert result.total_latency_ms == 0
        assert result.total_tokens == 0
