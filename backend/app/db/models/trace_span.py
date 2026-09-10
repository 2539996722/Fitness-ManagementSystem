"""trace_spans（M10+ 全链路追踪）。

每行 = 一次 AI 请求的一个阶段。request_id 跨阶段相同，按其聚合可还原整次调用时间线。
"""
from sqlalchemy import JSON, BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TraceSpan(Base, TimestampMixin):
    """单阶段 span。"""

    __tablename__ = "trace_spans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(32), index=True, comment="X-Request-ID（32 字符 hex）")
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    stage: Mapped[str] = mapped_column(String(32), comment="query_rewrite / intent / tool / rag / llm / output")
    intent: Mapped[str | None] = mapped_column(String(16), comment="qa / plan / substitute / diet")
    status: Mapped[str] = mapped_column(String(16), default="success", comment="success / error")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    input_preview: Mapped[str | None] = mapped_column(Text)
    output_preview: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<TraceSpan {self.stage} rid={self.request_id[:8]}.. {self.latency_ms}ms {self.status}>"