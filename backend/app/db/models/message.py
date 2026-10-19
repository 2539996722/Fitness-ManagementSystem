"""消息表（messages）。

属于某个会话，按时间顺序存储对话内容。
"""

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Message(Base, TimestampMixin):
    """会话内的一条消息。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="cascade"),
        nullable=False, index=True, comment="所属会话",
    )

    # 谁发的
    sender_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="user / ai / trainer"
    )
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="发送者 ID（人工时填）")

    # 内容
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息正文")

    # 元数据
    intent: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="意图：qa/plan/substitute/diet")
    extra: Mapped[dict] = mapped_column(JSON, default=dict, comment="RAG sources、动作引用 等")

    def __repr__(self) -> str:
        return f"<Message {self.id} {self.sender_type}>"