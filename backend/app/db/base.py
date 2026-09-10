"""SQLAlchemy 声明式基类。

所有模型都从这里继承 `Base`。
alembic 通过 `Base.metadata` 探测模型变更。
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


class TimestampMixin:
    """时间戳混入类：自动管理 created_at / updated_at。

    使用示例：
        class User(Base, TimestampMixin):
            __tablename__ = "users"
            ...
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )