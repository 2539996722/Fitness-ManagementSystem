"""训练计划表（plans）。

每个 plan 包含 weeks 字段，存储完整的周训练结构（JSON）。
"""

from sqlalchemy import JSON, BigInteger, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Plan(Base, TimestampMixin):
    """用户训练计划。"""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 所属用户
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        comment="所属用户 ID（FK -> users.id）",
    )

    # 计划基本信息
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="计划名称")
    goal: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
        comment="目标：muscle_gain / fat_loss / body_shape / endurance",
    )

    # 周训练结构（JSON，详见 PRD §8.3）
    weeks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, comment="周训练结构")

    # 当前计划标记
    is_current: Mapped[int] = mapped_column(
        SmallInteger,
        default=0,
        nullable=False,
        comment="0 否 1 是（同一用户同时只能有一个 current）",
    )

    # 训练元数据
    days_per_week: Mapped[int] = mapped_column(SmallInteger, default=3, comment="每周训练天数")
    equipment: Mapped[list] = mapped_column(JSON, default=list, comment="可用器械列表")

    def __repr__(self) -> str:
        return f"<Plan {self.id} {self.name} ({self.goal})>"