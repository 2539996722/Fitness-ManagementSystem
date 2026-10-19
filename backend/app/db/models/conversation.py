"""会话表（conversations）。

每个会话对应用户和 AI（或人工）的一轮完整对话。
"""

from sqlalchemy import JSON, BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    """用户会话。"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="cascade"),
        nullable=False, index=True, comment="所属用户",
    )

    # 会话元数据
    title: Mapped[str] = mapped_column(String(64), default="新会话", comment="会话标题")
    conversation_type: Mapped[str] = mapped_column(
        String(16), default="ai", comment="ai / trainer"
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(16), default="ai_active", comment="ai_active / waiting_human / human_active / waiting_trainer / trainer_active / closed"
    )

    # 当前人工接管者 ID（兼容历史客服接管；统一指向 assigned_trainer_id 字段）
    assigned_cs_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 当前教练 ID（如果转教练后被接管）
    assigned_trainer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="set null"), nullable=True, index=True,
        comment="当前教练 ID",
    )

    # RAG 检索到的源文档（可选）
    rag_sources: Mapped[list] = mapped_column(JSON, default=list, comment="RAG 检索时命中的文档 chunk IDs")

    def __repr__(self) -> str:
        return f"<Conversation {self.id} {self.title} ({self.status})>"