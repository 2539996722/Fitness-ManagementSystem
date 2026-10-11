"""chat_metrics 单测（进程内计数器，O(1)）。"""
from __future__ import annotations

import time

import pytest

from app.services.chat_metrics import ChatMetrics, chat_metrics


@pytest.fixture
def fresh_metrics():
    """每次拿一个独立的实例，避免污染全局单例。"""
    return ChatMetrics()


class TestStreamLifecycle:
    """SSE 流生命周期：start → first_byte → stop。"""

    def test_stream_started_increments_total(self, fresh_metrics):
        sid = fresh_metrics.stream_started(
            user_id=1, conversation_id=100, intent="qa",
        )
        snap = fresh_metrics.snapshot()
        assert snap["active_streams"] == 1
        assert snap["today"]["total_streams"] == 1
        assert snap["today"]["by_intent"]["qa"] == 1

    def test_stream_started_returns_unique_id(self, fresh_metrics):
        sids = [
            fresh_metrics.stream_started(user_id=i, conversation_id=i, intent="qa")
            for i in range(10)
        ]
        assert len(set(sids)) == 10  # 全部唯一

    def test_stream_stopped_decrements_active(self, fresh_metrics):
        sid = fresh_metrics.stream_started(
            user_id=1, conversation_id=100, intent="qa",
        )
        fresh_metrics.stream_stopped(stream_id=sid)
        snap = fresh_metrics.snapshot()
        assert snap["active_streams"] == 0
        assert snap["today"]["total_streams"] == 1  # 总数不减
        assert snap["today"]["errors"] == 0

    def test_stream_stopped_with_error_increments_errors(self, fresh_metrics):
        sid = fresh_metrics.stream_started(
            user_id=1, conversation_id=100, intent="qa",
        )
        fresh_metrics.stream_stopped(stream_id=sid, error=True)
        snap = fresh_metrics.snapshot()
        assert snap["today"]["errors"] == 1
        assert snap["today"]["error_rate"] == 1.0

    def test_stream_first_byte_records_latency(self, fresh_metrics):
        sid = fresh_metrics.stream_started(
            user_id=1, conversation_id=100, intent="qa",
        )
        time.sleep(0.05)  # 50ms
        fresh_metrics.stream_first_byte(stream_id=sid, model="gpt-4o-mini")
        snap = fresh_metrics.snapshot()
        # 至少 50ms 延迟（实际会稍多一些）
        assert snap["today"]["first_byte_ms"]["samples"] == 1
        assert snap["today"]["first_byte_ms"]["avg"] >= 50
        assert snap["today"]["by_model"]["gpt-4o-mini"] == 1

    def test_record_model_supplements_delta(self, fresh_metrics):
        """done 事件里能补录 model 分布。"""
        fresh_metrics.record_model("deepseek-chat")
        fresh_metrics.record_model("deepseek-chat")
        snap = fresh_metrics.snapshot()
        assert snap["today"]["by_model"]["deepseek-chat"] == 2

    def test_stream_first_byte_unknown_id_is_noop(self, fresh_metrics):
        """stream_stopped / stream_first_byte 用错误 id 不应崩。"""
        fresh_metrics.stream_first_byte(stream_id="bogus")  # 不抛
        fresh_metrics.stream_stopped(stream_id="bogus")    # 不抛
        snap = fresh_metrics.snapshot()
        assert snap["active_streams"] == 0


class TestMultiIntentAndDay:

    def test_by_intent_separated(self, fresh_metrics):
        for _ in range(3):
            sid = fresh_metrics.stream_started(
                user_id=1, conversation_id=1, intent="qa",
            )
            fresh_metrics.stream_stopped(stream_id=sid)
        for _ in range(2):
            sid = fresh_metrics.stream_started(
                user_id=1, conversation_id=1, intent="plan",
            )
            fresh_metrics.stream_stopped(stream_id=sid)

        snap = fresh_metrics.snapshot()
        assert snap["today"]["by_intent"]["qa"] == 3
        assert snap["today"]["by_intent"]["plan"] == 2
        assert snap["today"]["total_streams"] == 5
        assert snap["today"]["error_rate"] == 0.0

    def test_multiple_active_concurrent(self, fresh_metrics):
        sids = [
            fresh_metrics.stream_started(
                user_id=i, conversation_id=i, intent="qa",
            )
            for i in range(5)
        ]
        snap = fresh_metrics.snapshot()
        assert snap["active_streams"] == 5
        # 中途停 2 个
        fresh_metrics.stream_stopped(stream_id=sids[0])
        fresh_metrics.stream_stopped(stream_id=sids[1])
        snap = fresh_metrics.snapshot()
        assert snap["active_streams"] == 3
        assert snap["today"]["total_streams"] == 5  # 历史累积不变


class TestPercentiles:

    def test_p50_and_p95_with_many_samples(self, fresh_metrics):
        # 注入 100 个样本，固定 latency
        for _ in range(100):
            sid = fresh_metrics.stream_started(
                user_id=1, conversation_id=1, intent="qa",
            )
            fresh_metrics.stream_first_byte(stream_id=sid)
            fresh_metrics.stream_stopped(stream_id=sid)

        snap = fresh_metrics.snapshot()
        assert snap["today"]["first_byte_ms"]["samples"] == 100
        # samples 都很小（<10ms），p50/p95 都接近 0 但 ≥0
        assert snap["today"]["first_byte_ms"]["p50"] >= 0
        assert snap["today"]["first_byte_ms"]["p95"] >= 0
        assert snap["today"]["first_byte_ms"]["avg"] >= 0

    def test_empty_state(self, fresh_metrics):
        snap = fresh_metrics.snapshot()
        assert snap["active_streams"] == 0
        assert snap["today"]["total_streams"] == 0
        assert snap["today"]["errors"] == 0
        assert snap["today"]["error_rate"] == 0.0
        assert snap["today"]["first_byte_ms"]["samples"] == 0
        assert snap["today"]["first_byte_ms"]["avg"] == 0.0


class TestGlobalSingleton:
    """进程内单例：每次测试不应污染全局（仅验证 import 能拿到对象）。"""

    def test_singleton_exists(self):
        assert chat_metrics is not None
        assert isinstance(chat_metrics, ChatMetrics)
