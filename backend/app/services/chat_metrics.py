"""Chat 流式接口的运行时 metrics（in-memory 进程内计数器）。

为什么不用 ai_call_logs 表：
- 那个表记录历史调用，用于成本分析 / 月度对账
- 这里需要一个**实时**的轻量计数器，看 SSE 当前活跃流数 / 错误率 / P95
- 进程内 ConcurrentDict 即可，O(1) 读写，无 DB 压力

线程安全：asyncio 单线程 → 不需要锁；FastAPI 多 worker → 各自独立（要看全局用 Prometheus / 集中存储）。

暴露字段：
- active_streams         当前活跃 SSE 流数
- total_streams_today    今日累计发起数
- errors_today           今日累计错误数
- avg_latency_ms_today   今日平均首字节延迟（仅 LLM 阶段）
- p95_latency_ms_today   今日 P95 延迟
- by_intent              各 intent 的总调用数
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

IntentStr = Literal["qa", "plan", "substitution", "diet", "unknown"]


@dataclass
class _DailyStats:
    """单日累积（重进程不丢；跨日自动滚动）。"""
    total_streams: int = 0
    errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    by_intent: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_model: dict[str, int] = field(default_factory=lambda: defaultdict(int))


@dataclass
class _ActiveStream:
    """单个活跃 SSE 流追踪。"""
    started_at: float
    user_id: int
    conversation_id: int
    intent: str


class ChatMetrics:
    """进程内 Chat 流式指标聚合器。

    单例：所有 chat 路由共享同一个实例（import 即创建）。
    """

    def __init__(self) -> None:
        self._lock = Lock()  # 跨线程保护（asyncio 不需要，兼用）
        self._day_key: str = self._today_key()
        self._day = _DailyStats()
        self._active: dict[str, _ActiveStream] = {}  # stream_id → info

    # ============ 日滚动 ============

    def _today_key(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def _ensure_day(self) -> None:
        k = self._today_key()
        if self._day_key != k:
            self._day = _DailyStats()
            self._day_key = k

    # ============ SSE 流生命周期 ============

    def stream_started(
        self, *, user_id: int, conversation_id: int, intent: str,
    ) -> str:
        """SSE 连接刚建立时调用。返回 stream_id 用于后续 stop。"""
        self._ensure_day()
        stream_id = f"{user_id}-{conversation_id}-{time.time_ns()}"
        with self._lock:
            self._day.total_streams += 1
            self._day.by_intent[intent] += 1
            self._active[stream_id] = _ActiveStream(
                started_at=time.time(),
                user_id=user_id,
                conversation_id=conversation_id,
                intent=intent,
            )
        return stream_id

    def stream_first_byte(
        self, *, stream_id: str, model: str | None = None,
    ) -> None:
        """记录首字节延迟（LLM 返回第一个 delta 的耗时）。"""
        with self._lock:
            info = self._active.get(stream_id)
            if not info:
                return
            elapsed_ms = (time.time() - info.started_at) * 1000
            self._day.latencies_ms.append(elapsed_ms)
            if model:
                self._day.by_model[model] += 1

    def record_model(self, model: str) -> None:
        """在 done 事件里补录 model 分布（delta 事件不带 model 字段）。"""
        if not model:
            return
        with self._lock:
            self._day.by_model[model] += 1

    def stream_stopped(
        self, *, stream_id: str, error: bool = False,
    ) -> None:
        """SSE 结束（正常 / 异常 / 客户端断开）。"""
        self._ensure_day()
        with self._lock:
            self._active.pop(stream_id, None)
            if error:
                self._day.errors += 1

    # ============ 读视图 ============

    def snapshot(self) -> dict:
        """返回当前指标的快照（dict 形式，B 端直接返回给前端）。"""
        self._ensure_day()
        with self._lock:
            lats = list(self._day.latencies_ms)
            active = [
                {
                    "user_id": s.user_id,
                    "conversation_id": s.conversation_id,
                    "intent": s.intent,
                    "running_seconds": round(time.time() - s.started_at, 1),
                }
                for s in self._active.values()
            ]
            day = self._day
        # 计算 p50 / p95 / avg
        lats_sorted = sorted(lats)
        n = len(lats_sorted)
        if n == 0:
            p50 = p95 = avg = 0.0
        else:
            p50 = lats_sorted[n // 2]
            p95 = lats_sorted[int(n * 0.95)] if n >= 20 else lats_sorted[-1]
            avg = sum(lats_sorted) / n
        return {
            "active_streams": len(active),
            "active_details": active,
            "today": {
                "date": self._day_key,
                "total_streams": day.total_streams,
                "errors": day.errors,
                "error_rate": round(day.errors / day.total_streams, 4) if day.total_streams else 0.0,
                "first_byte_ms": {
                    "samples": n,
                    "avg": round(avg, 1),
                    "p50": round(p50, 1),
                    "p95": round(p95, 1),
                },
                "by_intent": dict(day.by_intent),
                "by_model": dict(day.by_model),
            },
        }


# 全局单例
chat_metrics = ChatMetrics()
