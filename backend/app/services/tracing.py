"""链路 span 写入器（M10+ 全链路追踪）。

用法：
    from app.services.tracing import span

    with span("rag", intent="plan", query=body.content) as s:
        chunks = await retrieve(body.content, top_k=3)
        s.output_preview = f"{len(chunks)} chunks"
        s.meta["chunk_ids"] = [c.id for c in chunks]
        s.tokens = {"prompt": 100, "completion": 50, "total": 150}

特性：
- fire-and-forget：DB 写入在 finally 用 asyncio.create_task 调度，不阻塞主调用链
- 失败降级：DB 写失败仅写日志，不影响用户请求
- 自动关联 request_id（从 ContextVar 取）+ conversation_id + user_id（通过调用方传 ctx）
"""
from contextlib import contextmanager
from time import monotonic
from typing import Any

from loguru import logger

from app.core.tracing import get_request_id
from app.db.models import TraceSpan
from app.db.session import async_session


class _SpanCtx(dict):
    """contextmanager yield 的对象——dict 子类，可写：input_preview / output_preview / meta / tokens。"""

    def __init__(self, rec: dict):
        super().__init__(rec)  # 直接以 rec 作为内部 dict

    # 提供常见属性便捷访问
    @property
    def input_preview(self):
        return self.get("input_preview")

    @input_preview.setter
    def input_preview(self, v):
        self["input_preview"] = v

    @property
    def output_preview(self):
        return self.get("output_preview")

    @output_preview.setter
    def output_preview(self, v):
        self["output_preview"] = v

    @property
    def meta(self) -> dict:
        return self.setdefault("meta", {})

    @property
    def tokens(self) -> dict:
        return self.setdefault("tokens", {})

    @tokens.setter
    def tokens(self, v: dict):
        self["tokens"] = v


@contextmanager
def span(
    stage: str,
    *,
    intent: str | None = None,
    conversation_id: int | None = None,
    user_id: int | None = None,
    **meta: Any,
):
    """阶段计时 + 收集 + 异步写库。"""
    rec: dict = {
        "stage": stage,
        "intent": intent,
        "conversation_id": conversation_id,
        "user_id": user_id,
        "meta": dict(meta),
        "input_preview": None,
        "output_preview": None,
        "tokens": {},
        "status": "success",
        "error_message": None,
    }
    start = monotonic()
    try:
        yield _SpanCtx(rec)
        rec["status"] = "success"
    except Exception as e:
        rec["status"] = "error"
        rec["error_message"] = str(e)[:500]
        raise
    finally:
        latency_ms = int((monotonic() - start) * 1000)
        _fire_and_forget_write(rec, latency_ms)


def _fire_and_forget_write(rec: dict, latency_ms: int) -> None:
    """调度一个协程异步写库；不在请求里就跳过。"""
    rid = get_request_id()
    if not rid:
        return
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    loop.create_task(_write_span(rid, rec, latency_ms))


async def _write_span(rid: str, rec: dict, latency_ms: int) -> None:
    """实际写库；失败仅日志告警。"""
    tokens = rec.get("tokens") or {}
    payload = {
        "request_id": rid,
        "stage": rec["stage"],
        "intent": rec.get("intent"),
        "status": rec["status"],
        "latency_ms": latency_ms,
        "prompt_tokens": int(tokens.get("prompt", 0)),
        "completion_tokens": int(tokens.get("completion", 0)),
        "total_tokens": int(tokens.get("total", 0)),
        "input_preview": (rec.get("input_preview") or "")[:200],
        "output_preview": (rec.get("output_preview") or "")[:200],
        "meta": rec.get("meta"),
        "error_message": rec.get("error_message"),
        "conversation_id": rec.get("conversation_id"),
        "user_id": rec.get("user_id"),
    }
    try:
        async with async_session() as s:
            row = TraceSpan(**payload)
            s.add(row)
            await s.commit()
    except Exception as e:
        logger.warning(f"trace span 写入失败：stage={rec['stage']} err={e}")