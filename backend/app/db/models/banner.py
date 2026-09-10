"""banners 表（C 端首页公告 Banner）。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Banner(Base, TimestampMixin):
    """C 端首页 Banner 公告。

    - is_active=0 永久下架；=1 且当前时间在 [starts_at, ends_at] 内则展示
    - sort_order 越小越靠前；同序按 id desc
    """

    __tablename__ = "banners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False, comment="Banner 标题")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Banner 正文（短文本）")
    link_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="可选跳转链接")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True, comment="是否启用")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序：越小越靠前")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="生效起始（NULL=不限）")
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="生效结束（NULL=不限）")

    __table_args__ = (
        Index("idx_banners_active_order", "is_active", "sort_order", "id"),
    )