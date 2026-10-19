"""ai_call_logs（LLM 调用审计表，PRD §6.5 / §8.11）。

记录每次 LLM 调用的 user / 意图 / 模型 / token / 成本 / 延迟 / 状态 / 错误。
"""

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AiCallLog(Base, TimestampMixin):
    """LLM 调用日志（异步写入；落库失败不影响主流程）。"""

    __tablename__ = "ai_call_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="set null"),
        nullable=True, index=True, comment="调用者用户 ID（系统任务为 NULL）",
    )
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="set null"),
        nullable=True, index=True, comment="所属会话 ID",
    )
    intent: Mapped[str | None] = mapped_column(
        String(16), nullable=True, index=True, comment="调用意图：qa / plan / substitute / diet",
    )
    model: Mapped[str | None] = mapped_column(String(64), comment="实际使用的模型名")
    prompt_tokens: Mapped[int | None] = mapped_column(default=0, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(default=0, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(default=0, nullable=True)
    cost_cny: Mapped[float | None] = mapped_column(Numeric(10, 6), default=0, nullable=True, comment="估算成本（元）")
    latency_ms: Mapped[int | None] = mapped_column(default=0, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="success", comment="success / error / timeout")
    error_message: Mapped[str | None] = mapped_column(Text, comment="失败时的错误信息")
    prompt_preview: Mapped[str | None] = mapped_column(Text, comment="prompt 摘要（截断 200 字）")
    response_preview: Mapped[str | None] = mapped_column(Text, comment="响应摘要（截断 200 字）")
    call_type: Mapped[str] = mapped_column(
        String(16), default="chat", server_default="chat",
        comment="chat / embedding",
    )
