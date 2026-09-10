"""知识库（M10+ RAG 文档问答）。"""
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class KnowledgeBase(Base, TimestampMixin):
    """一个 KB = 一个 Chroma collection（命名 kb_{id}）。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    # 检索配置（KB 级别，可运行时改）
    chunk_size: Mapped[int] = mapped_column(Integer, default=500)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=80)
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    similarity_threshold: Mapped[float] = mapped_column(
        Numeric(4, 3), default=0.0,
        comment="cosine distance 阈值，0 = 不过滤",
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="set null"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase {self.id} {self.name!r} enabled={self.enabled}>"