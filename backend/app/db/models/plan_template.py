"""计划模板表（plan_templates）。

教练创建的预设训练计划；C 端用户在"模板市场"看到已发布模板，
点击"采用"后系统把 weeks 复制成一份普通 plan 给该用户。

状态机：
    draft ──submit──> pending_review ──approve──> published
       ↑                                            │
       └──────────────── offline ────────offline────┘
                       (admin 强下架，可 republish)
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


# 状态常量（避免字符串拼写错误）
STATUS_DRAFT = "draft"
STATUS_PENDING = "pending_review"
STATUS_PUBLISHED = "published"
STATUS_OFFLINE = "offline"

ALL_STATUSES = (STATUS_DRAFT, STATUS_PENDING, STATUS_PUBLISHED, STATUS_OFFLINE)


class PlanTemplate(Base, TimestampMixin):
    """计划模板。"""

    __tablename__ = "plan_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="模板名")
    goal: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="muscle_gain / fat_loss / body_shape / endurance",
    )
    level: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="beginner / intermediate / advanced",
    )
    cover_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    weeks: Mapped[list] = mapped_column(JSON, nullable=False, default=list, comment="周训练结构")

    author_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="cascade"),
        nullable=False,
        index=True,
        comment="创建者（教练）ID",
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=STATUS_DRAFT,
        index=True,
        comment="draft / pending_review / published / offline",
    )

    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<PlanTemplate {self.id} {self.name} ({self.status})>"